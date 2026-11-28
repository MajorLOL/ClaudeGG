/*  Claude GG Pokemon GO Layout (is the game drawn the way the bot expects?)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  See ClaudeGG_PokemonGoLayout.h.  What the Python code does is followed line by line, down to the order of the questions that it asks.
 *
 */

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <vector>
#include <opencv2/imgproc.hpp>
#include <QJsonDocument>
#include <QJsonValue>
#include <QRegularExpression>
#include "ClaudeGG_PokemonGoCatch.h"
#include "ClaudeGG_PokemonGoFlow.h"
#include "ClaudeGG_PokemonGoLayout.h"
#include "ClaudeGG_PokemonGoPy.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Layout{

namespace{

//  `value` is true in Python (an empty text, a zero, null and an empty list or object are not).
bool truthy(const QJsonValue& value){
    switch (value.type()){
    case QJsonValue::Bool:      return value.toBool();
    case QJsonValue::Double:    return value.toDouble() != 0.0;
    case QJsonValue::String:    return !value.toString().isEmpty();
    case QJsonValue::Array:     return !value.toArray().isEmpty();
    case QJsonValue::Object:    return !value.toObject().isEmpty();
    default:                    return false;
    }
}

//  load_wm_record(): what the bot wrote down of its change of the display; nothing when there is none or it cannot be used.
std::optional<QJsonObject> load_record(Host& host){
    const std::optional<QString> text = host.record_text();
    if (!text.has_value()){
        return std::nullopt;
    }
    QJsonParseError error;
    const QJsonDocument doc = QJsonDocument::fromJson(text->toUtf8(), &error);
    if (error.error != QJsonParseError::NoError || !doc.isObject() || !truthy(doc.object().value("set"))){
        return std::nullopt;
    }
    return doc.object();
}

struct Size{
    int w = 0;
    int h = 0;
};

//  The size that `wm size` says after the word ("Physical" or "Override"); nothing when it does not say one.
std::optional<Size> wm_size(const QString& text, const QString& word){
    const QRegularExpression pattern(word + " size:\\s*(\\d+)x(\\d+)");
    const QRegularExpressionMatch found = pattern.match(text);
    if (!found.hasMatch()){
        return std::nullopt;
    }
    return Size{found.captured(1).toInt(), found.captured(2).toInt()};
}

QString size_text(int w, int h){
    return QString("%1x%2").arg(w).arg(h);
}

//  The text of an exception for `({e})`.
QString what(const std::exception& e){
    return QString::fromUtf8(e.what());
}

}


void judge_screen(State& state, Host& host){
    const int w = state.screen.w;
    const int h = state.screen.h;
    const double ref = (double)REF_W / (double)REF_H;
    const double rel = std::abs((double)w / (double)h - ref) / ref;
    if (rel <= ASPECT_TOLERANCE){
        state.screen.ok = true;
        state.screen.note.clear();
        return;
    }
    const QString note = QString("screen %1x%2 (width/height %3) has a different shape than the %4x%5 (width/height %6) this bot is written for")
        .arg(w).arg(h).arg(Py::fixed((double)w / (double)h, 2)).arg(REF_W).arg(REF_H).arg(Py::fixed(ref, 2));
    if (host.file_exists("allow")){
        state.screen.ok = true;
        state.screen.note = note + QString(" - running anyway because %1 exists").arg(host.file_path("allow"));
    }else{
        state.screen.ok = false;
        state.screen.note = note + " - the bot tries to let Android draw the game in the right shape (wm size); "
            "until that has worked it does not tap (run device_check.py --layout, see the wiki page 'Phone setup')";
    }
}

void screen_seen(State& state, Host& host, int w, int h){
    if (w != state.screen.w || h != state.screen.h){
        state.screen.w = w;
        state.screen.h = h;
        host.log(QString("screen size is %1x%2").arg(w).arg(h));
        judge_screen(state, host);
    }
}

bool detect_screen(State& state, Host& host, bool wake){
    const std::optional<ScreenRead> read = host.read_screen(wake);
    if (!read.has_value()){
        return false;
    }
    state.screen.w = read->w;
    state.screen.h = read->h;
    state.screen.model = read->model;
    judge_screen(state, host);
    return true;
}

void wait_unsupported(State& state, Host& host){
    if (host.wall() - state.wait_log > UNSUPPORTED_LOG_EVERY){
        state.wait_log = host.wall();
        host.log("not playing: " + state.screen.note);
    }
    host.sleep(UNSUPPORTED_WAIT);
    detect_screen(state, host, true);
}


