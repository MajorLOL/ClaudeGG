#!/usr/bin/env python3
"""Makes tests/fixtures/gifts_golden.json.qz (JSON, packed the way qCompress() of Qt does: the length, then zlib): what gamebot.py does with the GIFTS
of the friends - the friend list that is read (parse_friends() with the grey arrow of a gift that was sent and the pink bow of one that waits), the
readers of the gift screens (is_gift_screen(), find_pill_button(), send_button(), has_sticker_button(), is_friend_list()), the memory of the day
(load_gift_state(), save_gift_state()), a visit to one friend (visit_friend(): open the gift that waits, scroll the profile to SEND GIFT, choose the
first gift, SEND) and the whole round (gifts_round(): the avatar, the FRIENDS tab, the list scrolled to its end) - the file that the C++ port,
SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoGifts.cpp, is tested against.

    python3 tools/make_gifts_golden.py            writes the file
    python3 tools/make_gifts_golden.py --check    says whether the file is what the code does now (the stories stored in it are played again)

The file is a list of stories: a list of calls, each with the EVENTS that it makes, with the time of a fake clock (it starts at 1000.0 and only moves
with the screenshots and the sleeps).  The pictures are drawn on the canvas by the ops of tools/make_throw_golden.py; the readers of pictures (the
check for the map, the pink and grey places, the green pill button) are the real ones.  Some stories are played on a pretend phone ('sim') that has
a map, the profile of the trainer, a friend list that scrolls, the gift of a friend, the profile of a friend that scrolls, the list of gifts to send,
the screen to send one and the messages of a gift that cannot be opened or sent: it changes the screen with every touch, so that what the code
does is what it makes of the screens.  What the code is GIVEN:
    shot          a screenshot (which of the frames of the story)
    ocr           the text reader read the lines (with the places of the words) of a picture
    ocr_text      the text reader read the words of a strip of a picture
    gift_read     what the file of the gift memory held (or that there was none)
  what it DOES (the C++ port has to do the same, in this order):
    tap (a short touch), press (a touch that lasts: with how many ms), back, swipe, sleep, log, save (a picture that is kept), gift_write (what was
    written to the file of the gift memory), then at the end of every call: result (what it returned) or raised, and state (the memory of the day
    that the call was given, as it is afterwards).

What the stories leave out on purpose (the port does something else there, and says so in its own file): a gift memory that is no JSON object, or
holds an object with another set of keys than the five of the code (the Python code stops with a KeyError or an AttributeError: the port starts a
new day), and the keys of the file that the code does not know (the port does not write them back)."""
import argparse
import copy
import io
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
import cv2  # noqa: E402
import numpy as np  # noqa: E402
import gamebot as G  # noqa: E402
import spin_stop as S  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "tests", "fixtures", "gifts_golden.json.qz")
W, H = TG.W, TG.H
PLAIN = CG.PLAIN
jsonable = CG.jsonable

MAGENTA = [255, 0, 255]
GREY = [140, 140, 140]
TODAY = "2026-11-22"                   # what the fake clock says of the day (make_start_golden.Clock.strftime)
PACKAGE = "com.nianticlabs.pokemongo"


