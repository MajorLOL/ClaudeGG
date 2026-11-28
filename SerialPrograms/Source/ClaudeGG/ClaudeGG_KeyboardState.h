/*  ClaudeGG Keyboard State
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The keys held on the keyboard of a board that plays a keyboard (HID:
 *  Keyboard, for an iPhone with Full Keyboard Access), as a controller
 *  state: what the program Macro records and plays (ClaudeGG_Macro.h).
 *  Pokemon Automation has no such state for its keyboard, so its keyboard
 *  passes nothing on to a recording; the keyboard now does
 *  (StandardHid_Keyboard.cpp, run_controller_input()).
 *
 *  In a file: {"keys": [4, 40]}, the HID codes of the keys held. Nothing
 *  held: no "keys".
 *
 */

#ifndef PokemonAutomation_ClaudeGG_KeyboardState_H
#define PokemonAutomation_ClaudeGG_KeyboardState_H

#include <set>
#include <string>
#include <vector>
#include "ControllerInput/Keyboard/KeyboardHidButtons.h"
#include "Controllers/ControllerState.h"

namespace PokemonAutomation{
namespace ClaudeGG{


class KeyboardMacroState : public ControllerState{
public:
    KeyboardMacroState() = default;
    explicit KeyboardMacroState(const std::set<KeyboardKey>& held);

    virtual void clear() override;
    virtual bool operator==(const ControllerState& x) const override;
    virtual bool is_neutral() const override;

    virtual void load_json(const JsonObject& json) override;
    virtual JsonObject to_json() const override;

    //  Holds the keys for "duration", then the next step comes. Nothing held:
    //  only the wait.
    virtual void execute(
        Cancellable* scope,
        bool enable_logging,
        AbstractController& controller,
        Milliseconds duration
    ) const override;

public:
    //  Sorted, each once.
    std::vector<KeyboardKey> keys;
};

//  The name of a key: "A", "ENTER", "LEFT_SHIFT". A code without a name:
//  "0x87".
std::string keyboard_key_name(KeyboardKey key);


}
}
#endif
