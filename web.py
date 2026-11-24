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
import sys
import io
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

import chapters as CH        # the test chapters (Test): what they are; gamebot.py runs them
import bag_rules             # what the bag clean-up keeps
import claude_chat           # Claude in the chat on the right side of the page
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
VIDEO_FPS = 12
VIDEO_WIDTH = 480                           # width of the frames sent to the browser
VIDEO_BITRATE = "2000000"
OPTIONS = {                                 # key -> label (default: on)
    "daily_cycle": "Daily run: both Pokémon GO apps one after another until full",
    "battle": "Battles: in the daily run the chosen app fights GO Battle League battles first",
    "battle_give_up": "Battles: give up a battle that is lost (our last Pokémon cannot win any more)",
    "catch": "Catch wild Pokémon",
    "spin": "Spin PokéStops",
    "gifts_open": "Open gifts from friends",
    "gifts_send": "Send gifts to friends",
    "curveball": "Always throw a curveball",
    "fast_catch": "Fast catch: after a clear hit press BACK to skip the catch animation (the result is checked on the map)",
    "spin_only_when_full": "Spin PokéStops when Pokémon storage is full (catching pauses until there is room again)",
    "close_when_full": "Close the game when Pokémon storage and bag are both full",
    "rocket_fight": "Team GO Rocket at a PokéStop: battle it with the recommended party (a missing third one is chosen)",
    "quests": "Quests: when the quest button is gold, claim the GO Pass rewards (VIEW REWARDS, CLAIM ALL)",
    "bag_clean": "Bag full: discard and keep what 'What the bag keeps' says",
    "buddy": "My buddy walks along on the map (a Pokémon next to the trainer may be the buddy)",
    "fast_look": "Realistic look around",
    "live_look": "Look with the live video of the phone (a picture in a tenth of a second instead of 1-3 s)",
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
                ["ffmpeg", "-loglevel", "error", "-threads", "1", "-flags", "low_delay",   # (no pictures held back)
                 "-probesize", "32768", "-analyzeduration", "0",
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


def clear_log():
    """'Delete log and pictures': the log starts again and the pictures of the bot in ~/debug are deleted.
    The day counters of the bot (caught, fled, stops) go into the first line of the new log, so that a restart
    still goes on from them; the battles won and lost of today start again at nothing. Returns (lines, pictures)."""
    today, keep, n_lines = time.strftime("%Y-%m-%d"), "", 0
    try:
        with open(LOGFILE, "rb") as f:
            data = f.read().decode(errors="ignore")
        n_lines = data.count("\n")
        for line in reversed(today_lines(today)):
            m = re.search(r"\(today: ([^)]*caught[^)]*)\)", line)
            if m:
                keep = re.sub(r",\s*\d+ won, \d+ lost", "", m.group(1))
                break
        os.truncate(LOGFILE, 0)            # (in place: the bot keeps writing to the same file)
    except OSError:
        pass
    pictures = 0
    try:
        for n in os.listdir(DEBUG_DIR):
            if n.lower().endswith((".png", ".jpg")):
                try:
                    os.remove(os.path.join(DEBUG_DIR, n))
                    pictures += 1
                except OSError:
                    pass
    except OSError:
        pass
    _today["key"] = None
    write_log(f"log and {pictures} pictures deleted in the web interface" + (f" (today: {keep})" if keep else ""))
    return n_lines, pictures


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


DEBUG_DIR = os.path.expanduser("~/debug")
DEBUG_LOG_BYTES = 600000       # the end of the log that goes into the debug download ...
DEBUG_PICTURES = 30            # ... with this many of the newest pictures the bot saved ...
DEBUG_HOURS = 6                # ... when they are not older than this
DEBUG_FILES = ("battle_minigame.json", "battle_team.json", "battle_seen.json")   # ... and these files of the home folder


def debug_zip(now=None):
    """A zip for whoever helps with a problem: the end of the log and the newest pictures the bot saved in
    ~/debug (as JPEG: the PNGs are 2 MB each, thirty of them would not fit in a message).  Nothing with a
    password in it.  Returns the bytes of the zip."""
    now = now or time.time()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        try:
            with open(LOGFILE, "rb") as f:
                f.seek(0, 2)
                f.seek(max(f.tell() - DEBUG_LOG_BYTES, 0))
                z.writestr("spin_tail.log", f.read().decode(errors="ignore"))
        except OSError as e:
            z.writestr("spin_tail.log", f"(the log could not be read: {e})")
        index = []
        try:
            names = [n for n in os.listdir(DEBUG_DIR) if n.lower().endswith((".png", ".jpg"))]
        except OSError:
            names = []
        files = sorted(((os.path.getmtime(os.path.join(DEBUG_DIR, n)), n) for n in names), reverse=True)
        for mtime, n in files[:DEBUG_PICTURES]:
            if now - mtime > DEBUG_HOURS * 3600:
                break
            path = os.path.join(DEBUG_DIR, n)
            try:
                if n.lower().endswith(".png"):
                    ok, jpg = cv2.imencode(".jpg", cv2.imread(path), [cv2.IMWRITE_JPEG_QUALITY, 82])
                    data, n = jpg.tobytes(), n[:-4] + ".jpg"
                else:
                    with open(path, "rb") as f:
                        data = f.read()
                z.writestr(zipfile.ZipInfo("debug/" + n, time.localtime(mtime)[:6]), data, zipfile.ZIP_STORED)
                index.append(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))}  {n}")
            except Exception as e:  # noqa: BLE001
                index.append(f"(not added: {n}: {e})")
        z.writestr("pictures.txt", "\n".join(index) or "(no pictures of the last hours)")
        for n in DEBUG_FILES:
            path = os.path.expanduser("~/" + n)
            if os.path.exists(path):
                z.write(path, n)
    return buf.getvalue()


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


TODAY_LOG_BYTES = 8000000      # at most this much of the end of the log is read for the counters of today
_today = {"key": None, "stats": "", "battles": []}
BATTLES_RESET_FILE = os.path.expanduser("~/battle_count_reset.json")   # 'Reset' under Battles today: from when on


def battles_reset_at():
    """The time of the last 'Reset' of the battles won and lost ('YYYY-MM-DD HH:MM:SS'), or ''."""
    try:
        with open(BATTLES_RESET_FILE) as f:
            return str(json.load(f).get("at", ""))
    except (OSError, ValueError, AttributeError):
        return ""


