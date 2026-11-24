#!/usr/bin/env python3
"""
Automatically spins the PokéStop next to the player every 5 minutes (Pokémon GO).
Galaxy Z Fold3, inner screen 1768 x 2208, via ADB from the Raspberry Pi.

Usage:
  python3 spin_stop.py test    -> screenshot + analysis, saves check.png
  python3 spin_stop.py once    -> 1 round
  python3 spin_stop.py catch   -> only 1 catch attempt (for testing; "vang" works too)
  python3 spin_stop.py         -> keeps running (this is how the systemd service starts it)

Log: ~/spin.log
"""
import datetime
import json
import os
import re
import struct
import select
import subprocess
import sys
import threading
import time

import cv2
import numpy as np

# ============================== INSTELLINGEN ==============================
STOP = (1143, 1187)            # start position of the PokéStop on the map
MIN_AREA = 4000                # minimum size (px) of the stop rings (also on a zoomed-out map)
SPIN_Y = 1066                  # middle of the round photo in the stop screen
SPIN_X1, SPIN_X2 = 450, 1320   # swipe across the photo (fast, like a 'fling')
RING_CENTER, RING_R = (883, 1066), (395, 445)  # ring around the photo in the stop screen
CLOSE = (883, 2043)            # X button at the bottom of the stop screen
CENTER = (884, 1104)           # middle of the screen (tap through eggs, notifications)
NEUTRAL = (300, 750)           # empty spot on the map to wake a dimmed game
INTERVAL = 5 * 60 + 15         # 5 min cooldown + 15 s marge
RETRY = 30                     # wait time (s) after a recovery attempt
BAG_FULL_WAIT = 30 * 60        # bag full: wait this long before trying again
EXPECTED_SIZE = (1768, 2208)   # the canvas all coordinates below are written for (Galaxy Z Fold3, inner screen)
DARK_LIMIT = 120             # brightest pixels (99.5%) below this value = dimmed screen (normally ~255, dimmed ~50)
LOGFILE = os.path.expanduser("~/spin.log")

# ------------------------------ catching -----------------------------------
CATCH = True                   # catch wild Pokémon around the player
BERRY = "pinap"                # "razz", "nanab", "pinap" or None (no berry)
BALL = "poke"                  # "poke", "great" or "ultra"
MAX_THROWS = 8                 # then run away
THROW_END_Y = 700              # end point of the throw swipe (lower number = throw further)
THROW_MS = 200                 # duration of the throw swipe (shorter = throw harder)
PLAYER = (884, 1480)           # position of the player on the map
ENC_BALL = (877, 2017)         # ball at the bottom of the catch screen
ENC_BERRY_BTN = (212, 1840)    # berry button bottom left
ENC_BALL_BTN = (1539, 1840)    # ball button bottom right
RUN_BTN = (159, 248)           # run away, top left
BERRY_POS = {"razz": (325, 1274), "nanab": (884, 1274), "pinap": (1432, 1274)}
BALL_POS = {"poke": (325, 1592), "great": (877, 1592), "ultra": (1432, 1592)}
NO_POKEMON_COOLDOWN = 5 * 60   # spot where there was no Pokémon: skip it this long
DEBUG_DIR = os.path.expanduser("~/debug")   # screenshots of the last round
PACKAGE = "com.nianticlabs.pokemongo"
MAX_FAILS = 3                  # after this many failed recovery attempts Pokémon GO is restarted
# ==========================================================================

stop_pos = list(STOP)
fails = 0
cooldown = []   # [(x, y, expires_at)] spots without catchable Pokémon


def log(msg):
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line, flush=True)
    try:
        with open(LOGFILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ------------------------------- ADB --------------------------------------
def adb(*args, binary=False):
    r = subprocess.run(["adb", *args], capture_output=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="ignore").strip() or "adb-fout")
    return r.stdout if binary else r.stdout.decode(errors="ignore")


INPUT = ["input"]              # becomes ["cmd", "input"] when that is faster (see probe_input)

# ------------------------------ the screen ---------------------------------
# All coordinates in this code are written for one canvas, REF_W x REF_H (the inner screen of a
# Galaxy Z Fold3). Every screenshot is brought to that canvas and every tap and swipe is converted
# back to the real screen, so other resolutions work. On the Fold3 itself this changes nothing.
# A screen with a very different shape (a tall phone) is not supported yet: the game puts its
# buttons in other places there. The bot then does not tap at all; see device_check.py.
REF_W, REF_H = EXPECTED_SIZE
ASPECT_TOLERANCE = 0.10        # width/height may differ this much (relative) from the canvas
SCREEN_FILE = os.path.expanduser("~/gamebot_display.json")        # what detect_screen() found
ALLOW_FILE = os.path.expanduser("~/gamebot_allow_unsupported")    # create this file: run on an unsupported screen anyway

screen = {"id": None, "w": REF_W, "h": REF_H, "model": "", "ok": True, "note": "", "checked": 0.0}


def to_real(x, y):
    """Canvas coordinates -> pixels of the real screen."""
    return int(round(x * screen["w"] / REF_W)), int(round(y * screen["h"] / REF_H))


def _judge_screen():
    """Is the shape of the screen close enough to the canvas for the layout of the game to match?"""
    w, h = screen["w"], screen["h"]
    ref = REF_W / REF_H
    rel = abs(w / h - ref) / ref
    if rel <= ASPECT_TOLERANCE:
        screen.update(ok=True, note="")
        return
    note = (f"screen {w}x{h} (width/height {w / h:.2f}) has a different shape than the {REF_W}x{REF_H} "
            f"(width/height {ref:.2f}) this bot is written for")
    if os.path.exists(ALLOW_FILE):
        screen.update(ok=True, note=note + f" - running anyway because {ALLOW_FILE} exists")
    else:
        screen.update(ok=False, note=note + " - the bot tries to let Android draw the game in the right shape (wm size); "
                      "until that has worked it does not tap (run device_check.py --layout, see the wiki page 'Phone setup')")


def _normalize(img):
    """Real screenshot -> canvas picture (and keep track of the real size)."""
    h, w = img.shape[:2]
    if (w, h) != (screen["w"], screen["h"]):
        screen["w"], screen["h"] = w, h
        log(f"screen size is {w}x{h}")
        _judge_screen()
    if (w, h) != EXPECTED_SIZE:
        img = cv2.resize(img, EXPECTED_SIZE, interpolation=cv2.INTER_AREA if w * h >= REF_W * REF_H else cv2.INTER_LINEAR)
    return img


