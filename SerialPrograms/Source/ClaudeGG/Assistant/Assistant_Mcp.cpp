/*  ClaudeGG Assistant: MCP Session
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <deque>
#include <functional>
#include <map>
#include <utility>
#include <QByteArray>
#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QRandomGenerator>
#include <QSaveFile>
#include <QString>
#include "Common/Cpp/CancellableScope.h"
#include "Common/Cpp/Concurrency/Mutex.h"
#include "Assistant_McpServer.h"
#include "Assistant_Settings.h"
#include "Assistant_Mcp.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace Assistant{


namespace{

//  Runs "work" in the thread of the interface, some time soon. False if
//  there is no interface (any more).
bool post(std::function<void()> work){
    QCoreApplication* application = QCoreApplication::instance();
    if (application == nullptr){
        return false;
    }
    return QMetaObject::invokeMethod(application, std::move(work), Qt::QueuedConnection);
}

//  How long a waiting program sleeps between two looks.
const std::chrono::milliseconds LOOK_EVERY(20);

}


std::string mcp_token(const std::string& settings_folder, bool make_new, std::string& error){
    SecretStore store(QString::fromStdString(settings_folder) + "ClaudeGG-Mcp-Token.json");
    //  Nothing shorter than what this makes counts: a token that somebody
    //  typed into the file, or that an older build made, is not trusted.
    const int LENGTH = 32;
    if (!make_new && store.get(Secret::MCP_TOKEN).size() == 2 * LENGTH){
        return store.get(Secret::MCP_TOKEN).toStdString();
    }
    QByteArray bytes(LENGTH, 0);
    QRandomGenerator* generator = QRandomGenerator::system();
    for (int index = 0; index < LENGTH; index++){
        bytes[index] = (char)(generator->generate() & 0xff);
    }
    const QString token = QString::fromLatin1(bytes.toHex());
    QString message;
    if (!store.set(Secret::MCP_TOKEN, token, message)){
        error = message.toStdString();
    }
    return token.toStdString();
}


std::string mcp_connect_text(int port, const std::string& token){
    const std::string url = "http://127.0.0.1:" + std::to_string(port) + "/mcp";
    return
        "Claude GG: connecting Claude Code to the program (Claude Plays, \"Claude Code plays\")\r\n"
        "\r\n"
        "1. Once, in a terminal (Windows Terminal, PowerShell or cmd), add the program's server to Claude Code:\r\n"
        "\r\n"
        "   claude mcp add --transport http claude-gg " + url + " --header \"Authorization: Bearer " + token + "\"\r\n"
        "\r\n"
        "2. Start the program Claude Plays with \"Who plays\" set to Claude Code. The log says when it listens.\r\n"
        "\r\n"
        "3. Start Claude Code and give it the goal, for example: \"Use the claude-gg tools to play the game on the "
        "screen: ...\". Its tools are the game's (look, press, ...) and done.\r\n"
        "\r\n"
        "4. Claude Code asks before it uses a tool. Allow the tools of claude-gg (for this session or always), "
        "or every press waits for you.\r\n"
        "\r\n"
        "Good to know:\r\n"
        "- The server runs only while the program does, and listens on this computer only (127.0.0.1). Port " +
        std::to_string(port) + " is set in the options of the program.\r\n"
        "- The token above is what keeps other programs and web pages on this computer from using the server. "
        "Do not post this file. For a new token, delete ClaudeGG-Mcp-Token.json in the settings folder and add "
        "the server to Claude Code again (\"claude mcp remove claude-gg\" first).\r\n"
        "- Claude Code runs on your Claude subscription or your own API key: the program has no key of its own "
        "in this mode and pays nothing. The pictures of the game go to whatever Claude Code is set to use.\r\n";
}

std::string write_mcp_connect_file(const std::string& settings_folder, int port, const std::string& token, std::string& error){
    const QString path = QString::fromStdString(settings_folder) + "ClaudeGG-Mcp-Connect.txt";
    QDir().mkpath(QFileInfo(path).absolutePath());
    QSaveFile file(path);
    if (!file.open(QIODevice::WriteOnly)){
        error = "The file could not be written (" + file.errorString().toStdString() + ").";
        return std::string();
    }
    const std::string text = mcp_connect_text(port, token);
    file.write(text.data(), (qint64)text.size());
    if (!file.commit()){
        error = "The file could not be written (" + file.errorString().toStdString() + ").";
        return std::string();
    }
    return path.toStdString();
}


struct McpSession::Shared : public McpBackend, public std::enable_shared_from_this<McpSession::Shared>{
    Setup setup;

    //  For both threads, under the lock.
    mutable Mutex lock;
    std::deque<PlayCall> queue;
    uint64_t clients = 0;
    uint64_t calls = 0;
    //  The answer of the start.
    bool started = false;
    std::string start_error;
    int port = 0;

    //  Only in the thread of the interface.
    std::unique_ptr<McpServer> server;
    uint64_t numbering = 0;
    std::map<std::string, std::function<void(PlayResult result)>> waiting;

    virtual std::string server_name() const override{
        return setup.server_name;
    }
    virtual std::string server_version() const override{
        return setup.version;
    }
    virtual std::string instructions() const override{
        return setup.instructions;
    }
    virtual std::vector<PlayTool> tools() const override{
        return setup.tools;
    }
    virtual void initialized() override{
        LockGuard<Mutex> lg(lock);
        clients++;
    }
    virtual void call(
        const std::string& name, const std::string& arguments,
        std::function<void(PlayResult result)> done
    ) override{
        PlayCall incoming;
        incoming.id = "mcp-" + std::to_string(++numbering);
        incoming.name = name;
        incoming.input = arguments;
        waiting[incoming.id] = std::move(done);
        LockGuard<Mutex> lg(lock);
        calls++;
        queue.push_back(std::move(incoming));
    }

    void open(){
        std::string error;
        std::unique_ptr<McpServer> made = std::make_unique<McpServer>(*this, setup.token);
        const bool listening = made->listen(setup.port, error);
        if (listening){
            server = std::move(made);
        }
        LockGuard<Mutex> lg(lock);
        start_error = listening ? std::string() : error;
        port = listening ? server->port() : 0;
        started = true;
    }

    void close(){
        //  The calls that wait are answered first, while their connections
        //  are still there: the client is told, not left hanging.
        std::map<std::string, std::function<void(PlayResult result)>> left = std::move(waiting);
        waiting.clear();
        for (auto& entry : left){
            PlayResult result;
            result.is_error = true;
            result.text = "The program stopped: the session is over.";
            entry.second(std::move(result));
        }
        server.reset();
    }

    void finish(const std::string& id, PlayResult result){
        auto iter = waiting.find(id);
        if (iter == waiting.end()){
            return;
        }
        std::function<void(PlayResult result)> done = std::move(iter->second);
        waiting.erase(iter);
        done(std::move(result));
    }
};


McpSession::McpSession(Setup setup)
    : m_shared(std::make_shared<Shared>())
{
    m_shared->setup = std::move(setup);
}

McpSession::~McpSession(){
    //  The server goes where it lives: in the thread of the interface.
    const std::shared_ptr<Shared> shared = m_shared;
    post([shared]{
        shared->close();
    });
}

std::string McpSession::start(CancellableScope& scope){
    const std::shared_ptr<Shared> shared = m_shared;
    if (!post([shared]{ shared->open(); })){
        return "The program has no interface: nothing can listen.";
    }
    while (true){
        {
            LockGuard<Mutex> lg(m_shared->lock);
            if (m_shared->started){
                return m_shared->start_error;
            }
        }
        scope.wait_for(LOOK_EVERY);
    }
}

int McpSession::port() const{
    LockGuard<Mutex> lg(m_shared->lock);
    return m_shared->port;
}

bool McpSession::wait(CancellableScope& scope, std::chrono::milliseconds timeout, PlayCall& call){
    const std::chrono::steady_clock::time_point until = std::chrono::steady_clock::now() + timeout;
    while (true){
        //  A program that was stopped runs nothing more, whatever is waiting.
        scope.throw_if_cancelled();
        {
            LockGuard<Mutex> lg(m_shared->lock);
            if (!m_shared->queue.empty()){
                call = std::move(m_shared->queue.front());
                m_shared->queue.pop_front();
                return true;
            }
        }
        if (std::chrono::steady_clock::now() >= until){
            return false;
        }
        scope.wait_for(LOOK_EVERY);
    }
}

void McpSession::finish(const PlayCall& call, PlayResult result){
    const std::shared_ptr<Shared> shared = m_shared;
    const std::string id = call.id;
    post([shared, id, result]{
        shared->finish(id, result);
    });
}

uint64_t McpSession::clients() const{
    LockGuard<Mutex> lg(m_shared->lock);
    return m_shared->clients;
}

uint64_t McpSession::calls() const{
    LockGuard<Mutex> lg(m_shared->lock);
    return m_shared->calls;
}



}
}
}
