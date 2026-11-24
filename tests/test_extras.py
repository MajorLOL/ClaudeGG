"""Looking after the bot (extras.py): the update from GitHub, the history of the days, the warnings to the phone
(ntfy, replaced by a fake here), the backup - and the pause when it gets hot (gamebot.heat_wait).
Run: python3 -m unittest discover -s tests"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import extras as X  # noqa: E402

try:
    import gamebot as G
except Exception:  # noqa: BLE001
    G = None


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True,
                   capture_output=True)


class Update(unittest.TestCase):
    def setUp(self):
        self.saved = dict(X.update)
        d = tempfile.mkdtemp()
        self.origin, self.clone = os.path.join(d, "origin"), os.path.join(d, "clone")
        os.makedirs(self.origin)
        git(self.origin, "init", "-q", "-b", "main")
        with open(os.path.join(self.origin, "a.txt"), "w") as f:
            f.write("1\n")
        git(self.origin, "add", "a.txt")
        git(self.origin, "commit", "-qm", "first")
        subprocess.run(["git", "clone", "-q", self.origin, self.clone], check=True, capture_output=True)
        with open(os.path.join(self.clone, "install.sh"), "w"):
            pass

    def tearDown(self):
        X.update.clear()
        X.update.update(self.saved)

    def test_a_new_version_is_seen_and_installed(self):
        self.assertEqual(X.update_check(self.clone, force=True)["behind"], 0)
        with open(os.path.join(self.origin, "a.txt"), "w") as f:
            f.write("2\n")
        git(self.origin, "commit", "-qam", "Battles: a better switch")
        u = X.update_check(self.clone, force=True)
        self.assertEqual((u["behind"], u["subjects"], u["error"]), (1, ["Battles: a better switch"], ""))
        restarted, logs = [], []
        saved_log = X.UPDATE_LOG
        X.UPDATE_LOG = os.path.join(self.clone, "..", "update.log")
        try:
            self.assertTrue(X.update_run(self.clone, lambda: restarted.append("bot"), lambda: restarted.append("web"),
                                         logs.append, install=("true",)))
            t_end = time.time() + 10
            while len(restarted) < 2 and time.time() < t_end:
                time.sleep(0.05)
        finally:
            X.UPDATE_LOG = saved_log
        self.assertEqual(restarted, ["bot", "web"])
        with open(os.path.join(self.clone, "a.txt")) as f:
            self.assertEqual(f.read(), "2\n")
        self.assertTrue(logs[0].startswith("update: "), logs)

    def test_a_failing_install_restarts_nothing(self):
        restarted, logs = [], []
        saved_log = X.UPDATE_LOG
        X.UPDATE_LOG = os.path.join(self.clone, "..", "update.log")
        try:
            X.update_run(self.clone, lambda: restarted.append(1), lambda: restarted.append(2), logs.append,
                         install=("false",))
            t_end = time.time() + 10
            while X.update["running"] and time.time() < t_end:
                time.sleep(0.05)
        finally:
            X.UPDATE_LOG = saved_log
        self.assertEqual(restarted, [])
        self.assertIn("failed", X.update["result"])


class History(unittest.TestCase):
    def test_days_are_kept_and_read_back(self):
        path = os.path.join(tempfile.mkdtemp(), "h.json")
        X.history_record("2026-11-23", {"caught": 5, "stops": 2}, path)
        X.history_record("2026-11-24", {"caught": 7, "fled": 1, "stops": 3, "won": 2, "lost": 1}, path)
        X.history_record("2026-11-24", {"caught": 8, "fled": 1, "stops": 3, "won": 2, "lost": 1}, path)
        h = X.history_read(30, path)
        self.assertEqual([d["day"] for d in h], ["2026-11-23", "2026-11-24"])
        self.assertEqual(h[1], {"day": "2026-11-24", "caught": 8, "fled": 1, "stops": 3, "won": 2, "lost": 1})
        self.assertEqual(h[0]["won"], 0)
        self.assertEqual(X.history_read(1, path)[0]["day"], "2026-11-24")
        self.assertEqual(X.history_read(30, path + ".none"), [])


class Alerts(unittest.TestCase):
    def setUp(self):
        X.alerts["sent"].clear()
        self.sent = []

    def send(self, topic, title, text, priority="default"):
        self.sent.append(title)
        return ""

    def test_warnings_go_out_once_an_hour(self):
        state = {"adb_ok": False, "level": 12, "charging": False, "phone_c": 44.0, "pi_c": 60.0,
                 "bot_running": True, "log_age": 25 * 60, "summary": ("2026-11-24 10:00:00", "Today: 5 caught")}
        out = X.watch_once("gamebot-test-1", state, now=1000.0, send=self.send)
        self.assertEqual(out, ["adb", "battery", "heat_phone", "quiet", "summary:2026-11-24 10:00:00"])
        self.assertEqual(X.watch_once("gamebot-test-1", state, now=1100.0, send=self.send), [])
        self.assertEqual(X.watch_once("gamebot-test-1", dict(state, summary=None), now=1000.0 + X.ALERT_AGAIN + 1,
                                      send=self.send), ["adb", "battery", "heat_phone", "quiet"])

    def test_nothing_without_a_topic_or_when_all_is_well(self):
        self.assertEqual(X.watch_once("", {"adb_ok": False}, send=self.send), [])
        ok = {"adb_ok": True, "level": 80, "charging": False, "phone_c": 33, "pi_c": 55, "bot_running": True,
              "log_age": 30, "summary": None}
        self.assertEqual(X.watch_once("gamebot-test-1", ok, send=self.send), [])
        self.assertEqual(self.sent, [])

    def test_a_charging_phone_is_not_low(self):
        out = X.watch_once("gamebot-test-1", {"level": 9, "charging": True}, send=self.send)
        self.assertEqual(out, [])

    def test_topic_and_message(self):
        self.assertIn("no valid topic", X.ntfy_send("a b", "t", "x"))
        got = {}

        def opener(req, timeout=0):
            got.update(url=req.full_url, data=req.data, title=req.headers.get("Title"))
            return io.BytesIO(b"{}")
        self.assertEqual(X.ntfy_send("gamebot-test-1", "Battery low", "12 %", opener=opener), "")
        self.assertEqual((got["url"], got["data"], got["title"]),
                         ("https://ntfy.sh/gamebot-test-1", b"12 %", "Battery low"))

    def test_battery(self):
        text = "  AC powered: false\n  USB powered: true\n  status: 2\n  level: 81\n  temperature: 312\n"
        self.assertEqual(X.battery(text), (81, True, 31.2))
        self.assertEqual(X.battery("  level: 40\n  status: 3\n  USB powered: false\n"), (40, False, None))


class Backup(unittest.TestCase):
    def test_backup_and_back(self):
        home, other = tempfile.mkdtemp(), tempfile.mkdtemp()
        with open(os.path.join(home, "battle_seen.json"), "w") as f:
            json.dump({"whiscash": {"MUD_BOMB": 2}}, f)
        with open(os.path.join(home, "gamebot_control.json"), "w") as f:
            json.dump({"catch": True}, f)
        with open(os.path.join(home, ".gamebot_web_password"), "w") as f:
            f.write("secret")
        data = X.backup_zip(home)
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        self.assertIn("battle_seen.json", names)
        self.assertNotIn(".gamebot_web_password", names)
        ok, msg = X.backup_restore(data, other)
        self.assertTrue(ok, msg)
        with open(os.path.join(other, "battle_seen.json")) as f:
            self.assertEqual(json.load(f), {"whiscash": {"MUD_BOMB": 2}})

    def test_a_bad_backup_puts_nothing_back(self):
        other = tempfile.mkdtemp()
        self.assertEqual(X.backup_restore(b"not a zip", other)[0], False)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("battle_seen.json", "{}")
            z.writestr("gamebot_control.json", "{broken")
            z.writestr("../evil.json", "{}")
        ok, msg = X.backup_restore(buf.getvalue(), other)
        self.assertFalse(ok)
        self.assertIn("gamebot_control.json is not valid JSON", msg)
        self.assertEqual(os.listdir(other), [])


@unittest.skipIf(G is None, "gamebot cannot be imported here")
class Heat(unittest.TestCase):
    def setUp(self):
        self.saved = (G.read_heat, G.setting, G.log, dict(G.heat), G.time)
        self.temps = [(44.0, 60.0)]
        self.now = [1000.0]
        self.logs = []
        G.read_heat = lambda: self.temps[0]
        G.setting = lambda key, default=None: default
        G.log = self.logs.append

        class Clock:
            @staticmethod
            def time():
                return self.now[0]
        G.time = Clock
        G.heat.update(t=0.0, since=None)

    def tearDown(self):
        G.read_heat, G.setting, G.log, heat, G.time = self.saved
        G.heat.clear()
        G.heat.update(heat)

    def test_a_hot_phone_pauses_until_it_has_cooled_down(self):
        self.assertEqual(G.heat_wait(), 30)
        self.assertIn("the phone's battery is 44 °C", self.logs[-1])
        self.now[0] += 31
        self.temps[0] = (41.0, 60.0)                  # (cooler, not cool enough: 39)
        self.assertEqual(G.heat_wait(), 30)
        self.now[0] += 31
        self.temps[0] = (38.5, 60.0)
        self.assertEqual(G.heat_wait(), 0)
        self.assertIn("heat: going on after 1 min", self.logs[-1])

    def test_cool_enough_is_no_pause(self):
        self.temps[0] = (36.0, 65.0)
        self.assertEqual(G.heat_wait(), 0)
        self.assertEqual(self.logs, [])

    def test_never_longer_than_the_longest_pause(self):
        G.heat_wait()
        self.now[0] += G.HEAT_MAX_PAUSE + 31
        self.assertEqual(G.heat_wait(), 0)
        self.assertIn("still warm", self.logs[-1])


if __name__ == "__main__":
    unittest.main()
