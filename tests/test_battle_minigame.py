"""Unit tests for battle_minigame (the little game of a charged attack: find the icons, plan the swipes).
Run: python3 -m unittest discover -s tests

fixtures/minigame/*.jpg are real pictures of the little game (flying, electric, water, ghost) and one of the fight
itself with both charged attack buttons lit (a lit button looks like an icon of its type)."""
import math
import os
import sys
import unittest

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import battle_minigame as bm  # noqa: E402

W, H = 352, 440


def fixture(name):
    img = cv2.imread(os.path.join(HERE, "fixtures", "minigame", name + ".jpg"))
    assert img is not None, name
    return img


def picture(icons, kind="water", background=(60, 40, 25), middle=True, radius=bm.ICON_R):
    """A night scene with icons of a type drawn on it: discs in the type colour with a white drawing."""
    img = np.zeros((H, W, 3), np.uint8)
    img[:] = background
    r, g, b = bm.TYPE_RGB[kind]
    for x, y in icons:
        c = (int(round(x * W)), int(round(y * H)))
        cv2.circle(img, c, int(round(radius * W)), (b, g, r), -1, cv2.LINE_AA)
        if middle:
            cv2.circle(img, c, int(round(radius * W * 0.35)), (255, 255, 255), -1, cv2.LINE_AA)
    return img


def near(found, want, tol=0.02):
    """Every wanted point has a found one close by, and there are no others."""
    return len(found) == len(want) and all(any(bm._dist(p, q) <= tol for q in found) for p in want)


class FindIcons(unittest.TestCase):
    def test_drawn_icons_of_every_type(self):
        want = [(0.25, 0.40), (0.55, 0.55), (0.80, 0.75)]
        for kind in bm.TYPE_RGB:
            found = bm.find_icons(picture(want, kind), kind)
            self.assertTrue(near(found, want), (kind, found))

    def test_other_types_are_not_found(self):
        img = picture([(0.3, 0.5), (0.6, 0.6)], "water")
        self.assertEqual(bm.find_icons(img, "electric"), [])
        self.assertEqual(bm.find_icons(img, "fire"), [])

    def test_unknown_type_or_no_picture(self):
        self.assertEqual(bm.find_icons(picture([(0.5, 0.5)]), "banana"), [])
        self.assertEqual(bm.find_icons(None, "water"), [])

    def test_a_field_of_the_colour_is_no_icon(self):
        r, g, b = bm.TYPE_RGB["flying"]                 # a pale sky in the colour of the flying icons
        sky = np.zeros((H, W, 3), np.uint8)
        sky[:] = (b, g, r)
        self.assertEqual(bm.find_icons(sky, "flying"), [])
        big = picture([(0.5, 0.6)], "water", radius=3 * bm.ICON_R)       # a blue Lapras is no water icon
        self.assertEqual(bm.find_icons(big, "water"), [])

    def test_a_disc_without_the_white_drawing_is_no_icon(self):
        self.assertEqual(bm.find_icons(picture([(0.5, 0.6)], "ghost", middle=False), "ghost"), [])

    def test_nothing_above_the_name_boxes(self):
        img = picture([(0.5, 0.12), (0.5, 0.60)], "electric")
        self.assertTrue(near(bm.find_icons(img, "electric"), [(0.5, 0.60)]))

    def test_icons_that_touch_are_found_one_by_one(self):
        want = [(0.30 + i * 0.135, 0.60) for i in range(4)]            # a stream: 0.135 apart, 0.13 across
        self.assertTrue(near(bm.find_icons(picture(want, "water"), "water"), want))

    def test_real_pictures(self):
        self.assertTrue(near(bm.find_icons(fixture("flying"), "flying"),
                             [(0.93, 0.46), (0.42, 0.38), (0.55, 0.49), (0.28, 0.31), (0.80, 0.78), (0.67, 0.80)], 0.03))
        self.assertTrue(near(bm.find_icons(fixture("electric"), "electric"),
                             [(0.55, 0.54), (0.67, 0.66), (0.55, 0.78), (0.44, 0.90)], 0.03))
        # (the water icons are in front of a blue Lapras)
        self.assertTrue(near(bm.find_icons(fixture("water"), "water"),
                             [(0.74, 0.38), (0.87, 0.34), (0.65, 0.48), (0.56, 0.65), (0.48, 0.84)], 0.03))
        self.assertTrue(near(bm.find_icons(fixture("ghost"), "ghost"), [(0.30, 0.79), (0.40, 0.77), (0.50, 0.79)], 0.03))

    def test_real_pictures_have_no_icons_of_other_types(self):
        for name, others in (("flying", ("electric", "fire", "grass")), ("electric", ("water", "ghost", "flying")),
                             ("ghost", ("electric", "fire", "grass"))):
            for kind in others:
                self.assertEqual(bm.find_icons(fixture(name), kind), [], (name, kind))

    def test_a_lit_button_looks_like_an_icon(self):
        # the fight itself, both buttons lit (Shadow Ball: ghost, Sky Attack: flying): this is why the fight loop
        # leaves out what it finds at a lit button
        ghost = bm.find_icons(fixture("fight"), "ghost")
        flying = bm.find_icons(fixture("fight"), "flying")
        self.assertTrue(near(ghost, [(0.307, 0.816)], 0.04), ghost)
        self.assertTrue(near(flying, [(0.690, 0.816)], 0.04), flying)
        self.assertEqual(bm.find_icons(fixture("fight"), "water"), [])


