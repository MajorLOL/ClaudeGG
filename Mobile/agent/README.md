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
git clone https://github.com/MajorLOL/ClaudeGG.git
cd ClaudeGG/Mobile/agent
bash install-agent.sh
```

It installs `adb` and Python 3, copies the agent to `~/claudegg-agent`, starts it as a service on port 8765
and prints the address and the token to enter in Claude GG (under the setup of a Raspberry Pi). The token is
made the first time and kept in `~/.claudegg-agent/token`; `claudegg_agent.py --print-token` shows it again.

The phone: Settings → About phone → tap *Build number* seven times → Developer options → *USB debugging* on;
connect it to the Pi and accept the question *Allow USB debugging?* on the phone (*Always allow*). `adb
devices` on the Pi must show it as `device`. The lock screen must be *swipe* or *none* for a program that
runs unattended.

## The protocol (version 1)

HTTP with JSON on the local network. Everything but `/v1/ping` needs the header
`Authorization: Bearer <token>`. It is plain HTTP: use it on a network you trust, not over the internet.

| Request | What it does |
|---|---|
| `GET /v1/ping` | `{"ok": true}`: is it there (no token) |
| `GET /v1/info` | `{model, android, width, height, display}`: the phone (`Override size` of `wm size` when set) |
| `GET /v1/screen` | the screen as a PNG (`X-Screen-Width`, `X-Screen-Height`) |
| `POST /v1/tap` `{x, y, ms}` | a press of `ms` milliseconds (120): a very short tap is missed by Unity games |
| `POST /v1/swipe` `{x1, y1, x2, y2, ms}` | a swipe (300 ms) |
| `POST /v1/swipes` `{strokes: [[x1, y1, x2, y2, ms], ...]}` | up to 50 swipes one after the other in ONE `adb` command: the phone starts the next the moment one is done |
| `POST /v1/key` `{key}` or `{keycode}` | `BACK`, `HOME`, `APP_SWITCH`, `POWER`, `WAKEUP`, `ENTER`, ... or a number 0 to 300 |
| `POST /v1/text` `{text}` | letters, digits, spaces and `. , _ @ : / + -`, up to 200 |
| `POST /v1/wake` | wakes the screen |

Errors are `{"error": "..."}` with 400 (an argument is wrong), 401 (the token), 413, 502 (`adb` says no: the phone is
off, not authorised, or not there) or 504 (`adb` does not answer).

What it will not do: open a shell, run a program or write a file on the phone. Every argument is checked and
`adb` is called with a list of arguments, never a line for a shell.

`claudegg_agent.py --help` lists the options (`--port`, `--serial` for more than one phone, `--display` for a
foldable's second screen, `--host 127.0.0.1` to listen on the Pi itself only).

## Tests

```bash
python3 -m unittest discover -s tests
```

`fake_adb.py` is a phone that is not there. Claude GG's own test (`ClaudeGG.exe --mobile-test`) starts this
agent with it and goes through the protocol with the code that Claude GG uses.
