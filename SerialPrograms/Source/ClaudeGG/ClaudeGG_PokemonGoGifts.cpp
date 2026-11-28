/*  Claude GG Pokemon GO Gifts (the gifts of the friends in the Pokémon GO bot: open the ones that wait and send one to every friend)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  See ClaudeGG_PokemonGoGifts.h.  What the Python code does is followed line by line, down to the order of the taps, the waits and the log lines.
 *
 */

#include <algorithm>
#include <cstdlib>
#include <set>
#include <string>
#include <opencv2/imgproc.hpp>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonValue>
#include "ClaudeGG_PokemonGoGifts.h"
#include "ClaudeGG_PokemonGoPy.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Gifts{

using Py::py_space;

namespace{

//  ---- numpy: a[start:stop] along an axis that is n long (a negative end counts from the other end; both are cut at the edges)
std::pair<int, int> cut(int n, int start, int stop){
    const auto one = [n](int i){
        if (i < 0){
            i += n;
        }
        return std::min(std::max(i, 0), n);
    };
    const int lo = one(start);
    const int hi = one(stop);
    return {lo, std::max(hi, lo)};
}

//  img[y0:y1, x0:x1] (nothing in it: an empty picture).
cv::Mat part(const cv::Mat& img, int y0, int y1, int x0, int x1){
    const std::pair<int, int> rows = cut(img.rows, y0, y1);
    const std::pair<int, int> cols = cut(img.cols, x0, x1);
    return img(cv::Range(rows.first, rows.second), cv::Range(cols.first, cols.second));
}

//  The pixels of a part of a picture that are pink (hue 140 - 172, saturation over s_min, value over v_min).
int count_pink(const cv::Mat& region, int s_min, int v_min){
    if (region.empty()){
        return 0;
    }
    cv::Mat hsv;
    cv::cvtColor(region, hsv, cv::COLOR_BGR2HSV);
    int count = 0;
    for (int r = 0; r < hsv.rows; r++){
        const cv::Vec3b* row = hsv.ptr<cv::Vec3b>(r);
        for (int c = 0; c < hsv.cols; c++){
            if (row[c][0] >= 140 && row[c][0] <= 172 && row[c][1] > s_min && row[c][2] > v_min){
                count++;
            }
        }
    }
    return count;
}


//  ---- the text of the friend list

//  The words that are no names (NOT_NAMES).
bool not_a_name(const QString& w){
    static const std::set<QString> NOT_NAMES = {
        "SENT", "CAUGHT", "GIFT", "GIFT!", "YOU", "TODAY", "YESTERDAY", "ONLINE", "FRIEND", "FRIENDS",
        "SEARCH", "INVITE", "HATCHED", "EVOLVED", "RAID", "NICKNAME", "LEVEL", "DAYS", "AGO",
        "REMOVE", "REMOTE", "TRADE", "BATTLE", "SETTINGS", "UNKNOWN", "TOTAL", "ACTIVITY"
    };
    return NOT_NAMES.count(w) != 0;
}

//  re.fullmatch(r"[A-Z0-9_]{lo,hi}", w)
bool name_like(const QString& w, int lo, int hi){
    if (w.size() < lo || w.size() > hi){
        return false;
    }
    for (const QChar c : w){
        const ushort u = c.unicode();
        if (!((u >= 'A' && u <= 'Z') || (u >= '0' && u <= '9') || u == '_')){
            return false;
        }
    }
    return true;
}
//  re.fullmatch(r"\d+", w) (for a word that has a letter or a digit at least: it is only asked of names)
bool all_digits(const QString& w){
    for (const QChar c : w){
        if (!c.isDigit()){
            return false;
        }
    }
    return true;
}

//  The place where the first of the time words of the friend list is in a text, nothing when there is none: TIME_WORDS.search(text).start() with
//  TIME_WORDS = (\d+\+?\s*DAYS?\s*AGO|YESTERDAY|TODAY|\d+\s*H(OURS?)?\s*AGO|JUST NOW).  Only where the match begins is wanted, so every way that the
//  expression could take is tried at every place, from the left.
qsizetype skip_space(const QString& t, qsizetype i){
    while (i < t.size() && py_space(t.at(i))){
        i++;
    }
    return i;
}
bool word_at(const QString& t, qsizetype i, const char* w){
    return t.mid(i, (qsizetype)std::char_traits<char>::length(w)) == QLatin1String(w);
}
bool ago_at(const QString& t, qsizetype i){
    return word_at(t, skip_space(t, i), "AGO");
}
bool days_ago_at(const QString& t, qsizetype i){                //  \d+\+?\s*DAYS?\s*AGO  (asked at a place inside the text only)
    if (!t.at(i).isDigit()){
        return false;
    }
    while (i < t.size() && t.at(i).isDigit()){
        i++;
    }
    if (i < t.size() && t.at(i) == QChar('+')){
        i++;
    }
    i = skip_space(t, i);
    if (!word_at(t, i, "DAY")){
        return false;
    }
    i += 3;
    if (word_at(t, i, "S") && ago_at(t, i + 1)){
        return true;
    }
    return ago_at(t, i);
}
bool hours_ago_at(const QString& t, qsizetype i){               //  \d+\s*H(OURS?)?\s*AGO  (asked at a place inside the text only)
    if (!t.at(i).isDigit()){
        return false;
    }
    while (i < t.size() && t.at(i).isDigit()){
        i++;
    }
    i = skip_space(t, i);
    if (!word_at(t, i, "H")){
        return false;
    }
    i += 1;
    if (word_at(t, i, "OUR")){
        if (word_at(t, i + 3, "S") && ago_at(t, i + 4)){
            return true;
        }
        if (ago_at(t, i + 3)){
            return true;
        }
    }
    return ago_at(t, i);
}
qsizetype time_word_start(const QString& text){
    for (qsizetype i = 0; i < text.size(); i++){
        if (days_ago_at(text, i) || word_at(text, i, "YESTERDAY") || word_at(text, i, "TODAY") || hours_ago_at(text, i) || word_at(text, i, "JUST NOW")){
            return i;
        }
    }
    return -1;
}

QJsonArray strings_of(const QJsonValue& value){
    QJsonArray out;
    for (const QJsonValue& v : value.toArray()){
        if (v.isString()){
            out.append(v);
        }
    }
    return out;
}
QStringList list_of(const QJsonValue& value){
    QStringList out;
    for (const QJsonValue& v : strings_of(value)){
        out << v.toString();
    }
    return out;
}

}


