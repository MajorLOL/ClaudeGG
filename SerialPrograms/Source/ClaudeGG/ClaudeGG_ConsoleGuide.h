/*  ClaudeGG Console Guide
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The guide of the consoles: for each console what you need, how the parts
 *  are connected, the steps in short, how quick the controls are, what the
 *  games there are, what is known not to work yet, and what to try when it
 *  does not work. One page compares them all. It is a panel over the main
 *  window (the button "Consoles" along the top), and it does not change
 *  anything: the setup is where the board is flashed and the type is picked.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_ConsoleGuide_H
#define PokemonAutomation_ClaudeGG_ConsoleGuide_H

#include <QString>
#include <QStringList>

class QWidget;

namespace PokemonAutomation{
namespace ClaudeGG{


//  The guide as a widget, a child of "parent". "console_code" is the console
//  that is shown first ("switch", "switch2", "mobile", "ps3", "xbox",
//  "retro", "xbox360", "psremote", "xboxremote", "iphone", "psclassic",
//  "wiiu"); empty or unknown: the page that compares them all. It follows
//  the language. "open_setup" is called by its button "Open the setup"
//  (nothing: the button is not shown).
QWidget* make_console_guide(QWidget* parent, const QString& console_code, void (*open_setup)() = nullptr);

//  The codes of the consoles that the guide has a page for, in its order.
QStringList console_guide_codes();

//  The page of a console as HTML, in the current language (the guide shows
//  it; the self-test reads it). Empty or unknown code: the page that
//  compares them all.
QString console_guide_html(const QString& console_code);

//  Every English text of the guide (the language test checks that each
//  language has them all).
QStringList console_guide_texts();

//  The self-test of the guide: every console of the setup has a page, every
//  page has its parts. Returns the number of failures; writes them to the log
//  of the command line.
int console_guide_self_test();


}
}
#endif
