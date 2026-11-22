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
    fight.aim()                          -> (button, Move) or None: the charged attack to throw the moment it is
                                            ready (the fast attacks are then tapped on its button)
    fight.shield(foes, ready)            -> (True / False, why): the question "Use a Protect Shield?"
    fight.switch(tiles)                  -> (index of the tile, Mon, why): "Switch in a new Pokémon?"
    fight.doomed() / fight.hopeless(n)   -> (True / False, why): is the fight lost (see "giving up")?

    fight.foe_used(text)                 the banner 'Mismagius used Dark Pulse!' was read: that attack is one of
                                         the foe's two for sure
    fight.fought(seconds)                so much more of the plain fight has passed (for the foe's energy)
    fight.foe_threw()                    the foe has thrown a charged attack (the question is up)

What it cannot see is estimated: our energy from which buttons are lit (a lit button means the energy is at
least its cost), the foe's moves from PvPoke's recommended moveset for its species - until the banner of a
charged attack names one of them (foe_used; what was seen is kept for later battles in Fight.known) - and the
foe's energy from the time it has been fighting: it cannot have more than its fastest fast attack gives in
that time (foe_energy).  An incoming attack is taken to be the hardest one the foe can pay for.
"""
import difflib
import re

import battle_engine as BE

HP_JUMP = 0.30            # a bigger change between two pictures has to be seen twice before it is believed
FAINTED_BELOW = 0.25      # a Pokémon with less HP than this that is replaced has fainted
LABEL_TRIES = 8           # pictures to read the labels under the buttons from (they are hidden at times)
FOE_CHECK_EVERY = 3       # read the name boxes again every this many pictures with the HUD (a new foe comes in
                          # without a sign other than its name)
SHIELDS_BACK = 6          # pictures in a row that show more shields of ours than we counted: believe them
FOE_RETRY = 8             # a name box that gave nothing is read again after this many pictures at most
GOING_DOWN_HP = 0.20      # our HP below this part of the full bar: we are about to faint ...
GOING_DOWN_FAST = 4       # ... or it is no more than this many fast attacks of the foe
SWITCH_MISSED = 250       # pictures after the switch question: another one of ours on the field = our tap missed
HP_BACK_UP = 12          # pictures in a row (with the HUD) on which our bar reads higher: believe the bar again
FOE_BACK_SOON = 6.0       # s of fight: a foe that is back within this time was not away (its name was misread)


class Fight:
    def __init__(self, team, log=None, known=None):
        self.team = list(team)
        self.log = log or (lambda _m: None)
        # species -> {charged attack: in how many battles it was seen}: what opponents really used in earlier
        # battles (the fight loop keeps it in a file); it goes before the guess of the recommended moveset
        self.known = known if known is not None else {}
        self.learned = False                   # something was added to it in this battle
        self.clock = 0.0                       # seconds of plain fight so far (see fought())
        self._foe_e = [0.0, 0.0]               # the foe's energy: [what it had at most, at this time of the clock]
        self._foe_e_ok = True                  # False: that count was proven wrong for this foe - not used
        self._foe_left = {}                    # species -> (energy at most, ok, the clock) when it left the field
        self._change = None                    # the clock when the foe's name box changed (its name not read since)
        self._read_at = 0.0                    # the clock when the foe's name was last read
        self._threw = None                     # the foe's last charged attack: (energy it had at most, cost taken off)
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
        self._balls = [3, 0]                   # the red Poké Balls of our name box: [how many, pictures in a row]
        self._seen = 0                         # pictures seen; at which of them ...
        self._balls_at = 0                     # ... the number of red Poké Balls last changed
        self._named_at = -1                    # ... the name box last showed that another one of ours had come in
        self._my_reads = 0                     # readings of our HP bar in the plain fight since `me` came in ...
        self._my_read = 1.0                    # ... and the last of them
        self._rise = [None, 0]                 # our bar reads higher than believed: [the reading, pictures in a row]
        self._switch_seen = None               # the picture count when the switch question was answered
        self._came = (self.me, self.me.hp)     # who came in last, and the HP it had before that
        self._aim = (None, None)               # (what aim() was worked out for, its answer)
        self.foe_seen = {}                     # species -> the charged attacks it was seen to use in this battle

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
        self._seen += 1
        mine, foe = feat["hp"]
        old = self.my_hp
        self.my_hp = self._believe("me", self.my_hp, mine)
        if old < self.my_hp <= old + HP_JUMP:  # (a Pokémon never heals: a small rise is a misread ...
            self.my_hp = old
            r = self._rise
            if feat["hud"] and r[0] is not None and abs(mine - r[0]) <= 0.10:
                r[1] += 1
            elif feat["hud"]:
                r[0], r[1] = mine, 1
            if r[1] >= HP_BACK_UP:             # ... unless the bar says so on picture after picture: then what
                self.my_hp = mine              # was believed before was the misread (31% on the bar, 6% kept)
                r[0], r[1] = None, 0
        elif old < FAINTED_BELOW and self.my_hp > 0.6:
            self._came_in()                    # (a full bar after a nearly empty one: the next one of ours)
        if mine is not None and mine <= old + 0.03:
            self._rise = [None, 0]             # (the bar does not read higher on this picture: no misread below)
        if mine is not None and feat["hud"] and abs(mine - self.my_hp) <= 0.06:
            self._my_reads += 1                # (its HP is known from its own bar, read in the plain fight - not
            self._my_read = self.my_hp         # from what was kept, not from a picture with a banner over the bar)
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
            balls = (feat.get("balls") or {}).get("me")
            if balls and sum(balls) == 3:          # (all three are seen: none under a banner)
                self._see_balls(balls[0])

    def _see_balls(self, red):
        """The Poké Balls of our name box: `red` of our three can still fight.  A Pokémon that faints from a
        charged attack is gone without its HP bar ever being seen empty; its ball turning grey is the sign (it
        does so a second or two before the name in the box changes).  Only the one on the field can faint, and
        when that leaves one other Pokémon, that one comes in by itself (the game only asks when there are two).
        Unless the name box has shown a new name since the ball turned grey: then the one on the field is the
        one that came in, and it is the other that has fainted."""
        if red != self._balls[0]:
            self._balls, self._balls_at = [red, 1], self._seen
        else:
            self._balls[1] += 1
        if self._balls[1] != 2 or 3 - red != len(self.dead) + 1:
            return
        others = [m for m in self.team if m.pos not in self.dead and m is not self.me]
        if len(others) != 1:
            return
        if self._named_at >= self._balls_at:
            self.log(f"fight: another Poké Ball of ours is grey - {others[0].label} has fainted too")
            self.dead.add(others[0].pos)
            others[0].hp = 0
        else:
            self.log(f"fight: another Poké Ball of ours is grey - {self.me.label} fainted, {others[0].label} is "
                     f"on the field")
            self.faint()
            self._enter(others[0])

    def _fainted_more(self):
        """Do the Poké Balls show more fainted Pokémon of ours than were counted?"""
        return 3 - self._balls[0] > len(self.dead)

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

    def read_names(self, side=None):
        """Something changed in a name box (side: "me" / "foe"): read the names at the next picture.  Until the
        foe's name has been read again nobody knows who is on the field: its energy is not known either."""
        self.since_foe = 10 ** 6
        if side != "me" and self._change is None:
            self._change = self.clock

    # ------------------------------------------------------------ the foe's energy ---
    def fought(self, seconds):
        """`seconds` more of the plain fight have passed: both sides were tapping fast attacks.  (The fight loop
        counts them; a charged attack of either side stops that clock, as it stops the game.)"""
        self.clock += max(float(seconds), 0.0)

    def _energy(self, at=None):
        """What the foe on the field has at most at time `at` of the clock (now), without any margin."""
        rate, _gain = BE.fast_rate(self.foe.species)
        base, mark = self._foe_e
        return min(100.0, base + rate * max((self.clock if at is None else at) - mark, 0.0))

    def foe_energy(self):
        """The energy the foe has at most right now, None when that is not known.  It came in with nothing (or
        with what it had when it left), every charged attack took its cost off, and in between it cannot have
        gained more than its fastest fast attack gives in the time that was fought - plus one fast attack, for
        the one that is under way.  An upper limit: an attack that costs more is not the one that is coming.
        Not known: the foe itself is not, its name box changed and was not read since, or the count was proven
        wrong for it (it threw what it could not have paid for)."""
        if self.foe is None or not self._foe_e_ok or self._change is not None:
            return None
        return min(100.0, self._energy() + BE.fast_rate(self.foe.species)[1])

    def foe_threw(self, sure=True):
        """The foe has thrown a charged attack (the question about it is up).  Its energy went down by the cost
        of that attack: by the least any attack of its species costs, until the banner names it (foe_used).
        sure=False: the question was not read, the picture was only taken for one - nothing comes off the
        energy until the banner says that an attack was thrown (what is kept is the MOST the foe can have)."""
        if self.foe is None:
            self._threw = None
            return
        had = self.foe_energy()
        cost = BE.cheapest_charged(self.foe.species) if sure else 0
        self._threw = (had, cost)
        if had is not None:                    # (counted on from here; the margin is only added when it is asked)
            self._foe_e = [max(self._energy() - cost, 0.0), self.clock]

    def threw_with(self):
        """The energy the foe had at most when it threw the attack that is on its way (None: not known)."""
        return self._threw[0] if self._threw else self.foe_energy()

    def set_foe(self, name, cp=None):
        """The foe's name box was read.  Returns True when the foe is known now."""
        self.since_foe = 0
        foe = BE.foe_from_text(name) if name else None
        if foe is None:
            # nothing was read, or a name that is not known ('Awe' for Whiscash under the banner 'Go, Whiscash!'):
            # a banner over the box?  Try again soon - until then the one before is taken to be on the field
            self.since_foe = max(self.foe_every - FOE_RETRY, 0)
            if name and name != self._foe_miss:
                self._foe_miss = name
                self.log(f"fight: foe '{name}' not recognised" + (" - playing without knowing it"
                                                                   if self.foe is None else ""))
            return self.foe is not None
        if self.foe is not None and self.foe.species == foe.species and (
                not cp or not self.foe_cp or abs(cp - self.foe_cp) <= 1):
            self.foe_cp = cp or self.foe_cp
            self._change, self._read_at = None, self.clock     # (it is still the one whose energy is counted)
            return True                        # the same foe
        # When the new one came in, at the earliest: when its name box was seen to change - or, when that was
        # not noticed, when the one before it was last read there (its energy must not be counted too low).
        came = self._change if self._change is not None else self._read_at
        if self.foe is not None:               # a new one: it comes in with a full HP bar
            self.foe_hp = 1.0
            self._pending.pop("foe", None)
            self._foe_left[self.foe.species] = (self._energy(came), self._foe_e_ok, came)   # (it keeps its energy)
        elif not self._foe_left:
            came = 0.0                         # (the first one of the battle: there from the start)
        energy, ok, left = self._foe_left.get(foe.species, (0.0, True, None))
        if left is not None and came - left < FOE_BACK_SOON:
            came = left                        # (back that soon: a name that was misread - it never left)
        self._foe_e, self._foe_e_ok, self._change, self._threw = [energy, came], ok, None, None
        self._read_at = self.clock
        foe.hp = int(round(self.foe_hp * foe.max_hp))
        known = self._apply_seen(foe)          # (what it used before - in this battle or in earlier ones)
        self.foe, self.foe_cp = foe, cp
        self.log(f"fight: foe is {foe.label}" + (f" (CP {cp})" if cp else "")
                 + f" - moves {foe.fast.name} / " + ", ".join(m.name for m in foe.charged)
                 + (" (as seen before)" if known else ""))
        return True

    def _apply_seen(self, foe):
        """Put the charged attacks this species was seen to use at the front of the attacks of `foe`: those of
        this battle first, then those of earlier battles (the ones seen most often first).  A Pokémon has two
        at most: a guessed one makes room.  True when that changed something."""
        seen = list(self.foe_seen.get(foe.species, []))
        pool = BE.load()["mons"][foe.species][6]
        before = self.known.get(foe.species) or {}
        seen += [m for m, _n in sorted(before.items(), key=lambda t: -t[1]) if m in pool and m not in seen]
        if not seen:
            return False
        ids = (seen + [m.id for m in foe.charged if m.id not in seen])[:min(2, max(len(foe.charged), len(seen)))]
        if ids == [m.id for m in foe.charged]:
            return False
        foe.charged = [BE.Move(i) for i in ids]
        return True

    def foe_used(self, text):
        """The banner at the top was read: 'Mismagius used Dark Pulse!'.  When it names the foe on the field
        and one of the charged attacks its species can have, that attack is one of its two for sure: it takes
        the place of one that was only guessed (the guess is PvPoke's recommended moveset; players use others
        too).  Our own banner ('Noctowl used Shadow Ball!') and anything misread change nothing.
        Returns the Move, or None."""
        foe = self.foe
        if foe is None or not text:
            return None
        words = text.replace("!", "! ").split()
        at = next((i for i, w in enumerate(words)
                   if 3 <= len(w) <= 5 and difflib.SequenceMatcher(None, w.lower(), "used").ratio() >= 0.75), None)
        if at is None or at == 0 or at + 1 >= len(words):
            return None

        def plain(name):
            return BE._norm(re.sub(r"\(.*?\)", " ", name)).replace(" ", "")

        def like(name):                        # how well the words before 'used' fit this name
            return max(difflib.SequenceMatcher(None, plain(" ".join(words[max(at - n, 0):at])), plain(name)).ratio()
                       for n in (1, 2, 3))
        theirs = like(foe.name)
        if theirs < 0.75 or theirs <= max(like(m.name) for m in self.team):
            return None                        # (ours, or not a name at all)
        rest = words[at + 1:]
        end = next((i for i, w in enumerate(rest) if "!" in w), len(rest) - 1)
        rest = rest[:end + 1][:4]
        pool = BE.load()["mons"][foe.species][6]
        best, found = 0.0, None
        for mid in pool:
            target = plain(BE.load()["moves"][mid][0])
            for n in range(1, len(rest) + 1):
                r = difflib.SequenceMatcher(None, plain(" ".join(rest[:n])), target).ratio()
                if r > best:
                    best, found = r, mid
        if found is None or best < 0.82:
            return None
        move = BE.Move(found)
        if self._threw is not None:            # the attack that was thrown: its real cost comes off the energy
            had, cost = self._threw
            self._threw = None
            if had is not None and move.energy > had + 5:
                if self._foe_e_ok:             # (it threw what it could not have had the energy for)
                    self.log(f"fight: {foe.label} threw {move.name} ({move.energy} energy) when it should have had "
                             f"{int(had)} at most - its energy is not counted any more")
                self._foe_e_ok = False
            elif had is not None and move.energy > cost:
                self._foe_e[0] = max(self._foe_e[0] - (move.energy - cost), 0.0)
        seen = self.foe_seen.setdefault(foe.species, [])
        if found in seen:
            return move
        seen.append(found)
        del seen[:-2]                          # (two at most: the newest count)
        count = self.known.setdefault(foe.species, {})
        count[found] = count.get(found, 0) + 1                 # (once a battle: for the battles to come)
        self.learned = True
        guess = [m.name for m in foe.charged]
        self._apply_seen(foe)
        if sorted(guess) != sorted(m.name for m in foe.charged):       # (not when only their order changed)
            self.log(f"fight: {foe.label} used {move.name} - its charged attacks are taken to be "
                     + ", ".join(m.name for m in foe.charged) + f" now (the guess was {', '.join(guess)})")
        return move

    def set_active(self, cp):
        """The CP in my name box: correct who is on the field when it is somebody else than expected.  A
        Pokémon that was nearly down has fainted and the next one came in by itself (the game does not ask
        when only one is left); otherwise we only had the wrong one in mind."""
        if not cp:
            return
        if abs(cp - self.me.cp) <= 1:
            self._switch_seen = None           # (the one that was chosen is on the field: the tap counted)
            return
        for m in self.team:
            if m.pos not in self.dead and abs(m.cp - cp) <= 1 and m is not self.me:
                if self._switch_seen is not None and self._seen - self._switch_seen <= SWITCH_MISSED:
                    # right after the switch question: our choice did not come in, the game chose the other one
                    # (the tap on its tile did not count) - nobody fainted
                    self.log(f"fight: {m.label} is on the field, not {self.me.label} - the tap on the tile of "
                             f"{self.me.label} did not count, the game chose")
                    self._switch_seen = None
                    self._enter(m)
                    self._named_at = self._seen
                    return
                fainted = self.my_hp < FAINTED_BELOW or self._fainted_more()
                self.log(f"fight: {m.label} is on the field (not {self.me.label}"
                         + (", which fainted)" if fainted else ")"))
                if fainted:
                    self.faint()
                elif self._came[0] is self.me:     # (it never was on the field: the HP that was read meanwhile
                    self.me.hp = self._came[1]     # was not its own - it still has what it had before)
                reads = self._my_reads
                self._enter(m, keep_hp=not fainted)
                self._named_at = self._seen        # (the name box says so, now)
                if not fainted:
                    self._my_reads = reads         # (the bar that was read is the bar of this one)
                return
        for m in self.team:
            if (m.pos in self.dead and abs(m.cp - cp) <= 1 and self._balls[1] >= 2
                    and 3 - self._balls[0] == len(self.dead) and self._seen - self._balls_at >= self.foe_every):
                # the name box shows one that was taken for fainted, the Poké Balls agree with the count and have
                # done so for a while (right after a faint the box still shows the old name): two were mixed up -
                # the game had chosen the other one when the switch question ran out
                self.log(f"fight: {m.label} is on the field - it was {self.me.label} that fainted")
                self.dead.discard(m.pos)
                m.hp = m.max_hp
                self.faint()
                self._enter(m)
                self._named_at = self._seen
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

    def buttons_swapped(self, mon):
        """The icons of a little game showed that our tap on a button threw the other attack: the names under
        the buttons were read the wrong way round.  Swap them (for the Pokémon that threw it, if it is still on
        the field)."""
        if mon is not self.me or len(self.me.charged) != 2:
            return
        a, b = self.move_of(0), self.move_of(1)
        if a is None or b is None:
            return
        self.slots = [b.id, a.id]
        self.labels_ok = True
        self.need_labels = False
        self.log(f"fight: the buttons are the other way round - {b.name} on the left, {a.name} on the right")

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
        # the picked move is not on a lit button.  When it costs no more than one that is lit, it is ready too
        # (the energy is the same for both): its button was not seen lit on this picture.  Throw it there - the
        # fast attacks are tapped on that button anyway, a tap on the other one would race them.
        if self.labels_ok:
            for i in (0, 1):
                m = self.move_of(i)
                if m is not None and m.id == move.id and move.energy <= max(x.energy for _j, x in lit):
                    return self._thrown(i, move, why + f" (ready: it costs no more than {lit[0][1].name})"
                                        if len(lit) == 1 else why)
        # the picked move is not on a lit button (labels not read, the buttons may be the other way round)
        i, m = max(lit, key=lambda t: t[1].energy)
        return self._thrown(i, m, f"{m.name} (lit) instead of {move.name}")

    def aim(self):
        """(button, Move): the charged attack that is thrown the moment its button lights up, None when there is
        no such attack right now (the plan is to save up, or to throw the cheap one only when the dear one is
        ready too).  The fight loop then taps the fast attacks ON that button: a tap on a button that is not
        ready is a fast attack like any other, and the first tap after it is ready throws the attack - no
        picture has to be waited for, no turn is lost.  Only when it is known which attack is on which button."""
        me = self.me
        if len(me.charged) != 2 or not (self.labels_ok or all(self.slots)):
            return None
        key = (me.pos, self.foe.species if self.foe else "", int(self.my_hp * 50), int(self.foe_hp * 50),
               self.foe_shields, tuple(self.slots))
        if key == self._aim[0]:
            return self._aim[1]
        moves = [(self.move_of(i), i) for i in (0, 1)]
        res = None
        if all(m for m, _i in moves):
            first = min(m.energy for m, _i in moves)       # (what lights up first)
            early = [(m, i) for m, i in moves if m.energy == first]
            if self.foe is None:                           # (foe unknown: throw() takes what is lit, see there)
                m, i = max(early, key=lambda t: t[0].power / float(max(t[0].energy, 1)))
                res = (i, m)
            else:
                energy = me.energy
                for cost in sorted(set(m.energy for m, _i in moves)):
                    me.energy = cost
                    pick, _why = BE.pick_charged(me, self.foe, cost, self.foe_shields, self.foe.hp)
                    if pick is None:
                        continue                           # (it saves up - for the dearer one, perhaps)
                    if pick.energy == cost:                # (thrown the moment it is ready)
                        res = next(((i, m) for m, i in moves if m.id == pick.id), None)
                    break                                  # (a cheaper one, thrown only now: not to be thrown early)
                me.energy = energy
                if res is None and self._going_down():     # (anything that lights up, see throw())
                    m, i = max(early, key=lambda t: BE.damage(t[0], me, self.foe))
                    res = (i, m)
        self._aim = (key, res)
        return res

    # ------------------------------------------------------------ giving up ---
    def doomed(self):
        """An attack is coming and we have no shield.  (True, why) when that ends the fight: this is our last
        Pokémon, its HP was read from its own bar and the foe's hardest charged attack - as far as its attacks
        are known, and of those it had the energy for - knocks it out."""
        lost, why = self._doomed()
        return (True, why) if lost else (False, "")

    def fights_on(self):
        """Why doomed() says that the fight is not over (for the log; '' when it is over)."""
        lost, why = self._doomed()
        return "" if lost else why

    def _doomed(self):
        if self.foe is None:
            return False, "the foe is not known"
        if self.my_shields > 0:
            return False, f"we have {self.my_shields} shield(s) left by our count"
        if len(self.alive()) != 1:
            return False, f"{len(self.alive())} of ours can still fight by our count"
        if not self._hp_sure():
            return False, (f"the HP of {self.me.label} is not sure (read from its bar {self._my_reads} time(s), "
                           f"last {self._my_read:.0%}, taken to be {self.my_hp:.0%})")
        # Which attack comes is not known: only when EVERY attack the foe can pay for knocks ours out is the
        # fight over (22 November: given up on a Frenzy Plant, while the Serperior had just shown Leaf Tornado,
        # which costs the same and would have been survived).  In doubt the fight goes on: giving up saves ten
        # seconds, a fight that goes on can still be won.
        moves = BE.can_throw(self.foe, self.threw_with())
        hits = sorted((BE.damage(m, self.foe, self.me), m.name) for m in moves)
        dmg, name = hits[0]
        if dmg < self.me.hp:
            return False, (f"{self.foe.label}'s {name} does {dmg}, {self.me.label} has {self.me.hp} HP"
                           + (" (its other attack costs more energy than it can have)"
                              if len(moves) < len(self.foe.charged) else ""))
        dmg, name = hits[-1]
        return True, (f"{self.me.label} is our last Pokémon, it has {self.me.hp} HP and no shield, and "
                      f"{self.foe.label}'s {name} does {dmg}"
                      + (f" (and {hits[0][1]} {hits[0][0]})" if len(hits) > 1 else ""))

    def _hp_sure(self):
        """Is our HP known well enough to give a fight up on it?  It has to be read from the bar of the Pokémon
        that is on the field, in the plain fight (twice at least since it came in), and what is believed now
        must be what was read there: the banner of a question lies over our HP bar, a Pokémon that has just
        come in has the HP that was kept for it."""
        return self._my_reads >= 2 and abs(self._my_read - self.my_hp) <= 0.10

    def hopeless(self, foes):
        """The plain fight, our last Pokémon against `foes` of theirs that can still fight.  (True, why) when
        there are two or more of them and ours loses the duel it is in, played out with the rules of the engine
        and with everything that is not known taken in our favour: our energy just short of the next charged
        attack, the foe's at zero."""
        if foes < 2 or self.foe is None or len(self.alive()) != 1 or not self._hp_sure():
            return False, ""
        me, foe = self.me.copy(), self.foe.copy()
        me.energy = min([m.energy - 1 for m in me.charged if m.energy > self.energy] or [100])
        foe.energy = 0
        mine, theirs = BE.simulate(me, foe, self.my_shields, self.foe_shields)
        if mine > 0:
            return False, ""
        return True, (f"{self.me.label} ({self.my_hp:.0%} HP) is our last Pokémon and loses to {self.foe.label} "
                      f"({self.foe_hp:.0%} HP, it would keep {theirs:.0%}), and {foes - 1} more "
                      f"{'is' if foes == 2 else 'are'} waiting")

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

    def shield(self, foes=None, ready=False):
        """The question 'Attack incoming! Use a Protect Shield?': (use it, why).  foes: how many Pokémon the foe
        can still fight with (the red Poké Balls of its name box; None: not known).  ready: a charged attack of
        ours was ready when the question came up.  See battle_engine.use_shield for the rule; the attack is
        taken to be the hardest one the foe can pay for (foe_energy).  Call foe_threw() after it."""
        if self.my_shields <= 0:
            return False, "no shields left"
        mine = max(len([m for m in self.team if m.pos not in self.dead]), 1)
        use, why = BE.use_shield(self.foe, self.me, self.my_shields, self.me.hp, mine, foes, ready, None,
                                 self.foe_energy())
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
        self._switch_seen = self._seen
        self._enter(best)
        return idx, best, why

    def _enter(self, mon, keep_hp=False):
        self._came = (mon, mon.hp)
        self.me = mon
        self._my_reads = 0
        self._aim = (None, None)
        if not keep_hp:
            self.my_hp = mon.hp_frac
        self.slots, self.labels_ok = [None, None], False
        self.need_labels, self.label_tries = True, 0
        self.lit = (False, False)
        self._pending.pop("me", None)


def state(feat):
    """What a picture shows: 'result' (the green NEXT BATTLE button, or the round check mark that is the only
    button after a battle that was won), 'prompt' (the countdown ring of a question), 'fight' (the HUD with the
    name boxes) or 'other' (VS screen, animation, banner, loading ...)."""
    if feat["white"] or feat["versus"]:
        return "other"
    if (feat["result"] or feat.get("done")) and not feat["hud"]:
        return "result"
    if feat["ring"]:
        return "prompt"
    if feat["hud"]:
        return "fight"
    return "other"
