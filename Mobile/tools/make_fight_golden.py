#!/usr/bin/env python3
"""Makes tests/fixtures/fight_golden.json.qz (JSON, packed the way qCompress() of Qt does: the length, then zlib): fights played with battle_fight.py, every call with its answer, the lines
it logged and the state after it, as the file that the C++ port of it
(SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoFight.cpp) is played against.

    python3 tools/make_fight_golden.py            writes the file
    python3 tools/make_fight_golden.py --check    says whether the file is what battle_fight.py does now
    python3 tools/make_fight_golden.py --coverage says which lines of battle_fight.py the fights do not reach

The pictures of the fights are the features of four real recordings (tests/fixtures/fight/features*.json, with the
noise of real readings) and made-up ones (the HP bars going down, shields going, buttons lighting and dimming, the Poké
Balls turning grey); between them come the calls the fight loop makes (the names that were read, the CP, the texts
under the buttons, the banners, the questions) and the ones it makes when something goes wrong (names that are
misread, a tap that missed, a Pokémon that fainted without a question).  A fixed seed makes it the same every time."""
import json
import os
import random
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import battle_engine as be  # noqa: E402
import battle_fight as bf  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
OUT = os.path.join(FIXTURES, "fight_golden.json.qz")
SEED = 20261128
FIGHTS = 60
STEPS = 200

CONFUSED = {"o": "0", "0": "o", "i": "l", "l": "i", "e": "c", "s": "5", "5": "s", "b": "6", "a": "o", "u": "v", "n": "m"}


def mutate(text, rnd):
    """What OCR does to a name: a letter misread, one gone, one doubled, a space inside, a stray word."""
    if len(text) < 2:
        return text
    kind = rnd.randrange(6)
    i = rnd.randrange(len(text))
    if kind == 0:
        return text[:i] + text[i + 1:]
    if kind == 1:
        return text[:i] + text[i] + text[i:]
    if kind == 2:
        return text[:i] + CONFUSED.get(text[i].lower(), "x") + text[i + 1:]
    if kind == 3:
        return text[:i] + " " + text[i:]
    if kind == 4:
        return text.upper()
    return rnd.choice(["Go,", "Cep", "CP"]) + " " + text


def mon_full(m):
    """A Pokémon as it stands: what the C++ port rebuilds it from."""
    return {"species": m.species, "shadow": bool(m.shadow), "level": m.level, "ivs": list(m.ivs), "fast": m.fast.id,
            "charged": [c.id for c in m.charged], "pos": m.pos, "atk": m.atk, "dfn": m.dfn, "max_hp": m.max_hp,
            "hp": m.hp, "hp_float": isinstance(m.hp, float), "max_hp_float": isinstance(m.max_hp, float), "cp": m.cp}


def known_out(known):
    return [[species, [[k, v] for k, v in counts.items()]] for species, counts in known.items()]


def snap(f):
    foe = f.foe
    return [f.me.pos, f.my_hp, f.foe_hp, f.my_shields, f.foe_shields, f.lit[0], f.lit[1], f.slots[0], f.slots[1],
            f.labels_ok, f.need_labels, f.label_tries, foe.species if foe else None, f.foe_cp,
            [m.id for m in foe.charged] if foe else None, foe.hp if foe else None, f.me.hp, sorted(f.dead), f.throws,
            f.clock, f.tile[0], f.tile[1], f.learned, f.since_foe, f.energy, f.foe_energy()]


def internals(f):
    return {"foe_e": list(f._foe_e), "foe_e_ok": f._foe_e_ok, "change": f._change, "read_at": f._read_at,
            "threw": None if f._threw is None else list(f._threw), "balls": list(f._balls), "seen": f._seen,
            "balls_at": f._balls_at, "named_at": f._named_at, "my_reads": f._my_reads, "my_read": f._my_read,
            "switch_seen": f._switch_seen, "known": known_out(f.known),
            "foe_seen": sorted([k, v] for k, v in f.foe_seen.items()), "alive": [m.pos for m in f.alive()]}


# ------------------------------------------------------------------ the pictures

