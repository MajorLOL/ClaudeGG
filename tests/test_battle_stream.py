"""Unit tests for battle_stream (the live picture of the phone).  No phone, no ffmpeg: _open() is replaced by a
pipe that is filled by the test.  Run: python3 -m unittest discover -s tests"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import battle_stream as bs  # noqa: E402

W, H = 16, 8


class PipeStream(bs.FrameStream):
    """A FrameStream whose 'ffmpeg' is a pipe: the test writes raw pictures into it."""

    def __init__(self, scripts):
        super().__init__((W, H))
        self.scripts = list(scripts)           # one entry per start: a list of byte strings written to the pipe
        self.opened = 0

    def _open(self):
        self.opened += 1
        r, w = os.pipe()
        script = self.scripts.pop(0) if self.scripts else []

        def feed():
            for chunk in script:
                if chunk == "wait":
                    time.sleep(0.05)
                    continue
                os.write(w, chunk)
            os.close(w)

        threading.Thread(target=feed, daemon=True).start()
        return os.fdopen(r, "rb", buffering=0)


def picture(value):
    return np.full((H, W, 3), value, np.uint8).tobytes()


class VideoSize(unittest.TestCase):
    def test_follows_the_screen_shape(self):
        self.assertEqual(bs.video_size(1768, 2208), (704, 880))
        w, h = bs.video_size(1080, 2400)
        self.assertEqual(w, 704)
        self.assertEqual(h % 16, 0)
        self.assertAlmostEqual(h / float(w), 2400 / 1080.0, delta=0.03)

    def test_commands(self):
        s = bs.FrameStream((704, 880), display_id="4630946")
        rec, ff = s.commands()
        self.assertIn("--display-id", rec)
        self.assertIn("704x880", rec)
        self.assertEqual(rec[-1], "-")
        self.assertIn("bgr24", ff)
        self.assertTrue(any("scale=704:880" in a for a in ff))


class RealFfmpeg(unittest.TestCase):
    """The real ffmpeg command on a real H.264 stream (made here with ffmpeg): the first version of the command had
    "-fflags nobuffer" in it and gave no picture at all, which no test with a fake pipe could show."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.file = os.path.join(cls.dir, "t.h264")
        cls.ok = False
        if shutil.which("ffmpeg"):
            r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=64x80:rate=30",
                                "-t", "2", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
                                "-profile:v", "baseline", "-f", "h264", cls.file],
                               stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
            cls.ok = r.returncode == 0 and os.path.getsize(cls.file) > 0

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_pictures_come_out(self):
        if not self.ok:
            self.skipTest("no ffmpeg with libx264")
        outer = self

        class FromFile(bs.FrameStream):
            def _open(self):
                _rec, ff_cmd = self.commands()
                with open(outer.file, "rb") as src:
                    ff = subprocess.Popen(ff_cmd, stdin=src, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self._procs = [ff]
                threading.Thread(target=self._drain, args=("ffmpeg", ff.stderr), daemon=True).start()
                return ff.stdout

        s = FromFile((64, 80))
        s.start()
        try:
            seq, n = 0, 0
            end = time.monotonic() + 10
            while time.monotonic() < end and n < 10:
                got = s.wait_new(seq, 1.0)
                if got:
                    seq = got[0]
                    n += 1
            self.assertGreaterEqual(n, 10, s.describe())
        finally:
            s.close()

    def test_no_buffering_option(self):
        _rec, ff = bs.FrameStream((704, 880)).commands()
        self.assertNotIn("nobuffer", " ".join(ff))


class Pictures(unittest.TestCase):
    def test_pictures_come_in_order(self):
        s = PipeStream([[picture(10), "wait", picture(20), "wait", picture(30)]])
        s.start()
        try:
            seq = 0
            seen = []
            for _ in range(3):
                got = s.wait_new(seq, 2.0)
                self.assertIsNotNone(got)
                seq, _t, pic = got
                seen.append(int(pic[0, 0, 0]))
                self.assertEqual(pic.shape, (H, W, 3))
            self.assertEqual(seen[0], 10)
            self.assertEqual(seen[-1], 30)
            self.assertEqual(sorted(seen), seen)
            self.assertTrue(s.healthy())
        finally:
            s.close()

    def test_wait_new_gives_nothing_new_after_the_timeout(self):
        s = PipeStream([[picture(5), "wait", "wait", "wait", "wait", "wait", "wait", picture(6)]])
        s.start()
        try:
            first = s.wait_new(0, 2.0)
            self.assertIsNotNone(first)
            t0 = time.monotonic()
            self.assertIsNone(s.wait_new(first[0] + 5, 0.15))      # (no such picture yet)
            self.assertGreaterEqual(time.monotonic() - t0, 0.1)
        finally:
            s.close()

    def test_not_before_skips_old_pictures(self):
        s = PipeStream([[picture(1), "wait", "wait", "wait", picture(2)]])
        s.start()
        try:
            first = s.wait_new(0, 2.0)
            got = s.wait_new(0, 2.0, not_before=first[1] + 0.1)
            self.assertIsNotNone(got)
            self.assertGreater(got[1], first[1])
            self.assertEqual(int(got[2][0, 0, 0]), 2)
        finally:
            s.close()

    def test_restarts_when_the_recorder_stops(self):
        # screenrecord stops after its time limit: the stream starts it again and the pictures go on
        s = PipeStream([[picture(1)], [picture(2)]])
        s.start()
        try:
            seq = 0
            values = []
            for _ in range(2):
                got = s.wait_new(seq, 3.0)
                self.assertIsNotNone(got)
                seq = got[0]
                values.append(int(got[2][0, 0, 0]))
            self.assertEqual(values, [1, 2])
            self.assertGreaterEqual(s.starts, 2)
        finally:
            s.close()

    def test_a_cut_off_picture_is_not_used(self):
        s = PipeStream([[picture(7), picture(8)[:50]]])
        s.start()
        try:
            got = s.wait_new(0, 2.0)
            self.assertEqual(int(got[2][0, 0, 0]), 7)
            time.sleep(0.3)
            self.assertEqual(s.frames, 1)
        finally:
            s.close()

    def test_gives_up_without_pictures(self):
        bs.MAX_BAD_STARTS, saved = 2, bs.MAX_BAD_STARTS
        try:
            s = PipeStream([[], [], []])
            s.start()
            end = time.monotonic() + 5
            while not s.failed and time.monotonic() < end:
                time.sleep(0.05)
            self.assertTrue(s.failed)
            self.assertFalse(s.healthy())
            self.assertIsNone(s.wait_new(0, 0.2))
        finally:
            bs.MAX_BAD_STARTS = saved

    def test_describe_says_what_happened(self):
        s = bs.FrameStream((W, H))
        s.notes.append("screenrecord: ERROR: nope")
        s.starts = 2
        s.failed = True
        text = s.describe()
        self.assertIn("gave up", text)
        self.assertIn("ERROR: nope", text)

    def test_close_stops_the_thread(self):
        s = PipeStream([[picture(1), "wait", "wait", "wait", "wait", "wait", "wait", "wait", "wait", "wait"]])
        s.start()
        s.wait_new(0, 2.0)
        s.close()
        s.join(3.0)
        self.assertFalse(s.is_alive())


if __name__ == "__main__":
    unittest.main()
