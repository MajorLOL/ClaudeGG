/*  Claude GG Pokemon GO Start (starting the game and the battles of a run, of the Pokémon GO bot)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  See the header.  The numbers, the order of what is looked at and the words of the log lines are those of gamebot.py
 *  (news_popup, safety_notice, find_pill_button, startup_screen, auto_battle, battle_app, battle_league, battle_count) and of
 *  spin_stop.py (find_green_button, restart_game); the checks hold the port to the order of what was read and done.
 *
 */

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <opencv2/imgproc.hpp>
#include "ClaudeGG_PokemonGoStart.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Start{

const Point DISMISS_BTN = {884, 2098};
const Point NOTICE_OK_BTN = {884, 2005};
const char* const MAIN_PACKAGE = "com.nianticlabs.pokemongo";
const char* const BATTLE_LEAGUE = "Great League";
const int BATTLE_COUNT = 5;

namespace{

const double START_SECONDS = 100;           //  the most time that the start of the game may take
const int LEAGUE_LETTERS = 40;
const int COUNT_MOST = 50;

//  f"{x:.Nf}" of Python.
QString fixed(double x, int digits){
    char buffer[64];
    std::snprintf(buffer, sizeof(buffer), "%.*f", digits, x);
    return QString::fromLatin1(buffer);
}

//  The pixels of the picture that the (BGR) picture is looked at in: rows from `y0` on, as a mask of what the colours say.
cv::Mat green_mask(const cv::Mat& img, int y0, int saturation, int v_low, int v_high){
    cv::Mat hsv;
    cv::cvtColor(img.rowRange(y0, img.rows), hsv, cv::COLOR_BGR2HSV);
    cv::Mat mask;
    cv::inRange(hsv, cv::Scalar(45, saturation + 1, v_low + 1), cv::Scalar(95, 255, v_high), mask);
    return mask / 255;
}

}


std::optional<Found> find_pill_button(const cv::Mat& img, int y_min){
    if (img.empty() || y_min < 0 || y_min >= img.rows){
        return std::nullopt;
    }
    //  (the light green background of the gift screens is brighter, V ~255, and paler than the button: only V under 248 counts)
    cv::Mat m = green_mask(img, y_min, 62, 170, 247);
    cv::morphologyEx(m, m, cv::MORPH_OPEN, cv::Mat::ones(9, 9, CV_8U));
    cv::morphologyEx(m, m, cv::MORPH_CLOSE, cv::Mat::ones(25, 25, CV_8U));
    cv::Mat labels, stats, centroids;
    const int n = cv::connectedComponentsWithStats(m, labels, stats, centroids);
    std::optional<Found> best;
    for (int i = 1; i < n; i++){
        const int x = stats.at<int>(i, cv::CC_STAT_LEFT);
        const int y = stats.at<int>(i, cv::CC_STAT_TOP);
        const int w = stats.at<int>(i, cv::CC_STAT_WIDTH);
        const int h = stats.at<int>(i, cv::CC_STAT_HEIGHT);
        const int a = stats.at<int>(i, cv::CC_STAT_AREA);
        if (450 < w && w < 1300 && 80 < h && h < 320 && w > 2.5 * h && std::abs(x + w / 2 - 884) < 300
            && (!best.has_value() || a > best->area)){
            best = Found{x + w / 2, y + h / 2 + y_min, a};
        }
    }
    return best;
}

std::optional<Found> find_green_button(const cv::Mat& img){
    if (img.empty()){
        return std::nullopt;
    }
    const int y0 = img.rows / 2;
    cv::Mat m = green_mask(img, y0, 55, 170, 255);
    cv::morphologyEx(m, m, cv::MORPH_CLOSE, cv::Mat::ones(25, 25, CV_8U));
    cv::Mat labels, stats, centroids;
    const int n = cv::connectedComponentsWithStats(m, labels, stats, centroids);
    std::optional<Found> best;
    for (int i = 1; i < n; i++){
        const int x = stats.at<int>(i, cv::CC_STAT_LEFT);
        const int y = stats.at<int>(i, cv::CC_STAT_TOP);
        const int w = stats.at<int>(i, cv::CC_STAT_WIDTH);
        const int h = stats.at<int>(i, cv::CC_STAT_HEIGHT);
        const int a = stats.at<int>(i, cv::CC_STAT_AREA);
        const int cx = x + w / 2;
        //  only wide buttons in the middle (OK / CLAIM REWARD), never POWER UP / EVOLVE
        if (a > 20000 && w > 700 && w > 2.2 * h && h > 60 && std::abs(cx - 884) < 200 && (!best.has_value() || a > best->area)){
            best = Found{x + w / 2, y + h / 2 + y0, a};
        }
    }
    return best;
}


//  gamebot.ocr_text(): the words of a strip of the screen in capitals, white space as one space.  (The reader of the host gives ""
//  where the text reader is not there or does not answer in time; gamebot.py lets the second end that look with an error, which the
//  start-up check logs - the port goes on with the next look without that log line and the two seconds that follow it.)
QString ocr_text(Loop::Host& host, const cv::Mat& img, int y0, int y1){
    const int to = std::min(y1, img.rows);
    if (img.empty() || y0 < 0 || y0 >= to){
        return QString();
    }
    return host.ocr_line(img.rowRange(y0, to), 2).toUpper();
}

bool news_popup(Loop::Host& host, const cv::Mat& img){
    return ocr_text(host, img, 2000, 2208).contains("DISMISS");
}

bool safety_notice(Loop::Host& host, const cv::Mat& img){
    const QString t = ocr_text(host, img, 1100, 1800);
    for (const char* word : {"SURROUNDINGS", "TRESPASS", "WHILE DRIVING", "DANGEROUS AREAS"}){
        if (t.contains(QLatin1String(word))){
            return true;
        }
    }
    return false;
}


