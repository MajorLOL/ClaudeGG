/*  Claude GG Pokemon GO Chapter (one part of the bot on its own)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port of run_chapter() of Mobile/gamebot.py and the list of Mobile/chapters.py (issue #31): a part of the bot that runs on its own, from the
 *  screen that is on the phone now, so that a fix can be tried in a minute instead of waiting for the moment in a whole run.  It says
 *  'TEST <key>: started - <title> (start screen: ...)' and at the end 'TEST <key>: done - ...' (or 'failed - ...'), and saves the screen at the
 *  start and at the end (g_test_start.png, g_test_end.png).
 *
 *  The parts that the C++ bot has: screen (what the bot sees: one screenshot, no taps), play (the normal bot for 3 minutes), catch, throw,
 *  rocket, rocket_fight, bag, quests and gifts.  Not here (they stay on the Pi): the live video, looking (video against screenshots), the checks
 *  that contain these, the leagues, the Pokémon and the teams, the storage.  The battles are the program 'GO Battle League'.
 *
 *  Where it differs from the Python code: the first screenshot of the run is not taken for a start picture that is not the screen of the
 *  agent's display (the layout check of the run does the looking), and the throw does not count itself as a throw of an encounter (the catch
 *  screen is not in play: nothing reads the result screen afterwards).
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoChapter_H
#define PokemonAutomation_ClaudeGG_PokemonGoChapter_H

#include <vector>
#include <QString>
#include <QStringList>
#include "ClaudeGG_PokemonGoBot.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Chapter{

//  CHAPTERS of chapters.py: the key, the title, the screen the game has to be on at the start.
struct Info{
    const char* key;
    const char* title;
    const char* start;
};

//  The parts that the C++ bot can run on its own, in the order of chapters.py.
const std::vector<Info>& available();
const Info* find(const QString& key);
//  The keys, comma separated (the line of 'no such test').
QString keys();

inline constexpr double PLAY_SECONDS = 180;             //  CHAPTER_PLAY_S: 'Normal play for 3 minutes'
inline constexpr double CATCH_SECONDS = 180;            //  CHAPTER_CATCH_S: at most this long for 'Catch this Pokémon' (and the catch after a Rocket battle)

struct Result{
    bool ok = false;
    QString how;
};

//  _chapter_steps(): the normal bot, step after step, for `seconds` - or (until_map) until it is back on the map after at least one step.
//  Returns the number of steps.
int chapter_steps(Bot::PhoneBot& bot, double seconds, bool until_map);

//  Runs one part (the log says how it goes).  Flow::Interrupted does not leave it: the person's stop is a result ('stopped') like any other.
Result run(Bot::PhoneBot& bot, const QString& key);

}
}
}
}
#endif
