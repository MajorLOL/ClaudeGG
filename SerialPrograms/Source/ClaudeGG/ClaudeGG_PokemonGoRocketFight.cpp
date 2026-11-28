/*  Claude GG Pokemon GO Rocket Fight (the fight against Team GO Rocket in the Pokémon GO bot)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  See ClaudeGG_PokemonGoRocketFight.h.  What the Python code does is followed line by line, down to the order of the taps, the aims and the log lines.
 *
 */

#include <algorithm>
#include <memory>
#include <optional>
#include "ClaudeGG_PokemonGoBattle.h"
#include "ClaudeGG_PokemonGoMinigame.h"
#include "ClaudeGG_PokemonGoRocketFight.h"
#include "ClaudeGG_PokemonGoVision.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace RocketFight{

namespace{

//  _frac_xy(): a place as fractions of the screen -> pixels of the canvas.
Loop::Point frac_xy(double fx, double fy){
    return Loop::Point{(int)(fx * Loop::REF_W), (int)(fy * Loop::REF_H)};
}

}


QStringList rocket_kinds(const QString& name){
    QStringList kinds;
    if (name.isEmpty()){
        return kinds;
    }
    const QString species = Battle::find_species(name);
    if (species.isEmpty()){
        return kinds;
    }
    for (const QString& id : Battle::species_charged(species)){
        Battle::Move move;
        if (!Battle::move_by_id(id, move)){
            continue;
        }
        const QString type = move.type.toLower();
        if (!kinds.contains(type)){
            kinds << type;
        }
    }
    kinds.sort();
    return kinds;
}


int rocket_fight(Loop::Host& host){
    host.busy(SECONDS);
    Loop::Eyes eyes(host);
    const std::unique_ptr<Loop::Tapper> tapper = host.make_tapper(frac_xy(Vision::TAP_FAST[0], Vision::TAP_FAST[1]), Loop::FIGHT_TAP_MS);
    const double t0 = host.monotonic();
    std::optional<double> last_hud;
    std::optional<double> started;
    std::shared_ptr<Loop::LittleGame> mini;                 //  its little game: the icons, the swipes
    double game_at = -100.0;
    double shield_at = -100.0;
    int games = 0;
    int shields = 0;
    QString me;                                             //  who is ours on the field (its attacks: their types)
    QStringList kinds;
    double named_at = -100.0;
    int turn = 0;
    const Loop::Point aims[2] = {frac_xy(BTN_X[1], Vision::BTN_Y), frac_xy(BTN_X[0], Vision::BTN_Y)};
    const auto leave = [&]{
        tapper->sweep(Loop::Planner());
        tapper->close();
        eyes.close();
        host.busy(0);
    };
    try{
        while (host.monotonic() - t0 < SECONDS && !host.stop()){
            const Loop::Look look = eyes.look();
            const double now = host.monotonic();
            const QString st = Loop::fight_state(host, look.small);
            if (mini){                                      //  its little game: the icons, the swipes
                mini->see(mini->look(look.small), look.t);
                if (mini->over(now) || now - game_at > GAME_LONGEST){
                    tapper->sweep(Loop::Planner());
                    QString report = mini->report();
                    report.replace("battle: ", "");
                    host.log("rocket: " + report);
                    mini.reset();
                    tapper->go();
                }
                continue;
            }
            if (st == "prompt"){
                tapper->pause();
                if (Vision::shield_question(look.small) && now - shield_at > SHIELD_EVERY){
                    shield_at = now;
                    shields++;
                    host.log("rocket: an attack is coming - SHIELD");
                    const Loop::Point shield = frac_xy(Vision::TAP_SHIELD[0], Vision::TAP_SHIELD[1]);
                    tapper->tap(shield.x, shield.y);
                }
                continue;
            }
            if (st == "fight"){
                last_hud = now;
                if (!started.has_value()){
                    started = now;
                    host.log("rocket: the fight has started");
                }
                if (now - named_at > NAMED_EVERY){          //  who is ours on the field (its attacks: their types)
                    named_at = now;
                    const QString name = Loop::fight_name_box(host, look.canvas, true).name;
                    if (!name.isEmpty() && name != me){
                        me = name;
                        kinds = rocket_kinds(name);
                        host.log(QString("rocket: ours is %1 - its charged attacks can be: %2").arg(me, kinds.isEmpty() ? QString("not known") : kinds.join(", ")));
                    }
                }
                turn++;
                tapper->aim(aims[(turn / TURN_PICTURES) % 2]);  //  (4 pictures on a button, then the other)
                tapper->go();
                continue;
            }
            //  no HUD: the little game of our charged attack?  (or theirs, a flash, the end)
            if (started.has_value() && now - game_at > GAME_EVERY){
                for (const QString& kind : (kinds.isEmpty() ? Minigame::type_names() : kinds)){
                    if (Minigame::find_icons(look.small, kind).size() >= (size_t)GAME_ICONS){
                        games++;
                        game_at = now;
                        Battle::Move move;                  //  (a charged attack known only by its type: the little game needs no more)
                        move.id = kind.toUpper();
                        move.name = QString("a %1 attack").arg(kind);
                        move.type = kind;
                        move.energy = 50;
                        mini = std::make_shared<Loop::LittleGame>(move, now - 1.0, host.load_minigames(), 0);
                        mini->see(mini->look(look.small), look.t);
                        tapper->aim(std::nullopt);
                        {
                            const std::shared_ptr<Loop::LittleGame> game = mini;
                            Loop::Host& phone = host;
                            tapper->sweep([game, &phone]{ return game->strokes(phone.monotonic()); });
                        }
                        host.log(QString("rocket: the little game of a %1 attack").arg(kind));
                        break;
                    }
                }
                if (mini){
                    continue;
                }
            }
            if (started.has_value() && now - *last_hud > HUD_GONE && now - game_at > HUD_GONE){
                break;                                      //  the fight is over (speech bubble, rewards, ...)
            }
            if (!started.has_value() && now - t0 > NO_FIGHT){
                host.log("rocket: no fight came");
                break;
            }
        }
    }catch (...){
        leave();
        throw;
    }
    leave();
    const int secs = (int)(host.monotonic() - t0);
    host.log(QString("rocket: fight ended after %1 s (%2 fast taps, %3 little games, %4 shields)").arg(secs).arg(tapper->taps()).arg(games).arg(shields));
    return secs;
}


}
}
}
}
