"""Unit tests for battle_fight (the state and the decisions of one GO Battle League fight).  Run:
python3 -m unittest discover -s tests

features.json holds what battle_vision saw on the 141 pictures of a recorded fight (every 1.3 s): replaying it
checks that the fight state survives real, noisy readings."""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import battle_engine as be  # noqa: E402
import battle_fight as bf  # noqa: E402

with open(os.path.join(HERE, "fixtures", "fight", "features.json"), encoding="utf-8") as f:
    FEATURES = json.load(f)


def feat(hp=(None, None), lit=(False, False), shields=None, hud=True, ring=False, result=False):
    return {"hud": hud, "white": False, "versus": False, "ring": ring, "result": result, "ready": list(lit),
            "shields": shields or {"me": 2, "foe": 2}, "hp": list(hp)}


def see_twice(fight, **kw):
    """A big change of the HP is only believed when two pictures agree."""
    fight.see(feat(**kw))
    fight.see(feat(**kw))


def new_fight(foe="Cramorant"):
    team = be.load_team()
    fight = bf.Fight(team, log=lambda _m: None)
    if foe:
        fight.set_foe(foe, 1493)
    fight.set_buttons("SHADOW BALL", "SKY ATTACK")
    return fight


class State(unittest.TestCase):
    def test_states(self):
        self.assertEqual(bf.state(feat()), "fight")
        self.assertEqual(bf.state(feat(hud=False)), "other")
        self.assertEqual(bf.state(feat(hud=False, ring=True)), "prompt")
        self.assertEqual(bf.state(feat(hud=False, result=True)), "result")
        white = feat()
        white["white"] = True                      # (a white screen looks like a HUD: all pale)
        self.assertEqual(bf.state(white), "other")

    def test_result_needs_the_hud_to_be_gone(self):
        self.assertEqual(bf.state(feat(result=True)), "fight")


class NextOneComesIn(unittest.TestCase):
    def test_last_pokemon_comes_in_by_itself(self):
        """Two of three have fainted: the third comes in without a question, only the HP bar tells."""
        fight = new_fight()
        first, second, third = fight.team
        fight.faint()                                   # (the first one fainted earlier, the second came in)
        fight._enter(second)
        see_twice(fight, hp=(0.05, 0.7), lit=(False, False))
        self.assertEqual(fight.me, second)              # (still the second: its bar is nearly empty)
        see_twice(fight, hp=(1.0, 0.7), lit=(False, False))
        self.assertEqual(fight.me, third)
        self.assertIn(second.pos, fight.dead)
        self.assertTrue(fight.need_labels)

    def test_with_two_left_the_game_asks_instead(self):
        fight = new_fight()
        see_twice(fight, hp=(0.05, 0.7))
        see_twice(fight, hp=(1.0, 0.7))
        self.assertEqual(fight.me, fight.team[0])       # (not guessed: switch() decides)


class ShieldsAndNames(unittest.TestCase):
    def test_a_shield_that_was_not_used_comes_back(self):
        fight = new_fight()
        fight.me.hp = 1                                      # (so that the engine wants the shield)
        fight.my_hp = 0.01
        use, _why = fight.shield()
        self.assertTrue(use)
        self.assertEqual(fight.my_shields, 1)
        for _ in range(bf.SHIELDS_BACK - 1):                 # the icons still show two: the tap came too late
            fight.see(feat(shields={"me": 2, "foe": 2}))
        self.assertEqual(fight.my_shields, 1)
        fight.see(feat(shields={"me": 2, "foe": 2}))
        self.assertEqual(fight.my_shields, 2)

    def test_a_shield_that_is_used_does_not_come_back(self):
        fight = new_fight()
        fight.my_shields = 1
        for _ in range(3):                                   # for a moment the icons still show two ...
            fight.see(feat(shields={"me": 2, "foe": 2}))
        for _ in range(4):                                   # ... then one turns grey
            fight.see(feat(shields={"me": 1, "foe": 2}))
        for _ in range(3):
            fight.see(feat(shields={"me": 2, "foe": 2}))     # (a misread now and then does not count)
            fight.see(feat(shields={"me": 1, "foe": 2}))
        self.assertEqual(fight.my_shields, 1)

    def test_the_foes_shields_never_come_back(self):
        fight = new_fight()
        fight.foe_shields = 0
        for _ in range(20):
            fight.see(feat(shields={"me": 2, "foe": 2}))
        self.assertEqual(fight.foe_shields, 0)

    def test_names_are_read_when_asked(self):
        fight = new_fight()
        self.assertFalse(fight.foe_due)
        fight.read_names()
        self.assertTrue(fight.foe_due)
        fight.set_foe("Cramorant", 1493)
        self.assertFalse(fight.foe_due)

    def test_a_name_box_that_gave_nothing_is_read_again_soon(self):
        fight = new_fight()
        fight.foe_every = 50                                 # (the live video: ten pictures a second)
        fight.set_foe("", None)
        seen = 0
        while not fight.foe_due:
            fight.see(feat())
            seen += 1
        self.assertLessEqual(seen, bf.FOE_RETRY)
        fight.set_foe("Cramorant", 1493)                     # read well: the next look is far away
        fight.see(feat())
        self.assertFalse(fight.foe_due)


