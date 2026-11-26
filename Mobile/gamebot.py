#!/usr/bin/env python3
"""
Gamebot v3 - Pokémon GO automation with image recognition (LiteRT).

Recognises, with the models of RegiBot (MIT, github.com/Juancavr6/RegiBot):
  - which screen is open (map, PokéStop, catch, reward, egg, menu, summary, ...)
  - Pokémon and PokéStops on the map
  - the target ring around the Pokémon while catching
  - buttons (OK, CLAIM REWARD, "I am a passenger")
and uses their 'predictor' to calculate how hard and how far the ball must be thrown.

All basic functions (ADB, unlocking, bag full, spinning stops, restarting)
come from spin_stop.py, which must be in the same folder.

Usage:
  ~/gbvenv/bin/python gamebot.py          -> keeps running
  ~/gbvenv/bin/python gamebot.py test     -> analyse 1 screenshot (debug/g_test.png)
  ~/gbvenv/bin/python gamebot.py step     -> do 1 step ("stap" works too)
  ~/gbvenv/bin/python gamebot.py battle   -> walk from the map to the party screen of the battle league and
                                             back (bot stopped, game open on the map; pictures in ~/debug/g_battle_*.png)
"""
import atexit
import csv
import difflib
import io
import json
import os
import queue
import random
import re
import signal
import subprocess
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

import battle_nav as BN
import spin_stop as S   # hergebruik van de bestaande functies

# ============================== INSTELLINGEN ==============================
MODEL_DIR = os.path.expanduser("~/models")
CATCH = True                  # catch Pokémon
SPIN = True                   # PokéStops draaien
BERRY_ORDER = ["pinap", "razz", "nanab"]   # Pinap first; when those run out Razz, then Nanab.
                              # Silver Pinap and Golden Razz are NEVER used. [] = no berries
BALL = "poke"                 # "poke", "great" of "ultra"
MAX_THROWS = 8                # then run away
THROW_BOOST = 0.8             # duration factor of the throw (RegiBot default 0.8 = 20% harder)
THROW_FALLBACK = (-1300, 250) # (deltaY, ms) when the target ring is not found
IDLE_WAIT = 8                 # wait (s) when there is nothing to do on the map
COOLDOWN = 5 * 60             # spot where tapping gave nothing: skip it this long
STORAGE_FULL_WAIT = 30 * 60   # storage full: do not catch for this long
GIFT_INTERVAL = 60 * 60       # how often to go through the friend list (seconds)
ROCKET_COOLDOWN = 30 * 60     # Team Rocket at a stop: leave that stop alone this long
ROTATE = True                 # turn the camera around to find Pokémon behind/next to the player
ROTATE_SWIPE = (350, 900, 1050, 900, 600)   # horizontal swipe across the map = turn the camera (700 px = ~45 degrees)
# Looking around is varied like the 'Realistic' throws, so that it is not the same swipe every time:
ROTATE_TURN = (365, 415)      # degrees one round turns the camera (a bit more than all the way round): drawn at random
ROTATE_REVERSE = 0.3          # share of the rounds that turn the other way
ROTATE_LEN = (570, 830)       # px one swipe is long (700 px = ~45 degrees); neighbouring views still overlap
ROTATE_Y = (780, 1020)        # px: height on the screen where the swipe is made
ROTATE_DRIFT = 40             # px: the finger ends up this much higher or lower than it started
ROTATE_SPEED = (0.9, 1.5)     # px per ms: how fast the finger moves (the swipe time follows from it)
ROTATE_PAUSE = (1.6, 2.2)     # s: wait after a swipe before looking again (when 'fast looking' is off) ...
ROTATE_LONG_PAUSE = (0.06, 2.8, 5.0)   # ... and now and then (share) a longer one
# Fast looking: the swipe that turns the camera is started the moment the screenshot has been
# taken (the picture is complete then, only the transfer over USB is still going on), so the
# camera turns while the picture is transferred and searched. The next screenshot follows as soon
# as the camera has come to rest.
ROTATE_LAG = 0.35             # s from starting the swipe until the finger touches the screen
ROTATE_REST = 0.5             # s the camera needs to come to rest after the finger is lifted
SHOT_LAG = 0.25               # s from asking for a screenshot until the picture is taken
ROTATE_JITTER = (0.0, 0.4)    # s of extra, random waiting before the next screenshot
IDLE_RANGE = (6.0, 11.0)      # s: wait after a full round without any Pokémon (IDLE_WAIT on average)

TH_CLASS = 0.5                # minimale zekerheid schermherkenning
TH_POKEMON = 0.4              # minimum certainty for a Pokémon on the map
ZOOM_BOX = (200, 600, 1400, 1700)   # extra detection area around the player
TILE = 650                          # the lower half of the map is also scanned in square tiles
TILE_X = (0, 325, 650, 975)
TILE_Y = (700, 1025, 1250)
TH_TILE = 0.5                       # minimum certainty for a Pokémon found in a tile
MAP_WORKERS = max(min(os.cpu_count() or 2, 4), 1)   # map looks that run at the same time
TH_WEAK = 0.35                      # ... and for the other looks that must confirm it
TH_STOP = 0.3                 # minimum certainty for a PokéStop on the map
TH_RING = 0.35                # minimum certainty for the target ring while catching
TH_CLICK = 0.25               # minimum certainty for a button
TH_PASSENGER = 0.8            # minimale zekerheid "Ik ben passagier"-melding

W, H = S.EXPECTED_SIZE        # 1768 x 2208
BALL_XY = S.ENC_BALL          # ball at the bottom of the catch screen
# ==========================================================================

log = S.log


# ------------------------------- modellen ---------------------------------
# The models run with LiteRT (ai-edge-litert). MediaPipe itself does not work on the Pi 4
# (the CPU lacks AES instructions), so we do the pre- and post-processing here ourselves, in exactly
# the same way as MediaPipe (checked on the same screenshots).
from ai_edge_litert.interpreter import Interpreter

SCREENS = ["areneScreen", "eggScreen", "encounterScreen", "mapScreen", "menusScreen",
           "pokestopScreen", "rewardScreen", "rocketScreen", "summaryScreen"]
MAP_LABELS = ["background", "gym", "pokemon", "pokestop", "rocket_pokestop", "unable_pokestop"]
CLICK_LABELS = ["background", "clickable", "passenger"]
ENC_LABELS = ["pokeball", "dynamicBox", "boundingBox"]


def _nms(boxes, iou_th=0.5):
    """boxes: [(label, score, cx, cy, w, h)] sorted by score -> without overlapping duplicates."""
    keep = []
    for b in boxes:
        ok = True
        for k in keep:
            if k[0] != b[0]:
                continue
            x1, y1 = max(b[2] - b[4] / 2, k[2] - k[4] / 2), max(b[3] - b[5] / 2, k[3] - k[5] / 2)
            x2, y2 = min(b[2] + b[4] / 2, k[2] + k[4] / 2), min(b[3] + b[5] / 2, k[3] + k[5] / 2)
            inter = max(0, x2 - x1) * max(0, y2 - y1)
            union = b[4] * b[5] + k[4] * k[5] - inter
            if union > 0 and inter / union > iou_th:
                ok = False
                break
        if ok:
            keep.append(b)
    return keep


_clf = {"brain": None, "it": None, "failed": False}     # the screen classifier for screen_class()


def screen_class(img):
    """(name, certainty) of the screen classifier alone, for the parts of the bot that run without the whole
    Brain (gamebot.py fight).  The classifier of a Brain that exists is used, otherwise only this one model
    is loaded.  ("onbekend", 0.0) when the model cannot be used."""
    if _clf["brain"] is not None:
        return _clf["brain"].screen(img)
    if _clf["failed"]:
        return "onbekend", 0.0
    try:
        if _clf["it"] is None:
            it = Interpreter(model_path=os.path.join(MODEL_DIR, "model_classifier_screen_v5.tflite"), num_threads=2)
            it.allocate_tensors()
            _clf["it"] = it
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        x = cv2.resize(cv2.resize(rgb, (256, 256)), (224, 224)).astype(np.float32) / 255.0
        p = list(Brain._run(_clf["it"], x).values())[0]
        i = int(np.argmax(p))
        return SCREENS[i], float(p[i])
    except Exception as e:  # noqa: BLE001
        _clf["failed"] = True
        log(f"the screen classifier cannot be used here ({e})")
        return "onbekend", 0.0


class Brain:
    def __init__(self):
        _clf["brain"] = self
        p = lambda f: os.path.join(MODEL_DIR, f)

        def load(f):
            it = Interpreter(model_path=p(f), num_threads=4)
            it.allocate_tensors()
            return it
        self.clf = load("model_classifier_screen_v5.tflite")
        self.map = load("model_detector_map_v2.tflite")
        # extra copies of the map detector, one per CPU core: the many enlarged looks of the
        # thorough map scan then run side by side instead of one after the other
        self.map_pool = queue.Queue()
        for _ in range(MAP_WORKERS):
            it = Interpreter(model_path=p("model_detector_map_v2.tflite"), num_threads=1)
            it.allocate_tensors()
            self.map_pool.put(it)
        self.workers = ThreadPoolExecutor(MAP_WORKERS)
        # the two looks of every map step (the whole screen and the enlarged middle) side by side, each on half
        # of the cores, instead of one after the other on all of them (24 November: 1.2 - 2.2 s a look)
        half = max((os.cpu_count() or 4) // 2, 1)
        self.pair = []
        for _ in range(2):
            it = Interpreter(model_path=p("model_detector_map_v2.tflite"), num_threads=half)
            it.allocate_tensors()
            self.pair.append(it)
        self.pair_pool = ThreadPoolExecutor(2)
        self._seen = None                          # (image, full-frame result, zoom result) of the last quick look
        self.clk = load("model_detector_clickable_v2.tflite")
        self.enc = load("model_detector_encounter.tflite")
        a = np.load(p("anchors.npz"))
        self.map_anchors = a["model_detector_map_v2_anchors"]
        self.clk_anchors = a["model_detector_clickable_v2_anchors"]
        self.pred = dict(np.load(p("predictor_weights.npz")))   # 4 -> 128 -> 64 -> 32 -> 2

    @staticmethod
    def _run(it, x):
        it.set_tensor(it.get_input_details()[0]["index"], x[None].astype(np.float32))
        it.invoke()
        return {d["name"]: it.get_tensor(d["index"])[0] for d in it.get_output_details()}

    def screen(self, img):
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        x = cv2.resize(cv2.resize(rgb, (256, 256)), (224, 224)).astype(np.float32) / 255.0
        p = list(self._run(self.clf, x).values())[0]
        i = int(np.argmax(p))
        return SCREENS[i], float(p[i])

    def _ssd(self, it, anchors, labels, img, th=0.2, top=10):
        """Decode the RetinaNet output (27621 anchors) like MediaPipe: yxhw + exp, no sigmoid."""
        h0, w0 = img.shape[:2]
        rgb = cv2.cvtColor(cv2.resize(img, (384, 384)), cv2.COLOR_BGR2RGB)
        out = self._run(it, (rgb.astype(np.float32) - 127.5) / 127.5)
        boxes = [v for v in out.values() if v.shape[-1] == 4][0]
        scores = [v for v in out.values() if v.shape[-1] != 4][0]
        cls = scores[:, 1:].argmax(1) + 1
        sc = scores[np.arange(len(scores)), cls]
        idx = np.where(sc >= th)[0]
        idx = idx[np.argsort(-sc[idx])][:200]
        ax, ay, aw, ah = anchors[idx].T
        yc, xc, hh, ww = boxes[idx].T
        cx, cy = (xc * aw + ax) * w0, (yc * ah + ay) * h0
        bw, bh = np.exp(ww) * aw * w0, np.exp(hh) * ah * h0
        res = [(labels[cls[i]], float(sc[i]), int(cx[n]), int(cy[n]), int(bw[n]), int(bh[n]))
               for n, i in enumerate(idx)]
        res = [r for r in res if r[4] < 0.6 * w0 and r[5] < 0.6 * h0]   # onzinnig grote vakken weg
        return _nms(res)[:top]

    def map_objects(self, img, tiles=False):
        self.src = {}                              # (x, y) of a Pokémon -> the part of the screen it was seen in
        # extra looks at enlarged parts of the map: small Pokémon (and the dark night map)
        # are often missed when the whole screen is squeezed to 384 px
        def near(a, b):
            return abs(a[2] - b[2]) < 100 and abs(a[3] - b[3]) < 100

        def look(box, alone=False, it=None):
            x0, y0, x1, y1 = box
            pooled = it is None and not alone
            it = it or (self.map if alone else self.map_pool.get())    # alone: the copy that uses all cores
            try:
                found = self._ssd(it, self.map_anchors, MAP_LABELS, img[y0:y1, x0:x1])
            finally:
                if pooled:
                    self.map_pool.put(it)
            return [((o[0], o[1], o[2] + x0, o[3] + y0) + tuple(o[4:]), box)
                    for o in found if o[0] == "pokemon" and o[1] >= TH_WEAK]

        if self._seen is not None and self._seen[0] is img:     # same screenshot: reuse the quick look
            res, zoom = list(self._seen[1]), self._seen[2]
        else:
            whole = self.pair_pool.submit(self._ssd, self.pair[0], self.map_anchors, MAP_LABELS, img)
            zoom = look(ZOOM_BOX, it=self.pair[1])
            res = whole.result()
            self._seen = (img, list(res), zoom)
        # something that could be a Pokémon (weak hit in the whole screen or the zoom look)?
        self.hint = bool(zoom) or any(r[0] == "pokemon" and r[1] >= 0.2 for r in res)
        for o, box in zoom:
            if o[1] >= TH_POKEMON and not any(r[0] == "pokemon" and near(r, o) for r in res):
                res.append(o)
                self.src[(o[2], o[3])] = box
        if tiles:
            # thorough (slower) scan in overlapping square tiles. One tile alone often sees a
            # 'Pokémon' in buildings or weather streaks; a real one is seen in several looks.
            boxes = [(x0, y0, x0 + TILE, y0 + TILE) for y0 in TILE_Y for x0 in TILE_X]
            hits = zoom + [h for part in self.workers.map(look, boxes) for h in part]
            hits.sort(key=lambda h: -h[0][1])
            while hits:
                o, box = hits[0]
                group = [h for h in hits if near(h[0], o)]
                hits = [h for h in hits if not near(h[0], o)]
                if len(group) >= 2 and o[1] >= TH_TILE and \
                        not any(r[0] == "pokemon" and near(r, o) for r in res):
                    res.append(o)
                    self.src[(o[2], o[3])] = box
        return sorted(res, key=lambda t: -t[1])

    def buttons(self, img):
        return self._ssd(self.clk, self.clk_anchors, CLICK_LABELS, img)

    def second_look(self, img, x, y):
        """Second look (new screenshot) at a Pokémon found on the map. Returns its box as it
        is now (score, x, y, w, h) or None when it is gone: effects that only flash by (the
        pulse around the trainer, weather) are gone then, and a camera that was still
        turning has come to rest. self.second_best keeps the best score that was seen near
        the spot (for the log)."""
        full = (0, 0, img.shape[1], img.shape[0])
        x0, y0, x1, y1 = getattr(self, "src", {}).get((x, y), full)
        self.second_best = 0.0
        looks = [((x0, y0, x1, y1), 0.35)] + ([(full, 0.3)] if (x0, y0, x1, y1) != full else [])
        for box, th in looks:
            bx0, by0, bx1, by1 = box
            near = [(o[1], o[2] + bx0, o[3] + by0, o[4], o[5])
                    for o in self._ssd(self.map, self.map_anchors, MAP_LABELS, img[by0:by1, bx0:bx1], th=0.15)
                    if o[0] == "pokemon" and abs(o[2] + bx0 - x) < 150 and abs(o[3] + by0 - y) < 150]
            if near:
                self.second_best = max(self.second_best, max(near)[0])
            good = [n for n in near if n[0] >= th]
            if good:
                return max(good)
        return None

    def encounter_objects(self, img, th=0.2):
        h0, w0 = img.shape[:2]
        rgb = cv2.cvtColor(cv2.resize(img, (640, 640)), cv2.COLOR_BGR2RGB)
        out = self._run(self.enc, (rgb.astype(np.float32) - 127.5) / 127.5)
        boxes = [v for v in out.values() if getattr(v, "ndim", 0) == 2][0]          # [10, 4] ymin,xmin,ymax,xmax
        vecs = [v for v in out.values() if getattr(v, "ndim", 0) == 1 and v.shape[0] == boxes.shape[0]]
        scores, classes = (vecs[0], vecs[1]) if vecs[0].max() <= 1 and np.any(vecs[0] % 1) else (vecs[1], vecs[0])
        res = []
        for (y1, x1, y2, x2), s, c in zip(boxes, scores, classes):
            if s >= th:
                res.append((ENC_LABELS[int(c)], float(s), int((x1 + x2) / 2 * w0), int((y1 + y2) / 2 * h0),
                            int((x2 - x1) * w0), int((y2 - y1) * h0)))
        return sorted(res, key=lambda t: -t[1])

    def throw_params(self, cx, cy, bw, bh):
        """RegiBot predictor: target ring -> (deltaY in px, duration in ms)."""
        w = self.pred
        x = np.array([cx / W, cy / H, bw / W, bh / H], dtype=np.float32)
        for i in (1, 2, 3):
            x = np.maximum(x @ w[f"W{i}"].T + w[f"b{i}"], 0)
        dy, dur = x @ w["W4"].T + w["b4"]
        return float(dy) * H, float(dur) * 1000


# ---------------------- bediening via de webinterface ----------------------
CONTROL_FILE = os.path.expanduser("~/gamebot_control.json")


def setting(key, default):
    try:
        import json
        with open(CONTROL_FILE) as f:
            return json.load(f).get(key, default)
    except (OSError, ValueError):
        return default


S.live_wanted = lambda: bool(setting("live_look", True))   # option 'Look with the live video'


def wanted(key):
    """Is catching/spinning switched on in the web interface? (on by default)"""
    try:
        import json
        with open(CONTROL_FILE) as f:
            return bool(json.load(f).get(key, True))
    except (OSError, ValueError):
        return True


# ------------------------------- toestand ---------------------------------
cooldown = []          # [(x, y, verloopt_op)]
enc = {"start": 0.0, "throws": 0, "berry": False, "ball_set": False, "caught": False,
       "t_throw": 0.0, "t_result": 0.0, "t_tap": 0.0}    # clock times of the last ball, the result screen and the tap on OK
handoff = {"img": None, "t": 0.0}   # a screenshot that was already taken (and looked at) while waiting for the catch result: the next step() reuses it
throw_info = {"hit": None}          # did the last ball clearly come down on the Pokémon? (None: not known)
enc_xy = {"xy": None}               # where on the map the Pokémon of this encounter was tapped
# Fast catch (option, off by default): after a clear hit press BACK - the catch animation is skipped and
# the game is back on the map in a moment. Whether the Pokémon was caught is checked on the map: when it
# is gone from where it was, it counts as caught (a Pokémon that fled looks the same).
fast_pending = {"xy": None, "t": 0.0, "t_throw": 0.0, "t_back": 0.0, "looks": 0}
fast_state = {"fails": 0, "off_until": 0.0}
FAST_BACK_AFTER = 1.2         # s after the release: the ball has reached the Pokémon by then
FAST_BACK_LATEST = 5.0        # s after the release: later than that the animation may be over, press nothing
FAST_LOOK_AFTER = 1.0         # s after BACK until the screenshot that shows where we are
FAST_PENDING_MAX = 90.0       # s: how long a fast catch can wait for the check on the map
FAST_RADIUS = 200             # px: the Pokémon counts as still there when one is found this close to its old spot
FAST_SCORE = 0.3              # ... with at least this certainty (and not a PokéStop or gym)
FAST_MAX_FAILS = 2            # in a row: then the option rests (it does not seem to work on this game version)
FAST_REST = 30 * 60           # s
stats = {"day": None, "caught": 0, "fled": 0, "stops": 0, "won": 0, "lost": 0}


def _stats_of_today():
    """The counters of today from the log (the last '(today: ...)' line of today): a restart does not set
    them back to nothing."""
    today = time.strftime("%Y-%m-%d")
    try:
        with open(S.LOGFILE, "rb") as f:
            f.seek(0, 2)
            f.seek(max(f.tell() - 400000, 0))
            lines = f.read().decode(errors="ignore").splitlines()
    except OSError:
        return
    for line in reversed(lines):
        if not line.startswith(today):
            if line[:4].isdigit():
                return                         # (an older day: nothing of today yet)
            continue
        m = re.search(r"\(today: ([^)]*)\)", line)
        if m:
            stats["day"] = today
            for n, what in re.findall(r"(\d+) (\w+)", m.group(1)):
                if what in stats:
                    stats[what] = int(n)
            return


def count(key):
    today = time.strftime("%Y-%m-%d")
    if stats["day"] is None:
        _stats_of_today()
    if stats["day"] != today:
        stats.update(day=today, caught=0, fled=0, stops=0, won=0, lost=0)
    stats[key] += 1
    try:
        extras.history_record(today, stats)
    except Exception:  # noqa: BLE001
        pass
    return (f"(today: {stats['caught']} caught, {stats['fled']} fled, {stats['stops']} stops"
            + (f", {stats['won']} won, {stats['lost']} lost" if stats["won"] or stats["lost"] else "") + ")")


day_count = count             # (under another name, where 'count' means something else: battle_run)


def mark_caught():
    if enc["throws"] > 0 and not enc["caught"]:
        enc["caught"] = True
        enc["t_result"] = time.time()
        log(f"Pokémon CAUGHT ✔ after {enc['throws']} ball(s) {count('caught')}")
same_screen = {"name": None, "count": 0}
last_tap = {"kind": None, "xy": None, "alt": None, "near": False}
NEAR_BLOCK = 20 * 60          # s: after a tap on a "Pokémon" next to the trainer did nothing (the buddy?), leave that area alone
near_state = {"until": 0.0}
TAP_UP = 0.22                 # tap this share of the box height above the middle of a Pokémon
rotation = {"steps": 0, "turned": 0.0, "goal": 0.0, "dir": 1,        # steps done in this round, px turned so far, px this round turns, direction (1 / -1)
            "armed": None, "armed_at": 0.0, "fired": None}            # fast looking: the next swipe, and the one just started


def rotate_swipe(direction):
    """One camera rotation step: a horizontal swipe of random length, height, tilt and speed.
    Returns the swipe as (x1, y1, x2, y2, ms) and the s to wait for the camera to come to rest."""
    length = random.uniform(*ROTATE_LEN)
    x0 = random.uniform(0.18, 0.26) * W
    y0 = random.uniform(*ROTATE_Y)
    y1 = min(max(y0 + random.uniform(-ROTATE_DRIFT, ROTATE_DRIFT), 700), 1100)
    ms = length / random.uniform(*ROTATE_SPEED)
    if direction < 0:                                  # the other way round: from the right side
        x0 = W - x0
        length = -length
    share, lo, hi = ROTATE_LONG_PAUSE
    pause = random.uniform(lo, hi) if random.random() < share else random.uniform(*ROTATE_PAUSE)
    return (int(x0), int(y0), int(x0 + length), int(y1), int(ms)), pause


def fire_rotation():
    """Called by S.screenshot the moment the picture has been taken: start the armed swipe."""
    armed, rotation["armed"] = rotation["armed"], None
    if not armed or time.time() - rotation["armed_at"] > 20:
        return
    rotation["fired"] = {"t": time.time(), "swipe": armed[0]}
    S.swipe_async(*armed[0])


def settle_left(fired):
    """s until the camera has come to rest after a swipe that was started (and a screenshot
    that is asked for then, is taken after SHOT_LAG)."""
    ms = fired["swipe"][4]
    return max(fired["t"] + ROTATE_LAG + ms / 1000 + ROTATE_REST - SHOT_LAG - time.time(), 0.0)


def undo_rotation(fired):
    """The camera was turned on right after the picture was taken (fast looking), and now a
    Pokémon or stop in that picture is wanted: it is not where it was in the picture. Turn the
    camera back and look again. Returns True when that was done."""
    rotation.update(fired=None, armed=None)
    if not fired:
        return False
    x1, y1, x2, y2, ms = fired["swipe"]
    time.sleep(max(fired["t"] + ROTATE_LAG + ms / 1000 + 0.1 - time.time(), 0.0))   # let that swipe end first
    log("camera had already started turning - turning back to look again")
    S.swipe(x2, y2, x1, y1, ms)
    time.sleep(ROTATE_REST)
    rotation["steps"] = 0
    return True


def cooled(x, y):
    now = time.time()
    cooldown[:] = [c for c in cooldown if c[2] > now]
    return any(abs(x - cx) < 150 and abs(y - cy) < 150 for cx, cy, _ in cooldown)


def reset_encounter():
    if enc["throws"] > 0 and not enc["caught"]:
        log(f"Pokémon fled or gone after {enc['throws']} ball(s) {count('fled')}")
    enc.update(start=0.0, throws=0, berry=False, ball_set=False, caught=False,
               t_throw=0.0, t_result=0.0, t_tap=0.0)
    enc_xy["xy"] = None
    throw_info["hit"] = None


# ------------------------------- schermen ---------------------------------
def looks_spun(img, o):
    """Is this stop purple (already spun)? The model is sometimes unsure about that; the colour is not."""
    _, _, x, y, bw, bh = o
    box = img[max(y - bh // 2, 0):y + bh // 2, max(x - bw // 2, 0):x + bw // 2]
    if box.size == 0:
        return False
    hsv = cv2.cvtColor(box, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    blue = ((hsv[:, 0] >= 92) & (hsv[:, 0] <= 108) & (hsv[:, 1] > 165)).sum()
    purple = ((hsv[:, 0] >= 128) & (hsv[:, 0] <= 150) & (hsv[:, 1] > 70) & (hsv[:, 2] > 120)).sum()
    return purple > blue


def fast_catch_on():
    """Option 'Fast catch' ticked, and not resting after it failed twice in a row?"""
    return bool(setting("fast_catch", False)) and time.time() >= fast_state["off_until"]


def fast_catch_leave(brain, t_throw):
    """The last ball came down on the Pokémon: press BACK so the catch animation is skipped.
    Returns the s to wait when the game is back on the map (or a question over the map was
    answered), None when the normal way of waiting for the result has to carry on."""
    xy = enc_xy["xy"]
    since = time.time() - t_throw
    if xy is None:
        return None                                     # not known where the Pokémon is on the map: could not check it afterwards
    if since > FAST_BACK_LATEST:
        log(f"fast catch: {since:.1f} s after the release - too late to leave, waiting for the result")
        return None
    if since < FAST_BACK_AFTER:
        time.sleep(FAST_BACK_AFTER - since)
    t_back = time.time()
    log(f"fast catch: clear hit - pressing BACK ({t_back - t_throw:.1f} s after the release)")
    S.back()
    time.sleep(FAST_LOOK_AFTER)
    img = S.quick_screenshot()
    if not S.on_map(img):
        lines = ocr_lines(img, 100, 2150)
        kind = _screen_kind(img, lines)
        if kind == "exit":                              # the game was already on the map: BACK asks 'exit?'
            log("fast catch: the game asks whether to exit - answering CANCEL")
            _cancel_exit(lines)
            img = None
        else:
            log(f"fast catch: after BACK the screen is '{kind}', not the map - waiting for the result the normal way "
                f"(read: {_reads(lines, 80) or 'nothing'}; debug/g_fast_back.png)")
            save_async("g_fast_back.png", img)
            return None
    enc["caught"] = True                                # (so the map does not count it as 'fled'; the check there decides)
    fast_pending.update(xy=xy, t=time.time(), t_throw=t_throw, t_back=t_back, looks=0)
    if img is not None:
        handoff.update(img=img, t=time.time())          # the map as it is now: the next step uses it
        return 0.0
    return 1.5


def fast_check(objs):
    """Back on the map after a fast catch: is the Pokémon still where it was?
    Returns True / False, or None when no fast catch is waiting for a check."""
    fp = fast_pending
    if fp["xy"] is None:
        return None
    if time.time() - fp["t"] > FAST_PENDING_MAX:
        log("fast catch: could not check the result in time - not counted")
        fp["xy"] = None
        return None
    x0, y0 = fp["xy"]
    stops = [o for o in objs if o[0] in ("pokestop", "unable_pokestop", "rocket_pokestop", "gym")]

    def on_stop(o):                                     # "Pokémon" that is really (part of) a stop or gym
        return any(abs(o[2] - b[2]) < b[4] / 2 and abs(o[3] - b[3]) < b[5] / 2 for b in stops)

    return any(o[0] == "pokemon" and o[1] >= FAST_SCORE and not on_stop(o)
               and abs(o[2] - x0) < FAST_RADIUS and abs(o[3] - y0) < FAST_RADIUS for o in objs)


def fast_verdict(objs):
    """Called from do_map with the objects of the first look. Returns the s to wait when the
    Pokémon is still on the map (look once more first), None to carry on with the map."""
    there = fast_check(objs)
    if there is None:
        return None
    fp = fast_pending
    now = time.time()
    if not there:
        log(f"Pokémon CAUGHT ✔ (fast catch: gone from the map after BACK) {count('caught')}")
        log(f"fast catch timeline: release -> BACK {fp['t_back'] - fp['t_throw']:.1f} s, "
            f"-> map checked {now - fp['t_back']:.1f} s ({now - fp['t_throw']:.1f} s in total)")
        fast_state["fails"] = 0
        fp["xy"] = None
        return None
    fp["looks"] += 1
    if fp["looks"] < 2:                                 # the map may need a moment to drop it: look once more
        log("fast catch: the Pokémon is still on the map - looking once more")
        return 1.5
    x0, y0 = fp["xy"]
    cooldown[:] = [c for c in cooldown if not (abs(c[0] - x0) < 150 and abs(c[1] - y0) < 150)]
    fast_state["fails"] += 1
    log(f"fast catch: the Pokémon is still on the map after BACK - not caught, trying it again "
        f"({fast_state['fails']} of {FAST_MAX_FAILS} in a row)")
    if fast_state["fails"] >= FAST_MAX_FAILS:
        fast_state.update(fails=0, off_until=now + FAST_REST)
        log(f"fast catch does not seem to work here - catching the normal way for {FAST_REST // 60} min")
    fp["xy"] = None
    return None


perf = {"looks": 0, "shot": 0.0, "detect": 0.0, "total": 0.0, "wait": 0.0}
GONE_COOLDOWN = 45             # s: a spot where the second look saw nothing is not looked at again right away


def do_map(brain, img):
    if enc["caught"] and enc["t_throw"] and enc["t_result"]:     # how long did the catch take, start to finish?
        now = time.time()
        log(f"catch timeline: last ball -> result screen seen {enc['t_result'] - enc['t_throw']:.1f} s, "
            f"-> back on the map {now - enc['t_result']:.1f} s ({now - enc['t_throw']:.1f} s in total)")
    reset_encounter()
    fired, rotation["fired"] = rotation["fired"], None   # fast looking: a swipe was started right after this picture was taken
    gifts_due = (gift_timer["last"] == 0.0 if wanted("daily_cycle")      # daily run: once per app
                 else time.time() - gift_timer["last"] > GIFT_INTERVAL)
    if (wanted("gifts_open") or wanted("gifts_send")) and gifts_due:
        gift_timer["last"] = time.time()
        gifts_round()
        return 3
    # the trainer itself (head and body) is never tapped. A Pokémon at the trainer's feet is: it
    # is a real wild one when the tap opens a catch screen; when it does not (your buddy walks
    # there too) that area is left alone for a while.
    px, py = S.PLAYER
    buddy_walks = bool(setting("buddy", False))        # option 'My buddy walks along' (off: everything next to the trainer is wild)

    def on_trainer(o):
        return abs(o[2] - px) < 110 and -300 < o[3] - py < 40

    def beside_trainer(o):
        return abs(o[2] - px) < 200 and -300 < o[3] - py < 260

    def scan(tiles):
        objs = [o for o in brain.map_objects(img, tiles=tiles)
                if not (on_trainer(o) if o[0] == "pokemon" else (abs(o[2] - px) < 130 and -280 < o[3] - py < 160))]
        stop_boxes = [o for o in objs if o[0] in ("pokestop", "unable_pokestop", "rocket_pokestop", "gym")]

        def on_stop(o):   # "Pokémon" that is really (part of) a stop or gym
            return any(abs(o[2] - b[2]) < b[4] / 2 and abs(o[3] - b[3]) < b[5] / 2 for b in stop_boxes)

        return objs, [o for o in objs if o[0] == "pokemon" and o[1] >= TH_POKEMON
                      and o[3] < 1820 and o[2] < 1400          # not the buttons on the right / at the bottom
                      and not on_stop(o) and not cooled(o[2], o[3])
                      and not (buddy_walks and beside_trainer(o) and time.time() < near_state["until"])]

    t_det = time.time()
    objs, pokemon = scan(False)
    looking = CATCH and wanted("catch") and not (                 # not when only spinning stops
        storage_state["full"] and (wanted("daily_cycle") or wanted("spin_only_when_full")))
    if not pokemon and looking:
        # nothing found: look again, more thoroughly (12 enlarged looks, about 2 s on the Pi).
        # Every other camera position is enough: neighbouring views overlap, and a weak hit
        # (something that might be a Pokémon) is always worth the thorough look.
        if brain.hint or rotation["steps"] % 2 == 0:
            objs, pokemon = scan(True)
    perf["detect"] += time.time() - t_det
    perf["looks"] += 1
    wait_more = fast_verdict(objs)                      # a fast catch waiting for its check on the map
    if wait_more is not None:
        return wait_more
    rockets = [o for o in objs if o[0] == "rocket_pokestop" and o[1] >= 0.4]

    def rocket_near(o):
        return any(abs(o[2] - r[2]) < 250 and abs(o[3] - r[3]) < 350 for r in rockets)

    stops = [o for o in objs if o[0] == "pokestop" and o[1] >= TH_STOP and not rocket_near(o)
             and not cooled(o[2], o[3]) and not looks_spun(img, o)]

    full = box_full_ball(img)
    if full != storage_state["full"]:
        storage_state["full"] = full
        log("POKÉMON STORAGE FULL (gold ball)" + (" - only spinning PokéStops until there is room again"
                                                if wanted("spin_only_when_full") else "")
            if full else "Pokémon storage has room again - catching re-enabled")
    daily = wanted("daily_cycle")
    if full and (daily or wanted("close_when_full")) and time.time() - menu_check["last"] > MENU_CHECK_INTERVAL:
        menu_check["last"] = time.time()
        check_menu_full()                          # is the bag full as well?
        check_all_full()
        return 2
    catch_on = CATCH and wanted("catch") and not (full and (daily or wanted("spin_only_when_full")))
    spin_on = SPIN and wanted("spin")
    if ((catch_on and pokemon) or (spin_on and stops)) and undo_rotation(fired):
        return 0.3
    if catch_on and pokemon:
        rotation["steps"] = 0                          # found: stop turning
        _, sc, x, y, *_ = pokemon[0]
        t_2 = time.time()
        img2 = S.quick_screenshot()
        perf["shot"] += time.time() - t_2
        seen = brain.second_look(img2, x, y)
        if not seen:
            best = getattr(brain, "second_best", 0.0)
            log(f"Pokémon on map ({x}, {y}) [{sc:.2f}] gone at second look "
                f"({'best score there now ' + format(best, '.2f') if best else 'nothing there now'}) - looking again")
            cooldown.append((x, y, time.time() + GONE_COOLDOWN))   # not the same spot again and again
            dbg = img.copy()                           # both looks, to see afterwards what it was
            cv2.circle(dbg, (x, y), 90, (0, 0, 255), 6)
            save_async("g_look1.png", dbg)
            save_async("g_look2.png", img2)
            return 1
        _, x, y, bw, bh = seen                         # where it is right now
        near = beside_trainer((0, 0, x, y))
        if near:                                       # next to the trainer: tap the side of it that is away from him
            tx, ty = x + (-1 if x < px else 1) * int(0.12 * bw), y + int(0.05 * bh)
        else:
            tx, ty = x, y - int(TAP_UP * bh)           # a hovering Pokémon floats above its ground
        log(f"Pokémon on map ({x}, {y}) [{sc:.2f}]{' next to the trainer' if near else ''} - tapping")
        dbg = img2.copy()
        cv2.circle(dbg, (tx, ty), 60, (0, 0, 255), 8)
        save_async("g_pokemon_kaart.png", dbg)
        S.tap(tx, ty)
        cooldown.append((x, y, time.time() + 60))     # not the same spot again right away
        last_tap.update(kind="pokemon", xy=(x, y), near=near,
                        alt=[(x, y), (x, y + int(0.3 * bh))])
        return 3
    if spin_on and stops:
        rotation["steps"] = 0
        _, sc, x, y, *_ = stops[0]
        log(f"PokéStop on map ({x}, {y}) [{sc:.2f}] - opening")
        last_tap.update(kind="stop", xy=(x, y))
        S.tap(x, y)
        cooldown.append((x, y, time.time() + 60))
        return AFTER_STOP_TAP

    # nothing to do in view: turn the camera a little and look again
    if catch_on and ROTATE and rotation["steps"] == 0:         # a new round: how far round, which way
        rotation.update(turned=0.0, goal=random.uniform(*ROTATE_TURN) * 700 / 45,
                        dir=-1 if random.random() < ROTATE_REVERSE else 1, armed=None)
        fired = None
    if catch_on and ROTATE and (fired or rotation["turned"] < rotation["goal"]):
        rotation["steps"] += 1
        if rotation["steps"] == 1:
            n = max(perf["looks"], 1)                  # how long did the looks since the last round take?
            rest = max(perf["total"] - perf["shot"] - perf["detect"], 0.0)
            log(f"no Pokémon in view - rotating camera (round of {rotation['goal'] * 45 / 700:.0f} degrees, "
                f"{'right to left' if rotation['dir'] < 0 else 'left to right'})" + (
                f" (last {perf['looks']} looks: {perf['total'] / n + perf['wait'] / n:.1f} s each = "
                f"screenshot {perf['shot'] / n:.1f} s + detection {perf['detect'] / n:.1f} s + "
                f"other {rest / n:.1f} s + camera wait {perf['wait'] / n:.1f} s)" if perf["looks"] >= 3 else ""))
            perf.update(looks=0, shot=0.0, detect=0.0, wait=0.0,
                        total=-(time.time() - perf.get("t_step", time.time())))
            save_async("g_map_none.png", img)          # what the bot saw when it found nothing
        fast = bool(setting("fast_look", True))
        if fired is None:                              # first look of a round (or fast looking is off): turn now
            swipe, pause = rotate_swipe(rotation["dir"])
            if not fast:                               # the old way: turn, wait, look
                rotation["turned"] += abs(swipe[2] - swipe[0])
                S.swipe(*swipe)
                perf["wait"] += pause
                return pause
            fired = {"t": time.time(), "swipe": swipe}
            S.swipe_async(*swipe)
        rotation["turned"] += abs(fired["swipe"][2] - fired["swipe"][0])
        if rotation["turned"] < rotation["goal"]:      # more to come: it starts when the next picture has been taken
            rotation.update(armed=(rotate_swipe(rotation["dir"])[0], 0), armed_at=time.time())
        # cooldowns stay: whatever is always at the same screen position (such as something near the
        # player) is not tapped again and again; real Pokémon move along with the camera.
        wait = settle_left(fired) + random.uniform(*ROTATE_JITTER)
        if random.random() < ROTATE_LONG_PAUSE[0]:     # now and then a longer look away
            wait += random.uniform(*ROTATE_LONG_PAUSE[1:])
        perf["wait"] += wait
        return wait                                    # the camera has to come to rest first
    rotation["steps"] = 0                              # rondje klaar: even wachten
    return random.uniform(*IDLE_RANGE)


STOP_LOAD = 0.5                # s: let the stop screen finish loading (the screenshot that showed it was taken a while ago)
SPIN_FIRST_LOOK = 0.8          # s after the swipe until the first look at the ring ...
SPIN_POLL_UNTIL = 4.5          # ... then looking again straight away until this many s after the swipe
STOP_CLOSE_DELAY = 0.4         # s between 'ring is purple' and closing the stop
AFTER_STOP_TAP = 2.0           # s between tapping a stop on the map and the next look (the stop screen opens in ~1 s)


def do_pokestop(brain, img):
    if S.ring_spun(img):                               # already spun (purple): just close it
        log("stop already spun - closing")
        S.back()
        return 1.5
    time.sleep(STOP_LOAD)                              # let the stop load
    for attempt in range(1, 5):
        t_swipe = time.time()
        S.swipe(S.SPIN_X1, S.SPIN_Y, S.SPIN_X2, S.SPIN_Y, 180)
        time.sleep(SPIN_FIRST_LOOK)
        while True:                                    # no fixed wait: look until the ring turns purple
            img = S.screenshot()
            if S.ring_spun(img):
                log(f"stop spun ✔ {count('stops')} - spin took {time.time() - t_swipe:.1f} s")
                time.sleep(STOP_CLOSE_DELAY)
                S.back()
                return 1.5
            if S.bag_full(img):
                S.back()
                if setting("bag_clean", True) and bag_state.get("cleaned", 0) + BAG_CLEAN_EVERY < time.time():
                    bag_state["cleaned"] = time.time()
                    time.sleep(2.0)
                    try:
                        gone = clean_bag()
                    except Exception as e:  # noqa: BLE001
                        log(f"bag clean-up: error {e}")
                        _bag_to_map()
                        gone = 0
                    if gone:
                        return 2
                log(f"BAG FULL - clean up your bag; skipping stops for {S.BAG_FULL_WAIT // 60} min")
                global SPIN
                SPIN = False
                bag_state["full"] = True
                _resume_spin_later()
                check_all_full()
                return 3
            if time.time() - t_swipe > SPIN_POLL_UNTIL:
                break
    log("spin failed (too far away?) - closing stop")
    S.back()
    return 5


def _resume_spin_later():
    import threading

    def resume():
        global SPIN
        SPIN = True
        bag_state["full"] = False
        log("spinning stops re-enabled")
    threading.Timer(S.BAG_FULL_WAIT, resume).start()


# ------------------------------- berries ----------------------------------
TRAY_COLS = [326, 880, 1432]                   # centre of the 3 columns in the berry tray
TRAY_ICON_Y = [1220, 1740]                     # height of the berry icons per row
TRAY_LABEL_Y = [(1420, 1540), (1950, 2140)]    # height of the names per row
BERRY_RULES = {                                # name -> (must contain, must not contain)
    "pinap": ("PINAP", "SILVER"),
    "razz": ("RAZZ", "GOLD"),
    "nanab": ("NANAB", None),
}


OCR = {"env": None}                            # environment for tesseract (None: as it is), see ocr_probe()


def ocr_probe():
    """How does tesseract read fastest on this computer?  It can use all processor cores for one picture, but
    on a small computer that often costs more than it brings, and the cores are needed by the rest of the bot
    (the live video of a battle, the map detector).  One picture with text is read both ways; the faster way is
    used from then on (one core wins a tie).  Returns a line for the log."""
    img = np.full((520, 900), 255, np.uint8)
    for i, text in enumerate(("GREAT LEAGUE BATTLE", "USE THIS PARTY 1489", "Attack incoming!", "POKEMON ITEMS SHOP",
                              "Noctowl CP 1497 Lanturn", "NEXT BATTLE GOOD EFFORT")):
        cv2.putText(img, text, (30, 70 + i * 80), cv2.FONT_HERSHEY_SIMPLEX, 1.6 if i % 2 else 1.1, 0, 3, cv2.LINE_AA)
    buf = cv2.imencode(".png", img)[1].tobytes()
    one = dict(os.environ, OMP_THREAD_LIMIT="1")

    def once(env):
        t0 = time.time()
        subprocess.run(["tesseract", "stdin", "stdout", "--psm", "11", "tsv"], input=buf, capture_output=True,
                       timeout=60, env=env)
        return time.time() - t0

    try:
        once(None)                                 # (the first run also loads the program from disk)
        t_all = min(once(None) for _ in range(2))
        t_one = min(once(one) for _ in range(2))
    except Exception as e:  # noqa: BLE001
        return f"text reading speed not measured ({e})"
    OCR["env"] = one if t_one <= 1.1 * t_all else None
    return (f"text reading: {t_all:.2f} s with all processor cores, {t_one:.2f} s with one - using "
            + ("one" if OCR["env"] else "all"))


def ocr_text(img, y0, y1):
    """All text in a horizontal strip of the screen (upper case)."""
    gray = cv2.cvtColor(img[y0:y1], cv2.COLOR_BGR2GRAY)
    ok, buf = cv2.imencode(".png", gray)
    try:
        out = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "6"], env=OCR["env"],
                             input=buf.tobytes(), capture_output=True, timeout=30).stdout.decode()
    except FileNotFoundError:
        return ""
    return " ".join(out.upper().split())


def storage_full(img):
    """Melding 'Your Pokémon storage is full.'"""
    t = ocr_text(img, 450, 700)
    return "STORAGE" in t and "FULL" in t


storage_state = {"full": False}
bag_state = {"full": False}


menu_check = {"last": 0.0}
MENU_CHECK_INTERVAL = 10 * 60   # storage full: check the bag in the main menu this often
MENU_BTN = (884, 1985)          # Poké Ball button on the map -> main menu


def check_menu_full():
    """Open the main menu and read the red FULL labels: under POKÉMON (left) = storage full,
    under ITEMS (right) = bag full."""
    S.tap(*MENU_BTN)
    time.sleep(2.5)
    img = S.screenshot()
    lines = ocr_lines(img, 1300, 2100)
    words = [(w, wx) for _, _, _, ws in lines for w, wx, wy in ws]
    if any(w.startswith("ITEMS") for w, _ in words) or any(w.startswith("POK") for w, _ in words):
        fulls = [wx for w, wx in words if "FULL" in w]
        storage_state["full"] = any(wx < 884 for wx in fulls) or storage_state["full"]
        bag_state["full"] = any(wx >= 884 for wx in fulls)
        log(f"menu check: Pokémon storage {'FULL' if storage_state['full'] else 'ok'}, "
            f"bag {'FULL' if bag_state['full'] else 'ok'}")
        S.tap(*MENU_BTN)                           # X button closes the menu (BACK on the map
        time.sleep(2)                              # would ask "exit Pokémon GO?")
    else:
        save_async("g_menu.png", img)
        log("menu check: main menu not recognised")


# ----------------------------- daily incense ------------------------------
# Option 'Use the daily incense': once a day per Pokémon GO app (each app is its own account)
# the item bag is opened, the 'Daily Adventure Incense' is looked up (OCR on its name, scrolling
# through the bag) and used. Nothing else in the bag is ever tapped.
# NOTE: the daily-incense routine below is not called any more (option removed from the web interface): the game
# does not accept injected touches (adb / scrcpy) on the incense card, only a real finger.
INCENSE_FILE = os.path.expanduser("~/gamebot_incense.json")
INCENSE_TRIES = 2              # visits to the bag per app per day when something went wrong
INCENSE_RETRY = 15 * 60        # s between two visits
BAG_SCROLLS = 45               # how many pages down the bag is searched (it is a long list)
INCENSE_VERSION = 10            # visits recorded by an older version of this routine do not count


def incense_state():
    try:
        with open(INCENSE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_incense_state(st):
    with open(INCENSE_FILE, "w") as f:
        json.dump(st, f)


def incense_due():
    """Option on, and this app has not had its incense yet today (or a visit went wrong a while ago)."""
    if not setting("daily_incense", False):
        return False
    rec = incense_state().get(S.PACKAGE, {})
    if rec.get("date") != time.strftime("%Y-%m-%d") or rec.get("v") != INCENSE_VERSION:
        return True
    return (not rec.get("done") and rec.get("tries", 0) < INCENSE_TRIES
            and time.time() - rec.get("last", 0) > INCENSE_RETRY)


def _like(word, target, th=0.8):
    return difflib.SequenceMatcher(None, word, target).ratio() >= th


def incense_tile(lines):
    """Middle of the words 'DAILY ADVENTURE' (also when OCR misreads a letter or the name wraps
    over two lines) in the OCR lines of a screen, or None. 'Incense' alone is not enough:
    ordinary incense, Lucky Eggs etc. must never be tapped."""
    words = [(w, x, y) for _, _, _, ws in lines for w, x, y in ws]
    daily = [(x, y) for w, x, y in words if _like(w, "DAILY")]
    adventure = [(x, y) for w, x, y in words if _like(w, "ADVENTURE")]
    for dx, dy in daily:
        for ax, ay in adventure:
            if abs(ax - dx) < 450 and abs(ay - dy) < 130:
                return (dx + ax) // 2, (dy + ay) // 2
    return None


def incense_use_button(img, lines):
    """A button that uses the incense on its card: the word USE / ACTIVATE in the lower half (OCR).
    (The real card has no button: see incense_gesture().)"""
    cands = [(wx, wy) for _, _, _, ws in lines for w, wx, wy in ws
             if w in ("USE", "ACTIVATE", "START") and wy > 1100 and abs(wx - 884) < 400]
    return max(cands, key=lambda c: c[1]) if cands else None


def incense_card(lines):
    """The card of the daily incense (title, or its text 'Special Incense with a mysterious fragrance ...')."""
    ws = [w for w, _, _ in _words(lines)]
    return bool(incense_tile(lines)) or any(_like(w, "FRAGRANCE", 0.8) or _like(w, "MYSTERIOUS", 0.8) for w in ws)


def find_button(img):
    """The little yellow dot on the button of the 3D incense (x, y), or None. The dot sits inside the round
    button on the right of the incense; it is looked up in the whole area under the text panel because the
    incense sometimes hops up, partly behind that panel."""
    h, w = img.shape[:2]
    s = w / 1768.0
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    y0, y1, x0, x1 = int(h * 0.30), int(h * 0.85), int(w * 0.10), int(w * 0.90)
    reg = hsv[y0:y1, x0:x1]
    mask = ((reg[..., 0] >= 18) & (reg[..., 0] <= 38) & (reg[..., 1] > 110) & (reg[..., 2] > 170)).astype(np.uint8)
    n, _, stats, cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
    best = None
    for i in range(1, n):
        bw, bh, area = int(stats[i][2]), int(stats[i][3]), int(stats[i][4])
        if area < 8 * s * s or area > 900 * s * s or bw > 45 * s or bh > 45 * s:
            continue
        if best is None or area > best[0]:
            best = (area, int(cent[i][0]) + x0, int(cent[i][1]) + y0)
    return (best[1], best[2]) if best else None


# Size of the incense in a 1768-px wide screenshot, and where its parts lie relative to the yellow dot of
# its button (measured on real screenshots): body middle, blue top and button middle.
INC_BODY_FROM_DOT = (-185, 58)      # the middle of the white body
INC_BUTTON_FROM_DOT = (-18, 20)     # the middle of the round button (the dot sits in its upper right)


def find_incense(img):
    """The 3D incense on its card: {cx, cy (middle of its body), x, y, w, h, button (the yellow dot of its
    little button, or None)}; None when it cannot be found. It floats, sways and sometimes hops up, so it is
    looked up in a fresh screenshot before every gesture. The yellow dot gives the most reliable position."""
    h, w = img.shape[:2]
    s = w / 1768.0
    btn = find_button(img)
    if btn:
        cx, cy = int(btn[0] + INC_BODY_FROM_DOT[0] * s), int(btn[1] + INC_BODY_FROM_DOT[1] * s)
        bw, bh = int(510 * s), int(310 * s)
        return {"cx": cx, "cy": cy, "x": cx - bw // 2, "y": cy - bh // 2, "w": bw, "h": bh, "button": btn}
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    y0, y1, x0, x1 = int(h * 0.36), int(h * 0.82), int(w * 0.18), int(w * 0.82)    # below the text panel
    reg = hsv[y0:y1, x0:x1]
    mask = ((reg[..., 2] > 185) & (reg[..., 1] < 75)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(c) < 15000:
        return None
    bx, by, bw, bh = cv2.boundingRect(c)
    m = cv2.moments(c)
    cx, cy = int(m["m10"] / m["m00"]) + x0, int(m["m01"] / m["m00"]) + y0
    return {"cx": cx, "cy": cy, "x": bx + x0, "y": by + y0, "w": bw, "h": bh, "button": None}


def steady_incense(inc, dots, s=1.0):
    """The incense sways by up to ~50 px between two pictures, and a screenshot is ~1 s old when the finger
    lands. So the aim is the dot of the fresh picture pulled halfway to the median of the last pictures
    (ignored when the incense is somewhere else, e.g. hopping)."""
    if not inc or not inc.get("button"):
        return inc
    bx, by = inc["button"]
    if len(dots) >= 3:
        mx, my = float(np.median([d[0] for d in dots])), float(np.median([d[1] for d in dots]))
        if abs(bx - mx) < 90 * s and abs(by - my) < 90 * s:
            bx, by = int((bx + mx) / 2), int((by + my) / 2)
    inc = dict(inc, button=(bx, by))
    inc["cx"], inc["cy"] = int(bx + INC_BODY_FROM_DOT[0] * s), int(by + INC_BODY_FROM_DOT[1] * s)
    return inc


# The real card has no USE button and a TAP does nothing (22 tries with every press length from 20 ms to 2 s,
# on the body and on the button, 4 ways of sending a touch: none worked). What works - seen in a screen
# recording of a hand-made activation - is to THROW the incense UP with a quick swipe starting on it: the
# card closes and the incense flies into the sky ("swipe on the Daily Adventure Incense to use it"). Like a
# Poké Ball, a throw needs speed, so the gestures differ in speed, length and way of sending. The list is
# FIXED (the number of a gesture never depends on one picture) and is gone through twice, because the
# incense hops and sways and a gesture may start beside it; every gesture is aimed at a fresh screenshot.
# After each one a picture is kept (debug/g_incense_a1.png ...) and one of where it was aimed
# (debug/g_incense_t1.jpg ...).
_THROWS = [
    ("a throw up like a Poké Ball (finger down, 2 moves, up, ~1000 px)", "touch", "ball", 0),
    ("a fast swipe up (600 px in 100 ms)", "swipe", "up_fast", 100),
    ("a swipe up (800 px in 150 ms)", "swipe", "up_mid", 150),
    ("a very fast swipe up (500 px in 60 ms)", "swipe", "up_vfast", 60),
    ("grab the incense for a moment, then throw it up", "touch", "grab", 0),
    ("a fast swipe up starting low on the incense", "swipe", "up_low", 120),
    ("a long throw up like a Poké Ball (~1400 px)", "touch", "ball_far", 0),
    ("a swipe up (700 px in 250 ms)", "swipe", "up_slow", 250),
    ("a slow drag up (600 px in 500 ms)", "swipe", "up_drag", 500),
    ("a fast swipe up, a bit to the right", "swipe", "up_right", 100),
]
INCENSE_GESTURES = _THROWS + _THROWS + [
    ("a tap on its little button", "tap", "button", 120),
    ("a tap on the middle of the incense", "tap", "middle", 120),
]


def incense_gesture(n, img, inc=None):
    """Gesture number n (0, 1, ...) of INCENSE_GESTURES aimed at the incense inc (find_incense of img, or the
    last one seen): (text, kind, args), kind 'tap' (x, y, ms), 'swipe' (x1, y1, x2, y2, ms) or 'touch' (a list
    of (action, x, y) for _touch); None when there are no more gestures; kind 'skip' (args None) when this one
    cannot be aimed (no yellow dot seen for the button)."""
    if n >= len(INCENSE_GESTURES):
        return None
    what, kind, key, ms = INCENSE_GESTURES[n]
    h, w = img.shape[:2]
    s = w / 1768.0
    if inc is None:                                   # not found at all: where it usually hangs
        inc = {"cx": int(0.5 * w), "cy": int(0.57 * h), "button": None}
    cx, cy, btn = inc["cx"], inc["cy"], inc.get("button")
    up = lambda d: max(100, cy - int(d * s))          # the end of a throw, never off the top of the screen
    if key == "button":
        if not btn:
            return what, "skip", None
        return what, "tap", (int(btn[0] + INC_BUTTON_FROM_DOT[0] * s), int(btn[1] + INC_BUTTON_FROM_DOT[1] * s), ms)
    if key == "middle":
        return what, "tap", (cx, cy, ms)
    if key == "ball":
        return what, "touch", [("DOWN", cx, cy), ("MOVE", cx, (cy + up(1000)) // 2), ("UP", cx, up(1000))]
    if key == "ball_far":
        return what, "touch", [("DOWN", cx, cy), ("MOVE", cx, (cy + up(1400)) // 2), ("UP", cx, up(1400))]
    if key == "grab":
        return what, "touch", [("DOWN", cx, cy), ("SLEEP", 0.4, 0), ("MOVE", cx, cy - int(300 * s)),
                               ("MOVE", cx, cy - int(600 * s)), ("UP", cx, up(900))]
    if key == "up_fast":
        return what, "swipe", (cx, cy, cx, up(600), ms)
    if key == "up_mid":
        return what, "swipe", (cx, cy + int(30 * s), cx, up(770), ms)
    if key == "up_vfast":
        return what, "swipe", (cx, cy, cx, up(500), ms)
    if key == "up_low":
        return what, "swipe", (cx, cy + int(90 * s), cx, up(610), ms)
    if key == "up_slow":
        return what, "swipe", (cx, cy, cx, up(700), ms)
    if key == "up_drag":
        return what, "swipe", (cx, cy, cx, up(600), ms)
    if key == "up_right":
        return what, "swipe", (cx, cy, min(w - 60, cx + int(200 * s)), up(600), ms)
    return what, "tap", (cx, cy, ms)


def _bag_to_map():
    """Back to the map from wherever the bag routine ended (bag, item, main menu, a question)."""
    for _ in range(6):
        img = S.screenshot()
        if S.on_map(img):
            return
        lines = ocr_lines(img, 100, 2150, 0.6)
        kind = _screen_kind(img, lines)
        if kind in ("exit", "discard"):
            _leave_question(kind, lines)             # never confirm either of them
        elif kind in ("menu", "bag"):
            S.tap(*MENU_BTN)                         # the round X button at the bottom closes both
        else:
            S.back()
        time.sleep(2)


# ------------------------------- Pokémon storage: look (nothing is sent away) ----------------------------------
STORAGE_SEARCH = ("count2-&!shiny&!legendary&!mythical&!ultra beasts&!4*&!3*&!favorite&!#&!costume&!lucky&!shadow"
                  "&!purified&!traded&!background&!dynamax&!gigantamax&!xxl&!xxs&cp-1500")
STORAGE_SEARCH_Y = 0.15        # the search field near the top of the storage (fraction of the height), when not read


def storage_search():
    """The search of 'what may go' (web interface), or the standard one."""
    t = str(setting("storage_search", STORAGE_SEARCH) or STORAGE_SEARCH)
    return t if re.fullmatch(r"[A-Za-z0-9 &,!*#:+\-]{1,240}", t) else STORAGE_SEARCH


def _type_text(text):
    """Type text in the field that has the focus (spaces as %s; inside single quotes for the phone's shell)."""
    S.adb("shell", "input text '" + text.replace("'", "").replace(" ", "%s") + "'")


def storage_look():
    """From the map: main menu -> POKÉMON -> search with storage_search() -> a picture of what came up
    (debug/g_storage_result.png) -> back to the map.  Nothing is selected and nothing is sent away: this shows
    which Pokémon the search would pick.  Returns {ok, used, max, why}."""
    out = {"ok": False, "used": None, "max": None, "why": ""}
    S.tap(*MENU_BTN)
    spots = None
    try:
        for step in range(7):
            shot = _settled(2.5)
            lines = ocr_lines(shot, 100, 2150)
            ws = _words(lines)
            k = shot.shape[0] / 2208
            count = next((w for w, x, y in ws if y < 500 * k and re.fullmatch(r"\d{1,4}/\d{3,4}", w)), None)
            top_pokemon = any(_like(w, "POKEMON", 0.8) and y < 450 * k for w, x, y in ws)
            log(f"storage: step {step}: {_reads(lines, 90)}")
            if (count or top_pokemon) and not any(_like(w, "ITEMS", 0.8) and y < 450 * k for w, x, y in ws):
                if count:
                    out["used"], out["max"] = (int(v) for v in count.split("/"))
                save_async("g_storage.png", shot)
                field = next(((x, y) for w, x, y in ws if _like(w, "SEARCH", 0.8) and y < 700 * k), None)
                x, y = field or (shot.shape[1] // 2, int(STORAGE_SEARCH_Y * shot.shape[0]))
                log(f"storage: the Pokémon storage is open ({count or 'count not read'}) - searching at ({x}, {y})")
                S.tap(x, y)
                time.sleep(1.5)
                _type_text(storage_search())
                time.sleep(0.8)
                S.adb("shell", "input", "keyevent", "66")
                res = _settled(2.5)
                save_async("g_storage_result.png", res)
                log(f"storage: searched '{storage_search()}' - what came up is in debug/g_storage_result.png "
                    f"({_reads(ocr_lines(res, 100, 2150), 120)})")
                out["ok"] = True
                return out
            if S.on_map(shot):
                S.tap(*MENU_BTN)
                continue
            if _screen_kind(shot, lines) == "menu":
                if spots is None:
                    found = sorted([(x, y) for w, x, y in ws if _like(w, "POKEMON", 0.75) and 1250 * k < y < 1700 * k
                                    and x < shot.shape[1] // 2], key=lambda p: p[0])
                    if not found:
                        out["why"] = "POKEMON is not in the main menu"
                        break
                    x, y = found[0]
                    spots = [(x, y + int(ITEMS_ICON_DY * k)), (x, y)]
                if not spots:
                    out["why"] = "the storage did not open"
                    break
                S.tap(*spots.pop(0))
            else:
                S.back()
        out["why"] = out["why"] or "the storage was not reached"
        return out
    finally:
        _bag_to_map()
        if out["used"] is not None:
            log(f"storage: {out['used']} of {out['max']} places used")


# ------------------------------- your Pokémon: leagues, tags, scan, teams ----------------------------------
# (collection.py does the sums; here are the steps on the phone.  The screens of the storage were seen on
# screenshots of 24 November: tabs TAGS / POKEMON / EGGS at the top, 'Search' under them, three Pokémon a row;
# TAGS: cards of the tags with a round + at the bottom left; CREATE TAG: 'Enter tag name', colours, DONE.)
import collection as COL     # your Pokémon and the teams (collection.py)

TAG_PLUS = (0.145, 0.885)      # the round + on the TAGS tab (fractions of the screen)
FIRST_TILE = (0.205, 0.45)     # the first Pokémon of the storage (when its CP is not read)
MENU_RB = (0.88, 0.905)        # the round menu button at the bottom right of a Pokémon's page
SCAN_SWIPE = ((0.85, 0.30), (0.15, 0.30))   # to the next Pokémon (from right to left, high on the screen)
SCAN_SAME = 3                  # the same Pokémon this many times after a swipe: the end of the list
SCAN_EVERY_SAVE = 20           # the scan is written to collection.json every so many Pokémon
TAG_COLOURS = ((0.36, 0.405), (0.475, 0.405), (0.585, 0.405), (0.695, 0.405))   # CREATE TAG: the first row


def current_game():
    """The package of the Pokémon GO app on the screen now (every app is another account), else S.PACKAGE."""
    pk = S.foreground_package()
    return pk if "pokemongo" in pk else S.PACKAGE


def read_leagues(game=None):
    """The leagues on the league list of the Battle screen now: [{title, cap, cup}] (cup: PvPoke's name), kept in
    the collection of this game. Walks there from the map and back."""
    game = game or current_game()
    info = battle_open_menu(leagues_only=True)
    if not info.get("leagues"):
        log(f"leagues: not read - {info.get('why') or 'unknown'}")
        return []
    leagues = []
    for title, cap in info["leagues"]:
        cup, _cap = COL.match_format(title, cap)
        leagues.append({"title": title, "cap": cap, "cup": cup})
    c = COL.load_collection(game=game)
    c["game"] = game
    c["leagues"], c["leagues_read"] = leagues, time.strftime("%Y-%m-%d %H:%M")
    COL.save_collection(c, game=game)
    log("leagues: " + "; ".join(f"{lg['title']} = PvPoke {lg['cup']} {lg['cap']}" for lg in leagues))
    return leagues


def _open_storage(tab="POKEMON"):
    """From the map: main menu -> POKEMON -> the tab (POKEMON or TAGS). Returns (picture, lines) or None."""
    S.tap(*MENU_BTN)
    spots = None
    for step in range(8):
        shot = _settled(2.2)
        lines = ocr_lines(shot, 60, 2150)
        ws = _words(lines)
        k = shot.shape[0] / 2208
        tabs = {w: (x, y) for w, x, y in ws if y < 420 * k and any(_like(w, t, 0.8) for t in ("TAGS", "POKEMON", "EGGS"))}
        if any(_like(w, "EGGS", 0.8) for w in tabs) or any(_like(w, "TAGS", 0.8) for w in tabs):
            want = next(((x, y) for w, (x, y) in tabs.items() if _like(w, tab, 0.8)), None)
            if want is None:
                log(f"storage: the tab {tab} is not read ({_reads(lines, 80)})")
                return None
            S.tap(*want)
            shot = _settled(1.8)
            return shot, ocr_lines(shot, 60, 2150)
        if S.on_map(shot):
            S.tap(*MENU_BTN)
            continue
        if _screen_kind(shot, lines) == "menu":
            if spots is None:
                found = sorted([(x, y) for w, x, y in ws if _like(w, "POKEMON", 0.75) and 1250 * k < y < 1700 * k
                                and x < shot.shape[1] // 2], key=lambda p: p[0])
                if not found:
                    break
                x, y = found[0]
                spots = [(x, y + int(ITEMS_ICON_DY * k)), (x, y)]
            if not spots:
                break
            S.tap(*spots.pop(0))
        else:
            S.back()
    log("storage: the Pokémon storage did not open")
    return None


def _xy(img, frac):
    return int(frac[0] * img.shape[1]), int(frac[1] * img.shape[0])


def _all_tag_text(shot, lines):
    """The text of every tag on the TAGS tab: the cards are scrolled through (up to five times) and back."""
    texts, seen = [t for t, _x, _y, _w in lines], set()
    for i in range(5):
        h, w = shot.shape[:2]
        S.swipe(w // 2, int(h * 0.75), w // 2, int(h * 0.35), 350)
        time.sleep(1.0)
        shot = S.screenshot()
        new = [t for t, _x, _y, _w in ocr_lines(shot, 60, 2150)]
        if set(new) <= seen:
            break
        seen.update(new)
        texts += new
    for _ in range(i + 1):
        S.swipe(w // 2, int(h * 0.35), w // 2, int(h * 0.80), 300)
        time.sleep(0.6)
    return " | ".join(texts)


def _green_button(img, y0=0.6, y1=0.97):
    """The centre of the wide green button (DONE) in the lower part of the screen, or None. Its white letters with
    wide gaps ('D O N E') on the green gradient are not always read (24 November)."""
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img[int(y0 * h):int(y1 * h)], cv2.COLOR_BGR2HSV)
    mask = ((hsv[..., 0] >= 35) & (hsv[..., 0] <= 90) & (hsv[..., 1] > 70) & (hsv[..., 2] > 140)).astype(np.uint8)
    n, _lab, st, cen = cv2.connectedComponentsWithStats(mask, 8)
    best = None
    for i in range(1, n):
        x, y, bw, bh, area = st[i]
        if bw > 0.25 * w and 0.03 * h < bh < 0.15 * h and area > 0.5 * bw * bh and (best is None or area > best[0]):
            best = (area, int(cen[i][0]), int(cen[i][1] + y0 * h))
    return best[1:] if best else None


def make_league_tags(leagues=None, game=None):
    """A tag for every league of now, named after it, unless it is there already (TAGS tab, all cards looked
    through). Returns the names."""
    game = game or current_game()
    leagues = leagues if leagues is not None else (COL.load_collection(game=game).get("leagues") or read_leagues(game))
    if not leagues:
        return []
    got = _open_storage("TAGS")
    if got is None:
        _bag_to_map()
        return []
    shot, lines = got
    made = []
    try:
        have = _all_tag_text(shot, lines)
        shot = S.screenshot()
        for i, lg in enumerate(leagues):
            name = COL.tag_name(lg["title"], 60)
            if _plain_name(name) in _plain_name(have):
                log(f"tags: '{name}' is there already")
                made.append(name)
                continue
            for attempt, nm in enumerate((name, COL.tag_name(lg["title"], 24))):
                S.tap(*_xy(shot, TAG_PLUS))
                form = _settled(1.6)
                fl = ocr_lines(form, 60, 2150)
                if not any("CREATE TAG" in t or "TAG NAME" in t for t, _x, _y, _w in fl):
                    save_async("g_tag_create.png", form)
                    log(f"tags: CREATE TAG did not open ({_reads(fl, 80)}) - see debug/g_tag_create.png")
                    return made
                field = next(((x, y) for t, x, y, _w in fl if "TAG NAME" in t or "ENTER" in t), _xy(form, (0.35, 0.255)))
                S.tap(field[0] + 120, field[1])
                time.sleep(0.8)
                _type_text(nm)
                time.sleep(0.6)
                S.adb("shell", "input", "keyevent", "66")
                time.sleep(0.6)
                S.tap(*_xy(form, TAG_COLOURS[i % len(TAG_COLOURS)]))
                time.sleep(0.4)
                form = _settled(1.0)
                fl = ocr_lines(form, 60, 2150)
                done = next(((x, y) for t, x, y, _w in fl if "DONE" in t.replace(" ", "")), None) or _green_button(form)
                if done is None:
                    save_async("g_tag_form.png", form)
                    log("tags: DONE is not read (debug/g_tag_form.png)")
                    S.back()
                    return made
                S.tap(*done)
                after = _settled(1.6)
                al = ocr_lines(after, 60, 2150)
                if any("CREATE TAG" in t for t, _x, _y, _w in al):          # not taken (a name too long?)
                    save_async(f"g_tag_refused{attempt}.png", after)
                    log(f"tags: the game did not take the name '{nm}' ({_reads(al, 80)})")
                    S.back()
                    time.sleep(1.2)
                    continue
                log(f"tags: made the tag '{nm}' for {lg['title']}")
                made.append(nm)
                shot, lines = after, al
                break
        c = COL.load_collection(game=game)
        c["tags"] = {lg["title"]: n for lg, n in zip(leagues, made)}
        COL.save_collection(c, game=game)
        return made
    finally:
        _bag_to_map()


BARS_BOX = (0.02, 0.50, 0.45, 0.93)   # where the panel with the three appraisal bars is (x0, y0, x1, y1 fractions)


def _bar_row(hsv_row, k):
    """(start, end, filled length) of the longest bar on one row of pixels, or None. Filled: orange (Attack,
    Defense) or pale red (a full HP bar); empty: light grey; the three parts have small gaps between them."""
    h, sat, v = hsv_row[:, 0].astype(int), hsv_row[:, 1].astype(int), hsv_row[:, 2].astype(int)
    fill = (sat > 60) & (v > 150) & ((h <= 25) | (h >= 160))
    grey = (sat < 40) & (v > 170) & (v < 242)
    cols = np.where(fill | grey)[0]
    if len(cols) < 2:
        return None
    runs, start, prev = [], cols[0], cols[0]
    for c in cols[1:]:
        if c - prev > 24 * k:
            runs.append((start, prev))
            start = c
        prev = c
    runs.append((start, prev))
    a, b = max(runs, key=lambda r: r[1] - r[0])
    filled = np.where(fill[a:b + 1])[0]
    return int(a), int(b), int(filled[-1] + 1) if len(filled) else 0


def _bars(img, lines=None):
    """The three appraisal bars: [attack, defense, hp] (0..15) or None. Found by their colours in the white panel
    at the bottom left (seen on 24 November): three bars of the same length one under the other, each of three
    parts; the filled part orange (pale red when it is 15), the rest light grey. (The labels next to them are too
    small and coloured for OCR.)"""
    H, W = img.shape[:2]
    k = H / 2208
    x0, y0, x1, y1 = (int(BARS_BOX[0] * W), int(BARS_BOX[1] * H), int(BARS_BOX[2] * W), int(BARS_BOX[3] * H))
    hsv = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    bands, cur = [], None
    for r in range(0, hsv.shape[0], max(1, int(3 * k))):
        got = _bar_row(hsv[r], k)
        if got and got[1] - got[0] >= 0.15 * W:
            if cur and r - cur["last"] <= 12 * k:
                cur["rows"].append(got)
                cur["last"] = r
            else:
                cur = {"rows": [got], "last": r, "y": r}
                bands.append(cur)
    best = []
    for b in bands:                                    # per band: its longest row (the middle of the bar)
        a, e, f = max(b["rows"], key=lambda g: g[1] - g[0])
        best.append((b["y"], a, e, f))
    for i in range(len(best) - 2):                     # three bars in a row of (nearly) the same length
        trio = best[i:i + 3]
        lens = [e - a for _y, a, e, _f in trio]
        if max(lens) - min(lens) <= 0.08 * max(lens) and max(abs(t[1] - trio[0][1]) for t in trio) <= 20 * k:
            return [COL.bar_value(f, e - a + 1) for _y, a, e, f in trio]
    return None


TYPE_WORDS = ("NORMAL", "FIRE", "WATER", "GRASS", "ELECTRIC", "ICE", "FIGHTING", "POISON", "GROUND", "FLYING",
              "PSYCHIC", "BUG", "ROCK", "GHOST", "DRAGON", "DARK", "STEEL", "FAIRY")


def _tess_line(img, chars):
    """One line of text (tesseract --psm 7) with only these characters."""
    ok, buf = cv2.imencode(".png", img)
    try:
        return subprocess.run(["tesseract", "stdin", "stdout", "--psm", "7", "-c", "tessedit_char_whitelist=" + chars],
                              env=OCR["env"], input=buf.tobytes(), capture_output=True, timeout=20).stdout.decode().strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


CP_BOX = (0.035, 0.14, 0.25, 0.75)       # (y0, y1, x0, x1): 'CP 3007' above the Pokémon, white on the background
HP_BOX = (0.56, 0.592, 0.38, 0.62)       # '161 / 161 HP' under the name


CP_TEXT = (0.045, 0.122, 0.28, 0.72)     # (y0, y1, x0, x1): only the 'CP 3007' line, above the arc
NAME_BOX = (0.49, 0.545, 0.2, 0.8)       # the name (or nickname) on the white card, above the HP bar


def _read_cp(img):
    """The CP at the top of a Pokémon's page: the text that is lighter than the background around it (top-hat),
    so also on a light, sunny background (24 November: 'CP112' on a bright sky). The older white-only reading
    is the fallback."""
    h, w = img.shape[:2]
    y0, y1, x0, x1 = CP_TEXT
    g = cv2.cvtColor(img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)], cv2.COLOR_BGR2GRAY)
    if g.size:
        sc = 110 / g.shape[0]
        g = cv2.resize(g, None, fx=sc, fy=sc, interpolation=cv2.INTER_CUBIC)
        th = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (41, 41)))
        _t, b = cv2.threshold(th, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        b = cv2.copyMakeBorder(255 - b, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        t = _tess_line(b, "CPcp0123456789")
        m = re.search(r"[Pp]\s*(\d{2,5})", t)
        if m:
            return int(m.group(1))
    return _read_cp_white(img)


def _read_name(img):
    """The name on the Pokémon's card, read on its own (dark letters on the white-to-blue card; the general OCR
    misses it under the appraisal: 'Vee' for Eevee). '' when nothing was read."""
    h, w = img.shape[:2]
    y0, y1, x0, x1 = NAME_BOX
    g = cv2.cvtColor(img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)], cv2.COLOR_BGR2GRAY)
    if g.size == 0:
        return ""
    g = cv2.resize(g, None, fx=90 / g.shape[0], fy=90 / g.shape[0], interpolation=cv2.INTER_CUBIC)
    _t, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if (b == 0).mean() > 0.5:
        b = 255 - b
    b = cv2.copyMakeBorder(b, 15, 15, 15, 15, cv2.BORDER_CONSTANT, value=255)
    t = _tess_line(b, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.'- ")
    words = t.split()
    while words and len(words[-1].strip(".'-")) < 2:           # (the pencil and the gender sign: 'Eevee .')
        words.pop()
    return " ".join(words).strip(" .-")


def _read_cp_white(img):
    """The CP at the top of a Pokémon's page (also under the appraisal). The general OCR does not see the white
    'CP3007' on the coloured background (24 November): only the white parts of the picture are read, without the
    arc under it."""
    h, w = img.shape[:2]
    y0, y1, x0, x1 = CP_BOX
    crop = img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = ((hsv[..., 2] > 200) & (hsv[..., 1] < 70)).astype(np.uint8)
    n, lab, st, _c = cv2.connectedComponentsWithStats(mask, 8)
    ch, cw = mask.shape
    keep = np.zeros_like(mask)
    for i in range(1, n):
        _x, _y, bw, bh, area = st[i]
        if 0.12 * ch < bh < 0.7 * ch and bw < 0.2 * cw and area > 4:     # (letters; not the arc, not specks)
            keep[lab == i] = 255
    if not keep.any():
        return None
    sc = 100 / ch
    pic = cv2.resize(255 - keep, None, fx=sc, fy=sc, interpolation=cv2.INTER_CUBIC)
    pic = cv2.copyMakeBorder(pic, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    t = _tess_line(pic, "CPcp0123456789")
    m = re.search(r"[Pp]\s*(\d{2,5})", t) or re.fullmatch(r"(\d{2,5})", t)
    return int(m.group(1)) if m else None


def _read_hp(img):
    """The maximum HP under the name ('161 / 161 HP'), also under the appraisal (a darker background)."""
    h, w = img.shape[:2]
    y0, y1, x0, x1 = HP_BOX
    g = cv2.cvtColor(img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)], cv2.COLOR_BGR2GRAY)
    if g.size == 0:
        return None
    g = cv2.resize(g, None, fx=70 / g.shape[0], fy=70 / g.shape[0], interpolation=cv2.INTER_CUBIC)
    _t, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if (b == 0).mean() > 0.5:
        b = 255 - b
    b = cv2.copyMakeBorder(b, 15, 15, 15, 15, cv2.BORDER_CONSTANT, value=255)
    m = re.search(r"(\d{1,4})\s*/\s*(\d{1,4})", _tess_line(b, "0123456789/HP "))
    return int(m.group(2)) if m else None


def _read_page(img, lines):
    """{name, cp, hp (max HP), types} of the Pokémon on its page (also under the appraisal: name, CP, HP and
    the types are above it). Values that were not read are None."""
    k = img.shape[0] / 2208
    name, _sid, cp = _read_mon(img, lines)
    hp = None
    types = None
    for t, _x, y, _w in lines:
        m = re.search(r"(\d{1,4})\s*/\s*(\d{1,4})\s*HP", t.replace("O", "0"))
        if m and hp is None:
            hp = int(m.group(2))
        found = [w for w in TYPE_WORDS if re.search(r"\b" + w + r"\b", t)]
        if found and "/" in t or (found and len(found) == 1 and t.strip() in TYPE_WORDS):
            if 700 * k < y < 1700 * k and types is None:
                types = [w.lower() for w in found][:2]
    cp = _read_cp(img) or cp
    hp = _read_hp(img) or hp
    own = _read_name(img)
    if own and (not name or COL.find_species(own.title())):
        name = own.title()                                  # (the name read on its own is the better one)
    if not name:
        for t, _x, y, _w in sorted(lines, key=lambda l: l[2]):      # (a nickname: the line above the HP bar)
            if 600 * k < y < 1300 * k and re.fullmatch(r"[A-Z0-9 .'\-]{2,14}", t.strip()) and "HP" not in t:
                name = t.strip().title()
                break
    return {"name": name, "cp": cp, "hp": hp, "types": types}


def _read_mon(img, lines):
    """(name, species id, CP) of the Pokémon on its page (also under the appraisal)."""
    k = img.shape[0] / 2208
    cp = None
    for t, _x, y, _w in lines:
        if y < 700 * k:
            m = re.search(r"[CE]{0,2}\s*P\s*(\d{2,5})\b", t.replace("O", "0"))
            if m:
                cp = int(m.group(1))
                break
    name = sid = None
    for t, _x, y, _w in sorted(lines, key=lambda l: l[2]):
        if y < 500 * k or y > 1500 * k or re.search(r"\d|/|HP|WEIGHT|HEIGHT|STARDUST|CANDY|ATTACK|DEFENSE", t):
            continue
        found = COL.find_species(t.title())
        if found:
            # (without the bits OCR makes of the pencil and the gender sign: 'Latios ~', 24 November)
            name, sid = re.sub(r"[^\w .'\-:()]+", " ", t).split("  ")[0].strip(" .-").title() or t.title(), found
            name = re.sub(r"\s+[^\w(]{0,2}$", "", name).strip()
            break
    return name, sid, cp


def _open_first_and_appraise(search=""):
    """Storage -> (search) -> the first Pokémon -> its menu -> APPRAISE -> the bars. Returns True when the bars
    are on the screen."""
    got = _open_storage("POKEMON")
    if got is None:
        return False
    shot, lines = got
    if search:
        field = next(((x, y) for w, x, y in _words(lines) if _like(w, "SEARCH", 0.8)), _xy(shot, (0.5, 0.275)))
        S.tap(*field)
        time.sleep(1.2)
        _type_text(search)
        time.sleep(0.6)
        S.adb("shell", "input", "keyevent", "66")
        shot = _settled(2.0)
        lines = ocr_lines(shot, 60, 2150)
    k = shot.shape[0] / 2208
    cps = sorted([(y, x) for w, x, y in _words(lines) if re.fullmatch(r"C?P?\d{2,5}", w) and 400 * k < y < 900 * k])
    x, y = (cps[0][1], int(cps[0][0] + 170 * k)) if cps else _xy(shot, FIRST_TILE)
    S.tap(x, y)
    page = _settled(2.0)
    save_async("g_scan_page.png", page)
    return _appraise_here(page)


def _appraise_here(page=None):
    """On a Pokémon's page: its menu -> APPRAISE -> tap through the leader's words until the bars are there.
    Also to open the appraisal again when it closed halfway a scan (24 November: after 300 Pokémon)."""
    page = page if page is not None else S.screenshot()
    S.tap(*_xy(page, MENU_RB))
    menu = _settled(1.5)
    ml = ocr_lines(menu, 60, 2150)
    spot = next(((x, y) for w, x, y in _words(ml) if _like(w, "APPRAISE", 0.8)), None)
    if spot is None:
        save_async("g_scan_menu.png", menu)
        log(f"scan: APPRAISE is not in the menu ({_reads(ml, 80)}) - see debug/g_scan_menu.png")
        return False
    S.tap(*spot)
    for _ in range(6):                                # the leader talks first: tap until the bars are there
        time.sleep(1.2)
        img = S.screenshot()
        if _bars(img):
            return True
        S.tap(*_xy(img, (0.5, 0.80)))
    save_async("g_scan_appraise.png", img)
    log("scan: the appraisal bars did not come (debug/g_scan_appraise.png)")
    return False


def _scan_one(img, lines):
    """A scanned Pokémon from one picture: {name, species, cp, ivs, level, hp, how} or None (with why)."""
    page = _read_page(img, lines)
    ivs = _bars(img)
    if not ivs or not page["cp"]:
        return None, f"name {page['name']} CP {page['cp']} bars {ivs}"
    sid, lv, how = COL.identify(page["cp"], ivs, page["hp"], page["types"], page["name"])
    if not sid:
        return None, f"{page['name']} CP {page['cp']} HP {page['hp']} {ivs}: {how}"
    return {"name": page["name"] or COL.species_table()[sid]["name"], "species": sid, "cp": page["cp"],
            "ivs": ivs, "level": lv, "hp": page["hp"], "how": how}, ""


def scan_collection(limit=None, search="", stop=None, flag=None, game=None):
    """Go through the Pokémon storage with the appraisal open: for each Pokémon its name, CP, HP, types and IVs
    (bars), one after another (swiping to the next). The pictures come from the live video when it runs (a sharp
    screenshot when something was not read); the species is checked against CP and HP (also for a nickname).
    Kept in the collection of the game (also halfway). limit: at most this many; search: only what the game's
    search finds ('age0-7': caught in the last week); flag ('shadow', 'lucky', 'purified'): only mark the ones
    the search finds (search = flag) in the collection. Returns the number scanned."""
    game = game or current_game()
    c = COL.load_collection(game=game)
    c["game"] = game
    old = {m["id"]: m for m in c.get("mons") or []}
    seen, n, tried, same, last, dup, reopen = {}, 0, 0, 0, None, {}, 0
    flagged = set()
    t0 = time.time()
    if not _open_first_and_appraise(flag or search):
        _bag_to_map()
        return 0
    try:
        while (limit is None or tried < limit) and not (stop and stop()):
            tried += 1                                      # (the limit counts the Pokémon looked at, read or not)
            img = S.quick_screenshot()
            lines = ocr_lines(img, 60, 2150)
            mon, why = _scan_one(img, lines)
            if mon is None or mon["how"] != "name":
                sharp = S.screenshot()                      # (once more on a sharp screenshot)
                sl = ocr_lines(sharp, 60, 2150)
                mon2, why2 = _scan_one(sharp, sl)
                if mon2 is not None and (mon is None or mon2["how"] == "name"):
                    mon, why, img = mon2, why2, sharp
                elif mon is None and not _bars(sharp):
                    # the appraisal closed (the page of a Pokémon without the bars): open it again, then this
                    # Pokémon once more - without it every next Pokémon is 'not read' (24 November)
                    reopen += 1
                    if reopen > 3:
                        save_async("g_scan_lost.png", sharp)
                        log("scan: the appraisal does not open again - stopped (debug/g_scan_lost.png)")
                        break
                    log("scan: the appraisal closed - opening it again")
                    if not _appraise_here(sharp):
                        log("scan: the appraisal did not open again - stopped")
                        break
                    tried -= 1
                    continue
            reopen = 0
            if mon is None and "CP None" in why:
                save_async("g_scan_nocp.png", img)          # (to see why the CP was not read)
            key = (mon["species"], mon["cp"], tuple(mon["ivs"])) if mon else ("?", why)
            if key == last and mon is None:                 # (a Pokémon not read ends the list only after many)
                same += 1
                if same >= 8:
                    log(f"scan: the same unread page after {same} swipes - stopped")
                    break
            elif key == last:
                same += 1
                if same >= SCAN_SAME:
                    log(f"scan: the same Pokémon after {same} swipes - the end of the list")
                    break
            else:
                same, last = 0, key
                if mon:
                    base_id = f"{mon['species']}-{mon['cp']}-{mon['ivs'][0]}-{mon['ivs'][1]}-{mon['ivs'][2]}"
                    dup[base_id] = dup.get(base_id, 0) + 1
                    mid = base_id + (f"#{dup[base_id]}" if dup[base_id] > 1 else "")   # (two that are the same)
                    if flag:
                        flagged.add(mid)
                    else:
                        prev = old.get(mid, {})
                        seen[mid] = {**{k: prev[k] for k in ("shadow", "lucky", "purified", "moves", "candy", "xl")
                                        if k in prev},
                                     "id": mid, **mon, "scanned": time.strftime("%Y-%m-%d %H:%M")}
                    n += 1
                    if n <= 3 or n % 25 == 0:
                        log(f"scan: {n}: {mon['species']} CP {mon['cp']} IVs {mon['ivs'][0]}/{mon['ivs'][1]}/"
                            f"{mon['ivs'][2]} level {mon['level']} ({mon['how']})")
                else:
                    save_async(f"g_scan_unread{tried % 5}.png", img)
                    log(f"scan: not read ({why}; debug/g_scan_unread{tried % 5}.png)")
                if n and n % SCAN_EVERY_SAVE == 0 and not flag:
                    c["mons"] = list({**old, **seen}.values())
                    COL.save_collection(c, game=game)
            if limit is not None and tried >= limit:
                break                                       # (no swipe past the last one)
            (x1, y1), (x2, y2) = _xy(img, SCAN_SWIPE[0]), _xy(img, SCAN_SWIPE[1])
            S.swipe(x1, y1, x2, y2, 220)
            time.sleep(0.9)
    finally:
        if flag:
            for mid, m in old.items():
                m[flag] = mid in flagged
            c["mons"] = list(old.values())
            log(f"scan: {len(flagged)} Pokémon are {flag}")
        else:
            c["mons"] = list(({**old, **seen} if limit or search else (seen or old)).values())
            c["scanned"] = time.strftime("%Y-%m-%d %H:%M")
        COL.save_collection(c, game=game)
        log(f"scan: {n} Pokémon read in {(time.time() - t0) / 60:.0f} min ({len(c['mons'])} in the collection of "
            f"{game})")
        _bag_to_map()
    return n


def _search_and_open(lines, shot, text):
    """On the Pokémon tab: search for `text` and open the first Pokémon. Returns its page."""
    field = next(((x, y) for w, x, y in _words(lines) if _like(w, "SEARCH", 0.8)), _xy(shot, (0.5, 0.275)))
    S.tap(*field)
    time.sleep(1.2)
    _type_text(text)
    time.sleep(0.6)
    S.adb("shell", "input", "keyevent", "66")
    res = _settled(2.0)
    S.tap(*_xy(res, FIRST_TILE))
    return _settled(2.0)


def _number_above(lines, word, k, exclude=None):
    """The number on the line just above a label (STARDUST, CANDY, CANDY XL); '284.694' -> 284694."""
    for t, x, y, _w in lines:
        if word in t and not (exclude and exclude in t):
            above = [(y - y2, t2) for t2, x2, y2, _w2 in lines if 0 < y - y2 < 130 * k and abs(x2 - x) < 260 * k]
            for _d, t2 in sorted(above):
                m = re.search(r"\d[\d.,]*", t2)
                if m:
                    return int(re.sub(r"[.,]", "", m.group(0)))
    return None


def check_team(game=None, stop=None):
    """For the team members and reserves of every league: open the Pokémon (search by name and CP), read the
    Candy, Candy XL and Stardust under it, scroll down and read its moves. Kept in the collection; the teams are
    made again with it (a Pokémon without the right moves or without enough candy counts less)."""
    game = game or current_game()
    c = COL.load_collection(game=game)
    t = COL.load_teams(game=game)
    by_id = {m["id"]: m for m in c.get("mons") or []}
    table = COL.species_table()
    done = 0
    for title, tm in (t.get("teams") or {}).items():
        for e in tm.get("team", []) + tm.get("reserves", []):
            if stop and stop():
                break
            m = by_id.get(e["mon"]["id"])
            if not m:
                continue
            got = _open_storage("POKEMON")
            if got is None:
                return done
            shot, lines = got
            try:
                page = _search_and_open(lines, shot, f"{table.get(m['species'], {}).get('name', m['name'])}&cp{m['cp']}")
                pl = ocr_lines(page, 60, 2150)
                k = page.shape[0] / 2208
                m["candy"] = _number_above(pl, "CANDY", k, exclude="XL")
                m["xl"] = _number_above(pl, "XL", k)
                m["stardust"] = _number_above(pl, "STARDUST", k)
                h, w = page.shape[:2]
                S.swipe(w // 2, int(h * 0.80), w // 2, int(h * 0.35), 400)     # down to the moves
                time.sleep(1.2)
                low = S.screenshot()
                ll = ocr_lines(low, 60, 2150)
                fast, charged = None, []
                row = table.get(m["species"], {})
                for t2, _x, _y, _w in ll:
                    mv = COL.BE.find_move(t2)
                    if not mv:
                        continue
                    if mv in (row.get("fast") or []) and fast is None:
                        fast = mv
                    elif mv in (row.get("charged") or []) and mv not in charged:
                        charged.append(mv)
                if fast or charged:
                    m["moves"] = {"fast": fast, "charged": charged}
                done += 1
                log(f"teams: {m['species']} CP {m['cp']}: moves {fast} / {', '.join(charged) or '?'}, candy {m['candy']}, "
                    f"XL {m['xl']}")
                if not (fast or charged):
                    save_async("g_moves.png", low)
            finally:
                _bag_to_map()
    COL.save_collection(c, game=game)
    if done:
        COL.make_teams(c, game=game)
    return done


def write_battle_team(teams=None, game=None):
    """The team of the league the bot fights in (and of the app that fights) becomes ~/battle_team.json."""
    game = game or current_game()
    if game != battle_app():
        return False
    t = teams if teams is not None else COL.load_teams(game=game).get("teams") or {}
    entries = COL.battle_team_entries(t, battle_league())
    if not entries:
        return False
    import battle_engine as BE2
    with open(BE2.team_file(), "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=1)
    log("teams: the battle team is now " + ", ".join(e["species"] for e in entries) + f" ({battle_league()})")
    return True


TEAMS_EVERY = 6.5 * 24 * 3600   # s: the weekly round (leagues, tags, new Pokémon, teams) after this long


def teams_due(game):
    """Option 'Keep the teams up to date': the weekly round is due for this game."""
    if not setting("teams_weekly", False):
        return False
    c = COL.load_collection(game=game)
    try:
        last = time.mktime(time.strptime(c.get("refreshed", "2000-01-01 00:00"), "%Y-%m-%d %H:%M"))
    except ValueError:
        last = 0
    return time.time() - last > TEAMS_EVERY


def teams_refresh(game=None, stop=None):
    """The weekly round of a game: read the leagues; when they changed (or never): a tag for each; scan the
    Pokémon of the last week (or all, the first time); shadow / lucky / purified; make the teams; check their
    moves and candy; tag them; the battle team; a message to the phone."""
    game = game or current_game()
    c = COL.load_collection(game=game)
    before = [lg["title"] for lg in c.get("leagues") or []]
    leagues = read_leagues(game)
    if not leagues:
        return False
    changed = [lg["title"] for lg in leagues] != before
    log(f"teams: weekly round for {game} - the leagues {'changed' if changed else 'are the same'}")
    if changed:
        make_league_tags(leagues, game)
    first = not c.get("mons")
    if not (stop and stop()):
        scan_collection(search="" if first else "age0-7", stop=stop, game=game)
    for flag in ("shadow", "lucky", "purified"):
        if stop and stop():
            break
        scan_collection(flag=flag, stop=stop, game=game)
    t = COL.make_teams(game=game)
    if not (stop and stop()):
        check_team(game, stop)
        t = COL.load_teams(game=game)
    if changed and not (stop and stop()):
        tag_team_members(t, game)
    write_battle_team(t.get("teams"), game)
    c = COL.load_collection(game=game)
    c["refreshed"] = time.strftime("%Y-%m-%d %H:%M")
    COL.save_collection(c, game=game)
    lines = [f"{title}: " + ", ".join(f"{e.get('role', '')} {e['eval']['form_name']}" for e in tm["team"])
             for title, tm in (t.get("teams") or {}).items()]
    topic = str(setting("ntfy_topic", "") or "")
    if topic:
        extras.ntfy_send(topic, "New teams", "\n".join(lines) or "no teams")
    log("teams: " + " | ".join(lines))
    return True


def tag_team_members(teams=None, game=None):
    """Give the Pokémon of the teams (and their reserves) the tag of their league: storage -> search for the
    Pokémon (name and CP) -> its page -> the tag button -> the league's tag. (The tag screens of a Pokémon were not
    seen yet: every step is read first, and the routine stops at a screen it does not know.)"""
    game = game or current_game()
    t = teams if teams is not None else COL.load_teams(game=game)
    names = COL.load_collection(game=game).get("tags") or {}
    done = 0
    for title, tm in (t.get("teams") or {}).items():
        tag = names.get(title) or COL.tag_name(title, 60)
        for e in tm.get("team", []) + tm.get("reserves", []):
            m = e["mon"]
            got = _open_storage("POKEMON")
            if got is None:
                return done
            shot, lines = got
            try:
                sp_name = COL.species_table().get(m["species"], {}).get("name", m["name"])
                page = _search_and_open(lines, shot, f"{re.sub(r' [(].*', '', sp_name)}&cp{m['cp']}")
                pl = ocr_lines(page, 60, 2150)
                spot = next(((x, y) for w, x, y in _words(pl) if _like(w, "TAG", 0.9) or _like(w, "TAGS", 0.9)), None)
                if spot is None:
                    S.tap(*_xy(page, MENU_RB))
                    menu = _settled(1.5)
                    pl = ocr_lines(menu, 60, 2150)
                    spot = next(((x, y) for w, x, y in _words(pl) if _like(w, "TAG", 0.9) or _like(w, "TAGS", 0.9)), None)
                    page = menu
                if spot is None:
                    save_async("g_tag_page.png", page)
                    log(f"tags: no tag button for {m['name']} CP {m['cp']} ({_reads(pl, 80)}) - see debug/g_tag_page.png; "
                        "send this picture so the tag screens can be added")
                    return done
                S.tap(*spot)
                pick = _settled(1.6)
                pk = ocr_lines(pick, 60, 2150)
                want = _plain_name(tag)
                row = next(((x, y) for t2, x, y, _w in pk if _like(_plain_name(t2), want, 0.8)), None)
                if row is None:
                    save_async("g_tag_pick.png", pick)
                    log(f"tags: the tag '{tag}' is not in the list ({_reads(pk, 80)}) - see debug/g_tag_pick.png")
                    return done
                S.tap(*row)
                time.sleep(0.8)
                after = _settled(1.0)
                al = ocr_lines(after, 60, 2150)
                ok_btn = (next(((x, y) for t2, x, y, _w in al if "DONE" in t2.replace(" ", "")), None)
                          or next(((x, y) for w, x, y in _words(al) if w in ("OK", "SAVE")), None) or _green_button(after))
                if ok_btn is None:
                    save_async("g_tag_done.png", after)
                    log("tags: DONE is not read (debug/g_tag_done.png)")
                    return done
                S.tap(*ok_btn)
                done += 1
                log(f"tags: {m['name']} CP {m['cp']} has the tag '{tag}'")
            finally:
                _bag_to_map()
    return done


BAG_WORDS = ("POTION", "REVIVE", "BALL", "BERR", "LUCKY", "INCENSE", "RAZZ", "PINAP", "NANAB", "EGG", "LURE", "ADVENTURE")


# ------------------------------- a full bag: clean-up ----------------------------------
# What is kept of each item when the bag is full (the rest is discarded); items that are not named here are
# never touched (Ultra Ball, Master Ball, Revive, eggs, lures, incense ...).  The names as the bag shows them,
# without accents; a name ending in '*' stands for every item whose name contains the word (all berries).
import bag_rules             # what the bag keeps: set in the web interface ('What the bag keeps'), see bag_rules.py
import extras               # the history of the days (gamebot_history.json)
BAG_TRASH_X = 0.80          # the trash can of a row, right of its name (fraction of the width) ...
BAG_TRASH_DY = -0.017       # ... a little above the middle of its name (fraction of the height)
BAG_COUNT_DY = (0.04, 0.16)  # the count 'x487' stands under the left of the picture, this far under the name
DISCARD_MINUS_X, DISCARD_PLUS_X = 0.26, 0.726   # 'Discard Poké Ball?': the - and + buttons ...
DISCARD_NUMBER_AT = 0.458   # ... and the number between them: this far from the title down to YES
BAG_CLEAN_EVERY = 20 * 60   # s: the bag is cleaned up at most this often (when one freed nothing, it waits)
BAG_CLEAN_PAGES = 30        # pages of the bag that are looked through


def _plain_name(text):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().upper()
    return " ".join(re.sub(r"[^A-Z ]", " ", t).split())


def bag_plan():
    """[(NAME, keep)] as the bag clean-up uses them now: the numbers set in the web interface (plain upper-case
    names, 'POKE BALL'), or the standard ones."""
    return [(_plain_name(n), k) for n, k in bag_rules.rules(setting("bag_keep", None))]


def bag_keep(name, plan=None):
    """How many of the item with this name (as read in the bag) are kept, or None: not to be touched."""
    n = _plain_name(name)
    if not n or len(n.split()) > 4:
        return None
    for rule, keep in (plan if plan is not None else bag_plan()):
        if rule.endswith("*"):
            if rule[:-1] in n.split():
                return keep
        elif n == rule or (len(n) >= 6 and difflib.SequenceMatcher(None, n, rule).ratio() >= 0.9
                           and len(n.split()) == len(rule.split())):
            return keep
    return None


def bag_rows(lines, h, plan=None):
    """[(name, keep, x, y, count or None)]: the rows of a bag page whose item has a rule (see bag_plan).
    count: the number under the item's picture ('x487'), when it was read."""
    rows = []
    words = _words(lines)
    plan = plan if plan is not None else bag_plan()
    for text, x, y, _ws in lines:
        keep = bag_keep(text, plan)
        if keep is None:
            continue
        count = None
        for w, wx, wy in words:
            m = re.fullmatch(r"[XxKk×]?(\d{1,4})", w.strip())
            if m and wx < x and BAG_COUNT_DY[0] * h < wy - y < BAG_COUNT_DY[1] * h:
                count = int(m.group(1))
                break
        rows.append((_plain_name(text), keep, x, y, count))
    return rows


def _discard_dialog(img):
    """(title text, number or None, YES (x, y), NO (x, y), number y) of 'Discard <item>?', or None."""
    lines = ocr_lines(img, 100, 2150, 0.6)
    title = next(((t, x, y) for t, x, y, _ws in lines if "DISCARD" in t.upper()), None)
    if not title:
        return None
    yes = next(((x, y) for w, x, y in _words(lines) if w.upper() == "YES" and y > title[2]), None)
    no = next(((x, y) for w, x, y in _words(lines) if w.upper() == "NO" and y > title[2]), None)
    if not yes or not no:
        return None
    h, w = img.shape[:2]
    ny = int(title[2] + DISCARD_NUMBER_AT * (yes[1] - title[2]))
    box = img[max(0, ny - int(0.045 * h)):ny + int(0.045 * h), int(0.38 * w):int(0.62 * w)]
    gray = cv2.cvtColor(box, cv2.COLOR_BGR2GRAY)
    _t, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    digits = re.sub(r"\D", "", ocr_line(bw).replace("O", "0").replace("o", "0"))
    return title[0], (int(digits) if digits else None), yes, no, ny


def _canvas(img, x, y):
    h, w = img.shape[:2]
    return int(x * S.REF_W / w), int(y * S.REF_H / h)


def _set_discard_number(target, tries=14):
    """Tap - and + of the open 'Discard ...?' until it shows `target`.  Returns the last picture and reading."""
    img = S.screenshot()
    d = _discard_dialog(img)
    for _ in range(tries):
        if not d or d[1] is None:
            return img, d
        n = d[1]
        if n == target:
            return img, d
        h, w = img.shape[:2]
        x = DISCARD_PLUS_X if target > n else DISCARD_MINUS_X
        step = abs(target - n)
        cx, cy = _canvas(img, x * w, d[4])
        S.swipes([(cx, cy, cx, cy, 70)] * min(step, 40))    # (one adb command: up to 40 taps one after the other)
        time.sleep(0.8)
        img = S.screenshot()
        d = _discard_dialog(img)
    return img, d


def clean_bag():
    """The bag is full: discard what bag_plan() says (from the map, back on the map).  Every discard is checked
    on the question itself - the name of the item and the number - before YES; anything else gets NO.
    Returns the number of items discarded."""
    page = _open_bag()
    if not page:
        log("bag clean-up: the bag did not open")
        _bag_to_map()
        return 0
    gone, done, prev, still = 0, set(), None, 0
    plan = bag_plan()
    log("bag clean-up: the bag is full - discarding: " + ", ".join(f"{r.title()} down to {k}" for r, k in plan))
    pages = acts = 0
    while pages < BAG_CLEAN_PAGES and acts < 3 * len(plan) + 10:
        img = S.screenshot()
        lines = bag_ocr(img)
        h, w = img.shape[:2]
        if S.on_map(img):
            log("bag clean-up: the bag closed - stopping")
            break
        todo = [r for r in bag_rows(lines, h, plan) if r[0] not in done and 0.12 * h < r[3] < 0.86 * h]
        acted = False
        for name, keep, x, y, count in todo:
            done.add(name)
            if count is None:
                log(f"bag clean-up: {name.title()}: its number was not read - left as it is")
                continue
            if count <= keep:
                log(f"bag clean-up: {name.title()}: {count} - kept")
                continue
            want = count - keep
            log(f"bag clean-up: {name.title()}: {count}, keeping {keep} - discarding {want}")
            S.tap(*_canvas(img, BAG_TRASH_X * w, y + BAG_TRASH_DY * h))
            time.sleep(1.5)
            shot, d = _set_discard_number(want)
            save_async(f"g_bag_discard_{len(done)}.png", shot)
            if not d:
                log(f"bag clean-up: the question to discard {name.title()} did not come up")
                acted = True
                break
            title, n, yes, no = d[0], d[1], d[2], d[3]
            if _plain_name(title.replace("?", "")).replace("DISCARD", "").strip() != name or n != want:
                log(f"bag clean-up: the question reads '{title}' with {n} - not {name.title()} {want}: answering NO")
                S.tap(*_canvas(shot, *no))
            else:
                S.tap(*_canvas(shot, *yes))
                gone += want
                log(f"bag clean-up: discarded {want} {name.title()}")
            time.sleep(2.0)
            acted = True
            break                                    # (the list changed: read this page again)
        if acted:
            acts += 1
            continue
        pages += 1
        if prev is not None and not screen_changed(img, prev, 0.003):
            still += 1
            if still >= 2:
                break                                # the end of the list
        else:
            still = 0
        prev = img
        S.swipe(*BAG_SWIPE)
        time.sleep(1.2)
    log(f"bag clean-up: done - {gone} items discarded")
    _bag_to_map()
    return gone


def _words(lines):
    return [(w, x, y) for _, _, _, ws in lines for w, x, y in ws]


def _reads(lines, n=150):
    """For the log: the words OCR read on a screen."""
    seen = []
    for w, _, _ in _words(lines):
        if w not in seen:
            seen.append(w)
    return " ".join(seen)[:n] or "nothing"


def bag_like(lines):
    """Does this screen show items of the bag (balls, potions, berries ...)?"""
    return any(any(b in w for b in BAG_WORDS) for w, _, _ in _words(lines))


def screen_changed(a, b, share=0.05):
    small = lambda im: cv2.resize(im, (221, 276), interpolation=cv2.INTER_AREA).astype(np.int16)
    return float((np.abs(small(a) - small(b)).max(axis=2) > 25).mean()) >= share


ITEMS_ICON_DY = 195     # main menu: the round ITEMS button sits this far (px on a 2208 high screen) BELOW its label


def _screen_kind(img, lines):
    """map / exit ('Do you want to exit Pokémon GO?') / discard ('Discard <item>?') / bag (title ITEMS
    at the top) / menu (main menu: ITEMS and POKÉMON side by side in the lower half) / other."""
    if S.on_map(img):
        return "map"
    text = " ".join(t for t, _, _, _ in lines)
    ws = _words(lines)
    if "EXIT" in text and ("CANCEL" in text or "POK" in text):
        return "exit"
    if "DISCARD" in text or ("YES" in text.split() and "NO" in text.split() and "?" in text):
        return "discard"
    if any(y < 450 and ((_like(w, "ITEMS", 0.8) and abs(x - 884) < 330) or re.fullmatch(r"\d{1,4}/\d{1,4}", w))
           for w, x, y in ws):
        return "bag"                                 # the title ITEMS or the 'used/capacity' count at the top
    for w, x, y in ws:
        if _like(w, "ITEMS", 0.8) and 1250 < y < 1700 and x > 884:
            if any(_like(w2, "POKEMON", 0.8) and abs(y2 - y) < 80 and x2 < 884 for w2, x2, y2 in ws):
                return "menu"
    return "other"


def _settled(first_wait=2.0):
    """A screenshot of a screen that has stopped moving (after a tap: transitions and animations): two
    screenshots, taken at least a second apart, that show the same.  A screenshot takes one to three seconds
    itself, which is that second already (the picture is taken at the start of it)."""
    time.sleep(first_wait)
    t0 = time.time()
    prev = S.screenshot()
    for _ in range(3):
        time.sleep(max(1.0 - (time.time() - t0), 0.0))
        t0 = time.time()
        cur = S.screenshot()
        if not screen_changed(prev, cur, 0.01):
            return cur
        prev = cur
    return prev


def _cancel_exit(lines):
    """Answer 'Do you want to exit Pokémon GO?' with CANCEL."""
    for _, _, _, ws in lines:
        for w, x, y in ws:
            if _like(w, "CANCEL", 0.8):
                S.tap(x, y)
                return
    S.back()


def _cancel_discard(lines):
    """Answer 'Discard <item>?' with NO - never with YES."""
    for _, _, _, ws in lines:
        for w, x, y in ws:
            if w == "NO" and y > 1000:
                S.tap(x, y)
                return
    S.back()


def _leave_question(kind, lines):
    if kind == "exit":
        _cancel_exit(lines)
    elif kind == "discard":
        log("daily incense: a 'Discard ...?' question came up - answering NO")
        _cancel_discard(lines)


def _open_bag():
    """Main menu -> item bag. Returns (picture, OCR lines) of the bag, or None.
    Every step looks at what is really on the screen (map / main menu / bag / a question) instead
    of pressing BACK blindly. The bag is only accepted when its title ITEMS is at the top; the
    round ITEMS button (below its label in the menu) is tapped first, then the label itself."""
    S.tap(*MENU_BTN)
    spots, tapped, others = None, 0, 0
    for step in range(9):
        shot = _settled(2.5 if step == 0 or tapped else 1.5)
        lines = ocr_lines(shot, 100, 2150)
        kind = _screen_kind(shot, lines)
        save_async(f"g_incense_s{step}.png", shot)
        log(f"daily incense: step {step}: screen is {kind} ({_reads(lines, 90)})")
        if kind == "bag":
            return shot, lines
        if kind in ("exit", "discard"):
            _leave_question(kind, lines)
            if kind == "discard":
                break
        elif kind == "map":
            S.tap(*MENU_BTN)                         # the menu is closed (again): open it
        elif kind == "other":
            others += 1                              # something in the way / still loading
            if others > 2:
                break
            if not tapped:
                S.back()
        else:                                        # menu
            if spots is None:
                save_async("g_incense_menu.png", shot)
                items = sorted([(x, y) for w, x, y in _words(lines) if _like(w, "ITEMS", 0.75) and y > 1250],
                               key=lambda p: -p[0])
                if not items:
                    log("daily incense: the word ITEMS is not in the main menu (see debug/g_incense_menu.png)")
                    break
                x, y = items[0]
                k = shot.shape[0] / 2208
                spots = [(x, y + int(ITEMS_ICON_DY * k)), (x, y), (x, y + int((ITEMS_ICON_DY - 45) * k))]
            if not spots:
                log("daily incense: tapped every spot of the ITEMS button and the bag did not open")
                break
            x, y = spots.pop(0)
            log(f"daily incense: tapping ITEMS at ({x}, {y})")
            S.tap(x, y)
            tapped += 1
    return None


_ocr_variant = [0]
BAG_OCR_SCALE = 0.6        # the names in the bag list are big: a smaller picture reads them faster


def _bag_image(img, variant):
    if variant == 1:                                 # inverted
        return 255 - img
    if variant == 2:                                 # darkest channel: white text on colour stays white
        return cv2.cvtColor(img.min(axis=2), cv2.COLOR_GRAY2BGR)
    if variant == 3:                                 # local contrast
        g = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    return img


def bag_ocr(img, y0=250):
    """OCR of a bag page. The way of reading that worked on an earlier page is tried first; another
    one is tried only when nothing of the bag can be read."""
    order = [_ocr_variant[0]] + [v for v in range(4) if v != _ocr_variant[0]]
    first = None
    for v in order:
        lines = ocr_lines(_bag_image(img, v), y0, 2150, BAG_OCR_SCALE)
        if first is None:
            first = lines
        if bag_like(lines) or incense_tile(lines):
            _ocr_variant[0] = v
            return lines
    return first


BAG_SWIPE = (1150, 1800, 1150, 700, 900)    # one page down (~1100 px; the list is ~1900 px high, so nothing
                                            # is skipped); slow, so the list does not fly on; away from the X button


def _incense_visit():
    """One visit to the item bag. Returns 'activated', 'absent' (not in the bag) or 'failed'.
    The bag is a long list (medicine, balls, berries ...): the daily incense is not at the top, so
    the list is scrolled page by page; every page is read (OCR) and kept as debug/g_incense_pN.jpg.
    Only a row that reads DAILY ADVENTURE is ever tapped, on its name (the trash can is at the right)."""
    page = _open_bag()
    if not page:
        _bag_to_map()
        return "failed"
    img, lines = page
    save_async("g_incense_bag.png", img)
    lines = bag_ocr(img)
    if len(_words(lines)) < 4 and not (bag_like(lines) or incense_tile(lines)):
        log(f"daily incense: the bag opened but no item names can be read on it ({_reads(lines, 100)}) - "
            "see debug/g_incense_bag.png")
        _bag_to_map()
        return "failed"
    tile, prev, still = None, None, 0
    for i in range(BAG_SCROLLS + 1):
        if i:
            img = S.screenshot()
            lines = bag_ocr(img)
        save_async(f"g_incense_p{i}.jpg", img)
        log(f"daily incense: bag page {i}: {_reads(lines, 100)}")
        if S.on_map(img) or any("DISCARD" in t for t, _, _, _ in lines):
            log("daily incense: the bag is not on the screen any more - stopping")
            _bag_to_map()
            return "failed"
        tile = incense_tile(lines)
        if tile and tile[0] < 1150 and 300 < tile[1] < 1850:       # on its name, clear of the X button
            break
        if prev is not None and not screen_changed(img, prev, 0.003):       # the list did not move
            still += 1
            if still >= 2:                                                   # twice in a row: the end
                break
        else:
            still = 0
        prev = img
        tile = None
        S.swipe(*BAG_SWIPE)
        time.sleep(1.2)
    if not tile:
        log(f"daily incense: last page of the bag reads: {_reads(lines)}")
        save_async("g_incense_bag_end.png", img)
        _bag_to_map()
        return "absent"
    log(f"daily incense: found in the item bag at ({tile[0]}, {tile[1]}) - opening it")
    bag_img = img
    S.tap(*tile)
    time.sleep(2.5)
    img = S.screenshot()
    if S.on_map(img):                                  # used by the tap alone
        log("daily incense: ACTIVATED (the bag closed after the tap)")
        return "activated"
    lines = bag_ocr(img, 100)        # (the card's title is high up: from y=100)
    save_async("g_incense_card.png", img)
    log(f"daily incense: after the tap the screen reads: {_reads(lines, 110)}")
    if any("DISCARD" in t for t, _, _, _ in lines):
        _leave_question("discard", lines)
        _bag_to_map()
        return "failed"
    small = lambda im: cv2.resize(im, (221, 276), interpolation=cv2.INTER_AREA).astype(np.int16)
    unchanged = float((np.abs(small(img) - small(bag_img)).max(axis=2) > 25).mean()) < 0.004
    if unchanged or not incense_card(lines):           # the tap opened nothing
        log("daily incense: the tap did not open the incense (see debug/g_incense_card.png)")
        _bag_to_map()
        return "failed"
    btn = incense_use_button(img, lines)
    if btn:                                            # a USE / ACTIVATE button (not on the usual card)
        log(f"daily incense: tapping {btn} (USE)")
        S.tap(*btn)
        time.sleep(3)
        img = S.screenshot()
        if S.on_map(img) or not incense_card(bag_ocr(img, 100)):
            _bag_to_map()
            return "activated"
    n, shot_n, last, dots = 0, 0, None, []
    for _ in range(2):                                 # a first look at how it sways
        b = find_button(S.screenshot())
        if b:
            dots.append(b)
    while True:
        fresh = S.screenshot()                         # aimed at what the incense looks like RIGHT NOW
        inc = find_incense(fresh)
        if inc and not inc.get("button") and last and last.get("button"):
            inc = dict(inc, button=last["button"])     # (the dot hidden for a moment: use the last one seen)
        if inc is None and last:
            inc = last
        if inc and inc.get("button"):
            dots = (dots + [inc["button"]])[-7:]
            inc = steady_incense(inc, dots, fresh.shape[1] / 1768.0)
        if inc:
            last = inc
        g = incense_gesture(n, fresh, inc)
        if g is None:
            log("daily incense: still on the incense card after every gesture (pictures: debug/g_incense_a1.png ...)")
            break
        what, kind, args = g
        n += 1
        if kind == "skip":
            log(f"daily incense: gesture {n} skipped: {what} (the yellow dot of the button is not visible)")
            continue
        shot_n += 1
        log(f"daily incense: attempt {shot_n}: {what} {args}"
            + ("" if inc else " (incense not found in the picture: usual place)"))
        marked = fresh.copy()
        x1, y1 = (args[0][1], args[0][2]) if kind == "touch" else (args[0], args[1])
        cv2.circle(marked, (x1, y1), 30, (0, 0, 255), 6)
        if kind == "swipe":
            cv2.arrowedLine(marked, (args[0], args[1]), (args[2], args[3]), (0, 0, 255), 6)
        elif kind == "touch":
            cv2.arrowedLine(marked, (x1, y1), (args[-1][1], args[-1][2]), (0, 0, 255), 6)
        save_async(f"g_incense_t{shot_n}.jpg", marked)
        if kind == "tap":
            S.tap(*args)
        elif kind == "swipe":
            S.swipe(*args)
        else:
            try:
                out = S.adb("shell", _touch(args))
            except Exception as e:  # noqa: BLE001
                out = str(e)
            if "rror" in out or "nknown" in out or "Usage" in out:     # never leave the finger 'down'
                log(f"daily incense: touch events failed ({out.strip()[:80]})")
                try:
                    S.adb("shell", *S.INPUT, "motionevent", "UP", *map(str, S.to_real(args[-1][1], args[-1][2])))
                except Exception:  # noqa: BLE001
                    pass
        time.sleep(2.5)
        img = S.screenshot()
        lines = None
        if not S.on_map(img):
            lines = bag_ocr(img, 100)
            if incense_card(lines):
                time.sleep(2.0)                        # lighting it may take a moment before the card closes
                img, lines = S.screenshot(), None
        save_async(f"g_incense_a{shot_n}.png", img)
        if S.on_map(img):
            log("daily incense: ACTIVATED (the card closed, the map is back)")
            return "activated"
        if lines is None:
            lines = bag_ocr(img, 100)
        kind = _screen_kind(img, lines)
        if kind in ("exit", "discard"):
            _leave_question(kind, lines)
            break
        if kind == "bag":                              # the gesture only went back to the bag
            log(f"daily incense: that went back to the bag, not used (see debug/g_incense_a{shot_n}.png)")
            break
        if not incense_card(lines):
            log(f"daily incense: the card is gone (the screen reads: {_reads(lines, 80)}) - "
                f"see debug/g_incense_a{shot_n}.png")
            _bag_to_map()                              # (a reward notice may need a moment: step() clears those)
            return "activated"
    _bag_to_map()
    return "failed"


def use_daily_incense():
    """Called from the map when incense_due(). Keeps the day's state per app in INCENSE_FILE."""
    today = time.strftime("%Y-%m-%d")
    st = incense_state()
    rec = st.get(S.PACKAGE, {})
    if rec.get("date") != today or rec.get("v") != INCENSE_VERSION:
        rec = {"date": today, "v": INCENSE_VERSION, "tries": 0, "done": False, "last": 0}
    rec.update(tries=rec.get("tries", 0) + 1, last=time.time())
    st[S.PACKAGE] = rec
    save_incense_state(st)
    log(f"daily incense: opening the item bag ({S.PACKAGE.split('.')[-1]}, visit {rec['tries']} of {INCENSE_TRIES})")
    try:
        result = _incense_visit()
    except Exception as e:  # noqa: BLE001
        log(f"daily incense: error {e}")
        result = "failed"
    if result == "activated":
        rec["done"] = True
        log("daily incense: ACTIVATED - it burns for 30 minutes (15 in older versions of the game)")
    elif result == "absent":
        rec["done"] = True
        log("daily incense: not in the item bag (already used today, or not unlocked yet) - not looking again today")
    elif rec["tries"] >= INCENSE_TRIES:
        rec["done"] = True
        log("daily incense: did not work - giving up for today (the pictures are in ~/debug, g_incense_*.png)")
    else:
        log(f"daily incense: did not work - trying again in {INCENSE_RETRY // 60} min")
    save_incense_state(st)


def close_game_completely():
    """Stop Pokémon GO and also remove it from the recent apps ('Alle sluiten' / 'Close all'),
    so it is really gone and not running in the background."""
    try:
        S.adb("shell", "am", "force-stop", S.PACKAGE)
        time.sleep(1)
        S.adb("shell", "input", "keyevent", "KEYCODE_APP_SWITCH")   # recent apps
        time.sleep(2.5)
        img = S.screenshot()
        target = None
        for t, x, y, ws in ocr_lines(img, 1100, 2208):
            if "SLUITEN" in t or "CLOSE ALL" in t:
                xs = [wx for w, wx, wy in ws]
                target = (sum(xs) // len(xs), y)
                break
        S.tap(*(target or CLOSE_ALL_BTN))
        time.sleep(2)
        S.adb("shell", "input", "keyevent", "KEYCODE_HOME")
        S.adb("shell", "am", "force-stop", S.PACKAGE)
        log("Pokémon GO closed (also removed from recent apps)")
    except Exception as e:
        log(f"could not close Pokémon GO completely: {e}")


def check_all_full():
    """Pokémon storage AND bag full (option 'close_when_full'): close Pokémon GO.
    The bot keeps running but waits; as soon as you open Pokémon GO again yourself
    (after making room), it carries on."""
    daily = wanted("daily_cycle")
    if not (storage_state["full"] and bag_state["full"] and (daily or wanted("close_when_full"))):
        return
    log("POKÉMON STORAGE AND BAG FULL - closing Pokémon GO and stopping the bot")
    close_game_completely()
    if daily:                                     # daily run: next app / wait for tomorrow
        run_state["done"] = True
        return
    while True:                                   # wait until the game is opened again
        time.sleep(30)
        try:
            if S.adb("shell", "pidof", S.PACKAGE).strip():
                break
        except Exception:                         # pidof finds nothing -> error: still closed
            pass
    storage_state["full"] = False
    bag_state["full"] = False
    global SPIN
    SPIN = True
    log("Pokémon GO opened again - bot continues")
    time.sleep(20)                                # let the game load

def box_full_ball(img):
    """Poké Ball button on the map has a gold centre when the Pokémon storage is full
    (normally grey)."""
    hsv = cv2.cvtColor(img[1920:2050, 820:940], cv2.COLOR_BGR2HSV)
    gold = (hsv[..., 0] >= 12) & (hsv[..., 0] <= 35) & (hsv[..., 1] > 110) & (hsv[..., 2] > 150)
    return int(gold.sum()) > 300


def pause_catching():
    global CATCH
    CATCH = False
    log(f"POKÉMON STORAGE FULL - transfer some Pokémon; catching paused for {STORAGE_FULL_WAIT // 60} min")
    import threading

    def resume():
        global CATCH
        CATCH = True
        log("catching re-enabled")
    threading.Timer(STORAGE_FULL_WAIT, resume).start()


def tray_labels(img):
    """Reads the berry names in the tray with Tesseract (OCR): {(row, column): 'TEXT'}."""
    y0 = 1380
    gray = cv2.cvtColor(img[y0:], cv2.COLOR_BGR2GRAY)
    ok, buf = cv2.imencode(".png", gray)
    try:
        out = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "11", "tsv"], env=OCR["env"],
                             input=buf.tobytes(), capture_output=True, timeout=30).stdout.decode()
    except FileNotFoundError:
        log("tesseract missing (sudo apt install tesseract-ocr) - no berries")
        return {}
    cells = {}
    for r in csv.DictReader(io.StringIO(out), delimiter="\t", quoting=csv.QUOTE_NONE):
        t = (r.get("text") or "").strip().upper()
        if not t or float(r.get("conf") or -1) < 30:
            continue
        cx = int(r["left"]) + int(r["width"]) // 2
        cy = int(r["top"]) + int(r["height"]) // 2 + y0
        col = min(range(3), key=lambda i: abs(TRAY_COLS[i] - cx))
        row = next((i for i, (a, b) in enumerate(TRAY_LABEL_Y) if a <= cy <= b), None)
        if row is not None:
            cells.setdefault((row, col), []).append(t)
    return {k: " ".join(v) for k, v in cells.items()}


def pick_berry(img):
    """Chooses the first available berry from BERRY_ORDER. Never Silver Pinap or Golden Razz."""
    labels = tray_labels(img)
    log(f"berry tray: {sorted(labels.values())}")
    for name in BERRY_ORDER:
        must, never = BERRY_RULES[name]
        for (row, col), text in labels.items():
            if must in text and not (never and never in text):
                return name, (TRAY_COLS[col], TRAY_ICON_Y[row])
    return None



# --------------------------------- gifts -----------------------------------
AVATAR = (150, 1990)               # trainer avatar bottom-left on the map
FRIENDS_TAB = (884, 230)           # FRIENDS tab at the top of the profile
FIRST_GIFT = (340, 850)
SEND_BTN = (860, 1812)                              # SEND, below ADD STICKER
CLOSE_ALL_BTN = (875, 1640)                         # 'Alle sluiten' in recent apps
OPEN_BTN = (860, 1815)                              # OPEN on the received-gift screen
GIFT_SPOTS = [(340, 900), (370, 640), (340, 1150)]   # first gift in "Which Gift do you want to send?"
GIFT_STATE = os.path.expanduser("~/gifts_state.json")
NOT_NAMES = {"SENT", "CAUGHT", "GIFT", "GIFT!", "YOU", "TODAY", "YESTERDAY", "ONLINE", "FRIEND", "FRIENDS",
             "SEARCH", "INVITE", "HATCHED", "EVOLVED", "RAID", "NICKNAME", "LEVEL", "DAYS", "AGO",
             "REMOVE", "REMOTE", "TRADE", "BATTLE", "SETTINGS", "UNKNOWN", "TOTAL", "ACTIVITY"}
TIME_WORDS = re.compile(r"(\d+\+?\s*DAYS?\s*AGO|YESTERDAY|TODAY|\d+\s*H(OURS?)?\s*AGO|JUST NOW)")
gift_timer = {"last": 0.0}


def gift_state_file():
    """One gift memory per Pokémon GO app (each app is its own account)."""
    if S.PACKAGE == "com.nianticlabs.pokemongo":
        return GIFT_STATE
    return GIFT_STATE.replace(".json", "_" + S.PACKAGE.split(".")[-1] + ".json")


def ocr_lines(img, y0=0, y1=None, scale=1.0):
    """OCR with positions: [(TEXT, x_first_word, y, [(word, x, y), ...]), ...] (upper case).
    scale < 1: read a smaller picture (faster; for big letters), positions are still full size.
    (The table Tesseract gives is read without quoting rules: a word that is read as a single double quote
    would otherwise swallow every word after it - a result screen was "not read" that way.)"""
    crop = img[y0:y1]
    if scale != 1.0:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    ok, buf = cv2.imencode(".png", gray)
    try:
        out = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "11", "tsv"], env=OCR["env"],
                             input=buf.tobytes(), capture_output=True, timeout=40).stdout.decode()
    except FileNotFoundError:
        return []
    words = []
    for r in csv.DictReader(io.StringIO(out), delimiter="\t", quoting=csv.QUOTE_NONE):
        t = (r.get("text") or "").strip()
        if t and float(r.get("conf") or -1) >= 40:
            words.append((t.upper(), int((int(r["left"]) + int(r["width"]) / 2) / scale),
                          int((int(r["top"]) + int(r["height"]) / 2) / scale) + y0, int(int(r["height"]) / scale)))
    words.sort(key=lambda w: (w[2], w[1]))
    lines = []
    for w in words:
        if lines and abs(lines[-1][-1][2] - w[2]) < w[3] * 0.7:
            lines[-1].append(w)
        else:
            lines.append([w])
    res = []
    for ws in lines:
        ws.sort(key=lambda w: w[1])
        res.append((" ".join(w[0] for w in ws), ws[0][1], sum(w[2] for w in ws) // len(ws),
                    [(w[0], w[1], w[2]) for w in ws]))
    return res


def ocr_line(img, lines=1):
    """The text of a picture that holds nothing else (black letters on white), as it is written: one line, or
    a few lines under each other (lines > 1) given as one.  '' when nothing is read or the text reader is not
    there."""
    ok, buf = cv2.imencode(".png", img)
    try:
        out = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "7" if lines == 1 else "6"], env=OCR["env"],
                             input=buf.tobytes(), capture_output=True, timeout=20).stdout.decode(errors="replace")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return " ".join(out.split())


def white_words(pic, x0, y0, x1, y1, lines=1, wide=1900.0):
    """The words that stand in pure white in a part of the screen (fractions): the banners of a fight and the
    big words of its result screen are white letters over the picture of the game, where the text reader finds
    little.  Only what is nearly pure white is kept, as black letters on white - then it reads every letter, on
    the small picture of the live video as well.  '' when there is nothing white (or nearly everything is)."""
    h, w = pic.shape[:2]
    zone = pic[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    if zone.size == 0:
        return ""
    white = zone.min(axis=2) >= 215
    if not 0.01 <= float(white.mean()) <= 0.45:           # (no letters at all, or a white screen)
        return ""
    k = wide / zone.shape[1]
    img = cv2.resize(255 - white.astype(np.uint8) * 255, None, fx=k, fy=k,
                     interpolation=cv2.INTER_CUBIC if k > 1 else cv2.INTER_AREA)
    return ocr_line(cv2.copyMakeBorder(img, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255), lines)


def button_label(img, button):
    """The white text on a button of battle_vision.wide_buttons() ('CLAIM RANK REWARDS!', 'LET'S GO!', 'OK'),
    '' when it is not read.  ocr_lines() does not read white letters on a green or orange button.  Here the
    letters are taken out of the button's own box: what is lighter than the button around it (the button is a
    colour gradient, so no fixed threshold), in the middle of the box, as black text on white, read as one line."""
    h, w = img.shape[:2]
    crop = img[int(max(button["y0"] - 0.012, 0.0) * h):int(min(button["y1"] + 0.012, 1.0) * h),
               int(button["x0"] * w):int(button["x1"] * w)]
    if crop.size == 0 or crop.shape[0] < 8:
        return ""
    f = 110.0 / crop.shape[0]                      # (letters of 40 to 60 px: what tesseract reads best)
    crop = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC if f > 1 else cv2.INTER_AREA)
    ch, cw = crop.shape[:2]
    top = cv2.morphologyEx(crop.min(axis=2), cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)))
    zone = np.zeros((ch, cw), bool)                # where the label is: the middle of the button (lower down in
    cut = button["y1"] >= 0.985                    # one that is cut off by the lower edge of the screen)
    zone[int((0.30 if cut else 0.24) * ch):int((0.98 if cut else 0.80) * ch), int(0.08 * cw):int(0.92 * cw)] = True
    thr = max(float(cv2.threshold(top[zone].reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[0]), 18.0)
    text = cv2.copyMakeBorder(np.where((top > thr) & zone, 0, 255).astype(np.uint8), 16, 16, 16, 16,
                              cv2.BORDER_CONSTANT, value=255)
    ok, buf = cv2.imencode(".png", text)
    try:
        out = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "7"], env=OCR["env"], input=buf.tobytes(),
                             capture_output=True, timeout=30).stdout.decode(errors="ignore")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return " ".join(out.upper().split())


def parse_friends(lines, img=None):
    """Friend rows: a name line (with 'Today' / 'Yesterday' / '2+ days ago' ...).
    Gift = 'sent you a Gift!' somewhere in the row (text may wrap over two lines),
    or the pink gift box icon in that row (when the text is not readable)."""
    rows = []
    for i, (text, x, y, ws) in enumerate(lines):
        m = TIME_WORDS.search(text)
        name_w = None
        if m:                                    # "Name   2+ days ago"
            before = [w for w in ws if text.find(w[0]) < m.start()]
            cands = [w for w in before if re.fullmatch(r"[A-Z0-9_]{3,15}", w[0]) and w[0] not in NOT_NAMES]
            name_w = cands[-1] if cands else None
        if name_w is None:                       # "Name" with "Name caught X!" / "Name sent you a Gift!" below
            for w in ws:
                if (re.fullmatch(r"[A-Z0-9_]{4,15}", w[0]) and w[0] not in NOT_NAMES
                        and not re.fullmatch(r"\d+", w[0])) and any(
                        t2.startswith(w[0]) or f" {w[0]} " in f" {t2} "
                        for t2, _, y2, _ in lines[i + 1:i + 4] if 0 < y2 - y < 500):
                    name_w = w
                    break
        if name_w and not (rows and rows[-1][1][0] == name_w[0]):
            rows.append((i, name_w))
    friends = []
    for k, (i, name_w) in enumerate(rows):
        y = name_w[2]
        y_next = rows[k + 1][1][2] if k + 1 < len(rows) else y + 520
        band = [t for t, _, y2, _ in lines if y < y2 < y_next]
        gift = any("SENT YOU" in t or "GIFT!" in t for t in band)
        if not gift and img is not None:
            gift = gift_icon(img, y, min(y_next, y + 520))
        friends.append({"name": name_w[0], "x": name_w[1], "y": y, "gift": gift,
                        "arrow": img is not None and sent_arrow(img, y)})
    return friends


def sent_arrow(img, y):
    """Grey circle with a white arrow at the bottom right of the avatar:
    this friend already has a gift from you (not opened yet) -> nothing to send."""
    region = img[max(y + 90, 0):min(y + 200, H), 320:420]
    if region.size == 0:
        return False
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    grey = (hsv[..., 1] < 40) & (hsv[..., 2] > 95) & (hsv[..., 2] < 180)
    return int(grey.sum()) > 1200


def gift_icon(img, y0, y1):
    """Pink/magenta gift bow in the icon column of a friend row."""
    region = img[max(y0, 0):min(y1, H), 450:900]
    if region.size == 0:
        return False
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    magenta = (hsv[..., 0] >= 140) & (hsv[..., 0] <= 172) & (hsv[..., 1] > 120) & (hsv[..., 2] > 140)
    return int(magenta.sum()) > 1500


def load_gift_state():
    import json
    today = time.strftime("%Y-%m-%d")
    try:
        with open(gift_state_file()) as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    if st.get("day") != today:
        st = {"day": today, "sent": [], "opened": [], "open_blocked": False, "send_blocked": False}
    return st


def save_gift_state(st):
    import json
    with open(gift_state_file(), "w") as f:
        json.dump(st, f)


def any_text(lines, *needles):
    return any(all(n in t for n in needles) for t, *_ in lines)


def is_friend_list(img):
    """Friend list: 'FRIENDS' tab at the top, or friend rows with 'Today'/'days ago'."""
    top = ocr_text(img, 0, 420)
    return "FRIENDS" in top and ("SOCIAL" in top or "ME " in top + " " or "PARTY" in top)


def back_to_list():
    for _ in range(3):
        S.back()
        time.sleep(2.5)
        if is_friend_list(S.screenshot()):
            return True
    return False


def find_pill_button(img, y_min=1500):
    """Green pill button (OPEN / SEND) on the gift screens. The light green background
    there is brighter (V ~255) and paler than the button, so find_green_button() would
    take the whole background for a button."""
    hsv = cv2.cvtColor(img[y_min:], cv2.COLOR_BGR2HSV)
    m = ((hsv[..., 0] >= 45) & (hsv[..., 0] <= 95) & (hsv[..., 1] > 62) &
         (hsv[..., 2] > 170) & (hsv[..., 2] < 248)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    n, _, st, _ = cv2.connectedComponentsWithStats(m)
    best = None
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if 450 < w < 1300 and 80 < h < 320 and w > 2.5 * h and abs(x + w // 2 - 884) < 300 \
                and (best is None or a > best[2]):
            best = (int(x + w // 2), int(y + h // 2 + y_min), int(a))
    return best


def send_button(img):
    """SEND button on the 'send this gift' screen. It sits right below the ADD STICKER
    button; that label is dark text on white and reads reliably, the SEND label is not."""
    if has_sticker_button(img):
        return SEND_BTN
    return find_pill_button(img)


def has_sticker_button(img):
    return "STICKER" in ocr_text(img, 1480, 1680)


def is_gift_screen(img):
    """Gift screen (OPEN or SEND): the big pink bow of the present at the top centre."""
    hsv = cv2.cvtColor(img[150:900, 400:1400], cv2.COLOR_BGR2HSV)
    bow = (hsv[..., 0] >= 140) & (hsv[..., 0] <= 172) & (hsv[..., 1] > 120) & (hsv[..., 2] > 120)
    return int(bow.sum()) > 40000


def visit_friend(f, want_open, want_send, st):
    name = f["name"]
    S.tap(f["x"], f["y"])
    time.sleep(3.5)
    img = S.screenshot()

    if f["gift"] or is_gift_screen(img):           # tapping a friend with a gift opens the gift
        btn = find_pill_button(img) or (OPEN_BTN if is_gift_screen(img) else None)
        if want_open and btn:
            S.tap(btn[0], btn[1])                  # OPEN
            time.sleep(6)
            img = S.screenshot()
            save_async("g_gift_opened.png", img)
            lines = ocr_lines(img)
            if is_gift_screen(img) and not any_text(lines, "LIMIT"):
                log(f"gifts: tapped OPEN for {name} but the gift screen is still open")
                S.back()
                time.sleep(2)
            elif any_text(lines, "MAXIMUM") or any_text(lines, "LIMIT") or any_text(lines, "BAG", "FULL"):
                log("gift limit reached or bag full - no more opening today")
                st["open_blocked"] = True
                S.back()
                time.sleep(2)
            else:
                st["opened"].append(name)
                log(f"gift from {name} opened ✔")
                for _ in range(2):                 # skip the item overview
                    S.tap(*S.CENTER)
                    time.sleep(2)
        else:
            S.back()                               # do not open: close the gift screen
            time.sleep(2.5)

    if want_send:
        # scroll the profile down to the SEND GIFT / TRADE buttons in small, slow steps
        # (a fast swipe flings the page too far). Swipe on the empty right side: a drag
        # on the trainer only rotates the avatar.
        def button_y(ls):
            for _, _, _, ws in ls:
                for w, wx, wy in ws:
                    if w == "SEND" or w.startswith("TRADE"):
                        return wy
            return None

        lines, img = [], None
        for _ in range(10):
            img = S.screenshot()
            lines = ocr_lines(img, 0, 2208)
            by = button_y(lines)
            if by is not None and by < 450:          # buttons too high (icon cut off): scroll back up
                S.swipe(1550, 900, 1550, 1300, 1000)
                time.sleep(2)
                continue
            if by is not None or any_text(lines, "GIFT", "SENT"):
                break
            S.swipe(1550, 1700, 1550, 1200, 1000)
            time.sleep(2)
        else:
            log(f"gifts: SEND GIFT button not found on the profile of {name}")
        save_async("g_friend_profile.png", img)
        if any_text(lines, "GIFT", "SENT"):
            st["sent"].append(name)
        else:
            target = None
            for t, x, y, ws in lines:
                for w, wx, wy in ws:
                    if w == "SEND" or w.startswith("TRADE"):
                        target = (336, wy - 140)   # icon above the SEND GIFT label (left column)
                        break
                if target:
                    break
            near_remove = target and any("REMOVE" in t and abs(y - target[1]) < 300 for t, x, y, _ in lines)
            sendable = False
            if target:
                # coloured gift icon = you can send; grey icon = already sent today / not possible
                tx, ty = target
                icon = cv2.cvtColor(img[max(ty - 120, 0):ty + 110, max(tx - 136, 0):tx + 134], cv2.COLOR_BGR2HSV)
                magenta = ((icon[..., 0] >= 140) & (icon[..., 0] <= 172) & (icon[..., 1] > 100) & (icon[..., 2] > 120)).sum()
                sendable = magenta > 1500
                if not sendable:
                    log(f"cannot send a gift to {name} right now (icon grey) - skipping today")
                    st["sent"].append(name)
            if target and sendable and not near_remove:
                S.tap(*target)
                time.sleep(3)
                img = S.screenshot()
                lines = ocr_lines(img, 150, 500)
                if any_text(lines, "WHICH", "GIFT"):
                    time.sleep(2)                  # let the gift list finish its animation
                    btn = None
                    for gx, gy in GIFT_SPOTS:      # postcard, bow, place name of the first gift
                        S.tap(gx, gy, ms=200)
                        time.sleep(3)
                        img = S.screenshot()
                        btn = send_button(img)
                        if btn:
                            break
                        save_async("g_gift_select.png", img)
                    if not btn:
                        save_async("g_send_nobutton.png", img)
                        log(f"gifts: SEND button not found for {name}")
                        S.back()
                        time.sleep(2)
                    else:
                        S.tap(btn[0], btn[1])      # SEND
                        time.sleep(6)
                        img = S.screenshot()
                        if has_sticker_button(img):
                            save_async("g_send_stuck.png", img)
                            log(f"gifts: tapped SEND for {name} but the send screen is still open")
                            S.back()
                            time.sleep(2)
                        else:
                            st["sent"].append(name)
                            log(f"gift sent to {name} ✔")
                else:
                    save_async("g_send_failed.png", img)
                    full = ocr_lines(img)
                    if any_text(full, "NO", "GIFT") or any_text(full, "DON'T HAVE"):
                        log("no gifts left to send - stopping for today")
                        st["send_blocked"] = True
                    else:
                        log(f"could not send a gift to {name} (already sent today?)")
                        st["sent"].append(name)    # do not retry this friend today
                    S.back()
                    time.sleep(2)
    save_gift_state(st)
    back_to_list()


def gifts_round():
    st = load_gift_state()
    want_open = wanted("gifts_open") and not st["open_blocked"]
    want_send = wanted("gifts_send") and not st["send_blocked"]
    if not (want_open or want_send):
        return
    log("gifts: checking friend list")
    S.tap(*AVATAR)
    time.sleep(3)
    S.tap(*FRIENDS_TAB)
    time.sleep(3)
    img = S.screenshot()
    save_async("g_gifts_start.png", img)
    if not is_friend_list(img):
        log("gifts: friend list not found - aborting (see debug/g_gifts_start.png)")
        for _ in range(3):
            S.back(); time.sleep(2)
        return
    seen, idle_scrolls = set(), 0
    for _ in range(60):
        img = S.screenshot()
        if not is_friend_list(img):                # e.g. still on a profile: go back first
            if not back_to_list():
                log("gifts: lost the friend list - aborting")
                break
            img = S.screenshot()
        friends = parse_friends(ocr_lines(img, 380, 2050), img)
        todo = None
        new_names = False
        for f in friends:
            if f["name"] in seen:
                continue
            seen.add(f["name"])
            new_names = True
            o = want_open and not st["open_blocked"] and f["gift"]
            # a friend with an unopened gift is only visited when opening is on
            # (tapping that friend always opens the gift screen first)
            snd = (want_send and not st["send_blocked"] and f["name"] not in st["sent"]
                   and not f["arrow"] and (not f["gift"] or o))
            if want_send and f["arrow"] and not o:
                log(f"gifts: {f['name']} already has a gift from you (arrow) - not visiting")
            if o or snd:
                todo = (f, o, snd)
                break
        if todo:
            idle_scrolls = 0
            visit_friend(*todo, st)
            continue
        # only stop when scrolling shows no new friends any more (end of the list)
        idle_scrolls = 0 if new_names else idle_scrolls + 1
        if idle_scrolls > 1:
            break
        S.swipe(884, 1800, 884, 900, 700)          # scroll the friend list
        time.sleep(2)
    log(f"gifts: done (today: {len(st['opened'])} opened, {len(st['sent'])} sent)")
    for _ in range(4):                              # back to the map
        S.back()
        time.sleep(2.5)
        if S.on_map(S.screenshot()):
            break


# ---------------------- curveball + Nice/Great/Excellent ----------------------
# Ring size = coloured target ring / white ring (1.0 = full size, 0 = smallest).
# Nice 0.7-1.0, Great 0.3-0.7, Excellent < 0.3. The ring only shrinks while the ball is
# held, keeps its size when the ball is let go and freezes when the ball is thrown.
THROW_TARGETS = {"nice": 0.85, "great": 0.50, "excellent": 0.20}
TOUCH_SHOT = 0.25             # s after the finger goes down the screenshot of the ring is taken
CURVE_SPINS = 2.5             # circles (clockwise) before a curveball
CURVE_RADIUS = 140            # px, radius of the spin circle
CURVE_D = 400                 # px left of the middle from where a curveball is thrown
CURVE_LAND = 280              # thrown straight up from there it lands this many px right of the middle
CURVE_LEAN_GAIN = 2.35        # px the landing point moves per px the throw leans sideways
CURVE_LEAN_MAX = 330
CURVE_POWER = 1.0             # > 1 = longer (harder) curveball throw
CAL_FILE = os.path.expanduser("~/gamebot_throw.json")
CAL_VERSION = 5
RING_SPEED = 0.55             # the ring shrinks this much per second of holding (cycle ~1.8 s)
cal = {"k": RING_SPEED,       # ring shrink per second of holding
       "c": 0.3,              # s between asking for a screenshot and the moment it is taken (learned)
       "lat": 55.0,           # ms per injected touch event (learned)
       "rel": 0.3,            # s the throw itself takes (learned)
       "aim": 0.0,            # px correction of the curveball landing point (learned)
       "obs": [],             # last throws: (ring measured, s until release, ring at release)
       "c_live": -0.12,       # the same as c for a picture of the live video: it came in a little after it was taken
       "obs_live": []}        # ... and the throws that were timed with the live video
RING_TRACK_S = 0.8            # s the ring is followed in the live video before the throw is timed
RING_TRACK_EVERY = 0.1        # s at least between two pictures of the ring


def load_cal():
    import json
    try:
        with open(CAL_FILE) as f:
            data = json.load(f)
        if data.get("v") == CAL_VERSION:          # values learned with an older method are dropped
            cal.update({k: v for k, v in data.items() if k in cal})
    except (OSError, ValueError):
        pass


def save_cal():
    import json
    try:
        with open(CAL_FILE, "w") as f:
            json.dump(dict(cal, v=CAL_VERSION), f)
    except OSError:
        pass


def _edge_points(crop):
    """Strong colour edges in the crop: positions and unit gradient directions."""
    f = cv2.GaussianBlur(crop, (0, 0), 1.2).astype(np.float32)
    gx = cv2.Sobel(f, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(f, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(gx ** 2 + gy ** 2)
    ch = mag.argmax(axis=2)                       # per pixel: the colour channel with the strongest edge
    ii, jj = np.indices(ch.shape)
    gx, gy, mag = gx[ii, jj, ch], gy[ii, jj, ch], mag[ii, jj, ch]
    thr = max(float(np.percentile(mag, 80)), 18.0)
    ys, xs = np.nonzero(mag > thr)
    m = mag[ys, xs]
    return xs.astype(np.float32), ys.astype(np.float32), gx[ys, xs] / m, gy[ys, xs] / m


def _circle_profile(pts, cx, cy, rmax, band, n_theta=72):
    """Per radius: the share of directions with an edge that runs along a circle around (cx, cy)."""
    xs, ys, ux, uy = pts
    dx, dy = xs - cx, ys - cy
    r = np.sqrt(dx ** 2 + dy ** 2) + 1e-6
    ok = (r < rmax) & (np.abs((dx * ux + dy * uy) / r) > 0.85)     # gradient points along the radius
    ri = r[ok].astype(np.int32)
    ti = ((np.arctan2(dy[ok], dx[ok]) + np.pi) / (2 * np.pi) * n_theta).astype(np.int32) % n_theta
    hit = np.zeros((int(rmax) + 1, n_theta), np.uint8)
    hit[ri, ti] = 1
    if band:
        hit = cv2.dilate(hit, np.ones((2 * band + 1, 1), np.uint8))
    return hit.mean(axis=1)


RING_LINE_MAX = 30            # px: the ring line is thin; thicker coloured bands are the Pokémon


def _ring_colour_mask(crop):
    """Pixels with the bright, saturated colour of the shrinking ring (green, yellow, orange, red)."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    return (((h <= 82) | (h >= 170)) & (s > 95) & (v > 165)).astype(np.uint8)


def _polar_cov(mask, cx, cy, rmax, band, n_theta=120):
    """Per radius: the share of directions in which the mask is set (within +-band px)."""
    polar = cv2.warpPolar(mask, (int(rmax), n_theta), (float(cx), float(cy)), float(rmax),
                          cv2.WARP_POLAR_LINEAR | cv2.INTER_NEAREST)
    if band:
        polar = cv2.dilate(polar, np.ones((1, 2 * band + 1), np.uint8))
    return polar.mean(axis=0)


def _colour_ring(mask, cx, cy, rmax, r_lo):
    """The coloured ring around (cx, cy): a thin circle that is coloured (almost) all the way
    round while it is not coloured just inside and just outside it. Returns (score, radius)."""
    cov = _polar_cov(mask, cx, cy, rmax, 2)
    best = (0.0, None)
    for r in range(int(r_lo), len(cov) - 1):
        if cov[r] < 0.7:
            continue
        g = max(int(r * 0.12), 10)
        inner = cov[max(r - 2 * g, 0):max(r - g, 1)].mean()
        outer = cov[min(r + g, len(cov) - 1):min(r + 2 * g, len(cov))].mean()
        score = float(cov[r] - max(inner, outer))
        if score > best[0]:
            best = (score, r)
    if best[1] is None:
        return best
    r = best[1]                                    # middle of the line
    a = b = r
    while a - 1 > 0 and cov[a - 1] >= 0.6 * cov[r]:
        a -= 1
    while b + 1 < len(cov) and cov[b + 1] >= 0.6 * cov[r]:
        b += 1
    if b - a > RING_LINE_MAX:                      # too thick for the ring line: part of the Pokémon
        return 0.0, None
    return best[0], (a + b) / 2


ring_diag = {}                                     # why the last measure_ring failed (for the log)


def measure_ring(img, box):
    """Size of the coloured (shrinking) ring relative to the white ring, both thin circles
    around the Pokémon. box = the detector's box of the white ring (only found while the
    rings are visible). Returns dict(ratio, rw, rc, cx, cy, q) or None."""
    ring_diag.clear()
    _, _, bx, by, bw, bh = box
    r0 = max(bw, bh) / 2
    if r0 < 40:
        return None
    pad = int(r0 * 1.5)
    x0, y0 = max(int(bx - pad), 0), max(int(by - pad), 0)
    crop = img[y0:int(by + pad), x0:int(bx + pad)]
    if crop.shape[0] < 80 or crop.shape[1] < 80:
        return None
    # 1. the white ring (edges on a circle about as big as the box): centre and radius
    pts = _edge_points(crop)
    rmax = int(r0 * 1.3)
    band = max(int(r0 * 0.02), 2)
    step = max(int(r0 * 0.03), 2)
    lo, hi = int(r0 * 0.78), int(r0 * 1.12)
    # only edges that can belong to that ring, and not more than needed (speed on the Pi)
    dist = np.hypot(pts[0] - (bx - x0), pts[1] - (by - y0))
    keep = np.nonzero((dist > r0 * 0.6) & (dist < r0 * 1.3))[0]
    if len(keep) > 9000:
        keep = keep[::len(keep) // 9000 + 1]
    pts = tuple(a[keep] for a in pts)

    def white_fit(cx, cy):
        prof = _circle_profile(pts, cx, cy, rmax, band)
        top = float(prof[lo:hi].max())
        r = lo + int(np.nonzero(prof[lo:hi] >= 0.85 * top)[0].max())   # the outermost circle
        return float(prof[r]), r, cx, cy

    best = max(white_fit(bx - x0 + dx * 2 * step, by - y0 + dy * 2 * step)
               for dx in range(-2, 3) for dy in range(-2, 3))            # coarse ...
    best = max(white_fit(best[2] + dx * step, best[3] + dy * step)
               for dx in (-1, 0, 1) for dy in (-1, 0, 1))                # ... then fine
    ring_diag["white"] = round(best[0], 2)
    if best[0] < 0.6:
        return None
    _, rw, cx, cy = best
    # 2. the coloured ring: same centre (fine-tuned), anywhere from tiny to the white ring
    mask = _ring_colour_mask(crop)
    bestc = (0.0, None, cx, cy)
    for span, st in ((2, 7), (1, 3)):              # coarse search, then fine around the best
        ox, oy = bestc[2], bestc[3]
        for dx in range(-span, span + 1):
            for dy in range(-span, span + 1):
                sc, rc = _colour_ring(mask, ox + dx * st, oy + dy * st, rw * 1.15, max(rw * 0.04, 5))
                if rc is not None and sc > bestc[0]:
                    bestc = (sc, rc, ox + dx * st, oy + dy * st)
    sc, rc, ccx, ccy = bestc
    ring_diag.update(colour=round(sc, 2), size=round(rc / rw, 2) if rc else None)
    if rc is None or sc < 0.6:
        return None
    return {"ratio": float(min(rc / rw, 1.0)), "rw": int(rw), "rc": int(rc),
            "cx": int(ccx + x0), "cy": int(ccy + y0), "q": round(sc, 2)}


ring_shots = {"n": 0}


def _circ(a, b):
    """Signed distance a - b on the ring-size circle (the ring jumps from 0 back to 1)."""
    return (a - b + 0.5) % 1.0 - 0.5


def refit_timing(live=False):
    """Learn from the last throws: the ring at release must equal
    measured - k * (seconds between the screenshot and the release - c). c (moment the
    screenshot is really taken) is fitted from the first throw on, the shrink speed k as
    soon as there are enough throws. live: the throws timed with the live video (their own c)."""
    obs = cal["obs_live" if live else "obs"][-16:]
    if not obs:
        return
    r, t, g = (np.array([o[i] for o in obs]) for i in range(3))
    ks = np.arange(0.35, 0.801, 0.01) if len(obs) >= 6 and np.ptp(t) >= 0.6 else np.array([cal["k"]])
    cs = np.arange(-0.3, 1.21, 0.02)
    keep = max(int(len(obs) * 0.75), 1)           # ignore the worst quarter (e.g. an attack froze the ring)
    best = None
    for k in ks:
        pred = (r[None, :] - k * (t[None, :] - cs[:, None])) % 1.0
        res = np.abs((g[None, :] - pred + 0.5) % 1.0 - 0.5)
        cost = np.sort(res, axis=1)[:, :keep].mean(axis=1)
        i = int(cost.argmin())
        if best is None or cost[i] < best[0]:
            best = (float(cost[i]), float(k), float(cs[i]))
    cal["k"], cal["c_live" if live else "c"] = best[1], best[2]


def ring_track(brain, first, t_first=None):
    """Follow the ring in the live video for a moment while the ball is held: [(clock time, ring size)] of the
    pictures where it could be measured, and the detector's box of the ring (found on the first picture).
    Empty when the video does not run or no ring is seen."""
    wall = lambda t: time.time() - (time.monotonic() - t)     # noqa: E731  (clock time of a picture of the video)
    frames = [(wall(t_first) if t_first else time.time(), first)] + [(wall(t), im)
                                       for t, im in S.live_frames(RING_TRACK_S, RING_TRACK_EVERY)]
    rings = [o for o in brain.encounter_objects(first)
             if o[0] == "boundingBox" and o[1] >= TH_RING and o[3] < BALL_XY[1] - 300]
    if not rings:
        return [], None
    out = []
    for t, im in frames:
        m = measure_ring(im, rings[0])
        if m:
            out.append((t, float(m["ratio"])))
    return out, rings[0]


def ring_speed(points):
    """The shrink speed of the ring (size per second) from pictures taken one after another, or None. The ring
    shrinks from 1 to 0 and starts again: only steps that go down count."""
    steps = [((r0 - r1) / (t1 - t0)) for (t0, r0), (t1, r1) in zip(points, points[1:])
             if t1 - t0 >= 0.05 and 0 < r0 - r1 < 0.6]
    if len(steps) < 2:
        return None
    k = float(np.median(steps))
    return k if 0.25 <= k <= 1.0 else None


def save_async(name, img):
    """Write a debug screenshot in the background (takes about a second on the Pi)."""
    threading.Thread(target=S.debug_save, args=(name, img), daemon=True).start()


def _touch(events):
    """Shell line (runs on the phone) that sends touch events one after another."""
    ip = " ".join(S.INPUT)                          # 'input', or the faster 'cmd input' (see S.probe_input)

    def one(a, x, y):
        if a == "SLEEP":
            return f"sleep {x:.2f}"
        rx, ry = S.to_real(x, y)                    # canvas coordinates -> real screen
        return f"{ip} motionevent {a} {rx} {ry}"
    return "{ " + "; ".join(one(a, x, y) for a, x, y in events) + "; } 2>&1"


def spin_points():
    """Clockwise circles next to the ball, ending on their left side (from there the ball is thrown)."""
    cx, cy = W // 2 - CURVE_D + CURVE_RADIUS, min(BALL_XY[1] - 60, H - CURVE_RADIUS - 60)
    n = int(round(CURVE_SPINS * 8))               # 8 points per circle
    return [(int(cx + CURVE_RADIUS * np.cos(i * np.pi / 4)), int(cy + CURVE_RADIUS * np.sin(i * np.pi / 4)))
            for i in range(n + 1)]


def curve_lean(target_x):
    """Sideways px of the throw so that the curveball lands at screen x = target_x.
    Measured on this phone: thrown straight up from CURVE_D px left of the middle the ball
    curves back and lands CURVE_LAND px right of the middle; every px the throw leans
    sideways moves the landing point CURVE_LEAN_GAIN px. cal['aim'] is what the bot has
    learned on top of that from watching its own throws."""
    t = (W // 2 if target_x is None else target_x) - W // 2
    lean = (t - CURVE_LAND - cal["aim"]) / CURVE_LEAN_GAIN
    return int(min(max(lean, -CURVE_LEAN_MAX), CURVE_LEAN_MAX))


def find_ball(img, before):
    """The flying ball in a screenshot: a red blob that was not there before the throw.
    Returns (x, y, area) or None."""
    def red(im):
        hsv = cv2.cvtColor(im[:1560], cv2.COLOR_BGR2HSV)
        return (((hsv[..., 0] < 8) | (hsv[..., 0] > 172)) & (hsv[..., 1] > 150) & (hsv[..., 2] > 110)).astype(np.uint8)
    m = red(img) & ~cv2.dilate(red(before), np.ones((41, 41), np.uint8)).astype(bool)
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    n, _, st, cen = cv2.connectedComponentsWithStats(m)
    balls = [(int(st[i, 4]), int(cen[i][0]), int(cen[i][1])) for i in range(1, n)
             if 700 <= st[i, 4] <= 26000 and st[i, 1] > 150 and 0.5 < st[i, 2] / max(st[i, 3], 1) < 2.2]
    if not balls:
        return None
    a, x, y = max(balls)
    return x, y, a


def watch_flight(before, ring):
    """Screenshots while the ball flies. Returns (first screenshot, x where the ball came down
    next to the Pokémon or None)."""
    if S.live_stream() is not None:               # the live video: a picture every tenth of a second
        time.sleep(0.15)
        imgs = [im for _t, im in S.live_frames(1.0, 0.12)][:8]
        if imgs:
            return _landing(imgs, before, ring)
    shots = []
    with ThreadPoolExecutor(4) as pool:
        time.sleep(0.2)
        for _ in range(4):
            shots.append(pool.submit(S.screenshot))
            time.sleep(0.16)
        imgs = []
        for f in shots:
            try:
                imgs.append(f.result(timeout=20))
            except Exception:  # noqa: BLE001
                pass
    if not imgs:
        return None, None
    return _landing(imgs, before, ring)


def _landing(imgs, before, ring):
    """(first picture, x where the ball came down next to the Pokémon or None)."""
    land_x = None
    if ring:
        _, _, cx, cy, bw, bh = ring
        want_y = cy - 0.4 * bh                    # the ball comes down onto the Pokémon from above
        seen = [b for b in (find_ball(im, before) for im in imgs) if b]
        near = [b for b in seen if abs(b[1] - want_y) < 380]
        if near:
            land_x = min(near, key=lambda b: abs(b[1] - want_y))[0]
    return imgs[0], land_x


throw_stats = {"n": 0, "on": 0}   # timed throws and how many got the ring size that was wanted (for the log)


def throw_touch(brain, curve, target, target_name, aim_dx=0, power=1.0):
    """One throw as a single touch: finger down (the target ring appears), look at the ring
    while the ball is held / spun, wait until the ring has the wanted size and throw.
    Returns the clock time of the release, or None when this phone cannot send single
    touch events."""
    t_touch = time.time()
    start = [("DOWN", *BALL_XY)] + ([("MOVE", x, y) for x, y in spin_points()] if curve else [])
    hand = start[-1][1:]                          # where the finger rests after this
    spin = subprocess.Popen(["adb", "shell", _touch(start)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    ring = measured = t_shot = before = None
    t_grab = t_find = 0.0                         # where does the time of the hold go? (for the log)
    k_now, live_timed = cal["k"], False           # (the speed of the ring for this throw)
    time.sleep(TOUCH_SHOT)
    try:
        if target is not None and S.live_stream() is not None:    # the live video: follow the ring for a moment
            t_s = time.time()
            img = S.quick_screenshot()
            t_grab += time.time() - t_s
            if S.quick_screenshot.live:
                before = img
                t_f = time.time()
                points, box = ring_track(brain, img, S.quick_screenshot.t)
                t_find += time.time() - t_f
                if box is not None:
                    ring = box
                if points:
                    t_shot, measured = points[-1]
                    live_timed = True
                    k = ring_speed(points)
                    if k is not None:
                        k_now = 0.5 * k + 0.5 * cal["k"]
                    log(f"  ring followed in the live video: {len(points)} pictures, size {points[0][1]:.2f} -> "
                        f"{measured:.2f}" + (f", speed {k:.2f}/s" if k is not None else ""))
        for attempt in range(0 if live_timed else 2):   # screenshots - 2nd look: no ring seen / not readable (yet)
            t_s = time.time()
            img = S.quick_screenshot()
            t_grab += time.time() - t_s
            before = img
            t_f = time.time()
            rings = [o for o in brain.encounter_objects(img)
                     if o[0] == "boundingBox" and o[1] >= TH_RING and o[3] < BALL_XY[1] - 300]
            if rings:
                ring = rings[0]
                m = measure_ring(img, ring) if target is not None else None
                if m:
                    measured, t_shot = m["ratio"], t_s
                    if S.quick_screenshot.live:   # (a picture of the video: its own moment and its own c)
                        t_shot, live_timed = time.time() - (time.monotonic() - S.quick_screenshot.t), True
                elif target is not None:
                    save_async(f"g_ring_unreadable_{attempt + 1}.png", img)   # to see afterwards why it could not be read
                    d = dict(ring_diag)
                    log(f"  ring attempt {attempt + 1} not readable ({t_s - t_touch:.2f} s after touch-down; white ring "
                        f"fit {d.get('white')}, coloured ring score {d.get('colour')}, size {d.get('size')})")
            elif target is not None:
                log(f"  ring attempt {attempt + 1}: no ring found ({t_s - t_touch:.2f} s after touch-down)")
            t_find += time.time() - t_f
            if ring and (target is None or measured is not None):
                break
    except Exception:                             # never leave the finger 'down'
        spin.communicate(timeout=30)
        subprocess.Popen(["adb", "shell", *S.INPUT, "motionevent", "UP", *map(str, S.to_real(*hand))])
        raise
    ring_shots["n"] = ring_shots["n"] % 6 + 1      # keep the last 6: g_ring_1.png ... g_ring_6.png
    save_async(f"g_ring_{ring_shots['n']}.png", before)

    t_w = time.time()
    out = spin.communicate(timeout=30)[0].decode(errors="ignore")
    t_spin = time.time() - t_w                    # how long the spin was still going after the ring was read
    if "rror" in out or "nknown" in out or "Usage" in out:
        try:                                      # never leave the finger 'down'
            S.adb("shell", *S.INPUT, "motionevent", "UP", *map(str, S.to_real(*hand)))
        except Exception:  # noqa: BLE001
            pass
        log(f"single touch events not possible on this phone ({out.strip()[:80]}) - using simple throws")
        cal["no_curve"] = True
        return None

    if ring:
        _, sc, cx, cy, bw, bh = ring
        dy, dur = brain.throw_params(cx, cy, bw, bh)
        tx = cx
        log(f"target ring ({cx}, {cy}, {bw}x{bh}) [{sc:.2f}] -> deltaY {dy:.0f}, {dur:.0f} ms")
    else:
        dy, dur = THROW_FALLBACK
        tx = W // 2
        log("target ring not found - default throw")
    tx, dy = tx + aim_dx, dy * power              # 'realistic throwing': not dead centre every time
    dur_ms = max(int(dur * THROW_BOOST), 60)
    steps = int(min(max(round(dur_ms / max(cal["lat"], 5.0)), 2), 8))
    lean = curve_lean(tx) if curve else 0
    if curve:
        end = (hand[0] + lean, max(int(hand[1] + dy * CURVE_POWER), 50))
    else:
        end = (tx, max(int(BALL_XY[1] + dy), 50))
    end = (min(max(end[0], 20), W - 20), end[1])
    path = [(hand[0] + (end[0] - hand[0]) * (i + 1) / steps, hand[1] + (end[1] - hand[1]) * (i + 1) / steps)
            for i in range(steps)]
    release = [("MOVE", x, y) for x, y in path[:-1]] + [("UP", *path[-1])]

    c_now = cal["c_live"] if live_timed else cal["c"]

    def ring_at(t):                               # ring size at clock time t
        return (measured - k_now * (t - t_shot - c_now)) % 1.0

    expect = None
    wait = 0.0
    if measured is not None:
        diff = (ring_at(time.time() + cal["rel"]) - target) % 1.0
        if diff > 0.93:                           # already just below the target: throw now
            diff -= 1.0
        wait = max(diff, 0.0) / k_now
        log(f"throw target {target_name}: ring measured {measured:.2f}, holding {wait:.2f} s more")
        time.sleep(wait)
    elif target is not None:
        log("throw target: ring not readable - throwing without timing (NOT on purpose)")

    t_b = time.time()
    try:
        S.adb("shell", _touch(release))
    except Exception as e:  # noqa: BLE001
        log(f"throw failed: {e}")
    t_rel = time.time()
    cal["rel"] = 0.7 * cal["rel"] + 0.3 * (t_rel - t_b)
    cal["lat"] = 0.7 * cal["lat"] + 0.3 * 1000 * (t_rel - t_b) / (len(release) + 1)
    if measured is not None:
        expect = ring_at(t_rel)
    log(("curveball" if curve else "ball") + f" thrown from x={hand[0]} towards x={int(end[0])} "
        f"(held {t_rel - t_touch:.1f} s, throw in {steps} steps)")
    log(f"  hold time: {'live video' if live_timed else 'screenshot'} {t_grab:.1f} s + ring search {t_find:.1f} s + "
        f"spin still going {t_spin:.1f} s + ring wait {wait:.1f} s + release {t_rel - t_b:.1f} s")

    first, land_x = watch_flight(before, ring)     # where does the ball go, and how big was the ring?
    if first is not None and expect is not None:
        m = measure_ring(first, ring)
        if m:
            got = m["ratio"]
            kind = "Excellent" if got < 0.3 else "Great" if got < 0.7 else "Nice"
            log(f"ring at release {got:.2f} ({kind} size, wanted {target:.2f}, expected {expect:.2f})")
            key = "obs_live" if live_timed else "obs"
            cal[key] = (cal[key] + [[round(float(measured), 3), round(t_rel - t_shot, 3), round(float(got), 3)]])[-16:]
            refit_timing(live_timed)
            throw_stats["n"] += 1
            throw_stats["on"] += kind.lower() == str(target_name).lower()
            if throw_stats["n"] % 10 == 0:
                log(f"throws timed: {throw_stats['on']} of the last {throw_stats['n']} hit the wanted ring size "
                    f"(ring speed {cal['k']:.2f}/s)")
                throw_stats.update(n=0, on=0)
    if land_x is not None and ring:
        err = land_x - ring[2]
        aimed = err - aim_dx                      # compared with where this throw was meant to go
        side = "left" if err < 0 else "right"
        hit_r = HIT_SHARE * ring[4]
        throw_info["hit"] = abs(err) <= 0.85 * hit_r          # a clear hit, not one on the edge
        verdict = ""
        if abs(err) > hit_r:
            verdict = " - MISSED the Pokémon" + (" (on purpose, as planned)" if abs(aim_dx) > hit_r else " (NOT on purpose)")
        elif abs(aim_dx) > hit_r:
            verdict = " - planned miss, but it landed on the Pokémon"
        # learn from a throw only when it could go where it was meant to: not a deliberately
        # sloppy one and not one that was already leaning as far as it can
        learn = curve and abs(aimed) > 70 and abs(aim_dx) <= 2.5 * REAL_AIM and abs(lean) < CURVE_LEAN_MAX
        if learn:
            step_px = 0.3 * min(max(aimed, -300), 300)
            cal["aim"] = float(min(max(cal["aim"] + min(max(step_px, -100), 100), -700), 700))
            log(f"ball came down {abs(err)} px {side} of the Pokémon (meant {aim_dx:+d}){verdict} - adjusting the aim "
                f"by {step_px:+.0f} px (correction now {cal['aim']:.0f} px)")
        else:
            log(f"ball came down {abs(err)} px {side} of the Pokémon" + (f" (meant {aim_dx:+d})" if aim_dx else "") + verdict)
    save_cal()
    return t_rel


# 'Realistic throwing': a person does not throw the same perfect ball every time.
# There are no real statistics on how well players throw; the mix below follows what
# experienced players say about themselves (most throws on target, some a level lower,
# now and then a sloppy one).
REAL_BASE = "great"           # what the 'Realistic' profile goes for
REAL_KEEP = 0.70              # share of throws that go for the chosen target (Nice/Great/Excellent)
REAL_LOWER = 0.20             # ... that end up one level lower (the rest: no ring timing at all)
REAL_BANDS = {"nice": (0.75, 0.95), "great": (0.36, 0.64), "excellent": (0.12, 0.26)}   # ring size aimed for
REAL_LOWER_OF = {"excellent": "great", "great": "nice", "nice": "off"}
REAL_CURVE = 0.92             # share of throws that are curveballs (when curveballs are on)
REAL_AIM = 45                 # px: normal spread of where the ball is aimed
REAL_SLOPPY = (0.07, 220)     # now and then (share) a sloppy throw with this spread in px
REAL_POWER = 0.03             # spread of the throw length (3 %)
REAL_PAUSE = (0.3, 1.6)       # s: short pause before a throw ...
REAL_LONG_PAUSE = (0.06, 2.5, 6.0)   # ... and now and then (share) a longer one of 2.5-6 s


HIT_SHARE = 0.35              # a ball that lands within this share of the ring width from the middle is on the Pokémon


def aim_note(aim_dx, ring_w=460):
    """For the log: what the deliberate sideways offset of a 'realistic' throw means."""
    side = "right" if aim_dx > 0 else "left"
    if abs(aim_dx) > HIT_SHARE * ring_w:
        return f"aim {abs(aim_dx)} px {side} of the Pokémon on purpose - MEANT TO MISS"
    if abs(aim_dx) < 8:
        return "aimed at the middle"
    return f"aim {abs(aim_dx)} px {side} of the middle on purpose - still on the Pokémon"


def humanize(target_name, curve):
    """Draw the variation for one throw. Returns (target name, ring size to aim for,
    curveball yes/no, sideways aim offset in px, factor for the throw length, pause in s)."""
    r = random.random()
    if target_name in THROW_TARGETS and r >= REAL_KEEP:
        target_name = REAL_LOWER_OF[target_name] if r < REAL_KEEP + REAL_LOWER else "off"
    target = random.uniform(*REAL_BANDS[target_name]) if target_name in REAL_BANDS else None
    if curve and random.random() >= REAL_CURVE:
        curve = False
    sloppy = random.random() < REAL_SLOPPY[0]
    aim_dx = int(random.gauss(0, REAL_SLOPPY[1] if sloppy else REAL_AIM))
    power = min(max(random.gauss(1.0, REAL_POWER), 0.92), 1.08)
    share, lo, hi = REAL_LONG_PAUSE
    pause = random.uniform(lo, hi) if random.random() < share else random.uniform(*REAL_PAUSE)
    return target_name, target, curve, aim_dx, power, pause


def throw_ball(brain):
    """One throw, with the options from the web interface (curveball; throw target Realistic,
    Off, Nice, Great or Excellent). Returns the clock time at which the ball left the hand."""
    throw_info["hit"] = None                       # (throw_touch fills this in when it saw where the ball came down)
    target_name = str(setting("throw_target", "realistic")).lower()
    curve = bool(setting("curveball", False))
    aim_dx, power = 0, 1.0
    realistic = target_name == "realistic"         # standard profile: mostly Great, with variation
    if realistic:
        target_name = REAL_BASE
    target = THROW_TARGETS.get(target_name)
    if realistic:
        chosen = (target_name, curve)
        target_name, target, curve, aim_dx, power, pause = humanize(target_name, curve)
        plan = [f"{target_name.capitalize()} ring" if target is not None else "no ring timing (on purpose)",
                "curveball" if curve else "straight ball" + (" (on purpose)" if chosen[1] else ""),
                aim_note(aim_dx)]
        log("realistic throw: " + ", ".join(plan))      # so you can tell a planned miss from a real one
        time.sleep(pause)
    if (curve or target is not None) and not cal.get("no_curve"):
        t_rel = throw_touch(brain, curve, target, target_name, aim_dx, power)
        if t_rel:
            return t_rel
    ring = aim(brain)                              # simple throw: look, then one swipe
    if ring:
        _, sc, cx, cy, bw, bh = ring
        dy, dur = brain.throw_params(cx, cy, bw, bh)
        log(f"target ring ({cx}, {cy}, {bw}x{bh}) [{sc:.2f}] -> deltaY {dy:.0f}, {dur:.0f} ms")
        tx = cx
    else:
        dy, dur = THROW_FALLBACK
        tx = BALL_XY[0]
        log("target ring not found - default throw")
    S.swipe(BALL_XY[0], BALL_XY[1], int(min(max(tx + aim_dx, 20), W - 20)), max(int(BALL_XY[1] + dy * power), 50),
            max(int(dur * THROW_BOOST), 60))
    return time.time()


def enc_buttons(img):
    """The two round grey buttons (berries left, balls right) of the catch screen. They are
    there whenever the ball lies ready - also in the moments the ball itself flips over."""
    yy, xx = np.ogrid[-165:165, -165:165]
    r = np.sqrt(xx ** 2 + yy ** 2)
    ring, outside = (r > 88) & (r < 112), (r > 140) & (r < 162)     # the disc is ~122 px in radius
    for bx, by in (S.ENC_BERRY_BTN, S.ENC_BALL_BTN):
        hsv = cv2.cvtColor(img[by - 165:by + 165, bx - 165:bx + 165], cv2.COLOR_BGR2HSV)
        light = (hsv[..., 1] < 45) & (hsv[..., 2] > 150)
        if light[ring].mean() < 0.4 or light[outside].mean() > 0.3:   # a light disc on a darker scene
            return False
    return True


def ball_ready(img):
    return S.in_encounter(img) or enc_buttons(img)


def result_ok_button(img):
    """The teal OK pill of the 'TOTAL XP' screen after a catch (hue ~90, a bit darker than the
    green pills elsewhere in the game, so find_pill_button() does not see it). A new Pokémon
    or a shiny adds the 'New Pokémon Caught Bonus' there, and then the screen classifier is
    often unsure what it is looking at. Returns (x, y) of the middle of the button, or None."""
    y0 = 1500
    hsv = cv2.cvtColor(img[y0:2150], cv2.COLOR_BGR2HSV)
    m = ((hsv[..., 0] >= 80) & (hsv[..., 0] <= 100) & (hsv[..., 1] >= 70) & (hsv[..., 1] <= 210) &
         (hsv[..., 2] >= 110) & (hsv[..., 2] <= 235)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    n, _, st, _ = cv2.connectedComponentsWithStats(m)
    best = None
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if 600 < w < 1200 and 110 < h < 330 and w > 2.5 * h and abs(x + w // 2 - 884) < 160 \
                and a > 0.6 * w * h and (best is None or a > best[2]):
            best = (int(x + w // 2), int(y + h // 2 + y0), int(a))
    return best[:2] if best else None


def catch_result_button(brain, img):
    """OK button of the 'TOTAL XP' screen, only when a catch was thrown and the screen is not
    clearly still the catch screen (the teal blob could be a pond in the background)."""
    if enc["throws"] <= 0:
        return None
    btn = result_ok_button(img)
    if not btn:
        return None
    name, score = brain.screen(img)
    if name == "encounterScreen" and score >= 0.8:
        return None
    return btn


RESULT_FIRST_LOOK = 2.0        # s after the throw until the first look (a miss shows the ball back in the hand from ~2.5 s)
RESULT_WINDOW = 20.0           # s after the throw during which we keep looking (flight + up to 3 shakes + catch animation)
POLL_PAUSE = 0.3               # s between two looks (a screenshot itself already takes ~2 s on the Pi, so no more waiting than this)
POLL_PAUSE_LIVE = 0.05         # ... with the live video (a picture takes a tenth of a second; the classifier ~0.3 s)
AFTER_OK_WAIT = 1.5            # s after the tap on OK of the result screen until the map has been drawn again
AFTER_TAP_WAIT = 2.0           # s after another tap on the way back to the map (a button, closing a summary)


def tap_catch_result(btn, how):
    log(f"catch result screen ({how}) - tapping OK")
    mark_caught()
    enc["t_tap"] = time.time()
    S.tap(*btn)


def wait_for_result(brain, t_throw):
    """After a throw: return as soon as the ball is back in the hand (miss / broke free) or
    the catch screen is gone (caught), instead of always waiting a fixed time. When the
    'TOTAL XP' screen is there the OK button is tapped right here. When some other screen is
    there, the picture is handed to the next step() (no second screenshot of the same screen).
    Returns True when the ball lies ready for the next throw."""
    time.sleep(max(RESULT_FIRST_LOOK - (time.time() - t_throw), 0.1))
    while True:
        img = S.quick_screenshot()
        if ball_ready(img):
            return True
        btn = catch_result_button(brain, img)
        if btn:
            tap_catch_result(btn, "seen while waiting")
            return False
        name, score = brain.screen(img)
        if name != "encounterScreen" and score >= TH_CLASS:
            handoff.update(img=img, t=time.time())
            return False
        if time.time() - t_throw > RESULT_WINDOW:
            return False
        time.sleep(POLL_PAUSE_LIVE if S.quick_screenshot.live else POLL_PAUSE)


def aim(brain):
    """Hold the ball (the target ring appears then), take a screenshot and look for the ring."""
    bx, by = S.to_real(*BALL_XY)
    hold = subprocess.Popen(["adb", "shell", *S.INPUT, "swipe", str(bx), str(by), str(bx), str(by), "1300"])
    time.sleep(0.4)
    img = S.quick_screenshot()
    hold.wait(timeout=10)
    time.sleep(0.2)
    rings = [o for o in brain.encounter_objects(img)
             if o[0] == "boundingBox" and o[1] >= TH_RING and o[3] < BALL_XY[1] - 300]
    save_async("g_richten.png", img)
    return rings[0] if rings else None


def do_encounter(brain, img):
    if storage_state["full"] and (wanted("spin_only_when_full") or wanted("daily_cycle")) and ball_ready(img):   # storage full: do not catch, run away
        log("encounter while storage is full - running away")
        S.tap(*S.RUN_BTN)
        return 3
    if not ball_ready(img):                     # e.g. "TOTAL XP" with OK: no ball at the bottom
        btn = catch_result_button(brain, img)
        if btn:                                 # (a new Pokémon: the classifier is unsure about that screen)
            tap_catch_result(btn, "classified as catch screen")
            return 1.5
        time.sleep(0.5)                         # the ball may just be flipping over / flying back:
        img = S.quick_screenshot()              # look once more before deciding it is over
        if ball_ready(img):
            return 0.2
        mark_caught()
        if tap_button(brain, img):
            return AFTER_TAP_WAIT
        btn = S.find_green_button(img)
        if btn:
            S.tap(btn[0], btn[1])
        return AFTER_TAP_WAIT
    if enc["start"] == 0:
        enc["start"] = time.time()
        log("encounter opened")
        save_async("g_vangscherm.png", img)

    if enc["throws"] >= MAX_THROWS:
        log("too many misses - running away")
        S.tap(*S.RUN_BTN)
        reset_encounter()
        return 3

    if BALL and not enc["ball_set"]:
        S.tap(*S.ENC_BALL_BTN); time.sleep(1.5)
        S.tap(*S.BALL_POS[BALL]); time.sleep(1.5)
        enc["ball_set"] = True

    if BERRY_ORDER and not enc["berry"]:
        enc["berry"] = True                    # only one attempt per Pokémon
        S.tap(*S.ENC_BERRY_BTN); time.sleep(1.0)
        tray = S.screenshot()
        save_async("g_berries.png", tray)
        choice = pick_berry(tray)
        if choice:
            name, (x, y) = choice
            S.tap(x, y); time.sleep(1.0)
            S.tap(*BALL_XY)                        # a tap on the berry feeds it (a throw can miss)
            log(f"{name} berry fed")
            time.sleep(2.5)
        else:
            log("no allowed berry available - continuing without berry")
            S.back(); time.sleep(1.5)          # berry-lade sluiten

    while True:                                        # keep throwing while the ball comes back
        t_throw = throw_ball(brain)
        enc["throws"] += 1
        enc["t_throw"] = t_throw
        log(f"ball {enc['throws']} thrown")
        if throw_info["hit"] and fast_catch_on() and wanted("catch"):
            wait = fast_catch_leave(brain, t_throw)    # clear hit: skip the catch animation
            if wait is not None:
                return wait
        back = wait_for_result(brain, t_throw)         # wait for flight + shaking
        if not back or enc["throws"] >= MAX_THROWS or not wanted("catch"):
            # OK was just tapped: give the map time to come back (a look right away would see the
            # fading result screen and tap OK a second time); otherwise carry on at once
            return AFTER_OK_WAIT if time.time() - enc["t_tap"] < 1.0 else 0.2


DISMISS_BTN = (884, 2098)       # DISMISS under a news popup
AWAY_LIMIT = 300                # s away from the map before the game is restarted
away = {"since": None}


def news_popup(img):
    """News card over the map (e.g. 'Pokémon GO x Duolingo', button SEE DETAILS): it has the
    word DISMISS at the very bottom of the screen."""
    return "DISMISS" in ocr_text(img, 2000, 2208)


PARTY_CLOSE_BTN = (884, 1990)   # X at the bottom of the Weekly Challenge / group screen


def leave_group_screen(img):
    """Weekly Challenge screen ('Find me a group!') and its question 'Are you sure you want
    to join a group?': never join. Tap CANCEL on the question, the X on the screen itself."""
    lines = ocr_lines(img, 150, 2150)
    text = " ".join(t for t, *_ in lines)
    question = "GROUP WITH OTHER TRAINERS" in text or ("ARE YOU SURE" in text and "GROUP" in text)
    screen = "FIND ME A GROUP" in text or "WEEKLY CHALLENGE" in text or "JOIN GROUP" in text
    if not (question or screen):
        return False
    cancel = [(wx, wy) for _, _, _, ws in lines for w, wx, wy in ws if w == "CANCEL"]
    if cancel:
        log("group question - tapping CANCEL (not joining)")
        S.tap(*cancel[0])
    elif question:
        log("group question - going back (not joining)")
        S.back()
    else:
        log("Weekly Challenge / group screen - closing it")
        S.tap(*PARTY_CLOSE_BTN)
    return True


NOTICE_OK_BTN = (884, 2005)   # OK on the safety notice shown when the game starts


def safety_notice(img):
    """Notice at start-up ('Stay Aware of Your Surroundings', 'Do not trespass ...',
    'Do not play while driving', ...): it only goes away with OK."""
    t = ocr_text(img, 1100, 1800)
    return any(w in t for w in ("SURROUNDINGS", "TRESPASS", "WHILE DRIVING", "DANGEROUS AREAS"))


def is_rocket_text(img):
    """Team Rocket dialogue / battle screen recognised by its text."""
    t = ocr_text(img, 1300, 2208)
    return any(w in t for w in ("TEAM GO ROCKET", "GRUNT", "BATTLE PARTY", "USE THIS PARTY"))


def tap_button(brain, img, only_passenger=False):
    """Tap a wide button in the middle (OK, CLAIM REWARD, 'I am a passenger').
    Never small buttons or buttons at the side (such as POWER UP / EVOLVE)."""
    btns = brain.buttons(img)
    if only_passenger and not any(n == "passenger" and sc >= TH_PASSENGER for n, sc, *_ in btns):
        return False
    for name, sc, x, y, bw, bh in btns:
        if name == "clickable" and sc >= TH_CLICK and abs(x - W // 2) < 250 and bw > 500:
            label = ocr_text(img, max(y - bh // 2, 0), min(y + bh // 2, H))
            if any(w in label for w in ("BATTLE", "FIGHT", "USE THIS PARTY", "LET'S GO", "JOIN", "GROUP", "DETAILS")):
                log(f"button '{label}' is a battle/group button - NOT tapping, going back")
                S.back()
                return True
            log(f"button ({x}, {y}) [{sc:.2f}] - tapping")
            S.tap(x, y)
            return True
    return False


# ------------------- layout: is the game drawn the way this bot expects? -------------------
# On the first map picture of every run the bot looks for the Poké Ball menu button and compares where it
# is with where it is on the canvas (spin_stop.find_menu_button). When that does not fit, or the screen has
# another shape, it lets Android draw the game on a canvas of the right shape (wm size), checks again and
# taps the menu button to see that the menu opens. Anything that does not work is undone.
layout = {"state": "new",       # new | confirmed | unverified | adapting | adapted
          "looks": 0, "since": 0.0, "next_try": 0.0}
LAYOUT_LOOKS = 4                # map pictures without the button before the bot gives up looking for it
LAYOUT_MAP_WAIT = 300           # s after a display change in which the map has to be seen again
LAYOUT_RETRY = 1800             # s between two attempts to adapt the display


def layout_init():
    """Called once at the start: put a display change back when the bot stops, and take over one
    that an earlier run did not get to put back."""
    atexit.register(S.restore_display)
    try:
        signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))      # (so that atexit runs when the service is stopped)
    except ValueError:
        pass
    rec = S.load_wm_record()
    if not rec:
        return
    try:
        _, over = S.wm_info()
    except Exception:  # noqa: BLE001
        over = None
    if over and f"{over[0]}x{over[1]}" == rec.get("set"):
        log(f"layout: the display size {rec['set']} set by an earlier run is still active - checking it")
        layout.update(state="adapting", since=time.time())
    else:
        S.forget_wm_record()


def layout_adapt(why):
    """Try to get the game drawn in the right shape. True when the display was changed (the bot has to
    look at the game again); False when that is not possible or not allowed."""
    if time.time() < layout["next_try"]:
        return False
    layout["next_try"] = time.time() + LAYOUT_RETRY
    log(f"layout: {why} - trying to let Android draw the game in the right shape")
    changed, text = S.adapt_display()
    if not changed:
        log(f"layout: not possible: {text}")
        return False
    layout.update(state="adapting", looks=0, since=time.time())
    log(f"layout: {text} - checking the game again on the map")
    same_screen.update(name=None, count=0)
    return True


def layout_undo(why):
    """The display change did not work out: put everything back."""
    log(f"layout: {why} - putting the display size back")
    S.restore_display()
    layout.update(state="unverified", looks=0, next_try=time.time() + LAYOUT_RETRY)


def layout_tap_test(before):
    """Tap the menu button and see whether the main menu opens (the taps land where the pictures say);
    then go back to the map. True when the menu opened (or the screen is something else than the map
    and not the question 'exit?': then the tap did land on the button, only the text was not read)."""
    S.tap(*MENU_BTN)
    shot = _settled(2.0)
    lines = ocr_lines(shot, 100, 2150)
    kind = _screen_kind(shot, lines)
    log(f"layout check: after a tap on the menu button the screen is '{kind}'")
    opened = kind in ("menu", "bag") or (kind == "other" and not S.on_map(shot) and screen_changed(before, shot))
    for _ in range(4):                                     # back to the map, whatever it is
        if S.on_map(shot):
            break
        if kind == "exit":
            _cancel_exit(lines)
        else:
            S.back()
        shot = _settled(1.5)
        lines = ocr_lines(shot, 100, 2150)
        kind = _screen_kind(shot, lines)
    return opened


def layout_verify(img):
    """Called with a picture of the map (on the canvas) until the layout is settled for this run."""
    state = layout["state"]
    found = S.find_menu_button(img)
    ok, text = S.menu_button_check(found)
    if ok:
        if state == "adapting":
            if layout_tap_test(img):
                layout["state"] = "adapted"
                log(f"layout check: {text} - confirmed; the menu opens when tapped, the game is playable on {S.screen['w']}x{S.screen['h']}")
            else:
                layout_undo("tapping the menu button did not open the menu")
        else:
            layout["state"] = "confirmed"
            log(f"layout check: {text} - the game is drawn as expected")
        return
    layout["looks"] += 1
    if ok is None and layout["looks"] < LAYOUT_LOOKS:
        return                                             # something may cover the button: look at a few more pictures
    if state == "adapting":
        layout_undo(f"{text}" if ok is not None else f"menu button not found on {layout['looks']} map pictures")
        return
    if ok is False and layout_adapt(text):
        return
    layout["state"] = "unverified"
    log(f"layout check: {text} - the game is not drawn the way this bot expects, taps may land in the wrong places "
        f"(see the wiki page 'Phone setup')" if ok is False else
        f"layout check: menu button not found on {layout['looks']} map pictures - carrying on without that check")


def layout_watch():
    """After a display change the map has to come back within a few minutes."""
    if layout["state"] == "adapting" and time.time() - layout["since"] > LAYOUT_MAP_WAIT:
        layout_undo(f"the map was not seen within {LAYOUT_MAP_WAIT // 60} minutes of the display change")


health = {"t": 0.0, "ok": False}


# ------------------------------- quests: the GO Pass rewards ----------------------------------
# The quest button at the bottom right of the map is gold when something can be claimed (23 November,
# screenshots): the quest screen -> the tab GO PASS -> its pages (GO PASS: DYNAMAX TRAILS, GO PASS: NOVEMBER)
# -> down to 'Claimable rewards: N' and VIEW REWARDS -> CLAIM ALL -> (a Pokémon as a reward: an encounter, the
# normal catching) -> the X at the bottom closes it.
QUEST_BTN = (0.945, 0.847)     # the quest button on the map (binoculars), gold when something is to be claimed
QUEST_R = 0.026                # its radius (fraction of the width)
QUEST_CLOSE = (0.50, 0.925)    # the round X at the bottom of the quest screens
QUEST_EVERY = 15 * 60          # s: looked at at most this often (a gold button that stays: not every step)
QUEST_NOTHING = 60 * 60       # s: after a look that found nothing to claim, the next one waits this long
quest_state = {"t": 0.0}


def quest_gold(img):
    """True when the quest button on the map is gold (orange) instead of white."""
    h, w = img.shape[:2]
    cx, cy, r = QUEST_BTN[0] * w, QUEST_BTN[1] * h, QUEST_R * w
    y0, y1, x0, x1 = int(cy - r), int(cy + r) + 1, int(cx - r), int(cx + r) + 1
    hsv = cv2.cvtColor(img[max(y0, 0):y1, max(x0, 0):x1], cv2.COLOR_BGR2HSV)
    gold = (hsv[..., 0] >= 8) & (hsv[..., 0] <= 25) & (hsv[..., 1] >= 120) & (hsv[..., 2] >= 180)
    return float(gold.mean()) >= 0.45


def quests_due(img):
    if not setting("quests", True) or time.time() - quest_state["t"] < QUEST_EVERY:
        return False
    return quest_gold(img)


def _tap_word(lines, *words, below=0.0, h=2208):
    """Tap the first OCR line that holds all `words` (upper case), lower than `below` (fraction).  Returns it."""
    for t, x, y, _ws in lines:
        u = t.upper()
        if all(wd in u for wd in words) and y >= below * h:
            S.tap(x, y)
            return (t, x, y)
    return None


def claim_quests():
    """The quest button is gold: claim what the GO Pass has (VIEW REWARDS -> CLAIM ALL), close with the X.
    Returns 'claimed', 'nothing', 'catch' (a Pokémon came as a reward: the normal bot catches it) or
    'failed'."""
    quest_state["t"] = time.time()
    log("quests: the quest button is gold - looking at the GO Pass")
    S.tap(*_frac_xy(QUEST_BTN))
    shot = _settled(2.5)
    lines = ocr_lines(shot, 100, 2150, 0.6)
    save_async("g_quest_0.png", shot)
    if S.on_map(shot):
        log("quests: the quest screen did not open")
        return "failed"
    h = shot.shape[0]
    if not _tap_word(lines, "GO PASS"):
        log(f"quests: no GO PASS tab ({_reads(lines, 80)})")
        S.tap(*_frac_xy(QUEST_CLOSE))
        return "failed"
    shot = _settled(1.5)
    lines = ocr_lines(shot, 100, 2150, 0.6)
    pages = [(t, x, y) for t, x, y, _ws in lines if "GO PASS" in t.upper() and ":" in t and y < 0.35 * h] or [None]
    claimed = 0
    for page in pages[:3]:
        if page is not None:
            S.tap(page[1], page[2])
            time.sleep(2.0)
        found = None
        for _ in range(6):                               # down the page to 'Claimable rewards' / VIEW REWARDS
            shot = S.screenshot()
            lines = ocr_lines(shot, 300, 2050, 0.6)
            found = _tap_word(lines, "VIEW", "REWARDS")
            if found:
                break
            if any("DAILY TASKS" in t.upper() for t, _x, _y, _w in lines):
                break                                    # (past the place where it would be)
            S.swipe(884, 1700, 884, 900, 700)
            time.sleep(1.2)
        if not found:
            continue
        log(f"quests: VIEW REWARDS on '{page[0] if page else 'the GO Pass'}'")
        shot = _settled(2.0)
        lines = ocr_lines(shot, 300, 2150, 0.6)
        save_async("g_quest_rewards.png", shot)
        if not _tap_word(lines, "CLAIM", "ALL"):
            log(f"quests: no CLAIM ALL ({_reads(lines, 80)})")
            break
        claimed += 1
        log("quests: CLAIM ALL")
        time.sleep(4.0)
        shot = S.screenshot()
        name, score = screen_class(shot)
        if name == "encounterScreen" and score >= TH_CLASS:
            log("quests: a Pokémon came as a reward - the normal bot catches it")
            quest_state["t"] = time.time() - QUEST_EVERY + 60     # (look again a minute after it)
            return "catch"
        break
    for _ in range(3):                                   # close: the round X at the bottom
        if S.on_map(S.screenshot()):
            break
        S.tap(*_frac_xy(QUEST_CLOSE))
        time.sleep(2.0)
    log("quests: " + ("rewards claimed" if claimed else "nothing to claim in the GO Pass - looking again in an hour"))
    if not claimed:                                      # (the button stays gold for something else: research)
        quest_state["t"] = time.time() + QUEST_NOTHING - QUEST_EVERY
    return "claimed" if claimed else "nothing"


HEAT_EVERY = 60              # s between two looks at the temperatures
HEAT_PHONE, HEAT_PHONE_OK = 43.0, 39.0    # °C of the phone's battery: pause from here, go on again below that
HEAT_PI, HEAT_PI_OK = 82.0, 72.0          # °C of the Pi's processor: the same
HEAT_MAX_PAUSE = 45 * 60     # s: a pause never takes longer than this (a sensor that is stuck)
heat = {"t": 0.0, "since": None, "phone": None, "pi": None}


def read_heat():
    """(°C of the phone's battery, °C of the Pi), None for what cannot be read."""
    phone = pi = None
    try:
        m = re.search(r"^\s*temperature:\s*(-?\d+)", S.adb("shell", "dumpsys", "battery"), re.M)
        phone = int(m.group(1)) / 10.0 if m else None
    except Exception:  # noqa: BLE001
        pass
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            pi = int(f.read().strip()) / 1000.0
    except (OSError, ValueError):
        pass
    return phone, pi


def heat_wait():
    """Option 'Pause when it gets hot': s to wait when the phone or the Pi is too hot (nothing is tapped then),
    0 when the bot may go on. Looked at every HEAT_EVERY s (and every 30 s while it pauses)."""
    if not setting("heat_pause", True):
        heat["since"] = None
        return 0
    now = time.time()
    if now - heat["t"] < (30 if heat["since"] else HEAT_EVERY):
        return 30 if heat["since"] else 0
    heat["t"] = now
    phone, pi = heat["phone"], heat["pi"] = read_heat()
    if heat["since"] is None:
        hot = [f"the phone's battery is {phone:.0f} °C" for _ in [1] if phone is not None and phone >= HEAT_PHONE] + \
              [f"the Pi is {pi:.0f} °C" for _ in [1] if pi is not None and pi >= HEAT_PI]
        if hot:
            heat["since"] = now
            log(f"heat: {' and '.join(hot)} - pausing until it is below {HEAT_PHONE_OK:.0f} / {HEAT_PI_OK:.0f} °C")
            return 30
        return 0
    cool = (phone is None or phone <= HEAT_PHONE_OK) and (pi is None or pi <= HEAT_PI_OK)
    if cool or now - heat["since"] > HEAT_MAX_PAUSE:
        log(f"heat: going on after {(now - heat['since']) / 60:.0f} min"
            + ("" if cool else " (the longest pause is over, although it is still warm)")
            + (f" - phone {phone:.0f} °C" if phone is not None else "") + (f", Pi {pi:.0f} °C" if pi is not None else ""))
        heat["since"] = None
        return 0
    return 30


def step(brain):
    wait = heat_wait()
    if wait:
        return wait
    if not S.screen["ok"]:                  # e.g. a foldable was folded during the run: the layout is not supported
        if layout_adapt("the screen has another shape than the canvas"):
            return 3
        S.wait_unsupported()
        return 5
    layout_watch()
    # is the phone awake and unlocked? Asking Android takes a while, so only do it when the
    # last look did not show a normal game screen, or now and then.
    if not health["ok"] or time.time() - health["t"] > 60:
        if "mWakefulness=Awake" not in S.adb("shell", "dumpsys", "power"):
            S.adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")
            time.sleep(2)
        S.unlock()
        health["t"] = time.time()
    t_step = t_shot = time.time()
    if handoff["img"] is not None and time.time() - handoff["t"] < 2.5:
        img = handoff["img"]                # looked at a moment ago while waiting for the catch result: no new screenshot
        handoff["img"] = None
    else:
        handoff["img"] = None
        img = S.unlock_game(S.quick_screenshot(fire_rotation) if rotation["armed"] else S.quick_screenshot())
    shot_cost = time.time() - t_shot

    name, score = brain.screen(img)
    if score < TH_CLASS:
        name = "onbekend"
    if S.quick_screenshot.live and name not in ("mapScreen", "encounterScreen"):
        img = S.unlock_game(S.screenshot())         # (a picture of the video is not sharp enough to read text)
        name, score = brain.screen(img)
        if score < TH_CLASS:
            name = "onbekend"
    if name != "mapScreen" and not S.on_map(img):      # (a swipe started for a picture that turned out not to be the map: forget it)
        rotation.update(fired=None, armed=None)
    health["ok"] = name in ("mapScreen", "encounterScreen", "pokestopScreen")
    if name == same_screen["name"]:
        same_screen["count"] += 1
    else:
        same_screen.update(name=name, count=1)

    # away from the map / catch screen / PokéStop for minutes (e.g. going round in circles
    # between two menus)? Then start the game again.
    if name in ("mapScreen", "encounterScreen", "pokestopScreen"):
        away["since"] = None
    elif away["since"] is None:
        away["since"] = time.time()
    elif time.time() - away["since"] > AWAY_LIMIT:
        log(f"not back on the map for {AWAY_LIMIT // 60} min (now '{name}') - restarting Pokémon GO")
        save_async("g_stuck.png", img)
        S.restart_game()
        away["since"] = None
        same_screen.update(name=None, count=0)
        return 5

    # stuck? (not the map, and the same screen 12 times already)
    if name != "mapScreen" and same_screen["count"] > 12:
        log(f"stuck on '{name}' - restarting Pokémon GO")
        S.restart_game()
        same_screen.update(name=None, count=0)
        return 5

    # did the previous step tap a "Pokémon" without the catch screen opening (e.g. your buddy,
    # or storage full)? Then skip that spot for longer.
    if last_tap["kind"] == "pokemon" and name == "mapScreen" and last_tap.get("alt"):
        ax, ay = last_tap["alt"].pop(0)           # the tap before did not open it: try lower down
        log(f"no encounter yet - tapping lower ({ax}, {ay})")   # (middle of the box, then its foot)
        S.tap(ax, ay)
        return 3
    if last_tap["kind"] == "pokemon" and name != "encounterScreen":
        x, y = last_tap["xy"]
        cooldown.append((x, y, time.time() + COOLDOWN))
        log(f"no encounter after tapping ({x}, {y}) [{name}] - skipping for {COOLDOWN // 60} min")
        if last_tap.get("near") and setting("buddy", False):   # probably your buddy, not a wild Pokémon
            near_state["until"] = time.time() + NEAR_BLOCK
            log(f"that was next to the trainer - leaving Pokémon there alone for {NEAR_BLOCK // 60} min")
        save_async("g_pokemon_na_tik.png", img)
    if ((name == "rocketScreen" or (name in ("menusScreen", "rewardScreen", "onbekend") and is_rocket_text(img)))
            and setting("rocket_fight", True)):
        log("Team GO Rocket at the stop - battling")
        save_async("g_rocket.png", img)
        try:
            res = rocket_battle()
        except Exception as e:  # noqa: BLE001
            log(f"rocket: error {e}")
            res = "failed"
        if res != "failed":
            return 1
        if last_tap["kind"] == "stop":           # (it went wrong: leave that stop alone for a while)
            x, y = last_tap["xy"]
            cooldown.append((x, y, time.time() + ROCKET_COOLDOWN))
        name = brain.screen(S.screenshot())[0]
    if name == "rocketScreen" or (name in ("menusScreen", "rewardScreen", "onbekend") and is_rocket_text(img)):
        if last_tap["kind"] == "stop":
            x, y = last_tap["xy"]
            cooldown.append((x, y, time.time() + ROCKET_COOLDOWN))
        log(f"Team Rocket - not battling, leaving (stop skipped for {ROCKET_COOLDOWN // 60} min)")
        save_async("g_rocket.png", img)
        for _ in range(3):                       # back out of the dialogue / battle party screen
            S.back()
            time.sleep(1.5)
            nm, sc = brain.screen(S.screenshot())
            if nm == "mapScreen" and sc >= TH_CLASS:
                break
        last_tap.update(kind=None, xy=None, alt=None)
        return 3
    if last_tap["kind"] == "pokemon" and name == "encounterScreen":
        enc_xy["xy"] = last_tap["xy"]                  # (fast catch: where this Pokémon is on the map)
    last_tap.update(kind=None, xy=None, alt=None)

    if name == "mapScreen" and layout["state"] in ("new", "adapting"):
        layout_verify(img)                             # first map picture of this run: is the game drawn as expected?
        if layout["state"] in ("adapting", "adapted") or not S.screen["ok"]:
            return 1.0                                 # (the display changed, or is still being checked: look at the game again)
    if name == "mapScreen" and quests_due(img):
        try:
            res = claim_quests()
        except Exception as e:  # noqa: BLE001
            log(f"quests: error {e}")
            res = "failed"
        if res != "failed":
            return 1.0
    if name == "mapScreen":
        perf["shot"] += shot_cost
        perf["t_step"] = t_step
        wait = do_map(brain, img)
        perf["total"] += time.time() - t_step          # (without the wait that follows)
        return wait
    if name == "pokestopScreen":
        return do_pokestop(brain, img)
    if name == "encounterScreen":
        return do_encounter(brain, img)
    if name == "eggScreen":
        S.tap(*S.CENTER)
        return 3
    if name == "summaryScreen":                  # Pokémon summary after catching
        mark_caught()
        S.back()
        return AFTER_TAP_WAIT
    if name != "encounterScreen" and name != "mapScreen" and news_popup(img):
        log("news popup - tapping DISMISS")
        S.tap(*DISMISS_BTN)
        return 1.5                               # (several cards can follow each other)
    if name in ("menusScreen", "onbekend", "rewardScreen", "summaryScreen") and leave_group_screen(img):
        return 3
    if name in ("menusScreen", "onbekend", "rewardScreen") and safety_notice(img):
        btn = find_pill_button(img) or S.find_green_button(img) or NOTICE_OK_BTN
        log("startup safety notice - tapping OK")
        S.tap(btn[0], btn[1])
        return 3
    if name in ("menusScreen", "onbekend", "rewardScreen") and storage_full(img):
        save_async("g_opslag_vol.png", img)
        S.back()                                 # close the notification (never tap MANAGE POKÉMON)
        if CATCH:
            pause_catching()
        return 3
    if name == "menusScreen":                    # only click away "you are going too fast", otherwise go back
        if not tap_button(brain, img, only_passenger=True):
            S.back()
        return 3
    if name in ("rewardScreen", "onbekend"):
        if enc["throws"] > 0:
            mark_caught()                        # "TOTAL XP" with OK after a throw = caught
            btn = catch_result_button(brain, img)
            if btn:
                tap_catch_result(btn, name)
                return 1.5
        if tap_button(brain, img):
            return AFTER_TAP_WAIT
        btn = S.find_green_button(img)           # old method as a fallback
        if btn:
            S.tap(btn[0], btn[1])
            return AFTER_TAP_WAIT
        if name == "onbekend" and S.on_map(img):
            return do_map(brain, img)
        S.back()
        return 3
    # rocketScreen, areneScreen en de rest: terug
    S.back()
    return 3


# ------------------------------ daily run ----------------------------------
DAILY_FILE = os.path.expanduser("~/gamebot_daily.json")
DAILY_MAX_MIN = 480           # default for "Stop after ... min" (minutes): how long a run may take, set in the web interface
FINISH_MAX_S = 150            # s: when the time is up during a catch, this long to finish it
MAIN_PACKAGE = "com.nianticlabs.pokemongo"     # Play Store version: always first
run_state = {"done": False, "waiting_logged": False}
force_start = {"pending": False}   # the bot was just started: play now, do not wait for the start time
FORCE_FILE = os.path.expanduser("~/gamebot_force.json")   # written by the Start / Restart button of the web interface


def take_force_flag():
    """Was the bot started with the Start / Restart button just now? (The flag is used up.)"""
    try:
        recent = time.time() - os.path.getmtime(FORCE_FILE) < 300
        os.remove(FORCE_FILE)
        return recent
    except OSError:
        return False


def game_packages():
    """All installed Pokémon GO apps (Play Store + Galaxy Store), Play Store first."""
    try:
        out = S.adb("shell", "pm", "list", "packages", "pokemongo")
    except Exception:
        return [MAIN_PACKAGE]
    pkgs = sorted({l.split(":", 1)[1].strip() for l in out.splitlines() if l.startswith("package:")})
    return sorted(pkgs, key=lambda p: (p != MAIN_PACKAGE, p)) or [MAIN_PACKAGE]


# ------------------------------- auto battle -------------------------------
# Option "Battles" (web interface): in the daily run the chosen Pokémon GO app first fights some GO Battle
# League battles, then it spins and catches as usual. The decisions (which charged attack, when to shield,
# who comes in after a faint) are made by battle_engine.py; battle_vision.py reads the fight screen,
# battle_fight.py keeps the state of one fight, battle_nav.py reads the menus and questions with OCR.
BATTLE_LEAGUE = "Great League"
BATTLE_COUNT = 5


def battle_wanted():
    return bool(setting("battle", False)) and not battles_done_today()


BATTLE_DONE_FILE = os.path.expanduser("~/battle_done.json")   # the day on which the BATTLE button was grey


def battles_done_today(mark=False):
    """True when the Battle screen showed a grey BATTLE button today (all sets of the day are played): the
    daily run then skips the battles until tomorrow.  mark=True: write that down for today."""
    today = time.strftime("%Y-%m-%d")
    if mark:
        try:
            with open(BATTLE_DONE_FILE, "w") as f:
                json.dump({"day": today}, f)
        except OSError:
            pass
        return True
    try:
        with open(BATTLE_DONE_FILE) as f:
            return json.load(f).get("day") == today
    except (OSError, ValueError, AttributeError):
        return False


def battle_app():
    """Package of the Pokémon GO app that fights (the first app when none is chosen)."""
    return str(setting("battle_app", "") or "") or MAIN_PACKAGE


def battle_league():
    return str(setting("battle_league", BATTLE_LEAGUE) or BATTLE_LEAGUE).strip()[:40]


def battle_count():
    try:
        return min(max(int(setting("battle_count", BATTLE_COUNT)), 1), 50)
    except (TypeError, ValueError):
        return BATTLE_COUNT


def battle_give_up():
    """Option 'Give up a lost battle' (web interface, on by default): see _fight_give_up()."""
    return bool(setting("battle_give_up", True))


BATTLE_NAV_STEPS = 20        # screens looked at on the way to the party screen
BATTLE_NAV_SECONDS = 240     # ... and the most time that may take
# A new rank has to be claimed before the next battle: the Battle screen then has an orange CLAIM RANK REWARDS!
# button where the green BATTLE button is.  It is tapped and the screens that follow are worked through.
BATTLE_RESUMES = 3           # the battles go on after a Pokémon of a reward was caught, this often a run at most
COLLECT_TAPS = 6             # gold COLLECT tiles of a Battle screen with a grey BATTLE button tapped at most
CLAIM_TAPS = 4               # the claim button of the Battle screen is tapped this often at most
CLAIM_STEPS = 14             # screens looked at after it (the rank-up and its rewards) ...
CLAIM_SECONDS = 150          # ... and the most time that may take
CLAIM_NOT = ("SHOP", "BUY", "COIN", "SHARE", "EXCHANGE", "PREMIUM", "PASS", "PURCHASE")   # buttons never tapped there
CLAIM_TAP_ON = (0.5, 0.30)   # where a screen with nothing to tap on it is tapped to go on (tap to continue)
# When a new set of five battles starts, the card of the Battle screen is longer ('Choose a reward tier ...') and
# its BATTLE button is below the lower edge of the screen: it is scrolled down in small, slow steps (y from -> to
# as fractions of the screen; slow, so that the page does not fly on), until the first BATTLE button is in view.
HOME_SCROLL = ((0.70, 0.56), (0.64, 0.48), (0.78, 0.62))
HOME_SCROLL_MS = 900
HOME_TAPS = 4                # the BATTLE button is tapped this often at most
POPUP_TAPS = 4               # pop-ups on the way (Welcome to the GO Battle League: LET'S GO!) tapped away at most
WELCOME_BUTTON = (0.5, 0.916)   # where LET'S GO! is when the button itself is not seen


def _battle_kind(shot, lines):
    return BN.screen_kind(lines, S.on_map(shot), battle_league(), shot.shape[0] / 2208)


def _battle_to_map(beat=None, leaving_setup=False):
    """Leave the battle screens: look at what is on the screen and go back, never blindly.
    A closed menu is left with its X button, 'Do you want to exit Pokémon GO?' is answered with CANCEL.
    BACK on the league list or the party screen asks 'Exit the Trainer Battle?': with leaving_setup (we
    only looked at those screens, no fight was started) it is answered with YES, otherwise with NO."""
    yes_taps = 0
    for i in range(10):
        shot = S.screenshot()
        if S.on_map(shot):
            return True
        lines = ocr_lines(shot, 100, None, 0.6)
        kind = _battle_kind(shot, lines)
        if beat:
            beat()
        if kind == "exit":
            _cancel_exit(lines)
        elif kind == "exit_battle":
            spots = BN.exit_battle_spots(lines, shot.shape[0] / 2208)
            if leaving_setup and yes_taps < 3:
                yes_taps += 1
                log("battle: leaving the league screens - answering YES to 'Exit the Trainer Battle?' "
                    f"(no battle was started), at {spots['yes']}")
                S.tap(*spots["yes"])
            elif spots["no"]:
                S.tap(*spots["no"])
            else:
                S.back()
        elif kind == "menu":
            S.tap(*MENU_BTN)                         # the X of the main menu
        else:
            S.back()
        time.sleep(2.5)
    return S.on_map(S.screenshot())


def battle_open_menu(beat=None, stop=None, restart=False, stay=False, leagues_only=False):
    """Walks from the map (or from the Battle screen after a fight) to the party screen of the chosen league.

    map -> main menu -> BATTLE tile -> Battle screen -> BATTLE button -> [league list] -> party screen.
    Every step looks at what is really on the screen first (see battle_nav.py); an unknown screen is
    logged with a saved picture (debug/g_battle_s<step>.png). It NEVER presses USE THIS PARTY itself.
    When the Battle screen has an orange claim button where the BATTLE button is (CLAIM RANK REWARDS!: a new
    rank has to be claimed before the next battle) that is tapped first and the screens after it are worked
    through (pictures: debug/g_battle_claim*.png).  When no BATTLE button is in view (a new set starts: the
    card is longer) the screen is scrolled down a little; of two BATTLE buttons the upper one is the one of
    the basic rewards, the lower one (premium rewards, costs a pass) is never tapped.
    stay: wait on the party screen (the fight starts from there); otherwise go back to the map. restart:
    when the way back to the map fails, restart the game (the daily run needs the map).
    leagues_only: stop at the league list, read the leagues on it ("leagues": [(title, max CP)]) and go back.
    Returns {"ok": bool, "why": str, "title": str, "members": [...], "use_spots": [(x, y), ...]}; with
    "leave": True the screen was left as it is (BACK could throw away a reward: a Pokémon to catch)."""
    import battle_vision as BV
    league = battle_league()
    info = {"ok": False, "why": "", "title": "", "members": [], "use_spots": []}
    try:
        import battle_engine as BE
        names = [m.name for m in BE.load_team()]
    except Exception:  # noqa: BLE001
        names = []
    t0 = time.monotonic()
    taps = {"map": 0, "home": 0, "league": 0}
    menu_spots = None
    others, tapped, in_setup = 0, False, False   # in_setup: the league list or party screen was seen
    claim = {"taps": 0, "since": 0.0, "steps": 0, "idle": 0, "catch": 0}    # the claim button and what follows it
    collect = {"taps": 0}     # the gold COLLECT tiles of the rewards of a set (tapped when the BATTLE button is grey)
    scroll = {"down": 0, "up": 0}                # how often the Battle screen was scrolled
    popups = 0                                   # pop-ups that were tapped away
    max_steps, max_seconds = BATTLE_NAV_STEPS, BATTLE_NAV_SECONDS
    step = -1

    def after_claim(shot, lines, k):
        """A screen that came after the claim button (the rank-up, its rewards): tap what takes it further.
        Returns True when the walk has to stop here (info says why)."""
        claim["steps"] += 1
        if claim["steps"] <= 8:
            save_async(f"g_battle_claim_{claim['steps']}.png", shot)
        buttons = BV.wide_buttons(shot)
        name, score = screen_class(shot)
        if name == "encounterScreen" and score >= TH_CLASS and not buttons and not BN.battle_words(lines):
            claim["catch"] += 1                      # a Pokémon to catch as a reward (seen twice: no flicker)
            if claim["catch"] >= 2:
                info.update(why="a Pokémon to catch came up after the claim (a reward)", leave=True)
                return True
            return False
        claim["catch"] = 0
        if claim["steps"] > CLAIM_STEPS or time.monotonic() - claim["since"] > CLAIM_SECONDS:
            info.update(why="the screens after the claim did not come to an end (see debug/g_battle_claim_*.png)",
                        leave=True)
            return True
        spot = what = None
        for b in buttons:                            # a green or orange button: CLAIM, OK, NEXT ... (lowest first)
            text = button_label(shot, b)
            if BN.keep_off_label(text) or any(bad in text for bad in CLAIM_NOT):
                log(f"battle: claiming: not tapping the button '{text}'")
                continue
            spot = _frac_xy(BV.button_spot(b))
            what = f"the {b['color']} button '{text or 'label not read'}'"
            break
        if spot is None:
            words = BN.next_words(lines, k)
            if words:
                spot, what = (words[0][1], words[0][2]), f"'{words[0][0]}'"
        if spot is None:
            claim["idle"] += 1                       # an animation, or a screen that goes on with a tap anywhere
            if claim["idle"] < 2:
                return False
            spot, what = _frac_xy(CLAIM_TAP_ON), "the screen (nothing to tap is seen on it)"
        claim["idle"] = 0
        log(f"battle: claiming: tapping {what} at ({spot[0]}, {spot[1]})")
        S.tap(*spot)
        return False

    def popup_button(shot, lines):
        """A screen the bot does not know, with a green button: (x, y, label) when that button may be tapped.
        It may when its label says that it only takes the screen further (LET'S GO!, OK, CONTINUE, NEXT
        BATTLE ...), or when the label is not read and the button is where NEXT BATTLE is on a result screen.
        Never when the label says something else that is read (USE THIS PARTY, YES, JOIN ...) or when the
        screen is about buying, leaving or giving something away.  None: do not tap."""
        if BN.danger_words(lines):
            return None
        green = [b for b in BV.wide_buttons(shot) if b["color"] == "green"]
        if not green:                                # (not found as a button, but the place of NEXT BATTLE is green)
            if BV.result_button(shot):
                return _frac_xy(BV.TAP_NEXT) + ("label not read",)
            if BV.done_button(shot) and (BN.result_word(_result_words(shot)) or BN.result_kind(lines)):
                return _frac_xy(BV.TAP_DONE) + ("the check mark of the result screen",)   # (no NEXT BATTLE there)
            return None
        text = button_label(shot, green[0])
        if BN.keep_off_label(text) or any(bad in text for bad in CLAIM_NOT):
            return None
        x, y = _frac_xy(BV.button_spot(green[0]))
        if BN.go_on_label(text):
            return x, y, text
        if BV.result_button(shot) and green[0]["y0"] < BV.TAP_NEXT[1] < green[0]["y1"]:
            return x, y, f"{text or 'label not read'}, where NEXT BATTLE is"
        return None

    try:
        while True:
            step += 1
            if step >= max_steps:
                info["why"] = "too many steps"
                break
            if (stop and stop()) or time.monotonic() - t0 > max_seconds:
                info["why"] = "stopped or out of time"
                break
            shot = _settled(1.0 if step == 0 else 1.8)
            lines = [] if S.on_map(shot) else ocr_lines(shot, 100, None, 0.6)    # (the map needs no reading)
            kind = _battle_kind(shot, lines)
            if kind != "party":                          # (the party screen gets its own picture below)
                save_async(f"g_battle_s{step}.png", shot)
            if collect["taps"] and kind not in ("home", "party", "league", "map") and not claim["since"]:
                # a reward tile was collected and something else is on the screen: a Pokémon to catch (the
                # rewards of a set can be an encounter, 22 November) - leave it as it is, BACK would run away
                name, score = screen_class(shot)
                if name == "encounterScreen" and score >= TH_CLASS and not BN.battle_words(lines):
                    collect["catch"] = collect.get("catch", 0) + 1
                    if collect["catch"] >= 2:
                        save_async("g_battle_reward_catch.png", shot)
                        info.update(why="a Pokémon to catch came up as a reward of the set", leave=True,
                                    catch=True)
                        break
                    continue
            log(f"battle: step {step}: screen is {kind} ({BN.reads(lines, 90)})")
            if beat:
                beat()
            k = shot.shape[0] / 2208
            if kind in ("party", "league"):
                in_setup = True
            if leagues_only and kind == "league":
                info["leagues"] = BN.read_leagues(lines, shot.shape[1])
                save_async("g_leagues.png", shot)
                if info["leagues"]:
                    info["ok"] = True
                    log("leagues: " + ", ".join(f"{t} (max CP {c})" for t, c in info["leagues"]))
                else:
                    info["why"] = "the leagues on the list were not read (see debug/g_leagues.png)"
                break
            if leagues_only and kind == "party":         # (the game went to a party screen by itself: back)
                S.back()
                continue
            if kind == "party":
                info["ok"] = True
                info["title"] = BN.party_title(lines, k)
                info["members"] = BN.party_members(lines, names)
                info["use_spots"] = BN.party_use_spots(lines, k)
                save_async("g_battle_party.png", shot)
                break
            if kind == "map":
                taps["map"] += 1
                if taps["map"] > 3:
                    info["why"] = "the main menu does not stay open"
                    break
                S.tap(*MENU_BTN)
                tapped = True
            elif kind == "menu":
                if menu_spots is None:
                    menu_spots = BN.menu_battle_spots(lines, k)
                    if not menu_spots:
                        save_async("g_battle_menu.png", shot)
                        info["why"] = "the BATTLE tile is not in the main menu (see debug/g_battle_menu.png)"
                        break
                if not menu_spots:
                    info["why"] = "tapped every spot of the BATTLE tile and the Battle screen did not open"
                    break
                x, y = menu_spots.pop(0)
                log(f"battle: tapping BATTLE in the main menu at ({x}, {y})")
                S.tap(x, y)
                tapped = True
            elif kind == "welcome":                  # 'Welcome to the GO Battle League' (a new season): LET'S GO!
                popups += 1
                if popups > POPUP_TAPS:
                    info["why"] = "the pop-up 'Welcome to the GO Battle League' does not go away"
                    break
                green = [b for b in BV.wide_buttons(shot) if b["color"] == "green"]
                x, y = _frac_xy(BV.button_spot(green[0]) if green else WELCOME_BUTTON)
                log(f"battle: 'Welcome to the GO Battle League' - tapping LET'S GO! at ({x}, {y})"
                    + ("" if green else " (the button was not seen: its usual place)"))
                save_async("g_battle_welcome.png", shot)
                S.tap(x, y)
                tapped = True
            elif kind == "home" and BN.max_battles_today(lines):
                # 'You've reached the maximum number of battles for today.' (22 November, after the third set)
                save_async("g_battle_home.png", shot)
                info["why"] = "the game says: the maximum number of battles for today is reached"
                info["done_today"] = True
                break
            elif kind == "home":
                button = BV.home_button(shot)        # orange: claim first; green: BATTLE; None: not in view
                if button is None and BV.home_button_off(shot):
                    # The BATTLE button is grey.  First the rewards of the last set have to be collected: the
                    # gold tiles with COLLECT under them (22 November: two of them); after them the game asks to
                    # claim a new rank (the orange button, see above), and then a new set starts with a green
                    # BATTLE button.  Grey with nothing to collect: no set is left today.
                    tiles = BN.collect_spots(lines, shot.shape[0]) or [
                        (int(fx * shot.shape[1]), int(fy * shot.shape[0])) for fx, fy in BV.gold_tiles(shot)]
                    if tiles and collect["taps"] < COLLECT_TAPS:
                        collect["taps"] += 1
                        x, y = tiles[0]
                        log(f"battle: the BATTLE button is grey - collecting a reward first (COLLECT at ({x}, {y}))")
                        save_async(f"g_battle_collect_{collect['taps']}.png", shot)
                        S.tap(x, y)
                        tapped = True
                        continue
                    save_async("g_battle_home.png", shot)
                    info["why"] = "the BATTLE button is grey - the battles of today are done"
                    info["done_today"] = True
                    break
                label = BN.claim_label(lines, k)
                if (button is not None and button["color"] == "orange") or label:
                    claim["taps"] += 1               # something has to be claimed before the next battle
                    if claim["taps"] > CLAIM_TAPS:
                        info["why"] = f"the claim button of the Battle screen was tapped {CLAIM_TAPS} times and is still there"
                        break
                    if button is not None and button["color"] == "orange":
                        label = label or button_label(shot, button)
                        x, y = _frac_xy(BV.button_spot(button, 0.25))    # (not its middle: the round X is there)
                    else:
                        x, y = int(BN.HOME_BUTTON_FALLBACK[0][0] * k), int(BN.HOME_BUTTON_FALLBACK[0][1] * k)
                    log(f"battle: something has to be claimed before the next battle (button '{label or 'not read'}') "
                        f"- tapping it at ({x}, {y})")
                    save_async("g_battle_claim.png", shot)
                    S.tap(x, y)
                    tapped = True
                    if not claim["since"]:           # (the screens that follow take their time: allow for them)
                        max_steps += CLAIM_STEPS + CLAIM_TAPS
                        max_seconds += CLAIM_SECONDS
                    claim.update(since=time.monotonic(), steps=0, idle=0, catch=0)
                    scroll["down"] = 0
                    continue
                text = button_label(shot, button) if button is not None else ""
                if button is not None and (BN.premium_above(lines, button["y0"] * shot.shape[0])
                                           or any(bad in text for bad in CLAIM_NOT)):
                    # scrolled too far: this is the BATTLE button of the premium rewards (it costs a pass)
                    scroll["up"] += 1
                    if scroll["up"] > 2:
                        info["why"] = "only the BATTLE button of the premium rewards is in view - not tapping that one"
                        break
                    log(f"battle: the BATTLE button in view is the one of the premium rewards ('{text or 'label not read'}') "
                        "- not tapping it, scrolling back up")
                    S.swipe(*_frac_xy((0.5, HOME_SCROLL[0][1])), *_frac_xy((0.5, HOME_SCROLL[0][0])), HOME_SCROLL_MS)
                    tapped = True
                    continue
                if button is None:
                    # No button in view.  When a new set starts ('Choose a reward tier ...') the card is longer
                    # and the BATTLE button is below the lower edge of the screen: scroll down a little, so that
                    # the first BATTLE button comes into view (the basic rewards) and not the second one.
                    spots = [p for p in BN.home_battle_spots(ocr_lines(shot, 1500, None, 0.8), k)[:-len(BN.HOME_BUTTON_FALLBACK)]
                             if p[1] > 0.93 * shot.shape[0]]                   # (BATTLE at the very bottom, not in a sentence)
                    if spots and not scroll["down"] and taps["home"] < 2:      # (its label was read: tap that)
                        taps["home"] += 1
                        x, y = spots[0]
                        log(f"battle: tapping the BATTLE button at its label ({x}, {y})")
                        S.tap(x, y)
                        tapped = True
                        continue
                    if scroll["down"] < len(HOME_SCROLL):
                        y_from, y_to = HOME_SCROLL[scroll["down"]]
                        scroll["down"] += 1
                        if scroll["down"] == 1:
                            save_async("g_battle_home_top.png", shot)
                        log("battle: no BATTLE button in view on the Battle screen (a new set starts?) - scrolling down "
                            f"({scroll['down']} of {len(HOME_SCROLL)})")
                        S.swipe(*_frac_xy((0.5, y_from)), *_frac_xy((0.5, y_to)), HOME_SCROLL_MS)
                        tapped = True
                        continue
                    if claim["since"]:               # (after a claim: something that goes on with a tap?)
                        if after_claim(shot, lines, k):
                            break
                        tapped = True
                        continue
                    save_async("g_battle_home.png", shot)
                    info["why"] = "the BATTLE button was not found on the Battle screen (see debug/g_battle_home.png)"
                    break
                if claim["since"]:
                    log("battle: claimed - the BATTLE button is there")
                    claim["since"] = 0.0
                taps["home"] += 1
                if taps["home"] > HOME_TAPS:
                    info["why"] = f"the BATTLE button was tapped {HOME_TAPS} times and nothing happened"
                    break
                if taps["home"] == 1:
                    save_async("g_battle_home.png", shot)
                x, y = _frac_xy(BV.button_spot(button, 0.25 if taps["home"] % 2 else 0.75))   # (the X is over its middle)
                log(f"battle: tapping the BATTLE button at ({x}, {y})" + (f" ('{text}')" if text else "")
                    + (f" after scrolling down {scroll['down']}x" if scroll["down"] else ""))
                S.tap(x, y)
                tapped = True
            elif kind == "league":
                taps["league"] += 1
                spots = BN.league_lines(lines, league)
                if not spots:
                    save_async("g_battle_leagues.png", shot)
                    info["why"] = (f"the league '{league}' is not on the league list: "
                                   + BN.reads(lines, 120) + " (see debug/g_battle_leagues.png)")
                    break
                if taps["league"] > 2:
                    info["why"] = f"the league '{league}' was tapped but the party screen did not open"
                    break
                t, x, y = spots[0]
                log(f"battle: choosing the league '{t}' at ({x}, {y})")
                info["chosen"] = t                   # (the party screen that follows is the one of this league)
                S.tap(x, y)
            elif kind == "exit":
                _cancel_exit(lines)
            elif kind == "exit_battle":
                info["why"] = "a battle is going on (Exit the Trainer Battle?) - not touching it"
                break
            elif claim["since"] and kind == "other":             # the screens after the claim button
                if after_claim(shot, lines, k):
                    break
                tapped = True
            elif kind == "other" and popups < POPUP_TAPS and (found := popup_button(shot, lines)):
                popups += 1                  # a pop-up or a result screen with a button that takes it further
                x, y, text = found
                read = BN.reads(lines, 60)
                if text.startswith("the check mark"):
                    log(f"battle: a result screen is still there ({read}) - tapping {text} at ({x}, {y})")
                else:
                    log(f"battle: a screen with a green button ({read}) - tapping '{text}' at ({x}, {y})")
                save_async(f"g_battle_popup_{popups}.png", shot)
                S.tap(x, y)
                tapped = True
            else:                                    # something in the way, or still loading
                others += 1
                if others > 6:                     # (the league screens can take a while to load)
                    info["why"] = "an unknown screen (see debug/g_battle_s%d.png)" % step
                    break
                if not tapped:
                    S.back()
    finally:
        if info["ok"] and stay:
            pass                                     # (the caller starts the fight from the party screen)
        elif info.get("leave"):
            log("battle: the screen is left as it is (no BACK: that could throw a reward away)")
        elif not _battle_to_map(beat, in_setup):
            if restart:
                log("battle: could not get back to the map - restarting the game")
                S.restart_game()
            else:
                log("battle: could not get back to the map - the normal bot takes over")
    if not info["ok"] and not info["why"]:
        info["why"] = "unknown"
    return info


# ------------------------------- the fight ---------------------------------
# One battle: fight_battle() looks at the screen all the time (battle_vision.py: pictures, battle_nav.py: OCR),
# keeps the state in battle_fight.Fight and takes the decisions with the PvPoke rules of battle_engine.py.
FIGHT_START_SECONDS = 240      # "Finding opponent" and the loading screens before the fight can take a while
FIGHT_SECONDS = 480            # a 3 against 3 fight is over in about four minutes
FIGHT_TAP_MS = 70              # a fast attack is a tap anywhere
CHARGE_HOLD = 2.8              # s after the tap on a charged attack button: no other charged attack is thrown
GAME_BLOCK = 8.5               # ... and this long when the icons of its little game were seen (it takes about 9 s)
THROW_CHECK = 1.1              # s after the tap on a charged attack button: still lit = the tap did not count
THROW_RETRIES = 2              # ... tap again this many times at most
THROW_LATEST = 3.0             # s after the tap: the camera is on the attacker by now ("Get Ready!" comes after
                               # about 1.5 s).  Pictures of the plain fight that are taken later than this say that
PLAIN_PICTURES = (5, 2)        # the attack did not start: this many in a row (live video, screenshots)
ZOOM_PICTURES = (3, 1)         # ... and this many pictures of the camera on the attacker before anything is swiped
                               # that was not seen (the banner "Get Ready!" does not have to wait for them) ...
ZOOM_AFTER = 2.0               # ... and they only count this long after the tap: right after it the plain fight is
                               # still on the screen, and its HP bars are not read on every picture
BARS_ONLY = (20, 2)            # the fight has not been recognised by its name boxes, but both HP bars are on this
                               # many pictures in a row (live video, screenshots): fight on the HP bars
HELD_LIT = 5                   # a charged attack that waits for the other side's: its button lit again on this many
                               # pictures in a row = it was not thrown after all
HELD_BACK = (15, 2)            # ... and so it was when the plain fight (both HP bars) is back on this many pictures
# The fast attacks are tapped ON the button of the charged attack that is to be thrown the moment it is ready
# (battle_fight.Fight.aim): a tap on a button that is not ready is a fast attack, the first one after it is ready
# throws it.  Seeing the button light up and tapping it then takes more than half a second - a turn or two.
FIGHT_AIM = os.environ.get("GAMEBOT_FIGHT_AIM", "1") != "0"      # (0: the fast attacks stay in the middle)
AIM_RECENT = 4.0               # 'Get Ready!' this long after the last tap on a button: that tap threw the attack
AIM_CHECK = 10.0               # s of taps on a button without the foe's HP going down at all: they do not count
                               # there as fast attacks (then the middle of the screen is tapped again)
GIVE_UP_LOOKS = 4              # a fight is given up when it was found lost this many times in a row ...
GIVE_UP_EVERY = 0.8            # ... looked at this many seconds apart
GIVE_UP_WAIT = 3.5             # s to wait for the question 'Exit the Trainer Battle?' after the tap on the button
FIGHT_VIDEO = os.environ.get("GAMEBOT_FIGHT_VIDEO", "1") != "0"   # the live video in a fight (0: screenshots only)
RETAP_AFTER = 0.8              # a question that is still on the screen this long after the answer: tap again (a
                               # tap is lost now and then, and the shield question only waits five seconds)
RETAP_MAX = 3                  # ... at most this many times
BALLS_FRESH = 120.0            # s: the Poké Balls of the name boxes that were seen this long ago still count (they
                               # are only read in the plain fight, and a count only goes down)
READY_RECENT = 3.0             # s: a charged attack button of ours that was ready this short ago "is ready" when
                               # the shield question comes up (the question hides the buttons)
USED_FROM, USED_UNTIL = 4.0, 11.0      # s after the shield question: the banner 'X used Y!' is looked for (it
USED_EVERY = 0.35                      # comes after about six seconds and stays for two), a picture every ... s
MAP_PICTURES, MAP_SECONDS = 3, 2.0   # the fight loop ends on the map: this many pictures in a row, this long
SWITCH_TAP_MS = 220            # the tile of 'Switch in a new Pokémon?' is pressed this long ...
SWITCH_TAP_Y = (0.74, 0.78, 0.71, 0.81)   # the heights of the tile that are tried in turn
SWITCH_TOUCHES = (("quick tap", lambda x, y: S.tap_quick(x, y), ()),
                  ("finger down and up", lambda x, y: S.tap_motion(x, y), ()),
                  ("press 60 ms", lambda x, y, ms: S.tap(x, y, ms), (60,)),
                  ("press 220 ms", lambda x, y, ms: S.tap(x, y, ms), (220,)))
SWITCH_RETAPS = 13             # ... and tapped again (every RETAP_AFTER s) for as long as the question stays: in the
                               # first seconds, while our Pokémon faints, the game does not seem to take the tap -
                               # three taps in 3.5 s were ignored again and again, the game then chose by itself
RESULT_SETTLE = 0.7            # s the button of a result screen has to be there before it is tapped (it fades in)
THEIR_ATTACK = 12.0            # s after a question: name boxes without an HP bar are the banner of their attack,
OUR_ATTACK = 4.0               # ... and this long after our little game the banner of ours - not the plain fight
ATTACK_EDGES = 1.5             # s of plain fight that are counted for the time a charged attack took (its edges)
PRE_FIGHT_TAPS = 25.0          # fast attacks start at the VS screen already (taps before the fight are ignored)
FIGHT_WAIT_LOOK = 8.0          # unknown screen this long (before the fight / after it): read it


def _frac_xy(p):
    """A position as fractions of the screen -> canvas pixels for S.tap."""
    return int(p[0] * S.REF_W), int(p[1] * S.REF_H)


class FastTapper(threading.Thread):
    """Fast attacks: tap, tap, tap anywhere on the fight screen.  A screenshot takes a second or more, so
    the tapping goes on by itself in the background while the main loop looks at the pictures (go() / pause()).

    Every tap is an 'adb shell input' command of its own; two of them at the same time spoil each other (a
    finger that goes down twice without lifting).  So there is one lock: the taps of the main loop (tap():
    charged attack button, shield, switch, NEXT BATTLE) wait for the fast tap that is running and go first.

    sweep(planner): the little game of a charged attack.  While a planner is set the thread asks it what to
    swipe now and swipes that instead of tapping; when it gives nothing the fast taps go on."""

    def __init__(self, xy, ms=FIGHT_TAP_MS):
        super().__init__(daemon=True, name="fast-tapper")
        self.xy, self.ms = xy, ms
        self._on = threading.Event()
        self._hold = threading.Event()         # the main loop wants to tap: the fast taps wait
        self._lock = threading.Lock()
        self._quit = False
        self._sweep = None                     # gives the swipes of the little game (see sweep())
        self._aim = None                       # where the fast attacks are tapped instead of xy (see aim())
        self.taps = 0
        self.swipes = 0

    def run(self):
        while not self._quit:
            if self._hold.is_set():
                time.sleep(0.01)
                continue
            planner = self._sweep
            if planner is not None:
                try:
                    strokes = planner()
                except Exception:  # noqa: BLE001
                    strokes = []
                if strokes:
                    try:
                        with self._lock:
                            if self._sweep is planner and not self._hold.is_set():
                                S.swipes(strokes)
                                self.swipes += len(strokes)
                    except Exception:  # noqa: BLE001
                        time.sleep(0.3)
                    continue
            if not self._on.wait(0.2):
                continue
            try:
                with self._lock:
                    if self._on.is_set() and not self._hold.is_set():
                        x, y = self._aim or self.xy
                        S.tap(x, y, self.ms)
                        self.taps += 1
            except Exception:  # noqa: BLE001
                time.sleep(0.5)

    def tap(self, x, y, ms=120):
        """A tap of the main loop: after the fast tap that is running, before the next one."""
        self._hold.set()
        try:
            with self._lock:
                S.tap(x, y, ms)
        finally:
            self._hold.clear()

    def do(self, fn, *args):
        """Like tap(), for another kind of touch: fn(*args) after the fast tap that is running."""
        self._hold.set()
        try:
            with self._lock:
                fn(*args)
        finally:
            self._hold.clear()

    def sweep(self, planner):
        """planner(): -> [(x1, y1, x2, y2, ms), ...] on the canvas, the swipes to make now ([]: none).
        None: no little game any more."""
        self._sweep = planner

    def aim(self, xy):
        """Tap the fast attacks at xy (the button of a charged attack that is to be thrown the moment it is
        ready) instead of the usual place; None: the usual place again."""
        self._aim = xy

    def go(self):
        self._on.set()

    def pause(self):
        self._on.clear()

    def close(self):
        self._quit = True
        self._sweep = None
        self._on.clear()


def _fight_box(shot, side):
    """(name, cp) from one of the two name boxes at the top (mine on the left, the foe's on the right)."""
    h, w = shot.shape[:2]
    x0, x1 = (0.03, 0.39) if side == "me" else (0.60, 0.97)
    crop = shot[int(0.108 * h):int(0.150 * h), int(x0 * w):int(x1 * w)]
    crop = cv2.copyMakeBorder(crop, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    return BN.name_box(ocr_lines(crop))


def _fight_look(shot, fight, lock):
    """Read what the fight asks for: the name boxes (who is on the field) now and then, the labels under
    the charged attack buttons after a new Pokémon came in.  The reading (OCR, seconds on a Pi) is done outside
    the lock, what it finds is put into the fight inside it."""
    with lock:
        due, labels = fight.foe_due, fight.need_labels
    found = None
    if due:
        name, cp = _fight_box(shot, "foe")
        mine = _fight_box(shot, "me")[1]
        found = bool(name)
        with lock:
            fight.set_foe(name, cp)
            fight.set_active(mine)
    if labels:
        h, w = shot.shape[:2]
        left, right = BN.button_texts(ocr_lines(shot, int(0.895 * h), int(0.96 * h), 1.0), w)
        with lock:
            fight.set_buttons(left, right)
    return found


def _banner_text(pic):
    """The words of the banner at the top of a fight ('Mismagius used Dark Pulse!'): white letters on a grey
    see-through box with the sky behind it (the box makes the clouds behind it grey: they are not pure white
    any more).  '' when there is nothing to read."""
    return white_words(pic, 0.05, 0.150, 0.95, 0.210)


def _result_words(pic):
    """The big white words in the middle of the result screen of a battle: 'YOU WIN!' or 'GOOD EFFORT!' (two
    lines).  They stand over the trainer; read with the rest of the screen they come out in pieces ('GOOD.',
    'WIN!', 'YOU W IN'), read on their own they are read whole."""
    return white_words(pic, 0.12, 0.40, 0.88, 0.61, lines=2, wide=1100.0)


class FightLooker(threading.Thread):
    """Reads the name boxes and the button labels next to the main loop.  The OCR takes seconds on a Pi, and the
    main loop must not wait for that: a charged attack or a shield is worth more than a name.  It also reads
    the banner of the foe's charged attack ('Mismagius used Dark Pulse!', see read_banner())."""

    def __init__(self, fight, lock):
        super().__init__(daemon=True, name="fight-looker")
        self.fight, self.lock = fight, lock
        self._shot = None
        self._wake = threading.Event()
        self._busy = False
        self._quit = False
        self.empty = 0                         # name boxes that gave nothing, in a row
        self.video = False                     # the pictures come from the live video (small text is hard to read)
        self._what = "names"                   # what the picture that waits is to be read for
        self.used_at = 0.0                     # when a banner last named a charged attack of the foe

    def read_banner(self, shot):
        """A picture taken while the banner of the foe's charged attack can be up ('X used Y!', about six
        seconds after the shield question, for two seconds): read it when the last reading is finished.  What
        it says goes to fight.foe_used(); used_at tells the fight loop that an attack was named."""
        if self._busy or self._quit:
            return
        self._shot, self._what, self._busy = (shot() if callable(shot) else shot), "banner", True
        self._wake.set()

    def ask(self, shot):
        """A picture of the fight; used when something is to be read and the last reading is finished.
        shot: the picture, or a function that gives it (so that it is only made when it is needed)."""
        if self._busy or self._quit:
            return
        with self.lock:
            wanted = self.fight.foe_due or self.fight.need_labels
        if wanted:
            self._shot, self._what, self._busy = (shot() if callable(shot) else shot), "names", True
            self._wake.set()

    def run(self):
        while not self._quit:
            if not self._wake.wait(0.3):
                continue
            self._wake.clear()
            shot, self._shot = self._shot, None
            if shot is None:
                self._busy = False
                continue
            try:
                if self._what == "banner":
                    text = _banner_text(shot)
                    if text:
                        with self.lock:
                            move = self.fight.foe_used(text)
                        if move is not None:
                            self.used_at = time.monotonic()
                    continue
                if self.empty >= 2 and self.video:     # (the video picture is too small for this text: a real one)
                    self.empty = 0
                    try:
                        shot = S.screenshot()
                    except Exception:  # noqa: BLE001
                        pass
                found = _fight_look(shot, self.fight, self.lock)
                if found is not None:
                    self.empty = 0 if found else self.empty + 1
            except Exception as e:  # noqa: BLE001
                log(f"battle: reading the name boxes failed: {type(e).__name__}: {e}")
            finally:
                self._busy = False

    def close(self):
        self._quit = True
        self._wake.set()


def _fight_sleep(seconds, beat, stop):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not (stop and stop()):
        if beat:
            beat()
        time.sleep(min(0.5, max(end - time.monotonic(), 0)))


def _fight_stream():
    """The live video of the phone for this fight (battle_stream.py), or None when it cannot be started."""
    if not FIGHT_VIDEO:
        return None
    S.live_stop()                              # (the video for looking: the fight has one of its own)
    try:
        import battle_stream as BS
        size = BS.video_size(S.screen["w"], S.screen["h"])
        stream = BS.FrameStream(size, display_id=S.screen.get("id"))
        stream.start()
        return stream
    except Exception as e:  # noqa: BLE001
        log(f"battle: no live video ({e}) - taking screenshots")
        return None


VIEW = (704, int(round(704 * S.REF_H / float(S.REF_W) / 16.0)) * 16)   # the picture the readers of a fight look at


class Eyes:
    """The pictures of the fight.  A screenshot takes 1 to 3 seconds on the phone, which is too slow for a question
    that is on the screen for five seconds, so the live video is used (about ten pictures a second, see
    battle_stream.py) and a screenshot only when no video comes.  look() gives (picture on the 1768 x 2208
    canvas, the small picture the readers use, when it came in): the readers (battle_vision) are six times as
    fast on the small picture, the text readers and the rest of the bot use the canvas.  video: the last
    picture came from the live video (it is fresh, but too small for small text)."""

    def __init__(self, stream):
        self.stream = stream
        self.seq = 0
        self.live = self.shots = 0
        self.mode = ""
        self.video = False
        self._said = 0.0                    # when the reason for the missing video was last logged ...
        self._told = 0                      # ... and how often

    def look(self, not_before=0.0):
        got = None
        if self.stream is not None and self.stream.healthy():
            got = self.stream.wait_new(self.seq, 1.0, not_before)
            if got is None and self.live and self.stream.starting():
                # (screenrecord stops by itself every three minutes and is started again: its pictures are
                # back within a second or two, a screenshot would take longer)
                got = self.stream.wait_new(self.seq, 2.5, not_before)
        if got is not None:
            self.seq, t, small = got
            self._mode("live video", f"{small.shape[1]}x{small.shape[0]}")
            self.live += 1
            self.video = True
            canvas = cv2.resize(small, (S.REF_W, S.REF_H), interpolation=cv2.INTER_LINEAR)
        else:
            self._mode("screenshots")
            if self.stream is not None and self._told < 3 and time.monotonic() - self._said >= 30.0:
                self._said = time.monotonic()      # (why does the video not come?  the programs' own words)
                self._told += 1
                log("battle: the live video gives no pictures: " + self.stream.describe())
            canvas = S.screenshot()
            small = cv2.resize(canvas, VIEW, interpolation=cv2.INTER_AREA)
            self.shots += 1
            self.video = False
            t = time.monotonic()
        return canvas, small, t

    def _mode(self, mode, note=""):
        if mode != self.mode:
            self.mode = mode
            log("battle: pictures from the " + mode + (f" ({note})" if note else "")
                if mode == "live video" else "battle: no live video - the pictures are screenshots (slow)")

    def real(self, canvas):
        """A real screenshot for reading text (the video picture is small); the canvas itself when that is a
        screenshot already, or when taking one fails."""
        if not self.video:
            return canvas
        try:
            return S.screenshot()
        except Exception:  # noqa: BLE001
            return canvas

    def close(self):
        if self.stream is not None:
            self.stream.close()


def stream_test(seconds=8.0):
    """gamebot.py streamtest: start the live video for a few seconds and say what came out of it."""
    stream = _fight_stream()
    if stream is None:
        log("streamtest: the live video could not be started (GAMEBOT_FIGHT_VIDEO=0, or see the line above)")
        return False
    t0 = time.monotonic()
    first = None
    last = None
    seq = 0
    try:
        while time.monotonic() - t0 < seconds:
            got = stream.wait_new(seq, 1.0)
            if got is None:
                if stream.failed:
                    break
                continue
            seq, t, last = got
            first = first if first is not None else t - t0
        n = stream.frames
        if last is None:
            log("streamtest: NO pictures in %.0f s: %s" % (seconds, stream.describe()))
            return False
        log(f"streamtest: {n} pictures in {seconds:.0f} s ({n / seconds:.1f} per second), the first after "
            f"{first:.1f} s, size {last.shape[1]}x{last.shape[0]}")
        S.debug_save("g_stream.png", last)
        log("streamtest: picture saved as ~/debug/g_stream.png; " + stream.describe())
        return True
    finally:
        stream.close()


def _question_seen(feat):
    """Which question a picture with the countdown shows, as far as the picture itself tells: 'shield' (the big
    lilac shield), 'switch' (its countdown sits lower than that of the other questions, between the name
    boxes) or ''."""
    return "shield" if feat.get("hex") else "switch" if feat.get("count") == "switch" else ""


def _fight_answer(shot, feat, fight, lock, tapper, state, eyes=None, know=None):
    """The countdown ring is up: find out which question it is and answer it.  state: {"unknown": n}.
    Returns None when the question was not read (look again at the next picture), otherwise {"xy": where was
    tapped (None: nothing), "kind": "shield" / "noshield" / "switch"}.  The shield question is known from its
    picture (the big lilac shield): the answer has to be tapped within the five seconds of the countdown, there
    is no time to read text first.  The switch question is known from its picture too: its countdown sits at
    another place, and its tiles stand in party order.  What is left is read as text from the picture at hand
    (the words are big enough for the picture of the video; eyes: where the picture came from).  know: what
    the fight loop knows for the shield question - {"foes": how many Pokémon the foe has left (None: not
    known), "ready": a charged attack of ours was ready when the question came}."""
    import battle_vision as BV

    def read(pic):
        h = pic.shape[0]
        return (BN.question_kind(ocr_lines(pic, int(0.44 * h), int(0.60 * h), 1.0))
                or BN.question_kind(ocr_lines(pic, int(0.40 * h), int(0.66 * h), 0.8)))

    video = eyes is not None and eyes.video
    kind = _question_seen(feat) or read(shot)
    sure = bool(kind)                                   # (seen or read, not only taken for a question)
    if not kind:                                        # not read: look again at the next picture
        state["unknown"] = state.get("unknown", 0) + 1
        if state["unknown"] < 2:
            return None
        with lock:
            kind = "shield" if fight.my_shields > 0 else "noshield"   # (twice in a row: a question we must not miss)
        log(f"battle: the question was not read - taking it for '{kind}'")
    state["unknown"] = 0
    h, w = shot.shape[:2]
    xy = None
    if kind == "noshield":
        log("battle: an attack is coming and we have no shields left")
        with lock:
            fight.foe_threw(sure)
    elif kind == "shield":
        with lock:
            if feat.get("hex") and fight.my_shields <= 0:
                fight.my_shields = 1                     # (the game offers a shield: the count we kept was too low)
            had = fight.foe_energy()
            use, why = fight.shield((know or {}).get("foes"), bool((know or {}).get("ready")))
            fight.foe_threw(sure)                        # (its energy goes down by what the attack costs)
            if had is not None and "at most" not in why:   # (for whoever reads the log: what the count said)
                why += f" ({fight.foe.label} has {int(had)} energy at most)"
        log(f"battle: shield question - {'SHIELD' if use else 'no shield (NOT NOW)'}: {why}")
        xy = _frac_xy(BV.TAP_SHIELD if use else BV.TAP_NOT_NOW)
        tapper.tap(*xy)
    elif kind == "switch":
        # The tiles stand in party order, so nothing has to be read to know which is which - and there is no
        # time to read: the countdown of this question does not always start at 12 (when the other side's
        # Pokémon fainted a few seconds before ours, 3 seconds were left; the game then chose by itself).
        # Only a real screenshot is read for its CP numbers (they are too small on the video picture).
        tiles = [] if video else BN.popup_tiles(ocr_lines(shot, int(0.60 * h), int(0.70 * h), 1.0))
        shown_n = BV.popup_tiles_shown(shot)             # (the tiles on the screen, not our count of who is left)
        with lock:
            idx, mon, why = fight.switch(tiles, shown_n)
            place, n = fight.tile
            n = max(n, shown_n)
        if mon is None:
            log("battle: our Pokémon fainted and nobody is left")
        else:
            if idx is not None:
                x = tiles[idx][1]
            else:                                        # its CP was not read: the tiles stand in party order
                x = int((0.5 if n < 2 else BV.POPUP_TILES[min(place, 1)]) * w)
            log(f"battle: switching to {mon.label} - {why}")
            xy = (int(x * S.REF_W / w), int(BV.POPUP_TILE_Y * S.REF_H))
            tapper.tap(*xy, SWITCH_TAP_MS)
    return {"xy": xy, "kind": kind}


def _result_spot(pic):
    """Where to tap on the result screen of a battle, and what that is: NEXT BATTLE when that button is there,
    otherwise the round button with the check mark under it.  That one was the only button after the first
    battle that was won - probably because it was the last of its set of five; it leads to the Battle screen."""
    import battle_vision as BV
    if not BV.result_button(pic) and BV.done_button(pic):
        return _frac_xy(BV.TAP_DONE), "the check mark"
    return _frac_xy(BV.TAP_NEXT), "NEXT BATTLE"


def _fight_give_up(tapper, eyes, why, beat=None):
    """Give up the battle: tap the button with the running trainer (top left) and answer the question 'Exit the
    Trainer Battle?' with YES.  The question is known by its green YES button in the middle of the screen (a fight
    has no green buttons; nothing is read, that would take seconds).  Returns True when YES was tapped; False
    when the question did not come up - then nothing happened and the fight goes on."""
    import battle_vision as BV
    log(f"battle: giving up - {why}")
    tapper.aim(None)
    tapper.pause()
    shot = None
    try:
        shot, small, _t = eyes.look()
        if BV.exit_yes(small):                           # (something green is there already: not a question)
            log("battle: not giving up after all - the place of the YES button is green before the question")
            return False
        tapper.tap(*_frac_xy(BV.RUN_BUTTON))
        end = time.monotonic() + GIVE_UP_WAIT
        seen = 0
        while time.monotonic() < end:
            shot, small, _t = eyes.look()
            if beat:
                beat()
            spot = BV.exit_yes(small)
            seen = seen + 1 if spot else 0
            if spot and seen >= (2 if eyes.video else 1):    # (twice on the video: no flicker)
                save_async("g_battle_giveup.png", shot)
                tapper.tap(*_frac_xy(spot))
                log("battle: 'Exit the Trainer Battle?' - YES")
                return True
        log("battle: the question to leave the battle did not come up - fighting on")
    except Exception as e:  # noqa: BLE001
        log(f"battle: giving up failed ({type(e).__name__}: {e}) - fighting on")
    if shot is not None:
        save_async("g_battle_giveup.png", shot)
    return False


MINIGAME_FILE = os.path.expanduser("~/battle_minigame.json")   # what the little games of earlier fights taught
SWEEP_SECONDS = 0.6            # the swipes of the little game are sent in pieces of about this long


def load_minigames():
    """{type: {"gates": [...], "rows": [...]}}: where the icons of the little game of a charged attack came by
    in earlier fights (for the types that battle_minigame.py does not know from recordings)."""
    try:
        with open(MINIGAME_FILE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_minigames(d):
    try:
        with open(MINIGAME_FILE, "w") as f:
            json.dump(d, f, indent=1)
    except OSError:
        pass


SEEN_FILE = os.path.expanduser("~/battle_seen.json")   # the charged attacks opponents were seen to use


def load_seen():
    """{species: {charged attack: in how many battles it was seen}}: what the opponents of earlier battles
    really used (read from the banner 'Whiscash used Blizzard!').  It goes before the moveset that is guessed
    for a species - the players of a league do not all use the recommended one."""
    try:
        with open(SEEN_FILE) as f:
            d = json.load(f)
        return {str(k): {str(m): int(n) for m, n in v.items()} for k, v in d.items() if isinstance(v, dict)}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def save_seen(d):
    try:
        with open(SEEN_FILE + ".tmp", "w") as f:
            json.dump(d, f, indent=1, sort_keys=True)
        os.replace(SEEN_FILE + ".tmp", SEEN_FILE)
    except OSError:
        pass


class Minigame:
    """The little game of one charged attack (see battle_minigame.py): the fight loop gives it the pictures
    (see()), the tapper thread asks it for the swipes (strokes())."""

    def __init__(self, move, t0, learned=None, button=0):
        import battle_minigame as BMG
        import battle_vision as BV
        self.BMG, self.BV = BMG, BV
        self.move = move
        self.button = button               # the charged attack button that was tapped (0: left, 1: right)
        self.game = BMG.Game(move.type, t0, (learned or {}).get(move.type))
        self.lock = threading.Lock()
        self.on = False                    # its icons were seen: the attack was thrown, the little game runs
        self.saved = False                 # a picture of it was saved for checking
        self.mon = None                    # the Pokémon that threw it (set by the fight loop)
        self.held = False                  # the other side's attack went first: ours is waited for (see hold())
        self.asked = 0.0
        self.lit = 0                       # ... pictures in a row on which its button was lit again meanwhile
        self.plain = 0                     # pictures in a row that show the plain fight (see view())
        self.zoomed = 0                    # ... and that show the camera on the attacker
        self.game.plain = True             # (nothing is swiped blind before the camera was seen there)
        self.doubt = False                 # the attack did not start in time: its icons are still watched for,
                                           # nothing is swiped blind and the next throw does not wait for it
        self.late = False                  # ... and they came after all
        self.ready = False                 # the banner 'Get Ready!' was seen: the attack does start (see started())
        self.back = 0                      # (held) pictures of the plain fight with both HP bars since the question
        self.unseen = False                # nobody saw it being thrown: it is known from 'Get Ready!' alone
        self.alt = None                    # ... and it may be this other attack of ours (the icons will tell)
        self.alt_n = 0                     # ... pictures in a row with the icons of that other attack
        self.race = False                  # ... because the fast taps were on the other button (not the labels)

    def look(self, small):
        """The icons of the attack's type on a picture (fractions of the screen).  A lit charged attack button
        of the same type looks like an icon, so what is found at a button only counts when the picture clearly
        shows the little game: three icons or more, or two away from the buttons (then self.on is set: the
        attack was thrown, the little game runs)."""
        BV = self.BV
        aspect = small.shape[0] / float(small.shape[1])
        found = self.BMG.find_icons(small, self.game.kind)
        away = [p for p in found if not any(abs(p[0] - bx) < 0.10 and abs(p[1] - BV.BTN_Y) * aspect < 0.10
                                            for bx in BV.BTN_X)]
        if len(away) >= 2 or len(found) >= 3:
            self.on = True
            return found
        return away

    def others(self, small):
        """The icons of the other attack (self.alt) on a picture; what is found at a charged attack button does
        not count (a button that is ready looks like an icon of its type)."""
        BV = self.BV
        aspect = small.shape[0] / float(small.shape[1])
        return [p for p in self.BMG.find_icons(small, self.alt.type)
                if not any(abs(p[0] - bx) < 0.10 and abs(p[1] - BV.BTN_Y) * aspect < 0.10 for bx in BV.BTN_X)]

    def see(self, icons, t):
        """The icons of a picture of the live video that came in at time t (for the swipes)."""
        with self.lock:
            self.game.see(t, icons)

    def strokes(self):
        """The swipes to make now, on the canvas (asked by the tapper thread)."""
        with self.lock:
            plan = self.game.plan(time.monotonic())
        out, total = [], 0.0
        for x1, y1, x2, y2, ms in plan:
            out.append((int(x1 * S.REF_W), int(y1 * S.REF_H), int(x2 * S.REF_W), int(y2 * S.REF_H), ms))
            total += ms / 1000.0 + 0.06
            if total >= SWEEP_SECONDS:
                break
        return out

    def over(self, now):
        with self.lock:
            return self.game.over(now)

    def view(self, fight, bars, need=1, now=None):
        """Tell the game what the newest picture shows.  fight: the name boxes are on it.  bars: an HP bar is.
        Both: the plain fight, the attack has not started (yet).  The name boxes without any HP bar: the camera
        is on the attacker, that is the charged attack (from 'Get Ready!' until it is over).  The known lines of
        the attack's type are swiped without their icons being seen from the banner 'Get Ready!' on (started())
        - or, when the banner was not seen, after `need` pictures of the camera on the attacker that were taken
        ZOOM_AFTER seconds or more after the tap (now: the time of the picture).  Never over the plain fight:
        the rows of some types run right over the charged attack buttons, a blind swipe there would throw
        whatever lights up.  Returns the number of pictures of the plain fight in a row."""
        if fight and bars:
            self.plain, self.zoomed = self.plain + 1, 0
        elif fight:
            self.plain, self.zoomed = 0, self.zoomed + 1
        else:                              # (an animation, a flash, a banner over the name boxes: no plain
            self.plain = self.zoomed = 0   # fight, and not the camera on the attacker either)
        zoom = self.zoomed >= need and (now is None or now - self.game.t0 >= ZOOM_AFTER)
        with self.lock:                    # (after 'Get Ready!' only the plain fight itself stops the swipes)
            self.game.plain = self.plain > 0 or not (self.ready or zoom)
        return self.plain

    def started(self, now):
        """The banner 'Get Ready!' is on the picture: the attack starts, its icons come within a second or two.
        From now on what is known of its type is swiped - also when it had to wait for the other side's attack
        or was given up.  True the first time."""
        if self.ready or self.on:
            return False
        self.ready = True
        with self.lock:
            self.game.started(now)
        return True

    def give_up(self):
        """The attack did not start in time (the plain fight is still on the pictures): from now on only icons
        that are seen are swiped, should it start after all."""
        self.doubt = True
        with self.lock:
            self.game.blind = False

    def hold(self, now):
        """A question came up before the icons did: the other side's charged attack goes first, ours comes
        after it (when both are thrown in the same turn) or not at all.  It is waited for; only icons that are
        seen are swiped."""
        self.held = True
        self.asked = now                   # (when the question was last on the screen)
        with self.lock:
            self.game.hold(now)

    def report(self):
        g = self.game
        text = (f"battle: little game of {self.move.name} ({g.kind}): icons on {g.pictures} picture(s), "
                f"{g.swipes} swipes planned")
        if self.held:
            text += ", it had to wait for the other side's attack"
        if self.unseen:
            text += ", thrown by a tap of the fast attacks on its button"
        if self.doubt:
            text += ", it did not start after the tap" + (" but came later" if self.on else "")
        if g.gate:
            text += f", the stream crossed {g.gate}"
        rows = [tuple(round(float(v), 2) for v in r) for r, t in g.rows.items() if t is not None]
        if rows:
            text += f", rows seen {rows}"
        if not g.pictures and g.swipes:
            text += " - no icons seen: what is known of this type was swiped"
        return text


# ------------------------------- Team GO Rocket ----------------------------------
# A grunt or a leader at a PokéStop (23 November, a recording of a fight with Leader Cliff by hand):
# speech bubbles -> the screen with BATTLE -> 'Use your Rocket Radar?' (YES) -> 'Recommended Battle Party' with
# USE THIS PARTY (a slot without a Pokémon: tapped, the first Pokémon of the list, DONE) -> VS -> the fight:
# the same name boxes and HP bars as in the Battle League, but a Pokémon with one charged attack has ONE button,
# in the middle, and the next one comes in by itself -> speech bubble, rewards, SUMMARY -> the Shadow Pokémon
# to catch (Premier Balls: the normal catching does that).
ROCKET_BTN_X = (0.307, 0.50, 0.690)    # the charged attack buttons: left, middle (one attack only), right
ROCKET_PARTY_X = (0.33, 0.51, 0.69)    # the three slots of 'Recommended Battle Party'
ROCKET_LIST_FIRST = (0.18, 0.70)       # the first Pokémon in the list that a slot opens
ROCKET_BATTLE_X = 0.33                 # BATTLE on the screen before the fight: left of the round X over its middle
ROCKET_FIGHT_SECONDS = 300
ROCKET_STEPS = 70


class _Kind:
    """A charged attack known only by its type (the little game needs no more)."""

    def __init__(self, kind):
        self.type, self.name, self.id, self.energy = kind, f"a {kind} attack", kind.upper(), 50


def _rocket_kinds(name):
    """The types of the charged attacks a Pokémon of this name can have ('' when the name is not known)."""
    import battle_engine as BE
    sp = BE.find_species(name) if name else None
    if not sp:
        return set()
    data = BE.load()
    row = data["mons"].get(sp)
    if not row:
        return set()
    return {str(BE.Move(m).type).lower() for m in row[6] if m in data["moves"]}


def rocket_fight(stop=None):
    """The fight against Team GO Rocket, until its HUD is gone for a while.  The fast attacks are tapped on
    the charged attack buttons, by turns on the middle one (a Pokémon with one charged attack) and the left
    one (with two): a button that is ready throws its attack at the next tap, a button that is not ready is a
    fast attack.  The little game is known by its icons: of the types that the charged attacks of our Pokémon
    can have (its name is read in its name box), the one whose icons come up.  Every 'Use a Protect Shield?'
    gets a shield.  Returns the seconds it took."""
    import battle_fight as BF
    import battle_minigame as BMG
    import battle_vision as BV
    S.busy(ROCKET_FIGHT_SECONDS)
    eyes = Eyes(_fight_stream())
    tapper = FastTapper(_frac_xy(BV.TAP_FAST))
    tapper.start()
    t0 = time.monotonic()
    last_hud = started = None
    mini, game_at, shield_at, games, shields = None, -100.0, -100.0, 0, 0
    me, kinds, named_at, turn = "", set(), -100.0, 0
    aims = [_frac_xy((ROCKET_BTN_X[1], BV.BTN_Y)), _frac_xy((ROCKET_BTN_X[0], BV.BTN_Y))]
    try:
        while time.monotonic() - t0 < ROCKET_FIGHT_SECONDS and not (stop and stop()):
            canvas, small, t = eyes.look()
            now = time.monotonic()
            st = BF.state(BV.features(small))
            if mini is not None:                         # its little game: the icons, the swipes
                mini.see(mini.look(small), t)
                if mini.game.over(now) or now - game_at > 14:
                    tapper.sweep(None)
                    log("rocket: " + mini.report().replace("battle: ", ""))
                    mini = None
                    tapper.go()
                continue
            if st == "prompt":
                tapper.pause()
                if BV.shield_question(small) and now - shield_at > 6:
                    shield_at = now
                    shields += 1
                    log("rocket: an attack is coming - SHIELD")
                    tapper.tap(*_frac_xy(BV.TAP_SHIELD))
                continue
            if st == "fight":
                last_hud = now
                if started is None:
                    started = now
                    log("rocket: the fight has started")
                if now - named_at > 6:                   # who is ours on the field (its attacks: their types)
                    named_at = now
                    name = (_fight_box(canvas, "me") or ("", 0))[0]
                    if name and name != me:
                        me, kinds = name, _rocket_kinds(name)
                        log(f"rocket: ours is {me} - its charged attacks can be: "
                            f"{', '.join(sorted(kinds)) or 'not known'}")
                turn += 1
                tapper.aim(aims[(turn // 4) % 2])        # (4 pictures on a button, then the other)
                tapper.go()
                continue
            # no HUD: the little game of our charged attack?  (or theirs, a flash, the end)
            if started is not None and now - game_at > 8:
                for kind in (kinds or set(BMG.TYPE_RGB)):
                    if len(BMG.find_icons(small, kind)) >= 3:
                        games += 1
                        game_at = now
                        mini = Minigame(_Kind(kind), now - 1.0, load_minigames(), 0)
                        mini.see(mini.look(small), t)
                        tapper.aim(None)
                        tapper.sweep(mini.strokes)
                        log(f"rocket: the little game of a {kind} attack")
                        break
                if mini is not None:
                    continue
            if started is not None and now - last_hud > 10 and now - game_at > 10:
                break                                    # the fight is over (speech bubble, rewards, ...)
            if started is None and now - t0 > 40:
                log("rocket: no fight came")
                break
    finally:
        tapper.sweep(None)
        tapper.close()
        eyes.close()
        S.busy(0)
    secs = int(time.monotonic() - t0)
    log(f"rocket: fight ended after {secs} s ({tapper.taps} fast taps, {games} little games, {shields} shields)")
    return secs


def _rocket_words(lines):
    return [(w.upper(), x, y) for w, x, y in _words(lines)]


def rocket_battle(stop=None):
    """From the first screen of Team GO Rocket at a stop to the map again (or to the Shadow Pokémon to catch:
    then 'catch' is returned and the normal bot catches it).  Returns 'map', 'catch' or 'failed'."""
    import battle_fight as BF
    import battle_vision as BV
    picked, fought, unknown = False, False, 0
    for step in range(ROCKET_STEPS):
        if stop and stop():
            return "failed"
        shot = S.screenshot()
        h, w = shot.shape[:2]
        if S.on_map(shot):
            log("rocket: back on the map")
            return "map"
        small = cv2.resize(shot, (704, int(round(h * 704.0 / w))), interpolation=cv2.INTER_AREA)
        if BF.state(BV.features(small)) in ("fight", "prompt"):
            rocket_fight(stop)
            fought = True
            continue
        lines = ocr_lines(shot, 100, 2150, 0.6)
        text = " ".join(t for t, _, _, _ in lines).upper()
        ws = _rocket_words(lines)
        name, score = screen_class(shot)
        if name == "encounterScreen" and score >= TH_CLASS and fought:
            log("rocket: the Shadow Pokémon to catch - the normal bot catches it")
            return "catch"
        save_async(f"g_rocket_s{step % 20}.png", shot)
        if "ROCKET RADAR" in text:
            yes = next(((x, y) for wd, x, y in ws if wd == "YES"), None)
            log("rocket: 'Use your Rocket Radar?' - YES")
            S.tap(*(_canvas(shot, *yes) if yes else _frac_xy((0.50, 0.42))))
        elif "USE THIS PARTY" in text or "RECOMMENDED" in text:
            use = next(((x, y) for wd, x, y in ws if wd == "USE"), None)
            cps = [(x, y) for wd, x, y in ws if re.fullmatch(r"(CP)?\d{3,4}", wd) and (not use or y < use[1])]
            filled = [i for i, sx in enumerate(ROCKET_PARTY_X) if any(abs(x / w - sx) < 0.08 for x, _y in cps)]
            empty = [i for i in range(3) if i not in filled]
            if cps and empty and len(filled) < 3 and not picked:
                y = max(y for _x, y in cps) + int(0.05 * h)
                log(f"rocket: the party has {len(filled)} Pokémon - choosing a third one for slot {empty[0] + 1}")
                S.tap(*_canvas(shot, ROCKET_PARTY_X[empty[0]] * w, y))
            elif use:
                log(f"rocket: USE THIS PARTY ({len(filled) or '?'} Pokémon)")
                S.tap(*_canvas(shot, *use))
            else:
                S.tap(*_frac_xy((0.50, 0.70)))
        elif "CANCEL" in text and "DONE" in text:
            done = next(((x, y) for wd, x, y in ws if wd == "DONE"), None)
            if not picked:
                log("rocket: the list of Pokémon - the first one")
                S.tap(*_frac_xy(ROCKET_LIST_FIRST))
                picked = True
            elif done:
                log("rocket: DONE")
                S.tap(*_canvas(shot, *done))
        elif "SUMMARY" in text:
            log("rocket: the summary - tapping on")
            S.tap(*_frac_xy((0.50, 0.85)))
        elif any(wd == "BATTLE" and y > 0.75 * h for wd, x, y in ws) and not fought:
            y = next(y for wd, x, y in ws if wd == "BATTLE" and y > 0.75 * h)
            log("rocket: BATTLE")
            S.tap(*_canvas(shot, ROCKET_BATTLE_X * w, y))
        else:                                            # speech bubbles, the rewards, the VS screen
            unknown += 1
            if unknown > 25:
                log("rocket: too many screens that are not known - stopping")
                return "failed"
            S.tap(*_frac_xy((0.50, 0.55)))
        time.sleep(1.5)
    return "failed"


def fight_battle(beat=None, stop=None, team=None, use_spots=None, stream=None):
    """Plays the battle that is about to start (or is going on) until its result screen.

    It looks at the screen all the time (the live video of the phone, see Eyes): VS screen and loading (wait), the
    fight (fast attacks in the background - on the button of the charged attack that is wanted next, so that
    it is thrown the moment it is ready -, a charged attack when the engine wants one and then its little game:
    swiping the icons), the questions "Use a Protect Shield?" and "Switch in a new Pokémon?" (answered by the
    engine), the result (NEXT BATTLE is tapped, or the round check mark when that is the only button).
    The banner of the other side's charged attack is read on the side.  The BACK button is never pressed during
    a fight; a fight that is lost is given up with the game's own button when the option is on (see
    _fight_give_up()).  use_spots: where USE THIS PARTY is, tapped again when the party screen is still there
    after a while.  stream: a battle_stream.FrameStream to use (default: start one).
    Returns {"result": "win" / "loss" / "", "why": "...", "seconds": n, "gave_up": bool}: why is '' after a
    result screen."""
    import battle_engine as BE
    import battle_fight as BF
    import battle_minigame as BMG
    import battle_vision as BV
    fight = BF.Fight(team or BE.load_team(), log=lambda m: log("battle: " + m), known=load_seen())
    flock = threading.RLock()  # (the fight is changed by the loop and by the looker that reads the names)
    S.busy(FIGHT_START_SECONDS + FIGHT_SECONDS)        # (no screen check, no screenshot test during the fight)
    eyes = Eyes(stream if stream is not None else _fight_stream())
    tapper = FastTapper(_frac_xy(BV.TAP_FAST))
    tapper.start()
    looker = FightLooker(fight, flock)
    looker.start()
    out = {"result": "", "why": "", "seconds": 0, "gave_up": False}
    t0 = time.monotonic()
    started = None            # when the HUD was first seen
    fight_seen = 0.0          # when a picture of the fight was last seen
    ask = {"seen": -100.0, "since": 0.0, "done": False, "xy": None, "tapped": 0.0, "tries": 0,   # the question on
           "kind": "", "n": 0}                                                                 # the screen
    thr = {"b": None, "xy": None, "t": 0.0, "tries": 0, "until": 0.0, "dark": 0}   # the charged attack that was tapped
    mini = None               # the little game of the charged attack that was thrown (Minigame)
    lit_prev = (False, False) # the buttons that were lit on the picture before
    lit_t = [None, None]      # since when each button has been seen ready (for the log: how fast was the throw?)
    last_lit = {"b": None, "t": 0.0}       # the button that was last seen ready
    arm = {"on": FIGHT_AIM, "b": None, "t": 0.0, "key": None, "acc": 0.0, "hp": 1.0, "proven": False}   # the fast
    # attacks on a button (see FIGHT_AIM): which one, when last, and whether the foe's HP goes down meanwhile
    ready_n = 0               # pictures in a row with the banner 'Get Ready!' and no little game going
    balls = {"me": 3, "foe": 3, "t": 0.0}  # the red Poké Balls of the name boxes: who can still fight
    give = {"on": battle_give_up(), "tried": False, "n": 0, "t": 0.0, "yes": 0.0}   # giving up a lost fight (once)
    used = {"since": 0.0, "until": 0.0, "t": 0.0}    # the banner 'X used Y!' of the foe's charged attack is read
    on_map = {"n": 0, "t": None}  # pictures in a row on which the map was seen, since when
    clock = {"t": None, "bars": False, "mini": -100.0}   # the clock of the plain fight (the foe's energy): the last
    # picture that counted, an HP bar was seen in this fight, when a little game of ours last ended
    bars = {"n": 0, "on": False}   # the fight is known by its HP bars only (see BARS_ONLY)
    learned = load_minigames()
    keys = {}                 # fingerprints of the two name boxes: side -> [the text now, a new one, times seen]
    versus_seen = 0.0         # when the VS screen was last seen
    tim = {"n": 0, "t": time.monotonic(), "feat": 0.0, "logged": 0}     # how long the pictures take
    unknown_ring = {}
    look = {"t": t0, "n": 0}  # last time an unknown screen was read
    party_taps = result_seen = errors = 0
    result_at = None          # since when the result screen has been on the pictures

    def end_minigame(why=""):
        nonlocal mini
        if mini is None:
            return
        tapper.sweep(None)
        clock["mini"] = time.monotonic()
        log(mini.report() + (f" ({why})" if why else ""))
        found = mini.game.learned()
        if found:                                    # (a type that is not known from recordings: remember it)
            learned[mini.game.kind] = found
            save_minigames(learned)
        mini = None

    def start_unseen(now):
        """The banner 'Get Ready!' is up and no charged attack was thrown from here: a tap of the fast attacks
        on its button threw it (or a swipe, or a tap the loop had given up on).  Which one: the button the fast
        attacks were on - then it is that one for sure.  Else the one that was last seen ready, else the one
        that is ready first (the cheaper attack): a guess, and the icons tell when it is wrong (see mini.alt)."""
        nonlocal mini
        sure = False
        with flock:
            both = [fight.move_of(0), fight.move_of(1)]
            if arm["b"] is not None and now - arm["t"] <= AIM_RECENT:
                b, sure = arm["b"], True             # (the taps were on this button and on no other)
            elif last_lit["b"] is not None and now - last_lit["t"] <= AIM_RECENT:
                b = last_lit["b"]
            else:
                b = 0 if both[1] is None or (both[0] is not None and both[0].energy <= both[1].energy) else 1
            move = both[b] or fight.me.charged[0]
            other = both[1 - b]
            fight.throws += 1
            me = fight.me
        t = now - BMG.GET_READY
        thr.update(b=None, xy=None, t=t, tries=0, dark=0, until=t + GAME_BLOCK)
        mini = Minigame(move, t, learned, b)
        mini.mon, mini.unseen = me, True
        mini.alt = None if sure or other is None or other.type == move.type else other
        mini.started(now)
        tapper.sweep(mini.strokes)
        log(f"battle: 'Get Ready!' - {move.name} was thrown by a tap on its button, its little game starts")

    try:
        while True:
            now = time.monotonic()
            if stop and stop():
                out["why"] = "stopped"
                break
            if started is None and now - t0 > FIGHT_START_SECONDS:
                out["why"] = "the fight did not start"
                break
            if started is not None and now - started > FIGHT_SECONDS:
                out["why"] = "the fight takes too long"
                break
            try:
                shot, small, t_seen = eyes.look()
            except Exception as e:  # noqa: BLE001
                errors += 1
                log(f"battle: screenshot failed ({e})")
                if errors > 8:
                    out["why"] = "the phone does not answer"
                    break
                time.sleep(1.0)
                continue
            if beat:
                beat()
            now = time.monotonic()
            # Back on the map: only when the map is on every picture for a while.  One picture of the loading
            # screens before a fight was once taken for the map, the loop ended and the bot did not fight at all.
            if S.on_map(shot):
                if on_map["t"] is None:
                    on_map["t"] = now
                    save_async("g_battle_map.png", shot)     # (to see afterwards what was taken for the map)
                on_map["n"] += 1
                if on_map["n"] >= MAP_PICTURES and now - on_map["t"] >= MAP_SECONDS:
                    out["why"] = "back on the map"
                    break
                continue
            on_map.update(n=0, t=None)
            # the video gives ~10 pictures a second: the names are then read when a name box changes (and every
            # five seconds to be sure) and a shield that was not used is believed after six seconds; with
            # screenshots (one every one to three seconds) these are counted in pictures as before
            fight.foe_every, fight.shields_back = (50, 60) if eyes.video else (BF.FOE_CHECK_EVERY, BF.SHIELDS_BACK)
            looker.video = eyes.video
            try:
                feat = BV.features(small)
                tim["n"] += 1
                tim["feat"] += time.monotonic() - now
                if tim["n"] >= 100 and tim["logged"] < 3:
                    log(f"battle: timing - {tim['n']} pictures in {time.monotonic() - tim['t']:.0f} s "
                        f"({eyes.live} from the live video, {eyes.shots} screenshots), reading one takes "
                        f"{tim['feat'] / tim['n'] * 1000:.0f} ms")
                    tim.update(n=0, t=time.monotonic(), feat=0.0, logged=tim["logged"] + 1)
                    eyes.live = eyes.shots = 0
                st = BF.state(feat)
                if started is None or bars["on"]:
                    # A net under the name boxes.  They are known by their Poké Balls; should those ever not be
                    # recognised (another arena, other colours on the video), no picture would count as the
                    # fight and the bot would stand still.  Two HP bars for two seconds are the fight as well.
                    both = (st == "other" and feat["hp"][0] is not None and feat["hp"][1] is not None
                            and not feat["versus"] and not feat["white"] and not feat["result"])
                    bars["n"] = bars["n"] + 1 if both else 0
                    if not bars["on"] and started is None and bars["n"] >= BARS_ONLY[0 if eyes.video else 1]:
                        bars["on"] = True
                        log("battle: both HP bars are on the screen but the name boxes are not recognised - "
                            "fighting on the HP bars (a recording of this fight would show why)")
                        save_async("g_battle_bars.png", shot)
                    if bars["on"] and st == "other" and (feat["hp"][0] is not None or feat["hp"][1] is not None):
                        feat = dict(feat, hud=True, ready=BV.charge_ready(small))
                        st = "fight"
                six = feat.get("balls")                      # the Poké Balls of the name boxes: who can still fight
                if six and sum(six["me"]) == 3 and sum(six["foe"]) == 3:       # (all six: none under a banner)
                    balls.update(me=six["me"][0], foe=six["foe"][0], t=now)
                if st != "fight":
                    tapper.aim(None)                         # (a button is only tapped in the plain fight)
                if st != "result":
                    result_at = None
                if now < used["until"]:                      # the foe's charged attack: its banner names it
                    if looker.used_at >= used["since"]:
                        used["until"] = 0.0                  # (read)
                    elif now - used["since"] >= USED_FROM and now - used["t"] >= USED_EVERY and st != "result":
                        used["t"] = now
                        looker.read_banner(shot)
                if mini is not None:                         # the little game of our charged attack
                    with flock:
                        other = mini.mon is not None and fight.me is not mini.mon
                    if st == "result":
                        end_minigame("the fight is over")
                    elif other:                              # (the one that threw it is not on the field any more)
                        end_minigame("another Pokémon is on the field")
                    elif st == "prompt":
                        if mini.on or mini.doubt or not eyes.video:
                            end_minigame("a question came up")
                        elif mini.held and now - mini.asked > 3.0:
                            end_minigame("the charged attack did not start")   # (a second question, and ours did
                        else:                                                  # not come in between)
                            mini.hold(now)                   # before its icons came: the other side's attack goes
                                                             # first, ours may follow - wait for 'Get Ready!'
                    elif mini.over(now):
                        end_minigame()
                    else:
                        k = 0 if eyes.video else 1
                        if feat.get("get_ready") and mini.started(now):      # the one sure sign that it starts
                            log(f"battle: 'Get Ready!' - the little game of {mini.move.name} starts"
                                + (" (it waited for the other side's attack)" if mini.held else ""))
                        n = mini.view(st == "fight", feat["hp"][0] is not None or feat["hp"][1] is not None,
                                      ZOOM_PICTURES[k], now)
                        icons = mini.look(small)
                        if mini.alt is not None and not mini.on and not icons:
                            # nobody saw which button was thrown and the attack was a guess: the icons tell.
                            # Those of the other attack have to be on two pictures in a row of the camera on
                            # the attacker, after the banner (by day the sky behind 'Get Ready!' gave four
                            # "flying" icons, and a Shadow Ball was swiped as a Sky Attack)
                            mini.alt_n = mini.alt_n + 1 if (mini.zoomed and not feat.get("get_ready")
                                                            and len(mini.others(small)) >= 3) else 0
                            if mini.alt_n >= (2 if eyes.video else 1):
                                log(f"battle: the icons are those of {mini.alt.name}, not of {mini.move.name}")
                                if not mini.unseen and not mini.race:    # (our own tap on a button that was
                                    with flock:                          # taken for the other attack)
                                        fight.buttons_swapped(mini.mon)
                                was, mini = mini, Minigame(mini.alt, mini.game.t0, learned, 1 - mini.button)
                                mini.mon, mini.unseen = was.mon, True
                                mini.started(now)
                                mini.view(True, False, 1)
                                tapper.sweep(mini.strokes)
                                icons = mini.look(small)
                        if eyes.video:                       # (a screenshot is too old to aim with)
                            mini.see(icons, t_seen)
                        if len(icons) >= 3 and not mini.saved:
                            mini.saved = True                # (one picture of it, to check what was seen)
                            pic = small.copy()
                            for x, y in icons:
                                cv2.circle(pic, (int(x * pic.shape[1]), int(y * pic.shape[0])),
                                           int(0.065 * pic.shape[1]), (0, 0, 255), 2)
                            save_async("g_battle_minigame.png", pic)
                        if mini.held and not mini.on and not mini.ready:
                            # waited for.  The fight is back and its button is ready again, or the plain fight
                            # with both HP bars has been back for a while: it does not come
                            again = st == "fight" and not icons and feat["ready"][mini.button]
                            mini.lit = mini.lit + 1 if again else 0
                            if st == "fight" and feat["hp"][0] is not None and feat["hp"][1] is not None:
                                mini.back += 1
                        if (icons and not mini.doubt) or mini.ready:     # (icons, so no buttons: what looks ready
                            feat = dict(feat, ready=(False, False))      # there is an icon)
                        if mini.on and n >= 2 and not icons:
                            end_minigame()                   # (the plain fight is back: nothing is swiped over it)
                        elif mini.on:                        # (the attack was thrown: no other one before it is over)
                            if mini.doubt and not mini.late:
                                mini.late = True             # (it was given up, and its icons are there after all)
                                log(f"battle: the little game of {mini.move.name} started after all")
                                with flock:
                                    fight.throws += 1
                                thr["t"] = now - mini.BMG.LEAD
                            thr["until"] = max(thr["until"], thr["t"] + GAME_BLOCK)
                        elif mini.held and not mini.ready and (mini.lit >= HELD_LIT or mini.back >= HELD_BACK[k]):
                            end_minigame("the charged attack did not start")
                        elif not mini.held and not mini.doubt and not mini.ready:
                            # no icons yet.  The camera goes to the attacker when a charged attack starts and no HP
                            # bar is shown until it is over: pictures of the plain fight say "not started"
                            if n >= PLAIN_PICTURES[k] and t_seen - thr["t"] >= THROW_LATEST:
                                mini.give_up()               # (a throw of something that was not ready, or a tap the
                                thr["b"] = None              # game did not take: the fast attacks go on, the next
                                thr["until"] = 0.0           # throw does not wait, the icons are still watched for)
                                with flock:
                                    fight.throws = max(fight.throws - 1, 0)
                                log(f"battle: {mini.move.name} did not start - the fight is still on the screen "
                                    f"{t_seen - thr['t']:.1f} s after the tap, going on")
                # The clock of the plain fight: both sides tap fast attacks, and the foe gains energy.  It runs
                # while the name boxes and an HP bar are on the picture and no little game of ours is on (a
                # charged attack of either side stops the game for both).  The name boxes without an HP bar
                # count too (a flash hides the bars for a moment) - but not within the seconds after a question
                # or after our little game: that is the banner of the attack.  What the clock is used for is
                # the MOST energy the foe can have, so in doubt time counts: the time between two pictures of
                # the plain fight counts in full (also when the video stood still for seconds), unless a
                # question or a little game lay in it - then the game stood still, and only its edges count.
                has_bar = feat["hp"][0] is not None or feat["hp"][1] is not None
                if st == "fight" and has_bar:
                    clock["bars"] = True
                if (st == "fight" and (mini is None or not (mini.on or mini.ready))
                        and (has_bar or (clock["bars"] and now - ask["seen"] > THEIR_ATTACK
                                         and now - clock["mini"] > OUR_ATTACK))):
                    if clock["t"] is not None:
                        gap = now - clock["t"]
                        if max(ask["seen"], clock["mini"]) >= clock["t"]:
                            gap = min(gap, ATTACK_EDGES)
                        with flock:
                            fight.fought(gap)
                    clock["t"] = now
                ready = feat["ready"]                        # what this picture says about the two buttons
                if eyes.video:                               # on the video a button is lit when two pictures in a
                    feat = dict(feat, ready=tuple(a and b for a, b in zip(ready, lit_prev)))   # row say so (one can
                lit_prev = ready if st == "fight" else (False, False)   # be a flash or a banner over the label)
                for b in (0, 1):
                    lit_t[b] = (lit_t[b] or t_seen) if st == "fight" and ready[b] else None
                    if lit_t[b]:
                        last_lit.update(b=b, t=now)
                if st != "fight":
                    with flock:
                        fight.lit = (False, False)           # (no HUD: what was lit is not known any more)
                if st == "fight" or (st == "other" and started is not None and now - fight_seen < 12):
                    with flock:
                        fight.see(feat)
                if st == "fight":
                    if started is None:
                        started = now
                        log("battle: the fight has started")
                    fight_seen = look["t"] = now
                    unknown_ring = {}
                    tapper.go()
                    for side in ("me", "foe"):               # another text in a name box: read the names now
                        key = BV.name_key(small, side)
                        k = keys.setdefault(side, [None, None, 0])
                        if not BV.key_differs(key, k[0]):
                            k[1], k[2] = None, 0
                        elif k[1] is not None and not BV.key_differs(key, k[1]):
                            k[2] += 1
                        else:
                            k[1], k[2] = key, 1
                        if k[2] >= (2 if eyes.video else 1):  # (the same new text twice: no flicker)
                            first = k[0] is None
                            k[0], k[1], k[2] = key, None, 0
                            if not first:
                                with flock:
                                    fight.read_names(side)
                    looker.ask(shot)                         # (names and labels are read next to this loop)
                    ready_n = ready_n + 1 if mini is None and feat.get("get_ready") else 0
                    if ready_n >= (2 if eyes.video else 1):  # our charged attack starts, and it was not thrown from
                        ready_n = 0                          # here: a tap of the fast attacks on its button did it
                        start_unseen(now)
                    if thr["b"] is not None:                 # a charged attack was tapped: did it count?
                        if mini is not None and mini.on:
                            thr["b"] = None                  # (the icons of the little game are there: it counted)
                        elif now - thr["t"] >= THROW_CHECK:
                            if not ready[thr["b"]]:
                                thr["dark"] += 1             # (the button is gone or dark: it counted - on the
                                if thr["dark"] >= (3 if eyes.video else 1):    # video only after three pictures
                                    thr["b"] = None          # in a row, one could be a flicker)
                            elif thr["tries"] < THROW_RETRIES:
                                thr["dark"] = 0
                                thr["tries"] += 1
                                log("battle: the button is still ready - the tap did not count, tapping again")
                                tapper.tap(*thr["xy"], 90)
                                thr["t"] = time.monotonic()
                                thr["until"] = thr["t"] + CHARGE_HOLD
                                if mini is not None:         # (when its swipes start is told by the pictures, not
                                    mini.game.t0 = thr["t"]  # by this time: a second tap does not make them late)
                            else:                            # tapped again and again, and it is still lit:
                                thr["b"] = None              # the game is slow, or it does not take the taps.  The
                                if mini is not None and not mini.doubt:      # icons are still watched for and the
                                    mini.give_up()           # next throw (the button is lit!) does not wait
                                    with flock:
                                        fight.throws = max(fight.throws - 1, 0)
                                    log(f"battle: {mini.move.name} did not start - the button is still ready after "
                                        f"{THROW_RETRIES + 1} taps, going on")
                    elif (mini is None or (mini.doubt and not mini.on and not mini.ready)) and now >= thr["until"]:
                        with flock:
                            throw = fight.throw()
                        if throw:
                            end_minigame()                   # (one that was given up: this throw takes its place)
                            button, move, why = throw
                            xy = _frac_xy((BV.BTN_X[button], BV.BTN_Y))
                            t_tap = time.monotonic()
                            tapper.tap(*xy, 90)
                            thr.update(b=button, xy=xy, t=time.monotonic(), tries=0, dark=0)
                            thr["until"] = thr["t"] + CHARGE_HOLD
                            # (for the log: how old the first picture of the ready button was when the tap went
                            # out, and how long the tap itself took - together the time the throw came late)
                            log(f"battle: throwing {move.name} on the {'left' if button == 0 else 'right'} button - "
                                f"{why} (seen ready {max(t_tap - (lit_t[button] or t_tap), 0.0):.1f} s before, "
                                f"the tap took {thr['t'] - t_tap:.1f} s)")
                            mini = Minigame(move, thr["t"], learned, button)   # its little game: swipe the icons
                            with flock:
                                mini.mon = fight.me
                                other = fight.move_of(1 - button)
                            if other is not None and other.type != move.type:
                                # The icons tell which attack it really was: the fast taps were on the other
                                # button a moment ago and one of them may have thrown that one - or the names
                                # under the buttons were read the wrong way round (22 November: 'Thunderbolt /
                                # Surf' for Lanturn, every Thunderbolt was swiped as a Surf)
                                mini.alt = other
                                mini.race = arm["b"] is not None and arm["b"] != button and now - arm["t"] <= AIM_RECENT
                            tapper.sweep(mini.strokes)
                    # Where the fast attacks are tapped: on the button of the charged attack that is to be thrown
                    # the moment it is ready - only while our HP bar is on the picture (the plain fight: when our
                    # Pokémon faints, the tiles of the switch question come up right where the buttons are)
                    spot = None
                    if (arm["on"] and mini is None and thr["b"] is None and now >= thr["until"]
                            and feat["hp"][0] is not None):
                        with flock:
                            aimed = fight.aim()
                            foe_hp = fight.foe_hp
                            who = (fight.me.pos, fight.foe.species if fight.foe else "")
                        if aimed is not None:
                            spot = aimed[0]
                            who += (spot,)
                            if who != arm["key"] or foe_hp > arm["hp"] + 0.05:     # (more HP: another foe came in)
                                arm.update(key=who, acc=0.0, hp=foe_hp)
                            elif not arm["proven"] and feat["hp"][1] is not None:
                                # do such taps count as fast attacks?  The foe's HP has to go down meanwhile
                                arm["acc"] += min(max(now - arm["t"], 0.0), 0.3)
                                if arm["acc"] < 1.5:
                                    arm["hp"] = foe_hp       # (an attack that was on its way does not count)
                                elif foe_hp < arm["hp"] - 0.01:
                                    arm["proven"] = True
                                elif arm["acc"] >= AIM_CHECK:
                                    arm["on"], spot = False, None
                                    globals()["FIGHT_AIM"] = False       # (not in the next fights of this run either)
                                    log(f"battle: the foe's HP did not go down in {AIM_CHECK:.0f} s of fast attacks "
                                        "tapped on a charged attack button - they do not seem to count there, the "
                                        "middle of the screen is tapped again (GAMEBOT_FIGHT_AIM=0 switches this off "
                                        "for good)")
                            arm.update(b=spot, t=now)
                    tapper.aim(_frac_xy((BV.BTN_X[spot], BV.BTN_Y)) if spot is not None else None)
                    # A fight that is lost is given up: our last Pokémon against two or more, and it loses the duel
                    # it is in (the same answer several times in a row - one reading of an HP bar is not enough)
                    if out["gave_up"] and now - give["yes"] > 8.0:
                        out["gave_up"] = False               # (YES was tapped and the fight is still going on)
                        log("battle: still fighting 8 s after YES - the battle was not left, it goes on")
                    if (give["on"] and not give["tried"] and mini is None and thr["b"] is None
                            and now - give["t"] >= GIVE_UP_EVERY):
                        give["t"] = now
                        lost, why = False, ""
                        if (balls["me"] == 1 and balls["foe"] >= 2 and now - balls["t"] < 5.0
                                and feat["hp"][0] is not None and feat["hp"][1] is not None):
                            with flock:
                                if not fight.foe_due:        # (the name in the foe's box is the one that was read)
                                    lost, why = fight.hopeless(balls["foe"])
                        give["n"] = give["n"] + 1 if lost else 0
                        if give["n"] >= GIVE_UP_LOOKS:
                            give["tried"] = True
                            out["gave_up"] = _fight_give_up(tapper, eyes, why, beat)
                            give["yes"] = time.monotonic()
                elif st == "prompt":
                    fight_seen = look["t"] = now
                    seen = _question_seen(feat)
                    if now - ask["seen"] > 3.0 or (ask["done"] and seen and seen != ask["kind"]):
                        # a new question: after a while without one - or another one than the one that was
                        # answered (the shield question can follow the switch question within a second or two)
                        ask.update(since=now, done=False, xy=None, tapped=0.0, tries=0, kind="", n=0)
                        unknown_ring = {}
                    ask["seen"] = now
                    ask["n"] += 1
                    thr["b"] = None
                    if not ask["done"]:
                        tapper.pause()
                        if seen == "switch":             # ours fainted: no swipes of a little game over the tiles
                            tapper.sweep(None)           # (they went on until the answer and spoilt its tap)
                        # (the answer to the switch question tells the bot that our Pokémon fainted: on the video
                        # that waits for a second picture of it, a tenth of a second - not longer, the countdown
                        # of this question can be nearly over when it comes up)
                        know = {"foes": balls["foe"] if balls["t"] and now - balls["t"] < BALLS_FRESH else None,
                                "ready": last_lit["b"] is not None and now - last_lit["t"] <= READY_RECENT}
                        res = (None if seen == "switch" and eyes.video and ask["n"] < 2 else
                               _fight_answer(shot, feat, fight, flock, tapper, unknown_ring, eyes, know))
                        if res is not None:
                            ask.update(done=True, xy=res["xy"], tapped=time.monotonic(), seen=time.monotonic(),
                                       kind=res["kind"])
                            log(f"battle: answered {ask['tapped'] - ask['since']:.1f} s after the question was seen")
                            if res["kind"] == "switch":      # (ours fainted: its charged attack does not come)
                                end_minigame("another Pokémon comes in")
                            else:                            # (their attack: its banner will say which one it is)
                                used.update(since=ask["tapped"], until=ask["tapped"] + USED_UNTIL, t=0.0)
                            last = balls["me"] == 1 and now - balls["t"] < 30.0   # (our last Pokémon, by its box)
                            if res["kind"] == "noshield" and give["on"] and not give["tried"] and last:
                                with flock:                  # an attack on our last Pokémon, and no shield: is that
                                    lost, why = fight.doomed()           # the end of the fight?  Then give it up
                                    on = "" if lost else fight.fights_on()
                                if lost:
                                    give["tried"] = True
                                    out["gave_up"] = _fight_give_up(tapper, eyes, why, beat)
                                    give["yes"] = ask["seen"] = time.monotonic()   # (the same question, still)
                                    if out["gave_up"]:
                                        end_minigame("the battle was given up")
                                else:                        # (said, so that a log tells why a lost end was played)
                                    log(f"battle: not giving up - {on}")
                            elif res["kind"] == "noshield":
                                with flock:
                                    alone = len(fight.alive()) == 1
                                if last or alone:            # (our last one by its box or by our own count)
                                    log("battle: not giving up - " + (
                                        "the option 'Give up a lost battle' is off" if not give["on"] else
                                        "it was tried before in this battle" if give["tried"] else
                                        f"the Poké Balls of our name box showed {balls['me']} of ours that can still "
                                        f"fight, {now - balls['t']:.0f} s ago"))
                            if res["xy"] is None and not out["gave_up"]:
                                tapper.go()                  # (nothing to tap: the attack plays out)
                    elif ask["xy"] is not None and now - ask["tapped"] >= RETAP_AFTER:
                        if ask["tries"] < (SWITCH_RETAPS if ask["kind"] == "switch" else RETAP_MAX):
                            ask["tries"] += 1                # (a tap that did not count: the question is still there)
                            tapper.sweep(None)
                            x, y = ask["xy"]
                            if ask["kind"] == "switch":
                                # 22 November: eleven presses on the tile in eleven seconds and none counted - so
                                # each time another kind of touch (and another height of the tile); the log says
                                # which one, to find the one the game takes
                                y = int(SWITCH_TAP_Y[ask["tries"] % len(SWITCH_TAP_Y)] * S.REF_H)
                                how, fn, args = SWITCH_TOUCHES[ask["tries"] % len(SWITCH_TOUCHES)]
                                log(f"battle: the question is still on the screen - tapping again ({how} at "
                                    f"{x}, {y})")
                                try:
                                    tapper.do(fn, x, y, *args)
                                except Exception as e:  # noqa: BLE001
                                    log(f"battle: that touch did not work here ({e})")
                            else:
                                log("battle: the question is still on the screen - tapping again")
                                tapper.tap(x, y, 120)
                            ask["tapped"] = time.monotonic()
                        else:
                            tapper.go()
                elif st == "result":
                    tapper.pause()
                    if result_at is None:
                        result_at = now
                    if started is not None and eyes.video and now - result_at < RESULT_SETTLE:
                        continue                             # (its button is still coming in: a tap now is lost)
                    words = _result_words(shot)              # the big white words: 'YOU WIN!' / 'GOOD EFFORT!'
                    res = BN.result_word(words)
                    if res:                                  # (read from the picture at hand: no screenshot, no
                        real, lines = shot, [(words.upper(), 0, 0, [(w, 0, 0) for w in words.upper().split()])]
                    else:                                    # reading of the whole screen)
                        real = eyes.real(shot)               # (other text is read from a real screenshot)
                        lines = ocr_lines(real, 100, None, 0.6)
                        res = BN.result_kind(lines)
                    if not res and started is not None and result_seen < 2 and _battle_kind(real, lines) != "party":
                        result_seen += 1                     # (the text of the result comes in: read it once more)
                        continue
                    if not res and (started is None or _battle_kind(real, lines) == "party"):
                        # a green button at the bottom that is no result: the party screen (USE THIS PARTY sits
                        # where NEXT BATTLE does) or a pop-up before the fight
                        if use_spots and party_taps < 3 and _battle_kind(real, lines) == "party":
                            x, y = use_spots[min(party_taps, len(use_spots) - 1)]
                            party_taps += 1
                            log(f"battle: still on the party screen - tapping USE THIS PARTY at ({x}, {y})")
                            tapper.tap(x, y)
                            time.sleep(2.0)
                        elif now - look["t"] >= FIGHT_WAIT_LOOK:
                            look["t"] = now
                            log(f"battle: waiting - a green button, no result ({BN.reads(lines, 90)})")
                        continue
                    out["result"] = res
                    out["gave_up"] = out["gave_up"] and res != "win"
                    spot, what = _result_spot(real)
                    log(f"battle: the fight is over: {res or 'result not read'}"
                        + (" - given up" if out["gave_up"] else "") + f" ({BN.reads(lines, 90)}) - tapping {what}")
                    save_async("g_battle_result.png", real)
                    tapper.tap(*spot)
                    time.sleep(2.5)
                    break
                else:                                        # VS screen, animation, banner, loading ...
                    if feat["versus"] and started is None:
                        versus_seen = now
                    if started is not None and now - fight_seen < 12:
                        if not out["gave_up"]:
                            tapper.go()                      # (an animation in the middle of the fight)
                        continue
                    if started is None and versus_seen and now - versus_seen < PRE_FIGHT_TAPS:
                        tapper.go()                          # (the fight starts any moment: the first tap must not
                    else:                                    # wait for a picture of the HUD; before it taps are ignored)
                        tapper.pause()
                    if now - look["t"] < FIGHT_WAIT_LOOK:
                        continue
                    look["t"] = now
                    look["n"] += 1
                    real = eyes.real(shot)
                    lines = ocr_lines(real, 100, None, 0.6)
                    kind = _battle_kind(real, lines)
                    if kind == "party":
                        versus_seen = 0.0                    # (no VS screen: this is still the party screen)
                    log(f"battle: waiting - screen is {kind} ({BN.reads(lines, 90)})")
                    if look["n"] == 2:
                        save_async("g_battle_wait.png", real)
                    res = BN.result_word(_result_words(real)) or BN.result_kind(lines)
                    if res and (BV.result_button(real) or BV.done_button(real)):
                        out["result"] = res
                        spot, what = _result_spot(real)
                        log(f"battle: the fight is over: {res} - tapping {what}")
                        tapper.tap(*spot)
                        time.sleep(2.5)
                        break
                    if kind == "party" and use_spots and party_taps < 3:
                        x, y = use_spots[min(party_taps, len(use_spots) - 1)]
                        party_taps += 1
                        log(f"battle: still on the party screen - tapping USE THIS PARTY at ({x}, {y})")
                        tapper.tap(x, y)
                    elif kind in ("home", "league", "menu", "map"):
                        out["why"] = f"back on the {kind} screen"
                        break
                    elif kind == "exit_battle":
                        spots = BN.exit_battle_spots(lines, real.shape[0] / 2208)
                        if give["tried"]:                    # (the question we asked for: the tap on YES did not count)
                            out["gave_up"] = True
                            log("battle: 'Exit the Trainer Battle?' is still on the screen - YES")
                            give["yes"] = time.monotonic()
                            tapper.tap(*spots["yes"])
                        elif spots["no"]:
                            tapper.tap(*spots["no"])
            except Exception as e:  # noqa: BLE001
                errors += 1
                log(f"battle: error in the fight loop: {type(e).__name__}: {e}")
                if errors > 8:
                    out["why"] = "too many errors"
                    break
    finally:
        tapper.sweep(None)
        tapper.close()
        looker.close()
        eyes.close()
        S.busy(0)
        if mini is not None:
            log(mini.report())
        if fight.learned:                      # (the attacks the opponents really used: for the battles to come)
            save_seen(fight.known)
        if out["gave_up"] and not out["result"] and out["why"].startswith("back on"):
            out["result"], out["why"] = "loss", ""     # (given up, and the game did not show a result screen)
        out["seconds"] = int(time.monotonic() - t0)
        log(f"battle: fight loop ended after {out['seconds']} s: " + (out["result"] or out["why"] or "no result")
            + (" (given up)" if out["gave_up"] else "")
            + f" ({tapper.taps} fast taps, {fight.throws} charged attacks with {tapper.swipes} swipes, "
            f"shields left {fight.my_shields})")
    return out


def _fight_on_screen():
    """True when the screen shows a running fight (name boxes or a question with its countdown)."""
    import battle_fight as BF
    import battle_vision as BV
    try:
        shot = S.screenshot()
        h, w = shot.shape[:2]
        small = cv2.resize(shot, (704, int(round(h * 704.0 / w))), interpolation=cv2.INTER_AREA)
        return BF.state(BV.features(small)) in ("fight", "prompt")
    except Exception:  # noqa: BLE001
        return False


def battle_run(beat, stop, count, team=None, no_more=None):
    """Fights `count` battles one after the other: map -> party screen -> USE THIS PARTY -> fight -> NEXT
    BATTLE (or the check mark when that is all there is: it leads to the Battle screen) -> party screen again
    ... and goes back to the map at the end.  Returns {"fought": n, "wins": n}."""
    res = {"fought": 0, "wins": 0}
    failures = 0
    league = battle_league()
    interrupted = False
    unfinished = False                               # the last fight ended without a result
    try:
        for n in range(1, count + 1):
            if stop and stop():
                break
            S.recheck_shot_mode()                    # (the quiet screens before a battle: a good moment to compare)
            if unfinished and _fight_on_screen():    # the last fight ended without a result and a fight is still
                log("battle: a fight is on the screen - fighting it")   # going on (the loop let go of it too
                unfinished = False                                        # early): fight it, the menus do not
                fought = fight_battle(beat, stop, team)                   # lead anywhere from here
                if fought["result"]:
                    res["fought"] += 1
                    res["wins"] += fought["result"] == "win"
                    failures = 0
                    log(f"battle: battle {n} done: {fought['result']} ({res['wins']} won of {res['fought']})"
                        + (f" {day_count('won' if fought['result'] == 'win' else 'lost')}"
                           if fought["result"] in ("win", "loss") else ""))
                    beat()
                    continue
                if stop and stop():
                    break
            if no_more and no_more():                # the time of the run is up: the last fight is done, no new one
                log(f"battle: the run time is up - no new battle after {res['fought']}")
                break
            info = battle_open_menu(beat, stop, restart=True, stay=True)
            if not info["ok"]:
                log(f"battle: the party screen was not reached: {info['why']}")
                res["leave"] = bool(info.get("leave"))
                res["catch"] = bool(info.get("catch"))
                if info.get("done_today"):
                    res["done_today"] = True
                    battles_done_today(True)
                return res
            words = BN.league_words(league)
            title = info["title"].upper()
            title_ok = all(w in title for w in words)
            # The title is read with OCR and a word can be missing ('2026 LEAGUE EDITION' for the Great League
            # edition: the bot went back and fought nothing, 22 November).  When the bot chose the league itself
            # on the list a moment ago, by its name, this is its party screen - unless the title names another.
            chosen = str(info.get("chosen") or "").upper()
            other = any(w in title for w in ("ULTRA", "MASTER", "LITTLE")) and not any(w in title for w in words[:1])
            by_choice = not title_ok and chosen and all(w in chosen for w in words) and not other
            title_ok = title_ok or by_choice
            log(f"battle: party screen '{info['title'] or '?'}' (team seen: {', '.join(info['members']) or 'not read'})"
                + (f" - the league '{info['chosen']}' was chosen on the list just now" if by_choice else "")
                + ("" if title_ok else f" - this is not '{league}', not fighting"))
            if not title_ok:
                break
            x, y = info["use_spots"][0]
            log(f"battle: battle {n} of {count} - tapping USE THIS PARTY at ({x}, {y})")
            S.tap(x, y)
            fought = fight_battle(beat, stop, team, info["use_spots"])
            if fought["result"]:
                res["fought"] += 1
                res["wins"] += fought["result"] == "win"
                failures = 0
                log(f"battle: battle {n} done: {fought['result']}" + (" (given up)" if fought.get("gave_up") else "")
                    + f" ({res['wins']} won of {res['fought']})"
                    + (f" {day_count('won' if fought['result'] == 'win' else 'lost')}"
                       if fought["result"] in ("win", "loss") else ""))
            else:
                failures += 1
                unfinished = True
                log(f"battle: battle {n} did not finish normally: {fought['why'] or 'no result'}")
                if failures >= 2 or fought["why"] == "stopped":
                    break
            beat()
    except KeyboardInterrupt:
        interrupted = True                           # (Ctrl+C: stop here, do not walk back through the menus -
        raise                                        # BACK in a running battle would give it up)
    finally:
        if not interrupted and not res.get("leave"):
            beat()
            if not S.on_map(S.screenshot()):
                if not _battle_to_map(beat, leaving_setup=True):
                    log("battle: could not get back to the map - restarting the game")
                    S.restart_game()
    return res


def auto_battle(pkg, beat, stop, no_more=None):
    """Fights the battles of this game when `pkg` is the app chosen for battles (see above).

    beat(): call it now and then - it books the time that has passed and tells the watchdog that the
    bot is alive (a long battle is not a stuck bot). stop(): True when the daily run is switched off,
    the max time is over or the run is done - then stop at once. Returns the number of battles fought."""
    if not battle_wanted() or pkg != battle_app():
        if setting("battle", False) and pkg == battle_app() and battles_done_today():
            log("battle: the battles of today are done (the BATTLE button was grey) - spinning and catching")
        return 0
    try:
        import battle_engine as BE
        team = BE.load_team()
        import battle_fight  # noqa: F401  (the fight needs these files: see install.sh)
        import battle_minigame  # noqa: F401
        import battle_vision  # noqa: F401
    except Exception as e:  # noqa: BLE001
        log(f"battle: the battle engine could not be loaded ({e}) - no battles")
        return 0
    log(f"battle: {battle_count()} battle(s) in '{battle_league()}' with " + ", ".join(m.label for m in team))
    beat()
    res = battle_run(beat, stop, battle_count(), team, no_more)
    log(f"battle: done - {res['fought']} fought, {res['wins']} won"
        + (" - the normal bot catches the Pokémon of the reward, then the battles go on" if res.get("catch") else
           " - the normal bot goes on from the screen that is there" if res.get("leave") else ""))
    run_state["battle_resume"] = bool(res.get("catch"))
    beat()
    return res["fought"]


def load_daily():
    import json
    try:
        with open(DAILY_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"start": 0, "done": []}


def save_daily(d):
    import json
    with open(DAILY_FILE, "w") as f:
        json.dump(d, f)


def reset_for_game():
    global SPIN, CATCH
    SPIN, CATCH = True, True
    storage_state["full"] = False
    bag_state["full"] = False
    menu_check["last"] = 0.0
    gift_timer["last"] = 0.0          # gifts round straight away
    rotation["steps"] = 0
    cooldown.clear()
    run_state["done"] = False


def daily_limit():
    """Max minutes a run may take, all games together ('Stop after ... min' next to the Start button). When they
    are over, a fight that is going on and a catch are finished, nothing new is started, the game is closed and
    the run ends."""
    try:
        return min(max(float(setting("daily_max_min", DAILY_MAX_MIN)), 1), 1440)
    except (TypeError, ValueError):
        return DAILY_MAX_MIN


WATCHDOG_EVERY = 30        # s between two looks of the watchdog
WATCHDOG_STALE = 180       # s: the loop of a game has not come round for this long (a step is stuck)
WATCHDOG_GRACE = 600       # s over the max time before a stuck bot is stopped by force
WATCHDOG_STUCK = 900       # s: no step has ended for this long, whatever the max time: the bot restarts


def start_watchdog(pkg, played, clock, d):
    """Safety net for a bot that hangs. The loop in run_one_game looks at the clock between two steps;
    when one step never ends (a hanging call), that look never comes and the game would run for ever.
    This thread then stops the bot when no step has ended for 15 minutes, or - when the game is also
    over its max time by ten minutes - after 3 minutes, and closes the game. systemd starts the bot
    again within 30 s; the run carries on with the time already played. Returns the Event that stops
    the thread."""
    stop = threading.Event()

    def run():
        while not stop.wait(WATCHDOG_EVERY):
            silent = time.monotonic() - clock["last"]
            total = played.get(pkg, 0) + silent
            over = sum(played.values()) + silent - daily_limit() * 60
            if silent > WATCHDOG_STUCK or (silent > WATCHDOG_STALE and over > WATCHDOG_GRACE):
                log(f"daily run: {pkg} - the bot has been stuck in one step for {silent / 60:.0f} min"
                    + (f" and the game is over its max time by {over / 60:.0f} min" if over > 0 else "")
                    + " - restarting the bot")
                played[pkg] = total
                try:
                    save_daily(d)
                    S.adb("shell", "am", "force-stop", pkg)
                except Exception:  # noqa: BLE001
                    pass
                os._exit(3)
    threading.Thread(target=run, daemon=True, name="daily-watchdog").start()
    return stop


def run_one_game(brain, pkg, d):
    S.PACKAGE = pkg
    reset_for_game()
    played = d.setdefault("played", {})            # seconds per game, kept when the bot restarts
    if sum(played.values()) > daily_limit() * 60:  # (the bot was restarted after the time was up: nothing left to play)
        log(f"daily run: the run time of {daily_limit():.0f} min is up - closing the game")
        close_game_completely()
        d["time_up"] = True
        return True
    log(f"daily run: starting {pkg} (the run stops after {daily_limit():.0f} min"
        + (f", {sum(played.values()) / 60:.0f} min played)" if sum(played.values()) else ")"))
    pkgs_now = game_packages()
    if battle_wanted() and pkg == pkgs_now[0] and battle_app() not in pkgs_now:      # said once per run
        log(f"battle: the chosen app {battle_app()} is not installed - no battles in this run")
    clock = {"last": time.monotonic()}             # all the time counts, also the start of the game and a long step
    watchdog = start_watchdog(pkg, played, clock, d)
    try:
        S.restart_game()

        def beat():                                # book the time so far; also tells the watchdog the bot lives
            mono = time.monotonic()
            played[pkg] = played.get(pkg, 0) + (mono - clock["last"])
            clock["last"] = mono

        def stop():                                # stop at once (also in the middle of a fight)
            return run_state["done"] or not wanted("daily_cycle")

        def time_up():                             # finish what is going on, start nothing new
            return sum(played.values()) + (time.monotonic() - clock["last"]) > daily_limit() * 60

        if not run_state["done"]:
            try:
                auto_battle(pkg, beat, stop, time_up)       # first the battles (when chosen), then spin and catch
            except Exception as e:  # noqa: BLE001
                log(f"battle: error {e}")
            beat()
        if not run_state["done"] and teams_due(pkg):
            try:
                teams_refresh(pkg, stop=lambda: stop() or time_up())
            except Exception as e:  # noqa: BLE001
                log(f"teams: error {e}")
            beat()
        saved = time.time()
        reported = played.get(pkg, 0)
        resumes = 0
        while not run_state["done"]:
            if not wanted("daily_cycle"):
                log("daily run switched off")
                save_daily(d)
                return False
            mono, now = time.monotonic(), time.time()
            played[pkg] = played.get(pkg, 0) + (mono - clock["last"])   # monotonic: a jump of the clock (NTP) does not count
            clock["last"] = mono
            d["slot"] = max(d.get("slot", 0), last_slot(now))     # a start time that passes during a run is used up by that run
            if now - saved > 60:
                save_daily(d)
                saved = now
            if played[pkg] - reported >= 1800:                    # now and then: how far is it
                reported = played[pkg]
                log(f"daily run: {sum(played.values()) / 60:.0f} of {daily_limit():.0f} min played")
            if time_up():
                finish_catch(brain, beat)
                log(f"daily run: the run time of {daily_limit():.0f} min is up - closing the game, the run ends")
                close_game_completely()
                d["time_up"] = True
                break
            try:
                wait = step(brain)
            except Exception as e:  # noqa: BLE001
                log(f"error: {e}")
                wait = 10
            # The reward of a set was a Pokémon to catch: the normal bot caught it (or it fled) - back on the map,
            # the battles go on (at most a few times a run)
            if run_state.get("battle_resume") and resumes < BATTLE_RESUMES:
                try:
                    back = S.on_map(S.screenshot())
                except Exception:  # noqa: BLE001
                    back = False
                if back:
                    resumes += 1
                    run_state["battle_resume"] = False
                    log("battle: the Pokémon of the reward was caught - back to the battles")
                    try:
                        auto_battle(pkg, beat, stop, time_up)
                    except Exception as e:  # noqa: BLE001
                        log(f"battle: error {e}")
                    beat()
                    continue
            time.sleep(wait)
    finally:
        watchdog.set()
    save_daily(d)
    log(f"daily run: {pkg} finished")
    return True


def finish_catch(brain, beat=None):
    """The time is up: a catch that is going on is finished first (at most FINISH_MAX_S), so no ball is left in
    the air and no Pokémon on the screen."""
    t_end = time.time() + FINISH_MAX_S
    told = False
    while time.time() < t_end:
        try:
            name, _ = brain.screen(S.screenshot())
        except Exception:  # noqa: BLE001
            return
        if name == "mapScreen":
            return
        if name != "encounterScreen" and not told:
            return                                 # (not catching: nothing to finish)
        if not told:
            log("daily run: the run time is up - finishing this catch first")
            told = True
        try:
            wait = step(brain)
        except Exception as e:  # noqa: BLE001
            log(f"error: {e}")
            wait = 5
        if beat:
            beat()
        time.sleep(min(wait, max(0.0, t_end - time.time())))


def daily_order():
    """The apps of the daily run in the order they are played: the one that fights battles first when battles
    are wanted (the battles come first in the run - 22 November: the other app was started first, while the
    one that fights was open already), then the rest in the usual order (Play Store first)."""
    pkgs = game_packages()
    if battle_wanted() and battle_app() in pkgs:
        pkgs = [battle_app()] + [p for p in pkgs if p != battle_app()]
    return pkgs


def daily_cycle(brain):
    d = load_daily()
    now = time.time()
    if force_start["pending"]:
        how, force_start["pending"] = force_start["pending"], False
        unfinished = [p for p in daily_order() if p not in d.get("done", [])]
        # Start button: always a fresh run. Otherwise (e.g. restart after an update) a run that is
        # still going just continues, and a finished one starts again.
        if how == "button" or not unfinished:
            d = {"start": now, "done": [], "slot": last_slot(now)}
            save_daily(d)
            log(f"{'Start pressed' if how == 'button' else 'bot started'} - daily run starts now: "
                f"{', '.join(daily_order())}")
            run_state["waiting_logged"] = None
    served = d.get("slot")                                 # the latest start time that a run has already used
    if served is None:                                     # file of an older version
        served = last_slot(d["start"]) if d.get("start") else 0
    if now >= last_slot(now) > served:                     # today's start time passed and no run has used it yet
        d = {"start": now, "done": [], "slot": last_slot(now)}
        save_daily(d)
        pkgs = daily_order()
        log(f"daily run started: {', '.join(pkgs)}")
        run_state["waiting_logged"] = None
    pkgs = [p for p in daily_order() if p not in d["done"]]
    if pkgs:                                       # (also continues a run after a restart)
        pkg = pkgs[0]
        if run_one_game(brain, pkg, d):
            d["done"].append(pkg)
            if d.get("time_up"):                   # the run time is up: the other games are not played this run
                d["done"] = list(dict.fromkeys(d["done"] + daily_order()))
                log("daily run: stopped - the run time is up")
            save_daily(d)
        return 5
    key = (setting("daily_time", "08:00"), d.get("start", 0))
    if run_state["waiting_logged"] != key:
        nxt = time.strftime("%Y-%m-%d %H:%M", time.localtime(last_slot(now) + 86400))
        log(f"daily run {'complete' if d.get('start') else 'waiting'} - next run at {nxt}")
        run_state["waiting_logged"] = key
    return 60


def last_slot(now):
    """Most recent moment (timestamp) of the daily start time set in the web interface."""
    try:
        hh, mm = (int(v) for v in str(setting("daily_time", "08:00")).split(":"))
    except ValueError:
        hh, mm = 8, 0
    t = time.localtime(now)
    slot = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, hh, mm, 0, 0, 0, -1))
    return slot if slot <= now else slot - 86400


def startup_screen(img):
    """Looks at one screenshot while Pokémon GO is starting (called by S.restart_game):
    dismisses a news card or the safety notice at once. Returns "map" when the map is there,
    "handled" after a tap, otherwise None."""
    if news_popup(img):
        log("news popup at start-up - tapping DISMISS")
        S.tap(*DISMISS_BTN)
        return "handled"
    if safety_notice(img):
        btn = find_pill_button(img) or S.find_green_button(img) or NOTICE_OK_BTN
        log("startup safety notice - tapping OK")
        S.tap(btn[0], btn[1])
        return "handled"
    return "map" if S.on_map(img) else None


S.startup_hook = startup_screen


LOCK_FILE = os.path.expanduser("~/.gamebot.lock")
LOCK_POLL = 5                  # s between two tries of a gamebot that waits for the lock
_one = {"f": None}             # the lock of the gamebot that may tap the phone (kept open while it runs)


def only_one(mode, wait=False):
    """Only one gamebot at a time may tap the phone.  The bot service and a 'gamebot.py fight' started by hand
    tap through each other: each presses Back and its own buttons on the screens of the other (a battle that
    ends on the Battle screen, a league that is tapped and does not open).  The first one takes a lock on
    ~/.gamebot.lock, which the system gives back when it ends, however it ends.
    wait: wait until the other one is done (the service) instead of giving up.  Returns True when this
    process may go on."""
    import fcntl
    f = open(LOCK_FILE, "a+")
    told = False
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            f.seek(0)
            who = f.read().strip() or "another gamebot"
            if not wait:
                f.close()
                log(f"NOT STARTED: another gamebot is tapping the phone ({who}). Two at the same time spoil each "
                    "other's taps. Stop the bot first: sudo systemctl stop spin-stop (or Stop in the web interface); "
                    "see what is running with: pgrep -af gamebot.py")
                return False
            if not told:
                told = True
                log(f"waiting: another gamebot is tapping the phone ({who}) - this one starts when it is done")
            time.sleep(LOCK_POLL)
    f.seek(0)
    f.truncate()
    f.write(f"gamebot.py {mode}, process {os.getpid()}, started {time.strftime('%Y-%m-%d %H:%M:%S')}")
    f.flush()
    _one["f"] = f
    return True


CHAPTER_PLAY_S = 180          # s: 'Normal play for 3 minutes'
CHAPTER_CATCH_S = 180         # s: at most this long for 'Catch this Pokémon' (and the catch after a Rocket battle)


def _chapter_steps(brain, seconds, until_map=False, stop=None):
    """The normal bot, step after step, for `seconds` - or (until_map) until it is back on the map after at least
    one step.  Returns the number of steps."""
    t_end, n = time.time() + seconds, 0
    while time.time() < t_end and not (stop and stop()):
        if until_map and n:
            name, _ = brain.screen(S.screenshot())
            if name == "mapScreen":
                break
        try:
            wait = step(brain)
        except Exception as e:  # noqa: BLE001
            log(f"error: {e}")
            wait = 5
        n += 1
        time.sleep(min(wait, max(0.0, t_end - time.time())))
    return n


chapter_stop = {"now": False}     # Stop test: also the parts of 'All checks' that are still to come


def run_chapter(key):
    """gamebot.py chapter <key>: one part of the bot on its own (see chapters.py). It starts on the screen
    that is on the phone now, logs 'TEST <key>: started' and at the end 'TEST <key>: done - ...' (or
    'failed - ...'), and saves the screen at the start and at the end (debug/g_test_start.png, g_test_end.png).
    Returns True when the part did what it is for."""
    import chapters as CH
    ch = CH.chapter(key)
    if not ch:
        log(f"TEST {key}: no such test - there are: {', '.join(CH.KEYS)}")
        return False
    stopped = chapter_stop

    def on_term(*_):
        stopped["now"] = True
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, on_term)
    stop = lambda: stopped["now"]          # noqa: E731
    log(f"TEST {key}: started - {ch['title']} (start screen: {ch['start']})")
    ok, how = False, ""
    try:
        S.detect_screen()
        layout_init()
        load_cal()
        try:
            S.debug_save("g_test_start.png")
        except Exception as e:  # noqa: BLE001
            log(f"TEST {key}: no screenshot ({e})")
        brain = Brain() if key in ("screen", "play", "catch", "rocket", "look", "throw") else None
        if key.startswith("battle") or key == "rocket_fight":
            try:
                log(S.probe_input())
            except Exception as e:  # noqa: BLE001
                log(f"input speed test failed: {e}")
            log(ocr_probe())
        if key == "screen":
            img = S.screenshot()
            name, score = brain.screen(img)
            dbg = img.copy()
            found = brain.map_objects(img) if name == "mapScreen" else brain.encounter_objects(img)
            for n, sc, x, y, bw, bh in found:
                log(f"  {n} [{sc:.2f}] at ({x}, {y}) {bw}x{bh}")
                cv2.rectangle(dbg, (x - bw // 2, y - bh // 2), (x + bw // 2, y + bh // 2), (0, 0, 255), 5)
                cv2.putText(dbg, f"{n} {sc:.2f}", (x - bw // 2, y - bh // 2 - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 255), 3)
            S.debug_save("g_test.png", dbg)
            ok, how = True, f"screen {name} [{score:.2f}], {len(found)} things found (debug/g_test.png)"
        elif key == "video":
            ok = bool(stream_test())
            how = "the live video works" if ok else "the live video did not work (see the lines above)"
        elif key == "look":
            def timed(fn):
                t = time.time()
                img = fn()
                return img, time.time() - t
            vids = [timed(S.quick_screenshot) for _ in range(10)]
            live_ok = S.quick_screenshot.live
            shots = [timed(S.screenshot) for _ in range(3)]
            t = time.time()
            found_v = brain.map_objects(vids[-1][0]) if live_ok else []
            t_det = time.time() - t
            brain._seen = None
            found_s = brain.map_objects(shots[-1][0])
            if live_ok:
                save_async("g_look_video.png", vids[-1][0])
            save_async("g_look_shot.png", shots[-1][0])
            names = lambda objs: ", ".join(f"{o[0]} {o[1]:.2f}" for o in objs[:6]) or "nothing"   # noqa: E731
            avg = lambda xs: sum(x[1] for x in xs) / len(xs)                                  # noqa: E731
            log(f"TEST look: screenshots {avg(shots):.2f} s each, finds: {names(found_s)}")
            if live_ok:
                log(f"TEST look: live video {avg(vids):.2f} s a picture, finds: {names(found_v)} "
                    f"(detection {t_det:.2f} s; debug/g_look_video.png and g_look_shot.png)")
                ok, how = True, f"live video {avg(vids):.2f} s a picture, screenshot {avg(shots):.2f} s"
            else:
                ok, how = False, ("the live video does not run (option 'Look with the live video' off, or see the "
                                  f"lines above) - screenshot {avg(shots):.2f} s")
        elif key == "throw":
            name, _ = brain.screen(S.quick_screenshot())
            if name != "encounterScreen" or not ball_ready(S.screenshot()):
                how = f"no ball ready on an encounter screen ({name})"
            else:
                enc["throws"] += 1
                t_rel = throw_ball(brain)
                hit = throw_info.get("hit")
                ok, how = bool(t_rel), ("thrown - " + ("a clear hit" if hit else "not a clear hit" if hit is False
                                                       else "where it came down was not seen") + " (see the lines above)")
        elif key == "play":
            gift_timer["last"] = time.time()   # (the gifts have a test of their own: not the first minute of this one)
            n = _chapter_steps(brain, CHAPTER_PLAY_S, stop=stop)
            ok, how = True, f"{n} steps in {CHAPTER_PLAY_S // 60} minutes"
        elif key == "battle_menu":
            info = battle_open_menu(stop=stop)
            ok = bool(info["ok"])
            how = f"on the party screen '{info['title']}'" if ok else f"the party screen was not reached: {info['why']}"
        elif key in ("battle_one", "battle_set"):
            import battle_engine as BE
            team = BE.load_team()
            n = 1 if key == "battle_one" else battle_count()
            log(f"battle: {n} battle(s) in '{battle_league()}' with " + ", ".join(m.label for m in team))
            res = battle_run(lambda: None, stop, n, team)
            ok = res["fought"] >= 1
            how = (f"{res['fought']} fought, {res['wins']} won"
                   + (" - a Pokémon of the rewards is waiting to be caught" if res.get("catch") else "")
                   + (" - the battles are done for today" if res.get("done_today") else ""))
        elif key == "battle_fight":
            import battle_engine as BE
            team = BE.load_team()
            log(f"battle: 1 battle(s) in '{battle_league()}' with " + ", ".join(m.label for m in team))
            fought = fight_battle(None, stop, team)
            ok = bool(fought["result"])
            how = (f"result {fought['result']}" + (" (given up)" if fought.get("gave_up") else "")
                   + f" after {fought.get('seconds', 0)} s" if ok else f"no result: {fought['why'] or '?'}")
            if fought["result"] in ("win", "loss"):
                log(f"battle: battle 1 done: {fought['result']}" + (" (given up)" if fought.get("gave_up") else "")
                    + f" {day_count('won' if fought['result'] == 'win' else 'lost')}")
        elif key == "rocket":
            res = rocket_battle(stop)
            if res == "catch":
                n = _chapter_steps(brain, CHAPTER_CATCH_S, until_map=True, stop=stop)
                how = f"fought, then {n} steps to catch the Shadow Pokémon"
            else:
                how = "back on the map" if res == "map" else "the battle did not go through (see the lines above)"
            ok = res in ("map", "catch")
        elif key == "rocket_fight":
            secs = rocket_fight(stop)
            ok, how = True, f"the fight took {secs} s"
        elif key == "catch":
            brain_name, _ = brain.screen(S.screenshot())
            if brain_name != "encounterScreen":
                how = f"no encounter on the screen ({brain_name})"
            else:
                n = _chapter_steps(brain, CHAPTER_CATCH_S, until_map=True, stop=stop)
                ok, how = True, f"{n} steps until the map"
        elif key == "bag":
            n = clean_bag()
            ok, how = n is not None, f"{n or 0} kinds of items discarded"
        elif key == "quests":
            res = claim_quests()
            ok, how = res != "failed", res
        elif key == "checks":
            done = []
            for k in ("screen", "video", "look"):
                if stopped["now"]:
                    break
                done.append((k, run_chapter(k)))
            ok = len(done) == 3 and all(r for _k, r in done)
            how = ", ".join(f"{CH.chapter(k)['title']} {'done' if r else 'FAILED'}" for k, r in done)
        elif key == "leagues":
            got = read_leagues(current_game())
            ok, how = bool(got), ("; ".join(f"{lg['title']} (max CP {lg['cap']}, PvPoke {lg['cup']})" for lg in got)
                                  or "the leagues were not read")
        elif key == "tags":
            leagues = read_leagues()
            made = make_league_tags(leagues) if leagues else []
            ok, how = bool(leagues) and len(made) == len(leagues), (f"tags: {', '.join(made)}" if made else "no tags made")
        elif key in ("scan_test", "scan", "scan_new"):
            n = scan_collection(limit=5 if key == "scan_test" else None, search="age0-7" if key == "scan_new" else "",
                                stop=stop)
            ok, how = n > 0, f"{n} Pokémon scanned ({current_game()})"
        elif key == "scan_flags":
            ns = [scan_collection(flag=f, stop=stop) for f in ("shadow", "lucky", "purified")]
            ok, how = True, f"shadow {ns[0]}, lucky {ns[1]}, purified {ns[2]}"
        elif key == "check_team":
            n = check_team(stop=stop)
            ok, how = n > 0, f"moves and candy read of {n} Pokémon; the teams were made again"
        elif key == "refresh":
            ok = teams_refresh(stop=stop)
            how = "the weekly round is done" if ok else "the leagues were not read"
        elif key == "teams":
            game = current_game()
            c = COL.load_collection(game=game)
            if not c.get("leagues"):
                read_leagues(game)
                c = COL.load_collection(game=game)
            t = COL.make_teams(c, game=game)
            write_battle_team(t["teams"], game)
            for title, tm in t["teams"].items():
                log(f"TEST teams: {title}: " + ", ".join(
                    f"{e.get('role', '')} {e['mon']['name']} CP {e['mon']['cp']} -> {e['eval']['form_name']} CP {e['eval']['cp']}"
                    for e in tm["team"])
                    + (" | reserves: " + ", ".join(e["mon"]["name"] for e in tm["reserves"]) if tm["reserves"] else ""))
            ok = any(tm["team"] for tm in t["teams"].values())
            how = (f"teams for {len(t['teams'])} leagues from {len(c.get('mons') or [])} Pokémon" if ok
                   else "no teams: scan your Pokémon first (and read the leagues)")
        elif key == "tag_teams":
            n = tag_team_members()
            ok, how = n > 0, f"{n} Pokémon tagged"
        elif key == "storage":
            res = storage_look()
            ok = res["ok"]
            how = ((f"searched; {res['used']} of {res['max']} places used" if res["used"] is not None else "searched")
                   + " - see debug/g_storage_result.png" if ok else res["why"])
        elif key == "gifts":
            gifts_round()
            ok, how = True, "round over (see the gift lines above)"
    except KeyboardInterrupt:
        how = "stopped"
    except Exception as e:  # noqa: BLE001
        import traceback
        log(f"TEST {key}: error {e!r}\n" + traceback.format_exc())
        how = f"error {e}"
    try:
        S.debug_save("g_test_end.png")
    except Exception:  # noqa: BLE001
        pass
    log(f"TEST {key}: {'done' if ok else 'failed'} - {how}")
    return ok


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "loop"
    if mode in ("battle", "fight", "step", "stap") and not only_one(mode):
        sys.exit(1)
    if mode == "chapter":                  # one part of the bot on its own (the web interface: Test)
        if not only_one(mode):
            sys.exit(1)
        ok = run_chapter(sys.argv[2] if len(sys.argv) > 2 else "")
        os._exit(0 if ok else 1)           # (at once: no thread or adb command of the part is waited for)
    if mode == "loop":
        only_one(mode, wait=True)          # (the service: wait until a test that was started by hand is over)
    if mode == "battle":                   # try the way to the party screen now (stop the bot first; the game on the map)
        S.detect_screen()
        info = battle_open_menu()
        log("battle: " + ("reached the party screen '%s'" % info["title"] if info["ok"] else "failed: " + info["why"]))
        return
    if mode == "streamtest":               # does the live video of the phone work?  (8 seconds, no taps)
        S.detect_screen()
        sys.exit(0 if stream_test() else 1)
    if mode == "fight":                    # fight the battles now (stop the bot first; the game on the map)
        S.detect_screen()
        try:
            log(S.probe_input())           # (the faster 'cmd input' when the phone has it: lighter for the phone)
        except Exception as e:  # noqa: BLE001
            log(f"input speed test failed: {e}")
        log(ocr_probe())
        try:
            res = battle_run(lambda: None, lambda: False, battle_count())
        except KeyboardInterrupt:
            log("stopped with Ctrl+C - the game is left as it is")
            os._exit(0)                    # (at once: no thread or adb command is waited for)
        log(f"battle: {res['fought']} fought, {res['wins']} won"
            + (" - the game is left on the screen that came up: look at the phone" if res.get("leave") else ""))
        return
    if mode == "loop":                     # the first screenshot also picks raw or PNG capture (a few
        def first_shot():                  # seconds): do that while the models are loading
            try:
                S.screenshot()
            except Exception as e:  # noqa: BLE001
                log(f"first screenshot failed: {e}")
        early = threading.Thread(target=first_shot, daemon=True)
        early.start()
    log("gamebot v3 loading models...")
    brain = Brain()
    if mode == "loop":
        early.join(timeout=60)             # (the game must not be restarted while that picture is being compared)

    if mode == "test":
        S.unlock()
        img = S.unlock_game(S.screenshot())
        name, score = brain.screen(img)
        log(f"screen: {name} [{score:.2f}]")
        dbg = img.copy()
        for o in brain.map_objects(img) if name == "mapScreen" else brain.encounter_objects(img):
            n, sc, x, y, bw, bh = o
            log(f"  {n} [{sc:.2f}] at ({x}, {y}) {bw}x{bh}")
            cv2.rectangle(dbg, (x - bw // 2, y - bh // 2), (x + bw // 2, y + bh // 2), (0, 0, 255), 5)
            cv2.putText(dbg, f"{n} {sc:.2f}", (x - bw // 2, y - bh // 2 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 255), 3)
        S.debug_save("g_test.png", dbg)
        return

    if mode in ("step", "stap"):
        log(f"wait {step(brain)} s")
        return

    S.detect_screen()                      # which phone and which display; sets up the conversion to the canvas
    layout_init()
    load_cal()
    force_start["pending"] = "button" if take_force_flag() else "start"
    try:
        log(S.probe_input())
    except Exception as e:  # noqa: BLE001
        log(f"input speed test failed: {e}")
    log(ocr_probe())
    log("gamebot v3 started")
    while True:
        if not S.screen["ok"]:                # a screen shape the bot cannot play on: do not tap
            if layout_adapt("the screen has another shape than the canvas"):
                continue
            S.wait_unsupported()
            continue
        if wanted("daily_cycle"):
            time.sleep(daily_cycle(brain))
            continue
        S.PACKAGE = MAIN_PACKAGE
        try:
            wait = step(brain)
        except Exception as e:  # noqa: BLE001
            log(f"error: {e}")
            wait = 10
        time.sleep(wait)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("stopped")
