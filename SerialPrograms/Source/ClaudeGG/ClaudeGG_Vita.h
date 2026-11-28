/*  Claude GG PlayStation Vita (vita-agent-bridge over Wi-Fi)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A PlayStation Vita with HENkaku Enso and taiHEN runs vita-agent-bridge
 *  (MIT, Copyright (c) 2026 Mitchell Vizensky, a separate project): a kernel
 *  plugin that presses its buttons, moves its sticks and touches its front
 *  screen, and a service in the shell that takes commands over TCP (port
 *  1348) and gives pictures of the screen. No board and no capture card: the
 *  program talks to the Vita over the home network.
 *
 *  Every command is one connection: "AUTH <token> <command>\n", with the 64
 *  hexadecimal characters of the token that is on the Vita too. The answer is
 *  a line (OK ... or ERR ...), and for "shot" two pictures (the game's, then
 *  the shell's), each a header of 24 bytes ("VSHT", width, height, pitch,
 *  format, size, little-endian) and its RGBA rows.
 *
 *  The console's list ("PlayStation Vita") has two programs: one that checks
 *  the connection and saves a picture, and Claude Plays, with the tools of
 *  ClaudePlays_AnyGame.h and a touch on the screen.
 *
 *  Experimental: not tried on a Vita yet.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_Vita_H
#define PokemonAutomation_ClaudeGG_Vita_H

#include <stddef.h>
#include <stdint.h>
#include <string>
#include <vector>
#include <QByteArray>
#include <QImage>
#include "CommonFramework/Panels/PanelList.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace Vita{


//  The name of the list, as the page with the games shows it (and as
//  consoles_of_game() knows it).
extern const char* const VITA_LIST_NAME;

//  The port of vita-agent-bridge.
constexpr int BRIDGE_PORT = 1348;

//  The Vita's screen.
constexpr int SCREEN_WIDTH = 960;
constexpr int SCREEN_HEIGHT = 544;


class VitaList : public PanelListDescriptor{
public:
    VitaList();

protected:
    virtual std::vector<PanelEntry> make_panels() const override;
};

//  How many programs the list has (for the test).
size_t vita_program_count();

//  The bit of a button in the mask of "hold" (SceCtrl, as the bridge's own
//  command line has them), by the name Claude uses: CROSS, CIRCLE, SQUARE,
//  TRIANGLE, L, R, START, SELECT, UP, DOWN, LEFT, RIGHT, HOME (the PS
//  button). 0: not a button of the Vita.
uint32_t button_bit(const std::string& name);

//  A stick from -1 to 1 (y up) as the bridge has it: 0 to 255, 128 in the
//  middle, y down.
int stick_value(double value, bool is_y);

//  The token as it is typed: 64 hexadecimal characters, spaces around it left
//  out. Empty: not a token.
std::string token_of(const std::string& typed);

//  A touch at (x, y) of a picture of "width" x "height" (what Claude saw), on
//  the Vita's screen (960 x 544), kept inside it.
void touch_point(int x, int y, int width, int height, int& screen_x, int& screen_y);

//  The answer of "shot" as one picture: the game's picture with the shell's
//  over it (its alpha). A plane with size 0 is not there. Null: no picture
//  in "data" (too short, or no header).
QImage picture_of_shot(const QByteArray& data);


}
}
}
#endif
