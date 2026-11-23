"""Unit tests for battle_fight (the state and the decisions of one GO Battle League fight).  Run:
python3 -m unittest discover -s tests

features.json holds what battle_vision sees on the 141 pictures of a recorded fight (every 1.3 s, an arena by
night), features_day.json, features_day2.json and features_day3.json the same for the fights of three more
recordings (113, 119 and 95 pictures, an arena by day): replaying them checks that the fight state survives
real, noisy readings.  The files are made from the recordings with the readers as they are now; when a reader
changes they are made again."""
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
        for _ in range(bf.JUST_CAME_IN):                # (it fought for a while)
            fight.see(feat(hp=(0.5, 0.7), lit=(False, False)))
        see_twice(fight, hp=(0.05, 0.7), lit=(False, False))
        self.assertEqual(fight.me, second)              # (still the second: its bar is nearly empty)
        see_twice(fight, hp=(1.0, 0.7), lit=(False, False))
        self.assertEqual(fight.me, third)
        self.assertIn(second.pos, fight.dead)
        self.assertTrue(fight.need_labels)

    def test_the_entrance_of_a_pokemon_is_not_a_faint(self):
        """23 November, 09:29: right after a switch the bar was read empty for a moment (the Pokémon coming in)
        and then full - and the bot took the one that had just come in for fainted."""
        fight = new_fight()
        first, second, third = fight.team
        fight.faint()
        fight._enter(second)
        see_twice(fight, hp=(0.05, 0.7), lit=(False, False))
        see_twice(fight, hp=(1.0, 0.7), lit=(False, False))
        self.assertEqual(fight.me, second)
        self.assertNotIn(second.pos, fight.dead)

    def test_with_two_left_the_game_asks_instead(self):
        fight = new_fight()
        see_twice(fight, hp=(0.05, 0.7))
        see_twice(fight, hp=(1.0, 0.7))
        self.assertEqual(fight.me, fight.team[0])       # (not guessed: switch() decides)


