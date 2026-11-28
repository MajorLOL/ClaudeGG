/*  Claude GG Mobile (an Android phone, through a Raspberry Pi)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <chrono>
#include <cmath>
#include <functional>
#include <memory>
#include <stdexcept>
#include <mutex>
#include <thread>
#include <QCoreApplication>
#include <QDate>
#include <QDateTime>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QProcessEnvironment>
#include <QStandardPaths>
#include <QTcpSocket>
#include <QTemporaryDir>
#include <QTextStream>
#include <QThread>
#include <QTimeZone>
#include "Common/Cpp/Color.h"
#include "Common/Cpp/Logging/AbstractLogger.h"
#include "Common/Cpp/Logging/GlobalLogger.h"
#include "CommonFramework/Logging/Logger.h"
#include "CommonFramework/GlobalAutoPaths.h"
#include "Assistant/Assistant_Settings.h"
#include "ClaudeGG_Language.h"
#include "ClaudeGG_Mobile.h"
#include "ClaudeGG_PokemonGo.h"
#include "ClaudeGG_PokemonGoBattle.h"
#include "ClaudeGG_PokemonGoFight.h"
#include "ClaudeGG_PokemonGoFlow.h"
#include "ClaudeGG_PokemonGoMinigame.h"
#include "ClaudeGG_PokemonGoLayout.h"
#include "ClaudeGG_PokemonGoLock.h"
#include "ClaudeGG_PokemonGoLoop.h"
#include "ClaudeGG_PokemonGoText.h"
#include "ClaudeGG_PokemonGoModels.h"
#include "ClaudeGG_PokemonGoNav.h"
#include "ClaudeGG_PokemonGoPhone.h"
#include "ClaudeGG_PokemonGoMap.h"
#include "ClaudeGG_PokemonGoStart.h"
#include "ClaudeGG_PokemonGoThrow.h"
#include "ClaudeGG_PokemonGoBot.h"
#include "ClaudeGG_PokemonGoChapter.h"
#include "ClaudeGG_PokemonGoCatch.h"
#include "ClaudeGG_PokemonGoStep.h"
#include "ClaudeGG_PokemonGoBag.h"
#include "ClaudeGG_PokemonGoGifts.h"
#include "ClaudeGG_PokemonGoQuests.h"
#include "ClaudeGG_PokemonGoRocket.h"
#include "ClaudeGG_PokemonGoRocketFight.h"
#include "ClaudeGG_PokemonGoDaily.h"
#include "ClaudeGG_PokemonGoThrowPlay.h"
#include "ClaudeGG_PokemonGoVision.h"

namespace PokemonAutomation{
namespace ClaudeGG{


const char* const MOBILE_TEST_OPTION = "--mobile-test";


MobileVideo::MobileVideo(const QString& host, int port, const QString& token, int fps, int width)
    : m_host(host)
    , m_port(port)
    , m_token(token)
    , m_fps(fps)
    , m_width(width)
{}

MobileVideo::~MobileVideo(){
    stop();
}

void MobileVideo::start(){
    if (m_thread.joinable()){
        return;
    }
    m_stop = false;
    m_thread = std::thread([this]{
        run();
    });
}

void MobileVideo::stop(){
    m_stop = true;
    m_changed.notify_all();
    if (m_thread.joinable()){
        m_thread.join();
    }
}

bool MobileVideo::latest(QImage& picture, quint64* serial, double* when) const{
    std::lock_guard<std::mutex> lock(m_lock);
    if (serial != nullptr){
        *serial = m_serial;
    }
    if (m_serial == 0){
        return false;
    }
    picture = m_picture;
    if (when != nullptr){
        *when = m_time;
    }
    return true;
}

bool MobileVideo::wait_newer(QImage& picture, quint64 after, int msec, quint64* serial, double* when) const{
    std::unique_lock<std::mutex> lock(m_lock);
    const bool came = m_changed.wait_for(lock, std::chrono::milliseconds(msec), [&]{
        return m_serial > after || m_stop.load();
    });
    if (!came || m_serial <= after){
        return false;
    }
    picture = m_picture;
    if (serial != nullptr){
        *serial = m_serial;
    }
    if (when != nullptr){
        *when = m_time;
    }
    return true;
}

QString MobileVideo::error() const{
    std::lock_guard<std::mutex> lock(m_lock);
    return m_error;
}

void MobileVideo::run(){
    while (!m_stop){
        const QString why = read_stream();
        if (m_stop){
            break;
        }
        {
            std::lock_guard<std::mutex> lock(m_lock);
            m_error = why;
        }
        //  Connect again in a moment (a phone that was unplugged, an agent that was restarted).
        for (int c = 0; c < 20 && !m_stop; c++){
            QThread::msleep(50);
        }
    }
}

QString MobileVideo::read_stream(){
    constexpr int STALL_MSEC = 10000;
    constexpr qsizetype MAX_PICTURE = 8 * 1024 * 1024;

    QTcpSocket socket;
    socket.connectToHost(m_host, (quint16)m_port);
    if (!socket.waitForConnected(5000)){
        return QString("cannot reach the Raspberry Pi at %1:%2 (%3)").arg(m_host).arg(m_port).arg(socket.errorString());
    }
    QByteArray head = "GET /v1/video?fps=" + QByteArray::number(m_fps) + "&width=" + QByteArray::number(m_width) + " HTTP/1.1\r\n";
    head += "Host: " + m_host.toUtf8() + ":" + QByteArray::number(m_port) + "\r\n";
    head += "Authorization: Bearer " + m_token.toUtf8() + "\r\n";
    head += "Connection: close\r\n\r\n";
    socket.write(head);
    if (!socket.waitForBytesWritten(5000)){
        return "the request could not be sent to the Raspberry Pi";
    }

    QByteArray buffer;
    bool answered = false;
    QElapsedTimer quiet;
    quiet.start();
    while (!m_stop){
        if (socket.bytesAvailable() > 0 || socket.waitForReadyRead(200)){
            buffer += socket.readAll();
            quiet.restart();
        }else if (socket.state() != QAbstractSocket::ConnectedState){
            buffer += socket.readAll();
            if (!answered){
                //  The agent said something and closed: an error (JSON), or nothing.
                const qsizetype split = buffer.indexOf("\r\n\r\n");
                if (split >= 0){
                    const QJsonObject object = QJsonDocument::fromJson(buffer.mid(split + 4)).object();
                    if (object.contains("error")){
                        return object.value("error").toString();
                    }
                }
                return "the agent gave no picture (is it the Claude GG agent on that port?)";
            }
            return "the stream of the picture ended";
        }else if (quiet.elapsed() > STALL_MSEC){
            return "no picture for ten seconds";
        }

        if (!answered){
            const qsizetype split = buffer.indexOf("\r\n\r\n");
            if (split < 0){
                continue;
            }
            const QList<QByteArray> status = buffer.left(buffer.indexOf("\r\n")).split(' ');
            if (status.size() < 2 || !status[0].startsWith("HTTP/")){
                return "the answer is not HTTP (is it the Claude GG agent on that port?)";
            }
            if (status[1].toInt() != 200){
                //  An error: its JSON follows, until the agent closes.
                QByteArray rest = buffer.mid(split + 4);
                QElapsedTimer wait;
                wait.start();
                while (socket.state() == QAbstractSocket::ConnectedState && wait.elapsed() < 3000){
                    socket.waitForReadyRead(200);
                    rest += socket.readAll();
                }
                rest += socket.readAll();
                const QJsonObject object = QJsonDocument::fromJson(rest).object();
                return object.contains("error") ? object.value("error").toString() : QString("the agent says %1").arg(status[1].toInt());
            }
            buffer.remove(0, split + 4);
            answered = true;
            {
                std::lock_guard<std::mutex> lock(m_lock);
                m_error.clear();
            }
        }

        //  The pictures that are complete in what came.
        for (;;){
            const qsizetype boundary = buffer.indexOf("--frame\r\n");
            if (boundary < 0){
                if (buffer.size() > 1024){
                    buffer = buffer.right(16);
                }
                break;
            }
            const qsizetype head_end = buffer.indexOf("\r\n\r\n", boundary);
            if (head_end < 0){
                break;
            }
            qsizetype length = -1;
            for (const QByteArray& line : buffer.mid(boundary, head_end - boundary).split('\n')){
                const QByteArray lower = line.trimmed().toLower();
                if (lower.startsWith("content-length:")){
                    length = lower.mid(QByteArray("content-length:").size()).trimmed().toLongLong();
                }
            }
            if (length <= 0 || length > MAX_PICTURE){
                return "the stream of the picture is not what the agent makes";
            }
            const qsizetype body = head_end + 4;
            if (buffer.size() < body + length){
                break;
            }
            const QImage picture = QImage::fromData(buffer.mid(body, length), "JPEG");
            buffer.remove(0, body + length);
            if (!picture.isNull()){
                {
                    std::lock_guard<std::mutex> lock(m_lock);
                    m_picture = picture;
                    m_serial++;
                    m_time = std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
                }
                m_changed.notify_all();
            }
        }
    }
    return QString();
}


namespace{

const char* const TOKEN_FILE = "ClaudeGG-Mobile-Token.json";

//  The store of the token: the one file, one key. Made when it is needed, so
//  what another installation saved is read, not what was there at the start.
Assistant::SecretStore make_token_store(){
    return Assistant::SecretStore(QString::fromStdString(SETTINGS_PATH()) + TOKEN_FILE);
}

}

QString mobile_token(){
    return make_token_store().get(Assistant::Secret::MOBILE_TOKEN);
}
bool set_mobile_token(const QString& token, QString& error){
    Assistant::SecretStore store = make_token_store();
    return store.set(Assistant::Secret::MOBILE_TOKEN, token, error);
}

bool check_mobile(const QString& host, int port, const QString& token, QString& message){
    if (host.trimmed().isEmpty()){
        message = tr_ui("Type the address of the Raspberry Pi first.");
        return false;
    }
    if (port < 1 || port > 65535){
        message = tr_ui("The port is a number from 1 to 65535.");
        return false;
    }
    //  Short: the page of the setup waits for this.
    const MobileAgent agent(host.trimmed(), port, token.trimmed(), 4000);
    QString error;
    if (!agent.ping(&error)){
        message = tr_ui("No answer: %1.").arg(error);
        return false;
    }
    if (token.trimmed().isEmpty()){
        message = tr_ui("The agent is there. Type its token (the installer printed it) to go on.");
        return false;
    }
    MobileInfo info;
    if (!agent.info(info, &error)){
        message = tr_ui("The agent is there, but %1.").arg(error);
        return false;
    }
    QString phone = info.model.isEmpty() ? tr_ui("a phone") : info.model;
    if (!info.android.isEmpty()){
        phone += ", Android " + info.android;
    }
    if (info.width > 0 && info.height > 0){
        phone += QString(", %1 x %2").arg(info.width).arg(info.height);
    }
    message = tr_ui("Connected to %1.").arg(phone);

    return true;
}


MobileAgent::MobileAgent(const QString& host, int port, const QString& token, int timeout_msec)
    : m_host(host)
    , m_port(port)
    , m_token(token)
    , m_timeout(timeout_msec)
{}

//  One request, one answer, on a connection of its own: the agent closes it
//  when the answer is complete.
bool MobileAgent::request(const char* method, const QString& path, const QByteArray& body, Reply& reply, QString* error) const{
    auto fail = [&](const QString& why){
        if (error != nullptr){
            *error = why;
        }
        return false;
    };

    QTcpSocket socket;
    socket.connectToHost(m_host, (quint16)m_port);
    if (!socket.waitForConnected(m_timeout)){
        return fail(QString("cannot reach the Raspberry Pi at %1:%2 (%3)").arg(m_host).arg(m_port).arg(socket.errorString()));
    }
    QByteArray head;
    head += QByteArray(method) + " " + path.toUtf8() + " HTTP/1.1\r\n";
    head += "Host: " + m_host.toUtf8() + ":" + QByteArray::number(m_port) + "\r\n";
    head += "Authorization: Bearer " + m_token.toUtf8() + "\r\n";
    head += "Content-Type: application/json\r\n";
    head += "Content-Length: " + QByteArray::number(body.size()) + "\r\n";
    head += "Connection: close\r\n\r\n";
    socket.write(head + body);
    if (!socket.waitForBytesWritten(m_timeout)){
        return fail("the request could not be sent to the Raspberry Pi");
    }

    QByteArray data;
    QElapsedTimer clock;
    clock.start();
    for (;;){
        data += socket.readAll();
        if (socket.state() != QAbstractSocket::ConnectedState){
            data += socket.readAll();
            break;
        }
        const qint64 left = m_timeout - clock.elapsed();
        if (left <= 0 || !socket.waitForReadyRead((int)left)){
            data += socket.readAll();
            if (socket.state() == QAbstractSocket::ConnectedState){
                return fail("the agent did not answer in time");
            }
            break;
        }
    }

    const qsizetype split = data.indexOf("\r\n\r\n");
    if (split < 0){
        return fail("the agent gave no answer (is it the Claude GG agent on that port?)");
    }
    const QList<QByteArray> lines = data.left(split).split('\n');
    const QList<QByteArray> status = lines.isEmpty() ? QList<QByteArray>() : lines.front().trimmed().split(' ');
    if (status.size() < 2 || !status[0].startsWith("HTTP/")){
        return fail("the answer is not HTTP (is it the Claude GG agent on that port?)");
    }
    reply.status = status[1].toInt();
    reply.body = data.mid(split + 4);
    for (const QByteArray& line : lines){
        const QByteArray lower = line.trimmed().toLower();
        if (lower.startsWith("content-length:")){
            const int length = lower.mid(QByteArray("content-length:").size()).trimmed().toInt();
            if (length != reply.body.size()){
                return fail("the answer of the agent was cut short");
            }
        }
    }
    if (reply.status != 200){
        QString why = QString("the agent says %1").arg(reply.status);
        const QJsonObject object = QJsonDocument::fromJson(reply.body).object();
        if (object.contains("error")){
            why = object.value("error").toString();
        }
        return fail(why);
    }
    return true;
}

bool MobileAgent::post(const QString& path, const QByteArray& body, QString* error) const{
    Reply reply;
    return request("POST", path, body, reply, error);
}

bool MobileAgent::ping(QString* error) const{
    Reply reply;
    if (!request("GET", "/v1/ping", QByteArray(), reply, error)){
        return false;
    }
    return QJsonDocument::fromJson(reply.body).object().value("ok").toBool();
}

bool MobileAgent::info(MobileInfo& result, QString* error) const{
    Reply reply;
    if (!request("GET", "/v1/info", QByteArray(), reply, error)){
        return false;
    }
    const QJsonObject object = QJsonDocument::fromJson(reply.body).object();
    result.model = object.value("model").toString();
    result.android = object.value("android").toString();
    result.width = object.value("width").toInt();
    result.height = object.value("height").toInt();
    result.version = object.value("version").toString();
    result.features.clear();
    for (const QJsonValue& value : object.value("features").toArray()){
        result.features << value.toString();
    }
    return true;
}

bool MobileAgent::screen(QImage& picture, QString* error) const{
    Reply reply;
    if (!request("GET", "/v1/screen", QByteArray(), reply, error)){
        return false;
    }
    picture = QImage::fromData(reply.body, "PNG");
    if (picture.isNull()){
        if (error != nullptr){
            *error = "the picture of the phone could not be read";
        }
        return false;
    }
    return true;
}

bool MobileAgent::tap(int x, int y, int ms, QString* error) const{
    return touch("press", x, y, ms, error);
}

bool MobileAgent::touch(const QString& kind, int x, int y, int ms, QString* error) const{
    QJsonObject body;
    body["x"] = x;
    body["y"] = y;
    body["ms"] = ms;
    if (kind != "press"){
        body["kind"] = kind;                    //  (an agent from before "kind" takes every touch for a press)
    }
    return post("/v1/tap", QJsonDocument(body).toJson(QJsonDocument::Compact), error);
}

bool MobileAgent::swipe(int x1, int y1, int x2, int y2, int ms, QString* error) const{
    QJsonObject body;
    body["x1"] = x1;
    body["y1"] = y1;
    body["x2"] = x2;
    body["y2"] = y2;
    body["ms"] = ms;
    return post("/v1/swipe", QJsonDocument(body).toJson(QJsonDocument::Compact), error);
}

bool MobileAgent::swipes(const std::vector<MobileStroke>& strokes, QString* error) const{
    QJsonArray list;
    for (const MobileStroke& stroke : strokes){
        list.append(QJsonArray{stroke.x1, stroke.y1, stroke.x2, stroke.y2, stroke.ms});
    }
    QJsonObject body;
    body["strokes"] = list;
    return post("/v1/swipes", QJsonDocument(body).toJson(QJsonDocument::Compact), error);
}

bool MobileAgent::key(const QString& name, QString* error) const{
    QJsonObject body;
    body["key"] = name;
    return post("/v1/key", QJsonDocument(body).toJson(QJsonDocument::Compact), error);
}

bool MobileAgent::text(const QString& typed, QString* error) const{
    QJsonObject body;
    body["text"] = typed;
    return post("/v1/text", QJsonDocument(body).toJson(QJsonDocument::Compact), error);
}

bool MobileAgent::wake(QString* error) const{
    return post("/v1/wake", "{}", error);
}

bool MobileAgent::touch(const std::vector<MobileTouch>& events, QString& out, QString* error) const{
    QJsonArray list;
    for (const MobileTouch& event : events){
        list.append(QJsonArray{event.action, event.x, event.y});
    }
    QJsonObject body;
    body["events"] = list;
    Reply reply;
    if (!request("POST", "/v1/touch", QJsonDocument(body).toJson(QJsonDocument::Compact), reply, error)){
        return false;
    }
    out = QJsonDocument::fromJson(reply.body).object().value("out").toString();
    return true;
}

bool MobileAgent::app(const char* action, const QString& package, Reply& reply, QString* error) const{
    QJsonObject body;
    body["action"] = QString::fromLatin1(action);
    body["package"] = package;
    return request("POST", "/v1/app", QJsonDocument(body).toJson(QJsonDocument::Compact), reply, error);
}

bool MobileAgent::app_stop(const QString& package, QString* error) const{
    Reply reply;
    return app("stop", package, reply, error);
}

bool MobileAgent::app_start(const QString& package, QString* error) const{
    Reply reply;
    return app("start", package, reply, error);
}

bool MobileAgent::app_state(const QString& package, MobileLaunch& launch, QString* error) const{
    Reply reply;
    if (!app("state", package, reply, error)){
        return false;
    }
    const QJsonObject object = QJsonDocument::fromJson(reply.body).object();
    launch.running = object.value("running").toBool();
    launch.code = object.value("code").toInt();
    launch.error = object.value("error").toString();
    return true;
}

bool MobileAgent::app_end(const QString& package, QString* error) const{
    Reply reply;
    return app("end", package, reply, error);
}

bool MobileAgent::app_list(QStringList& packages, QString* error) const{
    QJsonObject body;
    body["action"] = "list";
    Reply reply;
    if (!request("POST", "/v1/app", QJsonDocument(body).toJson(QJsonDocument::Compact), reply, error)){
        return false;
    }
    packages.clear();
    for (const QJsonValue& one : QJsonDocument::fromJson(reply.body).object().value("packages").toArray()){
        packages << one.toString();
    }
    return true;
}

bool MobileAgent::heat(std::optional<double>& phone, std::optional<double>& pi, QString* error) const{
    Reply reply;
    if (!request("GET", "/v1/heat", QByteArray(), reply, error)){
        return false;
    }
    const QJsonObject object = QJsonDocument::fromJson(reply.body).object();
    const auto number = [&](const char* key) -> std::optional<double>{
        const QJsonValue value = object.value(QLatin1String(key));
        return value.isDouble() ? std::optional<double>(value.toDouble()) : std::nullopt;
    };
    phone = number("phone");
    pi = number("pi");
    return true;
}

namespace{
//  What /v1/power said under the key: a true or false, or an error when it said something else.
bool power_value(const QByteArray& body, const QString& key, bool& value, QString* error){
    const QJsonValue found = QJsonDocument::fromJson(body).object().value(key);
    if (!found.isBool()){
        if (error != nullptr){
            *error = "the agent did not say whether the phone is " + key;
        }
        return false;
    }
    value = found.toBool();
    return true;
}
}

bool MobileAgent::power_awake(bool& awake, QString* error) const{
    Reply reply;
    return request("GET", "/v1/power?only=awake", QByteArray(), reply, error) && power_value(reply.body, "awake", awake, error);
}

bool MobileAgent::power_locked(bool& locked, QString* error) const{
    Reply reply;
    return request("GET", "/v1/power?only=locked", QByteArray(), reply, error) && power_value(reply.body, "locked", locked, error);
}

bool MobileAgent::unlock(QString* error) const{
    return post("/v1/unlock", "{}", error);
}

bool MobileAgent::display_wm(QString& text, QString* error) const{
    Reply reply;
    if (!request("GET", "/v1/display?only=wm", QByteArray(), reply, error)){
        return false;
    }
    const QJsonValue found = QJsonDocument::fromJson(reply.body).object().value("wm");
    if (!found.isString()){
        if (error != nullptr){
            *error = "the agent did not say what the display size is";
        }
        return false;
    }
    text = found.toString();
    return true;
}

bool MobileAgent::display_files(MobileDisplayFiles& files, QString* error) const{
    Reply reply;
    if (!request("GET", "/v1/display?only=files", QByteArray(), reply, error)){
        return false;
    }
    const QJsonObject object = QJsonDocument::fromJson(reply.body).object();
    const QJsonObject paths = object.value("paths").toObject();
    files = MobileDisplayFiles();
    if (object.value("record").isString()){
        files.record = object.value("record").toString();
    }
    files.allow = object.value("allow").toBool();
    files.no_adapt = object.value("no_adapt").toBool();
    files.record_path = paths.value("record").toString();
    files.allow_path = paths.value("allow").toString();
    files.no_adapt_path = paths.value("no_adapt").toString();
    return true;
}

bool MobileAgent::display_record(const QJsonObject& record, QString* error) const{
    QJsonObject body = record;
    body["action"] = "record";
    return post("/v1/display", QJsonDocument(body).toJson(QJsonDocument::Compact), error);
}

bool MobileAgent::display_size(const QString& size, QString* error) const{
    QJsonObject body;
    body["action"] = "size";
    body["size"] = size;
    return post("/v1/display", QJsonDocument(body).toJson(QJsonDocument::Compact), error);
}

bool MobileAgent::display_reset(QString* error) const{
    return post("/v1/display", "{\"action\":\"reset\"}", error);
}

bool MobileAgent::display_forget(QString* error) const{
    return post("/v1/display", "{\"action\":\"forget\"}", error);
}

bool MobileAgent::bot_state(MobileBotState& state, int lines, QString* error) const{
    Reply reply;
    if (!request("GET", "/v1/bot?lines=" + QString::number(std::max(1, std::min(200, lines))), QByteArray(), reply, error)){
        return false;
    }
    const QJsonObject object = QJsonDocument::fromJson(reply.body).object();
    state.installed = object.value("installed").toBool();
    state.running = object.value("running").toBool();
    state.log.clear();
    for (const QJsonValue& line : object.value("log").toArray()){
        state.log << line.toString();
    }
    state.battle_app = object.value("battle_app").toString();
    state.battle_league = object.value("battle_league").toString();
    state.battle_count = object.value("battle_count").toInt();
    const QJsonObject battles = object.value("battles").toObject();
    state.battles_won = battles.value("won").toInt();
    state.battles_lost = battles.value("lost").toInt();
    const QJsonObject test = object.value("test").toObject();
    state.test = MobileBotTest();
    state.test.key = test.value("key").toString();
    state.test.title = test.value("title").toString();
    state.test.running = test.value("running").toBool();
    state.test.finished = !state.test.running && test.value("ok").isBool();
    state.test.ok = test.value("ok").toBool();
    state.test.result = test.value("result").toString();
    state.test.seconds = test.value("seconds").toInt();
    return true;
}

//  What a start or a test asks for, as the agent wants it.
static QJsonObject bot_body(const MobileBotStart& settings){
    QJsonObject options;
    for (const std::pair<QString, bool>& option : settings.options){
        options.insert(option.first, option.second);
    }
    QJsonObject body;
    body.insert("options", options);
    if (!settings.throw_target.isEmpty()){
        body.insert("throw_target", settings.throw_target);
    }
    if (!settings.daily_time.isEmpty()){
        body.insert("daily_time", settings.daily_time);
    }
    if (settings.daily_max_min > 0){
        body.insert("daily_max_min", settings.daily_max_min);
    }
    if (settings.daily_now){
        body.insert("daily_now", true);
    }
    if (settings.battle_app_given){
        body.insert("battle_app", settings.battle_app);
    }
    if (!settings.battle_league.isEmpty()){
        body.insert("battle_league", settings.battle_league);
    }
    if (settings.battle_count > 0){
        body.insert("battle_count", settings.battle_count);
    }
    return body;
}

bool MobileAgent::bot_start(const MobileBotStart& settings, QString* error) const{
    return post("/v1/bot/start", QJsonDocument(bot_body(settings)).toJson(QJsonDocument::Compact), error);
}

bool MobileAgent::bot_stop(QString* error) const{
    return post("/v1/bot/stop", "{}", error);
}

bool MobileAgent::bot_tests(std::vector<MobileBotChapter>& chapters, QString* error) const{
    Reply reply;
    if (!request("GET", "/v1/bot/tests", QByteArray(), reply, error)){
        return false;
    }
    chapters.clear();
    for (const QJsonValue& value : QJsonDocument::fromJson(reply.body).object().value("tests").toArray()){
        const QJsonObject object = value.toObject();
        MobileBotChapter chapter;
        chapter.key = object.value("key").toString();
        chapter.group = object.value("group").toString();
        chapter.title = object.value("title").toString();
        chapter.start = object.value("start").toString();
        chapter.what = object.value("what").toString();
        chapters.push_back(chapter);
    }
    return true;
}

bool MobileAgent::bot_test(const QString& key, const MobileBotStart& settings, QString* error) const{
    QJsonObject body = bot_body(settings);
    body.insert("key", key);
    return post("/v1/bot/test", QJsonDocument(body).toJson(QJsonDocument::Compact), error);
}

bool MobileAgent::bot_test_stop(QString* error) const{
    return post("/v1/bot/test/stop", "{}", error);
}

bool MobileAgent::bot_file(const QString& name, QByteArray& data, bool& found, QString* error) const{
    Reply reply;
    QString why;
    data.clear();
    found = false;
    if (request("GET", "/v1/bot/file?name=" + name, QByteArray(), reply, &why)){
        data = reply.body;
        found = true;
        return true;
    }
    if (reply.status == 404){
        return true;
    }
    if (error != nullptr){
        *error = why;
    }
    return false;
}


//  ---------------------------------------------------------------------
//  The test
//  ---------------------------------------------------------------------

namespace{

//  A gamebot.py that is not one: `gamebot.py chapter <key>` says in the log how it ended, as a real test
//  does ("TEST <key>: done - ..."); with a file called hang in its folder it waits to be stopped.
const char* const FAKE_GAMEBOT =
    "import os, signal, sys, time\n"
    "home = os.path.dirname(os.path.abspath(__file__))\n"
    "key = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == 'chapter' else ''\n"
    "def say(text):\n"
    "    with open(os.path.join(home, 'spin.log'), 'a', encoding='utf-8') as handle:\n"
    "        handle.write(time.strftime('%Y-%m-%d %H:%M:%S') + '  ' + text + '\\n')\n"
    "if os.path.exists(os.path.join(home, 'hang')):\n"
    "    def stopped(*_):\n"
    "        say('TEST ' + key + ': done - stopped')\n"
    "        sys.exit(0)\n"
    "    signal.signal(signal.SIGTERM, stopped)\n"
    "    say('TEST ' + key + ': begins')\n"
    "    while True:\n"
    "        time.sleep(0.05)\n"
    "say('TEST ' + key + ': done - all fine')\n";

QStringList read_lines(const QString& path){
    QFile file(path);
    QStringList lines;
    if (file.open(QIODevice::ReadOnly)){
        const QString all = QString::fromUtf8(file.readAll());
        for (const QString& line : all.split('\n')){
            if (!line.trimmed().isEmpty()){
                lines << line.trimmed();
            }
        }
    }
    return lines;
}

}

int run_mobile_test(QApplication& application, const QString& agent_folder){
    (void)application;
    Logger& logger = global_logger_tagged();
    int wrong = 0;
    QStringList report;
    //  The report is written when the test is over; until then every check goes into the file as it is made, with the seconds since the start, so that
    //  a test that is stopped from outside (the time limit of the CI) shows how far it came and where it was slow.
    QElapsedTimer started;
    started.start();
    QFile progress(agent_folder.isEmpty() ? QString() : agent_folder + "/mobile-test.txt");
    const bool progress_open = !agent_folder.isEmpty() && progress.open(QIODevice::WriteOnly | QIODevice::Truncate);
    auto check = [&](bool fine, const QString& what){
        report << (fine ? "ok:     " : "FAILED: ") + what;
        if (progress_open){
            const QString seconds = QString::number((double)started.elapsed() / 1000.0, 'f', 1);
            progress.write(("[" + seconds + " s] " + (fine ? "ok:     " : "FAILED: ") + what + "\n").toUtf8());
            progress.flush();
        }
        if (!fine){
            wrong++;
            logger.log("Mobile test: FAILED: " + what.toStdString(), COLOR_RED);
        }
    };
    auto finish = [&]() -> int{
        for (const QString& line : report){
            logger.log("Mobile test: " + line.toStdString());
        }
        if (progress_open){
            progress.close();
        }
        if (!agent_folder.isEmpty()){
            QFile file(agent_folder + "/mobile-test.txt");
            if (file.open(QIODevice::WriteOnly | QIODevice::Truncate)){
                QTextStream(&file) << report.join("\n") << "\n" << "the test took " << QString::number((double)started.elapsed() / 1000.0, 'f', 1) << " s\n";
            }
        }
        logger.log(
            wrong == 0
                ? "Mobile test: passed."
                : "Mobile test: " + std::to_string(wrong) + " failed.",
            wrong == 0 ? COLOR_BLUE : COLOR_RED
        );
        return wrong == 0 ? 0 : 1;
    };

    const QString script = agent_folder + "/claudegg_agent.py";
    const QString fake = agent_folder + "/fake_adb.py";
    check(QFile::exists(script) && QFile::exists(fake), "the agent and the fake phone are in " + agent_folder);
    QString python = QStandardPaths::findExecutable("python");
    if (python.isEmpty()){
        python = QStandardPaths::findExecutable("python3");
    }
    check(!python.isEmpty(), "Python is there to run the agent");
    //  The screen readers of the bot, ported to C++ (issue #30): held to the answers of the Python ones.
    {
        QStringList nav;
        const int differ = PokemonGo::Nav::run_nav_checks(agent_folder + "/../tests/fixtures/nav_golden.json", nav);
        for (const QString& line : nav){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, nav.isEmpty() ? QString("the screen readers answer as battle_nav.py does") : nav.last());
    }
    //  The brain of the fights, ported to C++ (issue #30): held to the answers of the Python one.
    {
        QStringList engine;
        const int differ = PokemonGo::Battle::run_engine_checks(
            agent_folder + "/../tests/fixtures/engine_golden.json",
            agent_folder + "/../models/battle_data.json",
            engine
        );
        for (const QString& line : engine){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, engine.isEmpty() ? QString("the brain of the fights answers as battle_engine.py does") : engine.last());
    }
    //  The state of a fight, ported to C++ (issue #30): fights played on it as they were played on the Python one.
    {
        QStringList fights;
        const int differ = PokemonGo::Fight::run_fight_checks(
            agent_folder + "/../tests/fixtures/fight_golden.json.qz",
            agent_folder + "/../models/battle_data.json",
            fights
        );
        for (const QString& line : fights){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, fights.isEmpty() ? QString("the state of a fight is kept as battle_fight.py keeps it") : fights.last());
    }
    //  The readers of the picture of a fight, ported to C++ (issue #30): pictures read as battle_vision.py reads them.
    {
        QStringList pictures;
        const int differ = PokemonGo::Vision::run_vision_checks(
            agent_folder + "/../tests/fixtures/vision_golden.json.qz",
            agent_folder + "/../tests/fixtures/fight",
            pictures
        );
        for (const QString& line : pictures){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, pictures.isEmpty() ? QString("the picture of a fight is read as battle_vision.py reads it") : pictures.last());
    }
    //  The little game of a charged attack, ported to C++ (issue #30): icons found and swipes planned as battle_minigame.py does.
    {
        QStringList minigame;
        const int differ = PokemonGo::Minigame::run_minigame_checks(
            agent_folder + "/../tests/fixtures/minigame_golden.json.qz",
            agent_folder + "/../tests/fixtures/minigame",
            minigame
        );
        for (const QString& line : minigame){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, minigame.isEmpty() ? QString("the little game of a charged attack is played as battle_minigame.py plays it") : minigame.last());
    }
    //  The fight loop, ported to C++ (issue #30): fights played on it as gamebot.py played them, picture by picture - every tap,
    //  swipe, line of the log and moment the same.
    {
        QStringList loop;
        const int differ = PokemonGo::Loop::run_loop_checks(
            agent_folder + "/../tests/fixtures/loop_golden.json.qz",
            agent_folder + "/../tests/fixtures",
            agent_folder + "/../models/battle_data.json",
            loop
        );
        for (const QString& line : loop){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, loop.isEmpty() ? QString("the fight loop plays a fight as gamebot.py plays it") : loop.last());
    }
    //  The walk around a fight, ported to C++ (issue #30): the menus to the party screen, the claim of a new rank, pop-ups, the
    //  list of leagues, the way back to the map and a run of battles, played as gamebot.py walks them - every screenshot and reading
    //  given, every tap, swipe, BACK, line of the log, sleep and saved picture of the walk the same, at the same moment.
    {
        QStringList flow;
        const int differ = PokemonGo::Flow::run_flow_checks(
            agent_folder + "/../tests/fixtures/flow_golden.json.qz",
            agent_folder + "/../tests/fixtures",
            flow
        );
        for (const QString& line : flow){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, flow.isEmpty() ? QString("the walk around a fight is walked as gamebot.py walks it") : flow.last());
    }
    //  Starting the game and the battles of a run, ported to C++ (issue #30): the two kinds of green button, the notices of the start,
    //  restart_game() and auto_battle(), played on the stories of the Python code.
    {
        QStringList start;
        const int differ = PokemonGo::Start::run_start_checks(agent_folder + "/../tests/fixtures/start_golden.json.qz", start);
        for (const QString& line : start){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, start.isEmpty() ? QString("the start of the game and the battles of a run are done as gamebot.py does them") : start.last());
    }
    //  A step on the map, ported to C++ (issue #31): the looks of the Brain at the map, do_map() (a Pokémon, a PokéStop, turning the
    //  camera, the gifts of the hour, the full storage, a fast catch that is checked) and do_pokestop(), with the readers of pixels, played
    //  on the stories of the Python code.
    {
        QStringList map;
        const int differ = PokemonGo::Map::run_map_checks(agent_folder + "/../tests/fixtures/map_golden.json.qz", map);
        for (const QString& line : map){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, map.isEmpty() ? QString("a step on the map is done as gamebot.py does it") : map.last());
    }
    //  What the throw of a ball looks at, ported to C++ (issue #31): the size of the coloured ring (measure_ring), the ball in the air and
    //  where it came down, the buttons of the catch screen and the teal OK of the result screen, the speed of the ring and what the bot
    //  learns from its last throws, and the curveball - on pictures drawn as the Python code's file says, with the same numbers out.
    {
        QStringList throw_report;
        const int differ = PokemonGo::Throw::run_throw_checks(agent_folder + "/../tests/fixtures/throw_golden.json.qz", throw_report);
        for (const QString& line : throw_report){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, throw_report.isEmpty() ? QString("the readers and the sums of the throw are done as gamebot.py does them") : throw_report.last());
    }
    //  The throw itself, ported to C++ (issue #31): holding the ball, following the ring, timing the release, the pictures of the flight
    //  and what the bot learns from them, the variation of a 'realistic' throw and the simple throw - little stories played on a
    //  pretend phone with a pretend clock, event by event as the Python code did them.
    {
        QStringList play_report;
        const int differ = PokemonGo::Throw::run_throwplay_checks(agent_folder + "/../tests/fixtures/throwplay_golden.json.qz", play_report);
        for (const QString& line : play_report){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, play_report.isEmpty() ? QString("the throw of a ball is done as gamebot.py does it") : play_report.last());
    }
    //  The catch screen around the throw, ported to C++ (issue #31): the ball that is chosen, the berry that is fed (the berry tray read
    //  by the tesseract program), the throws, waiting for the result, the OK of the result screen, the fast catch (BACK while the ball comes
    //  down) and finishing a catch when the time is up - little stories played on a pretend phone with a pretend clock, event by event as the
    //  Python code did them.
    {
        QStringList catch_report;
        const int differ = PokemonGo::Catch::run_catch_checks(agent_folder + "/../tests/fixtures/catch_golden.json.qz", catch_report);
        for (const QString& line : catch_report){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, catch_report.isEmpty() ? QString("the catch screen is handled as gamebot.py handles it") : catch_report.last());
    }
    //  One step of the bot, ported to C++ (issue #31): step() of gamebot.py - which screen is it and what is done with it (the heat, the shape
    //  of the screen, the phone that is awake, the screenshot that was handed on, away from the map or stuck: start the game again, a tap
    //  on a Pokemon that did nothing, Team GO Rocket, the first looks at the map, and the map, the stop, the catch screen, an egg, the
    //  summary, a news card, a group question, the safety notice, a full storage, the passenger pop-up and the result screen), held to what
    //  the Python code did on the little stories of tests/fixtures/step_golden.json.qz.
    {
        QStringList step_report;
        const int differ = PokemonGo::Step::run_step_checks(agent_folder + "/../tests/fixtures/step_golden.json.qz", step_report);
        for (const QString& line : step_report){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, step_report.isEmpty() ? QString("a step of the bot is made as gamebot.py makes it") : step_report.last());
    }
    //  The item bag, ported to C++ (issue #31): what the bag keeps of each item, the rows of a page of the bag, the question 'Discard <item>?'
    //  that is read and set to the number wanted, the way to the bag and back to the map, the clean-up of a full bag, the red FULL marks of the
    //  main menu and closing the game when the storage and the bag are both full, held to what the Python code did on the little stories of
    //  tests/fixtures/bag_golden.json.qz.
    {
        QStringList bag_report;
        const int differ = PokemonGo::Bag::run_bag_checks(agent_folder + "/../tests/fixtures/bag_golden.json.qz", bag_report);
        for (const QString& line : bag_report){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, bag_report.isEmpty() ? QString("the item bag is handled as gamebot.py handles it") : bag_report.last());
    }
    //  The gifts of the friends, ported to C++ (issue #31): the rows of the friend list with the pink bow of a gift that waits and the grey arrow
    //  of one that is on its way, the readers of the gift screens, the memory of the day, a visit to one friend (open the gift, scroll the profile
    //  to SEND GIFT, choose a gift, SEND) and the whole round, held to what the Python code did on the little stories of
    //  tests/fixtures/gifts_golden.json.qz.
    {
        QStringList gifts_report;
        const int differ = PokemonGo::Gifts::run_gifts_checks(agent_folder + "/../tests/fixtures/gifts_golden.json.qz", gifts_report);
        for (const QString& line : gifts_report){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, gifts_report.isEmpty() ? QString("the gifts are handled as gamebot.py handles them") : gifts_report.last());
    }
    //  The quests of the GO Pass, ported to C++ (issue #31): the check whether the quest button on the map is gold, whether it is time to look at it,
    //  and the visit (the tab GO PASS, its pages, VIEW REWARDS, CLAIM ALL, a Pokémon that comes as a reward, the X that closes it), held to what the
    //  Python code did on the little stories of tests/fixtures/quests_golden.json.qz.
    {
        QStringList quests_report;
        const int differ = PokemonGo::Quests::run_quests_checks(agent_folder + "/../tests/fixtures/quests_golden.json.qz", quests_report);
        for (const QString& line : quests_report){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, quests_report.isEmpty() ? QString("the quests are handled as gamebot.py handles them") : quests_report.last());
    }
    //  Team GO Rocket at a stop, ported to C++ (issue #31): the way from the first speech bubble to the map or the Shadow Pokémon (BATTLE, the radar
    //  question, the party and its empty slots, the list of Pokémon, the summary), held to what the Python code did on the little stories of
    //  tests/fixtures/rocket_golden.json.qz.  (The fight itself is a seam in these stories.)
    {
        QStringList rocket_report;
        const int differ = PokemonGo::Rocket::run_rocket_checks(agent_folder + "/../tests/fixtures/rocket_golden.json.qz", rocket_report);
        for (const QString& line : rocket_report){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, rocket_report.isEmpty() ? QString("the way through Team GO Rocket is walked as gamebot.py walks it") : rocket_report.last());
    }
    //  The fight against Team GO Rocket itself, ported to C++ (issue #31): the fast taps, the shield, the charged attacks, the little game of the type
    //  of the attack, until the fight is over, played on the real pictures of fights and little games (tests/fixtures/rocketfight_golden.json.qz).
    {
        QStringList fight_report;
        const int differ = PokemonGo::Loop::run_rocket_fight_checks(agent_folder + "/../tests/fixtures/rocketfight_golden.json.qz",
            agent_folder + "/../tests/fixtures", agent_folder + "/../models/battle_data.json", fight_report);
        for (const QString& line : fight_report){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, fight_report.isEmpty() ? QString("the fight against Team GO Rocket is fought as gamebot.py fights it") : fight_report.last());
    }
    //  The daily run, ported to C++ (issue #31): the start time of the day, the apps one after the other, the time of the run, the battles and the teams
    //  first, a catch that is finished, the battles that go on after a reward - played on a pretend phone with a pretend clock, held to what the Python
    //  code did on the stories of tests/fixtures/daily_golden.json.qz.
    {
        QStringList daily_report;
        const int differ = PokemonGo::Daily::run_daily_checks(agent_folder + "/../tests/fixtures/daily_golden.json.qz", daily_report);
        for (const QString& line : daily_report){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, daily_report.isEmpty() ? QString("the daily run is played as gamebot.py plays it") : daily_report.last());
    }
    //  The lock screen of the phone and the game that dims and locks itself, ported to C++ (issue #31): held to what the Python code did on the
    //  stories of tests/fixtures/lock_golden.json.qz.
    {
        QStringList lock_report;
        const int differ = PokemonGo::Lock::run_lock_checks(agent_folder + "/../tests/fixtures/lock_golden.json.qz", lock_report);
        for (const QString& line : lock_report){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, lock_report.isEmpty() ? QString("the lock screen is taken away as spin_stop.py takes it away") : lock_report.last());
    }
    //  The shape of the screen, the menu button and the change of the display size, ported to C++ (issue #31): held to what the Python code did on the
    //  stories of tests/fixtures/layout_golden.json.qz.
    {
        QStringList layout_report;
        const int differ = PokemonGo::Layout::run_layout_checks(agent_folder + "/../tests/fixtures/layout_golden.json.qz", layout_report);
        for (const QString& line : layout_report){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, layout_report.isEmpty() ? QString("the layout of the game is checked as gamebot.py checks it") : layout_report.last());
    }
    //  The text reader, ported to C++ (issue #30): the table that Tesseract writes made into lines of words with their places, as
    //  gamebot.ocr_lines() makes them (354 tables, 36 of them read from frames of real fights), and - where the tesseract program is
    //  found - a picture with words drawn on it read with it.
    {
        QStringList text;
        const int differ = PokemonGo::Text::run_text_checks(agent_folder + "/../tests/fixtures/text_golden.json.qz", text);
        for (const QString& line : text){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, text.isEmpty() ? QString("the text reader reads the table of Tesseract as gamebot.py does") : text.mid(qMax<qsizetype>(0, text.size() - 2)).join("; "));
    }
    //  The phone side of the fight loop (issue #30), what needs no phone: the pictures of the agent as pictures of OpenCV, the
    //  canvas and the real screen, the files of what the bot learns (in the format of gamebot.py).
    {
        QStringList phone_report;
        const int differ = PokemonGo::Phone::run_phone_checks(phone_report);
        for (const QString& line : phone_report){
            if (line.startsWith("FAILED: ")){
                check(false, line.mid(8));
            }
        }
        check(differ == 0, phone_report.isEmpty() ? QString("the pictures, the coordinates and the files of the phone side are as they should be") : phone_report.last());
    }
    //  The networks of the Pokémon GO bot (RegiBot), run with ONNX Runtime: what the screen classifier, the two detectors and
    //  the throw predictor say is what gamebot.py says with LiteRT (issue #30).  The ONNX copies are not in the repository: the
    //  build makes them (Mobile/tools/convert_models_to_onnx.py) and names their folder in CLAUDEGG_MODELS.  Without the
    //  variable (a run on a computer that has no models) this part is left out.
    {
        const QString models = qEnvironmentVariable("CLAUDEGG_MODELS");
        if (!models.isEmpty()){
            QStringList lines;
            const int differ = PokemonGo::Models::run_models_checks(
                agent_folder + "/../tests/fixtures/models_golden.json",
                agent_folder + "/../tests/fixtures",
                models,
                lines
            );
            for (const QString& line : lines){
                if (line.startsWith("FAILED: ")){
                    check(false, line.mid(8));
                }
            }
            check(differ == 0, lines.isEmpty() ? QString("the models are run as gamebot.py runs them") : lines.last());
        }
    }
    if (wrong != 0){
        return finish();
    }

    QTemporaryDir scratch;
    check(scratch.isValid(), "a folder for the test");
    const QString token_file = scratch.path() + "/token";
    const QString adb_log = scratch.path() + "/adb.log";
    const QString off_file = scratch.path() + "/off";
    //  The live picture of the test: this file, again and again (see fake_video.py).
    const QString video_file = scratch.path() + "/picture.jpg";
    const QString fake_video = agent_folder + "/fake_video.py";
    //  The Pokémon GO bot: its files are in a folder of the test, its service is a fake one.
    const QString fake_systemctl = agent_folder + "/fake_systemctl.py";
    const QString bot_home = scratch.path() + "/bot";
    check(QDir().mkpath(bot_home) && QFile::exists(fake_systemctl), "the folder of the bot and the fake service are there");
    {
        QImage red(48, 96, QImage::Format_RGB32);
        red.fill(QColor(200, 30, 30));
        check(red.save(video_file, "JPG", 95), "a picture for the live video is made");
        check(QFile::exists(fake_video), "the fake live picture is in " + agent_folder);
    }

    QProcess agent;
    QProcessEnvironment environment = QProcessEnvironment::systemEnvironment();
    environment.insert("FAKE_ADB_LOG", adb_log);
    environment.insert("FAKE_ADB_FAIL_FILE", off_file);
    //  What the fake phone says of its power and its lock screen when these files are there (see fake_adb.py).
    const QString power_file = scratch.path() + "/power";
    const QString window_file = scratch.path() + "/window";
    environment.insert("FAKE_POWER_FILE", power_file);
    environment.insert("FAKE_WINDOW_FILE", window_file);
    //  The display size that the fake phone says (see fake_adb.py: `wm size WxH` and `wm size reset` write it; no file: the fixed answer), and the home
    //  folder of the agent, where it keeps the files of the display (the record and the two switch files).
    const QString wm_file = scratch.path() + "/wm";
    const QString home_folder = scratch.path() + "/home";
    check(QDir().mkpath(home_folder), "a home folder for the agent");
    environment.insert("FAKE_WM_FILE", wm_file);
    environment.insert("HOME", home_folder);                                    //  (where Python looks for "~" on Linux and macOS ...)
    environment.insert("USERPROFILE", QDir::toNativeSeparators(home_folder));   //  (... and on Windows)
    environment.insert("FAKE_MONKEY_FILE", scratch.path() + "/monkey");
    environment.insert("FAKE_SYSTEMCTL_STATE", scratch.path() + "/service-state");
    environment.insert("FAKE_SYSTEMCTL_LOG", scratch.path() + "/service-calls");
    agent.setProcessEnvironment(environment);
    agent.setProcessChannelMode(QProcess::MergedChannels);
    agent.start(python, QStringList{
        script, "--host", "127.0.0.1", "--port", "0",
        "--adb", python, "--adb-arg", fake, "--token-file", token_file,
        "--video-cmd", python, "--video-arg", fake_video, "--video-arg", video_file,
        "--bot-home", bot_home, "--systemctl", python, "--systemctl", fake_systemctl,
        "--bot-python", python,
    });
    check(agent.waitForStarted(15000), "the agent starts");

    //  It says on which port it listens.
    int port = 0;
    QByteArray heard;
    QElapsedTimer clock;
    clock.start();
    while (port == 0 && clock.elapsed() < 20000 && agent.state() != QProcess::NotRunning){
        if (agent.waitForReadyRead(500)){
            heard += agent.readAll();
            const qsizetype at = heard.indexOf("listening on port ");
            if (at >= 0){
                port = heard.mid(at + 18).split('\n').front().trimmed().toInt();
            }
        }
    }
    check(port > 0, "the agent says on which port it listens (" + QString::number(port) + ")");
    if (port <= 0){
        agent.kill();
        agent.waitForFinished(3000);
        return finish();
    }

    QString token;
    {
        QFile file(token_file);
        if (file.open(QIODevice::ReadOnly)){
            token = QString::fromUtf8(file.readAll()).trimmed();
        }
    }
    check(token.size() >= 16, "the agent made a token");

    const MobileAgent phone("127.0.0.1", port, token, 20000);
    QString error;

    check(phone.ping(&error), "ping: " + error);

    //  The token.
    {
        const MobileAgent stranger("127.0.0.1", port, "not-the-token", 20000);
        MobileInfo info;
        error.clear();
        check(!stranger.info(info, &error) && error.contains("token"), "a wrong token is refused (" + error + ")");
        error.clear();
        check(!stranger.tap(1, 1, 120, &error), "and cannot tap");
        check(read_lines(adb_log).isEmpty(), "and nothing went to the phone");
    }

    //  The phone.
    {
        MobileInfo info;
        error.clear();
        const bool fine = phone.info(info, &error);
        check(fine, "the phone is described: " + error);
        check(info.model == "FakePhone" && info.android == "14", "its model and Android (" + info.model + ", " + info.android + ")");
        check(info.width == 1000 && info.height == 2200, "its size is the size that was set (" + QString::number(info.width) + "x" + QString::number(info.height) + ")");
        check(
            info.features.contains("tap_kind") && info.features.contains("app") && info.features.contains("bot_file") && info.features.contains("app_list")
                && info.features.contains("heat") && info.features.contains("power") && info.features.contains("display"),
            "the agent (" + info.version + ") can do what GO Battle League, the daily run, the pause for the heat, the lock screen and the layout of the game need when Claude GG plays: " + info.features.join(", ")
        );
    }
    //  The files of the bot's battles (the team), read only.
    {
        QByteArray data;
        bool found = true;
        error.clear();
        check(phone.bot_file("battle_team.json", data, found, &error) && !found, "the Pi without a team says so: " + error);
        {
            QFile team(bot_home + "/battle_team.json");
            check(team.open(QIODevice::WriteOnly | QIODevice::Truncate) && team.write("[{\"species\": \"Noctowl\"}]") > 0, "a team is written on the Pi");
        }
        error.clear();
        check(phone.bot_file("battle_team.json", data, found, &error) && found && data == "[{\"species\": \"Noctowl\"}]", "and it is read as it is: " + error);
        error.clear();
        check(!phone.bot_file("gamebot_control.json", data, found, &error) && !error.isEmpty(), "another file of the bot is refused (" + error + ")");
        QFile::remove(bot_home + "/battle_team.json");
    }
    {
        QImage picture;
        error.clear();
        const bool fine = phone.screen(picture, &error);
        check(fine, "the screen is a picture: " + error);
        check(picture.width() == 48 && picture.height() == 96, "of the size of the screen the phone gave");
        const QColor colour = picture.isNull() ? QColor() : picture.pixelColor(10, 10);
        check(colour.red() == 200 && colour.green() == 30 && colour.blue() == 30, "and the colours are those of the phone");
    }

    //  What it presses.
    const QStringList before = read_lines(adb_log);
    error.clear();
    check(phone.tap(300, 400, 120, &error), "a tap: " + error);
    check(phone.tap(5, 6, 80, &error), "a tap of 80 milliseconds");
    check(phone.swipe(1, 2, 3, 4, 300, &error), "a swipe: " + error);
    check(phone.swipes({{1, 2, 3, 4, 100}, {5, 6, 7, 8, 200}}, &error), "swipes: " + error);
    check(phone.key("BACK", &error), "a key: " + error);
    check(phone.text("a b", &error), "a text: " + error);
    check(phone.wake(&error), "waking: " + error);
    {
        QString out;
        check(phone.touch({{"DOWN", 1, 2}, {"MOVE", 3, 4}, {"UP", 5, 6}}, out, &error), "touch events (agent 0.2.2): " + error);
        QString refused;
        check(!phone.touch({{"PRESS", 1, 2}}, out, &refused) && !refused.isEmpty(), "a touch event that does not exist is refused (" + refused + ")");
    }
    const QStringList pressed = read_lines(adb_log).mid(before.size());
    const QStringList wanted{
        "shell input swipe 300 400 300 400 120",
        "shell input swipe 5 6 5 6 80",
        "shell input swipe 1 2 3 4 300",
        "shell input swipe 1 2 3 4 100; input swipe 5 6 7 8 200",
        "shell input keyevent 4",
        "shell input text a%sb",
        "shell input keyevent 224",
        "shell { input motionevent DOWN 1 2; input motionevent MOVE 3 4; input motionevent UP 5 6; } 2>&1",
    };
    check(pressed == wanted, "the phone was asked just that (" + QString::number(pressed.size()) + " commands)");
    if (pressed != wanted){
        for (const QString& line : pressed){
            report << "         it was asked: " + line;
        }
    }

    //  What is not allowed does not get to the phone.
    {
        const qsizetype count = read_lines(adb_log).size();
        error.clear();
        check(!phone.tap(-1, 5, 120, &error) && !error.isEmpty(), "a tap outside the screen is refused (" + error + ")");
        error.clear();
        check(!phone.key("REBOOT", &error) && !error.isEmpty(), "a key that does not exist is refused (" + error + ")");
        error.clear();
        check(!phone.text("x; reboot", &error) && !error.isEmpty(), "a text that could be a command is refused (" + error + ")");
        check(read_lines(adb_log).size() == count, "none of them reached the phone");
    }

    //  The phone side of the fight loop (issue #30) against this agent and this made-up phone: the touches reach it as the loop asks
    //  for them, the screenshot is the canvas, the live video gives pictures with the time they came in, and a phone that is off is
    //  told in the log.
    {
        using namespace PokemonGo::Phone;
        std::mutex told_lock;
        QStringList told;
        Options options;
        options.folder = scratch.path() + "/loop";
        AgentHost host("127.0.0.1", port, token, options, [&](const QString& line){
            std::lock_guard<std::mutex> lock(told_lock);
            told << line;
        });
        check(host.screen_width() == 1000 && host.screen_height() == 2200, "the host knows the size of the screen (1000 x 2200)");

        {
            const QStringList start = read_lines(adb_log);
            std::unique_ptr<PokemonGo::Loop::Tapper> tapper = host.make_tapper(PokemonGo::Loop::Point{884, 1104}, 70);
            tapper->tap(884, 1104, 120);
            tapper->tap(884, 1104, 0);
            tapper->touch(0, 884, 1104);
            tapper->touch(1, 884, 1104);
            tapper->touch(2, 884, 1104);
            tapper->touch(3, 884, 1104);
            tapper->close();
            const QStringList got = read_lines(adb_log).mid(start.size());
            const QStringList want{
                "shell input swipe 500 1100 500 1100 120",
                "shell input swipe 500 1100 500 1100 1",
                "shell input tap 500 1100",
                "shell input motionevent DOWN 500 1100; sleep 0.08; input motionevent UP 500 1100",
                "shell input swipe 500 1100 500 1100 60",
                "shell input swipe 500 1100 500 1100 220",
            };
            check(got == want, "the touches of the loop reach the phone on the real screen (" + QString::number(got.size()) + " commands)");
            if (got != want){
                for (const QString& line : got){
                    report << "         it was asked: " + line;
                }
            }
        }
        {
            const QStringList start = read_lines(adb_log);
            AgentFingers fingers(phone, 1000, 2200, nullptr);
            fingers.swipes({{884, 1104, 0, 0, 100}, {1768, 2208, 884, 1104, 0}});
            std::vector<PokemonGo::Loop::Stroke> many;
            for (int i = 0; i < 51; i++){
                many.push_back(PokemonGo::Loop::Stroke{0, 0, 884, 1104, 50});
            }
            fingers.swipes(many);
            const QStringList got = read_lines(adb_log).mid(start.size());
            check(got.size() == 3 && got[0] == "shell input swipe 500 1100 0 0 100; input swipe 1000 2200 500 1100 1",
                  "swipes go in one command (a swipe of no time takes a millisecond)");
            check(got.size() == 3 && got[1].count("input swipe") == 50 && got[2].count("input swipe") == 1, "and 51 of them in a command of 50 and one of 1");
        }
        {
            //  A phone that is off: the touch is not lost without a word.
            QFile off(off_file);
            check(off.open(QIODevice::WriteOnly), "the phone is switched off");
            off.close();
            std::unique_ptr<PokemonGo::Loop::Tapper> tapper = host.make_tapper(PokemonGo::Loop::Point{884, 1104}, 70);
            tapper->tap(10, 10, 120);
            tapper->close();
            QFile::remove(off_file);
            std::lock_guard<std::mutex> lock(told_lock);
            check(!told.isEmpty() && told.last().contains("did not reach the phone") && told.last().contains("device offline"),
                  "a touch that did not reach the phone is told in the log (" + (told.isEmpty() ? QString() : told.last()) + ")");
        }
        {
            error.clear();
            cv::Mat canvas;
            try{
                canvas = host.screenshot();
            }catch (const std::exception& e){
                error = e.what();
            }
            check(canvas.cols == 1768 && canvas.rows == 2208 && canvas.type() == CV_8UC3, "the screenshot is on the canvas of the bot: " + error);
            const cv::Vec3b middle = canvas.empty() ? cv::Vec3b() : canvas.at<cv::Vec3b>(1000, 800);
            check(middle[2] == 200 && middle[1] == 30 && middle[0] == 30, "with the colours of the phone (as blue, green, red)");
            //  (the screenshot is 48 x 96: the real screen is what it says, as spin_stop._normalize does)
            check(host.screen_width() == 48 && host.screen_height() == 96, "the size of the real screen is the size of the screenshot");
            const QStringList start = read_lines(adb_log);
            std::unique_ptr<PokemonGo::Loop::Tapper> tapper = host.make_tapper(PokemonGo::Loop::Point{884, 1104}, 70);
            tapper->tap(884, 1104, 120);
            tapper->close();
            const QStringList got = read_lines(adb_log).mid(start.size());
            check(got == QStringList{"shell input swipe 24 48 24 48 120"}, "and the touches go by it from then on");
        }
        //  The walk around a fight and the start of the game (Flow::Host and Start::Host) against the same agent: the real screen is 48 x 96
        //  now, a press of the walk is a press of 120 ms, a swipe is one swipe, BACK is the key, and the game is closed and started by
        //  /v1/app.
        {
            const QString game = "com.nianticlabs.pokemongo";
            const QString monkey_file = scratch.path() + "/monkey";
            const QStringList start = read_lines(adb_log);
            host.tap(884, 1104);
            host.swipe(884, 1500, 884, 700, 300);
            host.back();
            const QStringList got = read_lines(adb_log).mid(start.size());
            check(got == QStringList{"shell input swipe 24 48 24 48 120", "shell input swipe 24 65 24 30 300", "shell input keyevent 4"},
                  "a tap, a swipe and BACK of the walk reach the phone (" + got.join(" | ") + ")");
            const double wall = host.wall();
            check(std::abs(wall - (double)QDateTime::currentSecsSinceEpoch()) < 5.0, "the clock of the walk is the clock of the day");
            check(std::abs(host.monotonic() - now_seconds()) < 1.0, "and the other clock is the steady one");

            //  A phone that is off: BACK that does not arrive is an error (adb raises in gamebot.py), a press is told in the log.
            {
                QFile off(off_file);
                check(off.open(QIODevice::WriteOnly), "the phone is switched off");
                off.close();
                std::string what;
                try{
                    host.back();
                }catch (const std::exception& e){
                    what = e.what();
                }
                check(what.find("BACK did not reach the phone") != std::string::npos && what.find("device offline") != std::string::npos,
                      "BACK that does not reach the phone throws (" + QString::fromStdString(what) + ")");
                std::string closing;
                try{
                    host.stop_game();
                }catch (const std::exception& e){
                    closing = e.what();
                }
                check(closing.find("closing the game failed") != std::string::npos && closing.find("device offline") != std::string::npos,
                      "closing the game when the phone is off throws (" + QString::fromStdString(closing) + ")");
                host.start_game();
                PokemonGo::Start::Launch failed = host.start_state();
                for (int i = 0; failed.running && i < 200; i++){
                    std::this_thread::sleep_for(std::chrono::milliseconds(50));
                    failed = host.start_state();
                }
                check(!failed.running && failed.code != 0 && failed.error.contains("device offline"), "a start that does not get to the phone is a start that failed");
                host.start_end();
                QFile::remove(off_file);
            }

            //  Closing and starting the game.
            const QStringList closing_start = read_lines(adb_log);
            host.stop_game();
            host.start_game();
            PokemonGo::Start::Launch launch = host.start_state();
            for (int i = 0; launch.running && i < 200; i++){
                std::this_thread::sleep_for(std::chrono::milliseconds(50));
                launch = host.start_state();
            }
            host.start_end();
            const QStringList closed = read_lines(adb_log).mid(closing_start.size());
            check(closed == QStringList{"shell am force-stop " + game, "shell monkey -p " + game + " -c android.intent.category.LAUNCHER 1"},
                  "the game is closed and started with the commands of the bot (" + closed.join(" | ") + ")");
            check(!launch.running && launch.code == 0 && launch.error.isEmpty(), "and the start ends well");

            //  A start that fails says what monkey said; one that does not come back is let go of.
            {
                QFile out(monkey_file);
                check(out.open(QIODevice::WriteOnly | QIODevice::Truncate), "the fake monkey is told to fail");
                out.write("fail:** No activities found to run, monkey aborted.");
            }
            host.start_game();
            PokemonGo::Start::Launch failed = host.start_state();
            for (int i = 0; failed.running && i < 200; i++){
                std::this_thread::sleep_for(std::chrono::milliseconds(50));
                failed = host.start_state();
            }
            check(!failed.running && failed.code == 1 && failed.error.contains("No activities found"), "a start that fails says what monkey said (" + failed.error + ")");
            {
                QFile out(monkey_file);
                check(out.open(QIODevice::WriteOnly | QIODevice::Truncate), "the fake monkey is told to hang");
                out.write("hang:30");
            }
            const double began = now_seconds();
            host.start_game();
            check(now_seconds() - began < 5.0, "the start of the game is not waited for");
            const PokemonGo::Start::Launch running = host.start_state();
            check(running.running && running.code == 0 && running.error.isEmpty(), "a start that does not come back is still running");
            host.start_end();
            MobileLaunch gone;
            error.clear();
            check(!phone.app_state(game, gone, &error) && error.contains("was not started"), "and is let go of (" + error + ")");
            QFile::remove(monkey_file);

            //  The apps that are installed: the Play Store one first, an app that could not be started left out.
            {
                QStringList installed;
                error.clear();
                check(phone.app_list(installed, &error), "the installed apps are asked for: " + error);
                check(installed == QStringList({game, game + ".ares"}), "the Play Store one first, the app of another name left out (" + installed.join(", ") + ")");
                check(read_lines(adb_log).last() == "shell pm list packages pokemongo", "from `pm list packages`");
            }

            //  The temperatures: the battery of the phone (31.2 degrees in the fake one), and the Pi's processor when this machine has one.
            {
                std::optional<double> battery;
                std::optional<double> processor;
                error.clear();
                check(phone.heat(battery, processor, &error), "the temperatures are asked for: " + error);
                check(battery.has_value() && std::abs(*battery - 31.2) < 1e-9, "the battery of the phone is 31.2 degrees (" + QString::number(battery.value_or(-99)) + ")");
                check(!processor.has_value() || (*processor > -100 && *processor < 200), "the processor is nothing or a temperature (" + QString::number(processor.value_or(-99)) + ")");
                check(read_lines(adb_log).last() == "shell dumpsys battery", "from `dumpsys battery`");
            }

            //  The power of the phone (agent 0.2.5): awake and no lock screen in the fake one, what the files of the fake phone say when they are there.
            {
                const auto say = [&](const QString& file, const QByteArray& text){
                    QFile out(file);
                    check(out.open(QIODevice::WriteOnly | QIODevice::Truncate) && out.write(text) >= 0, "the fake phone is told what to say");
                };
                bool awake = false;
                bool locked = true;
                error.clear();
                check(phone.power_awake(awake, &error) && awake, "the phone is awake: " + error);
                check(read_lines(adb_log).last() == "shell dumpsys power", "from `dumpsys power`");
                check(phone.power_locked(locked, &error) && !locked, "and shows no lock screen: " + error);
                check(read_lines(adb_log).last() == "shell dumpsys window", "from `dumpsys window`");
                say(power_file, "  mWakefulness=Asleep\n");
                check(phone.power_awake(awake, &error) && !awake, "a phone that sleeps is not awake");
                say(power_file, "  mWakefulness=Dozing\n");
                check(phone.power_awake(awake, &error) && !awake, "nor one that dozes");
                say(window_file, "  mCurrentFocus=null\n  isKeyguardShowing=true\n");
                check(phone.power_locked(locked, &error) && locked, "a phone with a lock screen says so");
                error.clear();
                check(phone.unlock(&error), "the lock screen is dismissed: " + error);
                check(read_lines(adb_log).last() == "shell wm dismiss-keyguard", "with `wm dismiss-keyguard`");
                {
                    QFile off(off_file);
                    check(off.open(QIODevice::WriteOnly), "the phone is switched off");
                    off.close();
                    error.clear();
                    awake = true;
                    check(!phone.power_awake(awake, &error) && error.contains("device offline"), "a phone that is off is no answer (" + error + ")");
                    error.clear();
                    locked = false;
                    check(!phone.power_locked(locked, &error) && error.contains("device offline"), "neither is it for the lock screen (" + error + ")");
                    error.clear();
                    check(!phone.unlock(&error) && error.contains("device offline"), "and the lock screen is not dismissed (" + error + ")");
                    QFile::remove(off_file);
                }
                QFile::remove(power_file);
                QFile::remove(window_file);
                check(phone.power_awake(awake, &error) && awake && phone.power_locked(locked, &error) && !locked, "it is awake and unlocked again when the files are gone");
            }

            //  The display (agent 0.2.6): what `wm size` says, the files of the Pi, and the steps of a change (record, size, reset, forget).
            {
                const auto write_text = [&](const QString& file, const QByteArray& text){
                    QFile out(file);
                    check(out.open(QIODevice::WriteOnly | QIODevice::Truncate) && out.write(text) >= 0, "a file of the fake phone is written");
                };
                QString wm;
                error.clear();
                check(phone.display_wm(wm, &error) && wm == "Physical size: 1080x2340\nOverride size: 1000x2200\n", "the display size is what `wm size` says (" + wm + ") " + error);
                check(read_lines(adb_log).last() == "shell wm size", "asked with `wm size`");
                MobileDisplayFiles files;
                error.clear();
                check(phone.display_files(files, &error) && !files.record.has_value() && !files.allow && !files.no_adapt, "the Pi has no record and no switch file yet: " + error);
                check(QDir::fromNativeSeparators(files.record_path) == home_folder + "/gamebot_wm_override.json"
                      && QDir::fromNativeSeparators(files.allow_path) == home_folder + "/gamebot_allow_unsupported"
                      && QDir::fromNativeSeparators(files.no_adapt_path) == home_folder + "/gamebot_no_display_change",
                      "the files are in the home folder of the agent (" + files.record_path + ")");
                const QStringList before_display = read_lines(adb_log);
                error.clear();
                check(!phone.display_size("1080x1348", &error) && error.contains("write down"), "a size is not set before it is written down (" + error + ")");
                check(read_lines(adb_log) == before_display, "and the phone did not hear of it");
                QJsonObject record;
                record["set"] = "1080x1348";
                record["time"] = 1234.5;
                record["model"] = "Fake";
                record["was"] = "1080x2340";
                error.clear();
                check(phone.display_record(record, &error), "what is going to be changed is written down: " + error);
                check(phone.display_files(files, &error) && files.record.has_value()
                      && QJsonDocument::fromJson(files.record->toUtf8()).object() == record, "and the Pi has it as it was said");
                QJsonObject command = record;
                command["set"] = "1080x1348; reboot";
                error.clear();
                check(!phone.display_record(command, &error) && !error.isEmpty(), "a size that could be a command is not written down (" + error + ")");
                error.clear();
                check(!phone.display_size("1080x1349", &error) && error.contains("write down"), "a size that the record does not name is not set (" + error + ")");
                write_text(wm_file, "");
                error.clear();
                check(phone.display_size("1080x1348", &error), "the size that the record names is set: " + error);
                check(read_lines(adb_log).last() == "shell wm size 1080x1348", "with `wm size`");
                check(phone.display_wm(wm, &error) && wm == "Physical size: 1080x2340\nOverride size: 1080x1348\n", "and `wm size` says so (" + wm + ")");
                write_text(home_folder + "/gamebot_no_display_change", "");
                error.clear();
                check(phone.display_files(files, &error) && files.no_adapt, "a switch file that is there is seen");
                check(!phone.display_size("1080x1348", &error) && error.contains("is not changed"), "and the size is not set while it is there (" + error + ")");
                QFile::remove(home_folder + "/gamebot_no_display_change");
                error.clear();
                check(phone.display_reset(&error), "the size is put back: " + error);
                check(read_lines(adb_log).last() == "shell wm size reset", "with `wm size reset`");
                check(phone.display_wm(wm, &error) && wm == "Physical size: 1080x2340\n", "and `wm size` says no override any more (" + wm + ")");
                check(phone.display_forget(&error) && phone.display_files(files, &error) && !files.record.has_value(), "the record is forgotten");
                {
                    QFile off(off_file);
                    check(off.open(QIODevice::WriteOnly), "the phone is switched off");
                    off.close();
                    error.clear();
                    check(!phone.display_wm(wm, &error) && error.contains("device offline"), "a phone that is off says no size (" + error + ")");
                    error.clear();
                    check(!phone.display_reset(&error) && error.contains("device offline"), "and does not put it back (" + error + ")");
                    QFile::remove(off_file);
                }
                QFile::remove(wm_file);
            }

            //  What the agent refuses.
            const QStringList count = read_lines(adb_log);
            error.clear();
            check(!phone.app_stop("com.android.settings", &error) && !error.isEmpty(), "an app that is not Pokémon GO is not closed (" + error + ")");
            error.clear();
            check(!phone.app_start("com.nianticlabs.pokemongo; reboot", &error) && !error.isEmpty(), "a package that could be a command is refused (" + error + ")");
            check(read_lines(adb_log).size() == count.size(), "none of them reached the phone");

            //  The day on which the battles were done is kept in the folder of the bot (battle_done.json of gamebot.py).
            check(!host.battles_done_today(), "the battles are not done before the Battle screen says so");
            host.mark_battles_done();
            check(host.battles_done_today(), "the day on which the Battle screen showed a grey BATTLE button is written down");
            QFile done(options.folder + "/battle_done.json");
            check(done.open(QIODevice::ReadOnly), "in battle_done.json");
            const QJsonObject done_object = QJsonDocument::fromJson(done.readAll()).object();
            check(done_object.size() == 1 && done_object.value("day").toString() == PokemonGo::Phone::today_text()
                  && QDate::fromString(done_object.value("day").toString(), "yyyy-MM-dd").isValid(), "as the day, like \"2026-11-22\"");
            done.close();
            {
                QFile out(options.folder + "/battle_done.json");
                check(out.open(QIODevice::WriteOnly | QIODevice::Truncate), "the file of another day can be written");
                out.write("{\"day\": \"2001-01-01\"}");
            }
            check(!host.battles_done_today(), "a day that is gone is not today");
            {
                QFile out(options.folder + "/battle_done.json");
                check(out.open(QIODevice::WriteOnly | QIODevice::Truncate), "the file can be written");
                out.write("{not json");
            }
            check(!host.battles_done_today(), "a file that is no file is nothing done");
            QFile::remove(options.folder + "/battle_done.json");

            //  What only the program knows.
            check(host.day_count("won").isEmpty() && host.team_names().isEmpty() && !host.no_more(), "without a program nothing is known of the day, the team or the time");
            host.beat();
            int beats = 0;
            PokemonGo::Phone::Hooks hooks;
            hooks.day_count = [](const QString& key){ return "(today: 3 " + key + ")"; };
            hooks.team_names = []{ return QStringList{"Medicham", "Azumarill"}; };
            hooks.no_more = []{ return true; };
            hooks.beat = [&]{ beats++; };
            host.set_hooks(hooks);
            check(host.day_count("lost") == "(today: 3 lost)" && host.team_names() == QStringList{"Medicham", "Azumarill"} && host.no_more(),
                  "the program tells the count of the day, the team and the time");
            host.beat();
            check(beats == 1, "and is told that the bot is alive");

            //  The screen classifier: without models every screen is unknown; with them it says one of the nine.
            std::pair<QString, double> guess = host.screen_class(cv::Mat(2208, 1768, CV_8UC3, cv::Scalar(10, 20, 30)));
            check(guess.first == "onbekend" && guess.second == 0.0, "without models the screen is unknown");
            {
                std::lock_guard<std::mutex> lock(told_lock);
                check(!told.isEmpty() && told.last().contains("the screen classifier cannot be used here"), "and that is told once");
            }
            //  Claude GG spins itself (ClaudeGG_PokemonGoBot): what is not ported yet is switched off, and a catch screen is left with the
            //  run-away button.
            {
                PokemonGo::Bot::Switches asked{{"spin", true}, {"catch", false}, {"rocket_fight", true}, {"quests", true}, {"bag_clean", true},
                                               {"heat_pause", true}, {"fast_look", true}, {"gifts_open", true}, {"daily_cycle", true}, {"teams_weekly", true}};
                //  The picture of the fake phone is 48 x 96: not the shape the bot is written for.  Where that is not what is tested the Pi is told to play on
                //  anyway (the file of ~/gamebot_allow_unsupported), as a person with a phone of another shape does.
                const QString allow_file = home_folder + "/gamebot_allow_unsupported";
                {
                    QFile out(allow_file);
                    check(out.open(QIODevice::WriteOnly | QIODevice::Truncate), "the Pi is told to play on a screen of any shape");
                }
                PokemonGo::Bot::PhoneBot bot(host, asked, {{"throw_target", "great"}, {"berries", "razz, nanab"}});
                check(bot.wanted("spin") && bot.setting("fast_look", false) && !bot.wanted("catch") && bot.setting("rocket_fight", false)
                      && bot.setting("quests", false) && bot.setting("bag_clean", false) && bot.setting("heat_pause", false) && bot.wanted("gifts_open")
                      && bot.wanted("daily_cycle") && !bot.wanted("teams_weekly"),
                      "Claude GG plays with what is ported (the gifts, the GO Pass, Team GO Rocket, the clean-up of the bag and the daily run too), the rest is off");
                {
                    //  The heat: the pause is played when the agent can tell the temperatures, and not when it cannot.
                    check(PokemonGo::Bot::playable(asked, true).at("heat_pause") && !PokemonGo::Bot::playable(asked).at("heat_pause")
                          && !PokemonGo::Bot::playable(asked, false).at("heat_pause"), "the pause for the heat is played only with an agent that tells the temperatures");
                    check(PokemonGo::Bot::playable(PokemonGo::Bot::Switches{{"heat_pause", false}}, true).at("heat_pause") == false,
                          "and it stays off when the person switched it off");
                    check(host.reads_heat(), "the fake agent tells the temperatures");
                    const std::pair<std::optional<double>, std::optional<double>> heat = bot.read_heat();
                    check(heat.first.has_value() && std::abs(*heat.first - 31.2) < 1e-9, "the bot reads the battery of the phone (31.2 degrees)");
                }
                {
                    //  The lock screen: the bot asks the agent whether the phone is awake and locked, and takes the lock screen away like by hand.
                    const auto say = [&](const QString& file, const QByteArray& text){
                        QFile out(file);
                        check(out.open(QIODevice::WriteOnly | QIODevice::Truncate) && out.write(text) >= 0, "the fake phone is told what to say");
                    };
                    const auto throws = [&](const std::function<void()>& what){
                        try{
                            what();
                        }catch (const std::runtime_error&){
                            return true;
                        }
                        return false;
                    };
                    check(host.reads_power(), "the fake agent can say whether the phone is awake and locked");
                    check(bot.power_state().contains("mWakefulness=Awake") && !bot.keyguard_showing(), "the bot sees an awake phone without a lock screen");
                    say(power_file, "  mWakefulness=Asleep\n");
                    check(!bot.power_state().contains("mWakefulness=Awake"), "and one that sleeps");
                    say(window_file, "  mShowingLockscreen=true\n");
                    check(bot.keyguard_showing(), "and one with a lock screen");
                    bot.dismiss_keyguard();
                    check(read_lines(adb_log).last() == "shell wm dismiss-keyguard", "which is dismissed with the command of Android");
                    //  The lock screen that stays (a PIN): the bot tries once more with a swipe, says it failed, and goes on.
                    const qsizetype before_unlock = read_lines(adb_log).size();
                    check(!PokemonGo::Lock::unlock(bot), "a lock screen that stays is not taken away");
                    const QStringList after_unlock = read_lines(adb_log).mid(before_unlock);
                    check(after_unlock.size() >= 4 && after_unlock.at(0) == "shell dumpsys window" && after_unlock.at(1) == "shell wm dismiss-keyguard"
                          && after_unlock.at(2) == "shell dumpsys window" && after_unlock.at(3).startsWith("shell input swipe"),
                          "after the dismiss it looks again and swipes (" + after_unlock.join(" | ") + ")");
                    QFile::remove(window_file);
                    check(!PokemonGo::Lock::unlock(bot), "and a phone without a lock screen has nothing to take away");
                    {
                        QFile off(off_file);
                        check(off.open(QIODevice::WriteOnly), "the phone is switched off");
                        off.close();
                        check(throws([&]{ bot.power_state(); }) && throws([&]{ bot.keyguard_showing(); }) && throws([&]{ bot.dismiss_keyguard(); }),
                              "a phone that does not answer is an error, not a yes or a no");
                        QFile::remove(off_file);
                    }
                    QFile::remove(power_file);
                }
                {
                    //  The layout of the game (agent 0.2.6): the bot looks at the shape of the screen, lets Android draw the game in the right shape when it is
                    //  not, and puts that back.  The fake phone says the display it has in the file `wm`: no override at first (1080 x 2340, tall and narrow).
                    const auto write_text = [&](const QString& file, const QByteArray& text){
                        QFile out(file);
                        check(out.open(QIODevice::WriteOnly | QIODevice::Truncate) && out.write(text) >= 0, "a file of the fake phone is written");
                    };
                    const auto told_lines = [&]{
                        std::lock_guard<std::mutex> lock(told_lock);
                        return told;
                    };
                    const auto said = [&](const QStringList& lines, const QString& part){
                        for (const QString& line : lines){
                            if (line.contains(part)){
                                return true;
                            }
                        }
                        return false;
                    };
                    check(host.reads_display() && bot.layout_active(), "the fake agent can change the display, so the layout is checked");
                    QFile::remove(allow_file);
                    write_text(wm_file, "");
                    const QStringList before_told = told_lines();
                    PokemonGo::Bot::PhoneBot looks(host, PokemonGo::Bot::Switches{}, {});
                    check(looks.screen_ok(), "the shape of the screen is taken as right before it is looked at");
                    looks.layout_start();
                    const QStringList start_told = told_lines().mid(before_told.size());
                    check(!looks.screen_ok(), "a screen of 1080 x 2340 has another shape than the canvas");
                    check(said(start_told, "screen check: ") && said(start_told, "using the display 1080x2340"), "the start says which display it uses (" + start_told.join(" | ") + ")");
                    check(said(start_told, "has a different shape than the 1768x2208"), "and why it cannot be played on as it is");
                    check(looks.layout_state() == "new", "the layout is not settled yet");
                    //  The display is changed: written down first, then set, and the shape is right.
                    const QStringList adb_before = read_lines(adb_log);
                    check(looks.layout_adapt("the menu button is not where it should be"), "the bot lets Android draw the game in the right shape");
                    const QStringList adb_after = read_lines(adb_log).mid(adb_before.size());
                    check(adb_after.contains("shell wm size 1080x1348"), "with `wm size 1080x1348` (" + adb_after.join(" | ") + ")");
                    check(looks.screen_ok() && looks.layout_state() == "adapting", "the shape is right now and the bot checks the game on the map");
                    {
                        MobileDisplayFiles files;
                        QString display_error;
                        check(host.agent().display_files(files, &display_error) && files.record.has_value(), "the change is written down on the Pi: " + display_error);
                        const QJsonObject written = QJsonDocument::fromJson(files.record.value_or(QString()).toUtf8()).object();
                        check(written.value("set").toString() == "1080x1348" && written.value("was").toString() == "1080x2340", "with the size it set and the size it was");
                    }
                    check(said(told_lines(), "display size set to 1080x1348"), "and the log says what was done");
                    check(!looks.layout_adapt("again"), "and it does not try again within half an hour");
                    //  The run ends: the size is put back and the record is forgotten.
                    looks.layout_end();
                    {
                        QString wm;
                        QString display_error;
                        MobileDisplayFiles files;
                        check(host.agent().display_wm(wm, &display_error) && !wm.contains("Override"), "the display size is put back when the run ends (" + wm + ")");
                        check(host.agent().display_files(files, &display_error) && !files.record.has_value(), "and the record is forgotten");
                        check(read_lines(adb_log).contains("shell wm size reset"), "with `wm size reset`");
                    }
                    check(said(told_lines(), "display size put back"), "and the log says so");
                    looks.layout_end();                                  //  (nothing to put back the second time)
                    //  A change that an earlier run did not put back is taken over (and put back by this one).
                    {
                        QJsonObject record;
                        record["set"] = "1080x1348";
                        record["time"] = 1.0;
                        record["model"] = "Fake";
                        record["was"] = "1080x2340";
                        QString display_error;
                        check(host.agent().display_record(record, &display_error) && host.agent().display_size("1080x1348", &display_error),
                              "an earlier run changed the display and did not put it back: " + display_error);
                        PokemonGo::Bot::PhoneBot next(host, PokemonGo::Bot::Switches{}, {});
                        const QStringList before_next = told_lines();
                        next.layout_start();
                        const QStringList next_told = told_lines().mid(before_next.size());
                        check(next.screen_ok() && next.layout_state() == "adapting", "a screen that is right in the shape it was left in is checked on the map");
                        check(said(next_told, "set by an earlier run is still active"), "and the log says that the earlier run left it (" + next_told.join(" | ") + ")");
                        next.layout_end();
                        QString wm;
                        check(host.agent().display_wm(wm, &display_error) && !wm.contains("Override"), "and this run puts it back");
                    }
                    //  The run: its start takes over a change that was left, and its end puts the size back, whichever way the run ends (here: at once, as the
                    //  person who stops it does).
                    {
                        QJsonObject record;
                        record["set"] = "1080x1348";
                        record["time"] = 1.0;
                        record["model"] = "Fake";
                        record["was"] = "1080x2340";
                        QString display_error;
                        check(host.agent().display_record(record, &display_error) && host.agent().display_size("1080x1348", &display_error),
                              "a display change is left on the phone: " + display_error);
                        std::mutex run_lock;
                        QStringList run_told;
                        AgentHost stopping("127.0.0.1", port, token, options, [&](const QString& line){
                            std::lock_guard<std::mutex> lock(run_lock);
                            run_told << line;
                        }, []{ return true; });
                        bool interrupted = false;
                        {
                            PokemonGo::Bot::PhoneBot playing(stopping, PokemonGo::Bot::Switches{}, {});
                            try{
                                PokemonGo::Bot::run(playing);
                            }catch (const PokemonGo::Flow::Interrupted&){
                                interrupted = true;
                            }
                        }
                        check(interrupted, "the run ends with the stop of the person");
                        {
                            std::lock_guard<std::mutex> lock(run_lock);
                            check(said(run_told, "screen check: FakePhone; using the display 1080x1348") && said(run_told, "set by an earlier run is still active"),
                                  "the start looks at the screen and takes over what the earlier run left (" + run_told.join(" | ") + ")");
                            check(said(run_told, "display size put back"), "and the end puts it back");
                        }
                        QString wm;
                        MobileDisplayFiles files;
                        check(host.agent().display_wm(wm, &display_error) && !wm.contains("Override") && host.agent().display_files(files, &display_error)
                              && !files.record.has_value(), "the phone is as it was and the record is gone (" + wm + ")");
                    }
                    //  A screen that cannot be played on and may not be changed: the run says so, waits, and does not touch the phone (the normal and the daily run: main() of
                    //  gamebot.py looks before both).
                    for (const bool daily_run : {false, true}){
                        const QString path = daily_run ? "the daily run: " : "the normal run: ";
                        write_text(wm_file, "");
                        write_text(home_folder + "/gamebot_no_display_change", "");
                        std::mutex wait_lock;
                        QStringList wait_told;
                        std::atomic<bool> stop_run{false};
                        AgentHost halting("127.0.0.1", port, token, options, [&](const QString& line){
                            std::lock_guard<std::mutex> lock(wait_lock);
                            wait_told << line;
                        }, [&]{ return stop_run.load(); });
                        const qsizetype adb_start = read_lines(adb_log).size();
                        std::thread timer([&]{
                            std::this_thread::sleep_for(std::chrono::milliseconds(1500));
                            stop_run = true;
                        });
                        bool interrupted = false;
                        {
                            PokemonGo::Bot::PhoneBot waiting(halting, PokemonGo::Bot::Switches{{"daily_cycle", daily_run}}, {});
                            try{
                                PokemonGo::Bot::run(waiting);
                            }catch (const PokemonGo::Flow::Interrupted&){
                                interrupted = true;
                            }
                        }
                        timer.join();
                        check(interrupted, path + "the run ends with the stop of the person");
                        const QStringList touched = read_lines(adb_log).mid(adb_start);
                        {
                            std::lock_guard<std::mutex> lock(wait_lock);
                            check(said(wait_told, "layout: the screen has another shape than the canvas - trying to let Android draw the game in the right shape")
                                  && said(wait_told, "layout: not possible: not changing the display size") && said(wait_told, "not playing: screen 1080x2340"),
                                  path + "a screen of another shape that may not be changed is said, and the bot waits for another (" + wait_told.join(" | ") + ")");
                        }
                        bool touched_the_game = false;
                        for (const QString& line : touched){
                            touched_the_game = touched_the_game || line.startsWith("shell input") || line.startsWith("exec-out screencap") || line.contains("monkey");
                        }
                        check(!touched_the_game, path + "it did not tap or look at the game (" + touched.join(" | ") + ")");
                        QFile::remove(home_folder + "/gamebot_no_display_change");
                    }
                    //  The parts of the bot on their own (Chapter::run, run_chapter() of gamebot.py): the list, the words of the log, a part that is
                    //  stopped, and parts that find the game on another screen than the one they need (no models here: every screen is 'onbekend').
                    {
                        check(PokemonGo::Chapter::keys() == "screen, play, rocket, rocket_fight, catch, throw, bag, quests, gifts",
                              "the parts that Claude GG can run on its own are those of chapters.py that are ported (" + PokemonGo::Chapter::keys() + ")");
                        check(PokemonGo::Chapter::find("bag") != nullptr && PokemonGo::Chapter::find("video") == nullptr && PokemonGo::Chapter::find("") == nullptr
                              && PokemonGo::Chapter::find("battle_one") == nullptr, "the live video and the battles are not among them");
                        std::mutex chapter_lock;
                        QStringList chapter_told;
                        std::atomic<bool> chapter_stop{false};
                        AgentHost chapter_host("127.0.0.1", port, token, options, [&](const QString& line){
                            std::lock_guard<std::mutex> lock(chapter_lock);
                            chapter_told << line;
                        }, [&]{ return chapter_stop.load(); });
                        PokemonGo::Bot::PhoneBot chapter_bot(chapter_host, PokemonGo::Bot::Switches{}, {});
                        const auto chapter_said = [&](const QString& part){
                            std::lock_guard<std::mutex> lock(chapter_lock);
                            return said(chapter_told, part);
                        };
                        const PokemonGo::Chapter::Result missing = PokemonGo::Chapter::run(chapter_bot, "video");
                        check(!missing.ok && chapter_said("TEST video: no such test - there are: screen, play, rocket,"), "a part that is not there is told, with the parts that are");
                        const PokemonGo::Chapter::Result seen = PokemonGo::Chapter::run(chapter_bot, "screen");
                        check(seen.ok && seen.how == "screen onbekend [0.00], 0 things found (g_test.png)"
                              && chapter_said("TEST screen: started - What the bot sees (start screen: Any screen)") && chapter_said("TEST screen: done - screen onbekend [0.00]"),
                              "'what the bot sees' says the screen and what it found, and how it started and ended (" + seen.how + ")");
                        check(QFile::exists(options.folder + "/pictures/g_test.png") && QFile::exists(options.folder + "/pictures/g_test_start.png")
                              && QFile::exists(options.folder + "/pictures/g_test_end.png"), "and keeps the screen of the start, of the end and the marked one");
                        const PokemonGo::Chapter::Result caught = PokemonGo::Chapter::run(chapter_bot, "catch");
                        check(!caught.ok && caught.how == "no encounter on the screen (onbekend)" && chapter_said("TEST catch: failed - no encounter on the screen (onbekend)"),
                              "catching needs an encounter on the screen (" + caught.how + ")");
                        const PokemonGo::Chapter::Result thrown = PokemonGo::Chapter::run(chapter_bot, "throw");
                        check(!thrown.ok && thrown.how == "no ball ready on an encounter screen (onbekend)", "and so does a throw (" + thrown.how + ")");
                        //  A part that is stopped ends with the stop of the person: nothing is played, and it is told.
                        chapter_stop = true;
                        const PokemonGo::Chapter::Result played = PokemonGo::Chapter::run(chapter_bot, "play");
                        check(played.ok && played.how == "0 steps in 3 minutes" && chapter_said("TEST play: started - Normal play for 3 minutes (start screen: The map)")
                              && chapter_said("TEST play: done - 0 steps in 3 minutes"), "normal play that is stopped at once has made no step (" + played.how + ")");
                        check(PokemonGo::Chapter::chapter_steps(chapter_bot, 5.0, false) == 0 && PokemonGo::Chapter::chapter_steps(chapter_bot, 5.0, true) == 0,
                              "and the steps of a part are not made after the stop");
                    }
                    //  A switch file: the Pi is told not to change the display, and to play on anyway.
                    {
                        PokemonGo::Bot::PhoneBot other(host, PokemonGo::Bot::Switches{}, {});
                        other.layout_start();
                        write_text(home_folder + "/gamebot_no_display_change", "");
                        const QStringList before_other = read_lines(adb_log);
                        const QStringList told_other = told_lines();
                        check(!other.layout_adapt("the menu button is not where it should be"), "the display is not changed when the Pi is told not to");
                        check(!read_lines(adb_log).mid(before_other.size()).join(" | ").contains("wm size 1"), "the phone did not hear of a size");
                        check(said(told_lines().mid(told_other.size()), "no_display_change exists") || said(told_lines().mid(told_other.size()), "not changing the display size"),
                              "and the log says why");
                        QFile::remove(home_folder + "/gamebot_no_display_change");
                        write_text(allow_file, "");
                        PokemonGo::Bot::PhoneBot allowed(host, PokemonGo::Bot::Switches{}, {});
                        allowed.layout_start();
                        check(allowed.screen_ok(), "a screen of another shape is played on when the Pi is told to");
                    }
                    QFile::remove(wm_file);
                    write_text(allow_file, "");
                }
                {
                    //  The daily run: the bot is its host (the file of the run, the apps of the phone, what is chosen for the battles, the time of the day).
                    const QString main_app = "com.nianticlabs.pokemongo";
                    const QString other_app = "com.nianticlabs.pokemongo.ares";
                    PokemonGo::Bot::Texts texts{{"daily_time", "09:15"}, {"daily_max_min", "90"}, {"daily_force", "start"}, {"battle_app", other_app},
                                                {"battle_league", "Ultra League"}, {"battle_count", "7"}};
                    PokemonGo::Bot::PhoneBot daily(host, PokemonGo::Bot::Switches{{"daily_cycle", true}, {"battle", true}}, texts);
                    check(daily.daily_state().force == "start" && !daily.daily_state().done && !daily.daily_state().battle_resume, "a daily run that is told it was started again carries on");
                    PokemonGo::Bot::PhoneBot by_button(host, PokemonGo::Bot::Switches{{"daily_cycle", true}}, {});
                    check(by_button.daily_state().force == "button", "and one that is started with the button begins a new run");
                    check(daily.setting_value("daily_time").toString() == "09:15" && daily.setting_value("daily_max_min").toString() == "90"
                          && daily.setting_value("daily_start").isUndefined(), "what the person set is handed to the run as text, what was not set is not there");
                    check(daily.game_packages() == QStringList({main_app, other_app}), "the apps are those that the agent lists, the Play Store one first");
                    check(daily.battle_wanted() && daily.battle_app() == other_app, "the battles are wanted in the app that was chosen");
                    check(!by_button.battle_wanted() && by_button.battle_app() == main_app, "and not when they were not asked for (the first app when none was chosen)");
                    host.mark_battles_done();
                    check(!daily.battle_wanted(), "and not when the Battle screen said that they are done for today");
                    QFile::remove(options.folder + "/battle_done.json");
                    check(!daily.teams_due(main_app), "the weekly teams are never due (they are not ported)");
                    //  The file of the run: in the memory of the program, or in the folder of the bot.
                    QJsonObject written;
                    written["start"] = 5;
                    written["done"] = QJsonArray{main_app};
                    check(!daily.read_daily().has_value(), "there is no file of the run before one is written");
                    daily.write_daily(written);
                    check(daily.read_daily() == std::optional<QJsonObject>(written), "the file of the run is read as it was written");
                    PokemonGo::Bot::PhoneBot kept(host, PokemonGo::Bot::Switches{{"daily_cycle", true}}, {}, options.folder);
                    kept.write_daily(written);
                    QFile run_file(options.folder + "/gamebot_daily.json");
                    check(run_file.open(QIODevice::ReadOnly) && QJsonDocument::fromJson(run_file.readAll()).object() == written, "in gamebot_daily.json of the folder of the bot");
                    run_file.close();
                    check(kept.read_daily() == std::optional<QJsonObject>(written), "and read from there");
                    for (const char* content : {"this is not json", "[1, 2]", "", "{\"start\": "}){
                        QFile bad(options.folder + "/gamebot_daily.json");
                        check(bad.open(QIODevice::WriteOnly | QIODevice::Truncate) && bad.write(content) >= 0, "a file that cannot be used is written");
                        bad.close();
                        check(!kept.read_daily().has_value(), QString("is no file of the run (%1)").arg(content));
                    }
                    QFile::remove(options.folder + "/gamebot_daily.json");
                    //  The game is played from the start: the flags of the last one are reset.
                    bot.map_state().spin = false;
                    bot.map_state().catching = false;
                    bot.map_state().storage_full = true;
                    bot.map_state().bag_is_full = true;
                    bot.map_state().menu_check_last = 5.0;
                    bot.map_state().gift_last = 6.0;
                    bot.map_state().rotation.steps = 7;
                    bot.map_state().cooldown.push_back(PokemonGo::Map::Cool());
                    bot.run_done();
                    check(bot.daily_state().done, "the run is done with the app when the storage and the bag are full");
                    bot.reset_for_game();
                    check(bot.map_state().spin && bot.map_state().catching && !bot.map_state().storage_full && !bot.map_state().bag_is_full
                          && bot.map_state().menu_check_last == 0.0 && bot.map_state().gift_last == 0.0 && bot.map_state().rotation.steps == 0
                          && bot.map_state().cooldown.empty() && !bot.daily_state().done, "a new game starts with spinning and catching on and nothing full");
                    bot.map_state().catching = false;                   //  (back to what this bot was asked for, for the checks below)
                    //  The time of the day, in the local time (hours and minutes that are too big or too small go to the next or the last day).
                    const QDateTime noon(QDate(2026, 11, 22), QTime(12, 0), QTimeZone::systemTimeZone());
                    const double now = (double)noon.toSecsSinceEpoch();
                    const auto local = [](double moment){ return QDateTime::fromSecsSinceEpoch((qint64)moment, QTimeZone::systemTimeZone()); };
                    const auto when = [](int day, int hours, int minutes){ return QDateTime(QDate(2026, 11, day), QTime(hours, minutes), QTimeZone::systemTimeZone()); };
                    check(local(bot.slot_time(now, 8, 30)) == when(22, 8, 30) && local(bot.slot_time(now, 0, 0)) == when(22, 0, 0)
                          && local(bot.slot_time(now, 23, 59)) == when(22, 23, 59), "the start time is on the day of now");
                    check(local(bot.slot_time(now, 25, 70)) == when(23, 2, 10) && local(bot.slot_time(now, 48, 0)) == when(24, 0, 0)
                          && local(bot.slot_time(now, 24, 0)) == when(23, 0, 0), "hours and minutes that are too big go to the next days");
                    check(local(bot.slot_time(now, -1, 0)) == when(21, 23, 0) && local(bot.slot_time(now, 8, -30)) == when(22, 7, 30)
                          && local(bot.slot_time(now, 0, -1)) == when(21, 23, 59) && local(bot.slot_time(now, -24, 0)) == when(21, 0, 0)
                          && local(bot.slot_time(now, 0, -1441)) == when(20, 23, 59), "and those that are too small to the last days");
                    check(bot.local_text(now) == "2026-11-22 12:00" && bot.local_text(bot.slot_time(now, 8, 5)) == "2026-11-22 08:05",
                          "a moment is told as YYYY-MM-DD HH:MM in the local time");
                }
                {
                    //  Team GO Rocket: the bot is the host of its walk and fight, and reads a fight on the screen as the Battle League does.
                    PokemonGo::Rocket::Host& rocket = bot;
                    check(rocket.screen_state(cv::Mat(880, 704, CV_8UC3, cv::Scalar(10, 20, 30))) == "other",
                          "a plain picture is no fight on the screen, for the Team GO Rocket battles as well");
                }
                {
                    //  The quest button is gold: it is time to look (nothing was looked at yet), and when the person switched the quests off it is not.
                    cv::Mat gold(2208, 1768, CV_8UC3, cv::Scalar(255, 255, 255));
                    gold(cv::Rect(1624, 1824, 93, 93)).setTo(cv::Scalar(47, 137, 220));         //  (hue 16, saturation 201, value 220)
                    const cv::Mat white(2208, 1768, CV_8UC3, cv::Scalar(255, 255, 255));
                    check(bot.quests_due(gold) && !bot.quests_due(white), "the quests are due when the quest button is gold");
                    PokemonGo::Bot::PhoneBot without(host, PokemonGo::Bot::Switches{{"quests", false}}, {});
                    check(!without.quests_due(gold), "and not when the person switched them off");
                }
                check(!bot.map_state().catching && bot.map_state().spin && !host.has_models(), "it does not catch when that is off, and there are no models here");
                check(bot.setting_text("throw_target", "realistic") == "great" && bot.setting_text("fast_look", "") == "True"
                      && bot.berry_order() == QStringList{"razz", "nanab"} && bot.ball() == "poke", "the throw, the berries and the ball are as chosen");
                const PokemonGo::Loop::Point real = bot.to_real(884, 1104);
                //  (The screen is the size of the last screenshot of the made-up phone, which need not be 1000 x 2200 any more.)
                const int real_w = host.screen_width();
                const int real_h = host.screen_height();
                check(real_w > 0 && real_h > 0 && real.x == (int)std::nearbyint(884.0 * real_w / PokemonGo::Loop::REF_W)
                      && real.y == (int)std::nearbyint(1104.0 * real_h / PokemonGo::Loop::REF_H),
                      "the throw is sent on the real screen (" + QString::number(real_w) + " x " + QString::number(real_h) + ": "
                      + QString::number(real.x) + ", " + QString::number(real.y) + ")");
                {
                    //  The commands of the throw reach the phone as touch events and swipes (and nothing else is sent).
                    const QStringList throw_start = read_lines(adb_log);
                    const int hold = bot.adb_start({"adb", "shell", "{ input motionevent DOWN 500 1900; input motionevent MOVE 520 1880; } 2>&1"}, true);
                    bot.adb_communicate(hold);
                    bot.adb({"shell", "input", "motionevent", "UP", "520", "1880"});
                    const int aim = bot.adb_start({"adb", "shell", "input", "swipe", "500", "1900", "500", "1900", "1300"}, false);
                    bot.adb_wait(aim);
                    bool refused = false;
                    try{
                        bot.adb({"shell", "reboot"});
                    }catch (const std::runtime_error&){
                        refused = true;
                    }
                    const QStringList throw_got = read_lines(adb_log).mid(throw_start.size());
                    const QStringList throw_want{
                        "shell { input motionevent DOWN 500 1900; input motionevent MOVE 520 1880; } 2>&1",
                        "shell { input motionevent UP 520 1880; } 2>&1",
                        "shell input swipe 500 1900 500 1900 1300",
                    };
                    check(throw_got == throw_want && refused, "the commands of the throw reach the phone through the agent, any other is refused ("
                          + QString::number(throw_got.size()) + " commands)");
                    if (throw_got != throw_want){
                        for (const QString& line : throw_got){
                            report << "         it was asked: " + line;
                        }
                    }
                }
                {
                    //  The shell lines of the bag reach the phone as the agent does them: the game is closed (/v1/app) and a key is a key
                    //  (/v1/key); `pidof` cannot be answered, so the bot stops; anything else is refused.
                    const QStringList bag_start = read_lines(adb_log);
                    bot.shell({"shell", "am", "force-stop", host.package()});
                    bot.shell({"shell", "input", "keyevent", "KEYCODE_APP_SWITCH"});
                    bot.shell({"adb", "shell", "input", "keyevent", "KEYCODE_HOME"});
                    bool other_app = false;
                    bool other_line = false;
                    bool stopped = false;
                    try{
                        bot.shell({"shell", "am", "force-stop", "com.android.settings"});
                    }catch (const std::runtime_error&){
                        other_app = true;
                    }
                    try{
                        bot.shell({"shell", "reboot"});
                    }catch (const std::runtime_error&){
                        other_line = true;
                    }
                    try{
                        bot.shell({"shell", "pidof", host.package()});
                    }catch (const PokemonGo::Flow::Interrupted&){
                        stopped = true;
                    }
                    const QStringList bag_got = read_lines(adb_log).mid(bag_start.size());
                    const QStringList bag_want{"shell am force-stop " + host.package(), "shell input keyevent 187", "shell input keyevent 3"};
                    check(bag_got == bag_want && other_app && other_line && stopped,
                          "the shell lines of the bag reach the phone through the agent, pidof stops the bot, any other is refused ("
                          + QString::number(bag_got.size()) + " commands)");
                    //  A touch that lasts and several swipes in one command (the gifts and the bag).
                    const QStringList touch_start = read_lines(adb_log);
                    bot.tap_press(100, 200, 200);
                    bot.swipes({PokemonGo::Loop::Stroke{1, 2, 3, 4, 100}, PokemonGo::Loop::Stroke{5, 6, 7, 8, 70}});
                    const QStringList touch_got = read_lines(adb_log).mid(touch_start.size());
                    check(touch_got.size() == 2 && touch_got[0].startsWith("shell input swipe ") && touch_got[0].endsWith(" 200")
                          && touch_got[1].count("input swipe") == 2, "a press that lasts is one touch and swipes go in one command");
                    //  What the person chose to keep, the day, and the memory of the gifts (a file in the folder of the bot, in the program without one).
                    check(bot.bag_keep_saved().isNull() && bot.today() == PokemonGo::Phone::today_text(), "nothing is chosen to keep unless the person chose, and the day is the day");
                    PokemonGo::Bot::PhoneBot chosen(host, asked, {{"bag_keep", "{\"Potion\": 5}"}});
                    PokemonGo::Bot::PhoneBot garbled(host, asked, {{"bag_keep", "[1, 2"}});
                    check(chosen.bag_keep_saved().isObject() && chosen.bag_keep_saved().toObject().value("Potion").toInt() == 5 && garbled.bag_keep_saved().isNull(),
                          "what the person chose to keep is a JSON object, anything else is nothing chosen");
                    check(!bot.gift_state_read("gifts_state.json").has_value(), "there is no memory of the gifts before one is written");
                    bot.gift_state_write("gifts_state.json", "{\"day\": \"2026-11-22\"}");
                    const std::optional<QByteArray> again = bot.gift_state_read("gifts_state.json");
                    check(again.has_value() && *again == QByteArray("{\"day\": \"2026-11-22\"}") && !QFile::exists(options.folder + "/gifts_state.json"),
                          "without a folder the memory of the gifts is kept by the program");
                    PokemonGo::Bot::PhoneBot kept(host, asked, {}, options.folder);
                    check(!kept.gift_state_read("gifts_state.json").has_value(), "a folder has its own memory");
                    kept.gift_state_write("gifts_state.json", "{\"day\": \"2026-11-23\"}");
                    const std::optional<QByteArray> in_folder = kept.gift_state_read("gifts_state.json");
                    check(in_folder.has_value() && *in_folder == QByteArray("{\"day\": \"2026-11-23\"}") && QFile::exists(options.folder + "/gifts_state.json"),
                          "and the memory of the gifts is a file there");
                    QFile::remove(options.folder + "/gifts_state.json");
                }
                const qsizetype before_run = read_lines(adb_log).size();
                const double wait = bot.do_encounter(cv::Mat(2208, 1768, CV_8UC3, cv::Scalar(10, 20, 30)));
                check(wait == 3 && read_lines(adb_log).size() == before_run + 1, "a catch screen is left with one tap (run away)");
                check(bot.count("stops") == "(this run: 1 stops, 0 caught, 0 fled)", "the stops of the run are counted");
            }
            const QString models_folder = qEnvironmentVariable("CLAUDEGG_MODELS");
            if (!models_folder.isEmpty()){
                Options with_models = options;
                with_models.models = models_folder;
                AgentHost classified("127.0.0.1", port, token, with_models, nullptr);
                guess = classified.screen_class(cv::Mat(2208, 1768, CV_8UC3, cv::Scalar(10, 20, 30)));
                check(guess.first != "onbekend" && guess.second > 0.0 && guess.second <= 1.0, "with the models the screen classifier says which screen it is (" + guess.first + ")");
            }
        }
        {
            PokemonGo::Loop::Stream* stream = host.stream();
            check(stream != nullptr, "the host has the live video");
            if (stream != nullptr){
                long long serial = 0;
                double when = 0;
                cv::Mat small;
                const double asked = now_seconds();
                const bool came = stream->wait_new(0, 10.0, 0.0, serial, when, small);
                check(came, "a picture of the live video comes");
                check(came && small.cols == 704 && small.rows == 880 && serial >= 1, "on the size of the video of gamebot.py");
                check(came && when >= asked && when <= now_seconds(), "stamped with the moment it came in");
                const cv::Vec3b pixel = small.empty() ? cv::Vec3b() : small.at<cv::Vec3b>(400, 300);
                check(std::abs(pixel[2] - 200) < 14 && std::abs(pixel[1] - 30) < 14 && std::abs(pixel[0] - 30) < 14, "with the colours of the phone");
                check(stream->healthy() && !stream->describe().isEmpty(), "the video is healthy");
                const double mark = now_seconds();
                long long next = 0;
                double next_when = 0;
                cv::Mat next_small;
                const bool newer = stream->wait_new(serial, 10.0, mark, next, next_when, next_small);
                check(newer && next > serial && next_when >= mark, "a picture that is newer than one, and taken after the moment that is asked for, comes");
                check(!stream->wait_new(serial + 1000000, 0.3, 0.0, next, next_when, next_small), "none comes out of the future");
                stream->close();
                check(!stream->healthy() && !stream->wait_new(0, 0.5, 0.0, next, next_when, next_small), "a video that is closed is none");
                PokemonGo::Loop::Stream* again = host.stream();
                long long third = 0;
                double third_when = 0;
                cv::Mat third_small;
                check(again != nullptr && again->wait_new(0, 10.0, 0.0, third, third_when, third_small), "the next fight has a video of its own");
                again->close();
            }
        }
        {
            PokemonGo::Fight::Known seen = {{"Lanturn", {{"Surf", 2}}}};
            host.save_seen(seen);
            check(host.load_seen() == seen && QFile::exists(options.folder + "/battle_seen.json"), "what is seen of the foes is kept in the folder of the bot");
            cv::Mat picture(10, 10, CV_8UC3, cv::Scalar(1, 2, 3));
            host.save_picture("g_battle_test.png", picture);
            check(QFile::exists(options.folder + "/pictures/g_battle_test.png"), "a picture to look at afterwards is kept");
        }
        {
            //  the team: the preset where the folder has no file, the team of the file where it has one, an error where it has a file that cannot be used
            QFile::remove(options.folder + "/battle_team.json");
            check(host.load_team().size() == 3, "the team is the preset where the folder of the bot has no file");
            QFile team(options.folder + "/battle_team.json");
            check(team.open(QIODevice::WriteOnly) && team.write("[{\"species\": \"lanturn\", \"cp\": 1494, \"hp\": 186}]") > 0, "a team file is written");
            team.close();
            const std::vector<PokemonGo::Battle::Mon> mine = host.load_team();
            check(mine.size() == 1 && mine[0].species == "lanturn", "the team is the one of battle_team.json in the folder of the bot");
            check(team.open(QIODevice::WriteOnly) && team.write("[{\"species\": \"missingno\"}]") > 0, "another team file is written");
            team.close();
            bool refused = false;
            try{
                host.load_team();
            }catch (const std::runtime_error&){
                refused = true;
            }
            check(refused, "a team with a Pokémon that is not in the data is refused");
            QFile::remove(options.folder + "/battle_team.json");
        }
    }

    //  The Pokémon GO bot on the Pi (with a service that is not one).
    {
        MobileBotState state;
        error.clear();
        check(phone.bot_state(state, 40, &error), "the bot is asked for: " + error);
        check(!state.installed && !state.running && state.log.isEmpty(), "it is not installed on this Pi");
        MobileBotStart start;
        start.options = {{"spin", true}, {"catch", false}};
        error.clear();
        check(!phone.bot_start(start, &error) && error.contains("not installed"), "a bot that is not installed is not started (" + error + ")");

        {
            QFile program(bot_home + "/gamebot.py");
            check(program.open(QIODevice::WriteOnly) && program.write("# the bot\n") > 0, "the bot is installed (a file in its folder)");
        }
        {
            QFile log(bot_home + "/spin.log");
            check(log.open(QIODevice::WriteOnly) && log.write("2026-11-26 10:00:01  one\n2026-11-26 10:00:02  two\n2026-11-26 10:00:03  three\n") > 0, "with a log");
        }
        MobileBotStart bad;
        bad.options = {{"tea_party", true}};
        error.clear();
        check(!phone.bot_start(bad, &error) && error.contains("not an option"), "an option that the bot does not have is refused (" + error + ")");
        MobileBotStart bad_league;
        bad_league.battle_league = "Great League; reboot";
        error.clear();
        check(!phone.bot_start(bad_league, &error) && error.contains("battle_league"), "a league that could be a command is refused (" + error + ")");

        start.throw_target = "great";
        start.daily_time = "06:30";
        start.daily_max_min = 90;
        start.daily_now = true;
        error.clear();
        check(phone.bot_start(start, &error), "the bot is started: " + error);
        error.clear();
        check(phone.bot_state(state, 2, &error) && state.installed && state.running, "and it runs now: " + error);
        check(state.log.size() == 2 && state.log.back().endsWith("three"), "with the end of its log");
        QJsonObject control;
        {
            QFile file(bot_home + "/gamebot_control.json");
            if (file.open(QIODevice::ReadOnly)){
                control = QJsonDocument::fromJson(file.readAll()).object();
            }
        }
        check(control.value("spin").toBool() && !control.value("catch").toBool(true), "its switches are as asked");
        check(control.value("throw_target").toString() == "great" && control.value("daily_time").toString() == "06:30" && control.value("daily_max_min").toInt() == 90,
            "so are the throw, the time of the daily run and its limit");
        check(QFile::exists(bot_home + "/gamebot_force.json"), "the daily run begins at once when that is asked for");
        error.clear();
        check(phone.bot_stop(&error), "the bot is stopped: " + error);
        check(phone.bot_state(state, 1, &error) && !state.running, "and it does not run");
        const QStringList calls = read_lines(scratch.path() + "/service-calls");
        QStringList service;
        for (const QString& line : calls){
            if (!line.startsWith("is-active")){
                service << line;
            }
        }
        check(service == QStringList({"start spin-stop", "stop spin-stop"}), "the service was started and stopped, and nothing else (" + service.join("; ") + ")");
        const MobileAgent stranger("127.0.0.1", port, "not-the-token", 20000);
        error.clear();
        check(!stranger.bot_start(start, &error) && !stranger.bot_stop(&error) && !stranger.bot_state(state, 1, &error), "a wrong token does not start or stop the bot");
        check(read_lines(scratch.path() + "/service-calls").size() == calls.size(), "and the service was not asked");
    }

    //  The programs of the game "Pokémon GO": presets of that bot. What each asks for must be
    //  what the agent knows (it refuses a switch that it does not know), and be what it is called.
    {
        check(PokemonGo::pokemon_go_program_count() == 11, "the game has its eleven programs");
        auto asks = [&](const std::string& program, const std::string& key){
            for (const std::pair<std::string, bool>& option : PokemonGo::pokemon_go_switches(program)){
                if (option.first == key){
                    return option.second;
                }
            }
            return false;
        };
        const std::string spin = "Spin Pok\xc3\xa9Stops";
        const std::string catching = "Catch Pok\xc3\xa9mon";
        const std::string daily = "Daily run";
        const std::string rocket = "Team GO Rocket battles";
        const std::string quests = "Claim GO Pass rewards";
        const std::string battles = "GO Battle League";
        const std::string teams = "Your Pok\xc3\xa9mon and teams";
        const std::string part = "One part of the bot";
        const std::string autoplay = "Auto play";
        check(asks(autoplay, "spin") && asks(autoplay, "catch") && asks(autoplay, "gifts_open") && asks(autoplay, "gifts_send")
              && !asks(autoplay, "daily_cycle") && !asks(autoplay, "rocket_fight") && !asks(autoplay, "quests") && !asks(autoplay, "battle"),
              "Auto play spins, catches and does the gifts until more is chosen");
        check(asks(spin, "spin") && !asks(spin, "catch") && !asks(spin, "daily_cycle") && !asks(spin, "rocket_fight"), "Spin PokeStops only spins");
        check(!asks(catching, "spin") && asks(catching, "catch") && !asks(catching, "gifts_open"), "Catch Pokemon only catches");
        check(asks(daily, "daily_cycle") && asks(daily, "spin") && asks(daily, "catch") && asks(daily, "gifts_open") && asks(daily, "gifts_send"), "the daily run is the whole day");
        check(asks(rocket, "rocket_fight") && asks(rocket, "spin") && !asks(rocket, "quests") && !asks(rocket, "catch"), "the Team GO Rocket battles are only those");
        check(asks(quests, "quests") && asks(quests, "catch") && !asks(quests, "rocket_fight"), "the GO Pass rewards are claimed while it plays");
        check(!asks(daily, "battle") && !asks(daily, "teams_weekly") && asks(daily, "battle_give_up"), "the daily run fights no battles and keeps no teams unless it is told to");
        check(!asks(spin, "battle") && !asks(quests, "teams_weekly"), "the other programs of the day fight none either");
        check(asks(battles, "battle") && asks(battles, "battle_give_up") && !asks(battles, "spin") && !asks(battles, "catch"), "GO Battle League only fights");
        check(!asks(teams, "spin") && !asks(teams, "battle") && PokemonGo::pokemon_go_switches(teams).size() == 2, "Your Pokemon and teams changes next to nothing of the bot");
        check(!asks(part, "spin") && !asks(part, "daily_cycle"), "One part of the bot leaves what it does to the part");
        check(PokemonGo::pokemon_go_switches("Not a program").empty(), "a program that is not there asks nothing");
        for (const std::string& program : {autoplay, spin, catching, std::string("Spin Pok\xc3\xa9Stops and catch Pok\xc3\xa9mon"), std::string("Gifts"), daily, rocket, quests, battles, teams, part}){
            MobileBotStart ask;
            const std::vector<std::pair<std::string, bool>> switches = PokemonGo::pokemon_go_switches(program);
            const bool service = program != battles && program != teams && program != part;
            check(service ? switches.size() == 19 : !switches.empty(), "each program says what it asks of the bot's switches (" + QString::fromStdString(program) + ")");
            for (const std::pair<std::string, bool>& option : switches){
                ask.options.emplace_back(QString::fromStdString(option.first), option.second);
            }
            error.clear();
            check(phone.bot_start(ask, &error), "the bot takes what the program asks (" + QString::fromStdString(program) + "): " + error);
        }
        QJsonObject control;
        {
            QFile file(bot_home + "/gamebot_control.json");
            if (file.open(QIODevice::ReadOnly)){
                control = QJsonDocument::fromJson(file.readAll()).object();
            }
        }
        check(control.value("quests").toBool() && control.value("catch").toBool() && !control.value("rocket_fight").toBool(true), "and it keeps what the last one asked");
        error.clear();
        check(phone.bot_stop(&error), "the bot is stopped again: " + error);
    }

    //  GO Battle League, and the parts of the bot that run on their own (its tests).
    {
        MobileBotState state;
        error.clear();
        std::vector<MobileBotChapter> chapters;
        check(phone.bot_tests(chapters, &error) && chapters.empty(), "a bot without its list of parts has no parts (" + error + ")");
        MobileBotStart ask;
        ask.options = {{"battle", true}};
        error.clear();
        check(!phone.bot_test("screen", ask, &error) && error.contains("chapters.py"), "and no part can be run (" + error + ")");

        //  The bot as it is installed: its own list of parts, and a gamebot.py that says how a part ended.
        {
            QFile program(bot_home + "/gamebot.py");
            check(program.open(QIODevice::WriteOnly | QIODevice::Truncate) && program.write(FAKE_GAMEBOT) > 0, "the bot that says how a test ended is installed");
        }
        const QString chapters_file = QDir(agent_folder).filePath("../chapters.py");
        check(QFile::exists(chapters_file) && QFile::copy(chapters_file, bot_home + "/chapters.py"), "with the chapters.py of the bot (" + chapters_file + ")");
        error.clear();
        check(phone.bot_tests(chapters, &error) && chapters.size() > 10, "the bot lists its parts: " + error);
        QStringList keys;
        for (const MobileBotChapter& chapter : chapters){
            keys << chapter.key;
            if (chapter.title.isEmpty() || chapter.group.isEmpty() || chapter.what.isEmpty()){
                check(false, "every part has a group, a title and what it does (" + chapter.key + ")");
            }
        }
        //  The programs of Claude GG name the parts by their keys: one that the bot does not have would fail on the phone.
        const std::vector<std::string> known = PokemonGo::pokemon_go_part_keys();
        bool all_known = true;
        for (const std::string& key : known){
            if (!keys.contains(QString::fromStdString(key))){
                all_known = false;
                check(false, "the bot has the part that the programs name: " + QString::fromStdString(key));
            }
        }
        check(all_known && (size_t)keys.size() == known.size(), "the parts of the programs and those of the bot are the same (" + QString::number(keys.size()) + " and " + QString::number((qulonglong)known.size()) + ")");

        //  A set of battles: its settings are written, and the test runs to its end.
        MobileBotStart battles;
        battles.options = {{"battle", true}, {"battle_give_up", false}};
        battles.battle_league = "Ultra League";
        battles.battle_app_given = true;
        battles.battle_count = 7;
        error.clear();
        check(phone.bot_test("battle_set", battles, &error), "a set of battles is started: " + error);
        auto wait_for_end = [&](bool running){
            QElapsedTimer timer;
            timer.start();
            while (timer.elapsed() < 20000){
                if (phone.bot_state(state, 5, &error) && state.test.running == running){
                    return true;
                }
                QThread::msleep(100);
            }
            return false;
        };
        check(wait_for_end(false) && state.test.finished, "it ends");
        check(state.test.key == "battle_set" && state.test.ok && state.test.result == "all fine" && !state.test.title.isEmpty(), "and says how (" + state.test.result + ")");
        QJsonObject control;
        {
            QFile file(bot_home + "/gamebot_control.json");
            if (file.open(QIODevice::ReadOnly)){
                control = QJsonDocument::fromJson(file.readAll()).object();
            }
        }
        check(control.value("battle").toBool() && !control.value("battle_give_up").toBool(true), "the battle switches are as asked");
        check(control.value("battle_league").toString() == "Ultra League" && control.value("battle_count").toInt() == 7 && control.value("battle_app").toString().isEmpty(),
            "so are the league, the number of battles and the app");
        check(state.battle_league == "Ultra League" && state.battle_count == 7 && state.battle_app.isEmpty(), "and the state says so");
        error.clear();
        check(!phone.bot_test("no_such_test", ask, &error) && error.contains("not a test"), "a part the bot does not have is refused (" + error + ")");
        error.clear();
        check(!phone.bot_test("screen; reboot", ask, &error) && !error.isEmpty(), "a name that could be a command is refused (" + error + ")");

        //  The matches of today are in the log of the bot.
        {
            const QString today = QDate::currentDate().toString("yyyy-MM-dd");
            QFile log(bot_home + "/spin.log");
            check(log.open(QIODevice::WriteOnly | QIODevice::Append), "the log of the bot is added to");
            log.write((today + " 09:00:00  battle: 2 battle(s) in 'Great League' with A, B, C\n").toUtf8());
            log.write((today + " 09:05:10  battle: battle 1 done: win\n").toUtf8());
            log.write((today + " 09:11:40  battle: battle 2 done: loss (given up)\n").toUtf8());
        }
        error.clear();
        const bool asked = phone.bot_state(state, 5, &error);     //  (before the text: the order of the arguments is not fixed)
        check(asked && state.battles_won == 1 && state.battles_lost == 1, "the battles of today are counted: " + QString::number(state.battles_won) + " won, " + QString::number(state.battles_lost) + " lost");

        //  A part that does not end by itself: it can be stopped, and the bot is not started over it.
        {
            QFile hang(bot_home + "/hang");
            check(hang.open(QIODevice::WriteOnly), "a part that waits is set up");
        }
        error.clear();
        check(phone.bot_test("scan", ask, &error), "a long part is started: " + error);
        check(wait_for_end(true), "it runs");
        error.clear();
        check(!phone.bot_test("screen", ask, &error) && error.contains("running already"), "a second part is not started next to it (" + error + ")");
        error.clear();
        check(!phone.bot_start(ask, &error) && error.contains("stop it first"), "nor is the bot (" + error + ")");
        error.clear();
        check(phone.bot_test_stop(&error), "the part is stopped: " + error);
        check(wait_for_end(false) && state.test.finished && state.test.key == "scan", "and it is over");
        QFile::remove(bot_home + "/hang");
        error.clear();
        check(phone.bot_start(ask, &error), "after it the bot can be started: " + error);
        error.clear();
        check(phone.bot_stop(&error), "and stopped: " + error);

        const MobileAgent stranger("127.0.0.1", port, "not-the-token", 20000);
        error.clear();
        check(!stranger.bot_test("screen", ask, &error) && !stranger.bot_test_stop(&error) && !stranger.bot_tests(chapters, &error), "a wrong token runs no part of the bot");
    }

    //  The live picture.
    {
        MobileVideo video("127.0.0.1", port, token, 10, 300);
        video.start();
        QImage first;
        quint64 serial = 0;
        check(video.wait_newer(first, 0, 10000, &serial), "the live picture gives a first picture: " + video.error());
        check(first.size() == QSize(48, 96), "it is the picture of the phone (" + QString::number(first.width()) + "x" + QString::number(first.height()) + ")");
        const QColor color = first.isNull() ? QColor() : first.pixelColor(24, 48);
        check(std::abs(color.red() - 200) < 40 && std::abs(color.green() - 30) < 40 && std::abs(color.blue() - 30) < 40,
            "with its colors (" + color.name() + ")");
        QImage next;
        quint64 later = serial;
        check(video.wait_newer(next, serial, 5000, &later) && later > serial, "and more pictures come");
        QImage newest;
        quint64 count = 0;
        check(video.latest(newest, &count) && count >= later, "the newest picture can be asked for at any time");
        check(video.error().isEmpty(), "with nothing wrong");
        QElapsedTimer stopping;
        stopping.start();
        video.stop();
        check(stopping.elapsed() < 3000, "it stops at once");

        //  A wrong token: no pictures, and it says why.
        MobileVideo stranger("127.0.0.1", port, "not-the-token", 10, 300);
        stranger.start();
        QImage none;
        check(!stranger.wait_newer(none, 0, 1500), "a wrong token gets no picture");
        check(stranger.error().contains("token"), "and is told why (" + stranger.error() + ")");
        stranger.stop();
    }

    //  A phone that is switched off, and that comes back.
    {
        QFile off(off_file);
        check(off.open(QIODevice::WriteOnly), "the phone is switched off for the test");
        off.close();
        QImage picture;
        error.clear();
        check(!phone.screen(picture, &error) && error.contains("device offline"), "a phone that is off is told as it is (" + error + ")");
        QFile::remove(off_file);
        error.clear();
        check(phone.screen(picture, &error), "and the screen is there again when it is on: " + error);
    }

    //  The agent goes: it is told, and not waited for.
    agent.kill();
    agent.waitForFinished(5000);
    {
        QElapsedTimer waited;
        waited.start();
        const MobileAgent gone("127.0.0.1", port, token, 3000);
        error.clear();
        check(!gone.ping(&error) && !error.isEmpty(), "an agent that is gone is told (" + error + ")");
        check(waited.elapsed() < 8000, "without a long wait");
    }

    return finish();
}


}
}
