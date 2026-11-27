/*  ClaudeGG Claude Plays: the games
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  What the program "Claude Plays" of each game's list tells Claude about
 *  its game, and "Other Games" for whatever else is on the screen.
 *  (FireRed and LeafGreen have a Claude Plays of their own, with the
 *  routines of the AutoStory: VideoGames/PokemonFRLG/Programs/ClaudePlays.)
 *
 *  Every game that is added to the program gets a Claude Plays: a GameId and
 *  a profile here, and either a list of its own in VideoGames/ (like
 *  ZeldaTotK) or, while it has no programs, an entry in
 *  has_only_claude_plays(): it has no tile on the page with the games then,
 *  and is a choice of the option "Game" of Claude Plays in Other Games. The
 *  notes of a profile say only what is certain.
 *
 *  No Qt in this header.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_ClaudePlays_Games_H
#define PokemonAutomation_ClaudeGG_ClaudePlays_Games_H

#include <string>
#include <vector>

namespace PokemonAutomation{
namespace ClaudeGG{
namespace ClaudePlays{


enum class GameId{
    OTHER_GAMES,
    POKEMON_HOME,
    LETS_GO,
    SWORD_SHIELD,
    BRILLIANT_DIAMOND_SHINING_PEARL,
    LEGENDS_ARCEUS,
    SCARLET_VIOLET,
    LEGENDS_ZA,
    POKOPIA,
    RUBY_SAPPHIRE_EMERALD,
    ZELDA_TOTK,
    OCTOPATH_TRAVELER_0,
    MARIO_KART_8_DELUXE,
    SPLATOON_3,
    ANIMAL_CROSSING_NEW_HORIZONS,
    //  Whatever game a PlayStation 3 shows: the list of that console.
    PLAYSTATION_3,
};

//  The controller the game's programs use.
enum class PadKind{
    PRO_CONTROLLER,
    RIGHT_JOYCON,
    //  A PlayStation 3 controller, by its own names: a wired board that the
    //  console sees as a plain USB gamepad (ClaudePlays_AnyGame.h,
    //  ps3_controller_layout()).
    PS3_CONTROLLER,
};

struct GameProfile{
    GameId id;
    //  The program's identifier: "PokemonSV:ClaudePlays".
    std::string identifier;
    //  The category of the game's programs: "Pokemon SV" (with the accent).
    std::string category;
    //  For Claude: "Pokemon Scarlet or Violet". Empty for OTHER_GAMES.
    std::string name;
    //  For the user, in the program's description: "Pokemon Scarlet and
    //  Violet".
    std::string title;
    //  For Claude: the controls and what else helps, as far as they are
    //  certain. The buttons on the screen are what counts.
    std::string notes;
    PadKind pad = PadKind::PRO_CONTROLLER;
    //  The game's other programs have a routine that saves the game (the
    //  program wires it to the tool save_game).
    bool save_routine = false;
    //  The console the game is played on: the code of the setup's console
    //  ("switch" stands for both Switches, see ClaudeGG_Home.h).
    std::string console = "switch";
};

const GameProfile& game_profile(GameId id);
//  All of them, in the order of the list of games.
const std::vector<GameId>& all_games();

//  The games that have a list of their own with nothing in it but Claude
//  Plays (no program for the game itself yet): the list is made by
//  GameOnlyList (ClaudePlays_Program.h).
bool has_only_claude_plays(GameId id);

//  The games of the Switch among those: the choices of the option "Game" of
//  Other Games. (The list of another console is a tile of its own.)
bool is_other_games_choice(GameId id);

//  The consoles of a list of games by its name, when the list is one of a
//  game here that is not played on the Switch: {"ps3"}. Empty: not one of them.
std::vector<std::string> consoles_of_list(const std::string& list_name);

//  The name of the list of games "Other Games".
extern const char* const OTHER_GAMES_LIST;



}
}
}
#endif
