/*  Claude GG Pokemon GO Rocket Check (the way through a fight of Team GO Rocket, played on the stories of the Python code)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The file of Mobile/tools/make_rocket_golden.py holds little stories of what gamebot.py does between the first speech bubble of Team GO Rocket and the map
 *  (or the Shadow Pokémon to catch): the speech bubbles, BATTLE, the radar question, the party and its empty slots, the list of Pokémon, the summary.  They are
 *  played on a pretend phone that changes its screen with every touch (see Mobile/tools/make_rocket_golden.py).  What the code was GIVEN: the screenshots,
 *  the lines of the text reader, what the screen classifier and the fight reader said, and (in some stories) whether the person stopped the bot.  What it DID:
 *  the taps, waits, log lines and pictures that are kept, that the fight was played (the fight itself is a story of its own), and at the end of every call
 *  what it returned.  The first event that differs ends that story.
 *
 */

#include <cmath>
#include <stdexcept>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include "ClaudeGG_PokemonGoRocket.h"
#include "ClaudeGG_PokemonGoStory.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Rocket{

namespace{

using Story::Abort;
using Story::describe;


class Replay : public Story::Host, public Rocket::Host{
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
    //  The person who stops the bot: asked only in a story that has such a person.
    bool stop() override{
        if (!spec().contains("stop_at")){
            return false;
        }
        const QJsonArray event = out("stop", "the question whether the person stopped the bot");
        return event.at(2).toBool();
    }

    //  ---- Flow::Host
    std::pair<QString, double> screen_class(const cv::Mat&) override{
        const QJsonArray event = out("class", "the screen classifier");
        return {event.at(2).toString(), event.at(3).toDouble()};
    }

    //  ---- Rocket::Host
    QString screen_state(const cv::Mat& small) override{
        const QJsonArray event = out("fight_state", "the fight reader");
        if (event.at(3).toInt() != small.rows || event.at(4).toInt() != small.cols){
            fail(QString("the small picture of the fight reader differs: the Python code gave one of %1 x %2 (rows x columns), the port: %3 x %4")
                .arg(event.at(3).toInt()).arg(event.at(4).toInt()).arg(small.rows).arg(small.cols));
        }
        if (std::abs(event.at(5).toDouble() - Story::mean_of(small)) > Story::MEAN_TOLERANCE){
            fail(QString("the small picture of the fight reader differs: its mean is %1 and the Python code gave one of %2")
                .arg(Story::mean_of(small), 0, 'f', 2).arg(event.at(5).toDouble(), 0, 'f', 2));
        }
        return event.at(2).toString();
    }
    void rocket_fight() override{
        out("fight", "the fight is played");
    }
};


//  One call of a story; returns what it returned, as the stories hold it.
QJsonValue run_call(Replay& host, const QJsonObject& call){
    const QString fn = call.value("fn").toString();
    if (fn == "rocket_battle"){
        return rocket_battle(host);
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
            QJsonValue result;
            QString what;
            bool threw = false;
            try{
                result = run_call(host, call);
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
        }
        host.finish_story();
    }catch (const Abort&){
    }
    return host.failed ? host.message : QString();
}

}


int run_rocket_checks(const QString& golden, QStringList& report, bool stop_at_first){
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the stories of Team GO Rocket are not there: " + golden;
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
        report << "FAILED: the file of Team GO Rocket has no stories";
        return failed + 1;
    }
    report << QString("rocket: %1 stories played, %2 went another way").arg(cases.size()).arg(failed);
    return failed;
}


}
}
}
}
