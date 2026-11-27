// SPDX-License-Identifier: GPL-2.0-only
// claudegg-wiiu-bridge
//
// Runs on a Raspberry Pi (or another Linux machine) next to vanilla-pipe and
// acts as the Wii U GamePad for ClaudeGG:
//
//   ClaudeGG (Windows) --TCP commands--> bridge --libvanilla--> vanilla-pipe --5 GHz Wi-Fi--> Wii U
//   ClaudeGG (Windows) <--H.264 video--- bridge <--------------------------------------------- Wii U
//
// Command port (default 51200): one ASCII command per line, see README.md.
// Video port   (default 51201): raw Annex-B H.264 of the GamePad screen
//                               (854x480). Each client starts at a keyframe.
//
// This program links Vanilla's library, which is GPL-2.0, so this program is
// GPL-2.0 as well. ClaudeGG only talks to it over sockets.

#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <arpa/inet.h>
#include <unistd.h>

#include <vanilla.h>

#define MAX_CLIENTS 8
#define LINE_MAX_LEN 256

enum BridgeState { STATE_IDLE, STATE_SYNCING, STATE_CONNECTED };

typedef struct {
    int fd;
    char buf[LINE_MAX_LEN];
    size_t len;
} cmd_client_t;

typedef struct {
    int fd;
    int waiting_for_idr;
} video_client_t;

static cmd_client_t cmd_clients[MAX_CLIENTS];
static video_client_t video_clients[MAX_CLIENTS];
static int state = STATE_IDLE;
static int got_first_frame = 0;
static int verbose = 0;
static char console_path[512];
static volatile sig_atomic_t quit_requested = 0;

// ---------------------------------------------------------------------------
// Names

typedef struct { const char *name; int id; } name_map_t;

static const name_map_t BUTTONS[] = {
    {"A", VANILLA_BTN_A}, {"B", VANILLA_BTN_B}, {"X", VANILLA_BTN_X}, {"Y", VANILLA_BTN_Y},
    {"L", VANILLA_BTN_L}, {"R", VANILLA_BTN_R}, {"ZL", VANILLA_BTN_ZL}, {"ZR", VANILLA_BTN_ZR},
    {"MINUS", VANILLA_BTN_MINUS}, {"PLUS", VANILLA_BTN_PLUS}, {"HOME", VANILLA_BTN_HOME},
    {"TV", VANILLA_BTN_TV}, {"L3", VANILLA_BTN_L3}, {"R3", VANILLA_BTN_R3},
    {"LEFT", VANILLA_BTN_LEFT}, {"RIGHT", VANILLA_BTN_RIGHT},
    {"DOWN", VANILLA_BTN_DOWN}, {"UP", VANILLA_BTN_UP},
    {0, 0}
};

// Same convention as SDL: -32768..32767, negative Y = up.
static const name_map_t AXES[] = {
    {"LX", VANILLA_AXIS_L_X}, {"LY", VANILLA_AXIS_L_Y},
    {"RX", VANILLA_AXIS_R_X}, {"RY", VANILLA_AXIS_R_Y},
    {0, 0}
};

static const name_map_t REGIONS[] = {
    {"JPN", VANILLA_REGION_JAPAN}, {"USA", VANILLA_REGION_AMERICA},
    {"EUR", VANILLA_REGION_EUROPE}, {"CHN", VANILLA_REGION_CHINA},
    {"KOR", VANILLA_REGION_SOUTH_KOREA}, {"TWN", VANILLA_REGION_TAIWAN},
    {"AUS", VANILLA_REGION_AUSTRALIA},
    {0, 0}
};

static int lookup(const name_map_t *map, const char *name)
{
    for (int i = 0; map[i].name; i++) {
        if (!strcasecmp(map[i].name, name)) return map[i].id;
    }
    return -1;
}

// ---------------------------------------------------------------------------
// Output to command clients

