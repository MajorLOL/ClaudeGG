#!/usr/bin/env python3
"""Reading the screen of a GO Battle League fight (pictures in, facts out).

Pure picture tests (NumPy + OpenCV, no OCR, no phone): they are fast, so the fight loop can look at every
screenshot.  Every position is a fraction of the screen, so the same code works on the 1768 x 2208 canvas
of the Galaxy Z Fold3 and on a smaller copy of it.  The numbers come from recordings of whole fights
(tests/fixtures/fight/, made with the recorder of the web interface): one in an arena by night and one in an
arena by day.  By day the sky is full of white clouds, so nothing in here may take "pale" or "white" alone
for a sign: the name boxes are known by their Poké Balls, the countdown by its white arc on the darker disc
and a lit button by its white ring together with its white label.

    VERSUS  "Finding opponent" / "Battle starting": two halves with a white line in the middle
    HUD     the two name boxes at the top: name, CP, Poké Balls (alive), shields
    fight   the HUD, HP bars above the two Pokémon and, at the bottom, the two charged attack buttons
    prompt  a ring with a countdown at the top: "Attack incoming! Use a Protect Shield?" or the
            "Switch in a new Pokémon?" question (told apart by OCR, see battle_nav.py)
    result  "GOOD EFFORT!" ..., a green button NEXT BATTLE at the bottom
"""
import cv2
import numpy as np

# ---- where things are (fractions of the screen width / height) --------------------------------------
BTN_Y = 0.816                     # centre of the two charged attack buttons
BTN_X = (0.307, 0.690)            # ... left and right
BTN_R = 0.095                     # ... radius of a ready (lit) button, in screen widths
LABEL_Y = (0.895, 0.935)          # the name of the move under a button (bright white when it is ready)
LABEL_LIT = 215                   # ... brightness of that text: ready 234-255, not ready 60-150
LABEL_FLASH = 0.20                # ... more than this fraction white is a flash, not a text (a text: 0.04-0.11)
RING_LIT = 0.45                   # the white ring of a lit button: 0.70-0.82 of it is white (0.56 and more on a
                                  # badly blurred video).  With a bright label and no ring: 0.21 at most
TAP_FAST = (0.50, 0.45)           # a tap here is a fast attack (nothing is under it)
TAP_SHIELD = (0.50, 0.70)         # the shield on "Attack incoming! Use a Protect Shield?"
TAP_NOT_NOW = (0.50, 0.91)        # NOT NOW on the same question
TAP_NEXT = (0.50, 0.866)          # the green NEXT BATTLE button
POPUP_TILES = (0.32, 0.68)        # "Switch in a new Pokémon?": the two choices (x); y below
POPUP_TILE_Y = 0.74
BAR_FULL = 484 / 1768.0           # the inside of a full HP bar
SHIELD_SLOTS_Y = 0.171            # the two shield icons in each name box
SHIELD_SLOTS = {"me": (0.235, 0.283), "foe": (0.717, 0.764)}
COUNT_CENTER = (0.50, 0.145)      # the countdown of a question (about: see COUNT_DISCS)
# ... its white arc: (centre x, centre y, radius in screen widths) for the shield question / "No Protect
# Shields remaining!" and for the switch question (that one sits between the name boxes, a little lower)
COUNT_DISCS = ((0.499, 0.143, 0.066), (0.501, 0.158, 0.070))
COUNT_LAST = (238.0, 267.0)       # degrees (270 = the top, 180 = the left): the piece of the arc that goes last
BALL_Y = 0.170                    # the three Poké Balls in each name box (red: can fight, grey: fainted)
BALL_X = {"me": (0.053, 0.107, 0.161), "foe": (0.836, 0.890, 0.944)}
BALL_R = 0.011                    # ... half the side of the patch that is looked at (in screen widths)
SHIELD_ICON = (0.50, 0.715)       # the big shield icon on "Use a Protect Shield?"