//  ---- the readers

bool sent_arrow(const cv::Mat& img, int y){
    const cv::Mat region = part(img, std::max(y + 90, 0), std::min(y + 200, CANVAS_H), 320, 420);
    if (region.empty()){
        return false;
    }
    cv::Mat hsv;
    cv::cvtColor(region, hsv, cv::COLOR_BGR2HSV);
    int count = 0;
    for (int r = 0; r < hsv.rows; r++){
        const cv::Vec3b* row = hsv.ptr<cv::Vec3b>(r);
        for (int c = 0; c < hsv.cols; c++){
            if (row[c][1] < 40 && row[c][2] > 95 && row[c][2] < 180){
                count++;
            }
        }
    }
    return count > 1200;
}

bool gift_icon(const cv::Mat& img, int y0, int y1){
    const cv::Mat region = part(img, std::max(y0, 0), std::min(y1, CANVAS_H), 450, 900);
    return !region.empty() && count_pink(region, 120, 140) > 1500;
}

std::vector<Friend> parse_friends(const Nav::Lines& lines, const cv::Mat* img){
    //  the rows: (index of the line, the word that is the name)
    std::vector<std::pair<size_t, Nav::Word>> rows;
    for (size_t i = 0; i < lines.size(); i++){
        const Nav::Line& line = lines[i];
        const QString& text = line.text;
        std::optional<Nav::Word> name;
        const qsizetype start = time_word_start(text);
        if (start >= 0){                                            //  "Name   2+ days ago"
            for (const Nav::Word& w : line.words){
                if (text.indexOf(w.text) < start && name_like(w.text, 3, 15) && !not_a_name(w.text)){
                    name = w;                                       //  (the last one that fits)
                }
            }
        }
        if (!name.has_value()){                                     //  "Name" with "Name caught X!" / "Name sent you a Gift!" below
            for (const Nav::Word& w : line.words){
                if (!(name_like(w.text, 4, 15) && !not_a_name(w.text) && !all_digits(w.text))){
                    continue;
                }
                bool below = false;
                for (size_t k = i + 1; k < std::min(i + 4, lines.size()) && !below; k++){
                    const int dy = lines[k].y - line.y;
                    if (0 < dy && dy < 500 && (lines[k].text.startsWith(w.text) || (QString(" ") + lines[k].text + " ").contains(QString(" ") + w.text + " "))){
                        below = true;
                    }
                }
                if (below){
                    name = w;
                    break;
                }
            }
        }
        if (name.has_value() && !(!rows.empty() && rows.back().second.text == name->text)){
            rows.push_back({i, *name});
        }
    }
    std::vector<Friend> friends;
    for (size_t k = 0; k < rows.size(); k++){
        const Nav::Word& name = rows[k].second;
        const int y = name.y;
        const int y_next = k + 1 < rows.size() ? rows[k + 1].second.y : y + 520;
        bool gift = false;
        for (const Nav::Line& line : lines){
            if (y < line.y && line.y < y_next && (line.text.contains("SENT YOU") || line.text.contains("GIFT!"))){
                gift = true;
                break;
            }
        }
        if (!gift && img != nullptr){
            gift = gift_icon(*img, y, std::min(y_next, y + 520));
        }
        Friend f;
        f.name = name.text;
        f.x = name.x;
        f.y = y;
        f.gift = gift;
        f.arrow = img != nullptr && sent_arrow(*img, y);
        friends.push_back(f);
    }
    return friends;
}

