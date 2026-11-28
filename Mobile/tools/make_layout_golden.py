#!/usr/bin/env python3
"""Makes tests/fixtures/layout_golden.json.qz (JSON, packed the way qCompress() of Qt does: the length, then zlib): what spin_stop.py and gamebot.py do to
find out whether the game is DRAWN THE WAY THE BOT EXPECTS, and to put that right - _judge_screen() (is the shape of the screen close enough to the canvas),
_normalize() (the size of a screenshot is noticed), find_menu_button() and menu_button_check() (the Poké Ball button of the map, where it is, how wide),
display_plan(), adapt_display() and restore_display() (let Android draw the game on a canvas of the right shape: `wm size`, and put it back),
wait_unsupported(), and layout_init(), layout_adapt(), layout_undo(), layout_tap_test(), layout_verify() and layout_watch() of the bot - the file that the
C++ port, SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoLayout.cpp, is tested against.

    python3 tools/make_layout_golden.py            writes the file
    python3 tools/make_layout_golden.py --check    says whether the file is what the code does now (the stories stored in it are played again)

The file is a list of stories: a list of calls, each with the EVENTS that it makes, with the time of a fake clock (it starts at 1000.0 and only moves with
the sleeps and the screenshots).  The pictures are drawn on the canvas by the ops of tools/make_throw_golden.py.  What the code is GIVEN (the spec):
    screen        the size of the screen that the bot knows (w, h, model) before the first call
    allow, no_adapt   do the files ~/gamebot_allow_unsupported and ~/gamebot_no_display_change exist
    wm            what `wm size` says (a text, or {"raise": text}), one answer for every question (the last again when there are fewer)
    wm_set, wm_reset  what `wm size WxH` and `wm size reset` do (null, or {"raise": text})
    record        the file of what the bot changed (~/gamebot_wm_override.json): its text, or an object (the file as json), or null (no file)
    record_write_error   the text of the error when the file cannot be written
    detects       what the check of the screen finds after a change: {w, h, model}, {"none": true} (no display can be captured) or {"raise": text}
    frames, shots   the pictures (with the lines that the text reader finds in them) and which of them the screenshots give
    layout        what the bot remembers of the layout before the first call
  what it DOES (the C++ port has to do the same, in this order):
    wm_info (what `wm size` said), wm_set, wm_reset, record_read, record_write, record_forget, detect_screen, same_screen (the screen that is told apart
    again), tap, back, shot, ocr, sleep, log, then at the end of every call: result (what it returned) or raised, and state (what the bot remembers)."""
import argparse
import builtins
import json
import os
import struct
import sys
import types
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_throw_golden as TG  # noqa: E402  (the ops of the pictures)
import make_catch_golden as CG  # noqa: E402  (the frames and their lines)
from make_start_golden import START, Clock, Rec, mean  # noqa: E402
import gamebot as G  # noqa: E402
import spin_stop as S  # noqa: E402
import numpy as np  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "tests", "fixtures", "layout_golden.json.qz")
W, H = S.EXPECTED_SIZE                                          # the canvas
PLAIN = CG.PLAIN
HOME = "/home/pi"                                               # (where the files of the bot are on the Pi: the same in every build of the file)
ALLOW_FILE = HOME + "/gamebot_allow_unsupported"
NO_ADAPT_FILE = HOME + "/gamebot_no_display_change"
WM_FILE = HOME + "/gamebot_wm_override.json"

RED = [30, 30, 220]                                             # [b, g, r]
WHITE = [255, 255, 255]


def button_ops(cx=884, bot=1991, w=170, h=None, red=None, white=None, below=None, base=None):
    """The picture of the map: a red half and a white half of the Poké Ball button (the red one's middle at cx, its lower edge at bot)."""
    h = int(w * 0.5) if h is None else h
    x = cx - w // 2
    return [base or PLAIN, ["rect", x, bot - h, w, h, red or RED], ["rect", x, bot, w, below if below is not None else 100, white or WHITE]]


def frame(ops=None, lines=None, text=None):
    f = {"pic": ops if ops is not None else [PLAIN]}
    if lines is not None:
        f["lines"] = lines
    return f


def line(text, x, y, words=None):
    """What the text reader finds: [the text, x, y, [[word, x, y], ...]] (a word per word of the text when none are given)."""
    if words is None:
        words = [[w, x + 40 * i, y] for i, w in enumerate(text.split())]
    return [text, x, y, words]


def jsonable(value):
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        return round(value, 6)
    if hasattr(value, "item"):
        return jsonable(value.item())
    return value


# ---------------------------------------------------------------------- the stories are played on the fake phone

class Script:
    """What the phone answers: the n-th question gets the n-th answer of the list (the last one again when there are fewer)."""
    def __init__(self, items):
        self.items, self.n = items, 0

    def next(self, default=None):
        one = self.items[min(self.n, len(self.items) - 1)] if self.items else default
        self.n += 1
        return one


