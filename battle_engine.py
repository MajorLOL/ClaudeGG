#!/usr/bin/env python3
"""Battle brain for GO Battle League (PvP).

This module is the decision part of the auto battle feature.  It does not
touch the phone: it only answers questions such as

  * which charged attack is best against the Pokémon that is on the field,
  * should this incoming charged attack be shielded,
  * which Pokémon should come in after a faint.

Game data (base stats, moves, type chart, CP multipliers) comes from
models/battle_data.json, built by tools/build_battle_data.py from the open
PvPoke data (MIT License, Copyright (c) 2019 pvpoke), including the moveset
PvPoke's Great League rankings recommend for each opponent.  The choice of
charged attack (plan_kill, best_charged, bait) and the shield decision of a
duel (should_shield, cycle_damage) follow PvPoke's ActionLogic.js; a real
battle of three against three decides on its shields with use_shield;
tools/crosscheck_gbl_lab.py compares the duels with a simulator that matches
PvPoke.

Damage formula (PvP):
    floor(power * STAB * attack/defense * effectiveness * 0.5 * 1.3) + 1
with STAB 1.2, super effective 1.6, resisted 0.625, immune/double resisted
0.390625, and Shadow Pokémon at attack x1.2 / defense x0.8333.

    python3 battle_engine.py --team            # show the team and its stats
    python3 battle_engine.py medicham          # best moves against a foe
"""
import difflib
import json
import math
import os
import re
import sys
import unicodedata

BONUS = 1.3
STAB = 1.2
SUPER = 1.6
RESIST = 0.625
DOUBLE_RESIST = 0.390625
SHADOW_ATK = 1.2
SHADOW_DEF = 0.83333331

_DATA = None
_DATA_PATHS = []


def data_paths():
    here = os.path.dirname(os.path.abspath(__file__))
    return [os.path.join(here, "models", "battle_data.json"),
            os.path.join(os.path.expanduser("~"), "models", "battle_data.json"),
            os.path.join(here, "battle_data.json")]


def load(path=None):
    """Load (and cache) the game data."""
    global _DATA
    if _DATA is not None and path is None:
        return _DATA
    for p in ([path] if path else data_paths()):
        if p and os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                _DATA = json.load(f)
            return _DATA
    raise FileNotFoundError("battle_data.json not found (looked in %s)" %
                            ", ".join(data_paths()))


# ---------------------------------------------------------------- types ---

def type_mult(move_type, def_types):
    """Type effectiveness of a move type against the defending types."""
    chart = load()["types"]
    mult = 1.0
    for t in def_types:
        res, weak, imm = chart[t]
        if move_type in weak:
            mult *= SUPER
        elif move_type in res:
            mult *= RESIST
        elif move_type in imm:
            mult *= DOUBLE_RESIST
    return mult


# ---------------------------------------------------------------- moves ---

class Move:
    """A fast (energy > 0 is False) or charged move."""

    def __init__(self, move_id):
        row = load()["moves"].get(move_id)
        if row is None:
            raise KeyError("unknown move: %s" % move_id)
        self.id = move_id
        (self.name, self.type, self.power, self.energy,
         self.gain, self.turns) = row

    @property
    def charged(self):
        return self.energy > 0

    def __repr__(self):
        return "<%s>" % self.name


def _norm(text):
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def find_move(text, cutoff=0.78):
    """Look up a move id from a (possibly OCR-damaged) name."""
    if not text:
        return None
    moves = load()["moves"]
    want = _norm(text)
    if not want:
        return None
    names = {}
    for mid, row in moves.items():
        names.setdefault(_norm(row[0]), mid)
    if want in names:
        return names[want]
    close = difflib.get_close_matches(want, list(names), n=1, cutoff=cutoff)
    return names[close[0]] if close else None


