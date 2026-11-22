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


with open(os.path.join(HERE, "fixtures", "fight", "ocr.json"), encoding="utf-8") as f:
    FIGHT = json.load(f)


class FightQuestions(unittest.TestCase):
    """OCR lines of the question strip of a real fight (tests/fixtures/fight/ocr.json)."""

    def test_shield_question(self):
        for key in ("question_15", "question_34", "question_71"):
            self.assertEqual(bn.question_kind(FIGHT[key]), "shield", key)

    def test_no_shields_remaining(self):
        for key in ("question_101", "question_125"):
            self.assertEqual(bn.question_kind(FIGHT[key]), "noshield", key)

    def test_switch_question(self):
        self.assertEqual(bn.question_kind(FIGHT["question_65"]), "switch")

    def test_unreadable_is_not_guessed(self):
        self.assertEqual(bn.question_kind(FIGHT["question_91"]), "")
        self.assertEqual(bn.question_kind([]), "")

    def test_misread_words(self):
        for text, kind in (("ATTACK INCOMING! USE APROTECT SHIELD?", "shield"), ("ATTACK INCOMING! USE SHIELD?", "shield"),
                           ("SWITCH IN A NEW POKEMON?", "switch"), ("NO PROT€ET SHIELDS REMAINING!", "noshield"),
                           ("NO FEMAINING!", "noshield"), ("SHIELDS", "noshield")):
            self.assertEqual(bn.question_kind([line(text, 100, 100)]), kind, text)


class FightBoxes(unittest.TestCase):
    def test_name_boxes(self):
        self.assertEqual(bn.name_box(FIGHT["name_me_41"]), ("Noctowl", 1497))
        self.assertEqual(bn.name_box(FIGHT["name_foe_41"]), ("Cramorant", 1493))
        self.assertEqual(bn.name_box(FIGHT["name_foe_55"]), ("Beedrill", 1483))
        self.assertEqual(bn.name_box(FIGHT["name_me_79"]), ("Lanturn", 1494))

    def test_name_box_nothing_read(self):
        self.assertEqual(bn.name_box([]), ("", None))

    def test_popup_tiles(self):
        tiles = bn.popup_tiles(FIGHT["popup_cp_65"])          # ('CP1489 CPE1494': the small CP is misread)
        self.assertEqual([cp for cp, _x in tiles], [1489, 1494])
        self.assertLess(tiles[0][1], 884)                     # the left tile and the right one
        self.assertGreater(tiles[1][1], 884)
        self.assertEqual(bn.popup_tiles([line("LAPRAS", 560, 1890), line("12", 900, 1400), line("C1494", 1195, 1428)]),
                         [(1494, 1195)])                      # (a name or a short number is no CP)
        self.assertEqual(bn.popup_tiles([line("CP1489", 570, 1428), line("CP1494", 1195, 1428)]),
                         [(1489, 570 + 0), (1494, 1195 + 0)])

    def test_button_texts(self):
        self.assertEqual(bn.button_texts(FIGHT["buttons_41"], 1768), ("SHADOW BALL", "SKY ATTACK"))
        left, right = bn.button_texts(FIGHT["buttons_113"], 1768)      # (a hint 'Not very effective' stands in it)
        self.assertIn("FRUSTRATION", left)
        self.assertIn("SURF", right)
        left, right = bn.button_texts([line("SHADOW BALL", 540, 2040), line("SKY ATTACK", 1220, 2040)], 1768)
        self.assertEqual((left, right), ("SHADOW BALL", "SKY ATTACK"))

    def test_result(self):
        self.assertEqual(bn.result_kind(FIGHT["result_137"]), "loss")
        self.assertEqual(bn.result_kind(FIGHT["result_136"]), "loss")
        self.assertEqual(bn.result_kind(FIGHT["result_135"]), "loss")       # ('GOOD' only: the rest is still coming)
        self.assertEqual(bn.result_kind([line("VICTORY!", 800, 600)]), "win")
        self.assertEqual(bn.result_kind(SCREENS["home"]), "")               # (the Battle screen says 'WINS: 100')

    def test_you_win(self):
        """The result of a battle that was won says 'YOU WIN!' in big white letters over the trainer; the text
        reader does not always give them in one piece (what it made of seven pictures of that screen)."""
        for text in ("YOU WIN!", "IM HE F HY, UE YOU. WIN!", "LS , YOU W IN", "AK = RE YOU WIN",
                     "AIE A AKE: AON YOU W IN", "AE 3 YOU WIN!", "YOUWIN!"):
            self.assertEqual(bn.result_kind([line(text, 500, 1100)]), "win", text)
        for text in ("V OF, FN A, >", "HE: AY = > YOU A", "WIN 30 TRAINER BATTLES IN THE", "4 RESEARCH TASKS UPDATED",
                     "BATTLE IN THE GO BATTLE LEAGUE 60"):
            self.assertEqual(bn.result_kind([line(text, 500, 1100)]), "", text)
        # a line of the research on the screen of a battle that was lost does not turn it into a win
        self.assertEqual(bn.result_kind([line("GOOD EFFORT!", 600, 1000), line("WIN 30 TRAINER BATTLES", 500, 1700)]),
                         "loss")
        self.assertEqual(bn.result_kind([line("YOU", 700, 1100), line("WIN 30 TRAINER BATTLES", 500, 1700)]), "")


