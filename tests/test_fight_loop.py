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


FIGHT_SCENES = ("fight_ready", "day_start", "day_dim", "day_lit", "day_lines")     # the plain fight, buttons shown


class Phone:
    """What is on the screen, and what was done to it.

    Without a script the phone plays the fight of the first recording (by night): VS screen, the fight with both
    buttons lit, the little game of the attack that is thrown, the fight again, a shield question, the result.
    script: [(scene, how it ends), ...] for another story.  A scene ends after a number of seconds or with a
    tap: "throw" (a charged attack button), "ignore" (the same, but the game does not take the tap), "shield"
    (the shield or NOT NOW), "switch" (a tile of the switch question), "next" (NEXT BATTLE).  The scene "icons"
    is the little game of the attack that was thrown; "name#word" shows the picture `name` (to tell two
    scenes with the same picture apart)."""

    def __init__(self, video=True, tie="", script=None):
        self.video = video
        self.tie = tie                     # "first": the other side's charged attack goes first, ours follows it;
        self.tied = False                  # "lost": theirs goes first and ours was not thrown at all
        self.scene = "versus"
        self.since = Clock.t
        self.taps, self.swipes, self.logs = [], [], []
        self.thrown = None
        self.switched = None               # the tile that was tapped on the switch question (0: left, 1: right)
        self.boxes = 0
        self.pictures = {}
        self.script = list(script or [])
        self.step = -1
        if self.script:
            self.advance()

    def advance(self):
        self.step += 1
        if self.step < len(self.script):
            self.to(self.script[self.step][0])

    def ends_with(self):
        return self.script[self.step][1] if self.script and self.step < len(self.script) else None

    def picture(self, name, size=(704, 880)):
        name = name.split("#")[0]                                    # ("day_dim#wait": the picture day_dim)
        if name == "icons":
            name = "ghost" if self.thrown == 0 else "flying"
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
        if self.script:
            end = self.ends_with()
            if isinstance(end, (int, float)) and age > end:
                self.advance()
            return
        if self.scene == "versus" and age > 0.5:
            self.to("fight_ready")
        elif self.scene == "their_attack" and age > 2.0:             # the other side's attack is over:
            self.to("minigame_zoom" if self.tie == "first" else "fight_ready")   # ours follows - or the fight
        elif self.scene == "minigame_zoom" and age > 2.5:            # "Get Ready!" ...
            self.to("ghost" if self.thrown == 0 else "flying")       # ... then the icons
        elif self.scene in ("ghost", "flying") and age > 4.0:
            self.to("day_dim")                                       # the fight goes on, nothing lit
        elif self.scene == "day_dim" and age > 3.0:
            self.to("shield_question")

    def button(self, fx, fy):
        """The charged attack button at a spot (0 / 1), None when there is none."""
        if abs(fy - BV.BTN_Y) < 0.05:
            for i, bx in enumerate(BV.BTN_X):
                if abs(fx - bx) < 0.08:
                    return i
        return None

    def tap(self, x, y, ms=120):
        fx, fy = x / float(S.REF_W), y / float(S.REF_H)
        self.taps.append((self.scene, round(fx, 3), round(fy, 3)))
        answer = abs(fx - 0.5) < 0.2 and (abs(fy - BV.TAP_SHIELD[1]) < 0.05 or abs(fy - BV.TAP_NOT_NOW[1]) < 0.05)
        if self.script:
            end = self.ends_with()
            if end in ("throw", "ignore") and self.button(fx, fy) is not None:
                if end == "throw":
                    self.thrown = self.button(fx, fy)
                self.advance()
            elif end == "shield" and answer:
                self.advance()
            elif (end == "switch" and abs(fy - BV.POPUP_TILE_Y) < 0.06
                  and min(abs(fx - t) for t in BV.POPUP_TILES) < 0.09):
                self.switched = 0 if fx < 0.5 else 1
                self.advance()
            elif end == "next" and abs(fx - BV.TAP_NEXT[0]) < 0.15 and abs(fy - BV.TAP_NEXT[1]) < 0.03:
                self.advance()
        elif self.scene == "fight_ready" and self.button(fx, fy) is not None:
            self.thrown = self.button(fx, fy)
            if self.tie and not self.tied:                           # (the other side was a little earlier)
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
        scene = self.scene.split("#")[0]
        if y0 > 0.8 * img.shape[0]:                                  # the labels under the buttons
            return OCR["buttons_41"] if scene in FIGHT_SCENES else []
        if scene in ("result_loss", "day_result"):
            return OCR["result_135"]
        if scene in ("day_switch", "switch_popup"):                  # the question, and the CPs on its tiles
            return OCR["popup_cp_65"] if y0 >= 0.59 * img.shape[0] else OCR["question_65"]
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

    def play(self, video, tie="", script=None):
        phone = Phone(video, tie, script)
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
        self.assertTrue([t for t in fast if t[0] == "day_dim"])
        self.assertFalse([t for t in fast if t[0] == "result_loss"][3:])      # (hardly any on the result screen)

    # ---- the fight by day that went wrong (see test_battle_vision.py for the pictures) -------------------
    # (after the icons of the little game the attack itself is shown, with a banner: 'Noctowl used Shadow Ball!')
    DAY = [("versus", 0.5), ("day_intro", 2.0), ("day_start", 1.5), ("day_dim#first", 1.0), ("day_lit", "throw"),
           ("day_get_ready", 2.0), ("icons", 4.0), ("day_banner", 1.0), ("day_flash", 1.0), ("day_lines", 2.0),
           ("day_dim", 2.0), ("day_switch", "switch"), ("day_dim#next", 1.5), ("day_shield", "shield"),
           ("day_flash#theirs", 1.0), ("day_faint", 1.5), ("day_result", "next")]
    AFTER = ("icons", "day_banner", "day_flash")       # (the rows are swiped a second longer: the icons come back)

    def fast_taps(self, phone):
        spot = (round(int(BV.TAP_FAST[0] * S.REF_W) / S.REF_W, 3), round(int(BV.TAP_FAST[1] * S.REF_H) / S.REF_H, 3))
        return [t for t in phone.taps if (t[1], t[2]) == spot]

    def throws(self, phone):
        return [t for t in phone.taps if abs(t[2] - BV.BTN_Y) < 0.01 and min(abs(t[1] - x) for x in BV.BTN_X) < 0.01]

    def test_a_whole_fight_by_day(self):
        phone, res = self.play(video=True, script=self.DAY)
        log = "\n".join(phone.logs)
        self.assertNotIn("error in the fight loop", log)
        self.assertEqual(res["result"], "loss", log)
        # one charged attack was thrown, when a button was really lit: not at the intro ('Go, Noctowl!'), not
        # at an attack's flash, not when the white lines of the field ran through the label zones, not when
        # our Pokémon fainted
        self.assertEqual([t[0] for t in self.throws(phone)], ["day_lit"], log)
        self.assertEqual(log.count("battle: throwing "), 1, log)
        self.assertNotIn("did not start", log)
        self.assertIn("the fight has started", log)
        started = phone.logs.index(next(line for line in phone.logs if "the fight has started" in line))
        self.assertFalse([line for line in phone.logs[:started] if "throwing" in line], log)
        # its little game was played, and nothing was swiped anywhere else
        self.assertGreater(len([s for sc, strokes in phone.swipes if sc == "icons" for s in strokes]), 3, log)
        self.assertEqual({sc for sc, _s in phone.swipes} - {"day_get_ready"} - set(self.AFTER), set(), log)
        # the switch question was seen (its countdown is grey over the clouds) and answered with a tile
        self.assertIn(phone.switched, (0, 1), log)
        self.assertIn("battle: switching to ", log)
        tiles = [t for t in phone.taps if t[0] == "day_switch" and abs(t[2] - BV.POPUP_TILE_Y) < 0.06]
        self.assertEqual(len(tiles), 1, log)
        # the shield question too, and the result screen (clouds where the name boxes were) was not taken for
        # the fight: NEXT BATTLE was tapped
        # the shield question came a second and a half after the switch question: it is another question, and
        # it got its own answer (the shield or NOT NOW, not a second tap on the tile)
        answers = [t for t in phone.taps if t[0] == "day_shield" and t[2] > 0.6]
        self.assertEqual(len(answers), 1, log)
        self.assertEqual(answers[0][1], 0.5, log)
        self.assertIn("shield question", log)
        self.assertNotIn("still on the screen", log)
        # the result screen (clouds where the name boxes were) was not taken for the fight: NEXT BATTLE
        nxt = [t for t in phone.taps if t[0] == "day_result" and abs(t[2] - BV.TAP_NEXT[1]) < 0.01]
        self.assertEqual(len(nxt), 1, log)
        # and the fast attacks went on in between
        fast = {t[0] for t in self.fast_taps(phone)}
        self.assertTrue({"day_start", "day_dim#first", "day_lit", "day_lines", "day_dim", "day_dim#next"} <= fast, fast)

    def test_a_whole_fight_by_day_with_screenshots_only(self):
        phone, res = self.play(video=False, script=self.DAY)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertEqual([t[0] for t in self.throws(phone)], ["day_lit"], log)
        self.assertIn(phone.switched, (0, 1), log)
        self.assertNotIn("did not start", log)

    def test_a_tap_that_the_game_does_not_take(self):
        """The button is tapped and nothing happens: the plain fight stays on the screen (with its HP bars).
        Nothing may be swiped then - the rows of a ghost attack run right over the buttons - and the fast
        attacks go on; the next time a button is lit it is thrown as usual."""
        script = [("versus", 0.5), ("day_start", 1.0), ("day_lit#first", "ignore"), ("day_dim#wait", 7.0),
                  ("day_lit", "throw"), ("day_get_ready", 2.0), ("icons", 4.0), ("day_banner", 2.0), ("day_dim", 2.0),
                  ("day_shield", "shield"), ("day_result", "next")]
        phone, res = self.play(video=True, script=script)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertEqual([t[0] for t in self.throws(phone)], ["day_lit#first", "day_lit"], log)
        self.assertEqual(log.count(" did not start - the fight is still on the screen"), 1, log)
        self.assertEqual({sc for sc, _s in phone.swipes} - {"day_get_ready"} - set(self.AFTER), set(), log)
        self.assertGreater(len([t for t in self.fast_taps(phone) if t[0] == "day_dim#wait"]), 10, log)
        self.assertGreater(len([s for sc, strokes in phone.swipes if sc == "icons" for s in strokes]), 3, log)
        self.assertNotIn("started after all", log)
        gave_up = next(line for line in phone.logs if " did not start - " in line)
        self.assertLess(float(gave_up.split("screen ")[1].split(" s after")[0]), 4.0)   # (soon: about 3 s)
        self.assertRegex(log, r"1 charged attacks? with")             # (the one that was not thrown is not counted)

    def test_a_tap_that_is_not_taken_with_screenshots_only(self):
        script = [("versus", 0.5), ("day_start", 1.0), ("day_lit#first", "ignore"), ("day_dim#wait", 12.0),
                  ("day_lit", "throw"), ("day_get_ready", 2.0), ("icons", 4.0), ("day_banner", 2.0), ("day_dim", 2.0),
                  ("day_shield", "shield"), ("day_result", "next")]
        phone, res = self.play(video=False, script=script)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertEqual(log.count(" did not start - the fight is still on the screen"), 1, log)
        quiet = ("day_dim#wait", "day_lit#first", "day_lit", "day_start")
        self.assertFalse([sc for sc, _s in phone.swipes if sc in quiet], log)
        self.assertEqual([t[0] for t in self.throws(phone)], ["day_lit#first", "day_lit"], log)

    def test_the_fight_is_fought_on_its_hp_bars_when_the_name_boxes_are_not_seen(self):
        """The name boxes are known by their Poké Balls.  Should those ever not be recognised (an arena the bot
        has not seen, other colours on the video), the two HP bars are sign enough: the bot must not stand
        still through a whole fight."""
        script = [("versus", 0.5), ("day_intro", 1.5), ("day_start", 1.0), ("day_dim#first", 3.0), ("day_lit", "throw"),
                  ("day_get_ready", 2.0), ("icons", 4.0), ("day_banner", 2.0), ("day_dim", 2.0),
                  ("day_shield", "shield"), ("day_result", "next")]
        seen = BV.hud_visible
        BV.hud_visible = lambda img: False
        try:
            phone, res = self.play(video=True, script=script)
        finally:
            BV.hud_visible = seen
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertIn("fighting on the HP bars", log)
        self.assertEqual(log.count("fighting on the HP bars"), 1, log)
        self.assertIn("the fight has started", log)
        self.assertEqual([t[0] for t in self.throws(phone)], ["day_lit"], log)
        self.assertEqual(len([t for t in phone.taps if t[0] == "day_shield" and t[2] > 0.6]), 1, log)
        self.assertGreater(len([t for t in self.fast_taps(phone) if t[0] in ("day_dim#first", "day_lit", "day_dim")]), 10)

    def test_the_net_under_the_name_boxes_is_not_used_in_a_normal_fight(self):
        for story in (self.DAY, None):
            phone, _res = self.play(video=True, script=story)
            self.assertNotIn("fighting on the HP bars", "\n".join(phone.logs))

    def test_an_attack_that_starts_late(self):
        """The game takes the tap, but the attack only starts seconds later (after it was given up): its
        little game is played all the same, and no second attack is thrown meanwhile."""
        script = [("versus", 0.5), ("day_start", 1.0), ("day_lit", "throw"), ("day_dim#wait", 4.5),
                  ("day_get_ready", 2.0), ("icons", 4.0), ("day_banner", 2.0), ("day_dim", 2.0),
                  ("day_shield", "shield"), ("day_result", "next")]
        phone, res = self.play(video=True, script=script)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertEqual(len(self.throws(phone)), 1, log)
        self.assertIn(" did not start - the fight is still on the screen", log)
        self.assertIn("started after all", log)
        self.assertEqual({sc for sc, _s in phone.swipes} - set(self.AFTER), set(), log)   # (nothing blind this time)
        self.assertGreater(len([s for sc, strokes in phone.swipes if sc == "icons" for s in strokes]), 3, log)
        self.assertRegex(log, r"little game of .* icons on \d+ picture.*it did not start after the tap but came later")
        self.assertRegex(log, r"1 charged attacks? with")


if __name__ == "__main__":
    unittest.main()
