"""The file that the C++ port of a step on the map (do_map and do_pokestop of gamebot.py, the camera that turns when nothing is in view,
the looks of the Brain at the map, a fast catch that is checked on the map, the readers of pixels ring_spun, bag_full, looks_spun and
box_full_ball) is tested against is what the Python code does now.  If this fails, one of those changed: run
python3 tools/make_map_golden.py  and port the change to SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoMap.cpp or
ClaudeGG_PokemonGoBrain.cpp (their test then says what differs).  The file holds pictures with what the four readers of pixels make of
them (a picture made to be exactly on the edge of every number), and stories as a list of what the code was given (screenshots, what the
map detector found in a part of a picture, the random numbers that were drawn, the counts of the day) and what it did (every tap, swipe,
log line, sleep, kept picture and call of the parts that are not ported yet, with the time on a fake clock, what it returned and what
it remembered afterwards), and the numbers of the map.
(Another version of OpenCV than the one that made the file moves a few pixels: that is allowed for up to 5 % of the cases.)"""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_map_golden.py")


class MapGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())


if __name__ == "__main__":
    unittest.main()