def find_species(text, cutoff=0.8):
    """Look up a species id from a (possibly OCR-damaged) name."""
    if not text:
        return None
    mons = load()["mons"]
    want = _norm(re.sub(r"\(shadow\)|shadow", "", text, flags=re.I))
    if not want:
        return None
    names = {}
    for sid, row in mons.items():
        names.setdefault(_norm(row[0]), sid)
    if want in names:
        return names[want]
    by_words = {}                                       # "Galarian Corsola" is "Corsola (Galarian)"
    for n, sid in names.items():
        by_words.setdefault(tuple(sorted(n.split())), sid)
    if tuple(sorted(want.split())) in by_words:
        return by_words[tuple(sorted(want.split()))]
    forms = [(n, sid) for n, sid in names.items() if n.startswith(want + " ")]
    if forms:                                           # the game shows "Gourgeist" for all its sizes
        for n, sid in forms:
            if any(w in n.split() for w in FORM_DEFAULTS):
                return sid
        return forms[0][1]
    close = difflib.get_close_matches(want, list(names), n=1, cutoff=cutoff)
    if close:
        return names[close[0]]
    # a stray word in front of or behind the name ("Cep Tropius": the small CP in the name box misread):
    # the longest word that is a name on its own
    if len(want.split()) > 1:
        for w in sorted((w for w in want.split() if len(w) >= 4), key=len, reverse=True):
            close = difflib.get_close_matches(w, list(names), n=1, cutoff=max(cutoff, 0.85))
            if close:
                return names[close[0]]
    return None


FORM_DEFAULTS = ("average", "normal", "standard", "incarnate", "ordinary", "male")   # the form to take when
                                                                                    # the name has none


# -------------------------------------------------------------- pokémon ---

def cpm(level):
    table = load()["cpm"]
    return table[int(round((level - 1) * 2))]


def calc_cp(base, ivs, level):
    c = cpm(level)
    cp = ((base[0] + ivs[0]) * math.sqrt(base[1] + ivs[1]) *
          math.sqrt(base[2] + ivs[2]) * c * c) / 10.0
    return max(10, int(cp))


class Mon:
    """One Pokémon in a battle: stats, moves and its current state."""

    def __init__(self, species_id, level=None, ivs=None, shadow=False,
                 fast=None, charged=None, stats=None, pos=0):
        row = load()["mons"][species_id]
        (self.name, self.types, b_atk, b_def, b_hp, fast_ids, charged_ids,
         default_ivs, _shadow_ok) = row
        self.species = species_id
        self.shadow = bool(shadow)
        self.base = (b_atk, b_def, b_hp)
        self.pos = pos
        if level is None:
            level = default_ivs[0]
        if ivs is None:
            ivs = default_ivs[1:4]
        self.level = level
        self.ivs = tuple(ivs)
        self.cp = calc_cp(self.base, self.ivs, level)
        c = cpm(level)
        atk = c * (b_atk + self.ivs[0])
        dfn = c * (b_def + self.ivs[1])
        hp = max(10, int(c * (b_hp + self.ivs[2])))
        if stats:                       # fitted average stats override the IVs
            atk, dfn, hp = stats
        if self.shadow:
            atk *= SHADOW_ATK
            dfn *= SHADOW_DEF
        self.atk, self.dfn, self.max_hp = atk, dfn, hp
        if fast is None or not charged:
            f2, c2 = default_moveset(species_id)
            fast = fast or f2
            charged = charged or c2
        self.fast = Move(fast)
        self.charged = [Move(m) for m in charged]
        self.hp = hp
        self.energy = 0
        self.shields = 2

    @property
    def label(self):
        return ("Shadow " if self.shadow else "") + self.name

    @property
    def hp_frac(self):
        return self.hp / float(self.max_hp)

    @property
    def alive(self):
        return self.hp > 0

    def copy(self):
        m = Mon.__new__(Mon)
        m.__dict__.update(self.__dict__)
        m.charged = list(self.charged)
        return m

    def __repr__(self):
        return "<%s CP%d %d/%d HP>" % (self.label, self.cp, self.hp,
                                       self.max_hp)


def damage(move, attacker, defender):
    """PvP damage of `move` from attacker onto defender."""
    stab = STAB if move.type in attacker.types else 1.0
    eff = type_mult(move.type, defender.types)
    return int(move.power * stab * (attacker.atk / defender.dfn) * eff *
               0.5 * BONUS) + 1


