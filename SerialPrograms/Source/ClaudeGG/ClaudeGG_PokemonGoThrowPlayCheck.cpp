/*  Claude GG Pokemon GO Throw Play Check (the throw of a ball, played on the stories of the Python code)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The file of Mobile/tools/make_throwplay_golden.py holds little stories of throw_touch, throw_ball, humanize, aim, ring_track and
 *  watch_flight of gamebot.py, played on a pretend phone with a pretend clock: for every call the events in the order in which they
 *  happened.  What the code was GIVEN: the screenshots and the pictures of the live video (drawn here as the file says), the boxes of the
 *  detector, the answers of the throw predictor, the random numbers, what the commands for the phone wrote and how long they took.
 *  What it DID: the commands for the phone, the waits, the log lines, the pictures that are kept, what was written down, and at the end of
 *  every call what it returned (or raised) and what it remembers.  The host here gives the port the same, one after the other, and says
 *  where the port does something else: the first event that differs ends that story.
 *
 */

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <opencv2/imgproc.hpp>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include "ClaudeGG_PokemonGoThrowPlay.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Throw{

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
    }else if (value.isNull()){
        text = "none";
    }else{
        text = value.toVariant().toString();
    }
    if (text.size() > 300){
        text = text.left(300) + "...";
    }
    return text;
}

//  round(x, 6) of Python (what the stories hold the numbers as).
double round6(double x){
    char buffer[512];
    std::snprintf(buffer, sizeof(buffer), "%.6f", x);
    return std::strtod(buffer, nullptr);
}
QJsonValue num(double x){
    return QJsonValue(round6(x));
}
QJsonValue optional_num(const std::optional<double>& x){
    return x.has_value() ? num(*x) : QJsonValue(QJsonValue::Null);
}
QJsonValue optional_int(const std::optional<int>& x){
    return x.has_value() ? QJsonValue(*x) : QJsonValue(QJsonValue::Null);
}

//  Are two values the same (numbers: exactly)?
bool same(const QJsonValue& a, const QJsonValue& b){
    if (a.isDouble() && b.isDouble()){
        return a.toDouble() == b.toDouble();
    }
    if (a.isArray() && b.isArray()){
        const QJsonArray x = a.toArray();
        const QJsonArray y = b.toArray();
        if (x.size() != y.size()){
            return false;
        }
        for (qsizetype i = 0; i < x.size(); i++){
            if (!same(x.at(i), y.at(i))){
                return false;
            }
        }
        return true;
    }
    if (a.isObject() && b.isObject()){
        const QJsonObject x = a.toObject();
        const QJsonObject y = b.toObject();
        if (x.size() != y.size()){
            return false;
        }
        for (auto it = x.begin(); it != x.end(); ++it){
            if (!y.contains(it.key()) || !same(it.value(), y.value(it.key()))){
                return false;
            }
        }
        return true;
    }
    return a == b;
}

//  repr() of a float, and str() of what a person chose (a text, yes or no, or a number).
QString py_str(const QJsonValue& v){
    if (v.isString()){
        return v.toString();
    }
    if (v.isBool()){
        return v.toBool() ? "True" : "False";
    }
    if (v.isDouble()){
        const double x = v.toDouble();
        if (x == std::floor(x) && std::fabs(x) < 1e15){
            return QString::number((long long)x);
        }
        return QString::number(x, 'g', 17);
    }
    return "None";
}

Detection detection_of(const QJsonArray& a){
    Detection d;
    d.label = a.at(0).toString().toStdString();
    d.score = a.at(1).toDouble();
    d.cx = a.at(2).toInt();
    d.cy = a.at(3).toInt();
    d.w = a.at(4).toInt();
    d.h = a.at(5).toInt();
    return d;
}
QJsonValue detection_json(const std::optional<Detection>& d){
    if (!d.has_value()){
        return QJsonValue(QJsonValue::Null);
    }
    return QJsonArray{QString::fromStdString(d->label), num(d->score), d->cx, d->cy, d->w, d->h};
}

