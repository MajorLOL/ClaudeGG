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
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

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


class Brain:
    def __init__(self):
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

        def look(box, alone=False):
            x0, y0, x1, y1 = box
            it = self.map if alone else self.map_pool.get()    # alone: the copy that uses all cores
            try:
                found = self._ssd(it, self.map_anchors, MAP_LABELS, img[y0:y1, x0:x1])
            finally:
                if not alone:
                    self.map_pool.put(it)
            return [((o[0], o[1], o[2] + x0, o[3] + y0) + tuple(o[4:]), box)
                    for o in found if o[0] == "pokemon" and o[1] >= TH_WEAK]

        if self._seen is not None and self._seen[0] is img:     # same screenshot: reuse the quick look
            res, zoom = list(self._seen[1]), self._seen[2]
        else:
            res = self._ssd(self.map, self.map_anchors, MAP_LABELS, img)
            zoom = look(ZOOM_BOX, alone=True)
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
stats = {"day": None, "caught": 0, "fled": 0, "stops": 0}


def count(key):
    today = time.strftime("%Y-%m-%d")
    if stats["day"] != today:
        stats.update(day=today, caught=0, fled=0, stops=0)
    stats[key] += 1
    return f"(today: {stats['caught']} caught, {stats['fled']} fled, {stats['stops']} stops)"


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
    img = S.screenshot()
    if not S.on_map(img):
        lines = ocr_lines(img, 100, 2150)
        kind = _screen_kind(img, lines)
        if kind == "exit":                              # the game was already on the map: BACK asks 'exit?'
            log("fast catch: the game asks whether to exit - answering CANCEL")
            _cancel_exit(lines)
            img = None
        else:
            log(f"fast catch: after BACK the screen is '{kind}', not the map - waiting for the result the normal way")
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
        img2 = S.screenshot()
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
                log(f"BAG FULL - clean up your bag; skipping stops for {S.BAG_FULL_WAIT // 60} min")
                S.back()
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


def ocr_text(img, y0, y1):
    """All text in a horizontal strip of the screen (upper case)."""
    gray = cv2.cvtColor(img[y0:y1], cv2.COLOR_BGR2GRAY)
    ok, buf = cv2.imencode(".png", gray)
    try:
        out = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "6"],
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
        S.debug_save("g_menu.png", img)
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


