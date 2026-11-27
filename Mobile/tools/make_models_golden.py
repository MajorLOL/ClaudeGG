#!/usr/bin/env python3
"""Makes tests/fixtures/models_golden.json: what the RegiBot models say through gamebot.py (LiteRT, the TFLite files the
Raspberry Pi runs), as the file that the C++ port of them (SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoModels.cpp,
ONNX Runtime, the ONNX copies made by tools/convert_models_to_onnx.py) is tested against.

    python3 tools/make_models_golden.py --models DIR            writes the file
    python3 tools/make_models_golden.py --models DIR --check    says whether the file is what the models say now

DIR holds the five .tflite files (the folder that install.sh fills; the default is ~/models, or the folder in the
environment variable CLAUDEGG_TFLITE).

The answers are the ones of Brain in gamebot.py: the screen classifier (all nine certainties), the map detector and the
clickable-object detector (what Brain._ssd makes of them: the 27621 boxes decoded with the anchors, the size filter and
the non-maximum suppression; at three thresholds, the last two so low that the decoding and the suppression have a lot to
do on pictures that show no map), and the throw predictor.  The pictures are the frames of the fights, the home screens
and the little game in tests/fixtures/, whole and in one cut-out each (a fixed seed makes it the same every time).

The encounter detector (Brain.encounter_objects) is in it too, with its own post-processing: the C++ port runs the network cut
in front of that (convert_models_to_onnx.cut_encounter) and does the rest itself, so this tool has a second way to the same
answers, a NumPy version of TensorFlow Lite's post-processing, and makes sure that it agrees with the whole model on every
picture before it is used for the made-up answers.

The choice from a detector's boxes is held on its own too: "decode" has the answers of Brain._ssd to made-up answers of
a network (27,621 boxes and certainties from a little generator of numbers that both sides have, with many equal
certainties, so the order of the equal ones counts).
The two runtimes do not give the same bits, so every comparison has a margin, the same one on both sides: certainties and
scores differ by at most SCORE_TOL, a position or a size by at most PIXEL_TOL, the throw by at most THROW_TOL.  The detection
lists must have the same labels in the same order."""
import glob
import json
import os
import random
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
OUT = os.path.join(FIXTURES, "models_golden.json")
SEED = 20261129
SCORE_TOL = 1e-4
PIXEL_TOL = 1
THROW_TOL = 0.01
ENCOUNTER_LOOKS = [0.2, 0.0]                       # thresholds of Brain.encounter_objects: its own, and none
LOOKS = [(0.2, 10), (0.01, 10), (0.01, 200)]      # (threshold, how many) of Brain._ssd: its own, and two low ones
BOXES = 27621
MASK = (1 << 64) - 1
# the made-up answers: (kind, seed, picture width, picture height, threshold, how many)
DECODES = [(kind, seed, w, h, th, top)
           for kind in ("map", "clickable")
           for seed, (w, h) in ((11, (772, 618)), (12, (1768, 2208)))
           for th, top in ((0.2, 10), (0.0, 200), (0.05, 5))]
DECODES += [("encounter", seed, w, h, th, 10)
            for seed, (w, h) in ((21, (772, 618)), (22, (437, 360)), (23, (1768, 2208)))
            for th in ENCOUNTER_LOOKS]


class Lcg:
    """A generator of numbers that the C++ port has too (a linear congruential one of 64 bits, the top 31 bits)."""
    def __init__(self, seed):
        self.state = seed & MASK

    def next(self):
        self.state = (self.state * 6364136223846793005 + 1442695040888963407) & MASK
        return self.state >> 33


def made_up_answer(seed, classes, count=BOXES):
    """(boxes [N, 4], certainties [N, classes]) of a network that never was: most certainties low, a few high, and all of
    them from short lists of values, so that many are equal (also the ones of the classes of one box)."""
    g = Lcg(seed)
    boxes = np.empty((count, 4), np.float32)
    scores = np.empty((count, classes), np.float32)
    for n in range(count):
        for j in range(4):
            boxes[n, j] = ((g.next() % 2001) - 1000) / 10000.0 if j < 2 else ((g.next() % 1001) - 500) / 1000.0
        for c in range(classes):
            r = g.next()
            scores[n, c] = (r % 100) / 100.0 if (r >> 10) % 25 == 0 else (r % 16) / 160.0
            if c > 0 and (r >> 4) % 5 == 0:         # now and then a class is exactly as sure as the one before it
                scores[n, c] = scores[n, c - 1]
    return boxes, scores


