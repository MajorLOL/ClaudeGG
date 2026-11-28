/*  Claude GG Pokemon GO Step Check (one step of the bot, played on the stories of the Python code)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The file of Mobile/tools/make_step_golden.py holds little stories of step() of gamebot.py (and of heat_wait(), leave_group_screen(),
 *  is_rocket_text(), storage_full() and pause_catching()), played on a pretend phone with a pretend clock (see ClaudeGG_PokemonGoStory.h):
 *  for every call the events in the order in which they happened.  What the code was GIVEN: the screenshots, the answers of the screen
 *  classifier, of the detector of buttons and of the text readers, the temperatures, what Android says of the power state, and what the parts
 *  that are not in this part answered and how long they took (the layout check, the lock screen, the quests, the Team Rocket battle, the map,
 *  the stop and the catch screen).  What it DID: the taps and BACK, the waits, the log lines, the pictures that are kept, the calls of those
 *  parts, and at the end of every call what it returned (or raised) and what it remembers.  The first event that differs ends that story.
 *
 */

#include <cmath>
#include <stdexcept>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include "ClaudeGG_PokemonGoStep.h"
#include "ClaudeGG_PokemonGoStory.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Step{

namespace{

using Story::Abort;
using Story::describe;
using Story::num;
using Story::optional_num;
using Story::same;
using Catch::Detection;


class Replay : public Story::Host, public Step::Host{
public:
    Replay(const QJsonObject& test_case, double start, std::vector<Story::Scene>& cache)
        : Story::Host(test_case, start, cache)
    {
    }

    //  The state of the layout check and of the screen: the host's own (the story's parts change them).
    bool m_screen_ok = true;
    QString m_layout = "confirmed";

    //  ---- Loop::Host (the check for the map is the real one: the pictures decide)
    bool on_map(const cv::Mat& img) override{ return Loop::map_visible(img); }

    //  ---- Flow::Host / Map::Host: what a step does by itself
    void swipe_async(int x1, int y1, int x2, int y2, int ms) override{
        const QString doing = QString("a swipe without waiting (%1, %2) to (%3, %4) in %5 ms").arg(x1).arg(y1).arg(x2).arg(y2).arg(ms);
        const QJsonArray event = out("swipe_async", doing);
        if (event.at(2).toInt() != x1 || event.at(3).toInt() != y1 || event.at(4).toInt() != x2 || event.at(5).toInt() != y2 || event.at(6).toInt() != ms){
            fail("the swipe differs: the Python code did " + describe(event) + ", the port: " + doing);
        }
    }
    void restart_game() override{ out("restart_game", "the game is started again"); }

    //  ---- Catch::Host (the detector of buttons is used by tap_button(); the rest belongs to the catch screen, which is a seam here)
    std::vector<Detection> buttons(const cv::Mat& img) override{
        const int frame = index_of(img);
        const QJsonArray event = input("buttons", QString("a look of the detector of buttons at the picture %1").arg(frame));
        if (event.at(2).toInt() != frame){
            fail("the look differs: the Python code looked at " + describe(event) + ", the port at the picture " + QString::number(frame));
        }
        std::vector<Detection> found;
        for (const QJsonValue& v : event.at(3).toArray()){
            found.push_back(Story::detection_of(v.toArray()));
        }
        return found;
    }
    bool quick_live() override{ return quick_was_live(); }
    double throw_ball(std::optional<bool>&) override{ fail("the code threw a ball"); }
    QString ball() override{ fail("the code asked which ball is wanted"); }
    QStringList berry_order() override{ fail("the code asked which berries are wanted"); }
    std::optional<QString> tray_table(const cv::Mat&) override{ fail("the code read the berry tray"); }
    double step() override{ fail("the code made a step of the bot while finishing a catch"); }

