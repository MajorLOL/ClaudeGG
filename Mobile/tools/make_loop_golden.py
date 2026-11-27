#!/usr/bin/env python3
"""Makes tests/fixtures/loop_golden.json.qz (JSON, packed the way qCompress() of Qt does: the length, then zlib):
fights played by the fight loop of gamebot.py (fight_battle), as the file that the C++ port of that loop
(SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoLoop.cpp) is tested against.

    python3 tools/make_loop_golden.py            writes the file (the fights are those that tests/test_fight_loop.py plays)
    python3 tools/make_loop_golden.py --check    says whether the file is what the loop does now (the fights stored in it are played again)

A fight is a story of a fake phone (tests/test_fight_loop.py: Phone) that shows pictures of real fights and reacts to
what the bot does.  Here the loop runs without threads, so that it is always the same: the thread that taps the fast
attacks is a fake that taps once for every picture the phone gives, the thread that reads the names is one that
reads when it is asked, the clock only moves with the pictures and the sleeps of the loop.

What comes out is the list of EVENTS of one fight, in order, every one with the time of the fake clock (it starts at 1000.0 and only moves with the pictures and the sleeps):
  what the loop is GIVEN (the C++ port is given the same):
    wait_new  a picture of the live video            (name of the picture)
    screenshot  a screenshot                          (name of the picture)
    ocr       the text reader read lines             (size of the picture, the part, scale, its mean, the lines)
    ocr_line  the text reader read one line          (size of the picture, lines, its mean, the text)
    on_map    the answer of the check for the map
  what the loop DOES (the C++ port has to do the same, in this order):
    tap, tap_quick, tap_motion, swipe, go, pause, aim, sweep, ask, banner, log, sleep, save, save_seen, save_minigames
    and at the end result (the dict the loop returns).
The names of the pictures are folder/file, with "+exit" for the question 'Exit the Trainer Battle?' that the test draws
over a picture.  Also in the file: the answers of the check for the map for every picture of the fights."""
import argparse
import inspect
import json
import os
import struct
import sys
import tempfile
import unittest
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.environ["HOME"] = tempfile.mkdtemp()               # (no team, no settings and no memory of other fights)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import cv2  # noqa: E402
import battle_engine as BE  # noqa: E402
import battle_fight as BF  # noqa: E402
import battle_vision as BV  # noqa: E402
import gamebot as G  # noqa: E402
import spin_stop as S  # noqa: E402
import test_fight_loop as T  # noqa: E402

OUT = os.path.join(ROOT, "tests", "fixtures", "loop_golden.json.qz")
HUD_VISIBLE = BV.hud_visible                             # (two tests change a reader: one of them is a story of its own, see "patch")
HOPELESS = BF.Fight.hopeless


def one_vs_two(fight, foes):
    """The story of the test that tells the fight it is lost when its last Pokémon is against two (the port has the same rule)."""
    return (len(fight.alive()) == 1 and foes == 2), "Lanturn is our last Pokémon and loses (told by the test)"
START = 1000.0                                          # the clock of the fake phone starts here


class Recorder:
    def __init__(self, phone):
        self.phone = phone
        self.events = []
        self.who = "fast"                               # who taps: "main" (the loop) or "fast" (the tapper thread)
        self.tapper = None

    def add(self, kind, *rest):
        self.events.append([kind, T.Clock.t] + list(rest))

    def picture(self):
        """The name of the picture that the phone shows now (see Phone.picture())."""
        name = self.phone.scene.split("#")[0]
        if name == "icons":
            name = "ghost" if self.phone.thrown == 0 else "flying"
        folder = "minigame" if name in ("flying", "ghost") else "fight"
        file = {"their_attack": "banner_over_hud", "tie_question": "shield_question", "exit": "day_dim",
                "map_like": "versus"}.get(name, name)
        return f"{folder}/{file}" + ("+exit" if name == "exit" else "")


class RClock(T.Clock):
    """The clock of the test, and the sleeps of the loop are told."""
    rec = None

    @staticmethod
    def sleep(seconds):
        RClock.rec.add("sleep", seconds)
        T.Clock.sleep(seconds)