LEAGUE_CAP = "1500"      # the engine rates opponents at Great League level


def ranked_moveset(species_id, cap=LEAGUE_CAP):
    """The moveset PvPoke's rankings recommend (fast, [charged, ...]) or None."""
    row = (load().get("sets") or {}).get(cap, {}).get(species_id)
    moves = load()["moves"]
    if not row or len(row) < 2 or any(m not in moves for m in row):
        return None
    return row[0], list(row[1:3])


def guessed_moveset(species_id):
    """Fallback for species the rankings do not list: best fast move (damage x
    energy per turn) and the two charged moves with the most damage per energy."""
    row = load()["mons"][species_id]
    moves = load()["moves"]
    fast_ids, charged_ids = row[5], row[6]

    def fscore(mid):
        m = moves[mid]
        return (m[2] * m[4]) / float(m[5] * m[5])   # dpt * ept

    fast = max(fast_ids, key=fscore)

    def cscore(mid):
        m = moves[mid]
        return m[2] / float(m[3]) if m[3] else 0     # damage per energy

    ranked = sorted(charged_ids, key=cscore, reverse=True)
    return fast, ranked[:2]


def default_moveset(species_id):
    """Likely moves of an opponent: the PvPoke ranking set, else a guess."""
    return ranked_moveset(species_id) or guessed_moveset(species_id)


def fit_stats(species_id, cp, hp, shadow=False):
    """Find level/IV combinations that give this CP and HP.

    Returns (level, ivs, stats) where stats are the average attack, defense
    and HP over all matching combinations, or None if nothing matches.
    """
    row = load()["mons"][species_id]
    b_atk, b_def, b_hp = row[2], row[3], row[4]
    table = load()["cpm"]
    found = []
    for i in range(0, 2 * 50 - 1 + 1):            # levels 1 .. 50
        level = 1 + i / 2.0
        c = table[i]
        for hp_iv in range(16):
            if max(10, int(c * (b_hp + hp_iv))) != hp:
                continue
            for a in range(16):
                for d in range(16):
                    got = ((b_atk + a) * math.sqrt(b_def + d) *
                           math.sqrt(b_hp + hp_iv) * c * c) / 10.0
                    if int(got) == cp:
                        found.append((level, (a, d, hp_iv), c))
    if not found:
        return None
    n = float(len(found))
    atk = sum(c * (b_atk + iv[0]) for _l, iv, c in found) / n
    dfn = sum(c * (b_def + iv[1]) for _l, iv, c in found) / n
    best = min(found, key=lambda x: abs(x[2] * (b_atk + x[1][0]) - atk))
    return best[0], best[1], (atk, dfn, float(hp))


# ----------------------------------------------------------------- team ---

DEFAULT_TEAM = [
    {"species": "noctowl", "cp": 1497, "hp": 162, "fast": "WING_ATTACK",
     "charged": ["SHADOW_BALL", "SKY_ATTACK"]},
    {"species": "lapras", "shadow": True, "cp": 1489, "hp": 174,
     "fast": "ICE_SHARD", "charged": ["FRUSTRATION", "SURF"]},
    {"species": "lanturn", "cp": 1494, "hp": 186, "fast": "SPARK",
     "charged": ["SURF", "THUNDERBOLT"]},
]


def team_file():
    return os.path.join(os.path.expanduser("~"), "battle_team.json")


def build_team(entries):
    """Make Mon objects (in party order) from a list of team entries.

    Entry keys: species (PvPoke id), shadow, cp + hp (stats are fitted from
    these) or level + ivs, fast, charged (list of move ids).
    """
    team = []
    for pos, e in enumerate(entries):
        sid = e["species"]
        stats = level = ivs = None
        if e.get("cp") and e.get("hp"):
            fit = fit_stats(sid, int(e["cp"]), int(e["hp"]))
            if fit:
                level, ivs, stats = fit
        if level is None and e.get("level"):
            level, ivs = e["level"], e.get("ivs")
        team.append(Mon(sid, level=level, ivs=ivs, shadow=e.get("shadow"),
                        fast=e.get("fast"), charged=e.get("charged"),
                        stats=stats, pos=pos))
    return team