class MadeUpNetwork:
    """Stands in for an Interpreter: Brain._run asks it for its outputs."""
    def __init__(self, boxes, scores):
        self.outputs = [("boxes", boxes[None]), ("scores", scores[None])]

    def get_input_details(self):
        return [{"index": 0}]

    def set_tensor(self, index, x):
        pass

    def invoke(self):
        pass

    def get_output_details(self):
        return [{"index": i, "name": name} for i, (name, _) in enumerate(self.outputs)]

    def get_tensor(self, index):
        return self.outputs[index][1]


def models_dir(argv):
    if "--models" in argv:
        return argv[argv.index("--models") + 1]
    return os.environ.get("CLAUDEGG_TFLITE") or os.path.expanduser("~/models")


def make_brain(folder):
    """A Brain with only what the readers need (no threads, no copies of the map detector)."""
    import gamebot as G
    from ai_edge_litert.interpreter import Interpreter

    def load(name):
        it = Interpreter(model_path=os.path.join(folder, name), num_threads=1)
        it.allocate_tensors()
        return it
    brain = object.__new__(G.Brain)
    brain.clf = load("model_classifier_screen_v5.tflite")
    brain.map = load("model_detector_map_v2.tflite")
    brain.clk = load("model_detector_clickable_v2.tflite")
    anchors = np.load(os.path.join(ROOT, "models", "anchors.npz"))
    brain.map_anchors = anchors["model_detector_map_v2_anchors"]
    brain.clk_anchors = anchors["model_detector_clickable_v2_anchors"]
    brain.pred = dict(np.load(os.path.join(ROOT, "models", "predictor_weights.npz")))
    brain.enc = load("model_detector_encounter.tflite")
    # the same network cut in front of its post-processing (what the C++ port runs), and its anchors
    import convert_models_to_onnx as C
    cut, brain.enc_anchors = C.cut_encounter(Path(folder) / "model_detector_encounter.tflite")
    brain.enc_cut = Interpreter(model_content=cut, num_threads=1)
    brain.enc_cut.allocate_tensors()
    return G, brain


def encounter_reference(G, boxes, certainties, anchors, w0, h0, th):
    """TensorFlow Lite's TFLite_Detection_PostProcess in its fast variant with the settings of the encounter detector
    (y and x scale 10, h and w scale 5, 10 detections, one class per box, overlap 0.6, no threshold), then the end of
    Brain.encounter_objects.  The box decoding is in double and then float as TensorFlow Lite does it, the rest in float32;
    equal certainties keep the order of the boxes."""
    n = len(boxes)
    be, an = boxes.astype(np.float64), anchors.astype(np.float64)
    y_center = (be[:, 0] / 10.0 * an[:, 2] + an[:, 0]).astype(np.float32)
    x_center = (be[:, 1] / 10.0 * an[:, 3] + an[:, 1]).astype(np.float32)
    half_h = (0.5 * np.exp(be[:, 2] / 5.0) * an[:, 2]).astype(np.float32)
    half_w = (0.5 * np.exp(be[:, 3] / 5.0) * an[:, 3]).astype(np.float32)
    ymin, xmin, ymax, xmax = y_center - half_h, x_center - half_w, y_center + half_h, x_center + half_w
    classes = certainties[:, 1:]
    best = classes.argmax(axis=1)
    top = classes[np.arange(n), best]
    order = np.flatnonzero(~(top < 0.0))
    order = order[np.argsort(-top[order], kind="stable")]
    area = (ymax - ymin) * (xmax - xmin)
    selected, active = [], np.ones(len(order), bool)
    zero = np.float32(0)
    with np.errstate(divide="ignore", invalid="ignore"):
        for i in range(len(order)):
            if len(selected) >= 10:
                break
            if not active[i]:
                continue
            a = order[i]
            selected.append(a)
            active[i] = False
            rest = np.flatnonzero(active[i + 1:]) + i + 1
            if not len(rest):
                continue
            b = order[rest]
            inter = (np.maximum(np.minimum(ymax[a], ymax[b]) - np.maximum(ymin[a], ymin[b]), zero)
                     * np.maximum(np.minimum(xmax[a], xmax[b]) - np.maximum(xmin[a], xmin[b]), zero))
            iou = np.where((area[a] <= 0) | (area[b] <= 0), zero, inter / (area[a] + area[b] - inter))
            active[rest[iou > np.float32(0.6)]] = False
    found = []
    for a in selected:
        score = top[a]
        if score >= np.float32(th):
            y1, x1, y2, x2 = ymin[a], xmin[a], ymax[a], xmax[a]
            found.append((G.ENC_LABELS[int(best[a])], float(score), int((x1 + x2) / 2 * w0), int((y1 + y2) / 2 * h0),
                          int((x2 - x1) * w0), int((y2 - y1) * h0)))
    return sorted(found, key=lambda t: -t[1])


