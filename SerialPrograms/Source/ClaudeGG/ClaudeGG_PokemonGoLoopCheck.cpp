/*  Claude GG Pokemon GO Loop Check (the fight loop played on the fights of the Python one)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The file of Mobile/tools/make_loop_golden.py holds fights of the fight loop of gamebot.py as lists of events: what the
 *  loop was given (the pictures, what the text reader read, the answer of the check for the map) and what it did (taps,
 *  swipes, calls of the tapper and of the looker, lines of the log, sleeps, what it saved, what it returned).  The host
 *  here gives the port the same, one after the other, and says where the port does something else: the first event that
 *  differs ends that fight.
 *
 */

#include <cmath>
#include <map>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include "ClaudeGG_PokemonGoLoop.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Loop{

namespace{


//  Thrown when the port went another way: ends the fight (not a std::exception: the loop must not take it for an error of the phone).
struct Abort{};

class Replay;

double mean_of(const cv::Mat& img){
    const cv::Scalar sum = cv::sum(img);
    double total = 0;
    for (int c = 0; c < img.channels(); c++){
        total += sum[c];
    }
    return total / ((double)img.rows * img.cols * img.channels());
}

QString describe(const QJsonArray& event){
    QString text = QString::fromUtf8(QJsonDocument(event).toJson(QJsonDocument::Compact));
    if (text.size() > 300){
        text = text.left(300) + "...";
    }
    return text;
}

class ReplayStream : public Stream{
public:
    ReplayStream(Replay& replay) : m_replay(replay){}
    bool healthy() override{ return true; }
    bool starting() override{ return false; }
    bool wait_new(long long seq, double timeout, double not_before, long long& seq_out, double& t, cv::Mat& small) override;
    QString describe() override{ return "fake phone"; }
    void close() override{}
private:
    Replay& m_replay;
};

//  The thread of the tapper, without the thread: poll() is what it would have done in the time that went by (a swipe of the
//  little game when its planner has one, else a fast tap while it is on) - the Python recording does the same.
class ReplayTapper : public Tapper{
public:
    ReplayTapper(Replay& replay, Point xy, int ms) : m_replay(replay), m_xy(xy), m_ms(ms){}
    void go() override;
    void pause() override;
    void aim(const std::optional<Point>& xy) override;
    void sweep(const Planner& planner) override;
    void tap(int x, int y, int ms = 120) override;
    void touch(int how, int x, int y) override;
    int taps() const override{ return m_taps; }
    int swipes() const override{ return m_swipes; }
    void close() override{
        m_sweep = Planner();
        m_on = false;
    }
    void poll();

private:
    Replay& m_replay;
    Point m_xy;
    int m_ms;
    bool m_on = false;
    Planner m_sweep;
    std::optional<Point> m_aim;
    int m_taps = 0;
    int m_swipes = 0;
};

class Replay : public Host{
public:
    Replay(const QJsonObject& test_case, const QJsonObject& root, const QString& fixtures)
        : m_fixtures(fixtures)
        , m_spec(test_case.value("spec").toObject())
        , m_events(test_case.value("events").toArray())
        , m_t(root.value("start").toDouble())
    {}

    //  ---- the events
    bool failed = false;
    QString message;
    qsizetype index = 0;

    void fail(const QString& text){
        if (!failed){
            failed = true;
            message = QString("event %1: ").arg(index) + text;
        }
        throw Abort();
    }

