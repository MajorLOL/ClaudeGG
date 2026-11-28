#!/usr/bin/env python3
"""Makes tests/fixtures/lock_golden.json.qz (JSON, packed the way qCompress() of Qt does: the length, then zlib): what spin_stop.py does about the
LOCK SCREEN and the DIMMED GAME - is_dimmed() (the brightest pixels of the picture, the 99.5th percentile of the brightness as numpy takes it, are
below 120), unlock() (the swipe lock screen of the phone: dismiss it, swipe it away like by hand, say when it stays) and unlock_game() (Pokemon GO dims
and locks itself: tap, drag the little lock one of three ways, look again) - the file that the C++ port,
SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoLock.cpp, is tested against.

    python3 tools/make_lock_golden.py            writes the file
    python3 tools/make_lock_golden.py --check    says whether the file is what the code does now (the stories stored in it are played again)

The file is a list of stories: a list of calls, each with the EVENTS that it makes, with the time of a fake clock (it starts at 1000.0 and only moves with
the sleeps).  The pictures are drawn on the canvas by the ops of tools/make_throw_golden.py.  What the code is GIVEN:
    keyguard      does the phone show the lock screen (the answer of keyguard_showing(): the parsing of what `dumpsys window` says is the job of the
                  agent, whose tests have it), or an error of adb
    shot          a screenshot (which of the frames of the story), or an error (the events are those of the other files: shot, shot_error)
  what it DOES (the C++ port has to do the same, in this order):
    keyguard (asked), dismiss (`wm dismiss-keyguard`), tap, swipe, sleep, log, then at the end of every call: result (what it returned: for unlock_game
    the number of the frame of the picture) or raised.
"""
import argparse
import json
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_throw_golden as TG  # noqa: E402  (the ops of the pictures)
from make_start_golden import START, Clock, Rec  # noqa: E402
import spin_stop as S  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "tests", "fixtures", "lock_golden.json.qz")
W, H = S.EXPECTED_SIZE                                           # the canvas
PIXELS = W * H

# the colours of the pictures: [b, g, r]; the brightness of a pixel (the V of HSV) is its biggest number
DARK = [50, 40, 30]                                              # (V 50: a dimmed game)
LIGHT = [255, 255, 255]


def grey(v):
    return ["fill", v, v, v]


def frame(ops):
    return {"pic": ops}


def bright_pixels(base, count, colour=None):
    """A picture of `base` with exactly `count` pixels of `colour` (whole rows from the top, then the start of the next row)."""
    colour = colour or LIGHT
    rows, rest = divmod(count, W)
    ops = [["fill"] + list(base)]
    if rows:
        ops.append(["rect", 0, 0, W, rows, colour])
    if rest:
        ops.append(["rect", 0, rows, rest, 1, colour])
    return ops


# ---------------------------------------------------------------------- the stories are played on the fake phone