class FakeTapper:
    """The thread that taps the fast attacks, without the thread: poll() is what it would have done in the time
    that went by (a swipe of the little game when its planner has one, else a fast tap while it is on)."""

    def __init__(self, rec, xy, ms=G.FIGHT_TAP_MS):
        self.rec, self.xy, self.ms = rec, xy, ms
        self._on = False
        self._sweep = None
        self._aim = None
        self.taps = 0
        self.swipes = 0
        rec.tapper = self

    def start(self):
        pass

    def tap(self, x, y, ms=120):
        self.rec.who = "main"
        try:
            S.tap(x, y, ms)
        finally:
            self.rec.who = "fast"

    def do(self, fn, *args):
        self.rec.who = "main"
        try:
            fn(*args)
        finally:
            self.rec.who = "fast"

    def sweep(self, planner):
        self._sweep = planner
        self.rec.add("sweep", 0 if planner is None else 1)

    def aim(self, xy):
        self._aim = xy
        self.rec.add("aim", None if xy is None else list(xy))

    def go(self):
        self._on = True
        self.rec.add("go")

    def pause(self):
        self._on = False
        self.rec.add("pause")

    def close(self):
        self._sweep = None
        self._on = False

    def poll(self):
        planner = self._sweep
        if planner is not None:
            try:
                strokes = planner()
            except Exception:  # noqa: BLE001
                strokes = []
            if strokes:
                S.swipes(strokes)
                self.swipes += len(strokes)
                return
        if self._on:
            x, y = self._aim or self.xy
            S.tap(x, y, self.ms)
            self.taps += 1


class FakeLooker(G.FightLooker):
    """The thread that reads the names, without the thread: it reads at once when it is asked."""

    def __init__(self, fight, lock, rec):
        super().__init__(fight, lock)
        self.rec = rec

    def start(self):
        pass

    def ask(self, shot):
        busy = self._busy
        super().ask(shot)
        if not busy and self._shot is not None:
            self.rec.add("ask")
            self._work()

    def read_banner(self, shot):
        busy = self._busy
        super().read_banner(shot)
        if not busy and self._shot is not None:
            self.rec.add("banner")
            self._work()


class Stream:
    """What battle_stream.FrameStream is to the loop, from the phone."""

    def __init__(self, rec):
        self.rec, self.failed = rec, False

    def healthy(self, max_age=2.5):
        return True

    def starting(self):
        return False

    def describe(self):
        return "fake phone"

    def close(self):
        pass

    def wait_new(self, seq, timeout=1.0, not_before=0.0):
        got = self.rec.phone.wait_new(seq, timeout, not_before)
        self.rec.add("wait_new", self.rec.picture())
        self.rec.tapper.poll()
        return got


def mean(img):
    return round(float(img.mean()), 2)


def lines_of(lines):
    return [[line[0], line[1], line[2], [list(w) for w in line[3]]] for line in lines]


