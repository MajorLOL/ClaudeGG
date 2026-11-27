#!/usr/bin/env python3
"""Makes tests/fixtures/text_golden.json.qz (JSON, packed the way qCompress() of Qt does: the length, then zlib):
what gamebot.ocr_lines() and gamebot.ocr_line() make of what Tesseract wrote, as the file that the C++ port of the
text reader (SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoText.cpp) is tested against.

    python3 tools/make_text_golden.py            writes the file (reads pictures with the tesseract program for the
                                                 tables that the file does not have yet: sudo apt install tesseract-ocr)
    python3 tools/make_text_golden.py --check    says whether the file is what gamebot.py makes of its tables now
                                                 (no tesseract program is needed: the tables are in the file)

A case is the table that `tesseract stdin stdout --psm 11 tsv` wrote (or the text that it wrote without a table),
and what gamebot.py makes of it for a part of the picture (y0, y1) and a scale: the lines, with the place of every
word.  The tables are of three kinds: real ones (frames of real fights, read by Tesseract when the file was made:
the version of Tesseract does not matter later, they are in the file), made-up ones that look like them (a word
split in two, an unsure word, a double quote, accents) and a seeded lot of random ones."""
import argparse
import json
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import types
import zlib

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault("HOME", tempfile.mkdtemp())
import gamebot as G  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
FIGHT = os.path.join(FIXTURES, "fight")
OUT = os.path.join(FIXTURES, "text_golden.json.qz")
SEED = 20261129
CANVAS = (1768, 2208)
HEAD = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
#  what is read of a picture (y0, y1, scale): the whole of it, small; the lower part
REAL_PARTS = ((0, None, 0.5), (1400, None, 0.7))
REAL_PICTURES = 18


