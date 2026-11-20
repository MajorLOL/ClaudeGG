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

    def test_no_shields_left(self):
        f, mv = self.foe("medicham", "ICE_PUNCH")
        ok, _ = be.should_shield(f, self.lapras, 0, mv)
        self.assertFalse(ok)

    def test_weak_move_is_not_shielded(self):
        f, mv = self.foe("medicham", "FRUSTRATION")
        ok, why = be.should_shield(f, self.noctowl, 2, mv)
        self.assertFalse(ok)
        self.assertIn("weak", why)
        ok, _ = be.should_shield(f, self.noctowl, 1, mv)
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

    def test_big_hit_is_shielded(self):
        f, mv = self.foe("medicham", "PSYCHIC")           # super effective hit is not involved:
        dmg = be.damage(mv, f, self.noctowl)
        frac = dmg / float(self.noctowl.max_hp)
        ok, _ = be.should_shield(f, self.noctowl, 2, mv)
        self.assertEqual(ok, frac >= be.SHIELD_HIT_2)

    def test_resisted_hit_is_not_shielded(self):
        f, mv = self.foe("azumarill", "BUBBLE_BEAM")        # water vs Lapras/Lanturn: resisted
        dmg = be.damage(mv, f, self.lanturn)
        self.assertLess(be.type_mult(mv.type, self.lanturn.types), 1.0)
        ok, _ = be.should_shield(f, self.lanturn, 2, mv)
        if dmg / float(self.lanturn.max_hp) < be.WEAK_RESISTED_HIT \
                and dmg < self.lanturn.hp:
            self.assertFalse(ok)

    def test_last_shield_is_saved_for_bigger_hits(self):
        f = be.foe_from_text("medicham")
        # craft a move that takes about 22% of max HP: shielded with two
        # shields, kept with the last one
        mv = be.Move("SURF")
        target = mon("noctowl", stats=(100.0, 100.0, 200.0))
        attacker = mon("medicham", stats=(100.0, 100.0, 150.0))
        dmg = be.damage(mv, attacker, target)
        frac = dmg / float(target.max_hp)
        self.assertTrue(be.WEAK_HIT <= frac)
        two, _ = be.should_shield(attacker, target, 2, mv)
        one, _ = be.should_shield(attacker, target, 1, mv)
        self.assertEqual(two, frac >= be.SHIELD_HIT_2)
        if be.SHIELD_HIT_2 <= frac < be.SHIELD_HIT_1:
            self.assertFalse(one)

    def test_cycle_rule_shields_when_the_next_fast_attacks_would_finish_us(self):
        f, mv = self.foe("skarmory", "CRUNCH")             # 42 dmg = 26% of Noctowl's HP
        self.assertEqual(be.damage(mv, f, self.noctowl), 42)
        # 1 shield, 80 HP left: not lethal, below the 30% / 60% thresholds, but the
        # 38 HP that remain are less than the next round of fast attacks (43)
        ok, why = be.should_shield(f, self.noctowl, 1, mv, 80)
        self.assertTrue(ok)
        self.assertIn("next fast attacks", why)
        # with 100 HP left the same hit is survivable: keep the last shield
        ok, why = be.should_shield(f, self.noctowl, 1, mv, 100)
        self.assertFalse(ok)
        self.assertIn("saving", why)

    def test_cycle_damage_numbers(self):
        f, mv = self.foe("skarmory", "CRUNCH")
        # Air Slash: 9 energy per hit, 7 damage; Crunch costs 45 -> ceil(45/9)+1 = 6 hits
        self.assertEqual(be.cycle_damage(f, self.noctowl, mv, 1), 6 * 7 + 1)
        self.assertEqual(be.cycle_damage(f, self.noctowl, mv, 2), (6 * 7 + 1) * 2)
        self.assertEqual(be.cycle_damage(f, self.noctowl, mv, 0), 0)

    def test_weak_move_is_still_not_shielded_at_low_hp_unless_lethal(self):
        f, mv = self.foe("medicham", "POWER_UP_PUNCH")      # 15 dmg
        self.assertEqual(be.damage(mv, f, self.noctowl), 15)
        ok, why = be.should_shield(f, self.noctowl, 2, mv, 30)   # 15 HP would be left: the cycle rule alone would shield
        self.assertFalse(ok)
        self.assertIn("weak", why)
        ok, _ = be.should_shield(f, self.noctowl, 2, mv, 15)     # now it is lethal
        self.assertTrue(ok)

    def test_unknown_move_assumes_the_hardest_hit(self):
        f = be.foe_from_text("medicham")
        dmg, mv = be.foe_hit(f, self.noctowl, None)
        self.assertEqual(dmg, max(be.damage(m, f, self.noctowl) for m in f.charged))


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

    def test_best_switch_against_steel_flying_is_lanturn(self):
        foe = be.foe_from_text("skarmory")
        best, score = be.best_switch(self.team, foe)
        self.assertEqual(best.name, "Lanturn")
        self.assertGreater(score, 0)

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