Look startup_screen(Flow::Host& host, const cv::Mat& img){
    if (news_popup(host, img)){
        host.log("news popup at start-up - tapping DISMISS");
        host.tap(DISMISS_BTN.x, DISMISS_BTN.y);
        return Look::Handled;
    }
    if (safety_notice(host, img)){
        std::optional<Found> button = find_pill_button(img);
        if (!button.has_value()){
            button = find_green_button(img);
        }
        host.log("startup safety notice - tapping OK");
        if (button.has_value()){
            host.tap(button->x, button->y);
        }else{
            host.tap(NOTICE_OK_BTN.x, NOTICE_OK_BTN.y);
        }
        return Look::Handled;
    }
    return host.on_map(img) ? Look::Map : Look::Nothing;
}


void restart_game(Host& host){
    host.log("restarting Pokémon GO");
    const double t_begin = host.wall();
    host.stop_game();
    const double t_stopped = host.wall() - t_begin;
    host.sleep(1);
    //  The command that starts the game can take half a minute to end while the game is starting (it waits for the app), so it is not
    //  waited for: the screenshots start straight away.
    host.start_game();
    host.sleep(2);                      //  (nothing useful to see in the first moments)
    const double t0 = host.wall();
    int on_map_frames = 0;
    std::optional<double> first_shot;
    bool up = false;
    while (host.wall() - t0 < START_SECONDS){
        Look result = Look::Nothing;
        try{
            const cv::Mat img = host.screenshot();
            if (!first_shot.has_value()){
                first_shot = host.wall() - t_begin;
            }
            result = startup_screen(host, img);
        }catch (const Flow::Interrupted&){
            throw;
        }catch (const std::exception& e){
            host.log(QString("start-up check failed: %1").arg(QString::fromUtf8(e.what())));
            host.sleep(2);
            continue;
        }
        if (result == Look::Map){
            on_map_frames++;            //  twice in a row: a card that slides in a moment later is caught too
            if (on_map_frames >= 2){
                up = true;
                break;
            }
        }else{
            on_map_frames = 0;
            host.sleep(result == Look::Handled ? 0.8 : 0.3);
        }
    }
    if (!up){
        host.log("Pokémon GO did not reach the map within 100 s - carrying on");
        on_map_frames = 0;
    }
    const Launch launch = host.start_state();
    if (launch.running){
        host.start_end();               //  (still waiting for the game: no need for it any more)
    }else if (launch.code != 0){
        const QString error = launch.error.trimmed().left(120);
        host.log(QString("WARNING: starting Pokémon GO with monkey failed (%1)")
            .arg(error.isEmpty() ? QString("return code %1").arg(launch.code) : error));
    }
    if (on_map_frames >= 2){
        host.log(QString("Pokémon GO is on the map (%1 s after starting; closing the old game took %2 s, first screenshot after %3 s)")
            .arg(fixed(host.wall() - t_begin, 0), fixed(t_stopped, 1), fixed(first_shot.value_or(0.0), 0)));
    }
}


Choice choose(const Settings& settings, bool done_today){
    Choice choice;
    choice.wanted = settings.battle && !done_today;
    choice.app = settings.app.isEmpty() ? QString(MAIN_PACKAGE) : settings.app;
    QString league = settings.league.value_or(QString(BATTLE_LEAGUE));
    if (league.isEmpty()){
        league = BATTLE_LEAGUE;
    }
    choice.league = league.trimmed().left(LEAGUE_LETTERS);
    choice.count = std::min(std::max(settings.count.value_or(BATTLE_COUNT), 1), COUNT_MOST);
    return choice;
}

AutoBattle auto_battle(Flow::Host& host, const QString& package, const Settings& settings, bool done_today,
                       const TeamLoader& load_team, const Runner& run){
    AutoBattle out;
    const Choice choice = choose(settings, done_today);
    if (!choice.wanted || package != choice.app){
        if (settings.battle && package == choice.app && done_today){
            host.log("battle: the battles of today are done (the BATTLE button was grey) - spinning and catching");
        }
        return out;
    }
    std::vector<Battle::Mon> team;
    try{
        team = load_team();
    }catch (const Flow::Interrupted&){
        throw;
    }catch (const std::exception& e){
        host.log(QString("battle: the battle engine could not be loaded (%1) - no battles").arg(QString::fromUtf8(e.what())));
        return out;
    }
    QStringList labels;
    for (const Battle::Mon& mon : team){
        labels << mon.label();
    }
    host.log(QString("battle: %1 battle(s) in '%2' with %3").arg(choice.count).arg(choice.league, labels.join(", ")));
    host.beat();
    const Flow::Run res = run ? run(host, team, choice.count) : Flow::battle_run(host, team, choice.count);
    const bool catch_reward = res.catch_reward.value_or(false);
    const bool leave = res.leave.value_or(false);
    host.log(QString("battle: done - %1 fought, %2 won").arg(res.fought).arg(res.wins)
        + (catch_reward ? QString(" - the normal bot catches the Pokémon of the reward, then the battles go on")
            : leave ? QString(" - the normal bot goes on from the screen that is there") : QString()));
    out.resume = catch_reward;
    host.beat();
    out.fought = res.fought;
    return out;
}


std::vector<std::pair<QString, std::vector<double>>> start_constants(){
    return {
        {"DISMISS_BTN", {(double)DISMISS_BTN.x, (double)DISMISS_BTN.y}},
        {"NOTICE_OK_BTN", {(double)NOTICE_OK_BTN.x, (double)NOTICE_OK_BTN.y}},
        {"BATTLE_COUNT", {(double)BATTLE_COUNT}},
    };
}


}
}
}
}
