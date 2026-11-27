"""The file that the C++ port of the text reader (the table of Tesseract made into lines, gamebot.ocr_lines) is tested
against is what gamebot.py makes of its tables now.  If this fails, ocr_lines() or ocr_line() in gamebot.py changed: run
python3 tools/make_text_golden.py and port the change to SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoText.cpp (its
test then says what differs).  The tables are in the file (36 of them were read from frames of real fights by Tesseract),
so no tesseract program is needed here."""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_text_golden.py")


class TextGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())


if __name__ == "__main__":
    unittest.main()
