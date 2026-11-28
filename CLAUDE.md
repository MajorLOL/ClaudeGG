# CLAUDE.md

A short guide for Claude working in this repository. Read this first; open the long
documents only for the part you need.

## What this is

Claude GG (MajorLOL/ClaudeGG) is a fork of Pokémon Automation's "SerialPrograms"
(C++23, Qt 6.10.2, Windows release). Goal: automatic controller input for every console
and for a phone. The repository starts as a snapshot of the fork at build 102, so it
shares no git history with Pokémon Automation.

- Upstream's own rules for agents (Qt, filesystem, threads, code style, tests):
  [AGENTS.md](AGENTS.md). They still apply. Two things there are out of date for this
  fork: upstream's `cpp-ci-*` workflows are removed (see "CI" below), and test images
  come from `PokemonAutomation/CommandLineTests`, pinned in our workflow.
- What differs from upstream and why: [CHANGES.md](CHANGES.md); every changed file:
  [CHANGED-FILES.md](CHANGED-FILES.md).
- Plans and status of each idea: [ROADMAP.md](ROADMAP.md), an index of
  `docs/roadmap/*.md` (one file per section; read only the one you need).

## Where things live

| Path | What |
|---|---|
| `SerialPrograms/Source/ClaudeGG/` | All of Claude GG's own C++: interface (Setup, Home, Panel, Theme, Intro), installations, languages, firmware, Claude panel (`Assistant/`), Claude Plays (`ClaudePlays/`), phone/Pokémon GO port (`ClaudeGG_PokemonGo*.cpp`, `*Check.cpp` = checks against the Python golden files). Notes: `ASSISTANT.md`, `FIXES.md`, `ISSUES.md`, `OTHERS.md`. |
| `SerialPrograms/Source/ClaudeGG/Resources/lang/` | Translations `nl.json`, `de.json`, `fr.json`, `es.json` (English text -> translation). |
| `SerialPrograms/Source/VideoGames/PokemonFRLG/` | FRLG programs, including the fork's AutoStory. Its route data/scripts: `SerialPrograms/Scripts/PokemonFRLG/`. |
| `SerialPrograms/cmake/SourceFiles.cmake` | Explicit list of source files: **every new .cpp/.h must be added here.** |
| `Mobile/` | Python Pokémon GO bot for a Raspberry Pi + Android phone (ADB). `Mobile/agent/` is the small HTTP agent on the Pi that the C++ program talks to. `Mobile/tests/fixtures/*_golden.json.qz` are the answers the C++ port is held to. |
| `WiiU/vanilla-bridge/` | C bridge for a Raspberry Pi as Wii U GamePad (Vanilla); the C++ side is `ClaudeGG_WiiU.cpp`. |
| `Common/`, the rest of `SerialPrograms/Source/` | Pokémon Automation's code. Change it only for a real fix; keeping it close to upstream keeps syncing easy. |
| `.github/workflows/` | `claudegg-windows.yml` (build, tests, release), `mobile-python.yml`, `tabs.yml`. |

## Build and test

There is no Windows machine or Qt 6.10 here. The real build and the tests run in CI.

- **CI on every PR into `main`:** `claudegg-windows.yml` builds with MSVC/Ninja/ccache,
  then runs the program's own tests (`--setup-test`, `--language-test`, `--intro-test`,
  `--tutorial-test`, `--installation-test`, `--embed-test`, `--host-test`,
  `--mobile-test`) and upstream's `--command-line-test-mode`. A run takes about
  20 minutes: the build ~2 minutes with a warm ccache (~35 minutes from an empty cache),
  the tests ~15. A new push to the same branch cancels the running build.
- **A push to `main`** is built, tested and published as a pre-release (`v0.2.0.N`).
- **Warnings are errors** (`/W4 /WX`). A missing `[[nodiscard]]` check or an unused
  variable fails the build.
- **Quick local check in the container** (syntax only, no link): install Qt 6.4 with
  `apt-get install -y qt6-base-dev qt6-multimedia-dev qt6-svg-dev`, then from
  `SerialPrograms/Source` run
  `g++ -std=c++20 -fPIC -fsyntax-only -I. -I../.. -I../../Common -I../../3rdParty -I/usr/include/x86_64-linux-gnu/qt6 -I<each Qt* subfolder> <file>.cpp`.
- **Python (`Mobile/`):** `cd Mobile && python3 -m unittest discover -s tests`, and
  `python3 -m unittest discover -s agent/tests` for the agent. CI uses Python 3.12 with
  pinned versions (`mobile-python.yml`, about 4 minutes, only when `Mobile/**` changes).

## Rules

- **Line endings:** almost every source file and most top-level `.md` files are CRLF
  (`* -text`, no normalization). Keep each file's own line endings; never convert a
  whole file. Python's text mode turns CRLF into LF: read and write with `newline=''`.
- **No tabs** in source files (the "Check for Tabs" job).
- **Translations:** user-facing text stays English in the source (`tr_ui("...")`, or the
  filter on labels/buttons). New or changed text in the interface needs an entry in all
  four files in `Resources/lang/` (nl, de, fr, es), keeping `%1`, tags and line breaks.
  `--language-test` checks this.
- **Upstream sync:** Pokémon Automation's commits are taken one by one with
  `git cherry-pick -x` (no merge; the histories are unrelated). Record what was taken,
  what was already here and what was left out in `CHANGES.md` section 1.
- **Documentation of changes:** a change to upstream's files goes in `CHANGES.md` (and
  `CHANGED-FILES.md`); a new idea or its status goes in the right `docs/roadmap/` file.
- **Experimental:** nearly nothing has run on real hardware (Switch, PS3, Xbox, Pi,
  phone). Mark new console or program support "experimental" and say what was tested.
- **Git:** one feature or fix per PR, branch `claude/...`, PR into `main`, squash merge
  (the PR number ends up in the commit title). Do not push or open a PR without asking.
- **Parallel work:** several Claude threads work in this repository at once. Before
  editing a shared file (`ROADMAP.md`/`docs/roadmap/`, `CHANGES.md`, `README.md`,
  `SourceFiles.cmake`), check the open PRs for the same file and keep edits small.
