#!/usr/bin/env python3
"""Makes tests/fixtures/rocket_golden.json.qz (JSON, packed the way qCompress() of Qt does: the length, then zlib): what gamebot.py does at a PokéStop
of Team GO Rocket between the first speech bubble and the map (or the Shadow Pokémon to catch) - rocket_battle(): the speech bubbles, BATTLE, 'Use your
Rocket Radar?', 'Recommended Battle Party' (a slot without a Pokémon is filled from the list of Pokémon: the first one, DONE), USE THIS PARTY, the fight
(which is played by rocket_fight(): a story of its own, see make_rocketfight_golden.py), the speech bubble and SUMMARY after it, and the Shadow Pokémon -
the file that the C++ port, SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoRocket.cpp, is tested against.

    python3 tools/make_rocket_golden.py            writes the file
    python3 tools/make_rocket_golden.py --check    says whether the file is what the code does now (the stories stored in it are played again)

The file is a list of stories: a list of calls, each with the EVENTS that it makes, with the time of a fake clock (it starts at 1000.0 and only moves
with the sleeps).  The stories are played on a pretend phone ('sim') that has the screens of the walk - the speech bubble, the screen with BATTLE, the
radar question, the party with its slots (the words CP2699 ... where there is a Pokémon), the list of Pokémon, the fight, what is said after it, SUMMARY,
the catch screen and the map - and changes its screen with every touch.  The pictures are drawn on the canvas by the ops of tools/make_throw_golden.py;
the check for the map is the real one, and so is the reading of the party.  What the code is GIVEN:
    shot          a screenshot (which of the frames of the story)
    ocr           the text reader read the lines (with the places of the words) of a picture
    class         what the screen classifier said of a screen
    fight_state   what the fight reader said of the small picture ('fight', 'prompt', 'other': battle_fight.state(battle_vision.features())), with the
                  height, the width and the mean of that small picture (704 wide)
    stop          what the 'stop' of the person said (only in a story that has one)
  what it DOES (the C++ port has to do the same, in this order):
    tap, sleep, log, save (a picture that is kept), fight (rocket_fight() was called: the story gives what it returns and where the phone is after it),
    then at the end of every call: result (what it returned) or raised.
"""
import argparse
import json
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_catch_golden as CG  # noqa: E402  (the pictures and the map)
import make_gifts_golden as GG  # noqa: E402  (the helpers of the pictures)
from make_start_golden import START, Clock, Rec, mean  # noqa: E402
import battle_fight as BF  # noqa: E402
import battle_vision as BV  # noqa: E402
import gamebot as G  # noqa: E402
import spin_stop as S  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "tests", "fixtures", "rocket_golden.json.qz")
PLAIN, frame, line, marker, jsonable = GG.PLAIN, GG.frame, GG.line, GG.marker, GG.jsonable
World = GG.World
W, H = 1768, 2208
SLOT_X = [int(x * W) for x in (0.33, 0.51, 0.69)]            # (where the three slots of the party are, in the walk of the port)
CP_X = [590, 900, 1220]                                        # (where the words CPnnnn of the three slots stand: 0.334, 0.509, 0.690 of the width)
USE_Y = 1720
CP_Y = 1560
BATTLE_Y = 1960


# ---------------------------------------------------------------------- the pretend phone

