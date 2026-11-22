"""Unit tests for battle_vision (reading the picture of a GO Battle League fight).

The pictures in tests/fixtures/fight/ are frames of a real fight that was recorded with the recorder of the web
interface (35 % of the 1768 x 2208 canvas).  The tests bring them back to the full canvas, as the bot does with
every screenshot.   Run:  python3 -m unittest discover -s tests"""
import os
import sys
import unittest

import cv2
import numpy as np

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

    def test_blue_button_counts_as_lit(self):
        """The second real fight (a screen recording of the phone): a lit Surf button has hardly a white ring, only
        the name under it turns from grey to white.  That was not seen, so Surf was never thrown."""
        dim = bv.features(frame("run2_dim"))
        self.assertTrue(dim["hud"])
        self.assertEqual(tuple(dim["ready"]), (False, False))
        right = bv.features(frame("run2_right_lit"))
        self.assertEqual(tuple(right["ready"]), (False, True))
        both = bv.features(frame("run2_both_lit"))
        self.assertEqual(tuple(both["ready"]), (True, True))
        self.assertEqual(bf.state(both), "fight")

    def test_shield_question_is_known_by_its_picture(self):
        """The big lilac shield tells the shield question from the switch question without reading any text."""
        for name in ("shield_question", "run2_shield_question"):
            f = bv.features(frame(name))
            self.assertTrue(f["hex"], name)
            self.assertEqual(bf.state(f), "prompt", name)
        for name in ("switch_popup", "no_shields", "fight_ready", "fight_lanturn", "run2_both_lit", "versus"):
            self.assertFalse(bv.features(frame(name))["hex"], name)

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


def small(name):
    """The picture as the fight loop reads it: the size of the live video."""
    img = cv2.imread(os.path.join(FIX, name + ".jpg"))
    return cv2.resize(img, (704, 880), interpolation=cv2.INTER_AREA)


class NameBoxes(unittest.TestCase):
    """The fingerprint of the text in a name box: it tells when another Pokémon came in."""

    def test_the_same_pokemon_gives_the_same_key(self):
        # two pictures of the second fight with the same foe, and one fight picture / one question of the first
        self.assertFalse(bv.key_differs(bv.name_key(small("run2_dim"), "foe"), bv.name_key(small("run2_right_lit"), "foe")))
        self.assertFalse(bv.key_differs(bv.name_key(small("run2_dim"), "me"), bv.name_key(small("run2_both_lit"), "me")))
        self.assertFalse(bv.key_differs(bv.name_key(small("fight_lanturn"), "foe"), bv.name_key(small("switch_popup"), "foe")))

    def test_another_pokemon_gives_another_key(self):
        self.assertTrue(bv.key_differs(bv.name_key(small("fight_ready"), "foe"), bv.name_key(small("fight_lanturn"), "foe")))
        self.assertTrue(bv.key_differs(bv.name_key(small("fight_ready"), "foe"), bv.name_key(small("run2_dim"), "foe")))
        self.assertTrue(bv.key_differs(bv.name_key(small("fight_ready"), "me"), bv.name_key(small("run2_dim"), "me")))

    def test_no_key_yet(self):
        self.assertTrue(bv.key_differs(None, bv.name_key(small("fight_ready"), "foe")))

    def test_same_key_on_the_canvas_and_on_the_small_picture(self):
        a = bv.name_key(frame("fight_ready"), "foe")
        b = bv.name_key(small("fight_ready"), "foe")
        self.assertEqual(a.shape, b.shape)
        self.assertFalse(bv.key_differs(a, b))


def battle_screen(name):
    """The Battle screen with its lowest fifth from tests/fixtures/nav/ (the reward tiles and the big button; the
    rest of the screen, with the player's name and numbers, is left white), on the canvas."""
    strip = cv2.imread(os.path.join(HERE, "fixtures", "nav", name + ".jpg"))
    assert strip is not None, name
    full = np.full((strip.shape[0] * 5, strip.shape[1], 3), 255, np.uint8)
    full[-strip.shape[0]:] = strip
    return cv2.resize(full, (1768, 2208), interpolation=cv2.INTER_CUBIC)