def load_team(path=None):
    """The team to fight with: ~/battle_team.json if present, else the preset."""
    path = path or team_file()
    entries = DEFAULT_TEAM
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                entries = json.load(f)
        except (OSError, ValueError):
            entries = DEFAULT_TEAM
    return build_team(entries)


def foe_from_text(name, shadow=False):
    """A guessed opponent from an on-screen name (None when unknown)."""
    sid = find_species(name)
    if not sid:
        return None
    return Mon(sid, shadow=shadow)


# ------------------------------------------------------------ decisions ---

def _dpe(move, dmg):
    return dmg / float(move.energy)


def best_charged(active, dmg):
    """PvPoke's 'best' charged move: the most damage per energy, where a move
    must beat the cheaper one by a clear margin to take over."""
    best = active[0]
    for m in active[1:]:
        if _dpe(m, dmg[m.id]) - _dpe(best, dmg[best.id]) > 0.03:
            best = m
    return best


def plan_kill(me, foe, energy, foe_hp, foe_shields, active, dmg, fast_dmg,
              limit=500):
    """PvPoke's planner: the charged moves that knock the foe out soonest.

    Walks forward in time over 'wait until the move is charged, then throw it'
    steps (and plain fast-move farming).  A foe with shields soaks one throw
    each for 1 damage.  Returns the list of moves, empty when farming with the
    fast move alone is quickest, or None when no plan was found.
    """
    fast = me.fast
    gain, fturns = fast.gain, fast.turns
    queue = [(0, 0, energy, foe_hp, foe_shields, ())]
    seq = 1
    expanded = 0
    while queue and expanded < limit:
        expanded += 1
        turn, _n, en, hp, sh, moves = queue.pop(0)
        if hp <= 0:
            return list(moves)
        new = []
        if fast_dmg > 0:
            farm = int(math.ceil(hp / float(fast_dmg)))
            new.append((turn + farm * fturns, en + gain * farm, 0, sh, moves))
        for m in active:
            if en >= m.energy:
                wait = 0
            elif gain > 0:
                wait = int(math.ceil((m.energy - en) / float(gain))) * fturns
            else:
                continue
            k = wait // fturns
            nhp = hp - fast_dmg * k - (1 if sh > 0 else dmg[m.id])
            new.append((turn + wait + 1, en - m.energy + gain * k, nhp,
                        sh - 1 if sh > 0 else sh, moves + (m,)))
        for t, e, h, s_, mv in new:
            # skip a state that an earlier, at least as good one already covers
            if any(q[0] <= t and q[3] <= h and q[2] >= e and q[4] <= s_
                   for q in queue):
                continue
            i = 0
            while i < len(queue) and queue[i][0] <= t:
                i += 1
            queue.insert(i, (t, seq, e, h, s_, mv))
            seq += 1
    return None


