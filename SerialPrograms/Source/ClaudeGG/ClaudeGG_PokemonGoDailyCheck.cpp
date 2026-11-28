/*  Claude GG Pokemon GO Daily Check (the daily run, played on the stories of the Python code)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The file of Mobile/tools/make_daily_golden.py holds stories of what gamebot.py does in the daily run: daily_cycle() called again and again as the loop of the
 *  bot calls it, the start time of the day, the apps one after the other, the time of the run, the battles and the teams, the steps, a catch that is finished.
 *  They are played on a pretend phone with a pretend clock (a day in November 2026 in a pretend time zone one hour east of UTC).  What the code was GIVEN: the
 *  file of the run, the apps that are installed, what the person chose for the battles, the steps (how long they took and what they changed), the screenshots
 *  and what the screen classifier said of them.  What it DID: the log lines, sleeps, writes of the file, the calls to start the game again, to close it, to
 *  fight the battles and to bring the teams up to date, and at the end of every call what it returned and what the run remembers.  The first event that
 *  differs ends that story.
 *
 */

#include <cmath>
#include <stdexcept>
#include <QDateTime>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTimeZone>
#include "ClaudeGG_PokemonGoDaily.h"
#include "ClaudeGG_PokemonGoStory.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Daily{

namespace{

using Story::Abort;
using Story::describe;

constexpr int OFFSET = 3600;                            //  the pretend time zone: one hour east of UTC, no summer time

//  The story has no more steps: it ends here (not a std::exception: the code must not take it for the error of a step).
struct Over{};


class Replay : public Story::Host, public Daily::Host{
public:
    Replay(const QJsonObject& test_case, double start, std::vector<Story::Scene>& cache)
        : Story::Host(test_case, start + test_case.value("spec").toObject().value("at").toDouble(8 * 3600.0), cache)
    {
    }

    State run;                                          //  what the run remembers

    //  A call starts: what the person chose and what the pretend phone does change, then the call event.
    void begin_call(const QJsonObject& call){
        if (call.contains("wanted")){
            const QJsonObject o = call.value("wanted").toObject();
            for (auto it = o.begin(); it != o.end(); ++it){
                m_wanted[it.key()] = it.value();
            }
        }
        if (call.contains("force")){
            run.force = call.value("force").isString() ? call.value("force").toString() : QString();
        }
        if (call.contains("done")){
            run.done = call.value("done").toBool();
        }
        begin(call);
    }

    //  What a step or a script changes (the pretend phone does it; the file is the pretend phone's own).
    void apply(const QJsonObject& effects){
        if (effects.contains("done")){
            run.done = effects.value("done").toBool();
        }
        if (effects.contains("resume")){
            run.battle_resume = effects.value("resume").toBool();
        }
        for (const char* name : {"settings", "wanted"}){
            if (!effects.contains(name)){
                continue;
            }
            const QJsonObject o = effects.value(name).toObject();
            QJsonObject& target = (QString(name) == "settings") ? m_settings : m_wanted;
            for (auto it = o.begin(); it != o.end(); ++it){
                target[it.key()] = it.value();
            }
        }
    }

    //  ---- Loop::Host (the check for the map is the frame's word; what is switched on is on when the story does not say otherwise)
    bool on_map(const cv::Mat& img) override{
        return spec().value("frames").toArray().at(index_of(img)).toObject().value("is_map").toBool();
    }
    bool wanted(const QString& key) override{
        const QJsonValue v = m_wanted.value(key);
        return v.isUndefined() ? true : v.toBool();
    }

