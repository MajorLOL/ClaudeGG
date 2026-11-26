#!/usr/bin/env python3
"""A phone that is not there: what `adb` would say, for the tests of the agent (and of Claude GG's
connection to it). Every call is written to the file in FAKE_ADB_LOG, one line each."""

import os
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


def main(argv):
    log = os.environ.get("FAKE_ADB_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(" ".join(argv) + "\n")
    args = list(argv)
    if args[:2] == ["-s", args[1] if len(args) > 1 else ""]:
        args = args[2:]
    off_file = os.environ.get("FAKE_ADB_FAIL_FILE")
    if os.environ.get("FAKE_ADB_FAIL") or (off_file and os.path.exists(off_file)):
        sys.stderr.write("error: device offline\n")
        return 1
    if args[:2] == ["exec-out", "screencap"]:
        #  Some noise before the picture, as a real adb can give.
        sys.stdout.buffer.write(b"noise\n" + png(48, 96, (200, 30, 30)))
    elif args[:2] == ["shell", "wm"]:
        sys.stdout.write("Physical size: 1080x2340\nOverride size: 1000x2200\n")
    elif args[:3] == ["shell", "getprop", "ro.product.model"]:
        sys.stdout.write("FakePhone\n")
    elif args[:3] == ["shell", "getprop", "ro.build.version.release"]:
        sys.stdout.write("14\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