def pick_charged(me, foe, energy, foe_shields=0, foe_hp=None):
    """Choose the charged attack to throw now (PvPoke's default decision logic).

    Returns (move or None, reason).  None means: keep using the fast move.
    The rules, in order: throw a move that finishes the foe; when the fight will
    take many cycles just build up to the best move; otherwise follow the
    quickest plan to knock the foe out, baiting a shield with a cheap, efficient
    move when the foe still has shields.
    """
    foe_hp = foe.hp if foe_hp is None else foe_hp
    dmg = {m.id: damage(m, me, foe) for m in me.charged}
    # cheapest first; of two that cost the same, the one that hurts THIS foe most (not the highest power on
    # paper: Sky Attack beats Shadow Ball against an Abomasnow, at 50 energy each)
    active = sorted(me.charged, key=lambda m: (m.energy, -dmg[m.id], -m.power))
    if not active or energy < active[0].energy:
        return None, "not enough energy"
    fast_dmg = damage(me.fast, me, foe)

    def pays(m):
        return m.energy <= energy

    # 1. Finish the opponent: cheapest move that is enough.
    if foe_shields <= 0 and foe_hp > fast_dmg:
        for m in active:
            if pays(m) and dmg[m.id] >= foe_hp:
                return m, "%s finishes it (%d dmg >= %d HP)" % (
                    m.name, dmg[m.id], foe_hp)

    def foe_would_shield(m):
        return should_shield(me, foe, foe_shields, m, foe_hp)[0]

    best = best_charged(active, dmg)

    # 2. Many cycles to go: just build up to the best move (or a cheap bait).
    cycle = dmg[best.id] + fast_dmg * int(math.ceil(
        best.energy / float(max(me.fast.gain, 1))))
    if foe_hp / float(max(cycle, 1)) > 2:
        pick = best
        if foe_shields > 0 and len(active) > 1 and \
                any(foe_would_shield(m) for m in active):
            pick = active[0]
        if energy < pick.energy:
            return None, "building up to %s" % pick.name
        return pick, "%s is the best attack (%d dmg, x%.2f)" % (
            pick.name, dmg[pick.id], type_mult(pick.type, foe.types))

    # 3. Few cycles to go: follow the plan that knocks the foe out soonest.
    plan = plan_kill(me, foe, energy, foe_hp, foe_shields, active, dmg,
                     fast_dmg)
    if not plan:
        return None, "farming down with the fast move is quickest"
    first = plan[0]

    if foe_shields > 0 and len(active) > 1:
        # Keep building towards a more efficient (bait) move when it is not yet
        # charged ...
        for m in active[1:]:
            if energy < m.energy and _dpe(m, dmg[m.id]) > _dpe(first, dmg[first.id]):
                return None, "building up to %s to bait the shield" % m.name
        # ... but do not bait with a weak move when the foe will not shield a
        # clearly stronger one.
        for m in active[1:]:
            if pays(m) and _dpe(m, dmg[m.id]) / _dpe(first, dmg[first.id]) > 1.5 \
                    and not foe_would_shield(m):
                first = m

    # no shields: lead with the hardest hitting move of the plan
    if foe_shields <= 0:
        first = max(plan, key=lambda m: dmg[m.id])
    # shields up: prefer the cheap move when it is the more efficient one
    elif len(active) > 1 and active[0].energy <= first.energy and \
            _dpe(active[0], dmg[active[0].id]) > _dpe(first, dmg[first.id]):
        first = active[0]
    if len(active) > 1 and active[0].energy == first.energy and \
            _dpe(active[0], dmg[active[0].id]) > _dpe(first, dmg[first.id]):
        first = active[0]

    if energy < first.energy:
        return None, "building up to %s" % first.name
    how = ("%s as bait (foe has %d shield%s)" % (
        first.name, foe_shields, "" if foe_shields == 1 else "s")
        if foe_shields > 0 else
        "%s is the best attack (%d dmg, x%.2f)" % (
            first.name, dmg[first.id], type_mult(first.type, foe.types)))
    return first, how


def foe_hit(foe, me, foe_move=None, energy=None):
    """(damage, move) of the incoming charged attack.

    With no known move the foe's hardest-hitting charged move is assumed -
    of those it can pay for, when `energy` says how much energy it has at
    most (see fast_rate): a foe that has been on the field for five seconds
    cannot throw an attack of 75 energy.  (When it could pay for none of them
    the count is wrong: all of them are possible again.)
    """
    if foe_move is not None:
        return damage(foe_move, foe, me), foe_move
    moves = can_throw(foe, energy)
    best = max(moves, key=lambda m: damage(m, foe, me))
    return damage(best, foe, me), best


def can_throw(foe, energy=None):
    """The charged attacks `foe` can throw with `energy` at most (None: not
    known), all of them when that would be none."""
    if energy is None:
        return list(foe.charged)
    return [m for m in foe.charged if m.energy <= energy] or list(foe.charged)


def fast_rate(species_id):
    """(energy a second, energy per fast attack) this species gains at most,
    whichever of its fast attacks it has: the fastest charging one counts, so
    that what is worked out from it is an upper limit of the energy."""
    row = load()["mons"][species_id]
    moves = load()["moves"]
    fast = [moves[m] for m in row[5] if m in moves and moves[m][5] > 0]
    if not fast:
        return 10.0, 15
    return max(m[4] / (m[5] * 0.5) for m in fast), max(m[4] for m in fast)


