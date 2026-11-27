/*  ClaudeGG Assistant: Self Test
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <deque>
#include <map>
#include <utility>
#include <cstdlib>
#include <QColor>
#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QImage>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QObject>
#include <QSslSocket>
#include <QStringList>
#include <QTimer>
#include <QUrl>
#include <QUrlQuery>
#include "CommonFramework/ImageTypes/ImageRGB32.h"
#include "Assistant_Claude.h"
#include "Assistant_Mcp.h"
#include "Assistant_McpServer.h"
#include "Assistant_Play.h"
#include "Assistant_Settings.h"
#include "Assistant_Workspace.h"
#include "Assistant_SelfTest.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace Assistant{


const char* const TestBackend::BASE_BRANCH = "main";
const char* const TestBackend::SOURCE_FILE =
    "SerialPrograms/Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStory.cpp";


namespace{

const char* const TEST_REPOSITORY = "/repos/MajorLOL/ClaudeGG";

//  One answer of the Messages API as it streams in.
QByteArray make_stream(const QJsonArray& blocks, const QString& stop_reason){
    QByteArray stream;
    const auto event = [&](const char* name, const QJsonObject& data){
        stream += "event: ";
        stream += name;
        stream += "\ndata: " + QJsonDocument(data).toJson(QJsonDocument::Compact) + "\n\n";
    };
    event("message_start", QJsonObject{{"type", "message_start"}, {"message", QJsonObject{
        {"id", "msg_test"}, {"type", "message"}, {"role", "assistant"}, {"content", QJsonArray()},
        {"model", "claude-sonnet-5-5"},
        {"usage", QJsonObject{
            {"input_tokens", 1800}, {"cache_read_input_tokens", 3100},
            {"cache_creation_input_tokens", 400}, {"output_tokens", 1},
        }},
    }}});
    int index = 0;
    for (const QJsonValue& value : blocks){
        const QJsonObject block = value.toObject();
        if (block.value("type").toString() == "text"){
            event("content_block_start", QJsonObject{
                {"type", "content_block_start"}, {"index", index},
                {"content_block", QJsonObject{{"type", "text"}, {"text", ""}}},
            });
            const QString text = block.value("text").toString();
            for (qsizetype at = 0; at < text.size(); at += 24){
                event("content_block_delta", QJsonObject{
                    {"type", "content_block_delta"}, {"index", index},
                    {"delta", QJsonObject{{"type", "text_delta"}, {"text", text.mid(at, 24)}}},
                });
            }
        }else{
            event("content_block_start", QJsonObject{
                {"type", "content_block_start"}, {"index", index},
                {"content_block", QJsonObject{
                    {"type", "tool_use"}, {"id", block.value("id")}, {"name", block.value("name")},
                    {"input", QJsonObject()},
                }},
            });
            const QString json = QString::fromUtf8(
                QJsonDocument(block.value("input").toObject()).toJson(QJsonDocument::Compact)
            );
            for (qsizetype at = 0; at < json.size(); at += 40){
                event("content_block_delta", QJsonObject{
                    {"type", "content_block_delta"}, {"index", index},
                    {"delta", QJsonObject{{"type", "input_json_delta"}, {"partial_json", json.mid(at, 40)}}},
                });
            }
        }
        event("content_block_stop", QJsonObject{{"type", "content_block_stop"}, {"index", index}});
        index++;
    }
    event("message_delta", QJsonObject{
        {"type", "message_delta"},
        {"delta", QJsonObject{{"stop_reason", stop_reason}}},
        {"usage", QJsonObject{{"output_tokens", 240}}},
    });
    event("message_stop", QJsonObject{{"type", "message_stop"}});
    return stream;
}

HttpResponse json_response(int status, const QJsonValue& value){
    HttpResponse response;
    response.status = status;
    response.body = value.isArray()
        ? QJsonDocument(value.toArray()).toJson(QJsonDocument::Compact)
        : QJsonDocument(value.toObject()).toJson(QJsonDocument::Compact);
    return response;
}

HttpResponse not_found(){
    return json_response(404, QJsonObject{{"message", "Not Found"}});
}

}



struct TestBackend::Data{
    //  Claude: the answers to come.
    std::deque<QByteArray> answers;
    int claude_requests = 0;
    int next_call = 1;

    //  GitHub: files by their id, the files of each tree, the commits, and
    //  where each branch is.
    struct Commit{
        QString tree;
        QString parent;
    };
    std::map<QString, QByteArray> blobs;
    std::map<QString, std::map<QString, QString>> trees;
    std::map<QString, Commit> commits;
    std::map<QString, QString> refs;
    int counter = 0;

    QString new_id(const QByteArray& of){
        counter++;
        return QString::fromLatin1(
            QCryptographicHash::hash(of + QByteArray::number(counter), QCryptographicHash::Sha1).toHex()
        );
    }
    QString add_blob(const QByteArray& bytes){
        const QString id = QString::fromLatin1(
            QCryptographicHash::hash("blob " + bytes, QCryptographicHash::Sha1).toHex()
        );
        blobs[id] = bytes;
        return id;
    }
    const std::map<QString, QString>* files_of(const QString& commit) const{
        const auto entry = commits.find(commit);
        if (entry == commits.end()){
            return nullptr;
        }
        const auto tree = trees.find(entry->second.tree);
        return tree == trees.end() ? nullptr : &tree->second;
    }

    //  The answer to a request. For Claude's, "stream" gets the answer.
    HttpResponse answer(const HttpRequest& request, QByteArray& stream){
        const QString host = request.url.host();
        QString path = request.url.path(QUrl::FullyDecoded);
        const QString method = QString::fromLatin1(request.method);

        if (host == "api.anthropic.com"){
            claude_requests++;
            HttpResponse response;
            if (answers.empty()){
                return json_response(500, QJsonObject{
                    {"type", "error"},
                    {"error", QJsonObject{{"type", "api_error"}, {"message", "The test has no answer left."}}},
                });
            }
            response.status = 200;
            stream = answers.front();
            answers.pop_front();
            return response;
        }
        if (host == "raw.githubusercontent.com"){
            //  /owner/repository/commit/path
            const QString commit = path.section('/', 3, 3);
            const QString file = path.section('/', 4);
            const std::map<QString, QString>* files = files_of(commit);
            HttpResponse response;
            if (files == nullptr || files->find(file) == files->end()){
                response.status = 404;
                return response;
            }
            response.status = 200;
            response.body = blobs[files->at(file)];
            return response;
        }
        if (host != "api.github.com" || !path.startsWith(QLatin1String(TEST_REPOSITORY))){
            return not_found();
        }
        path = path.mid(QString::fromLatin1(TEST_REPOSITORY).size());
        const QJsonObject body = QJsonDocument::fromJson(request.body).object();

        if (method == "GET" && path.startsWith("/git/ref/heads/")){
            const QString branch = path.mid(QString("/git/ref/heads/").size());
            const auto ref = refs.find(branch);
            if (ref == refs.end()){
                return not_found();
            }
            return json_response(200, QJsonObject{{"object", QJsonObject{{"sha", ref->second}}}});
        }
        if (method == "GET" && path.startsWith("/git/trees/")){
            const std::map<QString, QString>* files = files_of(path.mid(QString("/git/trees/").size()));
            if (files == nullptr){
                return not_found();
            }
            QJsonArray entries;
            for (const auto& file : *files){
                entries.append(QJsonObject{
                    {"path", file.first}, {"mode", "100644"}, {"type", "blob"}, {"sha", file.second},
                    {"size", (double)blobs[file.second].size()},
                });
            }
            return json_response(200, QJsonObject{{"tree", entries}, {"truncated", false}});
        }
        if (method == "GET" && path.startsWith("/contents/")){
            const QString commit = QUrlQuery(request.url).queryItemValue("ref");
            const std::map<QString, QString>* files = files_of(commit);
            const QString file = path.mid(QString("/contents/").size());
            HttpResponse response;
            if (files == nullptr || files->find(file) == files->end()){
                return not_found();
            }
            response.status = 200;
            response.body = blobs[files->at(file)];
            return response;
        }
        if (method == "GET" && path.startsWith("/git/commits/")){
            const auto commit = commits.find(path.mid(QString("/git/commits/").size()));
            if (commit == commits.end()){
                return not_found();
            }
            return json_response(200, QJsonObject{{"tree", QJsonObject{{"sha", commit->second.tree}}}});
        }
        if (method == "POST" && path == "/git/blobs"){
            const QString id = add_blob(QByteArray::fromBase64(body.value("content").toString().toLatin1()));
            return json_response(201, QJsonObject{{"sha", id}});
        }
        if (method == "POST" && path == "/git/trees"){
            const auto base = trees.find(body.value("base_tree").toString());
            if (base == trees.end()){
                return json_response(422, QJsonObject{{"message", "base_tree is not a tree"}});
            }
            std::map<QString, QString> files = base->second;
            for (const QJsonValue& value : body.value("tree").toArray()){
                const QJsonObject entry = value.toObject();
                files[entry.value("path").toString()] = entry.value("sha").toString();
            }
            const QString id = new_id("tree");
            trees[id] = std::move(files);
            return json_response(201, QJsonObject{{"sha", id}});
        }
        if (method == "POST" && path == "/git/commits"){
            Commit commit;
            commit.tree = body.value("tree").toString();
            commit.parent = body.value("parents").toArray().first().toString();
            if (trees.find(commit.tree) == trees.end() || commits.find(commit.parent) == commits.end()){
                return json_response(422, QJsonObject{{"message", "Not a tree or not a commit"}});
            }
            const QString id = new_id("commit");
            commits[id] = commit;
            return json_response(201, QJsonObject{{"sha", id}});
        }
        if (method == "POST" && path == "/git/refs"){
            const QString branch = body.value("ref").toString().mid(QString("refs/heads/").size());
            if (branch.isEmpty() || refs.find(branch) != refs.end()){
                return json_response(422, QJsonObject{{"message", "Reference already exists"}});
            }
            refs[branch] = body.value("sha").toString();
            return json_response(201, QJsonObject{{"ref", body.value("ref")}});
        }
        if (method == "PATCH" && path.startsWith("/git/refs/heads/")){
            const QString branch = path.mid(QString("/git/refs/heads/").size());
            if (refs.find(branch) == refs.end()){
                return not_found();
            }
            refs[branch] = body.value("sha").toString();
            return json_response(200, QJsonObject{{"ref", "refs/heads/" + branch}});
        }
        if (method == "GET" && path.startsWith("/compare/")){
            return json_response(200, QJsonObject{{"ahead_by", 0}, {"behind_by", 0}, {"files", QJsonArray()}});
        }
        return not_found();
    }
};


namespace{

class TestCall : public HttpCall{
public:
    virtual void abort() override{
        aborted = true;
    }
    bool aborted = false;
};

class TestTransport : public HttpTransport{
public:
    explicit TestTransport(std::shared_ptr<TestBackend::Data> data)
        : m_data(std::move(data))
    {}

    virtual std::shared_ptr<HttpCall> send(
        const HttpRequest& request, DataHandler on_data, DoneHandler on_done
    ) override{
        std::shared_ptr<TestCall> call = std::make_shared<TestCall>();
        QByteArray stream;
        const HttpResponse response = m_data->answer(request, stream);
        //  As the network: the answer comes from the event loop.
        QTimer::singleShot(0, &m_context, [call, response, stream, on_data, on_done]{
            if (call->aborted){
                return;
            }
            if (on_data && !stream.isEmpty()){
                //  In pieces, as a stream comes in.
                for (qsizetype at = 0; at < stream.size() && !call->aborted; at += 300){
                    on_data(stream.mid(at, 300));
                }
            }
            if (!call->aborted && on_done){
                HttpResponse whole = response;
                if (!on_data){
                    whole.body += stream;
                }
                on_done(whole);
            }
        });
        return call;
    }

private:
    std::shared_ptr<TestBackend::Data> m_data;
    QObject m_context;
};

}


TestBackend::TestBackend()
    : m_data(std::make_shared<Data>())
{
    //  A repository with one source file and the list of files to build.
    QByteArray source = "/*  Pokemon FRLG Autostory\r\n *\r\n */\r\n\r\nnamespace PokemonAutomation{\r\n\r\n";
    for (int line = 1; line <= 36; line++){
        source += "//  Line " + QByteArray::number(line) + " of the test's source file.\r\n";
    }
    source +=
        "            if (league_again_losses > 6){\r\n"
        "                throw UserSetupError(env.logger(), \"The League was lost seven times in a row.\");\r\n"
        "            }\r\n"
        "\r\n}\r\n";
    std::map<QString, QString> files;
    files[QString::fromLatin1(SOURCE_FILE)] = m_data->add_blob(source);
    files["SerialPrograms/cmake/SourceFiles.cmake"] = m_data->add_blob(
        "    Source/VideoGames/PokemonFRLG/Programs/AutoStory/PokemonFRLG_AutoStory.cpp\r\n"
    );
    const QString tree = m_data->new_id("tree");
    m_data->trees[tree] = files;
    const QString commit = m_data->new_id("commit");
    m_data->commits[commit] = Data::Commit{tree, QString()};
    m_data->refs[QString::fromLatin1(BASE_BRANCH)] = commit;
}