class Buttons(unittest.TestCase):
    def test_labels_give_the_slots(self):
        fight = new_fight()
        self.assertEqual(fight.slots, ["SHADOW_BALL", "SKY_ATTACK"])
        self.assertTrue(fight.labels_ok)
        self.assertFalse(fight.need_labels)

    def test_labels_the_other_way_round(self):
        fight = bf.Fight(be.load_team())
        fight.set_buttons("SKY ATTACK", "SHADOW BALL")
        self.assertEqual(fight.move_of(0).id, "SKY_ATTACK")
        self.assertEqual(fight.move_of(1).id, "SHADOW_BALL")

    def test_one_label_is_enough(self):
        fight = bf.Fight(be.load_team())
        fight.set_buttons("NOISE", "SKY ATTACK")
        self.assertEqual(fight.slots, ["SHADOW_BALL", "SKY_ATTACK"])

    def test_hints_next_to_the_names(self):
        fight = bf.Fight(be.load_team())
        fight.set_buttons("NOT VERY FRUSTRATION EFFECTIVE", "SUPER SURF EFFECTIVE")      # (not Noctowl's moves)
        self.assertTrue(fight.need_labels)
        fight.me = fight.team[1]                                                       # Shadow Lapras
        fight.set_buttons("NOT VERY FRUSTRATION EFFECTIVE", "SUPER SURF EFFECTIVE")
        self.assertEqual(fight.slots, ["FRUSTRATION", "SURF"])

    def test_labels_never_read_keeps_the_party_order(self):
        fight = bf.Fight(be.load_team())
        for _ in range(bf.LABEL_TRIES):
            fight.set_buttons("", "")
        self.assertFalse(fight.need_labels)
        self.assertEqual(fight.move_of(0).id, "SHADOW_BALL")

    def test_only_the_cheaper_move_is_lit(self):
        """Without labels: a single lit button is the cheaper move (Fire Blast 80 / Surf 40, say)."""
        team = be.build_team([{"species": "lapras", "fast": "ICE_SHARD", "charged": ["SURF", "FRUSTRATION"]}])
        fight = bf.Fight(team)
        a, b = fight.me.charged
        cheap = min(fight.me.charged, key=lambda m: m.energy)
        if a.energy == b.energy:
            self.skipTest("both moves cost the same")
        fight.see(feat(lit=(False, True)))
        self.assertEqual(fight.move_of(1).id, cheap.id)


class Throwing(unittest.TestCase):
    def test_nothing_lit_nothing_thrown(self):
        fight = new_fight()
        fight.see(feat())
        self.assertIsNone(fight.throw())

    def test_energy_comes_from_the_lit_buttons(self):
        fight = new_fight()
        fight.see(feat(lit=(True, False)))
        self.assertEqual(fight.energy, fight.move_of(0).energy)
        fight.see(feat(lit=(True, True)))
        self.assertEqual(fight.energy, max(m.energy for m in fight.me.charged))

    def test_throws_the_move_of_a_lit_button(self):
        fight = new_fight()
        fight.foe_shields = 0
        fight.see(feat(hp=(1.0, 1.0), lit=(True, True), shields={"me": 2, "foe": 0}))
        button, move, why = fight.throw()
        self.assertIn(button, (0, 1))
        self.assertEqual(fight.move_of(button).id, move.id)
        self.assertEqual(fight.lit, (False, False))        # (spent)
        self.assertTrue(why)

    def test_waits_with_the_fast_attack_when_the_engine_says_so(self):
        fight = new_fight()
        see_twice(fight, hp=(0.9, 0.31), lit=(True, True))       # the foe nearly down, two shields: farm it down
        self.assertEqual(be.pick_charged(fight.me, fight.foe, fight.energy, 2, fight.foe.hp)[0], None)
        self.assertIsNone(fight.throw())

    def test_foe_not_known_still_throws(self):
        fight = new_fight(foe=None)
        fight.see(feat(lit=(False, True)))
        button, move, _why = fight.throw()
        self.assertEqual(button, 1)