def cheapest_charged(species_id):
    """The least energy a charged attack of this species costs, whichever
    two it has."""
    row = load()["mons"][species_id]
    moves = load()["moves"]
    costs = [moves[m][3] for m in row[6] if m in moves and moves[m][3] > 0]
    return min(costs) if costs else 35


def cycle_damage(foe, me, move, shields, foe_energy=None):
    """Damage of the fast attacks the foe needs to charge `move` again, for each
    shield we still have (plus one hit as margin).  This is PvPoke's idea of
    'can I still afford to let a charged attack connect': after this hit we must
    survive long enough to use our remaining shields on the next ones.

    foe_energy is the energy the foe has left after throwing `move`, when that
    is known (leftover energy shortens the next charge); without it a full
    charge is assumed."""
    fast = foe.fast
    if fast.gain <= 0:
        return 0
    need = move.energy - max((foe_energy or 0) - move.energy, 0)
    n = int(math.ceil(need / float(fast.gain))) + 1
    return (n * damage(fast, foe, me) + 1) * max(shields, 0)


def should_shield(foe, me, shields, foe_move=None, my_hp=None, foe_energy=None):
    """Decide whether to shield an incoming charged attack (PvPoke's rule).

    Returns (bool, reason).  `foe` throws `foe_move` at `me`, who has `shields`
    left.  Following PvPoke's ActionLogic.wouldShield, the shield is used when

      * the hit would leave too little HP to survive the foe's next round of
        fast attacks (cycle_damage) - this includes a hit that knocks us out, or
      * the foe has a charged move that we cannot afford to let connect: one that
        does at least HP/1.4 while its fast attacks hit hard (more than 1.5
        damage per turn), or at least the HP that is left after one round of
        fast attacks.

    Otherwise the shield is kept.  An unknown incoming move is taken to be the
    foe's hardest hit.  foe_energy: see cycle_damage.
    """
    my_hp = me.hp if my_hp is None else my_hp
    if shields <= 0:
        return False, "no shields left"
    dmg, mv = foe_hit(foe, me, foe_move)
    cycle = cycle_damage(foe, me, mv, shields, foe_energy)
    left = my_hp - dmg
    if dmg >= my_hp:
        return True, "%s would knock us out (%d >= %d HP)" % (mv.name, dmg,
                                                               my_hp)
    if left <= cycle:
        return True, ("%s (%d dmg) would leave %d HP, not enough for the next "
                      "fast attacks (%d)" % (mv.name, dmg, left, cycle))
    fast_dpt = damage(foe.fast, foe, me) / float(foe.fast.turns)
    for c in foe.charged:
        cd = damage(c, foe, me)
        if cd >= my_hp / 1.4 and fast_dpt > 1.5:
            return True, ("%s could follow (%d dmg of %d HP) and its fast "
                          "attacks hit hard" % (c.name, cd, my_hp))
        if cd >= my_hp - cycle:
            return True, ("%s (%d dmg) must not connect: only %d HP would be "
                          "left after a round of fast attacks" % (
                              c.name, cd, my_hp - cycle))
    return False, "%s (%d dmg) is survivable, keeping the shield" % (mv.name,
                                                                      dmg)


# In a battle of three against three a shield is worth what it saves, and it is worth nothing once the
# battle is over.  PvPoke's rule above is made for a duel of one against one: there the last shield is kept
# for the hit that would knock the Pokémon out.  In a real battle that rule let a Megahorn take 61% of a
# Lanturn's HP and a Dark Pulse 36% of a Noctowl's, and the battle ended with the shield unused.
SHIELD_HIT = 0.20         # a charged attack is shielded when it takes this part of our full HP or more ...
SHIELD_HIT_LAST = 0.10    # ... or this part when nothing is left to keep the shield for: the foe's last Pokémon
UNKNOWN_HIT = 0.45        # the charged attack of a foe that is not known is taken for this part of our full HP


