#!/usr/bin/env python3
"""Reading the GO Battle League screens: OCR lines in, decisions out.

This module does not touch the phone and does not import OpenCV, so it can be
tested anywhere.  gamebot.py reads the screen (OCR) and calls these functions to
find out *which* screen it is looking at and *where* to tap.

The way from the map to a battle:

    map -> main menu (Poké Ball) -> BATTLE tile -> Battle screen (tabs BATTLE and
    PARTY, card "GO BATTLE LEAGUE" with a BATTLE button) -> [league list] ->
    party screen ("CHOOSE YOUR PARTY", button "USE THIS PARTY")

`lines` is what gamebot.ocr_lines() returns: [(TEXT, x, y, [(word, x, y), ...]), ...]
in upper case, with positions in pixels of the full screen.  `k` is the screen
height divided by 2208 (the Galaxy Z Fold3's inner display, 1768 x 2208), so the
same positions work on a differently sized screenshot.
"""
import difflib
import re

SCREEN_H = 2208
ICON_DY = 195            # main menu: the round tile sits this far below its label
HOME_BUTTON_Y = 1700     # Battle screen: the BATTLE button is in the lowest part
# Battle screen: where the green BATTLE button is when its label is not read (the
# round close button floats in the middle of its top edge, so tap left or right of it)
HOME_BUTTON_FALLBACK = [(650, 2165), (1120, 2165)]
MENU_WORDS = ("SETTINGS", "POKEDEX", "BATTLE", "SHOP", "POKEMON", "ITEMS")


def like(word, target, th=0.8):
    return difflib.SequenceMatcher(None, word, target).ratio() >= th


def words_of(lines):
    return [(w, x, y) for _t, _x, _y, ws in lines for w, x, y in ws]


def text_of(lines):
    return " ".join(t for t, _x, _y, _ws in lines)


def reads(lines, n=150):
    """For the log: the words OCR read on a screen."""
    seen = []
    for w, _x, _y in words_of(lines):
        if w not in seen:
            seen.append(w)
    return " ".join(seen)[:n] or "nothing"


def _phrase(lines, phrase, th=0.8):
    """True when the words of `phrase` follow each other in one OCR line (each
    word may be misread a little)."""
    want = phrase.split()
    for _t, _x, _y, ws in lines:
        have = [w for w, _x2, _y2 in ws]
        for i in range(len(have) - len(want) + 1):
            if all(like(have[i + j], want[j], th) for j in range(len(want))):
                return True
    return False


def _has(lines, word, th=0.8):
    return any(like(w, word, th) for w, _x, _y in words_of(lines))


def _norm(text):
    return re.sub(r"[^A-Z0-9 ]+", " ", text.upper()).split()


def league_words(league):
    """The words of the league name the user typed ('Great League' -> GREAT LEAGUE)."""
    return [w for w in _norm(league) if len(w) > 1]


def league_lines(lines, league, th=0.8):
    """OCR lines that show the league name: [(line, tap_x, tap_y)] best first.
    All words of the name must be in the line (misreads allowed)."""
    want = league_words(league)
    out = []
    if not want:
        return out
    for t, _x, y, ws in lines:
        have = [w for w, _x2, _y2 in ws]
        if all(any(like(h, w, th) for h in have) for w in want):
            xs = [x for _w, x, _y2 in ws]
            out.append((t, sum(xs) // len(xs), y))
    return out


def screen_kind(lines, on_map=False, league="", k=1.0):
    """What is on the screen?

    map        the game map (no text needed, `on_map` comes from the picture)
    party      'CHOOSE YOUR PARTY' / 'USE THIS PARTY'
    home       the Battle screen with the GO BATTLE LEAGUE card
    menu       the main menu (Poké Ball): ITEMS and POKÉMON side by side
    exit       'Do you want to exit Pokémon GO?'
    exit_battle  'Exit the Trainer Battle?' (we are inside a fight: answer NO)
    league     any other screen that shows the wanted league's name
    other      anything else (loading, a pop-up, ...)
    """
    if on_map:
        return "map"
    if _phrase(lines, "USE THIS PARTY") or _phrase(lines, "CHOOSE YOUR PARTY"):
        return "party"
    if _phrase(lines, "GO BATTLE LEAGUE") or (
            _has(lines, "LONGEST") and _has(lines, "STREAK")) or (
            _has(lines, "STARDUST") and _has(lines, "EARNED")):
        return "home"
    ws = words_of(lines)
    for w, x, y in ws:
        if like(w, "ITEMS", 0.8) and 1250 * k < y < 1700 * k and x > 884 * k:
            if any(like(w2, "POKEMON", 0.8) and abs(y2 - y) < 80 * k and x2 < 884 * k
                   for w2, x2, y2 in ws):
                return "menu"
    if sum(1 for m in MENU_WORDS if any(like(w, m, 0.8) for w, _x, _y in ws)) >= 4:
        return "menu"                         # most of the tile names are read
    text = text_of(lines)
    if "EXIT" in text and "TRAINER BATTLE" in text:
        return "exit_battle"
    if "EXIT" in text and ("CANCEL" in text or "POK" in text):
        return "exit"
    if league and league_lines(lines, league):
        return "league"
    return "other"


def menu_battle_spots(lines, k=1.0):
    """Where to tap the BATTLE tile of the main menu: the round button below its
    label first, then the label itself, then a bit higher.  [] when the label is
    not found (it sits in the upper right, above the ITEMS tile)."""
    found = sorted([(x, y) for w, x, y in words_of(lines)
                    if like(w, "BATTLE", 0.8) and x > 884 * k and 450 * k < y < 1250 * k],
                   key=lambda p: -p[0])
    if not found:
        return []
    x, y = found[0]
    return [(x, y + int(ICON_DY * k)), (x, y), (x, y + int((ICON_DY - 45) * k))]


def home_battle_spots(lines, k=1.0):
    """Where to tap the big BATTLE button at the bottom of the Battle screen (the
    tab at the top and the card title also contain the word BATTLE, they are
    higher up).  The button sits close to the bottom edge, so after the label (and
    a bit above it) two fixed spots on the green button are tried: they are
    used when the label is not read."""
    found = sorted([(x, y) for w, x, y in words_of(lines)
                    if like(w, "BATTLE", 0.8) and y > HOME_BUTTON_Y * k],
                   key=lambda p: -p[1])
    spots = []
    if found:
        x, y = found[0]
        spots += [(x, y), (x, y - int(45 * k))]
    spots += [(int(x * k), int(y * k)) for x, y in HOME_BUTTON_FALLBACK]
    return spots


def party_title(lines, k=1.0):
    """The league name on the party screen (the big title above 'Max CP per
    Pokémon'), '' when it is not found."""
    for i, (t, _x, y, _ws) in enumerate(lines):
        if "MAX CP" in t and i > 0:
            return lines[i - 1][0]
    return ""


def party_members(lines, names):
    """Which of `names` (species names of the team) are on the party screen."""
    text = " ".join(_norm(text_of(lines)))
    out = []
    for n in names:
        key = " ".join(_norm(n))
        if key and (key in text or any(like(w, key, 0.8) for w in text.split())):
            out.append(n)
    return out