bool is_gift_screen(const cv::Mat& img){
    return count_pink(part(img, 150, 900, 400, 1400), 120, 120) > 40000;
}

bool has_sticker_button(Loop::Host& host, const cv::Mat& img){
    return Start::ocr_text(host, img, 1480, 1680).contains("STICKER");
}

namespace{

std::optional<Button> pill_button(const cv::Mat& img){
    const std::optional<Start::Found> found = Start::find_pill_button(img);
    if (!found.has_value()){
        return std::nullopt;
    }
    return Button{found->x, found->y, found->area};
}

}

std::optional<Button> send_button(Loop::Host& host, const cv::Mat& img){
    if (has_sticker_button(host, img)){
        return Button{SEND_BTN.x, SEND_BTN.y, std::nullopt};
    }
    return pill_button(img);
}

bool is_friend_list(Loop::Host& host, const cv::Mat& img){
    const QString top = Start::ocr_text(host, img, 0, 420);
    return top.contains("FRIENDS") && (top.contains("SOCIAL") || (top + " ").contains("ME ") || top.contains("PARTY"));
}

bool any_text(const Nav::Lines& lines, const QStringList& needles){
    for (const Nav::Line& line : lines){
        bool all = true;
        for (const QString& n : needles){
            if (!line.text.contains(n)){
                all = false;
                break;
            }
        }
        if (all){
            return true;
        }
    }
    return false;
}


//  ---- the memory of the day

QJsonObject state_json(const State& state){
    return QJsonObject{
        {"day", state.day},
        {"sent", QJsonArray::fromStringList(state.sent)},
        {"opened", QJsonArray::fromStringList(state.opened)},
        {"open_blocked", state.open_blocked},
        {"send_blocked", state.send_blocked},
    };
}

QString state_file(Host& host){
    const QString package = host.package();
    if (package == "com.nianticlabs.pokemongo"){
        return "gifts_state.json";
    }
    return "gifts_state_" + package.section('.', -1) + ".json";
}

State load_gift_state(Host& host){
    const QString today = host.today();
    const std::optional<QByteArray> raw = host.gift_state_read(state_file(host));
    if (raw.has_value()){
        const QJsonDocument doc = QJsonDocument::fromJson(*raw);       //  (a null document when it is not JSON: no object)
        if (doc.isObject()){
            const QJsonObject o = doc.object();
            if (o.value("day").isString() && o.value("day").toString() == today){
                State st;
                st.day = today;
                st.sent = list_of(o.value("sent"));
                st.opened = list_of(o.value("opened"));
                st.open_blocked = o.value("open_blocked").toBool();
                st.send_blocked = o.value("send_blocked").toBool();
                return st;
            }
        }
    }
    State st;
    st.day = today;
    return st;
}

void save_gift_state(Host& host, const State& state){
    host.gift_state_write(state_file(host), QJsonDocument(state_json(state)).toJson(QJsonDocument::Compact));
}


//  ---- the visits

bool back_to_list(Host& host){
    for (int k = 0; k < 3; k++){
        host.back();
        host.sleep(2.5);
        if (is_friend_list(host, host.screenshot())){
            return true;
        }
    }
    return false;
}

namespace{

//  The y of the first word of the lines that is SEND or begins with TRADE: the label of the buttons below the gift icon of the profile.
std::optional<int> label_y(const Nav::Lines& lines){
    for (const Nav::Line& line : lines){
        for (const Nav::Word& w : line.words){
            if (w.text == "SEND" || w.text.startsWith("TRADE")){
                return w.y;
            }
        }
    }
    return std::nullopt;
}

}

