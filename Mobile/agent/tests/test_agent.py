import http.client
import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import claudegg_agent as agent  # noqa: E402

FAKE = os.path.join(os.path.dirname(HERE), "fake_adb.py")
FAKE_VIDEO = os.path.join(os.path.dirname(HERE), "fake_video.py")
FAKE_SYSTEMCTL = os.path.join(os.path.dirname(HERE), "fake_systemctl.py")

#  A gamebot.py for the tests: `gamebot.py chapter <key>` writes the line a real test ends with.
FAKE_GAMEBOT = r"""
import os, signal, sys, time
home = os.path.dirname(os.path.abspath(__file__))
key = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "chapter" else ""
def say(text):
    with open(os.path.join(home, "spin.log"), "a", encoding="utf-8") as handle:
        handle.write(time.strftime("%Y-%m-%d %H:%M:%S") + "  " + text + "\n")
with open(os.path.join(home, "test-calls"), "a", encoding="utf-8") as handle:
    handle.write(" ".join(sys.argv[1:]) + "\n")
if os.environ.get("FAKE_TEST_CRASH"):
    sys.stderr.write("Traceback: no module named cv2\n")
    sys.exit(3)
if os.environ.get("FAKE_TEST_HANG"):
    def stopped(*_):
        say("TEST " + key + ": done - stopped")
        sys.exit(0)
    signal.signal(signal.SIGTERM, stopped)
    say("TEST " + key + ": begins")
    while True:
        time.sleep(0.05)
say("TEST " + key + ": done - all fine")
"""


class Running:
    """The agent on a free port, with the fake adb; `calls()` is what the fake adb was asked."""

    def __init__(self, fail=False, bot=None):
        self.folder = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.folder.name, "adb.log")
        os.environ["FAKE_ADB_LOG"] = self.log
        if fail:
            os.environ["FAKE_ADB_FAIL"] = "1"
        else:
            os.environ.pop("FAKE_ADB_FAIL", None)
        self.token = agent.read_or_make_token(os.path.join(self.folder.name, "token"))
        adb = agent.Adb([sys.executable, FAKE])
        #  The live picture comes from a program that is not a phone either.
        self.video_log = os.path.join(self.folder.name, "video.log")
        os.environ["FAKE_VIDEO_LOG"] = self.video_log
        video = agent.VideoPipeline(adb, None, [sys.executable, FAKE_VIDEO], retry_delay=0.05, idle_seconds=0.3)
        self.phone = agent.Phone(adb, None, video, bot)
        self.server = agent.make_server(self.phone, self.token, "127.0.0.1", 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.phone.video._idle_now()
        os.environ.pop("FAKE_ADB_LOG", None)
        os.environ.pop("FAKE_ADB_FAIL", None)
        for name in ("FAKE_VIDEO_LOG", "FAKE_VIDEO_FRAMES", "FAKE_VIDEO_FAIL", "FAKE_VIDEO_DELAY"):
            os.environ.pop(name, None)
        self.folder.cleanup()

    def video_starts(self):
        try:
            with open(self.video_log, encoding="utf-8") as handle:
                return len(handle.readlines())
        except OSError:
            return 0

    def watch(self, query="", token=""):
        """The live picture: a connection that gives the pictures one after the other."""
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        headers = {} if token is None else {"Authorization": "Bearer " + (self.token if token == "" else token)}
        connection.request("GET", "/v1/video" + query, headers=headers)
        return Watching(connection, connection.getresponse())

    def calls(self):
        try:
            with open(self.log, encoding="utf-8") as handle:
                return [line.rstrip("\n") for line in handle]
        except OSError:
            return []

    def ask(self, method, path, body=None, token="", raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        request = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=data, method=method)
        if token is not None:
            request.add_header("Authorization", "Bearer " + (self.token if token == "" else token))
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=10) as answer:
                return answer.status, answer.read(), dict(answer.headers)
        except urllib.error.HTTPError as error:
            return error.code, error.read(), dict(error.headers)


