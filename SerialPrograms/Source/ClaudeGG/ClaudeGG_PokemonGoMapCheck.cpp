/*  Claude GG Pokemon GO Map Check (a step on the map of the Pokémon GO bot, played on the stories of the Python code)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The file of Mobile/tools/make_map_golden.py holds three things: the numbers of the map, pictures with what the four readers of
 *  pixels (ring_spun(), bag_full(), box_full_ball() and looks_spun()) made of them, and stories: lists of calls (do_map(),
 *  do_pokestop(), the looks of the Brain and fire_rotation()) with the events that they made.  What the code was given: screenshots,
 *  what the map detector found in a part of a picture, the random numbers that were drawn, the counts of the day.  What it did: taps,
 *  swipes, log lines, sleeps, pictures that were kept, the calls of the parts that are not ported yet, what it returned and what it
 *  remembered afterwards.  The host here gives the port the same, one after the other, and says where the port does something else: the
 *  first event that differs ends that story.
 *
 *  A picture is not in the file: the file says how it is made (white, or white with rectangles of colour), and what the detector found
 *  in it is in the events.
 *
 */

#include <algorithm>
#include <cmath>
#include <map>
#include <stdexcept>
#include <opencv2/imgproc.hpp>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include "ClaudeGG_PokemonGoMap.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Map{

