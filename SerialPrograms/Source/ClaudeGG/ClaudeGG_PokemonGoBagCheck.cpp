/*  Claude GG Pokemon GO Bag Check (the item bag, played on the stories of the Python code)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The file of Mobile/tools/make_bag_golden.py holds little stories of what gamebot.py does with the item bag: the names and the rules of what the bag
 *  keeps, the rows of a page of the bag, the question 'Discard <item>?', the ways of looking at a page, the way to the bag and back, the clean-up of a
 *  full bag, the red FULL marks of the main menu and closing the game when everything is full.  Some of them are played on a pretend phone that changes
 *  its screen with every touch (see Mobile/tools/make_bag_golden.py).  What the code was GIVEN: the screenshots, the text reader's lines and the number
 *  in the box of the question, the answers of adb.  What it DID: the taps, swipes and BACK, the waits, the log lines, the pictures that are kept, the
 *  daily run being told that it is over, and at the end of every call what it returned (or raised) and what it remembers.  The first event that
 *  differs ends that story.
 *
 */

#include <cmath>
#include <stdexcept>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include "ClaudeGG_PokemonGoBag.h"
#include "ClaudeGG_PokemonGoStory.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Bag{

namespace{

using Story::Abort;
using Story::describe;


class Replay : public Story::Host, public Bag::Host{
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

    //  The strip with the number of the question: the story also says how many lines the code was told to read.
    QString ocr_line(const cv::Mat& img, int lines) override{
        const QJsonArray next = peek("a reading of a strip of text");
        if (next.at(0).toString() == "ocr_text" && next.size() > 6 && next.at(6).toInt() != lines){
            fail(QString("the reading differs: the Python code read %1 lines, the port %2: %3").arg(next.at(6).toInt()).arg(lines).arg(describe(next)));
        }
        return Story::Host::ocr_line(img, lines);
    }

