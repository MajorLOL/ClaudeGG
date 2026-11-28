Part of the [Claude GG roadmap](../../ROADMAP.md).

## 2. Can the AutoStory match a speedrunner?

Not today, and not by a small change. The numbers:

| | Time |
|---|---|
| World record, Any% Glitchless (pokeguy, with Squirtle) | 1 h 59 min 34 s |
| AutoStory, second playthrough with Charmander, new game to the Hall of Fame (measured from the logs of 8 to 13 November, 34 runs; the Champion fell on 13 November at 01:49) | 56.9 hours of play |
| of which training levels in the grass (11 segments) | 45.8 hours |
| of which the route itself: walking, talking, the trainers on the way, the gyms, shopping, retries after a failure | 11.2 hours |
| of which the Elite Four and the Champion, each beaten at the first try | 0.9 hours |

So a whole story takes 57 hours, some 29 times the record. Four fifths of that is training:

| Training for | Hours | Levels asked for |
|---|---|---|
| Brock (Routes 1 and 2) | 3.3 | Charmander 18 |
| The rival in Cerulean | 1.3 | 25 |
| Misty | 4.3 | 34 |
| Erika (with Electrode and Vaporeon) | 8.3 | Charizard 36, Electrode 25, Vaporeon 30 |
| Koga | 4.4 | 50, 33, 35 |
| Sabrina (with Lapras) | 1.7 | 47, Lapras 32 |
| Blaine | 7.0 | 52, the team 42 |
| Giovanni | 5.6 | 66, the team 47 |
| The League | 9.8 (11.3 in the first playthrough) | 74, the team 58 |

A speedrunner does not train at all. The published routes ([Squirtle](https://www.speedrun.com/pkmnfrlg/guide/rps95), [Charmander](https://www.speedrun.com/pkmnfrlg/guides/wardh)) take their levels from the trainers on the way and a handful of Rare Candies, and win the hard fights with items bought on the 5th floor of the Celadon Department Store (the Charmander route: 22 X Special, 5 X Defend, 1 to 3 X Speed, 2 X Accuracy, 3 Guard Spec). The Charmander route meets Erika at level 34, Giovanni in Silph Co. at 43 and leaves Fuchsia at 48. They also reset the run when a fight goes wrong; the program cannot count on luck, so it levels until the fight is safe.

What would bring the time down, in the order of what it gains for the work it takes:

1. **X items instead of levels.** Buy the route's X items in Celadon, use them at the start of the gym leaders', Giovanni's, the rival's and the League's fights, and ask for the route's levels instead of today's. Save before each of those fights (the program does); after a loss, try again, and only after a second loss train three levels. Estimate: 5 to 10 hours of training left instead of 46.
2. **Only the lead trains.** Electrode, Vaporeon and Lapras are there for the League's match-ups. With X items the lead can carry the League; the team then only needs to exist for Surf, Strength and Fly.
3. **Running by default.** The option "Running (experimental)" halves the walking time on the maps that allow it. It needs a run from start to end without getting lost before it can be the default.
4. **The Switch versions' fanfare skip.** Opening and closing the help menu with L at the right moment skips a fanfare (2.68 seconds each, up to a minute and a half in a run, found by iamClemi in March 2026). Small, but free once the timing is known.
5. **A leaner route.** Leave out the trainers and item detours the speedrun routes leave out, and replace screen checks by fixed timing where a mistake cannot happen.

With 1 to 3 the story should come under 20 hours; with 4 and 5 perhaps under 12. A separate speed mode that walks by the clock, like a tool-assisted run, could come near 3 or 4 hours, but every step of it would have to be tested on the console, and it would stop at the first dropped button press. The record itself is the best of thousands of human attempts with the fastest starter; a program that has to finish every time will stay behind it.

All of these change how the story plays, so each needs test runs. The first step, the X items, is the one to start with.