class Shields(unittest.TestCase):
    def test_the_engine_decides(self):
        fight = new_fight()
        see_twice(fight, hp=(0.30, 0.80))
        use, why = fight.shield()
        self.assertTrue(use, why)
        self.assertEqual(fight.my_shields, 1)

    def test_no_shield_left(self):
        fight = new_fight()
        fight.my_shields = 0
        self.assertEqual(fight.shield()[0], False)

    def test_keeps_the_shield_for_a_small_hit(self):
        fight = new_fight()
        fight.see(feat(hp=(1.0, 1.0)))
        use, _why = fight.shield()
        self.assertFalse(use)
        self.assertEqual(fight.my_shields, 2)

    def test_foe_not_known(self):
        fight = new_fight(foe=None)
        fight.my_hp = 0.9
        self.assertFalse(fight.shield()[0])
        fight.my_hp = 0.3
        self.assertTrue(fight.shield()[0])

    def test_icons_are_believed_after_two_pictures(self):
        fight = new_fight()
        fight.see(feat(shields={"me": 2, "foe": 1}))
        self.assertEqual(fight.foe_shields, 2)
        fight.see(feat(shields={"me": 2, "foe": 1}))
        self.assertEqual(fight.foe_shields, 1)
        fight.see(feat(shields={"me": 2, "foe": 2}))           # (never goes up)
        self.assertEqual(fight.foe_shields, 1)

    def test_icons_without_the_hud_are_not_read(self):
        fight = new_fight()
        for _ in range(3):
            fight.see(feat(hud=False, shields={"me": 0, "foe": 0}))
        self.assertEqual((fight.my_shields, fight.foe_shields), (2, 2))


class HP(unittest.TestCase):
    def test_small_steps_are_taken(self):
        fight = new_fight()
        fight.see(feat(hp=(0.9, 0.8)))
        self.assertAlmostEqual(fight.my_hp, 0.9)
        self.assertAlmostEqual(fight.foe_hp, 0.8)
        self.assertEqual(fight.me.hp, round(0.9 * fight.me.max_hp))

    def test_a_big_jump_needs_two_pictures(self):
        fight = new_fight()
        see_twice(fight, hp=(1.0, 0.6))
        fight.see(feat(hp=(1.0, 0.05)))                         # (a spark that looks like a bar)
        self.assertAlmostEqual(fight.foe_hp, 0.6)
        fight.see(feat(hp=(1.0, 0.55)))
        self.assertAlmostEqual(fight.foe_hp, 0.55)
        fight.see(feat(hp=(1.0, 0.05)))
        fight.see(feat(hp=(1.0, 0.06)))                         # ... but twice is a real drop
        self.assertAlmostEqual(fight.foe_hp, 0.06)

    def test_our_hp_never_goes_up(self):
        fight = new_fight()
        see_twice(fight, hp=(0.6, 0.5))
        fight.see(feat(hp=(0.5, 0.5)))
        fight.see(feat(hp=(0.55, 0.5)))
        self.assertAlmostEqual(fight.my_hp, 0.5)

    def test_hp_is_read_without_the_hud_too(self):
        fight = new_fight()
        fight.see(feat(hp=(0.8, 0.9), hud=False))
        self.assertAlmostEqual(fight.my_hp, 0.8)


class Foes(unittest.TestCase):
    def test_foe_from_the_name_box(self):
        fight = new_fight(foe=None)
        self.assertTrue(fight.foe_due)
        self.assertTrue(fight.set_foe("Cramorant", 1493))
        self.assertEqual(fight.foe.species, be.find_species("Cramorant"))
        self.assertFalse(fight.foe_due)

    def test_checked_again_after_a_few_pictures(self):
        fight = new_fight()
        for _ in range(bf.FOE_CHECK_EVERY):
            fight.see(feat())
        self.assertTrue(fight.foe_due)

    def test_the_same_foe_changes_nothing(self):
        fight = new_fight()
        see_twice(fight, hp=(1.0, 0.5))
        fight.set_foe("Cramorant", 1493)
        self.assertAlmostEqual(fight.foe_hp, 0.5)

    def test_a_new_foe_comes_in_with_full_hp(self):
        fight = new_fight()
        fight.see(feat(hp=(1.0, 0.05)))
        fight.set_foe("Beedrill", 1483)
        self.assertEqual(fight.foe.species, be.find_species("Beedrill"))
        self.assertAlmostEqual(fight.foe_hp, 1.0)

    def test_unknown_name_keeps_the_foe(self):
        fight = new_fight()
        self.assertTrue(fight.set_foe("Xxxxxxx", None))
        self.assertEqual(fight.foe.species, be.find_species("Cramorant"))

    def test_a_hp_jump_asks_for_the_name(self):
        fight = new_fight()
        see_twice(fight, hp=(1.0, 0.05))
        fight.set_foe("Cramorant", 1493)
        self.assertFalse(fight.foe_due)
        see_twice(fight, hp=(1.0, 0.9))
        self.assertTrue(fight.foe_due)


