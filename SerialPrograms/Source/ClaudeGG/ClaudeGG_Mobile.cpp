/*  Claude GG Mobile (an Android phone, through a Raspberry Pi)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <chrono>
#include <QCoreApplication>
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
#include "Common/Cpp/Color.h"
#include "Common/Cpp/Logging/AbstractLogger.h"
#include "Common/Cpp/Logging/GlobalLogger.h"
#include "CommonFramework/Logging/Logger.h"
#include "CommonFramework/GlobalAutoPaths.h"
#include "Assistant/Assistant_Settings.h"
#include "ClaudeGG_Mobile.h"

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

bool MobileVideo::latest(QImage& picture, quint64* serial) const{
    std::lock_guard<std::mutex> lock(m_lock);
    if (serial != nullptr){
        *serial = m_serial;
    }
    if (m_serial == 0){
        return false;
    }
    picture = m_picture;
    return true;
}

bool MobileVideo::wait_newer(QImage& picture, quint64 after, int msec, quint64* serial) const{
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
        message = "Type the address of the Raspberry Pi first.";
        return false;
    }
    if (port < 1 || port > 65535){
        message = "The port is a number from 1 to 65535.";
        return false;
    }
    //  Short: the page of the setup waits for this.
    const MobileAgent agent(host.trimmed(), port, token.trimmed(), 4000);
    QString error;
    if (!agent.ping(&error)){
        message = "No answer: " + error + ".";
        return false;
    }
    if (token.trimmed().isEmpty()){
        message = "The agent is there. Type its token (the installer printed it) to go on.";
        return false;
    }
    MobileInfo info;
    if (!agent.info(info, &error)){
        message = "The agent is there, but " + error + ".";
        return false;
    }
    QString phone = info.model.isEmpty() ? QString("a phone") : info.model;
    if (!info.android.isEmpty()){
        phone += ", Android " + info.android;
    }
    if (info.width > 0 && info.height > 0){
        phone += QString(", %1 x %2").arg(info.width).arg(info.height);
    }
    message = "Connected to " + phone + ".";
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
    QJsonObject body;
    body["x"] = x;
    body["y"] = y;
    body["ms"] = ms;
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


//  ---------------------------------------------------------------------
//  The test
//  ---------------------------------------------------------------------

namespace{

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
    auto check = [&](bool fine, const QString& what){
        report << (fine ? "ok:     " : "FAILED: ") + what;
        if (!fine){
            wrong++;
            logger.log("Mobile test: FAILED: " + what.toStdString(), COLOR_RED);
        }
    };
    auto finish = [&]() -> int{
        for (const QString& line : report){
            logger.log("Mobile test: " + line.toStdString());
        }
        if (!agent_folder.isEmpty()){
            QFile file(agent_folder + "/mobile-test.txt");
            if (file.open(QIODevice::WriteOnly | QIODevice::Truncate)){
                QTextStream(&file) << report.join("\n") << "\n";
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
    agent.setProcessEnvironment(environment);
    agent.setProcessChannelMode(QProcess::MergedChannels);
    agent.start(python, QStringList{
        script, "--host", "127.0.0.1", "--port", "0",
        "--adb", python, "--adb-arg", fake, "--token-file", token_file,
        "--video-cmd", python, "--video-arg", fake_video, "--video-arg", video_file,
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
    const QStringList pressed = read_lines(adb_log).mid(before.size());
    const QStringList wanted{
        "shell input swipe 300 400 300 400 120",
        "shell input swipe 5 6 5 6 80",
        "shell input swipe 1 2 3 4 300",
        "shell input swipe 1 2 3 4 100; input swipe 5 6 7 8 200",
        "shell input keyevent 4",
        "shell input text a%sb",
        "shell input keyevent 224",
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