//  The pictures that were drawn lately (drawing one takes a while, and the stories use the same ones again and again).
struct Scene{
    QByteArray key;
    cv::Mat img;
};
cv::Mat scene_of(std::vector<Scene>& cache, const QJsonArray& ops){
    const QByteArray key = QJsonDocument(ops).toJson(QJsonDocument::Compact);
    for (size_t i = 0; i < cache.size(); i++){
        if (cache[i].key == key){
            const Scene found = cache[i];
            cache.erase(cache.begin() + (std::ptrdiff_t)i);
            cache.push_back(found);
            return found.img;
        }
    }
    Scene made;
    made.key = key;
    made.img = make_check_scene(ops);
    cache.push_back(made);
    if (cache.size() > 12){
        cache.erase(cache.begin());
    }
    return made.img;
}


class Replay : public Host{
public:
    Replay(const QJsonObject& test_case, double start, double mono, std::vector<Scene>& cache)
        : m_spec(test_case.value("spec").toObject())
        , m_events(test_case.value("events").toArray())
        , m_frames(m_spec.value("frames").toArray())
        , m_settings(m_spec.value("settings").toObject())
        , m_cache(cache)
        , m_mono(mono)
        , m_t(start)
    {
        const QJsonArray screen = m_spec.value("screen").toArray();
        if (screen.size() == 2){
            m_screen_w = screen.at(0).toInt();
            m_screen_h = screen.at(1).toInt();
        }
        const QJsonArray input = m_spec.value("input").toArray();
        for (const QJsonValue& v : input){
            m_input << v.toString();
        }
        if (m_input.isEmpty()){
            m_input << "input";
        }
        m_live_age = m_spec.value("live_age").toDouble(0.12);
        m_swipe_seconds = m_spec.value("swipe_seconds").toDouble(0.0);
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
    void same_time(const QJsonArray& event, const QString& doing){
        if (std::abs(event.at(1).toDouble() - m_t) > 1e-6){
            fail(QString("the Python code did %1 at the time %2, the port: %3 at %4")
                .arg(describe(event), QString::number(event.at(1).toDouble(), 'f', 6), doing, QString::number(m_t, 'f', 6)));
        }
    }
    //  The next event, which has to be of this kind (and at this time).
    QJsonArray out(const char* kind, const QString& doing){
        const QJsonArray event = peek(doing);
        if (event.at(0).toString() != kind){
            fail("the Python code did " + describe(event) + ", the port: " + doing);
        }
        same_time(event, doing);
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
    //  A call starts: what the person chose changes, time passes, the video runs or not.  The call event comes first.
    void begin(const QJsonObject& call){
        if (call.contains("settings")){
            const QJsonObject o = call.value("settings").toObject();
            for (auto it = o.begin(); it != o.end(); ++it){
                m_settings[it.key()] = it.value();
            }
        }
        if (call.contains("advance")){
            m_t += call.value("advance").toDouble();
        }
        m_live = call.contains("live") ? call.value("live").toBool() : m_spec.value("live").toBool();
        const QJsonArray event = out("call", "the call " + call.value("fn").toString());
        if (event.at(2).toString() != call.value("fn").toString()){
            fail("the call differs: the Python code did " + describe(event));
        }
    }
    //  The picture of a frame of the story: the same one every time it is asked for (the code tells pictures apart by their identity).
    cv::Mat picture(int frame){
        auto it = m_pics.find(frame);
        if (it == m_pics.end()){
            if (frame < 0 || frame >= m_frames.size() || !m_frames.at(frame).isObject()){
                fail(QString("the story has no picture %1").arg(frame));
            }
            it = m_pics.emplace(frame, scene_of(m_cache, m_frames.at(frame).toObject().value("pic").toArray()).clone()).first;
        }
        return it->second;
    }
    int index_of(const cv::Mat& img){
        for (const std::pair<const int, cv::Mat>& one : m_pics){
            if (one.second.data == img.data){
                return one.first;
            }
        }
        fail("the port gave a picture that is none of the story's");
    }
    //  The end of a call: what it returned, or what it threw; then what the code remembers.
    void result(const QJsonValue& got){
        const QJsonArray event = out("result", "the end of the call");
        if (!same(event.at(2), got)){
            fail("the call returned something else: the Python code " + describe(event.at(2)) + ", the port: " + describe(got));
        }
    }
    void raised(const QString& what){
        const QJsonArray event = peek("the end of the call (it threw)");
        if (event.at(0).toString() != "raised"){
            fail("the port threw '" + what + "', the Python code did " + describe(event));
        }
        same_time(event, "the end of the call (it threw)");
        index++;
        if (event.at(2).toString() != what){
            fail("the port threw '" + what + "', the Python code '" + event.at(2).toString() + "'");
        }
    }
    void state(const QJsonObject& got){
        const QJsonArray event = out("state", "the state at the end of the call");
        if (!same(event.at(2), got)){
            fail("what the code remembers differs: the Python code " + describe(event.at(2)) + ", the port: " + describe(got));
        }
    }
    void finish_story(){
        if (!done()){
            fail("the Python code did more: " + describe(m_events.at(index)));
        }
    }

    const QJsonObject& spec() const{ return m_spec; }

    //  ---- Loop::Host
    double monotonic() override{ return m_t - m_mono; }
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
    cv::Mat screenshot() override{ fail("the throw took a screenshot at once"); }
    Loop::Stream* stream() override{ return nullptr; }
    std::unique_ptr<Loop::Tapper> make_tapper(Point, int) override{
        fail("the throw made a tapper of the fast taps");
    }
    bool on_map(const cv::Mat&) override{ fail("the throw asked whether the map is on the screen"); }
    Nav::Lines ocr_lines(const cv::Mat&, int, std::optional<int>, double) override{
        fail("the throw read lines of text");
    }
    QString ocr_line(const cv::Mat&, int) override{
        fail("the throw read a line of text");
    }
    bool give_up_enabled() override{ return false; }
    bool aim_enabled() override{ return false; }
    void aim_disabled() override{}
    QString league() override{ return QString(); }
    Fight::Known load_seen() override{ return Fight::Known(); }
    void save_seen(const Fight::Known&) override{ fail("the throw saved what was seen in a fight"); }
    std::map<QString, Minigame::Learned> load_minigames() override{ return std::map<QString, Minigame::Learned>(); }
    void save_minigames(const std::map<QString, Minigame::Learned>&) override{ fail("the throw saved what was learned of a little game"); }
    void save_picture(const QString& name, const cv::Mat& img) override{
        const QJsonArray event = out("save", "the picture " + name + " is kept");
        if (event.at(2).toString() != name || event.at(3).toInt() != index_of(img)){
            fail("the picture that is kept differs: the Python code kept " + describe(event) + ", the port: " + name + " of the picture " + QString::number(index_of(img)));
        }
    }
    void beat() override{ fail("the throw made a beat"); }
    bool stop() override{ fail("the throw asked whether the person stopped"); }
    bool threads() override{ return false; }

    //  ---- Flow::Host
    double wall() override{ return m_t; }
    void tap(int, int) override{ fail("the throw tapped"); }
    void swipe(int x1, int y1, int x2, int y2, int ms) override{
        const QString doing = QString("a swipe from (%1, %2) to (%3, %4) in %5 ms").arg(x1).arg(y1).arg(x2).arg(y2).arg(ms);
        const QJsonArray event = out("swipe", doing);
        if (event.at(2).toInt() != x1 || event.at(3).toInt() != y1 || event.at(4).toInt() != x2 || event.at(5).toInt() != y2 || event.at(6).toInt() != ms){
            fail("the swipe differs: the Python code did " + describe(event) + ", the port: " + doing);
        }
        m_t += m_swipe_seconds;
    }
    void back() override{ fail("the throw pressed BACK"); }
    std::pair<QString, double> screen_class(const cv::Mat&) override{ fail("the throw asked for the screen classifier"); }
    void restart_game() override{ fail("the throw restarted the game through the host of the walk"); }

    //  ---- Start::Host
    void stop_game() override{ fail("the throw closed the game"); }
    void start_game() override{ fail("the throw started the game"); }
    Start::Launch start_state() override{ fail("the throw asked about the start of the game"); }
    void start_end() override{ fail("the throw ended the start of the game"); }

    //  ---- Map::Host
    cv::Mat quick_screenshot() override{ return shot("quick"); }
    void swipe_async(int, int, int, int, int) override{ fail("the throw swiped without waiting"); }
    double uniform(double lo, double hi) override{
        const QJsonArray event = out("random", QString("a random number between %1 and %2").arg(lo).arg(hi));
        if (event.at(2).toString() != "uniform" || std::abs(event.at(3).toDouble() - lo) > 1e-9 || std::abs(event.at(4).toDouble() - hi) > 1e-9){
            fail(QString("the random number differs: the Python code drew %1, the port: uniform(%2, %3)").arg(describe(event)).arg(lo).arg(hi));
        }
        return event.at(5).toDouble();
    }
    double unit() override{
        const QJsonArray event = out("random", "a random number between 0 and 1");
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
        return v.isBool() ? v.toBool() : (v.isDouble() && v.toDouble() != 0) || (v.isString() && !v.toString().isEmpty());
    }
    bool wanted(const QString&) override{ fail("the throw asked what is switched on"); }
    QString count(const QString&) override{ fail("the throw counted the day"); }
    void gifts_round() override{ fail("the throw opened the gifts"); }
    void check_menu_full() override{ fail("the throw checked the full bag in the menu"); }
    void check_all_full() override{ fail("the throw checked what can be full"); }
    int clean_bag() override{ fail("the throw cleaned the bag"); }
    void bag_to_map() override{ fail("the throw went back to the map from the bag"); }
    void resume_spin_later() override{ fail("the throw switched the spinning on again later"); }

    //  ---- Throw::Host
    QStringList input_cmd() override{ return m_input; }
    Point to_real(double x, double y) override{
        return Point{(int)std::nearbyint(x * m_screen_w / REF_W), (int)std::nearbyint(y * m_screen_h / REF_H)};
    }
    double gauss(double mu, double sigma) override{
        const QJsonArray event = out("random", QString("a random number (gauss %1, %2)").arg(mu).arg(sigma));
        if (event.at(2).toString() != "gauss" || std::abs(event.at(3).toDouble() - mu) > 1e-9 || std::abs(event.at(4).toDouble() - sigma) > 1e-9){
            fail(QString("the random number differs: the Python code drew %1, the port: gauss(%2, %3)").arg(describe(event)).arg(mu).arg(sigma));
        }
        return event.at(5).toDouble();
    }
    QString setting_text(const QString& key, const QString& fallback) override{
        const QJsonValue v = m_settings.value(key);
        return v.isUndefined() ? fallback : py_str(v);
    }
    bool quick_live() override{ return m_quick_live; }
    double quick_time() override{ return m_quick_t; }
    bool live_on() override{ return m_live; }
    std::vector<std::pair<double, cv::Mat>> live_frames(double seconds, double every) override{
        std::vector<std::pair<double, cv::Mat>> got;
        if (!m_live){
            return got;
        }
        const QJsonArray event = input("live_frames", QString("the pictures of the live video (%1 s, every %2 s)").arg(seconds).arg(every));
        if (std::abs(event.at(2).toDouble() - seconds) > 1e-9 || std::abs(event.at(3).toDouble() - every) > 1e-9){
            fail(QString("the live video differs: the Python code asked %1, the port: %2 s every %3 s").arg(describe(event)).arg(seconds).arg(every));
        }
        for (const QJsonValue& v : event.at(4).toArray()){
            const QJsonArray one = v.toArray();
            got.emplace_back(one.at(0).toDouble(), picture(one.at(1).toInt()));
        }
        return got;
    }
    Later screenshot_later() override{
        const QJsonArray event = peek("a screenshot that is taken meanwhile");
        if (event.at(0).toString() == "shot_error"){
            same_time(event, "a screenshot that is taken meanwhile");
            index++;
            const std::string text = event.at(2).toString().toStdString();
            return [text]() -> cv::Mat{ throw std::runtime_error(text); };
        }
        const cv::Mat img = shot("real");
        return [img]{ return img; };
    }
    int adb_start(const QStringList& argv, bool) override{
        const QString doing = "the command " + argv.join(" ");
        const QJsonArray event = out("popen", doing);
        if (!same(event.at(2), QJsonArray::fromStringList(argv))){
            fail("the command differs: the Python code did " + describe(event) + ", the port: " + doing);
        }
        return m_handles++;
    }
    QString adb_communicate(int) override{
        const QJsonArray event = input("communicate", "the end of a command that holds the finger");
        return event.at(2).toString();
    }
    void adb_wait(int) override{
        input("wait", "the end of a command that holds the ball");
    }
    void adb(const QStringList& args) override{
        const QString doing = "the command adb " + args.join(" ");
        const QJsonArray event = input("adb", doing);
        if (!same(event.at(2), QJsonArray::fromStringList(args))){
            fail("the command differs: the Python code did " + describe(event) + ", the port: " + doing);
        }
        if (event.at(3).isString()){
            throw std::runtime_error(event.at(3).toString().toStdString());
        }
    }
    std::vector<Detection> encounter_objects(const cv::Mat& img) override{
        const int frame = index_of(img);
        const QJsonArray event = input("objects", QString("a look of the detector at the picture %1").arg(frame));
        if (event.at(2).toInt() != frame){
            fail("the look differs: the Python code looked at " + describe(event) + ", the port at the picture " + QString::number(frame));
        }
        std::vector<Detection> found;
        for (const QJsonValue& v : event.at(3).toArray()){
            found.push_back(detection_of(v.toArray()));
        }
        return found;
    }
    std::pair<double, double> throw_params(double cx, double cy, double w, double h) override{
        const QString doing = QString("the throw predictor for (%1, %2, %3, %4)").arg(cx).arg(cy).arg(w).arg(h);
        const QJsonArray event = out("params", doing);
        if (event.at(2).toDouble() != cx || event.at(3).toDouble() != cy || event.at(4).toDouble() != w || event.at(5).toDouble() != h){
            fail("the question differs: the Python code asked " + describe(event) + ", the port: " + doing);
        }
        return {event.at(6).toDouble(), event.at(7).toDouble()};
    }
    void save_cal(const Cal& cal) override{
        const QJsonArray event = out("save_cal", "what was learned is written down");
        const QJsonObject got = cal_json(cal, true);
        if (!same(event.at(2), got)){
            fail("what is written down differs: the Python code " + describe(event.at(2)) + ", the port: " + describe(got));
        }
    }

private:
    //  A screenshot: the Python code was given this frame (and a quick one tells whether it came from the live video, and when).
    cv::Mat shot(const char* kind){
        const QString doing = QString("a %1 screenshot").arg(QString(kind));
        const QJsonArray event = peek(doing);
        if (event.at(0).toString() == "shot_error"){
            same_time(event, doing);
            index++;
            throw std::runtime_error(event.at(2).toString().toStdString());
        }
        const QJsonArray taken = input("shot", doing);
        if (taken.at(3).toString() != kind){
            fail("the Python code took " + describe(taken) + ", the port: " + doing);
        }
        if (QString(kind) == "quick"){
            m_quick_live = taken.at(4).toBool();
            m_quick_t = m_quick_live ? monotonic() - m_live_age : monotonic();
        }
        return picture(taken.at(2).toInt());
    }

    const QJsonObject m_spec;
    const QJsonArray m_events;
    const QJsonArray m_frames;
    QJsonObject m_settings;
    std::vector<Scene>& m_cache;
    std::map<int, cv::Mat> m_pics;
    QStringList m_input;
    int m_screen_w = REF_W;
    int m_screen_h = REF_H;
    double m_live_age = 0.12;
    const double m_mono;                    //  how far the monotonic clock runs behind the clock of the day
    double m_swipe_seconds = 0.0;
    bool m_live = false;
    bool m_quick_live = false;
    double m_quick_t = 0.0;
    int m_handles = 0;
    double m_t;
};


//  What the code remembers, as the stories hold it.
QJsonObject memory_json(const Memory& memory){
    QJsonObject out;
    out.insert("cal", cal_json(memory.cal, true));
    out.insert("ring_shots", QJsonObject{{"n", memory.ring_shots}});
    out.insert("throw_info", QJsonObject{{"hit", memory.hit.has_value() ? QJsonValue(*memory.hit) : QJsonValue(QJsonValue::Null)}});
    out.insert("throw_stats", QJsonObject{{"n", memory.stats_n}, {"on", memory.stats_on}});
    return out;
}

//  What the story starts with (restore() of the generator): the numbers of the start, with some of them changed.
void apply_init(Memory& memory, const QJsonObject& init){
    const QJsonObject cal = init.value("cal").toObject();
    const auto rows = [](const QJsonValue& value){
        std::vector<std::array<double, 3>> out;
        for (const QJsonValue& v : value.toArray()){
            const QJsonArray row = v.toArray();
            out.push_back({row.at(0).toDouble(), row.at(1).toDouble(), row.at(2).toDouble()});
        }
        return out;
    };
    for (auto it = cal.begin(); it != cal.end(); ++it){
        const QString key = it.key();
        const QJsonValue v = it.value();
        if (key == "k"){
            memory.cal.k = v.toDouble();
        }else if (key == "c"){
            memory.cal.c = v.toDouble();
        }else if (key == "lat"){
            memory.cal.lat = v.toDouble();
        }else if (key == "rel"){
            memory.cal.rel = v.toDouble();
        }else if (key == "aim"){
            memory.cal.aim = v.toDouble();
        }else if (key == "c_live"){
            memory.cal.c_live = v.toDouble();
        }else if (key == "obs"){
            memory.cal.obs = rows(v);
        }else if (key == "obs_live"){
            memory.cal.obs_live = rows(v);
        }else if (key == "no_curve"){
            memory.cal.no_curve = v.toBool();
        }
    }
    if (init.contains("ring_shots")){
        memory.ring_shots = init.value("ring_shots").toObject().value("n").toInt();
    }
    if (init.contains("throw_stats")){
        memory.stats_n = init.value("throw_stats").toObject().value("n").toInt();
        memory.stats_on = init.value("throw_stats").toObject().value("on").toInt();
    }
    if (init.contains("throw_info") && init.value("throw_info").toObject().value("hit").isBool()){
        memory.hit = init.value("throw_info").toObject().value("hit").toBool();
    }
}

//  One call of a story; returns what it returned, as the stories hold it.
QJsonValue run_call(Replay& host, Memory& memory, const QJsonObject& call){
    const QString fn = call.value("fn").toString();
    if (fn == "throw_touch"){
        std::optional<double> target;
        if (call.value("target").isDouble()){
            target = call.value("target").toDouble();
        }
        const std::optional<double> t_rel = throw_touch(host, memory, call.value("curve").toBool(), target, call.value("name").toString(),
                                                        call.value("aim_dx").toInt(0), call.value("power").toDouble(1.0));
        return optional_num(t_rel);
    }
    if (fn == "throw_ball"){
        return num(throw_ball(host, memory));
    }
    if (fn == "humanize"){
        const Humanized h = humanize(host, call.value("name").toString(), call.value("curve").toBool());
        return QJsonArray{h.target_name, optional_num(h.target), h.curve, h.aim_dx, num(h.power), num(h.pause)};
    }
    if (fn == "aim"){
        return detection_json(aim(host));
    }
    if (fn == "ring_track"){
        std::optional<double> t_first;
        if (call.value("t_first").isDouble()){
            t_first = call.value("t_first").toDouble();
        }
        const Track track = ring_track(host, host.picture(call.value("first").toInt()), t_first);
        QJsonArray points;
        for (const std::pair<double, double>& p : track.points){
            points.append(QJsonArray{num(p.first), num(p.second)});
        }
        return QJsonArray{points, detection_json(track.box)};
    }
    if (fn == "watch_flight"){
        std::optional<Detection> ring;
        if (call.value("ring").isArray()){
            ring = detection_of(call.value("ring").toArray());
        }
        const Flight flight = watch_flight(host, host.picture(call.value("before").toInt()), ring);
        return QJsonArray{flight.first.empty() ? QJsonValue(QJsonValue::Null) : QJsonValue(host.index_of(flight.first)), optional_int(flight.land)};
    }
    host.fail("the story asks for the call " + fn + ", which the check does not know");
}

//  One story; returns an empty text when the port did the same, or what went another way.
QString play(const QJsonObject& test_case, double start, double mono, std::vector<Scene>& cache){
    Replay host(test_case, start, mono, cache);
    Memory memory;
    try{
        apply_init(memory, host.spec().value("init").toObject());
        for (const QJsonValue& v : host.spec().value("calls").toArray()){
            const QJsonObject call = v.toObject();
            host.begin(call);
            QJsonValue result;
            QString what;
            bool threw = false;
            try{
                result = run_call(host, memory, call);
            }catch (const std::exception& e){
                threw = true;
                what = QString::fromUtf8(e.what());
            }
            if (threw){
                host.raised(what);
            }else{
                host.result(result);
            }
            host.state(memory_json(memory));
        }
        host.finish_story();
    }catch (const Abort&){
    }
    return host.failed ? host.message : QString();
}

}


//  An array of arrays.  (QJsonArray{QJsonArray{...}} with a single row is, with some compilers - MSVC - a copy of that row and not an array
//  that holds it: the Windows build made the file of what was learned look different from what the check wanted.)
static QJsonArray rows_of(std::initializer_list<QJsonArray> list){
    QJsonArray out;
    for (const QJsonArray& row : list){
        out.append(row);
    }
    return out;
}

//  The file of what was learned (save_cal() and load_cal() of gamebot.py): not in the stories, so held to what Python writes and reads here.
static int check_cal_file(QStringList& report){
    int failed = 0;
    const auto expect = [&](bool ok, const QString& what){
        if (!ok){
            report << "FAILED: the file of what was learned: " + what;
            failed++;
        }
    };
    Cal cal;
    cal.k = 0.61;
    cal.c = 0.12;
    cal.lat = 47.5;
    cal.rel = 0.28;
    cal.aim = -130.5;
    cal.obs = {{0.9, 1.0, 0.5}, {0.7, 1.2, 0.3}};
    cal.c_live = -0.08;
    cal.obs_live = {{0.6, 1.1, 0.2}};
    //  json.dump(dict(cal, v=CAL_VERSION)): the numbers, and the version; no_curve only when it is set.
    QJsonObject want{
        {"k", 0.61}, {"c", 0.12}, {"lat", 47.5}, {"rel", 0.28}, {"aim", -130.5},
        {"obs", rows_of({{0.9, 1.0, 0.5}, {0.7, 1.2, 0.3}})},
        {"c_live", -0.08}, {"obs_live", rows_of({{0.6, 1.1, 0.2}})}, {"v", 5},
    };
    expect(same(cal_file(cal), want), "what is written is " + describe(cal_file(cal)));
    cal.no_curve = true;
    want.insert("no_curve", true);
    expect(same(cal_file(cal), want), "what is written when the phone has no single touch events is " + describe(cal_file(cal)));
    expect(same(cal_json(cal, false).value("aim"), -130.5) && !cal_json(cal, false).contains("v"), "the numbers without the version");
    Cal odd;
    odd.aim = 0.1234567;
    odd.obs = {{0.12345678, 1.0, 0.5}};
    expect(same(cal_json(odd, true).value("aim"), 0.123457) && same(cal_json(odd, true).value("obs"), rows_of({{0.123457, 1.0, 0.5}})),
           "the numbers rounded to six places");
    expect(!cal_json(odd, true).contains("no_curve"), "no_curve is only there when it is set");
    expect(same(cal_json(odd, false).value("aim"), 0.1234567) && same(cal_json(odd, false).value("obs"), rows_of({{0.12345678, 1.0, 0.5}})),
           "the numbers of the file are not rounded (the numbers of the stories are)");

    //  load_cal(): values of the right version come in, no_curve does not (it is not in the cal that is there to be filled in).
    Cal loaded;
    expect(cal_load(loaded, want), "a file of the right version is taken");
    expect(loaded.k == 0.61 && loaded.c == 0.12 && loaded.lat == 47.5 && loaded.rel == 0.28 && loaded.aim == -130.5 && loaded.c_live == -0.08,
           "the numbers that are read");
    expect(same(cal_json(loaded, false).value("obs"), want.value("obs")) && same(cal_json(loaded, false).value("obs_live"), want.value("obs_live")),
           "the throws that are read");
    expect(!loaded.no_curve, "no_curve is not read");
    Cal old;
    QJsonObject older = want;
    older.insert("v", 4);
    expect(!cal_load(old, older) && old.k == Cal().k && old.obs.empty() && old.aim == 0.0, "a file of an older version is dropped");
    QJsonObject versionless = want;
    versionless.remove("v");
    expect(!cal_load(old, versionless) && old.k == Cal().k, "a file without a version is dropped");
    Cal part;
    expect(cal_load(part, QJsonObject{{"v", 5}, {"k", 0.7}, {"unknown", 1}}), "a file with some of the numbers is taken");
    expect(part.k == 0.7 && part.c == Cal().c && part.lat == Cal().lat && part.rel == Cal().rel && part.aim == Cal().aim && part.c_live == Cal().c_live
           && part.obs.empty() && part.obs_live.empty(), "and the rest stays as it was");
    Cal kept = cal;
    expect(cal_load(kept, QJsonObject{{"v", 5}, {"aim", 12.0}}) && kept.aim == 12.0 && kept.k == 0.61 && kept.no_curve && kept.obs.size() == 2,
           "numbers that the file does not have are kept");
    return failed;
}

int run_throwplay_checks(const QString& golden, QStringList& report, bool stop_at_first){
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the stories of the throw are not there: " + golden;
        return 1;
    }
    const QJsonObject root = QJsonDocument::fromJson(qUncompress(file.readAll())).object();
    const QJsonArray cases = root.value("cases").toArray();
    const double start = root.value("start").toDouble(1000.0);
    const double mono = root.value("mono").toDouble(0.0);
    int failed = 0;
    std::vector<Scene> cache;
    for (const QJsonValue& v : cases){
        const QJsonObject test_case = v.toObject();
        const QString what = play(test_case, start, mono, cache);
        if (!what.isEmpty()){
            report << QString("FAILED: in the story '%1' the port does something else than the Python code: %2").arg(test_case.value("id").toString(), what);
            failed++;
            if (stop_at_first){
                return failed;
            }
        }
    }
    if (cases.isEmpty()){
        report << "FAILED: the file of the throw has no stories";
        return failed + 1;
    }
    failed += check_cal_file(report);
    report << QString("throw play: %1 stories played and the file of what was learned, %2 went another way").arg(cases.size()).arg(failed);
    return failed;
}


}
}
}
}
