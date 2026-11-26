#!/usr/bin/env python3
"""Makes tests/fixtures/nav_golden.json: what battle_nav.py answers for a lot of screens, as the file that the
C++ port of it (SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoNav.cpp) is tested against.

    python3 tools/make_nav_golden.py            writes the file
    python3 tools/make_nav_golden.py --check    says whether the file is what battle_nav.py answers now

The screens are the OCR lines of real screenshots (tests/fixtures/battle_screens.json), a few made-up ones
that look like what OCR does to a screen (a word glued to the next, a letter misread, a line gone, the
screen moved), and some with accents.  The cases do not depend on the order of anything but this file's seed."""
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import battle_nav as bn  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
OUT = os.path.join(FIXTURES, "nav_golden.json")

CONFUSED = {"O": "0", "0": "O", "I": "1", "1": "I", "E": "F", "S": "5", "5": "S", "B": "8", "8": "B", "A": "4", "L": "I"}
LEAGUES = ["", "Great League", "Ultra League", "Master League", "GO Laic Cup", "Great"]
TARGETS = ["USE THIS PARTY", "ITEMS", "POKEMON", "BATTLE", "WELCOME", "LONGEST", "STREAK", "MAXIMUM", "BATTLES", "TODAY",
           "COLLECT", "CLAIM", "SWITCH", "REMAINING", "INCOMING", "EFFORT", "VICTORY", "WINNER", "PREMIUM", "LEAGUE",
           "RISE THROUGH THE RANKS", "GO BATTLE LEAGUE", "CHOOSE YOUR PARTY", "SETTINGS", "SHOP", "POKEDEX"]
SYNTHETIC_TEXTS = [
    "", "OK", "okay", "LET'S GO!", "LETS GO", "CLAIM REWARD!", "CONTINUE", "NEXT", "DONE", "CLOSE", "GOT IT", "Got it!",
    "USE THIS PARTY", "YES", "NO", "JOIN GROUP", "BUY NOW", "SHOP", "COINS", "EXIT", "SHARE", "PREMIUM PASS", "PARTY",
    "GOOD EFFORT!", "GOOD EFFORT", "YOU WIN!", "YOU WIN", "YOUWIN", "WIN", "WINS", "GOOD", "GOOD WIN", "VICTORY",
    "G00D EFF0RT", "Y0U W1N", "NEXT BATTLE", "POKÉMON", "Poké Ball", "ATTACK INCOMING", "NOT NOW", "O K", "CL AIM",
    "COLLECT 3", "CLAIM RANK REWARDS!", "CONT1NUE", "NEXT.", "d0ne", "LEAVE", "QUIT", "EXCHANGE", "TRANSFER",
    "Y", "?", "12", "CP1493", "CP 1493", "1493", "CPE1494",
]


def line(text, x, y):
    words = text.split()
    return [text, x, y, [[w, x + 60 * i, y] for i, w in enumerate(words)]]


def rebuild(l):
    """A line whose text is the words, the way OCR gives it."""
    return [" ".join(w[0] for w in l[3]), l[1], l[2], l[3]]


def mutations(lines, rnd):
    """Some ways OCR goes wrong on a screen, each a new list of lines."""
    out = []
    if len(lines) > 1:
        gone = rnd.randrange(len(lines))
        out.append([l for i, l in enumerate(lines) if i != gone])
    for _ in range(2):
        copy = json.loads(json.dumps(lines))
        for _try in range(4):
            if not copy:
                break
            l = rnd.choice(copy)
            if not l[3]:
                continue
            w = rnd.choice(l[3])
            spots = [i for i, c in enumerate(w[0]) if c in CONFUSED]
            if spots:
                i = rnd.choice(spots)
                w[0] = w[0][:i] + CONFUSED[w[0][i]] + w[0][i + 1:]
        out.append([rebuild(l) for l in copy])
    copy = json.loads(json.dumps(lines))
    for l in copy:
        if len(l[3]) >= 2 and rnd.random() < 0.5:
            a, b = l[3][0], l[3][1]
            l[3] = [[a[0] + b[0], a[1], a[2]]] + l[3][2:]
    out.append([rebuild(l) for l in copy])
    out.append([[l[0], l[1], l[2] + 150, [[w[0], w[1], w[2] + 150] for w in l[3]]] for l in lines])
    out.append([[l[0], l[1], max(l[2] - 220, 0), [[w[0], w[1], max(w[2] - 220, 0)] for w in l[3]]] for l in lines])
    return out


