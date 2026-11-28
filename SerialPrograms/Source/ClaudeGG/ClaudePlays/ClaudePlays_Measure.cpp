/*  ClaudeGG Claude Plays: measuring the timing on a console of a session
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <chrono>
#include <ctime>
#include "Common/Cpp/Json/JsonObject.h"
#include "Common/Cpp/Json/JsonValue.h"
#include "CommonFramework/GlobalAutoPaths.h"
#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "ClaudePlays_Measure.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace ClaudePlays{


const char* const MEASURE_TIMING_LABEL =
    "<b>Measure the timing first:</b><br>With a menu on the screen that DOWN and UP move in. Before "
    "Claude starts, the program presses DOWN and UP a few times (the cursor ends where it was) and "
    "measures how late the picture shows a press and how short a press can be. That timing is used for "
    "this session and kept for this console: the next sessions use it without measuring, until you "
    "measure again. The two boxes below go before it.";
const char* const PRESS_MS_LABEL =
    "<b>Press of a direction (ms):</b><br>How long UP, DOWN, LEFT and RIGHT are held; a button is held 30 "
    "ms longer. 0: the console's own (in the log at the start). Shorter is faster, but a press that is too "
    "short does not arrive.";
const char* const VIDEO_DELAY_MS_LABEL =
    "<b>Extra wait for the picture (ms):</b><br>How much longer the program waits after an action before "
    "it looks whether the picture changed: for a picture that comes late (Remote Play, an HDMI adapter). "
    "0: the console's own.";
const char* const KNOWN_GAME_LABEL =
    "<b>Which game:</b><br>For a well-known game the program tells Claude its controls by default, and "
    "makes the presses long enough for a game that runs at few frames a second. Another game: say "
    "which under \"About the game\", or Claude finds out from the screen.";


IntegerEnumDropdownDatabase known_games_database(const std::vector<const KnownGame*>& games){
    IntegerEnumDropdownDatabase database;
    database.add(0, "none", "Another one (say which under \"About the game\")", true);
    size_t index = 1;
    for (const KnownGame* known : games){
        database.add(index++, known->slug, known->name, true);
    }
    return database;
}
const KnownGame* chosen_known_game(const std::vector<const KnownGame*>& games, size_t index){
    return index > 0 && index <= games.size() ? games[index - 1] : nullptr;
}


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

namespace{

std::string saved_timing_path(){
    return SETTINGS_PATH() + "ClaudePlays-Timing.json";
}

//  The measurements kept, one for each console code. Empty when there is
//  no file, or it cannot be read (a new measurement then starts it over).
JsonObject read_saved(){
    try{
        JsonValue json = load_json_file(saved_timing_path());
        JsonObject* object = json.to_object();
        if (object != nullptr){
            return std::move(*object);
        }
    }catch (...){}
    return JsonObject();
}

std::string today(){
    const std::time_t now = std::time(nullptr);
    std::tm local{};
#ifdef _WIN32
    localtime_s(&local, &now);
#else
    localtime_r(&now, &local);
#endif
    char text[16] = {};
    std::strftime(text, sizeof(text), "%Y-%m-%d", &local);
    return text;
}

}   //  namespace


JsonObject saved_measurement_json(const Calibration& measured, const std::string& date){
    JsonObject entry;
    entry["delay_ms"] = (int64_t)measured.delay_ms;
    entry["shortest_press_ms"] = (int64_t)measured.shortest_press_ms;
    entry["date"] = date;
    return entry;
}
bool saved_measurement_from_json(const JsonObject& entry, Calibration& measured, std::string& date){
    const int64_t delay = entry.get_integer_default("delay_ms", -1);
    const int64_t shortest = entry.get_integer_default("shortest_press_ms", -1);
    if (delay < 0 || delay > 5000 || shortest < 0 || shortest > 1000){
        return false;
    }
    measured = Calibration();
    measured.measured = true;
    measured.delay_ms = (int)delay;
    measured.shortest_press_ms = (int)shortest;
    date = entry.get_string_default("date", "");
    return true;
}


InputTiming measured_timing(
    PlayConsole& console, const std::string& console_code, const InputTiming& timing,
    const std::function<void(const std::string& text, bool measured)>& log
){
    ConsoleProbe probe(console);
    const Calibration measured = calibrate(probe);
    log("Timing: " + measured.report, measured.measured);
    if (!measured.measured){
        return timing;
    }
    const InputTiming result = calibrated_timing(timing, measured);
    //  Kept for the next sessions on this console.
    bool kept = false;
    if (!console_code.empty()){
        try{
            JsonObject saved = read_saved();
            saved[console_code] = saved_measurement_json(measured, today());
            JsonValue(std::move(saved)).dump(saved_timing_path());
            kept = true;
        }catch (...){}
    }
    log(
        "Timing from the measurement: " + timing_text(result) + (kept
            ? ". Kept for this console: the next sessions use it without measuring."
            : ". It could not be kept (the settings folder cannot be written)."),
        true
    );
    return result;
}

InputTiming saved_timing(
    const std::string& console_code, const InputTiming& timing,
    const std::function<void(const std::string& text)>& log
){
    const JsonObject saved = read_saved();
    const JsonObject* entry = saved.get_object(console_code);
    Calibration measured;
    std::string date;
    if (entry == nullptr || !saved_measurement_from_json(*entry, measured, date)){
        return timing;
    }
    const InputTiming result = calibrated_timing(timing, measured);
    log(
        "Timing measured on this console" + (date.empty() ? std::string() : " on " + date) + ": " +
        timing_text(result) + ". Measure the timing first to measure it again."
    );
    return result;
}


}
}
}