namespace{

const int REF_W = Loop::REF_W;
const int REF_H = Loop::REF_H;


//  Thrown when the port went another way: ends the story (not a std::exception: the code must not take it for an error of the phone).
struct Abort{};

QString describe(const QJsonValue& value){
    QString text;
    if (value.isArray()){
        text = QString::fromUtf8(QJsonDocument(value.toArray()).toJson(QJsonDocument::Compact));
    }else if (value.isObject()){
        text = QString::fromUtf8(QJsonDocument(value.toObject()).toJson(QJsonDocument::Compact));
    }else{
        text = value.toVariant().toString();
    }
    if (text.size() > 300){
        text = text.left(300) + "...";
    }
    return text;
}

//  How make_start_golden.make_picture() makes a picture (the pictures are kept: the stories use few).
cv::Mat make_picture(const QJsonArray& spec){
    static std::map<QString, cv::Mat> kept;
    const QString key = QString::fromUtf8(QJsonDocument(spec).toJson(QJsonDocument::Compact));
    const auto at = kept.find(key);
    if (at != kept.end()){
        return at->second;
    }
    cv::Mat img(REF_H, REF_W, CV_8UC3, cv::Scalar(255, 255, 255));
    if (spec.at(0).toString() == "rect"){
        for (const QJsonValue& v : spec.at(1).toArray()){
            const QJsonArray r = v.toArray();
            const QJsonArray c = r.at(4).toArray();
            const int y0 = (int)(r.at(0).toDouble() * REF_H);
            const int y1 = std::min((int)(r.at(1).toDouble() * REF_H), REF_H);
            const int x0 = (int)(r.at(2).toDouble() * REF_W);
            const int x1 = std::min((int)(r.at(3).toDouble() * REF_W), REF_W);
            if (y0 < y1 && x0 < x1){
                img(cv::Range(y0, y1), cv::Range(x0, x1)) = cv::Scalar(c.at(0).toDouble(), c.at(1).toDouble(), c.at(2).toDouble());
            }
        }
    }
    kept[key] = img;
    return img;
}

//  The first place where two JSON values are not the same (numbers: to a millionth, as the golden file is rounded), or nothing.
QString difference(const QJsonValue& want, const QJsonValue& got, const QString& path){
    if (want.isDouble() && got.isDouble()){
        if (std::abs(want.toDouble() - got.toDouble()) > 1.5e-6){
            return QString("%1: %2 is not %3").arg(path, describe(want), describe(got));
        }
        return QString();
    }
    if (want.isArray() && got.isArray()){
        const QJsonArray a = want.toArray();
        const QJsonArray b = got.toArray();
        if (a.size() != b.size()){
            return QString("%1: %2 is not %3").arg(path, describe(want), describe(got));
        }
        for (qsizetype i = 0; i < a.size(); i++){
            const QString one = difference(a.at(i), b.at(i), QString("%1[%2]").arg(path).arg(i));
            if (!one.isEmpty()){
                return one;
            }
        }
        return QString();
    }
    if (want.isObject() && got.isObject()){
        const QJsonObject a = want.toObject();
        const QJsonObject b = got.toObject();
        for (auto it = a.begin(); it != a.end(); ++it){
            if (!b.contains(it.key())){
                return QString("%1: '%2' is missing").arg(path, it.key());
            }
            const QString one = difference(it.value(), b.value(it.key()), path + "." + it.key());
            if (!one.isEmpty()){
                return one;
            }
        }
        for (auto it = b.begin(); it != b.end(); ++it){
            if (!a.contains(it.key())){
                return QString("%1: '%2' is there but should not be").arg(path, it.key());
            }
        }
        return QString();
    }
    if (want == got){
        return QString();
    }
    return QString("%1: %2 is not %3").arg(path, describe(want), describe(got));
}


//  ---- what the port remembers, as the Python code's snapshot() tells it

QJsonValue point_json(const std::optional<Point>& p){
    return p.has_value() ? QJsonValue(QJsonArray{p->x, p->y}) : QJsonValue(QJsonValue::Null);
}
QJsonArray swipe_json(const Swipe& s){
    return QJsonArray{s.x1, s.y1, s.x2, s.y2, s.ms};
}

QJsonObject state_json(const State& st){
    QJsonObject out;
    QJsonObject bag{{"full", st.bag_is_full}};
    if (st.bag_cleaned.has_value()){
        bag["cleaned"] = *st.bag_cleaned;
    }
    out["bag_state"] = bag;
    out["catch"] = st.catching;
    QJsonArray cooldown;
    for (const Cool& c : st.cooldown){
        cooldown.append(QJsonArray{c.x, c.y, c.until});
    }
    out["cooldown"] = cooldown;
    out["enc"] = QJsonObject{
        {"ball_set", st.enc.ball_set}, {"berry", st.enc.berry}, {"caught", st.enc.caught}, {"start", st.enc.start},
        {"t_result", st.enc.t_result}, {"t_tap", st.enc.t_tap}, {"t_throw", st.enc.t_throw}, {"throws", st.enc.throws},
    };
    out["enc_xy"] = QJsonObject{{"xy", point_json(st.enc_xy)}};
    out["fast_pending"] = QJsonObject{
        {"looks", st.fast_pending.looks}, {"t", st.fast_pending.t}, {"t_back", st.fast_pending.t_back}, {"t_throw", st.fast_pending.t_throw},
        {"xy", point_json(st.fast_pending.xy)},
    };
    out["fast_state"] = QJsonObject{{"fails", st.fast_fails}, {"off_until", st.fast_off_until}};
    out["gift_timer"] = QJsonObject{{"last", st.gift_last}};
    QJsonValue alt = QJsonValue(QJsonValue::Null);
    if (st.last_tap.alt.has_value()){
        QJsonArray list;
        for (const Point& p : *st.last_tap.alt){
            list.append(QJsonArray{p.x, p.y});
        }
        alt = list;
    }
    out["last_tap"] = QJsonObject{
        {"alt", alt}, {"kind", st.last_tap.kind.has_value() ? QJsonValue(*st.last_tap.kind) : QJsonValue(QJsonValue::Null)},
        {"near", st.last_tap.near}, {"xy", point_json(st.last_tap.xy)},
    };
    out["menu_check"] = QJsonObject{{"last", st.menu_check_last}};
    out["near_state"] = QJsonObject{{"until", st.near_until}};
    QJsonObject perf{{"detect", st.perf.detect}, {"looks", st.perf.looks}, {"shot", st.perf.shot}, {"total", st.perf.total}, {"wait", st.perf.wait}};
    if (st.perf.t_step.has_value()){
        perf["t_step"] = *st.perf.t_step;
    }
    out["perf"] = perf;
    const Rotation& r = st.rotation;
    QJsonValue fired = QJsonValue(QJsonValue::Null);
    if (r.fired.has_value()){
        fired = QJsonObject{{"swipe", swipe_json(r.fired->swipe)}, {"t", r.fired->t}};
    }
    out["rotation"] = QJsonObject{
        {"armed", r.armed.has_value() ? QJsonValue(QJsonArray{swipe_json(*r.armed), 0}) : QJsonValue(QJsonValue::Null)},
        {"armed_at", r.armed_at}, {"dir", r.dir}, {"fired", fired}, {"goal", r.goal}, {"steps", r.steps}, {"turned", r.turned},
    };
    out["spin"] = st.spin;
    out["storage_state"] = QJsonObject{{"full", st.storage_full}};
    out["throw_info"] = QJsonObject{{"hit", st.throw_hit.has_value() ? QJsonValue(*st.throw_hit) : QJsonValue(QJsonValue::Null)}};
    return out;
}

std::optional<Point> point_of(const QJsonValue& v){
    if (!v.isArray()){
        return std::nullopt;
    }
    return Point{v.toArray().at(0).toInt(), v.toArray().at(1).toInt()};
}
Swipe swipe_of(const QJsonArray& a){
    Swipe s;
    s.x1 = a.at(0).toInt();
    s.y1 = a.at(1).toInt();
    s.x2 = a.at(2).toInt();
    s.y2 = a.at(3).toInt();
    s.ms = a.at(4).toInt();
    return s;
}

//  The state a story starts with: what restore() of the Python code makes of its "init" (what it does not say stays as it is).
State state_of(const QJsonObject& init){
    State st;
    for (auto it = init.begin(); it != init.end(); ++it){
        const QString key = it.key();
        const QJsonObject o = it.value().toObject();
        if (key == "enc"){
            Encounter& e = st.enc;
            e.start = o.value("start").toDouble(e.start);
            e.throws = o.value("throws").toInt(e.throws);
            e.berry = o.value("berry").toBool(e.berry);
            e.ball_set = o.value("ball_set").toBool(e.ball_set);
            e.caught = o.value("caught").toBool(e.caught);
            e.t_throw = o.value("t_throw").toDouble(e.t_throw);
            e.t_result = o.value("t_result").toDouble(e.t_result);
            e.t_tap = o.value("t_tap").toDouble(e.t_tap);
        }else if (key == "enc_xy"){
            st.enc_xy = point_of(o.value("xy"));
        }else if (key == "throw_info"){
            if (o.value("hit").isBool()){
                st.throw_hit = o.value("hit").toBool();
            }
        }else if (key == "fast_pending"){
            FastPending& f = st.fast_pending;
            if (o.contains("xy")){
                f.xy = point_of(o.value("xy"));
            }
            f.t = o.value("t").toDouble(f.t);
            f.t_throw = o.value("t_throw").toDouble(f.t_throw);
            f.t_back = o.value("t_back").toDouble(f.t_back);
            f.looks = o.value("looks").toInt(f.looks);
        }else if (key == "fast_state"){
            st.fast_fails = o.value("fails").toInt(st.fast_fails);
            st.fast_off_until = o.value("off_until").toDouble(st.fast_off_until);
        }else if (key == "last_tap"){
            if (o.value("kind").isString()){
                st.last_tap.kind = o.value("kind").toString();
            }
            if (o.contains("xy")){
                st.last_tap.xy = point_of(o.value("xy"));
            }
            st.last_tap.near = o.value("near").toBool(st.last_tap.near);
        }else if (key == "near_state"){
            st.near_until = o.value("until").toDouble(st.near_until);
        }else if (key == "rotation"){
            Rotation& r = st.rotation;
            r.steps = o.value("steps").toInt(r.steps);
            r.turned = o.value("turned").toDouble(r.turned);
            r.goal = o.value("goal").toDouble(r.goal);
            r.dir = o.value("dir").toInt(r.dir);
            if (o.contains("armed")){
                if (o.value("armed").isArray()){
                    r.armed = swipe_of(o.value("armed").toArray().at(0).toArray());
                }else{
                    r.armed.reset();
                }
            }
            r.armed_at = o.value("armed_at").toDouble(r.armed_at);
            if (o.contains("fired")){
                if (o.value("fired").isObject()){
                    Fired f;
                    f.t = o.value("fired").toObject().value("t").toDouble();
                    f.swipe = swipe_of(o.value("fired").toObject().value("swipe").toArray());
                    r.fired = f;
                }else{
                    r.fired.reset();
                }
            }
        }else if (key == "perf"){
            Perf& p = st.perf;
            p.looks = o.value("looks").toInt(p.looks);
            p.shot = o.value("shot").toDouble(p.shot);
            p.detect = o.value("detect").toDouble(p.detect);
            p.total = o.value("total").toDouble(p.total);
            p.wait = o.value("wait").toDouble(p.wait);
            if (o.contains("t_step")){
                p.t_step = o.value("t_step").toDouble();
            }
        }else if (key == "storage_state"){
            st.storage_full = o.value("full").toBool(st.storage_full);
        }else if (key == "bag_state"){
            st.bag_is_full = o.value("full").toBool(st.bag_is_full);
            if (o.contains("cleaned")){
                st.bag_cleaned = o.value("cleaned").toDouble();
            }
        }else if (key == "menu_check"){
            st.menu_check_last = o.value("last").toDouble(st.menu_check_last);
        }else if (key == "gift_timer"){
            st.gift_last = o.value("last").toDouble(st.gift_last);
        }else if (key == "cooldown"){
            for (const QJsonValue& c : it.value().toArray()){
                st.cooldown.push_back(Cool{c.toArray().at(0).toInt(), c.toArray().at(1).toInt(), c.toArray().at(2).toDouble()});
            }
        }else if (key == "spin"){
            st.spin = it.value().toBool();
        }else if (key == "catch"){
            st.catching = it.value().toBool();
        }
    }
    return st;
}


class Replay : public Host, public Brain::Detector{
public:
    Replay(const QJsonObject& test_case, double start)
        : m_spec(test_case.value("spec").toObject())
        , m_events(test_case.value("events").toArray())
        , m_frames(m_spec.value("frames").toArray())
        , m_t(start)
    {
        m_settings = m_spec.value("settings").toObject();
        m_wanted = QJsonObject{
            {"gifts_open", false}, {"gifts_send", false}, {"daily_cycle", false}, {"close_when_full", false}, {"spin_only_when_full", false},
        };
        const QJsonObject wanted = m_spec.value("wanted").toObject();
        for (auto it = wanted.begin(); it != wanted.end(); ++it){
            m_wanted[it.key()] = it.value();
        }
    }

