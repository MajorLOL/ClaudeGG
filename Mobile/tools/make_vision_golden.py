#!/usr/bin/env python3
"""Makes tests/fixtures/vision_golden.json.qz (JSON, packed the way qCompress() of Qt does: the length, then zlib):
what battle_vision.py reads from a lot of pictures, as the file that the C++ port of it
(SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoVision.cpp) is tested against.

    python3 tools/make_vision_golden.py            writes the file
    python3 tools/make_vision_golden.py --check    says whether the file is what battle_vision.py reads now
    python3 tools/make_vision_golden.py --coverage says which lines of battle_vision.py the pictures do not reach

A case is a recipe for a picture, not the picture: a frame of a real recording (tests/fixtures/fight/), cut to a
size, with parts of other frames pasted over it, darker or brighter, with made-up buttons, tiles and discs drawn on
it.  The recipe is a list of steps that both sides run with OpenCV (the C++ port runs exactly the same steps), the
answer is what every reader of battle_vision.py says about the result.  A fixed seed makes it the same every time."""
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
import battle_vision as bv  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
FIGHT = os.path.join(FIXTURES, "fight")
OUT = os.path.join(FIXTURES, "vision_golden.json.qz")
SEED = 20261128
FULL = (1768, 2208)               # the canvas of the phone (the frames are brought to it, with a straight line between pixels:
                                  # the cubic one of OpenCV is not the same pixel for pixel in every build of it)
HALF = (884, 1104)
REFERENCE = "fight_ready.jpg"     # the name keys are compared with the ones of this frame

# where things are drawn / pasted (fractions of the picture): the zones the readers look at
ZONES = [(0.0, 0.0, 1.0, 0.25), (0.0, 0.10, 1.0, 0.21), (0.30, 0.09, 0.70, 0.24), (0.0, 0.75, 1.0, 1.0),
         (0.15, 0.82, 0.85, 0.95), (0.25, 0.86, 0.75, 0.99), (0.25, 0.60, 0.75, 0.82), (0.0, 0.18, 1.0, 0.60),
         (0.0, 0.40, 1.0, 0.70), (0.0, 0.0, 0.5, 1.0), (0.5, 0.0, 1.0, 1.0), (0.0, 0.0, 1.0, 1.0)]


# ---- the steps of a recipe (the C++ port has the same ones) -------------------------------------------------
def load(name):
    img = cv2.imread(os.path.join(FIGHT, name))
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
        elif kind == "paste":
            h, w = img.shape[:2]
            other = cv2.resize(load(op[1]), (w, h), interpolation=cv2.INTER_LINEAR)
            x0, y0, x1, y1 = op[2:6]
            img[y0:y1, x0:x1] = other[y0:y1, x0:x1]
        elif kind == "blend":
            h, w = img.shape[:2]
            other = cv2.resize(load(op[1]), (w, h), interpolation=cv2.INTER_LINEAR)
            img = cv2.addWeighted(img, 1.0 - op[2], other, op[2], 0.0)
        elif kind == "fill":
            x0, y0, x1, y1 = op[1:5]
            img[y0:y1, x0:x1] = op[5:8]
        elif kind == "disc":
            cv2.circle(img, (op[1], op[2]), op[3], (op[4], op[5], op[6]), -1)
        elif kind == "line":
            cv2.line(img, (op[1], op[2]), (op[3], op[4]), (op[5], op[6], op[7]), op[8])
        else:
            raise ValueError(kind)
    return np.ascontiguousarray(img)


# ---- the answers ----------------------------------------------------------------------------------------------
def plain(value):
    """JSON-able: tuples are lists, NumPy numbers are numbers."""
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value)
    return value


def key_hex(key):
    return bytes(key.flatten().tolist()).hex()


_reference = []


def reference_keys():
    if not _reference:
        img = cv2.resize(load(REFERENCE), FULL, interpolation=cv2.INTER_LINEAR)
        _reference.extend([bv.name_key(img, "me"), bv.name_key(img, "foe")])
    return _reference


