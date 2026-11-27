/*  Claude GG Pokemon GO Nav (the screens of GO Battle League, read from text)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <algorithm>
#include <array>
#include <cmath>
#include <QFile>
#include <QHash>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include "ClaudeGG_PokemonGoNav.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Nav{


namespace{

//  The numbers of battle_nav.py, measured on the inner display of a Galaxy Z Fold3 (1768 x 2208).
const int SCREEN_H = 2208;
const int ICON_DY = 195;
const int HOME_BUTTON_Y = 1700;
const Spot HOME_BUTTON_FALLBACK[] = {{650, 2165}, {1120, 2165}};
const int YES_ABOVE_NO = 290;
const int YES_BELOW_TITLE = 310;
const Spot EXIT_YES_FALLBACK = {884, 1110};
const Spot PARTY_BUTTON_FALLBACK = {884, 1930};
const char* const MENU_WORDS[] = {"SETTINGS", "POKEDEX", "BATTLE", "SHOP", "POKEMON", "ITEMS"};
const char* const CLAIM_WORDS[] = {"CLAIM", "COLLECT"};
const char* const NEXT_WORDS[] = {"CLAIM", "COLLECT", "CONTINUE", "OK", "OKAY", "NEXT", "DONE", "CLOSE"};
const char* const GO_ON_LABELS[] = {"LETSGO", "OK", "OKAY", "CONTINUE", "NEXT", "CLAIM", "COLLECT", "DONE", "CLOSE", "GOTIT"};
const char* const DANGER_WORDS[] = {
    "SHOP", "BUY", "COIN", "POKECOIN", "PURCHASE", "PREMIUM", "PASS", "EXCHANGE", "TRANSFER", "DELETE",
    "EXIT", "QUIT", "LEAVE", "REMOVE", "SHARE", "DISCARD",
};
const char* const KEEP_OFF_LABELS[] = {
    "PARTY", "USE", "YES", "JOIN", "BUY", "SHOP", "COIN", "SHARE", "EXCHANGE", "PREMIUM", "PASS",
    "PURCHASE", "TRANSFER", "EXIT", "QUIT", "LEAVE",
};

//  Python's int(): towards zero.
int truncated(double value){
    return static_cast<int>(value);
}
//  Python's //, for numbers that may be below zero.
int floor_div(int a, int b){
    int q = a / b;
    if ((a % b != 0) && ((a < 0) != (b < 0))){
        q--;
    }
    return q;
}

std::vector<Word> words_of(const Lines& lines){
    std::vector<Word> out;
    for (const Line& line : lines){
        for (const Word& word : line.words){
            out.push_back(word);
        }
    }
    return out;
}

QString text_of(const Lines& lines){
    QStringList parts;
    for (const Line& line : lines){
        parts << line.text;
    }
    return parts.join(' ');
}

//  Python's str.split() with no argument.
QStringList py_split(const QString& text){
    return text.split(QRegularExpression("\\s+"), Qt::SkipEmptyParts);
}

//  " ".join(text.split()): the white space as one space.
QString collapsed(const QString& text){
    return py_split(text).join(' ');
}

//  Python's str.title().
QString py_title(const QString& text){
    QString out = text;
    bool in_word = false;
    for (qsizetype c = 0; c < out.size(); c++){
        const QChar ch = out[c];
        if (ch.isLetter()){
            out[c] = in_word ? ch.toLower() : ch.toUpper();
            in_word = true;
        }else{
            in_word = false;
        }
    }
    return out;
}

//  re.sub(r"[^A-Z0-9 ]+", " ", text.upper()).split()
QStringList norm(const QString& text){
    static const QRegularExpression other("[^A-Z0-9 ]+");
    QString upper = text.toUpper();
    upper.replace(other, " ");
    return py_split(upper);
}

bool phrase(const Lines& lines, const QString& wanted, double threshold = 0.8){
    const QStringList want = py_split(wanted);
    for (const Line& line : lines){
        const qsizetype have = (qsizetype)line.words.size();
        for (qsizetype i = 0; i + want.size() <= have; i++){
            bool all = true;
            for (qsizetype j = 0; j < want.size(); j++){
                if (!like(line.words[(size_t)(i + j)].text, want[j], threshold)){
                    all = false;
                    break;
                }
            }
            if (all){
                return true;
            }
        }
    }
    return false;
}

//  One OCR line has these letters one after the other, spaces and signs left out.
bool glued(const Lines& lines, const QString& letters){
    static const QRegularExpression other("[^A-Z]");
    for (const Line& line : lines){
        QString only = line.text.toUpper();
        only.remove(other);
        if (only.contains(letters)){
            return true;
        }
    }
    return false;
}

bool has(const Lines& lines, const QString& word, double threshold = 0.8){
    for (const Word& w : words_of(lines)){
        if (like(w.text, word, threshold)){
            return true;
        }
    }
    return false;
}

bool contains_text(const char* const* list, size_t count, const QString& what){
    for (size_t c = 0; c < count; c++){
        if (what == QLatin1String(list[c])){
            return true;
        }
    }
    return false;
}
#define COUNT_OF(list) (sizeof(list) / sizeof(list[0]))

}   //  namespace



//  ---------------------------------------------------------------------
//  difflib
//  ---------------------------------------------------------------------

//  The longest block that a and b have in common inside the ranges: the first one in a, and in b, when
//  there are several (find_longest_match of difflib, with no junk).
static void longest_match(
    const QString& a, const QString& b,
    int alo, int ahi, int blo, int bhi,
    int& besti, int& bestj, int& bestsize
){
    besti = alo;
    bestj = blo;
    bestsize = 0;
    std::vector<int> previous((size_t)b.size() + 1, 0);
    std::vector<int> current((size_t)b.size() + 1, 0);
    for (int i = alo; i < ahi; i++){
        std::fill(current.begin(), current.end(), 0);
        for (int j = blo; j < bhi; j++){
            if (a[i] != b[j]){
                continue;
            }
            const int k = previous[(size_t)j] + 1;      //  (previous[j] is the block that ended at j - 1)
            current[(size_t)j + 1] = k;
            if (k > bestsize){
                besti = i - k + 1;
                bestj = j - k + 1;
                bestsize = k;
            }
        }
        previous.swap(current);
    }
}

double similarity(const QString& a, const QString& b){
    const int length = (int)(a.size() + b.size());
    if (length == 0){
        return 1.0;
    }
    int matches = 0;
    std::vector<std::array<int, 4>> queue;
    queue.push_back({0, (int)a.size(), 0, (int)b.size()});
    while (!queue.empty()){
        const std::array<int, 4> range = queue.back();
        queue.pop_back();
        int i, j, k;
        longest_match(a, b, range[0], range[1], range[2], range[3], i, j, k);
        if (k > 0){
            matches += k;
            if (range[0] < i && range[2] < j){
                queue.push_back({range[0], i, range[2], j});
            }
            if (i + k < range[1] && j + k < range[3]){
                queue.push_back({i + k, range[1], j + k, range[3]});
            }
        }
    }
    return 2.0 * matches / length;
}

bool like(const QString& word, const QString& target, double threshold){
    return similarity(word, target) >= threshold;
}


//  ---------------------------------------------------------------------
//  Words
//  ---------------------------------------------------------------------

QString plain(const QString& word){
    static const QRegularExpression other("[^A-Z0-9]+");
    const QString decomposed = word.normalized(QString::NormalizationForm_KD);
    QString kept;
    for (const QChar ch : decomposed){
        if (QChar::combiningClass(ch.unicode()) == 0){
            kept += ch;
        }
    }
    kept = kept.toUpper();
    kept.remove(other);
    return kept;
}

QString reads(const Lines& lines, int count){
    QStringList seen;
    for (const Word& word : words_of(lines)){
        if (!seen.contains(word.text)){
            seen << word.text;
        }
    }
    const QString joined = seen.join(' ').left(count);
    return joined.isEmpty() ? QString("nothing") : joined;
}

QStringList league_words(const QString& league){
    QStringList out;
    for (const QString& word : norm(league)){
        if (word.size() > 1){
            out << word;
        }
    }
    return out;
}

std::vector<LeagueLine> league_lines(const Lines& lines, const QString& league, double threshold){
    std::vector<LeagueLine> out;
    const QStringList want = league_words(league);
    if (want.isEmpty()){
        return out;
    }
    for (const Line& line : lines){
        bool all = true;
        for (const QString& w : want){
            bool found = false;
            for (const Word& h : line.words){
                if (like(h.text, w, threshold)){
                    found = true;
                    break;
                }
            }
            if (!found){
                all = false;
                break;
            }
        }
        if (all && !line.words.empty()){
            int sum = 0;
            for (const Word& word : line.words){
                sum += word.x;
            }
            out.push_back({line.text, floor_div(sum, (int)line.words.size()), line.y});
        }
    }
    return out;
}

std::vector<std::pair<QString, int>> read_leagues(const Lines& lines, int width){
    static const QRegularExpression skip("CHOOSE YOUR LEAGUE|SEE WHAT|COMING NEXT");
    static const QRegularExpression max_cp("MAX\\s*C\\s*P");
    static const QRegularExpression number("(\\d)[.,\\s]?(\\d{3})");
    std::vector<std::pair<QString, int>> out;
    QStringList title;
    Lines sorted = lines;
    std::stable_sort(sorted.begin(), sorted.end(), [](const Line& a, const Line& b){
        return a.y < b.y;
    });
    for (const Line& line : sorted){
        if (collapsed(line.text).contains(skip)){
            continue;
        }
        QString u;
        if (!line.words.empty()){
            QStringList keep;
            for (const Word& word : line.words){
                if (word.x >= width * 0.42){
                    keep << word.text;
                }
            }
            if (keep.isEmpty()){
                continue;
            }
            u = collapsed(keep.join(' '));
        }else if (line.x < width * 0.42){
            continue;
        }else{
            u = collapsed(line.text);
        }
        if (u.contains(max_cp)){
            int cap = 0;
            if (u.contains("NO LIMIT") || u.contains("UNLIMITED")){
                cap = 10000;
            }else{
                const QRegularExpressionMatch m = number.match(u);
                if (m.hasMatch()){
                    cap = (m.captured(1) + m.captured(2)).toInt();
                }
            }
            if (!title.isEmpty() && cap != 0){
                QString name = py_title(title.join(' '));
                name.replace("Go ", "GO ");
                name.replace("Laic", "LAIC");
                out.emplace_back(name, cap);
            }
            title.clear();
        }else if (!u.isEmpty() && !u.contains(skip)){
            title << u;
        }
    }
    return out;
}


//  ---------------------------------------------------------------------
//  Which screen
//  ---------------------------------------------------------------------

QString screen_kind(const Lines& lines, bool on_map, const QString& league, double k){
    if (on_map){
        return "map";
    }
    if (phrase(lines, "USE THIS PARTY") || phrase(lines, "CHOOSE YOUR PARTY") || glued(lines, "CHOOSEYOURPARTY")
        || glued(lines, "USETHISPARTY") || glued(lines, "RECOMMENDEDBATTLEPARTY")
    ){
        return "party";
    }
    if ((has(lines, "WELCOME") && has(lines, "BATTLE")) || phrase(lines, "RISE THROUGH THE RANKS", 0.75)){
        return "welcome";
    }
    if (phrase(lines, "GO BATTLE LEAGUE") ||
        (has(lines, "LONGEST") && has(lines, "STREAK")) ||
        (has(lines, "STARDUST") && has(lines, "EARNED")) ||
        (phrase(lines, "REWARD TIER") || phrase(lines, "BASIC REWARDS") || phrase(lines, "PREMIUM REWARDS"))
    ){
        return "home";
    }
    const std::vector<Word> ws = words_of(lines);
    for (const Word& w : ws){
        if (like(w.text, "ITEMS", 0.8) && 1250 * k < w.y && w.y < 1700 * k && w.x > 884 * k){
            for (const Word& other : ws){
                if (like(other.text, "POKEMON", 0.8) && std::abs(other.y - w.y) < 80 * k && other.x < 884 * k){
                    return "menu";
                }
            }
        }
    }
    int menu_words = 0;
    for (const char* menu : MENU_WORDS){
        for (const Word& w : ws){
            if (like(w.text, menu, 0.8)){
                menu_words++;
                break;
            }
        }
    }
    if (menu_words >= 4){
        return "menu";
    }
    const QString text = text_of(lines);
    if (text.contains("EXIT") && text.contains("TRAINER BATTLE")){
        return "exit_battle";
    }
    if (text.contains("EXIT") && (text.contains("CANCEL") || text.contains("POK"))){
        return "exit";
    }
    if (phrase(lines, "CHOOSE YOUR LEAGUE") || (!league.isEmpty() && !league_lines(lines, league).empty())){
        return "league";
    }
    return "other";
}


//  ---------------------------------------------------------------------
//  Where to tap
//  ---------------------------------------------------------------------

std::vector<Spot> menu_battle_spots(const Lines& lines, double k){
    std::vector<Spot> found;
    for (const Word& w : words_of(lines)){
        if (like(w.text, "BATTLE", 0.8) && w.x > 884 * k && 450 * k < w.y && w.y < 1250 * k){
            found.emplace_back(w.x, w.y);
        }
    }
    if (found.empty()){
        return {};
    }
    std::stable_sort(found.begin(), found.end(), [](const Spot& a, const Spot& b){
        return -a.first < -b.first;
    });
    const int x = found[0].first;
    const int y = found[0].second;
    return {{x, y + truncated(ICON_DY * k)}, {x, y}, {x, y + truncated((ICON_DY - 45) * k)}};
}

std::vector<Spot> home_battle_spots(const Lines& lines, double k){
    std::vector<Spot> found;
    for (const Word& w : words_of(lines)){
        if (like(w.text, "BATTLE", 0.8) && w.y > HOME_BUTTON_Y * k){
            found.emplace_back(w.x, w.y);
        }
    }
    std::stable_sort(found.begin(), found.end(), [](const Spot& a, const Spot& b){
        return -a.second < -b.second;
    });
    std::vector<Spot> spots;
    if (!found.empty()){
        const int x = found[0].first;
        const int y = found[0].second;
        spots.emplace_back(x, y);
        spots.emplace_back(x, y - truncated(45 * k));
    }
    for (const Spot& fallback : HOME_BUTTON_FALLBACK){
        spots.emplace_back(truncated(fallback.first * k), truncated(fallback.second * k));
    }
    return spots;
}

Spot home_button_fallback(size_t index){
    return HOME_BUTTON_FALLBACK[index];
}

bool max_battles_today(const Lines& lines){
    QStringList words;
    for (const Word& w : words_of(lines)){
        words << plain(w.text);
    }
    auto any = [&](const char* target, double threshold){
        for (const QString& w : words){
            if (like(w, target, threshold)){
                return true;
            }
        }
        return false;
    };
    return any("MAXIMUM", 0.8) && any("BATTLES", 0.8) && any("TODAY", 0.75);
}

std::vector<Spot> collect_spots(const Lines& lines, int height){
    std::vector<Spot> out;
    for (const Word& w : words_of(lines)){
        if (w.y > 0.75 * height && like(plain(w.text), "COLLECT", 0.8)){
            out.emplace_back(w.x, truncated(w.y - 0.035 * height));
        }
    }
    std::sort(out.begin(), out.end());
    return out;
}

QString claim_label(const Lines& lines, double k){
    for (const Line& line : lines){
        if (line.y > HOME_BUTTON_Y * k){
            for (const Word& w : line.words){
                for (const char* claim : CLAIM_WORDS){
                    if (like(plain(w.text), claim, 0.8)){
                        return line.text;
                    }
                }
            }
        }
    }
    return QString();
}

std::vector<NextWord> next_words(const Lines& lines, double k){
    std::vector<NextWord> out;
    for (const Word& w : words_of(lines)){
        if (w.y <= SCREEN_H * k / 3.0){
            continue;
        }
        const QString p = plain(w.text);
        bool match = false;
        for (const char* next : NEXT_WORDS){
            const QString n = QString::fromLatin1(next);
            if (p == n || (n.size() > 3 && like(p, n, 0.85))){
                match = true;
                break;
            }
        }
        if (match){
            out.push_back({w.text, w.x, w.y});
        }
    }
    std::stable_sort(out.begin(), out.end(), [](const NextWord& a, const NextWord& b){
        return -a.y < -b.y;
    });
    return out;
}

bool keep_off_label(const QString& text){
    for (const QString& word : py_split(text)){
        const QString p = plain(word);
        if (p.isEmpty()){
            continue;
        }
        for (const char* keep : KEEP_OFF_LABELS){
            if (p.startsWith(QLatin1String(keep))){
                return true;
            }
        }
    }
    return false;
}

bool go_on_label(const QString& text){
    const QString p = plain(text);
    if (p.isEmpty()){
        return false;
    }
    for (const char* label : GO_ON_LABELS){
        const QString g = QString::fromLatin1(label);
        if (p == g || (g.size() >= 4 && (p.contains(g) || like(p, g, 0.8)))){
            return true;
        }
    }
    return false;
}

QStringList danger_words(const Lines& lines){
    QStringList out;
    for (const Word& w : words_of(lines)){
        const QString p = plain(w.text);
        bool danger = false;
        for (const char* d : DANGER_WORDS){
            if (p.startsWith(QLatin1String(d))){
                danger = true;
                break;
            }
        }
        if (danger && !out.contains(p)){
            out << p;
        }
    }
    return out;
}

bool premium_above(const Lines& lines, double y){
    for (const Word& w : words_of(lines)){
        if (like(plain(w.text), "PREMIUM", 0.8) && w.y < y){
            return true;
        }
    }
    return false;
}

bool battle_words(const Lines& lines){
    for (const Word& w : words_of(lines)){
        const QString p = plain(w.text);
        if (p == "LEAGUE" || p == "PARTY" || p == "REWARDS" || p == "REWARD" || p == "RANK" || p == "BATTLE"){
            return true;
        }
    }
    return false;
}

ExitSpots exit_battle_spots(const Lines& lines, double k){
    ExitSpots out;
    for (const Word& w : words_of(lines)){
        if (w.text == "NO" && w.y > 900 * k){
            out.has_no = true;
            out.no = {w.x, w.y};
            break;
        }
    }
    bool has_title = false;
    int title = 0;
    for (const Line& line : lines){
        if (line.text.contains("EXIT") && line.text.contains("TRAINER")){
            has_title = true;
            title = line.y;
            break;
        }
    }
    if (out.has_no){
        out.yes = {out.no.first, out.no.second - truncated(YES_ABOVE_NO * k)};
    }else if (has_title && title != 0){            //  (Python: "elif title" is false for 0)
        out.yes = {truncated(EXIT_YES_FALLBACK.first * k), title + truncated(YES_BELOW_TITLE * k)};
    }else{
        out.yes = {truncated(EXIT_YES_FALLBACK.first * k), truncated(EXIT_YES_FALLBACK.second * k)};
    }
    return out;
}

QString party_title(const Lines& lines, double k){
    (void)k;
    for (size_t i = 0; i < lines.size(); i++){
        if (lines[i].text.contains("MAX CP") && i > 0){
            return lines[i - 1].text;
        }
    }
    return QString();
}

QStringList party_members(const Lines& lines, const QStringList& names){
    const QString text = norm(text_of(lines)).join(' ');
    QStringList out;
    for (const QString& n : names){
        const QString key = norm(n).join(' ');
        if (key.isEmpty()){
            continue;
        }
        bool found = text.contains(key);
        if (!found){
            for (const QString& w : py_split(text)){
                if (like(w, key, 0.8)){
                    found = true;
                    break;
                }
            }
        }
        if (found){
            out << n;
        }
    }
    return out;
}


//  ---------------------------------------------------------------------
//  The fight
//  ---------------------------------------------------------------------

namespace{

QStringList plain_words(const Lines& lines){
    QStringList out;
    for (const Word& w : words_of(lines)){
        const QString p = plain(w.text);
        if (!p.isEmpty()){
            out << p;
        }
    }
    return out;
}

}

QString question_kind(const Lines& lines){
    const QStringList words = plain_words(lines);
    for (const QString& w : words){
        if (like(w, "SWITCH", 0.8)){
            return "switch";
        }
    }
    for (const QString& w : words){
        if (like(w, "REMAINING", 0.75) || w == "SHIELDS"){
            return "noshield";
        }
    }
    for (const QString& w : words){
        if (like(w, "INCOMING", 0.75) || w == "SHIELD" || w == "ATTACK" || w == "USE"){
            return "shield";
        }
    }
    return QString();
}

NameBox name_box(const Lines& lines){
    static const QRegularExpression with_cp("^CP(\\d{3,4})$");
    static const QRegularExpression number("^\\d{3,4}$");
    NameBox out;
    QStringList name;
    for (const Word& w : words_of(lines)){
        const QString p = plain(w.text);
        const QRegularExpressionMatch m = with_cp.match(p);
        if (m.hasMatch()){
            out.has_cp = true;
            out.cp = m.captured(1).toInt();
        }else if (p == "CP"){
            continue;
        }else if (number.match(p).hasMatch()){
            if (!out.has_cp || out.cp == 0){          //  (Python: "cp or int(plain)")
                out.has_cp = true;
                out.cp = p.toInt();
            }
        }else if (p.size() >= 3){
            bool letters = true;
            for (const QChar ch : p){
                if (ch < 'A' || ch > 'Z'){
                    letters = false;
                    break;
                }
            }
            if (letters){
                name << py_title(p);
            }
        }
    }
    out.name = name.join(' ');
    return out;
}

std::vector<std::pair<int, int>> popup_tiles(const Lines& lines){
    static const QRegularExpression tile("^[A-Z]{0,4}(\\d{3,4})$");
    std::vector<std::pair<int, int>> out;
    for (const Word& w : words_of(lines)){
        const QRegularExpressionMatch m = tile.match(plain(w.text));
        if (m.hasMatch()){
            out.emplace_back(m.captured(1).toInt(), w.x);
        }
    }
    std::stable_sort(out.begin(), out.end(), [](const std::pair<int, int>& a, const std::pair<int, int>& b){
        return a.second < b.second;
    });
    return out;
}

std::pair<QString, QString> button_texts(const Lines& lines, int width){
    std::vector<Word> words = words_of(lines);
    std::stable_sort(words.begin(), words.end(), [](const Word& a, const Word& b){
        return a.x < b.x;
    });
    QStringList left, right;
    for (const Word& w : words){
        ((double)w.x < width / 2.0 ? left : right) << w.text;
    }
    return {left.join(' '), right.join(' ')};
}

QString result_kind(const Lines& lines){
    const QStringList words = plain_words(lines);
    bool effort = false;
    bool victory = false;
    bool winner = false;
    for (const QString& w : words){
        effort |= like(w, "EFFORT", 0.8);
        victory |= like(w, "VICTORY", 0.8);
        winner |= like(w, "WINNER", 0.8);
    }
    if (effort || (words.contains("GOOD") && !victory)){
        return "loss";
    }
    if (victory || winner){
        return "win";
    }
    for (const Line& line : lines){
        QStringList ws;
        for (const Word& w : line.words){
            const QString p = plain(w.text);
            if (!p.isEmpty()){
                ws << p;
            }
        }
        for (qsizetype i = 0; i < ws.size(); i++){
            const QString& w = ws[i];
            if (w == "YOUWIN" || w == "YOUWINS"){
                return "win";
            }
            if (w == "YOU"){
                QString after;
                for (qsizetype j = i + 1; j < ws.size() && j < i + 3; j++){
                    after += ws[j];
                }
                after = after.left(3);
                if (after == "WIN" || after == "W1N" || after == "WLN"){
                    return "win";
                }
            }
        }
    }
    return QString();
}

QString result_word(const QString& text){
    QStringList words;
    for (const QString& w : py_split(text)){
        const QString p = plain(w);
        if (!p.isEmpty()){
            words << p;
        }
    }
    const QString joined = words.join(QString());
    bool effort = false;
    for (const QString& w : words){
        effort |= like(w, "EFFORT", 0.75);
    }
    if (joined.contains("EFFORT") || effort || (words.contains("GOOD") && !joined.contains("WIN"))){
        return "loss";
    }
    if (joined.contains("YOUWIN") || words.contains("WIN") || words.contains("WINS")){
        return "win";
    }
    return QString();
}

std::vector<Spot> party_use_spots(const Lines& lines, double k){
    std::vector<int> ys;
    for (const Line& line : lines){
        Lines one;
        Line single = line;
        single.x = 0;
        one.push_back(single);
        if (phrase(one, "USE THIS PARTY", 0.7)){
            ys.push_back(line.y);
        }
    }
    for (const Line& line : lines){
        if (line.text.contains("THIS PARTY") && !line.text.contains("CHOOSE")){
            ys.push_back(line.y);
        }
    }
    std::vector<Spot> spots;
    if (!ys.empty()){
        spots.emplace_back(truncated(PARTY_BUTTON_FALLBACK.first * k), *std::max_element(ys.begin(), ys.end()));
    }
    spots.emplace_back(truncated(PARTY_BUTTON_FALLBACK.first * k), truncated(PARTY_BUTTON_FALLBACK.second * k));
    return spots;
}


//  ---------------------------------------------------------------------
//  The test: the answers of battle_nav.py
//  ---------------------------------------------------------------------

namespace{

Lines lines_of(const QJsonArray& array){
    Lines out;
    for (const QJsonValue& value : array){
        const QJsonArray line = value.toArray();
        Line item;
        item.text = line.at(0).toString();
        item.x = line.at(1).toInt();
        item.y = line.at(2).toInt();
        for (const QJsonValue& w : line.at(3).toArray()){
            const QJsonArray word = w.toArray();
            item.words.push_back({word.at(0).toString(), word.at(1).toInt(), word.at(2).toInt()});
        }
        out.push_back(item);
    }
    return out;
}

QJsonArray spot_json(const Spot& spot){
    return QJsonArray{spot.first, spot.second};
}
QJsonArray spots_json(const std::vector<Spot>& spots){
    QJsonArray out;
    for (const Spot& spot : spots){
        out.append(spot_json(spot));
    }
    return out;
}
QJsonArray strings_json(const QStringList& list){
    QJsonArray out;
    for (const QString& s : list){
        out.append(s);
    }
    return out;
}

//  What the port answers for one case of the file, as the file has it; "known" is false for a function
//  that this port has not got.
QJsonValue answer(const QString& fn, const QJsonObject& c, const Lines& lines, bool& known){
    known = true;
    const double k = c.contains("k") ? c.value("k").toDouble() : 1.0;
    const QString league = c.value("league").toString();
    const QString text = c.value("text").toString();
    if (fn == "like"){
        return like(c.value("word").toString(), c.value("target").toString(), c.value("th").toDouble());
    }
    if (fn == "plain"){
        return plain(text);
    }
    if (fn == "league_words"){
        return strings_json(league_words(text));
    }
    if (fn == "keep_off_label"){
        return keep_off_label(text);
    }
    if (fn == "go_on_label"){
        return go_on_label(text);
    }
    if (fn == "result_word"){
        return result_word(text);
    }
    if (fn == "reads"){
        return reads(lines, c.value("n").toInt());
    }
    if (fn == "screen_kind"){
        return screen_kind(lines, c.value("on_map").toBool(), league, k);
    }
    if (fn == "league_lines"){
        QJsonArray out;
        for (const LeagueLine& line : league_lines(lines, league)){
            out.append(QJsonArray{line.text, line.x, line.y});
        }
        return out;
    }
    if (fn == "read_leagues"){
        QJsonArray out;
        for (const std::pair<QString, int>& league_cap : read_leagues(lines, c.value("width").toInt())){
            out.append(QJsonArray{league_cap.first, league_cap.second});
        }
        return out;
    }
    if (fn == "menu_battle_spots"){
        return spots_json(menu_battle_spots(lines, k));
    }
    if (fn == "home_battle_spots"){
        return spots_json(home_battle_spots(lines, k));
    }
    if (fn == "max_battles_today"){
        return max_battles_today(lines);
    }
    if (fn == "collect_spots"){
        return spots_json(collect_spots(lines, c.value("height").toInt()));
    }
    if (fn == "claim_label"){
        return claim_label(lines, k);
    }
    if (fn == "next_words"){
        QJsonArray out;
        for (const NextWord& word : next_words(lines, k)){
            out.append(QJsonArray{word.text, word.x, word.y});
        }
        return out;
    }
    if (fn == "danger_words"){
        return strings_json(danger_words(lines));
    }
    if (fn == "premium_above"){
        return premium_above(lines, c.value("y").toInt());
    }
    if (fn == "battle_words"){
        return battle_words(lines);
    }
    if (fn == "exit_battle_spots"){
        const ExitSpots spots = exit_battle_spots(lines, k);
        QJsonObject out;
        out.insert("yes", spot_json(spots.yes));
        out.insert("no", spots.has_no ? QJsonValue(spot_json(spots.no)) : QJsonValue(QJsonValue::Null));
        return out;
    }
    if (fn == "party_title"){
        return party_title(lines, k);
    }
    if (fn == "party_members"){
        QStringList names;
        for (const QJsonValue& name : c.value("names").toArray()){
            names << name.toString();
        }
        return strings_json(party_members(lines, names));
    }
    if (fn == "question_kind"){
        return question_kind(lines);
    }
    if (fn == "name_box"){
        const NameBox box = name_box(lines);
        return QJsonArray{box.name, box.has_cp ? QJsonValue(box.cp) : QJsonValue(QJsonValue::Null)};
    }
    if (fn == "popup_tiles"){
        QJsonArray out;
        for (const std::pair<int, int>& tile : popup_tiles(lines)){
            out.append(QJsonArray{tile.first, tile.second});
        }
        return out;
    }
    if (fn == "button_texts"){
        const std::pair<QString, QString> texts = button_texts(lines, c.value("width").toInt());
        return QJsonArray{texts.first, texts.second};
    }
    if (fn == "result_kind"){
        return result_kind(lines);
    }
    if (fn == "party_use_spots"){
        return spots_json(party_use_spots(lines, k));
    }
    known = false;
    return QJsonValue();
}

}

int run_nav_checks(const QString& golden, QStringList& report){
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the answers of battle_nav.py are not there: " + golden;
        return 1;
    }
    const QJsonObject root = QJsonDocument::fromJson(file.readAll()).object();
    const QJsonObject screens = root.value("screens").toObject();
    const QJsonArray cases = root.value("cases").toArray();
    if (screens.isEmpty() || cases.isEmpty()){
        report << "FAILED: the file of answers of battle_nav.py is empty or not right: " + golden;
        return 1;
    }
    QHash<QString, Lines> parsed;
    for (auto it = screens.begin(); it != screens.end(); ++it){
        parsed.insert(it.key(), lines_of(it.value().toArray()));
    }

    int wrong = 0;
    int shown = 0;
    QHash<QString, int> per_function;
    for (const QJsonValue& value : cases){
        const QJsonObject c = value.toObject();
        const QString fn = c.value("fn").toString();
        const Lines lines = parsed.value(c.value("screen").toString());
        bool known = false;
        const QJsonValue got = answer(fn, c, lines, known);
        per_function[fn]++;
        if (known && got == c.value("out")){
            continue;
        }
        wrong++;
        if (shown++ < 25){
            report << "FAILED: " + fn + (c.contains("screen") ? " on " + c.value("screen").toString() : QString())
                + (known ? "" : " (not in the port)")
                + ": battle_nav.py says " + QString::fromUtf8(QJsonDocument(QJsonArray{c.value("out")}).toJson(QJsonDocument::Compact))
                + ", the port says " + QString::fromUtf8(QJsonDocument(QJsonArray{got}).toJson(QJsonDocument::Compact));
        }
    }
    QStringList functions = per_function.keys();
    functions.sort();
    report << QString("%1 answers of battle_nav.py on %2 screens in %3 functions: %4 differ")
        .arg(cases.size()).arg(screens.size()).arg(functions.size()).arg(wrong);
    return wrong;
}


}
}
}
}
