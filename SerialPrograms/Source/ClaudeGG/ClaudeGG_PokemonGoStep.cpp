/*  Claude GG Pokemon GO Step (one step of the Pokémon GO bot: which screen is it, what is done with it)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <cstdio>
#include <stdexcept>
#include "ClaudeGG_PokemonGoStart.h"
#include "ClaudeGG_PokemonGoThrow.h"
#include "ClaudeGG_PokemonGoStep.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Step{

namespace{

//  f"{x:.0f}" of Python.
QString whole(double x){
    char buffer[512];
    std::snprintf(buffer, sizeof(buffer), "%.0f", x);
    return QString::fromLatin1(buffer);
}

bool is_menu_like(const QString& name){
    return name == "menusScreen" || name == "rewardScreen" || name == "onbekend";
}

bool is_home(const QString& name){
    return name == "mapScreen" || name == "encounterScreen" || name == "pokestopScreen";
}

}


double heat_wait(Host& host, State& state){
    Heat& heat = state.heat;
    if (!host.setting("heat_pause", true)){
        heat.since.reset();
        return 0;
    }
    const double now = host.wall();
    if (now - heat.t < (heat.since.has_value() ? HEAT_PAUSED_EVERY : HEAT_EVERY)){
        return heat.since.has_value() ? HEAT_PAUSED_EVERY : 0;
    }
    heat.t = now;
    const std::pair<std::optional<double>, std::optional<double>> read = host.read_heat();
    heat.phone = read.first;
    heat.pi = read.second;
    const std::optional<double>& phone = heat.phone;
    const std::optional<double>& pi = heat.pi;
    if (!heat.since.has_value()){
        QStringList hot;
        if (phone.has_value() && *phone >= HEAT_PHONE){
            hot << QString("the phone's battery is %1 °C").arg(whole(*phone));
        }
        if (pi.has_value() && *pi >= HEAT_PI){
            hot << QString("the Pi is %1 °C").arg(whole(*pi));
        }
        if (!hot.isEmpty()){
            heat.since = now;
            host.log(QString("heat: %1 - pausing until it is below %2 / %3 °C").arg(hot.join(" and "), whole(HEAT_PHONE_OK), whole(HEAT_PI_OK)));
            return HEAT_PAUSED_EVERY;
        }
        return 0;
    }
    const bool cool = (!phone.has_value() || *phone <= HEAT_PHONE_OK) && (!pi.has_value() || *pi <= HEAT_PI_OK);
    if (cool || now - *heat.since > HEAT_MAX_PAUSE){
        QString text = QString("heat: going on after %1 min").arg(whole((now - *heat.since) / 60));
        if (!cool){
            text += " (the longest pause is over, although it is still warm)";
        }
        if (phone.has_value()){
            text += QString(" - phone %1 °C").arg(whole(*phone));
        }
        if (pi.has_value()){
            text += QString(", Pi %1 °C").arg(whole(*pi));
        }
        host.log(text);
        heat.since.reset();
        return 0;
    }
    return HEAT_PAUSED_EVERY;
}


bool leave_group_screen(Host& host, const cv::Mat& img){
    const Nav::Lines lines = host.ocr_lines(img, 150, 2150);
    QStringList parts;
    for (const Nav::Line& line : lines){
        parts << line.text;
    }
    const QString text = parts.join(" ");
    const bool question = text.contains("GROUP WITH OTHER TRAINERS") || (text.contains("ARE YOU SURE") && text.contains("GROUP"));
    const bool screen = text.contains("FIND ME A GROUP") || text.contains("WEEKLY CHALLENGE") || text.contains("JOIN GROUP");
    if (!(question || screen)){
        return false;
    }
    std::optional<Point> cancel;
    for (const Nav::Line& line : lines){
        for (const Nav::Word& word : line.words){
            if (!cancel.has_value() && word.text == "CANCEL"){
                cancel = Point{word.x, word.y};
            }
        }
    }
    if (cancel.has_value()){
        host.log("group question - tapping CANCEL (not joining)");
        host.tap(cancel->x, cancel->y);
    }else if (question){
        host.log("group question - going back (not joining)");
        host.back();
    }else{
        host.log("Weekly Challenge / group screen - closing it");
        host.tap(PARTY_CLOSE_BTN.x, PARTY_CLOSE_BTN.y);
    }
    return true;
}

bool is_rocket_text(Host& host, const cv::Mat& img){
    const QString t = Start::ocr_text(host, img, 1300, 2208);
    for (const char* word : {"TEAM GO ROCKET", "GRUNT", "BATTLE PARTY", "USE THIS PARTY"}){
        if (t.contains(QLatin1String(word))){
            return true;
        }
    }
    return false;
}

bool storage_full(Host& host, const cv::Mat& img){
    const QString t = Start::ocr_text(host, img, 450, 700);
    return t.contains("STORAGE") && t.contains("FULL");
}

void pause_catching(Host& host, Map::State& map){
    map.catching = false;
    host.log(QString("POKÉMON STORAGE FULL - transfer some Pokémon; catching paused for %1 min").arg((int)(STORAGE_FULL_WAIT / 60)));
    host.resume_catch_later(STORAGE_FULL_WAIT);
}

void resume_catching(Host& host, Map::State& map){
    map.catching = true;
    host.log("catching re-enabled");
}


double step(Host& host, Map::State& map, State& state){
    const double heat = heat_wait(host, state);
    if (heat != 0){
        return heat;
    }
    if (!host.screen_ok()){                 //  e.g. a foldable was folded during the run: the layout is not supported
        if (host.layout_adapt("the screen has another shape than the canvas")){
            return 3;
        }
        host.wait_unsupported();
        return 5;
    }
    host.layout_watch();
    //  is the phone awake and unlocked?  Asking Android takes a while, so only do it when the last look did not show a normal game screen, or
    //  now and then.
    if (!state.health.ok || host.wall() - state.health.t > HEALTH_EVERY){
        if (!host.power_state().contains("mWakefulness=Awake")){
            host.key_wakeup();
            host.sleep(2);
        }
        host.unlock();
        state.health.t = host.wall();
    }
    const double t_step = host.wall();
    const double t_shot = t_step;
    cv::Mat img;
    if (!map.handoff.img.empty() && host.wall() - map.handoff.t < HANDOFF_MAX_AGE){
        img = map.handoff.img;              //  looked at a moment ago while waiting for the catch result: no new screenshot
        map.handoff.img = cv::Mat();
    }else{
        map.handoff.img = cv::Mat();
        if (map.rotation.armed.has_value()){
            img = host.unlock_game(host.quick_screenshot_grab([&]{ Map::fire_rotation(host, map); }));
        }else{
            img = host.unlock_game(host.quick_screenshot());
        }
    }
    const double shot_cost = host.wall() - t_shot;

    std::pair<QString, double> seen = host.screen_class(img);
    QString name = seen.first;
    if (seen.second < Catch::TH_CLASS){
        name = "onbekend";
    }
    if (host.quick_live() && name != "mapScreen" && name != "encounterScreen"){
        img = host.unlock_game(host.screenshot());          //  (a picture of the video is not sharp enough to read text)
        seen = host.screen_class(img);
        name = seen.first;
        if (seen.second < Catch::TH_CLASS){
            name = "onbekend";
        }
    }
    if (name != "mapScreen" && !host.on_map(img)){          //  (a swipe started for a picture that turned out not to be the map: forget it)
        map.rotation.fired.reset();
        map.rotation.armed.reset();
    }
    state.health.ok = is_home(name);
    if (state.same_screen.name.has_value() && *state.same_screen.name == name){
        state.same_screen.count++;
    }else{
        state.same_screen.name = name;
        state.same_screen.count = 1;
    }

    //  away from the map / catch screen / PokéStop for minutes (e.g. going round in circles between two menus)?  Then start the game again.
    if (is_home(name)){
        state.away_since.reset();
    }else if (!state.away_since.has_value()){
        state.away_since = host.wall();
    }else if (host.wall() - *state.away_since > AWAY_LIMIT){
        host.log(QString("not back on the map for %1 min (now '%2') - restarting Pokémon GO").arg((int)(AWAY_LIMIT / 60)).arg(name));
        host.save_picture("g_stuck.png", img);
        host.restart_game();
        state.away_since.reset();
        state.same_screen.name.reset();
        state.same_screen.count = 0;
        return 5;
    }

    //  stuck?  (not the map, and the same screen 12 times already)
    if (name != "mapScreen" && state.same_screen.count > STUCK_COUNT){
        host.log(QString("stuck on '%1' - restarting Pokémon GO").arg(name));
        host.restart_game();
        state.same_screen.name.reset();
        state.same_screen.count = 0;
        return 5;
    }

    //  did the previous step tap a "Pokémon" without the catch screen opening (e.g. your buddy, or storage full)?  Then skip that spot for longer.
    Map::LastTap& last = map.last_tap;
    const bool tapped_pokemon = last.kind.has_value() && *last.kind == "pokemon";
    if (tapped_pokemon && name == "mapScreen" && last.alt.has_value() && !last.alt->empty()){
        const Point alt = last.alt->front();            //  the tap before did not open it: try lower down
        last.alt->erase(last.alt->begin());
        host.log(QString("no encounter yet - tapping lower (%1, %2)").arg(alt.x).arg(alt.y));
        host.tap(alt.x, alt.y);
        return 3;
    }
    if (tapped_pokemon && name != "encounterScreen"){
        const Point xy = *last.xy;
        map.cooldown.push_back(Map::Cool{xy.x, xy.y, host.wall() + COOLDOWN});
        host.log(QString("no encounter after tapping (%1, %2) [%3] - skipping for %4 min").arg(xy.x).arg(xy.y).arg(name).arg((int)(COOLDOWN / 60)));
        if (last.near && host.setting("buddy", false)){     //  probably your buddy, not a wild Pokémon
            map.near_until = host.wall() + NEAR_BLOCK;
            host.log(QString("that was next to the trainer - leaving Pokémon there alone for %1 min").arg((int)(NEAR_BLOCK / 60)));
        }
        host.save_picture("g_pokemon_na_tik.png", img);
    }
    if ((name == "rocketScreen" || (is_menu_like(name) && is_rocket_text(host, img))) && host.setting("rocket_fight", true)){
        host.log("Team GO Rocket at the stop - battling");
        host.save_picture("g_rocket.png", img);
        QString res;
        try{
            res = host.rocket_battle();
        }catch (const Flow::Interrupted&){                  //  (the person stopped the bot: Python's `except Exception` does not take that)
            throw;
        }catch (const std::exception& e){
            host.log(QString("rocket: error %1").arg(QString::fromUtf8(e.what())));
            res = "failed";
        }
        if (res != "failed"){
            return 1;
        }
        if (last.kind.has_value() && *last.kind == "stop"){     //  (it went wrong: leave that stop alone for a while)
            const Point xy = *last.xy;
            map.cooldown.push_back(Map::Cool{xy.x, xy.y, host.wall() + ROCKET_COOLDOWN});
        }
        name = host.screen_class(host.screenshot()).first;
    }
    if (name == "rocketScreen" || (is_menu_like(name) && is_rocket_text(host, img))){
        if (last.kind.has_value() && *last.kind == "stop"){
            const Point xy = *last.xy;
            map.cooldown.push_back(Map::Cool{xy.x, xy.y, host.wall() + ROCKET_COOLDOWN});
        }
        host.log(QString("Team Rocket - not battling, leaving (stop skipped for %1 min)").arg((int)(ROCKET_COOLDOWN / 60)));
        host.save_picture("g_rocket.png", img);
        for (int i = 0; i < 3; i++){                //  back out of the dialogue / battle party screen
            host.back();
            host.sleep(1.5);
            const std::pair<QString, double> now = host.screen_class(host.screenshot());
            if (now.first == "mapScreen" && now.second >= Catch::TH_CLASS){
                break;
            }
        }
        last.kind.reset();
        last.xy.reset();
        last.alt.reset();
        return 3;
    }
    if (tapped_pokemon && name == "encounterScreen"){
        map.enc_xy = last.xy;                       //  (fast catch: where this Pokémon is on the map)
    }
    last.kind.reset();
    last.xy.reset();
    last.alt.reset();

    if (name == "mapScreen" && (host.layout_state() == "new" || host.layout_state() == "adapting")){
        host.layout_verify(img);                    //  first map picture of this run: is the game drawn as expected?
        const QString layout = host.layout_state();
        if (layout == "adapting" || layout == "adapted" || !host.screen_ok()){
            return 1.0;                             //  (the display changed, or is still being checked: look at the game again)
        }
    }
    if (name == "mapScreen" && host.quests_due(img)){
        QString res;
        try{
            res = host.claim_quests();
        }catch (const Flow::Interrupted&){
            throw;
        }catch (const std::exception& e){
            host.log(QString("quests: error %1").arg(QString::fromUtf8(e.what())));
            res = "failed";
        }
        if (res != "failed"){
            return 1.0;
        }
    }
    if (name == "mapScreen"){
        map.perf.shot += shot_cost;
        map.perf.t_step = t_step;
        const double wait = host.do_map(img);
        map.perf.total += host.wall() - t_step;     //  (without the wait that follows)
        return wait;
    }
    if (name == "pokestopScreen"){
        return host.do_pokestop(img);
    }
    if (name == "encounterScreen"){
        return host.do_encounter(img);
    }
    if (name == "eggScreen"){
        host.tap(CENTER.x, CENTER.y);
        return 3;
    }
    if (name == "summaryScreen"){                   //  Pokémon summary after catching
        Catch::mark_caught(host, map);
        host.back();
        return Throw::AFTER_TAP_WAIT;
    }
    if (name != "encounterScreen" && name != "mapScreen" && Start::news_popup(host, img)){
        host.log("news popup - tapping DISMISS");
        host.tap(Start::DISMISS_BTN.x, Start::DISMISS_BTN.y);
        return 1.5;                                 //  (several cards can follow each other)
    }
    if ((is_menu_like(name) || name == "summaryScreen") && leave_group_screen(host, img)){
        return 3;
    }
    if (is_menu_like(name) && Start::safety_notice(host, img)){
        Point btn = Start::NOTICE_OK_BTN;
        if (const std::optional<Start::Found> pill = Start::find_pill_button(img)){
            btn = Point{pill->x, pill->y};
        }else if (const std::optional<Start::Found> green = Start::find_green_button(img)){
            btn = Point{green->x, green->y};
        }
        host.log("startup safety notice - tapping OK");
        host.tap(btn.x, btn.y);
        return 3;
    }
    if (is_menu_like(name) && storage_full(host, img)){
        host.save_picture("g_opslag_vol.png", img);
        host.back();                                //  close the notification (never tap MANAGE POKÉMON)
        if (map.catching){
            pause_catching(host, map);
        }
        return 3;
    }
    if (name == "menusScreen"){                     //  only click away "you are going too fast", otherwise go back
        if (!Catch::tap_button(host, img, true)){
            host.back();
        }
        return 3;
    }
    if (name == "rewardScreen" || name == "onbekend"){
        if (map.enc.throws > 0){
            Catch::mark_caught(host, map);          //  "TOTAL XP" with OK after a throw = caught
            const std::optional<Point> btn = Catch::catch_result_button(host, map, img);
            if (btn.has_value()){
                Catch::tap_catch_result(host, map, *btn, name);
                return 1.5;
            }
        }
        if (Catch::tap_button(host, img)){
            return Throw::AFTER_TAP_WAIT;
        }
        if (const std::optional<Start::Found> green = Start::find_green_button(img)){      //  old method as a fallback
            host.tap(green->x, green->y);
            return Throw::AFTER_TAP_WAIT;
        }
        if (name == "onbekend" && host.on_map(img)){
            return host.do_map(img);
        }
        host.back();
        return 3;
    }
    //  rocketScreen, areneScreen and the rest: back
    host.back();
    return 3;
}


}
}
}
}
