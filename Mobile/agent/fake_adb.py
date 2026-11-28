#!/usr/bin/env python3
"""A phone that is not there: what `adb` would say, for the tests of the agent (and of Claude GG's
connection to it). Every call is written to the file in FAKE_ADB_LOG, one line each."""

import os
import re
import struct
import sys
import zlib


def png(width, height, colour):
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    row = b"\x00" + bytes(colour) * width
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * height))
            + chunk(b"IEND", b""))


SESSION_LINE = re.compile(r"^\{ (.*) ; \} </dev/null 2>&1; echo (\S+) \$\?$")


def session(log, off_file):
    """`adb shell` with no command: a shell that reads its commands, one a line (the agent's
    ShellSession). Each is written to the log as `adb shell <command>` would be. A phone that goes
    off ends it, as it ends a real one."""
    for line in sys.stdin:
        if off_file and os.path.exists(off_file):
            sys.stdout.write("error: device offline\n")
            sys.stdout.flush()
            return 1
        found = SESSION_LINE.match(line.rstrip("\r\n"))
        if not found:
            sys.stdout.write("sh: not a line of the agent: %s\n" % line.strip())
            sys.stdout.flush()
            continue
        command, mark = found.groups()
        if log:
            with open(log, "a", encoding="utf-8") as handle:
                handle.write("shell " + command + "\n")
        code = 0
        if os.environ.get("FAKE_SHELL_FAIL") and command.startswith(os.environ["FAKE_SHELL_FAIL"]):
            sys.stdout.write("Error: the command failed\n")
            code = 1
        sys.stdout.write("%s %d\n" % (mark, code))
        sys.stdout.flush()
    return 0


def main(argv):
    log = os.environ.get("FAKE_ADB_LOG")
    rest = argv[2:] if argv[:1] == ["-s"] else argv
    off_file = os.environ.get("FAKE_ADB_FAIL_FILE")
    if rest == ["shell"]:
        if os.environ.get("FAKE_ADB_FAIL") or (off_file and os.path.exists(off_file)):
            sys.stderr.write("error: device offline\n")
            return 1
        return session(log, off_file)
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(" ".join(argv) + "\n")
    args = list(argv)
    if args[:2] == ["-s", args[1] if len(args) > 1 else ""]:
        args = args[2:]
    if os.environ.get("FAKE_ADB_FAIL") or (off_file and os.path.exists(off_file)):
        sys.stderr.write("error: device offline\n")
        return 1
    if args[:2] == ["exec-out", "screencap"]:
        #  Some noise before the picture, as a real adb can give.
        sys.stdout.buffer.write(b"noise\n" + png(48, 96, (200, 30, 30)))
    elif args[:2] == ["exec-out", "screenrecord"]:
        #  A moving test picture as H.264, when ffmpeg can make one (a test of the whole live pipeline).
        import subprocess
        try:
            return subprocess.call(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=270x480:rate=30",
                                    "-t", "20", "-pix_fmt", "yuv420p", "-f", "h264", "-"])
        except FileNotFoundError:
            sys.stderr.write("error: no ffmpeg to make a picture with\n")
            return 1
    elif args[:2] == ["shell", "monkey"]:
        #  The command that starts the game: it does not come back while the game starts (FAKE_MONKEY_HANG), or it fails.
        #  (a test that has to change it while the agent runs puts it in a file: "fail:<what it says>" or "hang:<seconds>")
        monkey = os.environ.get("FAKE_MONKEY_FILE")
        if monkey and os.path.exists(monkey):
            with open(monkey, encoding="utf-8") as handle:
                mode, _, value = handle.read().strip().partition(":")
            if mode == "hang":
                os.environ["FAKE_MONKEY_HANG"] = value
            elif mode == "fail":
                os.environ["FAKE_MONKEY_FAIL"] = value
        if os.environ.get("FAKE_MONKEY_HANG"):
            import time
            time.sleep(float(os.environ["FAKE_MONKEY_HANG"]))
        if os.environ.get("FAKE_MONKEY_FAIL"):
            sys.stderr.write(os.environ["FAKE_MONKEY_FAIL"] + "\n")
            return 1
    elif args[:4] == ["shell", "pm", "list", "packages"]:
        #  The apps that are installed (FAKE_PACKAGES: the lines of the answer, "|" for a new line; a Play Store one and an app of another store when it is not set).
        lines = os.environ.get("FAKE_PACKAGES", "package:com.nianticlabs.pokemongo.ares|package:com.example.pokemongo.fan|package:com.nianticlabs.pokemongo")
        sys.stdout.write("\n".join(lines.split("|")) + "\n")
    elif args[:3] == ["shell", "dumpsys", "battery"]:
        #  What `dumpsys battery` says (FAKE_BATTERY: the lines of the answer, "|" for a new line; a battery of 31.2 degrees when it is not set).
        lines = os.environ.get("FAKE_BATTERY", "Current Battery Service state:|  AC powered: false|  USB powered: true|  level: 80|  temperature: 312|  technology: Li-ion")
        sys.stdout.write("\n".join(lines.split("|")) + "\n")
    elif args[:2] == ["shell", "wm"]:
        sys.stdout.write("Physical size: 1080x2340\nOverride size: 1000x2200\n")
    elif args[:3] == ["shell", "getprop", "ro.product.model"]:
        sys.stdout.write("FakePhone\n")
    elif args[:3] == ["shell", "getprop", "ro.build.version.release"]:
        sys.stdout.write("14\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