class ShieldsAndNames(unittest.TestCase):
    def test_a_shield_that_was_not_used_comes_back(self):
        fight = new_fight()                                  # (Cramorant's Surf takes 40% of Noctowl's HP)
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

    def test_a_banner_over_the_name_boxes_takes_no_shields_away(self):
        """'Slowbro used Ice Beam!' lies over the shield icons for a second or two: they are not seen then
        (None), which is not the same as none left.  It used to count as 0 for both sides - and the foe's
        shields never come back, so the engine played the rest of the fight as if the foe had none."""
        fight = new_fight()
        for _ in range(30):
            fight.see(feat(shields={"me": None, "foe": None}))
        self.assertEqual((fight.my_shields, fight.foe_shields), (2, 2))
        for _ in range(2):
            fight.see(feat(shields={"me": 2, "foe": 1}))         # the foe used one: seen on two clear pictures
        for _ in range(30):
            fight.see(feat(shields={"me": None, "foe": None}))
            fight.see(feat(shields={"me": 2, "foe": None}))
        self.assertEqual((fight.my_shields, fight.foe_shields), (2, 1))

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

    def test_the_tiles_on_the_question_correct_a_wrong_count(self):
        """23 November, 09:29 and 09:32: the bot took Lapras for fainted, thought Lanturn was the only one left
        and tapped the middle of the screen - between the two tiles that were shown - eleven times."""
        fight = new_fight("Raichu")
        lapras = fight.team[1]
        fight.dead.add(lapras.pos)                             # (the wrong count)
        logs = []
        fight.log = logs.append
        _idx, mon, why = fight.switch([], 2)                   # (Noctowl fainted; two tiles on the screen)
        self.assertNotIn(lapras.pos, fight.dead, logs)
        self.assertEqual(fight.tile[1], 2)
        self.assertEqual(fight.tile[0], [fight.team[1], fight.team[2]].index(mon))
        self.assertIn("did not faint after all", logs[0])
        fight2 = new_fight("Raichu")
        fight2.switch([], 2)                                   # (a right count: nothing to correct)
        self.assertEqual(fight2.tile[1], 2)

    def test_never_the_middle_when_the_question_comes(self):
        """23 November, 11:55: the tiles were not counted on the picture (it came too early) and the count said
        one was left: the middle was tapped again.  A question means two tiles."""
        fight = new_fight("Raichu")
        lapras, lanturn = fight.team[1], fight.team[2]
        fight.dead.add(lapras.pos)                             # (the wrong count)
        _idx, mon, _why = fight.switch([], 1)                  # (the picture did not show the tiles yet)
        self.assertIs(mon, lanturn)
        self.assertEqual(fight.tile, (1, 2))                   # (the right tile: Lapras is on the left)

    def test_after_a_switch_the_other_one_on_the_field_is_a_missed_tap(self):
        """22 November, 18:16: the bot chose Lanturn, its taps on the tile did not count and the game sent in
        Lapras when the time ran out.  The bot then took Lanturn for fainted."""
        fight = new_fight("Crustle")
        idx, chosen, why = fight.switch([])                     # (Noctowl fainted: the question comes)
        other = next(m for m in fight.alive() if m is not chosen)
        for _ in range(20):
            fight.see(feat(hp=(1.0, 0.8)))
        logs = []
        fight.log = logs.append
        fight.set_active(other.cp)
        self.assertIs(fight.me, other)
        self.assertNotIn(chosen.pos, fight.dead, logs)
        self.assertIn("did not count, the game chose", logs[-1])

    def test_a_switch_that_counted_and_a_faint_later(self):
        """The chosen one was seen in the name box: when the other one comes in later, the chosen one fainted."""
        fight = new_fight("Crustle")
        _idx, chosen, _why = fight.switch([])
        other = next(m for m in fight.alive() if m is not chosen)
        fight.set_active(chosen.cp)                            # (it came in: its name is in the box)
        see_twice(fight, hp=(0.1, 0.8))
        fight.set_active(other.cp)
        self.assertIs(fight.me, other)
        self.assertIn(chosen.pos, fight.dead)

    def test_a_low_reading_that_stuck_gives_way_to_the_bar(self):
        """22 November, 18:14: 'the HP of Lanturn is not sure (read from its bar 47 time(s), last 31%, taken to be
        6%)' - a low misread had been believed, and a Pokémon never heals, so the bar was not believed again."""
        fight = new_fight()
        see_twice(fight, hp=(0.06, 0.8))                       # (the misread, seen twice)
        self.assertAlmostEqual(fight.my_hp, 0.06)
        fight.see(feat(hp=(0.31, 0.8)))
        self.assertAlmostEqual(fight.my_hp, 0.06)              # one picture: still a misread
        for _ in range(bf.HP_BACK_UP):
            fight.see(feat(hp=(0.31, 0.8)))
        self.assertAlmostEqual(fight.my_hp, 0.31)

    def test_a_noisy_bar_that_stays_higher_is_believed(self):
        """22 November, 19:29: 'last 30%, taken to be 8%' again - the readings of the bar wander a little and
        pictures without one (a question) came in between."""
        fight = new_fight()
        see_twice(fight, hp=(0.08, 0.8))
        for i in range(30):
            fight.see(feat(hp=((0.27, 0.31, 0.33, None)[i % 4], 0.8)))
        self.assertGreater(fight.my_hp, 0.25)

    def test_the_buttons_the_other_way_round(self):
        """The names under Lanturn's buttons were read as 'Thunderbolt / Surf'; the icons of the little game
        showed that the tap on 'Surf' threw Thunderbolt."""
        team = be.load_team()
        fight = bf.Fight([team[2], team[0], team[1]], log=lambda _m: None)
        fight.set_foe("Leafeon", 1459)
        fight.set_buttons("THUNDERBOLT", "SURF")
        self.assertEqual(fight.move_of(1).name, "Surf")
        fight.buttons_swapped(fight.me)
        self.assertEqual((fight.move_of(0).name, fight.move_of(1).name), ("Surf", "Thunderbolt"))
        fight.buttons_swapped(team[0])                         # (another Pokémon: nothing changes)
        self.assertEqual(fight.move_of(0).name, "Surf")

    def test_a_flicker_upwards_is_still_no_healing(self):
        fight = new_fight()
        see_twice(fight, hp=(0.40, 0.8))
        for i in range(30):
            fight.see(feat(hp=(0.55 if i % 2 else 0.40, 0.8)))
        self.assertAlmostEqual(fight.my_hp, 0.40)

    def test_a_name_that_is_not_known_is_read_again_soon(self):
        """'Go, Whiscash!' lay over the name box and 'Awe' was read: the next try came 50 pictures (seconds)
        later, and all that time the bot took the Abomasnow that had left for the foe."""
        fight = new_fight("Abomasnow")
        fight.foe_every = 50
        fight.set_foe("Awe", 1485)
        for _ in range(bf.FOE_RETRY):
            fight.see(feat(hp=(0.9, 0.9)))
        self.assertTrue(fight.foe_due)

    def test_an_attack_that_costs_no_more_than_a_lit_one_is_ready_too(self):
        """Only Sky Attack was seen lit, the engine wanted Shadow Ball - both cost 50, so Shadow Ball was ready
        as well.  The bot tapped Sky Attack while its fast attacks were tapped on Shadow Ball's button: Shadow
        Ball went off and its little game was swiped as a Sky Attack (only NICE!).  Now Shadow Ball is thrown."""
        fight = new_fight("Whiscash")
        fight.set_buttons("SHADOW BALL", "SKY ATTACK")
        see_twice(fight, hp=(0.5, 0.9), lit=(False, True), shields={"me": 0, "foe": 0})
        self.assertEqual(be.pick_charged(fight.me, fight.foe, fight.energy, 0, fight.foe.hp)[0].name, "Shadow Ball")
        button, move, why = fight.throw()
        self.assertEqual((button, move.name), (0, "Shadow Ball"), why)
        self.assertIn("ready: it costs no more than Sky Attack", why)

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

    def test_what_is_lit_is_thrown_before_we_go_down(self):
        """The first recorded fight, picture 41: Noctowl at 17 % with both buttons lit against a Cramorant at
        31 % with two shields.  The plan says 'farm it down with the fast attack' (ten more of them) - but
        Noctowl does not live that long.  Its energy would be lost; a charged attack costs the foe a shield."""
        fight = new_fight()
        see_twice(fight, hp=(0.17, 0.31), lit=(True, True))
        self.assertEqual(be.pick_charged(fight.me, fight.foe, fight.energy, 2, fight.foe.hp)[0], None)
        button, move, why = fight.throw()
        self.assertIn("before we go down", why)
        self.assertEqual(move.id, max(fight.me.charged, key=lambda m: be.damage(m, fight.me, fight.foe)).id)
        self.assertEqual(fight.move_of(button).id, move.id)

    def test_not_thrown_early_when_the_foe_is_as_good_as_down(self):
        fight = new_fight()
        see_twice(fight, hp=(0.10, 0.05), lit=(True, True))      # two more fast attacks finish it: go on with those
        self.assertIsNone(fight.throw())

    def test_going_down_takes_the_dearer_button_only_when_it_is_lit(self):
        fight = new_fight()
        see_twice(fight, hp=(0.12, 0.31), lit=(True, False))
        cheap = min(fight.me.charged, key=lambda m: m.energy)
        if fight.move_of(0).id != cheap.id:                      # (only the cheaper move can be lit alone)
            fight.slots = [cheap.id, next(m.id for m in fight.me.charged if m.id != cheap.id)]
        fight.lit = (True, False)
        button, move, _why = fight.throw()
        self.assertEqual((button, move.id), (0, cheap.id))


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

    def test_a_hit_worth_it_gets_the_shield_also_the_last_one(self):
        fight = new_fight()
        fight.see(feat(hp=(1.0, 1.0)))
        use, why = fight.shield()
        self.assertTrue(use, why)                            # (Surf: 40% of our HP)
        self.assertEqual(fight.my_shields, 1)
        use, why = fight.shield()
        self.assertTrue(use, why)
        self.assertEqual(fight.my_shields, 0)
        self.assertEqual(fight.shield(), (False, "no shields left"))

    def test_keeps_the_shield_for_a_small_hit(self):
        fight = new_fight()
        fight.foe = be.Mon("medicham", fast="COUNTER", charged=["POWER_UP_PUNCH"])
        fight.see(feat(hp=(1.0, 1.0)))
        use, why = fight.shield()
        self.assertFalse(use, why)
        self.assertEqual(fight.my_shields, 2)

    def test_keeps_the_shield_for_the_next_pokemon_when_this_one_is_nearly_finished(self):
        fight = new_fight()
        see_twice(fight, hp=(0.12, 0.80))
        use, why = fight.shield()
        self.assertFalse(use, why)
        self.assertIn("next Pokémon", why)
        self.assertEqual(fight.my_shields, 2)
        use, why = fight.shield(ready=True)                  # (unless its own charged attack is ready)
        self.assertTrue(use, why)

    def test_the_last_pokemon_is_always_saved(self):
        fight = new_fight()
        fight.dead.update({1, 2})
        see_twice(fight, hp=(0.05, 0.80))
        use, why = fight.shield()
        self.assertTrue(use, why)
        self.assertIn("our last Pokémon", why)

    def test_the_foes_last_pokemon(self):
        """Nothing to keep the shield for: a hit that would be let through otherwise is shielded."""
        fight = new_fight()
        fight.foe = be.Mon("medicham", fast="COUNTER", charged=["POWER_UP_PUNCH"])
        fight.me = fight.team[1]                             # (Power-Up Punch: 17% of Lapras' HP)
        fight.see(feat(hp=(1.0, 1.0)))
        self.assertFalse(fight.shield(foes=2)[0])
        self.assertFalse(fight.shield()[0])                  # (how many the foe has left is not known)
        use, why = fight.shield(foes=1)
        self.assertTrue(use, why)

    def test_foe_not_known(self):
        """Its attack is taken for a hit of nearly half our HP."""
        fight = new_fight(foe=None)
        fight.see(feat(hp=(0.9, 1.0)))
        self.assertTrue(fight.shield()[0])
        fight = new_fight(foe=None)
        see_twice(fight, hp=(0.1, 1.0))                      # (hardly anything left to save)
        use, why = fight.shield()
        self.assertFalse(use, why)

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
        best, _score = be.best_switch([m for m in fight.team if m.pos != 0], fight.foe, 2, 2)
        idx, mon, why = fight.switch([])
        self.assertIsNone(idx)
        self.assertEqual(mon, best)                      # (still the best one, not simply the first)
        self.assertIn("party order", why)
        self.assertEqual(fight.tile, (best.pos - 1, 2))  # ... and where its tile is: the tiles are in party order

    def test_one_tile_read_and_the_other_one_is_better(self):
        """The CP numbers on the tiles are small: often only one is read.  The Pokémon whose number was not
        read is still a choice (before, the one that happened to be read was taken)."""
        for foe in ("Beedrill", "Ampharos", "Slowbro", "Garchomp"):
            fight = new_fight(foe)
            left = [m for m in fight.team if m.pos != 0]
            best, _score = be.best_switch(left, fight.foe, fight.my_shields, fight.foe_shields)
            other = next(m for m in left if m is not best)
            idx, mon, why = fight.switch([(other.cp, 570 if other.pos == 1 else 1195)])
            self.assertEqual(mon, best, foe)
            self.assertIsNone(idx, foe)                  # (its own tile was not read ...)
            self.assertEqual(fight.tile, (best.pos - 1, 2), foe)     # ... so it is tapped by its place
            self.assertIn("party order", why, foe)
            fight = new_fight(foe)                       # (a new fight: the same team again)
            idx, mon, why = fight.switch([(best.cp, 570 if best.pos == 1 else 1195)])
            self.assertEqual((idx, mon.pos), (0, best.pos), foe)
            self.assertIn("by CP", why, foe)

    def test_the_last_one_is_on_its_own_tile_of_two(self):
        """With one left the game sends it in without asking - so when the question comes, our count was wrong
        and two tiles are shown: the last one is on its own place among them (never the middle)."""
        fight = new_fight("Beedrill")
        fight.dead = {1}
        idx, mon, _why = fight.switch([])
        self.assertEqual(mon, fight.team[2])
        self.assertEqual(fight.tile, (1, 2))

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


