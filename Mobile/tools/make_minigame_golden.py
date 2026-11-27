#!/usr/bin/env python3
"""Makes tests/fixtures/minigame_golden.json.qz (JSON, packed the way qCompress() of Qt does: the length, then zlib):
what battle_minigame.py (the little game of a charged attack) answers, as the file that the C++ port of it
(SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoMinigame.cpp) is tested against.

    python3 tools/make_minigame_golden.py            writes the file
    python3 tools/make_minigame_golden.py --check    says whether the file is what battle_minigame.py answers now
    python3 tools/make_minigame_golden.py --coverage says which lines of battle_minigame.py the cases do not reach

Two kinds of case.  "icons": where find_icons() finds the icons of a type in a picture; the picture is a recipe, not
the picture (a real picture of tests/fixtures/minigame, or one drawn here: discs in the colour of a type with a white
middle on a background, in a size, darker or brighter), and both sides run the steps with OpenCV.  "game": a Game
that is given pictures one after another (see), asked what to swipe (plan), whether it is over, whether icons move,
what it learned, and so on; every step has its answer, and "state" steps say what the Game has noted.  The games are
made up (streams of icons that move along a bend, rows that flash up and stand still, icons all over the place) and
are the same every time (a fixed seed)."""
import json
import math
import os
import random
import struct
import sys
import zlib

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import battle_minigame as bm  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
MINIGAME = os.path.join(FIXTURES, "minigame")
OUT = os.path.join(FIXTURES, "minigame_golden.json.qz")
SEED = 20261129
W, H = 352, 440                       # the size of the pictures of the fixtures
PICTURES = ["electric.jpg", "fight.jpg", "flying.jpg", "ghost.jpg", "water.jpg"]
KINDS = sorted(bm.TYPE_RGB)
KNOWN_KINDS = ["water", "flying", "electric", "ghost"]


# ---- the steps of a recipe (the C++ port has the same ones) -------------------------------------------------
def load(name):
    img = cv2.imread(os.path.join(MINIGAME, name))
    assert img is not None, name
    return img


def run(ops):
    img = None
    for op in ops:
        kind = op[0]
        if kind == "load":
            img = load(op[1])
        elif kind == "blank":
            img = np.full((op[2], op[1], 3), op[3:6], np.uint8)
        elif kind == "size":
            img = cv2.resize(img, (op[1], op[2]), interpolation=op[3])
        elif kind == "scale":
            img = cv2.convertScaleAbs(img, alpha=op[1], beta=op[2])
        elif kind == "fill":
            x0, y0, x1, y1 = op[1:5]
            img[y0:y1, x0:x1] = op[5:8]
        elif kind == "disc":
            cv2.circle(img, (op[1], op[2]), op[3], (op[4], op[5], op[6]), -1)
        else:
            raise ValueError(kind)
    return img


def drawn(kind, icons, w=W, h=H, background=(60, 40, 25), radius=bm.ICON_R, middle=True, ring_only=False):
    """The steps that draw icons of a type (discs in its colour, a white disc in the middle) on a background."""
    r, g, b = bm.TYPE_RGB[kind]
    ops = [["blank", w, h, background[0], background[1], background[2]]]
    for x, y in icons:
        c = (int(round(x * w)), int(round(y * h)))
        ops.append(["disc", c[0], c[1], int(round(radius * w)), b, g, r])
        if ring_only:
            ops.append(["disc", c[0], c[1], int(round(radius * w * 0.6)), background[0], background[1], background[2]])
        elif middle:
            ops.append(["disc", c[0], c[1], int(round(radius * w * 0.35)), 255, 255, 255])
    return ops


def pts(arr):
    return [[float(x), float(y)] for x, y in arr]


def icons_case(ops, kind, top=None, limit=None):
    img = run(ops)
    args = {}
    if top is not None:
        args["top"] = top
    if limit is not None:
        args["limit"] = limit
    found = bm.find_icons(img, kind, **args)
    case = {"case": "icons", "ops": ops, "type": kind, "found": pts(found)}
    if top is not None:
        case["top"] = top
    if limit is not None:
        case["limit"] = limit
    return case