def answers(img):
    me, foe = bv.name_key(img, "me"), bv.name_key(img, "foe")
    ref_me, ref_foe = reference_keys()
    home = bv.home_button(img)
    exit_at = bv.exit_yes(img)
    # (features() holds hud, count, ring, hex, shields, hp and result: here only what it leaves out or only
    # asks for with the HUD on the picture, so that every reader is asked about every picture)
    return plain({
        "features": bv.features(img),
        "balls": bv.ball_slots(img),
        "ready": bv.charge_ready(img),
        "get_ready": bv.get_ready(img),
        "bars": bv.hp_bars(img),
        "done": bv.done_button(img),
        "keys": {"me": key_hex(me), "foe": key_hex(foe)},
        "differs": [bv.key_differs(me, ref_me), bv.key_differs(foe, ref_foe), bv.key_differs(me, ref_foe),
                    bv.key_differs(None, me), bv.key_differs(foe, None)],
        "wide": {"0.45": bv.wide_buttons(img), "0.7": bv.wide_buttons(img, 0.70), "0.38": bv.wide_buttons(img, 0.38)},
        "home": home,
        "spot": bv.button_spot(home) if home else None,
        "spot_q": bv.button_spot(home, 0.25) if home else None,
        "off": bv.home_button_off(img),
        "gold": bv.gold_tiles(img),
        "popup": bv.popup_tiles_shown(img),
        "exit": exit_at,
    })


# ---- the recipes ----------------------------------------------------------------------------------------------
def bgr(hue, sat, val):
    return [int(v) for v in cv2.cvtColor(np.uint8([[[hue, sat, val]]]), cv2.COLOR_HSV2BGR)[0][0]]


def rect(rnd, size, zone=None):
    w, h = size
    x0f, y0f, x1f, y1f = zone or rnd.choice(ZONES)
    if zone is None and rnd.random() < 0.4:
        a, b = sorted((rnd.random(), rnd.random()))
        c, d = sorted((rnd.random(), rnd.random()))
        x0f, x1f, y0f, y1f = a, max(b, a + 0.05), c, max(d, c + 0.03)
    return [int(x0f * w), int(y0f * h), min(int(x1f * w), w), min(int(y1f * h), h)]