std::optional<MenuButton> find_menu_button(const cv::Mat& img){
    if (img.empty() || img.type() != CV_8UC3){
        return std::nullopt;
    }
    const int H = img.rows;
    const int W = img.cols;
    const int y0 = (int)(0.78 * H);
    const int x0 = (int)(0.25 * W);
    const int x1 = (int)(0.75 * W);
    if (y0 >= H || x1 <= x0){
        return std::nullopt;
    }
    //  red = (r > 35) & (r > 2.5 * max(g, b, 1)) in the part of the picture below and between these
    cv::Mat red(H - y0, x1 - x0, CV_8UC1);
    for (int y = 0; y < red.rows; y++){
        const cv::Vec3b* row = img.ptr<cv::Vec3b>(y0 + y);
        uchar* out = red.ptr<uchar>(y);
        for (int x = 0; x < red.cols; x++){
            const int b = row[x0 + x][0];
            const int g = row[x0 + x][1];
            const int r = row[x0 + x][2];
            out[x] = (r > 35 && (double)r > 2.5 * (double)std::max(std::max(g, b), 1)) ? 1 : 0;
        }
    }
    cv::Mat labels, stats, centroids;
    const int n = cv::connectedComponentsWithStats(red, labels, stats, centroids, 8);
    std::optional<MenuButton> best;
    for (int i = 1; i < n; i++){
        const int x = stats.at<int>(i, cv::CC_STAT_LEFT);
        const int y = stats.at<int>(i, cv::CC_STAT_TOP);
        const int w = stats.at<int>(i, cv::CC_STAT_WIDTH);
        const int h = stats.at<int>(i, cv::CC_STAT_HEIGHT);
        const int a = stats.at<int>(i, cv::CC_STAT_AREA);
        if (!(0.05 * W <= w && w <= 0.2 * W && 0.3 * w <= h && h <= 0.7 * w && a > 0.3 * w * h)){
            continue;
        }
        const double cx = x0 + x + w / 2.0;
        const int bot = y0 + y + h;
        const int wy = (int)(bot + 0.25 * w);
        if (wy >= H){
            continue;
        }
        const cv::Vec3b& below = img.at<cv::Vec3b>(wy, (int)cx);       //  the white half below the red one
        const int px_r = below[2];
        const int px_g = below[1];
        const int px_b = below[0];
        const int r_up = img.at<cv::Vec3b>((int)(bot - 0.2 * w), (int)cx)[2];     //  (the game is dimmed behind a dialog: compare with the red half)
        if (std::max({px_r, px_g, px_b}) - std::min({px_r, px_g, px_b}) < 25 && px_r > 0.8 * r_up){
            const MenuButton candidate{cx, (double)bot, (double)w};
            if (!best.has_value() || std::abs(cx - W / 2.0) < std::abs(best->x - W / 2.0)){
                best = candidate;
            }
        }
    }
    return best;
}

Check menu_button_check(const std::optional<MenuButton>& found){
    if (!found.has_value()){
        return {std::nullopt, QString::fromUtf8("Pok\xC3\xA9 Ball menu button not found")};
    }
    const double dx = found->x - MENU_REF_X;
    const double dy = found->y - MENU_REF_Y;
    const double dd = found->w - MENU_REF_W;
    const QString where = QString("menu button at (%1, %2), %3 px wide (expected (%4, %5), %6 px)")
        .arg(Py::fixed(found->x, 0), Py::fixed(found->y, 0), Py::fixed(found->w, 0)).arg(MENU_REF_X).arg(MENU_REF_Y).arg(MENU_REF_W);
    if (std::abs(dx) <= MENU_TOL_X && std::abs(dy) <= MENU_TOL_Y && std::abs(dd) <= MENU_TOL_W){
        return {true, where};
    }
    return {false, where};
}


