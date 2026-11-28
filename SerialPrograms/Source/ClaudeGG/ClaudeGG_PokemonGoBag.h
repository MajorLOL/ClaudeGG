/*  Claude GG Pokemon GO Bag (the item bag of the Pokémon GO bot: clean it up when it is full, and what to do when storage and bag are both full)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port of what Mobile/gamebot.py and Mobile/bag_rules.py do with the item bag (issue #31):
 *
 *  - rules(), plan(), keep_for(), rows(): what the bag keeps of each item (the numbers that are set in the interface, or the standard ones: Potion,
 *    Super and Hyper Potion 0, Max Potion 30, Max Revive 30, Poké Ball 400, Great Ball 100, 30 of each berry; Revive and Ultra Ball are not touched),
 *    which of the names that were read in the bag are such an item (the name as read, a little misread is fine), and the rows of a page of the bag with
 *    the number under each ('x487');
 *  - clean_bag(): open the bag, look at it page by page, tap the trash can of an item that has too many, set the number of the question 'Discard <item>?'
 *    (discard_dialog() reads its title, YES, NO and the number; set_discard_number() taps - and + until it shows what is wanted) and press YES only
 *    when the question names that item and that number - anything else gets NO - and back to the map;
 *  - open_bag(), bag_to_map(), leave_question(): the way to the bag (looking at what is really on the screen at every step) and back from wherever the
 *    routine ended, never confirming a question to exit or to discard;
 *  - bag_ocr(), bag_like(), incense_tile(): reading a page of the bag with a second, third and fourth way of looking at the picture when the first
 *    reads nothing of the bag (the way that worked is tried first the next time), and the middle of the words DAILY ADVENTURE;
 *  - check_menu_full(): the red FULL marks in the main menu under POKÉMON and ITEMS;
 *  - close_game_completely() and check_all_full(): when the storage and the bag are both full, close Pokémon GO (also in the recent apps) and wait
 *    until the person opens it again (or tell the daily run that it is over).
 *
 *  Like the rest it knows nothing of the phone: it is given a Host, which adds to that of the map what the bag needs (several touches in one command,
 *  adb, the package of the game, what the person chose to keep, and the daily run).  run_bag_checks() holds all of it, in every build, to
 *  tests/fixtures/bag_golden.json.qz that Mobile/tools/make_bag_golden.py made with the Python code: the same pictures and readings in, and the same
 *  taps, swipes, log lines, sleeps and saved pictures out, in the same order and at the same moments of a fake clock, with the same things remembered
 *  afterwards.
 *
 *  Not ported: the daily incense (the option is gone from the web interface: the game does not take injected touches on its card), and the summary
 *  sentence of bag_rules.py (it is for the web page).  Numbers that a question reads with more than 18 digits are all taken as the same huge number.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoBag_H
#define PokemonAutomation_ClaudeGG_PokemonGoBag_H

#include <optional>
#include <utility>
#include <vector>
#include <opencv2/core.hpp>
#include <QJsonValue>
#include <QString>
#include <QStringList>
#include "ClaudeGG_PokemonGoCatch.h"
#include "ClaudeGG_PokemonGoMap.h"
#include "ClaudeGG_PokemonGoNav.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Bag{

using Loop::Point;
typedef Nav::Spot Spot;


//  ---- the numbers of the bag (canvas of 1768 x 2208)

inline constexpr int CANVAS_W = 1768;                   //  S.REF_W, S.REF_H: the canvas that all the places are written for
inline constexpr int CANVAS_H = 2208;
inline constexpr Point MENU_BTN{884, 1985};             //  the Poké Ball button on the map -> main menu (and the round X at the bottom that closes it)
inline constexpr Point CLOSE_ALL_BTN{875, 1640};        //  'Alle sluiten' in the recent apps
inline constexpr int ITEMS_ICON_DY = 195;               //  main menu: the round ITEMS button sits this far (px on a 2208 high screen) below its label
inline constexpr int MAX_KEEP = 9999;                   //  the most that can be set to keep
inline constexpr double TRASH_X = 0.80;                 //  the trash can of a row, right of its name (fraction of the width) ...
inline constexpr double TRASH_DY = -0.017;              //  ... a little above the middle of its name (fraction of the height)
inline constexpr double COUNT_DY_FROM = 0.04;           //  the count 'x487' stands under the left of the picture, this far under the name (fraction of the height)
inline constexpr double COUNT_DY_TO = 0.16;
inline constexpr double DISCARD_MINUS_X = 0.26;         //  'Discard <item>?': the - and + buttons ...
inline constexpr double DISCARD_PLUS_X = 0.726;
inline constexpr double DISCARD_NUMBER_AT = 0.458;      //  ... and the number between them: this far from the title down to YES
inline constexpr int CLEAN_PAGES = 30;                  //  pages of the bag that are looked through
inline constexpr double OCR_SCALE = 0.6;                //  the names in the bag list are big: a smaller picture reads them faster
inline constexpr int SWIPE_PAGE[5] = {1150, 1800, 1150, 700, 900};     //  one page down (x1, y1, x2, y2, ms)
inline constexpr int DISCARD_TRIES = 14;                //  rounds of taps that set the number of the question
inline constexpr int MAX_TAPS_AT_ONCE = 40;             //  taps of - or + in one command


//  ---- what the bag keeps

//  One item of the plan: its plain name (capitals, no accents: 'POKE BALL'; a name that ends in '*' stands for every item with that word in its name)
//  and how many are kept (nothing: that item is not touched - rules() never makes such a rule, a plan that is written by hand can).
struct Rule{
    QString name;
    std::optional<int> keep;
};

//  bag_rules.rules(saved): (name as the game shows it, how many are kept) of the items that are cleaned up, in the order of the standard list.  `saved` is
//  what the person set ('bag_keep': an object name -> number, text or null; anything else is the standard).  Throws std::runtime_error for a number that
//  is infinity (Python's OverflowError).
std::vector<std::pair<QString, int>> rules(const QJsonValue& saved);

//  A name in capitals without accents or punctuation, one space between the words ('Poké Ball' is 'POKE BALL').
QString plain_name(const QString& text);


//  ---- the phone, the person and the parts that come later

//  (virtual: the real host of the bot is also a Catch::Host and so on, and all of them are one Map::Host.)
class Host : public virtual Map::Host{
public:
    //  S.swipes(strokes): touches one after the other in ONE adb command.
    virtual void swipes(const std::vector<Loop::Stroke>& strokes) = 0;
    //  S.adb(...): what an adb command answered.  Throws std::runtime_error with the text of the error when it fails.
    virtual QString adb(const QStringList& args) = 0;
    //  S.PACKAGE: the package of the game on the phone.
    virtual QString package() = 0;
    //  setting("bag_keep", None): what the person chose to keep (null when nothing was chosen).
    virtual QJsonValue bag_keep_saved() = 0;
    //  run_state["done"] = True: the daily run is told that it is over.
    virtual void run_done() = 0;
};

//  What the bag routines remember (gamebot._ocr_variant).
struct State{
    int ocr_variant = 0;                //  the way of looking at a page of the bag that worked last
};


//  ---- what the bag keeps of each item

//  bag_plan(): the rules as the clean-up uses them now (plain names).
std::vector<Rule> plan(Host& host);
//  bag_keep(name, plan): how many of the item with this name (as read in the bag) are kept, or nothing: not to be touched.
std::optional<int> keep_for(const QString& name, const std::vector<Rule>& plan);

//  A row of a page of the bag whose item has a rule (bag_rows()).
struct Row{
    QString name;                       //  plain
    int keep = 0;
    int x = 0;
    int y = 0;
    std::optional<int> count;           //  the number under the picture ('x487') when it was read
};
std::vector<Row> rows(const Nav::Lines& lines, int h, const std::vector<Rule>& plan);

//  The question 'Discard <item>?' (_discard_dialog()).
struct Dialog{
    QString title;                      //  the line of the title as it was read
    std::optional<long long> n;         //  the number in the box between - and +, when it was read
    QString n_text;                     //  ... as Python writes the number (for the log)
    Spot yes;
    Spot no;
    int number_y = 0;                   //  the height of the number (picture)
};
std::optional<Dialog> discard_dialog(Host& host, const cv::Mat& img);
//  _canvas(): a place on the picture as a place on the canvas.
std::pair<int, int> canvas(const cv::Mat& img, double x, double y);
//  Tap - and + of the open question until it shows `target` (at most `tries` rounds).  The last picture and what was read on it.
std::pair<cv::Mat, std::optional<Dialog>> set_discard_number(Host& host, int target, int tries = DISCARD_TRIES);


//  ---- looking at the bag

bool bag_like(const Nav::Lines& lines);
//  The middle of the words DAILY ADVENTURE, or nothing.
std::optional<Spot> incense_tile(const Nav::Lines& lines);
//  The page of the bag as the text reader reads it, with the way of looking that works (see the top).  From row y0 down.
Nav::Lines bag_ocr(Host& host, State& state, const cv::Mat& img, int y0 = 250);

//  The picture and the lines of the bag, when it was opened from the map (nothing: it did not open).
std::optional<std::pair<cv::Mat, Nav::Lines>> open_bag(Host& host);
//  Back to the map from wherever the routine ended (bag, item, main menu, a question): never confirms a question.
void bag_to_map(Host& host);
//  'Exit Pokémon GO?' is answered with CANCEL, 'Discard ...?' with NO: `kind` is "exit" or "discard" (the screen kind).
void leave_question(Host& host, const QString& kind, const Nav::Lines& lines);
void cancel_exit(Host& host, const Nav::Lines& lines);
void cancel_discard(Host& host, const Nav::Lines& lines);


//  ---- the steps

//  The bag is full: discard what plan() says (from the map, back on the map).  Returns the number of items discarded.
int clean_bag(Host& host, State& state);
//  Open the main menu and read the red FULL labels (storage full under POKÉMON, bag full under ITEMS), and close it again.
void check_menu_full(Host& host, Map::State& state);
//  Stop Pokémon GO and take it out of the recent apps.  Says so in the log when that fails.
void close_game_completely(Host& host);
//  Storage AND bag full (and the person wants the game closed, or it is a daily run): close the game; wait until it is opened again, or tell the daily run.
void check_all_full(Host& host, Map::State& state);


//  ---- the check
//
//  Plays the stories of the file of Mobile/tools/make_bag_golden.py (tests/fixtures/bag_golden.json.qz) and says where the port does something else
//  than the Python code did.  Returns how many went another way ("FAILED: ..." lines in `report` say which, the last line says how many were played).
int run_bag_checks(const QString& golden, QStringList& report, bool stop_at_first = false);


}
}
}
}
#endif
