/*  Claude GG Pokemon GO Rocket (Team GO Rocket at a PokéStop in the Pokémon GO bot: the way to the fight and back to the map)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port of what Mobile/gamebot.py does with a PokéStop of Team GO Rocket (issue #31), the part around the fight:
 *
 *  rocket_battle(): from the first screen of the encounter to the map again (or to the Shadow Pokémon that is to be caught: then the normal bot catches
 *  it).  It looks at the screen about every 1.5 seconds, at most 70 times, and does what the screen asks:
 *  - the map: done ('map');
 *  - the fight (or the question in it): the fight is played by the host (rocket_fight() of the Python code, a port of its own);
 *  - 'Use your Rocket Radar?': the word YES (or the middle of the screen when the reader did not find it);
 *  - 'Recommended Battle Party': a slot without a Pokémon (the words CP and its number stand over the filled slots) is filled with the first Pokémon of
 *    the list that it opens (DONE), then USE THIS PARTY;
 *  - the list of Pokémon (CANCEL, DONE): the first one, then DONE;
 *  - SUMMARY after the fight: tapped on;
 *  - the screen before the fight: BATTLE in the lower quarter of the screen (not again after the fight);
 *  - after the fight the screen of the Shadow Pokémon (the screen classifier says an encounter): 'catch' (the normal bot catches it);
 *  - anything else (speech bubbles, the rewards, the VS screen): a tap in the middle of the screen; more than 25 of them stop the walk ('failed').
 *  It says 'map', 'catch' or 'failed' (70 looks that led nowhere, too many screens that are not known, or the person who stops the bot).
 *
 *  Like the rest it knows nothing of the phone: it is given a Host (that of the map, and the fight reader and the fight itself on top of it).
 *  run_rocket_checks() holds all of it, in every build, to tests/fixtures/rocket_golden.json.qz that Mobile/tools/make_rocket_golden.py made with the
 *  Python code: the same pictures and readings in, and the same taps, log lines, sleeps and saved pictures out, in the same order and at the same moments
 *  of a fake clock.  The fight itself is a seam in these stories (the story says that it was played and where the phone is after it).
 *
 *  Where it differs from the Python code (the stories leave these out):
 *  - the person who stops the bot is asked every look, as Python does when it is given a stop function (the host that has none answers 'no');
 *  - a picture that has no height or width is a mistake of the phone (Python stops with a division by zero, here the host's screenshot is trusted).
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoRocket_H
#define PokemonAutomation_ClaudeGG_PokemonGoRocket_H

#include <array>
#include <opencv2/core.hpp>
#include <QString>
#include <QStringList>
#include "ClaudeGG_PokemonGoMap.h"
#include "ClaudeGG_PokemonGoNav.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Rocket{


//  ---- the numbers of Team GO Rocket (fractions of the screen, the canvas is 1768 x 2208)

inline constexpr int STEPS = 70;                        //  ROCKET_STEPS: so many looks at the screen at the most
inline constexpr int UNKNOWN_SCREENS = 25;              //  more screens that are not known than this stop the walk
inline constexpr std::array<double, 3> PARTY_X = {0.33, 0.51, 0.69};//  ROCKET_PARTY_X: the three slots of 'Recommended Battle Party'
inline constexpr double LIST_FIRST_X = 0.18;            //  ROCKET_LIST_FIRST: the first Pokémon in the list that a slot opens
inline constexpr double LIST_FIRST_Y = 0.70;
inline constexpr double BATTLE_X = 0.33;                //  ROCKET_BATTLE_X: BATTLE on the screen before the fight, left of the round X over its middle
inline constexpr double BATTLE_FROM = 0.75;             //  BATTLE is the word in the lower quarter of the screen
inline constexpr double PARTY_SLOT_NEAR = 0.08;         //  a number of the party is over a slot when it is this close to it (fraction of the width)
inline constexpr double PARTY_BELOW = 0.05;             //  the list is opened this far (fraction of the height) under the numbers
inline constexpr int CANVAS_W = 1768;
inline constexpr int CANVAS_H = 2208;
inline constexpr int SMALL_W = 704;                     //  the picture that the fight reader looks at is this wide
inline constexpr double LOOK_EVERY = 1.5;               //  s between two looks


//  What the walk needs of the phone, on top of the map: the fight reader and the fight.
class Host : public virtual Map::Host{
public:
    //  battle_fight.state(battle_vision.features(small)) of the small picture (704 wide): 'fight', 'prompt' or 'other'.
    virtual QString screen_state(const cv::Mat& small) = 0;
    //  rocket_fight(): plays the fight that is going on, until it is over (a port of its own).
    virtual void rocket_fight() = 0;
};


//  The way through a fight of Team GO Rocket.  Returns 'map', 'catch' or 'failed'.  (Throws what the host throws: a phone that does not answer.)
QString rocket_battle(Host& host);


//  Plays the stories of tests/fixtures/rocket_golden.json.qz (what the Python code did) on the port and says in `report` what went another way.
//  Returns how many stories went another way.
int run_rocket_checks(const QString& golden, QStringList& report, bool stop_at_first = false);


}
}
}
}

#endif
