"""The battles of today in the web interface (web.battles_of / web.stats_of / web.today_lines): every GO Battle
League match with its time, result and foes, read from the log - also the matches of before the day counter
knew about won and lost.  Run: python3 -m unittest discover -s tests"""
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
os.environ.setdefault("HOME", tempfile.mkdtemp())
try:
    import web as W
except Exception:  # noqa: BLE001
    W = None

DAY = "2026-11-23"
LOG = [
    "2026-11-22 21:00:00  battle: battle 5 done: win (1 won of 1)",            # (yesterday)
    "2026-11-22 21:01:00  (today: 3 caught, 1 fled, 9 stops)",
    f"{DAY} 09:00:00  spin: stop spun (today: 4 caught, 0 fled, 2 stops)",
    f"{DAY} 09:10:00  battle: 5 battle(s) in 'Great League' with Medicham, Azumarill, Lanturn",
    f"{DAY} 09:11:00  battle: battle 1 of 5 - tapping USE THIS PARTY at (884, 1900)",
    f"{DAY} 09:11:20  fight: foe is Shadow Swampert (CP 1490) - moves Mud Shot / Hydro Cannon, Earthquake",
    f"{DAY} 09:12:10  fight: foe is Registeel - moves Lock-On / Focus Blast",
    f"{DAY} 09:12:30  fight: foe is Registeel - moves Lock-On / Focus Blast (as seen before)",
    f"{DAY} 09:13:40  battle: battle 1 done: win (1 won of 1)",
    f"{DAY} 09:14:00  battle: battle 2 of 5 - tapping USE THIS PARTY at (884, 1900)",
    f"{DAY} 09:15:00  fight: foe is Bastiodon - moves Smack Down / Stone Edge",
    f"{DAY} 09:17:00  battle: battle 2 done: loss (given up) (1 won of 2) (today: 4 caught, 0 fled, 2 stops, 1 won, 1 lost)",
    f"{DAY} 09:18:00  battle: battle 3 of 5 - tapping USE THIS PARTY at (884, 1900)",
    f"{DAY} 09:21:00  battle: battle 3 done: loss (1 won of 3)",
    f"{DAY} 09:30:00  gifts: done (today: 2 opened, 5 sent)",
]


@unittest.skipIf(W is None, "web.py cannot be imported here")
class BattlesToday(unittest.TestCase):
    def setUp(self):
        self.saved = W.LOGFILE
        W.LOGFILE = os.path.join(tempfile.mkdtemp(), "spin.log")
        with open(W.LOGFILE, "w") as f:
            f.write("\n".join(LOG) + "\n")
        W._today["key"] = None

    def tearDown(self):
        W.LOGFILE = self.saved
        W._today["key"] = None

    def test_only_the_lines_of_today(self):
        lines = W.today_lines(DAY)
        self.assertTrue(lines and all(l.startswith(DAY) for l in lines))

    def test_every_match_with_its_result_and_foes(self):
        games = W.battles_of(W.today_lines(DAY))
        self.assertEqual([g["result"] for g in games], ["win", "loss", "loss"])
        self.assertEqual([g["gave_up"] for g in games], [False, True, False])
        self.assertEqual(games[0]["foes"], ["Shadow Swampert", "Registeel"])
        self.assertEqual(games[1]["foes"], ["Bastiodon"])
        self.assertEqual(games[2]["foes"], [])
        self.assertEqual(games[0]["time"], "09:13")
        self.assertEqual(games[0]["league"], "Great League")

    def test_the_counters_count_the_matches_and_skip_the_gifts_line(self):
        stats, games = W.stats_of(W.today_lines(DAY))
        self.assertEqual(stats, "4 caught, 0 fled, 2 stops, 1 won, 2 lost")
        self.assertEqual(len(games), 3)

    def test_no_battles_no_won_and_lost(self):
        stats, games = W.stats_of([f"{DAY} 09:00:00  spin: stop spun (today: 1 caught, 0 fled, 1 stops)"])
        self.assertEqual((stats, games), ("1 caught, 0 fled, 1 stops", []))

    def test_battles_alone_still_show(self):
        stats, _ = W.stats_of([f"{DAY} 09:13:40  battle: battle 1 done: win (1 won of 1)"])
        self.assertEqual(stats, "1 won, 0 lost")

    def test_today_stats_reads_again_when_the_log_grows(self):
        today = time.strftime("%Y-%m-%d")
        with open(W.LOGFILE, "w") as f:
            f.write(f"{today} 10:00:00  battle: battle 1 done: win (1 won of 1)\n")
        self.assertEqual(W.today_stats()[0], "1 won, 0 lost")
        with open(W.LOGFILE, "a") as f:
            f.write(f"{today} 10:05:00  battle: battle 2 done: loss (1 won of 2)\n")
        os.utime(W.LOGFILE, (time.time() + 5, time.time() + 5))
        self.assertEqual(W.today_stats()[0], "1 won, 1 lost")


if __name__ == "__main__":
    unittest.main()
