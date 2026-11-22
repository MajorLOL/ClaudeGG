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
import unicodedata

SCREEN_H = 2208
ICON_DY = 195            # main menu: the round tile sits this far below its label
HOME_BUTTON_Y = 1700     # Battle screen: the BATTLE button is in the lowest part
# Battle screen: where the green BATTLE button is when its label is not read (the
# round close button floats in the middle of its top edge, so tap left or right of it)
HOME_BUTTON_FALLBACK = [(650, 2165), (1120, 2165)]
# 'Exit the Trainer Battle?': YES is white text on a green button (OCR does not read it), NO is plain text.
# YES sits this far above NO, and this far below the question; the buttons are big, so a few dozen px off is fine
YES_ABOVE_NO = 290
YES_BELOW_TITLE = 310
EXIT_YES_FALLBACK = (884, 1110)
MENU_WORDS = ("SETTINGS", "POKEDEX", "BATTLE", "SHOP", "POKEMON", "ITEMS")
# The green USE THIS PARTY button at the bottom of the party screen: where it is when its label is not read
PARTY_BUTTON_FALLBACK = (884, 1930)


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
    welcome    'Welcome to the GO Battle League' (the first battle of a season): a pop-up with LET'S GO!
    home       the Battle screen with the GO BATTLE LEAGUE card
    menu       the main menu (Poké Ball): ITEMS and POKÉMON side by side
    exit       'Do you want to exit Pokémon GO?'
    exit_battle  'Exit the Trainer Battle?' (we are inside a fight: answer NO)
    league     the league list ('CHOOSE YOUR LEAGUE') or any other screen that shows the wanted league's name
    other      anything else (loading, a pop-up, ...)
    """
    if on_map:
        return "map"
    if _phrase(lines, "USE THIS PARTY") or _phrase(lines, "CHOOSE YOUR PARTY"):
        return "party"
    if (_has(lines, "WELCOME") and _has(lines, "BATTLE")) or _phrase(lines, "RISE THROUGH THE RANKS", 0.75):
        return "welcome"                      # (before 'home': its title has GO BATTLE LEAGUE in it too)
    if _phrase(lines, "GO BATTLE LEAGUE") or (
            _has(lines, "LONGEST") and _has(lines, "STREAK")) or (
            _has(lines, "STARDUST") and _has(lines, "EARNED")) or (
            _phrase(lines, "REWARD TIER") or _phrase(lines, "BASIC REWARDS") or _phrase(lines, "PREMIUM REWARDS")):
        return "home"                         # (the last ones: the same screen scrolled down, a new set starts)
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
    if _phrase(lines, "CHOOSE YOUR LEAGUE") or (league and league_lines(lines, league)):
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


CLAIM_WORDS = ("CLAIM", "COLLECT")
# Labels of buttons that take a reward screen one step further (tapped on the screens after CLAIM RANK REWARDS!)
NEXT_WORDS = CLAIM_WORDS + ("CONTINUE", "OK", "OKAY", "NEXT", "DONE", "CLOSE")


def max_battles_today(lines):
    """True when the screen says "You've reached the maximum number of battles for today." (the pink banner
    of the Battle screen after a tap on BATTLE when all the sets of the day are played)."""
    words = {_plain(w) for w, _x, _y in words_of(lines)}
    return (any(like(w, "MAXIMUM", 0.8) for w in words)
            and any(like(w, "BATTLES", 0.8) for w in words)
            and any(like(w, "TODAY", 0.75) for w in words))


def collect_spots(lines, height):
    """[(x, y)] left to right: where to tap the reward tiles of the Battle screen that say COLLECT under them
    (gold tiles: the rewards of the wins of a set).  The tile is tapped a little above its label."""
    out = [(int(x), int(y - 0.035 * height)) for w, x, y in words_of(lines)
           if y > 0.75 * height and like(_plain(w), "COLLECT", 0.8)]
    return sorted(out)


def claim_label(lines, k=1.0):
    """The text of the button at the bottom of the Battle screen when it asks to claim something before the
    next battle ('CLAIM RANK REWARDS!'), '' when no such text is read (white text on a coloured button is
    often not read: the colour of the button is the other sign, see battle_vision.home_button)."""
    for t, _x, y, ws in lines:
        if y > HOME_BUTTON_Y * k and any(like(_plain(w), c, 0.8) for w, _x2, _y2 in ws for c in CLAIM_WORDS):
            return t
    return ""


def next_words(lines, k=1.0):
    """[(word, x, y)] lowest first: words that are the label of a button to go on with (CLAIM, OK, CONTINUE
    ...) in the lower two thirds of the screen."""
    out = [(w, x, y) for w, x, y in words_of(lines)
           if y > SCREEN_H * k / 3.0 and any(_plain(w) == n or (len(n) > 3 and like(_plain(w), n, 0.85)) for n in NEXT_WORDS)]
    return sorted(out, key=lambda t: -t[2])


# Labels of buttons that only take a pop-up further (nothing is chosen with them) ...
GO_ON_LABELS = ("LETSGO", "OK", "OKAY", "CONTINUE", "NEXT", "CLAIM", "COLLECT", "DONE", "CLOSE", "GOTIT")
# ... and words on a screen that mean: do not tap a button here that was not read
DANGER_WORDS = ("SHOP", "BUY", "COIN", "POKECOIN", "PURCHASE", "PREMIUM", "PASS", "EXCHANGE", "TRANSFER", "DELETE",
                "EXIT", "QUIT", "LEAVE", "REMOVE", "SHARE", "DISCARD")


# ... and labels that are never tapped on a screen the bot does not know (they choose or start something)
KEEP_OFF_LABELS = ("PARTY", "USE", "YES", "JOIN", "BUY", "SHOP", "COIN", "SHARE", "EXCHANGE", "PREMIUM", "PASS",
                   "PURCHASE", "TRANSFER", "EXIT", "QUIT", "LEAVE")


def keep_off_label(text):
    """True when the label of a button is read and says something the bot must not tap on a screen it does
    not know: USE THIS PARTY (that starts a battle), YES, JOIN GROUP, BUY ..."""
    words = [_plain(w) for w in text.split()]
    return any(w.startswith(k) for w in words if w for k in KEEP_OFF_LABELS)


def go_on_label(text):
    """True when the label of a button says that it only takes the screen further: LET'S GO!, OK, CONTINUE,
    NEXT, CLAIM REWARD! ... (the text may be misread a little)."""
    plain = _plain(text)
    return bool(plain) and any(plain == g or (len(g) >= 4 and (g in plain or like(plain, g, 0.8))) for g in GO_ON_LABELS)


def danger_words(lines):
    """The words read on a screen that have to do with buying, giving away or leaving ([] = none)."""
    out = []
    for w, _x, _y in words_of(lines):
        plain = _plain(w)
        if any(plain.startswith(d) for d in DANGER_WORDS) and plain not in out:
            out.append(plain)
    return out


def premium_above(lines, y):
    """True when the word PREMIUM is read above height y (pixels): a BATTLE button below it belongs to the
    premium rewards, which cost a Premium Battle Pass - it is not to be tapped."""
    return any(like(_plain(w), "PREMIUM", 0.8) and wy < y for w, _x, wy in words_of(lines))


def battle_words(lines):
    """True when words of the battle screens are read (LEAGUE, RANK, REWARDS ...): this is no catch screen."""
    return any(_plain(w) in ("LEAGUE", "PARTY", "REWARDS", "REWARD", "RANK", "BATTLE") for w, _x, _y in words_of(lines))


def exit_battle_spots(lines, k=1.0):
    """'Exit the Trainer Battle?' -> {"yes": (x, y), "no": (x, y) or None}.  The question comes up when
    BACK is pressed on the league list or on the party screen.  YES is placed from the word NO (or from the
    question when NO is not read, or at a fixed spot)."""
    no = next(((x, y) for w, x, y in words_of(lines) if w == "NO" and y > 900 * k), None)
    title = next((y for t, _x, y, _ws in lines if "EXIT" in t and "TRAINER" in t), None)
    if no:
        yes = (no[0], no[1] - int(YES_ABOVE_NO * k))
    elif title:
        yes = (int(EXIT_YES_FALLBACK[0] * k), title + int(YES_BELOW_TITLE * k))
    else:
        yes = (int(EXIT_YES_FALLBACK[0] * k), int(EXIT_YES_FALLBACK[1] * k))
    return {"yes": yes, "no": no}


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


# ------------------------------------------------------------------ the fight ---
# What OCR reads during a fight: the question strip in the middle of the screen, the two name boxes at the top,
# the labels under the two charged attack buttons and the CP numbers of the "Switch in a new Pokémon?" pop-up.

def _plain(word):
    """A word in plain capitals without accents or punctuation ('POKÉMON?' -> 'POKEMON')."""
    word = unicodedata.normalize("NFKD", word)
    return re.sub(r"[^A-Z0-9]+", "", "".join(c for c in word if not unicodedata.combining(c)).upper())


def question_kind(lines):
    """Which question is on the screen (OCR of the strip in the middle, while the countdown ring is up)?

    shield     'Attack incoming! Use a Protect Shield?' - answer it with the shield or NOT NOW
    noshield   'No Protect Shields remaining!' - an attack is coming and there is nothing to decide
    switch     'Switch in a new Pokémon?' - pick the next Pokémon
    ''         not read (try again on the next picture)
    """
    words = [_plain(w) for w, _x, _y in words_of(lines)]
    words = [w for w in words if w]
    if any(like(w, "SWITCH", 0.8) for w in words):
        return "switch"
    if any(like(w, "REMAINING", 0.75) or w == "SHIELDS" for w in words):
        return "noshield"
    if any(like(w, "INCOMING", 0.75) or w in ("SHIELD", "ATTACK", "USE") for w in words):
        return "shield"
    return ""


def name_box(lines):
    """(name, cp) from the OCR of one name box at the top ('NOCTOWL CP 1497' or 'CP 1493 CRAMORANT').
    name is '' when no name is read, cp is None when the number is not read."""
    name, cp = [], None
    for w, _x, _y in words_of(lines):
        plain = _plain(w)
        m = re.fullmatch(r"CP(\d{3,4})", plain)
        if m:
            cp = int(m.group(1))
        elif plain == "CP":
            continue
        elif re.fullmatch(r"\d{3,4}", plain):
            cp = cp or int(plain)
        elif len(plain) >= 3 and plain.isalpha():
            name.append(plain.title())
    return " ".join(name), cp


def popup_tiles(lines):
    """[(cp, x)] left to right: the CP numbers above the choices of 'Switch in a new Pokémon?' (the tiles
    show no names, only the CP).  The small 'CP' in front of the number is often misread ('CPE1494'): a few
    letters and then three or four digits is such a number."""
    out = []
    for w, x, _y in words_of(lines):
        m = re.fullmatch(r"[A-Z]{0,4}(\d{3,4})", _plain(w))
        if m:
            out.append((int(m.group(1)), x))
    out.sort(key=lambda t: t[1])
    return out


def button_texts(lines, width):
    """(left, right): the words under the two charged attack buttons (the move names), split at the middle
    of the screen; '' for a side where nothing is read."""
    left, right = [], []
    for w, x, _y in sorted(words_of(lines), key=lambda t: t[1]):
        (left if x < width / 2 else right).append(w)
    return " ".join(left), " ".join(right)


def result_kind(lines):
    """win / loss / '' from the words on the result screen: 'GOOD EFFORT!' is a loss, 'YOU WIN!' a win.  The
    big white letters stand over the trainer and are not always read in one piece ('YOU W IN', 'YOU. WIN!');
    WIN alone is not enough (a line of the research can say 'Win 30 Trainer Battles ...')."""
    words = [_plain(w) for w, _x, _y in words_of(lines)]
    words = [w for w in words if w]
    if any(like(w, "EFFORT", 0.8) for w in words) or ("GOOD" in words and not any(
            like(w, "VICTORY", 0.8) for w in words)):
        return "loss"
    if any(like(w, "VICTORY", 0.8) or like(w, "WINNER", 0.8) for w in words):
        return "win"
    for line in lines:                                   # YOU WIN, in one line
        ws = [w for w in (_plain(w) for w, _x, _y in line[3]) if w]
        for i, w in enumerate(ws):
            if w in ("YOUWIN", "YOUWINS") or (w == "YOU" and "".join(ws[i + 1:i + 3])[:3] in ("WIN", "W1N", "WLN")):
                return "win"
    return ""


def result_word(text):
    """win / loss / '' from the big white words in the middle of a result screen when they were read on their
    own (gamebot._result_words): 'YOU WIN!' or 'GOOD EFFORT!'.  Nothing else stands there in white, so WIN is
    enough here."""
    words = [w for w in (_plain(w) for w in (text or "").split()) if w]
    joined = "".join(words)
    if "EFFORT" in joined or any(like(w, "EFFORT", 0.75) for w in words) or ("GOOD" in words and "WIN" not in joined):
        return "loss"
    if "YOUWIN" in joined or any(w in ("WIN", "WINS") for w in words):
        return "win"
    return ""


def party_use_spots(lines, k=1.0):
    """Where to tap USE THIS PARTY: the middle of the green button (its label is the same height; the
    label is only used for the height) and a fixed spot when the label is not read."""
    ys = [y for t, _x, y, ws in lines if _phrase([(t, 0, y, ws)], "USE THIS PARTY", 0.7)]
    ys += [y for t, _x, y, _ws in lines if "THIS PARTY" in t and "CHOOSE" not in t]
    spots = []
    if ys:
        spots.append((int(PARTY_BUTTON_FALLBACK[0] * k), max(ys)))
    spots.append((int(PARTY_BUTTON_FALLBACK[0] * k), int(PARTY_BUTTON_FALLBACK[1] * k)))
    return spots
