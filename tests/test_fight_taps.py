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


@unittest.skipIf(G is None, "gamebot.py cannot be imported here")
class Sweeps(unittest.TestCase):
    """The little game of a charged attack: while a planner gives swipes the tapper swipes instead of tapping."""

    def setUp(self):
        self.events = []                      # ("tap" / "swipes", start, end, what)
        self.running = 0
        self.max_running = 0
        self.guard = threading.Lock()
        self._old = (S.tap, S.swipes)

        def record(kind, what, cost):
            with self.guard:
                self.running += 1
                self.max_running = max(self.max_running, self.running)
            start = time.monotonic()
            time.sleep(cost)
            with self.guard:
                self.running -= 1
                self.events.append((kind, start, time.monotonic(), what))
        S.tap = lambda x, y, ms=120: record("tap", (x, y), 0.01)
        S.swipes = lambda strokes: record("swipes", list(strokes), 0.03)

    def tearDown(self):
        S.tap, S.swipes = self._old

    def kinds(self):
        return [e[0] for e in self.events]

    def test_swipes_instead_of_fast_taps(self):
        plan = [(100, 900, 800, 900, 60), (800, 1200, 100, 1200, 60)]
        tapper = G.FastTapper((884, 993))
        tapper.start()
        tapper.go()
        tapper.sweep(lambda: plan)
        time.sleep(0.25)
        tapper.close()
        time.sleep(0.05)
        swipes = [e for e in self.events if e[0] == "swipes"]
        self.assertGreater(len(swipes), 3)
        self.assertEqual(swipes[0][3], plan)
        self.assertEqual(tapper.swipes, 2 * len(swipes))
        self.assertLessEqual(self.kinds().count("tap"), 1)        # (at most the one that was running)

    def test_fast_taps_go_on_while_the_planner_gives_nothing(self):
        tapper = G.FastTapper((884, 993))
        tapper.start()
        tapper.go()
        tapper.sweep(lambda: [])                                 # (the icons are not there yet)
        time.sleep(0.2)
        tapper.close()
        self.assertGreater(self.kinds().count("tap"), 5)
        self.assertEqual(self.kinds().count("swipes"), 0)

    def test_a_tap_of_the_main_loop_goes_between_two_sweeps(self):
        tapper = G.FastTapper((884, 993))
        tapper.start()
        tapper.sweep(lambda: [(100, 900, 800, 900, 60)])
        time.sleep(0.1)
        waits = []
        for i in range(5):
            t0 = time.monotonic()
            tapper.tap(300 + i, 1545)                            # (the shield)
            waits.append(time.monotonic() - t0)
            time.sleep(0.04)
        tapper.close()
        time.sleep(0.05)
        self.assertEqual(self.max_running, 1, "a tap and a swipe were running at the same time")
        self.assertEqual(len([e for e in self.events if e[0] == "tap" and e[3][1] == 1545]), 5)
        self.assertLess(max(waits), 0.2)                         # it waits for one batch of swipes at most

    def test_no_swipes_after_the_game(self):
        tapper = G.FastTapper((884, 993))
        tapper.start()
        tapper.sweep(lambda: [(100, 900, 800, 900, 60)])
        time.sleep(0.1)
        tapper.sweep(None)
        time.sleep(0.08)
        n = self.kinds().count("swipes")
        time.sleep(0.15)
        tapper.close()
        self.assertEqual(self.kinds().count("swipes"), n)

    def test_a_planner_that_fails_does_not_stop_the_tapper(self):
        def broken():
            raise RuntimeError("boom")
        tapper = G.FastTapper((884, 993))
        tapper.start()
        tapper.go()
        tapper.sweep(broken)
        time.sleep(0.15)
        tapper.close()
        self.assertGreater(self.kinds().count("tap"), 3)


