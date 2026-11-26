/*  Theme Selector Option
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#include <QCoreApplication>
#include "ThemeSelectorOption.h"

namespace PokemonAutomation{

namespace{

//  What the two options are set to.
UiThemeMode current_mode = UiThemeMode::POCKET_NIGHT;
ClaudeGG::Starter current_starter = ClaudeGG::Starter::FIRE;

void apply(){
    //  Options can be made before the application is: the main window
    //  applies the theme when it starts.
    if (QCoreApplication::instance() == nullptr){
        return;
    }
    ClaudeGG::apply_theme(current_mode, current_starter);
}

}

void apply_current_theme(){
    apply();
}



ThemeSelectorOption::ThemeSelectorOption()
    : EnumDropdownOption<UiThemeMode>(
        "<b>Theme:</b><br>"
        "Night and Day are Claude GG's own looks. "
        "The two classic ones are those of Pok\u00e9mon Automation.",
        {
            //  Other names than before ("default", "dark"): a setting saved
            //  by an older version starts with Night.
            {UiThemeMode::POCKET_NIGHT, "pocket-night",  "Night"},
            {UiThemeMode::POCKET_DAY,   "pocket-day",    "Day"},
            {UiThemeMode::DEFAULT_MODE, "classic",       "Classic (light)"},
            {UiThemeMode::DARK_MODE,    "classic-dark",  "Classic (dark)"},
        },
        LockMode::LOCK_WHILE_RUNNING,
        UiThemeMode::POCKET_NIGHT
    )
{}

bool ThemeSelectorOption::set_value(size_t value){
    if (!IntegerEnumDropdownOption::set_value(value)){
        return false;
    }
    current_mode = static_cast<UiThemeMode>(value);
    apply();
    return true;
}
void ThemeSelectorOption::load_json(const JsonValue& json){
    IntegerEnumDropdownOption::load_json(json);
    current_mode = static_cast<UiThemeMode>(current_value());
    apply();
}



StarterColorOption::StarterColorOption()
    : EnumDropdownOption<ClaudeGG::Starter>(
        "<b>Starter color:</b><br>"
        "The color of the Night and Day themes: pick your starter.",
        {
            {ClaudeGG::Starter::FIRE,    "fire",     "Fire"},
            {ClaudeGG::Starter::WATER,   "water",    "Water"},
            {ClaudeGG::Starter::GRASS,   "grass",    "Grass"},
        },
        LockMode::LOCK_WHILE_RUNNING,
        ClaudeGG::Starter::FIRE
    )
{}

bool StarterColorOption::set_value(size_t value){
    if (!IntegerEnumDropdownOption::set_value(value)){
        return false;
    }
    current_starter = static_cast<ClaudeGG::Starter>(value);
    apply();
    return true;
}
void StarterColorOption::load_json(const JsonValue& json){
    IntegerEnumDropdownOption::load_json(json);
    current_starter = static_cast<ClaudeGG::Starter>(current_value());
    apply();
}






}