def record(spec):
    """Plays one fight on the fake phone; returns the list of events and what the loop returned."""
    T.Clock.t = START
    phone = T.Phone(spec["video"], spec["tie"], spec["script"], spec["names"], spec["words"], spec["thrown"])
    rec = Recorder(phone)
    RClock.rec = rec
    names = ("time", "log", "ocr_lines", "ocr_line", "save_async", "MINIGAME_FILE", "SEEN_FILE", "FIGHT_AIM",
             "battle_give_up", "FastTapper", "FightLooker", "save_seen", "save_minigames", "FIGHT_VIDEO", "battle_league")
    names_s = ("tap", "swipes", "screenshot", "on_map", "debug_save", "tap_quick", "tap_motion")
    saved = {n: getattr(G, n) for n in names}
    saved_s = {n: getattr(S, n) for n in names_s}
    folder = tempfile.mkdtemp()
    hopeless_before = BF.Fight.hopeless
    try:
        if spec.get("patch") == "no_hud":                # the name boxes are never recognised
            BV.hud_visible = lambda img: False
        if spec.get("patch") == "one_vs_two":            # the fight is told it is lost: our last Pokémon against two
            BF.Fight.hopeless = one_vs_two
        G.time = RClock
        G.FIGHT_AIM = spec["aim"]
        G.battle_give_up = lambda: spec["give_up"]
        G.battle_league = lambda: spec["league"]
        G.MINIGAME_FILE = os.path.join(folder, "minigame.json")
        G.SEEN_FILE = os.path.join(folder, "seen.json")
        with open(G.SEEN_FILE, "w", encoding="utf-8") as handle:       # (what earlier fights taught, in its order)
            json.dump({species: dict(moves) for species, moves in spec["seen"]}, handle)
        with open(G.MINIGAME_FILE, "w", encoding="utf-8") as handle:
            json.dump(spec["minigames"], handle)
        G.save_async = lambda name, img: rec.add("save", name)
        G.save_seen = lambda d: rec.add("save_seen", json.loads(json.dumps(d, sort_keys=True)))
        G.save_minigames = lambda d: rec.add("save_minigames", json.loads(json.dumps(d, sort_keys=True)))
        G.FastTapper = lambda xy, ms=G.FIGHT_TAP_MS: FakeTapper(rec, xy, ms)
        G.FightLooker = lambda fight, lock: FakeLooker(fight, lock, rec)
        G.log = lambda text: (rec.add("log", text), phone.log(text))[0]

        def ocr_lines(img, y0=0, y1=None, scale=1.0):
            lines = phone.ocr(img, y0, y1, scale)
            rec.add("ocr", img.shape[0], img.shape[1], y0, y1, scale, mean(img), lines_of(lines))
            return lines

        def ocr_line(img, lines=1):
            text = phone.line(img, lines)
            rec.add("ocr_line", img.shape[0], img.shape[1], lines, mean(img), text)
            return text

        G.ocr_lines, G.ocr_line = ocr_lines, ocr_line

        def tap(x, y, ms=120):
            rec.add("tap", x, y, ms, rec.who)
            phone.tap(x, y, ms)

        def tap_quick(x, y):
            rec.add("tap_quick", x, y)
            phone.tap(x, y, 1)

        def tap_motion(x, y, ms=80):
            rec.add("tap_motion", x, y, ms)
            phone.tap(x, y, ms)

        def swipes(strokes):
            rec.add("swipe", [list(s) for s in strokes])
            phone.swipe(strokes)

        def screenshot(on_grab=None):
            img = phone.screenshot(on_grab)
            rec.add("screenshot", rec.picture())
            rec.tapper.poll()
            return img

        def on_map(img):
            answer = bool(spec["map_scene"]) and phone.scene.split("#")[0] == spec["map_scene"]
            rec.add("on_map", answer)
            return answer

        S.tap, S.swipes, S.screenshot, S.on_map = tap, swipes, screenshot, on_map
        S.tap_quick, S.tap_motion = tap_quick, tap_motion
        S.debug_save = lambda *a, **k: None
        if spec["video"]:
            res = G.fight_battle(stream=Stream(rec))
        else:
            G.FIGHT_VIDEO = False
            res = G.fight_battle()
        rec.add("result", res)
        return rec.events, res, phone
    finally:
        BV.hud_visible = HUD_VISIBLE
        BF.Fight.hopeless = hopeless_before
        for n, v in saved.items():
            setattr(G, n, v)
        for n, v in saved_s.items():
            setattr(S, n, v)


class Capture(T.FightLoop):
    """The tests of the fight loop, played to find the fights they play (and the answers of the tests are not looked at)."""
    out = None

    def play(self, video, tie="", script=None, names=None, words=True, thrown=None, map_scene=None):
        spec = {"video": video, "tie": tie, "script": json.loads(json.dumps(script)) if script else None,
                "names": list(names) if names else None, "words": words, "thrown": thrown, "map_scene": map_scene,
                "aim": bool(G.FIGHT_AIM), "give_up": bool(G.battle_give_up()), "league": G.battle_league(),
                "seen": [[species, list(moves.items())] for species, moves in G.load_seen().items()],
                "minigames": G.load_minigames()}
        if BV.hud_visible is not HUD_VISIBLE:
            spec["patch"] = "no_hud"
        if BF.Fight.hopeless is not HOPELESS:            # (the one test that tells the fight it is lost: see one_vs_two)
            spec["patch"] = "one_vs_two"
        events, res, phone = record(spec)
        self.out.append((self._testMethodName, spec, events))
        return phone, res


