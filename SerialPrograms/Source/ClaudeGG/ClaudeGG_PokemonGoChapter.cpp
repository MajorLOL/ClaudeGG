/*  Claude GG Pokemon GO Chapter (one part of the bot on its own)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  See ClaudeGG_PokemonGoChapter.h.  What run_chapter() of the Python code does is followed line by line.
 *
 */

#include <algorithm>
#include <exception>
#include <opencv2/imgproc.hpp>
#include "ClaudeGG_PokemonGoChapter.h"
#include "ClaudeGG_PokemonGoFlow.h"
#include "ClaudeGG_PokemonGoRocketFight.h"
#include "ClaudeGG_PokemonGoThrow.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Chapter{

namespace{

//  (chapters.py: the ones that the C++ bot has.)
const std::vector<Info> CHAPTERS{
    {"screen",       "What the bot sees",                    "Any screen"},
    {"play",         "Normal play for 3 minutes",            "The map"},
    {"rocket",       "Rocket battle",                        "A grunt or leader talking, at the stop"},
    {"rocket_fight", "The Rocket fight on the screen",       "A Rocket fight that is going on"},
    {"catch",        "Catch this Pokémon",                   "An encounter"},
    {"throw",        "One throw",                            "An encounter"},
    {"bag",          "Clean up the bag",                     "The map"},
    {"quests",       "Claim GO Pass rewards",                "The map"},
    {"gifts",        "Gifts",                                "The map"},
};

//  '{x:.2f}' of Python.
QString two(double value){
    return QString::number(value, 'f', 2);
}

//  What the part says when it did not do what it is for: it has not been on the screen it needs, or something went wrong.
Result screen_chapter(Bot::PhoneBot& bot){
    const cv::Mat img = bot.screenshot();
    const std::pair<QString, double> seen = bot.screen_class(img);
    cv::Mat marked = img.clone();
    const std::vector<Models::Detection> found = seen.first == "mapScreen" ? bot.map_objects(img) : bot.encounter_objects(img);
    for (const Models::Detection& one : found){
        const QString label = QString::fromStdString(one.label);
        bot.log(QString("  %1 [%2] at (%3, %4) %5x%6").arg(label, two(one.score)).arg(one.cx).arg(one.cy).arg(one.w).arg(one.h));
        cv::rectangle(marked, cv::Point(one.cx - one.w / 2, one.cy - one.h / 2), cv::Point(one.cx + one.w / 2, one.cy + one.h / 2), cv::Scalar(0, 0, 255), 5);
        cv::putText(marked, (label + " " + two(one.score)).toStdString(), cv::Point(one.cx - one.w / 2, one.cy - one.h / 2 - 10),
                    cv::FONT_HERSHEY_SIMPLEX, 1.4, cv::Scalar(0, 0, 255), 3);
    }
    bot.save_picture("g_test.png", marked);
    Result result;
    result.ok = true;
    result.how = QString("screen %1 [%2], %3 things found (g_test.png)").arg(seen.first, two(seen.second)).arg(found.size());
    return result;
}

Result throw_chapter(Bot::PhoneBot& bot){
    Result result;
    const QString name = bot.screen_class(bot.quick_screenshot()).first;
    if (name != "encounterScreen" || !Throw::ball_ready(bot.screenshot())){
        result.how = "no ball ready on an encounter screen (" + name + ")";
        return result;
    }
    std::optional<bool> hit;
    const double released = bot.throw_ball(hit);
    result.ok = released != 0.0;
    result.how = QString("thrown - ") + (hit.has_value() ? (*hit ? "a clear hit" : "not a clear hit") : "where it came down was not seen") + " (see the lines above)";
    return result;
}

Result catch_chapter(Bot::PhoneBot& bot){
    Result result;
    const QString name = bot.screen_class(bot.screenshot()).first;
    if (name != "encounterScreen"){
        result.how = "no encounter on the screen (" + name + ")";
        return result;
    }
    const int steps = chapter_steps(bot, CATCH_SECONDS, true);
    result.ok = true;
    result.how = QString("%1 steps until the map").arg(steps);
    return result;
}

Result rocket_chapter(Bot::PhoneBot& bot){
    Result result;
    const QString res = bot.rocket_battle();
    if (res == "catch"){
        const int steps = chapter_steps(bot, CATCH_SECONDS, true);
        result.how = QString("fought, then %1 steps to catch the Shadow Pokémon").arg(steps);
    }else{
        result.how = res == "map" ? QString("back on the map") : QString("the battle did not go through (see the lines above)");
    }
    result.ok = res == "map" || res == "catch";
    return result;
}

}


