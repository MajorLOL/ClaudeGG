/*  Claude GG Pokemon GO Daily (the daily run of the Pokémon GO bot)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  See ClaudeGG_PokemonGoDaily.h.  What the Python code does is followed line by line, down to the order of the questions that it asks (every
 *  battle_app() of daily_order() is a question), the log lines and the moments of the writes of the file.
 *
 */

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <stdexcept>
#include <utility>
#include <vector>
#include <QRegularExpression>
#include "ClaudeGG_PokemonGoDaily.h"
#include "ClaudeGG_PokemonGoFlow.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Daily{

namespace{

//  f"{x:.0f}"
QString fmt0(double x){
    if (std::isnan(x)){
        return "nan";                                   //  (never "-nan")
    }
    if (std::isinf(x)){
        return x < 0 ? "-inf" : "inf";
    }
    char buffer[400];                                   //  (a double has 309 digits at most)
    std::snprintf(buffer, sizeof(buffer), "%.0f", x);
    return QString::fromLatin1(buffer);
}

//  The digits of every script as the digits 0 - 9 (Python's int() and float() take them all), the rest as it is.
QString ascii_digits(const QString& text){
    QString out;
    for (const QChar c : text){
        out += c.isDigit() ? QChar('0' + c.digitValue()) : c;
    }
    return out;
}

//  Python's truth of a value of JSON.
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

bool has(const QJsonArray& items, const QString& text){
    for (const QJsonValue& v : items){
        if (v.isString() && v.toString() == text){
            return true;
        }
    }
    return false;
}

//  The seconds that each app was played, in the order they were played.
struct Played{
    std::vector<std::pair<QString, double>> items;

    explicit Played(const QJsonObject& o){
        for (auto it = o.begin(); it != o.end(); ++it){
            items.emplace_back(it.key(), it.value().toDouble());
        }
    }
    double get(const QString& pkg) const{
        for (const std::pair<QString, double>& one : items){
            if (one.first == pkg){
                return one.second;
            }
        }
        return 0.0;
    }
    void add(const QString& pkg, double seconds){
        const double total = get(pkg) + seconds;
        for (std::pair<QString, double>& one : items){
            if (one.first == pkg){
                one.second = total;
                return;
            }
        }
        items.emplace_back(pkg, total);
    }
    double sum() const{
        double total = 0.0;
        for (const std::pair<QString, double>& one : items){
            total += one.second;
        }
        return total;
    }
    QJsonObject object() const{
        QJsonObject o;
        for (const std::pair<QString, double>& one : items){
            o[one.first] = one.second;
        }
        return o;
    }
};

}


std::optional<double> py_float(const QJsonValue& value){
    switch (value.type()){
    case QJsonValue::Double:
        return value.toDouble();
    case QJsonValue::Bool:
        return value.toBool() ? 1.0 : 0.0;
    case QJsonValue::String:
        break;
    default:
        return std::nullopt;                            //  (None, a list: TypeError)
    }
    const QString text = ascii_digits(value.toString().trimmed());
    static const QRegularExpression special("^[+-]?(nan|inf|infinity)$", QRegularExpression::CaseInsensitiveOption);
    if (special.match(text).hasMatch()){
        const QString lower = text.toLower();
        const bool negative = lower.startsWith('-');
        if (lower.endsWith("nan")){
            return std::nan("");
        }
        return negative ? -HUGE_VAL : HUGE_VAL;
    }
    static const QRegularExpression number(
        "^[+-]?(?:[0-9]+(?:_[0-9]+)*(?:\\.(?:[0-9]+(?:_[0-9]+)*)?)?|\\.[0-9]+(?:_[0-9]+)*)(?:[eE][+-]?[0-9]+(?:_[0-9]+)*)?$");
    if (!number.match(text).hasMatch()){
        return std::nullopt;                            //  (ValueError)
    }
    QString plain = text;
    plain.remove('_');
    return std::strtod(plain.toLatin1().constData(), nullptr);
}