    //  ---- the events
    bool failed = false;
    QString message;
    qsizetype index = 0;

    [[noreturn]] void fail(const QString& text){
        if (!failed){
            failed = true;
            message = QString("event %1: ").arg(index) + text;
        }
        throw Abort();
    }

    QJsonArray peek(const QString& doing){
        if (failed){
            throw Abort();
        }
        if (index >= m_events.size()){
            fail("the port went on after the last event of the Python code: " + doing);
        }
        return m_events.at(index).toArray();
    }
    //  The next event, which has to be of this kind (and at this time).
    QJsonArray out(const char* kind, const QString& doing){
        const QJsonArray event = peek(doing);
        if (event.at(0).toString() != kind){
            fail("the Python code did " + describe(event) + ", the port: " + doing);
        }
        if (std::abs(event.at(1).toDouble() - m_t) > 1e-6){
            fail(QString("the Python code did %1 at the time %2, the port: %3 at %4")
                .arg(describe(event), QString::number(event.at(1).toDouble(), 'f', 6), doing, QString::number(m_t, 'f', 6)));
        }
        index++;
        return event;
    }
    //  An event that moves the clock: the code is given the time that it was given.
    QJsonArray input(const char* kind, const QString& doing){
        const QJsonArray event = peek(doing);
        if (event.at(0).toString() != kind){
            fail("the Python code did " + describe(event) + ", the port: " + doing);
        }
        m_t = event.at(1).toDouble();
        index++;
        return event;
    }
    bool done() const{ return index >= m_events.size(); }

