"""The walk to the party screen when a new rank has to be claimed first (gamebot.battle_open_menu), with a fake
phone: no adb, no OCR program, no detector models.

The Battle screen then has an orange CLAIM RANK REWARDS! button where the green BATTLE button is.  The two
pictures of that screen are the lowest fifth of real screenshots (tests/fixtures/nav/).  The screens that the game
shows after the claim were not seen when this was written: the fake phone shows a screen without anything to tap
(it goes on with a tap anywhere) and a screen with a green button, which is what the bot is built to handle.
gamebot.py needs OpenCV and the TFLite runtime; without them these tests are skipped.
Run: python3 -m unittest discover -s tests"""
import os
import sys
import tempfile
import unittest

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
os.environ.setdefault("HOME", tempfile.mkdtemp())
try:
    import gamebot as G
    import spin_stop as S
    import battle_vision as BV
except Exception:  # noqa: BLE001
    G = S = BV = None

FIX = os.path.join(HERE, "fixtures")
W, H = 1768, 2208


def line(text, x, y):
    words = text.split()
    return (text, x, y, [(w, x + 60 * i, y) for i, w in enumerate(words)])


def battle_screen(name):
    strip = cv2.imread(os.path.join(FIX, "nav", name + ".jpg"))
    full = np.full((strip.shape[0] * 5, strip.shape[1], 3), 255, np.uint8)
    full[-strip.shape[0]:] = strip
    return cv2.resize(full, (W, H), interpolation=cv2.INTER_CUBIC)


def fight_picture(name):
    return cv2.resize(cv2.imread(os.path.join(FIX, "fight", name + ".jpg")), (W, H), interpolation=cv2.INTER_CUBIC)


LINES = {
    "home_claim": [line("GO BATTLE LEAGUE", 600, 900), line("BASIC REWARDS", 650, 1700)],
    "home_battle": [line("GO BATTLE LEAGUE", 600, 900), line("BASIC REWARDS", 650, 1700)],
    "rankup": [line("YOU REACHED RANK 7", 500, 700)],
    "rewards": [line("RANK 7 REWARDS", 600, 600)],
    "shop": [line("SPECIAL OFFER", 600, 600)],
    "party": [line("GREAT LEAGUE", 600, 300), line("MAX CP PER POKEMON: 1500", 500, 380),
              line("CHOOSE YOUR PARTY", 500, 800), line("USE THIS PARTY", 700, 1930)],
    "catch": [], "stuck": [],
}


class Phone:
    """What is on the screen and what was done to it."""

    def __init__(self, scene="home_claim", after="rankup"):
        self.scene = scene
        self.after = after                 # the screen that comes after a tap on the claim button
        self.claim_works = True
        self.taps, self.seen, self.logs = [], [scene], []
        self.backs = self.walks_back = 0
        self.pictures = {}

    def picture(self):
        name = {"rankup": "versus", "catch": "versus", "stuck": "versus", "rewards": "result_loss",
                "shop": "result_loss"}.get(self.scene, self.scene)
        if name not in self.pictures:
            if name.startswith("home_"):
                self.pictures[name] = battle_screen(name)
            elif name == "party":
                self.pictures[name] = np.full((H, W, 3), 255, np.uint8)
            else:
                self.pictures[name] = fight_picture(name)
        return self.pictures[name]

    def to(self, scene):
        self.scene = scene
        self.seen.append(scene)

    def tap(self, x, y, ms=120):
        fx, fy = x / float(W), y / float(H)
        self.taps.append((self.scene, round(fx, 3), round(fy, 3)))
        if self.scene == "home_claim":
            if fy > 0.95 and 0.08 < fx < 0.94 and self.claim_works:
                self.to(self.after)
        elif self.scene == "rankup":
            self.to("rewards")                                  # (it goes on with a tap anywhere)
        elif self.scene == "rewards" and 0.33 < fx < 0.67 and 0.83 < fy < 0.89:
            self.to("home_battle")                              # (its green button)
        elif self.scene == "home_battle" and 0.32 < fx < 0.71 and fy > 0.972:
            self.to("party")

    def back(self):
        self.backs += 1

    def lines(self, img, y0=0, y1=None, scale=1.0):
        return [ln for ln in LINES[self.scene] if ln[2] >= y0]

    def label(self, img, button):
        return {"home_claim": "CLAIM RANK REWARDS!", "rewards": "OK", "shop": "BUY 100 COINS"}.get(self.scene, "")

    def klass(self, img):
        return ("encounterScreen", 0.9) if self.scene == "catch" else ("menusScreen", 0.8)

    def to_map(self, beat=None, leaving_setup=False):
        self.walks_back += 1
        return True


