/*  Claude GG Pokemon GO Gifts Check (the gifts of the friends, played on the stories of the Python code)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The file of Mobile/tools/make_gifts_golden.py holds little stories of what gamebot.py does with the gifts of the friends: the rows of the friend list
 *  with the pink bow and the grey arrow, the readers of the gift screens (the green pill button, ADD STICKER, the pink bow of the present, the strip that
 *  says FRIENDS), the memory of the day, a visit to one friend and the whole round.  Some of them are played on a pretend phone that changes its screen
 *  with every touch (see Mobile/tools/make_gifts_golden.py).  What the code was GIVEN: the screenshots, the lines and the strips of the text reader and
 *  the file of the memory of the day.  What it DID: the taps, presses, swipes and BACK, the waits, the log lines, the pictures that are kept, what it
 *  wrote to the file of the memory, and at the end of every call what it returned (or raised) and what it remembers.  The first event that differs
 *  ends that story.
 *
 */

#include <cmath>
#include <stdexcept>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include "ClaudeGG_PokemonGoGifts.h"
#include "ClaudeGG_PokemonGoStory.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Gifts{

namespace{

using Story::Abort;
using Story::describe;


class Replay : public Story::Host, public Gifts::Host{
public:
    Replay(const QJsonObject& test_case, double start, std::vector<Story::Scene>& cache)
        : Story::Host(test_case, start, cache)
    {
    }

    //  ---- Loop::Host (the check for the map is the real one: the pictures decide)
    bool on_map(const cv::Mat& img) override{ return Loop::map_visible(img); }

    //  ---- Flow::Host
    void swipe(int x1, int y1, int x2, int y2, int ms) override{
        const QString doing = QString("a swipe (%1, %2) to (%3, %4) in %5 ms").arg(x1).arg(y1).arg(x2).arg(y2).arg(ms);
        const QJsonArray event = out("swipe", doing);
        if (event.at(2).toInt() != x1 || event.at(3).toInt() != y1 || event.at(4).toInt() != x2 || event.at(5).toInt() != y2 || event.at(6).toInt() != ms){
            fail("the swipe differs: the Python code did " + describe(event) + ", the port: " + doing);
        }
    }

