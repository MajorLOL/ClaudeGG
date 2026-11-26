"""Your Pokémon and the best teams for the leagues of now.

The bot scans the Pokémon storage (gamebot.scan_collection: name, CP and the appraisal bars of each Pokémon) into
~/collection.json.  This module works out what each Pokémon is worth in each league that is on the league list
right now, and puts a team of three together for each league.

What it is worth comes from two things:
  * how good the species (or what it evolves into) is in that league: the score of the PvPoke rankings of that
    league or cup (only species that may play in it are in those rankings), and
  * how good its IVs are for the CP cap of the league: the stat product at the highest level that stays under the
    cap, against the best stat product the species can reach (Great and Ultra League: low Attack IVs are often
    better; Master League: plain IV %).
Pokémon GO has no natures (they belong to the main series games): IVs, level and CP are what count.

The data comes from PvPoke (https://github.com/pvpoke/pvpoke, MIT License, Copyright (c) 2019 pvpoke): the
species with their evolutions, the leagues and cups (formats.json) and their rankings.  It is downloaded to
~/models/pvpoke/ and fetched again after a day.  Only the standard library and battle_engine (the CP formula)."""
import csv
import difflib
import io
import json
import math
import os
import re
import time
import unicodedata
import urllib.request

import battle_engine as BE

RAW = "https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/"
CACHE = os.path.join(os.path.expanduser("~"), "models", "pvpoke")
MAIN_PACKAGE = "com.nianticlabs.pokemongo"
COLLECTION_FILE = os.path.join(os.path.expanduser("~"), "collection.json")          # (the Play Store app)
TEAMS_FILE = os.path.join(os.path.expanduser("~"), "collection_teams.json")


def game_key(pkg=None):
    """A short name for the files of one Pokémon GO app: '' for the Play Store app, else a part of its package
    name ('com.nianticlabs.pokemongo.ares' -> 'ares'). Every app is another account: its own Pokémon, tags and
    teams."""
    pkg = (pkg or MAIN_PACKAGE).strip()
    if pkg == MAIN_PACKAGE:
        return ""
    tail = pkg[len(MAIN_PACKAGE):].strip(".") if pkg.startswith(MAIN_PACKAGE) else pkg
    return re.sub(r"[^a-z0-9]+", "_", tail.lower()).strip("_") or "other"


def collection_file(game=None):
    k = game_key(game)
    return COLLECTION_FILE if not k else COLLECTION_FILE.replace(".json", f"-{k}.json")


def teams_file(game=None):
    k = game_key(game)
    return TEAMS_FILE if not k else TEAMS_FILE.replace(".json", f"-{k}.json")
FRESH = 24 * 3600            # s: the downloaded PvPoke files are fetched again after this long
MAX_LEVEL = 50.0             # (51 for a best buddy: not counted)
TEAM_SIZE = 3
RESERVES = 3                 # per league: this many more get the league's tag (in case one is needed)


# ------------------------------------------------------------------ data ---
def fetch(path, max_age=FRESH, opener=None):
    """A PvPoke data file (path below src/data/), from the cache when it is fresh, else downloaded.
    Falls back to an old cached copy when the download fails. Returns the parsed JSON or None."""
    local = os.path.join(CACHE, path.replace("/", "_"))
    if os.path.exists(local) and time.time() - os.path.getmtime(local) < max_age:
        with open(local, encoding="utf-8") as f:
            return json.load(f)
    try:
        req = urllib.request.Request(RAW + path, headers={"User-Agent": "pokemon-go-automation"})
        with (opener or urllib.request.urlopen)(req, timeout=60) as r:
            raw = r.read()
        data = json.loads(raw.decode("utf-8"))
        os.makedirs(CACHE, exist_ok=True)
        with open(local + ".tmp", "wb") as f:
            f.write(raw)
        os.replace(local + ".tmp", local)
        return data
    except Exception:  # noqa: BLE001
        if os.path.exists(local):
            with open(local, encoding="utf-8") as f:
                return json.load(f)
        return None


_species = {}


