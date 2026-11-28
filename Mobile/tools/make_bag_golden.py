#!/usr/bin/env python3
"""Makes tests/fixtures/bag_golden.json.qz (JSON, packed the way qCompress() of Qt does: the length, then zlib): what gamebot.py does with the ITEM BAG
and the full-storage checks - the clean-up of a full bag (clean_bag() with bag_plan(), bag_keep(), bag_rows(), the question 'Discard <item>?' that is read
and set to the number wanted, the way to the bag and back to the map, the readers of the bag with their ways of looking at a picture), what the bag keeps
(bag_rules.rules()), the red FULL marks in the main menu (check_menu_full()) and closing the game when storage and bag are both full (check_all_full(),
close_game_completely()): the file that the C++ port, SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoBag.cpp, is tested against.

    python3 tools/make_bag_golden.py            writes the file
    python3 tools/make_bag_golden.py --check    says whether the file is what the code does now (the stories stored in it are played again)

The file is a list of stories: a list of calls, each with the EVENTS that it makes, with the time of a fake clock (it starts at 1000.0 and only moves with
the screenshots and the sleeps).  The pictures are drawn on the canvas by the ops of tools/make_throw_golden.py (and one more: ["size", w, h] makes the
picture another size); the reader of the map (on_map) and the pictures of the bag (the inverted one, the darkest channel, the local contrast) are the real
ones.  Some stories are played on a pretend phone ('sim') that has a map, a main menu, a bag with items, the question to discard and a question to exit: it
changes the screen with every touch, so that the walk through the bag is what the code makes of it.  What the code is GIVEN:
    shot          a screenshot (which of the frames of the story)
    shot_error    the screenshot fails
    ocr           the text reader read the lines (with the places of the words) of a picture (its size, the part that is read, the scale and the mean of the
                  picture are there too: they tell which way of looking at the picture it was)
    ocr_text      the text reader read the number in the box of the question (the size and mean of the box, the text, and how many lines it was told to read)
    adb           what the adb command answered (or that it failed)
  what it DOES (the C++ port has to do the same, in this order):
    tap, back, swipe, swipes (several taps one after the other in one command), sleep, log, save (a picture that is kept), run_state (the daily run is told
    that it is over), then at the end of every call: result (what it returned) or raised, and state (what it remembers)."""
import argparse
import copy
import json
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_throw_golden as TG  # noqa: E402
import make_catch_golden as CG  # noqa: E402  (the pictures and the map)
from make_start_golden import START, Clock, Rec, mean  # noqa: E402
import numpy as np  # noqa: E402
import bag_rules as BR  # noqa: E402
import gamebot as G  # noqa: E402
import spin_stop as S  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "tests", "fixtures", "bag_golden.json.qz")
W, H = TG.W, TG.H
PLAIN = CG.PLAIN
jsonable = CG.jsonable

MENU = G.MENU_BTN
YES_Y, NO_Y, TITLE_Y = 1200, 1400, 900


# ---------------------------------------------------------------------- what the code remembers

_defaults = {"ocr_variant": 0, "storage_full": False, "bag_full": False, "spin": True}


def snapshot():
    return {"ocr_variant": G._ocr_variant[0], "storage_full": bool(G.storage_state["full"]), "bag_full": bool(G.bag_state["full"]), "spin": bool(G.SPIN)}


def apply(name, value):
    if name == "ocr_variant":
        G._ocr_variant[0] = value
    elif name == "storage_full":
        G.storage_state["full"] = bool(value)
    elif name == "bag_full":
        G.bag_state["full"] = bool(value)
    elif name == "spin":
        G.SPIN = bool(value)
    else:
        raise KeyError(name)


def restore(init):
    for name, value in dict(_defaults, **init).items():
        apply(name, value)


# ---------------------------------------------------------------------- the pictures and what the readers say of them

SPOTS = [(x, y) for x in (20, 340, 1150, 1450) for y in (20, 320, 620, 920, 1220, 1520, 1820)]        # (clear of the number box and the ball button)


def marker(n):
    """A white square somewhere on the picture: it makes two screens that are not the same look different to screen_changed()."""
    x, y = SPOTS[n % len(SPOTS)]
    return ["rect", x, y, 280, 280, [255, 255, 255]]


def line(text, x, y):
    """A line of the text reader: (TEXT, x of the first word, y, [(word, x, y)]) - the words are 120 px apart."""
    return [text, x, y, [[w, x + 120 * i, y] for i, w in enumerate(text.split())]]


def frame(ops=None, lines=None, **more):
    f = {"pic": ops if ops is not None else [PLAIN]}
    if lines is not None:
        f["lines"] = lines
    f.update(more)
    return f


class Tagged(np.ndarray):
    """A picture that the way of looking at the bag made (the frame it came from and the way of looking): the fake text reader knows what to say."""


class World(CG.World):
    def __init__(self, spec):
        super().__init__(spec)
        self.last_src = 0


