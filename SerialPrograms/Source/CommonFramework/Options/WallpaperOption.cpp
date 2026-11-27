/*  Wallpaper Option
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

//#include "CommonFramework/Globals.h"
#include <QString>
#include "ClaudeGG/ClaudeGG_Theme.h"
#include "WallpaperOption.h"

namespace PokemonAutomation{



WallpaperOption::~WallpaperOption(){
    IMAGE_OVERLAY.remove_listener(*this);
    IMAGE_FIT.remove_listener(*this);
    IMAGE_PATH.remove_listener(*this);
}
WallpaperOption::WallpaperOption()
    : GroupOption(
        //  ClaudeGG: a picture of your own behind the screens with the games
        //  and the programs. Off until asked for: then Claude GG's own
        //  background. "Restore Defaults" goes back to it.
        "Background: a picture of your own",
        LockMode::UNLOCK_WHILE_RUNNING,
        EnableMode::DEFAULT_DISABLED,
        true
    )
    , IMAGE_PATH(
        "<b>Picture:</b><br>"
        "Shown behind the screens with the games and the programs. "
        "Empty, or turned off: Claude GG's own background.",
        LockMode::UNLOCK_WHILE_RUNNING,
        "",
        "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*)",
        "Select a PNG, JPEG, BMP, or WebP image"
    )
    , IMAGE_FIT(
        "<b>How the picture fits:</b>",
        {
            {WallpaperImageFitMode::FILL, "fill", "Fill (crop to window)"},
            {WallpaperImageFitMode::FIT, "fit", "Fit (show entire image)"},
            {WallpaperImageFitMode::STRETCH, "stretch", "Stretch"},
            {WallpaperImageFitMode::TILE, "tile", "Tile"},
        },
        LockMode::UNLOCK_WHILE_RUNNING,
        WallpaperImageFitMode::FILL
    )
    , IMAGE_OVERLAY(
        "<b>Darken the picture (%):</b><br>Increase this to keep the texts readable on a light or busy picture.",
        LockMode::UNLOCK_WHILE_RUNNING,
        35, 0, 100
    )
{
    PA_ADD_OPTION(IMAGE_PATH);
    PA_ADD_OPTION(IMAGE_FIT);
    PA_ADD_OPTION(IMAGE_OVERLAY);

    IMAGE_PATH.add_listener(*this);
    IMAGE_FIT.add_listener(*this);
    IMAGE_OVERLAY.add_listener(*this);
}


void WallpaperOption::load_json(const JsonValue& json){
    GroupOption::load_json(json);
    apply();
}
void WallpaperOption::on_config_value_changed(void* object){
    apply();
    ConfigOption::report_value_changed(this);
}
void WallpaperOption::on_set_enabled(bool enabled){
    apply();
}
void WallpaperOption::apply(){
    ClaudeGG::BackgroundFit fit = ClaudeGG::BackgroundFit::FILL;
    switch ((WallpaperImageFitMode)IMAGE_FIT){
    case WallpaperImageFitMode::FILL:
        fit = ClaudeGG::BackgroundFit::FILL;
        break;
    case WallpaperImageFitMode::FIT:
        fit = ClaudeGG::BackgroundFit::FIT;
        break;
    case WallpaperImageFitMode::STRETCH:
        fit = ClaudeGG::BackgroundFit::STRETCH;
        break;
    case WallpaperImageFitMode::TILE:
        fit = ClaudeGG::BackgroundFit::TILE;
        break;
    }
    const std::string path = enabled() ? (std::string)IMAGE_PATH : std::string();
    ClaudeGG::set_custom_background(QString::fromStdString(path), fit, (int)(uint8_t)IMAGE_OVERLAY);
}






}
