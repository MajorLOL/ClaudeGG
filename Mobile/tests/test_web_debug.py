"""The 'Download log and pictures' zip of the web interface (web.debug_zip): the end of the log and the newest
pictures the bot saved, small enough to send along - and the zip of 'Record battle' (web.rec_finish), which
takes the bot's log and pictures of the time of the recording along.
Run: python3 -m unittest discover -s tests"""
import io
import os
import sys
import tempfile
import time
import unittest
import zipfile

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
os.environ.setdefault("HOME", tempfile.mkdtemp())
try:
    import web as W
except Exception:  # noqa: BLE001
    W = None


@unittest.skipIf(W is None, "web.py cannot be imported here")
class DebugZip(unittest.TestCase):
    def setUp(self):
        self.saved = (W.LOGFILE, W.DEBUG_DIR, W.DEBUG_PICTURES)
        self.dir = tempfile.mkdtemp()
        self.home, os.environ["HOME"] = os.environ.get("HOME"), self.dir   # (the files of a real home folder would
        W.LOGFILE = os.path.join(self.dir, "spin.log")                      # go into the zip: battle_team.json ...)
        W.DEBUG_DIR = os.path.join(self.dir, "debug")
        os.makedirs(W.DEBUG_DIR)

    def tearDown(self):
        W.LOGFILE, W.DEBUG_DIR, W.DEBUG_PICTURES = self.saved
        os.environ["HOME"] = self.home

    def picture(self, name, age_s=0.0):
        img = np.random.RandomState(len(name)).randint(0, 255, (552, 442, 3), np.uint8)
        path = os.path.join(W.DEBUG_DIR, name)
        cv2.imwrite(path, img)
        t = time.time() - age_s
        os.utime(path, (t, t))
        return path

    def test_the_end_of_the_log_and_the_newest_pictures(self):
        with open(W.LOGFILE, "w") as f:
            f.write("\n".join(f"2026-11-22 03:00:{i % 60:02d}  battle: line {i}" for i in range(3000)))
        png = self.picture("g_battle_s3.png", 60)
        self.picture("g_battle_party.jpg", 30)
        self.picture("g_old.png", 7 * 3600)                              # (from yesterday: not wanted)
        with zipfile.ZipFile(io.BytesIO(W.debug_zip())) as z:
            names = set(z.namelist())
            log = z.read("spin_tail.log").decode()
            index = z.read("pictures.txt").decode()
            jpg = z.read("debug/g_battle_s3.jpg")
        self.assertEqual(names, {"spin_tail.log", "pictures.txt", "debug/g_battle_s3.jpg", "debug/g_battle_party.jpg"})
        self.assertIn("battle: line 2999", log)
        self.assertEqual(index.count("\n"), 1)                           # two lines, the newest picture first
        self.assertTrue(index.splitlines()[0].endswith("g_battle_party.jpg"), index)
        self.assertLess(len(jpg), os.path.getsize(png))                  # the PNG went in as a (smaller) JPEG ...
        back = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(back.shape, (552, 442, 3))                      # ... of the same size

    def test_only_the_end_of_a_long_log(self):
        with open(W.LOGFILE, "w") as f:
            f.write("x" * (W.DEBUG_LOG_BYTES + 5000) + "\nthe last line")
        with zipfile.ZipFile(io.BytesIO(W.debug_zip())) as z:
            log = z.read("spin_tail.log").decode()
        self.assertLessEqual(len(log), W.DEBUG_LOG_BYTES)
        self.assertTrue(log.endswith("the last line"))

    def test_not_more_pictures_than_fit_in_a_message(self):
        W.DEBUG_PICTURES = 3
        for i in range(6):
            self.picture(f"g_battle_s{i}.png", 10 * i)
        with zipfile.ZipFile(io.BytesIO(W.debug_zip())) as z:
            pics = sorted(n for n in z.namelist() if n.startswith("debug/"))
        self.assertEqual(pics, ["debug/g_battle_s0.jpg", "debug/g_battle_s1.jpg", "debug/g_battle_s2.jpg"])

    def test_nothing_there(self):
        os.rmdir(W.DEBUG_DIR)
        with zipfile.ZipFile(io.BytesIO(W.debug_zip())) as z:
            self.assertIn("could not be read", z.read("spin_tail.log").decode())
            self.assertIn("no pictures", z.read("pictures.txt").decode())


