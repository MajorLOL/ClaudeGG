"""The fight loop of gamebot.py from the first picture to NEXT BATTLE, with a fake phone (no adb, no OCR program).

The "phone" shows real pictures of fights (tests/fixtures) as its live video and reacts to what the bot does: a
tap on a lit charged attack button starts the little game of that attack, a tap on the shield question ends it,
and so on.  The text reader is replaced by the lines it read from the same pictures (fixtures/fight/ocr.json).
gamebot.py needs OpenCV and the TFLite runtime; without them these tests are skipped.
Run: python3 -m unittest discover -s tests"""
import json
import os
import sys
import tempfile
import threading
import time as real_time
import unittest

import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
os.environ.setdefault("HOME", tempfile.mkdtemp())
try:
    import gamebot as G
    import spin_stop as S
    import battle_vision as BV
except Exception:  # noqa: BLE001
    G = S = BV = None

FIX = os.path.join(HERE, "fixtures")
with open(os.path.join(FIX, "fight", "ocr.json"), encoding="utf-8") as _f:
    OCR = {k: [(line[0], line[1], line[2], [tuple(w) for w in line[3]]) for line in v] for k, v in json.load(_f).items()}


class Clock:
    """A clock that only moves when the fake phone gives a picture or the loop sleeps (the test runs in a second)."""
    t = 1000.0

    @staticmethod
    def monotonic():
        return Clock.t

    @staticmethod
    def time():
        return Clock.t

    @staticmethod
    def sleep(seconds):
        if threading.current_thread() is threading.main_thread():
            Clock.t += seconds
        else:
            real_time.sleep(min(seconds, 0.002))

    @staticmethod
    def strftime(*a):
        return real_time.strftime(*a)


class Phone:
    """What is on the screen, and what was done to it."""

    def __init__(self, video=True, tie=""):
        self.video = video
        self.tie = tie                     # "first": the other side's charged attack goes first, ours follows it;
        self.tied = False                  # "lost": theirs goes first and ours was not thrown at all
        self.scene = "versus"
        self.since = Clock.t
        self.taps, self.swipes, self.logs = [], [], []
        self.thrown = None
        self.boxes = 0
        self.pictures = {}

    def picture(self, name, size=(704, 880)):
        key = (name, size)
        if key not in self.pictures:
            folder = "minigame" if name in ("flying", "ghost") else "fight"
            file = {"their_attack": "minigame_zoom", "tie_question": "shield_question"}.get(name, name)
            img = cv2.imread(os.path.join(FIX, folder, file + ".jpg"))
            self.pictures[key] = cv2.resize(img, size, interpolation=cv2.INTER_AREA)
        return self.pictures[key]

    def to(self, scene):
        self.scene, self.since = scene, Clock.t

    def tick(self):
        """The game goes on by itself."""
        age = Clock.t - self.since
        if self.scene == "versus" and age > 0.5:
            self.to("fight_ready")
        elif self.scene == "their_attack" and age > 2.0:             # the other side's attack is over:
            self.to("minigame_zoom" if self.tie == "first" else "fight_ready")   # ours follows - or the fight
        elif self.scene == "minigame_zoom" and age > 2.5:            # "Get Ready!" ...
            self.to("ghost" if self.thrown == 0 else "flying")       # ... then the icons
        elif self.scene in ("ghost", "flying") and age > 4.0:
            self.to("run2_dim")                                      # the fight goes on, nothing lit
        elif self.scene == "run2_dim" and age > 3.0:
            self.to("shield_question")

    def tap(self, x, y, ms=120):
        fx, fy = x / float(S.REF_W), y / float(S.REF_H)
        self.taps.append((self.scene, round(fx, 3), round(fy, 3)))
        answer = abs(fx - 0.5) < 0.2 and (abs(fy - BV.TAP_SHIELD[1]) < 0.05 or abs(fy - BV.TAP_NOT_NOW[1]) < 0.05)
        if self.scene == "fight_ready" and abs(fy - BV.BTN_Y) < 0.05:
            for i, bx in enumerate(BV.BTN_X):
                if abs(fx - bx) < 0.08:
                    self.thrown = i
                    if self.tie and not self.tied:                   # (the other side was a little earlier)
                        self.tied = True
                        self.to("tie_question")
                    else:
                        self.to("minigame_zoom")
        elif self.scene == "tie_question" and answer:
            self.to("their_attack")
        elif self.scene == "shield_question" and answer:
            self.to("result_loss")
        real_time.sleep(0.001)

    def swipe(self, strokes):
        self.swipes.append((self.scene, [tuple(s) for s in strokes]))
        real_time.sleep(0.002)

    def screenshot(self, on_grab=None):
        if not self.video:
            Clock.t += 1.3                                           # (a screenshot takes its time)
            self.tick()
        return self.picture(self.scene, (S.REF_W, S.REF_H))

    def ocr(self, img, y0=0, y1=None, scale=1.0):
        if img.shape[0] < 400:                                       # a name box: the foe's is read first, then mine
            self.boxes += 1
            # (the names only come through after the first throw: until then the foe is not known and the
            # engine throws what is lit - with the foe known it could also decide to go on with fast attacks,
            # and the fake foe never faints.  In the "lost" story a second throw is needed: no names at all.)
            if self.thrown is None or self.tie == "lost":
                return []
            return OCR["name_foe_41"] if self.boxes % 2 else OCR["name_me_41"]
        if y0 > 0.8 * img.shape[0]:                                  # the labels under the buttons
            return OCR["buttons_41"] if self.scene == "fight_ready" else []
        if self.scene == "result_loss":
            return OCR["result_135"]
        return []

    # ---- the live video
    failed = False

    def healthy(self, max_age=2.5):
        return True

    def starting(self):
        return False

    def describe(self):
        return "fake phone"

    def close(self):
        pass

    def wait_new(self, seq, timeout=1.0, not_before=0.0):
        Clock.t += 0.1
        self.tick()
        real_time.sleep(0.003)                                       # (the other threads get their turn)
        return seq + 1, Clock.t, self.picture(self.scene)