def real_streams():
    out = []
    for name in ("features.json", "features_day.json", "features_day2.json", "features_day3.json"):
        with open(os.path.join(FIXTURES, "fight", name), encoding="utf-8") as handle:
            out.append(json.load(handle))
    return out


class Synthetic:
    """Made-up pictures of a fight: HP bars that go down, shields that go, buttons that light and dim."""

    def __init__(self, rnd):
        self.rnd = rnd
        self.me = 1.0
        self.foe = 1.0
        self.sh_me = 2
        self.sh_foe = 2
        self.red = 3

    def next(self):
        rnd = self.rnd
        r = rnd.random()
        self.me = max(0.0, round(self.me - rnd.choice([0, 0, 0.01, 0.02, 0.05]), 2))
        self.foe = max(0.0, round(self.foe - rnd.choice([0, 0, 0.01, 0.02, 0.04]), 2))
        if rnd.random() < 0.03:
            self.me = rnd.choice([1.0, 0.1, 0.05, self.me])           # a new one of ours comes in
        if rnd.random() < 0.03:
            self.foe = rnd.choice([1.0, 0.3, self.foe])               # a new foe
        if rnd.random() < 0.04 and self.sh_me > 0:
            self.sh_me -= 1
        if rnd.random() < 0.04 and self.sh_foe > 0:
            self.sh_foe -= 1
        if rnd.random() < 0.02:
            self.sh_me = rnd.choice([2, 1, 0])
        if rnd.random() < 0.03 and self.red > 1:
            self.red -= 1
        hp_me = self.me if rnd.random() > 0.05 else rnd.choice([None, round(rnd.random(), 2)])
        hp_foe = self.foe if rnd.random() > 0.05 else rnd.choice([None, round(rnd.random(), 2)])
        sh_me = self.sh_me if rnd.random() > 0.06 else rnd.choice([None, 0, 1, 2])
        sh_foe = self.sh_foe if rnd.random() > 0.06 else rnd.choice([None, 0, 1, 2])
        balls = None
        if rnd.random() < 0.8:
            red = self.red if rnd.random() > 0.05 else rnd.choice([1, 2, 3])
            balls = {"me": [red, 3 - red] if rnd.random() > 0.05 else [red, 0], "foe": [3, 0]}
        feat = {"hud": r > 0.08, "white": r < 0.02, "versus": 0.02 <= r < 0.04, "ring": 0.04 <= r < 0.08,
                "count": "", "hex": False, "result": 0.99 < r, "ready": [rnd.random() < 0.3, rnd.random() < 0.2],
                "shields": {"me": sh_me, "foe": sh_foe}, "hp": [hp_me, hp_foe], "get_ready": False, "balls": balls}
        if rnd.random() < 0.02:
            feat["done"] = True
        return feat


# ------------------------------------------------------------------ one fight

def make_team(rnd, species_ranked):
    if rnd.random() < 0.35:
        return be.build_team([dict(e) for e in be.DEFAULT_TEAM])
    entries = []
    used = set()
    for _ in range(3):
        s = rnd.choice(species_ranked)
        while s in used:
            s = rnd.choice(species_ranked)
        used.add(s)
        e = {"species": s}
        if rnd.random() < 0.3:
            e["shadow"] = True
        if rnd.random() < 0.1:
            e["fast"], moves = be.default_moveset(s)[0], be.default_moveset(s)[1]
            e["charged"] = list(moves)[:1]
        if rnd.random() < 0.5:
            m = be.Mon(s, level=rnd.choice([20.0, 25.0, 30.0, 40.0]),
                       ivs=[rnd.randrange(16), rnd.randrange(16), rnd.randrange(16)])
            e["cp"], e["hp"] = m.cp, int(m.max_hp)
        entries.append(e)
    return be.build_team(entries)


