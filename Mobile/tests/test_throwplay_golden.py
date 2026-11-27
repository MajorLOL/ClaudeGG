"""The file that the C++ port of the throw itself (throw_touch, throw_ball, humanize, aim, ring_track and watch_flight of gamebot.py, played on
a pretend phone with a pretend clock) is tested against is what the Python code does now.  If this fails, one of those changed: run
python3 tools/make_throwplay_golden.py  and port the change to SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoThrowPlay.cpp (its test then
says what differs).  The file holds, for every little story, what the phone was asked for (screenshots, pictures of the live video, the
detector's boxes, random numbers) and what the throw did (every command, wait, log line and what it learned) in order."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_throwplay_golden.py")


class ThrowPlayGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())

    def test_the_file_of_what_was_learned(self):
        """save_cal() and load_cal() of gamebot.py: what the C++ port checks by hand in check_cal_file() (ClaudeGG_PokemonGoThrowPlayCheck.cpp) -
        the same numbers, the same answers.  The stories do not play these two: they only say what is written (save_cal events)."""
        sys.path.insert(0, os.path.join(HERE, ".."))
        import gamebot as G
        before = (dict(G.cal), G.CAL_FILE)
        want = {"k": 0.61, "c": 0.12, "lat": 47.5, "rel": 0.28, "aim": -130.5, "obs": [[0.9, 1.0, 0.5], [0.7, 1.2, 0.3]],
                "c_live": -0.08, "obs_live": [[0.6, 1.1, 0.2]], "v": 5}
        try:
            with tempfile.TemporaryDirectory() as folder:
                G.CAL_FILE = os.path.join(folder, "gamebot_throw.json")
                self.assertEqual(G.CAL_VERSION, 5)

                def written():
                    with open(G.CAL_FILE) as f:
                        return json.load(f)

                G.cal.clear()
                G.cal.update({k: v for k, v in want.items() if k != "v"})
                G.save_cal()
                self.assertEqual(written(), want)
                G.cal["aim"], G.cal["obs"] = 0.1234567, [[0.12345678, 1.0, 0.5]]   # (not rounded: the file keeps what the bot knows)
                G.save_cal()
                self.assertEqual((written()["aim"], written()["obs"]), (0.1234567, [[0.12345678, 1.0, 0.5]]))
                G.cal.update({k: v for k, v in want.items() if k != "v"})
                G.cal["no_curve"] = True                                  # (only when the phone has no single touch events)
                G.save_cal()
                self.assertEqual(written(), dict(want, no_curve=True))

                def loads(data, start):
                    G.cal.clear()
                    G.cal.update(start)
                    with open(G.CAL_FILE, "w") as f:
                        json.dump(data, f)
                    G.load_cal()
                    return dict(G.cal)

                fresh = {"k": 0.55, "c": 0.3, "lat": 55.0, "rel": 0.3, "aim": 0.0, "obs": [], "c_live": -0.12, "obs_live": []}
                got = loads(dict(want, no_curve=True), fresh)            # no_curve is not in the numbers that are there to be filled in
                self.assertEqual(got, {k: v for k, v in want.items() if k != "v"})
                self.assertEqual(loads(dict(want, v=4), fresh), fresh)   # an older version, or none, is dropped
                self.assertEqual(loads({k: v for k, v in want.items() if k != "v"}, fresh), fresh)
                self.assertEqual(loads({"v": 5, "k": 0.7, "unknown": 1}, fresh), dict(fresh, k=0.7))
                kept = dict(want, no_curve=True)
                kept.pop("v")
                self.assertEqual(loads({"v": 5, "aim": 12.0}, kept), dict(kept, aim=12.0))
        finally:
            G.cal.clear()
            G.cal.update(before[0])
            G.CAL_FILE = before[1]


if __name__ == "__main__":
    unittest.main()