@unittest.skipIf(W is None, "web.py cannot be imported here")
class RecordingZip(unittest.TestCase):
    """The zip of 'Record battle' also tells what the bot did meanwhile: its log and the pictures it saved."""

    def setUp(self):
        self.saved = (W.LOGFILE, W.DEBUG_DIR, W.REC_DIR, W.phone, dict(W.rec))
        self.dir = tempfile.mkdtemp()
        self.home, os.environ["HOME"] = os.environ.get("HOME"), self.dir
        W.LOGFILE = os.path.join(self.dir, "spin.log")
        W.DEBUG_DIR = os.path.join(self.dir, "debug")
        W.REC_DIR = os.path.join(self.dir, "battle_recording")
        os.makedirs(W.DEBUG_DIR)
        os.makedirs(os.path.join(W.REC_DIR, "frames"))
        W.phone = lambda: (None, 1768, 2208)
        self.t0 = time.time() - 200.0                                    # the recording began 200 s ago
        W.rec.update(on=True, frames=1, t0=self.t0, secs=0, note="", zip=None, mb=0.0, bytes=0, touch=None)
        cv2.imwrite(os.path.join(W.REC_DIR, "frames", "f0000_0000000.jpg"), np.zeros((77, 62, 3), np.uint8))

    def tearDown(self):
        W.LOGFILE, W.DEBUG_DIR, W.REC_DIR, W.phone = self.saved[:4]
        W.rec.clear()
        W.rec.update(self.saved[4])
        os.environ["HOME"] = self.home

    def stamp(self, ago):
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - ago))

    def picture(self, name, age_s, size=(2208, 1768)):
        path = os.path.join(W.DEBUG_DIR, name)
        cv2.imwrite(path, np.full(size + (3,), 90, np.uint8))
        t = time.time() - age_s
        os.utime(path, (t, t))

    def finish(self):
        W.rec_finish([(0, 0, "f0000_0000000.jpg")])
        self.assertTrue(W.rec["zip"], W.rec["note"])
        return zipfile.ZipFile(W.rec["zip"])

    def test_the_log_of_the_bot_during_the_recording_is_in_the_zip(self):
        with open(W.LOGFILE, "w") as f:
            f.write(self.stamp(4000) + "  an old line of this morning\n")
            f.write(self.stamp(600) + "  the daily run is ready\n")
            f.write(self.stamp(215) + "  battle recording started\n")
            f.write(self.stamp(190) + "  battle: the fight begins\n")
            f.write("Traceback (a line without a time belongs to the line before it)\n")
            f.write(self.stamp(20) + "  battle: the fight is over: loss (GOOD EFFORT!)\n")
        with self.finish() as z:
            names = set(z.namelist())
            log = z.read("bot_log.txt").decode()
        self.assertEqual(names, {"frames/f0000_0000000.jpg", "frames.csv", "meta.json", "bot_log.txt"})
        self.assertNotIn("this morning", log)
        self.assertNotIn("daily run", log)
        self.assertTrue(log.splitlines()[0].endswith("battle recording started"), log)
        self.assertIn("the fight begins\nTraceback", log)
        self.assertIn("the fight is over: loss", log)
        self.assertFalse(W.rec["on"])

    def test_the_pictures_the_bot_saved_meanwhile_are_in_the_zip_smaller(self):
        open(W.LOGFILE, "w").close()
        self.picture("g_battle_result.png", 15)
        self.picture("g_battle_bars.png", 120, size=(880, 704))          # (a picture of the live video: small already)
        self.picture("g_map_none.png", 3000)                             # (from before the recording: not this fight)
        with self.finish() as z:
            pics = sorted(n for n in z.namelist() if n.startswith("debug/"))
            big = cv2.imdecode(np.frombuffer(z.read("debug/g_battle_result.jpg"), np.uint8), cv2.IMREAD_COLOR)
            small = cv2.imdecode(np.frombuffer(z.read("debug/g_battle_bars.jpg"), np.uint8), cv2.IMREAD_COLOR)
            log = z.read("bot_log.txt").decode()
        self.assertEqual(pics, ["debug/g_battle_bars.jpg", "debug/g_battle_result.jpg"])
        self.assertEqual(big.shape[:2], (1124, 900))                     # 2208 x 1768 made 900 wide
        self.assertEqual(small.shape[:2], (880, 704))
        self.assertIn("nothing was written in the log", log)

    def test_not_more_pictures_than_the_newest_dozen(self):
        for i in range(W.REC_PICTURES + 5):
            self.picture(f"g_battle_s{i:02d}.png", 10 + i, size=(88, 70))
        with self.finish() as z:
            pics = sorted(n for n in z.namelist() if n.startswith("debug/"))
        self.assertEqual(pics, [f"debug/g_battle_s{i:02d}.jpg" for i in range(W.REC_PICTURES)])

    def test_a_log_that_is_not_there_does_not_stop_the_zip(self):
        with self.finish() as z:
            self.assertIn("could not be read", z.read("bot_log.txt").decode())

    def test_what_the_bot_has_learned_goes_along(self):
        """The team and the two files the bot keeps of what it saw in earlier battles: they say what it believed."""
        with open(os.path.join(self.dir, "battle_seen.json"), "w") as f:
            f.write('{"whiscash": {"MUD_BOMB": 1, "BLIZZARD": 1}}')
        with self.finish() as z:
            self.assertIn("battle_seen.json", z.namelist())
            self.assertIn("BLIZZARD", z.read("battle_seen.json").decode())

    def test_only_the_lines_from_a_time_on(self):
        with open(W.LOGFILE, "w") as f:
            f.write("half a line that was cut off by the size limit\n")
            f.write(self.stamp(500) + "  before\n" + self.stamp(100) + "  after\n")
        self.assertEqual(W.log_since(time.time() - 300).split("  ", 1)[1], "after")
        self.assertEqual(W.log_since(time.time() + 300), "")


if __name__ == "__main__":
    unittest.main()
