#!/usr/bin/env python3
"""The live picture of the phone for the fight: screenrecord (H.264) -> ffmpeg -> raw frames.

Why: a screenshot (screencap) takes 1 to 3 seconds on the phone while the game runs, and a question like
"Attack incoming! Use a Protect Shield?" is on the screen for only five seconds, a charged attack button is lit
for as long as it is not thrown.  The video stream gives a new picture about ten times a second with a delay
of a fraction of a second and hardly any load for the phone (the encoder is in hardware).  The web interface
uses the same trick for its live view (web.py).

FrameStream keeps the newest picture; the fight loop in gamebot.py takes it from there.  No phone is needed
for the tests: _open() is the only place that starts programs.
"""
import subprocess
import threading
import time

import numpy as np

VIDEO_WIDTH = 704              # px; the height follows the shape of the phone screen (multiple of 16)
VIDEO_FPS = 10                 # frames per second that are handed to Python (the decoder still sees them all)
VIDEO_BITRATE = "6000000"
TIME_LIMIT = 170               # s: screenrecord stops after this (its own limit is 180), the stream restarts
MAX_BAD_STARTS = 3             # in a row without one picture: give up (the loop takes screenshots)


def video_size(width, height, base=VIDEO_WIDTH):
    """(w, h) of the video for a phone screen of width x height pixels."""
    return base, max(16, int(round(base * height / float(width) / 16.0)) * 16)


class FrameStream(threading.Thread):
    """Reads pictures of the phone screen in a thread of its own.  latest() / wait_new() give the newest."""

    def __init__(self, size, display_id=None, bitrate=VIDEO_BITRATE, fps=VIDEO_FPS, adb="adb", ffmpeg="ffmpeg"):
        super().__init__(daemon=True, name="frame-stream")
        self.w, self.h = size
        self.display_id, self.bitrate, self.fps = display_id, bitrate, fps
        self.adb, self.ffmpeg = adb, ffmpeg
        self._cond = threading.Condition()
        self._frame = None
        self.seq = 0                    # number of the newest picture
        self.t = 0.0                    # when it came in (time.monotonic())
        self.frames = 0
        self.starts = 0
        self.failed = False             # gave up: no pictures came
        self.error = ""
        self._quit = False
        self._procs = []

    # ------------------------------------------------------------------ programs ---
    def commands(self):
        rec = [self.adb, "exec-out", "screenrecord"]
        if self.display_id:
            rec += ["--display-id", str(self.display_id)]
        rec += ["--output-format=h264", "--size", f"{self.w}x{self.h}", "--bit-rate", str(self.bitrate),
                "--time-limit", str(TIME_LIMIT), "-"]
        ff = [self.ffmpeg, "-loglevel", "error", "-fflags", "nobuffer", "-flags", "low_delay",
              "-probesize", "32768", "-analyzeduration", "0", "-f", "h264", "-i", "pipe:0", "-an",
              "-vf", f"fps={self.fps},scale={self.w}:{self.h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
        return rec, ff

    def _open(self):
        """Start screenrecord and ffmpeg; returns the file the raw pictures come from."""
        rec_cmd, ff_cmd = self.commands()
        rec = subprocess.Popen(rec_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        ff = subprocess.Popen(ff_cmd, stdin=rec.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        rec.stdout.close()
        self._procs = [ff, rec]
        return ff.stdout

    def _kill(self):
        for p in self._procs:
            try:
                if p.poll() is None:
                    p.kill()
            except Exception:  # noqa: BLE001
                pass
        self._procs = []

    # ------------------------------------------------------------------ the thread ---
    def run(self):
        size = self.w * self.h * 3
        bad = 0
        while not self._quit:
            got = 0
            out = None
            try:
                out = self._open()
                self.starts += 1
                while not self._quit:
                    data = out.read(size)
                    if not data or len(data) < size:
                        break
                    self._publish(np.frombuffer(data, np.uint8).reshape(self.h, self.w, 3))
                    got += 1
            except FileNotFoundError as e:
                self.error = f"{e.filename or 'program'} not found"
                bad = MAX_BAD_STARTS
            except Exception as e:  # noqa: BLE001
                self.error = f"{type(e).__name__}: {e}"
            finally:
                self._kill()
                try:
                    if out is not None:
                        out.close()
                except Exception:  # noqa: BLE001
                    pass
            if self._quit:
                break
            bad = 0 if got else bad + 1
            if bad >= MAX_BAD_STARTS:
                self.failed = True
                with self._cond:
                    self._cond.notify_all()
                break
            time.sleep(0.3)

    def _publish(self, frame):
        with self._cond:
            self._frame = frame            # (frombuffer of bytes: read-only, not touched afterwards)
            self.seq += 1
            self.frames += 1
            self.t = time.monotonic()
            self._cond.notify_all()

    # ------------------------------------------------------------------ for the loop ---
    def healthy(self, max_age=2.5):
        """Pictures are coming in (the first one is given a few seconds to arrive)."""
        if self.failed or self._quit:
            return False
        if self.frames == 0:
            return True                    # (starting up: wait_new() has a time-out of its own)
        return time.monotonic() - self.t < max_age

    def latest(self):
        with self._cond:
            return (self.seq, self.t, self._frame) if self._frame is not None else None

    def wait_new(self, after_seq, timeout=1.0, not_before=0.0):
        """The newest picture when it is newer than after_seq (and came in after not_before), waiting up to
        `timeout` seconds for it.  Returns (seq, time, picture) or None."""
        end = time.monotonic() + timeout
        with self._cond:
            while True:
                if self._frame is not None and self.seq > after_seq and self.t >= not_before:
                    return self.seq, self.t, self._frame
                left = end - time.monotonic()
                if left <= 0 or self.failed or self._quit:
                    return None
                self._cond.wait(min(left, 0.2))

    def close(self):
        self._quit = True
        self._kill()
        with self._cond:
            self._cond.notify_all()
