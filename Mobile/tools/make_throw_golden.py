#!/usr/bin/env python3
"""Makes tests/fixtures/throw_golden.json.qz (JSON, packed the way qCompress() of Qt does: the length, then zlib): what the readers and
the sums of the throw of gamebot.py do - the part of catching a Pokémon that looks at a picture or at some numbers - as the file that the
C++ port (SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoThrow.cpp) is tested against.

    python3 tools/make_throw_golden.py            writes the file
    python3 tools/make_throw_golden.py --check    says whether the file is what the code does now (the cases stored in it are played again)

The file has these parts (a picture is a scene: a list of what is drawn, in this order, on the canvas of 1768 x 2208 - see make_scene()):
  rings      measure_ring(): the scene, the box of the detector, what came out (the ratio, the radii, the middle and the quality of the
             ring, or none) and why it failed (ring_diag)
  balls      find_ball() and _landing(): the picture before the throw, the pictures of the flight, where the ball was seen
  buttons    enc_buttons(), in_encounter(), ball_ready() and result_ok_button() of a scene
  speeds     ring_speed(): the pictures of the ring over time and the speed they give
  timing     refit_timing(): what was learned from the last throws (the numbers of cal) before and after
  aims       curve_lean(), spin_points() and aim_note()
  percentiles np.percentile(values, 80) of float32 numbers (the threshold of the edges of measure_ring)
  constants  the numbers of the throw
"""
import argparse
import json
import math
import os
import struct
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.environ["HOME"] = tempfile.mkdtemp()               # (no memory of other days, no learned throws)
sys.path.insert(0, ROOT)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import gamebot as G  # noqa: E402
import spin_stop as S  # noqa: E402

OUT = os.path.join(ROOT, "tests", "fixtures", "throw_golden.json.qz")
W, H = 1768, 2208


# ---------------------------------------------------------------------- the pictures

