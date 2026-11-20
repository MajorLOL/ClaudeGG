"""Unit tests for battle_nav (reading the GO Battle League screens).  Run:  python3 -m unittest discover -s tests

The OCR lines in tests/fixtures/battle_screens.json were read from real screenshots of Pokémon GO
(main menu, Battle screen, party screen, 'Exit the Trainer Battle?', a Pokémon's detail page)."""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import battle_nav as bn  # noqa: E402

with open(os.path.join(HERE, "fixtures", "battle_screens.json"), encoding="utf-8") as f:
    SCREENS = json.load(f)


def line(text, x, y):
    """One OCR line the way gamebot.ocr_lines() gives it."""
    words = text.split()
    return (text, x, y, [(w, x + 60 * i, y) for i, w in enumerate(words)])


class ScreenKind(unittest.TestCase):
    def test_real_screens(self):
        for name, kind in (("menu", "menu"), ("home", "home"), ("party", "party"),
                           ("exit_battle", "exit_battle"), ("pokemon_detail", "other")):
            self.assertEqual(bn.screen_kind(SCREENS[name]), kind, name)

    def test_map_comes_from_the_picture(self):
        self.assertEqual(bn.screen_kind([], on_map=True), "map")

    def test_nothing_read_is_other(self):
        self.assertEqual(bn.screen_kind([]), "other")

    def test_party_wins_over_the_league_name(self):
        self.assertEqual(bn.screen_kind(SCREENS["party"], league="Great League"), "party")

    def test_league_list(self):
        lines = [line("SELECT A LEAGUE", 600, 300), line("GREAT LEAGUE", 600, 800),
                 line("ULTRA LEAGUE", 600, 1200)]
        self.assertEqual(bn.screen_kind(lines, league="Great League"), "league")
        self.assertEqual(bn.screen_kind(lines, league=""), "other")

    def test_league_list_by_its_title_even_when_the_wanted_league_is_not_on_it(self):
        self.assertEqual(bn.screen_kind(SCREENS["league_list"], league="Rocket League"), "league")
        self.assertEqual(bn.screen_kind(SCREENS["league_list"]), "league")

    def test_exit_pokemon_go_question(self):
        lines = [line("DO YOU WANT TO EXIT POKEMON GO?", 600, 900), line("CANCEL", 600, 1100)]
        self.assertEqual(bn.screen_kind(lines), "exit")

    def test_menu_with_most_tile_names_read(self):
        lines = [line("SETTINGS", 1400, 300), line("POKEDEX BATTLE", 500, 700), line("SHOP", 900, 1100)]
        self.assertEqual(bn.screen_kind(lines), "menu")

    def test_misread_words_still_count(self):
        lines = [line("USE THIS PARTV", 880, 1940)]
        self.assertEqual(bn.screen_kind(lines), "party")


