#!/usr/bin/env python3
"""Reading the screen of a GO Battle League fight (pictures in, facts out).

Pure picture tests (NumPy + OpenCV, no OCR, no phone): they are fast, so the fight loop can look at every
screenshot.  Every position is a fraction of the screen, so the same code works on the 1768 x 2208 canvas
of the Galaxy Z Fold3 and on a smaller copy of it.  The numbers come from a recording of a whole fight
(tests/fixtures/fight_frames/, made with the recorder of the web interface).

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
TAP_FAST = (0.50, 0.45)           # a tap here is a fast attack (nothing is under it)
TAP_SHIELD = (0.50, 0.70)         # the shield on "Attack incoming! Use a Protect Shield?"
TAP_NOT_NOW = (0.50, 0.91)        # NOT NOW on the same question
TAP_NEXT = (0.50, 0.866)          # the green NEXT BATTLE button
POPUP_TILES = (0.32, 0.68)        # "Switch in a new Pokémon?": the two choices (x); y below
POPUP_TILE_Y = 0.74
BAR_FULL = 484 / 1768.0           # the inside of a full HP bar
SHIELD_SLOTS_Y = 0.171            # the two shield icons in each name box
SHIELD_SLOTS = {"me": (0.235, 0.283), "foe": (0.717, 0.764)}
COUNT_CENTER = (0.50, 0.145)      # the countdown ring of a question


def _box(img, x0, y0, x1, y1):
    h, w = img.shape[:2]
    return img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def _pale(px):
    """Pale, hardly coloured pixels (the name boxes at the top, the white of a ring)."""
    mn = px.min(axis=-1).astype(np.int16)
    mx = px.max(axis=-1).astype(np.int16)
    return (mn > 190) & (mx - mn < 50)


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


def hud_visible(img):
    """True when the name boxes at the top of a fight are on the screen."""
    me = _pale(_box(img, 0.03, 0.115, 0.39, 0.19)).mean()
    foe = _pale(_box(img, 0.61, 0.115, 0.97, 0.19)).mean()
    return max(me, foe) > 0.35 and min(me, foe) > 0.12


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


def charge_ready(img):
    """(left, right): is the charged attack button lit (enough energy for it)?  A lit button is bigger
    than a dark one and has a thick white ring, which is what is measured (the radius is searched:
    the button swells a little when it is ready)."""
    h, w = img.shape[:2]
    res = []
    for bx in BTN_X:
        cx, cy = bx * w, BTN_Y * h
        best = 0.0
        for r in np.arange(0.080, 0.112, 0.004) * w:
            best = max(best, _ring_fraction(img, cx, cy, r - 0.004 * w, r + 0.004 * w))
        res.append(best > 0.30)
    return tuple(res)


def countdown_ring(img):
    """The countdown ring at the top that comes with a question (shield / switch / no shields left)."""
    h, w = img.shape[:2]
    cx, cy = COUNT_CENTER[0] * w, COUNT_CENTER[1] * h
    inner = _box(img, 0.46, 0.115, 0.54, 0.175)
    dark = float(inner.max(axis=-1).mean()) < 150                    # a dark disc ...
    ring = max(_ring_fraction(img, cx, cy, r - 0.003 * w, r + 0.003 * w)
               for r in np.arange(0.060, 0.096, 0.003) * w)
    digit = float(_pale(_box(img, 0.47, 0.12, 0.53, 0.17)).mean())   # ... with a white number and ring
    return dark and ring > 0.12 and digit > 0.04


def shield_icon_slots(img):
    """{'me': n, 'foe': n}: the shields each side still has (lilac icons in the name box), or None."""
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    out = {}
    for side, xs in SHIELD_SLOTS.items():
        n = 0
        for xf in xs:
            x, y = int(xf * w), int(SHIELD_SLOTS_Y * h)
            r = max(int(0.007 * w), 3)
            patch = hsv[y - r:y + r + 1, x - r:x + r + 1].reshape(-1, 3)
            hue, sat, val = np.median(patch, axis=0)
            if 125 <= hue <= 155 and 45 <= sat <= 120 and val >= 200:
                n += 1
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
    hh, ss, vv = [hsv[..., k].astype(np.int16) for k in range(3)]
    green = (hh >= 70) & (hh <= 90) & (ss > 150) & (vv > 200)
    yellow = (hh >= 22) & (hh <= 34) & (ss > 90) & (vv > 220)
    red = ((hh <= 6) | (hh >= 170)) & (ss > 110) & (vv > 200)
    fill = (green | yellow | red).astype(np.uint8)
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


def result_button(img):
    """True when the green pill button (NEXT BATTLE) is at the bottom of a result screen."""
    reg = _box(img, 0.31, 0.845, 0.69, 0.885)
    hsv = cv2.cvtColor(reg, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    green = (hue >= 65) & (hue <= 95) & (sat >= 70) & (val >= 150)
    return float(green.mean()) > 0.45


def features(img):
    """Everything above in one dict (for the log and the tests)."""
    mine, foe = hp_of_sides(img)
    return {
        "white": is_white_screen(img), "versus": is_versus(img), "hud": hud_visible(img),
        "ready": charge_ready(img), "ring": countdown_ring(img), "shields": shield_icon_slots(img),
        "hp": (mine, foe), "result": result_button(img),
    }