    //  The next event, which has to be of this kind (and at this time).
    QJsonArray next(const char* kind, const QString& doing){
        if (failed){
            throw Abort();
        }
        if (index >= m_events.size()){
            fail("the port went on after the last event of the Python loop: " + doing);
        }
        const QJsonArray event = m_events.at(index).toArray();
        if (event.at(0).toString() != kind){
            fail("the Python loop did " + describe(event) + ", the port: " + doing);
        }
        if (std::abs(event.at(1).toDouble() - m_t) > 1e-6){
            fail(QString("the Python loop did %1 at the time %2, the port: %3 at %4").arg(describe(event), QString::number(event.at(1).toDouble(), 'f', 6), doing, QString::number(m_t, 'f', 6)));
        }
        index++;
        return event;
    }
    //  An event that the loop does (nothing to give back): after a failure it is left alone.
    QJsonArray out(const char* kind, const QString& doing){
        if (failed){
            throw Abort();
        }
        return next(kind, doing);
    }
    //  An event that moves the clock: the loop is given the time that it was given.
    QJsonArray input(const char* kind, const QString& doing){
        if (failed){
            throw Abort();
        }
        if (index >= m_events.size()){
            fail("the port went on after the last event of the Python loop: " + doing);
        }
        const QJsonArray event = m_events.at(index).toArray();
        if (event.at(0).toString() != kind){
            fail("the Python loop did " + describe(event) + ", the port: " + doing);
        }
        m_t = event.at(1).toDouble();
        index++;
        return event;
    }

    //  ---- the numbers of the event compared
    void same(const QJsonArray& event, int at, double value, const QString& what){
        if (std::abs(event.at(at).toDouble() - value) > 1e-6){
            fail(QString("%1 differs: the Python loop did %2, the port: %3").arg(what, describe(event), QString::number(value, 'f', 6)));
        }
    }

    cv::Mat picture(const QString& name, int w, int h){
        const QString key = QString("%1 %2x%3").arg(name).arg(w).arg(h);
        const auto found = m_pictures.find(key);
        if (found != m_pictures.end()){
            return found->second;
        }
        QString file = name;
        const bool exit = file.endsWith("+exit");     //  (the question 'Exit the Trainer Battle?', drawn over the picture)
        if (exit){
            file.chop(5);
        }
        const cv::Mat raw = cv::imread((m_fixtures + "/" + file + ".jpg").toStdString());
        if (raw.empty()){
            fail("the picture is not there: " + file);
        }
        cv::Mat img;
        cv::resize(raw, img, cv::Size(w, h), 0, 0, cv::INTER_AREA);
        if (exit){
            cv::rectangle(img, cv::Point((int)(0.08 * w), (int)(0.30 * h)), cv::Point((int)(0.92 * w), (int)(0.72 * h)), cv::Scalar(255, 255, 255), cv::FILLED);
            cv::rectangle(img, cv::Point((int)(0.27 * w), (int)(0.49 * h)), cv::Point((int)(0.73 * w), (int)(0.55 * h)), cv::Scalar(110, 205, 120), cv::FILLED);
        }
        m_pictures[key] = img;
        return img;
    }