class More(Capture):
    """Fights of this tool's own.  The tests of the loop play a fight where its story is, not where a number of the loop has
    its limit; these do (found by changing the numbers and the conditions of the port one at a time and looking at which
    change the replay of the other fights did not see)."""

    def test_zz_a_button_that_goes_dark_for_a_moment_after_its_tap(self):
        """The charged attack button is tapped and the next pictures show it dark for a moment (a flash, a banner): one, two or
        three pictures of that are not the sign that the tap counted - the button is lit again and the tap is made again."""
        for dark in (1.15, 1.25, 1.35):
            script = [("versus", 0.5), ("day_start", 1.0), ("day_lit#first", "throw"), ("day_dim#flicker", dark),
                      ("day_lit#again", "throw"), ("day_get_ready", 1.3), ("icons", 4.0), ("day_banner", 1.0),
                      ("day_dim", 2.0), ("day_shield", "shield"), ("day_result", "next")]
            self.play(video=True, script=script)

    def test_zz_the_fight_goes_on_after_yes(self):
        """YES is tapped on 'Exit the Trainer Battle?' and the fight is still there eight seconds later."""
        self.dragalge_known()
        script = [("versus", 0.5), ("day2_last", 2.5), ("day2_no_shields", "run"), ("exit", "yes"),
                  ("day2_no_shields#after", 14.0), ("day_result", "next")]
        self.play(video=True, script=script, names=self.LAST)

    def test_zz_the_question_to_leave_stays_on_the_screen(self):
        """The tap on YES is not taken: the question is still there when the screen is read, and YES is tapped again."""
        self.dragalge_known()
        for video in (True, False):
            script = [("versus", 0.5), ("day2_last", 2.5), ("day2_no_shields", "run"), ("exit", 20.0), ("day_result", "next")]
            self.play(video=video, script=script, names=self.LAST)

    def test_zz_the_map_for_a_while_with_screenshots(self):
        """With screenshots it is three pictures that end the loop on the map (1.3 s apart), not the two seconds."""
        script = [("versus", 0.5), ("map_like", 12.0), ("day_result", "next")]
        self.play(video=False, script=script, map_scene="map_like")


