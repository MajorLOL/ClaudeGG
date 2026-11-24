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
COLLECTION_FILE = os.path.join(os.path.expanduser("~"), "collection.json")
TEAMS_FILE = os.path.join(os.path.expanduser("~"), "collection_teams.json")
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
                               "tags": p.get("tags") or [], "dex": p.get("dex")}
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
    return {r["speciesId"]: {"score": float(r.get("score", 0)), "moveset": r.get("moveset") or []} for r in data}


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
                if form not in rk:
                    continue
                base = table[form]["base"]
                where = best_under(base, ivs, lg["cap"], now_level)    # (evolving keeps the level)
                if where is None:
                    continue                                   # (already over the cap at its level now)
                fit = iv_fit(base, ivs, lg["cap"])
                value = rk[form]["score"] * (0.8 + 0.2 * fit)
                if best is None or value > best["value"]:
                    best = {"form": form, "form_name": table[form]["name"], "score": rk[form]["score"],
                            "fit": round(fit, 4), "value": round(value, 2), "level": where[0], "cp": where[1],
                            "moveset": rk[form]["moveset"], "evolve": form != sid}
            if best:
                per[lg["title"]] = best
        if per:
            out[m["id"]] = per
    return out


def _weak_to(types):
    """The attack types this type combination takes super effective damage from."""
    return {t for t in BE.load()["types"] if BE.type_mult(t, types) > 1.0}


def build_teams(mons, evals, leagues, table=None):
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
    for tm in teams.values():
        tm.pop("weak")
    return teams


# --------------------------------------------------------------- storage ---
def load_collection(path=None):
    try:
        with open(path or COLLECTION_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_collection(d, path=None):
    path = path or COLLECTION_FILE
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=0)
    os.replace(path + ".tmp", path)


def make_teams(collection=None, leagues=None, path=None):
    """Work out the teams of the leagues of now from the scanned Pokémon and keep them in TEAMS_FILE."""
    c = collection if collection is not None else load_collection()
    leagues = leagues if leagues is not None else c.get("leagues") or []
    mons = c.get("mons") or []
    evals = evaluate(mons, leagues)
    teams = build_teams(mons, evals, leagues)
    out = {"made": time.strftime("%Y-%m-%d %H:%M"), "leagues": leagues, "teams": teams,
           "best_league": {mid: max(e, key=lambda t: e[t]["value"]) for mid, e in evals.items()},
           "evals": evals}
    with open((path or TEAMS_FILE) + ".tmp", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    os.replace((path or TEAMS_FILE) + ".tmp", path or TEAMS_FILE)
    return out


def load_teams(path=None):
    try:
        with open(path or TEAMS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


EXPORT_FIELDS = ["name", "species", "cp", "atk", "def", "hp", "iv_pct", "level", "scanned", "best_league",
                 "best_form", "league_cp", "league_level", "league_score", "iv_fit_pct", "value", "in_team", "moveset"]


def export_rows(collection=None, teams=None):
    c = collection if collection is not None else load_collection()
    t = teams if teams is not None else load_teams()
    evals, best = t.get("evals") or {}, t.get("best_league") or {}
    in_team = {}
    for title, tm in (t.get("teams") or {}).items():
        for e in tm.get("team", []):
            in_team[e["mon"]["id"]] = title
        for e in tm.get("reserves", []):
            in_team.setdefault(e["mon"]["id"], title + " (reserve)")
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
                     "in_team": in_team.get(m["id"], ""), "moveset": " / ".join(ev["moveset"]) if ev else ""})
    return rows


def export_csv(collection=None, teams=None):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=EXPORT_FIELDS)
    w.writeheader()
    for r in export_rows(collection, teams):
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