    //  ---- the Host
    double monotonic() override{ return m_t; }
    void sleep(double seconds) override{
        const QJsonArray event = out("sleep", QString("sleep(%1)").arg(seconds));
        same(event, 2, seconds, "the sleep");
        m_t += seconds;
    }
    void log(const QString& text) override{
        const QJsonArray event = out("log", "the log line: " + text);
        if (event.at(2).toString() != text){
            fail("the log line differs: the Python loop wrote '" + event.at(2).toString() + "', the port: '" + text + "'");
        }
    }
    cv::Mat screenshot() override{
        const QJsonArray event = input("screenshot", "a screenshot");
        const cv::Mat img = picture(event.at(2).toString(), REF_W, REF_H);
        if (m_tapper != nullptr){
            m_tapper->poll();
        }
        return img;
    }
    Stream* stream() override{
        if (!m_spec.value("video").toBool()){
            return nullptr;
        }
        return &m_stream;
    }
    std::unique_ptr<Tapper> make_tapper(Point fast, int ms) override{
        std::unique_ptr<ReplayTapper> tapper = std::make_unique<ReplayTapper>(*this, fast, ms);
        m_tapper = tapper.get();
        return tapper;
    }
    bool on_map(const cv::Mat&) override{
        const QJsonArray event = out("on_map", "the check for the map");
        return event.at(2).toBool();
    }
    Vision::Seen features(const cv::Mat& small) override{
        Vision::Seen s = Vision::features(small);
        if (m_spec.value("patch").toString() == "no_hud"){      //  (the story in which the name boxes are never recognised)
            s.hud = false;
            s.ready = {false, false};
            s.done = Vision::done_button(small);
            s.get_ready = false;
            s.balls.reset();
        }
        return s;
    }
    std::optional<std::pair<bool, QString>> hopeless(Fight::Fight& fight, int foes) override{
        if (m_spec.value("patch").toString() != "one_vs_two"){
            return std::nullopt;
        }
        //  (the story of the test that tells the fight it is lost when its last Pokémon is against two)
        return std::make_pair(fight.alive().size() == 1 && foes == 2, QString("Lanturn is our last Pokémon and loses (told by the test)"));
    }
    Nav::Lines ocr_lines(const cv::Mat& img, int y0, std::optional<int> y1, double scale) override{
        const QJsonArray event = out("ocr", QString("a reading of lines (%1 x %2, from %3)").arg(img.cols).arg(img.rows).arg(y0));
        if (event.at(2).toInt() != img.rows || event.at(3).toInt() != img.cols || event.at(4).toInt() != y0
            || event.at(5).isNull() != !y1.has_value() || (y1.has_value() && event.at(5).toInt() != *y1)
            || std::abs(event.at(6).toDouble() - scale) > 1e-9){
            fail(QString("the reading differs: the Python loop read %1, the port: %2 x %3 rows %4 to %5 scale %6")
                .arg(describe(event)).arg(img.cols).arg(img.rows).arg(y0).arg(y1.has_value() ? QString::number(*y1) : QString("end")).arg(scale));
        }
        if (std::abs(event.at(7).toDouble() - mean_of(img)) > 0.6){
            fail(QString("the picture that was read differs: its mean is %1 and the Python loop read one of %2 (%3)")
                .arg(mean_of(img), 0, 'f', 2).arg(event.at(7).toDouble(), 0, 'f', 2).arg(describe(event)));
        }
        Nav::Lines lines;
        for (const QJsonValue& v : event.at(8).toArray()){
            const QJsonArray line = v.toArray();
            Nav::Line out_line;
            out_line.text = line.at(0).toString();
            out_line.x = line.at(1).toInt();
            out_line.y = line.at(2).toInt();
            for (const QJsonValue& w : line.at(3).toArray()){
                const QJsonArray word = w.toArray();
                out_line.words.push_back(Nav::Word{word.at(0).toString(), word.at(1).toInt(), word.at(2).toInt()});
            }
            lines.push_back(out_line);
        }
        return lines;
    }
    QString ocr_line(const cv::Mat& img, int lines) override{
        const QJsonArray event = out("ocr_line", QString("a reading of one line (%1 x %2)").arg(img.cols).arg(img.rows));
        if (event.at(2).toInt() != img.rows || event.at(3).toInt() != img.cols || event.at(4).toInt() != lines){
            fail(QString("the reading differs: the Python loop read %1, the port: %2 x %3, %4 line(s)").arg(describe(event)).arg(img.cols).arg(img.rows).arg(lines));
        }
        if (std::abs(event.at(5).toDouble() - mean_of(img)) > 0.6){
            fail(QString("the picture that was read differs: its mean is %1 and the Python loop read one of %2 (%3)")
                .arg(mean_of(img), 0, 'f', 2).arg(event.at(5).toDouble(), 0, 'f', 2).arg(describe(event)));
        }
        return event.at(6).toString();
    }
    bool give_up_enabled() override{ return m_spec.value("give_up").toBool(); }
    bool aim_enabled() override{ return m_spec.value("aim").toBool(); }
    void aim_disabled() override{}
    QString league() override{ return m_spec.value("league").toString(); }
    Fight::Known load_seen() override{
        Fight::Known known;
        for (const QJsonValue& v : m_spec.value("seen").toArray()){
            const QJsonArray entry = v.toArray();
            Fight::Counts counts;
            for (const QJsonValue& c : entry.at(1).toArray()){
                counts.push_back({c.toArray().at(0).toString(), c.toArray().at(1).toInt()});
            }
            known.push_back({entry.at(0).toString(), counts});
        }
        return known;
    }
    void save_seen(const Fight::Known& known) override{
        const QJsonArray event = out("save_seen", "what was seen in this fight is saved");
        const QJsonObject want = event.at(2).toObject();
        if ((size_t)want.size() != known.size()){
            fail(QString("what was seen differs: the Python loop saved %1, the port saved %2 species").arg(describe(event)).arg(known.size()));
        }
        for (const auto& species : known){
            const QJsonObject moves = want.value(species.first).toObject();
            if ((size_t)moves.size() != species.second.size()){
                fail("what was seen of " + species.first + " differs: " + describe(event));
            }
            for (const auto& move : species.second){
                if (moves.value(move.first).toInt(-1) != move.second){
                    fail("what was seen of " + species.first + " differs: " + describe(event));
                }
            }
        }
    }
    std::map<QString, Minigame::Learned> load_minigames() override{
        std::map<QString, Minigame::Learned> learned;
        const QJsonObject all = m_spec.value("minigames").toObject();
        for (auto it = all.begin(); it != all.end(); ++it){
            Minigame::Learned l;
            auto lines = [](const QJsonValue& value){
                std::vector<Minigame::Line> out_lines;
                for (const QJsonValue& v : value.toArray()){
                    const QJsonArray a = v.toArray();
                    out_lines.push_back(Minigame::Line{a.at(0).toDouble(), a.at(1).toDouble(), a.at(2).toDouble(), a.at(3).toDouble()});
                }
                return out_lines;
            };
            l.rows = lines(it.value().toObject().value("rows"));
            l.gates = lines(it.value().toObject().value("gates"));
            learned[it.key()] = l;
        }
        return learned;
    }
    void save_minigames(const std::map<QString, Minigame::Learned>& learned) override{
        const QJsonArray event = out("save_minigames", "what was learned of the little games is saved");
        const QJsonObject want = event.at(2).toObject();
        if ((size_t)want.size() != learned.size()){
            fail("what was learned differs: " + describe(event));
        }
        for (const auto& one : learned){
            if (!want.contains(one.first)){
                fail("what was learned differs: " + describe(event));
            }
        }
    }
    void save_picture(const QString& name, const cv::Mat&) override{
        const QJsonArray event = out("save", "the picture " + name + " is saved");
        if (event.at(2).toString() != name){
            fail("the picture that is saved differs: the Python loop saved " + event.at(2).toString() + ", the port: " + name);
        }
    }
    bool threads() override{ return false; }
    std::function<void(const char*)> looker_trace() override{
        return [this](const char* kind){ out(kind, QString("the looker starts to read (%1)").arg(kind)); };
    }

