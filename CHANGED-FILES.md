# Claude GG: the files that differ from Pokémon Automation

Every file that was added (A), changed (M) or removed (D) compared with Pokémon Automation's Arduino-Source at commit `743ac0d225d1d7a756d4b861e901c0fc4217eaee` ("run distortion augmentation on test UI (#1949)", `main` of 21 November 2026), the base of this code; as of build 102. 270 added, 120 changed, 0 removed, 390 in all. The reasons are in [CHANGES.md](CHANGES.md). The lines of each change: `git remote add upstream https://github.com/PokemonAutomation/Arduino-Source.git`, `git fetch upstream`, then `git diff 743ac0d225d1d7a756d4b861e901c0fc4217eaee HEAD`.

| Where | Added | Changed | Removed |
|---|---|---|---|
| `(top folder)` | 4 | 2 | 0 |
| `.github/workflows` | 1 | 1 | 0 |
| `Common/Cpp` | 2 | 8 | 0 |
| `Common/Qt` | 0 | 2 | 0 |
| `IconResource` | 3 | 6 | 0 |
| `SerialPrograms (build files)` | 0 | 1 | 0 |
| `SerialPrograms/Scripts` | 76 | 0 | 0 |
| `SerialPrograms/Source/CommonFramework` | 2 | 37 | 0 |
| `SerialPrograms/Source/CommonTools` | 0 | 3 | 0 |
| `SerialPrograms/Source/ComputerPrograms` | 0 | 1 | 0 |
| `SerialPrograms/Source/Controllers` | 0 | 2 | 0 |
| `SerialPrograms/Source/GameConsole` | 0 | 4 | 0 |
| `SerialPrograms/Source/Integrations` | 0 | 2 | 0 |
| `SerialPrograms/Source/ML` | 0 | 1 | 0 |
| `SerialPrograms/Source/NintendoSwitch` | 0 | 2 | 0 |
| `SerialPrograms/Source/PanelLists.cpp` | 0 | 1 | 0 |
| `SerialPrograms/Source/PanelLists.h` | 0 | 1 | 0 |
| `SerialPrograms/Source/PocketPilot` | 118 | 0 | 0 |
| `SerialPrograms/Source/PokemonBDSP` | 0 | 2 | 0 |
| `SerialPrograms/Source/Tests` | 0 | 1 | 0 |
| `SerialPrograms/Source/VideoGames/PokemonFRLG` | 64 | 23 | 0 |
| `SerialPrograms/Source/VideoGames/PokemonHome` | 0 | 1 | 0 |
| `SerialPrograms/Source/VideoGames/PokemonLA` | 0 | 1 | 0 |
| `SerialPrograms/Source/VideoGames/PokemonLGPE` | 0 | 3 | 0 |
| `SerialPrograms/Source/VideoGames/PokemonLZA` | 0 | 2 | 0 |
| `SerialPrograms/Source/VideoGames/PokemonPokopia` | 0 | 1 | 0 |
| `SerialPrograms/Source/VideoGames/PokemonRSE` | 0 | 1 | 0 |
| `SerialPrograms/Source/VideoGames/PokemonSV` | 0 | 6 | 0 |
| `SerialPrograms/Source/VideoGames/PokemonSwSh` | 0 | 3 | 0 |
| `SerialPrograms/Source/VideoGames/ZeldaTotK` | 0 | 1 | 0 |
| `SerialPrograms/cmake` | 0 | 1 | 0 |

## `(top folder)`

- M `.gitignore`
- A `CHANGES.md`
- A `GITHUB-SETUP.md`
- M `README.md`
- A `ROADMAP.md`
- A `SECURITY.md`

## `.github/workflows`

- M `.github/workflows/cpp-ci-serial-programs-base.yml`
- A `.github/workflows/pocketpilot-windows.yml`

## `Common/Cpp`

- M `Common/Cpp/ColoredText.cpp`
- M `Common/Cpp/ColoredText.h`
- M `Common/Cpp/Concurrency/PeriodicRunner.cpp`
- A `Common/Cpp/Cryptography/SecretSeal.cpp`
- A `Common/Cpp/Cryptography/SecretSeal.h`
- M `Common/Cpp/ExpressionEvaluator.cpp`
- M `Common/Cpp/ListenerSet.h`
- M `Common/Cpp/Logging/LastLogTracker.cpp`
- M `Common/Cpp/Options/StringOption.cpp`
- M `Common/Cpp/Sockets/Sockets_Tests.cpp`

