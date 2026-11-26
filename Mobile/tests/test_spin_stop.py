"""Unit tests for the parts of spin_stop that need no phone: comparing raw and PNG screenshots, the choice of
the screenshot method, the input commands.  Run: python3 -m unittest discover -s tests"""
import os
import sys
import time
import unittest

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import spin_stop as S  # noqa: E402


def scene(seed=1, w=442, h=552):
    """A picture with big coloured shapes (like a game screen)."""
    rng = np.random.RandomState(seed)
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = (90, 140, 60)
    for _ in range(25):
        x, y = int(rng.randint(0, w)), int(rng.randint(0, h))
        colour = tuple(int(v) for v in rng.randint(0, 255, 3))
        cv2.circle(img, (x, y), int(rng.randint(15, 70)), colour, -1)
    return img


def with_patch(img, x, y, colour=(255, 255, 255), size=60):
    """The same picture with something that moved: a square somewhere else."""
    out = img.copy()
    cv2.rectangle(out, (x, y), (x + size, y + size), colour, -1)
    return out


class CompareShots(unittest.TestCase):
    def test_the_same_picture(self):
        png = scene()
        res = S.compare_shots(png, png.copy(), png.copy())
        self.assertIs(res["same"], True)
        self.assertLess(res["diff"], 0.5)
        self.assertGreater(res["still"], 0.95)

    def test_the_same_picture_of_a_screen_that_moves(self):
        # something moved between the screenshots (the game is alive): the raw one is still the same picture
        base = scene()
        png, raw, png2 = with_patch(base, 40, 60), with_patch(base, 150, 200), with_patch(base, 260, 380)
        plain = float(np.abs(png.astype(np.int16) - raw).mean())
        res = S.compare_shots(png, raw, png2)
        self.assertGreater(plain, 3.0)                  # (a plain difference would have called it different)
        self.assertIs(res["same"], True)
        self.assertLess(res["diff"], S.SHOT_SAME)

    def test_other_colours_are_corrected(self):
        png = scene()
        raw = np.clip(png.astype(np.float32) * 0.9 + 12, 0, 255).astype(np.uint8)       # a bit darker and flatter
        res = S.compare_shots(png, raw, png.copy())
        self.assertIs(res["same"], True)
        self.assertIsNotNone(res["xf"])
        self.assertIn("colours corrected", res["note"])
        fixed = cv2.transform(raw, res["xf"])
        self.assertLess(float(np.abs(fixed.astype(np.int16) - png).mean()), 2.0)

    def test_another_picture(self):
        png = scene(1)
        res = S.compare_shots(png, scene(2), png.copy())
        self.assertIs(res["same"], False)
        self.assertGreater(res["diff"], 14)

    def test_a_skewed_picture(self):
        png = scene()
        raw = np.roll(png, 25, axis=1)                  # (rows that are too long: everything shifts)
        self.assertIs(S.compare_shots(png, raw, png.copy())["same"], False)

    def test_a_screen_that_changes_completely_cannot_be_judged(self):
        png = scene(1)
        res = S.compare_shots(png, png.copy(), 255 - png)       # (nothing is the same on the second PNG)
        self.assertIsNone(res["same"])
        self.assertLess(res["still"], S.SHOT_STILL_SHARE)

    def test_another_size(self):
        png = scene()
        res = S.compare_shots(png, png[:, :-10].copy(), png.copy())
        self.assertIs(res["same"], False)
        self.assertIn("another size", res["note"])