def capture():
    names = [n for n in dir(More) if n.startswith("test_") and "self.play(" in inspect.getsource(getattr(More, n))]
    Capture.out = []
    for name in names:
        case = More(name)
        case.setUp()
        try:
            getattr(case, name)()
        except Exception:  # noqa: BLE001
            pass                                         # (what the test says about the answers is not wanted here)
        finally:
            case.tearDown()
    seen, cases, counts = set(), [], {}
    for name, spec, events in Capture.out:
        key = json.dumps(spec, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        counts[name] = counts.get(name, 0) + 1
        cases.append({"id": "%s#%d" % (name, counts[name]), "spec": spec, "events": events})
    return cases


def on_map_answers():
    """What the check for the map says about every picture of the fights (on the canvas of the phone)."""
    out = {}
    for folder in ("fight", "minigame"):
        for name in sorted(os.listdir(os.path.join(T.FIX, folder))):
            if name.endswith(".jpg"):
                img = cv2.imread(os.path.join(T.FIX, folder, name))
                img = cv2.resize(img, (S.REF_W, S.REF_H), interpolation=cv2.INTER_AREA)
                out[folder + "/" + name[:-4]] = bool(S.on_map(img))
    return out


#  The numbers of the loop (in gamebot.py and battle_fight.py) that the C++ port has a copy of.  The fights only
#  show a number where one of them crosses its limit, so the port is also held to the numbers themselves.
CONSTANTS = (
    (G, "FIGHT_START_SECONDS"), (G, "FIGHT_SECONDS"), (G, "FIGHT_TAP_MS"), (G, "CHARGE_HOLD"), (G, "GAME_BLOCK"),
    (G, "THROW_CHECK"), (G, "THROW_RETRIES"), (G, "THROW_LATEST"), (G, "PLAIN_PICTURES"), (G, "ZOOM_PICTURES"),
    (G, "ZOOM_AFTER"), (G, "BARS_ONLY"), (G, "HELD_LIT"), (G, "HELD_BACK"), (G, "AIM_RECENT"), (G, "AIM_CHECK"),
    (G, "GIVE_UP_LOOKS"), (G, "GIVE_UP_EVERY"), (G, "GIVE_UP_WAIT"), (G, "RETAP_AFTER"), (G, "RETAP_MAX"),
    (G, "BALLS_FRESH"), (G, "READY_RECENT"), (G, "USED_FROM"), (G, "USED_UNTIL"), (G, "USED_EVERY"),
    (G, "MAP_PICTURES"), (G, "MAP_SECONDS"), (G, "SWITCH_TAP_MS"), (G, "SWITCH_TAP_Y"), (G, "SWITCH_RETAPS"),
    (G, "RESULT_SETTLE"), (G, "THEIR_ATTACK"), (G, "OUR_ATTACK"), (G, "ATTACK_EDGES"), (G, "PRE_FIGHT_TAPS"),
    (G, "FIGHT_WAIT_LOOK"), (G, "SWEEP_SECONDS"), (BF, "FOE_CHECK_EVERY"), (BF, "SHIELDS_BACK"),
)


def constants():
    out = {}
    for module, name in CONSTANTS:
        value = getattr(module, name)
        out[name] = [float(x) for x in value] if isinstance(value, (tuple, list)) else [float(value)]
    return out


def text(cases=None):
    if cases is None:
        cases = capture()
    league = cases[0]["spec"]["league"] if cases else ""
    doc = {"cv2": cv2.__version__, "start": START, "team": BE.DEFAULT_TEAM, "league": league,
           "constants": constants(), "on_map": on_map_answers(), "cases": cases}
    return json.dumps(doc, separators=(",", ":"), sort_keys=True)


def check():
    with open(OUT, "rb") as handle:
        packed = handle.read()
    old = json.loads(zlib.decompress(packed[4:]))
    new_cases = []
    for case in old["cases"]:
        events, _res, _phone = record(case["spec"])
        new_cases.append({"id": case["id"], "spec": case["spec"], "events": events})
    raw = text(new_cases).encode("utf-8")
    if len(packed) > 4 and struct.unpack(">I", packed[:4])[0] == len(raw) and zlib.decompress(packed[4:]) == raw:
        print("loop_golden.json.qz is what the fight loop does")
        return 0
    new = json.loads(raw)
    if old.get("constants") != new["constants"]:
        names = [k for k in new["constants"] if old.get("constants", {}).get(k) != new["constants"][k]]
        print("loop_golden.json.qz is NOT what the fight loop does: the numbers " + ", ".join(names) + " changed")
        return 1
    differ = [a["id"] for a, b in zip(old["cases"], new["cases"]) if json.dumps(a["events"]) != json.dumps(b["events"])]
    if old["cv2"] == new["cv2"] or len(differ) > int(0.05 * len(old["cases"])) or old["on_map"] != new["on_map"]:
        print("loop_golden.json.qz is NOT what the fight loop does: " + ", ".join(differ[:8]))
        return 1
    print("loop_golden.json.qz was made with OpenCV %s, this is %s: %d of %d fights go another way (allowed: %d)"
          % (old["cv2"], new["cv2"], len(differ), len(old["cases"]), int(0.05 * len(old["cases"]))))
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
    print("wrote %s: %d fights, %d events, %d bytes of JSON, packed to %d" % (
        OUT, len(doc["cases"]), sum(len(c["events"]) for c in doc["cases"]), len(raw), os.path.getsize(OUT)))
