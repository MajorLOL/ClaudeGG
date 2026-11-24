"""Parts of the web interface that look after the bot rather than play: updating from GitHub, the history of the
days, warnings sent to the phone (ntfy), and a backup of what the bot has learned.

Only the standard library; web.py wires them to its pages.  Every function that runs a program or touches the
network takes it as an argument where a test needs to replace it."""
import io
import json
import os
import re
import subprocess
import threading
import time
import urllib.request
import zipfile

HOME = os.path.expanduser("~")


# ---------------------------------------------------------------- update ---
UPDATE_LOG = os.path.join(HOME, "update.log")
UPDATE_CHECK_EVERY = 30 * 60   # s between two looks for a new version on GitHub
update = {"checked": 0.0, "behind": 0, "subjects": [], "version": "", "error": "", "running": False,
          "result": "", "dirty": False}


def _git(repo, *args, timeout=60):
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).decode(errors="ignore").strip().splitlines()[-1:] or ["git failed"])
    return p.stdout.decode(errors="ignore").strip()


def update_check(repo, force=False):
    """Look on GitHub whether there is a newer version (at most every UPDATE_CHECK_EVERY s). Fills `update`."""
    if update["running"] or (not force and time.time() - update["checked"] < UPDATE_CHECK_EVERY):
        return update
    update["checked"] = time.time()
    try:
        update["version"] = _git(repo, "log", "-1", "--format=%h %cd", "--date=format:%d %b %H:%M")
        update["dirty"] = bool(_git(repo, "status", "--porcelain", "--untracked-files=no"))
        _git(repo, "fetch", "-q", "origin", timeout=90)
        branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "main"
        update["behind"] = int(_git(repo, "rev-list", "--count", f"HEAD..origin/{branch}") or 0)
        update["subjects"] = _git(repo, "log", "--format=%s", f"HEAD..origin/{branch}").splitlines()[:15]
        update["error"] = ""
    except Exception as e:  # noqa: BLE001
        update["error"] = str(e)[:200]
    return update


