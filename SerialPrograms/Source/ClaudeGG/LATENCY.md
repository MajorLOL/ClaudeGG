# Reaction time: where the time goes, and what ClaudeGG does about it

Written on 28 November 2026. The numbers come from the pages listed at the end and from the code; nothing here was measured on a console yet. Where a number is a guess, it says so.

Every route from ClaudeGG to a game is the same chain: **the picture** comes in (capture card, Remote Play window or phone), **the program decides** (a reader of Pokémon Automation, Claude GG's own code, or Claude), and **the command** goes out (a board that is a controller, or a phone through a Raspberry Pi). The game then needs its own frames to react before the next picture shows the result.

## The chain, link by link

| Link | Typical time | What decides it |
| --- | --- | --- |
| Wired board (ESP32-S3, Pico wired) → console | timing accuracy under 1 ms, usually about 0.1 ms | Pokémon Automation's controller list. The console reads a wired controller every 8 ms. |
| Wireless board (ESP32, Pico W) → console | timing varies 2 to 10 ms | Bluetooth; the Switch reads a Bluetooth Pro Controller every 8 to 24 ms. Interference makes it worse. |
| Game reacts | 3 to 8 frames (50 to 130 ms at 60 fps) | The game itself: Smash Ultimate takes 6 to 8 frames with a Pro Controller. Menus are often slower. |
| Capture card → program | about 1 to 3 frames; cards differ by 30 to 40 ms between them | The card, and its format: YUY2/NV12 is decoded by nothing; MJPEG has to be decoded by the processor first and adds time. A few old cards take hundreds of milliseconds. |
| Remote Play (PS4/PS5 via chiaki-ng, Xbox via the browser) | tens of milliseconds more than a capture card (a guess: 30 to 100 ms on a wired network) | Encoding on the console, the network, decoding, and OBS Virtual Camera adding about a frame. A streaming program measured 7 ms of its own on a local network; Remote Play is not that tuned. |
| Claude Plays: one turn of Claude | about 1 to 5 seconds (a guess from the way the API answers) | The model (Haiku is the fastest), the size of the picture, and how much Claude writes. This is by far the largest link. |
| Phone: one tap through the Pi | the agent: a few ms; `adb shell` before 0.2.1: about 100 to 200 ms more on a Pi (a guess); `input` on an old Android: about 500 ms | See the phone section. |
| Phone: a picture | `screencap`: 1 to 3 s while the game runs; the live stream: a new picture every 100 ms | The agent's live stream (`/v1/video`) is what Claude GG uses when it can. |

## What ClaudeGG does now

- **Phone agent 0.2.1** (`Mobile/agent`): taps, swipes, keys and text go through one `adb shell` that stays open, instead of a new `adb shell` for every tap. The agent waits for each command to end as before, and never tries a tap twice when the phone goes away. `claudegg_agent.py --measure` measures the gain on your own phone. See [the agent's README](../../../Mobile/agent/README.md), *Speed*.
- **TCP_NODELAY in the agent**: an answer is written in pieces, and without it the last small piece waits for an acknowledgement that Windows sends late on purpose (up to 200 ms). Every connection to the agent now has it, and a live picture goes out in one piece.
- **Claude Plays, `wait` until the picture changes**: it looks every 50 ms instead of every 250 ms, so a change is seen about 100 ms sooner on average. Waiting until the picture is *still* compares looks 250 ms apart as before, so slow motion is not taken for still.
- **Claude Plays, already**: the answer comes as a stream, the conversation is cached on Anthropic's side (a cached request starts sooner and costs less), the effort is "low", and the pictures go as JPEG at the size you choose (384, 640 or 960 wide). A smaller picture is a faster answer.
- **The capture card's default format**: the format with the most frames a second, and of those the uncompressed one (before: always the uncompressed one, also when that came at 5 fps). See *What you can do yourself*, 2.
- **Per console**: the waits after a press (longer behind Remote Play, for instance) are set per console in `ClaudePlays_Consoles` (another change of the same night).

## What you can do yourself

1. **Use a wired board.** The ESP32-S3 wired is Pokémon Automation's advice for a reason: under 1 ms of timing error against 2 to 10 ms wireless, and it does not drop out. Wireless is for travelling and for consoles that need it (retro through BlueRetro, the Wii U).
2. **Give the capture card 60 frames a second.** At 60 fps a new picture comes every 17 ms; at 10 fps every 100 ms. Uncompressed (YUY2/NV12) is a little faster than MJPEG, which the processor has to decode first, but only when the card gives it at the same frame rate: a card on USB 2 often gives 1080p uncompressed at only 5 or 10 fps. ClaudeGG now picks, for a resolution, the format with the most frames a second, and of those the uncompressed one. The resolution, format and frame rate under the video can still be set by hand (the global setting *Show all FPS Options* shows every choice). 720p at 60 is often better than 1080p at 30.
3. **Remote Play over a cable.** Console and computer on a wired network, or at least on 5 GHz Wi-Fi. In chiaki-ng a lower resolution (720p) and a higher frame rate (60) react faster than 1080p 30.
4. **A board on a USB-to-serial adapter** (the Pico W setups): if the adapter has an FTDI chip, Windows waits 16 ms by default before it hands over a short answer. Device Manager → the COM port → *Port Settings* → *Advanced* → *Latency Timer* 1 ms. (The ESP32-S3 has its own USB and does not need this.)
5. **Phone**: update the agent on the Pi (`git pull`, then `bash Mobile/agent/install-agent.sh`) and run `python3 ~/claudegg-agent/claudegg_agent.py --measure` with the bot stopped. A newer Android taps faster: older versions start a small Java program for every tap. Pi and computer on a cable, or on the same 5 GHz network.
6. **Claude Plays**: Haiku for games that need quick turns, the smallest picture that still shows what matters, and let the program's readers do the looking (*The program sees: ...*): a turn with only text is faster than one with a picture.

## Measuring it yourself

- The phone: `claudegg_agent.py --measure` (above).
- The whole chain on a console: film the screen and the board's LED (or a press you can see) with a phone in slow motion (240 fps is 4 ms a frame) and count the frames from the press to the first change on screen. A streaming company measured its latency this way, with a 1000 fps camera.

## Sources

- Pokémon Automation, controller list: https://pokemonautomation.github.io/ControllerList.html (wired under 1 ms, wireless 2 to 10 ms; ESP32-S3 the best wired setup)
- Handheld Legend, lag comparison: https://docs.handheldlegend.com/s/progcc-3/doc/lag-comparison-aAR1mV3JLX (Switch polls USB every 8 ms, Bluetooth 8 to 24 ms; Smash Ultimate 6 to 8 frames)
- Level1Techs, capture card latency, decode modes and formats: https://beta.level1techs.com/article/capture-card-documentation-latency-decode-modes-formats-more (YUY2 lowest load and latency, MJPEG adds decoding; 30 to 40 ms between cards)
- Parsec, testing game streaming input latency: https://parsec.app/blog/testing-game-streaming-input-latency-on-parsec-with-diy-instructions-49ae838f45a7 (7 ms of its own on a local network; the slow-motion method)
- Android, "Accelerate input commands execution" (AOSP bug 132724511), as in /e/OS: https://gitlab.e.foundation/e/os/android_frameworks_base/-/commit/9a7d7dbfb55e19e56f932c8820448514837f39c6 (`input tap` from 500 ms to under 10 ms by `cmd input`)
- Stack Overflow, "adb input tap is slow": https://stackoverflow.com/questions/68788995 (one second and more between taps the old way)
