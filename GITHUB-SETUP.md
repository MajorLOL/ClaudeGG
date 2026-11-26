# Setting up Claude GG on GitHub

How the repository has to be set up for the build, the releases and Claude's panel to work. The workflow ([`.github/workflows/claudegg-windows.yml`](.github/workflows/claudegg-windows.yml)) needs no secrets and no token of yours: it uses the `GITHUB_TOKEN` that GitHub gives every run. What it needs are the settings below.

Written on 26 November 2026. GitHub moves its settings around; where a name below is not where you find it, the setting is the same one.

## 1. Make the repository

1. **A new, empty repository** (github.com/new): no README, no `.gitignore`, no license; those are in the code. A name such as `ClaudeGG`. Make it **public**: the build runs on a Windows runner, which is free for a public repository; in a private one the minutes count double against the free ones (a build of about 12 minutes is then 24), and the 10 GB of cache is shared. Check GitHub's current prices before you choose private.
2. **Fork or not.** A fork of `PokemonAutomation/Arduino-Source` keeps the line "forked from" and the page "Compare", and can open pull requests to Pokémon Automation. But an account normally has one fork of the same repository (the old one), and a fork cannot be turned into a plain repository except by GitHub's support. A new repository that is not a fork is clean: it gets the full history by a push, the history credits the authors, and a fix for Pokémon Automation is offered from a fork of theirs (the old one will do). This guide assumes a repository that is not a fork.
3. **The code, with or without its history.** The code is MIT-licensed, Copyright (c) 2021 Alexander J. Yee: the file `LICENSE` stays. There are two ways, and this repository was made the second way:

   - *With the history* (the importer): github.com/new/import, the address of the old repository as the source, then the name. The history (with the authors), all branches and the tags come along; the releases do not. A copy made by `git clone --depth` cannot be pushed this way: GitHub refuses a history that is cut off.
   - *As a snapshot*: one commit with the files as they are, and the history stays in the old repository. [CHANGES.md](CHANGES.md) and [CHANGED-FILES.md](CHANGED-FILES.md) then say what differs from Pokémon Automation.

     ```
     git checkout --orphan snapshot
     git add -A && git commit -m "Claude GG, a snapshot of <old repository> at build <N>"
     git push https://github.com/<owner>/<repo>.git snapshot:main
     ```

   Do not push the branches `claude/...` that exist now; they are finished pull requests of the old repository. Releases do not move with a push: see section 6.
4. **The default branch is `main`** (Settings → General → Default branch). The builds, the pull requests of Claude and the update check all look at it.

## 2. Tell the program where it lives

The program has the address of its repository in one place: `PROJECT_HOME_URL` in [`SerialPrograms/Source/CommonFramework/Globals.cpp`](SerialPrograms/Source/CommonFramework/Globals.cpp), as `https://github.com/<owner>/<repo>/tree/<branch>`. The About window, the button "Check for updates" and Claude's panel (which repository it reads, and which branch is the base of its pull requests) take their owner, name and branch from it. Change it, and the links in the texts:

```
sed -i 's#MajorLOL/\(ClaudeGG\|[Aa]rduino-[Ss]ource\)#<owner>/<repo>#g' SerialPrograms/Source/CommonFramework/Globals.cpp SerialPrograms/Source/ClaudeGG/Assistant/Assistant_SelfTest.cpp SerialPrograms/Source/ClaudeGG/ClaudeGG_SelfTest.cpp README.md SECURITY.md
```

Check `Globals.cpp` afterwards: `PROJECT_HOME_URL` ends in `/tree/main` and `PROJECT_HOME_TEXT` is `github.com/<owner>/<repo>`. The self-tests have the repository's name in their made-up data as well (`TEST_REPOSITORY` in `Assistant_SelfTest.cpp`, `PROJECT_URL` in `ClaudeGG_SelfTest.cpp`): change it there too, or the interface test fails, because Claude's panel does not find its repository in the made-up GitHub.

## 3. Settings of the repository

### Actions (Settings → Actions → General)