    //  ---- Step::Host
    std::pair<std::optional<double>, std::optional<double>> read_heat() override{
        const QJsonArray event = input("heat", "the temperatures are read");
        const auto value = [&](int i){ return event.at(i).isNull() ? std::optional<double>() : std::optional<double>(event.at(i).toDouble()); };
        return {value(2), value(3)};
    }
    bool screen_ok() override{ return m_screen_ok; }
    QString layout_state() override{ return m_layout; }
    bool layout_adapt(const QString& why) override{
        const QJsonArray event = input("layout_adapt", "the display is adapted: " + why);
        if (event.at(2).toString() != why){
            fail("the reason differs: the Python code said '" + event.at(2).toString() + "', the port: '" + why + "'");
        }
        m_layout = event.at(4).toString();
        m_screen_ok = event.at(5).toBool();
        return event.at(3).toBool();
    }
    void wait_unsupported() override{ out("wait_unsupported", "waiting for a screen that is supported"); }
    void layout_watch() override{
        const QJsonArray event = input("layout_watch", "a look at whether the layout changed");
        m_layout = event.at(2).toString();
        m_screen_ok = event.at(3).toBool();
    }
    void layout_verify(const cv::Mat& img) override{
        const int frame = index_of(img);
        const QJsonArray event = input("layout_verify", QString("a check of the layout on the picture %1").arg(frame));
        if (event.at(2).toInt() != frame){
            fail("the check of the layout differs: the Python code looked at " + describe(event) + ", the port at the picture " + QString::number(frame));
        }
        m_layout = event.at(3).toString();
        m_screen_ok = event.at(4).toBool();
    }
    QString power_state() override{ return input("power", "the power state of the phone is asked").at(2).toString(); }
    void key_wakeup() override{ out("wakeup", "the phone is woken"); }
    void unlock() override{ out("unlock", "the lock screen is taken away"); }
    cv::Mat unlock_game(const cv::Mat& img) override{
        const int frame = index_of(img);
        const QJsonArray event = input("unlock_game", QString("the game is woken (picture %1)").arg(frame));
        if (event.at(2).toInt() != frame){
            fail("the picture differs: the Python code woke " + describe(event) + ", the port the picture " + QString::number(frame));
        }
        return picture(event.at(3).toInt());
    }
    cv::Mat quick_screenshot_grab(const std::function<void()>& on_grab) override{
        const cv::Mat img = shot("quick");
        on_grab();
        return img;
    }
    bool quests_due(const cv::Mat& img) override{
        const int frame = index_of(img);
        const QJsonArray event = input("quests_due", QString("a look at whether the quests are due (picture %1)").arg(frame));
        if (event.at(2).toInt() != frame){
            fail("the look differs: the Python code looked at " + describe(event) + ", the port at the picture " + QString::number(frame));
        }
        return event.at(3).toBool();
    }
    QString claim_quests() override{ return answer("claim_quests", "the quests are claimed"); }
    QString rocket_battle() override{ return answer("rocket_battle", "the Team GO Rocket battle"); }
    double do_map(const cv::Mat& img) override{ return part("do_map", img); }
    double do_pokestop(const cv::Mat& img) override{ return part("do_pokestop", img); }
    double do_encounter(const cv::Mat& img) override{ return part("do_encounter", img); }
    void resume_catch_later(double seconds) override{
        const QJsonArray event = out("resume_catch_later", "catching is switched on again later");
        if (std::abs(event.at(2).toDouble() - seconds) > 1e-6){
            fail(QString("the time differs: the Python code did %1, the port: %2").arg(describe(event)).arg(seconds));
        }
    }

private:
    QString answer(const char* kind, const QString& doing){
        const QJsonArray event = input(kind, doing);
        if (event.at(3).isString()){
            throw std::runtime_error(event.at(3).toString().toStdString());
        }
        return event.at(2).toString();
    }
    double part(const char* kind, const cv::Mat& img){
        const int frame = index_of(img);
        const QJsonArray event = input(kind, QString("%1 on the picture %2").arg(kind).arg(frame));
        if (event.at(2).toInt() != frame){
            fail(QString("the picture differs: the Python code did %1, the port: %2 on the picture %3").arg(describe(event), kind).arg(frame));
        }
        return event.at(3).toDouble();
    }
};


//  What the code remembers, as the stories hold it.
QJsonValue point_json(const std::optional<Point>& p){
    return p.has_value() ? QJsonValue(QJsonArray{p->x, p->y}) : QJsonValue(QJsonValue::Null);
}
QJsonArray swipe_json(const Map::Swipe& s){
    return QJsonArray{s.x1, s.y1, s.x2, s.y2, s.ms};
}

QJsonObject state_json(Replay& host, const Map::State& map, const State& st){
    QJsonObject out;
    out.insert("away", QJsonObject{{"since", optional_num(st.away_since)}});
    out.insert("catch", map.catching);
    QJsonArray cooldown;
    for (const Map::Cool& c : map.cooldown){
        cooldown.append(QJsonArray{c.x, c.y, num(c.until)});
    }
    out.insert("cooldown", cooldown);
    out.insert("enc", QJsonObject{
        {"ball_set", map.enc.ball_set}, {"berry", map.enc.berry}, {"caught", map.enc.caught}, {"start", num(map.enc.start)},
        {"t_result", num(map.enc.t_result)}, {"t_tap", num(map.enc.t_tap)}, {"t_throw", num(map.enc.t_throw)}, {"throws", map.enc.throws},
    });
    out.insert("enc_xy", QJsonObject{{"xy", point_json(map.enc_xy)}});
    out.insert("handoff", QJsonObject{
        {"img", map.handoff.img.empty() ? QJsonValue(QJsonValue::Null) : QJsonValue(host.index_of(map.handoff.img))},
        {"t", num(map.handoff.t)},
    });
    out.insert("health", QJsonObject{{"ok", st.health.ok}, {"t", num(st.health.t)}});
    out.insert("heat", QJsonObject{
        {"phone", optional_num(st.heat.phone)}, {"pi", optional_num(st.heat.pi)}, {"since", optional_num(st.heat.since)}, {"t", num(st.heat.t)},
    });
    QJsonValue alt = QJsonValue(QJsonValue::Null);
    if (map.last_tap.alt.has_value()){
        QJsonArray list;
        for (const Point& p : *map.last_tap.alt){
            list.append(QJsonArray{p.x, p.y});
        }
        alt = list;
    }
    out.insert("last_tap", QJsonObject{
        {"alt", alt}, {"kind", map.last_tap.kind.has_value() ? QJsonValue(*map.last_tap.kind) : QJsonValue(QJsonValue::Null)},
        {"near", map.last_tap.near}, {"xy", point_json(map.last_tap.xy)},
    });
    out.insert("layout", host.m_layout);
    out.insert("near_state", QJsonObject{{"until", num(map.near_until)}});
    out.insert("perf", QJsonObject{{"shot", num(map.perf.shot)}, {"t_step", optional_num(map.perf.t_step)}, {"total", num(map.perf.total)}});
    const Map::Rotation& r = map.rotation;
    QJsonValue fired = QJsonValue(QJsonValue::Null);
    if (r.fired.has_value()){
        fired = QJsonObject{{"swipe", swipe_json(r.fired->swipe)}, {"t", num(r.fired->t)}};
    }
    out.insert("rotation", QJsonObject{
        {"armed", r.armed.has_value() ? QJsonValue(QJsonArray{swipe_json(*r.armed), 0}) : QJsonValue(QJsonValue::Null)},
        {"armed_at", num(r.armed_at)}, {"dir", r.dir}, {"fired", fired}, {"goal", num(r.goal)}, {"steps", r.steps}, {"turned", num(r.turned)},
    });
    out.insert("same_screen", QJsonObject{
        {"count", st.same_screen.count}, {"name", st.same_screen.name.has_value() ? QJsonValue(*st.same_screen.name) : QJsonValue(QJsonValue::Null)},
    });
    out.insert("screen_ok", host.m_screen_ok);
    return out;
}

std::optional<Point> point_of(const QJsonValue& v){
    if (!v.isArray()){
        return std::nullopt;
    }
    return Point{v.toArray().at(0).toInt(), v.toArray().at(1).toInt()};
}
Map::Swipe swipe_of(const QJsonArray& a){
    Map::Swipe s;
    s.x1 = a.at(0).toInt();
    s.y1 = a.at(1).toInt();
    s.x2 = a.at(2).toInt();
    s.y2 = a.at(3).toInt();
    s.ms = a.at(4).toInt();
    return s;
}

//  What a story (or a call of it) starts with (restore() and apply() of the generator): the things that the code remembers, with some of them
//  changed.  (The phone was looked at a moment ago, unless the story says otherwise.)
void apply_init(Replay& host, Map::State& map, State& st, const QJsonObject& init, bool first){
    QJsonObject all = init;
    if (first && !all.contains("health")){
        all.insert("health", QJsonObject{{"ok", true}, {"t", host.now()}});
    }
    for (auto it = all.begin(); it != all.end(); ++it){
        const QString key = it.key();
        const QJsonValue value = it.value();
        const QJsonObject o = value.toObject();
        if (key == "enc"){
            Map::Encounter& e = map.enc;
            e.start = o.value("start").toDouble(e.start);
            e.throws = o.value("throws").toInt(e.throws);
            e.berry = o.value("berry").toBool(e.berry);
            e.ball_set = o.value("ball_set").toBool(e.ball_set);
            e.caught = o.value("caught").toBool(e.caught);
            e.t_throw = o.value("t_throw").toDouble(e.t_throw);
            e.t_result = o.value("t_result").toDouble(e.t_result);
            e.t_tap = o.value("t_tap").toDouble(e.t_tap);
        }else if (key == "enc_xy"){
            map.enc_xy = point_of(o.value("xy"));
        }else if (key == "last_tap"){
            if (o.contains("kind")){
                map.last_tap.kind = o.value("kind").isString() ? std::optional<QString>(o.value("kind").toString()) : std::nullopt;
            }
            if (o.contains("xy")){
                map.last_tap.xy = point_of(o.value("xy"));
            }
            if (o.contains("alt")){
                if (o.value("alt").isArray()){
                    std::vector<Point> alt;
                    for (const QJsonValue& p : o.value("alt").toArray()){
                        alt.push_back(*point_of(p));
                    }
                    map.last_tap.alt = alt;
                }else{
                    map.last_tap.alt.reset();
                }
            }
            map.last_tap.near = o.value("near").toBool(map.last_tap.near);
        }else if (key == "near_state"){
            map.near_until = o.value("until").toDouble(map.near_until);
        }else if (key == "rotation"){
            Map::Rotation& r = map.rotation;
            r.steps = o.value("steps").toInt(r.steps);
            r.turned = o.value("turned").toDouble(r.turned);
            r.goal = o.value("goal").toDouble(r.goal);
            r.dir = o.value("dir").toInt(r.dir);
            if (o.contains("armed")){
                if (o.value("armed").isArray()){
                    r.armed = swipe_of(o.value("armed").toArray().at(0).toArray());
                }else{
                    r.armed.reset();
                }
            }
            r.armed_at = o.value("armed_at").toDouble(r.armed_at);
            if (o.contains("fired")){
                if (o.value("fired").isObject()){
                    Map::Fired f;
                    f.t = o.value("fired").toObject().value("t").toDouble();
                    f.swipe = swipe_of(o.value("fired").toObject().value("swipe").toArray());
                    r.fired = f;
                }else{
                    r.fired.reset();
                }
            }
        }else if (key == "away"){
            if (o.contains("since")){
                st.away_since = o.value("since").isNull() ? std::nullopt : std::optional<double>(o.value("since").toDouble());
            }
        }else if (key == "same_screen"){
            if (o.contains("name")){
                st.same_screen.name = o.value("name").isString() ? std::optional<QString>(o.value("name").toString()) : std::nullopt;
            }
            st.same_screen.count = o.value("count").toInt(st.same_screen.count);
        }else if (key == "health"){
            st.health.t = o.value("t").toDouble(st.health.t);
            st.health.ok = o.value("ok").toBool(st.health.ok);
        }else if (key == "heat"){
            st.heat.t = o.value("t").toDouble(st.heat.t);
            if (o.contains("since")){
                st.heat.since = o.value("since").isNull() ? std::nullopt : std::optional<double>(o.value("since").toDouble());
            }
            if (o.contains("phone")){
                st.heat.phone = o.value("phone").isNull() ? std::nullopt : std::optional<double>(o.value("phone").toDouble());
            }
            if (o.contains("pi")){
                st.heat.pi = o.value("pi").isNull() ? std::nullopt : std::optional<double>(o.value("pi").toDouble());
            }
        }else if (key == "perf"){
            map.perf.shot = o.value("shot").toDouble(map.perf.shot);
            map.perf.total = o.value("total").toDouble(map.perf.total);
            if (o.contains("t_step")){
                map.perf.t_step = o.value("t_step").toDouble();
            }
        }else if (key == "cooldown"){
            map.cooldown.clear();
            for (const QJsonValue& c : value.toArray()){
                const QJsonArray a = c.toArray();
                map.cooldown.push_back(Map::Cool{a.at(0).toInt(), a.at(1).toInt(), a.at(2).toDouble()});
            }
        }else if (key == "handoff"){
            const int img = o.value("img").isNull() ? -1 : o.value("img").toInt();
            map.handoff.img = img < 0 ? cv::Mat() : host.picture(img);
            map.handoff.t = o.value("t").toDouble();
        }else if (key == "catch"){
            map.catching = value.toBool();
        }else if (key == "layout"){
            host.m_layout = value.toString();
        }else if (key == "screen_ok"){
            host.m_screen_ok = value.toBool();
        }else{
            host.fail("the story starts with something that the check does not know: " + key);
        }
    }
}

//  One call of a story; returns what it returned, as the stories hold it.
QJsonValue run_call(Replay& host, Map::State& map, State& state, const QJsonObject& call){
    const QString fn = call.value("fn").toString();
    const auto picture = [&]{ return host.picture(call.value("img").toInt()); };
    if (fn == "step"){
        return num(step(host, map, state));
    }
    if (fn == "heat_wait"){
        return num(heat_wait(host, state));
    }
    if (fn == "leave_group_screen"){
        return leave_group_screen(host, picture());
    }
    if (fn == "is_rocket_text"){
        return is_rocket_text(host, picture());
    }
    if (fn == "storage_full"){
        return storage_full(host, picture());
    }
    if (fn == "pause_catching"){
        pause_catching(host, map);
        return QJsonValue(QJsonValue::Null);
    }
    if (fn == "resume_catching"){
        resume_catching(host, map);
        return QJsonValue(QJsonValue::Null);
    }
    host.fail("the story asks for the call " + fn + ", which the check does not know");
}

//  One story; returns an empty text when the port did the same, or what went another way.
QString play(const QJsonObject& test_case, double start, std::vector<Story::Scene>& cache){
    Replay host(test_case, start, cache);
    Map::State map;
    State state;
    try{
        apply_init(host, map, state, host.spec().value("init").toObject(), true);
        for (const QJsonValue& v : host.spec().value("calls").toArray()){
            const QJsonObject call = v.toObject();
            host.begin(call);
            apply_init(host, map, state, call.value("init").toObject(), false);
            QJsonValue result;
            QString what;
            bool threw = false;
            try{
                result = run_call(host, map, state, call);
            }catch (const Abort&){
                throw;
            }catch (const std::exception& e){
                threw = true;
                what = QString::fromUtf8(e.what());
            }
            if (threw){
                host.raised(what);
            }else{
                host.result(result);
            }
            host.state(state_json(host, map, state));
        }
        host.finish_story();
    }catch (const Abort&){
    }
    return host.failed ? host.message : QString();
}

}


int run_step_checks(const QString& golden, QStringList& report, bool stop_at_first){
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the stories of the step of the bot are not there: " + golden;
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
        report << "FAILED: the file of the step of the bot has no stories";
        return failed + 1;
    }
    report << QString("step of the bot: %1 stories played, %2 went another way").arg(cases.size()).arg(failed);
    return failed;
}


}
}
}
}
