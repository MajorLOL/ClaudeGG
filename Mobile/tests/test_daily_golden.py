"""The file that the C++ port of the daily run (gamebot.py: daily_cycle(), run_one_game(), finish_catch(), daily_order(), daily_limit(), last_slot(),
played on a pretend bot with a fake clock) is tested against is what the Python code does now.  If this fails, one of those changed: run
python3 tools/make_daily_golden.py  and port the change to SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoDaily.cpp (its test then says what
differs).  The file holds, for every story, what the bot was asked for (the apps, the steps, the screens) and what the code did (every log line,
wait, saved file, game started and closed, and what every call returned or raised) in order."""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_daily_golden.py")
sys.path.insert(0, os.path.join(HERE, "..", "tools"))


class DailyGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())

    def test_the_stories_have_their_own_names(self):
        import make_daily_golden as M
        names = [s["id"] for s in M.all_stories()]
        self.assertEqual(len(names), len(set(names)))

    def test_every_way_a_run_goes_happens(self):
        """A run starts in each of its ways (the daily time, the Start button, a bot started again), its time runs out, a catch is finished first,
        a step fails, the run is switched off, and the bot waits for the next day; and only the stories that are meant to make the code stop do."""
        import make_daily_golden as M
        with open(M.OUT, "rb") as f:
            doc = json.loads(M.unpack(f.read()))
        logs = [e[2] for c in doc["cases"] for e in c["events"] if e[0] == "log"]
        for start in ("daily run started:", "Start pressed - daily run starts now:", "bot started - daily run starts now:",
                      "the run time is up - finishing this catch first", "min is up - closing the game, the run ends", "error: ",
                      "daily run switched off", "daily run complete - next run at", "daily run waiting - next run at",
                      "daily run: stopped - the run time is up", "min played"):
            self.assertTrue(any(start in line for line in logs), start)
        raised = sorted(c["id"] for c in doc["cases"] if any(e[0] == "raised" for e in c["events"]))
        self.assertEqual(raised, ["file_without_done", "restart_fails"])

    def test_the_file_is_what_the_port_reads(self):
        import make_daily_golden as M
        with open(M.OUT, "rb") as f:
            doc = json.loads(M.unpack(f.read()))
        self.assertEqual(doc["start"], M.START)
        self.assertGreater(len(doc["cases"]), 40)
        for case in doc["cases"]:
            self.assertIn(case["events"][-1][0], ("result", "raised"), case["id"])


if __name__ == "__main__":
    unittest.main()
