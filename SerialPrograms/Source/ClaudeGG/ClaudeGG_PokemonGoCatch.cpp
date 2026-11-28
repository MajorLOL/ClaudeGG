/*  Claude GG Pokemon GO Catch (the catch screen around the throw of the Pokémon GO bot)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <stdexcept>
#include <opencv2/imgproc.hpp>
#include <QRegularExpression>
#include "ClaudeGG_PokemonGoCatch.h"
#include "ClaudeGG_PokemonGoPy.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Catch{

namespace{

using Py::fixed;
using Py::py_float;
using Py::py_int;
using Py::py_repr;
using Py::py_space;
using Py::py_strip;

//  The ball buttons of the tray (S.BALL_POS[BALL]: a ball that is none of them is a KeyError).
Point ball_pos(const QString& ball){
    if (ball == "poke"){
        return BALL_POS_POKE;
    }
    if (ball == "great"){
        return BALL_POS_GREAT;
    }
    if (ball == "ultra"){
        return BALL_POS_ULTRA;
    }
    throw std::runtime_error(py_repr(ball).toStdString());
}

//  Answer 'Do you want to exit Pokémon GO?' with CANCEL.
void cancel_exit(Host& host, const Nav::Lines& lines){
    for (const Nav::Line& line : lines){
        for (const Nav::Word& w : line.words){
            if (Nav::like(w.text, "CANCEL", 0.8)){
                host.tap(w.x, w.y);
                return;
            }
        }
    }
    host.back();
}

//  Option 'Fast catch' ticked, and not resting after it failed twice in a row (fast_catch_on())?
bool fast_catch_on(Host& host, const State& state){
    return host.setting("fast_catch", false) && host.wall() >= state.fast_off_until;
}

bool contains_any(const QString& text, std::initializer_list<const char*> words){
    for (const char* word : words){
        if (text.contains(QString::fromUtf8(word))){
            return true;
        }
    }
    return false;
}

}


void mark_caught(Host& host, State& state){
    if (state.enc.throws > 0 && !state.enc.caught){
        state.enc.caught = true;
        state.enc.t_result = host.wall();
        //  (the count is made first: the line that is written holds it)
        const QString counted = host.count("caught");
        host.log(QString::fromUtf8("Pokémon CAUGHT ✔ after %1 ball(s) %2").arg(state.enc.throws).arg(counted));
    }
}


std::optional<Point> catch_result_button(Host& host, State& state, const cv::Mat& img){
    if (state.enc.throws <= 0){
        return std::nullopt;
    }
    const std::optional<Point> btn = Throw::result_ok_button(img);
    if (!btn.has_value()){
        return std::nullopt;
    }
    const std::pair<QString, double> screen = host.screen_class(img);
    if (screen.first == "encounterScreen" && screen.second >= 0.8){
        return std::nullopt;
    }
    return btn;
}


void tap_catch_result(Host& host, State& state, Point btn, const QString& how){
    host.log(QString("catch result screen (%1) - tapping OK").arg(how));
    mark_caught(host, state);
    state.enc.t_tap = host.wall();
    host.tap(btn.x, btn.y);
}


bool tap_button(Host& host, const cv::Mat& img, bool only_passenger){
    const std::vector<Detection> buttons = host.buttons(img);
    if (only_passenger){
        bool found = false;
        for (const Detection& b : buttons){
            if (b.label == "passenger" && b.score >= TH_PASSENGER){
                found = true;
                break;
            }
        }
        if (!found){
            return false;
        }
    }
    for (const Detection& b : buttons){
        if (b.label == "clickable" && b.score >= TH_CLICK && std::abs(b.cx - Loop::REF_W / 2) < 250 && b.w > 500){
            const QString label = Start::ocr_text(host, img, std::max(b.cy - b.h / 2, 0), std::min(b.cy + b.h / 2, Loop::REF_H));
            if (contains_any(label, {"BATTLE", "FIGHT", "USE THIS PARTY", "LET'S GO", "JOIN", "GROUP", "DETAILS"})){
                host.log(QString("button '%1' is a battle/group button - NOT tapping, going back").arg(label));
                host.back();
                return true;
            }
            host.log(QString("button (%1, %2) [%3] - tapping").arg(b.cx).arg(b.cy).arg(fixed(b.score, 2)));
            host.tap(b.cx, b.cy);
            return true;
        }
    }
    return false;
}


bool wait_for_result(Host& host, State& state, double t_throw){
    host.sleep(std::max(Throw::RESULT_FIRST_LOOK - (host.wall() - t_throw), 0.1));
    while (true){
        const cv::Mat img = host.quick_screenshot();
        if (Throw::ball_ready(img)){
            return true;
        }
        const std::optional<Point> btn = catch_result_button(host, state, img);
        if (btn.has_value()){
            tap_catch_result(host, state, *btn, "seen while waiting");
            return false;
        }
        const std::pair<QString, double> screen = host.screen_class(img);
        if (screen.first != "encounterScreen" && screen.second >= TH_CLASS){
            state.handoff.img = img;
            state.handoff.t = host.wall();
            return false;
        }
        if (host.wall() - t_throw > Throw::RESULT_WINDOW){
            return false;
        }
        host.sleep(host.quick_live() ? Throw::POLL_PAUSE_LIVE : Throw::POLL_PAUSE);
    }
}


Cells tray_labels(Host& host, const cv::Mat& img){
    cv::Mat gray;
    cv::cvtColor(img.rowRange(std::min(TRAY_FROM, img.rows), img.rows), gray, cv::COLOR_BGR2GRAY);
    const std::optional<QString> table = host.tray_table(gray);
    if (!table.has_value()){
        host.log("tesseract missing (sudo apt install tesseract-ocr) - no berries");
        return Cells();
    }
    //  csv.DictReader(io.StringIO(out), delimiter="\t", quoting=csv.QUOTE_NONE): the first line names the columns, a line without
    //  anything in it is left out, a line with fewer columns has nothing in the last ones.
    QString text = *table;
    text.replace("\r\n", "\n");
    QStringList lines = text.split('\n');
    if (!lines.isEmpty() && lines.back().isEmpty()){
        lines.removeLast();
    }
    Cells cells;
    if (lines.isEmpty()){
        return cells;
    }
    const QStringList names = lines.front().split('\t');
    const auto field = [&](const QStringList& row, const char* name) -> std::optional<QString>{
        const qsizetype i = names.indexOf(QString(name));
        if (i < 0 || i >= row.size()){
            return std::nullopt;
        }
        return row.at(i);
    };
    for (qsizetype n = 1; n < lines.size(); n++){
        if (lines.at(n).isEmpty()){
            continue;
        }
        const QStringList row = lines.at(n).split('\t');
        const QString word = py_strip(field(row, "text").value_or(QString())).toUpper();
        if (word.isEmpty()){
            continue;
        }
        const QString conf = field(row, "conf").value_or(QString());
        if ((conf.isEmpty() ? -1.0 : py_float(conf)) < TRAY_MIN_CONF){
            continue;
        }
        const auto need = [&](const char* name){
            if (!names.contains(QString(name))){
                throw std::runtime_error(py_repr(QString(name)).toStdString());             //  KeyError: no such column
            }
            const std::optional<QString> v = field(row, name);
            if (!v.has_value()){                                                            //  a line that ends before the column
                throw std::runtime_error("int() argument must be a string, a bytes-like object or a real number, not 'NoneType'");
            }
            return py_int(*v);
        };
        const int left = need("left");
        const int width = need("width");
        const int cx = left + (int)std::floor(width / 2.0);
        const int top = need("top");
        const int height = need("height");
        const int cy = top + (int)std::floor(height / 2.0) + TRAY_FROM;
        int col = 0;
        for (int i = 1; i < 3; i++){
            if (std::abs(TRAY_COLS[i] - cx) < std::abs(TRAY_COLS[col] - cx)){
                col = i;
            }
        }
        int row_found = -1;
        for (int i = 0; i < 2; i++){
            if (TRAY_LABEL_Y[i][0] <= cy && cy <= TRAY_LABEL_Y[i][1]){
                row_found = i;
                break;
            }
        }
        if (row_found < 0){
            continue;
        }
        const std::pair<int, int> key{row_found, col};
        bool known = false;
        for (std::pair<std::pair<int, int>, QString>& cell : cells){
            if (cell.first == key){
                cell.second += " " + word;
                known = true;
                break;
            }
        }
        if (!known){
            cells.push_back({key, word});
        }
    }
    return cells;
}


std::optional<std::pair<QString, Point>> pick_berry(Host& host, const cv::Mat& img){
    const Cells labels = tray_labels(host, img);
    QStringList texts;
    for (const std::pair<std::pair<int, int>, QString>& cell : labels){
        texts << cell.second;
    }
    std::sort(texts.begin(), texts.end());
    QStringList shown;
    for (const QString& t : texts){
        shown << py_repr(t);
    }
    host.log("berry tray: [" + shown.join(", ") + "]");
    for (const QString& name : host.berry_order()){
        //  BERRY_RULES: what the label must hold, and what it must not.
        QString must;
        QString never;
        if (name == "pinap"){
            must = "PINAP";
            never = "SILVER";
        }else if (name == "razz"){
            must = "RAZZ";
            never = "GOLD";
        }else if (name == "nanab"){
            must = "NANAB";
        }else{
            throw std::runtime_error(py_repr(name).toStdString());
        }
        for (const std::pair<std::pair<int, int>, QString>& cell : labels){
            if (cell.second.contains(must) && !(!never.isEmpty() && cell.second.contains(never))){
                return std::make_pair(name, Point{TRAY_COLS[cell.first.second], TRAY_ICON_Y[cell.first.first]});
            }
        }
    }
    return std::nullopt;
}


double do_encounter(Host& host, State& state, const cv::Mat& first){
    cv::Mat img = first;
    if (state.storage_full && (host.wanted("spin_only_when_full") || host.wanted("daily_cycle")) && Throw::ball_ready(img)){
        host.log("encounter while storage is full - running away");
        host.tap(RUN_BTN.x, RUN_BTN.y);
        return 3;
    }
    if (!Throw::ball_ready(img)){                           //  e.g. "TOTAL XP" with OK: no ball at the bottom
        const std::optional<Point> btn = catch_result_button(host, state, img);
        if (btn.has_value()){                               //  (a new Pokémon: the classifier is unsure about that screen)
            tap_catch_result(host, state, *btn, "classified as catch screen");
            return 1.5;
        }
        host.sleep(0.5);                                    //  the ball may just be flipping over / flying back:
        img = host.quick_screenshot();                      //  look once more before deciding it is over
        if (Throw::ball_ready(img)){
            return 0.2;
        }
        mark_caught(host, state);
        if (tap_button(host, img)){
            return Throw::AFTER_TAP_WAIT;
        }
        const std::optional<Start::Found> green = Start::find_green_button(img);
        if (green.has_value()){
            host.tap(green->x, green->y);
        }
        return Throw::AFTER_TAP_WAIT;
    }
    if (state.enc.start == 0){
        state.enc.start = host.wall();
        host.log("encounter opened");
        host.save_picture("g_vangscherm.png", img);
    }

    if (state.enc.throws >= Throw::MAX_THROWS){
        host.log("too many misses - running away");
        host.tap(RUN_BTN.x, RUN_BTN.y);
        Map::reset_encounter(host, state);
        return 3;
    }

    const QString ball = host.ball();
    if (!ball.isEmpty() && !state.enc.ball_set){
        host.tap(Throw::ENC_BALL_BTN.x, Throw::ENC_BALL_BTN.y);
        host.sleep(1.5);
        const Point at = ball_pos(ball);
        host.tap(at.x, at.y);
        host.sleep(1.5);
        state.enc.ball_set = true;
    }

    if (!host.berry_order().isEmpty() && !state.enc.berry){
        state.enc.berry = true;                             //  only one attempt per Pokémon
        host.tap(Throw::ENC_BERRY_BTN.x, Throw::ENC_BERRY_BTN.y);
        host.sleep(1.0);
        const cv::Mat tray = host.screenshot();
        host.save_picture("g_berries.png", tray);
        const std::optional<std::pair<QString, Point>> choice = pick_berry(host, tray);
        if (choice.has_value()){
            host.tap(choice->second.x, choice->second.y);
            host.sleep(1.0);
            host.tap(Throw::BALL_XY.x, Throw::BALL_XY.y);   //  a tap on the berry feeds it (a throw can miss)
            host.log(choice->first + " berry fed");
            host.sleep(2.5);
        }else{
            host.log("no allowed berry available - continuing without berry");
            host.back();
            host.sleep(1.5);                                //  close the tray of berries
        }
    }

    while (true){                                           //  keep throwing while the ball comes back
        const double t_throw = host.throw_ball(state.throw_hit);
        state.enc.throws++;
        state.enc.t_throw = t_throw;
        host.log(QString("ball %1 thrown").arg(state.enc.throws));
        if (state.throw_hit.value_or(false) && fast_catch_on(host, state) && host.wanted("catch")){
            const std::optional<double> wait = fast_catch_leave(host, state, t_throw);    //  clear hit: skip the catch animation
            if (wait.has_value()){
                return *wait;
            }
        }
        const bool back = wait_for_result(host, state, t_throw);        //  wait for flight + shaking
        if (!back || state.enc.throws >= Throw::MAX_THROWS || !host.wanted("catch")){
            //  OK was just tapped: give the map time to come back (a look right away would see the fading result screen and tap OK a
            //  second time); otherwise carry on at once
            return host.wall() - state.enc.t_tap < 1.0 ? Throw::AFTER_OK_WAIT : 0.2;
        }
    }
}


std::optional<double> fast_catch_leave(Host& host, State& state, double t_throw){
    const std::optional<Point> xy = state.enc_xy;
    const double since = host.wall() - t_throw;
    if (!xy.has_value()){
        return std::nullopt;                                //  not known where the Pokémon is on the map: could not check it afterwards
    }
    if (since > Throw::FAST_BACK_LATEST){
        host.log(QString("fast catch: %1 s after the release - too late to leave, waiting for the result").arg(fixed(since, 1)));
        return std::nullopt;
    }
    if (since < Throw::FAST_BACK_AFTER){
        host.sleep(Throw::FAST_BACK_AFTER - since);
    }
    const double t_back = host.wall();
    host.log(QString("fast catch: clear hit - pressing BACK (%1 s after the release)").arg(fixed(t_back - t_throw, 1)));
    host.back();
    host.sleep(Throw::FAST_LOOK_AFTER);
    cv::Mat img = host.quick_screenshot();
    bool have_img = true;
    if (!host.on_map(img)){
        const Nav::Lines lines = host.ocr_lines(img, 100, 2150, 1.0);
        const QString kind = screen_kind(host, img, lines);
        if (kind == "exit"){                                //  the game was already on the map: BACK asks 'exit?'
            host.log("fast catch: the game asks whether to exit - answering CANCEL");
            cancel_exit(host, lines);
            have_img = false;
        }else{
            host.log(QString("fast catch: after BACK the screen is '%1', not the map - waiting for the result the normal way "
                             "(read: %2; debug/g_fast_back.png)").arg(kind, Nav::reads(lines, 80)));
            host.save_picture("g_fast_back.png", img);
            return std::nullopt;
        }
    }
    state.enc.caught = true;                                //  (so the map does not count it as 'fled'; the check there decides)
    state.fast_pending.xy = xy;
    state.fast_pending.t = host.wall();
    state.fast_pending.t_throw = t_throw;
    state.fast_pending.t_back = t_back;
    state.fast_pending.looks = 0;
    if (have_img){
        state.handoff.img = img;                            //  the map as it is now: the next step uses it
        state.handoff.t = host.wall();
        return 0.0;
    }
    return 1.5;
}


QString screen_kind(Host& host, const cv::Mat& img, const Nav::Lines& lines){
    if (host.on_map(img)){
        return "map";
    }
    QStringList parts;
    std::vector<Nav::Word> words;
    for (const Nav::Line& line : lines){
        parts << line.text;
        for (const Nav::Word& w : line.words){
            words.push_back(w);
        }
    }
    const QString text = parts.join(' ');
    const QStringList split = text.split(QRegularExpression("\\s+"), Qt::SkipEmptyParts);
    if (text.contains("EXIT") && (text.contains("CANCEL") || text.contains("POK"))){
        return "exit";
    }
    if (text.contains("DISCARD") || (split.contains("YES") && split.contains("NO") && text.contains("?"))){
        return "discard";
    }
    static const QRegularExpression count("^\\d{1,4}/\\d{1,4}$");
    for (const Nav::Word& w : words){
        if (w.y < 450 && ((Nav::like(w.text, "ITEMS", 0.8) && std::abs(w.x - 884) < 330) || count.match(w.text).hasMatch())){
            return "bag";                                   //  the title ITEMS or the 'used/capacity' count at the top
        }
    }
    for (const Nav::Word& w : words){
        if (Nav::like(w.text, "ITEMS", 0.8) && 1250 < w.y && w.y < 1700 && w.x > 884){
            for (const Nav::Word& other : words){
                if (Nav::like(other.text, "POKEMON", 0.8) && std::abs(other.y - w.y) < 80 && other.x < 884){
                    return "menu";
                }
            }
        }
    }
    return "other";
}


void finish_catch(Host& host, bool with_beat){
    const double t_end = host.wall() + FINISH_MAX_S;
    bool told = false;
    while (host.wall() < t_end){
        QString name;
        try{
            name = host.screen_class(host.screenshot()).first;
        }catch (const std::exception&){
            return;
        }
        if (name == "mapScreen"){
            return;
        }
        if (name != "encounterScreen" && !told){
            return;                                         //  (not catching: nothing to finish)
        }
        if (!told){
            host.log("daily run: the run time is up - finishing this catch first");
            told = true;
        }
        double wait = 5;
        try{
            wait = host.step();
        }catch (const std::exception& e){
            host.log(QString("error: %1").arg(QString::fromUtf8(e.what())));
            wait = 5;
        }
        if (with_beat){
            host.beat();
        }
        host.sleep(std::min(wait, std::max(0.0, t_end - host.wall())));
    }
}


}
}
}
}