## `Common/Qt`

- M `Common/Qt/Options/FloatingPointWidget.cpp`
- M `Common/Qt/Options/SimpleIntegerWidget.cpp`

## `IconResource`

- M `IconResource/IconResource.rc`
- M `IconResource/SerialPrograms.appdata.xml`
- M `IconResource/SerialPrograms.desktop`
- M `IconResource/SerialPrograms.png`
- A `IconResource/claudegg-logo.png`
- A `IconResource/claudegg.ico`
- A `IconResource/claudegg.png`
- M `IconResource/icon.icns`
- M `IconResource/icon.ico`

## `SerialPrograms (build files)`

- M `SerialPrograms/CMakeLists.txt`

## `SerialPrograms/Scripts`

- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/.gitignore`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/README.md`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/battle_sim.py`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/dex_availability.py`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/dex_report.py`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/engine.py`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/frlg_data.py`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/gen_dex.py`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/generate.py`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/START-POSITIONS.md`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/CeladonCity_48_12_down.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/CeladonCity_Gym_6_5_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/CeladonCity_PokemonCenter_1F_7_4_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/CeruleanCave_B1F_7_13_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/CeruleanCity_22_20_down.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/CeruleanCity_Gym_9_6_left.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/CeruleanCity_PokemonCenter_1F_7_4_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/CinnabarIsland_14_12_down.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/CinnabarIsland_Gym_5_5_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/CinnabarIsland_PokemonCenter_1F_7_4_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/FiveIsland_PokemonCenter_1F_7_4_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/FourIsland_IcefallCave_1F_13_16_left.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/FourIsland_PokemonCenter_1F_7_4_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/FuchsiaCity_25_32_down.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/FuchsiaCity_Gym_7_12_down.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/FuchsiaCity_PokemonCenter_1F_7_4_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/IndigoPlateau_Exterior_11_7_down.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/IndigoPlateau_PokemonCenter_1F_0_9_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/IndigoPlateau_PokemonCenter_1F_13_12_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/LavenderTown_6_6_down.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/LavenderTown_PokemonCenter_1F_7_4_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/MtEmber_Exterior_42_41_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/MtEmber_Summit_9_7_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/OneIsland_PokemonCenter_1F_5_4_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/PalletTown_6_8_down.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/PalletTown_PlayersHouse_2F_6_6_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/PalletTown_ProfessorOaksLab_10_5_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/PalletTown_ProfessorOaksLab_6_4_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/PalletTown_ProfessorOaksLab_7_8_down.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/PewterCity_Gym_6_6_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/PewterCity_PokemonCenter_1F_7_4_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/PokemonLeague_AgathasRoom_6_6_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/PokemonLeague_BrunosRoom_6_6_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/PokemonLeague_ChampionsRoom_6_19_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/PokemonLeague_LancesRoom_6_9_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/PokemonLeague_LoreleisRoom_6_6_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/PowerPlant_5_10_down.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/Route10_13_21_down.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/Route10_PokemonCenter_1F_7_4_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/Route16_House_4_3_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/Route23_5_35_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/Route4_12_6_down.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/Route4_PokemonCenter_1F_7_4_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/SaffronCity_Gym_14_12_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/SaffronCity_PokemonCenter_1F_7_4_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/SeafoamIslands_B4F_9_3_left.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/SeafoamIslands_B4F_9_3_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/SevenIsland_PokemonCenter_1F_7_4_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/SixIsland_PokemonCenter_1F_7_4_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/ThreeIsland_PokemonCenter_1F_7_4_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/TwoIsland_PokemonCenter_1F_7_4_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/VermilionCity_Gym_4_2_right.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/VermilionCity_PokemonCenter_1F_7_4_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/ViridianCity_26_27_down.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/ViridianCity_Gym_2_3_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/ViridianCity_Mart_4_3_left.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/guide/images/ViridianCity_PokemonCenter_1F_7_4_up.png`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/league_again_sim.py`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/log_video_check.py`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/move_audit.py`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/nugget_bridge_walk.py`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/render.py`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/start_positions.py`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/story.py`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/story_spec.py`
- A `SerialPrograms/Scripts/PokemonFRLG/AutoStory/team_sim.py`

## `SerialPrograms/Source/CommonFramework`

- M `SerialPrograms/Source/CommonFramework/AudioPipeline/AudioOption.cpp`
- M `SerialPrograms/Source/CommonFramework/AudioPipeline/IO/AudioFileLoader.cpp`
- M `SerialPrograms/Source/CommonFramework/GlobalAutoPaths.cpp`
- M `SerialPrograms/Source/CommonFramework/GlobalAutoPaths.h`
- M `SerialPrograms/Source/CommonFramework/GlobalSettingsPanel.cpp`
- M `SerialPrograms/Source/CommonFramework/GlobalSettingsPanel.h`
- M `SerialPrograms/Source/CommonFramework/Globals.cpp`
- M `SerialPrograms/Source/CommonFramework/Globals.h`
- M `SerialPrograms/Source/CommonFramework/Logging/LoggerWindow.cpp`
- M `SerialPrograms/Source/CommonFramework/Logging/LoggerWindow.h`
- M `SerialPrograms/Source/CommonFramework/Main.cpp`
- M `SerialPrograms/Source/CommonFramework/Notifications/ProgramNotifications.cpp`
- M `SerialPrograms/Source/CommonFramework/Options/Environment/ThemeSelectorOption.cpp`
- M `SerialPrograms/Source/CommonFramework/Options/Environment/ThemeSelectorOption.h`
- M `SerialPrograms/Source/CommonFramework/Options/WallpaperOption.cpp`
- M `SerialPrograms/Source/CommonFramework/Panels/OptionsPanelSession.h`
- M `SerialPrograms/Source/CommonFramework/Panels/PanelDescriptor.cpp`
- M `SerialPrograms/Source/CommonFramework/Panels/PanelDescriptor.h`
- M `SerialPrograms/Source/CommonFramework/Panels/PanelList.cpp`
- M `SerialPrograms/Source/CommonFramework/Panels/PanelList.h`
- M `SerialPrograms/Source/CommonFramework/Panels/PanelSession.h`
- M `SerialPrograms/Source/CommonFramework/Panels/UI/OptionsPanelWidget.cpp`
- M `SerialPrograms/Source/CommonFramework/Panels/UI/PanelElements.cpp`
- M `SerialPrograms/Source/CommonFramework/Panels/UI/PanelListWidget.cpp`
- M `SerialPrograms/Source/CommonFramework/Panels/UI/PanelListWidget.h`
- M `SerialPrograms/Source/CommonFramework/PersistentSettings.cpp`
- M `SerialPrograms/Source/CommonFramework/PersistentSettings.h`
- M `SerialPrograms/Source/CommonFramework/Recording/StreamHistoryTracker_SaveFrames.cpp`
- M `SerialPrograms/Source/CommonFramework/Recording/StreamHistoryTracker_SaveFrames.h`
- M `SerialPrograms/Source/CommonFramework/StaticGlobals.cpp`
- M `SerialPrograms/Source/CommonFramework/VideoPipeline/Backends/SnapshotManager.cpp`
- M `SerialPrograms/Source/CommonFramework/VideoPipeline/Backends/SnapshotManager.h`
- A `SerialPrograms/Source/CommonFramework/VideoPipeline/Backends/VideoFrameConversion.cpp`
- A `SerialPrograms/Source/CommonFramework/VideoPipeline/Backends/VideoFrameConversion.h`
- M `SerialPrograms/Source/CommonFramework/VideoPipeline/UI/VideoSourceSelectorWidget.cpp`
- M `SerialPrograms/Source/CommonFramework/VideoPipeline/VideoSession.cpp`
- M `SerialPrograms/Source/CommonFramework/VideoPipeline/VideoSession.h`
- M `SerialPrograms/Source/CommonFramework/Windows/MainWindow.cpp`
- M `SerialPrograms/Source/CommonFramework/Windows/MainWindow.h`

## `SerialPrograms/Source/CommonTools`

- M `SerialPrograms/Source/CommonTools/Async/InferenceSession.cpp`
- M `SerialPrograms/Source/CommonTools/Audio/AudioPerSpectrumDetectorBase.cpp`
- M `SerialPrograms/Source/CommonTools/Options/QtWidgets/StringSelectWidget.cpp`

## `SerialPrograms/Source/ComputerPrograms`

- M `SerialPrograms/Source/ComputerPrograms/Framework/ComputerProgramSession.h`

## `SerialPrograms/Source/Controllers`

- M `SerialPrograms/Source/Controllers/ControllerSession.cpp`
- M `SerialPrograms/Source/Controllers/ControllerStateTable.cpp`

## `SerialPrograms/Source/GameConsole`

- M `SerialPrograms/Source/GameConsole/Framework/ConsolePanelSession.h`
- M `SerialPrograms/Source/GameConsole/Framework/ConsoleProgramSession.h`
- M `SerialPrograms/Source/GameConsole/Framework/MultiConsolePanelSession.h`
- M `SerialPrograms/Source/GameConsole/Framework/MultiConsoleProgramSession.h`

## `SerialPrograms/Source/Integrations`

- M `SerialPrograms/Source/Integrations/DiscordSocial/DiscordSocial.cpp`
- M `SerialPrograms/Source/Integrations/DppIntegration/DppCommandHandler.cpp`

## `SerialPrograms/Source/ML`

- M `SerialPrograms/Source/ML/Models/ML_ONNXRuntimeHelpers.cpp`

## `SerialPrograms/Source/NintendoSwitch`

- M `SerialPrograms/Source/NintendoSwitch/Programs/NintendoSwitch_TurboMacro.cpp`
- M `SerialPrograms/Source/NintendoSwitch/Programs/NintendoSwitch_TurboMacro.h`

## `SerialPrograms/Source/PanelLists.cpp`

- M `SerialPrograms/Source/PanelLists.cpp`

## `SerialPrograms/Source/PanelLists.h`

- M `SerialPrograms/Source/PanelLists.h`

## `SerialPrograms/Source/PocketPilot`

- A `SerialPrograms/Source/PocketPilot/ASSISTANT.md`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_Agent.cpp`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_Agent.h`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_ChatTools.cpp`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_Claude.cpp`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_Claude.h`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_GitHub.cpp`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_GitHub.h`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_Http.cpp`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_Http.h`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_Panel.cpp`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_Panel.h`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_Play.cpp`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_Play.h`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_SelfTest.cpp`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_SelfTest.h`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_Service.cpp`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_Service.h`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_Settings.cpp`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_Settings.h`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_Tools.cpp`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_Tools.h`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_Workspace.cpp`
- A `SerialPrograms/Source/PocketPilot/Assistant/Assistant_Workspace.h`
- A `SerialPrograms/Source/PocketPilot/ClaudePlays/ClaudePlays_AnyGame.cpp`
- A `SerialPrograms/Source/PocketPilot/ClaudePlays/ClaudePlays_AnyGame.h`
- A `SerialPrograms/Source/PocketPilot/ClaudePlays/ClaudePlays_Engine.cpp`
- A `SerialPrograms/Source/PocketPilot/ClaudePlays/ClaudePlays_Engine.h`
- A `SerialPrograms/Source/PocketPilot/ClaudePlays/ClaudePlays_GameCard.cpp`
- A `SerialPrograms/Source/PocketPilot/ClaudePlays/ClaudePlays_GameCard.h`
- A `SerialPrograms/Source/PocketPilot/ClaudePlays/ClaudePlays_Games.cpp`
- A `SerialPrograms/Source/PocketPilot/ClaudePlays/ClaudePlays_Games.h`
- A `SerialPrograms/Source/PocketPilot/ClaudePlays/ClaudePlays_Program.cpp`
- A `SerialPrograms/Source/PocketPilot/ClaudePlays/ClaudePlays_Program.h`
- A `SerialPrograms/Source/PocketPilot/FIXES.md`
- A `SerialPrograms/Source/PocketPilot/ISSUES.md`
- A `SerialPrograms/Source/PocketPilot/Licenses/README.txt`
- A `SerialPrograms/Source/PocketPilot/OTHERS.md`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_About.cpp`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_About.h`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_Firmware.cpp`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_Firmware.h`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_Home.cpp`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_Home.h`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_InstancePaths.cpp`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_InstancePaths.h`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_Instances.cpp`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_Instances.h`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_Intro.cpp`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_Intro.h`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_Language.cpp`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_Language.h`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_Logo.cpp`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_Logo.h`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_OldSettings.cpp`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_OldSettings.h`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_ProgramList.cpp`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_ProgramList.h`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_Scrub.cpp`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_Scrub.h`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_SelfTest.cpp`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_SelfTest.h`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_SettingsSearch.cpp`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_SettingsSearch.h`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_Setup.cpp`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_Setup.h`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_ShinyClip.cpp`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_ShinyClip.h`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_Theme.cpp`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_Theme.h`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_Update.cpp`
- A `SerialPrograms/Source/PocketPilot/PocketPilot_Update.h`
- A `SerialPrograms/Source/PocketPilot/Resources/Jersey20-OFL.txt`
- A `SerialPrograms/Source/PocketPilot/Resources/Jersey20-Regular.ttf`
- A `SerialPrograms/Source/PocketPilot/Resources/arrow-dark.png`
- A `SerialPrograms/Source/PocketPilot/Resources/arrow-dark@2x.png`
- A `SerialPrograms/Source/PocketPilot/Resources/arrow-gray.png`
- A `SerialPrograms/Source/PocketPilot/Resources/arrow-gray@2x.png`
- A `SerialPrograms/Source/PocketPilot/Resources/arrow-light.png`
- A `SerialPrograms/Source/PocketPilot/Resources/arrow-light@2x.png`
- A `SerialPrograms/Source/PocketPilot/Resources/check-dark.png`
- A `SerialPrograms/Source/PocketPilot/Resources/check-dark@2x.png`
- A `SerialPrograms/Source/PocketPilot/Resources/check-light.png`
- A `SerialPrograms/Source/PocketPilot/Resources/check-light@2x.png`
- A `SerialPrograms/Source/PocketPilot/Resources/intro.mp4`
- A `SerialPrograms/Source/PocketPilot/Resources/lang/de.json`
- A `SerialPrograms/Source/PocketPilot/Resources/lang/es.json`
- A `SerialPrograms/Source/PocketPilot/Resources/lang/fr.json`
- A `SerialPrograms/Source/PocketPilot/Resources/lang/nl.json`
- A `SerialPrograms/Source/PocketPilot/Resources/pocketpilot.qrc`
- A `SerialPrograms/Source/PocketPilot/Resources/setup/Fredoka-Bold.ttf`
- A `SerialPrograms/Source/PocketPilot/Resources/setup/Fredoka-Medium.ttf`
- A `SerialPrograms/Source/PocketPilot/Resources/setup/Fredoka-OFL.txt`
- A `SerialPrograms/Source/PocketPilot/Resources/setup/Fredoka-SemiBold.ttf`
- A `SerialPrograms/Source/PocketPilot/Resources/setup/Newsreader-OFL.txt`
- A `SerialPrograms/Source/PocketPilot/Resources/setup/Newsreader16pt-Regular.ttf`
- A `SerialPrograms/Source/PocketPilot/Resources/setup/computer.png`
- A `SerialPrograms/Source/PocketPilot/Resources/setup/esp32-big.png`
- A `SerialPrograms/Source/PocketPilot/Resources/setup/esp32s3-big.png`
- A `SerialPrograms/Source/PocketPilot/Resources/setup/glyph-esp32.png`
- A `SerialPrograms/Source/PocketPilot/Resources/setup/glyph-esp32s3.png`
- A `SerialPrograms/Source/PocketPilot/Resources/setup/glyph-leonardo.png`
- A `SerialPrograms/Source/PocketPilot/Resources/setup/glyph-pico.png`
- A `SerialPrograms/Source/PocketPilot/Resources/setup/glyph-pico2.png`
- A `SerialPrograms/Source/PocketPilot/Resources/setup/glyph-promicro.png`
- A `SerialPrograms/Source/PocketPilot/Resources/setup/glyph-teensy.png`
- A `SerialPrograms/Source/PocketPilot/Resources/setup/glyph-uno.png`
- A `SerialPrograms/Source/PocketPilot/Resources/setup/pico-big.png`
- A `SerialPrograms/Source/PocketPilot/Resources/setup/setup-bg.png`
- A `SerialPrograms/Source/PocketPilot/Resources/setup/switch-gg.png`
- A `SerialPrograms/Source/PocketPilot/Resources/setup/switch.png`
- A `SerialPrograms/Source/PocketPilot/Resources/shell.qss`
- A `SerialPrograms/Source/PocketPilot/Resources/tutorial-esp32.mp4`
- A `SerialPrograms/Source/PocketPilot/Resources/tutorial-esp32s3.mp4`
- A `SerialPrograms/Source/PocketPilot/Resources/tutorial-pico.mp4`
- A `SerialPrograms/Source/PocketPilot/Resources/widgets.qss`
- A `SerialPrograms/Source/PocketPilot/Tools/TutorialFilms.cpp`
- A `SerialPrograms/Source/PocketPilot/Tools/tutorial_audio.py`

