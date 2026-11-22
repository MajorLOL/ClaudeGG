#!/usr/bin/env python3
"""The brain of one GO Battle League fight: what was seen in, what to do out.

No phone, no OCR, no OpenCV in here (gamebot.py takes the pictures and reads them with battle_vision.py and
battle_nav.py): this module only keeps the state of the fight and takes the decisions with the PvPoke rules of
battle_engine.py.  That keeps it testable anywhere.

What the fight loop in gamebot.py does with it:

    fight = Fight(team)
    fight.see(features)                  every picture with the HUD on it: HP bars, shield icons, lit buttons
    fight.set_foe(name, cp)              the foe's name box (when fight.foe_due: every few pictures)
    fight.set_active(cp)                 the CP in my own name box: who is really on the field
    fight.set_buttons(left, right)       the move names under the charged attack buttons (when fight.need_labels)
    fight.throw()                        -> (button 0 / 1, Move, why) or None: a charged attack to throw now
    fight.shield()                       -> (True / False, why): the question "Use a Protect Shield?"
    fight.switch(tiles)                  -> (index of the tile, Mon, why): "Switch in a new Pokémon?"

What it cannot see is estimated: the energy from which buttons are lit (a lit button means the energy is at
least its cost), the foe's moves from PvPoke's recommended moveset for its species, an incoming attack is taken
to be the foe's hardest one.
"""
import difflib

import battle_engine as BE

HP_JUMP = 0.30            # a bigger change between two pictures has to be seen twice before it is believed
UNKNOWN_FOE_SHIELD_BELOW = 0.5   # (foe not known) shield when our HP is below this fraction
FAINTED_BELOW = 0.25      # a Pokémon with less HP than this that is replaced has fainted
LABEL_TRIES = 8           # pictures to read the labels under the buttons from (they are hidden at times)
FOE_CHECK_EVERY = 3       # read the name boxes again every this many pictures with the HUD (a new foe comes in
                          # without a sign other than its name)
SHIELDS_BACK = 6          # pictures in a row that show more shields of ours than we counted: believe them
FOE_RETRY = 8             # a name box that gave nothing is read again after this many pictures at most
GOING_DOWN_HP = 0.20      # our HP below this part of the full bar: we are about to faint ...
GOING_DOWN_FAST = 4       # ... or it is no more than this many fast attacks of the foe