std::optional<int> py_int(const QString& text){
    const QString trimmed = ascii_digits(text.trimmed());
    static const QRegularExpression number("^[+-]?[0-9]+(?:_[0-9]+)*$");
    if (!number.match(trimmed).hasMatch()){
        return std::nullopt;
    }
    QString plain = trimmed;
    plain.remove('_');
    const bool negative = plain.startsWith('-');
    if (plain.startsWith('-') || plain.startsWith('+')){
        plain.remove(0, 1);
    }
    while (plain.size() > 1 && plain.startsWith('0')){
        plain.remove(0, 1);
    }
    if (plain.size() > 9){
        return std::nullopt;                            //  (too big: Python would fail in mktime())
    }
    const int n = plain.toInt();
    return negative ? -n : n;
}


double last_slot(Host& host, double now){
    int hours = 8;
    int minutes = 0;
    const QJsonValue set = host.setting_value("daily_time");
    const QString text = set.isUndefined() ? QString("08:00") : (set.isString() ? set.toString() : QString("not a time"));
    const QStringList parts = text.split(':');
    if (parts.size() == 2){
        const std::optional<int> h = py_int(parts[0]);
        const std::optional<int> m = h.has_value() ? py_int(parts[1]) : std::nullopt;
        if (h.has_value() && m.has_value()){
            hours = *h;
            minutes = *m;
        }
    }
    const double slot = host.slot_time(now, hours, minutes);
    return slot <= now ? slot : slot - 86400;
}

double daily_limit(Host& host){
    const QJsonValue set = host.setting_value("daily_max_min");
    const std::optional<double> x = set.isUndefined() ? std::optional<double>(MAX_MIN) : py_float(set);
    if (!x.has_value()){
        return MAX_MIN;
    }
    //  min(max(x, 1), 1440) as Python does it (a number that is not a number stays what it is)
    const double low = (1.0 > *x) ? 1.0 : *x;
    return (1440.0 < low) ? 1440.0 : low;
}

QStringList daily_order(Host& host){
    QStringList pkgs = host.game_packages();
    if (host.battle_wanted() && pkgs.contains(host.battle_app())){
        QStringList out;
        out << host.battle_app();
        for (const QString& p : pkgs){
            if (p != host.battle_app()){
                out << p;
            }
        }
        pkgs = out;
    }
    return pkgs;
}

QJsonObject load_daily(Host& host){
    const std::optional<QJsonObject> file = host.read_daily();
    if (file.has_value()){
        return *file;
    }
    QJsonObject fresh;
    fresh["start"] = 0;
    fresh["done"] = QJsonArray();
    return fresh;
}


void finish_catch(Host& host, const Beat& beat){
    const double t_end = host.wall() + FINISH_MAX_S;
    bool told = false;
    while (host.wall() < t_end){
        QString name;
        try{
            name = host.screen_class(host.screenshot()).first;
        }catch (const Flow::Interrupted&){
            throw;
        }catch (const std::exception&){
            return;
        }
        if (name == "mapScreen"){
            return;
        }
        if (name != "encounterScreen" && !told){
            return;                                     //  (not catching: nothing to finish)
        }
        if (!told){
            host.log("daily run: the run time is up - finishing this catch first");
            told = true;
        }
        double wait = 0.0;
        try{
            wait = host.daily_step();
        }catch (const Flow::Interrupted&){
            throw;
        }catch (const std::exception& e){
            host.log(QString("error: %1").arg(QString::fromUtf8(e.what())));
            wait = 5;
        }
        if (beat){
            beat();
        }
        const double left = t_end - host.wall();
        host.sleep(std::min(wait, left > 0.0 ? left : 0.0));
    }
}


