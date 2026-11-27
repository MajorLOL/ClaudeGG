/*  Claude GG Pokemon GO Fight (the state of one GO Battle League fight)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port to C++ of Mobile/battle_fight.py (issue #30): what was seen in, what
 *  to do out. No phone, no OCR and no picture in here: the pictures of the
 *  fight are read elsewhere (battle_vision.py) into "features" (the HP bars,
 *  the shield icons, the buttons that are lit), the names are read by OCR, and
 *  this class keeps the state of the fight and takes the decisions with the
 *  rules of ClaudeGG_PokemonGoBattle.h: which charged attack to throw and when,
 *  whether to use a shield, who comes in after a faint, whether the fight is
 *  lost. What it cannot see it estimates (our energy from the lit buttons, the
 *  foe's moves from the ranking and from what the banners say it used, the
 *  foe's energy from the time it has fought).
 *
 *  What it answers is what Fight of battle_fight.py answers, to the letter (the
 *  lines it logs too): Mobile/tools/make_fight_golden.py plays fights with the
 *  Python one (the features of four real recorded fights and made-up events
 *  of every kind) and writes every call with its answer and the state after
 *  it; run_fight_checks() plays the same calls on this port in every build
 *  (--mobile-test).
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoFight_H
#define PokemonAutomation_ClaudeGG_PokemonGoFight_H

#include <functional>
#include <optional>
#include <set>
#include <utility>
#include <vector>
#include <QHash>
#include <QString>
#include <QStringList>
#include "ClaudeGG_PokemonGoBattle.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Fight{


//  What a picture of the fight shows (the features of battle_vision.py that the fight uses).
struct Features{
    bool hud = false;               //  the name boxes and buttons are on the screen
    bool white = false;
    bool versus = false;
    bool ring = false;              //  the countdown ring of a question
    bool result = false;
    bool done = false;
    std::optional<double> hp_me;    //  the HP bars as a part of the full bar
    std::optional<double> hp_foe;
    std::optional<int> shields_me;  //  the shield icons
    std::optional<int> shields_foe;
    bool lit[2] = {false, false};   //  the charged attack buttons that are lit
    bool has_balls = false;         //  the red and the grey Poké Balls of our name box
    int balls[2] = {0, 0};
};

//  'result', 'prompt', 'fight' or 'other': what a picture shows.
QString state(const Features& feat);


//  What the foe was seen to use in earlier battles: species -> (charged attack -> in how many battles;
//  "first:<attack>" -> in how many of them it was thrown first), each in the order they came.
typedef std::vector<std::pair<QString, int>> Counts;
typedef std::vector<std::pair<QString, Counts>> Known;

struct Thrown{
    int button = 0;
    Battle::Move move;
    QString why;
};
struct Aim{
    int button = 0;
    Battle::Move move;
};
struct Switched{
    std::optional<int> tile;                //  the index into the tiles
    std::optional<int> mon;                 //  the party place of the one that comes in
    QString why;
};
struct Predicted{
    Battle::Move move;
    int count = 0;
    int total = 0;
};


class Fight{
public:
    typedef std::function<void(const QString&)> Log;

    Fight(const std::vector<Battle::Mon>& team, Log log = Log(), Known known = Known());

    //  ---- what is seen
    void see(const Features& feat);
    bool foe_due() const;
    void read_names(const QString& side = QString());
    void fought(double seconds);
    std::optional<double> foe_energy() const;
    void foe_threw(bool sure = true);
    std::optional<double> threw_with() const;
    bool set_foe(const QString& name, std::optional<int> cp = {});
    std::optional<Battle::Move> foe_used(const QString& text);
    void set_active(std::optional<int> cp);
    void buttons_swapped(int mon_pos);
    void set_buttons(const QString& left, const QString& right);
    const Battle::Move* move_of(int button) const;
    int energy() const;

    //  ---- what to do
    std::optional<Thrown> throw_now();
    std::optional<Aim> aim();
    std::pair<bool, QString> doomed();
    QString fights_on();
    std::pair<bool, QString> hopeless(int foes);
    std::optional<Predicted> predict_first() const;
    std::pair<bool, QString> shield(std::optional<int> foes = {}, bool ready = false);
    void faint();
    std::vector<int> alive() const;                         //  party places
    Switched switch_in(const std::vector<std::pair<int, int>>& tiles, std::optional<int> shown_n = {});

    //  ---- the state (public as the state of the Python one is: the fight loop and the test read it)
    std::vector<Battle::Mon> team;
    Known known;
    bool learned = false;
    double clock = 0.0;
    int me = 0;                                             //  the party place of the one on the field
    std::optional<Battle::Mon> foe;
    int my_shields = 2;
    int foe_shields = 2;
    double my_hp = 1.0;
    double foe_hp = 1.0;
    bool lit[2] = {false, false};
    std::optional<QString> button_slots[2];
    bool labels_ok = false;
    std::optional<int> foe_cp;
    int foe_every = 3;
    long long since_foe = 1000000;
    bool need_labels = true;
    int label_tries = 0;
    std::set<int> dead;
    int throws = 0;
    int shields_back = 6;
    std::pair<int, int> tile = {0, 1};
    QHash<QString, QStringList> foe_seen;

    //  the rest of the Python object's state, for the test
    double foe_e_base = 0.0;
    double foe_e_mark = 0.0;
    bool foe_e_ok = true;
    std::optional<double> change;
    double read_at = 0.0;
    bool has_threw = false;
    std::optional<double> threw_had;
    double threw_cost = 0.0;
    int balls_red = 3;
    int balls_rows = 0;
    long long seen = 0;
    long long balls_at = 0;
    long long named_at = -1;
    int my_reads = 0;
    double my_read = 1.0;
    std::optional<long long> switch_seen;

    const Battle::Mon& me_mon() const{ return team[(size_t)me]; }
    Battle::Mon& me_mon(){ return team[(size_t)me]; }

private:
    struct Left{
        double energy;
        bool ok;
        std::optional<double> clock;
    };

    double believe(const QString& side, double old, std::optional<double> value);
    void see_balls(int red);
    bool fainted_more() const;
    void see_shields(std::optional<int> sh_me, std::optional<int> sh_foe);
    double energy_at(std::optional<double> at = {}) const;
    bool apply_seen(Battle::Mon& foe_mon);
    void came_in();
    void calibrate();
    std::pair<bool, QString> doomed_inner();
    bool hp_sure() const;
    bool going_down() const;
    Thrown thrown(int button, const Battle::Move& move, const QString& why);
    void enter(int mon, bool keep_hp = false);
    std::optional<QString> find_mine(const QString& text) const;
    void log(const QString& text) const;

    Log m_log;
    std::optional<double> m_pending_me;
    std::optional<double> m_pending_foe;
    std::optional<int> m_shield_seen_me;
    std::optional<int> m_shield_seen_foe;
    QHash<QString, Left> m_foe_left;
    std::set<QString> m_threw_species;
    std::optional<QString> m_first_pending;
    QString m_foe_miss;
    int m_shield_more = 0;
    std::optional<int> m_shield_more_n;
    std::optional<double> m_rise_reading;
    int m_rise_rows = 0;
    int m_came_mon = 0;                     //  who came in last, and the HP it had before that
    double m_came_hp = 0.0;
    bool m_came_hp_float = false;
    long long m_entered_at = -1000000;
    double m_entered_clock = 0.0;

    //  What aim() was worked out for, and its answer.
    struct AimKey{
        int pos = -1;
        QString species;
        int my_hp = 0;
        int foe_hp = 0;
        int foe_shields = 0;
        std::optional<QString> button_slots[2];
        bool operator==(const AimKey& o) const;
    };
    bool m_aim_has_key = false;
    AimKey m_aim_key;
    std::optional<Aim> m_aim_result;

    friend class FightTest;
};


//  ---- the test: the answers of battle_fight.py
//
//  Reads the file of answers (Mobile/tests/fixtures/fight_golden.json) and the data, plays every
//  fight in it on this port and says where one differs. Returns how many fights differ.
int run_fight_checks(const QString& golden, const QString& data, QStringList& report);


}
}
}
}
#endif
