"""The file that the C++ port of the fight against Team GO Rocket (rocket_fight() of gamebot.py: the fast taps, the shield question, the little game of the
type of a charged attack, until the HUD is gone for good - played on a pretend phone with a pretend clock and the real pictures of fights) is tested against is
what the Python code does now.  If this fails, one of those changed: run  python3 tools/make_rocketfight_golden.py  and port the change to
SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoRocketFight.cpp (its test then says what differs).  The file holds, for every little story, what the phone
was asked for (pictures, the text reader's lines, the stop of the person) and what the code did (every aim, go, pause, shield tap, swipe of the little game,
log line, and at the end the seconds the fight took) in order, every event with the time of the pretend clock."""
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_rocketfight_golden.py")
sys.path.insert(0, os.path.join(HERE, "..", "tools"))


def load():
    import make_rocketfight_golden as M
    with open(M.OUT, "rb") as f:
        return json.loads(M.unpack(f.read()))


class RocketFightGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())

    def test_the_stories_have_their_own_names(self):
        import make_rocketfight_golden as M
        names = [s["id"] for s in M.all_stories()]
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(len(names), 35)

    def test_no_story_makes_the_code_stop_with_an_error(self):
        """The code that ends a fight only ends it with the seconds it took (a story that makes it raise would be a mistake of the pretend phone)."""
        for case in load()["cases"]:
            kinds = [e[0] for e in case["events"]]
            self.assertEqual(kinds.count("result"), 1, case["id"])
            self.assertNotIn("raised", kinds, case["id"])
            self.assertEqual(kinds[-1], "result", case["id"])

    def test_every_branch_of_the_fight_is_played(self):
        """The log lines of the fight are all in the stories (so every branch of rocket_fight() is played): the fight starts, ours is read, a shield, the
        little game, the end, and the fight that never came."""
        logs, kinds = set(), set()
        for case in load()["cases"]:
            for event in case["events"]:
                kinds.add(event[0])
                if event[0] == "log":
                    logs.add(re.sub(r"\d+", "N", event[2]))
        joined = "\n".join(sorted(logs))
        for part in ("rocket: the fight has started", "rocket: ours is ", "rocket: an attack is coming - SHIELD", "rocket: little game of a ",
                     "rocket: fight ended after N s", "rocket: no fight came"):
            self.assertIn(part, joined)
        for kind in ("aim", "go", "pause", "sweep", "tap", "swipe", "log", "result", "wait_new", "screenshot", "ocr", "busy", "stop"):
            self.assertIn(kind, kinds)

    def test_the_edges_are_exact(self):
        """The stories of the edges: a fight that starts at 39.875 s is a fight and one that starts at 40.0 s too, one after 40.125 s is no fight; the HUD
        gone for ten seconds ends the fight (not for less); the fight is over after 300 s."""
        seconds = {c["id"]: [e[2] for e in c["events"] if e[0] == "result"][0] for c in load()["cases"]}
        self.assertEqual(seconds["no_fight_comes"], 40)
        self.assertEqual(seconds["the_fight_starts_a_picture_before_forty_seconds"], 50)
        self.assertEqual(seconds["the_fight_starts_a_picture_after_exactly_forty_seconds"], 50)
        self.assertEqual(seconds["the_fight_starts_a_picture_too_late"], 40)
        self.assertEqual(seconds["the_fight_goes_on_for_300_seconds"], 300)
        self.assertEqual(seconds["the_person_stops_the_bot_at_once"], 0)

    def test_python_does_what_the_port_imitates(self):
        """Things of Python that the C++ port has to do by hand: int() cuts towards zero, the top of a picture (0.2 of the height) is painted black with a slice."""
        self.assertEqual(int(0.2 * 1080), 216)
        self.assertEqual(int(0.2 * 2208), 441)
        self.assertEqual(int(-0.5), 0)
        self.assertEqual(round(2.5), 2)


if __name__ == "__main__":
    unittest.main()
