"""The file that the C++ port of the throw itself (throw_touch, throw_ball, humanize, aim, ring_track and watch_flight of gamebot.py, played on
a pretend phone with a pretend clock) is tested against is what the Python code does now.  If this fails, one of those changed: run
python3 tools/make_throwplay_golden.py  and port the change to SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoThrowPlay.cpp (its test then
says what differs).  The file holds, for every little story, what the phone was asked for (screenshots, pictures of the live video, the
detector's boxes, random numbers) and what the throw did (every command, wait, log line and what it learned) in order."""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_throwplay_golden.py")


class ThrowPlayGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())


if __name__ == "__main__":
    unittest.main()