class Buttons(unittest.TestCase):
    """The wide green and orange buttons of the screens around a fight."""

    def test_the_battle_button_is_green(self):
        b = bv.home_button(battle_screen("home_battle"))
        self.assertEqual(b["color"], "green")
        self.assertGreater(b["y1"], 0.97)                         # (it is cut off by the lower edge of the screen)
        self.assertTrue(0.25 < b["x0"] < 0.40 and 0.60 < b["x1"] < 0.78, b)

    def test_a_rank_to_claim_makes_the_button_orange(self):
        b = bv.home_button(battle_screen("home_claim"))
        self.assertEqual(b["color"], "orange")
        self.assertGreater(b["x1"] - b["x0"], 0.7)                # (CLAIM RANK REWARDS! is much wider than BATTLE)
        x, y = bv.button_spot(b, 0.25)
        self.assertTrue(0.2 < x < 0.4 and b["y0"] < y < b["y1"], (x, y))    # on the button, left of the round X

    def test_the_tap_spot_is_on_the_button(self):
        b = {"color": "green", "x0": 0.3, "x1": 0.7, "y0": 0.8, "y1": 0.9}
        self.assertEqual(bv.button_spot(b), (0.5, 0.86))
        self.assertEqual(bv.button_spot(b, 0.25), (0.4, 0.86))

    def test_next_battle_is_a_green_button(self):
        found = bv.wide_buttons(frame("result_loss"))
        self.assertEqual([b["color"] for b in found], ["green"])
        self.assertTrue(found[0]["y0"] < bv.TAP_NEXT[1] < found[0]["y1"], found)
        self.assertIsNone(bv.home_button(frame("result_loss")))   # (it is not at the very bottom)

    def test_a_fight_has_no_such_buttons(self):
        for name in ("fight_ready", "fight_lanturn", "shield_question", "switch_popup", "versus", "minigame_zoom",
                     "banner_over_hud", "no_shields"):
            self.assertEqual(bv.wide_buttons(frame(name)), [], name)
            self.assertIsNone(bv.home_button(frame(name)), name)

    def test_a_background_in_the_colour_of_a_button_is_no_button(self):
        img = np.full((2208, 1768, 3), 255, np.uint8)
        img[1700:1900] = (120, 205, 110)                          # green from edge to edge (BGR)
        self.assertEqual(bv.wide_buttons(img), [])
        img[:] = 255
        img[1700:1850, 400:1400] = (120, 205, 110)                # the same green as a block in the middle
        found = bv.wide_buttons(img)
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found[0]["x0"], 400 / 1768, delta=0.02)
        self.assertAlmostEqual(found[0]["y1"], 1850 / 2208, delta=0.01)

    def test_a_thin_green_line_is_no_button(self):
        img = np.full((2208, 1768, 3), 255, np.uint8)
        img[1500:1526, 300:800] = (120, 205, 110)                 # an HP bar is this thin
        self.assertEqual(bv.wide_buttons(img), [])

    def test_buttons_come_lowest_first(self):
        img = np.full((2208, 1768, 3), 255, np.uint8)
        img[1300:1420, 400:1400] = (120, 205, 110)
        img[1800:1920, 400:1400] = (85, 180, 255)                 # orange (BGR)
        self.assertEqual([b["color"] for b in bv.wide_buttons(img)], ["orange", "green"])


class Rings(unittest.TestCase):
    def test_the_fast_ring_test_gives_what_the_plain_one_gives(self):
        import numpy as np
        rng = np.random.RandomState(3)
        for size in ((880, 704), (2208, 1768)):
            img = (rng.rand(size[0], size[1], 3) * 255).astype(np.uint8)
            img[rng.rand(size[0], size[1]) > 0.6] = 255
            h, w = img.shape[:2]
            for cx, cy in ((bv.BTN_X[0] * w, bv.BTN_Y * h), (bv.COUNT_CENTER[0] * w, bv.COUNT_CENTER[1] * h), (5.0, 7.0)):
                radii = np.arange(0.080, 0.112, 0.004) * w
                plain = max(bv._ring_fraction(img, cx, cy, r - 0.004 * w, r + 0.004 * w) for r in radii)
                self.assertAlmostEqual(bv._ring_best(img, cx, cy, radii, 0.004 * w), plain, places=9)
                self.assertAlmostEqual(bv._ring_best(img, cx, cy, radii, 0.004 * w), plain, places=9)   # (from the cache)

    def test_features_are_the_same_on_the_small_picture(self):
        # the fight loop reads the small picture (six times as fast): it must tell the same story as the canvas
        for name in ("fight_ready", "fight_lanturn", "shield_question", "run2_shield_question", "switch_popup",
                     "no_shields", "result_loss", "versus", "run2_both_lit", "run2_right_lit", "run2_dim"):
            a, b = bv.features(frame(name)), bv.features(small(name))
            for key in ("white", "versus", "hud", "ring", "result", "hex", "shields"):
                self.assertEqual(a[key], b[key], (name, key))
            self.assertEqual(tuple(a["ready"]), tuple(b["ready"]), name)
            self.assertEqual(bf.state(a), bf.state(b), name)


if __name__ == "__main__":
    unittest.main()
