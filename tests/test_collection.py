"""Your Pokémon and the teams (collection.py), the leagues on the league list (battle_nav.read_leagues) and the
appraisal bars (gamebot._bars, on a drawn panel like the one of 24 November).  PvPoke's data is replaced by a few
rows here.  Run: python3 -m unittest discover -s tests"""
import os
import sys
import tempfile
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import battle_nav as BN  # noqa: E402
import collection as C  # noqa: E402

try:
    import cv2
    import gamebot as G
except Exception:  # noqa: BLE001
    G = None

TABLE = C.species_table([
    {"speciesId": "cetoddle", "speciesName": "Cetoddle", "baseStats": {"atk": 119, "def": 80, "hp": 239},
     "types": ["ice", "none"], "family": {"evolutions": ["cetitan"]}},
    {"speciesId": "cetitan", "speciesName": "Cetitan", "baseStats": {"atk": 208, "def": 123, "hp": 347},
     "types": ["ice", "none"]},
    {"speciesId": "swalot", "speciesName": "Swalot", "baseStats": {"atk": 140, "def": 159, "hp": 225},
     "types": ["poison", "none"]},
    {"speciesId": "lapras", "speciesName": "Lapras", "baseStats": {"atk": 165, "def": 174, "hp": 277},
     "types": ["water", "ice"]},
    {"speciesId": "metagross", "speciesName": "Metagross", "baseStats": {"atk": 257, "def": 228, "hp": 190},
     "types": ["steel", "psychic"]},
    {"speciesId": "zamazenta_hero", "speciesName": "Zamazenta (Hero)", "baseStats": {"atk": 254, "def": 236, "hp": 192},
     "types": ["fighting", "none"]},
    {"speciesId": "stunfisk_galarian", "speciesName": "Stunfisk (Galarian)", "baseStats": {"atk": 144, "def": 171, "hp": 240},
     "types": ["ground", "steel"]},
    {"speciesId": "gyarados_mega", "speciesName": "Gyarados (Mega)", "baseStats": {"atk": 292, "def": 247, "hp": 216},
     "types": ["water", "dark"], "tags": ["mega"]},
    {"speciesId": "gyarados", "speciesName": "Gyarados", "baseStats": {"atk": 237, "def": 186, "hp": 216},
     "types": ["water", "flying"]},
])
FORMATS = [{"title": "LAIC 2027 Cup (GBL)", "cup": "laic2027gbl", "cp": 1500},
           {"title": "LAIC 2027 Championship Series Cup", "cup": "laic2027", "cp": 1500},
           {"title": "Mega Master League", "cup": "mega", "cp": 10000},
           {"title": "Mega Ultra League", "cup": "mega", "cp": 2500},
           {"title": "Custom", "cup": "custom", "cp": 1500}]


class Data(unittest.TestCase):
    def test_names_as_the_game_shows_them(self):
        self.assertEqual(C.find_species("Cetoddle", TABLE), "cetoddle")
        self.assertEqual(C.find_species("Galarian Stunfisk", TABLE), "stunfisk_galarian")
        self.assertEqual(C.find_species("Zamazenta", TABLE), "zamazenta_hero")
        self.assertEqual(C.find_species("Gyarados", TABLE), "gyarados")          # (not the Mega)
        self.assertEqual(C.find_species("Metagros", TABLE), "metagross")         # (a misread letter)
        self.assertIsNone(C.find_species("Sparky", TABLE))                      # (a nickname)

    def test_caps_and_cups(self):
        self.assertEqual([C.parse_cap(t) for t in ("Max CP per Pokémon: 2.500", "1,500", "Max CP per Pokemon: No limit")],
                         [2500, 1500, 10000])
        self.assertEqual(C.match_format("Ultra League", 2500, FORMATS), ("all", 2500))
        self.assertEqual(C.match_format("Master League: Mega Edition", 10000, FORMATS), ("mega", 10000))
        self.assertEqual(C.match_format("2026 GO LAIC Cup: Great League Edition", 1500, FORMATS), ("laic2027gbl", 1500))
        self.assertEqual(C.match_format("Great League", 1500, FORMATS), ("all", 1500))

    def test_the_leagues_on_the_league_list(self):
        def line(t, x, y):
            return (t, x, y, [(w, x + i * 60, y) for i, w in enumerate(t.split())])
        lines = [line("CHOOSE YOUR LEAGUE", 620, 530), line("ULTRA LEAGUE", 1000, 720),
                 line("MAX CP PER POKEMON: 2.500", 1000, 780), line("MASTER LEAGUE: MEGA", 1000, 950),
                 line("EDITION", 1000, 1010), line("MAX CP PER POKEMON: NO LIMIT", 1000, 1070),
                 line("2026 GO LAIC CUP:", 1000, 1220), line("GREAT LEAGUE EDITION", 1000, 1280),
                 line("MAX CP PER POKEMON: 1.500", 1000, 1340), line("SEE WHAT'S COMING NEXT ON 24 NOVEMBER!", 300, 2100)]
        self.assertEqual(BN.read_leagues(lines), [("Ultra League", 2500), ("Master League: Mega Edition", 10000),
                                                  ("2026 GO LAIC Cup: Great League Edition", 1500)])

    def test_tag_names(self):
        self.assertEqual(C.tag_name("Ultra League"), "Ultra League")
        short = C.tag_name("2026 GO LAIC Cup: Great League Edition", 24)
        self.assertLessEqual(len(short), 24)
        self.assertTrue(short.startswith("GO LAIC Cup"))


