/*  Claude GG Pokemon GO Bag (the item bag of the Pokémon GO bot: clean it up when it is full, and what to do when storage and bag are both full)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  See ClaudeGG_PokemonGoBag.h.  Every number, every wait and every line of the log is that of Mobile/gamebot.py (and Mobile/bag_rules.py); the
 *  check holds it to the Python code's stories.
 *
 */

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <set>
#include <stdexcept>
#include <opencv2/imgproc.hpp>
#include <QJsonObject>
#include "ClaudeGG_PokemonGoBag.h"
#include "ClaudeGG_PokemonGoFlow.h"
#include "ClaudeGG_PokemonGoPy.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Bag{

using Py::py_split;
using Py::py_strip;
using Py::py_title;

namespace{

//  The items that the bag can keep a number of: the name as the game shows it, whether it is cleaned up by default and how many are kept then
//  (bag_rules.ITEMS).
struct Item{
    const char* name;
    bool on;
    int keep;
};
const Item ITEMS[] = {
    {"Potion", true, 0}, {"Super Potion", true, 0}, {"Hyper Potion", true, 0}, {"Max Potion", true, 30},
    {"Revive", false, 0}, {"Max Revive", true, 30},
    {"Poké Ball", true, 400}, {"Great Ball", true, 100}, {"Ultra Ball", false, 0},
    {"Razz Berry", true, 30}, {"Nanab Berry", true, 30}, {"Pinap Berry", true, 30}, {"Golden Razz Berry", true, 30}, {"Silver Pinap Berry", true, 30},
};

//  The words that mark a screen as a page of the bag (BAG_WORDS).
const char* const BAG_WORDS[] = {"POTION", "REVIVE", "BALL", "BERR", "LUCKY", "INCENSE", "RAZZ", "PINAP", "NANAB", "EGG", "LURE", "ADVENTURE"};

std::vector<Nav::Word> words_of(const Nav::Lines& lines){
    std::vector<Nav::Word> out;
    for (const Nav::Line& line : lines){
        for (const Nav::Word& w : line.words){
            out.push_back(w);
        }
    }
    return out;
}

//  Python's a // b for a whole number b > 0.
int floor_div(int a, int b){
    int q = a / b;
    if ((a % b != 0) && (a < 0)){
        q--;
    }
    return q;
}

//  The number that the text of a word is, when it is one ('x487', 'K5', '30', with the digits of any script; re.fullmatch(r"[XxKk×]?(\d{1,4})", w.strip())).
std::optional<int> count_of(const QString& word){
    const QString s = py_strip(word);
    qsizetype from = 0;
    if (!s.isEmpty()){
        const ushort first = s.at(0).unicode();
        if (first == 'X' || first == 'x' || first == 'K' || first == 'k' || first == 0xD7){
            from = 1;
        }
    }
    const qsizetype digits = s.size() - from;
    if (digits < 1 || digits > 4){
        return std::nullopt;
    }
    int value = 0;
    for (qsizetype i = from; i < s.size(); i++){
        if (s.at(i).category() != QChar::Number_DecimalDigit){
            return std::nullopt;
        }
        value = value * 10 + s.at(i).digitValue();
    }
    return value;
}

//  The digits of a text as the number that int() of Python would make of them (more than 18: one huge number), and the way Python writes it.
void number_of(const QString& text, std::optional<long long>& value, QString& written){
    QString digits;
    for (const QChar c : text){
        if (c.category() == QChar::Number_DecimalDigit){
            digits += QChar((ushort)('0' + c.digitValue()));
        }
    }
    if (digits.isEmpty()){
        value.reset();
        written = "None";
        return;
    }
    qsizetype from = 0;
    while (from < digits.size() - 1 && digits.at(from) == '0'){
        from++;
    }
    written = digits.mid(from);
    value = written.size() > 18 ? 1000000000000000000LL : written.toLongLong();
}

//  The picture that a way of looking at the page makes of it (_bag_image()): 0 as it is, 1 inverted, 2 the darkest channel (white text on colour stays
//  white), 3 local contrast.
cv::Mat bag_image(const cv::Mat& img, int variant){
    if (variant == 1){
        return cv::Scalar::all(255) - img;
    }
    if (variant == 2){
        std::vector<cv::Mat> channels;
        cv::split(img, channels);
        const cv::Mat darkest = cv::min(cv::min(channels[0], channels[1]), channels[2]);
        cv::Mat out;
        cv::cvtColor(darkest, out, cv::COLOR_GRAY2BGR);
        return out;
    }
    if (variant == 3){
        cv::Mat gray, local, out;
        cv::cvtColor(img, gray, cv::COLOR_BGR2GRAY);
        cv::createCLAHE(3.0, cv::Size(8, 8))->apply(gray, local);
        cv::cvtColor(local, out, cv::COLOR_GRAY2BGR);
        return out;
    }
    return img;
}

}


