/*  Claude GG Pokemon GO Catch Check (the catch screen around the throw, played on the stories of the Python code)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The file of Mobile/tools/make_catch_golden.py holds little stories of do_encounter, wait_for_result, fast_catch_leave, tap_button, pick_berry
 *  and the rest of what gamebot.py does at the catch screen, played on a pretend phone with a pretend clock (see ClaudeGG_PokemonGoStory.h):
 *  for every call the events in the order in which they happened.  What the code was GIVEN: the screenshots, the answers of the screen
 *  classifier, of the detector of buttons and of the text readers, the table of the tesseract program, what the throws and the steps did and
 *  took.  What it DID: the taps and BACK, the waits, the log lines, the pictures that are kept, and at the end of every call what it returned
 *  (or raised) and what it remembers.  The first event that differs ends that story.
 *
 */

#include <cmath>
#include <stdexcept>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include "ClaudeGG_PokemonGoCatch.h"
#include "ClaudeGG_PokemonGoStory.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Catch{

namespace{

using Story::Abort;
using Story::describe;
using Story::mean_of;
using Story::num;
using Story::optional_num;
using Story::same;


class Replay : public Story::Host, public Catch::Host{
public:
    Replay(const QJsonObject& test_case, double start, std::vector<Story::Scene>& cache)
        : Story::Host(test_case, start, cache)
    {
        m_ball = m_spec.value("ball").isString() ? m_spec.value("ball").toString() : QString("poke");
        if (m_spec.contains("berries")){
            for (const QJsonValue& v : m_spec.value("berries").toArray()){
                m_berries << v.toString();
            }
        }else{
            m_berries << "pinap" << "razz" << "nanab";
        }
    }

    //  ---- Loop::Host (the check for the map is the real one: the pictures decide)
    bool on_map(const cv::Mat& img) override{ return Loop::map_visible(img); }