static void send_line(int fd, const char *fmt, ...)
{
    char line[LINE_MAX_LEN];
    va_list va;
    va_start(va, fmt);
    int n = vsnprintf(line, sizeof(line) - 1, fmt, va);
    va_end(va);
    if (n < 0) return;
    if (n > (int) sizeof(line) - 2) n = sizeof(line) - 2;
    line[n++] = '\n';
    // Command clients are blocking sockets; lines are tiny.
    if (send(fd, line, n, MSG_NOSIGNAL) < 0 && verbose) {
        fprintf(stderr, "send to command client failed: %s\n", strerror(errno));
    }
}

static void broadcast(const char *fmt, ...)
{
    char line[LINE_MAX_LEN];
    va_list va;
    va_start(va, fmt);
    vsnprintf(line, sizeof(line), fmt, va);
    va_end(va);
    fprintf(stderr, "%s\n", line);
    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (cmd_clients[i].fd >= 0) send_line(cmd_clients[i].fd, "%s", line);
    }
}

static void vanilla_logger(const char *fmt, va_list args)
{
    if (verbose) vfprintf(stderr, fmt, args);
}

// ---------------------------------------------------------------------------
// Saved console (BSSID + PSK, written after a successful SYNC)

static int load_console(vanilla_connection_t *out)
{
    FILE *f = fopen(console_path, "rb");
    if (!f) return 0;
    size_t n = fread(out, 1, sizeof(*out), f);
    fclose(f);
    return n == sizeof(*out);
}

static int save_console(const vanilla_connection_t *c)
{
    char dir[512];
    snprintf(dir, sizeof(dir), "%s", console_path);
    char *slash = strrchr(dir, '/');
    if (slash) {
        *slash = 0;
        mkdir(dir, 0700);
    }
    FILE *f = fopen(console_path, "wb");
    if (!f) return 0;
    size_t n = fwrite(c, 1, sizeof(*c), f);
    fclose(f);
    chmod(console_path, 0600);
    return n == sizeof(*c);
}

static int has_console(void)
{
    vanilla_connection_t c;
    return load_console(&c);
}

// ---------------------------------------------------------------------------
// Input

static void release_all(void)
{
    for (int i = 0; BUTTONS[i].name; i++) vanilla_set_button(BUTTONS[i].id, 0);
    for (int i = 0; AXES[i].name; i++) vanilla_set_button(AXES[i].id, 0);
    vanilla_set_touch(-1, -1);
}

// Sync code: the 4 symbols the Wii U shows, as letters
// S(pade) H(eart) D(iamond) C(lub), or as digits 0-3 in that order.
static int parse_sync_code(const char *s, uint16_t *code)
{
    if (strlen(s) != 4) return 0;
    uint16_t v = 0;
    for (int i = 0; i < 4; i++) {
        int d;
        switch (s[i]) {
        case 'S': case 's': case '0': d = 0; break;
        case 'H': case 'h': case '1': d = 1; break;
        case 'D': case 'd': case '2': d = 2; break;
        case 'C': case 'c': case '3': d = 3; break;
        default: return 0;
        }
        v = v * 10 + d;
    }
    *code = v;
    return 1;
}

static void stop_vanilla(void)
{
    if (state != STATE_IDLE) {
        release_all();
        vanilla_stop();
        state = STATE_IDLE;
        got_first_frame = 0;
    }
}

// ---------------------------------------------------------------------------
// Commands

static const char *state_name(void)
{
    switch (state) {
    case STATE_SYNCING: return "syncing";
    case STATE_CONNECTED: return "connected";
    default: return "idle";
    }
}

