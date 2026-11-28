#!/usr/bin/env python3
"""Makes tests/fixtures/daily_golden.json.qz (JSON, packed the way qCompress() of Qt does: the length, then zlib): what gamebot.py does in the daily run -
daily_cycle() (the start time of the day, the run that goes on after a restart, the apps one after the other, the next run), run_one_game() (the time of
every app counted, the battles first, the teams, the steps, the run time that is up, the battles that go on after a Pokémon of a reward was caught),
finish_catch(), last_slot(), daily_limit(), daily_order(), load_daily()/save_daily() and reset_for_game() - the file that the C++ port,
SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoDaily.cpp, is tested against.

    python3 tools/make_daily_golden.py            writes the file
    python3 tools/make_daily_golden.py --check    says whether the file is what the code does now (the stories stored in it are played again)

A story is a list of calls (daily_cycle() again and again, as the loop of the bot calls it), each with the EVENTS that it makes, in order, with the time of a
fake clock.  The clock is a day in November 2026 in a pretend time zone (one hour east of UTC, no summer time); it only moves with the sleeps, the steps and
what the stories say.  What the code is GIVEN:
    daily_file      what the file of the daily run holds (nothing: there is none or it is no JSON)
    packages        the Pokémon GO apps that are installed
    battle_wanted, battle_app    what the person chose for the battles (and whether they are done today)
    teams_due       is it time to bring the teams up to date
    step            what one step of the bot did: how long it took, how long it wants to wait, and what it changed (the run is done, the person switched
                    the run off, the Pokémon of a reward was caught, ...), or that it failed (step_error)
    restart         the game was started again (how long that took), or that it failed (restart_error)
    shot, screen    a screenshot, and what the screen classifier said of it (finish_catch)
    battle_op       what the battles ask of the run while they are fought (beat, is it time to stop, is the time up, time passes, an error), then battle_result
    teams_op        the same for the teams, then teams_end
  what it DOES:
    log, sleep, daily_save (what is written to the file), reset (the game is played from the start: the flags of the last game are reset), watchdog
    (started, stopped), close_game, auto_battle, teams_refresh (called), and at the end of every call: result (what it returned) or raised, and state (what
    the run remembers: that it is done, the time it last said it was waiting, whether the battles go on).
"""
import argparse
import calendar
import json
import os
import struct
import sys
import tempfile
import time as _time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_catch_golden as CG  # noqa: E402  (the frames and the fake screen classifier)
import make_gifts_golden as GG  # noqa: E402  (the helpers of the frames)
from make_start_golden import Clock, Rec  # noqa: E402
import gamebot as G  # noqa: E402
import spin_stop as S  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "tests", "fixtures", "daily_golden.json.qz")
OFFSET = 3600                                                                # the pretend time zone: one hour east of UTC, no summer time
DAY0 = float(calendar.timegm((2026, 11, 22, 0, 0, 0)) - OFFSET)               # midnight of Sunday 22 November 2026 there
MAIN = "com.nianticlabs.pokemongo"
ARES = "com.nianticlabs.pokemongo.ares"
PLAIN, frame = GG.PLAIN, GG.frame


def at(h, m=0, s=0):
    return h * 3600.0 + m * 60.0 + s


class Over(BaseException):
    """The story has no more steps: it ends here (not an Exception: the code must not take it for an error of a step)."""


class Stopper:
    def __init__(self, rec, pkg):
        self.rec, self.pkg = rec, pkg

    def set(self):
        self.rec.add("watchdog", self.pkg, "stop")


class Brain:
    """The screen classifier of the run: it says what the frame of the picture says."""

    def __init__(self, world, rec, spec):
        self.fake = CG.FakeBrain(world, rec, spec)

    def screen(self, img):
        return self.fake.screen(img)


# ---------------------------------------------------------------------- the stories are played on the fake phone

