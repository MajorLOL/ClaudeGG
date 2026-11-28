Part of the [Claude GG roadmap](../../ROADMAP.md).

## 5. Keeping up with Pokémon Automation

The branch takes Pokémon Automation's changes commit by commit (`git cherry-pick -x`), since this repository starts as a snapshot and shares no history with it; what was taken last is in [CHANGES.md](../../CHANGES.md), section 1. Claude GG's own code sits in one folder (`ClaudeGG`) to keep those merges small; the files it changes elsewhere are the main window, the program list, the theme option, the global names and the handful of files of the fixes.

The fixes and the video frame conversion are separate commits, so that they can be offered to Pokémon Automation one at a time (its rules: new contributors at most two open pull requests, opened and answered by a person).
