// SPDX-License-Identifier: GPL-2.0-only
// claudegg-wiiu-bridge
//
// Runs on a Raspberry Pi (or another Linux machine) next to vanilla-pipe and
// acts as the Wii U GamePad for ClaudeGG:
//
//   ClaudeGG (Windows) --TCP commands--> bridge --libvanilla--> vanilla-pipe --5 GHz Wi-Fi--> Wii U
//   ClaudeGG (Windows) <--JPEG pictures-- bridge <--------------------------------------------- Wii U
//
// Command port (default 51200): one ASCII command per line, see README.md.
// Video port   (default 51201): raw Annex-B H.264 of the GamePad screen
//                               (854x480). Each client starts at a keyframe.
// HTTP port    (default 51202): GET /v1/video gives the GamePad screen as JPEG
//                               pictures (multipart/x-mixed-replace, boundary
//                               "frame"), the same stream as the agent of
//                               ClaudeGG's Mobile/, so ClaudeGG reads it the
//                               same way. Decoded by an ffmpeg child process.
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
#include <sys/types.h>
#include <sys/uio.h>
#include <sys/wait.h>
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

typedef struct {
    int fd;
    char buf[1024];
    size_t len;
    int streaming;      // answered with the multipart header, gets pictures
} http_client_t;

static cmd_client_t cmd_clients[MAX_CLIENTS];
static video_client_t video_clients[MAX_CLIENTS];
static http_client_t http_clients[MAX_CLIENTS];
static int jpeg_fps = 10;
static int jpeg_quality = 5;  // ffmpeg -q:v, 2 (best) to 31
static int state = STATE_IDLE;
static int got_first_frame = 0;
static int verbose = 0;
static char console_path[512];
static volatile sig_atomic_t quit_requested = 0;
// --test-h264: plays a file of raw H.264 as if it came from the Wii U, to try
// the picture path (ffmpeg, HTTP) without a console.
static FILE *test_h264 = NULL;

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

static void close_all_http_clients(void);

