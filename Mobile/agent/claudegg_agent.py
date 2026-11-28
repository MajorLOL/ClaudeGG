#!/usr/bin/env python3
"""Claude GG agent: the hands and eyes of an Android phone, for a Raspberry Pi.

Claude GG (the program on the computer) does the thinking: it looks at the picture of the phone and
decides where to tap. This small program on the Raspberry Pi, that has the phone on a USB cable, does
only what it is asked: a picture of the screen, a tap, a swipe, a key. It is the "microcontroller" of a
phone, the way a Pico is that of a Nintendo Switch.

It speaks HTTP with JSON, on the local network, and wants a token (made the first time it starts, kept
in ~/.claudegg-agent/token) in the header "Authorization: Bearer <token>". What it can do is the list of
the endpoints below, and the arguments are checked before an `adb` command is made (on the Pi a list of
arguments, never a line for a shell; on the phone only checked numbers, key names and plain text). The
taps, swipes and keys go through one `adb shell` that stays open (ShellSession): faster than a new one each.

    GET  /  or  /status                 a page for a browser on the network: what runs, the screen, today's
                                        counters (no token for the page itself; it asks for the token and
                                        reads the endpoints below with it)
    GET  /v1/ping                       {"ok": true}                            (no token)
    GET  /v1/info                       the phone: model, android, width, height
    GET  /v1/screen                     the screen as a PNG
    GET  /v1/heat                       {phone, pi}: the temperature of the phone's battery and of the processor of the
                                        machine the agent runs on, in degrees Celsius (null for what cannot be read)
    GET  /v1/power?only=awake|locked    {awake, locked}: is the screen of the phone on (`dumpsys power`), and does it show the
                                        lock screen (`dumpsys window`); `only` asks for one of the two
    GET  /v1/display?only=wm|files      the shape of the screen as Android draws it: {wm} is what `wm size` says (the physical size and the
                                        override), {record, allow, no_adapt, paths} what the Pi keeps for the change of the display (the record of
                                        what was changed, the two switch files); `only` asks for one of the two parts
    POST /v1/display {action, ...}      "record" {set, time, model, was} writes down what is going to be changed (~/gamebot_wm_override.json),
                                        "size" {size: "WxH"} sets the size of the display (`wm size`: refused unless the record names that size,
                                        and while ~/gamebot_no_display_change exists), "reset" puts it back (`wm size reset`), "forget" removes
                                        the record
    POST /v1/unlock                     asks Android to take away the swipe lock screen (`wm dismiss-keyguard`; a PIN or a
                                        pattern stays)
    GET  /v1/video?fps=10&width=540     the screen live: JPEG pictures in a multipart/x-mixed-replace stream
    POST /v1/tap     {x, y, ms, kind}   a press of ms milliseconds (120); kind "tap": a plain `input tap` (finger down and
                                        up at once), "motion": finger down, ms, finger up as touch events (Android 11+)
    POST /v1/swipe   {x1, y1, x2, y2, ms}
    POST /v1/swipes  {strokes: [[x1, y1, x2, y2, ms], ...]}   one after the other, in ONE adb command
    POST /v1/touch   {events: [[action, x, y], ...]}   touch events one after another in ONE adb command (action DOWN,
                                        MOVE or UP; Android 11+): a finger that is held, moved and let go, as a throw of a ball
                                        needs; answers {out}: what the phone wrote (an old phone says it does not know them)
    POST /v1/key     {key: "BACK"}      or {keycode: 4}
    POST /v1/text    {text: "..."}      letters, digits and . , _ @ : / + - and spaces
    POST /v1/wake                       wakes the screen
    POST /v1/app     {action, package}  the Pokemon GO app (a package like com.nianticlabs.pokemongo): "stop" closes it,
                                        "start" starts it without waiting for the game to be up (monkey can take half a
                                        minute), "state" says how that start is going ({running, code, error}), "end" lets
                                        go of the start command that still runs, "list" (no package) says which Pokemon GO
                                        apps are installed ({packages}: the Play Store one first)
    GET  /v1/bot?lines=40               the Pokemon GO bot (gamebot.py, installed in the home folder as the service
                                        spin-stop): installed, running, its options, the end of its log, the
                                        counters of today, the GO Battle League matches of today, and the
                                        test that runs or ran last
    POST /v1/bot/start {options, throw_target, daily_time, daily_max_min, daily_now,
                        battle_app, battle_league, battle_count}
                                        sets what is asked in the bot's control file and starts it
    POST /v1/bot/stop                   stops it
    GET  /v1/bot/tests                  the parts of the bot that can be run on their own (its chapters.py)
    POST /v1/bot/test {key, options...} stops the bot and runs one part of it, as /v1/bot/start sets it
    POST /v1/bot/test/stop              ends that test
    GET  /v1/bot/file?name=battle_team.json   one of the files the bot keeps of its battles (battle_team.json,
                                        battle_seen.json, battle_minigame.json), read only; 404 when it is not there

Only the standard library is used, so it runs on the Pi as it is. Part of Claude GG
(https://github.com/MajorLOL/ClaudeGG); MIT license like the rest of this folder.
"""

import argparse
import base64
import hashlib
import hmac
import importlib.util
import json
import os
import queue
import re
import secrets
import struct
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.2.6"
#  What this agent can do that the first one (0.1.0) could not; Claude GG asks for these before a program of its own plays.
FEATURES = ("tap_kind", "app", "bot_file", "touch", "app_list", "heat", "power", "display")
DISPLAY_SIZE = re.compile(r"[1-9][0-9]{2,4}x[1-9][0-9]{2,4}\Z")      #  the argument of `wm size`: two whole numbers, nothing else
DISPLAY_WAS = re.compile(r"[0-9]{1,5}x[0-9]{1,5}\Z")
DISPLAY_RECORD_BYTES = 64 * 1024
DEFAULT_PORT = 8765
MAX_BODY = 64 * 1024
MAX_STROKES = 50
MAX_TOUCHES = 64
TOUCH_ACTIONS = ("DOWN", "MOVE", "UP")
MAX_COORDINATE = 20000
MAX_MS = 10000
MAX_TEXT = 200
ADB_TIMEOUT = 30

#  The live picture (see VideoPipeline).
RECORD_SECONDS = 170        #  `screenrecord` stops after 180 s by itself: it is started again before that
VIDEO_FPS = (1, 30, 10)     #  lowest, highest, default (pictures a second)
VIDEO_WIDTH = (100, 2000, 540)
VIDEO_IDLE_SECONDS = 5      #  the pipeline stops this long after the last viewer left
VIDEO_FIRST_PICTURE_SECONDS = 12
VIDEO_REPEAT_SECONDS = 1.0  #  a screen that does not change gives no new picture: the last one is sent again

#  The Pokemon GO bot (Mobile/gamebot.py, installed in the home folder as a service called spin-stop). The
#  agent only starts and stops it and sets the switches of its control file, as the bot's web interface
#  does; the options a program of Claude GG may set are listed here, and nothing else is written.
BOT_SERVICE = "spin-stop"
BOT_SWITCHES = (
    "spin", "catch", "gifts_open", "gifts_send", "daily_cycle", "curveball", "fast_catch",
    "spin_only_when_full", "close_when_full", "rocket_fight", "quests", "bag_clean", "buddy",
    "fast_look", "heat_pause", "live_look", "battle", "battle_give_up", "teams_weekly",
)
#  The ones that start unticked (as the bot itself reads a switch that was never set).
BOT_SWITCHES_OFF = ("curveball", "buddy", "fast_catch", "battle", "teams_weekly")
#  GO Battle League: the app (empty: the Play Store one), the league as the game names it, battles per run.
BOT_BATTLE_APP = re.compile(r"^(|com\.nianticlabs\.pokemongo[A-Za-z0-9._]{0,60})$")
BOT_BATTLE_LEAGUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 '\-]{0,39}$")
BOT_BATTLE_COUNT = (1, 50)
#  The apps that /v1/app may close and start: the Pokemon GO of the Play Store and the other stores.
APP_PACKAGE = re.compile(r"^com\.nianticlabs\.pokemongo[A-Za-z0-9._]{0,60}$")
APP_ACTIONS = ("stop", "start", "state", "end", "list")
APP_MAIN = "com.nianticlabs.pokemongo"      #  the Play Store version: always first in the list
PI_TEMPERATURE_FILE = "/sys/class/thermal/thermal_zone0/temp"   #  the processor of the Pi, in thousandths of a degree
APP_ERROR_BYTES = 2000      #  how much of what the start command wrote as an error is told
BOT_CHAPTER_KEY = re.compile(r"^[a-z][a-z_]{0,29}$")
BOT_TEST_STOP_WAIT = 20          #  seconds the service has to stop before a test begins
BOT_BATTLE_DONE = re.compile(r"battle: battle \d+ done: (win|loss)( \(given up\))?")
BOT_BATTLE_SET = re.compile(r"battle: \d+ battle\(s\) in '([^']*)'")
BOT_TEST_DONE = r"TEST %s: (done|failed) - (.*)$"
BOT_THROW_TARGETS = ("realistic", "off", "nice", "great", "excellent")
BOT_LOG_LINES = (1, 200, 40)
BOT_TODAY = re.compile(r"\(today: ([^)]*)\)")
BOT_TODAY_COUNTERS = ("caught", "fled", "stops", "won", "lost")
BOT_DAILY_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
#  The files of the bot that Claude GG may read (/v1/bot/file): the team and what the bot learned in its battles.
BOT_FILES = ("battle_team.json", "battle_seen.json", "battle_minigame.json")
BOT_FILE_BYTES = 4 * 1024 * 1024

