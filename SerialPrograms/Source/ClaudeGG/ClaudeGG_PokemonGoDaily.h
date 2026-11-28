/*  Claude GG Pokemon GO Daily (the daily run of the Pokémon GO bot: the start time of the day, the apps one after the other, the time of the run)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port of what Mobile/gamebot.py does in the daily run (issue #31):
 *
 *  daily_cycle(): what the bot does instead of one plain step when the daily run is on.  It reads the file of the run (gamebot_daily.json: when it
 *  started, which apps are done, which start time was used up, how long each app was played), starts a new run when the start time of the day has come and
 *  no run has used it (or at once after the Start button), plays the first app that is not done (run_one_game()), and when all are done says when the next
 *  run is.  It says how long the loop should wait (5 s, 60 s).
 *
 *  run_one_game(): one app: the game is started again, the battles are fought first (when they are chosen and this is the app for them), the teams are brought
 *  up to date (when it is time), then step after step (the plain bot) until the run is switched off, the app has nothing to do any more (storage and bag
 *  full), or the run time is up: a catch is finished (finish_catch()), the game is closed and the run ends.  The time of every app is counted, written
 *  to the file now and then, and kept when the bot is started again.  A Pokémon of a reward of the battles is caught and the battles go on, three times
 *  at most.
 *
 *  Like the rest it knows nothing of the phone: it is given a Host (the map's, with the file of the run, the apps, the battles and the teams on top of it).
 *  run_daily_checks() holds all of it, in every build, to tests/fixtures/daily_golden.json.qz that Mobile/tools/make_daily_golden.py made with the Python
 *  code: the same answers in, and the same log lines, sleeps, writes of the file and calls out, in the same order and at the same moments of a fake clock.
 *
 *  Where it differs from the Python code (the stories leave these out):
 *  - the watchdog (a thread of the Python bot that stops a bot that hangs in one step, so that systemd starts it again) is a seam of the host: the program
 *    that plays is stopped by the person and every call to the phone has a time limit, so PhoneBot starts none;
 *  - the time of each app is kept in the order the apps were played, but a file that was written by Qt has its keys sorted (the sum of the seconds of
 *    the apps may differ in the last bit of a double then);
 *  - hh:mm of the start time that has more than nine digits is taken for no start time (08:00), Python would fail in mktime();
 *  - a file of the run that is JSON but no object (a list) is taken for no file, Python would stop with an error.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoDaily_H
#define PokemonAutomation_ClaudeGG_PokemonGoDaily_H

#include <functional>
#include <optional>
#include <QJsonArray>
#include <QJsonObject>
#include <QJsonValue>
#include <QString>
#include <QStringList>
#include "ClaudeGG_PokemonGoMap.h"
#include "ClaudeGG_PokemonGoStart.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Daily{


inline constexpr double MAX_MIN = 480;                  //  DAILY_MAX_MIN: minutes a run may take (all the apps together), when the person said nothing
inline constexpr double FINISH_MAX_S = 150;             //  s: when the time is up during a catch, this long to finish it
inline constexpr int BATTLE_RESUMES = 3;                //  the battles go on after a Pokémon of a reward was caught, this often a run at most
inline constexpr double SAVE_EVERY = 60;                //  s between two writes of the file
inline constexpr double REPORT_EVERY = 1800;            //  s of play between two lines that say how far the run is


//  What the run remembers between two calls (run_state and force_start of gamebot.py).
struct State{
    bool done = false;                                  //  run_state['done']: this app has nothing to do any more (the storage and the bag are full)
    std::optional<QJsonArray> waiting;                  //  run_state['waiting_logged']: the (start time, start) that was last said to wait for
    bool battle_resume = false;                         //  run_state['battle_resume']: a Pokémon of a reward is to be caught, then the battles go on
    QString force;                                      //  force_start['pending']: 'button' (the Start button: a new run), 'start' (the bot was started), none
};


typedef std::function<void()> Beat;
typedef std::function<bool()> Ask;


class Host : public virtual Map::Host{
public:
    //  One step of the bot (step()): the seconds to wait afterwards.  Throws std::runtime_error when the step fails.
    virtual double daily_step() = 0;

    //  The file of the run (~/gamebot_daily.json): its content, nothing when there is none or it is no JSON.  And writing it.
    virtual std::optional<QJsonObject> read_daily() = 0;
    virtual void write_daily(const QJsonObject& daily) = 0;
    //  What the person set (setting(key, default)): as it is, undefined when it was never set.
    virtual QJsonValue setting_value(const QString& key) = 0;

    //  The Pokémon GO apps that are installed (game_packages(): Play Store first), and what was chosen for the battles (battle_wanted(), battle_app()).
    virtual QStringList game_packages() = 0;
    virtual bool battle_wanted() = 0;
    virtual QString battle_app() = 0;
    //  The app that is played (S.PACKAGE).
    virtual void set_package(const QString& package) = 0;
    //  The game is played from the start: the flags of the last one are reset (reset_for_game(): spinning and catching on, the storage and the bag not
    //  full, the checks and the gifts due at once, the rotation and the cooldowns empty).
    virtual void reset_for_game() = 0;
    //  Stop Pokémon GO and take it out of the recent apps.
    virtual void close_game_completely() = 0;
    //  The battles of the run for this app (auto_battle()): they ask the run for beat() now and then, stop() and time_up() to know when to end.  Throws
    //  std::runtime_error when they fail.
    virtual Start::AutoBattle auto_battle(const QString& package, const Beat& beat, const Ask& stop, const Ask& time_up) = 0;
    //  Is it time to bring the teams up to date (teams_due()), and doing it (teams_refresh()).
    virtual bool teams_due(const QString& package) = 0;
    virtual void teams_refresh(const QString& package, const Ask& stop) = 0;
    //  The watchdog of one app starts and stops (start_watchdog()).
    virtual void watchdog(const QString& package, bool start) = 0;
    //  The time of the day: the moment of hh:mm on the day (the local day) of `now` (time.mktime(...), hours and minutes that are too big or too small
    //  go to the next or the last day), and a moment as 'YYYY-MM-DD HH:MM' (time.strftime) in the local time.
    virtual double slot_time(double now, int hours, int minutes) = 0;
    virtual QString local_text(double moment) = 0;
};


//  Python's float() and int() of what the person set (a number, or a text), for the numbers of the run.
std::optional<double> py_float(const QJsonValue& value);
std::optional<int> py_int(const QString& text);


//  The newest start time of the day (set in the web interface) that has passed.
double last_slot(Host& host, double now);
//  Minutes that a run may take, all the apps together: 1 to 1440.
double daily_limit(Host& host);
//  The apps of the run in the order they are played (the one that fights battles first, when battles are wanted).
QStringList daily_order(Host& host);
//  The file of the run (or what the run starts with when there is none).
QJsonObject load_daily(Host& host);
//  The time is up: a catch that is going on is finished first (at most FINISH_MAX_S).  `beat` may be empty.
void finish_catch(Host& host, const Beat& beat);
//  One app of the run; says whether it is over (false: the run was switched off).  `daily` is the content of the file, it is changed and written.
bool run_one_game(Host& host, State& state, const QString& package, QJsonObject& daily);
//  What the bot does instead of a plain step in the daily run: the seconds to wait afterwards.
double daily_cycle(Host& host, State& state);


//  ---- the check

//  Plays the stories of the file of Mobile/tools/make_daily_golden.py (tests/fixtures/daily_golden.json.qz) and says where the port does something else
//  than the Python code did.  Returns how many went another way ("FAILED: ..." lines in `report` say which, the last line says how many were played).
int run_daily_checks(const QString& golden, QStringList& report, bool stop_at_first = false);


}
}
}
}
#endif