@unittest.skipIf(G is None, "gamebot.py cannot be imported here")
class MinigameParts(unittest.TestCase):
    def picture(self, name):
        import cv2
        img = cv2.imread(os.path.join(HERE, "fixtures", "minigame", name + ".jpg"))
        return cv2.resize(img, G.VIEW, interpolation=cv2.INTER_AREA)

    def game(self, move_id):
        import battle_engine as BE
        return G.Minigame(BE.Move(move_id), time.monotonic())

    def test_a_lit_button_is_no_icon(self):
        # the fight itself with both buttons lit: the Shadow Ball button looks like a ghost icon
        import battle_minigame as BMG
        self.assertEqual(len(BMG.find_icons(self.picture("fight"), "ghost")), 1)
        mini = self.game("SHADOW_BALL")
        self.assertEqual(mini.look(self.picture("fight")), [])   # (one "icon" at a button is not the little game)
        self.assertFalse(mini.on)

    def test_the_icons_turn_the_game_on(self):
        mini = self.game("SHADOW_BALL")
        icons = mini.look(self.picture("ghost"))                 # three ghost icons, two of them where the left
        self.assertEqual(len(icons), 3)                          # button is in the fight: three cannot be buttons
        self.assertTrue(mini.on)
        flying = self.game("SKY_ATTACK")
        self.assertEqual(len(flying.look(self.picture("flying"))), 6)
        self.assertTrue(flying.on)
        other = self.game("SURF")                                # (ghost icons are no water icons)
        self.assertEqual(other.look(self.picture("ghost")), [])
        self.assertFalse(other.on)

    def test_strokes_are_canvas_pixels_in_short_pieces(self):
        mini = self.game("SURF")
        mini.game.t0 = time.monotonic() - 3.0                    # (thrown three seconds ago: the icons are due)
        strokes = mini.strokes()
        self.assertTrue(strokes)
        for x1, y1, x2, y2, ms in strokes:
            self.assertTrue(0 <= x1 <= S.REF_W and 0 <= x2 <= S.REF_W)
            self.assertTrue(0.2 * S.REF_H <= y1 <= S.REF_H and 0.2 * S.REF_H <= y2 <= S.REF_H)
            self.assertIsInstance(x1, int)
        total = sum(ms / 1000.0 + 0.06 for *_xy, ms in strokes)
        self.assertLess(total, G.SWEEP_SECONDS + 0.3)
        gate = mini.game.prior[0]                                # the known gate of water, on the canvas
        self.assertEqual(strokes[0][:4], (int(gate[0] * S.REF_W), int(gate[1] * S.REF_H),
                                          int(gate[2] * S.REF_W), int(gate[3] * S.REF_H)))

    def test_nothing_to_swipe_right_after_the_throw(self):
        self.assertEqual(self.game("SURF").strokes(), [])

    def test_what_was_learned_is_kept_in_a_file(self):
        old = G.MINIGAME_FILE
        G.MINIGAME_FILE = os.path.join(tempfile.mkdtemp(), "minigame.json")
        try:
            self.assertEqual(G.load_minigames(), {})
            G.save_minigames({"fire": {"gates": [(0.1, 0.5, 0.9, 0.5)], "rows": []}})
            back = G.load_minigames()
            self.assertEqual(back["fire"]["gates"], [[0.1, 0.5, 0.9, 0.5]])
            import battle_engine as BE
            mini = G.Minigame(BE.Move("FLAMETHROWER"), time.monotonic() - 3.0, back)
            self.assertEqual(mini.game.prior, [(0.1, 0.5, 0.9, 0.5)])
        finally:
            G.MINIGAME_FILE = old


class _Stream:
    """A live video that gives the pictures it is told to give."""

    def __init__(self, answers, starting=False):
        self.answers, self._starting, self.asked = list(answers), starting, []
        self.failed = False

    def healthy(self, max_age=2.5):
        return True

    def starting(self):
        return self._starting

    def describe(self):
        return "test"

    def wait_new(self, seq, timeout=1.0, not_before=0.0):
        self.asked.append(timeout)
        return self.answers.pop(0) if self.answers else None

    def close(self):
        pass


