# Pokémon GO Automation

Automates Pokémon GO on an Android phone from a headless Raspberry Pi. The Pi controls the phone over ADB (USB), recognises what is on the screen with small neural networks, and plays: it spins PokéStops, catches wild Pokémon, opens and sends gifts, and runs a daily routine across two Pokémon GO installs. A password-protected web interface lets you watch the phone live and change options from any device on your network.

> **Read this first.** Automating Pokémon GO is against Niantic's Terms of Service. Accounts that use it can be warned, suspended or banned. Use it at your own risk, preferably on an account you can afford to lose. This project is not affiliated with, endorsed by or connected to Niantic, Nintendo, The Pokémon Company or Google. See the [Disclaimer](../../wiki/Disclaimer) wiki page.

## What it does

- **Spins PokéStops** next to the player and clears the pop-ups that follow (rewards, full bag, news, exit dialogs, ...).
- **Catches wild Pokémon.** Finds them on the map, taps them, gives a berry (Pinap first, then Razz, then Nanab; never Silver Pinap or Golden Razz), and throws. The throw is timed on the shrinking target ring: *Realistic* (a randomised, human-like mix: mostly Great, not every throw perfect), or always Nice / Great / Excellent, with an optional curveball, and an optional (experimental) *fast catch* that leaves the encounter right after a clear hit. It runs away after 8 throws.
- **Looks around** by turning the camera in randomised swipes to find Pokémon behind or next to the player.
- **Gifts:** opens gifts from friends and sends gifts.
- **Daily run:** at a time you choose, plays each installed Pokémon GO app (Play Store and Galaxy Store versions) one after another until the Pokémon storage and the bag are full or a time limit is reached, then closes the game.
- **Recovers by itself:** unlocks the phone, wakes a dimmed screen, restarts the game when it is stuck.
- **Web interface** on port 8080: live video of the phone, log with daily counters, Start / Stop / Restart / Close game, on/off options, throw target, daily start time and time limit, and a manual mode (tap on the picture, Back / Home / Apps, send text).

## How it works

```
 Raspberry Pi 4 ──USB──► Android phone (Pokémon GO)
   │  adb exec-out screencap   → screenshot
   │  LiteRT models (RegiBot)  → which screen? where are the Pokémon / stops / buttons / target ring?
   │  adb shell input ...      → taps, swipes, throws
   └─ web.py (port 8080)       → live video, log, options
```

The screen classifier, the object detectors and the throw predictor come from the open-source [RegiBot](https://github.com/Juancavr6/RegiBot) project (MIT). They are run here with [LiteRT](https://ai.google.dev/edge/litert) (`ai-edge-litert`), because MediaPipe does not run on the Raspberry Pi 4. Everything else (screen handling, navigation, timing, gifts, the daily run, the web interface) is in this repository.

## Quick start

You need a Raspberry Pi 4 with a **64-bit** Raspberry Pi OS, an Android phone connected by USB with USB debugging on, and the packages listed on the [Requirements](../../wiki/Requirements) wiki page.

```bash
git clone https://github.com/MajorLOL/pokemon-go-automation.git
cd pokemon-go-automation
bash install.sh            # Python environment, models, program files in ~
~/gbvenv/bin/python device_check.py       # which phone / screen was found? (writes a report to ~/debug)
~/gbvenv/bin/python device_check.py --layout   # with the game on the map: is it drawn the way the bot expects?
~/gbvenv/bin/python gamebot.py test      # analyse one screenshot of the phone
```

Then install the services, the sudoers rule and the web password as described in [Installation](../../wiki/Installation), and set up the phone as described in [Phone setup](../../wiki/Phone-setup).

## Repository layout

| Path | What it is |
|---|---|
| `gamebot.py` | The bot: image recognition, catching, spinning, gifts, daily run |
| `spin_stop.py` | Base functions: ADB, screenshots, unlocking, recovery, PokéStop spinning |
| `web.py` | Web interface (live video, log, options) |
| `device_check.py` | Reports which phone and screen the bot found; `--layout` checks (without changing anything) whether the game is drawn the way the bot expects; `--speed` measures screenshot speed; `--reset-display` undoes a display size change; collects what is needed to add a new phone |
| `systemd/` | Service files: `spin-stop.service` (the bot) and `gamebot-web.service` (the web interface) |
| `models/` | `anchors.npz` and `predictor_weights.npz` (derived from RegiBot, see `NOTICE.md`). The `.tflite` models are downloaded by `install.sh` |
| `install.sh` | Installs the Python environment, the models and the program files |

## Known limitations

- **Tested on one phone only.** The positions in the code are written for the **Samsung Galaxy Z Fold3 inner display (1768 × 2208)**. On the first map picture of every run the bot looks for the Poké Ball menu button and checks that the game is drawn the way it expects. On another resolution it simply converts everything. On a screen with another shape (tall phones, tablets) it lets Android draw the game on a 4:5 canvas (`adb shell wm size`, black bars), checks the result by tapping the menu, and puts the size back when it stops; if that does not work it does not tap. This automatic adaptation was only tested with simulated phones, not on a real one. See the *Phone setup* wiki page.
- **Pokémon GO must be set to English.** Some screens are recognised by reading their text with OCR.
- **The lock screen must be "swipe" or "none"**, not a PIN or pattern.
- **The Daily Adventure Incense cannot be activated by the bot.** On the incense card the game ignores injected touches (ADB `input`, scrcpy mouse); only a real finger works. The routine for it is still in `gamebot.py` but is switched off and has no option in the web interface.
- Parts of the code were written for a single user and are not polished. Expect rough edges; issues and pull requests are welcome.

## Credits and license

- [RegiBot](https://github.com/Juancavr6/RegiBot) by Juancavr6 (MIT): the trained models, the anchors and the throw predictor. See [`NOTICE.md`](NOTICE.md).
- This project is released under the [MIT License](LICENSE).
