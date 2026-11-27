#!/usr/bin/env python3
"""Makes tests/fixtures/flow_golden.json.qz (JSON, packed the way qCompress() of Qt does: the length, then zlib): stories of the
walk around a fight of gamebot.py - battle_open_menu(), _battle_to_map() and battle_run() - as the file that the C++ port of
that walk (SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoFlow.cpp) is tested against.

    python3 tools/make_flow_golden.py            writes the file
    python3 tools/make_flow_golden.py --check    says whether the file is what the walk does now (the stories stored in it are played again)

A story is a fake phone (a few screens and what a tap, a swipe or BACK on each does, as data), the options of the walk and, for
battle_run, what the fights it starts come to.  The walk runs with a fake clock (it starts at 1000.0 and only moves with the
screenshots and the sleeps) and what comes out is the list of EVENTS, every one with the time of that clock:
  what the walk is GIVEN (the C++ port is given the same):
    screenshot   a screenshot                           (the picture: how it is made, see make_picture())
    screenshot_fail   the phone did not answer          (the message)
    on_map       the answer of the check for the map
    ocr          the text reader read lines             (size of the picture, the part, scale, its mean, the lines)
    ocr_line     the text reader read one line          (size, lines, mean, text, and for a button label: a hash of the picture, which is in
                                                         the table "labels" of the file, as PNG)
    class        the answer of the screen classifier    (name, certainty)
    stop, no_more   what the callbacks of the caller said
    day_count    the count of the day after a fight     (key, text)
    fight        a battle that is fought                (where USE THIS PARTY is, what came of it: result, why, seconds, gave_up)
  what the walk DOES (the C++ port has to do the same, in this order):
    tap, swipe, back, log, sleep, save, beat, restart, recheck, mark_done
    and at the end result (what the walk returned) or raised (it did not return: "interrupt" or "error").
The label of a button is read by gamebot.button_label() itself, with the text reader (the tesseract program) played by this
tool: the picture that is given to it is part of the event."""
import argparse
import base64
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import types
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.environ["HOME"] = tempfile.mkdtemp()               # (no team, no settings and no memory of other days)
sys.path.insert(0, ROOT)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import battle_engine as BE  # noqa: E402
import gamebot as G  # noqa: E402
import spin_stop as S  # noqa: E402

OUT = os.path.join(ROOT, "tests", "fixtures", "flow_golden.json.qz")
FIX = os.path.join(ROOT, "tests", "fixtures")
W, H = 1768, 2208
START = 1000.0                                          # the clock of the fake phone starts here
LEAGUE = "Great League"


# ---------------------------------------------------------------------- the pictures

_pictures = {}
LABELS = {}                                              # digest -> the PNG of a label that was given to the text reader


def make_picture(spec):
    """A picture of the canvas (1768 x 2208) as the story says it is made:
      ["white"]                    white
      ["rect", [[y0, y1, x0, x1, [b, g, r]], ...]]    white, with filled rectangles (fractions of the picture)
      ["battle", name]             the lowest fifth of a real screenshot of the Battle screen (fixtures/nav), the rest white
      ["done", cleared]            the real Battle screen with the grey BATTLE button (the gold tiles white when cleared)
      ["fight", name]              a picture of a real fight (fixtures/fight)"""
    key = json.dumps(spec)
    if key in _pictures:
        return _pictures[key]
    kind = spec[0]
    if kind == "white":
        img = np.full((H, W, 3), 255, np.uint8)
    elif kind == "rect":
        img = np.full((H, W, 3), 255, np.uint8)
        for y0, y1, x0, x1, colour in spec[1]:
            img[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)] = colour
    elif kind == "battle":
        strip = cv2.imread(os.path.join(FIX, "nav", spec[1] + ".jpg"))
        full = np.full((strip.shape[0] * 5, strip.shape[1], 3), 255, np.uint8)
        full[-strip.shape[0]:] = strip
        img = cv2.resize(full, (W, H), interpolation=cv2.INTER_CUBIC)
    elif kind == "done":
        img = cv2.resize(cv2.imread(os.path.join(FIX, "nav", "home_done.jpg")), (W, H), interpolation=cv2.INTER_CUBIC)
        if spec[1]:
            img[int(0.80 * H):int(0.92 * H), int(0.08 * W):int(0.42 * W)] = 255
    elif kind == "fight":
        img = cv2.resize(cv2.imread(os.path.join(FIX, "fight", spec[1] + ".jpg")), (W, H), interpolation=cv2.INTER_CUBIC)
    else:
        raise ValueError(spec)
    _pictures[key] = img
    return img


# ---------------------------------------------------------------------- the screens of the fake phone

def ln(text, x, y):
    """An OCR line: its words are 60 px apart."""
    return [text, x, y, [[w, x + 60 * i, y] for i, w in enumerate(text.split())]]


GREEN = [120, 205, 110]
ORANGE = [60, 140, 245]
UPPER = [0.80, 0.85, 0.32, 0.71, GREEN]            # the BATTLE button of the basic rewards, scrolled into view
LOWER = [0.93, 0.98, 0.32, 0.71, GREEN]            # ... and the one of the premium rewards under it
POPUP = [0.83, 0.89, 0.33, 0.67, GREEN]            # the green button of a pop-up
WHITE = [255, 255, 255]
BARS = [[0.8338, 0.8373, 0.45, 0.55, WHITE], [0.838, 0.842, 0.45, 0.55, WHITE], [0.8785, 0.8815, 0.45, 0.55, WHITE],
        [0.8845, 0.8875, 0.45, 0.55, WHITE], [0.855, 0.865, 0.344, 0.355, WHITE], [0.855, 0.865, 0.357, 0.371, WHITE],
        [0.855, 0.865, 0.629, 0.643, WHITE], [0.855, 0.865, 0.645, 0.655, WHITE]]    # (in, at the edge of and out of the zone)


def rect(*items):
    return ["rect", [list(i) for i in items]]


SMALL = rect([0.0, 0.05, 0.0, 0.3, [0, 0, 0]])         # 1.5 % of the picture is another colour
TINY = rect([0.0, 0.025, 0.0, 0.2, [0, 0, 0]])         # 0.5 %
GREY30 = rect([0.0, 1.0, 0.0, 1.0, [225, 225, 225]])   # every pixel 30 levels darker than white
GREY20 = rect([0.0, 1.0, 0.0, 1.0, [235, 235, 235]])   # ... 20 levels


HOME = [ln("GO BATTLE LEAGUE", 600, 900), ln("BASIC REWARDS", 650, 1700)]
PARTY = [ln("GREAT LEAGUE", 600, 300), ln("MAX CP PER POKEMON: 1500", 500, 380), ln("MEDICHAM AZUMARILL", 500, 600),
         ln("CHOOSE YOUR PARTY", 500, 800), ln("USE THIS PARTY", 700, 1930)]
