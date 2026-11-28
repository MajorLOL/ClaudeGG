/*  ClaudeGG Claude Plays: measuring the timing on a console of a session
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The measuring itself (ClaudePlays_Calibrate.h) on a PlayConsole, and the
 *  three options of the timing ("Measure the timing first", "Press of a
 *  direction", "Extra wait for the picture"), for Claude Plays and for the
 *  consoles over Wi-Fi (Wii U, PlayStation Vita, Nintendo 3DS), which have
 *  their own programs.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_ClaudePlays_Measure_H
#define PokemonAutomation_ClaudeGG_ClaudePlays_Measure_H

#include <stdint.h>
#include <functional>
#include <string>
#include "ClaudePlays_AnyGame.h"
#include "ClaudePlays_Calibrate.h"
#include "ClaudePlays_Consoles.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace ClaudePlays{


//  The labels of the three options.
extern const char* const MEASURE_TIMING_LABEL;
extern const char* const PRESS_MS_LABEL;
extern const char* const VIDEO_DELAY_MS_LABEL;


//  The measuring on a console of a session: DOWN and UP (or the stick, on a
//  pad whose directions are a stick), and the picture of its screen().
class ConsoleProbe : public CalibrationProbe{
public:
    explicit ConsoleProbe(PlayConsole& console);
    virtual void press(bool down, int ms) override;
    virtual void wait(int ms) override;
    virtual bool mark() override;
    virtual double changed() override;
    virtual double now_ms() override;

private:
    PlayConsole& m_console;
    ScreenThumb m_marked;
};


//  For the log: "presses of 150 ms (directions 110 ms), 300 ms after each".
std::string timing_text(const InputTiming& timing);

//  The timing with what was set by hand. 0: the timing's own.
InputTiming timing_by_hand(InputTiming timing, uint32_t press_ms, uint32_t video_delay_ms);

//  Measures on the console (a menu that DOWN and UP move in must be on the
//  screen) and returns the timing to use: the measured one, or "timing" if
//  it could not be measured. "log" gets what happened (true: measured).
InputTiming measured_timing(
    PlayConsole& console, const InputTiming& timing,
    const std::function<void(const std::string& text, bool measured)>& log
);


}
}
}
#endif