def record(spec):
    """Plays one story on the fake phone; returns the list of events."""
    Clock.t = START
    rec = Rec()
    Clock.rec = rec
    frames = spec.get("frames", [])
    pictures = {}
    by_id = {}

    def picture(index):
        if index not in pictures:
            img = TG.make_scene(frames[index]["pic"])
            pictures[index] = img
            by_id[id(img)] = index
        return pictures[index]

    keyguards = list(spec.get("keyguards", []))
    shots = list(spec.get("shots", []))
    saved = {n: getattr(S, n) for n in ("time", "log", "tap", "swipe", "screenshot", "keyguard_showing", "adb")}
    try:
        S.time = Clock
        S.log = lambda text: rec.add("log", text)

        def tap(x, y, ms=120):
            rec.add("tap", x, y)
        S.tap = tap

        def swipe(x1, y1, x2, y2, ms=300):
            rec.add("swipe", x1, y1, x2, y2, ms)
        S.swipe = swipe

        def keyguard_showing():
            answer = keyguards.pop(0)
            if isinstance(answer, dict):
                rec.add("keyguard_error", answer["raise"])
                raise RuntimeError(answer["raise"])
            rec.add("keyguard", answer)
            return answer
        S.keyguard_showing = keyguard_showing

        def screenshot():
            answer = shots.pop(0)
            if isinstance(answer, dict):
                rec.add("shot_error", 0, answer["raise"])
                raise RuntimeError(answer["raise"])
            rec.add("shot", answer, "real")
            return picture(answer)
        S.screenshot = screenshot

        def adb(*args, binary=False):
            assert args == ("shell", "wm", "dismiss-keyguard"), args
            if spec.get("dismiss_error"):
                rec.add("dismiss_error", spec["dismiss_error"])
                raise RuntimeError(spec["dismiss_error"])
            rec.add("dismiss")
            return ""
        S.adb = adb

        for call in spec["calls"]:
            fn = call["fn"]
            rec.add("call", fn)
            try:
                if fn == "is_dimmed":
                    result = bool(S.is_dimmed(picture(call["img"])))
                elif fn == "unlock":
                    result = bool(S.unlock())
                elif fn == "unlock_game":
                    out = S.unlock_game(picture(call["img"])) if "img" in call else S.unlock_game()
                    result = by_id[id(out)]
                else:
                    raise ValueError(fn)
                rec.add("result", result)
            except RuntimeError as e:
                rec.add("raised", str(e))
        assert not keyguards and not shots, "the story gives more than the code asks for: %s %s" % (keyguards, shots)
        return rec.events
    finally:
        for n, v in saved.items():
            setattr(S, n, v)


# ---------------------------------------------------------------------- the stories