def reset_battles():
    """Count the battles won and lost from now on (the log itself is not touched)."""
    with open(BATTLES_RESET_FILE, "w") as f:
        json.dump({"at": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
    _today["key"] = None


def today_lines(day=None):
    """The lines of the log of today (day: 'YYYY-MM-DD'), oldest first."""
    day = day or time.strftime("%Y-%m-%d")
    try:
        with open(LOGFILE, "rb") as f:
            f.seek(0, 2)
            f.seek(max(f.tell() - TODAY_LOG_BYTES, 0))
            lines = f.read().decode(errors="ignore").splitlines()
    except OSError:
        return []
    for i in range(len(lines) - 1, -1, -1):          # back to the first line of an older day
        if lines[i][:4].isdigit() and not lines[i].startswith(day):
            return lines[i + 1:]
    return lines


BATTLE_DONE = re.compile(r"battle: battle \d+ done: (win|loss)( \(given up\))?")


def battles_of(lines):
    """The GO Battle League matches in these log lines: [{time, league, result, gave_up, foes}], oldest first.
    A match ends with 'battle: battle N done: win/loss'; the foes are the 'fight: foe is ...' lines before it."""
    out, foes, league = [], [], ""
    for line in lines:
        m = re.search(r"battle: \d+ battle\(s\) in '([^']*)'", line)
        if m:
            league = m.group(1)
        if "USE THIS PARTY" in line or "a fight is on the screen" in line:
            foes = []
        m = re.search(r"fight: foe is (.+?)(?: \(CP \d+\))?(?: - moves |$)", line)
        if m:
            name = m.group(1).strip()
            if name and name not in foes:
                foes.append(name)
        m = BATTLE_DONE.search(line)
        if m:
            t = re.search(r"\b(\d\d:\d\d)(:\d\d)?\b", line)
            out.append({"at": line[:19], "time": t.group(1) if t else "", "league": league, "result": m.group(1),
                        "gave_up": bool(m.group(2)), "foes": foes[:3]})
            foes = []
    return out


def stats_of(lines, since=""):
    """The day counters: the last '(today: ... caught ...)' line of the bot, with the battles won and lost
    counted from the matches themselves (so the ones of before the counter came are in it too) - those two
    always, 0 and 0 when there was no battle (yet, or since 'Reset')."""
    stats = ""
    for line in reversed(lines):
        m = re.search(r"\(today: ([^)]*caught[^)]*)\)", line)
        if m:
            stats = re.sub(r",\s*\d+ won, \d+ lost", "", m.group(1))
            break
    games = [g for g in battles_of(lines) if not since or g["at"] > since]
    won = sum(g["result"] == "win" for g in games)      # (always there, also 0 and 0 after a reset)
    stats = (stats + ", " if stats else "") + f"{won} won, {len(games) - won} lost"
    return stats, games


def today_stats():
    """(stats, battles) of today, read again only when the log changed."""
    try:
        st = os.stat(LOGFILE)
        key = (time.strftime("%Y-%m-%d"), st.st_size, st.st_mtime, battles_reset_at())
    except OSError:
        return "", []
    if _today["key"] != key:
        _today["stats"], _today["battles"] = stats_of(today_lines(key[0]), key[3])
        _today["key"] = key
    return _today["stats"], _today["battles"]


def status():
    active = subprocess.run(["systemctl", "is-active", SERVICE], capture_output=True).stdout.decode().strip()
    stats, battles = today_stats()
    _, pw, ph = phone()
    return {"service": active, "stats": stats, "battles": battles, "test": test_status(), "control": read_control(), "labels": OPTIONS, "apps": game_apps(), "rec": rec_status(),
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
 .stats .grp { display:flex; flex-wrap:wrap; align-items:center; gap:2px 18px; }
 .stats .grp + .grp { padding-left:18px; border-left:1px solid var(--ridge); }
 .stats .btn.small { height:26px; }
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
 .frame { position:relative; }
 .touch { position:absolute; width:34px; height:34px; margin:-17px 0 0 -17px; border-radius:50%; pointer-events:none;
  border:2px solid var(--blue); background:color-mix(in srgb, var(--blue) 30%, transparent); animation:touch .6s ease-out forwards; }
 .touch.line { width:auto; height:0; margin:0; border:0; border-top:3px solid var(--blue); border-radius:2px; background:none; transform-origin:0 0; }
 @keyframes touch { from { opacity:1; transform:scale(.6); } to { opacity:0; transform:scale(1.6); } }
 .touch.line { animation:fade .7s ease-out forwards; }
 @keyframes fade { from { opacity:1; } to { opacity:0; } }
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
 /* the option groups as tabs: one group at a time, so the page fits on one screen */
 .tabs { display:flex; flex-wrap:wrap; gap:2px 4px; margin:0 0 8px; border-bottom:1px solid var(--ridge); }
 .tabs button { padding:6px 10px 7px; border:0; border-bottom:2px solid transparent; margin-bottom:-1px; background:transparent;
  color:var(--mist); font-size:13px; font-weight:600; cursor:pointer; }
 .tabs button:hover { color:var(--chalk); }
 .tabs button[aria-selected="true"] { color:var(--chalk); border-bottom-color:var(--blue); }
 .groups.tabbed { display:block; }
 .groups.tabbed .col { display:contents; }
 .groups.tabbed .group { display:none; padding:0; }
 .groups.tabbed .group.on { display:grid; grid-template-columns:repeat(auto-fill, minmax(230px, 1fr)); gap:0 28px; align-items:start; }
 .groups.tabbed .group h2 { display:none; }
 .groups.tabbed .group.on .switches { display:contents; }
 .groups.tabbed .row .h { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
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
 .runfor { display:flex; align-items:center; gap:8px; margin-left:auto; color:var(--mist); font-size:13px; white-space:nowrap; }
 .inp { height:32px; padding:0 9px; border-radius:8px; border:1px solid var(--ridge); background:var(--dusk); }
 input[type=number].inp { width:96px; }       /* (room for 4 digits next to the arrows of a selected field) */
 input[type=text].inp { width:172px; max-width:100%; }
 a.btn { display:inline-flex; align-items:center; text-decoration:none; color:inherit; }
 .recbtns { display:flex; gap:8px; margin-left:auto; }
 .rechint { margin-top:6px; color:var(--mist); font-size:13px; }
 .recbtns .btn[disabled] { opacity:.45; cursor:default; }
 .group.off .field { display:none; }
 .bagkeep { grid-column:1 / -1; margin:6px 0 2px; font-size:13px; }
 .bagkeep summary { cursor:pointer; color:var(--blue); font-weight:600; padding:4px 0; }
 .bagkeep .h { margin:4px 0 8px; }
 .bagitems { display:grid; grid-template-columns:repeat(auto-fill, minmax(190px, 1fr)); gap:4px 22px; margin-bottom:8px; }
 .bagitems label { display:flex; align-items:center; justify-content:space-between; gap:8px; }
 .bagitems input { width:88px; }
 #bapp { max-width:210px; }
 input[type=time].inp { width:116px; }
 select.inp { max-width:100%; }
 .unit { color:var(--mist); }
 .field label { cursor:default; }

 /* ---------- log ---------- */
 .games h2 { margin:0 0 6px; font-size:13px; font-weight:650; color:var(--mist); }
 .games h2 b { color:var(--chalk); font-weight:650; }
 .games ol { list-style:none; margin:0; padding:0; max-height:220px; overflow:auto; }
 .games li { display:grid; grid-template-columns:44px 70px minmax(0,1fr); gap:10px; padding:4px 0; border-top:1px solid color-mix(in srgb, var(--ridge) 55%, transparent); font-size:13px; }
 .games li:first-child { border-top:0; }
 .games .t { color:var(--mist); font-variant-numeric:tabular-nums; }
 .games .r { font-weight:650; }
 .games .win .r { color:var(--run); } .games .loss .r { color:var(--stop); }
 .games .f { color:var(--mist); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
 .tests summary { display:flex; flex-wrap:wrap; align-items:baseline; gap:4px 12px; cursor:pointer; list-style:none; }
 .tests summary::-webkit-details-marker { display:none; }
 .tests summary h2 { margin:0; font-size:13px; font-weight:650; color:var(--chalk); }
 .tests summary h2::before { content:"\25B8"; display:inline-block; width:14px; color:var(--mist); transition:transform .15s; }
 .tests details[open] summary h2::before { transform:rotate(90deg); }
 .tests summary span { color:var(--mist); font-size:12.5px; }
 .testnow { display:flex; flex-wrap:wrap; align-items:center; gap:8px 12px; margin:10px 0 2px; padding:8px 12px; border-radius:9px; background:var(--dusk); font-size:13px; }
 .testnow #testline { margin-right:auto; }
 .testnow .ok { color:var(--run); font-weight:650; } .testnow .bad { color:var(--stop); font-weight:650; } .testnow .busy { color:var(--hold); font-weight:650; }
 .testrec { display:flex; align-items:center; gap:8px; margin:10px 0 4px; color:var(--mist); font-size:12.5px; cursor:pointer; }
 .chapters { display:grid; grid-template-columns:repeat(auto-fill, minmax(260px, 1fr)); gap:4px 22px; }
 .chapters h3 { grid-column:1 / -1; margin:10px 0 0; font-size:12px; font-weight:650; color:var(--mist); }
 .chap { display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:center; gap:2px 10px; padding:6px 0; border-top:1px solid color-mix(in srgb, var(--ridge) 55%, transparent); }
 .chap b { font-weight:600; font-size:13.5px; }
 .chap small { grid-column:1; color:var(--mist); font-size:12px; }
 .chap .btn { grid-row:1 / span 2; grid-column:2; }
 .chap .btn[disabled] { opacity:.45; cursor:default; }
 .tests .hint { margin:10px 0 0; color:var(--mist); font-size:12px; }
 .logsec { display:flex; flex-direction:column; }
 .loghead { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:baseline; gap:6px 8px; margin-bottom:6px; }
 .loghead h2 { margin:0; font-size:13px; font-weight:650; color:var(--mist); }
 .loghead span { color:var(--mist); font-size:12px; margin-right:auto; margin-left:10px; }
 .btn.small { height:28px; padding:0 10px; font-size:12px; font-weight:600; }
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
 @media (min-width:1000px) and (min-height:600px) {
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
  .stats .grp + .grp { padding-left:0; border-left:0; }
 }
 /* ---------- Claude: always on the right side ---------- */
 :root { --chatw:min(400px, 100vw); }
 @media (min-width:1000px) { :root { --chatw:clamp(320px, 26vw, 400px); } }
 .chat { position:fixed; top:0; right:0; bottom:0; width:var(--chatw); z-index:30; display:flex; flex-direction:column;
  background:var(--dusk); border-left:1px solid var(--ridge); transform:translateX(100%); transition:transform .2s; }
 .chat.open { transform:none; box-shadow:-12px 0 32px #0008; }
 .chathead { display:flex; align-items:center; gap:8px; padding:12px 14px; border-bottom:1px solid var(--ridge); }
 .chathead .btn { white-space:nowrap; }
 .chathead h2 { margin:0; font-size:16px; font-weight:650; }
 .chatwho { color:var(--mist); font-size:12px; margin-right:auto; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
 .chatwhere { display:block; width:100%; text-align:left; padding:7px 14px; border:0; border-bottom:1px solid var(--ridge); background:transparent; color:var(--mist); font-size:12.5px; cursor:pointer; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
 .chatwhere b { color:var(--chalk); font-weight:600; }
 .chatwhere:hover { background:var(--night); }
 .chatlist { padding:10px 14px; border-bottom:1px solid var(--ridge); max-height:55vh; overflow-y:auto; font-size:13px; }
 .chatlist .bar { align-items:center; }
 .chatlist select { flex:1; min-width:0; height:30px; padding:0 8px; border-radius:8px; border:1px solid var(--ridge); background:var(--night); }
 .sr { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); }
 .projedit { display:grid; gap:8px; margin:10px 0; padding:10px; border:1px solid var(--ridge); border-radius:10px; }
 .projedit label { display:grid; gap:3px; color:var(--mist); font-size:12.5px; }
 .projedit input, .projedit textarea { padding:7px 10px; border-radius:8px; border:1px solid var(--ridge); background:var(--night); font:inherit; color:inherit; resize:vertical; }
 #chatitems { list-style:none; margin:10px 0 0; padding:0; }
 #chatitems li { display:flex; align-items:center; gap:6px; border-top:1px solid color-mix(in srgb, var(--ridge) 55%, transparent); }
 #chatitems li:first-child { border-top:0; }
 #chatitems button.open { flex:1; min-width:0; text-align:left; padding:7px 4px; border:0; background:transparent; cursor:pointer; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
 #chatitems button.open small { color:var(--mist); margin-left:6px; }
 #chatitems li.on button.open { color:var(--blue); font-weight:600; }
 #chatitems button.del { border:0; background:transparent; color:var(--mist); cursor:pointer; padding:4px 6px; border-radius:6px; }
 #chatitems button.del:hover { color:var(--stop); background:var(--night); }
 .chatset { max-height:65vh; overflow-y:auto; padding:12px 14px; border-bottom:1px solid var(--ridge); display:grid; gap:8px; font-size:13px; }
 .chatset label { display:grid; gap:3px; color:var(--mist); }
 .chatset input, .chatset select { height:34px; padding:0 10px; border-radius:8px; border:1px solid var(--ridge); background:var(--night); }
 .chatset p { margin:0; color:var(--mist); font-size:12px; }
 .chatset .bar { align-items:center; } #set_msg { color:var(--mist); font-size:12.5px; }
 .chatlog { flex:1; min-height:0; overflow-y:auto; padding:14px; display:flex; flex-direction:column; gap:10px; }
 .msg { max-width:92%; font-size:13.5px; line-height:1.5; overflow-wrap:anywhere; }
 .msg.user { align-self:flex-end; background:var(--ridge); padding:8px 12px; border-radius:14px 14px 4px 14px; white-space:pre-wrap; }
 .msg.assistant { align-self:flex-start; }
 .msg.tell { align-self:center; color:var(--mist); font-size:12px; text-align:center; }
 .msg.tell a { color:var(--blue); }
 .msg pre { background:var(--night); padding:8px 10px; border-radius:8px; overflow-x:auto; font-size:12px; white-space:pre; }
 .msg code { background:var(--night); padding:1px 4px; border-radius:4px; font-size:12px; }
 .msg pre code { padding:0; background:none; }
 .msg a { color:var(--blue); }
 .chatempty { color:var(--mist); font-size:13px; margin:auto 0; text-align:center; }
 .chatbusy { display:flex; align-items:center; gap:8px; padding:6px 14px; color:var(--hold); font-size:12.5px; }
 .chatbusy .dot { width:8px; height:8px; border-radius:50%; background:var(--hold); animation:pulse 1.2s ease-in-out infinite; }
 .chatbusy .btn { margin-left:auto; }
 @keyframes pulse { 50% { opacity:.25; } }
 .chatin { display:flex; gap:8px; padding:10px 14px 14px; border-top:1px solid var(--ridge); }
 .chatin textarea { flex:1; resize:none; min-height:44px; max-height:160px; padding:9px 11px; border-radius:10px; border:1px solid var(--ridge); background:var(--night); font:inherit; color:inherit; }
 .chatin .btn { align-self:flex-end; height:44px; }
 .chatopen { position:fixed; right:16px; bottom:16px; z-index:25; background:var(--blue); color:#06202e; border-color:var(--blue); box-shadow:0 6px 20px #0007; }
 @media (min-width:1000px) {
  body { padding-right:var(--chatw); }
  .chat { transform:none; }
  .chatopen, .chatclose { display:none; }
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
    <label class="runfor" for="dmax" title="How long a run may take, all games together. Then a fight that is going on is finished, nothing new starts, the game is closed and the bot waits for the next daily start.">Stop after
     <input type="number" id="dmax" class="inp" min="5" max="1440" step="5" onchange="setMax(this.value)"> min</label>
   </div>
   <details class="help"><summary>What do these buttons do?</summary>
    <p>Start and Restart begin a new daily run right away. Stop pauses the bot so you can take over, for example for quests; stop it too before you open Pokémon GO on another device. Close game stops the bot and closes Pokémon GO on the phone; Start plays again. <b>Stop after ... min</b> is how long a run may take, all games together, counted from Start or the daily start: when the time is up, a battle that is being fought and a Pokémon that is being caught are finished, no new battle starts, the game is closed and the bot waits for the next daily start.</p>
   </details>
  </section>

  <section class="sec tests" aria-label="Test">
   <details id="testbox"><summary><h2>Test one part</h2><span id="testsum">Run one part of the bot on its own, from the screen the game is on now.</span></summary>
    <div class="testnow" id="testnow" hidden>
     <span id="testline"></span>
     <button class="btn small danger" id="teststop" onclick="testStop()">Stop test</button>
     <a class="btn small" id="testdl" href="test/download" hidden>Download test</a>
    </div>
    <label class="testrec"><input type="checkbox" id="testrec"> Record the screen during the test (the recording goes into the test zip)</label>
    <div class="chapters" id="chapters"></div>
    <p class="hint">Starting a test stops the bot. Put the game on the start screen first. Afterwards press Start to play normally again.</p>
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
     <button class="btn" id="recgo" onclick="recStart()" title="Records the screen during one battle - one you play yourself, or one the bot fights (gamebot.py fight). The zip holds the pictures, the touches and what the bot logged meanwhile.">Record battle</button>
     <button class="btn danger" id="recstop" onclick="recStop()" hidden>Stop</button>
     <a class="btn" id="recdl" href="record/download" hidden>Download</a>
    </span>
   </div>
   <div class="rechint" id="rechint" hidden></div>
  </section>

  <section class="sec" aria-label="Options">
   <div class="tabs" id="tabs" role="tablist" aria-label="Option groups"></div>
   <div class="groups tabbed" id="groups">
    <div class="col">
     <div class="group" data-keys="daily_cycle">
      <h2>Daily run</h2>
      <div class="switches"></div>
      <div class="row field"><label class="txt" for="dtime"><span class="t">Starts every day at</span></label>
       <input type="time" id="dtime" class="inp" onchange="setTime(this.value)"></div>
     </div>
     <div class="group" id="g_battle" data-keys="battle battle_give_up">
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
     <div class="group" data-keys="spin spin_only_when_full close_when_full bag_clean rocket_fight quests">
      <h2>PokéStops and storage</h2>
      <div class="switches"></div>
      <details class="bagkeep" id="bagkeep"><summary>What the bag keeps when it is cleaned up</summary>
       <p class="h">How many of each item stay in the bag; the rest is discarded. 0 discards all of it, an empty field leaves the item alone. Items that are not on this list are never touched.</p>
       <div class="bagitems" id="bagitems"></div>
       <div class="bar"><button class="btn small" type="button" onclick="bagDefaults()">Standard numbers</button><span class="h" id="bagmsg"></span></div>
      </details>
     </div>
     <div class="group" data-keys="catch curveball fast_catch fast_look live_look buddy">
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

  <section class="sec games" id="games" aria-label="Battles today" hidden>
   <h2 id="gamesum">Battles today</h2>
   <ol id="gamelist"></ol>
  </section>

  <section class="sec logsec" aria-label="Log">
   <div class="loghead"><h2>Log</h2><span>Newest first</span>
    <a class="btn small" href="debug/download" title="A zip with the end of the log and the newest pictures the bot saved: send it along when you ask for help.">Download log and pictures</a>
    <button class="btn small danger" onclick="clearLog()" title="Empties the log and deletes the pictures the bot saved. Download them first if you still need them.">Delete log and pictures</button></div>
   <pre id="log">Loading…</pre>
  </section>
 </div>
</main>
<aside class="chat" id="chat" aria-label="Chat with Claude">
 <div class="chathead">
  <h2>Claude</h2><span class="chatwho" id="chatwho"></span>
  <button class="btn small" id="chatsbtn" onclick="chatList()" title="The chats and projects" aria-expanded="false">Chats</button>
  <button class="btn small" onclick="chatNew()" title="Start a new chat in this project">New chat</button>
  <button class="btn small" id="chatgear" onclick="chatSettings()" title="API key, GitHub and model" aria-expanded="false">Settings</button>
  <button class="btn small chatclose" onclick="chatToggle(false)" aria-label="Close the chat">Close</button>
 </div>
 <button class="chatwhere" id="chatwhere" onclick="chatList()" title="Show the chats of this project"></button>
 <div class="chatlist" id="chatlist" hidden>
  <div class="bar"><label class="sr" for="projsel">Project</label><select id="projsel" onchange="projOpen(this.value)"></select>
   <button class="btn small" onclick="projEdit(true)">Edit project</button>
   <button class="btn small" onclick="projEdit(false)">New project</button></div>
  <form class="projedit" id="projedit" hidden onsubmit="projSave(event)">
   <label>Name <input id="proj_name" maxlength="60" required></label>
   <label>Instructions for Claude in this project <textarea id="proj_ins" rows="3" placeholder="For example: always answer in Dutch; focus on the battles."></textarea></label>
   <label>Project knowledge <textarea id="proj_notes" rows="4" placeholder="Notes every chat of this project gets. Claude adds what it finds worth keeping."></textarea></label>
   <div class="bar"><button class="btn primary small" type="submit">Save project</button>
    <button class="btn small" type="button" onclick="$('projedit').hidden = true">Cancel</button>
    <button class="btn small danger" type="button" id="projdel" onclick="projDelete()">Delete project</button></div>
  </form>
  <ul id="chatitems"></ul>
 </div>
 <form class="chatset" id="chatset" hidden onsubmit="chatSave(event)">
  <label>Claude API key <input type="password" id="set_key" autocomplete="off" placeholder="not set"></label>
  <label>GitHub token, for pull requests <input type="password" id="set_gh" autocomplete="off" placeholder="not set"></label>
  <label>Model <select id="set_model"></select></label>
  <label>Effort <select id="set_effort"></select></label>
  <p>Effort is how much Claude thinks and checks before it answers: low is fast and cheap, high and above are more thorough and cost more. Model default: medium on Opus and Haiku, high on Sonnet.</p>
  <p>The keys stay on the Pi and are never shown again. Type <b>-</b> in a field to remove that key. Claude sees the log, the phone screen and the code when it needs them; that goes to Anthropic. Changes to the code are only ever proposed as a pull request at <span id="set_maker"></span>, made with your GitHub account.</p>
  <div class="bar"><button class="btn primary" type="submit">Save</button><span id="set_msg"></span></div>
 </form>
 <div class="chatlog" id="chatlog" aria-live="polite"></div>
 <div class="chatbusy" id="chatbusy" hidden><span class="dot"></span><span id="chatprog">Thinking</span>
  <button class="btn small" onclick="chatStop()">Stop</button></div>
 <form class="chatin" onsubmit="chatSend(event)">
  <textarea id="chattext" rows="2" placeholder="Ask Claude about the bot" aria-label="Message to Claude"></textarea>
  <button class="btn primary" type="submit" id="chatgo">Send</button>
 </form>
</aside>
<button class="btn chatopen" id="chatopen" onclick="chatToggle(true)">Claude</button>
<script>
const $ = id => document.getElementById(id);
const img = $('scr');
img.onerror = () => setTimeout(() => { img.src = 'stream?t=' + Date.now(); }, 3000);

// Plain wording for each option: [title, extra line]. An option that is not listed shows the text from the server.
const WORDS = {
  daily_cycle: ['Play both Pokémon GO apps', 'One after the other, each until it is full - or until the run time next to Start is up.'],
  battle: ['Fight battles first', 'Daily run only. The chosen app fights its GO Battle League battles, then spins and catches.'],
  battle_give_up: ['Give up a lost battle', 'When the last Pokémon cannot win any more, leave the battle instead of playing it out.'],
  catch: ['Catch wild Pokémon'],
  curveball: ['Always throw a curveball'],
  fast_catch: ['Fast catch', 'After a clear hit, press Back to skip the catch animation. The result is checked on the map.'],
  fast_look: ['Look around like a person'],
  live_look: ['Look with the live video', 'The map, the ring and the ball are looked at in the live video of the phone: a picture in a tenth of a second instead of 1 to 3 s. Text is still read on sharp screenshots.'],
  buddy: ['My buddy walks along on the map', 'A Pokémon next to the trainer may be the buddy.'],
  spin: ['Spin PokéStops'],
  rocket_fight: ['Battle Team GO Rocket', 'A grunt or leader at a PokéStop is battled with the recommended party; a missing third Pokémon is chosen. The Shadow Pokémon is caught afterwards.'],
  quests: ['Claim GO Pass rewards', 'When the quest button on the map is gold: GO Pass, View rewards, Claim all. A Pokémon as a reward is caught.'],
  bag_clean: ['Clean up a full bag', 'Discards Potion, Super and Hyper Potion; keeps 30 Max Potion, 30 Max Revive, 400 Poké Ball, 100 Great Ball and 30 of each berry. Nothing else is touched.'],
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
  if (hint) { const h = document.createElement('span'); h.className = 'h'; h.textContent = hint; txt.append(h); row.title = hint; }
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
  buildTabs();
}
function buildTabs() {                                // one tab per group; the chosen one is remembered in this browser
  const bar = $('tabs'), groups = [...document.querySelectorAll('#groups .group')].filter(g => !g.hidden);
  let want = '';
  try { want = localStorage.getItem('optTab') || ''; } catch (e) {}
  bar.textContent = '';
  groups.forEach((g, i) => {
    const name = g.querySelector('h2').textContent;
    g.id = g.id || 'grp' + i; g.setAttribute('role', 'tabpanel');
    const b = document.createElement('button'); b.type = 'button'; b.textContent = name;
    b.setAttribute('role', 'tab'); b.setAttribute('aria-controls', g.id); b.dataset.name = name;
    b.onclick = () => showTab(name);
    bar.append(b);
  });
  showTab(groups.some(g => g.querySelector('h2').textContent === want) ? want : groups.length ? groups[0].querySelector('h2').textContent : '');
}
function showTab(name) {
  for (const g of document.querySelectorAll('#groups .group')) g.classList.toggle('on', g.querySelector('h2').textContent === name);
  for (const b of $('tabs').children) b.setAttribute('aria-selected', String(b.dataset.name === name));
  try { localStorage.setItem('optTab', name); } catch (e) {}
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
  const group = () => { const g = document.createElement('span'); g.className = 'grp'; box.append(g); return g; };
  const play = group(), fights = [];                   // catching and stops apart from the battles won and lost
  for (const [, n, what] of found) {
    const s = document.createElement('span'), b = document.createElement('b');
    b.textContent = n; s.append(b, what);
    if (what === 'won' || what === 'lost') fights.push(s); else play.append(s);
  }
  if (!play.childElementCount) play.remove();
  if (fights.length) {
    const g = group(), reset = document.createElement('button');
    reset.className = 'btn small'; reset.textContent = 'Reset'; reset.onclick = resetGames;
    reset.title = 'Counts the battles won and lost from now on. The log itself stays as it is.';
    g.append(...fights, reset);
  }
}

function showGames(list) {                            // the GO Battle League matches of today, newest first
  const sec = $('games'), ol = $('gamelist');
  list = list || [];
  sec.hidden = !list.length;
  if (!list.length) return;
  const won = list.filter(g => g.result === 'win').length;
  $('gamesum').innerHTML = 'Battles today: <b>' + won + '</b> won, <b>' + (list.length - won) + '</b> lost';
  ol.textContent = '';
  for (const g of [...list].reverse()) {
    const li = document.createElement('li'); li.className = g.result;
    const t = document.createElement('span'); t.className = 't'; t.textContent = g.time;
    const r = document.createElement('span'); r.className = 'r'; r.textContent = g.result === 'win' ? 'Won' : (g.gave_up ? 'Gave up' : 'Lost');
    const f = document.createElement('span'); f.className = 'f';
    f.textContent = (g.foes.length ? 'vs ' + g.foes.join(', ') : 'foes not read') + (g.league ? ' (' + g.league + ')' : '');
    f.title = f.textContent;
    li.append(t, r, f); ol.append(li);
  }
}

const CHAPTERS = @@CHAPTERS@@;
let testOn = false;
(function buildChapters() {                         // the test chapters, by group
  const box = $('chapters'); let group = '';
  for (const c of CHAPTERS) {
    if (c.group !== group) { group = c.group; const h = document.createElement('h3'); h.textContent = group; box.append(h); }
    const row = document.createElement('div'); row.className = 'chap'; row.title = c.what;
    const b = document.createElement('b'); b.textContent = c.title;
    const sm = document.createElement('small'); sm.textContent = 'Start: ' + c.start;
    const go = document.createElement('button'); go.className = 'btn small'; go.textContent = 'Run';
    go.dataset.key = c.key; go.onclick = () => testStart(c);
    row.append(b, go, sm); box.append(row);
  }
})();
async function testStart(c) {
  if (!confirm(c.title + '\n\n' + c.what + '\n\nThe bot is stopped for this test. Is the game on: ' + c.start + '?')) return;
  const r = await fetch('test/start/' + c.key + ($('testrec').checked ? '?rec=1' : ''), {method: 'POST'});
  if (!r.ok) alert('The test did not start: ' + await r.text());
  refresh();
}
async function testStop() { await fetch('test/stop', {method: 'POST'}); refresh(); }
function showTest(t) {
  testOn = !!(t && t.running);
  for (const b of document.querySelectorAll('.chap .btn')) b.disabled = testOn;
  const now = $('testnow');
  if (!t || !t.key) { now.hidden = true; return; }
  now.hidden = false;
  const line = $('testline'); line.textContent = '';
  const st = document.createElement('span');
  if (t.running) { st.className = 'busy'; st.textContent = 'Running'; }
  else if (t.ok) { st.className = 'ok'; st.textContent = 'Done'; }
  else { st.className = 'bad'; st.textContent = 'Failed'; }
  line.append(st, ' ' + t.title + ', ' + t.seconds + ' s' + (t.result ? ': ' + t.result : '') + (t.rec && t.running ? ' (recording)' : ''));
  $('teststop').hidden = !t.running;
  $('testdl').hidden = !t.ready;
  if (t.running) $('testbox').open = true;
}

// ---------- Claude ----------
let chatSeen = '';
function chatToggle(on) { $('chat').classList.toggle('open', on); if (on) $('chattext').focus(); }
function chatSettings() {
  const f = $('chatset'); f.hidden = !f.hidden; $('chatgear').setAttribute('aria-expanded', String(!f.hidden));
  if (!f.hidden) { $('chatlist').hidden = true; $('chatsbtn').setAttribute('aria-expanded', 'false'); }
}
let chatNow = null;
function chatList() {
  const l = $('chatlist'); l.hidden = !l.hidden; $('chatsbtn').setAttribute('aria-expanded', String(!l.hidden));
  if (!l.hidden) { $('chatset').hidden = true; $('chatgear').setAttribute('aria-expanded', 'false'); }
}
async function post(url, body) {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
  if (!r.ok) alert(await r.text());
  chatSeen = ''; chatRefresh(); return r.ok;
}
function showChats(c) {
  $('chatwhere').innerHTML = '<b>' + esc(c.project.name) + '</b> / ' + esc(c.chat.title);
  const sel = $('projsel');
  const names = c.projects.map(p => p.id + p.name).join();
  if (sel.dataset.names !== names) {
    sel.innerHTML = c.projects.map(p => '<option value="' + esc(p.id) + '">' + esc(p.name) + '</option>').join('');
    sel.dataset.names = names;
  }
  if (document.activeElement !== sel) sel.value = c.project.id;
  $('projdel').hidden = c.projects.length < 2;
  const ul = $('chatitems'), key = JSON.stringify([c.chats, c.chat.id]);
  if (ul.dataset.key === key) return;
  ul.dataset.key = key; ul.textContent = '';
  for (const it of c.chats) {
    const li = document.createElement('li'); if (it.id === c.chat.id) li.className = 'on';
    const o = document.createElement('button'); o.className = 'open'; o.textContent = it.title;
    const sm = document.createElement('small'); sm.textContent = it.updated.slice(5); o.append(sm);
    o.onclick = () => post('chat/open', {id: it.id});
    const d = document.createElement('button'); d.className = 'del'; d.textContent = '\u00d7'; d.title = 'Delete this chat';
    d.setAttribute('aria-label', 'Delete the chat ' + it.title);
    d.onclick = () => { if (confirm('Delete the chat "' + it.title + '"?')) post('chat/delete', {id: it.id}); };
    li.append(o, d); ul.append(li);
  }
}
function projOpen(id) { post('chat/project/open', {id}); }
function projEdit(existing) {
  const f = $('projedit'), p = chatNow && chatNow.project;
  f.dataset.id = existing && p ? p.id : '';
  $('proj_name').value = existing && p ? p.name : '';
  $('proj_ins').value = existing && p ? p.instructions : '';
  $('proj_notes').value = existing && p ? p.notes : '';
  f.hidden = false; $('proj_name').focus();
}
async function projSave(ev) {
  ev.preventDefault();
  const f = $('projedit');
  if (await post('chat/project', {id: f.dataset.id, name: $('proj_name').value, instructions: $('proj_ins').value, notes: $('proj_notes').value})) f.hidden = true;
}
function projDelete() {
  const p = chatNow && chatNow.project;
  if (p && confirm('Delete the project "' + p.name + '" and all its chats?')) { post('chat/project/delete', {id: p.id}); $('projedit').hidden = true; }
}
function esc(t) { return t.replace(/[&<>"]/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;'}[c])); }
function md(text) {                                   // a little markdown: code, bold, links, lists, line breaks
  return text.split(/```/).map((part, i) => {
    if (i % 2) return '<pre><code>' + esc(part.replace(/^[a-z]*\n/, '')) + '</code></pre>';
    let h = esc(part);
    h = h.replace(/`([^`\n]+)`/g, '<code>$1</code>').replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>')
         .replace(/^#{1,4} (.+)$/gm, '<b>$1</b>').replace(/^[-*] /gm, '\u2022 ')
         .replace(/(https:\/\/[^\s<)]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
    return h.replace(/\n/g, '<br>');
  }).join('');
}
function showChat(c) {
  chatNow = c; showChats(c);
  $('chatwho').textContent = c.has_key ? c.model + ', effort ' + (c.effort || 'default') : 'no API key yet';
  const ef = $('set_effort');
  if (!ef.options.length) ef.innerHTML = '<option value="">Model default</option>' + c.efforts.map(e => '<option>' + esc(e) + '</option>').join('');
  if (document.activeElement !== ef) ef.value = c.effort;
  $('set_key').placeholder = c.has_key ? 'set (type a new one to change it)' : 'not set';
  $('set_gh').placeholder = c.has_github ? 'set for ' + (c.github_user || '?') : 'not set';
  $('set_maker').textContent = c.maker;
  const sel = $('set_model');
  if (sel.options.length !== c.models.length) sel.innerHTML = c.models.map(m => '<option>' + esc(m) + '</option>').join('');
  if (document.activeElement !== sel) sel.value = c.model;
  $('chatbusy').hidden = !c.busy; $('chatprog').textContent = c.progress || 'Thinking';
  $('chatgo').disabled = c.busy;
  const key = c.chat.id + '|' + c.messages.length + '|' + (c.messages.length ? c.messages[c.messages.length - 1].text.length : 0) + '|' + c.has_key + c.password;
  if (key === chatSeen) return;
  chatSeen = key;
  const log = $('chatlog'), atEnd = log.scrollHeight - log.scrollTop - log.clientHeight < 60;
  log.textContent = '';
  if (!c.messages.length) {
    const p = document.createElement('p'); p.className = 'chatempty';
    p.textContent = !c.password ? 'Set a password for the web interface first: Claude uses your API key.'
      : !c.has_key ? 'Add your Claude API key under Settings to start.'
      : 'Ask about what the bot did, a problem in the log or on the screen, or a change to the code. Changes become a pull request at ' + c.maker + '.';
    log.append(p); return;
  }
  for (const m of c.messages) {
    const d = document.createElement('div'); d.className = 'msg ' + (m.role === 'note' ? 'tell' : m.role);
    if (m.role === 'assistant') d.innerHTML = md(m.text);
    else if (m.role === 'note' && m.url) { d.append(m.text.split(m.url)[0]); const a = document.createElement('a'); a.href = m.url; a.target = '_blank'; a.rel = 'noopener'; a.textContent = m.url; d.append(a); }
    else d.textContent = m.text;
    log.append(d);
  }
  if (atEnd || c.busy) log.scrollTop = log.scrollHeight;
}
async function chatRefresh() {
  try { showChat(await (await fetch('chat/state')).json()); } catch (e) {}
}
async function chatSend(ev) {
  ev.preventDefault();
  const t = $('chattext'), text = t.value.trim();
  if (!text) return;
  const r = await fetch('chat/send', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text})});
  if (!r.ok) { alert(await r.text()); return; }
  t.value = ''; chatRefresh();
}
$('chattext').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); chatSend(e); } });
async function chatNew() { await post('chat/new', {}); $('chattext').focus(); }
async function chatStop() { await fetch('chat/stop', {method: 'POST'}); }
async function chatSave(ev) {
  ev.preventDefault();
  const body = {api_key: $('set_key').value, github_token: $('set_gh').value, model: $('set_model').value, effort: $('set_effort').value};
  const r = await fetch('chat/settings', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  $('set_msg').textContent = await r.text();
  if (r.ok) { $('set_key').value = ''; $('set_gh').value = ''; }
  chatSeen = ''; chatRefresh();
}
chatRefresh();
setInterval(chatRefresh, 2500);

async function clearLog() {
  if (!confirm('Delete the whole log and the pictures the bot saved? This cannot be undone. The battles won and lost of today start again at nothing.')) return;
  await fetch('log/clear', {method: 'POST'}); refresh();
}

async function resetGames() {
  if (!confirm('Reset the battles won and lost? Only battles from now on will be counted.')) return;
  await fetch('battles/reset', {method: 'POST'}); refresh();
}

async function refresh() {
  try {
    const s = await (await fetch('status')).json();
    const [name, tone] = STATES[s.service] || [s.service || 'Unknown', 'hold'];
    $('svc').textContent = name; $('state').dataset.s = tone;
    showStats(s.stats);
    showGames(s.battles);
    showTest(s.test);
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
    showBag(s.control.bag_keep);
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
const BAG_ITEMS = @@BAGITEMS@@;                      // [name, standard number or null]
function bagValues(saved) { const o = {}; for (const [n, k] of BAG_ITEMS) o[n] = saved && n in saved ? saved[n] : k; return o; }
function bagSummary(v) {
  const gone = [], kept = [];
  for (const [n] of BAG_ITEMS) { const k = v[n]; if (k === null || k === '' || k === undefined) continue; (Number(k) === 0 ? gone : kept).push(Number(k) === 0 ? n : k + ' ' + n); }
  const join = xs => xs.length === 1 ? xs[0] : xs.slice(0, -1).join(', ') + ' and ' + xs[xs.length - 1];
  const parts = (gone.length ? ['discards ' + join(gone)] : []).concat(kept.length ? ['keeps ' + join(kept)] : []);
  if (!parts.length) return 'Nothing is set to be cleaned up.';
  const t = parts.join('; '); return t[0].toUpperCase() + t.slice(1) + '. Nothing else is touched.';
}
function showBag(saved) {
  const v = bagValues(saved), box = $('bagitems');
  if (!box.childElementCount) {
    for (const [n] of BAG_ITEMS) {
      const l = document.createElement('label'); l.append(n);
      const i = document.createElement('input'); i.type = 'number'; i.min = 0; i.max = 9999; i.className = 'inp';
      i.placeholder = 'leave'; i.dataset.n = n; i.setAttribute('aria-label', 'Keep how many ' + n);
      i.onchange = bagSave; l.append(i); box.append(l);
    }
  }
  for (const i of box.querySelectorAll('input')) if (document.activeElement !== i) i.value = v[i.dataset.n] === null ? '' : v[i.dataset.n];
  const h = document.querySelector('#o_bag_clean') && document.querySelector('#o_bag_clean').closest('.row').querySelector('.h');
  if (h) { h.textContent = bagSummary(v); h.closest('.row').title = h.textContent; }
}
async function bagSave() {
  const d = {};
  for (const i of $('bagitems').querySelectorAll('input')) d[i.dataset.n] = i.value === '' ? null : Number(i.value);
  const r = await fetch('bag_keep', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(d)});
  $('bagmsg').textContent = r.ok ? 'Saved.' : 'Not saved: ' + await r.text();
  refresh();
}
async function bagDefaults() {
  if (!confirm('Set the standard numbers again?')) return;
  for (const i of $('bagitems').querySelectorAll('input')) { const k = BAG_ITEMS.find(x => x[0] === i.dataset.n)[1]; i.value = k === null ? '' : k; }
  bagSave();
}
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
  else if (r.ready) t = 'Recording ready: ' + r.frames + ' pictures, ' + r.seconds + ' s, ' + r.mb + ' MB, with the log of the bot.' + (r.note ? ' ' + r.note : '');
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
function touchMark(x1, y1, x2, y2) {                 // shows at once where the tap or swipe went (the picture comes later)
  const f = $('frame'), r = img.getBoundingClientRect(), fr = f.getBoundingClientRect();
  const m = document.createElement('div');
  const ax = r.left - fr.left + x1, ay = r.top - fr.top + y1;
  if (x2 === undefined) { m.className = 'touch'; m.style.left = ax + 'px'; m.style.top = ay + 'px'; }
  else {
    m.className = 'touch line'; m.style.left = ax + 'px'; m.style.top = ay + 'px';
    m.style.width = Math.hypot(x2 - x1, y2 - y1) + 'px'; m.style.transform = `rotate(${Math.atan2(y2 - y1, x2 - x1)}rad)`;
  }
  f.append(m); setTimeout(() => m.remove(), 800);
}
img.addEventListener('pointerup', e => {
  if (!manual || !down) return; e.preventDefault();
  const p = phonePos(e), ms = Date.now() - down.t, d = Math.hypot(p[0] - down.p[0], p[1] - down.p[1]);
  const r = img.getBoundingClientRect(), sx = r.width / PW, sy = r.height / PH;
  if (d < 25 && ms < 450) { touchMark(p[0] * sx, p[1] * sy); fetch(`input/tap?x=${p[0]}&y=${p[1]}`, {method: 'POST'}); }
  else {
    touchMark(down.p[0] * sx, down.p[1] * sy, p[0] * sx, p[1] * sy);
    fetch(`input/swipe?x1=${down.p[0]}&y1=${down.p[1]}&x2=${p[0]}&y2=${p[1]}&ms=${Math.max(ms, 80)}`, {method: 'POST'});
  }
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
PAGE = PAGE.replace("@@BAGITEMS@@", json.dumps(bag_rules.ITEMS, ensure_ascii=False))
PAGE = PAGE.replace("@@NAME@@", APP_NAME).replace("@@CHAPTERS@@", json.dumps(CH.as_list()).replace("</", "<\\/"))



# ----------------------------- battle recorder -----------------------------
# A tool to teach the bot the screens of a battle. With the bot stopped: press Record, play ONE battle
# on the phone yourself, press Stop and download the zip. It holds small pictures of the screen (one
# whenever the picture changes, at most REC_FPS per second, with the time in the file name), and the
# raw touch events of the phone (getevent), so that every tap can be matched with its picture.
# It is also the way to show what the bot did in a battle it fought itself (gamebot.py fight, started by
# hand while the service is stopped): then the zip also holds what the bot wrote in its log during the
# recording (bot_log.txt) and the pictures it saved meanwhile (debug/), so that one file tells the story.
REC_DIR = os.path.expanduser("~/battle_recording")
REC_FPS = 2.0                 # pictures per second at most (a slow phone link gives fewer)
REC_SCALE = 0.35              # size of the saved pictures compared with the screen
REC_QUALITY = 55              # JPEG quality
REC_MAX_FRAMES = 420          # then the recording stops by itself
REC_MAX_MB = 30               # ... or when the pictures together are this big (the zip stays easy to send)
REC_MAX_SECONDS = 600
REC_KEEP_SAME = 4.0           # s: a picture that did not change is still kept now and then
REC_LOG_BEFORE = 30           # s before the recording from which the lines of the bot's log are taken along
REC_PICTURES = 12             # the newest pictures the bot saved during the recording go into the zip too ...
REC_PICTURE_WIDTH = 900       # ... not wider than this (px; the text on them stays readable), as JPEG
rec = {"on": False, "frames": 0, "t0": 0.0, "secs": 0, "note": "", "zip": None, "mb": 0.0, "bytes": 0,
       "stop": threading.Event(), "thread": None, "touch": None}
rec_lock = threading.Lock()


def rec_status():
    secs = int(time.time() - rec["t0"]) if rec["on"] else rec["secs"]
    return {"on": rec["on"], "frames": rec["frames"], "seconds": secs, "max": REC_MAX_FRAMES,
            "note": rec["note"], "ready": bool(rec["zip"]) and not rec["on"], "mb": rec["mb"]}


def log_since(t0, limit=None):
    """The lines the bot (and this web interface) wrote in the log from time t0 on, '' when there are none.
    Only the end of the log is looked at (`limit` bytes).  Every line starts with its date and time."""
    try:
        with open(LOGFILE, "rb") as f:
            f.seek(0, 2)
            f.seek(max(f.tell() - (limit or DEBUG_LOG_BYTES), 0))
            lines = f.read().decode(errors="ignore").splitlines()
    except OSError as e:
        return f"(the log could not be read: {e})"
    start = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0))
    for i, line in enumerate(lines):
        if re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", line) and line[:19] >= start:
            return "\n".join(lines[i:])
    return ""


def rec_pictures(t0):
    """[(name, time, JPEG bytes)]: the newest pictures the bot saved in ~/debug from time t0 on (in a battle:
    the result screen, a screen it did not know ...), not wider than REC_PICTURE_WIDTH, the newest first."""
    try:
        names = [n for n in os.listdir(DEBUG_DIR) if n.lower().endswith((".png", ".jpg"))]
    except OSError:
        return []
    files = []
    for n in names:
        try:
            files.append((os.path.getmtime(os.path.join(DEBUG_DIR, n)), n))
        except OSError:                                    # (the bot replaced it just now)
            pass
    out = []
    for mtime, n in sorted(files, reverse=True):
        if mtime < t0 or len(out) >= REC_PICTURES:
            break
        if os.path.splitext(n)[0] in [os.path.splitext(name)[0] for name, _t, _d in out]:
            continue                                       # (g_x.png and g_x.jpg: the newer one is in already)
        try:
            img = cv2.imread(os.path.join(DEBUG_DIR, n))
            h, w = img.shape[:2]
            if w > REC_PICTURE_WIDTH:
                img = cv2.resize(img, (REC_PICTURE_WIDTH, int(round(h * REC_PICTURE_WIDTH / float(w)))),
                                 interpolation=cv2.INTER_AREA)
            ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
            out.append((os.path.splitext(n)[0] + ".jpg", mtime, jpg.tobytes()))
        except Exception:  # noqa: BLE001
            continue
    return out


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
            # what the bot did meanwhile, when it was the bot that fought: its log and its pictures
            z.writestr("bot_log.txt", log_since(rec["t0"] - REC_LOG_BEFORE)
                       or "(nothing was written in the log during this recording)", zipfile.ZIP_DEFLATED)
            for name, mtime, data in rec_pictures(rec["t0"] - REC_LOG_BEFORE):
                z.writestr(zipfile.ZipInfo("debug/" + name, time.localtime(mtime)[:6]), data, zipfile.ZIP_STORED)
            for fn in DEBUG_FILES:                         # (the team, and what the bot has learned so far)
                if os.path.exists(os.path.expanduser("~/" + fn)):
                    z.write(os.path.expanduser("~/" + fn), fn, compress_type=zipfile.ZIP_DEFLATED)
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


# ---------- Test: one part of the bot on its own (chapters.py, 'gamebot.py chapter <key>') ----------
TEST_STOP_WAIT = 20            # s: the bot service has this long to stop before a test starts
TEST_ERR = os.path.join(DEBUG_DIR, "test_stderr.txt")
test = {"proc": None, "key": "", "title": "", "t0": 0.0, "end": 0.0, "result": "", "ok": None, "rec": False}
test_lock = threading.Lock()


def test_running():
    return bool(test["proc"]) and test["proc"].poll() is None


def test_result(key, t0):
    """(ok, text) of the line 'TEST <key>: done / failed - ...' the test wrote, or (None, '')."""
    for line in reversed(log_since(t0).splitlines()):
        m = re.search(r"TEST " + re.escape(key) + r": (done|failed) - (.*)$", line)
        if m:
            return m.group(1) == "done", m.group(2)
    return None, ""


def _test_watch(proc, key, record):
    proc.wait()
    test["end"] = time.time()
    if record:
        rec_stop()
    ok, text = test_result(key, test["t0"])
    if ok is None:                                   # it never got to its last line: a crash at the start
        err = ""
        try:
            with open(TEST_ERR, errors="ignore") as f:
                err = " | ".join(f.read().strip().splitlines()[-3:])
        except OSError:
            pass
        ok, text = False, f"ended without a result (exit code {proc.returncode})" + (f": {err}" if err else "")
        write_log(f"TEST {key}: failed - {text}")
    test.update(ok=ok, result=text)


def test_start(key, record=False):
    """(ok, message): stop the bot service and run the chapter `key`. The game is left on the screen it is on."""
    ch = CH.chapter(key)
    if not ch:
        return False, "no such test"
    with test_lock:
        if test_running():
            return False, "a test is running already"
        if rec["on"]:
            return False, "a recording is running: stop it first"
        if bot_running():
            subprocess.run(["sudo", "-n", "/usr/bin/systemctl", "stop", SERVICE], capture_output=True)
            t_end = time.time() + TEST_STOP_WAIT
            while bot_running() and time.time() < t_end:
                time.sleep(0.5)
            if bot_running():
                return False, "the bot did not stop"
        t0 = time.time()
        test.update(key=key, title=ch["title"], t0=t0, end=0.0, result="", ok=None, rec=False)
        if record:
            ok, _ = rec_start()
            test["rec"] = ok
        os.makedirs(DEBUG_DIR, exist_ok=True)
        here = os.path.dirname(os.path.abspath(__file__))
        with open(TEST_ERR, "w") as err:             # (the child keeps its own copy of the file)
            test["proc"] = subprocess.Popen([sys.executable, os.path.join(here, "gamebot.py"), "chapter", key],
                                            cwd=os.path.expanduser("~"), stdout=subprocess.DEVNULL,
                                            stderr=err, start_new_session=True)
        threading.Thread(target=_test_watch, args=(test["proc"], key, test["rec"]), daemon=True,
                         name="test-watch").start()
        return True, "ok"


def test_stop():
    proc = test["proc"]
    if not proc or proc.poll() is not None:
        return
    proc.terminate()                                  # (the test says 'stopped' and saves the screen)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_status():
    run = test_running()
    return {"key": test["key"], "title": test["title"], "running": run, "ok": test["ok"], "result": test["result"],
            "seconds": int((time.time() if run else (test["end"] or time.time())) - test["t0"]) if test["t0"] else 0,
            "rec": test["rec"], "ready": bool(test["t0"]) and not run}


def test_zip():
    """The zip of the last test: what was logged from its start on, the pictures it saved, the bot's files -
    and the screen recording, when it was recorded."""
    t0 = test["t0"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("test.txt", f"test: {test['key']} - {test['title']}\nresult: {'done' if test['ok'] else 'failed'}"
                   f" - {test['result']}\nstarted: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t0))}\n")
        z.writestr("bot_log.txt", log_since(t0 - 2) or "(nothing was logged)")
        for name, mtime, data in rec_pictures(t0 - 2):
            z.writestr(zipfile.ZipInfo("debug/" + name, time.localtime(mtime)[:6]), data, zipfile.ZIP_STORED)
        for fn in DEBUG_FILES:
            if os.path.exists(os.path.expanduser("~/" + fn)):
                z.write(os.path.expanduser("~/" + fn), fn)
        if test["rec"] and rec["zip"] and os.path.exists(rec["zip"]):
            z.write(rec["zip"], "screen_recording.zip", compress_type=zipfile.ZIP_STORED)
    return buf.getvalue()


# ---------- Claude: the chat on the right side ----------
def code_dir():
    """Where the code of the bot is as a git repository (for Claude to read): the clone that is pulled, else
    the folder of this file."""
    clone = os.path.expanduser("~/pokemon-go-automation")
    return clone if os.path.isdir(os.path.join(clone, ".git")) else os.path.dirname(os.path.abspath(__file__))


chat = claude_chat.Chat(code_dir(), status_fn=lambda: status(), log_file=LOGFILE, shot_fn=lambda: latest["jpg"],
                        write_log=write_log, chapters=[c["title"] for c in CH.as_list()])


def chat_state():
    st = chat.state()
    st["password"] = bool(password())
    return st


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

    def _json_body(self, limit=200000):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > limit:
                return {}
            d = json.loads(self.rfile.read(n).decode("utf-8", errors="ignore"))
            return d if isinstance(d, dict) else {}
        except (ValueError, OSError):
            return {}

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
        elif path == "/debug/download":
            data = debug_zip()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="gamebot-debug-'
                             + time.strftime("%Y%m%d-%H%M%S") + '.zip"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path == "/chat/state":
            self._send(json.dumps(chat_state()), "application/json")
        elif path == "/test/download":
            if not test["t0"] or test_running():
                return self._send("no test yet", code=404)
            data = test_zip()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="test-{test["key"]}-'
                             + time.strftime("%Y%m%d-%H%M%S", time.localtime(test["t0"])) + '.zip"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
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
        m = re.fullmatch(r"/test/start/([a-z_]+)", path)
        if m:
            ok, msg = test_start(m.group(1), record="rec=1" in self.path)
            return self._send(msg, code=200 if ok else 409)
        if path == "/bag_keep":
            c = read_control()
            c["bag_keep"] = bag_rules.clean(self._json_body())
            write_control(c)
            write_log("bag clean-up: what the bag keeps was changed in the web interface - " + bag_rules.summary(c["bag_keep"]))
            return self._send("ok")
        if path == "/chat/send":
            if not password():                     # (anyone on the network could use the API key)
                return self._send("set a password for the web interface first (wiki page Installation)", code=409)
            ok, msg = chat.send(str(self._json_body().get("text", ""))[:20000])
            return self._send(msg, code=200 if ok else 409)
        if path == "/chat/new":
            ok = chat.new(self._json_body().get("project"))
            return self._send("ok" if ok else "Claude is still answering", code=200 if ok else 409)
        if path in ("/chat/open", "/chat/delete", "/chat/project/open", "/chat/project/delete"):
            cid = str(self._json_body().get("id", ""))
            ok = {"/chat/open": chat.open_chat, "/chat/delete": chat.delete_chat, "/chat/project/open": chat.open_project,
                  "/chat/project/delete": chat.delete_project}[path](cid)
            return self._send("ok" if ok else "not possible now (Claude is answering, or it is not there)",
                              code=200 if ok else 409)
        if path == "/chat/project":
            p = chat.save_project(self._json_body())
            return self._send(json.dumps(p) if p else "a project needs a name", "application/json" if p else
                              "text/plain; charset=utf-8", code=200 if p else 400)
        if path == "/chat/stop":
            chat.stop()
            return self._send("ok")
        if path == "/chat/settings":
            ok, msg = chat.set_settings(self._json_body())
            return self._send(msg, code=200 if ok else 400)
        if path == "/test/stop":
            test_stop()
            return self._send("ok")
        if path == "/log/clear":
            n_lines, pictures = clear_log()
            return self._send(f"{n_lines} lines, {pictures} pictures")
        if path == "/battles/reset":
            reset_battles()
            return self._send("ok")
        if path == "/action/close":
            threading.Thread(target=close_game, daemon=True).start()
            return self._send("ok")
        if path.startswith("/input/"):
            # manual control: only while the bot is stopped, so you never fight the bot
            if bot_running() or test_running():
                return self._send("stop the bot first" if bot_running() else "a test is running", code=409)
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
