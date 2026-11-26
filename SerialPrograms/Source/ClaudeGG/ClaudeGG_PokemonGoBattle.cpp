/*  Claude GG Pokemon GO Battle (the brain of the GO Battle League fights)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <QFile>
#include <QHash>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include "ClaudeGG_PokemonGoNav.h"
#include "ClaudeGG_PokemonGoBattle.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Battle{


//  The numbers of battle_engine.py.
static const double BONUS = 1.3;
static const double STAB = 1.2;
static const double SUPER = 1.6;
static const double RESIST = 0.625;
static const double DOUBLE_RESIST = 0.390625;
static const double SHADOW_ATK = 1.2;
static const double SHADOW_DEF = 0.83333331;
static const double SHIELD_HIT = 0.20;
static const double SHIELD_HIT_LAST = 0.10;
static const double UNKNOWN_HIT = 0.45;
static const char* const FORM_DEFAULTS[] = {"average", "normal", "standard", "incarnate", "ordinary", "male"};


namespace{


//  ---------------------------------------------------------------------
//  JSON with the order of the file: the order of the species decides which of two with
//  the same name is taken, and QJsonObject sorts its keys
//  ---------------------------------------------------------------------

struct Json{
    enum Type{Null, Bool, Number, String, Array, Object};
    Type type = Null;
    bool boolean = false;
    double number = 0;
    QString string;
    std::vector<Json> array;
    std::vector<std::pair<QString, Json>> object;

    const Json* get(const QString& key) const{
        for (const std::pair<QString, Json>& item : object){
            if (item.first == key){
                return &item.second;
            }
        }
        return nullptr;
    }
};

class JsonReader{
public:
    JsonReader(const QString& text) : m_text(text) {}

    bool read(Json& out){
        skip();
        if (!value(out)){
            return false;
        }
        skip();
        return m_at == m_text.size();
    }

private:
    void skip(){
        while (m_at < m_text.size() && m_text[m_at].isSpace()){
            m_at++;
        }
    }
    bool literal(const char* word){
        const QString w = QString::fromLatin1(word);
        if (m_text.mid(m_at, w.size()) == w){
            m_at += w.size();
            return true;
        }
        return false;
    }
    bool string(QString& out){
        if (m_at >= m_text.size() || m_text[m_at] != '"'){
            return false;
        }
        m_at++;
        out.clear();
        while (m_at < m_text.size()){
            const QChar c = m_text[m_at++];
            if (c == '"'){
                return true;
            }
            if (c != '\\'){
                out += c;
                continue;
            }
            if (m_at >= m_text.size()){
                return false;
            }
            const QChar e = m_text[m_at++];
            switch (e.unicode()){
            case '"': out += '"'; break;
            case '\\': out += '\\'; break;
            case '/': out += '/'; break;
            case 'b': out += '\b'; break;
            case 'f': out += '\f'; break;
            case 'n': out += '\n'; break;
            case 'r': out += '\r'; break;
            case 't': out += '\t'; break;
            case 'u':{
                bool fine = false;
                const ushort code = m_text.mid(m_at, 4).toUShort(&fine, 16);
                if (!fine || m_at + 4 > m_text.size()){
                    return false;
                }
                out += QChar(code);
                m_at += 4;
                break;
            }
            default:
                return false;
            }
        }
        return false;
    }
    bool value(Json& out){
        if (m_at >= m_text.size()){
            return false;
        }
        const QChar c = m_text[m_at];
        if (c == '{'){
            m_at++;
            out.type = Json::Object;
            skip();
            if (m_at < m_text.size() && m_text[m_at] == '}'){
                m_at++;
                return true;
            }
            while (true){
                skip();
                QString key;
                if (!string(key)){
                    return false;
                }
                skip();
                if (m_at >= m_text.size() || m_text[m_at++] != ':'){
                    return false;
                }
                skip();
                Json item;
                if (!value(item)){
                    return false;
                }
                out.object.emplace_back(key, std::move(item));
                skip();
                if (m_at >= m_text.size()){
                    return false;
                }
                const QChar next = m_text[m_at++];
                if (next == '}'){
                    return true;
                }
                if (next != ','){
                    return false;
                }
            }
        }
        if (c == '['){
            m_at++;
            out.type = Json::Array;
            skip();
            if (m_at < m_text.size() && m_text[m_at] == ']'){
                m_at++;
                return true;
            }
            while (true){
                skip();
                Json item;
                if (!value(item)){
                    return false;
                }
                out.array.push_back(std::move(item));
                skip();
                if (m_at >= m_text.size()){
                    return false;
                }
                const QChar next = m_text[m_at++];
                if (next == ']'){
                    return true;
                }
                if (next != ','){
                    return false;
                }
            }
        }
        if (c == '"'){
            out.type = Json::String;
            return string(out.string);
        }
        if (literal("true")){
            out.type = Json::Bool;
            out.boolean = true;
            return true;
        }
        if (literal("false")){
            out.type = Json::Bool;
            return true;
        }
        if (literal("null")){
            out.type = Json::Null;
            return true;
        }
        qsizetype end = m_at;
        while (end < m_text.size() && (m_text[end].isDigit() || QString("+-.eE").contains(m_text[end]))){
            end++;
        }
        bool fine = false;
        const double number = m_text.mid(m_at, end - m_at).toDouble(&fine);
        if (!fine){
            return false;
        }
        out.type = Json::Number;
        out.number = number;
        m_at = end;
        return true;
    }

    const QString& m_text;
    qsizetype m_at = 0;
};


//  ---------------------------------------------------------------------
//  The data
//  ---------------------------------------------------------------------

struct MoveRow{
    QString id, name, type;
    int power = 0, energy = 0, gain = 0, turns = 0;
};
struct MonRow{
    QString id, name;
    QStringList types;
    int attack = 0, defense = 0, hp = 0;
    QStringList fast, charged;
    double level = 50;
    int ivs[3] = {15, 15, 15};
};
struct TypeRow{
    QStringList resists, weak, immune;
};

struct Data{
    QHash<QString, TypeRow> types;
    std::vector<MoveRow> moves;
    QHash<QString, int> move_index;
    std::vector<MonRow> mons;
    QHash<QString, int> mon_index;
    std::vector<double> cpm;
    QHash<QString, QHash<QString, QStringList>> sets;

    //  The names by their lower case letters, the first of the file wins ("names.setdefault").
    QStringList move_names;
    QHash<QString, QString> move_by_name;
    QStringList mon_names;
    QHash<QString, QString> mon_by_name;
    QHash<QString, QString> mon_by_words;
};

Data g_data;
bool g_loaded = false;


QStringList strings_of(const Json& json){
    QStringList out;
    for (const Json& item : json.array){
        out << item.string;
    }
    return out;
}

bool fill_data(const Json& root, Data& data, QString& error){
    const Json* types = root.get("types");
    const Json* moves = root.get("moves");
    const Json* mons = root.get("mons");
    const Json* cpm = root.get("cpm");
    if (types == nullptr || moves == nullptr || mons == nullptr || cpm == nullptr){
        error = "battle_data.json has no types, moves, mons or cpm";
        return false;
    }
    for (const std::pair<QString, Json>& item : types->object){
        const Json& row = item.second;
        if (row.array.size() != 3){
            error = "battle_data.json: a type is not (resists, weak, immune)";
            return false;
        }
        data.types.insert(item.first, TypeRow{strings_of(row.array[0]), strings_of(row.array[1]), strings_of(row.array[2])});
    }
    for (const std::pair<QString, Json>& item : moves->object){
        const Json& row = item.second;
        if (row.array.size() != 6){
            error = "battle_data.json: a move is not (name, type, power, energy, gain, turns)";
            return false;
        }
        MoveRow move;
        move.id = item.first;
        move.name = row.array[0].string;
        move.type = row.array[1].string;
        move.power = (int)row.array[2].number;
        move.energy = (int)row.array[3].number;
        move.gain = (int)row.array[4].number;
        move.turns = (int)row.array[5].number;
        data.move_index.insert(move.id, (int)data.moves.size());
        data.moves.push_back(move);
    }
    for (const std::pair<QString, Json>& item : mons->object){
        const Json& row = item.second;
        if (row.array.size() != 9 || row.array[7].array.size() != 4){
            error = "battle_data.json: a species is not what it should be";
            return false;
        }
        MonRow mon;
        mon.id = item.first;
        mon.name = row.array[0].string;
        mon.types = strings_of(row.array[1]);
        mon.attack = (int)row.array[2].number;
        mon.defense = (int)row.array[3].number;
        mon.hp = (int)row.array[4].number;
        mon.fast = strings_of(row.array[5]);
        mon.charged = strings_of(row.array[6]);
        mon.level = row.array[7].array[0].number;
        for (int c = 0; c < 3; c++){
            mon.ivs[c] = (int)row.array[7].array[(size_t)c + 1].number;
        }
        data.mon_index.insert(mon.id, (int)data.mons.size());
        data.mons.push_back(mon);
    }
    for (const Json& level : cpm->array){
        data.cpm.push_back(level.number);
    }
    if (data.cpm.size() < 100){
        error = "battle_data.json: the table of CP multipliers is too short";
        return false;
    }
    if (const Json* sets = root.get("sets")){
        for (const std::pair<QString, Json>& cap : sets->object){
            QHash<QString, QStringList> by_species;
            for (const std::pair<QString, Json>& species : cap.second.object){
                by_species.insert(species.first, strings_of(species.second));
            }
            data.sets.insert(cap.first, by_species);
        }
    }
    return true;
}

}   //  namespace


//  A name in lower case letters and digits with single spaces: what _norm() of Python does.
QString norm(const QString& text){
    static const QRegularExpression other("[^a-z0-9]+");
    const QString decomposed = text.normalized(QString::NormalizationForm_KD);
    QString kept;
    for (const QChar ch : decomposed){
        if (QChar::combiningClass(ch.unicode()) == 0){
            kept += ch;
        }
    }
    kept = kept.toLower();
    kept.replace(other, " ");
    return kept.trimmed();
}

static void make_names(Data& data){
    data.move_names.clear();
    data.move_by_name.clear();
    for (const MoveRow& move : data.moves){
        const QString key = norm(move.name);
        if (!data.move_by_name.contains(key)){
            data.move_by_name.insert(key, move.id);
            data.move_names << key;
        }
    }
    data.mon_names.clear();
    data.mon_by_name.clear();
    data.mon_by_words.clear();
    for (const MonRow& mon : data.mons){
        const QString key = norm(mon.name);
        if (!data.mon_by_name.contains(key)){
            data.mon_by_name.insert(key, mon.id);
            data.mon_names << key;
        }
    }
    //  "Galarian Corsola" is "Corsola (Galarian)".
    for (const QString& n : data.mon_names){
        QStringList words = n.split(' ', Qt::SkipEmptyParts);
        words.sort();
        const QString key = words.join('\x1f');
        if (!data.mon_by_words.contains(key)){
            data.mon_by_words.insert(key, data.mon_by_name.value(n));
        }
    }
}

bool load_data(const QString& path, QString& error){
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)){
        error = "battle_data.json is not there: " + path;
        return false;
    }
    const QString text = QString::fromUtf8(file.readAll());
    Json root;
    if (!JsonReader(text).read(root) || root.type != Json::Object){
        error = "battle_data.json is not JSON: " + path;
        return false;
    }
    Data data;
    if (!fill_data(root, data, error)){
        return false;
    }
    make_names(data);
    g_data = std::move(data);
    g_loaded = true;
    return true;
}

bool data_loaded(){
    return g_loaded;
}


//  ---------------------------------------------------------------------
//  Types and names
//  ---------------------------------------------------------------------

double type_mult(const QString& move_type, const QStringList& def_types){
    double mult = 1.0;
    for (const QString& t : def_types){
        const auto found = g_data.types.constFind(t);
        if (found == g_data.types.constEnd()){
            continue;
        }
        if (found->weak.contains(move_type)){
            mult *= SUPER;
        }else if (found->resists.contains(move_type)){
            mult *= RESIST;
        }else if (found->immune.contains(move_type)){
            mult *= DOUBLE_RESIST;
        }
    }
    return mult;
}

bool close_match(const QString& word, const QStringList& possibilities, double cutoff, QString& best){
    bool found = false;
    double best_score = 0;
    for (const QString& x : possibilities){
        //  (difflib sets the possibility as the first sequence and the word as the second.)
        const double score = Nav::similarity(x, word);
        if (score < cutoff){
            continue;
        }
        if (!found || score > best_score || (score == best_score && x > best)){
            found = true;
            best_score = score;
            best = x;
        }
    }
    return found;
}

QString find_move(const QString& text, double cutoff){
    if (text.isEmpty()){
        return QString();
    }
    const QString want = norm(text);
    if (want.isEmpty()){
        return QString();
    }
    const auto exact = g_data.move_by_name.constFind(want);
    if (exact != g_data.move_by_name.constEnd()){
        return exact.value();
    }
    QString close;
    if (close_match(want, g_data.move_names, cutoff, close)){
        return g_data.move_by_name.value(close);
    }
    return QString();
}

QString find_species(const QString& text, double cutoff){
    if (text.isEmpty()){
        return QString();
    }
    static const QRegularExpression shadow("\\(shadow\\)|shadow", QRegularExpression::CaseInsensitiveOption);
    QString plain = text;
    plain.remove(shadow);
    const QString want = norm(plain);
    if (want.isEmpty()){
        return QString();
    }
    const auto exact = g_data.mon_by_name.constFind(want);
    if (exact != g_data.mon_by_name.constEnd()){
        return exact.value();
    }
    QStringList want_words = want.split(' ', Qt::SkipEmptyParts);
    {
        QStringList sorted = want_words;
        sorted.sort();
        const auto same = g_data.mon_by_words.constFind(sorted.join('\x1f'));
        if (same != g_data.mon_by_words.constEnd()){
            return same.value();
        }
    }
    //  The game shows "Gourgeist" for all its sizes.
    QStringList forms;
    for (const QString& n : g_data.mon_names){
        if (n.startsWith(want + " ")){
            forms << n;
        }
    }
    if (!forms.isEmpty()){
        for (const QString& n : forms){
            const QStringList words = n.split(' ', Qt::SkipEmptyParts);
            for (const char* d : FORM_DEFAULTS){
                if (words.contains(QLatin1String(d))){
                    return g_data.mon_by_name.value(n);
                }
            }
        }
        return g_data.mon_by_name.value(forms[0]);
    }
    QString close;
    if (close_match(want, g_data.mon_names, cutoff, close)){
        return g_data.mon_by_name.value(close);
    }
    //  A stray word in front of or behind the name ("Cep Tropius": the small CP in the name box misread):
    //  the longest word that is a name on its own.
    if (want_words.size() > 1){
        QStringList long_words;
        for (const QString& w : want_words){
            if (w.size() >= 4){
                long_words << w;
            }
        }
        std::stable_sort(long_words.begin(), long_words.end(), [](const QString& a, const QString& b){
            return a.size() > b.size();
        });
        for (const QString& w : long_words){
            if (close_match(w, g_data.mon_names, std::max(cutoff, 0.85), close)){
                return g_data.mon_by_name.value(close);
            }
        }
    }
    return QString();
}


//  ---------------------------------------------------------------------
//  Stats and moves
//  ---------------------------------------------------------------------

static const MoveRow* move_row(const QString& id){
    const auto found = g_data.move_index.constFind(id);
    return found == g_data.move_index.constEnd() ? nullptr : &g_data.moves[(size_t)found.value()];
}
static const MonRow* mon_row(const QString& id){
    const auto found = g_data.mon_index.constFind(id);
    return found == g_data.mon_index.constEnd() ? nullptr : &g_data.mons[(size_t)found.value()];
}
static bool make_move(const QString& id, Move& out){
    const MoveRow* row = move_row(id);
    if (row == nullptr){
        return false;
    }
    out.id = row->id;
    out.name = row->name;
    out.type = row->type;
    out.power = row->power;
    out.energy = row->energy;
    out.gain = row->gain;
    out.turns = row->turns;
    return true;
}

//  Python's int(round(x)): halves go to the even one.
static int round_half_even(double x){
    return (int)std::nearbyint(x);
}

//  "%.2f" of Python (halves to the even digit, of the exact value).
static QString two_decimals(double x){
    char buffer[64];
    std::snprintf(buffer, sizeof(buffer), "%.2f", x);
    return QString::fromLatin1(buffer);
}

double cpm(double level){
    return g_data.cpm[(size_t)round_half_even((level - 1) * 2)];
}

int calc_cp(const int base[3], const int ivs[3], double level){
    const double c = cpm(level);
    const double cp = ((base[0] + ivs[0]) * std::sqrt((double)(base[1] + ivs[1])) *
        std::sqrt((double)(base[2] + ivs[2])) * c * c) / 10.0;
    return std::max(10, (int)cp);
}

int damage(const Move& move, const Mon& attacker, const Mon& defender){
    const double stab = attacker.types.contains(move.type) ? STAB : 1.0;
    const double eff = type_mult(move.type, defender.types);
    return (int)(move.power * stab * (attacker.atk / defender.dfn) * eff * 0.5 * BONUS) + 1;
}

QString Mon::label() const{
    return (shadow ? QString("Shadow ") : QString()) + name;
}
double Mon::hp_frac() const{
    return hp / max_hp;
}
bool Mon::alive() const{
    return hp > 0;
}

bool ranked_moveset(const QString& species, std::pair<QString, QStringList>& out, const QString& cap){
    const auto by_cap = g_data.sets.constFind(cap);
    if (by_cap == g_data.sets.constEnd()){
        return false;
    }
    const auto row = by_cap->constFind(species);
    if (row == by_cap->constEnd() || row->size() < 2){
        return false;
    }
    for (const QString& m : *row){
        if (move_row(m) == nullptr){
            return false;
        }
    }
    out.first = row->at(0);
    out.second = row->mid(1, 2);
    return true;
}

std::pair<QString, QStringList> guessed_moveset(const QString& species){
    const MonRow* row = mon_row(species);
    std::pair<QString, QStringList> out;
    if (row == nullptr){
        return out;
    }
    //  The best fast move (damage x energy per turn) ...
    double best_score = 0;
    bool first = true;
    for (const QString& id : row->fast){
        const MoveRow* m = move_row(id);
        if (m == nullptr){
            continue;
        }
        const double score = (m->power * m->gain) / (double)(m->turns * m->turns);
        if (first || score > best_score){
            first = false;
            best_score = score;
            out.first = id;
        }
    }
    //  ... and the two charged moves with the most damage per energy.
    std::vector<std::pair<double, QString>> ranked;
    for (const QString& id : row->charged){
        const MoveRow* m = move_row(id);
        if (m == nullptr){
            continue;
        }
        ranked.emplace_back(m->energy ? m->power / (double)m->energy : 0.0, id);
    }
    std::stable_sort(ranked.begin(), ranked.end(), [](const std::pair<double, QString>& a, const std::pair<double, QString>& b){
        return a.first > b.first;
    });
    for (size_t c = 0; c < ranked.size() && c < 2; c++){
        out.second << ranked[c].second;
    }
    return out;
}

std::pair<QString, QStringList> default_moveset(const QString& species){
    std::pair<QString, QStringList> ranked;
    if (ranked_moveset(species, ranked)){
        return ranked;
    }
    return guessed_moveset(species);
}

bool fit_stats(const QString& species, int cp, int hp, Fit& out){
    const MonRow* row = mon_row(species);
    if (row == nullptr){
        return false;
    }
    struct Found{
        double level;
        int a, d, h;
        double c;
    };
    std::vector<Found> found;
    for (int i = 0; i < 2 * 50; i++){                   //  levels 1 .. 50
        const double level = 1 + i / 2.0;
        const double c = g_data.cpm[(size_t)i];
        for (int hp_iv = 0; hp_iv < 16; hp_iv++){
            if (std::max(10, (int)(c * (row->hp + hp_iv))) != hp){
                continue;
            }
            for (int a = 0; a < 16; a++){
                for (int d = 0; d < 16; d++){
                    const double got = ((row->attack + a) * std::sqrt((double)(row->defense + d)) *
                        std::sqrt((double)(row->hp + hp_iv)) * c * c) / 10.0;
                    if ((int)got == cp){
                        found.push_back({level, a, d, hp_iv, c});
                    }
                }
            }
        }
    }
    if (found.empty()){
        return false;
    }
    const double n = (double)found.size();
    double atk_sum = 0;
    double dfn_sum = 0;
    for (const Found& f : found){
        atk_sum += f.c * (row->attack + f.a);
    }
    for (const Found& f : found){
        dfn_sum += f.c * (row->defense + f.d);
    }
    const double atk = atk_sum / n;
    const double dfn = dfn_sum / n;
    const Found* best = &found[0];
    double best_distance = std::abs(best->c * (row->attack + best->a) - atk);
    for (const Found& f : found){
        const double distance = std::abs(f.c * (row->attack + f.a) - atk);
        if (distance < best_distance){
            best = &f;
            best_distance = distance;
        }
    }
    out.level = best->level;
    out.ivs[0] = best->a;
    out.ivs[1] = best->d;
    out.ivs[2] = best->h;
    out.stats[0] = atk;
    out.stats[1] = dfn;
    out.stats[2] = (double)hp;
    return true;
}

bool make_mon(const MonSpec& spec, Mon& out){
    const MonRow* row = mon_row(spec.species);
    if (row == nullptr){
        return false;
    }
    Mon mon;
    mon.species = spec.species;
    mon.name = row->name;
    mon.types = row->types;
    mon.shadow = spec.shadow;
    mon.base[0] = row->attack;
    mon.base[1] = row->defense;
    mon.base[2] = row->hp;
    mon.pos = spec.pos;
    mon.level = spec.level.has_value() ? *spec.level : row->level;
    for (int c = 0; c < 3; c++){
        mon.ivs[c] = (spec.ivs.has_value() && spec.ivs->size() >= 3) ? (*spec.ivs)[(size_t)c] : row->ivs[c];
    }
    mon.cp = calc_cp(mon.base, mon.ivs, mon.level);
    const double c = cpm(mon.level);
    double atk = c * (row->attack + mon.ivs[0]);
    double dfn = c * (row->defense + mon.ivs[1]);
    double hp = (double)std::max(10, (int)(c * (row->hp + mon.ivs[2])));
    if (spec.stats.has_value() && spec.stats->size() >= 3){        //  fitted average stats override the IVs
        atk = (*spec.stats)[0];
        dfn = (*spec.stats)[1];
        hp = (*spec.stats)[2];
    }
    if (mon.shadow){
        atk *= SHADOW_ATK;
        dfn *= SHADOW_DEF;
    }
    mon.atk = atk;
    mon.dfn = dfn;
    mon.max_hp = hp;
    QString fast;
    QStringList charged;
    if (spec.fast.has_value()){
        fast = *spec.fast;
    }
    if (spec.charged.has_value()){
        charged = *spec.charged;
    }
    if (fast.isEmpty() || charged.isEmpty()){
        const std::pair<QString, QStringList> defaults = default_moveset(spec.species);
        if (fast.isEmpty()){
            fast = defaults.first;
        }
        if (charged.isEmpty()){
            charged = defaults.second;
        }
    }
    if (!make_move(fast, mon.fast)){
        return false;
    }
    for (const QString& id : charged){
        Move move;
        if (!make_move(id, move)){
            return false;
        }
        mon.charged.push_back(move);
    }
    mon.hp = hp;
    mon.energy = 0;
    mon.shields = 2;
    out = mon;
    return true;
}

std::vector<Mon> build_team(const std::vector<TeamEntry>& entries){
    std::vector<Mon> team;
    int pos = 0;
    for (const TeamEntry& e : entries){
        MonSpec spec;
        spec.species = e.species;
        spec.shadow = e.shadow;
        spec.fast = e.fast;
        spec.charged = e.charged;
        spec.pos = pos++;
        bool fitted = false;
        if (e.cp.has_value() && *e.cp != 0 && e.hp.has_value() && *e.hp != 0){
            Fit fit;
            if (fit_stats(e.species, *e.cp, *e.hp, fit)){
                fitted = true;
                spec.level = fit.level;
                spec.ivs = std::vector<int>{fit.ivs[0], fit.ivs[1], fit.ivs[2]};
                spec.stats = std::vector<double>{fit.stats[0], fit.stats[1], fit.stats[2]};
            }
        }
        if (!fitted && e.level.has_value() && *e.level != 0){
            spec.level = e.level;
            spec.ivs = e.ivs;
        }
        Mon mon;
        if (make_mon(spec, mon)){
            team.push_back(mon);
        }
    }
    return team;
}

bool foe_from_text(const QString& name, bool shadow, Mon& out){
    const QString species = find_species(name);
    if (species.isEmpty()){
        return false;
    }
    MonSpec spec;
    spec.species = species;
    spec.shadow = shadow;
    return make_mon(spec, out);
}


//  ---------------------------------------------------------------------
//  Decisions
//  ---------------------------------------------------------------------

static double dpe(const Move& move, int dmg){
    return dmg / (double)move.energy;
}

//  The damage of each charged move of a Pokémon, by the place of the move in its list.
typedef std::vector<int> Damages;

static const Move& best_charged(const std::vector<const Move*>& active, const Damages& dmg, const Mon& mon){
    (void)mon;
    const Move* best = active[0];
    for (size_t c = 1; c < active.size(); c++){
        const Move* m = active[c];
        if (dpe(*m, dmg[(size_t)(m - mon.charged.data())]) - dpe(*best, dmg[(size_t)(best - mon.charged.data())]) > 0.03){
            best = m;
        }
    }
    return *best;
}

namespace{

struct PlanState{
    int turn = 0;
    int n = 0;
    int energy = 0;
    double hp = 0;
    int shields = 0;
    std::vector<const Move*> moves;
};

//  PvPoke's planner: the charged moves that knock the foe out soonest ("false": no plan was found).
bool plan_kill(const Mon& me, int energy, double foe_hp, int foe_shields, const std::vector<const Move*>& active,
    const Damages& dmg, int fast_dmg, std::vector<const Move*>& plan){
    const Move& fast = me.fast;
    const int gain = fast.gain;
    const int fturns = fast.turns;
    std::vector<PlanState> queue;
    queue.push_back({0, 0, energy, foe_hp, foe_shields, {}});
    int seq = 1;
    int expanded = 0;
    const int limit = 500;
    while (!queue.empty() && expanded < limit){
        expanded++;
        const PlanState state = queue.front();
        queue.erase(queue.begin());
        if (state.hp <= 0){
            plan = state.moves;
            return true;
        }
        std::vector<PlanState> fresh;
        if (fast_dmg > 0){
            const int farm = (int)std::ceil(state.hp / (double)fast_dmg);
            fresh.push_back({state.turn + farm * fturns, 0, state.energy + gain * farm, 0, state.shields, state.moves});
        }
        for (const Move* m : active){
            int wait;
            if (state.energy >= m->energy){
                wait = 0;
            }else if (gain > 0){
                wait = (int)std::ceil((m->energy - state.energy) / (double)gain) * fturns;
            }else{
                continue;
            }
            const int k = wait / fturns;
            const double nhp = state.hp - fast_dmg * k
                - (state.shields > 0 ? 1 : dmg[(size_t)(m - me.charged.data())]);
            std::vector<const Move*> moves = state.moves;
            moves.push_back(m);
            fresh.push_back({state.turn + wait + 1, 0, state.energy - m->energy + gain * k, nhp,
                state.shields > 0 ? state.shields - 1 : state.shields, moves});
        }
        for (PlanState& s : fresh){
            //  Skip a state that an earlier, at least as good one already covers.
            bool covered = false;
            for (const PlanState& q : queue){
                if (q.turn <= s.turn && q.hp <= s.hp && q.energy >= s.energy && q.shields <= s.shields){
                    covered = true;
                    break;
                }
            }
            if (covered){
                continue;
            }
            size_t i = 0;
            while (i < queue.size() && queue[i].turn <= s.turn){
                i++;
            }
            s.n = seq++;
            queue.insert(queue.begin() + (qsizetype)i, s);
        }
    }
    return false;
}

}   //  namespace


Verdict should_shield(const Mon& foe, const Mon& me, int shields, const Move* foe_move,
    std::optional<double> my_hp_in, std::optional<double> foe_energy){
    const double my_hp = my_hp_in.has_value() ? *my_hp_in : me.hp;
    if (shields <= 0){
        return {false, "no shields left"};
    }
    const std::pair<int, Move> hit = foe_hit(foe, me, foe_move);
    const int dmg = hit.first;
    const Move& mv = hit.second;
    const int cycle = cycle_damage(foe, me, mv, shields, foe_energy);
    const double left = my_hp - dmg;
    if (dmg >= my_hp){
        return {true, QString("%1 would knock us out (%2 >= %3 HP)").arg(mv.name).arg(dmg).arg((int)my_hp)};
    }
    if (left <= cycle){
        return {true, QString("%1 (%2 dmg) would leave %3 HP, not enough for the next fast attacks (%4)")
            .arg(mv.name).arg(dmg).arg((int)left).arg(cycle)};
    }
    const double fast_dpt = damage(foe.fast, foe, me) / (double)foe.fast.turns;
    for (const Move& c : foe.charged){
        const int cd = damage(c, foe, me);
        if (cd >= my_hp / 1.4 && fast_dpt > 1.5){
            return {true, QString("%1 could follow (%2 dmg of %3 HP) and its fast attacks hit hard")
                .arg(c.name).arg(cd).arg((int)my_hp)};
        }
        if (cd >= my_hp - cycle){
            return {true, QString("%1 (%2 dmg) must not connect: only %3 HP would be left after a round of fast attacks")
                .arg(c.name).arg(cd).arg((int)(my_hp - cycle))};
        }
    }
    return {false, QString("%1 (%2 dmg) is survivable, keeping the shield").arg(mv.name).arg(dmg)};
}

Choice pick_charged(const Mon& me, const Mon& foe, int energy, int foe_shields, std::optional<double> foe_hp_in){
    const double foe_hp = foe_hp_in.has_value() ? *foe_hp_in : foe.hp;
    Damages dmg;
    for (const Move& m : me.charged){
        dmg.push_back(damage(m, me, foe));
    }
    auto damage_of = [&](const Move* m){
        return dmg[(size_t)(m - me.charged.data())];
    };
    //  Cheapest first; of two that cost the same, the one that hurts THIS foe most (not the highest power on
    //  paper: Sky Attack beats Shadow Ball against an Abomasnow, at 50 energy each).
    std::vector<const Move*> active;
    for (const Move& m : me.charged){
        active.push_back(&m);
    }
    std::stable_sort(active.begin(), active.end(), [&](const Move* a, const Move* b){
        if (a->energy != b->energy){
            return a->energy < b->energy;
        }
        if (damage_of(a) != damage_of(b)){
            return -damage_of(a) < -damage_of(b);
        }
        return -a->power < -b->power;
    });
    Choice result;
    if (active.empty() || energy < active[0]->energy){
        result.reason = "not enough energy";
        return result;
    }
    const int fast_dmg = damage(me.fast, me, foe);
    auto pays = [&](const Move* m){
        return m->energy <= energy;
    };

    //  1. Finish the opponent: the cheapest move that is enough.
    if (foe_shields <= 0 && foe_hp > fast_dmg){
        for (const Move* m : active){
            if (pays(m) && damage_of(m) >= foe_hp){
                result.has_move = true;
                result.move = *m;
                result.reason = QString("%1 finishes it (%2 dmg >= %3 HP)").arg(m->name).arg(damage_of(m)).arg((int)foe_hp);
                return result;
            }
        }
    }

    auto foe_would_shield = [&](const Move* m){
        return should_shield(me, foe, foe_shields, m, foe_hp).use;
    };

    const Move* best = &best_charged(active, dmg, me);

    //  2. Many cycles to go: just build up to the best move (or a cheap bait).
    const int cycle = damage_of(best) + fast_dmg * (int)std::ceil(best->energy / (double)std::max(me.fast.gain, 1));
    if (foe_hp / (double)std::max(cycle, 1) > 2){
        const Move* pick = best;
        if (foe_shields > 0 && active.size() > 1){
            bool any = false;
            for (const Move* m : active){
                if (foe_would_shield(m)){
                    any = true;
                    break;
                }
            }
            if (any){
                pick = active[0];
            }
        }
        if (energy < pick->energy){
            result.reason = "building up to " + pick->name;
            return result;
        }
        result.has_move = true;
        result.move = *pick;
        result.reason = QString("%1 is the best attack (%2 dmg, x%3)").arg(pick->name).arg(damage_of(pick))
            .arg(two_decimals(type_mult(pick->type, foe.types)));
        return result;
    }

    //  3. Few cycles to go: follow the plan that knocks the foe out soonest.
    std::vector<const Move*> plan;
    if (!plan_kill(me, energy, foe_hp, foe_shields, active, dmg, fast_dmg, plan) || plan.empty()){
        result.reason = "farming down with the fast move is quickest";
        return result;
    }
    const Move* first = plan[0];

    if (foe_shields > 0 && active.size() > 1){
        //  Keep building towards a more efficient (bait) move when it is not yet charged ...
        for (size_t c = 1; c < active.size(); c++){
            const Move* m = active[c];
            if (energy < m->energy && dpe(*m, damage_of(m)) > dpe(*first, damage_of(first))){
                result.reason = "building up to " + m->name + " to bait the shield";
                return result;
            }
        }
        //  ... but do not bait with a weak move when the foe will not shield a clearly stronger one.
        for (size_t c = 1; c < active.size(); c++){
            const Move* m = active[c];
            if (pays(m) && dpe(*m, damage_of(m)) / dpe(*first, damage_of(first)) > 1.5 && !foe_would_shield(m)){
                first = m;
            }
        }
    }

    //  No shields: lead with the hardest hitting move of the plan.
    if (foe_shields <= 0){
        const Move* hardest = plan[0];
        for (const Move* m : plan){
            if (damage_of(m) > damage_of(hardest)){
                hardest = m;
            }
        }
        first = hardest;
    //  Shields up: prefer the cheap move when it is the more efficient one.
    }else if (active.size() > 1 && active[0]->energy <= first->energy &&
        dpe(*active[0], damage_of(active[0])) > dpe(*first, damage_of(first))){
        first = active[0];
    }
    if (active.size() > 1 && active[0]->energy == first->energy &&
        dpe(*active[0], damage_of(active[0])) > dpe(*first, damage_of(first))){
        first = active[0];
    }

    if (energy < first->energy){
        result.reason = "building up to " + first->name;
        return result;
    }
    result.has_move = true;
    result.move = *first;
    if (foe_shields > 0){
        result.reason = QString("%1 as bait (foe has %2 shield%3)").arg(first->name).arg(foe_shields)
            .arg(foe_shields == 1 ? "" : "s");
    }else{
        result.reason = QString("%1 is the best attack (%2 dmg, x%3)").arg(first->name).arg(damage_of(first))
            .arg(two_decimals(type_mult(first->type, foe.types)));
    }
    return result;
}

std::vector<Move> can_throw(const Mon& foe, std::optional<double> energy){
    if (!energy.has_value()){
        return foe.charged;
    }
    std::vector<Move> out;
    for (const Move& m : foe.charged){
        if (m.energy <= *energy){
            out.push_back(m);
        }
    }
    return out.empty() ? foe.charged : out;
}

std::pair<int, Move> foe_hit(const Mon& foe, const Mon& me, const Move* foe_move, std::optional<double> energy){
    if (foe_move != nullptr){
        return {damage(*foe_move, foe, me), *foe_move};
    }
    const std::vector<Move> moves = can_throw(foe, energy);
    const Move* best = &moves[0];
    int best_damage = damage(moves[0], foe, me);
    for (const Move& m : moves){
        const int d = damage(m, foe, me);
        if (d > best_damage){
            best = &m;
            best_damage = d;
        }
    }
    return {best_damage, *best};
}

std::pair<double, int> fast_rate(const QString& species){
    const MonRow* row = mon_row(species);
    bool any = false;
    double rate = 0;
    int per_move = 0;
    if (row != nullptr){
        for (const QString& id : row->fast){
            const MoveRow* m = move_row(id);
            if (m == nullptr || m->turns <= 0){
                continue;
            }
            const double r = m->gain / (m->turns * 0.5);
            if (!any || r > rate){
                rate = r;
            }
            if (!any || m->gain > per_move){
                per_move = m->gain;
            }
            any = true;
        }
    }
    if (!any){
        return {10.0, 15};
    }
    return {rate, per_move};
}

int cheapest_charged(const QString& species){
    const MonRow* row = mon_row(species);
    bool any = false;
    int cheapest = 35;
    if (row != nullptr){
        for (const QString& id : row->charged){
            const MoveRow* m = move_row(id);
            if (m == nullptr || m->energy <= 0){
                continue;
            }
            if (!any || m->energy < cheapest){
                cheapest = m->energy;
            }
            any = true;
        }
    }
    return any ? cheapest : 35;
}

int cycle_damage(const Mon& foe, const Mon& me, const Move& move, int shields, std::optional<double> foe_energy){
    const Move& fast = foe.fast;
    if (fast.gain <= 0){
        return 0;
    }
    const double have = foe_energy.has_value() ? *foe_energy : 0.0;
    const double need = move.energy - std::max(have - move.energy, 0.0);
    const int n = (int)std::ceil(need / (double)fast.gain) + 1;
    return (n * damage(fast, foe, me) + 1) * std::max(shields, 0);
}

Verdict use_shield(const Mon* foe, const Mon& me, int shields, std::optional<double> my_hp_in,
    std::optional<int> mine_left, std::optional<int> foes_left, bool ready, const Move* foe_move,
    std::optional<double> foe_energy){
    const double my_hp = my_hp_in.has_value() ? *my_hp_in : me.hp;
    if (shields <= 0){
        return {false, "no shields left"};
    }
    int dmg;
    QString name;
    if (foe == nullptr){
        dmg = round_half_even(UNKNOWN_HIT * me.max_hp);
        name = "the attack of a foe that is not known";
    }else{
        const std::pair<int, Move> hit = foe_hit(*foe, me, foe_move, foe_energy);
        dmg = hit.first;
        const Move& mv = hit.second;
        name = mv.name;
        if (foe_move == nullptr && foe_energy.has_value()){
            //  (Said first: why the hard one is not counted.)
            bool affordable = false;
            for (const Move& m : foe->charged){
                if (m.energy <= *foe_energy){
                    affordable = true;
                }
            }
            std::vector<const Move*> out;
            if (affordable){
                for (const Move& m : foe->charged){
                    if (m.energy > *foe_energy){
                        out.push_back(&m);
                    }
                }
            }
            if (!out.empty()){
                const Verdict inner = use_shield(foe, me, shields, my_hp, mine_left, foes_left, ready, &mv);
                QStringList names;
                int cheapest = out[0]->energy;
                for (const Move* m : out){
                    names << m->name;
                    cheapest = std::min(cheapest, m->energy);
                }
                return {inner.use, QString("it can only be %1 (%2 costs %3 energy, %4 has %5 at most) - %6")
                    .arg(name, names.join(" / ")).arg(cheapest).arg(foe->label()).arg((int)*foe_energy).arg(inner.reason)};
            }
        }
    }
    const double saved = std::max(std::min((double)dmg, my_hp), 0.0);
    const double part = saved / me.max_hp;
    const QString pct = QString("%1%").arg(round_half_even(100 * part));
    const bool lethal = dmg >= my_hp;
    if (lethal && mine_left.has_value() && *mine_left <= 1){
        return {true, QString("%1 would knock out our last Pokémon (%2 >= %3 HP)").arg(name).arg(dmg).arg((int)my_hp)};
    }
    if (lethal && ready){
        return {true, QString("%1 would knock us out (%2 >= %3 HP) and our own charged attack is ready")
            .arg(name).arg(dmg).arg((int)my_hp)};
    }
    QString last;
    if (mine_left.has_value() && *mine_left <= 1){
        last = "this is our last Pokémon";
    }else if (foes_left.has_value() && *foes_left <= 1){
        last = "the foe is on its last Pokémon";
    }
    const double limit = last.isEmpty() ? SHIELD_HIT : SHIELD_HIT_LAST;
    if (part >= limit){
        QString text = QString("%1 would take %2 of our HP (%3 of %4)").arg(name, pct).arg((int)saved).arg((int)me.max_hp);
        if (!last.isEmpty() && part < SHIELD_HIT){
            text += QString(" and %1: nothing to keep the shield for").arg(last);
        }
        return {true, text};
    }
    if (lethal){
        return {false, QString("only %1 HP (%2) left to save from %3 - the shield is kept for the next Pokémon")
            .arg((int)saved).arg(pct, name)};
    }
    return {false, QString("%1 is a small hit (%2 dmg, %3 of our HP) - keeping the shield").arg(name).arg(dmg).arg(pct)};
}


//  ---------------------------------------------------------------------
//  Duels
//  ---------------------------------------------------------------------

std::pair<double, double> simulate(const Mon& a, const Mon& b, int shields_a, int shields_b, int max_turns){
    struct Side{
        const Mon* m;
        double hp;
        int en;
        int sh;
        int ready;
        bool landing;
        int land;
    };
    Side side[2] = {
        {&a, a.hp, std::min(100, a.energy), shields_a, 0, false, 0},
        {&b, b.hp, std::min(100, b.energy), shields_b, 0, false, 0},
    };
    const int first = a.atk >= b.atk ? 0 : 1;               //  ties: higher attack first
    const int order[2] = {first, 1 - first};

    for (int t = 0; t < max_turns; t++){
        //  Fast moves that land this turn.
        for (const int i : order){
            Side& s = side[i];
            Side& o = side[1 - i];
            if (s.landing && s.land == t && s.hp > 0){
                o.hp -= damage(s.m->fast, *s.m, *o.m);
                s.en = std::min(100, s.en + s.m->fast.gain);
                s.landing = false;
            }
        }
        if (side[0].hp <= 0 || side[1].hp <= 0){
            break;
        }
        for (const int i : order){
            Side& s = side[i];
            Side& o = side[1 - i];
            if (s.hp <= 0 || s.ready > t){
                continue;
            }
            const Choice mv = pick_charged(*s.m, *o.m, s.en, o.sh, std::max(0.0, o.hp));
            if (mv.has_move){
                s.en -= mv.move.energy;
                const Verdict shield = should_shield(*s.m, *o.m, o.sh, &mv.move, std::max(0.0, o.hp), (double)s.en);
                if (shield.use){
                    o.sh -= 1;
                    o.hp -= 1;
                }else{
                    o.hp -= damage(mv.move, *s.m, *o.m);
                }
                if (o.hp <= 0){
                    break;
                }
            }
            if (s.hp > 0 && !s.landing){
                s.landing = true;
                s.land = t + s.m->fast.turns;
                s.ready = s.land;
            }
        }
        if (side[0].hp <= 0 || side[1].hp <= 0){
            break;
        }
    }
    return {std::max(0.0, side[0].hp) / a.max_hp, std::max(0.0, side[1].hp) / b.max_hp};
}

double matchup(const Mon& me, const Mon& foe, int my_shields, int foe_shields){
    const std::pair<double, double> result = simulate(me, foe, my_shields, foe_shields);
    return result.first - result.second;
}

std::pair<int, double> best_switch(const std::vector<Mon>& candidates, const Mon& foe, int my_shields, int foe_shields){
    struct Scored{
        double score;
        int minus_pos;
        int index;
    };
    std::vector<Scored> scored;
    for (size_t c = 0; c < candidates.size(); c++){
        if (candidates[c].hp <= 0){
            continue;
        }
        scored.push_back({matchup(candidates[c], foe, my_shields, foe_shields), -candidates[c].pos, (int)c});
    }
    if (scored.empty()){
        return {-1, 0.0};
    }
    std::stable_sort(scored.begin(), scored.end(), [](const Scored& a, const Scored& b){
        if (a.score != b.score){
            return a.score > b.score;
        }
        return a.minus_pos > b.minus_pos;
    });
    return {scored[0].index, scored[0].score};
}


//  ---------------------------------------------------------------------
//  The test: the answers of battle_engine.py
//  ---------------------------------------------------------------------

namespace{

QJsonValue string_or_null(const QString& text){
    return text.isEmpty() ? QJsonValue(QJsonValue::Null) : QJsonValue(text);
}

QJsonArray ids_json(const std::vector<Move>& moves){
    QJsonArray out;
    for (const Move& m : moves){
        out.append(m.id);
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

QJsonObject mon_json(const Mon& m){
    QJsonObject out;
    out.insert("species", m.species);
    out.insert("name", m.name);
    out.insert("label", m.label());
    out.insert("types", strings_json(m.types));
    out.insert("shadow", m.shadow);
    out.insert("cp", m.cp);
    out.insert("level", m.level);
    out.insert("ivs", QJsonArray{m.ivs[0], m.ivs[1], m.ivs[2]});
    out.insert("atk", m.atk);
    out.insert("dfn", m.dfn);
    out.insert("max_hp", m.max_hp);
    out.insert("hp", m.hp);
    out.insert("fast", m.fast.id);
    out.insert("charged", ids_json(m.charged));
    out.insert("pos", m.pos);
    return out;
}

QStringList strings_of_json(const QJsonValue& value){
    QStringList out;
    for (const QJsonValue& v : value.toArray()){
        out << v.toString();
    }
    return out;
}

std::vector<int> ints_of_json(const QJsonValue& value){
    std::vector<int> out;
    for (const QJsonValue& v : value.toArray()){
        out.push_back(v.toInt());
    }
    return out;
}

//  A Pokémon as the file describes it; false when it is not in the data.
bool mon_of(const QJsonObject& spec, Mon& out){
    MonSpec s;
    s.species = spec.value("species").toString();
    s.shadow = spec.value("shadow").toBool();
    s.pos = spec.value("pos").toInt();
    if (spec.contains("level")){
        s.level = spec.value("level").toDouble();
    }
    if (spec.contains("ivs")){
        s.ivs = ints_of_json(spec.value("ivs"));
    }
    if (spec.contains("fast")){
        s.fast = spec.value("fast").toString();
    }
    if (spec.contains("charged")){
        s.charged = strings_of_json(spec.value("charged"));
    }
    if (spec.contains("stats")){
        std::vector<double> stats;
        for (const QJsonValue& v : spec.value("stats").toArray()){
            stats.push_back(v.toDouble());
        }
        s.stats = stats;
    }
    if (!make_mon(s, out)){
        return false;
    }
    if (spec.contains("hp")){
        out.hp = spec.value("hp").toDouble();
    }
    if (spec.contains("energy")){
        out.energy = spec.value("energy").toInt();
    }
    return true;
}

const Move* move_of(const Mon& mon, const QString& id){
    if (mon.fast.id == id){
        return &mon.fast;
    }
    for (const Move& m : mon.charged){
        if (m.id == id){
            return &m;
        }
    }
    return nullptr;
}

std::optional<double> optional_number(const QJsonObject& in, const char* key){
    const QJsonValue v = in.value(key);
    if (v.isNull() || v.isUndefined()){
        return {};
    }
    return v.toDouble();
}
std::optional<int> optional_int(const QJsonObject& in, const char* key){
    const QJsonValue v = in.value(key);
    if (v.isNull() || v.isUndefined()){
        return {};
    }
    return v.toInt();
}

bool same(const QJsonValue& a, const QJsonValue& b){
    if (a.isDouble() && b.isDouble()){
        const double x = a.toDouble();
        const double y = b.toDouble();
        return x == y || std::abs(x - y) <= 1e-9 * std::max(1.0, std::max(std::abs(x), std::abs(y)));
    }
    if (a.type() != b.type()){
        return false;
    }
    if (a.isArray()){
        const QJsonArray x = a.toArray();
        const QJsonArray y = b.toArray();
        if (x.size() != y.size()){
            return false;
        }
        for (qsizetype c = 0; c < x.size(); c++){
            if (!same(x[c], y[c])){
                return false;
            }
        }
        return true;
    }
    if (a.isObject()){
        const QJsonObject x = a.toObject();
        const QJsonObject y = b.toObject();
        if (x.keys() != y.keys()){
            return false;
        }
        for (const QString& key : x.keys()){
            if (!same(x.value(key), y.value(key))){
                return false;
            }
        }
        return true;
    }
    return a == b;
}

//  What the port answers for one question of the file, as the file has it; "known" is false for a function
//  that this port has not got.
QJsonValue answer(const QString& fn, const QJsonObject& in, bool& known){
    known = true;
    const QJsonValue broken = QJsonValue(QString("the question names a Pokémon or a move that is not in the data"));
    if (fn == "type_mult"){
        return type_mult(in.value("type").toString(), strings_of_json(in.value("against")));
    }
    if (fn == "find_move" || fn == "find_species"){
        const bool move = fn == "find_move";
        const QString text = in.value("text").toString();
        if (in.contains("cutoff")){
            return string_or_null(move ? find_move(text, in.value("cutoff").toDouble()) : find_species(text, in.value("cutoff").toDouble()));
        }
        return string_or_null(move ? find_move(text) : find_species(text));
    }
    if (fn == "default_moveset" || fn == "guessed_moveset"){
        const QString species = in.value("species").toString();
        const std::pair<QString, QStringList> set = fn == "default_moveset" ? default_moveset(species) : guessed_moveset(species);
        return QJsonArray{set.first, strings_json(set.second)};
    }
    if (fn == "fast_rate"){
        const std::pair<double, int> rate = fast_rate(in.value("species").toString());
        return QJsonArray{rate.first, rate.second};
    }
    if (fn == "cheapest_charged"){
        return cheapest_charged(in.value("species").toString());
    }
    if (fn == "cpm"){
        return cpm(in.value("level").toDouble());
    }
    if (fn == "calc_cp"){
        const std::vector<int> base = ints_of_json(in.value("base"));
        const std::vector<int> ivs = ints_of_json(in.value("ivs"));
        return calc_cp(base.data(), ivs.data(), in.value("level").toDouble());
    }
    if (fn == "fit_stats"){
        Fit fit;
        if (!fit_stats(in.value("species").toString(), in.value("cp").toInt(), in.value("hp").toInt(), fit)){
            return QJsonValue(QJsonValue::Null);
        }
        return QJsonArray{fit.level, QJsonArray{fit.ivs[0], fit.ivs[1], fit.ivs[2]},
            QJsonArray{fit.stats[0], fit.stats[1], fit.stats[2]}};
    }
    if (fn == "build_team"){
        std::vector<TeamEntry> entries;
        for (const QJsonValue& v : in.value("entries").toArray()){
            const QJsonObject e = v.toObject();
            TeamEntry entry;
            entry.species = e.value("species").toString();
            entry.shadow = e.value("shadow").toBool();
            if (e.contains("cp")){
                entry.cp = e.value("cp").toInt();
            }
            if (e.contains("hp")){
                entry.hp = e.value("hp").toInt();
            }
            if (e.contains("level")){
                entry.level = e.value("level").toDouble();
            }
            if (e.contains("ivs")){
                entry.ivs = ints_of_json(e.value("ivs"));
            }
            if (e.contains("fast")){
                entry.fast = e.value("fast").toString();
            }
            if (e.contains("charged")){
                entry.charged = strings_of_json(e.value("charged"));
            }
            entries.push_back(entry);
        }
        QJsonArray out;
        for (const Mon& m : build_team(entries)){
            out.append(mon_json(m));
        }
        return out;
    }
    if (fn == "mon"){
        Mon m;
        return mon_of(in.value("spec").toObject(), m) ? QJsonValue(mon_json(m)) : broken;
    }
    if (fn == "best_switch"){
        std::vector<Mon> team;
        for (const QJsonValue& v : in.value("team").toArray()){
            Mon m;
            if (!mon_of(v.toObject(), m)){
                return broken;
            }
            team.push_back(m);
        }
        Mon foe;
        if (!mon_of(in.value("foe").toObject(), foe)){
            return broken;
        }
        const std::pair<int, double> best = best_switch(team, foe);
        return QJsonArray{best.first < 0 ? QJsonValue(QJsonValue::Null) : QJsonValue(team[(size_t)best.first].pos), best.second};
    }

    //  The rest of them are about two Pokémon.
    Mon first;
    Mon second;
    const char* names[][2] = {
        {"damage", "attacker"}, {"pick_charged", "me"}, {"should_shield", "foe"}, {"use_shield", "foe"},
        {"foe_hit", "foe"}, {"can_throw", "foe"}, {"cycle_damage", "foe"}, {"simulate", "a"}, {"matchup", "a"},
    };
    const char* other[] = {"defender", "foe", "me", "me", "me", "", "me", "b", "b"};
    int which = -1;
    for (int c = 0; c < 9; c++){
        if (fn == QLatin1String(names[c][0])){
            which = c;
        }
    }
    if (which < 0){
        known = false;
        return QJsonValue();
    }
    const QJsonValue first_spec = in.value(names[which][1]);
    const bool first_null = first_spec.isNull();
    if (!first_null && !mon_of(first_spec.toObject(), first)){
        return broken;
    }
    if (other[which][0] != 0 && !mon_of(in.value(other[which]).toObject(), second)){
        return broken;
    }

    if (fn == "damage"){
        const Move* move = move_of(first, in.value("move").toString());
        return move == nullptr ? broken : QJsonValue(damage(*move, first, second));
    }
    if (fn == "pick_charged"){
        const Choice c = pick_charged(first, second, in.value("energy").toInt(), in.value("foe_shields").toInt(),
            optional_number(in, "foe_hp"));
        return QJsonArray{c.has_move ? QJsonValue(c.move.id) : QJsonValue(QJsonValue::Null), c.reason};
    }
    if (fn == "should_shield" || fn == "use_shield"){
        const Move* move = in.contains("foe_move") ? move_of(first, in.value("foe_move").toString()) : nullptr;
        const int shields = in.value("shields").toInt();
        Verdict v;
        if (fn == "should_shield"){
            v = should_shield(first, second, shields, move, optional_number(in, "my_hp"), optional_number(in, "foe_energy"));
        }else{
            v = use_shield(first_null ? nullptr : &first, second, shields, optional_number(in, "my_hp"),
                optional_int(in, "mine_left"), optional_int(in, "foes_left"), in.value("ready").toBool(), move,
                optional_number(in, "foe_energy"));
        }
        return QJsonArray{v.use, v.reason};
    }
    if (fn == "foe_hit"){
        const std::pair<int, Move> hit = foe_hit(first, second, nullptr, optional_number(in, "energy"));
        return QJsonArray{hit.first, hit.second.id};
    }
    if (fn == "can_throw"){
        return ids_json(can_throw(first, optional_number(in, "energy")));
    }
    if (fn == "cycle_damage"){
        const Move* move = move_of(first, in.value("move").toString());
        return move == nullptr ? broken : QJsonValue(cycle_damage(first, second, *move, in.value("shields").toInt(),
            optional_number(in, "foe_energy")));
    }
    if (fn == "simulate"){
        const std::pair<double, double> r = simulate(first, second, in.value("shields_a").toInt(), in.value("shields_b").toInt());
        return QJsonArray{r.first, r.second};
    }
    return matchup(first, second, in.value("shields_a").toInt(), in.value("shields_b").toInt());
}

}   //  namespace

int run_engine_checks(const QString& golden, const QString& data, QStringList& report){
    QString error;
    if (!load_data(data, error)){
        report << "FAILED: " + error;
        return 1;
    }
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the answers of battle_engine.py are not there: " + golden;
        return 1;
    }
    const QJsonArray cases = QJsonDocument::fromJson(file.readAll()).object().value("cases").toArray();
    if (cases.isEmpty()){
        report << "FAILED: the file of answers of battle_engine.py is empty or not right: " + golden;
        return 1;
    }
    int wrong = 0;
    int shown = 0;
    QHash<QString, int> per_function;
    for (const QJsonValue& value : cases){
        const QJsonObject c = value.toObject();
        const QString fn = c.value("fn").toString();
        bool known = false;
        const QJsonValue got = answer(fn, c.value("in").toObject(), known);
        per_function[fn]++;
        if (known && same(got, c.value("out"))){
            continue;
        }
        wrong++;
        if (shown++ < 25){
            auto compact = [](const QJsonValue& v){
                return QString::fromUtf8(QJsonDocument(QJsonArray{v}).toJson(QJsonDocument::Compact));
            };
            report << "FAILED: " + fn + " " + compact(c.value("in")).left(300)
                + (known ? "" : " (not in the port)")
                + ": battle_engine.py says " + compact(c.value("out")).left(300)
                + ", the port says " + compact(got).left(300);
        }
    }
    report << QString("%1 answers of battle_engine.py in %2 functions: %3 differ")
        .arg(cases.size()).arg(per_function.size()).arg(wrong);
    return wrong;
}


}
}
}
}
