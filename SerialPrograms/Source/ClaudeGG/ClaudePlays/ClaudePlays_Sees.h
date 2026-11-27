/*  ClaudeGG Claude Plays: what the program's own readers see
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The other programs of a game have picture readers (detectors) that know
 *  what a screen of that game shows: a dialog box, a menu. Claude Plays runs
 *  the readers of the games that have measured ones on every picture it takes
 *  of the screen, and puts what they found at the end of a result:
 *
 *      Screen: still now. The program sees: the main menu.
 *
 *  This is a hint beside the picture, never instead of it. The readers say
 *  only what they recognize: a result without this part does not say that
 *  the screen shows nothing of the kind, and a reader can be wrong.
 *
 *  Games with readers so far: Pokemon Legends Z-A (the dialog boxes and the
 *  main menu, the readers with stored pictures in the test repository).
 *  The other games are not covered yet: their readers have too few stored
 *  pictures to know how far they can be trusted (see ROADMAP.md).
 *
 */

#ifndef PokemonAutomation_ClaudeGG_ClaudePlays_Sees_H
#define PokemonAutomation_ClaudeGG_ClaudePlays_Sees_H

#include <string>
#include "ClaudePlays_Games.h"

namespace PokemonAutomation{

class ImageViewRGB32;

namespace ClaudeGG{
namespace ClaudePlays{


//  The game has readers whose findings go into the results (game_sees()).
bool game_has_readers(GameId game);

//  What the game's readers recognize in "frame", as the end of a sentence
//  that begins "The program sees": "the main menu", "a white dialog box and
//  a blue message box". Empty: nothing they know, or the game has no readers.
std::string game_sees(GameId game, const ImageViewRGB32& frame);


//  Pokemon Legends Z-A: what its readers found in one picture.
struct LegendsZaFindings{
    //  The main menu (Boxes, Satchel, Pokedex... on the left).
    bool main_menu = false;
    //  The white dialog box at the bottom: somebody speaks, or the game says
    //  something.
    bool white_dialog = false;
    //  The transparent dialog box of a battle: a trainer speaks before or
    //  after it.
    bool battle_dialog = false;
    //  The blue message box: an item is received, or a notice.
    bool blue_dialog = false;
};
LegendsZaFindings legends_za_findings(const ImageViewRGB32& frame);
//  In the words of game_sees(): empty when nothing was found.
std::string legends_za_words(const LegendsZaFindings& findings);


}
}
}
#endif
