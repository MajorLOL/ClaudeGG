/*  ClaudeGG Claude Plays: measuring the timing of a console
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The timing of each console (ClaudePlays_Consoles.h) is a guess until it
 *  is measured on the user's own setup: the capture card, the adapter, the
 *  network of Remote Play, the game. Before Claude starts, the program can
 *  measure two things with a menu on the screen:
 *
 *  -   How late the picture comes: DOWN is pressed, and the time from the
 *      end of the press until the picture changes is taken, a few times.
 *      The median is the delay.
 *
 *  -   The shortest press that arrives: DOWN is pressed shorter and shorter
 *      (and each time it arrived, UP puts the cursor back, so nothing
 *      moves in the end). The shortest one that arrived every time, with a
 *      margin, is the press of a direction from then on.
 *
 *  The measuring is behind an interface (Probe) so that it runs in a test
 *  with a made-up console and a made-up clock.
 *
 *  No Qt in this header.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_ClaudePlays_Calibrate_H
#define PokemonAutomation_ClaudeGG_ClaudePlays_Calibrate_H

#include <string>
#include <vector>
#include "ClaudePlays_Consoles.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace ClaudePlays{


//  What the measuring does on the console.
class CalibrationProbe{
public:
    virtual ~CalibrationProbe() = default;
    //  Presses DOWN ("down") or UP for "ms", and returns once the press is
    //  over.
    virtual void press(bool down, int ms) = 0;
    //  Nothing pressed for "ms".
    virtual void wait(int ms) = 0;
    //  Takes the picture that the next calls of changed() compare with.
    //  False: no video.
    virtual bool mark() = 0;
    //  How much of the picture differs from the marked one now, 0 to 1.
    //  Negative: no video.
    virtual double changed() = 0;
    //  A clock, in milliseconds.
    virtual double now_ms() = 0;
};

struct Calibration{
    //  It could be measured: a menu was on the screen and DOWN moved in it.
    bool measured = false;
    //  From the end of a press until the picture changed (the median).
    int delay_ms = 0;
    //  Each try's.
    std::vector<int> delays_ms;
    //  The shortest press of DOWN that arrived every time. 0: none of the
    //  short ones did (the console's own press stays).
    int shortest_press_ms = 0;
    //  For the log.
    std::string report;
};

//  Measures, with a menu on the screen that DOWN and UP move in.
Calibration calibrate(CalibrationProbe& probe);

//  The console's timing with what was measured: the picture is looked at
//  once it can show the press ("gap" and the delay after it, with a margin),
//  and a direction is pressed as short as arrives, with a margin. Without a
//  measurement: "base".
InputTiming calibrated_timing(const InputTiming& base, const Calibration& measured);


//  The checks of this file, with a made-up console: the number that failed,
//  and what failed in "report".
int calibration_tests(std::string& report);



}
}
}
#endif