//  ---- what the bag keeps

std::vector<std::pair<QString, int>> rules(const QJsonValue& saved){
    std::vector<std::optional<int>> keep;
    for (const Item& item : ITEMS){
        keep.push_back(item.on ? std::optional<int>(item.keep) : std::nullopt);
    }
    if (saved.isObject()){                                  //  (anything else: the standard numbers)
        const QJsonObject chosen = saved.toObject();
        for (size_t i = 0; i < keep.size(); i++){
            const QString name = QString::fromUtf8(ITEMS[i].name);
            if (!chosen.contains(name)){
                continue;
            }
            const QJsonValue v = chosen.value(name);
            if (v.isNull() || (v.isString() && py_strip(v.toString()).isEmpty())){
                keep[i].reset();
                continue;
            }
            double number = 0;
            if (v.isBool()){
                number = v.toBool() ? 1 : 0;
            }else if (v.isDouble()){
                number = v.toDouble();
            }else if (v.isString()){
                if (!Py::py_parse_float(v.toString(), number)){
                    continue;                               //  (ValueError: left as it was)
                }
            }else{
                continue;                                   //  (TypeError: a list or an object)
            }
            if (std::isnan(number)){
                continue;                                   //  (int() of NaN: ValueError)
            }
            if (std::isinf(number)){
                throw std::runtime_error("cannot convert float infinity to integer");
            }
            const double whole = std::trunc(number);
            keep[i] = whole <= 0 ? 0 : (whole >= MAX_KEEP ? MAX_KEEP : (int)whole);
        }
    }
    std::vector<std::pair<QString, int>> out;
    for (size_t i = 0; i < keep.size(); i++){
        if (keep[i].has_value()){
            out.push_back({QString::fromUtf8(ITEMS[i].name), *keep[i]});
        }
    }
    return out;
}

QString plain_name(const QString& text){
    QString letters;
    for (const QChar c : text.normalized(QString::NormalizationForm_KD)){
        const ushort u = c.unicode();
        if (u >= 128){
            continue;                                       //  (encode("ascii", "ignore"))
        }
        if (u >= 'a' && u <= 'z'){
            letters += QChar((ushort)(u - 'a' + 'A'));
        }else if ((u >= 'A' && u <= 'Z') || u == ' '){
            letters += c;
        }else{
            letters += ' ';
        }
    }
    return py_split(letters).join(' ');
}

std::vector<Rule> plan(Host& host){
    std::vector<Rule> out;
    for (const std::pair<QString, int>& r : rules(host.bag_keep_saved())){
        out.push_back(Rule{plain_name(r.first), r.second});
    }
    return out;
}

std::optional<int> keep_for(const QString& name, const std::vector<Rule>& plan){
    const QString n = plain_name(name);
    const QStringList words = py_split(n);
    if (n.isEmpty() || words.size() > 4){
        return std::nullopt;
    }
    for (const Rule& rule : plan){
        if (rule.name.endsWith('*')){
            if (words.contains(rule.name.left(rule.name.size() - 1))){
                return rule.keep;
            }
        }else if (n == rule.name || (n.size() >= 6 && Nav::similarity(n, rule.name) >= 0.9 && words.size() == py_split(rule.name).size())){
            return rule.keep;
        }
    }
    return std::nullopt;
}

std::vector<Row> rows(const Nav::Lines& lines, int h, const std::vector<Rule>& plan){
    std::vector<Row> out;
    const std::vector<Nav::Word> words = words_of(lines);
    for (const Nav::Line& line : lines){
        const std::optional<int> keep = keep_for(line.text, plan);
        if (!keep.has_value()){
            continue;
        }
        std::optional<int> count;
        for (const Nav::Word& w : words){
            const std::optional<int> number = count_of(w.text);
            const int dy = w.y - line.y;
            if (number.has_value() && w.x < line.x && COUNT_DY_FROM * h < dy && dy < COUNT_DY_TO * h){
                count = number;
                break;
            }
        }
        out.push_back(Row{plain_name(line.text), *keep, line.x, line.y, count});
    }
    return out;
}


