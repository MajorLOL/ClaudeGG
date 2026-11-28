"""The file that the C++ port of the lock screen and the dimmed game (is_dimmed(), unlock() and unlock_game() of spin_stop.py: the brightest pixels of the
picture, the swipe lock screen of the phone that is dismissed and swiped away, the little lock of the game that is dragged up, to the right or down - played
on a pretend phone with a pretend clock) is tested against is what the Python code does now.  If this fails, one of those changed: run
python3 tools/make_lock_golden.py  and port the change to SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoLock.cpp (its test then says what differs).  The
file holds, for every little story, what the code was given (what the phone says of its lock screen, the screenshots, the pictures drawn with a few ops)
and what it did (log lines, sleeps, taps, swipes, `wm dismiss-keyguard`) in order, every event with the time of the pretend clock, and at the end of
every call what it returned."""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_lock_golden.py")
sys.path.insert(0, os.path.join(HERE, "..", "tools"))


def load():
    import make_lock_golden as M
    with open(M.OUT, "rb") as f:
        return json.loads(M.unpack(f.read()))


def by_name():
    return {c["id"]: c for c in load()["cases"]}


def logs_of(case):
    return [e[2] for e in case["events"] if e[0] == "log"]


def results_of(case):
    return [e[2] for e in case["events"] if e[0] == "result"]


def acts_of(case):
    """What was done to the phone, in order, without the time: ("tap", x, y), ("swipe", x1, y1, x2, y2, ms), ("dismiss",), ("sleep", seconds)."""
    out = []
    for e in case["events"]:
        if e[0] in ("tap", "swipe"):
            out.append((e[0],) + tuple(e[2:]))
        elif e[0] == "dismiss":
            out.append(("dismiss",))
        elif e[0] == "sleep":
            out.append(("sleep", e[2]))
    return out


class LockGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())

    def test_the_stories_have_their_own_names(self):
        import make_lock_golden as M
        names = [s["id"] for s in M.all_stories()]
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(len(names), 150)

    def test_every_branch_is_played(self):
        """Every log line and every kind of event of the three functions is in the stories."""
        logs, kinds = set(), set()
        for case in load()["cases"]:
            for event in case["events"]:
                kinds.add(event[0])
                if event[0] == "log":
                    logs.add(event[2])
        for line in ("lock screen active - unlocking", "unlock failed - is there a PIN/pattern?", "game unlocked", "game stays dimmed",
                     "game is dimmed/locked - tap + drag lock (896,1208) -> (896,450)", "game is dimmed/locked - tap + drag lock (896,1208) -> (1600,1208)",
                     "game is dimmed/locked - tap + drag lock (896,1208) -> (896,1950)"):
            self.assertIn(line, logs)
        for kind in ("call", "keyguard", "keyguard_error", "dismiss", "dismiss_error", "tap", "swipe", "sleep", "log", "shot", "shot_error", "result", "raised"):
            self.assertIn(kind, kinds)

    def test_the_edge_of_dimmed_is_exact(self):
        """The brightest 0.5 % must be below 120: grey 119 is dimmed, 120 is not; the biggest of the three colour numbers counts; a few bright
        pixels (0.49 %) do not stop a game from being dimmed, a button of 2 % and a banner of 4.5 % do."""
        cases = by_name()
        dimmed = lambda name: results_of(cases[name])[0]  # noqa: E731
        self.assertTrue(dimmed("black"))
        self.assertTrue(dimmed("grey_119"))
        self.assertFalse(dimmed("grey_120"))
        self.assertFalse(dimmed("white"))
        for colour in ("blue", "green", "red"):
            self.assertTrue(dimmed("brightest_channel_counts_" + colour))
            self.assertFalse(dimmed(colour + "_120"))
        self.assertFalse(dimmed("a_bright_button_on_a_dim_game"))
        self.assertFalse(dimmed("a_bright_banner_on_a_dim_game"))
        self.assertFalse(dimmed("a_dark_night_scene_with_lots_of_white"))
        self.assertTrue(dimmed("bright_pixels_19518_on_dark"))
        self.assertFalse(dimmed("bright_pixels_19520_on_dark"))

    def test_the_lock_screen_is_asked_in_the_order_of_the_code(self):
        """unlock() asks for the lock screen, dismisses it, waits 1.5 s, asks again, swipes up only when it is still there, waits 1.5 s, asks the last
        time: three questions for a phone that was locked, one for a phone that was not."""
        cases = by_name()
        self.assertEqual(acts_of(cases["unlock_no_lock"]), [])
        self.assertEqual(results_of(cases["unlock_no_lock"]), [False])
        self.assertEqual(acts_of(cases["unlock_dismissed"]), [("dismiss",), ("sleep", 1.5)])
        self.assertEqual(results_of(cases["unlock_dismissed"]), [True])
        self.assertEqual(acts_of(cases["unlock_swiped"]), [("dismiss",), ("sleep", 1.5), ("swipe", 884, 1900, 884, 500, 300), ("sleep", 1.5)])
        self.assertEqual(results_of(cases["unlock_swiped"]), [True])
        self.assertEqual(results_of(cases["unlock_fails"]), [False])
        self.assertEqual(logs_of(cases["unlock_fails"])[-1], "unlock failed - is there a PIN/pattern?")
        self.assertEqual(results_of(cases["unlock_dismissed_but_back"]), [False])
        for name in ("unlock_cannot_ask", "unlock_cannot_ask_after_the_dismiss", "unlock_cannot_ask_after_the_swipe", "unlock_cannot_dismiss"):
            self.assertEqual([e[0] for e in cases[name]["events"] if e[0] in ("result", "raised")], ["raised"], name)

    def test_the_game_is_woken_by_dragging_the_little_lock(self):
        """unlock_game(): a picture that is not dimmed is given back as it is (nothing is done); a dimmed one is tapped, the lock dragged up, then to the
        right, then down, a look after each, until the picture is not dimmed; the last picture is given back when none is."""
        cases = by_name()
        self.assertEqual(acts_of(cases["game_is_not_dimmed"]), [])
        self.assertEqual(results_of(cases["game_is_not_dimmed"]), [1])
        one = [("tap", 884, 700), ("sleep", 1.2), ("swipe", 896, 1208, 896, 450, 700), ("sleep", 2.5)]
        self.assertEqual(acts_of(cases["game_woken_by_the_first_swipe"]), one)
        self.assertEqual(results_of(cases["game_woken_by_the_first_swipe"]), [1])
        self.assertEqual(logs_of(cases["game_woken_by_the_first_swipe"])[-1], "game unlocked")
        self.assertEqual(acts_of(cases["game_woken_by_the_third_swipe"]),
                         one + [("tap", 884, 700), ("sleep", 1.2), ("swipe", 896, 1208, 1600, 1208, 700), ("sleep", 2.5),
                                ("tap", 884, 700), ("sleep", 1.2), ("swipe", 896, 1208, 896, 1950, 700), ("sleep", 2.5)])
        self.assertEqual(logs_of(cases["game_stays_dimmed"])[-1], "game stays dimmed")
        self.assertEqual(results_of(cases["game_stays_dimmed"]), [0])
        self.assertEqual(results_of(cases["game_stays_dimmed_and_the_last_is_another"]), [3])
        self.assertEqual(results_of(cases["game_no_picture_given"]), [1])

    def test_a_look_that_fails_is_an_error_of_the_call(self):
        """When the phone cannot give a picture the call ends with that error, after what was done until then."""
        cases = by_name()
        for name in ("game_no_picture_given_cannot_look", "game_the_look_after_a_swipe_fails", "game_the_look_after_the_second_swipe_fails",
                     "game_the_look_after_the_third_swipe_fails"):
            self.assertEqual([e[0] for e in cases[name]["events"] if e[0] in ("result", "raised")], ["raised"], name)


if __name__ == "__main__":
    unittest.main()