class Watching:
    """The multipart stream of /v1/video: `next()` is the next picture."""

    def __init__(self, connection, response):
        self.connection = connection
        self.response = response

    def next(self):
        line = self.response.fp.readline()
        while line and line.strip() != b"--frame":
            line = self.response.fp.readline()
        if not line:
            return None
        length = 0
        while True:
            header = self.response.fp.readline().strip()
            if not header:
                break
            if header.lower().startswith(b"content-length:"):
                length = int(header.split(b":")[1])
        data = self.response.fp.read(length)
        return data if len(data) == length else None

    def close(self):
        #  The response holds the socket of a connection that closes at the end of the answer.
        self.response.close()
        self.connection.close()


class AgentTest(unittest.TestCase):
    def setUp(self):
        self.agent = Running()
        self.addCleanup(self.agent.close)

    def json(self, method, path, body=None, **kwargs):
        status, data, _ = self.agent.ask(method, path, body, **kwargs)
        return status, json.loads(data.decode())

    def test_ping_needs_no_token(self):
        status, body = self.json("GET", "/v1/ping", token=None)
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

    def test_the_token_is_needed(self):
        self.assertEqual(self.json("GET", "/v1/info", token=None)[0], 401)
        self.assertEqual(self.json("GET", "/v1/info", token="wrong")[0], 401)
        self.assertEqual(self.json("POST", "/v1/tap", {"x": 1, "y": 1}, token="wrong")[0], 401)
        self.assertEqual(self.agent.calls(), [])

    def test_info_takes_the_override_size(self):
        status, body = self.json("GET", "/v1/info")
        self.assertEqual(status, 200)
        self.assertEqual((body["model"], body["android"], body["width"], body["height"]), ("FakePhone", "14", 1000, 2200))

    def test_screen_is_a_png_without_the_noise(self):
        status, data, headers = self.agent.ask("GET", "/v1/screen")
        self.assertEqual(status, 200)
        self.assertTrue(data.startswith(b"\x89PNG"))
        self.assertEqual(struct.unpack(">II", data[16:24]), (48, 96))
        self.assertEqual((headers["X-Screen-Width"], headers["X-Screen-Height"]), ("48", "96"))
        self.assertEqual(self.agent.calls(), ["exec-out screencap -p"])

    def test_tap_is_a_press(self):
        self.assertEqual(self.json("POST", "/v1/tap", {"x": 300, "y": 400})[0], 200)
        self.assertEqual(self.json("POST", "/v1/tap", {"x": 5, "y": 6, "ms": 80})[0], 200)
        self.assertEqual(self.agent.calls(), ["shell input swipe 300 400 300 400 120", "shell input swipe 5 6 5 6 80"])

    def test_swipe(self):
        self.assertEqual(self.json("POST", "/v1/swipe", {"x1": 1, "y1": 2, "x2": 3, "y2": 4})[0], 200)
        self.assertEqual(self.agent.calls(), ["shell input swipe 1 2 3 4 300"])

    def test_swipes_are_one_command(self):
        status, _ = self.json("POST", "/v1/swipes", {"strokes": [[1, 2, 3, 4, 100], [5, 6, 7, 8, 200]]})
        self.assertEqual(status, 200)
        self.assertEqual(self.agent.calls(), ["shell input swipe 1 2 3 4 100; input swipe 5 6 7 8 200"])

    def test_keys(self):
        self.assertEqual(self.json("POST", "/v1/key", {"key": "back"})[0], 200)
        self.assertEqual(self.json("POST", "/v1/key", {"keycode": 66})[0], 200)
        self.assertEqual(self.json("POST", "/v1/wake", {})[0], 200)
        self.assertEqual(self.agent.calls(), ["shell input keyevent 4", "shell input keyevent 66", "shell input keyevent 224"])

    def test_text_has_no_way_out_to_a_shell(self):
        self.assertEqual(self.json("POST", "/v1/text", {"text": "a b.c"})[0], 200)
        self.assertEqual(self.agent.calls(), ["shell input text a%sb.c"])
        for bad in ("x; reboot", "$(id)", "a`b`", "a|b", "a&b", "a\nb", "é", "'", '"', "a>b"):
            self.assertEqual(self.json("POST", "/v1/text", {"text": bad})[0], 400, bad)
        self.assertEqual(self.json("POST", "/v1/text", {"text": "x" * 201})[0], 400)
        self.assertEqual(len(self.agent.calls()), 1)

    def test_arguments_are_checked(self):
        cases = [
            ("/v1/tap", {"x": "1; reboot", "y": 1}), ("/v1/tap", {"x": 1}), ("/v1/tap", {"x": -1, "y": 1}),
            ("/v1/tap", {"x": 1.5, "y": 1}), ("/v1/tap", {"x": True, "y": 1}), ("/v1/tap", {"x": 1, "y": 1, "ms": 0}),
            ("/v1/tap", {"x": 1, "y": 1, "ms": 99999}), ("/v1/swipe", {"x1": 1, "y1": 1, "x2": 1}),
            ("/v1/swipes", {"strokes": []}), ("/v1/swipes", {"strokes": [[1, 2, 3]]}),
            ("/v1/swipes", {"strokes": [[1, 2, 3, 4, "5"]]}), ("/v1/swipes", {"strokes": [[0, 0, 0, 0, 1]] * 51}),
            ("/v1/key", {"key": "REBOOT"}), ("/v1/key", {"keycode": 301}), ("/v1/key", {}),
        ]
        for path, body in cases:
            self.assertEqual(self.json("POST", path, body)[0], 400, (path, body))
        self.assertEqual(self.agent.calls(), [])

    def test_the_body_is_checked(self):
        self.assertEqual(self.json("POST", "/v1/tap", raw=b"not json")[0], 400)
        self.assertEqual(self.json("POST", "/v1/tap", raw=b"[1, 2]")[0], 400)
        self.assertEqual(self.json("POST", "/v1/tap", raw=b"x" * (agent.MAX_BODY + 1))[0], 413)

    def test_other_things_are_not_there(self):
        self.assertEqual(self.json("GET", "/v1/shell")[0], 404)
        self.assertEqual(self.json("POST", "/v1/info", {})[0], 404)
        self.assertEqual(self.json("DELETE", "/v1/tap")[0], 405)