def pill(rnd, size, colour):
    """A wide button: a block in the colour of the game's buttons with a white label in it (as pieces, as the
    letters are), not always as it should be."""
    w, h = size
    pw = rnd.choice([0.18, 0.26, 0.30, 0.34, 0.40, 0.46, 0.52, 0.70])
    ph = rnd.choice([0.012, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.13])
    cx = rnd.choice([0.5, 0.5, 0.5, 0.35, 0.65, rnd.random()])
    cy = rnd.choice([0.55, 0.60, 0.66, 0.74, 0.80, 0.866, 0.90, 0.95, 0.975, rnd.uniform(0.40, 1.0)])
    x0, x1 = int((cx - pw / 2) * w), int((cx + pw / 2) * w)
    y0, y1 = int((cy - ph / 2) * h), min(int((cy + ph / 2) * h), h)
    ops = []
    hue, sat, val = {"green": (rnd.randint(60, 90), rnd.randint(100, 230), rnd.randint(160, 250)),
                     "orange": (rnd.randint(10, 22), rnd.randint(130, 230), rnd.randint(205, 255))}[colour]
    ops.append(["fill", max(x0, 0), max(y0, 0), min(x1, w), y1] + bgr(hue, sat, val))
    pieces = rnd.choice([0, 1, 3, 5, 8])
    if pieces and y1 - y0 > 4:
        span = x1 - x0
        for i in range(pieces):
            lx = x0 + int(span * (0.25 + 0.5 * i / max(pieces, 1)))
            ops.append(["fill", lx, y0 + (y1 - y0) // 5, lx + max(span // 40, 2), y1 - (y1 - y0) // 5, 255, 255, 255])
    return ops


def disc(rnd, size):
    """The round button with a check mark (or an X) in it, under NEXT BATTLE."""
    w, h = size
    cx, cy, r = int(bv.TAP_DONE[0] * w), int(bv.TAP_DONE[1] * h), int(bv.DONE_R * w)
    cx += rnd.choice([0, 0, 0, 3, -3, 12])
    cy += rnd.choice([0, 0, 0, 3, -4, 15])
    r = max(int(r * rnd.choice([1.0, 1.0, 1.0, 0.9, 1.1, 0.5])), 3)
    hue, sat, val = rnd.choice([(93, 205, 148), (93, 205, 148), (88, 150, 120), (100, 220, 200), (60, 200, 150)])
    ops = [["disc", cx, cy, r] + bgr(hue, sat, val)]
    light = bgr(93, 40, rnd.choice([245, 245, 245, 215, 190, 175]))
    q = r // 2
    shape = rnd.choice(["check", "check", "cross", "none", "dash", "slash", "slash", "slash"])
    th = rnd.choice([1, 1, 2, 2, 3, 4, max(r // 6, 1)])
    if shape == "check":
        ops.append(["line", cx - q, cy, cx - q // 3, cy + q, *light, th])
        ops.append(["line", cx - q // 3, cy + q, cx + q, cy - q, *light, th])
    elif shape == "cross":
        ops.append(["line", cx - q, cy - q, cx + q, cy + q, *light, th])
        ops.append(["line", cx - q, cy + q, cx + q, cy - q, *light, th])
    elif shape == "slash":
        ops.append(["line", cx - q, cy + q, cx + q, cy - q, *light, th])
    elif shape == "dash":
        ops.append(["line", cx - q, cy, cx + q, cy, *light, th])
    if rnd.random() < 0.15:
        ops.append(["disc", cx + int(r * 1.4), cy, max(r // 3, 2)] + bgr(93, 205, 148))
    return ops


def tiles(rnd, size):
    """The gold reward tiles of the Battle screen."""
    w, h = size
    ops = []
    for i in range(rnd.choice([0, 1, 2, 3, 3, 4])):
        tw, th = rnd.choice([0.06, 0.10, 0.12, 0.16, 0.24]), rnd.choice([0.03, 0.06, 0.08, 0.10, 0.20])
        cx = 0.12 + 0.25 * i + rnd.choice([0, 0.01, -0.02])
        cy = rnd.choice([0.80, 0.85, 0.85, 0.90, 0.72])
        ops.append(["fill", int((cx - tw / 2) * w), int((cy - th / 2) * h), int((cx + tw / 2) * w), int((cy + th / 2) * h)]
                   + bgr(rnd.choice([14, 16, 20, 9, 26]), rnd.choice([200, 160, 110]), rnd.choice([240, 215, 190])))
        if rnd.random() < 0.4:
            ops.append(["fill", int(cx * w) - 3, int((cy - th / 4) * h), int(cx * w) + 3, int((cy + th / 4) * h), 255, 255, 255])
    return ops


def versus_line(rnd, names):
    """The white line of the VS screen, over part of the width."""
    w, h = FULL
    ops = [["load", rnd.choice(names)], ["size", w, h, cv2.INTER_LINEAR]]
    if rnd.random() < 0.5:
        ops = [["blank", w, h] + rnd.choice([[40, 30, 30], [90, 60, 20], [20, 20, 20]])]
    cover = rnd.uniform(0.70, 1.0)
    ops.append(["fill", int(0.02 * w), int(0.496 * h), int((0.02 + 0.96 * cover) * w), int(0.504 * h), 255, 255, 255])
    if rnd.random() < 0.3:                      # (a gap in it)
        gap = rnd.uniform(0.1, 0.9)
        ops.append(["fill", int(gap * w), int(0.496 * h), int((gap + 0.03) * w), int(0.504 * h), 40, 30, 30])
    return ops


def banner_contrast(rnd):
    """A frame with the banner "Get Ready!" made flatter, darker or brighter: from clear to not there."""
    w, h = FULL
    name = rnd.choice(["day_get_ready.jpg", "day2_get_ready.jpg", "day3_get_ready_sky.jpg", "day_get_ready_fading.jpg"])
    return [["load", name], ["size", w, h, cv2.INTER_LINEAR],
            ["scale", round(rnd.uniform(0.08, 0.7), 3), rnd.choice([0, 0, 20, 45, 80])]]


def hud_covered(rnd, names):
    """A fight with parts of the name boxes covered (a banner, an attack), so the light part of a box is small."""
    w, h = FULL
    ops = [["load", rnd.choice(["day_lit.jpg", "fight_ready.jpg", "day2_last.jpg", "fight_lanturn.jpg",
                                "day3_win.jpg", "day_dim.jpg", "run2_dim.jpg"])], ["size", w, h, cv2.INTER_LINEAR]]
    for side in ((0.03, 0.39), (0.61, 0.97)):
        for _ in range(rnd.choice([0, 1, 2, 3, 4])):
            x0 = rnd.uniform(side[0], side[1] - 0.05)
            x1 = min(x0 + rnd.uniform(0.03, 0.2), side[1])
            y0, y1 = rnd.choice([(0.115, 0.158), (0.115, 0.19), (0.183, 0.19), (0.12, 0.15)])
            ops.append(["fill", int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)] + rnd.choice([[60, 50, 50], [30, 30, 30], [230, 160, 90]]))
    return ops


def hud_thin(rnd):
    """The name boxes covered but for the part with the Poké Balls: what is left of the light part is small."""
    w, h = FULL
    ops = [["load", rnd.choice(["day_lit.jpg", "fight_ready.jpg", "day2_last.jpg", "fight_lanturn.jpg", "day3_win.jpg"])],
           ["size", w, h, cv2.INTER_LINEAR]]
    dark = [60, 50, 50]
    cut_me, cut_foe = rnd.uniform(0.17, 0.39), rnd.uniform(0.61, 0.83)
    ops.append(["fill", int(cut_me * w), int(0.115 * h), int(0.39 * w), int(0.19 * h)] + dark)
    ops.append(["fill", int(0.03 * w), int(0.115 * h), int(cut_me * w), int(rnd.uniform(0.150, 0.158) * h)] + dark)
    ops.append(["fill", int(0.61 * w), int(0.115 * h), int(cut_foe * w), int(0.19 * h)] + dark)
    ops.append(["fill", int(cut_foe * w), int(0.115 * h), int(0.97 * w), int(rnd.uniform(0.150, 0.158) * h)] + dark)
    return ops


def result_pill(rnd, names):
    """NEXT BATTLE: a green pill at the place of the button, not always exactly there."""
    w, h = FULL
    ops = [["load", rnd.choice(names)], ["size", w, h, cv2.INTER_LINEAR]]
    if rnd.random() < 0.4:
        ops = [["blank", w, h] + rnd.choice([[40, 30, 30], [235, 235, 235], [90, 90, 90]])]
    pw, ph = rnd.uniform(0.2, 0.55), rnd.uniform(0.025, 0.07)
    cy = rnd.uniform(0.84, 0.89)
    x0, x1 = int((0.5 - pw / 2) * w), int((0.5 + pw / 2) * w)
    ops.append(["fill", x0, int((cy - ph / 2) * h), x1, int((cy + ph / 2) * h)] + bgr(rnd.randint(60, 85), rnd.randint(110, 220), rnd.randint(170, 245)))
    for i in range(rnd.choice([0, 3, 5])):
        lx = x0 + int((x1 - x0) * (0.3 + 0.12 * i))
        ops.append(["fill", lx, int((cy - ph / 4) * h), lx + 5, int((cy + ph / 4) * h), 255, 255, 255])
    return ops


def recipes(names):
    rnd = random.Random(SEED)
    out = []
    for name in names:
        out.append([["load", name], ["size", FULL[0], FULL[1], cv2.INTER_LINEAR]])
        out.append([["load", name]])
        out.append([["load", name], ["size", HALF[0], HALF[1], cv2.INTER_AREA]])
        for _ in range(1):
            out.append([["load", name], ["size", FULL[0], FULL[1], cv2.INTER_LINEAR],
                        ["scale", rnd.choice([0.5, 0.6, 0.8, 1.2, 1.5]), rnd.choice([-30, -10, 0, 15, 40])]])
    for _ in range(24):
        out.append(versus_line(rnd, names))
    for _ in range(30):
        out.append(banner_contrast(rnd))
    for _ in range(30):
        out.append(hud_covered(rnd, names))
    for _ in range(30):
        out.append(hud_thin(rnd))
    for _ in range(30):
        out.append(result_pill(rnd, names))
    for v in (255, 250, 246, 244, 200, 0):       # a white screen (the game between two screens), a black one
        out.append([["blank", FULL[0], FULL[1], v, v, v]])
    for _ in range(120):                        # parts of one frame on another
        ops = [["load", rnd.choice(names)], ["size", FULL[0], FULL[1], cv2.INTER_LINEAR]]
        for _ in range(rnd.choice([1, 1, 2, 3])):
            ops.append(["paste", rnd.choice(names)] + rect(rnd, FULL))
        if rnd.random() < 0.25:
            ops.append(["blend", rnd.choice(names), rnd.choice([0.2, 0.5, 0.75])])
        if rnd.random() < 0.25:
            ops.append(["scale", rnd.choice([0.7, 0.9, 1.1]), rnd.choice([-12, 0, 12])])
        if rnd.random() < 0.3:
            ops.append(["size", HALF[0], HALF[1], cv2.INTER_AREA])
        out.append(ops)
    for _ in range(110):                        # made-up buttons
        size = FULL if rnd.random() < 0.7 else HALF
        ops = [["load", rnd.choice(names)], ["size", size[0], size[1], cv2.INTER_LINEAR]]
        if rnd.random() < 0.3:
            ops = [["blank", size[0], size[1]] + rnd.choice([[40, 30, 30], [235, 235, 235], [90, 160, 80], [20, 20, 20]])]
        for _ in range(rnd.choice([1, 1, 2, 3])):
            ops += pill(rnd, size, rnd.choice(["green", "green", "orange"]))
        out.append(ops)
    for _ in range(40):                         # made-up gold tiles
        size = FULL if rnd.random() < 0.7 else HALF
        ops = [["load", rnd.choice(names)], ["size", size[0], size[1], cv2.INTER_LINEAR]]
        out.append(ops + tiles(rnd, size))
    for _ in range(100):                        # made-up check marks
        size = FULL if rnd.random() < 0.8 else HALF
        ops = [["load", rnd.choice(names)], ["size", size[0], size[1], cv2.INTER_LINEAR]]
        if rnd.random() < 0.5:
            ops = [["blank", size[0], size[1]] + rnd.choice([[30, 30, 30], [240, 240, 240], [80, 90, 70]])]
        if rnd.random() < 0.5:
            ops += pill(rnd, size, "green")
        out.append(ops + disc(rnd, size))
    return out


def build():
    names = sorted(n for n in os.listdir(FIGHT) if n.endswith(".jpg"))
    cases, failed = [], 0
    for ops in recipes(names):
        img = run(ops)
        try:
            cases.append({"ops": ops, "a": answers(img)})
        except Exception as error:               # (a reader that cannot read such a picture: the case is left out)
            failed += 1
            print("left out:", ops[:2], repr(error)[:80], file=sys.stderr)
    return {"cv2": cv2.__version__, "fixtures": names, "cases": cases, "left_out": failed}


def text():
    return json.dumps(build(), ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n"


def close(new, old, key=False):
    """Two answers that only differ as another OpenCV version makes them differ: a pixel of a resized picture
    that is a step off (the fingerprints of the names: three steps of 255 at most) or a bar that is a few pixels
    wider."""
    if isinstance(new, dict) and isinstance(old, dict):
        return new.keys() == old.keys() and all(close(new[k], old[k], k == "keys" or key) for k in new)
    if isinstance(new, list) and isinstance(old, list):
        return len(new) == len(old) and all(close(a, b, key) for a, b in zip(new, old))
    if key and isinstance(new, str) and isinstance(old, str) and len(new) == len(old):
        a, b = bytes.fromhex(new), bytes.fromhex(old)
        return all(abs(x - y) <= 3 for x, y in zip(a, b))
    return new == old


def check(raw):
    """0 when the golden file is what battle_vision.py reads now.  With the OpenCV that made the file that is
    exactly (to the letter); another version of OpenCV resizes and converts a few pixels differently (they are
    the same pixels in C++ and in Python of the same version), so then the recipes have to be the same and
    almost all of the answers (97 %)."""
    with open(OUT, "rb") as handle:
        packed = handle.read()
    if len(packed) > 4 and struct.unpack(">I", packed[:4])[0] == len(raw) and zlib.decompress(packed[4:]) == raw:
        print("vision_golden.json.qz is what battle_vision.py reads")
        return 0
    old, new = json.loads(zlib.decompress(packed[4:])), json.loads(raw)
    if old["cv2"] == new["cv2"]:
        print("vision_golden.json.qz is NOT what battle_vision.py reads (OpenCV %s made it, too)" % new["cv2"])
        return 1
    if len(old["cases"]) != len(new["cases"]) or any(a["ops"] != b["ops"] for a, b in zip(old["cases"], new["cases"])):
        print("vision_golden.json.qz is NOT what battle_vision.py reads (other pictures)")
        return 1
    differ = sum(0 if close(b["a"], a["a"]) else 1 for a, b in zip(old["cases"], new["cases"]))
    allowed = int(0.03 * len(new["cases"]))
    print("vision_golden.json.qz was made with OpenCV %s, this is %s: %d of %d pictures are read differently "
          "(%d are allowed for the difference of the versions)" % (old["cv2"], new["cv2"], differ, len(new["cases"]),
                                                                    allowed))
    return 0 if differ <= allowed else 1


def coverage():
    path = os.path.join(ROOT, "battle_vision.py")
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
