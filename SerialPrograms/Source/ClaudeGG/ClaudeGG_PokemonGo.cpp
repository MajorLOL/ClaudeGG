/*  Claude GG Pokemon GO (the programs of the phone)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <chrono>
#include <QImage>
#include <QPainter>
#include <QRegularExpression>
#include <QString>
#include <QStringList>
#include "Common/Cpp/CancellableScope.h"
#include "Common/Cpp/Exceptions.h"
#include "Common/Cpp/Options/BooleanCheckBoxOption.h"
#include "Common/Cpp/Options/EnumDropdownOption.h"
#include "Common/Cpp/Options/SimpleIntegerOption.h"
#include "Common/Cpp/Options/StaticTextOption.h"
#include "Common/Cpp/Options/StringOption.h"
#include "CommonFramework/GlobalSettingsPanel.h"
#include "CommonFramework/ImageTypes/ImageRGB32_Qt.h"
#include "ComputerPrograms/ComputerProgram.h"
#include "Pokemon/Pokemon_Strings.h"
#include "ClaudeGG_Mobile.h"
#include "ClaudeGG_PokemonGo.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{


namespace{


//  What a program is: the bot's switches that it turns on (all the others it
//  turns off), and which options it shows.
struct Preset{
    const char* identifier;
    const char* name;
    const char* description;
    bool spin;
    bool catching;
    bool gifts;
    bool daily;
    bool rocket;
    bool quests;
};

const Preset PRESETS[] = {
    {
        "ClaudeGG:PokemonGO:Spin", "Spin PokéStops",
        "Spins the PokéStops that the trainer stands at and walks to the next ones, with the Pokémon GO bot on the "
        "Raspberry Pi of the phone. Pokémon GO must be on the map. Claude GG starts the bot, shows what it writes "
        "and stops it when this program is stopped.",
        true, false, false, false, false, false,
    },
    {
        "ClaudeGG:PokemonGO:Catch", "Catch Pokémon",
        "Catches the wild Pokémon that show up on the map, with the Pokémon GO bot on the Raspberry Pi of the "
        "phone. Pokémon GO must be on the map. Claude GG starts the bot, shows what it writes and stops it when "
        "this program is stopped.",
        false, true, false, false, false, false,
    },
    {
        "ClaudeGG:PokemonGO:SpinAndCatch", "Spin PokéStops and catch Pokémon",
        "Spins the PokéStops and catches the Pokémon that show up, with the Pokémon GO bot on the Raspberry Pi of "
        "the phone. Pokémon GO must be on the map. Claude GG starts the bot, shows what it writes and stops it "
        "when this program is stopped.",
        true, true, false, false, false, false,
    },
    {
        "ClaudeGG:PokemonGO:Gifts", "Gifts",
        "Opens the gifts that friends sent and sends gifts to friends, with the Pokémon GO bot on the Raspberry Pi "
        "of the phone.",
        false, false, true, false, false, false,
    },
    {
        "ClaudeGG:PokemonGO:Daily", "Daily run",
        "The whole day's play in one: at the time you give, both Pokémon GO apps one after the other (spin, catch, "
        "gifts), each until it is full or the time is up. The program stays and waits for the next day until it "
        "is stopped.",
        true, true, true, true, false, false,
    },
    {
        "ClaudeGG:PokemonGO:Rocket", "Team GO Rocket battles",
        "Spins PokéStops and battles the Team GO Rocket grunts and leaders that show up there, with the "
        "recommended party (a missing third Pokémon is chosen); the Shadow Pokémon is caught afterwards. "
        "Experimental: not tried on a phone with Claude GG yet.",
        true, false, false, false, true, false,
    },
    {
        "ClaudeGG:PokemonGO:Quests", "Claim GO Pass rewards",
        "Spins PokéStops, catches Pokémon, and claims the GO Pass rewards whenever the quest button on the map "
        "turns gold (a Pokémon as a reward is caught). Experimental: not tried on a phone with Claude GG yet.",
        true, true, false, false, false, true,
    },
};
constexpr size_t PRESET_COUNT = sizeof(PRESETS) / sizeof(PRESETS[0]);


enum class Throw{
    REALISTIC,
    OFF,
    NICE,
    GREAT,
    EXCELLENT,
};

const char* throw_slug(Throw value){
    switch (value){
    case Throw::OFF:        return "off";
    case Throw::NICE:       return "nice";
    case Throw::GREAT:      return "great";
    case Throw::EXCELLENT:  return "excellent";
    case Throw::REALISTIC:  break;
    }
    return "realistic";
}

const QRegularExpression& time_pattern(){
    static const QRegularExpression pattern("^([01]\\d|2[0-3]):[0-5]\\d$");
    return pattern;
}


class GoProgram_Descriptor : public ComputerProgramDescriptor{
public:
    explicit GoProgram_Descriptor(const Preset& preset)
        : ComputerProgramDescriptor(
            preset.identifier,
            Pokemon::STRING_POKEMON + " GO", preset.name,
            "",
            preset.description,
            PanelQualityStanding::EXPERIMENTAL
        )
        , m_preset(preset)
    {}

    virtual std::unique_ptr<ComputerProgramInstance> make_instance() const override;

private:
    const Preset& m_preset;
};


class GoProgram : public ComputerProgramInstance{
public:
    explicit GoProgram(const Preset& preset)
        : m_preset(preset)
        , SETUP_TEXT(
            "<b>The phone:</b> Pokémon GO runs on the phone that is plugged into the Raspberry Pi (Settings, "
            "Phone, or the console choice). The bot on the Pi does the playing; this program starts it with the "
            "options below and stops it when you press Stop. Use a spare account: automation is against "
            "Niantic's Terms of Service."
        )
        , THROW_TARGET(
            "<b>Throw:</b><br>Where the ball is aimed. Realistic: like a person does, no matter what the ring "
            "says. The others aim for that kind of throw.",
            {
                {Throw::REALISTIC,  "realistic",    "Realistic"},
                {Throw::NICE,       "nice",         "Nice"},
                {Throw::GREAT,      "great",        "Great"},
                {Throw::EXCELLENT,  "excellent",    "Excellent"},
                {Throw::OFF,        "off",          "No aiming (a plain throw)"},
            },
            LockMode::LOCK_WHILE_RUNNING,
            Throw::REALISTIC
        )
        , CURVEBALL("Always throw a curveball", LockMode::LOCK_WHILE_RUNNING, false)
        , FAST_CATCH("Fast catch: after a clear hit press Back to skip the catch animation", LockMode::LOCK_WHILE_RUNNING, false)
        , BUDDY("My buddy walks along on the map", LockMode::LOCK_WHILE_RUNNING, false)
        , SPIN_ONLY_WHEN_FULL("Spin PokéStops when the Pokémon storage is full (catching pauses until there is room)", LockMode::LOCK_WHILE_RUNNING, false)
        , GIFTS_OPEN("Open gifts from friends", LockMode::LOCK_WHILE_RUNNING, true)
        , GIFTS_SEND("Send gifts to friends", LockMode::LOCK_WHILE_RUNNING, true)
        , DAILY_TIME(false, "<b>Daily start (HH:MM):</b><br>When the day's run begins.", LockMode::LOCK_WHILE_RUNNING, "08:00", "08:00")
        , DAILY_MAX_MIN(
            "<b>Stop after (minutes):</b><br>How long a run may take, all games together.",
            LockMode::LOCK_WHILE_RUNNING,
            480, 5, 1440
        )
        , DAILY_NOW("Begin a run right away (otherwise it waits for the daily start)", LockMode::LOCK_WHILE_RUNNING, true)
        , CLOSE_WHEN_FULL("Close the game when the Pokémon storage and the bag are both full", LockMode::LOCK_WHILE_RUNNING, true)
        , BAG_CLEAN("Clean up a full bag (discards the Potions, Super and Hyper Potions; keeps 30 Max Potion, 30 Max Revive, 400 Poké Ball, 100 Great Ball and 30 of each berry)", LockMode::LOCK_WHILE_RUNNING, true)
        , HEAT_PAUSE("Pause when the phone (43 °C) or the Pi (82 °C) gets too hot, until it has cooled down", LockMode::LOCK_WHILE_RUNNING, true)
        , LIVE_LOOK("Look with the live video of the phone (a picture in a tenth of a second instead of 1 to 3 s)", LockMode::LOCK_WHILE_RUNNING, true)
        , FAST_LOOK("Look around like a person", LockMode::LOCK_WHILE_RUNNING, true)
    {
        PA_ADD_OPTION(SETUP_TEXT);
        if (preset.catching){
            PA_ADD_OPTION(THROW_TARGET);
            PA_ADD_OPTION(CURVEBALL);
            PA_ADD_OPTION(FAST_CATCH);
            PA_ADD_OPTION(BUDDY);
        }
        if (preset.catching && preset.spin){
            PA_ADD_OPTION(SPIN_ONLY_WHEN_FULL);
        }
        if (preset.gifts && !preset.daily){
            PA_ADD_OPTION(GIFTS_OPEN);
            PA_ADD_OPTION(GIFTS_SEND);
        }
        if (preset.daily){
            PA_ADD_OPTION(DAILY_TIME);
            PA_ADD_OPTION(DAILY_MAX_MIN);
            PA_ADD_OPTION(DAILY_NOW);
        }
        PA_ADD_OPTION(CLOSE_WHEN_FULL);
        PA_ADD_OPTION(BAG_CLEAN);
        PA_ADD_OPTION(HEAT_PAUSE);
        PA_ADD_OPTION(LIVE_LOOK);
        PA_ADD_OPTION(FAST_LOOK);
    }

    virtual std::string check_validity() const override{
        if (m_preset.daily && !time_pattern().match(QString::fromStdString(std::string(DAILY_TIME)).trimmed()).hasMatch()){
            return "The daily start must be a time as HH:MM, like 08:00.";
        }
        return std::string();
    }

    //  What the bot is asked to do.
    MobileBotStart settings() const{
        MobileBotStart start;
        auto add = [&](const char* key, bool on){
            start.options.emplace_back(QString::fromLatin1(key), on);
        };
        add("spin", m_preset.spin);
        add("catch", m_preset.catching);
        add("gifts_open", m_preset.gifts && (m_preset.daily || (bool)GIFTS_OPEN));
        add("gifts_send", m_preset.gifts && (m_preset.daily || (bool)GIFTS_SEND));
        add("daily_cycle", m_preset.daily);
        add("rocket_fight", m_preset.rocket);
        add("quests", m_preset.quests);
        add("curveball", m_preset.catching && (bool)CURVEBALL);
        add("fast_catch", m_preset.catching && (bool)FAST_CATCH);
        add("buddy", m_preset.catching && (bool)BUDDY);
        add("spin_only_when_full", m_preset.catching && m_preset.spin && (bool)SPIN_ONLY_WHEN_FULL);
        add("close_when_full", (bool)CLOSE_WHEN_FULL);
        add("bag_clean", (bool)BAG_CLEAN);
        add("heat_pause", (bool)HEAT_PAUSE);
        add("live_look", (bool)LIVE_LOOK);
        add("fast_look", (bool)FAST_LOOK);
        if (m_preset.catching){
            start.throw_target = QString::fromLatin1(throw_slug(THROW_TARGET.get()));
        }
        if (m_preset.daily){
            start.daily_time = QString::fromStdString(std::string(DAILY_TIME)).trimmed();
            start.daily_max_min = (int)DAILY_MAX_MIN.current_value();
            start.daily_now = (bool)DAILY_NOW;
        }
        return start;
    }

    virtual void program(ProgramEnvironment& env, CancellableScope& scope) override{
        GlobalSettings& global = GlobalSettings::instance();
        const QString host = QString::fromStdString(std::string(global.MOBILE_HOST)).trimmed();
        const int port = (int)global.MOBILE_PORT.current_value();
        if (host.isEmpty()){
            throw UserSetupError(env.logger(), "The address of the Raspberry Pi is not set. Pick the Android phone as the console and fill in the Raspberry Pi (Settings).");
        }
        const MobileAgent agent(host, port, mobile_token());
        const std::string where = host.toStdString() + ":" + std::to_string(port);

        QString error;
        MobileBotState state;
        if (!agent.bot_state(state, 5, &error)){
            throw UserSetupError(env.logger(), "Cannot reach the Raspberry Pi at " + where + ": " + error.toStdString());
        }
        if (!state.installed){
            throw UserSetupError(env.logger(), "The Pokémon GO bot is not installed on the Raspberry Pi (Mobile/install.sh installs it).");
        }
        //  Only what the bot writes from now on is shown.
        QString last = state.log.isEmpty() ? QString() : state.log.back();
        if (state.running){
            env.log("The bot runs already: it is started again with the options of this program.");
        }

        if (!agent.bot_start(settings(), &error)){
            throw UserSetupError(env.logger(), "The bot could not be started: " + error.toStdString());
        }
        env.log(std::string("The Pokémon GO bot on the Raspberry Pi (") + where + ") is started: " + m_preset.name + ".");

        try{
            int not_running = 0;
            int unreachable = 0;
            while (true){
                scope.wait_for(std::chrono::milliseconds(3000));
                if (!agent.bot_state(state, 80, &error)){
                    if (++unreachable >= 5){
                        throw UserSetupError(
                            env.logger(),
                            "The Raspberry Pi does not answer (" + error.toStdString() + "). The bot may still run there."
                        );
                    }
                    continue;
                }
                unreachable = 0;

                //  The lines after the last one that was shown (all of them when it is not in the log any more).
                qsizetype from = 0;
                if (!last.isEmpty()){
                    for (qsizetype c = state.log.size(); c > 0; c--){
                        if (state.log[c - 1] == last){
                            from = c;
                            break;
                        }
                    }
                }
                for (qsizetype c = from; c < state.log.size(); c++){
                    env.log(state.log[c].toStdString());
                }
                if (!state.log.isEmpty()){
                    last = state.log.back();
                }

                //  The bot ended by itself (the game was closed, the time was up): so does the program.
                not_running = state.running ? 0 : not_running + 1;
                if (not_running >= 2){
                    env.log("The bot has stopped.");
                    return;
                }
            }
        }catch (OperationCancelledException&){
            QString stop_error;
            if (agent.bot_stop(&stop_error)){
                env.log("The bot on the Raspberry Pi is stopped.");
            }else{
                env.log("The bot could not be stopped: " + stop_error.toStdString(), COLOR_RED);
            }
            throw;
        }
    }

    //  For the test: the switches that the program asks for.
    std::vector<std::pair<std::string, bool>> switches() const{
        std::vector<std::pair<std::string, bool>> list;
        for (const std::pair<QString, bool>& option : settings().options){
            list.emplace_back(option.first.toStdString(), option.second);
        }
        return list;
    }

private:
    const Preset& m_preset;
    StaticTextOption SETUP_TEXT;
    EnumDropdownOption<Throw> THROW_TARGET;
    BooleanCheckBoxOption CURVEBALL;
    BooleanCheckBoxOption FAST_CATCH;
    BooleanCheckBoxOption BUDDY;
    BooleanCheckBoxOption SPIN_ONLY_WHEN_FULL;
    BooleanCheckBoxOption GIFTS_OPEN;
    BooleanCheckBoxOption GIFTS_SEND;
    StringOption DAILY_TIME;
    SimpleIntegerOption<uint32_t> DAILY_MAX_MIN;
    BooleanCheckBoxOption DAILY_NOW;
    BooleanCheckBoxOption CLOSE_WHEN_FULL;
    BooleanCheckBoxOption BAG_CLEAN;
    BooleanCheckBoxOption HEAT_PAUSE;
    BooleanCheckBoxOption LIVE_LOOK;
    BooleanCheckBoxOption FAST_LOOK;
};

std::unique_ptr<ComputerProgramInstance> GoProgram_Descriptor::make_instance() const{
    return std::make_unique<GoProgram>(m_preset);
}


//  A Poké Ball on the blue and the red of the cartridge's label (the label takes
//  those colors itself, ClaudeGG_Home.cpp): the picture is the ball alone.
ImageRGB32 pokemon_go_picture(){
    QImage image(256, 128, QImage::Format_ARGB32);
    image.fill(Qt::transparent);
    {
        QPainter painter(&image);
        painter.setRenderHint(QPainter::Antialiasing, true);
        const QPointF center(128, 64);
        const double radius = 52;
        painter.setPen(Qt::NoPen);
        painter.setBrush(QColor(0xff, 0xff, 0xff));
        painter.drawEllipse(center, radius, radius);
        //  The red half.
        painter.setBrush(QColor(0xe6, 0x39, 0x46));
        painter.drawChord(QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius), 0, 180 * 16);
        //  The band and the button.
        painter.setBrush(QColor(0x22, 0x25, 0x30));
        painter.drawRect(QRectF(center.x() - radius, center.y() - 5, 2 * radius, 10));
        painter.drawEllipse(center, 17, 17);
        painter.setBrush(QColor(0xff, 0xff, 0xff));
        painter.drawEllipse(center, 10, 10);
        //  The outline.
        painter.setBrush(Qt::NoBrush);
        painter.setPen(QPen(QColor(0x22, 0x25, 0x30), 5));
        painter.drawEllipse(center, radius, radius);
    }
    return QImage_to_ImageRGB32(std::move(image));
}


}   //  namespace


PokemonGoList::PokemonGoList()
    : PanelListDescriptor(Pokemon::STRING_POKEMON + " GO")
{
    m_icon = pokemon_go_picture();
}

std::vector<PanelEntry> PokemonGoList::make_panels() const{
    std::vector<PanelEntry> ret;
    ret.emplace_back("---- " + Pokemon::STRING_POKEMON + " GO ----");
    for (const Preset& preset : PRESETS){
        ret.emplace_back(std::make_unique<GoProgram_Descriptor>(preset));
    }
    return ret;
}

size_t pokemon_go_program_count(){
    return PRESET_COUNT;
}

std::vector<std::pair<std::string, bool>> pokemon_go_switches(const std::string& program){
    for (const Preset& preset : PRESETS){
        if (program == preset.name){
            return GoProgram(preset).switches();
        }
    }
    return {};
}


}
}
}
