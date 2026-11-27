/*  ClaudeGG Claude Plays: Claude Code plays
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <chrono>
#include <string>
#include <utility>
#include "Common/Cpp/Color.h"
#include "Common/Cpp/Exceptions.h"
#include "CommonFramework/GlobalAutoPaths.h"
#include "CommonFramework/Globals.h"
#include "ClaudeGG/Assistant/Assistant_Mcp.h"
#include "ClaudePlays_External.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace ClaudePlays{


WhoPlays::WhoPlays()
    : PLAYER(
        "<b>Who plays:</b><br>\"The program asks Claude\": the program talks to Claude through the Claude API "
        "(your key, in the panel \"Claude\") and each request is billed to you. \"Claude Code plays\": you run "
        "Claude Code yourself (on your Claude subscription, say), and it calls the game's tools through a "
        "server of this program on this computer. The program then needs no key and pays nothing, and the "
        "goal is the one you give Claude Code, not the one below. The file ClaudeGG-Mcp-Connect.txt in the "
        "settings folder says how to connect Claude Code, once.",
        {
            {Player::API,           "api",          "The program asks Claude (through the API)"},
            {Player::CLAUDE_CODE,   "claude-code",  "Claude Code plays (through the program's server)"},
        },
        LockMode::LOCK_WHILE_RUNNING,
        Player::API
    )
    , PORT(
        "<b>Port of the server (\"Claude Code plays\"):</b><br>The program listens on this computer only "
        "(127.0.0.1). Keep it the same and Claude Code stays connected from one start to the next.",
        LockMode::LOCK_WHILE_RUNNING,
        28417, 1024, 65535
    )
    , IDLE(
        "<b>Stop after minutes without a call (\"Claude Code plays\"):</b><br>Counted from the start for the "
        "first call. 0: waits for ever (until Claude Code calls done, the limit on actions is reached, or you "
        "stop the program).",
        LockMode::LOCK_WHILE_RUNNING,
        30, 0, 1440
    )
{}


Ending serve_claude_code(
    Logger& logger, Host& host, Game& game,
    const WhoPlays& who, const Limits& limits
){
    const std::string settings_folder = SETTINGS_PATH();
    const uint32_t wanted_port = who.PORT;
    const uint32_t idle_minutes = who.IDLE;

    std::string error;
    McpSession::Setup setup;
    setup.version = PROGRAM_BUILD;
    setup.instructions = game.instructions();
    setup.tools = external_tools(game);
    setup.token = Assistant::mcp_token(settings_folder, false, error);
    if (setup.token.empty()){
        throw UserSetupError(logger, "The server cannot start: it has no token (" + error + ").");
    }
    if (!error.empty()){
        host.log("Claude Plays: " + error + " The token holds until the program closes.", COLOR_ORANGE);
    }
    setup.port = (int)wanted_port;
    const std::string token = setup.token;

    McpSession mcp(std::move(setup));
    const std::string start_error = mcp.start(host.scope());
    if (!start_error.empty()){
        throw UserSetupError(
            logger,
            "The server cannot listen on port " + std::to_string(wanted_port) + ": " + start_error +
            " Another program may use that port: pick another under \"Port of the server\"."
        );
    }

    std::string file_error;
    const std::string file = Assistant::write_mcp_connect_file(settings_folder, mcp.port(), token, file_error);
    const std::chrono::seconds idle(60 * (int64_t)idle_minutes);
    host.log(
        "Claude Plays: listening on 127.0.0.1:" + std::to_string(mcp.port()) + " for Claude Code, at most " +
        std::to_string(limits.max_actions) + " actions" +
        (idle_minutes > 0 ? ", until " + std::to_string(idle_minutes) + " minutes pass without a call" : std::string()) +
        ". " + (file.empty()
            ? "The file that says how to connect Claude Code could not be written (" + file_error + ")."
            : "How to connect Claude Code (once): see " + file + ". It holds the token, so it is not in this log."),
        file.empty() ? COLOR_ORANGE : COLOR_BLUE
    );
    host.show("Waiting for Claude Code", COLOR_GREEN);

    return serve_external(host, game, mcp, limits, idle);
}



}
}
}