def make_scene(ops):
    """The canvas with what the list says, in this order:
         ["fill", b, g, r]                              the whole canvas
         ["vgrad", [b, g, r], [b, g, r]]                from the top row to the bottom row (whole numbers, the first colour + the
                                                        difference * row // (rows - 1), rounded down)
         ["rect", x, y, w, h, [b, g, r]]                filled
         ["circle", cx, cy, r, thickness, [b, g, r]]    cv2.circle (thickness -1: filled)
         ["ellipse", cx, cy, ax, ay, angle, thickness, [b, g, r]]  (and then, if the part of the ellipse is not the whole: the angle to start and
                                                        the angle to end, in degrees, as cv2.ellipse takes them)
         ["noise", seed, amplitude]                     every colour of every pixel moves by a whole number from -amplitude to +amplitude
                                                        that a hash of its place and the seed gives (the same in C++)
         ["size", w, h]                                 the picture that there is now made w x h (cv2.resize, the nearest pixel): the last op, for
                                                        a phone with another screen than the canvas"""
    img = np.zeros((H, W, 3), np.uint8)
    for op in ops:
        kind = op[0]
        if kind == "fill":
            img[:] = op[1:4]
        elif kind == "vgrad":
            c0, c1 = np.array(op[1], np.int64), np.array(op[2], np.int64)
            rows = np.arange(H, dtype=np.int64)[:, None]
            img[:] = (c0[None, :] + ((c1 - c0)[None, :] * rows) // (H - 1)).astype(np.uint8)[:, None, :]
        elif kind == "rect":
            _, x, y, w, h, colour = op
            img[max(y, 0):max(y + h, 0), max(x, 0):max(x + w, 0)] = colour
        elif kind == "circle":
            _, cx, cy, r, thickness, colour = op
            cv2.circle(img, (cx, cy), r, tuple(colour), thickness)
        elif kind == "ellipse":
            cx, cy, ax, ay, angle, thickness, colour = op[1:8]
            start, end = (op[8], op[9]) if len(op) > 8 else (0, 360)
            cv2.ellipse(img, (cx, cy), (ax, ay), angle, start, end, tuple(colour), thickness)
        elif kind == "noise":
            _, seed, amp = op
            with np.errstate(over="ignore"):
                y = np.arange(H, dtype=np.uint32)[:, None, None]
                x = np.arange(W, dtype=np.uint32)[None, :, None]
                c = np.arange(3, dtype=np.uint32)[None, None, :]
                n = (x * np.uint32(73856093)) ^ (y * np.uint32(19349663)) ^ (c * np.uint32(83492791)) ^ np.uint32((seed * 2654435761) & 0xFFFFFFFF)
                n = n ^ (n >> np.uint32(13))
                n = n * np.uint32(1274126177)
                n = n ^ (n >> np.uint32(16))
            v = (n % np.uint32(2 * amp + 1)).astype(np.int64) - amp
            img[:] = np.clip(img.astype(np.int64) + v, 0, 255).astype(np.uint8)
        elif kind == "size":
            img = cv2.resize(img, (op[1], op[2]), interpolation=cv2.INTER_NEAREST)
        else:
            raise ValueError(op)
    return img


_scenes = {}


def scene(ops):
    key = json.dumps(ops)
    if key not in _scenes:
        if len(_scenes) > 6:
            _scenes.clear()
        _scenes[key] = make_scene(ops)
    return _scenes[key]


SKY = [120, 110, 70]
GROUND = [60, 110, 70]
WHITE = [255, 255, 255]
GREEN = [60, 210, 90]
YELLOW = [40, 220, 235]
ORANGE = [40, 140, 245]
RED = [40, 40, 235]
POKEMON = [200, 80, 30]


def background(noise=0, seed=1):
    ops = [["vgrad", SKY, GROUND]]
    if noise:
        ops.append(["noise", seed, noise])
    return ops


def ring_colour(ratio):
    return GREEN if ratio > 0.7 else YELLOW if ratio > 0.5 else ORANGE if ratio > 0.3 else RED


def ring_ops(cx, cy, radius, ratio, thickness=3, colour=None, blob=0.3, noise=0, seed=1, white=True, coloured=True, extra=()):
    """A catch screen: the white ring, the coloured ring (the size of the white one times ratio) and the Pokémon in the middle."""
    ops = background(0, seed)
    if blob:
        ops.append(["circle", cx, cy, int(radius * blob), -1, POKEMON])
    if white:
        ops.append(["circle", cx, cy, radius, thickness, WHITE])
    if coloured:
        ops.append(["circle", cx, cy, int(radius * ratio), thickness, colour or ring_colour(ratio)])
    ops.extend(extra)
    if noise:
        ops.append(["noise", seed, noise])
    return ops


def encounter_box(cx, cy, w, h=None, score=0.9):
    return ["boundingBox", score, cx, cy, w, h if h is not None else w]


# ---------------------------------------------------------------------- the rings

def hue_colour(h):
    """A colour (BGR, bright and saturated) that OpenCV turns into this hue."""
    from make_start_golden import exact
    for s in (200, 210, 190, 220, 180, 230, 170, 240, 160, 250):
        for v in (220, 230, 210, 240, 200, 250, 190):
            try:
                return exact(h, s, v)
            except KeyError:
                pass
    raise KeyError(h)


def hsv_colour(hues, sats, vals):
    """A colour (BGR) that OpenCV turns into exactly this hue, saturation and value (each a number or a list of them to try, the first that some
    colour has)."""
    from make_start_golden import exact
    for h in (hues if isinstance(hues, (list, tuple)) else [hues]):
        for sat in (sats if isinstance(sats, (list, tuple)) else [sats]):
            for val in (vals if isinstance(vals, (list, tuple)) else [vals]):
                try:
                    return exact(h, sat, val)
                except KeyError:
                    pass
    raise KeyError((hues, sats, vals))


def sv_colour(sats, vals):
    """A colour (BGR) with exactly this saturation and value (the first of these, of the first hue in the green - yellow - orange range
    that has one): a number or a list of them to try."""
    from make_start_golden import exact
    for sat in (sats if isinstance(sats, (list, tuple)) else [sats]):
        for val in (vals if isinstance(vals, (list, tuple)) else [vals]):
            for h in (30, 28, 32, 26, 34, 24, 36, 22, 38, 20, 40, 18, 42, 16, 44, 14, 46, 12, 48, 10, 50):
                try:
                    return exact(h, sat, val)
                except KeyError:
                    pass
    raise KeyError((sats, vals))


def measure(ops, box):
    img = scene(ops)
    m = G.measure_ring(img, tuple(box))
    diag = dict(G.ring_diag)
    return {"found": m is not None,
            "ratio": None if m is None else float(m["ratio"]), "rw": None if m is None else int(m["rw"]), "rc": None if m is None else int(m["rc"]),
            "cx": None if m is None else int(m["cx"]), "cy": None if m is None else int(m["cy"]), "q": None if m is None else float(m["q"]),
            "diag": {"white": diag.get("white"), "colour": diag.get("colour"), "size": diag.get("size"), "has_size": "size" in diag}}


def ring_cases():
    cases = []

    def add(name, ops, box):
        cases.append({"id": name, "pic": ops, "box": list(box), "result": measure(ops, box)})

    for radius in (100, 160, 230):
        for ratio in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
            add("ring_r%d_%d" % (radius, int(ratio * 100)), ring_ops(884, 900, radius, ratio), encounter_box(884, 900, 2 * radius))
    for radius, ratio, dx, dy in ((160, 0.5, 12, 0), (160, 0.5, -25, 18), (230, 0.6, 40, -30), (100, 0.8, 0, 22), (160, 0.9, -60, 60)):
        add("ring_off_r%d_%d_%d_%d" % (radius, int(ratio * 100), dx, dy), ring_ops(884, 900, radius, ratio),
            encounter_box(884 + dx, 900 + dy, 2 * radius))
    for noise in (4, 10, 20):
        for radius, ratio in ((160, 0.45), (230, 0.75), (120, 0.9)):
            add("ring_noise%d_r%d_%d" % (noise, radius, int(ratio * 100)), ring_ops(884, 900, radius, ratio, noise=noise, seed=noise),
                encounter_box(884, 900, 2 * radius))
    for thickness in (1, 2, 4, 6):
        add("ring_thick%d" % thickness, ring_ops(884, 900, 160, 0.6, thickness=thickness), encounter_box(884, 900, 320))
    add("ring_wide_box", ring_ops(884, 900, 160, 0.6), encounter_box(884, 900, 380, 320))
    add("ring_tall_box", ring_ops(884, 900, 160, 0.6), encounter_box(884, 900, 320, 380))
    add("ring_box_too_big", ring_ops(884, 900, 160, 0.6), encounter_box(884, 900, 420))
    add("ring_box_too_small", ring_ops(884, 900, 160, 0.6), encounter_box(884, 900, 240))
    add("ring_box_tiny", ring_ops(884, 900, 30, 0.6), encounter_box(884, 900, 79))
    add("ring_box_just_big_enough", ring_ops(884, 900, 40, 0.6, blob=0.0), encounter_box(884, 900, 80))
    add("ring_no_white", ring_ops(884, 900, 160, 0.6, white=False), encounter_box(884, 900, 320))
    add("ring_no_coloured", ring_ops(884, 900, 160, 0.6, coloured=False), encounter_box(884, 900, 320))
    add("ring_nothing", background(), encounter_box(884, 900, 320))
    add("ring_coloured_bigger_than_white", ring_ops(884, 900, 160, 1.04), encounter_box(884, 900, 320))
    add("ring_coloured_inside_the_pokemon", ring_ops(884, 900, 160, 0.2), encounter_box(884, 900, 320))
    add("ring_pokemon_the_colour_of_the_ring", ring_ops(884, 900, 160, 0.6, blob=0.0, extra=[["circle", 884, 900, 90, -1, GREEN]]),
        encounter_box(884, 900, 320))
    add("ring_a_band_as_thick_as_the_ring_allows", ring_ops(884, 900, 160, 0.6, blob=0.0, coloured=False,
                                                            extra=[["circle", 884, 900, 100, 28, GREEN]]), encounter_box(884, 900, 320))
    add("ring_a_band_too_thick", ring_ops(884, 900, 160, 0.6, blob=0.0, coloured=False, extra=[["circle", 884, 900, 100, 40, GREEN]]),
        encounter_box(884, 900, 320))
    add("ring_two_coloured", ring_ops(884, 900, 160, 0.6, extra=[["circle", 884, 900, 80, 3, RED]]), encounter_box(884, 900, 320))
    add("ring_a_big_faint_circle", ring_ops(884, 900, 160, 0.6, extra=[["circle", 884, 900, 200, 2, [200, 200, 200]]]), encounter_box(884, 900, 320))
    add("ring_a_second_white_circle", ring_ops(884, 900, 160, 0.6, extra=[["circle", 884, 900, 140, 3, WHITE]]), encounter_box(884, 900, 320))
    for name, cx, cy in (("top", 884, 190), ("left", 150, 900), ("right", 1650, 900), ("bottom", 884, 2150), ("corner", 120, 140)):
        add("ring_at_the_%s" % name, ring_ops(cx, cy, 160, 0.6), encounter_box(cx, cy, 320))
    add("ring_in_a_crowd", ring_ops(884, 900, 160, 0.6, noise=18, seed=7, extra=[["rect", 700, 700, 500, 20, WHITE], ["rect", 900, 600, 20, 600, WHITE],
                                                                                  ["circle", 1100, 1000, 50, 3, WHITE]]), encounter_box(884, 900, 320))
    # so much noise that the threshold of the edges is the 80th percentile of the strengths and not the least of 18 (the number of pixels of the crop
    # decides the part of the percentile that is interpolated)
    for noise in (30, 45, 70, 100):
        for radius, ratio, dx, dy in ((60, 0.5, 0, 0), (100, 0.6, 7, -3), (130, 0.45, 0, 0), (160, 0.7, -11, 5), (200, 0.5, 4, 9), (230, 0.8, 0, 0)):
            add("ring_loud_noise%d_r%d_%d" % (noise, radius, int(ratio * 100)), ring_ops(884, 900, radius, ratio, noise=noise, seed=noise + 1),
                encounter_box(884 + dx, 900 + dy, 2 * radius))
    for noise, cx, cy in ((60, 300, 500), (60, 1500, 1900), (60, 200, 200), (60, 1700, 2100), (60, 884, 160)):
        add("ring_loud_noise_at_%d_%d" % (cx, cy), ring_ops(cx, cy, 120, 0.5, noise=noise, seed=3), encounter_box(cx, cy, 240))
    # the white ring is only partly there: the directions that have an edge are counted (one of them is exactly the one at 180 degrees)
    for start, end in ((0, 180), (0, 200), (0, 270), (90, 360), (180, 360), (170, 350), (45, 315), (10, 340)):
        add("ring_white_arc_%d_%d" % (start, end), ring_ops(884, 900, 160, 0.6, white=False,
                                                              extra=[["ellipse", 884, 900, 160, 160, 0, 3, WHITE, start, end]]), encounter_box(884, 900, 320))
    # a ring at the edge of the screen leaves a crop that must be 80 px both ways (the box is 80 wide: pad 60)
    for name, cx, cy in (("w79", 19, 900), ("w80", 20, 900), ("h79", 884, 19), ("h80", 884, 20), ("r79", 1749, 900), ("r80", 1748, 900),
                         ("b79", 884, 2189), ("b80", 884, 2188), ("both79", 19, 19)):
        add("ring_small_crop_%s" % name, ring_ops(cx, cy, 40, 0.6, blob=0.0), encounter_box(cx, cy, 80))
    # small rings with the box next to the middle (the search steps are 2 px at least: 8 and 10 px off are reached)
    for radius, dx, dy in ((40, 8, 0), (50, -8, 6), (60, 0, -9), (50, 3, 3), (66, 10, -10), (66, 0, 0), (45, -10, 0), (45, 12, 0)):
        add("ring_small_off_r%d_%d_%d" % (radius, dx, dy), ring_ops(884, 900, radius, 0.6, blob=0.0), encounter_box(884 + dx, 900 + dy, 2 * radius))
    # a coloured ring that is tiny, or as big as the search looks for (up to 1.15 times the white one)
    for radius_c in (2, 3, 4, 5, 6, 7, 8, 9, 10, 12):
        add("ring_tiny_coloured_%d" % radius_c, ring_ops(884, 900, 160, 0.6, coloured=False, blob=0.0, extra=[["circle", 884, 900, radius_c, 3, GREEN]]),
            encounter_box(884, 900, 320))
    # (the least radius of the coloured ring is 4 % of the white one, and 5 px at the least: another white radius moves the line)
    for radius_w, radii in ((100, (3, 4, 5, 6, 7)), (200, (5, 6, 7, 8, 9, 10)), (230, (5, 6, 7, 8, 9, 10, 11))):
        for radius_c in radii:
            add("ring_tiny_coloured_w%d_%d" % (radius_w, radius_c),
                ring_ops(884, 900, radius_w, 0.6, coloured=False, blob=0.0, extra=[["circle", 884, 900, radius_c, 3, GREEN]]),
                encounter_box(884, 900, 2 * radius_w))
    for radius_c in (170, 176, 178, 180, 182, 184):
        add("ring_big_coloured_%d" % radius_c, ring_ops(884, 900, 160, 0.6, coloured=False, extra=[["circle", 884, 900, radius_c, 3, GREEN]]),
            encounter_box(884, 900, 320))
    # the colour of the ring to the last step of hue, saturation and value of the mask
    def ring_in(colour):
        return ring_ops(884, 900, 160, 0.6, coloured=False, extra=[["circle", 884, 900, 96, 3, colour]])

    for h in (0, 1, 80, 81, 82, 83, 84, 100, 160, 168, 169, 170, 171, 179):
        add("ring_hue_%d" % h, ring_in(hue_colour(h)), encounter_box(884, 900, 320))
    for sat in (80, 94, 95, 96, 97, 120):
        add("ring_saturation_%d" % sat, ring_in(sv_colour(sat, (220, 200, 240, 210, 230, 180))), encounter_box(884, 900, 320))
    for val in (150, 164, 165, 166, 167, 180):
        add("ring_value_%d" % val, ring_in(sv_colour((200, 180, 220, 190, 210, 160, 240), val)), encounter_box(884, 900, 320))
    # a second arc (of the same colour) next to the ring, in the window that the ring must stand out from (its size depends on the radius)
    for ra, rb, share_a, share_b in ((77, 96, 1.0, 0.8), (66, 86, 0.75, 0.8), (69, 89, 0.95, 0.9), (80, 100, 0.75, 0.8)):
        add("ring_two_arcs_%d_%d" % (ra, rb),
            ring_ops(884, 900, 160, 0.6, coloured=False, blob=0.0,
                     extra=[["ellipse", 884, 900, ra, ra, 0, 3, GREEN, 0, int(360 * share_a)], ["ellipse", 884, 900, rb, rb, 0, 3, GREEN, 100, 100 + int(360 * share_b)]]),
            encounter_box(884, 900, 320))
    # a coloured band: as thick as the ring line may be, and one pixel more (RING_LINE_MAX; the white ring is big, so the windows are wide)
    for radius_b, thickness in ((190, 37), (190, 38), (190, 39), (190, 40), (210, 38), (210, 39), (230, 38), (230, 39)):
        add("ring_band_%d_%d" % (radius_b, thickness),
            ring_ops(884, 900, 230, 0.5, coloured=False, blob=0.0, extra=[["circle", 884, 900, radius_b, thickness, GREEN]]), encounter_box(884, 900, 460))
    # a ring that is coloured only part of the way round (cov), with a second, shorter arc just inside it (the share that the first must beat)
    def arcs(share, inner_share):
        extra = [["ellipse", 884, 900, 96, 96, 0, 3, GREEN, 0, int(360 * share)]]
        if inner_share:
            extra.append(["ellipse", 884, 900, 80, 80, 0, 3, GREEN, 200, 200 + int(360 * inner_share)])
        return ring_ops(884, 900, 160, 0.6, coloured=False, extra=extra)

    for share in (0.66, 0.68, 0.69, 0.7, 0.71, 0.75, 0.9):
        add("ring_arc_%d" % round(share * 100), arcs(share, 0), encounter_box(884, 900, 320))
    for share, inner in ((0.72, 0.1), (0.72, 0.15), (0.72, 0.2), (0.72, 0.25), (0.72, 0.3), (0.75, 0.3), (0.75, 0.35), (0.78, 0.35)):
        add("ring_arc_%d_with_%d_inside" % (round(share * 100), round(inner * 100)), arcs(share, inner), encounter_box(884, 900, 320))
    return cases


# ---------------------------------------------------------------------- the ball in the air

def ball_ops(*balls, base=()):
    """A catch screen with red balls (x, y, w, h): filled ellipses; base: what is drawn before."""
    ops = list(base) + background()
    for x, y, w, h in balls:
        ops.append(["ellipse", x, y, w // 2, h // 2, 0, -1, [30, 30, 220]])
    return ops


def find(ops_after, ops_before):
    after, before = scene(ops_after), scene(ops_before)
    found = G.find_ball(after, before)
    return None if found is None else [int(v) for v in found]


def ball_cases():
    cases = []

    def add(name, after, before):
        cases.append({"id": name, "after": after, "before": before, "result": find(after, before)})

    before = ball_ops()
    add("ball_none", ball_ops(), before)
    add("ball_clear", ball_ops((900, 1000, 100, 100)), before)
    for size in (28, 29, 30, 60, 100, 160, 161, 162, 200):
        add("ball_size_%d" % size, ball_ops((900, 1000, size, size)), before)
    for y in (149, 150, 151, 152, 153, 160, 200):
        add("ball_at_y_%d" % y, ball_ops((900, y, 100, 100)), before)
    for w, h in ((200, 100), (100, 200), (220, 100), (230, 100), (100, 230), (100, 220), (210, 100), (100, 210), (50, 100), (150, 70)):
        add("ball_shape_%dx%d" % (w, h), ball_ops((900, 1000, w, h)), before)
    add("ball_was_there_before", ball_ops((900, 1000, 100, 100)), ball_ops((900, 1000, 100, 100)))
    add("ball_a_bit_moved", ball_ops((900, 1000, 100, 100)), ball_ops((905, 1005, 100, 100)))
    add("ball_a_lot_moved", ball_ops((900, 1000, 100, 100)), ball_ops((1000, 1000, 100, 100)))
    add("ball_moved_just_out_of_the_old_place", ball_ops((900, 1000, 60, 60)), ball_ops((900 + 62, 1000, 60, 60)))
    add("ball_two_balls_the_bigger_wins", ball_ops((600, 900, 70, 70), (1000, 1000, 120, 120)), before)
    add("ball_two_balls_the_same_size", ball_ops((600, 900, 100, 100), (1000, 1000, 100, 100)), before)
    add("ball_two_balls_one_too_small", ball_ops((600, 900, 20, 20), (1000, 1000, 90, 90)), before)
    add("ball_below_the_cut", ball_ops((900, 1580, 100, 100)), before)
    add("ball_dark_red", [["vgrad", SKY, GROUND], ["circle", 900, 1000, 50, -1, [20, 20, 120]]], before)
    add("ball_orange", [["vgrad", SKY, GROUND], ["circle", 900, 1000, 50, -1, [20, 120, 230]]], before)
    add("ball_pink", [["vgrad", SKY, GROUND], ["circle", 900, 1000, 50, -1, [150, 100, 230]]], before)
    add("ball_with_noise", ball_ops((900, 1000, 100, 100)) + [["noise", 3, 12]], before)
    # the red of a ball to the last step of hue, saturation and value (hue below 8 or above 172, saturation above 150, value above 110)
    def disc(colour):
        return [["vgrad", SKY, GROUND], ["circle", 900, 1000, 50, -1, colour]]

    sats, vals = (200, 210, 190, 220, 180, 230, 170, 240), (220, 200, 240, 210, 230, 190, 250)
    for h in (0, 6, 7, 8, 9, 171, 172, 173, 174, 179):
        add("ball_hue_%d" % h, disc(hsv_colour(h, sats, vals)), before)
    for sat in (140, 149, 150, 151, 152, 200):
        add("ball_saturation_%d" % sat, disc(hsv_colour((0, 1, 2, 3, 4, 5, 6, 7, 175, 176, 177, 178, 179), sat, vals)), before)
    for val in (100, 109, 110, 111, 112, 220):
        add("ball_value_%d" % val, disc(hsv_colour((0, 1, 2, 3, 4, 5, 6, 7, 175, 176, 177, 178, 179), sats, val)), before)
    # the area of a ball: a block of red with a corner that is taken away a step at a time, so that exactly this many pixels are left (the opening
    # of 7 x 7 does not take anything away from a block like that)
    def block(area, x=830, y=900):
        w = int(round((area * 1.2) ** 0.5))
        h = -(-area // w)
        cut = w * h - area
        rows = []
        if cut:
            side = 1
            while (side + 1) * (side + 2) // 2 <= cut:
                side += 1
            rows = [side - i + (1 if i < cut - side * (side + 1) // 2 else 0) for i in range(side)]
        ops = [["vgrad", SKY, GROUND], ["rect", x, y, w, h, [30, 30, 220]]]
        ops.extend(["rect", x, y + i, length, 1, [40, 40, 40]] for i, length in enumerate(rows))
        return ops

    for area in (690, 699, 700, 701, 710, 1000, 25990, 25999, 26000, 26001, 26010, 30000):
        add("ball_area_%d" % area, block(area), before)
    # a ring of red that is thin (the opening of 7 x 7 takes away what is thinner than that)
    for thickness in (4, 5, 6, 7, 8, 10):
        add("ball_thin_ring_%d" % thickness, [["vgrad", SKY, GROUND], ["circle", 900, 1000, 30, thickness, [30, 30, 220]]], before)
    # the top of a ball must lie below row 150, and its width and height give a shape between 0.5 and 2.2
    for top in (149, 150, 151, 152):
        add("ball_top_%d" % top, [["vgrad", SKY, GROUND], ["rect", 850, top, 40, 40, [30, 30, 220]]], before)
    for w, h in ((40, 80), (41, 80), (39, 80), (110, 50), (109, 50), (111, 50), (30, 60), (31, 60), (66, 30), (67, 30), (65, 30)):
        add("ball_shape_exact_%dx%d" % (w, h), [["vgrad", SKY, GROUND], ["rect", 850, 900, w, h, [30, 30, 220]]], before)
    # a ball that straddles the cut at row 1560 (what lies below is not looked at)
    for y in (1480, 1510, 1530, 1559, 1560, 1561, 1600, 1620):
        add("ball_straddles_the_cut_%d" % y, ball_ops((900, y, 100, 100)), before)
    return cases


def landing_cases():
    cases = []

    def add(name, afters, before, ring):
        imgs = [scene(a) for a in afters]
        first, land = G._landing(imgs, scene(before), None if ring is None else tuple(ring))
        cases.append({"id": name, "afters": afters, "before": before, "ring": ring, "first": 0 if first is imgs[0] else -1,
                      "land": None if land is None else int(land)})

    before = ball_ops()
    ring = ["boundingBox", 0.9, 884, 900, 320, 320]               # (the Pokémon at 884, 900: the ball comes down at y = 900 - 0.4 * 320 = 772)
    add("land_no_ring", [ball_ops((900, 770, 100, 100))], before, None)
    add("land_on_it", [ball_ops((900, 770, 100, 100))], before, ring)
    add("land_no_ball", [ball_ops()], before, ring)
    add("land_second_picture", [ball_ops(), ball_ops((700, 780, 100, 100))], before, ring)
    add("land_the_nearest_in_height", [ball_ops((700, 600, 100, 100)), ball_ops((1000, 800, 100, 100)), ball_ops((500, 700, 100, 100))], before, ring)
    add("land_too_high", [ball_ops((900, 772 - 380, 100, 100))], before, ring)
    add("land_too_low", [ball_ops((900, 772 + 380, 100, 100))], before, ring)
    add("land_just_in_range", [ball_ops((900, 772 + 379, 100, 100))], before, ring)
    add("land_just_in_range_above", [ball_ops((900, 772 - 379, 100, 100))], before, ring)
    tall = ["boundingBox", 0.9, 884, 900, 200, 320]               # (the height of the box counts, not the width: 900 - 0.4 * 320 = 772)
    wide = ["boundingBox", 0.9, 884, 900, 320, 200]               # (900 - 0.4 * 200 = 820)
    add("land_tall_box_in_range", [ball_ops((900, 772 - 379, 100, 100))], before, tall)
    add("land_tall_box_too_low", [ball_ops((900, 772 + 385, 100, 100))], before, tall)
    add("land_tall_box_too_high", [ball_ops((900, 772 - 385, 100, 100))], before, tall)
    add("land_wide_box_in_range", [ball_ops((900, 820 + 379, 100, 100))], before, wide)
    add("land_wide_box_too_high", [ball_ops((900, 820 - 385, 100, 100))], before, wide)
    add("land_equally_near", [ball_ops((700, 772 - 50, 100, 100)), ball_ops((1100, 772 + 50, 100, 100))], before, ring)
    return cases


# ---------------------------------------------------------------------- the buttons of the catch screen

DISC = [225, 225, 225]


def buttons_ops(berry=True, ball=True, radius=122, disc=DISC, base=None, extra=()):
    ops = list(base) if base is not None else [["fill", 70, 90, 60]]
    for centre, on in ((S.ENC_BERRY_BTN, berry), (S.ENC_BALL_BTN, ball)):
        if on:
            ops.append(["circle", centre[0], centre[1], radius, -1, disc])
    ops.extend(extra)
    return ops


TEAL = None


def teal(h=90, s=140, v=None):
    """A colour that OpenCV turns into exactly this hue and saturation (and this value, when it is given: else one of 130 - 230)."""
    from make_start_golden import exact
    for dv in range(0, 60):
        for value in ([v] if v is not None else [170 + dv, 170 - dv]):
            try:
                return exact(h, s, value)
            except KeyError:
                pass
        if v is not None:
            break
    for dv in range(0, 60):                                  # (a value that no colour of this hue and saturation has: the nearest saturation)
        for ds in (dv, -dv):
            try:
                return exact(h, s + ds, v if v is not None else 170)
            except KeyError:
                pass
    raise KeyError((h, s, v))


def pill_ops(x, y, w, h, colour=None):
    return [["fill", 60, 60, 60], ["rect", x, y, w, h, colour or teal()]]


def exact_light_ops(kind, n):
    """The ops of a catch screen where the ball button has exactly n light pixels in its ring (kind 'ring') or outside it (kind 'out')."""
    import cv2
    bx, by = S.ENC_BALL_BTN
    bg = [70, 90, 60]
    yy, xx = np.ogrid[-165:165, -165:165]
    r = np.sqrt(xx ** 2 + yy ** 2)
    band = (r > 88) & (r < 112) if kind == "ring" else (r > 140) & (r < 162)
    exact = np.zeros((330, 330), bool)
    for a in ((88, 112) if kind == "ring" else (140, 162)):
        exact |= r == a
    shape = [["circle", bx, by, 111, -1, DISC]] if kind == "ring" else [["circle", bx, by, 151, 22, DISC]]
    img = scene(buttons_ops(ball=False) + shape)
    hsv = cv2.cvtColor(img[by - 165:by + 165, bx - 165:bx + 165], cv2.COLOR_BGR2HSV)
    lit = (hsv[..., 1] < 45) & (hsv[..., 2] > 150) & ~exact
    per_column = (lit & band).sum(axis=0)
    cum = np.cumsum(per_column)
    xa = int(np.nonzero(cum >= n)[0][0])                         # the column that has the last pixels
    need = n - (int(cum[xa - 1]) if xa > 0 else 0)
    y0 = 0 if need == 0 else int(np.nonzero(np.cumsum((lit & band)[:, xa]) >= need)[0][0]) + 1
    ops = buttons_ops(ball=False) + shape
    ops.append(["rect", bx - 165 + xa + 1, by - 165, 330 - xa - 1, 330, bg])
    ops.append(["rect", bx - 165 + xa, by - 165 + y0, 1, 330 - y0, bg])
    for i, j in zip(*np.nonzero(exact & (hsv[..., 2] > 150))):
        ops.append(["rect", bx - 165 + int(j), by - 165 + int(i), 1, 1, bg])
    if kind == "out":                                              # (the disc itself must be there, or the ring would not be light)
        ops.append(["circle", bx, by, 122, -1, DISC])
    img = scene(ops)
    hsv = cv2.cvtColor(img[by - 165:by + 165, bx - 165:bx + 165], cv2.COLOR_BGR2HSV)
    got = int(((hsv[..., 1] < 45) & (hsv[..., 2] > 150) & band).sum())
    assert got == n, (kind, n, got)
    return ops


def button_cases():
    cases = []

    def add(name, ops):
        img = scene(ops)
        cases.append({"id": name, "pic": ops, "enc_buttons": bool(G.enc_buttons(img)), "in_encounter": bool(S.in_encounter(img)),
                      "ball_ready": bool(G.ball_ready(img)),
                      "ok": None if G.result_ok_button(img) is None else [int(v) for v in G.result_ok_button(img)]})

    add("buttons_both", buttons_ops())
    add("buttons_only_berry", buttons_ops(ball=False))
    add("buttons_only_ball", buttons_ops(berry=False))
    add("buttons_none", buttons_ops(berry=False, ball=False))
    for radius in (90, 95, 97, 98, 99, 100, 105, 110, 112, 116, 122, 135, 140, 143, 145, 146, 147, 148, 150, 160, 165):
        add("buttons_disc_%d" % radius, buttons_ops(radius=radius))
    # the disc is light when its saturation is below 45 and its value above 150 (to the last step)
    for sat in (30, 43, 44, 45, 46, 60):
        add("buttons_saturation_%d" % sat, buttons_ops(disc=hsv_colour(list(range(0, 180, 7)), sat, (200, 210, 190, 220, 180, 230, 170, 240))))
    for val in (140, 149, 150, 151, 152, 200):
        add("buttons_value_%d" % val, buttons_ops(disc=hsv_colour(list(range(0, 180, 7)), (20, 15, 25, 10, 30), val)))
    for name, disc in (("dark", [140, 140, 140]), ("grey_150", [151, 151, 151]), ("grey_149", [150, 150, 150]), ("tinted", [225, 200, 200]),
                       ("tinted_a_bit", [225, 215, 215]), ("white", [255, 255, 255])):
        add("buttons_colour_%s" % name, buttons_ops(disc=disc))
    add("buttons_a_light_scene", buttons_ops(base=[["fill", 215, 215, 215]]))
    add("buttons_a_bright_outside", buttons_ops(extra=[["circle", S.ENC_BALL_BTN[0], S.ENC_BALL_BTN[1], 151, 20, DISC]]))
    add("buttons_a_little_bright_outside", buttons_ops(extra=[["circle", S.ENC_BALL_BTN[0], S.ENC_BALL_BTN[1], 151, 5, DISC]]))
    add("buttons_with_noise", buttons_ops(extra=[["noise", 5, 14]]))
    # the share of light pixels in the ring (88 < r < 112 around the middle of the button: 15064 pixels) must be 0.4 at the least, and the one
    # outside (140 < r < 162: 20900 pixels) 0.3 at the most.  Exactly so many pixels are made light (a disc or ring of light, with a part taken away
    # again: whole columns, then some of the pixels of one more column), and the pixels at exactly 88, 112, 140 and 162 px from the middle
    # (the places where < or <= makes a difference) are left dark
    for kind, counts in (("ring", (6024, 6025, 6026, 6027, 6028, 6100, 7000)), ("out", (6000, 6269, 6270, 6271, 6272, 6273, 6274, 6275, 6400))):
        for n in counts:
            add("buttons_exactly_%d_light_pixels_%s" % (n, "in_the_ring" if kind == "ring" else "outside"), exact_light_ops(kind, n))
    # the red ball at the bottom: two pixels (1870, 877) and (1960, 877) that are red, and the map button (red top, white below) is not there
    red = [30, 30, 220]
    add("ball_red_both", [["fill", 60, 60, 60], ["rect", 877, 1870, 1, 1, red], ["rect", 877, 1960, 1, 1, red]])
    add("ball_red_top_only", [["fill", 60, 60, 60], ["rect", 877, 1870, 1, 1, red]])
    add("ball_red_bottom_only", [["fill", 60, 60, 60], ["rect", 877, 1960, 1, 1, red]])
    add("ball_red_a_bit_dark", [["fill", 60, 60, 60], ["rect", 877, 1870, 1, 1, [20, 20, 121]], ["rect", 877, 1960, 1, 1, [20, 20, 121]]])
    add("ball_red_too_dark", [["fill", 60, 60, 60], ["rect", 877, 1870, 1, 1, [20, 20, 120]], ["rect", 877, 1960, 1, 1, [20, 20, 120]]])
    add("ball_red_not_red_enough", [["fill", 60, 60, 60], ["rect", 877, 1870, 1, 1, [80, 80, 200]], ["rect", 877, 1960, 1, 1, [80, 80, 200]]])
    add("ball_red_just_red_enough", [["fill", 60, 60, 60], ["rect", 877, 1870, 1, 1, [60, 60, 200]], ["rect", 877, 1960, 1, 1, [60, 60, 200]]])
    for name, c in (("blue_dominant", [105, 10, 200]), ("green_dominant", [10, 105, 200]), ("exactly_twice", [100, 100, 200]), ("exactly_twice_blue", [100, 10, 200]),
                    ("exactly_twice_green", [10, 100, 200]), ("just_over_twice", [99, 99, 200]), ("just_over_twice_blue", [99, 10, 200]),
                    ("just_over_twice_green", [10, 99, 200]), ("red_121", [30, 30, 121]), ("red_120", [30, 30, 120]), ("red_255", [0, 0, 255])):
        add("ball_red_pixel_" + name, [["fill", 60, 60, 60], ["rect", 877, 1870, 1, 1, c], ["rect", 877, 1960, 1, 1, c]])
    add("ball_red_but_the_map", [["fill", 255, 255, 255], ["rect", 883, 1930, 1, 1, red], ["rect", 877, 1870, 1, 1, red], ["rect", 877, 1960, 1, 1, red]])
    # the teal OK pill of the screen after a catch: width 601 - 1199, height 111 - 329, wider than 2.5 times its height, its middle within 159 of x = 884
    for name, x, y, w, h in (("ok_good", 564, 1900, 640, 120), ("ok_x_off_159", 564 + 159, 1900, 640, 120), ("ok_x_off_160", 564 + 160, 1900, 640, 120),
                             ("ok_x_off_neg159", 564 - 159, 1900, 640, 120), ("ok_x_off_neg160", 564 - 160, 1900, 640, 120),
                             ("ok_w_600", 584, 1900, 600, 120), ("ok_w_601", 584, 1900, 601, 120), ("ok_w_1199", 285, 1900, 1199, 120),
                             ("ok_w_1200", 284, 1900, 1200, 120), ("ok_w_599", 585, 1900, 599, 120),
                             ("ok_h_110", 564, 1900, 640, 110), ("ok_h_111", 564, 1900, 640, 111), ("ok_h_329", 434, 1700, 900, 329),
                             ("ok_h_330", 434, 1700, 900, 330), ("ok_h_109", 564, 1900, 640, 109),
                             ("ok_aspect_exact", 884 - 312, 1900, 625, 250), ("ok_aspect_over", 884 - 313, 1900, 626, 250),
                             ("ok_high", 564, 1500, 640, 120), ("ok_a_little_high", 564, 1499, 640, 120), ("ok_low", 564, 2030, 640, 120),
                             ("ok_too_low", 564, 2040, 640, 120)):
        add(name, pill_ops(x, y, w, h))
    for name, colour in (("h79", teal(79)), ("h80", teal(80)), ("h100", teal(100)), ("h101", teal(101)), ("s69", teal(90, 69)), ("s70", teal(90, 70)),
                         ("s210", teal(90, 210)), ("s211", teal(90, 211)), ("v109", teal(90, 140, 109)), ("v110", teal(90, 140, 110)),
                         ("v235", teal(90, 140, 235)), ("v236", teal(90, 140, 236))):
        add("ok_colour_" + name, pill_ops(564, 1900, 640, 120, colour))
    add("ok_with_a_hole", pill_ops(564, 1900, 640, 120) + [["rect", 700, 1930, 300, 60, [60, 60, 60]]])
    add("ok_with_a_small_hole", pill_ops(564, 1900, 640, 120) + [["rect", 700, 1930, 100, 20, [60, 60, 60]]])
    add("ok_two_pills_the_bigger_wins", [["fill", 60, 60, 60], ["rect", 564, 1700, 640, 120, teal()], ["rect", 534, 1900, 700, 140, teal()]])
    add("ok_two_pills_the_same", [["fill", 60, 60, 60], ["rect", 564, 1700, 640, 120, teal()], ["rect", 564, 1900, 640, 120, teal()]])
    # a gap in the pill is closed by a closing of 25 x 25 (gaps of up to 24 px), and what is thinner than 7 px is taken away by the opening
    for gap in (10, 22, 24, 25, 26, 30, 40, 60):
        add("ok_gap_%d" % gap, pill_ops(564, 1900, 640, 120) + [["rect", 864, 1900, gap, 120, [60, 60, 60]]])
    for thickness in (3, 6, 7, 10, 14, 15, 16, 20):
        add("ok_tail_%d" % thickness, pill_ops(564, 1900, 640, 120) + [["rect", 1204, 1940, 120, thickness, teal()]])
    # the pill must fill 60 % of its box: a comb of 700 x 150 with 63000 px is exactly on the line (not found), 105 px more or less is on either side
    def comb(right_leg):
        return [["fill", 60, 60, 60], ["rect", 534, 1900, 700, 45, teal()], ["rect", 534, 1945, 150, 105, teal()],
                ["rect", 1234 - right_leg, 1945, right_leg, 105, teal()]]
    add("ok_fill_exact", comb(150))
    add("ok_fill_under", comb(149))
    add("ok_fill_over", comb(151))
    add("ok_a_thin_line", pill_ops(564, 1900, 640, 6))
    add("ok_with_noise", pill_ops(564, 1900, 640, 120) + [["noise", 4, 10]])
    add("ok_none", [["fill", 60, 60, 60]])
    return cases


# ---------------------------------------------------------------------- the speed of the ring, what was learned, the curveball

def speed_cases():
    cases = []

    def add(name, points):
        k = G.ring_speed([tuple(p) for p in points])
        cases.append({"id": name, "points": points, "k": None if k is None else float(k)})

    add("speed_none", [])
    add("speed_one", [[10.0, 0.9]])
    add("speed_two_points_one_step", [[10.0, 0.9], [10.2, 0.8]])
    add("speed_three_points", [[10.0, 0.9], [10.2, 0.79], [10.4, 0.68]])
    add("speed_the_ring_starts_again", [[10.0, 0.3], [10.2, 0.2], [10.4, 0.1], [10.6, 0.95], [10.8, 0.84], [11.0, 0.73]])
    add("speed_step_too_close_in_time", [[10.0, 0.9], [10.04, 0.88], [10.2, 0.8], [10.4, 0.69]])
    add("speed_step_just_far_enough", [[10.0, 0.9], [10.05, 0.88], [10.25, 0.77], [10.45, 0.66]])
    add("speed_step_down_by_6", [[10.0, 0.9], [10.2, 0.3], [10.4, 0.2], [10.6, 0.1]])
    add("speed_step_down_by_almost_6", [[10.0, 0.9], [10.2, 0.3001], [10.4, 0.2], [10.6, 0.1]])
    add("speed_no_step_down", [[10.0, 0.5], [10.2, 0.5], [10.4, 0.6]])
    add("speed_too_slow", [[10.0, 0.9], [10.5, 0.85], [11.0, 0.8]])
    add("speed_too_fast", [[10.0, 0.95], [10.1, 0.5], [10.2, 0.05]])
    add("speed_just_fast_enough", [[10.0, 0.9], [11.0, 0.65], [12.0, 0.4]])
    add("speed_just_slow_enough", [[10.0, 0.9], [10.5, 0.775], [11.0, 0.65], [11.5, 0.525]])
    add("speed_the_middle_of_four", [[10.0, 0.9], [10.2, 0.8], [10.4, 0.66], [10.6, 0.5], [10.8, 0.41]])
    # the least time between two pictures (0.05 s, to the last bit: 0.05 - 0.0 is exactly 0.05), a step of no size, a step of exactly 0.6, a speed of exactly 1.0
    add("speed_dt_exactly_0_05", [[0.0, 0.9], [0.05, 0.88], [0.25, 0.77]])
    add("speed_dt_0_055", [[10.0, 0.9], [10.055, 0.88], [10.255, 0.77], [10.455, 0.66]])
    add("speed_dt_0_0499", [[0.0, 0.9], [0.0499, 0.88], [0.2499, 0.77], [0.4499, 0.66]])
    add("speed_dt_0_06", [[0.0, 0.9], [0.06, 0.88], [0.26, 0.77], [0.46, 0.66]])
    add("speed_a_step_of_no_size", [[10.0, 0.5], [10.2, 0.5], [10.4, 0.4], [10.6, 0.28]])
    add("speed_a_step_of_exactly_0_6", [[10.0, 0.6], [10.5, 0.0], [10.7, 0.9], [10.9, 0.82], [11.1, 0.7]])
    add("speed_the_median_is_exactly_1", [[10.0, 0.75], [10.5, 0.25], [11.0, 0.75], [11.5, 0.25]])
    add("speed_the_median_is_just_over_1", [[10.0, 0.75], [10.5, 0.2499], [11.0, 0.75], [11.5, 0.2499]])
    add("speed_the_median_is_exactly_0_25", [[10.0, 0.75], [12.0, 0.25], [14.0, 0.75], [16.0, 0.25]])
    rnd = np.random.default_rng(11)
    for n in range(24):
        count = int(rnd.integers(3, 9))
        t = 10.0 + np.cumsum(rnd.uniform(0.03, 0.3, count))
        r = np.clip(0.95 - np.cumsum(rnd.uniform(-0.02, 0.2, count)), 0.02, 1.0)
        add("speed_random_%d" % n, [[round(float(a), 4), round(float(b), 4)] for a, b in zip(t, r)])
    return cases


def timing_cases():
    cases = []

    def add(name, obs, live=False, k=None):
        saved = {key: (list(v) if isinstance(v, list) else v) for key, v in G.cal.items()}
        G.cal.update({"obs": [], "obs_live": [], "k": 0.55 if k is None else k, "c": 0.3, "c_live": -0.12})
        G.cal["obs_live" if live else "obs"] = [list(o) for o in obs]
        G.refit_timing(live)
        cases.append({"id": name, "obs": obs, "live": live, "k_before": 0.55 if k is None else k,
                      "after": {key: G.cal[key] for key in ("k", "c", "c_live")}})
        G.cal.clear()
        G.cal.update(saved)

    add("timing_none", [])
    add("timing_one", [[0.5, 1.2, 0.3]])
    add("timing_one_live", [[0.5, 1.2, 0.3]], live=True)
    add("timing_exact", [[0.5, 1.0, 0.5 - 0.55 * (1.0 - 0.3) % 1.0]])
    add("timing_two", [[0.5, 1.2, 0.2], [0.8, 0.9, 0.4]])
    add("timing_five_so_k_stays", [[0.9, 1.0, 0.5], [0.5, 1.5, 0.2], [0.3, 0.7, 0.1], [0.7, 1.1, 0.4], [0.6, 1.3, 0.3]])
    add("timing_six_but_the_same_time", [[0.9, 1.0, 0.5]] * 6)
    add("timing_six_enough_spread", [[0.9, 1.0, 0.5], [0.5, 1.6, 0.2], [0.3, 0.7, 0.1], [0.7, 1.1, 0.4], [0.6, 1.3, 0.3], [0.8, 1.2, 0.45]])
    add("timing_six_just_spread_enough", [[0.9, 1.0, 0.5], [0.5, 1.6, 0.2], [0.3, 1.0, 0.1], [0.7, 1.0, 0.4], [0.6, 1.0, 0.3], [0.8, 1.0, 0.45]])
    add("timing_six_just_not_spread_enough", [[0.9, 1.0, 0.5], [0.5, 1.5999, 0.2], [0.3, 1.0, 0.1], [0.7, 1.0, 0.4], [0.6, 1.0, 0.3], [0.8, 1.0, 0.45]])
    # the spread of the times must be 0.6 (exactly: 0.6 - 0.0), and the speed that is looked for goes from 0.35 to 0.80 (a ring at 0.84 is read as 0.80)
    def sixteen(k_true, c_true, ts):
        return [[round(m, 3), round(t, 3), round((m - k_true * (t - c_true)) % 1.0, 3)] for m, t in zip((0.9, 0.5, 0.3, 0.7, 0.6, 0.8) * 3, ts)]

    add("timing_six_spread_exactly_0_6", sixteen(0.72, 0.4, (0.0, 0.6, 0.3, 0.2, 0.4, 0.5)))
    add("timing_six_spread_0_61", sixteen(0.72, 0.4, (0.0, 0.61, 0.3, 0.2, 0.4, 0.5)))
    add("timing_six_spread_0_59", sixteen(0.72, 0.4, (0.0, 0.59, 0.3, 0.2, 0.4, 0.5)))
    fast = (0.4, 2.5, 1.0, 1.5, 0.8, 2.0, 1.2, 1.8, 0.6, 2.2, 0.9, 1.4, 1.7, 2.4, 0.5, 1.1)
    for k_true in (0.84, 0.80, 0.35, 0.34):
        add("timing_a_ring_of_%s" % str(k_true).replace(".", "_"), sixteen(k_true, 0.5, fast))
    # sets of throws on a coarse grid, where two settings fit just as well (the sums are the same to the last bit but one, so what is left of them
    # decides): found by a search, they tell a sum in blocks of eight from one in a row, the remainder of the sum of a negative number from a plain
    # one, and a wrong 'add one' on it, apart
    ties = {
        "nomod": [
            [[0.9, 1.05, 0.85], [0.6, 2.15, 0.0], [0.4, 2.0, 0.75], [0.2, 1.2, 0.9], [0.45, 2.0, 0.1], [0.65, 0.45, 0.65], [0.65, 0.75, 0.15], [0.25, 2.4, 0.9], [0.55, 2.25, 0.55], [0.6, 2.25, 0.35], [0.3, 1.65, 0.0]],
            [[0.35, 0.8, 0.6], [0.15, 0.45, 0.8], [0.6, 1.75, 0.55], [0.6, 2.25, 0.25], [0.25, 1.25, 0.05], [0.85, 1.65, 0.25], [0.9, 1.3, 0.35], [0.1, 2.3, 0.35], [0.25, 0.55, 0.25], [0.75, 1.25, 0.95], [0.05, 0.55, 0.45], [0.35, 0.85, 0.95], [0.3, 0.65, 0.2], [0.8, 2.3, 0.1]],
            [[0.2, 2.4, 0.9], [0.6, 1.5, 0.4], [0.8, 0.6, 0.3], [0.3, 1.2, 0.2], [0.6, 2.3, 0.7], [0.5, 2.3, 0.5], [0.8, 1.3, 0.2], [0.4, 0.8, 0.6], [0.5, 1.3, 0.5], [0.6, 2.2, 0.7], [0.6, 1.7, 0.3], [0.2, 1.8, 0.9]],
        ],
        "seq": [
            [[0.2, 1.85, 0.75], [0.7, 1.25, 0.0], [0.7, 0.45, 0.8], [0.15, 1.0, 0.2], [0.55, 0.8, 0.25], [0.05, 2.45, 0.2], [0.2, 1.65, 0.1], [0.85, 2.0, 0.3], [0.4, 1.15, 0.7], [0.4, 0.95, 0.65], [0.15, 2.0, 0.4], [0.9, 0.9, 0.35], [0.85, 1.85, 0.0], [0.35, 0.4, 0.8]],
            [[0.6, 0.5, 0.4], [0.9, 1.8, 0.7], [0.3, 2.2, 0.1], [0.5, 2.0, 0.9], [0.1, 1.0, 0.3], [0.4, 1.4, 0.2], [0.6, 1.7, 0.2], [0.7, 0.5, 0.8], [0.8, 0.9, 0.5], [0.9, 0.5, 0.4], [0.2, 0.7, 0.2], [0.5, 1.4, 0.0], [0.7, 1.5, 0.6], [0.1, 1.7, 0.8]],
            [[0.7, 0.7, 0.0], [0.3, 0.4, 0.1], [0.3, 0.5, 0.2], [0.8, 1.6, 0.6], [0.5, 0.8, 0.2], [0.9, 0.8, 0.1], [0.3, 1.1, 0.5], [0.4, 1.8, 0.7], [0.9, 1.2, 0.6], [0.8, 1.5, 0.5], [0.4, 1.1, 0.2]],
        ],
        "negnoise": [
            [[0.35, 0.8, 0.6], [0.15, 0.45, 0.8], [0.6, 1.75, 0.55], [0.6, 2.25, 0.25], [0.25, 1.25, 0.05], [0.85, 1.65, 0.25], [0.9, 1.3, 0.35], [0.1, 2.3, 0.35], [0.25, 0.55, 0.25], [0.75, 1.25, 0.95], [0.05, 0.55, 0.45], [0.35, 0.85, 0.95], [0.3, 0.65, 0.2], [0.8, 2.3, 0.1]],
            [[0.45, 1.3, 0.4], [0.85, 1.3, 0.25], [0.1, 1.95, 0.85], [0.35, 1.7, 0.4], [0.35, 0.9, 0.4], [0.25, 2.2, 0.3], [0.6, 1.6, 0.3], [0.45, 0.7, 0.35], [0.95, 2.2, 0.55], [0.45, 1.8, 0.75], [0.4, 1.05, 0.35], [0.1, 0.85, 0.45], [0.5, 1.35, 0.8], [0.05, 0.45, 0.05], [0.55, 1.6, 0.55], [0.3, 0.7, 0.15]],
            [[0.7, 1.8, 0.9], [0.1, 1.0, 0.3], [0.5, 1.4, 0.4], [0.4, 0.7, 0.7], [0.1, 1.8, 0.7], [0.3, 1.0, 0.3], [0.1, 1.4, 0.3], [0.7, 0.7, 0.4], [0.3, 2.3, 0.2], [0.6, 1.7, 0.5], [0.4, 0.7, 0.3], [0.6, 1.9, 0.4], [0.4, 2.3, 0.6], [0.6, 1.9, 0.1]],
        ],
    }
    for kind, sets in ties.items():
        for i, obs in enumerate(sets):
            add("timing_tie_%s_%d" % (kind, i), obs)
    for live in (False, True):
        rnd = np.random.default_rng(23 + live)
        for n in range(40):
            count = int(rnd.integers(1, 20))
            k_true, c_true = float(rnd.uniform(0.35, 0.8)), float(rnd.uniform(-0.3, 1.2))
            obs = []
            for _ in range(count):
                measured = float(rnd.uniform(0.05, 1.0))
                held = float(rnd.uniform(0.4, 2.5))
                got = (measured - k_true * (held - c_true)) % 1.0
                if rnd.random() < 0.2:
                    got = float(rnd.uniform(0, 1))
                obs.append([round(measured, 3), round(held, 3), round(got, 3)])
            add("timing_random_%s_%d" % ("live" if live else "still", n), obs, live=live, k=float(rnd.uniform(0.4, 0.7)))
    return cases


def aim_cases():
    cases = {"lean": [], "points": None, "notes": []}
    for aim in (0.0, 60.0, -85.5, 400.0, -400.0):
        for target in (None, 0, 100, 400, 884, 1000, 1500, 1768, -300, 2500):
            saved = G.cal["aim"]
            G.cal["aim"] = aim
            cases["lean"].append({"aim": aim, "target": target, "lean": int(G.curve_lean(target))})
            G.cal["aim"] = saved
    cases["points"] = [[int(x), int(y)] for x, y in G.spin_points()]
    for aim_dx in (0, 1, -1, 7, -7, 8, -8, 9, -9, 50, -50, 160, 161, -161, 162, -162, 163, 300, -300):
        for ring_w in (None, 300, 460, 461):
            note = G.aim_note(aim_dx) if ring_w is None else G.aim_note(aim_dx, ring_w)
            cases["notes"].append({"aim_dx": aim_dx, "ring_w": ring_w, "note": note})
    return cases


CONSTANTS = ("THROW_TARGETS", "TOUCH_SHOT", "CURVE_SPINS", "CURVE_RADIUS", "CURVE_D", "CURVE_LAND", "CURVE_LEAN_GAIN", "CURVE_LEAN_MAX",
             "CURVE_POWER", "RING_SPEED", "RING_TRACK_S", "RING_TRACK_EVERY", "RING_LINE_MAX", "HIT_SHARE", "TH_RING", "MAX_THROWS", "THROW_BOOST",
             "THROW_FALLBACK", "REAL_BASE", "REAL_KEEP", "REAL_LOWER", "REAL_BANDS", "REAL_LOWER_OF", "REAL_CURVE", "REAL_AIM", "REAL_SLOPPY",
             "REAL_POWER", "REAL_PAUSE", "REAL_LONG_PAUSE", "RESULT_FIRST_LOOK", "RESULT_WINDOW", "POLL_PAUSE", "POLL_PAUSE_LIVE", "AFTER_OK_WAIT",
             "AFTER_TAP_WAIT", "FAST_BACK_AFTER", "FAST_BACK_LATEST", "FAST_LOOK_AFTER", "CAL_VERSION")


def constants():
    out = {}
    for name in CONSTANTS:
        value = getattr(G, name)
        if isinstance(value, dict):
            out[name] = {k: ([float(x) for x in v] if isinstance(v, (tuple, list)) else v) for k, v in value.items()}
        elif isinstance(value, (tuple, list)):
            out[name] = [float(x) for x in value]
        elif isinstance(value, str):
            out[name] = value
        else:
            out[name] = float(value)
    out["cal"] = {k: v for k, v in G.cal.items() if k in ("k", "c", "lat", "rel", "aim", "c_live")}
    out["BALL_XY"] = [int(v) for v in G.BALL_XY]
    out["ENC_BERRY_BTN"] = [int(v) for v in S.ENC_BERRY_BTN]
    out["ENC_BALL_BTN"] = [int(v) for v in S.ENC_BALL_BTN]
    return out


# ---------------------------------------------------------------------- the file

def percentile_cases():
    """np.percentile(values, 80) of float32 numbers: what the port must give for the threshold of the edges."""
    rnd = np.random.default_rng(31)
    cases = []

    def add(name, values):
        a = np.array(values, np.float32)
        # the shortest text that gives the same float32 back, so that the file stays small
        cases.append({"id": name, "values": [float(str(v)) for v in a], "p": float(np.percentile(a, 80))})

    for n in list(range(1, 41)) + [49, 50, 51, 99, 100, 101, 249, 250, 251, 1000, 2001]:
        add("percentile_normal_%d" % n, np.abs(rnd.normal(0, 30, n)))
        add("percentile_whole_%d" % n, np.floor(rnd.uniform(0, 1000, n)))
        mostly_zero = np.zeros(n)
        some = rnd.random(n) < 0.3
        mostly_zero[some] = rnd.uniform(1, 500, int(some.sum()))
        add("percentile_mostly_zero_%d" % n, mostly_zero)
        add("percentile_squares_%d" % n, np.sqrt(np.floor(rnd.uniform(0, 4e6, n))))
    return cases


def capture():
    return {"constants": constants(), "rings": ring_cases(), "balls": ball_cases(), "landings": landing_cases(), "buttons": button_cases(),
            "speeds": speed_cases(), "timing": timing_cases(), "aims": aim_cases(), "percentiles": percentile_cases()}


def text(parts=None):
    doc = {"cv2": cv2.__version__, "numpy": np.__version__}
    doc.update(capture() if parts is None else parts)
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), allow_nan=False)


def pack(data):
    raw = data.encode()
    return struct.pack(">I", len(raw)) + zlib.compress(raw, 9)


def unpack(blob):
    return zlib.decompress(blob[4:]).decode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--part", default=None)
    args = parser.parse_args()
    if args.check:
        sys.exit(check())
    data = text()
    with open(OUT, "wb") as f:
        f.write(pack(data))
    doc = json.loads(data)
    print("wrote %s: %s" % (OUT, ", ".join("%d %s" % (len(v), k) for k, v in doc.items() if isinstance(v, list))))


def same_percentiles(stored, now, ulps=16):
    """NumPy 2.5 makes the 80th percentile of some float32 numbers a bit different from NumPy 2.2 (54 of the 204 cases, by up to 7 steps of the
    biggest number: it interpolates in another way), and the C++ port follows the version that made the file.  So the numbers are allowed to
    differ by a few steps of the biggest number here; the C++ check is exact."""
    if stored is None or len(stored) != len(now):
        return False
    for a, b in zip(stored, now):
        if a["id"] != b["id"] or a["values"] != b["values"]:
            return False
        step = float(np.spacing(np.float32(max(abs(v) for v in a["values"]))))
        if abs(a["p"] - b["p"]) > ulps * step:
            return False
    return True


def check():
    stored = json.loads(unpack(open(OUT, "rb").read()))
    now = text()
    now_doc = json.loads(now)
    bad = [k for k in now_doc if k not in ("cv2", "numpy", "percentiles") and now_doc[k] != stored.get(k)]
    if not same_percentiles(stored.get("percentiles"), now_doc["percentiles"]):
        bad.append("percentiles")
    if bad:
        print("the file is not what the code does now: %s" % ", ".join(bad))
        return 1
    return 0


if __name__ == "__main__":
    main()
