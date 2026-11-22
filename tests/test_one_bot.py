"""Only one gamebot at a time may tap the phone (gamebot.only_one): the bot service and a test started by hand
spoil each other's taps.  gamebot.py needs OpenCV and the TFLite runtime; without them these tests are skipped.
Run: python3 -m unittest discover -s tests"""
import os
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
os.environ.setdefault("HOME", tempfile.mkdtemp())
try:
    import gamebot as G
except Exception:  # noqa: BLE001
    G = None


@unittest.skipIf(G is None, "gamebot.py cannot be imported here")
class OneBot(unittest.TestCase):
    def setUp(self):
        self.saved = (G.LOCK_FILE, G.LOCK_POLL, G.log, G._one["f"])
        G.LOCK_FILE = os.path.join(tempfile.mkdtemp(), "gamebot.lock")
        G.LOCK_POLL = 0.02
        G._one["f"] = None
        self.logs = []
        G.log = self.logs.append
        self.open = []

    def tearDown(self):
        for f in self.open + [G._one["f"]]:
            if f is not None and not f.closed:
                f.close()
        G.LOCK_FILE, G.LOCK_POLL, G.log, G._one["f"] = self.saved

    def take(self, mode, **kw):
        ok = G.only_one(mode, **kw)
        if ok:
            self.open.append(G._one["f"])
        return ok

    def test_the_first_one_may_go_on(self):
        self.assertTrue(self.take("fight"))
        with open(G.LOCK_FILE) as f:
            text = f.read()
        self.assertIn("gamebot.py fight", text)
        self.assertIn(f"process {os.getpid()}", text)
        self.assertEqual(self.logs, [])

    def test_a_second_one_is_not_started(self):
        self.assertTrue(self.take("loop"))
        self.assertFalse(self.take("fight"))
        self.assertEqual(len(self.logs), 1)
        self.assertIn("NOT STARTED", self.logs[0])
        self.assertIn("gamebot.py loop", self.logs[0])                  # (who has the phone)
        self.assertIn("sudo systemctl stop spin-stop", self.logs[0])    # (what to do about it)

    def test_the_lock_is_free_again_when_the_first_one_ends(self):
        self.assertTrue(self.take("fight"))
        self.open.pop().close()                                         # (the process ended)
        self.assertTrue(self.take("battle"))
        with open(G.LOCK_FILE) as f:
            self.assertIn("gamebot.py battle", f.read())                # (not what the first one wrote)

    def test_the_service_waits_for_a_test_that_was_started_by_hand(self):
        self.assertTrue(self.take("fight"))
        first = self.open[-1]
        done = []
        t = threading.Thread(target=lambda: done.append(self.take("loop", wait=True)), daemon=True)
        t.start()
        time.sleep(0.15)
        self.assertEqual(done, [])                                      # still waiting ...
        self.assertEqual(len([m for m in self.logs if m.startswith("waiting")]), 1)    # ... and said so once
        first.close()
        t.join(timeout=3)
        self.assertEqual(done, [True])


if __name__ == "__main__":
    unittest.main()