def species_table(data=None):
    """{speciesId: {name, base (atk, def, hp), types, evolutions, tags}} of the released Pokémon."""
    if _species and data is None:
        return _species
    rows = data if data is not None else (fetch("gamemaster/pokemon.json") or [])
    out = {}
    for p in rows:
        if not p.get("released", True) or not p.get("baseStats"):
            continue
        b = p["baseStats"]
        out[p["speciesId"]] = {"name": p["speciesName"], "base": (b["atk"], b["def"], b["hp"]),
                               "types": [t for t in p.get("types", []) if t and t != "none"],
                               "evolutions": (p.get("family") or {}).get("evolutions") or [],
                               "tags": p.get("tags") or [], "dex": p.get("dex"),
                               "fast": p.get("fastMoves") or [], "charged": p.get("chargedMoves") or [],
                               "elite": (p.get("eliteMoves") or []) + (p.get("legacyMoves") or [])}
    if data is None:
        _species.update(out)
    return out


def _norm(text):
    t = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def find_species(name, table=None):
    """The speciesId of a name as the game shows it ('Galarian Stunfisk', 'Zamazenta', 'Mr. Mime'), or None.
    Shadow, Mega and the like are not in a name on the storage screen, so the plain form is preferred."""
    table = table or species_table()
    want = _norm(name)
    if not want:
        return None
    plain = {}
    for sid, row in table.items():
        if any(t in ("mega", "shadow") for t in row["tags"]) or sid.endswith(("_shadow", "_mega", "_mega_x", "_mega_y")):
            continue
        n = _norm(row["name"])
        plain.setdefault(n, sid)
        # 'Stunfisk (Galarian)' is called 'Galarian Stunfisk' in the game
        m = re.fullmatch(r"(.+?) \((.+)\)", row["name"])
        if m:
            plain.setdefault(_norm(f"{m.group(2)} {m.group(1)}"), sid)
    if want in plain:
        return plain[want]
    forms = sorted(n for n in plain if n.startswith(want + " "))   # 'Zamazenta' -> 'zamazenta hero' (the usual form)
    if forms:
        usual = [n for n in forms if any(w in n.split() for w in BE.FORM_DEFAULTS + ("hero",))]
        return plain[(usual or forms)[0]]
    best = difflib.get_close_matches(want, list(plain), n=1, cutoff=0.8)
    return plain[best[0]] if best else None


def family_forms(sid, table=None):
    """The species itself and everything it can evolve into (in order)."""
    table = table or species_table()
    out, todo = [], [sid]
    while todo:
        s = todo.pop(0)
        if s in out or s not in table:
            continue
        out.append(s)
        todo.extend(table[s]["evolutions"])
    return out


# ---------------------------------------------------------------- leagues ---
def parse_cap(text):
    """The CP cap of 'Max CP per Pokémon: 2.500' / '1,500' / 'No limit' (10000)."""
    t = str(text).lower()
    if "no limit" in t or "unlimited" in t:
        return 10000
    m = re.search(r"(\d)[.,\s]?(\d{3})", t)
    if m:
        return int(m.group(1) + m.group(2))
    m = re.search(r"\b(\d{3,4})\b", t)
    return int(m.group(1)) if m else None


def match_format(title, cap, formats=None):
    """(cup, cap) of PvPoke for a league as the game names it.  'Great/Ultra/Master League' are the open leagues
    ('all'); 'Master League: Mega Edition' is 'mega'; a cup is matched by its words ('2026 GO LAIC Cup: Great
    League Edition' -> laic...gbl).  Unknown: the open league of that cap."""
    words = set(_norm(title).split()) - {"league", "edition", "cup", "go", "the", "great", "ultra", "master", "gbl"}
    words = {w for w in words if not re.fullmatch(r"\d{4}", w)}          # (the year is often another one)
    if not words:
        return "all", cap
    formats = formats if formats is not None else (fetch("gamemaster/formats.json") or [])
    best, best_score = None, 0.0
    for f in formats:
        if int(f.get("cp", 0)) != int(cap) or f.get("cup") in ("custom",):
            continue
        fw = set(_norm(f.get("title", "")).split()) | set(_norm(f.get("cup", "")).split())
        score = len(words & fw) + 0.5 * sum(1 for w in words if any(w in x for x in fw))
        if "gbl" in fw or "gbl" in f.get("cup", ""):
            score += 0.25                                                 # (the version for the Battle League)
        if score > best_score:
            best, best_score = f["cup"], score
    return (best, cap) if best else ("all", cap)