    //  ---- the story
    void use(const QJsonObject& call){
        if (call.contains("settings")){
            const QJsonObject o = call.value("settings").toObject();
            for (auto it = o.begin(); it != o.end(); ++it){
                m_settings[it.key()] = it.value();
            }
        }
        if (call.contains("wanted")){
            const QJsonObject o = call.value("wanted").toObject();
            for (auto it = o.begin(); it != o.end(); ++it){
                m_wanted[it.key()] = it.value();
            }
        }
    }
    //  The picture of a frame of the story: a new one every time (the code tells pictures apart by their identity), or the one that
    //  the call before was given.
    cv::Mat frame(int index_of, bool same){
        if (same && !m_last.empty()){
            return m_last;
        }
        m_last = make_picture(m_frames.at(index_of).toObject().value("pic").toArray()).clone();
        return m_last;
    }
    const QJsonObject& spec() const{ return m_spec; }

    //  ---- Loop::Host
    double monotonic() override{ return m_t; }
    void sleep(double seconds) override{
        const QJsonArray event = out("sleep", QString("sleep(%1)").arg(seconds));
        if (std::abs(event.at(2).toDouble() - seconds) > 1e-6){
            fail(QString("the sleep differs: the Python code did %1, the port: %2").arg(describe(event)).arg(seconds));
        }
        m_t += seconds;
    }
    void log(const QString& text) override{
        const QJsonArray event = out("log", "the log line: " + text);
        if (event.at(2).toString() != text){
            fail("the log line differs: the Python code wrote '" + event.at(2).toString() + "', the port: '" + text + "'");
        }
    }
    cv::Mat screenshot() override{ return shot("real"); }
    Loop::Stream* stream() override{ return nullptr; }
    std::unique_ptr<Loop::Tapper> make_tapper(Point, int) override{
        fail("the map made a tapper of the fast taps");
    }
    bool on_map(const cv::Mat& canvas) override{
        return Loop::map_visible(canvas);
    }
    Nav::Lines ocr_lines(const cv::Mat&, int, std::optional<int>, double) override{
        fail("the map read lines of text");
    }
    QString ocr_line(const cv::Mat&, int) override{
        fail("the map read a line of text");
    }
    bool give_up_enabled() override{ return false; }
    bool aim_enabled() override{ return false; }
    void aim_disabled() override{}
    QString league() override{ return QString(); }
    Fight::Known load_seen() override{ return Fight::Known(); }
    void save_seen(const Fight::Known&) override{ fail("the map saved what was seen in a fight"); }
    std::map<QString, Minigame::Learned> load_minigames() override{ return std::map<QString, Minigame::Learned>(); }
    void save_minigames(const std::map<QString, Minigame::Learned>&) override{ fail("the map saved what was learned of a little game"); }
    void save_picture(const QString& name, const cv::Mat&) override{
        const QJsonArray event = out("save", "the picture " + name);
        if (event.at(2).toString() != name){
            fail("the picture that is kept differs: the Python code kept " + describe(event) + ", the port: " + name);
        }
    }
    void beat() override{ fail("the map made a beat"); }
    bool stop() override{ fail("the map asked whether the person stopped"); }
    bool threads() override{ return false; }