def record(spec):
    """Plays one story on the fake phone; returns the list of events."""
    Clock.t = START
    rec = Rec()
    Clock.rec = rec
    world = CG.World(dict(spec, frames=spec.get("frames", [])))
    saved_g = {n: getattr(G, n) for n in ("time", "log", "ocr_lines", "same_screen", "atexit", "signal")}
    missing = object()                                          # (S has no open() of its own: the one of Python is used)
    saved_s = {n: getattr(S, n, missing) for n in ("time", "log", "tap", "back", "screenshot", "adb", "detect_screen", "ALLOW_FILE", "NO_ADAPT_FILE", "WM_FILE", "os",
                                          "open")}
    saved_screen, saved_layout, saved_wait = dict(S.screen), dict(G.layout), dict(S._wait_log)
    store = {"text": None}
    files = {"allow": spec.get("allow"), "no_adapt": spec.get("no_adapt")}       # the switch files of the Pi (a call may create or remove them)
    wm, wm_set, wm_reset, detects = (Script(spec.get(k, [])) for k in ("wm", "wm_set", "wm_reset", "detects"))
    shots = list(spec.get("shots", [0]))
    try:
        G.time = S.time = Clock
        G.log = S.log = lambda text: rec.add("log", text)
        S.ALLOW_FILE, S.NO_ADAPT_FILE, S.WM_FILE = ALLOW_FILE, NO_ADAPT_FILE, WM_FILE
        S.tap = lambda x, y, ms=120: rec.add("tap", x, y)
        S.back = lambda: rec.add("back")
        G.atexit = types.SimpleNamespace(register=lambda f: None)
        G.signal = types.SimpleNamespace(signal=lambda *a: None, SIGTERM=15)
        S._wait_log["t"] = 0.0
        S.screen.update(w=spec.get("screen", {}).get("w", W), h=spec.get("screen", {}).get("h", H), model=spec.get("screen", {}).get("model", ""),
                        ok=True, note="")
        G.layout.update(dict(state="new", looks=0, since=0.0, next_try=0.0), **spec.get("layout", {}))
        init = spec.get("record")
        store["text"] = json.dumps(init) if isinstance(init, (dict, list)) else init

        class Os(types.SimpleNamespace):
            def __getattr__(self, name):
                return getattr(os, name)

        class Path:
            def __getattr__(self, name):
                return getattr(os.path, name)

            @staticmethod
            def exists(path):
                if path == ALLOW_FILE:
                    return bool(files["allow"])
                if path == NO_ADAPT_FILE:
                    return bool(files["no_adapt"])
                if path == WM_FILE:
                    return store["text"] is not None
                return os.path.exists(path)

        def remove(path):
            assert path == WM_FILE, path
            rec.add("record_forget")
            had = store["text"] is not None
            store["text"] = None
            if not had:
                raise FileNotFoundError(path)
        S.os = Os(path=Path(), remove=remove)

        class File:
            def __init__(self, mode):
                self.mode, self.text = mode, ""

            def __enter__(self):
                return self

            def __exit__(self, *a):
                if "w" in self.mode:
                    data = json.loads(self.text)
                    store["text"] = self.text
                    rec.add("record_write", data["set"], data["time"], data["model"], data["was"])
                return False

            def write(self, text):
                self.text += text

            def read(self, *a):
                return store["text"]

            def __iter__(self):
                return iter(store["text"].splitlines(True))

        def fake_open(path, mode="r", *a, **kw):
            if path != WM_FILE:
                return builtins.open(path, mode, *a, **kw)
            if "w" in mode:
                if spec.get("record_write_error"):
                    rec.add("record_write_error", spec["record_write_error"])
                    raise OSError(spec["record_write_error"])
                return File(mode)
            rec.add("record_read", store["text"])
            if store["text"] is None:
                raise FileNotFoundError(path)
            return File(mode)
        S.open = fake_open

        def adb(*args, binary=False):
            if args == ("shell", "wm", "size"):
                one = wm.next("")
                if isinstance(one, dict):
                    rec.add("wm_info_error", one["raise"])
                    raise RuntimeError(one["raise"])
                rec.add("wm_info", one)
                return one
            if args[:3] == ("shell", "wm", "size") and len(args) == 4:
                script, kind = (wm_reset, "wm_reset") if args[3] == "reset" else (wm_set, "wm_set")
                one = script.next(None)
                extra = () if kind == "wm_reset" else (args[3],)
                if one:
                    rec.add(kind + "_error", *extra, one["raise"])
                    raise RuntimeError(one["raise"])
                rec.add(kind, *extra)
                return ""
            raise ValueError(args)
        S.adb = adb

        def detect_screen(wake=True):
            one = detects.next({"none": True})
            if one.get("raise"):
                rec.add("detect_error", wake, one["raise"])
                raise RuntimeError(one["raise"])
            if one.get("none"):
                rec.add("detect_none", wake)
                return False
            rec.add("detect_screen", wake, one["w"], one["h"], one.get("model", S.screen["model"]))
            S.screen.update(w=one["w"], h=one["h"], model=one.get("model", S.screen["model"]))
            S._judge_screen()
            return True
        S.detect_screen = detect_screen

        class SameScreen(dict):
            def update(self, *a, **kw):
                rec.add("same_screen", kw.get("name"), kw.get("count"))
                super().update(*a, **kw)
        G.same_screen = SameScreen(name="x", count=3)

        def take():
            n = world.shots
            world.shots += 1
            index = shots[min(n, len(shots) - 1)]
            Clock.t += spec.get("shot_seconds", 0.0)
            rec.add("shot", index, "real")
            return world.picture(index)
        S.screenshot = take

        def ocr_lines(img, y0=0, y1=None, scale=1.0):
            lines = [ln for ln in world.frame(img).get("lines", []) if ln[2] >= y0]
            rec.add("ocr", img.shape[0], img.shape[1], y0, y1, scale, mean(img), lines)
            return lines
        G.ocr_lines = ocr_lines

        if spec.get("judged", True):
            S._judge_screen()

        def state():
            parsed = None
            if store["text"] is not None:
                try:
                    parsed = json.loads(store["text"])
                except ValueError:
                    parsed = store["text"]
            return jsonable({"layout": {k: G.layout[k] for k in ("state", "looks", "since", "next_try")},
                             "screen": {k: S.screen[k] for k in ("w", "h", "ok", "note", "model")}, "record": parsed, "wait_log": S._wait_log["t"]})

        for call in spec["calls"]:
            fn = call["fn"]
            Clock.t += call.get("advance", 0.0)
            for key in ("allow", "no_adapt"):
                if key in call:
                    files[key] = call[key]
            rec.add("call", fn)
            try:
                if fn == "judge":
                    S.screen.update(w=call["w"], h=call["h"])
                    S._judge_screen()
                    result = [S.screen["ok"], S.screen["note"]]
                elif fn == "seen":
                    S._normalize(np.zeros((call["h"], call["w"], 3), np.uint8))
                    result = [S.screen["ok"], S.screen["note"]]
                elif fn == "find":
                    found = S.find_menu_button(world.picture(call["img"]))
                    result = None if found is None else list(found)
                elif fn == "check":
                    ok, text = S.menu_button_check(None if call["found"] is None else tuple(call["found"]))
                    result = [ok, text]
                elif fn == "plan":
                    cmd, size, why = S.display_plan()
                    result = [cmd, None if size is None else list(size), why]
                elif fn == "adapt":
                    changed, text = S.adapt_display()
                    result = [changed, text]
                elif fn == "restore":
                    result = S.restore_display()
                elif fn == "detect":
                    result = S.detect_screen(call.get("wake", True))
                elif fn == "wait_unsupported":
                    S.wait_unsupported()
                    result = None
                elif fn == "init":
                    G.layout_init()
                    result = None
                elif fn == "layout_adapt":
                    result = G.layout_adapt(call["why"])
                elif fn == "layout_undo":
                    G.layout_undo(call["why"])
                    result = None
                elif fn == "tap_test":
                    result = G.layout_tap_test(world.picture(call["before"]))
                elif fn == "verify":
                    G.layout_verify(world.picture(call["img"]))
                    result = None
                elif fn == "watch":
                    G.layout_watch()
                    result = None
                else:
                    raise ValueError(fn)
                rec.add("result", jsonable(result))
            except RuntimeError as e:
                rec.add("raised", str(e))
            rec.add("state", state())
        return rec.events
    finally:
        for n, v in saved_g.items():
            setattr(G, n, v)
        for n, v in saved_s.items():
            if v is missing:
                delattr(S, n)
            else:
                setattr(S, n, v)
        S.screen.clear()
        S.screen.update(saved_screen)
        G.layout.clear()
        G.layout.update(saved_layout)
        S._wait_log.clear()
        S._wait_log.update(saved_wait)


