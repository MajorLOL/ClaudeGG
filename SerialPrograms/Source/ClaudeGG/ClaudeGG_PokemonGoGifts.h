/*  Claude GG Pokemon GO Gifts (the gifts of the friends in the Pokémon GO bot: open the ones that wait and send one to every friend)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port of what Mobile/gamebot.py does with the gifts of the friends (issue #31):
 *
 *  - parse_friends(): the rows of the friend list from the lines of the text reader (a name next to 'Today', 'Yesterday', '2+ days ago', ...; or a
 *    name with 'caught ...!' or 'sent you a Gift!' under it), with for every friend whether a gift waits (the words 'sent you a Gift!' in the row, or
 *    the pink bow in its icon column: gift_icon()) and whether a gift of you is already on its way (the grey circle with the white arrow at the
 *    bottom right of the avatar: sent_arrow());
 *  - is_friend_list(), is_gift_screen(), find_pill_button(), send_button(), has_sticker_button(), any_text(): the readers of the screens (the green
 *    pill buttons OPEN and SEND are found by their colour and shape; ADD STICKER is read, because the SEND label below it is not);
 *  - load_gift_state(), save_gift_state(): the memory of the day (who was sent a gift, whose gift was opened, whether opening or sending is over for today),
 *    one file for each Pokémon GO app on the phone;
 *  - visit_friend(): tap the friend, open the gift that waits (and skip the overview of what it holds), scroll the profile in small slow steps until
 *    the SEND GIFT or TRADE label is in view, look at the colour of the gift icon above it (pink: a gift can be sent, grey: not today), choose the first
 *    gift of the list and press SEND, with a look at every step whether the screen did what it should;
 *  - gifts_round(): from the map through the avatar and the FRIENDS tab to the friend list, scroll it page by page, visit every friend that is
 *    wanted once and go back to the map.
 *
 *  Like the rest it knows nothing of the phone: it is given a Host, which adds to that of the map what the gifts need (a touch that lasts, the file of
 *  the memory of the day, the day and the package of the game).  run_gifts_checks() holds all of it, in every build, to
 *  tests/fixtures/gifts_golden.json.qz that Mobile/tools/make_gifts_golden.py made with the Python code: the same pictures and readings in, and the
 *  same taps, swipes, log lines, sleeps, saved pictures and writes of the memory out, in the same order and at the same moments of a fake clock, with
 *  the same things remembered afterwards.
 *
 *  Where it differs from the Python code (the stories leave these out):
 *  - a memory of the day that is no JSON object, or that has other keys than the five of the code, is taken as damaged and a new day is begun (Python
 *    stops with an AttributeError or a KeyError, and the bot goes on with the next thing); the keys that the code does not know are not written back.
 *  - a picture that has no rows left where the code looks (smaller than 150 rows, or find_pill_button() from a row past the end) is read as 'nothing
 *    found' (Python stops with a cv2.error).
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoGifts_H
#define PokemonAutomation_ClaudeGG_PokemonGoGifts_H

#include <optional>
#include <vector>
#include <opencv2/core.hpp>
#include <QByteArray>
#include <QJsonObject>
#include <QString>
#include <QStringList>
#include "ClaudeGG_PokemonGoMap.h"
#include "ClaudeGG_PokemonGoNav.h"
#include "ClaudeGG_PokemonGoStart.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Gifts{

using Loop::Point;


//  ---- the numbers of the gifts (canvas of 1768 x 2208)

inline constexpr int CANVAS_H = 2208;                   //  S.REF_H: the height of the canvas that all the places are written for
inline constexpr Point AVATAR{150, 1990};               //  the avatar of the trainer, bottom left on the map
inline constexpr Point FRIENDS_TAB{884, 230};           //  the FRIENDS tab at the top of the profile
inline constexpr Point SEND_BTN{860, 1812};             //  SEND, right below ADD STICKER
inline constexpr Point OPEN_BTN{860, 1815};             //  OPEN on the screen of a gift that was received
inline constexpr Point CENTER{884, 1104};               //  S.CENTER: the middle of the screen
inline constexpr Point GIFT_SPOTS[3] = {{340, 900}, {370, 640}, {340, 1150}};     //  the first gift of 'Which Gift do you want to send?': postcard, bow, place name
inline constexpr int GIFT_PRESS_MS = 200;               //  the touch on a gift lasts this long
inline constexpr int PROFILE_LOOKS = 10;                //  the profile is scrolled this many times to find the label
inline constexpr int ROUND_LOOKS = 60;                  //  the friend list is looked at this many times at the most


//  ---- the friends

struct Friend{
    QString name;
    int x = 0;                                          //  where the name is (what is tapped to open the friend)
    int y = 0;
    bool gift = false;                                  //  a gift waits
    bool arrow = false;                                 //  a gift of you is on its way
};

//  A button that was found: where to tap, and how many pixels the pill had (nothing: it is a place that is known and not found).
struct Button{
    int x = 0;
    int y = 0;
    std::optional<int> area;
};

//  gamebot.gift_state: what was done today.
struct State{
    QString day;                                        //  'yyyy-MM-dd'
    QStringList sent;
    QStringList opened;
    bool open_blocked = false;                          //  the limit of gifts or a full bag: no opening any more today
    bool send_blocked = false;                          //  no gifts left to send today
};
QJsonObject state_json(const State& state);


//  ---- the phone, the person and the files

//  (virtual: the real host of the bot is also a Catch::Host and so on, and all of them are one Map::Host.)
class Host : public virtual Map::Host{
public:
    //  S.tap(x, y, ms): a touch that lasts ms milliseconds (tap() is the short one).
    virtual void tap_press(int x, int y, int ms) = 0;
    //  S.PACKAGE: the package of the game on the phone.
    virtual QString package() = 0;
    //  time.strftime("%Y-%m-%d"): today.
    virtual QString today() = 0;
    //  What is in the file of the memory of the day (its name only: it is in the home folder); nothing when there is no such file.
    virtual std::optional<QByteArray> gift_state_read(const QString& file) = 0;
    //  Writes that file.
    virtual void gift_state_write(const QString& file, const QByteArray& json) = 0;
};


//  ---- the readers

//  The grey circle with the arrow at the bottom right of the avatar of the friend whose name is at y.
bool sent_arrow(const cv::Mat& img, int y);
//  The pink bow of a gift in the icon column of the rows y0 to y1.
bool gift_icon(const cv::Mat& img, int y0, int y1);
//  The rows of the friend list (img: nothing: the text only).
std::vector<Friend> parse_friends(const Nav::Lines& lines, const cv::Mat* img);
//  (The green pill button, OPEN or SEND, is found by Start::find_pill_button(): it is shared with the start of the game.)
//  The big pink bow of the present at the top of a screen of a gift.
bool is_gift_screen(const cv::Mat& img);
//  Is ADD STICKER on the screen (the strip under the middle of it is read)?
bool has_sticker_button(Loop::Host& host, const cv::Mat& img);
//  SEND on the screen to send a gift: below ADD STICKER when that is there, else the green pill button.
std::optional<Button> send_button(Loop::Host& host, const cv::Mat& img);
//  Is it the friend list (the strip at the top says FRIENDS and SOCIAL, ME or PARTY)?
bool is_friend_list(Loop::Host& host, const cv::Mat& img);
//  Is there a line that holds all of the words?
bool any_text(const Nav::Lines& lines, const QStringList& needles);


//  ---- the memory of the day

//  The name of the file for the game that is on the phone ('gifts_state.json' for the Play Store version, 'gifts_state_<last word of the package>.json').
QString state_file(Host& host);
//  What was done today: a new day when there is no file, it cannot be read or it is of another day.
State load_gift_state(Host& host);
void save_gift_state(Host& host, const State& state);


//  ---- the visits

//  BACK up to three times until the friend list is on the screen again.
bool back_to_list(Host& host);
//  Tap a friend, open the gift that waits (when wanted), send a gift (when wanted), write the memory and go back to the list.
void visit_friend(Host& host, const Friend& f, bool want_open, bool want_send, State& state);
//  The whole round: map, avatar, FRIENDS, the list from top to bottom, and back to the map.
void gifts_round(Host& host);

//  Plays the stories of tests/fixtures/gifts_golden.json.qz (what the Python code did) on the port and says in `report` what went another way.
//  Returns how many stories went another way.
int run_gifts_checks(const QString& golden, QStringList& report, bool stop_at_first = false);


}
}
}
}

#endif
