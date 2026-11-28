/*  ClaudeGG Claude Plays: measuring the timing of a console
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <algorithm>
#include <cmath>
#include "ClaudePlays_Calibrate.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace ClaudePlays{


namespace{

//  A press that surely arrives on every console (the longest press of a
//  direction in the table is shorter).
const int SURE_PRESS_MS = 150;
//  How long the picture may take to show a press before it is taken for
//  missed.
const double LONGEST_DELAY_MS = 1500;
//  The tries for the delay, and for each short press.
const int DELAY_TRIES = 5;
const int PRESS_TRIES = 3;
//  The short presses tried, shortest first: 2 to 6 frames at 60 a second.
const int SHORT_PRESSES_MS[] = {34, 50, 67, 84, 100};
//  How often the picture is looked at while waiting for it to change.
const int POLL_MS = 10;
//  The part of the picture that has to change for a press to count, at
//  least, and at least three times what changes by itself.
const double LEAST_CHANGE = 0.006;
const double STILL = 0.005;

//  Waits until the picture is still, and marks it. The noise of the still
//  picture in "noise". False: it does not get still, or no video.
bool mark_still(CalibrationProbe& probe, double& noise){
    for (int attempt = 0; attempt < 10; attempt++){
        if (!probe.mark()){
            return false;
        }
        probe.wait(200);
        const double moved = probe.changed();
        if (moved < 0){
            return false;
        }
        if (moved < STILL){
            noise = moved;
            return probe.mark();
        }
    }
    return false;
}

//  After a press: the time until the picture changed, -1 if it did not
//  within "limit_ms", -2 if the video stopped.
double time_to_change(CalibrationProbe& probe, double noise, double limit_ms){
    const double threshold = std::max(LEAST_CHANGE, noise * 3);
    const double start = probe.now_ms();
    while (probe.now_ms() - start <= limit_ms){
        const double moved = probe.changed();
        if (moved < 0){
            return -2;
        }
        if (moved >= threshold){
            return probe.now_ms() - start;
        }
        probe.wait(POLL_MS);
    }
    return -1;
}

}   //  namespace


Calibration calibrate(CalibrationProbe& probe){
    Calibration result;
    //  How late the picture comes.
    for (int attempt = 0; attempt < DELAY_TRIES; attempt++){
        double noise = 0;
        if (!mark_still(probe, noise)){
            result.report = "The picture does not get still (or no video comes in): nothing was measured.";
            return result;
        }
        probe.press(true, SURE_PRESS_MS);
        const double took = time_to_change(probe, noise, LONGEST_DELAY_MS);
        if (took == -2){
            result.report = "The video stopped while measuring.";
            return result;
        }
        if (took < 0){
            //  DOWN did nothing: no menu, or the end of one.
            result.report = result.delays_ms.empty()
                ? "DOWN did not change the picture: open a menu with a few entries and start again."
                : "DOWN stopped changing the picture (the end of the menu?): measured " +
                  std::to_string(result.delays_ms.size()) + " times.";
            break;
        }
        result.delays_ms.push_back((int)(took + 0.5));
        //  Back where it was.
        probe.press(false, SURE_PRESS_MS);
        probe.wait(300);
    }
    if (result.delays_ms.size() < 3){
        if (result.report.empty()){
            result.report = "Too few measurements.";
        }
        return result;
    }
    std::vector<int> sorted = result.delays_ms;
    std::sort(sorted.begin(), sorted.end());
    result.delay_ms = sorted[sorted.size() / 2];
    result.measured = true;

    //  The shortest press that arrives every time.
    const double limit = std::min(LONGEST_DELAY_MS, (double)result.delay_ms * 2 + 300);
    for (int press : SHORT_PRESSES_MS){
        int arrived = 0;
        for (int attempt = 0; attempt < PRESS_TRIES; attempt++){
            double noise = 0;
            if (!mark_still(probe, noise)){
                break;
            }
            probe.press(true, press);
            if (time_to_change(probe, noise, limit) < 0){
                continue;
            }
            arrived++;
            probe.press(false, SURE_PRESS_MS);
            probe.wait(300);
        }
        if (arrived == PRESS_TRIES){
            result.shortest_press_ms = press;
            break;
        }
    }

    std::string each;
    for (int delay : result.delays_ms){
        each += (each.empty() ? "" : ", ") + std::to_string(delay);
    }
    result.report =
        "The picture showed a press " + std::to_string(result.delay_ms) + " ms after it (each time: " + each +
        " ms). " + (result.shortest_press_ms > 0
            ? "The shortest press that arrived every time: " + std::to_string(result.shortest_press_ms) + " ms."
            : std::string("None of the short presses arrived every time: the console's own presses stay."));
    return result;
}

InputTiming calibrated_timing(const InputTiming& base, const Calibration& measured){
    InputTiming timing = base;
    if (!measured.measured){
        return timing;
    }
    if (measured.shortest_press_ms > 0){
        //  Two frames more than the shortest that arrived.
        timing.direction_ms = std::clamp(measured.shortest_press_ms + 33, 50, 300);
        timing.press_ms = std::clamp(timing.direction_ms + 30, 80, 400);
    }
    //  The program looks whether an action changed the picture after the
    //  wait that follows it (the gap of "press", the settle of "hold"), and
    //  after the delay: together they have to be longer than the picture
    //  takes, by a margin.
    const int already = std::min(timing.gap_ms, timing.settle_ms);
    timing.video_delay_ms = std::clamp(measured.delay_ms + 50 - already, 0, 1000);
    return timing;
}


int calibration_tests(std::string& report){
    int wrong = 0;
    auto fail = [&](const std::string& what){
        wrong++;
        report += (report.empty() ? "" : "\n") + what;
    };

    //  A made-up console with a menu: a press of DOWN of at least
    //  "min_press" moves the cursor, and the picture shows it "delay" later.
    class MadeUp : public CalibrationProbe{
    public:
        double delay = 120;
        int min_press = 50;
        //  The cursor does not move: no menu.
        bool menu = true;
        //  The picture changes by itself all the time.
        bool restless = false;

        virtual void press(bool down, int ms) override{
            clock += ms;
            if (menu && ms >= min_press){
                cursor += down ? 1 : -1;
                changes.push_back({clock + delay, cursor});
            }
        }
        virtual void wait(int ms) override{
            clock += ms;
        }
        virtual bool mark() override{
            marked = shown();
            return true;
        }
        virtual double changed() override{
            clock += 1;
            if (restless){
                return 0.02;
            }
            return shown() != marked ? 0.03 : 0.001;
        }
        virtual double now_ms() override{
            return clock;
        }

    private:
        struct Change{
            double at;
            int cursor;
        };
        double clock = 0;
        int cursor = 0;
        int marked = 0;
        std::vector<Change> changes;

        int shown() const{
            int value = 0;
            for (const Change& change : changes){
                if (change.at <= clock){
                    value = change.cursor;
                }
            }
            return value;
        }
    };

    for (double delay : {40.0, 120.0, 300.0}){
        for (int min_press : {30, 60, 90}){
            MadeUp console;
            console.delay = delay;
            console.min_press = min_press;
            const Calibration measured = calibrate(console);
            const int expected_press = min_press <= 34 ? 34 : min_press <= 50 ? 50 : min_press <= 67 ? 67 : min_press <= 84 ? 84 : 100;
            if (!measured.measured || std::abs(measured.delay_ms - (int)delay) > 2 * POLL_MS ||
                measured.shortest_press_ms != expected_press || measured.report.empty()
            ){
                fail(
                    "measured " + std::to_string(measured.delay_ms) + " ms and " +
                    std::to_string(measured.shortest_press_ms) + " ms for a delay of " +
                    std::to_string((int)delay) + " ms and presses of " + std::to_string(min_press) + " ms"
                );
            }
            const InputTiming base = console_traits("switch").timing;
            const InputTiming timing = calibrated_timing(base, measured);
            const int looked = std::min(timing.gap_ms, timing.settle_ms) + timing.video_delay_ms;
            if (looked < (int)delay || timing.direction_ms < min_press || timing.press_ms < timing.direction_ms){
                fail("the timing from a measurement of " + std::to_string((int)delay) + " ms is too short");
            }
        }
    }
    //  No menu: nothing is measured, and the timing stays.
    {
        MadeUp console;
        console.menu = false;
        const Calibration measured = calibrate(console);
        const InputTiming base = console_traits("retro").timing;
        const InputTiming timing = calibrated_timing(base, measured);
        if (measured.measured || measured.report.find("open a menu") == std::string::npos ||
            timing.press_ms != base.press_ms || timing.video_delay_ms != base.video_delay_ms
        ){
            fail("a screen without a menu is measured");
        }
    }
    //  A picture that never gets still: nothing is measured.
    {
        MadeUp console;
        console.restless = true;
        const Calibration measured = calibrate(console);
        if (measured.measured || measured.report.find("does not get still") == std::string::npos){
            fail("a restless picture is measured");
        }
    }
    //  Presses that never arrive short: the console's own stay, the delay
    //  is still used.
    {
        MadeUp console;
        console.min_press = 120;
        const Calibration measured = calibrate(console);
        const InputTiming base = console_traits("psremote").timing;
        const InputTiming timing = calibrated_timing(base, measured);
        if (!measured.measured || measured.shortest_press_ms != 0 ||
            timing.press_ms != base.press_ms || timing.direction_ms != base.direction_ms
        ){
            fail("presses that arrive only long are shortened");
        }
    }
    return wrong;
}



}
}
}