//  ---- the question 'Discard <item>?'

std::optional<Dialog> discard_dialog(Host& host, const cv::Mat& img){
    const Nav::Lines lines = host.ocr_lines(img, 100, 2150, 0.6);
    const Nav::Line* title = nullptr;
    for (const Nav::Line& line : lines){
        if (line.text.toUpper().contains("DISCARD")){
            title = &line;
            break;
        }
    }
    if (title == nullptr){
        return std::nullopt;
    }
    const std::vector<Nav::Word> words = words_of(lines);
    const auto find = [&](const char* what) -> std::optional<Spot>{
        for (const Nav::Word& w : words){
            if (w.text.toUpper() == what && w.y > title->y){
                return Spot(w.x, w.y);
            }
        }
        return std::nullopt;
    };
    const std::optional<Spot> yes = find("YES");
    const std::optional<Spot> no = find("NO");
    if (!yes.has_value() || !no.has_value()){
        return std::nullopt;
    }
    const int h = img.rows;
    const int w = img.cols;
    const int ny = (int)(title->y + DISCARD_NUMBER_AT * (yes->second - title->y));
    const int reach = (int)(0.045 * h);
    const int top = std::max(0, ny - reach);
    const int bottom = std::min(h, ny + reach);
    const int left = (int)(0.38 * w);
    const int right = (int)(0.62 * w);
    if (bottom <= top || right <= left){
        throw std::runtime_error("the box of the number is empty");
    }
    cv::Mat gray, bw;
    cv::cvtColor(img(cv::Range(top, bottom), cv::Range(left, right)), gray, cv::COLOR_BGR2GRAY);
    cv::threshold(gray, bw, 0, 255, cv::THRESH_BINARY | cv::THRESH_OTSU);
    QString read = host.ocr_line(bw, 1);
    read.replace("O", "0").replace("o", "0");
    Dialog d;
    d.title = title->text;
    number_of(read, d.n, d.n_text);
    d.yes = *yes;
    d.no = *no;
    d.number_y = ny;
    return d;
}

std::pair<int, int> canvas(const cv::Mat& img, double x, double y){
    return {(int)(x * CANVAS_W / img.cols), (int)(y * CANVAS_H / img.rows)};
}

std::pair<cv::Mat, std::optional<Dialog>> set_discard_number(Host& host, int target, int tries){
    cv::Mat img = host.screenshot();
    std::optional<Dialog> d = discard_dialog(host, img);
    for (int i = 0; i < tries; i++){
        if (!d.has_value() || !d->n.has_value()){
            return {img, d};
        }
        const long long n = *d->n;
        if (n == target){
            return {img, d};
        }
        const double x = target > n ? DISCARD_PLUS_X : DISCARD_MINUS_X;
        const long long step = n > target ? n - target : target - n;
        const std::pair<int, int> at = canvas(img, x * img.cols, d->number_y);
        const int taps = (int)std::min<long long>(step, MAX_TAPS_AT_ONCE);
        host.swipes(std::vector<Loop::Stroke>(taps, Loop::Stroke{at.first, at.second, at.first, at.second, 70}));      //  (one adb command: up to 40 taps in a row)
        host.sleep(0.8);
        img = host.screenshot();
        d = discard_dialog(host, img);
    }
    return {img, d};
}


//  ---- looking at the bag

bool bag_like(const Nav::Lines& lines){
    for (const Nav::Word& w : words_of(lines)){
        for (const char* b : BAG_WORDS){
            if (w.text.contains(QString(b))){
                return true;
            }
        }
    }
    return false;
}

