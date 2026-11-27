#!/usr/bin/env python3
"""Makes tests/fixtures/start_golden.json.qz (JSON, packed the way qCompress() of Qt does: the length, then zlib): what gamebot.py and
spin_stop.py do when Pokémon GO is started, and what auto_battle() does before the battles - as the file that the C++ port of
that (SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoStart.cpp) is tested against.

    python3 tools/make_start_golden.py            writes the file
    python3 tools/make_start_golden.py --check    says whether the file is what the code does now (the stories stored in it are played again)

The file has four parts:
  buttons    pictures (white, with filled rectangles of colour) and what find_pill_button() and S.find_green_button() found on them
  options    the settings of the battles (battle_app(), battle_league(), battle_count(), battle_wanted()) and what they make of them
  constants  the numbers and texts of the start-up
  cases      stories, as lists of EVENTS with the time of a fake clock (it starts at 1000.0 and only moves with the screenshots,
             the readings and the sleeps).  A story is the start-up of the game (S.restart_game()), the look at one screenshot while
             the game is starting (startup_screen()) or auto_battle().  What the code is GIVEN:
               screenshot, screenshot_fail     the screenshot (made as make_picture() says), or the message of the phone that did not answer
               ocr                             the text reader (tesseract) was given a strip of the screen (rows, columns, the mean of the grey strip) and
                                               wrote the text (as it is written: small letters, line ends, the form feed), or did not answer (null)
               start_state                     the game that is starting: still running?, the return code, what it wrote on stderr
             what it DOES (the C++ port has to do the same, in this order):
               tap, log, sleep, stop_game, start_game, kill, beat, run (the battles that are started), and at the end
               result (what it returned) or raised ("interrupt" or "error")."""
import argparse
import hashlib
import json
import os
import random
import struct
import sys
import tempfile
import types
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.environ["HOME"] = tempfile.mkdtemp()               # (no team, no settings and no memory of other days)
sys.path.insert(0, ROOT)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import battle_engine as BE  # noqa: E402
import gamebot as G  # noqa: E402
import spin_stop as S  # noqa: E402

OUT = os.path.join(ROOT, "tests", "fixtures", "start_golden.json.qz")
W, H = 1768, 2208
START = 1000.0                                          # the clock of the fake phone starts here
PACKAGE = "com.nianticlabs.pokemongo"


# ---------------------------------------------------------------------- the pictures

_pictures = {}


def make_picture(spec):
    """A picture of the canvas (1768 x 2208): ["white"], or ["rect", [[y0, y1, x0, x1, [b, g, r]], ...]] (white with filled rectangles,
    the places are fractions of the picture)."""
    key = json.dumps(spec)
    if key in _pictures:
        return _pictures[key]
    img = np.full((H, W, 3), 255, np.uint8)
    if spec[0] == "rect":
        for y0, y1, x0, x1, colour in spec[1]:
            img[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)] = colour
    elif spec[0] != "white":
        raise ValueError(spec)
    _pictures[key] = img
    return img


def rect(*items):
    return ["rect", [list(i) for i in items]]


def bgr(h, s, v):
    """The colour (BGR) of an HSV colour of OpenCV."""
    return [int(c) for c in cv2.cvtColor(np.uint8([[[h, s, v]]]), cv2.COLOR_HSV2BGR)[0, 0]]


_hsv_all = {}


