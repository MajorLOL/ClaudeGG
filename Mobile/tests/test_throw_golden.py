"""The file that the C++ port of the readers and the sums of the throw (measure_ring, find_ball and where the ball came down, enc_buttons,
in_encounter, ball_ready, result_ok_button, ring_speed, refit_timing, curve_lean, spin_points and aim_note of gamebot.py, with the numbers
of the throw) is tested against is what the Python code does now.  If this fails, one of those changed: run
python3 tools/make_throw_golden.py  and port the change to SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoThrow.cpp (its test then says
what differs).  The file holds pictures that are drawn on the canvas as it says (a background, discs, rings, noise) with what the readers
made of them (a picture made to be exactly on the edge of every number) and the numbers of the sums.
(The file is what this version of OpenCV and numpy make: the C++ port has to come to the same numbers to the last bit.)"""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_throw_golden.py")


class ThrowGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())


if __name__ == "__main__":
    unittest.main()
