"""The file that the C++ port of the daily run (daily_cycle(), run_one_game(), finish_catch(), last_slot(), daily_limit() and daily_order() of gamebot.py: the
start time of the day, the apps one after the other, the time of the run, the battles and the teams first, the catch that is finished, the battles that go on
after a reward - played on a pretend phone with a pretend clock) is tested against is what the Python code does now.  If this fails, one of those changed: run
python3 tools/make_daily_golden.py  and port the change to SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoDaily.cpp (its test then says what differs).  The
file holds, for every little story, what the code was given (the file of the run, the apps, the choices for the battles, the steps and how long they took,
the screenshots) and what it did (log lines, sleeps, writes of the file, the calls to reset, close, battle and teams) in order, every event with the time of
the pretend clock, and at the end of every call what it returned and what the run remembers."""
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_daily_golden.py")
sys.path.insert(0, os.path.join(HERE, "..", "tools"))


def load():
    import make_daily_golden as M
    with open(M.OUT, "rb") as f:
        return json.loads(M.unpack(f.read()))


def by_name():
    return {c["id"]: c for c in load()["cases"]}


def logs_of(case):
    return [e[2] for e in case["events"] if e[0] == "log"]


def results_of(case):
    return [e[2] for e in case["events"] if e[0] == "result"]


class DailyGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        done = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())

    def test_the_stories_have_their_own_names(self):
        import make_daily_golden as M
        names = [s["id"] for s in M.all_stories()]
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(len(names), 140)

    def test_only_two_stories_end_with_an_error(self):
        """The run does not fail by itself: only a file without the list of what is done (a file the bot did not write) and an app that does not start."""
        raised = {c["id"]: [e[2] for e in c["events"] if e[0] == "raised"] for c in load()["cases"]}
        self.assertEqual({k: v for k, v in raised.items() if v}, {"file_without_done": ["'done'"], "game_restart_error": ["adb offline"]})

    def test_every_branch_of_the_run_is_played(self):
        """The log lines of the daily run are all in the stories (so every branch of daily_cycle() and run_one_game() is played)."""
        logs, kinds = set(), set()
        for case in load()["cases"]:
            for event in case["events"]:
                kinds.add(event[0])
                if event[0] == "log":
                    logs.add(re.sub(r"\d+", "N", re.sub(r"\d{4}-\d\d-\d\d \d\d:\d\d", "DATE", event[2])))
        joined = "\n".join(sorted(logs))
        for part in ("daily run started: ", "Start pressed - daily run starts now: ", "bot started - daily run starts now: ", "daily run: starting ",
                     "min played)", "battle: the chosen app ", "daily run: N of N min played", "daily run: the run time of N min is up - closing the game, the run ends",
                     "daily run: the run time of N min is up - closing the game", "daily run: the run time is up - finishing this catch first",
                     "daily run switched off", "daily run: ", "error: boom", "battle: error ", "teams: error ", "battle: the Pokémon of the reward was caught - back to the battles",
                     "daily run: stopped - the run time is up", "daily run complete - next run at DATE", "daily run waiting - next run at DATE"):
            self.assertIn(part, joined)
        for kind in ("daily_file", "daily_save", "packages", "battle_wanted", "battle_app", "reset", "close_game", "watchdog", "restart", "restart_error", "auto_battle",
                     "battle_result", "teams_due", "teams_refresh", "teams_end", "step", "step_error", "no_step", "shot", "shot_error", "screen", "screen_error",
                     "beat", "sleep", "call", "result", "raised", "state", "battle_op", "teams_op"):
            self.assertIn(kind, kinds)

    def test_a_game_is_never_played_without_the_watchdog_and_the_reset(self):
        """Every game starts with the reset of the flags and the watchdog and the watchdog ends with it, also when the game ends with an error."""
        for case in load()["cases"]:
            kinds = [e[0] for e in case["events"] if e[0] in ("reset", "watchdog", "restart", "restart_error", "no_step")]
            started = [e for e in case["events"] if e[0] == "watchdog" and e[3] == "start"]
            stopped = [e for e in case["events"] if e[0] == "watchdog" and e[3] == "stop"]
            self.assertEqual(len(started), len(stopped), case["id"])
            resets = [e for e in case["events"] if e[0] == "reset"]
            self.assertGreaterEqual(len(resets), len(started), case["id"])

    def test_the_edges_are_exact(self):
        """The edges: the start time of the day at the second, the saves after more than a minute (not exactly one), the reports after half an hour, the
        time that is up after more than the limit (not exactly the limit), the apps that are tried."""
        cases = by_name()
        starts = lambda name: "daily run started: " + "com.nianticlabs.pokemongo" in logs_of(cases[name])  # noqa: E731
        self.assertTrue(starts("start_exactly_now"))
        self.assertTrue(starts("start_one_second_late"))
        self.assertFalse(starts("start_one_second_early"))
        self.assertTrue(starts("start_used_up_by_one_second"))
        self.assertFalse(starts("start_already_used"))
        saved_at = lambda name: [e[1] - cases[name]["events"][0][1] for e in cases[name]["events"] if e[0] == "daily_save"]  # noqa: E731
        self.assertEqual(saved_at("save_not_after_exactly_a_minute")[:2], [0, 120])                    # (60 s after the last save: not yet)
        self.assertEqual(saved_at("save_after_a_bit_more_than_a_minute")[:3], [0, 60.5, 121])
        reports = lambda name: len([x for x in logs_of(cases[name]) if re.match(r"daily run: \d+ of \d+ min played", x)])  # noqa: E731
        self.assertEqual(reports("report_exactly_half_an_hour"), 2)
        self.assertEqual(reports("report_just_before_half_an_hour"), 2)
        up = lambda name: any("closing the game, the run ends" in x for x in logs_of(cases[name]))  # noqa: E731
        self.assertTrue(up("limit_in_the_loop"))
        self.assertTrue(up("limit_is_reached_at_the_start"))
        self.assertEqual(results_of(cases["limit_values"])[:4], [480, 60, 60, 1])

    def test_python_does_what_the_port_imitates(self):
        """Things of Python that the C++ port has to do by hand: round-half-to-even in f'{x:.0f}', int() and float() of a text (spaces, signs, underscores,
        digits of every script), max() and min() that keep the first of two equal numbers, dict.fromkeys() that keeps the order, a list that is empty is false."""
        self.assertEqual(f"{30.5:.0f}", "30")
        self.assertEqual(f"{31.5:.0f}", "32")
        self.assertEqual(f"{0.5:.0f}", "0")
        self.assertEqual(int(" 1_0 "), 10)
        self.assertEqual(int("+8"), 8)
        self.assertEqual(int("\u0663"), 3)
        self.assertEqual(float("\u0661\u0662"), 12.0)
        self.assertEqual(float(" 1e2 "), 100.0)
        self.assertEqual(float("-INF"), float("-inf"))
        with self.assertRaises(ValueError):
            int("1__0")
        with self.assertRaises(ValueError):
            float("1_.5")
        with self.assertRaises(ValueError):
            int("")
        self.assertEqual(list(dict.fromkeys(["a", "b", "a", "c", "b"])), ["a", "b", "c"])
        self.assertFalse([] or {} or "" or 0)
        self.assertEqual(max(1, True), 1)
        self.assertIs(max(True, 1), True)


if __name__ == "__main__":
    unittest.main()