class Sim:
    """A phone at a PokéStop of Team GO Rocket.  p: start (the screen the phone is on: speech, battle, radar, party, list, fight, lost, summary, catch,
    map), speech (how many taps the speech bubbles at the start need), bubbles (the same after the fight), radar (yes: the question has YES; noword:
    it has none; skip: BATTLE leads to the party at once), radar_dead (how many taps the question ignores), slots (the slots that hold a Pokémon: the
    words CPnnnn stand over them), cp (how a CP is written: 'CP%d', '%d', 'CP%d' with other numbers: cp_numbers), cp_at_use (the CP words stand on the line of USE THIS PARTY), cp_below (the CP words stand under
    the line USE THIS PARTY), use (the line USE THIS PARTY is there), recommended (the words 'Recommended Battle Party' are there), list_done (the list has a
    word DONE), battle_dead (taps that BATTLE ignores), fight_state (what the fight reader says of the fight screen: fight, prompt), fight_secs (what the
    fight returned), after (the screen the fight leaves: lost, summary, catch, map, battle), after_class (what the classifier says of the catch
    screen), class_all (what the classifier says of every other screen), summary_dead (taps that SUMMARY ignores), word_battle (BATTLE is one of
    the words of a longer line), battle_y (where the word BATTLE is), radar_to (what a tap on the radar question leads to: party, map), cp_dx and
    cp_y_step (the words CPnnnn are shifted to the right, and by slot further down), list_fills (DONE puts the third Pokémon into the party), use_with_empty
    (USE THIS PARTY is taken with an empty slot), scale (the pictures are smaller: 0.5 is 884 x 1104; the places of the words are scaled with them)."""

    def __init__(self, spec, world):
        self.p = spec["sim"]
        self.world = world
        self.screen = self.p.get("start", "speech")
        self.count = 0
        self.picked = False
        self.fought = False
        self.keys = {}
        self.filled = list(self.p.get("slots", [0, 1]))
        self.dead = 0

    def state(self):
        return self.p.get("fight_state", "fight") if self.screen == "fight" else "other"

    def key(self):
        s = self.screen
        if s in ("party", "list"):
            return (s, tuple(self.filled), self.picked)
        return (s, self.count if s in ("speech", "lost") else 0)

    def frame(self):
        key = self.key()
        if key not in self.keys:
            self.keys[key] = len(self.world.frames)
            self.world.frames.append(self.build(key, len(self.keys)))
        return self.keys[key]

    def klass(self):
        if self.screen == "catch":
            return self.p.get("after_class", ["encounterScreen", 0.9])
        return self.p.get("class_all", ["onbekend", 0.0])

    def build(self, key, n):
        p = self.p
        s = key[0]
        sc = p.get("scale", 1.0)
        line = lambda text, x, y: GG.line(text, int(x * sc), int(y * sc))          # noqa: E731
        small = [["size", int(W * sc), int(H * sc)]] if sc != 1.0 else []
        lines = []
        if s == "map":
            return frame(CG.map_screen()["pic"] + [marker(n)] + small, lines=[], is_map=True, state="other")
        if s == "speech":
            lines = [line("Cliff's my name. Battling's my game.", 400, 1900)]
        elif s == "battle":
            lines = [line("Leader Cliff", 300, 1300)]
            by = p.get("battle_y", BATTLE_Y)
            lines.append(line("BATTLE", 884, by) if not p.get("word_battle") else line("BATTLE NOW OR NEVER", 884, by))
        elif s == "radar":
            lines = [line("Use your Rocket Radar?", 500, 800)]
            if p.get("radar", "yes") == "yes":
                lines += [line("YES", 884, 1050), line("NO", 884, 1200)]
            else:
                lines += [line("NO", 884, 1200)]
        elif s == "party":
            lines = [line("CHOOSE YOUR PARTY", 600, 1350)]
            if p.get("recommended", True):
                lines.append(line("Recommended Battle Party", 500, 1450))
            cp_y = USE_Y if p.get("cp_at_use") else (CP_Y if not p.get("cp_below") else USE_Y + 100)
            numbers = p.get("cp_numbers", [2699, 2626, 2888])
            for i in self.filled:
                lines.append(line(p.get("cp", "CP%d") % numbers[i], CP_X[i] + p.get("cp_dx", 0), cp_y + i * p.get("cp_y_step", 0)))
            if p.get("use", True):
                lines.append(line("USE THIS PARTY", 750, USE_Y))
        elif s == "list":
            lines = [line("TAGS POKEMON", 600, 150), line("CP418 CP1054 CP45", 400, 900), line("CANCEL", 400, 2000)]
            lines.append(line("DONE" if p.get("list_done", True) else "UNDONE", 1200, 2000))
        elif s == "lost":
            lines = [line("Leader Cliff: What? But I can't lose!", 400, 1900)]
        elif s == "summary":
            lines = [line("SUMMARY", 884, 300), line("TOTAL +7", 600, 1700)]
        return frame([PLAIN, marker(n)] + small, lines=lines, state=self.state())

    def tap(self, x, y):
        p = self.p
        s = self.screen

        def near(px, py, rx=120, ry=100):
            return abs(x - px) < rx and abs(y - py) < ry
        if s == "speech":
            self.count += 1
            if self.count >= p.get("speech", 1):
                self.screen, self.count = "battle", 0
        elif s == "battle":
            if near(int(0.33 * W), p.get("battle_y", BATTLE_Y), 150, 80):
                if self.dead < p.get("battle_dead", 0):
                    self.dead += 1
                    return
                self.dead = 0
                self.screen = "radar" if p.get("radar", "yes") != "skip" else "party"
        elif s == "radar":
            target = (884, 1050) if p.get("radar", "yes") == "yes" else (884, int(0.42 * H))
            if near(*target, rx=100, ry=60):
                if self.dead < p.get("radar_dead", 0):
                    self.dead += 1
                    return
                self.dead = 0
                self.screen = p.get("radar_to", "party")
        elif s == "party":
            empty = [i for i in range(3) if i not in self.filled]
            if p.get("use", True) and near(750, USE_Y, 150, 60):
                if not empty or p.get("use_with_empty"):
                    self.screen = "fight"
                    self.fought = True
            elif not p.get("use", True) and near(884, int(0.70 * H), 150, 60):
                self.screen = "fight"
                self.fought = True
            elif empty and any(near(SLOT_X[i], CP_Y + int(0.05 * H) + 20, 150, 100) for i in empty):
                self.screen = "list"
        elif s == "list":
            if near(int(0.18 * W), int(0.70 * H), 100, 80):
                self.picked = True
            elif self.picked and near(1200, 2000, 150, 80) and p.get("list_done", True):
                if p.get("list_fills", True):
                    self.filled = [0, 1, 2]
                self.screen = "party"
        elif s == "lost":
            self.count += 1
            if self.count >= p.get("bubbles", 1):
                self.screen, self.count = "summary", 0
        elif s == "summary":
            if self.dead < p.get("summary_dead", 0):
                self.dead += 1
                return
            self.dead = 0
            self.screen = "catch" if p.get("end", "catch") == "catch" else "map"
        elif s == "catch":
            self.screen = "map"

    def after_fight(self):
        self.screen, self.count = self.p.get("after", "lost"), 0