static void handle_command(int fd, char *line)
{
    char *argv[4] = {0};
    int argc = 0;
    for (char *tok = strtok(line, " \t\r"); tok && argc < 4; tok = strtok(NULL, " \t\r")) {
        argv[argc++] = tok;
    }
    if (argc == 0) return;
    const char *cmd = argv[0];

    if (!strcasecmp(cmd, "PING")) {
        send_line(fd, "OK PONG");
    } else if (!strcasecmp(cmd, "STATUS")) {
        send_line(fd, "OK STATE %s CONSOLE %s", state_name(), has_console() ? "yes" : "no");
    } else if (!strcasecmp(cmd, "BTN") && argc == 3) {
        int id = lookup(BUTTONS, argv[1]);
        if (id < 0) { send_line(fd, "ERR unknown button %s", argv[1]); return; }
        vanilla_set_button(id, atoi(argv[2]) ? INT16_MAX : 0);
        send_line(fd, "OK");
    } else if (!strcasecmp(cmd, "AXIS") && argc == 3) {
        int id = lookup(AXES, argv[1]);
        if (id < 0) { send_line(fd, "ERR unknown axis %s", argv[1]); return; }
        long v = strtol(argv[2], NULL, 10);
        if (v < -32768) v = -32768;
        if (v > 32767) v = 32767;
        vanilla_set_button(id, (int32_t) v);
        send_line(fd, "OK");
    } else if (!strcasecmp(cmd, "TOUCH") && argc == 2 && !strcasecmp(argv[1], "OFF")) {
        vanilla_set_touch(-1, -1);
        send_line(fd, "OK");
    } else if (!strcasecmp(cmd, "TOUCH") && argc == 3) {
        int x = atoi(argv[1]), y = atoi(argv[2]);
        if (x < 0 || x > 853 || y < 0 || y > 479) { send_line(fd, "ERR touch must be 0..853 0..479"); return; }
        vanilla_set_touch(x, y);
        send_line(fd, "OK");
    } else if (!strcasecmp(cmd, "RELEASE")) {
        release_all();
        send_line(fd, "OK");
    } else if (!strcasecmp(cmd, "IDR")) {
        vanilla_request_idr();
        send_line(fd, "OK");
    } else if (!strcasecmp(cmd, "SYNC") && argc == 2) {
        uint16_t code;
        if (!parse_sync_code(argv[1], &code)) { send_line(fd, "ERR sync code is 4 of S,H,D,C (spade, heart, diamond, club)"); return; }
        stop_vanilla();
        int r = vanilla_sync(code, VANILLA_ADDRESS_LOCAL);
        if (r != VANILLA_SUCCESS) { send_line(fd, "ERR sync failed to start (%d)", r); return; }
        state = STATE_SYNCING;
        send_line(fd, "OK SYNCING");
    } else if (!strcasecmp(cmd, "CONNECT")) {
        vanilla_connection_t c;
        if (!load_console(&c)) { send_line(fd, "ERR no console saved, SYNC first"); return; }
        stop_vanilla();
        int r = vanilla_start(VANILLA_ADDRESS_LOCAL, c.bssid, c.psk);
        if (r != VANILLA_SUCCESS) { send_line(fd, "ERR connect failed to start (%d)", r); return; }
        state = STATE_CONNECTED;
        got_first_frame = 0;
        send_line(fd, "OK CONNECTING");
    } else if (!strcasecmp(cmd, "DISCONNECT")) {
        stop_vanilla();
        send_line(fd, "OK");
    } else {
        send_line(fd, "ERR unknown command");
    }
}

// ---------------------------------------------------------------------------
// Video

static int is_keyframe(const uint8_t *data, size_t size)
{
    // Vanilla puts SPS (NAL type 7) first on every IDR frame.
    return size > 4 && memcmp(data, "\x00\x00\x00\x01", 4) == 0 && (data[4] & 0x1F) == 7;
}

static void close_video_client(int i)
{
    close(video_clients[i].fd);
    video_clients[i].fd = -1;
}

static void send_video(const uint8_t *data, size_t size)
{
    int key = is_keyframe(data, size);
    for (int i = 0; i < MAX_CLIENTS; i++) {
        video_client_t *vc = &video_clients[i];
        if (vc->fd < 0) continue;
        if (vc->waiting_for_idr) {
            if (!key) continue;
            vc->waiting_for_idr = 0;
        }
        size_t off = 0;
        while (off < size) {
            ssize_t n = send(vc->fd, data + off, size - off, MSG_NOSIGNAL | MSG_DONTWAIT);
            if (n > 0) { off += n; continue; }
            if (n < 0 && errno == EINTR) continue;
            break;
        }
        if (off < size) {
            // Too slow (or gone). A half-sent frame breaks the stream, so drop it.
            fprintf(stderr, "video client too slow or closed, dropping it\n");
            close_video_client(i);
        }
    }
}

