"""The test chapters (Test in the web interface): chapters.py describes them, gamebot.run_chapter runs one,
web.test_start / test_stop / test_zip start it from the page and give its zip.
Run: python3 -m unittest discover -s tests"""
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault("HOME", tempfile.mkdtemp())

import chapters as CH  # noqa: E402

try:
    import gamebot as G
    import spin_stop as S
except Exception:  # noqa: BLE001
    G = None
try:
    import web as W
except Exception:  # noqa: BLE001
    W = None


class Chapters(unittest.TestCase):
    def test_every_chapter_is_complete_and_once(self):
        self.assertEqual(len(CH.KEYS), len(set(CH.KEYS)))
        for c in CH.as_list():
            self.assertTrue(all(c[k] for k in ("key", "group", "title", "start", "what")), c)
            self.assertRegex(c["key"], r"^[a-z_]+$")

    def test_groups_stay_together(self):
        groups = [c["group"] for c in CH.as_list()]
        seen = []
        for g in groups:
            if not seen or seen[-1] != g:
                self.assertNotIn(g, seen, "a group comes back further down the list")
                seen.append(g)

    @unittest.skipIf(G is None, "gamebot cannot be imported here")
    def test_gamebot_knows_every_chapter(self):
        import inspect
        src = inspect.getsource(G.run_chapter)
        for key in CH.KEYS:
            self.assertIn(f'"{key}"', src, f"run_chapter does not handle '{key}'")


@unittest.skipIf(G is None, "gamebot cannot be imported here")
class RunChapter(unittest.TestCase):
    def setUp(self):
        self.lines = []
        self.saved = {n: getattr(G, n) for n in ("log", "layout_init", "load_cal", "claim_quests", "clean_bag")}
        self.saved_s = {n: getattr(S, n) for n in ("detect_screen", "debug_save")}
        G.log = self.lines.append
        G.layout_init = G.load_cal = lambda: None
        S.detect_screen = lambda: None
        S.debug_save = lambda *a, **k: None

    def tearDown(self):
        for n, f in self.saved.items():
            setattr(G, n, f)
        for n, f in self.saved_s.items():
            setattr(S, n, f)
        import signal
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

    def test_an_unknown_chapter(self):
        self.assertFalse(G.run_chapter("nope"))
        self.assertIn("no such test", self.lines[-1])

    def test_started_and_done_lines(self):
        G.claim_quests = lambda: "claimed"
        self.assertTrue(G.run_chapter("quests"))
        self.assertTrue(self.lines[0].startswith("TEST quests: started - Claim GO Pass rewards"))
        self.assertEqual(self.lines[-1], "TEST quests: done - claimed")

    def test_failed_and_an_error(self):
        G.claim_quests = lambda: "failed"
        self.assertFalse(G.run_chapter("quests"))
        self.assertEqual(self.lines[-1], "TEST quests: failed - failed")

        def boom():
            raise RuntimeError("no bag")
        G.clean_bag = boom
        self.assertFalse(G.run_chapter("bag"))
        self.assertTrue(self.lines[-1].startswith("TEST bag: failed - error no bag"))


@unittest.skipIf(W is None, "web.py cannot be imported here")
class WebTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.saved = (W.LOGFILE, W.DEBUG_DIR, W.TEST_ERR, W.bot_running, subprocess.Popen, dict(W.test))
        W.LOGFILE = os.path.join(self.dir, "spin.log")
        W.DEBUG_DIR = os.path.join(self.dir, "debug")
        W.TEST_ERR = os.path.join(W.DEBUG_DIR, "test_stderr.txt")
        W.bot_running = lambda: False
        real = subprocess.Popen
        log = W.LOGFILE

        def fake(argv, **kw):                     # instead of gamebot.py: a script that logs like a chapter
            key = argv[-1]
            code = ("import time,sys\n"
                    f"open({log!r},'a').write(time.strftime('%Y-%m-%d %H:%M:%S')+'  TEST {key}: started - x\\n')\n"
                    "time.sleep(0.3)\n"
                    + ("raise SystemExit('broken at the start')\n" if key == "video" else
                       f"open({log!r},'a').write(time.strftime('%Y-%m-%d %H:%M:%S')+'  TEST {key}: done - 2 things\\n')\n"))
            return real([sys.executable, "-c", code], **kw)
        W.subprocess.Popen = fake

    def tearDown(self):
        W.test_stop()
        W.LOGFILE, W.DEBUG_DIR, W.TEST_ERR, W.bot_running, subprocess.Popen, t = self.saved
        W.test.clear()
        W.test.update(t)

    def wait(self):
        t_end = time.time() + 10
        while (W.test_running() or W.test["ok"] is None) and time.time() < t_end:
            time.sleep(0.05)

    def test_a_test_runs_and_gives_its_result_and_zip(self):
        self.assertEqual(W.test_start("screen"), (True, "ok"))
        self.assertTrue(W.test_status()["running"])
        self.assertEqual(W.test_start("bag")[0], False)          # one at a time
        self.wait()
        st = W.test_status()
        self.assertEqual((st["running"], st["ok"], st["result"], st["ready"]), (False, True, "2 things", True))
        z = zipfile.ZipFile(io.BytesIO(W.test_zip()))
        self.assertIn("TEST screen: done - 2 things", z.read("bot_log.txt").decode())
        self.assertIn("result: done", z.read("test.txt").decode())

    def test_a_crash_at_the_start_is_a_failed_test(self):
        W.test_start("video")
        self.wait()
        st = W.test_status()
        self.assertFalse(st["ok"])
        self.assertIn("broken at the start", st["result"])

    def test_an_unknown_test_does_not_start(self):
        self.assertEqual(W.test_start("nope"), (False, "no such test"))


if __name__ == "__main__":
    unittest.main()