def _box(img, x0, y0, x1, y1):
    h, w = img.shape[:2]
    return img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def _pale(px):
    """Pale, hardly coloured pixels (the name boxes at the top, the white of a ring)."""
    b, g, r = cv2.split(np.ascontiguousarray(px))
    mn = cv2.min(cv2.min(b, g), r)
    mx = cv2.max(cv2.max(b, g), r)
    return (mn > 190) & (cv2.subtract(mx, mn) < 50)


def is_white_screen(img):
    return float(img[::8, ::8].mean()) > 245


def is_versus(img):
    """The VS screen: a white line over the whole width in the middle of the screen."""
    h, w = img.shape[:2]
    band = img[int(0.495 * h):int(0.505 * h), int(0.02 * w):int(0.98 * w)]
    white = band.min(axis=-1) > 225
    # (the round VS badge sits in the middle: leave it out)
    cut = np.ones(white.shape[1], bool)
    cut[int(0.40 * white.shape[1]):int(0.60 * white.shape[1])] = False
    return float(white.any(axis=0)[cut].mean()) > 0.85


def ball_slots(img):
    """{'me': (red, grey), 'foe': (red, grey)}: the Poké Balls in each name box, red for a Pokémon that can
    still fight and grey for one that fainted (three in all when the box is on the screen)."""
    h, w = img.shape[:2]
    y, r = int(BALL_Y * h), max(int(round(BALL_R * w)), 3)
    top = max(y - r, 0)
    strip = img[top:y + r + 1]
    hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
    out = {}
    for side, xs in BALL_X.items():
        red = grey = 0
        for xf in xs:
            x = int(xf * w)
            hue, sat, val = [hsv[:, max(x - r, 0):x + r + 1, k] for k in range(3)]
            # the red of a ball is a little orange (hue 7-9 of 180, saturation ~220, value ~240; under a banner
            # value ~180): 0.70 of the patch on a clear picture, 0.46 and more under a banner, 0.00 on a grey ball
            if float((((hue <= 14) | (hue >= 164)) & (sat >= 110) & (val >= 120)).mean()) >= 0.25:
                red += 1
            elif float((val < 125).mean()) >= 0.45:    # (val is the brightest channel: a grey ball is dark, 0.98)
                grey += 1
        out[side] = (red, grey)
    return out


def hud_visible(img):
    """True when the name boxes at the top of a fight are on the screen: two pale boxes, each with its Poké
    Balls.  The balls are what tells them from a pale sky (an arena by day has white clouds right there, and
    so have the screens before and after the fight): each side has at least one red ball (somebody can still
    fight) and at least two of its three balls are seen (a banner may cover one)."""
    for x0, x1 in ((0.03, 0.39), (0.61, 0.97)):
        box = _box(img, x0, 0.115, x1, 0.19)
        mn = box.min(axis=-1)
        light = (mn > 140) & (box.max(axis=-1).astype(np.int16) - mn < 60)   # (a box is dimmed while an attack
        if float(light.mean()) <= 0.12:                                      # is shown, and a video can be darker
            return False                                                     # than a screenshot: not too strict)
    return all(red >= 1 and red + grey >= 2 for red, grey in ball_slots(img).values())


def _ring_fraction(img, cx, cy, r0, r1):
    h, w = img.shape[:2]
    y0, y1 = max(int(cy - r1), 0), min(int(cy + r1) + 1, h)
    x0, x1 = max(int(cx - r1), 0), min(int(cx + r1) + 1, w)
    sub = img[y0:y1, x0:x1]
    yy, xx = np.ogrid[y0:y1, x0:x1]
    d2 = (xx - cx) ** 2 + (yy - cy) ** 2
    mask = (d2 >= r0 * r0) & (d2 <= r1 * r1)
    if not mask.any():
        return 0.0
    return float((sub.min(axis=-1)[mask] > 215).mean())


_rings = {}                       # which pixels belong to which ring: the same for every picture of one size