void visit_friend(Host& host, const Friend& f, bool want_open, bool want_send, State& state){
    const QString& name = f.name;
    host.tap(f.x, f.y);
    host.sleep(3.5);
    cv::Mat img = host.screenshot();

    if (f.gift || is_gift_screen(img)){                 //  tapping a friend with a gift opens the gift
        std::optional<Button> btn = pill_button(img);
        if (!btn.has_value() && is_gift_screen(img)){
            btn = Button{OPEN_BTN.x, OPEN_BTN.y, std::nullopt};
        }
        if (want_open && btn.has_value()){
            host.tap(btn->x, btn->y);                   //  OPEN
            host.sleep(6);
            img = host.screenshot();
            host.save_picture("g_gift_opened.png", img);
            const Nav::Lines lines = host.ocr_lines(img);
            if (is_gift_screen(img) && !any_text(lines, {"LIMIT"})){
                host.log(QString("gifts: tapped OPEN for %1 but the gift screen is still open").arg(name));
                host.back();
                host.sleep(2);
            }else if (any_text(lines, {"MAXIMUM"}) || any_text(lines, {"LIMIT"}) || any_text(lines, {"BAG", "FULL"})){
                host.log("gift limit reached or bag full - no more opening today");
                state.open_blocked = true;
                host.back();
                host.sleep(2);
            }else{
                state.opened << name;
                host.log(QString::fromUtf8("gift from %1 opened ✔").arg(name));
                for (int k = 0; k < 2; k++){            //  skip the item overview
                    host.tap(CENTER.x, CENTER.y);
                    host.sleep(2);
                }
            }
        }else{
            host.back();                                //  do not open: close the gift screen
            host.sleep(2.5);
        }
    }

    if (want_send){
        //  scroll the profile down to the SEND GIFT / TRADE buttons in small, slow steps (a fast swipe flings the page too far); on the empty
        //  right side: a drag on the trainer only rotates the avatar
        Nav::Lines lines;
        bool found = false;
        for (int k = 0; k < PROFILE_LOOKS; k++){
            img = host.screenshot();
            lines = host.ocr_lines(img, 0, 2208);
            const std::optional<int> by = label_y(lines);
            if (by.has_value() && *by < 450){           //  buttons too high (icon cut off): scroll back up
                host.swipe(1550, 900, 1550, 1300, 1000);
                host.sleep(2);
                continue;
            }
            if (by.has_value() || any_text(lines, {"GIFT", "SENT"})){
                found = true;
                break;
            }
            host.swipe(1550, 1700, 1550, 1200, 1000);
            host.sleep(2);
        }
        if (!found){
            host.log(QString("gifts: SEND GIFT button not found on the profile of %1").arg(name));
        }
        host.save_picture("g_friend_profile.png", img);
        if (any_text(lines, {"GIFT", "SENT"})){
            state.sent << name;
        }else{
            std::optional<Point> target;
            for (const Nav::Line& line : lines){
                for (const Nav::Word& w : line.words){
                    if (w.text == "SEND" || w.text.startsWith("TRADE")){
                        target = Point{336, w.y - 140};     //  icon above the SEND GIFT label (left column)
                        break;
                    }
                }
                if (target.has_value()){
                    break;
                }
            }
            bool near_remove = false;
            if (target.has_value()){
                for (const Nav::Line& line : lines){
                    if (line.text.contains("REMOVE") && std::abs(line.y - target->y) < 300){
                        near_remove = true;
                        break;
                    }
                }
            }
            bool sendable = false;
            if (target.has_value()){
                //  coloured gift icon = you can send; grey icon = already sent today / not possible
                const int tx = target->x;
                const int ty = target->y;
                const cv::Mat icon = part(img, std::max(ty - 120, 0), ty + 110, std::max(tx - 136, 0), tx + 134);
                sendable = count_pink(icon, 100, 120) > 1500;
                if (!sendable){
                    host.log(QString("cannot send a gift to %1 right now (icon grey) - skipping today").arg(name));
                    state.sent << name;
                }
            }
            if (target.has_value() && sendable && !near_remove){
                host.tap(target->x, target->y);
                host.sleep(3);
                img = host.screenshot();
                Nav::Lines shown = host.ocr_lines(img, 150, 500);
                if (any_text(shown, {"WHICH", "GIFT"})){
                    host.sleep(2);                      //  let the gift list finish its animation
                    std::optional<Button> btn;
                    for (const Point& spot : GIFT_SPOTS){   //  postcard, bow, place name of the first gift
                        host.tap_press(spot.x, spot.y, GIFT_PRESS_MS);
                        host.sleep(3);
                        img = host.screenshot();
                        btn = send_button(host, img);
                        if (btn.has_value()){
                            break;
                        }
                        host.save_picture("g_gift_select.png", img);
                    }
                    if (!btn.has_value()){
                        host.save_picture("g_send_nobutton.png", img);
                        host.log(QString("gifts: SEND button not found for %1").arg(name));
                        host.back();
                        host.sleep(2);
                    }else{
                        host.tap(btn->x, btn->y);       //  SEND
                        host.sleep(6);
                        img = host.screenshot();
                        if (has_sticker_button(host, img)){
                            host.save_picture("g_send_stuck.png", img);
                            host.log(QString("gifts: tapped SEND for %1 but the send screen is still open").arg(name));
                            host.back();
                            host.sleep(2);
                        }else{
                            state.sent << name;
                            host.log(QString::fromUtf8("gift sent to %1 ✔").arg(name));
                        }
                    }
                }else{
                    host.save_picture("g_send_failed.png", img);
                    const Nav::Lines full = host.ocr_lines(img);
                    if (any_text(full, {"NO", "GIFT"}) || any_text(full, {"DON'T HAVE"})){
                        host.log("no gifts left to send - stopping for today");
                        state.send_blocked = true;
                    }else{
                        host.log(QString("could not send a gift to %1 (already sent today?)").arg(name));
                        state.sent << name;             //  do not retry this friend today
                    }
                    host.back();
                    host.sleep(2);
                }
            }
        }
    }
    save_gift_state(host, state);
    back_to_list(host);
}

