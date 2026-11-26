# Claude GG

<img src="IconResource/claudegg-logo.png" width="420" alt="Claude GG: a handheld Nintendo Switch with orange Joy-Cons and a chat bubble that says GG on its screen">

Game automation for any console, starting with the Nintendo Switch. Run programs, or build and fix them with Claude.

A program of Claude GG plays a game by itself. It watches the game through a capture card and presses the buttons through a controller board (for example an ESP32). For now that is the Nintendo Switch, and most programs are for Pokémon games; the aim is every console a program can watch and press the buttons of (see [ROADMAP.md](ROADMAP.md)). Claude, in a panel of the main window, answers questions about the programs and can change their source, on a branch of its own that becomes a pull request.

It is a personal fork of [Pokémon Automation](https://github.com/PokemonAutomation/Arduino-Source)'s "SerialPrograms", with a new interface, a program that plays the whole story of FireRed and LeafGreen, Claude built in, and fixes of its own. The programs for the other games are those of Pokémon Automation.

Claude GG is not made, endorsed or supported by Nintendo, Game Freak, Creatures or The Pokémon Company, nor by Anthropic or the Pokémon Automation project. Please do not ask the Pokémon Automation team for help with this fork: use the [issues of this repository](https://github.com/MajorLOL/ClaudeGG/issues).

## Getting it

Every push to the branch `main` makes a Windows build and tests that it starts. A build that passes is published under [releases](https://github.com/MajorLOL/ClaudeGG/releases). Unzip `ClaudeGG-Windows.zip` and run `ClaudeGG.exe`.

To keep the settings of an older build, close it and copy its `UserSettings` folder into the new folder. The hardware and its setup are the same as for Pokémon Automation: see [its documentation](https://pokemonautomation.github.io/).

## What is different from Pokémon Automation

| | |
|---|---|
| **Interface** | A new window made of the screens of the setup: the games, the programs of a game (with the live picture, the checks, the log and the options) and the program itself. Two themes of its own, Night and Day, in the color of a starter; the old looks are still there as "Classic". |
| **Claude** | A panel where you talk to Anthropic's Claude, on an API key of your own. It answers questions about the programs and builds or fixes them: every change goes to a `claude/...` branch and a pull request that is built and tested before you merge it. The program **Claude Plays**, in the list of every game, lets Claude play toward a goal you write down. See [ASSISTANT.md](SerialPrograms/Source/ClaudeGG/ASSISTANT.md). |
| **Intro** | A short film at startup. Settings or `--no-intro` turns it off. |
| **Installations** | Several installations run side by side, each in its own window and process, with its own settings, capture card and microcontroller. An overview shows a miniature of each. |
| **FRLG AutoStory** | Plays FireRed or LeafGreen from a new game to the Hall of Fame and on, up to a Pokédex collection. See [the program's folder](SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory). |
| **Experimental programs** | New programs and options that have not run on a console yet carry the tag "experimental". What each is for and how far it was tested: [ROADMAP.md](ROADMAP.md), sections 6 and 7. |
| **Search** | The games and the programs of a game have a search field; just start typing. |
| **Fixes** | Fixes for bugs found in a review of the whole code: [FIXES.md](SerialPrograms/Source/ClaudeGG/FIXES.md). Pokémon Automation's open issues and where this fork stands on each: [ISSUES.md](SerialPrograms/Source/ClaudeGG/ISSUES.md), [OTHERS.md](SerialPrograms/Source/ClaudeGG/OTHERS.md). |
| **Video frames** | Pictures of the screen are made without Qt's `QVideoFrame::toImage()`, which on some computers grows the memory by up to 1.6 GB an hour. |
| **Builds** | Each build starts once on the build machine, as on a computer that never ran it, goes through its pages and saves a picture of each. A build that fails is not published. |
| **Left out** | The check for a new version (it is for Pokémon Automation's releases), Discord Rich Presence by default, and the Discord bot and Social SDK in the Windows build. |

Everything that differs from Pokémon Automation, with the reason for each change and the faults of the original that were found and fixed: [CHANGES.md](CHANGES.md); every file that differs: [CHANGED-FILES.md](CHANGED-FILES.md). How to set this repository up on GitHub: [GITHUB-SETUP.md](GITHUB-SETUP.md). What is planned: [ROADMAP.md](ROADMAP.md).

## Building

Claude GG builds like Pokémon Automation's SerialPrograms: see [SerialPrograms/BuildInstructions](SerialPrograms/BuildInstructions). The Windows builds are made by [this workflow](.github/workflows/claudegg-windows.yml) with Qt 6.10.2.

`SerialPrograms --ui-screenshots <folder>` starts the program, saves a picture of each page and exits; nothing is pressed on a console and no setting is saved. Its exit code is 0 when every picture was taken and every check passed. The other tests are `--language-test`, `--setup-test <folder>`, `--tutorial-test`, `--installation <name> --installation-test` and `--installations-hub-test <folder>`; the Windows workflow runs them all.

## Language and setup

The first start goes through a setup in the style of the intro: the **language**, the **console** and the **microcontroller**, then the **game** and the **program** to start. Menus wait for your choice (mouse or keyboard). Settings can open the setup again.

- **Language.** English is the default. Dutch, German, French and Spanish come with the program; **Other** reads your own file, `Languages/custom.json`. A language applies at once and can be changed in Settings.
- **Console.** Nintendo Switch or Switch 2. The other consoles are shown as "Coming soon". For now the choice is only kept; the programs detect the console themselves.
- **Microcontroller.** Raspberry Pi Pico W, Pico 2 W, ESP32 and ESP32-S3 get their steps in the program, and the installation (drivers, firmware, flashing) can be done from the menu. The steps are those of the [Pokémon Automation Setup Guide](https://pokemonautomation.github.io/SetupGuide/index.html). A video tutorial of each plays in the program.
- **A phone, through a Raspberry Pi (in the making).** The repository of the Pokémon GO bot for a Raspberry Pi and an Android phone is part of this one, in [Mobile](Mobile). Its [agent](Mobile/agent) lets a Pi give Claude GG the picture of the phone (one screenshot, or a live stream of about ten pictures a second) and take its taps, and Claude GG has the other end of that connection, tested in every build. The setup offers a phone as a console, with a page for its Raspberry Pi (address, token and a test of the connection); no program plays on one yet: see "A phone as a console" in the [roadmap](ROADMAP.md). Automating Pokémon GO is against Niantic's Terms of Service; use it at your own risk.
- **Firmware.** The firmware of the build is in the folder `Firmware`; newer versions can be downloaded from Pokémon Automation's [Packages](https://github.com/PokemonAutomation/Packages/tree/master/Firmware).
- **Game and program.** After the setup comes the choice of the game, then of its program, with the live picture, the checks, the log (with **Copy for Claude**, a text that is ready to paste into Claude) and the program's options next to it. Both screens can be turned off in Settings.

**Translation.** The English text stays in the source. A language is a file, `Resources/lang/<code>.json`: the English text as the key, the translation as the value. A file `Languages/<code>.json` next to the program wins over the built-in one, so a translation can be added or fixed without building. The setup, Claude GG's own windows and the Global Settings are translated; the option texts of the programs and the prompts of Claude are not yet and stay English.

## Where the code is

Claude GG's own code is in [SerialPrograms/Source/ClaudeGG](SerialPrograms/Source/ClaudeGG): the themes, the frame of the main window, the Games page, the setup, the installations and the tests of the interface. Claude is in its folder [Assistant](SerialPrograms/Source/ClaudeGG/Assistant). The rest of the tree is Pokémon Automation's, with the changes this fork needs. The branch follows Pokémon Automation's `main` by merging it.

## Licenses

- The source code is under the MIT license, like Pokémon Automation's: see [LICENSE](LICENSE) (Copyright (c) 2021 Alexander J. Yee). Claude GG's own changes and additions are under the same license.
- The builds bring along precompiled libraries and the resources of Pokémon Automation ([Packages](https://github.com/PokemonAutomation/Packages)), which that project gives for non-commercial use only. Use the builds for non-commercial purposes.
- The typeface of the name and the headings is Jersey 20 by Sarah Cadigan-Fried, under the [SIL Open Font License 1.1](SerialPrograms/Source/ClaudeGG/Resources/Jersey20-OFL.txt). The setup uses Newsreader and Fredoka, also under the SIL Open Font License 1.1: [Newsreader](SerialPrograms/Source/ClaudeGG/Resources/setup/Newsreader-OFL.txt), [Fredoka](SerialPrograms/Source/ClaudeGG/Resources/setup/Fredoka-OFL.txt).
- The Windows builds also bring along [esptool](https://github.com/espressif/esptool) of Espressif Systems (GPL-2.0-or-later) in the folder `Tools/esptool`, as a separate program that the setup starts to flash the ESP32 boards; its license and where its source is are in the `Licenses` folder of the build. The firmware in the `Firmware` folder is Pokémon Automation's, for non-commercial use.
- The folder [Mobile](Mobile) is the repository pokemon-go-automation, under the MIT license (Copyright (c) 2026 MajorLOL: [Mobile/LICENSE](Mobile/LICENSE)). It uses models and data of [RegiBot](https://github.com/Juancavr6/RegiBot) and [PvPoke](https://github.com/pvpoke/pvpoke), both MIT: see [Mobile/NOTICE.md](Mobile/NOTICE.md). It is not part of the builds.
- The Claude wordmark in the intro is Anthropic's: see the notice above. The names of the games belong to their owners and are used only to say which game a program is for.

Dependencies, as in Pokémon Automation:

| **Dependency** | **License** |
| --- | --- |
| Qt6 | LGPLv3 |
| [QDarkStyleSheet](https://github.com/ColinDuquesnoy/QDarkStyleSheet) | MIT |
| [Qt Wav Reader](https://code.qt.io/cgit/qt/qtmultimedia.git/tree/examples/multimedia/spectrum/app/wavfile.cpp?h=5.15) | BSD |
| [nlohmann json](https://github.com/nlohmann/json) | MIT |
| [D++](https://github.com/brainboxdotcc/DPP) (in the source; the Windows build leaves it out) | Apache 2.0 |
| [Tesseract](https://github.com/tesseract-ocr/tesseract) | Apache 2.0 |
| [Tesseract for Windows](https://github.com/peirick/Tesseract-OCR_for_Windows) | Apache 2.0 |
| [OpenCV](https://github.com/opencv/opencv) | Apache 2.0 |
| [ONNX](https://github.com/microsoft/onnxruntime) | MIT |
| [sdbus-c++](https://github.com/Kistler-Group/sdbus-cpp) | LGPLv2.1 |
| [SDL](https://github.com/libsdl-org/SDL) | zlib |

A tiny part of Pokémon Automation is not open source (telemetry and internal experiments, by its own README). It is not in this repository.