    //  ---- what the tapper did
    void tap_event(const char* kind, int x, int y, int ms, const char* who){
        const QString doing = QString("%1 at (%2, %3) for %4 ms (%5)").arg(kind).arg(x).arg(y).arg(ms).arg(who);
        const QJsonArray event = out(kind, doing);
        const bool plain = QString(kind) == "tap";
        if (event.at(2).toInt() != x || event.at(3).toInt() != y || (plain && (event.at(4).toInt() != ms || event.at(5).toString() != who))
            || (!plain && QString(kind) == "tap_motion" && event.at(4).toInt() != ms)){
            fail("the touch differs: the Python loop did " + describe(event) + ", the port: " + doing);
        }
    }
    void swipe_event(const std::vector<Stroke>& strokes){
        const QJsonArray event = out("swipe", QString("a swipe of %1 strokes").arg(strokes.size()));
        const QJsonArray want = event.at(2).toArray();
        bool same_strokes = (size_t)want.size() == strokes.size();
        for (size_t i = 0; same_strokes && i < strokes.size(); i++){
            const QJsonArray s = want.at((qsizetype)i).toArray();
            same_strokes = s.at(0).toInt() == strokes[i].x1 && s.at(1).toInt() == strokes[i].y1 && s.at(2).toInt() == strokes[i].x2
                && s.at(3).toInt() == strokes[i].y2 && s.at(4).toInt() == strokes[i].ms;
        }
        if (!same_strokes){
            QString mine;
            for (const Stroke& s : strokes){
                mine += QString("[%1, %2, %3, %4, %5] ").arg(s.x1).arg(s.y1).arg(s.x2).arg(s.y2).arg(s.ms);
            }
            fail("the swipes differ: the Python loop did " + describe(event) + ", the port: " + mine);
        }
    }

