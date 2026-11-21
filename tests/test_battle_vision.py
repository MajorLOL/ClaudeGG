"""Unit tests for battle_vision (reading the picture of a GO Battle League fight).

The pictures in tests/fixtures/fight/ are frames of a real fight that was recorded with the recorder of the web
interface (35 % of the 1768 x 2208 canvas).  The tests bring them back to the full canvas, as the bot does with
every screenshot.   Run:  python3 -m unittest discover -s tests"""
import os
import sys
import unittest

import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import battle_fight as bf  # noqa: E402
import battle_vision as bv  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "fight")


def frame(name):
    img = cv2.imread(os.path.join(FIX, name + ".jpg"))
    assert img is not None, name
    return cv2.resize(img, (1768, 2208), interpolation=cv2.INTER_CUBIC)


class FightPictures(unittest.TestCase):
    def test_versus_screen(self):
        f = bv.features(frame("versus"))
        self.assertTrue(f["versus"])
        self.assertEqual(bf.state(f), "other")

    def test_fight_with_both_buttons_lit(self):
        img = frame("fight_ready")
        f = bv.features(img)
        self.assertEqual(bf.state(f), "fight")
        self.assertEqual(tuple(f["ready"]), (True, True))
        mine, foe = f["hp"]
        self.assertAlmostEqual(mine, 0.18, delta=0.04)
        self.assertAlmostEqual(foe, 0.31, delta=0.04)
        self.assertEqual(f["shields"], {"me": 1, "foe": 2})

    def test_second_pokemon(self):
        f = bv.features(frame("fight_lanturn"))
        self.assertEqual(bf.state(f), "fight")
        self.assertEqual(tuple(f["ready"]), (True, True))
        self.assertAlmostEqual(f["hp"][0], 0.77, delta=0.04)
        self.assertAlmostEqual(f["hp"][1], 0.57, delta=0.04)
        self.assertEqual(f["shields"], {"me": 0, "foe": 1})

    def test_questions_have_a_countdown_ring(self):
        for name in ("shield_question", "switch_popup", "no_shields"):
            f = bv.features(frame(name))
            self.assertTrue(f["ring"], name)
            self.assertEqual(bf.state(f), "prompt", name)

    def test_charged_attack_game_has_no_hp_bars(self):
        """The camera zooms in on the attacker: lightning bolts and sparks are not HP bars."""
        f = bv.features(frame("minigame_zoom"))
        self.assertEqual(f["hp"], (None, None))
        self.assertEqual(tuple(f["ready"]), (False, False))

    def test_banner_over_the_name_boxes(self):
        f = bv.features(frame("banner_over_hud"))
        self.assertTrue(f["hud"])
        self.assertEqual(tuple(f["ready"]), (False, False))     # (the buttons are hidden while the Pokémon is down)

    def test_result_screen(self):
        f = bv.features(frame("result_loss"))
        self.assertTrue(f["result"])
        self.assertFalse(f["hud"])
        self.assertEqual(bf.state(f), "result")

    def test_fight_pictures_are_no_results(self):
        for name in ("fight_ready", "fight_lanturn", "shield_question", "switch_popup", "no_shields",
                     "minigame_zoom", "banner_over_hud", "versus"):
            self.assertFalse(bv.features(frame(name))["result"], name)


class SmallPictures(unittest.TestCase):
    """The tests use fractions of the screen, so a smaller copy gives the same answers."""

    def test_half_size(self):
        img = cv2.imread(os.path.join(FIX, "fight_ready.jpg"))
        img = cv2.resize(img, (884, 1104), interpolation=cv2.INTER_AREA)
        f = bv.features(img)
        self.assertEqual(bf.state(f), "fight")
        self.assertEqual(tuple(f["ready"]), (True, True))
        self.assertAlmostEqual(f["hp"][1], 0.31, delta=0.05)


if __name__ == "__main__":
    unittest.main()
