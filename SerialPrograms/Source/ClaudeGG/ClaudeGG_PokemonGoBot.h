/*  Claude GG Pokemon GO Bot (Claude GG itself plays Pokémon GO on the phone of the Pi: the steps of the bot over the agent)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The parts of Mobile/gamebot.py that are ported to C++ (the step, the map, the stop, ...: issue #31) are given a Host and know nothing of
 *  the phone.  PhoneBot is that Host for a phone on a Raspberry Pi: what it sees and taps goes through Phone::AgentHost (the agent of
 *  Mobile/agent), the map and the screens are read with the ONNX models of the folder of the bot, and the parts that are not ported yet are
 *  switched off in a way that leaves the game alone:
 *
 *  - catching: the ported catch screen (Catch::do_encounter) with the ported throw (Throw::throw_ball: a single touch through /v1/touch of
 *    agent 0.2.2, or a plain swipe), the berries read with Tesseract; when catching is off, a catch screen is left with the run-away button;
 *  - Team GO Rocket (Rocket::rocket_battle: the speech bubbles, BATTLE, the radar question, the party, the summary; RocketFight::rocket_fight: the
 *    fast taps, the shield, the little game of the charged attack, over the live video when there is one): the ported code when the
 *    switch "rocket_fight" is on; when it is off the step goes back out of it and leaves that stop alone for 30 minutes;
 *  - the gifts of the friends (Gifts::gifts_round: open the ones that wait, send one to every friend; the memory of the day is a file in the
 *    folder of the bot) and the clean-up of a full bag (Bag::clean_bag, the red FULL marks of the main menu): the ported code, with the keys
 *    and the closing of the game that the bag needs sent to the agent (see shell()); when the storage and the bag are both full and the game
 *    has been closed, the bot stops (gamebot.py waits there until it sees the game running again - `pidof` -, which the agent cannot tell);
 *  - the GO Pass (Quests::claim_quests: the quest button that turns gold, the tab GO PASS, VIEW REWARDS, CLAIM ALL; the memory of the last look is in
 *    the program): the ported code, over the same touches and swipes;
 *  - the temperatures: from the agent (0.2.4 and later: /v1/heat); with an older agent the pause when it gets hot does not happen;
 *  - the layout of the screen: taken to be the one of the canvas (the agent brings every screenshot to the canvas);
 *  - the camera that turns while the next picture is looked at: the swipe is made right away and waited for, which is slower but the same
 *    swipe;
 *  - the live video: not used for looking or throwing yet (screenshots only).
 *
 *  The commands for the phone that the throw makes (Throw::Host::adb_start(), adb()) are the shell lines of gamebot.py; PhoneBot reads the
 *  touch events and swipes out of them and sends those to the agent (nothing else is sent), the ones that the throw does not wait for in a
 *  thread of their own.
 *
 *  run() is the loop of gamebot.py around step(): a step, its wait, and an error in a step is told and waited out (10 s).  Experimental: not
 *  tried on a real phone yet.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoBot_H
#define PokemonAutomation_ClaudeGG_PokemonGoBot_H

#include <functional>
#include <memory>
#include <mutex>
#include <thread>
#include <map>
#include <optional>
#include <random>
#include <utility>
#include <vector>
#include <opencv2/core.hpp>
#include <QByteArray>
#include <QJsonValue>
#include <QString>
#include <QStringList>
#include "ClaudeGG_PokemonGoBag.h"
#include "ClaudeGG_PokemonGoBrain.h"
#include "ClaudeGG_PokemonGoDaily.h"
#include "ClaudeGG_PokemonGoGifts.h"
#include "ClaudeGG_PokemonGoLayout.h"
#include "ClaudeGG_PokemonGoLock.h"
#include "ClaudeGG_PokemonGoPhone.h"
#include "ClaudeGG_PokemonGoQuests.h"
#include "ClaudeGG_PokemonGoRocket.h"
#include "ClaudeGG_PokemonGoStep.h"
#include "ClaudeGG_PokemonGoThrowPlay.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Bot{

using Loop::Point;
using Models::Detection;


//  The map detector of the models of the phone, for Brain::Eyes (the part `box` of the picture is looked at on its own).
class PhoneDetector : public Brain::Detector{
public:
    explicit PhoneDetector(Phone::AgentHost& phone) : m_phone(phone){}
    std::vector<Detection> map(const cv::Mat& img, const cv::Rect& box, double threshold, int top) override;

private:
    Phone::AgentHost& m_phone;
};


//  What the bot is asked to do: the switches of the program ("spin", "catch", "fast_look", ...), as they are given to the Python bot.
using Switches = std::map<QString, bool>;

//  The switches that PhoneBot plays with: those of the program, with what is not ported yet switched off.  `heat`: the agent can tell the
//  temperatures (0.2.4 and later); the pause for the heat is switched off when it cannot.
Switches playable(const Switches& asked, bool heat = false);


//  What the person chose that is not a switch: "throw_target" (realistic, nice, great, excellent, off), "ball" and "berries" (the order,
//  comma separated, as BERRY_ORDER of gamebot.py).
using Texts = std::map<QString, QString>;


class PhoneBot : public Step::Host, public Throw::Host, public virtual Bag::Host, public Gifts::Host, public Rocket::Host, public Daily::Host, public Lock::Host, public Layout::Host{
public:
    //  `folder`: where what the throws learn is kept (gamebot_throw.json); empty: nowhere.
    PhoneBot(Phone::AgentHost& phone, const Switches& switches, const Texts& texts = Texts(), const QString& folder = QString());
    ~PhoneBot() override;

    Map::State& map_state(){ return m_map; }
    Step::State& step_state(){ return m_step; }
    Daily::State& daily_state(){ return m_daily; }
    //  The pauses that were given to the timers (the full bag, the full storage) are over: switch it on again.  Called before every step.
    void timers();
    //  "(this run: 3 stops, 1 caught, 0 fled)".
    QString counts() const;

    //  ---- Loop::Host
    double monotonic() override{ return m_phone.monotonic(); }
    void sleep(double seconds) override{ m_phone.sleep(seconds); }
    void log(const QString& text) override{ m_phone.log(text); }
    Loop::Stream* stream() override{ return m_phone.stream(); }
    std::unique_ptr<Loop::Tapper> make_tapper(Point fast, int ms) override{ return m_phone.make_tapper(fast, ms); }
    bool on_map(const cv::Mat& canvas) override{ return m_phone.on_map(canvas); }
    Nav::Lines ocr_lines(const cv::Mat& img, int y0 = 0, std::optional<int> y1 = {}, double scale = 1.0) override{
        return m_phone.ocr_lines(img, y0, y1, scale);
    }
    QString ocr_line(const cv::Mat& img, int lines = 1) override{ return m_phone.ocr_line(img, lines); }
    bool give_up_enabled() override{ return m_phone.give_up_enabled(); }
    bool aim_enabled() override{ return m_phone.aim_enabled(); }
    void aim_disabled() override{ m_phone.aim_disabled(); }
    QString league() override{ return m_phone.league(); }
    Fight::Known load_seen() override{ return m_phone.load_seen(); }
    void save_seen(const Fight::Known& known) override{ m_phone.save_seen(known); }
    std::map<QString, Minigame::Learned> load_minigames() override{ return m_phone.load_minigames(); }
    void save_minigames(const std::map<QString, Minigame::Learned>& learned) override{ m_phone.save_minigames(learned); }
    void save_picture(const QString& name, const cv::Mat& img) override{ m_phone.save_picture(name, img); }
    void beat() override{ m_phone.beat(); }
    bool stop() override{ return m_phone.stop(); }

    //  ---- Flow::Host
    double wall() override{ return m_phone.wall(); }
    void tap(int x, int y) override{ m_phone.tap(x, y); }
    void swipe(int x1, int y1, int x2, int y2, int ms) override{ m_phone.swipe(x1, y1, x2, y2, ms); }
    void back() override{ m_phone.back(); }
    std::pair<QString, double> screen_class(const cv::Mat& img) override{ return m_phone.screen_class(img); }
    void restart_game() override{ m_phone.restart_game(); }

    //  ---- Start::Host
    void stop_game() override{ m_phone.stop_game(); }
    void start_game() override{ m_phone.start_game(); }
    Start::Launch start_state() override{ return m_phone.start_state(); }
    void start_end() override{ m_phone.start_end(); }

    //  ---- Map::Host
    cv::Mat quick_screenshot() override;
    void swipe_async(int x1, int y1, int x2, int y2, int ms) override{ m_phone.swipe(x1, y1, x2, y2, ms); }
    double uniform(double lo, double hi) override;
    double unit() override;
    bool setting(const QString& key, bool fallback) override;
    bool wanted(const QString& key) override;
    QString count(const QString& key) override;
    void gifts_round() override;
    void check_menu_full() override;
    void check_all_full() override;
    int clean_bag() override;
    void bag_to_map() override;
    void resume_spin_later() override;

    //  ---- Bag::Host
    void swipes(const std::vector<Loop::Stroke>& strokes) override{ m_phone.swipes(strokes); }
    //  The shell lines of the bag as the agent can do them: `am force-stop <package>` (/v1/app) and `input keyevent KEYCODE_X` (/v1/key).
    //  `pidof <package>` cannot be answered: the bot says so and stops (Flow::Interrupted).  Any other line throws std::runtime_error.
    QString shell(const QStringList& args) override;
    QJsonValue bag_keep_saved() override;
    void run_done() override;

    //  ---- Gifts::Host  (package() is that of the bag too)
    void tap_press(int x, int y, int ms) override{ m_phone.press(x, y, ms); }
    QString package() override{ return m_phone.package(); }
    QString today() override{ return Phone::today_text(); }
    //  The memory of the day is a file in the folder of the bot (in the memory of the program when there is no folder).
    std::optional<QByteArray> gift_state_read(const QString& file) override;
    void gift_state_write(const QString& file, const QByteArray& json) override;

    //  ---- Catch::Host
    std::vector<Detection> buttons(const cv::Mat& img) override{ return m_phone.buttons(img); }
    bool quick_live() override{ return false; }
    double throw_ball(std::optional<bool>& hit) override;
    QString ball() override;
    QStringList berry_order() override;
    std::optional<QString> tray_table(const cv::Mat& gray) override{ return m_phone.ocr_table(gray); }
    double step() override{ return Step::step(*this, m_map, m_step); }

    //  ---- Throw::Host
    QStringList input_cmd() override{ return {"input"}; }
    Point to_real(double x, double y) override;
    double gauss(double mu, double sigma) override;
    QString setting_text(const QString& key, const QString& fallback) override;
    double quick_time() override{ return m_quick_t; }
    bool live_on() override{ return false; }
    std::vector<std::pair<double, cv::Mat>> live_frames(double, double) override{ return {}; }
    Throw::Later screenshot_later() override;
    int adb_start(const QStringList& argv, bool capture) override;
    QString adb_communicate(int handle) override;
    void adb_wait(int handle) override;
    void adb(const QStringList& args) override;
    std::vector<Detection> encounter_objects(const cv::Mat& img) override{ return m_phone.encounter_objects(img); }
    std::pair<double, double> throw_params(double cx, double cy, double w, double h) override;
    void save_cal(const Throw::Cal& cal) override;

    //  ---- Rocket::Host
    QString screen_state(const cv::Mat& small) override;
    void rocket_fight() override;

    //  ---- Step::Host
    std::pair<std::optional<double>, std::optional<double>> read_heat() override;
    //  The shape of the screen and the check of the layout (ClaudeGG_PokemonGoLayout.h).
    //  (An agent before 0.2.6 cannot change the display or read the switch files: the check is off then, as it was before it was ported.)
    bool layout_active() const{ return m_phone.reads_display(); }
    bool screen_ok() override{ return !layout_active() || m_layout.screen.ok; }
    QString layout_state() override{ return layout_active() ? m_layout.state : QString("confirmed"); }
    bool layout_adapt(const QString& why) override{ return layout_active() && Layout::layout_adapt(m_layout, *this, why); }
    void wait_unsupported() override{
        if (layout_active()){
            Layout::wait_unsupported(m_layout, *this);
        }else{
            sleep(5);
        }
    }
    void layout_watch() override{
        if (layout_active()){
            Layout::layout_watch(m_layout, *this);
        }
    }
    void layout_verify(const cv::Mat& img) override{
        if (layout_active()){
            Layout::layout_verify(m_layout, *this, img);
        }
    }
    //  What `dumpsys power` says: "mWakefulness=Awake" or not (the agent says which; an agent before 0.2.5 cannot: the phone is taken as awake).
    QString power_state() override;
    void key_wakeup() override{ m_phone.wake(); }
    //  The swipe lock screen and the game that dims and locks itself (ClaudeGG_PokemonGoLock.h).
    void unlock() override{ Lock::unlock(*this); }
    cv::Mat unlock_game(const cv::Mat& img) override{ return Lock::unlock_game(*this, img); }

    //  ---- Layout::Host  (/v1/info and /v1/display of the agent; an agent before 0.2.6 cannot change the display or read the switch files)
    QString wm_size_text() override;
    void wm_size_set(const QString& size) override;
    void wm_size_reset() override;
    std::optional<QString> record_text() override;
    QString record_write(const QJsonObject& record) override;
    void record_forget() override;
    bool file_exists(const QString& which) override;
    QString file_path(const QString& which) override;
    std::optional<Layout::ScreenRead> read_screen(bool wake) override;
    void reset_same_screen() override{ m_step.same_screen.name.reset(); m_step.same_screen.count = 0; }
    //  The start of a run: look at the screen of the phone (the log says what it is) and take over a display change that an earlier run did not put back.
    void layout_start();
    //  The end of a run: put the display size back when this bot changed it.
    void layout_end();
    //  Layout::screen_seen() for the size of the last screenshot: called after every screenshot of the bot.
    cv::Mat screenshot() override;

    //  ---- Lock::Host  (/v1/power and /v1/unlock of the agent; an agent before 0.2.5 has none: no lock screen is seen then)
    bool keyguard_showing() override;
    void dismiss_keyguard() override;
    cv::Mat quick_screenshot_grab(const std::function<void()>& on_grab) override;
    bool quests_due(const cv::Mat& img) override;
    QString claim_quests() override;
    QString rocket_battle() override{ return Rocket::rocket_battle(*this); }
    double do_map(const cv::Mat& img) override;
    double do_pokestop(const cv::Mat& img) override;
    double do_encounter(const cv::Mat& img) override;
    void resume_catch_later(double seconds) override;

    //  ---- Daily::Host  (the daily run: see ClaudeGG_PokemonGoDaily.h; what the person set is in the texts "daily_time", "daily_max_min",
    //  "battle_app", "battle_league", "battle_count" and "daily_force")
    double daily_step() override;
    //  The file of the run is gamebot_daily.json in the folder of the bot (in the memory of the program when there is no folder).
    std::optional<QJsonObject> read_daily() override;
    void write_daily(const QJsonObject& daily) override;
    QJsonValue setting_value(const QString& key) override;
    //  The apps that the agent lists (agent 0.2.3), the Play Store one first; the Play Store one alone when it cannot.
    QStringList game_packages() override;
    bool battle_wanted() override;
    QString battle_app() override;
    void set_package(const QString& package) override{ m_phone.set_package(package); }
    void reset_for_game() override;
    //  `am force-stop`, then the recent apps ("close all"), then the home screen: the game is gone, not running in the background.
    void close_game_completely() override;
    //  The battles of the run (Start::auto_battle: GO Battle League through Flow::battle_run of the phone's host).  The run's beat() and time_up()
    //  are the phone's hooks while they go on; the person's stop (the program is stopped) ends them; a Pokémon of a reward is caught by the steps.
    Start::AutoBattle auto_battle(const QString& package, const Daily::Beat& beat, const Daily::Ask& stop, const Daily::Ask& time_up) override;
    //  The weekly teams are not ported: never due.
    bool teams_due(const QString& package) override;
    void teams_refresh(const QString&, const Daily::Ask&) override{}
    //  There is no watchdog: the program is stopped by the person, and every call to the phone has a time limit.
    void watchdog(const QString&, bool) override{}
    double slot_time(double now, int hours, int minutes) override;
    QString local_text(double moment) override;

private:
    //  The files of the bot (the memory of the day of the gifts, the file of the daily run): in the folder, or in the memory of the program.
    std::optional<QByteArray> read_file(const QString& file);
    bool write_file(const QString& file, const QByteArray& data);
    Start::Settings battle_settings();
    //  A command of the throw for the phone, sent to the agent: what the phone wrote (throws std::runtime_error when the agent says no).
    QString send(const QStringList& args);
    struct Running{
        std::thread thread;
        QString out;
        QString error;
    };

    Phone::AgentHost& m_phone;
    Switches m_switches;
    Texts m_texts;
    QString m_folder;
    Throw::Memory m_memory;
    double m_quick_t = 0.0;
    std::mutex m_running_lock;
    std::map<int, std::unique_ptr<Running>> m_running;
    int m_next_handle = 1;
    PhoneDetector m_detector;
    Brain::Eyes m_eyes;
    Map::State m_map;
    Step::State m_step;
    Bag::State m_bag;
    Quests::State m_quests;                             //  when the quests were looked at last
    Daily::State m_daily;                               //  what the daily run remembers between two calls
    std::map<QString, QByteArray> m_files;              //  the files of the gifts and of the daily run when there is no folder
    QStringList m_team_names;                           //  the team of the battles
    int m_won = 0;
    int m_lost = 0;
    bool m_told_packages = false;
    bool m_told_teams = false;
    std::mt19937_64 m_random;
    std::optional<double> m_spin_at;
    std::optional<double> m_catch_at;
    bool m_told_heat = false;
    bool m_told_power = false;
    void told_no_power();
    Layout::State m_layout;
    std::optional<MobileDisplayFiles> display_files();   //  the files of the Pi for the display (nothing when the agent cannot say)
    int m_stops = 0;
    int m_caught = 0;
    int m_fled = 0;
};


//  The loop of the bot: step after step (the daily run when "daily_cycle" is on: Daily::daily_cycle() instead of a step) until the person stops it
//  (Flow::Interrupted is thrown then).  Every step `beat` is told how it goes (it may be empty).
void run(PhoneBot& bot, const std::function<void()>& beat = std::function<void()>());


}
}
}
}
#endif
