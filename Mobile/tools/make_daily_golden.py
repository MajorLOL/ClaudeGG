#!/usr/bin/env python3
"""Makes tests/fixtures/daily_golden.json.qz (JSON, packed the way qCompress() of Qt does: the length, then zlib): what gamebot.py does in the daily
run - daily_cycle() with run_one_game(), finish_catch(), daily_order(), daily_limit() and last_slot() - the file that the C++ port,
SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoDaily.cpp, is tested against.

    python3 tools/make_daily_golden.py            writes the file
    python3 tools/make_daily_golden.py --check    says whether the file is what the code does now

The file is a list of stories.  A story calls daily_cycle() a few times, the way the loop of the bot does: after each call the clock goes on by
what it returned.  The clock is a fake one (time.time() and time.monotonic() are the same number, the local time zone is UTC); it only moves with
the sleeps, the steps that take time and the waits between the calls.  The rest of the bot is pretend too, and the story says what it does:
    settings      the file of the web interface (setting(), wanted()); 'off_at': from this time on daily_cycle is switched off
    packages      the Pokémon GO apps on the phone (game_packages())
    file          what ~/gamebot_daily.json holds at the start (None: there is none)
    force         the Start button was pressed ('button'), or the bot was started ('start'); force_call: before that call (0: the first)
    steps         what each step() of the normal bot does: the wait it returns, 'takes' (the time the step itself takes), 'raise' (it fails
                  with that text), 'done' (it sets run_state['done']: the storage and the bag are full)
    screens       what the screen classifier says while a catch is finished (finish_catch()); 'raise': it fails
    restart_fail  restart_game() fails with this text
Not ported, so not in the stories: the battles and the weekly teams of a run (they are off in the C++ port, as here), the watchdog thread (it
ends the Python process; the C++ program has its own Stop), and the Pokémon of a reward that sends the run back to the battles.
What the code is GIVEN, in the EVENTS: the packages, the wait of a step (or what it raised), what a screen is.  What it DOES: log, sleep, save (the
whole file as it is written), reset (reset_for_game(), with the app that is played), restart, close (close_game_completely()), step, shot
(a look at the screen), and after every call of daily_cycle: result, or raised.
"""
import argparse
import copy
import json
import os
import struct
import sys
import time as real_time
import types
import zlib

os.environ["TZ"] = "UTC"
real_time.tzset()

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import gamebot as G  # noqa: E402
import spin_stop as S  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "tests", "fixtures", "daily_golden.json.qz")
START = 1795417200.0                       # 2026-11-23 07:00 UTC: an hour before the daily time of 08:00


class Clock:
    t = START


class Story:
    def __init__(self, spec):
        self.spec = spec
        self.events = []
        self.steps = list(spec.get("steps", []))
        self.screens = list(spec.get("screens", []))
        self.file = copy.deepcopy(spec.get("file"))
        self.settings = dict(spec.get("settings", {}))

    def add(self, kind, *rest):
        self.events.append([kind, Clock.t] + list(rest))

    # ---- the clock
    def time(self):
        return Clock.t

    def sleep(self, seconds):
        self.add("sleep", seconds)
        Clock.t += seconds

    # ---- the file of the web interface
    def control(self):
        off = self.spec.get("off_at")
        s = dict(self.settings)
        if off is not None and Clock.t >= off:
            s["daily_cycle"] = False
        return s

    def setting(self, key, default):
        return self.control().get(key, default)

    def wanted(self, key):
        return bool(self.control().get(key, True))

    # ---- the daily file
    def load_daily(self):
        if self.file is None:
            return {"start": 0, "done": []}
        return copy.deepcopy(self.file)

    def save_daily(self, d):
        self.file = copy.deepcopy(d)
        self.add("save", copy.deepcopy(d))

    # ---- the phone and the rest of the bot
    def game_packages(self):
        pkgs = list(self.spec.get("packages", [G.MAIN_PACKAGE]))
        self.add("packages", pkgs)
        return pkgs

    def reset_for_game(self):
        self.add("reset", S.PACKAGE)
        G.run_state["done"] = False

    def restart_game(self):
        self.add("restart")
        if self.spec.get("restart_fail"):
            raise RuntimeError(self.spec["restart_fail"])

    def close_game_completely(self):
        self.add("close")

    def step(self, brain):
        s = self.steps.pop(0) if self.steps else {"wait": 5, "takes": 55}
        if isinstance(s, (int, float)):
            s = {"wait": s}
        if "raise" in s:
            self.add("step", None, s["raise"], s.get("takes", 0))
            Clock.t += s.get("takes", 0)
            raise RuntimeError(s["raise"])
        self.add("step", s["wait"], None, s.get("takes", 0), bool(s.get("done")))
        Clock.t += s.get("takes", 0)
        if s.get("done"):
            G.run_state["done"] = True
        return s["wait"]

    def screen(self, img):
        s = self.screens.pop(0) if self.screens else "mapScreen"
        if s == "raise":
            self.add("shot", None)
            raise RuntimeError("the phone did not answer")
        self.add("shot", s)
        return s, 0.9