    ReplayTapper* m_tapper = nullptr;
    ReplayStream m_stream{*this};
    const QString m_fixtures;
    const QJsonObject m_spec;
    const QJsonArray m_events;
    double m_t;
    std::map<QString, cv::Mat> m_pictures;

    QJsonObject result_event(){
        const QJsonArray event = out("result", "the end of the loop");
        return event.at(2).toObject();
    }
};

bool ReplayStream::wait_new(long long seq, double, double, long long& seq_out, double& t, cv::Mat& small){
    const QJsonArray event = m_replay.input("wait_new", "a picture of the live video");
    small = m_replay.picture(event.at(2).toString(), VIEW_W, VIEW_H);
    seq_out = seq + 1;
    t = m_replay.monotonic();
    m_replay.m_tapper->poll();
    return true;
}

void ReplayTapper::go(){
    m_on = true;
    m_replay.out("go", "the fast taps go on");
}
void ReplayTapper::pause(){
    m_on = false;
    m_replay.out("pause", "the fast taps stop");
}
void ReplayTapper::aim(const std::optional<Point>& xy){
    m_aim = xy;
    const QJsonArray event = m_replay.out("aim", xy.has_value() ? QString("aim at (%1, %2)").arg(xy->x).arg(xy->y) : QString("aim at the usual place"));
    const bool same = xy.has_value() ? (event.at(2).isArray() && event.at(2).toArray().at(0).toInt() == xy->x && event.at(2).toArray().at(1).toInt() == xy->y)
                                     : event.at(2).isNull();
    if (!same){
        m_replay.fail("the aim differs: the Python loop did " + describe(event));
    }
}
void ReplayTapper::sweep(const Planner& planner){
    m_sweep = planner;
    const QJsonArray event = m_replay.out("sweep", planner ? "a little game is swiped" : "no little game any more");
    if (event.at(2).toInt() != (planner ? 1 : 0)){
        m_replay.fail("the little game differs: the Python loop did " + describe(event));
    }
}
void ReplayTapper::tap(int x, int y, int ms){
    m_replay.tap_event("tap", x, y, ms, "main");
}
void ReplayTapper::touch(int how, int x, int y){
    switch (how){
    case 0: m_replay.tap_event("tap_quick", x, y, 1, "main"); break;
    case 1: m_replay.tap_event("tap_motion", x, y, 80, "main"); break;
    case 2: m_replay.tap_event("tap", x, y, 60, "main"); break;
    default: m_replay.tap_event("tap", x, y, 220, "main"); break;
    }
}
void ReplayTapper::poll(){
    if (m_sweep){
        std::vector<Stroke> strokes;
        try{
            strokes = m_sweep();
        }catch (const std::exception&){
        }
        if (!strokes.empty()){
            m_replay.swipe_event(strokes);
            m_swipes += (int)strokes.size();
            return;
        }
    }
    if (m_on){
        const Point xy = m_aim.has_value() ? *m_aim : m_xy;
        m_replay.tap_event("tap", xy.x, xy.y, m_ms, "fast");
        m_taps++;
    }
}


std::optional<Battle::TeamEntry> team_entry(const QJsonObject& e){
    Battle::TeamEntry entry;
    entry.species = e.value("species").toString();
    entry.shadow = e.value("shadow").toBool();
    if (e.contains("cp")){
        entry.cp = e.value("cp").toInt();
    }
    if (e.contains("hp")){
        entry.hp = e.value("hp").toInt();
    }
    if (e.contains("fast")){
        entry.fast = e.value("fast").toString();
    }
    if (e.contains("charged")){
        QStringList charged;
        for (const QJsonValue& v : e.value("charged").toArray()){
            charged << v.toString();
        }
        entry.charged = charged;
    }
    return entry;
}

}


