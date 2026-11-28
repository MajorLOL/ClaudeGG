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
 *  - catching: a catch screen is left with the run-away button (spinning only: no Pokémon is tapped on the map);
 *  - Team GO Rocket: not battled (the step goes back out of it and leaves that stop alone for 30 minutes);
 *  - the GO Pass, the gifts and the clean-up of the bag: not done (a full bag pauses the spinning for 30 minutes, as the bot does without
 *    its clean-up);
 *  - the temperatures: the agent cannot read them yet, so the pause when it gets hot does not happen;
 *  - the layout of the screen: taken to be the one of the canvas (the agent brings every screenshot to the canvas);
 *  - the camera that turns while the next picture is looked at: the swipe is made right away and waited for (the agent takes one call at a
 *    time), which is slower but the same swipe.
 *
 *  run() is the loop of gamebot.py around step(): a step, its wait, and an error in a step is told and waited out (10 s).  Experimental: not
 *  tried on a real phone yet.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoBot_H
#define PokemonAutomation_ClaudeGG_PokemonGoBot_H

#include <functional>
#include <map>
#include <optional>
#include <random>
#include <utility>
#include <vector>
#include <opencv2/core.hpp>
#include <QString>
#include "ClaudeGG_PokemonGoBrain.h"
#include "ClaudeGG_PokemonGoPhone.h"
#include "ClaudeGG_PokemonGoStep.h"

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

//  The switches that PhoneBot plays with: those of the program, with what is not ported yet switched off.
Switches playable(const Switches& asked);


class PhoneBot : public Step::Host{
public:
    PhoneBot(Phone::AgentHost& phone, const Switches& switches);

    Map::State& map_state(){ return m_map; }
    Step::State& step_state(){ return m_step; }
    //  The pauses that were given to the timers (the full bag, the full storage) are over: switch it on again.  Called before every step.
    void timers();
    //  "(this run: 3 stops, 1 caught, 0 fled)".
    QString counts() const;

    //  ---- Loop::Host
    double monotonic() override{ return m_phone.monotonic(); }
    void sleep(double seconds) override{ m_phone.sleep(seconds); }
    void log(const QString& text) override{ m_phone.log(text); }
    cv::Mat screenshot() override{ return m_phone.screenshot(); }
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
    cv::Mat quick_screenshot() override{ return m_phone.screenshot(); }
    void swipe_async(int x1, int y1, int x2, int y2, int ms) override{ m_phone.swipe(x1, y1, x2, y2, ms); }
    double uniform(double lo, double hi) override;
    double unit() override;
    bool setting(const QString& key, bool fallback) override;
    bool wanted(const QString& key) override;
    QString count(const QString& key) override;
    void gifts_round() override{}
    void check_menu_full() override{}
    void check_all_full() override{}
    int clean_bag() override;
    void bag_to_map() override{ m_phone.back(); }
    void resume_spin_later() override;

    //  ---- Catch::Host
    std::vector<Detection> buttons(const cv::Mat& img) override{ return m_phone.buttons(img); }
    bool quick_live() override{ return false; }
    double throw_ball(std::optional<bool>& hit) override;
    QString ball() override{ return "poke"; }
    QStringList berry_order() override{ return QStringList(); }
    std::optional<QString> tray_table(const cv::Mat&) override{ return std::nullopt; }
    double step() override{ return Step::step(*this, m_map, m_step); }

    //  ---- Step::Host
    std::pair<std::optional<double>, std::optional<double>> read_heat() override;
    bool screen_ok() override{ return true; }
    QString layout_state() override{ return "confirmed"; }
    bool layout_adapt(const QString&) override{ return false; }
    void wait_unsupported() override{ sleep(5); }
    void layout_watch() override{}
    void layout_verify(const cv::Mat&) override{}
    QString power_state() override{ return "mWakefulness=Awake"; }
    void key_wakeup() override{ m_phone.wake(); }
    void unlock() override{}
    cv::Mat unlock_game(const cv::Mat& img) override{ return img; }
    cv::Mat quick_screenshot_grab(const std::function<void()>& on_grab) override;
    bool quests_due(const cv::Mat&) override{ return false; }
    QString claim_quests() override{ return "failed"; }
    QString rocket_battle() override{ return "failed"; }
    double do_map(const cv::Mat& img) override;
    double do_pokestop(const cv::Mat& img) override;
    double do_encounter(const cv::Mat& img) override;
    void resume_catch_later(double seconds) override;

private:
    Phone::AgentHost& m_phone;
    Switches m_switches;
    PhoneDetector m_detector;
    Brain::Eyes m_eyes;
    Map::State m_map;
    Step::State m_step;
    std::mt19937_64 m_random;
    std::optional<double> m_spin_at;
    std::optional<double> m_catch_at;
    bool m_told_heat = false;
    int m_stops = 0;
    int m_caught = 0;
    int m_fled = 0;
};


//  The loop of the bot: step after step until the person stops it (Flow::Interrupted is thrown then).  Every `beat_every` seconds `beat`
//  is told how it goes (it may be empty).
void run(PhoneBot& bot, const std::function<void()>& beat = std::function<void()>());


}
}
}
}
#endif
