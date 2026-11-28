/*  ClaudeGG Update Window
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The window that offers a newer build: what is new in it, and a button
 *  that installs it (ClaudeGG_Updater.h), over this copy or next to it.
 *
 *  At the start, installation 1 asks GitHub once whether there is a newer
 *  build (a few seconds after its window is up), unless "Check for updates
 *  when Claude GG starts" is off (in About, and in this window). When there
 *  is one, and it is not the build the user chose to skip, the window opens.
 *  Without an answer (no network, GitHub limits) nothing is shown: the check
 *  only writes to the log.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_UpdateDialog_H
#define PokemonAutomation_ClaudeGG_UpdateDialog_H

#include <memory>
#include <QString>
#include <QStringList>
#include "ClaudeGG_Update.h"

class QDialog;
class QWidget;

namespace PokemonAutomation{
namespace ClaudeGG{
namespace Assistant{
    class HttpTransport;
}


//  The settings of the updates (QSettings "ClaudeGG/Updates", for every copy).
bool update_check_at_start();               //  On unless turned off.
void set_update_check_at_start(bool on);
QString skipped_update();                   //  "0.2.0.12": not offered at the start.
void set_skipped_update(const QString& build);


//  Where this program is, and how to start it again.
struct UpdateTarget{
    QString program;            //  The folder of ClaudeGG.exe, with "/".
    QString data;               //  The folder of the data (installation 1's), with "/".
    QStringList restart;        //  The command line for the program after the update.
    //  Only for the tests: the update is downloaded and unpacked, but no
    //  process is started or closed ("next to it" is installed all the same,
    //  next to "program").
    bool dry_run = false;
};
UpdateTarget this_program();


//  The window, not shown yet. "transport" has to stay for as long as the
//  window; nullptr: the window makes a connection of its own. "at_start": it
//  was opened by the check at the start (it then offers to skip the build).
std::unique_ptr<QDialog> make_update_dialog(
    QWidget* parent, const UpdateResult& result, const UpdateTarget& target,
    Assistant::HttpTransport* transport, bool at_start
);

//  The same, shown without waiting, deleted when it is closed.
void show_update_dialog(QWidget* parent, const UpdateResult& result, bool at_start);


//  At the start of installation 1, once its window is up: says how the last
//  update went (when one ran), cleans up after it, and checks for a newer
//  build (see above). Does nothing in a test run.
void start_update_check_at_start(QWidget* window, const QString& project_url, const QString& build);



}
}
#endif
