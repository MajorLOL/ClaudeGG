/*  Claude GG Pokemon GO Rocket (Team GO Rocket at a PokéStop in the Pokémon GO bot: the way to the fight and back to the map)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  See ClaudeGG_PokemonGoRocket.h.  What the Python code does is followed line by line, down to the order of the taps, the waits and the log lines.
 *
 */

#include <algorithm>
#include <cmath>
#include <optional>
#include <vector>
#include <opencv2/imgproc.hpp>
#include <QRegularExpression>
#include "ClaudeGG_PokemonGoCatch.h"
#include "ClaudeGG_PokemonGoRocket.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Rocket{

namespace{

//  A word of the text reader (in capitals) and where it stands.
struct Spot{
    QString word;
    int x;
    int y;
};

//  _rocket_words(): all the words of all the lines, in capitals.
std::vector<Spot> words_of(const Nav::Lines& lines){
    std::vector<Spot> out;
    for (const Nav::Line& line : lines){
        for (const Nav::Word& word : line.words){
            out.push_back(Spot{word.text.toUpper(), word.x, word.y});
        }
    }
    return out;
}

//  next(((x, y) for wd, x, y in ws if wd == word), None)
std::optional<Spot> find_word(const std::vector<Spot>& words, const QString& word){
    for (const Spot& spot : words){
        if (spot.word == word){
            return spot;
        }
    }
    return std::nullopt;
}

//  The word BATTLE in the lower quarter of the screen (the first one): the button of the screen before the fight.
std::optional<Spot> find_battle(const std::vector<Spot>& words, int h){
    for (const Spot& spot : words){
        if (spot.word == "BATTLE" && spot.y > BATTLE_FROM * h){
            return spot;
        }
    }
    return std::nullopt;
}

//  _canvas(img, x, y): a place on the picture as a place on the canvas.
void tap_canvas(Host& host, const cv::Mat& img, double x, double y){
    host.tap((int)(x * CANVAS_W / img.cols), (int)(y * CANVAS_H / img.rows));
}

//  _frac_xy(): a place as fractions of the screen -> pixels of the canvas.
void tap_fraction(Host& host, double fx, double fy){
    host.tap((int)(fx * CANVAS_W), (int)(fy * CANVAS_H));
}

//  re.fullmatch(r"(CP)?\d{3,4}", word): \d of Python is every digit of every script.
bool is_cp_number(const QString& word){
    static const QRegularExpression pattern(QRegularExpression::anchoredPattern("(CP)?\\d{3,4}"), QRegularExpression::UseUnicodePropertiesOption);
    return pattern.match(word).hasMatch();
}

}


QString rocket_battle(Host& host){
    bool picked = false;
    bool fought = false;
    int unknown = 0;
    for (int step = 0; step < STEPS; step++){
        if (host.stop()){
            return "failed";
        }
        const cv::Mat shot = host.screenshot();
        const int h = shot.rows;
        const int w = shot.cols;
        if (host.on_map(shot)){
            host.log("rocket: back on the map");
            return "map";
        }
        cv::Mat small;                                      //  (the picture that the fight reader looks at: 704 wide)
        cv::resize(shot, small, cv::Size(SMALL_W, (int)std::nearbyint(h * (double)SMALL_W / w)), 0.0, 0.0, cv::INTER_AREA);
        const QString state = host.screen_state(small);
        if (state == "fight" || state == "prompt"){
            host.rocket_fight();
            fought = true;
            continue;
        }
        const Nav::Lines lines = host.ocr_lines(shot, 100, 2150, 0.6);
        QStringList texts;
        for (const Nav::Line& line : lines){
            texts << line.text;
        }
        const QString text = texts.join(' ').toUpper();
        const std::vector<Spot> ws = words_of(lines);
        const std::pair<QString, double> klass = host.screen_class(shot);
        if (klass.first == "encounterScreen" && klass.second >= Catch::TH_CLASS && fought){
            host.log("rocket: the Shadow Pokémon to catch - the normal bot catches it");
            return "catch";
        }
        host.save_picture(QString("g_rocket_s%1.png").arg(step % 20), shot);
        if (text.contains("ROCKET RADAR")){
            const std::optional<Spot> yes = find_word(ws, "YES");
            host.log("rocket: 'Use your Rocket Radar?' - YES");
            if (yes.has_value()){
                tap_canvas(host, shot, yes->x, yes->y);
            }else{
                tap_fraction(host, 0.50, 0.42);
            }
        }else if (text.contains("USE THIS PARTY") || text.contains("RECOMMENDED")){
            const std::optional<Spot> use = find_word(ws, "USE");
            std::vector<Spot> cps;                          //  the numbers of the Pokémon in the slots (CP2699 ...), above USE THIS PARTY
            for (const Spot& spot : ws){
                if (is_cp_number(spot.word) && (!use.has_value() || spot.y < use->y)){
                    cps.push_back(spot);
                }
            }
            std::vector<int> filled;
            for (int i = 0; i < 3; i++){
                for (const Spot& cp : cps){
                    if (std::abs((double)cp.x / w - PARTY_X.at(i)) < PARTY_SLOT_NEAR){
                        filled.push_back(i);
                        break;
                    }
                }
            }
            std::vector<int> empty;
            for (int i = 0; i < 3; i++){
                if (std::find(filled.begin(), filled.end(), i) == filled.end()){
                    empty.push_back(i);
                }
            }
            if (!cps.empty() && !empty.empty() && filled.size() < 3 && !picked){
                int lowest = cps.front().y;
                for (const Spot& cp : cps){
                    lowest = std::max(lowest, cp.y);
                }
                const int y = lowest + (int)(PARTY_BELOW * h);
                host.log(QString("rocket: the party has %1 Pokémon - choosing a third one for slot %2").arg((int)filled.size()).arg(empty.front() + 1));
                tap_canvas(host, shot, PARTY_X.at(empty.front()) * w, y);
            }else if (use.has_value()){
                host.log(QString("rocket: USE THIS PARTY (%1 Pokémon)").arg(filled.empty() ? QString("?") : QString::number((int)filled.size())));
                tap_canvas(host, shot, use->x, use->y);
            }else{
                tap_fraction(host, 0.50, 0.70);
            }
        }else if (text.contains("CANCEL") && text.contains("DONE")){
            const std::optional<Spot> done = find_word(ws, "DONE");
            if (!picked){
                host.log("rocket: the list of Pokémon - the first one");
                tap_fraction(host, LIST_FIRST_X, LIST_FIRST_Y);
                picked = true;
            }else if (done.has_value()){
                host.log("rocket: DONE");
                tap_canvas(host, shot, done->x, done->y);
            }
        }else if (text.contains("SUMMARY")){
            host.log("rocket: the summary - tapping on");
            tap_fraction(host, 0.50, 0.85);
        }else if (!fought && find_battle(ws, h).has_value()){
            const Spot battle = *find_battle(ws, h);
            host.log("rocket: BATTLE");
            tap_canvas(host, shot, BATTLE_X * w, battle.y);
        }else{                                              //  speech bubbles, the rewards, the VS screen
            unknown++;
            if (unknown > UNKNOWN_SCREENS){
                host.log("rocket: too many screens that are not known - stopping");
                return "failed";
            }
            tap_fraction(host, 0.50, 0.55);
        }
        host.sleep(LOOK_EVERY);
    }
    return "failed";
}


}
}
}
}
