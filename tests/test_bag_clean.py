"""The clean-up of a full item bag (gamebot.clean_bag): which items, how many are kept, and that YES is only
pressed when the question names the item and the number.  A fake bag stands in for the phone.
Run: python3 -m unittest discover -s tests"""
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

try:
    import gamebot as G
    import spin_stop as S
except Exception:  # noqa: BLE001  (the models of the bot are not on every machine)
    G = None

W, H = 1768, 2208
YES, NO = (884, 1200), (884, 1400)


class Bag:
    """A bag with items in rows; a trash can opens 'Discard <item>?' with a number that - and + change."""

    def __init__(self, items, misread=None):
        self.items = dict(items)                 # name -> count, in the order of the bag
        self.dialog = None                       # [name, number]
        self.logs = []
        self.misread = misread or {}             # name -> what the question says instead (a wrong item)
        self.top = 0                             # how far the list is scrolled (px)

    def rows(self):
        out = [(name, 400 + i * 300 - self.top) for i, name in enumerate(self.items)]
        return [(n, y) for n, y in out if 250 < y < 2000]

    def scroll(self, *_a, **_k):
        end = max(0, 400 + len(self.items) * 300 - 1900)
        self.moved = self.top < end
        self.top = min(self.top + 1100, end)

    def lines(self, _img=None, _y0=250):
        out = []
        for name, y in self.rows():
            out.append((name.title(), 600, y, [(w, 600, y) for w in name.title().split()]))
            out.append((f"x{self.items[name]}", 150, y + 160, [(f"x{self.items[name]}", 150, y + 160)]))
        return out

    def tap(self, x, y, ms=120):
        if self.dialog is None:
            if abs(x - 0.80 * W) < 60:
                for name, ry in self.rows():
                    if abs(y - (ry - 0.017 * H)) < 60:
                        self.dialog = [name, 1]
            return
        if abs(y - YES[1]) < 50:
            name, n = self.dialog
            self.items[name] -= n
            if self.items[name] <= 0:
                del self.items[name]
            self.dialog = None
        elif abs(y - NO[1]) < 50:
            self.dialog = None

    def swipes(self, strokes):
        if self.dialog is None:
            return
        for x, _y, _x2, _y2, _ms in strokes:
            if x > W / 2:
                self.dialog[1] = min(self.dialog[1] + 1, self.items[self.dialog[0]])
            else:
                self.dialog[1] = max(self.dialog[1] - 1, 1)

    def discard_dialog(self, _img):
        if self.dialog is None:
            return None
        name, n = self.dialog
        shown = self.misread.get(name, name)
        return f"Discard {shown.title()}?", n, YES, NO, 900


@unittest.skipIf(G is None, "gamebot cannot be imported here")
class CleanBag(unittest.TestCase):
    def setUp(self):
        self.saved_g = {n: getattr(G, n) for n in ("_open_bag", "_bag_to_map", "bag_ocr", "_discard_dialog", "log",
                                                     "screen_changed", "save_async")}
        self.saved_s = {n: getattr(S, n) for n in ("screenshot", "tap", "swipes", "swipe", "on_map")}
        self.sleep = G.time.sleep
        G.time.sleep = lambda s: None

    def tearDown(self):
        for n, f in self.saved_g.items():
            setattr(G, n, f)
        for n, f in self.saved_s.items():
            setattr(S, n, f)
        G.time.sleep = self.sleep

    def clean(self, bag):
        img = np.zeros((H, W, 3), np.uint8)
        G._open_bag = lambda: (img, bag.lines())
        G._bag_to_map = lambda: None
        G.bag_ocr = bag.lines
        G._discard_dialog = bag.discard_dialog
        G.log = bag.logs.append
        bag.moved = True
        G.screen_changed = lambda a, b, share=0.05: bag.moved
        G.save_async = lambda *a, **k: None
        S.screenshot = lambda *a, **k: img
        S.tap, S.swipes = bag.tap, bag.swipes
        S.swipe = bag.scroll
        S.on_map = lambda _img: False
        return G.clean_bag()

    def test_what_is_kept_of_each_item(self):
        """23 November: the bag was full (1627 of 1625).  Potions go, Max Potion and Max Revive stay at 30, Poké
        Balls at 400, Great Balls at 100, every berry at 30; Ultra Balls and Revives are not touched."""
        bag = Bag({"POTION": 3, "SUPER POTION": 2, "HYPER POTION": 3, "MAX POTION": 20, "REVIVE": 1,
                   "MAX REVIVE": 32, "POKE BALL": 487, "GREAT BALL": 185, "ULTRA BALL": 145, "RAZZ BERRY": 50,
                   "GOLDEN RAZZ BERRY": 12, "SILVER PINAP BERRY": 31})
        gone = self.clean(bag)
        self.assertEqual(bag.items, {"MAX POTION": 20, "REVIVE": 1, "MAX REVIVE": 30, "POKE BALL": 400,
                                     "GREAT BALL": 100, "ULTRA BALL": 145, "RAZZ BERRY": 30,
                                     "GOLDEN RAZZ BERRY": 12, "SILVER PINAP BERRY": 30}, bag.logs)
        self.assertEqual(gone, 3 + 2 + 3 + 2 + 87 + 85 + 20 + 1)

    def test_no_yes_when_the_question_names_another_item(self):
        bag = Bag({"POKE BALL": 487}, misread={"POKE BALL": "ULTRA BALL"})
        self.clean(bag)
        self.assertEqual(bag.items, {"POKE BALL": 487})
        self.assertTrue(any("answering NO" in line for line in bag.logs), bag.logs)

    def test_names(self):
        self.assertEqual(G.bag_keep("Poké Ball"), 400)
        self.assertEqual(G.bag_keep("Potion"), 0)
        self.assertEqual(G.bag_keep("Max Potion"), 30)
        self.assertEqual(G.bag_keep("Pinap Berry"), 30)
        self.assertIsNone(G.bag_keep("Ultra Ball"))
        self.assertIsNone(G.bag_keep("Revive"))
        self.assertIsNone(G.bag_keep("Master Ball"))
        self.assertIsNone(G.bag_keep("A spray-type medicine that restores the HP of one Pokemon"))


if __name__ == "__main__":
    unittest.main()