@unittest.skipIf(G is None, "gamebot.py cannot be imported here")
class ClaimFirst(unittest.TestCase):
    def setUp(self):
        self.saved = {n: getattr(G, n) for n in ("_settled", "ocr_lines", "button_label", "screen_class", "save_async",
                                                 "log", "battle_league", "_battle_to_map")}
        self.saved_s = {n: getattr(S, n) for n in ("tap", "back", "on_map", "screenshot")}

    def tearDown(self):
        for n, v in self.saved.items():
            setattr(G, n, v)
        for n, v in self.saved_s.items():
            setattr(S, n, v)

    def walk(self, phone, stay=True):
        G._settled = lambda first_wait=2.0: phone.picture()
        G.ocr_lines = phone.lines
        G.button_label = phone.label
        G.screen_class = phone.klass
        G.save_async = lambda name, img: None
        G.log = phone.logs.append
        G.battle_league = lambda: "Great League"
        G._battle_to_map = phone.to_map
        S.tap, S.back = phone.tap, phone.back
        S.on_map = lambda img: False
        S.screenshot = lambda *a, **k: phone.picture()
        return G.battle_open_menu(stay=stay)

    def test_a_rank_is_claimed_before_the_battle(self):
        phone = Phone()
        info = self.walk(phone)
        log = "\n".join(phone.logs)
        self.assertTrue(info["ok"], log)
        self.assertEqual(phone.seen, ["home_claim", "rankup", "rewards", "home_battle", "party"], log)
        first = phone.taps[0]
        self.assertEqual(first[0], "home_claim")
        self.assertTrue(0.2 < first[1] < 0.4 and first[2] > 0.95, first)       # on the button, left of the round X
        self.assertEqual(len([t for t in phone.taps if t[0] == "home_claim"]), 1, log)
        self.assertEqual(phone.backs, 0, log)                                   # BACK is never pressed on the way
        self.assertIn("something has to be claimed before the next battle (button 'CLAIM RANK REWARDS!')", log)
        self.assertIn("tapping the screen (nothing to tap is seen on it)", log)
        self.assertIn("tapping the green button 'OK'", log)
        self.assertIn("claimed - the BATTLE button is back", log)
        self.assertNotIn("leave", info)

    def test_nothing_changes_without_a_claim(self):
        phone = Phone("home_battle")
        info = self.walk(phone)
        log = "\n".join(phone.logs)
        self.assertTrue(info["ok"], log)
        self.assertEqual(phone.seen, ["home_battle", "party"])
        self.assertEqual(len(phone.taps), 1, log)
        self.assertNotIn("claim", log)

    def test_a_pokemon_that_comes_as_a_reward_is_left_alone(self):
        phone = Phone(after="catch")
        info = self.walk(phone)
        log = "\n".join(phone.logs)
        self.assertFalse(info["ok"])
        self.assertTrue(info.get("leave"), log)
        self.assertIn("a Pokémon to catch", info["why"])
        self.assertEqual([t for t in phone.taps if t[0] == "catch"], [], log)   # nothing is tapped on it ...
        self.assertEqual((phone.backs, phone.walks_back), (0, 0), log)          # ... and no BACK: that would be a flee
        self.assertIn("the screen is left as it is", log)

    def test_screens_that_do_not_come_to_an_end(self):
        phone = Phone(after="stuck")
        info = self.walk(phone)
        log = "\n".join(phone.logs)
        self.assertFalse(info["ok"])
        self.assertTrue(info.get("leave"), log)
        self.assertIn("did not come to an end", info["why"])
        taps = [t for t in phone.taps if t[0] == "stuck"]
        self.assertTrue(3 <= len(taps) <= G.CLAIM_STEPS, len(taps))             # (a tap now and then, to go on)
        self.assertEqual(set((t[1], t[2]) for t in taps),
                         {(round(int(G.CLAIM_TAP_ON[0] * W) / W, 3), round(int(G.CLAIM_TAP_ON[1] * H) / H, 3))})
        self.assertEqual((phone.backs, phone.walks_back), (0, 0), log)

    def test_a_button_that_sells_something_is_not_tapped(self):
        phone = Phone(after="shop")
        info = self.walk(phone)
        log = "\n".join(phone.logs)
        self.assertFalse(info["ok"])
        self.assertIn("not tapping the button 'BUY 100 COINS'", log)
        on_button = [t for t in phone.taps if t[0] == "shop" and 0.3 < t[1] < 0.7 and 0.82 < t[2] < 0.90]
        self.assertEqual(on_button, [], log)

    def test_a_claim_button_that_does_not_react(self):
        phone = Phone()
        phone.claim_works = False
        info = self.walk(phone)
        log = "\n".join(phone.logs)
        self.assertFalse(info["ok"])
        self.assertIn(f"tapped {G.CLAIM_TAPS} times", info["why"])
        self.assertEqual(len(phone.taps), G.CLAIM_TAPS, log)
        self.assertNotIn("leave", info)
        self.assertEqual(phone.walks_back, 1, log)                              # (the Battle screen: the usual way back)

    def test_the_run_of_battles_leaves_the_screen_too(self):
        phone = Phone(after="catch")
        calls = []
        saved = G.battle_open_menu
        try:
            G.battle_open_menu = lambda *a, **k: {"ok": False, "why": "a Pokémon to catch", "leave": True}
            G.log = phone.logs.append
            G._battle_to_map = phone.to_map
            S.screenshot = lambda *a, **k: calls.append("screenshot") or phone.picture()
            res = G.battle_run(lambda: None, lambda: False, 3, team=[])
        finally:
            G.battle_open_menu = saved
        self.assertEqual((res["fought"], res.get("leave")), (0, True))
        self.assertEqual((calls, phone.walks_back), ([], 0))                    # no look for the map, no way back


if __name__ == "__main__":
    unittest.main()