class Sim:
    """A phone with Pokémon GO: the map, the main menu, the bag, the question 'Discard <item>?' and the question to exit.  A touch changes the screen the
    way the game does; what is on it is told as pictures (frames that are made when they are first seen) and the lines the text reader would read."""

    def __init__(self, spec, world):
        self.p = spec["sim"]
        self.world = world
        self.screen = self.p.get("start", "map")
        self.items = [list(i) for i in self.p.get("items", [])]
        self.top = 0
        self.dialog = copy.deepcopy(self.p.get("dialog"))                      # [name, n]
        self.taps_on_items = 0
        self.loading = None
        self.keys = {}
        self.discards = 0
        self.came_from = "map"
        self.ny = int(TITLE_Y + 0.458 * (YES_Y - TITLE_Y))

    # ---- what is on the screen
    def rows(self):
        out = [(item[0], self.p.get("first_y", 400) + i * 300 - self.top) for i, item in enumerate(self.items)]
        return [(n, y) for n, y in out if 250 < y < 2000]

    def frame(self):
        if self.screen == "other" and self.loading is not None:               # (the bag is still loading: that many pictures of 'other', then the bag)
            if self.loading <= 0:
                self.screen, self.loading = "bag", None
            else:
                self.loading -= 1
        s, p = self.screen, self.p
        if s == "map":
            key = ("map",)
        elif s == "menu":
            key = ("menu", p.get("storage_full", False), p.get("bag_full", False))
        elif s == "bag":
            key = ("bag", tuple(tuple(i) for i in self.items), self.top)
        elif s == "discard":
            key = ("discard", self.dialog[0], self.dialog[1])
        else:
            key = (s,)
        if key not in self.keys:
            self.keys[key] = len(self.world.frames)
            self.world.frames.append(self.build(key, len(self.keys) - 1))
        return self.keys[key]

    def build(self, key, n):
        s, p = key[0], self.p
        if s == "map":
            return frame(CG.map_screen()["pic"] + [marker(n)], lines=[])
        if s == "menu":
            iy = p.get("items_y", 1500)
            lines = [line("POKEMON", 600, iy), line(p.get("items_label", "ITEMS"), 1100, iy)] + [line(t, x, y) for t, x, y in p.get("menu_extra", [])]
            if key[1]:
                lines.append(line("FULL", 600, 1560))
            if key[2]:
                lines.append(line("FULL", 1100, 1560))
            return frame([PLAIN, marker(n)], lines=lines)
        if s == "bag":
            lines = [line("ITEMS", 884, 300), line("126/350", 1300, 300)]
            for name, y in self.rows():
                lines.append(line(name.upper(), 600, y))
                if not p.get("hide_counts"):
                    lines.append(line("X%d" % dict((i[0], i[1]) for i in self.items)[name], 150, y + 160))
            lines.sort(key=lambda ln: (ln[2], ln[1]))
            f = frame([PLAIN, marker(n)], lines=lines)
            if "variants_ok" in p:
                f["lines_v"] = {str(v): (lines if v in p["variants_ok"] else []) for v in range(4)}
                if 0 not in p["variants_ok"]:
                    f["lines"] = lines            # (the walk to the bag reads the picture as it is)
            return f
        if s == "discard":
            name, number = key[1], key[2]
            shown = p.get("wrong_title", {}).get(name, name)
            lines = [line("DISCARD %s?" % shown.upper(), 884, TITLE_Y), line("YES", 884, YES_Y), line("NO", 884, NO_Y)]
            ops = [PLAIN, ["rect", 700, 960, 360, 100, [255, 255, 255]], marker(n)]
            return frame(ops, lines=lines, number=p.get("number_text", {}).get(str(number), str(number)))
        if s == "exit":
            lines = [line("DO YOU WANT TO EXIT POKEMON GO?", 884, 900), line("CANCEL", 600, 1300), line("EXIT", 1100, 1300)]
            return frame([PLAIN, marker(n)], lines=lines)
        return frame([PLAIN, marker(n)], lines=[line("LOADING", 884, 1000)] + [line(t, 300, 1100 + 60 * i) for i, t in enumerate(p.get("other_text", []))])

    # ---- what a touch does
    def tap(self, x, y):
        s, p = self.screen, self.p

        def near(px, py, r=80):
            return abs(x - px) < r and abs(y - py) < r
        if s == "map":
            if near(*MENU):
                self.screen = "exit" if p.get("menu_is_exit") else "menu"
        elif s == "menu":
            if near(*MENU):
                self.screen = "map"
            elif abs(x - 1100) < 150 and 1400 < y < 1800:
                self.taps_on_items += 1
                if self.taps_on_items >= p.get("opens_at", 1):
                    self.screen = "other" if p.get("loading_shots") else "bag"
                    self.loading = p.get("loading_shots")
        elif s == "bag":
            if near(*MENU):
                self.screen = "bag" if p.get("menu_dead") else "map"
            elif abs(x - 0.80 * W) < 70:
                for name, ry in self.rows():
                    if abs(y - (ry - 0.017 * H)) < 60 and not p.get("trash_dead"):
                        self.dialog = [name, 1]
                        self.screen = "discard"
                        break
        elif s == "discard":
            count = dict((i[0], i[1]) for i in self.items)[self.dialog[0]]
            if near(0.726 * W, self.ny, 90):
                self.dialog[1] = min(self.dialog[1] + 1, count, p.get("stuck_at", 10 ** 9))
            elif near(0.26 * W, self.ny, 90):
                self.dialog[1] = max(self.dialog[1] - 1, 1)
            elif abs(y - YES_Y) < 60:
                name, n = self.dialog
                for item in self.items:
                    if item[0] == name:
                        item[1] -= n
                self.items = [i for i in self.items if i[1] > 0]
                self.discards += 1
                self.screen = "map" if self.discards >= p.get("map_after_discards", 10 ** 9) else "bag"
            elif abs(y - NO_Y) < 60:
                self.screen = "bag"
        elif s == "exit":
            if near(600, 1300):
                self.screen = "map"

    def back(self):
        self.screen = {"map": "exit", "menu": "map", "bag": "menu", "discard": "bag", "exit": "map", "other": self.p.get("other_back_to", "map")}[self.screen]

    def swipe(self, x1, y1, x2, y2):
        if self.screen == "bag":
            end = max(0, 400 + len(self.items) * 300 - 1900)
            self.top = max(0, min(self.top + (y1 - y2), end))


# ---------------------------------------------------------------------- the fake phone

def record(spec):
    """Plays one story on the fake phone; returns the list of events."""
    Clock.t = START
    rec = Rec()
    Clock.rec = rec
    world = World(spec)
    sim = Sim(spec, world) if spec.get("sim") else None
    saved_g = {n: getattr(G, n) for n in ("time", "log", "setting", "wanted", "save_async", "ocr_line", "ocr_lines", "_bag_image", "run_state", "SPIN")}
    saved_s = {n: getattr(S, n) for n in ("time", "log", "tap", "back", "swipe", "swipes", "screenshot", "adb")}
    saved_state = snapshot()
    try:
        restore(spec.get("init", {}))
        G.time = S.time = Clock
        G.log = S.log = lambda text: rec.add("log", text)
        settings = dict(spec.get("settings", {}))
        wanted = dict(spec.get("wanted", {}))
        G.setting = lambda key, default: settings.get(key, default)
        G.wanted = lambda key: bool(wanted.get(key, key not in ("spin_only_when_full", "daily_cycle")))     # (as the pretend phone of the port answers)
        G.save_async = lambda name, img: rec.add("save", name, world.index_of(img))

        class Watched(dict):
            def __setitem__(self, key, value):
                rec.add("run_state", key, value)
                super().__setitem__(key, value)
        G.run_state = Watched(done=False, waiting_logged=False)

        def tap(x, y, ms=120):
            rec.add("tap", x, y)
            if sim:
                sim.tap(x, y)
        S.tap = tap

        def back():
            rec.add("back")
            if sim:
                sim.back()
        S.back = back

        def swipe(x1, y1, x2, y2, ms=300):
            rec.add("swipe", x1, y1, x2, y2, ms)
            if sim:
                sim.swipe(x1, y1, x2, y2)
        S.swipe = swipe

        def swipes(strokes):
            rec.add("swipes", [list(s) for s in strokes])
            if sim:
                for s in strokes:
                    sim.tap(s[0], s[1])
        S.swipes = swipes

        shots = list(spec.get("shots", [0]))

        def take(on_grab=None):
            n = world.shots
            world.shots += 1
            index = sim.frame() if sim else shots[min(n, len(shots) - 1)]
            Clock.t += spec.get("shot_seconds", 0.0)
            if isinstance(index, str):                       # "error: text": the screenshot fails
                text = index.split(": ", 1)[1]
                rec.add("shot_error", "real", text)
                raise RuntimeError(text)
            rec.add("shot", index, "real", False)
            return world.picture(index)
        S.screenshot = take

        adbs = spec.get("adbs", [])
        adb_calls = [0]

        def adb(*args, binary=False):
            one = adbs[min(adb_calls[0], len(adbs) - 1)] if adbs else {}
            adb_calls[0] += 1
            rec.add("adb", list(args), one.get("reply", ""), one.get("error"))
            if one.get("error") is not None:
                raise RuntimeError(one["error"])
            return one.get("reply", "")
        S.adb = adb

        def source(img):
            src = getattr(img, "src", None)
            return world.index_of(img) if src is None else src

        def ocr_lines(img, y0=0, y1=None, scale=1.0):
            src = source(img)
            f = world.frames[src]
            variant = getattr(img, "variant", None)
            lines = f.get("lines", []) if variant is None else f.get("lines_v", {}).get(str(variant), f.get("lines", []))
            lines = [ln for ln in lines if ln[2] >= y0 and (y1 is None or ln[2] < y1)]
            world.last_src = src
            rec.add("ocr", img.shape[0], img.shape[1], y0, y1, scale, mean(img), lines)
            return lines
        G.ocr_lines = ocr_lines

        def ocr_line(img, lines=1):
            text = world.frames[world.last_src].get("number", "")
            rec.add("ocr_text", img.shape[0], img.shape[1], mean(img), text, lines)
            return text
        G.ocr_line = ocr_line

        original = G._bag_image

        def bag_image(img, variant):
            out = original(img, variant).view(Tagged)
            out.src = source(img)
            out.variant = variant
            return out
        G._bag_image = bag_image

        def lines_of(call):
            return [tuple(ln[:3]) + ([tuple(w) for w in ln[3]],) for ln in call["lines"]]

        def plan_of(call):
            return None if call.get("plan") is None else [tuple(p) for p in call["plan"]]

        for call in spec["calls"]:
            if "settings" in call:
                settings.update(call["settings"])
            if "advance" in call:
                Clock.t += call["advance"]
            for name, value in call.get("init", {}).items():
                apply(name, value)
            rec.add("call", call["fn"], call.get("img"), None)
            try:
                fn = call["fn"]
                img = world.picture(call["img"]) if "img" in call else None
                if fn == "plain_name":
                    result = G._plain_name(call["text"])
                elif fn == "rules":
                    result = [list(r) for r in BR.rules(call.get("saved"))]
                elif fn == "bag_plan":
                    result = [list(r) for r in G.bag_plan()]
                elif fn == "bag_keep":
                    result = G.bag_keep(call["name"], plan_of(call))
                elif fn == "bag_rows":
                    result = [list(r) for r in G.bag_rows(lines_of(call), call["h"], plan_of(call))]
                elif fn == "bag_like":
                    result = G.bag_like(lines_of(call))
                elif fn == "incense_tile":
                    result = G.incense_tile(lines_of(call))
                elif fn == "canvas":
                    result = G._canvas(img, call["x"], call["y"])
                elif fn == "discard_dialog":
                    result = G._discard_dialog(img)
                elif fn == "set_discard_number":
                    shot, d = G._set_discard_number(call["target"], *([call["tries"]] if "tries" in call else []))
                    result = {"img": world.index_of(shot), "d": d}
                elif fn == "bag_ocr":
                    result = G.bag_ocr(img, *([call["y0"]] if "y0" in call else []))
                elif fn == "open_bag":
                    got = G._open_bag()
                    result = None if got is None else {"img": world.index_of(got[0]), "lines": got[1]}
                elif fn == "bag_to_map":
                    G._bag_to_map()
                    result = None
                elif fn == "clean_bag":
                    result = G.clean_bag()
                elif fn == "check_menu_full":
                    G.check_menu_full()
                    result = None
                elif fn == "check_all_full":
                    G.check_all_full()
                    result = None
                elif fn == "close_game_completely":
                    G.close_game_completely()
                    result = None
                elif fn == "leave_question":
                    G._leave_question(call["kind"], lines_of(call))
                    result = None
                elif fn == "cancel_exit":
                    G._cancel_exit(lines_of(call))
                    result = None
                elif fn == "cancel_discard":
                    G._cancel_discard(lines_of(call))
                    result = None
                else:
                    raise ValueError(call)
                rec.add("result", jsonable(result))
            except Exception as e:  # noqa: BLE001
                rec.add("raised", str(e))
            rec.add("state", snapshot())
        return rec.events
    finally:
        for n, v in saved_g.items():
            setattr(G, n, v)
        for n, v in saved_s.items():
            setattr(S, n, v)
        restore(saved_state)


