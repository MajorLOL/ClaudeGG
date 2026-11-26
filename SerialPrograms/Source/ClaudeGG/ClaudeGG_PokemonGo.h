/*  Claude GG Pokemon GO (the programs of the phone)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The game "Pokémon GO" is a game of the console "Android phone" (see
 *  ClaudeGG_Mobile.h): the phone is plugged into a Raspberry Pi, and that
 *  Pi runs the Pokémon GO bot that was made before Claude GG (Mobile/gamebot.py:
 *  it spins the PokéStops, catches, opens and sends gifts, battles Team GO
 *  Rocket, fights GO Battle League battles, keeps the teams of the leagues
 *  and plays the daily run). The programs here do not play by themselves.
 *  Each is a preset of that bot: it says what the bot is to do (the switches
 *  of the bot), starts it on the Pi through the agent (/v1/bot), shows what
 *  the bot writes in the output log of the program, and stops it when the
 *  program is stopped. Some do not start the bot's service but run one part
 *  of it (the "tests" of its chapters.py: a set of battles, a step of the
 *  scan of the Pokémon, one throw, ...) and end with that part.
 *
 *  Pokémon GO's Terms of Service do not allow automation: use a spare account.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGo_H
#define PokemonAutomation_ClaudeGG_PokemonGo_H

#include <string>
#include <utility>
#include <vector>
#include "CommonFramework/Panels/PanelList.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{


//  The list of the game "Pokémon GO": the programs of the phone.
class PokemonGoList : public PanelListDescriptor{
public:
    PokemonGoList();

protected:
    virtual std::vector<PanelEntry> make_panels() const override;
};

//  How many programs the list has (for the test).
size_t pokemon_go_program_count();

//  What a program asks of the bot, as the bot's switches by name (for the test):
//  the program by its name in the list; empty when there is no such program.
std::vector<std::pair<std::string, bool>> pokemon_go_switches(const std::string& program);

//  The parts of the bot that the programs can run on their own, by their key (for the test:
//  the bot must know every one of them).
std::vector<std::string> pokemon_go_part_keys();


}
}
}
#endif
