#!/usr/bin/env python3
"""The little game of a charged attack: touch the icons.

When a charged attack is thrown the game shows, for about five seconds, 32 round icons of the attack's type
(water drops for Surf, wings for Sky Attack ...).  Every icon that is touched makes the attack stronger: with
none of them it does about a quarter of its damage, with (nearly) all of them the full damage (the game then
says NICE!, GREAT! or EXCELLENT!).  A bot that only keeps tapping the middle of the screen throws charged attacks
at a quarter of their strength.

What is in here (no phone, no OCR: gamebot.py takes the pictures and does the swiping):

    find_icons(picture, type)      where the icons are on a picture of the game (fractions of the screen)
    Game(type)                     one little game: game.see(time, icons) for every picture,
                                   game.plan(now) -> the swipes to make now, game.over(now)

How the swipes are chosen.  The icons either stream over the screen in a line (water, flying, electric: about
six a second, each about a second on the screen) or flash up in small rows that stand still for half a second
and come back at the same places (ghost).  A picture is a few tenths of a second old when the finger gets there,
so the swipes do not aim at single icons:

  * a stream gets a "gate": a line across it that the finger swipes there and back all the time.  Every icon
    has to pass the gate, whatever way the stream bends in between;
  * a row that stands still gets a swipe along it, and the row is remembered: the next time icons flash up
    there the finger already comes by;
  * for water, flying, electric and ghost the gates and rows are known from recordings of real fights; for the
    other types the finger starts with a cross over the middle of the screen, follows the icons it sees and
    remembers what it found for the next time (Game.learned()).

Sizes are fractions of the screen width (x) and height (y); distances are measured in screen widths.
"""
import math

import cv2
import numpy as np

# The colours of the type icons (R, G, B).  Measured on real pictures for flying, electric, water and ghost
# (they are a little darker there: the icons are slightly see-through); the others are the game's own palette.
TYPE_RGB = {
    "normal": (0xA0, 0xA2, 0x9F), "fire": (0xFB, 0xA5, 0x4C), "water": (0x53, 0x9D, 0xDF),
    "electric": (0xF2, 0xD9, 0x4E), "grass": (0x5F, 0xBD, 0x58), "ice": (0x75, 0xD0, 0xC1),
    "fighting": (0xD3, 0x42, 0x5F), "poison": (0xB7, 0x63, 0xCF), "ground": (0xDA, 0x7C, 0x4D),
    "flying": (0xA1, 0xBB, 0xEC), "psychic": (0xFA, 0x85, 0x81), "bug": (0x92, 0xBC, 0x2C),
    "rock": (0xC9, 0xBB, 0x8A), "ghost": (0x5F, 0x6D, 0xBC), "dragon": (0x0C, 0x69, 0xC8),
    "dark": (0x59, 0x57, 0x61), "steel": (0x56, 0x95, 0xA3), "fairy": (0xEE, 0x90, 0xE6),
}
ICON_R = 0.065            # radius of an icon (fraction of the screen width)
GRID_W = 141              # the picture is made this wide for the search (an icon is then 18 px across)
COLOUR_TOL = 42           # how far a channel may be from the type colour
TOP = 0.22                # nothing is looked for (or swiped) above this: the name boxes
ASPECT = 2208 / 1768.0    # height / width of the screen

# --------------------------------------------------------------------------- the icons on a picture ---
_kernels = {}


def _masks(gw):
    """Ring, surroundings and middle of an icon as averaging filters for a picture `gw` wide."""
    if gw not in _kernels:
        r = ICON_R * gw
        n = int(math.ceil(1.6 * r))
        yy, xx = np.mgrid[-n:n + 1, -n:n + 1]
        d = np.hypot(xx, yy)
        ring = ((d >= 0.60 * r) & (d <= 0.95 * r)).astype(np.float32)
        outer = ((d >= 1.20 * r) & (d <= 1.55 * r)).astype(np.float32)
        inner = (d <= 0.45 * r).astype(np.float32)
        _kernels[gw] = (ring / ring.sum(), outer / outer.sum(), inner / inner.sum(), int(r) | 1)
    return _kernels[gw]


