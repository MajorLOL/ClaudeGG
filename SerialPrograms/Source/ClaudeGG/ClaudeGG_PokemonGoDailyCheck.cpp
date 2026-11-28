/*  Claude GG Pokemon GO Daily Check (the daily run, played on the stories of the Python code)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The file of Mobile/tools/make_daily_golden.py holds stories of what gamebot.py does in the daily run: several calls of daily_cycle(), the way
 *  the loop of the bot makes them, on a pretend bot and a fake clock (the local time zone is UTC).  What the code was GIVEN: the apps of the
 *  phone, the wait of every step (or what it raised), what a screen is.  What it DID: the log lines, the waits, the file as it was saved, the
 *  app that was reset and started, the closing of the game, the steps and the looks, and what every call returned (or raised).  The first
 *  event that differs ends that story.
 *
 */

#include <cmath>
#include <stdexcept>
#include <QDate>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include "ClaudeGG_PokemonGoDaily.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Daily{

namespace{

struct Abort{};

QString text_of(const QJsonValue& v){
    if (v.isObject()){
        return QString::fromUtf8(QJsonDocument(v.toObject()).toJson(QJsonDocument::Compact));
    }
    if (v.isArray()){
        return QString::fromUtf8(QJsonDocument(v.toArray()).toJson(QJsonDocument::Compact));
    }
    return QString::fromUtf8(QJsonDocument(QJsonArray{v}).toJson(QJsonDocument::Compact));
}

//  The same value: numbers to a millionth.
bool same(const QJsonValue& a, const QJsonValue& b){
    if (a.isDouble() && b.isDouble()){
        return std::fabs(a.toDouble() - b.toDouble()) <= 1e-6 * std::max(1.0, std::fabs(a.toDouble()));
    }
    if (a.type() != b.type()){
        return false;
    }
    if (a.isObject()){
        const QJsonObject x = a.toObject();
        const QJsonObject y = b.toObject();
        if (x.keys() != y.keys()){
            return false;
        }
        for (const QString& k : x.keys()){
            if (!same(x.value(k), y.value(k))){
                return false;
            }
        }
        return true;
    }
    if (a.isArray()){
        const QJsonArray x = a.toArray();
        const QJsonArray y = b.toArray();
        if (x.size() != y.size()){
            return false;
        }
        for (qsizetype i = 0; i < x.size(); i++){
            if (!same(x.at(i), y.at(i))){
                return false;
            }
        }
        return true;
    }
    return a == b;
}


class Replay : public Host{
public:
    Replay(const QJsonObject& test_case)
        : m_spec(test_case.value("spec").toObject())
        , m_events(test_case.value("events").toArray())
        , m_settings(m_spec.value("settings").toObject())
        , m_file(m_spec.value("file"))
        , m_force(m_spec.value("force").toString())
    {}

    double t = 0;
    int call = 0;
    bool failed = false;
    QString message;

    [[noreturn]] void fail(const QString& what){
        failed = true;
        message = QString("event %1: %2").arg(m_at).arg(what);
        throw Abort();
    }
    //  The next event, which has to be of this kind and at this time.
    QJsonArray next(const QString& kind, const QString& doing){
        if (m_at >= m_events.size()){
            fail("the port " + doing + ", the Python code did nothing more");
        }
        const QJsonArray event = m_events.at(m_at).toArray();
        if (event.at(0).toString() != kind){
            fail("the Python code did " + text_of(event) + ", the port " + doing);
        }
        if (std::fabs(event.at(1).toDouble() - t) > 1e-6){
            fail(QString("the Python code did %1 at %2, the port at %3").arg(text_of(event)).arg(event.at(1).toDouble(), 0, 'f', 3).arg(t, 0, 'f', 3));
        }
        m_at++;
        return event;
    }
    void finish(){
        if (m_at != m_events.size()){
            fail("the Python code went on with " + text_of(m_events.at(m_at)) + ", the port stopped");
        }
    }

