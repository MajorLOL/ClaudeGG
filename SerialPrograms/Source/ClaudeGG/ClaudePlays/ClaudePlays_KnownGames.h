/*  ClaudeGG Claude Plays: well-known games of the other consoles
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The list of a console (a PlayStation 2, a Nintendo 64, ...) does not
 *  know which game is in it: the user says so under "About the game", or
 *  Claude finds out. For some well-known games the program knows more, and
 *  the user can pick one:
 *
 *  -   its name and its controls as the game has them by default, where a
 *      game differs from what the console usually does (Final Fantasy VII
 *      confirms with CIRCLE outside Japan too);
 *
 *  -   how many frames a second it runs at, where that is far below 60: a
 *      game that reads the pad once a frame at 20 frames a second misses a
 *      press shorter than a frame or two, so presses are made longer.
 *
 *  Only what is certain is here (the games' manuals, their default
 *  controls). Everything is data: a game is a new entry in known_games().
 *
 *  No Qt in this header.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_ClaudePlays_KnownGames_H
#define PokemonAutomation_ClaudeGG_ClaudePlays_KnownGames_H

#include <string>
#include <vector>
#include "ClaudePlays_Consoles.h"
#include "ClaudePlays_Games.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace ClaudePlays{


struct KnownGame{
    //  The list it is in: GameId::NINTENDO_64.
    GameId list;
    //  For the option and in the settings file: "zelda-oot".
    std::string slug;
    //  For Claude and the user: "The Legend of Zelda: Ocarina of Time".
    std::string name;
    //  For Claude: its controls by default, by the names of the list's pad.
    std::string notes;
    //  Which button is yes, when the game has its own way. Empty: the
    //  console's.
    std::string yes_no;
    //  The frames a second it runs at where that is below 30 (0: not
    //  below): the presses are made long enough for it.
    int frame_rate = 0;
    //  For a console over Wi-Fi with a program of its own and no game list
    //  ("wiiu", "vita", "3ds"): its code ("list" is then OTHER_GAMES and not
    //  used). Empty: a game of "list".
    std::string console;
};

//  The known games of a list, in the order of the option. Empty for most.
std::vector<const KnownGame*> known_games(GameId list);
//  The known games of a console over Wi-Fi with a program of its own:
//  "wiiu", "vita", "3ds". Empty for the others.
std::vector<const KnownGame*> known_games_on(const std::string& console);

//  The timing for a game of "frame_rate": a direction held at least three
//  of its frames, a button 30 ms longer. Faster games: "base".
InputTiming timing_for_game(const InputTiming& base, int frame_rate);


//  The checks of this file: the number that failed, what failed in
//  "report".
int known_games_tests(std::string& report);



}
}
}
#endif
