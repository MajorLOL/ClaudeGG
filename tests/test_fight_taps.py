"""Tests for the tapping of the fight loop in gamebot.py (no phone: S.tap is replaced by a recorder).

gamebot.py needs OpenCV and the TFLite runtime; without them these tests are skipped.  Run:
python3 -m unittest discover -s tests"""
import os
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
os.environ.setdefault("HOME", tempfile.mkdtemp())
try:
    import gamebot as G
    import spin_stop as S
except Exception as _e:  # noqa: BLE001
    G = S = None
    _WHY = str(_e)


@unittest.skipIf(G is None, "gamebot.py cannot be imported here")
class TapsDoNotOverlap(unittest.TestCase):
    """Two 'adb shell input' commands at the same time spoil each other (a finger that goes down twice without
    lifting): the fast taps in the background and the taps of the main loop must take turns."""

    def setUp(self):
        self.calls = []                       # (start, end, x, y)
        self.running = 0
        self.max_running = 0
        self.guard = threading.Lock()
        self._old = S.tap

        def fake_tap(x, y, ms=120):
            with self.guard:
                self.running += 1
                self.max_running = max(self.max_running, self.running)
            start = time.monotonic()
            time.sleep(0.03)                  # (the real one takes 0.3 s)
            end = time.monotonic()
            with self.guard:
                self.running -= 1
                self.calls.append((start, end, x, y))
        S.tap = fake_tap

    def tearDown(self):
        S.tap = self._old

    def test_main_taps_and_fast_taps_take_turns(self):
        tapper = G.FastTapper((884, 993))
        tapper.start()
        tapper.go()
        time.sleep(0.15)
        waits = []
        for i in range(8):
            t0 = time.monotonic()
            tapper.tap(300 + i, 1801, 90)
            waits.append(time.monotonic() - t0)
            time.sleep(0.05)
        tapper.close()
        time.sleep(0.1)
        self.assertEqual(self.max_running, 1, "two taps were running at the same time")
        self.assertEqual(len([c for c in self.calls if c[3] == 1801]), 8)
        self.assertGreater(len([c for c in self.calls if c[3] == 993]), 5)     # the fast taps went on
        self.assertLess(max(waits), 0.2)      # a tap of the main loop waits for one fast tap at most

    def test_paused_tapper_does_not_tap(self):
        tapper = G.FastTapper((884, 993))
        tapper.start()
        tapper.go()
        time.sleep(0.1)
        tapper.pause()
        time.sleep(0.1)
        n = len(self.calls)
        time.sleep(0.2)
        tapper.close()
        self.assertEqual(len(self.calls), n)


if __name__ == "__main__":
    unittest.main()
