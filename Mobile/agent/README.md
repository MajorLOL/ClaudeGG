# Claude GG agent: a Raspberry Pi as the controller of an Android phone

For a Nintendo Switch, Claude GG looks at the game through a capture card and presses the buttons through a
board (a Pico or an ESP32 that the Switch takes for a controller). For an Android phone the Raspberry Pi is that
board: the phone is on its USB cable, and the Pi gives the computer what the capture card and the board give
for a console: **a picture of the screen, and taps, swipes and keys.**

```
 Claude GG (computer) ──network──► Raspberry Pi (this agent) ──USB (ADB)──► Android phone
   looks at the picture,              the hands and eyes:                       the game
   decides what to press              no thinking of its own
```

The agent has no thinking of its own. Claude GG does the thinking, so the Pi can be a Pi Zero 2 or a 3 as
well as a 4, and the program that decides is one for all consoles. (The older bot in the folder above this one,
`gamebot.py`, does everything on the Pi, in Python; it stays here until Claude GG does what it does.)

> **Automating Pokémon GO is against Niantic's Terms of Service.** Accounts that do it can be warned,
> suspended or banned. Use it at your own risk, on an account you can afford to lose. This is not affiliated
> with Niantic, Nintendo, The Pokémon Company or Google. The agent itself works for any app.

## Install

On the Pi (Raspberry Pi OS, 64-bit is not needed for the agent):

```bash
git clone --depth 1 https://github.com/MajorLOL/ClaudeGG.git
cd ClaudeGG/Mobile/agent
bash install-agent.sh
```

(Run the installer as yourself, not with `sudo`: it asks for `sudo` where it needs it, and the service runs as you.)
It installs `adb`, Python 3 and `ffmpeg` (for the live picture), copies the agent to `~/claudegg-agent`, starts it as a service on port 8765
and prints the address and the token to enter in Claude GG (under the setup of a Raspberry Pi). The token is
made the first time and kept in `~/.claudegg-agent/token`; `claudegg_agent.py --print-token` shows it again.

**Updating** an agent that is installed: in the folder of the clone on the Pi, `git pull`, then `bash Mobile/agent/install-agent.sh`
again. The token stays the same, and the service is restarted with the new file. `python3 ~/claudegg-agent/claudegg_agent.py --version`
says which version is installed; Claude GG's own GO Battle League needs 0.2.0 or later and says so when the agent is older; 0.2.1 taps faster (see *Speed*).

The phone: Settings → About phone → tap *Build number* seven times → Developer options → *USB debugging* on;
connect it to the Pi and accept the question *Allow USB debugging?* on the phone (*Always allow*). `adb
devices` on the Pi must show it as `device`. The lock screen must be *swipe* or *none* for a program that
runs unattended.

## The protocol (version 1)

HTTP with JSON on the local network. Everything but `/v1/ping` and the status page needs the header
`Authorization: Bearer <token>`. It is plain HTTP: use it on a network you trust, not over the internet.

