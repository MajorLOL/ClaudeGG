#!/usr/bin/env python3
"""Compare the battle engine's 1-against-1 duels with a simulator that matches PvPoke.

gbl-lab (https://github.com/bobeic/gbl-lab) publishes the duel results of the
top 150 Great League Pokémon, simulated with PvPoke's own decision logic, as
data/matrix-1500.json.  This script downloads that file (it is not part of this
repository), plays the same duels with battle_engine.simulate() and reports how
often the same Pokémon wins.  It is a check for the developer, not part of the
bot.

    python3 tools/crosscheck_gbl_lab.py                 # download and compare
    python3 tools/crosscheck_gbl_lab.py --matrix m.json # use a local copy

The matrix uses the movesets, levels and IVs it lists, so the engine is given
exactly those.  Pokémon with a form change (Morpeko, Mimikyu, ...) are skipped:
the engine does not model them.  Last result: no shields 94% (97% of the clear
duels), 1 shield each 88% (93%), 2 shields each 85% (91%).
"""
import argparse
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import battle_engine as be  # noqa: E402

URL = "https://raw.githubusercontent.com/bobeic/gbl-lab/main/data/matrix-1500.json"
FORMS = ("morpeko", "mimikyu", "cramorant", "aegislash", "minior")


def mon_from(entry):
    sid = entry["speciesId"]
    shadow = sid.endswith("_shadow")
    iv = entry["ivs"]
    return be.Mon(sid[:-len("_shadow")] if shadow else sid, level=entry["level"],
                  ivs=(iv["atk"], iv["def"], iv["hp"]), shadow=shadow,
                  fast=entry["moveset"][0], charged=entry["moveset"][1:3])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", help="local copy of matrix-1500.json")
    a = ap.parse_args()
    if a.matrix:
        with open(a.matrix, encoding="utf-8") as f:
            matrix = json.load(f)
    else:
        req = urllib.request.Request(URL, headers={"User-Agent": "pokemon-go-automation"})
        with urllib.request.urlopen(req, timeout=60) as r:
            matrix = json.loads(r.read().decode("utf-8"))
    meta, ratings = matrix["meta"], matrix["ratings"]
    mons = {i: mon_from(e) for i, e in enumerate(meta)
            if not e["speciesId"].startswith(FORMS)}
    print("%d Pokémon (%d skipped for form changes)" % (
        len(mons), len(meta) - len(mons)))
    for shields in (0, 1, 2):
        n = agree = clear = clear_agree = 0
        for i in mons:
            for j in mons:
                if i >= j:
                    continue
                rating = ratings[i][j][shields][shields]
                ha, hb = be.simulate(mons[i], mons[j], shields, shields)
                if ha > 0 >= hb:
                    mine = 1
                elif hb > 0 >= ha:
                    mine = 0
                else:
                    continue
                if rating == 500:
                    continue
                same = mine == (1 if rating > 500 else 0)
                n += 1
                agree += same
                if abs(rating - 500) >= 100:
                    clear += 1
                    clear_agree += same
        print("shields %d-%d: same winner in %.1f%% of %d duels "
              "(%.1f%% of the %d clear ones)" % (
                  shields, shields, 100.0 * agree / n, n,
                  100.0 * clear_agree / clear, clear))


if __name__ == "__main__":
    sys.exit(main())
