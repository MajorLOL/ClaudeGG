/*  Claude GG Pokemon GO Vision (the screen of a GO Battle League fight, read from the picture)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port to C++ of Mobile/battle_vision.py (issue #30): a picture in, facts out.
 *  The HUD (name boxes, Poké Balls, shields), the HP bars, the charged attack
 *  buttons that are ready, the banner "Get Ready!", the countdown of a question,
 *  the buttons of the screens around a fight (NEXT BATTLE, BATTLE, the round
 *  check mark, the gold reward tiles, the pop-up with the Pokémon to switch to).
 *  Pure picture tests, no OCR and no phone; every position is a fraction of
 *  the picture, so it reads the 1768 x 2208 canvas of the Galaxy Z Fold3 and a
 *  smaller copy of it alike.  The pictures are cv::Mat (8 bit, BGR), and every
 *  step is the one that the Python code takes with cv2 (the same OpenCV calls,
 *  the same order, the same rounding), so the answers are the same.
 *
 *  Mobile/tools/make_vision_golden.py makes a file with what battle_vision.py
 *  reads from 696 pictures (frames of real fights, parts of them pasted on each
 *  other, darker and brighter, with made-up buttons, tiles and discs drawn on
 *  them) and run_vision_checks() holds this port to it in every build
 *  (--mobile-test).
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoVision_H
#define PokemonAutomation_ClaudeGG_PokemonGoVision_H

#include <optional>
#include <utility>
#include <vector>
#include <opencv2/core.hpp>
#include <QString>
#include <QStringList>

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Vision{


//  ---- where things are (fractions of the picture width / height) -------------------------------------------

extern const double BTN_Y;                  //  the centre of the two charged attack buttons
extern const double BTN_X[2];               //  ... left and right
extern const double TAP_FAST[2];            //  a tap here is a fast attack (nothing is under it)
extern const double TAP_SHIELD[2];          //  the shield on "Attack incoming! Use a Protect Shield?"
extern const double TAP_NOT_NOW[2];         //  NOT NOW on the same question
extern const double TAP_NEXT[2];            //  the green NEXT BATTLE button
extern const double TAP_DONE[2];            //  the round button with the check mark under it
extern const double DONE_R;                 //  ... its radius (in picture widths)
extern const double POPUP_TILES[2];         //  "Switch in a new Pokémon?": the two choices (x) ...
extern const double POPUP_TILE_Y;           //  ... and y
extern const double BAR_FULL;               //  the inside of a full HP bar (in picture widths)
extern const double RUN_BUTTON[2];          //  the round button with the running trainer, top left
extern const double EXIT_YES_Y[2];          //  'Exit the Trainer Battle?': the green YES button lies in this part


//  ---- the readers -------------------------------------------------------------------------------------------

bool is_white_screen(const cv::Mat& img);

//  The VS screen: a white line over the whole width in the middle of the screen.
bool is_versus(const cv::Mat& img);

//  The Poké Balls in a name box: red for a Pokémon that can still fight, grey for one that fainted.
struct Balls{
    int red = 0;
    int grey = 0;
};
struct BallSlots{
    Balls me;
    Balls foe;
};
BallSlots ball_slots(const cv::Mat& img);

//  The two name boxes at the top of a fight are on the screen (each with its Poké Balls).
bool hud_visible(const cv::Mat& img);

//  (left, right): can the charged attack of a button be thrown (the name under it is bright white text)?
std::pair<bool, bool> charge_ready(const cv::Mat& img);

//  The banner "Get Ready!" between the name boxes: an attack of ours was thrown.
bool get_ready(const cv::Mat& img);

//  The countdown that comes with a question: "attack" (the shield question), "switch" or "" (none).
QString countdown_kind(const cv::Mat& img);
bool countdown_ring(const cv::Mat& img);

//  A small fingerprint (4 x 40, 8 bit) of the text line of a name box; "me" is the left one.
//  An empty cv::Mat is "no fingerprint".
cv::Mat name_key(const cv::Mat& img, bool me);
//  Do two fingerprints show another text?  (An empty one always does.)
bool key_differs(const cv::Mat& a, const cv::Mat& b);

//  The big lilac shield of "Attack incoming! Use a Protect Shield?".
bool shield_question(const cv::Mat& img);

//  The shields each side still has, nothing for a side whose icons are not clearly seen.
struct ShieldSlots{
    std::optional<int> me;
    std::optional<int> foe;
};
ShieldSlots shield_icon_slots(const cv::Mat& img);

//  The HP bars above the two Pokémon, from left to right.
struct HpBar{
    int x0 = 0;
    double frac = 0;                //  0..1
    QString color;                  //  "green", "yellow" or "red"
    int y = 0;
};
std::vector<HpBar> hp_bars(const cv::Mat& img);

//  (my HP fraction, the foe's) - nothing for a bar that is not clearly seen.
struct Hp{
    std::optional<double> me;
    std::optional<double> foe;
};
Hp hp_of_sides(const cv::Mat& img);

//  The green pill button (NEXT BATTLE) at the bottom of a result screen.
bool result_button(const cv::Mat& img);

//  The round button with the check mark at the bottom of the screen.
bool done_button(const cv::Mat& img);

//  A wide green or orange button of the screens around a fight, in fractions of the picture.
struct Button{
    QString color;                  //  "green" or "orange"
    double x0 = 0;
    double x1 = 0;
    double y0 = 0;
    double y1 = 0;
};
//  The wide buttons in the lower part of a screen (from `top` down), lowest first.
std::vector<Button> wide_buttons(const cv::Mat& img, double top = 0.45);

struct Spot{
    double x = 0;
    double y = 0;
};
//  Where to tap a button of wide_buttons(); side: how far from its left end (0.5 = the middle).
Spot button_spot(const Button& button, double side = 0.5);

//  The big button of the Battle screen (orange: claim first; green: BATTLE), nothing when none is in view.
std::optional<Button> home_button(const cv::Mat& img);
//  ... from the list of wide_buttons(img, 0.45) when it is at hand already.
std::optional<Button> home_button(const std::vector<Button>& found);
//  The BATTLE button at the bottom of the Battle screen is grey (nothing left to play today).
bool home_button_off(const cv::Mat& img);

//  The middles of the gold reward tiles of the Battle screen, left to right.
std::vector<Spot> gold_tiles(const cv::Mat& img);

//  How many tiles the question 'Switch in a new Pokémon?' shows: 2 or 1.
int popup_tiles_shown(const cv::Mat& img);

//  Where to tap YES on 'Exit the Trainer Battle?', nothing when there is no such button.
std::optional<Spot> exit_yes(const cv::Mat& img);


//  Everything above in one go (for the log and the tests).
struct Seen{
    bool white = false;
    bool versus = false;
    bool hud = false;
    std::pair<bool, bool> ready{false, false};
    bool ring = false;
    QString count;
    ShieldSlots shields;
    Hp hp;
    bool result = false;
    bool hex = false;
    bool done = false;
    bool get_ready = false;
    std::optional<BallSlots> balls;     //  (only with the name boxes on the picture)
};
Seen features(const cv::Mat& img);


//  Holds this port to the file that make_vision_golden.py made (see above).  `golden` is that file
//  (tests/fixtures/vision_golden.json.qz), `fixtures` the folder with the frames of the fights
//  (tests/fixtures/fight).  Returns how many pictures were read differently; "FAILED: ..." lines say which.
int run_vision_checks(const QString& golden, const QString& fixtures, QStringList& report);


}
}
}
}
#endif
