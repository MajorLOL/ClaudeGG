"""Unit tests for battle_engine.  Run:  python3 -m unittest discover -s tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import battle_engine as be  # noqa: E402


def mon(species, stats=(100.0, 100.0, 150.0), **kw):
    """A Pokémon with fixed stats so that damage ratios are exactly 1."""
    return be.Mon(species, stats=stats, **kw)


class TypeChart(unittest.TestCase):
    def test_single_types(self):
        self.assertAlmostEqual(be.type_mult("water", ["fire"]), 1.6)
        self.assertAlmostEqual(be.type_mult("fire", ["water"]), 0.625)
        self.assertAlmostEqual(be.type_mult("normal", ["water"]), 1.0)

    def test_immunities_count_as_double_resisted(self):
        self.assertAlmostEqual(be.type_mult("electric", ["ground"]), 0.390625)
        self.assertAlmostEqual(be.type_mult("fighting", ["ghost"]), 0.390625)
        self.assertAlmostEqual(be.type_mult("dragon", ["fairy"]), 0.390625)

    def test_dual_types(self):
        self.assertAlmostEqual(be.type_mult("ice", ["dragon", "flying"]), 2.56)
        self.assertAlmostEqual(be.type_mult("grass", ["water", "ground"]), 2.56)
        self.assertAlmostEqual(be.type_mult("fire", ["water", "rock"]), 0.390625)
        self.assertAlmostEqual(be.type_mult("electric", ["water", "flying"]), 2.56)

    def test_chart_is_complete(self):
        chart = be.load()["types"]
        self.assertEqual(len(chart), 18)


class Damage(unittest.TestCase):
    def test_formula_equal_stats(self):
        a = mon("lapras")               # water/ice
        d = mon("noctowl")              # normal/flying
        surf = be.Move("SURF")          # power 75, STAB
        # floor(75 * 1.2 * 1 * 1 * 0.5 * 1.3) + 1 = 59
        self.assertEqual(be.damage(surf, a, d), 59)

    def test_super_effective_and_no_stab(self):
        a = mon("noctowl")
        d = mon("medicham")             # fighting/psychic
        shadow_ball = be.Move("SHADOW_BALL")      # power 90, no STAB
        # floor(90 * 1.0 * 1 * 1.6 * 0.5 * 1.3) + 1 = 94
        self.assertEqual(be.damage(shadow_ball, a, d), 94)

    def test_shadow_multipliers(self):
        plain = be.Mon("lapras", stats=(100.0, 100.0, 150.0))
        shadow = be.Mon("lapras", stats=(100.0, 100.0, 150.0), shadow=True)
        self.assertAlmostEqual(shadow.atk, 120.0)
        self.assertAlmostEqual(shadow.dfn, 83.333331, places=4)
        self.assertEqual(plain.max_hp, shadow.max_hp)

    def test_minimum_damage_is_one(self):
        a = mon("noctowl", stats=(10.0, 100.0, 150.0))
        d = mon("lapras", stats=(100.0, 500.0, 150.0))
        self.assertGreaterEqual(be.damage(be.Move("WING_ATTACK"), a, d), 1)


class Team(unittest.TestCase):
    def test_preset_fits_cp_and_hp(self):
        team = be.build_team(be.DEFAULT_TEAM)
        self.assertEqual([m.label for m in team],
                         ["Noctowl", "Shadow Lapras", "Lanturn"])
        for m, e in zip(team, be.DEFAULT_TEAM):
            self.assertEqual(m.max_hp, e["hp"])
            self.assertLessEqual(m.cp, 1500)

    def test_fit_stats_matches(self):
        for e in be.DEFAULT_TEAM:
            fit = be.fit_stats(e["species"], e["cp"], e["hp"])
            self.assertIsNotNone(fit, e["species"])
            level, ivs, _stats = fit
            row = be.load()["mons"][e["species"]]
            self.assertEqual(be.calc_cp(row[2:5], ivs, level), e["cp"])

    def test_moves_and_positions(self):
        team = be.build_team(be.DEFAULT_TEAM)
        self.assertEqual([m.pos for m in team], [0, 1, 2])
        self.assertEqual(team[0].fast.name, "Wing Attack")
        self.assertEqual([c.name for c in team[1].charged], ["Frustration", "Surf"])
        self.assertEqual([c.name for c in team[2].charged], ["Surf", "Thunderbolt"])

    def test_user_team_file_overrides_preset(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.json")
            with open(path, "w") as f:
                json.dump([{"species": "azumarill"}], f)
            team = be.load_team(path)
            self.assertEqual([m.name for m in team], ["Azumarill"])


class Lookup(unittest.TestCase):
    def test_species(self):
        self.assertEqual(be.find_species("Azumarill"), "azumarill")
        self.assertEqual(be.find_species("azumaril"), "azumarill")
        self.assertEqual(be.find_species("Shadow Medicham"), "medicham")
        self.assertIsNone(be.find_species("zzzzzzzz"))

    def test_species_with_forms(self):
        # the game shows "Gourgeist", PvPoke has the forms gourgeist_average / _small / _large / _super
        self.assertEqual(be.find_species("Gourgeist"), "gourgeist_average")
        self.assertEqual(be.find_species("Pumpkaboo"), "pumpkaboo_average")
        self.assertEqual(be.find_species("Galarian Corsola"), "corsola_galarian")
        self.assertEqual(be.find_species("Alolan Marowak"), "marowak_alolan")
        self.assertEqual(be.find_species("Cursola"), "cursola")

    def test_move(self):
        self.assertEqual(be.find_move("Thunder bolt"), "THUNDERBOLT")
        self.assertEqual(be.find_move("SHADOW BALL"), "SHADOW_BALL")
        self.assertIsNone(be.find_move(""))


class ChargedChoice(unittest.TestCase):
    def setUp(self):
        self.team = be.build_team(be.DEFAULT_TEAM)
        self.noctowl, self.lapras, self.lanturn = self.team

    def test_nothing_without_energy(self):
        foe = be.foe_from_text("medicham")
        mv, _ = be.pick_charged(self.lanturn, foe, 30, 0)
        self.assertIsNone(mv)

    def test_picks_super_effective_move(self):
        foe = be.foe_from_text("skarmory")        # steel/flying: weak to electric
        mv, _ = be.pick_charged(self.lanturn, foe, 100, 0)
        self.assertEqual(mv.name, "Thunderbolt")

    def test_does_not_throw_weak_frustration(self):
        foe = be.foe_from_text("medicham")
        mv, _ = be.pick_charged(self.lapras, foe, 70, 0)
        self.assertEqual(mv.name, "Surf")          # not Frustration

    def test_cheapest_finisher(self):
        foe = be.foe_from_text("medicham")
        foe.hp = 5
        mv, why = be.pick_charged(self.lanturn, foe, 100, 0)
        self.assertEqual(mv.name, "Surf")          # 45 energy beats 55
        self.assertIn("finishes", why)

    def test_wait_for_better_move_when_resisted(self):
        foe = be.foe_from_text("azumarill")        # resists Surf, weak to Thunderbolt
        mv, why = be.pick_charged(self.lanturn, foe, 47, 0)
        self.assertIsNone(mv)
        self.assertIn("building up to Thunderbolt", why)
        mv, _ = be.pick_charged(self.lanturn, foe, 55, 0)
        self.assertEqual(mv.name, "Thunderbolt")

    def test_baits_when_foe_has_shields(self):
        foe = be.foe_from_text("medicham")
        mv, why = be.pick_charged(self.lanturn, foe, 100, 2)
        self.assertEqual(mv.name, "Surf")           # cheaper move first
        self.assertIn("bait", why)

    def test_no_bait_when_foe_has_no_shields(self):
        foe = be.foe_from_text("medicham")
        mv, why = be.pick_charged(self.lanturn, foe, 100, 0)
        self.assertIsNotNone(mv)
        self.assertNotIn("bait", why)

    def test_builds_up_to_the_big_move_instead_of_throwing_a_weak_one(self):
        # Kingdra (Shadow) vs Talonflame: Swift is affordable at 35 energy but
        # Surf (x1.6) is almost three times as strong and 10 energy away.
        kd = be.Mon("kingdra", shadow=True, fast="DRAGON_BREATH",
                    charged=["SURF", "SWIFT"])
        tf = be.Mon("talonflame", fast="INCINERATE",
                    charged=["FLY", "BRAVE_BIRD"])
        mv, why = be.pick_charged(kd, tf, 36, 0)
        self.assertIsNone(mv)
        self.assertIn("Surf", why)
        mv, _ = be.pick_charged(kd, tf, 45, 0)
        self.assertEqual(mv.name, "Surf")

    def test_plan_prefers_the_fastest_knockout(self):
        kd = be.Mon("kingdra", shadow=True, fast="DRAGON_BREATH",
                    charged=["SURF", "SWIFT"])
        tf = be.Mon("talonflame", fast="INCINERATE",
                    charged=["FLY", "BRAVE_BIRD"])
        active = sorted(kd.charged, key=lambda m: m.energy)
        dmg = {m.id: be.damage(m, kd, tf) for m in active}
        plan = be.plan_kill(kd, tf, 36, tf.hp - 40, 0, active, dmg,
                            be.damage(kd.fast, kd, tf))
        self.assertEqual([m.id for m in plan], ["SURF"])

    def test_plan_with_shields_burns_one_throw_per_shield(self):
        kd = be.Mon("kingdra", shadow=True, fast="DRAGON_BREATH",
                    charged=["SURF", "SWIFT"])
        tf = be.Mon("talonflame", fast="INCINERATE",
                    charged=["FLY", "BRAVE_BIRD"])
        active = sorted(kd.charged, key=lambda m: m.energy)
        dmg = {m.id: be.damage(m, kd, tf) for m in active}
        plan = be.plan_kill(kd, tf, 100, tf.hp, 1, active, dmg,
                            be.damage(kd.fast, kd, tf))
        self.assertGreaterEqual(len(plan), 2)


class Shielding(unittest.TestCase):
    def setUp(self):
        self.team = be.build_team(be.DEFAULT_TEAM)
        self.noctowl, self.lapras, self.lanturn = self.team

    def foe(self, name, move=None):
        f = be.foe_from_text(name)
        return f, (be.Move(move) if move else None)

    def skarmory(self):
        # Air Slash: 7 dmg per hit on Noctowl; Crunch hits Noctowl for 42
        return (be.Mon("skarmory", fast="AIR_SLASH", charged=["CRUNCH"]),
                be.Move("CRUNCH"))

    def test_no_shields_left(self):
        f, mv = self.skarmory()
        ok, _ = be.should_shield(f, self.noctowl, 0, mv)
        self.assertFalse(ok)

    def test_lethal_hit_is_always_shielded(self):
        f, mv = self.foe("medicham", "PSYCHIC")
        self.lapras.hp = be.damage(mv, f, self.lapras)       # exactly lethal
        ok, why = be.should_shield(f, self.lapras, 1, mv)
        self.assertTrue(ok)
        self.assertIn("knock", why)

    def test_even_a_weak_move_is_shielded_when_it_is_lethal(self):
        f, mv = self.foe("medicham", "FRUSTRATION")
        self.noctowl.hp = be.damage(mv, f, self.noctowl)
        ok, _ = be.should_shield(f, self.noctowl, 1, mv)
        self.assertTrue(ok)

    def test_survivable_hit_at_full_health_keeps_the_shield(self):
        f, mv = self.skarmory()
        for shields in (1, 2):
            ok, why = be.should_shield(f, self.noctowl, shields, mv)
            self.assertFalse(ok)
            self.assertIn("keeping", why)

    def test_cycle_rule_shields_when_the_next_fast_attacks_would_finish_us(self):
        f, mv = self.skarmory()
        self.assertEqual(be.damage(mv, f, self.noctowl), 42)
        # 80 HP: 38 would be left, less than the next round of fast attacks (43)
        ok, why = be.should_shield(f, self.noctowl, 1, mv, 80)
        self.assertTrue(ok)
        self.assertIn("next fast attacks", why)
        # 100 HP: 58 left is enough for one shield ...
        ok, _ = be.should_shield(f, self.noctowl, 1, mv, 100)
        self.assertFalse(ok)
        # ... but not for two shields (two rounds of fast attacks: 86)
        ok, _ = be.should_shield(f, self.noctowl, 2, mv, 100)
        self.assertTrue(ok)

    def test_cycle_damage_numbers(self):
        f, mv = self.skarmory()
        # Air Slash: 9 energy per hit, 7 damage; Crunch costs 45 -> ceil(45/9)+1 = 6 hits
        self.assertEqual(be.cycle_damage(f, self.noctowl, mv, 1), 6 * 7 + 1)
        self.assertEqual(be.cycle_damage(f, self.noctowl, mv, 2), (6 * 7 + 1) * 2)
        self.assertEqual(be.cycle_damage(f, self.noctowl, mv, 0), 0)

    def test_leftover_energy_shortens_the_cycle(self):
        f, mv = self.skarmory()
        full = be.cycle_damage(f, self.noctowl, mv, 1)
        # 90 energy left after the throw: the next Crunch is already charged, so
        # only the margin of one hit remains
        self.assertEqual(be.cycle_damage(f, self.noctowl, mv, 1, foe_energy=90),
                         1 * 7 + 1)
        # 60 left: 15 more than a Crunch -> 30 energy to find -> ceil(30/9)+1 = 5 hits
        self.assertEqual(be.cycle_damage(f, self.noctowl, mv, 1, foe_energy=60),
                         5 * 7 + 1)
        # PvPoke only counts energy beyond one full Crunch
        self.assertEqual(be.cycle_damage(f, self.noctowl, mv, 1, foe_energy=45), full)

    def test_a_weak_move_is_shielded_too_when_a_second_move_must_not_connect(self):
        # PvPoke cannot tell which move is coming: with a hard-hitting charged move
        # in the foe's set a shield is spent on the weak one as well
        f = be.Mon("medicham", fast="COUNTER", charged=["POWER_UP_PUNCH", "ICE_PUNCH"])
        weak = be.Move("POWER_UP_PUNCH")
        self.assertEqual(be.damage(weak, f, self.noctowl), 15)
        self.assertEqual(be.damage(be.Move("ICE_PUNCH"), f, self.noctowl), 58)
        ok, _ = be.should_shield(f, self.noctowl, 2, weak, 162)
        self.assertFalse(ok)                      # full health: Ice Punch is survivable
        ok, why = be.should_shield(f, self.noctowl, 2, weak, 100)
        self.assertTrue(ok)
        self.assertIn("next fast attacks", why)

    def test_a_weak_move_alone_is_not_shielded_at_good_health(self):
        f = be.Mon("medicham", fast="COUNTER", charged=["POWER_UP_PUNCH"])
        mv = be.Move("POWER_UP_PUNCH")
        ok, _ = be.should_shield(f, self.noctowl, 2, mv, 162)
        self.assertFalse(ok)

    def test_a_big_second_move_makes_the_foe_dangerous(self):
        # a fast attack that hits hard (> 1.5 per turn) and a charged move worth
        # at least HP/1.4: shield
        f = be.Mon("medicham", fast="COUNTER", charged=["POWER_UP_PUNCH", "ICE_PUNCH"])
        weak = be.Move("POWER_UP_PUNCH")
        fast_dpt = be.damage(f.fast, f, self.noctowl) / float(f.fast.turns)
        self.assertGreater(fast_dpt, 1.5)
        ok, _ = be.should_shield(f, self.noctowl, 1, weak, 80)   # Ice Punch 58 >= 80/1.4
        self.assertTrue(ok)

    def test_unknown_move_assumes_the_hardest_hit(self):
        f = be.foe_from_text("medicham")
        dmg, mv = be.foe_hit(f, self.noctowl, None)
        self.assertEqual(dmg, max(be.damage(m, f, self.noctowl) for m in f.charged))


class ShieldsInARealBattle(unittest.TestCase):
    """use_shield: three against three.  PvPoke's duel rule (should_shield, above) keeps the last shield for
    the hit that would knock the Pokémon out; a battle that ends with a shield unused has wasted it."""

    def setUp(self):
        self.noctowl, self.lapras, self.lanturn = be.build_team(be.DEFAULT_TEAM)

    def test_a_big_hit_is_shielded_with_the_last_shield_too(self):
        """The fourth recorded battle: Megahorn on a Lanturn with 93% of its HP and one shield left.  The duel
        rule kept the shield ('survivable'), Megahorn took 61% of the HP bar and the battle ended with the
        shield unused."""
        f = be.foe_from_text("scolipede")
        hp = int(0.93 * self.lanturn.max_hp)
        self.assertEqual(be.should_shield(f, self.lanturn, 1, None, hp)[0], False)      # (the duel rule)
        for shields in (1, 2):
            ok, why = be.use_shield(f, self.lanturn, shields, hp)
            self.assertTrue(ok, why)
            self.assertIn("Megahorn would take 61% of our HP", why)

    def test_the_second_question_of_that_battle(self):
        """Noctowl with two thirds of its HP and one shield left against Mismagius: the duel rule let Dark
        Pulse through (36% of the HP bar)."""
        f = be.foe_from_text("mismagius")
        hp = int(0.67 * self.noctowl.max_hp)
        self.assertEqual(be.should_shield(f, self.noctowl, 1, None, hp)[0], False)
        ok, why = be.use_shield(f, self.noctowl, 1, hp)                 # (with the moves that were guessed)
        self.assertTrue(ok, why)
        f.charged = [be.Move("DARK_PULSE"), be.Move("SHADOW_BALL")]     # (with the one it really used)
        ok, why = be.use_shield(f, self.noctowl, 1, hp)
        self.assertTrue(ok, why)
        self.assertIn("Dark Pulse would take 36% of our HP", why)

    def test_a_small_hit_is_let_through(self):
        f = be.Mon("medicham", fast="COUNTER", charged=["POWER_UP_PUNCH"])
        self.assertEqual(be.damage(f.charged[0], f, self.noctowl), 15)                  # 9% of 162 HP
        for shields in (1, 2):
            ok, why = be.use_shield(f, self.noctowl, shields)
            self.assertFalse(ok, why)
            self.assertIn("small hit", why)

    def test_the_hit_is_taken_for_the_hardest_one(self):
        f = be.Mon("medicham", fast="COUNTER", charged=["POWER_UP_PUNCH", "ICE_PUNCH"])
        ok, why = be.use_shield(f, self.noctowl, 2)
        self.assertTrue(ok, why)
        self.assertIn("Ice Punch", why)

    def test_a_pokemon_that_is_nearly_finished_does_not_get_the_shield(self):
        """15% of its HP left and two more waiting: there is hardly anything to save.  It faints, the foe has
        spent its energy and the next one comes in with the shield."""
        f = be.foe_from_text("scolipede")
        hp = int(0.15 * self.lanturn.max_hp)
        ok, why = be.use_shield(f, self.lanturn, 1, hp, mine_left=2)
        self.assertFalse(ok, why)
        self.assertIn("kept for the next Pokémon", why)
        ok, why = be.use_shield(f, self.lanturn, 1, int(0.25 * self.lanturn.max_hp), mine_left=2)
        self.assertTrue(ok, why)                                        # (a quarter of the bar is worth it)

    def test_unless_it_is_the_last_one(self):
        f = be.foe_from_text("scolipede")
        ok, why = be.use_shield(f, self.lanturn, 1, int(0.15 * self.lanturn.max_hp), mine_left=1)
        self.assertTrue(ok, why)
        self.assertIn("our last Pokémon", why)
        ok, why = be.use_shield(f, self.lanturn, 1, 1, mine_left=1)     # (even for a single HP)
        self.assertTrue(ok, why)

    def test_or_its_own_charged_attack_is_ready(self):
        f = be.foe_from_text("scolipede")
        hp = int(0.15 * self.lanturn.max_hp)
        ok, why = be.use_shield(f, self.lanturn, 1, hp, mine_left=2, ready=True)
        self.assertTrue(ok, why)
        self.assertIn("our own charged attack is ready", why)
        # (ready or not: a hit that does not knock us out and is small stays a small hit)
        weak = be.Mon("medicham", fast="COUNTER", charged=["POWER_UP_PUNCH"])
        self.assertFalse(be.use_shield(weak, self.noctowl, 1, ready=True)[0])

    def test_nothing_to_keep_the_shield_for(self):
        """The foe's last Pokémon (or ours): after this duel a shield is worth nothing, so a hit of a seventh
        of the HP bar is shielded as well - but not next to nothing."""
        f = be.Mon("medicham", fast="COUNTER", charged=["POWER_UP_PUNCH"])
        lapras = self.lapras
        dmg = be.damage(f.charged[0], f, lapras)
        part = dmg / float(lapras.max_hp)
        self.assertTrue(be.SHIELD_HIT_LAST <= part < be.SHIELD_HIT, part)
        self.assertFalse(be.use_shield(f, lapras, 1, foes_left=2)[0])
        ok, why = be.use_shield(f, lapras, 1, foes_left=1)
        self.assertTrue(ok, why)
        self.assertIn("the foe is on its last Pokémon", why)
        ok, why = be.use_shield(f, lapras, 1, mine_left=1, foes_left=3)
        self.assertTrue(ok, why)
        self.assertIn("this is our last Pokémon", why)
        self.assertFalse(be.use_shield(f, self.noctowl, 1, foes_left=1)[0])             # (9%: let it through)

    def test_a_foe_that_is_not_known(self):
        ok, why = be.use_shield(None, self.noctowl, 2, int(0.9 * self.noctowl.max_hp))
        self.assertTrue(ok, why)
        self.assertIn("not known", why)
        ok, why = be.use_shield(None, self.noctowl, 2, int(0.1 * self.noctowl.max_hp), mine_left=3)
        self.assertFalse(ok, why)

    def test_no_shields_left(self):
        f = be.foe_from_text("scolipede")
        self.assertEqual(be.use_shield(f, self.lanturn, 0), (False, "no shields left"))


class Matchups(unittest.TestCase):
    def setUp(self):
        self.team = be.build_team(be.DEFAULT_TEAM)

    def test_simulation_terminates_and_one_side_faints(self):
        for name in ("medicham", "azumarill", "skarmory", "registeel", "stunfisk_galarian"):
            foe = be.foe_from_text(name)
            self.assertIsNotNone(foe, name)
            for m in self.team:
                a, b = be.simulate(m, foe)
                self.assertTrue(a == 0 or b == 0, (name, m.label, a, b))

    def test_simulation_does_not_change_inputs(self):
        foe = be.foe_from_text("medicham")
        hp = (self.team[0].hp, foe.hp, self.team[0].energy)
        be.simulate(self.team[0], foe)
        self.assertEqual(hp, (self.team[0].hp, foe.hp, self.team[0].energy))

    def test_best_switch_against_steel_flying_avoids_noctowl(self):
        foe = be.foe_from_text("skarmory")
        best, score = be.best_switch(self.team, foe)
        self.assertNotEqual(best.name, "Noctowl")
        self.assertGreater(score, 0)
        lanturn = self.team[2]
        for shields in (0, 1, 2):
            self.assertGreater(be.matchup(lanturn, foe, shields, shields), 0)

    def test_best_switch_skips_fainted(self):
        foe = be.foe_from_text("skarmory")
        self.team[2].hp = 0
        best, _ = be.best_switch(self.team, foe)
        self.assertNotEqual(best.name, "Lanturn")

    def test_best_switch_with_nobody_left(self):
        for m in self.team:
            m.hp = 0
        best, _ = be.best_switch(self.team, be.foe_from_text("skarmory"))
        self.assertIsNone(best)

    def test_noctowl_beats_fighting_type(self):
        # a fighting type without coverage (the ranked Medicham carries Ice Punch)
        foe = be.Mon("medicham", fast="COUNTER", charged=["DYNAMIC_PUNCH"])
        self.assertGreater(be.matchup(self.team[0], foe), 0)
        self.assertLess(be.matchup(self.team[1], foe), 0)


class DataFile(unittest.TestCase):
    def test_contents(self):
        d = be.load()
        self.assertGreater(len(d["mons"]), 900)
        self.assertGreater(len(d["moves"]), 300)
        self.assertGreaterEqual(len(d["cpm"]), 101)
        self.assertIn("MIT", d["source"])
        self.assertGreater(len(d["sets"]["1500"]), 500)

    def test_every_species_builds(self):
        for sid in be.load()["mons"]:
            m = be.Mon(sid)
            self.assertGreater(m.max_hp, 0)


class Movesets(unittest.TestCase):
    def test_ranked_set_is_used_for_opponents(self):
        fast, charged = be.ranked_moveset("noctowl")
        self.assertEqual(fast, "WING_ATTACK")
        self.assertEqual(charged, ["SHADOW_BALL", "RETURN"])
        foe = be.Mon("noctowl")
        self.assertEqual(foe.fast.id, "WING_ATTACK")
        self.assertEqual([c.id for c in foe.charged], ["SHADOW_BALL", "RETURN"])

    def test_shadow_shares_the_moves_of_its_normal_form(self):
        self.assertEqual(be.default_moveset("lapras"),
                         be.ranked_moveset("lapras"))
        foe = be.Mon("lapras", shadow=True)
        self.assertEqual(foe.fast.id, be.ranked_moveset("lapras")[0])

    def test_species_without_a_ranking_falls_back_to_the_guess(self):
        missing = [s for s in be.load()["mons"] if be.ranked_moveset(s) is None]
        self.assertTrue(missing)
        sid = missing[0]
        self.assertEqual(be.default_moveset(sid), be.guessed_moveset(sid))
        self.assertTrue(be.Mon(sid).charged)

    def test_every_ranked_set_is_usable(self):
        moves = be.load()["moves"]
        for sid, row in be.load()["sets"]["1500"].items():
            self.assertIn(sid, be.load()["mons"])
            self.assertGreaterEqual(len(row), 2)
            self.assertEqual(moves[row[0]][3], 0, "%s: first move is fast" % sid)
            for m in row[1:]:
                self.assertGreater(moves[m][3], 0, "%s: %s is charged" % (sid, m))

    def test_explicit_moves_still_win(self):
        m = be.Mon("noctowl", fast="WING_ATTACK", charged=["SKY_ATTACK"])
        self.assertEqual([c.id for c in m.charged], ["SKY_ATTACK"])


if __name__ == "__main__":
    unittest.main()
