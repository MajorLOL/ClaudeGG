#!/usr/bin/env python3
"""Developer check: what would the fight loop do with this recording?

The pictures of a battle recording (the zip of *Record battle* in the web interface, unpacked: frames.csv and
the folder frames/) are shown to the real fight loop of gamebot.py as if they were the live video of the phone,
each one for as long as it was on the screen in the recording, with the real text reader (Tesseract, when it is
installed).  The "phone" is a film: it does not react to what the bot does, and nothing is sent to a real phone.
What the bot logs, where it taps and where it swipes is printed with the time and the number of the picture
in the recording.

    python3 tools/replay_recording.py ~/battle-recording                    # the whole recording
    python3 tools/replay_recording.py ~/battle-recording --first 181 --last 293   # only the fight

What to look for: `the fight has started` at the first picture of the fight and not before, `throwing ...` only
at pictures with a button that is ready (its name in white - the white ring may still be missing), `'Get Ready!'`
before every little game, an answer at every question, `the fight is over` at the result screen.  A film cannot
show whether a tap would have worked: after a throw the pictures go on as they were recorded, so lines like
`the button is still ready - the tap did not count`, `... did not start` and `the question to leave the battle
did not come up` are normal here.  The fast attacks are only counted: in the middle of the screen and on a
charged attack button (where they are tapped while that attack charges, see FIGHT_AIM in gamebot.py).

The team is the one of ~/battle_team.json (or the preset).  Run it with HOME set to an empty folder to leave
the settings and the learned little games of the real bot alone:  HOME=$(mktemp -d) python3 tools/...
"""
import argparse
import csv
import os
import sys
import threading
import time as real_time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


class Clock:
    """The time of the recording: it only moves when the film gives a picture or the loop sleeps."""
    t = 0.0

    @staticmethod
    def monotonic():
        return Clock.t

    @staticmethod
    def time():
        return Clock.t

    @staticmethod
    def sleep(seconds):
        if threading.current_thread() is threading.main_thread():
            Clock.t += seconds
        else:
            real_time.sleep(min(seconds, 0.002))

    @staticmethod
    def strftime(*a):
        return real_time.strftime(*a)


class Film:
    """The recording as a live video (the methods of battle_stream.FrameStream that the fight loop uses)."""
    failed = False

    def __init__(self, folder, rows, pace):
        self.folder, self.rows, self.pace = folder, rows, pace
        self.cache = {}

    def row(self):
        cur = self.rows[0]
        for r in self.rows:
            if int(r["ms"]) / 1000.0 > Clock.t:
                break
            cur = r
        return cur

    def picture(self, size):
        import cv2
        r = self.row()
        key = (r["index"], size)
        if key not in self.cache:
            if len(self.cache) > 6:
                self.cache.clear()
            img = cv2.imread(os.path.join(self.folder, "frames", r["file"]))
            if img is None:
                raise SystemExit(f"cannot read {r['file']}")
            how = cv2.INTER_AREA if size[0] <= img.shape[1] else cv2.INTER_CUBIC
            self.cache[key] = cv2.resize(img, size, interpolation=how)
        return self.cache[key]

    def healthy(self, max_age=2.5):
        return True

    def starting(self):
        return False

    def describe(self):
        return "a recording"

    def close(self):
        pass

    def wait_new(self, seq, timeout=1.0, not_before=0.0):
        Clock.t += 0.1                              # (ten pictures a second, as the live video)
        real_time.sleep(self.pace)                  # (the text reader works in real time: give it some)
        return seq + 1, Clock.t, self.picture((704, 880))

    def say(self, text):
        print(f"{Clock.t:7.1f} s  picture {int(self.row()['index']):3d}  {text}", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folder", help="the unpacked recording: frames.csv and frames/")
    ap.add_argument("--first", type=int, default=None, help="number of the first picture (default: the first)")
    ap.add_argument("--last", type=int, default=None, help="number of the last picture (default: the last)")
    ap.add_argument("--pace", type=float, default=0.03, help="real seconds per picture of the film (default 0.03)")
    args = ap.parse_args()
    with open(os.path.join(args.folder, "frames.csv"), encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f)
                if (args.first is None or int(r["index"]) >= args.first)
                and (args.last is None or int(r["index"]) <= args.last)]
    if not rows:
        raise SystemExit("no pictures in that range")

    import gamebot as G
    import spin_stop as S
    import battle_vision as BV

    def no_phone(*a, **k):
        raise RuntimeError("replay: there is no phone")

    film = Film(args.folder, rows, args.pace)
    Clock.t = int(rows[0]["ms"]) / 1000.0
    end = int(rows[-1]["ms"]) / 1000.0 + 12.0
    fast = [0, 0]                                   # fast attacks: in the middle, on a charged attack button
    aimed = {}                                      # pictures with fast attacks on a button -> which button
    swept = {}

    def tap(x, y, ms=120):
        fx, fy = x / float(S.REF_W), y / float(S.REF_H)
        button = next((i for i, bx in enumerate(BV.BTN_X) if abs(fx - bx) < 0.01 and abs(fy - BV.BTN_Y) < 0.01), None)
        if abs(fx - BV.TAP_FAST[0]) < 0.01 and abs(fy - BV.TAP_FAST[1]) < 0.01:
            fast[0] += 1                            # (the fast attacks: only counted)
        elif button is not None and ms == G.FIGHT_TAP_MS:
            fast[1] += 1                            # (the fast attacks on a button: the pictures are listed)
            aimed.setdefault(int(film.row()["index"]), "LR"[button])
        else:
            film.say(f"TAP at ({fx:.2f}, {fy:.2f})")
        real_time.sleep(0.001)

    def swipes(strokes):
        k = int(film.row()["index"])
        if k not in swept:                          # (the first swipe on every picture is enough to see)
            s = strokes[0]
            film.say(f"SWIPE from ({s[0] / S.REF_W:.2f}, {s[1] / S.REF_H:.2f}) to "
                     f"({s[2] / S.REF_W:.2f}, {s[3] / S.REF_H:.2f}) and more")
        swept[k] = swept.get(k, 0) + len(strokes)
        real_time.sleep(0.004)

    G.time = Clock
    G.log = film.say
    G.save_async = lambda name, img: None
    S.debug_save = lambda *a, **k: None
    S.adb = S.swipe = S.swipe_async = S.back = no_phone
    S.tap, S.swipes = tap, swipes
    S.screenshot = lambda on_grab=None: film.picture((S.REF_W, S.REF_H))
    res = G.fight_battle(stop=lambda: Clock.t > end, stream=film)
    print(f"result: {res['result'] or '-'}" + (f" ({res['why']})" if res["why"] else "")
          + (" - given up" if res.get("gave_up") else "")
          + f"; {fast[0]} fast taps in the middle and {fast[1]} on a button (the film runs faster than the phone: the "
          f"numbers say nothing); swipes on pictures {sorted(swept) or '-'}")
    if aimed:
        print("fast attacks on a button (L / R) on pictures: " + " ".join(f"{k}{v}" for k, v in sorted(aimed.items())))


if __name__ == "__main__":
    main()
