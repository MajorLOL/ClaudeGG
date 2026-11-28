#!/usr/bin/env python3
"""Makes tests/fixtures/catch_golden.json.qz (JSON, packed the way qCompress() of Qt does: the length, then zlib): what gamebot.py does at the
catch screen of Pokémon GO around the throw - do_encounter() (a Pokémon that is met: the ball that is chosen, the berry that is fed, the throws, a
storage that is full, a screen that is not the catch screen any more), wait_for_result() (the ball that comes back, the result screen with the teal
OK, another screen), fast_catch_leave() (BACK while the ball comes down), catch_result_button(), tap_catch_result(), tap_button(), pick_berry() with
tray_labels() (the berry tray read by the tesseract program) and finish_catch() - as the file that the C++ port
(SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoCatch.cpp) is tested against.

    python3 tools/make_catch_golden.py            writes the file
    python3 tools/make_catch_golden.py --check    says whether the file is what the code does now (the stories stored in it are played again)

The file is a list of stories: a list of calls, each with the EVENTS that it makes, with the time of a fake clock (it starts at 1000.0 and only moves
with the screenshots, the sleeps and the throws).  The pictures are drawn on the canvas by the ops of tools/make_throw_golden.py (the buttons of the
catch screen, the teal OK, a green button), and the readers of pictures (ball_ready, result_ok_button, find_green_button) are the real ones.
What the code is GIVEN:
    shot          a screenshot (which of the frames of the story, quick or real)
    screen        the screen classifier looked at a frame and said this (its name and certainty)
    buttons       the detector of buttons looked at a frame and found these
    ocr_text      the text reader read the text in a strip of a frame
    ocr           the text reader read the lines of a frame (with the places of the words)
    tesseract     the tesseract program was given the berry tray and answered with this table
    throw         a ball was thrown: how long it took, whether it came down on the Pokémon, how long before the end of it the ball was let go
    step          a step of the bot (finish_catch) took this long and said how long to wait, or failed
    day_count     the text of the counters of the day
  what it DOES (the C++ port has to do the same, in this order):
    tap, back, sleep, log, save (a picture that is kept), beat, then at the end of every call: result (what it returned) and state (what it
    remembers: the Pokémon that is being caught, where it was tapped, the fast catch that waits for its check, the picture that is handed on)."""
import argparse
import copy
import json
import os
import struct
import subprocess
import sys
import types
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_throw_golden as TG  # noqa: E402  (the pictures: the buttons of the catch screen)
from make_start_golden import START, Clock, Rec, mean, exact  # noqa: E402
import cv2  # noqa: E402
import numpy as np  # noqa: E402
import gamebot as G  # noqa: E402
import spin_stop as S  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "tests", "fixtures", "catch_golden.json.qz")
W, H = TG.W, TG.H


# ---------------------------------------------------------------------- what the code remembers

STATE = ("enc", "enc_xy", "throw_info", "fast_pending", "fast_state", "storage_state")
_defaults = {name: json.loads(json.dumps(getattr(G, name))) for name in STATE}
_ball, _berries = G.BALL, list(G.BERRY_ORDER)


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


def snapshot(world):
    state = {name: jsonable(getattr(G, name)) for name in STATE}
    img = G.handoff["img"]
    state["handoff"] = {"img": None if img is None else world.index_of(img), "t": jsonable(G.handoff["t"])}
    return state


def restore(init):
    for name in STATE:
        target = getattr(G, name)
        target.clear()
        target.update(copy.deepcopy(_defaults[name]))
        if name in init:
            target.update(copy.deepcopy(init[name]))
    G.handoff.update(img=None, t=0.0)


# ---------------------------------------------------------------------- the fake phone

class World:
    """The frames of a story: the pictures (drawn once, the same array every time) with what the readers say of them (the screen classifier, the
    detector of buttons, the text readers, the check for the map)."""

    def __init__(self, spec):
        self.frames = spec["frames"]
        self.cache = {}
        self.by_id = {}
        self.shots = 0                        # screenshots asked for so far
        self.throws = 0
        self.steps = 0
        self.tables = 0

    def picture(self, index):
        if index not in self.cache:
            img = TG.make_scene(self.frames[index]["pic"])
            self.cache[index] = img
            self.by_id[id(img)] = index
        return self.cache[index]

    def index_of(self, img):
        base = img
        while base.base is not None:
            base = base.base
        return self.by_id[id(base)]

    def frame(self, img):
        return self.frames[self.index_of(img)]


class FakeBrain:
    """The screen classifier and the detector of buttons: they say what the frame of the picture says."""

    def __init__(self, world, rec, spec):
        self.world, self.rec, self.spec = world, rec, spec

    def screen(self, img):
        frame = self.world.frame(img)
        Clock.t += self.spec.get("screen_seconds", 0.0)
        if "screen_error" in frame:                          # the classifier fails
            self.rec.add("screen_error", self.world.index_of(img), frame["screen_error"])
            raise RuntimeError(frame["screen_error"])
        name, score = frame.get("screen", ["mapScreen", 0.9])
        self.rec.add("screen", self.world.index_of(img), name, score)
        return name, score

    def buttons(self, img):
        frame = self.world.frame(img)
        Clock.t += self.spec.get("buttons_seconds", 0.0)
        found = [tuple(b) for b in frame.get("buttons", [])]
        self.rec.add("buttons", self.world.index_of(img), [list(b) for b in found])
        return found


class FakeSubprocess:
    """The tesseract program, as gamebot.tray_labels() calls it: it is given the berry tray (as a PNG) and answers with the table of the story."""
    TimeoutExpired = subprocess.TimeoutExpired

    def __init__(self, world, rec, spec):
        self.world, self.rec, self.spec = world, rec, spec

    def run(self, argv, env=None, input=None, capture_output=False, timeout=None):
        assert argv == ["tesseract", "stdin", "stdout", "--psm", "11", "tsv"], argv
        tables = self.spec.get("tables", [])
        table = tables[min(self.world.tables, len(tables) - 1)] if tables else ""
        self.world.tables += 1
        if table is None:                                    # the program is not there
            self.rec.add("tesseract", None, None, None, None)
            raise FileNotFoundError("tesseract")
        gray = cv2.imdecode(np.frombuffer(input, np.uint8), cv2.IMREAD_GRAYSCALE)
        self.rec.add("tesseract", gray.shape[0], gray.shape[1], mean(gray), table)
        return types.SimpleNamespace(stdout=table.encode())


def tsv(*words):
    """The table that tesseract writes: a word is (text, left, top, width, height, conf)."""
    rows = ["level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"]
    for text, left, top, width, height, conf in words:
        rows.append("5\t1\t1\t1\t1\t1\t%d\t%d\t%d\t%d\t%s\t%s" % (left, top, width, height, conf, text))
    return "\n".join(rows) + "\n"