def rankings(cup, cap):
    """{speciesId: {score, moveset}} of a league or cup (PvPoke 'overall')."""
    data = fetch(f"rankings/{cup}/overall/rankings-{cap}.json") or []
    return {r["speciesId"]: {"score": float(r.get("score", 0)), "moveset": r.get("moveset") or [],
                             "roles": (r.get("scores") or [0] * 6)[:3], "rank": i + 1}
            for i, r in enumerate(data)}


# ------------------------------------------------------------------ stats ---
def cpm(level):
    return BE.cpm(level)


def cp_of(base, ivs, level):
    return BE.calc_cp(base, ivs, level)


def levels():
    return [1 + i / 2 for i in range(int((MAX_LEVEL - 1) * 2) + 1)]


def level_from_cp(base, ivs, cp, exact=True):
    """The level at which this species with these IVs has this CP (the lowest one that fits). exact=False: the
    level with the nearest CP (a misread digit or IVs that are one off), else None."""
    best = None
    for lv in levels():
        c = cp_of(base, ivs, lv)
        if c == cp:
            return lv
        if not exact and (best is None or abs(c - cp) < best[0]):
            best = (abs(c - cp), lv)
    return best[1] if best else None


_LEVELS = None


def hp_of(base, ivs, level):
    """The maximum HP."""
    return max(10, int((base[2] + ivs[2]) * cpm(level)))


def closest_name(name, sids, table):
    """Of these species, the one whose name looks most like what was read ('Eeve' -> eevee), when it is clearly
    the closest (more than one species fits the CP, HP and IVs and the name was misread); else None."""
    near = sorted(((difflib.SequenceMatcher(None, name.lower(), table[sid]["name"].lower()).ratio(), sid)
                   for sid in sids), reverse=True)
    if near and near[0][0] >= 0.6 and (len(near) == 1 or near[0][0] - near[1][0] >= 0.15):
        return near[0][1]
    return None


def identify(cp, ivs, hp=None, types=None, name=None, table=None):
    """(speciesId, level, how) of a scanned Pokémon. The name decides when it fits the CP (and the HP); a
    nickname or a misread name is found by what fits: every species (of these types, when they were read) is
    tried for a level with exactly this CP and HP. how: 'name', 'stats' or 'name, HP does not fit'.
    (None, None, why) when nothing fits or more than one species does."""
    table = table or species_table()
    ivs = tuple(ivs)

    def fits(sid):
        base = table[sid]["base"]
        lv = level_from_cp(base, ivs, cp)
        if lv is None:
            return None
        if hp is not None and hp_of(base, ivs, lv) != hp:
            return None
        return lv
    by_name = find_species(name, table) if name else None
    if by_name:
        lv = fits(by_name)
        if lv is not None:
            return by_name, lv, "name"
    want = {t.lower() for t in (types or []) if t}
    hits = []
    for sid, row in table.items():
        if any(t in ("mega", "shadow") for t in row["tags"]) or sid.endswith(("_shadow", "_mega", "_mega_x", "_mega_y")):
            continue
        if want and set(row["types"]) != want:
            continue
        lv = fits(sid)
        if lv is not None:
            hits.append((sid, lv))
    # forms with the same stats (Pikachu caps ...) are one answer
    stats = {table[sid]["base"] for sid, _lv in hits}
    if hits and len(stats) == 1:
        return hits[0][0], hits[0][1], "stats"
    if by_name:
        lv = level_from_cp(table[by_name]["base"], ivs, cp, exact=False)
        return by_name, lv, "name, HP does not fit"
    if hits and name:
        sid = closest_name(name, [sid for sid, _lv in hits], table)
        if sid:
            return sid, dict(hits)[sid], "stats, name like"
    return None, None, ("no species fits" if not hits else f"{len(stats)} species fit")