TestBackend::~TestBackend() = default;

std::unique_ptr<HttpTransport> TestBackend::make_transport(){
    return std::make_unique<TestTransport>(m_data);
}

void TestBackend::claude_calls(const QString& tool, const QJsonObject& input, const QString& text_before){
    QJsonArray blocks;
    if (!text_before.isEmpty()){
        blocks.append(QJsonObject{{"type", "text"}, {"text", text_before}});
    }
    blocks.append(QJsonObject{
        {"type", "tool_use"},
        {"id", "toolu_test_" + QString::number(m_data->next_call++)},
        {"name", tool},
        {"input", input},
    });
    m_data->answers.push_back(make_stream(blocks, "tool_use"));
}

void TestBackend::claude_says(const QString& text){
    m_data->answers.push_back(make_stream(QJsonArray{QJsonObject{{"type", "text"}, {"text", text}}}, "end_turn"));
}

bool TestBackend::has_branch(const QString& branch) const{
    return m_data->refs.find(branch) != m_data->refs.end();
}

QByteArray TestBackend::file_on(const QString& branch, const QString& path) const{
    const auto ref = m_data->refs.find(branch);
    if (ref == m_data->refs.end()){
        return QByteArray();
    }
    const std::map<QString, QString>* files = m_data->files_of(ref->second);
    if (files == nullptr || files->find(path) == files->end()){
        return QByteArray();
    }
    return m_data->blobs[files->at(path)];
}

int TestBackend::requests_to_claude() const{
    return m_data->claude_requests;
}



//  The checks.

namespace{

//  A stream as the documentation of the API shows it: some text, then a
//  tool call whose input comes in pieces.
const char* const DOCUMENTED_STREAM = R"sse(event: message_start
data: {"type":"message_start","message":{"id":"msg_014p7gG3wDgGV9EUtLvnow3U","type":"message","role":"assistant","model":"claude-opus-5","stop_sequence":null,"usage":{"input_tokens":472,"output_tokens":2},"content":[],"stop_reason":null}}

event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}

event: ping
data: {"type": "ping"}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Okay"}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":", let's check"}}

event: content_block_stop
data: {"type":"content_block_stop","index":0}

event: content_block_start
data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"toolu_01T1x1fJ34qAmk2tNTrN7Up6","name":"get_weather","input":{}}}

event: content_block_delta
data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\"location\":"}}

event: content_block_delta
data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":" \"San"}}

event: content_block_delta
data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":" Francisco, CA\"}"}}

event: content_block_stop
data: {"type":"content_block_stop","index":1}

event: message_delta
data: {"type":"message_delta","delta":{"stop_reason":"tool_use","stop_sequence":null},"usage":{"output_tokens":89}}

event: message_stop
data: {"type":"message_stop"}

)sse";

//  An answer that starts with a thinking block, as the current models send
//  it: no text in it, and a signature that has to go back unchanged.
const char* const THINKING_STREAM = R"sse(event: message_start
data: {"type":"message_start","message":{"id":"msg_01","type":"message","role":"assistant","content":[],"model":"claude-sonnet-5-5","usage":{"input_tokens":10,"cache_read_input_tokens":900,"cache_creation_input_tokens":50,"output_tokens":1}}}