def record(spec):
    """Plays one story on the fake phone; returns the list of events."""
    Clock.t = START
    rec = Rec()
    Clock.rec = rec
    world = World(spec)
    saved_g = {n: getattr(G, n) for n in ("time", "log", "setting", "wanted", "count", "save_async", "ocr_text", "ocr_lines", "throw_ball", "step",
                                          "subprocess", "BALL", "BERRY_ORDER")}
    saved_s = {n: getattr(S, n) for n in ("time", "log", "tap", "back", "quick_screenshot", "screenshot")}
    try:
        restore(spec.get("init", {}))
        G.BALL = spec.get("ball", _ball)
        G.BERRY_ORDER = list(spec.get("berries", _berries))
        G.time = S.time = Clock
        G.log = S.log = lambda text: rec.add("log", text)
        settings = dict(spec.get("settings", {}))
        wanted = {"spin_only_when_full": False, "daily_cycle": False}
        wanted.update(spec.get("wanted", {}))
        G.setting = lambda key, default: settings.get(key, default)
        G.wanted = lambda key: bool(wanted.get(key, True))
        counts = {"caught": 0, "fled": 0, "stops": 0}

        def count(key):
            counts[key] = counts.get(key, 0) + 1
            text = "(today: %d caught, %d fled, %d stops)" % (counts["caught"], counts["fled"], counts["stops"])
            rec.add("day_count", key, text)
            return text
        G.count = count
        G.save_async = lambda name, img: rec.add("save", name, world.index_of(img))
        S.tap = lambda x, y, ms=120: rec.add("tap", x, y)
        S.back = lambda: rec.add("back")

        shots = list(spec.get("shots", [0]))

        def make_shot(kind):
            def take(on_grab=None):
                n = world.shots
                world.shots += 1
                index = shots[min(n, len(shots) - 1)]
                Clock.t += spec.get("shot_seconds", 0.0)
                if isinstance(index, str):                   # "error: text": the screenshot fails
                    text = index.split(": ", 1)[1]
                    rec.add("shot_error", kind, text)
                    raise RuntimeError(text)
                if kind == "quick":
                    take.live = bool(spec.get("live", False))
                rec.add("shot", index, kind, take.live if kind == "quick" else False)
                return world.picture(index)
            take.live = False
            return take
        S.quick_screenshot = make_shot("quick")
        S.screenshot = make_shot("real")

        def ocr_text(img, y0, y1):
            crop = img[y0:y1]
            text = world.frame(img).get("text", "")
            rec.add("ocr_text", crop.shape[0], crop.shape[1], mean(crop), text)
            return text
        G.ocr_text = ocr_text

        def ocr_lines(img, y0=0, y1=None, scale=1.0):
            lines = [ln for ln in world.frame(img).get("lines", []) if ln[2] >= y0]
            rec.add("ocr", img.shape[0], img.shape[1], y0, y1, scale, mean(img), lines)
            return lines
        G.ocr_lines = ocr_lines

        throws = list(spec.get("throws", [{"seconds": 1.0, "hit": False}]))

        def throw_ball(brain):
            one = throws[min(world.throws, len(throws) - 1)]
            world.throws += 1
            Clock.t += one["seconds"]
            G.throw_info["hit"] = one.get("hit")
            rec.add("throw", one["seconds"], one.get("hit"), one.get("ago", 1.0))
            return Clock.t - one.get("ago", 1.0)
        G.throw_ball = throw_ball

        steps = list(spec.get("steps", []))

        def step(brain):
            one = steps[min(world.steps, len(steps) - 1)] if steps else {"seconds": 0.0, "wait": 0.0}
            world.steps += 1
            Clock.t += one["seconds"]
            rec.add("step", one["seconds"], one.get("wait"), one.get("error"))
            if one.get("error"):
                raise RuntimeError(one["error"])
            return one["wait"]
        G.step = step

        G.subprocess = FakeSubprocess(world, rec, spec)
        brain = FakeBrain(world, rec, spec)

        for call in spec["calls"]:
            if "settings" in call:
                settings.update(call["settings"])
            if "advance" in call:
                Clock.t += call["advance"]
            if "init" in call:
                for name, value in call["init"].items():
                    getattr(G, name).update(copy.deepcopy(value))
            rec.add("call", call["fn"], call.get("img"), call.get("ago"))
            try:
                fn = call["fn"]
                img = world.picture(call["img"]) if "img" in call else None
                if fn == "do_encounter":
                    result = G.do_encounter(brain, img)
                elif fn == "wait_for_result":
                    result = G.wait_for_result(brain, Clock.t - call["ago"])
                elif fn == "fast_catch_leave":
                    result = G.fast_catch_leave(brain, Clock.t - call["ago"])
                elif fn == "catch_result_button":
                    result = G.catch_result_button(brain, img)
                elif fn == "tap_catch_result":
                    G.tap_catch_result(tuple(call["btn"]), call["how"])
                    result = None
                elif fn == "tap_button":
                    result = G.tap_button(brain, img, call.get("only_passenger", False))
                elif fn == "pick_berry":
                    result = G.pick_berry(img)
                elif fn == "tray_labels":
                    result = sorted([row, col, text] for (row, col), text in G.tray_labels(img).items())
                elif fn == "finish_catch":
                    result = G.finish_catch(brain, (lambda: rec.add("beat")) if call.get("beat") else None)
                elif fn == "mark_caught":
                    G.mark_caught()
                    result = None
                else:
                    raise ValueError(call)
                rec.add("result", jsonable(result))
            except Exception as e:  # noqa: BLE001
                rec.add("raised", str(e))
            rec.add("state", snapshot(world))
        return rec.events
    finally:
        for n, v in saved_g.items():
            setattr(G, n, v)
        for n, v in saved_s.items():
            setattr(S, n, v)
        restore({})
        G.BALL, G.BERRY_ORDER = _ball, list(_berries)


# ---------------------------------------------------------------------- the pictures

TEAL = None


def teal():
    global TEAL
    if TEAL is None:
        TEAL = TG.teal()
    return TEAL


PLAIN = ["fill", 70, 90, 60]
GREEN = [120, 205, 110]                                       # the green of a button (H 60, S 107, V 205)


def frame(ops=None, screen=None, buttons=None, lines=None, text=None, screen_error=None):
    f = {"pic": ops if ops is not None else [PLAIN]}
    if screen_error is not None:
        f["screen_error"] = screen_error
    if screen is not None:
        f["screen"] = list(screen)
    if buttons is not None:
        f["buttons"] = [list(b) for b in buttons]
    if lines is not None:
        f["lines"] = lines
    if text is not None:
        f["text"] = text
    return f


def catch_screen(**kw):
    """The catch screen with the ball and the berry buttons: the ball is ready."""
    return frame(TG.buttons_ops(), screen=("encounterScreen", 0.95), **kw)


def flying_screen(**kw):
    """The catch screen while the ball is in the air: no buttons."""
    return frame(TG.buttons_ops(berry=False, ball=False), screen=("encounterScreen", 0.95), **kw)


def result_screen(**kw):
    """'TOTAL XP': the teal OK pill."""
    return frame(TG.buttons_ops(berry=False, ball=False) + [["rect", 534, 1900, 700, 150, teal()]], screen=kw.pop("screen", ("rewardScreen", 0.9)), **kw)


def green_screen(**kw):
    return frame(TG.buttons_ops(berry=False, ball=False) + [["rect", 504, 1900, 760, 150, GREEN]], **kw)


def map_screen(**kw):
    """The map: the Poké Ball button at the bottom (red on top, white below) is what on_map() looks for."""
    return frame([PLAIN, ["rect", 860, 1920, 46, 20, [30, 30, 220]], ["rect", 860, 2020, 46, 30, [255, 255, 255]]], screen=("mapScreen", 0.95), **kw)


OK = (884, 1975)                                              # the middle of the teal pill above


# ---------------------------------------------------------------------- the stories