# ---------------------------------------------------------------------- the fake phone

def record(spec):
    """Plays one story on the fake phone; returns the list of events."""
    Clock.t = START
    rec = Rec()
    Clock.rec = rec
    world = World(spec)
    sim = Sim(spec, world)
    current = {"frame": 0}
    saved_g = {n: getattr(G, n) for n in ("time", "log", "save_async", "ocr_lines", "screen_class", "rocket_fight") if hasattr(G, n)}
    saved_s = {n: getattr(S, n) for n in ("time", "log", "tap", "screenshot", "on_map")}
    saved_bf, saved_bv = BF.state, BV.features
    try:
        G.time = S.time = Clock
        G.log = S.log = lambda text: rec.add("log", text)
        G.save_async = lambda name, img: rec.add("save", name, world.index_of(img))
        if spec.get("fake_map"):                                  # (the real check for the map reads a picture of the size of the canvas)
            S.on_map = lambda img: bool(world.frame(img).get("is_map"))

        def tap(x, y, ms=120):
            rec.add("tap", x, y)
            sim.tap(x, y)
        S.tap = tap

        def take(on_grab=None):
            index = sim.frame()
            current["frame"] = index
            world.shots += 1
            rec.add("shot", index, "real", False)
            return world.picture(index)
        S.screenshot = take

        def ocr_lines(img, y0=0, y1=None, scale=1.0):
            lines = [ln for ln in world.frame(img).get("lines", []) if ln[2] >= y0 and (y1 is None or ln[2] < y1)]
            rec.add("ocr", img.shape[0], img.shape[1], y0, y1, scale, mean(img), lines)
            return lines
        G.ocr_lines = ocr_lines

        def screen_class(img):
            answer = sim.klass()
            rec.add("class", answer[0], answer[1])
            return answer[0], answer[1]
        G.screen_class = screen_class

        BV.features = lambda small: (small.shape[0], small.shape[1], mean(small))        # (the reader is given this: what the port gives is held to it)

        def fight_state(feat):
            answer = sim.state()
            rec.add("fight_state", answer, feat[0], feat[1], feat[2])
            return answer
        BF.state = fight_state

        def fight(stop=None):
            secs = spec.get("fight_secs", 90)
            rec.add("fight", secs)
            sim.after_fight()
            return secs
        G.rocket_fight = fight

        asked = {"n": 0}

        def stop():
            n = asked["n"]
            asked["n"] += 1
            answer = n >= spec["stop_at"]
            rec.add("stop", answer)
            return answer

        for call in spec["calls"]:
            rec.add("call", call["fn"], None, None)
            try:
                result = G.rocket_battle(stop if "stop_at" in spec else None)
                rec.add("result", jsonable(result))
            except Exception as e:  # noqa: BLE001
                rec.add("raised", str(e))
        return rec.events
    finally:
        for n, v in saved_g.items():
            setattr(G, n, v)
        for n, v in saved_s.items():
            setattr(S, n, v)
        BF.state, BV.features = saved_bf, saved_bv