std::optional<Spot> incense_tile(const Nav::Lines& lines){
    const std::vector<Nav::Word> words = words_of(lines);
    std::vector<Spot> daily, adventure;
    for (const Nav::Word& w : words){
        if (Nav::like(w.text, "DAILY")){
            daily.push_back(Spot(w.x, w.y));
        }
    }
    for (const Nav::Word& w : words){
        if (Nav::like(w.text, "ADVENTURE")){
            adventure.push_back(Spot(w.x, w.y));
        }
    }
    for (const Spot& d : daily){
        for (const Spot& a : adventure){
            if (std::abs(a.first - d.first) < 450 && std::abs(a.second - d.second) < 130){
                return Spot(floor_div(d.first + a.first, 2), floor_div(d.second + a.second, 2));
            }
        }
    }
    return std::nullopt;
}

Nav::Lines bag_ocr(Host& host, State& state, const cv::Mat& img, int y0){
    std::vector<int> order{state.ocr_variant};
    for (int v = 0; v < 4; v++){
        if (v != state.ocr_variant){
            order.push_back(v);
        }
    }
    std::optional<Nav::Lines> first;
    for (const int v : order){
        const Nav::Lines lines = host.ocr_lines(bag_image(img, v), y0, 2150, OCR_SCALE);
        if (!first.has_value()){
            first = lines;
        }
        if (bag_like(lines) || incense_tile(lines).has_value()){
            state.ocr_variant = v;
            return lines;
        }
    }
    return *first;
}

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

void cancel_discard(Host& host, const Nav::Lines& lines){
    for (const Nav::Line& line : lines){
        for (const Nav::Word& w : line.words){
            if (w.text == "NO" && w.y > 1000){
                host.tap(w.x, w.y);
                return;
            }
        }
    }
    host.back();
}

void leave_question(Host& host, const QString& kind, const Nav::Lines& lines){
    if (kind == "exit"){
        cancel_exit(host, lines);
    }else if (kind == "discard"){
        host.log("daily incense: a 'Discard ...?' question came up - answering NO");
        cancel_discard(host, lines);
    }
}

std::optional<std::pair<cv::Mat, Nav::Lines>> open_bag(Host& host){
    host.tap(MENU_BTN.x, MENU_BTN.y);
    std::optional<std::vector<Spot>> spots;
    int tapped = 0;
    int others = 0;
    for (int step = 0; step < 9; step++){
        const cv::Mat shot = Flow::settled(host, (step == 0 || tapped) ? 2.5 : 1.5);
        const Nav::Lines lines = host.ocr_lines(shot, 100, 2150);
        const QString kind = Catch::screen_kind(host, shot, lines);
        host.save_picture(QString("g_incense_s%1.png").arg(step), shot);
        host.log(QString("daily incense: step %1: screen is %2 (%3)").arg(step).arg(kind, Nav::reads(lines, 90)));
        if (kind == "bag"){
            return std::make_pair(shot, lines);
        }
        if (kind == "exit" || kind == "discard"){
            leave_question(host, kind, lines);
            if (kind == "discard"){
                break;
            }
        }else if (kind == "map"){
            host.tap(MENU_BTN.x, MENU_BTN.y);                   //  the menu is closed (again): open it
        }else if (kind == "other"){
            others++;                                           //  something in the way / still loading
            if (others > 2){
                break;
            }
            if (!tapped){
                host.back();
            }
        }else{                                                  //  menu
            if (!spots.has_value()){
                host.save_picture("g_incense_menu.png", shot);
                std::vector<Spot> items;
                for (const Nav::Word& w : words_of(lines)){
                    if (Nav::like(w.text, "ITEMS", 0.75) && w.y > 1250){
                        items.push_back(Spot(w.x, w.y));
                    }
                }
                std::stable_sort(items.begin(), items.end(), [](const Spot& a, const Spot& b){ return a.first > b.first; });
                if (items.empty()){
                    host.log("daily incense: the word ITEMS is not in the main menu (see debug/g_incense_menu.png)");
                    break;
                }
                const int x = items[0].first;
                const int y = items[0].second;
                const double k = shot.rows / 2208.0;
                spots = std::vector<Spot>{Spot(x, y + (int)(ITEMS_ICON_DY * k)), Spot(x, y), Spot(x, y + (int)((ITEMS_ICON_DY - 45) * k))};
            }
            if (spots->empty()){
                host.log("daily incense: tapped every spot of the ITEMS button and the bag did not open");
                break;
            }
            const Spot at = spots->front();
            spots->erase(spots->begin());
            host.log(QString("daily incense: tapping ITEMS at (%1, %2)").arg(at.first).arg(at.second));
            host.tap(at.first, at.second);
            tapped++;
        }
    }
    return std::nullopt;
}

