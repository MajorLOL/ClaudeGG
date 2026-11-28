/*  Claude GG Pokemon GO Bot (Claude GG itself plays Pokémon GO on the phone of the Pi: the steps of the bot over the agent)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  See ClaudeGG_PokemonGoBot.h.
 *
 */

#include <stdexcept>
#include "ClaudeGG_PokemonGoBot.h"
#include "ClaudeGG_PokemonGoCatch.h"
#include "ClaudeGG_PokemonGoFlow.h"
#include "ClaudeGG_PokemonGoMap.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Bot{

namespace{
const double BAG_FULL_WAIT = 30 * 60;               //  s: no spinning after the message that the bag is full (spin_stop.BAG_FULL_WAIT)
const double STEP_ERROR_WAIT = 10;                  //  s after a step that failed (the loop of gamebot.py)
}


std::vector<Detection> PhoneDetector::map(const cv::Mat& img, const cv::Rect& box, double threshold, int top){
    const cv::Rect inside = box & cv::Rect(0, 0, img.cols, img.rows);
    if (inside.width <= 0 || inside.height <= 0){
        return {};
    }
    return m_phone.map_objects(img(inside), threshold, top);
}


Switches playable(const Switches& asked){
    Switches out = asked;
    //  Not ported yet: off, so that the steps leave them alone.
    for (const char* key : {"catch", "gifts_open", "gifts_send", "daily_cycle", "rocket_fight", "quests", "bag_clean", "battle", "teams_weekly",
                            "spin_only_when_full", "fast_catch", "curveball"}){
        out[QString::fromLatin1(key)] = false;
    }
    //  The pause for the heat needs temperatures that the agent cannot give yet.
    out["heat_pause"] = false;
    return out;
}


PhoneBot::PhoneBot(Phone::AgentHost& phone, const Switches& switches)
    : m_phone(phone)
    , m_switches(playable(switches))
    , m_detector(phone)
    , m_eyes(m_detector)
    , m_random(std::random_device{}())
{
    m_map.catching = false;
    m_map.spin = m_switches["spin"];
}

void PhoneBot::timers(){
    if (m_spin_at.has_value() && wall() >= *m_spin_at){
        m_spin_at.reset();
        m_map.spin = m_switches["spin"];
        m_map.bag_is_full = false;
        log("spinning PokéStops again (the pause for the full bag is over)");
    }
    if (m_catch_at.has_value() && wall() >= *m_catch_at){
        m_catch_at.reset();
        Step::resume_catching(*this, m_map);
    }
}

QString PhoneBot::counts() const{
    return QString("(this run: %1 stops, %2 caught, %3 fled)").arg(m_stops).arg(m_caught).arg(m_fled);
}

double PhoneBot::uniform(double lo, double hi){
    return std::uniform_real_distribution<double>(lo, hi)(m_random);
}
double PhoneBot::unit(){
    return std::uniform_real_distribution<double>(0.0, 1.0)(m_random);
}

bool PhoneBot::setting(const QString& key, bool fallback){
    const auto it = m_switches.find(key);
    return it == m_switches.end() ? fallback : it->second;
}
bool PhoneBot::wanted(const QString& key){
    //  (gamebot.wanted(): on when the web interface does not say; the two of the daily run and the full storage are off then.)
    const auto it = m_switches.find(key);
    if (it == m_switches.end()){
        return key != "spin_only_when_full" && key != "daily_cycle";
    }
    return it->second;
}

QString PhoneBot::count(const QString& key){
    if (key == "stops"){
        m_stops++;
    }else if (key == "caught"){
        m_caught++;
    }else if (key == "fled"){
        m_fled++;
    }
    return counts();
}

int PhoneBot::clean_bag(){
    throw std::runtime_error("cleaning the bag is not in Claude GG yet");
}

void PhoneBot::resume_spin_later(){
    m_spin_at = wall() + BAG_FULL_WAIT;
}

double PhoneBot::throw_ball(std::optional<bool>& hit){
    hit = std::nullopt;
    throw std::runtime_error("throwing a ball is not in Claude GG yet");
}

std::pair<std::optional<double>, std::optional<double>> PhoneBot::read_heat(){
    if (!m_told_heat){
        m_told_heat = true;
        log("the temperatures of the phone and the Pi cannot be read through the agent yet: no pause when it gets hot");
    }
    return {std::nullopt, std::nullopt};
}

cv::Mat PhoneBot::quick_screenshot_grab(const std::function<void()>& on_grab){
    cv::Mat img = m_phone.screenshot();
    if (on_grab){
        try{
            on_grab();
        }catch (const Flow::Interrupted&){
            throw;
        }catch (const std::exception& e){
            log(QString("action after the screenshot failed: ") + QString::fromUtf8(e.what()));
        }
    }
    return img;
}

double PhoneBot::do_map(const cv::Mat& img){
    return Map::do_map(*this, m_map, m_eyes, img);
}
double PhoneBot::do_pokestop(const cv::Mat& img){
    return Map::do_pokestop(*this, m_map, img);
}
double PhoneBot::do_encounter(const cv::Mat&){
    //  Catching is not in Claude GG yet: the catch screen opened anyway (a Pokémon came up by itself, or was tapped by the person).
    log("catch screen, but catching is not in Claude GG yet - running away");
    tap(Catch::RUN_BTN.x, Catch::RUN_BTN.y);
    Map::reset_encounter(*this, m_map);
    return 3;
}

void PhoneBot::resume_catch_later(double seconds){
    m_catch_at = wall() + seconds;
}


void run(PhoneBot& bot, const std::function<void()>& beat){
    while (!bot.stop()){
        bot.timers();
        double wait;
        try{
            wait = Step::step(bot, bot.map_state(), bot.step_state());
        }catch (const Flow::Interrupted&){
            throw;
        }catch (const std::exception& e){
            if (bot.stop()){
                break;
            }
            bot.log(QString("error: ") + QString::fromUtf8(e.what()));
            wait = STEP_ERROR_WAIT;
        }
        if (beat){
            beat();
        }
        bot.sleep(wait);
    }
    throw Flow::Interrupted();
}


}
}
}
}