class Stats(unittest.TestCase):
    def test_level_and_the_best_level_under_a_cap(self):
        base = TABLE["swalot"]["base"]
        cp = C.cp_of(base, (0, 15, 14), 30.0)
        self.assertEqual(C.level_from_cp(base, (0, 15, 14), cp), 30.0)
        self.assertIsNone(C.level_from_cp(base, (0, 15, 14), cp + 1))
        lv, cp1500, sp = C.best_under(base, (0, 15, 14), 1500)
        self.assertLessEqual(cp1500, 1500)
        self.assertGreater(C.cp_of(base, (0, 15, 14), lv + 0.5), 1500)
        self.assertIsNone(C.best_under(base, (15, 15, 15), 1500, min_level=50.0))   # (cannot be powered down)

    def test_low_attack_fits_great_league_better(self):
        base = TABLE["swalot"]["base"]
        self.assertGreater(C.iv_fit(base, (0, 15, 15), 1500), C.iv_fit(base, (15, 15, 15), 1500))
        self.assertEqual(C.iv_fit(base, (15, 15, 15), 10000), 1.0)

    def test_teams(self):
        leagues = [{"title": "Ultra League", "cap": 2500, "cup": "all"},
                   {"title": "LAIC Cup", "cap": 1500, "cup": "laic2027gbl"}]
        ranks = {"Ultra League": {"lapras": {"score": 90, "moveset": ["A"]}, "metagross": {"score": 80, "moveset": []},
                                  "zamazenta_hero": {"score": 85, "moveset": []}, "swalot": {"score": 60, "moveset": []}},
                 "LAIC Cup": {"cetitan": {"score": 96, "moveset": ["X"]}, "swalot": {"score": 96, "moveset": []},
                              "lapras": {"score": 94, "moveset": []}}}
        mons = [{"id": "a", "name": "Cetoddle", "species": "cetoddle", "cp": 600, "ivs": [1, 13, 15]},
                {"id": "b", "name": "Swalot", "species": "swalot", "cp": 1400, "ivs": [0, 15, 14]},
                {"id": "c", "name": "Lapras", "species": "lapras", "cp": 1400, "ivs": [2, 14, 15]},
                {"id": "d", "name": "Metagross", "species": "metagross", "cp": 3536, "ivs": [15, 15, 15]},
                {"id": "e", "name": "Zamazenta", "species": "zamazenta_hero", "cp": 2300, "ivs": [14, 15, 15]},
                {"id": "f", "name": "Lapras", "species": "lapras", "cp": 2000, "ivs": [1, 15, 15]}]
        evals = C.evaluate(mons, leagues, TABLE, ranks)
        self.assertNotIn("d", evals)                              # (CP 3536 is over every cap of these leagues)
        self.assertEqual(evals["a"]["LAIC Cup"]["form"], "cetitan")   # it becomes a Cetitan
        self.assertTrue(evals["a"]["LAIC Cup"]["evolve"])
        teams = C.build_teams(mons, evals, leagues, TABLE)
        ids = {t: [e["mon"]["id"] for e in tm["team"]] for t, tm in teams.items()}
        every = [i for v in ids.values() for i in v]
        self.assertEqual(len(every), len(set(every)))            # each Pokémon in one team only
        self.assertTrue(ids["Ultra League"] and ids["LAIC Cup"])
        rows = C.export_rows({"mons": mons}, {"teams": teams, "evals": evals,
                                              "best_league": {m: max(e, key=lambda t: e[t]["value"]) for m, e in evals.items()}})
        self.assertEqual(len(rows), len(mons))
        self.assertEqual(rows[0]["best_form"], "Cetitan")