def stories():
    out = []

    def story(name, calls, **spec):
        out.append({"id": name, "spec": dict(spec, calls=calls)})

    def dimmed(name, ops):
        if isinstance(ops[0], str):                                  # (one op instead of a list of them)
            ops = [ops]
        story(name, [{"fn": "is_dimmed", "img": 0}], frames=[frame(ops)])

    # --- is_dimmed(): the 99.5th percentile of the brightness is below 120
    dimmed("plain_picture", [["fill", 70, 90, 60]])                     # (the picture of most stories: V 90)
    dimmed("black", grey(0))
    dimmed("white", grey(255))
    dimmed("grey_119", grey(119))
    dimmed("grey_120", grey(120))
    dimmed("grey_121", grey(121))
    dimmed("brightest_channel_counts_blue", ["fill", 119, 10, 10])
    dimmed("brightest_channel_counts_green", ["fill", 10, 119, 10])
    dimmed("brightest_channel_counts_red", ["fill", 10, 10, 119])
    dimmed("blue_120", ["fill", 120, 10, 10])
    dimmed("green_120", ["fill", 10, 120, 10])
    dimmed("red_120", ["fill", 10, 10, 120])
    dimmed("noise_around_100", [["fill", 100, 100, 100], ["noise", 7, 15]])
    dimmed("noise_around_120", [["fill", 120, 120, 120], ["noise", 3, 6]])
    # the share of bright pixels: N = 1768 x 2208 pixels; the top 0.5 % of the pixels decide (the percentile lies between the pixels number
    # 3884224 and 3884225 of the sorted ones, a bit more than a quarter of the way: 19519 pixels are enough to touch it from above, 19520 to fill it)
    for count in (0, 1000, 19000, 19448, 19518, 19519, 19520, 19521, 21216, 100000, PIXELS // 2, PIXELS - 1):
        dimmed("bright_pixels_%d_on_dark" % count, bright_pixels(DARK, count))
    for count in (19518, 19519, 19520):
        dimmed("bright_pixels_%d_on_100" % count, bright_pixels([100, 100, 100], count))
        dimmed("bright_pixels_%d_on_119" % count, bright_pixels([119, 119, 119], count))
        dimmed("bright_pixels_%d_on_0" % count, bright_pixels([0, 0, 0], count))
        dimmed("grey_pixels_%d_on_dark" % count, bright_pixels(DARK, count, [130, 130, 130]))
        dimmed("grey_pixels_%d_on_dark_119" % count, bright_pixels(DARK, count, [119, 119, 119]))
        dimmed("grey_pixels_%d_on_dark_240" % count, bright_pixels(DARK, count, [240, 240, 240]))
    dimmed("a_bright_button_on_a_dim_game", [grey(60), ["rect", 500, 1800, 800, 100, [255, 255, 255]]])        # (2 %: more than the brightest 0.5 %, so not dimmed)
    dimmed("a_bright_banner_on_a_dim_game", [grey(60), ["rect", 0, 0, 1768, 100, [255, 255, 255]]])             # (4.5 %: not dimmed)
    dimmed("a_dark_night_scene_with_white_buttons", [grey(30), ["rect", 100, 100, 300, 200, [255, 255, 255]], ["rect", 700, 900, 400, 100, [250, 250, 250]]])
    dimmed("a_dark_night_scene_with_lots_of_white", [grey(30), ["rect", 0, 0, 1768, 400, [255, 255, 255]]])
    # other sizes of pictures (the percentile is taken of however many pixels there are): the part between the two pixels that is a half or more
    for width, height in ((101, 1), (100, 1), (1, 1), (2, 1), (3, 1), (201, 1), (40, 25), (1000, 2200), (1768, 1), (7, 13), (51, 2)):
        dimmed("small_%dx%d_dark" % (width, height), [grey(50), ["size", width, height]])
        dimmed("small_%dx%d_bright" % (width, height), [grey(200), ["size", width, height]])
        dimmed("small_%dx%d_a_bright_end" % (width, height), [grey(50), ["rect", W - 40, 0, 40, H, [255, 255, 255]], ["size", width, height]])
        dimmed("small_%dx%d_a_bright_start" % (width, height), [grey(50), ["rect", 0, 0, 40, H, [255, 255, 255]], ["size", width, height]])
        dimmed("small_%dx%d_a_third_bright" % (width, height), [grey(50), ["rect", 0, 0, W // 3, H, [255, 255, 255]], ["size", width, height]])
        dimmed("small_%dx%d_a_third_grey_130" % (width, height), [grey(50), ["rect", 0, 0, W // 3, H, [130, 130, 130]], ["size", width, height]])
    for width in (101, 201, 21, 11):
        for bright in (1, 2, 3):
            dimmed("row_%d_ends_with_%d_bright" % (width, bright), [grey(40), ["rect", W - bright * (W // width), 0, bright * (W // width), H, [255, 255, 255]],
                                                                    ["size", width, 1]])
    # the line between the two pixels that the percentile lies between, when the brightest one is just below or above 120 (a picture of 101 pixels: half way
    # between the pixels 99 and 100 of the sorted ones; of 21: nine tenths of the way; of 11: nineteen twentieths) - one pixel of `top` on a grey of `base`
    for width in (101, 21, 11):
        for top, base in ((119, 100), (119, 0), (121, 100), (121, 119), (125, 110), (130, 60), (140, 100), (118, 60)):
            dimmed("row_%d_one_pixel_%d_on_%d" % (width, top, base),
                   [grey(base), ["rect", W - 2 * (W // width), 0, 2 * (W // width), H, [top, top, top]], ["size", width, 1]])

    # --- unlock(): the lock screen of the phone
    story("unlock_no_lock", [{"fn": "unlock"}], keyguards=[False])
    story("unlock_dismissed", [{"fn": "unlock"}], keyguards=[True, False, False])
    story("unlock_dismissed_but_back", [{"fn": "unlock"}], keyguards=[True, False, True])
    story("unlock_swiped", [{"fn": "unlock"}], keyguards=[True, True, False])
    story("unlock_fails", [{"fn": "unlock"}], keyguards=[True, True, True])
    story("unlock_twice", [{"fn": "unlock"}, {"fn": "unlock"}, {"fn": "unlock"}, {"fn": "unlock"}],
          keyguards=[False, True, False, False, True, True, True, True, True, False])
    story("unlock_cannot_ask", [{"fn": "unlock"}], keyguards=[{"raise": "adb offline"}])
    story("unlock_cannot_ask_after_the_dismiss", [{"fn": "unlock"}], keyguards=[True, {"raise": "adb offline"}])
    story("unlock_cannot_ask_after_the_swipe", [{"fn": "unlock"}], keyguards=[True, True, {"raise": "device not found"}])
    story("unlock_cannot_dismiss", [{"fn": "unlock"}], keyguards=[True], dismiss_error="wm: not allowed")

    # --- unlock_game(): the game dims and locks itself
    dim, bright, other, third = frame([["fill", 60, 60, 60]]), frame([["fill", 200, 200, 200]]), frame([["fill", 200, 100, 50]]), frame([["fill", 20, 20, 20]])
    frames = [dim, bright, other, third]
    story("game_is_not_dimmed", [{"fn": "unlock_game", "img": 1}], frames=frames)
    story("game_is_not_dimmed_at_120", [{"fn": "unlock_game", "img": 4}], frames=frames + [frame([grey(120)])])
    story("game_is_dimmed_at_119", [{"fn": "unlock_game", "img": 4}], frames=frames + [frame([grey(119)])], shots=[1])
    story("game_woken_by_the_first_swipe", [{"fn": "unlock_game", "img": 0}], frames=frames, shots=[1])
    story("game_woken_by_the_second_swipe", [{"fn": "unlock_game", "img": 0}], frames=frames, shots=[0, 2])
    story("game_woken_by_the_third_swipe", [{"fn": "unlock_game", "img": 0}], frames=frames, shots=[0, 3, 1])
    story("game_stays_dimmed", [{"fn": "unlock_game", "img": 0}], frames=frames, shots=[0, 3, 0])
    story("game_stays_dimmed_and_the_last_is_another", [{"fn": "unlock_game", "img": 0}], frames=frames, shots=[3, 0, 3])
    story("game_no_picture_given", [{"fn": "unlock_game"}], frames=frames, shots=[1])
    story("game_no_picture_given_dimmed", [{"fn": "unlock_game"}], frames=frames, shots=[0, 1])
    story("game_no_picture_given_dimmed_for_good", [{"fn": "unlock_game"}], frames=frames, shots=[0, 0, 0, 3])
    story("game_no_picture_given_cannot_look", [{"fn": "unlock_game"}], frames=frames, shots=[{"raise": "screencap failed"}])
    story("game_the_look_after_a_swipe_fails", [{"fn": "unlock_game", "img": 0}], frames=frames, shots=[{"raise": "no PNG received"}])
    story("game_the_look_after_the_second_swipe_fails", [{"fn": "unlock_game", "img": 0}], frames=frames, shots=[0, {"raise": "no PNG received"}])
    story("game_the_look_after_the_third_swipe_fails", [{"fn": "unlock_game", "img": 0}], frames=frames, shots=[0, 3, {"raise": "no PNG received"}])
    story("game_dimmed_twice_in_a_row", [{"fn": "unlock_game", "img": 0}, {"fn": "unlock_game", "img": 3}], frames=frames, shots=[1, 2])
    story("game_a_dark_night_scene_is_not_dimmed", [{"fn": "unlock_game", "img": 0}], frames=[frame([grey(30), ["rect", 0, 0, 1768, 400, [255, 255, 255]]])])
    story("game_woken_picture_is_a_night_scene", [{"fn": "unlock_game", "img": 0}], frames=[dim, frame([grey(30), ["rect", 0, 0, 1768, 400, [255, 255, 255]]])], shots=[1])
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