def _ring_best(img, cx, cy, radii, half):
    """The whitest of the rings with the given radii (each `half` thick to both sides) around (cx, cy): the
    share of white pixels in it.  The same as max(_ring_fraction(...)) over the radii, but the pixels of every
    ring are worked out only once per picture size (the fight loop asks this for every picture)."""
    h, w = img.shape[:2]
    key = (h, w, round(cx, 2), round(cy, 2), tuple(round(float(r), 3) for r in radii), round(float(half), 3))
    geo = _rings.get(key)
    if geo is None:
        r1 = max(radii) + half
        y0, y1 = max(int(cy - r1), 0), min(int(cy + r1) + 1, h)
        x0, x1 = max(int(cx - r1), 0), min(int(cx + r1) + 1, w)
        yy, xx = np.ogrid[y0:y1, x0:x1]
        d2 = ((xx - cx) ** 2 + (yy - cy) ** 2).ravel()
        idx = [np.flatnonzero((d2 >= (r - half) ** 2) & (d2 <= (r + half) ** 2)) for r in radii]
        if len(_rings) > 64:
            _rings.clear()
        geo = _rings[key] = (y0, y1, x0, x1, idx)
    y0, y1, x0, x1, idx = geo
    white = (img[y0:y1, x0:x1].min(axis=-1) > 215).ravel()
    return max((float(white[i].mean()) for i in idx if i.size), default=0.0)


def _label_lit(img, bx):
    """Is the name of the move under a button bright white?  Text is a thin line: when a large part of the
    strip is white it is a flash of the charged attack's zoom, not a label."""
    h, w = img.shape[:2]
    lab = img[int(LABEL_Y[0] * h):int(LABEL_Y[1] * h), int((bx - 0.11) * w):int((bx + 0.11) * w)].min(axis=-1)
    return float(np.percentile(lab, 98)) >= LABEL_LIT and float((lab > 200).mean()) < LABEL_FLASH


def charge_ready(img):
    """(left, right): is the charged attack button lit (enough energy for it)?  Both signs must be there: the
    name under the button is bright white (grey when there is not enough energy) AND the button has its thick
    white ring (the radius is searched: the button swells a little when it is ready).  One sign alone is not
    enough: the white lines of the field, the Poké Ball of the intro and the flash of an attack make the label
    zone white, a flash or the glitter of a fainting Pokémon looks like a ring - and each of those made the
    bot throw a charged attack that was not there."""
    h, w = img.shape[:2]
    radii = np.arange(0.080, 0.112, 0.004) * w
    res = []
    for bx in BTN_X:
        res.append(_label_lit(img, bx) and _ring_best(img, bx * w, BTN_Y * h, radii, 0.004 * w) >= RING_LIT)
    return tuple(res)


_arcs = {}                        # the pixels of the last piece of the countdown's arc, per picture size


def _count_last(img, cx, cy, r):
    """How much of the last piece of the countdown's arc is on the picture (0..1).  The arc is a thin white
    line on a darker disc; it shrinks towards the top of the circle and the piece just left of the top goes
    last.  A point counts when the line is white there and the disc on both sides of it is not (so a white
    cloud or a white screen is no arc)."""
    h, w = img.shape[:2]
    key = (h, w, cx, cy, r)
    geo = _arcs.get(key)
    if geo is None:
        ang = np.radians(np.linspace(COUNT_LAST[0], COUNT_LAST[1], 24))
        geo = []
        for rr in (r - 0.014, r - 0.004, r, r + 0.004, r + 0.012):
            xs = np.clip(np.round(cx * w + rr * w * np.cos(ang)).astype(int), 0, w - 1)
            ys = np.clip(np.round(cy * h + rr * w * np.sin(ang)).astype(int), 0, h - 1)
            geo.append((ys, xs))
        if len(_arcs) > 32:
            _arcs.clear()
        _arcs[key] = geo
    inside, a, b, c, outside = [img[ys, xs] for ys, xs in geo]
    line = (a.min(axis=-1) > 215) | (b.min(axis=-1) > 215) | (c.min(axis=-1) > 215)
    disc = (inside.max(axis=-1) < 190) & (outside.max(axis=-1) < 190)
    return float((line & disc).mean())


