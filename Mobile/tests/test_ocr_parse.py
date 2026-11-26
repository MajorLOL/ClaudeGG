"""The table of words that Tesseract gives (gamebot.ocr_lines / tray_labels), without the Tesseract program.
Run: python3 -m unittest discover -s tests"""
import os
import sys
import tempfile
import types
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
os.environ.setdefault("HOME", tempfile.mkdtemp())
try:
    import gamebot as G
except Exception:  # noqa: BLE001
    G = None

HEAD = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def table(words):
    """Tesseract's tsv output for [(text, left, top, width, height, conf), ...]."""
    rows = [HEAD, "1\t1\t0\t0\t0\t0\t0\t0\t1768\t2208\t-1\t"]
    for i, (text, left, top, width, height, conf) in enumerate(words):
        rows.append(f"5\t1\t1\t1\t1\t{i + 1}\t{left}\t{top}\t{width}\t{height}\t{conf}\t{text}")
    return ("\n".join(rows) + "\n").encode()


@unittest.skipIf(G is None, "gamebot.py cannot be imported here")
class OcrTable(unittest.TestCase):
    def setUp(self):
        self.run = G.subprocess.run

    def tearDown(self):
        G.subprocess.run = self.run

    def read(self, words, **kw):
        G.subprocess.run = lambda *a, **k: types.SimpleNamespace(stdout=table(words))
        return G.ocr_lines(np.zeros((2208, 1768, 3), np.uint8), **kw)

    def test_words_on_one_line(self):
        lines = self.read([("Good", 800, 950, 200, 80, 91), ("effort!", 1010, 955, 260, 80, 88)])
        self.assertEqual([t for t, _x, _y, _ws in lines], ["GOOD EFFORT!"])
        self.assertEqual(lines[0][3][0], ("GOOD", 900, 990))             # (the middle of the word)

    def test_a_quote_does_not_swallow_the_rest(self):
        """A speck that is read as a double quote opened a 'quoted field' for the table reader: every word
        after it was lost.  The result screen of a real fight was 'not read' that way."""
        words = [("&", 1040, 640, 30, 40, 55), ('"', 947, 700, 20, 20, 61), ("GOOD", 800, 950, 200, 80, 91),
                 ('"EFFORT!', 800, 1100, 260, 80, 85), ("NEXT", 780, 1890, 120, 40, 90),
                 ("BATTLE", 920, 1890, 150, 40, 90)]
        lines = self.read(words)
        text = " ".join(t for t, _x, _y, _ws in lines)
        for word in ("GOOD", "EFFORT!", "NEXT BATTLE"):
            self.assertIn(word, text)
        import battle_nav as BN
        self.assertEqual(BN.result_kind(lines), "loss")

    def test_unsure_words_are_left_out(self):
        lines = self.read([("GOOD", 800, 950, 200, 80, 91), ("x#", 100, 100, 30, 30, 12)])
        self.assertEqual([t for t, _x, _y, _ws in lines], ["GOOD"])

    def test_positions_are_those_of_the_whole_picture(self):
        lines = self.read([("BATTLE", 100, 50, 200, 40, 90)], y0=1000, scale=0.5)
        self.assertEqual(lines[0][3][0], ("BATTLE", 400, 1140))          # ((100 + 100) / 0.5, (50 + 20) / 0.5 + 1000)

    def test_no_tesseract_program(self):
        def missing(*a, **k):
            raise FileNotFoundError("tesseract")
        G.subprocess.run = missing
        self.assertEqual(G.ocr_lines(np.zeros((100, 100, 3), np.uint8)), [])


if __name__ == "__main__":
    unittest.main()
