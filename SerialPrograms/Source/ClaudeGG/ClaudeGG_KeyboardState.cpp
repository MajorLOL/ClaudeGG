/*  ClaudeGG Keyboard State
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <algorithm>
#include <typeinfo>
#include "Common/Cpp/Json/JsonArray.h"
#include "Common/Cpp/Json/JsonObject.h"
#include "Controllers/StandardHid/StandardHid_Keyboard.h"
#include "ClaudeGG_KeyboardState.h"

namespace PokemonAutomation{
namespace ClaudeGG{


KeyboardMacroState::KeyboardMacroState(const std::set<KeyboardKey>& held)
    : keys(held.begin(), held.end())
{}

void KeyboardMacroState::clear(){
    keys.clear();
}
bool KeyboardMacroState::operator==(const ControllerState& x) const{
    if (typeid(*this) != typeid(x)){
        return false;
    }
    return keys == static_cast<const KeyboardMacroState&>(x).keys;
}
bool KeyboardMacroState::is_neutral() const{
    return keys.empty();
}

void KeyboardMacroState::load_json(const JsonObject& json){
    keys.clear();
    const JsonArray* list = json.get_array("keys");
    if (list == nullptr){
        return;
    }
    for (const JsonValue& item : *list){
        const int64_t code = item.to_integer_default(-1);
        if (code > 0 && code < 256){
            keys.emplace_back((KeyboardKey)code);
        }
    }
    std::sort(keys.begin(), keys.end());
    keys.erase(std::unique(keys.begin(), keys.end()), keys.end());
}
JsonObject KeyboardMacroState::to_json() const{
    JsonObject obj;
    if (!keys.empty()){
        JsonArray list;
        for (KeyboardKey key : keys){
            list.push_back((int64_t)key);
        }
        obj["keys"] = JsonValue(std::move(list));
    }
    return obj;
}

void KeyboardMacroState::execute(
    Cancellable* scope,
    bool,
    AbstractController& controller,
    Milliseconds duration
) const{
    controller.cast_with_exception<StandardHid::Keyboard>().issue_keys(
        scope, duration, duration, Milliseconds(0), keys
    );
}


}
}