@unittest.skipIf(G is None, "gamebot.py cannot be imported here")
class FightLoop(unittest.TestCase):
    def setUp(self):
        self.saved = {n: getattr(G, n) for n in ("time", "log", "ocr_lines", "save_async", "MINIGAME_FILE")}
        self.saved_s = {n: getattr(S, n) for n in ("tap", "swipes", "screenshot", "on_map", "debug_save")}
        self.dir = tempfile.mkdtemp()
        G.time = Clock
        G.MINIGAME_FILE = os.path.join(self.dir, "minigame.json")
        G.save_async = lambda name, img: None
        S.on_map = lambda img: False
        S.debug_save = lambda *a, **k: None

    def tearDown(self):
        for n, v in self.saved.items():
            setattr(G, n, v)
        for n, v in self.saved_s.items():
            setattr(S, n, v)

    def play(self, video, tie=""):
        phone = Phone(video, tie)
        G.log = phone.logs.append
        G.ocr_lines = phone.ocr
        S.tap, S.swipes, S.screenshot = phone.tap, phone.swipe, phone.screenshot
        if video:
            res = G.fight_battle(stream=phone)
        else:
            old, G.FIGHT_VIDEO = G.FIGHT_VIDEO, False
            try:
                res = G.fight_battle()
            finally:
                G.FIGHT_VIDEO = old
        return phone, res

    def check_fight(self, phone, res):
        log = "\n".join(phone.logs)
        self.assertNotIn("error in the fight loop", log)
        self.assertEqual(res["result"], "loss", log)
        self.assertEqual(res["why"], "")
        throws = [t for t in phone.taps if t[0] == "fight_ready" and abs(t[2] - BV.BTN_Y) < 0.01]
        self.assertEqual(len(throws), 1, log)                         # one tap on a charged attack button ...
        self.assertIn("battle: throwing ", log)
        self.assertNotIn("the tap did not count", log)                # ... which counted
        answers = [t for t in phone.taps if t[0] == "shield_question" and t[2] > 0.6]
        self.assertEqual(len(answers), 1, log)                        # the shield question was answered once
        self.assertIn("shield question", log)
        nxt = [t for t in phone.taps if t[0] == "result_loss"]
        self.assertEqual([(t[1], t[2]) for t in nxt], [(0.5, round(int(BV.TAP_NEXT[1] * S.REF_H) / S.REF_H, 3))], log)
        self.assertIn("little game of ", log)
        return log

    def test_a_whole_fight_on_the_live_video(self):
        phone, res = self.play(video=True)
        log = self.check_fight(phone, res)
        self.assertIn("pictures from the live video", log)
        kind = "ghost" if phone.thrown == 0 else "flying"
        game = [s for scene, strokes in phone.swipes if scene == kind for s in strokes]
        self.assertGreater(len(game), 3, log)                         # the icons were swiped ...
        import battle_minigame as BMG
        icons = BMG.find_icons(phone.picture(kind), kind)
        for x, y in icons:                                            # ... every one of them lies on a swipe
            on = [s for s in game if BMG._near_line((x, y), (s[0] / S.REF_W, s[1] / S.REF_H, s[2] / S.REF_W,
                                                             s[3] / S.REF_H)) <= BMG.ICON_R]
            self.assertTrue(on, (kind, x, y))
        self.assertFalse([s for scene, s in phone.swipes if scene in ("shield_question", "result_loss")], log)
        self.assertRegex(log, r"little game of .* icons on \d+ picture")
        self.assertNotIn("no icons seen", log)
        answered = [line for line in phone.logs if "answered" in line][0]
        self.assertLess(float(answered.split("answered ")[1].split(" s")[0]), 1.0)     # well within the countdown

    def test_a_whole_fight_with_screenshots_only(self):
        phone, res = self.play(video=False)
        log = self.check_fight(phone, res)
        self.assertIn("no live video", log)
        # without the video the known pattern of the attack's type is swiped (blind) while its little game runs
        self.assertTrue(phone.swipes, log)
        self.assertIn("no icons seen", log)

    def icon_swipes(self, phone):
        return [s for scene, strokes in phone.swipes if scene in ("ghost", "flying") for s in strokes]

    def test_our_attack_comes_after_theirs(self):
        # both sides throw in the same turn and theirs goes first: the shield question comes up where the
        # little game was expected, and our attack (with its little game) follows their attack
        phone, res = self.play(video=True, tie="first")
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        throws = [t for t in phone.taps if t[0] == "fight_ready" and abs(t[2] - BV.BTN_Y) < 0.01]
        self.assertEqual(len(throws), 1, log)                         # (not thrown a second time)
        self.assertEqual(len([t for t in phone.taps if t[0] == "tie_question" and t[2] > 0.6]), 1, log)
        self.assertGreater(len(self.icon_swipes(phone)), 3, log)      # the icons were swiped all the same
        quiet = [sc for sc, _s in phone.swipes if sc in ("tie_question", "their_attack", "shield_question")]
        self.assertFalse(quiet, log)                                  # ... and nothing before they came
        self.assertRegex(log, r"little game of .* icons on \d+ picture.*it had to wait for the other side's attack")
        self.assertNotIn("did not start", log)

    def test_our_attack_does_not_come_after_theirs(self):
        # theirs goes first and our tap was not taken: after their attack the button is still lit - throw again
        phone, res = self.play(video=True, tie="lost")
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        throws = [t for t in phone.taps if t[0] == "fight_ready" and abs(t[2] - BV.BTN_Y) < 0.01]
        self.assertEqual(len(throws), 2, log)
        self.assertIn("the charged attack did not start", log)
        self.assertFalse([sc for sc, _s in phone.swipes if sc in ("tie_question", "their_attack", "fight_ready")], log)
        self.assertGreater(len(self.icon_swipes(phone)), 3, log)      # (the little game of the second throw)

    def test_a_question_ends_the_little_game_without_the_video(self):
        phone, res = self.play(video=False, tie="first")
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertIn("a question came up", log)                      # (nothing can be waited for without seeing it)
        self.assertFalse([sc for sc, _s in phone.swipes if sc in ("tie_question", "shield_question")], log)

    def test_fast_attacks_go_on_between_the_events(self):
        phone, _res = self.play(video=True)
        fast = [t for t in phone.taps if (t[1], t[2]) == (round(int(BV.TAP_FAST[0] * S.REF_W) / S.REF_W, 3),
                                                          round(int(BV.TAP_FAST[1] * S.REF_H) / S.REF_H, 3))]
        self.assertGreater(len(fast), 10)
        self.assertTrue([t for t in fast if t[0] == "fight_ready"])
        self.assertTrue([t for t in fast if t[0] == "run2_dim"])
        self.assertFalse([t for t in fast if t[0] == "result_loss"][3:])      # (hardly any on the result screen)


if __name__ == "__main__":
    unittest.main()