    //  ---- Daily::Host
    double daily_step() override{
        const QJsonArray next = peek("a step of the bot");
        if (next.at(0).toString() == "no_step"){        //  (the story has no more steps: it ends here)
            out("no_step", "the story's last step");
            throw Over();
        }
        if (next.at(0).toString() == "step_error"){
            const QJsonArray event = input("step_error", "a step of the bot");
            throw std::runtime_error(event.at(2).toString().toStdString());
        }
        const QJsonArray event = input("step", "a step of the bot");
        apply(event.at(3).toObject());
        return event.at(2).toDouble();
    }
    std::optional<QJsonObject> read_daily() override{
        const QJsonArray event = out("daily_file", "the file of the run is read");
        if (event.at(2).isObject()){
            return event.at(2).toObject();
        }
        return std::nullopt;
    }
    void write_daily(const QJsonObject& daily) override{
        const QJsonArray event = out("daily_save", "the file of the run is written");
        if (!Story::same(event.at(2), daily)){
            fail("the file of the run differs: the Python code wrote " + describe(event.at(2)) + ", the port: " + describe(daily));
        }
    }
    QJsonValue setting_value(const QString& key) override{
        return m_settings.value(key);
    }
    QStringList game_packages() override{
        const QJsonArray event = out("packages", "the list of the installed apps");
        QStringList list;
        for (const QJsonValue& v : event.at(2).toArray()){
            list << v.toString();
        }
        return list;
    }
    bool battle_wanted() override{
        return out("battle_wanted", "are the battles wanted").at(2).toBool();
    }
    QString battle_app() override{
        return out("battle_app", "the app of the battles").at(2).toString();
    }
    void set_package(const QString& package) override{
        m_package = package;
    }
    void reset_for_game() override{
        const QJsonArray event = out("reset", "the flags of the last game are reset");
        if (event.at(2).toString() != m_package){
            fail("the app differs: the Python code reset for " + event.at(2).toString() + ", the port: " + m_package);
        }
    }
    void close_game_completely() override{
        const QJsonArray event = out("close_game", "the game is closed");
        if (event.at(2).toString() != m_package){
            fail("the app differs: the Python code closed " + event.at(2).toString() + ", the port: " + m_package);
        }
    }
    void restart_game() override{
        const QJsonArray next = peek("the game is started again");
        if (next.at(0).toString() == "restart_error"){
            const QJsonArray event = input("restart_error", "the game is started again");
            if (event.at(2).toString() != m_package){
                fail("the app differs: the Python code started " + event.at(2).toString() + ", the port: " + m_package);
            }
            throw std::runtime_error(event.at(3).toString().toStdString());
        }
        const QJsonArray event = input("restart", "the game is started again");
        if (event.at(2).toString() != m_package){
            fail("the app differs: the Python code started " + event.at(2).toString() + ", the port: " + m_package);
        }
        apply(event.at(3).toObject());
    }
    Start::AutoBattle auto_battle(const QString& package, const Beat& on_beat, const Ask& on_stop, const Ask& on_time_up) override{
        const QJsonArray event = out("auto_battle", "the battles of " + package);
        if (event.at(2).toString() != package){
            fail("the app differs: the Python code fought the battles of " + event.at(2).toString() + ", the port: " + package);
        }
        script("battle", [&](const QString& what) -> std::optional<bool>{
            if (what == "beat"){
                on_beat();
                return std::nullopt;
            }
            if (what == "stop"){
                return on_stop();
            }
            return on_time_up();
        });
        const QJsonArray end = input("battle_result", "the end of the battles");
        Start::AutoBattle result;
        result.fought = end.at(2).toInt();
        if (end.at(3).isBool()){
            result.resume = end.at(3).toBool();
        }
        return result;
    }
    bool teams_due(const QString& package) override{
        const QJsonArray event = out("teams_due", "is it time for the teams");
        if (event.at(2).toString() != package){
            fail("the app differs: the Python code asked for " + event.at(2).toString() + ", the port: " + package);
        }
        return event.at(3).toBool();
    }
    void teams_refresh(const QString& package, const Ask& on_stop) override{
        const QJsonArray event = out("teams_refresh", "the teams of " + package);
        if (event.at(2).toString() != package){
            fail("the app differs: the Python code refreshed " + event.at(2).toString() + ", the port: " + package);
        }
        script("teams", [&](const QString&) -> std::optional<bool>{ return on_stop(); });
        out("teams_end", "the end of the teams");
    }
    void watchdog(const QString& package, bool start) override{
        const QJsonArray event = out("watchdog", "the watchdog");
        if (event.at(2).toString() != package || event.at(3).toString() != (start ? "start" : "stop")){
            fail("the watchdog differs: the Python code did " + describe(event) + ", the port: " + QString(start ? "start " : "stop ") + package);
        }
    }
    double slot_time(double moment, int hours, int minutes) override{
        const double midnight = std::floor((moment + OFFSET) / 86400.0) * 86400.0 - OFFSET;
        return midnight + hours * 3600.0 + minutes * 60.0;
    }
    QString local_text(double moment) override{
        return QDateTime::fromSecsSinceEpoch((qint64)std::floor(moment + OFFSET), QTimeZone::utc()).toString("yyyy-MM-dd HH:mm");
    }

private:
    //  The questions that the battles or the teams ask of the run while they go on, as the story has them, until the end of them.
    template <class Ask_>
    void script(const char* kind, const Ask_& ask){
        const QString name = QString::fromLatin1(kind) + "_op";
        while (true){
            const QJsonArray next = peek("what the " + QString::fromLatin1(kind) + " ask of the run");
            if (next.at(0).toString() != name){
                return;
            }
            const QString what = next.at(2).toString();
            if (what == "beat" || what == "stop" || what == "time_up"){
                const std::optional<bool> answer = ask(what);
                if (answer.has_value() && next.at(3).toBool() != *answer){
                    fail(QString("the run answered %1 to '%2', the Python code %3").arg(*answer).arg(what).arg(next.at(3).toBool()));
                }
                input(name.toLatin1().constData(), "a question of the " + QString::fromLatin1(kind));
            }else if (what == "dt"){
                input(name.toLatin1().constData(), "time passes");
            }else if (what == "raise"){
                input(name.toLatin1().constData(), "an error of the " + QString::fromLatin1(kind));
                throw std::runtime_error(next.at(3).toString().toStdString());
            }else if (what == "effects"){
                apply(next.at(3).toObject());
                input(name.toLatin1().constData(), "what the pretend phone changes");
            }else{
                fail("the story has an operation that the check does not know: " + describe(next));
            }
        }
    }

