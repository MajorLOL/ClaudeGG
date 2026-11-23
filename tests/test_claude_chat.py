"""Claude in the web interface (claude_chat.py): the tools it may use, the conversation with the Claude API and
the pull request at the maker's repository - the API and GitHub are replaced by fakes here.
Run: python3 -m unittest discover -s tests"""
import base64
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import claude_chat as C  # noqa: E402


def make_repo():
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "tests"))
    with open(os.path.join(d, "bot.py"), "w") as f:
        f.write("def tap():\n    x = 884\n    return x\n")
    with open(os.path.join(d, "tests", "t.py"), "w") as f:
        f.write("# tap test\n")
    with open(os.path.join(d, ".secret"), "w") as f:
        f.write("key\n")
    subprocess.run(["git", "init", "-q", d], check=True)
    subprocess.run(["git", "-C", d, "add", "bot.py", "tests/t.py"], check=True)
    return d


class Files(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo()

    def test_only_the_files_of_the_code(self):
        self.assertEqual(C.repo_files(self.repo), ["bot.py", "tests/t.py"])
        self.assertTrue(C.safe_path(self.repo, "bot.py"))
        for bad in ("../etc/passwd", ".secret", "/etc/passwd", "", "nope.py"):
            self.assertIsNone(C.safe_path(self.repo, bad), bad)

    def test_parse_github(self):
        self.assertEqual(C.parse_github("https://github.com/MajorLOL/pokemon-go-automation"), "MajorLOL/pokemon-go-automation")
        self.assertEqual(C.parse_github("git@github.com:a/b.git\n"), "a/b")
        self.assertEqual(C.parse_github("https://example.com/a/b"), "")

    def test_apply_change_once_exactly(self):
        self.assertEqual(C.apply_change("a b c", "b", "B", "f"), "a B c")
        with self.assertRaises(ValueError):
            C.apply_change("a b b", "b", "B", "f")
        with self.assertRaises(ValueError):
            C.apply_change("a", "b", "B", "f")


class Settings(unittest.TestCase):
    def setUp(self):
        self.saved = (C.CONF_DIR, C.KEY_FILE, C.GH_FILE, C.SETTINGS_FILE, C.HISTORY_FILE, C.gh, C.STORE_DIR)
        d = tempfile.mkdtemp()
        C.STORE_DIR = os.path.join(d, "store")
        C.CONF_DIR = os.path.join(d, "conf")
        C.KEY_FILE, C.GH_FILE = os.path.join(C.CONF_DIR, "k"), os.path.join(C.CONF_DIR, "g")
        C.SETTINGS_FILE, C.HISTORY_FILE = os.path.join(d, "s.json"), os.path.join(d, "h.json")
        C.gh = lambda method, path, token, body=None: {"login": "dennis"}
        self.chat = C.Chat(make_repo())

    def tearDown(self):
        C.CONF_DIR, C.KEY_FILE, C.GH_FILE, C.SETTINGS_FILE, C.HISTORY_FILE, C.gh, C.STORE_DIR = self.saved

    def test_keys_are_kept_private_and_never_shown(self):
        self.assertEqual(self.chat.set_settings({"api_key": "sk-1", "github_token": "ghp_1", "model": "claude-opus-5-5"}),
                         (True, "saved - GitHub user dennis"))
        self.assertEqual(stat.S_IMODE(os.stat(C.KEY_FILE).st_mode), 0o600)
        st = self.chat.state()
        self.assertEqual((st["has_key"], st["has_github"], st["github_user"], st["model"]),
                         (True, True, "dennis", "claude-opus-5-5"))
        self.assertNotIn("sk-1", json.dumps(st))
        self.chat.set_settings({"api_key": "", "github_token": ""})          # empty: unchanged
        self.assertTrue(self.chat.state()["has_key"])
        self.chat.set_settings({"api_key": "-", "github_token": "-"})        # '-': removed
        st = self.chat.state()
        self.assertEqual((st["has_key"], st["has_github"], st["github_user"]), (False, False, ""))

    def test_a_token_github_does_not_accept(self):
        def refuse(method, path, token, body=None):
            raise C.ApiError(401, "Bad credentials")
        C.gh = refuse
        ok, msg = self.chat.set_settings({"github_token": "bad"})
        self.assertFalse(ok)
        self.assertIn("Bad credentials", msg)
        self.assertFalse(self.chat.state()["has_github"])


class Conversation(unittest.TestCase):
    def setUp(self):
        self.saved = (C.CONF_DIR, C.KEY_FILE, C.GH_FILE, C.SETTINGS_FILE, C.HISTORY_FILE, C.call_claude, C.STORE_DIR)
        d = tempfile.mkdtemp()
        C.STORE_DIR = os.path.join(d, "store")
        C.CONF_DIR = os.path.join(d, "conf")
        C.KEY_FILE, C.GH_FILE = os.path.join(C.CONF_DIR, "k"), os.path.join(C.CONF_DIR, "g")
        C.SETTINGS_FILE, C.HISTORY_FILE = os.path.join(d, "s.json"), os.path.join(d, "h.json")
        self.log = os.path.join(d, "spin.log")
        with open(self.log, "w") as f:
            f.write("2026-11-23 10:00:00  battle: switch - tapping tile 2 at (884, 1620)\n2026-11-23 10:00:01  other\n")
        self.chat = C.Chat(make_repo(), status_fn=lambda: {"service": "active", "labels": {"x": 1}},
                           log_file=self.log, shot_fn=lambda: b"\xff\xd8jpg")
        self.chat.set_settings({"api_key": "sk-test"})
        self.calls, self.systems, self.efforts = [], [], []

    def tearDown(self):
        C.CONF_DIR, C.KEY_FILE, C.GH_FILE, C.SETTINGS_FILE, C.HISTORY_FILE, C.call_claude, C.STORE_DIR = self.saved

    def fake(self, answers):
        def call(key, model, system, messages, tools, effort=""):
            self.calls.append(json.loads(json.dumps(messages)))
            self.systems.append(system)
            self.efforts.append(effort)
            self.assertEqual(key, "sk-test")
            self.assertIn("never change anything on the Pi", system)
            return answers.pop(0)
        C.call_claude = call

    def test_tools_then_an_answer(self):
        self.fake([
            {"stop_reason": "tool_use", "usage": {"input_tokens": 10, "output_tokens": 5}, "content": [
                {"type": "text", "text": "Even kijken."},
                {"type": "tool_use", "id": "a", "name": "read_log", "input": {"contains": "switch"}},
                {"type": "tool_use", "id": "b", "name": "read_file", "input": {"path": "bot.py", "start": 2, "end": 2}},
                {"type": "tool_use", "id": "c", "name": "screenshot", "input": {}},
                {"type": "tool_use", "id": "d", "name": "read_file", "input": {"path": "../x"}}]},
            {"stop_reason": "end_turn", "usage": {"input_tokens": 20, "output_tokens": 7},
             "content": [{"type": "text", "text": "Hij tikte op x=884."}]}])
        self.assertEqual(self.chat.send("waarom?"), (True, "ok"))
        self.chat_wait()
        results = {r["tool_use_id"]: r for r in self.calls[1][-1]["content"]}
        self.assertIn("884, 1620", results["a"]["content"])
        self.assertNotIn("other", results["a"]["content"])
        self.assertEqual(results["b"]["content"].splitlines()[-1], "2:     x = 884")
        self.assertEqual(results["c"]["content"][0]["type"], "image")        # Claude sees the picture ...
        self.assertTrue(results["d"]["is_error"])
        roles = [m["role"] for m in self.chat.shown]
        self.assertEqual(roles, ["user", "assistant", "note", "assistant"])
        self.assertEqual(self.chat.shown[-1]["text"], "Hij tikte op x=884.")
        self.assertEqual(self.chat.tokens, {"in": 30, "out": 12})
        kept = json.dumps(self.chat.messages)                                # ... but it is not kept afterwards
        self.assertNotIn('"image"', kept)
        again = C.Chat(self.chat.repo_dir)                                   # the conversation survives a restart
        self.assertEqual(len(again.shown), 4)

    def test_projects_chats_notes_and_effort(self):
        first = self.chat.state()
        self.assertEqual(first["project"]["name"], "Pokémon GO bot")
        self.chat.set_settings({"effort": "high"})
        self.chat.save_project({"id": first["project"]["id"], "instructions": "Always answer in Dutch."})
        self.fake([
            {"stop_reason": "tool_use", "content": [
                {"type": "tool_use", "id": "a", "name": "save_note", "input": {"text": "The LAIC Cup party screen glues words."}}]},
            {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Genoteerd."}]}])
        self.chat.send("onthoud dit")
        self.chat_wait()
        self.assertEqual(self.efforts, ["high", "high"])
        self.assertIn("Always answer in Dutch.", self.systems[0])
        st = self.chat.state()
        self.assertIn("- The LAIC Cup party screen glues words.", st["project"]["notes"])
        self.assertEqual(st["chat"]["title"], "onthoud dit")
        one = st["chat"]["id"]
        # a new chat in the same project gets the knowledge; the old chat stays in the list
        self.chat.new()
        self.fake([{"stop_reason": "end_turn", "content": [{"type": "text", "text": "Ja."}]}])
        self.chat.send("weet je het nog?")
        self.chat_wait()
        self.assertIn("glues words", self.systems[-1])
        self.assertEqual([c["title"] for c in self.chat.state()["chats"]], ["weet je het nog?", "onthoud dit"])
        # another project has its own chats and knowledge
        other = self.chat.save_project({"name": "Rocket"})
        st = self.chat.state()
        self.assertEqual((st["project"]["id"], st["chats"][0]["title"]), (other["id"], "New chat"))
        self.assertNotIn("glues words", self.chat.system_prompt())
        self.assertTrue(self.chat.open_chat(one))
        self.assertEqual(self.chat.state()["project"]["name"], "Pokémon GO bot")
        self.assertTrue(self.chat.delete_chat(one))
        self.assertNotIn(one, [c["id"] for c in self.chat.state()["chats"]])
        self.assertTrue(self.chat.delete_project(other["id"]))
        self.assertFalse(self.chat.delete_project(self.chat.state()["project"]["id"]))   # the last one stays
        self.assertFalse(self.chat.open_chat("../../etc/passwd"))

    def test_the_chat_of_before_the_projects_is_kept(self):
        with open(C.HISTORY_FILE, "w") as f:
            json.dump({"messages": [{"role": "user", "content": "oud"}], "shown": [{"role": "user", "text": "oud", "t": ""}],
                       "tokens": {"in": 1, "out": 2}}, f)
        import shutil
        shutil.rmtree(C.STORE_DIR, ignore_errors=True)
        os.remove(C.SETTINGS_FILE)
        chat = C.Chat(self.chat.repo_dir)
        self.assertEqual([c["title"] for c in chat.state()["chats"]], ["oud"])

    def test_effort_goes_into_the_request(self):
        sent = {}

        def fake_http(method, url, headers, body=None, timeout=180):
            sent.update(body)
            return {}
        saved = C._http
        C._http = fake_http
        try:
            C.call_claude("k", "claude-opus-5-5", "s", [], [], "xhigh")
            self.assertEqual((sent["output_config"], sent["max_tokens"]), ({"effort": "xhigh"}, 64000))
            sent.clear()
            C.call_claude("k", "claude-opus-5-5", "s", [], [], "")
            self.assertNotIn("output_config", sent)
        finally:
            C._http = saved

    def test_an_api_key_that_is_refused(self):
        def refuse(*a):
            raise C.ApiError(401, "invalid x-api-key")
        C.call_claude = refuse
        self.chat.send("hallo")
        self.chat_wait()
        self.assertEqual(self.chat.shown[-1]["text"], "The API key is not accepted.")
        self.assertFalse(self.chat.busy)

    def test_no_pull_request_without_a_github_token(self):
        out, err = self.chat.run_tool("create_pull_request", {"title": "t", "description": "d", "changes": []})
        self.assertTrue(err)
        self.assertIn("no GitHub token", out)

    def test_one_question_at_a_time_and_none_without_a_key(self):
        self.chat.busy = True
        self.assertEqual(self.chat.send("x")[0], False)
        self.chat.busy = False
        self.chat.set_settings({"api_key": "-"})
        self.assertIn("no API key", self.chat.send("x")[1])

    def chat_wait(self):
        import time
        t_end = time.time() + 10
        while self.chat.busy and time.time() < t_end:
            time.sleep(0.02)


class FakeGitHub:
    """Just enough of the GitHub API for open_pull_request."""

    def __init__(self, me, maker="maker/bot", files=None, fork=False):
        self.me, self.maker, self.files = me, maker, files or {}
        self.fork = fork
        self.calls, self.tree, self.pr, self.commit = [], None, None, None

    def __call__(self, method, path, token, body=None):
        self.calls.append((method, path))
        if path == "/user":
            return {"login": self.me}
        if method == "GET" and path == f"/repos/{self.maker}":
            return {"default_branch": "main", "full_name": self.maker}
        if method == "GET" and path == f"/repos/{self.me}/bot":
            if not self.fork:
                raise C.ApiError(404, "Not Found")
            return {"full_name": f"{self.me}/bot", "source": {"full_name": self.maker}}
        if method == "POST" and path.endswith("/forks"):
            self.fork = True
            return {"full_name": f"{self.me}/bot"}
        if path.endswith("/merge-upstream"):
            return {}
        if path.endswith("/git/ref/heads/main"):
            return {"object": {"sha": "base1"}}
        if path.endswith("/git/commits/base1"):
            return {"tree": {"sha": "tree1"}}
        if "/contents/" in path:
            name = path.split("/contents/")[1].split("?")[0]
            if name not in self.files:
                raise C.ApiError(404, "Not Found")
            return {"content": base64.b64encode(self.files[name].encode()).decode(), "sha": "x"}
        if path.endswith("/git/trees"):
            self.tree = (path, body)
            return {"sha": "tree2"}
        if path.endswith("/git/commits"):
            self.commit = (path, body)
            return {"sha": "commit2"}
        if path.endswith("/git/refs"):
            self.ref = (path, body)
            return {}
        if path.endswith("/pulls"):
            self.pr = (path, body)
            return {"html_url": f"https://github.com/{self.maker}/pull/7", "number": 7}
        raise AssertionError(f"unexpected {method} {path}")


class PullRequest(unittest.TestCase):
    def setUp(self):
        self.saved = C.gh

    def tearDown(self):
        C.gh = self.saved

    def test_a_user_forks_and_hands_it_in_at_the_maker(self):
        fake = C.gh = FakeGitHub("dennis", files={"bot.py": "def tap():\n    x = 884\n    return x\n"})
        url, number, branch = C.open_pull_request("tok", "maker/bot", "Tap the right tile", "Why and how to test.",
                                                  [{"path": "bot.py", "old_text": "x = 884", "new_text": "x = 1300"},
                                                   {"path": "notes.md", "old_text": "", "new_text": "new\n"}],
                                                  model="claude-sonnet-5-5", now=0)
        self.assertEqual((url, number), ("https://github.com/maker/bot/pull/7", 7))
        self.assertTrue(branch.startswith("claude/tap-the-right-tile-"))
        self.assertIn(("POST", "/repos/maker/bot/forks"), fake.calls)
        path, tree = fake.tree
        self.assertEqual(path, "/repos/dennis/bot/git/trees")                 # the branch is in the user's fork
        self.assertEqual(tree["base_tree"], "tree1")
        files = {t["path"]: t["content"] for t in tree["tree"]}
        self.assertEqual(files["bot.py"], "def tap():\n    x = 1300\n    return x\n")
        self.assertEqual(files["notes.md"], "new\n")
        self.assertEqual(fake.commit[1]["parents"], ["base1"])
        path, pr = fake.pr
        self.assertEqual(path, "/repos/maker/bot/pulls")                      # ... and handed in at the maker
        self.assertEqual((pr["head"], pr["base"]), (f"dennis:{branch}", "main"))
        self.assertNotIn("@", pr["body"])

    def test_the_maker_gets_a_branch_in_the_repository_itself(self):
        fake = C.gh = FakeGitHub("maker", files={"bot.py": "x = 1\n"})
        _, _, branch = C.open_pull_request("tok", "maker/bot", "t", "d", [{"path": "bot.py", "old_text": "x = 1",
                                                                            "new_text": "x = 2"}])
        self.assertNotIn(("POST", "/repos/maker/bot/forks"), fake.calls)
        self.assertEqual(fake.tree[0], "/repos/maker/bot/git/trees")
        self.assertEqual(fake.pr[1]["head"], branch)

    def test_nothing_is_made_when_a_change_does_not_fit(self):
        for change, why in (({"path": "bot.py", "old_text": "nope", "new_text": "y"}, "0 times"),
                            ({"path": "bot.py", "old_text": "x = 1", "new_text": "x = ("}, "would not run"),
                            ({"path": "bot.py", "old_text": "", "new_text": "y"}, "exists already"),
                            ({"path": "../x.py", "old_text": "", "new_text": "y"}, "not a file")):
            fake = C.gh = FakeGitHub("dennis", files={"bot.py": "x = 1\n"}, fork=True)
            with self.assertRaises(ValueError) as e:
                C.open_pull_request("tok", "maker/bot", "t", "d", [change])
            self.assertIn(why, str(e.exception))
            self.assertIsNone(fake.tree)
            self.assertIsNone(fake.pr)


if __name__ == "__main__":
    unittest.main()