class VideoTest(unittest.TestCase):
    def setUp(self):
        self.agent = Running()
        self.addCleanup(self.agent.close)

    def test_the_live_picture_is_a_stream_of_jpegs(self):
        watching = self.agent.watch()
        self.addCleanup(watching.close)
        self.assertEqual(watching.response.status, 200)
        self.assertIn("multipart/x-mixed-replace", watching.response.getheader("Content-Type"))
        pictures = [watching.next() for _ in range(4)]
        for picture in pictures:
            self.assertTrue(picture.startswith(b"\xff\xd8") and picture.endswith(b"\xff\xd9"))
        self.assertEqual(len(set(pictures)), 4, "each picture is a new one")
        self.assertEqual(self.agent.video_starts(), 1)

    def test_the_token_and_the_arguments_are_checked(self):
        for token in (None, "wrong"):
            watching = self.agent.watch(token=token)
            self.assertEqual(watching.response.status, 401)
            watching.close()
        for query in ("?fps=0", "?fps=31", "?fps=x", "?width=50", "?width=99999", "?fps=10;reboot"):
            watching = self.agent.watch(query)
            self.assertEqual(watching.response.status, 400, query)
            watching.close()
        self.assertEqual(self.agent.video_starts(), 0, "nothing was started for them")

    def test_one_pipeline_serves_all_who_look(self):
        first = self.agent.watch()
        second = self.agent.watch("?fps=5&width=300")
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        self.assertIsNotNone(first.next())
        self.assertIsNotNone(second.next())
        self.assertIsNotNone(first.next())
        self.assertEqual(self.agent.video_starts(), 1)

    def test_the_pipeline_is_started_again_when_it_ends(self):
        #  screenrecord ends by itself after three minutes: the viewer does not notice.
        os.environ["FAKE_VIDEO_FRAMES"] = "2"
        watching = self.agent.watch()
        self.addCleanup(watching.close)
        pictures = [watching.next() for _ in range(7)]
        self.assertTrue(all(p is not None for p in pictures))
        self.assertGreaterEqual(self.agent.video_starts(), 3)

    def test_a_still_screen_gives_the_last_picture_again(self):
        os.environ["FAKE_VIDEO_FRAMES"] = "1"
        os.environ["FAKE_VIDEO_DELAY"] = "30"       #  after its one picture it says nothing for a long time
        watching = self.agent.watch()
        self.addCleanup(watching.close)
        started = time.time()
        first = watching.next()
        second = watching.next()
        self.assertEqual(first, second)
        self.assertLess(time.time() - started, 5)

    def test_it_stops_when_the_last_viewer_has_gone(self):
        watching = self.agent.watch()
        self.assertIsNotNone(watching.next())
        self.assertTrue(self.agent.phone.video.running)
        watching.close()
        for _ in range(60):
            if not self.agent.phone.video.running:
                break
            time.sleep(0.1)
        self.assertFalse(self.agent.phone.video.running)
        #  and a new viewer starts it again
        again = self.agent.watch()
        self.addCleanup(again.close)
        self.assertIsNotNone(again.next())
        self.assertEqual(self.agent.video_starts(), 2)

    def test_what_went_wrong_is_told(self):
        os.environ["FAKE_VIDEO_FAIL"] = "boom: no encoder"
        watching = self.agent.watch()
        self.addCleanup(watching.close)
        self.assertEqual(watching.response.status, 502)
        self.assertIn("boom: no encoder", json.loads(watching.response.read().decode())["error"])

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed here")
    def test_the_whole_pipeline_with_ffmpeg(self):
        #  screenrecord (as the fake adb makes it) -> ffmpeg -> JPEG, scaled to the width asked for.
        running = Running()
        running.phone.video.command = None
        self.addCleanup(running.close)
        watching = running.watch("?fps=8&width=135")
        self.addCleanup(watching.close)
        pictures = [watching.next() for _ in range(5)]
        self.assertTrue(all(p is not None and p.startswith(b"\xff\xd8") and p.endswith(b"\xff\xd9") for p in pictures))
        #  A JPEG says its size in the SOF0 marker: 135 wide, 240 high.
        data = pictures[0]
        position = data.find(b"\xff\xc0")
        height, width = struct.unpack(">HH", data[position + 5:position + 9])
        self.assertEqual((width, height), (135, 240))
        self.assertTrue(any("screenrecord" in line and "--output-format=h264" in line for line in running.calls()))

    def test_ffmpeg_that_is_not_there_is_told(self):
        adb = agent.Adb([sys.executable, FAKE])
        video = agent.VideoPipeline(adb, None, None, ffmpeg="no-such-ffmpeg-here", retry_delay=0.05)
        video.open(10, 540)
        picture, _, alive = video.first(10)
        self.assertIsNone(picture)
        self.assertFalse(alive)
        self.assertIn("ffmpeg is not installed", video.error)


