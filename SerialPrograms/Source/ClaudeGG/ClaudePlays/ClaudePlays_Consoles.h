/*  ClaudeGG Claude Plays: what differs from console to console
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The same tools play every console, but the consoles are not the same:
 *
 *  -   How long a press has to be, and how long to wait after it. A Switch
 *      reads the board directly; a retro console gets it through a
 *      Bluetooth adapter (BlueRetro), Remote Play through a stream over the
 *      network. Many games of the older consoles run at 20 to 30 frames a
 *      second and read the pad once a frame.
 *
 *  -   How late the picture comes. A capture card adds a frame or two; a
 *      Remote Play stream (and the OBS camera it goes through) or the
 *      Lightning HDMI adapter of an iPhone adds more. The program waits that
 *      long before it looks whether an action changed the picture.
 *
 *  -   What part of the capture is the game. A 4:3 game (every retro
 *      console, many games of the PlayStation 3 and the Xboxes) fills a
 *      16:9 capture with black bars at the sides; an iPhone held upright
 *      fills only a narrow strip in the middle. The program finds those
 *      bars (content_box()) and sends Claude only the game: the same tokens
 *      for more detail, and the parts of the screen ("left", "top-right")
 *      are the game's.
 *
 *  -   Which button is yes. On a PlayStation in Japan CIRCLE confirms and
 *      CROSS goes back, the other way round from elsewhere (the PlayStation
 *      5 made CROSS confirm in its own menus in every region in 2020; games
 *      can still choose). Claude is told when the user says the game's text
 *      is Japanese.
 *
 *  Only what is certain is here. Everything is data: a new console is a new
 *  entry in console_traits().
 *
 *  No Qt in this header.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_ClaudePlays_Consoles_H
#define PokemonAutomation_ClaudeGG_ClaudePlays_Consoles_H

#include <stddef.h>
#include <stdint.h>
#include <functional>
#include <string>
#include <vector>
#include "ClaudePlays_Games.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace ClaudePlays{


//  How Claude's presses are played on a console.
struct InputTiming{
    //  How long a button is held by "press", and a direction (shorter: in
    //  many games a longer press moves the cursor twice).
    int press_ms = 150;
    int direction_ms = 110;
    //  The wait after each press of "press".
    int gap_ms = 300;
    //  The wait after "hold" lets go (and, 50 ms more, after "mash").
    int settle_ms = 250;
    //  How much later than a capture card's the picture comes: waited before
    //  the program looks whether an action changed it.
    int video_delay_ms = 0;
};

struct ConsoleTraits{
    //  The code of the setup's console: "switch", "ps3", "retro", ...
    std::string code;
    InputTiming timing;
    //  The shapes (width / height) the game's picture can have inside the
    //  capture, besides filling it. Empty: it always fills it.
    std::vector<double> picture_aspects;
    //  Why the timing is what it is, for the log.
    std::string why;
};

//  The traits of a console by its code. An unknown code: those of the
//  Switch.
const ConsoleTraits& console_traits(const std::string& code);
//  All of them, the Switch first.
const std::vector<ConsoleTraits>& all_console_traits();

//  For Claude, which button is yes and which no when the game's text is
//  Japanese, for this pad. Empty: the same as anywhere (on Nintendo's and
//  Microsoft's consoles A is yes everywhere).
std::string japanese_yes_no(PadKind pad);


//  A part of the capture, 0 to 1 of its width and height.
struct PictureBox{
    double x = 0;
    double y = 0;
    double width = 1;
    double height = 1;

    bool whole() const{ return width >= 1.0 && height >= 1.0; }
    bool operator==(const PictureBox& other) const{
        return x == other.x && y == other.y && width == other.width && height == other.height;
    }
};

//  Where the game is in a capture of "width" by "height", by its pixels
//  (0xAARRGGBB): the box of one of the "aspects", centered, when all around
//  it is black and inside it is not. A picture that says nothing (all black:
//  a fade, a scene loading) keeps "current"; one with something outside the
//  box of "current" is the whole capture again.
PictureBox content_box(
    size_t width, size_t height, const std::function<uint32_t(size_t x, size_t y)>& pixel,
    const std::vector<double>& aspects, const PictureBox& current
);

//  The size of a picture that shows a part of "box_width" by "box_height"
//  pixels in about as many pixels as one of "width" by "height" (what it
//  costs in tokens), not larger than the part itself, and at least 16 each
//  way.
void fit_picture(
    double box_width, double box_height, int width, int height,
    int& out_width, int& out_height
);


//  The checks of this file, without a console: the number that failed, and
//  what failed in "report".
int console_traits_tests(std::string& report);



}
}
}
#endif