MENU = [ln("SETTINGS", 300, 520), ln("BATTLE", 1300, 700), ln("SHOP", 900, 700), ln("ITEMS", 1300, 1500), ln("POKEMON", 400, 1500)]
LEAGUES = [ln("CHOOSE YOUR LEAGUE", 700, 300), ln("GREAT LEAGUE", 800, 700), ln("MAX CP PER POKEMON: 1500", 800, 780),
           ln("ULTRA LEAGUE", 800, 1100), ln("MAX CP PER POKEMON: 2500", 800, 1180)]

SCREENS = {
    # (made up here, after the tests of tests/test_battle_claim.py: the Battle screen, a claim, a new set, a pop-up)
    "home_claim": {"pic": ["battle", "home_claim"], "lines": HOME, "label": "CLAIM RANK REWARDS!"},
    "home_battle": {"pic": ["battle", "home_battle"], "lines": HOME, "label": "BATTLE"},
    "home_newset": {"pic": ["battle", "home_newset"], "label": "",
                    "lines": [ln("GO BATTLE LEAGUE", 600, 1260), ln("2026 GO LAIC CUP: GREAT LEAGUE EDITION", 500, 1600),
                              ln("CHOOSE A REWARD TIER TO ENTER THE GO BATTLE LEAGUE.", 300, 1690)]},
    "home_scrolled": {"pic": rect(UPPER, LOWER), "label": "BATTLE",
                      "lines": [ln("GO BATTLE LEAGUE", 600, 860), ln("CHOOSE A REWARD TIER TO ENTER THE GO BATTLE LEAGUE.", 300, 1290),
                                ln("PREMIUM REWARDS", 650, 1960)]},
    "home_too_far": {"pic": rect(LOWER), "label": "BATTLE",
                     "lines": [ln("CHOOSE A REWARD TIER TO ENTER THE GO BATTLE LEAGUE.", 300, 400), ln("PREMIUM REWARDS", 650, 1500)]},
    "home_empty": {"pic": ["white"], "lines": [ln("GO BATTLE LEAGUE", 600, 900)]},
    "premium": {"pic": ["white"], "lines": [ln("USE A PREMIUM BATTLE PASS", 500, 900)]},
    "welcome": {"pic": ["battle", "welcome"], "label": "LETV'S GO!",
                "lines": [ln("WELCOME TO THE GO BATTLE", 567, 1531), ln("RISE THROUGH THE RANKS AND COMPETE WORLDWIDE FOR", 364, 1731),
                          ln("REWARDS AND GLORY", 766, 1798)]},
    "tutorial": {"pic": ["fight", "result_loss"], "label": "NEXT", "lines": [ln("BATTLES ARE FOUGHT IN SETS OF FIVE", 400, 900)]},
    "odd_party": {"pic": ["fight", "result_loss"], "label": "USE THIS PARTY", "lines": [ln("NEW PARTY", 700, 900)]},
    "coins": {"pic": ["fight", "result_loss"], "label": "OK", "lines": [ln("BATTLE NOW FOR 100 POKECOINS?", 400, 900)]},
    "rankup": {"pic": ["fight", "versus"], "lines": [ln("YOU REACHED RANK 7", 500, 700)]},
    "rewards": {"pic": ["fight", "result_loss"], "label": "OK", "lines": [ln("RANK 7 REWARDS", 600, 600)]},
    "shop": {"pic": ["fight", "result_loss"], "label": "BUY 100 COINS", "lines": [ln("SPECIAL OFFER", 600, 600)]},
    "party": {"pic": ["white"], "lines": PARTY},
    "catch": {"pic": ["fight", "versus"], "lines": [], "class": ["encounterScreen", 0.9]},
    "stuck": {"pic": ["fight", "versus"], "lines": []},
    "home_done2": {"pic": ["done", False], "lines": HOME + [ln("COLLECT COLLECT", 230, 1985)]},
    "home_done1": {"pic": ["done", False], "lines": HOME + [ln("COLLECT", 560, 1985)]},
    "home_done": {"pic": ["done", True], "lines": HOME},
    "home_max": {"pic": ["battle", "home_battle"], "label": "BATTLE",
                 "lines": HOME + [ln("YOU'VE REACHED THE MAXIMUM NUMBER OF BATTLES FOR", 300, 1180), ln("TODAY.", 800, 1250)]},
    "wrong": {"pic": ["white"], "lines": []},
    # (the screens around them)
    "map": {"pic": ["white"], "lines": [], "map": True},
    "menu": {"pic": ["white"], "lines": MENU},
    "menu_no_battle": {"pic": ["white"], "lines": [m for m in MENU if m[0] != "BATTLE"]},
    "league": {"pic": ["white"], "lines": LEAGUES},
    "league_empty": {"pic": ["white"], "lines": [ln("CHOOSE YOUR LEAGUE", 700, 300), ln("SEE WHAT IS COMING NEXT", 700, 400)]},
    "exit": {"pic": ["white"], "lines": [ln("DO YOU WANT TO EXIT POKEMON GO?", 600, 1000), ln("CANCEL", 600, 1300), ln("EXIT", 1100, 1300)]},
    "exit_no_cancel": {"pic": ["white"], "lines": [ln("DO YOU WANT TO EXIT POKEMON GO?", 600, 1000)]},
    "exit_battle": {"pic": ["white"], "lines": [ln("EXIT THE TRAINER BATTLE?", 800, 900), ln("YES", 600, 1250), ln("NO", 1100, 1250)]},
    "exit_battle_title": {"pic": ["white"], "lines": [ln("EXIT THE TRAINER BATTLE?", 800, 900)]},
    "exit_battle_nothing": {"pic": ["white"], "lines": [ln("DO YOU WANT TO EXIT THE TRAINER BATTLE", 800, 900)]},
    "loading": {"pic": ["white"], "lines": []},
    "other_text": {"pic": ["white"], "lines": [ln("SOMETHING ELSE", 500, 900)]},
    "popup_ok": {"pic": rect(POPUP), "label": "OK", "lines": [ln("THANK YOU FOR PLAYING", 500, 900)]},
    "popup_unread": {"pic": rect(POPUP), "label": "", "lines": [ln("THANK YOU FOR PLAYING", 500, 900)]},
    "popup_use": {"pic": rect(POPUP), "label": "USE THIS PARTY", "lines": [ln("THANK YOU FOR PLAYING", 500, 900)]},
    "popup_buy": {"pic": rect(POPUP), "label": "OK", "lines": [ln("BUY THE COINS", 500, 900)]},
    # (a green button with white marks on it where the label is read from and around it: the zone of the label picture)
    "popup_busy": {"pic": rect(POPUP, *BARS), "label": "OK", "lines": [ln("THANK YOU FOR PLAYING", 500, 900)]},
    "popup_faint": {"pic": rect(POPUP, [0.855, 0.865, 0.45, 0.55, [130, 205, 132]]), "label": "OK", "lines": [ln("THANK YOU FOR PLAYING", 500, 900)]},
    "popup_collect_coins": {"pic": rect(POPUP), "label": "COLLECT POKECOINS", "lines": [ln("THANK YOU FOR PLAYING", 500, 900)]},
    "orange_busy": {"pic": rect([0.95, 0.99, 0.32, 0.71, ORANGE], [0.9566, 0.9600, 0.45, 0.55, WHITE]), "label": "", "lines": HOME},
    "popup_coins": {"pic": rect(POPUP), "label": "100 POKECOINS", "lines": [ln("THANK YOU FOR PLAYING", 500, 900)]},
    "reward_coins": {"pic": rect(POPUP), "label": "100 POKECOINS", "lines": [ln("REWARDS", 600, 600)]},
    "home_label_premium": {"pic": rect(UPPER), "label": "PREMIUM BATTLE", "lines": [ln("GO BATTLE LEAGUE", 600, 860)]},
    "home_label_mid": {"pic": ["white"], "lines": HOME + [ln("BATTLE", 884, 2030)]},
    "exit_misread": {"pic": ["white"], "lines": [ln("DO YOU WANT TO EXIT POKEMON GO?", 600, 1000), ln("CANCE1", 600, 1300), ln("EXIT", 1100, 1300)]},
    "popup_pass": {"pic": rect(POPUP), "label": "GET A PASS", "lines": [ln("THANK YOU FOR PLAYING", 500, 900)]},
    "popup_odd": {"pic": rect(POPUP), "label": "MAYBE", "lines": [ln("THANK YOU FOR PLAYING", 500, 900)]},
    "result_next": {"pic": ["fight", "result_loss"], "label": "", "lines": [ln("YOU WIN", 700, 800)]},
    "result_label": {"pic": ["fight", "result_loss"], "label": "ODD LABEL", "lines": [ln("GOOD EFFORT", 700, 800)]},
    "result_check": {"pic": ["fight", "day3_win"], "lines": [ln("YOU WIN", 700, 800)]},
    "result_check_text": {"pic": ["fight", "day3_win"], "lines": [ln("SOMETHING", 700, 800)], "words": "YOU WIN!"},
    "result_check_none": {"pic": ["fight", "day3_win"], "lines": [ln("SOMETHING", 700, 800)]},
    "fight": {"pic": ["fight", "fight_ready"], "lines": []},
    "fight_prompt": {"pic": ["fight", "shield_question"], "lines": []},
    "orange_claim": {"pic": rect([0.95, 0.99, 0.32, 0.71, ORANGE]), "label": "CLAIM", "lines": HOME},
    "orange_label": {"pic": rect([0.95, 0.99, 0.32, 0.71, ORANGE]), "label": "", "lines": HOME},
    "home_claim_text": {"pic": ["white"], "lines": HOME + [ln("CLAIM RANK REWARDS", 884, 2150)]},
    "home_label": {"pic": ["white"], "lines": HOME + [ln("BATTLE", 884, 2150)]},
    "home_label_high": {"pic": ["white"], "lines": HOME + [ln("BATTLE", 884, 1900)]},
    "home_premium_text": {"pic": rect(UPPER), "label": "PREMIUM BATTLE",
                          "lines": [ln("GO BATTLE LEAGUE", 600, 860), ln("PREMIUM REWARDS", 650, 1000)]},
    "home_premium_edge": {"pic": rect(UPPER), "label": "BATTLE",
                          "lines": [ln("GO BATTLE LEAGUE", 600, 860), ln("PREMIUM REWARDS", 650, 1768)]},     # (the top of the button is at 1768.6)
    "home_premium_above": {"pic": rect(UPPER), "label": "BATTLE",
                           "lines": [ln("GO BATTLE LEAGUE", 600, 860), ln("PREMIUM REWARDS", 650, 1000)]},
    "reward_next": {"pic": ["white"], "lines": [ln("YOUR REWARDS", 600, 600), ln("CONTINUE", 884, 1700)]},
    "reward_buttons": {"pic": rect(POPUP, [0.70, 0.76, 0.33, 0.67, ORANGE]), "label": "CLAIM", "lines": [ln("REWARDS", 600, 600)]},
    "reward_two_buttons": {"pic": rect(POPUP, [0.70, 0.76, 0.33, 0.67, ORANGE]), "label": "BUY",
                           "lines": [ln("REWARDS", 600, 600)]},
    "reward_nothing": {"pic": ["white"], "lines": []},
    "battle_home_party_text": {"pic": ["white"], "lines": [ln("BATTLE", 600, 500)] + HOME},
}