def countdown_kind(img):
    """The countdown at the top that comes with a question: a disc with a white number and a white arc that
    runs out.  Returns "attack" (the shield question, or 'No Protect Shields remaining!'), "switch" (the
    switch question: its disc sits a little lower, between the name boxes) or "" (no countdown).
    The disc is see-through - dark blue by night, grey over the clouds by day - so its own brightness says
    nothing; the number and the arc are white on something that is clearly not white."""
    h, w = img.shape[:2]
    r = int(0.040 * w)
    for kind, (cx, cy, radius) in zip(("attack", "switch"), COUNT_DISCS):
        x, y = int(cx * w), int(cy * h)
        mid = img[max(y - r, 0):y + r + 1, max(x - r, 0):x + r + 1]
        digit = float(_pale(mid).mean())                             # the white number ...
        if not 0.04 < digit < 0.60:
            continue
        if float((mid.max(axis=-1) < 190).mean()) < 0.35:            # ... on the disc
            continue
        if max(_count_last(img, cx, cy, radius + d) for d in (-0.003, 0.0, 0.003)) >= 0.70:
            return kind
    return ""


def countdown_ring(img):
    """True when a question with its countdown is on the screen (see countdown_kind())."""
    return bool(countdown_kind(img))


def name_key(img, side):
    """A small fingerprint of the text line of a name box ('me' / 'foe': the name and the CP).  It changes when
    another Pokémon comes in, so the fight loop knows when to read the names again without reading them all
    the time (reading text is the slowest thing the bot does)."""
    x0, x1 = (0.035, 0.385) if side == "me" else (0.615, 0.965)
    box = _box(img, x0, 0.118, x1, 0.148)
    ink = (box.max(axis=-1) < 150).astype(np.uint8) * 255            # the letters are dark on the pale box
    return cv2.resize(ink, (40, 4), interpolation=cv2.INTER_AREA)


def key_differs(a, b):
    """Do two name_key() fingerprints show another text?"""
    if a is None or b is None:
        return True
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean()) > KEY_DIFF


KEY_DIFF = 7.0                    # (0-255) the same text gives 0-5 on the next picture, another name 9 and more


def shield_question(img):
    """True when the pop-up shows the big lilac shield of "Attack incoming! Use a Protect Shield?" (so no OCR is
    needed to know which question it is, the countdown ring alone also comes with the switch question)."""
    h, w = img.shape[:2]
    cx, cy, r = SHIELD_ICON[0] * w, SHIELD_ICON[1] * h, 0.045 * w
    y0, y1, x0, x1 = int(cy - r), int(cy + r) + 1, int(cx - r), int(cx + r) + 1
    hsv = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    yy, xx = np.ogrid[y0:y1, x0:x1]
    disc = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
    hue, sat, val = [hsv[..., k][disc[:hsv.shape[0], :hsv.shape[1]]] for k in range(3)]
    lilac = (hue >= 130) & (hue <= 170) & (sat >= 25) & (sat <= 150) & (val >= 170)
    return bool(lilac.mean() > 0.6)