    //  ---- Catch::Host
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
    double throw_ball(std::optional<bool>& hit) override{
        const QJsonArray event = input("throw", "a ball is thrown");
        if (event.at(3).isBool()){
            hit = event.at(3).toBool();
        }else{
            hit = std::nullopt;
        }
        return m_t - event.at(4).toDouble();
    }
    QString ball() override{ return m_ball; }
    QStringList berry_order() override{ return m_berries; }
    std::optional<QString> tray_table(const cv::Mat& gray) override{
        const QJsonArray event = out("tesseract", QString("the berry tray is given to the tesseract program (%1 x %2)").arg(gray.cols).arg(gray.rows));
        if (event.at(2).isNull()){
            return std::nullopt;                                //  the program is not there
        }
        if (event.at(2).toInt() != gray.rows || event.at(3).toInt() != gray.cols){
            fail(QString("the berry tray differs: the Python code gave the program %1, the port: %2 x %3").arg(describe(event)).arg(gray.cols).arg(gray.rows));
        }
        if (std::abs(event.at(4).toDouble() - mean_of(gray)) > Story::MEAN_TOLERANCE){
            fail(QString("the berry tray differs: its mean is %1 and the Python code gave the program one of %2 (%3)")
                .arg(mean_of(gray), 0, 'f', 2).arg(event.at(4).toDouble(), 0, 'f', 2).arg(describe(event)));
        }
        return event.at(5).toString();
    }
    double step() override{
        const QJsonArray event = input("step", "a step of the bot");
        if (event.at(4).isString()){
            throw std::runtime_error(event.at(4).toString().toStdString());
        }
        return event.at(3).toDouble();
    }

private:
    QString m_ball;
    QStringList m_berries;
};


//  What the code remembers, as the stories hold it.
QJsonValue point_json(const std::optional<Point>& p){
    return p.has_value() ? QJsonValue(QJsonArray{p->x, p->y}) : QJsonValue(QJsonValue::Null);
}

QJsonObject state_json(Replay& host, const State& st){
    QJsonObject out;
    out.insert("enc", QJsonObject{
        {"ball_set", st.enc.ball_set}, {"berry", st.enc.berry}, {"caught", st.enc.caught}, {"start", num(st.enc.start)},
        {"t_result", num(st.enc.t_result)}, {"t_tap", num(st.enc.t_tap)}, {"t_throw", num(st.enc.t_throw)}, {"throws", st.enc.throws},
    });
    out.insert("enc_xy", QJsonObject{{"xy", point_json(st.enc_xy)}});
    out.insert("fast_pending", QJsonObject{
        {"looks", st.fast_pending.looks}, {"t", num(st.fast_pending.t)}, {"t_back", num(st.fast_pending.t_back)},
        {"t_throw", num(st.fast_pending.t_throw)}, {"xy", point_json(st.fast_pending.xy)},
    });
    out.insert("fast_state", QJsonObject{{"fails", st.fast_fails}, {"off_until", num(st.fast_off_until)}});
    out.insert("handoff", QJsonObject{
        {"img", st.handoff.img.empty() ? QJsonValue(QJsonValue::Null) : QJsonValue(host.index_of(st.handoff.img))},
        {"t", num(st.handoff.t)},
    });
    out.insert("storage_state", QJsonObject{{"full", st.storage_full}});
    out.insert("throw_info", QJsonObject{{"hit", st.throw_hit.has_value() ? QJsonValue(*st.throw_hit) : QJsonValue(QJsonValue::Null)}});
    return out;
}

//  What a story (or a call of it) starts with (restore() of the generator): the things that the code remembers, with some of them changed.
void apply_init(Replay& host, State& st, const QJsonObject& init){
    for (auto it = init.begin(); it != init.end(); ++it){
        const QString key = it.key();
        const QJsonObject o = it.value().toObject();
        if (key == "enc"){
            for (auto f = o.begin(); f != o.end(); ++f){
                const QString name = f.key();
                if (name == "throws"){ st.enc.throws = f.value().toInt(); }
                else if (name == "caught"){ st.enc.caught = f.value().toBool(); }
                else if (name == "berry"){ st.enc.berry = f.value().toBool(); }
                else if (name == "ball_set"){ st.enc.ball_set = f.value().toBool(); }
                else if (name == "start"){ st.enc.start = f.value().toDouble(); }
                else if (name == "t_throw"){ st.enc.t_throw = f.value().toDouble(); }
                else if (name == "t_result"){ st.enc.t_result = f.value().toDouble(); }
                else if (name == "t_tap"){ st.enc.t_tap = f.value().toDouble(); }
                else{ host.fail("the story starts with an unknown part of enc: " + name); }
            }
        }else if (key == "enc_xy"){
            const QJsonArray xy = o.value("xy").toArray();
            st.enc_xy = xy.size() == 2 ? std::optional<Point>(Point{xy.at(0).toInt(), xy.at(1).toInt()}) : std::nullopt;
        }else if (key == "throw_info"){
            st.throw_hit = o.value("hit").isBool() ? std::optional<bool>(o.value("hit").toBool()) : std::nullopt;
        }else if (key == "fast_pending"){
            for (auto f = o.begin(); f != o.end(); ++f){
                const QString name = f.key();
                if (name == "xy"){
                    const QJsonArray xy = f.value().toArray();
                    st.fast_pending.xy = xy.size() == 2 ? std::optional<Point>(Point{xy.at(0).toInt(), xy.at(1).toInt()}) : std::nullopt;
                }
                else if (name == "t"){ st.fast_pending.t = f.value().toDouble(); }
                else if (name == "t_throw"){ st.fast_pending.t_throw = f.value().toDouble(); }
                else if (name == "t_back"){ st.fast_pending.t_back = f.value().toDouble(); }
                else if (name == "looks"){ st.fast_pending.looks = f.value().toInt(); }
                else{ host.fail("the story starts with an unknown part of fast_pending: " + name); }
            }
        }else if (key == "fast_state"){
            st.fast_fails = o.value("fails").toInt(st.fast_fails);
            st.fast_off_until = o.value("off_until").toDouble(st.fast_off_until);
        }else if (key == "storage_state"){
            st.storage_full = o.value("full").toBool(st.storage_full);
        }else{
            host.fail("the story starts with something that the check does not know: " + key);
        }
    }
}

//  One call of a story; returns what it returned, as the stories hold it.
QJsonValue run_call(Replay& host, State& state, const QJsonObject& call){
    const QString fn = call.value("fn").toString();
    const auto picture = [&]{ return host.picture(call.value("img").toInt()); };
    if (fn == "do_encounter"){
        return num(do_encounter(host, state, picture()));
    }
    if (fn == "wait_for_result"){
        return wait_for_result(host, state, host.now() - call.value("ago").toDouble());
    }
    if (fn == "fast_catch_leave"){
        return optional_num(fast_catch_leave(host, state, host.now() - call.value("ago").toDouble()));
    }
    if (fn == "catch_result_button"){
        const std::optional<Point> btn = catch_result_button(host, state, picture());
        return point_json(btn);
    }
    if (fn == "tap_catch_result"){
        const QJsonArray btn = call.value("btn").toArray();
        tap_catch_result(host, state, Point{btn.at(0).toInt(), btn.at(1).toInt()}, call.value("how").toString());
        return QJsonValue(QJsonValue::Null);
    }
    if (fn == "tap_button"){
        return tap_button(host, picture(), call.value("only_passenger").toBool(false));
    }
    if (fn == "pick_berry"){
        const std::optional<std::pair<QString, Point>> choice = pick_berry(host, picture());
        if (!choice.has_value()){
            return QJsonValue(QJsonValue::Null);
        }
        return QJsonArray{choice->first, QJsonArray{choice->second.x, choice->second.y}};
    }
    if (fn == "tray_labels"){
        Cells cells = tray_labels(host, picture());
        std::sort(cells.begin(), cells.end(), [](const auto& a, const auto& b){
            return a.first != b.first ? a.first < b.first : a.second < b.second;
        });
        QJsonArray rows;
        for (const auto& cell : cells){
            rows.append(QJsonArray{cell.first.first, cell.first.second, cell.second});
        }
        return rows;
    }
    if (fn == "finish_catch"){
        finish_catch(host, call.value("beat").toBool(false));
        return QJsonValue(QJsonValue::Null);
    }
    if (fn == "mark_caught"){
        mark_caught(host, state);
        return QJsonValue(QJsonValue::Null);
    }
    host.fail("the story asks for the call " + fn + ", which the check does not know");
}

//  One story; returns an empty text when the port did the same, or what went another way.
QString play(const QJsonObject& test_case, double start, std::vector<Story::Scene>& cache){
    Replay host(test_case, start, cache);
    State state;
    try{
        apply_init(host, state, host.spec().value("init").toObject());
        for (const QJsonValue& v : host.spec().value("calls").toArray()){
            const QJsonObject call = v.toObject();
            host.begin(call);
            apply_init(host, state, call.value("init").toObject());
            QJsonValue result;
            QString what;
            bool threw = false;
            try{
                result = run_call(host, state, call);
            }catch (const std::exception& e){
                threw = true;
                what = QString::fromUtf8(e.what());
            }
            if (threw){
                host.raised(what);
            }else{
                host.result(result);
            }
            host.state(state_json(host, state));
        }
        host.finish_story();
    }catch (const Abort&){
    }
    return host.failed ? host.message : QString();
}

}


int run_catch_checks(const QString& golden, QStringList& report, bool stop_at_first){
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the stories of the catch screen are not there: " + golden;
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
        report << "FAILED: the file of the catch screen has no stories";
        return failed + 1;
    }
    report << QString("catch screen: %1 stories played, %2 went another way").arg(cases.size()).arg(failed);
    return failed;
}


}
}
}
}
