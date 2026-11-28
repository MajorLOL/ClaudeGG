#!/usr/bin/env python3
"""Makes tests/fixtures/quests_golden.json.qz (JSON, packed the way qCompress() of Qt does: the length, then zlib): what gamebot.py does with the
GO PASS rewards - the check whether the quest button on the map is gold (quest_gold()), whether it is time to look at it (quests_due()) and the visit
itself (claim_quests(): the quest screen, the tab GO PASS, its pages, down to VIEW REWARDS, CLAIM ALL, the Pokémon that may come as a reward, the X
that closes it) - the file that the C++ port, SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoQuests.cpp, is tested against.

    python3 tools/make_quests_golden.py            writes the file
    python3 tools/make_quests_golden.py --check    says whether the file is what the code does now (the stories stored in it are played again)

The file is a list of stories: a list of calls, each with the EVENTS that it makes, with the time of a fake clock (it starts at 1000.0 and only moves
with the screenshots and the sleeps).  The pictures are drawn on the canvas by the ops of tools/make_throw_golden.py; the check for the map is the
real one.  The stories of claim_quests() are played on a pretend phone ('sim') that has the map, the quest screen with its tabs, the GO PASS with its
pages that scroll, the screen of the rewards and what follows CLAIM ALL: it changes the screen with every touch.  What the code is GIVEN:
    shot          a screenshot (which of the frames of the story)
    ocr           the text reader read the lines (with the places of the words) of a picture
    class         what the screen classifier said of a screen
  what it DOES (the C++ port has to do the same, in this order):
    tap, swipe, sleep, log, save (a picture that is kept), then at the end of every call: result (what it returned) or raised, and state (the time
    of the last look at the quests, as it is afterwards).
"""
import argparse
import copy
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
import gamebot as G  # noqa: E402
import spin_stop as S  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "tests", "fixtures", "quests_golden.json.qz")
PLAIN, frame, line, marker, bgr_for, jsonable = GG.PLAIN, GG.frame, GG.line, GG.marker, GG.bgr_for, GG.jsonable
World = GG.World

GOLD = bgr_for(16, 200, 210)
WHITE = [255, 255, 255]
# the part of the picture that quest_gold() looks at (the canvas is 1768 x 2208): 93 x 93 pixels
X0, Y0, SIZE = 1624, 1824, 93
BUTTON = (1670, 1870)                                   # (where the bot taps the quest button)
CLOSE = (884, 2042)                                     # (the round X at the bottom)


# ---------------------------------------------------------------------- the pretend phone

