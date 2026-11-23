"""The counters of the day (gamebot.count): caught, fled, stops - and the battles won and lost, which the web
interface shows next to them.  Run: python3 -m unittest discover -s tests"""
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

try:
    import gamebot as G
    import spin_stop as S
except Exception:  # noqa: BLE001
    G = None


@unittest.skipIf(G is None, "gamebot cannot be imported here")
class DayCounters(unittest.TestCase):
    def setUp(self):
        self.saved = (dict(G.stats), S.LOGFILE)
        S.LOGFILE = os.path.join(tempfile.mkdtemp(), "spin.log")
        G.stats.update(day=None, caught=0, fled=0, stops=0, won=0, lost=0)

    def tearDown(self):
        G.stats.clear()
        G.stats.update(self.saved[0])
        S.LOGFILE = self.saved[1]

    def test_won_and_lost_only_when_there_were_battles(self):
        self.assertEqual(G.count("caught"), "(today: 1 caught, 0 fled, 0 stops)")
        self.assertEqual(G.count("won"), "(today: 1 caught, 0 fled, 0 stops, 1 won, 0 lost)")
        self.assertEqual(G.count("lost"), "(today: 1 caught, 0 fled, 0 stops, 1 won, 1 lost)")

    def test_a_restart_goes_on_from_the_log_of_today(self):
        today = time.strftime("%Y-%m-%d")
        with open(S.LOGFILE, "w") as f:
            f.write("2020-01-01 10:00:00  Pokémon CAUGHT (today: 50 caught, 1 fled, 9 stops)\n")
            f.write(f"{today} 10:00:00  battle: battle 2 done: win (today: 6 caught, 0 fled, 3 stops, 2 won, 1 lost)\n")
            f.write(f"{today} 10:05:00  gamebot v3 started\n")
        self.assertEqual(G.count("lost"), "(today: 6 caught, 0 fled, 3 stops, 2 won, 2 lost)")

    def test_a_log_of_another_day_starts_at_nothing(self):
        with open(S.LOGFILE, "w") as f:
            f.write("2020-01-01 10:00:00  stop spun (today: 50 caught, 1 fled, 9 stops, 4 won, 1 lost)\n")
        self.assertEqual(G.count("stops"), "(today: 0 caught, 0 fled, 1 stops)")


if __name__ == "__main__":
    unittest.main()