def one_fight(rnd, index, species_ranked, names_by_species, streams, feats_table, feats_index):
    data = be.load()
    team = make_team(rnd, species_ranked)
    foes = [rnd.choice(species_ranked) for _ in range(4)]
    known = {}
    if rnd.random() < 0.5:
        for s in foes:
            pool = data["mons"][s][6]
            if pool and rnd.random() < 0.7:
                counts = {}
                for mid in rnd.sample(pool, min(len(pool), rnd.randrange(1, 3))):
                    counts[mid] = rnd.randrange(1, 6)
                if rnd.random() < 0.6:
                    counts["first:" + rnd.choice(pool)] = rnd.randrange(4, 12)
                    if rnd.random() < 0.3:
                        counts["first:" + rnd.choice(pool)] = rnd.randrange(1, 4)
                known[s] = counts
    start = {"team": [mon_full(m) for m in team], "known": known_out(known)}
    logs = []
    fight = bf.Fight(team, log=logs.append, known=known)
    if rnd.random() < 0.5:
        fight.foe_every, fight.shields_back = 10, 20
    start["foe_every"], start["shields_back"] = fight.foe_every, fight.shields_back
    kind = rnd.randrange(3)
    if kind == 0:
        stream, at = rnd.choice(streams), 0
        synth = None
    else:
        stream, at = None, 0
        synth = Synthetic(rnd)
    foe_now = [0]
    steps = []

    def foe_name():
        s = foes[foe_now[0] % len(foes)]
        name = names_by_species[s]
        r = rnd.random()
        if r < 0.1:
            return mutate(name, rnd)
        if r < 0.15:
            return ""
        if r < 0.18:
            return "Go, " + name + "!"
        if r < 0.22:
            return rnd.choice(["Zzqxj", "Xqzv Wk", "Awe", "12345", "Qqqq"])
        return name

    def add(call, args, out):
        steps.append({"call": call, "args": args, "out": out, "log": list(logs), "st": snap(fight)})
        del logs[:]

    def see():
        nonlocal at
        if stream is not None:
            feat = stream[at % len(stream)]
            at += 1
        else:
            feat = synth.next()
        key = json.dumps(feat, sort_keys=True)
        if key not in feats_index:
            feats_index[key] = len(feats_table)
            feats_table.append(feat)
        fight.see(feat)
        add("see", [feats_index[key]], None)

    def mine_cp(noise=True):
        m = rnd.choice(team)
        if rnd.random() < 0.6:
            m = fight.me
        cp = m.cp + (rnd.choice([-1, 0, 0, 1, 2, 7]) if noise else 0)
        return cp

    def burst_rise():
        """Our bar reads higher than we believe on picture after picture (a misread kept for long)."""
        for _i in range(14):
            feat = json.loads(json.dumps(stream[at % len(stream)] if stream else synth.next()))
            feat["hud"], feat["white"], feat["versus"], feat["ring"] = True, False, False, False
            feat["hp"] = [min(1.0, round(fight.my_hp + 0.1, 3)), feat["hp"][1]]
            key = json.dumps(feat, sort_keys=True)
            if key not in feats_index:
                feats_index[key] = len(feats_table)
                feats_table.append(feat)
            fight.see(feat)
            add("see", [feats_index[key]], None)

    def burst_balls():
        """Poké Balls of ours turn grey on picture after picture, with the name box seen to change between."""
        red = 3 - (len(fight.dead) + 1)
        if red < 0:
            return
        others = [m for m in team if m.pos not in fight.dead and m is not fight.me]
        order = rnd.choice(["before", "after", "none"])
        for i in range(3):
            feat = {"hud": True, "white": False, "versus": False, "ring": False, "count": "", "hex": False,
                    "result": False, "ready": [False, False], "shields": {"me": 2, "foe": 2},
                    "hp": [fight.my_hp, fight.foe_hp], "get_ready": False,
                    "balls": {"me": [red, 3 - red], "foe": [3, 0]}}
            key = json.dumps(feat, sort_keys=True)
            if key not in feats_index:
                feats_index[key] = len(feats_table)
                feats_table.append(feat)
            if i == 1 and order == "after" and others:
                cp = others[0].cp
                fight.set_active(cp)
                add("set_active", [cp], None)
            fight.see(feat)
            add("see", [feats_index[key]], None)
            if i == 0 and order == "before" and others:
                cp = others[0].cp
                fight.set_active(cp)
                add("set_active", [cp], None)

    def burst_labels():
        """The texts under the buttons are not read, again and again."""
        for _i in range(9):
            texts = [rnd.choice(["", "xx", "???"]), rnd.choice(["", "yy"])]
            fight.set_buttons(texts[0], texts[1])
            add("set_buttons", texts, None)

    for _ in range(STEPS):
        r = rnd.random()
        q = rnd.random()
        if q < 0.012:
            burst_rise()
            continue
        if q < 0.03:
            burst_balls()
            continue
        if q < 0.036:
            burst_labels()
            continue
        if r < 0.42:
            see()
        elif r < 0.47 or (fight.foe_due and r < 0.60):
            if rnd.random() < 0.05:
                foe_now[0] += 1
            name = foe_name()
            cp = rnd.choice([None, 0, 1493, 1480, 1022, rnd.randrange(300, 1500)])
            add("set_foe", [name, cp], fight.set_foe(name, cp))
        elif r < 0.52:
            cp = rnd.choice([None, 0, mine_cp(), mine_cp(), mine_cp(False)])
            fight.set_active(cp)
            add("set_active", [cp], None)
        elif r < 0.56:
            moves = fight.me.charged
            names = [m.name for m in moves]
            texts = [names[0] if names else "", names[1] if len(names) > 1 else ""]
            if rnd.random() < 0.3:
                texts.reverse()
            texts = [t if rnd.random() > 0.15 else mutate(t, rnd) for t in texts]
            texts = [t if rnd.random() > 0.15 else t + " Super effective" for t in texts]
            if rnd.random() < 0.1:
                texts[rnd.randrange(2)] = ""
            if rnd.random() < 0.05:
                texts = [texts[0], texts[0]]
            fight.set_buttons(texts[0], texts[1])
            add("set_buttons", texts, None)
        elif r < 0.66:
            res = fight.throw()
            add("throw", [], None if res is None else [res[0], res[1].id, res[2]])
        elif r < 0.70:
            res = fight.aim()
            add("aim", [], None if res is None else [res[0], res[1].id])
        elif r < 0.75:
            foes_left = rnd.choice([None, 1, 2, 3])
            ready = rnd.random() < 0.3
            res = fight.shield(foes_left, ready)
            add("shield", [foes_left, ready], list(res))
        elif r < 0.77:
            sure = rnd.random() < 0.8
            fight.foe_threw(sure)
            add("foe_threw", [sure], None)
        elif r < 0.82:
            who = fight.foe if (fight.foe and rnd.random() < 0.8) else None
            if rnd.random() < 0.15:
                who = fight.me
            if who is None:
                text = rnd.choice(["", "Go, Lapras!", "used", "Something used"])
            else:
                pool = list(who.charged) + [be.Move(rnd.choice(data["mons"][who.species][6] or ["TACKLE"]))]
                move = rnd.choice(pool)
                text = "%s used %s!" % (who.name if rnd.random() > 0.15 else mutate(who.name, rnd),
                                        move.name if rnd.random() > 0.15 else mutate(move.name, rnd))
            res = fight.foe_used(text)
            add("foe_used", [text], None if res is None else res.id)
        elif r < 0.87:
            seconds = rnd.choice([0.1, 0.5, 1.0, 2.5, 4.0, 9.0, 15.0, 30.0, -1.0])
            fight.fought(seconds)
            add("fought", [seconds], None)
        elif r < 0.89:
            side = rnd.choice([None, "me", "foe"])
            fight.read_names(side)
            add("read_names", [side], None)
        elif r < 0.91:
            pos = rnd.choice([fight.me.pos, fight.me.pos, 99, rnd.randrange(3)])
            who = fight.me if pos == fight.me.pos else (team[pos] if pos < 3 else be.Mon("noctowl"))
            fight.buttons_swapped(who)
            add("buttons_swapped", [pos], None)
        elif r < 0.93:
            left = fight.alive()
            tiles = []
            for i, m in enumerate(rnd.sample(team, len(team))[:rnd.choice([2, 2, 3])]):
                cp = m.cp + rnd.choice([0, 0, 1, -1, 3]) if rnd.random() > 0.3 else 0
                tiles.append([cp, 300 + 400 * i])
            shown = rnd.choice([None, None, 2, 3, len(left)])
            res = fight.switch([tuple(t) for t in tiles], shown)
            add("switch", [tiles, shown], [res[0], None if res[1] is None else res[1].pos, res[2]])
        elif r < 0.95:
            res = fight.doomed()
            add("doomed", [], list(res))
            add("fights_on", [], fight.fights_on())
        elif r < 0.96:
            foes_left = rnd.choice([0, 1, 2, 3])
            add("hopeless", [foes_left], list(fight.hopeless(foes_left)))
        elif r < 0.97:
            res = fight.predict_first()
            add("predict_first", [], None if res is None else [res[0].id, res[1], res[2]])
        elif r < 0.98:
            add("misc", [], [fight.energy, fight.foe_energy(), fight.threw_with(), fight.foe_due,
                             [None if fight.move_of(i) is None else fight.move_of(i).id for i in (0, 1)],
                             [m.pos for m in fight.alive()]])
        elif r < 0.985:
            fight.faint()
            add("faint", [], None)
        else:
            feat = json.loads(json.dumps(synth.next() if synth else stream[rnd.randrange(len(stream))]))
            for flag in ("hud", "white", "versus", "ring", "result"):
                if rnd.random() < 0.25:
                    feat[flag] = not feat[flag]
            add("state", [feat], bf.state(feat))
    return {"start": start, "steps": steps, "final": internals(fight)}


