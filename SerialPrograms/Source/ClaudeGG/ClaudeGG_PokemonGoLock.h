/*  Claude GG Pokemon GO Lock (the lock screen of the phone and the dimmed game)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port of what Mobile/spin_stop.py does when the phone or the game locks itself (issue #31):
 *
 *  is_dimmed(): is the picture dimmed by the game's own lock?  Even the whitest pixels are grey then: the brightest 0.5 % of the pixels (the 99.5th
 *  percentile of the brightness, as numpy's linear one takes it) are below 120.  A night scene with white buttons is not dimmed.
 *
 *  unlock(): the swipe lock screen of the phone (no PIN): when the phone shows it, dismiss it, swipe it away like by hand, and say when it stays.
 *
 *  unlock_game(): Pokémon GO dims and locks itself (Samsung's Game Booster): tap, drag the little lock up, to the right and down, one after the other,
 *  looking at the screen after each, until the picture is not dimmed any more.
 *
 *  Like the rest it knows nothing of the phone: it is given a Host (the map's, with two questions for the phone's lock screen on top of it).
 *  run_lock_checks() holds all of it, in every build, to tests/fixtures/lock_golden.json.qz that Mobile/tools/make_lock_golden.py made with the Python
 *  code: the same answers in, and the same taps, swipes, sleeps and log lines, in the same order and at the same moments of a fake clock.
 *
 *  Where it differs from the Python code: whether the phone shows the lock screen (`dumpsys window`, four words that mean it) is answered by the agent
 *  (GET /v1/power, agent 0.2.5), whose tests hold the words; the Python code asks for it with adb.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoLock_H
#define PokemonAutomation_ClaudeGG_PokemonGoLock_H

#include <opencv2/core.hpp>
#include <QString>
#include <QStringList>
#include "ClaudeGG_PokemonGoMap.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Lock{


inline constexpr int DARK_LIMIT = 120;                  //  the brightest pixels (99.5 %) below this: a dimmed screen (normally 255, dimmed about 50)


class Host : public virtual Map::Host{
public:
    //  Does the phone show its lock screen (keyguard_showing())?  Throws when it cannot say.
    virtual bool keyguard_showing() = 0;
    //  `wm dismiss-keyguard`.
    virtual void dismiss_keyguard() = 0;
};


//  The 99.5th percentile of the brightness of the picture is below DARK_LIMIT.
bool is_dimmed(const cv::Mat& img);
//  Remove the swipe lock screen of the phone; says whether it is gone (false: it was not there to begin with, or it stays).
bool unlock(Host& host);
//  The picture, or the one after the game was woken: the first that is not dimmed (the last one when none is).  Without a picture one is taken.
cv::Mat unlock_game(Host& host, const cv::Mat& img);
cv::Mat unlock_game(Host& host);


//  ---- the check

//  Plays the stories of the file of Mobile/tools/make_lock_golden.py (tests/fixtures/lock_golden.json.qz) and says where the port does something else than
//  the Python code did.  Returns how many went another way ("FAILED: ..." lines in `report` say which, the last line says how many were played).
int run_lock_checks(const QString& golden, QStringList& report, bool stop_at_first = false);


}
}
}
}

#endif