with open(os.path.join(HERE, "fixtures", "fight", "features_day.json"), encoding="utf-8") as f:
    DAY = json.load(f)
DAY_FIRST = 181                                             # (the number of the first picture in the recording)


class ReplayByDay(unittest.TestCase):
    """The second recorded fight, in an arena by day (features_day.json: pictures 181 to 293 of that recording,
    one every 1.6 s).  White clouds stand where the name boxes and the countdown are; with the readers of that
    day the bot saw a fight before it began, at least seven charged attacks that were not there, no switch question
    and no result screen."""

    LIT = [195, 227, 268, 269, 270, 280, 281, 282]          # pictures with (both) buttons really lit
    QUESTIONS = {204: "attack", 235: "switch", 236: "switch", 237: "switch", 240: "attack", 241: "attack",
                 242: "attack", 249: "attack", 259: "attack", 260: "attack", 261: "attack", 284: "attack",
                 285: "attack", 286: "attack"}

    def at(self, picture):
        return DAY[picture - DAY_FIRST]

    def run_fight(self):
        """What the loop knows besides the pictures: the names it reads in the foe's name box, our Pokémon
        that came in after the switch question (238) and the last one, which came in by itself (253)."""
        fight = new_fight("Slowbro")
        events = {225: lambda: fight.set_foe("Ampharos", 1499), 235: lambda: fight.switch([]),
                  238: lambda: fight.set_active(1489), 253: lambda: fight.set_active(1494),
                  267: lambda: fight.set_foe("Slowbro", 1496), 278: lambda: fight.set_foe("Garchomp", 1472)}
        trace = {}
        for i, f in enumerate(DAY):
            picture = DAY_FIRST + i
            if picture in events:
                events[picture]()
            if bf.state(f) in ("fight", "other"):
                fight.see(f)
            trace[picture] = (fight.foe_shields, fight.my_shields, fight.me.label, fight.my_hp)
        return fight, trace

    def test_the_fight_starts_at_go(self):
        states = {DAY_FIRST + i: bf.state(f) for i, f in enumerate(DAY)}
        self.assertEqual({states[p] for p in range(181, 191)}, {"other"})      # VS screen, 'Go, Noctowl!', 3-2-1
        self.assertEqual(states[191], "fight")
        self.assertEqual([p for p, st in states.items() if st == "result"], [292, 293])

    def test_buttons_are_lit_only_when_they_are(self):
        lit = [DAY_FIRST + i for i, f in enumerate(DAY) if any(f["ready"])]
        self.assertEqual(lit, self.LIT)
        for p in self.LIT:
            self.assertEqual(self.at(p)["ready"], [True, True], p)

    def test_every_question_is_seen_with_its_kind(self):
        seen = {DAY_FIRST + i: f["count"] for i, f in enumerate(DAY) if f["ring"]}
        self.assertEqual(seen, self.QUESTIONS)
        self.assertTrue(self.at(204)["hex"])                                    # the shield question
        self.assertFalse(any(self.at(p)["hex"] for p in self.QUESTIONS if p != 204))

    def test_no_hp_bar_while_our_charged_attack_runs(self):
        # 'Get Ready!' and the little games: 197-201 (Shadow Ball), 213-217, 228-231, 272-275 (Thunderbolt)
        for p in list(range(197, 202)) + list(range(213, 218)) + list(range(228, 232)) + list(range(272, 276)):
            self.assertEqual(self.at(p)["hp"], [None, None], p)
            self.assertTrue(self.at(p)["hud"], p)

    def test_get_ready_is_seen_before_the_little_games(self):
        seen = [DAY_FIRST + i for i, f in enumerate(DAY) if f["get_ready"]]
        self.assertEqual(seen, [213, 228])           # (the two that were on a picture: 213 fading in, 228 full)

    def test_shields_are_counted_from_clear_pictures_only(self):
        fight, trace = self.run_fight()
        for p in range(191, 209):                    # (banners over the name boxes at 202 and 207: still two each)
            self.assertEqual(trace[p][:2], (2, 2), p)
        self.assertEqual(trace[211][:2], (1, 1))     # each side used one (the icons turned dark)
        self.assertEqual(trace[227][:2], (0, 0))     # ... and the second one
        self.assertEqual((fight.foe_shields, fight.my_shields), (0, 0))

    def test_who_is_on_the_field(self):
        _fight, trace = self.run_fight()
        self.assertIn("Noctowl", trace[234][2])
        self.assertIn("Lapras", trace[240][2])
        self.assertIn("Lanturn", trace[256][2])
        self.assertIn("Lanturn", trace[289][2])


with open(os.path.join(HERE, "fixtures", "fight", "features_day2.json"), encoding="utf-8") as f:
    DAY2 = json.load(f)
DAY2_FIRST = 20


