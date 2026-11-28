/*  Claude GG Pokemon GO Story (a pretend phone for the checks of the Pokémon GO bot)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  For the checks only.  The stories of the golden files (Mobile/tools/make_*_golden.py) are lists of calls, and for every call the EVENTS
 *  that the Python code made on a pretend phone with a pretend clock: what it was given (the screenshots, the answers of the detectors and of the
 *  text reader, the random numbers) and what it did (taps, waits, log lines, pictures that are kept), in order, each with the time of the
 *  pretend clock.  Story::Host is the pretend phone of the port: it answers the port from the events and says where the port does something else
 *  than the Python code did (the first event that differs ends the story, see Story::Host::fail()).
 *
 *  A check derives its own Replay from Story::Host and adds what its part of the bot needs (the seams of that part), and plays its calls on it.
 *  Everything that a part does not use is an error here: "the code did X, which the story does not have".
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoStory_H
#define PokemonAutomation_ClaudeGG_PokemonGoStory_H

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <optional>
#include <stdexcept>
#include <vector>
#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>
#include <QByteArray>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include <QString>
#include <QStringList>
#include "ClaudeGG_PokemonGoMap.h"
#include "ClaudeGG_PokemonGoThrow.h"

#ifdef _MSC_VER
//  A Replay derives from Story::Host and from the Host of the part that is checked, which both have the Host of the map as a virtual base: what
//  Story::Host answers for is what the Replay inherits "via dominance" (C4250), which is what it is for.
#pragma warning(disable: 4250)
#endif

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Story{

using Loop::Point;
using Models::Detection;


//  Thrown when the port went another way: ends the story (not a std::exception: the code must not take it for an error of the phone).
struct Abort{};


//  ---- small helpers

inline QString describe(const QJsonValue& value){
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
inline double round6(double x){
    char buffer[512];
    std::snprintf(buffer, sizeof(buffer), "%.6f", x);
    return std::strtod(buffer, nullptr);
}
inline QJsonValue num(double x){
    return QJsonValue(round6(x));
}
inline QJsonValue optional_num(const std::optional<double>& x){
    return x.has_value() ? num(*x) : QJsonValue(QJsonValue::Null);
}
inline QJsonValue optional_int(const std::optional<int>& x){
    return x.has_value() ? QJsonValue(*x) : QJsonValue(QJsonValue::Null);
}

//  Are two values the same (numbers: exactly)?
inline bool same(const QJsonValue& a, const QJsonValue& b){
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

inline Detection detection_of(const QJsonArray& a){
    Detection d;
    d.label = a.at(0).toString().toStdString();
    d.score = a.at(1).toDouble();
    d.cx = a.at(2).toInt();
    d.cy = a.at(3).toInt();
    d.w = a.at(4).toInt();
    d.h = a.at(5).toInt();
    return d;
}
inline QJsonValue detection_json(const std::optional<Detection>& d){
    if (!d.has_value()){
        return QJsonValue(QJsonValue::Null);
    }
    return QJsonArray{QString::fromStdString(d->label), num(d->score), d->cx, d->cy, d->w, d->h};
}

//  The mean of all the numbers of a picture (all channels): img.mean() of numpy.  (OpenCV does not draw or resize bit for bit as the
//  Python side does, so the means are held to each other with a tolerance of MEAN_TOLERANCE, not exactly.)
inline constexpr double MEAN_TOLERANCE = 0.6;
inline double mean_of(const cv::Mat& img){
    const cv::Scalar sum = cv::sum(img);
    double total = 0;
    for (int c = 0; c < img.channels(); c++){
        total += sum[c];
    }
    return total / ((double)img.rows * img.cols * img.channels());
}


//  ---- the pictures that were drawn lately (drawing one takes a while, and the stories use the same ones again and again)

struct Scene{
    QByteArray key;
    cv::Mat img;
};
inline cv::Mat scene_of(std::vector<Scene>& cache, const QJsonArray& ops){
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
    made.img = Throw::make_check_scene(ops);
    cache.push_back(made);
    if (cache.size() > 12){
        cache.erase(cache.begin());
    }
    return made.img;
}


//  ---- the pretend phone

class Host : public virtual Map::Host{
public:
    Host(const QJsonObject& test_case, double start, std::vector<Scene>& cache)
        : m_spec(test_case.value("spec").toObject())
        , m_events(test_case.value("events").toArray())
        , m_frames(m_spec.value("frames").toArray())
        , m_settings(m_spec.value("settings").toObject())
        , m_wanted(m_spec.value("wanted").toObject())
        , m_cache(cache)
        , m_t(start)
    {
        m_live = m_spec.value("live").toBool();
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
    //  An event that moves the clock (what the code was given, after it took its time): the code is given the time that it was given.
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
    //  A call starts: what the person chose changes, time passes.  The call event comes first.
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
    double now() const{ return m_t; }

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
        fail("the code made a tapper of the fast taps");
    }
    bool on_map(const cv::Mat&) override{ fail("the code asked whether the map is on the screen"); }
    Nav::Lines ocr_lines(const cv::Mat& img, int y0, std::optional<int> y1, double scale) override{
        const QJsonArray event = out("ocr", QString("a reading of lines (%1 x %2, from %3)").arg(img.cols).arg(img.rows).arg(y0));
        if (event.at(2).toInt() != img.rows || event.at(3).toInt() != img.cols || event.at(4).toInt() != y0
            || event.at(5).isNull() != !y1.has_value() || (y1.has_value() && event.at(5).toInt() != *y1)
            || std::abs(event.at(6).toDouble() - scale) > 1e-9){
            fail(QString("the reading differs: the Python code read %1, the port: %2 x %3 rows %4 to %5 scale %6")
                .arg(describe(event)).arg(img.cols).arg(img.rows).arg(y0).arg(y1.has_value() ? QString::number(*y1) : QString("end")).arg(scale));
        }
        if (std::abs(event.at(7).toDouble() - mean_of(img)) > MEAN_TOLERANCE){
            fail(QString("the picture that was read differs: its mean is %1 and the Python code read one of %2 (%3)")
                .arg(mean_of(img), 0, 'f', 2).arg(event.at(7).toDouble(), 0, 'f', 2).arg(describe(event)));
        }
        Nav::Lines lines;
        for (const QJsonValue& v : event.at(8).toArray()){
            const QJsonArray line = v.toArray();
            Nav::Line one;
            one.text = line.at(0).toString();
            one.x = line.at(1).toInt();
            one.y = line.at(2).toInt();
            for (const QJsonValue& w : line.at(3).toArray()){
                const QJsonArray word = w.toArray();
                one.words.push_back(Nav::Word{word.at(0).toString(), word.at(1).toInt(), word.at(2).toInt()});
            }
            lines.push_back(one);
        }
        return lines;
    }
    //  The strip of text that gamebot.ocr_text() reads (the stories hold it as "ocr_text": its size and mean, and the text it read).
    QString ocr_line(const cv::Mat& img, int) override{
        const QJsonArray event = out("ocr_text", QString("a reading of a strip of text (%1 x %2)").arg(img.cols).arg(img.rows));
        if (event.at(2).toInt() != img.rows || event.at(3).toInt() != img.cols){
            fail(QString("the reading differs: the Python code read %1, the port: %2 x %3").arg(describe(event)).arg(img.cols).arg(img.rows));
        }
        if (std::abs(event.at(4).toDouble() - mean_of(img)) > MEAN_TOLERANCE){
            fail(QString("the picture that was read differs: its mean is %1 and the Python code read one of %2 (%3)")
                .arg(mean_of(img), 0, 'f', 2).arg(event.at(4).toDouble(), 0, 'f', 2).arg(describe(event)));
        }
        return event.at(5).toString();
    }
    bool give_up_enabled() override{ return false; }
    bool aim_enabled() override{ return false; }
    void aim_disabled() override{}
    QString league() override{ return QString(); }
    Fight::Known load_seen() override{ return Fight::Known(); }
    void save_seen(const Fight::Known&) override{ fail("the code saved what was seen in a fight"); }
    std::map<QString, Minigame::Learned> load_minigames() override{ return std::map<QString, Minigame::Learned>(); }
    void save_minigames(const std::map<QString, Minigame::Learned>&) override{ fail("the code saved what was learned of a little game"); }
    void save_picture(const QString& name, const cv::Mat& img) override{
        const QJsonArray event = out("save", "the picture " + name + " is kept");
        if (event.at(2).toString() != name || event.at(3).toInt() != index_of(img)){
            fail("the picture that is kept differs: the Python code kept " + describe(event) + ", the port: " + name + " of the picture " + QString::number(index_of(img)));
        }
    }
    void beat() override{ out("beat", "a beat"); }
    bool stop() override{ fail("the code asked whether the person stopped"); }
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
    void swipe(int, int, int, int, int) override{ fail("the code swiped"); }
    void back() override{ out("back", "BACK"); }
    //  The screen classifier: it says what the frame of the picture says (Brain.screen()).
    std::pair<QString, double> screen_class(const cv::Mat& img) override{
        const int frame = index_of(img);
        const QString doing = QString("the screen classifier at the picture %1").arg(frame);
        const QJsonArray next = peek(doing);
        if (next.at(0).toString() == "screen_error"){                           //  the classifier failed
            m_t = next.at(1).toDouble();
            index++;
            throw std::runtime_error(next.at(3).toString().toStdString());
        }
        const QJsonArray event = input("screen", doing);
        if (event.at(2).toInt() != frame){
            fail("the look differs: the Python code classified " + describe(event) + ", the port the picture " + QString::number(frame));
        }
        return {event.at(3).toString(), event.at(4).toDouble()};
    }
    void restart_game() override{ fail("the code restarted the game through the host of the walk"); }

    //  ---- Start::Host
    void stop_game() override{ fail("the code closed the game"); }
    void start_game() override{ fail("the code started the game"); }
    Start::Launch start_state() override{ fail("the code asked about the start of the game"); }
    void start_end() override{ fail("the code ended the start of the game"); }

    //  ---- Map::Host
    cv::Mat quick_screenshot() override{ return shot("quick"); }
    void swipe_async(int, int, int, int, int) override{ fail("the code swiped without waiting"); }
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
    //  What is switched on in the web interface: on when the story does not say otherwise (the two that gamebot.py asks about while catching are off).
    bool wanted(const QString& key) override{
        const QJsonValue v = m_wanted.value(key);
        if (v.isUndefined()){
            return key != "spin_only_when_full" && key != "daily_cycle";
        }
        return v.toBool();
    }
    QString count(const QString& key) override{
        const QJsonArray event = input("day_count", "the count of the day (" + key + ")");
        if (event.at(2).toString() != key){
            fail("the count differs: the Python code counted " + describe(event) + ", the port: " + key);
        }
        return event.at(3).toString();
    }
    void gifts_round() override{ fail("the code opened the gifts"); }
    void check_menu_full() override{ fail("the code checked the full bag in the menu"); }
    void check_all_full() override{ fail("the code checked what can be full"); }
    int clean_bag() override{ fail("the code cleaned the bag"); }
    void bag_to_map() override{ fail("the code went back to the map from the bag"); }
    void resume_spin_later() override{ fail("the code switched the spinning on again later"); }

protected:
    //  A screenshot: the Python code was given this frame (and a quick one tells whether it came from the live video).
    cv::Mat shot(const char* kind){
        const QString doing = QString("a %1 screenshot").arg(QString(kind));
        const QJsonArray event = peek(doing);
        if (event.at(0).toString() == "shot_error"){
            m_t = event.at(1).toDouble();
            index++;
            throw std::runtime_error(event.at(3).toString().toStdString());
        }
        const QJsonArray taken = input("shot", doing);
        if (taken.at(3).toString() != kind){
            fail("the Python code took " + describe(taken) + ", the port: " + doing);
        }
        if (QString(kind) == "quick"){
            m_quick_live = taken.at(4).toBool();
        }
        return picture(taken.at(2).toInt());
    }
    bool quick_was_live() const{ return m_quick_live; }

    const QJsonObject m_spec;
    const QJsonArray m_events;
    const QJsonArray m_frames;
    QJsonObject m_settings;
    QJsonObject m_wanted;
    std::vector<Scene>& m_cache;
    std::map<int, cv::Mat> m_pics;
    bool m_live = false;
    bool m_quick_live = false;
    double m_t;
};


}
}
}
}

#endif
