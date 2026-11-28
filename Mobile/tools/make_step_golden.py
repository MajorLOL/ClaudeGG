#!/usr/bin/env python3
"""Makes tests/fixtures/step_golden.json.qz (JSON, packed the way qCompress() of Qt does: the length, then zlib): what gamebot.py does in one
STEP of the bot - step(), the choice of what to do with the screen that is on the phone: is the phone too hot, is the screen drawn right, is the
phone awake, the screenshot (or the one that was handed on), which screen it is, away from the map for too long, the same screen again and again,
a tap that did nothing, Team Rocket, the layout check and the quests of a first look at the map, and then the map, the stop, the catch screen,
an egg, the summary, a news card, a group question, the safety notice, a full storage, the passenger pop-up, a result screen - with heat_wait(),
leave_group_screen(), is_rocket_text(), storage_full() and pause_catching() that it uses (the file that the C++ port,
SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoStep.cpp, is tested against).

    python3 tools/make_step_golden.py            writes the file
    python3 tools/make_step_golden.py --check    says whether the file is what the code does now (the stories stored in it are played again)

The file is a list of stories: a list of calls, each with the EVENTS that it makes, with the time of a fake clock (it starts at 1000.0 and only moves
with the screenshots, the sleeps and what the parts that are not here take).  The pictures are drawn on the canvas by the ops of
tools/make_throw_golden.py; the readers of pictures (on_map, find_green_button, find_pill_button) are the real ones.  What the code is GIVEN:
    shot          a screenshot (which of the frames of the story, quick or real)
    screen        the screen classifier looked at a frame and said this (its name and certainty)
    buttons       the detector of buttons looked at a frame and found these
    ocr_text, ocr the text readers read the text (or the lines, with the places of the words) in a strip of a frame
    day_count     the text of the counters of the day
    heat          the temperatures that were read (the phone's battery, the Pi)
    power         what Android says of the power state of the phone
    unlock_game   the picture that is left when a dimmed game was woken (the same one, or another)
    layout_adapt, layout_watch, layout_verify, quests_due, claim_quests, rocket_battle, do_map, do_pokestop, do_encounter
                  the parts that are not in this part: what they said (or that they failed) and how long they took
  what it DOES (the C++ port has to do the same, in this order):
    tap, back, sleep, log, save (a picture that is kept), swipe_async (the swipe of a camera step that was armed), wakeup (KEYCODE_WAKEUP),
    unlock, wait_unsupported, restart_game, resume_catch_later (catching is switched on again after this long), then at the end of every call:
    result (what it returned) or raised, and state (what it remembers)."""
import argparse
import copy
import json
import os
import struct
import sys
import threading
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_throw_golden as TG  # noqa: E402
import make_catch_golden as CG  # noqa: E402  (the pictures, the fake classifier and detector of buttons, the frames)
from make_start_golden import START, Clock, Rec, mean  # noqa: E402
import gamebot as G  # noqa: E402
import spin_stop as S  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "tests", "fixtures", "step_golden.json.qz")
W, H = TG.W, TG.H


# ---------------------------------------------------------------------- what the code remembers

STATE = ("enc", "enc_xy", "last_tap", "near_state", "rotation", "away", "same_screen", "health", "heat", "perf")
_defaults = {name: json.loads(json.dumps(getattr(G, name))) for name in STATE}
_defaults["rotation"]["armed"] = None
_cooldown = list(G.cooldown)
_catch = G.CATCH
BASE = {"health": {"ok": True, "t": START}}                    # (the phone was looked at a moment ago)

jsonable = CG.jsonable


def snapshot(world):
    state = {name: jsonable(getattr(G, name)) for name in STATE}
    state["perf"] = {k: jsonable(G.perf.get(k)) for k in ("shot", "t_step", "total")}
    state["cooldown"] = jsonable([list(c) for c in G.cooldown])
    img = G.handoff["img"]
    state["handoff"] = {"img": None if img is None else world.index_of(img), "t": jsonable(G.handoff["t"])}
    state["catch"] = bool(G.CATCH)
    state["layout"] = G.layout["state"]
    state["screen_ok"] = bool(S.screen["ok"])
    return state


def restore(init, world=None):
    for name in STATE:
        target = getattr(G, name)
        target.clear()
        target.update(copy.deepcopy(_defaults[name]))
    G.cooldown[:] = _cooldown
    G.handoff.update(img=None, t=0.0)
    G.CATCH = _catch
    G.layout["state"] = "confirmed"
    S.screen["ok"] = True
    G.perf.pop("t_step", None)
    for name, value in dict(BASE, **init).items():
        apply(name, value, world)


def apply(name, value, world=None):
    if name in STATE:
        getattr(G, name).update(copy.deepcopy(value))
    elif name == "cooldown":
        G.cooldown[:] = [tuple(c) for c in value]
    elif name == "handoff":
        G.handoff.update(img=None if value["img"] is None else world.picture(value["img"]), t=value["t"])
    elif name == "catch":
        G.CATCH = bool(value)
    elif name == "layout":
        G.layout["state"] = value
    elif name == "screen_ok":
        S.screen["ok"] = bool(value)
    else:
        raise KeyError(name)


# ---------------------------------------------------------------------- the fake phone

def frame(ops=None, screen=None, buttons=None, lines=None, text=None, texts=None, screen_error=None):
    f = CG.frame(ops, screen=screen, buttons=buttons, lines=lines, text=text, screen_error=screen_error)
    if texts is not None:
        f["texts"] = {str(k): v for k, v in texts.items()}       # the text of the strips that begin at this row
    return f