class ReplayOfTheLateAttacks(unittest.TestCase):
    """The third recorded fight (features_day2.json: pictures 20 to 138 of that recording).  The bot fought it
    itself and lost it by a hair: its charged attacks came a turn or two late (it waited for the white ring of a
    button), the little game of an attack that had to wait for the other side's was not played at all, the
    switch question was not answered in the three seconds it stayed, and it fought on to the last second."""

    READY = {30: [True, True], 47: [True, True], 64: [True, True], 76: [True, True], 108: [True, True],
             119: [True, False]}                              # (30 and 119: the white ring is not there yet)
    QUESTIONS = {33: "attack", 77: "switch", 78: "switch", 81: "attack", 82: "attack", 83: "attack", 92: "attack",
                 93: "attack", 94: "attack", 103: "attack", 104: "attack", 105: "attack", 130: "attack",
                 131: "attack", 132: "attack"}

    def at(self, picture):
        return DAY2[picture - DAY2_FIRST]

    def run_fight(self, until=10 ** 6):
        """What the loop knows besides the pictures: the names it reads, our Pokémon after the switch question
        (the game chose Lapras: the question was not answered in time) and the last one, which came in by
        itself."""
        fight = new_fight("Slowbro")
        events = {73: lambda: fight.set_foe("Dragalge", 1482), 77: lambda: fight.switch([]),
                  79: lambda: fight.set_active(1489), 87: lambda: fight.set_foe("Hitmonchan", 1487),
                  97: lambda: fight.set_active(1494), 117: lambda: fight.set_foe("Dragalge", 1482)}
        for i, f in enumerate(DAY2):
            picture = DAY2_FIRST + i
            if picture > until:
                break
            if picture in events:
                events[picture]()
            if bf.state(f) in ("fight", "other"):
                fight.see(f)
        return fight

    def test_a_button_is_ready_before_its_ring_is_there(self):
        ready = {DAY2_FIRST + i: f["ready"] for i, f in enumerate(DAY2) if any(f["ready"])}
        self.assertEqual(ready, self.READY)

    def test_get_ready_is_seen_before_each_little_game_that_was_recorded(self):
        seen = [DAY2_FIRST + i for i, f in enumerate(DAY2) if f["get_ready"]]
        self.assertEqual(seen, [38, 121])            # (38: twelve seconds after the tap - theirs went first)
        for p in seen:
            self.assertEqual(self.at(p)["hp"], [None, None], p)
            self.assertEqual(bf.state(self.at(p)), "fight", p)

    def test_every_question_is_seen_with_its_kind(self):
        seen = {DAY2_FIRST + i: f["count"] for i, f in enumerate(DAY2) if f["ring"]}
        self.assertEqual(seen, self.QUESTIONS)
        self.assertTrue(self.at(33)["hex"])                                     # the one shield question on a picture

    def test_who_can_still_fight_is_read_from_the_poke_balls(self):
        self.assertEqual(self.at(30)["balls"], {"me": [3, 0], "foe": [3, 0]})
        self.assertEqual(self.at(79)["balls"], {"me": [2, 1], "foe": [2, 1]})   # Noctowl and Slowbro fainted
        self.assertEqual(self.at(101)["balls"], {"me": [1, 2], "foe": [2, 1]})  # our last one against two
        self.assertEqual(self.at(128)["balls"], {"me": [1, 2], "foe": [1, 2]})  # the last ones of both sides
        self.assertIsNone(self.at(130)["balls"])                                # (a question: no name boxes)

    def test_the_last_attack_ends_the_fight_and_the_bot_can_know_it(self):
        """Picture 130: 'No Protect Shields remaining!' - Lanturn is our last Pokémon and a third of its HP is
        left: Dragalge's hardest attack takes more than that, its Aqua Tail does not.  Which one comes is not
        known, so the fight goes on (until 22 November it was given up here)."""
        fight = self.run_fight(until=129)
        self.assertEqual(fight.me.species, "lanturn")
        self.assertEqual(fight.my_shields, 0)
        self.assertEqual(len(fight.alive()), 1)
        self.assertAlmostEqual(fight.my_hp, 0.32, delta=0.03)
        self.assertEqual(fight.doomed(), (False, ""))
        self.assertIn("Dragalge's Aqua Tail does", fight.fights_on())

    def test_no_attack_is_the_end_while_others_can_still_fight(self):
        for until in (32, 80, 91):                   # the questions on Noctowl and on Lapras
            fight = self.run_fight(until=until)
            self.assertEqual(fight.doomed(), (False, ""), until)

    def test_one_against_two_is_not_given_up_while_the_duel_can_be_won(self):
        """Pictures 97 to 115: Lanturn, our last one, against Hitmonchan with Dragalge still waiting.  Lanturn
        wins that duel (it did), so the fight goes on."""
        for until in (99, 101, 108):
            fight = self.run_fight(until=until)
            self.assertEqual(len(fight.alive()), 1, until)
            self.assertEqual(fight.hopeless(2), (False, ""), until)


with open(os.path.join(HERE, "fixtures", "fight", "features_day3.json"), encoding="utf-8") as f:
    DAY3 = json.load(f)
DAY3_FIRST = 24


class ReplayOfTheFirstWin(unittest.TestCase):
    """The fourth recorded fight (features_day3.json: pictures 24 to 118 of that recording), the first one the
    bot won.  Three times the other side threw a charged attack while we had a shield.  The first was shielded;
    at the second and the third the bot tapped NOT NOW on purpose: one shield was left and the rule of the
    duel simulator keeps the last one for a hit that would knock the Pokémon out.  Dark Pulse took 36% of
    Noctowl's HP, Megahorn 61% of Lanturn's, and the battle ended with the shield unused.  And then the bot
    stood in front of 'YOU WIN!': that screen has no NEXT BATTLE button."""

    def at(self, picture):
        return DAY3[picture - DAY3_FIRST]

    def run_fight(self, until=10 ** 6, on=None):
        """What the loop knows besides the pictures: the names it reads and, at picture 91, that Lanturn is on
        the field (the switch question was answered between two pictures of the recording).  on: {picture:
        what to do there with the fight}."""
        fight = new_fight("Scolipede")
        events = {30: lambda: fight.set_foe("Mismagius", 1460), 75: lambda: fight.set_foe("Dusknoir", 1386),
                  87: lambda: fight.set_foe("Scolipede", 1375), 91: lambda: fight.set_active(1494)}
        for i, f in enumerate(DAY3):
            picture = DAY3_FIRST + i
            if picture > until:
                break
            if picture in events:
                events[picture]()
            if bf.state(f) in ("fight", "other"):
                fight.see(f)
            if on and picture in on:
                on[picture](fight)
        return fight

    def test_the_questions_are_on_the_pictures(self):
        hexes = [DAY3_FIRST + i for i, f in enumerate(DAY3) if f["hex"] and not f["hud"]]
        self.assertEqual(hexes, [41, 58, 94])                # (41 and 94: the countdown is still sliding in)
        self.assertEqual({DAY3_FIRST + i: f["count"] for i, f in enumerate(DAY3) if f["ring"]}, {58: "attack"})

    def test_every_attack_that_is_worth_it_gets_a_shield(self):
        said = {}

        def ask(picture, foes):
            def do(fight):
                said[picture] = (fight.my_shields,) + fight.shield(foes)
            return do
        fight = self.run_fight(on={41: ask(41, 3), 58: ask(58, 3), 94: ask(94, 1)})
        self.assertEqual(said[41][0], 2)
        self.assertTrue(said[41][1], said[41])
        self.assertEqual(said[58][0], 1)                     # the second question: one shield left ...
        self.assertTrue(said[58][1], said[58])               # ... and it is used
        self.assertIn("of our HP", said[58][2])
        # (in the recording that shield was not used: the icons of the name box bring it back for the replay)
        self.assertEqual(said[94][0], 1)
        self.assertTrue(said[94][1], said[94])
        self.assertIn("Megahorn would take 61% of our HP", said[94][2])
        self.assertEqual(fight.me.species, "lanturn")

    def test_what_the_old_rule_said(self):
        """The duel rule of the engine, with what the fight knew at each question."""
        said = {}

        def ask(picture):
            def do(fight):
                said[picture] = be.should_shield(fight.foe, fight.me, fight.my_shields, None, fight.me.hp)[0]
                if picture == 41:
                    fight.my_shields -= 1                    # (that one was used)
            return do
        self.run_fight(on={41: ask(41), 58: ask(58), 94: ask(94)})
        self.assertEqual(said, {41: True, 58: False, 94: False})

    def test_the_banner_of_their_attack_names_it(self):
        """'Mismagius used Dark Pulse!' (pictures 45 and 46): not one of the two attacks that were guessed for a
        Mismagius.  From then on the bot knows what hits it."""
        said = {}

        def banner(fight):
            self.assertEqual([m.name for m in fight.foe.charged], ["Shadow Ball", "Mystical Fire"])
            self.assertEqual(fight.foe_used("LI Mismagius used Dark Pulse! Ne 4").name, "Dark Pulse")

        def ask(fight):
            said["why"] = fight.shield(3)[1]
        self.run_fight(until=58, on={41: lambda fight: fight.shield(3), 45: banner, 58: ask})
        self.assertIn("Dark Pulse would take 36% of our HP", said["why"])

    def test_who_can_still_fight(self):
        self.assertEqual(self.at(49)["balls"], {"me": [3, 0], "foe": [3, 0]})
        self.assertEqual(self.at(79)["balls"], {"me": [3, 0], "foe": [2, 1]})   # Mismagius fainted
        self.assertEqual(self.at(92)["balls"], {"me": [2, 1], "foe": [1, 2]})   # Noctowl and Dusknoir too
        fight = self.run_fight(until=92)
        self.assertEqual(len(fight.alive()), 2)

    def test_get_ready_is_seen_before_each_of_the_five_little_games(self):
        self.assertEqual([DAY3_FIRST + i for i, f in enumerate(DAY3) if f["get_ready"]], [33, 50, 66, 79, 103])
        self.assertEqual({DAY3_FIRST + i: f["ready"] for i, f in enumerate(DAY3) if any(f["ready"])},
                         {49: [True, True], 65: [True, True]})

    def test_the_result_of_a_win_is_known_by_its_check_mark(self):
        results = [DAY3_FIRST + i for i, f in enumerate(DAY3) if bf.state(f) == "result"]
        self.assertEqual(results, [115, 116, 117, 118])
        for p in results:
            self.assertFalse(self.at(p)["result"], p)        # (no NEXT BATTLE)
            self.assertTrue(self.at(p)["done"], p)