namespace{

//  What run_one_game() does while the watchdog is on: the game is started again, the battles, the teams, the steps.  Says whether the run carries on
//  (false: it was switched off).
bool play_game(Host& host, State& state, const QString& package, QJsonObject& daily, Played& played, double& last, const std::function<void()>& save){
    host.restart_game();

    const Beat beat = [&]{                              //  book the time so far; also tells the watchdog that the bot lives
        const double mono = host.monotonic();
        played.add(package, mono - last);
        last = mono;
    };
    const Ask stop = [&]{                               //  stop at once (also in the middle of a fight)
        return state.done || !host.wanted("daily_cycle");
    };
    const Ask time_up = [&]{                            //  finish what is going on, start nothing new
        return played.sum() + (host.monotonic() - last) > daily_limit(host) * 60;
    };
    const auto battles = [&]{
        try{
            const Start::AutoBattle result = host.auto_battle(package, beat, stop, time_up);
            if (result.resume.has_value()){
                state.battle_resume = *result.resume;
            }
        }catch (const Flow::Interrupted&){
            throw;
        }catch (const std::exception& e){
            host.log(QString("battle: error %1").arg(QString::fromUtf8(e.what())));
        }
        beat();
    };

    if (!state.done){
        battles();
    }
    if (!state.done && host.teams_due(package)){
        try{
            host.teams_refresh(package, [&]{ return stop() || time_up(); });
        }catch (const Flow::Interrupted&){
            throw;
        }catch (const std::exception& e){
            host.log(QString("teams: error %1").arg(QString::fromUtf8(e.what())));
        }
        beat();
    }
    double saved = host.wall();
    double reported = played.get(package);
    int resumes = 0;
    while (!state.done){
        if (!host.wanted("daily_cycle")){
            host.log("daily run switched off");
            save();
            return false;
        }
        const double mono = host.monotonic();
        const double now = host.wall();
        played.add(package, mono - last);               //  monotonic: a jump of the clock (NTP) does not count
        last = mono;
        const QJsonValue slot = daily.value("slot");    //  a start time that passes during a run is used up by that run
        const double before = slot.isDouble() ? slot.toDouble() : 0.0;
        const double after = last_slot(host, now);
        daily["slot"] = (after > before) ? after : before;
        if (now - saved > SAVE_EVERY){
            save();
            saved = now;
        }
        if (played.get(package) - reported >= REPORT_EVERY){            //  now and then: how far is it
            reported = played.get(package);
            host.log(QString("daily run: %1 of %2 min played").arg(fmt0(played.sum() / 60), fmt0(daily_limit(host))));
        }
        if (time_up()){
            finish_catch(host, beat);
            host.log(QString("daily run: the run time of %1 min is up - closing the game, the run ends").arg(fmt0(daily_limit(host))));
            host.close_game_completely();
            daily["time_up"] = true;
            break;
        }
        double wait = 0.0;
        try{
            wait = host.daily_step();
        }catch (const Flow::Interrupted&){
            throw;
        }catch (const std::exception& e){
            host.log(QString("error: %1").arg(QString::fromUtf8(e.what())));
            wait = 10;
        }
        //  The reward of a set was a Pokémon to catch: the normal bot caught it (or it fled) - back on the map, the battles go on (at most a few
        //  times a run)
        if (state.battle_resume && resumes < BATTLE_RESUMES){
            bool back = false;
            try{
                back = host.on_map(host.screenshot());
            }catch (const Flow::Interrupted&){
                throw;
            }catch (const std::exception&){
                back = false;
            }
            if (back){
                resumes++;
                state.battle_resume = false;
                host.log("battle: the Pokémon of the reward was caught - back to the battles");
                battles();
                continue;
            }
        }
        host.sleep(wait);
    }
    return true;
}

}


bool run_one_game(Host& host, State& state, const QString& package, QJsonObject& daily){
    host.set_package(package);
    state.done = false;
    host.reset_for_game();
    if (!daily.contains("played")){
        daily["played"] = QJsonObject();
    }
    Played played(daily.value("played").toObject());
    //  (the Python code changes the dict of the file in place: it is written back whenever the file is, and when this ends)
    struct Keep{
        QJsonObject& daily;
        Played& played;
        ~Keep(){ daily["played"] = played.object(); }
    } keep{daily, played};
    const auto save = [&]{
        daily["played"] = played.object();
        host.write_daily(daily);
    };
    if (played.sum() > daily_limit(host) * 60){         //  (the bot was restarted after the time was up: nothing left to play)
        host.log(QString("daily run: the run time of %1 min is up - closing the game").arg(fmt0(daily_limit(host))));
        host.close_game_completely();
        daily["time_up"] = true;
        return true;
    }
    host.log(QString("daily run: starting %1 (the run stops after %2 min").arg(package, fmt0(daily_limit(host)))
        + (played.sum() != 0.0 ? QString(", %1 min played)").arg(fmt0(played.sum() / 60)) : QString(")")));
    const QStringList pkgs_now = host.game_packages();
    if (host.battle_wanted() && package == pkgs_now.value(0) && !pkgs_now.contains(host.battle_app())){      //  (said once per run)
        host.log(QString("battle: the chosen app %1 is not installed - no battles in this run").arg(host.battle_app()));
    }
    double last = host.monotonic();                     //  all the time counts, also the start of the game and a long step
    host.watchdog(package, true);
    //  (what Python does in try: ... finally: watchdog.set())
    bool carries_on = false;
    try{
        carries_on = play_game(host, state, package, daily, played, last, save);
    }catch (...){
        host.watchdog(package, false);
        throw;
    }
    host.watchdog(package, false);
    if (!carries_on){
        return false;
    }
    save();
    host.log(QString("daily run: %1 finished").arg(package));
    return true;
}


