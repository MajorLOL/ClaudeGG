/*  Claude GG Nintendo 3DS (Luma3DS InputRedirection and NTR-HR over Wi-Fi)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
#include <QByteArray>
#include <QDateTime>
#include <QDir>
#include <QElapsedTimer>
#include <QHostAddress>
#include <QImage>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPainter>
#include <QString>
#include <QTcpSocket>
#include <QTransform>
#include <QUdpSocket>
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
#include "ClaudePlays/ClaudePlays_Engine.h"
#include "ClaudePlays/ClaudePlays_External.h"
#include "ClaudePlays/ClaudePlays_GameCard.h"
#include "ClaudeGG_3DS.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace ThreeDS{

using namespace ClaudePlays;


const char* const LIST_NAME = "Nintendo 3DS";


namespace{

void put_u32(QByteArray& data, qsizetype at, uint32_t value){
    for (int b = 0; b < 4; b++){
        data[at + b] = (char)((value >> (8 * b)) & 0xff);
    }
}

uint32_t clamp_u32(double value, double low, double high){
    return (uint32_t)std::clamp(value, low, high);
}

}


QByteArray input_packet(const PadState& state){
    //  The buttons of the HID pad, held when their bit is 0.
    static const struct{
        const char* name;
        uint32_t bit;
    } PAD[] = {
        {"A", 0}, {"B", 1}, {"SELECT", 2}, {"START", 3}, {"RIGHT", 4}, {"LEFT", 5}, {"UP", 6}, {"DOWN", 7},
        {"R", 8}, {"L", 9}, {"X", 10}, {"Y", 11},
    };
    uint32_t pad = 0xfff;
    uint32_t extra = 0;     //  ZR and ZL, next to the C-stick
    uint32_t special = 0;   //  HOME
    for (const std::string& name : state.buttons){
        for (const auto& button : PAD){
            if (name == button.name){
                pad &= ~(1u << button.bit);
            }
        }
        if (name == "ZR"){
            extra |= 0x2;
        }else if (name == "ZL"){
            extra |= 0x4;
        }else if (name == "HOME"){
            special |= 0x1;
        }
    }

    uint32_t touch = 0x02000000;
    if (state.touch_x >= 0 && state.touch_y >= 0){
        const uint32_t x = clamp_u32((double)std::lround(0xfff * std::clamp(state.touch_x, 0, BOTTOM_WIDTH) / (double)BOTTOM_WIDTH), 0, 0xfff);
        const uint32_t y = clamp_u32((double)std::lround(0xfff * std::clamp(state.touch_y, 0, BOTTOM_HEIGHT) / (double)BOTTOM_HEIGHT), 0, 0xfff);
        touch = (1u << 24) | (y << 12) | x;
    }

    //  The circle pad: 0x800 in the middle, 0x5d0 to each side.
    const uint32_t cx = clamp_u32(std::clamp(state.circle_x, -1.0, 1.0) * 0x5d0 + 0x800, 0, 0xfff);
    const uint32_t cy = clamp_u32(std::clamp(state.circle_y, -1.0, 1.0) * 0x5d0 + 0x800, 0, 0xfff);
    const uint32_t circle = (state.circle_x == 0 && state.circle_y == 0) ? 0x007ff7ff : ((cy << 12) | cx);

    //  The C-stick, turned by 45 degrees as the console reads it.
    const double rx = std::clamp(state.cstick_x, -1.0, 1.0);
    const double ry = std::clamp(state.cstick_y, -1.0, 1.0);
    const uint32_t sx = clamp_u32((double)std::lround(0.70710678 * (rx + ry) * 0x7f + 0x80), 0, 0xff);
    const uint32_t sy = clamp_u32((double)std::lround(0.70710678 * (ry - rx) * 0x7f + 0x80), 0, 0xff);
    const uint32_t cstick = (sy << 24) | (sx << 16) | (extra << 8) | 0x81;

    QByteArray data(20, '\0');
    put_u32(data, 0, pad);
    put_u32(data, 4, touch);
    put_u32(data, 8, circle);
    put_u32(data, 12, cstick);
    put_u32(data, 16, special);
    return data;
}

namespace{
QByteArray ntr_packet(uint32_t sequence, uint32_t command, const std::vector<uint32_t>& args){
    QByteArray data(84, '\0');
    put_u32(data, 0, 0x12345678);
    put_u32(data, 4, sequence);
    put_u32(data, 8, 0);
    put_u32(data, 12, command);
    for (size_t c = 0; c < args.size() && c < 16; c++){
        put_u32(data, 16 + 4 * (qsizetype)c, args[c]);
    }
    put_u32(data, 80, 0);
    return data;
}
}

QByteArray ntr_start_packet(bool top, int priority, int quality, int qos){
    const uint32_t factor = (uint32_t)std::clamp(priority, 1, 255);
    const uint32_t q = (uint32_t)std::clamp(quality, 10, 100);
    const uint32_t bandwidth = (uint32_t)std::clamp(qos, 1, 105);
    return ntr_packet(3000, 901, {((top ? 1u : 0u) << 8) | factor, q, (bandwidth * 2) << 16});
}

QByteArray ntr_heartbeat_packet(uint32_t sequence){
    return ntr_packet(sequence, 0, {});
}


bool FrameAssembler::add(const char* data, size_t size, bool& top, QByteArray& jpeg){
    if (size < 4){
        return false;
    }
    const uint8_t frame = (uint8_t)data[0];
    const uint8_t flags = (uint8_t)data[1];
    const uint8_t index = (uint8_t)data[3];
    const bool is_top = (flags & 0x0f) == 1;
    const bool last = ((flags & 0xf0) >> 4) == 1;
    Partial& partial = m_screens[is_top ? 1 : 0];
    if (index == 0){
        partial.active = true;
        partial.frame = frame;
        partial.next = 0;
        partial.bytes.clear();
    }else if (!partial.active || partial.frame != frame || partial.next != index){
        //  A piece is missing: the picture is left out.
        partial.active = false;
        return false;
    }
    partial.bytes.append(data + 4, (qsizetype)(size - 4));
    partial.next = (uint8_t)(index + 1);
    if (!last){
        return false;
    }
    partial.active = false;
    if (partial.bytes.size() < 4 || !partial.bytes.endsWith(QByteArray("\xff\xd9", 2))){
        return false;
    }
    top = is_top;
    jpeg = partial.bytes;
    return true;
}

QImage upright(const QImage& raw){
    if (raw.isNull() || raw.width() >= raw.height()){
        return raw;
    }
    return raw.transformed(QTransform().rotate(-90));
}

QImage both_screens(const QImage& top, const QImage& bottom){
    QImage out(TOP_WIDTH, TOP_HEIGHT + BOTTOM_HEIGHT, QImage::Format_RGB32);
    out.fill(Qt::black);
    QPainter p(&out);
    if (!top.isNull()){
        p.drawImage(QRect(0, 0, TOP_WIDTH, TOP_HEIGHT), top);
    }
    if (!bottom.isNull()){
        p.drawImage(QRect((TOP_WIDTH - BOTTOM_WIDTH) / 2, TOP_HEIGHT, BOTTOM_WIDTH, BOTTOM_HEIGHT), bottom);
    }
    p.end();
    return out;
}

bool touch_point(int x, int y, int width, int height, int& screen_x, int& screen_y){
    if (width <= 0 || height <= 0){
        return false;
    }
    const double fx = (double)x * TOP_WIDTH / width;
    const double fy = (double)y * (TOP_HEIGHT + BOTTOM_HEIGHT) / height;
    const double left = (TOP_WIDTH - BOTTOM_WIDTH) / 2.0;
    if (fy < TOP_HEIGHT || fx < left || fx >= left + BOTTOM_WIDTH){
        return false;
    }
    screen_x = std::clamp((int)std::lround(fx - left), 0, BOTTOM_WIDTH - 1);
    screen_y = std::clamp((int)std::lround(fy - TOP_HEIGHT), 0, BOTTOM_HEIGHT - 1);
    return true;
}


namespace{


QString console_host(){
    return QString::fromStdString(std::string(GlobalSettings::instance().N3DS_HOST)).trimmed();
}

void check_host(Logger& logger, const QString& host){
    if (host.isEmpty()){
        throw UserSetupError(
            logger,
            "The address of the 3DS is not set: fill in \"Nintendo 3DS, address\" in the settings (the Rosalina "
            "menu of Luma3DS shows it under Misc. settings, InputRedirection)."
        );
    }
}


//  The buttons, over UDP to InputRedirection.
class Pad{
public:
    explicit Pad(const QString& host)
        : m_host(QHostAddress(host))
    {}

    bool valid() const{
        return !m_host.isNull();
    }
    void send(const PadState& state){
        const QByteArray data = input_packet(state);
        (void)m_socket.writeDatagram(data, m_host, (quint16)INPUT_PORT);
    }
    //  Holds "state" for "duration", sent again every 50 ms (UDP can lose a
    //  packet), then lets go.
    void hold(CancellableScope& scope, const PadState& state, std::chrono::milliseconds duration){
        const auto end = std::chrono::steady_clock::now() + duration;
        try{
            for (;;){
                send(state);
                const auto left = std::chrono::duration_cast<std::chrono::milliseconds>(end - std::chrono::steady_clock::now());
                if (left.count() <= 0){
                    break;
                }
                scope.wait_for(std::min(left, std::chrono::milliseconds(50)));
            }
        }catch (...){
            release();
            throw;
        }
        release();
    }
    void release(){
        const PadState none;
        for (int c = 0; c < 3; c++){
            send(none);
        }
    }

private:
    QHostAddress m_host;
    QUdpSocket m_socket;
};


//  NTR's stream: the command that starts it, and the pictures of both
//  screens as they come, on a thread of its own.
class Stream{
public:
    Stream(QString host, int quality, bool top_first)
        : m_host(std::move(host))
        , m_quality(quality)
        , m_top_first(top_first)
    {}
    ~Stream(){
        stop();
    }

    void start(){
        m_stop = false;
        m_thread = std::thread([this]{ run(); });
    }
    void stop(){
        m_stop = true;
        if (m_thread.joinable()){
            m_thread.join();
        }
    }

    //  The latest pictures (upright), and how many have come.
    uint64_t latest(QImage& top, QImage& bottom) const{
        std::lock_guard<std::mutex> lg(m_lock);
        top = m_top;
        bottom = m_bottom;
        return m_count;
    }
    //  Waits up to "msec" for a picture after "count".
    bool wait_newer(uint64_t count, int msec) const{
        QElapsedTimer timer;
        timer.start();
        while (timer.elapsed() < msec){
            {
                std::lock_guard<std::mutex> lg(m_lock);
                if (m_count > count){
                    return true;
                }
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        return false;
    }
    QString error() const{
        std::lock_guard<std::mutex> lg(m_lock);
        return m_error;
    }

private:
    void set_error(const QString& error){
        std::lock_guard<std::mutex> lg(m_lock);
        m_error = error;
    }
    //  Sends the command that starts the stream. The TCP connection stays
    //  open, for the heartbeat.
    bool open_control(QTcpSocket& control){
        control.abort();
        control.connectToHost(m_host, (quint16)NTR_PORT);
        if (!control.waitForConnected(5000)){
            set_error("NTR does not answer at " + m_host + ":" + QString::number(NTR_PORT) + " (" + control.errorString() + ")");
            return false;
        }
        const QByteArray start = ntr_start_packet(m_top_first, 5, m_quality, 105);
        (void)control.write(start);
        (void)control.waitForBytesWritten(2000);
        return true;
    }

    void run(){
        QUdpSocket video;
        if (!video.bind(QHostAddress::AnyIPv4, (quint16)STREAM_PORT)){
            set_error("UDP port " + QString::number(STREAM_PORT) + " of this computer is taken (" + video.errorString() + "): close other 3DS viewers");
            return;
        }
        QTcpSocket control;
        if (!open_control(control)){
            return;
        }
        FrameAssembler assembler;
        QElapsedTimer since_picture;
        since_picture.start();
        QElapsedTimer since_heartbeat;
        since_heartbeat.start();
        bool reconnected = false;
        uint32_t sequence = 1;
        std::vector<char> buffer(2048);
        while (!m_stop){
            if (video.hasPendingDatagrams() || video.waitForReadyRead(100)){
                while (video.hasPendingDatagrams()){
                    const qint64 size = video.readDatagram(buffer.data(), (qint64)buffer.size());
                    bool top = false;
                    QByteArray jpeg;
                    if (size > 0 && assembler.add(buffer.data(), (size_t)size, top, jpeg)){
                        const QImage raw = QImage::fromData(jpeg, "JPEG");
                        if (!raw.isNull()){
                            const QImage picture = upright(raw);
                            std::lock_guard<std::mutex> lg(m_lock);
                            (top ? m_top : m_bottom) = picture;
                            m_count++;
                            m_error.clear();
                            (void)since_picture.restart();
                        }
                    }
                }
            }
            //  As the older viewers do: when nothing comes, connect again
            //  once (some versions of NTR start only then).
            if (!reconnected && since_picture.elapsed() > 3000){
                reconnected = true;
                (void)open_control(control);
            }
            //  The heartbeat, every two seconds; its answer is NTR's log.
            if (since_heartbeat.elapsed() > 2000 && control.state() == QAbstractSocket::ConnectedState){
                (void)since_heartbeat.restart();
                (void)control.write(ntr_heartbeat_packet(sequence++));
                (void)control.waitForBytesWritten(500);
                (void)control.readAll();
            }
        }
        control.abort();
    }

    const QString m_host;
    const int m_quality;
    const bool m_top_first;
    std::atomic<bool> m_stop{false};
    std::thread m_thread;
    mutable std::mutex m_lock;
    QImage m_top;
    QImage m_bottom;
    uint64_t m_count = 0;
    QString m_error;
};


//  Waits for the first pictures of both screens, or throws.
void wait_for_pictures(Stream& stream, int msec){
    QElapsedTimer timer;
    timer.start();
    while (timer.elapsed() < msec){
        QImage top;
        QImage bottom;
        stream.latest(top, bottom);
        if (!top.isNull() && !bottom.isNull()){
            return;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    const QString error = stream.error();
    throw OperationFailedException(
        ErrorReportMode::NO_ERROR_REPORT,
        "No picture of both screens came from NTR-HR in " + std::to_string(msec / 1000) + " seconds" +
        (error.isEmpty() ? std::string() : " (" + error.toStdString() + ")") +
        ". Is NTR-HR started on the 3DS (BootNTR Selector), is the address right, and does the firewall of this "
        "computer let UDP port 8001 in?"
    );
}


//  The 3DS, worked through InputRedirection, and both its screens.
class ThreeDSConsole : public PlayConsole{
public:
    ThreeDSConsole(CancellableScope& scope, Pad& pad, Stream& stream, Language language)
        : m_scope(scope)
        , m_pad(pad)
        , m_stream(stream)
        , m_language(language)
    {}

    static const PadLayout& pad_layout(){
        static const PadLayout layout{
            "a Nintendo 3DS (the program works it over the network through Luma3DS; its lower screen is a "
            "touch screen too, see the tool \"touch\"; ZL, ZR and the C-stick are on a New 3DS only)",
            {
                "A", "B", "X", "Y", "L", "R", "ZL", "ZR", "START", "SELECT",
                "UP", "DOWN", "LEFT", "RIGHT",
            },
            {"left_stick", "right_stick"},
            false,
            "a real Nintendo 3DS",
            "On a 3DS, A is usually yes and B usually no or back.",
            true,
        };
        return layout;
    }

    virtual const PadLayout& layout() const override{
        return pad_layout();
    }
    virtual void hold(const PadInput& input, std::chrono::milliseconds duration) override{
        PadState state;
        state.buttons = input.buttons;
        state.circle_x = input.stick_x;
        state.circle_y = input.stick_y;
        state.cstick_x = input.stick2_x;
        state.cstick_y = input.stick2_y;
        m_pad.hold(m_scope, state, duration);
    }
    virtual void mash(const std::string& name, std::chrono::milliseconds duration) override{
        PadState state;
        state.buttons = {name};
        const auto end = std::chrono::steady_clock::now() + duration;
        while (std::chrono::steady_clock::now() < end){
            m_pad.hold(m_scope, state, std::chrono::milliseconds(60));
            m_scope.wait_for(std::chrono::milliseconds(60));
        }
    }
    virtual void wait(std::chrono::milliseconds duration) override{
        m_scope.wait_for(duration);
    }
    virtual bool screen(const std::function<void(const ImageViewRGB32&)>& use) override{
        //  A picture that came after what was done.
        QImage top;
        QImage bottom;
        const uint64_t count = m_stream.latest(top, bottom);
        m_stream.wait_newer(count, 1000);
        m_stream.latest(top, bottom);
        if (top.isNull() && bottom.isNull()){
            return false;
        }
        const ImageRGB32 frame = QImage_to_ImageRGB32(both_screens(top, bottom));
        use(frame);
        return true;
    }
    virtual std::string read_text(const ImageViewRGB32& picture) override{
        return OCR::ocr_read(m_language, picture, OCR::PageSegMode::AUTO);
    }

    void touch(int x, int y, std::chrono::milliseconds duration){
        PadState state;
        state.touch_x = x;
        state.touch_y = y;
        m_pad.hold(m_scope, state, duration);
    }

private:
    CancellableScope& m_scope;
    Pad& m_pad;
    Stream& m_stream;
    const Language m_language;
};


//  The tools of any game, and a touch on the lower screen.
class ThreeDSGame : public Game{
public:
    ThreeDSGame(ThreeDSConsole& console, GameFacts facts, AnyGameOptions options)
        : m_console(console)
        , m_options(options)
        , m_any(console, std::move(facts), options)
    {}

    virtual std::vector<PlayTool> tools() const override{
        std::vector<PlayTool> list = m_any.tools();
        PlayTool touch;
        touch.name = "touch";
        touch.description =
            "Touches the 3DS's lower screen (the touch screen) at a point and lets go. x and y are pixels of a "
            "picture of both screens as \"look\" sends it (" + std::to_string(m_options.picture_width) + " x " +
            std::to_string(m_options.picture_height) + ", 0, 0 at the top left): the top screen is the upper "
            "half, the lower screen is the lower half, with black on its left and right. Only a point on the "
            "lower screen can be touched. ms: how long, 50 to 3000 (100 when left out).";
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
            "\n\nThe pictures show both screens of the 3DS: the top screen above, the lower screen (a touch "
            "screen) below it, narrower, with black on both sides. Many 3DS games have their menus or a map on "
            "the lower screen: use the tool \"touch\" for it.";
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
        int sx = 0;
        int sy = 0;
        if (!touch_point(x, y, m_options.picture_width, m_options.picture_height, sx, sy)){
            result.is_error = true;
            result.text = "That point is not on the lower screen: it is the lower half of the picture, from x = " +
                std::to_string(m_options.picture_width * (TOP_WIDTH - BOTTOM_WIDTH) / 2 / TOP_WIDTH) + " to " +
                std::to_string(m_options.picture_width * (TOP_WIDTH + BOTTOM_WIDTH) / 2 / TOP_WIDTH - 1) + ".";
            return result;
        }
        const int ms = std::clamp(input.contains("ms") ? input.value("ms").toInt() : 100, 50, 3000);
        m_console.touch(sx, sy, std::chrono::milliseconds(ms));
        result.text = "Touched (" + std::to_string(x) + ", " + std::to_string(y) + ") for " + std::to_string(ms) +
            " ms. Look to see what it did.";
        return result;
    }

private:
    ThreeDSConsole& m_console;
    const AnyGameOptions m_options;
    AnyGame m_any;
};


class ThreeDSHost : public Host{
public:
    ThreeDSHost(ProgramEnvironment& env, CancellableScope& scope)
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
    "<b>Experimental:</b> new, and not tried on a 3DS yet: tell us how it goes. ";

const std::string NEEDS =
    "<b>What it needs:</b> a 3DS with Luma3DS (a New 3DS or New 2DS is best: on the older ones the picture comes "
    "at a few frames a second). For the buttons, turn on InputRedirection in the Rosalina menu (L, DOWN and "
    "SELECT, then Misc. settings). For the picture, <a href=\"https://github.com/xzn/ntr-hr\">NTR-HR</a> "
    "(GPL-2.0, a separate project), started with BootNTR Selector. Then the 3DS's address under \"Nintendo 3DS, "
    "address\" in the settings. The 3DS and the computer on the same home network, and the firewall of this "
    "computer letting UDP port 8001 in (Windows asks the first time). Close other 3DS viewers: only one program "
    "can take the stream.";

std::string save_picture(const QImage& picture){
    const QString folder = QString::fromStdString(USER_FILE_PATH()) + "3DS/";
    QDir().mkpath(folder);
    const QString file = folder + "3DS-" + QDateTime::currentDateTime().toString("yyyyMMdd-HHmmss") + ".png";
    return picture.save(file) ? file.toStdString() : std::string();
}


//  ---- Connect the 3DS

class ConnectProgram_Descriptor : public ComputerProgramDescriptor{
public:
    ConnectProgram_Descriptor()
        : ComputerProgramDescriptor(
            "ClaudeGG:3DSConnect",
            LIST_NAME, "Connect the 3DS",
            "",
            "Starts the picture of NTR-HR, saves a picture of both screens, and can press a button as a test.",
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
            "<b>What it does:</b> starts the stream of NTR-HR, waits for a picture of both screens and saves it. "
            "If wanted, it presses HOME through InputRedirection: the HOME menu should open."
        )
        , QUALITY(
            "<b>Picture quality (10 to 100):</b><br>Of the JPEG pictures of NTR-HR. Lower is quicker over Wi-Fi.",
            LockMode::LOCK_WHILE_RUNNING,
            75, 10, 100
        )
        , PRESS_HOME(
            "<b>Press HOME as a test:</b><br>The program presses HOME once: the 3DS should show its HOME menu. "
            "Off: nothing is pressed.",
            LockMode::LOCK_WHILE_RUNNING,
            false
        )
        , SAVE_PICTURE(
            "<b>Save a picture of both screens</b> in the folder 3DS of the program's user files.",
            LockMode::LOCK_WHILE_RUNNING,
            true
        )
    {
        PA_ADD_OPTION(SETUP_TEXT);
        PA_ADD_OPTION(QUALITY);
        PA_ADD_OPTION(PRESS_HOME);
        PA_ADD_OPTION(SAVE_PICTURE);
    }

    virtual void program(ProgramEnvironment& env, CancellableScope& scope) override{
        env.log(PROGRAM_NAME + " build " + PROGRAM_BUILD + " (Nintendo 3DS: Connect the 3DS, experimental)", COLOR_BLUE);
        const QString host = console_host();
        check_host(env.logger(), host);
        Pad pad(host);
        if (!pad.valid()){
            throw UserSetupError(env.logger(), "\"Nintendo 3DS, address\" must be an address like 192.168.1.70, not a name.");
        }

        Stream stream(host, (int)(uint32_t)QUALITY, true);
        stream.start();
        QElapsedTimer timer;
        timer.start();
        wait_for_pictures(stream, 20000);
        QImage top;
        QImage bottom;
        const uint64_t count = stream.latest(top, bottom);
        env.log("The picture works: both screens came in " + std::to_string(timer.elapsed()) + " ms.", COLOR_BLUE);
        (void)timer.restart();
        scope.wait_for(std::chrono::seconds(2));
        QImage last_top;
        QImage last_bottom;
        const uint64_t later = stream.latest(last_top, last_bottom);
        env.log("About " + std::to_string((later - count) / 2) + " pictures a second came.", COLOR_BLUE);
        if (SAVE_PICTURE){
            const std::string file = save_picture(both_screens(last_top, last_bottom));
            env.log(file.empty() ? std::string("Could not save the picture.") : "Saved " + file + ".");
        }
        if (PRESS_HOME){
            env.log("Pressing HOME...");
            PadState state;
            state.buttons = {"HOME"};
            pad.hold(scope, state, std::chrono::milliseconds(200));
            env.log("Pressed HOME: the 3DS should show its HOME menu now. If not, is InputRedirection on in Rosalina?");
        }
        stream.stop();
        env.log("The 3DS works. Claude Plays (Nintendo 3DS) can play now.", COLOR_GREEN);
    }

private:
    StaticTextOption SETUP_TEXT;
    SimpleIntegerOption<uint32_t> QUALITY;
    BooleanCheckBoxOption PRESS_HOME;
    BooleanCheckBoxOption SAVE_PICTURE;
};

std::unique_ptr<ComputerProgramInstance> ConnectProgram_Descriptor::make_instance() const{
    return std::make_unique<ConnectProgram>();
}


//  ---- Claude Plays

class PlayProgram_Descriptor : public ComputerProgramDescriptor{
public:
    PlayProgram_Descriptor()
        : ComputerProgramDescriptor(
            "ClaudeGG:3DSClaudePlays",
            LIST_NAME, "Claude Plays",
            "",
            "Claude plays the game on the 3DS toward a goal you give it: it looks at both screens and works the "
            "buttons, the circle pad and the touch screen, over the network.",
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
            "pictures of both screens and the text the program reads from them, and works the 3DS: buttons "
            "pressed, buttons and sticks held, a button mashed, the lower screen touched.<br>"
            "<b>Who pays:</b> with \"The program asks Claude\", your Claude API key in the panel \"Claude\" (each "
            "request is billed to you by Anthropic, and the pictures go to Anthropic). Without a key: let Claude "
            "Code play (see \"Who plays\").<br>" + NEEDS + " Run \"Connect the 3DS\" once first."
        )
        , WHO()
        , GOAL(
            "<b>Goal:</b><br>What Claude should do, in your own words (any language). Say where the game is at, if "
            "that helps, and when the goal is reached. (Not used when Claude Code plays: give the goal to Claude Code.)",
            LockMode::LOCK_WHILE_RUNNING,
            "Look at the screens and say which game they show, where it is at and what could be done from here. "
            "Do not press anything.",
            "For example: Open the bag on the lower screen and tell me which items there are."
        )
        , ABOUT(
            "<b>About the game (optional):</b><br>Which game it is and what Claude should know about it: its "
            "controls, where the save is, what to stay away from. Without it Claude finds out from the screens.",
            LockMode::LOCK_WHILE_RUNNING,
            "",
            "For example: Pokemon Ultra Sun. The menu is X; the lower screen has the map."
        )
        , TEXT_LANGUAGE(
            "<b>Language of the text:</b><br>The language of the text in the game. The program reads text from the "
            "screens (the tool \"read_text\") in this language, and Claude is told which it is.",
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
        , QUALITY(
            "<b>Picture quality (10 to 100):</b><br>Of the JPEG pictures of NTR-HR. Lower is quicker over Wi-Fi.",
            LockMode::LOCK_WHILE_RUNNING,
            75, 10, 100
        )
        , ALLOW_HOME(
            "<b>Claude may press HOME:</b><br>HOME leaves the game for the 3DS's HOME menu. Off: the program does "
            "not press it, whatever Claude asks for.",
            LockMode::LOCK_WHILE_RUNNING,
            false
        )
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
        PA_ADD_OPTION(QUALITY);
        PA_ADD_OPTION(ALLOW_HOME);
    }

    virtual void program(ProgramEnvironment& env, CancellableScope& scope) override{
        env.log(PROGRAM_NAME + " build " + PROGRAM_BUILD + " (Nintendo 3DS: Claude Plays, experimental)", COLOR_BLUE);

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
        options.picture_width = TOP_WIDTH;
        options.picture_height = TOP_HEIGHT + BOTTOM_HEIGHT;
        options.allow_home = ALLOW_HOME;
        options.external = external;

        GameFacts facts;
        facts.notes =
            "The console is a Nintendo 3DS. 3DS games use A, B, X, Y, L, R, START (often the pause menu), SELECT, "
            "the circle pad, the d-pad and the lower screen as a touch screen; a New 3DS has ZL, ZR and a C-stick "
            "too (the right stick here).";
        facts.user_notes = trimmed(ABOUT);
        const Language text_language = TEXT_LANGUAGE;
        if (text_language != Language::English){
            facts.text_language = language_data(text_language).name;
        }

        Limits limits;
        limits.max_actions = (uint64_t)(uint32_t)MAX_ACTIONS;
        limits.max_cost = MAX_COST;
        const Model model = MODEL;

        const QString host = console_host();
        check_host(env.logger(), host);
        Pad pad(host);
        if (!pad.valid()){
            throw UserSetupError(env.logger(), "\"Nintendo 3DS, address\" must be an address like 192.168.1.70, not a name.");
        }
        Stream stream(host, (int)(uint32_t)QUALITY, true);
        stream.start();
        try{
            wait_for_pictures(stream, 20000);
            ThreeDSConsole console(scope, pad, stream, text_language);
            ThreeDSGame game(console, facts, options);
            ThreeDSHost host_of_play(env, scope);
            Ending ending;
            if (external){
                ending = serve_claude_code(env.logger(), host_of_play, game, WHO, limits);
            }else{
                PlaySession claude(make_setup(game, model));
                env.log(
                    std::string("Claude Plays: ") + model_id(model) + ", at most " + std::to_string(limits.max_actions) +
                    " actions" + (limits.max_cost > 0 ? ", at most about " + money(limits.max_cost) : std::string(", no cost limit")) +
                    ". Goal: " + one_line(goal, 300),
                    COLOR_BLUE
                );
                ending = play(host_of_play, game, claude, goal, limits);
                if (ending.failed){
                    throw OperationFailedException(ErrorReportMode::NO_ERROR_REPORT, ending.summary);
                }
            }
            env.log("Claude Plays: " + ending.summary, ending.reached ? COLOR_BLUE : COLOR_ORANGE);
        }catch (...){
            pad.release();
            stream.stop();
            throw;
        }
        pad.release();
        stream.stop();
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
    SimpleIntegerOption<uint32_t> QUALITY;
    BooleanCheckBoxOption ALLOW_HOME;
};

std::unique_ptr<ComputerProgramInstance> PlayProgram_Descriptor::make_instance() const{
    return std::make_unique<PlayProgram>();
}


}   //  namespace



ThreeDSList::ThreeDSList()
    : PanelListDescriptor(LIST_NAME)
{
    m_icon = QImage_to_ImageRGB32(make_game_card(LIST_NAME, qRgb(0xc8, 0x1e, 0x2c)));
}

std::vector<PanelEntry> ThreeDSList::make_panels() const{
    std::vector<PanelEntry> ret;
    ret.emplace_back("---- Nintendo 3DS (experimental) ----");
    ret.emplace_back(std::make_unique<ConnectProgram_Descriptor>());
    ret.emplace_back(std::make_unique<PlayProgram_Descriptor>());
    return ret;
}

size_t program_count(){
    return 2;
}



}
}
}
