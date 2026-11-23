"""Team GO Rocket at a PokéStop (gamebot.rocket_battle): the screens before and after the fight, from a recording
of a battle with Leader Cliff by hand (23 November).  The screens are faked by what OCR reads on them.
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
except Exception:  # noqa: BLE001
    G = None

W, H = 1768, 2208


def line(text, x, y):
    words = text.split()
    step = 120
    return (text, x, y, [(wd, x + i * step, y) for i, wd in enumerate(words)])


SCREENS = {
    "speech": [line("Cliff's my name. Battling's my game.", 400, 1900)],
    "battle": [line("Leader Cliff", 300, 1300), line("BATTLE", 884, 1960)],
    "radar": [line("Use your Rocket Radar?", 500, 800), line("YES", 884, 1050), line("NO", 884, 1200)],
    "party2": [line("CHOOSE YOUR PARTY", 600, 1350), line("Recommended Battle Party", 500, 1450),
               line("CP2699", 590, 1560), line("CP2626", 900, 1560), line("USE THIS PARTY", 750, 1720)],
    "list": [line("TAGS POKEMON", 600, 150), line("CP418 CP1054 CP45", 400, 900), line("CANCEL", 400, 2000),
             line("DONE", 1200, 2000)],
    "party3": [line("Recommended Battle Party", 500, 1450), line("CP2699", 590, 1560), line("CP2626", 900, 1560),
               line("CP2888", 1220, 1560), line("USE THIS PARTY", 750, 1720)],
    "fight": [],
    "lost": [line("Leader Cliff: What? But I can't lose!", 400, 1900)],
    "summary": [line("SUMMARY", 884, 300), line("TOTAL +7", 600, 1700)],
    "catch": [],
    "map": [],
}


class Phone:
    def __init__(self):
        self.scene = "speech"
        self.taps = []
        self.logs = []
        self.picked = False

    def tap(self, x, y, ms=120):
        fx, fy = x / W, y / H
        self.taps.append((self.scene, round(fx, 2), round(fy, 2)))
        sc = self.scene
        if sc == "speech":
            self.scene = "battle"
        elif sc == "battle" and fy > 0.85 and fx < 0.45:          # (not on the round X in its middle)
            self.scene = "radar"
        elif sc == "radar" and abs(fy - 1050 / H) < 0.03:
            self.scene = "party2"
        elif sc == "party2" and fx > 0.6 and 0.70 < fy < 0.80:     # (the empty third slot)
            self.scene = "list"
        elif sc == "list" and fx < 0.3 and 0.6 < fy < 0.8:
            self.picked = True
        elif sc == "list" and self.picked and fx > 0.6 and fy > 0.85:
            self.scene = "party3"
        elif sc == "party3" and abs(fy - 1720 / H) < 0.03:
            self.scene = "fight"
        elif sc == "lost":
            self.scene = "summary"
        elif sc == "summary":
            self.scene = "catch"


@unittest.skipIf(G is None, "gamebot cannot be imported here")
class RocketBattle(unittest.TestCase):
    def setUp(self):
        self.saved_g = {n: getattr(G, n) for n in ("ocr_lines", "screen_class", "rocket_fight", "log", "save_async",
                                                     "_frac_xy")}
        self.saved_s = {n: getattr(S, n) for n in ("screenshot", "tap", "on_map")}
        self.sleep = G.time.sleep
        G.time.sleep = lambda s: None
        self.bv = __import__("battle_fight").state

    def tearDown(self):
        for n, f in self.saved_g.items():
            setattr(G, n, f)
        for n, f in self.saved_s.items():
            setattr(S, n, f)
        G.time.sleep = self.sleep
        __import__("battle_fight").state = self.bv

    def test_from_the_first_words_to_the_shadow_pokemon(self):
        phone = Phone()
        img = np.zeros((H, W, 3), np.uint8)
        BF = __import__("battle_fight")
        BF.state = lambda feat: "fight" if phone.scene == "fight" else "other"
        G.ocr_lines = lambda *a, **k: SCREENS[phone.scene]
        G.screen_class = lambda shot: ("encounterScreen", 0.9) if phone.scene == "catch" else ("onbekend", 0.0)

        def fight(stop=None):
            phone.scene = "lost"
            return 90
        G.rocket_fight = fight
        G.log = phone.logs.append
        G.save_async = lambda *a, **k: None
        S.screenshot = lambda *a, **k: img
        S.tap = phone.tap
        S.on_map = lambda _img: phone.scene == "map"
        res = G.rocket_battle()
        log = "\n".join(phone.logs)
        self.assertEqual(res, "catch", log)
        self.assertIn("rocket: the party has 2 Pokémon - choosing a third one for slot 3", log)
        self.assertIn("rocket: USE THIS PARTY", log)
        self.assertTrue(phone.picked, log)
        self.assertFalse([t for t in phone.taps if t[0] == "battle" and 0.45 < t[1] < 0.55], log)   # (not the X)


if __name__ == "__main__":
    unittest.main()