class Brain:
    def __init__(self, story):
        self.story = story

    def screen(self, img):
        return self.story.screen(img)


def record(spec):
    Clock.t = START
    st = Story(spec)
    fake_time = types.SimpleNamespace(
        time=st.time, monotonic=st.time, sleep=st.sleep,
        localtime=real_time.localtime, mktime=real_time.mktime, strftime=real_time.strftime,
    )
    saved = {}
    patch = {
        "time": fake_time, "setting": st.setting, "wanted": st.wanted, "load_daily": st.load_daily, "save_daily": st.save_daily,
        "game_packages": st.game_packages, "reset_for_game": st.reset_for_game, "close_game_completely": st.close_game_completely,
        "step": st.step, "log": lambda text: st.add("log", text), "battle_wanted": lambda: False, "teams_due": lambda game: False,
        "auto_battle": lambda *a, **k: 0, "start_watchdog": lambda *a, **k: types.SimpleNamespace(set=lambda: None),
    }
    for k, v in patch.items():
        saved[k] = getattr(G, k)
        setattr(G, k, v)
    s_saved = {"restart_game": S.restart_game, "screenshot": S.screenshot, "PACKAGE": S.PACKAGE}
    S.restart_game = st.restart_game
    S.screenshot = lambda: None
    G.run_state.clear()
    G.run_state.update({"done": False, "waiting_logged": None})
    G.force_start["pending"] = spec.get("force") if not spec.get("force_call") else None
    brain = Brain(st)
    try:
        for n in range(spec.get("calls", 1)):
            if spec.get("force_call") and n == spec["force_call"]:
                G.force_start["pending"] = spec.get("force")
            try:
                r = G.daily_cycle(brain)
                st.add("result", r)
                Clock.t += r
            except Exception as e:  # noqa: BLE001
                st.add("raised", str(e))
                Clock.t += 10
    finally:
        for k, v in saved.items():
            setattr(G, k, v)
        S.restart_game, S.screenshot, S.PACKAGE = s_saved["restart_game"], s_saved["screenshot"], s_saved["PACKAGE"]
    return st.events


PLAY = "com.nianticlabs.pokemongo"
GALAXY = "com.nianticlabs.pokemongo.ares"
DAY = 86400.0
EIGHT = START + 3600                         # 08:00 that day


