/*  Claude GG Embedding
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The aim: one main window, and the installations in it. An installation stays
 *  a process of its own (a capture card or a microcontroller that hangs must not
 *  take the others along), but it has no window of its own to open: the main
 *  window, the overview of the installations, makes a place for it (a native child
 *  window) and the installation starts with
 *
 *      ClaudeGG.exe --installation 2 --embed-in <window>
 *
 *  and makes its windows children of that window. So the window of an
 *  installation is not on the taskbar, it opens inside the main window, and
 *  the main window shows and hides it.
 *
 *  This file is the mechanism. It is tried first with a window that is nothing
 *  but a colour (--embed-probe), in a test of the build (--embed-test <folder>)
 *  that starts the probe in a window of its own and checks, with the functions
 *  of Windows, that its window is a child of the window it was given, that it
 *  is visible and fills it, that it is red on the screen, and that it ends when
 *  the window it was given goes.
 *
 *  Windows only; elsewhere an installation has its own windows, as before.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_Embed_H
#define PokemonAutomation_ClaudeGG_Embed_H

#include <QString>
#include <QtGlobal>

class QApplication;
class QWidget;

namespace PokemonAutomation{
namespace ClaudeGG{


extern const char* const EMBED_IN_OPTION;       //  --embed-in <window>
extern const char* const EMBED_PROBE_OPTION;    //  --embed-probe
extern const char* const EMBED_TEST_OPTION;     //  --embed-test <folder>


//  Reads --embed-in <window> (the number of a native window of the process that
//  started this one). Call it first thing in main().
void read_embed_options(int argc, char* argv[]);

//  This process was told to put its windows in another one.
bool is_embedded();
quintptr embed_parent();

//  Makes a window of this installation a child of the window it was given, with
//  no frame, as large as that window (it follows its size). Call it before the
//  window is shown. False: nothing is embedded (not told to, or not Windows): the
//  window is a window of its own.
bool embed_instance_window(QWidget* window);

//  The windows of another process that are children of "parent": for the
//  main window to see that an installation has made its window.
int count_child_windows(quintptr parent, qint64 pid);

//  The windows of the process "pid" that are on the taskbar: visible, with no
//  owner and no parent (what the user sees as "a window of the program").
int count_top_level_windows(qint64 pid);

//  Gives the keyboard to the first window of the process "pid" that is a child
//  of "parent" (what is shown in the main window has to be typed in).
bool focus_child_window(quintptr parent, qint64 pid);

//  Takes the keyboard for a window of this process that is shown in the main
//  window (a click in a child window of another program does not give it the
//  keyboard by itself). Does nothing for a window that is not embedded.
void take_keyboard(QWidget* window);

//  What Windows says about the first window of the process "pid" that is a child
//  of "parent": the size of its inside and of the inside of "parent" (pixels),
//  whether it is visible and whether it has the style of a child. False: there
//  is none. Any of the pointers may be null.
bool describe_child_window(quintptr parent, qint64 pid, QSize* child_size, QSize* parent_size, bool* visible, bool* child_style);

//  What Windows says about every window of the process "pid" that is not a child
//  window (title, class, visible or not, owner, size): for a test to say what an
//  installation is doing when it has not made its window in the main window.
QString describe_process_windows(qint64 pid);

//  The probe (what a test starts) and the test.
int run_embed_probe(QApplication& application);
int run_embed_test(QApplication& application, const QString& folder);


}
}
#endif
