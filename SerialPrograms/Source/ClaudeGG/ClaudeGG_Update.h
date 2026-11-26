/*  ClaudeGG Update
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  "Check for updates" in the About window: is there a build of ClaudeGG
 *  that is newer than the one that runs?
 *
 *  -   Only when the button is pressed. The program never asks by itself, so
 *      nothing leaves the computer at the start or in the background.
 *  -   One request to the list of releases of this fork on github.com (no
 *      key, no token, nothing of the user's), answered with the numbers of
 *      the builds. A build is a release named "v<version>", with a
 *      version of four numbers ("v0.1.0.3").
 *  -   The program does not update itself. When there is a newer build the
 *      window shows the page of that release, where the download is, and
 *      the user opens it.
 *
 *  The link that is shown is made here from the number of the build and the
 *  address of this fork; nothing of the answer is used as an address.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_Update_H
#define PokemonAutomation_ClaudeGG_Update_H

#include <functional>
#include <memory>
#include <QByteArray>
#include <QObject>
#include <QString>
#include "Assistant/Assistant_Http.h"

namespace PokemonAutomation{
namespace ClaudeGG{


//  Where the releases of a fork are, from the address of its source
//  ("https://github.com/<owner>/<name>/tree/<branch>").
struct ReleaseLocation{
    QString api_url;        //  The list of releases, for the request.
    QString page_url;       //  The page of the releases, for the user.
    QString tag_page_url;   //  The start of the page of one release: the tag follows.
    bool valid() const{ return !api_url.isEmpty(); }
};
ReleaseLocation release_location(const QString& project_url);


//  A version of four numbers ("0.1.0.3") as one number that puts versions in
//  their order: ((a * 100 + b) * 100 + c) * 10000 + d, where a is one digit,
//  b and c have two at most and d four. 0 when the text is not such a
//  version (and for 0.0.0.0).
int version_number(const QString& version);

//  And back: "0.1.0.3".
QString version_text(int number);

//  The version in the name of a release ("v0.1.0.3"), as a number of
//  version_number(), or 0 when the name is not one of a build.
int build_of_tag(const QString& tag);

//  The version of the build that runs, from PROGRAM_BUILD ("0.1.0.3"), as a
//  number of version_number(): 0 for "local" and anything else that is not a
//  version.
int build_of_this_program(const QString& build);


struct LatestBuild{
    int build = 0;          //  A version_number(); 0: no build is published.
    QString date;           //  "2026-11-25", or empty.
};

//  The newest build in the answer of the list of releases. Drafts do not
//  count; pre-releases do (the builds are published as pre-releases).
//  False, with a reason, when the answer is not a list of releases.
bool newest_build(const QByteArray& json, LatestBuild& latest, QString& error);


enum class UpdateState{
    FAILED,             //  "error" says why.
    NO_BUILDS,          //  Nothing is published (yet).
    LOCAL_BUILD,        //  This program is a local build: it has no number to compare.
    UP_TO_DATE,         //  This is the newest build.
    NEWER_THAN_PUBLISHED,   //  This build is newer than any that is published.
    NEWER_AVAILABLE,    //  A newer build is published.
};

struct UpdateResult{
    UpdateState state = UpdateState::FAILED;
    int current = 0;        //  A version_number(); 0: a local build.
    LatestBuild latest;
    QString error;
    //  The page of the newest build (or of the releases when there is none).
    QString page_url;
};

//  What a window says about a result, as an HTML paragraph: the link is made
//  with "link_color".
QString update_text(const UpdateResult& result, const QString& link_color);

//  The result of an answer of the list of releases to this program's build.
UpdateResult update_result(const Assistant::HttpResponse& response, const ReleaseLocation& location, int current_build);


//  One check. It stops when it is destroyed: nothing is called after that.
class UpdateCheck{
public:
    //  "transport" has to stay for as long as the check.
    UpdateCheck(Assistant::HttpTransport& transport, const QString& project_url, const QString& build);
    ~UpdateCheck();
    UpdateCheck(const UpdateCheck&) = delete;
    void operator=(const UpdateCheck&) = delete;

    bool running() const{ return m_running; }

    //  Sends the request. "done" is called once, from the event loop, never
    //  from inside start(). Does nothing when a check is running.
    void start(std::function<void(const UpdateResult& result)> done);

private:
    Assistant::HttpTransport& m_transport;
    ReleaseLocation m_location;
    int m_current;
    bool m_running = false;
    std::shared_ptr<Assistant::HttpCall> m_call;
    QObject m_context;      //  For the answer that has to come from the event loop.
};



}
}
#endif