def build():
    rnd = random.Random(SEED)
    data = be.load()
    species_ranked = [s for s in data["sets"]["1500"] if s in data["mons"]]
    names_by_species = {s: data["mons"][s][0] for s in data["mons"]}
    streams = real_streams()
    feats_table, feats_index = [], {}
    fights = [one_fight(rnd, i, species_ranked, names_by_species, streams, feats_table, feats_index)
              for i in range(FIGHTS)]
    return {"about": "Made by tools/make_fight_golden.py from battle_fight.py: fights played with it. Do not edit.",
            "feats": feats_table, "fights": fights}


def text():
    return json.dumps(build(), ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n"


def coverage():
    """Which lines of battle_fight.py the fights run."""
    path = os.path.abspath(bf.__file__)
    hit = set()

    def tracer(frame, event, _arg):
        if frame.f_code.co_filename == path:
            if event == "line":
                hit.add(frame.f_lineno)
            return tracer
        return None

    sys.settrace(tracer)
    build()
    sys.settrace(None)
    wanted = set()
    source = open(path, encoding="utf-8").read().splitlines()
    import ast
    tree = ast.parse("\n".join(source))
    for node in ast.walk(tree):
        if isinstance(node, (ast.stmt,)) and not isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Import,
                                                                    ast.ImportFrom)):
            wanted.add(node.lineno)
    missing = sorted(wanted - hit)
    print("%d of %d statements run" % (len(wanted) - len(missing), len(wanted)))
    for n in missing:
        print("%4d  %s" % (n, source[n - 1].strip()[:110]))


if __name__ == "__main__":
    if "--coverage" in sys.argv:
        coverage()
        sys.exit(0)
    raw = text().encode("utf-8")
    if "--check" in sys.argv:
        with open(OUT, "rb") as handle:
            packed = handle.read()
        same = len(packed) > 4 and struct.unpack(">I", packed[:4])[0] == len(raw) and zlib.decompress(packed[4:]) == raw
        print("fight_golden.json.qz is" + (" " if same else " NOT ") + "what battle_fight.py does")
        sys.exit(0 if same else 1)
    with open(OUT, "wb") as handle:
        handle.write(struct.pack(">I", len(raw)) + zlib.compress(raw, 9))
    print("wrote %s: %d bytes of JSON, packed to %d" % (OUT, len(raw), os.path.getsize(OUT)))