class ShotMode(unittest.TestCase):
    """The choice between PNG and raw screenshots, with a fake phone."""

    def setUp(self):
        self.saved = (dict(S._shot), dict(S._busy), S._grab_png, S._grab_raw, S.log, dict(S.screen))
        self.logs = []
        S.log = self.logs.append
        self.png = scene(w=S.REF_W // 4, h=S.REF_H // 4)
        self.calls = []
        S.screen.update(w=self.png.shape[1], h=self.png.shape[0], checked=time.time())
        S._shot.update(mode=None, fails=0, tries=0, retry=0.0, xf=None, raw_ok=False, t_raw=0.0, png_avg=0.0,
                       png_n=0, saved=True, auto=False, raw_n=0)
        S._busy["until"] = 0.0

    def tearDown(self):
        shot, busy, S._grab_png, S._grab_raw, S.log, screen = self.saved
        S._shot.clear()
        S._shot.update(shot)
        S._busy.update(busy)
        S.screen.update(screen)

    def fake(self, raw=None, t_png=0.03, t_raw=0.0):
        def grab_png():
            self.calls.append("png")
            time.sleep(t_png)
            return self.png.copy()

        def grab_raw(on_grab=None):
            self.calls.append("raw")
            time.sleep(t_raw)
            return (self.png if raw is None else raw).copy()
        S._grab_png, S._grab_raw = grab_png, grab_raw

    def test_raw_is_used_when_it_is_the_same_and_faster(self):
        self.fake()
        S.screenshot()
        self.assertEqual(self.calls, ["png", "raw", "png"])
        self.assertEqual(S._shot["mode"], "raw")
        self.assertIn("raw capture", self.logs[-1])
        S.screenshot()
        self.assertEqual(self.calls[-1], "raw")

    def test_png_is_kept_when_raw_differs_and_tried_again_later(self):
        self.fake(raw=scene(9, w=self.png.shape[1], h=self.png.shape[0]))
        S.screenshot()
        self.assertEqual(S._shot["mode"], "png")
        self.assertIn("differs", self.logs[-1])
        self.assertGreater(S._shot["retry"], time.time() + 100)
        S.screenshot()
        self.assertEqual(self.calls[-1], "png")

    def test_no_new_comparison_while_busy(self):
        self.fake(raw=scene(9, w=self.png.shape[1], h=self.png.shape[0]))
        S.screenshot()
        n = len(self.calls)
        S._shot["retry"] = time.time() - 1              # it is time to compare again ...
        S.busy(60)                                      # ... but a battle is going on
        S.screenshot()
        self.assertEqual(self.calls[n:], ["png"])
        S.busy(0)
        S.screenshot()
        self.assertEqual(self.calls[n + 1:], ["png", "raw", "png"])

    def test_recheck_asks_for_a_new_comparison(self):
        self.fake(raw=scene(9, w=self.png.shape[1], h=self.png.shape[0]))
        S.screenshot()
        self.fake()                                     # (now the raw screenshot is right)
        self.calls.clear()
        S.recheck_shot_mode()
        S.screenshot()
        self.assertEqual(self.calls, ["png", "raw", "png"])
        self.assertEqual(S._shot["mode"], "raw")

    def test_raw_that_is_right_but_not_faster_is_used_once_pngs_get_slow(self):
        self.fake(t_png=0.02, t_raw=0.05)               # a quiet screen: the PNG is quick
        S.screenshot()
        self.assertEqual(S._shot["mode"], "png")
        self.assertTrue(S._shot["raw_ok"])
        self.assertIn("not faster", self.logs[-1])
        self.fake(t_png=0.12, t_raw=0.05)               # a busy screen (a battle): the PNG takes much longer
        for _ in range(4):
            S.screenshot()
        self.assertEqual(S._shot["mode"], "raw")
        self.assertIn("using raw capture while PNGs are this slow", self.logs[-1])

    def slow_pngs_then_raw(self):
        self.fake(t_png=0.02, t_raw=0.05)
        S.screenshot()                                  # (raw is right, not faster: PNG)
        self.fake(t_png=0.12, t_raw=0.05)
        for _ in range(3):
            S.screenshot()                              # (the battle: PNGs are slow, raw after the third one)
        self.assertEqual(S._shot["mode"], "raw")
        self.assertEqual(S._shot["raw_n"], 0)
        self.calls.clear()

    def test_png_again_when_pngs_are_quick_again(self):
        self.slow_pngs_then_raw()
        self.fake(t_png=0.02, t_raw=0.05)               # the battle is over: the screen is quiet again
        for _ in range(S.SHOT_PROBE):
            S.screenshot()
        self.assertEqual(self.calls, ["raw"] * S.SHOT_PROBE)
        S.screenshot()                                  # one PNG to see how long it takes now
        self.assertEqual(self.calls[-1], "png")
        self.assertEqual(S._shot["mode"], "png")
        self.assertIn("using PNG again", self.logs[-1])
        S.screenshot()
        self.assertEqual(self.calls[-1], "png")

    def test_raw_stays_when_pngs_are_still_slow(self):
        self.slow_pngs_then_raw()
        for _ in range(S.SHOT_PROBE + 1):
            S.screenshot()
        self.assertEqual(self.calls[-1], "png")         # (the PNG to see how long it takes: still slow)
        self.assertEqual(S._shot["mode"], "raw")
        S.screenshot()
        self.assertEqual(self.calls[-1], "raw")

    def test_the_end_of_a_battle_asks_for_that_png_at_once(self):
        self.slow_pngs_then_raw()
        S.busy(60)
        S._shot["raw_n"] = S.SHOT_PROBE                 # (it would be time for a PNG ...)
        S.screenshot()
        self.assertEqual(self.calls[-1], "raw")         # (... but not in the middle of a battle)
        S._shot["raw_n"] = 3
        self.fake(t_png=0.02, t_raw=0.05)
        S.busy(0)
        S.screenshot()
        self.assertEqual(self.calls[-1], "png")
        self.assertEqual(S._shot["mode"], "png")

    def test_a_battle_starts_with_raw_screenshots_when_they_are_right(self):
        self.fake(t_png=0.02, t_raw=0.05)
        S.screenshot()                                  # (raw is right, not faster on this quiet screen: PNG)
        self.assertEqual(S._shot["mode"], "png")
        self.calls.clear()
        S.busy(60)                                      # the battle: no slow PNGs first
        self.assertIn("raw capture for now", self.logs[-1])
        S.screenshot()
        self.assertEqual(self.calls, ["raw"])
        S.busy(0)                                       # over: a PNG shows that PNGs are quick again
        S.screenshot()
        self.assertEqual(self.calls[-1], "png")
        self.assertEqual(S._shot["mode"], "png")

    def test_a_battle_does_not_use_a_raw_screenshot_that_was_not_found_right(self):
        self.fake(raw=scene(9, w=self.png.shape[1], h=self.png.shape[0]))
        S.screenshot()
        self.calls.clear()
        S.busy(60)
        S.screenshot()
        self.assertEqual(self.calls, ["png"])
        self.assertEqual(S._shot["mode"], "png")

    def test_raw_chosen_at_the_comparison_is_not_questioned(self):
        self.fake()                                     # (raw is faster even on a quiet screen)
        S.screenshot()
        self.calls.clear()
        for _ in range(S.SHOT_PROBE + 3):
            S.screenshot()
        self.assertEqual(set(self.calls), {"raw"})

    def test_busy_ends(self):
        S.busy(30)
        self.assertGreater(S._busy["until"], time.time() + 20)
        S.busy(0)
        self.assertEqual(S._busy["until"], 0.0)


class Input(unittest.TestCase):
    USAGE = """Usage: input [<source>] [-d DISPLAY_ID] <command> [<arg>...]

The sources are:
      touchnavigation
      touchscreen
      joystick
      stylus
      touchpad
      gamepad
      dpad
      mouse
      keyboard
      trackball
      rotaryencoder
[axis_value] represents an option specifying the value of a given axis

-d: specifies the display ID.
  (Default: -1 for key event, 0 for motion event if not specified.)

The commands and default sources are:
      text <string> (Default: keyboard)
      keyevent [--longpress|--duration <duration to hold key down in ms>] [--doubletap] [--async] ...
      tap <x> <y> (Default: touchscreen)
      swipe <x1> <y1> <x2> <y2> [duration(ms)] (Default: touchscreen)
      draganddrop <x1> <y1> <x2> <y2> [duration(ms)] (Default: touchscreen)
      press (Default: trackball)
      roll <dx> <dy> (Default: trackball)
      motionevent <DOWN|UP|MOVE|CANCEL> <x> <y> (Default: touchscreen)
"""

    def setUp(self):
        self.saved = (S.adb, list(S.INPUT), dict(S.screen))
        self.sent = []
        S.adb = lambda *a, **k: self.sent.append(a) or ""

    def tearDown(self):
        S.adb, inp, screen = self.saved
        S.INPUT[:] = inp
        S.screen.update(screen)

    def test_the_whole_usage_text_counts(self):
        self.assertTrue(S.input_usage_ok(self.USAGE))
        self.assertGreater(self.USAGE.index("motionevent"), 600)          # (it comes late in the text)
        self.assertFalse(S.input_usage_ok(self.USAGE[:600]))
        self.assertFalse(S.input_usage_ok(""))
        self.assertFalse(S.input_usage_ok("cmd: Can't find service: input"))

    def test_swipes_go_out_as_one_command(self):
        S.screen.update(w=S.REF_W, h=S.REF_H)
        S.INPUT[:] = ["input"]
        S.swipes([(100, 200, 300, 400, 80), (300, 400, 500, 600, 45.7)])
        self.assertEqual(self.sent, [("shell", "input swipe 100 200 300 400 80; input swipe 300 400 500 600 45")])

    def test_swipes_on_another_screen_and_with_cmd_input(self):
        S.screen.update(w=S.REF_W // 2, h=S.REF_H // 2)
        S.INPUT[:] = ["cmd", "input"]
        S.swipes([(100, 200, 300, 400, 80)])
        self.assertEqual(self.sent, [("shell", "cmd input swipe 50 100 150 200 80")])

    def test_no_swipes_no_command(self):
        S.swipes([])
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