class Claims(unittest.TestCase):
    """A new rank has to be claimed before the next battle: the button of the Battle screen says so."""

    def test_the_claim_button_by_its_text(self):
        lines = SCREENS["home"] + [line("CLAIM RANK REWARDS!", 500, 2100)]
        self.assertEqual(bn.claim_label(lines), "CLAIM RANK REWARDS!")
        self.assertEqual(bn.claim_label(SCREENS["home"]), "")
        self.assertEqual(bn.claim_label([line("CLAIM REWARDS", 600, 900)]), "")     # (not the button at the bottom)
        self.assertEqual(bn.claim_label([line("CLAlM RANK REWARDS!", 500, 1050)], 0.5), "CLAlM RANK REWARDS!")

    def test_words_that_take_a_reward_screen_further(self):
        lines = [line("RANK UP!", 700, 500), line("REWARDS", 700, 1100), line("OK", 860, 1900), line("CLAIM!", 800, 1500)]
        self.assertEqual([w for w, _x, _y in bn.next_words(lines)], ["OK", "CLAIM!"])        # lowest first
        self.assertEqual(bn.next_words([line("OK", 860, 300)]), [])                           # (not at the top)
        self.assertEqual(bn.next_words([line("LOOK BOOKS TOKEN", 300, 1500)]), [])            # (no part of a word)
        self.assertEqual([w for w, _x, _y in bn.next_words([line("CONTlNUE", 700, 1800)])], ["CONTlNUE"])

    def test_the_battle_screen_scrolled_down(self):
        # a new set starts: the page is scrolled down to its BATTLE button and the lines at the top are gone
        lines = [line("2026 GO LAIC CUP: GREAT LEAGUE EDITION", 500, 300),
                 line("CHOOSE A REWARD TIER TO ENTER THE GO BATTLE LEAGUE.", 300, 420), line("PREMIUM REWARDS", 650, 1700)]
        self.assertEqual(bn.screen_kind(lines, league="Great League"), "home")       # (not the league list)
        self.assertEqual(bn.screen_kind([line("BASIC REWARDS", 650, 900)], league="Great League"), "home")
        self.assertEqual(bn.screen_kind([line("2026 GO LAIC CUP: GREAT LEAGUE EDITION", 500, 300)],
                                        league="Great League"), "league")

    def test_a_battle_button_under_premium_rewards(self):
        lines = [line("BASIC REWARDS", 650, 400), line("PREMlUM REWARDS", 650, 1500)]
        self.assertFalse(bn.premium_above(lines, 1300))                   # the button of the basic rewards
        self.assertTrue(bn.premium_above(lines, 1900))                    # the one below PREMIUM REWARDS
        self.assertFalse(bn.premium_above([], 1900))

    def test_the_welcome_of_a_new_season(self):
        lines = [line("WELCOME TO THE GO BATTLE", 567, 1531), line("RISE THROUGH THE RANKS AND COMPETE WORLDWIDE FOR", 364, 1731),
                 line("REWARDS AND GLORY", 766, 1798)]                      # (read from the real pop-up)
        self.assertEqual(bn.screen_kind(lines, league="Great League"), "welcome")
        self.assertEqual(bn.screen_kind([line("WELCOME TO THE GO BATTLE LEAGUE", 500, 1531)]), "welcome")    # (not 'home')
        self.assertEqual(bn.screen_kind([line("RlSE THROUGH THE RANKS AND COMPETE", 364, 1731)]), "welcome")
        self.assertEqual(bn.screen_kind(SCREENS["home"]), "home")
        self.assertEqual(bn.danger_words(lines), [])

    def test_labels_of_buttons_that_only_go_on(self):
        for text in ("LET'S GO!", "LETV'S GO!", "LET S GOI", "OK", "CONTlNUE", "NEXT BATTLE", "CLAIM REWARD!", "GOT IT!"):
            self.assertTrue(bn.go_on_label(text), text)
        for text in ("BATTLE", "USE THIS PARTY", "YES", "JOIN GROUP", "BUY", "GO", "", "0K", "NAWRTPTISA"):
            self.assertFalse(bn.go_on_label(text), text)

    def test_labels_that_are_never_tapped_blindly(self):
        for text in ("USE THIS PARTY", "YES", "JOIN GROUP", "BUY 100 COINS", "SHOP", "EXIT", "USE PREMIUM PASS"):
            self.assertTrue(bn.keep_off_label(text), text)
        for text in ("LET'S GO!", "OK", "NEXT BATTLE", "CLAIM REWARD!", "", "NAWRTPTISA", "BATTLE"):
            self.assertFalse(bn.keep_off_label(text), text)

    def test_words_that_keep_the_bot_from_tapping(self):
        self.assertEqual(bn.danger_words([line("BATTLE NOW FOR 100 POKECOINS? SHOP", 300, 900)]), ["POKECOINS", "SHOP"])
        self.assertEqual(bn.danger_words([line("USE A PREMIUM BATTLE PASS", 300, 900)]), ["PREMIUM", "PASS"])
        self.assertEqual(bn.danger_words(SCREENS["party"]), [])

    def test_words_of_the_battle_screens(self):
        self.assertTrue(bn.battle_words(SCREENS["home"]))
        self.assertTrue(bn.battle_words([line("RANK UP!", 700, 500)]))
        self.assertFalse(bn.battle_words([line("VENIPEDE CP 378", 600, 400)]))
        self.assertFalse(bn.battle_words([]))


class PartyButton(unittest.TestCase):
    def test_use_this_party_spots(self):
        spots = bn.party_use_spots([line("USE THIS PARTY", 700, 1930)])
        self.assertEqual(spots[0], (884, 1930))
        self.assertEqual(bn.party_use_spots(SCREENS["party"]), [(884, 1930)])     # (label misread: fixed spot)

    def test_spots_scale(self):
        self.assertEqual(bn.party_use_spots([], 0.5), [(442, 965)])


if __name__ == "__main__":
    unittest.main()
