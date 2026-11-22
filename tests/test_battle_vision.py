"""Unit tests for battle_vision (reading the picture of a GO Battle League fight).

The pictures in tests/fixtures/fight/ are frames of real fights that were recorded with the recorder of the web
interface (35 % of the 1768 x 2208 canvas): one fight in an arena by night and one in an arena by day (day_*).
By day the sky is full of white clouds - exactly where the name boxes and the countdown are - and that fight
went wrong in many ways: the bot saw name boxes in the clouds, lit buttons in every flash and no countdown at
all on the switch question.  The tests bring the pictures back to the full canvas, as the bot does with every
screenshot.   Run:  python3 -m unittest discover -s tests"""
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
        # by night the disc of the countdown is dark blue, by day it is grey over white clouds (it is
        # see-through): 5, 5 and 11 seconds left at night; 5, 1, 11 and 3 seconds left by day
        for name in ("shield_question", "switch_popup", "no_shields",
                     "day_shield", "day_no_shields", "day_switch", "day_switch_late"):
            f = bv.features(frame(name))
            self.assertTrue(f["ring"], name)
            self.assertEqual(bf.state(f), "prompt", name)

    def test_the_countdown_tells_the_switch_question_from_the_others(self):
        """The countdown of the switch question sits a little lower (between the name boxes) and is a little
        bigger: no text has to be read to know that our Pokémon fainted."""
        for name in ("switch_popup", "day_switch", "day_switch_late"):
            self.assertEqual(bv.countdown_kind(frame(name)), "switch", name)
            self.assertEqual(bv.countdown_kind(small(name)), "switch", name)
        for name in ("shield_question", "no_shields", "day_shield", "day_no_shields"):
            self.assertEqual(bv.countdown_kind(frame(name)), "attack", name)
            self.assertEqual(bv.countdown_kind(small(name)), "attack", name)
        self.assertEqual(bv.features(frame("day_switch"))["count"], "switch")
        self.assertEqual(bv.features(frame("day_dim"))["count"], "")

    def test_no_countdown_without_a_question(self):
        """Clouds are white and round, banners are grey with white text: none of them is a countdown."""
        for name in ("day_intro", "day_start", "day_dim", "day_lit", "day_lines", "day_flash", "day_faint",
                     "day_minigame", "day_banner", "day_get_ready", "day_result", "fight_ready", "fight_lanturn",
                     "minigame_zoom", "banner_over_hud", "result_loss", "versus"):
            self.assertFalse(bv.features(frame(name))["ring"], name)

    def test_a_white_screen_is_no_countdown(self):
        self.assertFalse(bv.countdown_ring(np.full((2208, 1768, 3), 255, np.uint8)))
        self.assertFalse(bv.countdown_ring(np.zeros((2208, 1768, 3), np.uint8)))
        self.assertFalse(bv.countdown_ring(np.full((2208, 1768, 3), 128, np.uint8)))

    def test_the_arc_of_the_countdown_is_what_counts(self):
        """A grey disc with a white number but without the white arc (the time is up) is no question any more;
        with the last piece of the arc it is."""
        img = np.full((2208, 1768, 3), (250, 235, 215), np.uint8)             # a pale sky
        cx, cy, r = [int(round(v)) for v in (bv.COUNT_DISCS[0][0] * 1768, bv.COUNT_DISCS[0][1] * 2208,
                                             bv.COUNT_DISCS[0][2] * 1768)]
        cv2.circle(img, (cx, cy), int(0.087 * 1768), (135, 130, 128), -1)     # the disc
        cv2.putText(img, "1", (cx - 30, cy + 45), cv2.FONT_HERSHEY_SIMPLEX, 4.0, (255, 255, 255), 14)
        self.assertFalse(bv.countdown_ring(img))
        cv2.ellipse(img, (cx, cy), (r, r), 0, 225, 270, (255, 255, 255), 12)   # the last eighth, left of the top
        self.assertTrue(bv.countdown_ring(img))

    def test_a_lit_button_has_a_white_label_and_a_white_ring(self):
        """By day: Lanturn with Surf (a blue button) and Thunderbolt both ready, and the same fight a little
        earlier with nothing ready."""
        lit = bv.features(frame("day_lit"))
        self.assertEqual(bf.state(lit), "fight")
        self.assertEqual(tuple(lit["ready"]), (True, True))
        dim = bv.features(frame("day_dim"))
        self.assertEqual(bf.state(dim), "fight")
        self.assertEqual(tuple(dim["ready"]), (False, False))

    def test_one_sign_alone_does_not_light_a_button(self):
        """What made the bot throw charged attacks that were not there (at least seven times in one fight):
        day_intro   'Go, Noctowl!': the white Poké Ball of the intro lies in the label zone
        day_lines   'Go, Garchomp!': the white lines of the field run through both label zones
        day_flash   the flash of an Ice Beam: white where the rings are
        day_faint   the glitter of a Pokémon that faints, right where the left button was
        and the pictures of a charged attack of our own (no buttons on them at all)."""
        for name in ("day_intro", "day_lines", "day_flash", "day_faint", "day_start", "day_get_ready",
                     "day_minigame", "day_banner", "day_switch", "day_shield", "day_result", "minigame_zoom"):
            f = bv.features(frame(name))
            self.assertEqual(tuple(f["ready"]), (False, False), name)
            self.assertEqual(bv.charge_ready(frame(name)), (False, False), name)    # (also without the name boxes)

    def test_a_recording_of_the_pc_screen_is_not_what_the_bot_sees(self):
        # (run2_*: a window on the PC that was filmed, with a border: the buttons are not at their places, so
        # nothing is taken for lit - these pictures are only used for the texts in the name boxes)
        for name in ("run2_dim", "run2_right_lit", "run2_both_lit"):
            self.assertEqual(tuple(bv.features(frame(name))["ready"]), (False, False), name)

    def test_shield_question_is_known_by_its_picture(self):
        """The big lilac shield tells the shield question from the switch question without reading any text."""
        for name in ("shield_question", "day_shield"):
            f = bv.features(frame(name))
            self.assertTrue(f["hex"], name)
            self.assertEqual(bf.state(f), "prompt", name)
        self.assertTrue(bv.features(frame("run2_shield_question"))["hex"])
        for name in ("switch_popup", "no_shields", "fight_ready", "fight_lanturn", "run2_both_lit", "versus",
                     "day_switch", "day_switch_late", "day_no_shields", "day_lit", "day_dim", "day_result"):
            self.assertFalse(bv.features(frame(name))["hex"], name)

    def test_charged_attack_game_has_no_hp_bars(self):
        """The camera zooms in on the attacker: lightning bolts and sparks are not HP bars."""
        f = bv.features(frame("minigame_zoom"))
        self.assertEqual(f["hp"], (None, None))
        self.assertEqual(tuple(f["ready"]), (False, False))

    def test_banner_over_the_name_boxes(self):
        for name in ("banner_over_hud", "day_banner"):
            f = bv.features(frame(name))
            self.assertTrue(f["hud"], name)
            self.assertEqual(tuple(f["ready"]), (False, False), name)   # (the buttons are hidden meanwhile)

    def test_name_boxes_are_known_by_their_poke_balls(self):
        """By day the sky behind the name boxes is as pale as the boxes are: the intro of the fight, the flash
        of an attack, a Pokémon that faints and the result screen all show clouds where the boxes would be."""
        for name in ("day_start", "day_dim", "day_lit", "day_lines", "day_minigame", "day_get_ready", "day_switch",
                     "day_switch_late", "fight_ready", "fight_lanturn", "switch_popup", "minigame_zoom"):
            self.assertTrue(bv.features(frame(name))["hud"], name)
        for name in ("day_intro", "day_flash", "day_faint", "day_result", "day_shield", "day_no_shields",
                     "shield_question", "no_shields", "result_loss", "versus"):
            self.assertFalse(bv.features(frame(name))["hud"], name)
        self.assertFalse(bv.hud_visible(np.full((2208, 1768, 3), 255, np.uint8)))      # (a white screen)
        self.assertFalse(bv.hud_visible(np.zeros((2208, 1768, 3), np.uint8)))          # (a black one)

    def test_shield_icons_left_used_and_not_seen(self):
        self.assertEqual(bv.shield_icon_slots(frame("day_start")), {"me": 2, "foe": 2})
        self.assertEqual(bv.shield_icon_slots(frame("day_dim")), {"me": 0, "foe": 0})       # all four are used
        self.assertEqual(bv.shield_icon_slots(frame("fight_ready")), {"me": 1, "foe": 2})
        self.assertEqual(bv.shield_icon_slots(frame("day_minigame")), {"me": 2, "foe": 2})  # (the camera on ours)
        # a banner over the name boxes, or no name boxes at all: not seen, which is not "none left"
        for name in ("day_banner", "banner_over_hud", "day_shield", "day_intro", "day_result", "day_flash"):
            self.assertEqual(bv.shield_icon_slots(frame(name)), {"me": None, "foe": None}, name)
            self.assertEqual(bv.shield_icon_slots(small(name)), {"me": None, "foe": None}, name)

    def test_poke_balls_red_and_grey(self):
        self.assertEqual(bv.ball_slots(frame("day_start")), {"me": (3, 0), "foe": (3, 0)})
        self.assertEqual(bv.ball_slots(frame("day_lit")), {"me": (1, 2), "foe": (2, 1)})     # two of ours are down
        self.assertEqual(bv.ball_slots(frame("fight_ready")), {"me": (3, 0), "foe": (3, 0)})
        self.assertEqual(bv.ball_slots(frame("day_result")), {"me": (0, 0), "foe": (0, 0)})

    def test_the_fight_before_it_starts_is_no_fight(self):
        # 'Go, Noctowl!' was taken for the fight (name boxes in the clouds) with a lit button (the Poké Ball):
        # the bot threw a charged attack before the countdown 3-2-1 had even begun
        self.assertEqual(bf.state(bv.features(frame("day_intro"))), "other")
        self.assertEqual(bf.state(bv.features(frame("day_start"))), "fight")           # (GO!)

    def test_result_screen(self):
        for name in ("result_loss", "day_result"):
            f = bv.features(frame(name))
            self.assertTrue(f["result"], name)
            self.assertFalse(f["hud"], name)
            self.assertEqual(bf.state(f), "result", name)

    def test_fight_pictures_are_no_results(self):
        for name in ("fight_ready", "fight_lanturn", "shield_question", "switch_popup", "no_shields",
                     "minigame_zoom", "banner_over_hud", "versus", "day_intro", "day_start", "day_dim", "day_lit",
                     "day_lines", "day_flash", "day_faint", "day_shield", "day_no_shields", "day_switch",
                     "day_minigame", "day_banner", "day_get_ready"):
            self.assertFalse(bv.features(frame(name))["result"], name)

    def test_green_from_edge_to_edge_is_no_result(self):
        """The map and the grass of an arena by day are green where NEXT BATTLE would be."""
        green = (160, 205, 100)                                   # the green of NEXT BATTLE (BGR)
        img = np.full((2208, 1768, 3), 255, np.uint8)
        img[1700:2100] = green                                    # green over the whole width
        self.assertFalse(bv.result_button(img))
        img[1700:2100, :300] = 255                                # ... also with something else at the sides
        img[1700:2100, 1450:] = 255                               # (the buttons of the map): no pill
        self.assertFalse(bv.result_button(img))
        img[:] = (60, 90, 40)
        cv2.rectangle(img, (560, 1835), (1200, 1975), green, -1)  # a green pill around TAP_NEXT
        self.assertTrue(bv.result_button(img))
        img[:] = (60, 90, 40)
        cv2.rectangle(img, (560, 1300), (1200, 1440), green, -1)  # the same pill higher up is another button
        self.assertFalse(bv.result_button(img))

    def test_no_hp_bars_while_a_charged_attack_of_ours_runs(self):
        """The camera is on the attacker from 'Get Ready!' until the attack is over and no HP bar is shown:
        that tells the fight loop whether a charged attack really started."""
        for name in ("day_get_ready", "day_minigame", "minigame_zoom"):
            self.assertEqual(bv.features(frame(name))["hp"], (None, None), name)
        for name in ("day_dim", "day_lit", "day_start", "fight_ready", "fight_lanturn"):
            mine, foe = bv.features(frame(name))["hp"]
            self.assertTrue(mine is not None and foe is not None, name)
        mine, foe = bv.features(frame("day_dim"))["hp"]
        self.assertAlmostEqual(mine, 0.22, delta=0.04)
        self.assertAlmostEqual(foe, 0.93, delta=0.04)


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
        cut = {"color": "green", "x0": 0.3, "x1": 0.7, "y0": 0.97, "y1": 1.0}      # cut off by the edge of the screen
        self.assertLessEqual(bv.button_spot(cut)[1], 0.981)                       # (not on the very edge)
        self.assertGreater(bv.button_spot(cut)[1], 0.97)

    def test_no_button_in_view_when_a_new_set_starts(self):
        # 'Choose a reward tier ...': the card is longer, only a sliver of the BATTLE button is above the edge
        img = battle_screen("home_newset")
        self.assertEqual(bv.wide_buttons(img), [])
        self.assertIsNone(bv.home_button(img))

    def test_of_two_battle_buttons_the_upper_one(self):
        # scrolled down: BATTLE of the basic rewards, and below it BATTLE of the premium rewards (costs a pass)
        img = np.full((2208, 1768, 3), 255, np.uint8)
        img[1300:1410, 560:1260] = (120, 205, 110)
        img[1950:2060, 560:1260] = (120, 205, 110)
        b = bv.home_button(img)
        self.assertEqual(b["color"], "green")
        self.assertAlmostEqual(b["y0"], 1300 / 2208, delta=0.01)
        img[1950:2060, 300:1500] = (85, 180, 255)                 # (an orange one anywhere goes first: claim)
        self.assertEqual(bv.home_button(img)["color"], "orange")

    def test_next_battle_is_a_green_button(self):
        found = bv.wide_buttons(frame("result_loss"))
        self.assertEqual([b["color"] for b in found], ["green"])
        self.assertTrue(found[0]["y0"] < bv.TAP_NEXT[1] < found[0]["y1"], found)

    def test_lets_go_of_the_welcome_popup(self):
        found = bv.wide_buttons(battle_screen("welcome"))
        self.assertEqual([b["color"] for b in found], ["green"])
        x, y = bv.button_spot(found[0])
        self.assertAlmostEqual(x, 0.5, delta=0.03)
        self.assertTrue(0.88 < y < 0.95, y)

    def test_a_button_whose_label_rows_fall_out_is_still_one_button(self):
        img = np.full((2208, 1768, 3), 255, np.uint8)
        img[1700:1850, 400:1400] = (120, 205, 110)
        for x in range(520, 1280, 26):                            # thick white letters right across the middle rows
            img[1755:1795, x:x + 14] = 255
        found = bv.wide_buttons(img)
        self.assertEqual(len(found), 1, found)
        self.assertAlmostEqual(found[0]["y0"], 1700 / 2208, delta=0.01)
        self.assertAlmostEqual(found[0]["y1"], 1850 / 2208, delta=0.01)

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
                     "no_shields", "result_loss", "versus", "run2_both_lit", "run2_right_lit", "run2_dim",
                     "day_intro", "day_start", "day_dim", "day_lit", "day_lines", "day_flash", "day_faint",
                     "day_shield", "day_no_shields", "day_switch", "day_switch_late", "day_minigame", "day_banner",
                     "day_result", "day_get_ready"):
            a, b = bv.features(frame(name)), bv.features(small(name))
            for key in ("white", "versus", "hud", "ring", "result", "hex", "shields"):
                self.assertEqual(a[key], b[key], (name, key))
            self.assertEqual(tuple(a["ready"]), tuple(b["ready"]), name)
            self.assertEqual(bf.state(a), bf.state(b), name)


if __name__ == "__main__":
    unittest.main()
