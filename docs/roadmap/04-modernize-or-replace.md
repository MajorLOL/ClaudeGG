Part of the [Claude GG roadmap](../../ROADMAP.md).

## 4. What could be modernized or replaced

Done in the first build: the interface and its themes, the build (Ninja, ccache, a test of the interface), the video frame conversion, readable colors, the bug fixes.

Candidates:

| What | Why |
|---|---|
| **The Qt version** | The builds use Qt 6.10.2 like Pokémon Automation's own workflow, while its build guide still names 6.8.3 (later versions hang when threads end, which the program works around by exiting hard). Worth one build with 6.8.3 to see whether the memory growth of `toImage()` is there too. |
| **`catch (...)` in the programs** | Looked at on 26 November 2026: of 116 `catch (...)` in the sources, 87 do not throw again. In the programs (FRLG AutoStory, SV) they wrap file writes, a destructor, or a retry whose handler calls the console again, and that call throws the stop again as the program's context stays cancelled, so a stop is not lost. Three handlers around the flight from a battle (Terarium, Blueberry quests, Blueberry photos) turn a stop into the error "Unable to flee": the program still ends, but with a failure report instead of a clean stop. A handler that only logs and goes on, around a call that waits, would lose the stop: none was found. New code should let the stop through (`catch (OperationCancelledException&){ throw; }` first). |
| **Pokémon Automation's tests in this fork's workflow** | Done: the step "Pokemon Automation's tests" checks out `PokemonAutomation/CommandLineTests` at a pinned commit (`dd7363a`, master on 26 November 2026; moved on purpose, as Packages is), unpacks the PaddleOCR resource into `bin/DownloadedResources` and runs `ClaudeGG.exe --command-line-test-mode` from `bin`. It passed in every run (27,599 tests, 0 failed), so since 27 November 2026 a failure keeps the build from being published. Next: move the pin when Pokémon Automation's tests change, together with the code taken from it. |
| **One interface, in the style of the setup** | The goal: everything in the style of the setup screens. The old main window (top bar, side bar, pages with the games, status strip, `--classic-interface`) was removed on 25 November 2026; the two classic *themes* of Pokémon Automation (Light and Dark, for the options and the dialogs) are still there as a choice under Settings. Done: the intro, the language, the console, the board and its installation, the choice of the game, and the programs of the chosen game (with the live picture, the checks, the output log with "Copy for Claude", a timeline, and the options of the program that is picked in a panel that slides open next to the list, wide for a program with many options, and the picture over the whole screen) as screens of their own. Since the first version of the window as these screens (see the list below): the open program and the settings are held inside the screen, Claude is a panel over the right, and the buttons of the old top bar are along the top. Next: restyle the program's own page (console setup, start and stop, log, video) and the settings in the style of the screens, let the lane of the program on the timeline show its loops and the board lane its answers. The list of programs (`ProgramSelect`) is still a widget, kept out of sight, that makes the programs and loads their panels: it can become a plain list. |

### The window as the screens of the setup: what each button does now

The first version of "one interface" was made without the old window's buttons being specified, so each one got an interpretation of mine. They are listed here to be reviewed; each is one place in the code. (The old window has been removed since: the first column says what the button was.)

| Where | Old | Now (interpretation) | To decide |
|---|---|---|---|
| Games > a game > **Start** | opened the game's page in the old window | opens the programs of that game, in the same screen | |
| Programs > **Start** | opened the program in the old window | opens the program's own page *inside* the screen (`HostPage`), under a header: way back, game and program, state | The page itself is the old widget; since 28 November 2026 it has the look of the program options next to the list (dark, rounded fields, buttons and boxes, the scroll bars of the screens), whatever the classic theme is. Next: its parts (console setup, start and stop, log, video) as parts of the screen |
| Programs and Games > **Choose later** | closed the setup, the old window opened | left out: there is nothing to leave. Still there in the setup of the first start | |
| Programs > **All games** | - | back to the games, the game stays picked | |
| Header of an open program > the way back | "Home" in the top bar | back to the programs of that game (to the games for the settings). Off while a program runs, as the list of programs was locked | Should it ask before it closes a program with changes? (The options are kept when it closes, as before.) |
| Top bar > **Home** | the page with the games | **Games** along the top (not on the games themselves); closes the open program, not while one runs | |
| Top bar > **Settings** | the settings panel in the old window | the settings panel held in the screen, like a program | Not while a program runs, as before |
| Top bar > **Claude** | a panel in the frame at the right | the same panel over the right of the screen (34 % of the window, 380 to 640 px); the open program gives it room. The setting for its width is not used | Claude's width should be dragged? |
| Top bar > **Output** and **Buttons** | the log window and the diagram of the buttons | a panel over the window (`ClaudeGG_Panel.h`): a card with a title and a cross, Esc or a click beside it puts it away. No window of its own, so nothing is left open when the program closes | |
| Top bar > **About** | the dialog | the same text in a panel over the window | Restyle |
| Top bar > the **side bar** switch | showed and hid the side bar | gone: there is no side bar (the list of programs is kept out of sight, to make the programs and load their panels) | |
| Status strip > the **state** | "Ready" / "Running ..." | a chip in the header of the open program. Not on the programs and the games: a program that runs cannot be left, so they are never in view while one runs | |
| Status strip > **sleep** | the text and the check box | the text and "Keep the screen on" / "Let the screen sleep" at the foot of the open program; kept for the next start (also a setting, "Keep the screen on") | |
| Page with the games > **Resume** | opened the program of the last session | the window starts on the games, no program is loaded at the start; a button "Continue with <program>" next to Start opens the program of the last time (the one the settings keep) | Should it load at the start, as before? |
| Page with the games > the **search over all programs** | found a program in any game | a search field on the games: what is typed turns the cartridges into a list of the programs that match (name first, then description and game); Up, Down, Left, Right and Enter, or a click, open one; Escape clears it | Also a search in the settings? |
| Choose another console (games) | - | the screen of the consoles, then back to the games; the console is kept at once | |
| Settings > **Open the setup** | the setup as a window of its own | the same: the full screen setup over the window | |
| **Closing** | options of the open program kept | the same | |

What the test checks: `--setup-test` (the screens with made-up actions: Start does not end the screen, the program is held and shown, the way back, no way back while a program runs, Claude over the right, a program that cannot be opened, the console that is picked is passed on) and `--ui-screenshots` (the real window: the games, a game's programs, a real program, Claude, the settings, back).
