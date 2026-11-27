/*  Console Panel Session
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#ifndef PokemonAutomation_GameConsole_ConsolePanelSession_H
#define PokemonAutomation_GameConsole_ConsolePanelSession_H

#include "CommonFramework/Panels/PanelSession.h"
#include "GameConsole/ConsolePanel.h"
#include "ConsoleSystemSession.h"

namespace PokemonAutomation{
namespace GameConsole{



class ConsolePanelSession final : public UiState<ConsolePanelSession, PanelSession>{
public:
    bool try_shutdown();
    ~ConsolePanelSession();
    ConsolePanelSession(const ConsolePanelDescriptor& descriptor);


public:
    const ConsolePanelDescriptor& descriptor() const{ return m_descriptor; }

    Logger& logger(){ return m_system.logger(); }
    ConsoleSystemSession& system(){ return m_system; }
    ConfigOption& options();
    //  ClaudeGG: the options without the panel (see PanelSession).
    virtual ConfigOption* config_options() override{ return &options(); }
    virtual VideoFeed* console_video(size_t index) override{ return index == 0 ? &m_system.video() : nullptr; }
    virtual std::vector<ConsoleController> console_controllers() override{
        std::vector<ConsoleController> out;
        for (size_t c = 0; c < m_system.controllers(); c++){
            out.push_back({1, &m_system.controller(c)});
        }
        return out;
    }


public:
    virtual void restore_defaults() override;
    virtual JsonValue to_json() const override;
    virtual void load_json(const JsonValue& json) override;


private:
    const ConsolePanelDescriptor& m_descriptor;

    ConsoleSystemOption m_system_option;
    ConsoleSystemSession m_system;

    std::unique_ptr<ConsolePanelInstance> m_instance;
};





}
}
#endif
