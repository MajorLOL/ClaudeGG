#!/usr/bin/env python3
"""Build models/battle_data.json from the open PvPoke game data.

PvPoke (https://github.com/pvpoke/pvpoke) is MIT licensed, Copyright (c) 2019
pvpoke.  This script downloads three files from its repository and boils them
down to the few facts the battle engine needs: species base stats, moves,
the CP multiplier table and the type chart.

    python3 tools/build_battle_data.py                 # download and build
    python3 tools/build_battle_data.py --src /tmp/pvp  # use local copies

With --src the folder must hold moves.json, pokemon.json, Pokemon.js and
DamageCalculator.js (the same files the download fetches).
"""
import argparse
import json
import os
import re
import sys
import urllib.request

RAW = "https://raw.githubusercontent.com/pvpoke/pvpoke/master/"
FILES = {
    "moves.json": "src/data/gamemaster/moves.json",
    "pokemon.json": "src/data/gamemaster/pokemon.json",
    "Pokemon.js": "src/js/pokemon/Pokemon.js",
    "DamageCalculator.js": "src/js/battle/DamageCalculator.js",
}

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "models", "battle_data.json")


def fetch(name, src):
    if src:
        with open(os.path.join(src, name), encoding="utf-8") as f:
            return f.read()
    req = urllib.request.Request(RAW + FILES[name],
                                 headers={"User-Agent": "pokemon-go-automation"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")


def parse_cpm(js):
    m = re.search(r"var cpms = \[(.*?)\];", js, re.S)
    if not m:
        raise SystemExit("CP multiplier table not found in Pokemon.js")
    vals = [float(x) for x in m.group(1).split(",") if x.strip()]
    if len(vals) < 101:
        raise SystemExit("unexpected CP multiplier count: %d" % len(vals))
    return [round(v, 9) for v in vals]


def parse_types(js):
    body = js[js.index("static getTypeTraits"):]
    cases = re.findall(
        r'case "(\w+)":\s*traits = \{\s*resistances: \[(.*?)\],\s*'
        r'weaknesses: \[(.*?)\],\s*immunities: \[(.*?)\]', body, re.S)
    out = {}
    for t, res, weak, imm in cases:
        def lst(x):
            return [a.strip().strip('"') for a in x.split(",") if a.strip()]
        out[t] = [lst(res), lst(weak), lst(imm)]
    if len(out) != 18:
        raise SystemExit("expected 18 types, found %d" % len(out))
    return out


def build(src):
    moves = {m["moveId"]: m for m in json.loads(fetch("moves.json", src))}
    species = json.loads(fetch("pokemon.json", src))

    mons = {}
    for p in species:
        tags = p.get("tags") or []
        sid = p["speciesId"]
        if not p.get("released"):
            continue
        if "mega" in tags or sid.endswith("_shadow") or "_mega" in sid \
                or "_primal" in sid:
            continue
        fast = [m for m in p["fastMoves"] if m in moves]
        charged = [m for m in p["chargedMoves"] if m in moves]
        if not fast or not charged:
            continue
        b = p["baseStats"]
        ivs = (p.get("defaultIVs") or {}).get("cp1500") or [40, 0, 15, 15]
        mons[sid] = [p["speciesName"], [t for t in p["types"] if t != "none"],
                     b["atk"], b["def"], b["hp"], fast, charged,
                     [float(ivs[0])] + [int(v) for v in ivs[1:4]],
                     1 if "shadoweligible" in tags else 0]

    # Keep every move, not just the ones on the species lists: a team may use
    # moves PvPoke does not list for a species (Frustration, Return, ...).
    out_moves = {}
    for mid in sorted(moves):
        m = moves[mid]
        out_moves[mid] = [m["name"], m["type"], m["power"], m["energy"],
                          m["energyGain"], m.get("turns", 1)]

    return {
        "source": "PvPoke (https://github.com/pvpoke/pvpoke), MIT License, "
                  "Copyright (c) 2019 pvpoke",
        "cpm": parse_cpm(fetch("Pokemon.js", src)),
        "types": parse_types(fetch("DamageCalculator.js", src)),
        "moves": out_moves,
        "mons": mons,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="folder with local copies of the source files")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    data = build(a.src)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
    print("wrote %s: %d species, %d moves, %.0f KB" % (
        a.out, len(data["mons"]), len(data["moves"]),
        os.path.getsize(a.out) / 1024.0))


if __name__ == "__main__":
    sys.exit(main())