def record(spec):
    """Plays one story on the fake phone; returns the list of events."""
    Clock.t = DAY0 + spec.get("at", at(8))
    rec = Rec()
    Clock.rec = rec
    world = CG.World(spec)
    saved_time = {n: Clock.__dict__.get(n) for n in ("localtime", "mktime", "strftime")}
    names = ("time", "log", "setting", "wanted", "game_packages", "battle_wanted", "battle_app", "load_daily", "save_daily", "DAILY_FILE", "reset_for_game",
             "close_game_completely", "auto_battle", "teams_due", "teams_refresh", "step", "start_watchdog", "finish_catch", "force_start", "run_state")
    saved = {n: getattr(G, n) for n in names}
    saved_s = {n: getattr(S, n) for n in ("time", "log", "screenshot", "on_map", "restart_game", "PACKAGE")}
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "gamebot_daily.json")
    try:
        Clock.localtime = staticmethod(lambda ts=None: _time.gmtime((Clock.t if ts is None else ts) + OFFSET))
        Clock.mktime = staticmethod(lambda tt: float(calendar.timegm(tuple(tt)[:6]) - OFFSET))
        Clock.strftime = staticmethod(lambda fmt, tt=None: _time.strftime(fmt, tt if tt is not None else _time.gmtime(Clock.t + OFFSET)))
        G.time = S.time = Clock
        G.log = S.log = lambda text: rec.add("log", text)
        settings = dict(spec.get("settings", {}))
        wanted = dict(spec.get("wanted", {"daily_cycle": True}))
        battle = dict(spec.get("battle", {"wanted": False, "app": ""}))
        G.setting = lambda key, default: settings.get(key, default)
        G.wanted = lambda key: wanted.get(key, True)
        G.DAILY_FILE = path
        S.PACKAGE = MAIN

        def put_file(content):
            if os.path.exists(path):
                os.remove(path)
            if content is None:
                return
            with open(path, "w") as f:
                f.write(content if isinstance(content, str) else json.dumps(content))

        def raw_file():
            try:
                with open(path) as f:
                    return json.load(f)
            except (OSError, ValueError):
                return None
        put_file(spec.get("file"))
        orig_load, orig_save, orig_reset, orig_finish = G.load_daily, G.save_daily, G.reset_for_game, G.finish_catch
        G.load_daily = lambda: (rec.add("daily_file", raw_file()), orig_load())[1]

        def save(d):
            rec.add("daily_save", json.loads(json.dumps(d)))
            orig_save(d)
        G.save_daily = save

        def reset():
            rec.add("reset", S.PACKAGE)
            orig_reset()
        G.reset_for_game = reset
        packages = list(spec.get("packages", [MAIN]))

        def game_packages():
            rec.add("packages", list(packages))
            return list(packages)
        G.game_packages = game_packages

        def battle_wanted():
            rec.add("battle_wanted", bool(battle["wanted"]))
            return bool(battle["wanted"])
        G.battle_wanted = battle_wanted

        def battle_app():
            rec.add("battle_app", battle["app"] or MAIN)
            return battle["app"] or MAIN
        G.battle_app = battle_app
        G.close_game_completely = lambda: rec.add("close_game", S.PACKAGE)

        def restart():
            Clock.t += spec.get("restart_seconds", 20.0)
            if spec.get("restart_error"):
                rec.add("restart_error", S.PACKAGE, spec["restart_error"])
                raise RuntimeError(spec["restart_error"])
            effects = spec.get("restart_effects", {})
            apply(effects)
            rec.add("restart", S.PACKAGE, effects)
        S.restart_game = restart

        shots = list(spec.get("shots", [0]))
        count = {"shots": 0}

        def take(on_grab=None):
            n = count["shots"]
            count["shots"] += 1
            index = shots[min(n, len(shots) - 1)]
            Clock.t += spec.get("shot_seconds", 0.0)
            if index is None:
                rec.add("shot_error", "the phone did not answer")
                raise RuntimeError("the phone did not answer")
            rec.add("shot", index, "real", False)
            return world.picture(index)
        S.screenshot = take
        S.on_map = lambda img: bool(world.frame(img).get("is_map"))
        steps = list(spec.get("steps", []))

        def apply(effects):
            if "done" in effects:
                G.run_state["done"] = effects["done"]
            if "resume" in effects:
                G.run_state["battle_resume"] = effects["resume"]
            settings.update(effects.get("settings", {}))
            wanted.update(effects.get("wanted", {}))
            battle.update(effects.get("battle", {}))
            if "shots" in effects:
                shots[:] = effects["shots"]
                count["shots"] = 0
            if "file" in effects:
                put_file(effects["file"])

        def step(brain):
            if not steps:
                rec.add("no_step")
                raise Over()
            s = steps.pop(0)
            Clock.t += s.get("dt", 0.0)
            if "raise" in s:
                rec.add("step_error", s["raise"])
                raise RuntimeError(s["raise"])
            apply(s.get("effects", {}))
            rec.add("step", s.get("wait", 5), s.get("effects", {}))
            return s.get("wait", 5)
        G.step = step
        battles = list(spec.get("battles", []))

        def run_script(kind, script, closures):
            for op in script.get("ops", []):
                what = op[0]
                if what in closures:
                    rec.add(kind + "_op", what, bool(closures[what]()) if what != "beat" else closures[what]())
                elif what == "dt":
                    Clock.t += op[1]
                    rec.add(kind + "_op", "dt", op[1])
                elif what == "raise":
                    rec.add(kind + "_op", "raise", op[1])
                    raise RuntimeError(op[1])
                elif what == "effects":
                    apply(op[1])
                    rec.add(kind + "_op", "effects", op[1])
                else:
                    raise ValueError(op)

        def auto_battle(pkg, beat, stop, no_more=None):
            rec.add("auto_battle", pkg)
            script = battles.pop(0) if battles else {}
            run_script("battle", script, {"beat": beat, "stop": stop, "time_up": no_more})
            if "resume" in script:
                G.run_state["battle_resume"] = script["resume"]
            rec.add("battle_result", script.get("fought", 0), script.get("resume"))
            return script.get("fought", 0)
        G.auto_battle = auto_battle
        due = list(spec.get("teams_due", [False]))
        teams = list(spec.get("teams", []))

        def teams_due(pkg):
            answer = due[min(count.setdefault("due", 0), len(due) - 1)]
            count["due"] += 1
            rec.add("teams_due", pkg, bool(answer))
            return answer
        G.teams_due = teams_due

        def teams_refresh(game=None, stop=None):
            rec.add("teams_refresh", game)
            script = teams.pop(0) if teams else {}
            run_script("teams", script, {"stop": stop})
            rec.add("teams_end")
        G.teams_refresh = teams_refresh
        G.start_watchdog = lambda pkg, played, clock, d: (rec.add("watchdog", pkg, "start"), Stopper(rec, pkg))[1]
        brain = Brain(world, rec, spec)

        G.run_state.clear()
        G.run_state.update({"done": False, "waiting_logged": False})
        G.force_start["pending"] = False
        for call in spec["calls"]:
            settings.update(call.get("settings", {}))
            wanted.update(call.get("wanted", {}))
            battle.update(call.get("battle", {}))
            if "file" in call:
                put_file(call["file"])
            if "advance" in call:
                Clock.t += call["advance"]
            if "force" in call:
                G.force_start["pending"] = call["force"]
            if "done" in call:
                G.run_state["done"] = call["done"]
            rec.add("call", call["fn"])
            try:
                fn = call["fn"]
                if fn == "daily_cycle":
                    result = G.daily_cycle(brain)
                elif fn == "run_one_game":
                    result = G.run_one_game(brain, call["pkg"], json.loads(json.dumps(call["d"])))
                elif fn == "finish_catch":
                    result = G.finish_catch(brain, (lambda: rec.add("beat")) if call.get("beat") else None)
                elif fn == "last_slot":
                    result = G.last_slot(call["now"])
                elif fn == "daily_limit":
                    result = G.daily_limit()
                elif fn == "daily_order":
                    result = G.daily_order()
                else:
                    raise ValueError(call)
                rec.add("result", result)
            except Over:
                break
            except Exception as e:  # noqa: BLE001
                rec.add("raised", str(e))
            waiting = G.run_state.get("waiting_logged")
            rec.add("state", {"done": bool(G.run_state.get("done")), "waiting": list(waiting) if isinstance(waiting, tuple) else None,
                              "resume": bool(G.run_state.get("battle_resume"))})
        return rec.events
    finally:
        for n, v in saved.items():
            setattr(G, n, v)
        for n, v in saved_s.items():
            setattr(S, n, v)
        for n, v in saved_time.items():
            if v is None:
                if n in Clock.__dict__:
                    delattr(Clock, n)
            else:
                setattr(Clock, n, v)
        try:
            os.remove(path)
        except OSError:
            pass
        os.rmdir(folder)


