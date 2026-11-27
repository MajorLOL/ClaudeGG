/*  Claude GG Pokemon GO Flow (the walk around a fight of the Pokémon GO bot)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port of the parts of Mobile/gamebot.py that bring the bot to a fight and back (issue #30): battle_open_menu() walks from
 *  the map (or from the Battle screen after a fight) to the party screen of the league, looking at what is really on the
 *  screen at every step (the main menu, the Battle screen, a claim of a new rank, the gold reward tiles, a new set of battles
 *  that has to be scrolled to, the list of leagues, pop-ups); _battle_to_map() leaves the battle screens again; battle_run()
 *  fights a number of battles one after the other (party screen, USE THIS PARTY, the fight, the next one).
 *
 *  The flow knows nothing of the phone, the clock or the text reader: it is given a Host (the Host of the fight loop, with
 *  the touches and the screen class added).  run_flow_checks() holds it, in every build, to the stories of
 *  tests/fixtures/flow_golden.json.qz that Mobile/tools/make_flow_golden.py made with gamebot.py: the same pictures and
 *  readings in, and the same taps, swipes, log lines, sleeps and saved pictures out, in the same order and at the same
 *  moments of a fake clock.  The label of a button (the preparation of its picture for the text reader) is held to the
 *  picture that gamebot.button_label() gives the reader.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoFlow_H
#define PokemonAutomation_ClaudeGG_PokemonGoFlow_H

#include <exception>
#include <optional>
#include <utility>
#include <vector>
#include <opencv2/core.hpp>
#include <QString>
#include <QStringList>
#include "ClaudeGG_PokemonGoLoop.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Flow{

using Loop::Point;
typedef Nav::Spot Spot;


//  What the walk is given besides what the fight loop is given: the touches (a press, a swipe, BACK), the screen classifier,
//  the clock of the wall, restarting the game, and what the program keeps (the day on which the battles were done).
class Host : public Loop::Host{
public:
    //  time.time(): the seconds of the wall clock (monotonic() is time.monotonic()).
    virtual double wall() = 0;
    //  S.tap(x, y), S.swipe(...) and S.back() on the canvas (1768 x 2208).
    virtual void tap(int x, int y) = 0;
    virtual void swipe(int x1, int y1, int x2, int y2, int ms) = 0;
    virtual void back() = 0;
    //  The label of a wide button ('' when it is not read); by default what gamebot.button_label() does with the text reader.
    virtual QString button_label(const cv::Mat& img, const Vision::Button& button);
    //  (name, certainty) of the screen classifier ("onbekend", 0.0 when it cannot be used).
    virtual std::pair<QString, double> screen_class(const cv::Mat& img) = 0;
    //  Close the game and start it again (the walk back to the map failed).
    virtual void restart_game() = 0;
    //  Ask for the comparison of raw and PNG screenshots again at the next screenshot (a quiet moment).
    virtual void recheck_shot_mode(){}
    //  The Battle screen showed a grey BATTLE button: write down that the battles of today are done.
    virtual void mark_battles_done(){}
    //  The count of the day after a fight ("(today: 3 caught, ...)"), key "won" or "lost"; "" when there is none.
    virtual QString day_count(const QString& key){ (void)key; return QString(); }
    //  The names of the Pokémon of the team (to find them on the party screen).
    virtual QStringList team_names(){ return QStringList(); }
    //  The time of the run is up: no new battle.
    virtual bool no_more(){ return false; }
    //  One battle (fight_battle); the checks give a story of their own.
    virtual Loop::Result fight(const std::vector<Battle::Mon>& team, const std::vector<Point>& use_spots);
};

//  Thrown by a host when the person stops the bot (Ctrl+C: KeyboardInterrupt): battle_run() does not walk back through the
//  menus then (BACK in a running battle would give it up).
class Interrupted : public std::exception{
public:
    const char* what() const noexcept override{ return "interrupted"; }
};


//  ---- what is looked at

//  gamebot.screen_changed(): is more than `share` of the (small) picture another colour than it was?
bool screen_changed(const cv::Mat& a, const cv::Mat& b, double share = 0.05);

//  A screenshot of a screen that has stopped moving: two screenshots at least a second apart that show the same.
cv::Mat settled(Host& host, double first_wait = 2.0);

//  The picture of a button's label as it is given to the text reader (black letters on white, what is lighter than the button
//  around them); empty when the button is too small to read.
cv::Mat label_picture(const cv::Mat& img, const Vision::Button& button);
//  What the text reader reads on it, in capitals ('' when it is not read).
QString button_label(Loop::Host& host, const cv::Mat& img, const Vision::Button& button);


//  ---- the walk

struct Info{
    bool ok = false;
    QString why;
    QString title;
    QStringList members;
    std::vector<Spot> use_spots;
    QString chosen;                     //  the league that was chosen on the list (the party screen is that one's)
    bool leave = false;                 //  the screen is left as it is (BACK could throw a reward away)
    bool catch_reward = false;          //  ... because a Pokémon of a reward is to be caught
    bool done_today = false;            //  the battles of today are done
    std::vector<std::pair<QString, int>> leagues;
};

//  Leave the battle screens: look at what is on the screen and go back, never blindly.  With leaving_setup (only the league
//  list or the party screen were looked at, no fight was started) 'Exit the Trainer Battle?' is answered with YES, else with NO.
bool to_map(Host& host, bool leaving_setup = false);

//  Walks from the map (or from the Battle screen after a fight) to the party screen of the league; never presses USE THIS PARTY.
//  stay: wait on the party screen; restart: when the way back to the map fails, restart the game; leagues_only: stop at the league
//  list, read the leagues on it and go back.
Info open_menu(Host& host, bool restart = false, bool stay = false, bool leagues_only = false);

struct Run{
    int fought = 0;
    int wins = 0;
    std::optional<bool> leave;          //  set when the party screen was not reached
    std::optional<bool> catch_reward;
    bool done_today = false;
};

//  Fights `count` battles one after the other: map -> party screen -> USE THIS PARTY -> fight -> next ... and goes back to the map
//  at the end.
Run battle_run(Host& host, const std::vector<Battle::Mon>& team, int count);


//  The numbers of the walk by their names in gamebot.py, for the check.
std::vector<std::pair<QString, std::vector<double>>> flow_constants();


//  ---- the check
//
//  Plays the stories of the file of Mobile/tools/make_flow_golden.py (tests/fixtures/flow_golden.json.qz) on the pictures in
//  `fixtures` (tests/fixtures) and says where the port does something else than gamebot.py did; also checks the picture of
//  the label of a button.  Returns how many stories went another way ("FAILED: ..." lines in `report` say which, the last line
//  says how many were played).
int run_flow_checks(const QString& golden, const QString& fixtures, QStringList& report);


}
}
}
}
#endif
