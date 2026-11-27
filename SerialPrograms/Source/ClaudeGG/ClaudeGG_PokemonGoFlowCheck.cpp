/*  Claude GG Pokemon GO Flow Check (the walk around a fight played on the stories of the Python one)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The file of Mobile/tools/make_flow_golden.py holds stories of the walk of gamebot.py (battle_open_menu(), _battle_to_map()
 *  and battle_run()) as lists of events: what the walk was given (the screenshots, what the text reader read, the answers of
 *  the check for the map and of the screen classifier, the fights that were fought) and what it did (taps, swipes, BACK, lines
 *  of the log, sleeps, pictures that were saved, what it returned).  The host here gives the port the same, one after the
 *  other, and says where the port does something else: the first event that differs ends that story.
 *
 *  A screenshot is not in the file: the file says how it is made (white, rectangles of colour, the lower part of a screenshot
 *  of the Battle screen, a screenshot of a fight) and the host makes it here from the pictures in tests/fixtures.
 *
 */

#include <algorithm>
#include <cmath>
#include <map>
#include <stdexcept>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <QCryptographicHash>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include "ClaudeGG_PokemonGoFlow.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Flow{

namespace{

const int REF_W = Loop::REF_W;
const int REF_H = Loop::REF_H;


//  Thrown when the port went another way: ends the story (not a std::exception: the walk must not take it for an error of the phone).
struct Abort{};

double mean_of(const cv::Mat& img){
    const cv::Scalar sum = cv::sum(img);
    double total = 0;
    for (int c = 0; c < img.channels(); c++){
        total += sum[c];
    }
    return total / ((double)img.rows * img.cols * img.channels());
}

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

QJsonArray points(const std::vector<Spot>& spots){
    QJsonArray out;
    for (const Spot& s : spots){
        out.append(QJsonArray{s.first, s.second});
    }
    return out;
}


class Replay : public Host{
public:
    Replay(const QJsonObject& test_case, double start, const QString& fixtures, const QJsonObject& labels)
        : m_fixtures(fixtures)
        , m_labels(labels)
        , m_spec(test_case.value("spec").toObject())
        , m_events(test_case.value("events").toArray())
        , m_t(start)
    {}

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
            fail("the port went on after the last event of the Python walk: " + doing);
        }
        return m_events.at(index).toArray();
    }
    //  The next event, which has to be of this kind (and at this time).
    QJsonArray out(const char* kind, const QString& doing){
        const QJsonArray event = peek(doing);
        if (event.at(0).toString() != kind){
            fail("the Python walk did " + describe(event) + ", the port: " + doing);
        }
        if (std::abs(event.at(1).toDouble() - m_t) > 1e-6){
            fail(QString("the Python walk did %1 at the time %2, the port: %3 at %4")
                .arg(describe(event), QString::number(event.at(1).toDouble(), 'f', 6), doing, QString::number(m_t, 'f', 6)));
        }
        index++;
        return event;
    }
    //  An event that moves the clock: the walk is given the time that it was given.
    QJsonArray input(const char* kind, const QString& doing){
        const QJsonArray event = peek(doing);
        if (event.at(0).toString() != kind){
            fail("the Python walk did " + describe(event) + ", the port: " + doing);
        }
        m_t = event.at(1).toDouble();
        index++;
        return event;
    }

    void same(const QJsonArray& event, int at, double value, const QString& what){
        if (std::abs(event.at(at).toDouble() - value) > 1e-6){
            fail(QString("%1 differs: the Python walk did %2, the port: %3").arg(what, describe(event), QString::number(value, 'f', 6)));
        }
    }

    //  ---- the pictures (how make_flow_golden.make_picture() makes them)
    cv::Mat read(const QString& file){
        const auto found = m_files.find(file);
        if (found != m_files.end()){
            return found->second;
        }
        const cv::Mat raw = cv::imread((m_fixtures + "/" + file).toStdString());
        if (raw.empty()){
            fail("the picture is not there: " + file);
        }
        m_files[file] = raw;
        return raw;
    }
    cv::Mat scaled(const cv::Mat& raw){
        cv::Mat img;
        cv::resize(raw, img, cv::Size(REF_W, REF_H), 0, 0, cv::INTER_CUBIC);
        return img;
    }
    cv::Mat picture(const QJsonArray& spec){
        const QString key = QString::fromUtf8(QJsonDocument(spec).toJson(QJsonDocument::Compact));
        const auto found = m_pictures.find(key);
        if (found != m_pictures.end()){
            return found->second;
        }
        const QString kind = spec.at(0).toString();
        cv::Mat img;
        if (kind == "white"){
            img = cv::Mat(REF_H, REF_W, CV_8UC3, cv::Scalar(255, 255, 255));
        }else if (kind == "rect"){
            img = cv::Mat(REF_H, REF_W, CV_8UC3, cv::Scalar(255, 255, 255));
            for (const QJsonValue& v : spec.at(1).toArray()){
                const QJsonArray r = v.toArray();
                const QJsonArray c = r.at(4).toArray();
                const int y0 = (int)(r.at(0).toDouble() * REF_H);
                const int y1 = std::min((int)(r.at(1).toDouble() * REF_H), REF_H);
                const int x0 = (int)(r.at(2).toDouble() * REF_W);
                const int x1 = std::min((int)(r.at(3).toDouble() * REF_W), REF_W);
                img(cv::Range(y0, y1), cv::Range(x0, x1)) = cv::Scalar(c.at(0).toDouble(), c.at(1).toDouble(), c.at(2).toDouble());
            }
        }else if (kind == "battle"){
            const cv::Mat strip = read("nav/" + spec.at(1).toString() + ".jpg");
            cv::Mat full(strip.rows * 5, strip.cols, CV_8UC3, cv::Scalar(255, 255, 255));
            strip.copyTo(full(cv::Rect(0, full.rows - strip.rows, strip.cols, strip.rows)));
            img = scaled(full);
        }else if (kind == "done"){
            img = scaled(read("nav/home_done.jpg"));
            if (spec.at(1).toBool()){
                img(cv::Range((int)(0.80 * REF_H), (int)(0.92 * REF_H)), cv::Range((int)(0.08 * REF_W), (int)(0.42 * REF_W))) = cv::Scalar(255, 255, 255);
            }
        }else if (kind == "fight"){
            img = scaled(read("fight/" + spec.at(1).toString() + ".jpg"));
        }else{
            fail("a picture that is not known: " + kind);
        }
        m_pictures[key] = img;
        return img;
    }

    //  ---- Loop::Host
    double monotonic() override{ return m_t; }
    void sleep(double seconds) override{
        const QJsonArray event = out("sleep", QString("sleep(%1)").arg(seconds));
        same(event, 2, seconds, "the sleep");
        m_t += seconds;
    }
    void log(const QString& text) override{
        const QJsonArray event = out("log", "the log line: " + text);
        if (event.at(2).toString() != text){
            fail("the log line differs: the Python walk wrote '" + event.at(2).toString() + "', the port: '" + text + "'");
        }
    }
    cv::Mat screenshot() override{
        const QJsonArray event = peek("a screenshot");
        if (event.at(0).toString() == "screenshot_fail"){
            m_t = event.at(1).toDouble();
            index++;
            throw std::runtime_error(event.at(2).toString().toStdString());
        }
        const QJsonArray shot = input("screenshot", "a screenshot");
        return picture(shot.at(2).toArray());
    }
    Loop::Stream* stream() override{ return nullptr; }
    std::unique_ptr<Loop::Tapper> make_tapper(Point, int) override{
        fail("the walk made a tapper of the fast taps (a fight was not played)");
    }
    bool on_map(const cv::Mat&) override{
        return out("on_map", "the check for the map").at(2).toBool();
    }
    Nav::Lines ocr_lines(const cv::Mat& img, int y0, std::optional<int> y1, double scale) override{
        const QJsonArray event = out("ocr", QString("a reading of lines (%1 x %2, from %3)").arg(img.cols).arg(img.rows).arg(y0));
        if (event.at(2).toInt() != img.rows || event.at(3).toInt() != img.cols || event.at(4).toInt() != y0
            || event.at(5).isNull() != !y1.has_value() || (y1.has_value() && event.at(5).toInt() != *y1)
            || std::abs(event.at(6).toDouble() - scale) > 1e-9){
            fail(QString("the reading differs: the Python walk read %1, the port: %2 x %3 rows %4 to %5 scale %6")
                .arg(describe(event)).arg(img.cols).arg(img.rows).arg(y0).arg(y1.has_value() ? QString::number(*y1) : QString("end")).arg(scale));
        }
        if (std::abs(event.at(7).toDouble() - mean_of(img)) > 0.6){
            fail(QString("the picture that was read differs: its mean is %1 and the Python walk read one of %2 (%3)")
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
    QString ocr_line(const cv::Mat& img, int lines) override{
        const QJsonArray event = out("ocr_line", QString("a reading of one line (%1 x %2)").arg(img.cols).arg(img.rows));
        if (event.at(2).toInt() != img.rows || event.at(3).toInt() != img.cols || event.at(4).toInt() != lines){
            fail(QString("the reading differs: the Python walk read %1, the port: %2 x %3, %4 line(s)").arg(describe(event)).arg(img.cols).arg(img.rows).arg(lines));
        }
        if (std::abs(event.at(5).toDouble() - mean_of(img)) > 0.6){
            fail(QString("the picture that was read differs: its mean is %1 and the Python walk read one of %2 (%3)")
                .arg(mean_of(img), 0, 'f', 2).arg(event.at(5).toDouble(), 0, 'f', 2).arg(describe(event)));
        }
        //  The picture of the label of a button is held to the picture that gamebot.button_label() gave the reader (the file has it
        //  as PNG under the hash that the event has).  OpenCV does not compute a resize or a top-hat bit for bit the same on every
        //  computer, so a few pixels (at most one in a thousand) may be another colour; a wrong zone or threshold changes thousands.
        if (event.at(7).isString()){
            const cv::Mat flat = img.isContinuous() ? img : img.clone();
            const QByteArray bytes = QByteArray::fromRawData((const char*)flat.data, (qsizetype)(flat.total() * flat.elemSize()));
            const QString digest = QString::fromLatin1(QCryptographicHash::hash(bytes, QCryptographicHash::Sha1).toHex());
            if (digest != event.at(7).toString()){
                const QByteArray png = QByteArray::fromBase64(m_labels.value(event.at(7).toString()).toString().toLatin1());
                const cv::Mat want = png.isEmpty() ? cv::Mat() : cv::imdecode(cv::Mat(1, (int)png.size(), CV_8UC1, (void*)png.constData()), cv::IMREAD_UNCHANGED);
                if (want.empty()){
                    fail("the picture of the label of the button is not in the file (" + describe(event) + ")");
                }
                if (want.size() != img.size() || want.type() != img.type()){
                    fail("the picture of the label of the button has another size than the one of gamebot.py (" + describe(event) + ")");
                }
                const int differ = cv::countNonZero(want != img);
                if (differ > (int)(img.total() / 1000)){
                    fail(QString("the picture of the label of the button is not the picture of gamebot.py: %1 of its %2 pixels differ (%3)")
                        .arg(differ).arg(img.total()).arg(describe(event)));
                }
            }
        }
        return event.at(6).toString();
    }
    bool give_up_enabled() override{ return false; }
    bool aim_enabled() override{ return false; }
    void aim_disabled() override{}
    QString league() override{ return m_spec.value("league").toString(); }
    Fight::Known load_seen() override{ return Fight::Known(); }
    void save_seen(const Fight::Known&) override{ fail("the walk saved what was seen in a fight"); }
    std::map<QString, Minigame::Learned> load_minigames() override{ return std::map<QString, Minigame::Learned>(); }
    void save_minigames(const std::map<QString, Minigame::Learned>&) override{ fail("the walk saved what was learned of a little game"); }
    void save_picture(const QString& name, const cv::Mat&) override{
        const QJsonArray event = out("save", "the picture " + name + " is saved");
        if (event.at(2).toString() != name){
            fail("the picture that is saved differs: the Python walk saved " + event.at(2).toString() + ", the port: " + name);
        }
    }
    void beat() override{ out("beat", "a beat"); }
    bool stop() override{ return out("stop", "the question whether the person stopped").at(2).toBool(); }
    bool threads() override{ return false; }

    //  ---- Flow::Host
    double wall() override{ return m_t; }
    void tap(int x, int y) override{
        const QString doing = QString("a tap at (%1, %2)").arg(x).arg(y);
        const QJsonArray event = out("tap", doing);
        if (event.at(2).toInt() != x || event.at(3).toInt() != y){
            fail("the tap differs: the Python walk did " + describe(event) + ", the port: " + doing);
        }
    }
    void swipe(int x1, int y1, int x2, int y2, int ms) override{
        const QString doing = QString("a swipe from (%1, %2) to (%3, %4) in %5 ms").arg(x1).arg(y1).arg(x2).arg(y2).arg(ms);
        const QJsonArray event = out("swipe", doing);
        if (event.at(2).toInt() != x1 || event.at(3).toInt() != y1 || event.at(4).toInt() != x2 || event.at(5).toInt() != y2 || event.at(6).toInt() != ms){
            fail("the swipe differs: the Python walk did " + describe(event) + ", the port: " + doing);
        }
    }
    void back() override{ out("back", "BACK"); }
    std::pair<QString, double> screen_class(const cv::Mat&) override{
        const QJsonArray event = out("class", "the screen classifier");
        return {event.at(2).toString(), event.at(3).toDouble()};
    }
    void restart_game() override{ out("restart", "restarting the game"); }
    void recheck_shot_mode() override{ out("recheck", "the comparison of the screenshots again"); }
    void mark_battles_done() override{ out("mark_done", "the battles of today are written down as done"); }
    QString day_count(const QString& key) override{
        const QJsonArray event = out("day_count", "the count of the day (" + key + ")");
        if (event.at(2).toString() != key){
            fail("the count of the day differs: the Python walk asked for " + describe(event) + ", the port: " + key);
        }
        return event.at(3).toString();
    }
    QStringList team_names() override{
        QStringList names;
        for (const QJsonValue& v : m_spec.value("names").toArray()){
            names << v.toString();
        }
        return names;
    }
    bool no_more() override{ return out("no_more", "the question whether the time of the run is up").at(2).toBool(); }
    Loop::Result fight(const std::vector<Battle::Mon>&, const std::vector<Point>& use_spots) override{
        const QJsonArray event = out("fight", QString("a fight (%1 places of USE THIS PARTY)").arg(use_spots.size()));
        const QJsonArray want = event.at(2).toArray();
        bool same_spots = (size_t)want.size() == use_spots.size();
        for (size_t i = 0; same_spots && i < use_spots.size(); i++){
            const QJsonArray p = want.at((qsizetype)i).toArray();
            same_spots = p.at(0).toInt() == use_spots[i].x && p.at(1).toInt() == use_spots[i].y;
        }
        if (!same_spots){
            fail("the places of USE THIS PARTY differ: the Python walk gave the fight " + describe(event) + ", the port: " + QString::number(use_spots.size()) + " places");
        }
        const QString raised = event.at(4).toString();
        if (raised == "interrupt"){
            throw Interrupted();
        }
        if (raised == "error"){
            throw std::runtime_error("boom");
        }
        const QJsonObject res = event.at(3).toObject();
        Loop::Result result;
        result.result = res.value("result").toString();
        result.why = res.value("why").toString();
        result.seconds = (int)res.value("seconds").toDouble();
        result.gave_up = res.value("gave_up").toBool();
        m_t += res.value("seconds").toDouble();
        return result;
    }

    //  ---- the end of the story
    //  What the walk returned has to be what the Python walk returned.
    void finish(const QJsonValue& got){
        const QJsonArray event = out("result", "the end of the walk");
        if (event.at(2) != got){
            fail("the walk ended differently: the Python walk returned " + describe(event.at(2)) + ", the port: " + describe(got));
        }
    }
    //  The walk did not return (it was stopped or it failed): the Python walk did not either.
    void finish_raised(const QString& kind, const QString& what){
        const QJsonArray event = out("raised", "the end of the walk (" + kind + ")");
        if (event.at(2).toString() != kind || (kind == "error" && event.at(3).toString() != what)){
            fail("the walk ended differently: the Python walk did " + describe(event) + ", the port: " + kind + " '" + what + "'");
        }
    }

    const QJsonObject& spec() const{ return m_spec; }

private:
    const QString m_fixtures;
    const QJsonObject m_labels;
    const QJsonObject m_spec;
    const QJsonArray m_events;
    double m_t;
    std::map<QString, cv::Mat> m_files;
    std::map<QString, cv::Mat> m_pictures;
};


QJsonObject info_object(const Info& info){
    QJsonObject out;
    out["ok"] = info.ok;
    out["why"] = info.why;
    out["title"] = info.title;
    QJsonArray members;
    for (const QString& m : info.members){
        members.append(m);
    }
    out["members"] = members;
    out["use_spots"] = points(info.use_spots);
    out["chosen"] = info.chosen;
    out["leave"] = info.leave;
    out["catch"] = info.catch_reward;
    out["done_today"] = info.done_today;
    QJsonArray leagues;
    for (const auto& league : info.leagues){
        leagues.append(QJsonArray{league.first, league.second});
    }
    out["leagues"] = leagues;
    return out;
}

QJsonObject run_object(const Run& run){
    QJsonObject out;
    out["fought"] = run.fought;
    out["wins"] = run.wins;
    out["leave"] = run.leave.has_value() ? QJsonValue(*run.leave) : QJsonValue(QJsonValue::Null);
    out["catch"] = run.catch_reward.has_value() ? QJsonValue(*run.catch_reward) : QJsonValue(QJsonValue::Null);
    out["done_today"] = run.done_today;
    return out;
}

}


int run_flow_checks(const QString& golden, const QString& fixtures, QStringList& report){
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the stories of the walk around a fight are not there: " + golden;
        return 1;
    }
    const QJsonObject root = QJsonDocument::fromJson(qUncompress(file.readAll())).object();
    const QJsonArray cases = root.value("cases").toArray();
    if (cases.isEmpty()){
        report << "FAILED: the file of stories of the walk around a fight is empty or not right: " + golden;
        return 1;
    }

    int wrong = 0;
    //  The numbers of the walk (the stories only show one where it crosses its limit).
    {
        const QJsonObject numbers = root.value("constants").toObject();
        QStringList known;
        for (const auto& [name, values] : flow_constants()){
            known << name;
            const QJsonArray want = numbers.value(name).toArray();
            bool same = (size_t)want.size() == values.size();
            for (size_t i = 0; same && i < values.size(); i++){
                same = want[(qsizetype)i].toDouble() == values[i];
            }
            if (!same){
                wrong++;
                report << "FAILED: the number " + name + " of the walk is not the number of gamebot.py";
            }
        }
        for (const QString& name : numbers.keys()){
            if (!known.contains(name)){
                wrong++;
                report << "FAILED: the number " + name + " of gamebot.py is not in the walk";
            }
        }
    }

    const double start = root.value("start").toDouble();
    int events = 0;
    for (const QJsonValue& value : cases){
        const QJsonObject one = value.toObject();
        Replay host(one, start, fixtures, root.value("labels").toObject());
        const QJsonObject spec = host.spec();
        const QJsonObject args = spec.value("args").toObject();
        const QString call = spec.value("call").toString();
        try{
            try{
                if (call == "open_menu"){
                    const Info info = open_menu(host, args.value("restart").toBool(), args.value("stay").toBool(), args.value("leagues_only").toBool());
                    host.finish(info_object(info));
                }else if (call == "to_map"){
                    host.finish(to_map(host, args.value("leaving_setup").toBool()));
                }else if (call == "battle_run"){
                    const Run run = battle_run(host, std::vector<Battle::Mon>(), args.value("count").toInt());
                    host.finish(run_object(run));
                }else{
                    host.fail("a story of a kind that is not known: " + call);
                }
            }catch (const Interrupted&){
                host.finish_raised("interrupt", QString());
            }catch (const Abort&){
                throw;
            }catch (const std::exception& e){
                host.finish_raised("error", QString::fromUtf8(e.what()));
            }
            if (host.index != one.value("events").toArray().size()){
                host.fail("the port ended before the Python walk did");
            }
        }catch (const Abort&){
        }
        events += (int)host.index;
        if (host.failed){
            wrong++;
            report << "FAILED: " + one.value("id").toString() + ": " + host.message;
        }
    }
    report << QString("%1 stories of the walk played, %2 events, %3 of them went another way").arg(cases.size()).arg(events).arg(wrong);
    return wrong;
}


}
}
}
}