static void stop_vanilla(void)
{
    if (state != STATE_IDLE) {
        close_all_http_clients();
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

// ---------------------------------------------------------------------------
// JPEG pictures for HTTP clients: H.264 in, through ffmpeg, JPEG out.

static pid_t decoder_pid = -1;
static int decoder_in = -1;          // H.264 to ffmpeg
static int decoder_out = -1;         // MJPEG from ffmpeg
static int decoder_need_key = 1;     // feed only from a keyframe on
static uint8_t *jpeg_buf = NULL;
static size_t jpeg_len = 0, jpeg_cap = 0;

static int streaming_http_clients(void)
{
    int n = 0;
    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (http_clients[i].fd >= 0 && http_clients[i].streaming) n++;
    }
    return n;
}

static void stop_decoder(void)
{
    if (decoder_pid < 0) return;
    if (decoder_in >= 0) close(decoder_in);
    if (decoder_out >= 0) close(decoder_out);
    decoder_in = decoder_out = -1;
    kill(decoder_pid, SIGTERM);
    waitpid(decoder_pid, NULL, 0);
    decoder_pid = -1;
    jpeg_len = 0;
}

static int start_decoder(void)
{
    int in_pipe[2], out_pipe[2];
    if (pipe(in_pipe) < 0) return 0;
    if (pipe(out_pipe) < 0) {
        close(in_pipe[0]);
        close(in_pipe[1]);
        return 0;
    }
    char fps[16], quality[16];
    snprintf(fps, sizeof(fps), "fps=%d", jpeg_fps);
    snprintf(quality, sizeof(quality), "%d", jpeg_quality);

    pid_t pid = fork();
    if (pid < 0) {
        close(in_pipe[0]); close(in_pipe[1]); close(out_pipe[0]); close(out_pipe[1]);
        return 0;
    }
    if (pid == 0) {
        dup2(in_pipe[0], 0);
        dup2(out_pipe[1], 1);
        for (int fd = 3; fd < 1024; fd++) close(fd);
        // The GamePad stream runs at about 60 frames a second; raw H.264 has
        // no timestamps, so say so, or the fps filter counts wrong.
        execlp("ffmpeg", "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-fflags", "nobuffer", "-flags", "low_delay",
            "-framerate", "60", "-f", "h264", "-i", "pipe:0",
            "-vf", fps, "-q:v", quality, "-f", "image2pipe", "-c:v", "mjpeg", "pipe:1",
            (char *) NULL);
        _exit(127);
    }
    close(in_pipe[0]);
    close(out_pipe[1]);
    decoder_in = in_pipe[1];
    decoder_out = out_pipe[0];
    fcntl(decoder_in, F_SETFL, fcntl(decoder_in, F_GETFL) | O_NONBLOCK);
    fcntl(decoder_out, F_SETFL, fcntl(decoder_out, F_GETFL) | O_NONBLOCK);
    decoder_pid = pid;
    decoder_need_key = 1;
    jpeg_len = 0;
    vanilla_request_idr();
    fprintf(stderr, "started ffmpeg for the JPEG pictures\n");
    return 1;
}

static void close_http_client(int i)
{
    close(http_clients[i].fd);
    http_clients[i].fd = -1;
    http_clients[i].streaming = 0;
    http_clients[i].len = 0;
    if (streaming_http_clients() == 0) stop_decoder();
}

static void feed_decoder(const uint8_t *data, size_t size, int key)
{
    if (decoder_pid < 0) return;
    if (decoder_need_key) {
        if (!key) return;
        decoder_need_key = 0;
    }
    size_t off = 0;
    while (off < size) {
        ssize_t n = write(decoder_in, data + off, size - off);
        if (n > 0) { off += n; continue; }
        if (n < 0 && errno == EINTR) continue;
        break;
    }
    if (off < size) {
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
            // ffmpeg is behind. What was cut off breaks the frames that follow,
            // so wait for the next keyframe (and ask for one).
            decoder_need_key = 1;
            vanilla_request_idr();
        } else {
            fprintf(stderr, "ffmpeg stopped taking the video (is ffmpeg installed?)\n");
            stop_decoder();
        }
    }
}

static void send_jpeg(const uint8_t *data, size_t size)
{
    char head[128];
    int head_len = snprintf(head, sizeof(head),
        "--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %zu\r\n\r\n", size);
    for (int i = 0; i < MAX_CLIENTS; i++) {
        http_client_t *hc = &http_clients[i];
        if (hc->fd < 0 || !hc->streaming) continue;
        struct iovec parts[3] = {
            {head, (size_t) head_len},
            {(void *) data, size},
            {"\r\n", 2},
        };
        size_t total = head_len + size + 2;
        struct msghdr msg = {0};
        msg.msg_iov = parts;
        msg.msg_iovlen = 3;
        ssize_t n = sendmsg(hc->fd, &msg, MSG_NOSIGNAL | MSG_DONTWAIT);
        if (n != (ssize_t) total) {
            // A picture cut in two breaks the stream: let the client connect again.
            fprintf(stderr, "picture client too slow or closed, dropping it\n");
            close_http_client(i);
        }
    }
}