Plan display_plan(State& state, Host& host){
    Plan plan;
    const int w = state.screen.w;
    const int h = state.screen.h;
    QString text;
    try{
        text = host.wm_size_text();
    }catch (const std::runtime_error& e){
        plan.why = QString("'wm size' does not work on this phone (%1)").arg(what(e));
        return plan;
    }
    const std::optional<Size> phys = wm_size(text, "Physical");
    const std::optional<Size> over = wm_size(text, "Override");
    if (!phys.has_value()){
        plan.why = "'wm size' does not give a physical size";
        return plan;
    }
    if (over.has_value()){
        const std::optional<QJsonObject> mine = load_record(host);
        if (mine.has_value() && mine->value("set") == QJsonValue(size_text(over->w, over->h))){
            plan.why = QString("the display size is already set by this bot (%1x%2)").arg(over->w).arg(over->h);
            return plan;
        }
        plan.why = QString("the display size was changed by something else (%1x%2, physical %3x%4) - not touching it (reset it with: adb shell wm size reset)")
            .arg(over->w).arg(over->h).arg(phys->w).arg(phys->h);
        return plan;
    }
    bool swapped = false;
    if (phys->w == w && phys->h == h){
        swapped = false;
    }else if (phys->h == w && phys->w == h){
        swapped = true;                                 //  the game is turned the other way than the phone's natural position
    }else{
        plan.why = QString("the screenshot is %1x%2 but the display is %3x%4: cannot tell which display that is").arg(w).arg(h).arg(phys->w).arg(phys->h);
        return plan;
    }
    const double scale = std::min((double)w / REF_W, (double)h / REF_H);
    const int tw = (int)std::nearbyint(REF_W * scale) / 2 * 2;
    const int th = (int)std::nearbyint(REF_H * scale) / 2 * 2;
    if (tw < MIN_CANVAS_W || th < MIN_CANVAS_H){
        plan.why = QString("the screen is too small to draw the game in the right shape (%1x%2)").arg(tw).arg(th);
        return plan;
    }
    if (std::abs(tw - w) <= 2 && std::abs(th - h) <= 2){
        plan.why = "the screen already has the shape of the canvas";
        return plan;
    }
    plan.cmd = swapped ? size_text(th, tw) : size_text(tw, th);
    plan.w = tw;
    plan.h = th;
    return plan;
}

Adapted adapt_display(State& state, Host& host){
    Adapted result;
    if (host.file_exists("no_adapt")){
        result.text = QString("not changing the display size (%1 exists)").arg(host.file_path("no_adapt"));
        return result;
    }
    const Plan plan = display_plan(state, host);
    if (plan.cmd.isEmpty()){
        result.text = plan.why;
        return result;
    }
    QJsonObject record;                                 //  first write down what is going to be changed
    record["set"] = plan.cmd;
    record["time"] = host.wall();
    record["model"] = state.screen.model;
    record["was"] = size_text(state.screen.w, state.screen.h);
    const QString write_error = host.record_write(record);
    if (!write_error.isEmpty()){
        result.text = QString("cannot write %1 (%2) - not changing the display size without a way back").arg(host.file_path("record"), write_error);
        return result;
    }
    try{
        host.wm_size_set(plan.cmd);
    }catch (const std::runtime_error& e){
        host.record_forget();
        result.text = QString("wm size %1 was refused (%2)").arg(plan.cmd, what(e));
        return result;
    }
    host.log(QString("display size set to %1 so the game is drawn in the right shape (the phone shows black bars; "
                     "this is put back when the bot stops, or run: adb shell wm size reset)").arg(plan.cmd));
    host.sleep(3);                                      //  the game redraws itself
    detect_screen(state, host, false);
    const int low = std::min(state.screen.w, state.screen.h);
    const int high = std::max(state.screen.w, state.screen.h);
    if (low != std::min(plan.w, plan.h) || high != std::max(plan.w, plan.h)){
        restore_display(state, host);
        result.text = QString("after wm size %1 the screenshots are %2x%3, not %4x%5").arg(plan.cmd).arg(state.screen.w).arg(state.screen.h).arg(plan.w).arg(plan.h);
        return result;
    }
    result.changed = true;
    result.text = QString("display now %1x%2").arg(plan.w).arg(plan.h);
    return result;
}

bool restore_display(State& state, Host& host){
    if (!load_record(host).has_value()){
        return false;
    }
    try{
        host.wm_size_reset();
    }catch (const std::runtime_error& e){
        host.log(QString("could not put the display size back (%1) - run: adb shell wm size reset").arg(what(e)));
        return false;
    }
    host.record_forget();
    host.log("display size put back (wm size reset)");
    try{
        detect_screen(state, host, false);              //  (also updates what the web interface reads)
    }catch (const std::runtime_error&){
    }
    return true;
}