OVER = {"pic": "pics", "lines": "lines", "label": "labels", "words": "words", "class": "classes", "map": "maps"}


def scene_of(world, key, default=None):
    """What the story says about the scene that is on the screen (spec["pics"][scene] ...), else what the screens above say."""
    scene = world.scene
    over = world.spec.get(OVER[key], {}).get(scene)
    if over is not None:
        return over
    return SCREENS[scene].get(key, default)


class World:
    """The screen of the fake phone and what it does with a tap, a swipe or BACK (rules: [scene, action, box, to], the first one that
    fits is used; the scene "*" fits every scene; action "tap" with box [x0, x1, y0, y1] (fractions, strictly inside), "swipe_down"
    (the finger goes up: the page scrolls down), "swipe_up", "back", "any")."""

    def __init__(self, spec):
        self.spec = spec
        self.scene = spec["scene"]
        self.queue = [list(p) for p in spec.get("pre", {}).get(self.scene, [])]
        self.shots = 0
        self.touched = 0

    def go(self, to):
        self.scene = to
        self.queue = [list(p) for p in self.spec.get("pre", {}).get(to, [])]

    def act(self, action, fx=0.0, fy=0.0):
        self.touched += 1
        for scene, what, box, to in self.spec["rules"]:
            if scene not in (self.scene, "*") or what not in (action, "any"):
                continue
            if box is not None and not (box[0] < fx < box[1] and box[2] < fy < box[3]):
                continue
            self.go(to)
            return

    def picture(self):
        if self.queue:
            return self.queue.pop(0)
        return scene_of(self, "pic")

    def lines(self, y0):
        return [ln_ for ln_ in scene_of(self, "lines", None) or [] if ln_[2] >= y0]


# ---------------------------------------------------------------------- the rules of the screens of the tests

def claim_rules(after="rankup", then="party", claim_works=True, after_rewards="home_battle", collect_to="home_done1"):
    """What a tap does on the screens of the Battle screen and what comes after it (as tests/test_battle_claim.py has it)."""
    rules = []
    if claim_works:
        rules.append(["home_claim", "tap", [0.08, 0.94, 0.95, 2.0], after])
    rules += [
        ["rankup", "tap", None, "rewards"],
        ["rewards", "tap", [0.33, 0.67, 0.83, 0.89], after_rewards],
        ["home_done2", "tap", [-1.0, 0.25, 0.84, 0.88], collect_to],
        ["home_done1", "tap", [0.25, 0.4, 0.84, 0.88], "home_claim"],
        ["home_battle", "tap", [0.32, 0.71, 0.972, 2.0], then],
        ["welcome", "tap", [0.32, 0.68, 0.88, 0.95], "party"],
        ["tutorial", "tap", [0.33, 0.67, 0.83, 0.89], "party"],
        ["odd_party", "tap", [0.33, 0.67, 0.83, 0.89], "wrong"],
        ["coins", "tap", [0.33, 0.67, 0.83, 0.89], "wrong"],
        ["home_scrolled", "tap", [0.32, 0.71, 0.80, 0.85], "party"],
        ["home_scrolled", "tap", [0.32, 0.71, 0.93, 0.98], "premium"],
        ["home_too_far", "tap", [0.32, 0.71, 0.93, 0.98], "premium"],
        ["home_newset", "swipe_down", None, "home_scrolled"],
        ["home_too_far", "swipe_up", None, "home_scrolled"],
    ]
    return rules