    //  ---- Flow::Host
    double wall() override{ return m_t; }
    void tap(int x, int y) override{
        const QString doing = QString("a tap at (%1, %2)").arg(x).arg(y);
        const QJsonArray event = out("tap", doing);
        if (event.at(2).toInt() != x || event.at(3).toInt() != y){
            fail("the tap differs: the Python code did " + describe(event) + ", the port: " + doing);
        }
    }
    void swipe(int x1, int y1, int x2, int y2, int ms) override{ stroke("swipe", x1, y1, x2, y2, ms); }
    void back() override{ out("back", "BACK"); }
    std::pair<QString, double> screen_class(const cv::Mat&) override{ fail("the map asked for the screen classifier"); }
    void restart_game() override{ fail("the map restarted the game through the host of the walk"); }

    //  ---- Start::Host
    void stop_game() override{ fail("the map closed the game"); }
    void start_game() override{ fail("the map started the game"); }
    Start::Launch start_state() override{ fail("the map asked about the start of the game"); }
    void start_end() override{ fail("the map ended the start of the game"); }

    //  ---- Map::Host
    cv::Mat quick_screenshot() override{ return shot("quick"); }
    void swipe_async(int x1, int y1, int x2, int y2, int ms) override{ stroke("swipe_async", x1, y1, x2, y2, ms); }
    double uniform(double lo, double hi) override{
        const QJsonArray event = input("random", QString("a random number between %1 and %2").arg(lo).arg(hi));
        if (event.at(2).toString() != "uniform" || std::abs(event.at(3).toDouble() - lo) > 1e-9 || std::abs(event.at(4).toDouble() - hi) > 1e-9){
            fail(QString("the random number differs: the Python code drew %1, the port: uniform(%2, %3)").arg(describe(event)).arg(lo).arg(hi));
        }
        return event.at(5).toDouble();
    }
    double unit() override{
        const QJsonArray event = input("random", "a random number between 0 and 1");
        if (event.at(2).toString() != "random"){
            fail("the random number differs: the Python code drew " + describe(event) + ", the port: random()");
        }
        return event.at(5).toDouble();
    }
    bool setting(const QString& key, bool fallback) override{
        const QJsonValue v = m_settings.value(key);
        if (v.isUndefined()){
            return fallback;
        }
        return v.isBool() ? v.toBool() : (v.isDouble() && v.toDouble() != 0);
    }
    bool wanted(const QString& key) override{
        const QJsonValue v = m_wanted.value(key);
        return v.isUndefined() ? true : v.toBool();
    }
    QString count(const QString& key) override{
        const QJsonArray event = input("day_count", "the count of the day (" + key + ")");
        if (event.at(2).toString() != key){
            fail("the count differs: the Python code counted " + describe(event) + ", the port: " + key);
        }
        return event.at(3).toString();
    }
    void gifts_round() override{ out("gifts_round", "the gifts"); }
    void check_menu_full() override{ out("check_menu_full", "the check of the full bag in the menu"); }
    void check_all_full() override{ out("check_all_full", "the check of everything that can be full"); }
    int clean_bag() override{
        const QJsonArray event = out("clean_bag", "the clean-up of the bag");
        if (event.at(3).isString()){
            throw std::runtime_error(event.at(3).toString().toStdString());
        }
        return event.at(2).toInt();
    }
    void bag_to_map() override{ out("bag_to_map", "back to the map from the bag"); }
    void resume_spin_later() override{
        const QJsonArray event = out("later", "switching the spinning on again later");
        if (event.at(2).toString() != "spin" || std::abs(event.at(3).toDouble() - BAG_WAIT) > 1e-6){
            fail("the wait differs: the Python code did " + describe(event) + ", the port: spin after " + QString::number(BAG_WAIT));
        }
    }

