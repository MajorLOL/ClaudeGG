/*  ClaudeGG Claude Plays: Claude Code plays
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  What every program in which Claude plays has to offer the user who has no
 *  API credit: to let a Claude of their own (Claude Code, on a Claude
 *  subscription, say) play through a server of the program
 *  (Assistant_Mcp.h) instead of the program asking Claude through the API.
 *
 *  The options that choose who plays, and the part of the program that
 *  starts the server, says how to connect and serves the calls until the
 *  session ends. The game, and the host with the log and the numbers under
 *  the video, are the program's own.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_ClaudePlays_External_H
#define PokemonAutomation_ClaudeGG_ClaudePlays_External_H

#include <stdint.h>
#include "Common/Cpp/Options/EnumDropdownOption.h"
#include "Common/Cpp/Options/SimpleIntegerOption.h"
#include "ClaudePlays_Engine.h"

namespace PokemonAutomation{

class Logger;

namespace ClaudeGG{
namespace ClaudePlays{


//  The options of a program that can be played by Claude Code. The program
//  adds the three to its own (after its setup text, before its goal) and
//  asks claude_code() when it starts.
class WhoPlays{
public:
    //  The program asks Claude through the Claude API (the key in the panel
    //  of the interface), or the Claude of the user calls the game's tools
    //  through a server of this program and the program asks nobody.
    enum class Player{
        API,
        CLAUDE_CODE,
    };

    WhoPlays();

    bool claude_code() const{
        return (Player)PLAYER == Player::CLAUDE_CODE;
    }

    EnumDropdownOption<Player> PLAYER;
    SimpleIntegerOption<uint32_t> PORT;
    //  Minutes, 0: for ever.
    SimpleIntegerOption<uint32_t> IDLE;
};


//  Starts the server on 127.0.0.1 with the game's tools, writes the file
//  that tells how to connect Claude Code (it holds the token, so it is not
//  in the log), and runs the calls that come in until the session ends
//  (serve_external() in ClaudePlays_Engine.h). "logger" is the program's own,
//  for the errors of a user's setup: a port that is taken is one. Throws as
//  the host's scope does once the program is stopped.
//
//  The game has to have been made for it: instructions() and tools() are
//  what Claude Code is told.
Ending serve_claude_code(
    Logger& logger, Host& host, Game& game,
    const WhoPlays& who, const Limits& limits
);



}
}
}
#endif