BACK_TO_MAP = [["*", "back", None, "map"]]


def story(call, scene, rules=None, **kw):
    spec = {"call": call, "scene": scene, "rules": rules if rules is not None else [], "league": LEAGUE, "names": ["Medicham", "Azumarill"],
            "args": {}, "fights": [], "shot_seconds": 0.4}
    spec.update(kw)
    return spec


def walk(scene, rules=None, back=True, **kw):
    """battle_open_menu(); args: restart, stay (default True: a walk to the party screen), leagues_only."""
    args = {"restart": False, "stay": True, "leagues_only": False}
    args.update(kw.pop("args", {}))
    return story("open_menu", scene, (rules or []) + (BACK_TO_MAP if back else []), args=args, **kw)


def leave(scene, rules=None, **kw):
    """_battle_to_map(); args: leaving_setup."""
    args = {"leaving_setup": False}
    args.update(kw.pop("args", {}))
    return story("to_map", scene, rules, args=args, **kw)


def run(scene, count, rules=None, fights=None, back=True, **kw):
    return story("battle_run", scene, (rules or []) + (BACK_TO_MAP if back else []), args={"count": count}, fights=fights or [], **kw)


# ---------------------------------------------------------------------- the stories

def stories():
    out = []

    def add(name, spec):
        out.append({"id": name, "spec": spec})

    # --- the tests of tests/test_battle_claim.py, as they were: a claim, a grey button, a new set, a pop-up ...
    add("a_rank_is_claimed", walk("home_claim", claim_rules()))
    add("a_grey_battle_button_after_the_rewards", walk("home_done2", claim_rules(after_rewards="home_done")))
    add("a_reward_that_is_a_pokemon", walk("home_done2", claim_rules(collect_to="catch")))
    add("the_maximum_number_of_battles", walk("home_battle", claim_rules(then="home_max")))
    add("a_new_set_after_the_rewards", walk("home_done2", claim_rules(after_rewards="home_newset")))
    add("gold_tiles_not_read", walk("home_done2", claim_rules(after_rewards="home_done"), lines={"home_done2": SCREENS["home_done"]["lines"]}))
    add("nothing_to_claim", walk("home_battle", claim_rules()))
    add("claim_then_a_new_set", walk("home_claim", claim_rules(after="home_newset")))
    add("a_new_set_without_a_claim", walk("home_newset", claim_rules()))
    add("the_premium_button_is_never_tapped", walk("home_too_far", claim_rules()))
    add("only_the_premium_button", walk("home_too_far", [r for r in claim_rules() if r[1] != "swipe_up"]))
    add("no_battle_button_at_all", walk("home_empty", claim_rules()))
    add("the_welcome_of_a_new_season", walk("home_battle", claim_rules(then="welcome")))
    add("the_welcome_without_its_button", walk("welcome", claim_rules(), pics={"welcome": ["white"]}))
    add("a_popup_that_only_goes_on", walk("home_battle", claim_rules(then="tutorial")))
    add("a_green_button_that_says_use_this_party", walk("home_battle", claim_rules(then="odd_party")))
    add("a_green_button_that_pays", walk("home_battle", claim_rules(then="coins")))
    add("a_pokemon_as_a_reward_after_the_claim", walk("home_claim", claim_rules(after="catch")))
    add("screens_that_do_not_end", walk("home_claim", claim_rules(after="stuck")))
    add("a_button_that_sells_something", walk("home_claim", claim_rules(after="shop")))
    add("a_claim_button_that_does_not_react", walk("home_claim", claim_rules(claim_works=False)))
    # --- a claim that goes on too long
    add("the_claim_takes_too_long", walk("home_claim", claim_rules(after="stuck"), shot_seconds=9.0))
    add("a_claim_with_the_button_cut_off", walk("home_claim", [["home_claim", "tap", [0.08, 0.94, 0.95, 2.0], "orange_claim"],
                                                             ["orange_claim", "tap", [0.0, 2.0, 0.0, 2.0], "party"]]))
    # --- the buttons of the screens after the claim
    add("claim_buttons_by_colour", walk("home_claim", [["home_claim", "tap", [0.08, 0.94, 0.95, 2.0], "reward_buttons"],
                                                        ["reward_buttons", "tap", [0.33, 0.67, 0.70, 0.76], "party"]]))
    add("claim_a_button_that_buys_is_skipped", walk("home_claim", [["home_claim", "tap", [0.08, 0.94, 0.95, 2.0], "reward_two_buttons"],
                                                                    ["reward_two_buttons", "tap", [0.33, 0.67, 0.70, 0.76], "home_battle"],
                                                                    ["home_battle", "tap", [0.32, 0.71, 0.972, 2.0], "party"]]))
    add("claim_the_word_continue", walk("home_claim", [["home_claim", "tap", [0.08, 0.94, 0.95, 2.0], "reward_next"],
                                                        ["reward_next", "tap", [0.4, 0.6, 0.7, 0.85], "home_battle"],
                                                        ["home_battle", "tap", [0.32, 0.71, 0.972, 2.0], "party"]]))
    add("claim_nothing_to_tap_twice", walk("home_claim", [["home_claim", "tap", [0.08, 0.94, 0.95, 2.0], "reward_nothing"],
                                                           ["reward_nothing", "tap", [0.45, 0.55, 0.25, 0.35], "home_battle"],
                                                           ["home_battle", "tap", [0.32, 0.71, 0.972, 2.0], "party"]]))
    add("claim_by_its_text_only", walk("home_claim_text", [["home_claim_text", "tap", [0.3, 0.4, 0.97, 2.0], "home_battle"],
                                                            ["home_battle", "tap", [0.32, 0.71, 0.972, 2.0], "party"]]))
    add("claim_an_orange_button_not_read", walk("orange_label", [["orange_label", "tap", [0.3, 0.5, 0.95, 2.0], "home_battle"],
                                                                  ["home_battle", "tap", [0.32, 0.71, 0.972, 2.0], "party"]]))
    # --- the BATTLE button
    add("the_battle_button_taps_at_both_sides", walk("home_battle", [["home_battle", "tap", [0.5, 0.6, 0.972, 2.0], "party"]]))
    add("the_battle_button_nothing_happens", walk("home_battle"))
    add("the_battle_label_is_tapped", walk("home_label", [["home_label", "tap", [0.45, 0.55, 0.97, 1.0], "party"]]))
    add("a_label_that_is_too_high", walk("home_label_high", [["home_label_high", "swipe_down", None, "home_scrolled"],
                                                              ["home_scrolled", "tap", [0.32, 0.71, 0.80, 0.85], "party"]]))
    add("the_premium_label_is_never_tapped", walk("home_premium_text", [["home_premium_text", "swipe_up", None, "home_scrolled"],
                                                                         ["home_scrolled", "tap", [0.32, 0.71, 0.80, 0.85], "party"]]))
    add("premium_text_above_the_button", walk("home_premium_above", [["home_premium_above", "swipe_up", None, "home_scrolled"],
                                                                      ["home_scrolled", "tap", [0.32, 0.71, 0.80, 0.85], "party"]]))
    # --- when is a screen quiet: a few of the pixels are another colour, a little or a lot
    add("a_screen_that_changes_a_little", walk("party", pre={"party": [["white"], SMALL, SMALL]}))
    add("a_screen_that_changes_less_than_that", walk("party", pre={"party": [["white"], TINY, TINY]}))
    add("a_screen_that_gets_a_little_darker", walk("party", pre={"party": [["white"], GREY30, GREY30]}))
    add("a_screen_that_hardly_gets_darker", walk("party", pre={"party": [["white"], GREY20, GREY20]}))
    # --- the labels of the buttons
    add("a_popup_button_with_marks_on_it", walk("popup_busy", [["popup_busy", "tap", [0.33, 0.67, 0.83, 0.89], "party"]]))
    add("a_popup_button_with_a_faint_mark", walk("popup_faint", [["popup_faint", "tap", [0.33, 0.67, 0.83, 0.89], "party"]]))
    add("a_popup_button_that_costs_coins", walk("popup_coins", back=False))
    add("a_popup_button_that_collects_coins", walk("popup_collect_coins", [["popup_collect_coins", "tap", [0.33, 0.67, 0.83, 0.89], "party"]], back=False))
    add("a_claim_button_that_is_cut_off_and_busy", walk("orange_busy", [["orange_busy", "tap", [0.3, 0.5, 0.95, 2.0], "home_battle"],
                                                                      ["home_battle", "tap", [0.32, 0.71, 0.972, 2.0], "party"]]))
    add("a_claim_button_that_costs_coins", walk("home_claim", claim_rules(after="reward_coins")))
    add("a_battle_button_of_the_premium_rewards_by_its_label", walk("home_label_premium", [["home_label_premium", "swipe_up", None, "home_scrolled"],
                                                                                         ["home_scrolled", "tap", [0.32, 0.71, 0.80, 0.85], "party"]]))
    add("the_battle_label_does_nothing", walk("home_label"))
    add("a_battle_label_that_is_not_at_the_bottom", walk("home_label_mid", [["home_label_mid", "swipe_down", None, "home_scrolled"],
                                                                           ["home_scrolled", "tap", [0.32, 0.71, 0.80, 0.85], "party"]]))
    add("the_exit_question_with_a_cancel_that_is_misread", walk("exit_misread", [["exit_misread", "tap", [0.30, 0.40, 0.55, 0.62], "home_battle"],
                                                                                ["home_battle", "tap", [0.32, 0.71, 0.972, 2.0], "party"]]))
    add("premium_text_at_the_top_of_the_button", walk("home_premium_edge", [["home_premium_edge", "swipe_up", None, "home_scrolled"],
                                                                         ["home_scrolled", "tap", [0.32, 0.71, 0.80, 0.85], "party"]]))
    # --- from the map to the party screen
    close_menu = [["menu", "tap", [0.45, 0.55, 0.88, 0.92], "map"], ["menu_no_battle", "tap", [0.45, 0.55, 0.88, 0.92], "map"]]
    menu_rules = close_menu + [["map", "tap", [0.4, 0.6, 0.85, 0.95], "menu"], ["menu", "tap", [0.70, 0.77, 0.38, 0.42], "home_battle"],
                  ["home_battle", "tap", [0.32, 0.71, 0.972, 2.0], "league"], ["league", "tap", [0.40, 0.50, 0.30, 0.33], "party"]]
    add("from_the_map_to_the_party_screen", walk("map", menu_rules))
    add("from_the_map_leagues_only", walk("map", menu_rules, args={"leagues_only": True, "stay": False}))
    add("from_the_map_and_back_again", walk("map", menu_rules, args={"stay": False}))
    add("the_menu_takes_the_second_spot", walk("menu", [["menu", "tap", [0.70, 0.77, 0.30, 0.33], "home_battle"],
                                                         ["home_battle", "tap", [0.32, 0.71, 0.972, 2.0], "party"]]))
    add("the_menu_has_no_battle_tile", walk("menu_no_battle", close_menu + [["map", "tap", [0.4, 0.6, 0.85, 0.95], "menu"]]))
    add("the_menu_never_opens_the_battle_screen", walk("menu", close_menu))
    add("the_menu_does_not_stay_open", walk("map"))
    add("the_league_list", walk("league", [["league", "tap", [0.40, 0.50, 0.30, 0.33], "party"]]))
    add("the_league_is_not_on_the_list", walk("league", [], league="Master League"))
    add("the_league_tap_does_not_work", walk("league"))
    add("the_leagues_are_read", walk("league", args={"leagues_only": True, "stay": False}))
    add("no_leagues_are_read", walk("league_empty", args={"leagues_only": True, "stay": False}))
    add("leagues_only_and_the_party_screen_comes", walk("party", [["party", "back", None, "league"]], args={"leagues_only": True, "stay": False}))
    add("leagues_only_and_the_party_screen_stays", walk("party", [], back=False, args={"leagues_only": True, "stay": False}))
    add("the_league_list_of_another_league", walk("league", [["league", "tap", [0.40, 0.50, 0.40, 0.54], "party"]], league="Ultra League"))
    # --- questions and screens in the way
    add("exit_question_cancel", walk("exit", [["exit", "tap", [0.30, 0.40, 0.55, 0.62], "home_battle"],
                                               ["home_battle", "tap", [0.32, 0.71, 0.972, 2.0], "party"]]))
    add("exit_question_without_cancel", walk("exit_no_cancel", [["exit_no_cancel", "back", None, "home_battle"],
                                                                 ["home_battle", "tap", [0.32, 0.71, 0.972, 2.0], "party"]], back=False))
    add("a_battle_is_going_on", walk("exit_battle"))
    add("welcome_that_does_not_go_away", walk("welcome"))
    add("an_unknown_screen_and_back", walk("loading", [["loading", "back", None, "home_battle"],
                                                        ["home_battle", "tap", [0.32, 0.71, 0.972, 2.0], "party"]], back=False))
    add("an_unknown_screen_for_ever", walk("loading", back=False))
    add("an_unknown_screen_for_ever_restart", walk("loading", back=False, args={"restart": True}))
    add("an_unknown_screen_with_text", walk("other_text", back=False))
    add("a_popup_with_ok", walk("popup_ok", [["popup_ok", "tap", [0.33, 0.67, 0.83, 0.89], "party"]]))
    add("a_popup_with_a_green_button_that_is_not_read", walk("popup_unread", [["popup_unread", "tap", [0.33, 0.67, 0.83, 0.89], "party"]], back=False))
    add("a_popup_that_says_use_this_party", walk("popup_use", back=False))
    add("a_popup_that_is_about_buying", walk("popup_buy", back=False))
    add("a_popup_that_says_pass", walk("popup_pass", back=False))
    add("a_popup_with_another_word", walk("popup_odd", back=False))
    add("a_result_screen_still_there", walk("result_next", [["result_next", "tap", [0.45, 0.55, 0.84, 0.89], "party"]]))
    add("a_result_screen_with_a_label", walk("result_label", [["result_label", "tap", [0.45, 0.55, 0.84, 0.89], "party"]]))
    add("a_result_screen_with_a_check_mark", walk("result_check", [["result_check", "tap", [0.45, 0.55, 0.91, 0.95], "party"]]))
    add("a_check_mark_and_a_word_of_the_result", walk("result_check_text", [["result_check_text", "tap", [0.45, 0.55, 0.91, 0.95], "party"]]))
    add("a_check_mark_and_nothing_else", walk("result_check_none", back=False))
    add("popups_that_never_end", walk("popup_ok"))
    # --- the end of the walk
    add("too_many_steps", walk("party", [["party", "back", None, "party"]], args={"leagues_only": True, "stay": False}))
    add("the_caller_stops", walk("loading", back=False, stop_at=2))
    add("out_of_time", walk("loading", back=False, shot_seconds=60.0))
    add("a_phone_that_does_not_answer", walk("home_battle", fail_at=3))
    add("a_phone_that_goes_when_it_walks_back", walk("loading", back=False, fail_at=14))
    add("a_screen_that_flickers", walk("home_battle", [["home_battle", "tap", [0.32, 0.71, 0.972, 2.0], "party"]],
                                       pre={"home_battle": [["white"], ["battle", "home_newset"], ["battle", "home_claim"]]}))
    add("a_screen_that_flickers_for_good", walk("home_battle", [["home_battle", "tap", [0.32, 0.71, 0.972, 2.0], "party"]],
                                                pre={"home_battle": [["white"], ["battle", "home_newset"], ["battle", "home_claim"], ["white"],
                                                                     ["battle", "home_newset"], ["battle", "home_claim"], ["white"],
                                                                     ["battle", "home_newset"]]}))
    # --- the walk back to the map
    add("to_map_already_there", leave("map"))
    add("to_map_from_the_party_screen", leave("party", [["party", "back", None, "exit_battle"], ["exit_battle", "tap", [0.55, 0.65, 0.40, 0.46], "map"]],
                                              args={"leaving_setup": True}))
    add("to_map_no_battle_was_started_but_it_says_no", leave("party", [["party", "back", None, "exit_battle"],
                                                                        ["exit_battle", "tap", [0.55, 0.65, 0.5, 0.6], "map"]]))
    add("to_map_the_yes_button_does_not_work", leave("exit_battle", [], args={"leaving_setup": True}))
    add("to_map_without_a_no", leave("exit_battle_title", [["exit_battle_title", "back", None, "map"]]))
    add("to_map_exit_nothing_found", leave("exit_battle_nothing", [["exit_battle_nothing", "back", None, "map"]]))
    add("to_map_from_the_menu", leave("menu", [["menu", "tap", [0.4, 0.6, 0.85, 0.95], "map"]]))
    add("to_map_the_exit_question", leave("exit", [["exit", "tap", [0.30, 0.40, 0.55, 0.62], "map"]]))
    add("to_map_the_exit_question_without_cancel", leave("exit_no_cancel", [["exit_no_cancel", "back", None, "map"]]))
    add("to_map_by_back", leave("home_battle", BACK_TO_MAP))
    add("to_map_never_gets_there", leave("home_battle"))
    add("to_map_the_last_look_gets_there", leave("home_battle", [["home_battle", "any", None, "map"]], shot_seconds=0.4))
    # --- battles
    fights = [{"result": "win", "seconds": 140.0, "scene": "home_battle"}, {"result": "loss", "seconds": 95.5, "scene": "home_battle"},
              {"result": "win", "seconds": 180.0, "scene": "home_battle", "gave_up": True}]
    battle_rules = [["home_battle", "tap", [0.32, 0.71, 0.972, 2.0], "party"], ["party", "tap", [0.4, 0.6, 0.85, 0.9], "wrong"],
                    ["wrong", "any", None, "wrong"]]
    add("three_battles", run("home_battle", 3, battle_rules, fights))
    add("battles_that_end_on_the_map", run("home_battle", 2, battle_rules,
                                           [dict(f, scene="map") for f in fights]))
    add("a_fight_without_a_result_then_the_fight_is_still_on", run("home_battle", 3, battle_rules, [
        {"result": "", "why": "no screen it knows", "seconds": 60.0, "scene": "fight"},
        {"result": "win", "seconds": 90.0, "scene": "home_battle"}, {"result": "loss", "seconds": 100.0, "scene": "home_battle"}]))
    add("a_fight_with_a_prompt_on_the_screen", run("home_battle", 2, battle_rules, [
        {"result": "", "why": "x", "seconds": 60.0, "scene": "fight_prompt"},
        {"result": "win", "seconds": 90.0, "scene": "home_battle"}]))
    add("a_fight_without_a_result_and_no_fight_on_the_screen", run("home_battle", 2, battle_rules, [
        {"result": "", "why": "lost the screen", "seconds": 60.0, "scene": "home_battle"},
        {"result": "win", "seconds": 90.0, "scene": "home_battle"}]))
    add("the_fight_on_the_screen_has_no_result_either", run("home_battle", 3, battle_rules, [
        {"result": "", "why": "x", "seconds": 60.0, "scene": "fight"}, {"result": "", "why": "y", "seconds": 40.0, "scene": "fight"},
        {"result": "win", "seconds": 90.0, "scene": "home_battle"}]))
    add("two_fights_without_a_result", run("home_battle", 4, battle_rules, [
        {"result": "", "why": "x", "seconds": 60.0, "scene": "home_battle"}, {"result": "", "why": "", "seconds": 40.0, "scene": "home_battle"}]))
    add("a_fight_that_was_stopped", run("home_battle", 4, battle_rules, [{"result": "", "why": "stopped", "seconds": 60.0, "scene": "home_battle"}]))
    add("the_run_time_is_up", run("home_battle", 4, battle_rules, fights, no_more_at=2))
    add("the_caller_stops_a_run", run("home_battle", 4, battle_rules, fights, stop_at=2))
    add("the_caller_stops_a_run_at_the_start", run("home_battle", 4, battle_rules, fights, stop_at=1))
    add("the_caller_stops_after_a_fight_that_ended_badly", run("home_battle", 4, battle_rules, [
        {"result": "", "why": "x", "seconds": 60.0, "scene": "fight"}], stop_at=3))
    add("the_party_screen_is_not_reached", run("loading", 3, [], fights))
    add("the_battles_are_done_today", run("home_done", 3, [], fights))
    add("a_reward_to_catch_leaves_the_screen", run("home_done2", 3, claim_rules(collect_to="catch"), fights))
    add("the_title_is_not_the_league", run("home_battle", 3, [["home_battle", "tap", [0.32, 0.71, 0.972, 2.0], "party_ultra"]], fights,
                                           lines={"party_ultra": [ln("ULTRA LEAGUE", 600, 300), ln("MAX CP PER POKEMON: 2500", 500, 380),
                                                                  ln("USE THIS PARTY", 700, 1930)]}, scenes={"party_ultra": {"pic": ["white"]}}))
    add("a_title_with_a_word_missing", run("league", 1, [["league", "tap", [0.40, 0.50, 0.30, 0.33], "party_short"]], fights,
                                           lines={"party_short": [ln("2026 LEAGUE EDITION", 600, 300), ln("MAX CP PER POKEMON: 1500", 500, 380),
                                                                  ln("USE THIS PARTY", 700, 1930)]}, scenes={"party_short": {"pic": ["white"]}}))
    add("a_title_with_a_word_missing_of_another_league", run("league", 1, [["league", "tap", [0.40, 0.50, 0.30, 0.33], "party_short"]], fights,
                                                              lines={"party_short": [ln("ULTRA LEAGUE EDITION", 600, 300), ln("MAX CP PER POKEMON: 1500", 500, 380),
                                                                                     ln("USE THIS PARTY", 700, 1930)]}, scenes={"party_short": {"pic": ["white"]}}))
    for title in ("GREAT ULTRA EDITION", "LITTLE CUP EDITION", "MASTER LEAGUE EDITION", "ULTRA PREMIER EDITION"):
        add("a_title_with_a_word_missing_" + title.split()[0].lower() + "_" + title.split()[1].lower(), run(
            "league", 1, [["league", "tap", [0.40, 0.50, 0.30, 0.33], "party_x"]], fights,
            lines={"party_x": [ln(title, 600, 300), ln("MAX CP PER POKEMON: 1500", 500, 380), ln("USE THIS PARTY", 700, 1930)]},
            scenes={"party_x": {"pic": ["white"]}}))
    add("a_title_that_is_not_read", run("home_battle", 1, [["home_battle", "tap", [0.32, 0.71, 0.972, 2.0], "party_blind"]], fights,
                                        lines={"party_blind": [ln("USE THIS PARTY", 700, 1930)]}, scenes={"party_blind": {"pic": ["white"]}}))
    add("the_party_screen_without_the_button_word", run("home_battle", 1, [["home_battle", "tap", [0.32, 0.71, 0.972, 2.0], "party_plain"]], fights,
                                                         lines={"party_plain": [ln("GREAT LEAGUE", 600, 300), ln("MAX CP PER POKEMON: 1500", 500, 380),
                                                                                ln("CHOOSE YOUR PARTY", 500, 800)]},
                                                         scenes={"party_plain": {"pic": ["white"]}}))
    add("the_run_through_the_leagues", run("league", 2, [["league", "tap", [0.40, 0.50, 0.30, 0.33], "party"]] + [
        ["home_battle", "tap", [0.32, 0.71, 0.972, 2.0], "league"]], [dict(f, scene="home_battle") for f in fights]))
    add("a_fight_that_is_interrupted", run("home_battle", 3, battle_rules, [{"raise": "interrupt"}]))
    add("a_fight_that_fails_with_an_error", run("home_battle", 3, battle_rules, [{"raise": "error"}]))
    add("a_fight_that_fails_the_walk_back_restarts", run("home_battle", 1, battle_rules, [
        {"result": "win", "seconds": 90.0, "scene": "loading"}], back=False))
    add("a_run_without_battles", run("home_battle", 0, battle_rules, fights))
    return out


