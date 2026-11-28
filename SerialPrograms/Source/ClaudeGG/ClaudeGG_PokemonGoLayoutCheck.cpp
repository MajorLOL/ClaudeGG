/*  Claude GG Pokemon GO Layout Check (the layout of the game, played on the stories of the Python code)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The file of Mobile/tools/make_layout_golden.py holds stories of what spin_stop.py and gamebot.py do to find out whether the game is drawn the way the
 *  bot expects: the shape of the screen, the menu button on pictures, the plan for `wm size`, the change of the display and putting it back, and the
 *  steps of the layout check.  They are played on a pretend phone with a pretend clock.  What the code was GIVEN: what `wm size` says, the record of
 *  the Pi, the two switch files, what the check of the screen finds, the screenshots and what the text reader reads.  What it DID: the calls for the
 *  display, the record, the taps, sleeps and log lines, and at the end of every call what it returned and what the bot remembers.  The first event
 *  that differs ends that story.
 *
 */

#include <map>
#include <stdexcept>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include "ClaudeGG_PokemonGoLayout.h"
#include "ClaudeGG_PokemonGoStory.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Layout{

namespace{

using Story::Abort;
using Story::describe;


class Replay : public Story::Host, public Layout::Host{
public:
    Replay(const QJsonObject& test_case, double start, std::vector<Story::Scene>& cache)
        : Story::Host(test_case, start, cache)
    {
        const QJsonValue record = spec().value("record");
        if (record.isString()){
            m_store = record.toString();
        }else if (record.isObject() || record.isArray()){
            m_store = QString::fromUtf8(record.isObject() ? QJsonDocument(record.toObject()).toJson(QJsonDocument::Compact)
                                                           : QJsonDocument(record.toArray()).toJson(QJsonDocument::Compact));
        }
    }

    //  What the bot remembers of the record (the file of the Pi), as the story has it: the json in it, or the text when it is no json.
    QJsonValue record_state() const{
        if (!m_store.has_value()){
            return QJsonValue(QJsonValue::Null);
        }
        QJsonParseError error;
        const QJsonDocument doc = QJsonDocument::fromJson(m_store->toUtf8(), &error);
        if (error.error == QJsonParseError::NoError){
            if (doc.isObject()){
                return doc.object();
            }
            if (doc.isArray()){
                return doc.array();
            }
        }
        return *m_store;
    }

    //  ---- Loop::Host (the check for the map is the real one: the pictures decide)
    bool on_map(const cv::Mat& img) override{ return Loop::map_visible(img); }

    //  ---- Bag::Host (the layout check does none of this)
    void swipes(const std::vector<Loop::Stroke>&) override{ fail("the code swiped"); }
    QString shell(const QStringList& args) override{ fail("the code gave the adb command " + args.join(' ')); }
    QString package() override{ return "com.nianticlabs.pokemongo"; }
    QJsonValue bag_keep_saved() override{ return QJsonValue(QJsonValue::Null); }
    void run_done() override{ fail("the daily run was told that it is over"); }