def bgr_for(h, s, v):
    """A colour (b, g, r) whose hue, saturation and value are exactly these (OpenCV's: hue 0-179)."""
    hf, sf, vf = h * 2.0, s / 255.0, v / 255.0
    c = vf * sf
    x = c * (1 - abs((hf / 60.0) % 2 - 1))
    m = vf - c
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(hf // 60) % 6]
    base = [round((p + m) * 255) for p in (b, g, r)]
    for reach in (3, 8):
        for db in range(-reach, reach + 1):
            for dg in range(-reach, reach + 1):
                for dr in range(-reach, reach + 1):
                    bgr = [min(255, max(0, base[0] + db)), min(255, max(0, base[1] + dg)), min(255, max(0, base[2] + dr))]
                    px = cv2.cvtColor(np.array([[bgr]], np.uint8), cv2.COLOR_BGR2HSV)[0, 0]
                    if (int(px[0]), int(px[1]), int(px[2])) == (h, s, v):
                        return bgr
    raise ValueError((h, s, v))


GREEN = bgr_for(67, 150, 220)          # a pill button


# ---------------------------------------------------------------------- the pictures and what the readers say of them

SPOTS = [(x, y) for x in (20, 1450) for y in (20, 320, 620, 920, 1220, 1520, 1820)]        # (clear of the places that the readers look at)


def marker(n):
    """A white square at the edge of the picture: it makes two screens that are not the same look different."""
    x, y = SPOTS[n % len(SPOTS)]
    return ["rect", x, y, 60, 60, [255, 255, 255]]


def line(text, x, y):
    """A line of the text reader: (TEXT, x of the first word, y, [(word, x, y)]) - the words are 120 px apart."""
    return [text, x, y, [[w, x + 120 * i, y] for i, w in enumerate(text.split())]]


def frame(ops=None, lines=None, **more):
    f = {"pic": ops if ops is not None else [PLAIN]}
    if lines is not None:
        f["lines"] = lines
    f.update(more)
    return f


class World(CG.World):
    pass


# ---------------------------------------------------------------------- the pretend phone

HEADER = {"0": "SOCIAL FRIENDS PARTY"}             # (what the strip at the top of the friend list reads)


def friend(name, **kw):
    """A friend of the pretend phone.  when: what the list says of the last visit; gift: what the list shows of a gift that waits (text: 'sent you a
    Gift!', icon: only the pink bow, none); pending: whether one really waits (the tap opens the gift screen); arrow: the grey arrow (a gift of you is
    on its way); open: what the OPEN button does (ok, limit, maximum, bagfull, stuck, stuck_limit); open_pill: whether the gift screen shows a green
    OPEN button; profile: what the profile shows (sendable: the pink icon above the label SEND GIFT, grey: a grey icon, remove: REMOVE FRIEND is near the
    icon, trade: the label TRADE, sent: the label says that a gift was sent, none: no label); button_y: where the label is when the profile is not
    scrolled; scroll0: how far the profile is scrolled when it opens; after_icon: what the icon does (which: the list of gifts, failed: a message);
    fail: that message (nogift, dont, other); spot: which of the three places chooses a gift (None: none of them); send: what SEND does (ok, stuck);
    sticker: whether the screen to send one shows ADD STICKER (else a green pill button; none: neither); icon_px: how many pixels of the icon are
    coloured (None: all of a big square); icon_color: the colour of the icon (None: pink); icon_extra: single pixels of the icon colour, as [dx, dy] from
    the place the bot taps on the icon (336, label - 140); remove_dy: how far below the icon the words REMOVE FRIEND are."""
    f = {"name": name, "when": "TODAY", "gift": None, "pending": None, "arrow": False, "open": "ok", "open_pill": True, "profile": "sendable",
         "button_y": 1500, "scroll0": 0, "after_icon": "which", "fail": "nogift", "spot": 0, "send": "ok", "sticker": "yes", "was_sent": False,
         "icon_px": None, "icon_color": None, "icon_extra": [], "remove_dy": 100}
    f.update(kw)
    if f["pending"] is None:
        f["pending"] = f["gift"] is not None
    return f


class Sim:
    """A phone with Pokémon GO: the map, the profile of the trainer, the friend list, the gift of a friend, the profile of a friend, the list of gifts
    to send, the screen to send one.  A touch changes the screen the way the game does; what is on it is told as pictures (frames that are made
    when they are first seen) and the lines and strips the text reader would read."""

    def __init__(self, spec, world):
        self.p = spec["sim"]
        self.world = world
        self.friends = [friend(**f) for f in self.p["friends"]]
        self.screen = self.p.get("start", "map")
        self.scroll = 0
        self.cur = 0
        self.prof_scroll = 0
        self.result_taps = 0
        self.looks = 0
        self.keys = {}

    # ---- the friend list
    def row_y(self, i):
        return 600 + 400 * i - self.scroll

    def max_scroll(self):
        return max(0, 600 + 400 * len(self.friends) - 1700)

    def frame(self):
        self.looks += 1
        if self.screen == "friends" and self.looks - 1 == self.p.get("popup_at", -1):
            self.screen = "popup"
        s, f = self.screen, (self.friends[self.cur] if self.friends else None)
        if s == "friends":
            key = ("friends", self.scroll, tuple((x["name"], x["when"], x["gift"], x["arrow"]) for x in self.friends))
        elif s == "profile":
            key = ("profile", self.cur, self.prof_scroll, f["profile"], f["was_sent"], f["button_y"], f["icon_px"], str(f["icon_color"]), str(f["icon_extra"]), f["remove_dy"])
        elif s == "gift_open":
            key = ("gift_open", f["open_pill"])
        elif s in ("gift_result", "gift_stuck_limit"):
            key = (s, f["open"])
        elif s == "send_screen":
            key = ("send_screen", f["sticker"])
        elif s == "send_failed":
            key = ("send_failed", f["fail"])
        else:
            key = (s,)
        if key not in self.keys:
            self.keys[key] = len(self.world.frames)
            self.world.frames.append(self.build(key, len(self.keys)))
        return self.keys[key]

    def build(self, key, n):
        s = key[0]
        f = self.friends[self.cur] if self.friends else None
        if s == "map":
            return frame(CG.map_screen()["pic"] + [marker(n)], lines=[])
        if s == "me":
            return frame([PLAIN, marker(n)], lines=[line("TRAINER LEVEL 40", 884, 500)], texts={"0": "TRAINER PROFILE"})
        if s == "popup":
            return frame([PLAIN, marker(n)], lines=[line("NEWS", 884, 900)], texts={})
        if s == "friends":
            ops, lines = [PLAIN, marker(n)], []
            for i, x in enumerate(self.friends):
                y = self.row_y(i)
                if not 300 <= y <= 2150:
                    continue
                lines.append(line(x["name"] + " " + x["when"], 520, y))
                if x["gift"] == "text":
                    lines.append(line("SENT YOU A GIFT!", 520, y + 80))
                if x["gift"] == "icon":
                    ops.append(["rect", 500, y + 150, 300, 200, MAGENTA])
                if x["arrow"]:
                    ops.append(["rect", 330, y + 100, 80, 90, GREY])
            return frame(ops, lines=lines, texts=dict(HEADER))
        if s == "gift_open":
            ops = [PLAIN, ["rect", 500, 300, 600, 300, MAGENTA], marker(n)] + ([["rect", 500, 1700, 800, 200, GREEN]] if key[1] else [])
            return frame(ops, lines=[], texts={})
        if s == "gift_stuck_limit":
            return frame([PLAIN, ["rect", 500, 300, 600, 300, MAGENTA], marker(n)], lines=[line("DAILY LIMIT", 884, 700)], texts={})
        if s == "gift_result":
            text = {"ok": "YOU RECEIVED 3 POTIONS", "limit": "DAILY GIFT LIMIT REACHED", "maximum": "MAXIMUM GIFTS OPENED", "bagfull": "YOUR BAG IS FULL"}[key[1]]
            return frame([PLAIN, marker(n)], lines=[line(text, 300, 700)], texts={})
        if s == "profile":
            by = f["button_y"] - self.prof_scroll
            ops, lines = [PLAIN, marker(n)], [line(f["name"], 884, 300 - self.prof_scroll)]
            if f["was_sent"] or f["profile"] == "sent":
                lines.append(line("GIFT SENT", 336, by))
            elif f["profile"] == "trade":
                lines.append(line("TRADE", 336, by))
            elif f["profile"] != "none":
                lines.append(line("SEND GIFT", 336, by))
            if f["profile"] in ("sendable", "grey", "remove", "trade") and not f["was_sent"]:
                colour = GREY if f["profile"] == "grey" else (f["icon_color"] or MAGENTA)
                if f["icon_px"] is None:
                    ops.append(["rect", 336 - 130, by - 140 - 110, 260, 220, colour])
                else:
                    full, rest = divmod(f["icon_px"], 100)
                    if full:
                        ops.append(["rect", 336 - 130, by - 140 - 110, 100, full, colour])
                    if rest:
                        ops.append(["rect", 336 - 130, by - 140 - 110 + full, rest, 1, colour])
                for dx, dy in f["icon_extra"]:
                    ops.append(["rect", 336 + dx, by - 140 + dy, 1, 1, colour])
            if f["profile"] == "remove":
                lines.append(line("REMOVE FRIEND", 884, by - 140 + f["remove_dy"]))
            return frame(ops, lines=lines, texts={})
        if s == "which_gift":
            return frame([PLAIN, marker(n)], lines=[line("WHICH GIFT DO YOU WANT TO SEND?", 884, 300)], texts={})
        if s == "send_screen":
            ops = [PLAIN, marker(n)]
            if key[1] == "pill":
                ops.append(["rect", 484, 1700, 800, 200, GREEN])
            return frame(ops, lines=[], texts={"1480": "ADD STICKER"} if key[1] == "yes" else {})
        if s == "sent":
            return frame([PLAIN, marker(n)], lines=[line("GIFT SENT", 884, 900)], texts={})
        if s == "send_failed":
            text = {"nogift": "YOU HAVE NO GIFTS TO SEND", "dont": "YOU DON'T HAVE ANY GIFTS LEFT", "other": "SOMETHING WENT WRONG"}[key[1]]
            return frame([PLAIN, marker(n)], lines=[line(text, 300, 900)], texts={})
        raise KeyError(key)

    # ---- what a touch does
    def tap(self, x, y):
        s, p = self.screen, self.p
        f = self.friends[self.cur] if self.friends else None

        def near(px, py, rx=100, ry=100):
            return abs(x - px) < rx and abs(y - py) < ry
        if s == "map":
            if near(*G.AVATAR):
                self.screen = "me"
        elif s == "me":
            if near(*G.FRIENDS_TAB, rx=200, ry=80) and not p.get("tab_dead"):
                self.screen = "friends"
        elif s == "friends":
            for i, row in enumerate(self.friends):
                if near(520, self.row_y(i), 250, 100):
                    self.cur, self.result_taps = i, 0
                    self.prof_scroll = row["scroll0"]
                    self.screen = "gift_open" if row["pending"] else "profile"
                    break
        elif s == "gift_open":
            if abs(x - 884) < 450 and 1600 < y < 1950:
                if f["open"] in ("ok", "limit", "maximum", "bagfull"):
                    self.screen = "gift_result"
                    if f["open"] == "ok":
                        f["gift"], f["pending"] = None, False
                elif f["open"] == "stuck_limit":
                    self.screen = "gift_stuck_limit"
        elif s == "gift_result":
            if f["open"] == "ok":
                self.result_taps += 1
                if self.result_taps >= 2:
                    self.screen = "profile"
        elif s == "profile":
            by = f["button_y"] - self.prof_scroll
            if near(336, by - 140, 150, 150) and f["profile"] in ("sendable", "remove", "trade") and not f["was_sent"]:
                self.screen = "which_gift" if f["after_icon"] == "which" else "send_failed"
        elif s == "which_gift":
            for k, (gx, gy) in enumerate(G.GIFT_SPOTS):
                if near(gx, gy) and f["spot"] == k:
                    self.screen = "send_screen"
        elif s == "send_screen":
            if abs(x - 884) < 450 and 1650 < y < 1950 and f["send"] == "ok":
                f["was_sent"], f["arrow"] = True, True
                self.screen = "sent"

    def back(self):
        if (self.screen == "popup" and self.p.get("popup_stuck")) or (self.screen == "me" and self.p.get("map_stuck")):
            return
        self.screen = {"map": "map", "me": "map", "friends": "me", "gift_open": "profile", "gift_result": "profile", "gift_stuck_limit": "profile",
                       "profile": "friends", "which_gift": "profile", "send_screen": "which_gift", "sent": "profile", "send_failed": "profile",
                       "popup": "friends"}[self.screen]

    def swipe(self, x1, y1, x2, y2):
        if self.screen == "friends":
            self.scroll = max(0, min(self.scroll + (y1 - y2), self.max_scroll()))
        elif self.screen == "profile":
            self.prof_scroll = max(0, min(self.prof_scroll + (y1 - y2), self.p.get("prof_max", 3000)))


# ---------------------------------------------------------------------- the fake phone

class Writer(io.StringIO):
    """The file of the gift memory, opened to write: what is written is told when it is closed."""

    def __init__(self, name, rec, files):
        super().__init__()
        self.name, self.rec, self.files = name, rec, files

    def __exit__(self, *a):
        text = self.getvalue()
        self.rec.add("gift_write", self.name, jsonable(json.loads(text)))
        self.files[self.name] = text
        return super().__exit__(*a)


def record(spec):
    """Plays one story on the fake phone; returns the list of events."""
    Clock.t = START
    rec = Rec()
    Clock.rec = rec
    world = World(spec)
    sim = Sim(spec, world) if spec.get("sim") else None
    saved_g = {n: getattr(G, n) for n in ("time", "log", "setting", "wanted", "save_async", "ocr_text", "ocr_lines") if hasattr(G, n)}
    had_open = hasattr(G, "open")
    saved_s = {n: getattr(S, n) for n in ("time", "log", "tap", "back", "swipe", "screenshot", "PACKAGE")}
    try:
        G.time = S.time = Clock
        G.log = S.log = lambda text: rec.add("log", text)
        S.PACKAGE = spec.get("package", PACKAGE)
        settings = dict(spec.get("settings", {}))
        wanted = dict(spec.get("wanted", {}))
        G.setting = lambda key, default: settings.get(key, default)
        G.wanted = lambda key: bool(wanted.get(key, key not in ("spin_only_when_full", "daily_cycle")))
        G.save_async = lambda name, img: rec.add("save", name, world.index_of(img))
        files = dict(spec.get("files", {}))

        def fake_open(path, mode="r", *args, **kw):
            name = os.path.basename(path)
            if "w" in mode:
                return Writer(name, rec, files)
            content = files.get(name)
            rec.add("gift_read", name, content)
            if content is None:
                raise FileNotFoundError(name)
            return io.StringIO(content)
        G.open = fake_open

        def tap(x, y, ms=120):
            rec.add("tap", x, y) if ms == 120 else rec.add("press", x, y, ms)
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

        shots = list(spec.get("shots", [0]))

        def take(on_grab=None):
            n = world.shots
            world.shots += 1
            index = sim.frame() if sim else shots[min(n, len(shots) - 1)]
            Clock.t += spec.get("shot_seconds", 0.0)
            rec.add("shot", index, "real", False)
            return world.picture(index)
        S.screenshot = take

        def ocr_lines(img, y0=0, y1=None, scale=1.0):
            lines = [ln for ln in world.frame(img).get("lines", []) if ln[2] >= y0 and (y1 is None or ln[2] < y1)]
            rec.add("ocr", img.shape[0], img.shape[1], y0, y1, scale, mean(img), lines)
            return lines
        G.ocr_lines = ocr_lines

        def ocr_text(img, y0, y1):
            crop = img[y0:y1]
            f = world.frame(img)
            text = " ".join(f.get("texts", {}).get(str(y0), f.get("text", "")).upper().split())     # (as the real ocr_text() gives it)
            rec.add("ocr_text", crop.shape[0], crop.shape[1], mean(crop), text)
            return text
        G.ocr_text = ocr_text

        def lines_of(call):
            return [tuple(ln[:3]) + ([tuple(w) for w in ln[3]],) for ln in call["lines"]]

        for call in spec["calls"]:
            if "settings" in call:
                settings.update(call["settings"])
            if "advance" in call:
                Clock.t += call["advance"]
            rec.add("call", call["fn"], call.get("img"), None)
            st = copy.deepcopy(call["st"]) if "st" in call else None
            try:
                fn = call["fn"]
                img = world.picture(call["img"]) if "img" in call else None
                if fn == "parse_friends":
                    result = G.parse_friends(lines_of(call), img)
                elif fn == "sent_arrow":
                    result = bool(G.sent_arrow(img, call["y"]))
                elif fn == "gift_icon":
                    result = bool(G.gift_icon(img, call["y0"], call["y1"]))
                elif fn == "find_pill_button":
                    result = G.find_pill_button(img, *([call["y_min"]] if "y_min" in call else []))
                elif fn == "send_button":
                    result = G.send_button(img)
                elif fn == "has_sticker_button":
                    result = bool(G.has_sticker_button(img))
                elif fn == "is_gift_screen":
                    result = bool(G.is_gift_screen(img))
                elif fn == "is_friend_list":
                    result = bool(G.is_friend_list(img))
                elif fn == "any_text":
                    result = bool(G.any_text(lines_of(call), *call["needles"]))
                elif fn == "load_gift_state":
                    result = G.load_gift_state()
                elif fn == "save_gift_state":
                    G.save_gift_state(st)
                    result = None
                elif fn == "back_to_list":
                    result = bool(G.back_to_list())
                elif fn == "visit_friend":
                    G.visit_friend(copy.deepcopy(call["f"]), call["want_open"], call["want_send"], st)
                    result = None
                elif fn == "gifts_round":
                    G.gifts_round()
                    result = None
                else:
                    raise ValueError(call)
                rec.add("result", jsonable(result))
            except Exception as e:  # noqa: BLE001
                rec.add("raised", str(e))
            rec.add("state", {"st": None if st is None else jsonable(st)})
        return rec.events
    finally:
        for n, v in saved_g.items():
            setattr(G, n, v)
        if not had_open and hasattr(G, "open"):
            del G.open
        for n, v in saved_s.items():
            setattr(S, n, v)


# ---------------------------------------------------------------------- the stories

def stories():
    out = []

    def add(name, calls, frames=None, **spec):
        spec.update(calls=calls, frames=frames if frames is not None else [])
        out.append({"id": name, "spec": spec})

    def call(fn, **kw):
        return dict({"fn": fn}, **kw)

    def sim(name, calls, friends, **p):
        spec = {k: p.pop(k) for k in ("shot_seconds", "settings", "wanted", "files", "package") if k in p}
        add(name, calls, [], sim=dict(p, friends=friends), **spec)

    def new_state(**kw):
        return dict({"day": TODAY, "sent": [], "opened": [], "open_blocked": False, "send_blocked": False}, **kw)

    # ---- the memory of the day: load_gift_state(), save_gift_state()
    today_state = json.dumps(new_state(sent=["ANNA"], opened=["BEN"]))
    for name, content in (("no_file", None), ("empty_file", ""), ("not_json", "{oops"), ("empty_object", "{}"), ("today", today_state),
                          ("another_day", json.dumps(new_state(day="2026-11-21", sent=["ANNA"]))),
                          ("blocked", json.dumps(new_state(open_blocked=True, send_blocked=True))), ("day_is_a_number", json.dumps({"day": 5})),
                          ("trailing_text", today_state + " x")):
        add("load_%s" % name, [call("load_gift_state")], files={"gifts_state.json": content} if content is not None else {})
    add("load_for_another_app", [call("load_gift_state")], package="com.nianticlabs.pokemongo.ares", files={"gifts_state_ares.json": today_state})
    add("load_for_another_app_without_a_file", [call("load_gift_state")], package="com.nianticlabs.pokemongo.ares", files={"gifts_state.json": today_state})
    add("load_for_a_package_without_a_dot", [call("load_gift_state")], package="ares", files={"gifts_state_ares.json": today_state})
    add("load_for_a_package_that_ends_with_a_dot", [call("load_gift_state")], package="com.ares.", files={"gifts_state_.json": today_state})
    add("save_the_state", [call("save_gift_state", st=new_state(sent=["ANNA", "BEN"], opened=["CARL"], open_blocked=True))])
    add("save_the_state_of_another_app", [call("save_gift_state", st=new_state())], package="com.nianticlabs.pokemongo.ares")
    add("save_then_load", [call("save_gift_state", st=new_state(sent=["ANNA"])), call("load_gift_state")])

    # ---- the words in the lines: any_text()
    for i, (lines, needles) in enumerate([
        ([line("GIFT SENT", 300, 500)], ["GIFT", "SENT"]), ([line("SEND GIFT", 300, 500)], ["GIFT", "SENT"]),
        ([line("GIFT", 300, 500), line("SENT", 300, 600)], ["GIFT", "SENT"]), ([line("NO GIFTS LEFT", 300, 500)], ["NO", "GIFT"]),
        ([], ["GIFT"]), ([line("HELLO", 300, 500)], []), ([], []), ([line("DON'T HAVE ANY", 300, 500)], ["DON'T HAVE"]),
        ([line("LIMIT", 300, 500), line("HELLO", 300, 600)], ["LIMIT"]), ([line("limit", 300, 500)], ["LIMIT"]),
    ]):
        add("any_text_%02d" % i, [call("any_text", lines=lines, needles=needles)])

    # ---- the friend list: is_friend_list()
    for i, text in enumerate(["SOCIAL FRIENDS", "FRIENDS ME", "FRIENDS HOME", "FRIENDS PARTY", "FRIENDS", "SOCIAL", "ME PARTY", "FRIENDS TIMES", "  friends   social ", "",
                              "FRIENDSHIP SOCIAL", "FRIENDS AME", "FRIENDS GAME"]):
        add("is_friend_list_%02d" % i, [call("is_friend_list", img=0)], [frame(texts={"0": text})])
    add("is_friend_list_the_strip_is_the_top", [call("is_friend_list", img=0)], [frame(texts={"0": "", "1": "FRIENDS SOCIAL"}, text="")])

    # ---- back to the list
    on_list, off_list = frame(texts={"0": "SOCIAL FRIENDS"}), frame(texts={})
    add("back_to_list_at_once", [call("back_to_list")], [off_list, on_list], shots=[1])
    add("back_to_list_second_try", [call("back_to_list")], [off_list, on_list], shots=[0, 1])
    add("back_to_list_third_try", [call("back_to_list")], [off_list, on_list], shots=[0, 0, 1])
    add("back_to_list_never", [call("back_to_list")], [off_list, on_list], shots=[0])

    # ---- the screens of a gift
    add("is_gift_screen_the_bow", [call("is_gift_screen", img=0)], [frame([PLAIN, ["rect", 500, 300, 600, 300, MAGENTA]])])
    add("is_gift_screen_no_bow", [call("is_gift_screen", img=0)], [frame()])
    add("is_gift_screen_exactly_40000", [call("is_gift_screen", img=0)], [frame([PLAIN, ["rect", 500, 300, 200, 200, MAGENTA]])])
    add("is_gift_screen_40001", [call("is_gift_screen", img=0)], [frame([PLAIN, ["rect", 500, 300, 200, 200, MAGENTA], ["rect", 800, 300, 1, 1, MAGENTA]])])
    add("is_gift_screen_the_bow_is_above_the_part_that_is_looked_at", [call("is_gift_screen", img=0)], [frame([PLAIN, ["rect", 500, 0, 600, 150, MAGENTA]])])
    add("is_gift_screen_the_bow_is_left_of_the_part_that_is_looked_at", [call("is_gift_screen", img=0)], [frame([PLAIN, ["rect", 0, 300, 400, 300, MAGENTA]])])
    add("is_gift_screen_the_bow_in_the_corner", [call("is_gift_screen", img=0), call("is_gift_screen", img=1), call("is_gift_screen", img=2), call("is_gift_screen", img=3)],
        [frame([PLAIN, ["rect", 400, 150, 201, 200, MAGENTA]]), frame([PLAIN, ["rect", 1199, 700, 201, 200, MAGENTA]]),
         frame([PLAIN, ["rect", 1200, 700, 500, 500, MAGENTA]]), frame([PLAIN, ["rect", 1199, 700, 500, 500, MAGENTA]])])
    for i, (h, s, v) in enumerate([(139, 200, 200), (140, 200, 200), (172, 200, 200), (173, 200, 200), (150, 120, 200), (150, 121, 200), (150, 200, 120), (150, 200, 121)]):
        add("is_gift_screen_colour_%02d" % i, [call("is_gift_screen", img=0)], [frame([PLAIN, ["rect", 500, 300, 600, 300, bgr_for(h, s, v)]])])
    add("is_gift_screen_a_smaller_picture", [call("is_gift_screen", img=0)], [frame([PLAIN, ["rect", 500, 300, 1000, 500, MAGENTA], ["size", 884, 1104]])])
    # the edges of the part that is looked at (rows 150 to 899, columns 400 to 1399): 40000 pink pixels are not enough, one more is
    bow_base = ["rect", 500, 300, 200, 200, MAGENTA]
    for name, (x, y) in (("above", (800, 149)), ("below", (800, 900)), ("left", (399, 600)), ("right", (1400, 600))):
        add("is_gift_screen_40000_and_one_pixel_outside_%s" % name, [call("is_gift_screen", img=0)], [frame([PLAIN, bow_base, ["rect", x, y, 1, 1, MAGENTA]])])
    for name, (x, y) in (("first_row", (800, 150)), ("last_row", (800, 899)), ("first_column", (400, 600)), ("last_column", (1399, 600))):
        add("is_gift_screen_40000_and_one_pixel_at_the_edge_%s" % name, [call("is_gift_screen", img=0)], [frame([PLAIN, bow_base, ["rect", x, y, 1, 1, MAGENTA]])])

    def pill(x, y, w, h, c=GREEN):
        return ["rect", x, y, w, h, c]
    pills = [
        ("one", [pill(500, 1700, 800, 200)]), ("none", []), ("two_the_bigger_wins", [pill(300, 1600, 600, 150), pill(500, 1800, 800, 200)]),
        ("two_the_first_is_bigger", [pill(500, 1700, 800, 200), pill(300, 1950, 500, 100)]),
        ("width_449", [pill(500, 1700, 449, 150)]), ("width_450", [pill(500, 1700, 450, 150)]), ("width_451", [pill(500, 1700, 451, 150)]),
        ("width_1299", [pill(300, 1700, 1299, 200)]), ("width_1300", [pill(300, 1700, 1300, 200)]),
        ("height_80", [pill(500, 1700, 800, 80)]), ("height_81", [pill(500, 1700, 800, 81)]), ("height_319", [pill(500, 1700, 800, 319)]),
        ("height_320", [pill(500, 1700, 800, 320)]), ("not_wide_enough_for_its_height", [pill(500, 1650, 500, 200)]), ("just_wide_enough", [pill(500, 1650, 505, 200)]),
        ("middle_far_left", [pill(0, 1700, 800, 200)]), ("middle_just_near", [pill(185, 1700, 800, 200)]), ("middle_just_far", [pill(184, 1700, 800, 200)]),
        ("middle_right_just_near", [pill(783, 1700, 800, 200)]), ("middle_right_just_far", [pill(784, 1700, 800, 200)]),
        ("partly_above_the_part_that_is_looked_at", [pill(500, 1400, 800, 200)]), ("a_third_of_it_is_above", [pill(500, 1400, 800, 300)]),
        ("a_pale_green_background_only", [["rect", 0, 1500, 1768, 700, [200, 255, 200]]]),
        ("the_button_on_a_pale_background", [["rect", 0, 1500, 1768, 700, [200, 255, 200]], pill(500, 1700, 800, 200)]),
        ("a_small_hole_is_closed", [pill(500, 1700, 800, 200), ["rect", 880, 1790, 10, 10, [255, 255, 255]]]),
        ("a_thin_line_is_opened_away", [pill(500, 1700, 800, 8)]),
        ("two_that_touch_are_one", [pill(500, 1700, 400, 150), pill(900, 1700, 400, 150)]),
        ("two_apart_by_24", [pill(500, 1700, 400, 150), pill(924, 1700, 400, 150)]),
        ("two_apart_by_25", [pill(500, 1700, 400, 150), pill(925, 1700, 400, 150)]),
        ("two_apart_by_26", [pill(500, 1700, 400, 150), pill(926, 1700, 400, 150)]),
    ]
    for name, ops in pills:
        add("pill_%s" % name, [call("find_pill_button", img=0)], [frame([PLAIN] + ops)])
    add("pill_from_row_1000", [call("find_pill_button", img=0, y_min=1000), call("find_pill_button", img=0)], [frame([PLAIN, pill(500, 1200, 800, 200)])])
    add("pill_from_row_0", [call("find_pill_button", img=0, y_min=0)], [frame([PLAIN, pill(500, 300, 800, 200)])])
    for i, (h, s, v) in enumerate([(44, 150, 220), (45, 150, 220), (95, 150, 220), (96, 150, 220), (67, 62, 201), (67, 63, 201), (67, 101, 170), (67, 101, 171),
                                   (67, 101, 247), (67, 101, 248)]):
        add("pill_colour_%02d" % i, [call("find_pill_button", img=0)], [frame([PLAIN, pill(500, 1700, 800, 200, bgr_for(h, s, v))])])

    add("has_sticker_button_yes", [call("has_sticker_button", img=0)], [frame(texts={"1480": "ADD STICKER"})])
    add("has_sticker_button_no", [call("has_sticker_button", img=0)], [frame(texts={"1480": "SEND"})])
    add("has_sticker_button_a_longer_word", [call("has_sticker_button", img=0)], [frame(texts={"1480": "STICKERS"})])
    add("has_sticker_button_another_strip", [call("has_sticker_button", img=0)], [frame(texts={"1480": "", "1481": "ADD STICKER"}, text="")])
    add("send_button_by_the_sticker", [call("send_button", img=0)], [frame([PLAIN, pill(500, 1700, 800, 200)], texts={"1480": "ADD STICKER"})])
    add("send_button_the_pill", [call("send_button", img=0)], [frame([PLAIN, pill(500, 1700, 800, 200)], texts={})])
    add("send_button_nothing", [call("send_button", img=0)], [frame(texts={})])

    # ---- the grey arrow and the pink bow of a friend row
    def grey_ops(n, y=100):
        """exactly n grey pixels in the places that sent_arrow(img, y) looks at (x 320-420, y+90 to y+200)"""
        full, rest = divmod(n, 100)
        ops = [["rect", 320, y + 90, 100, full, GREY]] if full else []
        if rest:
            ops.append(["rect", 320, y + 90 + full, rest, 1, GREY])
        return ops
    for n in (0, 1199, 1200, 1201, 11000):
        add("sent_arrow_%d_grey_pixels" % n, [call("sent_arrow", img=0, y=100)], [frame([PLAIN] + grey_ops(n))])
    for i, (h, s, v) in enumerate([(0, 39, 139), (0, 40, 139), (0, 0, 95), (0, 0, 96), (0, 0, 179), (0, 0, 180), (60, 30, 110)]):
        add("sent_arrow_colour_%02d" % i, [call("sent_arrow", img=0, y=100)], [frame([PLAIN, ["rect", 320, 190, 100, 110, bgr_for(h, s, v)]])])
    add("sent_arrow_a_place_that_is_not_looked_at", [call("sent_arrow", img=0, y=100)],
        [frame([PLAIN, ["rect", 0, 190, 320, 110, GREY], ["rect", 420, 190, 300, 110, GREY], ["rect", 320, 0, 100, 190, GREY], ["rect", 320, 300, 100, 300, GREY]])])
    add("sent_arrow_at_the_bottom", [call("sent_arrow", img=0, y=2100), call("sent_arrow", img=0, y=2150), call("sent_arrow", img=0, y=2118), call("sent_arrow", img=0, y=2117)],
        [frame([PLAIN, ["rect", 320, 2190, 100, 18, GREY]])])
    add("sent_arrow_above_the_picture", [call("sent_arrow", img=0, y=-50), call("sent_arrow", img=0, y=-91), call("sent_arrow", img=0, y=-199), call("sent_arrow", img=0, y=-200)],
        [frame([PLAIN, ["rect", 320, 0, 100, 300, GREY]])])
    add("sent_arrow_the_first_row_counts", [call("sent_arrow", img=0, y=-91), call("sent_arrow", img=0, y=-90), call("sent_arrow", img=0, y=-89), call("sent_arrow", img=0, y=-92)],
        [frame([PLAIN, ["rect", 320, 0, 100, 1, GREY], ["rect", 320, 1, 100, 11, GREY], ["rect", 320, 12, 1, 1, GREY]])])
    add("sent_arrow_far_above_the_picture", [call("sent_arrow", img=0, y=-500), call("sent_arrow", img=0, y=-2300)], [frame([PLAIN, ["rect", 320, 0, 100, 1800, GREY]])])
    add("sent_arrow_a_smaller_picture", [call("sent_arrow", img=0, y=100), call("sent_arrow", img=0, y=800)],
        [frame([PLAIN, ["rect", 320, 100, 400, 2000, GREY], ["size", 884, 1104]])])
    # the edges of the part that is looked at (rows y + 90 to y + 199, columns 320 to 419): 1200 grey pixels are not enough, one more is
    arrow_base = ["rect", 320, 200, 100, 12, GREY]
    for name, (x, y) in (("above", (320, 189)), ("below", (320, 300)), ("left", (319, 250)), ("right", (420, 250))):
        add("sent_arrow_1200_and_one_pixel_outside_%s" % name, [call("sent_arrow", img=0, y=100)], [frame([PLAIN, arrow_base, ["rect", x, y, 1, 1, GREY]])])
    for name, (x, y) in (("first_row", (320, 190)), ("last_row", (419, 299)), ("first_column", (320, 250)), ("last_column", (419, 250))):
        add("sent_arrow_1200_and_one_pixel_at_the_edge_%s" % name, [call("sent_arrow", img=0, y=100)], [frame([PLAIN, arrow_base, ["rect", x, y, 1, 1, GREY]])])

    def pink_ops(n, y=100):
        """exactly n pink pixels in the places that gift_icon(img, y, y + 300) looks at (x 450-900)"""
        full, rest = divmod(n, 100)
        ops = [["rect", 450, y, 100, full, MAGENTA]] if full else []
        if rest:
            ops.append(["rect", 450, y + full, rest, 1, MAGENTA])
        return ops
    for n in (0, 1499, 1500, 1501, 30000):
        add("gift_icon_%d_pink_pixels" % n, [call("gift_icon", img=0, y0=100, y1=400)], [frame([PLAIN] + pink_ops(n))])
    for i, (h, s, v) in enumerate([(139, 200, 200), (140, 200, 200), (172, 200, 200), (173, 200, 200), (150, 120, 200), (150, 121, 200), (150, 157, 140), (150, 157, 141)]):
        add("gift_icon_colour_%02d" % i, [call("gift_icon", img=0, y0=100, y1=400)], [frame([PLAIN, ["rect", 450, 100, 450, 300, bgr_for(h, s, v)]])])
    add("gift_icon_places", [call("gift_icon", img=0, y0=100, y1=400)],
        [frame([PLAIN, ["rect", 0, 100, 450, 300, MAGENTA], ["rect", 900, 100, 300, 300, MAGENTA], ["rect", 450, 0, 450, 100, MAGENTA], ["rect", 450, 400, 450, 300, MAGENTA]])])
    add("gift_icon_the_rows_are_taken_from_y0", [call("gift_icon", img=0, y0=100, y1=400), call("gift_icon", img=0, y0=101, y1=400), call("gift_icon", img=0, y0=99, y1=400)],
        [frame([PLAIN, ["rect", 450, 99, 450, 1, MAGENTA]] + pink_ops(1499, 100) + [["rect", 450, 100, 1, 1, MAGENTA]])])
    add("gift_icon_up_to_y1", [call("gift_icon", img=0, y0=100, y1=400), call("gift_icon", img=0, y0=100, y1=401)], [frame([PLAIN, ["rect", 450, 397, 450, 4, MAGENTA]])])
    add("gift_icon_above_the_picture", [call("gift_icon", img=0, y0=-100, y1=30)], [frame([PLAIN, ["rect", 450, 0, 450, 30, MAGENTA]])])
    add("gift_icon_end_just_above_the_picture", [call("gift_icon", img=0, y0=0, y1=-1), call("gift_icon", img=0, y0=0, y1=-2208), call("gift_icon", img=0, y0=0, y1=-2207)],
        [frame([PLAIN] + pink_ops(30000, 100))])
    add("gift_icon_the_first_row_counts", [call("gift_icon", img=0, y0=-5, y1=30), call("gift_icon", img=0, y0=0, y1=30), call("gift_icon", img=0, y0=1, y1=30)],
        [frame([PLAIN, ["rect", 450, 0, 450, 1, MAGENTA], ["rect", 450, 1, 450, 3, MAGENTA]])])
    add("gift_icon_end_above_the_picture", [call("gift_icon", img=0, y0=-300, y1=-100)], [frame([PLAIN, ["rect", 450, 0, 450, 2000, MAGENTA]])])
    add("gift_icon_below_the_picture", [call("gift_icon", img=0, y0=2200, y1=2500), call("gift_icon", img=0, y0=2100, y1=2500), call("gift_icon", img=0, y0=2205, y1=2500),
                                        call("gift_icon", img=0, y0=2300, y1=2500)], [frame([PLAIN, ["rect", 450, 2100, 450, 108, MAGENTA]])])
    add("gift_icon_empty_rows", [call("gift_icon", img=0, y0=400, y1=400), call("gift_icon", img=0, y0=400, y1=300)], [frame([PLAIN] + pink_ops(30000, 100))])
    add("gift_icon_a_smaller_picture", [call("gift_icon", img=0, y0=100, y1=400)], [frame([PLAIN, ["rect", 450, 100, 450, 600, MAGENTA], ["size", 884, 1104]])])
    # the edges of the part that is looked at (rows 100 to 399, columns 450 to 899): 1500 pink pixels are not enough, one more is
    icon_base = ["rect", 500, 200, 100, 15, MAGENTA]
    for name, (x, y) in (("above", (700, 99)), ("below", (700, 400)), ("left", (449, 300)), ("right", (900, 300))):
        add("gift_icon_1500_and_one_pixel_outside_%s" % name, [call("gift_icon", img=0, y0=100, y1=400)], [frame([PLAIN, icon_base, ["rect", x, y, 1, 1, MAGENTA]])])
    for name, (x, y) in (("first_row", (700, 100)), ("last_row", (700, 399)), ("first_column", (450, 300)), ("last_column", (899, 300))):
        add("gift_icon_1500_and_one_pixel_at_the_edge_%s" % name, [call("gift_icon", img=0, y0=100, y1=400)], [frame([PLAIN, icon_base, ["rect", x, y, 1, 1, MAGENTA]])])

    # ---- the rows of the friend list: parse_friends()
    def friends_of(name, lines, img=None):
        add(name, [call("parse_friends", lines=lines, **({"img": 0} if img is not None else {}))], [img] if img is not None else [])
    friends_of("friends_nothing", [])
    friends_of("friends_one_today", [line("ANNA TODAY", 520, 600)])
    for i, text in enumerate(["ANNA 2+ DAYS AGO", "ANNA YESTERDAY", "ANNA 3 HOURS AGO", "ANNA 5 H AGO", "ANNA JUST NOW", "ANNA 1 DAY AGO", "ANNA 12+ DAYS AGO", "ANNA 2 HOUR AGO",
                              "ANNA 3H AGO", "ANNA 7 DAYSAGO", "ANNA 4+DAYS AGO", "ANNA ONLINE", "ANNA", "ANNA SENT", "ANNA TODAY GIFT!"]):
        friends_of("friends_when_%02d" % i, [line(text, 520, 600)])
    for i, text in enumerate(["ANNA DAYS AGO", "ANNA H AGO", "ANNA HOURS AGO", "ANNA 2 H", "ANNA 2 HOUR", "ANNA +2 DAYS AGO", "ANNA 2 DAY", "ANNA 2 DAYS", "ANNA 2 AGO",
                              "ANNA JUST", "ANNA NOW", "ANNA 2+\u00a0DAYS AGO", "ANNA \u0662 DAYS AGO", "ANNA 2\u2003H AGO", "ANNA 12H AGO", "ANNA 2 HOURSAGO", "ANNA 2 HOURAGO",
                              "ANNA 22+ DAYAGO", "ANNA 2 HO AGO", "ANNA 2 HOUS AGO", "ANNA 3 d AGO", "ANNA 3 DAYS A GO", "ANNA 2+ + DAYS AGO", "ANNA 2 HH AGO",
                              "ANNA 2 HOURS", "ANNA 2 HOURX AGO", "ANNA 2 HOURSX AGO", "ANNA 2 DAYS", "ANNA 2 DAYX AGO"]):
        friends_of("friends_more_when_%02d" % i, [line(text, 520, 600)])
    friends_of("friends_the_last_name_before_the_time", [line("OLD NAME TODAY", 520, 600)])
    friends_of("friends_a_name_that_is_a_word_of_the_screen", [line("SENT TODAY", 520, 600), line("FRIENDS TODAY", 520, 1000), line("UNKNOWN TODAY", 520, 1400)])
    friends_of("friends_the_name_before_a_word_of_the_screen", [line("ANNA SENT TODAY", 520, 600)])
    for i, name in enumerate(["AB", "ABC", "ABCDEFGHIJKLMNO", "ABCDEFGHIJKLMNOP", "A1_B2", "Anna", "ANNA-B", "123", "1234567890123456", "ÄNNA"]):
        friends_of("friends_name_%02d" % i, [line(name + " TODAY", 520, 600)])
    friends_of("friends_the_same_name_twice_in_a_row", [line("ANNA TODAY", 520, 600), line("ANNA TODAY", 520, 800)])
    friends_of("friends_the_same_name_not_in_a_row", [line("ANNA TODAY", 520, 600), line("BERT TODAY", 520, 1000), line("ANNA TODAY", 520, 1400)])
    friends_of("friends_a_gift_in_the_text", [line("ANNA TODAY", 520, 600), line("SENT YOU A GIFT!", 520, 680), line("BERT TODAY", 520, 1000)])
    friends_of("friends_a_gift_mark_only", [line("ANNA TODAY", 520, 600), line("GIFT! OPEN", 520, 680), line("BERT TODAY", 520, 1000)])
    friends_of("friends_a_gift_of_the_next_friend_is_not_mine", [line("ANNA TODAY", 520, 600), line("BERT TODAY", 520, 1000), line("SENT YOU A GIFT!", 520, 1080)])
    friends_of("friends_a_gift_at_the_edge_of_the_band", [line("ANNA TODAY", 520, 600), line("SENT YOU A GIFT!", 520, 999), line("BERT TODAY", 520, 1000)])
    friends_of("friends_a_gift_in_the_line_of_the_next_name", [line("ANNA TODAY", 520, 600), line("SENT YOU", 520, 1000), line("BERT TODAY", 520, 1000)])
    friends_of("friends_a_gift_at_the_name_height_is_not_in_the_band", [line("ANNA TODAY", 520, 600), line("SENT YOU A GIFT!", 520, 600)])
    friends_of("friends_the_last_band_is_520_high", [line("ANNA TODAY", 520, 600), line("SENT YOU A GIFT!", 520, 1119)])
    friends_of("friends_the_last_band_ends_at_520", [line("ANNA TODAY", 520, 600), line("SENT YOU A GIFT!", 520, 1120)])
    friends_of("friends_the_name_in_the_line_below", [line("ANNA", 520, 600), line("ANNA SENT YOU A GIFT!", 520, 680)])
    friends_of("friends_the_name_starts_the_line_below", [line("ANNA", 520, 600), line("ANNAMARIE CAUGHT A PIDGEY!", 520, 680)])
    friends_of("friends_the_name_is_inside_the_line_below", [line("ANNA", 520, 600), line("TODAY ANNA CAUGHT A PIDGEY!", 520, 680)])
    friends_of("friends_the_name_is_part_of_a_word_below", [line("ANNA", 520, 600), line("BANNAS CAUGHT A PIDGEY!", 520, 680)])
    friends_of("friends_the_name_is_far_below", [line("ANNA", 520, 600), line("ANNA CAUGHT A PIDGEY!", 520, 1100)])
    friends_of("friends_the_name_is_just_below", [line("ANNA", 520, 600), line("ANNA CAUGHT A PIDGEY!", 520, 1099)])
    friends_of("friends_the_name_is_level_with", [line("ANNA", 520, 600), line("ANNA CAUGHT A PIDGEY!", 520, 600)])
    friends_of("friends_the_name_is_above", [line("ANNA CAUGHT A PIDGEY!", 520, 500), line("ANNA", 520, 600)])
    friends_of("friends_the_name_four_lines_down", [line("ANNA", 520, 600), line("HELLO", 520, 650), line("THERE", 520, 700), line("WORLD", 520, 750), line("ANNA CAUGHT", 520, 800)])
    friends_of("friends_the_name_three_lines_down", [line("ANNA", 520, 600), line("HELLO", 520, 650), line("THERE", 520, 700), line("ANNA CAUGHT", 520, 750)])
    friends_of("friends_a_name_of_three_letters_is_too_short_below", [line("ANN", 520, 600), line("ANN CAUGHT A PIDGEY!", 520, 680)])
    friends_of("friends_a_name_of_digits_below", [line("1234", 520, 600), line("1234 CAUGHT A PIDGEY!", 520, 680)])
    friends_of("friends_two_rows_one_with_the_time_and_one_below", [line("ANNA TODAY", 520, 600), line("BERT", 520, 1000), line("BERT SENT YOU A GIFT!", 520, 1080)])
    friends_of("friends_a_word_that_is_found_earlier_in_the_line", [line("ANNA ANNA TODAY", 520, 600)])
    friends_of("friends_the_word_found_first_is_after_the_time", [line("TODAY ANNA 2 H AGO", 520, 600)])
    friends_of("friends_a_name_inside_another_word_before_the_time", [line("MARIANNA ANNA TODAY", 520, 600)])
    friends_of("friends_text_without_words", [["ANNA TODAY", 520, 600, []]])
    # a word that the text does not hold counts as one that comes before the time word (str.find says -1)
    friends_of("friends_a_word_that_is_not_in_the_text_counts_as_before_the_time_word", [["TODAY", 520, 600, [["ANNA", 520, 600]]]])
    friends_of("friends_a_word_that_is_not_in_the_text_and_a_time_word_further_on", [["HI TODAY", 520, 600, [["ANNA", 520, 600]]]])
    friends_of("friends_a_word_that_is_not_in_the_text_and_no_time_word", [["HELLO", 520, 600, [["ANNA", 520, 600]]]])
    friends_of("friends_the_name_is_one_pixel_below", [line("ANNA", 520, 600), line("ANNA CAUGHT A PIDGEY!", 520, 601)])
    for n in (14, 15, 16):
        word = "ABCDEFGHIJKLMNOP"[:n]
        friends_of("friends_a_name_of_%d_letters_with_the_line_below" % n, [line(word, 520, 600), line(word + " CAUGHT A PIDGEY!", 520, 680)])
    friends_of("friends_the_x_of_the_name_is_taken", [line("MARY ANNA TODAY", 300, 600)])
    # with the picture: the pink bow and the grey arrow
    rows_img = frame([PLAIN, ["rect", 500, 750, 300, 200, MAGENTA], ["rect", 330, 1100, 80, 90, GREY], ["rect", 330, 1500, 80, 90, GREY], ["rect", 500, 1550, 300, 200, MAGENTA]])
    three = [line("ANNA TODAY", 520, 600), line("BERT TODAY", 520, 1000), line("CARL TODAY", 520, 1400)]
    friends_of("friends_the_bow_and_the_arrow_are_read", three, rows_img)
    friends_of("friends_no_picture_no_bow", three)
    friends_of("friends_the_text_is_enough_for_the_gift", [line("ANNA TODAY", 520, 600), line("SENT YOU A GIFT!", 520, 680)], frame([PLAIN]))
    friends_of("friends_the_last_row_looks_520_down", [line("ANNA TODAY", 520, 600)], frame([PLAIN, ["rect", 500, 1100, 300, 200, MAGENTA]]))
    friends_of("friends_the_last_row_does_not_look_further", [line("ANNA TODAY", 520, 600)], frame([PLAIN, ["rect", 500, 1120, 300, 200, MAGENTA]]))
    # the last row looks at the rows 0 to 519 below its name: 1500 pink pixels are not enough, one more is
    friends_of("friends_the_last_row_looks_519_down", [line("ANNA TODAY", 520, 600)], frame([PLAIN, ["rect", 500, 700, 100, 15, MAGENTA], ["rect", 500, 1119, 1, 1, MAGENTA]]))
    friends_of("friends_the_last_row_does_not_look_520_down_1500", [line("ANNA TODAY", 520, 600)], frame([PLAIN, ["rect", 500, 700, 100, 15, MAGENTA], ["rect", 500, 1120, 1, 1, MAGENTA]]))
    # a row that has a next row far below looks at 520 rows only: the same count, one more pixel
    far_rows = [line("ANNA TODAY", 520, 600), line("BERT TODAY", 520, 1400)]
    friends_of("friends_a_row_with_the_next_far_below_looks_519_down", far_rows, frame([PLAIN, ["rect", 500, 700, 100, 15, MAGENTA], ["rect", 500, 1119, 1, 1, MAGENTA]]))
    friends_of("friends_a_row_with_the_next_far_below_does_not_look_520_down", far_rows, frame([PLAIN, ["rect", 500, 700, 100, 15, MAGENTA], ["rect", 500, 1120, 1, 1, MAGENTA]]))
    friends_of("friends_the_bow_of_the_next_row_is_not_mine", [line("ANNA TODAY", 520, 600), line("BERT TODAY", 520, 1000)], frame([PLAIN, ["rect", 500, 1050, 300, 200, MAGENTA]]))
    friends_of("friends_a_friend_row_close_to_the_bottom", [line("ANNA TODAY", 520, 2050)], frame([PLAIN, ["rect", 330, 2150, 80, 58, GREY], ["rect", 500, 2100, 300, 108, MAGENTA]]))

    # ---- a visit to one friend: visit_friend()
    def visit(name, friends, want_open=True, want_send=True, st=None, **p):
        i = p.pop("who", 0)
        f = {"name": friends[i]["name"], "x": 520, "y": 600 + 400 * i, "gift": friends[i].get("gift") is not None, "arrow": bool(friends[i].get("arrow"))}
        sim(name, [call("visit_friend", f=f, want_open=want_open, want_send=want_send, st=st if st is not None else new_state())], friends, start="friends", **p)

    anna = {"name": "ANNA"}
    visit("visit_send", [anna])
    visit("visit_send_with_a_green_button", [dict(anna, sticker="pill")])
    visit("visit_send_with_no_button_at_all", [dict(anna, sticker="none")])
    visit("visit_send_the_second_gift", [dict(anna, spot=1)])
    visit("visit_send_the_third_gift", [dict(anna, spot=2)])
    visit("visit_send_no_gift_place_works", [dict(anna, spot=None)])
    visit("visit_send_is_stuck", [dict(anna, send="stuck")])
    visit("visit_send_is_stuck_with_a_green_button", [dict(anna, send="stuck", sticker="pill")])
    visit("visit_send_grey_icon", [dict(anna, profile="grey")])
    visit("visit_send_near_remove", [dict(anna, profile="remove")])
    visit("visit_send_trade", [dict(anna, profile="trade")])
    visit("visit_send_already_sent", [dict(anna, profile="sent")])
    visit("visit_send_no_label", [dict(anna, profile="none")])
    visit("visit_send_label_below_the_screen", [dict(anna, button_y=2500)])
    visit("visit_send_label_far_below_the_screen", [dict(anna, button_y=3300)])
    visit("visit_send_label_too_high", [dict(anna, button_y=1200, scroll0=800)])
    visit("visit_send_label_too_high_for_good", [dict(anna, button_y=300)])
    visit("visit_send_label_at_449", [dict(anna, button_y=449 + 0, scroll0=0)])
    visit("visit_send_label_at_450", [dict(anna, button_y=450)])
    visit("visit_send_no_gifts_left", [dict(anna, after_icon="failed", fail="nogift")])
    visit("visit_send_dont_have", [dict(anna, after_icon="failed", fail="dont")])
    visit("visit_send_something_else", [dict(anna, after_icon="failed", fail="other")])
    visit("visit_send_not_wanted", [dict(anna)], want_send=False)
    visit("visit_nothing_wanted", [dict(anna)], want_open=False, want_send=False)
    visit("visit_a_name_that_was_there_before", [anna], st=new_state(sent=["BERT"], opened=["CARL"]))
    visit("visit_the_second_friend", [{"name": "BERT"}, anna], who=1)
    # a gift that waits
    for kind in ("ok", "limit", "maximum", "bagfull", "stuck", "stuck_limit"):
        visit("visit_open_%s" % kind, [dict(anna, gift="text", open=kind)])
        visit("visit_open_%s_send_not_wanted" % kind, [dict(anna, gift="text", open=kind)], want_send=False)
    visit("visit_open_with_no_green_button", [dict(anna, gift="text", open_pill=False)])
    visit("visit_open_the_bow_only", [dict(anna, gift="icon")])
    visit("visit_open_not_wanted", [dict(anna, gift="text")], want_open=False, want_send=False)
    visit("visit_open_not_wanted_but_send", [dict(anna, gift="text")], want_open=False)
    visit("visit_gift_screen_that_the_list_did_not_show", [dict(anna, gift=None, pending=True)], want_open=False)
    visit("visit_gift_screen_that_the_list_did_not_show_open_wanted", [dict(anna, gift=None, pending=True)])
    visit("visit_gift_shown_but_none_there", [dict(anna, gift="text", pending=False)], want_send=False)
    visit("visit_gift_shown_but_none_there_and_send", [dict(anna, gift="text", pending=False)])
    visit("visit_open_then_send", [dict(anna, gift="text", open="ok", sticker="pill")])
    visit("visit_open_then_no_label", [dict(anna, gift="text", open="ok", profile="none")])

    # the icon above the label: how much of it is pink and which pink
    for px in (1499, 1500, 1501):
        visit("visit_icon_%d_pink_pixels" % px, [dict(anna, icon_px=px)])
    for i, (h, sat, v) in enumerate([(139, 200, 200), (140, 200, 200), (172, 200, 200), (173, 200, 200), (150, 100, 201), (150, 101, 201), (150, 200, 120), (150, 200, 121)]):
        visit("visit_icon_colour_%02d" % i, [dict(anna, icon_color=bgr_for(h, sat, v))])
    # the edges of the part around the icon that is looked at (rows -120 to 109 and columns -136 to 133 from where the bot taps): 1500 pink pixels are not enough
    for name, xy in (("above", [0, -121]), ("row_-120", [0, -120]), ("row_109", [0, 109]), ("below", [0, 110]),
                     ("left", [-137, 0]), ("column_-136", [-136, 0]), ("column_133", [133, 0]), ("right", [134, 0])):
        visit("visit_icon_1500_and_one_pixel_%s" % name, [dict(anna, icon_px=1500, icon_extra=[xy])])
    visit("visit_icon_at_the_top_of_the_picture", [dict(anna, icon_px=1501, button_y=250)])
    visit("visit_icon_cut_off_by_the_top_of_the_picture", [dict(anna, button_y=250)])
    # REMOVE FRIEND near the icon or not
    for dy in (-300, -299, 299, 300):
        visit("visit_remove_friend_%+d_from_the_icon" % dy, [dict(anna, profile="remove", remove_dy=dy)])

    # ---- the whole round: gifts_round()
    def rnd(name, friends, st=None, **p):
        files = p.pop("files", {})
        if st is not None:
            files = dict(files, **{"gifts_state.json": json.dumps(st)})
        sim(name, [call("gifts_round")], friends, files=files, **p)

    names = ["ANNA", "BERT", "CARL", "DIRK", "EMMA", "FRED", "GERT", "HANS", "INGE", "JANA"]
    rnd("round_nobody_wants_anything", [{"name": "ANNA"}], wanted={"gifts_open": False, "gifts_send": False})
    rnd("round_open_is_blocked_and_send_is_off", [{"name": "ANNA"}], st=new_state(open_blocked=True), wanted={"gifts_send": False})
    rnd("round_send_is_blocked_and_open_is_off", [{"name": "ANNA"}], st=new_state(send_blocked=True), wanted={"gifts_open": False})
    rnd("round_both_are_blocked", [{"name": "ANNA"}], st=new_state(open_blocked=True, send_blocked=True))
    rnd("round_no_friend_tab", [{"name": "ANNA"}], tab_dead=True)
    rnd("round_no_friends", [])
    rnd("round_one_friend", [{"name": "ANNA"}])
    rnd("round_three_friends", [{"name": n} for n in names[:3]])
    rnd("round_a_friend_that_got_a_gift_from_me_is_not_visited", [{"name": "ANNA", "arrow": True}, {"name": "BERT"}])
    rnd("round_a_friend_from_the_file_is_not_visited", [{"name": "ANNA"}, {"name": "BERT"}], st=new_state(sent=["ANNA"]))
    rnd("round_gifts_to_open_and_to_send", [{"name": "ANNA", "gift": "text"}, {"name": "BERT"}, {"name": "CARL", "gift": "icon", "sticker": "pill"}])
    rnd("round_only_open", [{"name": "ANNA", "gift": "text"}, {"name": "BERT"}], wanted={"gifts_send": False})
    rnd("round_only_send", [{"name": "ANNA", "gift": "text"}, {"name": "BERT"}], wanted={"gifts_open": False})
    rnd("round_a_gift_and_an_arrow_with_open_off", [{"name": "ANNA", "gift": "text", "arrow": True}, {"name": "BERT"}], wanted={"gifts_open": False})
    rnd("round_a_gift_and_an_arrow_with_open_on", [{"name": "ANNA", "gift": "text", "arrow": True}, {"name": "BERT"}])
    rnd("round_the_limit_stops_opening", [{"name": "ANNA", "gift": "text", "open": "limit"}, {"name": "BERT", "gift": "text"}, {"name": "CARL"}])
    rnd("round_no_gifts_left_stops_sending", [{"name": "ANNA", "after_icon": "failed", "fail": "nogift"}, {"name": "BERT"}, {"name": "CARL"}])
    rnd("round_no_gift_can_be_sent_to_one_friend", [{"name": "ANNA", "after_icon": "failed", "fail": "other"}, {"name": "BERT"}])
    rnd("round_send_is_stuck_for_one", [{"name": "ANNA", "send": "stuck"}, {"name": "BERT"}])
    rnd("round_grey_icons", [{"name": "ANNA", "profile": "grey"}, {"name": "BERT", "profile": "sent"}, {"name": "CARL"}])
    rnd("round_the_time_words", [{"name": "ANNA", "when": "YESTERDAY"}, {"name": "BERT", "when": "2+ DAYS AGO"}, {"name": "CARL", "when": "3 HOURS AGO"}])
    rnd("round_a_long_list", [{"name": n, "arrow": i % 3 == 0, "gift": "text" if i % 4 == 1 else None} for i, n in enumerate(names)])
    rnd("round_a_long_list_that_ends_on_a_page", [{"name": n, "arrow": True} for n in names[:6]])
    rnd("round_a_long_list_open_only", [{"name": n, "arrow": True, "gift": "text" if i in (2, 7) else None} for i, n in enumerate(names)], wanted={"gifts_send": False})
    rnd("round_a_screen_pops_up", [{"name": "ANNA"}, {"name": "BERT"}], popup_at=1)
    rnd("round_a_screen_pops_up_later", [{"name": "ANNA"}, {"name": "BERT"}], popup_at=9)
    rnd("round_a_screen_pops_up_and_stays", [{"name": "ANNA"}, {"name": "BERT"}], popup_at=1, popup_stuck=True)
    rnd("round_a_screen_pops_up_and_stays_later", [{"name": "ANNA"}, {"name": "BERT"}], popup_at=9, popup_stuck=True)
    rnd("round_the_map_never_comes", [{"name": "ANNA"}], map_stuck=True)
    rnd("round_the_start_is_a_popup", [{"name": "ANNA"}], popup_at=0, start="friends")
    rnd("round_the_file_of_another_app", [{"name": "ANNA"}], package="com.nianticlabs.pokemongo.ares",
        files={"gifts_state_ares.json": json.dumps(new_state(sent=["ANNA"]))})
    rnd("round_sixty_looks", [{"name": "F%03d" % i, "arrow": True} for i in range(260)])
    rnd("round_the_friends_have_the_name_of_a_screen_word", [{"name": "SENT"}, {"name": "BERT"}])
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
