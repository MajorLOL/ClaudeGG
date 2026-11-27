"""The file that the C++ port of the fight loop (fight_battle in gamebot.py) is tested against is what gamebot.py
does now.  If this fails, the loop in gamebot.py (or something it calls: battle_fight.py, battle_vision.py,
battle_minigame.py, battle_engine.py) changed: run  python3 tools/make_loop_golden.py  and port the change to
SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoLoop.cpp (its test then says what differs).  The file holds 51
fights as a list of what the loop was shown (pictures, text read from them) and what it did (every tap, swipe,
log line and sleep, with the time on a fake clock), and the numbers of the loop (CHARGE_HOLD, GAME_BLOCK ...), which
the port is held to as well.  (Another version of OpenCV than the one that made the file
moves a few pixels: that is allowed for up to 5 % of the fights.)"""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_loop_golden.py")


class LoopGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())


if __name__ == "__main__":
    unittest.main()
