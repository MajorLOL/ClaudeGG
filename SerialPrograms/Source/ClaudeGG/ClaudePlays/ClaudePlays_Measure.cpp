/*  ClaudeGG Claude Plays: measuring the timing on a console of a session
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <chrono>
#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "ClaudePlays_Measure.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace ClaudePlays{


const char* const MEASURE_TIMING_LABEL =
    "<b>Measure the timing first:</b><br>With a menu on the screen that DOWN and UP move in. Before "
    "Claude starts, the program presses DOWN and UP a few times (the cursor ends where it was) and "
    "measures how late the picture shows a press and how short a press can be. That timing is used for "
    "this session and is in the log: put it in the two boxes below to keep it.";
const char* const PRESS_MS_LABEL =
    "<b>Press of a direction (ms):</b><br>How long UP, DOWN, LEFT and RIGHT are held; a button is held 30 "
    "ms longer. 0: the console's own (in the log at the start). Shorter is faster, but a press that is too "
    "short does not arrive.";
const char* const VIDEO_DELAY_MS_LABEL =
    "<b>Extra wait for the picture (ms):</b><br>How much longer the program waits after an action before "
    "it looks whether the picture changed: for a picture that comes late (Remote Play, an HDMI adapter). "
    "0: the console's own.";


ConsoleProbe::ConsoleProbe(PlayConsole& console)
    : m_console(console)
{}
void ConsoleProbe::press(bool down, int ms){
    PadInput input;
    if (m_console.layout().directions_are_stick){
        input.stick_y = down ? -1 : 1;
    }else{
        input.buttons.push_back(down ? "DOWN" : "UP");
    }
    m_console.hold(input, std::chrono::milliseconds(ms));
    //  Until the press is over (a look waits for everything sent).
    m_console.screen([](const ImageViewRGB32&){});
}
void ConsoleProbe::wait(int ms){
    m_console.wait(std::chrono::milliseconds(ms));
    m_console.screen([](const ImageViewRGB32&){});
}
bool ConsoleProbe::mark(){
    m_marked = ScreenThumb();
    m_console.screen([&](const ImageViewRGB32& frame){
        m_marked = screen_thumb(frame);
    });
    return m_marked.valid();
}
double ConsoleProbe::changed(){
    ScreenThumb now;
    m_console.screen([&](const ImageViewRGB32& frame){
        now = screen_thumb(frame);
    });
    if (!now.valid()){
        return -1;
    }
    return thumb_difference(m_marked, now);
}
double ConsoleProbe::now_ms(){
    return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now().time_since_epoch()).count();
}


std::string timing_text(const InputTiming& timing){
    return "presses of " + std::to_string(timing.press_ms) + " ms (directions " +
        std::to_string(timing.direction_ms) + " ms), " + std::to_string(timing.gap_ms) + " ms after each" +
        (timing.video_delay_ms > 0
            ? ", the picture looked at " + std::to_string(timing.video_delay_ms) + " ms later"
            : std::string());
}

InputTiming timing_by_hand(InputTiming timing, uint32_t press_ms, uint32_t video_delay_ms){
    if (press_ms > 0){
        timing.direction_ms = (int)press_ms;
        timing.press_ms = (int)press_ms + 30;
    }
    if (video_delay_ms > 0){
        timing.video_delay_ms = (int)video_delay_ms;
    }
    return timing;
}

InputTiming measured_timing(
    PlayConsole& console, const InputTiming& timing,
    const std::function<void(const std::string& text, bool measured)>& log
){
    ConsoleProbe probe(console);
    const Calibration measured = calibrate(probe);
    log("Timing: " + measured.report, measured.measured);
    if (!measured.measured){
        return timing;
    }
    const InputTiming result = calibrated_timing(timing, measured);
    log(
        "Timing from the measurement: " + timing_text(result) + ". To keep it: press of a direction " +
        std::to_string(result.direction_ms) + " ms, extra wait for the picture " +
        std::to_string(result.video_delay_ms) + " ms.",
        true
    );
    return result;
}


}
}
}