class Spots(unittest.TestCase):
    def test_menu_tile_is_below_its_label(self):
        spots = bn.menu_battle_spots(SCREENS["menu"])
        self.assertEqual(spots[0][0], spots[1][0])
        self.assertEqual(spots[0][1] - spots[1][1], bn.ICON_DY)
        self.assertEqual(len(spots), 3)

    def test_menu_spots_scale_with_the_screen(self):
        full = bn.menu_battle_spots(SCREENS["menu"], 1.0)
        half = bn.menu_battle_spots([(t, x // 2, y // 2, [(w, wx // 2, wy // 2) for w, wx, wy in ws])
                                     for t, x, y, ws in SCREENS["menu"]], 0.5)
        for (x1, y1), (x2, y2) in zip(full, half):
            self.assertAlmostEqual(x1 / 2, x2, delta=3)
            self.assertAlmostEqual(y1 / 2, y2, delta=3)

    def test_menu_without_the_label_has_no_spots(self):
        self.assertEqual(bn.menu_battle_spots([line("SETTINGS", 1400, 300)]), [])

    def test_battle_word_in_the_left_column_is_not_the_tile(self):
        self.assertEqual(bn.menu_battle_spots([line("BATTLE", 300, 700)]), [])

    def test_home_button_falls_back_to_fixed_spots(self):
        spots = bn.home_battle_spots(SCREENS["home"])
        self.assertEqual(spots[-2:], bn.HOME_BUTTON_FALLBACK)

    def test_home_button_label_is_tried_first(self):
        lines = SCREENS["home"] + [line("BATTLE", 932, 2196)]
        spots = bn.home_battle_spots(lines)
        self.assertEqual(spots[0], (932, 2196))
        self.assertEqual(len(spots), 4)

    def test_home_tab_and_title_are_not_the_button(self):
        lines = [line("BATTLE", 530, 141), line("GO BATTLE LEAGUE", 904, 1283)]
        self.assertEqual(bn.home_battle_spots(lines), bn.HOME_BUTTON_FALLBACK)

    def test_home_spots_scale_with_the_screen(self):
        spots = bn.home_battle_spots([], 0.5)
        self.assertEqual(spots, [(325, 1082), (560, 1082)])


class League(unittest.TestCase):
    def test_words(self):
        self.assertEqual(bn.league_words("Great League"), ["GREAT", "LEAGUE"])
        self.assertEqual(bn.league_words(""), [])

    def test_finds_the_chosen_league_only(self):
        hits = bn.league_lines(SCREENS["party"], "Great League")
        self.assertEqual(len(hits), 1)
        self.assertIn("GREAT LEAGUE", hits[0][0])
        self.assertEqual(bn.league_lines(SCREENS["party"], "Ultra League"), [])

    def test_empty_name_finds_nothing(self):
        self.assertEqual(bn.league_lines(SCREENS["party"], ""), [])


class LeagueList(unittest.TestCase):
    """The 'CHOOSE YOUR LEAGUE' screen (read from a screen recording of the phone)."""

    def test_is_a_league_screen_for_the_chosen_league(self):
        self.assertEqual(bn.screen_kind(SCREENS["league_list"], league="Great League"), "league")

    def test_missing_league_is_not_found(self):
        self.assertEqual(bn.league_lines(SCREENS["league_list"], "Rocket League"), [])

    def test_great_league_is_the_edition_tile_not_ultra_or_master(self):
        hits = bn.league_lines(SCREENS["league_list"], "Great League")
        self.assertEqual(len(hits), 1)
        self.assertIn("GREAT LEAGUE EDITION", hits[0][0])
        self.assertGreater(hits[0][2], 1600)                  # the third tile, low on the screen

    def test_ultra_league_tile(self):
        hits = bn.league_lines(SCREENS["league_list"], "Ultra League")
        self.assertEqual(len(hits), 1)
        self.assertLess(hits[0][2], 1100)                     # the first tile


class ExitTrainerBattle(unittest.TestCase):
    """'Exit the Trainer Battle?': YES is white on green and not read by OCR, NO is."""

    def test_both_screenshots_are_recognised(self):
        self.assertEqual(bn.screen_kind(SCREENS["exit_battle_video"]), "exit_battle")
        self.assertEqual(bn.screen_kind(SCREENS["exit_battle_video"], league="Great League"), "exit_battle")

    def test_yes_is_above_no(self):
        spots = bn.exit_battle_spots(SCREENS["exit_battle_video"])
        no = spots["no"]
        self.assertEqual(no, (883, 1403))
        # on the recording the YES button is centred at y 1115 (50% of the screen height)
        self.assertEqual(spots["yes"][0], 883)
        self.assertAlmostEqual(spots["yes"][1], 1115, delta=60)

    def test_yes_from_the_question_when_no_is_not_read(self):
        lines = [l for l in SCREENS["exit_battle_video"] if l[0] != "NO"]
        spots = bn.exit_battle_spots(lines)
        self.assertIsNone(spots["no"])
        self.assertAlmostEqual(spots["yes"][1], 1115, delta=60)

    def test_fixed_spot_when_nothing_is_read(self):
        spots = bn.exit_battle_spots([])
        self.assertEqual(spots["yes"], bn.EXIT_YES_FALLBACK)
        self.assertIsNone(spots["no"])

    def test_spots_scale_with_the_screen(self):
        full = bn.exit_battle_spots(SCREENS["exit_battle_video"])
        half = bn.exit_battle_spots([(t, x // 2, y // 2, [(w, wx // 2, wy // 2) for w, wx, wy in ws])
                                     for t, x, y, ws in SCREENS["exit_battle_video"]], 0.5)
        self.assertAlmostEqual(full["yes"][1] / 2, half["yes"][1], delta=3)

    def test_the_two_buttons_do_not_overlap(self):
        spots = bn.exit_battle_spots(SCREENS["exit_battle"])
        self.assertGreater(spots["no"][1] - spots["yes"][1], 200)


class PartyScreen(unittest.TestCase):
    def test_title(self):
        self.assertIn("GREAT LEAGUE", bn.party_title(SCREENS["party"]))

    def test_title_missing(self):
        self.assertEqual(bn.party_title([line("CHOOSE YOUR PARTY", 800, 900)]), "")

    def test_members_seen(self):
        self.assertEqual(bn.party_members(SCREENS["party"], ["Noctowl", "Lanturn", "Azumarill"]),
                         ["Noctowl", "Lanturn"])

    def test_members_with_a_two_word_name(self):
        lines = [line("MR MIME NOCTOWL", 500, 1500)]
        self.assertEqual(bn.party_members(lines, ["Mr. Mime", "Noctowl"]), ["Mr. Mime", "Noctowl"])


if __name__ == "__main__":
    unittest.main()
