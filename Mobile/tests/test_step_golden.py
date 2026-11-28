"""The file that the C++ port of one step of the bot (step(), heat_wait(), leave_group_screen(), is_rocket_text(), storage_full() and pause_catching()
of gamebot.py, played on a pretend phone with a pretend clock) is tested against is what the Python code does now.  If this fails, one of those
changed: run  python3 tools/make_step_golden.py  and port the change to SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoStep.cpp (its test then
says what differs).  The file holds, for every little story, what the phone was asked for (screenshots, the screen classifier, the detector of
buttons, the text readers, the temperatures, the power state, and what the parts that are not in the port answered and how long they took) and what
the code did (every tap, BACK, wait, log line and kept picture, every call of those parts, what it returned or raised and what it remembers) in
order."""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_step_golden.py")
sys.path.insert(0, os.path.join(HERE, "..", "tools"))


class StepGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())

    def test_every_call_has_stories(self):
        import make_step_golden as M
        calls = {}
        for story in M.all_stories():
            for call in story["spec"]["calls"]:
                calls[call["fn"]] = calls.get(call["fn"], 0) + 1
        for fn in ("step", "heat_wait", "leave_group_screen", "is_rocket_text", "storage_full", "pause_catching", "resume_catching"):
            self.assertGreaterEqual(calls.get(fn, 0), 2, fn)
        self.assertGreater(calls["step"], 150)

    def test_the_stories_have_their_own_names(self):
        import make_step_golden as M
        names = [s["id"] for s in M.all_stories()]
        self.assertEqual(len(names), len(set(names)))

    def test_python_does_what_the_port_imitates(self):
        """Things of Python that the C++ port has to do by hand: the whole number of a temperature or a time in a log line (f"{x:.0f}" rounds a
        half to the even number, as printf does), what the reader of text gives (capitals, white space as one space) and the minutes of a time."""
        self.assertEqual("%s" % f"{42.5:.0f}", "42")
        self.assertEqual("%s" % f"{43.5:.0f}", "44")
        self.assertEqual("%s" % f"{42.9:.0f}", "43")
        self.assertEqual("%s" % f"{(1000.0 + 2700.0 - 1000.0) / 60:.0f}", "45")
        self.assertEqual(" ".join("team  go\trocket ".upper().split()), "TEAM GO ROCKET")
        self.assertEqual(30 * 60 // 60, 30)
        self.assertEqual(300 // 60, 5)

    def test_the_file_is_what_the_port_reads(self):
        import make_step_golden as M
        with open(M.OUT, "rb") as f:
            doc = json.loads(M.unpack(f.read()))
        self.assertEqual(doc["start"], M.START)
        self.assertGreater(len(doc["cases"]), 250)
        for case in doc["cases"]:
            self.assertEqual(case["events"][0][0], "call", case["id"])
            self.assertEqual(case["events"][-1][0], "state", case["id"])


if __name__ == "__main__":
    unittest.main()