#  The keys a program may press (Android's key events). Others by their number, 0 to 300.
KEYS = {
    "BACK": 4, "HOME": 3, "APP_SWITCH": 187, "POWER": 26, "WAKEUP": 224, "MENU": 82,
    "ENTER": 66, "DEL": 67, "TAB": 61, "SPACE": 62, "ESCAPE": 111,
    "DPAD_UP": 19, "DPAD_DOWN": 20, "DPAD_LEFT": 21, "DPAD_RIGHT": 22, "DPAD_CENTER": 23,
    "VOLUME_UP": 24, "VOLUME_DOWN": 25,
}
TEXT_ALLOWED = re.compile(r"^[A-Za-z0-9 ._@:,/+-]*$")


class AgentError(Exception):
    """Something to tell the caller, with the HTTP status it goes with."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class Adb:
    """`adb` with a list of arguments: never a shell line. `command` is the program (and what
    comes before the arguments: a test puts a script there)."""

    def __init__(self, command=("adb",), serial=None, timeout=ADB_TIMEOUT):
        self.command = list(command)
        self.serial = serial
        self.timeout = timeout

    def line(self, *args):
        """The arguments of one adb command (to run, or to give to Popen)."""
        line = list(self.command)
        if self.serial:
            line += ["-s", self.serial]
        return line + [str(a) for a in args]

    def run(self, *args, binary=False):
        line = self.line(*args)
        try:
            done = subprocess.run(line, capture_output=True, timeout=self.timeout)
        except FileNotFoundError:
            raise AgentError(502, "adb is not installed here (sudo apt install adb)")
        except subprocess.TimeoutExpired:
            raise AgentError(504, "adb did not answer in time")
        if done.returncode != 0:
            why = done.stderr.decode(errors="ignore").strip() or done.stdout.decode(errors="ignore").strip()
            raise AgentError(502, "adb: " + (why or "failed"))
        return done.stdout if binary else done.stdout.decode(errors="ignore")

    def quick(self, *args):
        """A short `adb shell` command (a tap, a swipe, a key): through the shell that stays open
        (ShellSession) when there is one, else as `run("shell", ...)`. The same command either way."""
        session = self.session
        if session is not None:
            done = session.run(" ".join(str(a) for a in args))
            if done is not None:
                return done
        return self.run("shell", *args)

    session = None


class ShellSession:
    """One `adb shell` that stays open for the short commands (taps, swipes, keys).

    Why: every `adb shell ...` starts the adb program on the Pi, connects to the adb server and has
    the phone start a shell: about 50 to 200 ms (more on an older Pi) before the tap itself begins.
    Through one shell that stays open, a command is a line written to it, and the answer the line
    after it. The command is the same as `adb shell <command>` would run.

    A command that cannot go through it (the shell is busy with another one, or could not be
    started) goes the old way: `run()` gives None for that. A shell that broke off while a command
    was in it is an error of that command, never a second try: a tap must not be done twice."""

    MARK = "__claudegg_done__"
    RETRY_SECONDS = 2.0        #  after the shell could not be started, the old way for this long

    def __init__(self, adb, timeout=ADB_TIMEOUT):
        self.adb = adb
        self.timeout = timeout
        self.lock = threading.Lock()
        self.process = None
        self.lines = None              #  what the shell writes, line by line (from a thread of its own)
        self.count = 0
        self.failed_at = None

    def _start(self):
        if self.failed_at is not None and time.monotonic() - self.failed_at < self.RETRY_SECONDS:
            return False
        try:
            process = subprocess.Popen(self.adb.line("shell"), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, bufsize=0)
        except OSError:
            self.failed_at = time.monotonic()
            return False
        lines = queue.Queue()

        def read():
            for line in iter(process.stdout.readline, b""):
                lines.put(line.decode(errors="ignore"))
            lines.put(None)
        threading.Thread(target=read, daemon=True).start()
        self.process, self.lines, self.failed_at = process, lines, None
        return True

    def _stop(self):
        process, self.process, self.lines = self.process, None, None
        if process is None:
            return
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        for pipe in (process.stdin, process.stdout):
            try:
                pipe.close()
            except OSError:
                pass

    def close(self):
        with self.lock:
            self._stop()

    def run(self, command):
        """What the command wrote, or None when it has to go the old way."""
        if not self.lock.acquire(blocking=False):
            return None
        try:
            if self.process is not None and self.process.poll() is not None:
                self._stop()
            if self.process is None and not self._start():
                return None
            self.count += 1
            mark = "%s%d" % (self.MARK, self.count)
            #  { ...; }: the whole command, also one of several parts, with nothing to read and its errors with
            #  what it writes; then the line that says it is done, with how it ended.
            line = "{ %s ; } </dev/null 2>&1; echo %s $?\n" % (command, mark)
            try:
                self.process.stdin.write(line.encode())
                self.process.stdin.flush()
            except OSError:
                #  Nothing reached the phone: the old way is safe.
                self._stop()
                self.failed_at = time.monotonic()
                return None
            out = []
            until = time.monotonic() + self.timeout
            while True:
                try:
                    got = self.lines.get(timeout=max(0.01, until - time.monotonic()))
                except queue.Empty:
                    self._stop()
                    raise AgentError(504, "adb did not answer in time")
                if got is None:
                    self._stop()
                    why = "".join(out).strip()
                    raise AgentError(502, "adb: " + (why or "the connection to the phone broke off"))
                if got.startswith(mark + " ") or got.rstrip("\r\n") == mark:
                    code = got[len(mark):].strip()
                    text = "".join(out)
                    if code not in ("", "0"):
                        raise AgentError(502, "adb: " + (text.strip() or "failed"))
                    return text
                out.append(got)
        finally:
            self.lock.release()


def png_size(data):
    """(width, height) of a PNG, from its header, or None."""
    start = data.find(b"\x89PNG\r\n\x1a\n")
    if start < 0 or len(data) < start + 24:
        return None
    width, height = struct.unpack(">II", data[start + 16:start + 24])
    return width, height


class VideoPipeline:
    """The live picture of the phone: `screenrecord` (H.264) -> ffmpeg -> JPEG pictures, ONE pipeline
    for all who look. It starts with the first viewer and stops a few seconds after the last one.
    `screenrecord` ends by itself after three minutes: the pipeline starts it again (the viewers
    keep their stream). A screen that does not change gives no new pictures.

    `command` (a test) is a program that writes the JPEG pictures to its standard output, in place
    of `screenrecord` and ffmpeg."""

    def __init__(self, adb, display=None, command=None, ffmpeg="ffmpeg", retry_delay=0.5, idle_seconds=VIDEO_IDLE_SECONDS):
        self.adb = adb
        self.display = display
        self.command = list(command) if command else None
        self.ffmpeg = ffmpeg
        self.retry_delay = retry_delay
        self.idle_seconds = idle_seconds
        self.cond = threading.Condition()
        self.frame = None
        self.serial = 0
        self.viewers = 0
        self.running = False        #  the thread is there
        self.stopping = False
        self.error = None
        self.processes = []
        self.timer = None

    def _commands(self, fps, width):
        if self.command:
            return [self.command]
        record = self.adb.line("exec-out", "screenrecord", "--output-format=h264",
                               "--bit-rate", "6000000", "--time-limit", str(RECORD_SECONDS))
        if self.display:
            record += ["--display-id", str(self.display)]
        record.append("-")
        decode = [self.ffmpeg, "-loglevel", "error", "-fflags", "nobuffer", "-flags", "low_delay",
                  "-f", "h264", "-i", "-", "-vf", "fps=%d,scale=%d:-2" % (fps, width),
                  "-q:v", "5", "-f", "mjpeg", "-"]
        return [record, decode]

    def open(self, fps, width):
        """A viewer starts: the pipeline is started when it is not there."""
        with self.cond:
            self.viewers += 1
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None
            #  One that is just being stopped goes on instead.
            self.stopping = False
            if not self.running:
                self.running = True
                self.error = None
                self.frame = None
                threading.Thread(target=self._run, args=(fps, width), daemon=True).start()

    def close(self):
        """A viewer is gone: with the last one the pipeline stops, after a while."""
        with self.cond:
            self.viewers -= 1
            if self.viewers <= 0:
                self.viewers = 0
                self.timer = threading.Timer(self.idle_seconds, self._idle)
                self.timer.daemon = True
                self.timer.start()

    def _idle(self):
        with self.cond:
            if self.viewers == 0:
                self.stopping = True
                self._kill()
                self.cond.notify_all()

    def _idle_now(self):
        """Stops it without waiting (the end of a test)."""
        with self.cond:
            if self.timer is not None:
                self.timer.cancel()
            self.stopping = True
            self._kill()
            self.cond.notify_all()

    def _kill(self):
        for process in self.processes:
            try:
                process.kill()
            except OSError:
                pass

    def wait(self, serial, timeout):
        """(picture, serial, alive): the newest picture when it is newer than `serial`, the same one
        again after the timeout. Not alive: the pipeline gave up or was stopped (see `error`)."""
        with self.cond:
            self.cond.wait_for(lambda: self.serial != serial or not self.running, timeout)
            return self.frame, self.serial, self.running

    def first(self, timeout):
        """The newest picture, waiting for the first one when there is none yet: (picture, serial,
        alive) like wait()."""
        with self.cond:
            self.cond.wait_for(lambda: self.frame is not None or not self.running, timeout)
            return self.frame, self.serial, self.running

    def _publish(self, frame):
        with self.cond:
            self.frame = frame
            self.serial += 1
            self.cond.notify_all()

    def _run(self, fps, width):
        failures = 0
        try:
            while True:
                with self.cond:
                    if self.stopping:
                        return
                pictures, note = self._once(fps, width)
                with self.cond:
                    if self.stopping:
                        return
                if pictures:
                    failures = 0
                else:
                    failures += 1
                    self.error = note or "the picture stopped at once"
                    if failures >= 3:
                        return
                time.sleep(self.retry_delay)
        finally:
            with self.cond:
                self.running = False
                self.processes = []
                self.cond.notify_all()

    def _once(self, fps, width):
        """One run of the pipeline: how many pictures it gave, and what it said when it ended."""
        commands = self._commands(fps, width)
        processes = []
        try:
            previous = None
            for index, command in enumerate(commands):
                last = index == len(commands) - 1
                process = subprocess.Popen(command, stdin=previous.stdout if previous else subprocess.DEVNULL,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE if last else subprocess.DEVNULL)
                if previous:
                    previous.stdout.close()
                processes.append(process)
                previous = process
        except FileNotFoundError as error:
            for process in processes:
                process.kill()
                process.wait()
                for pipe in (process.stdout, process.stderr):
                    if pipe is not None:
                        pipe.close()
            what = "ffmpeg is not installed here (sudo apt install ffmpeg)" if commands[-1][0] == self.ffmpeg else str(error)
            return 0, what
        with self.cond:
            self.processes = processes
        pictures = 0
        buffer = b""
        try:
            stream = processes[-1].stdout
            while True:
                chunk = stream.read1(65536)
                if not chunk:
                    break
                buffer += chunk
                while True:
                    start = buffer.find(b"\xff\xd8")
                    if start < 0:
                        buffer = buffer[-1:]
                        break
                    end = buffer.find(b"\xff\xd9", start + 2)
                    if end < 0:
                        buffer = buffer[start:]
                        break
                    self._publish(buffer[start:end + 2])
                    pictures += 1
                    buffer = buffer[end + 2:]
        finally:
            for process in processes:
                process.kill()
            note = processes[-1].stderr.read().decode(errors="ignore").strip() if processes[-1].stderr else ""
            for process in processes:
                process.wait()
                for pipe in (process.stdout, process.stderr):
                    if pipe is not None:
                        pipe.close()
        return pictures, note[-300:]


class Phone:
    """What can be done with the phone: the endpoints, with their arguments checked."""

    def __init__(self, adb, display=None, video=None, bot=None, heat_file=PI_TEMPERATURE_FILE):
        self.adb = adb
        self.heat_file = heat_file
        #  The files of the bot of the Pi for the change of the display (spin_stop.py: WM_FILE, ALLOW_FILE, NO_ADAPT_FILE).
        home = os.path.expanduser("~")
        self.wm_file = os.path.join(home, "gamebot_wm_override.json")
        self.allow_file = os.path.join(home, "gamebot_allow_unsupported")
        self.no_adapt_file = os.path.join(home, "gamebot_no_display_change")
        self.display = display
        self.video = video if video is not None else VideoPipeline(adb, display)
        self.bot = bot if bot is not None else Bot()
        self._launch = None             #  the command that starts the game (it runs while the game starts)
        self._launch_lock = threading.Lock()

    @staticmethod
    def _int(value, name, low=0, high=MAX_COORDINATE):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):
            raise AgentError(400, "%s must be a whole number" % name)
        value = int(value)
        if value < low or value > high:
            raise AgentError(400, "%s must be from %d to %d" % (name, low, high))
        return value

    def info(self):
        model = self.adb.run("shell", "getprop", "ro.product.model").strip()
        android = self.adb.run("shell", "getprop", "ro.build.version.release").strip()
        size = self.adb.run("shell", "wm", "size")
        #  "Physical size: 1080x2340", and a line "Override size: ..." when it was changed: that one counts.
        found = re.findall(r"(Physical|Override) size:\s*(\d+)x(\d+)", size)
        width = height = 0
        for kind, w, h in found:
            width, height = int(w), int(h)
            if kind == "Override":
                break
        return {"model": model, "android": android, "width": width, "height": height,
                "display": self.display}

    def heat(self):
        """The temperatures that the bot of the Pi watches (read_heat() of gamebot.py): `phone`, the battery of the phone
        (`dumpsys battery` says it in tenths of a degree), and `pi`, the processor of this machine; null for what cannot be read."""
        phone = pi = None
        try:
            found = re.search(r"^\s*temperature:\s*(-?\d+)", self.adb.run("shell", "dumpsys", "battery"), re.M)
            phone = int(found.group(1)) / 10.0 if found else None
        except Exception:  # noqa: BLE001  (a phone that does not answer is no temperature)
            phone = None
        try:
            with open(self.heat_file) as handle:
                pi = int(handle.read().strip()) / 1000.0
        except (OSError, ValueError):
            pi = None
        return {"phone": phone, "pi": pi}

    #  What `dumpsys window` says when the phone shows its lock screen (keyguard_showing() of spin_stop.py: any of these).
    KEYGUARD_WORDS = ("mKeyguardShowing=true", "isKeyguardShowing=true", "mShowingLockscreen=true", "KeyguardShowing=true")

    def power(self, only=None):
        """What the bot of the Pi asks of the phone now and then: `awake`, is the screen on (`dumpsys power` has mWakefulness=Awake), and `locked`,
        does it show the lock screen (`dumpsys window`, keyguard_showing() of spin_stop.py). `only` ("awake" or "locked") asks for one of them; the
        other is then left out. A phone that does not answer is an error: neither a yes nor a no."""
        if only not in (None, "awake", "locked"):
            raise AgentError(400, "only must be awake or locked")
        answer = {}
        if only in (None, "awake"):
            answer["awake"] = "mWakefulness=Awake" in self.adb.run("shell", "dumpsys", "power")
        if only in (None, "locked"):
            window = self.adb.run("shell", "dumpsys", "window")
            answer["locked"] = any(word in window for word in self.KEYGUARD_WORDS)
        return answer

    def _record_text(self):
        try:
            with open(self.wm_file, encoding="utf-8", errors="replace") as handle:
                return handle.read(DISPLAY_RECORD_BYTES)
        except OSError:
            return None

    def display_state(self, only=None):
        """The shape of the screen as Android draws it (what the bot of the Pi asks in wm_info(), load_wm_record() and for the two switch files):
        `wm` is what `wm size` says; `record` the text of the record of what was changed (null: there is none), `allow` and `no_adapt` whether the
        two switch files exist, `paths` where they are. `only` ("wm" or "files") asks for one of the two parts; "files" does not ask the phone."""
        if only not in (None, "wm", "files"):
            raise AgentError(400, "only must be wm or files")
        answer = {}
        if only in (None, "wm"):
            answer["wm"] = self.adb.run("shell", "wm", "size").replace("\r\n", "\n")     #  (an adb through a terminal ends its lines with \r\n)
        if only in (None, "files"):
            answer["record"] = self._record_text()
            answer["allow"] = os.path.exists(self.allow_file)
            answer["no_adapt"] = os.path.exists(self.no_adapt_file)
            answer["paths"] = {"record": self.wm_file, "allow": self.allow_file, "no_adapt": self.no_adapt_file}
        return answer

    def display_change(self, body):
        """Change the display and put it back, in the steps of adapt_display() and restore_display() of spin_stop.py: `record` first (what is going to be
        changed is written down), then `size`, and `reset` (and `forget` for the record) when it is over. `size` only goes with a record that names it,
        so that there is always a way back, and not while the switch file ~/gamebot_no_display_change exists."""
        action = body.get("action")
        if action == "record":
            size, was, model, moment = body.get("set"), body.get("was"), body.get("model"), body.get("time")
            if not isinstance(size, str) or not DISPLAY_SIZE.match(size):
                raise AgentError(400, "set must be a size like 1080x1348")
            if not isinstance(was, str) or not DISPLAY_WAS.match(was):
                raise AgentError(400, "was must be a size like 1080x2400")
            if not isinstance(model, str) or len(model) > 100:
                raise AgentError(400, "model must be a text of at most 100 letters")
            if isinstance(moment, bool) or not isinstance(moment, (int, float)):
                raise AgentError(400, "time must be a number")
            try:
                with open(self.wm_file, "w", encoding="utf-8") as handle:
                    json.dump({"set": size, "time": moment, "model": model, "was": was}, handle)
            except OSError as error:
                raise AgentError(500, str(error))
        elif action == "forget":
            try:
                os.remove(self.wm_file)
            except OSError:
                pass
        elif action == "size":
            size = body.get("size")
            if not isinstance(size, str) or not DISPLAY_SIZE.match(size):
                raise AgentError(400, "size must be like 1080x1348")
            if os.path.exists(self.no_adapt_file):
                raise AgentError(409, "the display size is not changed: %s exists" % self.no_adapt_file)
            try:
                record = json.loads(self._record_text() or "")
            except ValueError:
                record = None
            if not isinstance(record, dict) or record.get("set") != size:
                raise AgentError(409, "write down what is going to be changed first (action record with set %s)" % size)
            self.adb.run("shell", "wm", "size", size)
        elif action == "reset":
            self.adb.run("shell", "wm", "size", "reset")
        else:
            raise AgentError(400, "action must be record, size, reset or forget")

    def unlock(self):
        """`wm dismiss-keyguard`: the swipe lock screen goes away (a PIN or a pattern does not)."""
        self.adb.run("shell", "wm", "dismiss-keyguard")

    def screen(self):
        args = ["exec-out", "screencap"]
        if self.display:
            args += ["-d", str(self.display)]
        args.append("-p")
        raw = self.adb.run(*args, binary=True)
        start = raw.find(b"\x89PNG")
        if start < 0:
            raise AgentError(502, "the phone gave no picture (is the screen on and unlocked?)")
        return raw[start:]

    def tap(self, body):
        x = self._int(body.get("x"), "x")
        y = self._int(body.get("y"), "y")
        ms = self._int(body.get("ms", 120), "ms", 1, MAX_MS)
        kind = body.get("kind", "press")
        if kind == "tap":
            #  Some screens of a game take this and not a press.
            self.adb.quick("input", "tap", x, y)
        elif kind == "motion":
            #  Finger down, a moment, finger up: separate touch events.
            self.adb.quick("input motionevent DOWN %d %d; sleep %.2f; input motionevent UP %d %d" % (x, y, ms / 1000.0, x, y))
        elif kind == "press":
            #  A press of a moment: Pokemon GO (Unity) misses a very short tap.
            self.adb.quick("input", "swipe", x, y, x, y, ms)
        else:
            raise AgentError(400, 'kind is "press", "tap" or "motion"')

    def swipe(self, body):
        x1 = self._int(body.get("x1"), "x1")
        y1 = self._int(body.get("y1"), "y1")
        x2 = self._int(body.get("x2"), "x2")
        y2 = self._int(body.get("y2"), "y2")
        ms = self._int(body.get("ms", 300), "ms", 1, MAX_MS)
        self.adb.quick("input", "swipe", x1, y1, x2, y2, ms)

    def swipes(self, body):
        strokes = body.get("strokes")
        if not isinstance(strokes, list) or not strokes or len(strokes) > MAX_STROKES:
            raise AgentError(400, "strokes must be a list of 1 to %d swipes" % MAX_STROKES)
        parts = []
        for stroke in strokes:
            if not isinstance(stroke, list) or len(stroke) != 5:
                raise AgentError(400, "a stroke is [x1, y1, x2, y2, ms]")
            x1, y1, x2, y2 = (self._int(v, n) for v, n in zip(stroke[:4], ("x1", "y1", "x2", "y2")))
            ms = self._int(stroke[4], "ms", 1, MAX_MS)
            parts.append("input swipe %d %d %d %d %d" % (x1, y1, x2, y2, ms))
        #  One command for all of them: the phone starts the next swipe the moment one is
        #  done, with no trip to the computer in between. Only numbers are in the line.
        self.adb.quick("; ".join(parts))

    def touch(self, body):
        """Touch events one after another (a finger down, moved, up): one command, so that nothing comes in between."""
        events = body.get("events")
        if not isinstance(events, list) or not events or len(events) > MAX_TOUCHES:
            raise AgentError(400, "events must be a list of 1 to %d touch events" % MAX_TOUCHES)
        parts = []
        for event in events:
            if not isinstance(event, list) or len(event) != 3 or event[0] not in TOUCH_ACTIONS:
                raise AgentError(400, "a touch event is [action, x, y] with action DOWN, MOVE or UP")
            x = self._int(event[1], "x")
            y = self._int(event[2], "y")
            parts.append("input motionevent %s %d %d" % (event[0], x, y))
        #  (only the three words and numbers are in the line)  What the phone writes is the answer: an Android that does not know
        #  these events says so, and then the caller throws without them.
        try:
            out = self.adb.quick("{ " + "; ".join(parts) + "; } 2>&1")
        except AgentError as e:
            out = str(e)
        return {"out": out if isinstance(out, str) else out.decode(errors="ignore")}

    def key(self, body):
        if "keycode" in body:
            code = self._int(body["keycode"], "keycode", 0, 300)
        else:
            name = body.get("key")
            if not isinstance(name, str) or name.upper() not in KEYS:
                raise AgentError(400, "key must be one of " + ", ".join(sorted(KEYS)))
            code = KEYS[name.upper()]
        self.adb.quick("input", "keyevent", code)

    def text(self, body):
        text = body.get("text")
        if not isinstance(text, str) or len(text) > MAX_TEXT or not TEXT_ALLOWED.match(text):
            raise AgentError(400, "text: up to %d letters, digits, spaces and . , _ @ : / + -" % MAX_TEXT)
        if text:
            #  `input text` takes %s for a space.
            self.adb.quick("input", "text", text.replace(" ", "%s"))

    def wake(self):
        self.adb.quick("input", "keyevent", KEYS["WAKEUP"])

    def app(self, body):
        """Close or start the Pokemon GO app; what it says goes in the answer."""
        action = body.get("action")
        package = body.get("package")
        if action not in APP_ACTIONS:
            raise AgentError(400, "action is " + ", ".join('"%s"' % a for a in APP_ACTIONS))
        if action == "list":
            #  The apps of the stores that have "pokemongo" in their name (as `pm list packages` says), the ones /v1/app may close and start.
            out = self.adb.run("shell", "pm", "list", "packages", "pokemongo")
            found = {line.split(":", 1)[1].strip() for line in out.splitlines() if line.startswith("package:")}
            return {"packages": sorted((p for p in found if APP_PACKAGE.match(p)), key=lambda p: (p != APP_MAIN, p))}
        if not isinstance(package, str) or not APP_PACKAGE.match(package):
            raise AgentError(400, "package is the name of a Pokemon GO app (com.nianticlabs.pokemongo...)")
        with self._launch_lock:
            if action == "stop":
                self.adb.run("shell", "am", "force-stop", package)
                return {}
            if action == "start":
                self._end_launch()
                #  `monkey` does not come back while the game is starting (it waits for the app): the caller looks
                #  at the screen meanwhile and asks how it went with "state".
                line = self.adb.line("shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1")
                try:
                    self._launch = subprocess.Popen(line, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                except FileNotFoundError:
                    raise AgentError(502, "adb is not installed here (sudo apt install adb)")
                return {}
            if action == "state":
                if self._launch is None:
                    raise AgentError(409, "the game was not started")
                code = self._launch.poll()
                if code is None:
                    return {"running": True, "code": 0, "error": ""}
                error = self._launch.stderr.read(APP_ERROR_BYTES).decode(errors="ignore") if self._launch.stderr else ""
                return {"running": False, "code": code, "error": error}
            self._end_launch()
            return {}

    def _end_launch(self):
        """Let go of the start command that still runs (the game itself goes on)."""
        launch, self._launch = self._launch, None
        if launch is None:
            return
        if launch.poll() is None:
            launch.kill()
        launch.wait()
        if launch.stderr:
            launch.stderr.close()


class Bot:
    """The Pokemon GO bot of Mobile/ as the agent shows it and starts it: a service called spin-stop that
    reads its switches from ~/gamebot_control.json. `home` is where its files are (the home folder of the
    user of the agent), `systemctl` the command that starts and stops services."""

    def __init__(self, home=None, systemctl=("sudo", "-n", "/usr/bin/systemctl"), status=("systemctl",), python=None):
        self.home = home or os.path.expanduser("~")
        self.systemctl = list(systemctl)
        self.status = list(status)
        #  The python that runs a test of the bot: the one of its environment (a test puts another here).
        self.python = list(python) if python else None
        self.lock = threading.Lock()
        self.test = {"key": "", "title": "", "proc": None, "t0": 0.0, "end": 0.0, "ok": None, "result": ""}
        self._chapters = (None, [])

    def _path(self, name):
        return os.path.join(self.home, name)

    def installed(self):
        return os.path.exists(self._path("gamebot.py"))

    def running(self):
        try:
            done = subprocess.run(self.status + ["is-active", BOT_SERVICE], capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return False
        return done.stdout.decode(errors="ignore").strip() == "active"

    def control(self):
        try:
            with open(self._path("gamebot_control.json"), "r", encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def file(self, name):
        """One of BOT_FILES of the home folder, as bytes; nothing else can be read."""
        if name not in BOT_FILES:
            raise AgentError(400, "name is one of " + ", ".join(BOT_FILES))
        try:
            with open(self._path(name), "rb") as handle:
                data = handle.read(BOT_FILE_BYTES + 1)
        except FileNotFoundError:
            raise AgentError(404, "the bot has no " + name)
        except OSError as error:
            raise AgentError(502, "%s cannot be read: %s" % (name, error))
        if len(data) > BOT_FILE_BYTES:
            raise AgentError(413, name + " is too big")
        return data

    def log_lines(self, count):
        try:
            with open(self._path("spin.log"), "rb") as handle:
                handle.seek(0, 2)
                handle.seek(max(handle.tell() - 60000, 0))
                lines = handle.read().decode("utf-8", errors="ignore").splitlines()
        except OSError:
            return []
        return lines[-count:]

    def state(self, lines):
        control = self.control()
        #  A switch that was never touched is on (but for a few), as the web interface of the bot shows it.
        options = {key: bool(control.get(key, key not in BOT_SWITCHES_OFF)) for key in BOT_SWITCHES}
        return {
            "installed": self.installed(), "running": self.running(), "options": options,
            "throw_target": control.get("throw_target", "realistic"),
            "daily_time": control.get("daily_time", "08:00"),
            "daily_max_min": control.get("daily_max_min", 480),
            "battle_app": control.get("battle_app", ""),
            "battle_league": control.get("battle_league", "Great League"),
            "battle_count": control.get("battle_count", 5),
            "today": self.today(),
            "battles": self.battles(),
            "test": self.test_state(),
            "log": self.log_lines(lines),
        }

    def today(self):
        """The counters of today as the bot keeps them: the last '(today: 6 caught, 0 fled, 3 stops, 2 won,
        1 lost)' of today's lines in its log (zero for the ones it has not counted yet, all zero on a new day)."""
        day = time.strftime("%Y-%m-%d")
        counters = dict.fromkeys(BOT_TODAY_COUNTERS, 0)
        try:
            with open(self._path("spin.log"), "rb") as handle:
                handle.seek(0, 2)
                handle.seek(max(handle.tell() - 400000, 0))
                lines = handle.read().decode("utf-8", errors="ignore").splitlines()
        except OSError:
            return dict(counters, day=day)
        for line in reversed(lines):
            if not line.startswith(day):
                if line[:4].isdigit():
                    break                       #  an older day: nothing of today yet
                continue
            found = BOT_TODAY.search(line)
            if found:
                for number, name in re.findall(r"(\d+) (\w+)", found.group(1)):
                    if name in counters:
                        counters[name] = int(number)
                break
        return dict(counters, day=day)

    def battles(self):
        """The GO Battle League matches of today, as the bot's log tells them: how many were won and lost, and
        the last twenty (time, league, result, whether it was given up). 'Reset' of the bot's web interface
        counts from that moment on, here too."""
        today = time.strftime("%Y-%m-%d")
        since = ""
        try:
            with open(self._path("battle_count_reset.json"), "r", encoding="utf-8") as handle:
                since = str(json.load(handle).get("at", ""))
        except (OSError, ValueError, AttributeError):
            pass
        won = lost = 0
        done = []
        league = ""
        try:
            with open(self._path("spin.log"), "rb") as handle:
                handle.seek(0, 2)
                handle.seek(max(handle.tell() - 2000000, 0))
                lines = handle.read().decode("utf-8", errors="ignore").splitlines()
        except OSError:
            lines = []
        for line in lines:
            if not line.startswith(today):
                continue
            found = BOT_BATTLE_SET.search(line)
            if found:
                league = found.group(1)
            found = BOT_BATTLE_DONE.search(line)
            if found and (not since or line[:19] > since):
                if found.group(1) == "win":
                    won += 1
                else:
                    lost += 1
                done.append({"time": line[11:16], "league": league, "result": found.group(1), "gave_up": bool(found.group(2))})
        return {"won": won, "lost": lost, "list": done[-20:]}

    def chapters(self):
        """The parts of the bot that can be run on their own, [{key, group, title, start, what}], from the
        bot's own chapters.py (read again when that file changes)."""
        path = self._path("chapters.py")
        try:
            stamp = os.stat(path).st_mtime
        except OSError:
            return []
        if self._chapters[0] != stamp:
            try:
                spec = importlib.util.spec_from_file_location("claudegg_bot_chapters", path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                found = [dict(c) for c in module.as_list()]
            except Exception:  # noqa: BLE001 - a file that cannot be read gives no tests
                found = []
            self._chapters = (stamp, found)
        return self._chapters[1]

    def _test_running(self):
        #  Until what the test said of itself is read (end is set last), it has not ended for the caller.
        return self.test["proc"] is not None and self.test["end"] == 0.0

    def test_state(self):
        running = self._test_running()
        began = self.test["t0"]
        seconds = int((time.time() if running else (self.test["end"] or time.time())) - began) if began else 0
        return {"key": self.test["key"], "title": self.test["title"], "running": running,
                "ok": None if running else self.test["ok"], "result": self.test["result"], "seconds": seconds}

    @staticmethod
    def _checked(body):
        """What is asked, checked: the switches that exist with true or false, a throw target of the list,
        a time as HH:MM and a time limit in minutes. Returns what is to be written to the control file."""
        wanted = {}
        options = body.get("options", {})
        if not isinstance(options, dict):
            raise AgentError(400, "options must be an object")
        for key, value in options.items():
            if key not in BOT_SWITCHES:
                raise AgentError(400, "%s is not an option of the bot" % key)
            if not isinstance(value, bool):
                raise AgentError(400, "%s must be true or false" % key)
            wanted[key] = value
        if "throw_target" in body:
            if body["throw_target"] not in BOT_THROW_TARGETS:
                raise AgentError(400, "throw_target must be one of %s" % ", ".join(BOT_THROW_TARGETS))
            wanted["throw_target"] = body["throw_target"]
        if "daily_time" in body:
            if not isinstance(body["daily_time"], str) or not BOT_DAILY_TIME.match(body["daily_time"]):
                raise AgentError(400, "daily_time must be HH:MM")
            wanted["daily_time"] = body["daily_time"]
        if "daily_max_min" in body:
            wanted["daily_max_min"] = Phone._int(body["daily_max_min"], "daily_max_min", 5, 1440)
        if "battle_app" in body:
            if not isinstance(body["battle_app"], str) or not BOT_BATTLE_APP.match(body["battle_app"]):
                raise AgentError(400, "battle_app must be empty (the Play Store app) or a Pokemon GO package")
            wanted["battle_app"] = body["battle_app"]
        if "battle_league" in body:
            if not isinstance(body["battle_league"], str) or not BOT_BATTLE_LEAGUE.match(body["battle_league"].strip()):
                raise AgentError(400, "battle_league must be the name of a league, like Great League")
            wanted["battle_league"] = body["battle_league"].strip()
        if "battle_count" in body:
            wanted["battle_count"] = Phone._int(body["battle_count"], "battle_count", BOT_BATTLE_COUNT[0], BOT_BATTLE_COUNT[1])
        return wanted

    def _write_control(self, wanted):
        control = self.control()
        control.update(wanted)
        path = self._path("gamebot_control.json")
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(control, handle)
        os.replace(temporary, path)

    def _service(self, action):
        try:
            done = subprocess.run(self.systemctl + [action, BOT_SERVICE], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as error:
            done_word = {"start": "started", "restart": "restarted", "stop": "stopped"}[action]
            raise AgentError(502, "the bot could not be %s: %s" % (done_word, error))
        if done.returncode != 0:
            said = done.stderr.decode(errors="ignore").strip() or done.stdout.decode(errors="ignore").strip()
            raise AgentError(502, "systemctl %s %s failed (%d): %s%s" % (
                action, BOT_SERVICE, done.returncode, said[-200:],
                " - the user of the agent needs the sudoers rule of the Installation page" if "password" in said else ""))

    def start(self, body):
        wanted = self._checked(body)
        if not self.installed():
            raise AgentError(409, "the Pokemon GO bot is not installed on this Raspberry Pi (Mobile/install.sh)")
        with self.lock:
            if self._test_running():
                raise AgentError(409, "a test of the bot runs (%s): stop it first" % self.test["title"])
            self._write_control(wanted)
            if body.get("daily_now") is True:
                #  What the Start button of the bot's web interface does: the daily run begins at once.
                with open(self._path("gamebot_force.json"), "w", encoding="utf-8") as handle:
                    handle.write(str(time.time()))
            #  'start' on a service that runs does nothing: a program that is started again begins afresh.
            self._service("restart" if self.running() else "start")

    def stop(self):
        with self.lock:
            self._stop_test()
            self._service("stop")

    def _stop_test(self):
        proc = self.test["proc"]
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()            #  (the test says 'stopped' and goes back to the map: that takes a while)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)

    def stop_test(self):
        with self.lock:
            self._stop_test()

    def run_test(self, body):
        """One part of the bot on its own (`gamebot.py chapter <key>`, what the Test of the bot's web interface
        does): the bot's service is stopped, the settings asked for are written, the test runs, and what it
        says of itself ('TEST <key>: done - ...') is its result. The game is left on the screen it is on."""
        key = body.get("key")
        if not isinstance(key, str) or not BOT_CHAPTER_KEY.match(key):
            raise AgentError(400, "key must be the name of a test")
        wanted = self._checked(body)
        if not self.installed():
            raise AgentError(409, "the Pokemon GO bot is not installed on this Raspberry Pi (Mobile/install.sh)")
        titles = {chapter["key"]: chapter["title"] for chapter in self.chapters()}
        if not titles:
            raise AgentError(409, "the bot on this Raspberry Pi has no tests (chapters.py is missing: update it)")
        if key not in titles:
            raise AgentError(400, "%s is not a test of the bot" % key)
        with self.lock:
            if self._test_running():
                raise AgentError(409, "a test is running already (%s)" % self.test["title"])
            if self.running():
                self._service("stop")
                until = time.time() + BOT_TEST_STOP_WAIT
                while self.running() and time.time() < until:
                    time.sleep(0.25)
                if self.running():
                    raise AgentError(502, "the bot did not stop")
            self._write_control(wanted)
            os.makedirs(self._path("debug"), exist_ok=True)
            try:
                offset = os.path.getsize(self._path("spin.log"))
            except OSError:
                offset = 0
            python = self.python
            if python is None:
                venv = self._path(os.path.join("gbvenv", "bin", "python"))
                python = [venv] if os.path.exists(venv) else [sys.executable]
            with open(self._path(os.path.join("debug", "test_stderr.txt")), "wb") as errors:
                try:
                    proc = subprocess.Popen(python + [self._path("gamebot.py"), "chapter", key], cwd=self.home,
                                            stdout=subprocess.DEVNULL, stderr=errors, start_new_session=True)
                except OSError as error:
                    raise AgentError(502, "the test could not be started: %s" % error)
            self.test.update(key=key, title=titles[key], proc=proc, t0=time.time(), end=0.0, ok=None, result="")
            threading.Thread(target=self._watch_test, args=(proc, key, offset), daemon=True, name="bot-test").start()

    def _watch_test(self, proc, key, offset):
        proc.wait()
        found = re.compile(BOT_TEST_DONE % re.escape(key))
        ok, text = None, ""
        try:
            with open(self._path("spin.log"), "rb") as handle:
                size = handle.seek(0, 2)
                handle.seek(offset if offset <= size else 0)
                lines = handle.read().decode("utf-8", errors="ignore").splitlines()
        except OSError:
            lines = []
        for line in reversed(lines):
            match = found.search(line)
            if match:
                ok, text = match.group(1) == "done", match.group(2)
                break
        if ok is None:           #  it never got to its last line: a crash at the start
            said = ""
            try:
                with open(self._path(os.path.join("debug", "test_stderr.txt")), "r", encoding="utf-8", errors="ignore") as handle:
                    said = " | ".join(handle.read().strip().splitlines()[-3:])
            except OSError:
                pass
            ok, text = False, "ended without a result (exit code %s)%s" % (proc.returncode, ": " + said if said else "")
        self.test.update(ok=ok, result=text, end=time.time())


def read_or_make_token(path):
    """The token of this agent: made at the first start, readable by its user only."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            token = handle.read().strip()
        if len(token) >= 16:
            return token
    except OSError:
        pass
    token = secrets.token_hex(16)
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(token + "\n")
    return token


#  The page of GET / and GET /status. It holds nothing secret (the token is typed in the browser, kept in the
#  tab, and sent in a header to the endpoints above), so it is served without one. It is one file, with no
#  address of anywhere else in it; the browser is told (Content-Security-Policy) to run nothing but this
#  script and style and to speak to nobody but this agent, and the page puts what the agent says on the screen
#  as text, never as markup.
STATUS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Claude GG phone</title>
<style>
:root { color-scheme: dark; --bg: #16181e; --panel: #20232b; --line: #313644; --text: #eceef3; --muted: #a3a9ba; --ok: #74d38f; --warn: #ff8f61; --accent: #6ab8ff; }
* { box-sizing: border-box; }
[hidden] { display: none !important; }
body { margin: 0; background: var(--bg); color: var(--text); font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 1040px; margin: 0 auto; padding: 20px 16px 40px; }
h1 { display: flex; align-items: center; gap: 10px; margin: 0; font-size: 1.5rem; font-weight: 650; letter-spacing: -0.01em; }
h2 { margin: 0 0 12px; font-size: 1rem; font-weight: 600; }
p { margin: 0 0 10px; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
header { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 16px; margin-bottom: 20px; }
.who { margin: 0 0 0 auto; color: var(--muted); }
.dot { flex: none; width: 12px; height: 12px; border-radius: 50%; background: var(--muted); }
.dot.run { background: var(--ok); box-shadow: 0 0 0 4px rgba(116, 211, 143, 0.18); }
.dot.stop { background: var(--warn); }
.grid { display: grid; grid-template-columns: minmax(220px, 320px) 1fr; gap: 24px; align-items: start; }
.phone { position: sticky; top: 12px; margin: 0; padding: 10px; border: 2px solid var(--line); border-radius: 28px; background: #0b0c10; }
.phone img { display: block; width: 100%; height: auto; border-radius: 18px; background: #000; }
.phone figcaption { margin: 8px 4px 0; color: var(--muted); font-size: 0.85rem; text-align: center; }
section { margin-bottom: 16px; padding: 16px 18px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); }
.counts { display: flex; flex-wrap: wrap; gap: 12px 28px; margin: 0; }
.counts div { display: flex; flex-direction: column-reverse; min-width: 64px; }
.counts dt { color: var(--muted); font-size: 0.85rem; }
.counts dd { margin: 0; font-size: 2rem; font-weight: 650; line-height: 1.1; font-variant-numeric: tabular-nums; }
.muted { color: var(--muted); }
.list, .chips { margin: 0; padding: 0; list-style: none; }
.list li { display: flex; gap: 12px; padding: 3px 0; font-variant-numeric: tabular-nums; }
.list .time { color: var(--muted); }
.list .win { color: var(--ok); }
.list .loss { color: var(--warn); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chips li { padding: 2px 10px; border: 1px solid var(--line); border-radius: 999px; font-size: 0.85rem; }
pre { margin: 0; max-height: 320px; overflow: auto; color: #cfd3df; font: 12.5px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; white-space: pre-wrap; word-break: break-word; }
#login { max-width: 420px; margin: 8vh auto 0; }
#login label { display: block; margin: 16px 0 4px; color: var(--muted); }
#login input { width: 100%; padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); color: var(--text); font: inherit; }
#login button { margin-top: 12px; padding: 10px 18px; border: 0; border-radius: 8px; background: var(--accent); color: #0b0c10; font: inherit; font-weight: 600; cursor: pointer; }
#login-error { min-height: 1.5em; margin-top: 10px; color: var(--warn); }
@media (max-width: 760px) { .grid { grid-template-columns: 1fr; } .phone { position: static; max-width: 300px; margin: 0 auto; } }
</style>
</head>
<body>
<main>
<form id="login" hidden>
<h1>Claude GG phone</h1>
<p class="muted">Type the token of this agent. It stays in this tab until the tab is closed. On the Raspberry Pi it is printed by <code>claudegg_agent.py --print-token</code>.</p>
<label for="token">Token</label>
<input id="token" type="password" autocomplete="off" required>
<button type="submit">Open</button>
<p id="login-error" role="alert"></p>
</form>
<div id="app" hidden>
<header>
<h1><span id="dot" class="dot"></span><span id="state">Connecting</span></h1>
<p id="phone-name" class="who"></p>
</header>
<div class="grid">
<figure class="phone">
<img id="screen" alt="The screen of the phone" hidden>
<figcaption id="screen-note">Waiting for the first picture</figcaption>
</figure>
<div>
<section>
<h2>Today</h2>
<dl class="counts">
<div><dt>caught</dt><dd id="n-caught">0</dd></div>
<div><dt>fled</dt><dd id="n-fled">0</dd></div>
<div><dt>stops</dt><dd id="n-stops">0</dd></div>
<div><dt>won</dt><dd id="n-won">0</dd></div>
<div><dt>lost</dt><dd id="n-lost">0</dd></div>
</dl>
</section>
<section>
<h2>GO Battle League</h2>
<p id="battle-plan" class="muted"></p>
<ul id="battle-list" class="list"></ul>
</section>
<section>
<h2>Switched on</h2>
<ul id="options" class="chips"></ul>
</section>
<section>
<h2>Log</h2>
<pre id="log"></pre>
</section>
</div>
</div>
</div>
</main>
<script>
(function () {
  "use strict";
  const KEY = "claudegg-agent-token";
  const BOT_EVERY = 4000, SCREEN_EVERY = 10000, INFO_EVERY = 60000;
  const $ = (id) => document.getElementById(id);
  let token = "";
  let timers = [];
  const shot = { url: "", at: 0, busy: false };
  let bot = { busy: false }, info = { busy: false };

  function put(id, value) { $(id).textContent = String(value); }

  function api(path) {
    return fetch(path, { headers: { "Authorization": "Bearer " + token }, cache: "no-store" }).then((answer) => {
      if (answer.status === 401) {
        const error = new Error("The token is wrong.");
        error.auth = true;
        throw error;
      }
      if (!answer.ok) {
        return answer.json().catch(() => ({})).then((body) => { throw new Error(body.error || ("HTTP " + answer.status)); });
      }
      return answer;
    });
  }

  function needToken(message) {
    timers.forEach(clearInterval);
    timers = [];
    try { sessionStorage.removeItem(KEY); } catch (e) { /* no storage: the token is asked again next time */ }
    token = "";
    $("app").hidden = true;
    $("login").hidden = false;
    put("login-error", message || "");
    $("token").value = "";
    $("token").focus();
  }

  function setState(text, kind) {
    put("state", text);
    $("dot").className = "dot" + (kind ? " " + kind : "");
  }

  function renderBot(state) {
    if (!state.installed) {
      setState("The bot is not installed", "");
    } else if (state.test && state.test.running) {
      setState("Testing: " + state.test.title, "run");
    } else if (state.running) {
      setState("Running", "run");
    } else {
      setState("Stopped", "stop");
    }
    const today = state.today || {};
    ["caught", "fled", "stops", "won", "lost"].forEach((name) => put("n-" + name, today[name] || 0));

    const battles = state.battles || { won: 0, lost: 0, list: [] };
    const on = state.options && state.options.battle;
    put("battle-plan", on
      ? state.battle_league + ", " + state.battle_count + " battles a run. Today: " + battles.won + " won, " + battles.lost + " lost."
      : "Battles are switched off.");
    const list = $("battle-list");
    list.textContent = "";
    battles.list.slice().reverse().forEach((entry) => {
      const item = document.createElement("li");
      const time = document.createElement("span");
      time.className = "time";
      time.textContent = entry.time;
      const result = document.createElement("span");
      result.className = entry.result === "win" ? "win" : "loss";
      result.textContent = (entry.result === "win" ? "Won" : "Lost") + (entry.gave_up ? " (given up)" : "");
      const league = document.createElement("span");
      league.textContent = entry.league;
      item.append(time, result, league);
      list.append(item);
    });

    const options = $("options");
    options.textContent = "";
    Object.keys(state.options || {}).filter((key) => state.options[key]).forEach((key) => {
      const item = document.createElement("li");
      item.textContent = key.replace(/_/g, " ");
      options.append(item);
    });

    const log = $("log");
    const atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 8;
    log.textContent = (state.log || []).join("\n");
    if (atEnd) { log.scrollTop = log.scrollHeight; }
  }

  function guarded(slot, work, failed) {
    if (slot.busy || document.hidden) { return; }
    slot.busy = true;
    work().catch((error) => {
      if (error.auth) { needToken(error.message); } else { failed(error); }
    }).then(() => { slot.busy = false; });
  }

  function refreshBot() {
    guarded(bot, () => api("/v1/bot?lines=15").then((a) => a.json()).then(renderBot),
      (error) => setState("The agent does not answer: " + error.message, ""));
  }

  function refreshInfo() {
    guarded(info, () => api("/v1/info").then((a) => a.json()).then((phone) => {
      put("phone-name", [phone.model, phone.android ? "Android " + phone.android : "", phone.width + " x " + phone.height].filter(Boolean).join(", "));
    }), () => put("phone-name", "The phone does not answer"));
  }

  function refreshScreen() {
    guarded(shot, () => api("/v1/screen").then((a) => a.blob()).then((blob) => {
      const image = $("screen");
      const before = shot.url;
      shot.url = URL.createObjectURL(blob);
      shot.at = Date.now();
      image.src = shot.url;
      image.hidden = false;
      if (before) { URL.revokeObjectURL(before); }
      showAge();
    }), (error) => put("screen-note", "No picture: " + error.message));
  }

  function showAge() {
    if (!shot.at) { return; }
    const seconds = Math.max(0, Math.round((Date.now() - shot.at) / 1000));
    put("screen-note", "Picture of " + (seconds < 2 ? "now" : seconds + " s ago"));
  }

  function refreshAll() { refreshBot(); refreshInfo(); refreshScreen(); }

  function start() {
    $("login").hidden = true;
    $("app").hidden = false;
    put("login-error", "");
    refreshAll();
    timers = [setInterval(refreshBot, BOT_EVERY), setInterval(refreshScreen, SCREEN_EVERY),
              setInterval(refreshInfo, INFO_EVERY), setInterval(showAge, 1000)];
  }

  document.addEventListener("visibilitychange", () => { if (!document.hidden && token) { refreshAll(); } });

  $("login").addEventListener("submit", (event) => {
    event.preventDefault();
    token = $("token").value.trim();
    if (!token) { return; }
    try { sessionStorage.setItem(KEY, token); } catch (e) { /* kept in memory only */ }
    start();
  });

  //  A link with #token=... (a bookmark on the phone) opens the page at once; the token is taken out of the
  //  address and never goes to the agent in a request line.
  if (location.hash.indexOf("#token=") === 0) {
    try { token = decodeURIComponent(location.hash.slice(7)); } catch (e) { token = ""; }
    history.replaceState(null, "", location.pathname + location.search);
    try { if (token) { sessionStorage.setItem(KEY, token); } } catch (e) { /* kept in memory only */ }
  }
  if (!token) {
    try { token = sessionStorage.getItem(KEY) || ""; } catch (e) { token = ""; }
  }
  if (token) { start(); } else { needToken(""); }
})();
</script>
</body>
</html>
"""


def _status_page():
    html = STATUS_HTML.encode("utf-8")
    hashes = []
    for tag in ("script", "style"):
        found = re.search(r"<%s>(.*?)</%s>" % (tag, tag), STATUS_HTML, re.S)
        digest = hashlib.sha256(found.group(1).encode("utf-8")).digest()
        hashes.append("'sha256-%s'" % base64.b64encode(digest).decode("ascii"))
    policy = ("default-src 'none'; script-src %s; style-src %s; img-src blob:; connect-src 'self'; "
              "base-uri 'none'; form-action 'none'; frame-ancestors 'none'" % tuple(hashes))
    return html, {"Content-Security-Policy": policy, "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"}


STATUS_PAGE, STATUS_PAGE_HEADERS = _status_page()


def make_handler(phone, token, quiet=True):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ClaudeGGAgent/" + VERSION
        protocol_version = "HTTP/1.0"      #  one answer per connection: the end of the answer is the close
        #  TCP_NODELAY: an answer is written in pieces (the headers, then the body; a picture of the live stream,
        #  then the line after it). Without it the system holds back a small last piece until the computer has
        #  acknowledged the one before, and Windows acknowledges late on purpose (up to 200 ms): every tap and
        #  every picture could wait that long for its last bytes.
        disable_nagle_algorithm = True

        def log_message(self, fmt, *args):
            if not quiet:
                sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def _send(self, status, body, content_type="application/json", headers=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self):
            given = self.headers.get("Authorization", "")
            return given.startswith("Bearer ") and hmac.compare_digest(given[7:].strip().encode(), token.encode())

        def _body(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise AgentError(400, "Content-Length is not a number")
            if length < 0 or length > MAX_BODY:
                raise AgentError(413, "the request is too large")
            raw = self.rfile.read(length) if length else b""
            if not raw:
                return {}
            try:
                body = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise AgentError(400, "the body is not JSON")
            if not isinstance(body, dict):
                raise AgentError(400, "the body must be a JSON object")
            return body

        def _video(self):
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            values = dict(part.split("=", 1) for part in query.split("&") if "=" in part)

            def number(name, limits):
                try:
                    value = int(values.get(name, limits[2]))
                except ValueError:
                    raise AgentError(400, "%s must be a whole number" % name)
                if value < limits[0] or value > limits[1]:
                    raise AgentError(400, "%s must be from %d to %d" % (name, limits[0], limits[1]))
                return value

            fps = number("fps", VIDEO_FPS)
            width = number("width", VIDEO_WIDTH)
            video = phone.video
            video.open(fps, width)
            try:
                frame, serial, alive = video.first(VIDEO_FIRST_PICTURE_SECONDS)
                if frame is None:
                    raise AgentError(502, video.error or "the phone gave no picture (is the screen on and unlocked?)")
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                while frame is not None:
                    #  In one piece: the picture arrives whole, at once.
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(frame)
                                     + frame + b"\r\n")
                    self.wfile.flush()
                    if not alive:
                        break
                    frame, serial, alive = video.wait(serial, VIDEO_REPEAT_SECONDS)
            except OSError:
                pass        #  the viewer went away
            finally:
                video.close()

        def _handle(self, method):
            try:
                path = self.path.split("?", 1)[0]
                if method == "GET" and path in ("/", "/status"):
                    return self._send(200, STATUS_PAGE, "text/html; charset=utf-8", STATUS_PAGE_HEADERS)
                if method == "GET" and path == "/v1/ping":
                    return self._send(200, {"ok": True, "agent": "claudegg-agent", "version": VERSION,
                                           "features": list(FEATURES)})
                if not self._authorized():
                    return self._send(401, {"error": "the token is missing or wrong"})
                #  No lock: a tap does not wait for a picture that is being taken.
                if method == "GET" and path == "/v1/info":
                    return self._send(200, dict(phone.info(), agent="claudegg-agent", version=VERSION,
                                                    features=list(FEATURES)))
                if method == "GET" and path == "/v1/heat":
                    return self._send(200, dict(phone.heat(), ok=True))
                if method == "GET" and path == "/v1/display":
                    query = self.path.split("?", 1)[1] if "?" in self.path else ""
                    values = dict(part.split("=", 1) for part in query.split("&") if "=" in part)
                    return self._send(200, dict(phone.display_state(values.get("only")), ok=True))
                if method == "POST" and path == "/v1/display":
                    phone.display_change(self._body())
                    return self._send(200, {"ok": True})
                if method == "GET" and path == "/v1/power":
                    query = self.path.split("?", 1)[1] if "?" in self.path else ""
                    values = dict(part.split("=", 1) for part in query.split("&") if "=" in part)
                    return self._send(200, dict(phone.power(values.get("only")), ok=True))
                if method == "POST" and path == "/v1/unlock":
                    self._body()
                    phone.unlock()
                    return self._send(200, {"ok": True})
                if method == "GET" and path == "/v1/video":
                    return self._video()
                if method == "GET" and path == "/v1/screen":
                    png = phone.screen()
                    size = png_size(png) or (0, 0)
                    return self._send(200, png, "image/png",
                                      {"X-Screen-Width": str(size[0]), "X-Screen-Height": str(size[1])})
                actions = {"/v1/tap": phone.tap, "/v1/swipe": phone.swipe, "/v1/swipes": phone.swipes,
                           "/v1/key": phone.key, "/v1/text": phone.text}
                if method == "POST" and path in actions:
                    actions[path](self._body())
                    return self._send(200, {"ok": True})
                if method == "POST" and path == "/v1/touch":
                    return self._send(200, dict(phone.touch(self._body()), ok=True))
                if method == "POST" and path == "/v1/app":
                    return self._send(200, dict(phone.app(self._body()), ok=True))
                if method == "GET" and path == "/v1/bot":
                    query = self.path.split("?", 1)[1] if "?" in self.path else ""
                    values = dict(part.split("=", 1) for part in query.split("&") if "=" in part)
                    try:
                        lines = int(values.get("lines", BOT_LOG_LINES[2]))
                    except ValueError:
                        raise AgentError(400, "lines must be a whole number")
                    if lines < BOT_LOG_LINES[0] or lines > BOT_LOG_LINES[1]:
                        raise AgentError(400, "lines must be from %d to %d" % (BOT_LOG_LINES[0], BOT_LOG_LINES[1]))
                    return self._send(200, phone.bot.state(lines))
                if method == "GET" and path == "/v1/bot/file":
                    query = self.path.split("?", 1)[1] if "?" in self.path else ""
                    values = dict(part.split("=", 1) for part in query.split("&") if "=" in part)
                    return self._send(200, phone.bot.file(values.get("name", "")), "application/json")
                if method == "POST" and path == "/v1/bot/start":
                    phone.bot.start(self._body())
                    return self._send(200, {"ok": True})
                if method == "POST" and path == "/v1/bot/stop":
                    self._body()
                    phone.bot.stop()
                    return self._send(200, {"ok": True})
                if method == "GET" and path == "/v1/bot/tests":
                    return self._send(200, {"tests": phone.bot.chapters()})
                if method == "POST" and path == "/v1/bot/test":
                    phone.bot.run_test(self._body())
                    return self._send(200, {"ok": True})
                if method == "POST" and path == "/v1/bot/test/stop":
                    self._body()
                    phone.bot.stop_test()
                    return self._send(200, {"ok": True})
                if method == "POST" and path == "/v1/wake":
                    self._body()
                    phone.wake()
                    return self._send(200, {"ok": True})
                self._send(404 if method in ("GET", "POST") else 405, {"error": "no such endpoint"})
            except AgentError as error:
                self._send(error.status, {"error": error.message})
            except Exception as error:  # noqa: BLE001 - the caller is told, the agent goes on
                self._send(500, {"error": "%s: %s" % (type(error).__name__, error)})

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_PUT(self):
            self._handle("PUT")

        def do_DELETE(self):
            self._handle("DELETE")

    return Handler


def make_server(phone, token, host, port, quiet=True):
    server = ThreadingHTTPServer((host, port), make_handler(phone, token, quiet))
    server.daemon_threads = True
    return server


def measure(adb, count=20, out=None):
    """How long a command that does nothing (`input keyevent 0`, a key with no meaning) takes, the old way
    (a new `adb shell` each time) and through the shell that stays open. Prints the middle and slowest
    time of each, in milliseconds; gives them as a dict too."""
    out = out or sys.stdout

    def times(do):
        taken = []
        for _ in range(count):
            start = time.perf_counter()
            do()
            taken.append((time.perf_counter() - start) * 1000.0)
        taken.sort()
        return {"middle": taken[len(taken) // 2], "slowest": taken[-1]}

    session = ShellSession(adb)
    kept = Adb(adb.command, adb.serial, adb.timeout)
    kept.session = session
    try:
        kept.quick("input", "keyevent", 0)            # the shell is started before the clock runs
        result = {"new_shell": times(lambda: adb.run("shell", "input", "keyevent", 0)),
                  "kept_shell": times(lambda: kept.quick("input", "keyevent", 0))}
    except AgentError as error:
        print("The phone did not answer: %s" % error.message, file=out)
        return 1
    finally:
        session.close()
    for name, label in (("new_shell", "a new adb shell each time"), ("kept_shell", "the shell that stays open")):
        print("%-28s middle %6.1f ms, slowest %6.1f ms" % (label + ":", result[name]["middle"], result[name]["slowest"]), file=out)
    print("A tap waits %.0f ms less before it starts." % (result["new_shell"]["middle"] - result["kept_shell"]["middle"]), file=out)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Claude GG agent: the hands and eyes of an Android phone.")
    parser.add_argument("--host", default="0.0.0.0", help="the address to listen on (0.0.0.0: the whole network)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="the port (0: any free one; it is printed)")
    parser.add_argument("--adb", default="adb", help="the adb program")
    parser.add_argument("--adb-arg", action="append", default=[], help="an argument before the ones of adb (for tests)")
    parser.add_argument("--serial", default=None, help="the phone, when more than one is connected")
    parser.add_argument("--display", default=None, help="the display to take the picture of (a foldable has two)")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="the ffmpeg program (for the live picture)")
    parser.add_argument("--video-cmd", default=None, help="a program that writes JPEG pictures to its output, in place of screenrecord and ffmpeg (for tests)")
    parser.add_argument("--video-arg", action="append", default=[], help="an argument of --video-cmd")
    parser.add_argument("--bot-home", default=None, help="where the Pokemon GO bot's files are (default: the home folder; for tests)")
    parser.add_argument("--systemctl", action="append", default=None, help="the command that starts and stops the bot's service, one argument at a time (for tests)")
    parser.add_argument("--bot-python", action="append", default=None, help="the python that runs a test of the bot, one argument at a time (for tests)")
    parser.add_argument("--token-file", default=os.path.expanduser("~/.claudegg-agent/token"))
    parser.add_argument("--print-token", action="store_true", help="print the token and end")
    parser.add_argument("--version", action="version", version=VERSION, help="print the version of the agent and end")
    parser.add_argument("--verbose", action="store_true", help="log every request")
    parser.add_argument("--no-shell-session", action="store_true",
                        help="start a new `adb shell` for every tap (slower; the way of agent 0.2.0)")
    parser.add_argument("--measure", action="store_true",
                        help="measure how long a command takes on the phone, with and without the shell that stays open, and end")
    args = parser.parse_args(argv)

    token = read_or_make_token(args.token_file)
    if args.print_token:
        print(token)
        return 0
    adb = Adb([args.adb] + args.adb_arg, args.serial)
    if args.measure:
        return 0 if isinstance(measure(adb), dict) else 1
    if not args.no_shell_session:
        adb.session = ShellSession(adb)
    video = VideoPipeline(adb, args.display, [args.video_cmd] + args.video_arg if args.video_cmd else None, args.ffmpeg)
    python = tuple(args.bot_python) if args.bot_python else None
    bot = Bot(args.bot_home, tuple(args.systemctl), tuple(args.systemctl), python) if args.systemctl else Bot(args.bot_home, python=python)
    phone = Phone(adb, args.display, video, bot)
    server = make_server(phone, token, args.host, args.port, quiet=not args.verbose)
    print("Claude GG agent %s listening on port %d" % (VERSION, server.server_address[1]), flush=True)
    print("The token is in %s" % args.token_file, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