| Setting | Value | Why |
|---|---|---|
| Actions permissions | Allow all actions and reusable workflows, **or** "Allow owner, and select non-owner actions" with: `actions/*`, `jurplel/install-qt-action@*`, `hendrikmuhs/ccache-action@*` | The workflow uses these three owners' actions, each pinned by its commit. |
| Workflow permissions | **Read repository contents and packages permissions** | The workflow asks for what it needs by itself: `build` reads, `publish` writes (`contents: write`, `actions: read`). The default stays read so that nothing else can write. |
| Allow GitHub Actions to create and approve pull requests | Off | Nothing here needs it. |
| Fork pull request workflows from outside collaborators | **Require approval for all outside collaborators** | A pull request's build runs the code of the pull request, on your runners and your minutes. |
| Artifact and log retention | The default (90 days) or less | The artifact "ClaudeGG-Windows" is about the size of the program. |

If your account or organization limits what a workflow may write to **read-only, with no way for a job to ask for more**, `publish` cannot make a release: allow it, or the builds are made and tested but not published.

### Branches (Settings → Rules → Rulesets, or Branches → Branch protection)

For `main`:

- Require a pull request before merging (Claude's changes arrive that way, from `claude/...`).
- Require status checks to pass: **`build`** (the job of the workflow "Claude GG - Windows build"; it can be picked only after it has run once). This is what keeps a change that does not compile or does not start from reaching the branch the releases are made from.
- Block force pushes and deletion.
- Do not require an approving review if you are the only one who works on it (you cannot approve your own pull request); add it when there are two of you.

Do not add a rule that stops the workflow from pushing tags: `publish` makes the tag of the release (`v0.1.0.N`) with its `GITHUB_TOKEN`.

### General (Settings → General)

- Features: Issues on. Wikis, Projects and Discussions off unless you use them. (There is no GitHub Pages site.)
- Pull requests: allow squash merging (a tidy history for Claude's pull requests) and **Automatically delete head branches** (the `claude/...` branches go away after a merge).
- About (the gear at the right of the repository's front page): a description ("Game automation for any console, starting with the Nintendo Switch. Run programs, or build and fix them with Claude."), the topics (`game-automation`, `automation`, `consoles`, `nintendo-switch`, `pokemon`, `qt`), no website.

### Code security (Settings → Advanced Security, or Code security and analysis)

- **Dependency graph**, **Dependabot alerts** and **Dependabot security updates**: on. [`.github/dependabot.yml`](.github/dependabot.yml) already asks for a weekly update of the actions in the workflows; because they are pinned by commit, a pull request of Dependabot changes the commit and the comment with the version, and the pull request is built as any other.
- **Secret scanning** and **push protection**: on (free for a public repository). They stop a Claude key or a GitHub token that is pasted into a file from being pushed.
- **Private vulnerability reporting**: on, and say so in [SECURITY.md](SECURITY.md) ("Reporting" says to open an issue; a security hole should not be reported in the open).

## 4. The token that Claude's panel uses

The panel needs two things from you, and neither is stored in the repository: your own **Claude API key**, and a **fine-grained personal access token** for this one repository (github.com/settings/personal-access-tokens/new): "Only select repositories" → this repository; permissions **Contents: Read and write** and **Actions: Read-only**; nothing else; an expiry (90 days). The program keeps both encrypted with your Windows account. The full explanation is in [ASSISTANT.md](SerialPrograms/Source/ClaudeGG/ASSISTANT.md).

The token can write to every branch the repository's rules let it; the rule of section 3 (pull request, status check) is what keeps a change of Claude's off `main` until you merge it. The program itself only commits to branches named `claude/...`.

## 5. The workflows of Pokémon Automation

Pokémon Automation's repository has workflows of its own: `cpp-ci-serial-programs-*` and `cpp-ci-python-bindings.yml` (builds on Windows, Linux and macOS, with tests that need the `CommandLineTests` repository) and `tabs.yml` (no tab characters in source). They run on pushes to **`main`** and on every pull request, which here is the branch of Claude GG itself. So in this repository:

- `tabs.yml` is cheap and useful: it stays.
- The `cpp-ci-*` files are **removed**: each would start 20 to 40 minutes of builds on three systems at every push and pull request, and Claude GG's own workflow already builds and tests all of them. (If a merge of Pokémon Automation's `main`, section 9, brings a change to one of them, delete the file again.)

## 6. Releases and versions

- Every push to `main` that passes its tests makes a **pre-release** with the tag `v0.1.0.N`, named "Claude GG - V 0.1.0.N", with `ClaudeGG-Windows.zip` and its SHA-256 in the text. The pictures of the interface test stay in the run's artifact.
- **The version counts up.** The first build is `0.1.0.0`, the next `0.1.0.1`, and so on: N is the highest N of the releases `v0.1.0.N` in the repository, plus one. `SERIES` (`0.1.0`) is a line of the step "Build number" in the workflow; change it there, on purpose, when a new series starts (`0.2.0` starts again at `0.2.0.0`). The program shows it as its build ("Claude GG (build 0.1.0.3)") and compares versions by their four numbers.
  Never delete the newest release: the next build would take its number again. (In a repository that was **imported**, the tags come along but not the releases: a build would get a number whose tag exists already, and its release would be tied to the old commit. That is what happened to build 100 of MajorLOL/arduino-source on 26 November 2026, after its release had been deleted.)
- The builds before the versions are numbered: up to 102 in MajorLOL/arduino-source, and 103 and 104 here (tagged `pocketpilot-build-103` and `claudegg-build-104`). They do not count for the version; delete their releases when you no longer need them.
- A release made by `publish` is a pre-release on purpose: no build is "the latest" until you say so. The update check of the About window reads the list of releases and says whether a higher version exists.
- A pull request's build is named after the pull request (`pr<number>`) and is not published.
- The program is not signed with a certificate, so Windows warns when it starts. The release's text says to compare the SHA-256 first; that is the only guard.

## 7. What a build needs from outside

All of it public; none of it needs a secret:

| What | Where from | Pinned by |
|---|---|---|
| Resources, firmware and scripts | `PokemonAutomation/Packages` | A commit (in the workflow: "move it on purpose"). Also fetched at runtime by the program for firmware and OCR models. |
| Qt 6.10.2 | `jurplel/install-qt-action`, with `aqtinstall` | The commit of both. |
| esptool | Espressif's release | Its version and SHA-256. |
| The compiler's cache | The repository's Actions cache (`claudegg-windows-2025`, 5 GB) | Written by pushes, read by pull requests. |

The first build in a new repository has an empty cache and takes about 35 minutes; after that, 4 to 12 minutes. The Actions cache of a repository is 10 GB in total and old entries are removed by GitHub after 7 days without use: a pause of more than a week means a slow build again.

## 8. The first run, as a list

1. Push `main` (section 1). The workflow starts by itself.
2. Open Actions → "Claude GG - Windows build". The steps "Build", "Interface test", "Intro test", "Tutorial film test", "Language test", "Setup test" and "Installations test" must be green. In the log of the setup test and the interface test, the pictures are in the log as text between `PP-PREVIEW-BEGIN` and `PP-PREVIEW-END` (base64 of a JPEG), to look at without downloading the artifact.
3. Releases: a pre-release "Claude GG - V 0.1.0.0" (or the next version) with the zip.
4. Set the branch rule of section 3 now that the check `build` exists.
5. Download the zip, compare its SHA-256 with the text of the release, unzip, run `ClaudeGG.exe`.
6. Open Settings → Claude in the program, enter the key and the token (section 4), and ask a question about a program.

## 9. Keeping up with Pokémon Automation

```
git remote add upstream https://github.com/PokemonAutomation/Arduino-Source.git
git fetch upstream
git checkout -b merge-upstream main
git merge upstream/main
```

Resolve the conflicts (they are in the few files of [CHANGES.md](CHANGES.md), section 9), push `merge-upstream`, and open a pull request into `main`: its build and tests say whether the merge works before it is on the branch. Look at the pictures of the interface test. New source files of the merge are in their `SourceFiles.cmake`; new programs get a line in the panel list that the new interface reads.

## 10. Licenses and what to say

- The source is MIT (Pokémon Automation's license file stays, with its Copyright line; add yours below it, not instead). [`SerialPrograms/Source/ClaudeGG/Licenses/README.txt`](SerialPrograms/Source/ClaudeGG/Licenses/README.txt) lists the typefaces and the other licenses that come along.
- The builds bring Pokémon Automation's precompiled libraries and resources (`Packages`), which that project gives **for non-commercial use only**: the readme and every release say to use the builds for non-commercial purposes. Keep that sentence.
- The readme says that this is not made, endorsed or supported by Nintendo, Game Freak, Creatures, The Pokémon Company, Anthropic or the Pokémon Automation project, and that questions go to this repository's issues, not to theirs. Keep that too.