## `SerialPrograms/Source/PokemonBDSP`

- M `SerialPrograms/Source/PokemonBDSP/Inference/ShinyDetection/PokemonBDSP_ShinyEncounterDetector.cpp`
- M `SerialPrograms/Source/PokemonBDSP/PokemonBDSP_Panels.cpp`

## `SerialPrograms/Source/Tests`

- M `SerialPrograms/Source/Tests/CommandLineTests.h`

## `SerialPrograms/Source/VideoGames/PokemonFRLG`

- M `SerialPrograms/Source/VideoGames/PokemonFRLG/Inference/Menus/PokemonFRLG_SummaryDetector.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/Inference/Menus/PokemonFRLG_SummaryDetector.h`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/Inference/PokemonFRLG_BallReader.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/Inference/PokemonFRLG_BallReader.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Inference/PokemonFRLG_NamingScreenText.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Inference/PokemonFRLG_NamingScreenText.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Inference/PokemonFRLG_NamingScreenText_Tests.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Inference/PokemonFRLG_NamingScreenText_Tests.h`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/Inference/PokemonFRLG_PokemonSpriteReader.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/Inference/PokemonFRLG_ShinySymbolDetector.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/Inference/PokemonFRLG_StatsReader.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Inference/PokemonFRLG_TypeReader.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Inference/PokemonFRLG_TypeReader.h`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/Inference/PokemonFRLG_WildEncounterReader.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/Inference/PokemonFRLG_WildEncounterReader.h`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/PokemonFRLG_Navigation.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/PokemonFRLG_Navigation.h`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/PokemonFRLG_Panels.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/PokemonFRLG_Tests.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStory.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStory.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryActions.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryActions.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryBattle.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryBattle.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryBoxScan.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryBoxes.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryBump.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryCoins.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryCollection.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryCollection.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryCollectionText.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryData.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryDex.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryDexCollection.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryFerryTalk.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryFishing.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryMemory.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryMemory.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryMemoryTest.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryNameMark.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryNameMark.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryNewGame.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryNewGame.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryPlaceList.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStorySafari.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryScript.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryScroll.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryScroll.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStorySlowSteps.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStorySmallRoom.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryTimes.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryTimes.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryTools.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryTools.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryWalkTracker.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStoryWalkTracker.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/BoxOrganization/PokemonFRLG_BoxNamer.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/BoxOrganization/PokemonFRLG_BoxNamer.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/ClaudePlays/PokemonFRLG_ClaudePlays.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/ClaudePlays/PokemonFRLG_ClaudePlays.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/Farming/PokemonFRLG_LevelTrainer.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/Farming/PokemonFRLG_LevelTrainer.h`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/Farming/PokemonFRLG_NuggetBridgeFarmer.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/Farming/PokemonFRLG_NuggetBridgeFarmer.h`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/Farming/PokemonFRLG_PickupFarmer.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/RngManipulation/PokemonFRLG_RngPlan.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/RngManipulation/PokemonFRLG_RngPlan.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/RngManipulation/PokemonFRLG_RngPlanTestTargets.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/RngManipulation/PokemonFRLG_RngPlanTestTargets.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/RngManipulation/PokemonFRLG_RngPlanTracker.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/RngManipulation/PokemonFRLG_RngPlanTracker.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/RngManipulation/PokemonFRLG_RngPlanTracker_Tests.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/RngManipulation/PokemonFRLG_RngPlanTracker_Tests.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/RngManipulation/PokemonFRLG_RngTargetSearch.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/RngManipulation/PokemonFRLG_RngTargetSearch.h`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/RngManipulation/PokemonFRLG_RngTargetSearch_Tests.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/RngManipulation/PokemonFRLG_RngTargetSearch_Tests.h`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/RngManipulation/PokemonFRLG_SeedsDatabase.h`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/ShinyHunting/PokemonFRLG_GiftReset.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/ShinyHunting/PokemonFRLG_LegendaryReset.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/ShinyHunting/PokemonFRLG_LegendaryRunAway.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/ShinyHunting/PokemonFRLG_PrizeCornerReset.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/ShinyHunting/PokemonFRLG_ShinyHunt-Fishing.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/ShinyHunting/PokemonFRLG_ShinyHunt-Overworld.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/TestPrograms/PokemonFRLG_InputTimingTest.cpp`
- A `SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/TestPrograms/PokemonFRLG_InputTimingTest.h`