# ---------------------------------------------------------------------- the recording

class Clock:
    t = START

    @staticmethod
    def monotonic():
        return Clock.t

    @staticmethod
    def time():
        return Clock.t

    @staticmethod
    def sleep(seconds):
        Clock.rec.add("sleep", seconds)
        Clock.t += seconds

    @staticmethod
    def strftime(*a):
        return "2026-11-22"


class Rec:
    def __init__(self):
        self.events = []
        self.stops = 0
        self.no_mores = 0
        self.fights = 0
        self.counts = {}

    def add(self, kind, *rest):
        self.events.append([kind, Clock.t] + list(rest))


def mean(img):
    return round(float(img.mean()), 2)


class FakeSubprocess:
    """The text reader (the tesseract program) of gamebot.button_label(): it is given the picture and answers with the label of the
    screen.  What it was given is part of the story."""
    TimeoutExpired = subprocess.TimeoutExpired

    def __init__(self, rec, world):
        self.rec, self.world = rec, world

    def run(self, cmd, env=None, input=None, capture_output=None, timeout=None):
        assert cmd == ["tesseract", "stdin", "stdout", "--psm", "7"], cmd
        img = cv2.imdecode(np.frombuffer(input, np.uint8), cv2.IMREAD_UNCHANGED)
        label = scene_of(self.world, "label", "")
        digest = hashlib.sha1(np.ascontiguousarray(img).tobytes()).hexdigest()
        LABELS[digest] = base64.b64encode(input).decode("ascii")
        self.rec.add("ocr_line", img.shape[0], img.shape[1], 1, mean(img), label, digest)
        return types.SimpleNamespace(stdout=(label + "\n").encode())


