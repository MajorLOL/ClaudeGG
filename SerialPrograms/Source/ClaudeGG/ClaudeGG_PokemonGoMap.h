/*  Claude GG Pokemon GO Map (a step on the map of the Pokémon GO bot: a Pokémon, a PokéStop, the camera)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port of what Mobile/gamebot.py and Mobile/spin_stop.py do with the map of the game (issue #31):
 *
 *  - do_map(): what to do with a screenshot of the map.  A Pokémon that is sure enough is looked at a second time on a new screenshot
 *    (an effect that only flashes by and a camera that was still turning are gone then) and tapped; a PokéStop that has not been
 *    spun (it is not purple) is opened; when there is nothing, the camera is turned a little and the map looked at again, in rounds
 *    of about 400 degrees, with swipes of random length, height and speed.  Fast looking starts the swipe the moment the screenshot
 *    has been taken (fire_rotation()) and looks at that picture meanwhile; when something is found in it the camera is turned back
 *    first (undo_rotation()).  The same step starts the gifts of the hour or the day, keeps an eye on the gold Poké Ball button of
 *    the full storage and checks a fast catch (the game was left with BACK while the ball came down) on the map;
 *  - do_pokestop(): the screen of a stop: swipe the photo until the ring around it turns purple (looking again and again, no fixed
 *    wait), and close it; a message that the bag is full cleans the bag or pauses the spinning;
 *  - the readers of pixels: ring_spun(), bag_full(), looks_spun() (a stop in the colour of a stop that was spun) and box_full_ball().
 *
 *  Like the rest it knows nothing of the phone: it is given a Host, which adds to that of the start what a step needs (a quick
 *  screenshot, a swipe that does not wait, the random numbers, the settings of the person, the counts of the day, and the parts that
 *  are not here yet: the gifts, the full bag and the full storage).  run_map_checks() holds all of it, in every build, to
 *  tests/fixtures/map_golden.json.qz that Mobile/tools/make_map_golden.py made with the Python code: the same pictures and
 *  detections in, and the same taps, swipes, log lines, sleeps and calls out, in the same order and at the same moments of a fake
 *  clock, with the same things remembered afterwards.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoMap_H
#define PokemonAutomation_ClaudeGG_PokemonGoMap_H

#include <optional>
#include <utility>
#include <vector>
#include <opencv2/core.hpp>
#include <QString>
#include <QStringList>
#include "ClaudeGG_PokemonGoBrain.h"
#include "ClaudeGG_PokemonGoStart.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Map{

using Loop::Point;


//  ---- the readers of pixels (spin_stop.py and gamebot.py)

//  The stop screen: is the ring around the photo purple (the stop was spun)?
bool ring_spun(const cv::Mat& img);
//  The stop screen: the pink message 'Your Item Bag is full.'?
bool bag_full(const cv::Mat& img);
//  The map: has the Poké Ball button a gold middle (the Pokémon storage is full)?
bool box_full_ball(const cv::Mat& img);
//  Is this stop purple (spun already)?  The detector is sometimes unsure about that, the colour is not.
bool looks_spun(const cv::Mat& img, const Brain::Detection& stop);


//  ---- what a step remembers

struct Swipe{
    int x1 = 0;
    int y1 = 0;
    int x2 = 0;
    int y2 = 0;
    int ms = 0;
};

struct Fired{
    double t = 0;                       //  when the swipe was started
    Swipe swipe;
};

//  Turning the camera (gamebot.rotation).
struct Rotation{
    int steps = 0;                      //  steps done in this round
    double turned = 0.0;                //  pixels turned so far
    double goal = 0.0;                  //  pixels this round turns
    int dir = 1;                        //  1 or -1
    std::optional<Swipe> armed;         //  fast looking: the next swipe ...
    double armed_at = 0.0;              //  ... and when it was armed
    std::optional<Fired> fired;         //  the swipe that was just started
};

//  The Pokémon that is being caught (gamebot.enc).
struct Encounter{
    double start = 0.0;
    int throws = 0;
    bool berry = false;
    bool ball_set = false;
    bool caught = false;
    double t_throw = 0.0;
    double t_result = 0.0;
    double t_tap = 0.0;
};

//  A fast catch that waits for its check on the map (gamebot.fast_pending).
struct FastPending{
    std::optional<Point> xy;
    double t = 0.0;
    double t_throw = 0.0;
    double t_back = 0.0;
    int looks = 0;
};

//  What was tapped on the map last (gamebot.last_tap).
struct LastTap{
    std::optional<QString> kind;
    std::optional<Point> xy;
    std::optional<std::vector<Point>> alt;
    bool near = false;
};

//  How long the looks of the rounds took (gamebot.perf), for the log line that starts a round.
struct Perf{
    int looks = 0;
    double shot = 0.0;
    double detect = 0.0;
    double total = 0.0;
    double wait = 0.0;
    std::optional<double> t_step;       //  when the step began (the part of the bot that runs the steps writes it)
};

//  A place on the map that is left alone until `until`.
struct Cool{
    int x = 0;
    int y = 0;
    double until = 0.0;
};

//  A screenshot that was already taken (and looked at) while waiting for the catch result: the next step reuses it (gamebot.handoff).
struct Handoff{
    cv::Mat img;                        //  empty: there is none
    double t = 0.0;
};

//  What gamebot.py keeps in its globals for the map and the stop.
struct State{
    bool spin = true;                   //  SPIN: spinning stops is on (the full bag pauses it)
    bool catching = true;               //  CATCH: catching is on (the full storage pauses it)
    std::vector<Cool> cooldown;
    Encounter enc;
    std::optional<Point> enc_xy;
    std::optional<bool> throw_hit;      //  throw_info['hit']
    FastPending fast_pending;
    Handoff handoff;
    int fast_fails = 0;                 //  fast_state: in a row
    double fast_off_until = 0.0;
    LastTap last_tap;
    double near_until = 0.0;            //  near_state['until']
    Rotation rotation;
    Perf perf;
    bool storage_full = false;
    bool bag_is_full = false;           //  bag_state['full']
    std::optional<double> bag_cleaned;  //  bag_state['cleaned']
    double menu_check_last = 0.0;
    double gift_last = 0.0;
};


//  ---- the phone, the person and the parts that come later

class Host : public Start::Host{
public:
    //  A screenshot that may be a little older and faster (S.quick_screenshot()); screenshot() is the real one.
    virtual cv::Mat quick_screenshot() = 0;
    //  A swipe that does not wait for its end (S.swipe_async()).
    virtual void swipe_async(int x1, int y1, int x2, int y2, int ms) = 0;
    //  random.uniform(lo, hi) and random.random().
    virtual double uniform(double lo, double hi) = 0;
    virtual double unit() = 0;
    //  The options of the person: setting(key, default) as a yes or no, and 'is this on in the web interface' (on when not set).
    virtual bool setting(const QString& key, bool fallback) = 0;
    virtual bool wanted(const QString& key) = 0;
    //  The count of the day after counting one more of "caught", "fled" or "stops": "(today: 3 caught, ...)".
    virtual QString count(const QString& key) = 0;
    //  The parts that are not here yet.
    virtual void gifts_round() = 0;                 //  open the gifts of the friends and send them
    virtual void check_menu_full() = 0;             //  is the bag full as well (through the main menu)?
    virtual void check_all_full() = 0;
    virtual int clean_bag() = 0;                    //  throw away what is too much; how many kinds were thrown away (throws std::runtime_error)
    virtual void bag_to_map() = 0;                  //  back to the map after a clean-up that failed
    virtual void resume_spin_later() = 0;           //  spinning stops is switched on again after BAG_FULL_WAIT
};


//  ---- the steps

//  The swipe of a camera step and the seconds to wait for the camera to come to rest (rotate_swipe()).
std::pair<Swipe, double> rotate_swipe(Host& host, int direction);
//  Called the moment a screenshot has been taken: starts the swipe that was armed (if it was armed less than 20 s ago).
void fire_rotation(Host& host, State& state);
//  The seconds until the camera has come to rest after a swipe that was started.
double settle_left(Host& host, const Fired& fired);
//  The camera was turned on right after the picture was taken and a Pokémon or stop in that picture is wanted: turn it back and look
//  again.  True when that was done.
bool undo_rotation(Host& host, State& state, const std::optional<Fired>& fired);
//  Is the place (x, y) left alone for the moment?  (Takes the places whose time is over out of the list.)
bool cooled(Host& host, State& state, int x, int y);
//  Forget the Pokémon that was being caught (and say it fled when no ball won it).
void reset_encounter(Host& host, State& state);

//  What a step does with a screenshot of the map.  Returns the seconds to wait before the next step.
double do_map(Host& host, State& state, Brain::Eyes& eyes, const cv::Mat& img);
//  What a step does at the screen of a PokéStop.  Returns the seconds to wait.
double do_pokestop(Host& host, State& state, const cv::Mat& img);

//  A fast catch that waits for its check: is the Pokémon still where it was (nothing: no fast catch waits)?
std::optional<bool> fast_check(Host& host, State& state, const std::vector<Brain::Detection>& objs);
//  What do_map does with the first look after a fast catch: the seconds to wait (look once more), or nothing (carry on).
std::optional<double> fast_verdict(Host& host, State& state, const std::vector<Brain::Detection>& objs);


//  The numbers of the map by their names in gamebot.py and spin_stop.py ("S." in front of those), for the check.
std::vector<std::pair<QString, std::vector<double>>> map_constants();


//  ---- the check
//
//  Plays the pictures and the stories of the file of Mobile/tools/make_map_golden.py (tests/fixtures/map_golden.json.qz) and says
//  where the port does something else than the Python code did.  Returns how many went another way ("FAILED: ..." lines in `report`
//  say which, the last line says how many were played).
int run_map_checks(const QString& golden, QStringList& report);


}
}
}
}
#endif
