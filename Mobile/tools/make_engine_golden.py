#!/usr/bin/env python3
"""Makes tests/fixtures/engine_golden.json: what battle_engine.py answers for a lot of questions, as the file that
the C++ port of it (SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoBattle.cpp) is tested against.

    python3 tools/make_engine_golden.py            writes the file
    python3 tools/make_engine_golden.py --check    says whether the file is what battle_engine.py answers now

The questions are made from models/battle_data.json with a fixed seed: the type chart, the names of moves and of
species (as they are and as OCR misreads them), the movesets, the fit of CP and HP to level and IVs, the damage,
the charged attack to throw, the shield to use (the rule of a duel and the rule of a real battle), whole duels
the choice of who comes in after a faint, and the team file (load_team: what the engine makes of a file, as a list of Pokémon or as an error,
for a hundred files that are cut off, no team, not JSON, not UTF-8, or written the way a person might)."""
import base64
import json
import os
import random
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import battle_engine as be  # noqa: E402

OUT = os.path.join(ROOT, "tests", "fixtures", "engine_golden.json")
SEED = 20261127

CONFUSED = {"o": "0", "0": "o", "i": "l", "l": "i", "e": "c", "s": "5", "5": "s", "b": "6", "a": "o", "u": "v", "n": "m"}


def mutate(text, rnd):
    """What OCR does to a name: a letter misread, one gone, one doubled, a space inside, a stray word."""
    if len(text) < 2:
        return text
    kind = rnd.randrange(7)
    i = rnd.randrange(len(text))
    if kind == 0:
        return text[:i] + text[i + 1:]
    if kind == 1:
        return text[:i] + text[i] + text[i:]
    if kind == 2:
        c = text[i].lower()
        return text[:i] + CONFUSED.get(c, "x") + text[i + 1:]
    if kind == 3:
        return text[:i] + " " + text[i:]
    if kind == 4:
        return text.upper()
    if kind == 5:
        return rnd.choice(["Cep", "CP", "Lv", "x2", "1493"]) + " " + text
    return text + rnd.choice([" ", "  ", ".", " 2", "!"])


def mon_out(m):
    return {"species": m.species, "name": m.name, "label": m.label, "types": list(m.types), "shadow": m.shadow,
            "cp": m.cp, "level": m.level, "ivs": list(m.ivs)[:3], "atk": m.atk, "dfn": m.dfn, "max_hp": m.max_hp,
            "hp": m.hp, "fast": m.fast.id, "charged": [c.id for c in m.charged], "pos": m.pos}


def mon_from(spec):
    m = be.Mon(spec["species"], level=spec.get("level"), ivs=spec.get("ivs"), shadow=spec.get("shadow"),
               fast=spec.get("fast"), charged=spec.get("charged"), stats=spec.get("stats"), pos=spec.get("pos", 0))
    if "hp" in spec:
        m.hp = spec["hp"]
    if "energy" in spec:
        m.energy = spec["energy"]
    return m