def use_shield(foe, me, shields, my_hp=None, mine_left=3, foes_left=None,
               ready=False, foe_move=None, foe_energy=None):
    """Use a shield on the charged attack that is coming, in a real battle?

    Returns (bool, reason).  `foe` (None: not known) throws at `me`, who has
    `my_hp` HP and `shields` left.  mine_left / foes_left: how many Pokémon
    each side can still fight with, the ones on the field included (None: not
    known).  ready: a charged attack of ours was ready when theirs came.
    foe_energy: the energy the foe has at most (None: not known) - an attack
    it cannot pay for is not the one that is coming, which is how a cheap,
    weak attack thrown to draw a shield is told from the hard one.

      * our last Pokémon: a hit that knocks it out is always shielded;
      * a hit that knocks us out while our own charged attack is ready is
        shielded: that attack is still thrown then;
      * otherwise the shield is used on a hit worth it - one that takes
        SHIELD_HIT of our full HP or more (SHIELD_HIT_LAST when the foe or we
        are on the last Pokémon: no later use for the shield then);
      * it is kept for a small hit, and for a Pokémon that has so little HP
        left that there is hardly anything to save: it faints, the foe has
        spent its energy, and the next Pokémon comes in with the shield.

    What counts is the HP the shield saves: the damage of the hit, or what is
    left of our HP when that is less.  Which move is coming is not known, so
    it is taken to be the hardest one the foe can pay for (foe_hit).
    """
    my_hp = me.hp if my_hp is None else my_hp
    if shields <= 0:
        return False, "no shields left"
    if foe is None:
        dmg, name = int(round(UNKNOWN_HIT * me.max_hp)), "the attack of a foe that is not known"
    else:
        dmg, mv = foe_hit(foe, me, foe_move, foe_energy)
        name = mv.name
        if foe_move is None and foe_energy is not None:
            out = [m for m in foe.charged if m not in can_throw(foe, foe_energy)]
            if out:                    # (said first: why the hard one is not counted)
                use, why = use_shield(foe, me, shields, my_hp, mine_left, foes_left, ready, mv)
                return use, ("it can only be %s (%s costs %d energy, %s has %d at most) - %s"
                             % (name, " / ".join(m.name for m in out), min(m.energy for m in out),
                                foe.label, int(foe_energy), why))
    saved = max(min(dmg, my_hp), 0)
    part = saved / float(me.max_hp)
    pct = "%d%%" % int(round(100 * part))
    lethal = dmg >= my_hp
    if lethal and mine_left is not None and mine_left <= 1:
        return True, "%s would knock out our last Pokémon (%d >= %d HP)" % (name, dmg, my_hp)
    if lethal and ready:
        return True, ("%s would knock us out (%d >= %d HP) and our own charged "
                      "attack is ready" % (name, dmg, my_hp))
    last = ""
    if mine_left is not None and mine_left <= 1:
        last = "this is our last Pokémon"
    elif foes_left is not None and foes_left <= 1:
        last = "the foe is on its last Pokémon"
    limit = SHIELD_HIT_LAST if last else SHIELD_HIT
    if part >= limit:
        return True, ("%s would take %s of our HP (%d of %d)" % (name, pct, saved, me.max_hp)
                      + (" and %s: nothing to keep the shield for" % last
                         if last and part < SHIELD_HIT else ""))
    if lethal:
        return False, ("only %d HP (%s) left to save from %s - the shield is kept for the "
                       "next Pokémon" % (saved, pct, name))
    return False, "%s is a small hit (%d dmg, %s of our HP) - keeping the shield" % (name, dmg, pct)


# ----------------------------------------------------------- simulation ---