// What ffmpeg wrote: JPEG pictures one after the other, each from FF D8 to
// FF D9 (FF D9 does not occur inside a picture: an FF there is followed by 00).
static void read_decoder(void)
{
    if (decoder_out < 0) return;
    for (;;) {
        if (jpeg_cap - jpeg_len < 65536) {
            size_t cap = jpeg_cap ? jpeg_cap * 2 : 262144;
            if (cap > (16u << 20)) {
                jpeg_len = 0;
                cap = jpeg_cap;
            } else {
                uint8_t *b = realloc(jpeg_buf, cap);
                if (!b) { jpeg_len = 0; return; }
                jpeg_buf = b;
                jpeg_cap = cap;
            }
        }
        ssize_t n = read(decoder_out, jpeg_buf + jpeg_len, jpeg_cap - jpeg_len);
        if (n == 0) {
            fprintf(stderr, "ffmpeg ended\n");
            stop_decoder();
            return;
        }
        if (n < 0) {
            if (errno == EINTR) continue;
            if (errno != EAGAIN && errno != EWOULDBLOCK) stop_decoder();
            return;
        }
        size_t scan_from = jpeg_len > 0 ? jpeg_len - 1 : 0;
        jpeg_len += n;
        size_t start = 0;
        for (size_t k = scan_from; k + 1 < jpeg_len; k++) {
            if (jpeg_buf[k] == 0xFF && jpeg_buf[k + 1] == 0xD9 && k + 2 - start > 4) {
                if (jpeg_buf[start] == 0xFF && jpeg_buf[start + 1] == 0xD8) {
                    send_jpeg(jpeg_buf + start, k + 2 - start);
                    if (decoder_pid < 0) return;
                }
                start = k + 2;
                k++;
            }
        }
        if (start > 0) {
            memmove(jpeg_buf, jpeg_buf + start, jpeg_len - start);
            jpeg_len -= start;
        }
    }
}

static void http_reply(int fd, const char *status, const char *json)
{
    char buf[512];
    int n = snprintf(buf, sizeof(buf),
        "HTTP/1.1 %s\r\nContent-Type: application/json\r\nContent-Length: %zu\r\nConnection: close\r\n\r\n%s",
        status, strlen(json), json);
    if (n > 0) send(fd, buf, n, MSG_NOSIGNAL | MSG_DONTWAIT);
}

static void handle_http_request(int i)
{
    http_client_t *hc = &http_clients[i];
    if (!strncmp(hc->buf, "GET /v1/ping", 12)) {
        http_reply(hc->fd, "200 OK", "{\"ok\": true}");
        close_http_client(i);
    } else if (!strncmp(hc->buf, "GET /v1/video", 13)) {
        if (state != STATE_CONNECTED) {
            http_reply(hc->fd, "503 Service Unavailable",
                "{\"error\": \"the Wii U is not connected to the bridge (run Connect the GamePad first)\"}");
            close_http_client(i);
            return;
        }
        static const char head[] =
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: multipart/x-mixed-replace; boundary=frame\r\n"
            "Cache-Control: no-cache\r\n"
            "Connection: close\r\n\r\n";
        int sndbuf = 1 << 20;
        setsockopt(hc->fd, SOL_SOCKET, SO_SNDBUF, &sndbuf, sizeof(sndbuf));
        if (send(hc->fd, head, sizeof(head) - 1, MSG_NOSIGNAL) != (ssize_t) sizeof(head) - 1) {
            close_http_client(i);
            return;
        }
        hc->streaming = 1;
        if (decoder_pid < 0 && !start_decoder()) {
            fprintf(stderr, "could not start ffmpeg\n");
            close_http_client(i);
        }
    } else {
        http_reply(hc->fd, "404 Not Found", "{\"error\": \"not here: try /v1/video\"}");
        close_http_client(i);
    }
}

static void accept_http_client(int lfd)
{
    int fd = accept(lfd, NULL, NULL);
    if (fd < 0) return;
    int one = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (http_clients[i].fd < 0) {
            http_clients[i].fd = fd;
            http_clients[i].len = 0;
            http_clients[i].streaming = 0;
            return;
        }
    }
    http_reply(fd, "503 Service Unavailable", "{\"error\": \"too many viewers\"}");
    close(fd);
}

