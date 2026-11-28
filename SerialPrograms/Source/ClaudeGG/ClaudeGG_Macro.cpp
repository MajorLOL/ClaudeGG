/*  ClaudeGG Macro
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <cmath>
#include <atomic>
#include "Common/Cpp/Exceptions.h"
#include "Common/Cpp/Filesystem/Filesystem.h"
#include "Common/Cpp/Json/JsonArray.h"
#include "Common/Cpp/Json/JsonObject.h"
#include "Common/Cpp/TestRunners/UnitTest.h"
#include "CommonFramework/GlobalAutoPaths.h"
#include "CommonFramework/ProgramStats/StatsTracking.h"
#include "Controllers/ControllerTypeStrings.h"
#include "NintendoSwitch/Controllers/NintendoSwitch_ControllerButtons.h"
#include "NintendoSwitch/Controllers/Procon/NintendoSwitch_ProControllerState.h"
#include "NintendoSwitch/Controllers/Joycon/NintendoSwitch_JoyconState.h"
#include "ClaudePlays/ClaudePlays_AnyGame.h"
#include "ClaudePlays/ClaudePlays_Program.h"
#include "ClaudeGG_Language.h"
#include "ClaudeGG_Macro.h"

namespace PokemonAutomation{
namespace ClaudeGG{

using namespace NintendoSwitch;
using ClaudePlays::GameId;
using ClaudePlays::PadKind;
using ClaudePlays::game_profile;



void add_macro(std::vector<PanelEntry>& list, GameId game){
    if (game_profile(game).pad == PadKind::IPHONE_KEYBOARD){
        return;
    }
    list.emplace_back("---- Macro ----");
    list.emplace_back(std::make_unique<Macro_Descriptor>(game));
}


std::string macro_file_name(const std::string& name){
    std::string out;
    for (char c : name){
        const bool kept =
            (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
            c == ' ' || c == '-' || c == '_';
        out += kept ? c : '_';
    }
    //  No spaces at the ends (Windows drops them), and not only "_".
    size_t first = out.find_first_not_of(' ');
    size_t last = out.find_last_not_of(' ');
    if (first == std::string::npos){
        return "";
    }
    out = out.substr(first, last - first + 1);
    if (out.find_first_not_of('_') == std::string::npos){
        return "";
    }
    return out;
}
std::string macro_path(const std::string& name){
    return SETTINGS_PATH() + "Macros/" + macro_file_name(name) + ".json";
}


std::chrono::milliseconds scaled_ms(uint64_t ms, uint32_t speed_percent){
    if (ms == 0){
        return std::chrono::milliseconds(0);
    }
    if (speed_percent == 0){
        speed_percent = 100;
    }
    const double scaled = std::round((double)ms * 100.0 / speed_percent);
    return std::chrono::milliseconds(scaled < 1 ? 1 : (int64_t)scaled);
}



namespace{


//  The name of a Switch button on the pad, by the tables of Claude Plays.
std::string button_name(PadKind pad, Button button){
    if (pad == PadKind::PRO_CONTROLLER || pad == PadKind::RIGHT_JOYCON){
        return button_to_string(button);
    }
    if (button == BUTTON_HOME){
        return "HOME";
    }
    for (const std::string& name : ClaudePlays::pad_layout(pad).buttons){
        Button found = BUTTON_NONE;
        if (ClaudePlays::button_of_pad(pad, name, found) && found == button){
            return name;
        }
    }
    //  A button the console has no name for: by the Switch's name.
    return "(" + button_to_string(button) + ")";
}

//  "up", "down-left", ...: where a stick or the d-pad points. Empty: in the
//  middle.
std::string direction_of(double x, double y){
    const double threshold = 0.3;
    std::string out;
    if (y > threshold){
        out = "up";
    }else if (y < -threshold){
        out = "down";
    }
    if (x > threshold){
        out += out.empty() ? "right" : "-right";
    }else if (x < -threshold){
        out += out.empty() ? "left" : "-left";
    }
    return out;
}

std::string dpad_words(const std::string& dpad){
    std::string out;
    for (char c : dpad){
        out += c == ' ' ? '-' : (char)std::toupper((unsigned char)c);
    }
    return out;
}

bool read_stick(const JsonObject& step, const char* x_key, const char* y_key, double& x, double& y){
    x = 0;
    y = 0;
    const bool found_x = step.read_float(x, x_key);
    const bool found_y = step.read_float(y, y_key);
    return found_x || found_y;
}

}   //  namespace



std::string describe_step(PadKind pad, const JsonObject& step){
    std::vector<std::string> parts;

    std::string buttons;
    if (step.read_string(buttons, "buttons") && !buttons.empty()){
        const Button held = string_to_button(buttons, " ");
        for (uint32_t bit = 0; bit < 32; bit++){
            const Button one = (Button)((uint32_t)1 << bit);
            if ((held & one) != 0){
                parts.emplace_back(button_name(pad, one));
            }
        }
    }
    std::string dpad;
    if (step.read_string(dpad, "dpad") && !dpad.empty() && dpad != "none"){
        parts.emplace_back(dpad_words(dpad));
    }

    double x, y;
    if (read_stick(step, "lxf", "lyf", x, y)){
        const std::string where = direction_of(x, y);
        if (!where.empty()){
            parts.emplace_back(
                (ClaudePlays::pad_layout(pad).sticks.size() > 1 ? "left stick " : "stick ") + where
            );
        }
    }
    if (read_stick(step, "rxf", "ryf", x, y)){
        const std::string where = direction_of(x, y);
        if (!where.empty()){
            //  BlueRetro makes the right stick the C buttons of a Nintendo 64.
            parts.emplace_back((pad == PadKind::N64_CONTROLLER ? "C buttons " : "right stick ") + where);
        }
    }
    if (read_stick(step, "jxf", "jyf", x, y)){
        const std::string where = direction_of(x, y);
        if (!where.empty()){
            parts.emplace_back("stick " + where);
        }
    }

    std::string out;
    for (const std::string& part : parts){
        out += out.empty() ? part : " + " + part;
    }
    if (out.empty()){
        out = "nothing";
    }

    uint64_t ms = 0;
    if (!step.read_integer(ms, "ms")){
        step.read_integer(ms, "duration_in_ms");
    }
    return out + ", " + std::to_string(ms) + " ms";
}



namespace{

std::string description_of(GameId game){
    const ClaudePlays::GameProfile& profile = game_profile(game);
    return
        "Record what you press on the keyboard or on a controller of the computer, save it under a name and "
        "play it back on " + (profile.title.empty() ? std::string("the console") : profile.title) +
        " as often as you like.";
}

std::string identifier_of(GameId game){
    std::string id = game_profile(game).identifier;
    const std::string suffix = ":ClaudePlays";
    if (id.size() > suffix.size() && id.compare(id.size() - suffix.size(), suffix.size(), suffix) == 0){
        id.resize(id.size() - suffix.size());
    }
    return id + ":Macro";
}

}


Macro_Descriptor::Macro_Descriptor(GameId game)
    : SingleSwitchProgramDescriptor(
        identifier_of(game),
        game_profile(game).category, "Macro",
        "",
        description_of(game),
        PanelQualityStanding::EXPERIMENTAL,
        ProgramControllerClass::StandardController_NoRestrictions,
        FeedbackType::NONE,
        //  You play while it records.
        AllowCommandsWhenRunning::ENABLE_COMMANDS
    )
    , m_game(game)
{}

struct Macro_Descriptor::Stats : public StatsTracker{
    Stats()
        : loops(m_stats["Rounds"])
        , steps(m_stats["Steps"])
    {
        m_display_order.emplace_back("Rounds");
        m_display_order.emplace_back("Steps");
    }

    std::atomic<uint64_t>& loops;
    std::atomic<uint64_t>& steps;
};
std::unique_ptr<StatsTracker> Macro_Descriptor::make_stats() const{
    return std::unique_ptr<StatsTracker>(new Stats());
}
std::unique_ptr<GameConsole::ConsoleProgramInstance> Macro_Descriptor::make_instance(
    GameConsole::ConsoleSystemSession&
) const{
    return std::make_unique<Macro>(m_game);
}



namespace{

//  Which button of the Switch each button of the pad is: for the list, which
//  has the names of the Switch.
std::string button_names_text(GameId game){
    const ClaudePlays::GameProfile& profile = game_profile(game);
    if (profile.pad == PadKind::PRO_CONTROLLER || profile.pad == PadKind::RIGHT_JOYCON){
        return tr_ui(
            "<b>Buttons:</b> the list below and the log use the names of the Switch."
        ).toStdString();
    }
    std::string pairs;
    for (const std::string& name : ClaudePlays::pad_layout(profile.pad).buttons){
        if (name == "UP" || name == "DOWN" || name == "LEFT" || name == "RIGHT"){
            continue;
        }
        Button button = BUTTON_NONE;
        if (!ClaudePlays::button_of_pad(profile.pad, name, button)){
            continue;
        }
        pairs += (pairs.empty() ? "" : ", ") + name + " = " + button_to_string(button);
    }
    std::string text = tr_ui(
        "<b>Buttons of %1:</b> the log shows its own names. In the list below, and on your keyboard or "
        "controller, they have the names of the Switch: %2."
    ).arg(QString::fromStdString(profile.title), QString::fromStdString(pairs)).toStdString();
    if (profile.pad == PadKind::N64_CONTROLLER){
        text += " " + tr_ui("C_UP and C_RIGHT are the right stick.").toStdString();
    }
    return text;
}

}


Macro::Macro(GameId game)
    : m_game(game)
    , HOW_TO(
        "<b>Record</b> what you press on the keyboard, or on a controller plugged into the computer, while "
        "the program runs: it goes to the console as always. Stop ends the recording. "
        "<b>Play</b> sends it to the console again, as often as you like. "
        "<b>Play the list</b> plays steps you type in below. "
        "<b>Show</b> writes the steps of a macro to the log.<br><br>"
        "The steps go to the board ahead of time and the board holds each one for its time itself, so there "
        "is no wait for the computer between two steps. What the keyboard or controller recorded is a few "
        "milliseconds off (about 8 to 15 ms per press): a few long presses repeat better than many short ones."
    )
    , BUTTON_NAMES(button_names_text(game))
    , MODE(
        "<b>What to do:</b>",
        {
            {Mode::RECORD,      "record",       "Record"},
            {Mode::PLAY,        "play",         "Play"},
            {Mode::PLAY_LIST,   "play-list",    "Play the list"},
            {Mode::SHOW,        "show",         "Show the steps in the log"},
        },
        LockMode::LOCK_WHILE_RUNNING,
        Mode::RECORD
    )
    , NAME(
        false,
        "<b>Name of the macro:</b><br>It is kept in the folder UserSettings/Macros.",
        LockMode::LOCK_WHILE_RUNNING,
        "My macro",
        "My macro"
    )
    , OVERWRITE(
        "<b>Record over a macro with this name:</b>",
        LockMode::LOCK_WHILE_RUNNING,
        false
    )
    , RECORD_SECONDS(
        "<b>Stop recording after (seconds):</b><br>0: when you press Stop.",
        LockMode::LOCK_WHILE_RUNNING,
        0, 0, 3600
    )
    , LOOPS(
        "<b>Rounds to play:</b><br>0: until you press Stop.",
        LockMode::UNLOCK_WHILE_RUNNING,
        1, 0
    )
    , PAUSE_MS(
        "<b>Pause between two rounds (ms):</b>",
        LockMode::UNLOCK_WHILE_RUNNING,
        0, 0, 600000
    )
    , SPEED(
        "<b>Speed (%):</b><br>100: as recorded. 200: twice as fast.",
        LockMode::LOCK_WHILE_RUNNING,
        100, 10, 1000
    )
    , LIST(
        "List of steps:",
        {
            ControllerClass::NintendoSwitch_ProController,
            ControllerClass::NintendoSwitch_LeftJoycon,
            ControllerClass::NintendoSwitch_RightJoycon,
        }
    )
{
    PA_ADD_OPTION(HOW_TO);
    PA_ADD_OPTION(BUTTON_NAMES);
    PA_ADD_OPTION(MODE);
    PA_ADD_OPTION(NAME);
    PA_ADD_OPTION(OVERWRITE);
    PA_ADD_OPTION(RECORD_SECONDS);
    PA_ADD_OPTION(LOOPS);
    PA_ADD_OPTION(PAUSE_MS);
    PA_ADD_OPTION(SPEED);
    PA_ADD_OPTION(LIST);
}
Macro::~Macro() = default;


void Macro::program(SingleSwitchProgramEnvironment& env, CancellableScope& scope){
    switch ((Mode)MODE){
    case Mode::RECORD:
        record(env, scope);
        return;
    case Mode::PLAY:
        play(env, scope);
        return;
    case Mode::PLAY_LIST:
        play_list(env, scope);
        return;
    case Mode::SHOW:
        show(env);
        return;
    }
}


void Macro::on_command_input(WallClock timestamp, const ControllerState& state){
    JsonValue json = state.to_json();
    std::lock_guard<std::mutex> lg(m_lock);
    m_history.push_back(Snapshot{timestamp, std::move(json)});
}


JsonValue Macro::recording_to_json(ControllerClass controller_class){
    std::vector<Snapshot> history;
    {
        std::lock_guard<std::mutex> lg(m_lock);
        history = std::move(m_history);
        m_history.clear();
    }

    //  Each change of what is held is a step that lasts until the next change.
    //  The times are counted from the start and rounded then, so that the
    //  rounding does not add up (as Record Keyboard Controller does).
    JsonArray steps;
    if (history.size() >= 2){
        const WallClock start = history[0].time;
        auto since_start = [&](WallClock time){
            return std::chrono::round<std::chrono::milliseconds>(
                std::chrono::duration_cast<std::chrono::nanoseconds>(time - start)
            );
        };
        size_t previous = 0;
        for (size_t i = 1; i < history.size(); i++){
            const JsonObject& now = history[i].state.to_object_throw();
            const JsonObject& before = history[previous].state.to_object_throw();
            if (now == before){
                continue;
            }
            JsonObject step = before.clone();
            step["ms"] = (int64_t)(since_start(history[i].time) - since_start(history[previous].time)).count();
            steps.push_back(std::move(step));
            previous = i;
        }
    }

    JsonObject out;
    out["controller_class"] = CONTROLLER_CLASS_STRINGS().get_string(controller_class);
    out["console"] = game_profile(m_game).console;
    out["game"] = game_profile(m_game).title;
    out["history"] = JsonValue(std::move(steps));
    return out;
}


void Macro::record(SingleSwitchProgramEnvironment& env, CancellableScope& scope){
    const std::string name = NAME;
    if (macro_file_name(name).empty()){
        throw UserSetupError(env.logger(), "Give the macro a name first.");
    }
    const std::string path = macro_path(name);
    if (Filesystem::exists(Filesystem::Path(path)) && !OVERWRITE){
        throw UserSetupError(
            env.logger(),
            "There is a macro with this name already (" + path + "). Choose another name, or tick "
            "\"Record over a macro with this name\"."
        );
    }
    Filesystem::create_directories(Filesystem::Path(SETTINGS_PATH() + "Macros/"));

    AbstractController& controller = env.console.controller();
    const ControllerClass controller_class = controller.controller_class();
    {
        std::lock_guard<std::mutex> lg(m_lock);
        m_history.clear();
    }

    Macro_Descriptor::Stats& stats = env.current_stats<Macro_Descriptor::Stats>();
    auto save = [&]{
        controller.remove_input_sniffer(*this);
        JsonValue json = recording_to_json(controller_class);
        const size_t count = json.to_object_throw().get_array_throw("history").size();
        stats.steps = count;
        env.update_stats();
        if (count == 0){
            env.log("Nothing was pressed: no macro saved.", COLOR_ORANGE);
            return;
        }
        json.dump(path);
        env.log("Macro saved: " + path + " (" + std::to_string(count) + " steps).", COLOR_BLUE);
    };

    env.log(
        "Recording \"" + name + "\". Play with the keyboard or a controller of the computer; Stop ends it.",
        COLOR_BLUE
    );
    controller.add_input_sniffer(*this);
    try{
        if (RECORD_SECONDS > 0){
            scope.wait_for(std::chrono::seconds(RECORD_SECONDS));
        }else{
            scope.wait_until_cancel();
        }
    }catch (...){
        save();
        throw;
    }
    save();
}


namespace{

template <typename State>
uint64_t play_steps(
    AbstractControllerContext& context, const JsonArray& steps, uint32_t speed
){
    State state;
    uint64_t played = 0;
    for (const JsonValue& item : steps){
        const JsonObject& step = item.to_object_throw();
        uint64_t ms = 0;
        if (!step.read_integer(ms, "ms") && !step.read_integer(ms, "duration_in_ms")){
            throw JsonParseException("", "ms");
        }
        const std::chrono::milliseconds duration = scaled_ms(ms, speed);
        if (duration.count() == 0){
            continue;
        }
        state.load_json(step);
        //  Not logged: a line per step slows a fast macro down.
        state.execute(&context, false, context.controller(), duration);
        played++;
    }
    return played;
}

}


void Macro::pause(SingleSwitchProgramEnvironment& env, CancellableScope& scope){
    if (PAUSE_MS == 0){
        return;
    }
    AbstractControllerContext context(scope, env.console.controller());
    const ControllerClass type = context.controller().controller_class();
    if (type == ControllerClass::NintendoSwitch_ProController){
        ProControllerState().execute(&context, false, context.controller(), std::chrono::milliseconds(PAUSE_MS));
    }else{
        JoyconState().execute(&context, false, context.controller(), std::chrono::milliseconds(PAUSE_MS));
    }
    context.wait_for_all_requests();
}


void Macro::play(SingleSwitchProgramEnvironment& env, CancellableScope& scope){
    const std::string path = macro_path(NAME);
    if (!Filesystem::exists(Filesystem::Path(path))){
        throw UserSetupError(env.logger(), "There is no macro with this name: " + path);
    }
    const JsonValue json = load_json_file(path);
    const JsonObject& file = json.to_object_throw();
    const ControllerClass recorded = CONTROLLER_CLASS_STRINGS().get_enum(file.get_string_throw("controller_class"));
    const ControllerClass type = env.console.controller().controller_class();
    if (recorded != type){
        throw UserSetupError(
            env.logger(),
            "This macro was recorded with another kind of controller (" +
            CONTROLLER_CLASS_STRINGS().get_string(recorded) + "). Pick that one, or record it again."
        );
    }
    const JsonArray& steps = file.get_array_throw("history");
    if (steps.empty()){
        throw UserSetupError(env.logger(), "This macro has no steps.");
    }

    Macro_Descriptor::Stats& stats = env.current_stats<Macro_Descriptor::Stats>();
    const uint32_t speed = SPEED;
    env.log(
        "Playing \"" + std::string(NAME) + "\": " + std::to_string(steps.size()) + " steps, speed " +
        std::to_string(speed) + "%.",
        COLOR_BLUE
    );
    for (uint32_t round = 0; LOOPS == 0 || round < LOOPS; round++){
        {
            AbstractControllerContext context(scope, env.console.controller());
            const uint64_t played = type == ControllerClass::NintendoSwitch_ProController
                ? play_steps<ProControllerState>(context, steps, speed)
                : play_steps<JoyconState>(context, steps, speed);
            //  Let go of everything at the end of the round.
            if (type == ControllerClass::NintendoSwitch_ProController){
                ProControllerState().execute(&context, false, context.controller(), std::chrono::milliseconds(1));
            }else{
                JoyconState().execute(&context, false, context.controller(), std::chrono::milliseconds(1));
            }
            context.wait_for_all_requests();
            stats.steps += played;
        }
        stats.loops++;
        env.update_stats();
        if (LOOPS != 0 && round + 1 >= LOOPS){
            break;
        }
        pause(env, scope);
    }
}


void Macro::play_list(SingleSwitchProgramEnvironment& env, CancellableScope& scope){
    Macro_Descriptor::Stats& stats = env.current_stats<Macro_Descriptor::Stats>();
    for (uint32_t round = 0; LOOPS == 0 || round < LOOPS; round++){
        LIST.run(scope, env.console.controller());
        env.console.controller().wait_for_all(&scope);
        stats.loops++;
        env.update_stats();
        if (LOOPS != 0 && round + 1 >= LOOPS){
            break;
        }
        pause(env, scope);
    }
}


void Macro::show(SingleSwitchProgramEnvironment& env){
    const std::string path = macro_path(NAME);
    if (!Filesystem::exists(Filesystem::Path(path))){
        throw UserSetupError(env.logger(), "There is no macro with this name: " + path);
    }
    const JsonValue json = load_json_file(path);
    const JsonArray& steps = json.to_object_throw().get_array_throw("history");
    const PadKind pad = game_profile(m_game).pad;
    uint64_t total = 0;
    size_t index = 0;
    for (const JsonValue& item : steps){
        const JsonObject& step = item.to_object_throw();
        env.log(std::to_string(++index) + ". " + describe_step(pad, step));
        uint64_t ms = 0;
        if (step.read_integer(ms, "ms") || step.read_integer(ms, "duration_in_ms")){
            total += ms;
        }
    }
    env.log(
        "\"" + std::string(NAME) + "\": " + std::to_string(steps.size()) + " steps, " +
        std::to_string(total) + " ms in all.",
        COLOR_BLUE
    );
}



//  ---------------------------------------------------------------------
//  Tests
//  ---------------------------------------------------------------------

namespace{

class Test_Macro : public UnitTest{
public:
    Test_Macro()
        : UnitTest("ClaudeGG::Macro - names, speed and the steps by the names of each console")
    {}
    virtual UnitTestResult run(Logger&, CancellableScope&) const override{
        std::string failures;
        auto check = [&](bool ok, const std::string& what){
            if (!ok){
                failures += what + "\n";
            }
        };

        check(macro_file_name("My macro") == "My macro", "plain name");
        check(macro_file_name("../x:y") == "___x_y", "no folders in a name");
        check(macro_file_name("  ") == "", "only spaces");
        check(macro_file_name("//") == "", "only signs");

        check(scaled_ms(100, 100).count() == 100, "speed 100");
        check(scaled_ms(100, 200).count() == 50, "speed 200");
        check(scaled_ms(100, 50).count() == 200, "speed 50");
        check(scaled_ms(1, 1000).count() == 1, "at least 1 ms");
        check(scaled_ms(0, 100).count() == 0, "a step of 0 stays 0");

        JsonObject step;
        step["buttons"] = "B";
        step["dpad"] = "up";
        step["ms"] = (int64_t)120;
        check(describe_step(PadKind::PS3_CONTROLLER, step) == "CROSS + UP, 120 ms", "PS3: " + describe_step(PadKind::PS3_CONTROLLER, step));
        check(describe_step(PadKind::XBOX360_CONTROLLER, step) == "A + UP, 120 ms", "Xbox 360: " + describe_step(PadKind::XBOX360_CONTROLLER, step));
        check(describe_step(PadKind::GAMECUBE_CONTROLLER, step) == "A + UP, 120 ms", "GameCube: " + describe_step(PadKind::GAMECUBE_CONTROLLER, step));
        check(describe_step(PadKind::PRO_CONTROLLER, step) == "B + UP, 120 ms", "Switch: " + describe_step(PadKind::PRO_CONTROLLER, step));

        JsonObject stick;
        stick["lxf"] = 1.0;
        stick["lyf"] = 1.0;
        stick["rxf"] = 0.0;
        stick["ryf"] = 1.0;
        stick["ms"] = (int64_t)300;
        check(
            describe_step(PadKind::N64_CONTROLLER, stick) == "stick up-right + C buttons up, 300 ms",
            "N64 sticks: " + describe_step(PadKind::N64_CONTROLLER, stick)
        );

        JsonObject nothing;
        nothing["ms"] = (int64_t)50;
        check(describe_step(PadKind::PS4_CONTROLLER, nothing) == "nothing, 50 ms", "nothing held");

        JsonObject start;
        start["buttons"] = "+";
        start["ms"] = (int64_t)80;
        check(describe_step(PadKind::XBOXONE_CONTROLLER, start) == "MENU, 80 ms", "Xbox One: " + describe_step(PadKind::XBOXONE_CONTROLLER, start));
        check(describe_step(PadKind::PS4_CONTROLLER, start) == "OPTIONS, 80 ms", "PS4: " + describe_step(PadKind::PS4_CONTROLLER, start));

        if (failures.empty()){
            return true;
        }
        return failures;
    }
};

}

void add_tests_Macro(UnitTestDatabase& database){
    database.add<Test_Macro>();
}



}
}