def find_icons(img, kind, top=TOP, limit=12):
    """Middles (x, y) of the icons of type `kind` on a picture, the clearest first.

    An icon is a disc in the colour of the type with a white drawing in its middle: its ring has the colour,
    what lies around it has not (so a blue Lapras or a pale sky is no icon) and its middle has some white."""
    rgb = TYPE_RGB.get(str(kind).lower())
    if rgb is None or img is None:
        return []
    h, w = img.shape[:2]
    gw = GRID_W
    gh = max(int(round(gw * h / float(w))), 8)
    small = cv2.resize(img, (gw, gh), interpolation=cv2.INTER_AREA)
    k_ring, k_outer, k_inner, win = _masks(gw)
    target = np.array(rgb[::-1], np.int16)
    mask = (np.abs(small.astype(np.int16) - target).max(axis=2) <= COLOUR_TOL).astype(np.float32)
    white = (small.min(axis=2) >= 190).astype(np.float32)
    ring = cv2.filter2D(mask, -1, k_ring, borderType=cv2.BORDER_CONSTANT)
    outer = cv2.filter2D(mask, -1, k_outer, borderType=cv2.BORDER_CONSTANT)
    inner = cv2.filter2D(white, -1, k_inner, borderType=cv2.BORDER_CONSTANT)
    score = ring - outer
    ok = (ring >= 0.55) & (outer <= 0.55) & (score >= 0.45) & (inner >= 0.06)
    ok[:int(top * gh)] = False
    peak = cv2.dilate(score, np.ones((win, win), np.uint8))
    ys, xs = np.where(ok & (score >= peak - 1e-6))
    found = sorted(((float(score[y, x]), x / float(gw), y / float(gh)) for y, x in zip(ys, xs)), reverse=True)
    out = []
    for _s, x, y in found:
        if all(_dist((x, y), p) > 1.2 * ICON_R for p in out):
            out.append((x, y))
            if len(out) >= limit:
                break
    return out


# --------------------------------------------------------------------------------------- geometry ---
def _dist(a, b):
    """Distance between two points in screen widths."""
    return math.hypot(a[0] - b[0], (a[1] - b[1]) * ASPECT)


def _clip(p):
    return min(max(p[0], 0.03), 0.97), min(max(p[1], TOP + 0.04), 0.975)


def _stretch(a, b, extra):
    """The line a -> b made `extra` screen widths longer at both ends."""
    d = _dist(a, b)
    if d < 1e-6:
        return (a[0] - extra, a[1]), (b[0] + extra, b[1])
    ux, uy = (b[0] - a[0]) / d, (b[1] - a[1]) / d            # (uy is in height fractions per width)
    return (a[0] - ux * extra, a[1] - uy * extra), (b[0] + ux * extra, b[1] + uy * extra)


def groups(points, link=0.26):
    """Points that belong together (each within `link` of another one), every group in the order of the line
    it forms."""
    left = list(points)
    out = []
    while left:
        grp = [left.pop(0)]
        grew = True
        while grew:
            grew = False
            for p in list(left):
                if any(_dist(p, q) <= link for q in grp):
                    grp.append(p)
                    left.remove(p)
                    grew = True
        out.append(_in_line(grp))
    return out


def _in_line(grp):
    """The points of a group sorted along its longest direction."""
    if len(grp) < 3:
        return sorted(grp)
    pts = np.array([(x, y * ASPECT) for x, y in grp], np.float64)
    c = pts - pts.mean(axis=0)
    axis = np.linalg.svd(c, full_matrices=False)[2][0]
    order = np.argsort(c @ axis)
    return [grp[i] for i in order]


