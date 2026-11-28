/*  Claude GG Pokemon GO Catch (the catch screen around the throw of the Pokémon GO bot)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port of what Mobile/gamebot.py does at the catch screen around the throw itself (issue #31):
 *
 *  - do_encounter(): the whole encounter - run away when the storage is full, the start of the catch (log line, picture), the limit of
 *    throws, the choice of ball, the berry that is picked from the tray, the throw loop (the throw itself is Throw::throw_ball, the fast
 *    catch is checked on the way) and how long to wait after it;
 *  - wait_for_result(): after a throw, look at the screen again and again until the ball is back in the hand (a miss, or the Pokémon broke
 *    free), the result screen ('TOTAL XP') shows its teal OK button (it is tapped right there) or another screen is there (the picture is
 *    handed to the next step, there is no second screenshot of the same screen);
 *  - fast_catch_leave() and finish_catch(): what to do when the catch is over (the screen kinds map, exit, discard, bag, menu and other of
 *    gamebot's _screen_kind, which is not the Nav one);
 *  - catch_result_button(), tap_catch_result() and mark_caught(): the OK of the result screen, and the count of the catch;
 *  - tap_button(): a wide button in the middle of the screen (OK, CLAIM REWARD, 'I am a passenger'), never one that starts a battle or joins a group;
 *  - tray_labels() and pick_berry(): the table of the text reader turned into the labels of the berry tray (with the quirks of Python's
 *    csv.DictReader), and the berry that is used.
 *
 *  Like the rest it knows nothing of the phone: it is given a Host, which adds to that of the map what the catch screen needs (the detector of
 *  buttons, whether the last quick screenshot came from the live video, the throw, the choice of ball and berries, the table of Tesseract,
 *  the step of the brain).  run_catch_checks() holds all of it, in every build, to tests/fixtures/catch_golden.json.qz that
 *  Mobile/tools/make_catch_golden.py made with the Python code: the same pictures and answers in, and the same taps, log lines, sleeps and
 *  saved pictures out, in the same order and at the same moments of a fake clock, with the same things remembered afterwards.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoCatch_H
#define PokemonAutomation_ClaudeGG_PokemonGoCatch_H

#include <optional>
#include <vector>
#include <opencv2/core.hpp>
#include <QString>
#include <QStringList>
#include "ClaudeGG_PokemonGoMap.h"
#include "ClaudeGG_PokemonGoNav.h"
#include "ClaudeGG_PokemonGoThrow.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Catch{

using Loop::Point;
using Models::Detection;
using Map::State;


inline constexpr double TH_CLASS = 0.5;                 //  the least certainty of the screen classifier that is believed
inline constexpr double TH_CLICK = 0.25;                //  the least certainty for a button
inline constexpr double TH_PASSENGER = 0.8;             //  the least certainty for the 'I am a passenger' notice


//  ---- the numbers of the catch screen (canvas of 1768 x 2208)

inline constexpr Point RUN_BTN{159, 248};               //  run away, top left
inline constexpr Point BALL_POS_POKE{325, 1592};        //  the balls of the tray that opens with the ball button
inline constexpr Point BALL_POS_GREAT{877, 1592};
inline constexpr Point BALL_POS_ULTRA{1432, 1592};
inline constexpr int TRAY_FROM = 1380;                  //  the berry tray is read from this row down
inline constexpr int TRAY_COLS[3] = {326, 880, 1432};   //  the middle of the 3 columns of the tray
inline constexpr int TRAY_ICON_Y[2] = {1220, 1740};     //  the height of the berry icons per row
inline constexpr int TRAY_LABEL_Y[2][2] = {{1420, 1540}, {1950, 2140}};     //  the height of the names per row
inline constexpr double TRAY_MIN_CONF = 30.0;           //  a word that tesseract is less sure of is left out
inline constexpr double FINISH_MAX_S = 150.0;           //  s: when the time is up during a catch, this long to finish it


//  ---- the phone, the person and the parts that come later

//  (virtual: the real host of the bot is also a Throw::Host and so on, and all of them are one Map::Host.)
class Host : public virtual Map::Host{
public:
    //  Brain.buttons(): the detector of what can be clicked (label, certainty, middle, size).
    virtual std::vector<Detection> buttons(const cv::Mat& img) = 0;
    //  Was the last quick_screenshot() a picture of the live video?  (Throw::Host has this one too: one function does both.)
    virtual bool quick_live() = 0;
    //  The throw of a ball (Throw::throw_ball): the moment it was let go (the clock of the wall), and whether it came down on the Pokémon
    //  (written to `hit`: gamebot.throw_info['hit']).
    virtual double throw_ball(std::optional<bool>& hit) = 0;
    //  What the person chose: the ball ("poke", "great", "ultra"; BALL) and the berries in the order they are tried (BERRY_ORDER).
    virtual QString ball() = 0;
    virtual QStringList berry_order() = 0;
    //  The berry tray read by the tesseract program (gray picture of the strip from TRAY_FROM down): its table in the TSV form, or nothing
    //  when the program is not there.  Throws std::runtime_error when it does not answer in time.
    virtual std::optional<QString> tray_table(const cv::Mat& gray) = 0;
    //  A step of the bot (step()): the seconds to wait afterwards.  Throws std::runtime_error when the step fails.
    virtual double step() = 0;
};


//  ---- the steps

//  The count of a catch: the first time that a ball was thrown and the Pokémon is gone from the catch screen (gamebot.mark_caught()).
void mark_caught(Host& host, State& state);
//  The OK button of the 'TOTAL XP' screen, only when a ball was thrown and the screen is not clearly still the catch screen.
std::optional<Point> catch_result_button(Host& host, State& state, const cv::Mat& img);
//  Tap that button.
void tap_catch_result(Host& host, State& state, Point btn, const QString& how);
//  Tap a wide button in the middle (OK, CLAIM REWARD, 'I am a passenger'); never small buttons or buttons at the side.  True when something was
//  tapped (or BACK was pressed, for a button that starts a battle or joins a group).
bool tap_button(Host& host, const cv::Mat& img, bool only_passenger = false);
//  After a throw: look until the ball is back (true: ready for the next throw), the result screen has been tapped or another screen is there
//  (false; in that case the screen is kept in state.handoff).
bool wait_for_result(Host& host, State& state, double t_throw);

//  The berry names of the tray, by (row, column) in the order in which they were found: the table of the tesseract program for the picture.
using Cells = std::vector<std::pair<std::pair<int, int>, QString>>;
Cells tray_labels(Host& host, const cv::Mat& img);
//  The first berry of berry_order() that the tray has (never a Silver Pinap or a Golden Razz): its name and the place of its icon.
std::optional<std::pair<QString, Point>> pick_berry(Host& host, const cv::Mat& img);

//  A Pokémon is on the catch screen: choose the ball, feed a berry, throw until it is caught or gone.  Returns the seconds to wait.
double do_encounter(Host& host, State& state, const cv::Mat& img);
//  The last ball came down on the Pokémon: press BACK so that the catch animation is skipped.  Returns the seconds to wait when the game is
//  back on the map (or a question over the map was answered), nothing when the normal way of waiting for the result has to carry on.
std::optional<double> fast_catch_leave(Host& host, State& state, double t_throw);
//  What the screen is when the words are read (gamebot._screen_kind()): "map", "exit" ('Do you want to exit?'), "discard", "bag", "menu" or "other".
QString screen_kind(Host& host, const cv::Mat& img, const Nav::Lines& lines);
//  The time is up: a catch that is going on is finished first (at most FINISH_MAX_S).  `with_beat`: the host is told of every step (host.beat()).
void finish_catch(Host& host, bool with_beat);


//  ---- the check
//
//  Plays the stories of the file of Mobile/tools/make_catch_golden.py (tests/fixtures/catch_golden.json.qz) and says where the port does
//  something else than the Python code did.  Returns how many went another way ("FAILED: ..." lines in `report` say which, the last line
//  says how many were played).
int run_catch_checks(const QString& golden, QStringList& report, bool stop_at_first = false);


}
}
}
}
#endif
