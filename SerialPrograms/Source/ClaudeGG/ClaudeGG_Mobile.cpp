/*  Claude GG Mobile (an Android phone, through a Raspberry Pi)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

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
#include "ClaudeGG_Mobile.h"

namespace PokemonAutomation{
namespace ClaudeGG{


const char* const MOBILE_TEST_OPTION = "--mobile-test";


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

    const int split = data.indexOf("\r\n\r\n");
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

    QProcess agent;
    QProcessEnvironment environment = QProcessEnvironment::systemEnvironment();
    environment.insert("FAKE_ADB_LOG", adb_log);
    environment.insert("FAKE_ADB_FAIL_FILE", off_file);
    agent.setProcessEnvironment(environment);
    agent.setProcessChannelMode(QProcess::MergedChannels);
    agent.start(python, QStringList{
        script, "--host", "127.0.0.1", "--port", "0",
        "--adb", python, "--adb-arg", fake, "--token-file", token_file,
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
            const int at = heard.indexOf("listening on port ");
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
        const int count = read_lines(adb_log).size();
        error.clear();
        check(!phone.tap(-1, 5, 120, &error) && !error.isEmpty(), "a tap outside the screen is refused (" + error + ")");
        error.clear();
        check(!phone.key("REBOOT", &error) && !error.isEmpty(), "a key that does not exist is refused (" + error + ")");
        error.clear();
        check(!phone.text("x; reboot", &error) && !error.isEmpty(), "a text that could be a command is refused (" + error + ")");
        check(read_lines(adb_log).size() == count, "none of them reached the phone");
    }

    //  A phone that is switched off, and that comes back.
    {
        QFile off(off_file);
        off.open(QIODevice::WriteOnly);
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
