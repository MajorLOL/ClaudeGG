#!/usr/bin/env python3
"""Makes tests/fixtures/throwplay_golden.json.qz (JSON, packed the way qCompress() of Qt does: the length, then zlib): what gamebot.py does
when it throws a ball - humanize() (the variation of a 'realistic' throw), throw_ball(), throw_touch() (one throw as a single touch: the finger
goes down, the ring is looked at while the ball is held or spun, the throw is timed, the ball is let go, and what the flight and the size of
the ring teach), aim() (the simple throw), ring_track() and watch_flight() - as the file that the C++ port
(SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoThrowPlay.cpp) is tested against.

    python3 tools/make_throwplay_golden.py            writes the file
    python3 tools/make_throwplay_golden.py --check    says whether the file is what the code does now (the stories stored in it are played again)

The file is a list of stories: a list of calls, each with the EVENTS that it makes, with the time of a fake clock (it starts at 1000.0 and only
moves with the screenshots, the sleeps and the commands of the phone).  The pictures are drawn on the canvas by the ops of
tools/make_throw_golden.py (rings and balls), and the readers of the throw (measure_ring, find_ball, ...) are the real ones.  What the code is GIVEN:
    shot          a screenshot (which of the frames of the story, a quick or a real one, and whether it came from the live video)
    live_frames   the pictures of the live video that were asked for (their times and the frames)
    objects       the encounter detector looked at a frame and found these boxes
    params        the throw predictor was asked where and how long to swipe, and said
    random        a number that was drawn (random(), uniform(), gauss())
    communicate   what the command that holds the finger (and spins the ball) said when it was done, and how long it took
    adb           a command of the phone ended (in an error, or well), and how long it took
  what it DOES (the C++ port has to do the same, in this order):
    popen, adb, swipe (the commands for the phone, as the text that the shell is given), sleep, log, save (a picture that is kept: which frame),
    save_cal (what the bot has learned is written down), then at the end of every call: result (what it returned, or raised) and state (what
    it remembers)."""
import argparse
import copy
import json
import os
import random as pyrandom
import struct
import sys
import types
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_throw_golden as TG  # noqa: E402  (the pictures: rings and balls)
from make_start_golden import START, Clock, Rec  # noqa: E402
import gamebot as G  # noqa: E402
import spin_stop as S  # noqa: E402

ROOT = os.path.dirname(HERE)
MONO = 640.25         # time.monotonic() of the fake phone runs this far behind time.time() (on a real one they are nowhere near each other: the times of the
#                       video are on the monotonic clock, and a sum that mixes the two up is no sum)
OUT = os.path.join(ROOT, "tests", "fixtures", "throwplay_golden.json.qz")
W, H = TG.W, TG.H


# ---------------------------------------------------------------------- what the code remembers

STATE = ("cal", "ring_shots", "throw_stats", "throw_info")
_defaults = {name: json.loads(json.dumps(getattr(G, name))) for name in STATE}


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


def snapshot():
    return {name: jsonable(getattr(G, name)) for name in STATE}


def restore(init):
    for name in STATE:
        target = getattr(G, name)
        target.clear()
        target.update(copy.deepcopy(_defaults[name]))
        if name in init:
            target.update(copy.deepcopy(init[name]))


# ---------------------------------------------------------------------- the fake phone

class FakeRandom:
    """random.random(), random.uniform() and random.gauss() of gamebot.py: numbers from a generator with a seed (or the numbers that the story
    says, first), each told as an event."""

    def __init__(self, seed, rec, script=()):
        self.rnd, self.rec = pyrandom.Random(seed), rec
        self.script = list(script)

    def _next(self, make):
        return self.script.pop(0) if self.script else make()

    def random(self):
        value = self._next(self.rnd.random)
        self.rec.add("random", "random", None, None, value)
        return value

    def uniform(self, lo, hi):
        value = self.rnd.uniform(lo, hi)
        self.rec.add("random", "uniform", lo, hi, value)
        return value

    def gauss(self, mu, sigma):
        value = self.rnd.gauss(mu, sigma)
        self.rec.add("random", "gauss", mu, sigma, value)
        return value


class SyncPool:
    """ThreadPoolExecutor, without the threads: what is asked is done at once, in order; an error comes out when the result is asked for."""

    def __init__(self, workers=1):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def submit(self, fn, *args):
        try:
            result, error = fn(*args), None
        except Exception as e:  # noqa: BLE001
            result, error = None, e

        def get(timeout=None):
            if error is not None:
                raise error
            return result
        return types.SimpleNamespace(result=get)


class World:
    """The frames of a story: pictures (drawn once, the same array every time: the code does not write into pictures) and the boxes that the
    detector finds in each."""

    def __init__(self, spec):
        self.frames = spec["frames"]
        self.cache = {}
        self.by_id = {}
        self.shots = 0                        # screenshots asked for so far

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


class ThrowClock(Clock):
    """The fake clock, with a monotonic clock that is not the same as the clock of the day."""

    @staticmethod
    def monotonic():
        return Clock.t - MONO


