/*  ClaudeGG Updater
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  Installing a newer build (found by ClaudeGG_Update.h) from the program
 *  itself, on Windows.
 *
 *  1.  Download. The package (ClaudeGG-Windows.zip) of the release goes to
 *      Updates/<version>/ in the folder of the data (the folder the program
 *      was started in). Its SHA-256 is checked against the one the release
 *      lists; a package that does not match is deleted and nothing else
 *      happens.
 *  2.  Unpack, into Updates/<version>/package/, and check that ClaudeGG.exe
 *      is in it.
 *  3.  Then one of two:
 *
 *      Update this copy. A running program cannot overwrite its own files,
 *      so the program starts the NEW ClaudeGG.exe from the unpacked package
 *      with --apply-update and closes. That process waits until the old one
 *      has ended, puts the new files over the old ones and starts the
 *      program again. What is the user's is never overwritten
 *      (keep_users_file()): the settings, the other installations, the own
 *      languages, the pictures and logs. A file that was replaced is first
 *      moved to Updates/<version>/backup/; when any file cannot be written
 *      (still in use, no rights) everything is put back as it was and the
 *      old build starts again. Either way the program says so at its next
 *      start (take_update_outcome()).
 *
 *      Install next to this copy. The package goes into a folder of its own
 *      next to the folder of this program ("Claude GG 0.2.0.12"), with a
 *      copy of the settings, and this copy stays as it is. Two builds side
 *      by side, each with its own data.
 *
 *  Nothing here asks the network by itself: UpdateDownload is started by the
 *  window of the update (ClaudeGG_UpdateDialog.h).
 *
 */

#ifndef PokemonAutomation_ClaudeGG_Updater_H
#define PokemonAutomation_ClaudeGG_Updater_H

#include <stdint.h>
#include <atomic>
#include <functional>
#include <memory>
#include <thread>
#include <QByteArray>
#include <QCryptographicHash>
#include <QFile>
#include <QObject>
#include <QString>
#include <QStringList>
#include "Assistant/Assistant_Http.h"

