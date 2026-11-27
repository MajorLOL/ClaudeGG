"""The file that the C++ port of battle_vision is tested against is what battle_vision.py reads now.  If this
fails, battle_vision.py changed: run  python3 tools/make_vision_golden.py  and port the change to
SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoVision.cpp (its test then says what differs).  (Another version
of OpenCV than the one that made the file moves a few pixels: that is allowed for up to 3 % of the pictures.)"""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_vision_golden.py")


class VisionGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())


if __name__ == "__main__":
    unittest.main()