| Request | What it does |
|---|---|
| `GET /` or `GET /status` | the status page, for a browser on the network (no token: the page holds nothing secret, it asks for the token and keeps it in the tab until the tab is closed; a bookmark with `#token=...` opens it at once and takes the token out of the address). It shows whether the bot runs, the last screenshot (every ten seconds, not while the tab is hidden), today's counters (caught, fled, stops, won, lost), the GO Battle League matches of today, the switches that are on, and the end of the log. It only looks: it starts and stops nothing. One file with no address of anywhere else in it; the browser is told (`Content-Security-Policy`) to run nothing but that script and to speak to nobody but the agent, and what the agent says is put on the screen as text, never as markup |
| `GET /v1/ping` | `{"ok": true, version, features}`: is it there (no token) |
| `GET /v1/info` | `{model, android, width, height, display, version, features}`: the phone (`Override size` of `wm size` when set). `features` is what the agent can do beyond version 0.1.0: `tap_kind` (the `kind` of `/v1/tap`), `app` (`/v1/app`), `bot_file` (`/v1/bot/file`) |
| `GET /v1/screen` | the screen as a PNG (`X-Screen-Width`, `X-Screen-Height`) |
| `GET /v1/video?fps=10&width=540` | the screen live, about ten pictures a second (a screenshot takes one to three seconds): JPEG pictures in a `multipart/x-mixed-replace` stream (boundary `frame`, each part with its `Content-Length`). `screenrecord` (H.264) goes through `ffmpeg` on the Pi; one pipeline serves all who look, starts with the first and stops five seconds after the last, and is started again every 170 seconds (`screenrecord` ends after 180) without the viewer noticing. A screen that does not change gives the last picture again once a second. `fps` 1 to 30, `width` 100 to 2000 (a pipeline that is running keeps the values it started with) |
| `POST /v1/tap` `{x, y, ms, kind}` | a press of `ms` milliseconds (120): a very short tap is missed by Unity games. `kind`: `"press"` (the default), `"tap"` (a plain `input tap`, finger down and up at once: some screens of a game take this and not a press) or `"motion"` (finger down, `ms`, finger up as separate touch events, Android 11 and newer) |
| `POST /v1/swipe` `{x1, y1, x2, y2, ms}` | a swipe (300 ms) |
| `POST /v1/swipes` `{strokes: [[x1, y1, x2, y2, ms], ...]}` | up to 50 swipes one after the other in ONE `adb` command: the phone starts the next the moment one is done |
| `POST /v1/key` `{key}` or `{keycode}` | `BACK`, `HOME`, `APP_SWITCH`, `POWER`, `WAKEUP`, `ENTER`, ... or a number 0 to 300 |
| `POST /v1/text` `{text}` | letters, digits, spaces and `. , _ @ : / + -`, up to 200 |
| `POST /v1/wake` | wakes the screen |
| `POST /v1/app` `{action, package}` | the Pokémon GO app of the phone (`package` is `com.nianticlabs.pokemongo` or another one that starts with that, such as the Galaxy Store one; nothing else is closed or started). `"stop"`: `am force-stop`. `"start"`: `monkey -p <package> -c android.intent.category.LAUNCHER 1` as the bot starts the game; `monkey` does not come back while the game is starting (it waits for the app, up to half a minute), so the call does not wait for it: the answer is `{ok: true}` at once and the screen can be looked at meanwhile. `"state"`: how that start is going, `{ok, running, code, error}` (`code` and `error`, what `monkey` wrote on stderr, are only set when it has ended; 409 when the game was not started). `"end"`: lets go of the start command that still runs (the game itself goes on). A new `"start"` lets go of the one before. This is what `restart_game()` of the bot does, in the pieces that a program on another computer needs |
| `GET /v1/bot?lines=40` | the Pokémon GO bot of `Mobile/` (`gamebot.py`, installed in the home folder as the service `spin-stop`): `{installed, running, options, throw_target, daily_time, daily_max_min, battle_app, battle_league, battle_count, today, battles, test, log}`, with the last `lines` (1 to 200) of `~/spin.log`. `today` are the counters the bot keeps for the day, as its last `(today: ...)` line of today says: `{caught, fled, stops, won, lost, day}` (zero until the bot has counted). `battles` are the GO Battle League matches of today as the log tells them: `{won, lost, list: [{time, league, result, gave_up}]}`; `test` is the part of the bot that runs or ran last: `{key, title, running, ok, result, seconds}` |
| `POST /v1/bot/start` `{options, throw_target, daily_time, daily_max_min, daily_now, battle_app, battle_league, battle_count}` | sets what is asked in the bot's control file (`~/gamebot_control.json`, as its web interface does) and starts the service (restarts it when it runs). `options` are only switches of this list, true or false: `spin`, `catch`, `gifts_open`, `gifts_send`, `daily_cycle`, `curveball`, `fast_catch`, `spin_only_when_full`, `close_when_full`, `rocket_fight`, `quests`, `bag_clean`, `buddy`, `fast_look`, `heat_pause`, `live_look`, `battle` (the daily run fights GO Battle League battles first), `battle_give_up`, `teams_weekly`. `battle_app` is empty (the Play Store app) or a Pokémon GO package, `battle_league` the league as the game names it, `battle_count` 1 to 50. `daily_now` makes the daily run begin at once. 409: the bot is not installed, or a test of it runs |
| `POST /v1/bot/stop` | stops the service, and a test of the bot that runs |
| `GET /v1/bot/tests` | the parts of the bot that run on their own, `{tests: [{key, group, title, start, what}]}`, as the bot's own `chapters.py` in the home folder lists them (empty without it) |
| `POST /v1/bot/test` `{key, ...}` | runs one part of the bot (`gamebot.py chapter <key>` with the python of `~/gbvenv`: what *Test* in the bot's web interface does): stops the service, sets what is asked (the same fields as `/v1/bot/start`), starts the part. What it says of itself (`TEST <key>: done - ...`) is its result in `test` of `GET /v1/bot`. 400: no such part, 409: not installed, no `chapters.py`, or a test runs already |
| `POST /v1/bot/test/stop` | ends that test (it says `stopped` and goes back to the map; that can take half a minute) |
| `GET /v1/bot/file?name=battle_team.json` | one of the files the bot keeps of its battles, as it is: `battle_team.json` (the team that the bot's teams step made), `battle_seen.json`, `battle_minigame.json`. Read only, nothing else of the home folder; 404 when the file is not there. Claude GG takes the team from here when it plays GO Battle League itself |

Errors are `{"error": "..."}` with 400 (an argument is wrong), 401 (the token), 413, 502 (`adb` says no: the phone is
off, not authorised, or not there) or 504 (`adb` does not answer).

The bot is started and stopped with `sudo -n /usr/bin/systemctl`: the user of the agent needs a sudoers rule for
`start`, `stop` and `restart` of `spin-stop`, and nothing else. `install-agent.sh` checks one with `visudo` and writes it
to `/etc/sudoers.d/claudegg-agent` (the bot's web interface needs the same rule, see the page *Installation* of the wiki);
without it the answer is a 502 that says so.

What it will not do: run a program of its caller or write a file on the phone. Every argument is checked
before a command is made: only numbers, the names of keys, and text of letters, digits and `. , _ @ : / + -`
reach the phone. On the Pi, `adb` is called with a list of arguments, never a line for a shell.

## Speed

Since 0.2.1 the taps, swipes, keys and text go through one `adb shell` that stays open, instead of a new
`adb shell ...` for every one. A new one starts the adb program on the Pi, connects to the adb server and
has the phone start a shell before the tap itself begins: tens of milliseconds on a fast computer, often
100 to 200 on a Raspberry Pi. Through the shell that stays open, a tap is one line written to it.

- A command waits for the one before it to end, as it did before (the answer comes once the swipe is done).
  When the shell is busy with a long swipe, another command goes the old way at once instead of waiting.
- When the phone goes away, the command in the shell is an error (502, as before) and is never tried twice;
  the next one starts a new shell.
- `--no-shell-session` goes back to a new `adb shell` for every command.
- `claudegg_agent.py --measure` measures it on your own phone: it sends 20 times a key that does nothing
  (`input keyevent 0`) each way and prints the middle and slowest time. Leave the bot and Claude GG stopped
  while it runs.

What else takes time with a phone:

- The command `input` itself. On older Android it starts a small Java program for every tap (about half a
  second); newer Android has `input` call `cmd input`, which asks the system directly (under 10 ms, by the
  change "Accelerate input commands execution" in Android itself). An old phone is therefore slower to tap:
  `--measure` shows it (a middle time of several hundred ms with the shell that stays open).
- A screenshot (`/v1/screen`, `screencap`) takes one to three seconds while the game runs. The live
  picture (`/v1/video`) has a new picture about every 100 ms; Claude GG uses that one when it can.
- Wi-Fi between the computer and the Pi: a cable (or the Pi and the computer on the same 5 GHz network)
  keeps each request to a few milliseconds.

`claudegg_agent.py --help` lists the options (`--port`, `--serial` for more than one phone, `--display` for a
foldable's second screen, `--host 127.0.0.1` to listen on the Pi itself only).

## Tests

```bash
python3 -m unittest discover -s tests
```

`fake_adb.py` is a phone that is not there, `fake_systemctl.py` a service manager that is not one. Claude GG's own test (`ClaudeGG.exe --mobile-test`) starts this
agent with it and goes through the protocol with the code that Claude GG uses.