void gifts_round(Host& host){
    State state = load_gift_state(host);
    const bool want_open = host.wanted("gifts_open") && !state.open_blocked;
    const bool want_send = host.wanted("gifts_send") && !state.send_blocked;
    if (!(want_open || want_send)){
        return;
    }
    host.log("gifts: checking friend list");
    host.tap(AVATAR.x, AVATAR.y);
    host.sleep(3);
    host.tap(FRIENDS_TAB.x, FRIENDS_TAB.y);
    host.sleep(3);
    cv::Mat img = host.screenshot();
    host.save_picture("g_gifts_start.png", img);
    if (!is_friend_list(host, img)){
        host.log("gifts: friend list not found - aborting (see debug/g_gifts_start.png)");
        for (int k = 0; k < 3; k++){
            host.back();
            host.sleep(2);
        }
        return;
    }
    std::set<QString> seen;
    int idle_scrolls = 0;
    for (int look = 0; look < ROUND_LOOKS; look++){
        img = host.screenshot();
        if (!is_friend_list(host, img)){                //  e.g. still on a profile: go back first
            if (!back_to_list(host)){
                host.log("gifts: lost the friend list - aborting");
                break;
            }
            img = host.screenshot();
        }
        const std::vector<Friend> friends = parse_friends(host.ocr_lines(img, 380, 2050), &img);
        std::optional<Friend> todo;
        bool todo_open = false;
        bool todo_send = false;
        bool new_names = false;
        for (const Friend& f : friends){
            if (seen.count(f.name) != 0){
                continue;
            }
            seen.insert(f.name);
            new_names = true;
            const bool o = want_open && !state.open_blocked && f.gift;
            //  a friend with an unopened gift is only visited when opening is on (tapping that friend always opens the gift screen first)
            const bool snd = want_send && !state.send_blocked && !state.sent.contains(f.name) && !f.arrow && (!f.gift || o);
            if (want_send && f.arrow && !o){
                host.log(QString("gifts: %1 already has a gift from you (arrow) - not visiting").arg(f.name));
            }
            if (o || snd){
                todo = f;
                todo_open = o;
                todo_send = snd;
                break;
            }
        }
        if (todo.has_value()){
            idle_scrolls = 0;
            visit_friend(host, *todo, todo_open, todo_send, state);
            continue;
        }
        //  only stop when scrolling shows no new friends any more (end of the list)
        idle_scrolls = new_names ? 0 : idle_scrolls + 1;
        if (idle_scrolls > 1){
            break;
        }
        host.swipe(884, 1800, 884, 900, 700);           //  scroll the friend list
        host.sleep(2);
    }
    host.log(QString("gifts: done (today: %1 opened, %2 sent)").arg(state.opened.size()).arg(state.sent.size()));
    for (int k = 0; k < 4; k++){                        //  back to the map
        host.back();
        host.sleep(2.5);
        if (host.on_map(host.screenshot())){
            break;
        }
    }
}


}
}
}
}
