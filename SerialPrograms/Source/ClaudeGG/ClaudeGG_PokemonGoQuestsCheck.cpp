/*  Claude GG Pokemon GO Quests Check (the quests of the GO Pass, played on the stories of the Python code)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The file of Mobile/tools/make_quests_golden.py holds little stories of what gamebot.py does with the quests: the check whether the quest button is gold,
 *  whether it is time to look at it, and the visit to the GO PASS (the tab, the pages, VIEW REWARDS, CLAIM ALL, a Pokémon that comes as a reward, the X
 *  that closes it).  The visits are played on a pretend phone that changes its screen with every touch (see Mobile/tools/make_quests_golden.py).  What the
 *  code was GIVEN: the screenshots, the lines of the text reader and what the screen classifier said.  What it DID: the taps, swipes, waits, log lines and
 *  pictures that are kept, and at the end of every call what it returned (or raised) and the time of its last look.  The first event that differs ends
 *  that story.
 *
 */

#include <cmath>
#include <stdexcept>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include "ClaudeGG_PokemonGoQuests.h"
#include "ClaudeGG_PokemonGoStory.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Quests{

namespace{

using Story::Abort;
using Story::describe;


class Replay : public Story::Host{
public:
    Replay(const QJsonObject& test_case, double start, std::vector<Story::Scene>& cache)
        : Story::Host(test_case, start, cache)
    {
    }

    //  ---- Loop::Host (the check for the map is the real one: the pictures decide; in a story with pictures of another size than the canvas the frames say)
    bool on_map(const cv::Mat& img) override{
        if (spec().value("fake_map").toBool()){
            return spec().value("frames").toArray().at(index_of(img)).toObject().value("is_map").toBool();
        }
        return Loop::map_visible(img);
    }

    //  ---- Flow::Host
    void swipe(int x1, int y1, int x2, int y2, int ms) override{
        const QString doing = QString("a swipe (%1, %2) to (%3, %4) in %5 ms").arg(x1).arg(y1).arg(x2).arg(y2).arg(ms);
        const QJsonArray event = out("swipe", doing);
        if (event.at(2).toInt() != x1 || event.at(3).toInt() != y1 || event.at(4).toInt() != x2 || event.at(5).toInt() != y2 || event.at(6).toInt() != ms){
            fail("the swipe differs: the Python code did " + describe(event) + ", the port: " + doing);
        }
    }
    std::pair<QString, double> screen_class(const cv::Mat&) override{
        const QJsonArray event = out("class", "the screen classifier");
        return {event.at(2).toString(), event.at(3).toDouble()};
    }
};


//  One call of a story; returns what it returned, as the stories hold it.
QJsonValue run_call(Replay& host, State& state, const QJsonObject& call){
    const QString fn = call.value("fn").toString();
    if (fn == "quest_gold"){
        return quest_gold(host.picture(call.value("img").toInt()));
    }
    if (fn == "quests_due"){
        return quests_due(host, state, host.picture(call.value("img").toInt()));
    }
    if (fn == "claim_quests"){
        return claim_quests(host, state);
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
            State state;
            if (has_state){
                state.t = call.value("st").toObject().value("t").toDouble();
            }
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
            host.state(QJsonObject{{"st", has_state ? QJsonValue(QJsonObject{{"t", state.t}}) : QJsonValue(QJsonValue::Null)}});
        }
        host.finish_story();
    }catch (const Abort&){
    }
    return host.failed ? host.message : QString();
}

}


int run_quests_checks(const QString& golden, QStringList& report, bool stop_at_first){
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the stories of the quests are not there: " + golden;
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
        report << "FAILED: the file of the quests has no stories";
        return failed + 1;
    }
    report << QString("quests: %1 stories played, %2 went another way").arg(cases.size()).arg(failed);
    return failed;
}


}
}
}
}
