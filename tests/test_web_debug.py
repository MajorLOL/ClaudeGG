"""The 'Download log and pictures' zip of the web interface (web.debug_zip): the end of the log and the newest
pictures the bot saved, small enough to send along.  Run: python3 -m unittest discover -s tests"""
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
        W.LOGFILE = os.path.join(self.dir, "spin.log")
        W.DEBUG_DIR = os.path.join(self.dir, "debug")
        os.makedirs(W.DEBUG_DIR)

    def tearDown(self):
        W.LOGFILE, W.DEBUG_DIR, W.DEBUG_PICTURES = self.saved

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


if __name__ == "__main__":
    unittest.main()