# ---------------------------------------------------------------------- the stories

PHYS = "Physical size: %dx%d"


def wm_text(phys=None, over=None):
    lines = []
    if phys:
        lines.append(PHYS % phys)
    if over:
        lines.append("Override size: %dx%d" % over)
    return "\n".join(lines) + "\n"


def stories():
    out = []

    def story(name, calls, **spec):
        out.append({"id": name, "spec": dict(spec, calls=calls)})

    # ---- _judge_screen(): is the shape of the screen close enough to the canvas?  (the canvas is 1768 x 2208: 0.8007; 10 % more or less is allowed)
    for w, h in ((1768, 2208), (1592, 2208), (1591, 2208), (1944, 2208), (1945, 2208), (1080, 2400), (1080, 2340), (1440, 3120), (1080, 1920), (2208, 1768),
                 (1812, 2176), (1000, 2200), (1080, 1349), (1080, 1348), (600, 750), (2208, 2208), (1, 1), (2400, 1080), (1768, 1769), (1769, 2208)):
        story("judge_%dx%d" % (w, h), [{"fn": "judge", "w": w, "h": h}])
    story("judge_allowed_anyway", [{"fn": "judge", "w": 1080, "h": 2400}], allow=True)
    story("judge_allowed_but_fits", [{"fn": "judge", "w": 1768, "h": 2208}], allow=True)
    story("judge_twice", [{"fn": "judge", "w": 1080, "h": 2400}, {"fn": "judge", "w": 1768, "h": 2208}, {"fn": "judge", "w": 1080, "h": 1920}])

    # ---- _normalize(): the size of a screenshot is noticed
    story("seen_the_canvas", [{"fn": "seen", "w": 1768, "h": 2208}])
    story("seen_another_size", [{"fn": "seen", "w": 1080, "h": 2400}])
    story("seen_the_same_size_again", [{"fn": "seen", "w": 1080, "h": 2400}, {"fn": "seen", "w": 1080, "h": 2400}], screen={"w": 1080, "h": 2400})
    story("seen_a_foldable_that_folds", [{"fn": "seen", "w": 1768, "h": 2208}, {"fn": "seen", "w": 904, "h": 2316}, {"fn": "seen", "w": 1768, "h": 2208}],
          screen={"w": 1768, "h": 2208})
    story("seen_a_screen_that_fits_after_one_that_does_not", [{"fn": "seen", "w": 1592, "h": 2208}], screen={"w": 1080, "h": 2400})
    story("seen_allowed_anyway", [{"fn": "seen", "w": 1080, "h": 2400}], allow=True)
    story("seen_only_the_width_changes", [{"fn": "seen", "w": 1000, "h": 2400}], screen={"w": 1080, "h": 2400})
    story("seen_only_the_height_changes", [{"fn": "seen", "w": 1080, "h": 2300}], screen={"w": 1080, "h": 2400})
    story("judge_allowed_after_it_was_not", [{"fn": "judge", "w": 1080, "h": 2400}, {"fn": "judge", "w": 1080, "h": 2400, "allow": True},
                                             {"fn": "judge", "w": 1080, "h": 2400, "allow": False}])

    # ---- detect_screen(): look at the screen, take its size, judge it
    story("detect_finds_the_screen", [{"fn": "detect"}], detects=[{"w": 1080, "h": 2400, "model": "Pixel 7"}])
    story("detect_finds_a_screen_that_fits", [{"fn": "detect", "wake": False}], screen={"w": 1080, "h": 2400}, detects=[{"w": 1768, "h": 2208, "model": "Fold3"}])
    story("detect_finds_no_display", [{"fn": "detect"}], screen={"w": 1080, "h": 2400}, detects=[{"none": True}])
    story("detect_cannot_look", [{"fn": "detect"}], screen={"w": 1080, "h": 2400}, detects=[{"raise": "adb offline"}])

    # ---- menu_button_check(): is the button where the canvas expects it ((884, 1991), 170 px wide; 45, 60 and 28 px off are allowed)
    for name, found in (("exact", [884.0, 1991.0, 170.0]), ("none", None), ("half_pixels", [884.5, 1991.5, 169.5]), ("dx_45", [929.0, 1991.0, 170.0]),
                        ("dx_45_5", [929.5, 1991.0, 170.0]), ("dx_minus_45", [839.0, 1991.0, 170.0]), ("dx_minus_45_5", [838.5, 1991.0, 170.0]),
                        ("dy_60", [884.0, 2051.0, 170.0]), ("dy_60_5", [884.0, 2051.5, 170.0]), ("dy_minus_60", [884.0, 1931.0, 170.0]),
                        ("dy_minus_60_5", [884.0, 1930.5, 170.0]), ("dd_28", [884.0, 1991.0, 198.0]), ("dd_28_5", [884.0, 1991.0, 198.5]),
                        ("dd_minus_28", [884.0, 1991.0, 142.0]), ("dd_minus_28_5", [884.0, 1991.0, 141.5]), ("all_edges", [929.0, 2051.0, 198.0]),
                        ("all_edges_minus", [839.0, 1931.0, 142.0]), ("rounds_to_even_down", [884.5, 1992.5, 170.5]), ("rounds_to_even_up", [885.5, 1991.5, 171.5]),
                        ("far_off", [300.0, 1200.0, 60.0]), ("tiny", [0.0, 0.0, 0.0]), ("small_numbers", [884.4, 1991.6, 170.49])):
        story("check_" + name, [{"fn": "check", "found": found}])

    # ---- find_menu_button(): the red half and the white half of the button at the bottom of the map
    def find(name, ops_or_list, **spec):
        ops = ops_or_list
        story("find_" + name, [{"fn": "find", "img": 0}], frames=[frame(ops)], **spec)

    find("reference", button_ops())
    find("odd_width", button_ops(w=171))
    find("odd_width_173", button_ops(w=173, h=86))
    find("shifted_left", button_ops(cx=840))
    find("shifted_right", button_ops(cx=930))
    find("shifted_up", button_ops(bot=1900))
    find("shifted_down", button_ops(bot=2060))
    find("no_button", [PLAIN])
    find("no_white_half", [PLAIN, ["rect", 799, 1906, 170, 85, RED]], base=None)
    find("grey_instead_of_white", button_ops(white=[128, 128, 128]))
    find("white_a_little_coloured", button_ops(white=[255, 240, 250]))
    find("white_too_coloured", button_ops(white=[255, 225, 250]))
    find("white_edge_24", button_ops(white=[200, 224, 200]))
    find("white_edge_25", button_ops(white=[200, 225, 200]))
    find("dimmed_game", button_ops(red=[10, 10, 110], white=[100, 100, 100], base=["fill", 30, 30, 30]))
    find("dimmed_white_too_dark", button_ops(red=[10, 10, 110], white=[80, 80, 80], base=["fill", 30, 30, 30]))
    find("dimmed_white_edge", button_ops(red=[10, 10, 110], white=[88, 88, 88], base=["fill", 30, 30, 30]))
    find("dimmed_white_edge_89", button_ops(red=[10, 10, 110], white=[89, 89, 89], base=["fill", 30, 30, 30]))
    find("red_edge_35", button_ops(red=[10, 10, 35]))
    find("red_edge_36", button_ops(red=[10, 10, 36]))
    find("red_not_red_enough", button_ops(red=[40, 40, 100]))
    find("red_just_red_enough", button_ops(red=[40, 40, 101]))
    find("orange_not_red", button_ops(red=[10, 120, 255]))
    find("width_88", button_ops(w=88, h=44))
    find("width_89", button_ops(w=89, h=44))
    find("width_353", button_ops(w=353, h=176))
    find("width_354", button_ops(w=354, h=177))
    find("height_51_of_170", button_ops(h=51))
    find("height_50_of_170", button_ops(h=50))
    find("height_118_of_170", button_ops(h=118))
    find("height_119_of_170", button_ops(h=119))
    find("height_70_of_100", button_ops(w=100, h=70))
    find("height_71_of_100", button_ops(w=100, h=71))
    find("height_30_of_100", button_ops(w=100, h=30))
    find("height_29_of_100", button_ops(w=100, h=29))
    find("half_a_disc", [PLAIN, ["ellipse", 884, 1991, 85, 85, 0, -1, RED, 180, 360], ["rect", 799, 1991, 170, 100, WHITE]])
    find("a_ring_is_not_a_button", [PLAIN, ["ellipse", 884, 1991, 85, 60, 0, 6, RED, 180, 360], ["rect", 799, 1991, 170, 100, WHITE]])
    find("a_thin_cross_is_not_a_button", [PLAIN, ["rect", 880, 1900, 8, 90, RED], ["rect", 800, 1940, 170, 8, RED], ["rect", 799, 1991, 170, 100, WHITE]])
    find("too_high", button_ops(bot=1700))
    find("just_low_enough", button_ops(bot=1810))
    find("too_far_left", button_ops(cx=380))
    find("too_far_right", button_ops(cx=1400))
    find("at_the_left_edge_of_the_region", button_ops(cx=527))
    find("at_the_right_edge_of_the_region", button_ops(cx=1241))
    find("cut_by_the_left_edge_of_the_region", button_ops(cx=480))
    find("at_the_bottom_with_no_room_for_the_white", button_ops(bot=2180, below=28))
    find("at_the_bottom_with_just_room", button_ops(bot=2150, below=58))
    find("two_buttons_the_middle_one_wins", [PLAIN, ["rect", 600, 1906, 170, 85, RED], ["rect", 600, 1991, 170, 100, WHITE],
                                            ["rect", 799, 1906, 170, 85, RED], ["rect", 799, 1991, 170, 100, WHITE]])
    find("two_buttons_the_middle_one_wins_the_other_way", [PLAIN, ["rect", 799, 1906, 170, 85, RED], ["rect", 799, 1991, 170, 100, WHITE],
                                                           ["rect", 1000, 1906, 170, 85, RED], ["rect", 1000, 1991, 170, 100, WHITE]])
    find("two_buttons_as_far_from_the_middle", [PLAIN, ["rect", 684, 1906, 170, 85, RED], ["rect", 684, 1991, 170, 100, WHITE],
                                                ["rect", 899, 1906, 170, 85, RED], ["rect", 899, 1991, 170, 100, WHITE]])
    find("two_buttons_as_far_the_higher_is_first", [PLAIN, ["rect", 899, 1806, 170, 85, RED], ["rect", 899, 1891, 170, 100, WHITE],
                                                    ["rect", 684, 1906, 170, 85, RED], ["rect", 684, 1991, 170, 100, WHITE]])
    find("two_buttons_one_has_no_white", [PLAIN, ["rect", 799, 1906, 170, 85, RED], ["rect", 600, 1906, 170, 85, RED], ["rect", 600, 1991, 170, 100, WHITE]])
    find("a_wide_red_banner_is_no_button", [PLAIN, ["rect", 0, 1800, W, 85, RED], ["rect", 0, 1885, W, 100, WHITE]])
    find("a_button_and_a_banner", button_ops() + [["rect", 0, 2100, W, 40, RED]])
    find("touching_corners_make_one", [PLAIN, ["rect", 799, 1906, 100, 60, RED], ["rect", 899, 1966, 100, 60, RED], ["rect", 799, 2040, 200, 100, WHITE]])
    find("with_noise", button_ops() + [["noise", 3, 4]])
    find("with_a_lot_of_noise", button_ops() + [["noise", 5, 25]])
    find("a_dark_night_map", button_ops(base=["fill", 40, 25, 20]))
    find("a_red_map", [["fill", 20, 20, 200], ["rect", 799, 1991, 170, 100, WHITE]])
    find("another_size_of_screenshot", button_ops(cx=450, bot=995, w=85, h=42) + [["size", 884, 1104]])
    find("a_small_picture", [PLAIN, ["size", 100, 125]])
    # the bits of the button that decide, one at a time (the red half has to be red, the white half white, as bright as the red one, in the shape of a button)
    find("red_half_with_much_blue", button_ops(red=[100, 0, 60]))
    find("red_half_with_a_little_blue", button_ops(red=[20, 0, 60]))
    find("white_half_with_a_blue_that_is_too_low", button_ops(white=[100, 200, 200]))
    find("white_half_with_a_red_that_is_too_low", button_ops(white=[180, 180, 170]))
    find("white_half_with_a_red_that_is_high_enough", button_ops(white=[170, 180, 180]))
    find("white_half_with_a_green_that_is_too_low", button_ops(white=[180, 170, 180]))
    find("white_half_with_a_green_that_is_too_high", button_ops(white=[180, 200, 180]))
    find("white_half_with_a_green_that_is_too_high_the_other_way", button_ops(white=[200, 180, 180]))
    find("the_red_half_is_brighter_a_little_higher_up", button_ops(white=[200, 200, 200]) + [["rect", 799, 1991 - 34, 170, 1, [30, 30, 255]]])
    find("the_red_half_is_brighter_a_little_lower_down", button_ops(white=[200, 200, 200]) + [["rect", 799, 1991 - 17, 170, 1, [30, 30, 255]]])
    find("the_red_half_is_brighter_much_higher_up", button_ops(white=[200, 200, 200]) + [["rect", 799, 1991 - 51, 170, 1, [30, 30, 255]]])
    find("the_red_half_starts_at_the_top_of_the_region", button_ops(bot=1752, w=100, h=30))
    find("the_red_half_starts_a_row_above_the_region", button_ops(bot=1751, w=100, h=30))
    find("the_red_half_starts_a_row_below_the_region", button_ops(bot=1753, w=100, h=30))
    # a red half that is not full: the red has to fill more than 0.3 of its box (the box stays the same, the red is a frame of a thickness: from 10 px on it does)
    # exactly 0.3 of a box of 100 x 50 (1500 of 5000 pixels) is not more than 0.3: a bar across the top, a bar down the left and a few pixels to make the number
    for extra, name in ((19, "just_under"), (20, "exactly"), (21, "just_over")):
        find("the_red_fills_%s_0_3_of_the_box" % name, [PLAIN, ["rect", 834, 1941, 100, 10, RED], ["rect", 834, 1951, 12, 40, RED], ["rect", 934 - extra, 1951, extra, 1, RED],
                                                       ["rect", 834, 1991, 100, 100, WHITE]])
    for thick in (5, 6, 9, 10, 12, 13):
        find("a_frame_of_%d_px" % thick, [PLAIN, ["rect", 799, 1906, 170, 85, RED], ["rect", 799 + thick, 1906 + thick, 170 - 2 * thick, 85 - 2 * thick, ["fill", 70, 90, 60][1:]],
                                            ["rect", 799, 1991, 170, 100, WHITE]])
    find("a_picture_of_one_row_of_red", [["fill", 20, 20, 200], ["size", 400, 10]])
    find("button_at_the_last_row", [PLAIN, ["rect", 799, 2038, 170, 170, RED]])
    find("button_with_a_big_white_half", button_ops(below=300))
    find("button_in_the_middle_of_a_wide_screen", button_ops(cx=884, bot=1991) + [["size", 2208, 1768]])

    # ---- display_plan(): what does the display have to be?
    def plan(name, screen, wm, **spec):
        story("plan_" + name, [{"fn": "plan"}], screen={"w": screen[0], "h": screen[1]}, wm=[wm], **spec)

    plan("a_tall_phone", (1080, 2400), wm_text((1080, 2400)))
    plan("another_tall_phone", (1440, 3120), wm_text((1440, 3120)))
    plan("a_phone_of_1080x1920", (1080, 1920), wm_text((1080, 1920)))
    plan("a_phone_of_1080x2340", (1080, 2340), wm_text((1080, 2340)))
    plan("turned_the_other_way", (2400, 1080), wm_text((1080, 2400)))
    plan("turned_the_other_way_a_small_one", (1920, 1080), wm_text((1080, 1920)))
    plan("already_the_shape", (1768, 2208), wm_text((1768, 2208)))
    plan("almost_the_shape", (1766, 2206), wm_text((1766, 2206)))
    plan("two_off", (1770, 2210), wm_text((1770, 2210)))
    plan("three_off", (1771, 2210), wm_text((1771, 2210)))
    plan("too_small", (480, 854), wm_text((480, 854)))
    plan("small_but_enough", (700, 1500), wm_text((700, 1500)))
    plan("the_height_is_too_small", (1000, 1500), wm_text((1000, 1500)))
    plan("another_phone_than_the_screenshot", (1080, 2400), wm_text((1440, 3120)))
    plan("no_physical_size", (1080, 2400), "Error: nothing\n")
    plan("an_empty_answer", (1080, 2400), "")
    plan("own_override", (1080, 1348), wm_text((1080, 2400), (1080, 1348)),
         record={"set": "1080x1348", "time": 900.0, "model": "x", "was": "1080x2400"})
    plan("another_override_of_ours", (1080, 1348), wm_text((1080, 2400), (1080, 1348)),
         record={"set": "1000x1200", "time": 900.0, "model": "x", "was": "1080x2400"})
    plan("an_override_of_somebody_else", (1080, 1348), wm_text((1080, 2400), (1080, 1348)))
    plan("an_override_with_a_record_without_set", (1080, 1348), wm_text((1080, 2400), (1080, 1348)), record={"time": 900.0})
    plan("an_override_with_a_record_that_is_not_json", (1080, 1348), wm_text((1080, 2400), (1080, 1348)), record="this is not json")
    plan("an_override_with_a_record_that_is_a_list", (1080, 1348), wm_text((1080, 2400), (1080, 1348)), record="[1, 2]")
    plan("an_override_with_an_empty_set", (1080, 1348), wm_text((1080, 2400), (1080, 1348)), record={"set": ""})
    plan("the_override_line_first", (1080, 2400), "Override size: 1080x1348\nPhysical size: 1080x2400\n")
    plan("only_an_override", (1080, 1348), "Override size: 1080x1348\n")
    plan("words_and_spaces", (1080, 2400), "Physical size:   1080x2400  \nPhysical size: 100x100\n")
    story("plan_the_phone_does_not_answer", [{"fn": "plan"}], screen={"w": 1080, "h": 2400}, wm=[{"raise": "device offline"}])
    story("plan_after_a_change_of_the_screen", [{"fn": "plan"}, {"fn": "judge", "w": 1440, "h": 3120}, {"fn": "plan"}], screen={"w": 1080, "h": 2400},
          wm=[wm_text((1080, 2400)), wm_text((1440, 3120))])

    # ---- adapt_display() and restore_display(): the display is changed (after the record of it is written) and put back
    ok_detect = {"w": 1080, "h": 1348}
    story("adapt_works", [{"fn": "adapt"}], screen={"w": 1080, "h": 2400, "model": "Pixel"}, wm=[wm_text((1080, 2400))], detects=[ok_detect])
    story("adapt_works_for_a_phone_turned_the_other_way", [{"fn": "adapt"}], screen={"w": 2400, "h": 1080, "model": "Pixel"}, wm=[wm_text((1080, 2400))],
          detects=[{"w": 1348, "h": 1080}])
    story("adapt_works_and_the_sizes_are_the_other_way_round", [{"fn": "adapt"}], screen={"w": 1080, "h": 2400}, wm=[wm_text((1080, 2400))],
          detects=[{"w": 1348, "h": 1080}])
    story("adapt_not_allowed", [{"fn": "adapt"}], screen={"w": 1080, "h": 2400}, wm=[wm_text((1080, 2400))], no_adapt=True)
    story("adapt_has_no_plan", [{"fn": "adapt"}], screen={"w": 1768, "h": 2208}, wm=[wm_text((1768, 2208))])
    story("adapt_cannot_write_the_record", [{"fn": "adapt"}], screen={"w": 1080, "h": 2400}, wm=[wm_text((1080, 2400))], record_write_error="Permission denied")
    story("adapt_is_refused_by_the_phone", [{"fn": "adapt"}], screen={"w": 1080, "h": 2400}, wm=[wm_text((1080, 2400))], wm_set=[{"raise": "wm: not allowed"}])
    story("adapt_gives_another_size", [{"fn": "adapt"}], screen={"w": 1080, "h": 2400}, wm=[wm_text((1080, 2400))], detects=[{"w": 1080, "h": 2400}],
          wm_reset=[None])
    story("adapt_gives_another_size_and_the_reset_fails", [{"fn": "adapt"}], screen={"w": 1080, "h": 2400}, wm=[wm_text((1080, 2400))],
          detects=[{"w": 1000, "h": 1000}], wm_reset=[{"raise": "device offline"}])
    story("adapt_cannot_look_at_the_screen_after_the_change", [{"fn": "adapt"}], screen={"w": 1080, "h": 2400}, wm=[wm_text((1080, 2400))],
          detects=[{"raise": "no display can be captured"}])
    story("adapt_finds_no_display_after_the_change", [{"fn": "adapt"}], screen={"w": 1080, "h": 2400}, wm=[wm_text((1080, 2400))], detects=[{"none": True}],
          wm_reset=[None])
    story("adapt_after_the_phone_changed_its_model", [{"fn": "adapt"}], screen={"w": 1080, "h": 2400, "model": "A"}, wm=[wm_text((1080, 2400))],
          detects=[{"w": 1080, "h": 1348, "model": "B"}])
    story("adapt_when_it_is_already_adapted", [{"fn": "adapt"}], screen={"w": 1080, "h": 1348}, wm=[wm_text((1080, 2400), (1080, 1348))],
          record={"set": "1080x1348", "time": 1.0, "model": "x", "was": "y"})
    story("restore_with_no_record", [{"fn": "restore"}], wm=[wm_text((1080, 2400))])
    story("restore_puts_it_back", [{"fn": "restore"}], screen={"w": 1080, "h": 1348}, record={"set": "1080x1348", "time": 1.0, "model": "x", "was": "y"},
          detects=[{"w": 1080, "h": 2400}])
    story("restore_cannot_put_it_back", [{"fn": "restore"}], record={"set": "1080x1348", "time": 1.0, "model": "x", "was": "y"},
          wm_reset=[{"raise": "device offline"}])
    story("restore_cannot_look_at_the_screen_afterwards", [{"fn": "restore"}], record={"set": "1080x1348", "time": 1.0, "model": "x", "was": "y"},
          detects=[{"raise": "no display"}])
    story("restore_finds_no_display_afterwards", [{"fn": "restore"}], record={"set": "1080x1348", "time": 1.0, "model": "x", "was": "y"}, detects=[{"none": True}])
    story("restore_with_a_record_that_is_no_use", [{"fn": "restore"}], record="not json")
    story("restore_with_a_record_without_set", [{"fn": "restore"}], record={"time": 1.0})
    story("restore_twice", [{"fn": "restore"}, {"fn": "restore"}], record={"set": "1080x1348", "time": 1.0, "model": "x", "was": "y"}, detects=[{"w": 1080, "h": 2400}])
    story("adapt_and_restore", [{"fn": "adapt"}, {"fn": "restore"}, {"fn": "adapt"}], screen={"w": 1080, "h": 2400, "model": "Pixel"},
          wm=[wm_text((1080, 2400)), wm_text((1080, 2400), (1080, 1348)), wm_text((1080, 2400))], detects=[ok_detect, {"w": 1080, "h": 2400}, ok_detect])

    # ---- wait_unsupported(): do nothing and look again (a foldable may be unfolded); say so every ten minutes
    story("wait_says_why_the_first_time", [{"fn": "wait_unsupported"}], screen={"w": 1080, "h": 2400}, detects=[{"w": 1080, "h": 2400}])
    story("wait_says_it_every_ten_minutes", [{"fn": "wait_unsupported"} for _ in range(25)], screen={"w": 1080, "h": 2400}, detects=[{"w": 1080, "h": 2400}])
    story("wait_says_it_after_more_than_ten_minutes", [{"fn": "wait_unsupported"}, {"fn": "wait_unsupported", "advance": 600}, {"fn": "wait_unsupported", "advance": 600.5}],
          screen={"w": 1080, "h": 2400}, detects=[{"w": 1080, "h": 2400}])
    story("wait_and_the_foldable_is_unfolded", [{"fn": "wait_unsupported"}, {"fn": "wait_unsupported"}], screen={"w": 904, "h": 2316},
          detects=[{"w": 904, "h": 2316}, {"w": 1768, "h": 2208}])
    story("wait_cannot_look", [{"fn": "wait_unsupported"}], screen={"w": 904, "h": 2316}, detects=[{"raise": "adb offline"}])
    story("wait_finds_no_display", [{"fn": "wait_unsupported"}], screen={"w": 904, "h": 2316}, detects=[{"none": True}])

    # ---- layout_init(): a display change that an earlier run did not get to put back
    rec1 = {"set": "1080x1348", "time": 1.0, "model": "x", "was": "1080x2400"}
    story("init_with_no_record", [{"fn": "init"}], wm=[wm_text((1080, 2400))])
    story("init_takes_the_change_over", [{"fn": "init"}], wm=[wm_text((1080, 2400), (1080, 1348))], record=rec1, screen={"w": 1080, "h": 1348})
    story("init_forgets_a_record_that_is_not_active", [{"fn": "init"}], wm=[wm_text((1080, 2400))], record=rec1)
    story("init_forgets_a_record_of_another_size", [{"fn": "init"}], wm=[wm_text((1080, 2400), (1000, 1200))], record=rec1)
    story("init_forgets_a_record_when_the_phone_does_not_answer", [{"fn": "init"}], wm=[{"raise": "device offline"}], record=rec1)
    story("init_with_a_record_that_is_no_use", [{"fn": "init"}], wm=[wm_text((1080, 2400), (1080, 1348))], record="[]")
    story("init_with_an_override_of_somebody_else", [{"fn": "init"}], wm=[wm_text((1080, 2400), (1080, 1348))])
    for name, value in (("zero", 0), ("zero_point_zero", 0.0), ("a_tenth", 0.1), ("minus_a_tenth", -0.1), ("five", 5), ("empty", ""), ("null", None), ("false", False),
                        ("true", True), ("an_empty_list", []), ("a_list", [1]), ("an_empty_object", {}), ("an_object", {"a": 1})):
        story("init_with_a_record_that_sets_" + name, [{"fn": "init"}], wm=[wm_text((1080, 2400), (1080, 1348))], record={"set": value, "time": 1.0})

    # ---- layout_adapt(): try to get the game drawn in the right shape (once in half an hour)
    bad = {"w": 1080, "h": 2400, "model": "Pixel"}
    story("layout_adapt_works", [{"fn": "layout_adapt", "why": "the menu button is far off"}], screen=bad, wm=[wm_text((1080, 2400))], detects=[ok_detect],
          layout={"state": "new", "looks": 3})
    story("layout_adapt_is_not_possible", [{"fn": "layout_adapt", "why": "the menu button is far off"}], screen={"w": 1768, "h": 2208},
          wm=[wm_text((1768, 2208))])
    story("layout_adapt_is_not_allowed", [{"fn": "layout_adapt", "why": "x"}], screen=bad, wm=[wm_text((1080, 2400))], no_adapt=True)
    story("layout_adapt_waits_for_the_next_try", [{"fn": "layout_adapt", "why": "x"}], screen=bad, wm=[wm_text((1080, 2400))], layout={"next_try": 1000.5})
    story("layout_adapt_at_the_moment_of_the_next_try", [{"fn": "layout_adapt", "why": "x"}], screen=bad, wm=[wm_text((1080, 2400))], detects=[ok_detect],
          layout={"next_try": 1000.0})
    story("layout_adapt_twice", [{"fn": "layout_adapt", "why": "x"}, {"fn": "layout_adapt", "why": "y"},
                                 {"fn": "layout_adapt", "why": "z", "advance": 1800}],
          screen={"w": 1768, "h": 2208}, wm=[wm_text((1768, 2208))])
    story("layout_adapt_fails_in_the_phone", [{"fn": "layout_adapt", "why": "x"}], screen=bad, wm=[wm_text((1080, 2400))], wm_set=[{"raise": "no"}])
    story("layout_adapt_cannot_ask_the_phone", [{"fn": "layout_adapt", "why": "x"}], screen=bad, wm=[{"raise": "device offline"}])
    story("layout_adapt_cannot_look_afterwards", [{"fn": "layout_adapt", "why": "x"}], screen=bad, wm=[wm_text((1080, 2400))], detects=[{"raise": "boom"}])

    # ---- layout_undo(): the display change did not work out
    story("undo_with_a_record", [{"fn": "layout_undo", "why": "the map was not seen"}], record=rec1, detects=[{"w": 1080, "h": 2400}], layout={"state": "adapting",
                                                                                                                                         "looks": 2})
    story("undo_with_no_record", [{"fn": "layout_undo", "why": "x"}], layout={"state": "adapting"})
    story("undo_cannot_put_it_back", [{"fn": "layout_undo", "why": "x"}], record=rec1, wm_reset=[{"raise": "device offline"}], layout={"state": "adapting"})

    # ---- layout_watch(): after a display change the map has to come back within five minutes
    for name, state, since, now in (("adapting_in_time", "adapting", 1000.0, 0), ("adapting_at_five_minutes", "adapting", 700.0, 0),
                                    ("adapting_after_five_minutes", "adapting", 699.5, 0), ("adapting_long_ago", "adapting", 0.0, 0),
                                    ("confirmed_long_ago", "confirmed", 0.0, 0), ("new_long_ago", "new", 0.0, 0), ("adapted_long_ago", "adapted", 0.0, 0),
                                    ("unverified_long_ago", "unverified", 0.0, 0)):
        story("watch_" + name, [{"fn": "watch"}], layout={"state": state, "since": since}, record=rec1, detects=[{"w": 1080, "h": 2400}])
    story("watch_cannot_put_it_back", [{"fn": "watch"}], layout={"state": "adapting", "since": 0.0}, record=rec1, wm_reset=[{"raise": "device offline"}])

    # ---- layout_tap_test(): tap the menu button and see whether the menu opens, then back to the map
    mp = frame(button_ops())
    menu = frame([PLAIN, ["rect", 10, 10, 50, 50, [200, 100, 50]]], lines=[line("ITEMS", 1200, 1500), line("POKEMON", 500, 1500)])
    bag = frame([PLAIN, ["rect", 20, 20, 50, 50, [200, 100, 50]]], lines=[line("ITEMS", 884, 300)])
    exit_q = frame([PLAIN, ["rect", 30, 30, 50, 50, [200, 100, 50]]], lines=[line("Do you want to exit Pokemon GO?", 884, 900), line("CANCEL", 700, 1200)])
    exit_no_cancel = frame([PLAIN, ["rect", 30, 30, 50, 50, [200, 100, 50]]], lines=[line("Do you want to exit POK", 884, 900)])
    other = frame([PLAIN, ["rect", 40, 40, 50, 50, [10, 200, 50]]], lines=[line("SOMETHING ELSE", 884, 900)])
    same_as_map = frame(button_ops() + [["rect", 0, 0, 20, 20, [250, 250, 250]]])
    changed_a_lot = frame([["fill", 10, 200, 10]], lines=[line("SOMETHING ELSE", 884, 900)])
    frames = [mp, menu, bag, exit_q, exit_no_cancel, other, same_as_map, changed_a_lot]
    MP, MENU, BAG, EXIT, EXIT_NO, OTHER, SAME, CHANGED = range(8)

    def tap_story(name, shots, **kw):
        story("tap_test_" + name, [{"fn": "tap_test", "before": MP}], frames=frames, shots=shots, **kw)
    tap_story("the_menu_opens_and_the_map_comes_back", [MENU, MENU, MP])
    tap_story("the_menu_opens_but_keeps_moving", [MENU, BAG, BAG, MENU, MP])
    tap_story("the_menu_opens_and_the_map_comes_back_at_once", [MENU, MENU, MP, MP])
    tap_story("the_bag_opens", [BAG, BAG, MP, MP])
    tap_story("the_map_stays", [MP, MP])
    tap_story("something_else_that_is_not_the_map_and_changed", [OTHER, OTHER, MP])
    tap_story("something_else_that_looks_like_the_map_is_the_map", [SAME, SAME])
    tap_story("something_else_that_did_not_change_much_is_not_a_menu", [OTHER, OTHER, MP])
    tap_story("the_question_to_exit_is_cancelled", [EXIT, EXIT, MP, MP])
    tap_story("the_question_to_exit_with_no_cancel_goes_back", [EXIT_NO, EXIT_NO, MP, MP])
    tap_story("the_question_to_exit_stays_four_times", [EXIT, EXIT, EXIT, EXIT, EXIT, EXIT, EXIT, EXIT, EXIT, EXIT, EXIT, EXIT])
    tap_story("it_never_gets_back_to_the_map", [MENU, MENU, BAG, BAG, BAG, BAG, BAG, BAG, BAG, BAG, BAG, BAG])
    tap_story("it_gets_back_to_the_map_after_the_last_try", [MENU, MENU, BAG, BAG, BAG, BAG, BAG, BAG, BAG, BAG, BAG, BAG, MP])
    tap_story("a_picture_that_changes_a_lot_is_other", [CHANGED, CHANGED, MP])
    tap_story("shots_that_take_time", [MENU, MENU, MP], shot_seconds=1.5)

    # ---- layout_verify(): the first map pictures of a run
    def verify(name, shots, imgs, **kw):
        story("verify_" + name, [{"fn": "verify", "img": i} for i in imgs], frames=frames + [frame(button_ops(**p)) for p in kw.pop("buttons", [])], shots=shots, **kw)
    base = len(frames)                                          # the number of the first picture after the ones of the tap test
    verify("the_button_is_where_it_should_be", [MENU, MENU, MP], [0])
    verify("the_button_is_found_after_a_change", [MENU, MENU, MP], [0], layout={"state": "adapting", "since": 900.0})
    verify("the_button_is_where_it_should_be_in_the_second_run", [MENU, MENU, MP], [0, 0], layout={"state": "confirmed"})
    verify("the_menu_does_not_open_after_a_change", [MP, MP], [0], layout={"state": "adapting", "since": 900.0}, record=rec1, detects=[{"w": 1080, "h": 2400}])
    verify("no_button_one_look", [MENU], [base], buttons=[{"cx": 884, "bot": 1991, "w": 170, "red": [60, 60, 60], "white": [60, 60, 60]}])
    verify("no_button_four_looks", [MENU], [base] * 4, buttons=[{"red": [60, 60, 60], "white": [60, 60, 60]}])
    verify("no_button_three_looks", [MENU], [base] * 3, buttons=[{"red": [60, 60, 60], "white": [60, 60, 60]}])
    verify("no_button_after_a_change", [MENU], [base] * 4, buttons=[{"red": [60, 60, 60], "white": [60, 60, 60]}], layout={"state": "adapting", "since": 900.0},
           record=rec1, detects=[{"w": 1080, "h": 2400}])
    verify("no_button_after_a_change_in_the_first_looks", [MENU], [base] * 3, buttons=[{"red": [60, 60, 60], "white": [60, 60, 60]}],
           layout={"state": "adapting", "since": 900.0}, record=rec1)
    verify("the_button_is_off_and_it_cannot_be_helped", [MENU], [base], buttons=[{"cx": 700, "bot": 1900}], screen={"w": 1768, "h": 2208}, wm=[wm_text((1768, 2208))])
    verify("the_button_is_off_and_the_display_is_adapted", [MENU, MENU, MP], [base], buttons=[{"cx": 700, "bot": 1900}], screen={"w": 1080, "h": 2400},
           wm=[wm_text((1080, 2400))], detects=[ok_detect])
    verify("the_button_is_off_and_the_phone_does_not_allow_it", [MENU], [base], buttons=[{"cx": 700, "bot": 1900}], screen={"w": 1080, "h": 2400},
           wm=[wm_text((1080, 2400))], no_adapt=True)
    verify("the_button_is_off_for_the_second_time_too_soon", [MENU], [base, base], buttons=[{"cx": 700, "bot": 1900}], screen={"w": 1768, "h": 2208},
           wm=[wm_text((1768, 2208))])
    verify("the_button_is_off_after_a_change", [MENU], [base], buttons=[{"cx": 700, "bot": 1900}], layout={"state": "adapting", "since": 900.0}, record=rec1,
           detects=[{"w": 1080, "h": 2400}])
    verify("the_button_is_too_wide", [MENU], [base], buttons=[{"w": 230}], screen={"w": 1768, "h": 2208}, wm=[wm_text((1768, 2208))])
    verify("the_button_is_just_in_range", [MENU], [base], buttons=[{"cx": 929, "bot": 2051, "w": 198}])
    verify("a_look_of_the_state_unverified", [MENU], [base], buttons=[{"cx": 700, "bot": 1900}], layout={"state": "unverified"})
    verify("looks_are_counted_over_the_pictures", [MENU], [base, 0, base, base, base], buttons=[{"red": [60, 60, 60], "white": [60, 60, 60]}])
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