## `SerialPrograms/Source/VideoGames/PokemonHome`

- M `SerialPrograms/Source/VideoGames/PokemonHome/PokemonHome_Panels.cpp`

## `SerialPrograms/Source/VideoGames/PokemonLA`

- M `SerialPrograms/Source/VideoGames/PokemonLA/PokemonLA_Panels.cpp`

## `SerialPrograms/Source/VideoGames/PokemonLGPE`

- M `SerialPrograms/Source/VideoGames/PokemonLGPE/PokemonLGPE_Panels.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonLGPE/Programs/ShinyHunting/PokemonLGPE_AlolanTrade.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonLGPE/Programs/ShinyHunting/PokemonLGPE_FossilRevival.cpp`

## `SerialPrograms/Source/VideoGames/PokemonLZA`

- M `SerialPrograms/Source/VideoGames/PokemonLZA/PokemonLZA_Panels.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonLZA/Programs/PokemonLZA_FastTravelNavigation.cpp`

## `SerialPrograms/Source/VideoGames/PokemonPokopia`

- M `SerialPrograms/Source/VideoGames/PokemonPokopia/PokemonPokopia_Panels.cpp`

## `SerialPrograms/Source/VideoGames/PokemonRSE`

- M `SerialPrograms/Source/VideoGames/PokemonRSE/PokemonRSE_Panels.cpp`