double daily_cycle(Host& host, State& state){
    QJsonObject d = load_daily(host);
    const double now = host.wall();
    if (!state.force.isEmpty()){
        const QString how = state.force;
        state.force.clear();
        QStringList unfinished;
        for (const QString& p : daily_order(host)){
            if (!has(d.value("done").toArray(), p)){
                unfinished << p;
            }
        }
        //  Start button: always a fresh run.  Otherwise (e.g. restart after an update) a run that is still going just continues, and a finished one
        //  starts again.
        if (how == "button" || unfinished.isEmpty()){
            QJsonObject fresh;
            fresh["start"] = now;
            fresh["done"] = QJsonArray();
            fresh["slot"] = last_slot(host, now);
            d = fresh;
            host.write_daily(d);
            host.log(QString("%1 - daily run starts now: %2").arg(how == "button" ? "Start pressed" : "bot started", daily_order(host).join(", ")));
            state.waiting.reset();
        }
    }
    double served;                                      //  the latest start time that a run has already used
    const QJsonValue slot = d.value("slot");
    if (slot.isNull() || slot.isUndefined()){           //  file of an older version
        served = truthy(d.value("start")) ? last_slot(host, d.value("start").toDouble()) : 0.0;
    }else{
        served = slot.toDouble();
    }
    const double today = last_slot(host, now);
    if (now >= today && today > served){                //  today's start time passed and no run has used it yet
        QJsonObject fresh;
        fresh["start"] = now;
        fresh["done"] = QJsonArray();
        fresh["slot"] = today;
        d = fresh;
        host.write_daily(d);
        host.log("daily run started: " + daily_order(host).join(", "));
        state.waiting.reset();
    }
    QStringList pkgs;
    for (const QString& p : daily_order(host)){
        if (!d.contains("done")){
            throw std::runtime_error("'done'");
        }
        if (!has(d.value("done").toArray(), p)){
            pkgs << p;
        }
    }
    if (!pkgs.isEmpty()){                               //  (also continues a run after a restart)
        const QString pkg = pkgs.first();
        if (run_one_game(host, state, pkg, d)){
            QJsonArray done = d.value("done").toArray();
            done.append(pkg);
            d["done"] = done;
            if (truthy(d.value("time_up"))){            //  the run time is up: the other games are not played this run
                QStringList merged;
                for (const QJsonValue& v : done){
                    merged << v.toString();
                }
                merged << daily_order(host);
                QJsonArray unique;
                QStringList seen;
                for (const QString& p : merged){
                    if (!seen.contains(p)){
                        seen << p;
                        unique.append(p);
                    }
                }
                d["done"] = unique;
                host.log("daily run: stopped - the run time is up");
            }
            host.write_daily(d);
        }
        return 5;
    }
    const QJsonValue time_value = host.setting_value("daily_time");
    QJsonArray key;
    key.append(time_value.isUndefined() ? QJsonValue(QString("08:00")) : time_value);
    key.append(d.contains("start") ? d.value("start") : QJsonValue(0));
    if (!state.waiting.has_value() || *state.waiting != key){
        const QString next = host.local_text(last_slot(host, now) + 86400);
        host.log(QString("daily run %1 - next run at %2").arg(truthy(d.value("start")) ? "complete" : "waiting", next));
        state.waiting = key;
    }
    return 60;
}


}
}
}
}