def made_up():
    """Screens of the fight and of the result, as the tests of battle_nav make them."""
    return {
        "fight_question_shield": [line("ATTACK INCOMING!", 884, 1100), line("USE A PROTECT SHIELD?", 884, 1180)],
        "fight_question_none": [line("NO PROTECT SHIELDS REMAINING!", 884, 1100)],
        "fight_question_switch": [line("SWITCH IN A NEW POKÉMON?", 884, 1100), line("CP 1494 CPE1450 1380", 900, 1500)],
        "fight_names": [line("NOCTOWL CP 1497", 300, 160), line("CP 1493 CRAMORANT", 1400, 160), line("TOXAPEX CP1488", 300, 260)],
        "fight_buttons": [line("SURF", 400, 2000), line("WEATHER BALL", 1300, 2000)],
        "result_loss": [line("GOOD EFFORT!", 884, 700), line("NEXT BATTLE", 884, 1900)],
        "result_win": [line("YOU WIN!", 884, 700), line("NEXT BATTLE", 884, 1900)],
        "result_win_split": [line("YOU W IN", 884, 700)],
        "result_research": [line("WIN 30 TRAINER BATTLES", 800, 900)],
        "max_battles": [line("YOU'VE REACHED THE MAXIMUM NUMBER OF BATTLES FOR TODAY.", 884, 1950)],
        "claim": [line("CLAIM RANK REWARDS!", 884, 1900), line("BATTLE", 884, 150)],
        "collect": [line("COLLECT", 300, 1750), line("COLLECT", 900, 1750), line("COLLECT", 1500, 1750), line("BATTLE", 884, 2165)],
        "rewards_premium": [line("PREMIUM REWARDS", 884, 1200), line("BATTLE", 884, 1800)],
        "shop": [line("SHOP", 884, 400), line("BUY 100 POKECOINS", 884, 900), line("OK", 884, 1900)],
        "leagues": [line("CHOOSE YOUR LEAGUE", 884, 150), line("GREAT LEAGUE", 1000, 600), line("MAX CP PER POKEMON: 1.500", 1000, 700),
                    line("ULTRA LEAGUE", 1000, 1000), line("MAX CP PER POKEMON: 2.500", 1000, 1100),
                    line("MASTER LEAGUE: MEGA", 1000, 1400), line("EDITION", 1000, 1470), line("MAX CP PER POKEMON: NO LIMIT", 1000, 1550),
                    line("2026 GO LAIC CUP", 1000, 1800), line("MAX CP PER POKEMON 1500", 1000, 1870), line("SEE WHAT IS COMING NEXT", 600, 2100)],
        "exit_battle": [line("EXIT THE TRAINER BATTLE?", 884, 800), line("NO", 884, 1400)],
        "exit_battle_no_no": [line("EXIT THE TRAINER BATTLE?", 884, 800)],
        "exit_game": [line("DO YOU WANT TO EXIT POKÉMON GO?", 884, 800), line("CANCEL", 600, 1300)],
        "party_ok": [line("2026 GO LAIC CUP: GREAT LEAGUE EDITION", 900, 761), line("MAX CP 1500", 900, 840), line("CHOOSE YOUR PARTY", 900, 1161),
                     line("SOLROCK DUBWOOL VOLBEAT", 900, 1820), line("USE THIS PARTY", 900, 1930)],
        "party_glued": [line("2026 GO LAIC CUP: GREAT LEAGUE EDITION", 900, 761), line("CHOOSE YOURPARTY", 900, 1161),
                        line("RECOMMENDED BATTLE PARTY =", 900, 1315), line("SOLROCK DUBWOOL VOLBEAT", 900, 1820)],
        "empty": [],
    }