def table(words, extra=()):
    """The table of Tesseract for [(text, left, top, width, height, conf), ...]: the rows of the page, a block and a
    line without text, then one row per word."""
    rows = [HEAD, "1\t1\t0\t0\t0\t0\t0\t0\t1768\t2208\t-1\t", "2\t1\t1\t0\t0\t0\t10\t10\t900\t900\t-1\t"]
    for i, (text, left, top, width, height, conf) in enumerate(words):
        if i % 3 == 0:
            rows.append("4\t1\t1\t1\t%d\t0\t%s\t%s\t%s\t%s\t-1\t" % (i // 3 + 1, left, top, width, height))
        rows.append("5\t1\t1\t1\t%d\t%d\t%s\t%s\t%s\t%s\t%s\t%s" % (i // 3 + 1, i % 3 + 1, left, top, width, height, conf, text))
    rows.extend(extra)
    return "\n".join(rows) + "\n"


def parse(tsv, y0, y1, scale):
    """What gamebot.ocr_lines() makes of a table (it runs the tesseract program: here it answers with the table)."""
    saved = G.subprocess.run
    G.subprocess.run = lambda *a, **k: types.SimpleNamespace(stdout=tsv.encode("utf-8"))
    try:
        img = np.zeros((CANVAS[1], CANVAS[0], 3), np.uint8)
        lines = G.ocr_lines(img, y0, y1, scale)
    finally:
        G.subprocess.run = saved
    return [[text, x, y, [[w, wx, wy] for w, wx, wy in words]] for text, x, y, words in lines]


def one_line(raw):
    """What gamebot.ocr_line() makes of the text that Tesseract wrote."""
    saved = G.subprocess.run
    G.subprocess.run = lambda *a, **k: types.SimpleNamespace(stdout=raw.encode("utf-8"))
    try:
        return G.ocr_line(np.zeros((40, 200, 3), np.uint8))
    finally:
        G.subprocess.run = saved


def tesseract(img, y0, y1, scale):
    """The table that the tesseract program writes for a part of a picture, as gamebot.ocr_lines() asks for it."""
    crop = img[y0:y1]
    if scale != 1.0:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    ok, buf = cv2.imencode(".png", gray)
    done = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "11", "tsv"], input=buf.tobytes(),
                          capture_output=True, timeout=120)
    return done.stdout.decode()


def real_cases(old):
    cases = []
    names = sorted(n for n in os.listdir(FIGHT) if n.endswith(".jpg"))
    step = max(1, len(names) // REAL_PICTURES)
    for name in names[::step][:REAL_PICTURES]:
        img = None
        for y0, y1, scale in REAL_PARTS:
            key = "%s|%s|%s|%s" % (name, y0, y1, scale)
            tsv = old.get(key)
            if tsv is None:
                if shutil.which("tesseract") is None:
                    raise SystemExit("the table of %s is not in the file and there is no tesseract program here" % key)
                if img is None:
                    img = cv2.resize(cv2.imread(os.path.join(FIGHT, name)), CANVAS, interpolation=cv2.INTER_AREA)
                tsv = tesseract(img, y0, y1, scale)
            cases.append({"id": "real " + key, "tsv": tsv, "y0": y0, "y1": y1, "scale": scale})
    return cases


def made_up_cases():
    cases = []

    def add(name, words, y0=0, y1=None, scale=1.0, extra=()):
        cases.append({"id": "made up " + name, "tsv": table(words, extra), "y0": y0, "y1": y1, "scale": scale})

    add("two words on one line", [("Good", 800, 950, 200, 80, 91), ("effort!", 1010, 955, 260, 80, 88)])
    add("a quote does not swallow the rest", [("&", 1040, 640, 30, 40, 55), ('"', 947, 700, 20, 20, 61),
                                              ("GOOD", 800, 950, 200, 80, 91), ('"EFFORT!', 800, 1100, 260, 80, 85),
                                              ("NEXT", 780, 1890, 120, 40, 90), ("BATTLE", 920, 1890, 150, 40, 90)])
    add("unsure words are left out", [("GOOD", 800, 950, 200, 80, 91), ("x#", 100, 100, 30, 30, 12),
                                      ("edge", 300, 300, 80, 40, 39.9), ("on", 400, 300, 80, 40, 40), ("float", 500, 300, 80, 40, "40.0001")])
    add("positions of the whole picture", [("BATTLE", 100, 50, 200, 40, 90)], y0=1000, scale=0.5)
    add("scales", [("A", 33, 77, 21, 19, 99), ("bc", 151, 79, 25, 21, 98)], y0=17, scale=0.35)
    add("odd sizes", [("Odd", 101, 203, 55, 33, 77), ("size", 171, 205, 61, 35, 66)], y0=3, scale=0.7)
    add("accents and capitals", [("Pokémon", 100, 100, 200, 40, 90), ("straße", 320, 102, 200, 40, 90),
                                 ("señor", 100, 200, 200, 40, 90), ("ørsted", 320, 198, 200, 40, 90), ("łódź", 540, 200, 120, 40, 90)])
    add("spaces around a word", [("  padded  ", 100, 100, 200, 40, 90), ("   ", 320, 100, 40, 40, 95), ("next", 400, 100, 80, 40, 90)])
    add("same place, same height", [("B", 100, 100, 50, 40, 90), ("A", 100, 100, 50, 40, 90), ("C", 100, 100, 50, 40, 90)])
    add("a line that bends down", [("one", 100, 100, 60, 40, 90), ("two", 200, 120, 60, 40, 90), ("three", 300, 140, 60, 40, 90),
                                   ("four", 400, 160, 60, 40, 90), ("five", 500, 180, 60, 40, 90)])
    add("words 0.7 of a height apart", [("a", 100, 100, 40, 40, 90), ("b", 200, 126, 40, 40, 90), ("c", 300, 128, 40, 40, 90)])
    add("no words at all", [])
    add("conf not given", [("A", 100, 100, 40, 40, "")], extra=("5\t1\t1\t1\t9\t1\t300\t300\t40\t40",))
    add("a row cut short", [("A", 100, 100, 40, 40, 90)], extra=("5\t1\t1\t1\t9\t1\t300\t300",))
    add("an empty row", [("A", 100, 100, 40, 40, 90)], extra=("", "5\t1\t1\t1\t9\t1\t500\t300\t40\t40\t88\tB"))
    cases.append({"id": "made up no table", "tsv": "", "y0": 0, "y1": None, "scale": 1.0})
    cases.append({"id": "made up only the head", "tsv": HEAD + "\n", "y0": 0, "y1": None, "scale": 1.0})
    cases.append({"id": "made up windows line ends", "tsv": table([("Good", 800, 950, 200, 80, 91), ("win", 1010, 955, 260, 80, 88)]).replace("\n", "\r\n"),
                  "y0": 0, "y1": None, "scale": 1.0})
    return cases


def random_cases(count=300):
    rnd = random.Random(SEED)
    pieces = ["GO", "Battle", "NEXT", "x", "Poké", "ball!", "12", "CP1493", "$", "'", "\"", "é", "ß", "Ü", "ñ", "I'm", "a-b", "100%", "?", "©"]
    cases = []
    for k in range(count):
        words = []
        y = rnd.randint(0, 2100)
        for _ in range(rnd.randint(1, 40)):
            if rnd.random() < 0.3:
                y = rnd.randint(0, 2100)
            height = rnd.randint(14, 90)
            words.append((rnd.choice(pieces) + (rnd.choice(pieces) if rnd.random() < 0.3 else ""), rnd.randint(0, 1700), y + rnd.randint(-height // 2, height // 2),
                          rnd.randint(10, 400), height, rnd.choice([-1, 0, 30, 39, 40, 41, 55, 91, "91.5", "99.123456"])))
        words = [w for w in words if w[2] >= 0]
        cases.append({"id": "random %d" % k, "tsv": table(words), "y0": rnd.choice([0, 0, 17, 1000, 1400]), "y1": None,
                      "scale": rnd.choice([1.0, 1.0, 0.5, 0.35, 0.7, 0.45])})
    return cases


RAW_TEXTS = ["", "  \n", "NEXT BATTLE", "  NEXT   BATTLE \n", "line one\nline two\n", "tab\tseparated\n", "nbsp word\n",
             "Pokémon GO !", "a\x1cb\x1fc", "trailing space \r\n", "\n\n x \n\n", "ß", "one\u0085two"]


def build(old=None):
    old_tables = {}
    if old:
        for case in old["cases"]:
            if case["id"].startswith("real "):
                old_tables[case["id"][5:]] = case["tsv"]
    cases = real_cases(old_tables) + made_up_cases() + random_cases()
    for case in cases:
        case["lines"] = parse(case["tsv"], case["y0"], case["y1"], case["scale"])
    return {"cases": cases, "texts": [{"raw": raw, "line": one_line(raw)} for raw in RAW_TEXTS]}


def load():
    with open(OUT, "rb") as handle:
        packed = handle.read()
    return json.loads(zlib.decompress(packed[4:])), packed


def text(doc):
    return json.dumps(doc, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def check():
    old, packed = load()
    new = build(old)
    raw = text(new).encode("utf-8")
    if zlib.decompress(packed[4:]) == raw:
        print("text_golden.json.qz is what the text reader makes of its tables")
        return 0
    differ = [a["id"] for a, b in zip(old["cases"], new["cases"]) if a != b]
    print("text_golden.json.qz is NOT what the text reader makes of its tables: " + ", ".join(differ[:8]))
    return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        sys.exit(check())
    old = load()[0] if os.path.exists(OUT) else None
    raw = text(build(old)).encode("utf-8")
    with open(OUT, "wb") as handle:
        handle.write(struct.pack(">I", len(raw)) + zlib.compress(raw, 9))
    doc = json.loads(raw)
    print("wrote %s: %d tables (%d real), %d texts, %d bytes of JSON, packed to %d" % (
        OUT, len(doc["cases"]), len([c for c in doc["cases"] if c["id"].startswith("real ")]), len(doc["texts"]), len(raw),
        os.path.getsize(OUT)))
