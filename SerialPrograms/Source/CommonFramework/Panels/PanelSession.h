/*  Panel Session
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#ifndef PokemonAutomation_PanelSession_H
#define PokemonAutomation_PanelSession_H

#include <stddef.h>
#include <vector>
#include "Common/Cpp/UiWrapper.h"
#include "PanelDescriptor.h"

class QWidget;

namespace PokemonAutomation{

class JsonValue;
class ConfigOption;
class VideoFeed;
class ControllerSession;
class VideoSession;

// Class to represent one instance of a pokemon automation program.
// Since programs are listed in the program panels, so this class is called PanelSession.
// Its derived classes hold all the program data and program logic. It also calls
// `make_widget()` to generate the UI for the program.
class PanelSession : public UiState<PanelSession>{
public:
    explicit PanelSession(const PanelDescriptor& descriptor);
    virtual ~PanelSession() = default;

    const PanelDescriptor& descriptor() const{ return m_descriptor; }

    void save_settings() const;


public:
    virtual void restore_defaults(){}
    virtual JsonValue to_json() const;
    virtual void load_json(const JsonValue& json);
    void load_json_from_global();


public:
    //  ClaudeGG: the options of the panel, for the setup, which shows them
    //  next to its list of programs without opening the panel. Null: the panel
    //  has no options of its own.
    virtual ConfigOption* config_options(){ return nullptr; }

    //  ClaudeGG: the video of console number "index" (0 is the first) of the
    //  panel, for the chat, which can be asked to look at the game. Null: the
    //  panel has no console, or not that many (or none is started).
    virtual VideoFeed* console_video(size_t index){ (void)index; return nullptr; }

    //  ClaudeGG: the controllers of the panel's consoles, with the number of
    //  the console each belongs to (1 is the first), for the header of the main
    //  window, which shows which controller is open and whether it is
    //  connected. Empty: the panel has no console.
    struct ConsoleController{
        size_t console;
        ControllerSession* session;
    };
    virtual std::vector<ConsoleController> console_controllers(){ return {}; }

    //  ClaudeGG: the video of console number "index" (0 is the first) with its
    //  source, for that header: which capture card is chosen and whether
    //  pictures come in. Null as console_video().
    virtual VideoSession* console_video_session(size_t index){ (void)index; return nullptr; }


protected:
    const PanelDescriptor& m_descriptor;
};



}
#endif
