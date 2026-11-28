"""The file that the C++ port of the item bag (what the bag keeps of each item, the rows of a page of the bag, the question 'Discard <item>?', the ways of
looking at a page, the way to the bag and back, the clean-up of a full bag, the red FULL marks of the main menu and closing the game when storage and bag
are both full: gamebot.py and bag_rules.py, played on a pretend phone with a pretend clock) is tested against is what the Python code does now.  If this
fails, one of those changed: run  python3 tools/make_bag_golden.py  and port the change to SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoBag.cpp (its
test then says what differs).  The file holds, for every little story, what the phone was asked for (screenshots, the text reader's lines, the number in
the box of the question, the answers of adb) and what the code did (every tap, swipe, BACK, wait, log line and kept picture, the daily run being told that
it is over, what it returned or raised and what it remembers) in order."""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_bag_golden.py")
sys.path.insert(0, os.path.join(HERE, "..", "tools"))


class BagGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())

    def test_every_call_has_stories(self):
        import make_bag_golden as M
        calls = {}
        for story in M.all_stories():
            for call in story["spec"]["calls"]:
                calls[call["fn"]] = calls.get(call["fn"], 0) + 1
        for fn in ("plain_name", "rules", "bag_plan", "bag_keep", "bag_rows", "bag_like", "incense_tile", "bag_ocr", "discard_dialog", "canvas",
                   "set_discard_number", "open_bag", "bag_to_map", "clean_bag", "check_menu_full", "close_game_completely", "check_all_full",
                   "cancel_exit", "cancel_discard", "leave_question"):
            self.assertGreaterEqual(calls.get(fn, 0), 2, fn)
        self.assertGreater(calls["clean_bag"], 20)

    def test_the_stories_have_their_own_names(self):
        import make_bag_golden as M
        names = [s["id"] for s in M.all_stories()]
        self.assertEqual(len(names), len(set(names)))

    def test_python_does_what_the_port_imitates(self):
        """Things of Python that the C++ port has to do by hand: the name without accents and punctuation ('Poké Ball' is 'POKE BALL'), a name split on
        white space, the words of a name in capitals at the start of each word, the whole number of a number that was set as text or as a fraction, and
        the digits of any script that \\d and int() take."""
        self.assertEqual(" ".join("Poké-Ball".encode("ascii", "ignore").decode().upper().split()), "POK-BALL")
        self.assertEqual("POKE BALL".title(), "Poke Ball")
        self.assertEqual("GOLDEN RAZZ BERRY".title(), "Golden Razz Berry")
        self.assertEqual(int(3.9), 3)
        self.assertEqual(int(-3.9), -3)
        self.assertEqual(int(float("1e2")), 100)
        self.assertEqual(int("١٢"), 12)
        self.assertEqual(7 // 2, 3)
        self.assertEqual(-7 // 2, -4)
        with self.assertRaises(OverflowError):
            int(float("inf"))
        with self.assertRaises(ValueError):
            int(float("nan"))
        with self.assertRaises(ZeroDivisionError) as why:
            sum([]) // len([])
        self.assertEqual(str(why.exception), "integer division or modulo by zero")

    def test_the_file_is_what_the_port_reads(self):
        import make_bag_golden as M
        with open(M.OUT, "rb") as f:
            doc = json.loads(M.unpack(f.read()))
        self.assertEqual(doc["start"], M.START)
        self.assertGreater(len(doc["cases"]), 300)
        for case in doc["cases"]:
            self.assertEqual(case["events"][0][0], "call", case["id"])
            self.assertEqual(case["events"][-1][0], "state", case["id"])


if __name__ == "__main__":
    unittest.main()