# ------------------------------------------------------------------------------- what to swipe ---
SPEED = 5.0               # screen widths a second the finger moves
MIN_MS = 45               # shortest swipe
REACH = 0.07              # a swipe goes this far past the outermost icon of a row
REACH_MOVING = 0.11       # ... and this far when the icons move (they move on meanwhile)
SIDE_MOVING = 0.035       # a strip of moving icons is taken this much wider on both sides
LINE_GAP = 0.105          # lines next to each other are at most this far apart (an icon is 0.13 across)
MAX_LINES = 5             # lines for one group of icons
MAX_SWIPES = 6            # swipes in one go (then the newest picture is looked at again)
CHAIN_GAP = 0.30          # icons of one smooth line are at most this far apart
CHAIN_BEND = 0.45         # ... and the line bends less than about 63 degrees at each of them (the cosine)
FRESH = 0.8               # s: a picture older than this is not used any more
STILL = 0.03              # an icon that moved less than this stands still ...
STILL_FROM, STILL_TO = 0.08, 0.32      # ... compared with the pictures that are this many seconds older
STILL_FOR = 0.2           # ... of which the oldest must be at least this old
MOVED = 0.17              # an icon that moves is at most this far from where one was on the picture before
START = 2.0               # s after the throw: from here on the known lines are swiped when nothing was seen yet
GAME_SECONDS = 10.0       # s after the throw: the little game is certainly over
QUIET = 1.2               # s without icons (after some were seen): the little game is over
ROW_LIFE = 3.0            # s a row that was seen standing still is still visited
GATE_ICONS = 12           # moving icons seen before the place to wait for the stream is chosen
GATE_LONG = 0.40          # ... and they must lie at least this far apart along the stream
GATE_NEAR = 0.2           # icons this close to the gate (along the stream) tell how wide it must be
GATE_SIDE = 0.07          # the gate reaches this far past the outermost of them
GATE_HALF = 0.12          # ... and at least this far to both sides
GATE_TIMES = 4            # swipes over the gate in one go (there and back)
LEAD = 2.8                # s between the tap on the button and the first icons
HOLD = 8.0                # the other side's charged attack goes first: ours is waited for this long after it

# Where the icons of a type come by, from recordings of real fights: "gates" are lines across a stream of
# icons (every icon has to pass there), "rows" are places where icons flash up standing still.
KNOWN = {
    "water": {"gates": [(0.68, 0.39, 0.68, 0.78)]},
    "flying": {"gates": [(0.62, 0.42, 0.62, 0.87)]},
    "electric": {"gates": [(0.26, 0.70, 0.76, 0.70)]},
    "ghost": {"rows": [(0.42, 0.56, 0.62, 0.56), (0.29, 0.79, 0.50, 0.79), (0.55, 0.79, 0.75, 0.79)]},
}
# The types that are not known yet get these lines until their icons are seen: a cross and two lines through
# the middle of the screen.
STAR = [(0.18, 0.36, 0.82, 0.86), (0.82, 0.36, 0.18, 0.86), (0.12, 0.60, 0.88, 0.60), (0.50, 0.32, 0.50, 0.90)]


def known(kind, learned=None):
    """What is known about the little game of a type: {"gates": [...], "rows": [...]}, both empty when nothing
    is.  The built-in knowledge (from recordings) goes first; for the other types `learned` is used: what an
    earlier game of this type found (Game.learned())."""
    base = KNOWN.get(str(kind).lower()) or learned or {}
    return {"gates": [tuple(g) for g in base.get("gates") or []], "rows": [tuple(r) for r in base.get("rows") or []]}


def _ms(a, b):
    return max(int(round(_dist(a, b) / SPEED * 1000)), MIN_MS)


def _swipe(a, b):
    a, b = _clip(a), _clip(b)
    return (round(float(a[0]), 4), round(float(a[1]), 4), round(float(b[0]), 4), round(float(b[1]), 4), _ms(a, b))


def _wu(points):
    """Points (x, y in fractions) -> array in screen widths."""
    return np.array([(x, y * ASPECT) for x, y in points], np.float64)