event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":"","signature":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"signature_delta","signature":"EqQBCgIYAhIM1gbcDa9GJwZA2b3hGgxBdjrkzLoky3dl1pkiMOYds"}}

event: content_block_stop
data: {"type":"content_block_stop","index":0}

event: content_block_start
data: {"type":"content_block_start","index":1,"content_block":{"type":"text","text":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"It is **21**."}}

event: content_block_stop
data: {"type":"content_block_stop","index":1}

event: message_delta
data: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},"usage":{"output_tokens":40}}

event: message_stop
data: {"type":"message_stop"}

)sse";

bool about_equal(double a, double b){
    const double difference = a - b;
    return difference < 1e-9 && difference > -1e-9;
}

}


CheckResult run_checks(const QString& folder, const std::function<void(const QString& line)>& report){
    CheckResult result;
    const auto check = [&](bool ok, const char* what){
        result.checks++;
        if (!ok){
            result.failed++;
            if (report){
                report(QString::fromLatin1(what));
            }
        }
    };

    //  Claude and GitHub are only reached over a secure connection: the
    //  build has to bring along what Qt needs for one.
    check(QSslSocket::supportsSsl(), "secure connections (TLS) can be made");

    //  The API's stream, whole and cut into pieces of several sizes.
    for (int size : {1, 7, 4096}){
        MessageStream stream;
        QString text;
        QString tool;
        stream.on_text = [&](const QString& more){
            text += more;
        };
        stream.on_tool = [&](const QString& name){
            tool = name;
        };
        //  With the line ends of a stream, whatever those of this file are.
        QByteArray data(DOCUMENTED_STREAM);
        data.replace("\r\n", "\n");
        for (qsizetype at = 0; at < data.size(); at += size){
            stream.feed(data.mid(at, size));
        }
        stream.finish();
        const QJsonArray content = stream.content();
        check(stream.complete() && !stream.failed(), "the documented stream is read to its end");
        check(stream.stop_reason() == "tool_use", "the stream's stop reason");
        check(text == "Okay, let's check", "the stream's text");
        check(tool == "get_weather", "the stream's tool call is announced");
        check(content.size() == 2, "the stream has two blocks");
        check(
            content[1].toObject().value("input").toObject().value("location").toString() == "San Francisco, CA",
            "the tool call's input is put together from its pieces"
        );
        check(content[1].toObject().value("id").toString() == "toolu_01T1x1fJ34qAmk2tNTrN7Up6", "the tool call's id");
        check(stream.usage().input == 472 && stream.usage().output == 89, "the stream's token counts");
        check(stream.broken_tool_calls().isEmpty(), "no tool call counts as broken");
    }
    {
        MessageStream stream;
        QByteArray data(THINKING_STREAM);
        //  As a server sends it.
        data.replace("\r\n", "\n");
        data.replace("\n", "\r\n");
        for (qsizetype at = 0; at < data.size(); at += 11){
            stream.feed(data.mid(at, 11));
        }
        stream.finish();
        const QJsonArray content = stream.content();
        check(stream.complete() && content.size() == 2, "a stream with a thinking block is read");
        const QJsonObject thinking = content[0].toObject();
        check(thinking.value("type").toString() == "thinking", "the thinking block stays a block");
        check(
            thinking.value("signature").toString() == "EqQBCgIYAhIM1gbcDa9GJwZA2b3hGgxBdjrkzLoky3dl1pkiMOYds",
            "the thinking block's signature is kept as it came"
        );
        check(thinking.value("thinking").isString() && thinking.value("thinking").toString().isEmpty(), "its empty text is kept");
        check(
            stream.usage().cache_read == 900 && stream.usage().cache_write == 50,
            "the tokens read from and written to the cache"
        );
    }
    {
        MessageStream stream;
        stream.feed("event: error\ndata: {\"type\": \"error\", \"error\": {\"type\": \"overloaded_error\", \"message\": \"Overloaded\"}}\n\n");
        stream.finish();
        check(stream.failed() && !stream.complete() && stream.error_type() == "overloaded_error", "an error in the stream");
    }

    //  What a request costs.
    {
        double usd = 0;
        check(estimate_cost("claude-sonnet-5-5", 1000000, 0, 0, 0, usd) && about_equal(usd, 2.0), "the price of Sonnet's input");
        check(
            estimate_cost("claude-sonnet-5-5", 0, 1000000, 1000000, 1000000, usd) && about_equal(usd, 2.5 + 0.10 + 10.0),
            "the prices of Sonnet's cache and output"
        );
        check(estimate_cost("claude-haiku-5-5", 50000, 0, 0, 1000, usd) && about_equal(usd, 0.0055), "the price of Haiku");
        check(
            estimate_cost("claude-haiku-5-5", 150000, 0, 0, 1000, usd) && about_equal(usd, 5 * 0.0155),
            "the price of Haiku for a long request"
        );
        check(estimate_cost("claude-opus-5-5", 0, 0, 1000000, 0, usd) && about_equal(usd, 0.20), "the price of Opus's cache");
        check(!estimate_cost("some-other-model", 1, 1, 1, 1, usd), "a model without a known price");
        Usage usage;
        usage.input = 12400;
        usage.requests = 1;
        usage.cost_usd = 0.031;
        check(usage_text(usage) == "12.4k tokens, about $0.03", "the text of the meter");
    }

    //  A request's body: what the API documents, and nothing it refuses.
    {
        class NoTransport : public HttpTransport{
        public:
            virtual std::shared_ptr<HttpCall> send(const HttpRequest&, DataHandler, DoneHandler) override{
                return nullptr;
            }
        };
        NoTransport transport;
        ClaudeClient client(transport, []{
            return QString();
        });
        ClaudeRequest request;
        request.model = "claude-sonnet-5-5";
        request.system = "Instructions.";
        request.effort = "low";
        request.messages = QJsonArray{QJsonObject{{"role", "user"}, {"content", "Hello"}}};
        const QJsonObject body = QJsonDocument::fromJson(client.request_body(request)).object();
        check(
            body.value("model").toString() == "claude-sonnet-5-5" && body.value("stream").toBool() &&
            body.value("max_tokens").toInt() > 0 && body.value("system").toString() == "Instructions.",
            "the body of a request"
        );
        check(body.value("cache_control").toObject().value("type").toString() == "ephemeral", "the request asks for caching");
        check(body.value("output_config").toObject().value("effort").toString() == "low", "the request's effort");
        check(
            !body.contains("temperature") && !body.contains("top_p") && !body.contains("top_k") &&
            !body.contains("tool_choice") && !body.contains("tools"),
            "the request has nothing the API refuses"
        );
    }

    //  The workspace of the API: named for a key that was not made for one,
    //  and words for the user when the API misses it.
    {
        class NoTransport : public HttpTransport{
        public:
            virtual std::shared_ptr<HttpCall> send(const HttpRequest&, DataHandler, DoneHandler) override{
                return nullptr;
            }
        };
        //  A header's value, "(none)" or "(twice)".
        const auto header_of = [](const std::vector<HttpHeader>& headers, const char* name){
            QByteArray value = "(none)";
            int found = 0;
            for (const HttpHeader& header : headers){
                if (header.name == name){
                    value = header.value;
                    found++;
                }
            }
            return found > 1 ? QByteArray("(twice)") : value;
        };
        NoTransport transport;
        QString workspace_id;
        ClaudeClient client(
            transport,
            []{
                return QString("  sk-ant-test-0123456789\n");
            },
            [&workspace_id]{
                return workspace_id;
            }
        );
        std::vector<HttpHeader> headers = client.request_headers();
        check(
            header_of(headers, "x-api-key") == "sk-ant-test-0123456789" &&
            header_of(headers, "anthropic-version").startsWith("20") &&
            header_of(headers, "content-type") == "application/json",
            "the headers of a request"
        );
        check(header_of(headers, "anthropic-workspace-id") == "(none)", "no workspace is named unless one is set");
        workspace_id = " wrkspc_01JwQvzr7rXLA5AGx3HKfFUJ ";
        headers = client.request_headers();
        check(
            header_of(headers, "anthropic-workspace-id") == "wrkspc_01JwQvzr7rXLA5AGx3HKfFUJ",
            "the workspace that is set is named"
        );

        const QString unscoped =
            "This API key is not scoped to a workspace, so this request must include the anthropic-workspace-id "
            "header with the ID of the workspace to use. Add the header, or use an API key that is scoped to a "
            "workspace.";
        const QString told = api_error_text("invalid_request_error", 400, unscoped, QString(), false);
        check(
            told.contains("was not made for one workspace") && told.contains("settings of this panel") &&
            told.contains(unscoped),
            "a key without a workspace: what to do about it"
        );
        check(
            api_error_text(
                "invalid_request_error", 400, "anthropic-workspace-id header must be a valid workspace ID.",
                QString(), true
            ).contains("did not take the workspace ID"),
            "a workspace ID the API does not take"
        );
        check(
            api_error_text("not_found_error", 404, "Not found", QString(), true).contains("workspace ID") &&
            !api_error_text("not_found_error", 404, "model: claude-none", QString(), false).contains("workspace"),
            "the workspace ID is pointed at only when one was named"
        );
        check(
            clean_workspace_id("  wrkspc_01Ab-Z9\r\nx-other: y ") == "wrkspc_01Ab-Z9x-othery" &&
            clean_workspace_id(QString()).isEmpty(),
            "a workspace ID is letters, digits, _ and - alone"
        );
    }

    //  Text files: their line ends and the mark in front come back as they were.
    {
        const QByteArray samples[] = {
            QByteArray("a\r\nb\r\n"), QByteArray("a\nb\n"), QByteArray("a\nb"),
            QByteArray("\xEF\xBB\xBF" "a\r\n\r\nb\r\n"), QByteArray(),
        };
        bool same = true;
        for (const QByteArray& sample : samples){
            const TextFile file = TextFile::from_bytes(sample);
            same = same && file.valid && file.to_bytes() == sample;
        }
        check(same, "text files come back byte for byte");
        check(TextFile::from_bytes("a\r\nb\r\n").crlf && !TextFile::from_bytes("a\nb\n").crlf, "the kind of line end");
        check(!TextFile::from_bytes(QByteArray("a\0b", 3)).valid && !TextFile::from_bytes("caf\xE9\n").valid, "what is not text");

        QByteArray before;
        for (int line = 1; line <= 20; line++){
            before += "line " + QByteArray::number(line) + "\r\n";
        }
        QByteArray after = before;
        after.replace("line 10\r\n", "line ten\r\n");
        const QString diff = diff_text(before, after);
        check(diff.contains("@@ -7,7 +7,7 @@") && diff.contains("-line 10\n+line ten\n"), "the lines of a change");
        check(diff_text(before, before) == "(No change.)\n", "no change");

        check(branch_slug("Fix the party menu!") == "fix-the-party-menu", "a branch's name from a topic");
        check(branch_slug("???") == "change", "a branch's name from nothing usable");
        check(why_not_writable(QString::fromLatin1(TestBackend::SOURCE_FILE)).isEmpty(), "a source file can be changed");
        check(!why_not_writable(".github/workflows/claudegg-windows.yml").isEmpty(), "a workflow cannot be changed");
        check(!why_not_writable("../outside.cpp").isEmpty() && !why_not_writable("a/../b.cpp").isEmpty(), "a path outside cannot be changed");
        check(!why_not_writable("3rdParty/library/file.h").isEmpty(), "third-party code cannot be changed");
        check(!why_not_writable("SerialPrograms/Source/picture.png").isEmpty(), "a picture cannot be changed");

        const QByteArray log =
            "2026-11-14T05:19:36.3Z cl : Command line warning D9025 : overriding '/W4' with '/W0'\n"
            "2026-11-14T05:19:36.5Z D:\\a\\A\\A\\A\\SerialPrograms\\Source\\ClaudeGG\\ClaudeGG_Home.cpp(123): error C2065: 'foo': undeclared identifier\n"
            "2026-11-14T05:19:37.1Z ##[error]Process completed with exit code 1.\n";
        const QStringList errors = build_errors(log, 40);
        check(
            errors.size() == 2 &&
            errors.value(0) == "SerialPrograms\\Source\\ClaudeGG\\ClaudeGG_Home.cpp(123): error C2065: 'foo': undeclared identifier",
            "the errors of a build's log"
        );
    }

    //  The files of a build from before the rename: moved to their new names,
    //  and not over a file that has its new name already.
    {
        const QString older = folder + "/older-build";
        QDir().mkpath(older);
        const auto write = [&](const QString& name, const QByteArray& data){
            QFile file(older + "/" + name);
            if (file.open(QIODevice::WriteOnly)){
                file.write(data);
            }
        };
        const auto read = [&](const QString& name){
            QFile file(older + "/" + name);
            return file.open(QIODevice::ReadOnly) ? file.readAll() : QByteArray("(no file)");
        };
        write("PocketPilot-Assistant-Keys.json", "old keys");
        write("PocketPilot-Assistant.json", "old settings");
        write("ClaudeGG-Assistant.json", "new settings");
        move_files_of_older_builds(older);
        check(
            read("ClaudeGG-Assistant-Keys.json") == "old keys" && !QFile::exists(older + "/PocketPilot-Assistant-Keys.json"),
            "the keys of an older build come along under their new name"
        );
        check(
            read("ClaudeGG-Assistant.json") == "new settings" && QFile::exists(older + "/PocketPilot-Assistant.json"),
            "a file that has its new name already is not replaced"
        );
    }

    //  The keys: kept in their file, back after a new start, never in the
    //  file as they are.
    {
        const QString path = folder + "/Assistant-SelfTest-Keys.json";
        QFile::remove(path);
        const QString key = "sk-ant-test-0123456789-ABCDEFGHIJ";
        const QString token = "github_pat_test_9876543210";
        QString error;
        {
            SecretStore store(path);
            check(!store.has(Secret::CLAUDE_API_KEY), "no key before one is saved");
            check(store.set(Secret::CLAUDE_API_KEY, "  " + key + "\n", error), "a key is saved");
            check(store.set(Secret::GITHUB_TOKEN, token, error), "a token is saved");
        }
        {
            SecretStore store(path);
            check(store.get(Secret::CLAUDE_API_KEY) == key, "the key is back after a new start");
            check(store.get(Secret::GITHUB_TOKEN) == token, "the token is back after a new start");
            check(!store.unreadable(Secret::CLAUDE_API_KEY), "the saved key can be read");
            //  Closed again before the store writes: Windows does not
            //  replace a file that is open.
            QByteArray content;
            {
                QFile file(path);
                if (file.open(QIODevice::ReadOnly)){
                    content = file.readAll();
                }
            }
            check(!content.isEmpty() && !content.contains(key.toUtf8()) && !content.contains(token.toUtf8()), "the keys' file does not show the keys");
#ifdef _WIN32
            //  Encrypted, not only encoded.
            check(!content.contains(key.toUtf8().toBase64()), "the keys' file is encrypted");
#endif
            check(store.set(Secret::CLAUDE_API_KEY, QString(), error) && !store.has(Secret::CLAUDE_API_KEY), "a key is forgotten");
        }
        {
            SecretStore store(path);
            check(!store.has(Secret::CLAUDE_API_KEY) && store.has(Secret::GITHUB_TOKEN), "a forgotten key stays forgotten");
        }
        QFile::remove(path);

        //  Not remembered: the keys are in memory only. The file never has
        //  one, whatever is saved, and a new start has none.
        const auto file_text = [&]{
            QFile file(path);
            return file.open(QIODevice::ReadOnly) ? file.readAll() : QByteArray();
        };
        {
            SecretStore store(path);
            check(store.remembers(), "the keys are remembered unless it is switched off");
            check(store.set(Secret::CLAUDE_API_KEY, key, error), "a key is saved before it is switched off");
            check(!file_text().isEmpty() && file_text().contains("claude_api_key"), "a remembered key is in the file");
            check(store.set_remembers(false, error) && !store.remembers(), "remembering is switched off");
            check(store.get(Secret::CLAUDE_API_KEY) == key, "the key stays in use after it is switched off");
            check(
                !file_text().isEmpty() && !file_text().contains("claude_api_key") && !file_text().contains("github_token"),
                "switched off, the file has no key any more"
            );
            check(store.set(Secret::GITHUB_TOKEN, token, error) && store.get(Secret::GITHUB_TOKEN) == token, "a token is kept in memory");
            check(
                !file_text().contains("github_token") && !file_text().contains(token.toUtf8()) && !file_text().contains(key.toUtf8()),
                "a key that is not remembered is never written"
            );
            check(!store.protection_text().isEmpty() && store.protection_text().contains("memory"), "the note says the keys are in memory only");
        }
        {
            SecretStore store(path);
            check(!store.remembers(), "not remembering stays so after a new start");
            check(!store.has(Secret::CLAUDE_API_KEY) && !store.has(Secret::GITHUB_TOKEN), "a key that is not remembered is gone after a new start");
            check(!store.unreadable(Secret::CLAUDE_API_KEY), "no key is left that cannot be read");
            //  Back on: the key in use is written.
            check(store.set(Secret::CLAUDE_API_KEY, key, error), "a key is kept without remembering it");
            check(store.set_remembers(true, error) && store.remembers(), "remembering is switched on");
            check(file_text().contains("claude_api_key"), "switched on, the key in use is written");
        }
        {
            SecretStore store(path);
            check(store.remembers() && store.get(Secret::CLAUDE_API_KEY) == key, "the key is back after it was remembered again");
        }
        {
            //  A key in a file that says not to remember is not read.
            QFile::remove(path);
            {
                SecretStore store(path);
                store.set(Secret::CLAUDE_API_KEY, key, error);
            }
            QByteArray content = file_text();
            content.replace("\"remember\": true", "\"remember\": false");
            QFile file(path);
            if (file.open(QIODevice::WriteOnly | QIODevice::Truncate)){
                file.write(content);
            }
            file.close();
            SecretStore store(path);
            check(!store.remembers() && !store.has(Secret::CLAUDE_API_KEY), "a key in a file that says not to remember is not used");
        }
        QFile::remove(path);

        const QString settings_path = folder + "/Assistant-SelfTest-Settings.json";
        Settings settings;
        settings.chat_model = "claude-opus-5-5";
        settings.ask_at_usd = 2.5;
        settings.panel_width = 512;
        settings.api_workspace_id = "wrkspc_01SelfTest";
        check(settings.save(settings_path), "the settings are saved");
        Settings again;
        again.load(settings_path);
        check(
            again.chat_model == "claude-opus-5-5" && about_equal(again.ask_at_usd, 2.5) && again.panel_width == 512 &&
            again.chat_effort == Settings().chat_effort,
            "the settings are back after a new start"
        );
        check(
            again.api_workspace_id == "wrkspc_01SelfTest" && Settings().api_workspace_id.isEmpty(),
            "the workspace ID is back after a new start, and empty unless set"
        );
        QFile::remove(settings_path);
    }

    //  The picture the chat gets when it looks at the game: the parts of the
    //  screen by name, and the right part of the frame in the picture. A
    //  frame whose left half is red and right half blue, and whose top is
    //  lighter than its bottom.
    {
        check(find_look_area("full") != nullptr && find_look_area("Top-Left") != nullptr, "the parts of the screen are found by name, in any case");
        check(find_look_area("middle") == nullptr && find_look_area("") == nullptr, "a name that is not one is not found");
        check(look_area_names().find("bottom-right") != std::string::npos, "the names of the parts are listed");
        check(look_picture(ImageViewRGB32(), *find_look_area("full"), 400).empty(), "no frame, no picture");

        ImageRGB32 frame(400, 200);
        for (size_t y = 0; y < 200; y++){
            for (size_t x = 0; x < 400; x++){
                const uint32_t red = x < 200 ? (y < 100 ? 255 : 150) : 0;
                const uint32_t blue = x < 200 ? 0 : (y < 100 ? 255 : 150);
                frame.pixel(x, y) = 0xff000000 | (red << 16) | blue;
            }
        }
        const auto look = [&](const char* name, int width, int& w, int& h){
            const std::string bytes = look_picture(frame, *find_look_area(name), width, &w, &h);
            return QImage::fromData(QByteArray(bytes.data(), (qsizetype)bytes.size()));
        };
        const auto near_colour = [](const QImage& image, int x, int y, int red, int blue){
            const QColor c = image.pixelColor(x, y);
            return std::abs(c.red() - red) < 24 && std::abs(c.blue() - blue) < 24 && c.green() < 24;
        };
        int w = 0;
        int h = 0;
        const std::string whole_bytes = look_picture(frame, *find_look_area("full"), 200, &w, &h);
        check(whole_bytes.size() > 3 && (unsigned char)whole_bytes[0] == 0xff && (unsigned char)whole_bytes[1] == 0xd8, "the picture is a JPEG");
        QImage whole = look("full", 200, w, h);
        check(w == 200 && h == 100 && whole.width() == 200 && whole.height() == 100, "the whole screen is as wide as asked, and as high as it is in proportion");
        check(near_colour(whole, 20, 20, 255, 0) && near_colour(whole, 180, 20, 0, 255) && near_colour(whole, 20, 80, 150, 0) && near_colour(whole, 180, 80, 0, 150), "the whole screen shows all four quarters where they are");
        QImage left = look("left", 200, w, h);
        check(w == 200 && h == 200 && left.width() == 200 && left.height() == 200, "a part of the screen comes at twice the detail, up to the size of the frame itself");
        check(near_colour(left, 20, 20, 255, 0) && near_colour(left, 180, 20, 255, 0) && near_colour(left, 20, 180, 150, 0) && near_colour(left, 180, 180, 150, 0), "the left half is the left half of the frame");
        QImage right = look("right", 200, w, h);
        check(near_colour(right, 20, 20, 0, 255) && near_colour(right, 180, 180, 0, 150), "the right half is the right half of the frame");
        QImage bottom_right = look("bottom-right", 200, w, h);
        check(w == 200 && h == 100 && near_colour(bottom_right, 100, 50, 0, 150) && near_colour(bottom_right, 5, 5, 0, 150), "the bottom right is a quarter of the frame");
        QImage top_left = look("top-left", 200, w, h);
        QImage top_right = look("top-right", 200, w, h);
        QImage bottom_left = look("bottom-left", 200, w, h);
        QImage top = look("top", 200, w, h);
        QImage bottom = look("bottom", 200, w, h);
        check(near_colour(top_left, 100, 50, 255, 0) && near_colour(top_right, 100, 50, 0, 255) && near_colour(bottom_left, 100, 50, 150, 0), "each quarter of the screen is where its name says");
        check(
            near_colour(top, 20, 20, 255, 0) && near_colour(top, 380, 20, 0, 255) &&
            near_colour(bottom, 20, 80, 150, 0) && near_colour(bottom, 380, 80, 0, 150),
            "the top and the bottom are the upper and the lower half"
        );
        QImage tiny = look("full", 4, w, h);
        check(w == 16 && h == 16 && !tiny.isNull(), "a picture is never smaller than 16 pixels");
        QImage wide = look("full", 4000, w, h);
        check(w == 400 && h == 200 && !wide.isNull(), "a picture is never larger than the frame");
    }

    //  The server that Claude Code plays through (Assistant_McpServer.h):
    //  what it answers, and what it refuses. No network: the protocol and the
    //  HTTP side are checked as functions, the sockets by the test of the
    //  interface.
    {
        struct FakeMcpBackend : public McpBackend{
            int started = 0;
            std::string last_call;
            //  A call is held until "held" is called, not answered at once.
            bool hold = false;
            std::function<void(PlayResult)> held;
            PlayResult next;

            virtual std::string server_name() const override{ return "check-server"; }
            virtual std::string server_version() const override{ return "9.9"; }
            virtual std::string instructions() const override{ return "Play well."; }
            virtual std::vector<PlayTool> tools() const override{
                return {
                    PlayTool{"look", "Looks at the screen.", R"({"type":"object","properties":{"area":{"type":"string"}}})"},
                    PlayTool{"done", "Ends the session.", ""},
                };
            }
            virtual void initialized() override{ started++; }
            virtual void call(
                const std::string& name, const std::string& arguments,
                std::function<void(PlayResult result)> done
            ) override{
                last_call = name + " " + arguments;
                PlayResult made = next;
                if (made.text.empty()){
                    made.text = "did " + name;
                }
                if (hold){
                    held = std::move(done);
                    held_result = made;
                    return;
                }
                done(std::move(made));
            }
            PlayResult held_result;
        };
        struct Reply{
            bool got = false;
            int status = 0;
            QByteArray body;
            QJsonObject object() const{
                return QJsonDocument::fromJson(body).object();
            }
            QJsonArray array() const{
                return QJsonDocument::fromJson(body).array();
            }
        };

        FakeMcpBackend backend;
        McpProtocol protocol(backend);
        const auto send = [&](const char* body, const std::string& version = std::string()){
            const std::shared_ptr<Reply> reply = std::make_shared<Reply>();
            protocol.handle(QByteArray(body), version, [reply](McpReply answer){
                reply->got = true;
                reply->status = answer.status;
                reply->body = answer.body;
            });
            return reply;
        };
        const auto error_code = [](const Reply& reply){
            return reply.object().value("error").toObject().value("code").toInt();
        };

        //  The handshake.
        {
            const auto reply = send(
                R"({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"x","version":"1"}}})"
            );
            const QJsonObject init_result = reply->object().value("result").toObject();
            check(reply->got && reply->status == 200, "the server answers a handshake");
            check(
                init_result.value("protocolVersion").toString() == "2025-06-18" &&
                init_result.value("serverInfo").toObject().value("name").toString() == "check-server" &&
                init_result.value("serverInfo").toObject().value("version").toString() == "9.9" &&
                init_result.value("capabilities").toObject().contains("tools") &&
                init_result.value("instructions").toString() == "Play well." && backend.started == 1,
                "the handshake names the server, its tools and its instructions, and counts the client"
            );
            check(reply->object().value("id").toInt() == 1 && reply->object().value("jsonrpc").toString() == "2.0", "the answer carries the id of the request");

            const auto text_id = send(R"({"jsonrpc":"2.0","id":"abc","method":"ping"})");
            check(text_id->object().value("id").toString() == "abc" && text_id->object().contains("result"), "an id that is text is answered as text");

            const auto newer = send(R"({"jsonrpc":"2.0","id":2,"method":"initialize","params":{"protocolVersion":"2099-01-01"}})");
            check(
                newer->object().value("result").toObject().value("protocolVersion").toString() ==
                    QString::fromStdString(mcp_protocol_versions().back()),
                "a revision that is not known gets the newest one this server speaks"
            );
            const auto older = send(R"({"jsonrpc":"2.0","id":3,"method":"initialize","params":{"protocolVersion":"2024-11-05"}})");
            check(
                older->object().value("result").toObject().value("protocolVersion").toString() == "2024-11-05",
                "an older revision that is known is spoken as it is"
            );
            const auto none = send(R"({"jsonrpc":"2.0","id":4,"method":"initialize","params":{}})");
            check(error_code(*none) == -32602, "a handshake without a revision is refused");

            const auto notification = send(R"({"jsonrpc":"2.0","method":"notifications/initialized"})");
            check(notification->got && notification->status == 202 && notification->body.isEmpty(), "a notification gets 202 and no body");
            const auto answer_of_client = send(R"({"jsonrpc":"2.0","id":9,"result":{}})");
            check(answer_of_client->got && answer_of_client->status == 202, "an answer of the client (there is no request of the server to answer) is let go");
        }

        //  The tools.
        {
            const auto list = send(R"({"jsonrpc":"2.0","id":5,"method":"tools/list"})", "2025-06-18");
            const QJsonArray tools = list->object().value("result").toObject().value("tools").toArray();
            check(
                tools.size() == 2 && tools[0].toObject().value("name").toString() == "look" &&
                tools[1].toObject().value("name").toString() == "done",
                "the tools are listed, in order"
            );
            check(
                tools[0].toObject().value("inputSchema").toObject().value("properties").toObject().contains("area") &&
                tools[0].toObject().value("description").toString() == "Looks at the screen.",
                "a tool has its schema and its description"
            );
            check(
                tools[1].toObject().value("inputSchema").toObject().value("type").toString() == "object",
                "a tool without a schema is given an empty object's"
            );

            backend.next = PlayResult();
            backend.next.image = std::string("\xff\xd8\xff\xe0", 4) + "jpeg-bytes";
            const auto looked = send(
                R"({"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"look","arguments":{"area":"top"}}})",
                "2025-06-18"
            );
            const QJsonObject look_result = looked->object().value("result").toObject();
            const QJsonArray content = look_result.value("content").toArray();
            check(looked->status == 200 && backend.last_call == R"(look {"area":"top"})", "a call reaches the program with its arguments");
            check(
                content.size() == 2 && content[0].toObject().value("type").toString() == "text" &&
                content[0].toObject().value("text").toString() == "did look" && !look_result.value("isError").toBool(true),
                "the result of a call is its text"
            );
            const QByteArray picture = QByteArray::fromBase64(content[1].toObject().value("data").toString().toLatin1());
            check(
                content.size() == 2 && content[1].toObject().value("type").toString() == "image" &&
                content[1].toObject().value("mimeType").toString() == "image/jpeg" &&
                picture.startsWith("\xff\xd8\xff") && picture.endsWith("jpeg-bytes"),
                "a picture comes as an image, with its type, the bytes back as they were"
            );

            backend.next = PlayResult();
            backend.next.is_error = true;
            backend.next.text = "Not pressed.";
            backend.next.image = "not a picture at all";
            const auto failed_call = send(R"({"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"done"}})");
            const QJsonObject failed_result = failed_call->object().value("result").toObject();
            check(
                backend.last_call == "done {}" && failed_result.value("isError").toBool(false) &&
                failed_result.value("content").toArray().size() == 1 &&
                failed_result.value("content").toArray()[0].toObject().value("text").toString() == "Not pressed.",
                "a call without arguments gets an empty object, an error is flagged, bytes that are no picture are not sent as one"
            );
            backend.next = PlayResult();

            const std::string before = backend.last_call;
            const auto unknown = send(R"({"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"launch_missiles"}})");
            check(error_code(*unknown) == -32602 && backend.last_call == before, "a tool that does not exist is refused and not called");
            const auto no_name = send(R"({"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"arguments":{}}})");
            check(error_code(*no_name) == -32602 && backend.last_call == before, "a call without a name is refused");
            const auto array_arguments = send(R"({"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"look","arguments":[1]}})");
            check(error_code(*array_arguments) == -32602 && backend.last_call == before, "arguments that are not an object are refused");

            //  A call takes as long as the program takes: the answer comes later.
            backend.hold = true;
            const auto slow = send(R"({"jsonrpc":"2.0","id":10,"method":"tools/call","params":{"name":"look"}})");
            check(!slow->got && backend.held, "a call that takes time has no answer yet");
            PlayResult late = backend.held_result;
            late.text = "late but there";
            backend.held(late);
            check(slow->got && slow->status == 200 && slow->object().value("id").toInt() == 10, "the answer comes when the program has it");
            backend.hold = false;
        }

        //  What is not a request it can serve.
        {
            const auto unknown_method = send(R"({"jsonrpc":"2.0","id":11,"method":"resources/list"})");
            check(unknown_method->status == 200 && error_code(*unknown_method) == -32601, "a method it does not have is not found");
            const auto discover = send(R"({"jsonrpc":"2.0","id":12,"method":"server/discover"})", "2026-07-28");
            check(discover->status == 200 && error_code(*discover) == -32601, "a newer client that asks what the server is first is told it is not found, and goes on with the handshake");
            const auto ping = send(R"({"jsonrpc":"2.0","id":13,"method":"ping"})");
            check(ping->object().contains("result"), "a ping is answered");
            const auto not_json = send("this is not json");
            check(not_json->status == 400 && error_code(*not_json) == -32700, "a body that is not JSON is a bad request");
            const auto number = send("5");
            check(number->status == 400, "JSON that is no message is a bad request");
            const auto not_object = send(R"([5])");
            check(not_object->status == 400 && !not_object->array().isEmpty() &&
                not_object->array()[0].toObject().value("error").toObject().value("code").toInt() == -32600,
                "a batch with something in it that is no message is told so");
            const auto future = send(R"({"jsonrpc":"2.0","id":14,"method":"tools/list"})", "1999-01-01");
            check(future->status == 400, "a revision in the header that is not known is refused once the handshake is past");
            const auto handshake_under_future = send(R"({"jsonrpc":"2.0","id":15,"method":"initialize","params":{"protocolVersion":"2025-06-18"}})", "1999-01-01");
            check(handshake_under_future->status == 200 && handshake_under_future->object().contains("result"), "but the handshake itself is answered");
            const auto no_method = send(R"({"jsonrpc":"2.0","id":16})");
            check(no_method->status == 400, "a message without a method is a bad request");
        }

        //  A batch (revisions before 2025-06-18).
        {
            const auto batch = send(
                R"([{"jsonrpc":"2.0","id":20,"method":"ping"},{"jsonrpc":"2.0","method":"notifications/initialized"},{"jsonrpc":"2.0","id":21,"method":"tools/list"}])"
            );
            const QJsonArray answers = batch->array();
            check(batch->status == 200 && answers.size() == 2 && answers[0].toObject().value("id").toInt() == 20 && answers[1].toObject().value("id").toInt() == 21, "a batch is answered in one: one answer for each request, none for a notification");
            const auto only_notes = send(R"([{"jsonrpc":"2.0","method":"notifications/initialized"}])");
            check(only_notes->status == 202 && only_notes->body.isEmpty(), "a batch of notifications gets 202");
            const auto empty = send("[]");
            check(empty->status == 400, "an empty batch is a bad request");
            backend.hold = true;
            const auto held_batch = send(
                R"([{"jsonrpc":"2.0","id":22,"method":"ping"},{"jsonrpc":"2.0","id":23,"method":"tools/call","params":{"name":"look"}}])"
            );
            check(!held_batch->got, "a batch waits for its slowest call");
            backend.held(backend.held_result);
            check(held_batch->got && held_batch->array().size() == 2, "and goes out once all its answers are there");
            backend.hold = false;
        }

        //  The pictures' types.
        check(mcp_image_mime(std::string("\x89PNG\r\n\x1a\n") + "rest") == "image/png", "a PNG is told by its signature");
        check(mcp_image_mime(std::string("\xff\xd8\xff\xdb", 4)) == "image/jpeg", "a JPEG is told by its signature");
        check(mcp_image_mime("GIF89a....").empty() && mcp_image_mime("").empty() && mcp_image_mime("\xff\xd8").empty(), "bytes that are neither are no picture");
    }

    //  The HTTP side: what is read off the socket, and what is refused.
    {
        const auto parse = [](const QByteArray& raw, McpHttpRequest& request, bool& wants_continue, QByteArray& left){
            left = raw;
            return parse_mcp_http_request(left, request, wants_continue);
        };
        McpHttpRequest request;
        bool wants_continue = false;
        QByteArray left;

        check(
            parse("POST /mcp HTTP/1.1\r\nHOST: 127.0.0.1:1\r\nContent-Length: 2\r\nAuthorization: Bearer t\r\n\r\n{}", request, wants_continue, left) == McpHttpParse::COMPLETE &&
            request.method == "POST" && request.target == "/mcp" && request.body == "{}" &&
            request.header("host") == "127.0.0.1:1" && request.header("authorization") == "Bearer t" && left.isEmpty(),
            "a request is read: its method, target, headers (in any case) and body, and its bytes are taken"
        );
        const QByteArray two = "POST /mcp HTTP/1.1\r\nContent-Length: 1\r\n\r\nAPOST /mcp HTTP/1.1\r\nContent-Length: 1\r\n\r\nB";
        McpHttpRequest second;
        check(
            parse(two, request, wants_continue, left) == McpHttpParse::COMPLETE && request.body == "A" &&
            parse_mcp_http_request(left, second, wants_continue) == McpHttpParse::COMPLETE && second.body == "B" && left.isEmpty(),
            "two requests that came together are read one after the other"
        );
        check(parse("POST /mcp HTTP/1.1\r\nContent-Le", request, wants_continue, left) == McpHttpParse::INCOMPLETE, "headers that are not all there are waited for");
        check(
            parse("POST /mcp HTTP/1.1\r\nContent-Length: 5\r\n\r\nab", request, wants_continue, left) == McpHttpParse::INCOMPLETE &&
            left.endsWith("ab") && !wants_continue,
            "a body that is not all there is waited for, and nothing is taken"
        );
        check(
            parse("POST /mcp HTTP/1.1\r\nContent-Length: 5\r\nExpect: 100-continue\r\n\r\n", request, wants_continue, left) == McpHttpParse::INCOMPLETE &&
            wants_continue,
            "a client that waits for 100 Continue is told to go on"
        );
        check(parse("POST /mcp HTTP/1.1\r\n\r\n", request, wants_continue, left) == McpHttpParse::COMPLETE && request.body.isEmpty(), "no length is no body");
        check(parse("GARBAGE\r\n\r\n", request, wants_continue, left) == McpHttpParse::BAD, "something that is no request line is bad");
        check(parse("post /mcp HTTP/1.1\r\n\r\n", request, wants_continue, left) == McpHttpParse::BAD, "a method in lower case is bad");
        check(parse("POST /mcp HTTP/2.0\r\n\r\n", request, wants_continue, left) == McpHttpParse::BAD, "a version that is not HTTP/1.x is bad");
        check(parse("POST /mcp HTTP/1.1\r\nNoColonHere\r\n\r\n", request, wants_continue, left) == McpHttpParse::BAD, "a header without a colon is bad");
        check(parse("POST /mcp HTTP/1.1\r\nHost : x\r\n\r\n", request, wants_continue, left) == McpHttpParse::BAD, "a space in front of a colon is bad");
        check(parse("POST /mcp HTTP/1.1\r\nContent-Length: 1\r\nContent-Length: 2\r\n\r\nab", request, wants_continue, left) == McpHttpParse::BAD, "two lengths are bad: two readers could read them differently");
        check(parse("POST /mcp HTTP/1.1\r\nHost: a\r\nHost: b\r\n\r\n", request, wants_continue, left) == McpHttpParse::BAD, "two hosts are bad");
        check(parse("POST /mcp HTTP/1.1\r\nAuthorization: Bearer a\r\nAuthorization: Bearer b\r\n\r\n", request, wants_continue, left) == McpHttpParse::BAD, "two authorizations are bad");
        check(
            parse("POST /mcp HTTP/1.1\r\nAccept: a\r\nAccept: b\r\n\r\n", request, wants_continue, left) == McpHttpParse::COMPLETE &&
            request.header("accept") == "a, b",
            "another header that is said twice is joined"
        );
        for (const char* length : {"-1", "abc", "+5", "1x", ""}){
            const QByteArray raw = QByteArray("POST /mcp HTTP/1.1\r\nContent-Length: ") + length + "\r\n\r\n";
            check(parse(raw, request, wants_continue, left) == McpHttpParse::BAD, (std::string("a length of \"") + length + "\" is bad").c_str());
        }
        check(parse("POST /mcp HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n", request, wants_continue, left) == McpHttpParse::LENGTH_REQUIRED, "a body without a length (chunked) is told to have one");
        check(parse("POST /mcp HTTP/1.1\r\nContent-Length: 99999999\r\n\r\n", request, wants_continue, left) == McpHttpParse::BODY_TOO_LARGE, "a body that is too large is refused before it is read");
        check(parse("POST /mcp HTTP/1.1\r\nX: " + QByteArray(20000, 'a'), request, wants_continue, left) == McpHttpParse::HEADERS_TOO_LARGE, "headers that never end are cut off");

        //  What may be served.
        const std::string token = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
        const int port = 4321;
        const auto make = [&](const char* method, const char* target, const QByteArray& host, const QByteArray& authorization){
            McpHttpRequest made;
            made.method = method;
            made.target = target;
            if (!host.isNull()){
                made.headers["host"] = host;
            }
            if (!authorization.isNull()){
                made.headers["authorization"] = authorization;
            }
            return made;
        };
        const QByteArray good_host = "127.0.0.1:4321";
        const QByteArray good_auth = "Bearer " + QByteArray::fromStdString(token);
        check(check_mcp_request(make("POST", "/mcp", good_host, good_auth), port, token) == 0, "a request with the right host and token is served");
        check(check_mcp_request(make("POST", "/mcp", "localhost:4321", good_auth), port, token) == 0, "localhost is this computer");
        check(check_mcp_request(make("POST", "/mcp", "LocalHost:4321", good_auth), port, token) == 0, "in any case");
        check(check_mcp_request(make("POST", "/mcp", "[::1]:4321", good_auth), port, token) == 0, "so is [::1]");
        check(check_mcp_request(make("POST", "/mcp", good_host, "bearer " + QByteArray::fromStdString(token)), port, token) == 0, "the scheme of the token may be in lower case");
        check(check_mcp_request(make("POST", "/mcp", QByteArray(), good_auth), port, token) == 400, "no host is a bad request");
        check(check_mcp_request(make("POST", "/mcp", "evil.example:4321", good_auth), port, token) == 403, "another host is refused, even with the right token (a web page that points its own name at this port)");
        check(check_mcp_request(make("POST", "/mcp", "127.0.0.1:4322", good_auth), port, token) == 403, "another port is another host");
        check(check_mcp_request(make("POST", "/mcp", "127.0.0.1", good_auth), port, token) == 403, "no port is another host");
        check(check_mcp_request(make("POST", "/mcp", "127.0.0.1.evil.example:4321", good_auth), port, token) == 403, "a host that only begins like this computer's is refused");
        {
            McpHttpRequest from_page = make("POST", "/mcp", good_host, good_auth);
            from_page.headers["origin"] = "https://evil.example";
            check(check_mcp_request(from_page, port, token) == 403, "a request that a web page sends is refused (its origin)");
            from_page.headers["origin"] = "null";
            check(check_mcp_request(from_page, port, token) == 403, "also from a page with no origin of its own");
            from_page.headers["origin"] = "http://127.0.0.1:4321";
            check(check_mcp_request(from_page, port, token) == 0, "a page of this very server is no stranger");
        }
        check(check_mcp_request(make("POST", "/mcp", good_host, QByteArray()), port, token) == 401, "no token is refused");
        check(check_mcp_request(make("POST", "/mcp", good_host, "Bearer wrong"), port, token) == 401, "a wrong token is refused");
        check(check_mcp_request(make("POST", "/mcp", good_host, good_auth + "x"), port, token) == 401, "a token with something after it is refused");
        check(check_mcp_request(make("POST", "/mcp", good_host, good_auth.left(good_auth.size() - 1)), port, token) == 401, "a token that lacks its last character is refused");
        check(check_mcp_request(make("POST", "/mcp", good_host, "Basic " + QByteArray::fromStdString(token)), port, token) == 401, "another scheme is refused");
        check(check_mcp_request(make("POST", "/mcp", good_host, "Bearer "), port, token) == 401, "an empty token is refused");
        check(check_mcp_request(make("POST", "/mcp", good_host, "Bearer x"), port, std::string()) == 401, "a server that has no token serves nobody");
        check(check_mcp_request(make("POST", "/mcp", good_host, "Bearer "), port, std::string()) == 401, "not even an empty one");
        check(check_mcp_request(make("POST", "/mcp", good_host, "Bearer  "), port, std::string()) == 401, "nor one that is only spaces: an empty token is no token");
        check(check_mcp_request(make("POST", "/other", good_host, good_auth), port, token) == 404, "another path is not found");
        check(check_mcp_request(make("POST", "/mcp?x=1", good_host, good_auth), port, token) == 404, "the path is exact");
        check(check_mcp_request(make("POST", "/mcp/", good_host, good_auth), port, token) == 404, "also with a slash after it");
        check(check_mcp_request(make("GET", "/mcp", good_host, good_auth), port, token) == 405, "a GET is not allowed (there is no stream of events)");
        check(check_mcp_request(make("DELETE", "/mcp", good_host, good_auth), port, token) == 405, "a DELETE is not allowed (there are no sessions)");
        check(check_mcp_request(make("POST", "/other", good_host, "Bearer wrong"), port, token) == 401, "a stranger is told nothing of what is there: 401 before 404");
        check(check_mcp_request(make("GET", "/mcp", good_host, QByteArray()), port, token) == 401, "a stranger is told nothing of the method either");

        const QByteArray ok = mcp_http_response(200, "{}", false);
        check(ok.startsWith("HTTP/1.1 200 OK\r\n") && ok.contains("Content-Length: 2\r\n") && ok.contains("Connection: close\r\n") && ok.endsWith("\r\n\r\n{}") && ok.contains("Content-Type: application/json\r\n"), "a response is a response");
        check(mcp_http_response(401, "", true).contains("WWW-Authenticate: Bearer\r\n") && mcp_http_response(401, "", true).contains("Connection: keep-alive\r\n"), "a 401 says what is wanted");
        check(mcp_http_response(405, "", false).contains("Allow: POST\r\n"), "a 405 says what is allowed");
        check(!mcp_http_response(202, "", false).contains("Content-Type: "), "a 202 has no type: it has no body");
        check(mcp_http_response(202, "", false).contains("Content-Length: 0\r\n"), "but it has a length");
    }

    //  The token of the server and the file that says how to use it.
    {
        const QString token_file = folder + "/ClaudeGG-Mcp-Token.json";
        QFile::remove(token_file);
        const std::string folder_path = (folder + "/").toStdString();
        const auto is_hex = [](const std::string& text){
            if (text.size() != 64){
                return false;
            }
            for (char c : text){
                if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))){
                    return false;
                }
            }
            return true;
        };
        std::string error;
        const std::string first = mcp_token(folder_path, false, error);
        check(is_hex(first) && error.empty(), "a token is made: 32 bytes, as 64 hex digits");
        check(mcp_token(folder_path, false, error) == first, "it is kept: the same at the next start");
        QByteArray content;
        {
            QFile file(token_file);
            if (file.open(QIODevice::ReadOnly)){
                content = file.readAll();
            }
        }
        check(!content.isEmpty() && !content.contains(QByteArray::fromStdString(first)), "the file of the token does not show it");
        const std::string renewed = mcp_token(folder_path, true, error);
        check(is_hex(renewed) && renewed != first, "a new one is a different one");
        check(mcp_token(folder_path, false, error) == renewed, "and it is the one that is kept from then on");
        {
            SecretStore store(token_file);
            QString store_error;
            check(store.set(Secret::MCP_TOKEN, "short", store_error), "a short token is written into the file");
            check(!store.has(Secret::CLAUDE_API_KEY) && !store.has(Secret::GITHUB_TOKEN) && !store.has(Secret::MOBILE_TOKEN), "the token is not any of the other keys");
        }
        const std::string replaced = mcp_token(folder_path, false, error);
        check(is_hex(replaced) && replaced != "short", "a token that is not what this makes is not trusted: a new one is made");
        check(is_hex(mcp_token(folder_path, true, error)) && mcp_token(folder_path, true, error) != mcp_token(folder_path, true, error), "tokens do not repeat");

        //  A folder that cannot be written: the token holds for the run, and
        //  says so.
        const QString not_a_folder = folder + "/Assistant-SelfTest-NotAFolder";
        {
            QFile file(not_a_folder);
            if (file.open(QIODevice::WriteOnly)){
                file.write("a file where a folder should be");
            }
        }
        std::string unwritable_error;
        const std::string unwritable = mcp_token((not_a_folder + "/inside/").toStdString(), false, unwritable_error);
        check(is_hex(unwritable) && !unwritable_error.empty(), "when the file cannot be written the token is still made, and the error says so");

        //  The file that tells how to connect.
        const std::string text = mcp_connect_text(4321, first);
        check(
            text.find("claude mcp add --transport http claude-gg http://127.0.0.1:4321/mcp --header \"Authorization: Bearer " + first + "\"") != std::string::npos,
            "the file tells the command that adds the server to Claude Code"
        );
        check(text.find("\r\n") != std::string::npos && text.find("Port 4321") != std::string::npos, "with the line ends of Windows, and the port");
        std::string write_error;
        const std::string written = write_mcp_connect_file(folder_path, 4321, first, write_error);
        QByteArray read_back;
        {
            QFile file(QString::fromStdString(written));
            if (file.open(QIODevice::ReadOnly)){
                read_back = file.readAll();
            }
        }
        check(!written.empty() && write_error.empty() && read_back.toStdString() == text, "the file is written, as it is");
        QFile::remove(QString::fromStdString(written));
        std::string no_error;
        check(write_mcp_connect_file((not_a_folder + "/inside/").toStdString(), 1, first, no_error).empty() && !no_error.empty(), "a file that cannot be written says so");
        QFile::remove(not_a_folder);
        QFile::remove(token_file);
    }

    return result;
}



}
}
}
