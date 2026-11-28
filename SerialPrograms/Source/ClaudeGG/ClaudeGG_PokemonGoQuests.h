/*  Claude GG Pokemon GO Quests (the rewards of the GO Pass in the Pokémon GO bot: see that the quest button is gold, and claim what waits)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port of what Mobile/gamebot.py does with the quests (issue #31):
 *
 *  - quest_gold(): the quest button at the bottom right of the map (binoculars) is gold - not white - when something can be claimed: a square around
 *    where it is, and at least 45% of its pixels have a hue of 8 to 25, a saturation of 120 or more and a value of 180 or more;
 *  - quests_due(): the person has the quests switched on, the last look at them is 15 minutes ago or longer, and the button is gold;
 *  - claim_quests(): tap the button, the tab GO PASS, the first three of its pages (their titles say 'GO PASS: ...'; one page without a title when there
 *    are none), scroll down each (six looks at the most) to VIEW REWARDS, tap it, tap CLAIM ALL, and look at what the game did: when a Pokémon came as
 *    a reward (an encounter) the normal bot catches it ('catch'); at the end the round X at the bottom closes the screens (three taps at the most
 *    until the map is back).  It says 'claimed', 'nothing' (the button was gold for something else, research for example: the next look is an hour away),
 *    'catch' (look again in a minute) or 'failed' (the quest screen did not open, or it has no GO PASS tab).
 *
 *  Like the rest it knows nothing of the phone: it is given a Host (that of the map: touches, screenshots, the text reader, the screen classifier, the
 *  clock).  run_quests_checks() holds all of it, in every build, to tests/fixtures/quests_golden.json.qz that Mobile/tools/make_quests_golden.py made with
 *  the Python code: the same pictures and readings in, and the same taps, swipes, log lines, sleeps and saved pictures out, in the same order and at the
 *  same moments of a fake clock, with the same time of the last look afterwards.
 *
 *  Where it differs from the Python code (the stories leave these out):
 *  - a picture that has no pixels left where quest_gold() looks (an empty picture) is read as 'not gold' (Python stops with a cv2.error).
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoQuests_H
#define PokemonAutomation_ClaudeGG_PokemonGoQuests_H

#include <opencv2/core.hpp>
#include <QString>
#include <QStringList>
#include "ClaudeGG_PokemonGoMap.h"
#include "ClaudeGG_PokemonGoNav.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Quests{


//  ---- the numbers of the quests (fractions of the screen, the canvas is 1768 x 2208)

inline constexpr double BUTTON_X = 0.945;               //  the quest button on the map (QUEST_BTN)
inline constexpr double BUTTON_Y = 0.847;
inline constexpr double BUTTON_R = 0.026;               //  its radius, a fraction of the width (QUEST_R)
inline constexpr double CLOSE_X = 0.50;                 //  the round X at the bottom of the quest screens (QUEST_CLOSE)
inline constexpr double CLOSE_Y = 0.925;
inline constexpr int CANVAS_W = 1768;                   //  S.REF_W and S.REF_H: what the fractions are fractions of
inline constexpr int CANVAS_H = 2208;
inline constexpr double EVERY = 15 * 60;                //  s: looked at at most this often (a gold button that stays: not at every step)
inline constexpr double NOTHING = 60 * 60;              //  s: after a look that found nothing to claim, the next one waits this long
inline constexpr double GOLD_SHARE = 0.45;              //  how much of the square has to be gold
inline constexpr int PAGES = 3;                         //  the first pages of the GO PASS that are looked at
inline constexpr int PAGE_LOOKS = 6;                    //  a page is scrolled this many times to find VIEW REWARDS
inline constexpr int CLOSES = 3;                        //  the X is tapped this many times at the most


//  gamebot.quest_state: when the quests were looked at last (the wall clock, time.time()).
struct State{
    double t = 0.0;
};


//  ---- the readers

//  Is the quest button gold (orange) instead of white?
bool quest_gold(const cv::Mat& img);
//  Is it time to claim the quests: they are switched on, 15 minutes have passed and the button is gold?
bool quests_due(Map::Host& host, const State& state, const cv::Mat& img);


//  ---- the visit

//  The quest button is gold: claim what the GO Pass has.  Returns 'claimed', 'nothing', 'catch' or 'failed'.  (Throws what the host throws: a phone that
//  does not answer, the person who stops the bot.)
QString claim_quests(Map::Host& host, State& state);


//  Plays the stories of tests/fixtures/quests_golden.json.qz (what the Python code did) on the port and says in `report` what went another way.
//  Returns how many stories went another way.
int run_quests_checks(const QString& golden, QStringList& report, bool stop_at_first = false);


}
}
}
}

#endif