def record(spec):
    """Plays one story on the fake phone; returns the list of events."""
    Clock.t = START
    rec = Rec()
    Clock.rec = rec
    world = World(spec)
    saved_g = {n: getattr(G, n) for n in ("time", "log", "random", "setting", "save_async", "save_cal", "subprocess", "ThreadPoolExecutor")}
    saved_s = {n: getattr(S, n) for n in ("time", "log", "INPUT", "adb", "swipe", "quick_screenshot", "screenshot", "live_stream", "live_frames",
                                          "to_real")}
    saved_screen = dict(S.screen)
    try:
        restore(spec.get("init", {}))
        G.time = S.time = ThrowClock
        G.log = S.log = lambda text: rec.add("log", text)
        G.random = FakeRandom(spec.get("seed", 1), rec, spec.get("random_script", ()))
        settings = dict(spec.get("settings", {}))
        G.setting = lambda key, default: settings.get(key, default)
        G.save_async = lambda name, img: rec.add("save", name, world.index_of(img))
        G.save_cal = lambda: rec.add("save_cal", snapshot()["cal"])
        G.ThreadPoolExecutor = SyncPool
        S.INPUT = list(spec.get("input", ["input"]))
        S.screen.update(w=spec.get("screen", [W, H])[0], h=spec.get("screen", [W, H])[1])
        live = {"on": False}
        shots = list(spec.get("shots", [0]))
        adb_errors = list(spec.get("adb_errors", []))
        outputs = list(spec.get("spin_outputs", []))
        script_frames = list(spec.get("live_frames", []))
        params = list(spec.get("params", [[-900.0, 200.0]]))
        objects_seconds = spec.get("objects_seconds", 0.0)

        def next_frame():
            n = world.shots
            world.shots += 1
            index = shots[min(n, len(shots) - 1)]
            if isinstance(index, str):                 # "error: text": the screenshot fails
                text = index.split(": ", 1)[1]
                rec.add("shot_error", text)
                raise RuntimeError(text)
            return index

        def make_shot(kind):
            def take(on_grab=None):
                index = next_frame()
                if kind == "quick" and live["on"] and not spec.get("quick_not_live"):
                    Clock.t += spec.get("live_shot_seconds", 0.02)
                    take.live, take.t = True, Clock.t - MONO - spec.get("live_age", 0.12)
                    rec.add("shot", index, kind, True)
                else:
                    Clock.t += spec.get("shot_seconds", 0.0)
                    if kind == "quick":
                        take.live, take.t = False, Clock.t - MONO
                    rec.add("shot", index, kind, False)
                return world.picture(index)
            take.live, take.t = False, 0.0
            return take

        S.quick_screenshot = make_shot("quick")
        S.screenshot = make_shot("real")
        S.live_stream = lambda: object() if live["on"] else None

        def live_frames(seconds, every=0.0):
            if not live["on"]:
                return []
            start = Clock.t - MONO
            Clock.t += seconds
            got = script_frames.pop(0) if script_frames else []
            rec.add("live_frames", seconds, every, [[start + dt, index] for dt, index in got])
            return [(start + dt, world.picture(index)) for dt, index in got]
        S.live_frames = live_frames

        def to_real(x, y):
            return int(round(x * S.screen["w"] / S.REF_W)), int(round(y * S.screen["h"] / S.REF_H))
        S.to_real = to_real

        def adb(*args, binary=False):
            Clock.t += spec.get("release_seconds", 0.0)
            error = adb_errors.pop(0) if adb_errors else None
            rec.add("adb", list(args), error)
            if error:
                raise RuntimeError(error)
            return ""
        S.adb = adb
        S.swipe = lambda x1, y1, x2, y2, ms=300: (rec.add("swipe", x1, y1, x2, y2, ms), setattr(Clock, "t", Clock.t + spec.get("swipe_seconds", 0.0)))

        class FakePopen:
            def __init__(self, args, stdout=None, stderr=None):
                rec.add("popen", list(args))
                self.t0 = Clock.t

            def communicate(self, timeout=None):
                Clock.t = max(Clock.t, self.t0 + spec.get("spin_seconds", 0.0))
                out = outputs.pop(0) if outputs else ""
                rec.add("communicate", out)
                return out.encode(), None

            def wait(self, timeout=None):
                Clock.t = max(Clock.t, self.t0 + spec.get("hold_seconds", 1.3))
                rec.add("wait")
                return 0
        G.subprocess = types.SimpleNamespace(Popen=FakePopen, PIPE=-1, STDOUT=-2)

        class FakeBrain:
            def encounter_objects(self, img):
                index = world.index_of(img)
                found = [tuple(o) for o in world.frames[index].get("found", [])]
                Clock.t += objects_seconds
                rec.add("objects", index, [list(o) for o in found])
                return found

            def throw_params(self, cx, cy, bw, bh):
                dy, dur = params.pop(0) if len(params) > 1 else params[0]
                rec.add("params", cx, cy, bw, bh, dy, dur)
                return dy, dur
        brain = FakeBrain()

        for call in spec["calls"]:
            if "settings" in call:
                settings.update(call["settings"])
            if "advance" in call:
                Clock.t += call["advance"]
            live["on"] = bool(call.get("live", spec.get("live", False)))
            rec.add("call", call["fn"], jsonable({k: v for k, v in call.items() if k not in ("fn", "settings", "advance")}))
            try:
                fn = call["fn"]
                if fn == "throw_touch":
                    result = G.throw_touch(brain, call["curve"], call["target"], call["name"], call.get("aim_dx", 0), call.get("power", 1.0))
                elif fn == "throw_ball":
                    result = G.throw_ball(brain)
                elif fn == "humanize":
                    result = list(G.humanize(call["name"], call["curve"]))
                elif fn == "aim":
                    ring = G.aim(brain)
                    result = None if ring is None else list(ring)
                elif fn == "ring_track":
                    first = world.picture(call["first"])
                    points, box = G.ring_track(brain, first, call.get("t_first"))
                    result = [[list(p) for p in points], None if box is None else list(box)]
                elif fn == "watch_flight":
                    first, land = G.watch_flight(world.picture(call["before"]), None if call.get("ring") is None else tuple(call["ring"]))
                    result = [None if first is None else world.index_of(first), land]
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
        S.screen.clear()
        S.screen.update(saved_screen)
        restore({})


# ---------------------------------------------------------------------- the frames

RING_BOX = TG.encounter_box(884, 900, 320)


def ring_frame(ratio, found=True, box=None, radius=160, cx=884, **kw):
    """A catch screen with the ring at this size; found: the detector sees the white ring (box: its box, when it is not the square one; cx: the ring
    is not in the middle)."""
    return {"pic": TG.ring_ops(cx, 900, radius, ratio, **kw), "found": [box or TG.encounter_box(cx, 900, 320)] if found else []}