def icon_cases(rng):
    cases = []
    # real pictures, asked about every type: those that are in them are found, the others are not
    for name in PICTURES:
        for kind in KINDS:
            cases.append(icons_case([["load", name]], kind))
    # ... darker, brighter, bigger, smaller, in another way of making a picture
    for name, kind in (("flying.jpg", "flying"), ("electric.jpg", "electric"), ("water.jpg", "water"),
                       ("ghost.jpg", "ghost"), ("fight.jpg", "ghost"), ("fight.jpg", "flying")):
        for extra in ([["scale", 0.8, 0]], [["scale", 1.15, 5]], [["scale", 0.6, 10]],
                      [["size", 704, 880, cv2.INTER_LINEAR]], [["size", 704, 880, cv2.INTER_CUBIC]],
                      [["size", 176, 220, cv2.INTER_AREA]], [["size", 1408, 1760, cv2.INTER_LINEAR]],
                      [["size", 300, 300, cv2.INTER_AREA]], [["size", 400, 10, cv2.INTER_AREA]]):
            cases.append(icons_case([["load", name]] + extra, kind))
    # drawn: every type, a few icons at random places, three backgrounds, three sizes
    backgrounds = [(60, 40, 25), (20, 20, 20), (90, 120, 60), (200, 190, 180)]
    for kind in KINDS:
        for n, (w, h) in enumerate(((W, H), (2 * W, 2 * H), (W // 2, H // 2), (W, H), (W, H))):
            count = rng.randint(1, 6)
            icons = [(rng.uniform(0.12, 0.88), rng.uniform(0.15, 0.92)) for _ in range(count)]
            bg = backgrounds[(n + len(kind)) % len(backgrounds)]
            cases.append(icons_case(drawn(kind, icons, w, h, bg), kind))
    # drawn: what is no icon, and what is
    for kind in ("water", "ghost", "fire", "flying", "dragon", "dark"):
        cases.append(icons_case(drawn(kind, [(0.5, 0.6)], middle=False), kind))                    # no white middle
        cases.append(icons_case(drawn(kind, [(0.5, 0.6)], ring_only=True), kind))                  # a ring
        cases.append(icons_case(drawn(kind, [(0.5, 0.6)], radius=3 * bm.ICON_R), kind))            # a big disc
        cases.append(icons_case(drawn(kind, [(0.5, 0.12), (0.5, 0.6)]), kind))                     # one above the boxes
        cases.append(icons_case(drawn(kind, [(0.5, 0.12), (0.5, 0.6)]), kind, top=0.0))
        cases.append(icons_case(drawn(kind, [(0.5, 0.12), (0.5, 0.6), (0.3, 0.4)]), kind, top=0.5))
        cases.append(icons_case(drawn(kind, [(0.30 + i * 0.135, 0.60) for i in range(4)]), kind))  # touching icons
        cases.append(icons_case(drawn(kind, [(0.30 + i * 0.07, 0.60) for i in range(4)]), kind))   # overlapping
        many = [(0.08 + 0.12 * (i % 7), 0.30 + 0.11 * (i // 7)) for i in range(14)]
        cases.append(icons_case(drawn(kind, many), kind))                                          # more than 12
        cases.append(icons_case(drawn(kind, many), kind, limit=3))
        cases.append(icons_case(drawn(kind, [(0.5, 0.6)], radius=0.5 * bm.ICON_R), kind))          # small ones
    # drawn: at the edges of the thresholds.  A channel of the disc that is 42 from the colour of the type is still
    # that colour, 43 is not; the middle counts as white from 190 in every channel (the picture is made smaller, a
    # field of one colour stays what it is)
    for kind in ("water", "fire", "ghost"):
        r, g, b = bm.TYPE_RGB[kind]
        cx, cy = W // 2, int(H * 0.6)
        radius = int(round(bm.ICON_R * W))
        for channel in range(3):
            for delta in (-43, -42, 42, 43):
                bgr = [b, g, r]
                bgr[channel] = min(max(bgr[channel] + delta, 0), 255)
                ops = [["blank", W, H, 60, 40, 25], ["disc", cx, cy, radius] + bgr,
                       ["disc", cx, cy, int(round(radius * 0.35)), 255, 255, 255]]
                cases.append(icons_case(ops, kind))
        for white in ([189] * 3, [190] * 3, [191] * 3, [255, 255, 189], [190, 255, 255], [255, 189, 255]):
            ops = [["blank", W, H, 60, 40, 25], ["disc", cx, cy, radius, b, g, r],
                   ["disc", cx, cy, int(round(radius * 0.35))] + white]
            cases.append(icons_case(ops, kind))
    # a field of the colour: no icon
    for kind in ("flying", "water", "grass"):
        cases.append(icons_case([["blank", W, H] + list(reversed(bm.TYPE_RGB[kind]))], kind))
    # darker or brighter versions of drawn pictures
    for kind in ("water", "electric", "ghost", "fire"):
        base = drawn(kind, [(0.3, 0.5), (0.6, 0.6), (0.8, 0.8)])
        for extra in ([["scale", 0.85, 0]], [["scale", 1.1, 0]], [["scale", 0.7, 0]]):
            cases.append(icons_case(base + extra, kind))
    # an unknown type, and nothing
    cases.append(icons_case(drawn("water", [(0.5, 0.5)]), "banana"))
    return cases


# ---- the games ------------------------------------------------------------------------------------------------
def state_of(game):
    return {
        "first": game.first, "last": game.last, "pictures": game.pictures, "icons": game.icons,
        "swipes": game.swipes, "gate": list(game.gate) if game.gate else None,
        "rows": [list(r) + [t] for r, t in game.rows.items()], "trail": len(game.trail), "turn": game.turn,
        "blind": game.blind, "plain": game.plain, "t0": game.t0, "prior": [list(g) for g in game.prior],
        "kind": game.kind, "builtin": game.builtin,
    }


def learned_json(learned):
    if learned is None:
        return None
    return {"rows": [list(r) for r in learned["rows"]], "gates": [list(g) for g in learned["gates"]]}


def play(steps):
    """Runs the steps on a Game; the answers, one for every step."""
    game = None
    answers = []
    for step in steps:
        kind = step[0]
        if kind == "new":
            learned = step[3]
            if learned is not None:
                learned = {"rows": [tuple(r) for r in learned["rows"]], "gates": [tuple(g) for g in learned["gates"]]}
            game = bm.Game(step[1], step[2], learned)
            answers.append(state_of(game))
        elif kind == "see":
            game.see(step[1], [tuple(p) for p in step[2]])
            answers.append(None)
        elif kind == "plan":
            answers.append([list(s) for s in game.plan(step[1])])
        elif kind == "over":
            answers.append(game.over(step[1]))
        elif kind == "hold":
            if len(step) > 2:
                game.hold(step[1], step[2])
            else:
                game.hold(step[1])
            answers.append(None)
        elif kind == "started":
            game.started(step[1])
            answers.append(None)
        elif kind == "plain":
            game.plain = step[1]
            answers.append(None)
        elif kind == "blind":
            game.blind = step[1]
            answers.append(None)
        elif kind == "moving":
            answers.append(game.moving([tuple(p) for p in step[1]]))
        elif kind == "learned":
            answers.append(learned_json(game.learned()))
        elif kind == "state":
            answers.append(state_of(game))
        else:
            raise ValueError(kind)
    return answers


def game_case(steps):
    return {"case": "game", "steps": steps, "answers": play(steps)}


# What is on the screen, made up.
def bezier(p0, p1, p2, u):
    a = (1 - u) ** 2
    b = 2 * (1 - u) * u
    c = u * u
    return (a * p0[0] + b * p1[0] + c * p2[0], a * p0[1] + b * p1[1] + c * p2[1])


def stream_icons(rng, path, t, start, rate=6.0, life=1.0, jitter=0.004, miss=0.1):
    """The icons of a stream at time t: one is born every 1/rate seconds, lives `life` seconds and goes along the
    path."""
    out = []
    n = int(max(t - start, 0) * rate) + 1
    for i in range(n):
        u = (t - start - i / rate) / life
        if 0.0 <= u <= 1.0:
            x, y = bezier(path[0], path[1], path[2], u)
            if rng.random() > miss:
                out.append((round(x + rng.uniform(-jitter, jitter), 4), round(y + rng.uniform(-jitter, jitter), 4)))
    return out


def row_icons(rng, row, t, flashes, count=4, jitter=0.002):
    """The icons of a row that flashes up in `flashes` = [(from, to)]: standing still."""
    for a, b in flashes:
        if a <= t <= b:
            x1, y1, x2, y2 = row
            return [(round(x1 + (x2 - x1) * i / (count - 1) + rng.uniform(-jitter, jitter), 4),
                     round(y1 + (y2 - y1) * i / (count - 1) + rng.uniform(-jitter, jitter), 4)) for i in range(count)]
    return []


def random_path(rng):
    a = (rng.uniform(0.1, 0.9), rng.uniform(0.3, 0.9))
    b = (rng.uniform(0.1, 0.9), rng.uniform(0.3, 0.9))
    c = (rng.uniform(0.1, 0.9), rng.uniform(0.3, 0.9))
    return [a, b, c]


def stream_game(rng, kind, learned=None, hold=False, with_started=True, plain_first=True, path=None, dt=0.15):
    """A game of a stream of icons: the fight loop gives a picture every `dt` seconds or so and asks what to swipe."""
    t0 = round(rng.uniform(0, 50), 3)
    steps = [["new", kind, t0, learned]]
    path = path or random_path(rng)
    steps.append(["plain", plain_first])
    start = t0 + bm.LEAD
    t = t0
    if hold:
        steps.append(["hold", t0 + 0.2])
    started_at = t0 + bm.GET_READY
    did_start = False
    for _ in range(int(11.0 / dt)):
        t = round(t + dt * rng.uniform(0.7, 1.4), 3)
        if with_started and not did_start and t >= started_at:
            steps.append(["started", t])
            did_start = True
            steps.append(["plain", False])
        icons = stream_icons(rng, path, t, start)
        steps.append(["see", t, pts(icons)])
        now = round(t + rng.uniform(0.02, 0.2), 3)
        steps.append(["plan", now])
        steps.append(["over", now])
        if icons and rng.random() < 0.4:
            steps.append(["moving", pts(icons)])
        if rng.random() < 0.2:
            steps.append(["state"])
    steps.append(["learned"])
    steps.append(["state"])
    return steps


def rows_game(rng, kind, rows, learned=None, dt=0.12):
    """Rows of icons that flash up and stand still, every row at its own moments."""
    t0 = round(rng.uniform(0, 50), 3)
    steps = [["new", kind, t0, learned], ["plain", False]]
    start = t0 + bm.LEAD
    flashes = []
    for _row in rows:
        mine = []
        s = start + rng.uniform(0, 0.6)
        while s < start + 5.0:
            mine.append((s, s + 0.5))
            s += rng.uniform(0.6, 1.1)
        flashes.append(mine)
    t = t0
    for _ in range(int(11.0 / dt)):
        t = round(t + dt * rng.uniform(0.8, 1.3), 3)
        icons = []
        for row, mine in zip(rows, flashes):
            icons += row_icons(rng, row, t, mine)
        steps.append(["see", t, pts(icons)])
        now = round(t + rng.uniform(0.02, 0.15), 3)
        steps.append(["plan", now])
        steps.append(["over", now])
        if icons and rng.random() < 0.5:
            steps.append(["moving", pts(icons)])
    steps.append(["learned"])
    steps.append(["state"])
    return steps


def fuzz_game(rng):
    """Anything: pictures with icons all over the place, calls in any order, times that go back and forth."""
    kind = rng.choice(KINDS + ["banana"])
    t0 = round(rng.uniform(0, 30), 3)
    learned = None
    if rng.random() < 0.25:
        learned = {
            "rows": [[round(rng.uniform(0.1, 0.5), 3), round(rng.uniform(0.3, 0.9), 3),
                      round(rng.uniform(0.5, 0.9), 3), round(rng.uniform(0.3, 0.9), 3)] for _ in range(rng.randint(0, 2))],
            "gates": [[round(rng.uniform(0.1, 0.9), 3), round(rng.uniform(0.3, 0.9), 3),
                       round(rng.uniform(0.1, 0.9), 3), round(rng.uniform(0.3, 0.9), 3)] for _ in range(rng.randint(0, 2))],
        }
    steps = [["new", kind, t0, learned]]
    t = t0
    base = pts([(rng.uniform(0.1, 0.9), rng.uniform(0.25, 0.95)) for _ in range(rng.randint(1, 9))])
    for _ in range(rng.randint(12, 40)):
        what = rng.random()
        t = round(t + rng.uniform(0.02, 0.6), 3)
        if what < 0.45:
            if rng.random() < 0.5:        # the same icons again (standing still), a little moved
                icons = [[round(x + rng.uniform(-0.01, 0.01), 4), round(y + rng.uniform(-0.01, 0.01), 4)] for x, y in base]
            else:
                icons = pts([(round(rng.uniform(0.05, 0.95), 4), round(rng.uniform(0.2, 0.97), 4))
                             for _ in range(rng.randint(0, 9))])
            if rng.random() < 0.15:
                icons = icons + icons[:2]                  # the same point twice
            steps.append(["see", t, icons])
        elif what < 0.7:
            steps.append(["plan", round(t + rng.uniform(0, 1.0), 3)])
        elif what < 0.8:
            steps.append(["over", round(t + rng.uniform(0, 12), 3)])
        elif what < 0.85:
            steps.append(["hold", t, rng.choice([bm.HOLD, 5.0, 25.0])] if rng.random() < 0.5 else ["hold", t])
        elif what < 0.9:
            steps.append(["started", t])
        elif what < 0.93:
            steps.append(["plain", rng.random() < 0.5])
        elif what < 0.95:
            steps.append(["blind", rng.random() < 0.5])
        elif what < 0.98:
            steps.append(["moving", base])
        else:
            steps.append(["learned"])
    steps.append(["learned"])
    steps.append(["state"])
    return steps


def spread_game(rng, kind):
    """Icons spread over a strip, so that no single line follows them: the swipes that cover it."""
    t0 = round(rng.uniform(0, 30), 3)
    steps = [["new", kind, t0, None], ["plain", False]]
    t = t0 + bm.LEAD
    cx, cy = rng.uniform(0.3, 0.7), rng.uniform(0.45, 0.8)
    for _ in range(14):
        t = round(t + 0.15, 3)
        count = rng.randint(3, 8)
        angle = rng.uniform(0, math.pi)
        icons = []
        for _i in range(count):
            along = rng.uniform(-0.25, 0.25)
            side = rng.uniform(-0.12, 0.12)
            icons.append((round(min(max(cx + along * math.cos(angle) - side * math.sin(angle), 0.05), 0.95), 4),
                          round(min(max(cy + (along * math.sin(angle) + side * math.cos(angle)) / bm.ASPECT, 0.25), 0.95), 4)))
        steps.append(["see", t, pts(icons)])
        steps.append(["plan", round(t + 0.1, 3)])
        steps.append(["moving", pts(icons)])
    steps.append(["state"])
    return steps


def sequential_rows_game(rng, kind, count, dt=0.1):
    """More rows than a Game keeps: every row flashes up on its own, standing still, one after the other."""
    t0 = round(rng.uniform(0, 50), 3)
    steps = [["new", kind, t0, None], ["plain", False]]
    rows = []
    for i in range(count):
        y = round(0.30 + 0.07 * i, 3)
        x = 0.12 if i % 2 == 0 else 0.55
        rows.append((x, y, round(x + 0.3, 3), y))
    start = t0 + bm.LEAD
    t = t0
    for _ in range(int((count * 0.8 + 4.0) / dt)):
        t = round(t + dt, 3)
        icons = []
        for i, row in enumerate(rows):
            icons += row_icons(rng, row, t, [(start + 0.8 * i, start + 0.8 * i + 0.6)])
        steps.append(["see", t, pts(icons)])
        steps.append(["plan", round(t + 0.05, 3)])
    steps.append(["learned"])
    steps.append(["state"])
    return steps


def flood_game(rng, kind, frames=130, dt=0.1, icons=10):
    """Many more moving icons than a Game keeps of the trail: icons that wander about the screen."""
    t0 = round(rng.uniform(0, 50), 3)
    steps = [["new", kind, t0, None], ["plain", False]]
    spots = [(rng.uniform(0.15, 0.85), rng.uniform(0.35, 0.85)) for _ in range(icons)]
    t = t0
    for n in range(frames):
        t = round(t + dt, 3)
        moved = []
        for x, y in spots:
            angle = rng.uniform(0, 2 * math.pi)
            step = rng.uniform(0.05, 0.09)
            x = min(max(x + step * math.cos(angle), 0.1), 0.9)
            y = min(max(y + step * math.sin(angle) / bm.ASPECT, 0.3), 0.9)
            moved.append((x, y))
        spots = moved
        steps.append(["see", t, pts([(round(x, 4), round(y, 4)) for x, y in spots])])
        if n % 5 == 0:
            steps.append(["plan", round(t + 0.05, 3)])
    steps.append(["state"])
    return steps


def close_game():
    """Icons on top of each other, and a hair apart (a bend after a step too small to have a direction)."""
    steps = [["new", "dark", 10.0, None], ["plain", False]]
    for t, icons in ((13.0, [(0.5, 0.5), (0.5, 0.5), (0.5, 0.58)]),
                     (13.1, [(0.5, 0.5), (0.500005, 0.5), (0.500005, 0.58)]),
                     (13.2, [(0.5, 0.5), (0.5000002, 0.5), (0.5000002, 0.58)]),
                     (13.3, [(0.4, 0.5), (0.4, 0.5), (0.4, 0.5)])):
        steps.append(["see", t, pts(icons)])
        steps.append(["plan", round(t + 0.05, 3)])
        steps.append(["moving", pts(icons)])
    steps.append(["state"])
    return steps


def game_cases(rng):
    cases = []
    # a stream, of every type; the types that are not known get to learn
    learned_by_kind = {}
    for kind in KINDS:
        steps = stream_game(rng, kind)
        case = game_case(steps)
        cases.append(case)
        learned = case["answers"][-2]            # (what the game found: for the next game of this type)
        if learned is not None:
            learned_by_kind[kind] = learned
    for kind, learned in sorted(learned_by_kind.items()):
        cases.append(game_case(stream_game(rng, kind, learned=learned)))
    # known types more than once: other paths, a hold, a start that comes late, the plain fight
    for kind in KNOWN_KINDS:
        for variant in range(6):
            cases.append(game_case(stream_game(
                rng, kind, hold=variant % 2 == 1, with_started=variant % 3 != 2, plain_first=variant % 4 != 3,
                dt=rng.choice([0.1, 0.15, 0.25]),
            )))
    # a stream that goes along a straight line, along the screen, across it
    for path in ([(0.9, 0.35), (0.6, 0.55), (0.3, 0.75)], [(0.15, 0.5), (0.5, 0.5), (0.85, 0.5)],
                 [(0.5, 0.3), (0.5, 0.6), (0.5, 0.9)], [(0.85, 0.85), (0.4, 0.3), (0.1, 0.85)]):
        for kind in ("fire", "water", "dragon"):
            cases.append(game_case(stream_game(rng, kind, path=path)))
    # rows that flash up
    ghost_rows = [(0.42, 0.56, 0.62, 0.56), (0.29, 0.79, 0.50, 0.79), (0.55, 0.79, 0.75, 0.79)]
    for kind in ("ghost", "ghost", "dark", "psychic", "fairy"):
        rows = ghost_rows[:rng.randint(1, 3)]
        cases.append(game_case(rows_game(rng, kind, rows)))
    for _ in range(3):
        rows = [(round(rng.uniform(0.15, 0.4), 3), round(y, 3), round(rng.uniform(0.55, 0.85), 3), round(y, 3))
                for y in (rng.uniform(0.4, 0.5), rng.uniform(0.6, 0.9))]
        cases.append(game_case(rows_game(rng, "ghost", rows)))
        cases.append(game_case(rows_game(rng, "psychic", rows)))
    # spread out icons
    for _ in range(10):
        cases.append(game_case(spread_game(rng, rng.choice(KINDS))))
    # anything
    for _ in range(150):
        cases.append(game_case(fuzz_game(rng)))
    # the limits (a generator of its own: the games above stay what they were)
    more = random.Random(SEED + 1)
    for kind in ("psychic", "dark"):
        case = game_case(sequential_rows_game(more, kind, 12))
        assert len(case["answers"][-1]["rows"]) == 8, "rows are kept up to 8"
        cases.append(case)
    case = game_case(flood_game(more, "dark"))
    assert case["answers"][-1]["trail"] == 600, "the trail is kept up to 600 icons"
    cases.append(case)
    cases.append(game_case(close_game()))
    return cases


def build():
    rng = random.Random(SEED)
    cases = icon_cases(rng) + game_cases(rng)
    return {"seed": SEED, "cv2": cv2.__version__, "numpy": np.__version__, "cases": cases}


def text():
    return json.dumps(build(), separators=(",", ":"), allow_nan=False)


def check(raw):
    with open(OUT, "rb") as handle:
        packed = handle.read()
    old = json.loads(zlib.decompress(packed[4:]))
    new = json.loads(raw)
    differ = 0
    games = 0
    for a, b in zip(old["cases"], new["cases"]):
        if a != b:
            differ += 1
        games += a["case"] == "game"
    if len(old["cases"]) != len(new["cases"]):
        print("the file has %d cases, battle_minigame.py makes %d now" % (len(old["cases"]), len(new["cases"])))
        return 1
    allowed = int(0.03 * len(new["cases"]))
    print("minigame_golden.json.qz was made with OpenCV %s, this is %s: %d of %d cases are answered differently "
          "(%d are allowed for the difference of the versions)" % (old["cv2"], new["cv2"], differ, len(new["cases"]),
                                                                    allowed))
    return 0 if differ <= allowed else 1


def coverage():
    path = os.path.join(ROOT, "battle_minigame.py")
    hit = set()

    def tracer(frame, event, _arg):
        if frame.f_code.co_filename == path:
            if event == "line":
                hit.add(frame.f_lineno)
            return tracer
        return None

    sys.settrace(tracer)
    build()
    sys.settrace(None)
    import ast
    source = open(path, encoding="utf-8").read().splitlines()
    wanted = set()
    for node in ast.walk(ast.parse("\n".join(source))):
        if isinstance(node, ast.stmt) and not isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
            wanted.add(node.lineno)
    missing = sorted(wanted - hit)
    print("%d of %d statements run" % (len(wanted) - len(missing), len(wanted)))
    for n in missing:
        print("%4d  %s" % (n, source[n - 1].strip()[:110]))


if __name__ == "__main__":
    if "--coverage" in sys.argv:
        coverage()
        sys.exit(0)
    raw = text().encode("utf-8")
    if "--check" in sys.argv:
        sys.exit(check(raw))
    with open(OUT, "wb") as handle:
        handle.write(struct.pack(">I", len(raw)) + zlib.compress(raw, 9))
    print("wrote %s: %d bytes of JSON, packed to %d" % (OUT, len(raw), os.path.getsize(OUT)))
