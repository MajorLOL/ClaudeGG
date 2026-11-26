/*  Claude GG Pokemon GO Battle (the brain of the GO Battle League fights)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port to C++ of Mobile/battle_engine.py (issue #30): the part of the
 *  Pokémon GO bot that decides, and does not touch the phone. Which charged
 *  attack is best against the Pokémon on the field and when to throw it,
 *  whether to use a shield on the attack that is coming, who comes in after a
 *  faint, and the stats of a Pokémon worked out from its CP and HP. The data
 *  (base stats, moves, the type chart, the CP multipliers) is the file
 *  models/battle_data.json, made from PvPoke's data (MIT License, Copyright
 *  (c) 2019 pvpoke); the choice of the charged attack and of the shield in a
 *  duel follow PvPoke's ActionLogic.js.
 *
 *  What the functions answer is what battle_engine.py answers, to the letter
 *  (the reasons that come with a decision too): Mobile/tools/make_engine_golden.py
 *  makes a file with its answers to some 17,000 questions and run_engine_checks()
 *  holds this port to it in every build (--mobile-test). Change battle_engine.py
 *  and the test of Python says the file is old; make it again, and the test of
 *  this port says what is different.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoBattle_H
#define PokemonAutomation_ClaudeGG_PokemonGoBattle_H

#include <optional>
#include <utility>
#include <vector>
#include <QString>
#include <QStringList>

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Battle{


//  The data. Load it once (the models folder of the bot has it); every function below needs it.
//  Returns false, with the reason, when the file is not there or is not what it should be.
bool load_data(const QString& path, QString& error);
bool data_loaded();


//  A fast move (no energy to pay) or a charged one.
struct Move{
    QString id;
    QString name;
    QString type;
    int power = 0;
    int energy = 0;     //  what a charged move costs; 0 for a fast move
    int gain = 0;       //  the energy a fast move gives
    int turns = 0;      //  how many half seconds a fast move takes
    bool charged() const{ return energy > 0; }
};

//  One Pokémon in a battle: its stats, its moves and its state.
struct Mon{
    QString species;
    QString name;
    QStringList types;
    bool shadow = false;
    int base[3] = {0, 0, 0};            //  base attack, defense, HP
    int pos = 0;                        //  its place in the party
    double level = 0;
    int ivs[3] = {0, 0, 0};
    int cp = 0;
    double atk = 0;
    double dfn = 0;
    double max_hp = 0;
    Move fast;
    std::vector<Move> charged;
    double hp = 0;
    int energy = 0;
    int shields = 2;

    QString label() const;
    double hp_frac() const;
    bool alive() const;
};

//  What Mon() of Python is given: what is not given is not set.
struct MonSpec{
    QString species;
    bool shadow = false;
    std::optional<double> level;
    std::optional<std::vector<int>> ivs;
    std::optional<QString> fast;
    std::optional<QStringList> charged;
    std::optional<std::vector<double>> stats;       //  fitted average stats (attack, defense, HP) replace the IVs'
    int pos = 0;
};
//  False when the species or a move is not in the data.
bool make_mon(const MonSpec& spec, Mon& out);


//  ---- types and names

double type_mult(const QString& move_type, const QStringList& def_types);

//  A name in lower case letters and digits with single spaces ("Pokémon" is "pokemon").
QString norm(const QString& text);
//  A move or a species from a name that OCR may have damaged: the id, or an empty string.
QString find_move(const QString& text, double cutoff = 0.78);
QString find_species(const QString& text, double cutoff = 0.8);

//  difflib.get_close_matches(word, possibilities, n=1, cutoff): the best one, or false.
bool close_match(const QString& word, const QStringList& possibilities, double cutoff, QString& best);


//  ---- stats and moves

double cpm(double level);
int calc_cp(const int base[3], const int ivs[3], double level);
int damage(const Move& move, const Mon& attacker, const Mon& defender);

//  The moveset the rankings recommend (false when they have none), a guess, or the first and else the second.
bool ranked_moveset(const QString& species, std::pair<QString, QStringList>& out, const QString& cap = "1500");
std::pair<QString, QStringList> guessed_moveset(const QString& species);
std::pair<QString, QStringList> default_moveset(const QString& species);

//  Level, IVs and the average stats of the combinations that give this CP and HP; false when none does.
struct Fit{
    double level = 0;
    int ivs[3] = {0, 0, 0};
    double stats[3] = {0, 0, 0};
};
bool fit_stats(const QString& species, int cp, int hp, Fit& out);

//  The team from entries: species, shadow, cp + hp (fitted) or level + ivs, fast, charged.
struct TeamEntry{
    QString species;
    bool shadow = false;
    std::optional<int> cp;
    std::optional<int> hp;
    std::optional<double> level;
    std::optional<std::vector<int>> ivs;
    std::optional<QString> fast;
    std::optional<QStringList> charged;
};
std::vector<Mon> build_team(const std::vector<TeamEntry>& entries);

//  A guessed opponent from the name on the screen; false when it is not known.
bool foe_from_text(const QString& name, bool shadow, Mon& out);


//  ---- decisions

struct Choice{
    bool has_move = false;
    Move move;
    QString reason;
};
struct Verdict{
    bool use = false;
    QString reason;
};

//  The charged attack to throw now (has_move false: go on with the fast one).
Choice pick_charged(const Mon& me, const Mon& foe, int energy, int foe_shields = 0, std::optional<double> foe_hp = {});

//  The damage and the move of the charged attack that is coming (no move known: the hardest one the foe can pay for).
std::pair<int, Move> foe_hit(const Mon& foe, const Mon& me, const Move* foe_move = nullptr, std::optional<double> energy = {});
std::vector<Move> can_throw(const Mon& foe, std::optional<double> energy = {});
std::pair<double, int> fast_rate(const QString& species);
int cheapest_charged(const QString& species);
int cycle_damage(const Mon& foe, const Mon& me, const Move& move, int shields, std::optional<double> foe_energy = {});

//  The shield in a duel of one against one (PvPoke's rule).
Verdict should_shield(const Mon& foe, const Mon& me, int shields, const Move* foe_move = nullptr,
    std::optional<double> my_hp = {}, std::optional<double> foe_energy = {});

//  The shield in a real battle of three against three; foe is null when it is not known.
Verdict use_shield(const Mon* foe, const Mon& me, int shields, std::optional<double> my_hp = {},
    std::optional<int> mine_left = 3, std::optional<int> foes_left = {}, bool ready = false,
    const Move* foe_move = nullptr, std::optional<double> foe_energy = {});

//  A duel played out with these rules: the part of its HP that each has left. Neither is changed.
std::pair<double, double> simulate(const Mon& a, const Mon& b, int shields_a = 2, int shields_b = 2, int max_turns = 1200);
double matchup(const Mon& me, const Mon& foe, int my_shields = 2, int foe_shields = 2);

//  The best of the Pokémon that are alive against the foe: its index in the list (-1: none) and its score.
std::pair<int, double> best_switch(const std::vector<Mon>& candidates, const Mon& foe, int my_shields = 2, int foe_shields = 2);


//  ---- the test: the answers of battle_engine.py
//
//  Reads the file of answers (Mobile/tests/fixtures/engine_golden.json) and the data, answers every
//  question with this port and says what is different. Returns how many answers differ.
int run_engine_checks(const QString& golden, const QString& data, QStringList& report);


}
}
}
}
#endif