class Geometry(unittest.TestCase):
    def test_distance_is_in_screen_widths(self):
        self.assertAlmostEqual(bm._dist((0.2, 0.5), (0.5, 0.5)), 0.3)
        self.assertAlmostEqual(bm._dist((0.5, 0.2), (0.5, 0.6)), 0.4 * bm.ASPECT)

    def test_groups(self):
        pts = [(0.42, 0.56), (0.62, 0.56), (0.30, 0.90), (0.40, 0.88), (0.50, 0.90)]
        grp = sorted(bm.groups(pts), key=len)
        self.assertEqual([len(g) for g in grp], [2, 3])
        self.assertEqual(grp[1], [(0.30, 0.90), (0.40, 0.88), (0.50, 0.90)])     # in the order of the row

    def test_smooth_line(self):
        line = [(0.9, 0.3), (0.8, 0.4), (0.7, 0.52), (0.6, 0.66)]
        self.assertTrue(bm._smooth(line))
        self.assertFalse(bm._smooth([(0.2, 0.5), (0.4, 0.7), (0.5, 0.45), (0.7, 0.7)]))    # a zigzag
        self.assertFalse(bm._smooth([(0.1, 0.5), (0.6, 0.5)]))                             # too far apart

    def test_simplify(self):
        line = [(0.2, 0.5), (0.4, 0.5), (0.6, 0.5), (0.8, 0.5)]
        self.assertEqual(bm._simplify(line, 0.03), [(0.2, 0.5), (0.8, 0.5)])
        bent = [(0.2, 0.5), (0.5, 0.5), (0.5, 0.8)]
        self.assertEqual(bm._simplify(bent, 0.03), bent)

    def test_distance_to_a_line_piece(self):
        row = (0.3, 0.5, 0.7, 0.5)
        self.assertAlmostEqual(bm._near_line((0.5, 0.5), row), 0.0)
        self.assertAlmostEqual(bm._near_line((0.5, 0.6), row), 0.1 * bm.ASPECT)
        self.assertAlmostEqual(bm._near_line((0.8, 0.5), row), 0.1)


def inside(swipes):
    return all(0.0 <= v <= 1.0 for s in swipes for v in s[:4]) and all(s[1] >= bm.TOP and s[3] >= bm.TOP for s in swipes)