    //  ---- Layout::Host
    QString wm_size_text() override{
        const QJsonArray next = peek("the question what `wm size` says");
        if (next.at(0).toString() == "wm_info_error"){
            input("wm_info_error", "the question what `wm size` says");
            throw std::runtime_error(next.at(2).toString().toStdString());
        }
        return input("wm_info", "the question what `wm size` says").at(2).toString();
    }
    void wm_size_set(const QString& size) override{
        const QString doing = "wm size " + size;
        const QJsonArray next = peek(doing);
        const bool refused = next.at(0).toString() == "wm_set_error";
        const QJsonArray event = out(refused ? "wm_set_error" : "wm_set", doing);
        if (event.at(2).toString() != size){
            fail("the size differs: the Python code did " + describe(event) + ", the port: " + doing);
        }
        if (refused){
            throw std::runtime_error(event.at(3).toString().toStdString());
        }
    }
    void wm_size_reset() override{
        const QJsonArray next = peek("wm size reset");
        if (next.at(0).toString() == "wm_reset_error"){
            const QJsonArray event = out("wm_reset_error", "wm size reset");
            throw std::runtime_error(event.at(2).toString().toStdString());
        }
        out("wm_reset", "wm size reset");
    }
    std::optional<QString> record_text() override{
        const QJsonValue text = input("record_read", "a look at the record of the display change").at(2);
        if (text.isString()){
            return text.toString();
        }
        return std::nullopt;
    }
    QString record_write(const QJsonObject& record) override{
        const QString doing = "the record of the display change is written";
        const QJsonArray next = peek(doing);
        if (next.at(0).toString() == "record_write_error"){
            return out("record_write_error", doing).at(2).toString();
        }
        const QJsonArray event = out("record_write", doing);
        if (event.at(2).toString() != record.value("set").toString() || event.at(3).toDouble() != record.value("time").toDouble()
            || event.at(4).toString() != record.value("model").toString() || event.at(5).toString() != record.value("was").toString()){
            fail("the record differs: the Python code wrote " + describe(event) + ", the port: " + describe(record));
        }
        m_store = QString::fromUtf8(QJsonDocument(record).toJson(QJsonDocument::Compact));
        return QString();
    }
    void record_forget() override{
        out("record_forget", "the record of the display change is forgotten");
        m_store.reset();
    }
    bool file_exists(const QString& which) override{
        const auto changed = m_files.find(which);
        return changed != m_files.end() ? changed->second : spec().value(which).toBool();
    }
    //  A call of the story creates or removes a switch file of the Pi ("allow", "no_adapt").
    void set_file(const QString& which, bool exists){ m_files[which] = exists; }
    QString file_path(const QString& which) override{
        if (which == "allow"){
            return "/home/pi/gamebot_allow_unsupported";
        }
        if (which == "no_adapt"){
            return "/home/pi/gamebot_no_display_change";
        }
        return "/home/pi/gamebot_wm_override.json";
    }
    std::optional<ScreenRead> read_screen(bool wake) override{
        const QString doing = QString("a look at the screen of the phone (wake: %1)").arg(wake);
        const QString kind = peek(doing).at(0).toString();
        if (kind != "detect_error" && kind != "detect_none" && kind != "detect_screen"){
            fail("the Python code did " + describe(peek(doing)) + ", the port: " + doing);
        }
        const QJsonArray event = out(kind == "detect_error" ? "detect_error" : kind == "detect_none" ? "detect_none" : "detect_screen", doing);
        if (event.at(2).toBool() != wake){
            fail("the look differs: the Python code did " + describe(event) + ", the port: " + doing);
        }
        if (kind == "detect_error"){
            throw std::runtime_error(event.at(3).toString().toStdString());
        }
        if (kind == "detect_none"){
            return std::nullopt;
        }
        return ScreenRead{event.at(3).toInt(), event.at(4).toInt(), event.at(5).toString()};
    }
    void reset_same_screen() override{
        const QJsonArray event = out("same_screen", "the step is told to look at the screen again");
        if (!event.at(2).isNull() || event.at(3).toInt() != 0){
            fail("the step was told something else: the Python code did " + describe(event));
        }
    }

private:
    std::optional<QString> m_store;
    std::map<QString, bool> m_files;                  //  the switch files that a call of the story created or removed
};


QJsonValue frame_result(const std::optional<MenuButton>& found){
    if (!found.has_value()){
        return QJsonValue(QJsonValue::Null);
    }
    return QJsonArray{found->x, found->y, found->w};
}

QJsonObject state_of(const State& state, const Replay& host){
    QJsonObject layout;
    layout["state"] = state.state;
    layout["looks"] = state.looks;
    layout["since"] = state.since;
    layout["next_try"] = state.next_try;
    QJsonObject screen;
    screen["w"] = state.screen.w;
    screen["h"] = state.screen.h;
    screen["ok"] = state.screen.ok;
    screen["note"] = state.screen.note;
    screen["model"] = state.screen.model;
    QJsonObject all;
    all["layout"] = layout;
    all["screen"] = screen;
    all["record"] = host.record_state();
    all["wait_log"] = state.wait_log;
    return all;
}

//  Plays one story; says what went another way (nothing: all of it was the same).
QString play(const QJsonObject& test_case, double start, std::vector<Story::Scene>& cache){
    Replay host(test_case, start, cache);
    try{
        State state;
        const QJsonObject spec = test_case.value("spec").toObject();
        const QJsonObject screen = spec.value("screen").toObject();
        state.screen.w = screen.value("w").toInt(REF_W);
        state.screen.h = screen.value("h").toInt(REF_H);
        state.screen.model = screen.value("model").toString();
        const QJsonObject layout = spec.value("layout").toObject();
        state.state = layout.value("state").toString("new");
        state.looks = layout.value("looks").toInt(0);
        state.since = layout.value("since").toDouble(0.0);
        state.next_try = layout.value("next_try").toDouble(0.0);
        judge_screen(state, host);
        for (const QJsonValue& v : spec.value("calls").toArray()){
            const QJsonObject call = v.toObject();
            host.begin(call);
            for (const char* key : {"allow", "no_adapt"}){
                if (call.contains(QLatin1String(key))){
                    host.set_file(QLatin1String(key), call.value(QLatin1String(key)).toBool());
                }
            }
            const QString fn = call.value("fn").toString();
            try{
                if (fn == "judge"){
                    state.screen.w = call.value("w").toInt();
                    state.screen.h = call.value("h").toInt();
                    judge_screen(state, host);
                    host.result(QJsonArray{state.screen.ok, state.screen.note});
                }else if (fn == "seen"){
                    screen_seen(state, host, call.value("w").toInt(), call.value("h").toInt());
                    host.result(QJsonArray{state.screen.ok, state.screen.note});
                }else if (fn == "find"){
                    host.result(frame_result(find_menu_button(host.picture(call.value("img").toInt()))));
                }else if (fn == "check"){
                    std::optional<MenuButton> found;
                    if (call.value("found").isArray()){
                        const QJsonArray f = call.value("found").toArray();
                        found = MenuButton{f.at(0).toDouble(), f.at(1).toDouble(), f.at(2).toDouble()};
                    }
                    const Check check = menu_button_check(found);
                    host.result(QJsonArray{check.ok.has_value() ? QJsonValue(*check.ok) : QJsonValue(QJsonValue::Null), check.text});
                }else if (fn == "plan"){
                    const Plan plan = display_plan(state, host);
                    host.result(QJsonArray{plan.cmd.isEmpty() ? QJsonValue(QJsonValue::Null) : QJsonValue(plan.cmd),
                                           plan.cmd.isEmpty() ? QJsonValue(QJsonValue::Null) : QJsonValue(QJsonArray{plan.w, plan.h}), plan.why});
                }else if (fn == "adapt"){
                    const Adapted adapted = adapt_display(state, host);
                    host.result(QJsonArray{adapted.changed, adapted.text});
                }else if (fn == "restore"){
                    host.result(restore_display(state, host));
                }else if (fn == "detect"){
                    host.result(detect_screen(state, host, call.value("wake").toBool(true)));
                }else if (fn == "wait_unsupported"){
                    wait_unsupported(state, host);
                    host.result(QJsonValue(QJsonValue::Null));
                }else if (fn == "init"){
                    layout_init(state, host);
                    host.result(QJsonValue(QJsonValue::Null));
                }else if (fn == "layout_adapt"){
                    host.result(layout_adapt(state, host, call.value("why").toString()));
                }else if (fn == "layout_undo"){
                    layout_undo(state, host, call.value("why").toString());
                    host.result(QJsonValue(QJsonValue::Null));
                }else if (fn == "tap_test"){
                    host.result(layout_tap_test(state, host, host.picture(call.value("before").toInt())));
                }else if (fn == "verify"){
                    layout_verify(state, host, host.picture(call.value("img").toInt()));
                    host.result(QJsonValue(QJsonValue::Null));
                }else if (fn == "watch"){
                    layout_watch(state, host);
                    host.result(QJsonValue(QJsonValue::Null));
                }else{
                    host.fail("the story has a call that the check does not know: " + fn);
                }
            }catch (const Abort&){
                throw;
            }catch (const std::exception& e){
                host.raised(QString::fromUtf8(e.what()));
            }
            host.state(state_of(state, host));
        }
        host.finish_story();
    }catch (const Abort&){
        return host.message;
    }
    return QString();
}


}


int run_layout_checks(const QString& golden, QStringList& report, bool stop_at_first){
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the stories of the layout are not there: " + golden;
        return 1;
    }
    const QJsonObject root = QJsonDocument::fromJson(qUncompress(file.readAll())).object();
    const QJsonArray cases = root.value("cases").toArray();
    const double start = root.value("start").toDouble(1000.0);
    int failed = 0;
    std::vector<Story::Scene> cache;
    for (const QJsonValue& v : cases){
        const QJsonObject test_case = v.toObject();
        const QString what = play(test_case, start, cache);
        if (!what.isEmpty()){
            report << QString("FAILED: in the story '%1' the port does something else than the Python code: %2").arg(test_case.value("id").toString(), what);
            failed++;
            if (stop_at_first){
                return failed;
            }
        }
    }
    if (cases.isEmpty()){
        report << "FAILED: the file of the layout has no stories";
        return failed + 1;
    }
    report << QString("layout: %1 stories played, %2 went another way").arg(cases.size()).arg(failed);
    return failed;
}


}
}
}
}
