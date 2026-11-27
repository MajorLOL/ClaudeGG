/*  Claude GG Pokemon GO Fight (the state of one GO Battle League fight)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include "ClaudeGG_PokemonGoNav.h"
#include "ClaudeGG_PokemonGoFight.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Fight{

using Battle::Mon;
using Battle::Move;


//  The numbers of battle_fight.py.
static const int PREDICT_MIN = 4;           //  battles in which a species was seen to throw its first charged attack ...
static const double PREDICT_SHARE = 0.8;    //  ... and the share of them with the same one: then that one is expected first
static const double HP_JUMP = 0.30;         //  a bigger change between two pictures has to be seen twice before it is believed
static const double FAINTED_BELOW = 0.25;   //  a Pokémon with less HP than this that is replaced has fainted
static const int LABEL_TRIES = 8;           //  pictures to read the labels under the buttons from
static const int FOE_RETRY = 8;             //  a name box that gave nothing is read again after this many pictures at most
static const double GOING_DOWN_HP = 0.20;
static const int GOING_DOWN_FAST = 4;
static const double JUST_CAME_IN_S = 8.0;
static const int JUST_CAME_IN = 60;
static const int SWITCH_MISSED = 250;
static const int HP_BACK_UP = 12;
static const double FOE_BACK_SOON = 6.0;
static const long long LONG_AGO = 1000000;


namespace{

//  Python's int(round(x)): halves go to the even one.
int round_half_even(double x){
    return (int)std::nearbyint(x);
}

//  f"{x:.0%}" and f"{x:+.2f}" of Python.
QString percent(double x){
    char buffer[64];
    std::snprintf(buffer, sizeof(buffer), "%.0f%%", x * 100);
    return QString::fromLatin1(buffer);
}
QString signed_two(double x){
    char buffer[64];
    std::snprintf(buffer, sizeof(buffer), "%+.2f", x);
    return QString::fromLatin1(buffer);
}

//  f"{mon.hp}": a float prints as 174.0.
QString hp_text(const Mon& mon){
    const QString whole = QString::number((long long)mon.hp);
    return mon.hp_float ? whole + ".0" : whole;
}

//  str.split() with no argument.
QStringList py_split(const QString& text){
    return text.split(QRegularExpression("\\s+"), Qt::SkipEmptyParts);
}

//  the names of a list of moves, joined
QString names_of(const std::vector<Move>& moves, const QString& by){
    QStringList names;
    for (const Move& m : moves){
        names << m.name;
    }
    return names.join(by);
}

//  A counter dictionary of Python with the order of the keys kept.
Counts* find_counts(Known& known, const QString& species){
    for (std::pair<QString, Counts>& item : known){
        if (item.first == species){
            return &item.second;
        }
    }
    return nullptr;
}
const Counts* find_counts(const Known& known, const QString& species){
    for (const std::pair<QString, Counts>& item : known){
        if (item.first == species){
            return &item.second;
        }
    }
    return nullptr;
}
Counts& counts_of(Known& known, const QString& species){
    if (Counts* found = find_counts(known, species)){
        return *found;
    }
    known.emplace_back(species, Counts());
    return known.back().second;
}
void add_count(Counts& counts, const QString& key){
    for (std::pair<QString, int>& item : counts){
        if (item.first == key){
            item.second++;
            return;
        }
    }
    counts.emplace_back(key, 1);
}

}   //  namespace


QString state(const Features& feat){
    if (feat.white || feat.versus){
        return "other";
    }
    if ((feat.result || feat.done) && !feat.hud){
        return "result";
    }
    if (feat.ring){
        return "prompt";
    }
    if (feat.hud){
        return "fight";
    }
    return "other";
}


bool Fight::AimKey::operator==(const AimKey& o) const{
    return pos == o.pos && species == o.species && my_hp == o.my_hp && foe_hp == o.foe_hp
        && foe_shields == o.foe_shields && button_slots[0] == o.button_slots[0] && button_slots[1] == o.button_slots[1];
}

Fight::Fight(const std::vector<Mon>& team_, Log log_, Known known_)
    : team(team_)
    , known(std::move(known_))
    , m_log(std::move(log_))
{
    me = 0;
    m_came_mon = 0;
    m_came_hp = team[0].hp;
    m_came_hp_float = team[0].hp_float;
}

void Fight::log(const QString& text) const{
    if (m_log){
        m_log(text);
    }
}


//  ---------------------------------------------------------------------
//  What is seen
//  ---------------------------------------------------------------------

//  New HP fraction of one side: small steps are taken at once, a big jump has to be seen twice (the
//  readings are wrong now and then while a banner covers the bar).
double Fight::believe(const QString& side, double old, std::optional<double> value){
    std::optional<double>& pending = side == "me" ? m_pending_me : m_pending_foe;
    if (!value.has_value()){
        return old;
    }
    if (std::abs(*value - old) <= HP_JUMP){
        pending.reset();
        return *value;
    }
    if (pending.has_value() && std::abs(*pending - *value) <= 0.06){
        pending.reset();
        return *value;
    }
    pending = value;
    return old;
}

void Fight::see(const Features& feat){
    seen++;
    const std::optional<double> mine = feat.hp_me;
    const std::optional<double> foe_read = feat.hp_foe;
    double old = my_hp;
    my_hp = believe("me", my_hp, mine);
    if (old < my_hp && my_hp <= old + HP_JUMP){     //  (a Pokémon never heals: a small rise is a misread ...
        my_hp = old;
        if (feat.hud && m_rise_reading.has_value() && std::abs(*mine - *m_rise_reading) <= 0.10){
            m_rise_rows++;
        }else if (feat.hud){
            m_rise_reading = mine;
            m_rise_rows = 1;
        }
        if (m_rise_rows >= HP_BACK_UP){             //  ... unless the bar says so on picture after picture: then what
            my_hp = *mine;                          //  was believed before was the misread
            m_rise_reading.reset();
            m_rise_rows = 0;
        }
    }else if (old < FAINTED_BELOW && my_hp > 0.6){
        came_in();                                  //  (a full bar after a nearly empty one: the next one of ours)
    }
    if (mine.has_value() && *mine <= old + 0.03){
        m_rise_reading.reset();                     //  (the bar does not read higher on this picture: no misread below)
        m_rise_rows = 0;
    }
    if (mine.has_value() && feat.hud && std::abs(*mine - my_hp) <= 0.06){
        my_reads++;                                 //  (its HP is known from its own bar, read in the plain fight)
        my_read = my_hp;
    }
    me_mon().hp = round_half_even(my_hp * me_mon().max_hp);
    me_mon().hp_float = false;

    old = foe_hp;
    double fresh = believe("foe", foe_hp, foe_read);
    if (fresh > old + HP_JUMP){                     //  the foe's HP went up: its next Pokémon is on the field
        log("fight: the foe's HP bar is full again - a new foe");
        since_foe = LONG_AGO;                       //  (read its name now)
    }else if (fresh > old){
        fresh = old;
    }
    foe_hp = fresh;
    if (foe.has_value()){
        foe->hp = round_half_even(foe_hp * foe->max_hp);
        foe->hp_float = false;
    }
    if (feat.hud && !feat.white){
        since_foe++;
        see_shields(feat.shields_me, feat.shields_foe);
        lit[0] = feat.lit[0];
        lit[1] = feat.lit[1];
        calibrate();
        if (feat.has_balls && feat.balls[0] + feat.balls[1] == 3){      //  (all three are seen: none under a banner)
            see_balls(feat.balls[0]);
        }
    }
}

//  The Poké Balls of our name box: `red` of our three can still fight. A Pokémon that faints from a
//  charged attack is gone without its HP bar ever being seen empty; its ball turning grey is the sign.
void Fight::see_balls(int red){
    if (red != balls_red){
        balls_red = red;
        balls_rows = 1;
        balls_at = seen;
    }else{
        balls_rows++;
    }
    if (balls_rows != 2 || 3 - red != (int)dead.size() + 1){
        return;
    }
    std::vector<int> others;
    for (const Mon& m : team){
        if (dead.count(m.pos) == 0 && m.pos != me){
            others.push_back(m.pos);
        }
    }
    if (others.size() != 1){
        return;
    }
    Mon& other = team[(size_t)others[0]];
    if (named_at >= balls_at){
        log("fight: another Poké Ball of ours is grey - " + other.label() + " has fainted too");
        dead.insert(other.pos);
        other.hp = 0;
        other.hp_float = false;
    }else{
        log("fight: another Poké Ball of ours is grey - " + me_mon().label() + " fainted, " + other.label()
            + " is on the field");
        faint();
        enter(other.pos);
    }
}

bool Fight::fainted_more() const{
    return 3 - balls_red > (int)dead.size();
}

//  Shield icons: a lower number is believed after two pictures that agree. The foe's never goes up.
//  Ours does, after shields_back pictures that agree.
void Fight::see_shields(std::optional<int> sh_me, std::optional<int> sh_foe){
    const int now_me = my_shields;
    const int now_foe = foe_shields;
    for (int which = 0; which < 2; which++){
        const bool mine = which == 0;
        const std::optional<int> n = mine ? sh_me : sh_foe;
        const int now = mine ? now_me : now_foe;
        std::optional<int>& seen_before = mine ? m_shield_seen_me : m_shield_seen_foe;
        if (mine && n.has_value() && *n > now){
            m_shield_more = (m_shield_more_n.has_value() && *m_shield_more_n == *n) ? m_shield_more + 1 : 1;
            m_shield_more_n = n;
            if (m_shield_more >= shields_back){
                log(QString("fight: we still have %1 shield(s) - one that was counted as used was not used").arg(*n));
                my_shields = *n;
                m_shield_more = 0;
            }
            seen_before.reset();
            continue;
        }
        if (mine){
            m_shield_more = 0;
        }
        if (!n.has_value() || *n >= now){
            seen_before.reset();
            continue;
        }
        if (seen_before.has_value() && *seen_before == *n){
            seen_before.reset();
            if (mine){
                my_shields = *n;
            }else{
                foe_shields = *n;
                log(QString("fight: the foe has %1 shield(s) left").arg(*n));
            }
        }else{
            seen_before = n;
        }
    }
}

//  Time to read the name boxes again.
bool Fight::foe_due() const{
    return since_foe >= foe_every;
}

//  Something changed in a name box (side: "me" / "foe"): read the names at the next picture.
void Fight::read_names(const QString& side){
    since_foe = LONG_AGO;
    if (side != "me" && !change.has_value()){
        change = clock;
    }
}


//  ---------------------------------------------------------------------
//  The foe's energy
//  ---------------------------------------------------------------------

//  `seconds` more of the plain fight have passed: both sides were tapping fast attacks.
void Fight::fought(double seconds){
    clock += std::max(seconds, 0.0);
}

//  What the foe on the field has at most at time `at` of the clock (now), without any margin.
double Fight::energy_at(std::optional<double> at) const{
    const double rate = Battle::fast_rate(foe->species).first;
    return std::min(100.0, foe_e_base + rate * std::max((at.has_value() ? *at : clock) - foe_e_mark, 0.0));
}

//  The energy the foe has at most right now, none when that is not known.
std::optional<double> Fight::foe_energy() const{
    if (!foe.has_value() || !foe_e_ok || change.has_value()){
        return {};
    }
    return std::min(100.0, energy_at() + Battle::fast_rate(foe->species).second);
}

//  The foe has thrown a charged attack (the question about it is up). Its energy went down by the cost
//  of that attack: by the least any attack of its species costs, until the banner names it (foe_used).
void Fight::foe_threw(bool sure){
    if (!foe.has_value()){
        has_threw = false;
        return;
    }
    if (m_threw_species.count(foe->species) == 0){          //  its first charged attack of this battle
        m_threw_species.insert(foe->species);
        m_first_pending = foe->species;
    }
    const std::optional<double> had = foe_energy();
    const int cost = sure ? Battle::cheapest_charged(foe->species) : 0;
    has_threw = true;
    threw_had = had;
    threw_cost = cost;
    if (had.has_value()){                       //  (counted on from here; the margin is only added when it is asked)
        foe_e_base = std::max(energy_at() - cost, 0.0);
        foe_e_mark = clock;
    }
}

//  The energy the foe had at most when it threw the attack that is on its way (none: not known).
std::optional<double> Fight::threw_with() const{
    return has_threw ? threw_had : foe_energy();
}

//  The foe's name box was read. Returns true when the foe is known now.
bool Fight::set_foe(const QString& name, std::optional<int> cp){
    since_foe = 0;
    Mon fresh;
    const bool known_foe = !name.isEmpty() && Battle::foe_from_text(name, false, fresh);
    if (!known_foe){
        //  Nothing was read, or a name that is not known: a banner over the box? Try again soon - until then
        //  the one before is taken to be on the field.
        since_foe = std::max(foe_every - FOE_RETRY, 0);
        if (!name.isEmpty() && name != m_foe_miss){
            m_foe_miss = name;
            log("fight: foe '" + name + "' not recognised" + (!foe.has_value() ? " - playing without knowing it" : ""));
        }
        return foe.has_value();
    }
    const bool cp_given = cp.has_value() && *cp != 0;
    const bool old_cp_given = foe_cp.has_value() && *foe_cp != 0;
    if (foe.has_value() && foe->species == fresh.species && (!cp_given || !old_cp_given || std::abs(*cp - *foe_cp) <= 1)){
        foe_cp = cp_given ? cp : foe_cp;
        change.reset();
        read_at = clock;                        //  (it is still the one whose energy is counted)
        return true;                            //  the same foe
    }
    //  When the new one came in, at the earliest: when its name box was seen to change - or, when that was
    //  not noticed, when the one before it was last read there (its energy must not be counted too low).
    double came = change.has_value() ? *change : read_at;
    if (foe.has_value()){                       //  a new one: it comes in with a full HP bar
        foe_hp = 1.0;
        m_pending_foe.reset();
        m_foe_left.insert(foe->species, Left{energy_at(came), foe_e_ok, came});     //  (it keeps its energy)
    }else if (m_foe_left.isEmpty()){
        came = 0.0;                             //  (the first one of the battle: there from the start)
    }
    Left left = {0.0, true, std::nullopt};
    const auto before = m_foe_left.constFind(fresh.species);
    if (before != m_foe_left.constEnd()){
        left = *before;
    }
    if (left.clock.has_value() && came - *left.clock < FOE_BACK_SOON){
        came = *left.clock;                     //  (back that soon: a name that was misread - it never left)
    }
    foe_e_base = left.energy;
    foe_e_mark = came;
    foe_e_ok = left.ok;
    change.reset();
    has_threw = false;
    threw_had.reset();
    read_at = clock;
    fresh.hp = round_half_even(foe_hp * fresh.max_hp);
    fresh.hp_float = false;
    const bool seen_before = apply_seen(fresh);     //  (what it used before - in this battle or in earlier ones)
    foe = fresh;
    foe_cp = cp;
    log("fight: foe is " + fresh.label() + (cp_given ? QString(" (CP %1)").arg(*cp) : QString())
        + " - moves " + fresh.fast.name + " / " + names_of(fresh.charged, ", ")
        + (seen_before ? " (as seen before)" : ""));
    return true;
}

//  Put the charged attacks this species was seen to use at the front of the attacks of `foe_mon`: those of
//  this battle first, then those of earlier battles (the ones seen most often first). A Pokémon has two
//  at most: a guessed one makes room. True when that changed something.
bool Fight::apply_seen(Mon& foe_mon){
    QStringList seen_ids = foe_seen.value(foe_mon.species);
    const QStringList pool = Battle::species_charged(foe_mon.species);
    Counts before;
    if (const Counts* found = find_counts(known, foe_mon.species)){
        before = *found;
    }
    std::stable_sort(before.begin(), before.end(), [](const std::pair<QString, int>& a, const std::pair<QString, int>& b){
        return -a.second < -b.second;
    });
    for (const std::pair<QString, int>& item : before){
        if (pool.contains(item.first) && !seen_ids.contains(item.first)){
            seen_ids << item.first;
        }
    }
    if (seen_ids.isEmpty()){
        return false;
    }
    QStringList ids = seen_ids;
    for (const Move& m : foe_mon.charged){
        if (!seen_ids.contains(m.id)){
            ids << m.id;
        }
    }
    const qsizetype keep = std::min<qsizetype>(2, std::max<qsizetype>((qsizetype)foe_mon.charged.size(), seen_ids.size()));
    ids = ids.mid(0, keep);
    QStringList now;
    for (const Move& m : foe_mon.charged){
        now << m.id;
    }
    if (ids == now){
        return false;
    }
    std::vector<Move> moves;
    for (const QString& id : ids){
        Move move;
        Battle::move_by_id(id, move);
        moves.push_back(move);
    }
    foe_mon.charged = moves;
    return true;
}

//  The banner at the top was read: 'Mismagius used Dark Pulse!'. When it names the foe on the field and one
//  of the charged attacks its species can have, that attack is one of its two for sure.
std::optional<Move> Fight::foe_used(const QString& text){
    if (!foe.has_value() || text.isEmpty()){
        return {};
    }
    QString spaced = text;
    spaced.replace("!", "! ");
    const QStringList words = py_split(spaced);
    int at = -1;
    for (int i = 0; i < words.size(); i++){
        const QString& w = words[i];
        if (w.size() >= 3 && w.size() <= 5 && Nav::similarity(w.toLower(), "used") >= 0.75){
            at = i;
            break;
        }
    }
    if (at < 0 || at == 0 || at + 1 >= words.size()){
        return {};
    }
    static const QRegularExpression brackets("\\(.*?\\)");
    auto plain = [&](const QString& name){
        QString cleaned = name;
        cleaned.replace(brackets, " ");
        return Battle::norm(cleaned).remove(' ');
    };
    auto like = [&](const QString& name){           //  how well the words before 'used' fit this name
        double best = 0;
        bool first = true;
        for (int n = 1; n <= 3; n++){
            const QString heard = plain(words.mid(std::max(at - n, 0), at - std::max(at - n, 0)).join(' '));
            const double r = Nav::similarity(heard, plain(name));
            if (first || r > best){
                best = r;
                first = false;
            }
        }
        return best;
    };
    const double theirs = like(foe->name);
    double ours = 0;
    for (size_t c = 0; c < team.size(); c++){
        const double r = like(team[c].name);
        if (c == 0 || r > ours){
            ours = r;
        }
    }
    if (theirs < 0.75 || theirs <= ours){
        return {};                                  //  (ours, or not a name at all)
    }
    QStringList rest = words.mid(at + 1);
    int end = (int)rest.size() - 1;
    for (int i = 0; i < rest.size(); i++){
        if (rest[i].contains('!')){
            end = i;
            break;
        }
    }
    rest = rest.mid(0, end + 1).mid(0, 4);
    const QStringList pool = Battle::species_charged(foe->species);
    double best = 0.0;
    QString found;
    for (const QString& mid : pool){
        Move candidate;
        Battle::move_by_id(mid, candidate);
        const QString target = plain(candidate.name);
        for (int n = 1; n <= rest.size(); n++){
            const double r = Nav::similarity(plain(rest.mid(0, n).join(' ')), target);
            if (r > best){
                best = r;
                found = mid;
            }
        }
    }
    if (found.isEmpty() || best < 0.82){
        return {};
    }
    Move move;
    Battle::move_by_id(found, move);
    if (has_threw){                                 //  the attack that was thrown: its real cost comes off the energy
        const std::optional<double> had = threw_had;
        const double cost = threw_cost;
        has_threw = false;
        threw_had.reset();
        if (had.has_value() && move.energy > *had + 5){
            if (foe_e_ok){                          //  (it threw what it could not have had the energy for)
                log("fight: " + foe->label() + " threw " + move.name + QString(" (%1 energy) when it should have had %2 at most - its energy is not counted any more")
                    .arg(move.energy).arg((int)*had));
            }
            foe_e_ok = false;
        }else if (had.has_value() && move.energy > cost){
            foe_e_base = std::max(foe_e_base - (move.energy - cost), 0.0);
        }
    }
    if (m_first_pending.has_value() && *m_first_pending == foe->species){   //  which attack a species throws first
        m_first_pending.reset();
        add_count(counts_of(known, foe->species), "first:" + found);
        learned = true;
    }
    QStringList& seen_list = foe_seen[foe->species];
    if (seen_list.contains(found)){
        return move;
    }
    seen_list << found;
    while (seen_list.size() > 2){
        seen_list.removeFirst();                    //  (two at most: the newest count)
    }
    add_count(counts_of(known, foe->species), found);   //  (once a battle: for the battles to come)
    learned = true;
    QStringList guess;
    for (const Move& m : foe->charged){
        guess << m.name;
    }
    apply_seen(*foe);
    QStringList after;
    for (const Move& m : foe->charged){
        after << m.name;
    }
    QStringList sorted_guess = guess;
    QStringList sorted_after = after;
    sorted_guess.sort();
    sorted_after.sort();
    if (sorted_guess != sorted_after){              //  (not when only their order changed)
        log("fight: " + foe->label() + " used " + move.name + " - its charged attacks are taken to be "
            + after.join(", ") + " now (the guess was " + guess.join(", ") + ")");
    }
    return move;
}

//  The CP in my name box: correct who is on the field when it is somebody else than expected.
void Fight::set_active(std::optional<int> cp_in){
    if (!cp_in.has_value() || *cp_in == 0){
        return;
    }
    const int cp = *cp_in;
    if (std::abs(cp - me_mon().cp) <= 1){
        switch_seen.reset();                        //  (the one that was chosen is on the field: the tap counted)
        return;
    }
    for (size_t c = 0; c < team.size(); c++){
        Mon& m = team[c];
        if (dead.count(m.pos) == 0 && std::abs(m.cp - cp) <= 1 && m.pos != me){
            if (switch_seen.has_value() && seen - *switch_seen <= SWITCH_MISSED){
                //  Right after the switch question: our choice did not come in, the game chose the other one
                //  (the tap on its tile did not count) - nobody fainted.
                log("fight: " + m.label() + " is on the field, not " + me_mon().label() + " - the tap on the tile of "
                    + me_mon().label() + " did not count, the game chose");
                switch_seen.reset();
                enter(m.pos);
                named_at = seen;
                return;
            }
            const bool fainted = my_hp < FAINTED_BELOW || fainted_more();
            log("fight: " + m.label() + " is on the field (not " + me_mon().label() + (fainted ? ", which fainted)" : ")"));
            if (fainted){
                faint();
            }else if (m_came_mon == me){            //  (it never was on the field: the HP that was read meanwhile
                me_mon().hp = m_came_hp;            //  was not its own - it still has what it had before)
                me_mon().hp_float = m_came_hp_float;
            }
            const int reads = my_reads;
            enter(m.pos, !fainted);
            named_at = seen;                        //  (the name box says so, now)
            if (!fainted){
                my_reads = reads;                   //  (the bar that was read is the bar of this one)
            }
            return;
        }
    }
    for (size_t c = 0; c < team.size(); c++){
        Mon& m = team[c];
        if (dead.count(m.pos) != 0 && std::abs(m.cp - cp) <= 1 && balls_rows >= 2
            && 3 - balls_red == (int)dead.size() && seen - balls_at >= foe_every){
            //  The name box shows one that was taken for fainted, the Poké Balls agree with the count and have
            //  done so for a while: two were mixed up - the game had chosen the other one when the switch
            //  question ran out.
            log("fight: " + m.label() + " is on the field - it was " + me_mon().label() + " that fainted");
            dead.erase(m.pos);
            m.hp = m.max_hp;
            m.hp_float = m.max_hp_float;
            faint();
            enter(m.pos);
            named_at = seen;
            return;
        }
    }
}

//  Our HP bar was nearly empty and is full now: our Pokémon fainted and the next one came in.
void Fight::came_in(){
    std::vector<int> others;
    for (const Mon& m : team){
        if (dead.count(m.pos) == 0 && m.pos != me){
            others.push_back(m.pos);
        }
    }
    if (others.size() != 1){
        return;
    }
    if (seen - m_entered_at < JUST_CAME_IN && clock - m_entered_clock < JUST_CAME_IN_S){
        return;                                     //  (it came in a moment ago: the empty bar was its entrance)
    }
    log("fight: our HP bar is full again - " + team[(size_t)others[0]].label() + " is on the field (not "
        + me_mon().label() + ", which fainted)");
    faint();
    enter(others[0]);
}

//  The icons of a little game showed that our tap on a button threw the other attack: the names under the
//  buttons were read the wrong way round. Swap them.
void Fight::buttons_swapped(int mon_pos){
    if (mon_pos != me || me_mon().charged.size() != 2){
        return;
    }
    const Move* a = move_of(0);
    const Move* b = move_of(1);
    if (a == nullptr || b == nullptr){
        return;
    }
    const QString a_id = a->id;
    const QString b_id = b->id;
    const QString a_name = a->name;
    const QString b_name = b->name;
    button_slots[0] = b_id;
    button_slots[1] = a_id;
    labels_ok = true;
    need_labels = false;
    log("fight: the buttons are the other way round - " + b_name + " on the left, " + a_name + " on the right");
}

//  The texts under the buttons were read: which move is on which button.
void Fight::set_buttons(const QString& left, const QString& right){
    label_tries++;
    QStringList ids;
    for (const Move& m : me_mon().charged){
        ids << m.id;
    }
    std::optional<QString> found[2] = {find_mine(left), find_mine(right)};
    const bool first = found[0].has_value() && !found[0]->isEmpty();
    const bool second = found[1].has_value() && !found[1]->isEmpty();
    if (first && second && *found[0] == *found[1]){
        found[0].reset();
        found[1].reset();
    }
    const bool one = found[0].has_value() && !found[0]->isEmpty();
    const bool two = found[1].has_value() && !found[1]->isEmpty();
    if (ids.size() == 2){
        if (one && !two){
            for (const QString& id : ids){
                if (id != *found[0]){
                    found[1] = id;
                    break;
                }
            }
        }else if (two && !one){
            for (const QString& id : ids){
                if (id != *found[1]){
                    found[0] = id;
                    break;
                }
            }
        }
    }
    const bool both = found[0].has_value() && !found[0]->isEmpty() && found[1].has_value() && !found[1]->isEmpty();
    const bool single = found[0].has_value() && !found[0]->isEmpty();
    if ((ids.size() == 2 && both) || (ids.size() == 1 && single)){
        button_slots[0] = found[0];
        button_slots[1] = found[1];
        labels_ok = true;
        need_labels = false;
        QStringList names;
        for (const std::optional<QString>& s : found){
            if (s.has_value() && !s->isEmpty()){
                Move move;
                Battle::move_by_id(*s, move);
                names << move.name;
            }
        }
        log("fight: buttons are " + names.join(" / "));
    }else if (label_tries >= LABEL_TRIES){
        need_labels = false;                        //  keep the party order
        log("fight: the moves under the buttons were not read ('" + left + "' / '" + right + "') - party order");
    }
}

//  Which of our charged moves is named in a text (a hint like 'Super effective' may stand next to the
//  name, and a letter may be misread).
std::optional<QString> Fight::find_mine(const QString& text) const{
    const QStringList words = Battle::norm(text).split(' ', Qt::SkipEmptyParts);
    double best = 0.0;
    QString found;
    for (const Move& m : me_mon().charged){
        const QString target = Battle::norm(m.name);
        const int n = (int)target.split(' ', Qt::SkipEmptyParts).size();
        const int last = std::max((int)words.size() - n + 1, 0);
        for (int i = 0; i < last; i++){
            const double r = Nav::similarity(words.mid(i, n).join(' '), target);
            if (r > best){
                best = r;
                found = m.id;
            }
        }
    }
    if (best >= 0.8){
        return found;
    }
    return {};
}

//  The Move under a button (the party order when the labels are not known).
const Move* Fight::move_of(int button) const{
    const std::optional<QString>& id = button_slots[button];
    const std::vector<Move>& charged = me_mon().charged;
    if (id.has_value() && !id->isEmpty()){
        for (const Move& m : charged){
            if (m.id == *id){
                return &m;
            }
        }
        return nullptr;
    }
    return button < (int)charged.size() ? &charged[(size_t)button] : nullptr;
}

//  Without labels: when only one button is lit it is the cheaper move.
void Fight::calibrate(){
    if (labels_ok || (int)lit[0] + (int)lit[1] != 1 || me_mon().charged.size() != 2){
        return;
    }
    const Move& a = me_mon().charged[0];
    const Move& b = me_mon().charged[1];
    if (a.energy == b.energy){
        return;
    }
    const Move& cheap = a.energy < b.energy ? a : b;
    const Move& dear = a.energy < b.energy ? b : a;
    const int which = lit[0] ? 0 : 1;
    const Move* under = move_of(which);
    if (under != nullptr && under->id == dear.id){
        button_slots[which] = cheap.id;
        button_slots[1 - which] = dear.id;
        log(QString("fight: only the %1 button is lit, so it is the cheaper %2").arg(which == 0 ? "left" : "right", cheap.name));
    }
}

//  At least this much energy: the dearest move whose button is lit.
int Fight::energy() const{
    int best = 0;
    bool any = false;
    for (int i = 0; i < 2; i++){
        const Move* m = move_of(i);
        if (m != nullptr && lit[i]){
            if (!any || m->energy > best){
                best = m->energy;
            }
            any = true;
        }
    }
    return any ? best : 0;
}


//  ---------------------------------------------------------------------
//  What to do
//  ---------------------------------------------------------------------

Thrown Fight::thrown(int button, const Move& move, const QString& why){
    throws++;
    lit[0] = false;                                 //  (spent: the next picture shows what is lit now)
    lit[1] = false;
    return {button, move, why};
}

//  (button, Move, why) of the charged attack to throw now, none to go on with the fast attack.
std::optional<Thrown> Fight::throw_now(){
    if (!lit[0] && !lit[1]){
        return {};
    }
    std::vector<std::pair<int, Move>> lit_moves;
    for (int i = 0; i < 2; i++){
        const Move* m = move_of(i);
        if (lit[i] && m != nullptr){
            lit_moves.emplace_back(i, *m);
        }
    }
    if (lit_moves.empty()){
        return {};
    }
    if (!foe.has_value()){                          //  (foe unknown) the move with the most damage per energy
        size_t best = 0;
        for (size_t c = 1; c < lit_moves.size(); c++){
            const Move& x = lit_moves[c].second;
            const Move& y = lit_moves[best].second;
            if (x.power / (double)std::max(x.energy, 1) > y.power / (double)std::max(y.energy, 1)){
                best = c;
            }
        }
        const Move& m = lit_moves[best].second;
        return thrown(lit_moves[best].first, m, m.name + " (foe not known)");
    }
    me_mon().energy = energy();
    const Battle::Choice choice = Battle::pick_charged(me_mon(), *foe, energy(), foe_shields, (double)foe->hp);
    if (!choice.has_move){
        if (!going_down()){
            return {};
        }
        //  The plan was to go on with the fast attack (or to save up for the dearer move), but we will not
        //  live to see it: energy that is not used is lost, and even an attack that is shielded costs the
        //  foe a shield - the next one of ours is glad of that.
        size_t best = 0;
        for (size_t c = 1; c < lit_moves.size(); c++){
            const int dx = Battle::damage(lit_moves[c].second, me_mon(), *foe);
            const int dy = Battle::damage(lit_moves[best].second, me_mon(), *foe);
            if (dx > dy || (dx == dy && -lit_moves[c].second.energy > -lit_moves[best].second.energy)){
                best = c;
            }
        }
        const Move& m = lit_moves[best].second;
        return thrown(lit_moves[best].first, m, m.name + " before we go down (our HP is " + percent(my_hp) + ")");
    }
    for (const std::pair<int, Move>& item : lit_moves){
        if (item.second.id == choice.move.id){
            return thrown(item.first, choice.move, choice.reason);
        }
    }
    //  The picked move is not on a lit button. When it costs no more than one that is lit, it is ready too
    //  (the energy is the same for both): its button was not seen lit on this picture. Throw it there - the
    //  fast attacks are tapped on that button anyway, a tap on the other one would race them.
    if (labels_ok){
        int most = lit_moves[0].second.energy;
        for (const std::pair<int, Move>& item : lit_moves){
            most = std::max(most, item.second.energy);
        }
        for (int i = 0; i < 2; i++){
            const Move* m = move_of(i);
            if (m != nullptr && m->id == choice.move.id && choice.move.energy <= most){
                return thrown(i, choice.move, lit_moves.size() == 1
                    ? choice.reason + " (ready: it costs no more than " + lit_moves[0].second.name + ")"
                    : choice.reason);
            }
        }
    }
    //  The picked move is not on a lit button (labels not read, the buttons may be the other way round).
    size_t best = 0;
    for (size_t c = 1; c < lit_moves.size(); c++){
        if (lit_moves[c].second.energy > lit_moves[best].second.energy){
            best = c;
        }
    }
    const Move& m = lit_moves[best].second;
    return thrown(lit_moves[best].first, m, m.name + " (lit) instead of " + choice.move.name);
}

//  (button, Move): the charged attack that is thrown the moment its button lights up, none when there is
//  no such attack right now. Only when it is known which attack is on which button.
std::optional<Aim> Fight::aim(){
    Mon& mon = me_mon();
    const bool both_slots = button_slots[0].has_value() && !button_slots[0]->isEmpty() && button_slots[1].has_value() && !button_slots[1]->isEmpty();
    if (mon.charged.size() != 2 || !(labels_ok || both_slots)){
        return {};
    }
    AimKey key;
    key.pos = mon.pos;
    key.species = foe.has_value() ? foe->species : QString();
    key.my_hp = (int)(my_hp * 50);
    key.foe_hp = (int)(foe_hp * 50);
    key.foe_shields = foe_shields;
    key.button_slots[0] = button_slots[0];
    key.button_slots[1] = button_slots[1];
    if (m_aim_has_key && key == m_aim_key){
        return m_aim_result;
    }
    std::vector<std::pair<const Move*, int>> moves = {{move_of(0), 0}, {move_of(1), 1}};
    std::optional<Aim> res;
    if (moves[0].first != nullptr && moves[1].first != nullptr){
        const int first = std::min(moves[0].first->energy, moves[1].first->energy);    //  (what lights up first)
        std::vector<std::pair<const Move*, int>> early;
        for (const std::pair<const Move*, int>& item : moves){
            if (item.first->energy == first){
                early.push_back(item);
            }
        }
        if (!foe.has_value()){                      //  (foe unknown: throw() takes what is lit, see there)
            size_t best = 0;
            for (size_t c = 1; c < early.size(); c++){
                const Move& x = *early[c].first;
                const Move& y = *early[best].first;
                if (x.power / (double)std::max(x.energy, 1) > y.power / (double)std::max(y.energy, 1)){
                    best = c;
                }
            }
            res = Aim{early[best].second, *early[best].first};
        }else{
            const int energy_before = mon.energy;
            std::vector<int> costs = {moves[0].first->energy, moves[1].first->energy};
            std::sort(costs.begin(), costs.end());
            costs.erase(std::unique(costs.begin(), costs.end()), costs.end());
            for (const int cost : costs){
                mon.energy = cost;
                const Battle::Choice pick = Battle::pick_charged(mon, *foe, cost, foe_shields, (double)foe->hp);
                if (!pick.has_move){
                    continue;                       //  (it saves up - for the dearer one, perhaps)
                }
                if (pick.move.energy == cost){      //  (thrown the moment it is ready)
                    for (const std::pair<const Move*, int>& item : moves){
                        if (item.first->id == pick.move.id){
                            res = Aim{item.second, *item.first};
                            break;
                        }
                    }
                }
                break;                              //  (a cheaper one, thrown only now: not to be thrown early)
            }
            mon.energy = energy_before;
            if (!res.has_value() && going_down()){  //  (anything that lights up, see throw())
                size_t best = 0;
                for (size_t c = 1; c < early.size(); c++){
                    if (Battle::damage(*early[c].first, mon, *foe) > Battle::damage(*early[best].first, mon, *foe)){
                        best = c;
                    }
                }
                res = Aim{early[best].second, *early[best].first};
            }
        }
    }
    m_aim_has_key = true;
    m_aim_key = key;
    m_aim_result = res;
    return res;
}


//  ---------------------------------------------------------------------
//  Giving up
//  ---------------------------------------------------------------------

//  An attack is coming and we have no shield. (true, why) when that ends the fight: this is our last
//  Pokémon, its HP was read from its own bar and the foe's hardest charged attack knocks it out.
std::pair<bool, QString> Fight::doomed(){
    const std::pair<bool, QString> lost = doomed_inner();
    return lost.first ? std::make_pair(true, lost.second) : std::make_pair(false, QString());
}

//  Why doomed() says that the fight is not over (for the log; '' when it is over).
QString Fight::fights_on(){
    const std::pair<bool, QString> lost = doomed_inner();
    return lost.first ? QString() : lost.second;
}

std::pair<bool, QString> Fight::doomed_inner(){
    if (!foe.has_value()){
        return {false, "the foe is not known"};
    }
    if (my_shields > 0){
        return {false, QString("we have %1 shield(s) left by our count").arg(my_shields)};
    }
    if (alive().size() != 1){
        return {false, QString("%1 of ours can still fight by our count").arg(alive().size())};
    }
    if (!hp_sure()){
        return {false, QString("the HP of %1 is not sure (read from its bar %2 time(s), last %3, taken to be %4)")
            .arg(me_mon().label()).arg(my_reads).arg(percent(my_read), percent(my_hp))};
    }
    //  Which attack comes is not known: only when EVERY attack the foe can pay for knocks ours out is the
    //  fight over. In doubt the fight goes on.
    const std::vector<Move> moves = Battle::can_throw(*foe, threw_with());
    std::vector<std::pair<int, QString>> hits;
    for (const Move& m : moves){
        hits.emplace_back(Battle::damage(m, *foe, me_mon()), m.name);
    }
    std::sort(hits.begin(), hits.end());
    int dmg = hits.front().first;
    QString name = hits.front().second;
    if (dmg < me_mon().hp){
        return {false, foe->label() + "'s " + name + QString(" does %1, ").arg(dmg) + me_mon().label() + " has " + hp_text(me_mon()) + " HP"
            + (moves.size() < foe->charged.size() ? " (its other attack costs more energy than it can have)" : "")};
    }
    dmg = hits.back().first;
    name = hits.back().second;
    return {true, me_mon().label() + " is our last Pokémon, it has " + hp_text(me_mon()) + " HP and no shield, and "
        + foe->label() + "'s " + name + QString(" does %1").arg(dmg)
        + (hits.size() > 1 ? " (and " + hits.front().second + QString(" %1)").arg(hits.front().first) : QString())};
}

//  Is our HP known well enough to give a fight up on it?
bool Fight::hp_sure() const{
    return my_reads >= 2 && std::abs(my_read - my_hp) <= 0.10;
}

//  The plain fight, our last Pokémon against `foes` of theirs that can still fight. (true, why) when
//  there are two or more of them and ours loses the duel it is in.
std::pair<bool, QString> Fight::hopeless(int foes){
    if (foes < 2 || !foe.has_value() || alive().size() != 1 || !hp_sure()){
        return {false, QString()};
    }
    Mon mine = me_mon();
    Mon theirs = *foe;
    int next_cost = 100;
    bool any = false;
    const int have = energy();
    for (const Move& m : mine.charged){
        if (m.energy > have){
            if (!any || m.energy - 1 < next_cost){
                next_cost = m.energy - 1;
            }
            any = true;
        }
    }
    mine.energy = any ? next_cost : 100;
    theirs.energy = 0;
    const std::pair<double, double> result = Battle::simulate(mine, theirs, my_shields, foe_shields);
    if (result.first > 0){
        return {false, QString()};
    }
    return {true, me_mon().label() + " (" + percent(my_hp) + " HP) is our last Pok\u00e9mon and loses to " + foe->label()
        + " (" + percent(foe_hp) + " HP, it would keep " + percent(result.second) + QString("), and %1 more ").arg(foes - 1)
        + (foes == 2 ? "is" : "are") + " waiting"};
}

//  Are we about to faint while the foe is not?
bool Fight::going_down() const{
    if (!foe.has_value()){
        return false;
    }
    const double low = std::max(GOING_DOWN_HP * me_mon().max_hp, (double)(GOING_DOWN_FAST * Battle::damage(foe->fast, *foe, me_mon())));
    return me_mon().hp <= low && foe->hp > 2 * Battle::damage(me_mon().fast, me_mon(), *foe);
}

//  The charged attack the foe on the field will throw first, when earlier battles say so clearly.
std::optional<Predicted> Fight::predict_first() const{
    if (!foe.has_value() || m_threw_species.count(foe->species) != 0){
        return {};
    }
    Counts firsts;
    int total = 0;
    if (const Counts* found = find_counts(known, foe->species)){
        for (const std::pair<QString, int>& item : *found){
            if (item.first.startsWith("first:")){
                firsts.emplace_back(item.first.mid(6), item.second);
                total += item.second;
            }
        }
    }
    if (total < PREDICT_MIN){
        return {};
    }
    size_t best = 0;
    for (size_t c = 1; c < firsts.size(); c++){
        if (firsts[c].second > firsts[best].second){
            best = c;
        }
    }
    const QString mid = firsts[best].first;
    const int n = firsts[best].second;
    if (n < PREDICT_SHARE * total){
        return {};
    }
    const Move* move = nullptr;
    for (const Move& m : foe->charged){
        if (m.id == mid){
            move = &m;
            break;
        }
    }
    if (move == nullptr){
        return {};
    }
    bool can = false;
    for (const Move& m : Battle::can_throw(*foe, foe_energy())){
        if (m.id == move->id){
            can = true;
        }
    }
    if (!can){
        return {};
    }
    return Predicted{*move, n, total};
}

//  The question 'Attack incoming! Use a Protect Shield?': (use it, why).
std::pair<bool, QString> Fight::shield(std::optional<int> foes, bool ready){
    if (my_shields <= 0){
        return {false, "no shields left"};
    }
    int left = 0;
    for (const Mon& m : team){
        if (dead.count(m.pos) == 0){
            left++;
        }
    }
    const int mine = std::max(left, 1);
    const std::optional<Predicted> guess = predict_first();
    const Battle::Verdict verdict = Battle::use_shield(
        foe.has_value() ? &*foe : nullptr, me_mon(), my_shields, me_mon().hp, mine, foes, ready,
        guess.has_value() ? &guess->move : nullptr, foe_energy()
    );
    QString why = verdict.reason;
    if (guess.has_value()){
        why = "predicted " + guess->move.name + " (the first attack of " + foe->label()
            + QString(" in %1 of %2 earlier battles) - ").arg(guess->count).arg(guess->total) + why;
    }
    if (verdict.use){
        my_shields--;
    }
    return {verdict.use, why};
}

//  The Pokémon on the field fainted.
void Fight::faint(){
    dead.insert(me_mon().pos);
    me_mon().hp = 0;
    me_mon().hp_float = false;
    my_hp = 0.0;
}

std::vector<int> Fight::alive() const{
    std::vector<int> out;
    for (const Mon& m : team){
        if (dead.count(m.pos) == 0 && m.hp > 0){
            out.push_back(m.pos);
        }
    }
    return out;
}

//  'Switch in a new Pokémon?' tiles: [(cp, x)] left to right as read on the pop-up. Every Pokémon that is
//  left is a choice all the same (the tiles stand in party order), so the best one is taken, read or not.
Switched Fight::switch_in(const std::vector<std::pair<int, int>>& tiles, std::optional<int> shown_n){
    const int fainted = me;
    faint();
    std::vector<int> left = alive();
    if (shown_n.has_value() && *shown_n != 0 && *shown_n > (int)left.size()){
        //  The question shows more Pokémon than our count says are left: one was taken for fainted that is
        //  not (a missed switch, a name box read during the change). The tiles are the truth.
        std::vector<int> back;
        for (const Mon& m : team){
            if (dead.count(m.pos) != 0 && m.pos != me && (int)back.size() < *shown_n - (int)left.size()){
                back.push_back(m.pos);
            }
        }
        for (const int pos : back){
            dead.erase(pos);
        }
        if (!back.empty()){
            QStringList labels;
            for (const int pos : back){
                labels << team[(size_t)pos].label();
            }
            log(QString("fight: the question shows %1 Pokémon - ").arg(*shown_n) + labels.join(", ") + " did not faint after all");
        }
        left = alive();
    }
    if (left.empty()){
        return {std::nullopt, std::nullopt, "nobody left"};
    }
    std::vector<std::pair<int, int>> shown;         //  (tile index, party place) for tiles whose CP is a Pokémon of ours
    for (size_t i = 0; i < tiles.size(); i++){
        for (const int pos : left){
            bool taken = false;
            for (const std::pair<int, int>& s : shown){
                if (s.second == pos){
                    taken = true;
                }
            }
            if (std::abs(team[(size_t)pos].cp - tiles[i].first) <= 1 && !taken){
                shown.emplace_back((int)i, pos);
                break;
            }
        }
    }
    if (shown.empty() && tiles.size() == left.size()){      //  no CP read, but as many tiles as choices: in party order
        for (size_t i = 0; i < tiles.size(); i++){
            shown.emplace_back((int)i, left[i]);
        }
    }
    int best = left[0];
    QString why;
    if (foe.has_value()){
        std::vector<Mon> candidates;
        for (const int pos : left){
            candidates.push_back(team[(size_t)pos]);
        }
        const std::pair<int, double> picked = Battle::best_switch(candidates, *foe, my_shields, foe_shields);
        if (picked.first >= 0){
            best = left[(size_t)picked.first];
        }
        why = team[(size_t)best].label() + " fares best against " + foe->label() + " (score " + signed_two(picked.second);
    }else{
        why = "foe not known, taking " + team[(size_t)left[0]].label() + " (";
    }
    std::optional<int> idx;
    for (const std::pair<int, int>& s : shown){
        if (s.second == best){
            idx = s.first;
            break;
        }
    }
    const bool by_cp = idx.has_value() && std::abs(tiles[(size_t)*idx].first - team[(size_t)best].cp) <= 1;
    why += (why.endsWith("(") ? QString() : QString(", ")) + (by_cp ? "by CP)" : "by party order)");
    int place = 0;
    for (size_t c = 0; c < left.size(); c++){
        if (left[c] == best){
            place = (int)c;
        }
    }
    tile = {place, (int)left.size()};
    if (left.size() < 2 && team.size() == 3){
        //  The game asks only when two are left, so two tiles are on the screen whatever our count says: the
        //  two that did not just faint, in party order.
        int where = 0;
        int index = 0;
        for (const Mon& m : team){
            if (m.pos != fainted){
                if (m.pos == best){
                    where = index;
                }
                index++;
            }
        }
        tile = {where, 2};
    }
    switch_seen = seen;
    enter(best);
    return {idx, best, why};
}

void Fight::enter(int mon, bool keep_hp){
    Mon& m = team[(size_t)mon];
    m_came_mon = mon;
    m_came_hp = m.hp;
    m_came_hp_float = m.hp_float;
    me = mon;
    m_entered_at = seen;
    m_entered_clock = clock;
    my_reads = 0;
    m_aim_has_key = false;
    m_aim_result.reset();
    if (!keep_hp){
        my_hp = m.hp_frac();
    }
    button_slots[0].reset();
    button_slots[1].reset();
    labels_ok = false;
    need_labels = true;
    label_tries = 0;
    lit[0] = false;
    lit[1] = false;
    m_pending_me.reset();
}


//  ---------------------------------------------------------------------
//  The test: the fights of battle_fight.py
//  ---------------------------------------------------------------------

namespace{

QJsonValue number_or_null(const std::optional<double>& value){
    return value.has_value() ? QJsonValue(*value) : QJsonValue(QJsonValue::Null);
}
QJsonValue string_or_null(const std::optional<QString>& value){
    return value.has_value() ? QJsonValue(*value) : QJsonValue(QJsonValue::Null);
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

QString compact(const QJsonValue& value){
    return QString::fromUtf8(QJsonDocument(QJsonArray{value}).toJson(QJsonDocument::Compact)).mid(1).chopped(1);
}

std::optional<double> optional_number(const QJsonValue& value){
    if (value.isNull() || value.isUndefined()){
        return {};
    }
    return value.toDouble();
}
std::optional<int> optional_int(const QJsonValue& value){
    if (value.isNull() || value.isUndefined()){
        return {};
    }
    return value.toInt();
}

Features features_of(const QJsonObject& f){
    Features out;
    out.hud = f.value("hud").toBool();
    out.white = f.value("white").toBool();
    out.versus = f.value("versus").toBool();
    out.ring = f.value("ring").toBool();
    out.result = f.value("result").toBool();
    out.done = f.value("done").toBool();
    const QJsonArray hp = f.value("hp").toArray();
    out.hp_me = optional_number(hp.at(0));
    out.hp_foe = optional_number(hp.at(1));
    const QJsonObject shields = f.value("shields").toObject();
    out.shields_me = optional_int(shields.value("me"));
    out.shields_foe = optional_int(shields.value("foe"));
    const QJsonArray ready = f.value("ready").toArray();
    out.lit[0] = ready.at(0).toBool();
    out.lit[1] = ready.at(1).toBool();
    const QJsonObject balls = f.value("balls").toObject();
    if (balls.contains("me")){
        const QJsonArray me = balls.value("me").toArray();
        out.has_balls = true;
        out.balls[0] = me.at(0).toInt();
        out.balls[1] = me.at(1).toInt();
    }
    return out;
}

bool mon_of(const QJsonObject& spec, Mon& out){
    Battle::MonSpec s;
    s.species = spec.value("species").toString();
    s.shadow = spec.value("shadow").toBool();
    s.pos = spec.value("pos").toInt();
    s.level = spec.value("level").toDouble();
    std::vector<int> ivs;
    for (const QJsonValue& v : spec.value("ivs").toArray()){
        ivs.push_back(v.toInt());
    }
    s.ivs = ivs;
    s.fast = spec.value("fast").toString();
    QStringList charged;
    for (const QJsonValue& v : spec.value("charged").toArray()){
        charged << v.toString();
    }
    s.charged = charged;
    if (!Battle::make_mon(s, out)){
        return false;
    }
    out.atk = spec.value("atk").toDouble();
    out.dfn = spec.value("dfn").toDouble();
    out.max_hp = spec.value("max_hp").toDouble();
    out.hp = spec.value("hp").toDouble();
    out.cp = spec.value("cp").toInt();
    out.hp_float = spec.value("hp_float").toBool();
    out.max_hp_float = spec.value("max_hp_float").toBool();
    return true;
}

Known known_of(const QJsonArray& array){
    Known out;
    for (const QJsonValue& item : array){
        const QJsonArray pair = item.toArray();
        Counts counts;
        for (const QJsonValue& c : pair.at(1).toArray()){
            const QJsonArray kv = c.toArray();
            counts.emplace_back(kv.at(0).toString(), kv.at(1).toInt());
        }
        out.emplace_back(pair.at(0).toString(), counts);
    }
    return out;
}

QJsonArray known_json(const Known& known){
    QJsonArray out;
    for (const std::pair<QString, Counts>& item : known){
        QJsonArray counts;
        for (const std::pair<QString, int>& c : item.second){
            counts.append(QJsonArray{c.first, c.second});
        }
        out.append(QJsonArray{item.first, counts});
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

QJsonArray snap(const Fight& f){
    const Mon& me = f.me_mon();
    QJsonArray dead;
    for (const int pos : f.dead){
        dead.append(pos);
    }
    QJsonArray charged;
    if (f.foe.has_value()){
        for (const Move& m : f.foe->charged){
            charged.append(m.id);
        }
    }
    return QJsonArray{
        me.pos, f.my_hp, f.foe_hp, f.my_shields, f.foe_shields, f.lit[0], f.lit[1],
        string_or_null(f.button_slots[0]), string_or_null(f.button_slots[1]), f.labels_ok, f.need_labels, f.label_tries,
        f.foe.has_value() ? QJsonValue(f.foe->species) : QJsonValue(QJsonValue::Null),
        f.foe_cp.has_value() ? QJsonValue(*f.foe_cp) : QJsonValue(QJsonValue::Null),
        f.foe.has_value() ? QJsonValue(charged) : QJsonValue(QJsonValue::Null),
        f.foe.has_value() ? QJsonValue(f.foe->hp) : QJsonValue(QJsonValue::Null),
        me.hp, dead, f.throws, f.clock, f.tile.first, f.tile.second, f.learned, (double)f.since_foe, f.energy(),
        number_or_null(f.foe_energy()),
    };
}

QJsonObject internals(const Fight& f){
    QJsonObject out;
    out.insert("foe_e", QJsonArray{f.foe_e_base, f.foe_e_mark});
    out.insert("foe_e_ok", f.foe_e_ok);
    out.insert("change", number_or_null(f.change));
    out.insert("read_at", f.read_at);
    out.insert("threw", f.has_threw ? QJsonValue(QJsonArray{number_or_null(f.threw_had), f.threw_cost}) : QJsonValue(QJsonValue::Null));
    out.insert("balls", QJsonArray{f.balls_red, f.balls_rows});
    out.insert("seen", (double)f.seen);
    out.insert("balls_at", (double)f.balls_at);
    out.insert("named_at", (double)f.named_at);
    out.insert("my_reads", f.my_reads);
    out.insert("my_read", f.my_read);
    out.insert("switch_seen", f.switch_seen.has_value() ? QJsonValue((double)*f.switch_seen) : QJsonValue(QJsonValue::Null));
    out.insert("known", known_json(f.known));
    QStringList species = f.foe_seen.keys();
    species.sort();
    QJsonArray foe_seen;
    for (const QString& s : species){
        foe_seen.append(QJsonArray{s, strings_json(f.foe_seen.value(s))});
    }
    out.insert("foe_seen", foe_seen);
    QJsonArray alive;
    for (const int pos : f.alive()){
        alive.append(pos);
    }
    out.insert("alive", alive);
    return out;
}

//  What the port answers to one call of the file, as the file has it; "known" is false for a call that
//  this port has not got.
QJsonValue answer(Fight& fight, const QString& call, const QJsonArray& args, const std::vector<Features>& feats,
    bool& known){
    known = true;
    if (call == "see"){
        fight.see(feats[(size_t)args.at(0).toInt()]);
        return QJsonValue(QJsonValue::Null);
    }
    if (call == "set_foe"){
        return fight.set_foe(args.at(0).toString(), optional_int(args.at(1)));
    }
    if (call == "set_active"){
        fight.set_active(optional_int(args.at(0)));
        return QJsonValue(QJsonValue::Null);
    }
    if (call == "set_buttons"){
        fight.set_buttons(args.at(0).toString(), args.at(1).toString());
        return QJsonValue(QJsonValue::Null);
    }
    if (call == "throw"){
        const std::optional<Thrown> t = fight.throw_now();
        return t.has_value() ? QJsonValue(QJsonArray{t->button, t->move.id, t->why}) : QJsonValue(QJsonValue::Null);
    }
    if (call == "aim"){
        const std::optional<Aim> a = fight.aim();
        return a.has_value() ? QJsonValue(QJsonArray{a->button, a->move.id}) : QJsonValue(QJsonValue::Null);
    }
    if (call == "shield"){
        const std::pair<bool, QString> r = fight.shield(optional_int(args.at(0)), args.at(1).toBool());
        return QJsonArray{r.first, r.second};
    }
    if (call == "foe_threw"){
        fight.foe_threw(args.at(0).toBool());
        return QJsonValue(QJsonValue::Null);
    }
    if (call == "foe_used"){
        const std::optional<Move> m = fight.foe_used(args.at(0).toString());
        return m.has_value() ? QJsonValue(m->id) : QJsonValue(QJsonValue::Null);
    }
    if (call == "fought"){
        fight.fought(args.at(0).toDouble());
        return QJsonValue(QJsonValue::Null);
    }
    if (call == "read_names"){
        fight.read_names(args.at(0).isNull() ? QString() : args.at(0).toString());
        return QJsonValue(QJsonValue::Null);
    }
    if (call == "buttons_swapped"){
        fight.buttons_swapped(args.at(0).toInt());
        return QJsonValue(QJsonValue::Null);
    }
    if (call == "switch"){
        std::vector<std::pair<int, int>> tiles;
        for (const QJsonValue& t : args.at(0).toArray()){
            tiles.emplace_back(t.toArray().at(0).toInt(), t.toArray().at(1).toInt());
        }
        const Switched r = fight.switch_in(tiles, optional_int(args.at(1)));
        return QJsonArray{r.tile.has_value() ? QJsonValue(*r.tile) : QJsonValue(QJsonValue::Null),
            r.mon.has_value() ? QJsonValue(*r.mon) : QJsonValue(QJsonValue::Null), r.why};
    }
    if (call == "doomed"){
        const std::pair<bool, QString> r = fight.doomed();
        return QJsonArray{r.first, r.second};
    }
    if (call == "fights_on"){
        return fight.fights_on();
    }
    if (call == "hopeless"){
        const std::pair<bool, QString> r = fight.hopeless(args.at(0).toInt());
        return QJsonArray{r.first, r.second};
    }
    if (call == "predict_first"){
        const std::optional<Predicted> p = fight.predict_first();
        return p.has_value() ? QJsonValue(QJsonArray{p->move.id, p->count, p->total}) : QJsonValue(QJsonValue::Null);
    }
    if (call == "misc"){
        QJsonArray moves;
        for (int i = 0; i < 2; i++){
            const Move* m = fight.move_of(i);
            moves.append(m != nullptr ? QJsonValue(m->id) : QJsonValue(QJsonValue::Null));
        }
        QJsonArray alive;
        for (const int pos : fight.alive()){
            alive.append(pos);
        }
        return QJsonArray{fight.energy(), number_or_null(fight.foe_energy()), number_or_null(fight.threw_with()),
            fight.foe_due(), moves, alive};
    }
    if (call == "faint"){
        fight.faint();
        return QJsonValue(QJsonValue::Null);
    }
    if (call == "state"){
        return state(features_of(args.at(0).toObject()));
    }
    known = false;
    return QJsonValue();
}

}   //  namespace

int run_fight_checks(const QString& golden, const QString& data, QStringList& report){
    QString error;
    if (!Battle::load_data(data, error)){
        report << "FAILED: " + error;
        return 1;
    }
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the fights of battle_fight.py are not there: " + golden;
        return 1;
    }
    const QByteArray json = qUncompress(file.readAll());
    const QJsonObject root = QJsonDocument::fromJson(json).object();
    const QJsonArray fights = root.value("fights").toArray();
    if (fights.isEmpty()){
        report << "FAILED: the file of fights of battle_fight.py is empty or not right: " + golden;
        return 1;
    }
    std::vector<Features> feats;
    for (const QJsonValue& f : root.value("feats").toArray()){
        feats.push_back(features_of(f.toObject()));
    }

    int wrong = 0;
    int steps_done = 0;
    for (qsizetype index = 0; index < fights.size(); index++){
        const QJsonObject fight_json = fights[index].toObject();
        const QJsonObject start = fight_json.value("start").toObject();
        std::vector<Mon> team;
        bool fine = true;
        for (const QJsonValue& m : start.value("team").toArray()){
            Mon mon;
            fine = fine && mon_of(m.toObject(), mon);
            team.push_back(mon);
        }
        if (!fine){
            wrong++;
            report << QString("FAILED: fight %1: a Pok\u00e9mon of the team is not in the data").arg(index);
            continue;
        }
        QStringList logs;
        Fight fight(team, [&logs](const QString& line){ logs << line; }, known_of(start.value("known").toArray()));
        fight.foe_every = start.value("foe_every").toInt();
        fight.shields_back = start.value("shields_back").toInt();
        const QJsonArray steps = fight_json.value("steps").toArray();
        bool broken = false;
        for (qsizetype c = 0; c < steps.size() && !broken; c++){
            const QJsonObject step = steps[c].toObject();
            const QString call = step.value("call").toString();
            logs.clear();
            bool known = false;
            const QJsonValue got = answer(fight, call, step.value("args").toArray(), feats, known);
            const QJsonValue got_log = strings_json(logs);
            const QJsonValue got_state = snap(fight);
            steps_done++;
            const char* what = nullptr;
            QJsonValue expected;
            QJsonValue shown;
            if (!known){
                what = "not in the port";
            }else if (!same(got, step.value("out"))){
                what = "the answer";
                expected = step.value("out");
                shown = got;
            }else if (!same(got_log, step.value("log"))){
                what = "the log";
                expected = step.value("log");
                shown = got_log;
            }else if (!same(got_state, step.value("st"))){
                what = "the state after it";
                expected = step.value("st");
                shown = got_state;
            }
            if (what != nullptr){
                wrong++;
                broken = true;
                if (wrong <= 12){
                    report << QString("FAILED: fight %1, step %2, %3 %4: %5 differs: battle_fight.py says %6, the port says %7")
                        .arg(index).arg(c).arg(call, compact(step.value("args")).left(200), what,
                            compact(expected).left(400), compact(shown).left(400));
                }
            }
        }
        if (!broken && !same(internals(fight), fight_json.value("final"))){
            wrong++;
            if (wrong <= 12){
                report << QString("FAILED: fight %1, at the end: battle_fight.py says %2, the port says %3").arg(index)
                    .arg(compact(fight_json.value("final")).left(500), compact(internals(fight)).left(500));
            }
        }
    }
    report << QString("%1 fights of battle_fight.py (%2 calls): %3 differ").arg(fights.size()).arg(steps_done).arg(wrong);
    return wrong;
}


}
}
}
}
