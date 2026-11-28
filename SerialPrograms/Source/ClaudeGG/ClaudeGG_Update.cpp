/*  ClaudeGG Update
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include "Common/Compiler.h"
#include <algorithm>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <QStringList>
#include <QTimer>
#include <QUrl>
#include "ClaudeGG_Language.h"
#include "ClaudeGG_Update.h"

namespace PokemonAutomation{
namespace ClaudeGG{

using namespace Assistant;

const char* const PACKAGE_FILE_NAME = "ClaudeGG-Windows.zip";

namespace{

//  A name of an owner or a repository on GitHub.
bool is_github_name(const QString& name){
    static const QRegularExpression pattern("^[A-Za-z0-9_.-]{1,100}$");
    return pattern.match(name).hasMatch() && name != "." && name != "..";
}

QString link(const QString& url, const QString& text, const QString& color){
    return "<a href=\"" + url + "\" style=\"color: " + color + "\">" + text.toHtmlEscaped() + "</a>";
}

}


ReleaseLocation release_location(const QString& project_url){
    ReleaseLocation location;
    const QStringList parts = project_url.split('/', Qt::SkipEmptyParts);
    const qsizetype host = parts.indexOf("github.com");
    if (host < 0 || parts.size() < host + 3){
        return location;
    }
    const QString& owner = parts[host + 1];
    const QString& name = parts[host + 2];
    if (!is_github_name(owner) || !is_github_name(name)){
        return location;
    }
    location.api_url = "https://api.github.com/repos/" + owner + "/" + name + "/releases?per_page=30";
    location.page_url = "https://github.com/" + owner + "/" + name + "/releases";
    location.tag_page_url = location.page_url + "/tag/";
    location.download_url = location.page_url + "/download/";
    return location;
}


int version_number(const QString& version){
    static const QRegularExpression pattern("^([0-9])\\.([0-9]{1,2})\\.([0-9]{1,2})\\.([0-9]{1,4})$");
    const QRegularExpressionMatch match = pattern.match(version);
    if (!match.hasMatch()){
        return 0;
    }
    const int a = match.captured(1).toInt();
    const int b = match.captured(2).toInt();
    const int c = match.captured(3).toInt();
    const int d = match.captured(4).toInt();
    return ((a * 100 + b) * 100 + c) * 10000 + d;
}

QString version_text(int number){
    if (number <= 0){
        return "0";
    }
    const int d = number % 10000;
    number /= 10000;
    const int c = number % 100;
    number /= 100;
    const int b = number % 100;
    const int a = number / 100;
    return QString("%1.%2.%3.%4").arg(a).arg(b).arg(c).arg(d);
}

int build_of_tag(const QString& tag){
    if (!tag.startsWith('v')){
        return 0;
    }
    return version_number(tag.mid(1));
}

int build_of_this_program(const QString& build){
    return version_number(build.trimmed());
}


bool newest_build(const QByteArray& json, LatestBuild& latest, QString& error){
    latest = LatestBuild();
    QJsonParseError parse;
    const QJsonDocument document = QJsonDocument::fromJson(json, &parse);
    if (parse.error != QJsonParseError::NoError || !document.isArray()){
        error = tr_ui("The answer of GitHub is not a list of releases.");
        return false;
    }
    static const QRegularExpression date_pattern("^[0-9]{4}-[0-9]{2}-[0-9]{2}");
    for (const QJsonValue& value : document.array()){
        const QJsonObject release = value.toObject();
        if (release.value("draft").toBool()){
            continue;
        }
        const int build = build_of_tag(release.value("tag_name").toString());
        if (build <= latest.build){
            continue;
        }
        latest.build = build;
        latest.date.clear();
        const QRegularExpressionMatch date = date_pattern.match(release.value("published_at").toString());
        if (date.hasMatch()){
            latest.date = date.captured(0);
        }
        latest.package_sha256 = package_sha256_of(release);
        latest.package_size = 0;
        for (const QJsonValue& asset : release.value("assets").toArray()){
            if (asset.toObject().value("name").toString() == PACKAGE_FILE_NAME){
                latest.package_size = (qint64)asset.toObject().value("size").toDouble();
            }
        }
    }
    return true;
}


QStringList whats_new_items(const QString& body){
    static const QRegularExpression heading("^#{1,6}\\s*(.*?)\\s*$");
    static const QRegularExpression point("^\\s*[-*+]\\s+(.*\\S)\\s*$");
    //  What GitHub's own notes add after the title of a pull request.
    static const QRegularExpression by(" by @[A-Za-z0-9_.\\[\\]-]+ in https?://\\S+$");
    static const QRegularExpression markup("\\*\\*|__|`");
    QStringList items;
    bool inside = false;
    for (const QString& raw : body.split('\n')){
        const QString line = QString(raw).remove('\r');
        const QRegularExpressionMatch title = heading.match(line);
        if (title.hasMatch()){
            const QString name = title.captured(1).toLower().remove('\'').remove(QChar(0x2019));
            inside = name == "whats new" || name == "whats changed";
            continue;
        }
        if (!inside){
            continue;
        }
        const QRegularExpressionMatch item = point.match(line);
        if (!item.hasMatch()){
            continue;
        }
        QString text = item.captured(1);
        text.remove(by);
        text.remove(markup);
        text = text.trimmed();
        if (!text.isEmpty() && items.size() < 40){
            items.push_back(text.left(300));
        }
    }
    return items;
}

QString package_sha256_of(const QJsonObject& release){
    static const QRegularExpression digest("^sha256:([0-9a-fA-F]{64})$");
    for (const QJsonValue& value : release.value("assets").toArray()){
        const QJsonObject asset = value.toObject();
        if (asset.value("name").toString() != PACKAGE_FILE_NAME){
            continue;
        }
        const QRegularExpressionMatch match = digest.match(asset.value("digest").toString());
        if (match.hasMatch()){
            return match.captured(1).toLower();
        }
    }
    //  The workflow writes it in the text of each release as well.
    static const QRegularExpression in_text(
        "SHA-256 of " + QRegularExpression::escape(PACKAGE_FILE_NAME) + ":\\s*([0-9a-fA-F]{64})(?![0-9a-fA-F])"
    );
    const QRegularExpressionMatch match = in_text.match(release.value("body").toString());
    return match.hasMatch() ? match.captured(1).toLower() : QString();
}

std::vector<ReleaseNotes> release_news(const QByteArray& json, int after){
    std::vector<ReleaseNotes> news;
    const QJsonDocument document = QJsonDocument::fromJson(json);
    if (!document.isArray()){
        return news;
    }
    static const QRegularExpression date_pattern("^[0-9]{4}-[0-9]{2}-[0-9]{2}");
    for (const QJsonValue& value : document.array()){
        const QJsonObject release = value.toObject();
        if (release.value("draft").toBool()){
            continue;
        }
        ReleaseNotes notes;
        notes.build = build_of_tag(release.value("tag_name").toString());
        if (notes.build <= after){
            continue;
        }
        const QRegularExpressionMatch date = date_pattern.match(release.value("published_at").toString());
        if (date.hasMatch()){
            notes.date = date.captured(0);
        }
        notes.items = whats_new_items(release.value("body").toString());
        news.push_back(std::move(notes));
    }
    std::sort(news.begin(), news.end(), [](const ReleaseNotes& a, const ReleaseNotes& b){
        return a.build > b.build;
    });
    if (news.size() > MAX_RELEASE_NOTES){
        news.resize(MAX_RELEASE_NOTES);
    }
    return news;
}


UpdateResult update_result(const HttpResponse& response, const ReleaseLocation& location, int current_build){
    UpdateResult result;
    result.current = current_build;
    result.page_url = location.page_url;
    if (!response.error.isEmpty()){
        result.error = response.error;
        return result;
    }
    if (response.status == 403 || response.status == 429){
        result.error = tr_ui("GitHub does not answer requests from this address for now (it limits them). Try again later.");
        return result;
    }
    if (response.status == 404){
        result.error = tr_ui("GitHub has no list of releases at this address.");
        return result;
    }
    if (!response.ok()){
        result.error = tr_ui("GitHub answered with the status %1.").arg(response.status);
        return result;
    }
    if (!newest_build(response.body, result.latest, result.error)){
        return result;
    }
    if (result.latest.build == 0){
        result.state = UpdateState::NO_BUILDS;
        return result;
    }
    result.page_url = location.tag_page_url + "v" + version_text(result.latest.build);
    result.news = release_news(response.body, current_build);
    if (current_build == 0){
        result.state = UpdateState::LOCAL_BUILD;
        //  A local build has no number to compare: only what is new in the newest.
        if (result.news.size() > 1){
            result.news.resize(1);
        }
    }else if (current_build < result.latest.build){
        result.state = UpdateState::NEWER_AVAILABLE;
        result.package_url = location.download_url + "v" + version_text(result.latest.build) + "/" + PACKAGE_FILE_NAME;
    }else if (current_build == result.latest.build){
        result.state = UpdateState::UP_TO_DATE;
    }else{
        result.state = UpdateState::NEWER_THAN_PUBLISHED;
    }
    return result;
}


bool can_install(const UpdateResult& result){
#ifdef _WIN32
    return result.state == UpdateState::NEWER_AVAILABLE &&
        result.latest.package_sha256.size() == 64 &&
        !result.package_url.isEmpty();
#else
    (void)result;
    return false;
#endif
}

QString news_html(const UpdateResult& result){
    QString html;
    for (const ReleaseNotes& notes : result.news){
        html += "<p style=\"margin: 8px 0 2px 0\"><b>" + (notes.date.isEmpty()
            ? tr_ui("Build %1").arg(version_text(notes.build))
            : tr_ui("Build %1, of %2").arg(version_text(notes.build), notes.date)
        ).toHtmlEscaped() + "</b></p>";
        if (notes.items.isEmpty()){
            html += "<p style=\"margin: 0\">" + tr_ui("Its release says nothing about what changed.").toHtmlEscaped() + "</p>";
            continue;
        }
        html += "<ul style=\"margin: 0\">";
        for (const QString& item : notes.items){
            html += "<li>" + item.toHtmlEscaped() + "</li>";
        }
        html += "</ul>";
    }
    return html;
}


QString update_text(const UpdateResult& result, const QString& link_color){
    const QString latest = version_text(result.latest.build);
    const QString current = version_text(result.current);
    switch (result.state){
    case UpdateState::FAILED:
        return tr_ui("Could not check for updates: %1").arg(result.error.toHtmlEscaped());
    case UpdateState::NO_BUILDS:
        return tr_ui("No build is published yet.") + " " +
            link(result.page_url, tr_ui("Open the page of the releases"), link_color);
    case UpdateState::LOCAL_BUILD:
        return tr_ui("This is a local build, without a number. The newest published build is build %1.").arg(latest) + " " +
            link(result.page_url, tr_ui("Open its page"), link_color);
    case UpdateState::UP_TO_DATE:
        return tr_ui("Up to date: build %1 is the newest published build.").arg(current);
    case UpdateState::NEWER_THAN_PUBLISHED:
        return tr_ui("This build (%1) is newer than the newest published build (%2).").arg(current, latest);
    case UpdateState::NEWER_AVAILABLE:
        break;
    }
    QString text = result.latest.date.isEmpty()
        ? tr_ui("A newer build is published: build %1. This is build %2.").arg(latest, current)
        : tr_ui("A newer build is published: build %1, of %2. This is build %3.").arg(latest, result.latest.date, current);
    return text + " " + link(result.page_url, tr_ui("Open the page to download it"), link_color);
}


UpdateCheck::UpdateCheck(HttpTransport& transport, const QString& project_url, const QString& build)
    : m_transport(transport)
    , m_location(release_location(project_url))
    , m_current(build_of_this_program(build))
{}

UpdateCheck::~UpdateCheck(){
    if (m_call){
        m_call->abort();
    }
}

void UpdateCheck::start(std::function<void(const UpdateResult& result)> done){
    if (m_running){
        return;
    }
    m_running = true;

    if (!m_location.valid()){
        UpdateResult result;
        result.current = m_current;
        result.error = tr_ui("The address of this program's releases is not known.");
        QTimer::singleShot(0, &m_context, [this, result, done]{
            m_running = false;
            done(result);
        });
        return;
    }

    HttpRequest request;
    request.method = "GET";
    request.url = QUrl(m_location.api_url);
    request.headers.push_back({"accept", "application/vnd.github+json"});
    request.headers.push_back({"x-github-api-version", "2022-11-28"});
    //  GitHub's API refuses a request without a user agent.
    request.headers.push_back({"user-agent", "ClaudeGG"});
    request.idle_timeout_ms = 20000;
    //  A renamed repository answers with a redirect. The request carries
    //  nothing that must not go along.
    request.follow_redirects = true;

    const ReleaseLocation location = m_location;
    const int current = m_current;
    m_call = m_transport.send(
        request,
        nullptr,
        [this, location, current, done](const HttpResponse& response){
            //  Kept until the end of this handler: it is the handler of the call.
            std::shared_ptr<HttpCall> call = std::move(m_call);
            m_running = false;
            done(update_result(response, location, current));
        }
    );
    if (!m_call){
        UpdateResult result;
        result.current = m_current;
        result.error = tr_ui("There is no connection to use.");
        QTimer::singleShot(0, &m_context, [this, result, done]{
            m_running = false;
            done(result);
        });
    }
}



}
}
