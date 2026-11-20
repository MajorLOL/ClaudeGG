#!/usr/bin/env python3
"""Battle brain for GO Battle League (PvP).

This module is the decision part of the auto battle feature.  It does not
touch the phone: it only answers questions such as

  * which charged attack is best against the Pokémon that is on the field,
  * should this incoming charged attack be shielded,
  * which Pokémon should come in after a faint.

Game data (base stats, moves, type chart, CP multipliers) comes from
models/battle_data.json, built by tools/build_battle_data.py from the open
PvPoke data (MIT License, Copyright (c) 2019 pvpoke).  The shield rule that
looks at the next round of fast attacks (cycle_damage) follows PvPoke's
ActionLogic.js.

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

# Shield rules (fractions of the defending Pokémon's maximum HP).
WEAK_HIT = 0.15          # below this a hit is "weak": never worth a shield
WEAK_RESISTED_HIT = 0.25  # a resisted hit below this is also not worth a shield
SHIELD_HIT_2 = 0.20      # with two shields, shield hits of at least this size
SHIELD_HIT_1 = 0.30      # with the last shield, only shield bigger hits
SHIELD_CURRENT = 0.60    # ... or hits that take this much of the current HP
# A charged attack is "not worth throwing" below this fraction of the foe's HP.
MIN_WORTH = 0.10
# Energy gained that we are willing to wait for a better charged attack.
WAIT_ENERGY = 25

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
    close = difflib.get_close_matches(want, list(names), n=1, cutoff=cutoff)
    return names[close[0]] if close else None


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


def default_moveset(species_id):
    """Likely moves of a species: best fast move and two best charged moves."""
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
    chosen = ranked[:2]
    return fast, chosen


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

def pick_charged(me, foe, energy, foe_shields=0, foe_hp=None):
    """Choose the charged attack to throw now.

    Returns (move or None, reason).  None means: keep using the fast move.
    """
    foe_hp = foe.hp if foe_hp is None else foe_hp
    rows = []
    for m in me.charged:
        rows.append((m, damage(m, me, foe), type_mult(m.type, foe.types)))
    afford = [r for r in rows if r[0].energy <= energy]
    if not afford:
        return None, "not enough energy"

    # 1. Finish the opponent: cheapest move that is enough.
    if foe_shields <= 0:
        kills = [r for r in afford if r[1] >= foe_hp]
        if kills:
            m, d, eff = min(kills, key=lambda r: (r[0].energy, -r[1]))
            return m, "%s finishes it (%d dmg >= %d HP)" % (m.name, d, foe_hp)

    # 2. Skip moves that are not worth the energy.
    worth = [r for r in afford if r[1] >= MIN_WORTH * foe.max_hp]
    if not worth:
        return None, "no attack worth throwing (all too weak)"

    if foe_shields > 0:
        # Foe may shield: lead with the cheapest decent move (bait), keep the
        # strong one for when the shield is gone.
        decent = [r for r in worth if r[2] >= 1.0] or worth
        m, d, eff = min(decent, key=lambda r: (r[0].energy, -r[1]))
        how = "%s as bait (foe has %d shield%s)" % (
            m.name, foe_shields, "" if foe_shields == 1 else "s")
    else:
        m, d, eff = max(worth, key=lambda r: (r[1], -r[0].energy))
        how = "%s is the best attack (%d dmg, x%.2f)" % (m.name, d, eff)

    # Wait for a clearly better move that is almost charged.
    if eff < 1.0:
        for om, od, oeff in rows:
            if om.energy > energy and om.energy - energy <= WAIT_ENERGY \
                    and oeff >= 1.0 and od > d:
                return None, "%s is resisted, waiting for %s" % (m.name,
                                                                  om.name)
    return m, how


def foe_hit(foe, me, foe_move=None):
    """(damage, move) of the incoming charged attack.

    With no known move the foe's hardest-hitting charged move is assumed.
    """
    if foe_move is not None:
        return damage(foe_move, foe, me), foe_move
    best = max(foe.charged, key=lambda m: damage(m, foe, me))
    return damage(best, foe, me), best


def cycle_damage(foe, me, move, shields):
    """Damage of the fast attacks the foe needs to charge `move` again, for each
    shield we still have (plus one hit as margin).  This is PvPoke's idea of
    'can I still afford to let a charged attack connect': after this hit we must
    survive long enough to use our remaining shields on the next ones."""
    fast = foe.fast
    if fast.gain <= 0:
        return 0
    n = int(math.ceil(move.energy / float(fast.gain))) + 1
    return (n * damage(fast, foe, me) + 1) * max(shields, 0)


def should_shield(foe, me, shields, foe_move=None, my_hp=None):
    """Decide whether to shield an incoming charged attack.

    Returns (bool, reason).  A shield is not used when it is gone, and not for a
    weak attack (low damage) unless that attack would make us faint.  It is
    always used when the hit would make us faint, and when we would be too weak
    after the hit to survive the foe's next round of fast attacks (PvPoke's
    shield rule, see cycle_damage).
    """
    my_hp = me.hp if my_hp is None else my_hp
    if shields <= 0:
        return False, "no shields left"
    dmg, mv = foe_hit(foe, me, foe_move)
    eff = type_mult(mv.type, me.types)
    if dmg >= my_hp:
        return True, "%s would knock us out (%d >= %d HP)" % (mv.name, dmg,
                                                               my_hp)
    frac = dmg / float(me.max_hp)
    if frac < WEAK_HIT:
        return False, "%s is weak (%d dmg), no shield" % (mv.name, dmg)
    if eff < 1.0 and frac < WEAK_RESISTED_HIT:
        return False, "%s is resisted (%d dmg), no shield" % (mv.name, dmg)
    left = my_hp - dmg
    cycle = cycle_damage(foe, me, mv, shields)
    if left <= cycle:
        return True, ("%s (%d dmg) would leave %d HP, not enough for the next fast attacks (%d)"
                      % (mv.name, dmg, left, cycle))
    if shields >= 2:
        if frac >= SHIELD_HIT_2:
            return True, "%s hits hard (%d dmg)" % (mv.name, dmg)
        return False, "%s is moderate (%d dmg), keeping shields" % (mv.name,
                                                                    dmg)
    if frac >= SHIELD_HIT_1 or dmg >= SHIELD_CURRENT * my_hp:
        return True, "%s is dangerous (%d dmg), using the last shield" % (
            mv.name, dmg)
    return False, "%s is moderate (%d dmg), saving the last shield" % (
        mv.name, dmg)


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
                                           max(0, o["hp"]))
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
    lines = ["Foe: %s (%s) HP %d" % (foe.label, "/".join(foe.types),
                                      foe.max_hp)]
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