def pictures():
    """[(name, cut-out or None)]: every picture whole, and once with a part of it cut out."""
    rng = random.Random(SEED)
    names = sorted(os.path.relpath(p, FIXTURES).replace(os.sep, "/")
                   for kind in ("*.jpg", "*.png") for p in glob.glob(os.path.join(FIXTURES, "*", kind)))
    out = []
    for name in names:
        h, w = cv2.imread(os.path.join(FIXTURES, name)).shape[:2]
        fw, fh = rng.uniform(0.4, 0.8), rng.uniform(0.4, 0.8)
        x0, y0 = int(rng.uniform(0, 1 - fw) * w), int(rng.uniform(0, 1 - fh) * h)
        out += [(name, None), (name, [x0, y0, x0 + max(int(fw * w), 8), y0 + max(int(fh * h), 8)])]
    return out


def screen_probabilities(G, brain, img):
    """The nine certainties of the classifier, with the preprocessing of Brain.screen."""
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    x = cv2.resize(cv2.resize(rgb, (256, 256)), (224, 224)).astype(np.float32) / 255.0
    return [float(v) for v in list(G.Brain._run(brain.clf, x).values())[0]]


def read(G, brain, folder_picture):
    name, cut = folder_picture
    img = cv2.imread(os.path.join(FIXTURES, name))
    if cut:
        x0, y0, x1, y1 = cut
        img = img[y0:y1, x0:x1]
    label, score = brain.screen(img)
    probs = screen_probabilities(G, brain, img)
    assert G.SCREENS[int(np.argmax(probs))] == label
    case = {"picture": name, "cut": cut, "screen": {"label": label, "score": score, "probs": probs}}
    for kind, it, anchors, labels in (("map", brain.map, brain.map_anchors, G.MAP_LABELS),
                                      ("clickable", brain.clk, brain.clk_anchors, G.CLICK_LABELS)):
        case[kind] = [{"th": th, "top": top,
                       "found": [[o[0], o[1], o[2], o[3], o[4], o[5]]
                                 for o in brain._ssd(it, anchors, labels, img, th=th, top=top)]}
                      for th, top in LOOKS]
    # the encounter detector: the whole model, and the NumPy post-processing on the cut network (they must agree)
    rgb = cv2.cvtColor(cv2.resize(img, (640, 640)), cv2.COLOR_BGR2RGB)
    cut = G.Brain._run(brain.enc_cut, (rgb.astype(np.float32) - 127.5) / 127.5)
    case["encounter"] = []
    for th in ENCOUNTER_LOOKS:
        found = [[o[0], o[1], o[2], o[3], o[4], o[5]] for o in brain.encounter_objects(img, th=th)]
        mine = encounter_reference(G, cut["concat"], cut["convert_scores"], brain.enc_anchors, img.shape[1], img.shape[0], th)
        why = found_differ(found, [list(o) for o in mine])
        assert why is None, f"the NumPy post-processing is not what the model does ({name}, {th}): {why}"
        case["encounter"].append({"th": th, "found": found})
    return case


def throws(G, brain):
    rng = random.Random(SEED + 1)
    out = []
    for _ in range(200):
        args = [rng.uniform(0, G.W), rng.uniform(0, G.H), rng.uniform(20, 400), rng.uniform(20, 400)]
        dy, dur = brain.throw_params(*args)
        out.append({"in": args, "dy": dy, "ms": dur})
    return out


def decodes(G, brain):
    out, cache = [], {}
    for kind, seed, w, h, th, top in DECODES:
        if kind == "encounter":
            if (kind, seed) not in cache:
                cache[(kind, seed)] = made_up_answer(seed, 4, len(brain.enc_anchors))
            boxes, certainties = cache[(kind, seed)]
            found = encounter_reference(G, boxes, certainties, brain.enc_anchors, w, h, th)
            out.append({"kind": kind, "seed": seed, "w": w, "h": h, "th": th, "top": top,
                        "found": [[o[0], o[1], o[2], o[3], o[4], o[5]] for o in found]})
            continue
        anchors, labels = ((brain.map_anchors, G.MAP_LABELS) if kind == "map" else (brain.clk_anchors, G.CLICK_LABELS))
        if (kind, seed) not in cache:
            cache[(kind, seed)] = made_up_answer(seed, len(labels))
        found = brain._ssd(MadeUpNetwork(*cache[(kind, seed)]), anchors, labels, np.zeros((h, w, 3), np.uint8), th=th, top=top)
        out.append({"kind": kind, "seed": seed, "w": w, "h": h, "th": th, "top": top,
                    "found": [[o[0], o[1], o[2], o[3], o[4], o[5]] for o in found]})
    return out