def normal(info):
    return {"ok": bool(info["ok"]), "why": info["why"], "title": info["title"], "members": list(info["members"]),
            "use_spots": [list(p) for p in info["use_spots"]], "chosen": info.get("chosen", ""), "leave": bool(info.get("leave")),
            "catch": bool(info.get("catch")), "done_today": bool(info.get("done_today")),
            "leagues": [[t, c] for t, c in info.get("leagues", [])]}


def record(spec):
    """Plays one story on the fake phone; returns the list of events."""
    Clock.t = START
    rec = Rec()
    Clock.rec = rec
    # (the screens of the story: its own lines and pictures over the ones above)
    for name, extra in spec.get("scenes", {}).items():
        SCREENS[name] = extra
    world = World(spec)
    saved = {n: getattr(G, n) for n in ("time", "battle_league", "log", "save_async", "ocr_lines", "ocr_line", "screen_class", "day_count",
                                        "battles_done_today", "fight_battle", "subprocess")}
    saved_s = {n: getattr(S, n) for n in ("tap", "back", "swipe", "screenshot", "on_map", "restart_game", "recheck_shot_mode")}
    saved_be = BE.load_team
    try:
        G.time = Clock
        G.battle_league = lambda: spec["league"]
        G.log = lambda text: rec.add("log", text)
        G.save_async = lambda name, img: rec.add("save", name)
        G.subprocess = FakeSubprocess(rec, world)
        BE.load_team = lambda: [types.SimpleNamespace(name=n, label=n) for n in spec["names"]]

        def ocr_lines(img, y0=0, y1=None, scale=1.0):
            lines = world.lines(y0)
            rec.add("ocr", img.shape[0], img.shape[1], y0, y1, scale, mean(img), lines)
            return lines

        def ocr_line(img, lines=1):
            text = scene_of(world, "words", "")
            rec.add("ocr_line", img.shape[0], img.shape[1], lines, mean(img), text, None)
            return text

        def screen_class(img):
            answer = scene_of(world, "class", ["menusScreen", 0.8])
            rec.add("class", answer[0], answer[1])
            return answer[0], answer[1]

        def day_count(key):
            rec.counts[key] = rec.counts.get(key, 0) + 1
            text = "(today: %d %s)" % (rec.counts[key], key)
            rec.add("day_count", key, text)
            return text

        def mark_done(mark=False):
            if mark:
                rec.add("mark_done")
                return True
            return False

        def fight(beat=None, stop=None, team=None, use_spots=None, stream=None):
            f = spec["fights"][min(rec.fights, len(spec["fights"]) - 1)]
            rec.fights += 1
            spots = None if use_spots is None else [list(p) for p in use_spots]
            if f.get("raise") == "interrupt":
                rec.add("fight", spots, None, "interrupt")
                raise KeyboardInterrupt()
            if f.get("raise") == "error":
                rec.add("fight", spots, None, "error")
                raise RuntimeError("boom")
            res = {"result": f["result"], "why": f.get("why", ""), "seconds": f["seconds"], "gave_up": bool(f.get("gave_up"))}
            rec.add("fight", spots, res, "")
            Clock.t += f["seconds"]
            if "scene" in f:
                world.go(f["scene"])
            return res

        def screenshot(on_grab=None):
            world.shots += 1
            if spec.get("fail_at") == world.shots:
                rec.add("screenshot_fail", "the phone did not answer")
                raise RuntimeError("the phone did not answer")
            Clock.t += spec["shot_seconds"]
            pic = world.picture()
            rec.add("screenshot", pic)
            return make_picture(pic)

        def tap(x, y, ms=120):
            rec.add("tap", x, y)
            world.act("tap", x / float(W), y / float(H))

        def swipe(x1, y1, x2, y2, ms=300):
            rec.add("swipe", x1, y1, x2, y2, ms)
            if y2 < y1 - 0.08 * H:
                world.act("swipe_down")
            elif y2 > y1 + 0.08 * H:
                world.act("swipe_up")

        def back():
            rec.add("back")
            world.act("back")

        def on_map(img):
            answer = bool(scene_of(world, "map", False))
            rec.add("on_map", answer)
            return answer

        def restart_game():
            rec.add("restart")

        G.ocr_lines, G.ocr_line, G.screen_class, G.day_count = ocr_lines, ocr_line, screen_class, day_count
        G.battles_done_today, G.fight_battle = mark_done, fight
        S.tap, S.back, S.swipe, S.screenshot, S.on_map = tap, back, swipe, screenshot, on_map
        S.restart_game = restart_game
        S.recheck_shot_mode = lambda: rec.add("recheck")

        def beat():
            rec.add("beat")

        def stop():
            rec.stops += 1
            answer = spec.get("stop_at") is not None and rec.stops >= spec["stop_at"]
            rec.add("stop", answer)
            return answer

        def no_more():
            rec.no_mores += 1
            answer = spec.get("no_more_at") is not None and rec.no_mores >= spec["no_more_at"]
            rec.add("no_more", answer)
            return answer

        a = spec["args"]
        try:
            if spec["call"] == "open_menu":
                res = normal(G.battle_open_menu(beat, stop, restart=a["restart"], stay=a["stay"], leagues_only=a["leagues_only"]))
            elif spec["call"] == "to_map":
                res = bool(G._battle_to_map(beat, a["leaving_setup"]))
            else:
                run_ = G.battle_run(beat, stop, a["count"], team=[], no_more=no_more)
                res = {"fought": run_["fought"], "wins": run_["wins"], "leave": run_.get("leave"), "catch": run_.get("catch"),
                       "done_today": bool(run_.get("done_today"))}
            rec.add("result", res)
        except KeyboardInterrupt:
            rec.add("raised", "interrupt", "")
        except Exception as e:  # noqa: BLE001
            rec.add("raised", "error", str(e))
        return rec.events
    finally:
        for n, v in saved.items():
            setattr(G, n, v)
        for n, v in saved_s.items():
            setattr(S, n, v)
        BE.load_team = saved_be
        for name in spec.get("scenes", {}):
            SCREENS.pop(name, None)