def stories():
    out = []

    def add(name, **spec):
        spec.setdefault("calls", 1)
        out.append({"id": name, "spec": spec})

    # waiting for the time of the run, then it starts
    add("waiting_before_the_time", calls=2, file={"start": START - DAY + 3600 - 10, "done": [PLAY], "slot": START - DAY + 3600})
    add("no_file_starts_at_once", calls=1)
    add("the_time_comes", calls=3, file={"start": START - DAY + 3600, "done": [PLAY], "slot": START - DAY + 3600},
        settings={"daily_time": "07:01", "daily_max_min": 1}, steps=[{"wait": 5, "takes": 20}] * 8)
    add("start_button", force="button", file={"start": START - 50, "done": [], "slot": START - DAY}, settings={"daily_max_min": 1},
        steps=[{"wait": 2, "takes": 10}] * 10)
    add("bot_started_run_unfinished_goes_on", force="start", file={"start": START - 500, "done": [], "slot": START - DAY + 3600,
        "played": {PLAY: 30.0}}, settings={"daily_max_min": 1}, steps=[{"wait": 5, "takes": 10}] * 10)
    add("bot_started_run_finished_starts_again", force="start", file={"start": START - 500, "done": [PLAY], "slot": START - DAY + 3600},
        settings={"daily_max_min": 1}, steps=[{"wait": 5, "takes": 10}] * 10)
    add("two_apps", calls=3, packages=[GALAXY, PLAY], settings={"daily_max_min": 2},
        steps=[{"wait": 10, "takes": 15}] * 30)
    add("time_up_in_the_first_app", calls=3, packages=[PLAY, GALAXY], settings={"daily_max_min": 1},
        steps=[{"wait": 10, "takes": 15}] * 30)
    add("time_up_finishing_a_catch", settings={"daily_max_min": 1}, steps=[{"wait": 20, "takes": 15}] * 3 + [{"wait": 3, "takes": 2}] * 5,
        screens=["encounterScreen", "encounterScreen", "encounterScreen", "mapScreen"])
    add("time_up_catch_runs_long", settings={"daily_max_min": 1}, steps=[{"wait": 20, "takes": 15}] * 3 + [{"wait": 40, "takes": 30}] * 9,
        screens=["encounterScreen"] * 20)
    add("time_up_not_catching", settings={"daily_max_min": 1}, steps=[{"wait": 20, "takes": 15}] * 3, screens=["questScreen"])
    add("time_up_screen_fails", settings={"daily_max_min": 1}, steps=[{"wait": 20, "takes": 15}] * 3, screens=["raise"])
    add("time_up_catch_then_screen_fails", settings={"daily_max_min": 1}, steps=[{"wait": 20, "takes": 15}] * 3 + [{"raise": "no ball"}],
        screens=["encounterScreen", "raise"])
    add("time_up_catch_step_fails", settings={"daily_max_min": 1}, steps=[{"wait": 20, "takes": 15}] * 3 + [{"raise": "tap lost"}] * 3,
        screens=["encounterScreen", "encounterScreen", "otherScreen"])
    add("time_up_at_the_start", file={"start": START - 100, "done": [], "slot": START - DAY + 3600, "played": {PLAY: 100.0}},
        force="start", settings={"daily_max_min": 1})
    add("step_fails", settings={"daily_max_min": 1}, steps=[{"raise": "the phone is gone"}, {"wait": 5, "takes": 30}] + [{"wait": 5, "takes": 15}] * 10)
    add("bag_and_storage_full", calls=2, settings={"daily_max_min": 5}, steps=[{"wait": 5, "takes": 15}, {"wait": 60, "done": True}])
    add("switched_off_during_the_run", calls=2, settings={"daily_max_min": 10}, off_at=START + 120, steps=[{"wait": 30, "takes": 20}] * 10)
    add("saved_every_minute_and_told_every_half_hour", settings={"daily_max_min": 70}, steps=[{"wait": 50, "takes": 70}] * 60)
    add("restart_fails", settings={"daily_max_min": 1}, restart_fail="the agent did not answer")
    add("limit_text", settings={"daily_max_min": "2"}, steps=[{"wait": 30, "takes": 30}] * 6)
    add("limit_bad_text", settings={"daily_max_min": "two hours"}, off_at=START + 200, steps=[{"wait": 30, "takes": 30}] * 9)
    add("limit_none", settings={"daily_max_min": None}, off_at=START + 200, steps=[{"wait": 30, "takes": 30}] * 9)
    add("limit_list", settings={"daily_max_min": [5]}, off_at=START + 200, steps=[{"wait": 30, "takes": 30}] * 9)
    add("limit_text_with_spaces", settings={"daily_max_min": " 1.5 "}, steps=[{"wait": 30, "takes": 30}] * 9)
    add("limit_too_small", settings={"daily_max_min": 0}, steps=[{"wait": 30, "takes": 30}] * 6)
    add("limit_too_big", settings={"daily_max_min": 99999}, off_at=START + 200, steps=[{"wait": 30, "takes": 30}] * 9)
    add("limit_true", settings={"daily_max_min": True}, steps=[{"wait": 30, "takes": 30}] * 6)
    add("daily_time_bad", settings={"daily_time": "8.00"}, file={"start": START - 10, "done": [PLAY], "slot": START - DAY + 3600}, calls=2)
    add("daily_time_three_parts", settings={"daily_time": "7:30:00"}, file={"start": START - 10, "done": [PLAY], "slot": START - DAY + 3600})
    add("daily_time_spaces", settings={"daily_time": " 6 : 30 ", "daily_max_min": 1}, file={"start": START - 10, "done": [PLAY], "slot": START - DAY + 3600})
    add("daily_time_number", settings={"daily_time": 7}, file={"start": START - 10, "done": [PLAY], "slot": START - DAY + 3600})
    add("old_file_without_slot", file={"start": START - 3600 * 5, "done": [PLAY]})
    add("old_file_without_start", settings={"daily_max_min": 1}, file={"done": [PLAY]})
    add("old_file_start_zero", settings={"daily_max_min": 1}, file={"start": 0, "done": [PLAY]})
    add("file_without_done", file={"start": START - 10, "slot": START - DAY + 3600})
    add("file_without_done_new_day", settings={"daily_max_min": 1}, file={"start": START - DAY, "slot": START - DAY * 2})
    add("waiting_logged_once", calls=4, file={"start": START - 10, "done": [PLAY], "slot": START - DAY + 3600})
    add("waiting_complete_then_time_changes", calls=3, file={"start": START - 10, "done": [PLAY], "slot": START - DAY + 3600},
        settings={"daily_time": "09:00", "daily_max_min": 1})
    add("waiting_never_ran", calls=1, file={"start": 0, "done": [PLAY], "slot": START})
    add("time_passes_during_the_run", file={"start": START - 50, "done": [], "slot": START - DAY + 3600}, force="start",
        settings={"daily_max_min": 120}, steps=[{"wait": 60, "takes": 60}] * 80)
    add("three_apps_one_done", calls=3, packages=[PLAY, GALAXY, "com.nianticlabs.pokemongo.beta"],
        file={"start": START - 10, "done": [GALAXY], "slot": START - DAY + 3600}, force="start", settings={"daily_max_min": 1},
        steps=[{"wait": 10, "takes": 20}] * 20)
    add("played_from_before_counts", force="start", file={"start": START - 100, "done": [], "slot": START - DAY + 3600,
        "played": {GALAXY: 40.0}}, packages=[PLAY, GALAXY], settings={"daily_max_min": 1}, steps=[{"wait": 10, "takes": 10}] * 10)
    add("played_zero_start_message", force="start", file={"start": START - 100, "done": [], "slot": START - DAY + 3600,
        "played": {GALAXY: 0.0}}, packages=[PLAY, GALAXY], settings={"daily_max_min": 1}, steps=[{"wait": 10, "takes": 10}] * 10)
    add("off_before_the_start", calls=2, off_at=START, file={"start": START - 100, "done": [], "slot": START - DAY + 3600}, force="start")
    add("done_after_time_up_check", settings={"daily_max_min": 1}, steps=[{"wait": 5, "takes": 59}, {"wait": 5, "done": True}])
    add("many_days", calls=8, settings={"daily_max_min": 1, "daily_time": "07:30"}, steps=[{"wait": 300, "takes": 30}] * 40)
    add("saved_after_61_s", settings={"daily_max_min": 3}, steps=[{"wait": 30, "takes": 31}] * 8)
    add("slot_just_before", file={"start": START - 10, "done": [PLAY], "slot": START - DAY + 3600 + DAY - 3600 - 3600 - 0.5},
        settings={"daily_time": "06:00", "daily_max_min": 1})
    add("played_under_a_second", force="start", file={"start": START - 100, "done": [], "slot": START - DAY + 3600,
        "played": {GALAXY: 0.5}}, packages=[PLAY, GALAXY], settings={"daily_max_min": 1}, steps=[{"wait": 10, "takes": 10}] * 10)
    add("waiting_half_past", calls=2, file={"start": START - 10, "done": [PLAY], "slot": START - DAY + 1800}, settings={"daily_time": "07:30"})
    add("start_button_after_waiting", calls=4, force="button", force_call=2, file={"start": START - 10, "done": [PLAY], "slot": START - DAY + 3600},
        settings={"daily_max_min": 1}, steps=[{"wait": 10, "takes": 20}] * 10)
    add("done_twice_in_the_file", force="start", packages=[PLAY, GALAXY, "com.nianticlabs.pokemongo.beta"],
        file={"start": START - 100, "done": [GALAXY, GALAXY], "slot": START - DAY + 3600}, settings={"daily_max_min": 1},
        steps=[{"wait": 10, "takes": 20}] * 10)
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
    print("the file is what the code does now: %d stories" % len(stored["cases"]))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--show", help="print the events of one story")
    args = parser.parse_args()
    if args.check:
        sys.exit(check())
    if args.show:
        for c in all_stories():
            if c["id"] == args.show:
                for e in record(c["spec"]):
                    print(e)
        return
    data = text()
    with open(OUT, "wb") as f:
        f.write(pack(data))
    doc = json.loads(data)
    print("wrote %s: %d stories, %d events" % (OUT, len(doc["cases"]), sum(len(c["events"]) for c in doc["cases"])))


if __name__ == "__main__":
    main()
