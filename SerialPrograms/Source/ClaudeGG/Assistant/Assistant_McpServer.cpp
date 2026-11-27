/*  ClaudeGG Assistant: MCP Server
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <algorithm>
#include <iterator>
#include <optional>
#include <utility>
#include <QHostAddress>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonParseError>
#include <QJsonValue>
#include <QTcpServer>
#include <QTcpSocket>
#include <QTimer>
#include "Assistant_McpServer.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace Assistant{


namespace{

//  What a request may be: its head, and its body.
const int MAX_HEADER_BYTES = 16 * 1024;
const qint64 MAX_BODY_BYTES = 4 * 1024 * 1024;
//  A connection that sends nothing for this long is closed.
const int IDLE_MS = 5 * 60 * 1000;

const int PARSE_ERROR = -32700;
const int INVALID_REQUEST = -32600;
const int METHOD_NOT_FOUND = -32601;
const int INVALID_PARAMS = -32602;

QJsonObject rpc_error(const QJsonValue& id, int code, const QString& message){
    QJsonObject error;
    error["code"] = code;
    error["message"] = message;
    QJsonObject object;
    object["jsonrpc"] = "2.0";
    object["id"] = id;
    object["error"] = error;
    return object;
}

QJsonObject rpc_result(const QJsonValue& id, const QJsonObject& result){
    QJsonObject object;
    object["jsonrpc"] = "2.0";
    object["id"] = id;
    object["result"] = result;
    return object;
}

QByteArray to_body(const QJsonValue& value){
    if (value.isArray()){
        return QJsonDocument(value.toArray()).toJson(QJsonDocument::Compact);
    }
    return QJsonDocument(value.toObject()).toJson(QJsonDocument::Compact);
}

bool known_version(const std::string& version){
    const std::vector<std::string>& versions = mcp_protocol_versions();
    return std::find(versions.begin(), versions.end(), version) != versions.end();
}

//  Whether two tokens are the same, in a time that does not tell how many
//  of their first bytes were.
bool same_token(const QByteArray& a, const QByteArray& b){
    const qsizetype longest = std::max(a.size(), b.size());
    unsigned difference = a.size() == b.size() ? 0u : 1u;
    for (qsizetype i = 0; i < longest; i++){
        const unsigned x = i < a.size() ? (unsigned)(unsigned char)a[i] : 0u;
        const unsigned y = i < b.size() ? (unsigned)(unsigned char)b[i] : 0u;
        difference |= x ^ y;
    }
    return difference == 0;
}

const char* status_text(int status){
    switch (status){
    case 100: return "Continue";
    case 200: return "OK";
    case 202: return "Accepted";
    case 400: return "Bad Request";
    case 401: return "Unauthorized";
    case 403: return "Forbidden";
    case 404: return "Not Found";
    case 405: return "Method Not Allowed";
    case 411: return "Length Required";
    case 413: return "Content Too Large";
    case 431: return "Request Header Fields Too Large";
    case 503: return "Service Unavailable";
    default: return "Error";
    }
}


//  What one message of a client comes to: the answer (none for a message that
//  needs none) and the HTTP status.
struct Outcome{
    std::optional<QJsonObject> response;
    int status = 200;
};
using OutcomeCallback = std::function<void(Outcome outcome)>;

Outcome answer(const QJsonObject& object){
    Outcome outcome;
    outcome.response = object;
    return outcome;
}

QJsonObject tool_json(const PlayTool& tool){
    QJsonObject object;
    object["name"] = QString::fromStdString(tool.name);
    object["description"] = QString::fromStdString(tool.description);
    QJsonObject schema = QJsonDocument::fromJson(QByteArray::fromStdString(tool.input_schema)).object();
    if (schema.isEmpty()){
        schema["type"] = "object";
    }
    object["inputSchema"] = schema;
    return object;
}

QJsonObject result_json(const PlayResult& result){
    QJsonArray content;
    QJsonObject text;
    text["type"] = "text";
    text["text"] = QString::fromStdString(result.text);
    content.append(text);
    if (!result.image.empty()){
        const std::string mime = mcp_image_mime(result.image);
        if (!mime.empty()){
            QJsonObject picture;
            picture["type"] = "image";
            picture["data"] = QString::fromLatin1(
                QByteArray(result.image.data(), (qsizetype)result.image.size()).toBase64()
            );
            picture["mimeType"] = QString::fromStdString(mime);
            content.append(picture);
        }
    }
    QJsonObject object;
    object["content"] = content;
    object["isError"] = result.is_error;
    return object;
}

//  One message. "version" is the header MCP-Protocol-Version of the request.
void process_message(
    McpBackend& backend, const QJsonValue& message, const std::string& version,
    const OutcomeCallback& done
){
    if (!message.isObject()){
        Outcome outcome = answer(rpc_error(QJsonValue(), INVALID_REQUEST, "A JSON-RPC message is an object."));
        outcome.status = 400;
        done(std::move(outcome));
        return;
    }
    const QJsonObject object = message.toObject();
    const QJsonValue id = object.value("id");
    const bool has_id = object.contains("id") && !id.isNull();
    const QJsonValue method_value = object.value("method");

    if (!method_value.isString()){
        //  The answer of a client to a request of the server: there are none.
        if (object.contains("result") || object.contains("error")){
            done(Outcome());
            return;
        }
        Outcome outcome = answer(rpc_error(id, INVALID_REQUEST, "There is no \"method\"."));
        outcome.status = 400;
        done(std::move(outcome));
        return;
    }
    const QString method = method_value.toString();
    if (!has_id){
        //  A notification (initialized, cancelled...): nothing to answer.
        done(Outcome());
        return;
    }

    const QJsonObject params = object.value("params").toObject();

    if (method == "initialize"){
        const QString requested = params.value("protocolVersion").toString();
        if (requested.isEmpty()){
            done(answer(rpc_error(id, INVALID_PARAMS, "\"protocolVersion\" is missing.")));
            return;
        }
        const std::string wanted = requested.toStdString();
        const std::string chosen = known_version(wanted) ? wanted : mcp_protocol_versions().back();
        QJsonObject tools;
        tools["listChanged"] = false;
        QJsonObject capabilities;
        capabilities["tools"] = tools;
        QJsonObject info;
        info["name"] = QString::fromStdString(backend.server_name());
        info["title"] = "Claude GG";
        info["version"] = QString::fromStdString(backend.server_version());
        QJsonObject result;
        result["protocolVersion"] = QString::fromStdString(chosen);
        result["capabilities"] = capabilities;
        result["serverInfo"] = info;
        const std::string instructions = backend.instructions();
        if (!instructions.empty()){
            result["instructions"] = QString::fromStdString(instructions);
        }
        backend.initialized();
        done(answer(rpc_result(id, result)));
        return;
    }

    //  A version in the header that is not known: not for what comes after the
    //  handshake. ("server/discover" is how newer clients ask first: they go
    //  on with "initialize" after the answer below.)
    if (!version.empty() && !known_version(version) && method != "server/discover"){
        Outcome outcome = answer(rpc_error(id, INVALID_REQUEST, "The protocol version " + QString::fromStdString(version) + " is not known here."));
        outcome.status = 400;
        done(std::move(outcome));
        return;
    }

    if (method == "ping"){
        done(answer(rpc_result(id, QJsonObject())));
        return;
    }
    if (method == "tools/list"){
        QJsonArray list;
        for (const PlayTool& tool : backend.tools()){
            list.append(tool_json(tool));
        }
        QJsonObject result;
        result["tools"] = list;
        done(answer(rpc_result(id, result)));
        return;
    }
    if (method == "tools/call"){
        const QString name = params.value("name").toString();
        const QJsonValue arguments = params.value("arguments");
        if (name.isEmpty()){
            done(answer(rpc_error(id, INVALID_PARAMS, "\"name\" is missing.")));
            return;
        }
        if (!arguments.isUndefined() && !arguments.isNull() && !arguments.isObject()){
            done(answer(rpc_error(id, INVALID_PARAMS, "\"arguments\" must be an object.")));
            return;
        }
        const std::string tool_name = name.toStdString();
        bool found = false;
        for (const PlayTool& tool : backend.tools()){
            found = found || tool.name == tool_name;
        }
        if (!found){
            done(answer(rpc_error(id, INVALID_PARAMS, "Unknown tool: " + name)));
            return;
        }
        const QByteArray compact = QJsonDocument(arguments.toObject()).toJson(QJsonDocument::Compact);
        backend.call(tool_name, std::string(compact.constData(), (size_t)compact.size()), [id, done](PlayResult result){
            done(answer(rpc_result(id, result_json(result))));
        });
        return;
    }
    done(answer(rpc_error(id, METHOD_NOT_FOUND, "Method not found: " + method)));
}

}   //  namespace



const std::vector<std::string>& mcp_protocol_versions(){
    static const std::vector<std::string> versions = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"};
    return versions;
}

std::string mcp_image_mime(const std::string& picture){
    if (picture.size() >= 8 && picture.compare(0, 8, "\x89PNG\r\n\x1a\n") == 0){
        return "image/png";
    }
    if (picture.size() >= 3 &&
        (unsigned char)picture[0] == 0xff && (unsigned char)picture[1] == 0xd8 && (unsigned char)picture[2] == 0xff
    ){
        return "image/jpeg";
    }
    return std::string();
}



McpProtocol::McpProtocol(McpBackend& backend)
    : m_backend(backend)
{}

void McpProtocol::handle(
    const QByteArray& body, const std::string& protocol_version,
    std::function<void(McpReply reply)> reply
){
    QJsonParseError parse_error;
    const QJsonDocument document = QJsonDocument::fromJson(body, &parse_error);
    if (parse_error.error != QJsonParseError::NoError || !(document.isObject() || document.isArray())){
        McpReply bad;
        bad.status = 400;
        bad.body = to_body(rpc_error(QJsonValue(), PARSE_ERROR, "The body is not JSON."));
        reply(std::move(bad));
        return;
    }

    if (document.isObject()){
        process_message(m_backend, document.object(), protocol_version, [reply](Outcome outcome){
            McpReply out;
            if (!outcome.response){
                out.status = 202;
            }else{
                out.status = outcome.status;
                out.body = to_body(*outcome.response);
            }
            reply(std::move(out));
        });
        return;
    }

    //  A batch (the revisions before 2025-06-18 allow it): the answers go
    //  out together once they are all there.
    const QJsonArray messages = document.array();
    if (messages.isEmpty()){
        McpReply bad;
        bad.status = 400;
        bad.body = to_body(rpc_error(QJsonValue(), INVALID_REQUEST, "An empty batch."));
        reply(std::move(bad));
        return;
    }
    struct Batch{
        size_t waiting = 0;
        QJsonArray answers;
        int status = 200;
        bool sent = false;
    };
    const std::shared_ptr<Batch> batch = std::make_shared<Batch>();
    batch->waiting = (size_t)messages.size();
    auto finish = [batch, reply]{
        if (batch->sent || batch->waiting > 0){
            return;
        }
        batch->sent = true;
        McpReply out;
        if (batch->answers.isEmpty()){
            out.status = 202;
        }else{
            out.status = batch->status;
            out.body = to_body(batch->answers);
        }
        reply(std::move(out));
    };
    for (const QJsonValue& message : messages){
        process_message(m_backend, message, protocol_version, [batch, finish](Outcome outcome){
            if (outcome.response){
                batch->answers.append(*outcome.response);
                if (outcome.status != 200){
                    batch->status = outcome.status;
                }
            }
            batch->waiting--;
            finish();
        });
    }
}



QByteArray McpHttpRequest::header(const char* name) const{
    const auto iter = headers.find(QByteArray(name));
    return iter == headers.end() ? QByteArray() : iter->second;
}

McpHttpParse parse_mcp_http_request(QByteArray& buffer, McpHttpRequest& request, bool& expect_continue){
    expect_continue = false;
    const qsizetype end = buffer.indexOf("\r\n\r\n");
    if (end < 0){
        return buffer.size() > MAX_HEADER_BYTES ? McpHttpParse::HEADERS_TOO_LARGE : McpHttpParse::INCOMPLETE;
    }
    if (end > MAX_HEADER_BYTES){
        return McpHttpParse::HEADERS_TOO_LARGE;
    }

    const QList<QByteArray> lines = buffer.left(end).split('\n');
    //  The request line: METHOD TARGET HTTP/1.x
    QByteArray first = lines.front();
    if (first.endsWith('\r')){
        first.chop(1);
    }
    const QList<QByteArray> parts = first.split(' ');
    if (parts.size() != 3 || parts[0].isEmpty() || parts[1].isEmpty() || !parts[2].startsWith("HTTP/1.")){
        return McpHttpParse::BAD;
    }
    for (char c : parts[0]){
        if (c < 'A' || c > 'Z'){
            return McpHttpParse::BAD;
        }
    }

    McpHttpRequest parsed;
    parsed.method = parts[0];
    parsed.target = parts[1];
    for (qsizetype i = 1; i < lines.size(); i++){
        QByteArray line = lines[i];
        if (line.endsWith('\r')){
            line.chop(1);
        }
        const qsizetype colon = line.indexOf(':');
        if (colon <= 0){
            return McpHttpParse::BAD;
        }
        const QByteArray name = line.left(colon).toLower();
        if (name != name.trimmed()){
            return McpHttpParse::BAD;
        }
        const QByteArray value = line.mid(colon + 1).trimmed();
        auto iter = parsed.headers.find(name);
        if (iter == parsed.headers.end()){
            parsed.headers.emplace(name, value);
        }else if (name == "content-length" || name == "host" || name == "authorization"){
            //  Said twice: a request that two readers read differently.
            return McpHttpParse::BAD;
        }else{
            iter->second += ", " + value;
        }
    }

    if (parsed.headers.count("transfer-encoding") != 0){
        return McpHttpParse::LENGTH_REQUIRED;
    }
    qint64 length = 0;
    const auto length_header = parsed.headers.find("content-length");
    if (length_header != parsed.headers.end()){
        bool ok = false;
        const QByteArray& text = length_header->second;
        length = text.toLongLong(&ok);
        if (!ok || length < 0 || text.startsWith('+') || text.startsWith('-')){
            return McpHttpParse::BAD;
        }
        if (length > MAX_BODY_BYTES){
            return McpHttpParse::BODY_TOO_LARGE;
        }
    }

    const qsizetype total = end + 4 + (qsizetype)length;
    if (buffer.size() < total){
        expect_continue = parsed.header("expect").toLower() == "100-continue";
        return McpHttpParse::INCOMPLETE;
    }
    parsed.body = buffer.mid(end + 4, (qsizetype)length);
    buffer.remove(0, total);
    request = std::move(parsed);
    return McpHttpParse::COMPLETE;
}

int check_mcp_request(const McpHttpRequest& request, int port, const std::string& token){
    //  Only this computer, by any of its names: a web page that was sent to
    //  the user's browser and then pointed at this port by a name of its own
    //  has another Host.
    const QByteArray suffix = ":" + QByteArray::number(port);
    const QByteArray hosts[3] = {"127.0.0.1" + suffix, "localhost" + suffix, "[::1]" + suffix};
    const QByteArray host = request.header("host").toLower();
    if (host.isEmpty()){
        return 400;
    }
    if (std::find(std::begin(hosts), std::end(hosts), host) == std::end(hosts)){
        return 403;
    }
    if (request.headers.count("origin") != 0){
        const QByteArray origin = request.header("origin").toLower();
        bool local = false;
        for (const QByteArray& allowed : hosts){
            local = local || origin == "http://" + allowed;
        }
        if (!local){
            return 403;
        }
    }

    //  The token. A server without one serves nobody.
    const QByteArray authorization = request.header("authorization");
    const QByteArray prefix = "bearer ";
    if (token.empty() || authorization.size() <= prefix.size() ||
        authorization.left(prefix.size()).toLower() != prefix ||
        !same_token(authorization.mid(prefix.size()).trimmed(), QByteArray::fromStdString(token))
    ){
        return 401;
    }

    if (request.target != "/mcp"){
        return 404;
    }
    if (request.method != "POST"){
        return 405;
    }
    return 0;
}

QByteArray mcp_http_response(int status, const QByteArray& body, bool keep_alive){
    QByteArray out = "HTTP/1.1 " + QByteArray::number(status) + " " + status_text(status) + "\r\n";
    if (status == 401){
        out += "WWW-Authenticate: Bearer\r\n";
    }
    if (status == 405){
        out += "Allow: POST\r\n";
    }
    if (status != 202 && !body.isEmpty()){
        out += "Content-Type: application/json\r\n";
    }
    out += "Content-Length: " + QByteArray::number(body.size()) + "\r\n";
    out += "Cache-Control: no-store\r\n";
    out += "X-Content-Type-Options: nosniff\r\n";
    out += keep_alive ? "Connection: keep-alive\r\n" : "Connection: close\r\n";
    out += "\r\n";
    out += body;
    return out;
}



struct McpServer::Connection{
    QTcpSocket* socket = nullptr;
    QByteArray buffer;
    QTimer* idle = nullptr;
    //  A request is being answered: the next one waits for it.
    bool busy = false;
    bool alive = true;
    bool sent_continue = false;
};

McpServer::McpServer(McpBackend& backend, std::string token)
    : m_backend(backend)
    , m_protocol(backend)
    , m_token(std::move(token))
{}

McpServer::~McpServer(){
    close();
}

bool McpServer::listen(int port, std::string& error){
    if (m_server){
        error = "The server is listening already.";
        return false;
    }
    if (port < 0 || port > 65535){
        error = "The port must be 0 to 65535.";
        return false;
    }
    if (m_token.empty()){
        error = "There is no token: the server would serve everybody.";
        return false;
    }
    std::unique_ptr<QTcpServer> server = std::make_unique<QTcpServer>();
    server->setMaxPendingConnections((int)MAX_CONNECTIONS);
    if (!server->listen(QHostAddress::LocalHost, (quint16)port)){
        error = server->errorString().toStdString();
        return false;
    }
    QTcpServer* raw = server.get();
    QObject::connect(raw, &QTcpServer::newConnection, raw, [this]{
        accept();
    });
    m_server = std::move(server);
    return true;
}

int McpServer::port() const{
    return m_server ? (int)m_server->serverPort() : 0;
}

void McpServer::close(){
    if (m_server){
        m_server->close();
    }
    std::list<std::shared_ptr<Connection>> connections = std::move(m_connections);
    m_connections.clear();
    for (const std::shared_ptr<Connection>& connection : connections){
        connection->alive = false;
        if (connection->socket != nullptr){
            QTcpSocket* socket = connection->socket;
            connection->socket = nullptr;
            socket->disconnect();
            socket->close();
            socket->deleteLater();
        }
    }
    m_server.reset();
}

void McpServer::accept(){
    while (m_server && m_server->hasPendingConnections()){
        QTcpSocket* socket = m_server->nextPendingConnection();
        if (socket == nullptr){
            return;
        }
        if (m_connections.size() >= MAX_CONNECTIONS){
            socket->close();
            socket->deleteLater();
            continue;
        }
        const std::shared_ptr<Connection> connection = std::make_shared<Connection>();
        connection->socket = socket;
        connection->idle = new QTimer(socket);
        connection->idle->setSingleShot(true);
        connection->idle->setInterval(IDLE_MS);
        m_connections.push_back(connection);

        QObject::connect(connection->idle, &QTimer::timeout, socket, [this, connection]{
            drop(connection);
        });
        QObject::connect(socket, &QTcpSocket::readyRead, socket, [this, connection]{
            if (!connection->alive || connection->socket == nullptr){
                return;
            }
            connection->buffer += connection->socket->readAll();
            connection->idle->start();
            process(connection);
        });
        QObject::connect(socket, &QTcpSocket::disconnected, socket, [this, connection]{
            drop(connection);
        });
        connection->idle->start();
    }
}

void McpServer::drop(const std::shared_ptr<Connection>& connection){
    if (!connection->alive){
        return;
    }
    connection->alive = false;
    m_connections.remove(connection);
    if (connection->socket != nullptr){
        QTcpSocket* socket = connection->socket;
        connection->socket = nullptr;
        socket->disconnect();
        socket->close();
        socket->deleteLater();
    }
}

void McpServer::process(const std::shared_ptr<Connection>& connection){
    //  What a request ends in: the answer, and whether the connection goes on.
    auto send = [this, connection](int status, const QByteArray& body, bool keep_alive){
        if (!connection->alive || connection->socket == nullptr){
            return;
        }
        connection->socket->write(mcp_http_response(status, body, keep_alive));
        connection->socket->flush();
        connection->busy = false;
        if (!keep_alive){
            //  Closed once what was written is out.
            QTcpSocket* socket = connection->socket;
            QObject::connect(socket, &QTcpSocket::bytesWritten, socket, [this, connection]{
                if (connection->socket != nullptr && connection->socket->bytesToWrite() == 0){
                    drop(connection);
                }
            });
            if (socket->bytesToWrite() == 0){
                drop(connection);
            }
            return;
        }
        process(connection);
    };

    while (connection->alive && !connection->busy && !connection->buffer.isEmpty()){
        McpHttpRequest request;
        bool expect_continue = false;
        const McpHttpParse parsed = parse_mcp_http_request(connection->buffer, request, expect_continue);
        switch (parsed){
        case McpHttpParse::INCOMPLETE:
            if (expect_continue && !connection->sent_continue && connection->socket != nullptr){
                connection->sent_continue = true;
                connection->socket->write("HTTP/1.1 100 Continue\r\n\r\n");
            }
            return;
        case McpHttpParse::BAD:
            send(400, QByteArray(), false);
            return;
        case McpHttpParse::HEADERS_TOO_LARGE:
            send(431, QByteArray(), false);
            return;
        case McpHttpParse::BODY_TOO_LARGE:
            send(413, QByteArray(), false);
            return;
        case McpHttpParse::LENGTH_REQUIRED:
            send(411, QByteArray(), false);
            return;
        case McpHttpParse::COMPLETE:
            break;
        }
        connection->sent_continue = false;
        const bool keep_alive = request.header("connection").toLower() != "close";

        const int refused = check_mcp_request(request, port(), m_token);
        if (refused != 0){
            //  Nothing is said about why, but the status.
            send(refused, QByteArray(), keep_alive && refused != 403);
            if (!keep_alive || refused == 403){
                return;
            }
            continue;
        }

        connection->busy = true;
        const std::string version = request.header("mcp-protocol-version").toStdString();
        m_protocol.handle(request.body, version, [send, keep_alive](McpReply reply){
            send(reply.status, reply.body, keep_alive);
        });
    }
}



}
}
}