    //  ---- Gifts::Host
    void tap_press(int x, int y, int ms) override{
        const QString doing = QString("a touch at (%1, %2) for %3 ms").arg(x).arg(y).arg(ms);
        const QJsonArray event = out("press", doing);
        if (event.at(2).toInt() != x || event.at(3).toInt() != y || event.at(4).toInt() != ms){
            fail("the touch differs: the Python code did " + describe(event) + ", the port: " + doing);
        }
    }
    QString package() override{
        const QString package = m_spec.value("package").toString();
        return package.isEmpty() ? QString("com.nianticlabs.pokemongo") : package;
    }
    QString today() override{ return "2026-11-22"; }                //  (what the fake clock of the stories says of the day)
    std::optional<QByteArray> gift_state_read(const QString& file) override{
        const QString doing = "reading the file " + file;
        const QJsonArray event = input("gift_read", doing);
        if (event.at(2).toString() != file){
            fail("the file differs: the Python code read " + describe(event) + ", the port: " + file);
        }
        if (event.at(3).isNull()){
            return std::nullopt;
        }
        return event.at(3).toString().toUtf8();
    }
    void gift_state_write(const QString& file, const QByteArray& json) override{
        const QString doing = "writing the file " + file + ": " + QString::fromUtf8(json);
        const QJsonArray event = out("gift_write", doing);
        if (event.at(2).toString() != file){
            fail("the file differs: the Python code wrote " + describe(event) + ", the port: " + doing);
        }
        const QJsonValue got = QJsonDocument::fromJson(json).object();
        if (!Story::same(event.at(3), got)){
            fail("what was written differs: the Python code wrote " + describe(event.at(3)) + ", the port: " + describe(got));
        }
    }
};


//  ---- what the stories hold

Nav::Lines lines_of(const QJsonArray& list){
    Nav::Lines lines;
    for (const QJsonValue& v : list){
        const QJsonArray a = v.toArray();
        Nav::Line one;
        one.text = a.at(0).toString();
        one.x = a.at(1).toInt();
        one.y = a.at(2).toInt();
        for (const QJsonValue& w : a.at(3).toArray()){
            const QJsonArray word = w.toArray();
            one.words.push_back(Nav::Word{word.at(0).toString(), word.at(1).toInt(), word.at(2).toInt()});
        }
        lines.push_back(one);
    }
    return lines;
}

State state_of(const QJsonObject& o){
    State state;
    state.day = o.value("day").toString();
    for (const QJsonValue& v : o.value("sent").toArray()){
        state.sent << v.toString();
    }
    for (const QJsonValue& v : o.value("opened").toArray()){
        state.opened << v.toString();
    }
    state.open_blocked = o.value("open_blocked").toBool();
    state.send_blocked = o.value("send_blocked").toBool();
    return state;
}

QJsonValue button_json(const std::optional<Button>& b){
    if (!b.has_value()){
        return QJsonValue(QJsonValue::Null);
    }
    if (!b->area.has_value()){
        return QJsonArray{b->x, b->y};
    }
    return QJsonArray{b->x, b->y, *b->area};
}

//  One call of a story; returns what it returned, as the stories hold it.
QJsonValue run_call(Replay& host, State& state, const QJsonObject& call){
    const QString fn = call.value("fn").toString();
    const auto picture = [&]{ return host.picture(call.value("img").toInt()); };
    const auto lines = [&]{ return lines_of(call.value("lines").toArray()); };
    const QJsonValue null = QJsonValue(QJsonValue::Null);
    if (fn == "parse_friends"){
        QJsonArray out;
        cv::Mat img;
        if (call.contains("img")){
            img = picture();
        }
        for (const Friend& f : parse_friends(lines(), call.contains("img") ? &img : nullptr)){
            out.append(QJsonObject{{"name", f.name}, {"x", f.x}, {"y", f.y}, {"gift", f.gift}, {"arrow", f.arrow}});
        }
        return out;
    }
    if (fn == "sent_arrow"){
        return sent_arrow(picture(), call.value("y").toInt());
    }
    if (fn == "gift_icon"){
        return gift_icon(picture(), call.value("y0").toInt(), call.value("y1").toInt());
    }
    if (fn == "find_pill_button"){
        const cv::Mat img = picture();
        const std::optional<Start::Found> found = call.contains("y_min") ? Start::find_pill_button(img, call.value("y_min").toInt()) : Start::find_pill_button(img);
        if (!found.has_value()){
            return null;
        }
        return QJsonArray{found->x, found->y, found->area};
    }
    if (fn == "send_button"){
        return button_json(send_button(host, picture()));
    }
    if (fn == "has_sticker_button"){
        return has_sticker_button(host, picture());
    }
    if (fn == "is_gift_screen"){
        return is_gift_screen(picture());
    }
    if (fn == "is_friend_list"){
        return is_friend_list(host, picture());
    }
    if (fn == "any_text"){
        QStringList needles;
        for (const QJsonValue& v : call.value("needles").toArray()){
            needles << v.toString();
        }
        return any_text(lines(), needles);
    }
    if (fn == "load_gift_state"){
        return state_json(load_gift_state(host));
    }
    if (fn == "save_gift_state"){
        save_gift_state(host, state);
        return null;
    }
    if (fn == "back_to_list"){
        return back_to_list(host);
    }
    if (fn == "visit_friend"){
        const QJsonObject o = call.value("f").toObject();
        Friend f;
        f.name = o.value("name").toString();
        f.x = o.value("x").toInt();
        f.y = o.value("y").toInt();
        f.gift = o.value("gift").toBool();
        f.arrow = o.value("arrow").toBool();
        visit_friend(host, f, call.value("want_open").toBool(), call.value("want_send").toBool(), state);
        return null;
    }
    if (fn == "gifts_round"){
        gifts_round(host);
        return null;
    }
    host.fail("the story has a call that the check does not know: " + fn);
}

//  Plays one story; says what went another way (nothing: it did the same as the Python code).
QString play(const QJsonObject& test_case, double start, std::vector<Story::Scene>& cache){
    Replay host(test_case, start, cache);
    try{
        for (const QJsonValue& v : host.spec().value("calls").toArray()){
            const QJsonObject call = v.toObject();
            host.begin(call);
            const bool has_state = call.contains("st");
            State state = has_state ? state_of(call.value("st").toObject()) : State();
            QJsonValue result;
            QString what;
            bool threw = false;
            try{
                result = run_call(host, state, call);
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
            host.state(QJsonObject{{"st", has_state ? QJsonValue(state_json(state)) : QJsonValue(QJsonValue::Null)}});
        }
        host.finish_story();
    }catch (const Abort&){
    }
    return host.failed ? host.message : QString();
}

}


int run_gifts_checks(const QString& golden, QStringList& report, bool stop_at_first){
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the stories of the gifts are not there: " + golden;
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
        report << "FAILED: the file of the gifts has no stories";
        return failed + 1;
    }
    report << QString("gifts: %1 stories played, %2 went another way").arg(cases.size()).arg(failed);
    return failed;
}


}
}
}
}
