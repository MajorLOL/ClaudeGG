"""The file that the C++ port of battle_minigame is tested against is what battle_minigame.py answers now.  If
this fails, battle_minigame.py changed: run  python3 tools/make_minigame_golden.py  and port the change to
SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoMinigame.cpp (its test then says what differs).  (Another
version of OpenCV than the one that made the file moves a few pixels: that is allowed for a few of the pictures.)"""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_minigame_golden.py")


class MinigameGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())


if __name__ == "__main__":
    unittest.main()
