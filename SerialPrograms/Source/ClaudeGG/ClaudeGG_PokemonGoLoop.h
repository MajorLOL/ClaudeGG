/*  Claude GG Pokemon GO Loop (the fight loop of the Pokémon GO bot)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port of fight_battle() of Mobile/gamebot.py (issue #30): it looks at the screen all the time (Eyes: the live video
 *  of the phone, or screenshots), taps the fast attacks in the background (a Tapper), reads the names and the labels of
 *  the buttons next to the loop (a Looker), throws a charged attack when the fight (Fight) wants one and then swipes
 *  its little game (LittleGame), answers the questions of the game and ends on the result screen.
 *
 *  The loop knows nothing of the phone, the clock or the text reader: it is given a Host.  The checks of the port
 *  (run_loop_checks) give it a host that plays back the fights of tests/fixtures/loop_golden.json.qz - the pictures
 *  and the answers of the text reader that the Python loop was given - and say where what the loop does differs from
 *  what the Python loop did.  What the app gives it (the adb bridge, Tesseract) is not part of this file.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoLoop_H
#define PokemonAutomation_ClaudeGG_PokemonGoLoop_H

#include <atomic>
#include <condition_variable>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <thread>
#include <utility>
#include <vector>
#include <opencv2/core.hpp>
#include <QString>
#include <QStringList>
#include "ClaudeGG_PokemonGoBattle.h"
#include "ClaudeGG_PokemonGoFight.h"
#include "ClaudeGG_PokemonGoMinigame.h"
#include "ClaudeGG_PokemonGoNav.h"
#include "ClaudeGG_PokemonGoVision.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Loop{


//  The canvas of the phone (the size that all places on the screen are given in) and the small picture that the readers of a fight look at.
inline constexpr int REF_W = 1768;
inline constexpr int REF_H = 2208;
inline constexpr int VIEW_W = 704;
inline constexpr int VIEW_H = 880;

//  A place on the canvas, in pixels.
struct Point{
    int x = 0;
    int y = 0;
    bool operator==(const Point& o) const{ return x == o.x && y == o.y; }
};
//  A swipe on the canvas: from (x1, y1) to (x2, y2) in ms milliseconds.
struct Stroke{
    int x1 = 0;
    int y1 = 0;
    int x2 = 0;
    int y2 = 0;
    int ms = 0;
};
//  What the little game of a charged attack asks for: the swipes to make now (none: the fast taps go on).
typedef std::function<std::vector<Stroke>()> Planner;

//  What Eyes::look() gives: the picture on the canvas, the small one the readers use, and when it came in.
struct Look{
    cv::Mat canvas;
    cv::Mat small;
    double t = 0;
};


//  ---- what the loop is connected to

//  The live video of the phone (battle_stream.FrameStream).
class Stream{
public:
    virtual ~Stream() = default;
    virtual bool healthy() = 0;
    virtual bool starting() = 0;
    //  The next picture after `seq` (timeout seconds at most, and not one taken before `not_before`); false: none came.
    virtual bool wait_new(long long seq, double timeout, double not_before, long long& seq_out, double& t, cv::Mat& small) = 0;
    virtual QString describe() = 0;
    virtual void close() = 0;
};

//  What taps the fast attacks in the background and, for the little game of a charged attack, swipes its icons.
//  Every touch is a command of its own and two at once spoil each other: the taps of the loop (tap(), touch())
//  wait for the one that is running and go before the next one.
class Tapper{
public:
    virtual ~Tapper() = default;
    virtual void go() = 0;                                  //  fast taps on
    virtual void pause() = 0;                               //  ... off
    virtual void aim(const std::optional<Point>& xy) = 0;   //  tap the fast attacks here (nothing: in the usual place)
    virtual void sweep(const Planner& planner) = 0;         //  swipe what it gives; an empty one: no little game (any more)
    virtual void tap(int x, int y, int ms = 120) = 0;
    //  Another kind of touch for the question 'Switch in a new Pokémon?': 0 a quick tap, 1 finger down and up,
    //  2 a press of 60 ms, 3 a press of 220 ms.
    virtual void touch(int how, int x, int y) = 0;
    virtual int taps() const = 0;
    virtual int swipes() const = 0;
    virtual void close() = 0;
};

//  The touches of the phone, for the Tapper that has a thread of its own.
class Fingers{
public:
    virtual ~Fingers() = default;
    virtual void tap(int x, int y, int ms) = 0;
    virtual void swipes(const std::vector<Stroke>& strokes) = 0;
    virtual void quick(int x, int y) = 0;
    virtual void motion(int x, int y) = 0;
};

//  The Tapper of the app: a thread that taps the fast attacks (or swipes what the planner of the little game gives).
class ThreadedTapper : public Tapper{
public:
    ThreadedTapper(Fingers& fingers, Point xy, int ms);
    ~ThreadedTapper() override;

    void go() override;
    void pause() override;
    void aim(const std::optional<Point>& xy) override;
    void sweep(const Planner& planner) override;
    void tap(int x, int y, int ms = 120) override;
    void touch(int how, int x, int y) override;
    int taps() const override{ return m_taps; }
    int swipes() const override{ return m_swipes; }
    void close() override;

private:
    void run();

    Fingers& m_fingers;
    Point m_xy;
    int m_ms;
    std::mutex m_lock;                      //  one touch at a time
    std::mutex m_state;                     //  what is set from the loop
    std::condition_variable m_wake;
    std::atomic<bool> m_on{false};
    std::atomic<bool> m_hold{false};        //  the loop wants to tap: the fast taps wait
    std::atomic<bool> m_quit{false};
    Planner m_sweep;
    std::optional<Point> m_aim;
    std::atomic<int> m_taps{0};
    std::atomic<int> m_swipes{0};
    std::thread m_thread;
};

//  Everything else the loop needs from the app.
class Host{
public:
    virtual ~Host() = default;

    virtual double monotonic() = 0;                         //  seconds (time.monotonic())
    virtual void sleep(double seconds) = 0;
    virtual void log(const QString& text) = 0;

    //  A screenshot on the canvas (1768 x 2208); throws (std::exception) when the phone does not answer.
    virtual cv::Mat screenshot() = 0;
    //  The live video of this fight; nothing: screenshots only.
    virtual Stream* stream() = 0;
    virtual std::unique_ptr<Tapper> make_tapper(Point fast, int ms) = 0;
    //  Is the map of the game on the screen?
    virtual bool on_map(const cv::Mat& canvas) = 0;
    //  What a picture of a fight shows (the readers of battle_vision).  The checks change it for the story in which the name boxes
    //  are never recognised.
    virtual Vision::Seen features(const cv::Mat& small){ return Vision::features(small); }
    //  The verdict of a fight that is lost (Fight::hopeless).  The checks tell the fight that it is lost in one story (a test of the
    //  Python loop does so); nothing else gives an answer here.
    virtual std::optional<std::pair<bool, QString>> hopeless(Fight::Fight& fight, int foes){ (void)fight; (void)foes; return std::nullopt; }

    //  The text reader: the lines of a part of the picture (rows y0 to y1, scaled), or one line of text.
    virtual Nav::Lines ocr_lines(const cv::Mat& img, int y0 = 0, std::optional<int> y1 = {}, double scale = 1.0) = 0;
    virtual QString ocr_line(const cv::Mat& img, int lines = 1) = 0;

    //  The options, and what earlier fights taught.
    virtual bool give_up_enabled() = 0;                     //  'Give up a lost battle'
    virtual bool aim_enabled() = 0;                         //  fast attacks tapped on the button that is wanted next
    virtual void aim_disabled() = 0;                        //  they do not count there: not in the next fights either
    virtual QString league() = 0;
    virtual Fight::Known load_seen() = 0;
    virtual void save_seen(const Fight::Known& known) = 0;
    virtual std::map<QString, Minigame::Learned> load_minigames() = 0;
    virtual void save_minigames(const std::map<QString, Minigame::Learned>& learned) = 0;

    //  A picture to keep for looking at afterwards.
    virtual void save_picture(const QString& name, const cv::Mat& img) = 0;

    //  Called every picture; stop() true ends the loop.
    virtual void beat(){}
    virtual bool stop(){ return false; }
    //  False: the thread that reads the names is not started, the names are read when they are asked for (the checks).
    virtual bool threads(){ return true; }
    //  What the checks listen to: told when the looker starts to read ("ask" or "banner").
    virtual std::function<void(const char*)> looker_trace(){ return std::function<void(const char*)>(); }
    //  No screen check and no screenshot test while the fight is on (the seconds it can take at most).
    virtual void busy(double seconds){ (void)seconds; }
};


//  ---- the parts of the loop

//  The pictures of the fight: the live video (about ten a second) and, when that gives none, screenshots (one to three
//  seconds each).  look() gives the picture on the canvas, the small one for the readers of battle_vision (six times as fast)
//  and when it came in.
class Eyes{
public:
    explicit Eyes(Host& host);
    Look look(double not_before = 0.0);
    //  A real screenshot for reading text (a video picture is small); the canvas when that is one already, or when none comes.
    cv::Mat real(const cv::Mat& canvas);
    void close();

    long long seq = 0;
    int live = 0;
    int shots = 0;
    QString mode;
    bool video = false;                 //  the last picture came from the live video

private:
    void say_mode(const QString& mode, const QString& note = QString());

    Host& m_host;
    Stream* m_stream;
    double m_said = 0.0;
    int m_told = 0;
};

//  Is the map of the game on the screen (the Poké Ball menu button at the bottom: red on top, white below)?  The picture is the
//  canvas, 1768 x 2208.  (An app can give this to Host::on_map().)
bool map_visible(const cv::Mat& canvas);

//  The white words in a part of the picture (fractions of it): banners and the big words of a result screen, read on their own.
QString white_words(Host& host, const cv::Mat& pic, double x0, double y0, double x1, double y1, int lines = 1, double wide = 1900.0);
//  The big white words in the middle of the result screen of a battle: 'YOU WIN!' or 'GOOD EFFORT!' (two lines), read on their own.
QString result_words(Host& host, const cv::Mat& pic);
//  Does the screen show a running fight (name boxes, or a question with its countdown)?  (gamebot._fight_on_screen)
bool fight_on_screen(Host& host);

//  Reads the names in the name boxes and the labels under the buttons (and the banner of the foe's charged attack) next to
//  the loop: the text reader takes seconds on a Pi, and a charged attack is worth more than a name.
class Looker{
public:
    Looker(Host& host, Fight::Fight& fight, std::recursive_mutex& lock);
    ~Looker();

    void start();
    void close();
    //  A picture of the fight, read for names and labels when they are wanted and the last reading is finished.
    void ask(const cv::Mat& shot);
    //  A picture taken while the banner of the foe's charged attack can be up: read it when the last reading is finished.
    void read_banner(const cv::Mat& shot);
    //  The reading of the picture that waits (the thread does this; the checks do it at once).
    void work();
    double used_at() const{ return m_used_at; }

    bool video = false;                 //  the pictures come from the live video (small text is hard to read)
    //  Told when a reading starts: "ask" or "banner" (the checks listen).
    std::function<void(const char*)> trace;

private:
    void run();

    Host& m_host;
    Fight::Fight& m_fight;
    std::recursive_mutex& m_flock;
    cv::Mat m_shot;
    QString m_what = "names";
    std::atomic<bool> m_busy{false};
    std::atomic<bool> m_quit{false};
    std::atomic<double> m_used_at{0.0};
    int m_empty = 0;                    //  name boxes that gave nothing, in a row
    std::mutex m_wake_lock;
    std::condition_variable m_wake;
    bool m_woken = false;
    std::thread m_thread;
};

//  The little game of one charged attack (see Minigame::Game): the loop gives it the pictures, the tapper asks it for the swipes.
class LittleGame{
public:
    LittleGame(const Battle::Move& move, double t0, const std::map<QString, Minigame::Learned>& learned, int button);

    Minigame::Points look(const cv::Mat& small);
    Minigame::Points others(const cv::Mat& small) const;
    void see(const Minigame::Points& icons, double t);
    std::vector<Stroke> strokes(double now);
    bool over(double now);
    int view(bool fight, bool bars, int need = 1, std::optional<double> now = {});
    bool started(double now);
    void give_up();
    void hold(double now);
    QString report() const;

    Battle::Move move;
    int button = 0;                     //  the charged attack button that was tapped (0 left, 1 right)
    Minigame::Game game;
    std::mutex lock;
    bool on = false;                    //  its icons were seen: the attack was thrown, the little game runs
    bool saved = false;
    std::optional<int> mon;             //  the Pokémon that threw it
    bool held = false;                  //  the other side's attack went first: ours is waited for
    double asked = 0.0;
    int lit = 0;
    int plain = 0;
    int zoomed = 0;
    bool doubt = false;
    bool late = false;
    bool ready = false;
    int back = 0;
    bool unseen = false;
    std::optional<Battle::Move> alt;
    int alt_n = 0;
    bool race = false;
};


//  ---- the loop

struct Result{
    QString result;                     //  "win", "loss" or "" (why says why)
    QString why;
    int seconds = 0;
    bool gave_up = false;
};

//  Plays the battle that is about to start (or is going on) until its result screen (or until `why`).  use_spots: where
//  USE THIS PARTY is, tapped again when the party screen is still there after a while.
Result fight_battle(Host& host, const std::vector<Battle::Mon>& team, const std::vector<Point>& use_spots = {});


//  The numbers of the loop by their names in gamebot.py (and battle_fight.py), for the check: it holds them to the
//  numbers that the file of fights has from Python.
std::vector<std::pair<QString, std::vector<double>>> loop_constants();


//  ---- the check
//
//  Plays the fights of the file of Mobile/tools/make_loop_golden.py (tests/fixtures/loop_golden.json.qz) on the
//  pictures in `fixtures` (tests/fixtures), with the data of the engine (models/battle_data.json), and says where
//  the port does something else than the Python loop did.  Returns how many fights went another way ("FAILED: ..." lines
//  in `report` say which, the last line says how many were played).
int run_loop_checks(const QString& golden, const QString& fixtures, const QString& data, QStringList& report);


}
}
}
}
#endif