def simulate(a, b, shields_a=2, shields_b=2, max_turns=1200):
    """Play out a 1v1 with both sides using this module's own rules.

    Time moves in 0.5 s turns.  Returns (hp_a_left, hp_b_left) as fractions
    of each Pokémon's maximum HP.  Neither argument is changed.
    """
    side = []
    for mon, sh in ((a.copy(), shields_a), (b.copy(), shields_b)):
        side.append({"m": mon, "hp": mon.hp, "en": min(100, mon.energy),
                     "sh": sh, "ready": 0, "land": None})
    first = 0 if a.atk >= b.atk else 1                 # ties: higher attack first
    order = (first, 1 - first)

    for t in range(max_turns):
        # fast moves that land this turn
        for i in order:
            s, o = side[i], side[1 - i]
            if s["land"] == t and s["hp"] > 0:
                o["hp"] -= damage(s["m"].fast, s["m"], o["m"])
                s["en"] = min(100, s["en"] + s["m"].fast.gain)
                s["land"] = None
        if side[0]["hp"] <= 0 or side[1]["hp"] <= 0:
            break
        for i in order:
            s, o = side[i], side[1 - i]
            if s["hp"] <= 0 or s["ready"] > t:
                continue
            mv, _why = pick_charged(s["m"], o["m"], s["en"], o["sh"],
                                    max(0, o["hp"]))
            if mv is not None:
                s["en"] -= mv.energy
                shield, _r = should_shield(s["m"], o["m"], o["sh"], mv,
                                           max(0, o["hp"]),
                                           foe_energy=s["en"])
                if shield:
                    o["sh"] -= 1
                    o["hp"] -= 1
                else:
                    o["hp"] -= damage(mv, s["m"], o["m"])
                if o["hp"] <= 0:
                    break
            if s["hp"] > 0 and s["land"] is None:
                s["land"] = t + s["m"].fast.turns
                s["ready"] = s["land"]
        if side[0]["hp"] <= 0 or side[1]["hp"] <= 0:
            break
    return (max(0, side[0]["hp"]) / float(a.max_hp),
            max(0, side[1]["hp"]) / float(b.max_hp))


def matchup(me, foe, my_shields=2, foe_shields=2):
    """Score in [-1, 1]: positive means `me` beats `foe` with HP to spare."""
    mine, theirs = simulate(me, foe, my_shields, foe_shields)
    return mine - theirs


def best_switch(candidates, foe, my_shields=2, foe_shields=2):
    """Pick the best Pokémon from `candidates` (alive team members).

    Returns (Mon, score) for the best matchup against `foe`; ties go to the
    lower party position.
    """
    scored = []
    for m in candidates:
        if m.hp <= 0:
            continue
        scored.append((matchup(m, foe, my_shields, foe_shields), -m.pos, m))
    if not scored:
        return None, 0.0
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return scored[0][2], scored[0][0]


def describe(team, foe):
    """Human readable summary of how each team member fares against `foe`."""
    lines = ["Foe: %s (%s) HP %d  moves: %s / %s" % (
        foe.label, "/".join(foe.types), foe.max_hp, foe.fast.name,
        ", ".join(c.name for c in foe.charged))]
    for m in team:
        fd = damage(m.fast, m, foe)
        parts = []
        for c in m.charged:
            parts.append("%s %d dmg x%.2f (%d en)" % (
                c.name, damage(c, m, foe), type_mult(c.type, foe.types),
                c.energy))
        mv, why = pick_charged(m, foe, 100, 0)
        lines.append("  #%d %-18s fast %s %d dmg | %s | best: %s | score %+.2f"
                     % (m.pos + 1, m.label, m.fast.name, fd, "; ".join(parts),
                        mv.name if mv else "-",
                        matchup(m, foe)))
    return "\n".join(lines)


# ------------------------------------------------------------------ cli ---

def main(argv):
    team = load_team()
    if len(argv) < 2 or argv[1] == "--team":
        for m in team:
            print("#%d %-16s CP%d  atk %.1f def %.1f hp %d  fast %s  charged %s"
                  % (m.pos + 1, m.label, m.cp, m.atk, m.dfn, m.max_hp,
                     m.fast.name, ", ".join(c.name for c in m.charged)))
        return 0
    foe = foe_from_text(" ".join(argv[1:]))
    if foe is None:
        print("unknown Pokémon: %s" % " ".join(argv[1:]))
        return 1
    print(describe(team, foe))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
