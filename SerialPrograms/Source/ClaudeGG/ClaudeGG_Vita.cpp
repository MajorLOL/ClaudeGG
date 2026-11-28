/*  Claude GG PlayStation Vita (vita-agent-bridge over Wi-Fi)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <string>
#include <vector>
#include <QByteArray>
#include <QDateTime>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QImage>
#include <QJsonDocument>
#include <QJsonObject>
#include <QString>
#include <QTcpSocket>
#include "Common/Cpp/CancellableScope.h"
#include "Common/Cpp/Color.h"
#include "Common/Cpp/Exceptions.h"
#include "Common/Cpp/Options/BooleanCheckBoxOption.h"
#include "Common/Cpp/Options/EnumDropdownOption.h"
#include "Common/Cpp/Options/FloatingPointOption.h"
#include "Common/Cpp/Options/SimpleIntegerOption.h"
#include "Common/Cpp/Options/StaticTextOption.h"
#include "Common/Cpp/Options/TextEditOption.h"
#include "CommonFramework/Exceptions/OperationFailedException.h"
#include "CommonFramework/GlobalAutoPaths.h"
#include "CommonFramework/GlobalSettingsPanel.h"
#include "CommonFramework/Globals.h"
#include "CommonFramework/ImageTypes/ImageRGB32.h"
#include "CommonFramework/ImageTypes/ImageRGB32_Qt.h"
#include "CommonFramework/Language.h"
#include "CommonTools/OCR/OCR_Routines.h"
#include "CommonTools/Options/LanguageOCROption.h"
#include "ComputerPrograms/ComputerProgram.h"
#include "ClaudePlays/ClaudePlays_AnyGame.h"
#include "ClaudePlays/ClaudePlays_Consoles.h"
#include "ClaudePlays/ClaudePlays_Measure.h"
#include "ClaudePlays/ClaudePlays_Engine.h"
#include "ClaudePlays/ClaudePlays_External.h"
#include "ClaudePlays/ClaudePlays_GameCard.h"
#include "ClaudeGG_Vita.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace Vita{

using namespace ClaudePlays;


const char* const VITA_LIST_NAME = "PlayStation Vita";


uint32_t button_bit(const std::string& name){
    //  The bits of SceCtrl, as cli/vita.py of vita-agent-bridge has them. The
    //  shoulder buttons of a Vita report as L1 and R1.
    static const struct{
        const char* name;
        uint32_t bit;
    } BUTTONS[] = {
        {"SELECT", 0x1}, {"START", 0x8},
        {"UP", 0x10}, {"RIGHT", 0x20}, {"DOWN", 0x40}, {"LEFT", 0x80},
        {"L", 0x400}, {"R", 0x800},
        {"TRIANGLE", 0x1000}, {"CIRCLE", 0x2000}, {"CROSS", 0x4000}, {"SQUARE", 0x8000},
        {"HOME", 0x10000},
    };
    for (const auto& button : BUTTONS){
        if (name == button.name){
            return button.bit;
        }
    }
    return 0;
}

int stick_value(double value, bool is_y){
    const double v = std::clamp(is_y ? -value : value, -1.0, 1.0);
    return std::clamp((int)std::lround(127.5 + v * 127.5), 0, 255);
}

std::string token_of(const std::string& typed){
    std::string token;
    for (char ch : typed){
        if (ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n'){
            continue;
        }
        const bool hex = (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f') || (ch >= 'A' && ch <= 'F');
        if (!hex){
            return std::string();
        }
        token += ch;
    }
    return token.size() == 64 ? token : std::string();
}

void touch_point(int x, int y, int width, int height, int& screen_x, int& screen_y){
    const double fx = width > 1 ? (double)x / (double)(width - 1) : 0.5;
    const double fy = height > 1 ? (double)y / (double)(height - 1) : 0.5;
    screen_x = std::clamp((int)std::lround(fx * (SCREEN_WIDTH - 1)), 0, SCREEN_WIDTH - 1);
    screen_y = std::clamp((int)std::lround(fy * (SCREEN_HEIGHT - 1)), 0, SCREEN_HEIGHT - 1);
}


namespace{

uint32_t read_u32(const QByteArray& data, qsizetype at){
    const unsigned char* p = reinterpret_cast<const unsigned char*>(data.constData()) + at;
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

//  One plane of "shot" from "at": its picture (null when the plane is not
//  there), and where the next plane starts. False: the data is cut short.
bool read_plane(const QByteArray& data, qsizetype& at, QImage& plane){
    plane = QImage();
    if (data.size() - at < 24){
        return false;
    }
    const bool magic = data.mid(at, 4) == QByteArray("VSHT");
    const uint32_t width = read_u32(data, at + 4);
    const uint32_t height = read_u32(data, at + 8);
    const uint32_t pitch = read_u32(data, at + 12);
    const uint32_t size = read_u32(data, at + 20);
    at += 24;
    if (!magic || size == 0){
        return magic;
    }
    if ((qsizetype)size > data.size() - at){
        return false;
    }
    //  The rows are RGBA; a pitch below the width means tightly packed rows.
    const qsizetype stride = pitch >= width * 4 ? (qsizetype)pitch : (qsizetype)width * 4;
    if (width == 0 || height == 0 || width > 4096 || height > 4096 || stride * (qsizetype)height > (qsizetype)size){
        at += size;
        return true;
    }
    QImage image((int)width, (int)height, QImage::Format_RGBA8888);
    for (uint32_t row = 0; row < height; row++){
        memcpy(image.scanLine((int)row), data.constData() + at + stride * row, (size_t)width * 4);
    }
    at += size;
    plane = image;
    return true;
}

}

QImage picture_of_shot(const QByteArray& data){
    qsizetype at = 0;
    QImage app;
    QImage shell;
    if (!read_plane(data, at, app)){
        return QImage();
    }
    read_plane(data, at, shell);
    if (app.isNull()){
        return shell.isNull() ? QImage() : shell.convertToFormat(QImage::Format_RGB32);
    }
    QImage out = app.convertToFormat(QImage::Format_RGB32);
    if (!shell.isNull() && shell.size() == app.size()){
        for (int y = 0; y < out.height(); y++){
            QRgb* line = reinterpret_cast<QRgb*>(out.scanLine(y));
            const unsigned char* over = shell.constScanLine(y);
            for (int x = 0; x < out.width(); x++){
                const int a = over[x * 4 + 3];
                if (a == 0){
                    continue;
                }
                const QRgb under = line[x];
                const int r = (over[x * 4 + 0] * a + qRed(under) * (255 - a)) / 255;
                const int g = (over[x * 4 + 1] * a + qGreen(under) * (255 - a)) / 255;
                const int b = (over[x * 4 + 2] * a + qBlue(under) * (255 - a)) / 255;
                line[x] = qRgb(r, g, b);
            }
        }
    }
    return out;
}


namespace{


QString vita_host(){
    return QString::fromStdString(std::string(GlobalSettings::instance().VITA_HOST)).trimmed();
}
//  The token, where vita-agent-bridge's own README keeps it on the computer:
//  the file .vita-agent-token in the home folder (the user folder on
//  Windows). Not in the settings, which are a plain file that is easily shared.
QString token_file(){
    return QDir::homePath() + "/.vita-agent-token";
}
std::string vita_token(){
    QFile file(token_file());
    if (!file.open(QIODevice::ReadOnly)){
        return std::string();
    }
    return token_of(file.read(4096).toStdString());
}


//  The commands of vita-agent-bridge: one connection for each.
class Bridge{
public:
    Bridge(Logger& logger, QString host, std::string token)
        : m_logger(logger)
        , m_host(std::move(host))
        , m_token(std::move(token))
    {}

    std::string where() const{
        return m_host.toStdString() + ":" + std::to_string(BRIDGE_PORT);
    }

    //  Checks the settings and that the bridge answers: its "status" line.
    QString check(){
        if (m_host.isEmpty()){
            throw UserSetupError(
                m_logger,
                "The address of the Vita is not set: fill in \"PlayStation Vita, address\" in the settings "
                "(Settings, Network, Wi-Fi Settings on the Vita shows it)."
            );
        }
        if (m_token.empty()){
            throw UserSetupError(
                m_logger,
                "The token of vita-agent-bridge is not there: put the same 64 characters as in "
                "ur0:data/vita-agent-bridge/token.txt on the Vita into the file " + token_file().toStdString() +
                " on this computer."
            );
        }
        const QString status = command("status");
        if (!status.startsWith("vita-agent-bridge")){
            throw UserSetupError(
                m_logger,
                "Something answers at " + where() + ", but it is not vita-agent-bridge (it said \"" +
                status.left(60).toStdString() + "\")."
            );
        }
        return status;
    }

    //  One command; the answer without "OK" in front. ERR throws.
    QString command(const QString& line, int timeout_ms = 15000){
        QTcpSocket socket;
        send(socket, line);
        QByteArray buffer;
        const QString reply = read_line(socket, buffer, timeout_ms, line);
        return answer_of(reply, line);
    }

    //  "hold" and the like: the command, then the rest of "duration" after
    //  its answer (whether the bridge answers at once or when it is over).
    void timed(CancellableScope& scope, const QString& line, std::chrono::milliseconds duration){
        QElapsedTimer timer;
        timer.start();
        command(line, (int)duration.count() + 15000);
        const auto left = duration - std::chrono::milliseconds(timer.elapsed());
        if (left.count() > 0){
            scope.wait_for(left);
        }
    }

    //  A picture of the screen ("half": every second pixel, 480 x 272).
    QImage shot(bool half){
        QTcpSocket socket;
        const QString line = half ? "shot half" : "shot";
        send(socket, line);
        QByteArray data;
        QElapsedTimer timer;
        timer.start();
        //  Waits until "data" has "size" bytes. An ERR line instead of the
        //  pictures says why not.
        const auto need = [&](qsizetype size){
            while (data.size() < size){
                if (data.startsWith("ERR")){
                    const qsizetype end = data.indexOf('\n');
                    if (end >= 0){
                        answer_of(QString::fromUtf8(data.left(end)).trimmed(), line);
                    }
                }
                const int left = 60000 - (int)timer.elapsed();
                if (left <= 0){
                    fail("the picture did not come in time");
                }
                if (socket.bytesAvailable() > 0 || socket.waitForReadyRead(std::min(left, 500))){
                    data += socket.readAll();
                }else if (socket.state() != QAbstractSocket::ConnectedState){
                    fail("the bridge closed the connection during the picture");
                }
            }
        };
        //  The two planes (the game's, the shell's), each a header and its bytes.
        qsizetype at = 0;
        for (int plane = 0; plane < 2; plane++){
            need(at + 24);
            if (data.mid(at, 4) != QByteArray("VSHT")){
                fail("the picture has no header");
            }
            const qsizetype size = (qsizetype)read_u32(data, at + 20);
            if (size > 64 * 1024 * 1024){
                fail("the picture is too large");
            }
            need(at + 24 + size);
            at += 24 + size;
        }
        return picture_of_shot(data);
    }

private:
    [[noreturn]] void fail(const std::string& what){
        throw OperationFailedException(
            ErrorReportMode::NO_ERROR_REPORT,
            "The connection to vita-agent-bridge at " + where() + " failed: " + what + "."
        );
    }

    void send(QTcpSocket& socket, const QString& line){
        socket.connectToHost(m_host, (quint16)BRIDGE_PORT);
        if (!socket.waitForConnected(5000)){
            throw UserSetupError(
                m_logger,
                "Cannot reach the Vita at " + where() + " (" + socket.errorString().toStdString() + "). Is it on and "
                "on the same network, with vita-agent-bridge installed (its plugin in ur0:tai/config.txt, and its "
                "token file)? The Vita must not be asleep."
            );
        }
        const QByteArray bytes = ("AUTH " + QString::fromStdString(m_token) + " " + line + "\n").toUtf8();
        if (socket.write(bytes) != bytes.size() || !socket.waitForBytesWritten(3000)){
            fail("the command could not be sent");
        }
    }

    QString read_line(QTcpSocket& socket, QByteArray& buffer, int msec, const QString& line){
        QElapsedTimer timer;
        timer.start();
        for (;;){
            const qsizetype end = buffer.indexOf('\n');
            if (end >= 0){
                return QString::fromUtf8(buffer.left(end)).trimmed();
            }
            const int left = msec - (int)timer.elapsed();
            if (left <= 0){
                fail("no answer to \"" + line.toStdString() + "\" in time");
            }
            if (socket.bytesAvailable() > 0 || socket.waitForReadyRead(std::min(left, 500))){
                buffer += socket.readAll();
            }else if (socket.state() != QAbstractSocket::ConnectedState){
                if (!buffer.isEmpty()){
                    return QString::fromUtf8(buffer).trimmed();
                }
                fail("the bridge closed the connection");
            }
        }
    }

    QString answer_of(const QString& reply, const QString& line){
        if (reply == "ERR auth"){
            throw UserSetupError(
                m_logger,
                "vita-agent-bridge refuses the token: the file " + token_file().toStdString() + " must have the "
                "same 64 characters as ur0:data/vita-agent-bridge/token.txt on the Vita."
            );
        }
        if (reply.startsWith("ERR")){
            throw OperationFailedException(
                ErrorReportMode::NO_ERROR_REPORT,
                "vita-agent-bridge says: " + reply.mid(4).toStdString() + " (to \"" + line.toStdString() + "\")"
            );
        }
        if (reply == "OK"){
            return QString();
        }
        if (reply.startsWith("OK ")){
            return reply.mid(3);
        }
        fail("an answer it does not know: \"" + reply.left(60).toStdString() + "\"");
    }

    Logger& m_logger;
    QString m_host;
    std::string m_token;
};


//  The Vita, worked through the bridge, and its screen.
class VitaConsole : public PlayConsole{
public:
    VitaConsole(CancellableScope& scope, Bridge& bridge, bool half, Language language)
        : m_scope(scope)
        , m_bridge(bridge)
        , m_half(half)
        , m_language(language)
    {}

    static const PadLayout& vita_layout(){
        static const PadLayout layout{
            "a PlayStation Vita (the program works it over the network through vita-agent-bridge; its front "
            "screen is a touch screen too, see the tool \"touch\")",
            {
                "CROSS", "CIRCLE", "SQUARE", "TRIANGLE", "L", "R", "START", "SELECT",
                "UP", "DOWN", "LEFT", "RIGHT",
            },
            {"left_stick", "right_stick"},
            false,
            "a real PlayStation Vita",
            "On a Vita, CROSS is usually yes and CIRCLE usually no or back (on a Japanese Vita the other way round).",
            true,
        };
        return layout;
    }

    virtual const PadLayout& layout() const override{
        return vita_layout();
    }
    virtual void hold(const PadInput& input, std::chrono::milliseconds duration) override{
        const int ms = std::clamp((int)duration.count(), 16, 10000);
        //  The bridge takes the sticks and the buttons as two commands, one
        //  after the other: a stick first, then the buttons.
        if (input.stick_x != 0 || input.stick_y != 0 || input.stick2_x != 0 || input.stick2_y != 0){
            m_bridge.timed(
                m_scope,
                "stick " + QString::number(stick_value(input.stick_x, false)) + " " +
                    QString::number(stick_value(input.stick_y, true)) + " " +
                    QString::number(stick_value(input.stick2_x, false)) + " " +
                    QString::number(stick_value(input.stick2_y, true)) + " " + QString::number(ms),
                std::chrono::milliseconds(ms)
            );
        }
        uint32_t mask = 0;
        for (const std::string& name : input.buttons){
            mask |= button_bit(name);
        }
        if (mask != 0){
            m_bridge.timed(m_scope, "hold " + QString::number(mask) + " " + QString::number(ms), std::chrono::milliseconds(ms));
        }
    }
    virtual void mash(const std::string& name, std::chrono::milliseconds duration) override{
        const uint32_t bit = button_bit(name);
        if (bit == 0){
            return;
        }
        const auto end = std::chrono::steady_clock::now() + duration;
        while (std::chrono::steady_clock::now() < end){
            m_bridge.timed(m_scope, "hold " + QString::number(bit) + " 60", std::chrono::milliseconds(60));
            m_scope.wait_for(std::chrono::milliseconds(60));
        }
    }
    virtual void wait(std::chrono::milliseconds duration) override{
        m_scope.wait_for(duration);
    }
    virtual bool screen(const std::function<void(const ImageViewRGB32&)>& use) override{
        const QImage picture = m_bridge.shot(m_half);
        if (picture.isNull()){
            return false;
        }
        const ImageRGB32 frame = QImage_to_ImageRGB32(picture);
        use(frame);
        return true;
    }
    virtual std::string read_text(const ImageViewRGB32& picture) override{
        return OCR::ocr_read(m_language, picture, OCR::PageSegMode::AUTO);
    }

    //  Touches (x, y) of the screen for "duration".
    void touch(int x, int y, std::chrono::milliseconds duration){
        m_bridge.timed(
            m_scope,
            "touch " + QString::number(x) + " " + QString::number(y) + " " + QString::number(duration.count()),
            duration
        );
    }

private:
    CancellableScope& m_scope;
    Bridge& m_bridge;
    const bool m_half;
    const Language m_language;
};


//  The tools of any game, and a touch on the front screen.
class VitaGame : public Game{
public:
    VitaGame(VitaConsole& console, GameFacts facts, AnyGameOptions options)
        : m_console(console)
        , m_options(options)
        , m_any(console, std::move(facts), options)
    {}

    virtual std::vector<PlayTool> tools() const override{
        std::vector<PlayTool> list = m_any.tools();
        PlayTool touch;
        touch.name = "touch";
        touch.description =
            "Touches the Vita's front touch screen at a point and lets go. x and y are pixels of a picture of "
            "the whole screen as \"look\" sends it (" + std::to_string(m_options.picture_width) + " x " +
            std::to_string(m_options.picture_height) + ", 0, 0 at the top left). ms: how long, 50 to 3000 (100 "
            "when left out). The Vita's own menus (the home screen, the LiveArea) take only touches and the PS "
            "button, no other buttons.";
        touch.input_schema =
            "{\"type\":\"object\",\"properties\":{"
            "\"x\":{\"type\":\"integer\",\"description\":\"from the left\"},"
            "\"y\":{\"type\":\"integer\",\"description\":\"from the top\"},"
            "\"ms\":{\"type\":\"integer\",\"description\":\"how long the touch lasts\"}"
            "},\"required\":[\"x\",\"y\"]}";
        list.push_back(std::move(touch));
        return list;
    }
    virtual std::string instructions() const override{
        return m_any.instructions() +
            "\n\nThe pictures are of the Vita's screen (960 x 544). In games the buttons work; the Vita's own "
            "menus (the home screen, the LiveArea, the settings) ignore every button except HOME (the PS button): "
            "use the tool \"touch\" there.";
    }
    virtual std::string screen() override{
        return m_any.screen();
    }
    virtual PlayResult run(const PlayCall& call) override{
        if (call.name != "touch"){
            return m_any.run(call);
        }
        PlayResult result;
        const QJsonObject input = QJsonDocument::fromJson(QByteArray::fromStdString(call.input)).object();
        if (!input.contains("x") || !input.contains("y")){
            result.is_error = true;
            result.text = "touch needs x and y.";
            return result;
        }
        const int x = input.value("x").toInt();
        const int y = input.value("y").toInt();
        if (x < 0 || y < 0 || x >= m_options.picture_width || y >= m_options.picture_height){
            result.is_error = true;
            result.text = "x and y must be inside the picture: 0 to " + std::to_string(m_options.picture_width - 1) +
                " and 0 to " + std::to_string(m_options.picture_height - 1) + ".";
            return result;
        }
        const int ms = std::clamp(input.contains("ms") ? input.value("ms").toInt() : 100, 50, 3000);
        int sx = 0;
        int sy = 0;
        touch_point(x, y, m_options.picture_width, m_options.picture_height, sx, sy);
        m_console.touch(sx, sy, std::chrono::milliseconds(ms));
        result.text = "Touched (" + std::to_string(x) + ", " + std::to_string(y) + ") for " + std::to_string(ms) +
            " ms. Look to see what it did.";
        return result;
    }

private:
    VitaConsole& m_console;
    const AnyGameOptions m_options;
    AnyGame m_any;
};


class VitaHost : public Host{
public:
    VitaHost(ProgramEnvironment& env, CancellableScope& scope)
        : m_env(env)
        , m_scope(scope)
    {}
    virtual void log(const std::string& text, Color color) override{
        m_env.log(text, color);
    }
    virtual void show(const std::string& text, Color color) override{
        //  No video panel for this program: what would be on it goes in the log.
        (void)text;
        (void)color;
    }
    virtual void count(uint64_t actions, const PlayUsage& usage) override{
        (void)actions;
        (void)usage;
    }
    virtual CancellableScope& scope() override{
        return m_scope;
    }

private:
    ProgramEnvironment& m_env;
    CancellableScope& m_scope;
};


const std::string EXPERIMENTAL =
    "<b>Experimental:</b> new, and not tried on a Vita yet: tell us how it goes. ";

const std::string NEEDS =
    "<b>What it needs:</b> a PlayStation Vita with HENkaku Enso and taiHEN (vita-agent-bridge was made on a Vita "
    "2000 with 3.65), and <a href=\"https://github.com/hotdog-face/vita-agent-bridge\">vita-agent-bridge</a> "
    "(MIT, a separate project) installed as its page says: vakern.skprx and vabridge.suprx in "
    "ur0:data/vita-agent-bridge/, a token of 64 hexadecimal characters in token.txt there, and vakern.skprx "
    "under *KERNEL in ur0:tai/config.txt. Then the Vita's address under \"PlayStation Vita, address\" in the "
    "settings, and the same token in the file .vita-agent-token in your home folder (as the bridge's page says). The Vita and the computer on the same home "
    "network; the bridge has no encryption, so never open port 1348 to the internet.";


//  ---- Connect the Vita

class ConnectProgram_Descriptor : public ComputerProgramDescriptor{
public:
    ConnectProgram_Descriptor()
        : ComputerProgramDescriptor(
            "ClaudeGG:VitaConnect",
            VITA_LIST_NAME, "Connect the Vita",
            "",
            "Checks that the program reaches vita-agent-bridge on the Vita, and saves a picture of its screen.",
            PanelQualityStanding::EXPERIMENTAL
        )
    {}
    virtual std::unique_ptr<ComputerProgramInstance> make_instance() const override;
};

class ConnectProgram : public ComputerProgramInstance{
public:
    ConnectProgram()
        : SETUP_TEXT(
            EXPERIMENTAL + NEEDS + "<br>"
            "<b>What it does:</b> asks the bridge for its status (its version and the app on the screen), and "
            "saves a picture of the Vita's screen."
        )
        , PRESS_PS(
            "<b>Press the PS button as a test:</b><br>The program presses PS once: the Vita should go to its "
            "home screen or the LiveArea. Off: nothing is pressed.",
            LockMode::LOCK_WHILE_RUNNING,
            false
        )
        , SAVE_PICTURE(
            "<b>Save a picture of the Vita's screen</b> in the folder Vita of the program's user files.",
            LockMode::LOCK_WHILE_RUNNING,
            true
        )
    {
        PA_ADD_OPTION(SETUP_TEXT);
        PA_ADD_OPTION(PRESS_PS);
        PA_ADD_OPTION(SAVE_PICTURE);
    }

    virtual void program(ProgramEnvironment& env, CancellableScope& scope) override{
        env.log(PROGRAM_NAME + " build " + PROGRAM_BUILD + " (PlayStation Vita: Connect the Vita, experimental)", COLOR_BLUE);
        Bridge bridge(env.logger(), vita_host(), vita_token());
        const QString status = bridge.check();
        env.log("The bridge answers at " + bridge.where() + ": " + status.toStdString(), COLOR_BLUE);

        QElapsedTimer timer;
        timer.start();
        const QImage picture = bridge.shot(false);
        if (picture.isNull()){
            throw OperationFailedException(
                ErrorReportMode::NO_ERROR_REPORT,
                "The bridge answers, but gave no picture of the screen."
            );
        }
        env.log(
            "The picture works: " + std::to_string(picture.width()) + " x " + std::to_string(picture.height()) +
            ", in " + std::to_string(timer.elapsed()) + " ms.",
            COLOR_BLUE
        );
        if (SAVE_PICTURE){
            const QString folder = QString::fromStdString(USER_FILE_PATH()) + "Vita/";
            QDir().mkpath(folder);
            const QString file = folder + "Vita-" + QDateTime::currentDateTime().toString("yyyyMMdd-HHmmss") + ".png";
            if (picture.save(file)){
                env.log("Saved " + file.toStdString() + ".");
            }else{
                env.log("Could not save " + file.toStdString() + ".", COLOR_ORANGE);
            }
        }
        if (PRESS_PS){
            env.log("Pressing PS...");
            bridge.timed(scope, "hold " + QString::number(button_bit("HOME")) + " 150", std::chrono::milliseconds(150));
            env.log("Pressed PS: the Vita should show its home screen or the LiveArea now.");
        }
        env.log("The Vita works. Claude Plays (PlayStation Vita) can play now.", COLOR_GREEN);
    }

private:
    StaticTextOption SETUP_TEXT;
    BooleanCheckBoxOption PRESS_PS;
    BooleanCheckBoxOption SAVE_PICTURE;
};

std::unique_ptr<ComputerProgramInstance> ConnectProgram_Descriptor::make_instance() const{
    return std::make_unique<ConnectProgram>();
}


//  ---- Claude Plays

enum class Picture{
    HALF,
    FULL,
};

class PlayProgram_Descriptor : public ComputerProgramDescriptor{
public:
    PlayProgram_Descriptor()
        : ComputerProgramDescriptor(
            "ClaudeGG:VitaClaudePlays",
            VITA_LIST_NAME, "Claude Plays",
            "",
            "Claude plays the game on the Vita toward a goal you give it: it looks at the Vita's screen and works "
            "its buttons, sticks and touch screen, over the network.",
            PanelQualityStanding::EXPERIMENTAL
        )
    {}
    virtual std::unique_ptr<ComputerProgramInstance> make_instance() const override;
};

class PlayProgram : public ComputerProgramInstance{
public:
    PlayProgram()
        : SETUP_TEXT(
            EXPERIMENTAL + "<b>Many games save by themselves:</b> what Claude does in the game can be final. Where "
            "that matters, make a save or a backup of your own first.<br>"
            "<b>What it does:</b> Claude, the AI model of Anthropic, plays the game toward the goal below. It gets "
            "pictures of the Vita's screen and the text the program reads from it, and works the Vita: buttons "
            "pressed, buttons and sticks held, a button mashed, the touch screen touched. A picture takes a "
            "moment over Wi-Fi (the bridge sends about 2 MB a second), so this is for menus and games that wait, "
            "not for quick action.<br>"
            "<b>Who pays:</b> with \"The program asks Claude\", your Claude API key in the panel \"Claude\" (each "
            "request is billed to you by Anthropic, and the pictures go to Anthropic). Without a key: let Claude "
            "Code play (see \"Who plays\").<br>" + NEEDS + " Run \"Connect the Vita\" once first."
        )
        , WHO()
        , GOAL(
            "<b>Goal:</b><br>What Claude should do, in your own words (any language). Say where the game is at, if "
            "that helps, and when the goal is reached. (Not used when Claude Code plays: give the goal to Claude Code.)",
            LockMode::LOCK_WHILE_RUNNING,
            "Look at the screen and say which game it shows, where it is at and what could be done from here. "
            "Do not press anything.",
            "For example: Open the game's menu and tell me how much money the player has."
        )
        , ABOUT(
            "<b>About the game (optional):</b><br>Which game it is and what Claude should know about it: its "
            "controls, where the save is, what to stay away from. Without it Claude finds out from the screen.",
            LockMode::LOCK_WHILE_RUNNING,
            "",
            "For example: Persona 4 Golden. CROSS confirms, the menu is TRIANGLE."
        )
        , TEXT_LANGUAGE(
            "<b>Language of the text:</b><br>The language of the text in the game. The program reads text from the "
            "screen (the tool \"read_text\") in this language, and Claude is told which it is.",
            LanguageSet{
                Language::English, Language::Japanese, Language::Spanish, Language::French, Language::German,
                Language::Italian, Language::Korean, Language::ChineseSimplified, Language::ChineseTraditional,
            },
            LockMode::LOCK_WHILE_RUNNING,
            true
        )
        , MODEL(
            "<b>Model:</b><br>(Only when the program asks Claude.) The smallest model is the fastest and by far the "
            "cheapest, and enough for simple goals. A larger one finds its way better, and costs many times more.",
            {
                {Model::HAIKU,  "haiku",    "Claude Haiku 5.5 (fastest, cheapest)"},
                {Model::SONNET, "sonnet",   "Claude Sonnet 5.5 (about 20 times the price)"},
                {Model::OPUS,   "opus",     "Claude Opus 5.5 (about 40 times the price)"},
                {Model::FABLE,  "fable",    "Claude Fable 5.2 (about 80 times the price)"},
            },
            LockMode::LOCK_WHILE_RUNNING,
            Model::HAIKU
        )
        , MAX_ACTIONS(
            "<b>Stop after actions:</b><br>An action is one thing Claude has the program do: a look, a reading, "
            "some button presses, a touch, a wait.",
            LockMode::LOCK_WHILE_RUNNING,
            100, 1, 100000
        )
        , MAX_COST(
            "<b>Stop at a cost of (US dollars):</b><br>(Only when the program asks Claude.) Estimated from "
            "Anthropic's public prices; the invoice is what counts. 0: no limit.",
            LockMode::LOCK_WHILE_RUNNING,
            0.50, 0, 1000
        )
        , PICTURE(
            "<b>Pictures for Claude:</b><br>Of the whole screen. The full one shows small text better, costs more "
            "tokens and takes about four times as long over Wi-Fi.",
            {
                {Picture::HALF, "half", "480 x 272 (about 174 tokens a picture, quickest)"},
                {Picture::FULL, "full", "960 x 544 (about 696 tokens, the Vita's own size)"},
            },
            LockMode::LOCK_WHILE_RUNNING,
            Picture::HALF
        )
        , ALLOW_HOME(
            "<b>Claude may press PS:</b><br>PS leaves the game for the Vita's LiveArea. Off: the program does not "
            "press it, whatever Claude asks for.",
            LockMode::LOCK_WHILE_RUNNING,
            false
        )
        , MEASURE_TIMING(MEASURE_TIMING_LABEL, LockMode::LOCK_WHILE_RUNNING, false)
        , PRESS_MS(PRESS_MS_LABEL, LockMode::LOCK_WHILE_RUNNING, 0, 0, 500)
        , VIDEO_DELAY_MS(VIDEO_DELAY_MS_LABEL, LockMode::LOCK_WHILE_RUNNING, 0, 0, 1000)
    {
        PA_ADD_OPTION(SETUP_TEXT);
        add_option(WHO.PLAYER, "PLAYER");
        add_option(WHO.PORT, "MCP_PORT");
        add_option(WHO.IDLE, "MCP_IDLE");
        PA_ADD_OPTION(GOAL);
        PA_ADD_OPTION(ABOUT);
        PA_ADD_OPTION(TEXT_LANGUAGE);
        PA_ADD_OPTION(MODEL);
        PA_ADD_OPTION(MAX_ACTIONS);
        PA_ADD_OPTION(MAX_COST);
        PA_ADD_OPTION(PICTURE);
        PA_ADD_OPTION(ALLOW_HOME);
        PA_ADD_OPTION(MEASURE_TIMING);
        PA_ADD_OPTION(PRESS_MS);
        PA_ADD_OPTION(VIDEO_DELAY_MS);
    }

    virtual void program(ProgramEnvironment& env, CancellableScope& scope) override{
        env.log(PROGRAM_NAME + " build " + PROGRAM_BUILD + " (PlayStation Vita: Claude Plays, experimental)", COLOR_BLUE);

        const bool external = WHO.claude_code();
        const std::string goal = trimmed(GOAL);
        if (!external){
            if (goal.empty()){
                throw UserSetupError(env.logger(), "Write down a goal for Claude first.");
            }
            const std::string unavailable = PlaySession::why_unavailable(scope);
            if (!unavailable.empty()){
                throw UserSetupError(env.logger(), unavailable);
            }
        }

        const bool half = (Picture)PICTURE == Picture::HALF;
        AnyGameOptions options;
        options.picture_width = half ? SCREEN_WIDTH / 2 : SCREEN_WIDTH;
        options.picture_height = half ? SCREEN_HEIGHT / 2 : SCREEN_HEIGHT;
        options.allow_home = ALLOW_HOME;
        options.external = external;
        //  How presses are played and how late the picture comes, over Wi-Fi
        //  (ClaudePlays_Consoles.cpp).
        {
            const ConsoleTraits traits = console_traits("vita");
            const uint32_t press_ms = PRESS_MS;
            const uint32_t video_delay_ms = VIDEO_DELAY_MS;
            options.timing = timing_by_hand(traits.timing, press_ms, video_delay_ms);
            env.log(
                "Timing: " + timing_text(options.timing) +
                (press_ms > 0 || video_delay_ms > 0 ? " (set by hand). " : ". ") + traits.why
            );
        }

        GameFacts facts;
        facts.notes =
            "The console is a PlayStation Vita. Vita games use CROSS, CIRCLE, SQUARE, TRIANGLE, L, R, START "
            "(often the pause menu), SELECT, the two sticks, the d-pad and the front touch screen. The program "
            "cannot use the rear touch pad, and it does a stick and buttons one after the other, not at once.";
        facts.user_notes = trimmed(ABOUT);
        const Language text_language = TEXT_LANGUAGE;
        if (text_language != Language::English){
            facts.text_language = language_data(text_language).name;
        }

        Limits limits;
        limits.max_actions = (uint64_t)(uint32_t)MAX_ACTIONS;
        limits.max_cost = MAX_COST;
        const Model model = MODEL;

        Bridge bridge(env.logger(), vita_host(), vita_token());
        const QString status = bridge.check();
        env.log("The bridge answers at " + bridge.where() + ": " + status.toStdString(), COLOR_BLUE);

        VitaConsole console(scope, bridge, half, text_language);
        //  Measured on this setup first, when asked (a menu that DOWN and UP
        //  move in on the screen).
        if (MEASURE_TIMING){
            options.timing = measured_timing(
                console, options.timing,
                [&](const std::string& text, bool measured){
                    env.log(text, measured ? COLOR_BLUE : COLOR_ORANGE);
                }
            );
        }
        VitaGame game(console, facts, options);
        VitaHost host(env, scope);
        Ending ending;
        if (external){
            ending = serve_claude_code(env.logger(), host, game, WHO, limits);
        }else{
            PlaySession claude(make_setup(game, model));
            env.log(
                std::string("Claude Plays: ") + model_id(model) + ", at most " + std::to_string(limits.max_actions) +
                " actions" + (limits.max_cost > 0 ? ", at most about " + money(limits.max_cost) : std::string(", no cost limit")) +
                ". Goal: " + one_line(goal, 300),
                COLOR_BLUE
            );
            ending = play(host, game, claude, goal, limits);
            if (ending.failed){
                throw OperationFailedException(ErrorReportMode::NO_ERROR_REPORT, ending.summary);
            }
        }
        env.log("Claude Plays: " + ending.summary, ending.reached ? COLOR_BLUE : COLOR_ORANGE);
    }

private:
    StaticTextOption SETUP_TEXT;
    WhoPlays WHO;
    TextEditOption GOAL;
    TextEditOption ABOUT;
    OCR::LanguageOCROption TEXT_LANGUAGE;
    EnumDropdownOption<Model> MODEL;
    SimpleIntegerOption<uint32_t> MAX_ACTIONS;
    FloatingPointOption MAX_COST;
    EnumDropdownOption<Picture> PICTURE;
    BooleanCheckBoxOption ALLOW_HOME;
    BooleanCheckBoxOption MEASURE_TIMING;
    SimpleIntegerOption<uint32_t> PRESS_MS;
    SimpleIntegerOption<uint32_t> VIDEO_DELAY_MS;
};

std::unique_ptr<ComputerProgramInstance> PlayProgram_Descriptor::make_instance() const{
    return std::make_unique<PlayProgram>();
}


}   //  namespace



VitaList::VitaList()
    : PanelListDescriptor(VITA_LIST_NAME)
{
    m_icon = QImage_to_ImageRGB32(make_game_card(VITA_LIST_NAME, qRgb(0x22, 0x3a, 0x8c)));
}

std::vector<PanelEntry> VitaList::make_panels() const{
    std::vector<PanelEntry> ret;
    ret.emplace_back("---- PlayStation Vita (experimental) ----");
    ret.emplace_back(std::make_unique<ConnectProgram_Descriptor>());
    ret.emplace_back(std::make_unique<PlayProgram_Descriptor>());
    return ret;
}

size_t vita_program_count(){
    return 2;
}



}
}
}
