/*  Claude GG Mobile (an Android phone, through a Raspberry Pi)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  For a Nintendo Switch the picture comes from a capture card and the buttons go
 *  through a board. For a phone the Raspberry Pi is both: it has the phone on its
 *  USB cable and runs the small agent of Mobile/agent (claudegg_agent.py), that
 *  gives a picture of the screen and takes taps, swipes and keys. This is the
 *  other side: what a program of Claude GG calls to see and to press.
 *
 *  The calls wait for the answer (a program runs on a thread of its own) and say
 *  what went wrong in plain words. The protocol is in Mobile/agent/README.md.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_Mobile_H
#define PokemonAutomation_ClaudeGG_Mobile_H

#include <atomic>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <thread>
#include <utility>
#include <vector>
#include <QImage>
#include <QString>
#include <QStringList>

class QApplication;

namespace PokemonAutomation{
namespace ClaudeGG{


extern const char* const MOBILE_TEST_OPTION;    //  --mobile-test <folder of the agent>

//  The phone, as the agent says it.
struct MobileInfo{
    QString model;
    QString android;
    int width = 0;
    int height = 0;
};

//  One swipe: from (x1, y1) to (x2, y2) in "ms" milliseconds.
struct MobileStroke{
    int x1 = 0;
    int y1 = 0;
    int x2 = 0;
    int y2 = 0;
    int ms = 300;
};

//  The Pokémon GO bot that runs on the Raspberry Pi (Mobile/gamebot.py, started
//  and stopped by the agent: /v1/bot).
//  One part of the bot that runs on its own (its "test": a GO Battle League set, the
//  scan of the Pokémon, one throw, ...), as the bot's chapters.py names them.
struct MobileBotChapter{
    QString key;
    QString group;
    QString title;
    QString start;              //  the screen the game has to be on
    QString what;
};
//  The test that runs, or the one that ran last.
struct MobileBotTest{
    QString key;                //  empty: none yet since the agent started
    QString title;
    bool running = false;
    bool finished = false;      //  it ended, and "ok" and "result" say how
    bool ok = false;
    QString result;
    int seconds = 0;
};
struct MobileBotState{
    bool installed = false;
    bool running = false;
    QStringList log;            //  the end of its log, the oldest line first
    QString battle_app;         //  GO Battle League: the app ("" is the Play Store one), the league, battles per run
    QString battle_league;
    int battle_count = 0;
    int battles_won = 0;        //  of today
    int battles_lost = 0;
    MobileBotTest test;
};
struct MobileBotStart{
    //  Switches of the bot by name ("spin", "catch", ...): see BOT_SWITCHES in the agent.
    std::vector<std::pair<QString, bool>> options;
    QString throw_target;       //  "realistic", "nice", "great", "excellent" or "off"; empty: as it is
    QString daily_time;         //  HH:MM; empty: as it is
    int daily_max_min = 0;      //  minutes; 0: as it is
    bool daily_now = false;     //  the daily run begins at once
    bool battle_app_given = false;  //  false: the app stays as it is
    QString battle_app;         //  the package; empty is the Play Store one ("com.nianticlabs.pokemongo")
    QString battle_league;      //  empty: as it is
    int battle_count = 0;       //  battles per run (1 to 50); 0: as it is
};

class MobileAgent{
public:
    //  "host" and "port" of the Pi, and the token the agent made (see its README).
    MobileAgent(const QString& host, int port, const QString& token, int timeout_msec = 15000);

    //  Is the agent there (no token needed)?
    bool ping(QString* error = nullptr) const;
    bool info(MobileInfo& result, QString* error = nullptr) const;
    //  The screen of the phone.
    bool screen(QImage& picture, QString* error = nullptr) const;

    //  A press of "ms" milliseconds (a very short tap is missed by games made with Unity).
    bool tap(int x, int y, int ms = 120, QString* error = nullptr) const;
    //  A touch of another kind: "press" (as tap()), "tap" (a plain tap, finger down and up at once: some screens of a game
    //  take this and not a press) or "motion" (finger down, "ms", finger up as separate touch events, Android 11 and newer).
    bool touch(const QString& kind, int x, int y, int ms = 120, QString* error = nullptr) const;
    bool swipe(int x1, int y1, int x2, int y2, int ms = 300, QString* error = nullptr) const;
    //  Several swipes one after the other, in one command to the phone.
    bool swipes(const std::vector<MobileStroke>& strokes, QString* error = nullptr) const;
    //  A key by its name ("BACK", "HOME", "APP_SWITCH", "POWER", "ENTER", ...).
    bool key(const QString& name, QString* error = nullptr) const;
    bool text(const QString& typed, QString* error = nullptr) const;
    bool wake(QString* error = nullptr) const;

    //  The Pokémon GO bot on the Pi. "lines": how much of the end of its log.
    bool bot_state(MobileBotState& state, int lines = 40, QString* error = nullptr) const;
    //  Sets what is asked in the bot's control file and starts it (afresh when it runs).
    bool bot_start(const MobileBotStart& settings, QString* error = nullptr) const;
    bool bot_stop(QString* error = nullptr) const;
    //  The parts of the bot that can be run on their own.
    bool bot_tests(std::vector<MobileBotChapter>& chapters, QString* error = nullptr) const;
    //  Stops the bot, sets what is asked and runs one part of it (what "state.test" then follows).
    bool bot_test(const QString& key, const MobileBotStart& settings, QString* error = nullptr) const;
    bool bot_test_stop(QString* error = nullptr) const;

private:
    struct Reply{
        int status = 0;
        QByteArray body;
    };
    bool request(const char* method, const QString& path, const QByteArray& body, Reply& reply, QString* error) const;
    bool post(const QString& path, const QByteArray& body, QString* error) const;

    QString m_host;
    int m_port;
    QString m_token;
    int m_timeout;
};

//  The live picture of the phone, in place of one screenshot at a time (a
//  screenshot takes one to three seconds; this is about ten pictures a second).
//  A thread of its own holds one connection to the agent (/v1/video), keeps the
//  newest picture and connects again when the stream drops. The agent has one
//  pipeline for all who look; a screen that does not change gives the last
//  picture again about once a second.
class MobileVideo{
public:
    //  "fps" and "width" are asked of the agent when it starts the pipeline: a
    //  pipeline that is running already keeps the ones it started with.
    MobileVideo(const QString& host, int port, const QString& token, int fps = 10, int width = 540);
    ~MobileVideo();
    MobileVideo(const MobileVideo&) = delete;
    MobileVideo& operator=(const MobileVideo&) = delete;

    void start();
    //  Ends the thread (it does not take longer than a second).
    void stop();

    //  The newest picture; "serial" counts up with each one that came (0 before the
    //  first). False: none yet.  "when": the moment it came in, in seconds of the steady clock
    //  (std::chrono::steady_clock since its epoch).
    bool latest(QImage& picture, quint64* serial = nullptr, double* when = nullptr) const;
    //  Waits up to "msec" milliseconds for a picture newer than "after". False: none came.
    bool wait_newer(QImage& picture, quint64 after, int msec, quint64* serial = nullptr, double* when = nullptr) const;
    //  What went wrong the last time, in plain words; empty when the stream is fine.
    QString error() const;

private:
    void run();
    //  One connection, until it ends; the reason it ended.
    QString read_stream();

    QString m_host;
    int m_port;
    QString m_token;
    int m_fps;
    int m_width;

    mutable std::mutex m_lock;
    mutable std::condition_variable m_changed;
    QImage m_picture;
    quint64 m_serial = 0;
    double m_time = 0;
    QString m_error;
    std::atomic<bool> m_stop{false};
    std::thread m_thread;
};

//  The token of the agent, kept apart from the settings, like the keys of the
//  assistant (encrypted for the Windows account, never in the settings file or
//  the log). The address and the port are in the settings (MOBILE_HOST and
//  MOBILE_PORT of GlobalSettings).
QString mobile_token();
//  False if it could not be saved ("error" says why); it is then kept until
//  the program closes. An empty token forgets it.
bool set_mobile_token(const QString& token, QString& error);

//  "Test the connection" of the setup: asks the agent, in a few seconds at
//  most, and says in one line what it found ("Connected to Pixel 8, Android
//  14, 1080 x 2400.") or why not, in plain words. True when it works. Does
//  not touch the phone.
bool check_mobile(const QString& host, int port, const QString& token, QString& message);

//  The test of the build: starts the agent of Mobile/agent with a phone that is
//  not there (fake_adb.py) and goes through the whole protocol with the code above.
int run_mobile_test(QApplication& application, const QString& agent_folder);


}
}
#endif