    QString m_package;
};


//  Plays one story; says what went another way (nothing: all of it was the same).
QString play(const QJsonObject& test_case, double start, std::vector<Story::Scene>& cache){
    Replay host(test_case, start, cache);
    try{
        for (const QJsonValue& v : test_case.value("spec").toObject().value("calls").toArray()){
            const QJsonObject call = v.toObject();
            host.begin_call(call);
            const QString fn = call.value("fn").toString();
            try{
                if (fn == "daily_cycle"){
                    host.result(Story::num(daily_cycle(host, host.run)));
                }else if (fn == "run_one_game"){
                    QJsonObject d = call.value("d").toObject();
                    const bool over = run_one_game(host, host.run, call.value("pkg").toString(), d);
                    host.result(over);
                }else if (fn == "finish_catch"){
                    Beat beat;
                    if (call.value("beat").toBool()){
                        beat = [&]{ host.out("beat", "a beat"); };
                    }
                    finish_catch(host, beat);
                    host.result(QJsonValue(QJsonValue::Null));
                }else if (fn == "last_slot"){
                    host.result(Story::num(last_slot(host, call.value("now").toDouble())));
                }else if (fn == "daily_limit"){
                    host.result(Story::num(daily_limit(host)));
                }else if (fn == "daily_order"){
                    QJsonArray list;
                    for (const QString& p : daily_order(host)){
                        list.append(p);
                    }
                    host.result(list);
                }else{
                    host.fail("the story has a call that the check does not know: " + fn);
                }
            }catch (const Abort&){
                throw;
            }catch (const Over&){
                break;                                  //  (no more steps)
            }catch (const std::exception& e){
                host.raised(QString::fromUtf8(e.what()));
            }
            QJsonObject state;
            state["done"] = host.run.done;
            state["waiting"] = host.run.waiting.has_value() ? QJsonValue(*host.run.waiting) : QJsonValue(QJsonValue::Null);
            state["resume"] = host.run.battle_resume;
            host.state(state);
        }
        host.finish_story();
    }catch (const Abort&){
        return host.message;
    }
    return QString();
}


}


int run_daily_checks(const QString& golden, QStringList& report, bool stop_at_first){
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the stories of the daily run are not there: " + golden;
        return 1;
    }
    const QJsonObject root = QJsonDocument::fromJson(qUncompress(file.readAll())).object();
    const QJsonArray cases = root.value("cases").toArray();
    const double start = root.value("start").toDouble(1000.0);
    int failed = 0;
    std::vector<Story::Scene> cache;
    for (const QJsonValue& v : cases){
        const QJsonObject test_case = v.toObject();
        const QString what = play(test_case, start, cache);
        if (!what.isEmpty()){
            report << QString("FAILED: in the story '%1' the port does something else than the Python code: %2").arg(test_case.value("id").toString(), what);
            failed++;
            if (stop_at_first){
                return failed;
            }
        }
    }
    if (cases.isEmpty()){
        report << "FAILED: the file of the daily run has no stories";
        return failed + 1;
    }
    report << QString("daily: %1 stories played, %2 went another way").arg(cases.size()).arg(failed);
    return failed;
}


}
}
}
}
