/*  Multi-Console Panel Session
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#ifndef PokemonAutomation_GameConsole_MultiConsolePanelSession_H
#define PokemonAutomation_GameConsole_MultiConsolePanelSession_H

#include "CommonFramework/Panels/PanelSession.h"
#include "GameConsole/MultiConsolePanel.h"
#include "MultiConsoleSystemSession.h"

namespace PokemonAutomation{
namespace GameConsole{



class MultiConsolePanelSession final : public UiState<MultiConsolePanelSession, PanelSession>{
public:
    bool try_shutdown();
    ~MultiConsolePanelSession();
    MultiConsolePanelSession(const MultiConsolePanelDescriptor& descriptor);


public:
    const MultiConsolePanelDescriptor& descriptor() const{ return m_descriptor; }

    Logger& logger(){ return m_system.logger(); }
    MultiConsoleSystemSession& system(){ return m_system; }
    ConfigOption& options();
    //  ClaudeGG: the options without the panel (see PanelSession).
    virtual ConfigOption* config_options() override{ return &options(); }
    virtual VideoFeed* console_video(size_t index) override{
        return index < m_system.active_consoles() ? &m_system[index].video() : nullptr;
    }
    virtual std::vector<ConsoleController> console_controllers() override{
        std::vector<ConsoleController> out;
        for (size_t console = 0; console < m_system.active_consoles(); console++){
            ConsoleSystemSession& system = m_system[console];
            for (size_t c = 0; c < system.controllers(); c++){
                out.push_back({console + 1, &system.controller(c)});
            }
        }
        return out;
    }


public:
    //  Serialization

    virtual void restore_defaults() override;
    virtual JsonValue to_json() const override;
    virtual void load_json(const JsonValue& json) override;


private:
    const MultiConsolePanelDescriptor& m_descriptor;

    MultiConsoleSystemOption m_system_option;
    MultiConsoleSystemSession m_system;

    std::unique_ptr<MultiConsolePanelInstance> m_instance;
};





}
}
#endif
