/*  Claude GG Pokemon GO Daily (the daily run of the Pokémon GO bot: every app of the phone once a day, at the time the person chose)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  See ClaudeGG_PokemonGoDaily.h.  The functions follow those of Mobile/gamebot.py line by line; the names of the comments are theirs.
 *
 */

#include <stdexcept>
#include <QJsonArray>
#include "ClaudeGG_PokemonGoDaily.h"
#include "ClaudeGG_PokemonGoFlow.h"
#include "ClaudeGG_PokemonGoPy.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Daily{

using Py::fixed;

namespace{

//  Python's max(a, b) and min(a, b): the first one, unless the second is larger (smaller); so a NaN that comes first stays.
double py_max(double a, double b){
    return b > a ? b : a;
}
double py_min(double a, double b){
    return b < a ? b : a;
}

//  bool(x) of a value of the file.
bool truthy(const QJsonValue& v){
    switch (v.type()){
    case QJsonValue::Bool:
        return v.toBool();
    case QJsonValue::Double:
        return v.toDouble() != 0;
    case QJsonValue::String:
        return !v.toString().isEmpty();
    case QJsonValue::Array:
        return !v.toArray().isEmpty();
    case QJsonValue::Object:
        return !v.toObject().isEmpty();
    default:
        return false;
    }
}

//  A number of the file (a bool counts as 0 or 1, as in Python).
double number(const QJsonValue& v){
    return v.isBool() ? (v.toBool() ? 1.0 : 0.0) : v.toDouble();
}

//  ==, as Python compares two values of the file (1 == 1.0 == True).
bool py_equal(const QJsonValue& a, const QJsonValue& b){
    const bool na = a.isDouble() || a.isBool();
    const bool nb = b.isDouble() || b.isBool();
    if (na && nb){
        return number(a) == number(b);
    }
    if (a.isUndefined() || b.isUndefined()){
        return a.isUndefined() == b.isUndefined() || (a.isNull() || b.isNull());
    }
    return a == b;
}

//  d["done"] (a KeyError when it is not there).
QJsonArray done_of(const QJsonObject& d){
    if (!d.contains("done")){
        throw std::runtime_error("'done'");
    }
    return d.value("done").toArray();
}

bool contains(const QJsonArray& list, const QString& item){
    for (const QJsonValue& v : list){
        if (v.isString() && v.toString() == item){
            return true;
        }
    }
    return false;
}

double sum_played(const QJsonObject& played){
    double sum = 0;
    for (auto it = played.begin(); it != played.end(); ++it){
        sum += number(it.value());
    }
    return sum;
}

}   //  namespace


double daily_limit(Host& host){
    const QJsonValue v = host.setting("daily_max_min");
    double x = DAILY_MAX_MIN;
    if (v.isUndefined()){
        x = DAILY_MAX_MIN;
    }else if (v.isDouble() || v.isBool()){
        x = number(v);
    }else if (v.isString()){
        if (!Py::py_parse_float(v.toString(), x)){
            return DAILY_MAX_MIN;                                   //  ValueError
        }
    }else{
        return DAILY_MAX_MIN;                                       //  TypeError (None, a list, ...)
    }
    return py_min(py_max(x, 1), 1440);
}


double last_slot(Host& host, double now){
    int hh = 8;
    int mm = 0;
    const QJsonValue v = host.setting("daily_time");
    //  str(...).split(":") into two int(): only a text can have the two parts.
    const QString text = v.isUndefined() ? QString("08:00") : v.isString() ? v.toString() : QString();
    const QStringList parts = text.split(':');
    if (parts.size() == 2){
        bool ok_h = false;
        bool ok_m = false;
        const int h = Py::py_strip(parts[0]).toInt(&ok_h);
        const int m = Py::py_strip(parts[1]).toInt(&ok_m);
        if (ok_h && ok_m){
            hh = h;
            mm = m;
        }
    }
    const double slot = host.local_time_of_day(now, hh, mm);
    return slot <= now ? slot : slot - 86400;
}


QStringList daily_order(Host& host){
    //  (battle_wanted() is false: the battles are not ported)
    return host.game_packages();
}


