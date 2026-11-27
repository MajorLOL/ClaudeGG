/*  Claude GG Pokemon GO Start Check (starting the game and the battles of a run, played on the stories of the Python code)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The file of Mobile/tools/make_start_golden.py holds four things: pictures with what find_pill_button() and find_green_button()
 *  found on them, the settings of the battles with what battle_app(), battle_league(), battle_count() and battle_wanted() made of
 *  them, and stories of restart_game(), startup_screen() and auto_battle() as lists of events: what the code was given (the
 *  screenshots, what the text reader read, how the start of the game was going) and what it did (taps, log lines, sleeps, the calls
 *  that close and start the game, the battles that were started, what it returned).  The host here gives the port the same, one
 *  after the other, and says where the port does something else: the first event that differs ends that story.
 *
 *  A screenshot is not in the file: the file says how it is made (white, or white with rectangles of colour).
 *
 */

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <opencv2/imgproc.hpp>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include "ClaudeGG_PokemonGoStart.h"
#include "ClaudeGG_PokemonGoText.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Start{

namespace{

const int REF_W = Loop::REF_W;
const int REF_H = Loop::REF_H;


//  Thrown when the port went another way: ends the story (not a std::exception: the code must not take it for an error of the phone).
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

//  How make_start_golden.make_picture() makes a picture.
cv::Mat make_picture(const QJsonArray& spec){
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
    return img;
}

QJsonValue found_json(const std::optional<Found>& found){
    if (!found.has_value()){
        return QJsonValue(QJsonValue::Null);
    }
    return QJsonArray{found->x, found->y, found->area};
}

QJsonValue optional_bool(const std::optional<bool>& value){
    return value.has_value() ? QJsonValue(*value) : QJsonValue(QJsonValue::Null);
}


class Replay : public Host{
public:
    Replay(const QJsonObject& test_case, double start)
        : m_spec(test_case.value("spec").toObject())
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
    cv::Mat screenshot() override{
        const QJsonArray event = peek("a screenshot");
        if (event.at(0).toString() == "screenshot_fail"){
            m_t = event.at(1).toDouble();
            index++;
            if (event.at(2).toString() == "interrupt"){
                throw Flow::Interrupted();
            }
            throw std::runtime_error(event.at(2).toString().toStdString());
        }
        const QJsonArray shot = input("screenshot", "a screenshot");
        return make_picture(shot.at(2).toArray());
    }
    Loop::Stream* stream() override{ return nullptr; }
    std::unique_ptr<Loop::Tapper> make_tapper(Point, int) override{
        fail("the start made a tapper of the fast taps");
    }
    bool on_map(const cv::Mat& canvas) override{
        return Loop::map_visible(canvas);
    }
    Nav::Lines ocr_lines(const cv::Mat&, int, std::optional<int>, double) override{
        fail("the start read lines of text");
    }
    QString ocr_line(const cv::Mat& img, int lines) override{
        const QJsonArray event = input("ocr", QString("a reading of a strip (%1 x %2)").arg(img.cols).arg(img.rows));
        if (lines != 2 || event.at(2).toInt() != img.rows || event.at(3).toInt() != img.cols){
            fail(QString("the reading differs: the Python code read %1, the port: %2 x %3, %4 line(s)").arg(describe(event)).arg(img.cols).arg(img.rows).arg(lines));
        }
        //  (The text reader is given the grey picture: gamebot.ocr_text() makes it of the strip before it writes the PNG.)
        cv::Mat grey;
        cv::cvtColor(img, grey, cv::COLOR_BGR2GRAY);
        if (std::abs(event.at(4).toDouble() - mean_of(grey)) > 0.6){
            fail(QString("the strip that was read differs: its mean is %1 and the Python code read one of %2 (%3)")
                .arg(mean_of(grey), 0, 'f', 2).arg(event.at(4).toDouble(), 0, 'f', 2).arg(describe(event)));
        }
        if (event.at(5).isNull()){
            throw std::runtime_error("the text reader did not answer");
        }
        //  What the real reader gives: what tesseract wrote, white space (also the form feed at the end) as one space.
        return Text::one_line(event.at(5).toString());
    }
    bool give_up_enabled() override{ return false; }
    bool aim_enabled() override{ return false; }
    void aim_disabled() override{}
    QString league() override{ return QString(); }
    Fight::Known load_seen() override{ return Fight::Known(); }
    void save_seen(const Fight::Known&) override{ fail("the start saved what was seen in a fight"); }
    std::map<QString, Minigame::Learned> load_minigames() override{ return std::map<QString, Minigame::Learned>(); }
    void save_minigames(const std::map<QString, Minigame::Learned>&) override{ fail("the start saved what was learned of a little game"); }
    void save_picture(const QString& name, const cv::Mat&) override{ fail("the start saved the picture " + name); }
    void beat() override{ out("beat", "a beat"); }
    bool stop() override{ fail("the start asked whether the person stopped"); }
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
    void swipe(int, int, int, int, int) override{ fail("the start swiped"); }
    void back() override{ fail("the start pressed BACK"); }
    std::pair<QString, double> screen_class(const cv::Mat&) override{ fail("the start asked for the screen classifier"); }
    void restart_game() override{ fail("the start restarted the game through the host of the walk"); }

