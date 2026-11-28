/*  Claude GG Pokemon GO Daily (the daily run of the Pokémon GO bot: every app of the phone once a day, at the time the person chose)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port of the daily run of Mobile/gamebot.py (issue #31): daily_cycle() with run_one_game(), finish_catch(), daily_order(), daily_limit()
 *  and last_slot().  Once a day, at the time of "daily_time" (08:00 when it is not set), a run starts: every Pokémon GO app of the phone in
 *  turn is started and played with the normal bot (Host::step()) until the run time of "daily_max_min" (480 minutes when it is not set: all
 *  the apps together) is up or the bot says the run is done (the storage and the bag are full); a catch that is going on when the time is up
 *  is finished first (at most 150 s), then the game is closed.  What the run did is kept in a file (gamebot_daily.json), so a bot that is
 *  started again goes on with the run (and the time already played); the Start button begins a new run at once.
 *
 *  Not ported, and off in Claude GG (as they are in gamebot.py when they are not chosen): the GO Battle League battles at the start of a run,
 *  the weekly round of the teams, and the way back to the battles after the Pokémon of a reward.  Not ported either: the watchdog thread of
 *  gamebot.py, which ends the Python process when a step hangs (the Claude GG program has its own Stop).
 *
 *  Held, in every build (--mobile-test), to tests/fixtures/daily_golden.json.qz that Mobile/tools/make_daily_golden.py made with the Python
 *  code: stories of several calls of daily_cycle() on a pretend bot and a fake clock (the local time zone is UTC there), with what the code
 *  logged, waited, saved, started and closed.  Experimental: not tried on a real phone.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoDaily_H
#define PokemonAutomation_ClaudeGG_PokemonGoDaily_H

#include <functional>
#include <QJsonObject>
#include <QJsonValue>
#include <QString>
#include <QStringList>

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Daily{


//  The defaults of gamebot.py.
const double DAILY_MAX_MIN = 480;           //  "Stop after ... min": how long a run may take, all apps together
const double FINISH_MAX_S = 150;            //  s: when the time is up during a catch, this long to finish it


//  What the daily run needs of the bot and the phone.
class Host{
public:
    virtual ~Host() = default;

    //  time.time() and time.monotonic().
    virtual double wall() = 0;
    virtual double monotonic() = 0;
    virtual void sleep(double seconds) = 0;
    virtual void log(const QString& text) = 0;

    //  A setting of the web interface (gamebot.setting()): undefined when it is not there (then the default counts).
    virtual QJsonValue setting(const QString& key) = 0;
    //  gamebot.wanted(): a switch (on when it is not there).
    virtual bool wanted(const QString& key) = 0;

    //  The file of the run (gamebot_daily.json): {"start": 0, "done": []} when there is none or it cannot be read.
    virtual QJsonObject load_daily() = 0;
    virtual void save_daily(const QJsonObject& d) = 0;

    //  The Pokémon GO apps of the phone, the Play Store one first.
    virtual QStringList game_packages() = 0;
    //  The app that the bot plays from now on (S.PACKAGE), then reset_for_game(): the switches and timers of a new game.
    virtual void reset_for_game(const QString& package) = 0;
    virtual void restart_game() = 0;
    virtual void close_game_completely() = 0;

    //  One step of the normal bot: the seconds to wait after it.  It may throw (the run goes on: "error: ...").
    virtual double step() = 0;
    //  run_state["done"]: the bot says the run is over (the storage and the bag are full and the game is closed).
    virtual bool run_done() = 0;
    //  What the screen classifier says of a screenshot now ("encounterScreen", "mapScreen", ...).  It may throw.
    virtual QString screen_name() = 0;

    //  force_start["pending"]: "button" (the Start button), "start" (the bot was started), or empty; it is taken (cleared) by the call.
    virtual QString take_force_start() = 0;

    //  time.mktime() of the day of `now` (local time) at hh:mm.
    virtual double local_time_of_day(double now, int hh, int mm) = 0;
    //  time.strftime("%Y-%m-%d %H:%M", time.localtime(t)).
    virtual QString local_text(double t) = 0;
};


//  What gamebot.py keeps between two calls: run_state["waiting_logged"].
struct State{
    bool waiting_logged = false;
    QJsonValue logged_time;
    QJsonValue logged_start;
};


//  The minutes a run may take: "daily_max_min", between 1 and 1440 (480 when it is not a number).
double daily_limit(Host& host);
//  The latest moment (a timestamp) of the daily start time, at or before `now`.
double last_slot(Host& host, double now);
//  The apps in the order they are played (no battles: the order of game_packages()).
QStringList daily_order(Host& host);
//  A catch that is going on when the time is up is finished first.
//  beat(): books the time played so far.
void finish_catch(Host& host, const std::function<void()>& beat);
//  One app of the run; false when the daily run was switched off.
bool run_one_game(Host& host, State& state, const QString& package, QJsonObject& d);
//  One look of the loop of the bot at the daily run: starts or goes on with a run.  Returns the seconds to wait before the next call.
double daily_cycle(Host& host, State& state);


//  The checks: the stories of tests/fixtures/daily_golden.json.qz.  Returns the number of stories that went another way.
int run_daily_checks(const QString& golden, QStringList& report, bool stop_at_first = false);


}
}
}
}
#endif