    //  ---- Brain::Detector
    std::vector<Brain::Detection> map(const cv::Mat&, const cv::Rect& box, double threshold, int top) override{
        const QString doing = QString("a look of the map detector at (%1, %2, %3, %4)").arg(box.x).arg(box.y).arg(box.x + box.width).arg(box.y + box.height);
        const QJsonArray event = input("ssd", doing);
        const QJsonArray want = event.at(2).toArray();
        if (want.at(0).toInt() != box.x || want.at(1).toInt() != box.y || want.at(2).toInt() != box.x + box.width
            || want.at(3).toInt() != box.y + box.height || std::abs(event.at(3).toDouble() - threshold) > 1e-9 || event.at(4).toInt() != top){
            fail(QString("the look differs: the Python code did %1, the port: %2 with %3 and %4").arg(describe(event), doing).arg(threshold).arg(top));
        }
        std::vector<Brain::Detection> found;
        for (const QJsonValue& v : event.at(5).toArray()){
            const QJsonArray d = v.toArray();
            Brain::Detection o;
            o.label = d.at(0).toString().toStdString();
            o.score = d.at(1).toDouble();
            o.cx = d.at(2).toInt();
            o.cy = d.at(3).toInt();
            o.w = d.at(4).toInt();
            o.h = d.at(5).toInt();
            found.push_back(o);
        }
        return found;
    }