class Game:
    """One little game.  kind: the type of the charged attack.  t0: when it was thrown.  learned: what earlier
    games of this type found (see learned())."""

    def __init__(self, kind, t0=0.0, learned=None):
        self.kind = str(kind).lower()
        self.t0 = t0
        self.frames = []                   # [(time, [icons])] of the last moments
        self.first = None                  # when icons were first seen
        self.last = None                   # ... and last
        self.pictures = 0                  # pictures with icons on them
        self.icons = 0                     # icons seen in all (one icon is seen on several pictures)
        self.swipes = 0                    # swipes planned (for the log)
        self.rows = {}                     # row (x1, y1, x2, y2) -> when it was last seen (None: known beforehand)
        self.trail = []                    # where moving icons were seen in this game
        self.gate = None                   # the line across the stream that is swiped: (x1, y1, x2, y2)
        k = known(self.kind, learned)
        self.prior = list(k["gates"])      # gates that are known for this type
        for r in k["rows"]:
            self.rows[tuple(r)] = None
        self.builtin = self.kind in KNOWN
        self.turn = 0
        self.blind = True                  # swipe what is known of the type when no icons are seen (see hold())

    # ---------------------------------------------------------------- what is seen ---
    def see(self, t, icons):
        """The icons found on the picture that was taken at time t."""
        icons = [tuple(p) for p in icons]
        self.frames.append((t, icons))
        self.frames = [f for f in self.frames if f[0] >= t - 1.5]
        if not icons:
            return
        self.pictures += 1
        self.icons += len(icons)
        if self.first is None:
            self.first = t
            if not self.blind:
                self.t0 = t - LEAD                     # (it was waited for: this is when it really started)
        self.last = t
        for grp in groups(icons):
            moving = self.moving(grp)
            if moving is False and len(grp) >= 2:      # a row that stands still is remembered
                self._remember((grp[0][0], grp[0][1], grp[-1][0], grp[-1][1]), t)
            elif moving:
                self.trail += [p for p in grp if all(_dist(p, q) > 0.02 for q in self.trail[-60:])]
                del self.trail[600:]                   # (the first ones stay: they tell where the stream starts)
        self._find_gate()

    def _remember(self, row, t):
        for old in list(self.rows):
            if _dist(old[:2], row[:2]) <= 0.09 and _dist(old[2:], row[2:]) <= 0.09:
                self.rows[old] = t if t is not None else self.rows[old]
                return
        if len(self.rows) < 8:
            self.rows[row] = t

    def _find_gate(self):
        """The place to wait for a stream of icons: a line across it, halfway along the part of the screen
        where the icons were seen, as wide as the stream has been there.  Every icon of the stream has to pass
        it, whatever way the stream bends, so the finger does not have to know where each icon is right now.
        The direction of the stream: from where its first icons were seen to where the others were."""
        if len(self.trail) < GATE_ICONS:
            return
        pts = _wu(self.trail)
        src = pts[:3].mean(axis=0)
        d = pts.mean(axis=0) - src
        n = float(np.hypot(d[0], d[1]))
        if n < 0.10:
            return                                      # (icons around one place: no stream)
        axis = d / n
        across = np.array([-axis[1], axis[0]])
        along, side = (pts - src) @ axis, (pts - src) @ across
        if along.max() - along.min() < GATE_LONG:
            return                                      # (too little of the stream was seen)
        at = float(along.min() + along.max()) / 2.0
        near = np.abs(along - at) <= GATE_NEAR
        if not near.any():
            return
        lo, hi = float(side[near].min()) - GATE_SIDE, float(side[near].max()) + GATE_SIDE
        centre = (lo + hi) / 2.0
        lo, hi = min(lo, centre - GATE_HALF), max(hi, centre + GATE_HALF)
        p, q = src + axis * at + across * lo, src + axis * at + across * hi
        a, b = _clip((p[0], p[1] / ASPECT)), _clip((q[0], q[1] / ASPECT))
        self.gate = (round(float(a[0]), 3), round(float(a[1]), 3), round(float(b[0]), 3), round(float(b[1]), 3))

    def learned(self):
        """What this game found, to give to the next Game of this type: the rows where icons stood still and
        the gate of the stream.  None when nothing was seen, or when the type is known from recordings."""
        rows = [tuple(round(float(v), 3) for v in r) for r, t in self.rows.items() if t is not None]
        if self.builtin or (not rows and self.gate is None):
            return None
        return {"rows": rows, "gates": [self.gate] if self.gate else []}

    # ---------------------------------------------------------------- what to do ---
    def hold(self, now, wait=HOLD):
        """The attack has to wait: the other side threw a charged attack in the same turn and theirs goes
        first.  Ours comes after it, nobody knows exactly when - or not at all.  So from now on only icons
        that are seen are swiped (nothing blind: a swipe over the fight itself could tap a button), and the
        game is given up `wait` seconds from now when none came."""
        if self.first is None:
            self.blind = False
            self.t0 = now + wait - GAME_SECONDS

    def over(self, now):
        if now - self.t0 > GAME_SECONDS:
            return True
        return self.last is not None and now - self.last > QUIET

    def moving(self, grp):
        """Do the icons of this group move (a stream: True) or stand still (a row that flashes up: False)?
        None when that cannot be told (yet): icons that have only just appeared.  An icon stands still when it
        was at the same place on every picture of the last quarter of a second (one older picture is not
        enough: in a stream the next icon can be just where this one was, and the video repeats a picture now
        and then); it moves when the pictures before show an icon a little further on instead."""
        if not self.frames:
            return None
        t, newest = self.frames[-1]
        refs = [f for f in self.frames[:-1] if STILL_FROM <= t - f[0] <= STILL_TO]
        if not refs or t - refs[0][0] < STILL_FOR:
            return None
        mine = [p for p in grp if any(_dist(p, q) <= 1e-9 for q in newest)]
        if not mine:
            return None
        still = moved = 0
        for p in mine:
            if all(any(_dist(p, q) <= STILL for q in icons) for _t, icons in refs):
                still += 1
            elif not any(_dist(p, q) <= STILL for q in refs[-1][1]) and any(_dist(p, q) <= MOVED for q in refs[-1][1]):
                moved += 1                 # (nothing was here on the picture before, but an icon was close by)
        if still * 2 > len(mine):
            return False
        if moved * 2 > len(mine):
            return True
        return None

    def plan(self, now):
        """The swipes to make now: [(x1, y1, x2, y2, ms), ...] in fractions of the screen; [] = nothing (the
        icons are not there yet, or the game is over)."""
        if self.over(now):
            return []
        if self.first is None and (not self.blind or now - self.t0 < START):
            return []
        pts = []
        if self.frames and now - self.frames[-1][0] <= FRESH:
            pts = list(self.frames[-1][1])             # (the newest picture, when it is not too old)
        self.turn += 1
        flip = self.turn % 2 == 1                      # (there and back: not always from the same side)
        out = []
        rows = [r for r, seen in self.rows.items() if seen is None or now - seen <= ROW_LIFE]
        for row in rows:                               # rows of icons that stand still: they come back there
            a, b = _stretch(row[:2], row[2:], REACH)
            out.append(_swipe(b, a) if flip else _swipe(a, b))
        gates = self.prior or ([self.gate] if self.gate else [])
        for g in gates:                                # the place where the stream comes by: there and back
            out += [_swipe(g[:2], g[2:]), _swipe(g[2:], g[:2])] * max(GATE_TIMES // (2 * len(gates)), 1)
        painted = False
        for grp in groups(pts):
            if all(any(_near_line(p, r) <= ICON_R for r in rows) for p in grp):
                continue                               # (these icons are on a row that is swiped already)
            moving = self.moving(grp)
            if gates and moving is not False:
                continue                               # (a stream: the gate takes care of it)
            out += self._paint(grp, moving is not False, flip)
            painted = True
        if not out or (not gates and not rows and not painted):
            out += [_swipe(p[:2], p[2:]) for p in STAR]        # nothing known, nothing seen: try everywhere
        out = out[:MAX_SWIPES]
        self.swipes += len(out)
        return out

    def _paint(self, grp, moving, flip=False):
        """Swipes that cover the place where a group of icons is.  Icons in a smooth line (a row, a stream that
        follows one path) get one swipe along that line: the icons behind follow the same path, so it does not
        matter that the picture is a little old.  A group that is spread out gets lines next to each other
        over the whole strip the icons are in."""
        reach = REACH_MOVING if moving else REACH
        if len(grp) == 1:
            a, b = _stretch(grp[0], grp[0], reach)
            return [_swipe(b, a) if flip else _swipe(a, b)]
        line = _chain(grp)
        if _smooth(line):
            line = _simplify(line, 0.03)
            first, _x = _stretch(line[0], line[1], reach)
            _x, last = _stretch(line[-2], line[-1], reach)
            line = [first] + line[1:-1] + [last]
            if flip:
                line = line[::-1]
            return [_swipe(a, b) for a, b in zip(line, line[1:])]
        pts = np.array([(x, y * ASPECT) for x, y in grp], np.float64)
        mid = pts.mean(axis=0)
        c = pts - mid
        axis = np.linalg.svd(c, full_matrices=False)[2][0]           # the direction of the group (in widths)
        across = np.array([-axis[1], axis[0]])
        along, side = c @ axis, c @ across
        a0, a1 = float(along.min()) - reach, float(along.max()) + reach
        edge = SIDE_MOVING if moving else 0.0
        s0, s1 = float(side.min()) - edge, float(side.max()) + edge
        n = min(max(int(math.ceil((s1 - s0) / LINE_GAP)), 1), MAX_LINES)
        out = []
        for i in range(n):
            sv = (s0 + s1) / 2.0 if n == 1 else s0 + (s1 - s0) * (i + 0.5) / n
            p = mid + axis * a0 + across * sv
            q = mid + axis * a1 + across * sv
            p, q = (p[0], p[1] / ASPECT), (q[0], q[1] / ASPECT)
            out.append(_swipe(q, p) if (i % 2 == 1) != flip else _swipe(p, q))
        return out


def _chain(grp):
    """The points of a group as one path: from one end, always on to the nearest point that is left."""
    left = list(grp)                       # (groups() gave them sorted along the longest direction)
    path = [left.pop(0)]
    while left:
        nxt = min(left, key=lambda q: _dist(path[-1], q))
        left.remove(nxt)
        path.append(nxt)
    return path


def _smooth(path):
    """Is this path a smooth line (no sharp bends, no big jumps)?"""
    for a, b in zip(path, path[1:]):
        if _dist(a, b) > CHAIN_GAP:
            return False
    for a, b, c in zip(path, path[1:], path[2:]):
        v1 = (b[0] - a[0], (b[1] - a[1]) * ASPECT)
        v2 = (c[0] - b[0], (c[1] - b[1]) * ASPECT)
        n1, n2 = math.hypot(*v1), math.hypot(*v2)
        if n1 < 1e-6 or n2 < 1e-6:
            continue
        cos = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
        if cos < CHAIN_BEND:
            return False
    return True


def _simplify(path, tol):
    """The path with the points left out that lie (nearly) on the line between their neighbours."""
    if len(path) <= 2:
        return list(path)
    a, b = path[0], path[-1]
    far, where = max((_near_line(p, (a[0], a[1], b[0], b[1])), i) for i, p in enumerate(path[1:-1], 1))
    if far <= tol:
        return [a, b]
    return _simplify(path[:where + 1], tol)[:-1] + _simplify(path[where:], tol)


def _near_line(p, row):
    """Distance (screen widths) from a point to the line piece row = (x1, y1, x2, y2)."""
    ax, ay, bx, by = row[0], row[1] * ASPECT, row[2], row[3] * ASPECT
    px, py = p[0], p[1] * ASPECT
    dx, dy = bx - ax, by - ay
    n = dx * dx + dy * dy
    t = 0.0 if n < 1e-9 else min(max(((px - ax) * dx + (py - ay) * dy) / n, 0.0), 1.0)
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
