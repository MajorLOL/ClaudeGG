/*  ClaudeGG Updater
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include "Common/Compiler.h"
#include <string.h>
#include <algorithm>
#include <chrono>
#include <vector>
#include <QCoreApplication>
#include <QDateTime>
#include <QDir>
#include <QDirIterator>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QSaveFile>
#include <QThread>
#include <QTimer>
#include "miniz-3.1.1/miniz.h"
#include "ClaudeGG_Language.h"
#include "ClaudeGG_Update.h"
#include "ClaudeGG_Updater.h"

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <Windows.h>
#else
#include <signal.h>
#include <errno.h>
#endif

namespace PokemonAutomation{
namespace ClaudeGG{

using namespace Assistant;


const char* const APPLY_UPDATE_OPTION = "--apply-update";
const char* const UNPACK_UPDATE_OPTION = "--unpack-update";
const char* const PROGRAM_FILE_NAME = "ClaudeGG.exe";

namespace{

const char OUTCOME_FILE[] = "last-update.json";
const char LOG_FILE[] = "update.log";

QString with_slash(QString path){
    path.replace('\\', '/');
    if (!path.isEmpty() && !path.endsWith('/')){
        path += '/';
    }
    return path;
}

void pause_ms(int milliseconds){
    QThread::msleep((unsigned long)milliseconds);
}

//  A file moved, also from one drive to another.
bool move_file(const QString& from, const QString& to){
    if (QFileInfo::exists(to) && !QFile::remove(to)){
        return false;
    }
    if (QFile::rename(from, to)){
        return true;
    }
    if (!QFile::copy(from, to)){
        return false;
    }
    if (!QFile::remove(from)){
        QFile::remove(to);
        return false;
    }
    return true;
}

bool with_attempts(int attempts, const std::function<bool()>& step){
    for (int c = 0; c < std::max(1, attempts); c++){
        if (c > 0){
            pause_ms(500);
        }
        if (step()){
            return true;
        }
    }
    return false;
}

//  A name in a zip that stays inside the folder it is unpacked in.
bool safe_zip_name(const QString& name){
    if (name.isEmpty() || name.startsWith('/') || name.startsWith('\\') || name.contains(':')){
        return false;
    }
    for (const QString& part : QString(name).replace('\\', '/').split('/')){
        if (part == ".."){
            return false;
        }
    }
    return true;
}

size_t write_to_file(void* opaque, mz_uint64, const void* data, size_t size){
    QFile* file = static_cast<QFile*>(opaque);
    return file->write(static_cast<const char*>(data), (qint64)size) == (qint64)size ? size : 0;
}

}



QString updates_folder(const QString& data){
    return with_slash(data) + "Updates/";
}


bool keep_users_file(const QString& relative_path){
    const QStringList parts = QString(relative_path).replace('\\', '/').split('/', Qt::SkipEmptyParts);
    if (parts.isEmpty()){
        return true;
    }
    if (parts.size() == 1){
        const QString name = parts[0].toLower();
        return name.endsWith(".json") || name.endsWith(".log") || name.endsWith(".ini");
    }
    static const char* const USERS_FOLDERS[] = {
        "usersettings", "installations", "languages", "screenshots",
        "debugdumps", "errordumps", "tempfiles", "updates",
    };
    const QString top = parts[0].toLower();
    for (const char* folder : USERS_FOLDERS){
        if (top == QLatin1String(folder)){
            return true;
        }
    }
    return false;
}


QString file_sha256(const QString& path){
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)){
        return QString();
    }
    QCryptographicHash hash(QCryptographicHash::Sha256);
    if (!hash.addData(&file)){
        return QString();
    }
    return QString::fromLatin1(hash.result().toHex());
}


bool unpack_zip(const QString& zip, const QString& folder, QString& error, const std::atomic<bool>* cancel){
    //  Read through Qt, so that a folder with any name works (miniz opens
    //  files with the narrow names of the C library).
    QFile input(zip);
    if (!input.open(QIODevice::ReadOnly)){
        error = tr_ui("The package could not be opened: %1").arg(input.errorString());
        return false;
    }
    const qint64 size = input.size();
    uchar* bytes = input.map(0, size);
    if (bytes == nullptr){
        error = tr_ui("The package could not be read: %1").arg(input.errorString());
        return false;
    }

    mz_zip_archive archive;
    memset(&archive, 0, sizeof(archive));
    if (!mz_zip_reader_init_mem(&archive, bytes, (size_t)size, 0)){
        error = tr_ui("The package is not a zip that can be read.");
        return false;
    }
    struct Close{
        mz_zip_archive& archive;
        ~Close(){ mz_zip_reader_end(&archive); }
    } close{archive};

    const QString base = with_slash(folder);
    if (!QDir().mkpath(base)){
        error = tr_ui("The folder %1 could not be made.").arg(QDir::toNativeSeparators(folder));
        return false;
    }
    const mz_uint count = mz_zip_reader_get_num_files(&archive);
    for (mz_uint c = 0; c < count; c++){
        if (cancel != nullptr && cancel->load()){
            error = tr_ui("Stopped.");
            return false;
        }
        mz_zip_archive_file_stat stat;
        if (!mz_zip_reader_file_stat(&archive, c, &stat)){
            error = tr_ui("The package is not a zip that can be read.");
            return false;
        }
        const QString name = QString::fromUtf8(stat.m_filename).replace('\\', '/');
        if (!safe_zip_name(name)){
            error = tr_ui("The package has a file that would land outside its folder (%1). It is not used.").arg(name);
            return false;
        }
        if (mz_zip_reader_is_file_a_directory(&archive, c)){
            QDir().mkpath(base + name);
            continue;
        }
        const QString path = base + name;
        QDir().mkpath(QFileInfo(path).absolutePath());
        QFile output(path);
        if (!output.open(QIODevice::WriteOnly | QIODevice::Truncate)){
            error = tr_ui("%1 could not be written: %2").arg(QDir::toNativeSeparators(path), output.errorString());
            return false;
        }
        if (!mz_zip_reader_extract_to_callback(&archive, c, write_to_file, &output, 0)){
            output.close();
            output.remove();
            error = tr_ui("%1 could not be unpacked from the package.").arg(name);
            return false;
        }
        output.close();
    }
    return true;
}


QString package_root(const QString& unpacked){
    const QString base = with_slash(unpacked);
    if (QFileInfo(base + PROGRAM_FILE_NAME).isFile()){
        return base;
    }
    const QStringList folders = QDir(base).entryList(QDir::Dirs | QDir::NoDotAndDotDot, QDir::Name);
    for (const QString& folder : folders){
        if (QFileInfo(base + folder + "/" + PROGRAM_FILE_NAME).isFile()){
            return base + folder + "/";
        }
    }
    return QString();
}


QString side_by_side_folder(const QString& program, int build){
    const QDir parent(QFileInfo(QDir::cleanPath(program)).absolutePath());
    const QString name = "Claude GG " + version_text(build);
    QString path = parent.absoluteFilePath(name);
    for (int c = 2; QFileInfo::exists(path) && c < 100; c++){
        path = parent.absoluteFilePath(name + QString(" (%1)").arg(c));
    }
    return with_slash(path);
}


bool copy_package(const QString& package, const QString& target, const QString& backup, CopyReport& report, int attempts){
    report = CopyReport();
    const QString from_base = with_slash(package);
    const QString to_base = with_slash(target);
    const QString backup_base = with_slash(backup);

    //  The program itself last: until then the old one is whole.
    QStringList files;
    QDirIterator it(from_base, QDir::Files | QDir::Hidden | QDir::NoDotAndDotDot, QDirIterator::Subdirectories);
    while (it.hasNext()){
        files.push_back(QDir(from_base).relativeFilePath(it.next()));
    }
    files.sort(Qt::CaseInsensitive);
    if (files.removeAll(PROGRAM_FILE_NAME) > 0){
        files.push_back(PROGRAM_FILE_NAME);
    }
    if (files.isEmpty()){
        report.error = tr_ui("The package is empty.");
        return false;
    }

    struct Step{
        QString file;
        bool had_old;
    };
    std::vector<Step> done;
    auto undo = [&]{
        for (auto step = done.rbegin(); step != done.rend(); ++step){
            const QString to = to_base + step->file;
            with_attempts(attempts, [&]{ return !QFileInfo::exists(to) || QFile::remove(to); });
            if (step->had_old){
                with_attempts(attempts, [&]{ return move_file(backup_base + step->file, to); });
            }
        }
    };
    auto fail = [&](const QString& why){
        report.error = why;
        undo();
        report.replaced = report.added = 0;
        return false;
    };

    for (const QString& file : files){
        const QString from = from_base + file;
        const QString to = to_base + file;
        const QFileInfo existing(to);
        const bool exists = existing.exists();
        if (exists && keep_users_file(file)){
            report.kept++;
            continue;
        }
        if (exists && existing.isDir()){
            return fail(tr_ui("%1 is a folder in the program, and a file in the new build.").arg(QDir::toNativeSeparators(to)));
        }
        if (!QDir().mkpath(QFileInfo(to).absolutePath())){
            return fail(tr_ui("The folder %1 could not be made.").arg(QDir::toNativeSeparators(QFileInfo(to).absolutePath())));
        }
        if (exists){
            QDir().mkpath(QFileInfo(backup_base + file).absolutePath());
            if (!with_attempts(attempts, [&]{ return move_file(to, backup_base + file); })){
                return fail(tr_ui("%1 is in use or may not be changed.").arg(QDir::toNativeSeparators(to)));
            }
        }
        done.push_back({file, exists});
        if (!with_attempts(attempts, [&]{ return QFile::copy(from, to); })){
            return fail(tr_ui("%1 could not be written.").arg(QDir::toNativeSeparators(to)));
        }
        if (exists){
            report.replaced++;
        }else{
            report.added++;
        }
    }
    return true;
}


bool copy_folder(const QString& from, const QString& to){
    const QString from_base = with_slash(from);
    const QString to_base = with_slash(to);
    if (!QDir().mkpath(to_base)){
        return false;
    }
    bool fine = true;
    QDirIterator it(from_base, QDir::Files | QDir::Hidden | QDir::NoDotAndDotDot, QDirIterator::Subdirectories);
    while (it.hasNext()){
        const QString file = QDir(from_base).relativeFilePath(it.next());
        QDir().mkpath(QFileInfo(to_base + file).absolutePath());
        QFile::remove(to_base + file);
        fine = QFile::copy(from_base + file, to_base + file) && fine;
    }
    return fine;
}


bool install_side_by_side(const QString& package, const QString& folder, const QString& data, QString& error){
    const QString source = QDir::cleanPath(package);
    const QString destination = QDir::cleanPath(folder);
    if (QFileInfo::exists(destination)){
        error = tr_ui("The folder %1 is there already.").arg(QDir::toNativeSeparators(destination));
        return false;
    }
    //  The package is not needed any more: moved when it is on the same drive.
    if (!QDir().rename(source, destination)){
        if (!copy_folder(source, destination)){
            error = tr_ui("The new build could not be copied to %1.").arg(QDir::toNativeSeparators(destination));
            QDir(destination).removeRecursively();
            return false;
        }
    }
    //  The settings go along, so that the new copy starts as this one is now.
    const QString base = with_slash(data);
    for (const char* name : {"UserSettings", "Languages"}){
        const QString from = base + name;
        if (QFileInfo(from).isDir() && !copy_folder(from, destination + "/" + name)){
            error = tr_ui("The new build is in %1, but the settings could not all be copied along.").arg(QDir::toNativeSeparators(destination));
            return false;
        }
    }
    return true;
}


//  ---------------------------------------------------------------------
//  After the program has closed
//  ---------------------------------------------------------------------

bool start_apply_update(
    const QString& package, const QString& target, const QString& data,
    int build, const QStringList& restart_arguments, QString& error
){
    const QString program = with_slash(package) + PROGRAM_FILE_NAME;
    if (!QFileInfo(program).isFile()){
        error = tr_ui("The new build has no %1.").arg(PROGRAM_FILE_NAME);
        return false;
    }
    QStringList arguments{
        APPLY_UPDATE_OPTION,
        "--target", QDir::toNativeSeparators(QDir::cleanPath(target)),
        "--data", QDir::toNativeSeparators(QDir::cleanPath(data)),
        "--wait-pid", QString::number(QCoreApplication::applicationPid()),
        "--build", version_text(build),
        "--restart",
    };
    arguments += restart_arguments;
    if (!QProcess::startDetached(program, arguments, package)){
        error = tr_ui("The new build could not be started to put itself in place.");
        return false;
    }
    return true;
}


bool is_apply_update(int argc, char* argv[]){
    return argc > 1 && (strcmp(argv[1], APPLY_UPDATE_OPTION) == 0 || strcmp(argv[1], UNPACK_UPDATE_OPTION) == 0);
}


namespace{

//  Waits until the process "pid" has ended, at most "timeout_ms". True: it has.
bool wait_for_process(qint64 pid, int timeout_ms){
    if (pid <= 0){
        return true;
    }
#ifdef _WIN32
    HANDLE process = OpenProcess(SYNCHRONIZE, FALSE, (DWORD)pid);
    if (process == nullptr){
        return true;    //  Gone already.
    }
    const DWORD result = WaitForSingleObject(process, (DWORD)timeout_ms);
    CloseHandle(process);
    return result == WAIT_OBJECT_0;
#else
    const auto end = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_ms);
    while (std::chrono::steady_clock::now() < end){
        if (kill((pid_t)pid, 0) != 0 && errno == ESRCH){
            return true;
        }
        pause_ms(200);
    }
    return false;
#endif
}

class ApplyLog{
public:
    explicit ApplyLog(const QString& path)
        : m_file(path)
    {
        QDir().mkpath(QFileInfo(path).absolutePath());
        //  Without a log the update goes on all the same.
        if (!m_file.open(QIODevice::WriteOnly | QIODevice::Append | QIODevice::Text)){
            return;
        }
    }
    void line(const QString& text){
        if (m_file.isOpen()){
            m_file.write((QDateTime::currentDateTime().toString(Qt::ISODate) + "  " + text + "\n").toUtf8());
            m_file.flush();
        }
    }
private:
    QFile m_file;
};

}


bool write_update_outcome(const QString& data, bool ok, const QString& build, const QString& message){
    const QString folder = updates_folder(data);
    QDir().mkpath(folder);
    QJsonObject note;
    note.insert("ok", ok);
    note.insert("build", build);
    note.insert("message", message);
    QSaveFile file(folder + OUTCOME_FILE);
    if (!file.open(QIODevice::WriteOnly)){
        return false;
    }
    file.write(QJsonDocument(note).toJson());
    return file.commit();
}

bool take_update_outcome(const QString& data, bool& ok, QString& build, QString& message){
    const QString path = updates_folder(data) + OUTCOME_FILE;
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)){
        return false;
    }
    const QJsonObject note = QJsonDocument::fromJson(file.read(64 * 1024)).object();
    file.close();
    QFile::remove(path);
    if (note.isEmpty()){
        return false;
    }
    ok = note.value("ok").toBool();
    build = note.value("build").toString();
    message = note.value("message").toString();
    return true;
}


int run_apply_update(int argc, char* argv[]){
    QCoreApplication application(argc, argv);
    const QStringList arguments = QCoreApplication::arguments();
    if (arguments.value(1) == UNPACK_UPDATE_OPTION){
        //  The workflow's test: a package unpacked as a download is.
        if (arguments.size() < 4){
            return 2;
        }
        QString error;
        if (!unpack_zip(arguments[2], arguments[3], error)){
            ApplyLog(updates_folder(arguments[3]) + LOG_FILE).line("Unpacking failed: " + error);
            return 1;
        }
        return package_root(arguments[3]).isEmpty() ? 1 : 0;
    }
    QString target;
    QString data;
    QString build;
    qint64 pid = 0;
    QStringList restart;
    bool no_restart = false;
    for (qsizetype c = 2; c < arguments.size(); c++){
        const QString& argument = arguments[c];
        const bool has_value = c + 1 < arguments.size();
        if (argument == "--restart"){
            restart = arguments.mid(c + 1);
            break;
        }else if (argument == "--no-restart"){
            no_restart = true;
        }else if (argument == "--target" && has_value){
            target = arguments[++c];
        }else if (argument == "--data" && has_value){
            data = arguments[++c];
        }else if (argument == "--build" && has_value){
            build = arguments[++c];
        }else if (argument == "--wait-pid" && has_value){
            pid = arguments[++c].toLongLong();
        }
    }
    if (target.isEmpty() || data.isEmpty()){
        return 2;
    }
    target = with_slash(QDir::fromNativeSeparators(target));
    data = with_slash(QDir::fromNativeSeparators(data));
    const QString package = with_slash(QCoreApplication::applicationDirPath());
    ApplyLog log(updates_folder(data) + LOG_FILE);
    log.line("Update to build " + build + ": from " + package + " to " + target);

    if (!wait_for_process(pid, 120000)){
        log.line("The program (process " + QString::number(pid) + ") did not close within two minutes: nothing was changed.");
        write_update_outcome(data, false, build, tr_ui("Claude GG did not close in time, so the update was not installed. Nothing was changed."));
        return 1;
    }
    //  Windows can take a moment to let go of the files of a process that ended.
    pause_ms(500);

    const QString backup = with_slash(QDir::cleanPath(package + "../..")) + "backup/";
    CopyReport report;
    const bool ok = QDir::cleanPath(package) != QDir::cleanPath(target) &&
        copy_package(package, target, backup, report, 40);
    if (ok){
        log.line(QString("Done: %1 files replaced, %2 added, %3 of the user's kept.").arg(report.replaced).arg(report.added).arg(report.kept));
        write_update_outcome(data, true, build, QString());
    }else{
        log.line("Failed, everything was put back: " + report.error);
        write_update_outcome(data, false, build, tr_ui("The update could not be installed, so the build you had was put back. %1").arg(report.error));
    }

    const QString program = target + PROGRAM_FILE_NAME;
    if (no_restart){
        log.line("Not started again (--no-restart).");
    }else if (!QProcess::startDetached(program, restart, data)){
        log.line("The program could not be started again: " + program);
    }
    return ok ? 0 : 1;
}


void clean_old_updates(const QString& data){
    const QString folder = updates_folder(data);
    const QStringList entries = QDir(folder).entryList(QDir::Dirs | QDir::NoDotAndDotDot);
    for (const QString& entry : entries){
        QDir(folder + entry).removeRecursively();
    }
}


//  ---------------------------------------------------------------------
//  The download
//  ---------------------------------------------------------------------

UpdateDownload::UpdateDownload(HttpTransport& transport)
    : m_transport(transport)
{}

UpdateDownload::~UpdateDownload(){
    if (m_call){
        m_call->abort();
        m_call.reset();
    }
    m_cancel.store(true);
    if (m_worker.joinable()){
        m_worker.join();
    }
    if (m_file){
        m_file->remove();
    }
}

void UpdateDownload::finish(bool ok, const QString& error, const QString& package){
    m_running = false;
    if (m_progress){
        m_progress(ok ? Stage::DONE : Stage::FAILED, m_received, m_size);
    }
    Done done = std::move(m_done);
    m_progress = nullptr;
    if (done){
        done(ok, error, package);
    }
}

void UpdateDownload::start(
    const QString& url, const QString& sha256, qint64 size, const QString& folder,
    Progress progress, Done done
){
    if (m_running){
        return;
    }
    m_running = true;
    m_cancel.store(false);
    m_sha256 = sha256.toLower();
    m_folder = with_slash(folder);
    m_size = size;
    m_received = 0;
    m_progress = std::move(progress);
    m_done = std::move(done);
    if (m_worker.joinable()){
        m_worker.join();
    }

    auto fail_later = [this](const QString& error){
        QTimer::singleShot(0, &m_context, [this, error]{
            finish(false, error, QString());
        });
    };
    if (m_sha256.size() != 64){
        fail_later(tr_ui("The release does not say the SHA-256 of its package, so it is not installed."));
        return;
    }
    //  What an earlier attempt left behind.
    QDir(m_folder).removeRecursively();
    if (!QDir().mkpath(m_folder)){
        fail_later(tr_ui("The folder %1 could not be made.").arg(QDir::toNativeSeparators(m_folder)));
        return;
    }
    m_file = std::make_unique<QFile>(m_folder + PACKAGE_FILE_NAME + ".part");
    if (!m_file->open(QIODevice::WriteOnly | QIODevice::Truncate)){
        const QString error = tr_ui("%1 could not be written: %2").arg(QDir::toNativeSeparators(m_file->fileName()), m_file->errorString());
        m_file.reset();
        fail_later(error);
        return;
    }
    m_hash = std::make_unique<QCryptographicHash>(QCryptographicHash::Sha256);

    HttpRequest request;
    request.method = "GET";
    request.url = QUrl(url);
    request.headers.push_back({"user-agent", "ClaudeGG"});
    request.headers.push_back({"accept", "application/octet-stream"});
    request.idle_timeout_ms = 60000;
    //  The file of a release is served from another host, by a redirect. The
    //  request carries nothing that must not go along.
    request.follow_redirects = true;

    if (m_progress){
        m_progress(Stage::DOWNLOADING, 0, m_size);
    }
    m_call = m_transport.send(
        request,
        [this](const QByteArray& piece){
            if (!m_file){
                return;
            }
            if (m_file->write(piece) != piece.size()){
                m_file->close();
            }
            m_hash->addData(piece);
            m_received += piece.size();
            if (m_progress){
                m_progress(Stage::DOWNLOADING, m_received, m_size);
            }
        },
        [this](const HttpResponse& response){
            std::shared_ptr<HttpCall> call = std::move(m_call);
            downloaded(response);
        }
    );
    if (!m_call){
        m_file->remove();
        m_file.reset();
        fail_later(tr_ui("There is no connection to use."));
    }
}

void UpdateDownload::downloaded(const HttpResponse& response){
    //  A connection that hands the whole body at the end (the tests).
    if (m_file && response.ok() && !response.body.isEmpty()){
        m_file->write(response.body);
        m_hash->addData(response.body);
        m_received += response.body.size();
    }
    QString error;
    if (!response.error.isEmpty()){
        error = tr_ui("The download broke off: %1").arg(response.error);
    }else if (!response.ok()){
        error = tr_ui("GitHub answered with the status %1.").arg(response.status);
    }else if (!m_file || !m_file->isOpen()){
        error = tr_ui("The package could not be written to the disk. Is it full?");
    }
    if (!error.isEmpty()){
        if (m_file){
            m_file->remove();
            m_file.reset();
        }
        finish(false, error, QString());
        return;
    }

    if (m_progress){
        m_progress(Stage::CHECKING, m_received, m_size);
    }
    m_file->close();
    const QString actual = QString::fromLatin1(m_hash->result().toHex());
    if (actual != m_sha256){
        m_file->remove();
        m_file.reset();
        finish(false, tr_ui(
            "The package that came in is not the one the release lists (its SHA-256 is different). "
            "It was deleted and nothing was installed."
        ), QString());
        return;
    }
    const QString zip = m_folder + PACKAGE_FILE_NAME;
    QFile::remove(zip);
    if (!m_file->rename(zip)){
        m_file->remove();
        m_file.reset();
        finish(false, tr_ui("The package could not be written to the disk. Is it full?"), QString());
        return;
    }
    m_file.reset();

    //  Unpacking takes a while: not on the thread of the window.
    if (m_progress){
        m_progress(Stage::UNPACKING, m_received, m_size);
    }
    const QString folder = m_folder + "package/";
    m_worker = std::thread([this, zip, folder]{
        QString unpack_error;
        const bool unpacked = unpack_zip(zip, folder, unpack_error, &m_cancel);
        QMetaObject::invokeMethod(&m_context, [this, unpacked, unpack_error, zip, folder]{
            if (m_worker.joinable()){
                m_worker.join();
            }
            //  The zip is not needed once it is unpacked.
            QFile::remove(zip);
            if (!unpacked){
                QDir(folder).removeRecursively();
                finish(false, unpack_error, QString());
                return;
            }
            const QString root = package_root(folder);
            if (root.isEmpty()){
                finish(false, tr_ui("The package has no %1 in it.").arg(PROGRAM_FILE_NAME), QString());
                return;
            }
            finish(true, QString(), root);
        }, Qt::QueuedConnection);
    });
}



}
}