def exact(h, s, v):
    """A colour (BGR) that OpenCV turns into exactly this HSV (all 16.7 million colours are looked at once, the first time)."""
    if not _hsv_all:
        grid = np.indices((256, 256), dtype=np.uint8)                # (axis 0, axis 1) = (g, r)
        for b in range(256):
            img = np.dstack([np.full((256, 256), b, np.uint8), grid[0], grid[1]])
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            key = hsv[..., 0].astype(np.int64) * 65536 + hsv[..., 1].astype(np.int64) * 256 + hsv[..., 2]
            for k, idx in zip(*np.unique(key, return_index=True)):
                if int(k) not in _hsv_all:
                    _hsv_all[int(k)] = (b, int(idx) // 256, int(idx) % 256)
    found = _hsv_all[h * 65536 + s * 256 + v]
    return [int(c) for c in found]


def near(h, s, v):
    """exact(), but a saturation or a value that no colour has is taken a step higher or lower (a colour is a whole number of levels)."""
    for step in (0, 1, -1, 2, -2, 3, -3):
        for ds, dv in ((step, 0), (0, step)):
            key = h * 65536 + (s + ds) * 256 + (v + dv)
            exact(h, 150, 220)
            if key in _hsv_all:
                return [int(c) for c in _hsv_all[key]]
    raise KeyError((h, s, v))


def with_saturation(h, s):
    """A colour with exactly this saturation (the value is 180 - 247, where one is found)."""
    exact(h, 150, 220)
    for v in range(240, 180, -1):
        if h * 65536 + s * 256 + v in _hsv_all:
            return [int(c) for c in _hsv_all[h * 65536 + s * 256 + v]]
    raise KeyError((h, s))


def px(x, y, w, h, colour):
    """A rectangle of w x h pixels with its top left corner at (x, y), as the places (fractions) that make exactly those pixels."""
    return [round((y + 0.5) / H, 9), round((y + h + 0.5) / H, 9), round((x + 0.5) / W, 9), round((x + w + 0.5) / W, 9), colour]


GREEN = [120, 205, 110]                                 # the green of a button (H 60, S 107, V 205)
PALE = [190, 252, 200]                                  # a green that is too bright for the pill (V 252)
DARK = [60, 120, 55]                                    # ... and one that is too dark (V 120)
RED = [0, 0, 220]
PILL = [0.90, 0.95, 0.32, 0.68, GREEN]                  # 636 x 110 pixels in the middle, near the bottom
MAP = [0.8725, 0.8760, 0.49, 0.51, RED]                 # the red top of the Poké Ball button (rows 1926 - 1934, where row 1930 is looked at)
NEWS_TEXT = "POKEMON GO X DUOLINGO SEE DETAILS DISMISS"
NOTICE_TEXT = "STAY AWARE OF YOUR SURROUNDINGS DO NOT TRESPASS OK"


# ---------------------------------------------------------------------- the buttons

def button_cases():
    cases = []

    def add(name, pic, y_min=1500):
        img = make_picture(pic)
        pill = G.find_pill_button(img, y_min) if y_min != 1500 else G.find_pill_button(img)
        green = S.find_green_button(img)
        cases.append({"id": name, "pic": pic, "y_min": y_min, "pill": list(pill) if pill else None, "green": list(green) if green else None})

    add("white", ["white"])
    add("pill", rect(PILL))
    add("pill_dark", rect([0.90, 0.95, 0.32, 0.68, DARK]))
    add("pill_pale", rect([0.90, 0.95, 0.32, 0.68, PALE]))
    add("pill_red", rect([0.90, 0.95, 0.32, 0.68, RED]))
    add("pill_narrow", rect([0.90, 0.95, 0.40, 0.60, GREEN]))              # 354 wide (a pill is 450 - 1300)
    add("pill_just_wide_enough", rect([0.90, 0.95, 0.38, 0.64, GREEN]))
    add("pill_wide", rect([0.90, 0.95, 0.0, 0.8, GREEN]))
    add("pill_tall", rect([0.85, 0.99, 0.32, 0.68, GREEN]))                  # 309 px high: too high for 2.5 x its height? w 636 > 772 no
    add("pill_tall2", rect([0.80, 0.99, 0.32, 0.68, GREEN]))
    add("pill_short", rect([0.90, 0.91, 0.32, 0.68, GREEN]))                 # 22 px (a pill is 80 - 320)
    add("pill_off_left", rect([0.90, 0.95, 0.05, 0.40, GREEN]))
    add("pill_off_right", rect([0.90, 0.95, 0.60, 0.95, GREEN]))
    add("pill_a_bit_off", rect([0.90, 0.95, 0.40, 0.76, GREEN]))
    add("pill_above", rect([0.50, 0.55, 0.32, 0.68, GREEN]))                  # above y_min (1500)
    add("pill_cut", rect([0.66, 0.72, 0.32, 0.68, GREEN]))                    # the top is cut off by y_min
    add("pill_y_min_0", rect([0.50, 0.55, 0.32, 0.68, GREEN]), 0)
    add("pill_y_min_1900", rect([0.80, 0.84, 0.32, 0.68, GREEN], [0.90, 0.95, 0.40, 0.76, GREEN]), 1900)
    add("two", rect([0.76, 0.81, 0.32, 0.68, GREEN], [0.90, 0.95, 0.30, 0.70, GREEN]))
    add("green_two_same", ["rect", [px(434, 1500, 900, 100, GREEN), px(434, 1800, 900, 100, GREEN)]])
    add("two_same", rect([0.76, 0.81, 0.32, 0.68, GREEN], [0.90, 0.95, 0.32, 0.68, GREEN]))
    add("pill_hole", rect(PILL, [0.92, 0.93, 0.45, 0.55, [255, 255, 255]]))   # a label on the button (white marks)
    add("pill_gap", rect([0.90, 0.95, 0.32, 0.49, GREEN], [0.90, 0.95, 0.495, 0.68, GREEN]))     # two halves 8 px apart (closed by the 25 x 25 kernel)
    add("pill_gap_far", rect([0.90, 0.95, 0.32, 0.45, GREEN], [0.90, 0.95, 0.55, 0.68, GREEN]))
    add("pill_speck", rect(PILL, [0.80, 0.8030, 0.10, 0.1051, GREEN]))
    # the green button of the whole screen (find_green_button: the lower half, wide, in the middle)
    add("green_button", rect([0.86, 0.91, 0.25, 0.75, GREEN]))
    add("green_upper_half", rect([0.20, 0.25, 0.25, 0.75, GREEN]))
    add("green_across", rect([0.40, 0.60, 0.25, 0.75, GREEN]))                 # (cut at the middle of the screen)
    add("green_small", rect([0.86, 0.91, 0.40, 0.60, GREEN]))
    add("green_off", rect([0.86, 0.91, 0.55, 0.95, GREEN]))
    add("green_thin", rect([0.86, 0.8645, 0.25, 0.75, GREEN]))
    add("green_square", rect([0.70, 0.90, 0.40, 0.60, GREEN]))
    add("green_just_off_centre", rect([0.86, 0.91, 0.32, 0.92, GREEN]))
    add("green_just_centre", rect([0.86, 0.91, 0.30, 0.80, GREEN]))
    # the colours (hue 45 - 95, saturation over 62 (the pill) or 55 (the button), value over 170 and under 248 (the pill))
    for name, hsv in (("h44", (44, 150, 220)), ("h45", (45, 150, 220)), ("h95", (95, 150, 220)), ("h96", (96, 150, 220)),
                      ("s54", (60, 54, 220)), ("s56", (60, 56, 220)), ("s62", (60, 62, 220)), ("s64", (60, 64, 220)),
                      ("v169", (60, 150, 169)), ("v171", (60, 150, 171)), ("v247", (60, 150, 247)), ("v248", (60, 150, 248)),
                      ("v249", (60, 150, 249)), ("v255", (60, 150, 255))):
        colour = bgr(*hsv)
        add("pill_" + name, rect([0.90, 0.95, 0.32, 0.68, colour]))
        add("green_" + name, rect([0.86, 0.91, 0.25, 0.75, colour]))
    # the colours to the last step: exactly this hue, saturation and value (the pill: H 45 - 95, S over 62, V 171 - 247; the button: S over 55, V over 170)
    colours = {}
    for hue in (44, 45, 46, 94, 95, 96):
        colours["h%d" % hue] = near(hue, 150, 220)
    for sat in (54, 55, 56, 61, 62, 63, 64):
        colours["s%d" % sat] = with_saturation(60, sat)
    for val in (169, 170, 171, 246, 247, 248, 254, 255):
        colours["v%d" % val] = near(60, 150, val)
    for name, colour in colours.items():
        add("exact_pill_" + name, ["rect", [px(434, 1980, 900, 110, colour)]])
        add("exact_green_" + name, ["rect", [px(384, 1600, 1000, 330, colour)]])
    # the sizes to the last pixel: a pill is 451 - 1299 wide, 81 - 319 high, wider than 2.5 times its height and in the middle (+-299)
    for w in (449, 450, 451, 1299, 1300, 1301):
        add("pill_width_%d" % w, ["rect", [px(884 - w // 2, 1900, w, 100, GREEN)]])
    for h in (79, 80, 81, 319, 320, 321):
        add("pill_height_%d" % h, ["rect", [px(434, 1800, 900, h, GREEN)]])
    for w in (499, 500, 501):
        add("pill_ratio_%d" % w, ["rect", [px(884 - w // 2, 1800, w, 200, GREEN)]])
    for d in (-301, -300, -299, 299, 300, 301):
        add("pill_centre_%+d" % d, ["rect", [px(884 + d - 300, 1900, 600, 100, GREEN)]])
    # ... and of the green button: over 700 wide, over 60 high, wider than 2.2 times its height, in the middle (+-199)
    for w in (699, 700, 701):
        add("green_width_%d" % w, ["rect", [px(884 - w // 2, 1600, w, 100, GREEN)]])
    for h in (59, 60, 61):
        add("green_height_%d" % h, ["rect", [px(434, 1600, 900, h, GREEN)]])
    for w in (859, 860, 879, 880, 881):
        add("green_ratio_%d" % w, ["rect", [px(884 - w // 2, 1500, w, 400, GREEN)]])
    for d in (-201, -200, -199, 199, 200, 201):
        add("green_centre_%+d" % d, ["rect", [px(884 + d - 450, 1600, 900, 100, GREEN)]])
    # the number of pixels of the button (over 20000): a frame of 800 x 100 pixels (the rest is white) with sides of 25 and a top and bottom of 8 - 12
    for t in (8, 9, 10, 11, 12):
        top = 1600
        bars = [px(484, top, 800, t, GREEN), px(484, top + 100 - t, 800, t, GREEN), px(484, top, 25, 100, GREEN), px(484 + 775, top, 25, 100, GREEN)]
        add("green_frame_%d" % t, ["rect", bars])
    add("green_frame_20000", ["rect", [px(484, 1600, 800, 10, GREEN), px(484, 1690, 800, 10, GREEN), px(484, 1600, 25, 100, GREEN), px(484 + 775, 1600, 25, 100, GREEN)]])
    add("green_frame_20160", ["rect", [px(484, 1600, 800, 10, GREEN), px(484, 1690, 800, 10, GREEN), px(484, 1600, 26, 100, GREEN), px(484 + 774, 1600, 26, 100, GREEN)]])
    # two blocks and what is between them: an open gap (the 25 x 25 kernel of the closing joins gaps up to 24 pixels) ...
    for gap in (23, 24, 25, 26, 27):
        add("pill_gap_%d" % gap, ["rect", [px(884 - 330 - gap // 2, 1900, 330, 100, GREEN), px(884 + gap - gap // 2, 1900, 330, 100, GREEN)]])
        add("green_gap_%d" % gap, ["rect", [px(884 - 450 - gap // 2, 1600, 450, 100, GREEN), px(884 + gap - gap // 2, 1600, 450, 100, GREEN)]])
    # ... a thin bridge (the 9 x 9 kernel of the opening removes what is thinner than 9 pixels)
    for bridge in (7, 8, 9, 10, 11):
        add("pill_bridge_%d" % bridge, ["rect", [px(494, 1900, 390, 100, GREEN), px(914, 1900, 390, 100, GREEN), px(884, 1950 - bridge // 2, 30, bridge, GREEN)]])
    # random scenes: one to three rectangles in the lower part, most of them in the colours of a button
    rng = random.Random(2026)
    for n in range(260):
        items = []
        for _ in range(rng.randint(1, 3)):
            if rng.random() < 0.85:
                colour = bgr(rng.randint(40, 100), rng.randint(40, 255), rng.randint(150, 255))
            else:
                colour = [rng.randint(0, 255) for _ in range(3)]
            width, height = rng.randint(250, 1500), rng.randint(40, 420)
            cx, top = int(rng.gauss(884, 220)), rng.randint(900 if rng.random() < 0.3 else 1400, 2100)
            x0, x1 = max(cx - width // 2, 0), min(cx + width // 2, W)
            y0, y1 = top, min(top + height, H)
            items.append([round(y0 / H, 4), round(y1 / H, 4), round(x0 / W, 4), round(x1 / W, 4), colour])
        add("random_%03d" % n, ["rect", items], rng.choice((1500, 1500, 1500, 0, 1100, 1800)))
    return cases


# ---------------------------------------------------------------------- the settings of the battles

SETTINGS = [
    {},
    {"battle": True},
    {"battle": False, "battle_app": "com.example.second"},
    {"battle": True, "battle_app": "com.example.second", "battle_league": "Ultra League", "battle_count": 3},
    {"battle": True, "battle_league": "  Master League  ", "battle_count": 0},
    {"battle": True, "battle_league": "", "battle_count": -4},
    {"battle": True, "battle_league": "   ", "battle_count": 51},
    {"battle": True, "battle_league": "x" * 45, "battle_count": 50},
    {"battle": True, "battle_league": "y" * 40, "battle_count": 1},
    {"battle": True, "battle_league": "  " + "w" * 45, "battle_count": 3},
    {"battle": True, "battle_league": "v" * 39 + "  uuu", "battle_count": 3},
    {"battle": True, "battle_league": "z" * 41, "battle_count": None},
    {"battle": True, "battle_app": "", "battle_count": 7},
    {"battle": 0, "battle_count": 12},
    {"battle": 1, "battle_count": 49},
    {"battle": True, "battle_league": "Great League", "battle_count": 2, "battle_app": "com.nianticlabs.pokemongo"},
]


def option_cases():
    cases = []
    for settings in SETTINGS:
        for done in (False, True):
            G.setting = lambda key, default, settings=settings: settings.get(key, default)
            G.battles_done_today = lambda mark=False, done=done: done
            cases.append({"settings": settings, "done": done, "wanted": bool(G.battle_wanted()), "app": G.battle_app(),
                          "league": G.battle_league(), "count": G.battle_count()})
    return cases


# ---------------------------------------------------------------------- the clock and the notes

class Clock:
    """time.time(), time.monotonic() and time.sleep() of the fake phone."""
    t = START
    rec = None

    @staticmethod
    def monotonic():
        return Clock.t

    @staticmethod
    def time():
        return Clock.t

    @staticmethod
    def sleep(seconds):
        Clock.rec.add("sleep", seconds)
        Clock.t += seconds

    @staticmethod
    def strftime(*a):
        return "2026-11-22"


class Rec:
    def __init__(self):
        self.events = []

    def add(self, kind, *rest):
        self.events.append([kind, Clock.t] + list(rest))


def mean(img):
    return round(float(img.mean()), 2)


# ---------------------------------------------------------------------- the screens of the fake phone

SCENES = {
    "loading": {"pic": ["white"]},
    "news": {"pic": ["white"], "news": NEWS_TEXT},
    "news_in_a_word": {"pic": ["white"], "news": "SEE DETAILS DISMISSED"},
    "news_misread": {"pic": ["white"], "news": "SEE DETAILS DISMIS5"},
    "notice": {"pic": rect(PILL), "notice": NOTICE_TEXT},
    "notice_trespass": {"pic": rect(PILL), "notice": "DO NOT TRESPASS"},
    "notice_driving": {"pic": rect(PILL), "notice": "DO NOT PLAY WHILE DRIVING"},
    "notice_dangerous": {"pic": rect(PILL), "notice": "AVOID DANGEROUS AREAS"},
    "notice_other": {"pic": rect(PILL), "notice": "WELCOME BACK TRAINER"},
    "notice_pale": {"pic": rect([0.86, 0.91, 0.25, 0.75, PALE]), "notice": NOTICE_TEXT},
    "notice_none": {"pic": ["white"], "notice": NOTICE_TEXT},
    "notice_dark": {"pic": rect([0.90, 0.95, 0.32, 0.68, DARK]), "notice": NOTICE_TEXT},
    "notice_surroundings": {"pic": rect(PILL), "notice": "STAY AWARE OF YOUR SURROUNDINGS"},
    "notice_wrapped_driving": {"pic": rect(PILL), "raw_notice": "Do not play while\n  driving\r\n\x0c"},
    "notice_wrapped_dangerous": {"pic": rect(PILL), "raw_notice": "Avoid dangerous\tareas.\n\n\x0c"},
    "notice_wrapped_other": {"pic": rect(PILL), "raw_notice": "Do not play\nwhile\n\x0c"},
    "notice_two_buttons": {"pic": rect(PILL, [0.80, 0.84, 0.25, 0.75, PALE]), "notice": NOTICE_TEXT},
    "news_mixed_case": {"pic": ["white"], "raw_news": "Pokemon Go x Duolingo\n  See  Details\n\n  Dismiss \n\x0c"},
    "news_wrapped": {"pic": ["white"], "raw_news": "dis\nmiss\n\x0c"},
    "map": {"pic": rect(MAP)},
    "map_news": {"pic": rect(MAP), "news": NEWS_TEXT},
    "map_notice": {"pic": rect(MAP, PILL), "notice": NOTICE_TEXT},
    "news_notice": {"pic": rect(PILL), "news": NEWS_TEXT, "notice": NOTICE_TEXT},
    "ocr_fail": {"pic": ["white"], "fail": "ocr"},
    "shot_fail": {"fail": "shot", "message": "the phone did not answer"},
    "shot_stop": {"fail": "interrupt"},
}


class World:
    def __init__(self, spec):
        self.spec = spec
        self.scene = None
        self.shots = 0

    def look(self, name):
        self.scene = SCENES[name]


def tess(text):
    """What the tesseract program writes for a strip that holds `text`: as it reads it (capitals only at the start of a word),
    a few words to the line, and the form feed that it ends with."""
    words = text.split()
    if not words:
        return "\x0c\n"
    lines = [" ".join(w.capitalize() for w in words[i:i + 3]) for i in range(0, len(words), 3)]
    return "\n".join(lines) + "\n\x0c"


def tesseract(world, rec):
    """The `subprocess` of gamebot.py for gamebot.ocr_text(): the tesseract program, shown a strip of the screen (as the PNG that
    it is given), answers with what the scene says it reads there (`news`: rows 2000 - 2208, `notice`: rows 1100 - 1800); the
    strip that was given and the raw text are what the story records."""
    def run(cmd, env=None, input=None, capture_output=None, timeout=None):
        assert cmd == ["tesseract", "stdin", "stdout", "--psm", "6"], cmd
        assert capture_output is True and timeout == 30, (capture_output, timeout)
        grey = cv2.imdecode(np.frombuffer(input, np.uint8), cv2.IMREAD_UNCHANGED)
        assert grey.ndim == 2, grey.shape
        scene = world.scene
        Clock.t += world.spec.get("ocr_seconds", 0.0)
        if scene.get("fail") == "ocr":
            rec.add("ocr", grey.shape[0], grey.shape[1], mean(grey), None)
            raise RuntimeError("the text reader did not answer")
        kind = {208: "news", 700: "notice"}.get(grey.shape[0], "?")
        raw = scene.get("raw_" + kind)
        if raw is None:
            raw = tess(scene.get(kind, ""))
        rec.add("ocr", grey.shape[0], grey.shape[1], mean(grey), raw)
        return types.SimpleNamespace(stdout=raw.encode())
    return types.SimpleNamespace(run=run)


class FakePopen:
    """The monkey command that starts the game (it is not waited for): still running after `ends` seconds or never."""
    DEVNULL = -3
    PIPE = -1

    def __init__(self, world, rec):
        self.world, self.rec = world, rec

    def popen(self, cmd, stdout=None, stderr=None):
        assert cmd == ["adb", "shell", "monkey", "-p", S.PACKAGE, "-c", "android.intent.category.LAUNCHER", "1"], cmd
        assert stdout == self.DEVNULL and stderr == self.PIPE
        self.rec.add("start_game")
        launch = self.world.spec.get("launch", {})
        started = Clock.t
        rec = self.rec

        class Process:
            returncode = None
            stderr = types.SimpleNamespace(read=lambda: launch.get("stderr", "").encode())

            def poll(self):
                ends = launch.get("ends")
                running = ends is None or Clock.t - started < ends
                code = launch.get("code", 0)
                rec.add("start_state", running, 0 if running else code, launch.get("stderr", ""))
                if running:
                    return None
                self.returncode = code
                return code

            def kill(self):
                rec.add("kill")
        return Process()


def record(spec):
    """Plays one story on the fake phone; returns the list of events."""
    Clock.t = START
    rec = Rec()
    Clock.rec = rec
    world = World(spec)
    saved_g = {n: getattr(G, n) for n in ("time", "log", "setting", "battles_done_today", "battle_run", "subprocess", "run_state")}
    saved_s = {n: getattr(S, n) for n in ("time", "log", "adb", "subprocess", "screenshot", "tap", "startup_hook", "PACKAGE")}
    saved_be = BE.load_team
    try:
        G.time = S.time = Clock
        G.log = S.log = lambda text: rec.add("log", text)
        G.subprocess = tesseract(world, rec)
        S.PACKAGE = PACKAGE
        S.tap = lambda x, y, ms=120: rec.add("tap", x, y)
        S.startup_hook = G.startup_screen

        def adb(*args, binary=False):
            assert args == ("shell", "am", "force-stop", PACKAGE), args
            rec.add("stop_game")
            Clock.t += spec.get("stop_seconds", 0.0)
            if spec.get("stop_fail"):
                raise RuntimeError(spec["stop_fail"])
            return ""
        S.adb = adb
        S.subprocess = types.SimpleNamespace(Popen=lambda *a, **k: FakePopen(world, rec).popen(*a, **k), DEVNULL=FakePopen.DEVNULL, PIPE=FakePopen.PIPE)

        def screenshot(on_grab=None):
            frames = spec["frames"]
            name = frames[min(world.shots, len(frames) - 1)]
            world.shots += 1
            world.look(name)
            if world.scene.get("fail") == "shot":
                Clock.t += spec.get("shot_seconds", 0.0)
                rec.add("screenshot_fail", world.scene["message"])
                raise RuntimeError(world.scene["message"])
            if world.scene.get("fail") == "interrupt":
                rec.add("screenshot_fail", "interrupt")
                raise KeyboardInterrupt()
            Clock.t += spec.get("shot_seconds", 0.0)
            rec.add("screenshot", world.scene["pic"])
            return make_picture(world.scene["pic"])
        S.screenshot = screenshot

        call = spec["call"]
        try:
            if call == "restart":
                S.restart_game()
                rec.add("result", None)
            elif call == "startup":
                result = G.startup_screen(S.screenshot())
                rec.add("result", result)
            elif call == "auto":
                rec.add("result", *auto(spec, rec))
        except KeyboardInterrupt:
            rec.add("raised", "interrupt", "")
        except Exception as e:  # noqa: BLE001
            rec.add("raised", "error", str(e))
        return rec.events
    finally:
        for n, v in saved_g.items():
            setattr(G, n, v)
        for n, v in saved_s.items():
            setattr(S, n, v)
        BE.load_team = saved_be


def auto(spec, rec):
    """auto_battle(): returns [what it returned, battle_resume of run_state or None]."""
    settings, done = spec["settings"], spec["done"]
    G.setting = lambda key, default: settings.get(key, default)
    G.battles_done_today = lambda mark=False: done
    G.run_state = dict(G.run_state)
    G.run_state.pop("battle_resume", None)

    def load_team(path=None):
        if spec.get("team_error"):
            raise RuntimeError(spec["team_error"])
        return [types.SimpleNamespace(label=n) for n in spec["team"]]
    BE.load_team = load_team

    def battle_run(beat, stop, count, team=None, no_more=None):
        rec.add("run", count, [m.label for m in team])
        return dict(spec["run"])
    G.battle_run = battle_run
    fought = G.auto_battle(spec["package"], lambda: rec.add("beat"), lambda: False, lambda: False)
    return [fought, G.run_state.get("battle_resume")]


def stories():
    out = []

    def add(name, spec):
        spec.setdefault("shot_seconds", 0.4)
        spec.setdefault("ocr_seconds", 0.5)
        out.append({"id": name, "spec": spec})

    # --- one look at a screenshot while the game is starting
    for scene in ("loading", "news", "news_in_a_word", "news_misread", "notice", "notice_trespass", "notice_driving", "notice_dangerous",
                  "notice_other", "notice_pale", "notice_none", "notice_dark", "map", "map_news", "map_notice", "news_notice", "ocr_fail",
                  "notice_surroundings", "notice_wrapped_driving", "notice_wrapped_dangerous", "notice_wrapped_other", "notice_two_buttons",
                  "news_mixed_case", "news_wrapped"):
        add("look_" + scene, {"call": "startup", "frames": [scene]})
    add("look_screenshot_fails", {"call": "startup", "frames": ["shot_fail"]})
    add("look_without_waiting", {"call": "startup", "frames": ["notice"], "shot_seconds": 0.0, "ocr_seconds": 0.0})

    # --- the start of the game: stop it, start it, look at the screen until the map is there
    add("start_map_at_once", {"call": "restart", "frames": ["map"], "stop_seconds": 0.3})
    add("start_loading_then_map", {"call": "restart", "frames": ["loading", "loading", "map", "map"], "stop_seconds": 0.8,
                                    "launch": {"ends": 3.0, "code": 0}})
    add("start_news_then_map", {"call": "restart", "frames": ["loading", "news", "loading", "map", "map"], "stop_seconds": 1.2,
                                 "launch": {"ends": 9.0, "code": 0}})
    add("start_notice_then_map", {"call": "restart", "frames": ["loading", "notice", "map", "map"], "stop_seconds": 1.3})
    add("start_every_card", {"call": "restart", "frames": ["loading", "news", "news", "notice_pale", "notice_none", "loading", "map", "map"],
                              "stop_seconds": 2.7, "shot_seconds": 1.3})
    add("start_map_once_only", {"call": "restart", "frames": ["map", "loading", "map", "map"], "launch": {"ends": 1.0, "code": 0}})
    add("start_map_then_news", {"call": "restart", "frames": ["map", "news", "map", "map"]})
    add("start_map_then_notice", {"call": "restart", "frames": ["map", "notice", "map", "map"]})
    add("start_launch_fails", {"call": "restart", "frames": ["loading", "map", "map"], "shot_seconds": 0.43,
                                "launch": {"ends": 0.5, "code": 1, "stderr": "  Error: no activities found to run, monkey aborted.\n"}})
    add("start_launch_fails_quietly", {"call": "restart", "frames": ["loading", "map", "map"], "shot_seconds": 0.43, "launch": {"ends": 0.5, "code": 252, "stderr": ""}})
    add("start_launch_fails_long", {"call": "restart", "frames": ["map", "map"],
                                     "launch": {"ends": 0.5, "code": 1, "stderr": "x" * 200}})
    add("start_launch_ends_well", {"call": "restart", "frames": ["map", "map"], "launch": {"ends": 0.5, "code": 0, "stderr": "ignored"}})
    add("start_launch_still_running", {"call": "restart", "frames": ["loading", "map", "map"], "shot_seconds": 0.43, "launch": {"ends": 600.0, "code": 0}})
    add("start_ocr_fails_once", {"call": "restart", "frames": ["loading", "ocr_fail", "map", "map"]})
    add("start_screenshot_fails_once", {"call": "restart", "frames": ["loading", "shot_fail", "map", "map"]})
    add("start_screenshots_fail", {"call": "restart", "frames": ["shot_fail"], "shot_seconds": 9.0})
    add("start_never_reaches_the_map", {"call": "restart", "frames": ["loading"], "shot_seconds": 7.0, "ocr_seconds": 0.5,
                                         "launch": {"ends": 20.0, "code": 0}})
    add("start_never_reaches_the_map_failed", {"call": "restart", "frames": ["loading"], "shot_seconds": 6.2, "ocr_seconds": 1.0,
                                                "launch": {"ends": 5.0, "code": 1, "stderr": "monkey: not found"}})
    add("start_only_cards", {"call": "restart", "frames": ["news"], "shot_seconds": 12.0, "ocr_seconds": 1.0})
    add("start_slow_stop", {"call": "restart", "frames": ["map"], "stop_seconds": 12.9})
    add("start_stop_fails", {"call": "restart", "frames": ["map"], "stop_fail": "adb: device offline"})
    add("start_stopped_by_the_person", {"call": "restart", "frames": ["loading", "shot_stop"]})
    add("start_the_first_look_is_late", {"call": "restart", "frames": ["map", "map"], "shot_seconds": 31.5, "stop_seconds": 2.2})
    # the 100 s are counted from the end of the 2 s after the start: the last look is made at 99.4 s, the next ends at 100.8 s
    add("start_the_limit_from_below", {"call": "restart", "frames": ["loading"], "shot_seconds": 1.1, "ocr_seconds": 0.0})
    add("start_the_map_comes_at_the_limit", {"call": "restart", "frames": ["loading"] * 71 + ["map"], "shot_seconds": 1.1, "ocr_seconds": 0.0})
    add("start_the_limit_to_the_tie", {"call": "restart", "frames": ["loading"], "shot_seconds": 99.7, "ocr_seconds": 0.0})   # (exactly 100.0 s)
    add("start_the_limit_from_above", {"call": "restart", "frames": ["loading"], "shot_seconds": 4.6, "ocr_seconds": 0.5})
    add("start_the_second_map_comes_after_the_limit", {"call": "restart", "frames": ["loading", "loading", "map", "map"], "shot_seconds": 31.0, "ocr_seconds": 0.5})

    # --- auto_battle()
    team = ["Medicham", "Azumarill", "Shadow Machamp"]
    run = {"fought": 5, "wins": 4}

    def auto_case(name, package=PACKAGE, settings=None, done=False, run_=run, team_=team, error=None):
        spec = {"call": "auto", "package": package, "settings": {"battle": True} if settings is None else settings, "done": done, "team": team_, "run": run_,
                "frames": ["loading"]}
        if error:
            spec["team_error"] = error
        add(name, spec)

    auto_case("auto_plain")
    auto_case("auto_options", settings={"battle": True, "battle_league": "Ultra League", "battle_count": 12})
    auto_case("auto_not_wanted", settings={"battle": False})
    auto_case("auto_not_wanted_default", settings={})
    auto_case("auto_other_app", package="com.example.second")
    auto_case("auto_the_chosen_app", package="com.example.second", settings={"battle": True, "battle_app": "com.example.second"})
    auto_case("auto_the_other_app_is_chosen", settings={"battle": True, "battle_app": "com.example.second"})
    auto_case("auto_done_today", done=True)
    auto_case("auto_done_today_other_app", package="com.example.second", done=True)
    auto_case("auto_done_today_not_wanted", settings={"battle": False}, done=True)
    auto_case("auto_no_team", error="no team")
    auto_case("auto_empty_team", team_=[])
    auto_case("auto_one_in_the_team", team_=["Medicham"])
    auto_case("auto_leave", run_={"fought": 2, "wins": 1, "leave": True})
    auto_case("auto_catch", run_={"fought": 3, "wins": 1, "catch": True})
    auto_case("auto_catch_and_leave", run_={"fought": 3, "wins": 1, "catch": True, "leave": True})
    auto_case("auto_nothing_fought", run_={"fought": 0, "wins": 0, "leave": True})
    auto_case("auto_catch_false", run_={"fought": 1, "wins": 0, "catch": False, "leave": False})
    return out


CONSTANTS = ("DISMISS_BTN", "NOTICE_OK_BTN", "BATTLE_COUNT")
STRINGS = ("MAIN_PACKAGE", "BATTLE_LEAGUE")


def constants():
    out = {}
    for name in CONSTANTS:
        value = getattr(G, name)
        out[name] = [float(x) for x in value] if isinstance(value, (tuple, list)) else [float(value)]
    return out


def strings():
    return {name: getattr(G, name) for name in STRINGS}


def ties(cases):
    """The numbers of the log line 'Pokémon GO is on the map (... s after starting; closing the old game took ... s, first screenshot after
    ... s)' that are exactly half-way between two rounded ones: Python rounds those to the even one, printf of some C libraries does not."""
    found = []
    for c in cases:
        ev = c["events"]
        if not any(e[0] == "log" and "is on the map" in e[2] for e in ev):
            continue
        begin = ev[0][1]
        stopped = ev[[e[0] for e in ev].index("stop_game") + 1][1] - begin
        first = [e for e in ev if e[0] == "screenshot"][0][1] - begin
        last = [e for e in ev if e[0] == "log" and "is on the map" in e[2]][0][1] - begin
        for name, x, digits in (("elapsed", last, 0), ("stopped", stopped, 1), ("first", first, 0)):
            if abs(x * 10 ** digits % 1 - 0.5) < 1e-9:
                found.append("%s: %s is %r" % (c["id"], name, x))
    return found


def capture():
    cases = [{"id": item["id"], "spec": item["spec"], "events": record(item["spec"])} for item in stories()]
    tied = ties(cases)
    if tied:
        raise SystemExit("numbers that are exactly half-way (they are rounded another way by some C libraries): " + "; ".join(tied))
    return cases


def text(cases=None, buttons=None, options=None):
    doc = {"cv2": cv2.__version__, "start": START, "constants": constants(), "strings": strings(),
           "buttons": button_cases() if buttons is None else buttons,
           "options": option_cases() if options is None else options,
           "cases": capture() if cases is None else cases}
    return json.dumps(doc, separators=(",", ":"), sort_keys=True)


def check():
    with open(OUT, "rb") as handle:
        packed = handle.read()
    old = json.loads(zlib.decompress(packed[4:]))
    new_cases = [{"id": c["id"], "spec": c["spec"], "events": record(c["spec"])} for c in old["cases"]]
    buttons = []
    for c in old["buttons"]:
        img = make_picture(c["pic"])
        pill = G.find_pill_button(img, c["y_min"]) if c["y_min"] != 1500 else G.find_pill_button(img)
        green = S.find_green_button(img)
        buttons.append({"id": c["id"], "pic": c["pic"], "y_min": c["y_min"], "pill": list(pill) if pill else None,
                        "green": list(green) if green else None})
    options = option_cases()
    raw = text(new_cases, buttons, options).encode("utf-8")
    if len(packed) > 4 and struct.unpack(">I", packed[:4])[0] == len(raw) and zlib.decompress(packed[4:]) == raw:
        print("start_golden.json.qz is what the start-up does")
        return 0
    new = json.loads(raw)
    if old.get("constants") != new["constants"] or old.get("strings") != new["strings"] or old.get("options") != new["options"]:
        print("start_golden.json.qz is NOT what the start-up does: the numbers, the texts or the options changed")
        return 1
    differ = [a["id"] for a, b in zip(old["cases"], new["cases"]) if json.dumps(a["events"]) != json.dumps(b["events"])]
    differ += [a["id"] for a, b in zip(old["buttons"], new["buttons"]) if a != b]
    allowed = int(0.05 * (len(old["cases"]) + len(old["buttons"])))
    if old["cv2"] == new["cv2"] or len(differ) > allowed:
        print("start_golden.json.qz is NOT what the start-up does: " + ", ".join(differ[:8]))
        return 1
    print("start_golden.json.qz was made with OpenCV %s, this is %s: %d of %d cases go another way (allowed: %d)"
          % (old["cv2"], new["cv2"], len(differ), len(old["cases"]) + len(old["buttons"]), allowed))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        sys.exit(check())
    raw = text().encode("utf-8")
    with open(OUT, "wb") as handle:
        handle.write(struct.pack(">I", len(raw)) + zlib.compress(raw, 9))
    doc = json.loads(raw)
    found = sum(1 for c in doc["buttons"] if c["pill"] or c["green"])
    print("wrote %s: %d pictures of buttons (%d with a button), %d options, %d stories, %d events, %d bytes of JSON, packed to %d" % (
        OUT, len(doc["buttons"]), found, len(doc["options"]), len(doc["cases"]), sum(len(c["events"]) for c in doc["cases"]), len(raw),
        os.path.getsize(OUT)))
