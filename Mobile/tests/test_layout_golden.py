"""The file that the C++ port of the layout check (judge_screen(), find_menu_button(), the change of the display size and the check of the layout of
spin_stop.py and gamebot.py: is the game drawn the way the bot expects, and when it is not, `wm size` and back) is tested against is what the Python code
does now.  If this fails, one of those changed: run
python3 tools/make_layout_golden.py  and port the change to SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoLayout.cpp (its test then says what differs).  The
file holds, for every little story, what the code was given (what `wm size` says, the screenshots drawn with a few ops, the files of the Pi) and what it did
(log lines, sleeps, taps, `wm size` and the record of the change) in order, every event with the time of the pretend clock, and at the end of every call what
it returned."""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_layout_golden.py")
sys.path.insert(0, os.path.join(HERE, "..", "tools"))


def load():
    import make_layout_golden as M
    with open(M.OUT, "rb") as f:
        return json.loads(M.unpack(f.read()))


def by_name():
    return {c["id"]: c for c in load()["cases"]}


def logs_of(case):
    return [e[2] for e in case["events"] if e[0] == "log"]


def results_of(case):
    return [e[2] for e in case["events"] if e[0] == "result"]


def kinds_of(case):
    return [e[0] for e in case["events"]]


class LayoutGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())

    def test_the_stories_have_their_own_names(self):
        import make_layout_golden as M
        names = [s["id"] for s in M.all_stories()]
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(len(names), 250)

    def test_every_kind_of_event_is_played(self):
        kinds = set()
        for case in load()["cases"]:
            kinds.update(kinds_of(case))
        for kind in ("call", "log", "sleep", "tap", "back", "shot", "ocr", "result", "raised", "state", "wm_info", "wm_info_error", "wm_set", "wm_set_error",
                     "wm_reset", "wm_reset_error", "record_write", "record_write_error", "record_read", "record_forget", "detect_screen", "detect_none",
                     "detect_error", "same_screen"):
            self.assertIn(kind, kinds)

    def test_every_line_of_the_log_is_said(self):
        """(what a call returns says why as well: the reasons of the plan and of the adapt are in its results)"""
        logs = set()
        for case in load()["cases"]:
            logs.update(logs_of(case))
            logs.update(json.dumps(result) for result in results_of(case))
        for part in ("screen size is ", "not playing: ", "the display size was changed by something else", "cannot tell which display",
                     "the screen is too small", "the screen already has the shape of the canvas", "display size set to ", "display size put back (wm size reset)",
                     "could not put the display size back", "layout: the display size ", "layout check: after a tap on the menu button the screen is ",
                     "putting the display size back", "trying to let Android draw the game in the right shape", "layout: not possible: ",
                     "checking the game again on the map"):
            self.assertTrue(any(part in line for line in logs), part)

    def test_the_shape_of_the_screen_may_be_ten_percent_off(self):
        """The canvas is 1768 x 2208 (0.8007): a screen up to 10 % wider or narrower is taken, 1592 x 2208 and 1944 x 2208 are the edges."""
        cases = by_name()
        ok = lambda name: results_of(cases[name])[0][0]  # noqa: E731
        self.assertTrue(ok("judge_1768x2208"))
        self.assertTrue(ok("judge_1592x2208"))
        self.assertFalse(ok("judge_1591x2208"))
        self.assertTrue(ok("judge_1944x2208"))
        self.assertFalse(ok("judge_1945x2208"))
        for name in ("judge_1080x2400", "judge_1080x2340", "judge_1440x3120", "judge_2208x1768"):
            self.assertFalse(ok(name), name)
        self.assertTrue(ok("judge_1080x1348"))
        self.assertTrue(ok("judge_allowed_anyway"))
        self.assertIn("running anyway because /home/pi/gamebot_allow_unsupported exists", results_of(cases["judge_allowed_anyway"])[0][1])
        after = results_of(cases["judge_allowed_after_it_was_not"])
        self.assertEqual([one[0] for one in after], [False, True, False])

    def test_the_edges_of_the_menu_button_are_exact(self):
        """The red half is red from 36 (and 2.5 times the other colours), its box is from 89 px wide (5 % of the picture) to 20 %, 0.3 to 0.7 as high as it is
        wide, and the red fills more than 0.3 of the box (a frame of 10 px does, one of 9 does not); the white half under it has to be white (the colours
        less than 25 apart) and as bright as the red one at 0.2 of the width above the line."""
        cases = by_name()
        found = lambda name: results_of(cases["find_" + name])[0]  # noqa: E731
        self.assertEqual(found("reference"), [884.0, 1991.0, 170.0])
        self.assertIsNone(found("red_edge_35"))
        self.assertIsNotNone(found("red_edge_36"))
        self.assertIsNone(found("width_88"))
        self.assertEqual(found("width_89"), [884.5, 1991.0, 89.0])
        self.assertIsNotNone(found("height_51_of_170"))
        self.assertIsNone(found("height_50_of_170"))
        self.assertIsNone(found("a_frame_of_9_px"))
        self.assertIsNotNone(found("a_frame_of_10_px"))
        self.assertIsNone(found("a_frame_of_6_px"))
        self.assertIsNotNone(found("a_frame_of_12_px"))
        self.assertIsNone(found("red_half_with_much_blue"))
        self.assertIsNone(found("white_half_with_a_blue_that_is_too_low"))
        self.assertIsNone(found("white_half_with_a_red_that_is_too_low"))
        self.assertIsNotNone(found("white_half_with_a_red_that_is_high_enough"))
        self.assertIsNone(found("the_red_half_is_brighter_a_little_higher_up"))
        self.assertIsNotNone(found("the_red_half_is_brighter_a_little_lower_down"))
        self.assertIsNotNone(found("the_red_half_is_brighter_much_higher_up"))
        self.assertEqual(found("the_red_half_starts_at_the_top_of_the_region"), [884.0, 1752.0, 100.0])
        self.assertIsNone(found("the_red_half_starts_a_row_above_the_region"))
        self.assertIsNone(found("no_button"))

    def test_the_button_that_is_nearest_the_middle_wins(self):
        cases = by_name()
        for name in ("find_two_buttons_the_middle_one_wins", "find_two_buttons_the_middle_one_wins_the_other_way", "find_two_buttons_as_far_from_the_middle"):
            self.assertIsNotNone(results_of(cases[name])[0], name)

    def test_the_button_is_where_the_canvas_expects_it(self):
        """45 px sideways, 60 px up or down and 28 px wider or narrower are allowed."""
        cases = by_name()
        self.assertEqual(results_of(cases["check_exact"])[0][0], True)
        self.assertEqual(results_of(cases["check_none"])[0][0], None)
        self.assertEqual(results_of(cases["check_dx_45"])[0][0], True)

    def test_the_display_is_changed_in_the_order_of_the_code(self):
        """adapt_display(): the record is written first, then `wm size`, then a look at the screen; a record that cannot be written and a size that is
        refused leave the display as it was (and the record forgotten)."""
        cases = by_name()
        for name, case in cases.items():
            kinds = [k for k in kinds_of(case) if k in ("record_write", "wm_set")]
            if "record_write" in kinds and "wm_set" in kinds:
                self.assertLess(kinds.index("record_write"), kinds.index("wm_set"), name)
        self.assertTrue(any("wm_set" in kinds_of(c) and "record_forget" in kinds_of(c) for c in cases.values()))

    def test_a_record_that_sets_nothing_is_no_record(self):
        """load_wm_record(): the record has to be an object with a "set" that is not empty, zero or false; any other is no record at all."""
        cases = by_name()
        forgotten = lambda name: "record_forget" in kinds_of(cases["init_with_a_record_that_sets_" + name])  # noqa: E731
        for name in ("a_tenth", "minus_a_tenth", "five", "true", "a_list", "an_object"):
            self.assertTrue(forgotten(name), name)
        for name in ("zero", "zero_point_zero", "empty", "null", "false", "an_empty_list", "an_empty_object"):
            self.assertFalse(forgotten(name), name)

    def test_detect_screen_says_whether_it_saw_a_screen(self):
        cases = by_name()
        self.assertEqual(results_of(cases["detect_finds_the_screen"]), [True])
        self.assertEqual(results_of(cases["detect_finds_no_display"]), [False])
        self.assertEqual(results_of(cases["detect_cannot_look"]), [])
        self.assertIn("raised", kinds_of(cases["detect_cannot_look"]))


if __name__ == "__main__":
    unittest.main()
