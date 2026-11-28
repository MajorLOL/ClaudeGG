/*  Claude GG Wii U (a Raspberry Pi as the GamePad)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <algorithm>
#include <chrono>
#include <cmath>
#include <string>
#include <vector>
#include <QByteArray>
#include <QDateTime>
#include <QDir>
#include <QElapsedTimer>
#include <QImage>
#include <QJsonDocument>
#include <QJsonObject>
#include <QString>
#include <QStringList>
#include <QTcpSocket>
#include "Common/Cpp/CancellableScope.h"
#include "Common/Cpp/Color.h"
#include "Common/Cpp/Exceptions.h"
#include "Common/Cpp/Options/BooleanCheckBoxOption.h"
#include "Common/Cpp/Options/EnumDropdownOption.h"
#include "Common/Cpp/Options/FloatingPointOption.h"
#include "Common/Cpp/Options/SimpleIntegerOption.h"
#include "Common/Cpp/Options/StaticTextOption.h"
#include "Common/Cpp/Options/StringOption.h"
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
#include "ClaudeGG_Mobile.h"
#include "ClaudeGG_WiiU.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace WiiU{

using namespace ClaudePlays;


const char* const WIIU_LIST_NAME = "Nintendo Wii U";


std::string sync_code_of(const std::string& typed){
    //  The symbols as UTF-8: spade, heart, diamond, club (filled and outlined).
    static const struct{
        const char* text;
        char letter;
    } SYMBOLS[] = {
        {"\xE2\x99\xA0", 'S'}, {"\xE2\x99\xA4", 'S'},
        {"\xE2\x99\xA5", 'H'}, {"\xE2\x99\xA1", 'H'},
        {"\xE2\x99\xA6", 'D'}, {"\xE2\x99\xA2", 'D'},
        {"\xE2\x99\xA3", 'C'}, {"\xE2\x99\xA7", 'C'},
    };
    std::string code;
    size_t c = 0;
    while (c < typed.size()){
        const char ch = typed[c];
        if (ch == ' ' || ch == '\t' || ch == ',' || ch == '-'){
            c++;
            continue;
        }
        bool symbol = false;
        for (const auto& s : SYMBOLS){
            const size_t length = std::char_traits<char>::length(s.text);
            if (typed.compare(c, length, s.text) == 0){
                code += s.letter;
                c += length;
                symbol = true;
                break;
            }
        }
        if (symbol){
            continue;
        }
        switch (ch){
        case 'S': case 's': case '0':
            code += 'S';
            break;
        case 'H': case 'h': case '1':
            code += 'H';
            break;
        case 'D': case 'd': case '2':
            code += 'D';
            break;
        case 'C': case 'c': case '3':
            code += 'C';
            break;
        default:
            return std::string();
        }
        c++;
    }
    return code.size() == 4 ? code : std::string();
}

void touch_point(int x, int y, int width, int height, int& gamepad_x, int& gamepad_y){
    const double fx = width > 1 ? (double)x / (double)(width - 1) : 0.5;
    const double fy = height > 1 ? (double)y / (double)(height - 1) : 0.5;
    gamepad_x = std::clamp((int)std::lround(fx * (GAMEPAD_WIDTH - 1)), 0, GAMEPAD_WIDTH - 1);
    gamepad_y = std::clamp((int)std::lround(fy * (GAMEPAD_HEIGHT - 1)), 0, GAMEPAD_HEIGHT - 1);
}


namespace{


//  The Raspberry Pi of the Wii U: its own setting, or the phone's Pi.
QString bridge_host(){
    GlobalSettings& settings = GlobalSettings::instance();
    QString host = QString::fromStdString(std::string(settings.WIIU_HOST)).trimmed();
    if (host.isEmpty()){
        host = QString::fromStdString(std::string(settings.MOBILE_HOST)).trimmed();
    }
    return host;
}


//  One connection to the bridge's commands. The program's thread uses it,
//  and waits for each answer (a line that starts with OK or ERR). Lines that
//  start with EVENT come whenever something happens (paired, connected, an
//  error of the Wii U's link) and are kept until they are asked for.
class Bridge{
public:
    Bridge(Logger& logger, QString host)
        : m_logger(logger)
        , m_host(std::move(host))
    {}

    std::string where() const{
        return m_host.toStdString() + ":" + std::to_string(BRIDGE_COMMAND_PORT);
    }

    void open(){
        if (m_host.isEmpty()){
            throw UserSetupError(
                m_logger,
                "The address of the Raspberry Pi is not set: fill in \"Wii U, address of the Raspberry Pi\" in "
                "the settings."
            );
        }
        m_socket.connectToHost(m_host, (quint16)BRIDGE_COMMAND_PORT);
        if (!m_socket.waitForConnected(5000)){
            throw UserSetupError(
                m_logger,
                "Cannot reach the bridge on the Raspberry Pi at " + where() + " (" + m_socket.errorString().toStdString() +
                "). Start vanilla-pipe and claudegg-wiiu-bridge on the Pi first (see WiiU/vanilla-bridge/README.md)."
            );
        }
        const QString hello = read_line(5000);
        if (!hello.startsWith("HELLO claudegg-wiiu-bridge")){
            throw UserSetupError(
                m_logger,
                "Something answers at " + where() + ", but it is not claudegg-wiiu-bridge (it said \"" +
                hello.left(60).toStdString() + "\")."
            );
        }
    }

    //  Sends one command; the answer without "OK" in front. An answer ERR
    //  throws, with what the bridge said.
    QString command(const QString& line){
        const QByteArray bytes = (line + "\n").toUtf8();
        if (m_socket.write(bytes) != bytes.size() || !m_socket.waitForBytesWritten(3000)){
            fail("the command could not be sent to the bridge");
        }
        QElapsedTimer timer;
        timer.start();
        for (;;){
            const int left = 5000 - (int)timer.elapsed();
            if (left <= 0){
                fail("the bridge did not answer \"" + line.toStdString() + "\"");
            }
            const QString reply = read_line(left);
            if (reply.startsWith("EVENT")){
                m_events.append(reply);
                continue;
            }
            if (reply == "OK"){
                return QString();
            }
            if (reply.startsWith("OK ")){
                return reply.mid(3);
            }
            if (reply.startsWith("ERR")){
                throw OperationFailedException(
                    ErrorReportMode::NO_ERROR_REPORT,
                    "The bridge says: " + reply.mid(4).toStdString() + " (to \"" + line.toStdString() + "\")"
                );
            }
        }
    }

    //  Waits up to "seconds" for an event that starts with one of "wanted"
    //  ("EVENT SYNCED", ...), or "EVENT ERROR". Empty: none came.
    QString wait_event(CancellableScope& scope, const QStringList& wanted, int seconds){
        QElapsedTimer timer;
        timer.start();
        for (;;){
            while (!m_events.isEmpty()){
                const QString event = m_events.takeFirst();
                if (event.startsWith("EVENT ERROR")){
                    return event;
                }
                for (const QString& prefix : wanted){
                    if (event.startsWith(prefix)){
                        return event;
                    }
                }
            }
            scope.throw_if_cancelled();
            if (timer.elapsed() > seconds * 1000LL){
                return QString();
            }
            const QString line = read_line(250, true);
            if (!line.isEmpty()){
                m_events.append(line);
            }
        }
    }

    //  "idle", "syncing" or "connected", and whether a Wii U was paired.
    void status(QString& state, bool& paired){
        const QStringList words = command("STATUS").split(' ', Qt::SkipEmptyParts);
        state = words.size() >= 2 ? words[1] : QString();
        paired = words.size() >= 4 && words[3] == "yes";
    }

    void release_quietly(){
        try{
            if (m_socket.state() == QAbstractSocket::ConnectedState){
                command("RELEASE");
            }
        }catch (...){}
    }

private:
    [[noreturn]] void fail(const std::string& what){
        throw OperationFailedException(
            ErrorReportMode::NO_ERROR_REPORT,
            "The connection to the bridge at " + where() + " failed: " + what + "."
        );
    }

    //  One line, without its end. "may_time_out": an empty line when none
    //  came in time, otherwise that is an error.
    QString read_line(int msec, bool may_time_out = false){
        QElapsedTimer timer;
        timer.start();
        for (;;){
            const qsizetype end = m_buffer.indexOf('\n');
            if (end >= 0){
                const QString line = QString::fromUtf8(m_buffer.left(end)).trimmed();
                m_buffer.remove(0, end + 1);
                return line;
            }
            if (m_socket.state() != QAbstractSocket::ConnectedState && m_socket.bytesAvailable() == 0){
                fail("the bridge closed the connection");
            }
            const int left = msec - (int)timer.elapsed();
            if (left <= 0){
                if (may_time_out){
                    return QString();
                }
                fail("no answer in time");
            }
            if (m_socket.bytesAvailable() > 0 || m_socket.waitForReadyRead(std::min(left, 200))){
                m_buffer += m_socket.readAll();
            }
        }
    }

    Logger& m_logger;
    QString m_host;
    QTcpSocket m_socket;
    QByteArray m_buffer;
    QStringList m_events;
};


//  Connects the bridge to the Wii U, when it is not connected yet, and waits
//  for the first picture of the Wii U.
void make_connected(ProgramEnvironment& env, CancellableScope& scope, Bridge& bridge){
    QString state;
    bool paired = false;
    bridge.status(state, paired);
    if (state == "connected"){
        return;
    }
    if (!paired){
        throw UserSetupError(
            env.logger(),
            "The Raspberry Pi is not paired with a Wii U yet: run \"Connect the GamePad\" with the four symbols "
            "that the Wii U shows after a press of its SYNC button."
        );
    }
    env.log("Connecting to the Wii U...", COLOR_BLUE);
    bridge.command("CONNECT");
    const QString event = bridge.wait_event(scope, {"EVENT CONNECTED"}, 40);
    if (event.isEmpty()){
        throw OperationFailedException(
            ErrorReportMode::NO_ERROR_REPORT,
            "The Wii U did not answer within 40 seconds. Is it on, and near the Wi-Fi adapter of the Pi? (A Wii U "
            "only talks to one GamePad: the real GamePad must be off.)"
        );
    }
    if (event.startsWith("EVENT ERROR")){
        throw OperationFailedException(
            ErrorReportMode::NO_ERROR_REPORT,
            "The connection to the Wii U failed (" + event.toStdString() + "). The codes are those of Vanilla: -205 "
            "and -206 mean that the adapter has no 5 GHz, -4 that vanilla-pipe does not answer."
        );
    }
    env.log("Connected: the Wii U sends the GamePad's picture.", COLOR_BLUE);
}


//  The GamePad, worked through the bridge, and its screen.
class WiiUConsole : public PlayConsole{
public:
    WiiUConsole(CancellableScope& scope, Bridge& bridge, MobileVideo& video, Language language)
        : m_scope(scope)
        , m_bridge(bridge)
        , m_video(video)
        , m_language(language)
    {}

    static const PadLayout& gamepad_layout(){
        static const PadLayout layout{
            "a Wii U GamePad (the program plays it through a Raspberry Pi; it has a touch screen too, see the tool "
            "\"touch\")",
            {
                "A", "B", "X", "Y", "L", "R", "ZL", "ZR", "PLUS", "MINUS", "LSTICK", "RSTICK",
                "UP", "DOWN", "LEFT", "RIGHT",
            },
            {"left_stick", "right_stick"},
            false,
            "a real Nintendo Wii U",
            "On a Wii U, A is usually yes and B usually no or back.",
            true,
        };
        return layout;
    }

    virtual const PadLayout& layout() const override{
        return gamepad_layout();
    }
    virtual void hold(const PadInput& input, std::chrono::milliseconds duration) override{
        for (const std::string& name : input.buttons){
            m_bridge.command("BTN " + bridge_button(name) + " 1");
        }
        set_stick("LX", input.stick_x);
        set_stick("LY", -input.stick_y);   //  the bridge has up negative
        set_stick("RX", input.stick2_x);
        set_stick("RY", -input.stick2_y);
        try{
            m_scope.wait_for(duration);
        }catch (...){
            m_bridge.release_quietly();
            throw;
        }
        m_bridge.command("RELEASE");
    }
    virtual void mash(const std::string& name, std::chrono::milliseconds duration) override{
        const QString button = bridge_button(name);
        const auto end = std::chrono::steady_clock::now() + duration;
        try{
            while (std::chrono::steady_clock::now() < end){
                m_bridge.command("BTN " + button + " 1");
                m_scope.wait_for(std::chrono::milliseconds(60));
                m_bridge.command("BTN " + button + " 0");
                m_scope.wait_for(std::chrono::milliseconds(60));
            }
        }catch (...){
            m_bridge.release_quietly();
            throw;
        }
    }
    virtual void wait(std::chrono::milliseconds duration) override{
        m_scope.wait_for(duration);
    }
    virtual bool screen(const std::function<void(const ImageViewRGB32&)>& use) override{
        //  A picture that came after what was done: the stream is a tenth of
        //  a second behind at most.
        QImage picture;
        quint64 serial = 0;
        m_video.latest(picture, &serial);
        if (!m_video.wait_newer(picture, serial, 1500) && !m_video.latest(picture)){
            return false;
        }
        const ImageRGB32 frame = QImage_to_ImageRGB32(picture);
        use(frame);
        return true;
    }
    virtual std::string read_text(const ImageViewRGB32& picture) override{
        return OCR::ocr_read(m_language, picture, OCR::PageSegMode::AUTO);
    }

    //  Touches (x, y) of the GamePad's screen for "duration".
    void touch(int x, int y, std::chrono::milliseconds duration){
        m_bridge.command("TOUCH " + QString::number(x) + " " + QString::number(y));
        try{
            m_scope.wait_for(duration);
        }catch (...){
            m_bridge.release_quietly();
            throw;
        }
        m_bridge.command("TOUCH OFF");
    }

private:
    //  The names of the layout as the bridge has them.
    static QString bridge_button(const std::string& name){
        if (name == "LSTICK"){
            return "L3";
        }
        if (name == "RSTICK"){
            return "R3";
        }
        return QString::fromStdString(name);
    }
    void set_stick(const char* axis, double value){
        const int v = (int)std::lround(std::clamp(value, -1.0, 1.0) * 32767.0);
        m_bridge.command(QString("AXIS ") + axis + " " + QString::number(v));
    }

    CancellableScope& m_scope;
    Bridge& m_bridge;
    MobileVideo& m_video;
    const Language m_language;
};


//  The tools of any game, and a touch on the GamePad's screen.
class WiiUGame : public Game{
public:
    WiiUGame(WiiUConsole& console, GameFacts facts, AnyGameOptions options)
        : m_console(console)
        , m_options(options)
        , m_any(console, std::move(facts), options)
    {}

    virtual std::vector<PlayTool> tools() const override{
        std::vector<PlayTool> list = m_any.tools();
        PlayTool touch;
        touch.name = "touch";
        touch.description =
            "Touches the GamePad's touch screen at a point and lets go. x and y are pixels of a picture of the "
            "whole screen as \"look\" sends it (" + std::to_string(m_options.picture_width) + " x " +
            std::to_string(m_options.picture_height) + ", 0, 0 at the top left). ms: how long, 50 to 3000 "
            "(100 when left out). The GamePad's screen is the picture you see.";
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
            "\n\nThe pictures are of the Wii U GamePad's own screen (854 x 480). Some games show something else on "
            "the TV: what you see is what the GamePad shows. Many Wii U games are played with the touch screen "
            "too (menus, maps): use the tool \"touch\" for it.";
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
        int gx = 0;
        int gy = 0;
        touch_point(x, y, m_options.picture_width, m_options.picture_height, gx, gy);
        m_console.touch(gx, gy, std::chrono::milliseconds(ms));
        result.text = "Touched (" + std::to_string(x) + ", " + std::to_string(y) + ") for " + std::to_string(ms) +
            " ms. Look to see what it did.";
        return result;
    }

private:
    WiiUConsole& m_console;
    const AnyGameOptions m_options;
    AnyGame m_any;
};


class WiiUHost : public Host{
public:
    WiiUHost(ProgramEnvironment& env, CancellableScope& scope)
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
    "<b>Experimental:</b> new, and not tried on a Wii U yet: tell us how it goes (the issue \"Wii U: testers "
    "wanted\" on GitHub). ";

const std::string NEEDS =
    "<b>What it needs:</b> a Raspberry Pi with a USB Wi-Fi adapter that does 5 GHz (one that Vanilla lists as "
    "working), near the Wii U, running vanilla-pipe and claudegg-wiiu-bridge (the steps are in "
    "WiiU/vanilla-bridge/README.md), and its address under \"Wii U, address of the Raspberry Pi\" in the settings. "
    "The Wii U then takes the Pi as its GamePad: the real GamePad must be off, and is paired again with the "
    "SYNC button when you want it back.";


//  ---- Connect the GamePad

class ConnectProgram_Descriptor : public ComputerProgramDescriptor{
public:
    ConnectProgram_Descriptor()
        : ComputerProgramDescriptor(
            "ClaudeGG:WiiUConnect",
            WIIU_LIST_NAME, "Connect the GamePad",
            "",
            "Pairs the Raspberry Pi with the Wii U as its GamePad, connects, and checks the picture and a button.",
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
            "<b>What it does:</b> the first time, press the red SYNC button on the Wii U (or pick the GamePad "
            "pairing in its settings): the TV shows four symbols. Type them below and start. The Pi is paired, "
            "connects, and a picture of the GamePad's screen is saved. After that, leave the symbols empty: it "
            "only connects and checks."
        )
        , SYNC_CODE(
            false,
            "<b>The four symbols (only to pair):</b><br>As letters: S spade, H heart, D diamond, C club, from left "
            "to right, for example SHDC. Empty: the Pi was paired before.",
            LockMode::LOCK_WHILE_RUNNING,
            "", "SHDC"
        )
        , PRESS_HOME(
            "<b>Press HOME as a test:</b><br>When connected, the program presses HOME once: the Wii U's HOME "
            "menu should open on the GamePad's screen. Off: no button is pressed.",
            LockMode::LOCK_WHILE_RUNNING,
            false
        )
        , SAVE_PICTURE(
            "<b>Save a picture of the GamePad's screen</b> in the folder WiiU of the program's user files.",
            LockMode::LOCK_WHILE_RUNNING,
            true
        )
    {
        PA_ADD_OPTION(SETUP_TEXT);
        PA_ADD_OPTION(SYNC_CODE);
        PA_ADD_OPTION(PRESS_HOME);
        PA_ADD_OPTION(SAVE_PICTURE);
    }

    virtual std::string check_validity() const override{
        const std::string typed = SYNC_CODE;
        if (!typed.empty() && sync_code_of(typed).empty()){
            return "The symbols are four of S, H, D and C (spade, heart, diamond, club), like SHDC.";
        }
        return std::string();
    }

    virtual void program(ProgramEnvironment& env, CancellableScope& scope) override{
        env.log(PROGRAM_NAME + " build " + PROGRAM_BUILD + " (Wii U: Connect the GamePad, experimental)", COLOR_BLUE);
        Bridge bridge(env.logger(), bridge_host());
        bridge.open();
        env.log("The bridge answers at " + bridge.where() + ".");

        const std::string code = sync_code_of(SYNC_CODE);
        if (!code.empty()){
            env.log("Pairing with the symbols " + code + "...", COLOR_BLUE);
            bridge.command(QString::fromStdString("SYNC " + code));
            const QString event = bridge.wait_event(scope, {"EVENT SYNCED"}, 120);
            if (event.isEmpty()){
                throw OperationFailedException(
                    ErrorReportMode::NO_ERROR_REPORT,
                    "No pairing within two minutes. Were the symbols still on the TV? (They change with each press of SYNC.)"
                );
            }
            if (event.startsWith("EVENT ERROR")){
                throw OperationFailedException(
                    ErrorReportMode::NO_ERROR_REPORT,
                    "The pairing failed (" + event.toStdString() + "). -202 is a wrong code or a code that ran out: "
                    "press SYNC again and type the new symbols."
                );
            }
            env.log("Paired: the Pi is the Wii U's GamePad now.", COLOR_BLUE);
        }

        make_connected(env, scope, bridge);

        MobileVideo video(bridge_host(), BRIDGE_PICTURE_PORT, QString(), 10, GAMEPAD_WIDTH);
        video.start();
        QImage picture;
        const bool got = video.wait_newer(picture, 0, 15000);
        const QString video_error = video.error();
        video.stop();
        if (!got){
            throw OperationFailedException(
                ErrorReportMode::NO_ERROR_REPORT,
                "Connected, but no picture of the GamePad's screen came in 15 seconds" +
                (video_error.isEmpty() ? std::string() : " (" + video_error.toStdString() + ")") +
                ". Is ffmpeg installed on the Pi (sudo apt install ffmpeg)?"
            );
        }
        env.log("The picture works: " + std::to_string(picture.width()) + " x " + std::to_string(picture.height()) + ".", COLOR_BLUE);
        if (SAVE_PICTURE){
            const QString folder = QString::fromStdString(USER_FILE_PATH()) + "WiiU/";
            QDir().mkpath(folder);
            const QString file = folder + "GamePad-" + QDateTime::currentDateTime().toString("yyyyMMdd-HHmmss") + ".png";
            if (picture.save(file)){
                env.log("Saved " + file.toStdString() + ".");
            }else{
                env.log("Could not save " + file.toStdString() + ".", COLOR_ORANGE);
            }
        }

        if (PRESS_HOME){
            env.log("Pressing HOME...");
            bridge.command("BTN HOME 1");
            scope.wait_for(std::chrono::milliseconds(150));
            bridge.command("BTN HOME 0");
            env.log("Pressed HOME: the HOME menu should be on the GamePad's screen now.");
        }

        env.log("The GamePad works. Claude Plays (Wii U) can play now.", COLOR_GREEN);
    }

private:
    StaticTextOption SETUP_TEXT;
    StringOption SYNC_CODE;
    BooleanCheckBoxOption PRESS_HOME;
    BooleanCheckBoxOption SAVE_PICTURE;
};

std::unique_ptr<ComputerProgramInstance> ConnectProgram_Descriptor::make_instance() const{
    return std::make_unique<ConnectProgram>();
}


//  ---- Claude Plays

enum class Picture{
    SMALL,
    NORMAL,
    LARGE,
};

class PlayProgram_Descriptor : public ComputerProgramDescriptor{
public:
    PlayProgram_Descriptor()
        : ComputerProgramDescriptor(
            "ClaudeGG:WiiUClaudePlays",
            WIIU_LIST_NAME, "Claude Plays",
            "",
            "Claude plays the game on the Wii U toward a goal you give it: it looks at the GamePad's screen and "
            "works its buttons, sticks and touch screen.",
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
            "small pictures of the GamePad's screen and the text the program reads from it, and works the GamePad: "
            "buttons pressed, buttons and sticks held, a button mashed, the touch screen touched. It sees the "
            "GamePad, not the TV: in a game that shows the game on the TV only, switch it to play on the GamePad "
            "where the game has that.<br>"
            "<b>Who pays:</b> with \"The program asks Claude\", your Claude API key in the panel \"Claude\" (each "
            "request is billed to you by Anthropic, and the pictures go to Anthropic). Without a key: let Claude "
            "Code play (see \"Who plays\").<br>" + NEEDS + " Run \"Connect the GamePad\" once first."
        )
        , WHO()
        , GOAL(
            "<b>Goal:</b><br>What Claude should do, in your own words (any language). Say where the game is at, if "
            "that helps, and when the goal is reached. (Not used when Claude Code plays: give the goal to Claude Code.)",
            LockMode::LOCK_WHILE_RUNNING,
            "Look at the screen and say which game it shows, where it is at and what could be done from here. "
            "Do not press anything.",
            "For example: Open the map on the GamePad and tell me where the player is."
        )
        , ABOUT(
            "<b>About the game (optional):</b><br>Which game it is and what Claude should know about it: its "
            "controls, where the save is, what to stay away from. Without it Claude finds out from the screen.",
            LockMode::LOCK_WHILE_RUNNING,
            "",
            "For example: Mario Kart 8. The race is played on the GamePad's screen."
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
            "<b>Pictures for Claude:</b><br>Of the whole GamePad screen. Larger pictures show more and cost more "
            "tokens each.",
            {
                {Picture::SMALL,    "small",    "427 x 240 (about 137 tokens a picture)"},
                {Picture::NORMAL,   "normal",   "640 x 360 (about 299 tokens)"},
                {Picture::LARGE,    "large",    "854 x 480 (about 547 tokens, the GamePad's own size)"},
            },
            LockMode::LOCK_WHILE_RUNNING,
            Picture::NORMAL
        )
        , ALLOW_HOME(
            "<b>Claude may press HOME:</b><br>HOME leaves the game for the Wii U's HOME menu. Off: the program "
            "does not press it, whatever Claude asks for.",
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
        env.log(PROGRAM_NAME + " build " + PROGRAM_BUILD + " (Wii U: Claude Plays, experimental)", COLOR_BLUE);

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

        AnyGameOptions options;
        switch ((Picture)PICTURE){
        case Picture::SMALL:
            options.picture_width = 427;
            options.picture_height = 240;
            break;
        case Picture::NORMAL:
            options.picture_width = 640;
            options.picture_height = 360;
            break;
        case Picture::LARGE:
            options.picture_width = GAMEPAD_WIDTH;
            options.picture_height = GAMEPAD_HEIGHT;
            break;
        }
        options.allow_home = ALLOW_HOME;
        options.external = external;
        //  How presses are played and how late the picture comes, over Wi-Fi
        //  (ClaudePlays_Consoles.cpp).
        {
            const ConsoleTraits traits = console_traits("wiiu");
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
            "The console is a Wii U, played through its GamePad. Wii U games use A, B, X, Y, L, R, ZL, ZR, PLUS "
            "(often the pause or start menu), MINUS, the two sticks, the d-pad and the touch screen.";
        facts.user_notes = trimmed(ABOUT);
        const Language text_language = TEXT_LANGUAGE;
        if (text_language != Language::English){
            facts.text_language = language_data(text_language).name;
        }

        Limits limits;
        limits.max_actions = (uint64_t)(uint32_t)MAX_ACTIONS;
        limits.max_cost = MAX_COST;
        const Model model = MODEL;

        Bridge bridge(env.logger(), bridge_host());
        bridge.open();
        make_connected(env, scope, bridge);

        MobileVideo video(bridge_host(), BRIDGE_PICTURE_PORT, QString(), 10, GAMEPAD_WIDTH);
        video.start();
        try{
            QImage first;
            if (!video.wait_newer(first, 0, 15000)){
                const QString error = video.error();
                throw OperationFailedException(
                    ErrorReportMode::NO_ERROR_REPORT,
                    "No picture of the GamePad's screen came in 15 seconds" +
                    (error.isEmpty() ? std::string() : " (" + error.toStdString() + ")") + "."
                );
            }

            WiiUConsole console(scope, bridge, video, text_language);
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
            WiiUGame game(console, facts, options);
            WiiUHost host(env, scope);
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
        }catch (...){
            bridge.release_quietly();
            video.stop();
            throw;
        }
        bridge.release_quietly();
        video.stop();
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



WiiUList::WiiUList()
    : PanelListDescriptor(WIIU_LIST_NAME)
{
    m_icon = QImage_to_ImageRGB32(make_game_card(WIIU_LIST_NAME, qRgb(0x1f, 0x8f, 0xc4)));
}

std::vector<PanelEntry> WiiUList::make_panels() const{
    std::vector<PanelEntry> ret;
    ret.emplace_back("---- Nintendo Wii U (experimental) ----");
    ret.emplace_back(std::make_unique<ConnectProgram_Descriptor>());
    ret.emplace_back(std::make_unique<PlayProgram_Descriptor>());
    return ret;
}

size_t wiiu_program_count(){
    return 2;
}



}
}
}