class Sim:
    """A phone with Pokémon GO: the map, the quest screen with its tabs, the GO PASS with its pages, the rewards, what follows CLAIM ALL.
    p: opens (a tap on the quest button opens the quest screen), tab (the quest screen has the tab GO PASS), tab_dead (a tap on that tab does
    nothing), titles (the pages are named 'GO PASS: ...': how many; 0: the page is the GO PASS itself), pages (for every page: view_after: how
    many swipes until VIEW REWARDS is in view (None: never), daily_after: how many until DAILY TASKS is (None: never), claim: whether the screen of
    the rewards has CLAIM ALL), after (what the classifier says of the screen that CLAIM ALL leaves: [name, score]), close_after (how many taps on
    the X until the map is back), after_screen (the screen that CLAIM ALL leaves: claimed, map), moving (how many pictures after a touch show a screen that is still moving), view_dead (a tap on VIEW REWARDS does
    nothing), start (the screen the phone is on); tab_text, title_fmt, title_ys, view_text, daily_text, claim_text (what the words are, and where the
    titles of the pages are), tab_decoy, view_decoy, claim_decoy (another line with the same words before the real one: it does nothing),
    quest_blank, quest_extra, rewards_extra (no words / more words on the screens, for what the log tells of them), quest_size (the quest screen is
    a smaller picture: the bot takes the height of the screen from that picture; the check for the map then goes by what the frames say, 'is_map')."""

    def __init__(self, spec, world):
        self.p = spec["sim"]
        self.world = world
        self.screen = self.p.get("start", "map")
        self.page = 0
        self.scroll = 0
        self.closes = 0
        self.since = 99
        self.keys = {}

    def pages(self):
        return self.p.get("pages", [{"view_after": 1, "daily_after": None, "claim": True}])

    def cur(self):
        pages = self.pages()
        return pages[min(self.page, len(pages) - 1)]

    def frame(self):
        moving = self.since < self.p.get("moving", 0)
        self.since += 1
        s = self.screen
        if s == "gopass":
            cur = self.cur()
            key = (s, self.page, self.scroll, cur["view_after"] is not None and self.scroll >= cur["view_after"],
                   cur["daily_after"] is not None and self.scroll >= cur["daily_after"])
        elif s == "rewards":
            key = (s, self.cur()["claim"])
        else:
            key = (s,)
        if moving:
            key = key + ("moving", self.since)
        if key not in self.keys:
            self.keys[key] = len(self.world.frames)
            self.world.frames.append(self.build(key, len(self.keys)))
        return self.keys[key]

    def ys(self):
        """Where the titles of the pages are (top to bottom)."""
        return self.p.get("title_ys") or [300 + 80 * k for k in range(self.p.get("titles", 1))]

    def build(self, key, n):
        p = self.p
        s = key[0]
        if s == "map":
            return frame(CG.map_screen()["pic"] + [marker(n)], lines=[], is_map=True)
        if s == "quest":
            lines = [] if p.get("quest_blank") else [line("TODAY", 400, 330), line("RESEARCH", 1300, 330)]
            if p.get("tab_decoy"):
                lines.insert(0, line("GO PASS INFO", 884, 500))
            if p.get("tab", True):
                lines.append(line(p.get("tab_text", "GO PASS"), 884, 330))
            lines += [line(t, 884, 700 + 60 * k) for k, t in enumerate(p.get("quest_extra", []))]
            small = [["size"] + p["quest_size"]] if p.get("quest_size") else []
            return frame([PLAIN, marker(n)] + small, lines=lines, texts={})
        if s == "gopass":
            lines = [line("GO PASS", 884, 250)]
            for k, y in enumerate(self.ys()):
                lines.append(line(p.get("title_fmt", "GO PASS: PAGE %d") % (k + 1), 884, y))
            if p.get("view_decoy"):
                lines.append(line("VIEW REWARDS HISTORY", 884, 600))
            if key[3]:
                lines.append(line(p.get("view_text", "VIEW REWARDS"), 884, 1200))
            if key[4]:
                lines.append(line(p.get("daily_text", "DAILY TASKS"), 884, 1500))
            lines.append(line("CLAIMABLE REWARDS: 3", 884, 1000))
            return frame([PLAIN, marker(n)], lines=lines, texts={})
        if s == "rewards":
            lines = [line("REWARDS", 884, 400)]
            if p.get("claim_decoy"):
                lines.append(line("CLAIM ALL INFO", 884, 600))
            if key[1]:
                lines.append(line(p.get("claim_text", "CLAIM ALL"), 884, 1700))
            lines += [line(t, 884, 800 + 60 * k) for k, t in enumerate(p.get("rewards_extra", []))]
            return frame([PLAIN, marker(n)], lines=lines, texts={})
        return frame([PLAIN, marker(n)], lines=[line("THANK YOU", 884, 900)], texts={})          # (after CLAIM ALL, the quest screens)

    def klass(self):
        return self.p.get("after", ["mapScreen", 0.9])

    def tap(self, x, y):
        self.since = 0
        s, p = self.screen, self.p

        def near(px, py, rx=120, ry=100):
            return abs(x - px) < rx and abs(y - py) < ry
        if s == "map":
            if near(*BUTTON, rx=80, ry=80) and p.get("opens", True):
                self.screen = "quest"
        elif s == "quest":
            if near(884, 330) and p.get("tab", True) and not p.get("tab_dead"):
                self.screen, self.page, self.scroll = "gopass", 0, 0
            elif near(*CLOSE, rx=80, ry=80):
                self.screen = "map"
        elif s == "gopass":
            for k, ty in enumerate(self.ys()):
                if near(884, ty, 300, 35):
                    self.page, self.scroll = k, 0
            cur = self.cur()
            if cur["view_after"] is not None and self.scroll >= cur["view_after"] and near(884, 1200, 300, 60) and not p.get("view_dead"):
                self.screen = "rewards"
            elif near(*CLOSE, rx=80, ry=80):
                self.screen = "map"
        elif s == "rewards":
            if near(884, 1700, 300, 60) and self.cur()["claim"]:
                self.screen = p.get("after_screen", "claimed")
            elif near(*CLOSE, rx=80, ry=80):
                self.screen = "map"
        elif s == "claimed":
            if near(*CLOSE, rx=80, ry=80):
                self.closes += 1
                if self.closes >= p.get("close_after", 1):
                    self.screen = "map"

    def swipe(self, x1, y1, x2, y2):
        self.since = 0
        if self.screen == "gopass":
            self.scroll += 1


