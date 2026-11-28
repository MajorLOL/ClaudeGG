/*  Global Settings Panel
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#ifndef PokemonAutomation_GlobalSettingsPanel_H
#define PokemonAutomation_GlobalSettingsPanel_H

#include "Common/Cpp/Containers/Pimpl.h"
#include "Common/Cpp/Options/EnumDropdownOption.h"
#include "Common/Cpp/Options/ConfigOption.h"
#include "Common/Cpp/Options/StaticTextOption.h"
#include "Common/Cpp/Options/BooleanCheckBoxOption.h"
#include "Common/Cpp/Options/StringOption.h"
#include "Common/Cpp/Options/SimpleIntegerOption.h"
#include "Common/Cpp/Options/ButtonOption.h"
#include "CommonFramework/Options/WallpaperOption.h"
#include "CommonFramework/Panels/OptionsPanel.h"
#include "CommonFramework/ResourceDownload/SettingsResourceDownloadOptions.h"
#include "CommonFramework/ResourceDownload/SettingsResourceDownloadTable.h"

//#include <iostream>
//using std::cout;
//using std::endl;

namespace PokemonAutomation{

class CheckForUpdatesOption;
class ThemeSelectorOption;
class StarterColorOption;
class ResolutionOption;
class KeyboardLayoutOption;
class StreamHistoryOption;
class SleepSuppressOptions;
class DeviceAliasOptions;
namespace Integration{
    class DiscordSettingsOption;
}
class AudioPipelineOptions;
class VideoPipelineOptions;
class ErrorReportOption;
class ResourceDownload;


enum class OcrLibrary{
    PADDLE_OCR,
    TESSERACT,
};

//  ClaudeGG: the language of the menus, the settings and the explanations.
//  See ClaudeGG/ClaudeGG_Language.h.
enum class UiLanguage{
    ENGLISH,
    DUTCH,
    GERMAN,
    FRENCH,
    SPANISH,
    CUSTOM,     //  "Other": the file Languages/custom.json.
};

//  ClaudeGG: the console that the program is used with, as chosen in the
//  setup (the screen after the language).
enum class SetupConsole{
    NONE,       //  Not chosen yet.
    SWITCH,     //  Nintendo Switch (Switch 1 and OLED).
    SWITCH2,    //  Nintendo Switch 2.
    MOBILE,     //  An Android phone, on a Raspberry Pi (Mobile/agent).
    PS3,        //  PlayStation 3, through a wired board that it sees as a USB gamepad.
    XBOX,       //  The original Xbox, through that board and a Pico with OGX-Mini.
    RETRO,      //  PlayStation, PlayStation 2, GameCube, Nintendo 64, Dreamcast: a wireless board and BlueRetro.
    XBOX360,    //  An Xbox 360: the wired board and a Pico with OGX-Mini-2026 (XInput, with the console's check).
    PS_REMOTE,  //  PlayStation 4 and 5 through Remote Play on the computer (chiaki-ng).
    XBOX_REMOTE,//  Xbox One and Series through Remote Play on the computer (xbox.com/remoteplay).
    IPHONE,     //  An iPhone, with the wired board as a keyboard (Full Keyboard Access).
    PS_CLASSIC, //  The PlayStation Classic: the wired board and a Pico with OGX-Mini (its PS Classic mode).
};


class FolderInputOption : public StringOption{
public:
    using StringOption::StringOption;

    virtual void sanitize(std::string& str) override{
        if (!str.empty() && str.back() != '/'){
            str += '/';
        }
    }
};




class GlobalSettings : public BatchOption, private ConfigOption::Listener, private ButtonListener{
    ~GlobalSettings();
    GlobalSettings();
public:
    static GlobalSettings& instance();

    virtual JsonValue to_json() const override;
    virtual void load_json(const JsonValue& json) override;

    void connect_row_with_download(const std::string& resource_slug, std::shared_ptr<ResourceDownload>& download_ptr);

private:
    virtual void on_config_value_changed(void* object) override;
    virtual void on_press(ButtonCell& button) override;

public:
    Pimpl<CheckForUpdatesOption> CHECK_FOR_UPDATES;

    //  ClaudeGG: the language, the setup (language and microcontroller),
    //  and whether its questions still have to be asked at the next start.
    EnumDropdownOption<UiLanguage> LANGUAGE;
    EnumDropdownOption<SetupConsole> GAME_CONSOLE;
    //  The Raspberry Pi of a phone (the console "mobile"): where its agent is.
    //  The token of the agent is not here: it is kept apart, like the keys of
    //  the assistant (see ClaudeGG_Mobile.h).
    StringOption MOBILE_HOST;
    SimpleIntegerOption<uint16_t> MOBILE_PORT;
    ButtonOption OPEN_SETUP_BUTTON;
    BooleanCheckBoxOption ASK_LANGUAGE;
    BooleanCheckBoxOption ASK_SETUP;
    BooleanCheckBoxOption ASK_GAME;
    BooleanCheckBoxOption ASK_PROGRAM;
    BooleanCheckBoxOption KEEP_SCREEN_ON;

    ButtonOption OPEN_BASE_FOLDER_BUTTON;
    StringOption STATS_FILE;
    FolderInputOption TEMP_FOLDER;

    Pimpl<ThemeSelectorOption> THEME;
    Pimpl<StarterColorOption> STARTER_COLOR;
    WallpaperOption WALLPAPER;
    EnumDropdownOption<OcrLibrary> OCR_LIBRARY;
    StaticTextOption OCR_WARNING;
    SettingsResourceDownloadTable RESOURCE_DOWNLOAD_TABLE;
    SettingsDownloadError DOWNLOAD_ERROR;
    Pimpl<ResolutionOption> WINDOW_SIZE;
    Pimpl<ResolutionOption> LOG_WINDOW_SIZE;
    BooleanCheckBoxOption LOG_WINDOW_STARTUP;
    //  ClaudeGG: the short film that plays first when the program starts.
    BooleanCheckBoxOption PLAY_INTRO;

    Pimpl<KeyboardLayoutOption> KEYBOARD_CONTROLS_LAYOUT;

    Pimpl<DeviceAliasOptions> DEVICE_ALIASES;

    Pimpl<StreamHistoryOption> STREAM_HISTORY;
    Pimpl<SleepSuppressOptions> SLEEP_SUPPRESS;

    SectionDividerOption m_discord_settings;
    BooleanCheckBoxOption RICH_PRESENCE;
    BooleanCheckBoxOption ALL_STATS;
    Pimpl<Integration::DiscordSettingsOption> DISCORD;

    SectionDividerOption m_advanced_options;

    BooleanCheckBoxOption DUMP_VIDEO_FORMATS;
    BooleanCheckBoxOption SAVE_DEBUG_IMAGES;
    BooleanCheckBoxOption SAVE_DEBUG_VIDEOS_ON_SWITCH;
//    BooleanCheckBoxOption NAUGHTY_MODE_OPTION;

    Pimpl<AudioPipelineOptions> AUDIO_PIPELINE;
    Pimpl<VideoPipelineOptions> VIDEO_PIPELINE;

    BooleanCheckBoxOption ENABLE_LIFETIME_SANITIZER0;

    Pimpl<ErrorReportOption> ERROR_REPORTS;

    StringOption DEVELOPER_TOKEN;

    // The mode that does not run Qt GUI, but instead runs all the unit tests.
    // See Tests/CommandLineTests.h.
    bool COMMAND_LINE_TEST_MODE = false;
};





class GlobalSettingsPanel;

class GlobalSettings_Descriptor : public OptionsPanelDescriptor{
public:
    GlobalSettings_Descriptor();
public:
    using Wrapper = OptionsPanelWrapper<GlobalSettingsPanel>;
    static Wrapper& instance();
};


class GlobalSettingsPanel : public OptionsPanelInstance{
public:
    using Descriptor = GlobalSettings_Descriptor;
    GlobalSettingsPanel();
private:
    GlobalSettings& settings;
};






}
#endif