def _load_saved():
    try:
        with open(SCREEN_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def load_screen():
    """Take over what the bot found earlier (used by the web interface). True when there was something."""
    d = _load_saved()
    if not d.get("w") or not d.get("h"):
        return False
    screen.update(id=d.get("id"), w=int(d["w"]), h=int(d["h"]), model=d.get("model", ""), checked=time.time())
    _judge_screen()
    return True


def _screencap_info(display_id):
    """(width, height, mean brightness) of one display, or None when it cannot be captured."""
    args = ["exec-out", "screencap"] + (["-d", str(display_id)] if display_id else []) + ["-p"]
    try:
        raw = adb(*args, binary=True)
        i = raw.find(b"\x89PNG")
        img = cv2.imdecode(np.frombuffer(raw[i:], np.uint8), cv2.IMREAD_COLOR) if i >= 0 else None
    except Exception:  # noqa: BLE001
        return None
    if img is None:
        return None
    return img.shape[1], img.shape[0], float(img[::8, ::8].mean())


def detect_screen(wake=True):
    """Find out which phone this is and which of its displays shows the game, and set up the
    conversion to the canvas. A foldable has two displays: the one that is lit is used (the other
    is black), and when both are lit the one used before, or else the biggest. Returns True when a
    display was found. Writes what it found to SCREEN_FILE (the web interface reads it)."""
    screen["checked"] = time.time()
    model = ""
    try:
        model = f"{adb('shell', 'getprop', 'ro.product.manufacturer').strip()} {adb('shell', 'getprop', 'ro.product.model').strip()}".strip()
    except Exception:  # noqa: BLE001
        pass
    ids = []
    try:
        ids = list(dict.fromkeys(re.findall(r"Display (\d+)", adb("shell", "dumpsys", "SurfaceFlinger", "--display-id"))))
    except Exception:  # noqa: BLE001
        pass
    saved = _load_saved().get("id")
    found = []
    for attempt in range(2 if wake else 1):
        found = [(c, *info) for c in ids if (info := _screencap_info(c))]
        if not found:
            info = _screencap_info(None)                 # phones where -d does not work: the default display
            found = [(None, *info)] if info else []
        if not found or any(f[3] > 3.0 for f in found):
            break
        if attempt == 0:                                 # every display is black: the screen is off?
            try:
                adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")
            except Exception:  # noqa: BLE001
                pass
            time.sleep(2)
    if not found:
        log("screen check: no display can be captured (is the phone connected, and is USB debugging on?)")
        return False
    lit = [f for f in found if f[3] > 3.0] or found
    pick = next((f for f in lit if saved and str(f[0]) == str(saved)), None) or max(lit, key=lambda f: f[1] * f[2])
    old_id = screen["id"]
    screen.update(id=pick[0], w=pick[1], h=pick[2], model=model)
    _judge_screen()
    if str(old_id) != str(pick[0]):
        _shot["mode"] = None                             # the screenshot method is chosen again for this display
    log(f"screen check: {model or 'unknown phone'}; displays " + ", ".join(f"{f[0] or 'default'} {f[1]}x{f[2]}{'' if f[3] > 3.0 else ' (off)'}" for f in found)
        + f"; using {pick[0] or 'the default display'} {pick[1]}x{pick[2]}")
    if screen["note"]:
        log("screen check: " + screen["note"])
    try:
        with open(SCREEN_FILE, "w") as f:
            json.dump({"id": pick[0], "w": pick[1], "h": pick[2], "model": model, "time": time.time()}, f)
    except OSError:
        pass
    return True



# ------------------- layout: does the game look like the canvas? -------------------
# The conversion above only scales. That is right when the game puts its buttons on this phone in the
# same proportions as on the Fold3. The bot checks that with something it can recognise: the Poké Ball
# menu button at the bottom of the map. When it is not where it should be, or the screen has another
# shape, the bot lets Android draw the game on a canvas of the right shape (wm size: the phone then
# shows black bars) and puts that back when it stops.
MENU_REF = (884, 1991, 170)     # menu button on the canvas: x of its middle, y of the line between its red and
                                # white half, width of the red half
MENU_TOL = (45, 60, 28)         # how far off that may be (px on the canvas)
WM_FILE = os.path.expanduser("~/gamebot_wm_override.json")          # what this bot changed (so it can put it back)
NO_ADAPT_FILE = os.path.expanduser("~/gamebot_no_display_change")   # create this file: never change the display size
MIN_CANVAS = (600, 750)         # never make the game smaller than this


def find_menu_button(img):
    """The Poké Ball menu button (red top half, white bottom half) at the bottom of the map.
    Returns (x of its middle, y of the line between the halves, width of the red half) or None."""
    H, W = img.shape[:2]
    y0, x0, x1 = int(0.78 * H), int(0.25 * W), int(0.75 * W)
    reg = img[y0:, x0:x1].astype(np.int32)
    b, g, r = reg[..., 0], reg[..., 1], reg[..., 2]
    red = ((r > 35) & (r > 2.5 * np.maximum(np.maximum(g, b), 1))).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(red, 8)
    best = None
    for i in range(1, n):
        x, y, w, h, a = (int(v) for v in st[i])
        if not (0.05 * W <= w <= 0.2 * W and 0.3 * w <= h <= 0.7 * w and a > 0.3 * w * h):
            continue
        cx, bot = x0 + x + w / 2, y0 + y + h
        wy = int(bot + 0.25 * w)
        if wy >= H:
            continue
        px = [int(v) for v in img[wy, int(cx)][::-1]]          # white half below the red one
        r_up = int(img[int(bot - 0.2 * w), int(cx)][2])         # (the game is dimmed behind a dialog: compare with the red half)
        if max(px) - min(px) < 25 and px[0] > 0.8 * r_up:
            cand = (cx, float(bot), float(w))
            if best is None or abs(cx - W / 2) < abs(best[0] - W / 2):
                best = cand
    return best


def menu_button_check(found):
    """(True / False / None, text): is the menu button where the canvas expects it? None: not found."""
    if found is None:
        return None, "Poké Ball menu button not found"
    dx, dy, dd = found[0] - MENU_REF[0], found[1] - MENU_REF[1], found[2] - MENU_REF[2]
    where = f"menu button at ({found[0]:.0f}, {found[1]:.0f}), {found[2]:.0f} px wide (expected ({MENU_REF[0]}, {MENU_REF[1]}), {MENU_REF[2]} px)"
    if abs(dx) <= MENU_TOL[0] and abs(dy) <= MENU_TOL[1] and abs(dd) <= MENU_TOL[2]:
        return True, where
    return False, where


def wm_info():
    """(physical size, override size) of the default display from 'wm size'; override None when there is none."""
    out = adb("shell", "wm", "size")
    phys = re.search(r"Physical size:\s*(\d+)x(\d+)", out)
    over = re.search(r"Override size:\s*(\d+)x(\d+)", out)
    return (tuple(int(v) for v in phys.groups()) if phys else None,
            tuple(int(v) for v in over.groups()) if over else None)


def load_wm_record():
    try:
        with open(WM_FILE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get("set") else None
    except (OSError, ValueError):
        return None


def forget_wm_record():
    try:
        os.remove(WM_FILE)
    except OSError:
        pass


def display_plan():
    """What does the display have to be for the game to be drawn like the canvas?
    Returns (argument for 'wm size', (w, h) of the screenshots then, "") or (None, None, why not)."""
    w, h = screen["w"], screen["h"]
    try:
        phys, over = wm_info()
    except Exception as e:  # noqa: BLE001
        return None, None, f"'wm size' does not work on this phone ({e})"
    if not phys:
        return None, None, "'wm size' does not give a physical size"
    if over:
        mine = load_wm_record()
        if mine and mine.get("set") == f"{over[0]}x{over[1]}":
            return None, None, f"the display size is already set by this bot ({over[0]}x{over[1]})"
        return None, None, (f"the display size was changed by something else ({over[0]}x{over[1]}, physical {phys[0]}x{phys[1]}) "
                            f"- not touching it (reset it with: adb shell wm size reset)")
    if (phys[0], phys[1]) == (w, h):
        swapped = False
    elif (phys[1], phys[0]) == (w, h):
        swapped = True                                   # the game is turned the other way than the phone's natural position
    else:
        return None, None, f"the screenshot is {w}x{h} but the display is {phys[0]}x{phys[1]}: cannot tell which display that is"
    scale = min(w / REF_W, h / REF_H)
    tw, th = (int(round(REF_W * scale)) // 2 * 2), (int(round(REF_H * scale)) // 2 * 2)
    if tw < MIN_CANVAS[0] or th < MIN_CANVAS[1]:
        return None, None, f"the screen is too small to draw the game in the right shape ({tw}x{th})"
    if abs(tw - w) <= 2 and abs(th - h) <= 2:
        return None, None, "the screen already has the shape of the canvas"
    a, b = (th, tw) if swapped else (tw, th)
    return f"{a}x{b}", (tw, th), ""


def adapt_display():
    """Let Android draw the game on a canvas of the right shape. Returns (changed, text)."""
    if os.path.exists(NO_ADAPT_FILE):
        return False, f"not changing the display size ({NO_ADAPT_FILE} exists)"
    cmd, size, why = display_plan()
    if not cmd:
        return False, why
    try:
        with open(WM_FILE, "w") as f:                    # first write down what is going to be changed
            json.dump({"set": cmd, "time": time.time(), "model": screen["model"], "was": f"{screen['w']}x{screen['h']}"}, f)
    except OSError as e:
        return False, f"cannot write {WM_FILE} ({e}) - not changing the display size without a way back"
    try:
        adb("shell", "wm", "size", cmd)
    except Exception as e:  # noqa: BLE001
        forget_wm_record()
        return False, f"wm size {cmd} was refused ({e})"
    log(f"display size set to {cmd} so the game is drawn in the right shape (the phone shows black bars; "
        f"this is put back when the bot stops, or run: adb shell wm size reset)")
    time.sleep(3)                                        # the game redraws itself
    _shot["mode"] = None                                 # (the screenshot method is chosen again)
    detect_screen(wake=False)
    if sorted((screen["w"], screen["h"])) != sorted(size):
        restore_display()
        return False, f"after wm size {cmd} the screenshots are {screen['w']}x{screen['h']}, not {size[0]}x{size[1]}"
    return True, f"display now {size[0]}x{size[1]}"


def restore_display():
    """Put the display size back when this bot changed it. True when something was put back."""
    if not load_wm_record():
        return False
    try:
        adb("shell", "wm", "size", "reset")
    except Exception as e:  # noqa: BLE001
        log(f"could not put the display size back ({e}) - run: adb shell wm size reset")
        return False
    forget_wm_record()
    _shot["mode"] = None
    log("display size put back (wm size reset)")
    try:
        detect_screen(wake=False)                        # (also updates what the web interface reads)
    except Exception:  # noqa: BLE001
        pass
    return True


_wait_log = {"t": 0.0}


def wait_unsupported():
    """The screen has a shape the bot cannot play on: do nothing, but keep looking (a foldable may be unfolded)."""
    if time.time() - _wait_log["t"] > 600:
        _wait_log["t"] = time.time()
        log("not playing: " + screen["note"])
    time.sleep(30)
    detect_screen()


def tap(x, y, ms=120):
    # Pokémon GO (Unity) sometimes misses very fast taps; hence a short 'press'
    x, y = to_real(x, y)
    adb("shell", *INPUT, "swipe", str(x), str(y), str(x), str(y), str(ms))


def tap_quick(x, y):
    """A plain 'input tap' (finger down and up at once): some screens of the game take this and not a press."""
    x, y = to_real(x, y)
    adb("shell", *INPUT, "tap", str(x), str(y))


def tap_motion(x, y, ms=80):
    """Finger down, a moment, finger up - as separate touch events (input motionevent, Android 11 and newer)."""
    x, y = to_real(x, y)
    adb("shell", f"{' '.join(INPUT)} motionevent DOWN {x} {y}; sleep {ms / 1000.0:.2f}; "
                 f"{' '.join(INPUT)} motionevent UP {x} {y}")


def swipe(x1, y1, x2, y2, ms=300):
    (x1, y1), (x2, y2) = to_real(x1, y1), to_real(x2, y2)
    adb("shell", *INPUT, "swipe", str(x1), str(y1), str(x2), str(y2), str(ms))


def swipes(strokes):
    """Several swipes one after the other in ONE adb command: [(x1, y1, x2, y2, ms), ...] on the canvas.
    The phone starts the next swipe the moment the one before is finished, without a round trip to the Pi
    in between (used for the little game of a charged attack, where every tenth of a second counts)."""
    parts = []
    for x1, y1, x2, y2, ms in strokes:
        (a, b), (c, d) = to_real(x1, y1), to_real(x2, y2)
        parts.append(f"{' '.join(INPUT)} swipe {a} {b} {c} {d} {max(int(ms), 1)}")
    if parts:
        adb("shell", "; ".join(parts))


_bg = []                       # swipes that are still running in the background


def swipe_async(x1, y1, x2, y2, ms=300):
    """Start a swipe and do not wait for it (the caller knows when it is over: it takes about
    0.3 s + ms). Used to turn the camera while the screenshot is still being transferred."""
    _bg[:] = [p for p in _bg if p.poll() is None]
    (x1, y1), (x2, y2) = to_real(x1, y1), to_real(x2, y2)
    _bg.append(subprocess.Popen(["adb", "shell", *INPUT, "swipe", str(x1), str(y1), str(x2), str(y2), str(ms)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))


def back():
    adb("shell", *INPUT, "keyevent", "KEYCODE_BACK")


def probe_input():
    """How long does one input command take on the phone? 'input' is a script that starts 'cmd input' (on
    older phones a whole Java process: 0.3 s each, 22 of them for one curveball spin). 'cmd input' is the same
    command without the detour. Only the usage text is asked for: nothing is sent to the game. Returns a
    one-line report and switches INPUT to 'cmd input' when the phone has it and it is clearly faster."""
    def per_call(cmd, n=4):
        line = "; ".join([f"{cmd} >/dev/null 2>&1"] * n)
        t0 = time.time()
        subprocess.run(["adb", "shell", line], capture_output=True, timeout=60)
        return time.time() - t0

    try:
        base = min(per_call("true") for _ in range(2))          # adb round trip alone
        t_in = max(min(per_call("input") for _ in range(2)) - base, 0) / 4
        t_cmd = max(min(per_call("cmd input") for _ in range(2)) - base, 0) / 4
        usage = subprocess.run(["adb", "shell", "cmd input 2>&1"],
                               capture_output=True, timeout=30).stdout.decode(errors="ignore")
    except Exception as e:  # noqa: BLE001
        return f"input speed not measured ({e})"
    works = input_usage_ok(usage)
    if works and t_cmd < INPUT_GAIN * t_in and t_in - t_cmd >= 0.010:
        INPUT[:] = ["cmd", "input"]
    return (f"input commands: 'input' {t_in * 1000:.0f} ms each, 'cmd input' "
            f"{t_cmd * 1000:.0f} ms each{'' if works else ' (not available)'} - using '{' '.join(INPUT)}'")


INPUT_GAIN = 0.8               # 'cmd input' is used when it takes less than this share of the time of 'input'


def input_usage_ok(usage):
    """Does the usage text of 'cmd input' show the commands the bot needs? (The text is long: the commands
    come after the list of sources, so all of it has to be looked at.)"""
    text = (usage or "").lower()
    return all(word in text for word in ("swipe", "motionevent", "keyevent"))


def keyguard_showing():
    out = adb("shell", "dumpsys", "window")
    return any(k in out for k in ("mKeyguardShowing=true", "isKeyguardShowing=true",
                                  "mShowingLockscreen=true", "KeyguardShowing=true"))


def unlock():
    """Remove the swipe lock screen (no PIN)."""
    if not keyguard_showing():
        return False
    log("lock screen active - unlocking")
    adb("shell", "wm", "dismiss-keyguard")
    time.sleep(1.5)
    if keyguard_showing():
        swipe(884, 1900, 884, 500, 300)   # swipe up, like by hand
        time.sleep(1.5)
    if keyguard_showing():
        log("unlock failed - is there a PIN/pattern?")
        return False
    return True


def _dargs():
    """Which display to capture: ['-d', id], or nothing for the default display."""
    return ["-d", str(screen["id"])] if screen["id"] else []


def _grab_png():
    raw = adb("exec-out", "screencap", *_dargs(), "-p", binary=True)
    start = raw.find(b"\x89PNG")
    if start < 0:
        raise RuntimeError(f"no PNG received from screencap: {raw[:200]!r}")
    img = cv2.imdecode(np.frombuffer(raw[start:], np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("screenshot could not be read")
    return img


RAW_FIRST_BYTES_TIMEOUT = 30      # s the phone may take to start sending a raw screenshot


def _grab_raw(on_grab=None):
    """Raw RGBA from screencap: the phone does not have to compress a PNG first (that is
    what takes most of the 3 s), the 15 MB just go over the USB cable. on_grab() is called
    as soon as the first bytes arrive: the phone sends nothing before the picture has been
    taken, so from then on the screen may change (the rest is still on its way)."""
    if on_grab is None:
        raw = adb("exec-out", "screencap", *_dargs(), binary=True)
    else:
        p = subprocess.Popen(["adb", "exec-out", "screencap", *_dargs()],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            # (a plain read1() has no time-out: when adb stalls the bot would wait for ever)
            if not select.select([p.stdout], [], [], RAW_FIRST_BYTES_TIMEOUT)[0]:
                raise TimeoutError(f"screencap sent nothing within {RAW_FIRST_BYTES_TIMEOUT:.0f} s")
            first = p.stdout.read1(65536)
            if first:
                on_grab()
            rest, err = p.communicate(timeout=30)
        except BaseException:
            p.kill()
            raise
        if p.returncode != 0:
            raise RuntimeError(err.decode(errors="ignore").strip() or "adb-fout")
        raw = first + rest
    if len(raw) < 64:
        raise RuntimeError(f"raw capture too short: {raw[:64]!r}")
    w, h, fmt = struct.unpack("<III", raw[:12])
    if fmt not in (1, 2) or not (200 <= w <= 6000 and 200 <= h <= 6000):
        raise RuntimeError(f"unexpected raw format {w}x{h} (pixel format {fmt})")
    head = len(raw) - w * h * 4                    # 12 bytes, or 16 on newer Android
    if head not in (12, 16):
        raise RuntimeError(f"raw capture has {len(raw)} bytes, expected {w * h * 4} + header")
    rgba = np.frombuffer(raw, np.uint8, count=w * h * 4, offset=head).reshape(h, w, 4)
    img = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)
    if _shot["xf"] is not None:                    # the raw colours differ a little from the PNG ones: correct them
        img = cv2.transform(img, _shot["xf"])
    return img


def _fit_colours(raw, png, keep=None):
    """3x4 matrix that turns the colours of the raw screenshot into those of the PNG one (the
    raw data can be in another colour space; the ring measurement is sensitive to that).
    Fitted on two small copies of the same scene; the pixels that differ most (things that
    moved between the two screenshots) are left out. keep: the pixels to start from (a mask over
    the small copy), e.g. the ones that did not move."""
    sm = lambda im: cv2.resize(im, (221, 276), interpolation=cv2.INTER_AREA).reshape(-1, 3).astype(np.float64)
    a, b = sm(raw), sm(png)
    X = np.hstack([a, np.ones((len(a), 1))])
    keep = np.ones(len(a), bool) if keep is None else np.asarray(keep, bool).reshape(-1).copy()
    for _ in range(3):
        coef = np.linalg.lstsq(X[keep], b[keep], rcond=None)[0]            # 4 x 3
        err = np.abs(X @ coef - b).sum(axis=1)
        keep = keep & (err <= np.percentile(err[keep], 85))
    return coef.T.astype(np.float32)                                         # 3 x 4


_shot = {"mode": None, "fails": 0, "tries": 0, "retry": 0.0, "xf": None,
         "raw_ok": False, "t_raw": 0.0, "png_avg": 0.0, "png_n": 0, "saved": False,
         "auto": False, "raw_n": 0}
_shot_lock = threading.Lock()
_busy = {"until": 0.0}         # until then: no screen check and no new choice of the screenshot method
SHOT_SAME = 2.5                # raw and PNG show the same picture when they differ less than this (0-255) ...
SHOT_STILL = 6                 # ... on the parts of the screen that moved less than this between two PNGs
SHOT_STILL_SHARE = 0.25        # ... which must be at least this share of the screen
SHOT_FASTER = 0.85             # raw is used when it takes less than this share of the time of a PNG
SHOT_TRIES = 6                 # how often the comparison is made at most
SHOT_PROBE = 30                # raw used because PNGs were slow: one PNG per so many screenshots, to see how they are now


def busy(seconds):
    """Something that cannot wait is going on for the next `seconds` (a battle): screenshot() then does not
    stop to find the display again after a black picture (black is normal between two scenes of a battle; the
    check takes seconds) and does not try the raw screenshot again. busy(0) ends it.
    A battle is also where PNG screenshots take two or three times as long as elsewhere: the raw screenshot is
    used from the start when it was found right, and PNGs again afterwards when they are quicker."""
    _busy["until"] = time.time() + seconds if seconds > 0 else 0.0
    if seconds > 0:
        if _shot["mode"] == "png" and _shot["raw_ok"]:
            _shot.update(mode="raw", auto=True, raw_n=0)
            log("screenshots: raw capture for now (PNGs are slow on a screen that moves this much)")
    elif _shot["auto"]:
        _shot["raw_n"] = SHOT_PROBE                # (it is over: the next screenshot shows whether PNGs are quick again)


def compare_shots(png, raw, png2):
    """Is the raw screenshot the same picture as the PNG one? The game moves between two screenshots (the
    map is alive, a battle even more), so a plain difference says little: the raw one is compared with a PNG
    taken just before it, on the parts of the screen that did not change between that PNG and one taken just
    after. Returns {"same": True / False / None (too much moves to tell), "diff": ..., "still": share of the
    screen that stood still, "moved": difference between the two PNGs, "xf": colour correction or None,
    "note": text for the log}."""
    out = {"same": None, "diff": 0.0, "still": 0.0, "moved": 0.0, "xf": None, "note": ""}
    if raw.shape != png.shape or png2.shape != png.shape:
        out.update(same=False, note=f"another size: raw {raw.shape[1]}x{raw.shape[0]}, PNG {png.shape[1]}x{png.shape[0]}")
        return out
    small = lambda im: cv2.resize(im, (221, 276), interpolation=cv2.INTER_AREA).astype(np.int16)
    a, b, r = small(png), small(png2), small(raw)
    still = np.abs(a - b).max(axis=2) <= SHOT_STILL
    out["still"], out["moved"] = float(still.mean()), float(np.abs(a - b).mean())
    if out["still"] < SHOT_STILL_SHARE:
        out["note"] = f"only {out['still']:.0%} of the screen stood still"
        return out
    diff = float(np.abs(a - r)[still].mean())
    if SHOT_SAME < diff <= 14:                     # not the same colours: try to correct them
        xf = _fit_colours(raw, png, still)
        after = float(np.abs(a - small(cv2.transform(raw, xf)))[still].mean())
        if after < 0.6 * diff and after <= SHOT_SAME:
            out["xf"] = xf
            out["note"] = f"colours corrected (difference {diff:.1f} -> {after:.1f})"
            diff = after
    out["diff"] = diff
    out["same"] = diff <= SHOT_SAME
    return out


def _choose_shot_mode():
    """First screenshot: take it both ways (PNG, raw, PNG again) and keep the raw one when it is clearly
    faster and shows the same picture (not skewed, same colours - or colours that can be corrected)."""
    _shot["tries"] += 1
    _shot.update(xf=None, raw_ok=False)
    mode, why, png, again = "png", "", None, 300
    try:
        t0 = time.time()
        png = _grab_png()
        t_png = time.time() - t0
        t0 = time.time()
        raw = _grab_raw()
        t_raw = time.time() - t0
        t0 = time.time()
        png2 = _grab_png()
        t_png = (t_png + time.time() - t0) / 2.0
        res = compare_shots(png, raw, png2)
        times = f"raw {t_raw:.1f} s, PNG {t_png:.1f} s"
        detail = (f"difference {res['diff']:.1f} on the {res['still']:.0%} of the screen that stood still"
                  + (f", {res['note']}" if res["note"] else ""))
        if res["same"] is None:
            why, again = f"raw screenshot not judged yet ({res['note']}; {times}) - keeping PNG for now", 60
        elif not res["same"]:
            why = f"raw screenshot differs from PNG ({res['note'] or detail}; {times}) - keeping PNG"
            if not _shot["saved"]:                 # (once: the two pictures, to see what differs)
                _shot["saved"] = True
                try:
                    os.makedirs(DEBUG_DIR, exist_ok=True)
                    cv2.imwrite(os.path.join(DEBUG_DIR, "g_shot_png.png"), png)
                    cv2.imwrite(os.path.join(DEBUG_DIR, "g_shot_raw.png"), raw)
                    why += " (both saved: debug/g_shot_png.png and g_shot_raw.png)"
                except Exception:  # noqa: BLE001
                    pass
        else:
            _shot.update(raw_ok=True, t_raw=t_raw, xf=res["xf"])
            if t_raw > SHOT_FASTER * t_png:
                why = (f"raw screenshot is right but not faster here ({times}) - keeping PNG until PNGs "
                       f"take longer ({detail})")
            else:
                mode = "raw"
                why = f"screenshots: raw capture {t_raw:.1f} s instead of PNG {t_png:.1f} s ({detail})"
    except Exception as e:  # noqa: BLE001
        why = f"raw screenshot not possible ({e}) - keeping PNG"
    if mode != "raw" and not _shot["raw_ok"]:
        _shot["xf"] = None
    more = mode == "png" and not _shot["raw_ok"] and _shot["tries"] < SHOT_TRIES
    _shot.update(mode=mode, fails=0, retry=time.time() + again if more else 0.0, png_avg=0.0, png_n=0,
                 auto=False, raw_n=0)
    log(why)
    if png is None:                                    # (not even the PNG worked: let that error come through)
        png = _grab_png()
    return _normalize(png)


def recheck_shot_mode():
    """Ask for the comparison of raw and PNG screenshots to be made again at the next screenshot (when the
    raw one was not accepted yet): for a moment at which the screen is quiet."""
    if _shot["mode"] == "png" and not _shot["raw_ok"] and _shot["tries"] < SHOT_TRIES:
        _shot["retry"] = time.time() - 1


# ---------- the live video for looking (instead of a screenshot of 1 to 3 s) ----------
LIVE_WIDTH = 768               # px of the video the bot looks at (the height follows the shape of the screen)
LIVE_FPS = 12                  # pictures a second handed to Python
LIVE_BITRATE = "5000000"
LIVE_WAIT = 0.3                # s: no newer picture in this time after asking = the screen did not change
LIVE_REST = 300                # s: after the video failed, screenshots for this long before it is tried again
live = {"stream": None, "off_until": 0.0, "frames": 0, "shots": 0, "note": ""}
live_wanted = lambda: True     # noqa: E731  (gamebot sets it to the option 'Look with the live video')


def live_stream():
    """The live video of the phone for looking, started the first time it is asked for; None when it is
    switched off, failed a moment ago, or the phone is not known yet."""
    if not live_wanted() or time.time() < live["off_until"] or not screen.get("checked"):
        return None
    st = live["stream"]
    if st is not None and (st.failed or not st.is_alive()):
        why = st.describe()
        live_stop()
        live["off_until"] = time.time() + LIVE_REST
        log(f"live video for looking stopped ({why}) - screenshots for {LIVE_REST // 60} min")
        return None
    if st is None:
        try:
            import battle_stream as BS
            size = BS.video_size(screen["w"], screen["h"], base=LIVE_WIDTH)
            st = BS.FrameStream(size, display_id=screen.get("id"), bitrate=LIVE_BITRATE, fps=LIVE_FPS, low_delay=True)
            st.start()
            live["stream"] = st
            log(f"live video for looking started ({size[0]}x{size[1]}, {LIVE_FPS} pictures a second)")
        except Exception as e:  # noqa: BLE001
            live["off_until"] = time.time() + LIVE_REST
            log(f"live video for looking not possible ({e}) - screenshots")
            return None
    return st


def live_stop():
    """Stop the live video (a fight starts a video of its own; two at once are too much for the phone)."""
    st, live["stream"] = live["stream"], None
    if st is not None:
        try:
            st.close()
        except Exception:  # noqa: BLE001
            pass


LIVE_STALE = 10.0              # s: a last picture older than this is not trusted (a screenshot is taken)


def _live_picture(st, wait=LIVE_WAIT):
    """(picture in the size of a screenshot, time it came in) from the live video, or None."""
    got = st.wait_new(st.seq, timeout=wait)            # a picture that comes after the question ...
    if got is None:
        if st.starting() or not st.frames:
            got = st.wait_new(st.seq, timeout=2.5)     # (screenrecord (re)started: the first picture is on its way)
        else:
            got = st.latest()                          # ... or none came: the screen stood still, the last is now
            if got is not None and time.monotonic() - got[1] > LIVE_STALE:
                got = None
    if got is None:
        return None
    _seq, t, frame = got
    return cv2.resize(frame, (screen["w"], screen["h"]), interpolation=cv2.INTER_LINEAR), t


def quick_screenshot(on_grab=None):
    """A picture of the screen from the live video (a tenth of a second) when it runs, else a screenshot.
    For looking at the map, the ring and the ball; text that has to be read sharply wants screenshot().
    quick_screenshot.live tells where the last one came from."""
    st = live_stream()
    if st is not None:
        try:
            got = _live_picture(st)
        except Exception as e:  # noqa: BLE001
            log(f"live video picture failed: {e}")
            got = None
        if got is not None:
            live["frames"] += 1
            quick_screenshot.live, quick_screenshot.t = True, got[1]
            if on_grab is not None:
                try:
                    on_grab()
                except Exception as e:  # noqa: BLE001
                    log(f"action after the screenshot failed: {e}")
            return got[0]
    live["shots"] += 1
    quick_screenshot.live, quick_screenshot.t = False, time.monotonic()
    return screenshot(on_grab)


quick_screenshot.live, quick_screenshot.t = False, 0.0


def live_frames(seconds, every=0.0):
    """Pictures of the live video for `seconds`: [(time it came in, picture in screenshot size)], or [] when
    the video does not run.  every: at least this many s between two."""
    st = live_stream()
    if st is None:
        return []
    out, seq, end, last = [], st.seq, time.monotonic() + seconds, 0.0
    while time.monotonic() < end:
        got = st.wait_new(seq, timeout=max(end - time.monotonic(), 0.01))
        if got is None:
            break
        seq, t, frame = got
        if t - last >= every:
            out.append((t, cv2.resize(frame, (screen["w"], screen["h"]), interpolation=cv2.INTER_LINEAR)))
            last = t
    return out


def foreground_package():
    """The package of the app that is on the screen now (dumpsys activity: the resumed activity), or ''."""
    try:
        out = adb("shell", "dumpsys", "activity", "activities")
    except Exception:  # noqa: BLE001
        return ""
    for key in ("topResumedActivity", "mResumedActivity", "ResumedActivity"):
        m = re.search(key + r"[=:].*?\s(\S+?)/", out)
        if m:
            return m.group(1)
    return ""


def screenshot(on_grab=None):
    """on_grab: something to do the moment the picture has been taken (raw mode: before the
    transfer is finished; PNG mode: when it is complete). The caller can start a swipe then and
    work on the picture while the screen already changes."""
    hook = None
    if on_grab is not None:
        done = []

        def hook():
            if not done:
                done.append(1)
                try:
                    on_grab()
                except Exception as e:  # noqa: BLE001
                    log(f"action after the screenshot failed: {e}")
    if not screen["checked"]:
        detect_screen()                            # first screenshot of this run: which phone, which display?
    img = _screenshot(hook)
    if float(img[::16, ::16].mean()) < 1.5 and time.time() - screen["checked"] > 60 and time.time() > _busy["until"]:
        old = screen["id"]                         # a black screen: a foldable that was folded or unfolded?
        detect_screen()
        if str(screen["id"]) != str(old):
            img = _screenshot(hook)
    if hook:
        hook()                                     # not called yet (PNG mode): the picture is complete now
    return img


def _screenshot(hook):
    def choose():                                   # the first screenshot, or time to try the raw one again
        return _shot["mode"] is None or (_shot["mode"] == "png" and _shot["retry"]
                                         and time.time() > max(_shot["retry"], _busy["until"]))
    if choose():
        with _shot_lock:
            if choose():                            # (another thread may have done it meanwhile)
                _shot["retry"] = 0.0
                return _choose_shot_mode()
    img = None
    # A PNG of a busy screen (a battle) takes two or three times as long as one of a quiet screen; the raw
    # screenshot always takes the same time. When the raw one was found right ("raw_ok") the faster of the two
    # is used: raw while PNGs are slow ("auto"), and PNG again when they are quick again - a PNG now and then
    # ("probe") shows that.
    probe = (_shot["mode"] == "raw" and _shot["auto"] and _shot["raw_n"] >= SHOT_PROBE
             and time.time() > _busy["until"])
    if _shot["mode"] == "raw" and not probe:
        try:
            t0 = time.time()
            img = _grab_raw(hook)
            _shot["fails"] = 0
            if _shot["auto"]:
                _shot["raw_n"] += 1
                if hook is None:                   # (with a hook the time of what it does would be counted too)
                    _shot["t_raw"] += (time.time() - t0 - _shot["t_raw"]) / 4.0
        except Exception as e:  # noqa: BLE001
            _shot["fails"] += 1
            log(f"raw screenshot failed ({e}) - taking a PNG" + (" from now on" if _shot["fails"] >= 3 else ""))
            if _shot["fails"] >= 3:
                _shot.update(mode="png", auto=False, raw_ok=False)
    if img is None:
        t0 = time.time()
        img = _grab_png()
        took = time.time() - t0
        if probe:
            _shot["raw_n"] = 0
            if took < SHOT_FASTER * _shot["t_raw"]:
                _shot.update(mode="png", auto=False, png_avg=took, png_n=1)
                log(f"screenshots: a PNG takes {took:.1f} s again, raw capture {_shot['t_raw']:.1f} s - using PNG again")
        elif _shot["mode"] == "png" and _shot["raw_ok"]:
            _shot["png_n"] += 1
            _shot["png_avg"] += (took - _shot["png_avg"]) / min(_shot["png_n"], 4)
            if _shot["png_n"] >= 3 and _shot["t_raw"] < SHOT_FASTER * _shot["png_avg"]:
                _shot.update(mode="raw", auto=True, raw_n=0)
                log(f"screenshots: a PNG now takes {_shot['png_avg']:.1f} s, raw capture {_shot['t_raw']:.1f} s "
                    f"- using raw capture while PNGs are this slow")
    return _normalize(img)


# ----------------------------- recognition --------------------------------
def on_map(img):
    """Recognise the map screen by the Poké Ball menu button at the bottom (red on top, white below).
    Also works when the game is dimmed, because only ratios are compared."""
    r1, g1, b1 = (int(v) for v in img[1930, 883][::-1])
    r2, g2, b2 = (int(v) for v in img[2030, 883][::-1])
    red_top = r1 > 35 and r1 > 2.5 * max(g1, b1, 1)
    white_bottom = max(r2, g2, b2) - min(r2, g2, b2) < 20 and r2 > 0.8 * r1
    return red_top and white_bottom


def find_stop(img):
    """Looks for the PokéStop on the whole map area by the colour of the rings:
    bright blue = ready, purple = spun. Also works when the camera is turned,
    by day / at night and when the game is dimmed (brightness is relative).
    Returns (x, y, status) of the biggest stop, or None."""
    y0, y1, x1 = 700, 2050, 1500          # map area (without the buttons on the right and far stops at the top)
    hsv = cv2.cvtColor(img[y0:y1, :x1], cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    vmax = np.percentile(v, 99)
    masks = {
        "klaar": (h >= 92) & (h <= 108) & (s > 165) & (v > 0.75 * vmax),
        "gedraaid": (h >= 128) & (h <= 150) & (s > 70) & (v > 0.6 * vmax),
    }
    best = None
    for status, m in masks.items():
        m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
        n, _, st, cents = cv2.connectedComponentsWithStats(m)
        for i in range(1, n):
            area = int(st[i, cv2.CC_STAT_AREA])
            if area >= MIN_AREA and (best is None or area > best[0]):
                best = (area, int(cents[i][0]), int(cents[i][1]) + y0, status)
    if best is None:
        return None
    return best[1], best[2], best[3]


def ring_spun(img):
    """Stop screen: is the ring around the photo purple (= spun)?"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    yy, xx = np.mgrid[:img.shape[0], :img.shape[1]]
    d = np.hypot(xx - RING_CENTER[0], yy - RING_CENTER[1])
    px = hsv[(d > RING_R[0]) & (d < RING_R[1])]
    purple = ((px[:, 0] >= 125) & (px[:, 0] <= 165) & (px[:, 1] > 80)).mean()
    return purple > 0.4


def bag_full(img):
    """Pink message 'Your Item Bag is full.' in the middle of the stop screen."""
    hsv = cv2.cvtColor(img[1065:1140, 580:1200], cv2.COLOR_BGR2HSV).reshape(-1, 3)
    pink = ((hsv[:, 0] >= 150) & (hsv[:, 0] <= 178) & (hsv[:, 1] > 50) & (hsv[:, 2] > 140)).mean()
    return pink > 0.3


def debug_save(name, img=None):
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        cv2.imwrite(os.path.join(DEBUG_DIR, name), screenshot() if img is None else img)
    except Exception as e:  # noqa: BLE001
        log(f"debug screenshot failed: {e}")


# ------------------------------- acties -----------------------------------
# Samsung Game Booster-vergrendeling: "Sleep Vergrendelpictogram om te ontgrendelen".
# The little lock is in the middle of the screen; drag outwards from the lock.
UNLOCK_SWIPES = [
    (896, 1208, 896, 450),     # slotje omhoog slepen
    (896, 1208, 1600, 1208),   # drag the lock to the right
    (896, 1208, 896, 1950),    # slotje omlaag slepen
]


def is_dimmed(img):
    """Dimmed by Game Booster: even the whitest buttons are grey then.
    (A dark night scene still has white buttons, so that does not count as dimmed.)"""
    v = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[..., 2]
    return np.percentile(v, 99.5) < DARK_LIMIT


def unlock_game(img=None):
    """Pokémon GO dims and locks itself; undo it by swiping (like by hand)."""
    img = screenshot() if img is None else img
    if not is_dimmed(img):
        return img
    for x1, y1, x2, y2 in UNLOCK_SWIPES:
        log(f"game is dimmed/locked - tap + drag lock ({x1},{y1}) -> ({x2},{y2})")
        tap(884, 700)                  # the first tap makes the little lock appear
        time.sleep(1.2)
        swipe(x1, y1, x2, y2, 700)
        time.sleep(2.5)
        img = screenshot()
        if not is_dimmed(img):
            log("game unlocked")
            return img
    log("game stays dimmed")
    return img


def wake_if_dimmed(img):
    return unlock_game(img)


def find_green_button(img):
    """Looks for a big green/turquoise button (CLAIM REWARD!, OK, ...) in the lower half."""
    y0 = img.shape[0] // 2
    hsv = cv2.cvtColor(img[y0:], cv2.COLOR_BGR2HSV)
    m = ((hsv[..., 0] >= 45) & (hsv[..., 0] <= 95) &
         (hsv[..., 1] > 55) & (hsv[..., 2] > 170)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    n, _, st, _ = cv2.connectedComponentsWithStats(m)
    best = None
    for i in range(1, n):
        x, y, w, h, a = st[i]
        cx = x + w // 2
        # only wide buttons in the middle (OK / CLAIM REWARD), never POWER UP / EVOLVE
        if (a > 20000 and w > 700 and w > 2.2 * h and h > 60 and abs(cx - 884) < 200
                and (best is None or a > best[2])):
            best = (int(x + w // 2), int(y + h // 2 + y0), int(a))
    return best


def recover():
    """Not on the map (egg, reward, notification, stop screen, ...): click away until the map is back."""
    log("not on map - recovering")
    unlock()
    img = unlock_game()
    for _ in range(8):
        if on_map(img):
            log("back on map")
            return True
        btn = find_green_button(img)
        if btn:
            log(f"button found at ({btn[0]}, {btn[1]}) - tapping")
            tap(btn[0], btn[1])
        else:
            tap(*CENTER)               # eieren/animaties doortikken
        time.sleep(3)
        img = unlock_game()
    for _ in range(3):
        if on_map(img):
            log("back on map")
            return True
        back()
        time.sleep(2)
        img = screenshot()
    ok = on_map(img)
    log("back on map" if ok else "still not on map")
    return ok


def is_red(px):
    b, g, r = (int(v) for v in px)
    return r > 120 and r > 2 * max(g, b)


def in_encounter(img):
    """Catch screen: big red ball at the bottom in the middle (and not the map)."""
    return (not on_map(img)) and is_red(img[1870, 877]) and is_red(img[1960, 877])


def find_pokemon(img, stop=None):
    """Candidates for wild Pokémon: brightly coloured blobs around the player that are not
    map, stop, player or menu. Returns [(x, y), ...], biggest first."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s_, v = (hsv[..., i].astype(int) for i in range(3))
    # bright colours that do not occur in the map (green, turquoise and blue excluded)
    m = ((s_ > 130) & (v > 120) & ~((h >= 35) & (h <= 115))).astype(np.uint8)
    m[:650, :] = 0                      # horizon / bovenbalk
    m[:, 1420:] = 0                     # knoppen rechts
    m[1800:, :] = 0                     # menu onderaan
    m[1180:1560, 760:960] = 0           # speler
    if stop:
        x, y = stop
        m[max(y - 260, 0):y + 260, max(x - 260, 0):x + 260] = 0
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((21, 21), np.uint8))
    n, _, st, cents = cv2.connectedComponentsWithStats(m)
    now = time.time()
    cooldown[:] = [c for c in cooldown if c[2] > now]
    found = []
    for i in range(1, n):
        if 2500 < st[i, cv2.CC_STAT_AREA] < 80000:
            x, y = int(cents[i][0]), int(cents[i][1])
            if all(abs(x - cx) > 150 or abs(y - cy) > 150 for cx, cy, _ in cooldown):
                found.append((int(st[i, cv2.CC_STAT_AREA]), x, y))
    return [(x, y) for _, x, y in sorted(found, reverse=True)]


def wait_for(check, timeout, step=1.0):
    end = time.time() + timeout
    while time.time() < end:
        img = screenshot()
        if check(img):
            return img
        time.sleep(step)
    return None


def throw():
    swipe(ENC_BALL[0], ENC_BALL[1], ENC_BALL[0], THROW_END_Y, THROW_MS)


def catch_pokemon(x, y):
    """Tap a candidate; if the catch screen opens: give a berry, choose a ball, throw."""
    tap(x, y)
    img = wait_for(in_encounter, 8)
    if img is None:
        cooldown.append((x, y, time.time() + NO_POKEMON_COOLDOWN))
        if not on_map(screenshot()):
            recover()                  # e.g. buddy or stop screen opened by accident
        return False
    log(f"catch screen opened (Pokémon at {x}, {y})")
    debug_save("v_vangscherm.png", img)

    if BALL:
        tap(*ENC_BALL_BTN); time.sleep(1.5)
        tap(*BALL_POS[BALL]); time.sleep(1.5)

    for n in range(1, MAX_THROWS + 1):
        if BERRY:
            tap(*ENC_BERRY_BTN); time.sleep(1.5)
            tap(*BERRY_POS[BERRY]); time.sleep(1.5)
            throw()                    # give the berry to the Pokémon
            time.sleep(3)
        throw()
        log(f"ball {n} thrown")
        time.sleep(4)
        debug_save(f"v_worp_{n}.png")

        end = time.time() + 25         # schudden + resultaat afwachten
        while time.time() < end:
            img = screenshot()
            if in_encounter(img):      # missed or broke out: throw again
                log("not caught - again")
                break
            if on_map(img):
                log("Pokémon gevlucht")
                return True
            btn = find_green_button(img)
            if btn:                    # "TOTAL … XP" met OK
                log("caught ✔")
                tap(btn[0], btn[1]); time.sleep(3)
                back(); time.sleep(2)  # close the Pokémon summary (never POWER UP!)
                if not on_map(screenshot()):
                    recover()
                return True
            time.sleep(1.5)
        else:
            log("no result - recovering")
            recover()
            return True

    log("too many misses - running away")
    tap(*RUN_BTN); time.sleep(3)
    if not on_map(screenshot()):
        recover()
    return True


def try_catch(img, stop):
    for x, y in find_pokemon(img, stop)[:3]:
        log(f"mogelijke Pokémon op ({x}, {y}) - aantikken")
        if catch_pokemon(x, y):
            return True
    return False


startup_hook = None      # gamebot sets this: function(img) -> "map" | "handled" | None (see restart_game)


def restart_game():
    """Close Pokémon GO and start it again. While it starts, a screenshot is looked at every
    couple of seconds: news cards and notices are dismissed the moment they show up (the old
    way was to wait 45 s blindly), and the start is finished as soon as the map is there."""
    log("restarting Pokémon GO")
    t_begin = time.time()
    adb("shell", "am", "force-stop", PACKAGE)
    t_stopped = time.time() - t_begin
    time.sleep(1)
    cmd = ["monkey", "-p", PACKAGE, "-c", "android.intent.category.LAUNCHER", "1"]
    if startup_hook is None:             # (without gamebot: the old, slower way)
        adb("shell", *cmd)
        time.sleep(45)                   # starting up + loading the map
        for _ in range(3):               # opstartmeldingen wegtikken
            if on_map(screenshot()):
                break
            tap(*CENTER)
            time.sleep(3)
        return
    # 'monkey' can take half a minute to return while the game is starting (it waits for the
    # app), so it is not waited for: the screenshots start straight away.
    launch = subprocess.Popen(["adb", "shell", *cmd], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    time.sleep(2)                        # nothing useful to see in the first moments
    t0, on_map_frames, first_shot = time.time(), 0, None
    while time.time() - t0 < 100:
        try:
            img = screenshot()
            if first_shot is None:
                first_shot = time.time() - t_begin
            result = startup_hook(img)
        except Exception as e:  # noqa: BLE001
            log(f"start-up check failed: {e}")
            time.sleep(2)
            continue
        if result == "map":
            on_map_frames += 1           # twice in a row: a card that slides in a moment later is caught too
            if on_map_frames >= 2:
                break
        else:
            on_map_frames = 0
            time.sleep(0.8 if result == "handled" else 0.3)
    else:
        log("Pokémon GO did not reach the map within 100 s - carrying on")
        on_map_frames = 0
    err = ""
    if launch.poll() is None:            # (still waiting for the game: no need for it any more)
        launch.kill()
    elif launch.returncode != 0:
        err = launch.stderr.read().decode(errors="ignore").strip()[:120]
        log(f"WARNING: starting Pokémon GO with monkey failed ({err or 'return code ' + str(launch.returncode)})")
    if on_map_frames >= 2:
        log(f"Pokémon GO is on the map ({time.time() - t_begin:.0f} s after starting; closing the old game took "
            f"{t_stopped:.1f} s, first screenshot after {first_shot or 0:.0f} s)")


def spin_once():
    """One round. Returns the number of seconds until the next round."""
    global stop_pos, fails
    if "mWakefulness=Awake" not in adb("shell", "dumpsys", "power"):
        log("screen off - waking")
        adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")
        time.sleep(2)
    if unlock():
        time.sleep(2)

    img = screenshot()
    if not on_map(img):
        if recover():
            fails = 0
        else:
            fails += 1
            if fails >= MAX_FAILS:
                restart_game()
                fails = 0
        return RETRY
    fails = 0
    img = wake_if_dimmed(img)

    if CATCH:
        st = find_stop(img)
        if try_catch(img, st[:2] if st else None):
            img = screenshot()
            if not on_map(img):
                return RETRY

    found = find_stop(img)
    if found is None:
        log("no stop found on map - is the stop in view?")
        return RETRY
    x, y, status = found
    stop_pos = [x, y]
    log(f"stop found at ({x}, {y}) - {status}")
    if status != "klaar":
        return 60  # still in cooldown: look again in a minute

    debug_save("1_kaart.png", img)
    tap(x, y)
    time.sleep(3)
    img = screenshot()
    debug_save("2_geopend.png", img)
    if on_map(img):
        log("stop screen did not open - retry next time")
        return RETRY
    time.sleep(2)                      # let the stop screen load (loading icon top left)
    spun = False
    for attempt in range(1, 5):
        swipe(SPIN_X1, SPIN_Y, SPIN_X2, SPIN_Y, 180)
        time.sleep(2.5)
        img = screenshot()
        debug_save(f"3_gedraaid_{attempt}.png", img)
        if ring_spun(img):
            spun = True
            break
        if bag_full(img):
            log(f"BAG FULL - clean up your bag; retrying in {BAG_FULL_WAIT // 60} min")
            tap(*CLOSE)
            time.sleep(2)
            return BAG_FULL_WAIT
        log(f"swipe attempt {attempt}: ring still blue")
    time.sleep(1.5)                    # let the items appear
    tap(*CLOSE)
    time.sleep(2)

    img = screenshot()
    debug_save("4_na_sluiten.png", img)
    if not on_map(img):
        recover()
    if spun:
        log("stop spun ✔")
        return INTERVAL
    log("spin failed - retrying in 30 s")
    return RETRY


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "loop"

    if mode == "test":
        img = screenshot()
        log(f"on the map: {on_map(img)}  |  brightness: {img.mean():.0f}")
        found = find_stop(img)
        log(f"stop: {found}")
        x, y = (found[0], found[1]) if found else stop_pos
        cv2.rectangle(img, (0, 700), (1500, 2050), (0, 255, 0), 4)
        cv2.circle(img, (x, y), 14, (0, 0, 255), -1)
        cv2.imwrite("check.png", img)
        log("check.png saved (green = search area, red = stop found)")
        return

    if mode in ("catch", "vang"):
        img = unlock_game(screenshot())
        st = find_stop(img)
        found = find_pokemon(img, st[:2] if st else None)
        log(f"candidates: {found}")
        dbg = img.copy()
        for i, (x, y) in enumerate(found):
            cv2.circle(dbg, (x, y), 40, (0, 0, 255) if i < 3 else (0, 255, 255), 6)
        debug_save("v_kandidaten.png", dbg)
        if not try_catch(img, st[:2] if st else None):
            log("nothing caught (no Pokémon found or no catch screen)")
        return

    if mode == "once":
        spin_once()
        return

    log(f"started - log: {LOGFILE}")
    detect_screen()
    while True:
        if not screen["ok"]:
            wait_unsupported()
            continue
        try:
            wait = spin_once()
        except Exception as e:  # noqa: BLE001
            log(f"error: {e}")
            wait = RETRY
        time.sleep(wait)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("stopped")