    //  ---- the end of a call
    void finish(const QJsonValue& got){
        const QJsonArray event = out("result", "the end of the call");
        const QString one = difference(event.at(2), got, "result");
        if (!one.isEmpty()){
            fail("the call ended differently: " + one + " (the Python code returned " + describe(event.at(2)) + ")");
        }
    }
    void finish_state(const State& state){
        const QJsonArray event = out("state", "what is remembered");
        const QString one = difference(event.at(2), state_json(state), "state");
        if (!one.isEmpty()){
            fail("what is remembered differs: " + one);
        }
    }

private:
    cv::Mat shot(const char* kind){
        const QJsonArray event = input("shot", QString("a %1 screenshot").arg(kind));
        if (event.at(3).toString() != kind){
            fail(QString("the screenshot differs: the Python code took a %1 one, the port: %2").arg(event.at(3).toString(), QString(kind)));
        }
        return make_picture(m_frames.at(event.at(2).toInt()).toObject().value("pic").toArray()).clone();
    }
    void stroke(const char* kind, int x1, int y1, int x2, int y2, int ms){
        const QString doing = QString("a %1 from (%2, %3) to (%4, %5) in %6 ms").arg(QString(kind)).arg(x1).arg(y1).arg(x2).arg(y2).arg(ms);
        const QJsonArray event = out(kind, doing);
        if (event.at(2).toInt() != x1 || event.at(3).toInt() != y1 || event.at(4).toInt() != x2 || event.at(5).toInt() != y2 || event.at(6).toInt() != ms){
            fail(QString("the %1 differs: the Python code did %2, the port: %3").arg(QString(kind), describe(event), doing));
        }
    }

    static constexpr double BAG_WAIT = 1800;

    const QJsonObject m_spec;
    const QJsonArray m_events;
    const QJsonArray m_frames;
    QJsonObject m_settings;
    QJsonObject m_wanted;
    cv::Mat m_last;
    double m_t;
};


//  One story; returns an empty text when the port did the same, or what went another way.
QString play(const QJsonObject& test_case, double start){
    Replay host(test_case, start);
    State state = state_of(host.spec().value("init").toObject());
    Brain::Eyes eyes(host);
    try{
        for (const QJsonValue& v : host.spec().value("calls").toArray()){
            const QJsonObject call = v.toObject();
            host.use(call);
            const QString fn = call.value("fn").toString();
            const QJsonArray event = host.input("call", "the start of a call (" + fn + ")");
            if (event.at(2).toString() != fn){
                host.fail("the call differs: the Python code did " + describe(event) + ", the port: " + fn);
            }
            const bool same = call.value("same").toBool();
            const int img_at = call.value("img").toInt();
            if (fn == "do_map"){
                const cv::Mat img = host.frame(img_at, same);
                host.finish(do_map(host, state, eyes, img));
            }else if (fn == "do_pokestop"){
                const cv::Mat img = host.frame(img_at, same);
                host.finish(do_pokestop(host, state, img));
            }else if (fn == "map_objects"){
                const cv::Mat img = host.frame(img_at, same);
                const std::vector<Brain::Detection> objs = eyes.map_objects(img, call.value("tiles").toBool());
                QJsonArray list;
                for (const Brain::Detection& o : objs){
                    list.append(QJsonArray{QString::fromStdString(o.label), o.score, o.cx, o.cy, o.w, o.h});
                }
                host.finish(QJsonArray{list, eyes.hint});
            }else if (fn == "second_look"){
                const cv::Mat img = host.frame(img_at, same);
                const std::optional<Brain::Seen> seen = eyes.second_look(img, call.value("x").toInt(), call.value("y").toInt());
                QJsonValue found = QJsonValue(QJsonValue::Null);
                if (seen.has_value()){
                    found = QJsonArray{seen->score, seen->x, seen->y, seen->w, seen->h};
                }
                host.finish(QJsonArray{found, eyes.second_best});
            }else if (fn == "fire_rotation"){
                fire_rotation(host, state);
                host.finish(QJsonValue(QJsonValue::Null));
            }else{
                host.fail("a call that the check does not know: " + fn);
            }
            host.finish_state(state);
        }
        if (!host.done()){
            host.fail("the Python code went on: " + describe(host.peek("the end")));
        }
    }catch (const Abort&){
    }catch (const std::exception& e){
        if (!host.failed){
            host.failed = true;
            host.message = QString("event %1: the port threw an error: %2").arg(host.index).arg(QString::fromUtf8(e.what()));
        }
    }
    return host.failed ? host.message : QString();
}

}


