import base64
import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
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

GAME = "com.nianticlabs.pokemongo"
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
        adb.session = agent.ShellSession(adb)
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
        self.phone._end_launch()
        self.phone.adb.session.close()
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

    def test_ping_and_info_say_what_this_agent_can_do(self):
        for path in ("/v1/ping", "/v1/info"):
            status, body = self.json("GET", path)
            self.assertEqual(status, 200)
            self.assertEqual(body["version"], agent.VERSION)
            for feature in ("tap_kind", "app", "bot_file", "touch"):
                self.assertIn(feature, body["features"], "Claude GG asks for %s before it plays itself" % feature)

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

    def test_other_kinds_of_tap(self):
        self.assertEqual(self.json("POST", "/v1/tap", {"x": 7, "y": 8, "kind": "tap"})[0], 200)
        self.assertEqual(self.json("POST", "/v1/tap", {"x": 9, "y": 10, "ms": 80, "kind": "motion"})[0], 200)
        self.assertEqual(self.json("POST", "/v1/tap", {"x": 11, "y": 12, "kind": "press"})[0], 200)
        self.assertEqual(self.agent.calls(), ["shell input tap 7 8",
                                              "shell input motionevent DOWN 9 10; sleep 0.08; input motionevent UP 9 10",
                                              "shell input swipe 11 12 11 12 120"])
        before = len(self.agent.calls())
        self.assertEqual(self.json("POST", "/v1/tap", {"x": 1, "y": 2, "kind": "rm -rf"})[0], 400)
        self.assertEqual(self.json("POST", "/v1/tap", {"x": 1, "y": 2, "kind": 5})[0], 400)
        self.assertEqual(len(self.agent.calls()), before)                   # (a wrong kind reaches no phone)

    def test_swipe(self):
        self.assertEqual(self.json("POST", "/v1/swipe", {"x1": 1, "y1": 2, "x2": 3, "y2": 4})[0], 200)
        self.assertEqual(self.agent.calls(), ["shell input swipe 1 2 3 4 300"])

    def test_swipes_are_one_command(self):
        status, _ = self.json("POST", "/v1/swipes", {"strokes": [[1, 2, 3, 4, 100], [5, 6, 7, 8, 200]]})
        self.assertEqual(status, 200)
        self.assertEqual(self.agent.calls(), ["shell input swipe 1 2 3 4 100; input swipe 5 6 7 8 200"])

    def test_touch_events_are_one_command(self):
        status, body = self.json("POST", "/v1/touch", {"events": [["DOWN", 10, 20], ["MOVE", 11, 22], ["UP", 12, 400]]})
        self.assertEqual(status, 200)
        self.assertIn("out", body)
        self.assertEqual(self.agent.calls(),
                         ["shell { input motionevent DOWN 10 20; input motionevent MOVE 11 22; input motionevent UP 12 400; } 2>&1"])

    def test_touch_events_are_checked(self):
        for bad in ([], [["PRESS", 1, 2]], [["DOWN", 1]], [["DOWN", -1, 2]], [["DOWN", 1.5, 2]], [["DOWN", "1; reboot", 2]],
                    [["DOWN", 1, 2]] * (agent.MAX_TOUCHES + 1), "DOWN 1 2", [("DOWN", 1, 2, 3)]):
            self.assertEqual(self.json("POST", "/v1/touch", {"events": bad})[0], 400, bad)
        self.assertEqual(self.agent.calls(), [])

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

    def wait_for_state(self, running, timeout=10.0):
        """The state of the start of the game (/v1/app) once it is (not) running."""
        end = time.time() + timeout
        while True:
            status, body = self.json("POST", "/v1/app", {"action": "state", "package": GAME})
            self.assertEqual(status, 200)
            if body["running"] == running or time.time() > end:
                return body
            time.sleep(0.05)

    def test_the_game_is_closed_and_started(self):
        self.assertEqual(self.json("POST", "/v1/app", {"action": "stop", "package": GAME})[0], 200)
        status, body = self.json("POST", "/v1/app", {"action": "start", "package": GAME})
        self.assertEqual((status, body), (200, {"ok": True}))
        state = self.wait_for_state(False)
        self.assertEqual(state, {"ok": True, "running": False, "code": 0, "error": ""})
        self.assertEqual(self.agent.calls(), ["shell am force-stop " + GAME,
                                              "shell monkey -p " + GAME + " -c android.intent.category.LAUNCHER 1"])
        #  (the other store's app, too)
        self.assertEqual(self.json("POST", "/v1/app", {"action": "stop", "package": GAME + ".ares"})[0], 200)
        self.assertEqual(self.agent.calls()[-1], "shell am force-stop " + GAME + ".ares")

    def test_a_game_that_does_not_start_says_what_monkey_said(self):
        os.environ["FAKE_MONKEY_FAIL"] = "** No activities found to run, monkey aborted."
        self.addCleanup(os.environ.pop, "FAKE_MONKEY_FAIL", None)
        self.assertEqual(self.json("POST", "/v1/app", {"action": "start", "package": GAME})[0], 200)
        state = self.wait_for_state(False)
        self.assertEqual((state["running"], state["code"]), (False, 1))
        self.assertIn("No activities found", state["error"])
        #  (asked again: the same)
        self.assertEqual(self.json("POST", "/v1/app", {"action": "state", "package": GAME})[1]["code"], 1)

    def test_the_start_is_not_waited_for(self):
        os.environ["FAKE_MONKEY_HANG"] = "30"                  # monkey does not come back while the game starts
        self.addCleanup(os.environ.pop, "FAKE_MONKEY_HANG", None)
        began = time.time()
        self.assertEqual(self.json("POST", "/v1/app", {"action": "start", "package": GAME})[0], 200)
        self.assertLess(time.time() - began, 5)
        state = self.json("POST", "/v1/app", {"action": "state", "package": GAME})[1]
        self.assertEqual((state["running"], state["code"], state["error"]), (True, 0, ""))
        #  the command is let go of (it is killed; the game itself goes on) and there is nothing to ask about any more
        self.assertEqual(self.json("POST", "/v1/app", {"action": "end", "package": GAME})[0], 200)
        self.assertEqual(self.json("POST", "/v1/app", {"action": "state", "package": GAME})[0], 409)
        self.assertEqual(self.json("POST", "/v1/app", {"action": "end", "package": GAME})[0], 200)
        #  a new start lets go of the one that still runs
        self.assertEqual(self.json("POST", "/v1/app", {"action": "start", "package": GAME})[0], 200)
        self.assertEqual(self.json("POST", "/v1/app", {"action": "start", "package": GAME})[0], 200)
        self.assertEqual(self.json("POST", "/v1/app", {"action": "end", "package": GAME})[0], 200)

    def test_nothing_was_started(self):
        self.assertEqual(self.json("POST", "/v1/app", {"action": "state", "package": GAME})[0], 409)

    def test_only_pokemon_go_can_be_closed_and_started(self):
        for body in ({"action": "stop", "package": "com.android.settings"}, {"action": "stop", "package": "com.nianticlabs.pokemongo; reboot"},
                     {"action": "stop", "package": "com.nianticlabs.pokemongo$(id)"}, {"action": "stop", "package": "com.nianticlabs.pokemon"},
                     {"action": "stop", "package": ""}, {"action": "stop", "package": 5}, {"action": "stop"},
                     {"action": "start", "package": "-p"}, {"action": "start", "package": "x" * 100},
                     {"action": "reboot", "package": GAME}, {"package": GAME}, {"action": 1, "package": GAME}):
            self.assertEqual(self.json("POST", "/v1/app", body)[0], 400, body)
        self.assertEqual(self.agent.calls(), [])
        self.assertEqual(self.json("POST", "/v1/app", {"action": "stop", "package": GAME}, token="wrong")[0], 401)
        self.assertEqual(self.json("GET", "/v1/app")[0], 404)

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

    def test_the_status_page_is_served_without_a_token(self):
        for path in ("/", "/status", "/status?x=1"):
            status, data, headers = self.agent.ask("GET", path, token=None)
            self.assertEqual(status, 200, path)
            self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
            self.assertTrue(data.startswith(b"<!DOCTYPE html>"))
            self.assertNotIn(self.agent.token.encode(), data, "the page holds nothing secret")
        #  What it reads is as closed as before: the page is open, the phone and the bot are not.
        for path in ("/v1/info", "/v1/screen", "/v1/bot", "/v1/bot/tests"):
            self.assertEqual(self.agent.ask("GET", path, token=None)[0], 401, path)
        self.assertEqual(self.agent.calls(), [])
        self.assertEqual(self.json("POST", "/", {})[0], 404)

    def test_the_status_page_runs_nothing_but_itself(self):
        status, data, headers = self.agent.ask("GET", "/", token=None)
        html = data.decode("utf-8")
        policy = headers["Content-Security-Policy"]
        #  The policy names the hash of the one script and the one style the page has: nothing else may run.
        for tag, directive in (("script", "script-src"), ("style", "style-src")):
            parts = re.findall(r"<%s>(.*?)</%s>" % (tag, tag), html, re.S)
            self.assertEqual(len(parts), 1, tag)
            digest = base64.b64encode(hashlib.sha256(parts[0].encode("utf-8")).digest()).decode("ascii")
            self.assertIn("%s 'sha256-%s'" % (directive, digest), policy)
        self.assertIn("default-src 'none'", policy)
        self.assertIn("connect-src 'self'", policy)
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertNotIn("unsafe", policy)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        #  No address of anywhere else, no markup made from what the agent says, no handler in an attribute.
        self.assertNotRegex(html, r"https?://|//[a-z]")
        self.assertNotRegex(html, r"\son[a-z]+\s*=")
        self.assertNotRegex(html, r"style\s*=\s*[\"']")
        for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "localStorage"):
            self.assertNotIn(forbidden, html, forbidden)
        #  It asks for the token with the one header the agent wants, and sends it nowhere else.
        self.assertIn('"Authorization": "Bearer " + token', html)
        self.assertEqual(html.count("fetch("), 1)

    def test_the_status_page_script_is_valid_javascript(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        script = re.search(r"<script>(.*?)</script>", agent.STATUS_HTML, re.S).group(1)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "page.js")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(script)
            done = subprocess.run([node, "--check", path], capture_output=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr.decode(errors="ignore"))

    def test_every_answer_says_what_it_is(self):
        for path in ("/v1/ping", "/v1/bot/tests", "/nothing"):
            self.assertEqual(self.agent.ask("GET", path)[2]["X-Content-Type-Options"], "nosniff", path)

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
        self.assertEqual(state["today"], {"caught": 0, "fled": 0, "stops": 0, "won": 0, "lost": 0, "day": time.strftime("%Y-%m-%d")})
        self.assertFalse(state["test"]["running"])
        self.assertEqual((state["daily_time"], state["throw_target"], state["daily_max_min"]), ("06:45", "great", 480))
        self.assertEqual([line.split("  ")[1] for line in state["log"]], ["line 97", "line 98", "line 99"])
        self.assertEqual(self.json("GET", "/v1/bot?lines=0")[0], 400)
        self.assertEqual(self.json("GET", "/v1/bot?lines=201")[0], 400)
        self.assertEqual(self.json("GET", "/v1/bot?lines=x")[0], 400)

    def test_the_files_of_the_battles_can_be_read_and_nothing_else(self):
        team = b'[{"species": "Noctowl"}]'
        with open(os.path.join(self.home, "battle_team.json"), "wb") as handle:
            handle.write(team)
        with open(os.path.join(self.home, "gamebot_control.json"), "w", encoding="utf-8") as handle:
            handle.write("{}")
        status, data, _ = self.agent.ask("GET", "/v1/bot/file?name=battle_team.json")
        self.assertEqual((status, data), (200, team))
        self.assertEqual(self.json("GET", "/v1/bot/file?name=battle_seen.json")[0], 404, "a file that is not there")
        for name in ("gamebot_control.json", "../.ssh/id_rsa", "", "battle_team.json/.."):
            self.assertEqual(self.json("GET", "/v1/bot/file?name=" + name)[0], 400, name)
        self.assertEqual(self.json("GET", "/v1/bot/file?name=battle_team.json", token=None)[0], 401)

    def write_log(self, *lines):
        with open(os.path.join(self.home, "spin.log"), "w", encoding="utf-8") as handle:
            handle.write("".join(line + "\n" for line in lines))

    def test_the_counters_of_today_are_the_last_ones_the_bot_wrote(self):
        today = time.strftime("%Y-%m-%d")
        self.install()
        self.write_log(
            "2020-01-01 10:00:00  Pokémon CAUGHT (today: 50 caught, 1 fled, 9 stops)",
            today + " 09:00:00  Pokémon CAUGHT (today: 1 caught, 0 fled, 0 stops)",
            today + " 09:30:00  spun a stop (today: 6 caught, 2 fled, 30 stops)",
            today + " 10:00:00  battle: battle 2 done: win (today: 6 caught, 2 fled, 31 stops, 2 won, 1 lost)",
            today + " 10:05:00  nothing was counted on this line",
            "a line of a crash, with no date",
        )
        self.assertEqual(self.json("GET", "/v1/bot")[1]["today"],
                         {"caught": 6, "fled": 2, "stops": 31, "won": 2, "lost": 1, "day": today})

    def test_the_counters_of_today_begin_at_nothing(self):
        today = time.strftime("%Y-%m-%d")
        nothing = {"caught": 0, "fled": 0, "stops": 0, "won": 0, "lost": 0, "day": today}
        self.install()
        #  No log, a log of an older day, an empty log: nothing is counted yet, and the agent says so.
        self.assertEqual(self.json("GET", "/v1/bot")[1]["today"], nothing)
        self.write_log("2020-01-01 10:00:00  Pokémon CAUGHT (today: 50 caught, 1 fled, 9 stops)")
        self.assertEqual(self.json("GET", "/v1/bot")[1]["today"], nothing)
        self.write_log()
        self.assertEqual(self.json("GET", "/v1/bot")[1]["today"], nothing)
        #  A counter the agent does not know is left out, and the known ones before it still count.
        self.write_log(today + " 08:00:00  x (today: 3 caught, 7 eggs, 4 stops)")
        self.assertEqual(self.json("GET", "/v1/bot")[1]["today"], dict(nothing, caught=3, stops=4))

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