# Power-up costs (per half level), as the game asks them. Levels 1-40: Stardust and Candy per two levels; 40-50:
# Stardust and Candy XL. Lucky: half the Stardust; Shadow: 1.2x Stardust and Candy; Purified: 0.9x.
DUST = [200, 400, 600, 800, 1000, 1300, 1600, 1900, 2200, 2500, 3000, 3500, 4000, 4500, 5000, 6000, 7000, 8000, 9000, 10000]
CANDY = [1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 3, 3, 3, 4, 4, 6, 8, 10, 12, 15]
DUST_XL = [10000, 11000, 11000, 12000, 12000, 13000, 13000, 14000, 14000, 15000]
CANDY_XL = [10, 10, 12, 12, 15, 15, 17, 17, 20, 20]


def power_cost(from_level, to_level, lucky=False, shadow=False, purified=False):
    """(stardust, candy, candy XL) to power up from one level to another (an estimate of the game's table)."""
    dust = candy = xl = 0
    lv = from_level
    while lv < to_level - 1e-6:
        if lv < 40:
            i = min(int((lv - 1) // 2), len(DUST) - 1)
            dust += DUST[i]
            candy += CANDY[i]
        else:
            i = min(int(lv - 40), len(DUST_XL) - 1)
            dust += DUST_XL[i]
            xl += CANDY_XL[i]
        lv += 0.5
    f = 1.2 if shadow else 0.9 if purified else 1.0
    dust = dust * f * (0.5 if lucky else 1.0)
    return int(round(dust)), int(math.ceil(candy * f)), int(math.ceil(xl * f))


def best_under(base, ivs, cap, min_level=1.0):
    """(level, cp, stat product) at the highest level <= MAX_LEVEL whose CP stays <= cap, or None when even
    min_level (its level now: powering down is not possible) is over the cap. CP grows with the level, so the
    level is found by halving."""
    global _LEVELS
    if _LEVELS is None:
        _LEVELS = levels()
    lo = next((i for i, lv in enumerate(_LEVELS) if lv >= min_level), None)
    if lo is None or cp_of(base, ivs, _LEVELS[lo]) > cap:
        return None
    hi = len(_LEVELS) - 1
    while lo < hi:                                   # the highest index whose CP is <= cap
        mid = (lo + hi + 1) // 2
        if cp_of(base, ivs, _LEVELS[mid]) <= cap:
            lo = mid
        else:
            hi = mid - 1
    lv = _LEVELS[lo]
    c = cpm(lv)
    sp = (base[0] + ivs[0]) * c * (base[1] + ivs[1]) * c * math.floor((base[2] + ivs[2]) * c)
    return lv, cp_of(base, ivs, lv), sp


_max_sp = {}


def max_stat_product(base, cap):
    """The best stat product any IVs reach under the cap (for the rank %)."""
    key = (tuple(base), cap)
    if key not in _max_sp:
        top = 0.0
        for a in range(16):
            for d in range(16):
                for s in range(16):
                    b = best_under(base, (a, d, s), cap)
                    if b and b[2] > top:
                        top = b[2]
        _max_sp[key] = top
    return _max_sp[key]


def iv_fit(base, ivs, cap):
    """0..1: how good these IVs are for the league. Master League (no cap): IV %; else stat product %."""
    if cap >= 10000:
        return sum(ivs) / 45.0
    b = best_under(base, ivs, cap)
    top = max_stat_product(base, cap)
    return (b[2] / top) if b and top else 0.0


# --------------------------------------------------------------- teams ---
def evaluate(mons, leagues, table=None, ranks=None):
    """For each scanned Pokémon and each league: the best form it can become that may play there.
    mons: [{id, name, species, cp, ivs, level?}]; leagues: [{title, cap, cup}];
    ranks: {league title: rankings()} (fetched when not given).
    Returns {mon id: {league title: {form, score, fit, value, level, cp, moveset, evolve}}}."""
    table = table or species_table()
    ranks = ranks if ranks is not None else {lg["title"]: rankings(lg["cup"], lg["cap"]) for lg in leagues}
    out = {}
    for m in mons:
        sid = m.get("species")
        if not sid or sid not in table or not m.get("ivs"):
            continue
        ivs = tuple(m["ivs"])
        now_level = m.get("level") or level_from_cp(table[sid]["base"], ivs, m.get("cp") or 10, exact=False) or 1.0
        per = {}
        for lg in leagues:
            rk = ranks.get(lg["title"]) or {}
            best = None
            for form in family_forms(sid, table):
                rid = form + "_shadow" if m.get("shadow") and form + "_shadow" in rk else form
                if rid not in rk:
                    continue
                base = table[form]["base"]
                where = best_under(base, ivs, lg["cap"], now_level)    # (evolving keeps the level)
                if where is None:
                    continue                                   # (already over the cap at its level now)
                fit = iv_fit(base, ivs, lg["cap"])
                value = rk[rid]["score"] * (0.8 + 0.2 * fit)
                dust, candy, xl = power_cost(now_level, where[0], m.get("lucky"), m.get("shadow"), m.get("purified"))
                notes = []
                if form != sid and m.get("candy") is not None:
                    pass                                       # (evolution candy is not counted)
                if m.get("candy") is not None and candy > m["candy"]:
                    value *= 0.6
                    notes.append(f"needs {candy} candy, has {m['candy']}")
                if m.get("xl") is not None and xl > m["xl"]:
                    value *= 0.6
                    notes.append(f"needs {xl} candy XL, has {m['xl']}")
                moves = moves_status(m, form, rk[rid]["moveset"], table)
                if moves == "elite TM":
                    value *= 0.85
                elif moves == "TM":
                    value *= 0.95
                if best is None or value > best["value"]:
                    best = {"form": form, "rid": rid, "form_name": table[form]["name"] + (" (Shadow)" if rid != form else ""),
                            "score": rk[rid]["score"], "rank": rk[rid].get("rank"), "roles": rk[rid].get("roles", [0, 0, 0]),
                            "fit": round(fit, 4), "value": round(value, 2), "level": where[0], "cp": where[1],
                            "moveset": rk[rid]["moveset"], "evolve": form != sid, "now_level": now_level,
                            "dust": dust, "candy": candy, "xl": xl, "moves": moves, "notes": notes}
            if best:
                per[lg["title"]] = best
        if per:
            out[m["id"]] = per
    return out


def moves_status(m, form, moveset, table=None):
    """What the Pokémon needs for the moves PvPoke recommends: 'ok' (it has them), 'TM', 'elite TM' (a legacy or
    elite move it does not have), or '?' (its moves were not read)."""
    table = table or species_table()
    have = m.get("moves")
    want = set(moveset or [])
    if not want:
        return "?"
    if not have:
        elite = set(table.get(form, {}).get("elite") or [])
        return "elite TM?" if want & elite else "?"
    got = {have.get("fast")} | set(have.get("charged") or [])
    missing = want - got
    if not missing:
        return "ok"
    elite = set(table.get(form, {}).get("elite") or [])
    return "elite TM" if missing & elite else "TM"


def _weak_to(types):
    """The attack types this type combination takes super effective damage from."""
    return {t for t in BE.load()["types"] if BE.type_mult(t, types) > 1.0}


SIM_CANDIDATES = 9        # per league: the best this many are tried in teams of three with the simulator ...
SIM_META = 30             # ... against the top this many of the league (1 shield each)


def _mon_for(sid, ivs, level, moveset, shadow=False):
    """A battle_engine.Mon, or None when the engine does not know the species or a move."""
    try:
        fast = moveset[0] if moveset else None
        charged = list(moveset[1:]) if len(moveset) > 1 else None
        return BE.Mon(sid, level=level, ivs=tuple(ivs), shadow=shadow, fast=fast, charged=charged)
    except Exception:  # noqa: BLE001
        return None


def meta_mons(ranks, cap, table=None, n=SIM_META):
    """The top n of a league as Mons (IVs 0/15/15 at the best level under the cap: a usual build)."""
    table = table or species_table()
    out = []
    for rid, r in sorted(ranks.items(), key=lambda t: t[1].get("rank", 999))[:n]:
        sid = rid[:-7] if rid.endswith("_shadow") else rid
        if sid not in table:
            continue
        b = best_under(table[sid]["base"], (0, 15, 15), cap)
        if b is None:
            continue
        m = _mon_for(sid, (0, 15, 15), b[0], r["moveset"], rid.endswith("_shadow"))
        if m:
            out.append(m)
    return out


def coverage(members, meta):
    """0..1: over the top of the league, how well the best of the members does (1v1, 1 shield each)."""
    if not members or not meta:
        return 0.0
    tot = 0.0
    for foe in meta:
        tot += max((BE.matchup(m, foe, 1, 1) + 1) / 2 for m in members)
    return tot / len(meta)


def team_roles(team):
    """Lead, switch and closer, from PvPoke's role scores (lead / closer / switch): the team in that order."""
    if len(team) < 3:
        for e, r in zip(team, ("Lead", "Switch", "Closer")):
            e["role"] = r
        return team
    left = list(team)
    lead = max(left, key=lambda e: e["eval"].get("roles", [0, 0, 0])[0])
    left.remove(lead)
    closer = max(left, key=lambda e: e["eval"].get("roles", [0, 0, 0])[1])
    left.remove(closer)
    lead["role"], left[0]["role"], closer["role"] = "Lead", "Switch", "Closer"
    return [lead, left[0], closer]


def build_teams(mons, evals, leagues, table=None, ranks=None):
    """A team of three per league, and the league each picked Pokémon is best in.  Each Pokémon goes to one
    league only: the one where it is worth most next to the others there.  In a team the second and third
    Pokémon must not share a weakness with both others (they cover each other).
    Returns {league title: {"team": [entries], "reserves": [entries]}}; an entry is the mon plus its evaluation."""
    table = table or species_table()
    by_id = {m["id"]: m for m in mons}
    used = set()
    teams = {lg["title"]: {"team": [], "reserves": [], "cup": lg["cup"], "cap": lg["cap"], "weak": []} for lg in leagues}
    cands = {lg["title"]: sorted(((e[lg["title"]]["value"], mid) for mid, e in evals.items() if lg["title"] in e),
                                 reverse=True) for lg in leagues}
    # the leagues take turns (the one with the fewest candidates first), one Pokémon each turn: no league takes
    # all the good ones before another has any
    order = sorted(leagues, key=lambda lg: len(cands[lg["title"]]))

    def pick(title, strict):
        tm = teams[title]
        for _v, mid in cands[title]:
            if mid in used:
                continue
            ev = evals[mid][title]
            if any(ev["form"] == t["eval"]["form"] for t in tm["team"]):
                continue                                       # (not the same species twice)
            w = _weak_to(table[ev["form"]]["types"])
            if strict and tm["team"] and sum(1 for s in tm["weak"] if w & s) >= len(tm["team"]):
                continue                                       # shares a weakness with every one already in
            tm["team"].append({"mon": by_id[mid], "eval": ev})
            tm["weak"].append(w)
            used.add(mid)
            return True
        return False

    for _round in range(TEAM_SIZE):
        for lg in order:
            if len(teams[lg["title"]]["team"]) <= _round:
                pick(lg["title"], True) or pick(lg["title"], False)
    for lg in order:                                           # then the reserves
        for _v, mid in cands[lg["title"]]:
            if len(teams[lg["title"]]["reserves"]) >= RESERVES:
                break
            if mid not in used:
                teams[lg["title"]]["reserves"].append({"mon": by_id[mid], "eval": evals[mid][lg["title"]]})
                used.add(mid)
    if ranks:                                          # the simulator: the trio that covers the top of the league best
        for lg in leagues:
            _simulated_team(teams[lg["title"]], lg, cands[lg["title"]], evals, by_id, ranks.get(lg["title"]) or {},
                            used, table)
    for tm in teams.values():
        tm.pop("weak")
        tm["team"] = team_roles(tm["team"])
    return teams


def _simulated_team(tm, lg, cands, evals, by_id, rk, used, table):
    """Swap the team for the trio of the league's best candidates (that are not in another team) that covers the
    top of the league best in the simulator; the score of PvPoke and the IV fit weigh in too."""
    import itertools
    mine = {e["mon"]["id"] for e in tm["team"] + tm["reserves"]}
    pool = [mid for _v, mid in cands if mid in mine or mid not in used][:SIM_CANDIDATES]
    if len(pool) < 3:
        return
    meta = meta_mons(rk, lg["cap"], table)
    mons = {}
    for mid in pool:
        ev = evals[mid][lg["title"]]
        m = by_id[mid]
        mons[mid] = _mon_for(ev["form"], m["ivs"], ev["level"], ev["moveset"], bool(m.get("shadow")))
    pool = [mid for mid in pool if mons[mid] is not None]
    if len(pool) < 3 or not meta:
        return
    best, best_score = None, -1.0
    for trio in itertools.combinations(pool, 3):
        forms = {evals[mid][lg["title"]]["form"] for mid in trio}
        if len(forms) < 3:
            continue
        cov = coverage([mons[mid] for mid in trio], meta)
        val = sum(evals[mid][lg["title"]]["value"] for mid in trio) / 300.0
        score = 0.7 * cov + 0.3 * val
        if score > best_score:
            best, best_score = trio, score
    if not best:
        return
    for e in tm["team"] + tm["reserves"]:
        used.discard(e["mon"]["id"])
    tm["team"] = [{"mon": by_id[mid], "eval": evals[mid][lg["title"]]} for mid in best]
    tm["coverage"] = round(coverage([mons[mid] for mid in best], meta), 3)
    used.update(best)
    tm["reserves"] = [{"mon": by_id[mid], "eval": evals[mid][lg["title"]]} for _v, mid in cands
                      if mid not in used][:RESERVES]
    used.update(e["mon"]["id"] for e in tm["reserves"])


WANTED_TOP = 25           # the top this many of a league: wanted when you have none with good IVs for it
WANTED_FIT = 0.9


def wanted_list(mons, evals, leagues, ranks):
    """Per league: strong species (top WANTED_TOP) you do not have, or only with IVs that fit the cap badly."""
    out = {}
    for lg in leagues:
        rk = ranks.get(lg["title"]) or {}
        have = {}
        for mid, e in evals.items():
            ev = e.get(lg["title"])
            if ev:
                have[ev["rid"] if "rid" in ev else ev["form"]] = max(have.get(ev.get("rid", ev["form"]), 0), ev["fit"])
        rows = []
        for rid, r in sorted(rk.items(), key=lambda t: t[1].get("rank", 999))[:WANTED_TOP]:
            fit = have.get(rid)
            if fit is None or fit < WANTED_FIT:
                rows.append({"species": rid, "rank": r.get("rank"), "score": r["score"],
                             "best_fit": round(fit, 3) if fit is not None else None})
        out[lg["title"]] = rows
    return out


PROTECT_FIT, PROTECT_SCORE = 0.95, 85


def protected_ids(mons, evals, teams):
    """Pokémon that never may go when the storage is cleaned up: team members and reserves, and every one whose
    IVs fit a league very well (PROTECT_FIT) for a species that is strong there (PROTECT_SCORE)."""
    out = set()
    for tm in teams.values():
        out.update(e["mon"]["id"] for e in tm.get("team", []) + tm.get("reserves", []))
    for mid, e in evals.items():
        if any(ev["fit"] >= PROTECT_FIT and ev["score"] >= PROTECT_SCORE for ev in e.values()):
            out.add(mid)
    return out


def battle_team_entries(teams, league):
    """The team of the league the bot fights in, as battle_engine wants it in ~/battle_team.json (in the order
    lead, switch, closer), or None when there is no team of three for that league."""
    words = set(_norm(league).split())
    title = next((t for t in teams if words and words <= set(_norm(t).split())), None)
    if title is None or len(teams[title].get("team", [])) < 3:
        return None
    out = []
    for e in teams[title]["team"]:
        ev, m = e["eval"], e["mon"]
        mv = ev.get("moveset") or []
        out.append({"species": ev["form"], "shadow": bool(m.get("shadow")), "level": ev["level"],
                    "ivs": list(m["ivs"]), "fast": mv[0] if mv else None, "charged": list(mv[1:]) or None})
    return out


# --------------------------------------------------------------- storage ---
def load_collection(path=None, game=None):
    try:
        with open(path or collection_file(game), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_collection(d, path=None, game=None):
    path = path or collection_file(game)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=0)
    os.replace(path + ".tmp", path)


def make_teams(collection=None, leagues=None, path=None, game=None, simulate=True):
    """Work out the teams of the leagues of now from the scanned Pokémon of one game and keep them (teams_file)."""
    c = collection if collection is not None else load_collection(game=game)
    leagues = leagues if leagues is not None else c.get("leagues") or []
    mons = c.get("mons") or []
    ranks = {lg["title"]: rankings(lg["cup"], lg["cap"]) for lg in leagues}
    evals = evaluate(mons, leagues, ranks=ranks)
    teams = build_teams(mons, evals, leagues, ranks=ranks if simulate else None)
    out = {"made": time.strftime("%Y-%m-%d %H:%M"), "game": c.get("game") or game or MAIN_PACKAGE,
           "leagues": leagues, "teams": teams,
           "best_league": {mid: max(e, key=lambda t: e[t]["value"]) for mid, e in evals.items()},
           "evals": evals, "wanted": wanted_list(mons, evals, leagues, ranks),
           "protected": sorted(protected_ids(mons, evals, teams))}
    path = path or teams_file(game or c.get("game"))
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    os.replace(path + ".tmp", path)
    return out


def load_teams(path=None, game=None):
    try:
        with open(path or teams_file(game), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


EXPORT_FIELDS = ["name", "species", "cp", "atk", "def", "hp", "iv_pct", "level", "shadow", "lucky", "purified",
                 "scanned", "best_league", "best_form", "league_cp", "league_level", "league_rank", "league_score",
                 "iv_fit_pct", "value", "in_team", "role", "moveset", "moves", "stardust", "candy", "candy_xl",
                 "protect"]


def export_rows(collection=None, teams=None, game=None):
    c = collection if collection is not None else load_collection(game=game)
    t = teams if teams is not None else load_teams(game=game)
    evals, best = t.get("evals") or {}, t.get("best_league") or {}
    in_team = {}
    for title, tm in (t.get("teams") or {}).items():
        for e in tm.get("team", []):
            in_team[e["mon"]["id"]] = title
        for e in tm.get("reserves", []):
            in_team.setdefault(e["mon"]["id"], title + " (reserve)")
    roles = {}
    for title, tm in (t.get("teams") or {}).items():
        for e in tm.get("team", []):
            roles[e["mon"]["id"]] = e.get("role", "")
    prot = set(t.get("protected") or [])
    rows = []
    for m in c.get("mons") or []:
        ivs = m.get("ivs") or [None] * 3
        lg = best.get(m["id"])
        ev = (evals.get(m["id"]) or {}).get(lg) if lg else None
        rows.append({"name": m.get("name"), "species": m.get("species"), "cp": m.get("cp"),
                     "atk": ivs[0], "def": ivs[1], "hp": ivs[2],
                     "iv_pct": round(sum(ivs) / 45 * 100, 1) if None not in ivs else None,
                     "level": m.get("level"), "scanned": m.get("scanned"), "best_league": lg or "",
                     "best_form": ev["form_name"] if ev else "", "league_cp": ev["cp"] if ev else "",
                     "league_level": ev["level"] if ev else "", "league_score": ev["score"] if ev else "",
                     "iv_fit_pct": round(ev["fit"] * 100, 1) if ev else "", "value": ev["value"] if ev else "",
                     "in_team": in_team.get(m["id"], ""), "moveset": " / ".join(ev["moveset"]) if ev else "",
                     "shadow": bool(m.get("shadow")), "lucky": bool(m.get("lucky")), "purified": bool(m.get("purified")),
                     "league_rank": ev.get("rank", "") if ev else "", "role": roles.get(m["id"], ""),
                     "moves": ev.get("moves", "") if ev else "", "stardust": ev.get("dust", "") if ev else "",
                     "candy": ev.get("candy", "") if ev else "", "candy_xl": ev.get("xl", "") if ev else "",
                     "protect": m["id"] in prot})
    return rows


def export_csv(collection=None, teams=None, game=None):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=EXPORT_FIELDS)
    w.writeheader()
    for r in export_rows(collection, teams, game):
        w.writerow(r)
    return buf.getvalue()


# ------------------------------------------------------------- the bars ---
def bar_value(fill, total):
    """An appraisal bar: 0..15 from the filled length against the whole bar (three parts of five)."""
    if not total:
        return None
    return max(0, min(15, int(round(15.0 * fill / total))))


def tag_name(title, limit=30):
    """The name of the tag of a league: the league's own name, shortened when the game would not take it."""
    t = " ".join(str(title).split())
    if len(t) <= limit:
        return t
    t = re.sub(r"\s*:\s*", " ", t).replace(" Edition", "")
    t = re.sub(r"^\d{4}\s+", "", t)
    return t[:limit].rstrip()