def shield_icon_slots(img):
    """{'me': n, 'foe': n}: the shields each side still has, None for a side whose icons are not clearly seen.
    Each name box has two icons: lilac for a shield that is left, dark purple for one that was used.  A banner
    ('Slowbro used Ice Beam!') lies over the boxes for a second or two and makes the icons something in
    between: that says nothing (it used to count as "no shields left", for both sides)."""
    h, w = img.shape[:2]
    y, r = int(SHIELD_SLOTS_Y * h), max(int(0.007 * w), 3)
    top = max(y - r, 0)
    hsv = cv2.cvtColor(img[top:y + r + 1], cv2.COLOR_BGR2HSV)         # (only the strip the icons are in)
    out = {}
    for side, xs in SHIELD_SLOTS.items():
        n = 0
        for xf in xs:
            x = int(xf * w)
            patch = hsv[y - r - top:y + r + 1 - top, x - r:x + r + 1].reshape(-1, 3)
            hue, sat, val = np.median(patch, axis=0)
            if 125 <= hue <= 155 and 45 <= sat <= 120 and val >= 200:        # left: (140, 70-84, 240)
                n += 1
            elif not (125 <= hue <= 155 and 50 <= sat <= 115 and 105 <= val <= 140):   # used: (140, 72-90, 120)
                n = None                                                     # neither: covered, or no name box
                break
        out[side] = n
    return out


