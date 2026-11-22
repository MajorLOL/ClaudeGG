"""The fight loop of gamebot.py from the first picture to NEXT BATTLE, with a fake phone (no adb, no OCR program).

The "phone" shows real pictures of fights (tests/fixtures) as its live video and reacts to what the bot does: a
tap on a charged attack button that is ready starts the little game of that attack (on one that is not ready it
is a fast attack like any other), a tap on the shield question ends it, and so on.  The text reader is replaced
by the lines it read from the same pictures (fixtures/fight/ocr.json).
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


FIGHT_SCENES = ("fight_ready", "day_start", "day_dim", "day_lit", "day_lines", "day2_ready_new", "day2_last",
                "day2_one_two")                                                    # the plain fight, buttons shown
NO_SHIELDS = ("no_shields", "day_no_shields", "day2_no_shields")                   # 'No Protect Shields remaining!'
# white words read on their own (gamebot.white_words), as the text reader gave them on these pictures: the banner
# of a charged attack and the big words of a result screen
BANNERS = {"day3_their_attack": "Pe Mismagius used Dark Pulse! Lm «",
           "day3_their_attack#mud": "Whiscash used Mud Bomb!", "day3_their_attack#blizzard": "Whiscash used Blizzard!"}
RESULT_WORDS = {"day3_win": "YOU WIN!"}


def name_line(name, cp, mine=False):
    """What the text reader gives for a name box ('NOCTOWL CP 1497' / 'CP 1482 DRAGALGE')."""
    words = [name.upper(), "CP", str(cp)] if mine else ["CP", str(cp), name.upper()]
    return [(" ".join(words), 60, 70, [(w, 60 + 200 * i, 70) for i, w in enumerate(words)])]


class Phone:
    """What is on the screen, and what was done to it.

    Without a script the phone plays the fight of the first recording (by night): VS screen, the fight with both
    buttons lit, the little game of the attack that is thrown, the fight again, a shield question, the result.
    script: [(scene, how it ends), ...] for another story.  A scene ends after a number of seconds or with a
    tap: "throw" (a charged attack button), "ignore" (the same, but the game does not take the tap), "shield"
    (the shield or NOT NOW), "switch" (a tile of the switch question), "run" (the button to leave the battle),
    "yes" (YES on 'Exit the Trainer Battle?'), "next" (NEXT BATTLE), "done" (the round check mark of a result
    screen).  The scene "icons" is the little game of the attack that was thrown; "name#word" shows the picture
    `name` (to tell two scenes with the same picture apart); "exit" is the question 'Exit the Trainer Battle?'
    (drawn: there is no recording of it).  "shield twice": a shield question that only takes the second tap.
    words: the big words of a result screen are read on their own (as the bot does first); False: that reading
    gives nothing and the whole screen is read, as before.  thrown: the attack whose icons are shown when no
    tap of the story throws one (0: the left button's).
    kinds: what each tap was - "throw" / "ignored" (a button whose attack was ready), "fast" (the place of the
    fast attacks, or a button that is not ready), "" (anything else).  The clock of this phone only moves with
    its pictures while the thread that taps runs on: tap_at / swipe_at say how many pictures of the scene had
    been shown when a tap or a swipe came (a tenth of a second each on the video)."""

    def __init__(self, video=True, tie="", script=None, names=None, words=True, thrown=None):
        self.video = video
        self.words = words
        self.lines_read = 0                # how often the whole screen of a result was read
        self.answers = 0                   # taps on a question that ends with "shield twice"
        self.log_at = []                   # the scene that was on when each line of the log was written
        self.names = names                 # (foe, cp, ours, cp) read in the name boxes from the start (None: the
        self.reads = []                    # usual story, see ocr()); reads: the scenes whose switch tiles were read
        self.tie = tie                     # "first": the other side's charged attack goes first, ours follows it;
        self.tied = False                  # "lost": theirs goes first and ours was not thrown at all
        self.scene = "versus"
        self.since = Clock.t
        self.taps, self.swipes, self.logs, self.kinds = [], [], [], []
        self.tap_at, self.swipe_at, self.frames = [], [], 0
        self.thrown = thrown               # the button of the attack that was thrown (0 / 1; its icons are shown)
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
            # (the other side's attack: its banner over the name boxes - 'Get Ready!' is only shown for ours)
            file = {"their_attack": "banner_over_hud", "tie_question": "shield_question", "exit": "day_dim",
                    "map_like": "versus"}.get(name, name)
            img = cv2.resize(cv2.imread(os.path.join(FIX, folder, file + ".jpg")), size, interpolation=cv2.INTER_AREA)
            if name == "exit":                                       # a white box with a green YES and a plain NO
                h, w = img.shape[:2]
                cv2.rectangle(img, (int(0.08 * w), int(0.30 * h)), (int(0.92 * w), int(0.72 * h)), (255, 255, 255), -1)
                cv2.rectangle(img, (int(0.27 * w), int(0.49 * h)), (int(0.73 * w), int(0.55 * h)), (110, 205, 120), -1)
            self.pictures[key] = img
        return self.pictures[key]

    def to(self, scene):
        self.scene, self.since, self.frames = scene, Clock.t, 0

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
        self.tap_at.append(self.frames)
        button = self.button(fx, fy)
        fast = abs(fx - BV.TAP_FAST[0]) < 0.01 and abs(fy - BV.TAP_FAST[1]) < 0.01
        self.kinds.append("fast" if fast or button is not None else "")
        answer = abs(fx - 0.5) < 0.2 and (abs(fy - BV.TAP_SHIELD[1]) < 0.05 or abs(fy - BV.TAP_NOT_NOW[1]) < 0.05)
        if self.script:
            end = self.ends_with()
            if end in ("throw", "ignore") and button is not None:
                self.kinds[-1] = "throw" if end == "throw" else "ignored"
                if end == "throw":
                    self.thrown = button
                self.advance()
            elif end == "shield" and answer:
                self.advance()
            elif end == "shield twice" and answer:                   # (the game does not take the first tap)
                self.answers += 1
                if self.answers >= 2:
                    self.advance()
            elif end == "run" and abs(fx - BV.RUN_BUTTON[0]) < 0.04 and abs(fy - BV.RUN_BUTTON[1]) < 0.03:
                self.advance()
            elif end == "yes" and abs(fx - 0.5) < 0.2 and abs(fy - 0.52) < 0.03:
                self.advance()
            elif (end == "switch" and abs(fy - BV.POPUP_TILE_Y) < 0.06
                  and min(abs(fx - t) for t in BV.POPUP_TILES) < 0.09):
                self.switched = 0 if fx < 0.5 else 1
                self.advance()
            elif end == "next" and abs(fx - BV.TAP_NEXT[0]) < 0.15 and abs(fy - BV.TAP_NEXT[1]) < 0.03:
                self.advance()
            elif end == "done" and abs(fx - BV.TAP_DONE[0]) < 0.05 and abs(fy - BV.TAP_DONE[1]) < 0.025:
                self.advance()
        elif self.scene == "fight_ready" and button is not None:
            self.thrown = button
            self.kinds[-1] = "throw"
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
        self.swipe_at.append(self.frames)
        real_time.sleep(0.002)

    def screenshot(self, on_grab=None):
        if not self.video:
            Clock.t += 1.3                                           # (a screenshot takes its time)
            self.tick()
            self.frames += 1
        return self.picture(self.scene, (S.REF_W, S.REF_H))

    def ocr(self, img, y0=0, y1=None, scale=1.0):
        if img.shape[0] < 400:                                       # a name box: the foe's is read first, then mine
            self.boxes += 1
            if self.names:
                foe, foe_cp, mine, cp = self.names
                return name_line(foe, foe_cp) if self.boxes % 2 else name_line(mine, cp, mine=True)
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
            self.lines_read += 1
            return OCR["result_135"]
        if scene == "day3_win":                                      # (of 'YOU WIN!' only 'WIN!' is read this way)
            self.lines_read += 1
            return OCR["result_win"]
        if scene in ("day_switch", "switch_popup"):                  # the question, and the CPs on its tiles
            if y0 >= 0.59 * img.shape[0]:
                self.reads.append(self.scene)
                return OCR["popup_cp_65"]
            return OCR["question_65"]
        if scene in NO_SHIELDS:
            return OCR["question_125"]
        return []

    def log(self, text):
        self.logs.append(text)
        self.log_at.append(self.scene)

    def line(self, img, lines=1):
        """White words read on their own: a banner at the top (one line) or the words of a result (two)."""
        scene = self.scene.split("#")[0]
        if lines == 1:
            return BANNERS.get(self.scene, BANNERS.get(scene, ""))
        if not self.words:
            return ""
        return RESULT_WORDS.get(scene, "GOOD EFFORT!" if scene in ("result_loss", "day_result") else "")

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
        if self.scene == "stall":                                    # ("stall", seconds) in a script: the video
            Clock.t += self.ends_with()                              # stands still, the next picture comes later
            self.advance()
        self.frames += 1
        real_time.sleep(0.003)                                       # (the other threads get their turn)
        return seq + 1, Clock.t, self.picture(self.scene)


@unittest.skipIf(G is None, "gamebot.py cannot be imported here")
class FightLoop(unittest.TestCase):
    def setUp(self):
        self.saved = {n: getattr(G, n) for n in ("time", "log", "ocr_lines", "ocr_line", "save_async", "MINIGAME_FILE",
                                                 "SEEN_FILE", "FIGHT_AIM", "battle_give_up")}
        self.saved_s = {n: getattr(S, n) for n in ("tap", "swipes", "screenshot", "on_map", "debug_save",
                                                   "tap_quick", "tap_motion")}
        self.dir = tempfile.mkdtemp()
        G.time = Clock
        G.FIGHT_AIM = False                # (the fast attacks stay in the middle: the tests of the aim switch it on)
        G.MINIGAME_FILE = os.path.join(self.dir, "minigame.json")
        G.SEEN_FILE = os.path.join(self.dir, "seen.json")
        G.save_async = lambda name, img: None
        S.on_map = lambda img: False
        S.debug_save = lambda *a, **k: None

    def tearDown(self):
        for n, v in self.saved.items():
            setattr(G, n, v)
        for n, v in self.saved_s.items():
            setattr(S, n, v)

    def play(self, video, tie="", script=None, names=None, words=True, thrown=None, map_scene=None):
        phone = Phone(video, tie, script, names, words, thrown)
        if map_scene:                      # (pictures of this scene are taken for the map)
            S.on_map = lambda img: phone.scene.split("#")[0] == map_scene
        G.log = phone.log
        G.ocr_lines = phone.ocr
        G.ocr_line = phone.line
        S.tap, S.swipes, S.screenshot = phone.tap, phone.swipe, phone.screenshot
        S.tap_quick = lambda x, y: phone.tap(x, y, 1)
        S.tap_motion = lambda x, y, ms=80: phone.tap(x, y, ms)
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
        return [t for t, kind in zip(phone.taps, phone.kinds) if kind == "fast"]

    def throws(self, phone):
        """The taps on a charged attack button whose attack was ready (taken by the game or not)."""
        return [t for t, kind in zip(phone.taps, phone.kinds) if kind in ("throw", "ignored")]

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
        # nothing was swiped over the plain fight while the attack was awaited; the banner 'Get Ready!' is the
        # sign that it starts after all, and from there the known rows are swiped again
        self.assertEqual({sc for sc, _s in phone.swipes} - {"day_get_ready"} - set(self.AFTER), set(), log)
        self.assertTrue([sc for sc, _s in phone.swipes if sc == "day_get_ready"], log)
        self.assertIn("'Get Ready!' - the little game of Shadow Ball starts", log)
        self.assertGreater(len([s for sc, strokes in phone.swipes if sc == "icons" for s in strokes]), 3, log)
        self.assertRegex(log, r"little game of .* icons on \d+ picture.*it did not start after the tap but came later")
        self.assertRegex(log, r"1 charged attacks? with")

    # ---- the fight in which the charged attacks came late (pictures day2_*) --------------------------------
    def button_taps(self, phone, kinds=("fast",)):
        """The taps on a charged attack button: [(scene, button)]."""
        return [(t[0], phone.button(t[1], t[2])) for t, kind in zip(phone.taps, phone.kinds)
                if kind in kinds and phone.button(t[1], t[2]) is not None]

    def test_a_button_is_thrown_before_its_ring_is_there(self):
        """The name under the button is white, the white ring has not come yet: that is thrown, not waited for."""
        script = [("versus", 0.5), ("day_start", 1.0), ("day2_ready_new", "throw"), ("day2_get_ready", 1.3),
                  ("icons", 4.0), ("day_banner", 1.0), ("day_dim", 2.0), ("day_shield", "shield"), ("day_result", "next")]
        phone, res = self.play(video=True, script=script)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertEqual([t[0] for t in self.throws(phone)], ["day2_ready_new"], log)
        thrown = next(line for line in phone.logs if "battle: throwing " in line)
        self.assertRegex(thrown, r"seen ready 0\.[0-2] s before")              # (two pictures, not a second)
        self.assertGreater(len([s for sc, strokes in phone.swipes if sc == "icons" for s in strokes]), 3, log)

    AIMED = [("versus", 0.5), ("day_start", 1.0), ("day_dim#first", 3.0), ("day_lit", "throw"), ("day_get_ready", 1.3),
             ("icons", 4.0), ("day_banner", 1.0), ("day_flash", 1.0), ("day_dim", 2.0), ("day_shield", "shield"),
             ("day_result", "next")]

    def test_the_fast_attacks_are_tapped_on_the_button_that_is_wanted(self):
        """While a charged attack charges that will be thrown the moment it is ready, the fast attacks are
        tapped on its button: the first tap after it is ready throws it, no picture has to be waited for."""
        G.FIGHT_AIM = True
        phone, res = self.play(video=True, script=self.AIMED)
        log = "\n".join(phone.logs)
        self.assertNotIn("error in the fight loop", log)
        self.assertEqual(res["result"], "loss", log)
        on_button = self.button_taps(phone)
        self.assertGreater(len([t for t in on_button if t[0] == "day_dim#first"]), 5, log)   # fast attacks, there
        self.assertEqual({b for _sc, b in on_button}, {0}, log)                # ... on Shadow Ball's button only
        self.assertEqual(self.button_taps(phone, ("throw",)), [("day_lit", 0)], log)        # thrown once, by a tap
        self.assertTrue("battle: throwing Shadow Ball" in log or "Shadow Ball was thrown by a tap on its button" in log)
        self.assertEqual(log.count("battle: throwing ") + log.count("was thrown by a tap on its button"), 1, log)
        # its little game was played from the banner on, and nothing was swiped over the fight itself
        self.assertGreater(len([s for sc, strokes in phone.swipes if sc == "icons" for s in strokes]), 3, log)
        self.assertEqual({sc for sc, _s in phone.swipes} - {"day_get_ready"} - set(self.AFTER), set(), log)
        # the button is only tapped in the plain fight: not on a question (the tiles of the switch question lie
        # there), not on the result screen - but for the tap that was on its way when the picture changed
        stray = [(t[0], at) for t, kind, at in zip(phone.taps, phone.kinds, phone.tap_at)
                 if kind == "fast" and phone.button(t[1], t[2]) is not None and at > 2
                 and t[0] in ("day_shield", "day_result", "versus", "day_banner", "day_flash", "icons")]
        self.assertEqual(stray, [], log)
        self.assertRegex(log, r"1 charged attacks? with")
        self.assertNotIn("do not seem to count", log)

    def test_before_the_buttons_are_read_the_fast_attacks_stay_in_the_middle(self):
        G.FIGHT_AIM = True
        phone, _res = self.play(video=True, script=self.AIMED)
        first = next(i for i, line in enumerate(phone.logs) if "fight: buttons are" in line)
        self.assertGreaterEqual(first, 1)
        middle = [t for t, kind in zip(phone.taps, phone.kinds) if kind == "fast" and phone.button(t[1], t[2]) is None]
        self.assertTrue([t for t in middle if t[0] == "day_start"], middle[:5])

    def test_an_attack_thrown_by_the_fast_taps_gets_its_little_game(self):
        """The tap landed in the instant the button became ready: no picture ever showed it ready and nothing
        was 'thrown' by the loop.  The banner 'Get Ready!' tells that our attack starts all the same."""
        G.FIGHT_AIM = True
        script = [("versus", 0.5), ("day_start", 1.0), ("day_dim#charging", 2.0), ("day_dim#first", "throw"),
                  ("day_get_ready", 1.3), ("icons", 4.0), ("day_banner", 1.0), ("day_flash", 1.0), ("day_dim", 2.0),
                  ("day_shield", "shield"), ("day_result", "next")]
        phone, res = self.play(video=True, script=script)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertNotIn("battle: throwing ", log)
        self.assertIn("'Get Ready!' - Shadow Ball was thrown by a tap on its button", log)
        self.assertEqual(phone.thrown, 0, log)
        game = [s for sc, strokes in phone.swipes if sc == "icons" for s in strokes]
        self.assertGreater(len(game), 3, log)
        self.assertTrue([sc for sc, _s in phone.swipes if sc == "day_get_ready"], log)   # (from the banner on)
        self.assertEqual({sc for sc, _s in phone.swipes} - {"day_get_ready"} - set(self.AFTER), set(), log)
        self.assertRegex(log, r"little game of Shadow Ball .*thrown by a tap of the fast attacks on its button")
        self.assertRegex(log, r"1 charged attacks? with")
        # no button is tapped while this attack runs (but for the tap that was on its way at the banner)
        stray = [(t[0], at) for t, at in zip(phone.taps, phone.tap_at)
                 if phone.button(t[1], t[2]) is not None and at > 2 and t[0] in ("day_get_ready", "icons", "day_banner")]
        self.assertEqual(stray, [], log)

    def test_fast_attacks_that_do_not_count_on_a_button_go_back_to_the_middle(self):
        """Should a tap on a button that is not ready not be a fast attack after all, the foe's HP stands still
        while the button is tapped: after ten seconds of that the middle of the screen is tapped again."""
        G.FIGHT_AIM = True
        script = [("versus", 0.5), ("day_start", 1.0), ("day_dim#still", 16.0), ("day_shield", "shield"),
                  ("day_result", "next")]
        phone, res = self.play(video=True, script=script)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertEqual(log.count("do not seem to count"), 1, log)
        self.assertFalse(G.FIGHT_AIM)                                          # (nor in the next fights of this run)
        taps = [(t, phone.button(t[1], t[2])) for t, kind in zip(phone.taps, phone.kinds)
                if kind == "fast" and t[0] == "day_dim#still"]
        self.assertTrue([t for t, b in taps if b is not None][:1], log)
        last = [b for _t, b in taps[-20:]]
        self.assertEqual(set(last), {None}, log)                               # the middle again, to the end

    def test_our_attack_comes_nine_seconds_after_theirs(self):
        """Both sides throw in the same turn and theirs goes first: the shield question, their attack with
        its banner, its animation - and only then 'Get Ready!' and our icons, nine seconds after the question.
        The little game is waited for all that time and played from the banner on."""
        script = [("versus", 0.5), ("day_start", 1.0), ("day2_ready_new", "throw"), ("day_shield", "shield"),
                  ("day_flash#shield", 2.5), ("day2_their_attack", 2.5), ("day2_blocked", 3.0),
                  ("day2_get_ready", 1.3), ("icons", 4.0), ("day_banner", 1.0), ("day_dim", 2.0),
                  ("day_shield#second", "shield"), ("day_result", "next")]
        phone, res = self.play(video=True, script=script)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertEqual(len(self.throws(phone)), 1, log)
        self.assertIn("'Get Ready!' - the little game of Shadow Ball starts (it waited for the other side's attack)", log)
        self.assertGreater(len([s for sc, strokes in phone.swipes if sc == "icons" for s in strokes]), 3, log)
        self.assertTrue([sc for sc, _s in phone.swipes if sc == "day2_get_ready"], log)
        quiet = ("day_shield", "day_flash#shield", "day2_their_attack", "day2_blocked", "day2_ready_new")
        self.assertFalse([sc for sc, _s in phone.swipes if sc in quiet], log)   # nothing before our banner
        self.assertNotIn("did not start", log)
        self.assertRegex(log, r"little game of Shadow Ball .* icons on \d+ picture.*it had to wait for the other side's")

    def test_the_switch_question_is_answered_at_once(self):
        """Its countdown can be nearly over when it comes up (three seconds were left in a recorded fight, and
        the game chose by itself): nothing is read on the video, the tiles stand in party order."""
        phone, res = self.play(video=True, script=self.DAY)
        log = "\n".join(phone.logs)
        self.assertEqual(phone.reads, [], log)                                 # (no reading of the small CP numbers)
        self.assertIn("by party order", log)
        line = next(x for x in phone.logs if "answered" in x and phone.logs[phone.logs.index(x) - 1].startswith(
            "battle: switching to "))
        self.assertLess(float(line.split("answered ")[1].split(" s")[0]), 0.35)
        self.assertIn(phone.switched, (0, 1))
        shots, _res = self.play(video=False, script=self.DAY)                  # (a screenshot is big enough to read)
        self.assertEqual(shots.reads, ["day_switch"])

    def test_the_swipes_stop_when_the_plain_fight_is_back(self):
        """The rows of a ghost attack are swiped a second longer than its icons are seen (they come back at the
        same places) - but not over the plain fight: its buttons lie right there."""
        script = [("versus", 0.5), ("day_start", 1.0), ("day_lit", "throw"), ("day_get_ready", 1.3), ("icons", 4.0),
                  ("day_dim#back", 3.0), ("day_shield", "shield"), ("day_result", "next")]
        phone, res = self.play(video=True, script=script)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        late = [at for (sc, _s), at in zip(phone.swipes, phone.swipe_at) if sc == "day_dim#back"]
        self.assertFalse([at for at in late if at > 2], log)                   # (what was on its way, no more)

    # ---- the fourth recording: the first win, the shields, the wrong little game --------------------------------
    WON = [("versus", 0.5), ("day_start", 1.0), ("day_dim", 2.0), ("day_shield", "shield"), ("day3_win", "done")]

    def test_a_fight_that_is_won_ends_with_the_check_mark(self):
        """'YOU WIN!' has no NEXT BATTLE button, only a small round one with a check mark.  The bot knew a
        result by NEXT BATTLE alone: it stood in front of its first win until the recording was stopped."""
        for video in (True, False):
            phone, res = self.play(video=video, script=self.WON)
            log = "\n".join(phone.logs)
            self.assertNotIn("error in the fight loop", log)
            self.assertEqual((res["result"], res["why"]), ("win", ""), log)
            self.assertIn("battle: the fight is over: win (YOU WIN!) - tapping the check mark", log)
            last = [t for t in phone.taps if t[0] == "day3_win"]
            self.assertEqual([(t[1], t[2]) for t in last],
                             [(0.5, round(int(BV.TAP_DONE[1] * S.REF_H) / S.REF_H, 3))], log)
            self.assertEqual(phone.step, len(self.WON), log)                   # (the check mark was hit)
            self.assertEqual(phone.lines_read, 0, log)                         # (the words were enough)

    def test_the_words_of_a_result_are_read_on_their_own_first(self):
        """'GOOD EFFORT!' and 'YOU WIN!' stand in big white letters over the trainer.  Read with the whole
        screen they come out in pieces (of YOU WIN! only WIN! was read); read on their own they are whole, also
        on the small picture of the video - no screenshot and no reading of the whole screen is needed."""
        phone, res = self.play(video=True)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertIn("the fight is over: loss (GOOD EFFORT!) - tapping NEXT BATTLE", log)
        self.assertEqual(phone.lines_read, 0, log)
        phone, res = self.play(video=True, words=False)                        # that reading gives nothing:
        log = "\n".join(phone.logs)                                            # the whole screen, as before
        self.assertEqual(res["result"], "loss", log)
        self.assertGreater(phone.lines_read, 0, log)
        self.assertIn("- tapping NEXT BATTLE", log)

    def test_a_win_that_is_not_read_is_left_with_the_check_mark_all_the_same(self):
        phone, res = self.play(video=True, script=self.WON, words=False)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "", log)                               # ('WIN!' alone says too little)
        self.assertIn("the fight is over: result not read", log)
        self.assertIn("- tapping the check mark", log)
        self.assertEqual(phone.step, len(self.WON), log)

    NOCTOWL_MISMAGIUS = ("Mismagius", 1460, "Noctowl", 1497)

    def answers(self, phone, scene):
        return [("SHIELD" if abs(t[2] - BV.TAP_SHIELD[1]) < 0.05 else "NOT NOW") for t in phone.taps
                if t[0] == scene and abs(t[1] - 0.5) < 0.2 and t[2] > 0.6]

    def test_a_hit_that_is_worth_it_gets_the_shield(self):
        """Mismagius throws at a Noctowl in good health.  The duel rule of the engine said 'survivable, keeping
        the shield' and the bot tapped NOT NOW - twice in the recorded battle, which ended with a shield
        unused.  A hit that takes a quarter of the HP bar is what a shield is for."""
        script = [("versus", 0.5), ("day_start", 2.5), ("day3_shield_last", "shield"), ("day_result", "next")]
        phone, res = self.play(video=True, script=script, names=self.NOCTOWL_MISMAGIUS)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertEqual(self.answers(phone, "day3_shield_last"), ["SHIELD"], log)
        self.assertRegex(log, r"shield question - SHIELD: Mystical Fire would take 27% of our HP")

    def test_a_small_hit_is_let_through(self):
        """Palossand's attacks (Shadow Ball, Earth Power) hardly touch a Noctowl: NOT NOW, the shield is kept."""
        script = [("versus", 0.5), ("day_start", 2.5), ("day3_shield_last", "shield"), ("day_result", "next")]
        phone, res = self.play(video=True, script=script, names=("Palossand", 1480, "Noctowl", 1497))
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertEqual(self.answers(phone, "day3_shield_last"), ["NOT NOW"], log)
        self.assertRegex(log, r"shield question - no shield \(NOT NOW\): .* is a small hit")

    def test_an_answer_that_is_not_taken_is_tapped_again_within_the_countdown(self):
        script = [("versus", 0.5), ("day_start", 2.5), ("day3_shield_last", "shield twice"), ("day_result", "next")]
        phone, res = self.play(video=True, script=script, names=self.NOCTOWL_MISMAGIUS)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertEqual(self.answers(phone, "day3_shield_last"), ["SHIELD", "SHIELD"], log)
        self.assertEqual(log.count("the question is still on the screen - tapping again"), 1, log)
        ats = [at for t, at in zip(phone.taps, phone.tap_at) if t[0] == "day3_shield_last" and t[2] > 0.6]
        self.assertLess(ats[1] - ats[0], 15, log)                              # (well within a second and a half)

    def test_the_banner_of_their_attack_tells_which_one_it_is(self):
        """'Mismagius used Dark Pulse!' - not one of the two attacks that are guessed for a Mismagius.  The
        banner is read next to the fight, and the next question is answered knowing what hits us."""
        script = [("versus", 0.5), ("day_start", 2.5), ("day3_shield_last", "shield"), ("day_flash#theirs", 4.5),
                  ("day3_their_attack", 2.5), ("day_start#on", 2.5), ("day3_shield_last#again", "shield"),
                  ("day_result", "next")]
        phone, res = self.play(video=True, script=script, names=self.NOCTOWL_MISMAGIUS)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertIn("fight: Mismagius used Dark Pulse - its charged attacks are taken to be Dark Pulse, Shadow Ball "
                      "now (the guess was Shadow Ball, Mystical Fire)", log)
        self.assertEqual(log.count("Mismagius used Dark Pulse"), 1, log)
        self.assertRegex(log, r"shield question - SHIELD: Dark Pulse would take 36% of our HP")
        self.assertEqual(self.answers(phone, "day3_shield_last#again"), ["SHIELD"], log)

    # ---- the fifth recording: a shield for a Mud Bomb ----------------------------------------------------------
    WHISCASH = ("Whiscash", 1496, "Noctowl", 1497)
    BAIT = [("versus", 0.5), ("day_start", 5.5), ("day3_shield_last", "shield"), ("day_flash#theirs", 4.5),
            ("day3_their_attack#mud", 2.5), ("day_start#on", 9.5), ("day3_shield_last#again", "shield"),
            ("day_flash#again", 4.5), ("day3_their_attack#blizzard", 2.5), ("day_result", "next")]

    def test_a_weak_attack_thrown_to_draw_a_shield_does_not_get_one(self):
        """Five seconds into the fight a Whiscash throws a charged attack.  Earlier battles have shown what a
        Whiscash has here: Mud Bomb (45 energy, a Noctowl hardly feels it) and Blizzard (75, it takes most of
        its HP).  After five seconds of Mud Shot it cannot have 75: it is the Mud Bomb, and the shield stays.
        Ten seconds of fight later the Blizzard is possible: that one gets the shield."""
        with open(G.SEEN_FILE, "w") as f:
            json.dump({"whiscash": {"MUD_BOMB": 2, "BLIZZARD": 2, "SCALD": 1}}, f)
        phone, res = self.play(video=True, script=self.BAIT, names=self.WHISCASH)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertIn("foe is Whiscash (CP 1496) - moves Mud Shot / Mud Bomb, Blizzard (as seen before)", log)
        self.assertEqual(self.answers(phone, "day3_shield_last"), ["NOT NOW"], log)
        self.assertRegex(log, r"shield question - no shield \(NOT NOW\): it can only be Mud Bomb \(Blizzard costs 75 "
                              r"energy, Whiscash has 5\d at most\) - Mud Bomb is a small hit")
        self.assertEqual(self.answers(phone, "day3_shield_last#again"), ["SHIELD"], log)
        self.assertRegex(log, r"shield question - SHIELD: Blizzard would take 83% of our HP")
        with open(G.SEEN_FILE) as f:                                           # (one more battle with each)
            self.assertEqual(json.load(f), {"whiscash": {"MUD_BOMB": 3, "BLIZZARD": 3, "SCALD": 1}})

    def test_the_first_whiscash_teaches_what_a_whiscash_has(self):
        """Nothing is known of it yet: its attacks are the recommended ones (Mud Bomb, Scald), Scald is possible
        after five seconds and Scald hurts - the shield goes, as it did in the recorded battle.  But what the
        banners of this battle say is written down for the next one."""
        phone, res = self.play(video=True, script=self.BAIT, names=self.WHISCASH)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertIn("foe is Whiscash (CP 1496) - moves Mud Shot / Mud Bomb, Scald", log)
        self.assertEqual(self.answers(phone, "day3_shield_last"), ["SHIELD"], log)
        self.assertIn("fight: Whiscash used Blizzard - its charged attacks are taken to be Mud Bomb, Blizzard now "
                      "(the guess was Mud Bomb, Scald)", log)
        with open(G.SEEN_FILE) as f:
            self.assertEqual(json.load(f), {"whiscash": {"MUD_BOMB": 1, "BLIZZARD": 1}})

    def test_seconds_without_a_picture_of_the_fight_count_as_fight(self):
        """The video stands still for three and a half seconds in the plain fight (screenrecord starts again
        every three minutes, a phone can stutter).  The Whiscash went on with its Mud Shots in that time: eight
        seconds have passed, not four and a half, and the Blizzard is possible - the shield goes up.  What is
        counted is the MOST energy the foe can have: in doubt, time counts."""
        with open(G.SEEN_FILE, "w") as f:
            json.dump({"whiscash": {"MUD_BOMB": 2, "BLIZZARD": 2}}, f)
        script = [("versus", 0.5), ("day_start", 4.0), ("stall", 3.5), ("day_start#on", 0.5),
                  ("day3_shield_last", "shield"), ("day_flash#theirs", 4.5), ("day3_their_attack#blizzard", 2.5),
                  ("day_result", "next")]
        phone, res = self.play(video=True, script=script, names=self.WHISCASH)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertEqual(self.answers(phone, "day3_shield_last"), ["SHIELD"], log)
        self.assertRegex(log, r"shield question - SHIELD: Blizzard would take 83% of our HP")

    def test_the_time_of_our_own_charged_attack_is_no_time_to_gain_energy(self):
        """We throw first: 'Get Ready!', the little game, the attack - nine seconds in which the game stands
        still for the Whiscash too.  Three seconds of fight before it and two after it: the Blizzard is still
        out of its reach when its attack comes, so that is the Mud Bomb."""
        with open(G.SEEN_FILE, "w") as f:
            json.dump({"whiscash": {"MUD_BOMB": 2, "BLIZZARD": 2}}, f)
        G.FIGHT_AIM = True                                           # (thrown by the fast taps on its button)
        phone, res = self.play(video=True, script=self.SKY, names=self.WHISCASH)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertIn("little game of ", log)
        # (how many seconds of fight came before the throw depends on when the tapper thread got its turn: 6 or 7)
        self.assertRegex(log, r"it can only be Mud Bomb \(Blizzard costs 75 energy, Whiscash has \d\d at most\)")
        answers = [t for t in phone.taps if t[0] == "day_shield" and abs(t[1] - 0.5) < 0.05 and t[2] > 0.6]
        self.assertEqual([round(t[2], 2) for t in answers], [round(BV.TAP_NOT_NOW[1], 2)], log)   # (NOT NOW, once)

    def test_one_picture_that_looks_like_the_map_does_not_end_the_fight(self):
        """22 November, 17:34: one picture of the loading screens before the fight was taken for the map, the
        loop ended ('back on the map') and the bot let the whole fight play out without a tap."""
        script = [("versus", 0.5), ("map_like", 0.15), ("versus#again", 0.5), ("day_start", 3.0),
                  ("day_result", "next")]
        phone, res = self.play(video=True, script=script, map_scene="map_like")
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertNotIn("back on the map", log)
        self.assertIn("the fight has started", log)

    def test_the_map_for_a_while_ends_the_loop(self):
        script = [("versus", 0.5), ("map_like", 5.0), ("day_result", "next")]
        phone, res = self.play(video=True, script=script, map_scene="map_like")
        self.assertEqual(res["why"], "back on the map", "\n".join(phone.logs))

    def test_a_fight_on_the_screen_is_known_before_the_menus_are_walked(self):
        """After the loop let go of a fight the walk through the menus saw 'other' screens for a minute; now
        battle_run first looks whether a fight is on the screen."""
        for scene, want in (("day_start", True), ("day3_shield_last", True), ("versus", False),
                            ("day_result", False)):
            S.screenshot = lambda on_grab=None, sc=scene: Phone().picture(sc, (S.REF_W, S.REF_H))
            self.assertEqual(G._fight_on_screen(), want, scene)

    def test_a_fight_the_loop_let_go_of_is_fought_all_the_same(self):
        """22 November, 17:34: the fight loop ended at once ('back on the map') and the fight went on without
        the bot, which walked the menus and saw 'other' screens.  Now battle_run sees the fight on the screen
        and fights it."""
        names = ("battle_open_menu", "fight_battle", "_fight_on_screen", "_battle_to_map")
        saved = {n: getattr(G, n) for n in names}
        fights, logs = [], []
        G.log = logs.append
        G.battle_open_menu = lambda *a, **k: {"ok": True, "title": "GREAT LEAGUE", "members": [],
                                              "use_spots": [(884, 1930)]}
        G.fight_battle = lambda *a, **k: fights.append(len(a)) or (
            {"result": "", "why": "back on the map"} if len(fights) == 1 else {"result": "win", "why": ""})
        G._fight_on_screen = lambda: True
        G._battle_to_map = lambda *a, **k: True
        S.tap = lambda *a, **k: None
        S.on_map = lambda img: True
        S.screenshot = lambda *a, **k: Phone().picture("day_start")
        try:
            res = G.battle_run(lambda: None, lambda: False, 2, team=[])
        finally:
            for n, f in saved.items():
                setattr(G, n, f)
        self.assertEqual((res["fought"], res["wins"]), (1, 1), logs)
        self.assertIn("battle: a fight is on the screen - fighting it", logs)
        self.assertEqual(fights, [4, 3], logs)               # (the second without the spots of USE THIS PARTY)

    def test_a_grey_battle_button_ends_the_battles_of_the_day(self):
        saved = (G.BATTLE_DONE_FILE, G.setting)
        G.BATTLE_DONE_FILE = os.path.join(self.dir, "done.json")
        G.setting = lambda key, default=None: True if key == "battle" else default
        try:
            self.assertTrue(G.battle_wanted())
            G.battles_done_today(True)
            self.assertFalse(G.battle_wanted())
            with open(G.BATTLE_DONE_FILE, "w") as f:
                json.dump({"day": "2026-11-21"}, f)                    # (yesterday: today it starts again)
            self.assertTrue(G.battle_wanted())
        finally:
            G.BATTLE_DONE_FILE, G.setting = saved

    def test_a_title_with_a_word_missing_after_the_league_was_chosen(self):
        """22 November, 18:42: the party screen was read as '2026 LEAGUE EDITION' (GREAT missing), and the bot
        went back without a fight - although it had chosen 'GREAT LEAGUE EDITION' on the list itself."""
        names = ("battle_open_menu", "fight_battle", "_battle_to_map", "battle_league")
        saved = {n: getattr(G, n) for n in names}
        logs = []
        G.log = logs.append
        G.battle_league = lambda: "Great League"
        G._battle_to_map = lambda *a, **k: True
        S.tap = lambda *a, **k: None
        S.on_map = lambda img: True
        S.screenshot = lambda *a, **k: Phone().picture("day_start")
        try:
            for title, chosen, want in (("2026 LEAGUE EDITION", "GREAT LEAGUE EDITION", 1),
                                        ("2026 LEAGUE EDITION", None, 0),
                                        ("ULTRA LEAGUE", "GREAT LEAGUE EDITION", 0)):
                G.battle_open_menu = lambda *a, t=title, c=chosen, **k: {
                    "ok": True, "title": t, "chosen": c, "members": [], "use_spots": [(884, 1930)]}
                G.fight_battle = lambda *a, **k: {"result": "win", "why": ""}
                res = G.battle_run(lambda: None, lambda: False, 1, team=[])
                self.assertEqual(res["fought"], want, (title, chosen, logs[-3:]))
        finally:
            for n, f in saved.items():
                setattr(G, n, f)
        self.assertTrue(any("was chosen on the list just now" in line for line in logs), logs)

    def test_the_app_that_fights_is_played_first(self):
        """22 November, 18:51: the daily run started the Play Store app first, while the one that fights battles
        (the other one) was open already - the battles came only after a whole game of spinning and catching."""
        names = ("game_packages", "battle_wanted", "battle_app")
        saved = {n: getattr(G, n) for n in names}
        try:
            G.game_packages = lambda: ["com.nianticlabs.pokemongo", "com.nianticlabs.pokemongo.ares"]
            G.battle_app = lambda: "com.nianticlabs.pokemongo.ares"
            G.battle_wanted = lambda: True
            self.assertEqual(G.daily_order(), ["com.nianticlabs.pokemongo.ares", "com.nianticlabs.pokemongo"])
            G.battle_wanted = lambda: False                          # (no battles, or done for today)
            self.assertEqual(G.daily_order(), ["com.nianticlabs.pokemongo", "com.nianticlabs.pokemongo.ares"])
            G.battle_wanted = lambda: True
            G.battle_app = lambda: "com.nianticlabs.pokemongo.other"  # (not installed: the usual order)
            self.assertEqual(G.daily_order(), ["com.nianticlabs.pokemongo", "com.nianticlabs.pokemongo.ares"])
        finally:
            for n, f in saved.items():
                setattr(G, n, f)

    def test_the_switch_tile_is_tried_with_other_kinds_of_touch(self):
        """22 November, 19:39: eleven presses on the tile of Lanturn, none counted, the game chose Lapras.  The
        retaps now try other kinds of touch, and the log says which."""
        script = [("versus", 0.5), ("day_start", 1.0), ("day_switch", 6.0), ("day_result", "next")]
        phone, res = self.play(video=True, script=script)
        log = "\n".join(phone.logs)
        self.assertIn("battle: switching to ", log)
        for how in ("quick tap", "finger down and up", "press 60 ms", "press 220 ms"):
            self.assertIn(f"tapping again ({how} at", log)
        taps = [t for t in phone.taps if t[0] == "day_switch" and t[2] > 0.6]    # (on the tiles, not fast taps)
        self.assertGreaterEqual(len(taps), 5, log)
        self.assertEqual(len({t[1] for t in taps}), 1, taps)                  # (always the same tile)

    def test_a_file_that_cannot_be_read_is_no_trouble(self):
        with open(G.SEEN_FILE, "w") as f:
            f.write("{ not json")
        self.assertEqual(G.load_seen(), {})
        phone, res = self.play(video=True, script=self.BAIT, names=self.WHISCASH)
        self.assertEqual(res["result"], "loss", "\n".join(phone.logs))
        self.assertEqual(G.load_seen(), {"whiscash": {"MUD_BOMB": 1, "BLIZZARD": 1}})

    SKY = [("versus", 0.5), ("day_start", 1.0), ("day_dim#charging", 2.0), ("day_dim#first", "throw"),
           ("day3_get_ready_sky", 1.3), ("icons", 4.0), ("day_banner", 1.0), ("day_flash", 1.0), ("day_dim", 2.0),
           ("day_shield", "shield"), ("day_result", "next")]

    def ghost_rows_swiped(self, phone, scenes=("icons",)):
        import battle_minigame as BMG
        game = [s for sc, strokes in phone.swipes if sc in scenes for s in strokes]
        for x, y in BMG.find_icons(phone.picture("ghost"), "ghost"):
            on = [s for s in game if BMG._near_line((x, y), (s[0] / S.REF_W, s[1] / S.REF_H, s[2] / S.REF_W,
                                                             s[3] / S.REF_H)) <= BMG.ICON_R]
            self.assertTrue(on, (x, y))
        return game

    def test_the_sky_behind_get_ready_is_not_the_other_attack(self):
        """By day the sky behind the banner 'Get Ready!' gave four "flying" icons: a Shadow Ball that the fast
        taps had thrown was swiped as a Sky Attack (a line from top to bottom, right of the middle) while its
        ghosts came up elsewhere.  The fast attacks were tapped on Shadow Ball's button: it is that attack."""
        import battle_minigame as BMG
        img = phone_picture = Phone().picture("day3_get_ready_sky")
        self.assertGreaterEqual(len(BMG.find_icons(img, "flying")), 3)         # (the picture that did it)
        self.assertIsNotNone(phone_picture)
        G.FIGHT_AIM = True
        phone, res = self.play(video=True, script=self.SKY)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertIn("'Get Ready!' - Shadow Ball was thrown by a tap on its button", log)
        self.assertNotIn("the icons are those of", log)
        self.assertRegex(log, r"little game of Shadow Ball \(ghost\)")
        self.assertGreater(len(self.ghost_rows_swiped(phone)), 3, log)

    def test_a_guessed_attack_is_not_swapped_on_the_banner_either(self):
        """Nobody saw which button was thrown (no fast taps on a button): Shadow Ball is a guess, and the icons
        may tell that it was the other attack - but not the sky behind the banner."""
        script = [sc for sc in self.SKY if sc[0] != "day_dim#first"]
        phone, res = self.play(video=True, script=script, thrown=0)            # (ghosts come up)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertIn("'Get Ready!' - Shadow Ball was thrown by a tap on its button", log)
        self.assertNotIn("the icons are those of", log)
        self.assertGreater(len(self.ghost_rows_swiped(phone)), 3, log)

    def test_the_icons_tell_when_the_guess_was_wrong(self):
        script = [sc for sc in self.SKY if sc[0] != "day_dim#first"]
        phone, res = self.play(video=True, script=script, thrown=1)            # (wings come by: it was Sky Attack)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        said = [at for line, at in zip(phone.logs, phone.log_at) if "the icons are those of Sky Attack" in line]
        self.assertEqual(said, ["icons"], log)                                 # (on the icons, not on the banner)
        self.assertRegex(log, r"little game of Sky Attack \(flying\)")

    def test_a_gap_in_the_icons_does_not_end_the_little_game(self):
        """The smoke of a Shadow Ball lay over its ghosts for two seconds: the bot took the game for over, went
        back to the fast attacks and let the ghosts that still came go by."""
        script = [("versus", 0.5), ("day_start", 1.0), ("day_lit", "throw"), ("day_get_ready", 1.3), ("icons", 1.5),
                  ("day3_ghost_hidden", 2.2), ("icons#again", 1.5), ("day_banner", 1.0), ("day_dim#back", 3.0),
                  ("day_shield", "shield"), ("day_result", "next")]
        phone, res = self.play(video=True, script=script)
        log = "\n".join(phone.logs)
        self.assertEqual(res["result"], "loss", log)
        self.assertEqual(phone.thrown, 0, log)
        self.assertGreater(len(self.ghost_rows_swiped(phone, ("icons#again",))), 3, log)   # still in the game
        self.assertTrue([sc for sc, _s in phone.swipes if sc == "day3_ghost_hidden"], log)   # (its rows, unseen)
        fast = [at for t, kind, at in zip(phone.taps, phone.kinds, phone.tap_at)
                if kind == "fast" and t[0] in ("day3_ghost_hidden", "icons#again") and at > 2]
        self.assertEqual(fast, [], log)                                        # no fast attacks in between
        self.assertEqual(log.count("battle: little game of Shadow Ball"), 1, log)
        late = [at for (sc, _s), at in zip(phone.swipes, phone.swipe_at) if sc == "day_dim#back"]
        self.assertFalse([at for at in late if at > 2], log)                   # (and nothing over the plain fight)

    # ---- giving up a fight that is lost ---------------------------------------------------------------------
    LAST = ("Dragalge", 1482, "Lanturn", 1494)             # the names in the boxes of day2_last / day2_no_shields
    LOST = [("versus", 0.5), ("day2_last", 2.5), ("day2_no_shields", "run"), ("exit", "yes"), ("day_result", "next")]

    def dragalge_known(self):
        """Earlier battles showed what this Dragalge has: Outrage and Gunk Shot - either takes all of Lanturn's
        59 HP (the guess, Aqua Tail and Outrage, has an attack that does not: then nothing is given up)."""
        with open(G.SEEN_FILE, "w") as f:
            json.dump({"dragalge": {"OUTRAGE": 2, "GUNK_SHOT": 2}}, f)

    def run_taps(self, phone):
        return [t for t in phone.taps if abs(t[1] - BV.RUN_BUTTON[0]) < 0.02 and abs(t[2] - BV.RUN_BUTTON[1]) < 0.02]

    def test_a_lost_fight_is_given_up(self):
        """Our last Pokémon, a third of its HP left, no shield - and 'No Protect Shields remaining!': the
        attack that comes ends the fight.  The button with the running trainer, then YES."""
        self.dragalge_known()
        phone, res = self.play(video=True, script=self.LOST, names=self.LAST)
        log = "\n".join(phone.logs)
        self.assertNotIn("error in the fight loop", log)
        self.assertEqual((res["result"], res["gave_up"]), ("loss", True), log)
        self.assertIn("battle: giving up - Lanturn is our last Pokémon", log)
        self.assertIn("'Exit the Trainer Battle?' - YES", log)
        self.assertEqual([t[0] for t in self.run_taps(phone)], ["day2_no_shields"], log)
        yes = [t for t in phone.taps if t[0] == "exit"]
        self.assertEqual(len(yes), 1, log)
        self.assertAlmostEqual(yes[0][1], 0.5, delta=0.05)
        self.assertAlmostEqual(yes[0][2], 0.52, delta=0.02)
        self.assertIn("the fight is over: loss - given up", log)
        self.assertIn("(given up)", phone.logs[-1])
        self.assertIn("another Poké Ball of ours is grey", log)                # (how it knew this was the last one)

    def test_a_lost_fight_is_given_up_with_screenshots_only(self):
        self.dragalge_known()
        # (a screenshot every 1.3 s: it takes a few of them to know who is on the field and how much HP it has)
        script = [("day2_last", 9.0) if scene == "day2_last" else (scene, end) for scene, end in self.LOST]
        phone, res = self.play(video=False, script=script, names=self.LAST)
        log = "\n".join(phone.logs)
        self.assertEqual((res["result"], res["gave_up"]), ("loss", True), log)
        self.assertEqual(len(self.run_taps(phone)), 1, log)

    def test_nothing_is_given_up_when_the_option_is_off(self):
        G.battle_give_up = lambda: False
        script = [("versus", 0.5), ("day2_last", 2.5), ("day2_no_shields", 3.0), ("day_result", "next")]
        phone, res = self.play(video=True, script=script, names=self.LAST)
        log = "\n".join(phone.logs)
        self.assertEqual((res["result"], res["gave_up"]), ("loss", False), log)
        self.assertEqual(self.run_taps(phone), [], log)
        self.assertNotIn("battle: giving up", log)
        self.assertIn("an attack is coming and we have no shields left", log)
        self.assertIn("battle: not giving up - the option 'Give up a lost battle' is off", log)   # (the log says why)

    def test_an_attack_the_foe_cannot_pay_for_is_no_reason_to_give_up(self):
        """The same end, but the Dragalge has only been fighting for four seconds: it cannot have the energy
        for its Outrage (60), and its Aqua Tail does not knock a Lanturn out.  The fight goes on - and the log
        says why, so that a lost end that was played out can be understood afterwards."""
        script = [("versus", 0.5), ("day2_last", 4.0), ("day2_no_shields", 3.0), ("day_result", "next")]
        phone, res = self.play(video=True, script=script, names=self.LAST)
        log = "\n".join(phone.logs)
        self.assertEqual((res["result"], res["gave_up"]), ("loss", False), log)
        self.assertEqual(self.run_taps(phone), [], log)
        self.assertRegex(log, r"battle: not giving up - Dragalge's Aqua Tail does \d+, Lanturn has \d+ HP "
                              r"\(its other attack costs more energy than it can have\)")

    def test_a_question_that_does_not_come_up_changes_nothing(self):
        """The button to leave is tapped and the game does not ask: the fight goes on to its end, and the
        button is not tapped a second time."""
        self.dragalge_known()
        script = [("versus", 0.5), ("day2_last", 2.5), ("day2_no_shields", 6.0), ("day2_last#on", 4.0),
                  ("day2_no_shields#again", 2.0), ("day_result", "next")]
        phone, res = self.play(video=True, script=script, names=self.LAST)
        log = "\n".join(phone.logs)
        self.assertEqual((res["result"], res["gave_up"]), ("loss", False), log)
        self.assertEqual(len(self.run_taps(phone)), 1, log)
        self.assertIn("the question to leave the battle did not come up - fighting on", log)
        self.assertIn("battle: not giving up - it was tried before in this battle", log)
        self.assertTrue([t for t in self.fast_taps(phone) if t[0] == "day2_last#on"], log)   # (the fight went on)

    def test_no_attack_is_the_end_while_another_pokemon_can_fight(self):
        """The same question on a Pokémon that is not our last one: the fight goes on."""
        script = [("versus", 0.5), ("day_dim", 2.5), ("day_no_shields", 3.0), ("day_dim#on", 1.0),
                  ("day_shield", "shield"), ("day_result", "next")]
        phone, res = self.play(video=True, script=script)
        log = "\n".join(phone.logs)
        self.assertEqual(res["gave_up"], False, log)
        self.assertEqual(self.run_taps(phone), [], log)

    ONE_TWO = ("Hitmonchan", 1487, "Lanturn", 1494)        # day2_one_two: our last one against two of theirs

    def test_one_against_two_is_given_up_when_the_duel_is_lost(self):
        """Not at the first look: the fight has to be found lost four times in a row, over three seconds."""
        import battle_fight as BF
        real = BF.Fight.hopeless
        calls = []

        def hopeless(fight, foes):
            calls.append((fight.me.label, foes, Clock.t))
            return (len(fight.alive()) == 1 and foes == 2), "Lanturn is our last Pokémon and loses (told by the test)"

        BF.Fight.hopeless = hopeless
        try:
            script = [("versus", 0.5), ("day2_one_two", "run"), ("exit", "yes"), ("day_result", "next")]
            phone, res = self.play(video=True, script=script, names=self.ONE_TWO)
        finally:
            BF.Fight.hopeless = real
        log = "\n".join(phone.logs)
        self.assertEqual((res["result"], res["gave_up"]), ("loss", True), log)
        self.assertIn("battle: giving up - Lanturn is our last Pokémon and loses", log)
        lost = [c for c in calls if c[0] == "Lanturn"]
        self.assertGreaterEqual(len(lost), G.GIVE_UP_LOOKS, log)
        self.assertGreaterEqual(lost[-1][2] - lost[0][2], (G.GIVE_UP_LOOKS - 1) * G.GIVE_UP_EVERY - 0.2, log)
        self.assertEqual({c[1] for c in calls}, {2}, log)                      # (two red Poké Balls on their side)
        self.assertEqual(len(self.run_taps(phone)), 1, log)

    def test_one_against_two_is_fought_while_the_duel_can_be_won(self):
        """The real engine on the real picture: Lanturn (90 % HP) beats Hitmonchan (45 %) - it did."""
        script = [("versus", 0.5), ("day2_one_two", 6.0), ("day_shield", "shield"), ("day_result", "next")]
        phone, res = self.play(video=True, script=script, names=self.ONE_TWO)
        log = "\n".join(phone.logs)
        self.assertEqual(res["gave_up"], False, log)
        self.assertEqual(self.run_taps(phone), [], log)
        self.assertNotIn("giving up", log)


if __name__ == "__main__":
    unittest.main()
