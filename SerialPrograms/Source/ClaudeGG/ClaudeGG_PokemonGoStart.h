/*  Claude GG Pokemon GO Start (starting the game and the battles of a run, of the Pokémon GO bot)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port of what Mobile/gamebot.py and Mobile/spin_stop.py do when Pokémon GO is started (issue #30):
 *
 *  - restart_game(): close the game and start it again; while it starts a screenshot is looked at every couple of seconds
 *    (startup_screen()): a news card ("DISMISS" at the bottom) or the safety notice ("Stay aware of your surroundings", only OK
 *    makes it go away) is tapped away the moment it shows up, and the start is finished when the map has been there twice in
 *    a row;
 *  - find_pill_button() and find_green_button(): the big green buttons of such a notice (the pill of a gift screen is paler
 *    than the green of the other screens);
 *  - the settings of the battles (battle_app(), battle_league(), battle_count(), battle_wanted()) and auto_battle(): the
 *    battles of a run, fought with the team before the daily spinning and catching.
 *
 *  Like the walk (ClaudeGG_PokemonGoFlow) it knows nothing of the phone: it is given a Host.  The Host adds to that of the walk
 *  what the start of the game needs (stop_game(), start_game(), start_state(), start_end()).  run_start_checks() holds all of
 *  it, in every build, to tests/fixtures/start_golden.json.qz that Mobile/tools/make_start_golden.py made with the Python code:
 *  the same pictures and readings in, and the same taps, log lines, sleeps and calls out, in the same order and at the same
 *  moments of a fake clock; and the same buttons on 321 pictures.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoStart_H
#define PokemonAutomation_ClaudeGG_PokemonGoStart_H

#include <functional>
#include <optional>
#include <utility>
#include <vector>
#include <opencv2/core.hpp>
#include <QString>
#include <QStringList>
#include "ClaudeGG_PokemonGoFlow.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Start{

using Loop::Point;


extern const Point DISMISS_BTN;             //  DISMISS under a news card
extern const Point NOTICE_OK_BTN;           //  OK on the safety notice of the start
extern const char* const MAIN_PACKAGE;      //  the Pokémon GO of the Play Store (the first app)
extern const char* const BATTLE_LEAGUE;     //  the league of the battles when none is chosen
extern const int BATTLE_COUNT;              //  the battles of a run when no number is chosen


//  ---- what is looked at

//  A button that was found: its middle and the number of its pixels.
struct Found{
    int x = 0;
    int y = 0;
    int area = 0;
};

//  The green pill button (OPEN / SEND, OK of a notice) from row y_min on: a pale green button, 450 - 1300 wide, 80 - 320 high, in the
//  middle; the biggest one.  gamebot.find_pill_button().
std::optional<Found> find_pill_button(const cv::Mat& img, int y_min = 1500);
//  The big green button (CLAIM REWARD!, OK) in the lower half: wide, in the middle, the biggest one.  spin_stop.find_green_button().
std::optional<Found> find_green_button(const cv::Mat& img);

//  All text in the rows y0 to y1 of the picture, in capitals, white space as one space (gamebot.ocr_text()).
QString ocr_text(Loop::Host& host, const cv::Mat& img, int y0, int y1);
//  A news card over the map: it has the word DISMISS at the very bottom of the screen.
bool news_popup(Loop::Host& host, const cv::Mat& img);
//  The notice of the start ('Stay Aware of Your Surroundings', 'Do not trespass ...'): it only goes away with OK.
bool safety_notice(Loop::Host& host, const cv::Mat& img);


//  ---- starting the game

enum class Look{
    Nothing,            //  nothing that is known (the game is loading)
    Map,                //  the map is there
    Handled,            //  a card was tapped away
};

//  Looks at one screenshot while the game starts: taps a news card or the safety notice away, says whether the map is there.
Look startup_screen(Flow::Host& host, const cv::Mat& img);

//  How the start of the game (the command that starts it is not waited for) is going.
struct Launch{
    bool running = true;            //  it has not ended
    int code = 0;                   //  the return code when it has
    QString error;                  //  what it wrote as an error
};

class Host : public Flow::Host{
public:
    //  Close the game (throws std::runtime_error when that does not work).
    virtual void stop_game() = 0;
    //  Start it; the call does not wait for the game to be up.
    virtual void start_game() = 0;
    //  What came of the command that starts the game (asked once, after the game is up or the time is over).
    virtual Launch start_state() = 0;
    //  The command is not needed any more (it is still running when this is called).
    virtual void start_end() = 0;
};

//  Close Pokémon GO and start it again.  Looks at a screenshot every couple of seconds for at most 100 s; ends when the map has been
//  there twice in a row.  Throws what the Host throws for closing the game (and Flow::Interrupted when the person stops the bot);
//  a screenshot or a reading that fails is told and tried again.
void restart_game(Host& host);


//  ---- the battles of a run

//  What the person chose for the battles.
struct Settings{
    bool battle = false;                //  'battle'
    QString app;                        //  'battle_app': the package of the app that fights; empty: the first app
    std::optional<QString> league;      //  'battle_league': nothing: Great League
    std::optional<int> count;           //  'battle_count': nothing: 5
};

struct Choice{
    bool wanted = false;                //  battle_wanted(): chosen, and not done for today
    QString app;                        //  battle_app()
    QString league;                     //  battle_league(): without the spaces around it, 40 letters at most
    int count = 0;                      //  battle_count(): 1 - 50
};
Choice choose(const Settings& settings, bool done_today);

struct AutoBattle{
    int fought = 0;                     //  the battles that were fought
    std::optional<bool> resume;         //  run_state['battle_resume'] (nothing: no battles were started)
};

typedef std::function<std::vector<Battle::Mon>()> TeamLoader;
typedef std::function<Flow::Run(Flow::Host&, const std::vector<Battle::Mon>&, int)> Runner;

//  Fights the battles of this game when `package` is the app that was chosen for battles: loads the team, writes down what is
//  going to happen, lets battle_run() fight them (the host's beat(), stop() and no_more() are those of the run) and writes down what
//  came of it.  The team that cannot be loaded gives no battles.  gamebot.auto_battle().
AutoBattle auto_battle(Flow::Host& host, const QString& package, const Settings& settings, bool done_today,
                       const TeamLoader& load_team, const Runner& run = Runner());


//  The numbers of the start by their names in gamebot.py, for the check.
std::vector<std::pair<QString, std::vector<double>>> start_constants();


//  ---- the check
//
//  Plays the pictures and the stories of the file of Mobile/tools/make_start_golden.py (tests/fixtures/start_golden.json.qz) and says
//  where the port does something else than the Python code did.  Returns how many went another way ("FAILED: ..." lines in `report`
//  say which, the last line says how many were played).
int run_start_checks(const QString& golden, QStringList& report);


}
}
}
}
#endif