class TheirAttackIsNamed(unittest.TestCase):
    """foe_used: the banner of a charged attack, as the text reader gave it on pictures of real fights."""

    def test_the_attack_takes_the_place_of_a_guess(self):
        logs = []
        fight = bf.Fight(be.load_team(), log=logs.append)
        fight.set_foe("Mismagius", 1460)
        self.assertEqual([m.id for m in fight.foe.charged], ["SHADOW_BALL", "MYSTICAL_FIRE"])
        for text in ("pe: Mismagius used Dark Pulse!", "Misinagius uscd Dark Pulse! )@ 4",
                     "Se Mismagius uscd Dark Pulse! Bh"):
            self.assertEqual(fight.foe_used(text).id, "DARK_PULSE", text)
        self.assertEqual([m.id for m in fight.foe.charged], ["DARK_PULSE", "SHADOW_BALL"])
        self.assertEqual(len([m for m in logs if "used Dark Pulse" in m]), 1)       # (said once)
        self.assertIn("the guess was Shadow Ball, Mystical Fire", "\n".join(logs))

    def test_our_own_banner_and_other_banners_change_nothing(self):
        fight = bf.Fight(be.load_team(), log=lambda _m: None)
        fight.set_foe("Mismagius", 1460)
        for text in ("AE Noctowl used Shadow Ball! dub", "pie < Nociowl used Shadow dail! e4", "Go, Mismagius!",
                     "Attack incoming!", "Get Ready!", "", "Mismagius used", "used Dark Pulse!",
                     "Mismagius used Hydro Cannon!"):                               # (not an attack it can have)
            self.assertIsNone(fight.foe_used(text), text)
        self.assertEqual([m.id for m in fight.foe.charged], ["SHADOW_BALL", "MYSTICAL_FIRE"])
        fight.foe = None
        self.assertIsNone(fight.foe_used("Mismagius used Dark Pulse!"))

    def test_an_attack_that_was_guessed_right_stays(self):
        logs = []
        fight = bf.Fight(be.load_team(), log=logs.append)
        fight.set_foe("Scolipede", 1375)
        guess = sorted(m.id for m in fight.foe.charged)
        self.assertEqual(fight.foe_used("pe Scolipede used Megahorn! pes").id, "MEGAHORN")
        self.assertEqual(sorted(m.id for m in fight.foe.charged), guess)
        self.assertFalse([m for m in logs if "used Megahorn" in m])                 # (nothing new: nothing said)

    def test_it_is_remembered_when_the_foe_comes_back(self):
        logs = []
        fight = bf.Fight(be.load_team(), log=logs.append)
        fight.set_foe("Mismagius", 1460)
        fight.foe_used("Mismagius used Dark Pulse!")
        fight.set_foe("Scolipede", 1375)
        fight.set_foe("Mismagius", 1460)
        self.assertEqual(fight.foe.charged[0].id, "DARK_PULSE")
        self.assertIn("(as seen before)", logs[-1])

    def test_the_same_species_on_both_sides_tells_nothing(self):
        fight = bf.Fight(be.load_team(), log=lambda _m: None)
        fight.set_foe("Lanturn", 1490)
        self.assertIsNone(fight.foe_used("Lanturn used Surf!"))                     # (theirs or ours?)


