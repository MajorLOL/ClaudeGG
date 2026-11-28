/*  Claude GG Pokemon GO (the programs of the phone)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <chrono>
#include <QDir>
#include <QFile>
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
#include "CommonFramework/GlobalAutoPaths.h"
#include "CommonFramework/GlobalSettingsPanel.h"
#include "CommonFramework/ImageTypes/ImageRGB32_Qt.h"
#include "ComputerPrograms/ComputerProgram.h"
#include "Pokemon/Pokemon_Strings.h"
#include "ClaudeGG_Mobile.h"
#include "ClaudeGG_PokemonGo.h"
#include "ClaudeGG_PokemonGoBot.h"
#include "ClaudeGG_PokemonGoChapter.h"
#include "ClaudeGG_PokemonGoFlow.h"
#include "ClaudeGG_PokemonGoPhone.h"
#include "ClaudeGG_PokemonGoText.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{


namespace{


//  What a program is. A SERVICE program starts the bot with some of its switches
//  on (all the others off) and stays while it runs; the others run one part of
//  the bot (a "test" of its chapters.py) and end with it.
enum class Kind{
    SERVICE,        //  spin, catch, gifts, the daily run, Rocket, GO Pass
    BATTLES,        //  a set of GO Battle League battles
    TEAMS,          //  your Pokémon and the teams of the leagues
    PART,           //  any one part of the bot
};

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
    Kind kind;
    bool choose = false;    //  Auto play: what it does (spin, catch, gifts, Rocket, GO Pass) is chosen with the options
};

//  Can Claude GG play this preset itself (the parts of gamebot.py that are ported to C++)?  Spinning PokéStops, catching Pokémon, the gifts,
//  the GO Pass rewards, the clean-up of a full bag, Team GO Rocket and the daily run (the apps of the phone one after the other, the battles
//  first); the weekly teams of the daily run are not ported yet.
bool claude_can_play(const Preset& preset){
    return preset.kind == Kind::SERVICE && (preset.spin || preset.catching || preset.gifts || preset.choose);
}

const Preset PRESETS[] = {
    {
        "ClaudeGG:PokemonGO:AutoPlay", "Auto play",
        "Plays Pokémon GO on its own with the Pokémon GO bot on the Raspberry Pi of the phone, the way you choose "
        "below: spin PokéStops, catch Pokémon, open and send gifts, battle Team GO Rocket and claim the GO Pass "
        "rewards, each on or off, with all the options of the catch, the bag and the look. It is the normal play "
        "of the bot's own web interface. Pokémon GO must be on the map. Claude GG starts the bot, shows what it "
        "writes and stops it when this program is stopped. Under Who plays Claude GG can play itself instead "
        "(experimental): spin, catch, gifts, Team GO Rocket and the GO Pass, with the clean-up of a full bag.",
        true, true, true, false, false, false, Kind::SERVICE, true,
    },
    {
        "ClaudeGG:PokemonGO:Spin", "Spin PokéStops",
        "Spins the PokéStops that the trainer stands at and walks to the next ones, with the Pokémon GO bot on the "
        "Raspberry Pi of the phone. Pokémon GO must be on the map. Claude GG starts the bot, shows what it writes "
        "and stops it when this program is stopped.",
        true, false, false, false, false, false, Kind::SERVICE,
    },
    {
        "ClaudeGG:PokemonGO:Catch", "Catch Pokémon",
        "Catches the wild Pokémon that show up on the map, with the Pokémon GO bot on the Raspberry Pi of the "
        "phone. Pokémon GO must be on the map. Claude GG starts the bot, shows what it writes and stops it when "
        "this program is stopped.",
        false, true, false, false, false, false, Kind::SERVICE,
    },
    {
        "ClaudeGG:PokemonGO:SpinAndCatch", "Spin PokéStops and catch Pokémon",
        "Spins the PokéStops and catches the Pokémon that show up, with the Pokémon GO bot on the Raspberry Pi of "
        "the phone. Pokémon GO must be on the map. Claude GG starts the bot, shows what it writes and stops it "
        "when this program is stopped.",
        true, true, false, false, false, false, Kind::SERVICE,
    },
    {
        "ClaudeGG:PokemonGO:Gifts", "Gifts",
        "Opens the gifts that friends sent and sends gifts to friends, with the Pokémon GO bot on the Raspberry Pi "
        "of the phone, or (under Who plays, experimental) with Claude GG itself.",
        false, false, true, false, false, false, Kind::SERVICE,
    },
    {
        "ClaudeGG:PokemonGO:Daily", "Daily run",
        "The whole day's play in one: at the time you give, both Pokémon GO apps one after the other (spin, catch, "
        "gifts), each until it is full or the time is up. Choose below to fight GO Battle League battles first, and "
        "to keep the teams up to date once a week. The program stays and waits for the next day until it is stopped.",
        true, true, true, true, false, false, Kind::SERVICE,
    },
    {
        "ClaudeGG:PokemonGO:Rocket", "Team GO Rocket battles",
        "Spins PokéStops and battles the Team GO Rocket grunts and leaders that show up there, with the "
        "recommended party (a missing third Pokémon is chosen); the Shadow Pokémon is caught afterwards. "
        "Experimental: not tried on a phone with Claude GG yet.",
        true, false, false, false, true, false, Kind::SERVICE,
    },
    {
        "ClaudeGG:PokemonGO:Quests", "Claim GO Pass rewards",
        "Spins PokéStops, catches Pokémon, and claims the GO Pass rewards whenever the quest button on the map "
        "turns gold (a Pokémon as a reward is caught), with the Pokémon GO bot on the Raspberry Pi of the phone, or "
        "(under Who plays, experimental) with Claude GG itself. Experimental: not tried on a phone with Claude GG yet.",
        true, true, false, false, false, true, Kind::SERVICE,
    },
    {
        "ClaudeGG:PokemonGO:Battles", "GO Battle League",
        "Fights GO Battle League battles on the phone of the Raspberry Pi: from the map to the party screen of the "
        "league (the rewards of a finished set and a new rank are collected on the way), the team of three, the "
        "fight (charged attacks, shields, switching, giving up a lost fight) and the result screen, as many battles "
        "as you set. Claude GG itself plays (the Pi only gives the picture and the taps; Tesseract must be installed "
        "on this computer), or, as before, the Python bot on the Pi. Pokémon GO must be on the map. Experimental: "
        "not tried on a real phone with Claude GG yet. Fighting real trainers with a bot is against Niantic's Terms "
        "of Service.",
        false, false, false, false, false, false, Kind::BATTLES,
    },
    {
        "ClaudeGG:PokemonGO:Teams", "Your Pokémon and teams",
        "Reads your Pokémon and works out the best team of three for each league (the PvPoke rankings, how the "
        "IVs fit the CP cap), with the Pokémon GO bot on the Raspberry Pi of the phone: the leagues of now, a tag "
        "per league, the scan of the Pokémon storage, shadow, lucky and purified, the teams, their moves and "
        "candy, and the tags of the team members. Pick the step; the weekly round does them all. Scanning "
        "everything takes an hour or more. Pokémon GO must be on the map. Experimental.",
        false, false, false, false, false, false, Kind::TEAMS,
    },
    {
        "ClaudeGG:PokemonGO:Part", "One part of the bot",
        "Runs one part of the Pokémon GO bot on its own, from the screen the game is on: a look at what the bot sees "
        "(no taps), the live video, one GO Battle League battle or the fight that is going on, a Team GO Rocket "
        "battle, one throw, the bag, the GO Pass rewards, the Pokémon storage, gifts. It is what Test in the bot's "
        "own web interface does; the settings that are not shown here stay as the bot has them. Under Who plays, "
        "Claude GG itself can run some of the parts (experimental): what the bot sees, normal play, catching, one "
        "throw, a Team GO Rocket battle and its fight, the bag, the GO Pass rewards and gifts.",
        false, false, false, false, false, false, Kind::PART,
    },
};
constexpr size_t PRESET_COUNT = sizeof(PRESETS) / sizeof(PRESETS[0]);


//  The parts of the bot that run on their own: the chapters of Mobile/chapters.py (the test of
//  the programs checks that the bot knows each of these keys).
struct Part{
    const char* key;
    const char* group;
    const char* title;
};
const char* const TEAMS_GROUP = "Your Pokémon and teams";
const Part PARTS[] = {
    {"screen",       "Checks",              "What the bot sees"},
    {"video",        "Checks",              "Live video"},
    {"look",         "Checks",              "Looking: video against screenshots"},
    {"checks",       "Checks",              "All checks without taps"},
    {"play",         "Checks",              "Normal play for 3 minutes"},
    {"battle_menu",  "GO Battle League",    "To the party screen"},
    {"battle_one",   "GO Battle League",    "One battle"},
    {"battle_fight", "GO Battle League",    "The fight on the screen"},
    {"battle_set",   "GO Battle League",    "All battles of the setting"},
    {"rocket",       "Team GO Rocket",      "Rocket battle"},
    {"rocket_fight", "Team GO Rocket",      "The Rocket fight on the screen"},
    {"leagues",      TEAMS_GROUP,           "Read the leagues of now"},
    {"tags",         TEAMS_GROUP,           "Make a tag for each league"},
    {"scan_test",    TEAMS_GROUP,           "Scan the first 5 Pokémon"},
    {"scan",         TEAMS_GROUP,           "Scan all your Pokémon"},
    {"scan_new",     TEAMS_GROUP,           "Scan the Pokémon of the last week"},
    {"scan_flags",   TEAMS_GROUP,           "Find shadow, lucky and purified"},
    {"teams",        TEAMS_GROUP,           "Make the teams"},
    {"check_team",   TEAMS_GROUP,           "Check the moves and candy of the teams"},
    {"tag_teams",    TEAMS_GROUP,           "Tag the team members"},
    {"refresh",      TEAMS_GROUP,           "The weekly round"},
    {"catch",        "Catching",            "Catch this Pokémon"},
    {"throw",        "Catching",            "One throw"},
    {"bag",          "Items and rewards",   "Clean up the bag"},
    {"quests",       "Items and rewards",   "Claim GO Pass rewards"},
    {"storage",      "Items and rewards",   "Pokémon storage: look"},
    {"gifts",        "Items and rewards",   "Gifts"},
};
constexpr size_t PART_COUNT = sizeof(PARTS) / sizeof(PARTS[0]);

size_t part_index(const char* key){
    for (size_t c = 0; c < PART_COUNT; c++){
        if (std::string(PARTS[c].key) == key){
            return c;
        }
    }
    return 0;
}

//  A list for a dropdown: the numbers of the parts are the values.
IntegerEnumDropdownDatabase part_database(bool teams_only){
    IntegerEnumDropdownDatabase database;
    for (size_t c = 0; c < PART_COUNT; c++){
        const bool teams = std::string(PARTS[c].group) == TEAMS_GROUP;
        if (teams_only && !teams){
            continue;
        }
        database.add(c, PARTS[c].key, teams_only ? PARTS[c].title : std::string(PARTS[c].group) + ": " + PARTS[c].title);
    }
    return database;
}


//  Who fights the GO Battle League battles: the C++ port in Claude GG (issue #31), or the Python bot on the Pi.
enum class Player{
    CLAUDE_GG,
    PI_BOT,
};

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

//  As the agent checks them (the bot reads them from its control file).
const QRegularExpression& league_pattern(){
    static const QRegularExpression pattern("^[A-Za-z0-9][A-Za-z0-9 '\\-]{0,39}$");
    return pattern;
}
const QRegularExpression& app_pattern(){
    static const QRegularExpression pattern("^(|com\\.nianticlabs\\.pokemongo[A-Za-z0-9._]{0,60})$");
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
        , PART_CHOICE(
            "<b>Part:</b><br>Which part of the bot to run, from the screen the game is on now.",
            part_database(false),
            LockMode::LOCK_WHILE_RUNNING,
            part_index("screen")
        )
        , TEAMS_CHOICE(
            "<b>Step:</b><br>What to do with your Pokémon. The weekly round does the leagues, the tags, the Pokémon "
            "of the last week, shadow, lucky and purified, the teams, their moves and candy, the tags and the "
            "battle team in one go.",
            part_database(true),
            LockMode::LOCK_WHILE_RUNNING,
            part_index("refresh")
        )
        , BATTLE_DAILY("Fight GO Battle League battles first in the daily run (the app below, then spin and catch)", LockMode::LOCK_WHILE_RUNNING, false)
        , TEAMS_WEEKLY("Keep the teams up to date: once a week the leagues, tags, new Pokémon and teams of each game", LockMode::LOCK_WHILE_RUNNING, false)
        , BATTLE_LEAGUE(
            false,
            "<b>League:</b><br>The league as the game names it (Great League, Ultra League, Master League, ...).",
            LockMode::LOCK_WHILE_RUNNING,
            "Great League", "Great League"
        )
        , BATTLE_COUNT(
            "<b>Battles:</b><br>How many battles in one run.",
            LockMode::LOCK_WHILE_RUNNING,
            5, 1, 50
        )
        , BATTLE_APP(
            false,
            "<b>Pokémon GO app:</b><br>Which of the Pokémon GO apps on the phone fights (each one is another "
            "account). Empty: the Play Store app. Otherwise the name of the app as the bot's web interface lists it, "
            "like com.nianticlabs.pokemongo.ares.",
            LockMode::LOCK_WHILE_RUNNING,
            "", "com.nianticlabs.pokemongo"
        )
        , PLAYER(
            "<b>Who plays:</b><br>Claude GG: this program looks at the phone and decides, the Pi only gives the "
            "picture and the taps (the team is taken from the bot on the Pi when it has one). The bot on the Pi: "
            "the Python bot plays, as before.",
            {
                {Player::CLAUDE_GG, "claudegg", "Claude GG (on this computer)"},
                {Player::PI_BOT,    "pi",       "The Python bot on the Raspberry Pi"},
            },
            LockMode::LOCK_WHILE_RUNNING,
            preset.kind == Kind::BATTLES ? Player::CLAUDE_GG : Player::PI_BOT      //  (spinning with Claude GG is new: the bot of the Pi stays the default)
        )
        , BATTLE_GIVE_UP("Give up a battle that is lost (when the last Pokémon cannot win any more)", LockMode::LOCK_WHILE_RUNNING, true)
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
        , SPIN_ON("Spin PokéStops", LockMode::LOCK_WHILE_RUNNING, true)
        , CATCH_ON("Catch wild Pokémon", LockMode::LOCK_WHILE_RUNNING, true)
        , ROCKET_ON("Team GO Rocket at a PokéStop: battle it with the recommended party (the Shadow Pokémon is caught afterwards)", LockMode::LOCK_WHILE_RUNNING, false)
        , QUESTS_ON("GO Pass: claim the rewards when the quest button on the map turns gold", LockMode::LOCK_WHILE_RUNNING, false)
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
        switch (preset.kind){
        case Kind::SERVICE:
            if (claude_can_play(preset)){
                PA_ADD_OPTION(PLAYER);
            }
            if (preset.choose){
                PA_ADD_OPTION(SPIN_ON);
                PA_ADD_OPTION(CATCH_ON);
            }
            if (preset.choose || preset.daily){
                PA_ADD_OPTION(ROCKET_ON);
                PA_ADD_OPTION(QUESTS_ON);
            }
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
                PA_ADD_OPTION(BATTLE_DAILY);
                PA_ADD_OPTION(BATTLE_LEAGUE);
                PA_ADD_OPTION(BATTLE_COUNT);
                PA_ADD_OPTION(BATTLE_APP);
                PA_ADD_OPTION(BATTLE_GIVE_UP);
                PA_ADD_OPTION(TEAMS_WEEKLY);
            }
            PA_ADD_OPTION(CLOSE_WHEN_FULL);
            PA_ADD_OPTION(BAG_CLEAN);
            PA_ADD_OPTION(HEAT_PAUSE);
            PA_ADD_OPTION(LIVE_LOOK);
            PA_ADD_OPTION(FAST_LOOK);
            break;
        case Kind::BATTLES:
            PA_ADD_OPTION(PLAYER);
            PA_ADD_OPTION(BATTLE_LEAGUE);
            PA_ADD_OPTION(BATTLE_COUNT);
            PA_ADD_OPTION(BATTLE_APP);
            PA_ADD_OPTION(BATTLE_GIVE_UP);
            PA_ADD_OPTION(HEAT_PAUSE);
            PA_ADD_OPTION(LIVE_LOOK);
            break;
        case Kind::TEAMS:
            PA_ADD_OPTION(TEAMS_CHOICE);
            PA_ADD_OPTION(BATTLE_LEAGUE);
            PA_ADD_OPTION(BATTLE_APP);
            PA_ADD_OPTION(HEAT_PAUSE);
            PA_ADD_OPTION(LIVE_LOOK);
            break;
        case Kind::PART:
            PA_ADD_OPTION(PLAYER);
            PA_ADD_OPTION(PART_CHOICE);
            PA_ADD_OPTION(BATTLE_LEAGUE);
            PA_ADD_OPTION(BATTLE_COUNT);
            PA_ADD_OPTION(BATTLE_APP);
            PA_ADD_OPTION(BATTLE_GIVE_UP);
            PA_ADD_OPTION(HEAT_PAUSE);
            PA_ADD_OPTION(LIVE_LOOK);
            break;
        }
    }

    virtual std::string check_validity() const override{
        if (m_preset.choose && !SPIN_ON && !CATCH_ON && !GIFTS_OPEN && !GIFTS_SEND && !ROCKET_ON && !QUESTS_ON){
            return "Choose at least one thing to do: spin, catch, gifts, Team GO Rocket or the GO Pass.";
        }
        if (m_preset.gifts && !m_preset.daily && !GIFTS_OPEN && !GIFTS_SEND){
            return "Choose to open gifts, to send gifts, or both.";
        }
        if (m_preset.daily && !time_pattern().match(QString::fromStdString(std::string(DAILY_TIME)).trimmed()).hasMatch()){
            return "The daily start must be a time as HH:MM, like 08:00.";
        }
        if (has_battle_options()){
            if (!league_pattern().match(league()).hasMatch()){
                return "The league must be a name like Great League (letters, digits, spaces, up to 40).";
            }
            if (!app_pattern().match(app()).hasMatch()){
                return "The Pokémon GO app must be empty (the Play Store app) or a name like com.nianticlabs.pokemongo.ares.";
            }
        }
        return std::string();
    }

    //  What the bot is asked to do.
    MobileBotStart settings() const{
        MobileBotStart start;
        auto add = [&](const char* key, bool on){
            start.options.emplace_back(QString::fromLatin1(key), on);
        };
        switch (m_preset.kind){
        case Kind::SERVICE:{
            const bool spin = m_preset.choose ? (bool)SPIN_ON : m_preset.spin;
            const bool catching = m_preset.choose ? (bool)CATCH_ON : m_preset.catching;
            const bool chosen = m_preset.choose || m_preset.daily;
            add("spin", spin);
            add("catch", catching);
            add("gifts_open", m_preset.gifts && (m_preset.daily || (bool)GIFTS_OPEN));
            add("gifts_send", m_preset.gifts && (m_preset.daily || (bool)GIFTS_SEND));
            add("daily_cycle", m_preset.daily);
            add("rocket_fight", m_preset.rocket || (chosen && (bool)ROCKET_ON));
            add("quests", m_preset.quests || (chosen && (bool)QUESTS_ON));
            add("curveball", catching && (bool)CURVEBALL);
            add("fast_catch", catching && (bool)FAST_CATCH);
            add("buddy", catching && (bool)BUDDY);
            add("spin_only_when_full", catching && spin && (bool)SPIN_ONLY_WHEN_FULL);
            add("close_when_full", (bool)CLOSE_WHEN_FULL);
            add("bag_clean", (bool)BAG_CLEAN);
            add("heat_pause", (bool)HEAT_PAUSE);
            add("live_look", (bool)LIVE_LOOK);
            add("fast_look", (bool)FAST_LOOK);
            add("battle", m_preset.daily && (bool)BATTLE_DAILY);
            add("battle_give_up", !m_preset.daily || (bool)BATTLE_GIVE_UP);
            add("teams_weekly", m_preset.daily && (bool)TEAMS_WEEKLY);
            if (catching){
                start.throw_target = QString::fromLatin1(throw_slug(THROW_TARGET.get()));
            }
            if (m_preset.daily){
                start.daily_time = QString::fromStdString(std::string(DAILY_TIME)).trimmed();
                start.daily_max_min = (int)DAILY_MAX_MIN.current_value();
                start.daily_now = (bool)DAILY_NOW;
            }
            break;
        }
        case Kind::BATTLES:
            add("battle", true);
            add("battle_give_up", (bool)BATTLE_GIVE_UP);
            add("heat_pause", (bool)HEAT_PAUSE);
            add("live_look", (bool)LIVE_LOOK);
            break;
        case Kind::TEAMS:
            add("heat_pause", (bool)HEAT_PAUSE);
            add("live_look", (bool)LIVE_LOOK);
            break;
        case Kind::PART:
            add("battle_give_up", (bool)BATTLE_GIVE_UP);
            add("heat_pause", (bool)HEAT_PAUSE);
            add("live_look", (bool)LIVE_LOOK);
            break;
        }
        if (has_battle_options()){
            start.battle_league = league();
            start.battle_app_given = true;
            start.battle_app = app();
            if (m_preset.kind != Kind::TEAMS){
                start.battle_count = (int)BATTLE_COUNT.current_value();
            }
        }
        return start;
    }

    //  For a part of the bot: its key.
    QString part_key() const{
        switch (m_preset.kind){
        case Kind::BATTLES: return "battle_set";
        case Kind::TEAMS:   return QString::fromLatin1(PARTS[(size_t)TEAMS_CHOICE.current_value()].key);
        case Kind::PART:    return QString::fromLatin1(PARTS[(size_t)PART_CHOICE.current_value()].key);
        case Kind::SERVICE: break;
        }
        return QString();
    }

    virtual void program(ProgramEnvironment& env, CancellableScope& scope) override{
        GlobalSettings& global = GlobalSettings::instance();
        const QString host = QString::fromStdString(std::string(global.MOBILE_HOST)).trimmed();
        const int port = (int)global.MOBILE_PORT.current_value();
        if (host.isEmpty()){
            throw UserSetupError(env.logger(), "The address of the Raspberry Pi is not set. Pick the Android phone as the console and fill in the Raspberry Pi (Settings).");
        }
        const MobileAgent agent(host, port, mobile_token());
        if (m_preset.kind == Kind::BATTLES && PLAYER == Player::CLAUDE_GG){
            run_battles(env, scope, host, port);
            return;
        }
        if (claude_can_play(m_preset) && PLAYER == Player::CLAUDE_GG){
            run_play(env, scope, host, port);
            return;
        }
        if (m_preset.kind == Kind::PART && PLAYER == Player::CLAUDE_GG){
            run_chapter(env, scope, host, port);
            return;
        }
        //  Stopping a test waits for the game to be back on the map: that takes longer than a tap.
        const MobileAgent patient(host, port, mobile_token(), 60000);
        const std::string where = host.toStdString() + ":" + std::to_string(port);

        QString error;
        MobileBotState state;
        if (!agent.bot_state(state, 5, &error)){
            throw UserSetupError(env.logger(), "Cannot reach the Raspberry Pi at " + where + ": " + error.toStdString());
        }
        if (!state.installed){
            throw UserSetupError(env.logger(), "The Pokémon GO bot is not installed on the Raspberry Pi (Mobile/install.sh installs it).");
        }
        if (state.test.running){
            throw UserSetupError(
                env.logger(),
                "A test of the bot runs already (" + state.test.title.toStdString() + "): stop it first (in the web interface of the bot, or run this program and press Stop)."
            );
        }
        //  Only what the bot writes from now on is shown.
        QString last = state.log.isEmpty() ? QString() : state.log.back();

        if (m_preset.kind == Kind::SERVICE){
            run_service(env, scope, agent, patient, state, last, where);
        }else{
            run_part(env, scope, agent, patient, state, last, where);
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
    bool has_battle_options() const{
        return m_preset.kind != Kind::SERVICE || m_preset.daily;
    }
    QString league() const{
        return QString::fromStdString(std::string(BATTLE_LEAGUE)).trimmed();
    }
    QString app() const{
        return QString::fromStdString(std::string(BATTLE_APP)).trimmed();
    }

    //  The lines of the bot's log after the last one that was shown (all of them when that one is not in
    //  the log any more).
    static void show_new_lines(ProgramEnvironment& env, const MobileBotState& state, QString& last){
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
    }

    void run_service(
        ProgramEnvironment& env, CancellableScope& scope,
        const MobileAgent& agent, const MobileAgent& patient,
        MobileBotState& state, QString& last, const std::string& where
    ){
        QString error;
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
                show_new_lines(env, state, last);

                //  The bot ended by itself (the game was closed, the time was up): so does the program.
                not_running = state.running ? 0 : not_running + 1;
                if (not_running >= 2){
                    env.log("The bot has stopped.");
                    return;
                }
            }
        }catch (OperationCancelledException&){
            QString stop_error;
            if (patient.bot_stop(&stop_error)){
                env.log("The bot on the Raspberry Pi is stopped.");
            }else{
                env.log("The bot could not be stopped: " + stop_error.toStdString(), COLOR_RED);
            }
            throw;
        }
    }

    void run_part(
        ProgramEnvironment& env, CancellableScope& scope,
        const MobileAgent& agent, const MobileAgent& patient,
        MobileBotState& state, QString& last, const std::string& where
    ){
        const QString key = part_key();
        QString error;
        //  (The bot's service is stopped by the agent for the test, and set going again by nothing.)
        if (!patient.bot_test(key, settings(), &error)){
            throw UserSetupError(env.logger(), "The part of the bot could not be started: " + error.toStdString());
        }
        env.log("The part \"" + key.toStdString() + "\" of the Pokémon GO bot on the Raspberry Pi (" + where + ") is started: " + m_preset.name + ".");

        try{
            int unreachable = 0;
            while (true){
                scope.wait_for(std::chrono::milliseconds(3000));
                if (!agent.bot_state(state, 80, &error)){
                    if (++unreachable >= 5){
                        throw UserSetupError(
                            env.logger(),
                            "The Raspberry Pi does not answer (" + error.toStdString() + "). The part may still run there."
                        );
                    }
                    continue;
                }
                unreachable = 0;
                show_new_lines(env, state, last);

                if (state.test.key == key && state.test.finished){
                    if (m_preset.kind == Kind::BATTLES){
                        env.log(
                            "Battles today: " + std::to_string(state.battles_won) + " won, " +
                            std::to_string(state.battles_lost) + " lost."
                        );
                    }
                    if (state.test.ok){
                        env.log("The part is done: " + state.test.result.toStdString());
                        return;
                    }
                    throw UserSetupError(env.logger(), "The part of the bot failed: " + state.test.result.toStdString());
                }
                if (state.test.key != key || (!state.test.running && !state.test.finished)){
                    throw UserSetupError(env.logger(), "The part of the bot is gone from the Raspberry Pi (the agent was restarted?).");
                }
            }
        }catch (OperationCancelledException&){
            QString stop_error;
            if (patient.bot_test_stop(&stop_error)){
                env.log("The part of the bot on the Raspberry Pi is stopped.");
            }else{
                env.log("The part could not be stopped: " + stop_error.toStdString(), COLOR_RED);
            }
            throw;
        }
    }

    //  What Claude GG needs to play itself: an agent that is new enough, a phone that answers, Tesseract on this computer, and the Python bot
    //  not playing at the same time.  Returns the tesseract program.
    QString prepare_phone(ProgramEnvironment& env, const QString& address, int port, const QString& token, bool battles, bool catching = false, bool daily = false){
        const MobileAgent agent(address, port, token);
        const MobileAgent patient(address, port, token, 60000);
        const std::string where = address.toStdString() + ":" + std::to_string(port);
        QString error;

        //  The agent must be one that knows the kinds of a tap and the app (0.2.0 and later).
        MobileInfo info;
        if (!agent.info(info, &error)){
            throw UserSetupError(env.logger(), "Cannot reach the Raspberry Pi at " + where + ": " + error.toStdString());
        }
        for (const char* feature : {"tap_kind", "app", "bot_file"}){
            if (!info.features.contains(QString::fromLatin1(feature))){
                throw UserSetupError(
                    env.logger(),
                    "The agent on the Raspberry Pi is too old (" + (info.version.isEmpty() ? std::string("0.1.0") : info.version.toStdString()) +
                    ") for Claude GG to play: on the Pi, in the folder of the clone, run  git pull  and then  bash Mobile/agent/install-agent.sh  "
                    "(the token stays the same). Or choose the Python bot on the Pi under Who plays."
                );
            }
        }
        if (catching && !info.features.contains("touch")){
            throw UserSetupError(
                env.logger(),
                "The agent on the Raspberry Pi is too old (" + info.version.toStdString() + ") for Claude GG to throw a ball (0.2.2 and later): on the "
                "Pi, in the folder of the clone, run  git pull  and then  bash Mobile/agent/install-agent.sh. Or choose the Python bot on the Pi under Who plays."
            );
        }
        if (daily && !info.features.contains("app_list")){
            throw UserSetupError(
                env.logger(),
                "The agent on the Raspberry Pi is too old (" + info.version.toStdString() + ") for Claude GG to play the daily run (0.2.3 and later: it lists the "
                "Pokémon GO apps of the phone): on the Pi, in the folder of the clone, run  git pull  and then  bash Mobile/agent/install-agent.sh. Or choose the "
                "Python bot on the Pi under Who plays."
            );
        }
        if (info.width <= 0 || info.height <= 0){
            throw UserSetupError(env.logger(), "The phone on the Raspberry Pi does not answer (is it on, unlocked, and does adb devices show it?).");
        }
        env.log(
            "The phone: " + info.model.toStdString() + ", Android " + info.android.toStdString() + ", " +
            std::to_string(info.width) + " x " + std::to_string(info.height) + " (agent " + info.version.toStdString() + " at " + where + ")."
        );

        //  The text reader.
        const QString tesseract = PokemonGo::Text::Reader::find_program();
        if (tesseract.isEmpty()){
            throw UserSetupError(
                env.logger(),
                std::string(battles
                    ? "Tesseract is not installed on this computer: Claude GG reads the screens of the battles with it. Install it "
                      "(on Windows the installer of UB Mannheim, into C:\\Program Files\\Tesseract-OCR) and start the program again."
                    : "Tesseract is not installed on this computer: Claude GG reads the text on the screens of the game with it. Install it "
                      "(on Windows the installer of UB Mannheim, into C:\\Program Files\\Tesseract-OCR) and start the program again.")
            );
        }
        env.log("The text reader: " + tesseract.toStdString());

        //  The Python bot must not play at the same time.
        MobileBotState state;
        if (agent.bot_state(state, 1, &error)){
            if (state.test.running){
                env.log("A part of the Python bot runs on the Pi (" + state.test.title.toStdString() + "): it is stopped first.");
                patient.bot_test_stop(&error);
            }
            if (state.running){
                env.log("The Python bot runs on the Pi: it is stopped first (Claude GG plays now).");
                if (!patient.bot_stop(&error)){
                    throw UserSetupError(env.logger(), "The Python bot on the Pi could not be stopped: " + error.toStdString());
                }
            }
        }

        return tesseract;
    }

    //  The options of the phone for Claude GG: the folder of the bot and the models in it.
    PokemonGo::Phone::Options phone_options(const QString& tesseract, const QString& folder){
        PokemonGo::Phone::Options options;
        options.video = (bool)LIVE_LOOK;
        options.give_up = (bool)BATTLE_GIVE_UP;
        options.league = league();
        options.folder = folder;
        options.tesseract = tesseract;
        if (!app().isEmpty()){
            options.package = app();
        }
        options.models = qEnvironmentVariable("CLAUDEGG_MODELS");
        if (options.models.isEmpty() && QDir(folder + "/models").exists()){
            options.models = folder + "/models";
        }
        return options;
    }

    //  Spin PokéStops, catch Pokémon and do the gifts with Claude GG itself (the steps of gamebot.py ported to C++, over the agent).  Experimental.
    void run_play(ProgramEnvironment& env, CancellableScope& scope, const QString& address, int port){
        const QString token = mobile_token();
        const MobileBotStart start = settings();
        bool catching = false;
        for (const std::pair<QString, bool>& option : start.options){
            catching = catching || (option.first == "catch" && option.second);
        }
        const QString tesseract = prepare_phone(env, address, port, token, false, catching, m_preset.daily);
        const QString folder = QString::fromStdString(USER_FILE_PATH()) + "PokemonGo";
        QDir().mkpath(folder);
        const PokemonGo::Phone::Options options = phone_options(tesseract, folder);
        if (options.models.isEmpty()){
            throw UserSetupError(
                env.logger(),
                "Claude GG needs the models of the bot to see the map and the PokéStops (" + folder.toStdString() + "/models, the ONNX "
                "files that Mobile/tools/convert_models_to_onnx.py makes). Put them there, or choose the Python bot on the Pi under Who plays."
            );
        }
        PokemonGo::Phone::AgentHost phone(
            address, port, token, options,
            [&](const QString& line){ env.log(line.toStdString()); },
            [&]{ return scope.cancelled(); }
        );
        if (!phone.has_models()){
            throw UserSetupError(env.logger(), "The models of " + options.models.toStdString() + " cannot be used: see the log above.");
        }
        PokemonGo::Bot::Switches switches;
        for (const std::pair<QString, bool>& option : start.options){
            switches[option.first] = option.second;
        }
        PokemonGo::Bot::Texts texts;
        if (!start.throw_target.isEmpty()){
            texts["throw_target"] = start.throw_target;
        }
        if (m_preset.daily){
            //  The daily run: when it starts, how long it may take, whether it begins at once, and what the battles are.
            texts["daily_time"] = start.daily_time;
            texts["daily_max_min"] = QString::number(start.daily_max_min);
            texts["daily_force"] = start.daily_now ? "button" : "start";
            if (start.battle_app_given){
                texts["battle_app"] = start.battle_app;
            }
            if (!start.battle_league.isEmpty()){
                texts["battle_league"] = start.battle_league;
            }
            if (start.battle_count > 0){
                texts["battle_count"] = QString::number(start.battle_count);
            }
        }
        PokemonGo::Bot::PhoneBot bot(phone, switches, texts, folder);
        if (switches["heat_pause"] && !phone.reads_heat()){
            env.log(
                "The agent on the Raspberry Pi is older than 0.2.4 and cannot tell the temperatures: Claude GG plays without a pause when the phone "
                "or the Pi gets hot. On the Pi, in the folder of the clone, run  git pull  and then  bash Mobile/agent/install-agent.sh.",
                COLOR_RED
            );
        }
        std::string does;
        const auto add_part = [&](const char* part){
            does += (does.empty() ? "" : ", ") + std::string(part);
        };
        if (switches["daily_cycle"]){
            add_part(("plays the daily run (from " + std::string(DAILY_TIME) + ", at most " + std::to_string(DAILY_MAX_MIN.current_value()) +
                " min, the apps of the phone one after the other)").c_str());
        }
        if (switches["battle"]){
            add_part("fights GO Battle League battles first");
        }
        if (switches["spin"]){
            add_part("spins the PokéStops");
        }
        if (switches["catch"]){
            add_part("catches the Pokémon");
        }
        if (switches["gifts_open"]){
            add_part("opens the gifts");
        }
        if (switches["gifts_send"]){
            add_part("sends gifts");
        }
        if (switches["rocket_fight"]){
            add_part("battles Team GO Rocket");
        }
        if (switches["quests"]){
            add_part("claims the GO Pass rewards");
        }
        if (switches["bag_clean"]){
            add_part("cleans a full bag");
        }
        env.log("Claude GG itself " + does + " (experimental" + std::string(switches["daily_cycle"] && switches["teams_weekly"] ? "; the weekly teams are not kept up to date by Claude GG yet" : "") + ").");
        try{
            PokemonGo::Bot::run(bot);
        }catch (const PokemonGo::Flow::Interrupted&){
            env.log("Stopped " + bot.counts().toStdString() + ".");
            scope.throw_if_cancelled();
            throw;
        }
    }

    //  One part of the bot on its own, run by Claude GG itself (Chapter::run of ClaudeGG_PokemonGoChapter, the C++ port of run_chapter() of gamebot.py).
    //  Experimental.  The parts that need the live video, the Pokémon of the person or the storage stay with the Python bot on the Pi.
    void run_chapter(ProgramEnvironment& env, CancellableScope& scope, const QString& address, int port){
        const QString key = part_key();
        if (PokemonGo::Chapter::find(key) == nullptr){
            throw UserSetupError(
                env.logger(),
                "Claude GG cannot run the part \"" + key.toStdString() + "\" itself yet (it can run: " + PokemonGo::Chapter::keys().toStdString() +
                "; the battles are the program GO Battle League). Choose the Python bot on the Raspberry Pi under Who plays."
            );
        }
        const QString token = mobile_token();
        //  The parts that throw a ball need the touch of the agent (0.2.2).
        const bool throwing = key == "play" || key == "catch" || key == "throw" || key == "rocket";
        const QString tesseract = prepare_phone(env, address, port, token, false, throwing, false);
        const QString folder = QString::fromStdString(USER_FILE_PATH()) + "PokemonGo";
        QDir().mkpath(folder);
        const PokemonGo::Phone::Options options = phone_options(tesseract, folder);
        if (options.models.isEmpty()){
            throw UserSetupError(
                env.logger(),
                "Claude GG needs the models of the bot to see the screens of the game (" + folder.toStdString() + "/models, the ONNX "
                "files that Mobile/tools/convert_models_to_onnx.py makes). Put them there, or choose the Python bot on the Pi under Who plays."
            );
        }
        PokemonGo::Phone::AgentHost phone(
            address, port, token, options,
            [&](const QString& line){ env.log(line.toStdString()); },
            [&]{ return scope.cancelled(); }
        );
        if (!phone.has_models()){
            throw UserSetupError(env.logger(), "The models of " + options.models.toStdString() + " cannot be used: see the log above.");
        }
        PokemonGo::Bot::Switches switches;
        for (const std::pair<QString, bool>& option : settings().options){
            switches[option.first] = option.second;
        }
        PokemonGo::Bot::PhoneBot bot(phone, switches, PokemonGo::Bot::Texts(), folder);
        env.log("The part \"" + key.toStdString() + "\" of the Pokémon GO bot, run by Claude GG itself (experimental): " + m_preset.name + ".");
        const PokemonGo::Chapter::Result result = PokemonGo::Chapter::run(bot, key);
        scope.throw_if_cancelled();
        if (!result.ok){
            throw UserSetupError(env.logger(), "The part of the bot failed: " + result.how.toStdString());
        }
        env.log("The part is done: " + result.how.toStdString());
    }

    //  GO Battle League, played by Claude GG itself (Flow::battle_run of ClaudeGG_PokemonGoFlow, the C++ port of
    //  gamebot.battle_run): the agent on the Pi gives the picture and the taps, nothing more.
    void run_battles(ProgramEnvironment& env, CancellableScope& scope, const QString& address, int port){
        const QString token = mobile_token();
        const MobileAgent agent(address, port, token);
        QString error;
        const QString tesseract = prepare_phone(env, address, port, token, true);

        //  The folder of what the battles learn, and the team: taken from the bot on the Pi when it has them.
        const QString folder = QString::fromStdString(USER_FILE_PATH()) + "PokemonGo";
        QDir().mkpath(folder);
        for (const char* name : {"battle_team.json", "battle_seen.json", "battle_minigame.json"}){
            const QString file = folder + "/" + name;
            const bool team = std::string(name) == "battle_team.json";
            if (!team && QFile::exists(file)){
                continue;                   //  (what was learned here is kept; the Pi's copy is only a start)
            }
            QByteArray data;
            bool found = false;
            if (!agent.bot_file(QString::fromLatin1(name), data, found, &error)){
                env.log(std::string("The bot's ") + name + " could not be read from the Pi: " + error.toStdString(), COLOR_ORANGE);
                continue;
            }
            if (!found){
                if (team){
                    env.log(QFile::exists(file)
                        ? "The Pi has no battle_team.json: the one of " + folder.toStdString() + " is used."
                        : std::string("The Pi has no battle_team.json (the program Your Pokémon and teams makes one): the preset team is used."));
                }
                continue;
            }
            QFile out(file);
            if (out.open(QIODevice::WriteOnly | QIODevice::Truncate) && out.write(data) == data.size()){
                env.log(std::string("Taken from the Pi: ") + name);
            }
        }

        const PokemonGo::Phone::Options options = phone_options(tesseract, folder);
        if (options.models.isEmpty()){
            env.log("No models of the screen classifier (" + folder.toStdString() + "/models): a Pokémon to catch as a reward is not recognised.", COLOR_ORANGE);
        }

        PokemonGo::Phone::AgentHost phone(
            address, port, token, options,
            [&](const QString& line){ env.log(line.toStdString()); },
            [&]{ return scope.cancelled(); }
        );
        std::vector<PokemonGo::Battle::Mon> team;
        try{
            team = phone.load_team();
        }catch (const std::exception& e){
            throw UserSetupError(env.logger(), std::string("The team (battle_team.json) cannot be fought with: ") + e.what());
        }
        QStringList names;
        QStringList labels;
        for (const PokemonGo::Battle::Mon& mon : team){
            names << mon.name;
            labels << mon.label();
        }
        int won = 0;
        int lost = 0;
        PokemonGo::Phone::Hooks hooks;
        hooks.day_count = [&](const QString& key){
            (key == "won" ? won : lost)++;
            return QString("(this run: %1 won, %2 lost)").arg(won).arg(lost);
        };
        hooks.team_names = [names]{ return names; };
        phone.set_hooks(hooks);

        const int count = (int)BATTLE_COUNT.current_value();
        env.log(QString("battle: %1 battle(s) in '%2' with %3").arg(count).arg(league(), labels.join(", ")).toStdString());
        PokemonGo::Flow::Run run;
        try{
            run = PokemonGo::Flow::battle_run(phone, team, count);
        }catch (const PokemonGo::Flow::Interrupted&){
            scope.throw_if_cancelled();
            throw;
        }catch (const std::runtime_error& e){
            scope.throw_if_cancelled();
            throw UserSetupError(env.logger(), std::string("The battles stopped: ") + e.what());
        }
        scope.throw_if_cancelled();
        env.log(
            "Battles: " + std::to_string(run.fought) + " fought, " + std::to_string(run.wins) + " won" +
            (run.catch_reward.value_or(false) ? " - a Pokémon of the rewards is waiting to be caught" : "") +
            (run.done_today ? " - the battles are done for today" : "") + "."
        );
        if (run.fought == 0){
            throw UserSetupError(env.logger(), "No battle was fought: see the log above (the pictures are in " + folder.toStdString() + "/pictures).");
        }
    }

    const Preset& m_preset;
    StaticTextOption SETUP_TEXT;
    IntegerEnumDropdownOption PART_CHOICE;
    IntegerEnumDropdownOption TEAMS_CHOICE;
    BooleanCheckBoxOption BATTLE_DAILY;
    BooleanCheckBoxOption TEAMS_WEEKLY;
    StringOption BATTLE_LEAGUE;
    SimpleIntegerOption<uint32_t> BATTLE_COUNT;
    StringOption BATTLE_APP;
    EnumDropdownOption<Player> PLAYER;
    BooleanCheckBoxOption BATTLE_GIVE_UP;
    EnumDropdownOption<Throw> THROW_TARGET;
    BooleanCheckBoxOption CURVEBALL;
    BooleanCheckBoxOption FAST_CATCH;
    BooleanCheckBoxOption BUDDY;
    BooleanCheckBoxOption SPIN_ON;
    BooleanCheckBoxOption CATCH_ON;
    BooleanCheckBoxOption ROCKET_ON;
    BooleanCheckBoxOption QUESTS_ON;
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

std::vector<std::string> pokemon_go_part_keys(){
    std::vector<std::string> keys;
    for (const Part& part : PARTS){
        keys.emplace_back(part.key);
    }
    return keys;
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