void finish_catch(Host& host, const std::function<void()>& beat){
    const double t_end = host.wall() + FINISH_MAX_S;
    bool told = false;
    while (host.wall() < t_end){
        QString name;
        try{
            name = host.screen_name();
        }catch (const Flow::Interrupted&){
            throw;                                                  //  (the person stops the bot: not an Exception in Python)
        }catch (const std::exception&){
            return;
        }
        if (name == "mapScreen"){
            return;
        }
        if (name != "encounterScreen" && !told){
            return;                                                 //  (not catching: nothing to finish)
        }
        if (!told){
            host.log("daily run: the run time is up - finishing this catch first");
            told = true;
        }
        double wait = 0;
        try{
            wait = host.step();
        }catch (const Flow::Interrupted&){
            throw;
        }catch (const std::exception& e){
            host.log("error: " + QString::fromUtf8(e.what()));
            wait = 5;
        }
        if (beat){
            beat();
        }
        host.sleep(py_min(wait, py_max(0.0, t_end - host.wall())));
    }
}


bool run_one_game(Host& host, State& state, const QString& pkg, QJsonObject& d){
    (void)state;
    host.reset_for_game(pkg);
    //  played = d.setdefault("played", {}): seconds per game, kept when the bot restarts
    if (!d.contains("played")){
        d.insert("played", QJsonObject());
    }
    auto played = [&](){ return d.value("played").toObject(); };
    auto set_played = [&](const QString& key, double value){
        QJsonObject p = played();
        p.insert(key, value);
        d.insert("played", p);
    };
    auto played_of = [&](const QString& key){
        const QJsonObject p = played();
        return p.contains(key) ? number(p.value(key)) : 0.0;
    };
    if (sum_played(played()) > daily_limit(host) * 60){             //  (the bot was restarted after the time was up: nothing left to play)
        host.log("daily run: the run time of " + fixed(daily_limit(host), 0) + " min is up - closing the game");
        host.close_game_completely();
        d.insert("time_up", true);
        return true;
    }
    {
        const double sum = sum_played(played());
        host.log(
            "daily run: starting " + pkg + " (the run stops after " + fixed(daily_limit(host), 0) + " min" +
            (sum != 0 ? ", " + fixed(sum / 60, 0) + " min played)" : QString(")"))
        );
    }
    host.game_packages();                                           //  pkgs_now (for the battles, which are not ported)
    double clock_last = host.monotonic();                           //  all the time counts, also the start of the game and a long step
    host.restart_game();

    auto beat = [&](){                                              //  book the time so far
        const double mono = host.monotonic();
        set_played(pkg, played_of(pkg) + (mono - clock_last));
        clock_last = mono;
    };
    auto time_up = [&](){                                           //  finish what is going on, start nothing new
        return sum_played(played()) + (host.monotonic() - clock_last) > daily_limit(host) * 60;
    };

    if (!host.run_done()){
        //  (auto_battle(): the battles are not ported - nothing to fight)
        beat();
    }
    //  (teams_due() is false: the weekly teams are not ported)
    double saved = host.wall();
    double reported = played_of(pkg);
    while (!host.run_done()){
        if (!host.wanted("daily_cycle")){
            host.log("daily run switched off");
            host.save_daily(d);
            return false;
        }
        const double mono = host.monotonic();
        const double now = host.wall();
        set_played(pkg, played_of(pkg) + (mono - clock_last));     //  monotonic: a jump of the clock (NTP) does not count
        clock_last = mono;
        {
            //  d["slot"] = max(d.get("slot", 0), last_slot(now)): a start time that passes during a run is used up by that run
            const QJsonValue old = d.contains("slot") ? d.value("slot") : QJsonValue(0);
            const double slot = last_slot(host, now);
            if (slot > number(old)){
                d.insert("slot", slot);
            }else{
                d.insert("slot", old);
            }
        }
        if (now - saved > 60){
            host.save_daily(d);
            saved = now;
        }
        if (played_of(pkg) - reported >= 1800){                    //  now and then: how far is it
            reported = played_of(pkg);
            host.log("daily run: " + fixed(sum_played(played()) / 60, 0) + " of " + fixed(daily_limit(host), 0) + " min played");
        }
        if (time_up()){
            finish_catch(host, beat);
            host.log("daily run: the run time of " + fixed(daily_limit(host), 0) + " min is up - closing the game, the run ends");
            host.close_game_completely();
            d.insert("time_up", true);
            break;
        }
        double wait = 0;
        try{
            wait = host.step();
        }catch (const Flow::Interrupted&){
            throw;
        }catch (const std::exception& e){
            host.log("error: " + QString::fromUtf8(e.what()));
            wait = 10;
        }
        //  (the way back to the battles after the Pokémon of a reward: the battles are not ported)
        host.sleep(wait);
    }
    host.save_daily(d);
    host.log("daily run: " + pkg + " finished");
    return true;
}


