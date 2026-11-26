/*  Claude GG Main Window (the host)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The program is one window: the overview of the installations. An
 *  installation is a process of its own (see ClaudeGG_Instances.h: its folder,
 *  its capture card, its microcontroller) but it has no window of its own: it is
 *  started with
 *
 *      ClaudeGG.exe --installation <id> --embed-in <window>
 *
 *  and its windows (the intro and the setup, the games, the main window) are
 *  children of a window of this one (see ClaudeGG_Embed.h). This window shows
 *  the one that is opened and hides the others; the way back to the overview
 *  is the button "Installations" in every installation. There is one
 *  button on the taskbar, and closing this window closes the installations
 *  that are in it.
 *
 *  Windows only (a window of another process can only be a child of a window
 *  here); elsewhere, and with --standalone, installation 1 is a window of its
 *  own, as before. Starting the program with no option, or with --host, makes
 *  this the main window.
 *
 *  The workflow runs
 *
 *      ClaudeGG.exe --host-test <folder>
 *
 *  that opens installations in this window, as a person would: first a window
 *  that is only a colour (the probe of ClaudeGG_Embed.h) as an installation, to
 *  check what Windows says about the windows, then the program itself as two
 *  installations (its setup, and its main window). Pictures go to the folder.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_Host_H
#define PokemonAutomation_ClaudeGG_Host_H

#include <QString>

class QApplication;

namespace PokemonAutomation{
namespace ClaudeGG{


extern const char* const HOST_OPTION;           //  --host
extern const char* const STANDALONE_OPTION;     //  --standalone
extern const char* const HOST_TEST_OPTION;      //  --host-test <folder>

//  Reads what the program was started with (first thing in main()). Without an
//  option at all, on Windows, this process is the main window.
void read_host_options(int argc, char* argv[]);

//  This process is the main window (the overview, with the installations in it).
bool is_host();

//  The main window, until it is closed. 0 when it ends well.
int run_host(QApplication& application);

//  The test (see above).
int run_host_test(QApplication& application, const QString& folder);


}
}
#endif
