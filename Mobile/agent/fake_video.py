#!/usr/bin/env python3
"""A phone's live picture that is not there, for the tests: JPEG pictures to the output, one after the
other, each a little different (a comment with its number). Instead of `screenrecord` and ffmpeg.

    python fake_video.py [a JPEG file]       (the picture of the file, or a small blue one)

FAKE_VIDEO_FRAMES   end after this many pictures (0: go on)
FAKE_VIDEO_LOG      a line is added to this file each time it starts
FAKE_VIDEO_DELAY    seconds between the pictures (0.04)
FAKE_VIDEO_FAIL     say this on the error output and end at once
"""

import base64
import os
import struct
import sys
import time

BLUE = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQYGBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/"
    "2wBDAQcHBwoIChMKChMoGhYaKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCj/wAARCAAgABADASIAAhEBAxEB/8QAHwAAAQUB"
    "AQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3"
    "ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP0"
    "9fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNO"
    "El8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna"
    "4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDnKKKK+/PhAooooA//2Q=="
)


def main(argv):
    log = os.environ.get("FAKE_VIDEO_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write("start\n")
    if os.environ.get("FAKE_VIDEO_FAIL"):
        sys.stderr.write(os.environ["FAKE_VIDEO_FAIL"] + "\n")
        return 1
    if argv:
        with open(argv[0], "rb") as handle:
            base = handle.read()
    else:
        base = BLUE
    count = int(os.environ.get("FAKE_VIDEO_FRAMES", "0"))
    delay = float(os.environ.get("FAKE_VIDEO_DELAY", "0.04"))
    out = sys.stdout.buffer
    number = 0
    while count == 0 or number < count:
        number += 1
        note = ("picture %d" % number).encode()
        comment = b"\xff\xfe" + struct.pack(">H", len(note) + 2) + note
        out.write(base[:2] + comment + base[2:])
        out.flush()
        time.sleep(delay)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except BrokenPipeError:
        sys.exit(0)
