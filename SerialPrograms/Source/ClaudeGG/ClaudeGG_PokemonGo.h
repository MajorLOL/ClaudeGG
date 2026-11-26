/*  Claude GG Pokemon GO (the programs of the phone)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The game "Pokémon GO" is a game of the console "Android phone" (see
 *  ClaudeGG_Mobile.h): the phone is plugged into a Raspberry Pi, and that
 *  Pi runs the Pokémon GO bot that was made before Claude GG (Mobile/gamebot.py:
 *  it spins the PokéStops, catches, opens and sends gifts, battles Team GO
 *  Rocket and plays the daily run). The programs here do not play by
 *  themselves. Each is a preset of that bot: it says what the bot is to do
 *  (the switches of the bot), starts it on the Pi through the agent (/v1/bot),
 *  shows what the bot writes in the output log of the program, and stops it
 *  when the program is stopped.
 *
 *  The Go Battle League (online PvP) is left out on purpose: it is not
 *  automated in Claude GG, it stays with the bot's own web page.
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


}
}
}
#endif
