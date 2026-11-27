/*  ClaudeGG Assistant: MCP Session
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  Claude Plays without the program's API key: a Claude that the user runs
 *  (Claude Code, on a Claude subscription) connects to a server of this
 *  program (Assistant_McpServer.h) and calls the tools of the game. The
 *  server lives in the thread of the interface; the program that plays
 *  lives in a thread of its own. This is what lies between them, as
 *  PlaySession lies between the program and the Claude API: the program
 *  waits for the next call, runs it and says what came of it.
 *
 *  No Qt in this header: programs of the games include it.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_Assistant_Mcp_H
#define PokemonAutomation_ClaudeGG_Assistant_Mcp_H

#include <stdint.h>
#include <chrono>
#include <memory>
#include <string>
#include <vector>
#include "Assistant_Play.h"

namespace PokemonAutomation{

class CancellableScope;

namespace ClaudeGG{
namespace Assistant{


//  The token a client of the server has to show ("Authorization: Bearer ...").
//  Made once, at random (32 bytes from the system's source of randomness),
//  and kept in a file of its own in "settings_folder" (encrypted for the
//  user, as the other tokens are): the same at every start, so the client
//  is added to Claude Code once. "make_new" makes a new one: the client
//  that has the old one is refused from then on. Empty, with "error" saying
//  why, if none can be made. If the file cannot be written the token is
//  returned anyway, with "error" saying so: it holds until the program
//  closes.
std::string mcp_token(const std::string& settings_folder, bool make_new, std::string& error);


//  What the user needs to connect Claude Code to the server: the command that
//  adds it, and how it is used. It holds the token, so it goes in a file of
//  its own in "settings_folder" (ClaudeGG-Mcp-Connect.txt) and not in the log,
//  which people post when they ask for help. The path of the file, or empty
//  with "error" saying why not.
std::string write_mcp_connect_file(const std::string& settings_folder, int port, const std::string& token, std::string& error);
//  The text of that file.
std::string mcp_connect_text(int port, const std::string& token);


class McpSession{
public:
    struct Setup{
        std::string server_name = "claude-gg";
        std::string version;
        //  What the client's model is told about the server.
        std::string instructions;
        std::vector<PlayTool> tools;
        //  A request without it is refused. Not empty.
        std::string token;
        //  0: any free port.
        int port = 0;
    };

    explicit McpSession(Setup setup);
    //  Closes the server. A call that waits for its result gets an answer
    //  that says the program stopped.
    ~McpSession();
    McpSession(const McpSession&) = delete;
    void operator=(const McpSession&) = delete;

    //  Starts listening (on 127.0.0.1 only). Empty if it does; else why not,
    //  for the user. Throws as "scope" does once the program is stopped.
    std::string start(CancellableScope& scope);
    //  The port it listens on, once start() returned.
    int port() const;

    //  Waits up to "timeout" for the next call of the client. False if none
    //  came. Throws as "scope" does once the program is stopped.
    bool wait(CancellableScope& scope, std::chrono::milliseconds timeout, PlayCall& call);
    //  What came of the call that wait() handed out.
    void finish(const PlayCall& call, PlayResult result);

    //  How many times a client has started (the handshake) and how many
    //  calls came in, so far.
    uint64_t clients() const;
    uint64_t calls() const;

private:
    struct Shared;
    std::shared_ptr<Shared> m_shared;
};



}
}
}
#endif
