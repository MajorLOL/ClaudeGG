#!/usr/bin/env python3
"""Makes tests/fixtures/rocketfight_golden.json.qz (JSON, packed the way qCompress() of Qt does: the length, then zlib): fights against Team GO Rocket played
by rocket_fight() of gamebot.py, the file that the C++ port, SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoRocketFight.cpp, is tested against.

    python3 tools/make_rocketfight_golden.py            writes the file
    python3 tools/make_rocketfight_golden.py --check    says whether the file is what the code does now (the stories stored in it are played again)

Like the fights of tools/make_loop_golden.py these are played on the fake phone of tests/test_fight_loop.py: it shows pictures of real fights (tests/fixtures)
and reacts to what the bot does, the thread that taps the fast attacks is a fake that taps once for every picture the phone gives, the clock only moves
with the pictures and the sleeps.  What comes out is the list of EVENTS of one fight, in order, every one with the time of the fake clock (it starts at 1000.0):
  what the code is GIVEN:  wait_new (a picture of the live video), screenshot, ocr (the text reader read lines: the name box of ours), stop (what the
                           'stop' of the person said: only in a story that has one)
  what it DOES:            busy (no screen check while the fight is on: 300, then 0), aim, go, pause, sweep, tap (the shield), swipe (the little game), log,
                           and at the end result (the seconds it took) or raised.
The names of the pictures are folder/file, with "+nohud" for a picture of the little game with the top of the screen (the name boxes) painted black:
the screen of a charged attack without the HUD.  The state of every picture (fight, prompt, other) is what the readers say of it, the C++ port gets
no answer for that: it has to read the same from the same picture.
"""
import argparse
import json
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_loop_golden as L  # noqa: E402  (the fake phone, its clock, the fake tapper and the video stream)

T, G, S, BV, BF, BE, cv2 = L.T, L.G, L.S, L.BV, L.BF, L.BE, L.cv2
OUT = os.path.join(L.ROOT, "tests", "fixtures", "rocketfight_golden.json.qz")
START = L.START
NOHUD = {"ghost_nohud": "minigame/ghost", "flying_nohud": "minigame/flying", "water_nohud": "minigame/water", "electric_nohud": "minigame/electric",
         "flying_two_nohud": "fight/day2_their_attack"}          # (the last one: two icons of the type flying, not three)


class Phone(T.Phone):
    """The fake phone of the loop tests, with the name of ours that the text reader gives (names: one for each reading of the name box, the last one
    stays) and the pictures of the little games without the HUD."""

    def __init__(self, video, script, names):
        super().__init__(video, "", script, None, True, None)
        self.rocket_names = list(names or [])
        self.name_reads = 0

    # (the clock goes on in steps of an eighth of a second, which add up exactly: the limits of the code are met to the hair)
    def wait_new(self, seq, timeout=1.0, not_before=0.0):
        T.Clock.t += 0.125
        self.tick()
        if self.scene == "stall":                                # ("stall", seconds) in a script: the video stands still, the next picture comes later
            T.Clock.t += self.ends_with()
            self.advance()
        self.frames += 1
        return seq + 1, T.Clock.t, self.picture(self.scene)

    def screenshot(self, on_grab=None):
        if not self.video:
            T.Clock.t += 1.25                                    # (a screenshot takes its time)
            self.tick()
            self.frames += 1
        return self.picture(self.scene, (S.REF_W, S.REF_H))

    def picture(self, name, size=(704, 880)):
        name = name.split("#")[0]
        if name not in NOHUD:
            return super().picture(name, size)
        key = (name, size)
        if key not in self.pictures:
            img = cv2.resize(cv2.imread(os.path.join(T.FIX, NOHUD[name] + ".jpg")), size, interpolation=cv2.INTER_AREA)
            img[:int(0.2 * size[1])] = 0                         # (the name boxes are gone)
            self.pictures[key] = img
        return self.pictures[key]

    def ocr(self, img, y0=0, y1=None, scale=1.0):
        if img.shape[0] < 400:                                   # the name box of ours
            n = self.name_reads
            self.name_reads += 1
            if not self.rocket_names:
                return []
            name = self.rocket_names[min(n, len(self.rocket_names) - 1)]
            return T.name_line(name, 1500, mine=True) if name else []
        return []


class Recorder(L.Recorder):
    def picture(self):
        name = self.phone.scene.split("#")[0]
        if name in NOHUD:
            return NOHUD[name] + "+nohud"
        return super().picture()