# ---------------------------------------------------------------------- the stories

def stories():
    out = []

    def sim(name, p, **spec):
        spec.update(calls=[{"fn": "rocket_battle"}], frames=[], sim=p)
        if p.get("scale", 1.0) != 1.0:
            spec["fake_map"] = True                                  # (the real check for the map reads a picture of the size of the canvas)
        out.append({"id": name, "spec": spec})

    sim("the_whole_walk", {})
    sim("the_whole_walk_the_phone_ends_on_the_map", {"end": "map"})
    sim("the_walk_starts_on_the_map", {"start": "map"})
    sim("the_walk_starts_at_the_battle_screen", {"start": "battle"})
    sim("two_speech_bubbles_first", {"speech": 2})
    sim("five_speech_bubbles_first", {"speech": 5})
    sim("twenty_five_screens_that_are_not_known", {"speech": 24})
    sim("twenty_six_screens_that_are_not_known", {"speech": 25})
    sim("a_lot_of_screens_that_are_not_known", {"speech": 60})
    sim("battle_has_to_be_tapped_twice", {"battle_dead": 1})
    sim("battle_is_one_word_of_a_longer_line", {"word_battle": True})
    sim("battle_is_at_the_edge_of_the_lower_quarter", {"battle_y": 1656})
    sim("battle_is_just_inside_the_lower_quarter", {"battle_y": 1657})
    sim("the_whole_walk_on_a_smaller_picture", {"scale": 0.5})
    sim("the_whole_walk_on_a_smaller_picture_with_the_party_full", {"scale": 0.5, "slots": [0, 1, 2], "end": "map"})
    sim("the_whole_walk_on_a_picture_that_is_not_in_proportion", {"scale": 0.75})
    sim("radar_without_the_word_yes", {"radar": "noword"})
    sim("no_radar_at_all", {"radar": "skip"})
    sim("radar_ignores_a_tap", {"radar_dead": 1})
    sim("radar_ignores_every_tap_so_the_steps_run_out", {"radar_dead": 99})
    sim("the_map_comes_at_the_last_step", {"start": "radar", "radar_dead": 68, "radar_to": "map"})
    sim("the_map_comes_one_step_too_late", {"start": "radar", "radar_dead": 69, "radar_to": "map"})
    sim("party_with_three_pokemon", {"slots": [0, 1, 2]})
    sim("party_with_two_pokemon_the_third_slot_is_empty", {"slots": [0, 1]})
    sim("party_with_two_pokemon_the_middle_slot_is_empty", {"slots": [0, 2]})
    sim("party_with_two_pokemon_the_first_slot_is_empty", {"slots": [1, 2]})
    sim("party_with_one_pokemon", {"slots": [0]})
    sim("party_without_pokemon_words", {"slots": []})
    sim("party_without_the_line_use_this_party", {"use": False, "slots": [0, 1, 2]})
    sim("party_without_the_line_use_this_party_and_a_slot_empty", {"use": False, "slots": [0, 1]})
    sim("party_without_the_words_recommended", {"recommended": False})
    sim("party_the_numbers_have_no_cp", {"cp": "%d"})
    sim("party_the_numbers_are_three_digits", {"cp_numbers": [418, 626, 888], "cp": "CP%d"})
    sim("party_the_numbers_are_two_digits", {"cp_numbers": [41, 62, 88], "cp": "CP%d"})
    sim("party_the_numbers_are_five_digits", {"cp_numbers": [26990, 26260, 28880], "cp": "CP%d"})
    sim("party_the_numbers_are_in_other_digits", {"cp": "CP٢٦٩٩%.0s"})
    sim("party_the_words_are_at_the_edge_of_the_slot", {"slots": [0], "cp_dx": 130})
    sim("party_the_words_are_just_outside_the_slot", {"slots": [0], "cp_dx": 140})
    sim("party_the_words_are_a_hair_inside_the_slot", {"slots": [0], "cp_dx": 134})
    sim("party_the_words_are_a_hair_outside_the_slot", {"slots": [0], "cp_dx": 135})
    sim("party_the_words_of_the_slots_are_not_at_the_same_height", {"cp_y_step": 40})
    sim("the_list_does_not_fill_the_slot", {"list_fills": False, "use_with_empty": True})
    sim("the_list_does_not_fill_the_slot_and_the_party_is_not_taken", {"list_fills": False})
    sim("the_party_is_taken_with_an_empty_slot", {"use_with_empty": True, "slots": [0, 1], "list_fills": False})
    sim("party_the_words_stand_on_the_line_use_this_party", {"cp_at_use": True})
    sim("party_the_words_stand_under_the_line_use_this_party", {"cp_below": True})
    sim("party_the_words_stand_under_the_line_use_this_party_all_three", {"cp_below": True, "slots": [0, 1, 2]})
    sim("list_without_the_word_done", {"list_done": False})
    sim("a_pokemon_that_comes_as_a_reward_after_the_fight", {"after": "lost"})
    sim("the_fight_leaves_the_summary", {"after": "summary"})
    sim("the_fight_leaves_the_catch_screen", {"after": "catch"})
    sim("the_fight_leaves_the_map", {"after": "map"})
    sim("the_fight_leaves_the_battle_screen", {"after": "battle"})
    sim("a_prompt_is_a_fight_too", {"fight_state": "prompt"}, fight_secs=12)
    sim("the_fight_took_no_time", {}, fight_secs=0)
    sim("two_bubbles_after_the_fight", {"bubbles": 2})
    sim("summary_has_to_be_tapped_twice", {"summary_dead": 1})
    sim("summary_ends_on_the_map", {"end": "map", "summary_dead": 1})
    sim("the_catch_screen_certainty_is_exactly_the_limit", {"after_class": ["encounterScreen", 0.5]})
    sim("the_catch_screen_certainty_is_too_low", {"after_class": ["encounterScreen", 0.4999]})
    sim("another_screen_class_after_the_fight", {"after_class": ["mapScreen", 0.9]})
    sim("a_pokemon_is_seen_before_a_fight_was_fought", {"class_all": ["encounterScreen", 0.9]})
    sim("a_pokemon_is_seen_before_a_fight_was_fought_certainty_too_low", {"class_all": ["encounterScreen", 0.4]})
    sim("the_person_stops_the_bot_at_the_first_step", {}, stop_at=0)
    sim("the_person_stops_the_bot_at_the_third_step", {}, stop_at=2)
    sim("the_person_stops_the_bot_after_the_fight", {}, stop_at=9)
    sim("the_person_does_not_stop_the_bot", {}, stop_at=999)
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
