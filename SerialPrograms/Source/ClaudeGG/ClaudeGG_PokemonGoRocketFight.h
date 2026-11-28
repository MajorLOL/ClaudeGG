/*  Claude GG Pokemon GO Rocket Fight (the fight against Team GO Rocket in the Pokémon GO bot)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port of rocket_fight() of Mobile/gamebot.py (issue #31): the fight against the Team GO Rocket grunts and leaders at a PokéStop, played until its HUD
 *  (the two name boxes) has been gone for a while.  It looks at the screen all the time (Eyes: the live video of the phone, or screenshots) and:
 *  - taps the fast attacks on the buttons of the charged attacks, by turns (four pictures each) on the middle one (a Pokémon with one charged attack) and
 *    the left one (with two): a button that is ready throws its attack at the next tap, a button that is not ready is a fast attack;
 *  - reads the name of our Pokémon in its name box every six seconds, and from its name the types of the charged attacks that it can have;
 *  - knows the little game of a charged attack by its icons: of the types that our Pokémon's charged attacks can have (of all of them when its name is not
 *    known) the one whose icons - three or more - come up on a picture without the HUD, and swipes it (Loop::LittleGame, as in a battle of the league);
 *  - gives every 'Use a Protect Shield?' a shield (once in six seconds).
 *  It ends when the HUD has been gone for ten seconds and no little game was going (the speech bubble, the rewards ...), when no fight came in the first
 *  forty seconds, after 300 seconds, or when the person stops the bot.  It says how many seconds it took.
 *
 *  Like the rest it knows nothing of the phone: it is given a Host (that of the fight loop: the live video, the finger that taps, the text reader, the
 *  clock).  run_rocket_fight_checks() holds all of it, in every build, to tests/fixtures/rocketfight_golden.json.qz that Mobile/tools/make_rocketfight_golden.py
 *  made with the Python code on pictures of real fights: the same pictures and text readings in, and the same taps, swipes, log lines and aims out, in the
 *  same order and at the same moments of a fake clock.
 *
 *  Where it differs from the Python code (the stories leave these out):
 *  - when no name of ours is known, the types are tried in alphabetical order (Python tries the types in the order of a set of text, which changes from run
 *    to run: on a picture with the icons of two types it would take either);
 *  - the person who stops the bot is asked every look, as Python does when it is given a stop function (the host that has none answers 'no').
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoRocketFight_H
#define PokemonAutomation_ClaudeGG_PokemonGoRocketFight_H

#include <QString>
#include <QStringList>
#include "ClaudeGG_PokemonGoLoop.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace RocketFight{


//  ---- the numbers of the fight against Team GO Rocket

inline constexpr double SECONDS = 300;                  //  ROCKET_FIGHT_SECONDS: a fight lasts this long at the most
inline constexpr double BTN_X[3] = {0.307, 0.50, 0.690};//  ROCKET_BTN_X: the charged attack buttons: left, middle (one attack only), right
inline constexpr double NAMED_EVERY = 6;                //  s: the name of ours is read this often
inline constexpr double SHIELD_EVERY = 6;               //  s: a shield question is answered this often (the same question stays a while on the screen)
inline constexpr double GAME_EVERY = 8;                 //  s: a little game is looked for this long after the last one began
inline constexpr double GAME_LONGEST = 14;              //  s: a little game that does not end by itself is ended after this
inline constexpr double HUD_GONE = 10;                  //  s: the fight is over when the HUD and the little game are gone this long
inline constexpr double NO_FIGHT = 40;                  //  s: no fight came when there is no HUD in this time
inline constexpr int GAME_ICONS = 3;                    //  the icons of a type that make a little game
inline constexpr int TURN_PICTURES = 4;                 //  pictures on a button, then the other


//  The types of the charged attacks that a Pokémon of this name can have, in alphabetical order (nothing when the name is not known).  Needs the data of the
//  engine (Battle::load_data()).
QStringList rocket_kinds(const QString& name);

//  The fight against Team GO Rocket until its HUD is gone for a while.  Returns the seconds it took.  (Throws what the host throws: a phone that does not
//  answer; the fingers and the video are put away first.)
int rocket_fight(Loop::Host& host);


}

namespace Loop{

//  Plays the fights of tests/fixtures/rocketfight_golden.json.qz (what rocket_fight() of the Python code did on pictures of real fights) on the port and says
//  in `report` what went another way.  The pictures are in `fixtures` (tests/fixtures), the data of the engine in `data` (models/battle_data.json).  Returns how
//  many fights went another way ("FAILED: ..." lines in `report` say which, the last line says how many were played).  (It is in the file of the check of
//  the loop, which has the pretend phone of the fights.)
int run_rocket_fight_checks(const QString& golden, const QString& fixtures, const QString& data, QStringList& report, bool stop_at_first = false);

}
}
}
}

#endif