    double wall() override{ return t; }
    double monotonic() override{ return t; }
    void sleep(double seconds) override{
        const QJsonArray e = next("sleep", QString("waited %1 s").arg(seconds));
        if (!same(e.at(2), seconds)){
            fail(QString("the Python code waited %1 s, the port %2 s").arg(e.at(2).toDouble()).arg(seconds));
        }
        t += seconds;
    }
    void log(const QString& text) override{
        const QJsonArray e = next("log", "logged: " + text);
        if (e.at(2).toString() != text){
            fail("the Python code logged: " + e.at(2).toString() + "\nthe port: " + text);
        }
    }
    QJsonValue setting(const QString& key) override{
        return m_settings.contains(key) ? m_settings.value(key) : QJsonValue(QJsonValue::Undefined);
    }
    bool wanted(const QString& key) override{
        const QJsonValue off = m_spec.value("off_at");
        if (key == "daily_cycle" && off.isDouble() && t >= off.toDouble()){
            return false;
        }
        if (!m_settings.contains(key)){
            return true;
        }
        const QJsonValue v = m_settings.value(key);
        return v.isBool() ? v.toBool() : v.isDouble() ? v.toDouble() != 0 : v.isString() ? !v.toString().isEmpty() : !v.isNull();
    }
    QJsonObject load_daily() override{
        if (!m_file.isObject()){
            return QJsonObject{{"start", 0}, {"done", QJsonArray()}};
        }
        return m_file.toObject();
    }
    void save_daily(const QJsonObject& d) override{
        const QJsonArray e = next("save", "saved " + text_of(d));
        if (!same(e.at(2), d)){
            fail("the Python code saved " + text_of(e.at(2)) + ", the port " + text_of(d));
        }
        m_file = d;
    }
    QStringList game_packages() override{
        const QJsonArray e = next("packages", "asked for the apps");
        QStringList out;
        for (const QJsonValue& v : e.at(2).toArray()){
            out << v.toString();
        }
        return out;
    }
    void reset_for_game(const QString& package) override{
        const QJsonArray e = next("reset", "started a game of " + package);
        if (e.at(2).toString() != package){
            fail("the Python code started a game of " + e.at(2).toString() + ", the port of " + package);
        }
        m_done = false;
    }
    void restart_game() override{
        next("restart", "started the game");
        const QString why = m_spec.value("restart_fail").toString();
        if (!why.isEmpty()){
            throw std::runtime_error(why.toStdString());
        }
    }
    void close_game_completely() override{
        next("close", "closed the game");
    }
    double step() override{
        const QJsonArray e = next("step", "made a step");
        t += e.at(4).toDouble();
        if (!e.at(3).isNull()){
            throw std::runtime_error(e.at(3).toString().toStdString());
        }
        if (e.at(5).toBool()){
            m_done = true;
        }
        return e.at(2).toDouble();
    }
    bool run_done() override{ return m_done; }
    QString screen_name() override{
        const QJsonArray e = next("shot", "looked at the screen");
        if (e.at(2).isNull()){
            throw std::runtime_error("the phone did not answer");
        }
        return e.at(2).toString();
    }
    QString take_force_start() override{
        //  (force_call: the Start button is pressed before that call of the story)
        const int at = m_spec.value("force_call").toInt(0);
        if (at != 0 && call < at){
            return QString();
        }
        const QString out = m_force;
        m_force.clear();
        return out;
    }
    double local_time_of_day(double now, int hh, int mm) override{
        return std::floor(now / 86400) * 86400 + hh * 3600.0 + mm * 60.0;
    }
    QString local_text(double when) override{
        const double days = std::floor(when / 86400);
        const int minutes = (int)std::floor((when - days * 86400) / 60);
        return QDate(1970, 1, 1).addDays((qint64)days).toString("yyyy-MM-dd") +
            QString(" %1:%2").arg(minutes / 60, 2, 10, QChar('0')).arg(minutes % 60, 2, 10, QChar('0'));
    }

    const QJsonObject& spec() const{ return m_spec; }

private:
    QJsonObject m_spec;
    QJsonArray m_events;
    QJsonObject m_settings;
    QJsonValue m_file;
    QString m_force;
    qsizetype m_at = 0;
    bool m_done = false;
};


QString play(const QJsonObject& test_case, double start){
    Replay host(test_case);
    host.t = start;
    State state;
    try{
        const int calls = host.spec().value("calls").toInt(1);
        for (int i = 0; i < calls; i++){
            host.call = i;
            try{
                const double r = daily_cycle(host, state);
                const QJsonArray e = host.next("result", QString("returned %1").arg(r));
                if (!same(e.at(2), r)){
                    host.fail(QString("the Python code returned %1, the port %2").arg(e.at(2).toDouble()).arg(r));
                }
                host.t += r;
            }catch (const Abort&){
                throw;
            }catch (const std::exception& e){
                const QString what = QString::fromUtf8(e.what());
                const QJsonArray event = host.next("raised", "raised: " + what);
                if (event.at(2).toString() != what){
                    host.fail("the Python code raised: " + event.at(2).toString() + ", the port: " + what);
                }
                host.t += 10;
            }
        }
        host.finish();
    }catch (const Abort&){
    }
    return host.failed ? host.message : QString();
}

}   //  namespace


int run_daily_checks(const QString& golden, QStringList& report, bool stop_at_first){
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the stories of the daily run are not there: " + golden;
        return 1;
    }
    const QJsonObject root = QJsonDocument::fromJson(qUncompress(file.readAll())).object();
    const QJsonArray cases = root.value("cases").toArray();
    const double start = root.value("start").toDouble();
    int failed = 0;
    for (const QJsonValue& v : cases){
        const QJsonObject test_case = v.toObject();
        const QString what = play(test_case, start);
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
    report << QString("daily run: %1 stories played, %2 went another way").arg(cases.size()).arg(failed);
    return failed;
}


}
}
}
}