static void read_http_client(int i)
{
    http_client_t *hc = &http_clients[i];
    char tmp[1024];
    ssize_t n = recv(hc->fd, tmp, sizeof(tmp), 0);
    if (n <= 0) {
        close_http_client(i);
        return;
    }
    if (hc->streaming) return;  // nothing more is expected; ignore it
    size_t room = sizeof(hc->buf) - 1 - hc->len;
    if ((size_t) n > room) n = room;
    memcpy(hc->buf + hc->len, tmp, n);
    hc->len += n;
    hc->buf[hc->len] = 0;
    if (strstr(hc->buf, "\r\n\r\n") || strstr(hc->buf, "\n\n")) {
        handle_http_request(i);
    } else if (hc->len >= sizeof(hc->buf) - 1) {
        http_reply(hc->fd, "413 Payload Too Large", "{\"error\": \"request too long\"}");
        close_http_client(i);
    }
}

static void close_all_http_clients(void)
{
    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (http_clients[i].fd >= 0) close_http_client(i);
    }
    stop_decoder();
}

static void play_test_h264(void)
{
    // About 1.5 MB/s, more than the GamePad sends; ffmpeg keeps up or skips.
    static uint8_t chunk[4096];
    state = STATE_CONNECTED;
    size_t n = fread(chunk, 1, sizeof(chunk), test_h264);
    if (n == 0) {
        rewind(test_h264);
        decoder_need_key = 1;
        return;
    }
    send_video(chunk, n);
    feed_decoder(chunk, n, is_keyframe(chunk, n));
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
            feed_decoder(ev.data, ev.size, is_keyframe(ev.data, ev.size));
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
        "  --http-port <port>  JPEG pictures over HTTP, for ClaudeGG (default 51202)\n"
        "  --fps <n>           JPEG pictures a second, 1 to 30 (default 10)\n"
        "  --quality <q>       JPEG quality as ffmpeg's -q:v, 2 (best) to 31 (default 5)\n"
        "  --region <r>        GamePad region: EUR USA JPN AUS KOR CHN TWN (default EUR)\n"
        "  --console <file>    where the synced console is stored\n"
        "                      (default ~/.config/claudegg-wiiu/console.bin)\n"
        "  --verbose           print Vanilla's log\n"
        "  --test-h264 <file>  no Wii U: play this raw H.264 file (in a loop) as the GamePad\n"
        "                      screen, to try the pictures for ClaudeGG\n"
        "Run 'sudo vanilla-pipe -local <wifi-interface>' first.\n", argv0);
}