def update_run(repo, restart_bot, restart_web, write_log, install=("bash", "install.sh")):
    """git pull, install.sh, then restart the bot (when it runs) and the web interface. In a thread of its own;
    `update` says how far it is. restart_bot(): restarts the bot service when it was running. restart_web():
    ends this process (systemd starts it again)."""
    if update["running"]:
        return False
    update.update(running=True, result="Updating...")

    def run():
        ok = False
        try:
            with open(UPDATE_LOG, "w") as log:
                def step(cmd, timeout):
                    log.write("$ " + " ".join(cmd) + "\n")
                    log.flush()
                    p = subprocess.run(cmd, cwd=repo, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
                    if p.returncode != 0:
                        raise RuntimeError(f"'{' '.join(cmd)}' failed (see ~/update.log)")
                before = _git(repo, "rev-parse", "--short", "HEAD")
                step(["git", "pull", "--ff-only"], 180)
                after = _git(repo, "rev-parse", "--short", "HEAD")
                step(list(install), 900)
            ok = True
            update.update(result=f"Updated {before} -> {after}: restarting", behind=0, subjects=[])
            write_log(f"update: {before} -> {after} installed from the web interface - restarting the bot and the web interface")
        except Exception as e:  # noqa: BLE001
            update["result"] = f"Update failed: {e}"
            write_log(f"update: failed - {e}")
        finally:
            update["running"] = False
        if ok:
            restart_bot()
            time.sleep(2)
            restart_web()
    threading.Thread(target=run, daemon=True, name="update").start()
    return True


# --------------------------------------------------------------- history ---
HISTORY_FILE = os.path.join(HOME, "gamebot_history.json")
HISTORY_DAYS = 120
COUNTERS = ("caught", "fled", "stops", "won", "lost")


def history_record(day, counters, path=None):
    """Keep the counters of `day` (YYYY-MM-DD) in the history file: {day: {caught, fled, stops, won, lost}}."""
    path = path or HISTORY_FILE
    try:
        with open(path) as f:
            h = json.load(f)
        if not isinstance(h, dict):
            h = {}
    except (OSError, ValueError):
        h = {}
    h[day] = {k: int(counters.get(k, 0) or 0) for k in COUNTERS}
    for d in sorted(h)[:-HISTORY_DAYS]:
        h.pop(d, None)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(h, f, indent=0, sort_keys=True)
    os.replace(tmp, path)


def history_read(days=30, path=None):
    """[{day, caught, fled, stops, won, lost}] of the last `days` days that have counters, oldest first."""
    try:
        with open(path or HISTORY_FILE) as f:
            h = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(h, dict):
        return []
    out = []
    for d in sorted(h)[-days:]:
        v = h[d] if isinstance(h[d], dict) else {}
        out.append(dict({k: int(v.get(k, 0) or 0) for k in COUNTERS}, day=d))
    return out


# ----------------------------------------------------------------- alerts ---
NTFY_SERVER = "https://ntfy.sh"
ALERT_AGAIN = 3600             # s: the same warning is sent at most once an hour
alerts = {"sent": {}, "last": "", "last_t": 0.0}


def ntfy_send(topic, title, text, server=NTFY_SERVER, opener=None, priority="default"):
    """Send a message to the ntfy topic (the app on the phone shows it). Returns '' or the error."""
    topic = (topic or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", topic):
        return "no valid topic (6-64 letters, digits, - or _)"
    req = urllib.request.Request(f"{server.rstrip('/')}/{topic}", data=text.encode("utf-8"), method="POST",
                                 headers={"Title": title.encode("utf-8").decode("latin-1", "ignore"),
                                          "Priority": priority, "Tags": "video_game"})
    try:
        (opener or urllib.request.urlopen)(req, timeout=15).read()
        return ""
    except Exception as e:  # noqa: BLE001
        return str(e)[:200]


def alert(key, topic, title, text, send=None, now=None):
    """Send a warning, unless the same one (key) went out less than ALERT_AGAIN s ago. Returns True when sent."""
    now = now or time.time()
    if key in alerts["sent"] and now - alerts["sent"][key] < ALERT_AGAIN:
        return False
    err = (send or ntfy_send)(topic, title, text)
    alerts["sent"][key] = now
    alerts["last"], alerts["last_t"] = (f"{title}: {text}" if not err else f"not sent ({err}): {title}"), now
    return not err


def battery(text):
    """(level %, charging, °C) from 'dumpsys battery', None for what is not in it."""
    def num(key):
        m = re.search(r"^\s*" + key + r":\s*(-?\d+)", text or "", re.M)
        return int(m.group(1)) if m else None
    level, temp = num("level"), num("temperature")
    status = num("status")                       # 2 = charging, 5 = full
    powered = any(re.search(r"^\s*" + k + r" powered:\s*true", text or "", re.M) for k in ("AC", "USB", "Wireless"))
    return level, (status in (2, 5)) or powered, (temp / 10.0 if temp is not None else None)


def watch_once(topic, state, now=None, send=None):
    """One look of the watcher (web.py calls it every minute). state: {adb_ok, level, charging, phone_c, pi_c,
    log_age, bot_running, heat_paused, summary}: what web.py found. Returns the warnings that went out."""
    now = now or time.time()
    out = []
    if not topic:
        return out

    def go(key, title, text, prio="default"):
        if alert(key, topic, title, text, send=lambda t, ti, tx: (send or ntfy_send)(t, ti, tx, priority=prio), now=now):
            out.append(key)
    if state.get("adb_ok") is False:
        go("adb", "Phone not connected", "The Pi does not reach the phone over ADB (cable, USB debugging?).", "high")
    lvl = state.get("level")
    if lvl is not None and lvl <= 15 and not state.get("charging"):
        go("battery", "Battery low", f"The phone's battery is at {lvl}% and not charging.", "high")
    if (state.get("phone_c") or 0) >= 43:
        go("heat_phone", "Phone hot", f"The phone's battery is {state['phone_c']:.0f} °C.")
    if (state.get("pi_c") or 0) >= 80:
        go("heat_pi", "Pi hot", f"The Raspberry Pi is {state['pi_c']:.0f} °C and slows itself down.")
    if state.get("bot_running") and (state.get("log_age") or 0) > 20 * 60:
        go("quiet", "Bot quiet", f"The bot runs but wrote nothing for {state['log_age'] / 60:.0f} minutes.")
    if state.get("summary"):
        go("summary:" + state["summary"][0], "Run finished", state["summary"][1])
    return out


# ----------------------------------------------------------------- backup ---
BACKUP_FILES = ("gamebot_control.json", "gamebot_throw.json", "battle_seen.json", "battle_minigame.json",
                "battle_team.json", "gamebot_history.json")
BACKUP_MAX = 20 * 1024 * 1024


def backup_zip(home=None):
    """A zip of what the bot has learned and the settings (no keys, no passwords). Returns its bytes."""
    home = home or HOME
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        names = []
        for fn in BACKUP_FILES:
            p = os.path.join(home, fn)
            if os.path.isfile(p):
                z.write(p, fn)
                names.append(fn)
        z.writestr("backup.txt", "Backup of the gamebot, " + time.strftime("%Y-%m-%d %H:%M") + "\n" + "\n".join(names) + "\n")
    return buf.getvalue()


def backup_restore(data, home=None):
    """Put the files of a backup zip back. Only the known file names, only valid JSON. Returns (ok, message)."""
    home = home or HOME
    if not data or len(data) > BACKUP_MAX:
        return False, "no backup, or too big"
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return False, "not a zip file"
    put = []
    with z:
        for info in z.infolist():
            name = info.filename
            if name not in BACKUP_FILES or info.file_size > BACKUP_MAX:
                continue
            raw = z.read(info)
            try:
                json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return False, f"{name} is not valid JSON - nothing was put back"
            put.append((name, raw))
    if not put:
        return False, "no known files in the zip"
    for name, raw in put:
        p = os.path.join(home, name)
        with open(p + ".tmp", "wb") as f:
            f.write(raw)
        os.replace(p + ".tmp", p)
    return True, "put back: " + ", ".join(n for n, _ in put)