class TheFoesEnergy(unittest.TestCase):
    """How much energy the foe has at most: nothing when it comes in, what its fastest fast attack gives in the
    time that is fought, less what its charged attacks cost.  An attack that costs more is not the one that is
    coming - which is how a cheap attack that is thrown to draw a shield is told from the hard one."""

    KNOWN = {"whiscash": {"MUD_BOMB": 3, "BLIZZARD": 2, "SCALD": 1}}

    def fight(self, foe="Whiscash", known=None):
        logs = []
        known = {k: dict(v) for k, v in (self.KNOWN if known is None else known).items()}    # (a fight adds to it)
        fight = bf.Fight(be.load_team(), log=logs.append, known=known)
        if foe:
            fight.set_foe(foe, 1496)
        fight.set_buttons("SHADOW BALL", "SKY ATTACK")
        return fight, logs

    def test_it_comes_in_with_nothing_and_gains_with_the_seconds(self):
        fight, _logs = self.fight()
        self.assertEqual(fight.foe_energy(), 9)                  # (the one fast attack that may be under way)
        fight.fought(5.0)
        self.assertEqual(fight.foe_energy(), 54)                 # Mud Shot: 9 a second
        fight.fought(20.0)
        self.assertEqual(fight.foe_energy(), 100)                # (never more than 100)

    def test_the_first_foe_has_been_there_from_the_start(self):
        """Its name is read a second or two into the fight: its energy counts from the first second."""
        fight, _logs = self.fight(foe=None)
        self.assertIsNone(fight.foe_energy())
        fight.fought(6.0)
        fight.set_foe("Whiscash", 1496)
        self.assertEqual(fight.foe_energy(), 63)

    def test_the_shield_is_kept_for_the_bait_and_used_on_the_blizzard(self):
        """The fifth recorded battle, with what earlier battles had shown of a Whiscash (Mud Bomb, Blizzard)."""
        fight, logs = self.fight()
        self.assertEqual([m.id for m in fight.foe.charged], ["MUD_BOMB", "BLIZZARD"])
        self.assertIn("(as seen before)", logs[0])
        fight.see(feat(hp=(0.97, 0.83)))
        fight.fought(6.5)                                        # the attack came about seven seconds in
        use, why = fight.shield(3)
        fight.foe_threw()
        self.assertFalse(use, why)
        self.assertIn("it can only be Mud Bomb (Blizzard costs 75 energy, Whiscash has 67 at most)", why)
        self.assertEqual(fight.my_shields, 2)
        self.assertEqual(fight.foe_used("Whiscash used Mud Bomb!").id, "MUD_BOMB")
        self.assertAlmostEqual(fight.foe_energy(), 58.5 - 45 + 9, delta=0.1)   # 13 left at most (+ one fast attack)
        fight.fought(9.7)                                        # ten seconds of fight later: the next one
        self.assertEqual(fight.foe_energy(), 100)
        use, why = fight.shield(3)
        self.assertTrue(use, why)
        self.assertIn("Blizzard would take", why)

    def test_without_knowing_its_attacks_the_guess_decides(self):
        """The recommended moveset of a Whiscash has Scald (50 energy) where this one had Blizzard: after seven
        seconds Scald is possible, and Scald hurts - the shield goes.  That is what happened; what the banners
        of that battle showed is kept for the next Whiscash."""
        fight, _logs = self.fight(known={})
        self.assertEqual([m.id for m in fight.foe.charged], ["MUD_BOMB", "SCALD"])
        fight.fought(6.5)
        use, why = fight.shield(3)
        fight.foe_threw()
        self.assertTrue(use, why)
        self.assertIn("Scald would take", why)
        self.assertFalse(fight.learned)
        fight.foe_used("Whiscash used Mud Bomb!")
        fight.fought(9.7)
        fight.foe_threw()
        fight.foe_used("Whiscash used Blizzard!")
        self.assertTrue(fight.learned)
        self.assertEqual(fight.known, {"whiscash": {"MUD_BOMB": 1, "BLIZZARD": 1}})
        again = bf.Fight(be.load_team(), log=lambda _m: None, known=fight.known)     # the next battle
        again.set_foe("Whiscash", 1490)
        self.assertEqual(sorted(m.id for m in again.foe.charged), ["BLIZZARD", "MUD_BOMB"])

    def test_an_attack_is_counted_once_a_battle(self):
        fight, _logs = self.fight(known={})
        for _ in range(3):
            fight.foe_threw()
            fight.foe_used("Whiscash used Mud Bomb!")
        self.assertEqual(fight.known, {"whiscash": {"MUD_BOMB": 1}})

    def test_what_this_battle_shows_goes_before_what_earlier_ones_did(self):
        fight, _logs = self.fight()                              # (earlier: Mud Bomb 3x, Blizzard 2x, Scald 1x)
        fight.foe_threw()
        fight.foe_used("Whiscash used Scald!")
        self.assertEqual([m.id for m in fight.foe.charged], ["SCALD", "MUD_BOMB"])
        self.assertEqual(fight.known["whiscash"]["SCALD"], 2)

    def test_an_attack_that_is_not_one_of_the_species_is_not_taken_from_the_file(self):
        fight, _logs = self.fight(known={"whiscash": {"HYDRO_CANNON": 9, "BLIZZARD": 1}})
        self.assertEqual([m.id for m in fight.foe.charged], ["BLIZZARD", "MUD_BOMB"])

    def test_the_real_cost_of_the_attack_comes_off(self):
        fight, _logs = self.fight()
        fight.fought(10.0)                                       # 90 (+9: 99)
        fight.foe_threw()                                        # (taken for the cheapest: 45)
        self.assertAlmostEqual(fight.foe_energy(), 90 - 45 + 9, delta=0.1)
        fight.foe_used("Whiscash used Blizzard!")                # it was the one of 75
        self.assertAlmostEqual(fight.foe_energy(), 90 - 75 + 9, delta=0.1)
        fight.foe_used("Whiscash used Blizzard!")                # (the banner is read more than once: counted once)
        self.assertAlmostEqual(fight.foe_energy(), 90 - 75 + 9, delta=0.1)

    def test_the_margin_is_added_once_however_many_attacks_were_thrown(self):
        fight, _logs = self.fight()
        for _ in range(3):
            fight.fought(6.0)                                    # 54 more
            fight.foe_threw()
            fight.foe_used("Whiscash used Mud Bomb!")            # 45 less
        self.assertAlmostEqual(fight.foe_energy(), 3 * (54 - 45) + 9, delta=0.1)

    def test_a_question_that_was_not_read_takes_nothing_off(self):
        """The ring of a question was seen and its words were not read: the bot answers it as a shield question,
        but an attack may not have been thrown at all.  What is kept is the MOST the foe can have, so nothing
        comes off - until the banner says which attack it was."""
        fight, _logs = self.fight()
        fight.fought(6.0)
        fight.foe_threw(sure=False)
        self.assertEqual(fight.foe_energy(), 63)
        fight.fought(1.0)
        self.assertEqual(fight.foe_energy(), 72)
        fight.foe_used("Whiscash used Mud Bomb!")                # it was one after all
        self.assertAlmostEqual(fight.foe_energy(), 7 * 9 - 45 + 9, delta=0.1)

    def test_a_count_that_is_proven_wrong_is_not_used_any_more(self):
        """It threw Blizzard when it could not have had 75 energy by our count: the clock missed something."""
        fight, logs = self.fight()
        fight.fought(3.0)                                        # 27 (+9)
        fight.foe_threw()
        fight.foe_used("Whiscash used Blizzard!")
        self.assertIsNone(fight.foe_energy())
        self.assertIn("its energy is not counted any more", "\n".join(logs))
        fight.see(feat(hp=(0.9, 0.8)))
        use, why = fight.shield(3)                               # (as before: the hardest one it has)
        self.assertTrue(use, why)
        self.assertIn("Blizzard would take", why)

    def test_a_name_box_that_changed_is_an_unknown_foe(self):
        fight, _logs = self.fight()
        fight.fought(5.0)
        fight.read_names("me")                                   # (our own box: the foe is still the foe)
        self.assertEqual(fight.foe_energy(), 54)
        fight.read_names("foe")
        self.assertIsNone(fight.foe_energy())                    # who is it now?
        fight.set_foe("Whiscash", 1496)                          # still the Whiscash
        self.assertEqual(fight.foe_energy(), 54)

    def test_a_new_foe_starts_at_nothing_and_the_old_one_keeps_what_it_had(self):
        fight, _logs = self.fight()
        fight.fought(4.0)                                        # Whiscash: 36
        fight.read_names("foe")                                  # the box changes here ...
        fight.fought(1.5)
        fight.set_foe("Samurott", 1500)                          # ... and is read a second and a half later
        self.assertAlmostEqual(fight.foe_energy(), 1.5 * 8.0 + 10, delta=0.1)      # Samurott: from when it came
        fight.fought(30.0)
        fight.read_names("foe")
        fight.set_foe("Whiscash", 1496)                          # the Whiscash is back: with what it had
        self.assertAlmostEqual(fight.foe_energy(), 36 + 9, delta=0.1)

    def test_a_new_foe_that_came_in_unnoticed_has_been_there_since_the_last_look(self):
        """Its name box was not seen to change (the names are read again every few seconds): it may have come in
        right after the last time the old one was read there - its energy counts from then."""
        fight, _logs = self.fight()
        fight.fought(4.0)
        fight.set_foe("Whiscash", 1496)                          # read again: still the Whiscash
        fight.fought(5.0)
        fight.set_foe("Samurott", 1500)                          # and now a Samurott, without a sign
        self.assertAlmostEqual(fight.foe_energy(), 5.0 * 8.0 + 10, delta=0.1)

    def test_a_name_that_was_misread_for_a_moment_does_not_empty_the_count(self):
        """'Whiscash' is read as another Pokémon on one picture and as Whiscash again two seconds later: it never
        left, and it gained energy all the time."""
        fight, _logs = self.fight()
        fight.fought(4.0)                                        # 36
        fight.read_names("foe")
        fight.set_foe("Samurott", 1500)                          # (misread)
        fight.fought(2.0)
        fight.read_names("foe")
        fight.set_foe("Whiscash", 1496)
        self.assertAlmostEqual(fight.foe_energy(), 6.0 * 9 + 9, delta=0.1)

    def test_giving_up_counts_only_what_the_foe_could_throw(self):
        """'No Protect Shields remaining!' on our last Pokémon: the Blizzard would end it, the Mud Bomb would
        not - and five seconds after it came in a Whiscash can only have the Mud Bomb."""
        fight, _logs = self.fight()
        fight.dead.update({1, 2})
        fight.my_shields = 0
        for _ in range(3):
            fight.see(feat(hp=(0.6, 0.8), shields={"me": 0, "foe": 2}))
        fight.fought(5.0)
        fight.foe_threw()                                        # (the question is up)
        self.assertEqual(fight.doomed(), (False, ""))
        late, _logs = self.fight()
        late.dead.update({1, 2})
        late.my_shields = 0
        for _ in range(3):
            late.see(feat(hp=(0.1, 0.8), shields={"me": 0, "foe": 2}))      # (16 HP: Mud Bomb ends it as well)
        late.fought(12.0)
        late.foe_threw()
        lost, why = late.doomed()
        self.assertTrue(lost, why)
        self.assertIn("Blizzard", why)
        self.assertEqual(late.fights_on(), "")
        self.assertRegex(fight.fights_on(), r"^Whiscash's Mud Bomb does \d+, Noctowl has \d+ HP "
                                            r"\(its other attack costs more energy than it can have\)$")

    def test_why_a_fight_is_not_given_up(self):
        """For the log: a lost end that was played out has to be understood afterwards."""
        fight, _logs = self.fight(foe=None)
        self.assertEqual(fight.fights_on(), "the foe is not known")
        fight.set_foe("Whiscash", 1496)
        self.assertEqual(fight.fights_on(), "we have 2 shield(s) left by our count")
        fight.my_shields = 0
        self.assertEqual(fight.fights_on(), "3 of ours can still fight by our count")
        fight.dead.update({1, 2})
        self.assertRegex(fight.fights_on(), r"^the HP of Noctowl is not sure \(read from its bar 0 time\(s\), ")
        for _ in range(3):
            fight.see(feat(hp=(0.6, 0.8), shields={"me": 0, "foe": 2}))
        fight.fought(12.0)
        self.assertRegex(fight.fights_on(), r"^Whiscash's Mud Bomb does 19, Noctowl has 97 HP$")   # (Blizzard would
        for _ in range(3):                                                                      # end it, Mud Bomb not)
            fight.see(feat(hp=(0.1, 0.8), shields={"me": 0, "foe": 2}))
        self.assertEqual(fight.fights_on(), "")                  # (now it is: either attack ends it)
        self.assertTrue(fight.doomed()[0])