# ---------------------------------------------------------------------- the fake phone

def record(spec):
    """Plays one story on the fake phone; returns the list of events."""
    Clock.t = START
    rec = Rec()
    Clock.rec = rec
    world = World(spec)
    sim = Sim(spec, world) if spec.get("sim") is not None else None
    saved_g = {n: getattr(G, n) for n in ("time", "log", "setting", "save_async", "ocr_lines", "screen_class") if hasattr(G, n)}
    saved_s = {n: getattr(S, n) for n in ("time", "log", "tap", "swipe", "screenshot", "on_map")}
    saved_state = dict(G.quest_state)
    try:
        G.time = S.time = Clock
        G.log = S.log = lambda text: rec.add("log", text)
        settings = dict(spec.get("settings", {}))
        G.setting = lambda key, default: settings.get(key, default)
        if spec.get("fake_map"):                                  # (the real check for the map reads a picture of the size of the canvas: for a smaller one the frame says)
            S.on_map = lambda img: bool(world.frame(img).get("is_map"))
        G.save_async = lambda name, img: rec.add("save", name, world.index_of(img))

        def tap(x, y, ms=120):
            rec.add("tap", x, y) if ms == 120 else rec.add("press", x, y, ms)
            if sim:
                sim.tap(x, y)
        S.tap = tap

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

        def screen_class(img):
            answer = sim.klass() if sim else spec.get("class", ["mapScreen", 0.9])
            rec.add("class", answer[0], answer[1])
            return answer[0], answer[1]
        G.screen_class = screen_class

        for call in spec["calls"]:
            if "settings" in call:
                settings.update(call["settings"])
            if "advance" in call:
                Clock.t += call["advance"]
            rec.add("call", call["fn"], call.get("img"), None)
            if "st" in call:
                G.quest_state["t"] = call["st"]["t"]
            try:
                fn = call["fn"]
                img = world.picture(call["img"]) if "img" in call else None
                if fn == "quest_gold":
                    result = bool(G.quest_gold(img))
                elif fn == "quests_due":
                    result = bool(G.quests_due(img))
                elif fn == "claim_quests":
                    result = G.claim_quests()
                else:
                    raise ValueError(call)
                rec.add("result", jsonable(result))
            except Exception as e:  # noqa: BLE001
                rec.add("raised", str(e))
            rec.add("state", {"st": {"t": G.quest_state["t"]} if "st" in call else None})
        return rec.events
    finally:
        for n, v in saved_g.items():
            setattr(G, n, v)
        for n, v in saved_s.items():
            setattr(S, n, v)
        G.quest_state.clear()
        G.quest_state.update(saved_state)


# ---------------------------------------------------------------------- the stories

def gold_ops(n, x=X0, y=Y0, colour=GOLD):
    """Exactly n pixels of the colour in the part that quest_gold() looks at (full rows of 93, then a row that is not full)."""
    full, rest = divmod(n, SIZE)
    ops = [["rect", x, y, SIZE, full, colour]] if full else []
    if rest:
        ops.append(["rect", x, y + full, rest, 1, colour])
    return ops


