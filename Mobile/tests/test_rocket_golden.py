"""The file that the C++ port of the way through a fight of Team GO Rocket (rocket_battle() of gamebot.py: the speech bubbles, BATTLE, the radar question,
the party, the list of Pokémon, the summary, the Shadow Pokémon to catch - played on a pretend phone with a pretend clock) is tested against is what the Python
code does now.  If this fails, one of those changed: run  python3 tools/make_rocket_golden.py  and port the change to
SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoRocket.cpp (its test then says what differs).  The file holds, for every little story, what the phone was
asked for (screenshots, the text reader's lines, the screen classifier, the fight reader) and what the code did (every tap, wait, log line and kept picture,
that the fight was played, and what it returned) in order."""
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_rocket_golden.py")
sys.path.insert(0, os.path.join(HERE, "..", "tools"))


class RocketGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())

    def test_the_stories_have_their_own_names(self):
        import make_rocket_golden as M
        names = [s["id"] for s in M.all_stories()]
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(len(names), 50)

    def test_every_answer_of_a_walk_happens(self):
        """A walk ends in each of the three ways, in more than two stories each, and no story makes the code stop with an error (that would be a mistake
        of the pretend phone)."""
        import make_rocket_golden as M
        with open(M.OUT, "rb") as f:
            doc = json.loads(M.unpack(f.read()))
        answers = {}
        for case in doc["cases"]:
            for event in case["events"]:
                if event[0] == "result":
                    answers[event[2]] = answers.get(event[2], 0) + 1
                if event[0] == "raised":
                    answers["raised"] = answers.get("raised", 0) + 1
        for answer in ("map", "catch", "failed"):
            self.assertGreaterEqual(answers.get(answer, 0), 3, answer)
        self.assertEqual(answers.get("raised", 0), 0, "a story that makes the code stop: the pretend phone is wrong")

    def test_every_branch_of_the_walk_is_played(self):
        """Every log line of the walk is in the stories (so every branch of rocket_battle() is played), and the fight is played in them."""
        import make_rocket_golden as M
        with open(M.OUT, "rb") as f:
            doc = json.loads(M.unpack(f.read()))
        logs, kinds = set(), set()
        for case in doc["cases"]:
            for event in case["events"]:
                kinds.add(event[0])
                if event[0] == "log":
                    logs.add(re.sub(r"\d+", "N", event[2]))
        for part in ("back on the map", "'Use your Rocket Radar?' - YES", "the party has N Pokémon - choosing a third one for slot N", "USE THIS PARTY (N Pokémon)",
                     "USE THIS PARTY (? Pokémon)", "the list of Pokémon - the first one", "DONE", "the summary - tapping on", "BATTLE",
                     "the Shadow Pokémon to catch - the normal bot catches it", "too many screens that are not known - stopping"):
            self.assertIn("rocket: " + part, logs)
        for kind in ("fight", "stop", "fight_state", "class", "ocr", "save", "tap", "sleep"):
            self.assertIn(kind, kinds)

    def test_the_edges_are_exact(self):
        """The stories of the edges: 25 screens that are not known are fine and 26 stop the walk, the 70th step is the last one, BATTLE has to be below the
        lower quarter of the screen (not on it), the catch screen has to be certain to 0.5 (not less), a number of the party is over a slot to the hair (724 of 1768 pixels is, 725 is not),
        and the numbers have to be over the line USE THIS PARTY (not on it)."""
        import make_rocket_golden as M
        with open(M.OUT, "rb") as f:
            doc = json.loads(M.unpack(f.read()))
        result = {c["id"]: [e[2] for e in c["events"] if e[0] == "result"][0] for c in doc["cases"]}
        self.assertEqual(result["twenty_five_screens_that_are_not_known"], "catch")
        self.assertEqual(result["twenty_six_screens_that_are_not_known"], "failed")
        self.assertEqual(result["the_map_comes_at_the_last_step"], "map")
        self.assertEqual(result["the_map_comes_one_step_too_late"], "failed")
        self.assertEqual(result["battle_is_at_the_edge_of_the_lower_quarter"], "failed")
        self.assertEqual(result["battle_is_just_inside_the_lower_quarter"], "catch")
        self.assertEqual(result["the_catch_screen_certainty_is_exactly_the_limit"], "catch")
        self.assertEqual(result["the_catch_screen_certainty_is_too_low"], "map")
        self.assertEqual(result["party_the_words_are_a_hair_inside_the_slot"], "catch")
        self.assertEqual(result["party_the_words_are_a_hair_outside_the_slot"], "failed")
        self.assertEqual(result["party_the_words_stand_on_the_line_use_this_party"], "failed")

    def test_python_does_what_the_port_imitates(self):
        """Things of Python that the C++ port has to do by hand: \\d of a pattern of text is every digit of every script (the Arabic ones too), fullmatch()
        wants the whole word, int() cuts towards zero, round() goes to the even number, a number that is a fraction is compared as it is."""
        self.assertTrue(re.fullmatch(r"(CP)?\d{3,4}", "CP٢٦٩٩"))
        self.assertTrue(re.fullmatch(r"(CP)?\d{3,4}", "2699"))
        self.assertTrue(re.fullmatch(r"(CP)?\d{3,4}", "CP418"))
        self.assertFalse(re.fullmatch(r"(CP)?\d{3,4}", "CP41"))
        self.assertFalse(re.fullmatch(r"(CP)?\d{3,4}", "CP26990"))
        self.assertFalse(re.fullmatch(r"(CP)?\d{3,4}", "CP2699\n"))
        self.assertFalse(re.fullmatch(r"(CP)?\d{3,4}", "XCP2699"))
        self.assertEqual(round(2.5), 2)
        self.assertEqual(round(3.5), 4)
        self.assertEqual(int(-0.5), 0)
        self.assertEqual(int(0.05 * 2208), 110)
        self.assertEqual(int(0.33 * 1768 * 1768 / 1768), int(583.44))
        self.assertTrue(abs(590 / 1768 - 0.33) < 0.08)
        self.assertEqual(int(round(2208 * 704.0 / 1768)), 879)


if __name__ == "__main__":
    unittest.main()