    //  ---- Bag::Host
    void swipes(const std::vector<Loop::Stroke>& strokes) override{
        const QString doing = QString("%1 touches in one command").arg(strokes.size());
        const QJsonArray event = out("swipes", doing);
        const QJsonArray was = event.at(2).toArray();
        bool differs = (size_t)was.size() != strokes.size();
        for (size_t i = 0; !differs && i < strokes.size(); i++){
            const QJsonArray s = was.at((qsizetype)i).toArray();
            differs = s.at(0).toInt() != strokes[i].x1 || s.at(1).toInt() != strokes[i].y1 || s.at(2).toInt() != strokes[i].x2
                || s.at(3).toInt() != strokes[i].y2 || s.at(4).toInt() != strokes[i].ms;
        }
        if (differs){
            QString mine;
            for (const Loop::Stroke& s : strokes){
                mine += QString("[%1,%2,%3,%4,%5]").arg(s.x1).arg(s.y1).arg(s.x2).arg(s.y2).arg(s.ms);
            }
            fail("the touches differ: the Python code did " + describe(event) + ", the port: " + doing + " " + mine);
        }
    }
    QString adb(const QStringList& args) override{
        const QString doing = "the adb command " + args.join(' ');
        const QJsonArray event = input("adb", doing);
        QStringList was;
        for (const QJsonValue& v : event.at(2).toArray()){
            was << v.toString();
        }
        if (was != args){
            fail("the adb command differs: the Python code did " + describe(event) + ", the port: " + doing);
        }
        if (event.at(4).isString()){
            throw std::runtime_error(event.at(4).toString().toStdString());
        }
        return event.at(3).toString();
    }
    QString package() override{ return "com.nianticlabs.pokemongo"; }
    QJsonValue bag_keep_saved() override{
        const QJsonValue v = m_settings.value("bag_keep");
        return v.isUndefined() ? QJsonValue(QJsonValue::Null) : v;
    }
    void run_done() override{
        const QJsonArray event = out("run_state", "the daily run is told that it is over");
        if (event.at(2).toString() != "done" || !event.at(3).toBool()){
            fail("the daily run was told something else: the Python code did " + describe(event));
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
QJsonArray lines_json(const Nav::Lines& lines){
    QJsonArray out;
    for (const Nav::Line& line : lines){
        QJsonArray words;
        for (const Nav::Word& w : line.words){
            words.append(QJsonArray{w.text, w.x, w.y});
        }
        out.append(QJsonArray{line.text, line.x, line.y, words});
    }
    return out;
}
QJsonValue optional_int(const std::optional<int>& x){
    return x.has_value() ? QJsonValue(*x) : QJsonValue(QJsonValue::Null);
}
QJsonValue spot_json(const Spot& s){
    return QJsonArray{s.first, s.second};
}
QJsonArray rules_json(const std::vector<std::pair<QString, int>>& rules){
    QJsonArray out;
    for (const std::pair<QString, int>& r : rules){
        out.append(QJsonArray{r.first, r.second});
    }
    return out;
}
QJsonValue dialog_json(const std::optional<Dialog>& d){
    if (!d.has_value()){
        return QJsonValue(QJsonValue::Null);
    }
    QJsonValue n = QJsonValue(QJsonValue::Null);
    if (d->n.has_value()){
        n = QJsonValue((double)*d->n);
    }
    return QJsonArray{d->title, n, spot_json(d->yes), spot_json(d->no), d->number_y};
}

//  The plan that a call gives (nothing: the one that the person set).
std::vector<Rule> plan_of(Replay& host, const QJsonObject& call){
    if (call.value("plan").isNull() || call.value("plan").isUndefined()){
        return plan(host);
    }
    std::vector<Rule> out;
    for (const QJsonValue& v : call.value("plan").toArray()){
        const QJsonArray a = v.toArray();
        out.push_back(Rule{a.at(0).toString(), a.at(1).isNull() ? std::nullopt : std::optional<int>(a.at(1).toInt())});
    }
    return out;
}

//  What the code remembers.
QJsonObject state_json(const Map::State& map, const State& state){
    return QJsonObject{{"bag_full", map.bag_is_full}, {"ocr_variant", state.ocr_variant}, {"spin", map.spin}, {"storage_full", map.storage_full}};
}
void apply(Map::State& map, State& state, const QJsonObject& init, Replay& host){
    for (auto it = init.begin(); it != init.end(); ++it){
        const QString key = it.key();
        if (key == "ocr_variant"){
            state.ocr_variant = it.value().toInt();
        }else if (key == "storage_full"){
            map.storage_full = it.value().toBool();
        }else if (key == "bag_full"){
            map.bag_is_full = it.value().toBool();
        }else if (key == "spin"){
            map.spin = it.value().toBool();
        }else{
            host.fail("the story starts with something that the check does not know: " + key);
        }
    }
}

//  One call of a story; returns what it returned, as the stories hold it.
QJsonValue run_call(Replay& host, Map::State& map, State& state, const QJsonObject& call){
    const QString fn = call.value("fn").toString();
    const auto picture = [&]{ return host.picture(call.value("img").toInt()); };
    const auto lines = [&]{ return lines_of(call.value("lines").toArray()); };
    const QJsonValue null = QJsonValue(QJsonValue::Null);
    if (fn == "plain_name"){
        return plain_name(call.value("text").toString());
    }
    if (fn == "rules"){
        return rules_json(rules(call.value("saved")));
    }
    if (fn == "bag_plan"){
        QJsonArray out;
        for (const Rule& r : plan(host)){
            out.append(QJsonArray{r.name, optional_int(r.keep)});
        }
        return out;
    }
    if (fn == "bag_keep"){
        return optional_int(keep_for(call.value("name").toString(), plan_of(host, call)));
    }
    if (fn == "bag_rows"){
        QJsonArray out;
        for (const Row& r : rows(lines(), call.value("h").toInt(), plan_of(host, call))){
            out.append(QJsonArray{r.name, r.keep, r.x, r.y, optional_int(r.count)});
        }
        return out;
    }
    if (fn == "bag_like"){
        return bag_like(lines());
    }
    if (fn == "incense_tile"){
        const std::optional<Spot> tile = incense_tile(lines());
        return tile.has_value() ? spot_json(*tile) : null;
    }
    if (fn == "canvas"){
        const std::pair<int, int> at = canvas(picture(), call.value("x").toDouble(), call.value("y").toDouble());
        return QJsonArray{at.first, at.second};
    }
    if (fn == "discard_dialog"){
        return dialog_json(discard_dialog(host, picture()));
    }
    if (fn == "set_discard_number"){
        const std::pair<cv::Mat, std::optional<Dialog>> got = call.contains("tries")
            ? set_discard_number(host, call.value("target").toInt(), call.value("tries").toInt())
            : set_discard_number(host, call.value("target").toInt());
        return QJsonObject{{"d", dialog_json(got.second)}, {"img", host.index_of(got.first)}};
    }
    if (fn == "bag_ocr"){
        return lines_json(call.contains("y0") ? bag_ocr(host, state, picture(), call.value("y0").toInt()) : bag_ocr(host, state, picture()));
    }
    if (fn == "open_bag"){
        const std::optional<std::pair<cv::Mat, Nav::Lines>> got = open_bag(host);
        if (!got.has_value()){
            return null;
        }
        return QJsonObject{{"img", host.index_of(got->first)}, {"lines", lines_json(got->second)}};
    }
    if (fn == "bag_to_map"){
        bag_to_map(host);
        return null;
    }
    if (fn == "clean_bag"){
        return clean_bag(host, state);
    }
    if (fn == "check_menu_full"){
        check_menu_full(host, map);
        return null;
    }
    if (fn == "close_game_completely"){
        close_game_completely(host);
        return null;
    }
    if (fn == "check_all_full"){
        check_all_full(host, map);
        return null;
    }
    if (fn == "leave_question"){
        leave_question(host, call.value("kind").toString(), lines());
        return null;
    }
    if (fn == "cancel_exit"){
        cancel_exit(host, lines());
        return null;
    }
    if (fn == "cancel_discard"){
        cancel_discard(host, lines());
        return null;
    }
    host.fail("the story asks for the call " + fn + ", which the check does not know");
}

//  One story; returns an empty text when the port did the same, or what went another way.
QString play(const QJsonObject& test_case, double start, std::vector<Story::Scene>& cache){
    Replay host(test_case, start, cache);
    Map::State map;
    State state;
    try{
        apply(map, state, host.spec().value("init").toObject(), host);
        for (const QJsonValue& v : host.spec().value("calls").toArray()){
            const QJsonObject call = v.toObject();
            host.begin(call);
            apply(map, state, call.value("init").toObject(), host);
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
            host.state(state_json(map, state));
        }
        host.finish_story();
    }catch (const Abort&){
    }
    return host.failed ? host.message : QString();
}

}


int run_bag_checks(const QString& golden, QStringList& report, bool stop_at_first){
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the stories of the item bag are not there: " + golden;
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
        report << "FAILED: the file of the item bag has no stories";
        return failed + 1;
    }
    report << QString("item bag: %1 stories played, %2 went another way").arg(cases.size()).arg(failed);
    return failed;
}


}
}
}
}
