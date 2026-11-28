Part of the [Claude GG roadmap](../../ROADMAP.md).

## 7. Can a program of our own beat the world records?

The records:

| | Time | How |
|---|---|---|
| Best run by a person, Any% Glitchless | 1 h 59 min 34 s | pokeguy, on a Game Boy Player with Game Boy Interface. The leaderboard lists GBA, Game Boy Player, GBI and DS; the Switch versions are not on it. |
| Tool-assisted run | 1 h 44 min 17 s | mkdasher, 2013, on the emulator VBA-rr: 373,735 frames of input, with heavy manipulation of the game's random numbers (Squirtle, later a Clefable with Metronome). |

**An official record: no.** speedrun.com's rules say that "the game itself must not be altered or controlled with outside tools" and that turbo controllers "or such with non-native functions" are not allowed. A program pressing the buttons is exactly that. TASVideos publishes input files made on emulators; a run on a console is not one of those.

**The tool-assisted time: no.** That run is perfect to the frame for an hour and three quarters, made with save states and a view into the game's memory. A program that looks at a capture card cannot get there.

**Faster than the best person, unofficially: possible in principle, far away in practice.** What speaks for it:

- A long tool-assisted run has been played back on real hardware: a Pokémon Crystal run of more than 600,000 frames on a GameCube with Game Boy Interface (it lost its place once, after 32 minutes, through the drift of the game's clock, and that was fixed).
- On a console that asks a USB controller for its buttons, as the Switch does, timed playback worked in short stretches when the playback counted the console's video frames (a Wii U and an RP2040 board); over the air it was off by up to two frames.
- Pokémon Automation's RNG programs hit one chosen moment on the retail Switch versions after calibrating: the seed is set by when a button is pressed on the title screen, and its guide's example is 8 advances late and one seed off at the first try, on target at the next.
- A program does not get tired. Where people play thousands of attempts for one lucky run, it can play twelve two-hour attempts a day and keep the best, and it can do what the published route says it leaves out ("not optimized for RNG manipulation").

What stands in the way:

- The gap between a perfect run and the best person is only 15 minutes in two hours. The AutoStory is not near that kind of play: it looks at the screen after nearly everything it does (a walk of four tiles in the grass takes 3.3 seconds, of which one second is walking), it trains for 46 hours, and it takes Charmander.
- It would be another program, not a faster AutoStory: the speedrun route (Squirtle, no training, X items, Rare Candies, Repels, the bicycle), played by the clock in stretches of timed presses, looking at the video only where the game gives a clear sign to find its place again.
- The Switch versions run the game in Nintendo's own emulator: its timing has to be measured, nothing of the Game Boy Advance runs can be assumed.
- Every stretch has to be tested on the console, and a run stops at the first press that falls a frame late.

The order to go about it, each step useful by itself:

1. **Measure** (build 4): the Input Timing Test tells how much the delay between a press and its effect varies on this controller board, console and capture card, and whether a press can be aimed at a frame. Without that, nothing by the clock can be planned.
2. **Take the waits out of the AutoStory** where the game gives a sign: "Faster battles" (build 4), "Shorter looks in the grass" (build 5, see below), running.
3. **X items instead of levels** (section 2): from 57 hours to under 20.
4. **A speedrun mode** for one stretch first, for instance from the bedroom to the first rival battle: timed presses, the video as the check. Compare with the same stretch in a record run's video.
5. **The whole route** stretch by stretch, then the random numbers (the starter's stats from the title screen, as Pokémon Automation's Starter RNG does), then many attempts.

A fair guess: steps 1 to 3 are weeks, and bring a story that plays in less than a day. Steps 4 and 5 are months of test runs, with a first whole run somewhere around 3 to 4 hours. Coming under 1 h 59 min 34 s would take much more than that again, and may not be reachable through a capture card at all; the Input Timing Test is the first thing that can tell.

One thing would be new either way: no program-played run of FireRed or LeafGreen on a console turned up in this search. The first one that finishes at speedrun pace has no time to beat.

### What the logs of the test runs already tell (13 November)

The Input Timing Test has not run yet. Three things can be read from the logs of the AutoStory itself.

**Where the time of a run goes.** The run of 12 to 13 November (9.4 hours: six hours of training for the League, the Elite Four and the Champion, then 26 tries at Zapdos) counted its own time by activity:

| Activity | Minutes | Share |
|---|---|---|
| Battles (415), and reading text, moves and species names | 309 | 55% |
| Walking the route | 92 | 16% |
| Walks along the grass while training (1,614) | 85 | 15% |
| Menus, healing, saving, resets, flying, single steps | 42 | 7% |
| The rest | 36 | 6% |

**The look after a walk in the grass.** After every walk along the grass the program watched 1.5 seconds for a battle to start. Of the 1,614 walks, 1,266 ended without one and waited the whole time: 32 minutes of the run. Of the 348 battles, the video saw 343 start during the walk itself; that look found the other 5, 1.3 seconds after the walk. The game decides on a wild battle in the frame a step ends, and what follows changes the whole picture every frame until the screen is black (two fades to gray and back, then the transition). So a screen that stays the same for 0.3 seconds has no battle starting. **Build 5, experimental:** the option "Shorter looks in the grass" of the AutoStory and the Level Trainer ends the look then. About one second less for each walk without a battle: 23 minutes of that run. With "Faster battles" (about 5 seconds for each battle that is not a catch, some 30 minutes of that run) the two would have taken a little under an hour off the 9.4, if they work as meant; neither has run on a console.

**Walking by the clock.** A walk is one held press, timed to the tile (16 frames a tile), and the video counts the tiles after it. In the logs of 8 to 13 November the video could count 15,009 of them:

| | Walks | Exactly the tiles asked for | Short | A tile too far |
|---|---|---|---|---|
| Along the grass (up to 4 tiles) | 7,330 | 7,329 | 1 | 0 |
| On the route (1 to 41 tiles) | 7,679 | 7,464 | 215 | 0 |

The short ones are not the clock. 100 of the 215 are walks over rock stairs: the steps in front of the Indigo Plateau and the two ends of Nugget Bridge. On those tiles the game itself walks slower, 23 frames a tile instead of 16 (`PlayerIsMovingOnRockStairs` in its source). A walk over four of them came out two tiles short 83 times of 85 and one tile short the other two times; a walk over two of them one tile short, 14 times of 14. One stair tile fits in the spare time of a press (19 walks of 20). The program sees the missing tiles on the video and walks them. A clock that counts the stairs would not have to, and the script's generator knows where they are (it does not let the player run there). Another 22 are one walk in the Power Plant, two tiles short all 22 times: the Max Repel wears off on it, and the game shows "REPEL's effect wore off…" and takes the text away again by itself because a direction is held. And 79 are walks that did not start at all, 58 of them single steps and most of those at the same four places; those have not been looked into. Along the grass a timed walk came out right 7,329 times of 7,330, and no walk went a tile too far.

Between two walks the program takes 0.8 seconds (the median of 6,973 walks that were followed straight by another): it lets the last step end, counts the tiles on the video and waits for a still picture. The game needs up to a quarter of a second of that. In these logs the pauses add up to 87 minutes, next to 163 minutes of held presses.

So for step 4, walking by the clock is not what stands in the way on this controller board and console: the clock has to count the rock stairs and the steps of a Repel, and it can chain the presses where the program now stops to look. What a speed mode has to solve is what is not walking: more than half of a run is battles, and the texts, menus and fades between them have no fixed length yet. That is what the Input Timing Test and "Faster battles" are for.
