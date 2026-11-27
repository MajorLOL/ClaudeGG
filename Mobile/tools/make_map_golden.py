#!/usr/bin/env python3
"""Makes tests/fixtures/map_golden.json.qz (JSON, packed the way qCompress() of Qt does: the length, then zlib): what gamebot.py does at
the map of Pokémon GO - the looks at the map (Brain.map_objects, Brain.second_look), do_map() (a Pokémon to catch, a PokéStop to open,
turning the camera, the fast catch that is checked on the map) and do_pokestop() (spinning a stop, a bag that is full) - as the file
that the C++ port (SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoMap.cpp and ..Brain.cpp) is tested against.

    python3 tools/make_map_golden.py            writes the file
    python3 tools/make_map_golden.py --check    says whether the file is what the code does now (the stories stored in it are played again)

The file has four parts:
  readers    pictures (white, with filled rectangles of colour) and what ring_spun(), bag_full(), looks_spun() and box_full_ball() make of them
  constants  the numbers of the map and of the stop
  cases      stories: a list of calls (do_map / do_pokestop, each with the picture it is given) with the EVENTS that they make, with the time
             of a fake clock (it starts at 1000.0 and only moves with the screenshots and the sleeps).  What the code is GIVEN:
               shot            a screenshot (which of the frames of the story, and whether it was a quick or a real one)
               ssd             the map detector looked at a part of the picture (where, the certainty it was asked for) and found these boxes
               random          a number that was drawn
               day_count       the text of the counters of the day ("(today: 3 caught, ...)")
               bag, gone ...   what the parts that are not ported yet (the gifts, the bag, the storage) said
             what it DOES (the C++ port has to do the same, in this order):
               tap, swipe, swipe_async, back, sleep, log, save, later (something started again after a while), and the calls of the parts
               that are not ported yet, then at the end of every call: result (what it returned) and state (what it remembers)."""
import argparse
import json
import math
import os
import queue
import random as pyrandom
import struct
import sys
import types
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_start_golden as ST  # noqa: E402  (the pictures, the clock and the colours are the same)
from make_start_golden import H, W, START, Clock, Rec, make_picture, rect, px, exact, near, mean  # noqa: E402,F401
import cv2  # noqa: E402
import numpy as np  # noqa: E402
import gamebot as G  # noqa: E402
import spin_stop as S  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "tests", "fixtures", "map_golden.json.qz")

PURPLE = near(140, 150, 200)                    # the purple of a stop that was spun, and of the ring
BLUE = near(100, 200, 220)                      # the blue of a stop that can be spun
PINK = near(165, 120, 200)                      # the pink of the message 'Your Item Bag is full.'
GOLD = near(22, 160, 200)                       # the gold of the Poké Ball button when the storage is full
RING_CX, RING_CY = S.RING_CENTER
RING_LO, RING_HI = S.RING_R


# ---------------------------------------------------------------------- the readers of pixels

def ring_fraction(x_cut):
    """The share of the ring around the photo (as ring_spun() takes it) that lies left of the column x_cut."""
    yy, xx = np.mgrid[:H, :W]
    d = np.hypot(xx - RING_CX, yy - RING_CY)
    ring = (d > RING_LO) & (d < RING_HI)
    return float((ring & (xx < x_cut)).sum() / ring.sum())


_keys = []