int run_loop_checks(const QString& golden, const QString& fixtures, const QString& data, QStringList& report){
    QString error;
    if (!Battle::data_loaded() && !Battle::load_data(data, error)){
        report << "FAILED: the data of the engine is not there: " + error;
        return 1;
    }
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the fights of the fight loop are not there: " + golden;
        return 1;
    }
    const QJsonObject root = QJsonDocument::fromJson(qUncompress(file.readAll())).object();
    const QJsonArray cases = root.value("cases").toArray();
    if (cases.isEmpty()){
        report << "FAILED: the file of fights of the fight loop is empty or not right: " + golden;
        return 1;
    }

    int wrong = 0;
    //  The numbers of the loop (the fights only show one where it crosses its limit).
    {
        const QJsonObject numbers = root.value("constants").toObject();
        QStringList known;
        for (const auto& [name, values] : loop_constants()){
            known << name;
            const QJsonArray want = numbers.value(name).toArray();
            bool same = (size_t)want.size() == values.size();
            for (size_t i = 0; same && i < values.size(); i++){
                same = want[(qsizetype)i].toDouble() == values[i];
            }
            if (!same){
                wrong++;
                report << "FAILED: the number " + name + " of the loop is not the number of gamebot.py";
            }
        }
        for (const QString& name : numbers.keys()){
            if (!known.contains(name)){
                wrong++;
                report << "FAILED: the number " + name + " of gamebot.py is not in the loop";
            }
        }
    }
    //  The check for the map, picture by picture.
    {
        Replay pictures(QJsonObject(), root, fixtures);
        const QJsonObject table = root.value("on_map").toObject();
        int differ = 0;
        for (auto it = table.begin(); it != table.end(); ++it){
            try{
                if (map_visible(pictures.picture(it.key(), REF_W, REF_H)) != it.value().toBool()){
                    differ++;
                    report << "FAILED: the check for the map says something else on " + it.key();
                }
            }catch (const Abort&){
                differ++;
                report << "FAILED: " + pictures.message;
            }
        }
        wrong += differ;
    }

    std::vector<Battle::TeamEntry> entries;
    for (const QJsonValue& v : root.value("team").toArray()){
        entries.push_back(*team_entry(v.toObject()));
    }
    const std::vector<Battle::Mon> team = Battle::build_team(entries);

    int events = 0;
    for (const QJsonValue& value : cases){
        const QJsonObject one = value.toObject();
        Replay host(one, root, fixtures);
        Result result;
        try{
            result = fight_battle(host, team);
            const QJsonObject want = host.result_event();
            if (want.value("result").toString() != result.result || want.value("why").toString() != result.why
                || want.value("gave_up").toBool() != result.gave_up || want.value("seconds").toInt() != result.seconds){
                host.fail(QString("the fight ended differently: the Python loop returned %1, the port: result '%2', why '%3', gave up %4, %5 s")
                    .arg(QString::fromUtf8(QJsonDocument(want).toJson(QJsonDocument::Compact)), result.result, result.why).arg(result.gave_up).arg(result.seconds));
            }
            if (host.index != one.value("events").toArray().size()){
                host.fail("the port ended before the Python loop did");
            }
        }catch (const Abort&){
        }
        events += (int)host.index;
        if (host.failed){
            wrong++;
            report << "FAILED: " + one.value("id").toString() + ": " + host.message;
        }
    }
    report << QString("%1 fights played, %2 events, %3 of them went another way").arg(cases.size()).arg(events).arg(wrong);
    return wrong;
}


}
}
}
}