    //  ---- Start::Host
    void stop_game() override{
        out("stop_game", "closing the game");
        m_t += m_spec.value("stop_seconds").toDouble();
        if (m_spec.contains("stop_fail")){
            throw std::runtime_error(m_spec.value("stop_fail").toString().toStdString());
        }
    }
    void start_game() override{ out("start_game", "starting the game"); }
    Launch start_state() override{
        const QJsonArray event = out("start_state", "the state of the command that starts the game");
        Launch launch;
        launch.running = event.at(2).toBool();
        launch.code = event.at(3).toInt();
        launch.error = event.at(4).toString();
        return launch;
    }
    void start_end() override{ out("kill", "ending the command that starts the game"); }

    //  ---- the battles
    Flow::Run run(const std::vector<Battle::Mon>& team, int count){
        const QJsonArray event = out("run", QString("battles (%1)").arg(count));
        QStringList labels;
        for (const Battle::Mon& mon : team){
            labels << mon.label();
        }
        QStringList want;
        for (const QJsonValue& v : event.at(3).toArray()){
            want << v.toString();
        }
        if (event.at(2).toInt() != count || want != labels){
            fail(QString("the battles differ: the Python code started %1, the port: %2 with %3").arg(describe(event)).arg(count).arg(labels.join(", ")));
        }
        const QJsonObject res = m_spec.value("run").toObject();
        Flow::Run run;
        run.fought = res.value("fought").toInt();
        run.wins = res.value("wins").toInt();
        if (res.contains("leave")){
            run.leave = res.value("leave").toBool();
        }
        if (res.contains("catch")){
            run.catch_reward = res.value("catch").toBool();
        }
        return run;
    }

    //  ---- the end of the story
    void finish(const QJsonArray& got){
        const QJsonArray event = out("result", "the end of the story");
        for (qsizetype i = 0; i < got.size(); i++){
            if (event.at(2 + i) != got.at(i)){
                fail("the story ended differently: the Python code returned " + describe(event) + ", the port: " + describe(got));
            }
        }
    }
    void finish_raised(const QString& kind, const QString& what){
        const QJsonArray event = out("raised", "the end of the story (" + kind + ")");
        if (event.at(2).toString() != kind || (kind == "error" && event.at(3).toString() != what)){
            fail("the story ended differently: the Python code did " + describe(event) + ", the port: " + kind + " '" + what + "'");
        }
    }

    const QJsonObject& spec() const{ return m_spec; }

private:
    const QJsonObject m_spec;
    const QJsonArray m_events;
    double m_t;
};


Settings settings_of(const QJsonObject& object){
    Settings settings;
    const QJsonValue battle = object.value("battle");
    settings.battle = battle.isBool() ? battle.toBool() : (battle.isDouble() && battle.toDouble() != 0);
    settings.app = object.value("battle_app").toString();
    if (object.value("battle_league").isString()){
        settings.league = object.value("battle_league").toString();
    }
    if (object.value("battle_count").isDouble()){
        settings.count = object.value("battle_count").toInt();
    }
    return settings;
}

}


