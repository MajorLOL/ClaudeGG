import json
import os
import struct
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import claudegg_agent as agent  # noqa: E402

FAKE = os.path.join(os.path.dirname(HERE), "fake_adb.py")


class Running:
    """The agent on a free port, with the fake adb; `calls()` is what the fake adb was asked."""

    def __init__(self, fail=False):
        self.folder = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.folder.name, "adb.log")
        os.environ["FAKE_ADB_LOG"] = self.log
        if fail:
            os.environ["FAKE_ADB_FAIL"] = "1"
        else:
            os.environ.pop("FAKE_ADB_FAIL", None)
        self.token = agent.read_or_make_token(os.path.join(self.folder.name, "token"))
        phone = agent.Phone(agent.Adb([sys.executable, FAKE]))
        self.server = agent.make_server(phone, self.token, "127.0.0.1", 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        os.environ.pop("FAKE_ADB_LOG", None)
        os.environ.pop("FAKE_ADB_FAIL", None)
        self.folder.cleanup()

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
