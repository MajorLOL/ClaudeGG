"""The file that the C++ port of battle_engine is tested against is what battle_engine.py answers now.  If this
fails, battle_engine.py changed: run  python3 tools/make_engine_golden.py  and port the change to
SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoBattle.cpp (its test then says what differs)."""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_engine_golden.py")


class EngineGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())


if __name__ == "__main__":
    unittest.main()