int run_start_checks(const QString& golden, QStringList& report){
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the stories of the start of the game are not there: " + golden;
        return 1;
    }
    const QJsonObject root = QJsonDocument::fromJson(qUncompress(file.readAll())).object();
    const QJsonArray cases = root.value("cases").toArray();
    const QJsonArray buttons = root.value("buttons").toArray();
    const QJsonArray options = root.value("options").toArray();
    if (cases.isEmpty() || buttons.isEmpty() || options.isEmpty()){
        report << "FAILED: the file of stories of the start of the game is empty or not right: " + golden;
        return 1;
    }

    int wrong = 0;
    //  The numbers and the texts of the start.
    {
        const QJsonObject numbers = root.value("constants").toObject();
        QStringList known;
        for (const auto& [name, values] : start_constants()){
            known << name;
            const QJsonArray want = numbers.value(name).toArray();
            bool same = (size_t)want.size() == values.size();
            for (size_t i = 0; same && i < values.size(); i++){
                same = want[(qsizetype)i].toDouble() == values[i];
            }
            if (!same){
                wrong++;
                report << "FAILED: the number " + name + " of the start is not the number of gamebot.py";
            }
        }
        for (const QString& name : numbers.keys()){
            if (!known.contains(name)){
                wrong++;
                report << "FAILED: the number " + name + " of gamebot.py is not in the start";
            }
        }
        const QJsonObject texts = root.value("strings").toObject();
        if (texts.value("MAIN_PACKAGE").toString() != MAIN_PACKAGE || texts.value("BATTLE_LEAGUE").toString() != BATTLE_LEAGUE || texts.size() != 2){
            wrong++;
            report << "FAILED: the package of the game or the league of the battles is not the one of gamebot.py";
        }
    }

    //  The buttons.
    int found = 0;
    for (const QJsonValue& value : buttons){
        const QJsonObject one = value.toObject();
        const cv::Mat img = make_picture(one.value("pic").toArray());
        const int y_min = one.value("y_min").toInt();
        const QJsonValue pill = found_json(find_pill_button(img, y_min));
        const QJsonValue green = found_json(find_green_button(img));
        found += (!pill.isNull() || !green.isNull()) ? 1 : 0;
        if (pill != one.value("pill")){
            wrong++;
            report << "FAILED: " + one.value("id").toString() + ": the pill button is " + describe(pill) + ", gamebot.py found " + describe(one.value("pill"));
        }
        if (green != one.value("green")){
            wrong++;
            report << "FAILED: " + one.value("id").toString() + ": the green button is " + describe(green) + ", spin_stop.py found " + describe(one.value("green"));
        }
    }

    //  The settings of the battles.
    for (const QJsonValue& value : options){
        const QJsonObject one = value.toObject();
        const Choice choice = choose(settings_of(one.value("settings").toObject()), one.value("done").toBool());
        if (choice.wanted != one.value("wanted").toBool() || choice.app != one.value("app").toString()
            || choice.league != one.value("league").toString() || choice.count != one.value("count").toInt()){
            wrong++;
            report << QString("FAILED: the settings %1 (done today: %2) make the choice (%3, '%4', '%5', %6) in the port, in gamebot.py it is %7")
                .arg(describe(one.value("settings")), one.value("done").toBool() ? "yes" : "no", choice.wanted ? "wanted" : "not wanted",
                     choice.app, choice.league).arg(choice.count).arg(describe(value));
        }
    }

    //  The stories.
    const double start = root.value("start").toDouble();
    int events = 0;
    for (const QJsonValue& value : cases){
        const QJsonObject one = value.toObject();
        Replay host(one, start);
        const QJsonObject spec = host.spec();
        const QString call = spec.value("call").toString();
        try{
            try{
                if (call == "restart"){
                    restart_game(host);
                    host.finish(QJsonArray{QJsonValue(QJsonValue::Null)});
                }else if (call == "startup"){
                    const Look look = startup_screen(host, host.screenshot());
                    host.finish(QJsonArray{look == Look::Map ? QJsonValue("map") : look == Look::Handled ? QJsonValue("handled") : QJsonValue(QJsonValue::Null)});
                }else if (call == "auto"){
                    const QJsonObject s = spec.value("settings").toObject();
                    const TeamLoader load = [&]() -> std::vector<Battle::Mon>{
                        if (spec.contains("team_error")){
                            throw std::runtime_error(spec.value("team_error").toString().toStdString());
                        }
                        std::vector<Battle::Mon> mons;
                        for (const QJsonValue& n : spec.value("team").toArray()){
                            Battle::Mon mon;
                            mon.name = n.toString();
                            mons.push_back(mon);
                        }
                        return mons;
                    };
                    const Runner runner = [&](Flow::Host&, const std::vector<Battle::Mon>& mons, int count){
                        return host.run(mons, count);
                    };
                    const AutoBattle result = auto_battle(host, spec.value("package").toString(), settings_of(s), spec.value("done").toBool(), load, runner);
                    host.finish(QJsonArray{result.fought, optional_bool(result.resume)});
                }else{
                    host.fail("a story of a kind that is not known: " + call);
                }
            }catch (const Flow::Interrupted&){
                host.finish_raised("interrupt", QString());
            }catch (const Abort&){
                throw;
            }catch (const std::exception& e){
                host.finish_raised("error", QString::fromUtf8(e.what()));
            }
            if (host.index != one.value("events").toArray().size()){
                host.fail("the port ended before the Python code did");
            }
        }catch (const Abort&){
        }
        events += (int)host.index;
        if (host.failed){
            wrong++;
            report << "FAILED: " + one.value("id").toString() + ": " + host.message;
        }
    }
    report << QString("%1 pictures of buttons (%2 with a button), %3 settings and %4 stories of the start played, %5 events, %6 of them went another way")
        .arg(buttons.size()).arg(found).arg(options.size()).arg(cases.size()).arg(events).arg(wrong);
    return wrong;
}


}
}
}
}