class ShellSessionTest(unittest.TestCase):
    """The taps go through one `adb shell` that stays open: no new adb for every tap."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.folder.name, "adb.log")
        self.off = os.path.join(self.folder.name, "off")
        os.environ["FAKE_ADB_LOG"] = self.log
        os.environ["FAKE_ADB_FAIL_FILE"] = self.off
        os.environ.pop("FAKE_ADB_FAIL", None)
        self.adb = agent.Adb([sys.executable, FAKE])
        self.adb.session = agent.ShellSession(self.adb, timeout=10)

    def tearDown(self):
        self.adb.session.close()
        for name in ("FAKE_ADB_LOG", "FAKE_ADB_FAIL_FILE", "FAKE_SHELL_FAIL"):
            os.environ.pop(name, None)
        self.folder.cleanup()

    def calls(self):
        with open(self.log, encoding="utf-8") as handle:
            return [line.rstrip("\n") for line in handle]

    def test_one_shell_for_many_commands(self):
        self.adb.quick("input", "keyevent", 4)
        first = self.adb.session.process
        self.adb.quick("input", "swipe", 1, 2, 3, 4, 100)
        self.adb.quick("input swipe 1 2 3 4 100; input swipe 5 6 7 8 200")
        self.assertIs(self.adb.session.process, first, "the same shell every time")
        self.assertEqual(self.calls(), ["shell input keyevent 4", "shell input swipe 1 2 3 4 100",
                                        "shell input swipe 1 2 3 4 100; input swipe 5 6 7 8 200"])

    def test_a_command_that_fails_is_an_error(self):
        os.environ["FAKE_SHELL_FAIL"] = "input keyevent 66"
        with self.assertRaises(agent.AgentError) as caught:
            self.adb.quick("input", "keyevent", 66)
        self.assertEqual(caught.exception.status, 502)
        self.assertIn("the command failed", caught.exception.message)
        self.adb.quick("input", "keyevent", 4)                     # the shell goes on
        self.assertEqual(self.calls()[-1], "shell input keyevent 4")

    def test_a_phone_that_goes_off_and_comes_back(self):
        self.adb.quick("input", "keyevent", 4)
        open(self.off, "w").close()
        with self.assertRaises(agent.AgentError) as caught:
            self.adb.quick("input", "keyevent", 66)
        self.assertIn("device offline", caught.exception.message)
        self.assertEqual(self.calls(), ["shell input keyevent 4"], "the tap was not done, and not tried twice")
        os.remove(self.off)
        self.adb.quick("input", "keyevent", 66)                    # a new shell
        self.assertEqual(self.calls(), ["shell input keyevent 4", "shell input keyevent 66"])

    def test_a_busy_shell_lets_a_command_go_the_old_way(self):
        self.adb.quick("input", "keyevent", 4)
        with self.adb.session.lock:
            self.adb.quick("input", "keyevent", 3)
        self.assertEqual(self.calls(), ["shell input keyevent 4", "shell input keyevent 3"])

    def test_it_is_faster(self):
        """Not a measure of a real phone: only that the shell that stays open is not slower."""
        self.adb.quick("input", "keyevent", 0)
        start = time.monotonic()
        for _ in range(5):
            self.adb.quick("input", "keyevent", 0)
        kept = time.monotonic() - start
        start = time.monotonic()
        for _ in range(5):
            self.adb.run("shell", "input", "keyevent", 0)
        fresh = time.monotonic() - start
        self.assertLess(kept, fresh)


    def test_measure(self):
        import io
        text = io.StringIO()
        result = agent.measure(self.adb, count=3, out=text)
        self.assertLess(result["kept_shell"]["middle"], result["new_shell"]["middle"])
        self.assertIn("A tap waits", text.getvalue())
        self.assertEqual(set(self.calls()), {"shell input keyevent 0"})


class NoDelayTest(unittest.TestCase):
    def test_answers_are_not_held_back(self):
        """TCP_NODELAY on every connection: the last piece of an answer is not held back for an acknowledgement."""
        running = Running()
        self.addCleanup(running.close)
        handler = running.server.RequestHandlerClass
        self.assertTrue(handler.disable_nagle_algorithm)
        self.assertEqual(running.ask("GET", "/v1/info")[0], 200)


class AgentFailTest(unittest.TestCase):
    def test_a_phone_that_is_off_is_told_as_it_is(self):
        running = Running(fail=True)
        self.addCleanup(running.close)
        status, data, _ = running.ask("GET", "/v1/screen")
        self.assertEqual(status, 502)
        self.assertIn("device offline", json.loads(data.decode())["error"])
        status, data, _ = running.ask("POST", "/v1/tap", {"x": 1, "y": 1})
        self.assertEqual(status, 502)


class InstallerTest(unittest.TestCase):
    """install-agent.sh: the rule for sudo must be for what the agent runs, and nothing else."""

    def script(self):
        with open(os.path.join(os.path.dirname(HERE), "install-agent.sh"), encoding="utf-8") as handle:
            return handle.read()

    def test_the_sudo_rule_is_what_the_agent_runs(self):
        text = self.script()
        rule = [line for line in text.splitlines() if line.startswith("RULE=")]
        self.assertEqual(len(rule), 1)
        for action in ("start", "stop", "restart"):
            self.assertIn("/usr/bin/systemctl %s %s" % (action, agent.BOT_SERVICE), rule[0])
        self.assertEqual(rule[0].count("/usr/bin/systemctl"), 3, "no other command")
        self.assertEqual(agent.Bot().systemctl[:3], ["sudo", "-n", "/usr/bin/systemctl"], "that is how the agent calls it")
        self.assertIn("visudo -cf", text, "the rule is checked before it is installed")

    def test_running_it_again_updates_the_agent(self):
        text = self.script()
        self.assertIn("systemctl restart claudegg-agent", text, "an agent that runs already is started again with the new file")

    @unittest.skipUnless(os.name == "posix", "needs a shell")
    def test_the_script_is_a_script(self):
        import subprocess
        done = subprocess.run(["bash", "-n", os.path.join(os.path.dirname(HERE), "install-agent.sh")], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stderr.decode())


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
