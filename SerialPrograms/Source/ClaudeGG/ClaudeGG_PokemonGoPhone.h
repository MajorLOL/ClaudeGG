/*  Claude GG Pokemon GO Phone (what the fight loop of the Pokemon GO bot is connected to, in C++)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The fight loop (ClaudeGG_PokemonGoLoop) asks its Host for everything outside of it: the clock, the picture of
 *  the phone, the touches, the text reader and the places where it keeps what it learns.  AgentHost answers for a
 *  phone on a Raspberry Pi: the pictures and the touches go through the agent of Mobile/agent (MobileAgent and
 *  MobileVideo of ClaudeGG_Mobile), the text is read by the tesseract program (ClaudeGG_PokemonGoText).
 *
 *  - the live video of the agent (/v1/video, JPEG pictures 704 wide: the size that the readers of the fight were made
 *    on) is the Stream of the loop; its pictures are stamped with the time they came in;
 *  - the screenshot (/v1/screen) is brought to the canvas of the bot (1768 x 2208) as spin_stop._normalize does;
 *  - the touches (the canvas is brought to the real screen as spin_stop.to_real does) are the calls of the agent: a
 *    press, a plain tap and finger down / finger up;
 *  - for the walk around a fight (ClaudeGG_PokemonGoFlow) and the start of the game (ClaudeGG_PokemonGoStart) it also
 *    gives the clock of the day, BACK, the screen classifier (the ONNX models of ClaudeGG_PokemonGoModels, when they are
 *    there; else every screen is "onbekend" as in gamebot.py), closing and starting the app (/v1/app of the agent) and the
 *    day on which the battles were done (battle_done.json of gamebot.py); what only the program knows (the count of
 *    the day, the team, the time of the run) is given through Hooks;
 *  - what was seen of the foes and what the little games learned is kept in battle_seen.json and battle_minigame.json
 *    in the folder of the bot, in the format of gamebot.py (the files can be copied from the Pi).
 *
 *  Held, in every build, by the test of the agent (the touches and the pictures reach the made-up phone as asked)
 *  and by the files that are written and read back; not yet tried on a real phone.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoPhone_H
#define PokemonAutomation_ClaudeGG_PokemonGoPhone_H

#include <atomic>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <utility>
#include <vector>
#include <opencv2/core.hpp>
#include <QString>
#include <QStringList>
#include "ClaudeGG_Mobile.h"
#include "ClaudeGG_PokemonGoBattle.h"
#include "ClaudeGG_PokemonGoLoop.h"
#include "ClaudeGG_PokemonGoModels.h"
#include "ClaudeGG_PokemonGoStart.h"
#include "ClaudeGG_PokemonGoText.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Phone{

using Loop::Fingers;
using Loop::Host;
using Loop::Point;
using Loop::Stream;
using Loop::Stroke;
using Loop::Tapper;
using Loop::ThreadedTapper;


//  What the program asks of the fights (the options of the bot).
struct Options{
    bool video = true;                  //  the live video (the screenshots when it gives no pictures); false: screenshots only
    bool give_up = true;                //  'Give up a lost battle'
    bool aim = true;                    //  the fast attacks are tapped on the button that is wanted next
    QString league;                     //  the league of the battles (the names of the screens it shows)
    QString folder;                     //  where it keeps what it learns, and the pictures it saves
    QString tesseract;                  //  the tesseract program; empty: it is looked for
    QString package = "com.nianticlabs.pokemongo";   //  the Pokémon GO app that is closed and started
    QString models;                     //  the folder of the ONNX models of the screen classifier (CLAUDEGG_MODELS); empty: none
};

//  What only the program that runs the bot knows.  Every one may be empty.
struct Hooks{
    std::function<QString(const QString&)> day_count;   //  the count of the day after a fight ("(today: 3 won)"), key "won" or "lost"
    std::function<QStringList()> team_names;            //  the names of the Pokémon of the team
    std::function<bool()> no_more;                      //  the time of the run is up: no new battle
    std::function<void()> beat;                         //  the bot is alive: called every now and then
};

//  Seconds on the clock of the loop (the time pictures are stamped with).
double now_seconds();


//  The live video of the agent as the Stream of the loop.
class AgentStream : public Stream{
public:
    //  The picture is brought to 704 x 880 (the size of the video of gamebot.py) when the agent made another one.
    AgentStream(const QString& host, int port, const QString& token, int fps = 10);
    ~AgentStream() override;

    bool healthy() override;
    bool starting() override;
    bool wait_new(long long seq, double timeout, double not_before, long long& seq_out, double& t, cv::Mat& small) override;
    QString describe() override;
    void close() override;
    bool closed() const{ return m_closed; }

private:
    MobileVideo m_video;
    double m_started = 0;
    std::atomic<bool> m_closed{false};
    std::atomic<long long> m_frames{0};
    std::atomic<double> m_last{0};
};

//  The touches of the phone, as calls of the agent.  The coordinates are those of the canvas.
class AgentFingers : public Fingers{
public:
    //  `width` and `height`: the real screen (/v1/info); 0: the canvas itself.  `log`: where a touch that failed is told.
    AgentFingers(const MobileAgent& agent, int width, int height, std::function<void(const QString&)> log);

    void tap(int x, int y, int ms) override;
    void swipes(const std::vector<Stroke>& strokes) override;
    void quick(int x, int y) override;
    void motion(int x, int y) override;

    //  Canvas to the real screen (spin_stop.to_real).
    Point to_real(int x, int y) const;
    //  The real screen is this big (a screenshot says so).
    void set_screen(int width, int height);

private:
    void touch(const QString& kind, int x, int y, int ms);
    void failed(const QString& what, const QString& why);

    MobileAgent m_agent;
    std::atomic<int> m_width;
    std::atomic<int> m_height;
    std::function<void(const QString&)> m_log;
};


//  The Host of the loop, the walk and the start of the game for a phone on a Raspberry Pi.
class AgentHost : public Start::Host{
public:
    //  `log`: the lines of the log (from any thread); `stop`: true ends the fight (asked often).
    AgentHost(const QString& address, int port, const QString& token, const Options& options,
              std::function<void(const QString&)> log, std::function<bool()> stop = std::function<bool()>());
    ~AgentHost() override;

    double monotonic() override;
    void sleep(double seconds) override;
    void log(const QString& text) override;
    cv::Mat screenshot() override;
    Stream* stream() override;
    std::unique_ptr<Tapper> make_tapper(Point fast, int ms) override;
    bool on_map(const cv::Mat& canvas) override;
    Nav::Lines ocr_lines(const cv::Mat& img, int y0 = 0, std::optional<int> y1 = {}, double scale = 1.0) override;
    QString ocr_line(const cv::Mat& img, int lines = 1) override;
    bool give_up_enabled() override{ return m_options.give_up; }
    bool aim_enabled() override{ return m_aim; }
    void aim_disabled() override{ m_aim = false; }
    QString league() override{ return m_options.league; }
    Fight::Known load_seen() override;
    void save_seen(const Fight::Known& known) override;
    std::map<QString, Minigame::Learned> load_minigames() override;
    void save_minigames(const std::map<QString, Minigame::Learned>& learned) override;
    void save_picture(const QString& name, const cv::Mat& img) override;
    bool stop() override;
    void beat() override;

    //  The walk (Flow::Host).  The touches are those of the loop; a BACK that does not reach the phone throws, as `adb` of gamebot.py does.
    double wall() override;
    void tap(int x, int y) override;
    void swipe(int x1, int y1, int x2, int y2, int ms) override;
    void back() override;
    std::pair<QString, double> screen_class(const cv::Mat& img) override;
    void restart_game() override;
    //  The other readers of the models (the ONNX models of the folder of Options::models): what the map shows (Brain._ssd with the map
    //  detector on the picture as it is given) and the buttons that can be clicked.  Nothing when there are no models.
    bool has_models();
    std::vector<Models::Detection> map_objects(const cv::Mat& img, double threshold, int top);
    std::vector<Models::Detection> buttons(const cv::Mat& img);
    //  Wake the screen of the phone up (/v1/wake of the agent; what fails is told in the log).
    void wake();
    //  The detector of the catch screen and the throw predictor (Brain.encounter_objects, Brain.throw_params); nothing / the fallback of
    //  gamebot.py's throw when there are no models.
    std::vector<Models::Detection> encounter_objects(const cv::Mat& img);
    std::optional<std::pair<double, double>> throw_params(double cx, double cy, double w, double h);
    //  The table of the text reader for a picture (Text::Reader::table()).
    std::optional<QString> ocr_table(const cv::Mat& img){ return m_reader.table(img); }
    //  The agent itself (its calls take places on the real screen).
    const MobileAgent& agent() const{ return m_agent; }
    void mark_battles_done() override;
    QString day_count(const QString& key) override;
    QStringList team_names() override;
    bool no_more() override;

    //  Closing and starting the game (Start::Host): /v1/app of the agent.
    void stop_game() override;
    void start_game() override;
    Start::Launch start_state() override;
    void start_end() override;

    //  What the program knows (see Hooks); set it before the bot runs.
    void set_hooks(const Hooks& hooks){ m_hooks = hooks; }
    //  Did the Battle screen show a grey BATTLE button today (battle_done.json of the folder of the bot)?
    bool battles_done_today() const;
    //  The team to fight with: battle_team.json of the folder of the bot (the preset when there is none; Battle::load_team() says what
    //  a file that cannot be used does).  What Start::auto_battle() is given as its TeamLoader: [&]{ return host.load_team(); }.
    std::vector<Battle::Mon> load_team() const;

    //  The size of the real screen the agent told (0: not known).
    int screen_width() const{ return m_width; }
    int screen_height() const{ return m_height; }

private:
    QString m_address;
    int m_port;
    QString m_token;
    Options m_options;
    std::function<void(const QString&)> m_log;
    std::function<bool()> m_stop;
    MobileAgent m_agent;
    Text::Reader m_reader;
    std::unique_ptr<AgentFingers> m_fingers;
    std::unique_ptr<AgentStream> m_stream;
    std::atomic<bool> m_aim;
    std::atomic<int> m_width{0};
    std::atomic<int> m_height{0};
    Hooks m_hooks;
    std::optional<Start::Launch> m_launch_failed;   //  the start of the game that did not even reach the agent
    std::mutex m_models_lock;
    std::unique_ptr<Models::Models> m_models;
    bool m_models_failed = false;
    Models::Models* models_locked();               //  (with m_models_lock held) opened the first time; nothing when it cannot be
    void models_broke(const std::exception& e);
};


//  The files of what the bot learns, in the format of gamebot.py (load_seen(), save_seen(), load_minigames(),
//  save_minigames()); an empty result when the file is not there or is not right.
Fight::Known read_seen(const QString& file);
bool write_seen(const QString& file, const Fight::Known& known);
std::map<QString, Minigame::Learned> read_minigames(const QString& file);
bool write_minigames(const QString& file, const std::map<QString, Minigame::Learned>& learned);

//  A picture of the screen (a QImage of the agent) as the picture of OpenCV the readers work on (BGR, 8 bits).
cv::Mat mat_of(const QImage& picture);
//  The screenshot on the canvas of the bot: bigger ones are brought down with INTER_AREA, smaller ones up with
//  INTER_LINEAR (spin_stop._normalize).
cv::Mat canvas_of(const cv::Mat& screen);


//  The day of battle_done.json of gamebot.py: "YYYY-MM-DD" of the local time.
QString today_text();

//  The check of the files and of the pictures (what does not need a phone): the files of what is seen and learned are
//  read back as they were written and are the files of gamebot.py; the pictures and the touches are as they are asked.
int run_phone_checks(QStringList& report);


}
}
}
}
#endif