class Aim(unittest.TestCase):
    """The charged attack that is thrown the moment it is ready: the fast attacks are tapped on its button."""

    def lanturn(self, foe):
        team = be.load_team()
        fight = bf.Fight([team[2], team[0], team[1]], log=lambda _m: None)      # Lanturn: Surf 45, Thunderbolt 55
        if foe:
            fight.set_foe(foe, 1500)
        fight.set_buttons("SURF", "THUNDERBOLT")
        return fight

    def test_no_aim_while_the_buttons_are_not_known(self):
        fight = bf.Fight(be.load_team(), log=lambda _m: None)
        fight.set_foe("Cramorant", 1493)
        self.assertIsNone(fight.aim())
        fight.set_buttons("SHADOW BALL", "SKY ATTACK")
        self.assertIsNotNone(fight.aim())

    def test_the_aim_is_what_throw_would_throw(self):
        """Whatever the engine throws the moment a button lights up is what the aim is on."""
        for foe in ("Cramorant", "Slowbro", "Dragalge", "Hitmonchan", "Azumarill", "Registeel", ""):
            for shields in (0, 1, 2):
                for hp in (1.0, 0.5, 0.15):
                    fight = self.lanturn(foe)
                    fight.foe_shields = shields
                    fight.foe_hp = hp
                    if fight.foe:
                        fight.foe.hp = int(hp * fight.foe.max_hp)
                    aim = fight.aim()
                    costs = sorted({m.energy for m in fight.me.charged})
                    thrown = None
                    for cost in costs:                       # the buttons light up one after the other
                        fight.lit = tuple(fight.move_of(i).energy <= cost for i in (0, 1))
                        thrown = fight.throw()
                        if thrown:
                            break
                    case = (foe, shields, hp)
                    if aim is None:                          # (nothing is thrown early: the cheap one only when
                        if thrown:                           # the dear one is ready too)
                            self.assertLess(thrown[1].energy, cost, case)
                    else:
                        self.assertIsNotNone(thrown, case)
                        self.assertEqual((thrown[0], thrown[1].id), (aim[0], aim[1].id), case)
                        self.assertEqual(aim[1].energy, cost, case)

    def test_saving_up_for_the_dear_attack_aims_at_its_button(self):
        fight = self.lanturn("Slowbro")
        picks = {45: (None, "building up to Thunderbolt"), 55: (fight.me.charged[1], "the best attack")}
        real = be.pick_charged
        be.pick_charged = lambda me, foe, energy, *a: picks[energy]
        try:
            self.assertEqual(fight.aim()[0], 1)              # (taps on it are fast attacks until it is ready)
            fight.my_hp = 0.9                                # (another state: worked out again)
            picks[55] = (fight.me.charged[0], "Surf as bait")
            self.assertIsNone(fight.aim())                   # the cheap one, but only when the dear one is ready
            fight.my_hp = 0.8
            picks[45] = (fight.me.charged[0], "Surf finishes it")
            self.assertEqual(fight.aim()[0], 0)
        finally:
            be.pick_charged = real

    def test_the_other_way_round_on_the_screen(self):
        """The aim is on the button the attack is on - whatever the order in the party."""
        fight = self.lanturn("")
        want = fight.aim()
        self.assertEqual((want[0], want[1].id), (0, "SURF"))
        team = be.load_team()
        other = bf.Fight([team[2], team[0], team[1]], log=lambda _m: None)
        other.set_buttons("THUNDERBOLT", "SURF")
        self.assertEqual((other.aim()[0], other.aim()[1].id), (1, "SURF"))

    def test_about_to_faint_anything_goes(self):
        fight = self.lanturn("Slowbro")
        real = be.pick_charged
        be.pick_charged = lambda *a: (None, "farming down with the fast move is quickest")
        try:
            self.assertIsNone(fight.aim())
            see_twice(fight, hp=(0.05, 0.9))
            aim = fight.aim()
            self.assertEqual(aim[1].id, "SURF")              # (what lights up first)
        finally:
            be.pick_charged = real

    def test_a_new_pokemon_has_no_aim_until_its_buttons_are_read(self):
        fight = new_fight("Slowbro")
        self.assertIsNotNone(fight.aim())
        fight.switch([])
        self.assertIsNone(fight.aim())


