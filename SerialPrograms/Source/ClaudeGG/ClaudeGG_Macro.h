/*  ClaudeGG Macro
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The program "Macro" in the list of every console that has no programs of
 *  its own (the PlayStations, the Xboxes, the retro consoles) and in Other
 *  Games: record what you press, save it under a name, and play it back as
 *  often as you like.
 *
 *    - Record: what you press on the keyboard, or on a controller plugged
 *      into the computer, while the program runs goes to the console as
 *      always, and is written down with its timing (the input sniffer of
 *      Pokemon Automation's Record Keyboard Controller). Stop ends the
 *      recording, or a time limit does. It is saved in
 *      UserSettings/Macros/<name>.json, in the format of Record Keyboard
 *      Controller, so that program's files play here too.
 *    - Play: the steps of a macro, as often as asked (0: until Stop), with a
 *      pause between two rounds and a speed.
 *    - Play the list: a list of steps typed in by hand (the table of Turbo
 *      Macro, with the names of the Switch).
 *    - Show: the steps of a macro in the log, by the names of the console's
 *      own controller (CROSS on a PlayStation, A on an Xbox).
 *    - Save the goal: the screen as it is now becomes the macro's goal
 *      picture (UserSettings/Macros/<name>.png). Playing can then stop as
 *      soon as the screen looks like it, in the middle of a round too: the
 *      video is looked at every 50 ms while the steps play, and what is
 *      still to come is cancelled (the small picture of Claude Plays,
 *      ClaudePlays_AnyGame.h, screen_thumb()).
 *
 *  For the reaction time: the steps go to the board ahead of time, and the
 *  board holds each for its time itself, so there is no wait for the
 *  computer between two steps. Steps are not written to the log while they
 *  play.
 *
 *  The iPhone (a board that plays a keyboard) records and plays its keys
 *  (ClaudeGG_KeyboardState.h); the list of steps is for a Switch pad only.
 *  Everything typed while it records is in the file: no passwords then.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_Macro_H
#define PokemonAutomation_ClaudeGG_Macro_H

#include <chrono>
#include <functional>
#include <mutex>
#include <string>
#include <vector>
#include "Common/Cpp/Json/JsonValue.h"
#include "Common/Cpp/Options/BooleanCheckBoxOption.h"
#include "Common/Cpp/Options/EnumDropdownOption.h"
#include "Common/Cpp/Options/SimpleIntegerOption.h"
#include "Common/Cpp/Options/StaticTextOption.h"
#include "Common/Cpp/Options/StringOption.h"
#include "Common/Cpp/TestRunners/UnitTestDatabase.h"
#include "ControllerInput/Keyboard/KeyboardHidButtons.h"
#include "CommonFramework/Panels/PanelTools.h"
#include "Controllers/ControllerStateTable.h"
#include "NintendoSwitch/NintendoSwitch_SingleSwitchProgram.h"
#include "ClaudePlays/ClaudePlays_Games.h"

namespace PokemonAutomation{

class JsonObject;

namespace ClaudeGG{


//  Adds the section "Macro" with the program to the list of a game.
void add_macro(std::vector<PanelEntry>& list, ClaudePlays::GameId game);

//  The name of a macro as a file name: letters, digits, spaces, "-" and "_"
//  stay, anything else becomes "_". Empty when nothing is left.
std::string macro_file_name(const std::string& name);
//  Where a macro is kept: "<settings>/Macros/<name>.json".
std::string macro_path(const std::string& name);

//  A step of a macro by the names of the pad: "CROSS + UP, 120 ms",
//  "left stick up-right, 300 ms", "nothing, 50 ms".
std::string describe_step(ClaudePlays::PadKind pad, const JsonObject& step);
//  The goal picture of a macro: "<settings>/Macros/<name>.png".
std::string macro_goal_path(const std::string& name);

//  The name of a key of a keyboard: "A", "ENTER", "LEFT_SHIFT". A code
//  without a name: "0x87".
std::string keyboard_key_name(KeyboardKey key);

//  The time a step is held at a speed in percent (100: as recorded, 200:
//  twice as fast). At least 1 ms when it was more than 0.
std::chrono::milliseconds scaled_ms(uint64_t ms, uint32_t speed_percent);

void add_tests_Macro(UnitTestDatabase& database);



class Macro_Descriptor : public NintendoSwitch::SingleSwitchProgramDescriptor{
public:
    explicit Macro_Descriptor(ClaudePlays::GameId game);

    struct Stats;
    virtual std::unique_ptr<StatsTracker> make_stats() const override;
    virtual std::unique_ptr<GameConsole::ConsoleProgramInstance> make_instance(
        GameConsole::ConsoleSystemSession& system
    ) const override;

private:
    const ClaudePlays::GameId m_game;
};


class Macro
    : public NintendoSwitch::SingleSwitchProgramInstance
    , public AbstractController::InputSniffer
{
public:
    explicit Macro(ClaudePlays::GameId game);
    ~Macro();

    virtual void program(
        NintendoSwitch::SingleSwitchProgramEnvironment& env, CancellableScope& scope
    ) override;
    //  Whatever is on the screen: the console may have black borders.
    virtual void start_program_border_check(
        VideoStream& stream,
        FeedbackType feedback_type
    ) override{}

    enum class Mode{
        RECORD,
        PLAY,
        PLAY_LIST,
        SHOW,
        SAVE_GOAL,
    };
    enum class Until{
        ROUNDS,
        GOAL,
    };

private:
    virtual void on_command_input(WallClock timestamp, const ControllerState& state) override;

    void record(NintendoSwitch::SingleSwitchProgramEnvironment& env, CancellableScope& scope);
    void play(NintendoSwitch::SingleSwitchProgramEnvironment& env, CancellableScope& scope);
    void play_list(NintendoSwitch::SingleSwitchProgramEnvironment& env, CancellableScope& scope);
    void show(NintendoSwitch::SingleSwitchProgramEnvironment& env);
    void save_goal(NintendoSwitch::SingleSwitchProgramEnvironment& env);

    //  Runs "rounds" rounds of "one_round" with the pause between them, and
    //  stops early when the goal is seen (UNTIL).
    void play_rounds(
        NintendoSwitch::SingleSwitchProgramEnvironment& env, CancellableScope& scope,
        const std::function<uint64_t(AbstractControllerContext& context)>& one_round
    );

    //  What was recorded, as a macro: the file's contents.
    JsonValue recording_to_json(ControllerClass controller_class);

private:
    const ClaudePlays::GameId m_game;

    StaticTextOption HOW_TO;
    StaticTextOption BUTTON_NAMES;
    EnumDropdownOption<Mode> MODE;
    StringOption NAME;
    BooleanCheckBoxOption OVERWRITE;
    SimpleIntegerOption<uint32_t> RECORD_SECONDS;
    SimpleIntegerOption<uint32_t> LOOPS;
    SimpleIntegerOption<uint32_t> PAUSE_MS;
    SimpleIntegerOption<uint32_t> SPEED;
    EnumDropdownOption<Until> UNTIL;
    SimpleIntegerOption<uint32_t> GOAL_DIFFERENCE;
    ControllerCommandTables LIST;

    struct Snapshot{
        WallClock time;
        JsonValue state;
    };
    std::mutex m_lock;
    std::vector<Snapshot> m_history;
};



}
}
#endif