class BotTest(unittest.TestCase):
    """The Pokemon GO bot: what the agent says of it, and how it starts and stops it (with a systemctl that is not one)."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.home = self.folder.name
        os.environ["FAKE_SYSTEMCTL_STATE"] = os.path.join(self.home, "service-state")
        os.environ["FAKE_SYSTEMCTL_LOG"] = os.path.join(self.home, "service-calls")
        os.environ.pop("FAKE_SYSTEMCTL_FAIL", None)
        self.addCleanup(lambda: [os.environ.pop(name, None) for name in ("FAKE_SYSTEMCTL_STATE", "FAKE_SYSTEMCTL_LOG", "FAKE_SYSTEMCTL_FAIL")])
        command = (sys.executable, FAKE_SYSTEMCTL)
        self.bot = agent.Bot(self.home, command, command, (sys.executable,))
        self.agent = Running(bot=self.bot)
        self.addCleanup(self.agent.close)
        self.addCleanup(self.bot.stop_test)

    def json(self, method, path, body=None, **kwargs):
        status, data, _ = self.agent.ask(method, path, body, **kwargs)
        return status, json.loads(data.decode())

    def install(self):
        with open(os.path.join(self.home, "gamebot.py"), "w", encoding="utf-8") as handle:
            handle.write("# the bot\n")

    def install_with_tests(self):
        """The bot with its real chapters.py, and a gamebot.py that does what a test of the real one does: it
        says how it ended in the log (FAKE_TEST_HANG: it waits to be stopped; FAKE_TEST_CRASH: it ends without
        a word)."""
        shutil.copy(os.path.join(os.path.dirname(os.path.abspath(agent.__file__)), "..", "chapters.py"), self.home)
        with open(os.path.join(self.home, "gamebot.py"), "w", encoding="utf-8") as handle:
            handle.write(FAKE_GAMEBOT)

    def control(self):
        with open(os.path.join(self.home, "gamebot_control.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def service_calls(self):
        try:
            with open(os.environ["FAKE_SYSTEMCTL_LOG"], encoding="utf-8") as handle:
                return [line.strip() for line in handle if not line.startswith("is-active")]
        except OSError:
            return []

    def test_a_pi_without_the_bot_says_so(self):
        status, state = self.json("GET", "/v1/bot")
        self.assertEqual(status, 200)
        self.assertFalse(state["installed"])
        self.assertFalse(state["running"])
        self.assertEqual(state["log"], [])
        #  Not installed: nothing is started.
        status, body = self.json("POST", "/v1/bot/start", {"options": {"spin": True}})
        self.assertEqual(status, 409)
        self.assertIn("not installed", body["error"])
        self.assertEqual(self.service_calls(), [])

    def test_the_state_is_what_the_bot_keeps(self):
        self.install()
        with open(os.path.join(self.home, "gamebot_control.json"), "w", encoding="utf-8") as handle:
            json.dump({"spin": False, "daily_time": "06:45", "throw_target": "great", "battle": True}, handle)
        with open(os.path.join(self.home, "spin.log"), "w", encoding="utf-8") as handle:
            handle.write("".join("2026-11-26 10:00:%02d  line %d\n" % (n % 60, n) for n in range(100)))
        status, state = self.json("GET", "/v1/bot?lines=3")
        self.assertEqual(status, 200)
        self.assertTrue(state["installed"])
        self.assertFalse(state["running"])
        self.assertFalse(state["options"]["spin"])
        self.assertTrue(state["options"]["catch"], "a switch that was never touched is on, as the bot reads it")
        self.assertFalse(state["options"]["curveball"], "but the ones that start unticked are off")
        self.assertTrue(state["options"]["battle"], "the battles of GO Battle League are an option")
        self.assertTrue(state["options"]["battle_give_up"], "giving up a lost battle is on until it is switched off")
        self.assertFalse(state["options"]["teams_weekly"], "the weekly round of the teams is off until it is switched on")
        self.assertEqual((state["battle_app"], state["battle_league"], state["battle_count"]), ("", "Great League", 5))
        self.assertEqual(state["battles"], {"won": 0, "lost": 0, "list": []})
        self.assertFalse(state["test"]["running"])
        self.assertEqual((state["daily_time"], state["throw_target"], state["daily_max_min"]), ("06:45", "great", 480))
        self.assertEqual([line.split("  ")[1] for line in state["log"]], ["line 97", "line 98", "line 99"])
        self.assertEqual(self.json("GET", "/v1/bot?lines=0")[0], 400)
        self.assertEqual(self.json("GET", "/v1/bot?lines=201")[0], 400)
        self.assertEqual(self.json("GET", "/v1/bot?lines=x")[0], 400)

    def test_start_sets_what_is_asked_and_keeps_the_rest(self):
        self.install()
        with open(os.path.join(self.home, "gamebot_control.json"), "w", encoding="utf-8") as handle:
            json.dump({"battle": True, "bag_clean": True}, handle)
        status, _ = self.json("POST", "/v1/bot/start", {
            "options": {"spin": True, "catch": False, "gifts_open": False}, "throw_target": "great",
            "daily_time": "06:30", "daily_max_min": 120,
        })
        self.assertEqual(status, 200)
        control = self.control()
        self.assertEqual(control["spin"], True)
        self.assertEqual(control["catch"], False)
        self.assertEqual(control["throw_target"], "great")
        self.assertEqual(control["daily_time"], "06:30")
        self.assertEqual(control["daily_max_min"], 120)
        self.assertEqual((control["battle"], control["bag_clean"]), (True, True), "what was not asked for stays as it was")
        self.assertEqual(self.service_calls(), ["start spin-stop"])
        self.assertTrue(self.json("GET", "/v1/bot")[1]["running"])
        self.assertFalse(os.path.exists(os.path.join(self.home, "gamebot_force.json")), "no daily run unless it is asked for")
        #  Started while it runs: it begins afresh.
        self.assertEqual(self.json("POST", "/v1/bot/start", {"options": {"spin": False}})[0], 200)
        self.assertEqual(self.service_calls(), ["start spin-stop", "restart spin-stop"])

    def test_the_daily_run_can_begin_at_once(self):
        self.install()
        self.assertEqual(self.json("POST", "/v1/bot/start", {"options": {"daily_cycle": True}, "daily_now": True})[0], 200)
        self.assertTrue(os.path.exists(os.path.join(self.home, "gamebot_force.json")))

    def test_what_is_asked_is_checked_before_anything_is_written(self):
        self.install()
        for body in (
            {"options": {"battle": "yes"}},
            {"options": {"tea_party": True}},                    #  not an option of the bot
            {"battle_app": "com.example.other"},
            {"battle_app": 5},
            {"battle_league": ""},
            {"battle_league": "Great League; rm -rf /"},
            {"battle_league": "x" * 41},
            {"battle_count": 0},
            {"battle_count": 51},
            {"battle_count": "5"},
            {"options": {"spin": "yes"}},
            {"options": {"spin": 1}},
            {"options": ["spin"]},
            {"throw_target": "perfect"},
            {"daily_time": "25:00"},
            {"daily_time": "8:00"},
            {"daily_time": 800},
            {"daily_max_min": 3},
            {"daily_max_min": 2000},
            {"daily_max_min": "60"},
        ):
            status, answer = self.json("POST", "/v1/bot/start", body)
            self.assertEqual(status, 400, body)
            self.assertIn("error", answer)
        self.assertFalse(os.path.exists(os.path.join(self.home, "gamebot_control.json")))
        self.assertEqual(self.service_calls(), [])

    def test_the_battles_of_today_are_counted_from_the_log(self):
        self.install()
        today = time.strftime("%Y-%m-%d")
        yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
        with open(os.path.join(self.home, "spin.log"), "w", encoding="utf-8") as handle:
            handle.write(yesterday + " 21:00:00  battle: battle 1 done: win\n")
            handle.write(today + " 09:00:00  battle: 3 battle(s) in 'Great League' with A, B, C\n")
            handle.write(today + " 09:05:10  battle: battle 1 done: win\n")
            handle.write(today + " 09:11:40  battle: battle 2 done: loss (given up)\n")
            handle.write(today + " 09:19:02  battle: battle 3 done: loss\n")
            handle.write(today + " 09:20:00  nothing to do with it\n")
        battles = self.json("GET", "/v1/bot")[1]["battles"]
        self.assertEqual((battles["won"], battles["lost"]), (1, 2))
        self.assertEqual([(b["time"], b["league"], b["result"], b["gave_up"]) for b in battles["list"]],
                         [("09:05", "Great League", "win", False), ("09:11", "Great League", "loss", True),
                          ("09:19", "Great League", "loss", False)])
        #  'Reset' in the bot's web interface: counted from that moment on.
        with open(os.path.join(self.home, "battle_count_reset.json"), "w", encoding="utf-8") as handle:
            json.dump({"at": today + " 09:10:00"}, handle)
        battles = self.json("GET", "/v1/bot")[1]["battles"]
        self.assertEqual((battles["won"], battles["lost"]), (0, 2))

    def test_the_battle_settings_are_written(self):
        self.install()
        status, _ = self.json("POST", "/v1/bot/start", {
            "options": {"battle": True, "battle_give_up": False, "teams_weekly": True},
            "battle_app": "com.nianticlabs.pokemongo.ares", "battle_league": " Ultra League ", "battle_count": 12,
        })
        self.assertEqual(status, 200)
        control = self.control()
        self.assertEqual((control["battle"], control["battle_give_up"], control["teams_weekly"]), (True, False, True))
        self.assertEqual((control["battle_app"], control["battle_league"], control["battle_count"]),
                         ("com.nianticlabs.pokemongo.ares", "Ultra League", 12))
        state = self.json("GET", "/v1/bot")[1]
        self.assertEqual((state["battle_league"], state["battle_count"]), ("Ultra League", 12))

    def test_the_tests_of_the_bot_are_listed(self):
        self.assertEqual(self.json("GET", "/v1/bot/tests")[1]["tests"], [], "no chapters.py: no tests")
        self.install_with_tests()
        tests = self.json("GET", "/v1/bot/tests")[1]["tests"]
        keys = [test["key"] for test in tests]
        for key in ("screen", "battle_set", "battle_one", "refresh", "scan_new", "rocket", "bag", "storage"):
            self.assertIn(key, keys)
        self.assertTrue(all(test["title"] and test["group"] for test in tests))

    def wait_for_test(self, running):
        until = time.time() + 15
        while time.time() < until:
            test = self.json("GET", "/v1/bot")[1]["test"]
            if test["running"] == running:
                return test
            time.sleep(0.05)
        self.fail("the test did not %s" % ("start" if running else "end"))

    def test_a_part_of_the_bot_runs_on_its_own(self):
        self.install_with_tests()
        os.environ["FAKE_SYSTEMCTL_STATE"] = os.path.join(self.home, "service-state")
        self.assertEqual(self.json("POST", "/v1/bot/start", {})[0], 200)        #  the bot runs...
        self.assertTrue(self.json("GET", "/v1/bot")[1]["running"])
        status, _ = self.json("POST", "/v1/bot/test", {
            "key": "battle_set", "options": {"battle": True, "spin": False}, "battle_league": "Great League", "battle_count": 3,
        })
        self.assertEqual(status, 200)
        test = self.wait_for_test(False)
        self.assertEqual((test["key"], test["ok"], test["result"]), ("battle_set", True, "all fine"))
        self.assertTrue(test["title"])
        self.assertEqual(self.service_calls()[-1], "stop spin-stop", "...and is stopped for the test")
        self.assertFalse(self.json("GET", "/v1/bot")[1]["running"])
        control = self.control()
        self.assertEqual((control["battle"], control["spin"], control["battle_count"]), (True, False, 3))
        with open(os.path.join(self.home, "test-calls"), encoding="utf-8") as handle:
            self.assertEqual(handle.read().split("\n")[:-1], ["chapter battle_set"])

    def test_a_test_that_dies_says_what_it_said(self):
        self.install_with_tests()
        os.environ["FAKE_TEST_CRASH"] = "1"
        self.addCleanup(lambda: os.environ.pop("FAKE_TEST_CRASH", None))
        self.assertEqual(self.json("POST", "/v1/bot/test", {"key": "screen"})[0], 200)
        test = self.wait_for_test(False)
        self.assertFalse(test["ok"])
        self.assertIn("ended without a result (exit code 3)", test["result"])
        self.assertIn("no module named cv2", test["result"])

    def test_a_test_can_be_stopped_and_keeps_the_bot_off(self):
        self.install_with_tests()
        os.environ["FAKE_TEST_HANG"] = "1"
        self.addCleanup(lambda: os.environ.pop("FAKE_TEST_HANG", None))
        self.assertEqual(self.json("POST", "/v1/bot/test", {"key": "scan"})[0], 200)
        self.assertTrue(self.wait_for_test(True)["running"])
        #  While it runs, no second one and no bot: they would fight over the phone.
        status, answer = self.json("POST", "/v1/bot/test", {"key": "screen"})
        self.assertEqual(status, 409)
        self.assertIn("running already", answer["error"])
        status, answer = self.json("POST", "/v1/bot/start", {})
        self.assertEqual(status, 409)
        self.assertIn("stop it first", answer["error"])
        self.assertEqual(self.json("POST", "/v1/bot/test/stop")[0], 200)
        test = self.wait_for_test(False)
        self.assertEqual(test["key"], "scan")
        if os.name == "posix":
            self.assertEqual((test["ok"], test["result"]), (True, "stopped"), "it says so before it goes")
        else:
            self.assertFalse(test["ok"], "on Windows it is ended at once, without a word")
        self.assertEqual(self.json("POST", "/v1/bot/start", {})[0], 200)

    def test_stop_also_ends_a_test(self):
        self.install_with_tests()
        os.environ["FAKE_TEST_HANG"] = "1"
        self.addCleanup(lambda: os.environ.pop("FAKE_TEST_HANG", None))
        self.json("POST", "/v1/bot/test", {"key": "scan_new"})
        self.wait_for_test(True)
        self.assertEqual(self.json("POST", "/v1/bot/stop")[0], 200)
        self.assertFalse(self.json("GET", "/v1/bot")[1]["test"]["running"])

    def test_a_test_is_checked_before_anything_happens(self):
        self.install_with_tests()
        for body in ({}, {"key": 5}, {"key": "Screen"}, {"key": "screen; ls"}, {"key": "no_such_test"},
                     {"key": "screen", "battle_count": 99}, {"key": "screen", "options": {"nope": True}}):
            status, answer = self.json("POST", "/v1/bot/test", body)
            self.assertEqual(status, 400, body)
            self.assertIn("error", answer)
        self.assertFalse(os.path.exists(os.path.join(self.home, "test-calls")))
        self.assertFalse(os.path.exists(os.path.join(self.home, "gamebot_control.json")))
        self.assertEqual(self.service_calls(), [])
        #  Not installed, or an old bot without chapters.py.
        self.assertEqual(self.json("POST", "/v1/bot/test", {"key": "screen"}, token="wrong")[0], 401)
        os.remove(os.path.join(self.home, "chapters.py"))
        status, answer = self.json("POST", "/v1/bot/test", {"key": "screen"})
        self.assertEqual(status, 409)
        self.assertIn("chapters.py", answer["error"])
        os.remove(os.path.join(self.home, "gamebot.py"))
        self.assertEqual(self.json("POST", "/v1/bot/test", {"key": "screen"})[0], 409)

    def test_stop(self):
        self.install()
        self.json("POST", "/v1/bot/start", {})
        self.assertTrue(self.json("GET", "/v1/bot")[1]["running"])
        self.assertEqual(self.json("POST", "/v1/bot/stop")[0], 200)
        self.assertFalse(self.json("GET", "/v1/bot")[1]["running"])
        self.assertEqual(self.service_calls(), ["start spin-stop", "stop spin-stop"])

    def test_a_service_that_cannot_be_started_is_told_as_it_is(self):
        self.install()
        os.environ["FAKE_SYSTEMCTL_FAIL"] = "1"
        status, answer = self.json("POST", "/v1/bot/start", {})
        self.assertEqual(status, 502)
        self.assertIn("sudoers", answer["error"])
        self.assertEqual(self.json("POST", "/v1/bot/stop")[0], 502)

    def test_the_token_is_needed(self):
        self.assertEqual(self.json("GET", "/v1/bot", token=None)[0], 401)
        self.assertEqual(self.json("POST", "/v1/bot/start", {}, token="wrong")[0], 401)
        self.assertEqual(self.json("POST", "/v1/bot/stop", token=None)[0], 401)


class AgentFailTest(unittest.TestCase):
    def test_a_phone_that_is_off_is_told_as_it_is(self):
        running = Running(fail=True)
        self.addCleanup(running.close)
        status, data, _ = running.ask("GET", "/v1/screen")
        self.assertEqual(status, 502)
        self.assertIn("device offline", json.loads(data.decode())["error"])
        status, data, _ = running.ask("POST", "/v1/tap", {"x": 1, "y": 1})
        self.assertEqual(status, 502)


class TokenTest(unittest.TestCase):
    def test_the_token_is_made_once_and_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "sub", "token")
            first = agent.read_or_make_token(path)
            self.assertGreaterEqual(len(first), 32)
            self.assertEqual(agent.read_or_make_token(path), first)
            if os.name == "posix":
                self.assertEqual(os.stat(path).st_mode & 0o077, 0)


class ArgumentTest(unittest.TestCase):
    def test_a_display_is_asked_for(self):
        calls = []

        class Recording(agent.Adb):
            def run(self, *args, binary=False):
                calls.append(" ".join(str(a) for a in args))
                return b"\x89PNG\r\n\x1a\n" if binary else ""

        agent.Phone(Recording(), display="4").screen()
        self.assertEqual(calls, ["exec-out screencap -d 4 -p"])


if __name__ == "__main__":
    unittest.main()
