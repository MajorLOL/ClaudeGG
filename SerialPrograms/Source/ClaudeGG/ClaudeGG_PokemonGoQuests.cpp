/*  Claude GG Pokemon GO Quests (the rewards of the GO Pass in the Pokémon GO bot: see that the quest button is gold, and claim what waits)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  See ClaudeGG_PokemonGoQuests.h.  What the Python code does is followed line by line, down to the order of the taps, the waits and the log lines.
 *
 */

#include <algorithm>
#include <optional>
#include <vector>
#include <opencv2/imgproc.hpp>
#include "ClaudeGG_PokemonGoCatch.h"
#include "ClaudeGG_PokemonGoFlow.h"
#include "ClaudeGG_PokemonGoQuests.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Quests{

namespace{

//  A line of the text reader that has been found: its text as the reader wrote it, and where to tap.
struct Found{
    QString text;
    int x = 0;
    int y = 0;
};

//  _tap_word(): tap the first line that holds all the words (in capitals; the line is read in capitals as well).  (Python also asks for the line not to
//  be above 'below' = 0 of the picture: a line of the reader never is.)
std::optional<Found> tap_word(Map::Host& host, const Nav::Lines& lines, const QStringList& words){
    for (const Nav::Line& line : lines){
        const QString upper = line.text.toUpper();
        bool all = true;
        for (const QString& word : words){
            if (!upper.contains(word)){
                all = false;
                break;
            }
        }
        if (all){
            host.tap(line.x, line.y);
            return Found{line.text, line.x, line.y};
        }
    }
    return std::nullopt;
}

//  _frac_xy(): a place as fractions of the screen -> pixels of the canvas.
void tap_fraction(Map::Host& host, double fx, double fy){
    host.tap((int)(fx * CANVAS_W), (int)(fy * CANVAS_H));
}

}


bool quest_gold(const cv::Mat& img){
    const int h = img.rows;
    const int w = img.cols;
    const double cx = BUTTON_X * w;
    const double cy = BUTTON_Y * h;
    const double r = BUTTON_R * w;
    //  img[max(y0, 0):y1, max(x0, 0):x1] (numpy cuts the end at the edge of the picture)
    const int y0 = std::max((int)(cy - r), 0);
    const int y1 = std::min((int)(cy + r) + 1, h);
    const int x0 = std::max((int)(cx - r), 0);
    const int x1 = std::min((int)(cx + r) + 1, w);
    if (y1 <= y0 || x1 <= x0){
        return false;
    }
    cv::Mat hsv;
    cv::cvtColor(img(cv::Rect(x0, y0, x1 - x0, y1 - y0)), hsv, cv::COLOR_BGR2HSV);
    cv::Mat gold;                                           //  (hue 8 to 25, saturation 120 or more, value 180 or more)
    cv::inRange(hsv, cv::Scalar(8, 120, 180), cv::Scalar(25, 255, 255), gold);
    return (double)cv::countNonZero(gold) / ((double)hsv.rows * (double)hsv.cols) >= GOLD_SHARE;
}

bool quests_due(Map::Host& host, const State& state, const cv::Mat& img){
    if (!host.setting("quests", true) || host.wall() - state.t < EVERY){
        return false;
    }
    return quest_gold(img);
}

QString claim_quests(Map::Host& host, State& state){
    state.t = host.wall();
    host.log("quests: the quest button is gold - looking at the GO Pass");
    tap_fraction(host, BUTTON_X, BUTTON_Y);
    cv::Mat shot = Flow::settled(host, 2.5);
    Nav::Lines lines = host.ocr_lines(shot, 100, 2150, 0.6);
    host.save_picture("g_quest_0.png", shot);
    if (host.on_map(shot)){
        host.log("quests: the quest screen did not open");
        return "failed";
    }
    const int h = shot.rows;
    if (!tap_word(host, lines, {"GO PASS"}).has_value()){
        host.log(QString("quests: no GO PASS tab (%1)").arg(Nav::reads(lines, 80)));
        tap_fraction(host, CLOSE_X, CLOSE_Y);
        return "failed";
    }
    shot = Flow::settled(host, 1.5);
    lines = host.ocr_lines(shot, 100, 2150, 0.6);
    std::vector<std::optional<Found>> pages;
    for (const Nav::Line& line : lines){
        if (line.text.toUpper().contains("GO PASS") && line.text.contains(':') && line.y < 0.35 * h){
            pages.push_back(Found{line.text, line.x, line.y});
        }
    }
    if (pages.empty()){
        pages.push_back(std::nullopt);
    }
    bool claimed = false;
    for (size_t p = 0; p < pages.size() && p < (size_t)PAGES; p++){
        const std::optional<Found>& page = pages[p];
        if (page.has_value()){
            host.tap(page->x, page->y);
            host.sleep(2.0);
        }
        bool found = false;
        for (int look = 0; look < PAGE_LOOKS; look++){      //  down the page to 'Claimable rewards' / VIEW REWARDS
            shot = host.screenshot();
            lines = host.ocr_lines(shot, 300, 2050, 0.6);
            found = tap_word(host, lines, {"VIEW", "REWARDS"}).has_value();
            if (found){
                break;
            }
            bool daily = false;
            for (const Nav::Line& line : lines){
                if (line.text.toUpper().contains("DAILY TASKS")){
                    daily = true;
                    break;
                }
            }
            if (daily){
                break;                                      //  (past the place where it would be)
            }
            host.swipe(884, 1700, 884, 900, 700);
            host.sleep(1.2);
        }
        if (!found){
            continue;
        }
        host.log(QString("quests: VIEW REWARDS on '%1'").arg(page.has_value() ? page->text : QString("the GO Pass")));
        shot = Flow::settled(host, 2.0);
        lines = host.ocr_lines(shot, 300, 2150, 0.6);
        host.save_picture("g_quest_rewards.png", shot);
        if (!tap_word(host, lines, {"CLAIM", "ALL"}).has_value()){
            host.log(QString("quests: no CLAIM ALL (%1)").arg(Nav::reads(lines, 80)));
            break;
        }
        claimed = true;
        host.log("quests: CLAIM ALL");
        host.sleep(4.0);
        shot = host.screenshot();
        const std::pair<QString, double> klass = host.screen_class(shot);
        if (klass.first == "encounterScreen" && klass.second >= Catch::TH_CLASS){
            host.log("quests: a Pokémon came as a reward - the normal bot catches it");
            state.t = host.wall() - EVERY + 60;             //  (look again a minute after it)
            return "catch";
        }
        break;
    }
    for (int k = 0; k < CLOSES; k++){                       //  close: the round X at the bottom
        if (host.on_map(host.screenshot())){
            break;
        }
        tap_fraction(host, CLOSE_X, CLOSE_Y);
        host.sleep(2.0);
    }
    host.log(QString("quests: ") + (claimed ? "rewards claimed" : "nothing to claim in the GO Pass - looking again in an hour"));
    if (!claimed){                                          //  (the button stays gold for something else: research)
        state.t = host.wall() + NOTHING - EVERY;
    }
    return claimed ? "claimed" : "nothing";
}


}
}
}
}
