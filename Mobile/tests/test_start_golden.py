"""The file that the C++ port of the start of the game and of the battles of a run (restart_game and its start-up screens in
spin_stop.py and gamebot.py, the two green button finders, the settings of the battles and auto_battle) is tested against is
what the Python code does now.  If this fails, one of those changed: run  python3 tools/make_start_golden.py  and port the change
to SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoStart.cpp (its test then says what differs).  The file holds 424 pictures
with what find_pill_button() and find_green_button() found on them, the settings of the battles with what battle_app(),
battle_league(), battle_count() and battle_wanted() make of them, and 72 stories as a list of what the code was given (screenshots,
what the text reader read, how the start of the game was going) and what it did (every tap, log line, sleep, the calls that close
and start the game, the battles that are started, with the time on a fake clock), and the numbers and texts of the start.
(Another version of OpenCV than the one that made the file moves a few pixels: that is allowed for up to 5 % of the cases.)"""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_start_golden.py")


class StartGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())


if __name__ == "__main__":
    unittest.main()