def pick(h=None, s=None, v=None, s_min=0, v_min=0):
    """A colour (BGR) with exactly these components of the HSV of OpenCV (None: any, from s_min / v_min up), one in the middle of those
    that there are."""
    if not _keys:
        ST.exact(120, 150, 220)                                     # (fills the table of all colours)
        _keys.append(np.fromiter(ST._hsv_all.keys(), dtype=np.int64))
    keys = _keys[0]
    hh, ss, vv = keys >> 16, (keys >> 8) & 255, keys & 255
    ok = np.ones(len(keys), bool)
    if h is not None:
        ok &= hh == h
    ok &= (ss == s) if s is not None else (ss >= s_min)
    ok &= (vv == v) if v is not None else (vv >= v_min)
    found = np.flatnonzero(ok)
    if not len(found):
        raise KeyError((h, s, v, s_min, v_min))
    return [int(c) for c in ST._hsv_all[int(keys[found[len(found) // 2]])]]


def ring_pixels():
    """What the ring of ring_spun() is made of: the mask of its pixels, and the least number of purple ones that make it purple."""
    yy, xx = np.mgrid[:H, :W]
    d2 = (xx - RING_CX) ** 2 + (yy - RING_CY) ** 2
    mask = (d2 > RING_LO ** 2) & (d2 < RING_HI ** 2)
    total = int(mask.sum())
    need = next(k for k in range(int(0.4 * total) - 3, total) if k / total > 0.4)
    return mask, d2, total, need


def ring_exact(mask, side, count):
    """A picture on which exactly `count` pixels of the ring are purple, those that are the first from one side (a whole number of
    columns or rows, and the first pixels of the next one)."""
    if side in ("left", "right"):
        per = mask.sum(axis=0)
        order = list(range(W)) if side == "left" else list(range(W - 1, -1, -1))
    else:
        per = mask.sum(axis=1)
        order = list(range(H)) if side == "top" else list(range(H - 1, -1, -1))
    done, n = 0, 0
    while done + per[order[n]] <= count:
        done += per[order[n]]
        n += 1
    rest = count - done                                              # in the next column or row, from the end that is the first
    line = order[n]
    items = []
    if side == "left":
        items.append(px(0, 0, n, H, PURPLE))
    elif side == "right":
        items.append(px(W - n, 0, n, H, PURPLE))
    elif side == "top":
        items.append(px(0, 0, W, n, PURPLE))
    else:
        items.append(px(0, H - n, W, n, PURPLE))
    if rest:
        along = np.flatnonzero(mask[:, line] if side in ("left", "right") else mask[line, :])
        if side in ("left", "right"):
            last = int(along[rest - 1])
            items.append(px(line, 0, 1, last + 1, PURPLE))
        else:
            last = int(along[rest - 1])
            items.append(px(0, line, last + 1, 1, PURPLE))
    return items


def reader_cases():
    """[{id, pic, ring, bag, full, spun: [{box, value}]}]: what the four readers make of pictures that are made to be exactly on the edge."""
    cases = []

    def add(name, pic, boxes=()):
        img = make_picture(pic)
        entry = {"id": name, "pic": pic, "ring": bool(S.ring_spun(img)), "bag": bool(S.bag_full(img)), "full": bool(G.box_full_ball(img)),
                 "spun": [{"box": list(b), "value": bool(G.looks_spun(img, ("pokestop", 0.9) + tuple(b)))} for b in boxes]}
        cases.append(entry)

    add("white", ["white"])
    # the ring: purple on the left of a column; the column where the share crosses 0.4
    cut = next(c for c in range(RING_CX - 500, RING_CX + 500) if ring_fraction(c) > 0.4)
    for c in (cut - 40, cut - 2, cut - 1, cut, cut + 1, cut + 2, cut + 40, RING_CX - 400, RING_CX, RING_CX + 400):
        add("ring_cut_%d" % c, rect(px(0, 0, c, H, PURPLE)))
    # ... and to the last pixel: the ring with exactly as many purple pixels as make it purple, and one less, from every side
    mask, d2, total, need = ring_pixels()
    for side in ("left", "right", "top", "bottom"):
        for count in (need - 1, need):
            add("ring_%s_%d" % (side, count - need), rect(*ring_exact(mask, side, count)))
    # the pixels exactly as far from the middle as the ring begins (or ends) are not part of it
    for radius, name in ((RING_LO, "inner"), (RING_HI, "outer")):
        on = np.argwhere(d2 == radius ** 2)
        right = [px(int(x), int(y), 1, 1, PURPLE) for y, x in on if x > RING_CX]
        add("ring_circle_%s" % name, rect(*(ring_exact(mask, "left", need - 1) + right)))
        left = [px(int(x), int(y), 1, 1, PURPLE) for y, x in on if x < RING_CX]
        add("ring_circle_%s_left" % name, rect(*(ring_exact(mask, "right", need - 1) + left)))
    for h in (124, 125, 126, 145, 164, 165, 166):
        for sat in (81, 80, 150, 255):
            try:
                colour = pick(h=h, s=sat)
            except KeyError:
                continue
            add("ring_hsv_%d_%d" % (h, sat), rect(px(0, 0, cut + 30, H, colour)))
    # the message: pink in rows 1065 - 1140, columns 580 - 1200; more than 0.3 of them
    for c in (700, 760, 765, 766, 767, 768, 800, 1100):
        add("bag_cut_%d" % c, rect(px(580, 1065, c - 580, 75, PINK)))
    add("bag_rows_short", rect(px(580, 1066, 700, 74, PINK)))
    add("bag_rows_high", rect(px(580, 1064, 700, 76, PINK)))
    add("bag_outside", rect(px(580, 1000, 700, 60, PINK)))
    # ... and to the last pixel: 13951 pink pixels (more than 0.3 of the 46500) on the edges of the part that is looked at, and 13950
    # (not enough) with the pixels of every edge just outside it
    edges = {"top": px(580, 1065, 620, 1, PINK), "bottom": px(580, 1139, 620, 1, PINK),
             "left": px(580, 1065, 1, 75, PINK), "right": px(1199, 1065, 1, 75, PINK)}
    outside = {"top": px(580, 1064, 620, 1, PINK), "bottom": px(580, 1140, 620, 1, PINK),
               "left": px(579, 1065, 1, 75, PINK), "right": px(1200, 1065, 1, 75, PINK)}
    for edge, line in edges.items():
        rest = 13951 - (620 if edge in ("top", "bottom") else 75)
        rows, extra = divmod(rest, 600)
        block = [px(600, 1075, 600, rows, PINK)] + ([px(600, 1075 + rows, extra, 1, PINK)] if extra else [])
        add("bag_edge_%s" % edge, rect(line, *block))
    inside = [px(600, 1075, 600, 23, PINK), px(600, 1098, 150, 1, PINK)]                  # 13950
    for edge, line in outside.items():
        add("bag_out_%s" % edge, rect(*(inside + [line])))
    add("bag_13950", rect(*inside))
    add("bag_13951", rect(*(inside + [px(600, 1099, 1, 1, PINK)])))
    for h in (149, 150, 151, 177, 178, 179):
        for sat, val in ((51, 141), (50, 141), (51, 140), (200, 255)):
            try:
                colour = pick(h=h, s=sat, v=val)
            except KeyError:
                try:
                    colour = pick(h=h, s=sat, v_min=val if val > 200 else 142)
                except KeyError:
                    continue
            add("bag_hsv_%d_%d_%d" % (h, sat, val), rect(px(580, 1065, 700, 75, colour)))
    for sat in (49, 50, 51, 52):
        add("bag_sat_%d" % sat, rect(px(580, 1065, 700, 75, pick(h=165, s=sat, v_min=142))))
    for val in (139, 140, 141, 142):
        add("bag_val_%d" % val, rect(px(580, 1065, 700, 75, pick(h=165, s_min=60, v=val))))
    # the gold of the Poké Ball button: more than 300 pixels in rows 1920 - 2050, columns 820 - 940
    for n in (299, 300, 301, 302):                                   # two whole rows of 120 pixels and some of the next one
        add("full_%d" % n, rect(px(820, 1920, 120, 2, GOLD), px(820, 1922, n - 240, 1, GOLD)))
    add("full_outside", rect(px(820, 1919, 400, 1, GOLD), px(820, 2050, 400, 1, GOLD), px(819, 1930, 1, 100, GOLD), px(940, 1930, 1, 100, GOLD)))
    # ... and with the pixels of each edge: 301 with the edge, and 300 with the edge just outside
    inner = {"top": [px(820, 1920, 120, 1, GOLD), px(830, 1925, 90, 1, GOLD), px(830, 1926, 91, 1, GOLD)],
             "bottom": [px(820, 2049, 120, 1, GOLD), px(830, 1925, 90, 1, GOLD), px(830, 1926, 91, 1, GOLD)],
             "left": [px(820, 1920, 1, 130, GOLD), px(830, 1925, 90, 1, GOLD), px(830, 1926, 81, 1, GOLD)],
             "right": [px(939, 1920, 1, 130, GOLD), px(830, 1925, 90, 1, GOLD), px(830, 1926, 81, 1, GOLD)]}
    for edge, items in inner.items():
        add("full_edge_%s" % edge, rect(*items))
    three = [px(830, 1925, 100, 1, GOLD), px(830, 1926, 100, 1, GOLD), px(830, 1927, 100, 1, GOLD)]
    for edge, line in {"top": px(820, 1919, 120, 1, GOLD), "bottom": px(820, 2050, 120, 1, GOLD),
                       "left": px(819, 1920, 1, 130, GOLD), "right": px(940, 1920, 1, 130, GOLD)}.items():
        add("full_out_%s" % edge, rect(*(three + [line])))
    for h in (11, 12, 13, 34, 35, 36):
        for sat in (111, 110, 150, 255):
            try:
                colour = pick(h=h, s=sat, v_min=151)
            except KeyError:
                continue
            add("full_hsv_%d_%d" % (h, sat), rect(px(820, 1920, 120, 3, colour)))
    for val in (149, 150, 151, 152):
        add("full_val_%d" % val, rect(px(820, 1920, 120, 3, pick(h=20, s_min=112, v=val))))
    for sat in (109, 110, 111, 112):
        add("full_sat_%d" % sat, rect(px(820, 1920, 120, 3, pick(h=20, s=sat, v_min=152))))
    # a stop that was spun (purple) or not (blue): the colours in the box of the stop, which can reach out of the picture
    box = (884, 1000, 200, 200)                                       # x, y, w, h of the box (the middle and the size)
    left, top = box[0] - box[2] // 2, box[1] - box[3] // 2
    for blue_n, purple_n in ((0, 0), (100, 0), (0, 100), (100, 100), (100, 101), (101, 100), (1, 2), (200, 199)):
        pics = []
        if blue_n:
            pics.append(px(left, top, blue_n, 1, BLUE))
        if purple_n:
            pics.append(px(left, top + 1, purple_n, 1, PURPLE))
        add("spun_%d_%d" % (blue_n, purple_n), rect(*pics) if pics else ["white"], [box])
    # one purple pixel on every edge of the box (it is purple then), and one just outside it (it is not)
    right_edge, bottom_edge = left + box[2] - 1, top + box[3] - 1
    for name, x, y in (("top", 884, top), ("bottom", 884, bottom_edge), ("left", left, 1000), ("right", right_edge, 1000)):
        add("spun_edge_%s" % name, rect(px(x, y, 1, 1, PURPLE)), [box])
    for name, x, y in (("top", 884, top - 1), ("bottom", 884, bottom_edge + 1), ("left", left - 1, 1000), ("right", right_edge + 1, 1000)):
        add("spun_out_%s" % name, rect(px(x, y, 1, 1, PURPLE)), [box])
    components = []                                                   # (name, colour, is it blue?)
    for h in (91, 92, 93, 107, 108, 109):
        components.append(("blue_h%d" % h, pick(h=h, s_min=170), True))
    for sat in (164, 165, 166, 167):
        components.append(("blue_s%d" % sat, pick(h=100, s=sat), True))
    for h in (127, 128, 129, 149, 150, 151):
        components.append(("purple_h%d" % h, pick(h=h, s_min=75, v_min=125), False))
    for sat in (69, 70, 71, 72):
        components.append(("purple_s%d" % sat, pick(h=140, s=sat, v_min=125), False))
    for val in (119, 120, 121, 122):
        components.append(("purple_v%d" % val, pick(h=140, s_min=75, v=val), False))
    for name, colour, is_blue in components:
        other = [px(left, top + 1, 50, 1, PURPLE if is_blue else BLUE)]
        add("spun_hsv_%s" % name, rect(px(left, top, 100, 1, colour), *other), [box])
    for box in ((5, 5, 100, 100), (0, 0, 40, 40), (W - 10, H - 10, 200, 200), (884, 1000, 1, 1), (884, 1000, 0, 0), (-20, 1000, 60, 60),
                (884, 1000, 3, 3), (700, 700, 61, 61)):
        add("spun_box_%d_%d_%d_%d" % box, rect(px(max(box[0] - 30, 0), max(box[1] - 30, 0), 60, 60, PURPLE),
                                               px(max(box[0] - 30, 0), max(box[1] - 30, 0) + 60, 10, 5, BLUE)), [box])
    return cases


# ---------------------------------------------------------------------- the fake phone

STATE_DICTS = ("enc", "throw_info", "enc_xy", "fast_pending", "fast_state", "last_tap", "near_state", "rotation", "perf",
               "storage_state", "bag_state", "menu_check", "gift_timer")
_defaults = {name: json.loads(json.dumps(getattr(G, name), default=list)) for name in STATE_DICTS}


def jsonable(value):
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return round(float(value), 6)
    return value


def snapshot():
    state = {name: jsonable(getattr(G, name)) for name in STATE_DICTS}
    state["cooldown"] = jsonable(G.cooldown)
    state["spin"] = bool(G.SPIN)
    state["catch"] = bool(G.CATCH)
    return state


def restore(init):
    for name in STATE_DICTS:
        target = getattr(G, name)
        target.clear()
        target.update(json.loads(json.dumps(_defaults[name])))
        if name in init:
            target.update(init[name])
    G.cooldown[:] = [tuple(c) for c in init.get("cooldown", [])]
    G.SPIN = bool(init.get("spin", True))
    G.CATCH = bool(init.get("catch", True))


class FakeRandom:
    """random.uniform() and random.random() of gamebot.py: numbers from a generator with a seed, each told as an event."""

    def __init__(self, seed, rec, script=()):
        self.rnd, self.rec = pyrandom.Random(seed), rec
        self.script = list(script)              # the first random() answers: numbers on a threshold, which a seed never gives

    def uniform(self, lo, hi):
        value = self.rnd.uniform(lo, hi)
        self.rec.add("random", "uniform", lo, hi, value)
        return value

    def random(self):
        value = self.script.pop(0) if self.script else self.rnd.random()
        self.rec.add("random", "random", None, None, value)
        return value


class SyncPool:
    """ThreadPoolExecutor, without the threads: what is asked is done at once, in order."""

    def submit(self, fn, *args):
        result = fn(*args)
        return types.SimpleNamespace(result=lambda: result)

    def map(self, fn, items):
        return [fn(i) for i in items]


class World:
    def __init__(self, spec):
        self.spec = spec
        self.frames = spec["frames"]
        self.next = 1                         # the frame that the next screenshot of the story shows
        self.arrays = {}                      # id of an array -> (index of its frame, the array)
        self.last = None                      # the picture that the last call was given

    def picture(self, index, same=False):
        """A picture of the frame: every screenshot is a new array (the code tells screenshots apart by their identity); `same`: the
        picture of the call before, once more."""
        if same and self.last is not None:
            return self.last
        img = make_picture(self.frames[index]["pic"]).copy()
        self.arrays[id(img)] = (index, img)
        self.last = img
        return img

    def frame_of(self, crop):
        base = crop
        while base.base is not None:
            base = base.base
        return self.arrays[id(base)][0], base

    def offset(self, crop, base):
        off = crop.__array_interface__["data"][0] - base.__array_interface__["data"][0]
        row, rest = divmod(off, base.strides[0])
        return int(rest // base.strides[1]), int(row)

    def ssd(self, crop, th, top):
        """What the map detector finds in a part of a picture: the boxes of the world of the frame (their scores: how well each look
        sees them), as the detector gives them (the places are those of the part)."""
        index, base = self.frame_of(crop)
        x0, y0 = self.offset(crop, base)
        h0, w0 = crop.shape[:2]
        if th == 0.15:
            kind = "second"
        elif (w0, h0) == (W, H):
            kind = "whole"
        elif (w0, h0) == (650, 650):
            kind = "tile"
        elif (w0, h0) == (G.ZOOM_BOX[2] - G.ZOOM_BOX[0], G.ZOOM_BOX[3] - G.ZOOM_BOX[1]):
            kind = "zoom"
        else:
            kind = "whole"
        found = []
        for o in self.frames[index].get("world", []):
            scores = o["scores"]
            score = scores.get(kind, scores.get("all", 0.0))
            cx, cy = o["x"] - x0, o["y"] - y0
            if score >= th and 0 <= cx < w0 and 0 <= cy < h0 and o["w"] < 0.6 * w0 and o["h"] < 0.6 * h0:
                found.append((o["label"], float(score), int(cx), int(cy), int(o["w"]), int(o["h"])))
        found.sort(key=lambda b: -b[1])
        return (x0, y0, x0 + w0, y0 + h0), found[:top]


def record(spec):
    """Plays one story on the fake phone; returns the list of events."""
    Clock.t = START
    rec = Rec()
    Clock.rec = rec
    world = World(spec)
    saved_g = {n: getattr(G, n) for n in ("time", "log", "random", "setting", "wanted", "count", "save_async", "gifts_round", "check_menu_full",
                                          "check_all_full", "clean_bag", "_bag_to_map", "_resume_spin_later", "SPIN", "CATCH")}
    saved_s = {n: getattr(S, n) for n in ("time", "log", "tap", "swipe", "swipe_async", "back", "quick_screenshot", "screenshot")}
    saved_ssd = G.Brain._ssd
    saved_cooldown = list(G.cooldown)
    try:
        restore(spec.get("init", {}))
        G.time = S.time = Clock
        G.log = S.log = lambda text: rec.add("log", text)
        G.random = FakeRandom(spec.get("seed", 1), rec, spec.get("random_script", ()))
        settings = dict(spec.get("settings", {}))
        wanted = {"gifts_open": False, "gifts_send": False, "daily_cycle": False, "close_when_full": False, "spin_only_when_full": False}
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
        G.save_async = lambda name, img: rec.add("save", name)
        G.gifts_round = lambda: rec.add("gifts_round")
        G.check_menu_full = lambda: rec.add("check_menu_full")
        G.check_all_full = lambda: rec.add("check_all_full")
        G._bag_to_map = lambda: rec.add("bag_to_map")

        def clean_bag():
            rec.add("clean_bag", spec.get("bag_gone", 0), spec.get("bag_error"))
            if spec.get("bag_error"):
                raise RuntimeError(spec["bag_error"])
            return spec.get("bag_gone", 0)
        G.clean_bag = clean_bag
        G._resume_spin_later = lambda: rec.add("later", "spin", S.BAG_FULL_WAIT)
        S.tap = lambda x, y, ms=120: rec.add("tap", x, y)
        S.swipe = lambda x1, y1, x2, y2, ms=300: rec.add("swipe", x1, y1, x2, y2, ms)
        S.swipe_async = lambda x1, y1, x2, y2, ms=300: rec.add("swipe_async", x1, y1, x2, y2, ms)
        S.back = lambda: rec.add("back")

        def shot(kind):
            def take(on_grab=None):
                index = min(world.next, len(world.frames) - 1)
                world.next += 1
                Clock.t += spec.get("shot_seconds", 0.0)
                rec.add("shot", index, kind)
                img = make_picture(world.frames[index]["pic"]).copy()
                world.arrays[id(img)] = (index, img)
                if on_grab is not None:
                    on_grab()
                return img
            return take
        S.quick_screenshot = shot("quick")
        S.screenshot = shot("real")

        def fake_ssd(self, it, anchors, labels, img, th=0.2, top=10):
            box, found = world.ssd(img, th, top)
            Clock.t += spec.get("ssd_seconds", 0.0)
            rec.add("ssd", list(box), th, top, [list(f) for f in found])
            return found
        G.Brain._ssd = fake_ssd

        brain = G.Brain.__new__(G.Brain)
        brain._seen = None
        brain.pair = [None, None]
        brain.map = None
        brain.map_anchors = None
        brain.map_pool = queue.Queue()
        brain.map_pool.put(None)
        brain.workers = SyncPool()
        brain.pair_pool = SyncPool()

        for call in spec["calls"]:
            if "settings" in call:
                settings.update(call["settings"])
            if "wanted" in call:
                wanted.update(call["wanted"])
            if "advance" in call:
                Clock.t += call["advance"]
            rec.add("call", call["fn"], call.get("img"), bool(call.get("same")))
            if "img" in call:
                world.next = max(world.next, call["img"] + 1)
            try:
                if call["fn"] == "do_map":
                    result = G.do_map(brain, world.picture(call["img"], call.get("same", False)))
                elif call["fn"] == "do_pokestop":
                    result = G.do_pokestop(brain, world.picture(call["img"], call.get("same", False)))
                elif call["fn"] == "second_look":
                    seen = brain.second_look(world.picture(call["img"], call.get("same", False)), call["x"], call["y"])
                    result = [list(seen) if seen else None, brain.second_best]
                elif call["fn"] == "map_objects":
                    objs = brain.map_objects(world.picture(call["img"], call.get("same", False)), tiles=call.get("tiles", False))
                    result = [[list(o) for o in objs], brain.hint]
                elif call["fn"] == "fire_rotation":
                    G.fire_rotation()
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
        G.Brain._ssd = saved_ssd
        G.cooldown[:] = saved_cooldown
        restore({})


# ---------------------------------------------------------------------- the stories

def obj(label, x, y, w=150, h=150, **scores):
    return {"label": label, "x": x, "y": y, "w": w, "h": h, "scores": scores or {"all": 0.6}}


def pokemon(x, y, w=150, h=150, **scores):
    return obj("pokemon", x, y, w, h, **(scores or {"all": 0.6}))


def stop(x, y, **scores):
    return obj("pokestop", x, y, 120, 140, **(scores or {"all": 0.7}))


def frame(world=(), pic=None):
    return {"pic": pic or ["white"], "world": list(world)}


MAP_PIC = rect(ST.MAP)
STOP_BLUE = lambda x, y: px(x - 40, y - 40, 80, 80, BLUE)          # noqa: E731
STOP_PURPLE = lambda x, y: px(x - 40, y - 40, 80, 80, PURPLE)      # noqa: E731
PURPLE_RING = rect(px(0, 0, RING_CX + 150, H, PURPLE))             # the ring around the photo is purple: spun
PINK_MESSAGE = rect(px(580, 1065, 620, 75, PINK))
GOLD_BUTTON = rect(px(820, 1920, 120, 130, GOLD))                  # the storage is full


def stories():
    out = []

    def add(name, spec):
        spec.setdefault("shot_seconds", 0.4)
        spec.setdefault("ssd_seconds", 0.3)
        out.append({"id": name, "spec": spec})

    def one(name, fn, frames, **kw):
        add(name, dict(calls=[{"fn": fn, "img": 0}], frames=frames, **kw))

    # --- the looks at the map
    p = pokemon(500, 1100, whole=0.55, zoom=0.5)
    add("look_whole_screen", {"calls": [{"fn": "map_objects", "img": 0}], "frames": [frame([p, stop(900, 900, all=0.8)])]})
    add("look_zoom_adds_one", {"calls": [{"fn": "map_objects", "img": 0}], "frames": [frame([pokemon(500, 1100, whole=0.1, zoom=0.5)])]})
    add("look_zoom_weak", {"calls": [{"fn": "map_objects", "img": 0}], "frames": [frame([pokemon(500, 1100, whole=0.1, zoom=0.36)])]})
    add("look_zoom_and_whole_agree", {"calls": [{"fn": "map_objects", "img": 0}], "frames": [frame([pokemon(500, 1100, whole=0.5, zoom=0.5),
                                                                                                         pokemon(560, 1150, whole=0.1, zoom=0.6)])]})
    add("look_hint_only_weak", {"calls": [{"fn": "map_objects", "img": 0}], "frames": [frame([pokemon(100, 800, whole=0.25)])]})
    add("look_nothing", {"calls": [{"fn": "map_objects", "img": 0}], "frames": [frame([])]})
    add("look_tiles_two_agree", {"calls": [{"fn": "map_objects", "img": 0, "tiles": True}],
                                 "frames": [frame([pokemon(400, 1000, tile=0.6)])]})
    add("look_tiles_one_alone", {"calls": [{"fn": "map_objects", "img": 0, "tiles": True}],
                                 "frames": [frame([pokemon(10, 710, tile=0.6)])]})
    add("look_tiles_weak", {"calls": [{"fn": "map_objects", "img": 0, "tiles": True}],
                            "frames": [frame([pokemon(400, 1000, tile=0.45)])]})
    add("look_tiles_whole_already", {"calls": [{"fn": "map_objects", "img": 0, "tiles": True}],
                                     "frames": [frame([pokemon(400, 1000, tile=0.6, whole=0.6)])]})
    add("look_tiles_two_places", {"calls": [{"fn": "map_objects", "img": 0, "tiles": True}],
                                  "frames": [frame([pokemon(400, 1000, tile=0.6), pokemon(1300, 1500, tile=0.7), pokemon(1310, 1520, tile=0.5),
                                                    pokemon(800, 760, tile=0.55)])]})
    add("look_again_same_picture", {"calls": [{"fn": "map_objects", "img": 0}, {"fn": "map_objects", "img": 0, "tiles": True, "same": True}],
                                    "frames": [frame([pokemon(400, 1000, whole=0.1, zoom=0.1, tile=0.6)])]})
    add("look_again_other_picture", {"calls": [{"fn": "map_objects", "img": 0}, {"fn": "map_objects", "img": 0, "tiles": True}],
                                     "frames": [frame([pokemon(400, 1000, whole=0.1, zoom=0.1, tile=0.6)])]})
    add("look_same_picture_twice", {"calls": [{"fn": "map_objects", "img": 0}, {"fn": "map_objects", "img": 0, "same": True}],
                                    "frames": [frame([pokemon(500, 1100, whole=0.55, zoom=0.5)])]})
    add("map_reuses_the_quick_look", {"calls": [{"fn": "map_objects", "img": 0}, {"fn": "do_map", "img": 0, "same": True}],
                                      "frames": [frame([pokemon(500, 1100, all=0.6)]), frame([pokemon(500, 1100, all=0.6)])]})
    add("second_look_found", {"calls": [{"fn": "map_objects", "img": 0}, {"fn": "second_look", "img": 1, "x": 500, "y": 1100}],
                              "frames": [frame([p]), frame([pokemon(520, 1090, w=160, h=140, all=0.7)])]})
    add("second_look_gone", {"calls": [{"fn": "map_objects", "img": 0}, {"fn": "second_look", "img": 1, "x": 500, "y": 1100}],
                             "frames": [frame([p]), frame([])]})
    add("second_look_only_weak", {"calls": [{"fn": "map_objects", "img": 0}, {"fn": "second_look", "img": 1, "x": 500, "y": 1100}],
                                  "frames": [frame([p]), frame([pokemon(500, 1100, all=0.2)])]})
    add("second_look_zoom_part", {"calls": [{"fn": "map_objects", "img": 0}, {"fn": "second_look", "img": 1, "x": 500, "y": 1100}],
                                  "frames": [frame([pokemon(500, 1100, whole=0.1, zoom=0.5)]), frame([pokemon(500, 1100, whole=0.0, zoom=0.0, second=0.2)])]})
    add("second_look_far_away", {"calls": [{"fn": "map_objects", "img": 0}, {"fn": "second_look", "img": 1, "x": 500, "y": 1100}],
                                 "frames": [frame([p]), frame([pokemon(500, 1260, all=0.7)])]})
    add("second_look_two_near", {"calls": [{"fn": "map_objects", "img": 0}, {"fn": "second_look", "img": 1, "x": 500, "y": 1100}],
                                 "frames": [frame([p]), frame([pokemon(480, 1100, all=0.6), pokemon(530, 1120, all=0.6, w=170)])]})

    # --- do_map: a Pokémon
    one("map_catch", "do_map", [frame([pokemon(500, 1100, all=0.6)]), frame([pokemon(520, 1090, w=160, h=140, all=0.7)])])
    one("map_catch_gone", "do_map", [frame([pokemon(500, 1100, all=0.6)]), frame([])])
    one("map_catch_gone_weak", "do_map", [frame([pokemon(500, 1100, all=0.6)]), frame([pokemon(500, 1100, second=0.2, whole=0.0, zoom=0.0, tile=0.0)])])
    one("map_catch_beside_trainer", "do_map", [frame([pokemon(950, 1560, all=0.6)]), frame([pokemon(950, 1560, w=170, h=150, all=0.7)])],
        settings={"buddy": True})
    one("map_catch_beside_trainer_left", "do_map", [frame([pokemon(820, 1560, all=0.6)]), frame([pokemon(820, 1560, w=170, h=150, all=0.7)])])
    one("map_catch_on_the_trainer", "do_map", [frame([pokemon(884, 1400, all=0.9)]), frame([])], seed=2)
    one("map_catch_buddy_blocked", "do_map", [frame([pokemon(950, 1560, all=0.6)]), frame([])], settings={"buddy": True},
        init={"near_state": {"until": 1000.0 + 600}}, seed=3)
    one("map_catch_buddy_over", "do_map", [frame([pokemon(950, 1560, all=0.6)]), frame([pokemon(950, 1560, all=0.6)])], settings={"buddy": True},
        init={"near_state": {"until": 1000.0 - 5}})
    one("map_pokemon_cooled", "do_map", [frame([pokemon(500, 1100, all=0.6)])], init={"cooldown": [[540, 1150, 1000.0 + 100]]}, seed=4)
    one("map_pokemon_cool_over", "do_map", [frame([pokemon(500, 1100, all=0.6)]), frame([pokemon(500, 1100, all=0.6)])],
        init={"cooldown": [[540, 1150, 1000.0 - 1]]})
    one("map_pokemon_on_a_stop", "do_map", [frame([pokemon(900, 900, all=0.8), stop(900, 900, all=0.8)])], seed=5)
    one("map_pokemon_low", "do_map", [frame([pokemon(500, 1830, all=0.8)])], seed=6)
    one("map_pokemon_right", "do_map", [frame([pokemon(1410, 1100, all=0.8)])], seed=7)
    one("map_pokemon_too_weak", "do_map", [frame([pokemon(500, 1100, whole=0.39, zoom=0.39)])], seed=8)
    one("map_pokemon_only_zoom", "do_map", [frame([pokemon(500, 1100, whole=0.1, zoom=0.5)]), frame([pokemon(500, 1100, second=0.4)])])
    one("map_found_by_tiles", "do_map", [frame([pokemon(400, 1000, whole=0.1, zoom=0.1, tile=0.6)]), frame([pokemon(400, 1000, second=0.5)])],
        init={"rotation": {"steps": 0}})
    one("map_tiles_skipped", "do_map", [frame([pokemon(400, 1000, whole=0.0, zoom=0.0, tile=0.6)])], init={"rotation": {"steps": 1}}, seed=9)
    one("map_tiles_hint", "do_map", [frame([pokemon(100, 800, whole=0.25, tile=0.6), pokemon(120, 820, tile=0.6)]), frame([pokemon(110, 810, second=0.5)])],
        init={"rotation": {"steps": 1}})
    one("map_catch_off", "do_map", [frame([pokemon(500, 1100, all=0.6)])], wanted={"catch": False}, seed=10)
    one("map_catch_paused", "do_map", [frame([pokemon(500, 1100, all=0.6)])], init={"catch": False}, seed=11)
    one("map_catch_resets_the_turn", "do_map", [frame([pokemon(500, 1100, all=0.6)]), frame([pokemon(500, 1100, all=0.6)])],
        init={"rotation": {"steps": 3, "turned": 900.0, "goal": 2500.0}})

    # --- do_map: a stop
    one("map_stop", "do_map", [frame([stop(900, 900)])])
    one("map_stop_weak", "do_map", [frame([stop(900, 900, all=0.29)])], seed=12)
    one("map_stop_spun", "do_map", [frame([stop(900, 900)], rect(STOP_PURPLE(900, 900)))], seed=13)
    one("map_stop_blue", "do_map", [frame([stop(900, 900)], rect(STOP_BLUE(900, 900)))])
    one("map_stop_cooled", "do_map", [frame([stop(900, 900)])], init={"cooldown": [[900, 900, 1000.0 + 50]]}, seed=14)
    one("map_stop_rocket_near", "do_map", [frame([stop(900, 900), obj("rocket_pokestop", 1000, 1100, 120, 140, all=0.5)])], seed=15)
    one("map_stop_rocket_far", "do_map", [frame([stop(900, 900), obj("rocket_pokestop", 1200, 900, 120, 140, all=0.5)])])
    one("map_stop_rocket_weak", "do_map", [frame([stop(900, 900), obj("rocket_pokestop", 1000, 1100, 120, 140, all=0.39)])])
    one("map_stop_next_to_the_trainer", "do_map", [frame([stop(884, 1500)])], seed=16)
    one("map_stop_beside_the_trainer", "do_map", [frame([stop(1030, 1500)])])
    one("map_stop_off", "do_map", [frame([stop(900, 900)])], wanted={"spin": False}, seed=17)
    one("map_stop_spin_paused", "do_map", [frame([stop(900, 900)])], init={"spin": False}, seed=18)
    one("map_second_look_gone_with_a_stop_in_view", "do_map", [frame([pokemon(500, 1100), stop(900, 900)]), frame([])], seed=19)
    one("map_stop_when_catching_is_off", "do_map", [frame([pokemon(500, 1100), stop(900, 900)])], wanted={"catch": False})

    # --- do_map: nothing to do, the camera turns
    for n in range(1, 4):
        add("map_nothing_round_%d" % n, {"calls": [{"fn": "do_map", "img": 0}] * (n * 4), "frames": [frame([])], "seed": 20 + n,
                                         "settings": {"fast_look": n != 2}})
    add("map_nothing_slow", {"calls": [{"fn": "do_map", "img": 0}] * 6, "frames": [frame([])], "seed": 30, "settings": {"fast_look": False}})
    add("map_nothing_many_looks", {"calls": [{"fn": "do_map", "img": 0}] * 10, "frames": [frame([])], "seed": 31, "advance": 0.0,
                                   "settings": {"fast_look": True}})
    add("map_nothing_not_catching", {"calls": [{"fn": "do_map", "img": 0}] * 3, "frames": [frame([])], "wanted": {"catch": False}, "seed": 32})
    add("map_nothing_rotation_off_by_a_swipe", {"calls": [{"fn": "do_map", "img": 0}] * 4, "frames": [frame([])], "seed": 33,
                                                "init": {"rotation": {"steps": 2, "turned": 100.0, "goal": 300.0, "dir": -1}}})
    add("map_nothing_fired", {"calls": [{"fn": "do_map", "img": 0}] * 3, "frames": [frame([])], "seed": 34,
                              "init": {"rotation": {"steps": 2, "turned": 100.0, "goal": 4000.0, "dir": 1,
                                                    "fired": {"t": 1000.0, "swipe": [350, 900, 1000, 950, 600]}}}})
    add("map_nothing_armed", {"calls": [{"fn": "do_map", "img": 0}] * 3, "frames": [frame([])], "seed": 35,
                              "init": {"rotation": {"steps": 2, "turned": 100.0, "goal": 4000.0, "dir": 1, "armed": [[350, 900, 1000, 950, 600], 0],
                                                    "armed_at": 1000.0}}})
    add("map_looks_then_found", {"calls": [{"fn": "do_map", "img": 0}] * 2 + [{"fn": "do_map", "img": 1}],
                                 "frames": [frame([]), frame([pokemon(500, 1100)]), frame([pokemon(500, 1100)])], "seed": 36})
    add("map_undo_the_turn", {"calls": [{"fn": "do_map", "img": 0}],
                              "frames": [frame([pokemon(500, 1100)]), frame([pokemon(500, 1100)])], "seed": 37,
                              "init": {"rotation": {"steps": 2, "turned": 100.0, "goal": 4000.0, "dir": 1,
                                                    "fired": {"t": 1000.0, "swipe": [350, 900, 1000, 950, 600]}}}})
    add("map_undo_the_turn_for_a_stop", {"calls": [{"fn": "do_map", "img": 0}],
                                         "frames": [frame([stop(900, 900)]), frame([])], "seed": 38,
                                         "init": {"rotation": {"steps": 2, "turned": 100.0, "goal": 4000.0, "dir": 1,
                                                               "fired": {"t": 1000.0, "swipe": [350, 900, 1000, 950, 600]}}}})
    add("map_undo_late", {"calls": [{"fn": "do_map", "img": 0, "advance": 30.0}],
                          "frames": [frame([pokemon(500, 1100)]), frame([pokemon(500, 1100)])], "seed": 39,
                          "init": {"rotation": {"steps": 2, "turned": 100.0, "goal": 4000.0, "dir": 1,
                                                "fired": {"t": 1000.0, "swipe": [350, 900, 1000, 950, 600]}}}})

    # --- the camera that is turned while the picture is looked at (fast looking): fire_rotation() starts the swipe that was armed
    armed = [[350, 900, 1000, 950, 600], 0]
    add("fire_nothing_armed", {"calls": [{"fn": "fire_rotation"}], "frames": [frame([])]})
    add("fire_armed", {"calls": [{"fn": "fire_rotation"}], "frames": [frame([])], "init": {"rotation": {"armed": armed, "armed_at": 1000.0 - 5}}})
    add("fire_armed_to_the_second", {"calls": [{"fn": "fire_rotation"}], "frames": [frame([])],
                                     "init": {"rotation": {"armed": armed, "armed_at": 1000.0 - 20}}})
    add("fire_armed_too_old", {"calls": [{"fn": "fire_rotation"}], "frames": [frame([])],
                               "init": {"rotation": {"armed": armed, "armed_at": 1000.0 - 20.5}}})
    rounds = []
    for n in range(7):
        rounds += [{"fn": "do_map", "img": 0, "advance": 0.7}, {"fn": "fire_rotation", "advance": 0.4}]
    add("fast_rounds", {"calls": rounds, "frames": [frame([])], "seed": 90})
    add("fast_rounds_slow_looks", {"calls": rounds[:6], "frames": [frame([])], "seed": 91, "ssd_seconds": 0.9, "shot_seconds": 1.1})
    add("fast_rounds_then_a_pokemon", {"calls": [{"fn": "do_map", "img": 0}, {"fn": "fire_rotation", "advance": 0.4},
                                                 {"fn": "do_map", "img": 1, "advance": 0.4}],
                                       "frames": [frame([]), frame([pokemon(500, 1100)]), frame([pokemon(500, 1100)])], "seed": 92})
    add("fast_rounds_then_a_stop", {"calls": [{"fn": "do_map", "img": 0}, {"fn": "fire_rotation", "advance": 0.4},
                                              {"fn": "do_map", "img": 1, "advance": 0.4}],
                                    "frames": [frame([]), frame([stop(900, 900)]), frame([])], "seed": 93})
    add("fast_rounds_then_nothing_wanted", {"calls": [{"fn": "do_map", "img": 0}, {"fn": "fire_rotation", "advance": 0.4},
                                                      {"fn": "do_map", "img": 1, "advance": 0.4}],
                                            "frames": [frame([]), frame([pokemon(500, 1100)])], "seed": 94, "wanted": {"catch": False}})
    add("fast_rounds_the_round_ends", {"calls": [{"fn": "do_map", "img": 0}, {"fn": "fire_rotation", "advance": 0.4},
                                                 {"fn": "do_map", "img": 0, "advance": 0.4}],
                                       "frames": [frame([])], "seed": 95,
                                       "init": {"rotation": {"steps": 3, "turned": 4000.0, "goal": 4100.0, "dir": -1,
                                                             "armed": armed, "armed_at": 1000.0}}})

    # --- do_map: the rest of what a step looks at
    add("map_gifts_hourly", {"calls": [{"fn": "do_map", "img": 0}, {"fn": "do_map", "img": 0, "advance": 3601.0}], "frames": [frame([])],
                             "init": {"gift_timer": {"last": 1000.0 - 10}}, "wanted": {"gifts_open": True}, "seed": 40})
    add("map_gifts_waiting", {"calls": [{"fn": "do_map", "img": 0}], "frames": [frame([])],
                              "init": {"gift_timer": {"last": 1000.0 - 10}}, "wanted": {"gifts_open": True}, "seed": 41})
    add("map_gifts_hourly_late", {"calls": [{"fn": "do_map", "img": 0}], "frames": [frame([])],
                                  "init": {"gift_timer": {"last": 1000.0 - 3601}}, "wanted": {"gifts_open": True}, "seed": 42})
    add("map_gifts_hourly_to_the_second", {"calls": [{"fn": "do_map", "img": 0}], "frames": [frame([])],
                                           "init": {"gift_timer": {"last": 1000.0 - 3600}}, "wanted": {"gifts_open": True}, "seed": 43})
    add("map_gifts_hourly_send_only", {"calls": [{"fn": "do_map", "img": 0}], "frames": [frame([])],
                                       "init": {"gift_timer": {"last": 1000.0 - 3601}}, "wanted": {"gifts_send": True}, "seed": 44})
    add("map_gifts_hourly_off", {"calls": [{"fn": "do_map", "img": 0}], "frames": [frame([])],
                                 "init": {"gift_timer": {"last": 1000.0 - 3601}}, "seed": 45})
    add("map_gifts_daily", {"calls": [{"fn": "do_map", "img": 0}, {"fn": "do_map", "img": 0, "advance": 7200.0}], "frames": [frame([])],
                            "wanted": {"gifts_open": True, "daily_cycle": True}, "seed": 46})
    add("map_gifts_daily_send_only", {"calls": [{"fn": "do_map", "img": 0}], "frames": [frame([])],
                                      "wanted": {"gifts_send": True, "daily_cycle": True}, "seed": 47})
    add("map_gifts_daily_off", {"calls": [{"fn": "do_map", "img": 0}], "frames": [frame([])], "wanted": {"daily_cycle": True}, "seed": 48})
    one("map_storage_full", "do_map", [frame([], GOLD_BUTTON)], seed=47)
    one("map_storage_full_menu", "do_map", [frame([], GOLD_BUTTON)], wanted={"close_when_full": True}, seed=48)
    one("map_storage_full_daily", "do_map", [frame([], GOLD_BUTTON)], wanted={"daily_cycle": True}, seed=49)
    one("map_storage_full_menu_soon", "do_map", [frame([], GOLD_BUTTON)], wanted={"daily_cycle": True},
        init={"menu_check": {"last": 1000.0 - 100}}, seed=50)
    one("map_storage_full_menu_late", "do_map", [frame([], GOLD_BUTTON)], wanted={"daily_cycle": True},
        init={"menu_check": {"last": 1000.0 - 601}}, seed=51)
    one("map_storage_full_spin_only", "do_map", [frame([pokemon(500, 1100), stop(900, 900)], GOLD_BUTTON)], wanted={"spin_only_when_full": True},
        init={"storage_state": {"full": True}}, seed=52)
    one("map_storage_room_again", "do_map", [frame([], MAP_PIC)], init={"storage_state": {"full": True}}, seed=53)
    one("map_storage_room_again_spin_only", "do_map", [frame([], MAP_PIC)], wanted={"spin_only_when_full": True},
        init={"storage_state": {"full": True}}, seed=54)
    one("map_storage_full_again_nothing_new", "do_map", [frame([], GOLD_BUTTON)], init={"storage_state": {"full": True}}, seed=55)
    one("map_full_in_a_daily_run_spins", "do_map", [frame([pokemon(500, 1100), stop(900, 900)], GOLD_BUTTON)], wanted={"daily_cycle": True},
        init={"storage_state": {"full": True}, "menu_check": {"last": 1000.0 - 100}}, seed=56)
    one("map_full_in_a_daily_run_nothing_to_spin", "do_map", [frame([pokemon(500, 1100)], GOLD_BUTTON)], wanted={"daily_cycle": True},
        init={"storage_state": {"full": True}, "menu_check": {"last": 1000.0 - 100}}, seed=57)

    # --- do_map: what the last catch left behind
    one("map_catch_timeline", "do_map", [frame([])], init={"enc": {"caught": True, "t_throw": 995.0, "t_result": 998.5, "throws": 2}}, seed=57)
    one("map_catch_timeline_no_result", "do_map", [frame([])], init={"enc": {"caught": True, "t_throw": 995.0, "t_result": 0.0, "throws": 2}}, seed=58)
    one("map_catch_timeline_no_throw", "do_map", [frame([])], init={"enc": {"caught": True, "t_throw": 0.0, "t_result": 998.5, "throws": 2}}, seed=59)
    one("map_fled", "do_map", [frame([])], init={"enc": {"caught": False, "throws": 3, "start": 990.0}, "enc_xy": {"xy": [10, 20]},
                                                 "throw_info": {"hit": True}}, seed=60)
    one("map_no_throw_no_fled", "do_map", [frame([])], init={"enc": {"caught": False, "throws": 0, "start": 990.0}}, seed=61)

    # --- do_map: a fast catch that is checked on the map
    fast = {"xy": [500, 1100], "t": 1000.0 - 5, "t_throw": 1000.0 - 9, "t_back": 1000.0 - 7.5, "looks": 0}
    one("fast_gone", "do_map", [frame([])], init={"fast_pending": fast, "fast_state": {"fails": 1, "off_until": 0.0}}, seed=70)
    one("fast_still_there_first", "do_map", [frame([pokemon(520, 1120)])], init={"fast_pending": fast}, seed=71)
    one("fast_still_there_second", "do_map", [frame([pokemon(520, 1120)])],
        init={"fast_pending": dict(fast, looks=1), "cooldown": [[505, 1105, 1000.0 + 60], [900, 100, 1000.0 + 60]]}, seed=72)
    one("fast_still_there_twice_in_a_row", "do_map", [frame([pokemon(520, 1120)])],
        init={"fast_pending": dict(fast, looks=1), "fast_state": {"fails": 1, "off_until": 0.0}}, seed=73)
    one("fast_too_late", "do_map", [frame([pokemon(520, 1120)])], init={"fast_pending": dict(fast, t=1000.6 - 90.1)}, seed=74)
    one("fast_just_in_time", "do_map", [frame([pokemon(520, 1120)])], init={"fast_pending": dict(fast, t=1000.6 - 89.9)}, seed=75)
    one("fast_far_away", "do_map", [frame([pokemon(520, 1330)])], init={"fast_pending": fast}, seed=76)
    one("fast_far_away_x", "do_map", [frame([pokemon(701, 1100)])], init={"fast_pending": fast}, seed=77)
    one("fast_near_edge", "do_map", [frame([pokemon(699, 1100)])], init={"fast_pending": fast}, seed=78)
    one("fast_weak", "do_map", [frame([pokemon(520, 1120, all=0.29)])], init={"fast_pending": fast}, seed=79)
    one("fast_on_a_stop", "do_map", [frame([pokemon(520, 1120, all=0.8), stop(520, 1120, all=0.8)])], init={"fast_pending": fast}, seed=80)
    one("fast_weak_enough", "do_map", [frame([pokemon(520, 1120, all=0.3)])], init={"fast_pending": fast}, seed=81)

    # --- the same, on the edge: numbers that are exactly on a threshold, and distances of exactly 149, 150 and 151 px
    add("fast_rounds_draws_on_the_edge", {"calls": [{"fn": "do_map", "img": 0}, {"fn": "fire_rotation", "advance": 0.4}, {"fn": "do_map", "img": 0}],
                                          "frames": [frame([])], "seed": 100, "random_script": [0.3, 0.06, 0.06, 0.06]})
    add("slow_rounds_draws_on_the_edge", {"calls": [{"fn": "do_map", "img": 0}] * 2, "frames": [frame([])], "seed": 101,
                                          "settings": {"fast_look": False}, "random_script": [0.3, 0.06]})
    add("fast_rounds_draws_just_over_the_edge", {"calls": [{"fn": "do_map", "img": 0}, {"fn": "fire_rotation", "advance": 0.4}, {"fn": "do_map", "img": 0}],
                                                 "frames": [frame([])], "seed": 102, "random_script": [0.3000001, 0.0600001, 0.0600001, 0.0600001]})
    edge = dict(shot_seconds=0.5, ssd_seconds=0.25)       # times that a float holds exactly: 1000 + 2 looks = 1000.5
    for name, other in (("x149", [649, 1100]), ("x150", [650, 1100]), ("x151", [651, 1100]), ("y149", [500, 1249]), ("y150", [500, 1250]),
                        ("y151", [500, 1251]), ("x_in_y_out", [649, 1400]), ("y_in_x_out", [800, 1249]), ("x_neg149", [351, 1100]),
                        ("x_neg150", [350, 1100])):
        one("cooldown_edge_" + name, "do_map", [frame([pokemon(500, 1100)])], init={"cooldown": [other + [1000.0 + 60]]}, seed=110, **edge)
    for name, other in (("x149", [1049, 900]), ("x150", [1050, 900]), ("y149", [900, 1049]), ("y150", [900, 1050]), ("x_in_y_out", [1049, 1300])):
        one("cooldown_edge_stop_" + name, "do_map", [frame([stop(900, 900)])], init={"cooldown": [other + [1000.0 + 60]]}, seed=111, **edge)
    one("cooldown_ends_just_now", "do_map", [frame([pokemon(500, 1100)])], init={"cooldown": [[500, 1100, 1000.5]]}, seed=112, **edge)
    one("cooldown_ends_a_moment_later", "do_map", [frame([pokemon(500, 1100)])], init={"cooldown": [[500, 1100, 1000.75]]}, seed=113, **edge)
    one("cooldown_ended_a_moment_ago", "do_map", [frame([pokemon(500, 1100)])], init={"cooldown": [[500, 1100, 1000.25]]}, seed=114, **edge)
    one("cooldown_ends_just_now_stop", "do_map", [frame([stop(900, 900)])], init={"cooldown": [[900, 900, 1000.5]]}, seed=115, **edge)
    fast_edge = {"xy": [500, 1100], "t": 1000.5 - 90, "t_throw": 1000.0 - 9, "t_back": 1000.0 - 7.5, "looks": 0}
    one("fast_pending_exactly_in_time", "do_map", [frame([pokemon(520, 1120)])], init={"fast_pending": fast_edge}, seed=116, **edge)
    one("fast_pending_a_moment_late", "do_map", [frame([pokemon(520, 1120)])], init={"fast_pending": dict(fast_edge, t=1000.5 - 90.25)}, seed=117, **edge)
    one("fast_pending_a_moment_early", "do_map", [frame([pokemon(520, 1120)])], init={"fast_pending": dict(fast_edge, t=1000.5 - 89.75)}, seed=118, **edge)
    one("fast_radius_x_edge", "do_map", [frame([pokemon(700, 1100)])], init={"fast_pending": fast}, seed=119)
    one("fast_radius_y_edge", "do_map", [frame([pokemon(500, 1300)])], init={"fast_pending": fast}, seed=120)
    one("fast_radius_x_inside_y_outside", "do_map", [frame([pokemon(690, 1400)])], init={"fast_pending": fast}, seed=121)
    one("fast_radius_y_inside_x_outside", "do_map", [frame([pokemon(800, 1290)])], init={"fast_pending": fast}, seed=122)
    for label in ("gym", "unable_pokestop", "rocket_pokestop", "pokestop"):
        one("fast_on_a_" + label, "do_map", [frame([pokemon(520, 1120, all=0.8), obj(label, 520, 1120, 120, 140, all=0.8)])],
            init={"fast_pending": fast}, seed=123)
    one("fast_next_to_a_stop_edge_x", "do_map", [frame([pokemon(520, 1120, all=0.8), obj("pokestop", 570, 1120, 100, 100, all=0.8)])],
        init={"fast_pending": fast}, seed=124)
    one("fast_next_to_a_stop_edge_y", "do_map", [frame([pokemon(520, 1120, all=0.8), obj("pokestop", 520, 1170, 100, 100, all=0.8)])],
        init={"fast_pending": fast}, seed=125)
    one("fast_on_a_stop_odd_width", "do_map", [frame([pokemon(520, 1120, all=0.8), obj("pokestop", 570, 1120, 101, 100, all=0.8)])],
        init={"fast_pending": fast}, seed=126)
    one("fast_on_a_stop_odd_height", "do_map", [frame([pokemon(520, 1120, all=0.8), obj("pokestop", 520, 1170, 100, 101, all=0.8)])],
        init={"fast_pending": fast}, seed=127)
    one("fast_something_else_there", "do_map", [frame([obj("background", 520, 1120, all=0.8)])], init={"fast_pending": fast}, seed=128)
    for name, other in (("x149", [649, 1100]), ("x150", [650, 1100]), ("x151", [651, 1100]), ("y149", [500, 1249]), ("y150", [500, 1250]),
                        ("y151", [500, 1251]), ("x_in_y_out", [649, 1400]), ("x_out_y_in", [800, 1249])):
        one("fast_still_there_cooldown_edge_" + name, "do_map", [frame([pokemon(520, 1120)])],
            init={"fast_pending": dict(fast, looks=1), "cooldown": [other + [1000.0 + 60]]}, seed=129)

    # --- do_map: what is looked at and what is not, with objects on the edge of every distance
    def two(x, y, **kw):                                                       # the first look and the second look of a Pokémon
        return [frame([pokemon(x, y, all=0.6)]), frame([pokemon(x, y, w=170, h=150, all=0.7)])]

    seed = 140
    for name, x, y in (("x109", 884 + 109, 1400), ("x110", 884 + 110, 1400), ("x_109", 884 - 109, 1400), ("x_110", 884 - 110, 1400),
                       ("y_299", 884, 1480 - 299), ("y_300", 884, 1480 - 300), ("y39", 884, 1480 + 39), ("y40", 884, 1480 + 40)):
        seed += 1
        one("trainer_edge_" + name, "do_map", two(x, y), seed=seed)
    for name, x, y in (("x199", 884 + 199, 1400), ("x200", 884 + 200, 1400), ("x_199", 884 - 199, 1400), ("x_200", 884 - 200, 1400),
                       ("y_299", 884 + 150, 1480 - 299), ("y_300", 884 + 150, 1480 - 300), ("y259", 884 + 150, 1480 + 259),
                       ("y260", 884 + 150, 1480 + 260)):
        seed += 1
        one("beside_edge_" + name, "do_map", two(x, y), settings={"buddy": True}, init={"near_state": {"until": 1000.0 + 600}}, seed=seed)
    one("beside_but_no_buddy", "do_map", two(884 + 150, 1560), init={"near_state": {"until": 1000.0 + 600}}, seed=170)
    one("buddy_but_not_beside", "do_map", two(300, 1100), settings={"buddy": True}, init={"near_state": {"until": 1000.0 + 600}}, seed=171)
    one("buddy_beside_but_time_up", "do_map", two(884 + 150, 1560), settings={"buddy": True}, init={"near_state": {"until": 1000.0}}, seed=172)
    for name, x, y in (("x129", 884 + 129, 1400), ("x130", 884 + 130, 1400), ("x_129", 884 - 129, 1400), ("x_130", 884 - 130, 1400),
                       ("y_279", 884, 1480 - 279), ("y_280", 884, 1480 - 280), ("y159", 884, 1480 + 159), ("y160", 884, 1480 + 160)):
        seed += 1
        one("stop_drop_edge_" + name, "do_map", [frame([stop(x, y)])], seed=seed)
    one("stop_at_the_feet", "do_map", [frame([stop(884, 1580)])], seed=180)
    for name, x, y in (("y1819", 700, 1819), ("y1820", 700, 1820), ("x1399", 1399, 1300), ("x1400", 1400, 1300)):
        one("pokemon_edge_" + name, "do_map", two(x, y), seed=181)
    one("pokemon_score_on_the_edge", "do_map", [frame([pokemon(500, 1100, all=0.4)]), frame([pokemon(500, 1100, all=0.7)])], seed=182)
    one("pokemon_score_just_under_the_edge", "do_map", [frame([pokemon(500, 1100, all=0.3999)]), frame([pokemon(500, 1100, all=0.7)])], seed=183)
    one("stop_score_on_the_edge", "do_map", [frame([stop(900, 900, all=0.3)])], seed=184)
    one("stop_score_just_under_the_edge", "do_map", [frame([stop(900, 900, all=0.2999)])], seed=185)
    for name, x, y, score in (("score_04", 900, 900, 0.4), ("score_0399", 900, 900, 0.3999), ("x249", 900 + 249, 900, 0.6), ("x250", 900 + 250, 900, 0.6),
                              ("x_249", 900 - 249, 900, 0.6), ("x_250", 900 - 250, 900, 0.6), ("y349", 900, 900 + 349, 0.6),
                              ("y350", 900, 900 + 350, 0.6), ("y_349", 900, 900 - 349, 0.6), ("y_350", 900, 900 - 350, 0.6)):
        one("rocket_edge_" + name, "do_map", [frame([stop(900, 900), obj("rocket_pokestop", x, y, 120, 140, all=score)])], seed=186)
    one("not_looking_for_a_pokemon", "do_map", [frame([])], init={"catch": False}, seed=187)
    one("not_looking_when_full_in_a_daily_run", "do_map", [frame([], GOLD_BUTTON)], wanted={"daily_cycle": True},
        init={"storage_state": {"full": True}, "menu_check": {"last": 1000.0 - 100}}, seed=188)
    one("not_looking_when_full_spin_only", "do_map", [frame([], GOLD_BUTTON)], wanted={"spin_only_when_full": True},
        init={"storage_state": {"full": True}}, seed=189)
    one("looking_when_full_but_not_asked_to_stop", "do_map", [frame([], GOLD_BUTTON)], init={"storage_state": {"full": True}}, seed=190)
    one("menu_check_just_not_yet", "do_map", [frame([], GOLD_BUTTON)], wanted={"daily_cycle": True}, init={"menu_check": {"last": 1003.5 - 600}},
        seed=191, **edge)
    one("menu_check_a_moment_late", "do_map", [frame([], GOLD_BUTTON)], wanted={"daily_cycle": True},
        init={"menu_check": {"last": 1003.5 - 600.25}}, seed=192, **edge)
    one("catch_timeline_not_caught", "do_map", [frame([])], init={"enc": {"caught": False, "t_throw": 995.0, "t_result": 998.5, "throws": 0}}, seed=193)

    # --- do_map: the first look and the second look that do not agree, the best of several, a round that is left over
    one("map_second_look_moves_next_to_the_trainer", "do_map", [frame([pokemon(1100, 1400, all=0.6)]), frame([pokemon(1050, 1400, w=170, h=150, all=0.7)])],
        seed=200)
    for width in (165, 175, 180):
        one("map_tap_beside_the_trainer_w%d" % width, "do_map", [frame([pokemon(950, 1560, all=0.6)]), frame([pokemon(950, 1560, w=width, h=150, all=0.7)])],
            seed=201)
    one("map_two_pokemon_the_surest_first", "do_map", [frame([pokemon(500, 1100, all=0.8), pokemon(900, 1000, all=0.5)]),
                                                      frame([pokemon(500, 1100, all=0.8), pokemon(900, 1000, all=0.5)])], seed=202)
    one("map_two_pokemon_the_surest_last_in_the_picture", "do_map", [frame([pokemon(900, 1000, all=0.5), pokemon(500, 1100, all=0.8)]),
                                                                    frame([pokemon(900, 1000, all=0.5), pokemon(500, 1100, all=0.8)])], seed=203)
    one("map_two_stops_the_surest_first", "do_map", [frame([stop(900, 900, all=0.8), stop(500, 800, all=0.5)])], seed=204)
    one("map_two_stops_the_surest_last_in_the_picture", "do_map", [frame([stop(500, 800, all=0.5), stop(900, 900, all=0.8)])], seed=205)
    one("map_a_stop_while_the_camera_is_turning", "do_map", [frame([stop(900, 900)])], seed=206,
        init={"rotation": {"steps": 3, "turned": 500.0, "goal": 4000.0, "dir": 1}})
    one("map_a_pokemon_while_the_camera_is_turning", "do_map", two(500, 1100), seed=207,
        init={"rotation": {"steps": 3, "turned": 500.0, "goal": 4000.0, "dir": 1}})
    one("map_gone_twice_the_best_is_forgotten", "do_map", [frame([pokemon(500, 1100, whole=0.6, second=0.2)]), frame([pokemon(500, 1100, whole=0.6, second=0.2)])],
        seed=208)
    add("map_gone_twice_nothing_left_the_second_time", {"calls": [{"fn": "do_map", "img": 0}, {"fn": "do_map", "img": 2}], "seed": 209,
                                                        "frames": [frame([pokemon(500, 1100, whole=0.6, second=0.2)]), frame([pokemon(500, 1100, whole=0.6, second=0.2)]),
                                                                   frame([pokemon(900, 1000, whole=0.6)]), frame([])]})
    add("map_a_new_round_with_a_swipe_left_over", {"calls": [{"fn": "do_map", "img": 0}] * 2, "frames": [frame([])], "seed": 210,
                                                   "init": {"rotation": {"steps": 0, "turned": 0.0, "goal": 0.0, "dir": 1,
                                                                         "armed": [[350, 900, 1000, 950, 600], 0], "armed_at": 1000.0,
                                                                         "fired": {"t": 1000.0, "swipe": [350, 900, 1000, 950, 600]}}}})
    one("map_not_looking_with_a_round_going", "do_map", [frame([])], seed=211, init={"catch": False,
                                                                                         "rotation": {"steps": 2, "turned": 100.0, "goal": 4000.0, "dir": 1}})
    for looks in (1, 2, 3, 4):
        one("map_round_starts_after_%d_looks" % looks, "do_map", [frame([])], seed=212,
            init={"perf": {"looks": looks, "shot": 1.0, "detect": 0.6, "wait": 2.0, "total": 5.0, "t_step": 990.0}})
    one("map_round_starts_without_a_step_time", "do_map", [frame([])], seed=213,
        init={"perf": {"looks": 3, "shot": 1.0, "detect": 0.6, "wait": 2.0, "total": 5.0}})
    one("map_turned_exactly_the_goal", "do_map", [frame([])], seed=214,
        init={"rotation": {"steps": 2, "turned": 100.0, "goal": 750.0, "dir": 1, "fired": {"t": 1000.0, "swipe": [350, 900, 1000, 950, 600]}}})
    one("map_turned_a_little_less_than_the_goal", "do_map", [frame([])], seed=215,
        init={"rotation": {"steps": 2, "turned": 100.0, "goal": 750.5, "dir": 1, "fired": {"t": 1000.0, "swipe": [350, 900, 1000, 950, 600]}}})
    one("map_turned_a_little_more_than_the_goal", "do_map", [frame([])], seed=216,
        init={"rotation": {"steps": 2, "turned": 100.0, "goal": 749.5, "dir": 1, "fired": {"t": 1000.0, "swipe": [350, 900, 1000, 950, 600]}}})

    # --- the looks at the map: boxes that are as far from each other as the code can tell, scores on the edge, what is remembered
    for name, dx, dy in (("x99", 99, 0), ("x100", 100, 0), ("x101", 101, 0), ("y99", 0, 99), ("y100", 0, 100), ("y101", 0, 101),
                         ("x_99", -99, 0), ("x_100", -100, 0), ("diag99_150", 99, 150), ("diag150_99", 150, 99), ("diag99_99", 99, 99),
                         ("diag100_100", 100, 100)):
        add("look_near_edge_" + name, {"calls": [{"fn": "map_objects", "img": 0}],
                                       "frames": [frame([pokemon(500, 1100, whole=0.6, zoom=0.0), pokemon(500 + dx, 1100 + dy, whole=0.0, zoom=0.6)])]})
    add("look_zoom_next_to_a_stop", {"calls": [{"fn": "map_objects", "img": 0}],
                                     "frames": [frame([stop(500, 1100, whole=0.8, zoom=0.0), pokemon(500, 1100, whole=0.0, zoom=0.6)])]})
    for score in (0.4, 0.3999, 0.35, 0.3499, 0.2, 0.1999):
        add("look_zoom_score_%s" % score, {"calls": [{"fn": "map_objects", "img": 0}], "frames": [frame([pokemon(500, 1100, whole=0.0, zoom=score)])]})
    add("look_zoom_only_asked_twice", {"calls": [{"fn": "map_objects", "img": 0}, {"fn": "map_objects", "img": 0, "same": True}],
                                       "frames": [frame([pokemon(500, 1100, whole=0.0, zoom=0.6)])]})
    add("look_where_it_was_seen_is_forgotten", {"calls": [{"fn": "map_objects", "img": 0}, {"fn": "map_objects", "img": 1},
                                                          {"fn": "second_look", "img": 2, "x": 500, "y": 1100}],
                                                "frames": [frame([pokemon(500, 1100, whole=0.0, zoom=0.6)]), frame([pokemon(500, 1100, whole=0.6, zoom=0.0)]),
                                                           frame([pokemon(500, 1100, second=0.6)])]})
    add("look_zoom_better_than_the_whole_screen", {"calls": [{"fn": "map_objects", "img": 0}],
                                                   "frames": [frame([pokemon(500, 1100, whole=0.45, zoom=0.0), pokemon(900, 1000, whole=0.0, zoom=0.9)])]})
    add("look_zoom_as_sure_as_the_whole_screen", {"calls": [{"fn": "map_objects", "img": 0}],
                                                  "frames": [frame([pokemon(500, 1100, whole=0.6, zoom=0.0), pokemon(900, 1000, whole=0.0, zoom=0.6)])]})
    add("look_tiles_the_zoom_and_one_tile", {"calls": [{"fn": "map_objects", "img": 0, "tiles": True}],
                                             "frames": [frame([pokemon(300, 710, whole=0.0, zoom=0.38, tile=0.6)])]})
    add("look_tiles_the_zoom_and_a_weak_tile", {"calls": [{"fn": "map_objects", "img": 0, "tiles": True}],
                                                "frames": [frame([pokemon(300, 710, whole=0.0, zoom=0.38, tile=0.45)])]})
    for score in (0.5, 0.4999):
        add("look_tiles_score_%s" % score, {"calls": [{"fn": "map_objects", "img": 0, "tiles": True}], "frames": [frame([pokemon(500, 1100, whole=0.0, zoom=0.0, tile=score)])]})
    add("look_tiles_a_stop_between", {"calls": [{"fn": "map_objects", "img": 0, "tiles": True}],
                                      "frames": [frame([pokemon(500, 1100, whole=0.0, zoom=0.0, tile=0.6), stop(500, 1100, all=0.8)])]})
    add("look_tiles_the_surest_leads_the_group", {"calls": [{"fn": "map_objects", "img": 0, "tiles": True}],
                                                  "frames": [frame([pokemon(500, 1100, whole=0.0, zoom=0.36, tile=0.55), pokemon(560, 1130, whole=0.0, zoom=0.0, tile=0.7)])]})
    for name, others in (("x", [pokemon(520, 1100, second=0.5), pokemon(480, 1100, second=0.5)]),
                         ("y", [pokemon(500, 1120, second=0.5), pokemon(500, 1080, second=0.5)]),
                         ("w", [pokemon(500, 1100, w=150, second=0.5), pokemon(500, 1100, w=170, second=0.5)]),
                         ("h", [pokemon(500, 1100, h=150, second=0.5), pokemon(500, 1100, h=170, second=0.5)]),
                         ("score", [pokemon(520, 1100, second=0.5), pokemon(480, 1100, second=0.6)])):
        for order, items in (("", others), ("_reversed", others[::-1])):          # (the first of equals stays when nothing is better)
            add("second_look_tie_%s%s" % (name, order), {"calls": [{"fn": "map_objects", "img": 0}, {"fn": "second_look", "img": 1, "x": 500, "y": 1100}],
                                                         "frames": [frame([pokemon(500, 1100, whole=0.6)]), frame(items)]})
    for name, x, y in (("x149", 649, 1100), ("x150", 650, 1100), ("x_149", 351, 1100), ("x_150", 350, 1100), ("y149", 500, 1249), ("y150", 500, 1250),
                       ("y_149", 500, 951), ("y_150", 500, 950), ("x149_y150", 649, 1250)):
        add("second_look_near_%s" % name, {"calls": [{"fn": "map_objects", "img": 0}, {"fn": "second_look", "img": 1, "x": 500, "y": 1100}],
                                           "frames": [frame([pokemon(500, 1100, whole=0.6)]), frame([pokemon(x, y, second=0.6)])]})
    add("second_look_not_a_pokemon", {"calls": [{"fn": "map_objects", "img": 0}, {"fn": "second_look", "img": 1, "x": 500, "y": 1100}],
                                      "frames": [frame([pokemon(500, 1100, whole=0.6)]), frame([stop(500, 1100, second=0.8)])]})
    for score in (0.35, 0.3499, 0.3, 0.2999, 0.34, 0.31):
        add("second_look_whole_score_%s" % score, {"calls": [{"fn": "map_objects", "img": 0}, {"fn": "second_look", "img": 1, "x": 500, "y": 1100}],
                                                   "frames": [frame([pokemon(500, 1100, whole=0.6)]), frame([pokemon(500, 1100, second=score)])]})
        add("second_look_zoom_score_%s" % score, {"calls": [{"fn": "map_objects", "img": 0}, {"fn": "second_look", "img": 1, "x": 500, "y": 1100}],
                                                  "frames": [frame([pokemon(500, 1100, whole=0.0, zoom=0.6)]), frame([pokemon(500, 1100, second=score)])]})
    add("second_look_zoom_part_sees_less", {"calls": [{"fn": "map_objects", "img": 0}, {"fn": "second_look", "img": 1, "x": 210, "y": 1100}],
                                            "frames": [frame([pokemon(210, 1100, whole=0.0, zoom=0.6)]), frame([pokemon(210, 1100, second=0.2), pokemon(80, 1100, second=0.3)])]})

    # --- do_map: the first look that is not enough, what is only weakly seen
    for name, scores in (("whole_020", dict(whole=0.2)), ("whole_022", dict(whole=0.22)), ("whole_0199", dict(whole=0.1999)),
                         ("whole_039", dict(whole=0.39)), ("zoom_035", dict(whole=0.0, zoom=0.35)), ("zoom_0349", dict(whole=0.0, zoom=0.3499))):
        one("map_a_weak_look_" + name, "do_map", [frame([pokemon(100, 800, **scores)])], seed=220,
            init={"rotation": {"steps": 1, "turned": 100.0, "goal": 4000.0, "dir": 1}})

    # --- do_pokestop
    one("stop_already_spun", "do_pokestop", [frame([], PURPLE_RING)])
    one("stop_spun_at_once", "do_pokestop", [frame([]), frame([], PURPLE_RING)], seed=1)
    one("stop_spun_late", "do_pokestop", [frame([])] + [frame([])] * 3 + [frame([], PURPLE_RING)], shot_seconds=1.0)
    one("stop_spun_second_try", "do_pokestop", [frame([])] + [frame([])] * 6 + [frame([], PURPLE_RING)], shot_seconds=1.0)
    one("stop_spun_last_try", "do_pokestop", [frame([])] + [frame([])] * 14 + [frame([], PURPLE_RING)], shot_seconds=1.0)
    one("stop_not_spun", "do_pokestop", [frame([])], shot_seconds=1.2)
    one("stop_not_spun_fast_shots", "do_pokestop", [frame([])], shot_seconds=0.9)
    def bag(name, init=None, advance=0.0, **kw):
        add(name, dict(calls=[{"fn": "do_pokestop", "img": 0, "advance": advance}], frames=[frame([]), frame([], PINK_MESSAGE)], init=init or {}, **kw))
    bag("stop_bag_full_too_early")                                    # (the clock starts at 1000: not 1200 s after 0)
    bag("stop_bag_full_clean", advance=500.0, bag_gone=3)
    bag("stop_bag_full_clean_nothing", advance=500.0, bag_gone=0)
    bag("stop_bag_full_clean_fails", advance=500.0, bag_error="the bag did not open")
    bag("stop_bag_full_clean_off", advance=500.0, settings={"bag_clean": False}, bag_gone=3)
    bag("stop_bag_full_cleaned_lately", init={"bag_state": {"cleaned": 1000.0 - 600}}, bag_gone=3)
    bag("stop_bag_full_cleaned_long_ago", init={"bag_state": {"cleaned": 1000.0 - 1300}}, bag_gone=2)
    bag("stop_bag_full_cleaned_almost_due", init={"bag_state": {"cleaned": 1001.7 - 1200 + 0.5}}, bag_gone=2)
    bag("stop_bag_full_cleaned_just_due", init={"bag_state": {"cleaned": 1001.7 - 1200 - 0.5}}, bag_gone=2)
    due = ((1000.0 + 0.5) + 0.8) + 0.4                                 # the clock at the look at the bag (a step of 0.4 s per look)
    cleaned = due - 1200
    for candidate in (cleaned, math.nextafter(cleaned, -math.inf), math.nextafter(cleaned, math.inf)):
        if candidate + 1200 == due:
            cleaned = candidate
            break
    assert cleaned + 1200 == due
    bag("stop_bag_full_cleaned_exactly_in_time", init={"bag_state": {"cleaned": cleaned}}, bag_gone=2)
    bag("stop_bag_full_cleaned_a_moment_late", init={"bag_state": {"cleaned": cleaned - 0.25}}, bag_gone=2)
    bag("stop_bag_full_cleaned_a_moment_early", init={"bag_state": {"cleaned": cleaned + 0.25}}, bag_gone=2)
    one("stop_polls_to_the_second", "do_pokestop", [frame([])], shot_seconds=0.74)       # the 5th look is exactly 4.5 s after the swipe
    one("stop_polls_a_moment_less", "do_pokestop", [frame([])], shot_seconds=0.73)
    one("stop_polls_a_moment_more", "do_pokestop", [frame([])], shot_seconds=0.75)
    one("stop_ring_and_bag", "do_pokestop", [frame([]), frame([], rect(px(0, 0, RING_CX + 150, H, PURPLE), px(580, 1065, 620, 75, PINK)))])
    return out


CONSTANTS_G = ("TH_POKEMON", "TH_STOP", "TH_WEAK", "TH_TILE", "ZOOM_BOX", "TILE", "TILE_X", "TILE_Y", "GONE_COOLDOWN", "TAP_UP",
               "ROTATE", "ROTATE_TURN", "ROTATE_REVERSE", "ROTATE_LEN", "ROTATE_Y", "ROTATE_DRIFT", "ROTATE_SPEED", "ROTATE_PAUSE",
               "ROTATE_LONG_PAUSE", "ROTATE_LAG", "ROTATE_REST", "SHOT_LAG", "ROTATE_JITTER", "IDLE_RANGE", "FAST_PENDING_MAX",
               "FAST_RADIUS", "FAST_SCORE", "FAST_MAX_FAILS", "FAST_REST", "GIFT_INTERVAL", "MENU_CHECK_INTERVAL", "STOP_LOAD",
               "SPIN_FIRST_LOOK", "SPIN_POLL_UNTIL", "STOP_CLOSE_DELAY", "AFTER_STOP_TAP", "BAG_CLEAN_EVERY")
CONSTANTS_S = ("PLAYER", "SPIN_X1", "SPIN_X2", "SPIN_Y", "BAG_FULL_WAIT", "RING_CENTER", "RING_R")


def constants():
    out = {}
    for name in CONSTANTS_G:
        value = getattr(G, name)
        out[name] = [float(x) for x in value] if isinstance(value, (tuple, list)) else [float(value)]
    for name in CONSTANTS_S:
        value = getattr(S, name)
        out["S." + name] = [float(x) for x in value] if isinstance(value, (tuple, list)) else [float(value)]
    return out


def capture():
    return [{"id": item["id"], "spec": item["spec"], "events": record(item["spec"])} for item in stories()]


def text(cases=None, readers=None):
    doc = {"cv2": cv2.__version__, "start": START, "constants": constants(),
           "readers": reader_cases() if readers is None else readers,
           "cases": capture() if cases is None else cases}
    return json.dumps(doc, separators=(",", ":"), sort_keys=True)


def check():
    with open(OUT, "rb") as handle:
        packed = handle.read()
    old = json.loads(zlib.decompress(packed[4:]))
    new_cases = [{"id": c["id"], "spec": c["spec"], "events": record(c["spec"])} for c in old["cases"]]
    readers = []
    for c in old["readers"]:
        img = make_picture(c["pic"])
        readers.append({"id": c["id"], "pic": c["pic"], "ring": bool(S.ring_spun(img)), "bag": bool(S.bag_full(img)), "full": bool(G.box_full_ball(img)),
                        "spun": [{"box": s["box"], "value": bool(G.looks_spun(img, ("pokestop", 0.9) + tuple(s["box"])))} for s in c["spun"]]})
    raw = text(new_cases, readers).encode("utf-8")
    if len(packed) > 4 and struct.unpack(">I", packed[:4])[0] == len(raw) and zlib.decompress(packed[4:]) == raw:
        print("map_golden.json.qz is what the map step does")
        return 0
    new = json.loads(raw)
    if old.get("constants") != new["constants"]:
        print("map_golden.json.qz is NOT what the map step does: the numbers changed")
        return 1
    differ = [a["id"] for a, b in zip(old["cases"], new["cases"]) if json.dumps(a["events"]) != json.dumps(b["events"])]
    differ += [a["id"] for a, b in zip(old["readers"], new["readers"]) if a != b]
    allowed = int(0.05 * (len(old["cases"]) + len(old["readers"])))
    if old["cv2"] == new["cv2"] or len(differ) > allowed:
        print("map_golden.json.qz is NOT what the map step does: " + ", ".join(differ[:8]))
        return 1
    print("map_golden.json.qz was made with OpenCV %s, this is %s: %d of %d cases go another way (allowed: %d)"
          % (old["cv2"], new["cv2"], len(differ), len(old["cases"]) + len(old["readers"]), allowed))
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
    print("wrote %s: %d pictures for the readers, %d stories, %d events, %d bytes of JSON, packed to %d" % (
        OUT, len(doc["readers"]), len(doc["cases"]), sum(len(c["events"]) for c in doc["cases"]), len(raw), os.path.getsize(OUT)))