BAG_WORDS = ("POTION", "REVIVE", "BALL", "BERR", "LUCKY", "INCENSE", "RAZZ", "PINAP", "NANAB", "EGG", "LURE", "ADVENTURE")


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
    """A screenshot of a screen that has stopped moving (after a tap: transitions and animations)."""
    time.sleep(first_wait)
    prev = S.screenshot()
    for _ in range(3):
        time.sleep(1.0)
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
        S.debug_save(f"g_incense_s{step}.png", shot)
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
                S.debug_save("g_incense_menu.png", shot)
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
    S.debug_save("g_incense_bag.png", img)
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
        S.debug_save(f"g_incense_p{i}.jpg", img)
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
        S.debug_save("g_incense_bag_end.png", img)
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
    S.debug_save("g_incense_card.png", img)
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
        S.debug_save(f"g_incense_t{shot_n}.jpg", marked)
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
        S.debug_save(f"g_incense_a{shot_n}.png", img)
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
        out = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "11", "tsv"],
                             input=buf.tobytes(), capture_output=True, timeout=30).stdout.decode()
    except FileNotFoundError:
        log("tesseract missing (sudo apt install tesseract-ocr) - no berries")
        return {}
    cells = {}
    for r in csv.DictReader(io.StringIO(out), delimiter="\t"):
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
    scale < 1: read a smaller picture (faster; for big letters), positions are still full size."""
    crop = img[y0:y1]
    if scale != 1.0:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    ok, buf = cv2.imencode(".png", gray)
    try:
        out = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "11", "tsv"],
                             input=buf.tobytes(), capture_output=True, timeout=40).stdout.decode()
    except FileNotFoundError:
        return []
    words = []
    for r in csv.DictReader(io.StringIO(out), delimiter="\t"):
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
            S.debug_save("g_gift_opened.png", img)
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
        S.debug_save("g_friend_profile.png", img)
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
                        S.debug_save("g_gift_select.png", img)
                    if not btn:
                        S.debug_save("g_send_nobutton.png", img)
                        log(f"gifts: SEND button not found for {name}")
                        S.back()
                        time.sleep(2)
                    else:
                        S.tap(btn[0], btn[1])      # SEND
                        time.sleep(6)
                        img = S.screenshot()
                        if has_sticker_button(img):
                            S.debug_save("g_send_stuck.png", img)
                            log(f"gifts: tapped SEND for {name} but the send screen is still open")
                            S.back()
                            time.sleep(2)
                        else:
                            st["sent"].append(name)
                            log(f"gift sent to {name} ✔")
                else:
                    S.debug_save("g_send_failed.png", img)
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
    S.debug_save("g_gifts_start.png", img)
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
       "obs": []}             # last throws: (ring measured, s until release, ring at release)


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


def refit_timing():
    """Learn from the last throws: the ring at release must equal
    measured - k * (seconds between the screenshot and the release - c). c (moment the
    screenshot is really taken) is fitted from the first throw on, the shrink speed k as
    soon as there are enough throws."""
    obs = cal["obs"][-16:]
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
    cal["k"], cal["c"] = best[1], best[2]


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
    land_x = None
    if ring:
        _, _, cx, cy, bw, bh = ring
        want_y = cy - 0.4 * bh                    # the ball comes down onto the Pokémon from above
        seen = [b for b in (find_ball(im, before) for im in imgs) if b]
        near = [b for b in seen if abs(b[1] - want_y) < 380]
        if near:
            land_x = min(near, key=lambda b: abs(b[1] - want_y))[0]
    return imgs[0], land_x


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
    time.sleep(TOUCH_SHOT)
    try:
        for attempt in range(2):                  # 2nd look: no ring seen / not readable (yet)
            t_s = time.time()
            img = S.screenshot()
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

    def ring_at(t):                               # ring size at clock time t
        return (measured - cal["k"] * (t - t_shot - cal["c"])) % 1.0

    expect = None
    wait = 0.0
    if measured is not None:
        diff = (ring_at(time.time() + cal["rel"]) - target) % 1.0
        if diff > 0.93:                           # already just below the target: throw now
            diff -= 1.0
        wait = max(diff, 0.0) / cal["k"]
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
    log(f"  hold time: screenshot {t_grab:.1f} s + ring search {t_find:.1f} s + spin still going {t_spin:.1f} s + "
        f"ring wait {wait:.1f} s + release {t_rel - t_b:.1f} s")

    first, land_x = watch_flight(before, ring)     # where does the ball go, and how big was the ring?
    if first is not None and expect is not None:
        m = measure_ring(first, ring)
        if m:
            got = m["ratio"]
            kind = "Excellent" if got < 0.3 else "Great" if got < 0.7 else "Nice"
            log(f"ring at release {got:.2f} ({kind} size, wanted {target:.2f}, expected {expect:.2f})")
            cal["obs"] = (cal["obs"] + [[round(float(measured), 3), round(t_rel - t_shot, 3),
                                         round(float(got), 3)]])[-16:]
            refit_timing()
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
        img = S.screenshot()
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
        time.sleep(POLL_PAUSE)


def aim(brain):
    """Hold the ball (the target ring appears then), take a screenshot and look for the ring."""
    bx, by = S.to_real(*BALL_XY)
    hold = subprocess.Popen(["adb", "shell", *S.INPUT, "swipe", str(bx), str(by), str(bx), str(by), "1300"])
    time.sleep(0.4)
    img = S.screenshot()
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
        img = S.screenshot()                    # look once more before deciding it is over
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


def step(brain):
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
        img = S.unlock_game(S.screenshot(fire_rotation) if rotation["armed"] else S.screenshot())
    shot_cost = time.time() - t_shot

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
        S.debug_save("g_stuck.png", img)
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
    if name == "rocketScreen" or (name in ("menusScreen", "rewardScreen", "onbekend") and is_rocket_text(img)):
        if last_tap["kind"] == "stop":
            x, y = last_tap["xy"]
            cooldown.append((x, y, time.time() + ROCKET_COOLDOWN))
        log(f"Team Rocket - not battling, leaving (stop skipped for {ROCKET_COOLDOWN // 60} min)")
        S.debug_save("g_rocket.png", img)
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
        S.debug_save("g_opslag_vol.png", img)
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
DAILY_MAX_MIN = 480           # default for "max time per game" (minutes), set in the web interface
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
    """Max minutes one game may run in the daily run (web interface)."""
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
            over = total - daily_limit() * 60
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
    if played.get(pkg, 0) > daily_limit() * 60:    # (the bot was restarted after the max time: nothing left to play)
        log(f"daily run: {pkg} already played {played[pkg] / 60:.0f} min (max {daily_limit():.0f} min) - closing the game")
        close_game_completely()
        log(f"daily run: {pkg} finished")
        return True
    log(f"daily run: starting {pkg} (max {daily_limit():.0f} min"
        + (f", {played[pkg] / 60:.0f} min already played)" if played.get(pkg) else ")"))
    clock = {"last": time.monotonic()}             # all the time counts, also the start of the game and a long step
    watchdog = start_watchdog(pkg, played, clock, d)
    try:
        S.restart_game()
        saved = time.time()
        reported = played.get(pkg, 0)
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
                log(f"daily run: {pkg} {played[pkg] / 60:.0f} of {daily_limit():.0f} min played")
            if played[pkg] > daily_limit() * 60:
                log(f"daily run: {pkg} reached the max time of {daily_limit():.0f} min - closing the game")
                close_game_completely()
                break
            try:
                wait = step(brain)
            except Exception as e:  # noqa: BLE001
                log(f"error: {e}")
                wait = 10
            time.sleep(wait)
    finally:
        watchdog.set()
    save_daily(d)
    log(f"daily run: {pkg} finished")
    return True


def daily_cycle(brain):
    d = load_daily()
    now = time.time()
    if force_start["pending"]:
        how, force_start["pending"] = force_start["pending"], False
        unfinished = [p for p in game_packages() if p not in d.get("done", [])]
        # Start button: always a fresh run. Otherwise (e.g. restart after an update) a run that is
        # still going just continues, and a finished one starts again.
        if how == "button" or not unfinished:
            d = {"start": now, "done": [], "slot": last_slot(now)}
            save_daily(d)
            log(f"{'Start pressed' if how == 'button' else 'bot started'} - daily run starts now: "
                f"{', '.join(game_packages())}")
            run_state["waiting_logged"] = None
    served = d.get("slot")                                 # the latest start time that a run has already used
    if served is None:                                     # file of an older version
        served = last_slot(d["start"]) if d.get("start") else 0
    if now >= last_slot(now) > served:                     # today's start time passed and no run has used it yet
        d = {"start": now, "done": [], "slot": last_slot(now)}
        save_daily(d)
        pkgs = game_packages()
        log(f"daily run started: {', '.join(pkgs)}")
        run_state["waiting_logged"] = None
    pkgs = [p for p in game_packages() if p not in d["done"]]
    if pkgs:                                       # (also continues a run after a restart)
        pkg = pkgs[0]
        if run_one_game(brain, pkg, d):
            d["done"].append(pkg)
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


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "loop"
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