void bag_to_map(Host& host){
    for (int i = 0; i < 6; i++){
        const cv::Mat img = host.screenshot();
        if (host.on_map(img)){
            return;
        }
        const Nav::Lines lines = host.ocr_lines(img, 100, 2150, 0.6);
        const QString kind = Catch::screen_kind(host, img, lines);
        if (kind == "exit" || kind == "discard"){
            leave_question(host, kind, lines);                  //  never confirm either of them
        }else if (kind == "menu" || kind == "bag"){
            host.tap(MENU_BTN.x, MENU_BTN.y);                   //  the round X button at the bottom closes both
        }else{
            host.back();
        }
        host.sleep(2);
    }
}


//  ---- the steps

int clean_bag(Host& host, State& state){
    if (!open_bag(host).has_value()){
        host.log("bag clean-up: the bag did not open");
        bag_to_map(host);
        return 0;
    }
    int gone = 0;
    std::set<QString> done;
    cv::Mat prev;
    int still = 0;
    const std::vector<Rule> rules_now = plan(host);
    QStringList wanted;
    for (const Rule& r : rules_now){
        wanted << QString("%1 down to %2").arg(py_title(r.name), r.keep.has_value() ? QString::number(*r.keep) : QString("None"));
    }
    host.log("bag clean-up: the bag is full - discarding: " + wanted.join(", "));
    int pages = 0;
    int acts = 0;
    while (pages < CLEAN_PAGES && acts < 3 * (int)rules_now.size() + 10){
        const cv::Mat img = host.screenshot();
        const Nav::Lines lines = bag_ocr(host, state, img);
        const int h = img.rows;
        const int w = img.cols;
        if (host.on_map(img)){
            host.log("bag clean-up: the bag closed - stopping");
            break;
        }
        std::vector<Row> todo;
        for (const Row& r : rows(lines, h, rules_now)){
            if (done.count(r.name) == 0 && 0.12 * h < r.y && r.y < 0.86 * h){
                todo.push_back(r);
            }
        }
        bool acted = false;
        for (const Row& r : todo){
            done.insert(r.name);
            const QString shown = py_title(r.name);
            if (!r.count.has_value()){
                host.log(QString("bag clean-up: %1: its number was not read - left as it is").arg(shown));
                continue;
            }
            const int count = *r.count;
            if (count <= r.keep){
                host.log(QString("bag clean-up: %1: %2 - kept").arg(shown).arg(count));
                continue;
            }
            const int want = count - r.keep;
            host.log(QString("bag clean-up: %1: %2, keeping %3 - discarding %4").arg(shown).arg(count).arg(r.keep).arg(want));
            const std::pair<int, int> trash = canvas(img, TRASH_X * w, r.y + TRASH_DY * h);
            host.tap(trash.first, trash.second);
            host.sleep(1.5);
            const std::pair<cv::Mat, std::optional<Dialog>> asked = set_discard_number(host, want);
            const cv::Mat& shot = asked.first;
            host.save_picture(QString("g_bag_discard_%1.png").arg(done.size()), shot);
            if (!asked.second.has_value()){
                host.log(QString("bag clean-up: the question to discard %1 did not come up").arg(shown));
                acted = true;
                break;
            }
            const Dialog& d = *asked.second;
            QString named = plain_name(QString(d.title).replace("?", ""));
            named.replace("DISCARD", "");
            if (py_strip(named) != r.name || !d.n.has_value() || *d.n != want){
                host.log(QString("bag clean-up: the question reads '%1' with %2 - not %3 %4: answering NO").arg(d.title, d.n_text, shown).arg(want));
                const std::pair<int, int> no = canvas(shot, d.no.first, d.no.second);
                host.tap(no.first, no.second);
            }else{
                const std::pair<int, int> yes = canvas(shot, d.yes.first, d.yes.second);
                host.tap(yes.first, yes.second);
                gone += want;
                host.log(QString("bag clean-up: discarded %1 %2").arg(want).arg(shown));
            }
            host.sleep(2.0);
            acted = true;
            break;                                              //  (the list changed: read this page again)
        }
        if (acted){
            acts++;
            continue;
        }
        pages++;
        if (!prev.empty() && !Flow::screen_changed(img, prev, 0.003)){
            still++;
            if (still >= 2){
                break;                                          //  the end of the list
            }
        }else{
            still = 0;
        }
        prev = img;
        host.swipe(SWIPE_PAGE[0], SWIPE_PAGE[1], SWIPE_PAGE[2], SWIPE_PAGE[3], SWIPE_PAGE[4]);
        host.sleep(1.2);
    }
    host.log(QString("bag clean-up: done - %1 items discarded").arg(gone));
    bag_to_map(host);
    return gone;
}