## `SerialPrograms/Source/VideoGames/PokemonSV`

- M `SerialPrograms/Source/VideoGames/PokemonSV/Inference/Boxes/PokemonSV_BoxDetection.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonSV/Inference/Dialogs/PokemonSV_DialogArrowDetector.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonSV/Options/PokemonSV_SinglesMoveTable.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonSV/Options/PokemonSV_SinglesMoveTable.h`
- M `SerialPrograms/Source/VideoGames/PokemonSV/PokemonSV_Panels.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonSV/Programs/PokemonSV_WorldNavigation.cpp`

## `SerialPrograms/Source/VideoGames/PokemonSwSh`

- M `SerialPrograms/Source/VideoGames/PokemonSwSh/PkmnLib/PokemonSwSh_PkmnLib_Battle.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonSwSh/PokemonSwSh_Panels.cpp`
- M `SerialPrograms/Source/VideoGames/PokemonSwSh/Programs/DateSpamFarmers/PokemonSwSh_DateSpam-PokeJobsFarmer.cpp`

## `SerialPrograms/Source/VideoGames/ZeldaTotK`

- M `SerialPrograms/Source/VideoGames/ZeldaTotK/ZeldaTotK_Panels.cpp`

## `SerialPrograms/cmake`

- M `SerialPrograms/cmake/SourceFiles.cmake`
