/*  Claude GG Pokemon GO Lock Check (the lock screen and the dimmed game, played on the stories of the Python code)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The file of Mobile/tools/make_lock_golden.py holds stories of what spin_stop.py does about the lock screen of the phone and the dimmed game: is_dimmed()
 *  of pictures (brightness, the share of bright pixels, pictures of other sizes), unlock() and unlock_game().  They are played on a pretend phone with a
 *  pretend clock.  What the code was GIVEN: whether the phone shows its lock screen, the screenshots.  What it DID: the questions to the phone, the taps,
 *  swipes, sleeps and log lines, and at the end of every call what it returned.  The first event that differs ends that story.
 *
 */

#include <stdexcept>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include "ClaudeGG_PokemonGoLock.h"
#include "ClaudeGG_PokemonGoStory.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Lock{

namespace{

using Story::Abort;


class Replay : public Story::Host, public Lock::Host{
public:
    using Story::Host::Host;

    //  ---- Flow::Host (the story has the taps, the sleeps, the log lines and the screenshots; it has no swipes)
    void swipe(int x1, int y1, int x2, int y2, int ms) override{
        const QString doing = QString("a swipe (%1, %2) -> (%3, %4) in %5 ms").arg(x1).arg(y1).arg(x2).arg(y2).arg(ms);
        const QJsonArray event = out("swipe", doing);
        if (event.at(2).toInt() != x1 || event.at(3).toInt() != y1 || event.at(4).toInt() != x2 || event.at(5).toInt() != y2 || event.at(6).toInt() != ms){
            fail("the swipe differs: the Python code did " + Story::describe(event) + ", the port: " + doing);
        }
    }

    //  ---- Lock::Host
    bool keyguard_showing() override{
        const QJsonArray next = peek("the question whether the phone shows its lock screen");
        if (next.at(0).toString() == "keyguard_error"){
            input("keyguard_error", "the question whether the phone shows its lock screen");
            throw std::runtime_error(next.at(2).toString().toStdString());
        }
        return out("keyguard", "the question whether the phone shows its lock screen").at(2).toBool();
    }
    void dismiss_keyguard() override{
        const QJsonArray next = peek("wm dismiss-keyguard");
        if (next.at(0).toString() == "dismiss_error"){
            out("dismiss_error", "wm dismiss-keyguard");
            throw std::runtime_error(next.at(2).toString().toStdString());
        }
        out("dismiss", "wm dismiss-keyguard");
    }
};


//  Plays one story; says what went another way (nothing: all of it was the same).
QString play(const QJsonObject& test_case, double start, std::vector<Story::Scene>& cache){
    Replay host(test_case, start, cache);
    try{
        for (const QJsonValue& v : test_case.value("spec").toObject().value("calls").toArray()){
            const QJsonObject call = v.toObject();
            host.begin(call);
            const QString fn = call.value("fn").toString();
            try{
                if (fn == "is_dimmed"){
                    host.result(is_dimmed(host.picture(call.value("img").toInt())));
                }else if (fn == "unlock"){
                    host.result(unlock(host));
                }else if (fn == "unlock_game"){
                    const cv::Mat got = call.contains("img") ? unlock_game(host, host.picture(call.value("img").toInt())) : unlock_game(host);
                    host.result(host.index_of(got));
                }else{
                    host.fail("the story has a call that the check does not know: " + fn);
                }
            }catch (const Abort&){
                throw;
            }catch (const std::exception& e){
                host.raised(QString::fromUtf8(e.what()));
            }
        }
        host.finish_story();
    }catch (const Abort&){
        return host.message;
    }
    return QString();
}


}


int run_lock_checks(const QString& golden, QStringList& report, bool stop_at_first){
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the stories of the lock screen are not there: " + golden;
        return 1;
    }
    const QJsonObject root = QJsonDocument::fromJson(qUncompress(file.readAll())).object();
    const QJsonArray cases = root.value("cases").toArray();
    const double start = root.value("start").toDouble(1000.0);
    int failed = 0;
    std::vector<Story::Scene> cache;
    for (const QJsonValue& v : cases){
        const QJsonObject test_case = v.toObject();
        const QString what = play(test_case, start, cache);
        if (!what.isEmpty()){
            report << QString("FAILED: in the story '%1' the port does something else than the Python code: %2").arg(test_case.value("id").toString(), what);
            failed++;
            if (stop_at_first){
                return failed;
            }
        }
    }
    if (cases.isEmpty()){
        report << "FAILED: the file of the lock screen has no stories";
        return failed + 1;
    }
    report << QString("lock screen: %1 stories played, %2 went another way").arg(cases.size()).arg(failed);
    return failed;
}


}
}
}
}
