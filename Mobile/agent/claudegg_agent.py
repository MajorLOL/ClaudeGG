#!/usr/bin/env python3
"""Claude GG agent: the hands and eyes of an Android phone, for a Raspberry Pi.

Claude GG (the program on the computer) does the thinking: it looks at the picture of the phone and
decides where to tap. This small program on the Raspberry Pi, that has the phone on a USB cable, does
only what it is asked: a picture of the screen, a tap, a swipe, a key. It is the "microcontroller" of a
phone, the way a Pico is that of a Nintendo Switch.

It speaks HTTP with JSON, on the local network, and wants a token (made the first time it starts, kept
in ~/.claudegg-agent/token) in the header "Authorization: Bearer <token>". It opens no shell: what it can
do is the list of the endpoints below, and the arguments are checked before an `adb` command is made
(a list of arguments, never a line for a shell).

    GET  /v1/ping                       {"ok": true}                            (no token)
    GET  /v1/info                       the phone: model, android, width, height
    GET  /v1/screen                     the screen as a PNG
    POST /v1/tap     {x, y, ms}         a press of ms milliseconds (120)
    POST /v1/swipe   {x1, y1, x2, y2, ms}
    POST /v1/swipes  {strokes: [[x1, y1, x2, y2, ms], ...]}   one after the other, in ONE adb command
    POST /v1/key     {key: "BACK"}      or {keycode: 4}
    POST /v1/text    {text: "..."}      letters, digits and . , _ @ : / + - and spaces
    POST /v1/wake                       wakes the screen

Only the standard library is used, so it runs on the Pi as it is. Part of Claude GG
(https://github.com/MajorLOL/ClaudeGG); MIT license like the rest of this folder.
"""

import argparse
import hmac
import json
import os
import re
import secrets
import struct
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.1.0"
DEFAULT_PORT = 8765
MAX_BODY = 64 * 1024
MAX_STROKES = 50
MAX_COORDINATE = 20000
MAX_MS = 10000
MAX_TEXT = 200
ADB_TIMEOUT = 30

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

    def run(self, *args, binary=False):
        line = list(self.command)
        if self.serial:
            line += ["-s", self.serial]
        line += [str(a) for a in args]
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


def png_size(data):
    """(width, height) of a PNG, from its header, or None."""
    start = data.find(b"\x89PNG\r\n\x1a\n")
    if start < 0 or len(data) < start + 24:
        return None
    width, height = struct.unpack(">II", data[start + 16:start + 24])
    return width, height


class Phone:
    """What can be done with the phone: the endpoints, with their arguments checked."""

    def __init__(self, adb, display=None):
        self.adb = adb
        self.display = display

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
        #  A press of a moment: Pokemon GO (Unity) misses a very short tap.
        self.adb.run("shell", "input", "swipe", x, y, x, y, ms)

    def swipe(self, body):
        x1 = self._int(body.get("x1"), "x1")
        y1 = self._int(body.get("y1"), "y1")
        x2 = self._int(body.get("x2"), "x2")
        y2 = self._int(body.get("y2"), "y2")
        ms = self._int(body.get("ms", 300), "ms", 1, MAX_MS)
        self.adb.run("shell", "input", "swipe", x1, y1, x2, y2, ms)

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
        self.adb.run("shell", "; ".join(parts))

    def key(self, body):
        if "keycode" in body:
            code = self._int(body["keycode"], "keycode", 0, 300)
        else:
            name = body.get("key")
            if not isinstance(name, str) or name.upper() not in KEYS:
                raise AgentError(400, "key must be one of " + ", ".join(sorted(KEYS)))
            code = KEYS[name.upper()]
        self.adb.run("shell", "input", "keyevent", code)

    def text(self, body):
        text = body.get("text")
        if not isinstance(text, str) or len(text) > MAX_TEXT or not TEXT_ALLOWED.match(text):
            raise AgentError(400, "text: up to %d letters, digits, spaces and . , _ @ : / + -" % MAX_TEXT)
        if text:
            #  `input text` takes %s for a space.
            self.adb.run("shell", "input", "text", text.replace(" ", "%s"))

    def wake(self):
        self.adb.run("shell", "input", "keyevent", KEYS["WAKEUP"])


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


def make_handler(phone, token, quiet=True):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ClaudeGGAgent/" + VERSION
        protocol_version = "HTTP/1.0"      #  one answer per connection: the end of the answer is the close

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

        def _handle(self, method):
            try:
                path = self.path.split("?", 1)[0]
                if method == "GET" and path == "/v1/ping":
                    return self._send(200, {"ok": True, "agent": "claudegg-agent", "version": VERSION})
                if not self._authorized():
                    return self._send(401, {"error": "the token is missing or wrong"})
                #  No lock: a tap does not wait for a picture that is being taken.
                if method == "GET" and path == "/v1/info":
                    return self._send(200, dict(phone.info(), agent="claudegg-agent", version=VERSION))
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


def main(argv=None):
    parser = argparse.ArgumentParser(description="Claude GG agent: the hands and eyes of an Android phone.")
    parser.add_argument("--host", default="0.0.0.0", help="the address to listen on (0.0.0.0: the whole network)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="the port (0: any free one; it is printed)")
    parser.add_argument("--adb", default="adb", help="the adb program")
    parser.add_argument("--adb-arg", action="append", default=[], help="an argument before the ones of adb (for tests)")
    parser.add_argument("--serial", default=None, help="the phone, when more than one is connected")
    parser.add_argument("--display", default=None, help="the display to take the picture of (a foldable has two)")
    parser.add_argument("--token-file", default=os.path.expanduser("~/.claudegg-agent/token"))
    parser.add_argument("--print-token", action="store_true", help="print the token and end")
    parser.add_argument("--verbose", action="store_true", help="log every request")
    args = parser.parse_args(argv)

    token = read_or_make_token(args.token_file)
    if args.print_token:
        print(token)
        return 0
    phone = Phone(Adb([args.adb] + args.adb_arg, args.serial), args.display)
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
