/*  ClaudeGG Claude Plays: the program
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <atomic>
#include <chrono>
#include <string>
#include <QImage>
#include <QPainter>
#include <QPainterPath>
#include "Common/Cpp/Exceptions.h"
#include "CommonFramework/Globals.h"
#include "CommonFramework/Language.h"
#include "CommonFramework/Exceptions/OperationFailedException.h"
#include "CommonFramework/ImageTypes/ImageRGB32_Qt.h"
#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/Notifications/ProgramNotifications.h"
#include "CommonFramework/ProgramStats/StatsTracking.h"
#include "CommonFramework/VideoPipeline/VideoFeed.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "CommonTools/OCR/OCR_Routines.h"
#include "NintendoSwitch/Commands/NintendoSwitch_Commands_PushButtons.h"
#include "NintendoSwitch/Controllers/Joycon/NintendoSwitch_Joycon.h"
#include "NintendoSwitch/Controllers/PABotBase2/NintendoSwitch_PABotBase2_WiredController.h"
#include "NintendoSwitch/Controllers/PABotBase2/NintendoSwitch_PABotBase2_ProController.h"
#include "NintendoSwitch/Controllers/Procon/NintendoSwitch_ProController.h"
#include "Controllers/StandardHid/StandardHid_Keyboard.h"
#include "ControllerInput/Keyboard/KeyboardHidButtons.h"
#include "NintendoSwitch/NintendoSwitch_ConsoleHandle.h"
#include "PokemonBDSP/Programs/PokemonBDSP_GameNavigation.h"
#include "VideoGames/PokemonLA/Programs/PokemonLA_GameSave.h"
#include "VideoGames/PokemonLZA/Programs/PokemonLZA_BasicNavigation.h"
#include "VideoGames/PokemonSV/Programs/PokemonSV_SaveGame.h"
#include "VideoGames/PokemonSwSh/Programs/PokemonSwSh_MenuNavigation.h"
#include "ClaudePlays_AnyGame.h"
#include "ClaudePlays_Calibrate.h"
#include "ClaudePlays_Consoles.h"
#include "ClaudePlays_External.h"
#include "ClaudePlays_GameCard.h"
#include "ClaudePlays_Program.h"
#include "ClaudePlays_Sees.h"
#include "ClaudeGG/ClaudeGG_Macro.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace ClaudePlays{

using namespace NintendoSwitch;



std::unique_ptr<PanelDescriptor> make_claude_plays(GameId game){
    return std::make_unique<GameProgram_Descriptor>(game);
}


namespace{

std::string description_of(const GameProfile& profile){
    return
        "Claude plays " + profile.title + " toward a goal you write down, on your own Claude API key (or "
        "through Claude Code, on your subscription): it looks at the screen, has the text on it read, and "
        "works the controller.";
}

}


GameProgram_Descriptor::GameProgram_Descriptor(GameId game)
    : SingleSwitchProgramDescriptor(
        game_profile(game).identifier,
        game_profile(game).category, "Claude Plays",
        "",
        description_of(game_profile(game)),
        PanelQualityStanding::EXPERIMENTAL,
        game_profile(game).pad == PadKind::RIGHT_JOYCON || game_profile(game).pad == PadKind::IPHONE_KEYBOARD
            ? ProgramControllerClass::SpecializedController
            : ProgramControllerClass::StandardController_NoRestrictions,
        FeedbackType::REQUIRED,
        AllowCommandsWhenRunning::DISABLE_COMMANDS,
        {
            //  Multi-line OCR (the text on the screen).
            "PaddleOCRDetection",
        }
    )
    , m_game(game)
{}

struct GameProgram_Descriptor::Stats : public StatsTracker{
    Stats()
        : actions(m_stats["Actions"])
        , requests(m_stats["Requests to Claude"])
        , tokens(m_stats["Tokens"])
    {
        m_display_order.emplace_back("Actions");
        m_display_order.emplace_back("Requests to Claude");
        m_display_order.emplace_back("Tokens");
    }

    std::atomic<uint64_t>& actions;
    std::atomic<uint64_t>& requests;
    std::atomic<uint64_t>& tokens;
};

std::unique_ptr<StatsTracker> GameProgram_Descriptor::make_stats() const{
    return std::unique_ptr<StatsTracker>(new Stats());
}
std::unique_ptr<GameConsole::ConsoleProgramInstance> GameProgram_Descriptor::make_instance(
    GameConsole::ConsoleSystemSession&
) const{
    return std::make_unique<GameProgram>(m_game);
}



namespace{


//  The buttons by the names Claude uses.
bool button_of(const std::string& name, Button& button){
    struct Entry{
        const char* name;
        Button button;
    };
    static const Entry ENTRIES[] = {
        {"A",       BUTTON_A},
        {"B",       BUTTON_B},
        {"X",       BUTTON_X},
        {"Y",       BUTTON_Y},
        {"L",       BUTTON_L},
        {"R",       BUTTON_R},
        {"ZL",      BUTTON_ZL},
        {"ZR",      BUTTON_ZR},
        {"PLUS",    BUTTON_PLUS},
        {"MINUS",   BUTTON_MINUS},
        {"LSTICK",  BUTTON_LCLICK},
        {"RSTICK",  BUTTON_RCLICK},
        //  Of a right Joy-Con.
        {"STICK",   BUTTON_RCLICK},
        {"HOME",    BUTTON_HOME},
    };
    for (const Entry& entry : ENTRIES){
        if (name == entry.name){
            button = entry.button;
            return true;
        }
    }
    return false;
}

//  The d-pad, from the directions that are held.
DpadPosition dpad_of(bool up, bool down, bool left, bool right){
    if (up && right){
        return DPAD_UP_RIGHT;
    }
    if (up && left){
        return DPAD_UP_LEFT;
    }
    if (down && right){
        return DPAD_DOWN_RIGHT;
    }
    if (down && left){
        return DPAD_DOWN_LEFT;
    }
    if (up){
        return DPAD_UP;
    }
    if (down){
        return DPAD_DOWN;
    }
    if (left){
        return DPAD_LEFT;
    }
    if (right){
        return DPAD_RIGHT;
    }
    return DPAD_NONE;
}

std::string read_picture(const ImageViewRGB32& picture, Language language){
    //  Every line of text in the picture, from the top.
    return OCR::ocr_read(language, picture, OCR::PageSegMode::AUTO);
}


//  The console with a Pro Controller.
class ProConsole : public PlayConsole{
public:
    ProConsole(SingleSwitchProgramEnvironment& env, ProControllerContext& context, GameId game, Language language)
        : m_env(env)
        , m_context(context)
        , m_game(game)
        , m_language(language)
    {}

    virtual const PadLayout& layout() const override{
        return pro_controller_layout();
    }
    virtual void hold(const PadInput& input, std::chrono::milliseconds duration) override{
        Button buttons = BUTTON_NONE;
        bool up = false;
        bool down = false;
        bool left = false;
        bool right = false;
        for (const std::string& name : input.buttons){
            Button button = BUTTON_NONE;
            if (button_of(name, button)){
                buttons |= button;
            }else if (name == "UP"){
                up = true;
            }else if (name == "DOWN"){
                down = true;
            }else if (name == "LEFT"){
                left = true;
            }else if (name == "RIGHT"){
                right = true;
            }
        }
        pbf_controller_state(
            m_context, buttons, dpad_of(up, down, left, right),
            JoystickPosition(input.stick_x, input.stick_y),
            JoystickPosition(input.stick2_x, input.stick2_y),
            duration
        );
    }
    virtual void mash(const std::string& name, std::chrono::milliseconds duration) override{
        Button button = BUTTON_NONE;
        if (button_of(name, button)){
            pbf_mash_button(m_context, button, duration);
        }
    }
    virtual void wait(std::chrono::milliseconds duration) override{
        pbf_wait(m_context, duration);
    }
    virtual bool screen(const std::function<void(const ImageViewRGB32&)>& use) override{
        m_context.wait_for_all_requests();
        VideoSnapshot snapshot = m_env.console.video().snapshot();
        if (!snapshot){
            return false;
        }
        const ImageViewRGB32& frame = *snapshot.frame;
        use(frame);
        return true;
    }
    virtual std::string read_text(const ImageViewRGB32& picture) override{
        return read_picture(picture, m_language);
    }
    virtual std::string sees(const ImageViewRGB32& picture) override{
        return game_sees(m_game, picture);
    }

    virtual bool can_save() const override{
        return game_profile(m_game).save_routine;
    }
    virtual PlayResult save_game() override{
        PlayResult result;
        m_context.wait_for_all_requests();
        try{
            switch (m_game){
            case GameId::SWORD_SHIELD:
                PokemonSwSh::save_game(m_env.console, m_context);
                result.text = "The game is saved.";
                break;
            case GameId::BRILLIANT_DIAMOND_SHINING_PEARL:
                PokemonBDSP::save_game(m_env.console, m_context);
                result.text = "The routine opened the menu and saved the game.";
                break;
            case GameId::LEGENDS_ARCEUS:
                if (PokemonLA::save_game_from_overworld(m_env, m_env.console, m_context)){
                    result.text = "The game is saved.";
                }else{
                    result.is_error = true;
                    result.text =
                        "The game cannot be saved right now: the player is in the air, rolling or falling.";
                }
                break;
            case GameId::SCARLET_VIOLET:
                PokemonSV::save_game_from_menu_or_overworld(m_env.program_info(), m_env.console, m_context, true);
                result.text = "The game is saved, and the player is back in the overworld.";
                break;
            case GameId::LEGENDS_ZA:
                if (PokemonLZA::save_game_to_menu(m_env.console, m_context)){
                    result.text = "The game is saved. Its main menu is open: B closes it.";
                }else{
                    result.is_error = true;
                    result.text = "The game could not be saved here: a dialog came up instead of the question to save.";
                }
                break;
            default:
                result.is_error = true;
                result.text = "This game has no routine to save.";
                break;
            }
        }catch (OperationFailedException& e){
            //  The routine did not understand the screen: for Claude to sort
            //  out, with a look at it.
            m_env.log("Claude Plays: the routine that saves the game gave up: " + e.message(), COLOR_ORANGE);
            result.is_error = true;
            result.text =
                "The program's routine gave up: " + one_line(e.message(), 300) +
                " The game is as that left it: look before you go on.";
        }
        m_context.wait_for_all_requests();
        return result;
    }

private:
    SingleSwitchProgramEnvironment& m_env;
    ProControllerContext& m_context;
    const GameId m_game;
    const Language m_language;
};


//  A PlayStation 3, with a board that plays the Switch's wired controller
//  (NS1: Wired Controller, a HORIPAD S to the console). That is a plain USB
//  gamepad, which the PlayStation 3 takes: its buttons come in the order of a
//  PlayStation pad (square, cross, circle, triangle, L1, R1, L2, R2, SELECT,
//  START, L3, R3, PS), which is the order of Y, B, A, X, L, R, ZL, ZR, MINUS,
//  PLUS and the sticks of the Switch. Not tried on a PlayStation 3 yet.
bool ps3_button_of(const std::string& name, Button& button){
    struct Entry{
        const char* name;
        Button button;
    };
    static const Entry ENTRIES[] = {
        {"SQUARE",      BUTTON_Y},
        {"CROSS",       BUTTON_B},
        {"CIRCLE",      BUTTON_A},
        {"TRIANGLE",    BUTTON_X},
        {"L1",          BUTTON_L},
        {"R1",          BUTTON_R},
        {"L2",          BUTTON_ZL},
        {"R2",          BUTTON_ZR},
        {"SELECT",      BUTTON_MINUS},
        {"START",       BUTTON_PLUS},
        {"L3",          BUTTON_LCLICK},
        {"R3",          BUTTON_RCLICK},
        {"HOME",        BUTTON_HOME},
    };
    for (const Entry& entry : ENTRIES){
        if (name == entry.name){
            button = entry.button;
            return true;
        }
    }
    return false;
}

//  An original Xbox, with the same board plugged into a Raspberry Pi Pico
//  with OGX-Mini (MIT), which plays an original Xbox controller to the
//  console. OGX-Mini takes the board as a Switch pad (a HORIPAD S is on its
//  list) and passes it on by the places of the buttons: B to A, A to B, Y to
//  X, X to Y, L to WHITE, R to BLACK, ZL and ZR to the triggers, MINUS to
//  BACK and PLUS to START (its SwitchWired host driver and XboxOG device
//  driver). Its first mode is the original Xbox. Not tried on an Xbox yet.
bool xbox_button_of(const std::string& name, Button& button){
    struct Entry{
        const char* name;
        Button button;
    };
    static const Entry ENTRIES[] = {
        {"A",           BUTTON_B},
        {"B",           BUTTON_A},
        {"X",           BUTTON_Y},
        {"Y",           BUTTON_X},
        {"WHITE",       BUTTON_L},
        {"BLACK",       BUTTON_R},
        {"LT",          BUTTON_ZL},
        {"RT",          BUTTON_ZR},
        {"BACK",        BUTTON_MINUS},
        {"START",       BUTTON_PLUS},
        {"LSTICK",      BUTTON_LCLICK},
        {"RSTICK",      BUTTON_RCLICK},
    };
    for (const Entry& entry : ENTRIES){
        if (name == entry.name){
            button = entry.button;
            return true;
        }
    }
    return false;
}

//  The retro consoles, with a wireless board (a Switch Pro Controller) and a
//  BlueRetro adapter (Apache-2.0, an ESP32 in the console's controller port).
//  BlueRetro maps a Bluetooth pad by the places of its buttons (its tables
//  of the Switch Pro Controller and of each console): the left face button
//  (Y) to the left one of the console, the bottom one (B) to the bottom one,
//  and so on; L and R to L1 and R1, ZL and ZR to L2 and R2 or the analog
//  triggers. The PlayStation and the PlayStation 2 come out as the
//  PlayStation 3 (ps3_button_of()). Not tried on any of them yet.

//  The GameCube: Y to B, B to A, A to X, X to Y, L and R both to Z, ZL and ZR
//  to the analog L and R, PLUS to START. The right stick is the C stick.
bool gamecube_button_of(const std::string& name, Button& button){
    struct Entry{
        const char* name;
        Button button;
    };
    static const Entry ENTRIES[] = {
        {"A",           BUTTON_B},
        {"B",           BUTTON_Y},
        {"X",           BUTTON_A},
        {"Y",           BUTTON_X},
        {"Z",           BUTTON_R},
        {"L",           BUTTON_ZL},
        {"R",           BUTTON_ZR},
        {"START",       BUTTON_PLUS},
    };
    for (const Entry& entry : ENTRIES){
        if (name == entry.name){
            button = entry.button;
            return true;
        }
    }
    return false;
}

//  The Nintendo 64: B to A, Y to B, A to C_DOWN, X to C_LEFT, ZL and ZR to Z,
//  L to L, R to R, PLUS to START. C_UP and C_RIGHT are only on the right
//  stick (n64_stick_of()), which BlueRetro turns into the four C buttons.
bool n64_button_of(const std::string& name, Button& button){
    struct Entry{
        const char* name;
        Button button;
    };
    static const Entry ENTRIES[] = {
        {"A",           BUTTON_B},
        {"B",           BUTTON_Y},
        {"C_DOWN",      BUTTON_A},
        {"C_LEFT",      BUTTON_X},
        {"Z",           BUTTON_ZL},
        {"L",           BUTTON_L},
        {"R",           BUTTON_R},
        {"START",       BUTTON_PLUS},
    };
    for (const Entry& entry : ENTRIES){
        if (name == entry.name){
            button = entry.button;
            return true;
        }
    }
    return false;
}
bool n64_stick_of(const std::string& name, double& x, double& y){
    if (name == "C_UP"){
        x = 0;
        y = 1;
        return true;
    }
    if (name == "C_RIGHT"){
        x = 1;
        y = 0;
        return true;
    }
    return false;
}

//  The Dreamcast: B to A, A to B, Y to X, X to Y, ZL and ZR to the analog L
//  and R, PLUS to START.
bool dreamcast_button_of(const std::string& name, Button& button){
    struct Entry{
        const char* name;
        Button button;
    };
    static const Entry ENTRIES[] = {
        {"A",           BUTTON_B},
        {"B",           BUTTON_A},
        {"X",           BUTTON_Y},
        {"Y",           BUTTON_X},
        {"L",           BUTTON_ZL},
        {"R",           BUTTON_ZR},
        {"START",       BUTTON_PLUS},
    };
    for (const Entry& entry : ENTRIES){
        if (name == entry.name){
            button = entry.button;
            return true;
        }
    }
    return false;
}

//  The Xbox 360: the same board through a Pico with OGX-Mini in its XInput
//  mode (OGX-Mini-2026 answers the console's check of a pad; the older
//  OGX-Mini only works on a console with UsbdSecPatch). OGX-Mini passes
//  the Switch pad on by the places of the buttons, as for the original Xbox,
//  with L and R to LB and RB and HOME to the Guide button.
bool xbox360_button_of(const std::string& name, Button& button){
    struct Entry{
        const char* name;
        Button button;
    };
    static const Entry ENTRIES[] = {
        {"A",           BUTTON_B},
        {"B",           BUTTON_A},
        {"X",           BUTTON_Y},
        {"Y",           BUTTON_X},
        {"LB",          BUTTON_L},
        {"RB",          BUTTON_R},
        {"LT",          BUTTON_ZL},
        {"RT",          BUTTON_ZR},
        {"BACK",        BUTTON_MINUS},
        {"START",       BUTTON_PLUS},
        {"MENU",        BUTTON_PLUS},
        {"VIEW",        BUTTON_MINUS},
        {"LSTICK",      BUTTON_LCLICK},
        {"RSTICK",      BUTTON_RCLICK},
        {"HOME",        BUTTON_HOME},
    };
    for (const Entry& entry : ENTRIES){
        if (name == entry.name){
            button = entry.button;
            return true;
        }
    }
    return false;
}

//  Remote Play: the board is a USB gamepad of the computer, and the Remote
//  Play client (chiaki-ng for a PlayStation; for an Xbox a browser on
//  xbox.com/remoteplay, through a Pico with OGX-Mini, which makes it an Xbox
//  360 controller) takes it as a standard gamepad, by the places of its buttons:
//  the bottom one (B) is CROSS or A. The PlayStation 4 and 5 are laid out as
//  the PlayStation 3, with OPTIONS for START and SHARE for SELECT; the Xbox
//  One and Series as the Xbox 360 (xbox360_button_of(), MENU and VIEW).
bool ps4_button_of(const std::string& name, Button& button){
    if (name == "OPTIONS"){
        button = BUTTON_PLUS;
        return true;
    }
    if (name == "SHARE"){
        button = BUTTON_MINUS;
        return true;
    }
    return ps3_button_of(name, button);
}

//  A console that is played with a Switch controller under other names: the
//  PlayStation 3 and the original Xbox (the wired controller), the retro
//  consoles (the wireless Pro Controller, through BlueRetro).
class WiredPadConsole : public PlayConsole{
public:
    using ButtonOf = bool (*)(const std::string& name, Button& button);
    //  A button of the console that is a push of the right stick (the C
    //  buttons of a Nintendo 64): where to push it.
    using StickOf = bool (*)(const std::string& name, double& x, double& y);

    WiredPadConsole(
        SingleSwitchProgramEnvironment& env, ProControllerContext& context, Language language,
        const PadLayout& layout, ButtonOf button_of, StickOf stick_of = nullptr
    )
        : m_env(env)
        , m_context(context)
        , m_language(language)
        , m_layout(layout)
        , m_button_of(button_of)
        , m_stick_of(stick_of)
    {}

    virtual const PadLayout& layout() const override{
        return m_layout;
    }
    virtual void hold(const PadInput& input, std::chrono::milliseconds duration) override{
        Button buttons = BUTTON_NONE;
        bool up = false;
        bool down = false;
        bool left = false;
        bool right = false;
        double stick2_x = input.stick2_x;
        double stick2_y = input.stick2_y;
        for (const std::string& name : input.buttons){
            Button button = BUTTON_NONE;
            double x = 0;
            double y = 0;
            if (m_button_of(name, button)){
                buttons |= button;
            }else if (m_stick_of != nullptr && m_stick_of(name, x, y)){
                stick2_x = x;
                stick2_y = y;
            }else if (name == "UP"){
                up = true;
            }else if (name == "DOWN"){
                down = true;
            }else if (name == "LEFT"){
                left = true;
            }else if (name == "RIGHT"){
                right = true;
            }
        }
        pbf_controller_state(
            m_context, buttons, dpad_of(up, down, left, right),
            JoystickPosition(input.stick_x, input.stick_y),
            JoystickPosition(stick2_x, stick2_y),
            duration
        );
    }
    virtual void mash(const std::string& name, std::chrono::milliseconds duration) override{
        Button button = BUTTON_NONE;
        double x = 0;
        double y = 0;
        if (m_button_of(name, button)){
            pbf_mash_button(m_context, button, duration);
        }else if (m_stick_of != nullptr && m_stick_of(name, x, y)){
            //  A push of the stick and a let go, again and again.
            const std::chrono::milliseconds STEP(50);
            for (std::chrono::milliseconds done(0); done < duration; done += 2 * STEP){
                pbf_controller_state(m_context, BUTTON_NONE, DPAD_NONE, JoystickPosition(0, 0), JoystickPosition(x, y), STEP);
                pbf_controller_state(m_context, BUTTON_NONE, DPAD_NONE, JoystickPosition(0, 0), JoystickPosition(0, 0), STEP);
            }
        }
    }
    virtual void wait(std::chrono::milliseconds duration) override{
        pbf_wait(m_context, duration);
    }
    virtual bool screen(const std::function<void(const ImageViewRGB32&)>& use) override{
        m_context.wait_for_all_requests();
        VideoSnapshot snapshot = m_env.console.video().snapshot();
        if (!snapshot){
            return false;
        }
        const ImageViewRGB32& frame = *snapshot.frame;
        use(frame);
        return true;
    }
    virtual std::string read_text(const ImageViewRGB32& picture) override{
        return read_picture(picture, m_language);
    }

private:
    SingleSwitchProgramEnvironment& m_env;
    ProControllerContext& m_context;
    const Language m_language;
    const PadLayout& m_layout;
    const ButtonOf m_button_of;
    const StickOf m_stick_of;
};


//  The console with a single right Joy-Con. A direction is its stick.
class JoyconConsole : public PlayConsole{
public:
    JoyconConsole(SingleSwitchProgramEnvironment& env, JoyconContext& context, Language language)
        : m_env(env)
        , m_context(context)
        , m_language(language)
    {}

    virtual const PadLayout& layout() const override{
        return right_joycon_layout();
    }
    virtual void hold(const PadInput& input, std::chrono::milliseconds duration) override{
        Button buttons = BUTTON_NONE;
        for (const std::string& name : input.buttons){
            Button button = BUTTON_NONE;
            if (button_of(name, button)){
                buttons |= button;
            }
        }
        pbf_controller_state(m_context, buttons, JoystickPosition(input.stick_x, input.stick_y), duration);
    }
    virtual void mash(const std::string& name, std::chrono::milliseconds duration) override{
        Button button = BUTTON_NONE;
        if (button_of(name, button)){
            pbf_mash_button(m_context, button, duration);
        }
    }
    virtual void wait(std::chrono::milliseconds duration) override{
        pbf_wait(m_context, duration);
    }
    virtual bool screen(const std::function<void(const ImageViewRGB32&)>& use) override{
        m_context.wait_for_all_requests();
        VideoSnapshot snapshot = m_env.console.video().snapshot();
        if (!snapshot){
            return false;
        }
        const ImageViewRGB32& frame = *snapshot.frame;
        use(frame);
        return true;
    }
    virtual std::string read_text(const ImageViewRGB32& picture) override{
        return read_picture(picture, m_language);
    }

private:
    SingleSwitchProgramEnvironment& m_env;
    JoyconContext& m_context;
    const Language m_language;
};


//  An iPhone, with the wired board as a keyboard (HID: Keyboard) and Full
//  Keyboard Access turned on (Settings, Accessibility, Keyboards): the keys
//  move a frame over the items on the screen and tap the one in it. HOME is
//  Command-H. Not tried on an iPhone yet.
bool iphone_keys_of(const std::string& name, std::vector<KeyboardKey>& keys){
    struct Entry{
        const char* name;
        KeyboardKey first;
        KeyboardKey second;
    };
    static const Entry ENTRIES[] = {
        {"TAB",         KEY_TAB,        KEY_NONE},
        {"SHIFT_TAB",   KEY_LEFT_SHIFT, KEY_TAB},
        {"SPACE",       KEY_SPACE,      KEY_NONE},
        {"ENTER",       KEY_ENTER,      KEY_NONE},
        {"ESCAPE",      KEY_ESC,        KEY_NONE},
        {"BACKSPACE",   KEY_BACKSPACE,  KEY_NONE},
        {"UP",          KEY_UP,         KEY_NONE},
        {"DOWN",        KEY_DOWN,       KEY_NONE},
        {"LEFT",        KEY_LEFT,       KEY_NONE},
        {"RIGHT",       KEY_RIGHT,      KEY_NONE},
        {"HOME",        KEY_LEFT_META,  KEY_H},
    };
    for (const Entry& entry : ENTRIES){
        if (name == entry.name){
            keys.push_back(entry.first);
            if (entry.second != KEY_NONE){
                keys.push_back(entry.second);
            }
            return true;
        }
    }
    return false;
}

class KeyboardConsole : public PlayConsole{
public:
    KeyboardConsole(SingleSwitchProgramEnvironment& env, StandardHid::KeyboardContext& context, Language language)
        : m_env(env)
        , m_context(context)
        , m_language(language)
    {}

    virtual const PadLayout& layout() const override{
        return iphone_keyboard_layout();
    }
    virtual void hold(const PadInput& input, std::chrono::milliseconds duration) override{
        std::vector<KeyboardKey> keys;
        for (const std::string& name : input.buttons){
            iphone_keys_of(name, keys);
        }
        if (keys.empty()){
            wait(duration);
            return;
        }
        m_context->issue_keys(&m_context, duration, duration, std::chrono::milliseconds(0), keys);
    }
    virtual void mash(const std::string& name, std::chrono::milliseconds duration) override{
        std::vector<KeyboardKey> keys;
        if (!iphone_keys_of(name, keys)){
            return;
        }
        //  A press and a let go, again and again.
        const std::chrono::milliseconds STEP(60);
        for (std::chrono::milliseconds done(0); done < duration; done += 2 * STEP){
            m_context->issue_keys(&m_context, 2 * STEP, STEP, std::chrono::milliseconds(0), keys);
        }
    }
    virtual void wait(std::chrono::milliseconds duration) override{
        m_context->issue_nop(&m_context, duration);
    }
    virtual bool screen(const std::function<void(const ImageViewRGB32&)>& use) override{
        m_context.wait_for_all_requests();
        VideoSnapshot snapshot = m_env.console.video().snapshot();
        if (!snapshot){
            return false;
        }
        const ImageViewRGB32& frame = *snapshot.frame;
        use(frame);
        return true;
    }
    virtual std::string read_text(const ImageViewRGB32& picture) override{
        return read_picture(picture, m_language);
    }

private:
    SingleSwitchProgramEnvironment& m_env;
    StandardHid::KeyboardContext& m_context;
    const Language m_language;
};


//  The program a session runs in.
class ProgramHost : public Host{
public:
    ProgramHost(
        SingleSwitchProgramEnvironment& env, CancellableScope& scope,
        GameProgram_Descriptor::Stats& stats, bool overlay
    )
        : m_env(env)
        , m_scope(scope)
        , m_stats(stats)
        , m_overlay(overlay)
    {}

    virtual void log(const std::string& text, Color color) override{
        m_env.log(text, color);
    }
    virtual void show(const std::string& text, Color color) override{
        if (m_overlay){
            m_env.console.overlay().add_log(one_line(text, 110), color);
        }
    }
    virtual void count(uint64_t actions, const PlayUsage& usage) override{
        m_stats.actions += actions - m_actions;
        m_stats.requests += usage.requests - m_requests;
        m_stats.tokens += usage.tokens - m_tokens;
        m_actions = actions;
        m_requests = usage.requests;
        m_tokens = usage.tokens;
        m_env.update_stats();
    }
    virtual CancellableScope& scope() override{
        return m_scope;
    }

private:
    SingleSwitchProgramEnvironment& m_env;
    CancellableScope& m_scope;
    GameProgram_Descriptor::Stats& m_stats;
    const bool m_overlay;
    //  What the numbers under the video have already.
    uint64_t m_actions = 0;
    uint64_t m_requests = 0;
    uint64_t m_tokens = 0;
};


//  The measuring of the timing (ClaudePlays_Calibrate.h) on a console of a
//  session.
class ConsoleProbe : public CalibrationProbe{
public:
    explicit ConsoleProbe(PlayConsole& console)
        : m_console(console)
    {}
    virtual void press(bool down, int ms) override{
        PadInput input;
        if (m_console.layout().directions_are_stick){
            input.stick_y = down ? -1 : 1;
        }else{
            input.buttons.push_back(down ? "DOWN" : "UP");
        }
        m_console.hold(input, std::chrono::milliseconds(ms));
        //  Until the press is over (a look waits for everything sent).
        m_console.screen([](const ImageViewRGB32&){});
    }
    virtual void wait(int ms) override{
        m_console.wait(std::chrono::milliseconds(ms));
        m_console.screen([](const ImageViewRGB32&){});
    }
    virtual bool mark() override{
        m_marked = ScreenThumb();
        m_console.screen([&](const ImageViewRGB32& frame){
            m_marked = screen_thumb(frame);
        });
        return m_marked.valid();
    }
    virtual double changed() override{
        ScreenThumb now;
        m_console.screen([&](const ImageViewRGB32& frame){
            now = screen_thumb(frame);
        });
        if (!now.valid()){
            return -1;
        }
        return thumb_difference(m_marked, now);
    }
    virtual double now_ms() override{
        return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now().time_since_epoch()).count();
    }

private:
    PlayConsole& m_console;
    ScreenThumb m_marked;
};

std::string timing_text(const InputTiming& timing){
    return "presses of " + std::to_string(timing.press_ms) + " ms (directions " +
        std::to_string(timing.direction_ms) + " ms), " + std::to_string(timing.gap_ms) + " ms after each" +
        (timing.video_delay_ms > 0
            ? ", the picture looked at " + std::to_string(timing.video_delay_ms) + " ms later"
            : std::string());
}

std::string setup_text(const GameProfile& profile){
    const bool other = profile.id == GameId::OTHER_GAMES;
    const bool ps3 = profile.pad == PadKind::PS3_CONTROLLER;
    const bool xbox = profile.pad == PadKind::XBOX_CONTROLLER;
    const bool retro = profile.console == "retro";
    const std::string& console = profile.console;
    return
        "<b>Experimental:</b> this program is new. It has not been tested on a console, and not with a real "
        "API key either: the build machine has none. Watch it. <b>Many games save by themselves:</b> what "
        "Claude does in the game can be final. Where that matters, make a save or a backup of your own "
        "first.<br>"
        "<b>What it does:</b> Claude, the AI model of Anthropic, plays " +
        (other ? std::string("whatever game is on the screen") : profile.title) +
        " toward the goal below. It gets small pictures of the screen and the text the program reads from "
        "it, and works the controller: buttons pressed, buttons and sticks held, a button mashed. After "
        "every action the program tells it how much of the picture changed, which costs next to nothing. "
        "It is slow next to a program made for one task (every decision is a request to Claude), and it can "
        "get lost: it is for things no program exists for.<br>"
        "<b>What it needs:</b> your Claude API key in the panel \"Claude\" (along the top of the window). Each request is billed "
        "to you by Anthropic; the pictures of the game and the text read from it are sent to Anthropic. What "
        "a session used is in the log and under the video. Without a key: set \"Who plays\" to Claude Code, "
        "and play with a Claude Code of your own, which calls this program's tools (see that option).<br>"
        "<b>Setup:</b> " +
        (other
            ? std::string("a game on the screen that is played with a Pro Controller")
            : ps3
            ? std::string(
                "a PlayStation 3 with a game on the screen, and a wired board (the ESP32-S3) plugged into "
                "it, with NS1: Wired Controller as the type. The PlayStation 3 takes that as a plain USB "
                "gamepad. Not tried on a PlayStation 3 yet: first check in its menu that the d-pad moves "
                "and that CROSS picks")
            : xbox
            ? std::string(
                "an original Xbox with a game on the screen, and a wired board (the ESP32-S3) with NS1: Wired "
                "Controller as the type, plugged into a Raspberry Pi Pico with OGX-Mini, which is plugged into "
                "the Xbox. OGX-Mini takes the board as a Switch pad and plays an original Xbox controller. Not "
                "tried on an Xbox yet: first check in its menu that the d-pad moves and that A picks")
            : console == "xbox360"
            ? std::string(
                "an Xbox 360, and the wired board (the ESP32-S3) with NS1: Wired Controller as the type, plugged "
                "into a Raspberry Pi Pico with OGX-Mini-2026 in its XInput mode, which is plugged into the Xbox "
                "360 (the older OGX-Mini only works on a console with UsbdSecPatch). Not "
                "tried on an Xbox 360 yet: first check in its menu that the d-pad moves and that A picks")
            : console == "psremote" || console == "xboxremote"
            ? std::string(
                "Remote Play of the console on this computer (") +
              (console == "psremote" ? "chiaki-ng for a PlayStation 4 or 5" : "a browser on xbox.com/remoteplay for an Xbox One or Series") +
              "), its window as the video (OBS Studio's virtual camera), and the wired board (the ESP32-S3) "
              "with NS1: Wired Controller as the type, " +
              (console == "psremote"
                  ? "with both its cables in this computer: chiaki-ng takes it as a USB gamepad"
                  : "plugged into a Raspberry Pi Pico with OGX-Mini in its XInput mode, which is plugged into this "
                    "computer: the browser takes it as an Xbox 360 controller") +
              ". Not tried yet: first check that the d-pad moves in the console's menu"
            : console == "iphone"
            ? std::string(
                "an iPhone with Full Keyboard Access turned on (Settings, Accessibility, Keyboards), its screen "
                "on the capture card through an HDMI adapter, and the wired board (the ESP32-S3) with HID: "
                "Keyboard as the type, plugged into the iPhone. Not tried on an iPhone yet: first check that "
                "TAB moves the frame and SPACE taps")
            : console == "psclassic"
            ? std::string(
                "a PlayStation Classic with a game on the screen, and the wired board (the ESP32-S3) with NS1: "
                "Wired Controller as the type, plugged into a Raspberry Pi Pico with OGX-Mini in its PlayStation "
                "Classic mode, which is plugged into a controller port of the console. Not tried on a "
                "PlayStation Classic yet: first check in its menu that the d-pad moves and that CROSS picks")
            : retro
            ? std::string("a ") + profile.category + " with a game on the screen, and a BlueRetro adapter (an "
                "ESP32 with the BlueRetro firmware) in its first controller port. A wireless board (a Pico W, "
                "a Pico 2 W or an ESP32) with NS1: Wireless Pro Controller as the type pairs with the adapter "
                "as a Switch Pro Controller, and the adapter plays the console's own pad. Not tried on a " +
                profile.category + " yet: first check that the d-pad moves in a menu and that the buttons are "
                "where the program says"
            : std::string("the game on the screen, with the controller its other programs use") +
              (profile.pad == PadKind::RIGHT_JOYCON ? " (a right Joy-Con)" : "")) +
        ". Text is read in the language set under \"Language of the text\" (English unless you change it).";
}

//  The choices of the option "Game" of Other Games: nothing in particular, and
//  each game that has no list of its own (it has its profile, with its buttons,
//  but no tile on the page with the games).
EnumDropdownDatabase<GameId> other_games_database(){
    EnumDropdownDatabase<GameId> database;
    database.add(GameId::OTHER_GAMES, "other", "Whatever is on the screen", true);
    for (GameId id : all_games()){
        if (is_other_games_choice(id)){
            const GameProfile& profile = game_profile(id);
            database.add(id, profile.identifier, profile.title, true);
        }
    }
    return database;
}

}   //  namespace



GameProgram::GameProgram(GameId game)
    : m_game(game)
    , SETUP_TEXT(setup_text(game_profile(game)))
    , GAME(
        "<b>Game:</b><br>What the program tells Claude about the game: its name and its main controls, as "
        "far as they are certain. \"Whatever is on the screen\": nothing, Claude finds out from the screen.",
        other_games_database(),
        LockMode::LOCK_WHILE_RUNNING,
        GameId::OTHER_GAMES
    )
    , WHO()
    , GOAL(
        "<b>Goal:</b><br>What Claude should do, in your own words (any language). Say where the game is "
        "at, if that helps, and when the goal is reached. (Not used when \"Claude Code plays\": give the "
        "goal to Claude Code.)",
        LockMode::LOCK_WHILE_RUNNING,
        "Look at the screen and say which game it shows, where it is at and what could be done from here. "
        "Do not press anything.",
        "For example: Open the menu, look at the first Pokemon of the party and tell me its moves."
    )
    , ABOUT(
        game_profile(game).name.empty()
            ? "<b>About the game (optional):</b><br>Which game it is and what Claude should know about it: "
              "its controls, where the save is, what to stay away from. Without it Claude finds out from the "
              "screen."
            : "<b>About the game (optional):</b><br>What Claude should know on top of what the program "
              "tells it about this game: where the save is, what to stay away from.",
        LockMode::LOCK_WHILE_RUNNING,
        "",
        "For example: The player is in the first town, right after the tutorial."
    )
    , TEXT_LANGUAGE(
        "<b>Language of the text:</b><br>The language of the text in the game. The program reads text from "
        "the screen (the tool \"read_text\") in this language, and Claude is told which it is. Claude reads "
        "the pictures it asks for in any language.",
        LanguageSet{
            Language::English, Language::Japanese, Language::Spanish, Language::French, Language::German,
            Language::Italian, Language::Korean, Language::ChineseSimplified, Language::ChineseTraditional,
        },
        LockMode::LOCK_WHILE_RUNNING,
        true
    )
    , MODEL(
        "<b>Model:</b><br>(Only when the program asks Claude.) The smallest model is the fastest and by far the cheapest, and enough for simple "
        "goals. A larger one finds its way better, most of all in a 3D game, and costs many times more.",
        {
            {Model::HAIKU,  "haiku",    "Claude Haiku 5.5 (fastest, cheapest)"},
            {Model::SONNET, "sonnet",   "Claude Sonnet 5.5 (about 20 times the price)"},
            {Model::OPUS,   "opus",     "Claude Opus 5.5 (about 40 times the price)"},
            {Model::FABLE,  "fable",    "Claude Fable 5.2 (about 80 times the price)"},
        },
        LockMode::LOCK_WHILE_RUNNING,
        Model::HAIKU
    )
    , MAX_ACTIONS(
        "<b>Stop after actions:</b><br>An action is one thing Claude has the program do: a look, a reading, "
        "some button presses, a wait.",
        LockMode::LOCK_WHILE_RUNNING,
        100, 1, 100000
    )
    , MAX_COST(
        "<b>Stop at a cost of (US dollars):</b><br>(Only when the program asks Claude.) Estimated from Anthropic's public prices; the invoice is "
        "what counts. 0: no limit. A spending limit in Anthropic's console holds whatever this program does.",
        LockMode::LOCK_WHILE_RUNNING,
        0.50, 0, 1000
    )
    , PICTURE(
        "<b>Pictures for Claude:</b><br>Of the whole screen. Larger pictures show more and cost more tokens "
        "each. A part of the screen comes at twice the detail whatever is chosen here, and text is cheaper "
        "read than looked at.",
        {
            {Picture::SMALL,    "small",    "384 x 216 (about 112 tokens a picture)"},
            {Picture::NORMAL,   "normal",   "640 x 360 (about 299 tokens)"},
            {Picture::LARGE,    "large",    "960 x 540 (about 700 tokens)"},
        },
        LockMode::LOCK_WHILE_RUNNING,
        Picture::NORMAL
    )
    , ALLOW_SAVE(
        game_profile(game).save_routine
            ? "<b>Claude may save the game:</b><br>Off: Claude is told not to save. On: it saves with the "
              "routine of this game's other programs, when the goal asks for it. Either way Claude presses "
              "the buttons, and many games save by themselves: keep a save of your own."
            : "<b>Claude may save the game:</b><br>Off: Claude is told not to save. Either way Claude presses "
              "the buttons, and many games save by themselves: keep a save of your own.",
        LockMode::LOCK_WHILE_RUNNING,
        false
    )
    , ALLOW_HOME(
        "<b>Claude may press HOME:</b><br>HOME leaves the game for the console's menu, where other games, "
        "the settings and the shop are. Off: the program does not press it, whatever Claude asks for.",
        LockMode::LOCK_WHILE_RUNNING,
        false
    )
    , OVERLAY_NOTES(
        "<b>Show what Claude does on the video:</b><br>What Claude says and each action, in the log on the "
        "video (turn on \"Log\" above the video). The program's own log has all of it either way.",
        LockMode::LOCK_WHILE_RUNNING,
        true
    )
    , MEASURE_TIMING(
        "<b>Measure the timing first:</b><br>With a menu on the screen that DOWN and UP move in. Before "
        "Claude starts, the program presses DOWN and UP a few times (the cursor ends where it was) and "
        "measures how late the picture shows a press and how short a press can be. That timing is used for "
        "this session and is in the log: put it in the two boxes below to keep it.",
        LockMode::LOCK_WHILE_RUNNING,
        false
    )
    , PRESS_MS(
        "<b>Press of a direction (ms):</b><br>How long UP, DOWN, LEFT and RIGHT are held; a button is held 30 "
        "ms longer. 0: the console's own (in the log at the start). Shorter is faster, but a press that is too "
        "short does not arrive.",
        LockMode::LOCK_WHILE_RUNNING,
        0, 0, 500
    )
    , VIDEO_DELAY_MS(
        "<b>Extra wait for the picture (ms):</b><br>How much longer the program waits after an action before "
        "it looks whether the picture changed: for a picture that comes late (Remote Play, an HDMI adapter). "
        "0: the console's own.",
        LockMode::LOCK_WHILE_RUNNING,
        0, 0, 1000
    )
    , NOTIFICATIONS({
        &NOTIFICATION_PROGRAM_FINISH,
        &NOTIFICATION_ERROR_FATAL,
    })
{
    PA_ADD_STATIC(SETUP_TEXT);
    if (m_game == GameId::OTHER_GAMES){
        PA_ADD_OPTION(GAME);
    }
    add_option(WHO.PLAYER, "PLAYER");
    add_option(WHO.PORT, "MCP_PORT");
    add_option(WHO.IDLE, "MCP_IDLE");
    PA_ADD_OPTION(GOAL);
    PA_ADD_OPTION(ABOUT);
    PA_ADD_OPTION(TEXT_LANGUAGE);
    PA_ADD_OPTION(MODEL);
    PA_ADD_OPTION(MAX_ACTIONS);
    PA_ADD_OPTION(MAX_COST);
    PA_ADD_OPTION(PICTURE);
    PA_ADD_OPTION(ALLOW_SAVE);
    PA_ADD_OPTION(ALLOW_HOME);
    PA_ADD_OPTION(OVERLAY_NOTES);
    PA_ADD_OPTION(MEASURE_TIMING);
    PA_ADD_OPTION(PRESS_MS);
    PA_ADD_OPTION(VIDEO_DELAY_MS);
    PA_ADD_OPTION(NOTIFICATIONS);
}


void GameProgram::program(SingleSwitchProgramEnvironment& env, CancellableScope& scope){
    GameProgram_Descriptor::Stats& stats = env.current_stats<GameProgram_Descriptor::Stats>();
    //  In Other Games, the game that was picked there.
    const GameId selected = m_game == GameId::OTHER_GAMES ? (GameId)GAME : m_game;
    const GameProfile& profile = game_profile(selected);

    env.log(
        PROGRAM_NAME + " build " + PROGRAM_BUILD + " (Claude Plays: " +
        (selected == GameId::OTHER_GAMES ? std::string(OTHER_GAMES_LIST) : profile.name) + ", experimental)",
        COLOR_BLUE
    );

    //  Claude Code plays: it has its own goal, and the program has no key to
    //  ask for.
    const bool external = WHO.claude_code();
    const std::string goal = trimmed(GOAL);
    if (!external){
        if (goal.empty()){
            throw UserSetupError(env.console, "Write down a goal for Claude first.");
        }
        const std::string unavailable = PlaySession::why_unavailable(scope);
        if (!unavailable.empty()){
            throw UserSetupError(env.console, unavailable);
        }
    }

    AnyGameOptions options;
    switch ((Picture)PICTURE){
    case Picture::SMALL:
        options.picture_width = 384;
        options.picture_height = 216;
        break;
    case Picture::NORMAL:
        options.picture_width = 640;
        options.picture_height = 360;
        break;
    case Picture::LARGE:
        options.picture_width = 960;
        options.picture_height = 540;
        break;
    }
    options.allow_save = ALLOW_SAVE;
    options.allow_home = ALLOW_HOME;
    options.external = external;
    options.readers = profile.pad == PadKind::PRO_CONTROLLER && game_has_readers(selected);
    //  What differs on this console: how presses are played, how late the
    //  picture comes, and what part of the capture is the game.
    const ConsoleTraits& traits = console_traits(profile.console);
    options.timing = traits.timing;
    options.picture_aspects = traits.picture_aspects;
    //  Set by hand.
    const uint32_t press_ms = PRESS_MS;
    const uint32_t video_delay_ms = VIDEO_DELAY_MS;
    if (press_ms > 0){
        options.timing.direction_ms = (int)press_ms;
        options.timing.press_ms = (int)press_ms + 30;
    }
    if (video_delay_ms > 0){
        options.timing.video_delay_ms = (int)video_delay_ms;
    }
    env.log(
        "Console " + traits.code + ": " + timing_text(options.timing) +
        (press_ms > 0 || video_delay_ms > 0 ? " (set by hand). " : ". ") + traits.why
    );
    const bool measure_timing = MEASURE_TIMING;

    GameFacts facts;
    facts.name = profile.name;
    facts.notes = profile.notes;
    facts.user_notes = trimmed(ABOUT);
    const Language text_language = TEXT_LANGUAGE;
    if (text_language != Language::English){
        facts.text_language = language_data(text_language).name;
    }
    //  A Japanese PlayStation game: CIRCLE is yes.
    if (text_language == Language::Japanese){
        facts.yes_no = japanese_yes_no(profile.pad);
    }

    Limits limits;
    limits.max_actions = (uint64_t)(uint32_t)MAX_ACTIONS;
    limits.max_cost = MAX_COST;
    const Model model = MODEL;

    //  The session, on the game's controller.
    auto session = [&](PlayConsole& console, CancellableScope& controller){
        ProgramHost host(env, controller, stats, OVERLAY_NOTES);
        AnyGameOptions session_options = options;
        if (measure_timing){
            host.show("Measuring the timing (DOWN and UP in the menu)...", COLOR_PURPLE);
            ConsoleProbe probe(console);
            const Calibration measured = calibrate(probe);
            env.log("Timing: " + measured.report, measured.measured ? COLOR_BLUE : COLOR_ORANGE);
            if (measured.measured){
                session_options.timing = calibrated_timing(options.timing, measured);
                env.log(
                    "Timing from the measurement: " + timing_text(session_options.timing) + ". To keep it: "
                    "press of a direction " + std::to_string(session_options.timing.direction_ms) +
                    " ms, extra wait for the picture " + std::to_string(session_options.timing.video_delay_ms) +
                    " ms.",
                    COLOR_BLUE
                );
            }
            host.show("Timing: " + measured.report, measured.measured ? COLOR_GREEN : COLOR_ORANGE);
        }
        AnyGame game(console, facts, session_options);
        if (external){
            const Ending ending = serve_claude_code(env.console, host, game, WHO, limits);
            env.log("Claude Plays: " + ending.summary, ending.reached ? COLOR_BLUE : COLOR_ORANGE);
            host.show(ending.summary, ending.reached ? COLOR_GREEN : COLOR_ORANGE);
            send_program_finished_notification(env, NOTIFICATION_PROGRAM_FINISH, ending.summary);
            return;
        }
        PlaySession claude(make_setup(game, model));
        env.log(
            std::string("Claude Plays: ") + model_id(model) + ", at most " + std::to_string(limits.max_actions) +
            " actions" + (limits.max_cost > 0 ? ", at most about " + money(limits.max_cost) : std::string(", no cost limit")) +
            ". Goal: " + one_line(goal, 300),
            COLOR_BLUE
        );
        host.show("Claude plays: " + goal, COLOR_GREEN);

        const Ending ending = play(host, game, claude, goal, limits);
        if (ending.failed){
            throw OperationFailedException(ErrorReportMode::NO_ERROR_REPORT, ending.summary);
        }
        env.log("Claude Plays: " + ending.summary, ending.reached ? COLOR_BLUE : COLOR_ORANGE);
        host.show(ending.summary, ending.reached ? COLOR_GREEN : COLOR_ORANGE);
        send_program_finished_notification(env, NOTIFICATION_PROGRAM_FINISH, ending.summary);
    };

    if (profile.pad == PadKind::IPHONE_KEYBOARD){
        StandardHid::KeyboardContext context(scope, env.console.controller<StandardHid::Keyboard>());
        if (!context->is_ready()){
            throw UserSetupError(context->logger(), "Controller is not ready.");
        }
        KeyboardConsole console(env, context, text_language);
        session(console, context);
    }else if (
        profile.pad == PadKind::XBOX360_CONTROLLER || profile.pad == PadKind::PS4_CONTROLLER ||
        profile.pad == PadKind::XBOXONE_CONTROLLER || profile.pad == PadKind::PSCLASSIC_CONTROLLER
    ){
        //  The Xbox 360 and the PlayStation Classic (OGX-Mini) and Remote
        //  Play: the wired controller.
        ProController& controller = env.console.controller<ProController>();
        if (dynamic_cast<PABotBase2_WiredController*>(&controller) == nullptr){
            throw UserSetupError(
                env.console,
                profile.pad == PadKind::XBOX360_CONTROLLER || profile.pad == PadKind::PSCLASSIC_CONTROLLER
                    ? "The Pico with OGX-Mini takes a Switch pad: pick NS1: Wired Controller as the type of the "
                      "controller (on a wired board, the ESP32-S3)."
                    : "The Remote Play client takes a plain USB gamepad: pick NS1: Wired Controller as the type of "
                      "the controller (on a wired board, the ESP32-S3)."
            );
        }
        ProControllerContext context(scope, controller);
        if (!context->is_ready()){
            throw UserSetupError(context->logger(), "Controller is not ready.");
        }
        WiredPadConsole console(
            env, context, text_language, pad_layout(profile.pad),
            profile.pad == PadKind::PS4_CONTROLLER ? &ps4_button_of
            //  OGX-Mini passes the Switch pad on by the places of the buttons,
            //  as the PlayStation 3 takes it (B is CROSS: its mode is START and
            //  B on a Switch pad, START and CROSS on a PlayStation pad).
            : profile.pad == PadKind::PSCLASSIC_CONTROLLER ? &ps3_button_of
            : &xbox360_button_of
        );
        session(console, context);
    }else if (profile.pad == PadKind::PS3_CONTROLLER || profile.pad == PadKind::XBOX_CONTROLLER){
        const bool xbox = profile.pad == PadKind::XBOX_CONTROLLER;
        ProController& controller = env.console.controller<ProController>();
        if (dynamic_cast<PABotBase2_WiredController*>(&controller) == nullptr){
            throw UserSetupError(
                env.console,
                xbox
                    ? "The Pico with OGX-Mini takes a Switch pad: pick NS1: Wired Controller as the type of the "
                      "controller (on a wired board, the ESP32-S3)."
                    : "A PlayStation 3 takes a plain USB gamepad: pick NS1: Wired Controller as the type of the "
                      "controller (on a wired board, the ESP32-S3)."
            );
        }
        ProControllerContext context(scope, controller);
        if (!context->is_ready()){
            throw UserSetupError(context->logger(), "Controller is not ready.");
        }
        WiredPadConsole console(
            env, context, text_language,
            pad_layout(profile.pad), xbox ? &xbox_button_of : &ps3_button_of
        );
        session(console, context);
    }else if (profile.console == "retro"){
        ProController& controller = env.console.controller<ProController>();
        //  The wireless Pro Controller of a Pico W, a Pico 2 W or an ESP32:
        //  BlueRetro takes a Bluetooth pad. (The wired types are another
        //  class; the wired Pro Controller is this one too, and cannot be
        //  told apart here: the setup steers to the wireless boards.)
        if (dynamic_cast<PABotBase2_ProController*>(&controller) == nullptr){
            throw UserSetupError(
                env.console,
                "A BlueRetro adapter takes a Bluetooth pad: pick NS1: Wireless Pro Controller as the type of "
                "the controller (on a wireless board: a Pico W, a Pico 2 W or an ESP32)."
            );
        }
        ProControllerContext context(scope, controller);
        if (!context->is_ready()){
            throw UserSetupError(context->logger(), "Controller is not ready.");
        }
        const PadKind pad = profile.pad;
        WiredPadConsole console(
            env, context, text_language, pad_layout(pad),
            pad == PadKind::GAMECUBE_CONTROLLER ? &gamecube_button_of
            : pad == PadKind::N64_CONTROLLER ? &n64_button_of
            : pad == PadKind::DREAMCAST_CONTROLLER ? &dreamcast_button_of
            : &ps3_button_of,
            pad == PadKind::N64_CONTROLLER ? &n64_stick_of : nullptr
        );
        session(console, context);
    }else if (profile.pad == PadKind::RIGHT_JOYCON){
        JoyconContext context(scope, env.console.controller<RightJoycon>());
        if (!context->is_ready()){
            throw UserSetupError(context->logger(), "Controller is not ready.");
        }
        JoyconConsole console(env, context, text_language);
        session(console, context);
    }else{
        ProControllerContext context(scope, env.console.controller<ProController>());
        if (!context->is_ready()){
            throw UserSetupError(context->logger(), "Controller is not ready.");
        }
        ProConsole console(env, context, selected, text_language);
        session(console, context);
    }
}



namespace{

//  The picture of the list "Other Games": a controller, in the size and
//  shape of the pictures of the other lists. On a ground of its own, in the
//  color of the list's cartridge (ClaudeGG_Home.cpp): in the list of
//  games of the light themes a white controller alone is not seen.
ImageRGB32 other_games_picture(){
    QImage image(256, 128, QImage::Format_ARGB32);
    image.fill(Qt::transparent);
    {
        QPainter painter(&image);
        painter.setRenderHint(QPainter::Antialiasing, true);
        painter.setPen(Qt::NoPen);

        painter.setBrush(QColor(0x5a, 0x55, 0xb8));
        painter.drawRoundedRect(QRectF(0, 0, 256, 128), 16, 16);

        //  The body: a bar with two grips.
        const QColor body(0xf2, 0xf3, 0xf7);
        painter.setBrush(body);
        painter.drawRoundedRect(QRectF(48, 34, 160, 58), 26, 26);
        painter.drawEllipse(QPointF(70, 78), 30, 28);
        painter.drawEllipse(QPointF(186, 78), 30, 28);

        //  The d-pad and the left stick.
        const QColor dark(0x2b, 0x30, 0x40);
        painter.setBrush(dark);
        painter.drawRoundedRect(QRectF(68, 50, 9, 27), 2, 2);
        painter.drawRoundedRect(QRectF(59, 59, 27, 9), 2, 2);
        painter.drawEllipse(QPointF(104, 80), 9, 9);
        //  The right stick.
        painter.drawEllipse(QPointF(152, 80), 9, 9);

        //  The four buttons.
        const QPointF centers[4] = {
            QPointF(183, 49), QPointF(197, 63), QPointF(169, 63), QPointF(183, 77),
        };
        for (const QPointF& center : centers){
            painter.drawEllipse(center, 6.5, 6.5);
        }
    }
    return QImage_to_ImageRGB32(std::move(image));
}

}


namespace{

//  The ground of a game's card.
QRgb card_ground(GameId game){
    switch (game){
    case GameId::OCTOPATH_TRAVELER_0:
        return qRgb(0x7a, 0x5c, 0x2e);
    case GameId::MARIO_KART_8_DELUXE:
        return qRgb(0xb3, 0x34, 0x2f);
    case GameId::SPLATOON_3:
        return qRgb(0x9a, 0x2f, 0x8c);
    case GameId::ANIMAL_CROSSING_NEW_HORIZONS:
        return qRgb(0x3a, 0x86, 0x58);
    case GameId::PLAYSTATION_3:
        return qRgb(0x2a, 0x4f, 0x9a);
    case GameId::ORIGINAL_XBOX:
        return qRgb(0x3c, 0x7a, 0x34);
    case GameId::PLAYSTATION_1:
        return qRgb(0x5a, 0x5e, 0x6e);
    case GameId::PLAYSTATION_2:
        return qRgb(0x23, 0x35, 0x7a);
    case GameId::GAMECUBE:
        return qRgb(0x5b, 0x3f, 0x96);
    case GameId::NINTENDO_64:
        return qRgb(0x2f, 0x6b, 0x4a);
    case GameId::DREAMCAST:
        return qRgb(0xc0, 0x5a, 0x1e);
    case GameId::XBOX_360:
        return qRgb(0x5c, 0x9a, 0x2a);
    case GameId::PS_REMOTE_PLAY:
        return qRgb(0x1f, 0x3f, 0x8a);
    case GameId::XBOX_REMOTE_PLAY:
        return qRgb(0x1e, 0x6b, 0x2e);
    case GameId::IPHONE:
        return qRgb(0x4a, 0x4a, 0x52);
    case GameId::PS_CLASSIC:
        return qRgb(0x6a, 0x6e, 0x7c);
    default:
        return qRgb(0x44, 0x4a, 0x5c);
    }
}

}

//  The Switch button that a button of a pad is played with, by the names of
//  that pad (for the program Macro, ClaudeGG_Macro.h): the tables above, as
//  the program picks them for each pad.
bool button_of_pad(PadKind pad, const std::string& name, Button& button){
    switch (pad){
    case PadKind::PRO_CONTROLLER:
    case PadKind::RIGHT_JOYCON:
        return button_of(name, button);
    case PadKind::PS3_CONTROLLER:
    case PadKind::PS1_CONTROLLER:
    case PadKind::PS2_CONTROLLER:
    case PadKind::PSCLASSIC_CONTROLLER:
        return ps3_button_of(name, button);
    case PadKind::PS4_CONTROLLER:
        return ps4_button_of(name, button);
    case PadKind::XBOX_CONTROLLER:
        return xbox_button_of(name, button);
    case PadKind::XBOX360_CONTROLLER:
    case PadKind::XBOXONE_CONTROLLER:
        return xbox360_button_of(name, button);
    case PadKind::GAMECUBE_CONTROLLER:
        return gamecube_button_of(name, button);
    case PadKind::N64_CONTROLLER:
        return n64_button_of(name, button);
    case PadKind::DREAMCAST_CONTROLLER:
        return dreamcast_button_of(name, button);
    case PadKind::IPHONE_KEYBOARD:
        break;
    }
    return false;
}


GameOnlyList::GameOnlyList(GameId game)
    : PanelListDescriptor(game_profile(game).title)
    , m_game(game)
{
    m_icon = QImage_to_ImageRGB32(make_game_card(game_profile(game).title, card_ground(game)));
}

std::vector<PanelEntry> GameOnlyList::make_panels() const{
    std::vector<PanelEntry> ret;
    ret.emplace_back("---- Claude ----");
    ret.emplace_back(make_claude_plays(m_game));
    add_macro(ret, m_game);
    return ret;
}


OtherGamesList::OtherGamesList()
    : PanelListDescriptor(OTHER_GAMES_LIST)
{
    m_icon = other_games_picture();
}

std::vector<PanelEntry> OtherGamesList::make_panels() const{
    std::vector<PanelEntry> ret;
    ret.emplace_back("---- Claude ----");
    ret.emplace_back(make_claude_plays(GameId::OTHER_GAMES));
    add_macro(ret, GameId::OTHER_GAMES);
    return ret;
}



}
}
}