@unittest.skipIf(G is None, "gamebot cannot be imported here")
class Bars(unittest.TestCase):
    @staticmethod
    def panel(values):
        """A screen with the appraisal panel as on 24 November: three bars of three parts each."""
        img = np.full((2208, 1768, 3), (190, 160, 120), np.uint8)              # (the card behind it)
        cv2.rectangle(img, (110, 1480), (630, 1860), (255, 255, 255), -1)      # the white panel
        cv2.circle(img, (220, 1350), 150, (80, 170, 245), -1)                  # the orange star badge above it
        x0, length, gap = 144, 450, 10
        part = (length - 2 * gap) / 3
        for i, v in enumerate(values):
            y = 1590 + i * 112
            colour = (120, 120, 225) if (i == 2 and v == 15) else (60, 160, 245)
            for p in range(3):                                                 # grey parts first
                a = int(x0 + p * (part + gap))
                cv2.rectangle(img, (a, y - 9), (int(a + part), y + 9), (222, 222, 222), -1)
            left = v
            for p in range(3):
                if left <= 0:
                    break
                a = int(x0 + p * (part + gap))
                cv2.rectangle(img, (a, y - 9), (int(a + part * min(left, 5) / 5), y + 9), colour, -1)
                left -= 5
            cv2.putText(img, ["Attack", "Defense", "HP"][i], (150, y - 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, colour, 2)
        return img

    def test_the_bars_are_read(self):
        for values in ([13, 12, 15], [0, 15, 14], [15, 0, 5], [7, 8, 10]):
            self.assertEqual(G._bars(self.panel(values)), values, values)

    def test_no_bars_no_ivs(self):
        self.assertIsNone(G._bars(np.full((2208, 1768, 3), 255, np.uint8)))


class Collection(unittest.TestCase):
    def test_a_nickname_is_found_by_its_stats(self):
        base = TABLE["lapras"]["base"]
        cp, hp = C.cp_of(base, (2, 14, 15), 25.0), C.hp_of(base, (2, 14, 15), 25.0)
        self.assertEqual(C.identify(cp, (2, 14, 15), hp, ["water", "ice"], "Nessie", TABLE)[:2], ("lapras", 25.0))
        self.assertEqual(C.identify(cp, (2, 14, 15), hp, None, "Lapras", TABLE)[2], "name")
        self.assertIsNone(C.identify(cp + 7, (2, 14, 15), hp, ["water", "ice"], "Nessie", TABLE)[0])

    def test_power_up_costs(self):
        self.assertEqual(C.power_cost(20.0, 20.0), (0, 0, 0))
        dust, candy, xl = C.power_cost(30.0, 41.0)
        self.assertGreater(dust, 0)
        self.assertGreater(candy, 0)
        self.assertGreater(xl, 0)
        self.assertEqual(C.power_cost(30.0, 40.0, lucky=True)[0], C.power_cost(30.0, 40.0)[0] // 2)
        self.assertGreater(C.power_cost(30.0, 40.0, shadow=True)[1], C.power_cost(30.0, 40.0)[1])

    def test_every_game_has_its_own_files(self):
        self.assertEqual(C.game_key(), "")
        self.assertEqual(C.game_key(C.MAIN_PACKAGE), "")
        self.assertEqual(C.game_key(C.MAIN_PACKAGE + ".samsung"), "samsung")
        self.assertNotEqual(C.collection_file(C.MAIN_PACKAGE + ".samsung"), C.collection_file())
        self.assertNotEqual(C.teams_file(C.MAIN_PACKAGE + ".samsung"), C.teams_file())

    def test_moves(self):
        m = {"moves": {"fast": "WATER_GUN", "charged": ["ICE_BEAM"]}}
        self.assertEqual(C.moves_status(m, "lapras", ["WATER_GUN", "ICE_BEAM"], TABLE), "ok")
        self.assertEqual(C.moves_status(m, "lapras", ["WATER_GUN", "SURF"], TABLE), "TM")
        self.assertEqual(C.moves_status({}, "lapras", ["WATER_GUN"], TABLE), "?")

    def test_roles_wanted_protected_and_the_battle_team(self):
        def entry(i, roles):
            return {"mon": {"id": i, "ivs": [0, 15, 15]},
                    "eval": {"roles": roles, "form": "lapras", "level": 20.0, "moveset": ["A", "B"]}}
        team = C.team_roles([entry("a", [50, 90, 50]), entry("b", [90, 50, 50]), entry("c", [50, 50, 90])])
        self.assertEqual([(e["mon"]["id"], e["role"]) for e in team], [("b", "Lead"), ("c", "Switch"), ("a", "Closer")])
        teams = {"Great League": {"team": team, "reserves": []}}
        self.assertEqual(len(C.battle_team_entries(teams, "great league")), 3)
        self.assertIsNone(C.battle_team_entries(teams, "Ultra League"))
        evals = {"x": {"Great League": {"form": "lapras", "fit": 0.97, "score": 90, "value": 1}}}
        self.assertEqual(C.protected_ids([], evals, teams), {"a", "b", "c", "x"})
        ranks = {"Great League": {"lapras": {"rank": 1, "score": 90}, "swalot": {"rank": 2, "score": 88}}}
        want = C.wanted_list([], evals, [{"title": "Great League"}], ranks)["Great League"]
        self.assertEqual([w["species"] for w in want], ["swalot"])


class Storage(unittest.TestCase):
    def test_collection_file(self):
        path = os.path.join(tempfile.mkdtemp(), "c.json")
        C.save_collection({"mons": [{"id": "x"}]}, path)
        self.assertEqual(C.load_collection(path), {"mons": [{"id": "x"}]})
        self.assertEqual(C.load_collection(path + ".none"), {})


if __name__ == "__main__":
    unittest.main()