class Fight:
    def __init__(self, team, log=None):
        self.team = list(team)
        self.log = log or (lambda _m: None)
        self.me = self.team[0]                 # the Pokémon on the field (the game starts with the first one)
        self.foe = None                        # a Mon guessed from the name box, None while it is not known
        self.my_shields = 2
        self.foe_shields = 2
        self.my_hp = 1.0                       # fractions of the full HP bar
        self.foe_hp = 1.0
        self.lit = (False, False)              # charged attack buttons that are lit (enough energy)
        self.slots = [None, None]              # move id under the left / right button, None: party order
        self.labels_ok = False
        self.foe_cp = None
        self.foe_every = FOE_CHECK_EVERY       # (gamebot sets a higher number for the live video: ~10 pictures a second)
        self.since_foe = 10 ** 6               # HUD pictures since the foe's name box was read (read it now)
        self._foe_miss = ""                    # the last name that was not recognised (not logged twice)
        self.need_labels = True
        self.label_tries = 0
        self.dead = set()                      # party positions of Pokémon that fainted
        self.throws = 0
        self._pending = {}                     # unconfirmed big changes: side -> value
        self._shield_seen = {}                 # unconfirmed shield counts: side -> value
        self.shields_back = SHIELDS_BACK       # (gamebot sets a higher number for the live video, as foe_every)
        self._shield_more = 0                  # pictures in a row that show more shields of ours than counted
        self._shield_more_n = None
        self.tile = (0, 1)                     # where the Pokémon chosen by switch() stands: (place, tiles)

    # ------------------------------------------------------------ what is seen ---
    def _believe(self, side, old, new):
        """New HP fraction of one side: small steps are taken at once, a big jump has to be seen twice (the
        readings are wrong now and then while a banner covers the bar)."""
        if new is None:
            return old
        if abs(new - old) <= HP_JUMP:
            self._pending.pop(side, None)
            return new
        prev = self._pending.get(side)
        if prev is not None and abs(prev - new) <= 0.06:
            self._pending.pop(side, None)
            return new
        self._pending[side] = new
        return old

    def see(self, feat):
        """A picture of the fight (features from battle_vision.features).  The HP bars are read from every
        picture; the shield icons and the lit buttons only when the HUD is on it (they are wrong without)."""
        mine, foe = feat["hp"]
        old = self.my_hp
        self.my_hp = self._believe("me", self.my_hp, mine)
        if old < self.my_hp <= old + HP_JUMP:  # (a Pokémon never heals: a small rise is a misread)
            self.my_hp = old
        elif old < FAINTED_BELOW and self.my_hp > 0.6:
            self._came_in()                    # (a full bar after a nearly empty one: the next one of ours)
        self.me.hp = int(round(self.my_hp * self.me.max_hp))
        old = self.foe_hp
        new = self._believe("foe", self.foe_hp, foe)
        if new > old + HP_JUMP:                # the foe's HP went up: its next Pokémon is on the field
            self.log("fight: the foe's HP bar is full again - a new foe")
            self.since_foe = 10 ** 6           # (read its name now)
        elif new > old:
            new = old
        self.foe_hp = new
        if self.foe:
            self.foe.hp = int(round(self.foe_hp * self.foe.max_hp))
        if feat["hud"] and not feat["white"]:
            self.since_foe += 1
            self._see_shields(feat["shields"])
            self.lit = tuple(feat["ready"])
            self._calibrate()

    def _see_shields(self, sh):
        """Shield icons: a lower number is believed after two pictures that agree.  The foe's never goes up.
        Ours does, after SHIELDS_BACK pictures that agree: we counted a shield as used, but the tap came too
        late and the game did not use it.  (The icon of a shield that IS used turns grey within two seconds.)"""
        for side, now in (("me", self.my_shields), ("foe", self.foe_shields)):
            n = sh.get(side)
            if side == "me" and n is not None and n > now:
                self._shield_more = self._shield_more + 1 if self._shield_more_n == n else 1
                self._shield_more_n = n
                if self._shield_more >= self.shields_back:
                    self.log(f"fight: we still have {n} shield(s) - one that was counted as used was not used")
                    self.my_shields = n
                    self._shield_more = 0
                self._shield_seen.pop(side, None)
                continue
            if side == "me":
                self._shield_more = 0
            if n is None or n >= now:
                self._shield_seen.pop(side, None)
                continue
            if self._shield_seen.get(side) == n:
                self._shield_seen.pop(side, None)
                if side == "me":
                    self.my_shields = n
                else:
                    self.foe_shields = n
                    self.log(f"fight: the foe has {n} shield(s) left")
            else:
                self._shield_seen[side] = n

    @property
    def foe_due(self):
        """Time to read the name boxes again."""
        return self.since_foe >= self.foe_every

    def read_names(self):
        """Something changed in a name box: read the names at the next picture."""
        self.since_foe = 10 ** 6

    def set_foe(self, name, cp=None):
        """The foe's name box was read.  Returns True when the foe is known now."""
        self.since_foe = 0
        foe = BE.foe_from_text(name) if name else None
        if foe is None:
            if not name:                       # (nothing was read: a banner over the box?  try again soon)
                self.since_foe = max(self.foe_every - FOE_RETRY, 0)
            if name and name != self._foe_miss:
                self._foe_miss = name
                self.log(f"fight: foe '{name}' not recognised" + (" - playing without knowing it"
                                                                   if self.foe is None else ""))
            return self.foe is not None
        if self.foe is not None and self.foe.species == foe.species and (
                not cp or not self.foe_cp or abs(cp - self.foe_cp) <= 1):
            self.foe_cp = cp or self.foe_cp
            return True                        # the same foe
        if self.foe is not None:               # a new one: it comes in with a full HP bar
            self.foe_hp = 1.0
            self._pending.pop("foe", None)
        foe.hp = int(round(self.foe_hp * foe.max_hp))
        self.foe, self.foe_cp = foe, cp
        self.log(f"fight: foe is {foe.label}" + (f" (CP {cp})" if cp else "")
                 + f" - moves {foe.fast.name} / " + ", ".join(m.name for m in foe.charged))
        return True

    def set_active(self, cp):
        """The CP in my name box: correct who is on the field when it is somebody else than expected.  A
        Pokémon that was nearly down has fainted and the next one came in by itself (the game does not ask
        when only one is left); otherwise we only had the wrong one in mind."""
        if not cp or abs(cp - self.me.cp) <= 1:
            return
        for m in self.team:
            if m.pos not in self.dead and abs(m.cp - cp) <= 1 and m is not self.me:
                fainted = self.my_hp < FAINTED_BELOW
                self.log(f"fight: {m.label} is on the field (not {self.me.label}"
                         + (", which fainted)" if fainted else ")"))
                if fainted:
                    self.faint()
                self._enter(m, keep_hp=not fainted)
                return

    def _came_in(self):
        """Our HP bar was nearly empty and is full now: our Pokémon fainted and the next one came in.  The game
        only asks which one when there are two or more left; with one it comes in by itself, and then the CP in
        the name box may not be read in time (the banner 'Go, Lapras!' covers it)."""
        others = [m for m in self.team if m.pos not in self.dead and m is not self.me]
        if len(others) != 1:
            return
        self.log(f"fight: our HP bar is full again - {others[0].label} is on the field (not {self.me.label}, "
                 f"which fainted)")
        self.faint()
        self._enter(others[0])

    def set_buttons(self, left, right):
        """The texts under the buttons were read: which move is on which button.  One side is enough when
        the Pokémon has two charged moves (the other button has the other move)."""
        self.label_tries += 1
        ids = [m.id for m in self.me.charged]
        slots = [self._find_mine(left), self._find_mine(right)]
        if slots[0] and slots[0] == slots[1]:
            slots = [None, None]
        if len(ids) == 2:
            if slots[0] and not slots[1]:
                slots[1] = next(i for i in ids if i != slots[0])
            elif slots[1] and not slots[0]:
                slots[0] = next(i for i in ids if i != slots[1])
        if (len(ids) == 2 and all(slots)) or (len(ids) == 1 and slots[0]):
            self.slots, self.labels_ok, self.need_labels = slots, True, False
            self.log("fight: buttons are " + " / ".join(BE.Move(s).name for s in slots if s))
        elif self.label_tries >= LABEL_TRIES:
            self.need_labels = False           # keep the party order
            self.log(f"fight: the moves under the buttons were not read ('{left}' / '{right}') - party order")

    def _find_mine(self, text):
        """Which of our charged moves is named in a text (a hint like 'Super effective' may stand next to the
        name, and a letter may be misread)."""
        words = BE._norm(text).split()
        best, found = 0.0, None
        for m in self.me.charged:
            target = BE._norm(m.name)
            n = len(target.split())
            for i in range(max(len(words) - n + 1, 0)):
                r = difflib.SequenceMatcher(None, " ".join(words[i:i + n]), target).ratio()
                if r > best:
                    best, found = r, m.id
        return found if best >= 0.8 else None

    def move_of(self, button):
        """The Move under a button (the party order when the labels are not known)."""
        mid = self.slots[button]
        if mid:
            return next((m for m in self.me.charged if m.id == mid), None)
        return self.me.charged[button] if button < len(self.me.charged) else None

    def _calibrate(self):
        """Without labels: when only one button is lit it is the cheaper move."""
        if self.labels_ok or sum(self.lit) != 1 or len(self.me.charged) != 2:
            return
        a, b = self.me.charged
        if a.energy == b.energy:
            return
        cheap, dear = (a, b) if a.energy < b.energy else (b, a)
        lit = 0 if self.lit[0] else 1
        if self.move_of(lit) is dear:
            self.slots = [None, None]
            self.slots[lit], self.slots[1 - lit] = cheap.id, dear.id
            self.log(f"fight: only the {'left' if lit == 0 else 'right'} button is lit, so it is the cheaper "
                     f"{cheap.name}")

    @property
    def energy(self):
        """At least this much energy: the dearest move whose button is lit."""
        costs = [m.energy for i, m in ((i, self.move_of(i)) for i in (0, 1)) if m and self.lit[i]]
        return max(costs) if costs else 0

    # ------------------------------------------------------------ what to do ---
    def throw(self):
        """(button, Move, why) of the charged attack to throw now, None to go on with the fast attack."""
        if not any(self.lit):
            return None
        lit = [(i, self.move_of(i)) for i in (0, 1) if self.lit[i] and self.move_of(i)]
        if not lit:
            return None
        if self.foe is None:                   # (foe unknown) the move with the most damage per energy
            i, m = max(lit, key=lambda t: t[1].power / float(max(t[1].energy, 1)))
            return self._thrown(i, m, f"{m.name} (foe not known)")
        self.me.energy = self.energy
        move, why = BE.pick_charged(self.me, self.foe, self.energy, self.foe_shields, self.foe.hp)
        if move is None:
            if not self._going_down():
                return None
            # the plan was to go on with the fast attack (or to save up for the dearer move), but we will not
            # live to see it: energy that is not used is lost, and even an attack that is shielded costs the
            # foe a shield - the next one of ours is glad of that
            i, m = max(lit, key=lambda t: (BE.damage(t[1], self.me, self.foe), -t[1].energy))
            return self._thrown(i, m, f"{m.name} before we go down (our HP is {self.my_hp:.0%})")
        for i, m in lit:
            if m.id == move.id:
                return self._thrown(i, move, why)
        # the picked move is not on a lit button (labels not read, the buttons may be the other way round)
        i, m = max(lit, key=lambda t: t[1].energy)
        return self._thrown(i, m, f"{m.name} (lit) instead of {move.name}")

    def _going_down(self):
        """Are we about to faint while the foe is not?  (Our HP is low, and the foe needs more than two more
        of our fast attacks.)"""
        if self.foe is None:
            return False
        low = max(GOING_DOWN_HP * self.me.max_hp, GOING_DOWN_FAST * BE.damage(self.foe.fast, self.foe, self.me))
        return self.me.hp <= low and self.foe.hp > 2 * BE.damage(self.me.fast, self.me, self.foe)

    def _thrown(self, button, move, why):
        self.throws += 1
        self.lit = (False, False)              # (spent: the next picture shows what is lit now)
        return button, move, why

    def shield(self):
        """The question 'Attack incoming! Use a Protect Shield?': (use it, why)."""
        if self.my_shields <= 0:
            return False, "no shields left"
        if self.foe is None:
            use = self.my_hp < UNKNOWN_FOE_SHIELD_BELOW
            return use, f"foe not known, our HP is {self.my_hp:.0%}"
        use, why = BE.should_shield(self.foe, self.me, self.my_shields, None, self.me.hp)
        if use:
            self.my_shields -= 1
        return use, why

    def faint(self):
        """The Pokémon on the field fainted."""
        self.dead.add(self.me.pos)
        self.me.hp = 0
        self.my_hp = 0.0

    def alive(self):
        return [m for m in self.team if m.pos not in self.dead and m.hp > 0]

    def switch(self, tiles):
        """'Switch in a new Pokémon?'  tiles: [(cp, x)] left to right as read on the pop-up.  The CP numbers are
        small: often only one of them is read, or none.  Every Pokémon that is left is a choice all the same
        (the tiles stand in party order), so the best one is taken, read or not.
        Returns (index into tiles or None, Mon or None, why).  self.tile: (the place of the chosen one among
        the tiles, the number of tiles) - where to tap when its CP was not read."""
        self.faint()
        left = self.alive()
        if not left:
            return None, None, "nobody left"
        shown = []                             # (tile index, Mon) for tiles whose CP is a Pokémon of ours
        for i, (cp, _x) in enumerate(tiles):
            m = next((m for m in left if abs(m.cp - cp) <= 1 and all(m is not s for _i, s in shown)), None)
            if m:
                shown.append((i, m))
        if not shown and len(tiles) == len(left):  # no CP read, but as many tiles as choices: in party order
            shown = list(zip(range(len(tiles)), left))
        if self.foe is not None:
            best, score = BE.best_switch(left, self.foe, self.my_shields, self.foe_shields)
            best = best or left[0]
            why = f"{best.label} fares best against {self.foe.label} (score {score:+.2f}"
        else:
            best, why = left[0], f"foe not known, taking {left[0].label} ("
        idx = next((i for i, m in shown if m is best), None)
        by_cp = idx is not None and abs(tiles[idx][0] - best.cp) <= 1
        why += ("" if why.endswith("(") else ", ") + ("by CP)" if by_cp else "by party order)")
        self.tile = (left.index(best), len(left))
        self._enter(best)
        return idx, best, why

    def _enter(self, mon, keep_hp=False):
        self.me = mon
        if not keep_hp:
            self.my_hp = mon.hp_frac
        self.slots, self.labels_ok = [None, None], False
        self.need_labels, self.label_tries = True, 0
        self.lit = (False, False)
        self._pending.pop("me", None)


def state(feat):
    """What a picture shows: 'result' (green NEXT BATTLE button), 'prompt' (the countdown ring of a question),
    'fight' (the HUD with the name boxes) or 'other' (VS screen, animation, banner, loading ...)."""
    if feat["white"] or feat["versus"]:
        return "other"
    if feat["result"] and not feat["hud"]:
        return "result"
    if feat["ring"]:
        return "prompt"
    if feat["hud"]:
        return "fight"
    return "other"