def build(folder):
    G, brain = make_brain(folder)
    return {"score_tol": SCORE_TOL, "pixel_tol": PIXEL_TOL, "throw_tol": THROW_TOL,
            "screens": list(G.SCREENS),
            "cases": [read(G, brain, p) for p in pictures()],
            "decode": decodes(G, brain),
            "throws": throws(G, brain)}


def found_differ(fu, fv):
    """Why two lists of detections [label, score, cx, cy, w, h] are not the same within the margins (None when they are)."""
    if [f[0] for f in fu] != [f[0] for f in fv]:
        return f"the labels {[f[0] for f in fu]} / {[f[0] for f in fv]}"
    for f, g in zip(fu, fv):
        if abs(f[1] - g[1]) > SCORE_TOL or any(abs(f[i] - g[i]) > PIXEL_TOL for i in range(2, 6)):
            return f"{f} / {g}"
    return None


def differences(a, b):
    """What differs beyond the margins between two files (a list of words, empty when they agree)."""
    out = []
    if a["screens"] != b["screens"]:
        out.append("the names of the screens")
    if len(a["cases"]) != len(b["cases"]) or len(a["throws"]) != len(b["throws"]) or len(a["decode"]) != len(b["decode"]):
        return out + ["the number of cases"]
    for n, (x, y) in enumerate(zip(a["cases"], b["cases"])):
        if (x["picture"], x["cut"]) != (y["picture"], y["cut"]):
            out.append(f"case {n}: another picture")
            continue
        if x["screen"]["label"] != y["screen"]["label"]:
            out.append(f"case {n}: screen {x['screen']['label']} / {y['screen']['label']}")
        for p, q in zip(x["screen"]["probs"], y["screen"]["probs"]):
            if abs(p - q) > SCORE_TOL:
                out.append(f"case {n}: a certainty of the classifier {p} / {q}")
                break
        for kind in ("map", "clickable"):
            for u, v in zip(x[kind], y[kind]):
                why = found_differ(u["found"], v["found"])
                if why:
                    out.append(f"case {n}: {kind} at {u['th']}: {why}")
        for u, v in zip(x["encounter"], y["encounter"]):
            why = found_differ(u["found"], v["found"])
            if why:
                out.append(f"case {n}: encounter at {u['th']}: {why}")
    for n, (x, y) in enumerate(zip(a["decode"], b["decode"])):
        why = found_differ(x["found"], y["found"])
        if why:
            out.append(f"made-up answer {n} ({x['kind']}, seed {x['seed']}, {x['th']}, {x['top']}): {why}")
    for n, (x, y) in enumerate(zip(a["throws"], b["throws"])):
        if abs(x["dy"] - y["dy"]) > THROW_TOL or abs(x["ms"] - y["ms"]) > THROW_TOL:
            out.append(f"throw {n}: {x['dy']}, {x['ms']} / {y['dy']}, {y['ms']}")
    return out


def main(argv):
    folder = models_dir(argv)
    for name in ("model_classifier_screen_v5", "model_detector_map_v2", "model_detector_clickable_v2", "model_detector_encounter"):
        if not os.path.isfile(os.path.join(folder, name + ".tflite")):
            print(f"{name}.tflite is not in {folder} (--models DIR)")
            return 2
    made = build(folder)
    if "--check" in argv:
        with open(OUT, encoding="utf-8") as f:
            stored = json.load(f)
        wrong = differences(stored, made)
        if wrong:
            print(f"{len(wrong)} differences between {OUT} and what the models say now:")
            for line in wrong[:20]:
                print("  " + line)
            return 1
        print(f"{OUT} is what the models say ({len(made['cases'])} pictures, {len(made['decode'])} made-up answers, "
              f"{len(made['throws'])} throws).")
        return 0
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(made, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    print(f"wrote {OUT}: {len(made['cases'])} pictures, {len(made['decode'])} made-up answers, {len(made['throws'])} throws, "
          f"{os.path.getsize(OUT)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