@unittest.skipIf(G is None, "gamebot.py cannot be imported here")
class EyesOfTheFight(unittest.TestCase):
    def setUp(self):
        import numpy as np
        self.np = np
        self._old = (S.screenshot, G.log)
        self.shots = 0
        self.canvas = np.zeros((S.REF_H, S.REF_W, 3), np.uint8)

        def shot(*a, **k):
            self.shots += 1
            return self.canvas
        S.screenshot = shot
        G.log = lambda m: None

    def tearDown(self):
        S.screenshot, G.log = self._old

    def frame(self):
        return self.np.zeros((G.VIEW[1], G.VIEW[0], 3), self.np.uint8)

    def test_pictures_from_the_video(self):
        eyes = G.Eyes(_Stream([(1, 5.0, self.frame())]))
        canvas, small, t = eyes.look()
        self.assertTrue(eyes.video)
        self.assertEqual(canvas.shape[:2], (S.REF_H, S.REF_W))
        self.assertEqual(small.shape[:2], (G.VIEW[1], G.VIEW[0]))
        self.assertEqual((t, self.shots), (5.0, 0))
        eyes.real(canvas)                                        # text needs a real screenshot
        self.assertEqual(self.shots, 1)

    def test_screenshots_when_there_is_no_video(self):
        eyes = G.Eyes(None)
        canvas, small, _t = eyes.look()
        self.assertFalse(eyes.video)
        self.assertEqual(small.shape[:2], (G.VIEW[1], G.VIEW[0]))     # the readers get the small picture all the same
        self.assertEqual(self.shots, 1)
        self.assertIs(eyes.real(canvas), canvas)                 # it is a real screenshot already: no second one
        self.assertEqual(self.shots, 1)

    def test_a_video_that_gives_nothing_falls_back_to_a_screenshot(self):
        eyes = G.Eyes(_Stream([]))
        eyes.look()
        self.assertFalse(eyes.video)
        self.assertEqual(self.shots, 1)

    def test_the_restart_of_the_video_is_waited_for(self):
        # screenrecord stops every three minutes; its next pictures come sooner than a screenshot would
        stream = _Stream([(1, 1.0, self.frame()), None, (2, 2.0, self.frame())], starting=True)
        eyes = G.Eyes(stream)
        eyes.look()
        eyes.look()
        self.assertTrue(eyes.video)
        self.assertEqual(self.shots, 0)
        self.assertEqual(len(stream.asked), 3)
        self.assertGreater(stream.asked[2], stream.asked[1])     # (the second wait is the longer one)


class _Clock:
    def __init__(self):
        self.t, self.sleeps = 100.0, []

    def time(self):
        return self.t

    def monotonic(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(round(seconds, 3))
        self.t += seconds


@unittest.skipIf(G is None, "gamebot.py cannot be imported here")
class Settled(unittest.TestCase):
    """_settled(): two screenshots at least a second apart that show the same."""

    def run_it(self, cost):
        import numpy as np
        clock = _Clock()
        old = (G.time, S.screenshot)
        img = np.zeros((S.REF_H, S.REF_W, 3), np.uint8)
        starts = []

        def shot(*a, **k):
            starts.append(clock.t)
            clock.t += cost
            return img
        G.time, S.screenshot = clock, shot
        try:
            G._settled(1.8)
        finally:
            G.time, S.screenshot = old
        return clock, starts

    def test_a_slow_screenshot_is_the_wait(self):
        clock, starts = self.run_it(2.6)
        self.assertEqual(len(starts), 2)
        self.assertEqual([s for s in clock.sleeps if s > 0], [1.8])       # only the wait before the first one

    def test_fast_screenshots_are_still_a_second_apart(self):
        clock, starts = self.run_it(0.2)
        self.assertEqual(len(starts), 2)
        self.assertAlmostEqual(starts[1] - starts[0], 1.0, places=2)


if __name__ == "__main__":
    unittest.main()