int main(int argc, char **argv)
{
    const char *bind_addr = "0.0.0.0";
    int cmd_port = 51200, video_port = 51201, http_port = 51202;
    int region = VANILLA_REGION_EUROPE;

    const char *home = getenv("HOME");
    snprintf(console_path, sizeof(console_path), "%s/.config/claudegg-wiiu/console.bin", home ? home : ".");

    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        const char *next = (i + 1 < argc) ? argv[i + 1] : NULL;
        if (!strcmp(a, "--bind") && next) { bind_addr = next; i++; }
        else if (!strcmp(a, "--cmd-port") && next) { cmd_port = atoi(next); i++; }
        else if (!strcmp(a, "--video-port") && next) { video_port = atoi(next); i++; }
        else if (!strcmp(a, "--http-port") && next) { http_port = atoi(next); i++; }
        else if (!strcmp(a, "--fps") && next) {
            jpeg_fps = atoi(next);
            if (jpeg_fps < 1 || jpeg_fps > 30) { usage(argv[0]); return 1; }
            i++;
        }
        else if (!strcmp(a, "--quality") && next) {
            jpeg_quality = atoi(next);
            if (jpeg_quality < 2 || jpeg_quality > 31) { usage(argv[0]); return 1; }
            i++;
        }
        else if (!strcmp(a, "--region") && next) {
            region = lookup(REGIONS, next);
            if (region < 0) { usage(argv[0]); return 1; }
            i++;
        }
        else if (!strcmp(a, "--console") && next) { snprintf(console_path, sizeof(console_path), "%s", next); i++; }
        else if (!strcmp(a, "--verbose")) { verbose = 1; }
        else if (!strcmp(a, "--test-h264") && next) {
            test_h264 = fopen(next, "rb");
            if (!test_h264) { perror(next); return 1; }
            i++;
        }
        else { usage(argv[0]); return 1; }
    }

    for (int i = 0; i < MAX_CLIENTS; i++) {
        cmd_clients[i].fd = -1;
        video_clients[i].fd = -1;
        http_clients[i].fd = -1;
        http_clients[i].streaming = 0;
        http_clients[i].len = 0;
    }

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    signal(SIGPIPE, SIG_IGN);

    vanilla_install_logger(vanilla_logger);
    vanilla_set_region(region);
    vanilla_set_battery_status(VANILLA_BATTERY_STATUS_FULL);

    int cmd_lfd = listen_on(bind_addr, cmd_port);
    int vid_lfd = listen_on(bind_addr, video_port);
    int http_lfd = listen_on(bind_addr, http_port);
    if (cmd_lfd < 0 || vid_lfd < 0 || http_lfd < 0) return 1;

    fprintf(stderr, "claudegg-wiiu-bridge: commands on %s:%d, H.264 on %d, JPEG over HTTP on %d, console file %s\n",
        bind_addr, cmd_port, video_port, http_port, console_path);

    while (!quit_requested) {
        // idx: -1 command listener, -2 H.264 listener, -3 HTTP listener,
        // -4 ffmpeg's output, 0.. a command client, 100.. an HTTP client.
        struct pollfd pfds[4 + 2 * MAX_CLIENTS];
        int idx[4 + 2 * MAX_CLIENTS];
        int n = 0;
        pfds[n].fd = cmd_lfd; pfds[n].events = POLLIN; idx[n++] = -1;
        pfds[n].fd = vid_lfd; pfds[n].events = POLLIN; idx[n++] = -2;
        pfds[n].fd = http_lfd; pfds[n].events = POLLIN; idx[n++] = -3;
        if (decoder_out >= 0) {
            pfds[n].fd = decoder_out; pfds[n].events = POLLIN; idx[n++] = -4;
        }
        for (int i = 0; i < MAX_CLIENTS; i++) {
            if (cmd_clients[i].fd >= 0) {
                pfds[n].fd = cmd_clients[i].fd; pfds[n].events = POLLIN; idx[n++] = i;
            }
            if (http_clients[i].fd >= 0) {
                pfds[n].fd = http_clients[i].fd; pfds[n].events = POLLIN; idx[n++] = 100 + i;
            }
        }

        // Short timeout so video frames from Vanilla go out quickly.
        int r = poll(pfds, n, state == STATE_IDLE ? 100 : 2);
        if (r < 0 && errno != EINTR) { perror("poll"); break; }

        for (int k = 0; r > 0 && k < n; k++) {
            if (!(pfds[k].revents & (POLLIN | POLLHUP | POLLERR))) continue;
            if (idx[k] == -1) accept_cmd_client(cmd_lfd);
            else if (idx[k] == -2) accept_video_client(vid_lfd);
            else if (idx[k] == -3) accept_http_client(http_lfd);
            else if (idx[k] == -4) read_decoder();
            else if (idx[k] >= 100) {
                if (http_clients[idx[k] - 100].fd == pfds[k].fd) read_http_client(idx[k] - 100);
            }
            else read_cmd_client(idx[k]);
        }

        if (test_h264) {
            play_test_h264();
        } else {
            handle_vanilla_events();
        }
    }

    fprintf(stderr, "shutting down\n");
    stop_vanilla();
    close_all_http_clients();
    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (cmd_clients[i].fd >= 0) close(cmd_clients[i].fd);
        if (video_clients[i].fd >= 0) close(video_clients[i].fd);
    }
    close(cmd_lfd);
    close(vid_lfd);
    close(http_lfd);
    return 0;
}