def hp_bars(img):
    """The HP bars above the two Pokémon: [{'x0': px, 'frac': 0..1, 'color': ..., 'y': px}, ...] sorted
    from left to right.  The fill is green / yellow / red (the orange piece that has just been lost does
    not count); a full bar is 484 px of the 1768 px wide screen."""
    h, w = img.shape[:2]
    top, bot = int(0.20 * h), int(0.62 * h)
    reg = img[top:bot]
    hsv = cv2.cvtColor(reg, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, (70, 151, 201), (90, 255, 255))
    yellow = cv2.inRange(hsv, (22, 91, 221), (34, 255, 255))
    red = cv2.inRange(hsv, (0, 111, 201), (6, 255, 255)) | cv2.inRange(hsv, (170, 111, 201), (180, 255, 255))
    fill = ((green | yellow | red) > 0).astype(np.uint8)
    fill = cv2.morphologyEx(fill, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, w // 190), 1)))
    n, _lab, stats, _ = cv2.connectedComponentsWithStats(fill, connectivity=8)
    full = BAR_FULL * w
    out = []
    for j in range(1, n):
        x, y, bw, bh, area = [int(v) for v in stats[j]]
        if not (0.008 * h <= bh <= 0.03 * h) or bw < 0.008 * w or bw > full * 1.08 or area < 0.6 * bw * bh:
            continue
        yc = y + bh // 2
        if top + yc > 0.55 * h:
            continue                                   # (small coloured things lower down are no bars)
        row = reg[max(yc - 2, 0):yc + 3].astype(np.int16).mean(axis=0)
        l0 = max(x - int(0.009 * w), 0)
        l1 = max(x - int(0.001 * w), l0 + 1)
        seg = row[l0:l1]
        if not ((seg.min(axis=1) > 150) & (seg.max(axis=1) - seg.min(axis=1) < 90)).any():
            continue                                   # no pale frame on its left: not an HP bar
        # the right edge of the frame is there whatever the fill (a coloured blob of an attack is not a bar)
        r0 = min(int(x + full + 0.002 * w), w - 2)
        r1 = min(int(x + full + 0.008 * w), w - 1)
        side = reg[max(yc - int(0.005 * h), 0):yc + int(0.005 * h) + 1, r0:max(r1, r0 + 1)].astype(np.int16)
        edge = ((side.min(axis=-1) > 150) & (side.max(axis=-1) - side.min(axis=-1) < 90)).mean(axis=0)
        if edge.size == 0 or edge.max() < 0.6:
            continue
        col = "green" if green[yc, min(x + 1, w - 1)] else "yellow" if yellow[yc, min(x + 1, w - 1)] else "red"
        out.append({"x0": x, "frac": min(bw / full, 1.0), "color": col, "y": top + yc})
    out.sort(key=lambda b: b["x0"])
    return out


def hp_of_sides(img):
    """(my HP fraction, the foe's) - None for a bar that is not clearly seen.  Mine is the left one.  A
    lone bar in the middle (the camera follows one Pokémon during a charged attack) is not used."""
    h, w = img.shape[:2]
    mine = foe = None
    for b in hp_bars(img):
        if b["frac"] < 0.02:
            continue
        xf = b["x0"] / float(w)
        if xf < 0.30 and mine is None:
            mine = b["frac"]
        elif xf >= 0.40 and foe is None:
            foe = b["frac"]
    return mine, foe


def _green_share(img, x0, y0, x1, y1):
    hsv = cv2.cvtColor(_box(img, x0, y0, x1, y1), cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    return float(((hue >= 65) & (hue <= 95) & (sat >= 70) & (val >= 150)).mean())


def result_button(img):
    """True when the green pill button (NEXT BATTLE) is at the bottom of a result screen.  A quick look first
    (green where the button is, not green left and right of it: the grass of an arena by day and the map are
    green from edge to edge), then the button itself is looked for: a green pill around TAP_NEXT."""
    if _green_share(img, 0.31, 0.845, 0.69, 0.885) <= 0.45:
        return False
    if max(_green_share(img, 0.05, 0.845, 0.22, 0.885), _green_share(img, 0.78, 0.845, 0.95, 0.885)) >= 0.25:
        return False
    top = 0.70
    for b in wide_buttons(img, top):
        if (b["color"] == "green" and b["y0"] > top + 0.02 and b["x0"] < TAP_NEXT[0] < b["x1"]
                and b["y0"] < TAP_NEXT[1] < b["y1"] and 0.25 <= b["x1"] - b["x0"] <= 0.50
                and 0.035 <= b["y1"] - b["y0"] <= 0.095):
            return True
    return False


# ---- the buttons of the screens around a fight --------------------------------------------------------
# The game's buttons are wide pills in one colour with a white label: green (BATTLE, USE THIS PARTY, NEXT
# BATTLE, OK, CLAIM REWARD!) or orange (CLAIM RANK REWARDS!).  White text on such a button is often not read
# by OCR, so the button itself is looked for: rows that have the button's colour from one end to the other.
BUTTON_COLOURS = (("green", 55, 95, 70, 150), ("orange", 8, 24, 110, 200))   # name, hue from-to, min. saturation, value
BUTTON_TINT = 25                  # the label makes the colour paler: this saturation still belongs to the button
BUTTON_WIDE = 0.25                # a button is at least this wide (of the screen) ...
BUTTON_HIGH = (0.018, 0.11)       # ... and this high (of the screen height; the lowest ones are cut by the edge)


def _runs(row):
    """[(x0, x1), ...] of the stretches of True in a row (x1 is one past the end)."""
    d = np.diff(np.concatenate(([0], row.view(np.int8), [0])))
    return list(zip(np.where(d == 1)[0].tolist(), np.where(d == -1)[0].tolist()))


def wide_buttons(img, top=0.45):
    """The wide green and orange buttons in the lower part of a screen (from `top` down), lowest first:
    [{"color": "green" / "orange", "x0", "x1", "y0", "y1"}] in fractions of the screen.  A button is a block
    of rows that are in its colour from its left end to its right end (the white label in between is paler,
    in the same hue), that is clearly wider than high and does not touch the sides of the screen (a
    background in that colour does)."""
    h, w = img.shape[:2]
    y_top = int(top * h)
    sw = 221
    k = sw / float(w)
    sh = max(int(round((h - y_top) * k)), 1)
    hsv = cv2.cvtColor(cv2.resize(img[y_top:], (sw, sh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    full_h = h * k
    need = int(BUTTON_WIDE * sw)
    out = []
    for colour, h0, h1, s_min, v_min in BUTTON_COLOURS:
        in_hue = (hue >= h0) & (hue <= h1) & (val >= v_min)
        strict = in_hue & (sat >= s_min)
        tint = in_hue & (sat >= BUTTON_TINT)
        rows = []                                  # per row: its widest stretch that looks like a button
        for r in range(sh):
            best = None
            for a, b in _runs(tint[r]):
                if (b - a >= need and a > 2 and b < sw - 2 and strict[r, a:b].mean() >= 0.35
                        and strict[r, a:a + 4].any() and strict[r, b - 4:b].any()):
                    if best is None or b - a > best[1] - best[0]:
                        best = (a, b)
            rows.append(best)
        blocks = []                                # rows on top of each other that cover the same stretch
        for r, run in enumerate(rows):
            if run is None:
                continue
            last = blocks[-1] if blocks else None
            if last and r - last["r1"] <= 2 and min(run[1], last["b"]) - max(run[0], last["a"]) >= 0.6 * min(
                    run[1] - run[0], last["b"] - last["a"]):
                last["r1"] = r
                last["all"].append(run)
                last["a"], last["b"] = run
            else:
                blocks.append({"r0": r, "r1": r, "a": run[0], "b": run[1], "all": [run]})
        merged = []                                # the rows of the label can fall out: two blocks, one button
        for blk in blocks:
            last = merged[-1] if merged else None
            if last is not None:
                a, b = min(last["a"], blk["a"]), max(last["b"], blk["b"])
                gap = tint[last["r1"] + 1:blk["r0"], a:b]
                if (0 < gap.shape[0] <= 0.04 * full_h and gap.mean() >= 0.5
                        and min(last["b"], blk["b"]) - max(last["a"], blk["a"]) >= 0.6 * (b - a)):
                    last["r1"] = blk["r1"]
                    last["all"] += blk["all"]
                    continue
            merged.append(blk)
        for blk in merged:
            x0 = int(np.median([a for a, _b in blk["all"]]))
            x1 = int(np.median([b for _a, b in blk["all"]]))
            bh, bw = blk["r1"] - blk["r0"] + 1, x1 - x0
            if not (BUTTON_HIGH[0] * full_h <= bh <= BUTTON_HIGH[1] * full_h) or bw < 2.2 * bh:
                continue
            out.append({"color": colour, "x0": round(x0 / float(sw), 3), "x1": round(x1 / float(sw), 3),
                        "y0": round((y_top * k + blk["r0"]) / full_h, 3),
                        "y1": round(min((y_top * k + blk["r1"] + 1) / full_h, 1.0), 3)})
    out.sort(key=lambda b: -b["y1"])
    return out


def button_spot(button, side=0.5):
    """Where to tap a button of wide_buttons(): (x, y) in fractions.  side: how far from its left end
    (0.5 = the middle; the Battle screen's button has the round close button over the middle of its top
    edge, so that one is tapped at a quarter)."""
    return (round(button["x0"] + side * (button["x1"] - button["x0"]), 3),
            round(min(button["y0"] + 0.6 * (button["y1"] - button["y0"]), 0.981), 3))   # (not on the very edge)


def home_button(img):
    """The big button of the Battle screen, a button of wide_buttons() or None when none is in view.

    orange  something has to be claimed before the next battle (CLAIM RANK REWARDS!)
    green   BATTLE.  In the middle of a set it sits at the bottom, cut off by the lower edge of the screen.
            When a new set starts ('Choose a reward tier ...') the card is longer and the button is below
            the edge: None, scroll down.  Further down there is a second BATTLE button, the one of the
            premium rewards (it costs a pass): so the TOPMOST green button is given, never a lower one."""
    found = wide_buttons(img, 0.45)
    for b in found:
        if b["color"] == "orange":
            return b
    return min(found, key=lambda b: b["y0"]) if found else None


def features(img):
    """Everything above in one dict (for the log and the tests)."""
    mine, foe = hp_of_sides(img)
    hud = hud_visible(img)
    count = countdown_kind(img)
    return {
        "white": is_white_screen(img), "versus": is_versus(img), "hud": hud,
        # (the buttons only count with the HUD on the picture: a charged attack's zoom has bright sparks too)
        "ready": charge_ready(img) if hud else (False, False),
        "ring": bool(count), "count": count, "shields": shield_icon_slots(img),
        "hp": (mine, foe), "result": result_button(img), "hex": shield_question(img),
    }
