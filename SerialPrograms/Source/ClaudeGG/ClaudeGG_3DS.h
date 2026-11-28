/*  Claude GG Nintendo 3DS (Luma3DS InputRedirection and NTR-HR over Wi-Fi)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A 3DS with Luma3DS is worked over the home network, without a board or a
 *  capture card:
 *
 *  - The buttons go to Luma3DS's own InputRedirection (Rosalina menu, Misc.
 *    settings): UDP to port 4950 of the 3DS, 20 bytes of state each time.
 *  - The picture comes from NTR-HR (GPL-2.0, a separate project, a New 3DS
 *    recommended): a command over TCP to port 8000 of the 3DS starts the
 *    stream, and the 3DS sends both screens as JPEG to UDP port 8001 of the
 *    computer.
 *
 *  Both protocols are written here from what their open clients do
 *  (InputRedirectionClient-Qt, Snickerstream, Chokistream); no code of
 *  theirs is in it.
 *
 *  The console's list ("Nintendo 3DS") has two programs: one that starts the
 *  stream and checks a button, and Claude Plays, with the tools of
 *  ClaudePlays_AnyGame.h and a touch on the lower screen.
 *
 *  Experimental: not tried on a 3DS yet.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_3DS_H
#define PokemonAutomation_ClaudeGG_3DS_H

#include <stddef.h>
#include <stdint.h>
#include <string>
#include <vector>
#include <QByteArray>
#include <QImage>
#include "CommonFramework/Panels/PanelList.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace ThreeDS{


//  The name of the list, as the page with the games shows it (and as
//  consoles_of_game() knows it).
extern const char* const LIST_NAME;

//  The ports: InputRedirection and NTR on the 3DS, the stream on the computer.
constexpr int INPUT_PORT = 4950;
constexpr int NTR_PORT = 8000;
constexpr int STREAM_PORT = 8001;

//  The screens.
constexpr int TOP_WIDTH = 400;
constexpr int TOP_HEIGHT = 240;
constexpr int BOTTOM_WIDTH = 320;
constexpr int BOTTOM_HEIGHT = 240;


class ThreeDSList : public PanelListDescriptor{
public:
    ThreeDSList();

protected:
    virtual std::vector<PanelEntry> make_panels() const override;
};

//  How many programs the list has (for the test).
size_t program_count();


//  What is held on the 3DS, as InputRedirection takes it.
struct PadState{
    //  By the names Claude uses: A, B, X, Y, L, R, ZL, ZR, START, SELECT, UP,
    //  DOWN, LEFT, RIGHT, HOME. Other names are left out.
    std::vector<std::string> buttons;
    //  The circle pad and the C-stick (New 3DS), -1 to 1, y up.
    double circle_x = 0;
    double circle_y = 0;
    double cstick_x = 0;
    double cstick_y = 0;
    //  A touch on the lower screen, in its pixels (320 x 240). -1: none.
    int touch_x = -1;
    int touch_y = -1;
};

//  The 20 bytes of InputRedirection for "state".
QByteArray input_packet(const PadState& state);

//  The 84 bytes of NTR's command 901, which starts the stream: "top" first
//  (or the lower screen), "priority" 1 to 255 (how many pictures of that
//  screen for one of the other), "quality" 10 to 100 (of the JPEG), "qos"
//  the bandwidth NTR may use (its own unit; 105 and above: no limit).
QByteArray ntr_start_packet(bool top, int priority, int quality, int qos);
//  The 84 bytes of NTR's heartbeat (command 0).
QByteArray ntr_heartbeat_packet(uint32_t sequence);


//  Puts the pictures of NTR's stream together: each UDP packet is a header
//  of 4 bytes (the picture's number; its screen in the low four bits of the
//  second byte, 1 in its high four bits on the last packet; the format; the
//  packet's place, from 0) and a piece of the JPEG.
class FrameAssembler{
public:
    //  One packet. True when it ends a picture: "top" says of which screen,
    //  and "jpeg" has the picture's bytes (whole, ending in FF D9).
    bool add(const char* data, size_t size, bool& top, QByteArray& jpeg);

private:
    struct Partial{
        bool active = false;
        uint8_t frame = 0;
        uint8_t next = 0;
        QByteArray bytes;
    };
    Partial m_screens[2];   //  0: the lower screen, 1: the top
};

//  A picture of a screen as NTR sends it (turned on its side: 240 wide)
//  the right way round.
QImage upright(const QImage& raw);

//  Both screens in one picture as Claude sees it: the top screen (400 x 240)
//  above the lower one (320 x 240), centered, on black. A screen that has
//  not come yet is black.
QImage both_screens(const QImage& top, const QImage& bottom);

//  A point of that picture of "width" x "height" on the lower screen (320 x
//  240). False: the point is not on the lower screen.
bool touch_point(int x, int y, int width, int height, int& screen_x, int& screen_y);


}
}
}
#endif
