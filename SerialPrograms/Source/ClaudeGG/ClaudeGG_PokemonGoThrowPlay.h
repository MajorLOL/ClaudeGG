/*  Claude GG Pokemon GO Throw Play (the throw of a ball: holding it, timing the ring, letting it go, and learning from where it came down)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port of the throw of Mobile/gamebot.py (issue #31), the part that touches the phone (the readers and the sums are in
 *  ClaudeGG_PokemonGoThrow.h):
 *
 *  - throw_touch(): one throw as a single touch.  The finger goes down on the ball (and, for a curveball, turns circles); the ring of the
 *    Pokémon is looked at while the ball is held (in the live video it is followed for a moment, otherwise it is read from one or two
 *    screenshots), the throw is timed so that the ring has the wanted size when the ball leaves the hand, the ball is let go, and the
 *    pictures of the flight say how big the ring was and where the ball came down.  That is what the bot learns from (how fast the ring
 *    shrinks, how long a screenshot takes, how long the throw takes, how far a curveball has to be aimed to the side);
 *  - throw_ball(): one throw with what the person chose (the target ring: realistic, off, nice, great or excellent; curveballs).  A
 *    phone that cannot send single touch events gets a simple throw (aim() looks at the ring while the ball is held, then one swipe);
 *  - humanize(): the variation of a 'realistic' throw (the ring that is aimed at, a curve or not, the sideways aim, the length, the pause);
 *  - ring_track() and watch_flight(): the live video of the ring before the throw, and the pictures of the flight after it.
 *
 *  It knows nothing of the phone: it is given a Host, which adds to that of the map what a throw needs (commands that go on while the
 *  throw is looked at, the live video, the detector of the catch screen, the learned numbers on disk).  run_throwplay_checks() holds all of
 *  it, in every build, to tests/fixtures/throwplay_golden.json.qz that Mobile/tools/make_throwplay_golden.py made with the Python code:
 *  little stories (what happens when the ring is not seen, the video is there or not, the phone says no, the ball misses ...), the same pictures, detections and random numbers in, and the same commands, sleeps, log lines and learned numbers
 *  out, in the same order and at the same moments of a fake clock.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoThrowPlay_H
#define PokemonAutomation_ClaudeGG_PokemonGoThrowPlay_H

#include <functional>
#include <optional>
#include <utility>
#include <vector>
#include <opencv2/core.hpp>
#include <QJsonObject>
#include <QString>
#include <QStringList>
#include "ClaudeGG_PokemonGoMap.h"
#include "ClaudeGG_PokemonGoThrow.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Throw{


//  What the throw remembers (gamebot.cal, ring_shots, throw_stats and throw_info['hit']).
struct Memory{
    Cal cal;
    int ring_shots = 0;                 //  the last ring pictures that are kept (g_ring_1.png ... g_ring_6.png)
    int stats_n = 0;                    //  timed throws since the last statistic in the log ...
    int stats_on = 0;                   //  ... and how many of them got the ring size that was wanted
    std::optional<bool> hit;            //  did the last ball clearly come down on the Pokémon? (nothing: not known)
};

//  A screenshot that was asked for and is being taken: calling it gives the picture (or throws what went wrong).
using Later = std::function<cv::Mat()>;


//  ---- the phone and the parts of the app that a throw needs

class Host : public Map::Host{
public:
    //  The command that sends touch events: "input", or the faster "cmd input" (S.INPUT).
    virtual QStringList input_cmd() = 0;
    //  A place on the canvas (1768 x 2208) as a place on the real screen (S.to_real(): rounded to the nearest, half to even).
    virtual Point to_real(double x, double y) = 0;
    //  random.gauss(mu, sigma).
    virtual double gauss(double mu, double sigma) = 0;
    //  str(setting(key, default)): what the person chose, as the text that Python makes of it.
    virtual QString setting_text(const QString& key, const QString& fallback) = 0;

    //  Was the last quick_screenshot() a picture of the live video, and when was it taken (the monotonic clock)?
    virtual bool quick_live() = 0;
    virtual double quick_time() = 0;
    //  Does the live video run?  Its pictures of the next `seconds` seconds, at least `every` seconds apart: (monotonic time, picture).
    virtual bool live_on() = 0;
    virtual std::vector<std::pair<double, cv::Mat>> live_frames(double seconds, double every) = 0;
    //  A real screenshot that is taken meanwhile (S.screenshot() in a thread): the call that was asked for it returns at once.
    virtual Later screenshot_later() = 0;

    //  Commands for the phone that go on while the program does other things (subprocess.Popen(["adb", ...])); `argv` starts with "adb".
    //  The handle is for adb_communicate() (waits for the end, gives what the command wrote; capture: it was started to be read) and
    //  adb_wait().
    virtual int adb_start(const QStringList& argv, bool capture) = 0;
    virtual QString adb_communicate(int handle) = 0;
    virtual void adb_wait(int handle) = 0;
    //  A command for the phone that is waited for (S.adb(), without the "adb"); throws std::runtime_error when it fails.
    virtual void adb(const QStringList& args) = 0;

    //  The detector of the catch screen (Brain.encounter_objects) and the throw predictor (Brain.throw_params: deltaY and ms).
    virtual std::vector<Detection> encounter_objects(const cv::Mat& img) = 0;
    virtual std::pair<double, double> throw_params(double cx, double cy, double w, double h) = 0;

    //  What was learned is written down (save_cal()).
    virtual void save_cal(const Cal& cal) = 0;
};


//  ---- what is learned, on disk (~/gamebot_throw.json)

//  The numbers of `cal` as the file holds them (the file is the same with "v": CAL_VERSION added); rounded: the numbers as the
//  checks write them (round(x, 6)).  no_curve only when it is set.
QJsonObject cal_json(const Cal& cal, bool rounded);
//  The file of save_cal(): the numbers, and the version.
QJsonObject cal_file(const Cal& cal);
//  load_cal(): takes the numbers of a file of the right version (values learned with an older method are dropped).  False: not taken.
bool cal_load(Cal& cal, const QJsonObject& file);


//  ---- the throw

//  humanize(): what is drawn for one throw.
struct Humanized{
    QString target_name;                //  "nice", "great", "excellent" or "off"
    std::optional<double> target;       //  the ring size to aim for (nothing: no timing)
    bool curve = false;
    int aim_dx = 0;                     //  px, sideways
    double power = 1.0;                 //  factor for the length of the throw
    double pause = 0.0;                 //  s
};
Humanized humanize(Host& host, const QString& target_name, bool curve);

//  ring_track(): the sizes of the ring in the pictures of the live video, (monotonic-clock-free wall time, size) of the pictures where it
//  could be measured, and the detector's box of the ring (found on the first picture); empty when the video does not run or no ring is seen.
struct Track{
    std::vector<std::pair<double, double>> points;
    std::optional<Detection> box;
};
Track ring_track(Host& host, const cv::Mat& first, std::optional<double> t_first = std::nullopt);

//  watch_flight(): the pictures while the ball flies.  The first of them (empty: none came) and the x where the ball came down next to the
//  Pokémon.
struct Flight{
    cv::Mat first;
    std::optional<int> land;
};
Flight watch_flight(Host& host, const cv::Mat& before, const std::optional<Detection>& ring);

//  aim(): hold the ball (the ring appears then), take a screenshot and look for the ring.
std::optional<Detection> aim(Host& host);

//  throw_touch(): one throw as a single touch.  Returns the (wall) time of the release, or nothing when this phone cannot send single
//  touch events (the memory says so).  Throws what the phone throws (the finger is let go first).
std::optional<double> throw_touch(Host& host, Memory& memory, bool curve, std::optional<double> target, const QString& target_name,
                                  int aim_dx = 0, double power = 1.0);

//  throw_ball(): one throw, with the options of the person.  Returns the (wall) time at which the ball left the hand.
double throw_ball(Host& host, Memory& memory);


//  ---- the check

//  Plays the stories of tests/fixtures/throwplay_golden.json.qz (Mobile/tools/make_throwplay_golden.py) and says where the port does
//  something else than the Python code did.  Returns how many went another way ("FAILED: ..." lines in `report` say which, the last
//  line says how many were played).
//  stop_at_first: no more stories after the first one that went another way (for testing the check itself with faults that are put in).
int run_throwplay_checks(const QString& golden, QStringList& report, bool stop_at_first = false);


}
}
}
}
#endif