void layout_init(State& state, Host& host){
    const std::optional<QJsonObject> record = load_record(host);
    if (!record.has_value()){
        return;
    }
    std::optional<Size> over;
    try{
        over = wm_size(host.wm_size_text(), "Override");
    }catch (const std::runtime_error&){
        over = std::nullopt;
    }
    if (over.has_value() && record->value("set") == QJsonValue(size_text(over->w, over->h))){
        host.log(QString("layout: the display size %1 set by an earlier run is still active - checking it").arg(record->value("set").toString()));
        state.state = "adapting";
        state.since = host.wall();
    }else{
        host.record_forget();
    }
}

bool layout_adapt(State& state, Host& host, const QString& why){
    if (host.wall() < state.next_try){
        return false;
    }
    state.next_try = host.wall() + LAYOUT_RETRY;
    host.log(QString("layout: %1 - trying to let Android draw the game in the right shape").arg(why));
    const Adapted adapted = adapt_display(state, host);
    if (!adapted.changed){
        host.log(QString("layout: not possible: %1").arg(adapted.text));
        return false;
    }
    state.state = "adapting";
    state.looks = 0;
    state.since = host.wall();
    host.log(QString("layout: %1 - checking the game again on the map").arg(adapted.text));
    host.reset_same_screen();
    return true;
}

void layout_undo(State& state, Host& host, const QString& why){
    host.log(QString("layout: %1 - putting the display size back").arg(why));
    restore_display(state, host);
    state.state = "unverified";
    state.looks = 0;
    state.next_try = host.wall() + LAYOUT_RETRY;
}

bool layout_tap_test(State&, Host& host, const cv::Mat& before){
    host.tap(Bag::MENU_BTN.x, Bag::MENU_BTN.y);
    cv::Mat shot = Flow::settled(host, 2.0);
    Nav::Lines lines = host.ocr_lines(shot, 100, 2150);
    QString kind = Catch::screen_kind(host, shot, lines);
    host.log(QString("layout check: after a tap on the menu button the screen is '%1'").arg(kind));
    const bool opened = kind == "menu" || kind == "bag" || (kind == "other" && !host.on_map(shot) && Flow::screen_changed(before, shot));
    for (int i = 0; i < 4; i++){                        //  back to the map, whatever it is
        if (host.on_map(shot)){
            break;
        }
        if (kind == "exit"){
            Bag::cancel_exit(host, lines);
        }else{
            host.back();
        }
        shot = Flow::settled(host, 1.5);
        lines = host.ocr_lines(shot, 100, 2150);
        kind = Catch::screen_kind(host, shot, lines);
    }
    return opened;
}

void layout_verify(State& state, Host& host, const cv::Mat& img){
    const QString before = state.state;
    const Check check = menu_button_check(find_menu_button(img));
    if (check.ok.has_value() && *check.ok){
        if (before == "adapting"){
            if (layout_tap_test(state, host, img)){
                state.state = "adapted";
                host.log(QString("layout check: %1 - confirmed; the menu opens when tapped, the game is playable on %2x%3")
                    .arg(check.text).arg(state.screen.w).arg(state.screen.h));
            }else{
                layout_undo(state, host, "tapping the menu button did not open the menu");
            }
        }else{
            state.state = "confirmed";
            host.log(QString("layout check: %1 - the game is drawn as expected").arg(check.text));
        }
        return;
    }
    state.looks++;
    if (!check.ok.has_value() && state.looks < LAYOUT_LOOKS){
        return;                                         //  something may cover the button: look at a few more pictures
    }
    if (before == "adapting"){
        layout_undo(state, host, check.ok.has_value() ? check.text : QString("menu button not found on %1 map pictures").arg(state.looks));
        return;
    }
    if (check.ok.has_value() && !*check.ok && layout_adapt(state, host, check.text)){
        return;
    }
    state.state = "unverified";
    if (check.ok.has_value() && !*check.ok){
        host.log(QString("layout check: %1 - the game is not drawn the way this bot expects, taps may land in the wrong places "
                         "(see the wiki page 'Phone setup')").arg(check.text));
    }else{
        host.log(QString("layout check: menu button not found on %1 map pictures - carrying on without that check").arg(state.looks));
    }
}

void layout_watch(State& state, Host& host){
    if (state.state == "adapting" && host.wall() - state.since > LAYOUT_MAP_WAIT){
        layout_undo(state, host, QString("the map was not seen within %1 minutes of the display change").arg((int)LAYOUT_MAP_WAIT / 60));
    }
}


}
}
}
}
