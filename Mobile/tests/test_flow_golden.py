"""The file that the C++ port of the walk around a fight (battle_open_menu, _battle_to_map and battle_run in gamebot.py) is
tested against is what gamebot.py does now.  If this fails, the walk in gamebot.py (or something it calls: battle_nav.py,
battle_vision.py, the check for the map in spin_stop.py) changed: run  python3 tools/make_flow_golden.py  and port the change to
SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoFlow.cpp (its test then says what differs).  The file holds 133 stories as a
list of what the walk was given (screenshots, text read from them, the answers of the check for the map and of the screen
classifier, the fights that were fought) and what it did (every tap, swipe, BACK, log line, sleep and saved picture, with the
time on a fake clock), the pictures that the walk gives to the text reader for the label of a button, and the numbers of the
walk (CLAIM_TAPS, HOME_SCROLL ...), which the port is held to as well.  (Another version of OpenCV than the one that made the
file moves a few pixels: that is allowed for up to 5 % of the stories.)"""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_flow_golden.py")


class FlowGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())


if __name__ == "__main__":
    unittest.main()
