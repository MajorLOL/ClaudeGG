/*  Claude GG Pokemon GO Minigame (the little game of a charged attack)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port to C++ of Mobile/battle_minigame.py (issue #30).  When a charged
 *  attack is thrown the game shows, for about five seconds, 32 round icons of
 *  the attack's type; every icon that is touched makes the attack stronger.
 *  Two parts:
 *
 *    find_icons()   where the icons are on a picture of the game (fractions of
 *                   the screen), the same OpenCV steps as the Python code
 *    Game           one little game: see() for every picture, plan() for the
 *                   swipes to make now, over() for the end of it.  A stream of
 *                   icons gets a "gate" (a line across it that the finger
 *                   swipes there and back), a row that stands still gets a
 *                   swipe along it, a type that is not known starts with a
 *                   cross over the middle of the screen and learns.
 *
 *  No phone, no OCR: the loop that takes the pictures and does the swiping
 *  (gamebot.py) is not ported yet.  Mobile/tools/make_minigame_golden.py makes
 *  a file with what battle_minigame.py answers (316 pictures asked for their
 *  icons, 239 games of 25,000 steps) and run_minigame_checks() holds this port
 *  to it in every build (--mobile-test).
 *
 *  One thing differs from what the Python code did before this port: the
 *  direction of the main axis of a group of icons, which NumPy leaves to its
 *  linear algebra library (either way along the line).  Python and C++ now
 *  both take the way that points to the right (down when it is vertical).
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoMinigame_H
#define PokemonAutomation_ClaudeGG_PokemonGoMinigame_H

#include <optional>
#include <utility>
#include <vector>
#include <opencv2/core.hpp>
#include <QString>
#include <QStringList>

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Minigame{


//  A point of the screen: (x, y) in fractions of its width and its height.
using Point = std::pair<double, double>;
using Points = std::vector<Point>;

//  A line piece (x1, y1, x2, y2).
struct Line{
    double x1 = 0;
    double y1 = 0;
    double x2 = 0;
    double y2 = 0;
    bool operator==(const Line& other) const{
        return x1 == other.x1 && y1 == other.y1 && x2 == other.x2 && y2 == other.y2;
    }
};

//  A swipe: from (x1, y1) to (x2, y2) in ms milliseconds.
struct Swipe{
    double x1 = 0;
    double y1 = 0;
    double x2 = 0;
    double y2 = 0;
    int ms = 0;
};

//  What a game found, for the next game of the same type: the rows where icons
//  stood still and the gate of the stream.
struct Learned{
    std::vector<Line> rows;
    std::vector<Line> gates;
};


//  ---- the numbers (see the Python file for what they mean) -------------------------------------------------

inline constexpr double ICON_R = 0.065;
inline constexpr int GRID_W = 141;
inline constexpr int COLOUR_TOL = 42;
inline constexpr double TOP = 0.22;
inline constexpr double ASPECT = 2208 / 1768.0;

inline constexpr double SPEED = 5.0;
inline constexpr int MIN_MS = 45;
inline constexpr double REACH = 0.07;
inline constexpr double REACH_MOVING = 0.11;
inline constexpr double SIDE_MOVING = 0.035;
inline constexpr double LINE_GAP = 0.105;
inline constexpr int MAX_LINES = 5;
inline constexpr int MAX_SWIPES = 6;
inline constexpr double CHAIN_GAP = 0.30;
inline constexpr double CHAIN_BEND = 0.45;
inline constexpr double FRESH = 0.8;
inline constexpr double STILL = 0.03;
inline constexpr double STILL_FROM = 0.08;
inline constexpr double STILL_TO = 0.32;
inline constexpr double STILL_FOR = 0.2;
inline constexpr double MOVED = 0.17;
inline constexpr double GAME_SECONDS = 10.0;
inline constexpr double GET_READY = 1.5;
inline constexpr double QUIET = 1.2;
inline constexpr double ICONS_FOR = 4.5;
inline constexpr double ROW_LIFE = 3.0;
inline constexpr int GATE_ICONS = 12;
inline constexpr double GATE_LONG = 0.40;
inline constexpr double GATE_NEAR = 0.2;
inline constexpr double GATE_SIDE = 0.07;
inline constexpr double GATE_HALF = 0.12;
inline constexpr int GATE_TIMES = 4;
inline constexpr double LEAD = 2.8;
inline constexpr double HOLD = 25.0;


//  ---- the icons on a picture ---------------------------------------------------------------------------------

//  The colour of the icons of a type (R, G, B): false for a type that does not exist.
bool type_colour(const QString& kind, int rgb[3]);

//  Middles of the icons of type "kind" on a picture (8 bit, BGR), the clearest first.  An icon is a disc in
//  the colour of the type with a white drawing in its middle: its ring has the colour, what lies around it has
//  not and its middle has some white.  Nothing for an unknown type or an empty picture.
Points find_icons(const cv::Mat& img, const QString& kind, double top = TOP, int limit = 12);


//  ---- geometry -------------------------------------------------------------------------------------------------

//  The distance between two points in screen widths.
double dist(const Point& a, const Point& b);
//  Points that belong together (each within "link" of another one), every group in the order of the line it forms.
std::vector<Points> groups(const Points& points, double link = 0.26);
//  The distance (screen widths) from a point to a line piece.
double near_line(const Point& p, const Line& row);


//  ---- one little game ------------------------------------------------------------------------------------------

//  The state is public, as the attributes of the Python class are: the checks look at it.
class Game{
public:
    //  "kind": the type of the charged attack, "t0": when it was thrown, "learned": what earlier games of this
    //  type found (learned()).
    explicit Game(const QString& kind, double t0 = 0.0, const std::optional<Learned>& learned = std::nullopt);

    //  The icons found on the picture that was taken at time t.
    void see(double t, const Points& icons);
    //  What this game found, to give to the next Game of this type; nothing when nothing was seen, or when the
    //  type is known from recordings.
    std::optional<Learned> learned() const;

    //  The attack has to wait (the other side threw one in the same turn and theirs goes first): from now on only
    //  icons that are seen are swiped, until started(), and the game is given up "wait" seconds from now.
    void hold(double now, double wait = HOLD);
    //  The banner "Get Ready!" is on the screen: the attack starts now.
    void started(double now);
    //  Is the little game over?
    bool over(double now) const;
    //  Do the icons of this group move (true), stand still (false), or can that not be told (yet)?
    std::optional<bool> moving(const Points& grp) const;
    //  The swipes to make now; none when the icons are not there yet or the game is over.
    std::vector<Swipe> plan(double now);

    struct Frame{
        double t = 0;
        Points icons;
    };
    //  A row that was seen standing still, and when ("no time": known beforehand).
    struct Row{
        Line line;
        std::optional<double> seen;
    };

    QString kind;
    double t0 = 0;
    std::vector<Frame> frames;
    std::optional<double> first;
    std::optional<double> last;
    int pictures = 0;
    int icons = 0;
    int swipes = 0;
    std::vector<Row> rows;
    Points trail;
    std::optional<Line> gate;
    std::vector<Line> prior;
    bool builtin = false;
    int turn = 0;
    bool blind = true;
    bool plain = true;

private:
    void remember(const Line& row, std::optional<double> t);
    void find_gate();
    std::vector<Swipe> paint(const Points& grp, bool moving, bool flip) const;
};


//  ---- the check ---------------------------------------------------------------------------------------------------

//  Holds the port to the answers in "golden" (the file of make_minigame_golden.py, packed by qCompress()),
//  with the pictures in "fixtures" (tests/fixtures/minigame).  How many cases were answered differently; the
//  report says which, and ends with a line that says how many were checked.
int run_minigame_checks(const QString& golden, const QString& fixtures, QStringList& report);


}
}
}
}
#endif