def flight_frame(x, y, ratio=0.5, w=100, h=100, found=False, box=None, radius=160, cx=884):
    """The same, with a ball in the air at (x, y)."""
    ops = TG.ring_ops(cx, 900, radius, ratio)
    ops.append(["ellipse", x, y, w // 2, h // 2, 0, -1, [30, 30, 220]])
    return {"pic": ops, "found": [box or TG.encounter_box(cx, 900, 320)] if found else []}


def empty_frame():
    return {"pic": TG.background(), "found": []}


def unreadable_frame():
    return {"pic": TG.ring_ops(884, 900, 160, 0.6, coloured=False), "found": [RING_BOX]}


def story(name, calls, frames, **spec):
    spec.update(frames=frames, calls=calls)
    return {"id": name, "spec": spec}


def throw(curve=False, target=0.5, name="great", aim_dx=0, power=1.0, **extra):
    return dict({"fn": "throw_touch", "curve": curve, "target": target, "name": name, "aim_dx": aim_dx, "power": power}, **extra)


# ---------------------------------------------------------------------- what the stories have to hit exactly

def decision_ring():
    """ring_at() at the moment where throw_touch decides how long to wait, in the stories with the usual numbers of `common` (a screenshot of the ring
    with size 0.9 after the first quarter of a second, the spin command done 0.9 s after it started, nothing learned yet): the number that the wait is
    counted from.  (The same sums, in the same order, with the same clock, as the code does them.)"""
    img = TG.make_scene(ring_frame(0.9)["pic"])
    measured = G.measure_ring(img, tuple(RING_BOX))["ratio"]
    t_shot = START + G.TOUCH_SHOT
    now = START + 0.9
    return (measured - G.RING_SPEED * ((now + 0.3) - t_shot - 0.3)) % 1.0


def target_for_diff(a, want):
    """The target (a ring size between 0 and 1) for which (a - target) % 1.0 is exactly `want` (the number just below it, or just above, when
    nothing makes exactly that)."""
    import math
    x = a - want + 1.0
    for _ in range(400):
        d = (a - x) % 1.0
        if d == want:
            return x
        x = math.nextafter(x, 2.0 if d > want else -1.0)
    raise ValueError("no target for the difference %r" % want)


# ---------------------------------------------------------------------- the stories

def stories():
    out = []
    ring_hi, ring_mid, ring_lo = ring_frame(0.9), ring_frame(0.5), ring_frame(0.2)
    land_on = flight_frame(884, 772)             # the ball comes down on the Pokémon (the box is 320 high: 900 - 0.4 * 320 = 772)
    common = dict(shot_seconds=0.3, spin_seconds=0.9, release_seconds=0.35, params=[[-880.0, 190.0]])

    def flights(x, y=772):
        f = flight_frame(x, y)
        return [ring_hi, f, f, f, f]

    shots5 = [0, 1, 2, 3, 4]

    # ---- a straight ball with a timed ring, with screenshots; where the ball comes down (the box is 320 wide: a hit is within 112 of the middle)
    out.append(story("touch_straight_on_it", [throw()], flights(884), shots=shots5, **common))
    for name, x in (("left", 500), ("right", 1250), ("a_bit_right", 940), ("hit_edge_95", 884 + 95), ("hit_edge_96", 884 + 96),
                    ("at_the_limit_112", 884 + 112), ("over_the_limit_113", 884 + 113), ("a_bit_left", 884 - 60)):
        out.append(story("touch_straight_lands_%s" % name, [throw()], flights(x), shots=shots5, **common))
    # the size of the ring at the release is called Excellent below 0.3, Great below 0.7 and Nice from there: the pictures are made so that the
    # size that measure_ring() reads is exactly 0.3 (48 / 160) or 0.7 (112 / 160), or in the step just under or over it
    for name, radius, ratio in (("exactly_0_3", 153, 0.32), ("just_under_0_3", 160, 0.315), ("just_over_0_3", 160, 0.32), ("exactly_0_7", 153, 0.735),
                                ("just_under_0_7", 160, 0.72), ("just_over_0_7", 140, 0.74), ("far_under", 160, 0.1), ("far_over", 160, 0.95)):
        f = flight_frame(884, 772, ratio=ratio, radius=radius)
        out.append(story("touch_size_at_the_release_%s" % name, [throw()], [ring_hi, f, f, f, f], shots=shots5, **common))
    # the end of the swipe is never higher than y = 50: the predictor's deltaY that lands the finger on 49, 50 and 51 (the curveball starts from the last
    # point of the spin, y = 1957; the straight throw from the ball, y = 2017)
    for kind, curve, top in (("curve", True, 1957), ("straight", False, 2017)):
        for off in (-1, 0, 1):
            out.append(story("touch_the_top_of_the_swipe_%s_%d" % (kind, 50 + off), [throw(curve=curve)], flights(884), shots=shots5,
                             shot_seconds=0.3, spin_seconds=0.9, release_seconds=0.35, params=[[float(50 + off - top), 190.0]]))
    # ---- where the ball came down, on the edges: a hit is 0.85 of the 0.35 share of the width of the box from the middle (the box of 400: 119 px exactly), a miss
    # begins at the share itself (140 px), and a throw is planned to miss when the aim is more than the share (140 px) to the side
    box400 = TG.encounter_box(884, 900, 400)
    ring400 = ring_frame(0.9, box=box400)
    for name, err, aim_dx in (("hit_119", 119, 0), ("hit_120", 120, 0), ("limit_140", 140, 0), ("over_140", 141, 0),
                              ("aim_140_missed", 330, 140), ("aim_141_missed", 330, 141), ("aim_140_landed", 0, 140), ("aim_141_landed", 0, 141)):
        f = flight_frame(884 + err, 740, box=box400)
        out.append(story("touch_landing_%s" % name, [throw(aim_dx=aim_dx)], [ring400, f, f, f, f], shots=shots5, **common))
    # the aim that is learned from a curveball that did not go where it was meant to: not when the throw was meant to be sloppy (more than 2.5 times the
    # spread of 45 px = 112.5 px to the side), and kept within 700 px (the step is 0.3 of the miss)
    for aim_dx in (110, 112, 113, 115, -112, -113):
        f = flight_frame(884 + aim_dx + 200, 772)
        out.append(story("touch_learn_the_aim_meant_%s%d" % ("minus_" if aim_dx < 0 else "", abs(aim_dx)), [throw(curve=True, aim_dx=aim_dx)], [ring_hi, f, f, f, f],
                         shots=shots5, **common))
    for name, cx, aim0, err in (("right", 1584, 690.0, 100), ("left", 184, -690.0, -100)):
        ring_here = ring_frame(0.9, cx=cx)
        f = flight_frame(cx + err, 772, cx=cx)
        out.append(story("touch_the_aim_stays_within_700_%s" % name, [throw(curve=True)], [ring_here, f, f, f, f], shots=shots5, init={"cal": {"aim": aim0}}, **common))
    # the rings that the detector finds: only a 'boundingBox' with at least the score, and higher than 300 px above the ball (the ball is at y = 2017)
    for name, label, cy in (("a_clickable", "clickable", 900), ("cy_1716", "boundingBox", 1716), ("cy_1717", "boundingBox", 1717), ("cy_1718", "boundingBox", 1718)):
        odd = {"pic": TG.ring_ops(884, 900, 160, 0.9), "found": [[label, 0.9, 884, cy, 320, 320]]}
        out.append(story("touch_the_detector_finds_%s" % name, [throw()], [odd, ring_mid, land_on], shots=[0, 1, 2, 2, 2, 2], **common))
    out.append(story("touch_straight_no_ball_seen", [throw()], [ring_hi, ring_mid], shots=[0, 1, 1, 1, 1], **common))
    out.append(story("touch_straight_the_ball_is_too_high", [throw()], [ring_hi, flight_frame(884, 200)], shots=[0, 1, 1, 1, 1], **common))
    out.append(story("touch_straight_the_ball_is_a_bit_late", [throw()], [ring_hi, ring_mid, flight_frame(884, 772)], shots=[0, 1, 1, 2, 2], **common))
    # a planned sideways aim: a miss on purpose, a miss that landed on it
    out.append(story("touch_planned_miss_and_it_is_one", [throw(aim_dx=200)], flights(1090), shots=shots5, **common))
    out.append(story("touch_planned_miss_but_it_hits", [throw(aim_dx=150)], flights(900), shots=shots5, **common))
    out.append(story("touch_planned_small_aim_and_it_misses", [throw(aim_dx=-60)], flights(1250), shots=shots5, **common))
    out.append(story("touch_planned_aim_exactly_on_the_limit", [throw(aim_dx=112)], flights(884 + 112), shots=shots5, **common))
    out.append(story("touch_planned_aim_over_the_limit", [throw(aim_dx=113)], flights(884 + 113), shots=shots5, **common))
    # the power and the length of the throw
    for name, power, params in (("long", 1.08, [[-880.0, 190.0]]), ("short", 0.92, [[-880.0, 190.0]]), ("quick", 1.0, [[-600.0, 30.0]]),
                                ("slow", 1.0, [[-900.0, 900.0]]), ("up_to_the_top", 1.0, [[-2500.0, 190.0]])):
        out.append(story("touch_straight_throw_%s" % name, [throw(power=power)], flights(884), shots=shots5, **dict(common, params=params)))
    # the speed of the phone's touch events (ms per event) decides how many steps the throw is made of
    for lat in (5.0, 30.0, 55.0, 100.0, 400.0):
        out.append(story("touch_straight_lat_%d" % lat, [throw()], flights(884), shots=shots5, init={"cal": {"lat": lat}}, **common))
    # what is waited for: the ring is below the target (throw at once), above it, the one learned before
    for target, name in ((0.55, "just_below"), (0.9, "far_above"), (0.2, "wraps_round"), (0.52, "close")):
        out.append(story("touch_wait_%s" % name, [throw(target=target, name="nice")], flights(884), shots=shots5, **common))
    out.append(story("touch_wait_with_what_was_learned", [throw()], flights(884), shots=shots5,
                     init={"cal": {"k": 0.7, "c": 0.5, "rel": 0.45, "obs": [[0.7, 1.0, 0.45], [0.6, 1.2, 0.2], [0.9, 0.8, 0.6]]}}, **common))
    # the statistic of every tenth throw, and what is kept
    out.append(story("touch_the_tenth_throw", [throw()], flights(884), shots=shots5, init={"throw_stats": {"n": 9, "on": 7}}, **common))
    out.append(story("touch_the_tenth_throw_off_target", [throw(target=0.85, name="nice")], flights(884), shots=shots5,
                     init={"throw_stats": {"n": 19, "on": 4}}, **common))
    out.append(story("touch_ring_pictures_go_round", [throw()], flights(884), shots=shots5, init={"ring_shots": {"n": 6}}, **common))
    obs = [[round(0.9 - 0.05 * i, 3), round(0.8 + 0.1 * i, 3), round(0.45 + 0.01 * i, 3)] for i in range(16)]
    out.append(story("touch_sixteen_throws_learned", [throw()], flights(884), shots=shots5, init={"cal": {"obs": obs}}, **common))
    # the ring at the release: Excellent, Great and Nice
    for ratio, name in ((0.15, "excellent"), (0.5, "great"), (0.85, "nice")):
        out.append(story("touch_ring_at_release_%s" % name, [throw()], [ring_hi, flight_frame(884, 772, ratio=ratio), flight_frame(884, 772, ratio=ratio)],
                         shots=[0, 1, 2, 2, 2], **common))

    # ---- the throw is timed, and the ring is already just below the target: no waiting (a difference of more than 0.93 is a difference of less than 0.07)
    a = decision_ring()
    for label, want in (("0925", 0.925), ("0929", 0.929), ("exactly_093", 0.93), ("0931", 0.931), ("0935", 0.935), ("094", 0.94)):
        out.append(story("touch_wait_difference_%s" % label, [throw(target=target_for_diff(a, want), name="nice")], flights(884), shots=shots5, **common))
    # the speed of the touch events decides the number of steps (round to the nearest, the half to the even one): the lengths of the swipe that are
    # just on this side and just on that side of a half
    for lat in (60.4, 61.0):
        out.append(story("touch_steps_lat_%s" % lat, [throw()], flights(884), shots=shots5, init={"cal": {"lat": lat}}, **common))
    for lat in (23.8, 24.0, 24.2):
        out.append(story("touch_steps_short_throw_lat_%s" % lat, [throw()], flights(884), shots=shots5, init={"cal": {"lat": lat}},
                         **dict(common, params=[[-880.0, 50.0]])))
    out.append(story("touch_steps_default_throw_lat", [throw()], [empty_frame(), empty_frame(), land_on], shots=[0, 1, 2, 2, 2, 2], init={"cal": {"lat": 80.4}}, **common))
    out.append(story("touch_steps_default_throw_lat_80", [throw()], [empty_frame(), empty_frame(), land_on], shots=[0, 1, 2, 2, 2, 2], init={"cal": {"lat": 80.0}}, **common))
    # 0.8 * 251 ms is 200.8: cut to 200 (and not rounded to 201), which is 2.5 steps of 80 ms, so 2 (the half to the even one)
    out.append(story("touch_steps_the_duration_is_cut", [throw()], flights(884), shots=shots5, init={"cal": {"lat": 80.0}}, **dict(common, params=[[-880.0, 251.0]])))
    # a speed of the phone that is nothing or less than nothing counts as 5 ms a touch event
    for lat in (0.0, -3.0):
        out.append(story("touch_steps_a_phone_with_lat_%s" % lat, [throw()], flights(884), shots=shots5, init={"cal": {"lat": lat}}, **common))
    # ---- a box that is not square: the width is what a hit is measured in, the height says where the ball comes down, and the predictor is told both
    tall, wide = TG.encounter_box(884, 900, 300, 340), TG.encounter_box(884, 900, 340, 300)
    for name, box in (("tall", tall), ("wide", wide)):
        def box_flights(x, box=box, y=772):
            f = flight_frame(x, y, box=box)
            return [ring_frame(0.9, box=box), f, f, f, f]
        for label, x in (("on_it", 884 + 60), ("100", 884 + 100), ("110", 884 + 110), ("118", 884 + 118), ("120", 884 + 120)):
            out.append(story("touch_%s_ring_lands_%s" % (name, label), [throw()], box_flights(x), shots=shots5, **common))
        out.append(story("touch_%s_ring_curve" % name, [throw(curve=True, aim_dx=30)], box_flights(884 + 110), shots=shots5, **common))
        out.append(story("touch_%s_ring_planned_miss" % name, [throw(aim_dx=108)], box_flights(884 + 108), shots=shots5, **common))
    out.append(story("touch_the_ring_found_while_following", [throw(live=True)], [ring_frame(0.9, box=tall)] + [ring_frame(r, box=tall) for r in (0.85, 0.8, 0.75)],
                     shots=[0], live_frames=[[[0.1, 1], [0.2, 2], [0.3, 3]], []], params=[[-880.0, 190.0]], release_seconds=0.35, spin_seconds=0.9))

    # ---- a curveball: the finger goes round before the throw, and the aim is learned
    out.append(story("touch_curve_on_it", [throw(curve=True)], flights(884), shots=shots5, **common))
    for name, x, aim_dx, aim in (("lands_right", 1050, 0, 0.0), ("lands_left", 700, 0, 0.0), ("aim_100", 1000, 100, 0.0), ("aim_150", 1050, 150, 0.0),
                                 ("aim_minus_100", 780, -100, 0.0), ("learned_before", 1050, 0, 120.0), ("aim_at_the_top", 1400, 0, 690.0),
                                 ("small_error", 930, 0, 0.0), ("error_71", 884 + 71, 0, 0.0), ("error_70", 884 + 70, 0, 0.0), ("error_300", 884 + 400, 0, 0.0),
                                 ("error_minus_400", 884 - 400, 0, 0.0)):
        out.append(story("touch_curve_%s" % name, [throw(curve=True, aim_dx=aim_dx)], flights(x), shots=shots5, init={"cal": {"aim": aim}}, **common))
    out.append(story("touch_curve_leans_as_far_as_it_can", [throw(curve=True)], flights(1300), shots=shots5, init={"cal": {"aim": -1100.0}}, **common))
    out.append(story("touch_curve_leans_the_other_way", [throw(curve=True)], flights(300), shots=shots5, init={"cal": {"aim": 700.0}}, **common))
    out.append(story("touch_curve_ends_at_the_edge", [throw(curve=True, aim_dx=-400)], flights(300), shots=shots5, init={"cal": {"aim": 700.0}}, **common))
    out.append(story("touch_curve_power", [throw(curve=True, power=1.08)], flights(1050), shots=shots5, **common))
    out.append(story("touch_curve_without_timing", [throw(curve=True, target=None, name="off")], [ring_hi, land_on, land_on, land_on, land_on],
                     shots=shots5, **common))
    out.append(story("touch_straight_without_timing", [throw(target=None, name="off")], [ring_hi, land_on, land_on, land_on, land_on], shots=shots5, **common))

    # ---- the ring is not found, or cannot be read
    out.append(story("touch_no_ring_twice", [throw()], [empty_frame(), empty_frame(), land_on], shots=[0, 1, 2, 2, 2, 2], **common))
    out.append(story("touch_no_ring_then_one", [throw()], [empty_frame(), ring_hi, land_on], shots=[0, 1, 2, 2, 2, 2], **common))
    out.append(story("touch_ring_unreadable_twice", [throw()], [unreadable_frame(), unreadable_frame(), land_on], shots=[0, 1, 2, 2, 2, 2], **common))
    out.append(story("touch_ring_unreadable_then_readable", [throw()], [unreadable_frame(), ring_hi, land_on], shots=[0, 1, 2, 2, 2, 2], **common))
    out.append(story("touch_ring_unreadable_without_a_target", [throw(target=None, name="off")], [unreadable_frame(), land_on], shots=[0, 1, 1, 1, 1], **common))
    out.append(story("touch_no_ring_without_a_target", [throw(target=None, name="off")], [empty_frame(), empty_frame(), land_on], shots=[0, 1, 2, 2, 2, 2], **common))
    out.append(story("touch_curve_no_ring", [throw(curve=True)], [empty_frame(), empty_frame(), land_on], shots=[0, 1, 2, 2, 2, 2], **common))
    out.append(story("touch_ring_at_the_bottom_is_no_ring", [throw()], [{"pic": TG.ring_ops(884, 1900, 160, 0.6),
                                                                         "found": [TG.encounter_box(884, 1900, 320)]}, land_on, land_on],
                     shots=[0, 0, 1, 1, 1, 1], **common))
    out.append(story("touch_ring_not_sure_enough", [throw()], [{"pic": TG.ring_ops(884, 900, 160, 0.6),
                                                                "found": [TG.encounter_box(884, 900, 320, score=0.34)]}, land_on, land_on],
                     shots=[0, 0, 1, 1, 1, 1], **common))
    out.append(story("touch_ring_sure_enough", [throw()], [{"pic": TG.ring_ops(884, 900, 160, 0.6),
                                                            "found": [TG.encounter_box(884, 900, 320, score=0.35)]}, land_on, land_on],
                     shots=[0, 1, 1, 1, 1, 1], **common))
    out.append(story("touch_the_first_box_is_taken", [throw()], [{"pic": TG.ring_ops(884, 900, 160, 0.6),
                                                                  "found": [TG.encounter_box(884, 900, 320), TG.encounter_box(400, 600, 200)]},
                                                                 land_on, land_on], shots=[0, 1, 1, 1, 1], **common))
    out.append(story("touch_the_other_kinds_of_box_are_not_rings", [throw()], [{"pic": TG.ring_ops(884, 900, 160, 0.6),
                                                                                "found": [["pokemon", 0.9, 884, 900, 320, 320], TG.encounter_box(884, 900, 320)]},
                                                                               land_on, land_on], shots=[0, 1, 1, 1, 1], **common))

    # ---- the phone: another screen, another input command, errors
    out.append(story("touch_another_screen", [throw(curve=True)], flights(1050), shots=shots5, screen=[1080, 1350], **common))
    out.append(story("touch_another_screen_odd", [throw(curve=True, aim_dx=37)], flights(1050), shots=shots5, screen=[1081, 1357], **common))
    out.append(story("touch_cmd_input", [throw()], flights(884), shots=shots5, input=["cmd", "input"], **common))
    for name, text in (("error", "Exception occurred while executing: Error: inject failed"), ("unknown", "Unknown command: motionevent"),
                       ("usage", "Usage: input [<source>] <command> [<arg>...]"), ("long", "Error: " + "x" * 120)):
        out.append(story("touch_single_touch_not_possible_%s" % name, [throw(curve=True)], [ring_hi, land_on], shots=[0, 1], spin_outputs=[text], **common))
    out.append(story("touch_single_touch_not_possible_and_the_finger_stays", [throw(curve=True)], [ring_hi], shots=[0], spin_outputs=["Error: no"],
                     adb_errors=["device offline"], **common))
    out.append(story("touch_a_message_without_an_error", [throw()], flights(884), shots=shots5, spin_outputs=["  all fine \n"], **common))
    # 'rror' is looked for as it is written (a message in capitals is no error), and the message that is told is cut after the blanks around it are gone
    for name, text in (("capitals", "ERROR: SHOUTED"), ("usage_in_lower_case", "usage: input"), ("unknown_in_capitals", "UNKNOWN COMMAND")):
        out.append(story("touch_a_message_that_is_no_error_%s" % name, [throw()], flights(884), shots=shots5, spin_outputs=[text], **common))
    out.append(story("touch_single_touch_not_possible_a_long_message_after_blanks", [throw(curve=True)], [ring_hi, land_on], shots=[0, 1],
                     spin_outputs=["   \n  Error: " + "y" * 120], **common))
    # the finger goes up where it is: at the last point of the spin of a curveball
    out.append(story("touch_the_screenshot_fails_the_finger_goes_up_curve", [throw(curve=True)], ["x"], shots=["error: no screen"], **common))
    # the end of the swipe stays 20 px from the sides of the screen: the aim that puts it on 19, 20 and 21 from the left, and on 19, 20 and 21 from the right
    for off in (-866, -865, -864, -863, 863, 864, 865, 866):
        out.append(story("touch_the_side_of_the_screen_%s%d" % ("minus_" if off < 0 else "", abs(off)), [throw(aim_dx=off)], flights(884), shots=shots5, **common))
    out.append(story("touch_the_release_fails", [throw()], flights(884), shots=shots5, adb_errors=["device offline"], **common))
    out.append(story("touch_the_screenshot_fails_the_finger_goes_up", [throw()], ["x"], shots=["error: no screen"], **common))
    out.append(story("touch_the_second_screenshot_fails", [throw()], [empty_frame()], shots=[0, "error: no screen"], **common))
    out.append(story("touch_flight_screenshots_fail", [throw()], [ring_hi], shots=[0, "error: a", "error: b", "error: c", "error: d"], **common))
    out.append(story("touch_one_flight_screenshot_fails", [throw()], [ring_hi, land_on], shots=[0, "error: a", 1, "error: c", 1], **common))
    out.append(story("touch_time_runs_on", [throw()], flights(884), shots=shots5, shot_seconds=1.8, spin_seconds=3.5, release_seconds=0.9,
                     params=[[-880.0, 190.0]]))
    out.append(story("touch_the_spin_is_long", [throw(curve=True)], flights(884), shots=shots5, shot_seconds=0.3, spin_seconds=4.0, release_seconds=0.35,
                     params=[[-880.0, 190.0]]))
    out.append(story("touch_a_slow_object_detector", [throw()], flights(884), shots=shots5, objects_seconds=0.5, **common))

    # ---- the live video: the ring is followed for a moment, the flight is a row of pictures
    follow = [[0.1, 1], [0.2, 2], [0.3, 3], [0.4, 4], [0.5, 5], [0.6, 6]]
    ring_series = [ring_frame(r) for r in (0.95, 0.9, 0.84, 0.78, 0.72, 0.67, 0.61)]
    sky_frames = [flight_frame(884, 772) for _ in range(3)]
    live_flight = [[0.1, 7], [0.25, 8], [0.4, 9]]
    live_frames = ring_series + sky_frames
    out.append(story("live_follow_and_throw", [throw(live=True)], live_frames, shots=[0], live_frames=[follow, live_flight],
                     live_age=0.12, params=[[-880.0, 190.0]], release_seconds=0.35, spin_seconds=0.9))
    out.append(story("live_the_tenth_throw", [throw(live=True)], live_frames, shots=[0], live_frames=[follow, live_flight], init={"throw_stats": {"n": 9, "on": 7}},
                     live_age=0.12, params=[[-880.0, 190.0]], release_seconds=0.35, spin_seconds=0.9))
    out.append(story("live_follow_and_throw_a_curve", [throw(curve=True, live=True, aim_dx=40)], live_frames, shots=[0], live_frames=[follow, live_flight],
                     params=[[-880.0, 190.0]], release_seconds=0.35, spin_seconds=0.9))
    out.append(story("live_the_ring_is_not_seen_at_first", [throw(live=True)], [empty_frame(), ring_hi] + sky_frames, shots=[0, 1, 1, 1],
                     live_frames=[[], [[0.1, 2], [0.2, 3], [0.3, 4]]], params=[[-880.0, 190.0]], release_seconds=0.35, spin_seconds=0.9))
    out.append(story("live_only_the_first_picture", [throw(live=True)], [ring_hi] + sky_frames, shots=[0], live_frames=[[], [[0.1, 1], [0.2, 2]]],
                     params=[[-880.0, 190.0]], release_seconds=0.35, spin_seconds=0.9))
    out.append(story("live_the_ring_cannot_be_read", [throw(live=True)], [unreadable_frame(), unreadable_frame(), ring_hi] + sky_frames,
                     shots=[0, 1, 2], live_frames=[[[0.1, 1], [0.2, 1]], [[0.1, 3]]], params=[[-880.0, 190.0]], release_seconds=0.35, spin_seconds=0.9))
    out.append(story("live_no_flight_pictures", [throw(live=True)], live_frames, shots=[0, 7, 8, 9, 9], live_frames=[follow, []],
                     params=[[-880.0, 190.0]], release_seconds=0.35, spin_seconds=0.9))
    out.append(story("live_without_a_target", [throw(curve=True, target=None, name="off", live=True)], live_frames, shots=[0, 1], live_frames=[[[0.1, 7]]],
                     params=[[-880.0, 190.0]], release_seconds=0.35, spin_seconds=0.9))
    out.append(story("live_the_ring_hardly_moves", [throw(live=True)], [ring_frame(0.9)] * 3 + sky_frames, shots=[0], live_frames=[[[0.1, 1], [0.2, 2]], live_flight[:2] and [[0.1, 3], [0.2, 4]]],
                     params=[[-880.0, 190.0]], release_seconds=0.35, spin_seconds=0.9))
    out.append(story("live_the_ring_starts_again", [throw(live=True)], [ring_frame(r) for r in (0.3, 0.2, 0.1, 0.95, 0.85, 0.75)] + sky_frames,
                     shots=[0], live_frames=[[[0.1, 1], [0.2, 2], [0.3, 3], [0.4, 4], [0.5, 5]], [[0.1, 6], [0.2, 7]]], params=[[-880.0, 190.0]],
                     release_seconds=0.35, spin_seconds=0.9))
    out.append(story("live_learned_before", [throw(live=True)], live_frames, shots=[0], live_frames=[follow, live_flight],
                     init={"cal": {"c_live": 0.1, "obs_live": [[0.7, 1.0, 0.4], [0.5, 1.1, 0.1]]}}, params=[[-880.0, 190.0]], release_seconds=0.35,
                     spin_seconds=0.9))
    out.append(story("live_the_video_stops_in_between", [throw(live=True)], live_frames, shots=[0, 7, 8, 9, 9], live_frames=[[]],
                     params=[[-880.0, 190.0]], release_seconds=0.35, spin_seconds=0.9))
    # the video runs, but the quick screenshot is a real one: the ring is looked for the old way
    out.append(story("live_but_the_quick_shot_is_a_screenshot", [throw(live=True)], flights(884), shots=shots5, quick_not_live=True, live_frames=[[]],
                     **common))
    # the first picture of the flight shows no readable ring: nothing is learned from it
    out.append(story("touch_the_ring_cannot_be_read_in_the_flight", [throw()], [ring_hi, unreadable_frame(), unreadable_frame()], shots=[0, 1, 1, 1, 1], **common))
    out.append(story("touch_the_ring_is_gone_in_the_flight", [throw()], [ring_hi, empty_frame()], shots=[0, 1, 1, 1, 1], **common))
    # a picture of the video, and the next one is a screenshot (what the second look is given when the video is there only for the first)
    out.append(story("live_ring_found_again_by_screenshot", [throw(live=True)], [empty_frame(), ring_hi, land_on], shots=[0, 1, 2, 2, 2, 2], live_frames=[[]],
                     params=[[-880.0, 190.0]], release_seconds=0.35, spin_seconds=0.9))
    return out


def humanize_stories():
    """The draws of a throw that is made to look like a person's: every branch of humanize()."""
    out = []
    for curve in (False, True):
        for name in ("great", "nice", "excellent", "off"):
            for r in (0.0, 0.69999, 0.7, 0.85, 0.8999, 0.9, 0.95, 0.99999):
                script = [r] + ([0.5] if curve else []) + [0.5, 0.5]
                out.append({"id": "humanize_%s_%s_%d" % (name, "curve" if curve else "straight", int(r * 100000)),
                            "spec": {"seed": 3, "random_script": script, "frames": [], "calls": [{"fn": "humanize", "name": name, "curve": curve}]}})
    for curve_r, sloppy_r, pause_r in ((0.91, 0.5, 0.5), (0.92, 0.5, 0.5), (0.99, 0.5, 0.5), (0.5, 0.06, 0.5), (0.5, 0.07, 0.5), (0.5, 0.0, 0.5),
                                       (0.5, 0.5, 0.05), (0.5, 0.5, 0.06), (0.5, 0.5, 0.0), (0.5, 0.5, 0.99)):
        out.append({"id": "humanize_draws_%d_%d_%d" % (curve_r * 100, sloppy_r * 100, pause_r * 100),
                    "spec": {"seed": 5, "random_script": [0.1, curve_r, sloppy_r, pause_r], "frames": [],
                             "calls": [{"fn": "humanize", "name": "great", "curve": True}]}})
    for seed in range(1, 31):
        out.append({"id": "humanize_seed_%d" % seed, "spec": {"seed": seed, "frames": [], "calls": [{"fn": "humanize", "name": "great", "curve": True}] * 4}})
    out.append({"id": "humanize_an_unknown_target", "spec": {"seed": 2, "frames": [], "calls": [{"fn": "humanize", "name": "odd", "curve": False}]}})
    return out


def ball_stories():
    """throw_ball(): the options, the 'realistic' profile, the simple throw."""
    out = []
    common = dict(shot_seconds=0.3, spin_seconds=0.9, release_seconds=0.35, params=[[-880.0, 190.0]], swipe_seconds=0.3)
    f = flight_frame(884, 772)
    frames = [ring_frame(0.9), f, f, f, f]
    shots = [0, 1, 2, 3, 4]
    ball = {"fn": "throw_ball"}
    for name in ("great", "nice", "excellent", "Great", "EXCELLENT"):
        out.append(story("ball_target_%s" % name, [ball], frames, shots=shots, settings={"throw_target": name}, **common))
    out.append(story("ball_target_off_is_a_simple_throw", [ball], frames, shots=shots, settings={"throw_target": "off"}, **common))
    out.append(story("ball_target_off_with_a_curve", [ball], frames, shots=shots, settings={"throw_target": "off", "curveball": True}, **common))
    out.append(story("ball_curve_with_a_target", [ball], frames, shots=shots, settings={"throw_target": "great", "curveball": True}, **common))
    out.append(story("ball_an_unknown_target", [ball], frames, shots=shots, settings={"throw_target": "perfect"}, **common))
    out.append(story("ball_the_target_is_not_set", [ball], frames, shots=shots, seed=4, **common))
    out.append(story("ball_no_single_touch_events_on_this_phone", [ball], frames, shots=shots, settings={"throw_target": "great", "curveball": True},
                     init={"cal": {"no_curve": True}}, **common))
    out.append(story("ball_single_touch_events_fail", [ball], frames, shots=shots, settings={"throw_target": "great"}, spin_outputs=["Error: inject"],
                     **common))
    out.append(story("ball_two_in_a_row_single_touch_fails", [ball, ball], frames, shots=shots, settings={"throw_target": "great"},
                     spin_outputs=["Error: inject"], **common))
    out.append(story("ball_simple_throw_the_ring_is_not_found", [ball], [empty_frame()], shots=[0], settings={"throw_target": "off"}, **common))
    out.append(story("ball_simple_throw_another_screen", [ball], frames, shots=shots, settings={"throw_target": "off"}, screen=[1080, 1350], **common))
    out.append(story("ball_simple_throw_cmd_input", [ball], frames, shots=shots, settings={"throw_target": "off"}, input=["cmd", "input"], **common))
    out.append(story("ball_simple_throw_a_ring_next_to_the_edge", [ball], [{"pic": TG.ring_ops(30, 900, 160, 0.6), "found": [TG.encounter_box(30, 900, 320)]}],
                     shots=[0], settings={"throw_target": "off"}, **common))
    for seed in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12):
        out.append(story("ball_realistic_%d" % seed, [ball], frames, shots=shots, seed=seed, settings={"throw_target": "realistic", "curveball": seed % 2 == 0}, **common))
    # the draws of the 'realistic' profile that decide: a lower target, none, a straight ball on purpose, a sloppy one
    for name, script in (("keeps_the_target", [0.1, 0.5, 0.5, 0.5]), ("a_lower_target", [0.75, 0.5, 0.5, 0.5]), ("no_timing", [0.95, 0.5, 0.5, 0.5]),
                         ("straight_on_purpose", [0.1, 0.95, 0.5, 0.5]), ("sloppy", [0.1, 0.5, 0.03, 0.5]), ("a_long_pause", [0.1, 0.5, 0.5, 0.03])):
        out.append(story("ball_realistic_%s" % name, [ball], frames, shots=shots, random_script=script, settings={"throw_target": "realistic", "curveball": True},
                         **common))
    tall = TG.encounter_box(884, 900, 300, 340)
    out.append(story("ball_simple_throw_tall_ring", [ball], [ring_frame(0.9, box=tall)], shots=[0], settings={"throw_target": "off"}, **common))
    out.append(story("ball_realistic_without_curve", [ball], frames, shots=shots, random_script=[0.1, 0.5, 0.5], settings={"throw_target": "realistic"}, **common))
    out.append(story("ball_two_throws_learn", [ball, ball, ball], frames, shots=shots + shots + shots, seed=8,
                     settings={"throw_target": "great", "curveball": True}, **common))
    out.append(story("ball_the_option_is_a_number", [ball], frames, shots=shots, settings={"throw_target": "great", "curveball": 1}, **common))
    out.append(story("ball_the_target_is_a_number", [ball], frames, shots=shots, settings={"throw_target": 5}, **common))
    return out


def direct_stories():
    """aim(), ring_track() and watch_flight() asked for by themselves."""
    out = []
    land = flight_frame(884, 772)
    box = list(RING_BOX)
    far = list(TG.encounter_box(884, 900, 320))
    out.append(story("aim_a_ring", [{"fn": "aim"}], [ring_frame(0.6)], shots=[0], shot_seconds=0.3, params=[[-880.0, 190.0]]))
    out.append(story("aim_a_tall_ring", [{"fn": "aim"}], [ring_frame(0.6, box=TG.encounter_box(884, 900, 300, 340))], shots=[0], shot_seconds=0.3,
                     params=[[-880.0, 190.0]]))
    out.append(story("track_a_tall_ring", [{"fn": "ring_track", "first": 0, "live": True}], [ring_frame(0.9, box=TG.encounter_box(884, 900, 300, 340)), ring_frame(0.85)],
                     live_frames=[[[0.1, 1]]]))
    out.append(story("flight_a_tall_ring", [{"fn": "watch_flight", "before": 0, "ring": list(TG.encounter_box(884, 900, 300, 340))}],
                     [ring_frame(0.5), flight_frame(884 + 110, 772), flight_frame(884 + 110, 772)], shots=[1, 2, 1, 2], shot_seconds=0.3))
    out.append(story("aim_no_ring", [{"fn": "aim"}], [empty_frame()], shots=[0], shot_seconds=0.3))
    out.append(story("aim_a_ring_that_is_not_one", [{"fn": "aim"}], [{"pic": TG.ring_ops(884, 1900, 160, 0.6), "found": [TG.encounter_box(884, 1900, 320)]}],
                     shots=[0], shot_seconds=0.3))
    out.append(story("aim_another_screen", [{"fn": "aim"}], [ring_frame(0.6)], shots=[0], screen=[1080, 1350]))
    out.append(story("aim_cmd_input", [{"fn": "aim"}], [ring_frame(0.6)], shots=[0], input=["cmd", "input"]))
    out.append(story("track_no_video", [{"fn": "ring_track", "first": 0}], [ring_frame(0.6)], shots=[0]))
    out.append(story("track_a_ring", [{"fn": "ring_track", "first": 0, "t_first": 999.95, "live": True}], [ring_frame(0.9), ring_frame(0.85), ring_frame(0.8)],
                     live_frames=[[[0.1, 1], [0.15, 2], [0.3, 2]]]))
    out.append(story("track_a_ring_without_a_time", [{"fn": "ring_track", "first": 0, "live": True}], [ring_frame(0.9), ring_frame(0.85)],
                     live_frames=[[[0.1, 1]]]))
    out.append(story("track_no_ring", [{"fn": "ring_track", "first": 0, "live": True}], [empty_frame()], live_frames=[[[0.1, 0]]]))
    out.append(story("track_pictures_too_close", [{"fn": "ring_track", "first": 0, "live": True}], [ring_frame(0.9), ring_frame(0.85)],
                     live_frames=[[[0.05, 1], [0.1, 1], [0.15, 1], [0.2, 1], [0.25, 1]]]))
    out.append(story("track_a_ring_that_cannot_be_read", [{"fn": "ring_track", "first": 0, "live": True}], [unreadable_frame(), ring_frame(0.9)],
                     live_frames=[[[0.1, 1], [0.2, 0]]]))
    out.append(story("flight_screenshots", [{"fn": "watch_flight", "before": 0, "ring": far}], [ring_frame(0.5), land, land, land, land], shots=[1, 2, 3, 4],
                     shot_seconds=0.3))
    out.append(story("flight_without_a_ring", [{"fn": "watch_flight", "before": 0, "ring": None}], [ring_frame(0.5), land, land, land, land], shots=[1, 2, 3, 4],
                     shot_seconds=0.3))
    out.append(story("flight_live", [{"fn": "watch_flight", "before": 0, "ring": far, "live": True}], [ring_frame(0.5), land, land],
                     live_frames=[[[0.1, 1], [0.2, 2]]]))
    out.append(story("flight_live_nine_pictures", [{"fn": "watch_flight", "before": 0, "ring": far, "live": True}], [ring_frame(0.5), land, flight_frame(500, 772)],
                     live_frames=[[[0.05 * i, 1 + i % 2] for i in range(1, 10)]]))
    out.append(story("flight_live_none", [{"fn": "watch_flight", "before": 0, "ring": far, "live": True}], [ring_frame(0.5), land, land, land, land],
                     live_frames=[[]], shots=[1, 2, 3, 4], shot_seconds=0.3))
    out.append(story("flight_none_at_all", [{"fn": "watch_flight", "before": 0, "ring": far}], [ring_frame(0.5)], shots=["error: a", "error: b", "error: c", "error: d"]))
    return out


# ---------------------------------------------------------------------- the file

def all_stories():
    return stories() + humanize_stories() + ball_stories() + direct_stories()


def capture():
    return {"start": START, "mono": MONO, "cases": [dict(c, events=record(c["spec"])) for c in all_stories()]}


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