void check_menu_full(Host& host, Map::State& state){
    host.tap(MENU_BTN.x, MENU_BTN.y);
    host.sleep(2.5);
    const cv::Mat img = host.screenshot();
    const Nav::Lines lines = host.ocr_lines(img, 1300, 2100);
    const std::vector<Nav::Word> words = words_of(lines);
    bool menu = false;
    for (const Nav::Word& w : words){
        if (w.text.startsWith("ITEMS") || w.text.startsWith("POK")){
            menu = true;
            break;
        }
    }
    if (menu){
        bool storage = false;
        bool bag = false;
        for (const Nav::Word& w : words){
            if (w.text.contains("FULL")){
                storage = storage || w.x < 884;
                bag = bag || w.x >= 884;
            }
        }
        state.storage_full = storage || state.storage_full;
        state.bag_is_full = bag;
        host.log(QString("menu check: Pokémon storage %1, bag %2").arg(QString(state.storage_full ? "FULL" : "ok"), QString(state.bag_is_full ? "FULL" : "ok")));
        host.tap(MENU_BTN.x, MENU_BTN.y);                       //  the X button closes the menu (BACK on the map would ask "exit Pokémon GO?")
        host.sleep(2);
    }else{
        host.save_picture("g_menu.png", img);
        host.log("menu check: main menu not recognised");
    }
}

void close_game_completely(Host& host){
    try{
        host.shell({"shell", "am", "force-stop", host.package()});
        host.sleep(1);
        host.shell({"shell", "input", "keyevent", "KEYCODE_APP_SWITCH"});         //  recent apps
        host.sleep(2.5);
        const cv::Mat img = host.screenshot();
        std::optional<Spot> target;
        for (const Nav::Line& line : host.ocr_lines(img, 1100, 2208)){
            if (line.text.contains("SLUITEN") || line.text.contains("CLOSE ALL")){
                if (line.words.empty()){
                    throw std::runtime_error("integer division or modulo by zero");
                }
                int sum = 0;
                for (const Nav::Word& w : line.words){
                    sum += w.x;
                }
                target = Spot(floor_div(sum, (int)line.words.size()), line.y);
                break;
            }
        }
        host.tap(target.has_value() ? target->first : CLOSE_ALL_BTN.x, target.has_value() ? target->second : CLOSE_ALL_BTN.y);
        host.sleep(2);
        host.shell({"shell", "input", "keyevent", "KEYCODE_HOME"});
        host.shell({"shell", "am", "force-stop", host.package()});
        host.log("Pokémon GO closed (also removed from recent apps)");
    }catch (const Flow::Interrupted&){
        throw;
    }catch (const std::exception& e){
        host.log(QString("could not close Pokémon GO completely: %1").arg(QString::fromUtf8(e.what())));
    }
}

void check_all_full(Host& host, Map::State& state){
    const bool daily = host.wanted("daily_cycle");
    if (!(state.storage_full && state.bag_is_full && (daily || host.wanted("close_when_full")))){
        return;
    }
    host.log("POKÉMON STORAGE AND BAG FULL - closing Pokémon GO and stopping the bot");
    close_game_completely(host);
    if (daily){                                                 //  daily run: next app / wait for tomorrow
        host.run_done();
        return;
    }
    while (true){                                               //  wait until the game is opened again
        host.sleep(30);
        try{
            if (!py_strip(host.shell({"shell", "pidof", host.package()})).isEmpty()){
                break;
            }
        }catch (const Flow::Interrupted&){
            throw;
        }catch (const std::exception&){                         //  pidof finds nothing -> error: still closed
        }
    }
    state.storage_full = false;
    state.bag_is_full = false;
    state.spin = true;
    host.log("Pokémon GO opened again - bot continues");
    host.sleep(20);                                             //  let the game load
}


}
}
}
}
