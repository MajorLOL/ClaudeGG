/*  Claude GG Pokemon GO Nav (the screens of GO Battle League, read from text)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port to C++ of Mobile/battle_nav.py, the first of the screen readers of
 *  the Pokémon GO bot (issue #30): OCR lines in, decisions out. Which screen is
 *  this (the map, the main menu, the Battle screen, the party screen, a
 *  question in a fight), where to tap, what a question or a result says. It
 *  does not touch the phone and does not read a picture: the lines come from
 *  an OCR of the screenshot (the bot reads them with Tesseract), as a list of
 *  lines of words with the position of each in pixels of the full screen.
 *  "k" is the height of the screen divided by 2208 (the inner display of a
 *  Galaxy Z Fold3, which the positions were measured on).
 *
 *  What the functions answer is what battle_nav.py answers, to the letter:
 *  Mobile/tools/make_nav_golden.py makes a file with its answers for 109 screens
 *  (real ones, and ones that OCR has misread) and run_nav_checks() holds this
 *  port to it in every build (--mobile-test). Change battle_nav.py and the
 *  test of Python says the file is old; make it again, and the test of this
 *  port says what is different.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoNav_H
#define PokemonAutomation_ClaudeGG_PokemonGoNav_H

#include <utility>
#include <vector>
#include <QString>
#include <QStringList>

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Nav{


//  What OCR read: words with the place of each, and the line that they are in.
struct Word{
    QString text;
    int x = 0;
    int y = 0;
};
struct Line{
    QString text;
    int x = 0;
    int y = 0;
    std::vector<Word> words;
};
typedef std::vector<Line> Lines;
typedef std::pair<int, int> Spot;


//  difflib.SequenceMatcher(None, word, target).ratio() >= threshold: a word that is misread a little.
double similarity(const QString& a, const QString& b);
bool like(const QString& word, const QString& target, double threshold = 0.8);

//  A word in plain capitals without accents or punctuation ("POKÉMON?" is "POKEMON").
QString plain(const QString& word);
QString reads(const Lines& lines, int count = 150);

//  The words of a league name ("Great League" is GREAT LEAGUE).
QStringList league_words(const QString& league);
struct LeagueLine{
    QString text;
    int x = 0;
    int y = 0;
};
//  The lines that show the league name, best first.
std::vector<LeagueLine> league_lines(const Lines& lines, const QString& league, double threshold = 0.8);
//  The leagues on the league list, top to bottom: (title, max CP).
std::vector<std::pair<QString, int>> read_leagues(const Lines& lines, int width = 1768);

//  What is on the screen: "map", "party", "welcome", "home", "menu", "exit", "exit_battle", "league"
//  or "other" (see battle_nav.py).
QString screen_kind(const Lines& lines, bool on_map = false, const QString& league = QString(), double k = 1.0);

std::vector<Spot> menu_battle_spots(const Lines& lines, double k = 1.0);
std::vector<Spot> home_battle_spots(const Lines& lines, double k = 1.0);
//  Where the BATTLE button of the Battle screen is when it is not found (battle_nav.HOME_BUTTON_FALLBACK, on the 2208 high screen);
//  home_battle_spots() ends with these, in this order.
inline constexpr size_t HOME_BUTTON_FALLBACKS = 2;
Spot home_button_fallback(size_t index);
bool max_battles_today(const Lines& lines);
std::vector<Spot> collect_spots(const Lines& lines, int height);
QString claim_label(const Lines& lines, double k = 1.0);
struct NextWord{
    QString text;
    int x = 0;
    int y = 0;
};
std::vector<NextWord> next_words(const Lines& lines, double k = 1.0);
bool keep_off_label(const QString& text);
bool go_on_label(const QString& text);
QStringList danger_words(const Lines& lines);
bool premium_above(const Lines& lines, double y);       //  (y is a fraction of a height in pixels: a number with decimals)
bool battle_words(const Lines& lines);
struct ExitSpots{
    Spot yes;
    bool has_no = false;
    Spot no;
};
ExitSpots exit_battle_spots(const Lines& lines, double k = 1.0);
QString party_title(const Lines& lines, double k = 1.0);
QStringList party_members(const Lines& lines, const QStringList& names);

//  The fight: the question in the middle ("shield", "noshield", "switch" or ""), the name boxes, the
//  tiles of the pop-up, the move names, the result ("win", "loss" or "").
QString question_kind(const Lines& lines);
struct NameBox{
    QString name;
    bool has_cp = false;
    int cp = 0;
};
NameBox name_box(const Lines& lines);
std::vector<std::pair<int, int>> popup_tiles(const Lines& lines);
std::pair<QString, QString> button_texts(const Lines& lines, int width);
QString result_kind(const Lines& lines);
QString result_word(const QString& text);
std::vector<Spot> party_use_spots(const Lines& lines, double k = 1.0);


//  The checks against the file of answers of battle_nav.py ("golden": its path). One line in "report" for each
//  that went wrong and one that counts; returns how many went wrong (1 when the file is not there or not right).
int run_nav_checks(const QString& golden, QStringList& report);


}
}
}
}
#endif
