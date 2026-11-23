"""The GO Pass rewards (gamebot.claim_quests): the gold quest button on the map, the tab GO PASS, down to VIEW
REWARDS, CLAIM ALL, the X.  From screenshots of 23 November; the screens are faked by what OCR reads on them.
Run: python3 -m unittest discover -s tests"""
import os
import sys
import unittest

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

try:
    import gamebot as G
    import spin_stop as S
except Exception:  # noqa: BLE001
    G = None

W, H = 1768, 2208


def line(text, x, y):
    return (text, x, y, [(wd, x, y) for wd in text.split()])


SCREENS = {
    "research": [line("GO PASS", 450, 400), line("RESEARCH", 1300, 400), line("TODAY EVENTS SPECIAL", 884, 580),
                 line("Catch 10 Dark-type Pokemon", 600, 1550)],
    "pass_top": [line("GO PASS", 450, 400), line("RESEARCH", 1300, 400),
                 line("GO PASS: DYNAMAX TRAILS", 450, 560), line("GO PASS: NOVEMBER", 1300, 560),
                 line("GO Pass Deluxe: Dynamax Trails", 700, 1500)],
    "pass_down": [line("GO PASS: DYNAMAX TRAILS", 450, 560), line("Claimable rewards: 2", 884, 1180),
                  line("VIEW REWARDS", 884, 1350), line("Daily Tasks", 400, 1650)],
    "rewards": [line("GO PASS DELUXE: DYNAMAX", 884, 450), line("ULTRA BALL RARE CANDY", 884, 1150),
                line("CLAIM ALL", 280, 1900)],
    "claimed": [line("GO PASS DELUXE: DYNAMAX", 884, 450)],
    "map": [],
}


class Phone:
    def __init__(self, reward_pokemon=False):
        self.scene = "map"
        self.logs = []
        self.taps = []
        self.reward_pokemon = reward_pokemon

    def tap(self, x, y, ms=120):
        fx, fy = x / W, y / H
        self.taps.append((self.scene, round(fx, 2), round(fy, 2)))
        if self.scene == "map" and fx > 0.9 and 0.8 < fy < 0.9:
            self.scene = "research"
        elif self.scene in ("research", "pass_top") and abs(fy - 400 / H) < 0.02 and fx < 0.5:
            self.scene = "pass_top"
        elif self.scene == "pass_down" and abs(fy - 1350 / H) < 0.02:
            self.scene = "rewards"
        elif self.scene == "rewards" and abs(fy - 1900 / H) < 0.02:
            self.scene = "catch" if self.reward_pokemon else "claimed"
        elif self.scene in ("claimed", "pass_top", "pass_down", "research") and fy > 0.9:
            self.scene = "map"

    def swipe(self, *a, **k):
        if self.scene == "pass_top":
            self.scene = "pass_down"


@unittest.skipIf(G is None, "gamebot cannot be imported here")
class Quests(unittest.TestCase):
    def setUp(self):
        self.saved_g = {n: getattr(G, n) for n in ("ocr_lines", "screen_class", "log", "save_async", "_settled")}
        self.saved_s = {n: getattr(S, n) for n in ("screenshot", "tap", "on_map", "swipe")}
        self.sleep = G.time.sleep
        G.time.sleep = lambda s: None

    def tearDown(self):
        for n, f in self.saved_g.items():
            setattr(G, n, f)
        for n, f in self.saved_s.items():
            setattr(S, n, f)
        G.time.sleep = self.sleep

    def run_phone(self, phone):
        img = np.zeros((H, W, 3), np.uint8)
        G.ocr_lines = lambda *a, **k: SCREENS.get(phone.scene, [])
        G.screen_class = lambda shot: ("encounterScreen", 0.9) if phone.scene == "catch" else ("onbekend", 0.0)
        G.log = phone.logs.append
        G.save_async = lambda *a, **k: None
        G._settled = lambda *a, **k: img
        S.screenshot = lambda *a, **k: img
        S.tap = phone.tap
        S.swipe = phone.swipe
        S.on_map = lambda _img: phone.scene == "map"
        return G.claim_quests()

    def test_view_rewards_and_claim_all(self):
        phone = Phone()
        res = self.run_phone(phone)
        log = "\n".join(phone.logs)
        self.assertEqual(res, "claimed", log)
        self.assertIn("quests: CLAIM ALL", log)
        self.assertEqual(phone.scene, "map", log)

    def test_a_pokemon_as_a_reward_is_caught(self):
        phone = Phone(reward_pokemon=True)
        res = self.run_phone(phone)
        self.assertEqual(res, "catch", "\n".join(phone.logs))
        self.assertEqual(phone.scene, "catch")                 # (left as it is: the normal bot catches it)

    def test_the_gold_button(self):
        """The button drawn in the orange of the map of 23 November (BGR 60, 150, 240; no picture of the map
        itself in the repository), and white."""
        img = np.full((880, 704, 3), (120, 140, 110), np.uint8)
        h, w = img.shape[:2]
        spot = (int(G.QUEST_BTN[0] * w), int(G.QUEST_BTN[1] * h))
        self.assertFalse(G.quest_gold(img))
        cv2.circle(img, spot, int(0.032 * w), (60, 150, 240), -1)
        self.assertTrue(G.quest_gold(img))
        cv2.circle(img, spot, int(0.032 * w), (250, 250, 250), -1)
        self.assertFalse(G.quest_gold(img))


if __name__ == "__main__":
    unittest.main()