def build():
    rnd = random.Random(SEED)
    data = be.load()
    species_all = list(data["mons"])
    species_ranked = [s for s in data["sets"]["1500"] if s in data["mons"]]
    moves_all = list(data["moves"])
    cases = []

    def add(fn, inp, out):
        cases.append({"fn": fn, "in": inp, "out": out})

    def pick_species():
        return rnd.choice(species_ranked if rnd.random() < 0.8 else species_all)

    def random_spec(shadow_chance=0.15):
        spec = {"species": pick_species()}
        if rnd.random() < shadow_chance:
            spec["shadow"] = True
        r = rnd.random()
        if r < 0.15:
            spec["level"] = rnd.choice([15.0, 20.5, 25.0, 30.5, 40.0, 50.0])
            spec["ivs"] = [rnd.randrange(16), rnd.randrange(16), rnd.randrange(16)]
        return spec

    def with_hp(spec):
        """The same Pokémon hurt: a fraction of its HP is left."""
        m = mon_from(spec)
        spec = dict(spec)
        spec["hp"] = max(1, int(m.max_hp * rnd.choice([1, 1, 0.9, 0.7, 0.5, 0.35, 0.2, 0.1, 0.05])))
        return spec

    # ---- the type chart
    type_lists = []
    for s in species_all:
        t = data["mons"][s][1]
        if t not in type_lists:
            type_lists.append(t)
    for move_type in data["types"]:
        for t in rnd.sample(type_lists, 70):
            add("type_mult", {"type": move_type, "against": t}, be.type_mult(move_type, t))

    # ---- names
    names_m = [data["moves"][m][0] for m in moves_all]
    texts = []
    for n in names_m:
        texts += [n, n.lower(), mutate(n, rnd), mutate(mutate(n, rnd), rnd)]
    texts += ["", "   ", "x", "ZZZZ", "Wing Attak", "Surf!", "Shadow Ball ", "Sky Atack", "Frustration", "Return"]
    for t in texts:
        add("find_move", {"text": t}, be.find_move(t))
    for t in ["Wing At", "Wing Attack", "Surf", "Hydro Cannon"]:
        add("find_move", {"text": t, "cutoff": 0.6}, be.find_move(t, 0.6))
    names_s = [data["mons"][s][0] for s in species_all]
    texts = []
    for n in rnd.sample(names_s, 700):
        texts += [n, mutate(n, rnd), mutate(mutate(n, rnd), rnd), "Shadow " + n, n + " (Shadow)"]
    texts += ["", "  ", "x", "Gourgeist", "Pumpkaboo", "Galarian Corsola", "Corsola (Galarian)", "Corsola Galarian",
              "Cep Tropius", "Tropius Cep 1493", "Alolan Raichu", "Raichu Alolan", "Lanturn", "LANTURN", "Lantern",
              "Noctowl", "Lapras", "Shadow Lapras", "Lapras (Shadow)", "Medicham", "Mr Mime", "Mr. Mime", "Farfetch'd",
              "Farfetchd", "Nidoran", "Flabebe", "Flabébé", "Pokémon", "Zacian", "Giratina", "Deoxys", "Wormadam",
              "Lycanroc", "Oricorio", "Toxtricity", "Urshifu", "Basculin", "Indeedee"]
    for t in texts:
        add("find_species", {"text": t}, be.find_species(t))
    for t in ["Lantrun", "Notowl", "Medicam", "Gourgist"]:
        add("find_species", {"text": t, "cutoff": 0.7}, be.find_species(t, 0.7))

    # ---- movesets
    for s in species_all:
        fast, charged = be.default_moveset(s)
        add("default_moveset", {"species": s}, [fast, list(charged)])
    for s in rnd.sample(species_all, 100):
        add("guessed_moveset", {"species": s}, [be.guessed_moveset(s)[0], list(be.guessed_moveset(s)[1])])
        add("fast_rate", {"species": s}, list(be.fast_rate(s)))
        add("cheapest_charged", {"species": s}, be.cheapest_charged(s))

    # ---- cpm and CP
    for level in [1.0, 1.5, 10.0, 20.5, 25.0, 30.0, 40.0, 50.0]:
        add("cpm", {"level": level}, be.cpm(level))
    for s in rnd.sample(species_all, 40):
        row = data["mons"][s]
        base = [row[2], row[3], row[4]]
        for _ in range(3):
            ivs = [rnd.randrange(16), rnd.randrange(16), rnd.randrange(16)]
            level = rnd.choice([1.0, 7.5, 15.0, 20.0, 25.0, 40.0, 50.0])
            add("calc_cp", {"base": base, "ivs": ivs, "level": level}, be.calc_cp(base, ivs, level))

    # ---- the fit of CP and HP
    for _ in range(40):
        s = pick_species()
        row = data["mons"][s]
        level = rnd.choice([10.0, 15.5, 20.0, 22.5, 25.0, 30.0, 35.5, 40.0, 50.0])
        ivs = [rnd.randrange(16), rnd.randrange(16), rnd.randrange(16)]
        m = be.Mon(s, level=level, ivs=ivs)
        out = be.fit_stats(s, m.cp, int(m.max_hp))
        add("fit_stats", {"species": s, "cp": m.cp, "hp": int(m.max_hp)},
            None if out is None else [out[0], list(out[1]), list(out[2])])
    for s, cp, hp in [("lanturn", 1494, 186), ("noctowl", 1497, 162), ("lapras", 1489, 174), ("lanturn", 99999, 1),
                      ("medicham", 1500, 100)]:
        out = be.fit_stats(s, cp, hp)
        add("fit_stats", {"species": s, "cp": cp, "hp": hp},
            None if out is None else [out[0], list(out[1]), list(out[2])])

    # ---- one Pokémon
    for _ in range(150):
        spec = random_spec(0.3)
        if rnd.random() < 0.2:
            moves = be.default_moveset(spec["species"])
            spec["fast"] = moves[0]
            spec["charged"] = list(moves[1])[:1]
        if rnd.random() < 0.2:
            spec["stats"] = [rnd.uniform(80, 220), rnd.uniform(80, 220), float(rnd.randrange(80, 200))]
        add("mon", {"spec": spec}, mon_out(mon_from(spec)))

    # ---- damage
    for _ in range(800):
        a, d = random_spec(), random_spec()
        ma, md = mon_from(a), mon_from(d)
        moves = [ma.fast] + ma.charged
        mv = rnd.choice(moves)
        add("damage", {"attacker": a, "defender": d, "move": mv.id}, be.damage(mv, ma, md))

    # ---- the charged attack to throw
    for _ in range(1500):
        me, foe = random_spec(), with_hp(random_spec())
        inp = {"me": me, "foe": foe, "energy": rnd.choice([0, 10, 20, 30, 35, 40, 45, 50, 55, 60, 65, 70, 80, 100]),
               "foe_shields": rnd.choice([0, 1, 2])}
        mf = mon_from(foe)
        if rnd.random() < 0.3:
            inp["foe_hp"] = max(1, int(mf.max_hp * rnd.random()))
        mv, why = be.pick_charged(mon_from(me), mf, inp["energy"], inp["foe_shields"], inp.get("foe_hp"))
        add("pick_charged", inp, [mv.id if mv else None, why])

    # ---- the shield in a duel and in a battle
    def shield_input():
        foe, me = random_spec(), with_hp(random_spec())
        mf, mm = mon_from(foe), mon_from(me)
        inp = {"foe": foe, "me": me, "shields": rnd.choice([0, 1, 1, 2, 2])}
        if rnd.random() < 0.5:
            inp["foe_move"] = rnd.choice(mf.charged).id
        if rnd.random() < 0.3:
            inp["my_hp"] = max(1, int(mm.max_hp * rnd.random()))
        if rnd.random() < 0.4:
            inp["foe_energy"] = rnd.choice([0, 10, 25, 35, 40, 50, 60, 75, 100])
        return inp, mf, mm

    def resolve_move(mf, inp):
        return next(c for c in mf.charged if c.id == inp["foe_move"]) if "foe_move" in inp else None

    for _ in range(1200):
        inp, mf, mm = shield_input()
        use, why = be.should_shield(mf, mm, inp["shields"], resolve_move(mf, inp), inp.get("my_hp"),
                                    inp.get("foe_energy"))
        add("should_shield", inp, [use, why])
    for _ in range(1500):
        inp, mf, mm = shield_input()
        if rnd.random() < 0.05:
            inp["foe"] = None
            mf = None
        inp["mine_left"] = rnd.choice([None, 1, 2, 3])
        inp["foes_left"] = rnd.choice([None, 1, 2, 3])
        inp["ready"] = rnd.random() < 0.3
        move = None
        if mf is not None and "foe_move" in inp:
            move = resolve_move(mf, inp)
        use, why = be.use_shield(mf, mm, inp["shields"], inp.get("my_hp"), inp["mine_left"], inp["foes_left"],
                                 inp["ready"], move, inp.get("foe_energy"))
        add("use_shield", inp, [use, why])

    # ---- what the foe can throw
    for _ in range(300):
        foe, me = random_spec(), random_spec()
        mf, mm = mon_from(foe), mon_from(me)
        energy = rnd.choice([None, 0, 25, 40, 55, 70, 100])
        dmg, mv = be.foe_hit(mf, mm, None, energy)
        add("foe_hit", {"foe": foe, "me": me, "energy": energy}, [dmg, mv.id])
        add("can_throw", {"foe": foe, "energy": energy}, [m.id for m in be.can_throw(mf, energy)])
        mv = rnd.choice(mf.charged)
        shields = rnd.choice([0, 1, 2])
        foe_energy = rnd.choice([None, 0, 50, 100])
        add("cycle_damage", {"foe": foe, "me": me, "move": mv.id, "shields": shields, "foe_energy": foe_energy},
            be.cycle_damage(mf, mm, mv, shields, foe_energy))

    # ---- duels and who comes in
    for _ in range(350):
        a, b = random_spec(), random_spec()
        sa, sb = rnd.choice([0, 1, 2]), rnd.choice([0, 1, 2])
        ma, mb = mon_from(a), mon_from(b)
        add("simulate", {"a": a, "b": b, "shields_a": sa, "shields_b": sb}, list(be.simulate(ma, mb, sa, sb)))
        add("matchup", {"a": a, "b": b, "shields_a": sa, "shields_b": sb}, be.matchup(ma, mb, sa, sb))
    for _ in range(120):
        team = []
        for pos in range(3):
            spec = with_hp(random_spec())
            spec["pos"] = pos
            if rnd.random() < 0.2:
                spec["hp"] = 0
            team.append(spec)
        foe = random_spec()
        out = be.best_switch([mon_from(s) for s in team], mon_from(foe))
        add("best_switch", {"team": team, "foe": foe},
            [None if out[0] is None else out[0].pos, out[1]])

    # ---- the team
    entries = [dict(e) for e in be.DEFAULT_TEAM]
    add("build_team", {"entries": entries}, [mon_out(m) for m in be.build_team(entries)])
    for _ in range(25):
        entries = []
        for _p in range(3):
            s = pick_species()
            e = {"species": s}
            moves = be.default_moveset(s)
            r = rnd.random()
            if r < 0.5:
                m = be.Mon(s, level=rnd.choice([20.0, 25.0, 30.0, 40.0]),
                           ivs=[rnd.randrange(16), rnd.randrange(16), rnd.randrange(16)])
                e["cp"], e["hp"] = m.cp, int(m.max_hp)
            elif r < 0.8:
                e["level"] = rnd.choice([20.0, 25.0, 40.0])
                e["ivs"] = [rnd.randrange(16), rnd.randrange(16), rnd.randrange(16)]
            if rnd.random() < 0.3:
                e["shadow"] = True
            if rnd.random() < 0.5:
                e["fast"] = moves[0]
                e["charged"] = list(moves[1])
            entries.append(e)
        add("build_team", {"entries": entries}, [mon_out(m) for m in be.build_team(entries)])

    # ---- the team file (load_team): what the engine makes of a file, or that it raises
    def team_file_case(label, content):
        """content: the bytes of the file, None (no file) or "dir" (a folder where the file should be)."""
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "battle_team.json")
            kind = "none"
            if content == "dir":
                os.mkdir(path)
                kind = "dir"
            elif content is not None:
                with open(path, "wb") as f:
                    f.write(content)
                kind = "file"
            try:
                out = [mon_out(m) for m in be.load_team(path)]
            except Exception:  # noqa: BLE001  (the bot catches every kind of them)
                out = {"error": True}
        inp = {"label": label, "kind": kind}
        if kind == "file":
            inp["b64"] = base64.b64encode(content).decode("ascii")
        add("load_team", inp, out)

    def text(value):
        return json.dumps(value).encode()

    noctowl = {"species": "noctowl", "cp": 1497, "hp": 162, "fast": "WING_ATTACK", "charged": ["SHADOW_BALL", "SKY_ATTACK"]}
    lapras = {"species": "lapras", "shadow": True, "cp": 1489, "hp": 174, "fast": "ICE_SHARD", "charged": ["FRUSTRATION", "SURF"]}
    lanturn = {"species": "lanturn", "cp": 1494, "hp": 186}
    team_file_case("no file", None)
    team_file_case("a folder in its place", "dir")
    team_file_case("an empty file", b"")
    team_file_case("not JSON", b"{not json")
    team_file_case("a file that is cut off", b'[{"species": "noctowl", "cp": 14')
    team_file_case("a byte order mark", b"\xef\xbb\xbf" + text([noctowl]))
    team_file_case("not UTF-8", b'[{"species": "noct\xffowl"}]')
    team_file_case("more than one value", text([noctowl]) + b" " + text([lapras]))
    team_file_case("a comma too many", b"[" + text(noctowl) + b",]")
    team_file_case("two lists with a comma", b"[],[]")
    team_file_case("two Pokemon with a comma and no list", text(noctowl) + b"," + text(lapras))
    team_file_case("text after the list", text([noctowl]) + b" x")
    team_file_case("the preset written out", text(be.DEFAULT_TEAM))
    team_file_case("three Pokemon with CP and HP", text([noctowl, lapras, lanturn]))
    team_file_case("white space around it", b"\n  \t" + text([lanturn]) + b"  \n\n")
    team_file_case("a letter written as an escape", b'[{"species": "\\u006eoctowl"}]')
    team_file_case("a key twice", b'[{"species": "lapras", "species": "noctowl"}]')
    team_file_case("an empty list", b"[]")
    team_file_case("an empty table", b"{}")
    team_file_case("a table with a key", b'{"species": "noctowl"}')
    team_file_case("an empty text", b'""')
    team_file_case("a text", b'"noctowl"')
    team_file_case("a number", b"5")
    team_file_case("null", b"null")
    team_file_case("true", b"true")
    team_file_case("an entry that is a number", b"[1]")
    team_file_case("an entry that is null", b"[null]")
    team_file_case("an entry that is a list", b'[["noctowl"]]')
    team_file_case("an entry that is a text", b'["noctowl"]')
    team_file_case("an entry without a species", text([{"cp": 1497, "hp": 162}]))
    team_file_case("an entry with a species that is a number", text([{"species": 5}]))
    team_file_case("an entry with a species that is not in the data", text([{"species": "missingno"}]))
    team_file_case("one of three that is not in the data", text([noctowl, {"species": "missingno"}, lapras]))
    team_file_case("a fast move that is not in the data", text([{"species": "noctowl", "fast": "NO_SUCH_MOVE"}]))
    team_file_case("a charged move that is not in the data", text([{"species": "noctowl", "charged": ["SKY_ATTACK", "NO_SUCH_MOVE"]}]))
    # the numbers
    team_file_case("CP and HP as text", text([{"species": "noctowl", "cp": "1497", "hp": " 162 "}]))
    team_file_case("CP and HP with signs", text([{"species": "noctowl", "cp": "+1497", "hp": "162"}]))
    team_file_case("CP and HP with a point", text([{"species": "noctowl", "cp": 1497.0, "hp": 162.9}]))
    team_file_case("CP as a text with a point", text([{"species": "noctowl", "cp": "1497.5", "hp": 162}]))
    team_file_case("CP as a text with nothing", text([{"species": "noctowl", "cp": "many", "hp": 162}]))
    team_file_case("CP as a text with an exponent", text([{"species": "noctowl", "cp": "1e3", "hp": 162}]))
    team_file_case("CP as a list", text([{"species": "noctowl", "cp": [1497], "hp": 162}]))
    team_file_case("CP as a table", text([{"species": "noctowl", "cp": {"a": 1}, "hp": 162}]))
    team_file_case("CP as true", text([{"species": "noctowl", "cp": True, "hp": 162, "level": 25, "ivs": [1, 2, 3]}]))
    team_file_case("a bad CP next to an HP that is nothing", text([{"species": "noctowl", "cp": [1], "hp": 0}]))
    team_file_case("a CP that is nothing next to a bad HP", text([{"species": "noctowl", "cp": 0, "hp": [162]}]))
    team_file_case("CP 0 and a level", text([{"species": "noctowl", "cp": 0, "hp": 162, "level": 25, "ivs": [1, 2, 3]}]))
    team_file_case("CP as 0 in a text and a level", text([{"species": "noctowl", "cp": "0", "hp": "0", "level": 25}]))
    team_file_case("CP and HP that fit nothing, and a level", text([{"species": "noctowl", "cp": 99999, "hp": 1, "level": 20.5, "ivs": [4, 5, 6]}]))
    team_file_case("CP and HP that are far too big", text([{"species": "noctowl", "cp": 1e30, "hp": 1e30, "level": 20, "ivs": [4, 5, 6]}]))
    team_file_case("CP and HP that fit nothing and no level", text([{"species": "noctowl", "cp": 99999, "hp": 1}]))
    team_file_case("CP and HP that fit, and a level that is a text", text([{"species": "noctowl", "cp": 1497, "hp": 162, "level": "twenty"}]))
    team_file_case("only a CP", text([{"species": "noctowl", "cp": 1497}]))
    team_file_case("only an HP and a level", text([{"species": "noctowl", "hp": 162, "level": 30}]))
    team_file_case("a level and IVs", text([{"species": "noctowl", "level": 25.5, "ivs": [1, 2, 3]}]))
    team_file_case("a level without IVs", text([{"species": "noctowl", "level": 25.5}]))
    team_file_case("a level and IVs that are null", text([{"species": "noctowl", "level": 25, "ivs": None}]))
    team_file_case("a level and four IVs", text([{"species": "noctowl", "level": 25, "ivs": [1, 2, 3, 4]}]))
    team_file_case("a level and two IVs", text([{"species": "noctowl", "level": 25, "ivs": [1, 2]}]))
    team_file_case("a level and no IVs at all", text([{"species": "noctowl", "level": 25, "ivs": []}]))
    team_file_case("a level and IVs that are a text", text([{"species": "noctowl", "level": 25, "ivs": "123"}]))
    team_file_case("a level and an IV that is a text", text([{"species": "noctowl", "level": 25, "ivs": [1, "2", 3]}]))
    team_file_case("a level that is a text", text([{"species": "noctowl", "level": "25"}]))
    team_file_case("a level that is 0", text([{"species": "noctowl", "level": 0, "ivs": [1, 2, 3]}]))
    team_file_case("IVs and no level", text([{"species": "noctowl", "ivs": [1, 2, 3]}]))
    # shadow: what Python takes for true
    for label, value in (("true", True), ("false", False), ("1", 1), ("0", 0), ("0.0", 0.0), ("a text", "yes"), ("an empty text", ""),
                         ("minus one", -1), ("a small number", 0.25), ("a list", [0]), ("an empty list", []), ("a table", {"a": 0}), ("an empty table", {}), ("null", None)):
        team_file_case("shadow is " + label, text([{"species": "lapras", "shadow": value, "cp": 1489, "hp": 174}]))
    # the moves
    team_file_case("a fast move only", text([{"species": "noctowl", "fast": "WING_ATTACK"}]))
    team_file_case("charged moves only", text([{"species": "noctowl", "charged": ["SKY_ATTACK"]}]))
    team_file_case("one charged move", text([{"species": "noctowl", "fast": "WING_ATTACK", "charged": ["SKY_ATTACK"]}]))
    team_file_case("three charged moves", text([{"species": "noctowl", "fast": "WING_ATTACK", "charged": ["SKY_ATTACK", "SHADOW_BALL", "PSYCHIC"]}]))
    team_file_case("a fast move that is null and charged moves", text([{"species": "noctowl", "fast": None, "charged": ["SKY_ATTACK"]}]))
    team_file_case("a fast move that is empty and charged moves", text([{"species": "noctowl", "fast": "", "charged": ["SKY_ATTACK"]}]))
    team_file_case("a fast move that is empty and no charged moves", text([{"species": "noctowl", "fast": "", "charged": []}]))
    team_file_case("a fast move that is empty and nothing else", text([{"species": "noctowl", "fast": ""}]))
    team_file_case("a fast move that is 0 and no charged moves", text([{"species": "noctowl", "fast": 0, "charged": []}]))
    team_file_case("a fast move that is false and charged moves", text([{"species": "noctowl", "fast": False, "charged": ["SKY_ATTACK"]}]))
    team_file_case("a fast move that is a number", text([{"species": "noctowl", "fast": 5}]))
    team_file_case("a fast move that is a number and no charged moves", text([{"species": "noctowl", "fast": 5, "charged": []}]))
    team_file_case("a fast move that is a list", text([{"species": "noctowl", "fast": ["WING_ATTACK"]}]))
    team_file_case("charged moves that are empty", text([{"species": "noctowl", "fast": "WING_ATTACK", "charged": []}]))
    team_file_case("charged moves that are null", text([{"species": "noctowl", "fast": "WING_ATTACK", "charged": None}]))
    team_file_case("charged moves that are an empty text", text([{"species": "noctowl", "fast": "WING_ATTACK", "charged": ""}]))
    team_file_case("charged moves that are 0", text([{"species": "noctowl", "fast": "WING_ATTACK", "charged": 0}]))
    team_file_case("charged moves that are a text", text([{"species": "noctowl", "fast": "WING_ATTACK", "charged": "SKY_ATTACK"}]))
    team_file_case("charged moves that are a number", text([{"species": "noctowl", "charged": 5}]))
    team_file_case("charged moves with a number in them", text([{"species": "noctowl", "charged": ["SKY_ATTACK", 5]}]))
    team_file_case("charged moves with an empty name", text([{"species": "noctowl", "charged": ["SKY_ATTACK", ""]}]))
    team_file_case("a team of six", text([noctowl, lapras, lanturn, noctowl, lapras, lanturn]))

    return {"about": "Made by tools/make_engine_golden.py from battle_engine.py: what it answers. Do not edit.",
            "cases": cases}


def text():
    return json.dumps(build(), ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n"


if __name__ == "__main__":
    made = text()
    if "--check" in sys.argv:
        with open(OUT, encoding="utf-8") as handle:
            same = handle.read() == made
        print("engine_golden.json is" + (" " if same else " NOT ") + "what battle_engine.py answers")
        sys.exit(0 if same else 1)
    with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(made)
    print("wrote %s: %d bytes" % (OUT, len(made.encode("utf-8"))))
