/*  Claude GG Wii U (a Raspberry Pi as the GamePad)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The Wii U is played through its GamePad, and the GamePad is a Raspberry Pi:
 *  with a 5 GHz Wi-Fi adapter it runs vanilla-pipe (Vanilla, GPL-2.0, which
 *  makes the Wii U's own kind of Wi-Fi connection) and the bridge of
 *  WiiU/vanilla-bridge. The bridge takes buttons, sticks and touches as lines
 *  of text (port 51200) and gives the GamePad's screen as JPEG pictures
 *  (port 51202, the same stream as the agent of Mobile/, read here with
 *  MobileVideo). No board and no capture card: the picture is what the
 *  GamePad shows.
 *
 *  The console's list ("Nintendo Wii U") has two programs: one that pairs the
 *  Pi with the Wii U and checks that buttons and the picture work, and Claude
 *  Plays, with the tools of ClaudePlays_AnyGame.h and a touch on the screen.
 *
 *  Experimental: not tried on a Wii U yet.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_WiiU_H
#define PokemonAutomation_ClaudeGG_WiiU_H

#include <stddef.h>
#include <string>
#include "CommonFramework/Panels/PanelList.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace WiiU{


//  The name of the list, as the page with the games shows it (and as
//  consoles_of_game() knows it).
extern const char* const WIIU_LIST_NAME;

//  The ports of the bridge (its defaults).
constexpr int BRIDGE_COMMAND_PORT = 51200;
constexpr int BRIDGE_PICTURE_PORT = 51202;

//  The GamePad's screen.
constexpr int GAMEPAD_WIDTH = 854;
constexpr int GAMEPAD_HEIGHT = 480;


class WiiUList : public PanelListDescriptor{
public:
    WiiUList();

protected:
    virtual std::vector<PanelEntry> make_panels() const override;
};

//  How many programs the list has (for the test).
size_t wiiu_program_count();

//  The four symbols that the Wii U shows to pair a GamePad, as the user
//  types them, as the bridge takes them: "SHDC" for spade, heart, diamond,
//  club. Letters in either case, the digits 0 to 3 in that order, or the
//  symbols themselves; spaces are left out. Empty: not four symbols.
std::string sync_code_of(const std::string& typed);

//  A touch at (x, y) of a picture of "width" x "height" (what Claude saw), on
//  the GamePad's screen (854 x 480), kept inside it.
void touch_point(int x, int y, int width, int height, int& gamepad_x, int& gamepad_y);


}
}
}
#endif