def label(text, col, row, width=120, height=40, conf="90", dy=0):
    """A word of the berry tray as tesseract writes it: in this column and row of the tray (the strip that is read starts at y = 1380)."""
    cx = G.TRAY_COLS[col]
    cy = (G.TRAY_LABEL_Y[row][0] + G.TRAY_LABEL_Y[row][1]) // 2 + dy
    return (text, cx - width // 2, cy - 1380 - height // 2, width, height, conf)


def stories():
    out = []
    cs, fs, rs, gs, ms, pl = catch_screen(), flying_screen(), result_screen(), green_screen(), map_screen(), frame()

    def add(name, calls, frames, **spec):
        spec.update(calls=calls, frames=frames)
        out.append({"id": name, "spec": spec})

    def call(fn, **kw):
        return dict({"fn": fn}, **kw)

    # ---- catch_result_button(): the teal OK of the result screen, but only when a ball was thrown, and not when the screen is still sure to be the catch screen
    for name, throws, shot in (("no_ball_thrown", 0, rs), ("a_ball_thrown", 1, rs),
                               ("the_catch_screen_is_sure", 1, result_screen(screen=("encounterScreen", 0.8))),
                               ("the_catch_screen_is_not_quite_sure", 1, result_screen(screen=("encounterScreen", 0.79))),
                               ("the_catch_screen_is_very_sure", 1, result_screen(screen=("encounterScreen", 0.99))),
                               ("another_screen_that_is_sure", 1, result_screen(screen=("mapScreen", 0.99))),
                               ("no_button", 1, cs)):
        add("result_button_%s" % name, [call("catch_result_button", img=0)], [shot], init={"enc": {"throws": throws}}, screen_seconds=0.3)

    # ---- tap_catch_result(): the log line, the counted catch (only when a ball was thrown and it was not counted yet), the time of the tap, the tap
    add("tap_result_first_time", [call("tap_catch_result", btn=OK, how="seen while waiting")], [pl], init={"enc": {"throws": 2}}, advance=3.5)
    add("tap_result_already_counted", [call("tap_catch_result", btn=OK, how="classified as catch screen")], [pl], init={"enc": {"throws": 2, "caught": True}})
    add("tap_result_no_ball_thrown", [call("tap_catch_result", btn=(10, 20), how="seen while waiting")], [pl])
    add("mark_caught_twice", [call("mark_caught"), call("mark_caught")], [pl], init={"enc": {"throws": 3}}, advance=4.0)
    add("mark_caught_nothing_thrown", [call("mark_caught")], [pl])

    # ---- tap_button(): the wide button in the middle (a button that starts a battle or joins a group is not tapped)
    def btn(x=884, y=1900, w=700, h=150, score=0.5, name="clickable"):
        return (name, score, x, y, w, h)
    for name, buttons, text in (("a_button", [btn()], "OK"), ("no_buttons", [], ""),
                                ("too_unsure_0_25", [btn(score=0.25)], "OK"), ("too_unsure_0_249", [btn(score=0.249)], "OK"),
                                ("too_far_left_250", [btn(x=634)], "OK"), ("far_left_249", [btn(x=635)], "OK"),
                                ("far_right_249", [btn(x=1133)], "OK"), ("too_far_right_250", [btn(x=1134)], "OK"),
                                ("too_narrow_500", [btn(w=500)], "OK"), ("narrow_501", [btn(w=501)], "OK"),
                                ("not_clickable", [btn(name="passenger")], "OK"),
                                ("the_second_one", [btn(w=300), btn(x=900, y=1700)], "CLAIM REWARD"),
                                ("it_is_at_the_top", [btn(y=100, h=300)], "OK"),
                                ("it_is_at_the_bottom", [btn(y=2150, h=200)], "OK")):
        add("button_%s" % name, [call("tap_button", img=0)], [frame(buttons=buttons, text=text)])
    for word in ("BATTLE", "FIGHT", "USE THIS PARTY", "LET'S GO", "JOIN", "GROUP", "DETAILS"):
        add("button_that_is_a_%s_button" % word.lower().replace(" ", "_").replace("'", ""), [call("tap_button", img=0)],
            [frame(buttons=[btn()], text="TAP TO %s NOW" % word)])
    for name, score, kind in (("passenger_0_8", 0.8, "passenger"), ("passenger_0_79", 0.79, "passenger"), ("another_button", 0.9, "clickable")):
        add("button_only_the_passenger_%s" % name, [call("tap_button", img=0, only_passenger=True)], [frame(buttons=[btn(), btn(name=kind, score=score, w=100)], text="OK")])

    # ---- wait_for_result(): look after the throw until the ball is back, the result screen shows its OK, or another screen is there
    for ago in (0.5, 1.8, 1.9, 2.0, 3.0):
        add("wait_first_look_%s" % str(ago).replace(".", "_"), [call("wait_for_result", ago=ago)], [cs], shots=[0], init={"enc": {"throws": 1}})
    add("wait_flying_then_back", [call("wait_for_result", ago=1.0)], [fs, cs], shots=[0, 0, 1], init={"enc": {"throws": 1}}, shot_seconds=0.25)
    add("wait_flying_then_back_live", [call("wait_for_result", ago=1.0)], [fs, cs], shots=[0, 0, 1], init={"enc": {"throws": 1}}, shot_seconds=0.25, live=True)
    add("wait_caught", [call("wait_for_result", ago=1.0)], [fs, rs], shots=[0, 1], init={"enc": {"throws": 1}}, advance=0.5)
    add("wait_the_result_screen_is_still_the_catch_screen", [call("wait_for_result", ago=1.0)], [result_screen(screen=("encounterScreen", 0.9)), rs],
        shots=[0, 1], init={"enc": {"throws": 1}})
    for name, screen in (("sure_0_5", ("mapScreen", 0.5)), ("not_sure_0_49", ("mapScreen", 0.49)), ("a_catch_screen", ("encounterScreen", 0.99)),
                         ("something_else", ("pokemonScreen", 0.9))):
        add("wait_another_screen_%s" % name, [call("wait_for_result", ago=1.0)], [frame(screen=screen), cs],
            shots=[0, 0, 1], init={"enc": {"throws": 1}}, shot_seconds=0.25)
    add("wait_nothing_comes_in_20_s", [call("wait_for_result", ago=1.0)], [fs], shots=[0], init={"enc": {"throws": 1}}, shot_seconds=2.0)
    add("wait_nothing_comes_live", [call("wait_for_result", ago=1.0)], [fs], shots=[0], init={"enc": {"throws": 1}}, shot_seconds=0.5, live=True)
    add("wait_the_window_ends_exactly", [call("wait_for_result", ago=0.0)], [fs], shots=[0], init={"enc": {"throws": 1}}, shot_seconds=5.0)
    add("wait_a_screenshot_fails", [call("wait_for_result", ago=1.0)], [fs], shots=["error: no screen"], init={"enc": {"throws": 1}})

    # ---- tray_labels(): the names of the berries in the tray, read by tesseract: {(row, column): text}
    def raw(text, cx, cy, width=120, height=40, conf="90"):
        """A word whose middle is at (cx, cy) of the screen (the strip that is read starts at y = 1380)."""
        return (text, cx - width // 2, cy - 1380 - height // 2, width, height, conf)

    def tray(name, table, fn="tray_labels", **spec):
        add("%s_%s" % (fn, name), [call(fn, img=0)], [pl], tables=[table], **spec)

    tray("the_six_cells", tsv(*[label("%s%d%d" % ("ABC"[c], r, c), c, r) for r in range(2) for c in range(3)]))
    tray("two_words_in_one_cell", tsv(label("SILVER", 0, 0), label("PINAP", 0, 0, width=60), label("BERRY", 0, 0)))
    tray("the_words_of_a_cell_in_the_order_of_the_table", tsv(label("B", 2, 1), label("A", 0, 1), label("D", 2, 1), label("C", 0, 1)))
    for name, cy in (("row0_top_1419", 1419), ("row0_top_1420", 1420), ("row0_bottom_1540", 1540), ("row0_below_1541", 1541),
                     ("row1_above_1949", 1949), ("row1_top_1950", 1950), ("row1_bottom_2140", 2140), ("row1_below_2141", 2141),
                     ("between_the_rows", 1700), ("far_above", 1000)):
        tray("height_%s" % name, tsv(raw("PINAP", 326, cy)))
    for name, cx in (("far_left", 0), ("col0", 326), ("tie_0_1_603", 603), ("just_over_the_tie_604", 604), ("col1", 880),
                     ("tie_1_2_1156", 1156), ("just_before_the_tie_1155", 1155), ("just_over_the_tie_1157", 1157), ("col2", 1432), ("far_right", 5000)):
        tray("column_%s" % name, tsv(raw("RAZZ", cx, 1480)))
    for name, conf in (("30", "30"), ("29", "29"), ("29_9", "29.9"), ("30_0", "30.0"), ("30_1", "30.1"), ("100", "100"), ("0", "0"), ("none", ""),
                       ("minus_one", "-1"), ("minus_one_float", "-1.000000"), ("spaces", " 95 ")):
        tray("confidence_%s" % name, tsv(label("PINAP", 0, 0, conf=conf)))
    tray("confidence_garbage", tsv(label("PINAP", 0, 0, conf="abc")))
    tray("confidence_garbage_of_an_empty_word", tsv(label("", 0, 0, conf="abc")))
    for name, word in (("lower_case", "pinap"), ("padded", "  pinap\t"), ("mixed", "Nanab"), ("empty", ""), ("only_spaces", "   "), ("accent", "pinapé"),
                       ("quote", "PINAP'S"), ("quotes", "PINAP'S \"BEST\""), ("backslash", "PINAP\\"), ("zero_width", "PINAP​"), ("tab_like", "PINAP\x01")):
        tray("text_%s" % name, tsv(label(word, 0, 0)), fn="pick_berry")
    tray("odd_width", tsv(raw("NANAB", 880, 1480, width=121)))
    tray("odd_height", tsv(raw("NANAB", 880, 1480, height=41)))
    tray("tesseract_is_missing", None)
    tray("empty_table", "")
    tray("only_the_header", tsv())
    tray("blank_lines_and_windows_line_ends", tsv(label("PINAP", 0, 0)).replace("\n", "\r\n") + "\r\n\r\n")
    tray("no_end_of_line", tsv(label("PINAP", 0, 0)).rstrip("\n"))
    tray("a_line_of_spaces", tsv(label("PINAP", 0, 0)) + "   \n" + "\t\n")
    tray("more_columns_than_the_header", tsv(label("PINAP", 0, 0)).replace("\n5\t", "\n5\t7\t", 1).rstrip("\n") + "\textra\n")
    tray("fewer_columns", "level\tpage_num\n5\t1\n")
    tray("columns_in_another_order", "conf\ttext\tleft\ttop\twidth\theight\n90\tPINAP\t266\t60\t120\t40\n")
    tray("no_column_left", "conf\ttext\twidth\ttop\theight\n90\tPINAP\t120\t60\t40\n")
    tray("no_column_text", "conf\tleft\twidth\ttop\theight\n90\t266\t120\t60\t40\n")
    tray("no_column_conf", "text\tleft\twidth\ttop\theight\nPINAP\t266\t120\t60\t40\n")
    tray("a_row_that_is_too_short", "conf\ttext\tleft\ttop\twidth\theight\n90\tPINAP\n")
    tray("the_row_too_short_for_the_top", "conf\ttext\tleft\twidth\theight\ttop\n90\tPINAP\t266\t120\t40\n")
    tray("a_number_that_is_none", "conf\ttext\tleft\ttop\twidth\theight\n90\tPINAP\t266.5\t60\t120\t40\n")
    tray("a_width_that_is_none", "conf\ttext\tleft\ttop\twidth\theight\n90\tPINAP\t266\t60\twide\t40\n")
    tray("negative_left", tsv(("PINAP", -100, 60, 120, 40, "90")))
    tray("the_quote_stays_a_quote", tsv(label('"', 0, 0), label('"PINAP"', 1, 0)))
    tray("words_that_are_left_out_do_not_make_a_cell", tsv(label("PINAP", 0, 0, conf="10"), label("RAZZ", 1, 0)))
    add("tray_labels_takes_all_of_the_picture_from_row_1380", [call("tray_labels", img=0)], [frame([PLAIN, ["rect", 0, 1379, 1768, 1, [255, 255, 255]]])],
        tables=[tsv(label("PINAP", 0, 0))])

    # ---- pick_berry(): the first berry of the order that the tray has (never a Silver Pinap or a Golden Razz)
    def pick(name, table, **spec):
        add("pick_berry_%s" % name, [call("pick_berry", img=0)], [pl], tables=[table], **spec)

    pick("pinap_first", tsv(label("RAZZ BERRY", 1, 0), label("PINAP BERRY", 2, 1), label("NANAB BERRY", 0, 0)))
    pick("razz_when_there_is_no_pinap", tsv(label("RAZZ BERRY", 1, 0), label("NANAB BERRY", 0, 0)))
    pick("nanab_last", tsv(label("NANAB BERRY", 0, 0), label("WEPAR BERRY", 1, 0)))
    pick("nothing_that_is_wanted", tsv(label("WEPAR BERRY", 1, 0), label("GOLDEN RAZZ BERRY", 0, 0)))
    pick("silver_pinap_is_not_taken", tsv(label("SILVER PINAP BERRY", 0, 0)))
    pick("silver_pinap_then_razz", tsv(label("SILVER PINAP BERRY", 0, 0), label("RAZZ BERRY", 1, 0)))
    pick("silver_pinap_and_pinap", tsv(label("SILVER PINAP BERRY", 0, 0), label("PINAP BERRY", 1, 1)))
    pick("silver_in_another_cell", tsv(label("SILVER", 0, 0), label("PINAP BERRY", 1, 0)))
    pick("golden_razz_is_not_taken", tsv(label("GOLDEN RAZZ BERRY", 0, 0)))
    pick("golden_razz_and_nanab", tsv(label("GOLDEN RAZZ BERRY", 0, 0), label("NANAB BERRY", 2, 0)))
    pick("gold_alone_is_enough", tsv(label("GOLD RAZZ", 0, 0)))
    pick("the_first_cell_wins", tsv(label("PINAP BERRY", 2, 1), label("PINAP BERRY", 0, 0)))
    pick("the_first_cell_wins_the_other_way", tsv(label("PINAP BERRY", 0, 0), label("PINAP BERRY", 2, 1)))
    pick("a_part_of_a_name", tsv(label("PINAPPLE", 0, 0)))
    for r in range(2):
        for c in range(3):
            pick("the_icon_of_row%d_col%d" % (r, c), tsv(label("NANAB BERRY", c, r)))
    pick("the_tray_is_empty", tsv())
    pick("no_tesseract", None)
    pick("only_razz_is_wanted", tsv(label("PINAP BERRY", 0, 0), label("RAZZ BERRY", 1, 0)), berries=["razz"])
    pick("the_order_of_the_person", tsv(label("PINAP BERRY", 0, 0), label("RAZZ BERRY", 1, 0), label("NANAB BERRY", 2, 0)), berries=["nanab", "razz", "pinap"])
    pick("no_berries_are_wanted", tsv(label("PINAP BERRY", 0, 0)), berries=[])
    pick("a_berry_that_does_not_exist", tsv(label("PINAP BERRY", 0, 0)), berries=["golden"])
    pick("a_berry_that_does_not_exist_after_one_that_is_there", tsv(label("PINAP BERRY", 0, 0)), berries=["pinap", "wepar"])
    pick("a_berry_that_does_not_exist_after_one_that_is_not", tsv(label("RAZZ BERRY", 0, 0)), berries=["pinap", "wepar"])
    pick("the_same_berry_twice", tsv(label("RAZZ BERRY", 1, 0)), berries=["razz", "razz"])
    pick("a_tray_that_is_a_mess", tsv(label("B", 0, 0), label("A", 1, 0), label("a", 2, 0), label("C", 0, 1), label("Z", 1, 1)))

    # ---- screen_kind() and fast_catch_leave(): BACK while the ball comes down, then a look at where we are
    def lines_of(*words, y=800):
        """OCR lines: a word is a text or (text, x, y); every word is its own line."""
        out = []
        for w in words:
            text, x, wy = (w, 884, y) if isinstance(w, str) else w
            out.append([text, x, wy, [[text.split()[0] if text.split() else text, x, wy]] if " " not in text else [[t, x + 10 * i, wy] for i, t in enumerate(text.split())]])
        return out

    def leave(name, lines, ago=2.0, xy=(884, 900), shots=None, **spec):
        frames = [ms if lines is None else frame(lines=lines, screen=("encounterScreen", 0.9))]
        add("leave_%s" % name, [call("fast_catch_leave", ago=ago)], frames, shots=[0],
            init={"enc_xy": {"xy": None if xy is None else list(xy)}, "enc": {"throws": 1}}, **spec)

    leave("no_position_is_known", None, xy=None)
    leave("no_position_and_late", None, xy=None, ago=9.0)
    for ago in (4.9, 4.99, 5.0, 5.01, 5.5, 9.0):
        leave("late_%s" % str(ago).replace(".", "_"), None, ago=ago)
    for ago in (0.0, 0.5, 1.0, 1.19, 1.2, 1.21, 2.0):
        leave("early_%s" % str(ago).replace(".", "_"), None, ago=ago, shot_seconds=0.1)
    add("leave_early_exactly_1_2", [call("fast_catch_leave", ago=1.2, advance=-1000.0)], [ms], shots=[0], init={"enc_xy": {"xy": [884, 900]}, "enc": {"throws": 1}})
    add("leave_late_exactly_5_0_from_the_start_of_the_day", [call("fast_catch_leave", ago=5.0, advance=-1000.0)], [ms], shots=[0],
        init={"enc_xy": {"xy": [884, 900]}, "enc": {"throws": 1}})
    leave("the_map_is_there", None)
    leave("the_map_is_there_and_it_took_time", None, shot_seconds=0.4)
    for exit_lines, kind in (([["DO YOU WANT TO EXIT POKEMON GO?", 884, 900, [["DO", 700, 900], ["EXIT", 884, 900]]],
                               ["CANCEL", 600, 1100, [["CANCEL", 600, 1100]]], ["OK", 1100, 1100, [["OK", 1100, 1100]]]], "exit_with_cancel"),
                             ([["EXIT POKEMON GO", 884, 900, [["EXIT", 884, 900], ["POKEMON", 1000, 900]]], ["NO", 600, 1100, [["NO", 600, 1100]]]], "exit_without_cancel_word"),
                             ([["EXIT", 884, 900, [["EXIT", 884, 900]]], ["CANCEL", 600, 1100, [["CANC", 600, 1100]]]], "exit_cancel_in_the_text_only"),
                             ([["EXIT CANCEL", 884, 900, [["EXIT", 800, 900], ["CANCE1", 950, 900]]]], "exit_cancel_misread"),
                             ([["EXIT CANCEL", 884, 900, [["EXIT", 800, 900], ["CANAL", 950, 900]]]], "exit_cancel_not_like"),
                             ([["EXIT CANCEL", 884, 900, [["EXIT", 800, 900], ["CANCEL", 950, 900]]], ["CANCEL", 600, 1100, [["CANCEL", 600, 1100]]]], "exit_two_cancels")):
        leave(kind, exit_lines)
    leave("exit_that_is_cancelled_took_time", [["EXIT POK", 884, 900, [["EXIT", 884, 900]]]], shot_seconds=0.3)
    for name, lines in (("nothing_is_read", []), ("the_text_is_above_row_100", [["EXIT CANCEL", 884, 99, [["EXIT", 884, 99]]]]),
                        ("the_text_is_at_row_100", [["EXIT CANCEL", 884, 100, [["EXIT", 884, 100]]]]),
                        ("exit_alone", [["EXIT", 884, 900, [["EXIT", 884, 900]]]]),
                        ("pok_alone", [["POK", 884, 900, [["POK", 884, 900]]]]),
                        ("discard", [["DISCARD 5 POTION?", 884, 900, [["DISCARD", 800, 900], ["5", 900, 900], ["POTION?", 1000, 900]]]]),
                        ("yes_no_question", [["YES", 600, 1200, [["YES", 600, 1200]]], ["NO", 1100, 1200, [["NO", 1100, 1200]]], ["REALLY?", 884, 900, [["REALLY?", 884, 900]]]]),
                        ("yes_no_no_question_mark", [["YES", 600, 1200, [["YES", 600, 1200]]], ["NO", 1100, 1200, [["NO", 1100, 1200]]]]),
                        ("yes_only", [["YES ?", 600, 1200, [["YES", 600, 1200], ["?", 700, 1200]]]]),
                        ("no_only", [["NO ?", 600, 1200, [["NO", 600, 1200], ["?", 700, 1200]]]]),
                        ("yes_no_inside_words", [["YESTERDAY NOW ?", 600, 1200, [["YESTERDAY", 600, 1200], ["NOW", 800, 1200], ["?", 900, 1200]]]]),
                        ("bag_title", [["ITEMS", 884, 200, [["ITEMS", 884, 200]]]]),
                        ("bag_title_misread", [["ITEM5", 884, 200, [["ITEM5", 884, 200]]]]),
                        ("bag_title_far_left_553", [["ITEMS", 553, 200, [["ITEMS", 553, 200]]]]),
                        ("bag_title_far_left_554", [["ITEMS", 554, 200, [["ITEMS", 554, 200]]]]),
                        ("bag_title_far_right_1213", [["ITEMS", 1213, 200, [["ITEMS", 1213, 200]]]]),
                        ("bag_title_far_right_1214", [["ITEMS", 1214, 200, [["ITEMS", 1214, 200]]]]),
                        ("bag_title_low_449", [["ITEMS", 884, 449, [["ITEMS", 884, 449]]]]),
                        ("bag_title_low_450", [["ITEMS", 884, 450, [["ITEMS", 884, 450]]]]),
                        ("bag_count", [["12/350", 1500, 200, [["12/350", 1500, 200]]]]),
                        ("bag_count_small", [["1/2", 1500, 200, [["1/2", 1500, 200]]]]),
                        ("bag_count_four_digits", [["1234/5678", 1500, 200, [["1234/5678", 1500, 200]]]]),
                        ("bag_count_five_digits", [["12345/1", 1500, 200, [["12345/1", 1500, 200]]]]),
                        ("bag_count_five_digits_after", [["1/12345", 1500, 200, [["1/12345", 1500, 200]]]]),
                        ("bag_count_with_text", [["A12/350", 1500, 200, [["A12/350", 1500, 200]]]]),
                        ("bag_count_low", [["12/350", 1500, 450, [["12/350", 1500, 450]]]]),
                        ("bag_count_just_high_enough", [["12/350", 1500, 449, [["12/350", 1500, 449]]]]),
                        ("bag_count_no_digits", [["/", 1500, 200, [["/", 1500, 200]]]]),
                        ("menu", [["ITEMS", 1200, 1500, [["ITEMS", 1200, 1500]]], ["POKEMON", 400, 1500, [["POKEMON", 400, 1500]]]]),
                        ("menu_misread", [["ITEM5", 1200, 1500, [["ITEM5", 1200, 1500]]], ["POKEMON", 400, 1500, [["POKEMON", 400, 1500]]]]),
                        ("menu_pokemon_misread", [["ITEMS", 1200, 1500, [["ITEMS", 1200, 1500]]], ["POKEM0N", 400, 1500, [["POKEM0N", 400, 1500]]]]),
                        ("menu_without_pokemon", [["ITEMS", 1200, 1500, [["ITEMS", 1200, 1500]]]]),
                        ("menu_items_too_high_1250", [["ITEMS", 1200, 1250, [["ITEMS", 1200, 1250]]], ["POKEMON", 400, 1250, [["POKEMON", 400, 1250]]]]),
                        ("menu_items_1251", [["ITEMS", 1200, 1251, [["ITEMS", 1200, 1251]]], ["POKEMON", 400, 1251, [["POKEMON", 400, 1251]]]]),
                        ("menu_items_1699", [["ITEMS", 1200, 1699, [["ITEMS", 1200, 1699]]], ["POKEMON", 400, 1699, [["POKEMON", 400, 1699]]]]),
                        ("menu_items_too_low_1700", [["ITEMS", 1200, 1700, [["ITEMS", 1200, 1700]]], ["POKEMON", 400, 1700, [["POKEMON", 400, 1700]]]]),
                        ("menu_items_on_the_left_884", [["ITEMS", 884, 1500, [["ITEMS", 884, 1500]]], ["POKEMON", 400, 1500, [["POKEMON", 400, 1500]]]]),
                        ("menu_items_on_the_right_885", [["ITEMS", 885, 1500, [["ITEMS", 885, 1500]]], ["POKEMON", 400, 1500, [["POKEMON", 400, 1500]]]]),
                        ("menu_pokemon_79_higher", [["ITEMS", 1200, 1500, [["ITEMS", 1200, 1500]]], ["POKEMON", 400, 1421, [["POKEMON", 400, 1421]]]]),
                        ("menu_pokemon_80_higher", [["ITEMS", 1200, 1500, [["ITEMS", 1200, 1500]]], ["POKEMON", 400, 1420, [["POKEMON", 400, 1420]]]]),
                        ("menu_pokemon_79_lower", [["ITEMS", 1200, 1500, [["ITEMS", 1200, 1500]]], ["POKEMON", 400, 1579, [["POKEMON", 400, 1579]]]]),
                        ("menu_pokemon_80_lower", [["ITEMS", 1200, 1500, [["ITEMS", 1200, 1500]]], ["POKEMON", 400, 1580, [["POKEMON", 400, 1580]]]]),
                        ("menu_pokemon_at_884", [["ITEMS", 1200, 1500, [["ITEMS", 1200, 1500]]], ["POKEMON", 884, 1500, [["POKEMON", 884, 1500]]]]),
                        ("menu_pokemon_at_883", [["ITEMS", 1200, 1500, [["ITEMS", 1200, 1500]]], ["POKEMON", 883, 1500, [["POKEMON", 883, 1500]]]]),
                        ("bag_title_a_word_that_is_less_like_items", [["IMS", 884, 200, [["IMS", 884, 200]]]]),
                        ("menu_a_word_that_is_less_like_items", [["IMS", 1200, 1500, [["IMS", 1200, 1500]]], ["POKEMON", 400, 1500, [["POKEMON", 400, 1500]]]]),
                        ("menu_a_word_that_is_less_like_pokemon", [["ITEMS", 1200, 1500, [["ITEMS", 1200, 1500]]], ["POKN", 400, 1500, [["POKN", 400, 1500]]]]),
                        ("menu_the_second_items_counts", [["ITEMS", 400, 1500, [["ITEMS", 400, 1500]]], ["ITEMS", 1200, 1500, [["ITEMS", 1200, 1500]]], ["POKEMON", 400, 1500, [["POKEMON", 400, 1500]]]]),
                        ("bag_before_menu", [["ITEMS", 884, 200, [["ITEMS", 884, 200]]], ["ITEMS", 1200, 1500, [["ITEMS", 1200, 1500]]], ["POKEMON", 400, 1500, [["POKEMON", 400, 1500]]]]),
                        ("exit_before_bag", [["EXIT CANCEL", 884, 800, [["EXIT", 884, 800]]], ["ITEMS", 884, 200, [["ITEMS", 884, 200]]]]),
                        ("discard_before_bag", [["DISCARD", 884, 800, [["DISCARD", 884, 800]]], ["ITEMS", 884, 200, [["ITEMS", 884, 200]]]]),
                        ("a_lot_of_words", [["WORD%d" % i, 100 + i, 800 + i, [["WORD%d" % i, 100 + i, 800 + i]]] for i in range(30)]),
                        ("the_same_words_twice", [["HELLO WORLD", 884, 800, [["HELLO", 800, 800], ["WORLD", 900, 800]]], ["HELLO WORLD", 884, 900, [["HELLO", 800, 900], ["WORLD", 900, 900]]]])):
        leave("another_screen_%s" % name, lines)
    leave("another_screen_that_took_time", [["NEWS", 884, 800, [["NEWS", 884, 800]]]], shot_seconds=0.3)

    # ---- finish_catch(): the time is up, a catch that is going on is finished (at most 150 s)
    def finish(name, screens, steps=None, calls=None, **spec):
        spec.setdefault("shots", list(range(len(screens))))
        add("finish_%s" % name, calls or [call("finish_catch")], [frame(screen=sc) if isinstance(sc, tuple) else sc for sc in screens],
            steps=steps or [], **spec)

    finish("the_map_is_there", [("mapScreen", 0.9)])
    finish("the_map_is_there_with_a_beat", [("mapScreen", 0.9)], calls=[call("finish_catch", beat=True)])
    finish("no_catch_going_on", [("rewardScreen", 0.9)])
    finish("another_screen_with_a_low_score", [("pokemonScreen", 0.2)])
    finish("the_screenshot_fails", [frame()], shots=["error: no screen"])
    finish("the_classifier_fails", [frame(screen_error="model gone")])
    finish("the_classifier_fails_later", [("encounterScreen", 0.9), frame(screen_error="model gone")], steps=[{"seconds": 1.0, "wait": 2.0}])
    finish("a_catch_is_finished", [("encounterScreen", 0.9), ("encounterScreen", 0.9), ("mapScreen", 0.9)],
           steps=[{"seconds": 1.5, "wait": 2.0}, {"seconds": 2.5, "wait": 1.0}], screen_seconds=0.2, shot_seconds=0.3)
    finish("a_catch_is_finished_with_beats", [("encounterScreen", 0.9), ("encounterScreen", 0.9), ("mapScreen", 0.9)],
           steps=[{"seconds": 1.5, "wait": 2.0}, {"seconds": 2.5, "wait": 1.0}], calls=[call("finish_catch", beat=True)])
    finish("another_screen_while_the_catch_is_going_on", [("encounterScreen", 0.9), ("rewardScreen", 0.9), ("mapScreen", 0.9)],
           steps=[{"seconds": 0.5, "wait": 1.5}, {"seconds": 0.5, "wait": 1.5}])
    finish("a_screen_that_is_not_sure", [("encounterScreen", 0.1), ("mapScreen", 0.1)], steps=[{"seconds": 0.5, "wait": 1.0}])
    finish("a_step_fails", [("encounterScreen", 0.9), ("mapScreen", 0.9)], steps=[{"seconds": 0.5, "wait": None, "error": "the phone is gone"}])
    finish("a_step_fails_with_a_beat", [("encounterScreen", 0.9), ("mapScreen", 0.9)], steps=[{"seconds": 0.5, "wait": None, "error": "the phone is gone"}],
           calls=[call("finish_catch", beat=True)])
    finish("a_step_waits_for_ever", [("encounterScreen", 0.9)], steps=[{"seconds": 0.5, "wait": 1000.0}])
    finish("a_step_waits_exactly_until_the_end", [("encounterScreen", 0.9)], steps=[{"seconds": 0.0, "wait": 150.0}])
    finish("a_step_takes_all_the_time", [("encounterScreen", 0.9)], steps=[{"seconds": 150.0, "wait": 1.0}])
    finish("a_step_takes_longer_than_all_the_time", [("encounterScreen", 0.9)], steps=[{"seconds": 151.0, "wait": 1.0}])
    finish("a_step_takes_all_the_time_but_a_moment", [("encounterScreen", 0.9)], steps=[{"seconds": 149.9, "wait": 1.0}])
    finish("the_time_is_up_while_looking", [("encounterScreen", 0.9)], steps=[{"seconds": 0.0, "wait": 0.0}], screen_seconds=50.0)
    finish("short_waits", [("encounterScreen", 0.9)] * 4 + [("mapScreen", 0.9)], steps=[{"seconds": 0.0, "wait": 0.0}] * 4, calls=[call("finish_catch", beat=True)])
    finish("a_wait_of_nothing", [("encounterScreen", 0.9), ("mapScreen", 0.9)], steps=[{"seconds": 0.0, "wait": 0.0}])
    finish("a_negative_wait", [("encounterScreen", 0.9), ("mapScreen", 0.9)], steps=[{"seconds": 0.0, "wait": -3.0}])

    # the characters that repr() writes as an escape (the berry tray is logged as a list of texts)
    for name, word in (("control_1f", "PINAP\x1f"), ("delete", "PINAP\x7f"), ("c1_control", "PINAP\x9f"), ("no_break_space_inside", "PI NAP"),
                       ("soft_hyphen", "PI­NAP"), ("line_separator", "PI NAP"), ("unassigned", "PINAP͸"), ("private_use", "PINAP"),
                       ("tag_character", "PINAP\U000e0001"), ("noncharacter", "PINAP\U0010ffff"), ("emoji", "PINAP\U0001f600"), ("greek", "PINAPΩ"),
                       ("tab_inside_is_a_new_column", "PI\tNAP")):
        tray("text_%s" % name, tsv(label(word, 0, 0)), fn="pick_berry")

    # what str.strip() takes for white space (Python: the characters that are 'space', 'separator' or 'line end' to Unicode) and what it leaves
    for code in (0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x1b, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x21, 0x84, 0x85, 0x86, 0x9f, 0xa0, 0xa1, 0x167f, 0x1680, 0x1681,
                 0x1fff, 0x2000, 0x2005, 0x200a, 0x200b, 0x2027, 0x2028, 0x2029, 0x202a, 0x202e, 0x202f, 0x2030, 0x205e, 0x205f, 0x2060, 0x3000, 0x3001):
        tray("strip_%04x_at_the_end" % code, tsv(label("PINAP" + chr(code), 0, 0)), fn="pick_berry")
    for code in (0x1c, 0x1f, 0x85, 0xa0, 0x2003, 0x3000, 0x2060, 0x0e):
        tray("strip_%04x_at_the_start" % code, tsv(label(chr(code) + "PINAP", 0, 0)), fn="pick_berry")
    tray("strip_everything_but_the_word", tsv(label("\x1c\x1d 　\xa0PINAP \x85\t\x1f", 0, 0)), fn="pick_berry")
    tray("strip_a_word_of_white_space", tsv(label("\x1c　\xa0\x85", 0, 0)))

    # the look at the result that is made exactly 20 s after the throw: the window is over only after that
    for live in (False, True):
        t = START + 0.1                                       # (the first wait: 0.1 s, for a throw that was let go more than 1.9 s ago)
        pause = 0.05 if live else 0.3
        for _ in range(60):
            t += 0.5
            if t - START > 15:
                break
            t += pause
        ago = START - (t - 20.0)                              # (exact: both are near 1000)
        add("wait_the_window_ends_exactly_20_s_after_the_throw%s" % ("_live" if live else ""), [call("wait_for_result", ago=ago)], [fs],
            shots=[0], init={"enc": {"throws": 1}}, shot_seconds=0.5, live=live)

    # ---- do_encounter(): a Pokémon is on the catch screen
    def enc(name, frames, calls=None, **spec):
        add("encounter_%s" % name, calls or [call("do_encounter", img=0)], frames, **spec)

    def prepared(**more):
        """The ball and the berry are done: only the throwing is left."""
        init = {"enc": dict({"start": 5.0, "ball_set": True, "berry": True}, **more.pop("enc", {}))}
        init.update(more)
        return init

    stop = {"catch": False}                                   # (catching switched off in the web interface: one throw, then back to the step)
    # the storage is full: do not catch, run away
    full = {"storage_state": {"full": True}}
    enc("storage_full_and_only_spinning", [cs], init=full, wanted={"spin_only_when_full": True})
    enc("storage_full_and_the_daily_cycle", [cs], init=full, wanted={"daily_cycle": True})
    enc("storage_full_and_both", [cs], init=full, wanted={"spin_only_when_full": True, "daily_cycle": True})
    enc("storage_full_but_nobody_asked", [cs, cs], init=dict(full, **prepared()), wanted=stop, shots=[1])
    enc("storage_not_full_and_asked", [cs, cs], init=prepared(), wanted=dict(stop, spin_only_when_full=True, daily_cycle=True), shots=[1])
    enc("storage_full_and_the_ball_is_not_ready", [rs], init=dict(full, enc={"throws": 1}), wanted={"spin_only_when_full": True})
    enc("storage_full_and_the_ball_is_not_ready_and_nothing_else", [fs, fs], init=dict(full, enc={"throws": 1}), wanted={"spin_only_when_full": True}, shots=[1])

    # the ball is not at the bottom: the result screen, the ball that is coming back, or the end of the catch
    enc("result_screen_with_a_ball_thrown", [rs], init={"enc": {"throws": 2}}, screen_seconds=0.2)
    enc("result_screen_with_a_ball_thrown_and_counted", [rs], init={"enc": {"throws": 2, "caught": True}})
    enc("result_screen_that_is_the_catch_screen", [result_screen(screen=("encounterScreen", 0.9)), fs], init={"enc": {"throws": 2}}, shots=[1])
    enc("result_screen_that_is_the_catch_screen_but_not_sure", [result_screen(screen=("encounterScreen", 0.79))], init={"enc": {"throws": 2}})
    enc("result_screen_but_no_ball_was_thrown", [rs, fs], init={"enc": {"throws": 0}}, shots=[1])
    enc("the_ball_comes_back", [fs, cs], init={"enc": {"throws": 1}}, shots=[1], shot_seconds=0.25)
    enc("the_ball_comes_back_with_no_ball_thrown", [fs, cs], shots=[1])
    enc("the_catch_is_over_and_a_button_is_tapped", [fs, frame(buttons=[("clickable", 0.6, 884, 1900, 700, 150)], text="OK", screen=("mapScreen", 0.9))],
        init={"enc": {"throws": 3}}, shots=[1])
    enc("the_catch_is_over_and_a_button_is_tapped_but_nothing_was_thrown", [fs, frame(buttons=[("clickable", 0.6, 884, 1900, 700, 150)], text="OK")], shots=[1])
    enc("the_catch_is_over_and_a_battle_button_is_not_tapped", [fs, frame(buttons=[("clickable", 0.6, 884, 1900, 700, 150)], text="BATTLE")],
        init={"enc": {"throws": 1}}, shots=[1])
    enc("the_catch_is_over_and_the_screen_has_a_green_button", [fs, gs], init={"enc": {"throws": 1}}, shots=[1])
    enc("the_catch_is_over_and_the_screen_has_a_green_button_and_a_button", [fs, frame(TG.buttons_ops(berry=False, ball=False) + [["rect", 504, 1900, 760, 150, GREEN]],
        buttons=[("clickable", 0.6, 884, 1000, 700, 150)], text="OK")], init={"enc": {"throws": 1}}, shots=[1])
    enc("the_catch_is_over_and_nothing_can_be_tapped", [fs, fs], init={"enc": {"throws": 1}}, shots=[1])
    enc("the_catch_is_over_already_counted", [fs, fs], init={"enc": {"throws": 1, "caught": True}}, shots=[1])
    enc("the_second_look_fails", [fs, fs], init={"enc": {"throws": 1}}, shots=["error: no screen"])

    # a Pokémon that is met: the first look, the ball, the berry
    enc("a_new_encounter_opens", [cs], init=prepared(enc={"start": 0.0}), wanted=stop, shots=[0], advance=3.0)
    enc("an_encounter_goes_on", [cs], init=prepared(), wanted=stop, shots=[0])
    enc("an_encounter_that_started_at_time_zero_seconds", [cs], init=prepared(enc={"start": 0.0}), wanted=stop, shots=[0])
    for throws in (0, 1, 6, 7, 8, 9):
        enc("%d_balls_thrown" % throws, [cs, cs, cs], init=prepared(enc={"throws": throws}), wanted=stop, shots=[1, 2])
    enc("8_balls_thrown_and_caught", [cs], init=prepared(enc={"throws": 8, "caught": True}), wanted=stop)
    enc("8_balls_thrown_and_the_map_knows_where", [cs], init=prepared(enc={"throws": 8}, enc_xy={"xy": [800, 900]}, throw_info={"hit": True}))
    enc("8_balls_thrown_the_first_ball_of_the_catch", [cs], init=prepared(enc={"throws": 8, "start": 0.0}))
    for ball in ("poke", "great", "ultra", "", "master"):
        enc("the_ball_%s" % (ball or "of_nobody"), [cs, cs], init={"enc": {"start": 5.0, "berry": True}}, ball=ball, wanted=stop, shots=[1], advance=1.0)
    enc("the_ball_is_set_already", [cs, cs], init=prepared(), ball="great", wanted=stop, shots=[1])
    enc("the_ball_and_the_berry_are_new", [cs, pl, cs], init={"enc": {"start": 5.0}}, wanted=stop, shots=[1, 2],
        tables=[tsv(label("PINAP BERRY", 1, 0))])

    # the berry: the tray is read and the berry is fed, or the tray is closed
    def berry(name, table, frames_after=(), **spec):
        spec.setdefault("wanted", stop)
        spec.setdefault("shots", [1, 2])
        enc("berry_%s" % name, [cs, pl, cs] + list(frames_after), init={"enc": {"start": 5.0, "ball_set": True}}, tables=[table], **spec)

    berry("pinap", tsv(label("PINAP BERRY", 1, 0), label("RAZZ BERRY", 0, 0)))
    berry("razz", tsv(label("RAZZ BERRY", 2, 1)))
    berry("razz_in_the_second_row", tsv(label("RAZZ BERRY", 0, 1), label("NANAB BERRY", 0, 0)))
    berry("the_person_wants_razz_first", tsv(label("PINAP BERRY", 1, 0), label("RAZZ BERRY", 0, 0)), berries=["razz", "pinap"])
    berry("nothing_that_is_wanted", tsv(label("SILVER PINAP BERRY", 1, 0), label("GOLDEN RAZZ BERRY", 0, 0)))
    berry("an_empty_tray", tsv())
    berry("tesseract_is_missing", None)
    berry("a_berry_that_does_not_exist", tsv(label("PINAP BERRY", 1, 0)), berries=["golden"])
    berry("no_berries_wanted", tsv(label("PINAP BERRY", 1, 0)), berries=[])
    berry("the_tray_cannot_be_photographed", tsv(label("PINAP BERRY", 1, 0)), shots=["error: no screen"])
    berry("the_tray_took_time", tsv(label("PINAP BERRY", 1, 0)), shot_seconds=1.5)
    enc("berry_fed_already", [cs, cs], init=prepared(), wanted=stop, shots=[1])
    enc("berry_is_tried_once", [cs, pl, cs, pl, cs], init={"enc": {"start": 5.0, "ball_set": True}}, wanted=stop, shots=[1, 2],
        calls=[call("do_encounter", img=0), call("do_encounter", img=0)], tables=[tsv()])

    # throwing: the ball that is thrown, the wait for the result, the fast catch
    def throwing(name, frames, **spec):
        spec.setdefault("init", prepared())
        spec.setdefault("shots", [1])
        enc("throwing_%s" % name, [cs] + frames, **spec)

    throwing("one_ball_and_it_comes_back", [cs], wanted=stop)
    throwing("one_ball_and_it_comes_back_after_a_while", [fs, fs, cs], wanted=stop, shots=[1, 2, 3], shot_seconds=0.25)
    throwing("one_ball_and_a_catch", [rs], wanted=stop)
    throwing("one_ball_that_took_long", [cs], wanted=stop, throws=[{"seconds": 2.5, "hit": False, "ago": 0.5}])
    throwing("one_ball_that_was_thrown_long_ago", [cs], wanted=stop, throws=[{"seconds": 2.5, "hit": False, "ago": 2.4}])
    throwing("two_balls_and_a_catch", [fs, cs, fs, rs], shots=[1, 2, 3, 4], shot_seconds=0.25)
    throwing("three_misses_and_a_catch", [cs, cs, cs, rs], shots=[1, 2, 3, 4])
    throwing("the_last_ball_that_may_be_thrown", [cs], init=prepared(enc={"throws": 7}), shots=[1])
    throwing("the_ball_comes_back_after_the_last_throw", [cs, cs], init=prepared(enc={"throws": 7}), shots=[1, 2])
    throwing("another_screen_comes", [frame(screen=("pokemonScreen", 0.9))])
    throwing("another_screen_comes_and_the_tap_was_long_ago", [frame(screen=("pokemonScreen", 0.9))], init=prepared(enc={"t_tap": 1.0}))
    for name, t_tap in (("a_second_ago", 1001.0), ("a_little_less_than_a_second_ago", 1001.0625), ("three_quarters_of_a_second_ago", 1001.25),
                        ("half_a_second_ago", 1001.5), ("just_now", 1002.0), ("a_bit_more_than_a_second_ago", 1000.9375)):
        throwing("another_screen_comes_and_the_tap_was_%s" % name, [frame(screen=("pokemonScreen", 0.9))], init=prepared(enc={"t_tap": t_tap}))
    throwing("nothing_happens_for_20_s", [fs], shot_seconds=2.0)
    throwing("the_result_screen_comes", [fs, rs], shots=[1, 2], shot_seconds=0.5)
    throwing("the_result_screen_and_the_tap_is_new", [rs])
    throwing("the_screenshot_fails", [fs], shots=["error: no screen"])
    throwing("the_throw_fails_is_not_modelled", [cs], wanted=stop, throws=[{"seconds": 0.0, "hit": None}])
    throwing("hit_none", [cs], wanted=stop, throws=[{"seconds": 1.0, "hit": None}])
    throwing("hit_false", [cs], wanted=stop, throws=[{"seconds": 1.0, "hit": False}], settings={"fast_catch": True}, init=prepared(enc_xy={"xy": [884, 900]}))
    throwing("the_throws_hit_in_turn", [cs, cs, rs], throws=[{"seconds": 1.0, "hit": False}, {"seconds": 1.0, "hit": None}, {"seconds": 1.0, "hit": False}],
             shots=[1, 2, 3])

    # the fast catch: a hit, BACK, and the map
    def fast(name, frames, **spec):
        spec.setdefault("init", prepared(enc_xy={"xy": [884, 900]}))
        spec.setdefault("shots", [1])
        spec.setdefault("settings", {"fast_catch": True})
        spec.setdefault("throws", [{"seconds": 1.0, "hit": True}])
        enc("fast_%s" % name, [cs] + frames, **spec)

    fast("the_map_is_there", [ms])
    fast("the_map_is_there_the_catch_is_not_wanted", [ms], wanted=stop)
    fast("the_option_is_off", [cs], settings={"fast_catch": False}, wanted=stop)
    fast("the_option_is_not_set", [cs], settings={}, wanted=stop)
    fast("the_option_is_off_and_there_is_a_hit", [cs, rs], settings={"fast_catch": False}, shots=[1, 2])
    fast("the_hit_is_not_clear", [cs], throws=[{"seconds": 1.0, "hit": None}], wanted=stop)
    fast("the_ball_missed", [cs], throws=[{"seconds": 1.0, "hit": False}], wanted=stop)
    fast("the_position_is_not_known", [cs], init=prepared(), wanted=stop)
    fast("the_option_rests_until_later", [cs], init=prepared(enc_xy={"xy": [884, 900]}, fast_state={"off_until": 1001.25}), wanted=stop)
    fast("the_option_rests_until_now", [ms], init=prepared(enc_xy={"xy": [884, 900]}, fast_state={"off_until": 1001.0}))
    fast("the_option_rested_until_a_while_ago", [ms], init=prepared(enc_xy={"xy": [884, 900]}, fast_state={"off_until": 900.0}))
    fast("the_ball_was_let_go_long_ago", [cs], throws=[{"seconds": 1.0, "hit": True, "ago": 6.0}], wanted=stop)
    fast("the_ball_was_let_go_long_ago_and_it_comes_back", [cs], throws=[{"seconds": 1.0, "hit": True, "ago": 6.0}], wanted=stop)
    fast("the_exit_question_is_answered", [frame([PLAIN], lines=[["EXIT POKEMON GO CANCEL", 884, 900, [["EXIT", 700, 900], ["CANCEL", 884, 1100]]]], screen=("pokemonScreen", 0.9))])
    fast("another_screen_after_back", [frame([PLAIN], lines=[["NEWS", 884, 900, [["NEWS", 884, 900]]]], screen=("pokemonScreen", 0.9)), cs],
         shots=[1, 2], wanted=stop)
    fast("another_screen_after_back_and_the_ball_comes_back", [frame([PLAIN], lines=[["ITEMS", 884, 300, [["ITEMS", 884, 300]]]], screen=("pokemonScreen", 0.9)), cs],
         shots=[1, 2], wanted=stop)
    fast("another_screen_after_back_the_result_is_there", [frame([PLAIN], lines=[["ITEMS", 884, 300, [["ITEMS", 884, 300]]]], screen=("pokemonScreen", 0.9)), rs],
         shots=[1, 2])
    fast("the_screenshot_after_back_fails", [ms], shots=["error: no screen"])
    fast("a_second_hit", [ms], throws=[{"seconds": 1.0, "hit": True}, {"seconds": 1.0, "hit": True}])

    return out


# ---------------------------------------------------------------------- the file

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
