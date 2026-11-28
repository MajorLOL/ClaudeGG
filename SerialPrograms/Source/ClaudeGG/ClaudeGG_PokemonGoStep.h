/*  Claude GG Pokemon GO Step (one step of the Pokémon GO bot: which screen is it, what is done with it)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port of step() of Mobile/gamebot.py (issue #31) and of what it uses itself:
 *
 *  - heat_wait(): the phone or the Pi is too hot: nothing is tapped until it is cool again;
 *  - step(): the screen has another shape / the phone is awake / the screenshot (or the one that was handed on by the wait for the catch
 *    result) / which screen it is / away from the map for minutes or the same screen over and over: start the game again / a tap on a Pokémon
 *    that did nothing / Team GO Rocket / the layout check and the quests of the first looks at the map / and then the map, the stop, the
 *    catch screen, an egg, the summary, a news card, a group question, the safety notice, a full Pokémon storage, the 'I am a passenger'
 *    pop-up and the result screen;
 *  - leave_group_screen(), is_rocket_text(), storage_full() and pause_catching(): the small readers and the pause that step() uses.
 *
 *  What step() hands on to other parts is a seam of the Host: the map, the stop and the catch screen (the ports of ClaudeGG_PokemonGoMap and
 *  ClaudeGG_PokemonGoCatch are called by the host of the bot), the readings of the heat, the layout check, the lock screen, the quests and the
 *  Team Rocket battle (not ported yet).  run_step_checks() holds all of it, in every build, to tests/fixtures/step_golden.json.qz that
 *  Mobile/tools/make_step_golden.py made with the Python code: the same pictures and answers in, and the same taps, log lines, sleeps, saved
 *  pictures and calls of the seams out, in the same order and at the same moments of a fake clock, with the same things remembered afterwards.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoStep_H
#define PokemonAutomation_ClaudeGG_PokemonGoStep_H

#include <functional>
#include <optional>
#include <utility>
#include <opencv2/core.hpp>
#include <QString>
#include <QStringList>
#include "ClaudeGG_PokemonGoCatch.h"
#include "ClaudeGG_PokemonGoMap.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Step{

using Loop::Point;


inline constexpr double HEAT_EVERY = 60.0;              //  s between two looks at the temperatures
inline constexpr double HEAT_PHONE = 43.0;              //  °C of the phone's battery: pause from here ...
inline constexpr double HEAT_PHONE_OK = 39.0;           //  ... go on again below this
inline constexpr double HEAT_PI = 82.0;                 //  °C of the Pi's processor: the same
inline constexpr double HEAT_PI_OK = 72.0;
inline constexpr double HEAT_MAX_PAUSE = 45 * 60;       //  s: a pause never takes longer than this (a sensor that is stuck)
inline constexpr double HEAT_PAUSED_EVERY = 30.0;       //  s between two looks while it pauses (and the seconds that step() waits)
inline constexpr double AWAY_LIMIT = 300.0;             //  s away from the map before the game is started again
inline constexpr int STUCK_COUNT = 12;                  //  the same screen (not the map) more often than this: start the game again
inline constexpr double HEALTH_EVERY = 60.0;            //  s between two looks at whether the phone is awake
inline constexpr double HANDOFF_MAX_AGE = 2.5;          //  s: a screenshot that was handed on is used for this long
inline constexpr double COOLDOWN = 5 * 60;              //  s: a spot where tapping gave nothing is skipped this long
inline constexpr double NEAR_BLOCK = 20 * 60;           //  s: after a tap next to the trainer did nothing (the buddy?), leave that area alone
inline constexpr double ROCKET_COOLDOWN = 30 * 60;      //  s: Team GO Rocket at a stop: leave that stop alone this long
inline constexpr double STORAGE_FULL_WAIT = 30 * 60;    //  s: the storage is full: do not catch for this long
inline constexpr Point PARTY_CLOSE_BTN{884, 1990};      //  X at the bottom of the Weekly Challenge / group screen
inline constexpr Point CENTER{884, 1104};               //  the middle of the screen (tap through eggs and notifications)


//  What step() remembers besides what the map and the catch screen do (gamebot.heat, health, same_screen and away).
struct Heat{
    double t = 0.0;                     //  when the temperatures were looked at last
    std::optional<double> since;        //  when the pause began (nothing: it does not pause)
    std::optional<double> phone;
    std::optional<double> pi;
};
struct Health{
    double t = 0.0;                     //  when the phone was last asked whether it is awake
    bool ok = false;                    //  the last look showed a normal game screen
};
struct SameScreen{
    std::optional<QString> name;
    int count = 0;
};
struct State{
    Heat heat;
    Health health;
    SameScreen same_screen;
    std::optional<double> away_since;   //  away['since']: since when it has not been on the map, the catch screen or a stop
};


//  ---- the phone, the person and the parts that are not here

//  (virtual: the real host of the bot is also a Throw::Host and so on, and all of them are one Map::Host.)
class Host : public virtual Catch::Host{
public:
    //  The temperatures, °C of the phone's battery and of the Pi (nothing: it could not be read).
    virtual std::pair<std::optional<double>, std::optional<double>> read_heat() = 0;
    //  Is the screen drawn on a canvas of the shape that is supported (S.screen['ok'])?  And the state of the layout check ('new', 'confirmed',
    //  'unverified', 'adapting', 'adapted').
    virtual bool screen_ok() = 0;
    virtual QString layout_state() = 0;
    //  Let Android draw the game on a canvas of the right shape: did it work?  (layout_adapt())
    virtual bool layout_adapt(const QString& why) = 0;
    //  The screen has a shape that is not supported and could not be adapted: wait a little (S.wait_unsupported()).
    virtual void wait_unsupported() = 0;
    //  Has the layout changed (layout_watch())?  And the first map picture of a run: is the game drawn as expected (layout_verify())?
    virtual void layout_watch() = 0;
    virtual void layout_verify(const cv::Mat& img) = 0;
    //  What Android says of the power state of the phone ('dumpsys power'), the key that wakes it, and the lock screen (S.unlock()).
    virtual QString power_state() = 0;
    virtual void key_wakeup() = 0;
    virtual void unlock() = 0;
    //  The game dims and locks itself: the picture when it is wakened (the same picture when it was not dimmed).  S.unlock_game().
    virtual cv::Mat unlock_game(const cv::Mat& img) = 0;
    //  A quick screenshot; `on_grab` is called the moment the picture has been taken (S.quick_screenshot(on_grab)).
    virtual cv::Mat quick_screenshot_grab(const std::function<void()>& on_grab) = 0;
    //  Is it time to claim the rewards of the quests (quests_due()), and claim them (claim_quests(): 'claimed', 'nothing', 'catch' or 'failed';
    //  throws std::runtime_error).
    virtual bool quests_due(const cv::Mat& img) = 0;
    virtual QString claim_quests() = 0;
    //  The Team GO Rocket battle: 'failed' when it did not work out (throws std::runtime_error).
    virtual QString rocket_battle() = 0;
    //  What is done at the map, the stop and the catch screen: the seconds to wait.  (The host calls Map::do_map(), Map::do_pokestop() and
    //  Catch::do_encounter() with its own State and Eyes.)
    virtual double do_map(const cv::Mat& img) = 0;
    virtual double do_pokestop(const cv::Mat& img) = 0;
    virtual double do_encounter(const cv::Mat& img) = 0;
    //  Catching is switched on again after this many seconds (the Timer of pause_catching()).
    virtual void resume_catch_later(double seconds) = 0;
};


//  ---- the steps

//  Option 'Pause when it gets hot': the seconds to wait when the phone or the Pi is too hot (nothing is tapped then), 0 when the bot may go on.
double heat_wait(Host& host, State& state);

//  Weekly Challenge screen ('Find me a group!') and its question 'Are you sure you want to join a group?': never join.  Taps CANCEL on the
//  question, the X on the screen itself.  True when it was one of them.
bool leave_group_screen(Host& host, const cv::Mat& img);
//  Team Rocket dialogue / battle screen recognised by its text.
bool is_rocket_text(Host& host, const cv::Mat& img);
//  The notice 'Your Pokémon storage is full.'
bool storage_full(Host& host, const cv::Mat& img);
//  The Pokémon storage is full: catching is off (map.catching) and comes on again after STORAGE_FULL_WAIT.
void pause_catching(Host& host, Map::State& map);
//  The time of that pause is over (what the host does when the time that it was given by resume_catch_later() has passed).
void resume_catching(Host& host, Map::State& map);

//  One step of the bot: looks at the screen and does what it needs.  Returns the seconds to wait before the next step.  Throws what the
//  screenshot, the classifier or the parts that are called throw.
double step(Host& host, Map::State& map, State& state);


//  ---- the check
//
//  Plays the stories of the file of Mobile/tools/make_step_golden.py (tests/fixtures/step_golden.json.qz) and says where the port does
//  something else than the Python code did.  Returns how many went another way ("FAILED: ..." lines in `report` say which, the last line
//  says how many were played).
int run_step_checks(const QString& golden, QStringList& report, bool stop_at_first = false);


}
}
}
}
#endif