int run_map_checks(const QString& golden, QStringList& report){
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the stories of the map are not there: " + golden;
        return 1;
    }
    const QJsonObject root = QJsonDocument::fromJson(qUncompress(file.readAll())).object();
    const QJsonArray cases = root.value("cases").toArray();
    const QJsonArray readers = root.value("readers").toArray();
    const QJsonObject constants = root.value("constants").toObject();
    const double start = root.value("start").toDouble();
    int failed = 0;

    //  the numbers
    const auto mine = map_constants();
    for (const auto& one : mine){
        const QJsonArray want = constants.value(one.first).toArray();
        bool same = (size_t)want.size() == one.second.size();
        for (size_t i = 0; same && i < one.second.size(); i++){
            same = std::abs(want.at((qsizetype)i).toDouble() - one.second[i]) < 1e-12;
        }
        if (!same){
            report << QString("FAILED: the number %1 of the map is not that of the Python code (%2)").arg(one.first, describe(want));
            failed++;
        }
    }
    if ((size_t)constants.size() != mine.size()){
        report << QString("FAILED: the Python code has %1 numbers of the map, the port %2").arg(constants.size()).arg(mine.size());
        failed++;
    }

    //  the readers of pixels
    for (const QJsonValue& v : readers){
        const QJsonObject c = v.toObject();
        const cv::Mat img = make_picture(c.value("pic").toArray());
        QStringList wrong;
        if (ring_spun(img) != c.value("ring").toBool()){
            wrong << "ring_spun";
        }
        if (bag_full(img) != c.value("bag").toBool()){
            wrong << "bag_full";
        }
        if (box_full_ball(img) != c.value("full").toBool()){
            wrong << "box_full_ball";
        }
        for (const QJsonValue& s : c.value("spun").toArray()){
            const QJsonArray box = s.toObject().value("box").toArray();
            Brain::Detection stop;
            stop.label = "pokestop";
            stop.score = 0.9;
            stop.cx = box.at(0).toInt();
            stop.cy = box.at(1).toInt();
            stop.w = box.at(2).toInt();
            stop.h = box.at(3).toInt();
            if (looks_spun(img, stop) != s.toObject().value("value").toBool()){
                wrong << QString("looks_spun(%1)").arg(describe(box));
            }
        }
        if (!wrong.isEmpty()){
            report << QString("FAILED: on the picture '%1' the port reads another way than the Python code: %2").arg(c.value("id").toString(), wrong.join(", "));
            failed++;
        }
    }

    //  the stories
    for (const QJsonValue& v : cases){
        const QJsonObject c = v.toObject();
        const QString what = play(c, start);
        if (!what.isEmpty()){
            report << QString("FAILED: the story '%1' went another way: %2").arg(c.value("id").toString(), what);
            failed++;
        }
    }
    report << QString("map: %1 pictures of the readers and %2 stories played, %3 went another way").arg(readers.size()).arg(cases.size()).arg(failed);
    return failed;
}


}
}
}
}