def record(spec):
    """Plays one fight on the fake phone; returns the list of events."""
    T.Clock.t = START
    phone = Phone(spec["video"], spec["script"], spec["names"])
    rec = Recorder(phone)
    L.RClock.rec = rec
    names = ("time", "log", "ocr_lines", "MINIGAME_FILE", "FastTapper", "_fight_stream")
    names_s = ("tap", "swipes", "screenshot", "busy")
    saved = {n: getattr(G, n) for n in names}
    saved_s = {n: getattr(S, n) for n in names_s}
    import tempfile
    folder = tempfile.mkdtemp()
    try:
        G.time = L.RClock
        G.MINIGAME_FILE = os.path.join(folder, "minigame.json")
        with open(G.MINIGAME_FILE, "w", encoding="utf-8") as handle:
            json.dump(spec["minigames"], handle)
        G.FastTapper = lambda xy, ms=G.FIGHT_TAP_MS: L.FakeTapper(rec, xy, ms)
        G.log = lambda text: (rec.add("log", text), phone.log(text))[0]

        def ocr_lines(img, y0=0, y1=None, scale=1.0):
            lines = phone.ocr(img, y0, y1, scale)
            rec.add("ocr", img.shape[0], img.shape[1], y0, y1, scale, L.mean(img), L.lines_of(lines))
            return lines
        G.ocr_lines = ocr_lines

        def tap(x, y, ms=120):
            rec.add("tap", x, y, ms, rec.who)
            phone.tap(x, y, ms)

        def swipes(strokes):
            rec.add("swipe", [list(s) for s in strokes])
            phone.swipe(strokes)

        def screenshot(on_grab=None):
            img = phone.screenshot(on_grab)
            rec.add("screenshot", rec.picture())
            rec.tapper.poll()
            return img
        S.tap, S.swipes, S.screenshot = tap, swipes, screenshot
        S.busy = lambda seconds: rec.add("busy", seconds)
        G._fight_stream = (lambda: L.Stream(rec)) if spec["video"] else (lambda: None)

        stop = None
        if "stop_at" in spec:
            asked = {"n": 0}

            def stop():
                n = asked["n"]
                asked["n"] += 1
                answer = n >= spec["stop_at"]
                rec.add("stop", answer)
                return answer
        try:
            secs = G.rocket_fight(stop)
            rec.add("result", secs)
        except Exception as e:  # noqa: BLE001
            rec.add("raised", str(e))
        return rec.events
    finally:
        for n, v in saved.items():
            setattr(G, n, v)
        for n, v in saved_s.items():
            setattr(S, n, v)


# ---------------------------------------------------------------------- the stories