# ---------------------------------------------------------------------- the stories

def stories():
    out = []

    def add(name, calls, frames=None, **spec):
        spec.update(calls=calls, frames=frames if frames is not None else [])
        out.append({"id": name, "spec": spec})

    def call(fn, **kw):
        return dict({"fn": fn}, **kw)

    def sim(name, calls, **p):
        spec = {k: p.pop(k) for k in ("shot_seconds", "settings", "wanted", "init") if k in p}
        add(name, calls, [], sim=p, **spec)

    # ---- the names: _plain_name()
    for i, text in enumerate(["Poké Ball", "POKÉ BALL", "Great Ball", "Super  Potion", "Razz Berry x3", "ＰＯＴＩＯＮ", "ﬁne", "Ⅳ", "Ünïcödé ñ", "", "123", "a-b_c",
                              "naïve café", "İstanbul", "ß", "ŉ", "ｶﾀｶﾅ", "K", "  Max   Potion  ", "Potion\tPack\n", "Poke Ball", "Ǆ", "ᴀ", "x1,5", "Å", "O’Brien", "A\x7fB", "A\u0080B", "A\u007eB"]):
        add("plain_name_%02d" % i, [call("plain_name", text=text)])

    # ---- what the bag keeps: bag_rules.rules()
    saved = [
        ("none", None), ("empty", {}), ("number", {"Potion": 5}), ("text_number", {"Potion": "7"}), ("blank", {"Potion": ""}), ("null", {"Potion": None}),
        ("spaces", {"Potion": "  "}), ("not_a_number", {"Potion": "abc"}), ("a_list", {"Potion": [1]}), ("an_object", {"Potion": {"a": 1}}),
        ("huge", {"Potion": 1e9}), ("negative", {"Potion": -5}), ("fraction", {"Potion": 3.9}), ("true", {"Potion": True}), ("false", {"Potion": False}),
        ("underscore", {"Potion": "1_0"}), ("infinity", {"Potion": "inf"}), ("nan", {"Potion": "nan"}), ("a_revive", {"Revive": 5}),
        ("ultra_ball_zero", {"Ultra Ball": 0}), ("unknown_name", {"Nonexistent": 3}), ("a_list_not_an_object", []), ("a_text", "Potion"), ("a_number", 5),
        ("padded", {"Potion": " 12 "}), ("exponent", {"Potion": "1e2"}), ("hex", {"Potion": "0x10"}), ("big_int", {"Potion": 12345678901234567890}),
        ("fullwidth", {"Potion": "１２"}), ("sign", {"Potion": "+4"}), ("minus_text", {"Potion": "-4"}), ("point", {"Potion": ".5"}), ("point_end", {"Potion": "5."}),
        ("lonely_point", {"Potion": "."}), ("double_underscore", {"Potion": "1__0"}), ("underscore_end", {"Potion": "10_"}), ("infinity_word", {"Potion": "-Infinity"}),
        ("limit", {"Potion": 9999}), ("over_limit", {"Potion": 10000}), ("zero_text", {"Potion": "0"}), ("tab_blank", {"Potion": "\t"}),
        ("all", {"Potion": 1, "Super Potion": 2, "Hyper Potion": 3, "Max Potion": 4, "Revive": None, "Max Revive": 6, "Poké Ball": 7, "Great Ball": 8,
                 "Ultra Ball": 9, "Razz Berry": 10, "Nanab Berry": 11, "Pinap Berry": 12, "Golden Razz Berry": 13, "Silver Pinap Berry": 14}),
        ("all_off", {n: None for n in BR.NAMES}), ("exponent_sign", {"Potion": "2E+1"}), ("exponent_bare", {"Potion": "2e"}), ("nan_sign", {"Potion": "-nan"}),
        ("inf_short", {"Potion": "+inf"}), ("inf_upper", {"Potion": "INF"}), ("name_case", {"potion": 4}),
    ]
    for name, value in saved:
        add("rules_%s" % name, [call("rules", saved=value)])
    add("rules_without_saved", [call("rules")])

    # ---- the plan of the clean-up that the person set (the setting 'bag_keep')
    for name, value in (("none", None), ("numbers", {"Potion": 5, "Poké Ball": 123}), ("all_off", {n: None for n in BR.NAMES}), ("odd", {"Potion": "x"}),
                        ("broken", "text")):
        add("plan_%s" % name, [call("bag_plan")], settings={"bag_keep": value} if value is not None else {})
    add("plan_without_setting", [call("bag_plan")])

    # ---- which items are touched: bag_keep()
    names = ["Potion", "POTION", "Poké Ball", "POKE BALL", "Great Ball", "GREAT  BALL", "Ultra Ball", "Max Potion", "Max Potions", "Hyper Potion", "Hyper Potlon",
             "Pinap Berry", "Razz Berry", "Golden Razz Berry", "Silver Pinap Berry", "Razz", "Potion Pack", "A B C D E", "A B C D", "  ", "123", "", "Revive",
             "Max Revive", "Nanab Berry", "Nanab Berries", "Poke Bal", "Super Potion", "Super Potlon", "Superpotion", "POTIOM", "Pot1on", "Great Bell", "Greate Ball",
             "Ultra  Ball", "Razzberry", "GOLDEN RAZZ BERRY", "Golden Razz Berrie", "Silver Pinap Berrie", "Pokémon", "ＰＯＴＩＯＮ"]
    for i, n in enumerate(names):
        add("keep_%02d" % i, [call("bag_keep", name=n)])
    custom = [["RAZZ*", 5], ["POTION", 0], ["MAX POTION", None]]
    for i, n in enumerate(["Razz Berry", "Golden Razz Berry", "Razzmatazz", "Potion", "Max Potion", "Max Potion X", "Razz Razz", "Berry"]):
        add("keep_custom_%02d" % i, [call("bag_keep", name=n, plan=custom)])
    add("keep_star_alone", [call("bag_keep", name="Razz", plan=[["*", 3]])])
    add("keep_empty_plan", [call("bag_keep", name="Potion", plan=[])])
    add("keep_first_rule_wins", [call("bag_keep", name="Razz Berry", plan=[["RAZZ BERRY", 1], ["RAZZ*", 2]])])
    add("keep_star_then_exact", [call("bag_keep", name="Razz Berry", plan=[["RAZZ*", 2], ["RAZZ BERRY", 1]])])
    add("keep_rule_with_other_word_count", [call("bag_keep", name="Potion Potion", plan=[["POTION", 0]])])
    add("keep_short_rule_not_fuzzy", [call("bag_keep", name="Potiom", plan=[["POTION", 0]])])
    add("keep_six_letters_fuzzy", [call("bag_keep", name="Potiom", plan=[["POTIOM", 0]]), call("bag_keep", name="Potion", plan=[["POTION", 0]])])
    add("keep_five_letters_exact_only", [call("bag_keep", name="Potio", plan=[["POTIO", 0]]), call("bag_keep", name="Poti", plan=[["POTIO", 0]])])
    add("keep_ratio_just_below", [call("bag_keep", name="Ultra Bell", plan=[["ULTRA BALL", 1]]), call("bag_keep", name="Ultra Bxll", plan=[["ULTRA BALL", 1]])])
    razz = [["RAZZ*", 5]]
    add("keep_star_four_words", [call("bag_keep", name="Big Golden Razz Berry", plan=razz)])
    add("keep_star_five_words", [call("bag_keep", name="Big Very Golden Razz Berry", plan=razz)])
    add("keep_star_six_words", [call("bag_keep", name="Big Very Golden Razz Berry Pack", plan=razz)])
    add("keep_a_name_one_letter_short_of_a_rule", [call("bag_keep", name="Potion", plan=[["POTIONS", 1]])])
    add("keep_a_name_that_is_five_letters_of_a_rule", [call("bag_keep", name="Potio", plan=[["POTION", 0]])])
    add("keep_with_the_setting", [call("bag_keep", name="Potion"), call("bag_keep", name="Great Ball")], settings={"bag_keep": {"Potion": 3, "Great Ball": None}})

    # ---- the rows of a page of the bag: bag_rows()
    def row(name, x, y):
        return line(name, x, y)

    def counted(name, count, x=600, y=500, cx=150, cy=None):
        return [row(name, x, y), row(count, cx, y + 160 if cy is None else cy)]
    for i, count in enumerate(["X487", "x12", "K5", "k7", "×30", "30", "12345", "X", "x 5", "1234", "x0", "0", "X05", "XX5", "１２", "٣", "²", "x۴", "Xx5", " 9 ",
                               "x1,5", "5x"]):
        add("rows_count_%02d" % i, [call("bag_rows", lines=counted("Potion", count), h=2208)])
    add("rows_count_far_below", [call("bag_rows", lines=counted("Potion", "X5", cy=500 + 400), h=2208)])
    add("rows_count_just_below_the_range", [call("bag_rows", lines=counted("Potion", "X5", cy=500 + 88), h=2208),
                                            call("bag_rows", lines=counted("Potion", "X5", cy=500 + 89), h=2208)])
    add("rows_count_at_the_end_of_the_range", [call("bag_rows", lines=counted("Potion", "X5", cy=500 + 353), h=2208),
                                               call("bag_rows", lines=counted("Potion", "X5", cy=500 + 354), h=2208)])
    for cy_off in (99, 100, 101, 399, 400, 401):
        add("rows_count_%d_under_the_name_in_a_picture_2500_high" % cy_off, [call("bag_rows", lines=counted("Potion", "X5", cy=500 + cy_off), h=2500)])
    add("rows_count_above", [call("bag_rows", lines=counted("Potion", "X5", cy=500 - 100), h=2208)])
    add("rows_count_right_of_the_name", [call("bag_rows", lines=counted("Potion", "X5", cx=700), h=2208)])
    add("rows_count_at_the_same_x", [call("bag_rows", lines=counted("Potion", "X5", cx=600), h=2208)])
    add("rows_half_the_height", [call("bag_rows", lines=counted("Potion", "X5", y=250, cy=250 + 80), h=1104)])
    add("rows_two_counts_the_first_is_taken", [call("bag_rows", lines=counted("Potion", "X5") + [row("X9", 160, 700)], h=2208)])
    add("rows_two_items", [call("bag_rows", lines=counted("Potion", "X5", y=400) + counted("Poké Ball", "X450", y=700) + counted("Ultra Ball", "X7", y=1000), h=2208)])
    add("rows_no_rules", [call("bag_rows", lines=counted("Lucky Egg", "X5"), h=2208)])
    add("rows_custom_plan", [call("bag_rows", lines=counted("Razz Berry", "X5") + counted("Potion", "X9", y=900), h=2208, plan=[["RAZZ*", 5]])])
    add("rows_with_the_setting", [call("bag_rows", lines=counted("Potion", "X5"), h=2208)], settings={"bag_keep": {"Potion": 1}})
    add("rows_empty", [call("bag_rows", lines=[], h=2208)])
    add("rows_a_word_with_spaces_around_it", [call("bag_rows", lines=[row("Potion", 600, 500), ["X5", 150, 660, [[" x5\t", 150, 660]]]], h=2208)])

    # ---- the daily incense in the bag: incense_tile()
    def lines_with(*words):
        return [line(w, x, y) for w, x, y in words]
    add("incense_tile_both", [call("incense_tile", lines=lines_with(("DAILY", 500, 800), ("ADVENTURE", 800, 830)))])
    add("incense_tile_odd_sum", [call("incense_tile", lines=lines_with(("DAILY", 501, 801), ("ADVENTURE", 800, 830)))])
    add("incense_tile_misread", [call("incense_tile", lines=lines_with(("DAILI", 500, 800), ("ADVENTUR", 800, 830)))])
    add("incense_tile_two_lines", [call("incense_tile", lines=lines_with(("DAILY", 500, 800), ("ADVENTURE", 520, 920)))])
    add("incense_tile_far_apart_x", [call("incense_tile", lines=lines_with(("DAILY", 100, 800), ("ADVENTURE", 600, 800)))])
    add("incense_tile_x_just_near", [call("incense_tile", lines=lines_with(("DAILY", 100, 800), ("ADVENTURE", 549, 800)))])
    add("incense_tile_x_just_far", [call("incense_tile", lines=lines_with(("DAILY", 100, 800), ("ADVENTURE", 550, 800)))])
    add("incense_tile_far_apart_y", [call("incense_tile", lines=lines_with(("DAILY", 500, 800), ("ADVENTURE", 500, 930)))])
    add("incense_tile_y_just_near", [call("incense_tile", lines=lines_with(("DAILY", 500, 800), ("ADVENTURE", 500, 929)))])
    add("incense_tile_adventure_above_daily", [call("incense_tile", lines=lines_with(("DAILY", 500, 800), ("ADVENTURE", 400, 750)))])
    add("incense_tile_only_daily", [call("incense_tile", lines=lines_with(("DAILY", 500, 800)))])
    add("incense_tile_only_adventure", [call("incense_tile", lines=lines_with(("ADVENTURE", 500, 800)))])
    add("incense_tile_only_incense", [call("incense_tile", lines=lines_with(("INCENSE", 500, 800), ("LUCKY", 800, 800)))])
    add("incense_tile_two_daily", [call("incense_tile", lines=lines_with(("DAILY", 100, 300), ("DAILY", 500, 800), ("ADVENTURE", 800, 830)))])
    add("incense_tile_none", [call("incense_tile", lines=[])])
    add("incense_tile_negative_odd_sums", [call("incense_tile", lines=lines_with(("DAILY", -201, -801), ("ADVENTURE", 200, -830)))])
    add("incense_tile_negative_even_sums", [call("incense_tile", lines=lines_with(("DAILY", -200, -800), ("ADVENTURE", -400, -830)))])
    add("incense_tile_in_one_line", [call("incense_tile", lines=[["DAILY ADVENTURE INCENSE", 500, 800, [["DAILY", 500, 800], ["ADVENTURE", 620, 800], ["INCENSE", 740, 800]]]])])

    # ---- is it the bag: bag_like()
    for i, words in enumerate([["BALL"], ["GREAT", "BALL"], ["BERRY"], ["BERRIES"], ["LUCKY", "EGG"], ["EGGS"], ["INCENSE"], ["HELLO", "WORLD"], [], ["ITEMS"], ["ADVENTURE"],
                               ["RAZZ"], ["PINAP"], ["NANAB"], ["LURE"], ["POTION"], ["REVIVE"], ["BAL"]]):
        add("bag_like_%02d" % i, [call("bag_like", lines=[line(" ".join(words), 600, 500)] if words else [])])
    add("bag_like_second_line", [call("bag_like", lines=[line("HELLO", 100, 100), line("POTION", 100, 300)])])

    # ---- the ways of looking at a page of the bag: bag_ocr()
    scene = [["fill", 200, 80, 40], ["rect", 100, 100, 600, 400, [30, 220, 90]], ["rect", 900, 800, 500, 700, [250, 250, 20]]]
    page = [line("ITEMS", 884, 300), line("POTION", 600, 500), line("X12", 150, 660)]
    junk = [line("HELLO WORLD", 600, 500)]
    daily = [line("DAILY", 500, 800), line("ADVENTURE", 800, 830)]
    nothing = {str(v): [] for v in range(4)}
    colours = scene + [["rect", 100, 1000, 700, 600, [220, 20, 200]], ["rect", 1000, 1500, 600, 500, [20, 200, 230]]]      # (the darkest channel is each of the three somewhere)
    structure = [["vgrad", [10, 10, 10], [240, 240, 240]], ["rect", 100, 100, 900, 500, [90, 90, 90]], ["rect", 900, 1200, 700, 800, [200, 200, 200]],
                 ["rect", 300, 1600, 200, 300, [20, 20, 20]], ["noise", 3, 25]]
    add("bag_ocr_the_third_way_reads_colours", [call("bag_ocr", img=0)], [frame(colours, lines=[], lines_v=dict(nothing, **{"2": page}))])
    add("bag_ocr_the_last_way_reads_a_picture_with_structure", [call("bag_ocr", img=0)], [frame(structure, lines=[], lines_v=dict(nothing, **{"3": page}))])
    add("bag_ocr_the_second_way_reads_colours", [call("bag_ocr", img=0)], [frame(colours, lines=[], lines_v=dict(nothing, **{"1": page}))])
    add("bag_ocr_the_first_way_reads", [call("bag_ocr", img=0)], [frame(scene, lines=page)])
    add("bag_ocr_the_third_way_reads", [call("bag_ocr", img=0)], [frame(scene, lines=[], lines_v=dict(nothing, **{"2": page}))])
    add("bag_ocr_the_last_way_reads", [call("bag_ocr", img=0)], [frame(scene, lines=[], lines_v=dict(nothing, **{"3": page}))])
    add("bag_ocr_the_way_that_worked_first", [call("bag_ocr", img=0)], [frame(scene, lines=[], lines_v=dict(nothing, **{"2": page}))], init={"ocr_variant": 2})
    add("bag_ocr_remembered_way_then_the_others_in_order", [call("bag_ocr", img=0)], [frame(scene, lines=[], lines_v=dict(nothing, **{"0": page}))],
        init={"ocr_variant": 3})
    add("bag_ocr_nothing_reads_the_first_is_given", [call("bag_ocr", img=0)],
        [frame(scene, lines=[], lines_v={"0": junk, "1": [line("WORLD", 600, 500)], "2": [], "3": []})])
    add("bag_ocr_nothing_reads_the_remembered_way_is_first", [call("bag_ocr", img=0)],
        [frame(scene, lines=[], lines_v={"0": junk, "1": [line("WORLD", 600, 500)], "2": [], "3": []})], init={"ocr_variant": 1})
    add("bag_ocr_only_the_incense_is_read", [call("bag_ocr", img=0)], [frame(scene, lines=[], lines_v=dict(nothing, **{"1": daily}))])
    add("bag_ocr_from_row_100", [call("bag_ocr", img=0, y0=100), call("bag_ocr", img=0)],
        [frame(scene, lines=[line("DAILY", 500, 150), line("POTION", 600, 500)])])
    add("bag_ocr_the_way_is_kept_for_the_next_page", [call("bag_ocr", img=0), call("bag_ocr", img=1)],
        [frame(scene, lines=[], lines_v=dict(nothing, **{"2": page})), frame(scene + [["rect", 0, 0, 300, 300, [0, 0, 0]]], lines=[], lines_v=dict(nothing, **{"2": page}))])

    # ---- the question 'Discard <item>?': _discard_dialog() reads the title, YES, NO and the number
    box = ["rect", 700, 960, 360, 100, [255, 255, 255]]

    def dlg(number="12", title="DISCARD POTION?", yes=(884, YES_Y), no=(884, NO_Y), ty=TITLE_Y, ops=None, lines=None, **more):
        rows = lines if lines is not None else [line(title, 884, ty)] + ([line("YES", *yes)] if yes else []) + ([line("NO", *no)] if no else [])
        return frame(ops if ops is not None else [PLAIN, box], lines=rows, number=number, **more)
    for i, number in enumerate(["12", "1O", "O", "", "abc", "x5", "1o", "007", "9 9", "١٢", "1,000", "O0O", "oo7"]):
        add("dialog_number_%02d" % i, [call("discard_dialog", img=0)], [dlg(number)])
    add("dialog_no_title", [call("discard_dialog", img=0)], [dlg(lines=[line("YES", 884, YES_Y), line("NO", 884, NO_Y)])])
    add("dialog_no_yes", [call("discard_dialog", img=0)], [dlg(yes=None)])
    add("dialog_no_no", [call("discard_dialog", img=0)], [dlg(no=None)])
    add("dialog_yes_above_the_title", [call("discard_dialog", img=0)], [dlg(yes=(884, 800))])
    add("dialog_yes_level_with_the_title", [call("discard_dialog", img=0)], [dlg(yes=(884, TITLE_Y))])
    add("dialog_no_above_the_title", [call("discard_dialog", img=0)], [dlg(no=(884, 800))])
    add("dialog_lower_case_words", [call("discard_dialog", img=0)], [dlg(lines=[line("Discard Potion?", 884, TITLE_Y), line("Yes", 884, YES_Y), line("No", 884, NO_Y)])])
    add("dialog_two_titles_the_first_is_read", [call("discard_dialog", img=0)],
        [dlg(lines=[line("DISCARD POTION?", 884, TITLE_Y), line("DISCARD REVIVE?", 884, 1000), line("YES", 884, YES_Y), line("NO", 884, NO_Y)])])
    add("dialog_two_yes_the_first_below_the_title", [call("discard_dialog", img=0)],
        [dlg(lines=[line("YES", 884, 700), line("DISCARD POTION?", 884, TITLE_Y), line("YES", 884, YES_Y), line("YES", 884, 1250), line("NO", 884, NO_Y)])])
    add("dialog_title_above_row_100_is_not_seen", [call("discard_dialog", img=0)], [dlg(ty=20, yes=(884, 60), no=(884, 100))])
    add("dialog_number_box_at_the_bottom", [call("discard_dialog", img=0)], [dlg(ty=2100, yes=(884, 2149), no=(884, 2149))])
    add("dialog_the_picture_has_one_colour", [call("discard_dialog", img=0)], [dlg(ops=[PLAIN])])
    add("dialog_half_size_picture", [call("discard_dialog", img=0)],
        [dlg("7", ty=450, yes=(442, 600), no=(442, 700), ops=[PLAIN, ["rect", 350, 480, 180, 50, [255, 255, 255]], ["size", 884, 1104]])])
    add("dialog_title_in_the_middle_of_a_line", [call("discard_dialog", img=0)],
        [dlg(lines=[line("DO YOU WANT TO DISCARD POTION?", 884, TITLE_Y), line("YES", 884, YES_Y), line("NO", 884, NO_Y)])])
    add("dialog_a_word_yes_inside_another_word_is_no_yes", [call("discard_dialog", img=0)],
        [dlg(lines=[line("DISCARD POTION?", 884, TITLE_Y), line("YESTERDAY", 884, YES_Y), line("NO", 884, NO_Y)])])

    # ---- from the picture to the canvas
    add("canvas_the_same_size", [call("canvas", img=0, x=100.7, y=200.2), call("canvas", img=0, x=1414.4, y=1021.5)], [frame()])
    add("canvas_half_size", [call("canvas", img=0, x=100.7, y=200.2), call("canvas", img=0, x=442.0, y=552.0)], [frame([PLAIN, ["size", 884, 1104]])])
    add("canvas_a_wide_picture", [call("canvas", img=0, x=100.0, y=200.0), call("canvas", img=0, x=1.9, y=1.9)], [frame([PLAIN, ["size", 2000, 1000]])])
    add("canvas_a_negative_place", [call("canvas", img=0, x=-1.5, y=-0.5)], [frame()])

    # ---- the numbers of the question: _set_discard_number()
    items = [["Potion", 12], ["Poké Ball", 450]]
    sim("number_already_right", [call("set_discard_number", target=1)], items=items, start="discard", dialog=["Potion", 1])
    sim("number_up", [call("set_discard_number", target=5)], items=items, start="discard", dialog=["Potion", 1])
    sim("number_down", [call("set_discard_number", target=2)], items=items, start="discard", dialog=["Potion", 9])
    sim("number_up_by_more_than_40", [call("set_discard_number", target=100)], items=items, start="discard", dialog=["Poké Ball", 1])
    sim("number_down_by_more_than_40", [call("set_discard_number", target=3)], items=items, start="discard", dialog=["Poké Ball", 300])
    sim("number_not_a_question", [call("set_discard_number", target=5)], items=items, start="bag")
    sim("number_unreadable", [call("set_discard_number", target=5)], items=items, start="discard", dialog=["Potion", 3], number_text={"3": "??"})
    sim("number_stuck", [call("set_discard_number", target=8)], items=items, start="discard", dialog=["Potion", 1], stuck_at=4)
    sim("number_stuck_two_tries", [call("set_discard_number", target=8, tries=2)], items=items, start="discard", dialog=["Potion", 1], stuck_at=4)
    sim("number_no_tries", [call("set_discard_number", target=8, tries=0)], items=items, start="discard", dialog=["Potion", 1])
    sim("number_slow_screenshots", [call("set_discard_number", target=6)], items=items, start="discard", dialog=["Potion", 1], shot_seconds=1.25)

    # ---- the way to the bag: _open_bag()
    bag = [["Potion", 12], ["Poké Ball", 450], ["Lucky Egg", 3]]
    sim("open_bag_from_the_map", [call("open_bag")], items=bag)
    sim("open_bag_second_spot", [call("open_bag")], items=bag, opens_at=2)
    sim("open_bag_third_spot", [call("open_bag")], items=bag, opens_at=3)
    sim("open_bag_no_spot_opens_it", [call("open_bag")], items=bag, opens_at=99)
    sim("open_bag_menu_is_open_already", [call("open_bag")], items=bag, start="menu")
    sim("open_bag_bag_is_open_already", [call("open_bag")], items=bag, start="bag")
    sim("open_bag_a_question_to_exit", [call("open_bag")], items=bag, start="exit")
    sim("open_bag_a_question_to_discard", [call("open_bag")], items=bag, start="discard", dialog=["Potion", 1])
    sim("open_bag_something_in_the_way", [call("open_bag")], items=bag, start="other", other_back_to="other")
    sim("open_bag_something_in_the_way_that_goes", [call("open_bag")], items=bag, start="other", other_back_to="map")
    sim("open_bag_loading_after_the_tap", [call("open_bag")], items=bag, loading_shots=2)
    sim("open_bag_loading_for_long", [call("open_bag")], items=bag, loading_shots=8)
    sim("open_bag_the_menu_asks_to_exit", [call("open_bag")], items=bag, menu_is_exit=True)
    sim("open_bag_slow_screenshots", [call("open_bag")], items=bag, shot_seconds=1.6)
    sim("open_bag_fast_screenshots", [call("open_bag")], items=bag, shot_seconds=0.2)
    sim("open_bag_a_long_screen_is_cut_in_the_log", [call("open_bag")], items=bag, start="other", other_back_to="other",
        other_text=["WORD%02d WORD%02d WORD%02d" % (3 * i, 3 * i + 1, 3 * i + 2) for i in range(8)])
    sim("open_bag_a_screen_of_exactly_the_length", [call("open_bag")], items=bag, start="other", other_back_to="other",
        other_text=["ABCDEFGHIJKLM ABCDEFGHIJKLM ABCDEFGHIJKLM ABCDEFGHIJKLM", "ABCDEFGHI", "ABCDEFGHIJ"])
    sim("open_bag_the_items_label_is_a_little_misread", [call("open_bag")], items=bag, items_label="ITEXS")
    sim("open_bag_the_items_label_just_low_enough", [call("open_bag")], items=bag, items_y=1251)
    sim("open_bag_a_word_right_of_the_items_label", [call("open_bag")], items=bag, menu_extra=[("FULL", 1500, 1560)])
    sim("open_bag_menu_full_marks_do_not_matter", [call("open_bag")], items=bag, storage_full=True, bag_full=True)

    # ---- back to the map: _bag_to_map()
    for start in ("map", "menu", "bag", "exit", "other"):
        sim("bag_to_map_from_%s" % start, [call("bag_to_map")], items=bag, start=start, other_back_to="map")
    sim("bag_to_map_from_a_question_to_discard", [call("bag_to_map")], items=bag, start="discard", dialog=["Potion", 1])
    sim("bag_to_map_from_something_that_stays", [call("bag_to_map")], items=bag, start="other", other_back_to="other")
    sim("bag_to_map_the_menu_button_does_nothing", [call("bag_to_map")], items=bag, start="bag", menu_dead=True)

    # ---- the clean-up: clean_bag()
    stock = [["Potion", 12], ["Super Potion", 3], ["Poké Ball", 450], ["Great Ball", 80], ["Max Potion", 30], ["Razz Berry", 100], ["Lucky Egg", 2], ["Ultra Ball", 500]]
    sim("clean_basic", [call("clean_bag")], items=stock)
    sim("clean_nothing_to_do", [call("clean_bag")], items=[["Potion", 0], ["Poké Ball", 400], ["Great Ball", 100], ["Lucky Egg", 2]][1:])
    sim("clean_unreadable_counts", [call("clean_bag")], items=stock, hide_counts=True)
    sim("clean_wrong_item_in_the_question", [call("clean_bag")], items=stock, wrong_title={"Potion": "Revive"})
    sim("clean_wrong_number_in_the_question", [call("clean_bag")], items=stock[:2], stuck_at=5)
    sim("clean_the_question_does_not_come", [call("clean_bag")], items=stock[:3], trash_dead=True)
    sim("clean_the_bag_does_not_open", [call("clean_bag")], items=stock, opens_at=99)
    sim("clean_the_bag_closes", [call("clean_bag")], items=stock, map_after_discards=1)
    sim("clean_the_bag_closes_after_two", [call("clean_bag")], items=stock, map_after_discards=2)
    sim("clean_with_the_setting", [call("clean_bag")], items=stock, settings={"bag_keep": {"Potion": 5, "Poké Ball": 449, "Super Potion": None, "Great Ball": 50}})
    sim("clean_with_everything_off", [call("clean_bag")], items=stock, settings={"bag_keep": {n: None for n in BR.NAMES}})
    sim("clean_variants_read_late", [call("clean_bag")], items=stock, variants_ok=[2])
    sim("clean_variants_read_the_second_time_in_the_list", [call("clean_bag")], items=stock, variants_ok=[3], init={"ocr_variant": 1})
    sim("clean_slow_screenshots", [call("clean_bag")], items=stock, shot_seconds=1.2)
    sim("clean_an_empty_bag", [call("clean_bag")], items=[])
    sim("clean_everything_goes", [call("clean_bag")], items=[["Potion", 3]])
    sim("clean_only_junk", [call("clean_bag")], items=[["Lucky Egg", 3], ["Lure Module", 2], ["Incubator", 1]])
    long_list = [["Lure Module %d" % i, 2] for i in range(40)] + [["Potion", 10], ["Poké Ball", 500]]
    sim("clean_a_long_list", [call("clean_bag")], items=long_list)
    sim("clean_a_list_that_is_too_long", [call("clean_bag")], items=[["Lure Module %d" % i, 2] for i in range(140)] + [["Potion", 10]])
    sim("clean_the_number_of_actions_is_limited", [call("clean_bag")], items=[["Razz Berry%s" % chr(65 + i), 5] for i in range(14)],
        settings={"bag_keep": {n: None for n in BR.NAMES if n != "Razz Berry"} | {"Razz Berry": 0}})
    sim("clean_a_name_that_is_read_twice_is_done_once", [call("clean_bag")], items=[["Potion", 5], ["Potion", 7]])
    sim("clean_the_question_names_another_spelling", [call("clean_bag")], items=[["Poké Ball", 450]], wrong_title={"Poké Ball": "Poke Ball"})
    sim("clean_keep_is_zero_and_the_count_is_one", [call("clean_bag")], items=[["Potion", 1]])
    sim("clean_the_count_is_the_keep", [call("clean_bag")], items=[["Max Potion", 30], ["Poké Ball", 400]])
    sim("clean_the_count_is_one_over_the_keep", [call("clean_bag")], items=[["Max Potion", 31], ["Poké Ball", 401]])
    sim("clean_the_number_is_read_with_leading_zeros", [call("clean_bag")], items=[["Potion", 12]], stuck_at=4, number_text={"4": "007"})
    sim("clean_the_number_is_read_as_zeros", [call("clean_bag")], items=[["Potion", 12]], stuck_at=4, number_text={"4": "00"})
    sim("clean_the_number_is_read_as_a_zero", [call("clean_bag")], items=[["Potion", 12]], stuck_at=4, number_text={"4": "O"})
    sim("clean_the_row_at_y_260", [call("clean_bag")], items=[["Potion", 5]], first_y=260)
    sim("clean_the_row_at_y_264", [call("clean_bag")], items=[["Potion", 5]], first_y=264)
    sim("clean_the_row_at_y_265", [call("clean_bag")], items=[["Potion", 5]], first_y=265)
    sim("clean_the_row_at_y_1800", [call("clean_bag")], items=[["Potion", 5]], first_y=1800)
    sim("clean_the_row_at_y_1898", [call("clean_bag")], items=[["Potion", 5]], first_y=1898)
    sim("clean_the_row_at_y_1899", [call("clean_bag")], items=[["Potion", 5]], first_y=1899)
    sim("clean_twice_in_a_row", [call("clean_bag"), call("clean_bag")], items=stock)

    # ---- the red FULL marks of the main menu: check_menu_full()
    def menu(*fulls, items=True, pokemon=True, extra=()):
        lines = ([line("POKEMON", 600, 1500)] if pokemon else []) + ([line("ITEMS", 1100, 1500)] if items else []) + [line(w, x, 1560) for w, x in fulls] + list(extra)
        return frame([PLAIN, marker(0)], lines=lines)
    add("menu_check_storage_full", [call("check_menu_full")], [menu(("FULL", 600))])
    add("menu_check_bag_full", [call("check_menu_full")], [menu(("FULL", 1100))])
    add("menu_check_both_full", [call("check_menu_full")], [menu(("FULL", 600), ("FULL", 1100))])
    add("menu_check_neither_full", [call("check_menu_full")], [menu()])
    add("menu_check_only_items_is_there", [call("check_menu_full")], [menu(("FULL", 1100), pokemon=False)])
    add("menu_check_only_pokemon_is_there", [call("check_menu_full")], [menu(("FULL", 600), items=False)])
    add("menu_check_the_menu_is_not_recognised", [call("check_menu_full")], [menu(items=False, pokemon=False, extra=[line("LOADING", 884, 1500)])])
    add("menu_check_full_at_884_is_the_bag", [call("check_menu_full")], [menu(("FULL", 884))])
    add("menu_check_full_at_883_is_the_storage", [call("check_menu_full")], [menu(("FULL", 883))])
    add("menu_check_a_word_that_contains_full", [call("check_menu_full")], [menu(("FULL!", 600), ("NOTFULLY", 1100))])
    add("menu_check_storage_stays_full", [call("check_menu_full")], [menu()], init={"storage_full": True})
    add("menu_check_bag_is_not_full_any_more", [call("check_menu_full")], [menu()], init={"bag_full": True})
    add("menu_check_both_get_full_and_then_not", [call("check_menu_full"), call("check_menu_full", init={"bag_full": False})], [menu(("FULL", 600), ("FULL", 1100)), menu()],
        shots=[0, 1])
    add("menu_check_words_above_row_1300_are_not_read", [call("check_menu_full")], [menu(extra=[line("FULL", 1100, 1200)])])
    add("menu_check_slow_screenshot", [call("check_menu_full")], [menu(("FULL", 600))], shot_seconds=2.0)

    # ---- the recent apps: close_game_completely()
    def recent(*rows):
        return frame([PLAIN, marker(1)], lines=[line(t, x, y) for t, x, y in rows])
    add("close_closes_all_by_the_words", [call("close_game_completely")], [recent(("CLOSE ALL", 875, 1700))])
    add("close_dutch_word", [call("close_game_completely")], [recent(("SLUITEN", 1000, 1750))])
    add("close_nothing_found_the_usual_place", [call("close_game_completely")], [recent(("RECENT", 300, 1300))])
    add("close_two_words_in_the_line", [call("close_game_completely")], [recent(("ALLES SLUITEN", 801, 1720))])
    add("close_the_words_are_too_high", [call("close_game_completely")], [recent(("CLOSE ALL", 875, 1000))])
    add("close_the_first_line_that_fits_is_taken", [call("close_game_completely")], [recent(("CLOSE ALL", 700, 1500), ("SLUITEN", 1000, 1800))])
    add("close_the_words_are_at_the_edge", [call("close_game_completely")], [recent(("CLOSE ALL", 700, 1100)), recent(("CLOSE ALL", 700, 2207))])
    add("close_the_words_are_at_the_end", [call("close_game_completely")], [recent(("CLOSE ALL", 700, 2208))])
    add("close_first_adb_fails", [call("close_game_completely")], [recent(("CLOSE ALL", 875, 1700))], adbs=[{"error": "device offline"}])
    add("close_the_key_fails", [call("close_game_completely")], [recent(("CLOSE ALL", 875, 1700))], adbs=[{}, {"error": "no input"}, {}, {}])
    add("close_the_last_adb_fails", [call("close_game_completely")], [recent(("CLOSE ALL", 875, 1700))], adbs=[{}, {}, {}, {"error": "gone"}])
    add("close_the_screenshot_fails", [call("close_game_completely")], [recent(("CLOSE ALL", 875, 1700))], shots=["error: the screen is off"])
    add("close_a_line_without_words", [call("close_game_completely")], [frame([PLAIN, marker(1)], lines=[["CLOSE ALL", 875, 1700, []]])])
    add("close_an_error_without_text", [call("close_game_completely")], [recent(("CLOSE ALL", 875, 1700))], adbs=[{"error": ""}])

    # ---- the storage and the bag are both full: check_all_full()
    both = {"storage_full": True, "bag_full": True, "spin": False}
    close_frame = recent(("CLOSE ALL", 875, 1700))
    add("all_full_nothing_is_full", [call("check_all_full")], [close_frame], wanted={"daily_cycle": True, "close_when_full": True}, init={"spin": False})
    add("all_full_only_the_storage", [call("check_all_full")], [close_frame], wanted={"daily_cycle": True, "close_when_full": True}, init={"storage_full": True, "spin": False})
    add("all_full_only_the_bag", [call("check_all_full")], [close_frame], wanted={"daily_cycle": True, "close_when_full": True}, init={"bag_full": True, "spin": False})
    add("all_full_but_nothing_is_wanted", [call("check_all_full")], [close_frame], wanted={"close_when_full": False}, init=both)
    add("all_full_in_a_daily_run", [call("check_all_full")], [close_frame], wanted={"daily_cycle": True}, init=both)
    add("all_full_in_a_daily_run_and_close_when_full", [call("check_all_full")], [close_frame], wanted={"daily_cycle": True, "close_when_full": True}, init=both)
    waiting = [{}, {}, {}, {}]
    add("all_full_waits_for_the_game", [call("check_all_full")], [close_frame], wanted={"close_when_full": True}, init=both,
        adbs=waiting + [{"error": "adb-fout"}, {"error": "adb-fout"}, {"reply": "4242\n"}])
    add("all_full_waits_for_a_blank_answer", [call("check_all_full")], [close_frame], wanted={"close_when_full": True}, init=both,
        adbs=waiting + [{"reply": "  \n"}, {"reply": ""}, {"reply": "7\n"}])
    add("all_full_the_game_runs_at_once", [call("check_all_full")], [close_frame], wanted={"close_when_full": True}, init=both, adbs=waiting + [{"reply": "1\n"}])
    add("all_full_closing_fails_and_the_wait_goes_on", [call("check_all_full")], [close_frame], wanted={"close_when_full": True}, init=both,
        adbs=[{"error": "device offline"}, {"reply": "99\n"}])
    add("all_full_in_a_daily_run_the_closing_fails", [call("check_all_full")], [close_frame], wanted={"daily_cycle": True}, init=both, adbs=[{"error": "device offline"}])

    # ---- the questions that are answered with the safe button: _cancel_exit(), _cancel_discard(), _leave_question()
    add("cancel_exit_by_the_word", [call("cancel_exit", lines=[line("DO YOU WANT TO EXIT?", 884, 900), line("CANCEL", 600, 1300), line("EXIT", 1100, 1300)])])
    add("cancel_exit_a_misread_word", [call("cancel_exit", lines=[line("CANCELL", 650, 1310)])])
    add("cancel_exit_no_word", [call("cancel_exit", lines=[line("EXIT", 1100, 1300)])])
    add("cancel_exit_two_words_the_first", [call("cancel_exit", lines=[line("CANCEL", 600, 1300), line("CANCEL", 700, 1400)])])
    add("cancel_exit_a_word_that_is_not_like_enough", [call("cancel_exit", lines=[line("CANXL", 600, 1300)])])
    add("cancel_exit_the_word_is_a_little_like", [call("cancel_exit", lines=[line("CANCER", 600, 1300)]), call("cancel_exit", lines=[line("CAN", 600, 1300)])])
    add("cancel_discard_by_the_word", [call("cancel_discard", lines=[line("DISCARD POTION?", 884, 900), line("YES", 884, 1200), line("NO", 884, 1400)])])
    add("cancel_discard_no_too_high", [call("cancel_discard", lines=[line("NO", 884, 1000)])])
    add("cancel_discard_no_just_low_enough", [call("cancel_discard", lines=[line("NO", 884, 1001)])])
    add("cancel_discard_lower_case_no", [call("cancel_discard", lines=[line("no", 884, 1400)])])
    add("cancel_discard_no_word", [call("cancel_discard", lines=[line("YES", 884, 1200)])])
    add("cancel_discard_the_word_is_in_a_line", [call("cancel_discard", lines=[line("NO THANKS", 884, 1400)])])
    add("leave_question_exit", [call("leave_question", kind="exit", lines=[line("CANCEL", 600, 1300)])])
    add("leave_question_discard", [call("leave_question", kind="discard", lines=[line("NO", 884, 1400)])])
    add("leave_question_anything_else", [call("leave_question", kind="bag", lines=[line("NO", 884, 1400)]), call("leave_question", kind="map", lines=[])])
    return out


def all_stories():
    return stories()


def capture():
    return {"start": START, "cases": [dict(c, events=record(c["spec"])) for c in all_stories()]}


def text(doc=None):
    return json.dumps(doc if doc is not None else capture(), sort_keys=True, separators=(",", ":"), allow_nan=False)


def pack(data):
    raw = data.encode()
    return struct.pack(">I", len(raw)) + zlib.compress(raw, 9)


def unpack(blob):
    return zlib.decompress(blob[4:]).decode()


def check():
    stored = json.loads(unpack(open(OUT, "rb").read()))
    now = json.loads(text())
    if now != stored:
        bad = [c["id"] for c, o in zip(now["cases"], stored["cases"]) if c != o]
        print("the file is not what the code does now: %s" % ", ".join(bad[:10]))
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        sys.exit(check())
    data = text()
    with open(OUT, "wb") as f:
        f.write(pack(data))
    doc = json.loads(data)
    print("wrote %s: %d stories, %d events" % (OUT, len(doc["cases"]), sum(len(c["events"]) for c in doc["cases"])))


if __name__ == "__main__":
    main()