double daily_cycle(Host& host, State& state){
    QJsonObject d = host.load_daily();
    const double now = host.wall();
    auto new_run = [&](){
        return QJsonObject{{"start", now}, {"done", QJsonArray()}, {"slot", last_slot(host, now)}};
    };
    const QString how = host.take_force_start();
    if (!how.isEmpty()){
        QStringList unfinished;
        const QJsonArray done = d.value("done").toArray();
        for (const QString& p : daily_order(host)){
            if (!contains(done, p)){
                unfinished << p;
            }
        }
        //  Start button: always a fresh run.  Otherwise (e.g. restart after an update) a run that is still going just continues, and a
        //  finished one starts again.
        if (how == "button" || unfinished.isEmpty()){
            d = new_run();
            host.save_daily(d);
            host.log(QString(how == "button" ? "Start pressed" : "bot started") + " - daily run starts now: " + daily_order(host).join(", "));
            state.waiting_logged = false;
        }
    }
    //  served: the latest start time that a run has already used
    double served = 0;
    const QJsonValue slot = d.value("slot");
    if (slot.isUndefined() || slot.isNull()){                       //  file of an older version
        served = truthy(d.value("start")) ? last_slot(host, number(d.value("start"))) : 0;
    }else{
        served = number(slot);
    }
    const double latest = last_slot(host, now);
    if (now >= latest && latest > served){                          //  today's start time passed and no run has used it yet
        d = new_run();
        host.save_daily(d);
        const QStringList pkgs = daily_order(host);
        host.log("daily run started: " + pkgs.join(", "));
        state.waiting_logged = false;
    }
    QStringList pkgs;
    {
        //  [p for p in daily_order() if p not in d["done"]]: d["done"] is looked up for the first app
        const QStringList order = daily_order(host);
        for (const QString& p : order){
            if (!contains(done_of(d), p)){
                pkgs << p;
            }
        }
    }
    if (!pkgs.isEmpty()){                                           //  (also continues a run after a restart)
        const QString pkg = pkgs[0];
        if (run_one_game(host, state, pkg, d)){
            QJsonArray done = done_of(d);
            done.append(pkg);
            d.insert("done", done);
            if (truthy(d.value("time_up"))){                        //  the run time is up: the other games are not played this run
                QJsonArray all;
                for (const QJsonValue& v : done){
                    if (!all.contains(v)){
                        all.append(v);
                    }
                }
                for (const QString& p : daily_order(host)){
                    if (!all.contains(QJsonValue(p))){
                        all.append(p);
                    }
                }
                d.insert("done", all);
                host.log("daily run: stopped - the run time is up");
            }
            host.save_daily(d);
        }
        return 5;
    }
    const QJsonValue setting = host.setting("daily_time");
    const QJsonValue key_time = setting.isUndefined() ? QJsonValue("08:00") : setting;
    const QJsonValue key_start = d.contains("start") ? d.value("start") : QJsonValue(0);
    if (!state.waiting_logged || !py_equal(state.logged_time, key_time) || !py_equal(state.logged_start, key_start)){
        const QString next = host.local_text(last_slot(host, now) + 86400);
        host.log(QString("daily run ") + (truthy(d.value("start")) ? "complete" : "waiting") + " - next run at " + next);
        state.waiting_logged = true;
        state.logged_time = key_time;
        state.logged_start = key_start;
    }
    return 60;
}


}
}
}
}
