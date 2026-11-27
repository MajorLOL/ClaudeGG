/*  Claude GG Pokemon GO Throw (what the throw of a ball looks at: the rings, the ball in the air, the buttons of the catch screen)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port of the readers and the sums of the throw of Mobile/gamebot.py (issue #31), the part of catching a Pokémon that looks at one
 *  picture or at some numbers (the throw itself, which touches the phone, is not here yet):
 *
 *  - measure_ring(): the size of the coloured, shrinking ring in relation to the white one, both thin circles around the Pokémon;
 *  - find_ball() and landing_x(): the ball in flight (a red blob that was not there before the throw) and where it came down;
 *  - enc_buttons(), in_encounter(), ball_ready() and result_ok_button(): the catch screen and the teal OK of the result screen;
 *  - ring_speed() and refit_timing(): how fast the ring shrinks and how long the screenshot takes, learned from the last throws;
 *  - curve_lean(), spin_points() and aim_note(): the curveball.
 *
 *  They are held, in every build, to Mobile/tests/fixtures/throw_golden.json.qz that Mobile/tools/make_throw_golden.py made with the
 *  Python code (run_throw_checks()): pictures drawn on the canvas as the file says, the same numbers out.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoThrow_H
#define PokemonAutomation_ClaudeGG_PokemonGoThrow_H

#include <array>
#include <optional>
#include <string>
#include <utility>
#include <vector>
#include <opencv2/core.hpp>
#include <QJsonObject>
#include <QString>
#include <QStringList>
#include "ClaudeGG_PokemonGoLoop.h"
#include "ClaudeGG_PokemonGoModels.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Throw{

using Loop::Point;
using Models::Detection;


//  ---- the numbers of the throw (the ones of gamebot.py that the later parts of the throw use too)

//  Where the ball lies at the bottom of the catch screen, and the buttons next to it (canvas of 1768 x 2208).
inline constexpr Point BALL_XY{877, 2017};
inline constexpr Point ENC_BERRY_BTN{212, 1840};
inline constexpr Point ENC_BALL_BTN{1539, 1840};

//  The ring (size 1.0: as big as the white ring) at which a throw is a Nice, a Great or an Excellent one.
inline constexpr double TARGET_NICE = 0.85;
inline constexpr double TARGET_GREAT = 0.50;
inline constexpr double TARGET_EXCELLENT = 0.20;

inline constexpr double TOUCH_SHOT = 0.25;              //  s after the finger goes down the screenshot of the ring is taken
inline constexpr double CURVE_SPINS = 2.5;              //  circles (clockwise) before a curveball
inline constexpr int CURVE_RADIUS = 140;                //  px, radius of the spin circle
inline constexpr int CURVE_D = 400;                     //  px left of the middle from where a curveball is thrown
inline constexpr int CURVE_LAND = 280;                  //  thrown straight up from there it lands this many px right of the middle
inline constexpr double CURVE_LEAN_GAIN = 2.35;         //  px the landing point moves per px the throw leans sideways
inline constexpr int CURVE_LEAN_MAX = 330;
inline constexpr double CURVE_POWER = 1.0;              //  > 1: a longer (harder) curveball throw
inline constexpr double RING_SPEED = 0.55;              //  the ring shrinks this much per second of holding
inline constexpr double RING_TRACK_S = 0.8;             //  s the ring is followed in the live video before the throw is timed
inline constexpr double RING_TRACK_EVERY = 0.1;         //  s at least between two pictures of the ring
inline constexpr int RING_LINE_MAX = 30;                //  px: the ring line is thin; thicker coloured bands are the Pokémon
inline constexpr double HIT_SHARE = 0.35;               //  a ball that lands within this share of the ring width from the middle is on the Pokémon
inline constexpr double TH_RING = 0.35;                 //  minimum certainty for the target ring while catching
inline constexpr int MAX_THROWS = 8;
inline constexpr double THROW_BOOST = 0.8;              //  duration factor of the throw (RegiBot default 0.8: 20 % harder)
inline constexpr double THROW_FALLBACK_DY = -1300.0;    //  deltaY and ms of the throw when the target ring is not found
inline constexpr double THROW_FALLBACK_MS = 250.0;
inline constexpr int CAL_VERSION = 5;

//  The 'realistic' throw (the standard profile): mostly Great, with variation.
inline constexpr const char* REAL_BASE = "great";      //  the ring that a 'realistic' throw goes for most of the time
//  The ring (the least and the most, as a share of the white one) that a throw that goes for a Nice, a Great or an Excellent one aims at.
inline constexpr double BAND_NICE_LO = 0.75;
inline constexpr double BAND_NICE_HI = 0.95;
inline constexpr double BAND_GREAT_LO = 0.36;
inline constexpr double BAND_GREAT_HI = 0.64;
inline constexpr double BAND_EXCELLENT_LO = 0.12;
inline constexpr double BAND_EXCELLENT_HI = 0.26;
//  What a throw that goes for a lower ring than asked for aims at (Excellent: Great, Great: Nice, Nice: none).
inline constexpr const char* LOWER_OF_EXCELLENT = "great";
inline constexpr const char* LOWER_OF_GREAT = "nice";
inline constexpr const char* LOWER_OF_NICE = "off";
inline constexpr double REAL_KEEP = 0.7;                //  share of the throws that go for the ring that was asked for ...
inline constexpr double REAL_LOWER = 0.2;               //  ... share that goes for the next lower one (the rest: no timing, on purpose)
inline constexpr double REAL_CURVE = 0.92;              //  share of the curveballs that are thrown as one
inline constexpr double REAL_AIM = 45.0;                //  px, spread of the sideways aim
inline constexpr double REAL_SLOPPY_SHARE = 0.07;       //  share of the throws that are sloppy ...
inline constexpr double REAL_SLOPPY_AIM = 220.0;        //  ... px, spread of their aim
inline constexpr double REAL_POWER = 0.03;              //  spread of the throw length (3 %)
inline constexpr double REAL_PAUSE_MIN = 0.3;           //  s: short pause before a throw ...
inline constexpr double REAL_PAUSE_MAX = 1.6;
inline constexpr double REAL_LONG_PAUSE_SHARE = 0.06;   //  ... and now and then (share) a longer one of 2.5 - 6 s
inline constexpr double REAL_LONG_PAUSE_MIN = 2.5;
inline constexpr double REAL_LONG_PAUSE_MAX = 6.0;

//  After the throw.
inline constexpr double RESULT_FIRST_LOOK = 2.0;
inline constexpr double RESULT_WINDOW = 20.0;
inline constexpr double POLL_PAUSE = 0.3;
inline constexpr double POLL_PAUSE_LIVE = 0.05;
inline constexpr double AFTER_OK_WAIT = 1.5;
inline constexpr double AFTER_TAP_WAIT = 2.0;
inline constexpr double FAST_BACK_AFTER = 1.2;
inline constexpr double FAST_BACK_LATEST = 5.0;
inline constexpr double FAST_LOOK_AFTER = 1.0;


//  ---- the rings

//  The ring of a Pokémon on the catch screen.
struct Ring{
    double ratio = 0.0;                 //  the coloured ring as a share of the white one (1.0: full size)
    int rw = 0;                         //  radius of the white ring
    int rc = 0;                         //  radius of the coloured ring
    int cx = 0;                         //  the middle
    int cy = 0;
    double q = 0.0;                     //  how well the coloured ring was seen
};

//  Why the last measure_ring() ended as it did (for the log): what each part found, when it got that far.
struct RingDiag{
    std::optional<double> white;        //  how well the white ring fitted
    std::optional<double> colour;       //  how well the coloured ring was seen
    std::optional<double> size;         //  its size as a share of the white one, when there was one
    bool has_size = false;              //  (the search for the coloured ring was done)
};

//  np.percentile(values, 80) of float32 numbers, as numpy makes it (method 'linear', all in float32): the threshold of the edges.
float percentile80(std::vector<float> values);

//  The size of the coloured ring in relation to the white one.  `box` is the detector's box of the white ring (found only while the
//  rings are visible).  Nothing when the white ring or the coloured ring is not seen well enough.
std::optional<Ring> measure_ring(const cv::Mat& img, const Detection& box, RingDiag* diag = nullptr);


//  ---- the ball in the air

struct Ball{
    int x = 0;
    int y = 0;
    int area = 0;
};

//  The flying ball in a screenshot: a red blob that was not there before the throw (`before`).
std::optional<Ball> find_ball(const cv::Mat& img, const cv::Mat& before);

//  Where the ball came down next to the Pokémon (the x in the pictures of the flight, from above onto the Pokémon of `ring`), or nothing.
std::optional<int> landing_x(const std::vector<cv::Mat>& imgs, const cv::Mat& before, const Detection* ring);


//  ---- the catch screen

//  The two round grey buttons (berries left, balls right): they are there whenever the ball lies ready.
bool enc_buttons(const cv::Mat& img);
//  The catch screen: a big red ball at the bottom in the middle (and not the map).
bool in_encounter(const cv::Mat& img);
bool ball_ready(const cv::Mat& img);
//  The teal OK pill of the 'TOTAL XP' screen after a catch: the middle of the button, or nothing.
std::optional<Point> result_ok_button(const cv::Mat& img);


//  ---- what is learned from the throws

//  (gamebot.cal)
struct Cal{
    double k = 0.55;                    //  ring shrink per second of holding
    double c = 0.3;                     //  s between asking for a screenshot and the moment it is taken
    double lat = 55.0;                  //  ms per injected touch event
    double rel = 0.3;                   //  s the throw itself takes
    double aim = 0.0;                   //  px correction of the curveball landing point
    std::vector<std::array<double, 3>> obs;         //  last throws: (ring measured, s until release, ring at release)
    double c_live = -0.12;              //  the same as c for a picture of the live video
    std::vector<std::array<double, 3>> obs_live;    //  ... and the throws that were timed with the live video
};

//  The shrink speed of the ring (size per second) from pictures taken one after another (time, size), or nothing.
std::optional<double> ring_speed(const std::vector<std::pair<double, double>>& points);
//  Learn k (and the c of the kind of picture) from the last throws.
void refit_timing(Cal& cal, bool live);


//  ---- the curveball

//  Sideways pixels of the throw so that the curveball lands at screen x = target_x (nothing: the middle).
int curve_lean(const Cal& cal, std::optional<int> target_x);
//  Clockwise circles next to the ball, ending on their left side.
std::vector<Point> spin_points();
//  For the log: what the deliberate sideways offset of a 'realistic' throw means.
QString aim_note(int aim_dx, int ring_w = 460);


//  ---- the numbers (for the check): every number above under the name of the Python code (the dicts as objects, the tuples as arrays)
QJsonObject throw_constants();

//  Holds all of it to the file of the Python code (the report gets a line for every difference).  Returns how many there were.
int run_throw_checks(const QString& golden, QStringList& report);


}
}
}
}

#endif