namespace PokemonAutomation{
namespace ClaudeGG{


//  ClaudeGG.exe --apply-update --target <folder> --data <folder> --wait-pid <n>
//      --build <version> [--no-restart] [--restart <arguments of the program> ...]
//  (--no-restart: the workflow's test, which only looks at the files.)
extern const char* const APPLY_UPDATE_OPTION;       //  --apply-update
//  ClaudeGG.exe --unpack-update <zip> <folder>: unpacks a package as a
//  download is, for the workflow's test (exit code 0: it has ClaudeGG.exe).
extern const char* const UNPACK_UPDATE_OPTION;      //  --unpack-update

//  The name of the program in a package.
extern const char* const PROGRAM_FILE_NAME;         //  "ClaudeGG.exe"


//  ---------------------------------------------------------------------
//  Folders and files
//  ---------------------------------------------------------------------

//  "<data>Updates/": the downloads, the packages and the backups. "data" ends with "/".
QString updates_folder(const QString& data);

//  A file of the program's folder (relative, with "/") that an update never
//  overwrites when it is there: everything in UserSettings/, Installations/,
//  Languages/, Screenshots/, DebugDumps/, ErrorDumps/, TempFiles/ and
//  Updates/, and the settings and logs at the top (*.json, *.log, *.ini).
//  A package that brings such a file only adds it when it is missing.
bool keep_users_file(const QString& relative_path);

//  The SHA-256 of a file, 64 digits in lower case; empty when it cannot be read.
QString file_sha256(const QString& path);

//  Unpacks a zip into "folder" (made when missing). Refuses names that leave
//  the folder ("..", a drive, a "/" at the start). False, with a reason, when
//  anything could not be read or written; "cancel" stops it between files.
bool unpack_zip(const QString& zip, const QString& folder, QString& error, const std::atomic<bool>* cancel = nullptr);

//  The folder in an unpacked package that has ClaudeGG.exe in it: the
//  folder itself or one folder in it (the package has "ClaudeGG/" at its
//  top). Empty when there is none.
QString package_root(const QString& unpacked);

//  A folder for a build next to the program's folder: "<parent>/Claude GG
//  <version>", or with " (2)", " (3)"... when that is taken. "program" is the
//  program's folder.
QString side_by_side_folder(const QString& program, int build);


//  ---------------------------------------------------------------------
//  Putting a package in place
//  ---------------------------------------------------------------------

struct CopyReport{
    int replaced = 0;   //  Files that were there and are new now.
    int added = 0;      //  Files that were not there.
    int kept = 0;       //  The user's files that were left as they were.
    QString error;      //  Why it stopped (everything was put back then).
};

//  Puts the files of "package" over "target", keeping the user's
//  (keep_users_file()). A replaced file is moved into "backup" first. When a
//  file cannot be written, everything that was done is undone and false is
//  returned. "attempts": how often a file that is in use is tried, half a
//  second apart (the old process may take a moment to let go of it).
bool copy_package(const QString& package, const QString& target, const QString& backup, CopyReport& report, int attempts = 1);

//  A copy of a folder with everything in it. False: something could not be copied.
bool copy_folder(const QString& from, const QString& to);

//  Installs a package next to the program: moves (or copies) it to "folder"
//  and copies the user's settings ("<data>UserSettings/" and the own
//  languages) along. False, with a reason.
bool install_side_by_side(const QString& package, const QString& folder, const QString& data, QString& error);


//  ---------------------------------------------------------------------
//  The step after the program has closed
//  ---------------------------------------------------------------------

//  Starts the new ClaudeGG.exe of "package" with --apply-update: it waits for
//  this process to end, then copies "package" over "target" and starts the
//  program in "data" with "restart_arguments". The caller closes the program
//  next. False: it could not be started.
bool start_apply_update(
    const QString& package, const QString& target, const QString& data,
    int build, const QStringList& restart_arguments, QString& error
);

//  The command line is one of --apply-update (or --unpack-update).
bool is_apply_update(int argc, char* argv[]);

//  What ClaudeGG.exe does with --apply-update (from main(), before anything
//  else of the program). Writes Updates/update.log and what happened
//  (take_update_outcome()). Returns the exit code.
int run_apply_update(int argc, char* argv[]);

//  What the last --apply-update left for the program to say, once: true when
//  there is something ("ok": it worked; "build": the new build; "message": what
//  went wrong). The note is deleted.
bool take_update_outcome(const QString& data, bool& ok, QString& build, QString& message);
//  What run_apply_update() leaves (for the tests).
bool write_update_outcome(const QString& data, bool ok, const QString& build, const QString& message);

//  Deletes what earlier updates left in Updates/ (the packages and backups;
//  not the log). What is still in use stays, for the next time.
void clean_old_updates(const QString& data);


//  ---------------------------------------------------------------------
//  The download
//  ---------------------------------------------------------------------

class UpdateDownload{
public:
    enum class Stage{ IDLE, DOWNLOADING, CHECKING, UNPACKING, DONE, FAILED };

    //  "transport" has to stay for as long as the download.
    explicit UpdateDownload(Assistant::HttpTransport& transport);
    ~UpdateDownload();
    UpdateDownload(const UpdateDownload&) = delete;
    void operator=(const UpdateDownload&) = delete;

    using Progress = std::function<void(Stage stage, qint64 done, qint64 total)>;
    //  "package": the folder of the unpacked program (package_root()); empty on failure.
    using Done = std::function<void(bool ok, const QString& error, const QString& package)>;

    //  Downloads "url" into "folder" (made when missing), checks it against
    //  "sha256", unpacks it into "<folder>package/". "size": what the release
    //  says, for the progress (0: unknown). The handlers are called from the
    //  event loop, never from inside start(). Does nothing while one runs.
    void start(
        const QString& url, const QString& sha256, qint64 size, const QString& folder,
        Progress progress, Done done
    );
    bool running() const{ return m_running; }

private:
    void finish(bool ok, const QString& error, const QString& package);
    void downloaded(const Assistant::HttpResponse& response);

    Assistant::HttpTransport& m_transport;
    std::shared_ptr<Assistant::HttpCall> m_call;
    bool m_running = false;
    QString m_sha256;
    QString m_folder;
    qint64 m_size = 0;
    qint64 m_received = 0;
    std::unique_ptr<QFile> m_file;
    std::unique_ptr<QCryptographicHash> m_hash;
    Progress m_progress;
    Done m_done;
    std::atomic<bool> m_cancel{false};
    std::thread m_worker;
    QObject m_context;      //  For what has to come from the event loop.
};



}
}
#endif
