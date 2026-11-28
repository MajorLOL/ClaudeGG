/*  Claude GG Pokemon GO Layout (is the game drawn the way the bot expects?)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port of what Mobile/spin_stop.py and Mobile/gamebot.py do to find out whether the game is drawn on the screen of the phone the way the canvas
 *  (1768 x 2208, the inner screen of a Galaxy Z Fold3) expects, and to put that right (issue #31):
 *
 *  judge_screen(): is the shape of the screen (width / height) within 10 % of the canvas?  When it is not, the bot does not tap (until the display is
 *  adapted), unless the file ~/gamebot_allow_unsupported exists on the Pi.
 *
 *  find_menu_button(), menu_button_check(): the Poke Ball button at the bottom of the map (a red half on top, a white half below) is looked for and
 *  compared with where it is on the canvas.
 *
 *  display_plan(), adapt_display(), restore_display(): let Android draw the game on a canvas of the right shape (`wm size`: the phone then shows black bars),
 *  after writing down what is changed (the record gamebot_wm_override.json on the Pi), and put that back (`wm size reset`) when the bot stops or when it
 *  did not work out.  Nothing is changed when the file ~/gamebot_no_display_change exists.
 *
 *  layout_verify() and the rest: on the first map pictures of a run the bot looks at the button, tries to adapt the display when it is off, taps the menu
 *  button to see that the menu opens, and undoes everything that does not work.
 *
 *  Like the rest it knows nothing of the phone: it is given a Host (the bag's, with the questions for the display on top of it).  run_layout_checks()
 *  holds all of it, in every build, to tests/fixtures/layout_golden.json.qz that Mobile/tools/make_layout_golden.py made with the Python code: the same
 *  answers in, and the same taps, sleeps, log lines and calls for the display, in the same order and at the same moments of a fake clock.
 *
 *  Where it differs from the Python code: the screen is looked at through the agent (`GET /v1/info` and `GET /v1/display`, agent 0.2.6) and not with
 *  `screencap` of every display of the phone, so a foldable that has two displays is told apart by the agent's own choice of display (its option --display)
 *  and not by which one is lit; the files of the Pi (the record, the two switches) are kept by the agent.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoLayout_H
#define PokemonAutomation_ClaudeGG_PokemonGoLayout_H

#include <optional>
#include <opencv2/core.hpp>
#include <QJsonObject>
#include <QString>
#include <QStringList>
#include "ClaudeGG_PokemonGoBag.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Layout{


inline constexpr int REF_W = 1768;                      //  the canvas (S.EXPECTED_SIZE)
inline constexpr int REF_H = 2208;
inline constexpr double ASPECT_TOLERANCE = 0.10;        //  the shape of the screen may differ this much (relative) from the canvas
inline constexpr int MENU_REF_X = 884;                  //  the menu button on the canvas: x of its middle,
inline constexpr int MENU_REF_Y = 1991;                 //  y of the line between its red and white half,
inline constexpr int MENU_REF_W = 170;                  //  width of the red half
inline constexpr int MENU_TOL_X = 45;                   //  how far off that may be (px on the canvas)
inline constexpr int MENU_TOL_Y = 60;
inline constexpr int MENU_TOL_W = 28;
inline constexpr int MIN_CANVAS_W = 600;                //  never make the game smaller than this
inline constexpr int MIN_CANVAS_H = 750;
inline constexpr int LAYOUT_LOOKS = 4;                  //  map pictures without the button before the bot gives up looking for it
inline constexpr double LAYOUT_MAP_WAIT = 300;          //  s after a display change in which the map has to be seen again
inline constexpr double LAYOUT_RETRY = 1800;            //  s between two attempts to adapt the display
inline constexpr double UNSUPPORTED_LOG_EVERY = 600;    //  s between two lines that say why the bot does not play
inline constexpr double UNSUPPORTED_WAIT = 30;          //  s that it waits before it looks at the screen again


//  What the bot knows of the screen (spin_stop.screen) and of the layout check (gamebot.layout).
struct Screen{
    int w = REF_W;
    int h = REF_H;
    QString model;
    bool ok = true;                     //  is the shape supported?
    QString note;                       //  why not
};
struct State{
    Screen screen;
    QString state = "new";              //  new | confirmed | unverified | adapting | adapted
    int looks = 0;                      //  map pictures without the button
    double since = 0.0;                 //  when the display was changed
    double next_try = 0.0;              //  the first moment at which the display may be adapted again
    double wait_log = 0.0;              //  when the bot last said why it does not play
};

struct MenuButton{
    double x = 0;                       //  of its middle
    double y = 0;                       //  of the line between the halves
    double w = 0;                       //  of the red half
};
struct ScreenRead{
    int w = 0;
    int h = 0;
    QString model;
};

class Host : public virtual Bag::Host{
public:
    //  `adb shell wm size` (S.adb): what it says.  Throws std::runtime_error when the phone does not answer.
    virtual QString wm_size_text() = 0;
    //  `wm size WxH` and `wm size reset`.  Throw std::runtime_error with the text of the error when the phone refuses.
    virtual void wm_size_set(const QString& size) = 0;
    virtual void wm_size_reset() = 0;
    //  The record of what the bot changed (WM_FILE on the Pi): its text, nothing when there is none.  Written, with the text of the error when it cannot
    //  be (empty: it was), and forgotten.
    virtual std::optional<QString> record_text() = 0;
    virtual QString record_write(const QJsonObject& record) = 0;
    virtual void record_forget() = 0;
    //  Does the file exist on the Pi: "allow" (~/gamebot_allow_unsupported) or "no_adapt" (~/gamebot_no_display_change); and where are the files:
    //  "allow", "no_adapt" and "record".
    virtual bool file_exists(const QString& which) = 0;
    virtual QString file_path(const QString& which) = 0;
    //  Look at the screen of the phone (detect_screen()): its size and model, nothing when it cannot be seen.  Throws std::runtime_error when it
    //  cannot be asked.
    virtual std::optional<ScreenRead> read_screen(bool wake) = 0;
    //  The step has to look at the screen again (same_screen.update(name=None, count=0)).
    virtual void reset_same_screen() = 0;
};


//  ---- what the screen is

//  _judge_screen(): is the shape of the screen close enough to the canvas?  Sets screen.ok and screen.note.
void judge_screen(State& state, Host& host);
//  The part of _normalize() that notices the size of a screenshot: another size is said in the log and judged.
void screen_seen(State& state, Host& host, int w, int h);
//  detect_screen(): look at the screen (what the agent says), take its size and judge it.  False: it cannot be seen.
bool detect_screen(State& state, Host& host, bool wake);
//  The screen has a shape that cannot be played on: do nothing, but keep looking (a foldable may be unfolded).
void wait_unsupported(State& state, Host& host);


//  ---- the menu button

//  The Poke Ball menu button (red top half, white bottom half) at the bottom of the map, on a picture of any size; nothing when it is not there.
std::optional<MenuButton> find_menu_button(const cv::Mat& img);
struct Check{
    std::optional<bool> ok;             //  nothing: the button was not found
    QString text;
};
Check menu_button_check(const std::optional<MenuButton>& found);


//  ---- the display

struct Plan{
    QString cmd;                        //  the argument for `wm size`, empty when there is no plan
    int w = 0;                          //  the size of the screenshots then
    int h = 0;
    QString why;                        //  why there is no plan
};
//  What does the display have to be for the game to be drawn like the canvas?
Plan display_plan(State& state, Host& host);
struct Adapted{
    bool changed = false;
    QString text;
};
//  Let Android draw the game on a canvas of the right shape.
Adapted adapt_display(State& state, Host& host);
//  Put the display size back when this bot changed it.  True when something was put back.
bool restore_display(State& state, Host& host);


//  ---- the check of the layout

//  Called once at the start: take over a display change that an earlier run did not get to put back.
void layout_init(State& state, Host& host);
//  Try to get the game drawn in the right shape (once in half an hour): true when the display was changed.
bool layout_adapt(State& state, Host& host, const QString& why);
//  The display change did not work out: put everything back.
void layout_undo(State& state, Host& host, const QString& why);
//  Tap the menu button and see whether the main menu opens, then back to the map.
bool layout_tap_test(State& state, Host& host, const cv::Mat& before);
//  Called with a picture of the map (on the canvas) until the layout is settled for this run.
void layout_verify(State& state, Host& host, const cv::Mat& img);
//  After a display change the map has to come back within a few minutes.
void layout_watch(State& state, Host& host);


//  ---- the check

//  Plays the stories of the file of Mobile/tools/make_layout_golden.py (tests/fixtures/layout_golden.json.qz) and says where the port does something else
//  than the Python code did.  Returns how many went another way ("FAILED: ..." lines in `report` say which, the last line says how many were played).
int run_layout_checks(const QString& golden, QStringList& report, bool stop_at_first = false);


}
}
}
}

#endif