def build():
    rnd = random.Random(20261126)
    with open(os.path.join(FIXTURES, "battle_screens.json"), encoding="utf-8") as handle:
        real = json.load(handle)
    screens = {}
    for name, lines in real.items():
        lines = [[t, x, y, [list(w) for w in ws]] for t, x, y, ws in lines]
        screens[name] = lines
        for i, m in enumerate(mutations(lines, rnd)):
            screens["%s#%d" % (name, i + 1)] = m
    for name, lines in made_up().items():
        screens[name] = lines
        for i, m in enumerate(mutations(lines, rnd)[:2]):
            screens["%s#%d" % (name, i + 1)] = m

    def tup(lines):
        return [(t, x, y, [tuple(w) for w in ws]) for t, x, y, ws in lines]

    def jsonable(value):
        if isinstance(value, tuple):
            return [jsonable(v) for v in value]
        if isinstance(value, list):
            return [jsonable(v) for v in value]
        if isinstance(value, dict):
            return {k: jsonable(v) for k, v in value.items()}
        return value

    cases = []

    def add(fn, out, **args):
        cases.append(dict(fn=fn, out=jsonable(out), **args))

    names = ["NOCTOWL", "Cramorant", "Toxapex", "Solrock", "Dubwool", "VOLBEAT", "Ho-Oh", ""]
    for sid, lines in screens.items():
        t = tup(lines)
        add("reads", bn.reads(t), screen=sid, n=150)
        add("reads", bn.reads(t, 40), screen=sid, n=40)
        for k in (1.0, 0.5):
            add("menu_battle_spots", bn.menu_battle_spots(t, k), screen=sid, k=k)
            add("home_battle_spots", bn.home_battle_spots(t, k), screen=sid, k=k)
            add("claim_label", bn.claim_label(t, k), screen=sid, k=k)
            add("next_words", bn.next_words(t, k), screen=sid, k=k)
            add("exit_battle_spots", bn.exit_battle_spots(t, k), screen=sid, k=k)
            add("party_use_spots", bn.party_use_spots(t, k), screen=sid, k=k)
            add("party_title", bn.party_title(t, k), screen=sid, k=k)
            add("screen_kind", bn.screen_kind(t, False, "", k), screen=sid, k=k, league="", on_map=False)
        for league in LEAGUES:
            add("screen_kind", bn.screen_kind(t, False, league), screen=sid, k=1.0, league=league, on_map=False)
            add("league_lines", bn.league_lines(t, league), screen=sid, league=league)
        add("screen_kind", bn.screen_kind(t, True), screen=sid, k=1.0, league="", on_map=True)
        add("read_leagues", bn.read_leagues(t), screen=sid, width=1768)
        add("read_leagues", bn.read_leagues(t, 1080), screen=sid, width=1080)
        add("max_battles_today", bn.max_battles_today(t), screen=sid)
        add("collect_spots", bn.collect_spots(t, 2208), screen=sid, height=2208)
        add("collect_spots", bn.collect_spots(t, 1104), screen=sid, height=1104)
        add("danger_words", bn.danger_words(t), screen=sid)
        for y in (300, 1200, 2000):
            add("premium_above", bn.premium_above(t, y), screen=sid, y=y)
        add("battle_words", bn.battle_words(t), screen=sid)
        add("party_members", bn.party_members(t, names), screen=sid, names=names)
        add("question_kind", bn.question_kind(t), screen=sid)
        add("name_box", bn.name_box(t), screen=sid)
        add("popup_tiles", bn.popup_tiles(t), screen=sid)
        add("button_texts", bn.button_texts(t, 1768), screen=sid, width=1768)
        add("button_texts", bn.button_texts(t, 1080), screen=sid, width=1080)
        add("result_kind", bn.result_kind(t), screen=sid)
    for text in SYNTHETIC_TEXTS:
        add("keep_off_label", bn.keep_off_label(text), text=text)
        add("go_on_label", bn.go_on_label(text), text=text)
        add("result_word", bn.result_word(text), text=text)
        add("plain", bn._plain(text), text=text)
        add("league_words", bn.league_words(text), text=text)
    # like(): every word of every real screen against the words the bot looks for, and some misreadings
    words = sorted({w[0] for lines in real.values() for l in lines for w in l[3]})
    pairs = set()
    for w in words:
        for target in TARGETS:
            for th in (0.8, 0.75, 0.7):
                if bn.like(w, target, th) or rnd.random() < 0.02:
                    pairs.add((w, target, th))
    for target in TARGETS:
        for i in range(len(target)):
            pairs.add((target[:i] + target[i + 1:], target, 0.8))
            pairs.add((target[:i] + "X" + target[i + 1:], target, 0.8))
            pairs.add((target[:i] + target[i] + target[i:], target, 0.8))
    for w, target, th in sorted(pairs):
        add("like", bn.like(w, target, th), word=w, target=target, th=th)
    return {"about": "Made by tools/make_nav_golden.py from battle_nav.py: what it answers. Do not edit.",
            "screens": screens, "cases": cases}


def text():
    return json.dumps(build(), ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n"


if __name__ == "__main__":
    made = text()
    if "--check" in sys.argv:
        with open(OUT, encoding="utf-8") as handle:
            same = handle.read() == made
        print("nav_golden.json is" + (" " if same else " NOT ") + "what battle_nav.py answers")
        sys.exit(0 if same else 1)
    with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(made)
    print("wrote %s: %d bytes" % (OUT, len(made.encode("utf-8"))))