static void handle_vanilla_events(void)
{
    if (state == STATE_IDLE) return;

    vanilla_event_t ev;
    while (state != STATE_IDLE && vanilla_poll_event(&ev)) {
        switch (ev.type) {
        case VANILLA_EVENT_VIDEO:
            if (!got_first_frame) {
                got_first_frame = 1;
                broadcast("EVENT CONNECTED");
            }
            send_video(ev.data, ev.size);
            break;
        case VANILLA_EVENT_SYNC: {
            vanilla_sync_event_t *s = (vanilla_sync_event_t *) ev.data;
            int ok = save_console(&s->data);
            vanilla_free_event(&ev);
            stop_vanilla();
            if (ok) broadcast("EVENT SYNCED");
            else broadcast("EVENT ERROR could not save console to %s", console_path);
            continue;
        }
        case VANILLA_EVENT_ERROR: {
            int err = ev.data ? *(int *) ev.data : 0;
            vanilla_free_event(&ev);
            stop_vanilla();
            broadcast("EVENT ERROR %d", err);
            continue;
        }
        default:
            // Audio, vibration, mic and brightness are not used by ClaudeGG yet.
            break;
        }
        vanilla_free_event(&ev);
    }
}

// ---------------------------------------------------------------------------
// Sockets

static int listen_on(const char *bind_addr, int port)
{
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) { perror("socket"); return -1; }
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in a = {0};
    a.sin_family = AF_INET;
    a.sin_port = htons(port);
    if (inet_pton(AF_INET, bind_addr, &a.sin_addr) != 1) {
        fprintf(stderr, "bad bind address %s\n", bind_addr);
        close(fd);
        return -1;
    }
    if (bind(fd, (struct sockaddr *) &a, sizeof(a)) < 0 || listen(fd, 4) < 0) {
        fprintf(stderr, "cannot listen on %s:%d: %s\n", bind_addr, port, strerror(errno));
        close(fd);
        return -1;
    }
    return fd;
}

static void accept_cmd_client(int lfd)
{
    int fd = accept(lfd, NULL, NULL);
    if (fd < 0) return;
    int one = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (cmd_clients[i].fd < 0) {
            cmd_clients[i].fd = fd;
            cmd_clients[i].len = 0;
            send_line(fd, "HELLO claudegg-wiiu-bridge 1");
            return;
        }
    }
    send_line(fd, "ERR too many clients");
    close(fd);
}

static void accept_video_client(int lfd)
{
    int fd = accept(lfd, NULL, NULL);
    if (fd < 0) return;
    int one = 1, sndbuf = 1 << 20;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
    setsockopt(fd, SOL_SOCKET, SO_SNDBUF, &sndbuf, sizeof(sndbuf));
    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (video_clients[i].fd < 0) {
            video_clients[i].fd = fd;
            video_clients[i].waiting_for_idr = 1;
            if (state == STATE_CONNECTED) vanilla_request_idr();
            return;
        }
    }
    close(fd);
}

static void read_cmd_client(int i)
{
    cmd_client_t *c = &cmd_clients[i];
    char tmp[LINE_MAX_LEN];
    ssize_t n = recv(c->fd, tmp, sizeof(tmp), 0);
    if (n <= 0) {
        close(c->fd);
        c->fd = -1;
        return;
    }
    for (ssize_t k = 0; k < n; k++) {
        char ch = tmp[k];
        if (ch == '\n') {
            c->buf[c->len] = 0;
            handle_command(c->fd, c->buf);
            c->len = 0;
            if (c->fd < 0) return;
        } else if (c->len < sizeof(c->buf) - 1) {
            c->buf[c->len++] = ch;
        }
    }
}

static void on_signal(int sig)
{
    (void) sig;
    quit_requested = 1;
}

