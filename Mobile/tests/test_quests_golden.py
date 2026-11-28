"""The file that the C++ port of the quests (the check whether the quest button on the map is gold, whether it is time to look at it, and the visit to
the GO PASS: gamebot.py, played on a pretend phone with a pretend clock) is tested against is what the Python code does now.  If this fails, one of those
changed: run  python3 tools/make_quests_golden.py  and port the change to SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoQuests.cpp (its test then
says what differs).  The file holds, for every little story, what the phone was asked for (screenshots, the text reader's lines, the screen classifier)
and what the code did (every tap, swipe, wait, log line and kept picture, what it returned or raised and what it remembers) in order."""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_quests_golden.py")
sys.path.insert(0, os.path.join(HERE, "..", "tools"))


class QuestsGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())

    def test_every_call_has_stories(self):
        import make_quests_golden as M
        calls = {}
        for story in M.all_stories():
            for call in story["spec"]["calls"]:
                calls[call["fn"]] = calls.get(call["fn"], 0) + 1
        for fn in ("quest_gold", "quests_due", "claim_quests"):
            self.assertGreaterEqual(calls.get(fn, 0), 10, fn)
        self.assertGreater(calls["claim_quests"], 50)

    def test_the_stories_have_their_own_names(self):
        import make_quests_golden as M
        names = [s["id"] for s in M.all_stories()]
        self.assertEqual(len(names), len(set(names)))

    def test_every_answer_of_a_visit_happens(self):
        """A visit ends in each of the four ways, in more than two stories each, and no story makes the code stop with an error (that would be a mistake of
        the pretend phone)."""
        import make_quests_golden as M
        with open(M.OUT, "rb") as f:
            doc = json.loads(M.unpack(f.read()))
        answers = {}
        for case in doc["cases"]:
            for event in case["events"]:
                if event[0] == "result" and event[2] in ("claimed", "nothing", "catch", "failed"):
                    answers[event[2]] = answers.get(event[2], 0) + 1
                if event[0] == "raised":
                    answers["raised"] = answers.get("raised", 0) + 1
        for answer in ("claimed", "nothing", "catch", "failed"):
            self.assertGreaterEqual(answers.get(answer, 0), 3, answer)
        self.assertEqual(answers.get("raised", 0), 0, "a story that makes the code stop: the pretend phone is wrong")

    def test_the_colours_of_the_edges_are_exact(self):
        import cv2
        import numpy as np
        import make_quests_golden as M
        for hsv in ((7, 200, 210), (8, 200, 210), (25, 200, 210), (26, 200, 210), (16, 119, 200), (16, 120, 200), (16, 181, 179), (16, 180, 180)):
            px = cv2.cvtColor(np.array([[M.bgr_for(*hsv)]], np.uint8), cv2.COLOR_BGR2HSV)[0, 0]
            self.assertEqual(tuple(int(v) for v in px), hsv)
        for bgr, hsv in (([0, 100, 200], (15, 255, 200)), ([51, 154, 255], (15, 204, 255)), ([0, 128, 255], (15, 255, 255))):    # (the top of saturation and value)
            px = cv2.cvtColor(np.array([[bgr]], np.uint8), cv2.COLOR_BGR2HSV)[0, 0]
            self.assertEqual(tuple(int(v) for v in px), hsv)

    def test_python_does_what_the_port_imitates(self):
        """Things of Python that the C++ port has to do by hand: int() cuts towards zero, the part of the picture that is looked at (a slice of a picture
        is cut at the edges, a negative start counted as 0 by max()), the first three pages of a list, the first 80 letters of a text, and what the
        upper case of a text holds."""
        self.assertEqual(int(1.9), 1)
        self.assertEqual(int(-0.5), 0)
        rows = list(range(10))
        self.assertEqual(rows[max(-3, 0):5], [0, 1, 2, 3, 4])
        self.assertEqual(rows[8:300], [8, 9])
        self.assertEqual(rows[300:400], [])
        self.assertEqual([1, 2, 3, 4, 5][:3], [1, 2, 3])
        self.assertEqual([][:3], [])
        self.assertEqual(len(("x" * 100)[:80]), 80)
        self.assertEqual("Go Pass: Page".upper(), "GO PASS: PAGE")
        self.assertTrue(all(w in "VIEW REWARDS".upper() for w in ("VIEW", "REWARDS")))
        self.assertFalse(all(w in "VIEW REWARD" for w in ("VIEW", "REWARDS")))
        self.assertTrue("GO PASS" in "go pass: page".upper() and ":" in "go pass: page")

    def test_the_file_is_what_the_port_reads(self):
        import make_quests_golden as M
        with open(M.OUT, "rb") as f:
            doc = json.loads(M.unpack(f.read()))
        self.assertEqual(doc["start"], M.START)
        self.assertGreater(len(doc["cases"]), 90)
        for case in doc["cases"]:
            self.assertEqual(case["events"][0][0], "call", case["id"])
            self.assertEqual(case["events"][-1][0], "state", case["id"])


if __name__ == "__main__":
    unittest.main()