def crosses(swipe, p, q):
    """Does a swipe cross the line piece p - q?"""
    def side(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    a, b = swipe[:2], swipe[2:4]
    return side(a, b, p) * side(a, b, q) < 0 and side(p, q, a) * side(p, q, b) < 0


class Stream:
    """Icons that move in a line: one comes in every `gap` seconds at `start` and moves on with `speed`."""

    def __init__(self, start, speed, gap=0.165, life=1.2):
        self.start, self.speed, self.gap, self.life = start, speed, gap, life

    def at(self, t):
        out = []
        for i in range(60):
            age = t - i * self.gap
            if 0 <= age <= self.life:
                out.append((self.start[0] + self.speed[0] * age, self.start[1] + self.speed[1] * age))
        return out


class Plans(unittest.TestCase):
    def test_nothing_before_the_icons_can_be_there(self):
        self.assertEqual(bm.Game("water", t0=100.0).plan(101.0), [])

    def test_known_stream_types_swipe_their_gate(self):
        for kind in ("water", "flying", "electric"):
            game = bm.Game(kind, t0=100.0)
            plan = game.plan(100.0 + bm.START + 0.1)
            gate = bm.KNOWN[kind]["gates"][0]
            self.assertEqual(len(plan), bm.GATE_TIMES)
            self.assertEqual(plan[0][:4], gate)
            self.assertEqual(plan[1][:4], gate[2:] + gate[:2])            # there and back
            self.assertTrue(inside(plan))
            self.assertTrue(all(s[4] >= bm.MIN_MS for s in plan))

    def test_ghost_swipes_its_rows(self):
        plan = bm.Game("ghost", t0=0.0).plan(bm.START + 0.1)
        self.assertEqual(len(plan), 3)
        for row, swipe in zip(bm.KNOWN["ghost"]["rows"], plan):
            for x in (row[0], row[2]):                                    # every icon of the row lies on the swipe
                self.assertLessEqual(bm._near_line((x, row[1]), swipe[:4]), 0.01)

    def test_unknown_type_starts_with_the_star(self):
        plan = bm.Game("fire", t0=0.0).plan(bm.START + 0.1)
        self.assertEqual([s[:4] for s in plan], bm.STAR)

    def test_swipe_time_follows_the_length(self):
        s = bm._swipe((0.2, 0.5), (0.7, 0.5))
        self.assertEqual(s[4], int(round(0.5 / bm.SPEED * 1000)))
        self.assertEqual(bm._swipe((0.5, 0.5), (0.5, 0.5))[4], bm.MIN_MS)

    def test_swipes_stay_on_the_screen(self):
        s = bm._swipe((-0.2, 0.05), (1.3, 1.2))
        self.assertTrue(inside([s]))

    def test_a_stream_of_an_unknown_type_gets_a_gate(self):
        stream = Stream((1.0, 0.35), (-0.55, 0.45))                       # from the top right to the bottom left
        game = bm.Game("fire", t0=0.0)
        t = 3.0
        while t < 4.6:
            game.see(t, stream.at(t - 3.0))
            t += 0.1
        self.assertIsNotNone(game.gate)
        plan = game.plan(t)
        self.assertEqual(len(plan), bm.GATE_TIMES)
        # the gate lies across the stream: it crosses the line the icons move along
        p, q = stream.start, (stream.start[0] + stream.speed[0] * 1.2, stream.start[1] + stream.speed[1] * 1.2)
        self.assertTrue(crosses(plan[0], p, q), (plan[0], p, q))
        self.assertTrue(inside(plan))
        learned = game.learned()
        self.assertEqual(learned["gates"], [game.gate])
        nxt = bm.Game("fire", t0=0.0, learned=learned)                    # the next game of this type starts with it
        self.assertEqual(nxt.plan(bm.START + 0.1)[0][:4], game.gate)

    def test_before_the_gate_is_found_the_icons_themselves_are_swiped(self):
        stream = Stream((1.0, 0.35), (-0.55, 0.45))
        game = bm.Game("fire", t0=0.0)
        for i in range(3):
            game.see(3.0 + 0.1 * i, stream.at(0.4 + 0.1 * i))
        icons = stream.at(0.6)
        plan = game.plan(3.25)
        self.assertIsNone(game.gate)
        for p in icons:
            self.assertTrue(any(bm._near_line(p, s[:4]) <= bm.ICON_R for s in plan), (p, plan))

    def test_a_row_that_stands_still_is_learned_and_visited_again(self):
        row = [(0.30, 0.60), (0.42, 0.60), (0.54, 0.60)]
        game = bm.Game("steel", t0=0.0)
        for i in range(5):
            game.see(3.0 + 0.1 * i, row)
        self.assertEqual(len(game.learned()["rows"]), 1)
        for i in range(5, 9):
            game.see(3.0 + 0.1 * i, [(0.70, 0.40), (0.82, 0.40)])          # the icons flash up somewhere else
        plan = game.plan(3.9)
        for p in row + [(0.70, 0.40), (0.82, 0.40)]:                       # both places are swiped
            self.assertTrue(any(bm._near_line(p, s[:4]) <= 0.02 for s in plan), (p, plan))
        self.assertEqual(game.plan(3.0 + bm.ROW_LIFE + 5.0), [])           # (long after: the game is over)

    def test_a_repeated_picture_does_not_stop_a_stream(self):
        stream = Stream((1.0, 0.5), (-0.78, 0.0))
        game = bm.Game("fire", t0=0.0)
        t = 3.0
        while t < 4.2:
            icons = stream.at(t - 3.0)
            game.see(t, icons)
            game.see(t + 0.05, icons)                                     # the video gave the same picture twice
            t += 0.1
        self.assertEqual(game.learned()["rows"], [])
        self.assertIsNotNone(game.gate)

    def test_moving_or_standing_still(self):
        game = bm.Game("fire", t0=0.0)
        row = [(0.3, 0.6), (0.42, 0.6)]
        game.see(1.0, row)
        self.assertIsNone(game.moving(row))                               # one picture tells nothing
        for i in range(1, 4):
            game.see(1.0 + 0.1 * i, row)
        self.assertIs(game.moving(row), False)
        moved = [(0.36, 0.6), (0.48, 0.6)]
        game.see(1.4, moved)
        self.assertIs(game.moving(moved), True)
        new = [(0.7, 0.3), (0.82, 0.3)]
        game.see(1.5, new)
        self.assertIsNone(game.moving(new))                               # icons that have only just appeared

    def test_the_game_is_over(self):
        game = bm.Game("water", t0=0.0)
        self.assertFalse(game.over(5.0))
        self.assertTrue(game.over(bm.GAME_SECONDS + 0.1))                  # nothing seen: only the clock ends it
        game.see(3.0, [(0.5, 0.5)])
        self.assertFalse(game.over(3.0 + bm.QUIET - 0.1))
        self.assertTrue(game.over(3.0 + bm.QUIET + 0.1))                   # the icons are gone
        self.assertEqual(game.plan(3.0 + bm.QUIET + 0.1), [])
        game.see(5.0, [(0.5, 0.5)])                                        # (they were only hidden for a moment)
        self.assertFalse(game.over(5.1))

    def test_an_attack_that_has_to_wait_swipes_only_what_is_seen(self):
        game = bm.Game("water", t0=100.0)
        game.hold(101.0)                                                   # the other side's attack goes first
        for t in (101.5, 103.5, 106.0, 108.9):
            self.assertEqual(game.plan(t), [], t)                          # nothing blind, however long it takes
            self.assertFalse(game.over(t), t)
        self.assertTrue(game.over(101.0 + bm.HOLD + 0.1))                  # ... it is given up in the end
        self.assertEqual(game.plan(101.0 + bm.HOLD + 0.1), [])

    def test_an_attack_that_waited_plays_its_whole_game(self):
        game = bm.Game("water", t0=100.0)
        game.hold(101.0)
        game.hold(105.0)                                                   # (the question was on screen until here)
        first = 105.0 + bm.HOLD - 1.0                                      # its icons come just before it is given up
        game.see(first, [(0.7, 0.5), (0.6, 0.6)])
        self.assertTrue(game.plan(first + 0.05))
        self.assertTrue(inside(game.plan(first + 0.1)))
        t = first
        while t < first + 5.5:                                             # the icons stay for about six seconds
            t += 0.1
            game.see(t, [(0.7, 0.5), (0.6, 0.6)])
            self.assertFalse(game.over(t), t - first)
        self.assertTrue(game.over(t + bm.QUIET + 0.1))
        game.hold(t)                                                       # (a question after it: nothing changes)
        self.assertTrue(game.blind is False and game.first == first)

    def test_holding_does_not_change_a_game_that_runs(self):
        game = bm.Game("water", t0=100.0)
        game.see(102.8, [(0.7, 0.5), (0.6, 0.6)])
        game.hold(103.0)
        self.assertTrue(game.blind)
        self.assertEqual(game.t0, 100.0)

    def test_known_types_are_not_relearned(self):
        game = bm.Game("ghost", t0=0.0)
        for i in range(5):
            game.see(3.0 + 0.1 * i, [(0.42, 0.56), (0.62, 0.56)])
        self.assertIsNone(game.learned())
        self.assertIsNone(bm.Game("fire", t0=0.0).learned())               # nothing seen: nothing learned

    def test_what_is_known(self):
        self.assertEqual(bm.known("WATER")["gates"], bm.KNOWN["water"]["gates"])
        self.assertEqual(bm.known("fire"), {"gates": [], "rows": []})
        k = bm.known("fire", {"gates": [[0.1, 0.5, 0.9, 0.5]], "rows": []})
        self.assertEqual(k["gates"], [(0.1, 0.5, 0.9, 0.5)])
        # what was learned does not replace what is known from recordings
        self.assertEqual(bm.known("water", {"gates": [[0.1, 0.5, 0.9, 0.5]]})["gates"], bm.KNOWN["water"]["gates"])

    def test_the_gates_from_recordings_are_across_the_screen_part_the_icons_use(self):
        for kind, k in bm.KNOWN.items():
            for line in k.get("gates", []) + k.get("rows", []):
                self.assertTrue(inside([line + (0,)]), (kind, line))
                self.assertGreater(math.hypot(line[2] - line[0], (line[3] - line[1]) * bm.ASPECT), 0.15)


if __name__ == "__main__":
    unittest.main()