static void usage(const char *argv0)
{
    fprintf(stderr,
        "Usage: %s [options]\n"
        "  --bind <ip>         address to listen on (default 0.0.0.0)\n"
        "  --cmd-port <port>   command port (default 51200)\n"
        "  --video-port <port> H.264 video port (default 51201)\n"
        "  --region <r>        GamePad region: EUR USA JPN AUS KOR CHN TWN (default EUR)\n"
        "  --console <file>    where the synced console is stored\n"
        "                      (default ~/.config/claudegg-wiiu/console.bin)\n"
        "  --verbose           print Vanilla's log\n"
        "Run 'sudo vanilla-pipe -local <wifi-interface>' first.\n", argv0);
}

int main(int argc, char **argv)
{
    const char *bind_addr = "0.0.0.0";
    int cmd_port = 51200, video_port = 51201;
    int region = VANILLA_REGION_EUROPE;

    const char *home = getenv("HOME");
    snprintf(console_path, sizeof(console_path), "%s/.config/claudegg-wiiu/console.bin", home ? home : ".");

    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        const char *next = (i + 1 < argc) ? argv[i + 1] : NULL;
        if (!strcmp(a, "--bind") && next) { bind_addr = next; i++; }
        else if (!strcmp(a, "--cmd-port") && next) { cmd_port = atoi(next); i++; }
        else if (!strcmp(a, "--video-port") && next) { video_port = atoi(next); i++; }
        else if (!strcmp(a, "--region") && next) {
            region = lookup(REGIONS, next);
            if (region < 0) { usage(argv[0]); return 1; }
            i++;
        }
        else if (!strcmp(a, "--console") && next) { snprintf(console_path, sizeof(console_path), "%s", next); i++; }
        else if (!strcmp(a, "--verbose")) { verbose = 1; }
        else { usage(argv[0]); return 1; }
    }

    for (int i = 0; i < MAX_CLIENTS; i++) {
        cmd_clients[i].fd = -1;
        video_clients[i].fd = -1;
    }

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    signal(SIGPIPE, SIG_IGN);

    vanilla_install_logger(vanilla_logger);
    vanilla_set_region(region);
    vanilla_set_battery_status(VANILLA_BATTERY_STATUS_FULL);

    int cmd_lfd = listen_on(bind_addr, cmd_port);
    int vid_lfd = listen_on(bind_addr, video_port);
    if (cmd_lfd < 0 || vid_lfd < 0) return 1;

    fprintf(stderr, "claudegg-wiiu-bridge: commands on %s:%d, video on %s:%d, console file %s\n",
        bind_addr, cmd_port, bind_addr, video_port, console_path);

    while (!quit_requested) {
        struct pollfd pfds[2 + MAX_CLIENTS];
        int idx[2 + MAX_CLIENTS];
        int n = 0;
        pfds[n].fd = cmd_lfd; pfds[n].events = POLLIN; idx[n++] = -1;
        pfds[n].fd = vid_lfd; pfds[n].events = POLLIN; idx[n++] = -2;
        for (int i = 0; i < MAX_CLIENTS; i++) {
            if (cmd_clients[i].fd >= 0) {
                pfds[n].fd = cmd_clients[i].fd; pfds[n].events = POLLIN; idx[n++] = i;
            }
        }

        // Short timeout so video frames from Vanilla go out quickly.
        int r = poll(pfds, n, state == STATE_IDLE ? 100 : 2);
        if (r < 0 && errno != EINTR) { perror("poll"); break; }

        for (int k = 0; r > 0 && k < n; k++) {
            if (!(pfds[k].revents & (POLLIN | POLLHUP | POLLERR))) continue;
            if (idx[k] == -1) accept_cmd_client(cmd_lfd);
            else if (idx[k] == -2) accept_video_client(vid_lfd);
            else read_cmd_client(idx[k]);
        }

        handle_vanilla_events();
    }

    fprintf(stderr, "shutting down\n");
    stop_vanilla();
    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (cmd_clients[i].fd >= 0) close(cmd_clients[i].fd);
        if (video_clients[i].fd >= 0) close(video_clients[i].fd);
    }
    close(cmd_lfd);
    close(vid_lfd);
    return 0;
}
