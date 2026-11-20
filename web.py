#!/usr/bin/env python3
"""
Gamebot web interface - watch the phone and the log from any browser.

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
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

import spin_stop as S        # the phone's screen (which display, how big) is found there

# ================================ SETTINGS ================================
PORT = 8080
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
    "catch": "Catch wild Pokémon",
    "spin": "Spin PokéStops",
    "gifts_open": "Open gifts from friends",
    "gifts_send": "Send gifts to friends",
    "curveball": "Always throw a curveball",
    "fast_catch": "Fast catch: after a clear hit press BACK to skip the catch animation (the result is checked on the map)",
    "spin_only_when_full": "Only spin PokéStops when Pokémon storage is full",
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


DEFAULT_OFF = {"curveball", "buddy", "fast_catch"}                 # options that start unticked
THROW_TARGETS = ("realistic", "off", "nice", "great", "excellent")


def read_control():
    c = {k: k not in DEFAULT_OFF for k in OPTIONS}
    c["daily_time"] = "08:00"
    c["daily_max_min"] = 480
    c["throw_target"] = "realistic"
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


def status():
    active = subprocess.run(["systemctl", "is-active", SERVICE], capture_output=True).stdout.decode().strip()
    stats = ""
    for line in reversed(read_log(400)):
        m = re.search(r"\(today: ([^)]*)\)", line)
        if m:
            stats = m.group(1)
            break
    _, pw, ph = phone()
    return {"service": active, "stats": stats, "control": read_control(), "labels": OPTIONS,
            "w": pw, "h": ph, "phone": S.screen["model"], "screen_note": S.screen["note"], "screen_ok": S.screen["ok"],
            "video": latest["mode"], "error": latest["error"],
            "age": round(time.time() - latest["time"], 1) if latest["time"] else None}


PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gamebot</title>
<style>
 :root { color-scheme: dark; }
 body { margin:0; font-family: system-ui, sans-serif; background:#111418; color:#e6e6e6; }
 header { padding:12px 16px; background:#1b2027; display:flex; flex-wrap:wrap; gap:10px; align-items:center; }
 h1 { font-size:18px; margin:0 12px 0 0; }
 .pill { padding:4px 10px; border-radius:999px; background:#2a313b; font-size:13px; }
 .ok { background:#1f6f43; } .bad { background:#8a2b2b; }
 main { display:flex; flex-wrap:wrap; gap:16px; padding:16px; }
 .screen img { width:min(420px, 92vw); border-radius:14px; border:1px solid #2a313b; display:block; background:#000; aspect-ratio: 0.8; }
 .side { flex:1 1 360px; min-width:300px; display:flex; flex-direction:column; gap:12px; }
 .card { background:#1b2027; border-radius:12px; padding:12px; }
 .card h2 { font-size:14px; margin:0 0 8px; color:#9aa4b2; font-weight:600; }
 button { background:#2d6cdf; color:#fff; border:0; border-radius:8px; padding:8px 12px; margin:3px; font-size:14px; cursor:pointer; }
 button.grey { background:#3a424e; } button.red { background:#b53a3a; }
 label.opt { display:flex; align-items:center; gap:10px; padding:6px 2px; font-size:15px; cursor:pointer; }
 label.opt input { width:20px; height:20px; }
 pre { margin:0; white-space:pre-wrap; font-size:12px; line-height:1.45; max-height:38vh; overflow:auto; }
 .muted { color:#9aa4b2; font-size:12px; }
 .screen { position:relative; }
 .screen img.manual { outline:3px solid #e0a020; cursor:crosshair; touch-action:none; }
 #manualbar { display:none; margin-top:8px; }
 #manualbar.on { display:block; }
 .banner { background:#5a4510; color:#ffd77a; border-radius:8px; padding:6px 10px; font-size:13px; margin-bottom:6px; }
</style></head><body>
<header>
 <h1>🎮 Gamebot</h1>
 <span id="svc" class="pill">bot: …</span>
 <span id="stats" class="pill">today: …</span>
 <span id="vid" class="pill muted">video: …</span>
 <span id="scr_note" class="pill bad" style="display:none"></span>
</header>
<main>
 <div class="screen"><img id="scr" src="stream" alt="phone screen" draggable="false">
  <div id="manualbar">
   <div class="banner">Manual control - click to tap, drag to swipe, hold to long-press</div>
   <button class="grey" onclick="key('back')">◀ Back</button>
   <button class="grey" onclick="key('home')">● Home</button>
   <button class="grey" onclick="key('apps')">▤ Apps</button>
   <input id="txt" placeholder="type text" style="padding:7px;border-radius:8px;border:0;width:120px">
   <button class="grey" onclick="sendText()">Send</button>
  </div>
 </div>
 <div class="side">
  <div class="card"><h2>Bot</h2>
   <button onclick="act('start')">▶ Start</button>
   <button class="red" onclick="act('stop')">■ Stop</button>
   <button class="grey" onclick="act('restart')">↻ Restart</button>
   <button class="red" onclick="act('close')">✕ Close game</button>
   <div class="muted">Close game stops the bot and closes Pokémon GO completely on the phone. Press Start to play again.</div>
   <div class="muted">Stop the bot to take over control (e.g. for quests). Stop it too before opening Pokémon GO on another device.</div>
  </div>
  <div class="card"><h2>Options</h2><div id="opts"></div>
   <label class="opt">Throw target
    <select id="ttarget" style="padding:6px 8px;font-size:15px;border-radius:6px;border:0;background:#2a313b;color:#fff" onchange="setTarget(this.value)">
     <option value="realistic">Realistic (mostly Great, not every throw perfect)</option>
     <option value="off">Off (just throw)</option><option value="nice">Nice</option>
     <option value="great">Great</option><option value="excellent">Excellent</option>
    </select>
   </label>
   <label class="opt">Daily run starts at
    <input type="time" id="dtime" style="width:120px;height:auto;padding:6px 8px;font-size:15px;border-radius:6px;border:0;background:#2a313b;color:#fff;color-scheme:dark" onchange="setTime(this.value)">
   </label>
   <label class="opt">Daily run: max time per game
    <input type="number" id="dmax" min="5" max="1440" step="5" style="width:90px;height:auto;padding:6px 8px;font-size:15px;border-radius:6px;border:0;background:#2a313b;color:#fff" onchange="setMax(this.value)"> minutes
   </label>
   <div class="muted">When a game reaches this time it is closed and the next game starts.</div></div>
  <div class="card"><h2>Log <span class="muted">(newest first)</span></h2><pre id="log">loading…</pre></div>
 </div>
</main>
<script>
const img = document.getElementById('scr');
img.onerror = () => setTimeout(() => { img.src = 'stream?t=' + Date.now(); }, 3000);
let built = false;
async function refresh(){
  try {
    const s = await (await fetch('status')).json();
    const svc = document.getElementById('svc');
    svc.textContent = 'bot: ' + (s.service === 'active' ? 'running' : (s.service || 'unknown'));
    svc.className = 'pill ' + (s.service === 'active' ? 'ok' : 'bad');
    document.getElementById('stats').textContent = 'today: ' + (s.stats || '–');
    if (s.w && s.h) { PW = s.w; PH = s.h; img.style.aspectRatio = (s.w / s.h).toFixed(4); }
    const sn = document.getElementById('scr_note');
    sn.style.display = s.screen_note ? 'inline-block' : 'none';
    sn.textContent = s.screen_note ? '⚠ ' + s.screen_note : '';
    sn.className = 'pill ' + (s.screen_ok ? 'muted' : 'bad');
    document.getElementById('vid').textContent = 'video: ' + (s.error ? s.error : s.video + (s.age!==null ? ' (' + s.age + ' s)' : ''));
    const box = document.getElementById('opts');
    if (!built) {
      for (const [k, label] of Object.entries(s.labels)) {
        box.insertAdjacentHTML('beforeend',
          `<label class="opt"><input type="checkbox" id="o_${k}" onchange="setOpt('${k}', this.checked)"> ${label}</label>`);
      }
      built = true;
    }
    for (const k of Object.keys(s.labels)) document.getElementById('o_'+k).checked = !!s.control[k];
    const tt = document.getElementById('ttarget');
    if (document.activeElement !== tt) tt.value = s.control.throw_target || 'realistic';
    const dm = document.getElementById('dmax');
    if (document.activeElement !== dm) dm.value = s.control.daily_max_min || 480;
    const dt = document.getElementById('dtime');
    if (document.activeElement !== dt) dt.value = s.control.daily_time || '08:00';
    const log = document.getElementById('log');
    log.textContent = await (await fetch('log')).text();
  } catch(e) {}
}
async function act(a){ if (a==='stop' && !confirm('Stop the bot?')) return;
  if (a==='close' && !confirm('Stop the bot and close Pokémon GO completely?')) return; await fetch('action/'+a,{method:'POST'}); setTimeout(refresh, 1500); }
async function setMax(v){ const n = Math.round(Number(v)); if (n >= 5 && n <= 1440) await fetch('daily_max/'+n,{method:'POST'}); refresh(); }
async function setTime(t){ if (/^\\d\\d:\\d\\d$/.test(t)) await fetch('daily_time/'+t,{method:'POST'}); refresh(); }
async function setTarget(v){ await fetch('throw_target/'+v,{method:'POST'}); refresh(); }
async function setOpt(k, on){ await fetch('option/'+k+'/'+(on?'on':'off'),{method:'POST'}); refresh(); }
// ---- manual control (only while the bot is stopped) ----
let manual = false, down = null;
let PW = 1768, PH = 2208;                          // phone screen in pixels (updated from the status)
function phonePos(e){ const r = img.getBoundingClientRect();
  return [Math.round((e.clientX - r.left) / r.width * PW), Math.round((e.clientY - r.top) / r.height * PH)]; }
img.addEventListener('pointerdown', e => { if (!manual) return; e.preventDefault();
  img.setPointerCapture(e.pointerId); down = {p: phonePos(e), t: Date.now()}; });
img.addEventListener('pointerup', e => { if (!manual || !down) return; e.preventDefault();
  const p = phonePos(e), ms = Date.now() - down.t, d = Math.hypot(p[0]-down.p[0], p[1]-down.p[1]);
  if (d < 25 && ms < 450) fetch(`input/tap?x=${p[0]}&y=${p[1]}`, {method:'POST'});
  else fetch(`input/swipe?x1=${down.p[0]}&y1=${down.p[1]}&x2=${p[0]}&y2=${p[1]}&ms=${Math.max(ms,80)}`, {method:'POST'});
  down = null; });
img.addEventListener('contextmenu', e => { if (manual) e.preventDefault(); });
function key(k){ fetch('input/key/'+k, {method:'POST'}); }
function sendText(){ const t = document.getElementById('txt'); fetch('input/text?t='+encodeURIComponent(t.value), {method:'POST'}); t.value=''; }
function setManual(on){ manual = on; img.classList.toggle('manual', on); document.getElementById('manualbar').classList.toggle('on', on); }
const _refresh = refresh;
refresh = async function(){ await _refresh();
  const running = document.getElementById('svc').textContent.includes('running'); setManual(!running); };
refresh(); setInterval(() => refresh(), 3000);
</script></body></html>"""


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
        self.send_header("WWW-Authenticate", 'Basic realm="Gamebot"')
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
    print(f"Gamebot web on http://0.0.0.0:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