CONSTANTS = ("BATTLE_NAV_STEPS", "BATTLE_NAV_SECONDS", "COLLECT_TAPS", "CLAIM_TAPS", "CLAIM_STEPS", "CLAIM_SECONDS", "CLAIM_TAP_ON",
             "HOME_SCROLL", "HOME_SCROLL_MS", "HOME_TAPS", "POPUP_TAPS", "WELCOME_BUTTON", "MENU_BTN", "TH_CLASS")


def constants():
    out = {}
    for name in CONSTANTS:
        value = getattr(G, name)
        flat = []
        for x in (value if isinstance(value, (tuple, list)) else [value]):
            flat += [float(y) for y in x] if isinstance(x, (tuple, list)) else [float(x)]
        out[name] = flat
    return out


def capture():
    LABELS.clear()
    cases = []
    for item in stories():
        cases.append({"id": item["id"], "spec": item["spec"], "events": record(item["spec"])})
    return cases


def text(cases=None):
    if cases is None:
        cases = capture()
    doc = {"cv2": cv2.__version__, "start": START, "constants": constants(), "cases": cases, "labels": dict(sorted(LABELS.items()))}
    return json.dumps(doc, separators=(",", ":"), sort_keys=True)


def check():
    with open(OUT, "rb") as handle:
        packed = handle.read()
    old = json.loads(zlib.decompress(packed[4:]))
    LABELS.clear()
    new_cases = [{"id": c["id"], "spec": c["spec"], "events": record(c["spec"])} for c in old["cases"]]
    raw = text(new_cases).encode("utf-8")
    if len(packed) > 4 and struct.unpack(">I", packed[:4])[0] == len(raw) and zlib.decompress(packed[4:]) == raw:
        print("flow_golden.json.qz is what the walk does")
        return 0
    new = json.loads(raw)
    if old.get("constants") != new["constants"]:
        names = [k for k in new["constants"] if old.get("constants", {}).get(k) != new["constants"][k]]
        print("flow_golden.json.qz is NOT what the walk does: the numbers " + ", ".join(names) + " changed")
        return 1
    differ = [a["id"] for a, b in zip(old["cases"], new["cases"]) if json.dumps(a["events"]) != json.dumps(b["events"])]
    if old["cv2"] == new["cv2"] or len(differ) > int(0.05 * len(old["cases"])):
        print("flow_golden.json.qz is NOT what the walk does: " + ", ".join(differ[:8]))
        return 1
    print("flow_golden.json.qz was made with OpenCV %s, this is %s: %d of %d stories go another way (allowed: %d)"
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
    print("wrote %s: %d stories, %d events, %d bytes of JSON, packed to %d" % (
        OUT, len(doc["cases"]), sum(len(c["events"]) for c in doc["cases"]), len(raw), os.path.getsize(OUT)))