class Switching(unittest.TestCase):
    TILES = [(1489, 570), (1494, 1195)]

    def test_picks_a_tile_by_cp(self):
        fight = new_fight("Beedrill")
        idx, mon, why = fight.switch(self.TILES)
        self.assertIn(idx, (0, 1))
        self.assertEqual(mon.cp, self.TILES[idx][0])
        self.assertEqual(fight.me, mon)
        self.assertIn(0, fight.dead)
        self.assertTrue(fight.need_labels)
        self.assertEqual(fight.my_hp, 1.0)

    def test_the_best_matchup_is_chosen(self):
        fight = new_fight("Beedrill")
        left = [m for m in fight.team if m.pos != 0]
        best, _score = be.best_switch(left, fight.foe, fight.my_shields, fight.foe_shields)
        idx, mon, _why = fight.switch(self.TILES)
        self.assertEqual(mon, best)

    def test_tiles_without_cp_follow_the_party_order(self):
        fight = new_fight("Beedrill")
        idx, mon, why = fight.switch([(0, 570), (0, 1195)])
        self.assertIn("party order", why)
        self.assertEqual(mon, fight.team[1 + idx])

    def test_no_tiles_read(self):
        fight = new_fight("Beedrill")
        idx, mon, _why = fight.switch([])
        self.assertIsNone(idx)
        self.assertIsNotNone(mon)

    def test_foe_not_known(self):
        fight = new_fight(foe=None)
        idx, mon, why = fight.switch(self.TILES)
        self.assertEqual(idx, 0)
        self.assertIn("not known", why)

    def test_last_pokemon_down(self):
        fight = new_fight("Beedrill")
        fight.dead = {1, 2}
        self.assertEqual(fight.switch([])[1], None)

    def test_someone_else_is_on_the_field(self):
        fight = new_fight()
        fight.set_active(1494)                           # the name box says Lanturn, we thought Noctowl
        self.assertEqual(fight.me.species, be.find_species("Lanturn"))
        self.assertTrue(fight.need_labels)
        self.assertEqual(fight.dead, set())              # (Noctowl did not faint: we only had the wrong one)

    def test_the_next_one_comes_in_by_itself(self):
        fight = new_fight()
        see_twice(fight, hp=(0.07, 0.5))
        fight.set_active(1489)                           # Noctowl was nearly down; Lapras is on the field now
        self.assertEqual(fight.dead, {0})
        self.assertEqual(fight.my_hp, 1.0)

    def test_the_same_cp_changes_nothing(self):
        fight = new_fight()
        fight.set_active(1497)
        fight.set_active(None)
        self.assertEqual(fight.me.pos, 0)


class Replay(unittest.TestCase):
    """The pictures of a whole recorded fight, one after the other (as the loop in gamebot.py sees them)."""

    def run_fight(self):
        """What the loop knows besides the pictures: our switch at picture 65 (Lanturn) and the name box that
        shows Lapras at 108 (Lanturn fainted, Lapras came in by itself: the game does not ask for the last one)."""
        fight = new_fight()
        events = {65: lambda: fight.switch([(1494, 1195)]), 108: lambda: fight.set_active(1489)}
        trace = []
        for i, f in enumerate(FEATURES):
            if i in events:
                events[i]()
            st = bf.state(f)
            if st in ("fight", "other"):
                fight.see(f)
            trace.append((st, fight.foe_hp, fight.my_hp, fight.foe_shields, fight.my_shields))
        return fight, trace

    def test_states_of_the_recording(self):
        states = [bf.state(f) for f in FEATURES]
        self.assertEqual(states[:3], ["other"] * 3)                 # VS screen
        self.assertEqual(states[135:138], ["result"] * 3)          # GOOD EFFORT
        self.assertEqual(states[15], "prompt")
        self.assertEqual(states[65], "prompt")
        self.assertEqual(states[125], "prompt")
        self.assertGreater(states.count("fight"), 50)

    def test_no_picture_but_the_last_ones_is_a_result(self):
        self.assertNotIn("result", [bf.state(f) for f in FEATURES[:135]])

    def test_sparks_of_a_charged_attack_do_not_move_the_foe_hp(self):
        _fight, trace = self.run_fight()
        for i in (80, 81):
            self.assertGreater(trace[i][1], 0.45, f"picture {i}")

    def test_the_foe_ends_with_two_shields_less(self):
        fight, _trace = self.run_fight()
        self.assertEqual(fight.foe_shields, 0)

    def test_our_hp_only_goes_down_while_the_same_pokemon_fights(self):
        _fight, trace = self.run_fight()
        mine = [t[2] for t in trace]
        rises = [i + 1 for i, (a, b) in enumerate(zip(mine, mine[1:])) if b > a + 1e-9]
        self.assertEqual(rises, [65, 108])                  # (the two times a new Pokémon came in)


if __name__ == "__main__":
    unittest.main()
