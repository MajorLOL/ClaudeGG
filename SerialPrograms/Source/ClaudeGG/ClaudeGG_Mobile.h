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

#include <vector>
#include <QImage>
#include <QString>

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
    bool swipe(int x1, int y1, int x2, int y2, int ms = 300, QString* error = nullptr) const;
    //  Several swipes one after the other, in one command to the phone.
    bool swipes(const std::vector<MobileStroke>& strokes, QString* error = nullptr) const;
    //  A key by its name ("BACK", "HOME", "APP_SWITCH", "POWER", "ENTER", ...).
    bool key(const QString& name, QString* error = nullptr) const;
    bool text(const QString& typed, QString* error = nullptr) const;
    bool wake(QString* error = nullptr) const;

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
