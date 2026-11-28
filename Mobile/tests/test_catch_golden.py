"""The file that the C++ port of the catch screen around the throw (do_encounter, wait_for_result, fast_catch_leave, tap_button, pick_berry with
tray_labels, finish_catch, ... of gamebot.py, played on a pretend phone with a pretend clock) is tested against is what the Python code does now.
If this fails, one of those changed: run  python3 tools/make_catch_golden.py  and port the change to
SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoCatch.cpp (its test then says what differs).  The file holds, for every little story, what the
phone was asked for (screenshots, the screen classifier, the detector of buttons, the text readers, the berry tray, what the throws and the steps
did) and what the code did (every tap, BACK, wait, log line and kept picture, what it returned or raised and what it remembers) in order."""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_catch_golden.py")
sys.path.insert(0, os.path.join(HERE, "..", "tools"))


class CatchGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())

    def test_every_call_of_the_catch_screen_has_stories(self):
        import make_catch_golden as M
        calls = {}
        for story in M.all_stories():
            for call in story["spec"]["calls"]:
                calls[call["fn"]] = calls.get(call["fn"], 0) + 1
        for fn in ("do_encounter", "wait_for_result", "fast_catch_leave", "catch_result_button", "tap_catch_result", "tap_button", "pick_berry",
                   "tray_labels", "finish_catch", "mark_caught"):
            self.assertGreaterEqual(calls.get(fn, 0), 3, fn)
        self.assertEqual(sorted(calls), sorted(set(calls)))

    def test_the_stories_have_their_own_names(self):
        import make_catch_golden as M
        names = [s["id"] for s in M.all_stories()]
        self.assertEqual(len(names), len(set(names)))

    def test_python_does_what_the_port_imitates(self):
        """Things of Python that the C++ port has to do by hand (the stories hold them too): repr() of a text, and the errors of int() and float()."""
        self.assertEqual(repr("PINAP'S"), '"PINAP\'S"')
        self.assertEqual(repr("A'B\"C"), "'A\\'B\"C'")
        self.assertEqual(repr("A​"), "'A\\u200b'")
        self.assertEqual(repr("\x01"), "'\\x01'")
        self.assertEqual(repr("é"), "'é'")
        with self.assertRaises(ValueError) as e:
            int("266.5")
        self.assertEqual(str(e.exception), "invalid literal for int() with base 10: '266.5'")
        with self.assertRaises(ValueError) as e:
            float("abc")
        self.assertEqual(str(e.exception), "could not convert string to float: 'abc'")
        with self.assertRaises(TypeError) as e:
            int(None)
        self.assertEqual(str(e.exception), "int() argument must be a string, a bytes-like object or a real number, not 'NoneType'")

    def test_the_file_is_what_the_port_reads(self):
        import make_catch_golden as M
        with open(M.OUT, "rb") as f:
            doc = json.loads(M.unpack(f.read()))
        self.assertEqual(doc["start"], M.START)
        self.assertGreater(len(doc["cases"]), 300)
        for case in doc["cases"]:
            self.assertEqual(case["events"][0][0], "call", case["id"])
            self.assertEqual(case["events"][-1][0], "state", case["id"])


if __name__ == "__main__":
    unittest.main()