def record(spec):
    """Plays one story on the fake phone; returns the list of events."""
    Clock.t = START
    rec = Rec()
    Clock.rec = rec
    world = CG.World(spec)
    saved_g = {n: getattr(G, n) for n in ("time", "log", "setting", "wanted", "count", "save_async", "ocr_text", "ocr_lines", "read_heat", "layout_adapt",
                                          "layout_watch", "layout_verify", "quests_due", "claim_quests", "rocket_battle", "do_map", "do_pokestop",
                                          "do_encounter", "CATCH")}
    saved_s = {n: getattr(S, n) for n in ("time", "log", "tap", "back", "quick_screenshot", "screenshot", "wait_unsupported", "unlock", "unlock_game",
                                          "adb", "restart_game", "swipe_async")}
    saved_timer = threading.Timer
    saved_layout_state, saved_ok = G.layout["state"], S.screen["ok"]
    try:
        restore(spec.get("init", {}), world)
        G.time = S.time = Clock
        G.log = S.log = lambda text: rec.add("log", text)
        settings = {"heat_pause": False}
        settings.update(spec.get("settings", {}))
        G.setting = lambda key, default: settings.get(key, default)
        G.wanted = lambda key: True
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
        S.swipe_async = lambda x1, y1, x2, y2, ms=300: rec.add("swipe_async", x1, y1, x2, y2, ms)
        S.restart_game = lambda: rec.add("restart_game")

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
                if on_grab is not None:
                    on_grab()
                return world.picture(index)
            take.live = False
            return take
        S.quick_screenshot = make_shot("quick")
        S.screenshot = make_shot("real")

        def ocr_text(img, y0, y1):
            crop = img[y0:y1]
            frame_ = world.frame(img)
            text = " ".join(frame_.get("texts", {}).get(str(y0), frame_.get("text", "")).upper().split())     # (as the real ocr_text() gives it)
            rec.add("ocr_text", crop.shape[0], crop.shape[1], mean(crop), text)
            return text
        G.ocr_text = ocr_text

        def ocr_lines(img, y0=0, y1=None, scale=1.0):
            lines = [ln for ln in world.frame(img).get("lines", []) if ln[2] >= y0]
            rec.add("ocr", img.shape[0], img.shape[1], y0, y1, scale, mean(img), lines)
            return lines
        G.ocr_lines = ocr_lines

        class Script:
            """What the parts that are not here answer: the n-th call gets the n-th answer of the list (the last one again when there are fewer)."""
            def __init__(self, key):
                self.key, self.n = key, 0

            def next(self, default=None):
                items = spec.get(self.key, [])
                one = items[min(self.n, len(items) - 1)] if items else default
                self.n += 1
                return one
        scripts = {k: Script(k) for k in ("heats", "powers", "unlocks", "adapts", "watches", "verifies", "rockets", "due", "claims", "maps", "stops",
                                          "encounters")}

        def took(one):
            Clock.t += one.get("seconds", 0.0)

        def read_heat():
            one = scripts["heats"].next([None, None])
            rec.add("heat", one[0], one[1])
            return one[0], one[1]
        G.read_heat = read_heat

        def adb(*args):
            if args == ("shell", "dumpsys", "power"):
                text = scripts["powers"].next("mWakefulness=Awake")
                rec.add("power", text)
                return text
            if args == ("shell", "input", "keyevent", "KEYCODE_WAKEUP"):
                rec.add("wakeup")
                return ""
            raise ValueError(args)
        S.adb = adb

        def unlock():
            rec.add("unlock")
            return False
        S.unlock = unlock

        def unlock_game(img=None):
            one = scripts["unlocks"].next({})
            took(one)
            out = img if one.get("img") is None else world.picture(one["img"])
            rec.add("unlock_game", world.index_of(img), world.index_of(out))
            return out
        S.unlock_game = unlock_game

        def layout_event(kind, one, *rest):
            if "state" in one:
                G.layout["state"] = one["state"]
            if "ok" in one:
                S.screen["ok"] = bool(one["ok"])
            rec.add(kind, *rest, G.layout["state"], bool(S.screen["ok"]))

        def layout_adapt(why):
            one = scripts["adapts"].next({"result": False})
            took(one)
            G.layout["state"] = one.get("state", G.layout["state"])
            S.screen["ok"] = bool(one.get("ok", S.screen["ok"]))
            rec.add("layout_adapt", why, bool(one["result"]), G.layout["state"], bool(S.screen["ok"]))
            return bool(one["result"])
        G.layout_adapt = layout_adapt

        def layout_watch():
            one = scripts["watches"].next({})
            took(one)
            layout_event("layout_watch", one)
        G.layout_watch = layout_watch

        def layout_verify(img):
            one = scripts["verifies"].next({})
            took(one)
            layout_event("layout_verify", one, world.index_of(img))
        G.layout_verify = layout_verify

        def wait_unsupported():
            rec.add("wait_unsupported")
        S.wait_unsupported = wait_unsupported

        def quests_due(img):
            one = scripts["due"].next({"result": False})
            took(one)
            rec.add("quests_due", world.index_of(img), bool(one["result"]))
            return bool(one["result"])
        G.quests_due = quests_due

        def claim_quests():
            one = scripts["claims"].next({"result": "claimed"})
            took(one)
            rec.add("claim_quests", one.get("result"), one.get("error"))
            if one.get("error"):
                raise RuntimeError(one["error"])
            return one["result"]
        G.claim_quests = claim_quests

        def rocket_battle(stop=None):
            one = scripts["rockets"].next({"result": "won"})
            took(one)
            rec.add("rocket_battle", one.get("result"), one.get("error"))
            if one.get("error"):
                raise RuntimeError(one["error"])
            return one["result"]
        G.rocket_battle = rocket_battle

        def part(kind, key):
            def go(brain, img):
                one = scripts[key].next({"wait": 1.0})
                took(one)
                rec.add(kind, world.index_of(img), one["wait"])
                return one["wait"]
            return go
        G.do_map = part("do_map", "maps")
        G.do_pokestop = part("do_pokestop", "stops")
        G.do_encounter = part("do_encounter", "encounters")

        class Timer:
            last = None

            def __init__(self, interval, function):
                self.interval, self.function = interval, function

            def start(self):
                Timer.last = self
                rec.add("resume_catch_later", self.interval)
        threading.Timer = Timer

        brain = CG.FakeBrain(world, rec, spec)

        for call in spec["calls"]:
            if "settings" in call:
                settings.update(call["settings"])
            if "advance" in call:
                Clock.t += call["advance"]
            for name, value in call.get("init", {}).items():
                apply(name, value, world)
            rec.add("call", call["fn"], call.get("img"), None)
            try:
                fn = call["fn"]
                img = world.picture(call["img"]) if "img" in call else None
                if fn == "step":
                    result = G.step(brain)
                elif fn == "heat_wait":
                    result = G.heat_wait()
                elif fn == "leave_group_screen":
                    result = G.leave_group_screen(img)
                elif fn == "is_rocket_text":
                    result = G.is_rocket_text(img)
                elif fn == "storage_full":
                    result = G.storage_full(img)
                elif fn == "pause_catching":
                    G.pause_catching()
                    result = None
                elif fn == "resume_catching":                 # the Timer of pause_catching() has run out
                    Timer.last.function()
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
        threading.Timer = saved_timer
        restore({})
        G.layout["state"], S.screen["ok"] = saved_layout_state, saved_ok
        G.perf.pop("t_step", None)


