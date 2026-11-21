#!/usr/bin/env python3
"""
Pokémon GO Automation web interface - watch the phone and the log from any browser.

Open from a device on the same network:  http://gamebot.local:8080
(or http://<pi-ip>:8080)

- live video of the phone (H.264 from screenrecord -> MJPEG, ~8 fps)
  with a screenshot fallback if ffmpeg/screenrecord is not available
- log and daily counters
- buttons: start / stop / restart the bot
- options (on/off): catch wild Pokémon, spin PokéStops, open gifts, send gifts
"""
import base64
import json
import os
import re
import subprocess
import shutil
import threading
import time
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

import spin_stop as S        # the phone's screen (which display, how big) is found there

# ================================ SETTINGS ================================
PORT = 8080
APP_NAME = "Pokémon GO Automation"        # the name shown in the browser (tab, header)
USER_FILE = os.path.expanduser("~/.gamebot_web_user")           # one line: the login name (default: admin)
PASSWORD_FILE = os.path.expanduser("~/.gamebot_web_password")   # one line: the password (no file = no login)
LOGFILE = os.path.expanduser("~/spin.log")
CONTROL_FILE = os.path.expanduser("~/gamebot_control.json")
SERVICE = "spin-stop"
VIDEO_BASE = 704                            # width (px) of the screenrecord picture; the height follows the shape of the phone screen
VIDEO_FPS = 8
VIDEO_WIDTH = 480                           # width of the frames sent to the browser
VIDEO_BITRATE = "2000000"
OPTIONS = {                                 # key -> label (default: on)
    "daily_cycle": "Daily run: both Pokémon GO apps one after another until full",
    "battle": "Battles: in the daily run the chosen app fights GO Battle League battles first",
    "catch": "Catch wild Pokémon",
    "spin": "Spin PokéStops",
    "gifts_open": "Open gifts from friends",
    "gifts_send": "Send gifts to friends",
    "curveball": "Always throw a curveball",
    "fast_catch": "Fast catch: after a clear hit press BACK to skip the catch animation (the result is checked on the map)",
    "spin_only_when_full": "Spin PokéStops when Pokémon storage is full (catching pauses until there is room again)",
    "close_when_full": "Close the game when Pokémon storage and bag are both full",
    "buddy": "My buddy walks along on the map (a Pokémon next to the trainer may be the buddy)",
    "fast_look": "Realistic look around",
}
# ==========================================================================

latest = {"jpg": None, "time": 0.0, "error": "", "mode": "starting"}
cond = threading.Condition()
viewers = {"last": 0.0}


def web_user():
    try:
        with open(USER_FILE) as f:
            return f.read().strip() or "admin"
    except OSError:
        return "admin"


def password():
    try:
        with open(PASSWORD_FILE) as f:
            return f.read().strip()
    except OSError:
        return None


def publish(jpg, mode):
    with cond:
        latest.update(jpg=jpg, time=time.time(), error="", mode=mode)
        cond.notify_all()


_phone = {"t": 0.0, "tried": False}


def phone():
    """(display id, width, height) of the phone screen, as the bot found them (SCREEN_FILE). When the bot has
    not run yet, the screen is looked up here once."""
    now = time.time()
    if now - _phone["t"] > 10:
        _phone["t"] = now
        if not S.load_screen() and not _phone["tried"]:
            _phone["tried"] = True
            try:
                S.detect_screen()
            except Exception:  # noqa: BLE001
                pass
    return S.screen["id"], S.screen["w"], S.screen["h"]


def video_size(p):
    """screenrecord --size for this phone: VIDEO_BASE wide, the height in the same shape (multiple of 16)."""
    return f"{VIDEO_BASE}x{max(16, int(round(VIDEO_BASE * p[2] / p[1] / 16)) * 16)}"