def stories():
    out = []

    def story(name, script, names=None, video=True, minigames=None, **spec):
        spec.update(fn="rocket_fight", video=video, script=script, names=list(names or []), minigames=minigames or {},
                    give_up=False, aim=False, league="", seen=[])
        out.append({"id": name, "spec": spec})

    fight = [("versus", 0.5), ("day_start", 2.0), ("day_dim", 8.0), ("flying_nohud", 6.0), ("day_dim#after", 3.0), ("day_shield", "shield"),
             ("day_dim#more", 2.0), ("day_result", 30.0)]
    story("the_whole_fight", fight, ["Noctowl"])
    story("the_whole_fight_with_screenshots", fight, ["Noctowl"], video=False)
    story("the_whole_fight_with_screenshots_without_names", [("versus", 0.5), ("day_start", 3.0), ("electric_nohud", 6.0), ("day_dim", 2.0), ("day_result", 30.0)], video=False)
    game = lambda picture: [("versus", 0.5), ("day_start", 1.0), ("day_dim", 2.0), (picture, 6.0), ("day_dim#after", 1.0), ("day_faint", 12.0)]  # noqa: E731
    story("without_names_the_little_game_of_the_one_type_that_comes_up", game("electric_nohud"))
    story("without_names_the_little_game_on_a_picture_of_a_real_fight", game("day_flash"))
    story("ours_is_known_and_the_icons_of_two_types_come_up_ghost", game("ghost_nohud"), ["Noctowl"])
    story("ours_is_known_and_the_icons_of_two_types_come_up_flying", game("flying_nohud"), ["Noctowl"])
    story("ours_is_known_and_the_icons_of_two_types_come_up_water", game("water_nohud"), ["Lanturn"])
    story("ours_is_known_and_the_icons_are_of_another_type", game("flying_nohud"), ["Lanturn"])
    story("ours_is_not_known_by_the_data", game("electric_nohud"), ["Xyzzy"])
    story("ours_is_known_by_a_damaged_name", game("flying_nohud"), ["Noctowi"])
    story("ours_has_a_name_of_two_words", game("ghost_nohud"), ["Mr. Mime"])
    #  --- the first forty seconds: no fight came
    story("no_fight_comes", [("versus", 45.0), ("day_dim", 2.0)])
    story("the_fight_starts_a_picture_before_forty_seconds", [("versus", 39.875), ("day_dim", 0.5), ("day_faint", 12.0)])
    story("the_fight_starts_a_picture_after_exactly_forty_seconds", [("versus", 40.0), ("day_dim", 0.5), ("day_faint", 12.0)])
    story("the_fight_starts_a_picture_too_late", [("versus", 40.125), ("day_dim", 0.5), ("day_faint", 12.0)])
    story("no_fight_comes_with_screenshots", [("versus", 45.0), ("day_dim", 2.0)], video=False)
    #  --- the fight is over: the HUD is gone
    story("the_hud_is_gone_for_exactly_ten_seconds", [("versus", 0.5), ("day_start", 1.0), ("day_faint", 20.0)])
    story("the_hud_is_gone_but_a_little_game_began_less_than_ten_seconds_ago", [("versus", 0.5), ("day_start", 1.0), ("electric_nohud", 4.0), ("day_faint", 30.0)])
    story("the_hud_comes_back_and_goes_again", [("versus", 0.5), ("day_start", 1.0), ("day_faint", 9.5), ("day_dim", 1.0), ("day_faint#2", 20.0)])
    story("the_hud_is_back_just_before_ten_seconds", [("versus", 0.5), ("day_start", 1.0), ("day_faint", 9.75), ("day_dim", 1.0), ("day_faint#2", 20.0)])
    story("the_fight_goes_on_for_300_seconds", [("versus", 0.5), ("day_start", 1.0), ("stall", 289.0), ("day_dim", 400.0)], ["Noctowl"])
    #  --- the little games in a fight
    story("a_second_little_game_comes_up_exactly_eight_seconds_after_the_first_began",
          [("versus", 0.5), ("day_start", 1.0), ("electric_nohud", 1.0), ("day_faint", 6.75), ("electric_nohud#2", 2.0), ("day_faint#2", 14.0)])
    story("a_second_little_game_comes_up_too_soon",
          [("versus", 0.5), ("day_start", 1.0), ("electric_nohud", 1.0), ("day_faint", 5.0), ("electric_nohud#2", 1.0), ("day_faint#2", 14.0)])
    story("the_icons_do_not_stop_the_game_goes_on_until_it_is_over", [("versus", 0.5), ("day_start", 1.0), ("electric_nohud", 20.0), ("day_faint", 14.0)])
    story("the_hud_comes_back_while_the_little_game_goes_on", [("versus", 0.5), ("day_start", 1.0), ("electric_nohud", 2.0), ("day_dim", 14.0), ("day_faint", 14.0)])
    story("a_shield_question_comes_while_the_little_game_goes_on",
          [("versus", 0.5), ("day_start", 1.0), ("electric_nohud", 2.0), ("shield_question", 3.0), ("day_faint", 14.0)])
    story("the_little_game_needs_three_icons", [("versus", 0.5), ("day_start", 1.0), ("day2_ready_new", 3.0), ("day_faint", 14.0)])
    story("two_icons_of_the_type_are_no_little_game", [("versus", 0.5), ("day_start", 1.0), ("flying_two_nohud", 3.0), ("day_faint", 14.0)], ["Noctowl"])
    #  --- the shield
    story("a_shield_question_that_stays_for_thirteen_seconds", [("versus", 0.5), ("day_start", 1.0), ("shield_question", 13.0), ("day_result", 12.0)])
    story("a_shield_question_is_answered", [("versus", 0.5), ("day_start", 1.0), ("shield_question", "shield"), ("day_dim", 1.0), ("day_result", 12.0)])
    story("a_prompt_that_is_no_shield_question", [("versus", 0.5), ("day_start", 1.0), ("day2_no_shields", 3.0), ("day_dim", 1.0), ("day_result", 12.0)])
    story("the_question_to_switch", [("versus", 0.5), ("day_start", 1.0), ("day_switch", 3.0), ("day_dim", 1.0), ("day_result", 12.0)])
    #  --- the name of ours
    story("ours_is_read_again_every_six_seconds", [("versus", 0.5), ("day_dim", 27.0), ("day_result", 12.0)], ["Noctowl", "Noctowl", "Lanturn", "", "Lanturn", "Lanturn"])
    #  --- the person stops the bot
    quick = [("versus", 0.5), ("day_start", 1.0), ("electric_nohud", 2.0), ("day_dim", 1.0), ("day_faint", 12.0)]
    story("the_person_stops_the_bot_at_once", quick, stop_at=0)
    story("the_person_stops_the_bot_after_the_first_picture", quick, stop_at=1)
    story("the_person_stops_the_bot_in_the_fight", quick, stop_at=7)
    story("the_person_stops_the_bot_in_the_little_game", quick, stop_at=26)
    story("the_person_does_not_stop_the_bot", quick, stop_at=100000)
    return out
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