def stories():
    out = []

    def add(name, calls, frames=None, **spec):
        spec.update(calls=calls, frames=frames if frames is not None else [])
        out.append({"id": name, "spec": spec})

    def call(fn, **kw):
        return dict({"fn": fn}, **kw)

    def sim(name, p, **spec):
        if p.get("quest_size"):
            spec["fake_map"] = True
        add(name, [call("claim_quests", st={"t": 0.0})], [], sim=p, **spec)

    # ---- is the quest button gold?
    for n in (0, 1, 3891, 3892, 3893, 3894, 8649):
        add("gold_%d_pixels" % n, [call("quest_gold", img=0)], [frame([PLAIN] + gold_ops(n))])
    for name, colour in (("hue_7", bgr_for(7, 200, 210)), ("hue_8", bgr_for(8, 200, 210)), ("hue_25", bgr_for(25, 200, 210)), ("hue_26", bgr_for(26, 200, 210)),
                         ("saturation_119", bgr_for(16, 119, 200)), ("saturation_120", bgr_for(16, 120, 200)), ("value_179", bgr_for(16, 181, 179)),
                         ("value_180", bgr_for(16, 180, 180)), ("saturation_255", [0, 100, 200]), ("value_255", [51, 154, 255]),
                         ("saturation_and_value_255", [0, 128, 255]), ("white", WHITE), ("grey", [140, 140, 140])):
        add("gold_colour_%s" % name, [call("quest_gold", img=0)], [frame([PLAIN] + gold_ops(SIZE * SIZE, colour=colour))])
    # the edges of the part that is looked at (rows 1824 to 1916, columns 1624 to 1716): 3892 pixels are not enough, one more is
    for name, (x, y) in (("above", (1650, 1823)), ("below", (1650, 1917)), ("left", (1623, 1900)), ("right", (1717, 1900))):
        add("gold_3892_and_one_pixel_outside_%s" % name, [call("quest_gold", img=0)], [frame([PLAIN] + gold_ops(3892, y=Y0 + 1) + [["rect", x, y, 1, 1, GOLD]])])
    for name, (x, y) in (("first_row", (1650, 1824)), ("last_row", (1650, 1916)), ("first_column", (1624, 1900)), ("last_column", (1716, 1900))):
        add("gold_3892_and_one_pixel_at_the_edge_%s" % name, [call("quest_gold", img=0)],
            [frame([PLAIN] + gold_ops(3892, y=Y0 + 1 if name == "first_row" else Y0) + [["rect", x, y, 1, 1, GOLD]])])
    add("gold_a_smaller_picture", [call("quest_gold", img=0), call("quest_gold", img=1)],
        [frame([PLAIN, ["rect", 800, 900, 100, 100, GOLD], ["size", 884, 1104]]), frame([PLAIN, ["rect", 800, 900, 30, 30, GOLD], ["size", 884, 1104]])])
    add("gold_somewhere_else", [call("quest_gold", img=0)], [frame([PLAIN, ["rect", 0, 0, 1700, 1800, GOLD]])])

    # ---- is it time to look?
    gold = frame([PLAIN] + gold_ops(SIZE * SIZE))
    plain = frame([PLAIN])
    for name, t, settings in (("never_looked", 0.0, {}), ("a_moment_ago", 999.0, {}), ("899_s_ago", 100.1, {}), ("900_s_ago", 100.0, {}), ("901_s_ago", 99.0, {}),
                              ("switched_off", 0.0, {"quests": False}), ("switched_on", 0.0, {"quests": True}), ("switched_off_a_moment_ago", 999.0, {"quests": False})):
        add("due_%s_gold" % name, [call("quests_due", img=0, st={"t": t}, settings=settings)], [gold])
        add("due_%s_not_gold" % name, [call("quests_due", img=0, st={"t": t}, settings=settings)], [plain])
    add("due_the_clock_moves", [call("quests_due", img=0, st={"t": 1000.0}, advance=0.0), call("quests_due", img=0, st={"t": 1000.0}, advance=899.0),
                                call("quests_due", img=0, st={"t": 1000.0}, advance=1.0)], [gold])

    # ---- a visit
    sim("claim_the_rewards", {})
    sim("claim_the_rewards_the_screens_move", {"moving": 1})
    sim("claim_the_rewards_the_screens_move_longer", {"moving": 3})
    sim("claim_the_rewards_the_screens_keep_moving", {"moving": 20})
    sim("claim_the_quest_screen_does_not_open", {"opens": False})
    sim("claim_no_gopass_tab", {"tab": False})
    sim("claim_the_gopass_tab_does_nothing", {"tab_dead": True})
    sim("claim_view_rewards_at_once", {"pages": [{"view_after": 0, "daily_after": None, "claim": True}]})
    sim("claim_view_rewards_after_five_swipes", {"pages": [{"view_after": 5, "daily_after": None, "claim": True}]})
    sim("claim_view_rewards_after_six_swipes", {"pages": [{"view_after": 6, "daily_after": None, "claim": True}]})
    sim("claim_view_rewards_never", {"pages": [{"view_after": None, "daily_after": None, "claim": True}]})
    sim("claim_daily_tasks_first", {"pages": [{"view_after": 3, "daily_after": 1, "claim": True}]})
    sim("claim_daily_tasks_and_view_rewards_together", {"pages": [{"view_after": 1, "daily_after": 1, "claim": True}]})
    sim("claim_daily_tasks_after_view_rewards", {"pages": [{"view_after": 1, "daily_after": 2, "claim": True}]})
    sim("claim_view_rewards_does_nothing", {"view_dead": True})
    sim("claim_no_claim_all", {"pages": [{"view_after": 1, "daily_after": None, "claim": False}]})
    sim("claim_a_pokemon_comes", {"after": ["encounterScreen", 0.9]})
    sim("claim_a_pokemon_comes_score_exactly_the_limit", {"after": ["encounterScreen", 0.5]})
    sim("claim_a_pokemon_comes_certain", {"after": ["encounterScreen", 1.0]})
    sim("claim_a_pokemon_comes_the_clock_moves", {"after": ["encounterScreen", 0.8], "moving": 2}, shot_seconds=0.7)
    sim("claim_a_pokemon_comes_from_the_second_page", {"after": ["encounterScreen", 0.8], "titles": 2,
                                                       "pages": [{"view_after": None, "daily_after": None, "claim": True}, {"view_after": 1, "daily_after": None, "claim": True}]})
    sim("claim_a_pokemon_comes_score_too_low", {"after": ["encounterScreen", 0.4999]})
    sim("claim_another_screen_comes", {"after": ["menusScreen", 0.9]})
    sim("claim_the_map_comes_back_at_once", {"after": ["mapScreen", 0.9], "after_screen": "map"})
    sim("claim_the_x_has_to_be_tapped_twice", {"close_after": 2})
    sim("claim_the_x_has_to_be_tapped_three_times", {"close_after": 3})
    sim("claim_the_x_does_not_close", {"close_after": 9})
    two_pages = [{"view_after": None, "daily_after": None, "claim": True}, {"view_after": 1, "daily_after": None, "claim": True}]
    sim("claim_two_pages_the_second_has_it", {"titles": 2, "pages": two_pages})
    sim("claim_two_pages_the_first_has_it", {"titles": 2, "pages": [two_pages[1], two_pages[0]]})
    sim("claim_two_pages_none_has_it", {"titles": 2, "pages": [two_pages[0], two_pages[0]]})
    sim("claim_two_pages_the_second_has_no_claim_all", {"titles": 2, "pages": [two_pages[0], {"view_after": 1, "daily_after": None, "claim": False}]})
    page = {"view_after": None, "daily_after": None, "claim": True}
    sim("claim_three_pages_the_third_has_it", {"titles": 3, "pages": [page, page, {"view_after": 1, "daily_after": None, "claim": True}]})
    sim("claim_four_pages_the_fourth_is_not_looked_at", {"titles": 4, "pages": [page, page, page, {"view_after": 1, "daily_after": None, "claim": True}]})
    sim("claim_no_page_titles", {"titles": 0})
    sim("claim_no_page_titles_and_no_view_rewards", {"titles": 0, "pages": [{"view_after": None, "daily_after": None, "claim": True}]})
    sim("claim_from_the_gopass_screen", {"start": "gopass"})
    sim("claim_the_phone_is_on_the_gopass_and_the_button_does_nothing", {"start": "gopass", "opens": False})
    sim("claim_after_a_look_the_clock_moves", {"moving": 2}, shot_seconds=0.7)
    # what is read: the words (in capitals or not, in another order), the first line that has them, the places of the titles
    sim("claim_the_words_in_small_letters", {"tab_text": "Go Pass", "title_fmt": "Go Pass: Page %d", "view_text": "View Rewards", "daily_text": "Daily Tasks",
                                             "claim_text": "Claim All"})
    sim("claim_daily_tasks_in_small_letters", {"daily_text": "daily tasks", "pages": [{"view_after": 3, "daily_after": 1, "claim": True}]})
    sim("claim_daily_task_not_tasks", {"daily_text": "DAILY TASK", "pages": [{"view_after": 3, "daily_after": 1, "claim": True}]})
    sim("claim_the_words_in_another_order", {"view_text": "REWARDS VIEW", "claim_text": "ALL CLAIM"})
    sim("claim_view_only", {"view_text": "VIEW"})
    sim("claim_reward_not_rewards", {"view_text": "VIEW REWARD"})
    sim("claim_claim_only", {"claim_text": "CLAIM"})
    sim("claim_claimall_in_one_word", {"claim_text": "CLAIMALL"})
    sim("claim_gopass_in_one_word", {"tab_text": "GOPASS"})
    sim("claim_the_first_line_with_gopass_is_tapped", {"tab_decoy": True})
    sim("claim_the_first_line_with_view_rewards_is_tapped", {"view_decoy": True})
    sim("claim_the_first_line_with_claim_all_is_tapped", {"claim_decoy": True})
    sim("claim_a_title_at_the_edge_of_the_upper_third", {"title_ys": [772]})
    sim("claim_a_title_just_below_the_upper_third", {"title_ys": [773]})
    sim("claim_a_title_in_a_smaller_picture", {"title_ys": [386], "quest_size": [884, 1104]})
    sim("claim_a_title_below_the_upper_third_of_a_smaller_picture", {"title_ys": [387], "quest_size": [884, 1104]})
    sim("claim_a_title_exactly_at_the_upper_third_of_a_picture", {"title_ys": [350], "quest_size": [884, 1000]})
    sim("claim_a_title_one_pixel_above_the_upper_third_of_a_picture", {"title_ys": [349], "quest_size": [884, 1000]})
    sim("claim_titles_in_small_letters", {"title_fmt": "go pass: page %d"})
    sim("claim_a_title_without_colon", {"title_fmt": "GO PASS PAGE %d"})
    sim("claim_a_title_without_gopass", {"title_fmt": "PASS: PAGE %d"})
    sim("claim_two_titles_without_colon", {"titles": 2, "title_fmt": "GO PASS PAGE %d"})
    sim("claim_no_tab_the_quest_screen_has_much_text",
        {"tab": False, "quest_extra": ["WEEKLY CHALLENGE PROGRESS", "COLLECTION CHALLENGE ADVENTURE", "SPECIAL RESEARCH TIMED STORIES", "FIELD NOTES BADGES"]})
    sim("claim_no_tab_the_quest_screen_has_no_words", {"tab": False, "quest_blank": True})
    sim("claim_no_tab_the_words_come_twice", {"tab": False, "quest_extra": ["TODAY RESEARCH", "RESEARCH TODAY"]})
    sim("claim_no_claim_all_the_screen_has_much_text",
        {"pages": [{"view_after": 1, "daily_after": None, "claim": False}],
         "rewards_extra": ["COMPLETED STAMPS TIERS", "PREMIUM UPGRADE BONUS REWARDS", "SEASONAL TROPHIES AND EXTRAS", "FREE TRACK ITEMS"]})

    add("claim_twice_in_a_row", [call("claim_quests", st={"t": 0.0}), call("claim_quests", st={"t": 5.0})], [], sim={"pages": [{"view_after": None, "daily_after": None, "claim": True}]})
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
