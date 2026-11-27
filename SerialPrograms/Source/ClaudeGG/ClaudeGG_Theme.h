/*  ClaudeGG Theme
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The look of the program. Two themes (Night and Day), each in the color
 *  of a starter (Fire, Water or Grass): the screens of the shell (the games, the
 *  programs, the buttons along the top) take the starter's color, the rest (the
 *  "screen") stays quiet. Qt's Fusion style with a palette of these colors
 *  draws the standard widgets, with a style sheet (Resources/theme.qss) on
 *  top of it. The two classic looks of Pokemon Automation stay available.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_Theme_H
#define PokemonAutomation_ClaudeGG_Theme_H

#include <stdint.h>
#include <QColor>
#include <QFont>
#include <QImage>
#include <QPalette>
#include <QString>
#include "Common/Cpp/ColoredText.h"

namespace PokemonAutomation{
namespace ClaudeGG{


enum class Starter{
    FIRE,
    WATER,
    GRASS,
};


struct ThemeColors{
    bool dark = true;

    //  The shell: the screens of the games and the programs, and the buttons along the top.
    QColor shell;
    QColor shell_deep;
    QColor shell_text;
    QColor shell_muted;

    //  The screen: everything else.
    QColor screen;
    QColor surface;
    QColor surface_alt;
    QColor field;
    QColor line;
    QColor text;
    QColor muted;
    QColor disabled;

    //  Buttons to press and things that are selected.
    QColor accent;
    QColor accent_hover;
    QColor accent_text;

    QColor ok;
    QColor warning;
    QColor danger;
};

ThemeColors make_theme_colors(bool dark, Starter starter);
QPalette make_palette(const ThemeColors& colors);
QString make_style_sheet(const ThemeColors& colors);

//  The colors of the theme in use. With a classic theme they are made of
//  the application's palette, so that the program's own widgets fit in.
const ThemeColors& theme_colors();

//  Applies a theme to the whole application: the style, the palette, the
//  style sheet and (Qt 6.8 and later) the color of the window frames.
//  Only on the main thread, once the QApplication exists.
void apply_theme(UiThemeMode mode, Starter starter);

//  The typeface of the name and the headings (Jersey 20, in the program's
//  resources). The application's font in bold if it cannot be loaded.
QFont display_font(int pixel_size);

//  One color mixed into another: part 0 gives "from", part 1 gives "to".
QColor mix_colors(const QColor& from, const QColor& to, double part);

//  The contrast of two colors as WCAG 2 counts it, 1 to 21.
double contrast_ratio(const QColor& a, const QColor& b);



//  A picture of your own behind the screens (the games, the programs, the
//  setup), instead of Claude GG's own background. Settings > "Background".
enum class BackgroundFit{
    FILL,       //  covers the screen, the edges cut off
    FIT,        //  all of the picture, black around it
    STRETCH,    //  to the size of the screen
    TILE,       //  the picture in its own size, again and again
};
//  An empty path: Claude GG's own background. "darken" (0 to 100) darkens
//  the picture so that the white texts on it stay readable. From any thread;
//  the picture is read the next time a screen is drawn.
void set_custom_background(const QString& path, BackgroundFit fit, int darken);

struct CustomBackground{
    //  Null: Claude GG's own background (none chosen, or it could not be read).
    QImage image;
    BackgroundFit fit = BackgroundFit::FILL;
    double darken = 0;          //  0 to 1
    //  Changes with every change of the setting: for the screens' caches.
    uint64_t generation = 0;
};
//  The picture as it is set now, read when the setting changed. Only on the
//  main thread.
const CustomBackground& custom_background();



}
}
#endif