const std::vector<Info>& available(){
    return CHAPTERS;
}

const Info* find(const QString& key){
    for (const Info& one : CHAPTERS){
        if (key == QLatin1String(one.key)){
            return &one;
        }
    }
    return nullptr;
}

QString keys(){
    QStringList list;
    for (const Info& one : CHAPTERS){
        list << QString::fromLatin1(one.key);
    }
    return list.join(", ");
}


int chapter_steps(Bot::PhoneBot& bot, double seconds, bool until_map){
    const double t_end = bot.wall() + seconds;
    int steps = 0;
    while (bot.wall() < t_end && !bot.stop()){
        if (until_map && steps > 0){
            if (bot.screen_class(bot.screenshot()).first == "mapScreen"){
                break;
            }
        }
        double wait = 0.0;
        try{
            bot.timers();
            wait = Step::step(bot, bot.map_state(), bot.step_state());
        }catch (const Flow::Interrupted&){
            throw;
        }catch (const std::exception& e){
            bot.log(QString("error: ") + QString::fromUtf8(e.what()));
            wait = 5;
        }
        steps++;
        bot.sleep(std::min(wait, std::max(0.0, t_end - bot.wall())));
    }
    return steps;
}


Result run(Bot::PhoneBot& bot, const QString& key){
    const Info* info = find(key);
    Result result;
    if (info == nullptr){
        bot.log(QString("TEST %1: no such test - there are: %2").arg(key, keys()));
        result.how = "no such test";
        return result;
    }
    bot.log(QString("TEST %1: started - %2 (start screen: %3)").arg(key, QString::fromUtf8(info->title), QString::fromUtf8(info->start)));
    //  (The display size that this part changed is put back when it ends, however it ends.)
    bool started = false;
    try{
        bot.layout_start();
        started = true;
        try{
            bot.save_picture("g_test_start.png", bot.screenshot());
        }catch (const Flow::Interrupted&){
            throw;
        }catch (const std::exception& e){
            bot.log(QString("TEST %1: no screenshot (%2)").arg(key, QString::fromUtf8(e.what())));
        }
        if (key == "screen"){
            result = screen_chapter(bot);
        }else if (key == "play"){
            bot.map_state().gift_last = bot.wall();         //  (the gifts have a test of their own: not the first minute of this one)
            const int steps = chapter_steps(bot, PLAY_SECONDS, false);
            result.ok = true;
            result.how = QString("%1 steps in %2 minutes").arg(steps).arg((int)(PLAY_SECONDS / 60));
        }else if (key == "throw"){
            result = throw_chapter(bot);
        }else if (key == "catch"){
            result = catch_chapter(bot);
        }else if (key == "rocket"){
            result = rocket_chapter(bot);
        }else if (key == "rocket_fight"){
            const int seconds = RocketFight::rocket_fight(bot);
            result.ok = true;
            result.how = QString("the fight took %1 s").arg(seconds);
        }else if (key == "bag"){
            const int gone = bot.clean_bag();
            result.ok = true;
            result.how = QString("%1 kinds of items discarded").arg(gone);
        }else if (key == "quests"){
            const QString res = bot.claim_quests();
            result.ok = res != "failed";
            result.how = res;
        }else if (key == "gifts"){
            bot.gifts_round();
            result.ok = true;
            result.how = "round over (see the gift lines above)";
        }
    }catch (const Flow::Interrupted&){
        result.ok = false;
        result.how = "stopped";
    }catch (const std::exception& e){
        bot.log(QString("TEST %1: error %2").arg(key, QString::fromUtf8(e.what())));
        result.ok = false;
        result.how = QString("error ") + QString::fromUtf8(e.what());
    }
    if (started){
        try{
            bot.save_picture("g_test_end.png", bot.screenshot());
        }catch (const std::exception&){
        }
    }
    try{
        bot.layout_end();
    }catch (const std::exception&){
    }
    bot.log(QString("TEST %1: %2 - %3").arg(key, result.ok ? "done" : "failed", result.how));
    return result;
}


}
}
}
}