class WhoIsOnTheField(unittest.TestCase):
    """The Poké Balls of our name box and the CP in it, after the switch question ran out."""

    def balls(self, red, hp=(None, None)):
        f = feat(hp=hp, shields={"me": 0, "foe": 0})
        f["balls"] = {"me": [red, 3 - red], "foe": [3, 0]}
        return f

    def test_the_game_chose_the_other_one(self):
        """The bot tapped Lanturn when the countdown was over; the game had put Lapras in.  The HP that is read
        meanwhile is Lapras's: Lanturn keeps its own."""
        fight = new_fight("Dragalge")
        noctowl, lapras, lanturn = fight.team
        for _ in range(3):
            fight.see(self.balls(2))
        fight.faint()
        fight._enter(lanturn)                                 # (what the bot thinks)
        for _ in range(3):
            fight.see(self.balls(2, hp=(0.50, 0.9)))          # Lapras took a hit meanwhile
        fight.set_active(lapras.cp)                           # the name box: it is Lapras
        self.assertIs(fight.me, lapras)
        self.assertAlmostEqual(fight.my_hp, 0.50, delta=0.02)
        self.assertEqual(lanturn.hp, lanturn.max_hp)          # (not the 50 % that was read)
        self.assertEqual(fight.dead, {0})

    def test_a_grey_ball_brings_the_last_one_in(self):
        fight = new_fight("Dragalge")
        noctowl, lapras, lanturn = fight.team
        fight.faint()
        fight._enter(lapras)
        for _ in range(3):
            fight.see(self.balls(2, hp=(0.26, 0.9)))
        logs = []
        fight.log = logs.append
        fight.see(self.balls(1))                              # Lapras faints from a charged attack: no HP bar
        self.assertIs(fight.me, lapras)                       # (one picture is not enough)
        fight.see(self.balls(1))
        self.assertIs(fight.me, lanturn)
        self.assertEqual(fight.dead, {0, 1})
        self.assertIn("another Poké Ball of ours is grey - Shadow Lapras fainted, Lanturn is on the field", logs[0])
        self.assertEqual(fight.my_hp, 1.0)

    def test_two_grey_balls_at_once(self):
        """The bot comes to a fight that is half over (or missed a faint): two Poké Balls are grey, nobody was
        counted as fainted and the name box shows our last one.  The one in the box is the one on the field."""
        fight = new_fight("Dragalge")
        noctowl, lapras, lanturn = fight.team
        fight.see(self.balls(1, hp=(0.32, 0.28)))
        fight.set_active(lanturn.cp)                          # the name box: Lanturn
        self.assertIs(fight.me, lanturn)
        fight.see(self.balls(1, hp=(0.32, 0.28)))
        fight.see(self.balls(1, hp=(0.32, 0.28)))
        self.assertIs(fight.me, lanturn)
        self.assertEqual(fight.dead, {0, 1})
        self.assertEqual(len(fight.alive()), 1)

    def test_the_old_name_in_the_box_does_not_bring_the_fainted_one_back(self):
        """The ball turns grey a second or two before the name in the box changes: a reading of that box in
        between still gives the CP of the one that fainted."""
        fight = new_fight("Dragalge")
        noctowl, lapras, lanturn = fight.team
        fight.foe_every = 50                                  # (the live video: five seconds)
        fight.faint()
        fight._enter(lapras)
        for _ in range(3):
            fight.see(self.balls(2, hp=(0.26, 0.9)))
        fight.see(self.balls(1))
        fight.see(self.balls(1))
        self.assertIs(fight.me, lanturn)
        fight.set_active(lapras.cp)                           # the box still says 'Lapras CP 1489'
        self.assertIs(fight.me, lanturn)
        self.assertEqual(fight.dead, {0, 1})
        fight.set_active(lanturn.cp)
        self.assertIs(fight.me, lanturn)

    def test_a_mix_up_is_put_right_when_the_name_box_keeps_saying_so(self):
        fight = new_fight("Dragalge")
        noctowl, lapras, lanturn = fight.team
        fight.foe_every = 3
        fight.dead = {0, 2}                                   # (the bot took Lanturn for fainted: it was Lapras)
        fight._enter(lapras)
        for _ in range(6):
            fight.see(self.balls(1, hp=(0.9, 0.9)))
        fight.set_active(lanturn.cp)
        self.assertIs(fight.me, lanturn)
        self.assertEqual(fight.dead, {0, 1})


class GivingUp(unittest.TestCase):
    def last_one(self, foe="Dragalge", hp=0.06, foe_hp=0.85):
        fight = new_fight(foe)
        fight.dead = {1, 2}                                   # (Lapras and Lanturn fainted: Noctowl is the last)
        fight.my_shields = fight.foe_shields = 0
        for _ in range(3):                                    # (a big change is believed at the second picture)
            fight.see(feat(hp=(hp, foe_hp), shields={"me": 0, "foe": 0}))
        return fight

    def test_the_hp_has_to_be_read_from_its_own_bar(self):
        """A Pokémon that has just come in has the HP that was kept for it - which may be wrong after a mix-up
        (in a replay a full Lanturn was taken for one with 12 HP).  Nothing is given up on that."""
        fight = self.last_one(hp=0.20)
        self.assertTrue(fight.doomed()[0])
        fight._enter(fight.me)                                # (it came in: nothing read yet)
        self.assertEqual(fight.doomed(), (False, ""))
        self.assertEqual(fight.hopeless(2), (False, ""))
        fight.see(feat(hp=(0.20, 0.85), shields={"me": 0, "foe": 0}))
        self.assertEqual(fight.doomed(), (False, ""))         # (one reading is not enough)
        fight.see(feat(hp=(0.20, 0.85), shields={"me": 0, "foe": 0}))
        self.assertTrue(fight.doomed()[0])

    def test_an_attack_that_knocks_out_our_last_pokemon(self):
        fight = self.last_one(hp=0.20)                        # (32 HP: Aqua Tail 37 and Outrage 87 - either ends it)
        lost, why = fight.doomed()
        self.assertTrue(lost)
        self.assertIn("Noctowl is our last Pokémon", why)
        self.assertIn("no shield", why)

    def test_not_when_its_weaker_attack_would_be_survived(self):
        """22 November, 18:17: given up on a Frenzy Plant (138) with 73 HP, while the Serperior had just shown
        Leaf Tornado, which costs the same.  Which one comes is not known: only when both end it is it over."""
        fight = self.last_one(hp=0.30)                        # (49 HP: Outrage 87 would end it, Aqua Tail 37 not)
        lost, why = fight.fights_on() == "", fight.fights_on()
        self.assertFalse(lost)
        self.assertEqual(fight.doomed(), (False, ""))
        self.assertIn("Aqua Tail does 37", why)

    def test_not_while_there_is_a_shield_another_pokemon_or_enough_hp(self):
        fight = self.last_one(hp=0.30)
        fight.my_shields = 1
        self.assertEqual(fight.doomed(), (False, ""))
        fight = self.last_one(hp=0.30)
        fight.dead = {1}
        self.assertEqual(fight.doomed(), (False, ""))
        fight = self.last_one(hp=1.0)                         # (Outrage does not take all of a full Noctowl)
        self.assertEqual(fight.doomed(), (False, ""))
        fight = self.last_one(foe="", hp=0.05)                # (the foe is not known: nothing is known)
        self.assertEqual(fight.doomed(), (False, ""))

    def test_an_hp_that_was_not_read_in_the_plain_fight_gives_nothing_up(self):
        """Our bar under the banner of the question read as 6 % in a replay (it was 77 %): what is believed then
        is not what was read in the plain fight, and nothing is given up on it."""
        fight = self.last_one(hp=0.77)
        self.assertEqual(fight.doomed(), (False, ""))
        for _ in range(3):                                    # the question: no name boxes, a sliver of the bar
            fight.see(feat(hp=(0.06, None), hud=False, ring=True))
        self.assertAlmostEqual(fight.my_hp, 0.06, delta=0.01)
        self.assertEqual(fight.doomed(), (False, ""))
        self.assertEqual(fight.hopeless(2), (False, ""))

    def test_one_against_two_and_the_duel_is_lost(self):
        fight = self.last_one(hp=0.06, foe_hp=0.85)
        lost, why = fight.hopeless(2)
        self.assertTrue(lost)
        self.assertIn("loses to Dragalge", why)
        self.assertIn("1 more is waiting", why)
        self.assertIn("2 more are waiting", fight.hopeless(3)[1])

    def test_one_against_one_is_fought_out(self):
        fight = self.last_one(hp=0.06, foe_hp=0.85)
        self.assertEqual(fight.hopeless(1), (False, ""))

    def test_not_hopeless_while_it_is_not_our_last_or_the_duel_can_be_won(self):
        fight = self.last_one(hp=0.06, foe_hp=0.85)
        fight.dead = {1}
        self.assertEqual(fight.hopeless(2), (False, ""))
        fight = self.last_one(hp=1.0, foe_hp=0.10)
        self.assertEqual(fight.hopeless(2), (False, ""))
        fight = self.last_one(foe="", hp=0.05)
        self.assertEqual(fight.hopeless(3), (False, ""))

    def test_what_is_not_known_counts_for_us(self):
        """Our energy is taken just short of the next charged attack - with a button lit, just short of the
        other one - and the foe's as zero: a duel that is lost even so is lost."""
        fight = self.last_one(hp=0.19, foe_hp=0.45, foe="Slowbro")
        fight.foe_shields = 0
        seen = []
        real = be.simulate
        be.simulate = lambda me, foe, a, b: seen.append((me.energy, foe.energy)) or (0.0, 0.5)
        try:
            fight.lit = (False, False)
            fight.hopeless(2)
            fight.lit = (True, True)
            fight.hopeless(2)
        finally:
            be.simulate = real
        self.assertEqual(seen, [(49, 0), (100, 0)])


if __name__ == "__main__":
    unittest.main()