# ---------------------------------------------------------------------- the stories

def stories():
    out = []
    frames = [frame([PLAIN], screen=["mapScreen", 0.9], is_map=True), frame([PLAIN], screen=["encounterScreen", 0.9], is_map=False),
              frame([PLAIN], screen=["onbekend", 0.1], is_map=False), frame([PLAIN], screen_error="no model", is_map=False)]

    def story(name, calls, **spec):
        spec.setdefault("frames", frames)
        out.append({"id": name, "spec": dict(spec, calls=calls)})

    S0 = DAY0 + at(8)                                      # today's start time (08:00)
    YDAY = S0 - 86400
    cycle = {"fn": "daily_cycle"}
    DONE = {"wait": 5, "effects": {"done": True}}

    def step(wait=5, dt=0, **effects):
        s = {"wait": wait}
        if dt:
            s["dt"] = dt
        if effects:
            s["effects"] = effects
        return s

    def done(**more):
        return dict(DONE, **more)

    def file_of(done_list, start=S0, slot=S0, **more):
        return dict({"start": start, "done": list(done_list), "slot": slot}, **more)

    # --- last_slot(): the start time of the day, in all its spellings
    texts = [None, "09:30", "9:5", " 7 : 15 ", "\u0660\u0669:\u0663\u0660", "\uff18:\uff13\uff10", "+8:-30", "1_0:00", "24:00", "25:70", "-1:00", "8", "8:30:00", "08:xx",
             "", ":", "abc", "1__0:00", "_1:00", "1_:00", "0:0", "00:00", "10:00", "10:01", "09:59", "123456:00", "-123456:00", "8:", ":30", "1e1:00", "1.5:00",
             "0x8:00", "\u0663:\u0660\u0660", "8 :30", "+0:+0", "0000000000008:0000000000030", "00000000000:00000000000", "+0000000000008:0",
             "-0000000000001:00", "0000000000000000000000:0", "999999999:0", "0:-999999999"]
    calls = []
    for t in texts:
        call = {"fn": "last_slot", "now": DAY0 + at(10)}
        if t is not None:
            call["settings"] = {"daily_time": t}
        calls.append(call)
    story("slot_texts", calls)
    story("slot_other_values", [{"fn": "last_slot", "now": DAY0 + at(10), "settings": {"daily_time": v}} for v in (8, 8.5, True, False, None, [8, 0], {"a": 1}, "08:00")])
    story("slot_moments", [{"fn": "last_slot", "now": DAY0 + moment} for moment in (at(12), at(8), at(8, 0, 1), at(7, 59, 59), at(0), at(23, 59, 59), at(8) - 86400, at(8) + 86400)])
    story("slot_moments_other_time", [{"fn": "last_slot", "now": DAY0 + at(12), "settings": {"daily_time": "00:00"}}, {"fn": "last_slot", "now": DAY0, "settings": {"daily_time": "00:00"}},
                                      {"fn": "last_slot", "now": DAY0 + at(23, 59), "settings": {"daily_time": "23:59"}}, {"fn": "last_slot", "now": DAY0 + at(23, 58, 59)},
                                      {"fn": "last_slot", "now": DAY0 + at(23, 58, 59), "settings": {"daily_time": "23:59"}}])

    # --- daily_limit(): minutes a run may take
    values = [None, 60, "60", 0, 0.5, -5, 1, 1440, 1440.5, 5000, "1e2", " 12 ", "abc", "", None, True, False, [1], {"a": 1}, "inf", "-inf", "Infinity", "-INF", "1_0", ".5", "5.", "\u0661\u0662",
              "+7", "0x10", "1_.5", "1._5", "1,5", "1e", "1e+2", "-0", "7 7", "\t 3\n", 1e300, "1e400", 1439.9999, 1.05, 0.95, 1440.05, 1.0625, 0.9375, 1440.0625]
    calls = []
    for i, v in enumerate(values):
        call = {"fn": "daily_limit"}
        if i != 0:
            call["settings"] = {"daily_max_min": v}
        calls.append(call)
    story("limit_values", calls)

    # --- daily_order(): the apps in the order they are played
    story("order_plain", [{"fn": "daily_order"}], packages=[MAIN, ARES])
    story("order_battle_second", [{"fn": "daily_order", "battle": {"wanted": True, "app": ARES}}, {"fn": "daily_order", "battle": {"app": ""}},
                                  {"fn": "daily_order", "battle": {"app": "no.such.app"}}, {"fn": "daily_order", "battle": {"wanted": False, "app": ARES}}], packages=[MAIN, ARES])
    story("order_three", [{"fn": "daily_order", "battle": {"wanted": True, "app": "b.app"}}, {"fn": "daily_order", "battle": {"app": "c.app"}},
                          {"fn": "daily_order", "battle": {"app": "a.app"}}], packages=["a.app", "b.app", "c.app"])
    story("order_none", [{"fn": "daily_order", "battle": {"wanted": True, "app": ARES}}, {"fn": "daily_order", "battle": {"wanted": False}}], packages=[])

    # --- finish_catch(): the time is up, a catch is finished first
    story("finish_map", [{"fn": "finish_catch", "beat": True}], shots=[0])
    story("finish_not_catching", [{"fn": "finish_catch", "beat": True}], shots=[2])
    story("finish_encounter_then_map", [{"fn": "finish_catch", "beat": True}], shots=[1, 1, 0], steps=[step(3), step(4)])
    story("finish_encounter_no_beat", [{"fn": "finish_catch"}], shots=[1, 1, 0], steps=[step(3), step(4)])
    story("finish_stuck_until_the_end", [{"fn": "finish_catch", "beat": True}], shots=[1, 2], steps=[step(50), step(50), step(50), step(50)])
    story("finish_stuck_on_the_encounter", [{"fn": "finish_catch", "beat": True}], shots=[1], steps=[step(100), step(100), step(100)])
    story("finish_step_error", [{"fn": "finish_catch", "beat": True}], shots=[1, 1, 0], steps=[{"raise": "boom"}, step(2)])
    story("finish_step_takes_long", [{"fn": "finish_catch", "beat": True}], shots=[1, 1, 1], steps=[step(10, dt=200), step(10)])
    story("finish_a_little_time_left", [{"fn": "finish_catch", "beat": True}], shots=[1, 1, 1], steps=[step(10, dt=149.9375), step(10)])
    story("finish_a_little_time_over", [{"fn": "finish_catch", "beat": True}], shots=[1, 1, 1], steps=[step(10, dt=150.0625), step(10)])
    story("finish_step_takes_all", [{"fn": "finish_catch", "beat": True}], shots=[1, 1, 1], steps=[step(10, dt=150), step(10)])
    story("finish_shot_error", [{"fn": "finish_catch", "beat": True}], shots=[None])
    story("finish_shot_error_later", [{"fn": "finish_catch", "beat": True}], shots=[1, None], steps=[step(3)])
    story("finish_screen_error", [{"fn": "finish_catch", "beat": True}], shots=[3])
    story("finish_screen_error_later", [{"fn": "finish_catch", "beat": True}], shots=[1, 3], steps=[step(3)])
    story("finish_slow_shots", [{"fn": "finish_catch", "beat": True}], shots=[1, 1, 1], steps=[step(5), step(5), step(5)], shot_seconds=100.0)
    story("finish_slow_screen", [{"fn": "finish_catch", "beat": True}], shots=[1], steps=[step(5), step(5), step(5), step(5)], screen_seconds=60.0)
    story("finish_over", [{"fn": "finish_catch", "beat": True}], shots=[1], steps=[step(5)])

    # --- daily_cycle(): a run, from the start time to the end
    story("run_one_game", [cycle], file=None, steps=[step(5, dt=30), step(5, dt=4000), done(dt=1)])
    story("run_two_games", [cycle, dict(cycle, advance=100), dict(cycle, advance=100), dict(cycle, advance=100)], file=None, packages=[MAIN, ARES],
          steps=[step(5), done(), step(5, dt=7), done()])
    story("run_three_games_the_last_is_first_in_battles", [cycle, cycle, cycle, cycle], file=None, packages=[MAIN, ARES, "c.app"], battle={"wanted": True, "app": "c.app"},
          battles=[{"fought": 2, "ops": [["beat"], ["stop"], ["time_up"], ["dt", 30], ["beat"]]}, {}, {"fought": 1}], steps=[done(), done(), done()])
    story("run_over_in_the_loop", [cycle], file=None, steps=[step(5)])
    story("run_nothing_to_play", [cycle, cycle], file=None, packages=[])

    # the start time of the day
    story("start_exactly_now", [cycle], at=at(8), file=file_of([MAIN], start=YDAY, slot=YDAY), steps=[done()])
    story("start_one_second_late", [cycle], at=at(8, 0, 1), file=file_of([MAIN], start=YDAY, slot=YDAY), steps=[done()])
    story("start_one_second_early", [cycle], at=at(7, 59, 59), file=file_of([MAIN], start=YDAY, slot=YDAY), steps=[done()])
    story("start_used_up_by_one_second", [cycle], at=at(8), file=file_of([MAIN], start=YDAY, slot=S0 - 1), steps=[done()])
    story("start_already_used", [cycle, cycle], at=at(8), file=file_of([MAIN]), steps=[done()])
    story("start_used_by_the_run_before", [cycle], at=at(9), file=file_of([MAIN], start=S0 + 60), steps=[done()])
    story("start_continues_a_run", [cycle], at=at(10), file=file_of([], start=S0 + 60), steps=[step(5), done()])
    story("start_continues_the_second_game", [cycle], at=at(10), packages=[MAIN, ARES], file=file_of([MAIN], start=S0 + 60), steps=[done()])
    story("start_passes_during_the_restart", [cycle], at=at(7, 59, 50), file=file_of([], start=YDAY + 30, slot=YDAY), steps=[step(5), done()])
    story("start_passes_during_the_run", [cycle], at=at(7, 59, 50), file=file_of([], start=YDAY + 30, slot=YDAY), restart_seconds=1.0,
          steps=[step(5, dt=4), step(5, dt=4), step(5, dt=4), done()])
    story("start_other_time", [cycle, cycle], at=at(8, 30), settings={"daily_time": "09:00"}, file=None, steps=[done()])
    story("start_other_time_passed", [cycle], at=at(9, 0, 1), settings={"daily_time": "09:00"}, file=file_of([MAIN], start=YDAY, slot=YDAY), steps=[done()])
    story("start_time_changed", [cycle, dict(cycle, settings={"daily_time": "07:00"}), dict(cycle, settings={"daily_time": "08:30"}),
                                  dict(cycle, settings={"daily_time": "bad"}, advance=3600)], at=at(8), file=file_of([MAIN]), steps=[done(), done()])

    # the file of the older versions (no start time that was used up)
    story("old_file_used_up", [cycle], at=at(10), file={"start": S0 + 3600, "done": [MAIN]})
    story("old_file_yesterday", [cycle], at=at(10), file={"start": YDAY + 3600, "done": [MAIN]}, steps=[done()])
    story("old_file_without_start", [cycle], at=at(10), file={"start": 0, "done": []}, steps=[done()])
    story("old_file_continues", [cycle], at=at(9), file={"start": S0 + 60, "done": []}, steps=[step(5), done()])
    story("old_file_exactly_the_slot", [cycle], at=at(10), file={"start": S0, "done": [MAIN]})
    story("old_file_one_second_before_the_slot", [cycle], at=at(10), file={"start": S0 - 1, "done": [MAIN]}, steps=[done()])
    story("file_not_json", [cycle], file="this is not json", steps=[done()])
    story("file_empty", [cycle], file="", steps=[done()])
    story("file_without_done", [cycle], file={"start": S0, "slot": S0})
    story("file_without_done_no_apps", [cycle], file={"start": S0, "slot": S0}, packages=[])
    story("file_without_start", [cycle, cycle], at=at(10), file={"done": [MAIN], "slot": S0})
    story("file_without_start_and_slot", [cycle], at=at(10), file={"done": [MAIN]}, steps=[done()])
    story("file_with_a_start_time_of_text", [cycle], at=at(10), file={"start": S0, "slot": S0, "done": [MAIN, ARES]}, packages=[MAIN, ARES])
    story("file_slot_is_an_integer", [cycle, cycle], at=at(10), file={"start": int(S0), "slot": int(S0), "done": [MAIN]})

    # the Start button and the start of the bot
    story("force_button", [dict(cycle, force="button")], at=at(10), file=file_of([MAIN]), steps=[done()])
    story("force_button_while_running", [dict(cycle, force="button")], at=at(10), packages=[MAIN, ARES], file=file_of([MAIN]), steps=[done(), done()])
    story("force_start_continues", [dict(cycle, force="start")], at=at(10), file=file_of([]), steps=[step(5), done()])
    story("force_start_all_done", [dict(cycle, force="start")], at=at(10), file=file_of([MAIN]), steps=[done()])
    story("force_other_word", [dict(cycle, force="whatever")], at=at(10), file=file_of([], start=S0 + 60), steps=[done()])
    story("force_other_word_all_done", [dict(cycle, force="whatever")], at=at(10), file=file_of([MAIN]), steps=[done()])
    story("force_no_apps", [dict(cycle, force="button"), cycle], at=at(10), file=file_of([]), packages=[])
    story("force_resets_what_was_said", [cycle, dict(cycle, force="button"), cycle], at=at(10), file=file_of([MAIN]), steps=[done()])
    story("force_battle_order", [dict(cycle, force="button")], at=at(10), file=file_of([MAIN, ARES]), packages=[MAIN, ARES], battle={"wanted": True, "app": ARES},
          steps=[done(), done()])

    # waiting for the next run
    story("waiting_is_said_once", [cycle, cycle, dict(cycle, advance=5000), cycle], at=at(10), file=file_of([MAIN]))
    story("waiting_start_time_changes", [cycle, dict(cycle, settings={"daily_time": "09:00"}), dict(cycle, settings={"daily_time": "09:00"}),
                                         dict(cycle, settings={"daily_time": "7:15"})], at=at(10), file=file_of([MAIN], slot=S0 + 3600))
    story("waiting_file_changes", [cycle, dict(cycle, file=file_of([MAIN], start=S0 + 5)), dict(cycle, file=file_of([MAIN], start=S0 + 5)),
                                   dict(cycle, file=file_of([MAIN], start=0))], at=at(10), file=file_of([MAIN]))
    story("waiting_no_start", [cycle, cycle], at=at(10), file=file_of([], start=0), packages=[])
    story("waiting_start_is_text", [cycle], at=at(10), file=file_of([MAIN], start="x"))
    story("waiting_next_run_text", [dict(cycle, settings={"daily_time": "23:59"}), dict(cycle, settings={"daily_time": "00:00"})], at=at(10), file=file_of([MAIN], slot=S0 + 86400),
          packages=[MAIN])
    story("waiting_after_a_new_run", [cycle, cycle, dict(cycle, advance=86400), cycle, cycle], at=at(9), file=file_of([MAIN]), steps=[done()])
    story("waiting_state_done_stays", [dict(cycle, done=True), cycle], at=at(10), file=file_of([MAIN]))
    story("waiting_state_resume_stays", [dict(cycle, done=True, force=None)], at=at(10), file=file_of([MAIN]))

    # one game
    story("game_battles_first", [cycle], file=None, battle={"wanted": True, "app": MAIN}, battles=[{"fought": 3, "ops": [["beat"], ["stop"], ["time_up"], ["dt", 12], ["beat"], ["stop"]], "resume": False}],
          steps=[done()])
    story("game_battles_then_teams", [cycle], file=None, battle={"wanted": True, "app": MAIN}, battles=[{"fought": 1, "ops": [["dt", 3], ["beat"]]}], teams_due=[True],
          teams=[{"ops": [["stop"], ["dt", 4], ["stop"]]}], steps=[done()])
    story("game_battle_error", [cycle], file=None, battle={"wanted": True, "app": MAIN}, battles=[{"ops": [["dt", 3], ["raise", "no battle"]]}], steps=[done()])
    story("game_teams_error", [cycle], file=None, teams_due=[True], teams=[{"ops": [["dt", 2], ["raise", "no teams"]]}], steps=[done()])
    story("game_battles_finish_the_run", [cycle], file=None, battle={"wanted": True, "app": MAIN}, battles=[{"ops": [["effects", {"done": True}], ["stop"]]}], teams_due=[True])
    story("game_battles_are_switched_off", [cycle], file=None, battle={"wanted": True, "app": MAIN},
          battles=[{"ops": [["stop"], ["effects", {"wanted": {"daily_cycle": False}}], ["stop"]]}], teams_due=[True], teams=[{"ops": [["stop"]]}])
    story("game_teams_see_the_time_up", [cycle], file=None, settings={"daily_max_min": 1}, teams_due=[True], teams=[{"ops": [["stop"], ["dt", 39], ["stop"], ["dt", 1], ["stop"], ["dt", 1], ["stop"]]}],
          steps=[step(5)])
    story("game_battles_see_the_time_up", [cycle], file=None, settings={"daily_max_min": 1}, battle={"wanted": True, "app": MAIN},
          battles=[{"ops": [["time_up"], ["dt", 39], ["time_up"], ["dt", 1], ["time_up"], ["dt", 1], ["time_up"]], "fought": 1}], steps=[step(5)])
    story("game_teams_not_after_done", [cycle], file=None, teams_due=[True], battle={"wanted": True, "app": MAIN}, battles=[{"ops": [["effects", {"done": True}]]}])
    story("game_teams_take_long", [cycle], file=None, teams_due=[True], teams=[{"ops": [["dt", 1800]]}], steps=[done()])
    story("game_battles_take_long", [cycle], file=None, battle={"wanted": True, "app": MAIN}, battles=[{"fought": 1, "ops": [["dt", 1800]]}], steps=[done()])
    story("slot_at_the_dawn_of_time", [cycle], at=-DAY0 + at(5), file=None, steps=[done()])
    story("game_teams_every_game", [cycle, cycle], file=None, packages=[MAIN, ARES], teams_due=[True, False], teams=[{}], steps=[done(), done()])
    story("game_switched_off_in_the_loop", [cycle, dict(cycle, wanted={"daily_cycle": True})], file=None,
          steps=[step(5, dt=10), step(5, dt=10, wanted={"daily_cycle": False}), step(5, dt=10), done()])
    story("game_switched_off_before_the_loop", [cycle], file=None, wanted={"daily_cycle": False}, steps=[done()])
    story("game_step_error", [cycle], file=None, steps=[{"raise": "boom", "dt": 2}, step(5, dt=3), done()])
    story("game_restart_error", [cycle], file=None, restart_error="adb offline")
    story("game_restart_error_second_game", [cycle, cycle], file=None, packages=[MAIN, ARES], steps=[done()], restart_error=None)
    story("game_done_during_the_restart", [cycle], file=None, battle={"wanted": True, "app": MAIN}, teams_due=[True], restart_effects={"done": True})
    story("game_slow_restart", [cycle], file=None, restart_seconds=100.5, steps=[done()])
    story("game_battle_app_missing", [cycle, cycle, cycle], file=None, packages=[MAIN, ARES], battle={"wanted": True, "app": "no.such.app"}, steps=[done(), done()])
    story("game_battle_app_missing_second", [cycle, cycle], file=None, packages=[MAIN, ARES], battle={"wanted": False, "app": "no.such.app"}, steps=[done(), done()])
    story("game_battle_app_there", [cycle], file=None, packages=[MAIN, ARES], battle={"wanted": True, "app": ARES}, steps=[done()])
    story("game_played_is_kept", [cycle, dict(cycle, advance=60)], file=None, packages=[MAIN, ARES], steps=[step(5, dt=17), done(dt=3), step(5, dt=9), done(dt=1)])

    # played: the starting line
    def direct(name, d, **spec):
        story(name, [{"fn": "run_one_game", "pkg": spec.pop("pkg", MAIN), "d": d}], steps=spec.pop("steps", [done()]), **spec)
    direct("played_none", {"start": S0, "done": [], "slot": S0})
    direct("played_zero", {"start": S0, "done": [], "slot": S0, "played": {MAIN: 0}})
    direct("played_half_a_minute", {"start": S0, "done": [], "slot": S0, "played": {MAIN: 30.0}})
    direct("played_one_and_a_half_minutes", {"start": S0, "done": [], "slot": S0, "played": {MAIN: 90.0}})
    direct("played_other_app", {"start": S0, "done": [MAIN], "slot": S0, "played": {MAIN: 1830.0}}, pkg=ARES)
    direct("played_two_apps", {"start": S0, "done": [], "slot": S0, "played": {MAIN: 100.0, ARES: 50.0}}, pkg=ARES)
    direct("played_without_slot", {"start": S0, "done": []})
    direct("played_slot_is_ahead", {"start": S0, "done": [], "slot": S0 + 86400 * 3}, at=at(9))
    direct("played_nothing_else", {})

    # the time of the run
    story("limit_in_the_loop", [cycle, cycle], file=None, settings={"daily_max_min": 1}, packages=[MAIN, ARES], steps=[step(40), step(1), step(5)])
    story("limit_with_a_catch", [cycle], file=None, settings={"daily_max_min": 1}, shots=[1, 1, 0], steps=[step(40), step(1), step(3), step(2)])
    story("limit_not_on_the_map", [cycle], file=None, settings={"daily_max_min": 1}, shots=[2], steps=[step(40), step(1)])
    story("limit_catch_runs_out", [cycle], file=None, settings={"daily_max_min": 1}, shots=[1], steps=[step(40), step(1), step(100), step(100)])
    story("limit_shot_error", [cycle], file=None, settings={"daily_max_min": 1}, shots=[1, None], steps=[step(41)])
    story("limit_changes_in_the_run", [cycle], file=None, steps=[step(30), step(30, settings={"daily_max_min": 1}), step(5), step(5)])
    story("limit_is_over_at_the_start", [cycle, cycle], at=at(8), file=file_of([], played={MAIN: 3600.0}), settings={"daily_max_min": 30}, packages=[MAIN, ARES])
    story("limit_is_reached_at_the_start", [cycle], at=at(8), file=file_of([], played={MAIN: 1800.0}), settings={"daily_max_min": 30}, shots=[0], steps=[step(5)])
    story("limit_is_just_over_at_the_start", [cycle], at=at(8), file=file_of([], played={MAIN: 1800.5}), settings={"daily_max_min": 30}, packages=[MAIN, ARES])
    story("limit_counts_all_apps", [cycle, cycle], at=at(8), file=file_of([MAIN], played={MAIN: 1000.0}), settings={"daily_max_min": 20}, packages=[MAIN, ARES],
          steps=[step(5, dt=170), step(5), step(5)])
    story("limit_counts_all_apps_at_the_start", [cycle], at=at(8), file=file_of([MAIN], played={MAIN: 1200.5}), settings={"daily_max_min": 20}, packages=[MAIN, ARES])
    for name, text in (("limit_is_nan", "nan"), ("limit_is_nan_in_capitals", "NaN"), ("limit_is_nan_with_a_sign", "-nan"), ("limit_is_nan_with_a_plus", " +NAN ")):
        story(name, [cycle], file=None, settings={"daily_max_min": text}, steps=[step(1800), step(1800), done()])
    story("limit_time_up_in_the_file", [cycle], at=at(8), file=file_of([MAIN], time_up=True), packages=[MAIN, ARES], steps=[done()])
    story("limit_time_up_one_in_the_file", [cycle], at=at(8), file=file_of([MAIN], time_up=1), packages=[MAIN, ARES], steps=[done()])
    story("limit_time_up_zero_in_the_file", [cycle], at=at(8), file=file_of([MAIN], time_up=0), packages=[MAIN, ARES], steps=[done()])
    story("limit_time_up_text_in_the_file", [cycle], at=at(8), file=file_of([MAIN], time_up="yes"), packages=[MAIN, ARES], steps=[done()])
    story("limit_time_up_empty_text_in_the_file", [cycle], at=at(8), file=file_of([MAIN], time_up=""), packages=[MAIN, ARES], steps=[done()])
    story("limit_time_up_list_in_the_file", [cycle], at=at(8), file=file_of([MAIN], time_up=[0]), packages=[MAIN, ARES], steps=[done()])
    story("limit_time_up_empty_list_in_the_file", [cycle], at=at(8), file=file_of([MAIN], time_up=[]), packages=[MAIN, ARES], steps=[done()])
    story("limit_time_up_object_in_the_file", [cycle], at=at(8), file=file_of([MAIN], time_up={"a": 1}), packages=[MAIN, ARES], steps=[done()])
    story("limit_time_up_empty_object_in_the_file", [cycle], at=at(8), file=file_of([MAIN], time_up={}), packages=[MAIN, ARES], steps=[done()])
    story("limit_time_up_null_in_the_file", [cycle], at=at(8), file=file_of([MAIN], time_up=None), packages=[MAIN, ARES], steps=[done()])
    story("limit_time_up_fraction_in_the_file", [cycle], at=at(8), file=file_of([MAIN], time_up=0.5), packages=[MAIN, ARES], steps=[done()])

    # saving and saying how far it is
    story("save_not_after_exactly_a_minute", [cycle], file=None, restart_seconds=0.0, steps=[step(60), step(60), step(60), done()])
    story("save_after_a_bit_more_than_a_minute", [cycle], file=None, restart_seconds=0.0, steps=[step(60.5), step(60.5), done()])
    story("save_every_five_seconds", [cycle], file=None, restart_seconds=0.0, steps=[step(5)] * 26 + [done()])
    story("report_exactly_half_an_hour", [cycle], file=None, restart_seconds=0.0, steps=[step(1800), step(5), step(1800), done()])
    story("report_just_before_half_an_hour", [cycle], file=None, restart_seconds=0.0, steps=[step(1799.5), step(0.5), step(1799.5), step(0.25), step(5), done()])
    story("report_the_sum_of_all_apps", [cycle], at=at(8), file=file_of([MAIN], played={MAIN: 20.0}), packages=[MAIN, ARES], restart_seconds=10.0, steps=[step(1800), done()])
    story("report_rounds_half_to_even", [cycle], at=at(8), file=file_of([MAIN], played={MAIN: 30.0}), packages=[MAIN, ARES], restart_seconds=0.0, steps=[step(1800), done()])
    story("report_again_later", [cycle], file=None, restart_seconds=0.0, steps=[step(1800), step(1800), step(1800), step(1800), step(1800), done()])

    # the battles go on after a Pokémon of a reward was caught
    story("resume_once", [cycle], file=None, battle={"wanted": True, "app": MAIN}, shots=[0], battles=[{"fought": 1, "resume": True}, {"fought": 2, "ops": [["dt", 4], ["beat"]]}],
          steps=[step(5), step(5, dt=2), done()])
    story("resume_after_a_step", [cycle], file=None, shots=[0], battles=[{}, {"ops": [["dt", 4], ["beat"]]}], steps=[step(5, resume=True), step(5), done()])
    story("resume_not_on_the_map", [cycle], file=None, battle={"wanted": True, "app": MAIN}, battles=[{"resume": True}, {}], shots=[1],
          steps=[step(5), step(5), step(5, shots=[0]), done()])
    story("resume_screenshot_fails", [cycle], file=None, battle={"wanted": True, "app": MAIN}, battles=[{"resume": True}, {}], shots=[None],
          steps=[step(5), step(5, shots=[0]), done()])
    story("resume_four_times", [cycle], file=None, battle={"wanted": True, "app": MAIN}, shots=[0], battles=[{}, {"resume": True}, {"resume": True}, {"resume": True}, {}],
          steps=[step(5, resume=True), step(5, resume=True), step(5, resume=True), step(5, resume=True), step(5), done()])
    story("resume_three_times", [cycle], file=None, shots=[0], steps=[step(5, resume=True), step(5, resume=True), step(5, resume=True), done()])
    story("resume_and_the_battles_fail", [cycle], file=None, shots=[0], battles=[{}, {"ops": [["dt", 2], ["raise", "broken"]]}], steps=[step(5, resume=True), done()])
    story("resume_the_step_fails", [cycle], file=None, shots=[0], steps=[step(5, resume=True), {"raise": "boom"}, done()])
    story("resume_ends_the_run", [cycle], file=None, shots=[0], battles=[{"ops": [["effects", {"done": True}]]}], steps=[step(5, resume=True)])
    story("resume_in_the_loop_not_set", [cycle], file=None, shots=[0], steps=[step(5), done()])
    story("resume_flag_stays_after_the_run", [cycle], file=None, shots=[1], steps=[step(5, resume=True), done()])
    story("resume_time_goes_on", [cycle], file=None, settings={"daily_max_min": 1}, shots=[0], battles=[{}, {"ops": [["dt", 50]]}], steps=[step(5, resume=True), step(5), step(5)])

    return out


def all_stories():
    return stories()


def capture():
    return {"start": DAY0, "cases": [dict(c, events=record(c["spec"])) for c in all_stories()]}


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