def snapshot():
    """One screenshot via screencap (slow, ~1 s) - used as first frame and as fallback."""
    phone()
    raw = subprocess.run(["adb", "exec-out", "screencap", *S._dargs(), "-p"],
                         capture_output=True, timeout=15).stdout
    start = raw.find(b"\x89PNG")
    img = cv2.imdecode(np.frombuffer(raw[start:], np.uint8), cv2.IMREAD_COLOR) if start >= 0 else None
    if img is None:
        raise RuntimeError("no image from phone (is ADB connected?)")
    h, w = img.shape[:2]
    img = cv2.resize(img, (VIDEO_WIDTH, int(h * VIDEO_WIDTH / w)), interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()


def watching():
    return time.time() - viewers["last"] < 20


def video_loop():
    """Background: screenrecord (H.264) -> ffmpeg -> JPEG frames, only while someone watches."""
    fails = 0
    while True:
        if not watching():
            time.sleep(0.5)
            continue
        try:
            publish(snapshot(), "starting")    # screenrecord only sends frames when the screen changes
        except Exception as e:  # noqa: BLE001
            latest["error"] = str(e)
            time.sleep(3)
            continue
        if fails >= 3:                         # video keeps failing: screenshots only
            try:
                publish(snapshot(), "screenshots")
            except Exception as e:  # noqa: BLE001
                latest["error"] = str(e)
            time.sleep(1)
            continue
        rec = ff = None
        cur = phone()
        try:
            rec = subprocess.Popen(
                ["adb", "exec-out", "screenrecord", *(["--display-id", str(cur[0])] if cur[0] else []),
                 "--output-format=h264", "--size", video_size(cur), "--bit-rate", VIDEO_BITRATE,
                 "--time-limit", "180", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            ff = subprocess.Popen(
                ["ffmpeg", "-loglevel", "error", "-probesize", "32768", "-analyzeduration", "0",
                 "-f", "h264", "-i", "pipe:0", "-vf", f"fps={VIDEO_FPS},scale={VIDEO_WIDTH}:-2",
                 "-q:v", "7", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"],
                stdin=rec.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            rec.stdout.close()
            buf = b""
            got = 0
            started = time.time()
            while watching() and phone() == cur:        # (a changed screen, e.g. a foldable unfolded: start again)
                chunk = ff.stdout.read1(65536) if hasattr(ff.stdout, "read1") else ff.stdout.read(65536)
                if not chunk:
                    break
                buf += chunk
                while True:
                    a = buf.find(b"\xff\xd8")
                    b = buf.find(b"\xff\xd9", a + 2)
                    if a < 0 or b < 0:
                        break
                    publish(buf[a:b + 2], "live video")
                    got += 1
                    buf = buf[b + 2:]
                if len(buf) > 5_000_000:
                    buf = b""
            fails = 0 if (got or time.time() - started > 60) else fails + 1
        except FileNotFoundError:
            latest["error"] = "ffmpeg missing (sudo apt install ffmpeg) - using screenshots"
            fails = 3
        except Exception as e:  # noqa: BLE001
            latest["error"] = str(e)
            fails += 1
        finally:
            for p in (ff, rec):
                if p and p.poll() is None:
                    p.kill()
        time.sleep(0.5)



def bot_running():
    return subprocess.run(["systemctl", "is-active", SERVICE], capture_output=True).stdout.decode().strip() == "active"


FORCE_FILE = os.path.expanduser("~/gamebot_force.json")   # tells the bot: start the daily run right now


def bot_action(action):
    """Start / Stop / Restart button. Start and Restart make the bot begin the daily run at once
    (a fresh run: both games, full time each), also when the bot was already running."""
    if action in ("start", "restart"):
        try:
            with open(FORCE_FILE, "w") as f:
                f.write(str(time.time()))
        except OSError:
            pass
        if action == "start" and bot_running():
            action = "restart"                    # 'start' on a running service does nothing
    subprocess.run(["sudo", "-n", "/usr/bin/systemctl", action, SERVICE], capture_output=True)


def sh(*args, timeout=20):
    try:
        return subprocess.run(["adb", "shell", *map(str, args)], capture_output=True,
                              timeout=timeout).stdout.decode(errors="ignore")
    except Exception:  # noqa: BLE001
        return ""


def write_log(msg):
    try:
        with open(LOGFILE, "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "  " + msg + "\n")
    except OSError:
        pass


CLOSE_ALL_BTN = (875, 1640)     # 'Alle sluiten' / 'Close all' on the recent apps screen
closing = threading.Lock()


def game_packages():
    pk = [l.split(":", 1)[1].strip() for l in sh("pm", "list", "packages", "pokemongo").splitlines()
          if l.startswith("package:")]
    return pk or ["com.nianticlabs.pokemongo"]


def in_recents():
    return "pokemongo" in sh("dumpsys", "activity", "recents")


def close_game():
    """Stop the bot and close Pokémon GO for good: the app is force-stopped (nothing keeps
    running in the background) and taken out of the recent apps."""
    if not closing.acquire(blocking=False):
        return
    try:
        subprocess.run(["sudo", "-n", "/usr/bin/systemctl", "stop", SERVICE], capture_output=True)
        time.sleep(1)
        pkgs = game_packages()
        for p in pkgs:
            sh("am", "force-stop", p)
        if in_recents():                          # 1st way: remove just the game's task
            for tid in set(re.findall(r"(?:taskId|id)=(\d+)[^\n]*pokemongo", sh("am", "stack", "list"))):
                sh("am", "stack", "remove", tid)
                sh("am", "task", "remove", tid)
        if in_recents():                          # 2nd way: recent apps screen -> 'Close all'
            sh("input", "keyevent", "KEYCODE_APP_SWITCH")
            time.sleep(2.5)
            x, y = CLOSE_ALL_BTN
            sh("input", "swipe", x, y, x, y, 120)
            time.sleep(2)
        sh("input", "keyevent", "KEYCODE_HOME")
        for p in pkgs:
            sh("am", "force-stop", p)
        running = [p for p in pkgs if sh("pidof", p).strip()]
        write_log("game closed from the web interface (bot stopped): " + ", ".join(pkgs)
                  + (" - STILL RUNNING: " + ", ".join(running) if running else "")
                  + (" - still listed in recent apps" if in_recents() else ""))
    finally:
        closing.release()


def adb_input(*args):
    try:
        subprocess.Popen(["adb", "shell", "input", *map(str, args)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        pass


def read_log(n=80):
    try:
        with open(LOGFILE, "rb") as f:
            f.seek(0, 2)
            f.seek(max(f.tell() - 40000, 0))
            return f.read().decode(errors="ignore").splitlines()[-n:]
    except OSError:
        return []


DEFAULT_OFF = {"curveball", "buddy", "fast_catch", "battle"}                 # options that start unticked
THROW_TARGETS = ("realistic", "off", "nice", "great", "excellent")


def read_control():
    c = {k: k not in DEFAULT_OFF for k in OPTIONS}
    c["daily_time"] = "08:00"
    c["daily_max_min"] = 480
    c["throw_target"] = "realistic"
    c["battle_app"] = ""                        # empty: the first (Play Store) app
    c["battle_league"] = "Great League"
    c["battle_count"] = 5
    try:
        with open(CONTROL_FILE) as f:
            c.update(json.load(f))
    except (OSError, ValueError):
        pass
    c.pop("realistic", None)                    # was a separate tick box for a short while
    c.pop("daily_incense", None)                # option removed (the game does not accept injected touches on the incense)
    if c.get("profile_v") != 1:                 # once: 'Realistic' becomes the standard throw profile
        c["throw_target"] = "realistic"
        c["profile_v"] = 1
        try:
            write_control(c)
        except OSError:
            pass
    return c


def write_control(c):
    with open(CONTROL_FILE, "w") as f:
        json.dump(c, f)


MAIN_PACKAGE = "com.nianticlabs.pokemongo"
_apps = {"t": 0.0, "list": []}


def game_apps():
    """[(package, label)] of the installed Pokémon GO apps, Play Store first (looked up at most every 30 s)."""
    now = time.time()
    if not _apps["list"] or now - _apps["t"] > 30:
        pk = sorted(set(game_packages()), key=lambda p: (p != MAIN_PACKAGE, p))
        _apps.update(t=now, list=[(p, "Pokémon GO (Play Store)" if p == MAIN_PACKAGE else "Pokémon GO (" + (p[len(MAIN_PACKAGE):].lstrip(".") if p.startswith(MAIN_PACKAGE) and len(p) > len(MAIN_PACKAGE) else p) + ")")
                                  for p in pk])
    return _apps["list"]


def status():
    active = subprocess.run(["systemctl", "is-active", SERVICE], capture_output=True).stdout.decode().strip()
    stats = ""
    for line in reversed(read_log(400)):
        m = re.search(r"\(today: ([^)]*)\)", line)
        if m:
            stats = m.group(1)
            break
    _, pw, ph = phone()
    return {"service": active, "stats": stats, "control": read_control(), "labels": OPTIONS, "apps": game_apps(), "rec": rec_status(),
            "w": pw, "h": ph, "phone": S.screen["model"], "screen_note": S.screen["note"], "screen_ok": S.screen["ok"],
            "video": latest["mode"], "error": latest["error"],
            "age": round(time.time() - latest["time"], 1) if latest["time"] else None}


PAGE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>@@NAME@@</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%230c1a20'/%3E%3Ccircle cx='16' cy='16' r='11' fill='none' stroke='%2342b8ff' stroke-width='2.4' stroke-dasharray='52 18' stroke-linecap='round' transform='rotate(-70 16 16)'/%3E%3Ccircle cx='16' cy='16' r='6' fill='none' stroke='%2342b8ff' stroke-width='2.4'/%3E%3Ccircle cx='16' cy='16' r='2' fill='%2342b8ff'/%3E%3C/svg%3E">
<style>
 :root {
  color-scheme: dark;
  --night:#0c1a20; --dusk:#122a32; --ridge:#24444e; --chalk:#e9f2f0; --mist:#8aa8ab;
  --run:#5ee0a9; --stop:#ff7b67; --hold:#f4b94a; --blue:#42b8ff;
  --ring:var(--ridge); --ar:0.8;
 }
 * { box-sizing:border-box; }
 html, body { margin:0; }
 body { background:var(--night); color:var(--chalk);
  font:14.5px/1.45 "Avenir Next", "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif; }
 button, input, select { font:inherit; color:inherit; }
 :focus-visible { outline:2px solid var(--blue); outline-offset:2px; }
 [hidden] { display:none !important; }

 /* ---------- top bar ---------- */
 .top { display:flex; flex-wrap:wrap; align-items:center; gap:10px 28px; padding:12px 20px; border-bottom:1px solid var(--ridge); }
 .brand { display:flex; align-items:center; gap:11px; margin-right:auto; }
 .brand svg { width:28px; height:28px; color:var(--blue); flex:none; }
 .brand h1 { margin:0; font-size:18px; font-weight:650; letter-spacing:-0.01em; }
 .stats { display:flex; flex-wrap:wrap; gap:2px 18px; color:var(--mist); }
 .stats b { color:var(--chalk); font-size:17px; font-weight:650; font-variant-numeric:tabular-nums; margin-right:4px; }
 .state { display:flex; align-items:center; gap:9px; padding:5px 14px 5px 11px; border:1px solid var(--ridge); border-radius:999px; font-weight:600; }
 .state i { width:9px; height:9px; border-radius:50%; background:var(--mist); }
 .state[data-s="run"] { border-color:#2a6b57; } .state[data-s="run"] i { background:var(--run); }
 .state[data-s="hold"] { border-color:#7a6130; } .state[data-s="hold"] i { background:var(--hold); }
 .state[data-s="bad"] { border-color:#7b3a33; } .state[data-s="bad"] i { background:var(--stop); }

 /* ---------- layout ---------- */
 main { display:grid; grid-template-columns:minmax(0,1fr); gap:22px; padding:18px 20px 28px; }
 .stage { width:min(480px, 100%); min-width:0; }
 .panel { min-width:0; display:flex; flex-direction:column; }

 /* ---------- the phone screen: its frame shows the state of the bot ---------- */
 .frame { padding:6px; border-radius:24px; background:var(--dusk); border:2px solid var(--ring);
  box-shadow:0 0 0 5px color-mix(in srgb, var(--ring) 16%, transparent); transition:border-color .3s, box-shadow .3s; }
 .frame[data-ring="run"] { --ring:var(--run); animation:breathe 3.6s ease-in-out infinite; }
 .frame[data-ring="hold"] { --ring:var(--hold); }
 .frame[data-ring="bad"] { --ring:var(--stop); }
 @keyframes breathe { 50% { box-shadow:0 0 0 9px color-mix(in srgb, var(--ring) 7%, transparent); } }
 .frame img { display:block; width:100%; aspect-ratio:var(--ar); border-radius:18px; background:#000; }
 .frame img.manual { cursor:crosshair; touch-action:none; }
 .caption { display:flex; justify-content:space-between; gap:12px; margin:10px 6px 0; color:var(--mist); font-size:12.5px; }
 .caption .late { color:var(--hold); }
 .note.hold { background:#33290f; color:var(--hold); }
 .note { margin:10px 4px 0; padding:8px 12px; border-radius:9px; font-size:13px; background:#3a1f1c; color:#ffc2b8; }

 /* ---------- control column ---------- */
 .sec { padding:10px 0; border-top:1px solid var(--ridge); }
 .sec:first-child { border-top:0; padding-top:0; }
 .bar { display:flex; flex-wrap:wrap; gap:8px; }
 .btn { height:36px; padding:0 16px; border-radius:9px; border:1px solid var(--ridge); background:transparent; cursor:pointer; font-weight:600; }
 .btn:hover { background:var(--dusk); }
 .btn.primary { background:var(--blue); border-color:var(--blue); color:#04202e; }
 .btn.primary:hover { background:#6cc8ff; }
 .btn.danger { color:var(--stop); border-color:#6b3a35; }
 .btn.danger:hover { background:#2a1816; }
 .help { margin-top:8px; color:var(--mist); font-size:12.5px; }
 .help summary { cursor:pointer; width:max-content; }
 .help p { margin:6px 0 0; max-width:62ch; }
 #manualbar { display:none; }
 #manualbar.on { display:block; }
 #manualbar .bar { align-items:center; }
 #txt { height:36px; width:140px; padding:0 10px; border-radius:9px; border:1px solid var(--ridge); background:var(--dusk); }

 .groups { display:grid; grid-template-columns:minmax(0,1fr); gap:0 44px; align-items:start; }
 .group { padding:0 0 10px; }
 .group h2 { margin:0 0 2px; font-size:13px; font-weight:650; color:var(--mist); }
 .row { display:flex; align-items:center; gap:14px; padding:4px 0; min-height:32px; }
 .row .txt { flex:1; min-width:0; }
 .t { display:block; }
 .h { display:block; margin-top:1px; color:var(--mist); font-size:12px; line-height:1.35; }
 label.sw { position:relative; cursor:pointer; }
 label.sw input { position:absolute; opacity:0; width:1px; height:1px; }
 .track { flex:none; position:relative; width:36px; height:21px; border-radius:21px; background:var(--ridge); transition:background .15s; }
 .track::after { content:""; position:absolute; top:3px; left:3px; width:15px; height:15px; border-radius:50%; background:var(--chalk); transition:transform .15s; }
 label.sw input:checked + .track { background:var(--blue); }
 label.sw input:checked + .track::after { transform:translateX(15px); background:#04202e; }
 label.sw input:focus-visible + .track { outline:2px solid var(--chalk); outline-offset:2px; }
 .inp { height:32px; padding:0 9px; border-radius:8px; border:1px solid var(--ridge); background:var(--dusk); }
 input[type=number].inp { width:78px; }
 input[type=text].inp { width:172px; max-width:100%; }
 a.btn { display:inline-flex; align-items:center; text-decoration:none; color:inherit; }
 .recbtns { display:flex; gap:8px; margin-left:auto; }
 .rechint { margin-top:6px; color:var(--mist); font-size:13px; }
 .recbtns .btn[disabled] { opacity:.45; cursor:default; }
 .group.off .field { display:none; }
 #bapp { max-width:210px; }
 input[type=time].inp { width:116px; }
 select.inp { max-width:100%; }
 .unit { color:var(--mist); }
 .field label { cursor:default; }

 /* ---------- log ---------- */
 .logsec { display:flex; flex-direction:column; }
 .loghead { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:6px; }
 .loghead h2 { margin:0; font-size:13px; font-weight:650; color:var(--mist); }
 .loghead span { color:var(--mist); font-size:12px; }
 pre { margin:0; font:12px/1.55 ui-monospace, "Cascadia Mono", "SF Mono", Consolas, monospace; max-height:46vh; overflow:auto; }
 .ln { display:block; white-space:pre-wrap; overflow-wrap:anywhere; color:#c6d6d4; }
 .ts { color:var(--mist); margin-right:10px; }
 .ln.good { color:var(--run); } .ln.warn { color:var(--hold); } .ln.bad { color:var(--stop); }

 /* ---------- wide screens: the phone on the left, controls on the right ---------- */
 @media (min-width:1000px) {
  main { grid-template-columns:auto minmax(0,1fr); gap:32px; align-items:start; }
  .stage { width:clamp(320px, calc((100vh - 195px) * var(--ar)), 620px); position:sticky; top:16px; }
  .groups { grid-template-columns:1fr 1fr; }
 }
 /* tall enough: everything fits on one page, the log takes the space that is left */
 @media (min-width:1000px) and (min-height:780px) {
  html, body { height:100%; }
  body { display:flex; flex-direction:column; overflow:hidden; }
  main { flex:1; min-height:0; padding-bottom:18px; align-items:stretch; }
  .stage { position:static; }
  .panel { min-height:0; overflow-y:auto; }
  .logsec { flex:1 1 auto; min-height:96px; }
  .logsec pre { flex:1; min-height:0; max-height:none; overflow:hidden; }
 }
 @media (max-width:560px) {
  .top { padding:10px 14px; } main { padding:14px; }
  .stats { order:3; width:100%; }
 }
 @media (prefers-reduced-motion:reduce) { * { animation:none !important; transition:none !important; } }
</style></head><body>
<header class="top">
 <div class="brand">
  <svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" aria-hidden="true">
   <circle cx="16" cy="16" r="13" stroke-dasharray="60 22" transform="rotate(-70 16 16)"/>
   <circle cx="16" cy="16" r="7.5"/><circle cx="16" cy="16" r="2.3" fill="currentColor" stroke="none"/>
  </svg>
  <h1>@@NAME@@</h1>
 </div>
 <div class="stats" id="stats" aria-label="Today"></div>
 <div class="state" id="state" data-s="wait" role="status"><i></i><span id="svc">Connecting</span></div>
</header>
<main>
 <section class="stage" aria-label="Phone screen">
  <div class="frame" id="frame" data-ring="wait">
   <img id="scr" src="stream" alt="Live view of the phone screen" draggable="false">
  </div>
  <div class="caption"><span id="model"></span><span id="vid">Connecting</span></div>
  <div class="note" id="scr_note" hidden></div>
  <div class="note hold" id="manual_note" hidden>You are in control: click to tap, drag to swipe, hold to long-press.</div>
 </section>

 <div class="panel">
  <section class="sec" aria-label="Bot">
   <div class="bar">
    <button class="btn primary" onclick="act('start')">Start</button>
    <button class="btn danger" onclick="act('stop')">Stop</button>
    <button class="btn" onclick="act('restart')">Restart</button>
    <button class="btn danger" onclick="act('close')">Close game</button>
   </div>
   <details class="help"><summary>What do these buttons do?</summary>
    <p>Start and Restart begin a new daily run right away. Stop pauses the bot so you can take over, for example for quests; stop it too before you open Pokémon GO on another device. Close game stops the bot and closes Pokémon GO on the phone; Start plays again. A game that reaches its max time is closed.</p>
   </details>
  </section>

  <section class="sec" id="manualbar" aria-label="Manual control">
   <div class="bar">
    <button class="btn" onclick="key('back')">Back</button>
    <button class="btn" onclick="key('home')">Home</button>
    <button class="btn" onclick="key('apps')">Recent apps</button>
    <input id="txt" class="inp" placeholder="Type text" aria-label="Text to type on the phone">
    <button class="btn" onclick="sendText()">Send</button>
    <span class="recbtns">
     <button class="btn" id="recgo" onclick="recStart()" title="Play one battle yourself on the phone; the pictures and touches are saved so the bot can learn the battle screens.">Record battle</button>
     <button class="btn danger" id="recstop" onclick="recStop()" hidden>Stop</button>
     <a class="btn" id="recdl" href="record/download" hidden>Download</a>
    </span>
   </div>
   <div class="rechint" id="rechint" hidden></div>
  </section>

  <section class="sec" aria-label="Options">
   <div class="groups">
    <div class="col">
     <div class="group" data-keys="daily_cycle">
      <h2>Daily run</h2>
      <div class="switches"></div>
      <div class="row field"><label class="txt" for="dtime"><span class="t">Starts every day at</span></label>
       <input type="time" id="dtime" class="inp" onchange="setTime(this.value)"></div>
      <div class="row field"><label class="txt" for="dmax"><span class="t">Max time per game</span>
        <span class="h">Then the next game starts.</span></label>
       <span><input type="number" id="dmax" class="inp" min="5" max="1440" step="5" onchange="setMax(this.value)"> <span class="unit">min</span></span></div>
     </div>
     <div class="group" id="g_battle" data-keys="battle">
      <h2>Battles</h2>
      <div class="switches"></div>
      <div class="row field"><label class="txt" for="bapp"><span class="t">Battle in</span>
        <span class="h">This app battles first, then spins and catches.</span></label>
       <select id="bapp" class="inp" onchange="setBattle('battle_app', this.value)"></select></div>
      <div class="row field"><label class="txt" for="bleague"><span class="t">League</span>
        <span class="h">Part of the name as it shows on the phone.</span></label>
       <input type="text" id="bleague" class="inp" maxlength="40" onchange="setBattle('battle_league', this.value)"></div>
      <div class="row field"><label class="txt" for="bcount"><span class="t">Battles per run</span></label>
       <input type="number" id="bcount" class="inp" min="1" max="50" onchange="setBattle('battle_count', this.value)"></div>
     </div>
     <div class="group" data-keys="gifts_open gifts_send">
      <h2>Gifts</h2>
      <div class="switches"></div>
     </div>
    </div>
    <div class="col">
     <div class="group" data-keys="spin spin_only_when_full close_when_full">
      <h2>PokéStops and storage</h2>
      <div class="switches"></div>
     </div>
     <div class="group" data-keys="catch curveball fast_catch fast_look buddy">
      <h2>Catching</h2>
      <div class="switches"></div>
      <div class="row field"><label class="txt" for="ttarget"><span class="t">Throw target</span>
        <span class="h" id="thint"></span></label>
       <select id="ttarget" class="inp" onchange="setTarget(this.value)">
        <option value="realistic">Realistic</option><option value="off">Off</option><option value="nice">Nice</option>
        <option value="great">Great</option><option value="excellent">Excellent</option>
       </select></div>
     </div>
     <div class="group" id="g_more" data-keys="" hidden>
      <h2>More</h2>
      <div class="switches"></div>
     </div>
    </div>
   </div>
  </section>

  <section class="sec logsec" aria-label="Log">
   <div class="loghead"><h2>Log</h2><span>Newest first</span></div>
   <pre id="log">Loading…</pre>
  </section>
 </div>
</main>
<script>
const $ = id => document.getElementById(id);
const img = $('scr');
img.onerror = () => setTimeout(() => { img.src = 'stream?t=' + Date.now(); }, 3000);

// Plain wording for each option: [title, extra line]. An option that is not listed shows the text from the server.
const WORDS = {
  daily_cycle: ['Play both Pokémon GO apps', 'Each game runs until full or out of time.'],
  battle: ['Fight battles first', 'Daily run only. The chosen app fights its GO Battle League battles, then spins and catches.'],
  catch: ['Catch wild Pokémon'],
  curveball: ['Always throw a curveball'],
  fast_catch: ['Fast catch', 'After a clear hit, press Back to skip the catch animation. The result is checked on the map.'],
  fast_look: ['Look around like a person'],
  buddy: ['My buddy walks along on the map', 'A Pokémon next to the trainer may be the buddy.'],
  spin: ['Spin PokéStops'],
  spin_only_when_full: ['Spin PokéStops when Pokémon storage is full', 'Catching pauses until there is room again.'],
  close_when_full: ['Close the game when storage and bag are full'],
  gifts_open: ['Open gifts from friends'],
  gifts_send: ['Send gifts to friends'],
};
const TARGETS = {
  realistic: 'Mostly Great, not every throw perfect.', off: 'Just throw.',
  nice: 'Aim for Nice.', great: 'Aim for Great.', excellent: 'Aim for Excellent.',
};
const STATES = { active: ['Running', 'run'], inactive: ['Stopped', 'hold'], activating: ['Starting', 'run'],
                 deactivating: ['Stopping', 'hold'], failed: ['Failed', 'bad'] };

let built = false, lastLog = '', manual = false, down = null, PW = 1768, PH = 2208;
const fitMQ = window.matchMedia('(min-width:1000px) and (min-height:780px)');

function addSwitch(box, key, label) {
  const [title, hint] = WORDS[key] || [label];
  const row = document.createElement('label');
  row.className = 'row sw';
  const txt = document.createElement('span'); txt.className = 'txt';
  const t = document.createElement('span'); t.className = 't'; t.textContent = title; txt.append(t);
  if (hint) { const h = document.createElement('span'); h.className = 'h'; h.textContent = hint; txt.append(h); }
  const inp = document.createElement('input');
  inp.type = 'checkbox'; inp.setAttribute('role', 'switch'); inp.id = 'o_' + key; inp.dataset.k = key;
  const track = document.createElement('span'); track.className = 'track';
  row.append(txt, inp, track);
  box.append(row);
}
function buildOptions(labels) {
  const placed = new Set();
  document.querySelectorAll('.group').forEach(g => {
    const box = g.querySelector('.switches');
    for (const k of g.dataset.keys.split(' ')) if (k && k in labels) { addSwitch(box, k, labels[k]); placed.add(k); }
  });
  const more = $('g_more');                          // an option from a newer version that has no place yet
  for (const k of Object.keys(labels)) if (!placed.has(k)) { addSwitch(more.querySelector('.switches'), k, labels[k]); more.hidden = false; }
}
document.addEventListener('change', e => { if (e.target.matches('.switches input')) setOpt(e.target.dataset.k, e.target.checked); });

function esc(s) { return s.replace(/[&<>]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[c])); }
function lineHtml(l, day) {
  const m = /^(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d)\s+(.*)$/.exec(l);
  let ts = '', msg = l;
  if (m) { ts = (m[1] === day ? '' : m[1].slice(5) + ' ') + m[2]; msg = m[3]; }
  const cls = /error|failed|could not|WARNING|stuck/i.test(msg) ? 'bad'
            : /FULL|not playing|paused|did not/i.test(msg) ? 'warn'
            : /CAUGHT|spun ✔|finished|started/i.test(msg) ? 'good' : '';
  return `<span class="ln ${cls}"><span class="ts">${ts}</span>${esc(msg)}</span>`;
}
function showLog() {                                 // wide screen: as many lines as fit, so nothing has to be scrolled
  const pre = $('log'), lines = lastLog.split('\n').filter(Boolean);
  const day = lines.length && /^\d{4}-\d\d-\d\d/.test(lines[0]) ? lines[0].slice(0, 10) : '';
  const html = lines.map(l => lineHtml(l, day));
  if (!html.length) { pre.textContent = 'Nothing logged yet.'; return; }
  if (!fitMQ.matches) { pre.innerHTML = html.join(''); return; }
  let lo = 0, hi = html.length;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    pre.innerHTML = html.slice(0, mid).join('');
    if (pre.scrollHeight <= pre.clientHeight + 1) lo = mid; else hi = mid - 1;
  }
  pre.innerHTML = html.slice(0, lo).join('');
}
window.addEventListener('resize', showLog);
fitMQ.addEventListener('change', showLog);

function showStats(text) {
  const box = $('stats'); box.textContent = '';
  const found = [...(text || '').matchAll(/(\d+)\s+([A-Za-z]+)/g)];
  if (!found.length) { box.textContent = text ? 'Today: ' + text : 'No activity yet today'; return; }
  const day = document.createElement('span'); day.textContent = 'Today'; box.append(day);
  for (const [, n, what] of found) {
    const s = document.createElement('span'), b = document.createElement('b');
    b.textContent = n; s.append(b, what); box.append(s);
  }
}

async function refresh() {
  try {
    const s = await (await fetch('status')).json();
    const [name, tone] = STATES[s.service] || [s.service || 'Unknown', 'hold'];
    $('svc').textContent = name; $('state').dataset.s = tone;
    showStats(s.stats);
    if (s.w && s.h) { PW = s.w; PH = s.h; document.documentElement.style.setProperty('--ar', (s.w / s.h).toFixed(4)); }
    $('model').textContent = s.phone || '';
    const vid = $('vid');
    if (s.error) { vid.textContent = 'No video: ' + s.error; vid.className = 'late'; }
    else if (s.age !== null && s.age > 10) { vid.textContent = 'Video stalled, last picture ' + Math.round(s.age) + ' s old'; vid.className = 'late'; }
    else { vid.textContent = s.age !== null ? 'Live, ' + Math.round(s.age) + ' s ago' : 'Live'; vid.className = ''; }
    vid.title = s.video ? 'Video mode: ' + s.video : '';
    const note = $('scr_note');
    note.hidden = !s.screen_note; note.textContent = s.screen_note || '';
    note.style.background = s.screen_ok ? '#1d2c31' : ''; note.style.color = s.screen_ok ? 'var(--mist)' : '';
    const running = s.service === 'active';
    $('frame').dataset.ring = (!s.screen_ok || s.error || tone === 'bad') ? 'bad' : running ? 'run' : 'hold';
    if (!built) { buildOptions(s.labels); built = true; }
    for (const k of Object.keys(s.labels)) { const el = $('o_' + k); if (el) el.checked = !!s.control[k]; }
    const tt = $('ttarget');
    if (document.activeElement !== tt) tt.value = s.control.throw_target || 'realistic';
    $('thint').textContent = TARGETS[tt.value] || '';
    showBattle(s);
    const dm = $('dmax'); if (document.activeElement !== dm) dm.value = s.control.daily_max_min || 480;
    const dt = $('dtime'); if (document.activeElement !== dt) dt.value = s.control.daily_time || '08:00';
    setManual(!running);
    lastLog = await (await fetch('log')).text();
    showLog();
  } catch (e) {}
}

async function act(a) {
  if (a === 'stop' && !confirm('Stop the bot?')) return;
  if (a === 'close' && !confirm('Stop the bot and close Pokémon GO completely?')) return;
  await fetch('action/' + a, {method: 'POST'}); setTimeout(refresh, 1500);
}
async function setMax(v) { const n = Math.round(Number(v)); if (n >= 5 && n <= 1440) await fetch('daily_max/' + n, {method: 'POST'}); refresh(); }
async function setTime(t) { if (/^\d\d:\d\d$/.test(t)) await fetch('daily_time/' + t, {method: 'POST'}); refresh(); }
async function setTarget(v) { await fetch('throw_target/' + v, {method: 'POST'}); refresh(); }
function fillApps(apps, cur) {
  const sel = $('bapp');
  if (document.activeElement === sel || !apps.length) return;
  const list = apps.slice();
  if (cur && !list.some(a => a[0] === cur)) list.push([cur, cur + ' (not installed)']);
  const sig = list.map(a => a[0]).join('|');
  if (sel.dataset.sig !== sig) {
    sel.textContent = '';
    for (const [pkg, label] of list) { const o = document.createElement('option'); o.value = pkg; o.textContent = label; sel.append(o); }
    sel.dataset.sig = sig;
  }
  sel.value = cur || list[0][0];
}
function showBattle(s) {
  const c = s.control, on = !!c.battle;
  fillApps(s.apps || [], c.battle_app);
  const bl = $('bleague'); if (document.activeElement !== bl) bl.value = c.battle_league || '';
  const bc = $('bcount'); if (document.activeElement !== bc) bc.value = c.battle_count || 5;
  $('g_battle').classList.toggle('off', !on);
  showRec(s.rec || {}, s.service === 'active');
}
function showRec(r, running) {
  const go = $('recgo'), st = $('recstop'), dl = $('recdl'), h = $('rechint');
  go.hidden = !!r.on; st.hidden = !r.on; dl.hidden = !r.ready;
  let t = '';
  if (r.on) t = 'Recording: ' + r.frames + ' pictures, ' + r.seconds + ' s. Play your battle on the phone, then press Stop.';
  else if (r.ready) t = 'Recording ready: ' + r.frames + ' pictures, ' + r.seconds + ' s, ' + r.mb + ' MB.' + (r.note ? ' ' + r.note : '');
  else if (r.note) t = r.note;
  h.textContent = t; h.hidden = !t;
}
async function setBattle(key, v) {
  await fetch('setting/' + key + '?v=' + encodeURIComponent(v), {method: 'POST'}); refresh();
}
async function recStart() {
  const r = await fetch('record/start', {method: 'POST'});
  if (!r.ok) alert('Stop the bot first, then record.');
  refresh();
}
async function recStop() { $('recstop').disabled = true; await fetch('record/stop', {method: 'POST'}); $('recstop').disabled = false; refresh(); }
async function setOpt(k, on) { await fetch('option/' + k + '/' + (on ? 'on' : 'off'), {method: 'POST'}); refresh(); }

// ---- manual control (only while the bot is stopped) ----
function phonePos(e) {
  const r = img.getBoundingClientRect();
  return [Math.round((e.clientX - r.left) / r.width * PW), Math.round((e.clientY - r.top) / r.height * PH)];
}
img.addEventListener('pointerdown', e => {
  if (!manual) return; e.preventDefault();
  img.setPointerCapture(e.pointerId); down = {p: phonePos(e), t: Date.now()};
});
img.addEventListener('pointerup', e => {
  if (!manual || !down) return; e.preventDefault();
  const p = phonePos(e), ms = Date.now() - down.t, d = Math.hypot(p[0] - down.p[0], p[1] - down.p[1]);
  if (d < 25 && ms < 450) fetch(`input/tap?x=${p[0]}&y=${p[1]}`, {method: 'POST'});
  else fetch(`input/swipe?x1=${down.p[0]}&y1=${down.p[1]}&x2=${p[0]}&y2=${p[1]}&ms=${Math.max(ms, 80)}`, {method: 'POST'});
  down = null;
});
img.addEventListener('contextmenu', e => { if (manual) e.preventDefault(); });
function key(k) { fetch('input/key/' + k, {method: 'POST'}); }
function sendText() { const t = $('txt'); fetch('input/text?t=' + encodeURIComponent(t.value), {method: 'POST'}); t.value = ''; }
function setManual(on) {
  if (on === manual) return;
  manual = on; img.classList.toggle('manual', on); $('manualbar').classList.toggle('on', on); $('manual_note').hidden = !on; showLog();
}
refresh(); setInterval(refresh, 3000);
</script></body></html>"""
PAGE = PAGE.replace("@@NAME@@", APP_NAME)



# ----------------------------- battle recorder -----------------------------
# A tool to teach the bot the screens of a battle. With the bot stopped: press Record, play ONE battle
# on the phone yourself, press Stop and download the zip. It holds small pictures of the screen (one
# whenever the picture changes, at most REC_FPS per second, with the time in the file name), and the
# raw touch events of the phone (getevent), so that every tap can be matched with its picture.
REC_DIR = os.path.expanduser("~/battle_recording")
REC_FPS = 2.0                 # pictures per second at most (a slow phone link gives fewer)
REC_SCALE = 0.35              # size of the saved pictures compared with the screen
REC_QUALITY = 55              # JPEG quality
REC_MAX_FRAMES = 420          # then the recording stops by itself
REC_MAX_MB = 30               # ... or when the pictures together are this big (the zip stays easy to send)
REC_MAX_SECONDS = 600
REC_KEEP_SAME = 4.0           # s: a picture that did not change is still kept now and then
rec = {"on": False, "frames": 0, "t0": 0.0, "secs": 0, "note": "", "zip": None, "mb": 0.0, "bytes": 0,
       "stop": threading.Event(), "thread": None, "touch": None}
rec_lock = threading.Lock()


def rec_status():
    secs = int(time.time() - rec["t0"]) if rec["on"] else rec["secs"]
    return {"on": rec["on"], "frames": rec["frames"], "seconds": secs, "max": REC_MAX_FRAMES,
            "note": rec["note"], "ready": bool(rec["zip"]) and not rec["on"], "mb": rec["mb"]}


def rec_finish(rows):
    """Stop the touch log, write the index and make the zip."""
    proc, rec["touch"] = rec["touch"], None
    if proc:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
    rec["secs"] = int(time.time() - rec["t0"])
    try:
        with open(os.path.join(REC_DIR, "frames.csv"), "w") as f:
            f.write("index,ms,file\n")
            for i, ms, name in rows:
                f.write(f"{i},{ms},{name}\n")
        _, pw, ph = phone()
        with open(os.path.join(REC_DIR, "meta.json"), "w") as f:
            json.dump({"app": APP_NAME, "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(rec["t0"])),
                       "seconds": rec["secs"], "frames": len(rows), "scale": REC_SCALE, "screen_w": pw,
                       "screen_h": ph, "phone": S.screen["model"], "note": rec["note"]}, f, indent=1)
        path = os.path.join(REC_DIR, "recording.zip")
        with zipfile.ZipFile(path, "w") as z:
            for fn in sorted(os.listdir(os.path.join(REC_DIR, "frames"))):
                z.write(os.path.join(REC_DIR, "frames", fn), "frames/" + fn, compress_type=zipfile.ZIP_STORED)
            for fn in ("frames.csv", "meta.json", "touch_devices.txt", "touch_raw.txt"):
                if os.path.exists(os.path.join(REC_DIR, fn)):
                    z.write(os.path.join(REC_DIR, fn), fn, compress_type=zipfile.ZIP_DEFLATED)
        rec["zip"] = path
        rec["mb"] = round(os.path.getsize(path) / 1048576.0, 1)
    except Exception as e:  # noqa: BLE001
        rec["note"] = f"could not make the zip: {e}"
    rec["on"] = False
    write_log(f"battle recording finished: {len(rows)} pictures, {rec['secs']} s, {rec['mb']} MB")


def rec_loop():
    stop = rec["stop"]
    rows, last, last_saved = [], None, 0.0
    try:
        while not stop.is_set():
            if len(rows) >= REC_MAX_FRAMES:
                rec["note"] = f"Stopped by itself: {REC_MAX_FRAMES} pictures is the maximum."
                break
            if rec["bytes"] > REC_MAX_MB * 1048576:
                rec["note"] = f"Stopped by itself: {REC_MAX_MB} MB is the maximum."
                break
            if time.time() - rec["t0"] > REC_MAX_SECONDS:
                rec["note"] = f"Stopped by itself: {REC_MAX_SECONDS // 60} minutes is the maximum."
                break
            if bot_running():
                rec["note"] = "Stopped: the bot was started."
                break
            t_loop = time.time()
            try:
                img = S.screenshot()
            except Exception as e:  # noqa: BLE001
                rec["note"] = f"screenshot failed: {e}"
                stop.wait(1.0)
                continue
            t_cap = time.time()
            h, w = img.shape[:2]
            small = cv2.resize(img, (int(w * REC_SCALE), int(h * REC_SCALE)), interpolation=cv2.INTER_AREA)
            thumb = cv2.resize(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (24, 30),
                               interpolation=cv2.INTER_AREA).astype(np.int16)
            if last is None or float(np.abs(thumb - last).mean()) >= 1.0 or t_cap - last_saved >= REC_KEEP_SAME:
                ms = int((t_cap - rec["t0"]) * 1000)
                name = f"f{len(rows):04d}_{ms:07d}.jpg"
                cv2.imwrite(os.path.join(REC_DIR, "frames", name), small, [cv2.IMWRITE_JPEG_QUALITY, REC_QUALITY])
                rec["bytes"] += os.path.getsize(os.path.join(REC_DIR, "frames", name))
                rows.append((len(rows), ms, name))
                rec["frames"] = len(rows)
                last, last_saved = thumb, t_cap
            stop.wait(max(0.0, 1.0 / REC_FPS - (time.time() - t_loop)))
    except Exception as e:  # noqa: BLE001
        rec["note"] = f"recording stopped: {e}"
    finally:
        rec_finish(rows)


def rec_start():
    """(ok, message). The bot must be stopped: it would press things while you play."""
    with rec_lock:
        if rec["on"]:
            return True, "already recording"
        if bot_running():
            return False, "stop the bot first"
        shutil.rmtree(REC_DIR, ignore_errors=True)         # only the last recording is kept
        os.makedirs(os.path.join(REC_DIR, "frames"))
        phone()
        rec.update(on=True, frames=0, t0=time.time(), secs=0, note="", zip=None, mb=0.0, bytes=0)
        rec["stop"] = threading.Event()
        try:                                                # the raw touches: where and when the screen was touched
            with open(os.path.join(REC_DIR, "touch_devices.txt"), "w") as f:
                f.write(sh("getevent", "-p"))
            rec["touch"] = subprocess.Popen(["adb", "shell", "getevent", "-lt"],
                                            stdout=open(os.path.join(REC_DIR, "touch_raw.txt"), "w"),
                                            stderr=subprocess.DEVNULL)
        except Exception as e:  # noqa: BLE001
            rec["note"] = f"touches are not recorded: {e}"
        write_log("battle recording started")
        rec["thread"] = threading.Thread(target=rec_loop, daemon=True, name="battle-recorder")
        rec["thread"].start()
        return True, "ok"


def rec_stop():
    rec["stop"].set()
    th = rec["thread"]
    if th:
        th.join(timeout=40)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _auth(self):
        pw = password()
        if not pw:
            return True
        expected = "Basic " + base64.b64encode(f"{web_user()}:{pw}".encode()).decode()
        if self.headers.get("Authorization") == expected:
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Pokemon GO Automation"')
        self.end_headers()
        return False

    def _send(self, body, ctype="text/plain; charset=utf-8", code=200):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        last = 0.0
        try:
            while True:
                viewers["last"] = time.time()
                with cond:
                    cond.wait_for(lambda: latest["time"] > last, timeout=5)
                    jpg, last = latest["jpg"], latest["time"]
                if not jpg:
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                 + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if not self._auth():
            return
        path = self.path.split("?")[0]
        if path == "/":
            self._send(PAGE, "text/html; charset=utf-8")
        elif path == "/stream":
            self._stream()
        elif path == "/log":
            self._send("\n".join(reversed(read_log(40))))   # newest line at the top
        elif path == "/status":
            self._send(json.dumps(status()), "application/json")
        elif path == "/record/download":
            if not rec["zip"] or rec["on"] or not os.path.exists(rec["zip"]):
                return self._send("no recording yet", code=404)
            size = os.path.getsize(rec["zip"])
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="battle-recording-'
                             + time.strftime("%Y%m%d-%H%M%S", time.localtime(rec["t0"])) + '.zip"')
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with open(rec["zip"], "rb") as f:
                shutil.copyfileobj(f, self.wfile, 65536)
        else:
            self._send("not found", code=404)

    def do_POST(self):
        if not self._auth():
            return
        path = self.path.split("?")[0]
        m = re.fullmatch(r"/action/(start|stop|restart)", path)
        if m:
            bot_action(m.group(1))
            return self._send("ok")
        if path == "/action/close":
            threading.Thread(target=close_game, daemon=True).start()
            return self._send("ok")
        if path.startswith("/input/"):
            # manual control: only while the bot is stopped, so you never fight the bot
            if bot_running():
                return self._send("stop the bot first", code=409)
            q = dict(kv.split("=", 1) for kv in self.path.partition("?")[2].split("&") if "=" in kv)
            _, PHONE_W, PHONE_H = phone()
            num = lambda k, hi: max(0, min(hi, int(float(q.get(k, 0)))))
            if path == "/input/tap":
                adb_input("tap", num("x", PHONE_W), num("y", PHONE_H))
            elif path == "/input/swipe":
                adb_input("swipe", num("x1", PHONE_W), num("y1", PHONE_H), num("x2", PHONE_W),
                          num("y2", PHONE_H), max(40, min(5000, int(float(q.get("ms", 300))))))
            elif path in ("/input/key/back", "/input/key/home", "/input/key/apps"):
                key = {"back": "KEYCODE_BACK", "home": "KEYCODE_HOME", "apps": "KEYCODE_APP_SWITCH"}[path.rsplit("/", 1)[1]]
                adb_input("keyevent", key)
            elif path == "/input/text":
                txt = re.sub(r"[^A-Za-z0-9]", "", q.get("t", ""))[:60]   # simple text only
                if txt:
                    adb_input("text", txt)
            else:
                return self._send("not found", code=404)
            return self._send("ok")
        if path == "/record/start":
            ok, msg = rec_start()
            return self._send(msg, code=200 if ok else 409)
        if path == "/record/stop":
            rec_stop()
            return self._send("ok")
        m = re.fullmatch(r"/setting/(battle_app|battle_league|battle_count)", path)
        if m:
            key = m.group(1)
            v = urllib.parse.parse_qs(self.path.partition("?")[2]).get("v", [""])[0]
            if key == "battle_app":
                if v not in [p for p, _ in game_apps()]:
                    return self._send("that app is not installed", code=400)
            elif key == "battle_league":
                v = re.sub(r"[^\w .:'&+-]", "", v).strip()[:40]
                if not v:
                    return self._send("empty", code=400)
            else:
                if not v.isdigit() or not 1 <= int(v) <= 50:
                    return self._send("1 to 50", code=400)
                v = int(v)
            c = read_control()
            c[key] = v
            write_control(c)
            return self._send("ok")
        m = re.fullmatch(r"/daily_max/(\d{1,4})", path)
        if m and 5 <= int(m.group(1)) <= 1440:
            c = read_control()
            c["daily_max_min"] = int(m.group(1))
            write_control(c)
            return self._send("ok")
        m = re.fullmatch(r"/daily_time/([01]\d|2[0-3]):([0-5]\d)", path)
        if m:
            c = read_control()
            c["daily_time"] = f"{m.group(1)}:{m.group(2)}"
            write_control(c)
            return self._send("ok")
        m = re.fullmatch(r"/throw_target/(\w+)", path)
        if m and m.group(1) in THROW_TARGETS:
            c = read_control()
            c["throw_target"] = m.group(1)
            write_control(c)
            return self._send("ok")
        m = re.fullmatch(r"/option/(\w+)/(on|off)", path)
        if m and m.group(1) in OPTIONS:
            c = read_control()
            c[m.group(1)] = m.group(2) == "on"
            write_control(c)
            return self._send("ok")
        self._send("not found", code=404)


if __name__ == "__main__":
    read_control()                              # applies the standard profile once
    threading.Thread(target=video_loop, daemon=True).start()
    if not password():
        print(f"WARNING: no password set ({PASSWORD_FILE}) - anyone on your network can watch")
    print(f"{APP_NAME} web on http://0.0.0.0:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
