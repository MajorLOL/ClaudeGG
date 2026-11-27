/*  ClaudeGG Assistant: MCP Server
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A small server for the Model Context Protocol (MCP), so that a Claude that
 *  the user runs themselves (Claude Code on a subscription, for one) can use
 *  the tools of Claude Plays: it plays through the program without the
 *  program's API key. Three layers, each testable on its own:
 *
 *  -   The HTTP side: a request is read from the bytes of a connection
 *      (parse_mcp_http_request()) and is let through or refused (check_mcp_request():
 *      the address, the origin, the token).
 *  -   The protocol: one JSON-RPC message from a client in, the answer out
 *      (McpProtocol). What a client may ask: initialize, ping, tools/list,
 *      tools/call. Nothing else is offered (no resources, no prompts).
 *  -   The server: it listens on 127.0.0.1 only and serves one endpoint,
 *      POST /mcp (the "streamable HTTP" transport, answers as plain JSON).
 *
 *  What it serves is a McpBackend: the tools and what comes of a call.
 *
 *  A client of this server presses buttons on the user's consoles. So: the
 *  server never listens beyond this computer, a request needs the token that
 *  the user has put into the client, and a request whose Host or Origin is
 *  not this computer is refused (a web page cannot reach it through the
 *  user's browser).
 *
 */

#ifndef PokemonAutomation_ClaudeGG_Assistant_McpServer_H
#define PokemonAutomation_ClaudeGG_Assistant_McpServer_H

#include <functional>
#include <list>
#include <map>
#include <memory>
#include <string>
#include <vector>
#include <QByteArray>
#include <QString>
#include "Assistant_Play.h"

class QTcpServer;

namespace PokemonAutomation{
namespace ClaudeGG{
namespace Assistant{


//  The protocol revisions this server answers to (those of the "initialize"
//  handshake), oldest first.
const std::vector<std::string>& mcp_protocol_versions();

//  "image/png" or "image/jpeg" for the bytes of a picture, as play_picture()
//  packs them. Empty if they are neither.
std::string mcp_image_mime(const std::string& picture);


class McpBackend{
public:
    virtual ~McpBackend() = default;
    virtual std::string server_name() const = 0;
    virtual std::string server_version() const = 0;
    //  What the client's model is told about the server.
    virtual std::string instructions() const = 0;
    virtual std::vector<PlayTool> tools() const = 0;
    //  A client asked to start. (Counted by the session.)
    virtual void initialized(){}
    //  Runs a call and calls "done" once, now or later. "arguments" is the
    //  JSON object the tool's schema describes.
    virtual void call(
        const std::string& name, const std::string& arguments,
        std::function<void(PlayResult result)> done
    ) = 0;
};


//  --  The protocol  ---------------------------------------------------------

struct McpReply{
    //  The HTTP status: 200 with a JSON body, 202 without a body for a message
    //  that needs no answer, 400 for what is not JSON-RPC.
    int status = 200;
    QByteArray body;
};

class McpProtocol{
public:
    explicit McpProtocol(McpBackend& backend);

    //  The body of a POST. "protocol_version" is the header MCP-Protocol-Version
    //  of the request (empty: none). "reply" is called once, now or later
    //  (a call of a tool takes as long as the tool takes).
    void handle(
        const QByteArray& body, const std::string& protocol_version,
        std::function<void(McpReply reply)> reply
    );

private:
    McpBackend& m_backend;
};


//  --  The HTTP side  --------------------------------------------------------

struct McpHttpRequest{
    QByteArray method;
    QByteArray target;
    //  The names in lower case.
    std::map<QByteArray, QByteArray> headers;
    QByteArray body;

    QByteArray header(const char* name) const;
};

enum class McpHttpParse{
    INCOMPLETE,         //  More bytes are needed.
    COMPLETE,           //  "request" is there and its bytes are taken from the buffer.
    BAD,                //  Not an HTTP request: 400.
    HEADERS_TOO_LARGE,  //  431.
    BODY_TOO_LARGE,     //  413.
    LENGTH_REQUIRED,    //  A body without a length (chunked): 411.
};

//  Takes one request off the front of "buffer" (the bytes that came in so far).
//  "expect_continue" is set when the headers ask for a "100 Continue" and the
//  body is not there yet.
McpHttpParse parse_mcp_http_request(QByteArray& buffer, McpHttpRequest& request, bool& expect_continue);

//  0 if the request may be served, else the HTTP status to refuse it with:
//  400 (no Host), 403 (not this computer's Host or Origin), 401 (no or a wrong
//  token), 404 (not /mcp), 405 (not POST). (A protocol version that is not
//  known is refused by McpProtocol.)
int check_mcp_request(const McpHttpRequest& request, int port, const std::string& token);

//  The bytes of a response.
QByteArray mcp_http_response(int status, const QByteArray& body, bool keep_alive);


//  --  The server  -----------------------------------------------------------

class McpServer{
public:
    //  "token": the bearer token that a request must carry.
    McpServer(McpBackend& backend, std::string token);
    ~McpServer();
    McpServer(const McpServer&) = delete;
    void operator=(const McpServer&) = delete;

    //  Listens on 127.0.0.1. Port 0: any free port. False if it cannot, and
    //  "error" says why. Only in the thread of the interface.
    bool listen(int port, std::string& error);
    int port() const;
    //  Closes the connections. The calls that wait get no answer (the
    //  session answers them first: Assistant_Mcp.h).
    void close();

    //  How many connections there may be at a time.
    static constexpr size_t MAX_CONNECTIONS = 16;

private:
    struct Connection;
    void accept();
    void process(const std::shared_ptr<Connection>& connection);
    void drop(const std::shared_ptr<Connection>& connection);

private:
    McpBackend& m_backend;
    McpProtocol m_protocol;
    const std::string m_token;
    std::unique_ptr<QTcpServer> m_server;
    std::list<std::shared_ptr<Connection>> m_connections;
};



}
}
}
#endif
