"""The file that the C++ port of the gifts (the friend list that is read, the readers of the gift screens, the memory of the day, a visit to one friend
and the whole round: gamebot.py, played on a pretend phone with a pretend clock) is tested against is what the Python code does now.  If this fails, one
of those changed: run  python3 tools/make_gifts_golden.py  and port the change to SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoGifts.cpp (its test
then says what differs).  The file holds, for every little story, what the phone was asked for (screenshots, the text reader's lines and strips, the
file of the gift memory) and what the code did (every tap, press, swipe, BACK, wait, log line, kept picture and write of the gift memory, what it
returned or raised and what it remembers) in order."""
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_gifts_golden.py")
sys.path.insert(0, os.path.join(HERE, "..", "tools"))


class GiftsGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())

    def test_every_call_has_stories(self):
        import make_gifts_golden as M
        calls = {}
        for story in M.all_stories():
            for call in story["spec"]["calls"]:
                calls[call["fn"]] = calls.get(call["fn"], 0) + 1
        for fn in ("parse_friends", "sent_arrow", "gift_icon", "find_pill_button", "send_button", "has_sticker_button", "is_gift_screen", "is_friend_list",
                   "any_text", "load_gift_state", "save_gift_state", "back_to_list", "visit_friend", "gifts_round"):
            self.assertGreaterEqual(calls.get(fn, 0), 2, fn)
        self.assertGreater(calls["visit_friend"], 40)
        self.assertGreater(calls["gifts_round"], 20)

    def test_the_stories_have_their_own_names(self):
        import make_gifts_golden as M
        names = [s["id"] for s in M.all_stories()]
        self.assertEqual(len(names), len(set(names)))

    def test_the_colours_of_the_edges_are_exact(self):
        import cv2
        import numpy as np
        import make_gifts_golden as M
        for hsv in ((140, 200, 200), (150, 121, 200), (172, 200, 200), (45, 150, 220), (67, 101, 171), (0, 40, 139)):
            px = cv2.cvtColor(np.array([[M.bgr_for(*hsv)]], np.uint8), cv2.COLOR_BGR2HSV)[0, 0]
            self.assertEqual(tuple(int(v) for v in px), hsv)

    def test_python_does_what_the_port_imitates(self):
        """Things of Python that the C++ port has to do by hand: the end of a slice of a picture that is negative counts from the other end, the list
        is cut at the edges, the first place of a word in a text, the white space and the digits that \\s and \\d take, and what a name is made of."""
        rows = list(range(10))
        self.assertEqual(rows[2:-3], [2, 3, 4, 5, 6])
        self.assertEqual(rows[0:-300], [])
        self.assertEqual(rows[5:2], [])
        self.assertEqual(rows[8:300], [8, 9])
        self.assertEqual(rows[300:400], [])
        self.assertEqual("MARIANNA ANNA TODAY".find("ANNA"), 4)
        self.assertEqual("ANNA".find("X"), -1)
        self.assertTrue(re.fullmatch(r"[A-Z0-9_]{3,15}", "A1_B2"))
        self.assertFalse(re.fullmatch(r"[A-Z0-9_]{3,15}", "ÄNNA"))
        self.assertFalse(re.fullmatch(r"[A-Z0-9_]{3,15}", "anna"))
        self.assertTrue(re.search(r"\d+\+?\s*DAYS?\s*AGO", "2+ DAYS AGO"))      # (a no-break space is white space for \s)
        self.assertTrue(re.search(r"\d+\+?\s*DAYS?\s*AGO", "٢ DAYS AGO"))               # (an Arabic digit is a digit for \d)
        self.assertTrue(re.fullmatch(r"\d+", "٢٣"))
        self.assertIsNone(re.search(r"\d+\s*H(OURS?)?\s*AGO", "3 HOUR AGO".replace("HOUR", "HRS")))
        self.assertEqual(" ".join("  friends \t social ".upper().split()), "FRIENDS SOCIAL")

    def test_the_file_is_what_the_port_reads(self):
        import make_gifts_golden as M
        with open(M.OUT, "rb") as f:
            doc = json.loads(M.unpack(f.read()))
        self.assertEqual(doc["start"], M.START)
        self.assertGreater(len(doc["cases"]), 250)
        for case in doc["cases"]:
            self.assertEqual(case["events"][0][0], "call", case["id"])
            self.assertEqual(case["events"][-1][0], "state", case["id"])


if __name__ == "__main__":
    unittest.main()