# ---------------------------------------------------------------------- the pictures

PLAIN = CG.PLAIN
PALE = [190, 252, 200]                                       # a green that the pill finder does not take (too bright) but the button finder does
PILL = ["rect", 504, 1900, 760, 150, CG.GREEN]


def screen_frame(name, score=0.95, **kw):
    return frame(screen=(name, score), **kw)


def map_frame(**kw):
    return CG.frame([PLAIN, ["rect", 860, 1920, 46, 20, [30, 30, 220]], ["rect", 860, 2020, 46, 30, [255, 255, 255]]], screen=kw.pop("screen", ("mapScreen", 0.95)),
                    **kw)


# ---------------------------------------------------------------------- the stories

def stories():
    out = []
    mp = map_frame()
    enc = CG.catch_screen()
    stop = screen_frame("pokestopScreen")

    def add(name, calls, frames, **spec):
        spec["settings"] = dict({"heat_pause": False}, **spec.get("settings", {}))     # (the story says it: the port asks the story for it too)
        spec.update(calls=calls, frames=frames)
        out.append({"id": name, "spec": spec})

    def call(fn, **kw):
        return dict({"fn": fn}, **kw)

    def step(**kw):
        return call("step", **kw)

    def other(name, score=0.9, **kw):
        return screen_frame(name, score, **kw)

    # ---- heat_wait(): the phone or the Pi is too hot: nothing is tapped until it is cool again
    hot = {"heat_pause": True}
    add("heat_off", [call("heat_wait")], [mp], settings={"heat_pause": False}, init={"heat": {"since": 900.0}})
    add("heat_cool", [call("heat_wait")], [mp], settings=hot, heats=[[35.0, 60.0]])
    add("heat_unknown", [call("heat_wait")], [mp], settings=hot, heats=[[None, None]])
    for name, phone, pi in (("phone_43", 43.0, 60.0), ("phone_42_9", 42.9, 60.0), ("pi_82", 35.0, 82.0), ("pi_81_9", 35.0, 81.9), ("both", 44.5, 85.25),
                            ("phone_only_known", 43.0, None), ("pi_only_known", None, 82.0)):
        add("heat_start_%s" % name, [call("heat_wait")], [mp], settings=hot, heats=[[phone, pi]])
    add("heat_not_looked_at_again_for_60_s", [call("heat_wait"), call("heat_wait", advance=59.9), call("heat_wait", advance=0.1)], [mp], settings=hot,
        heats=[[35.0, 60.0], [35.0, 60.0]])
    add("heat_hot_then_30_s_pauses", [call("heat_wait"), call("heat_wait", advance=29.9), call("heat_wait", advance=0.1)], [mp], settings=hot,
        heats=[[43.0, 60.0], [43.0, 60.0]])
    add("heat_cools_down", [call("heat_wait"), call("heat_wait", advance=30.0)], [mp], settings=hot, heats=[[43.0, 60.0], [39.0, 72.0]])
    add("heat_still_warm", [call("heat_wait"), call("heat_wait", advance=30.0)], [mp], settings=hot, heats=[[43.0, 60.0], [39.1, 72.0]])
    add("heat_pi_still_warm", [call("heat_wait"), call("heat_wait", advance=30.0)], [mp], settings=hot, heats=[[43.0, 60.0], [30.0, 72.1]])
    add("heat_sensor_gone_while_paused", [call("heat_wait"), call("heat_wait", advance=30.0)], [mp], settings=hot, heats=[[43.0, 60.0], [None, None]])
    add("heat_longest_pause_not_over", [call("heat_wait"), call("heat_wait", advance=2700.0)], [mp], settings=hot, heats=[[43.0, 60.0], [43.0, 82.0]])
    add("heat_longest_pause_over_2701", [call("heat_wait"), call("heat_wait", advance=2701.0)], [mp], settings=hot, heats=[[43.0, 60.0], [43.0, 82.0]])
    add("heat_pause_then_cool_with_no_phone", [call("heat_wait"), call("heat_wait", advance=60.0)], [mp], settings=hot, heats=[[43.0, 60.0], [None, 50.0]])
    add("heat_pause_then_cool_with_no_pi", [call("heat_wait"), call("heat_wait", advance=60.0)], [mp], settings=hot, heats=[[43.0, 60.0], [20.0, None]])
    add("heat_setting_switched_off_while_paused", [call("heat_wait"), call("heat_wait", advance=5.0, settings={"heat_pause": False}), call("heat_wait", advance=5.0)],
        [mp], settings=hot, heats=[[43.0, 60.0]])
    add("heat_in_step", [step()], [mp], settings=hot, heats=[[43.0, 60.0]])
    add("heat_in_step_cool", [step()], [mp], settings=hot, heats=[[30.0, 60.0]], shots=[0], maps=[{"wait": 2.5}])

    # ---- the small readers
    for name, text in (("a_rocket", "TEAM GO ROCKET"), ("a_grunt", "GRUNT SAYS"), ("a_party", "BATTLE PARTY"), ("use_party", "USE THIS PARTY NOW"),
                       ("nothing", ""), ("rocket_in_lower_case_is_read_in_capitals", "team go rocket"), ("part_of_it", "TEAM GO"), ("something_else", "ROCKETS")):
        add("rocket_text_%s" % name, [call("is_rocket_text", img=0)], [frame(text=text)])
    for name, text in (("full", "YOUR POKEMON STORAGE IS FULL"), ("only_storage", "STORAGE"), ("only_full", "FULL"), ("none", ""), ("lower_case_is_read_in_capitals", "storage full"),
                       ("spread", "THE STORAGE IS NOT FULL")):
        add("storage_text_%s" % name, [call("storage_full", img=0)], [frame(text=text)])

    group_lines = lambda *items: [[t, x, y, ws] for t, x, y, ws in items]
    cancel = ("ARE YOU SURE YOU WANT TO JOIN A GROUP CANCEL", 884, 1200, [["CANCEL", 600, 1500], ["JOIN", 1100, 1500]])
    for name, lines, expect in (
            ("question_with_cancel", group_lines(("GROUP WITH OTHER TRAINERS", 884, 900, [["GROUP", 700, 900]]), ("CANCEL", 600, 1500, [["CANCEL", 600, 1500]])), True),
            ("question_are_you_sure", group_lines(("ARE YOU SURE", 884, 900, []), ("JOIN A GROUP", 884, 1000, []), ("CANCEL", 600, 1500, [["CANCEL", 610, 1510]])), True),
            ("question_without_cancel", group_lines(("GROUP WITH OTHER TRAINERS", 884, 900, [])), True),
            ("are_you_sure_without_group", group_lines(("ARE YOU SURE", 884, 900, [])), False),
            ("screen_find_me_a_group", group_lines(("FIND ME A GROUP!", 884, 900, [])), True),
            ("screen_weekly_challenge", group_lines(("WEEKLY CHALLENGE", 884, 300, [])), True),
            ("screen_join_group", group_lines(("JOIN GROUP", 884, 900, [])), True),
            ("screen_with_a_cancel_word", group_lines(("WEEKLY CHALLENGE", 884, 300, [["WEEKLY", 400, 300], ["CANCEL", 700, 400]])), True),
            ("two_cancel_words", group_lines(("GROUP WITH OTHER TRAINERS", 884, 900, [["CANCEL", 500, 1500], ["CANCEL", 900, 1600]])), True),
            ("cancel_in_a_word_only", group_lines(("WEEKLY CHALLENGE", 884, 300, [["CANCELLED", 400, 300]])), True),
            ("nothing", [], False),
            ("another_screen", group_lines(("YOUR POKEMON", 884, 900, [])), False),
            ("two_lines_make_the_question", group_lines(("ARE YOU SURE?", 400, 900, []), ("GROUP", 400, 1000, [])), True),
            ("a_line_above_row_150_is_not_read", group_lines(("WEEKLY CHALLENGE", 884, 149, [])), False),
            ("the_line_at_row_150_is_read", group_lines(("WEEKLY CHALLENGE", 884, 150, [])), True)):
        add("group_%s" % name, [call("leave_group_screen", img=0)], [frame(lines=lines)])

    # ---- pause_catching(): the Pokémon storage is full
    add("pause_catching", [call("pause_catching")], [mp])
    add("pause_catching_when_paused_already", [call("pause_catching")], [mp], init={"catch": False})
    add("pause_catching_and_it_comes_back", [call("pause_catching"), call("resume_catching", advance=1800.0)], [mp])
    add("pause_catching_twice_and_the_last_one_comes_back", [call("pause_catching"), call("pause_catching", advance=10.0), call("resume_catching", advance=1790.0)], [mp])

    # ---- step(): the first things - the screen has another shape, the phone is awake, the screenshot
    add("screen_not_ok_adapted", [step()], [mp], init={"screen_ok": False}, adapts=[{"result": True, "seconds": 1.25}])
    add("screen_not_ok_not_adapted", [step()], [mp], init={"screen_ok": False}, adapts=[{"result": False, "seconds": 0.5}])
    add("screen_not_ok_then_ok_after_adapt_failed", [step(), step()], [mp], init={"screen_ok": False},
        adapts=[{"result": False, "ok": True}], shots=[0], maps=[{"wait": 2.0}])
    add("layout_watch_moves_the_clock", [step()], [mp], watches=[{"seconds": 0.75}], maps=[{"wait": 1.0}])
    add("layout_watch_changes_the_screen", [step()], [mp], watches=[{"ok": False, "state": "adapting"}], maps=[{"wait": 1.0}])

    for name, ok, age in (("not_ok", False, 1.0), ("a_minute_ago", True, 60.0), ("just_over_a_minute_ago", True, 60.001), ("59_s_ago", True, 59.999),
                          ("long_ago", True, 3600.0)):
        add("health_%s" % name, [step(advance=age)], [mp], init={"health": {"ok": ok, "t": START}}, powers=["mWakefulness=Awake"], maps=[{"wait": 1.0}])
    add("health_awake", [step()], [mp], init={"health": {"ok": False, "t": START}}, powers=["Display Power: state=ON\nmWakefulness=Awake\n"])
    add("health_asleep", [step()], [mp], init={"health": {"ok": False, "t": START}}, powers=["mWakefulness=Asleep"], maps=[{"wait": 1.0}])
    add("health_dozing", [step()], [mp], init={"health": {"ok": False, "t": START}}, powers=["mWakefulness=Dozing"], maps=[{"wait": 1.0}])
    add("health_no_text", [step()], [mp], init={"health": {"ok": False, "t": START}}, powers=[""], maps=[{"wait": 1.0}])
    add("health_takes_time", [step()], [mp], init={"health": {"ok": False, "t": START}}, powers=["mWakefulness=Awake"], shot_seconds=0.5, maps=[{"wait": 1.0}])
    add("health_ok_after_the_step", [step(), step(advance=10.0)], [mp, other("menusScreen")], init={"health": {"ok": False, "t": START}},
        shots=[0, 1], powers=["mWakefulness=Awake"], maps=[{"wait": 1.0}])

    add("handoff_used", [step()], [mp], init={"handoff": {"img": 0, "t": START - 2.0}}, maps=[{"wait": 1.0}])
    add("handoff_used_at_2_49", [step()], [mp], init={"handoff": {"img": 0, "t": START - 2.49}}, maps=[{"wait": 1.0}])
    add("handoff_too_old_2_5", [step()], [mp], init={"handoff": {"img": 0, "t": START - 2.5}}, maps=[{"wait": 1.0}])
    add("handoff_too_old_3", [step()], [mp, mp], shots=[1], init={"handoff": {"img": 0, "t": START - 3.0}}, maps=[{"wait": 1.0}])
    add("handoff_used_only_once", [step(), step()], [mp, mp], shots=[1], init={"handoff": {"img": 0, "t": START}}, maps=[{"wait": 1.0}])
    add("handoff_not_in_the_future_is_used", [step()], [mp], init={"handoff": {"img": 0, "t": START + 5.0}}, maps=[{"wait": 1.0}])
    add("handoff_with_a_dimmed_game_is_not_unlocked", [step()], [mp, mp], init={"handoff": {"img": 0, "t": START}}, unlocks=[{"img": 1}], maps=[{"wait": 1.0}])

    add("screenshot_is_unlocked", [step()], [mp, mp], shots=[0], unlocks=[{"img": 1, "seconds": 3.0}], maps=[{"wait": 1.0}])
    add("screenshot_fails", [step()], [mp], shots=["error: no screen"])
    add("classifier_fails", [step()], [frame(screen_error="model gone")])
    add("rotation_armed_fires_with_the_screenshot", [step()], [mp], init={"rotation": {"armed": [[350, 900, 1050, 900, 600], 0], "armed_at": START - 5.0}},
        maps=[{"wait": 1.0}])
    add("rotation_armed_too_old_20_s", [step()], [mp], init={"rotation": {"armed": [[350, 900, 1050, 900, 600], 0], "armed_at": START - 20.0}},
        maps=[{"wait": 1.0}])
    add("rotation_armed_too_old_20_1", [step()], [mp], init={"rotation": {"armed": [[350, 900, 1050, 900, 600], 0], "armed_at": START - 20.001}},
        maps=[{"wait": 1.0}])
    add("rotation_armed_shot_takes_time", [step()], [mp], init={"rotation": {"armed": [[350, 900, 1050, 900, 600], 0], "armed_at": START - 19.9}}, shot_seconds=0.25,
        maps=[{"wait": 1.0}])
    add("rotation_not_armed_with_a_fired_swipe", [step()], [mp], init={"rotation": {"fired": {"t": START - 1.0, "swipe": [350, 900, 1050, 900, 600]}}},
        maps=[{"wait": 1.0}])

    # ---- the classifier: how sure it is, the live picture that is too soft to read
    for name, score, expect in (("0_5", 0.5, "mapScreen"), ("0_4999", 0.4999, "onbekend"), ("0_49", 0.49, "onbekend"), ("0_0", 0.0, "onbekend")):
        add("classifier_sure_%s" % name, [step()], [map_frame(screen=("mapScreen", score))], maps=[{"wait": 1.0}], stops=[{"wait": 1.0}])
    add("classifier_unsure_stop", [step()], [other("pokestopScreen", 0.49)], shots=[0])
    add("live_map_is_not_looked_at_again", [step()], [mp], live=True, maps=[{"wait": 1.0}])
    add("live_encounter_is_not_looked_at_again", [step()], [enc], live=True, encounters=[{"wait": 1.0}])
    add("live_menus_is_looked_at_again", [step()], [other("menusScreen"), mp], live=True, shots=[0, 1], maps=[{"wait": 1.0}])
    add("live_menus_is_the_same_after_the_real_shot", [step()], [other("menusScreen"), other("menusScreen")], live=True, shots=[0, 1])
    add("live_stop_is_looked_at_again", [step()], [stop, stop], live=True, shots=[0, 1], stops=[{"wait": 1.0}])
    add("live_unsure_then_sure", [step()], [other("mapScreen", 0.4), mp], live=True, shots=[0, 1], maps=[{"wait": 1.5}])
    add("live_looked_at_again_is_unlocked", [step()], [other("menusScreen"), other("menusScreen"), other("menusScreen")], live=True, shots=[0, 1, 2],
        unlocks=[{}, {"img": 2}])
    add("live_second_look_is_unsure", [step()], [other("menusScreen"), other("mapScreen", 0.49)], live=True, shots=[0, 1])
    add("live_second_look_is_exactly_sure", [step()], [other("menusScreen"), other("mapScreen", 0.5)], live=True, shots=[0, 1], maps=[{"wait": 1.0}])
    add("live_second_classifier_fails", [step()], [other("menusScreen"), frame(screen_error="model gone")], live=True, shots=[0, 1])

    add("rotation_forgotten_when_it_is_not_the_map", [step()], [other("menusScreen")],
        init={"rotation": {"fired": {"t": START - 1.0, "swipe": [350, 900, 1050, 900, 600]}, "armed": [[1, 2, 3, 4, 5], 0], "armed_at": START}})
    add("rotation_armed_is_forgotten_with_a_handed_on_picture", [step()], [other("menusScreen")],
        init={"handoff": {"img": 0, "t": START}, "rotation": {"armed": [[350, 900, 1050, 900, 600], 0], "armed_at": START,
                                                              "fired": {"t": START - 1.0, "swipe": [350, 900, 1050, 900, 600]}}})
    add("rotation_armed_is_kept_with_a_handed_on_map", [step()], [mp], init={"handoff": {"img": 0, "t": START}, "rotation": {"armed": [[350, 900, 1050, 900, 600], 0], "armed_at": START}},
        maps=[{"wait": 1.0}])
    add("rotation_kept_on_the_map_screen", [step()], [mp], init={"rotation": {"fired": {"t": START - 1.0, "swipe": [350, 900, 1050, 900, 600]}}},
        maps=[{"wait": 1.0}])
    add("rotation_forgotten_when_the_picture_is_not_the_map", [step()], [other("pokestopScreen")],
        init={"rotation": {"fired": {"t": START - 1.0, "swipe": [350, 900, 1050, 900, 600]}}}, stops=[{"wait": 1.0}])
    add("rotation_kept_when_the_map_is_there_on_another_screen", [step()], [map_frame(screen=("pokestopScreen", 0.9))],
        init={"rotation": {"fired": {"t": START - 1.0, "swipe": [350, 900, 1050, 900, 600]}}}, stops=[{"wait": 1.0}])
    add("rotation_a_mapscreen_that_is_not_the_map", [step()], [frame(screen=("mapScreen", 0.9))],
        init={"rotation": {"fired": {"t": START - 1.0, "swipe": [350, 900, 1050, 900, 600]}}}, maps=[{"wait": 1.0}])

    # ---- the same screen again and again, away from the map for minutes
    for name, screen in (("map", "mapScreen"), ("encounter", "encounterScreen"), ("stop", "pokestopScreen")):
        add("away_cleared_on_%s" % name, [step()], [other(screen)], init={"away": {"since": START - 1000.0}}, maps=[{"wait": 1.0}], stops=[{"wait": 1.0}],
            encounters=[{"wait": 1.0}])
    add("away_starts", [step()], [other("menusScreen")])
    add("away_starts_on_an_unsure_screen", [step()], [other("mapScreen", 0.3)])
    for name, ago in (("0", 0.0), ("299", 299.0), ("300", 300.0), ("300_01", 300.01), ("301", 301.0)):
        add("away_for_%s_s" % name, [step()], [other("menusScreen")], init={"away": {"since": START - ago}})
    add("away_restart_goes_on_to_nothing", [step(), step()], [other("menusScreen")], init={"away": {"since": START - 400.0}})
    add("away_restart_clears_the_same_screen_count", [step()], [other("menusScreen")], init={"away": {"since": START - 400.0}, "same_screen": {"name": "menusScreen", "count": 5}})
    for name, count in (("1", 1), ("11", 11), ("12", 12), ("13", 13)):
        add("same_screen_%s" % name, [step()], [other("menusScreen")], init={"same_screen": {"name": "menusScreen", "count": count}})
    add("same_screen_another_one_resets", [step()], [other("menusScreen")], init={"same_screen": {"name": "eggScreen", "count": 40}})
    add("same_screen_map_is_never_stuck", [step()], [mp], init={"same_screen": {"name": "mapScreen", "count": 40}}, maps=[{"wait": 1.0}])
    add("same_screen_stuck_and_away", [step()], [other("menusScreen")], init={"same_screen": {"name": "menusScreen", "count": 12}, "away": {"since": START - 400.0}})
    add("same_screen_counts_over_several_steps", [step() for _ in range(15)], [other("eggScreen")])
    add("same_screen_map_and_back", [step(), step(), step()], [mp, other("eggScreen"), mp], shots=[0, 1, 2], maps=[{"wait": 1.0}])

    # ---- a tap on a Pokémon that did not open the catch screen
    tap_pokemon = {"kind": "pokemon", "xy": [800, 900], "alt": None, "near": False}
    add("pokemon_tap_next_try_lower", [step()], [mp], init={"last_tap": dict(tap_pokemon, alt=[[800, 960], [800, 1010]])})
    add("pokemon_tap_next_try_lower_the_last_one", [step(), step()], [mp, mp], shots=[0, 1], init={"last_tap": dict(tap_pokemon, alt=[[800, 960]])},
        maps=[{"wait": 1.0}])
    add("pokemon_tap_no_alt_on_the_map", [step()], [mp], init={"last_tap": dict(tap_pokemon, alt=[])}, maps=[{"wait": 1.0}])
    add("pokemon_tap_no_encounter", [step()], [other("menusScreen")], init={"last_tap": tap_pokemon})
    add("pokemon_tap_no_encounter_on_the_stop", [step()], [stop], init={"last_tap": tap_pokemon}, stops=[{"wait": 1.0}])
    add("pokemon_tap_no_encounter_near_buddy_on", [step()], [other("menusScreen")], settings={"buddy": True}, init={"last_tap": dict(tap_pokemon, near=True)})
    add("pokemon_tap_no_encounter_near_buddy_off", [step()], [other("menusScreen")], settings={"buddy": False}, init={"last_tap": dict(tap_pokemon, near=True)})
    add("pokemon_tap_no_encounter_not_near_buddy_on", [step()], [other("menusScreen")], settings={"buddy": True}, init={"last_tap": tap_pokemon})
    add("pokemon_tap_no_encounter_near_default", [step()], [other("menusScreen")], init={"last_tap": dict(tap_pokemon, near=True)})
    add("pokemon_tap_with_encounter", [step()], [enc], init={"last_tap": tap_pokemon}, encounters=[{"wait": 1.0}])
    add("pokemon_tap_with_encounter_and_alt", [step()], [enc], init={"last_tap": dict(tap_pokemon, alt=[[1, 2]])}, encounters=[{"wait": 1.0}])
    add("pokemon_tap_with_encounter_near_is_kept", [step()], [enc], init={"last_tap": dict(tap_pokemon, near=True)}, encounters=[{"wait": 1.0}])
    add("stop_tap_is_forgotten", [step()], [mp], init={"last_tap": {"kind": "stop", "xy": [500, 600], "alt": None, "near": True}}, maps=[{"wait": 1.0}])
    add("pokemon_tap_cooldown_grows", [step()], [other("menusScreen")], init={"last_tap": tap_pokemon, "cooldown": [[1, 2, 3.0]]})

    # ---- Team Rocket
    rocket_frame = lambda screen="rocketScreen", **kw: other(screen, **kw)
    add("rocket_screen_fight_won", [step()], [rocket_frame()], rockets=[{"result": "won", "seconds": 40.0}])
    add("rocket_screen_fight_lost", [step()], [rocket_frame()], rockets=[{"result": "lost"}])
    add("rocket_screen_fight_failed_back_to_the_map", [step()], [rocket_frame(), mp], rockets=[{"result": "failed"}], shots=[0, 1], maps=[{"wait": 1.0}])
    add("rocket_screen_fight_failed_at_a_stop", [step()], [rocket_frame(), other("menusScreen")], rockets=[{"result": "failed"}], shots=[0, 1],
        init={"last_tap": {"kind": "stop", "xy": [500, 600], "alt": None, "near": False}})
    add("rocket_screen_fight_failed_at_a_pokemon", [step()], [rocket_frame(), other("menusScreen")], rockets=[{"result": "failed"}], shots=[0, 1],
        init={"last_tap": {"kind": "pokemon", "xy": [500, 600], "alt": None, "near": False}})
    add("rocket_screen_fight_fails_with_an_error", [step()], [rocket_frame(), other("menusScreen")], rockets=[{"error": "the phone is gone"}], shots=[0, 1])
    add("rocket_screen_fight_fails_and_the_next_screen_is_rocket", [step()], [rocket_frame(), rocket_frame()], rockets=[{"result": "failed"}], shots=[0, 1])
    add("rocket_screen_fight_fails_second_screenshot_fails", [step()], [rocket_frame()], rockets=[{"result": "failed"}], shots=[0, "error: no screen"])
    for screen in ("menusScreen", "rewardScreen", "onbekend"):
        add("rocket_text_%s_fight" % screen, [step()], [other(screen, texts={1300: "TEAM GO ROCKET"})], rockets=[{"result": "won"}])
    add("rocket_text_on_the_map_is_not_looked_at", [step()], [frame(text="TEAM GO ROCKET", ops=mp["pic"], screen=("mapScreen", 0.9))], maps=[{"wait": 1.0}])
    add("rocket_text_on_an_egg_is_not_looked_at", [step()], [other("eggScreen", text="TEAM GO ROCKET")])
    add("rocket_text_on_a_stop_is_not_looked_at", [step()], [other("pokestopScreen", text="TEAM GO ROCKET")], stops=[{"wait": 1.0}])
    add("rocket_text_unsure_screen", [step()], [other("mapScreen", 0.3, texts={1300: "GRUNT"})], rockets=[{"result": "won"}])
    add("rocket_no_fight_screen", [step()], [rocket_frame(), other("menusScreen"), mp], settings={"rocket_fight": False}, shots=[0, 1, 2])
    add("rocket_no_fight_back_is_enough", [step()], [rocket_frame(), mp], settings={"rocket_fight": False}, shots=[0, 1], shot_seconds=0.5)
    add("rocket_no_fight_map_but_unsure", [step()], [rocket_frame(), other("mapScreen", 0.49), other("mapScreen", 0.49), other("mapScreen", 0.5)],
        settings={"rocket_fight": False}, shots=[0, 1, 2, 3])
    add("rocket_no_fight_never_back_on_the_map", [step()], [rocket_frame(), other("menusScreen")], settings={"rocket_fight": False}, shots=[0, 1, 1, 1])
    add("rocket_no_fight_at_a_stop", [step()], [rocket_frame(), mp], settings={"rocket_fight": False}, shots=[0, 1],
        init={"last_tap": {"kind": "stop", "xy": [500, 600], "alt": None, "near": True}})
    add("rocket_no_fight_at_a_pokemon", [step()], [rocket_frame(), mp], settings={"rocket_fight": False}, shots=[0, 1],
        init={"last_tap": {"kind": "pokemon", "xy": [500, 600], "alt": None, "near": False}, "cooldown": [[1, 2, 3.0]]})
    add("rocket_no_fight_forgets_the_tap_with_its_alternatives", [step()], [rocket_frame(), mp], settings={"rocket_fight": False}, shots=[0, 1],
        init={"last_tap": {"kind": "pokemon", "xy": [500, 600], "alt": [[500, 660], [500, 710]], "near": True}})
    add("rocket_no_fight_text_menus", [step()], [other("menusScreen", texts={1300: "BATTLE PARTY"}), mp], settings={"rocket_fight": False}, shots=[0, 1])
    add("rocket_no_fight_text_menus_not_rocket_second_time", [step()], [other("menusScreen")], settings={"rocket_fight": False})
    add("rocket_fight_fails_then_text_is_there_again", [step()], [other("onbekend", texts={1300: "GRUNT"}), other("menusScreen")],
        rockets=[{"result": "failed"}], shots=[0, 1])

    # ---- the first look at the map: is the game drawn as expected?
    for name, state, after, ok in (("new_confirmed", "new", "confirmed", True), ("new_unverified", "new", "unverified", True), ("new_adapting", "new", "adapting", True),
                                   ("new_adapted", "new", "adapted", True), ("new_not_ok", "new", "confirmed", False), ("adapting_confirmed", "adapting", "confirmed", True),
                                   ("adapting_adapted", "adapting", "adapted", True), ("adapting_still", "adapting", "adapting", True)):
        add("layout_%s" % name, [step()], [mp], init={"layout": state}, verifies=[{"state": after, "ok": ok, "seconds": 0.5}], maps=[{"wait": 1.0}])
    for state in ("confirmed", "unverified", "adapted"):
        add("layout_%s_is_not_verified" % state, [step()], [mp], init={"layout": state}, maps=[{"wait": 1.0}])
    add("layout_new_but_not_the_map_screen", [step()], [other("menusScreen")], init={"layout": "new"})
    add("layout_new_on_a_stop", [step()], [stop], init={"layout": "new"}, stops=[{"wait": 1.0}])

    # ---- the quests
    add("quests_not_due", [step()], [mp], due=[{"result": False}], maps=[{"wait": 1.0}])
    add("quests_claimed", [step()], [mp], due=[{"result": True}], claims=[{"result": "claimed", "seconds": 30.0}])
    add("quests_nothing", [step()], [mp], due=[{"result": True}], claims=[{"result": "nothing"}])
    add("quests_a_pokemon_came", [step()], [mp], due=[{"result": True}], claims=[{"result": "catch"}])
    add("quests_failed", [step()], [mp], due=[{"result": True}], claims=[{"result": "failed"}], maps=[{"wait": 1.5}])
    add("quests_error", [step()], [mp], due=[{"result": True}], claims=[{"error": "no CLAIM ALL"}], maps=[{"wait": 1.5}])
    add("quests_after_the_layout_check", [step()], [mp], init={"layout": "new"}, verifies=[{"state": "confirmed"}], due=[{"result": True}], claims=[{"result": "claimed"}])
    add("quests_not_asked_when_the_layout_is_checked_again", [step()], [mp], init={"layout": "new"}, verifies=[{"state": "adapting"}])
    add("quests_not_asked_on_a_stop", [step()], [stop], due=[{"result": True}], stops=[{"wait": 1.0}])

    # ---- the map, the stop, the catch screen
    add("map_step", [step()], [mp], maps=[{"wait": 2.5, "seconds": 1.5}], shot_seconds=0.25, screen_seconds=0.125)
    add("map_step_perf_adds_up", [step(), step()], [mp], maps=[{"wait": 2.5, "seconds": 1.5}, {"wait": 0.5, "seconds": 0.75}], shot_seconds=0.25)
    add("map_step_live", [step()], [mp], maps=[{"wait": 0.0}], live=True, shot_seconds=0.1)
    add("map_step_zero_wait", [step()], [mp], maps=[{"wait": 0.0}])
    add("map_step_handoff", [step()], [mp], init={"handoff": {"img": 0, "t": START - 1.0}}, maps=[{"wait": 3.0}])
    add("stop_step", [step()], [stop], stops=[{"wait": 3.5, "seconds": 2.0}])
    add("encounter_step", [step()], [enc], encounters=[{"wait": 2.0, "seconds": 30.0}])
    add("encounter_step_sets_health", [step(), step()], [enc, other("menusScreen")], shots=[0, 1], encounters=[{"wait": 2.0}], init={"health": {"ok": False, "t": START}},
        powers=["mWakefulness=Awake"])

    # ---- an egg, the summary
    add("egg", [step()], [other("eggScreen")])
    add("summary_counts_the_catch", [step()], [other("summaryScreen")], init={"enc": {"throws": 2}})
    add("summary_nothing_thrown", [step()], [other("summaryScreen")])
    add("summary_already_counted", [step()], [other("summaryScreen")], init={"enc": {"throws": 2, "caught": True}})

    # ---- a news card, a group, the safety notice, a full storage
    for screen in ("menusScreen", "rewardScreen", "onbekend", "summaryScreen", "pokemonScreen", "areneScreen"):
        add("news_on_%s" % screen, [step()], [other(screen, texts={2000: "SEE DETAILS DISMISS"})])
    add("news_not_on_the_map", [step()], [frame(ops=mp["pic"], screen=("mapScreen", 0.9), texts={2000: "DISMISS"})], maps=[{"wait": 1.0}])
    add("news_not_on_the_catch_screen", [step()], [dict(enc, texts={"2000": "DISMISS"})], encounters=[{"wait": 1.0}])
    add("news_on_a_stop", [step()], [other("pokestopScreen", texts={2000: "DISMISS"})], stops=[{"wait": 1.0}])
    add("news_on_an_egg_is_the_egg", [step()], [other("eggScreen", texts={2000: "DISMISS"})])

    group_q = group_lines(("GROUP WITH OTHER TRAINERS", 884, 900, [["CANCEL", 600, 1500]]))
    for screen in ("menusScreen", "onbekend", "rewardScreen", "summaryScreen", "pokemonScreen"):
        add("group_question_on_%s" % screen, [step()], [other(screen, lines=group_q)])
    add("group_screen_closed", [step()], [other("menusScreen", lines=group_lines(("WEEKLY CHALLENGE", 884, 300, [])))])
    add("group_question_in_a_step_without_cancel", [step()], [other("menusScreen", lines=group_lines(("ARE YOU SURE", 884, 300, []), ("GROUP", 884, 400, [])))])
    add("group_screen_after_news", [step()], [other("menusScreen", lines=group_q, texts={2000: "DISMISS"})])
    add("group_not_asked_for_a_stop", [step()], [other("pokestopScreen", lines=group_q)], stops=[{"wait": 1.0}])

    pill = frame([PLAIN, PILL], screen=("menusScreen", 0.9), texts={1100: "STAY AWARE OF YOUR SURROUNDINGS"})
    pale = frame([PLAIN, ["rect", 504, 1900, 760, 150, PALE]], screen=("menusScreen", 0.9), texts={1100: "DO NOT TRESPASS"})
    nobutton = frame(screen=("menusScreen", 0.9), texts={1100: "DO NOT PLAY WHILE DRIVING"})
    for name, f in (("pill", pill), ("green", pale), ("no_button", nobutton)):
        add("safety_notice_%s" % name, [step()], [f])
    for screen in ("rewardScreen", "onbekend"):
        add("safety_notice_on_%s" % screen, [step()], [other(screen, texts={1100: "DANGEROUS AREAS"})])
    add("safety_notice_on_a_stop_is_the_stop", [step()], [other("pokestopScreen", texts={1100: "SURROUNDINGS"})], stops=[{"wait": 1.0}])
    add("safety_notice_summary_is_the_summary", [step()], [other("summaryScreen", texts={1100: "SURROUNDINGS"})])
    add("safety_notice_pokemon_screen_back", [step()], [other("pokemonScreen", texts={1100: "SURROUNDINGS"})])

    for screen in ("menusScreen", "onbekend", "rewardScreen"):
        for catch in (True, False):
            add("storage_full_on_%s_catching_%s" % (screen, "on" if catch else "off"), [step()], [other(screen, texts={450: "YOUR POKEMON STORAGE IS FULL"})],
                init={"catch": catch})
    add("storage_full_after_the_notice_check", [step()], [other("menusScreen", texts={450: "STORAGE FULL", 1100: "SURROUNDINGS"})])
    add("storage_full_pokemon_screen_back", [step()], [other("pokemonScreen", texts={450: "STORAGE FULL"})])

    # ---- the menus: the passenger pop-up, otherwise back
    btn = lambda name="passenger", score=0.9, x=884, y=1900, w=700, h=150: (name, score, x, y, w, h)
    add("menus_passenger", [step()], [other("menusScreen", buttons=[btn()], texts={1825: "I AM A PASSENGER"})])
    add("menus_passenger_unsure", [step()], [other("menusScreen", buttons=[btn(score=0.79)])])
    add("menus_passenger_exact", [step()], [other("menusScreen", buttons=[btn(score=0.8)], text="OK")])
    add("menus_passenger_a_battle_button", [step()], [other("menusScreen", buttons=[btn(name="passenger"), btn(name="clickable", score=0.5)], text="BATTLE")])
    add("menus_no_buttons_back", [step()], [other("menusScreen", buttons=[])])
    add("menus_an_ok_button_is_not_tapped", [step()], [other("menusScreen", buttons=[btn(name="clickable", score=0.9)], text="OK")])

    # ---- the result screen and the others
    for screen in ("rewardScreen", "onbekend"):
        rs = frame(TG.buttons_ops(berry=False, ball=False) + [["rect", 534, 1900, 700, 150, CG.teal()]], screen=(screen, 0.9))
        add("%s_result_after_a_throw" % screen, [step()], [rs], init={"enc": {"throws": 2}}, advance=0.0)
        add("%s_result_after_a_throw_already_counted" % screen, [step()], [rs], init={"enc": {"throws": 2, "caught": True}})
        add("%s_button_after_a_throw" % screen, [step()], [other(screen, buttons=[btn(name="clickable", score=0.5)], text="OK")], init={"enc": {"throws": 2}})
        add("%s_button" % screen, [step()], [other(screen, buttons=[btn(name="clickable", score=0.5)], text="OK")])
        add("%s_battle_button" % screen, [step()], [other(screen, buttons=[btn(name="clickable", score=0.5)], text="BATTLE")])
        add("%s_green_button" % screen, [step()], [frame([PLAIN, ["rect", 504, 1900, 760, 150, PALE]], screen=(screen, 0.9))])
        add("%s_nothing_to_tap" % screen, [step()], [other(screen)])
        add("%s_nothing_to_tap_after_a_throw" % screen, [step()], [other(screen)], init={"enc": {"throws": 1}})
    add("onbekend_on_the_map", [step()], [CG.frame([PLAIN, ["rect", 860, 1920, 46, 20, [30, 30, 220]], ["rect", 860, 2020, 46, 30, [255, 255, 255]]],
                                                    screen=("onbekend", 0.9))], maps=[{"wait": 2.0, "seconds": 0.5}])
    add("onbekend_unsure_on_the_map", [step()], [map_frame(screen=("mapScreen", 0.3))], maps=[{"wait": 2.0}])
    add("reward_on_the_map_is_not_done", [step()], [map_frame(screen=("rewardScreen", 0.9))])
    add("another_screen_goes_back", [step()], [other("pokemonScreen")])
    add("a_gym_screen_goes_back", [step()], [other("areneScreen")])
    add("a_screen_that_is_unknown_goes_back", [step()], [other("whatever")])

    # ---- a few steps one after the other
    add("a_round", [step() for _ in range(5)], [mp, mp, enc, other("rewardScreen"), mp], shots=[0, 1, 2, 3, 4], maps=[{"wait": 1.0}, {"wait": 2.0}, {"wait": 0.5}],
        encounters=[{"wait": 1.5, "seconds": 10.0}])
    add("a_stuck_round", [step() for _ in range(14)], [other("menusScreen")], shots=[0])
    add("shot_errors_in_a_row", [step(), step()], [mp], shots=["error: no screen"])
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
    with open(OUT, "rb") as f:
        stored = json.loads(unpack(f.read()))
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
