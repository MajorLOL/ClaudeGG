"""Looking with the live video (spin_stop.quick_screenshot / live_frames) and the ring speed from several pictures
(gamebot.ring_speed).  A fake video stream stands in for screenrecord.  Run: python3 -m unittest discover -s tests"""
import os
import sys
import threading
import time
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import spin_stop as S  # noqa: E402

try:
    import gamebot as G
except Exception:  # noqa: BLE001
    G = None


class FakeStream:
    """Like battle_stream.FrameStream: pictures come in with a number and a time."""

    def __init__(self, w=96, h=120):
        self.w, self.h = w, h
        self.cond = threading.Condition()
        self.seq, self.t, self.frame = 0, 0.0, None
        self.frames = self.since_open = 0
        self.failed = False
        self.closed = False

    def push(self, value):
        with self.cond:
            self.frame = np.full((self.h, self.w, 3), value, np.uint8)
            self.seq += 1
            self.frames += 1
            self.since_open += 1
            self.t = time.monotonic()
            self.cond.notify_all()

    def is_alive(self):
        return not self.closed

    def starting(self, patience=4.0):
        return self.frames == 0

    def latest(self):
        return (self.seq, self.t, self.frame) if self.frame is not None else None

    def wait_new(self, after_seq, timeout=1.0, not_before=0.0):
        end = time.monotonic() + timeout
        with self.cond:
            while True:
                if self.frame is not None and self.seq > after_seq:
                    return self.seq, self.t, self.frame
                left = end - time.monotonic()
                if left <= 0:
                    return None
                self.cond.wait(min(left, 0.05))

    def describe(self):
        return "fake"

    def close(self):
        self.closed = True


class QuickScreenshot(unittest.TestCase):
    def setUp(self):
        self.saved = (dict(S.live), S.live_wanted, S.screenshot, dict(S.screen), S.LIVE_WAIT)
        self.stream = FakeStream()
        S.live.update(stream=self.stream, off_until=0.0)
        S.live_wanted = lambda: True
        S.screen.update(w=192, h=240, checked=time.time())
        S.LIVE_WAIT = 0.1
        self.shots = []
        S.screenshot = lambda on_grab=None: self.shots.append(1) or np.zeros((240, 192, 3), np.uint8)

    def tearDown(self):
        live, S.live_wanted, S.screenshot, screen, S.LIVE_WAIT = self.saved
        S.live.clear()
        S.live.update(live)
        S.screen.clear()
        S.screen.update(screen)

    def test_a_picture_of_the_video_in_the_size_of_a_screenshot(self):
        self.stream.push(7)
        grabbed = []
        img = S.quick_screenshot(lambda: grabbed.append(1))
        self.assertEqual(img.shape, (240, 192, 3))
        self.assertEqual(int(img[0, 0, 0]), 7)
        self.assertTrue(S.quick_screenshot.live)
        self.assertEqual(grabbed, [1])
        self.assertEqual(self.shots, [])

    def test_a_newer_picture_is_waited_for(self):
        self.stream.push(1)
        threading.Timer(0.03, self.stream.push, args=(2,)).start()
        self.assertEqual(int(S.quick_screenshot()[0, 0, 0]), 2)

    def test_a_still_screen_gives_the_last_picture(self):
        self.stream.push(3)
        t = time.monotonic()
        self.assertEqual(int(S.quick_screenshot()[0, 0, 0]), 3)
        self.assertLess(time.monotonic() - t, 0.5)

    def test_an_old_last_picture_is_not_trusted(self):
        self.stream.push(3)
        self.stream.t -= S.LIVE_STALE + 1
        S.quick_screenshot()
        self.assertFalse(S.quick_screenshot.live)
        self.assertEqual(self.shots, [1])

    def test_switched_off_or_failed_means_a_screenshot(self):
        self.stream.push(3)
        S.live_wanted = lambda: False
        S.quick_screenshot()
        self.assertEqual((S.quick_screenshot.live, self.shots), (False, [1]))
        S.live_wanted = lambda: True
        self.stream.failed = True
        saved_log = S.log
        S.log = lambda m: None
        try:
            S.quick_screenshot()
        finally:
            S.log = saved_log
        self.assertFalse(S.quick_screenshot.live)
        self.assertTrue(self.stream.closed)
        self.assertGreater(S.live["off_until"], time.time())        # (screenshots for a while)

    def test_live_frames(self):
        def feed():
            for v in range(1, 6):
                time.sleep(0.02)
                self.stream.push(v)
        threading.Thread(target=feed).start()
        got = S.live_frames(0.3)
        self.assertEqual([int(im[0, 0, 0]) for _t, im in got], [1, 2, 3, 4, 5])
        self.assertEqual(got[0][1].shape, (240, 192, 3))


@unittest.skipIf(G is None, "gamebot cannot be imported here")
class RingSpeed(unittest.TestCase):
    def test_the_speed_from_pictures_one_after_another(self):
        pts = [(0.0, 0.90), (0.1, 0.845), (0.2, 0.79), (0.3, 0.735)]
        self.assertAlmostEqual(G.ring_speed(pts), 0.55, places=2)

    def test_the_jump_back_to_full_size_is_left_out(self):
        pts = [(0.0, 0.20), (0.1, 0.145), (0.2, 0.09), (0.3, 0.98), (0.4, 0.925)]
        self.assertAlmostEqual(G.ring_speed(pts), 0.55, places=2)

    def test_too_few_or_odd(self):
        self.assertIsNone(G.ring_speed([(0.0, 0.9), (0.1, 0.85)]))
        self.assertIsNone(G.ring_speed([(0.0, 0.9), (0.1, 0.89), (0.2, 0.88)]))     # (0.1 a second: not a ring)

    def test_the_live_throws_learn_their_own_offset(self):
        saved = {k: (list(v) if isinstance(v, list) else v) for k, v in G.cal.items()}
        try:
            G.cal.update(k=0.55, c=0.3, c_live=-0.12, obs_live=[[0.9, 0.5, 0.9 - 0.55 * (0.5 - 0.1)]] * 3)
            G.refit_timing(live=True)
            self.assertAlmostEqual(G.cal["c_live"], 0.1, places=2)
            self.assertEqual(G.cal["c"], 0.3)                                     # (the screenshot one stays)
        finally:
            G.cal.clear()
            G.cal.update(saved)


if __name__ == "__main__":
    unittest.main()
