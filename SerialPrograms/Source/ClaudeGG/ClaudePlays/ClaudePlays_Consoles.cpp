/*  ClaudeGG Claude Plays: what differs from console to console
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <algorithm>
#include <cmath>
#include <set>
#include "ClaudePlays_Consoles.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace ClaudePlays{


namespace{

//  The shapes of a game's picture. 4:3: the retro consoles, and the games
//  of the PlayStation 3 and the Xboxes that were made for the televisions
//  of their day. An iPhone upright: 19.5:9 (the iPhone X and later) or 16:9
//  (the iPhone 8 and earlier, and the SE); lying down it fills the capture.
const double ASPECT_4_3 = 4.0 / 3.0;
const double IPHONE_UPRIGHT = 9.0 / 19.5;
const double IPHONE_UPRIGHT_OLD = 9.0 / 16.0;

std::vector<ConsoleTraits> make_traits(){
    std::vector<ConsoleTraits> traits;
    auto add = [&](const char* code, InputTiming timing, std::vector<double> aspects, const char* why){
        ConsoleTraits entry;
        entry.code = code;
        entry.timing = timing;
        entry.picture_aspects = std::move(aspects);
        entry.why = why;
        traits.push_back(std::move(entry));
    };
    //  The board is the console's own controller (or a plain USB pad of
    //  it): the timing the Switch programs were made with.
    const InputTiming direct;
    add("switch", direct, {}, "The board is the console's controller: the usual timing.");
    add("ps3", direct, {ASPECT_4_3}, "A USB pad of the console: the usual timing. Older games are 4:3.");
    //  Through a Pico with OGX-Mini: one more USB hop of a millisecond or
    //  two, well inside a frame.
    add("xbox", direct, {ASPECT_4_3}, "Through OGX-Mini, a millisecond more: the usual timing. Most games are 4:3.");
    add("xbox360", direct, {ASPECT_4_3}, "Through OGX-Mini, a millisecond more: the usual timing. Older games are 4:3.");
    add("psclassic", direct, {ASPECT_4_3}, "Through OGX-Mini, a millisecond more: the usual timing. Its games are 4:3.");
    {
        //  A Bluetooth link to BlueRetro, and games that read the pad once
        //  a frame at 20 to 30 frames a second: a press a little longer, so
        //  that no frame misses it, and a moment more after it.
        InputTiming timing;
        timing.press_ms = 170;
        timing.direction_ms = 130;
        timing.gap_ms = 350;
        timing.settle_ms = 300;
        add(
            "retro", timing, {ASPECT_4_3},
            "Bluetooth to BlueRetro, and games at 20 to 30 frames a second: longer presses. 4:3."
        );
    }
    {
        //  The press goes over the network to the console and the picture
        //  comes back as a stream through OBS: both are late, and a press
        //  that is too short can fall between two of the client's packets.
        InputTiming timing;
        timing.press_ms = 180;
        timing.direction_ms = 140;
        timing.gap_ms = 400;
        timing.settle_ms = 350;
        timing.video_delay_ms = 150;
        add(
            "psremote", timing, {},
            "Remote Play: the press goes over the network and the picture comes back as a stream, so both are late."
        );
        add(
            "xboxremote", timing, {},
            "Remote Play: the press goes over the network and the picture comes back as a stream, so both are late."
        );
    }
    {
        //  Keys, not buttons: a key held long repeats, so it is pressed
        //  short. The focus frame of Full Keyboard Access moves with an
        //  animation, and the Lightning HDMI adapter compresses the picture,
        //  which makes it late.
        InputTiming timing;
        timing.press_ms = 90;
        timing.direction_ms = 90;
        timing.gap_ms = 350;
        timing.settle_ms = 300;
        timing.video_delay_ms = 100;
        add(
            "iphone", timing, {IPHONE_UPRIGHT, IPHONE_UPRIGHT_OLD},
            "Keys are pressed short (a long one repeats); the HDMI adapter makes the picture late. Upright, the "
            "screen is a strip in the middle of the capture."
        );
    }
    return traits;
}

}   //  namespace


const std::vector<ConsoleTraits>& all_console_traits(){
    static const std::vector<ConsoleTraits> traits = make_traits();
    return traits;
}

const ConsoleTraits& console_traits(const std::string& code){
    const std::vector<ConsoleTraits>& traits = all_console_traits();
    for (const ConsoleTraits& entry : traits){
        if (entry.code == code){
            return entry;
        }
    }
    return traits[0];
}

std::string japanese_yes_no(PadKind pad){
    switch (pad){
    case PadKind::PS1_CONTROLLER:
    case PadKind::PS2_CONTROLLER:
    case PadKind::PSCLASSIC_CONTROLLER:
        return "The game is a Japanese one: in Japanese PlayStation games CIRCLE is usually yes and CROSS no "
            "or back, the other way round from elsewhere.";
    case PadKind::PS3_CONTROLLER:
        return "The game is a Japanese one: on a Japanese PlayStation 3, and in its Japanese games, CIRCLE is "
            "usually yes and CROSS no or back, the other way round from elsewhere.";
    case PadKind::PS4_CONTROLLER:
        return "The game is a Japanese one: on a Japanese PlayStation 4, and in many Japanese games, CIRCLE is "
            "yes and CROSS no or back. A PlayStation 5 has CROSS for yes in its own menus in every region, "
            "but a game can still use CIRCLE: go by what the screen shows, and check the first choice.";
    default:
        return std::string();
    }
}


namespace{

//  Darker than this in each of red, green and blue: black, with the noise
//  of a capture card.
const uint32_t BLACK_LEVEL = 28;

bool is_black(uint32_t pixel){
    return ((pixel >> 16) & 0xff) < BLACK_LEVEL &&
        ((pixel >> 8) & 0xff) < BLACK_LEVEL &&
        (pixel & 0xff) < BLACK_LEVEL;
}

//  Of a grid of samples over the capture: how many are not black inside a
//  box and around it. A margin along the box's edges is counted in neither
//  (the scaler of a capture card blurs the edge of the picture).
struct Samples{
    size_t inside = 0;
    size_t inside_lit = 0;
    size_t outside = 0;
    size_t outside_lit = 0;
    //  The strips just inside the box along its two long sides (left and
    //  right of a box narrower than the capture, top and bottom of one
    //  lower): the game fills its box, so both have something lit.
    size_t side_a = 0;
    size_t side_a_lit = 0;
    size_t side_b = 0;
    size_t side_b_lit = 0;
};

const int GRID_COLUMNS = 192;
const int GRID_ROWS = 108;
const double EDGE_MARGIN = 0.012;
const double SIDE_STRIP = 0.01;

Samples count_samples(
    size_t width, size_t height, const std::function<uint32_t(size_t, size_t)>& pixel, const PictureBox& box
){
    Samples samples;
    for (int row = 0; row < GRID_ROWS; row++){
        const double fy = (row + 0.5) / GRID_ROWS;
        const size_t y = std::min(height - 1, (size_t)(fy * (double)height));
        for (int column = 0; column < GRID_COLUMNS; column++){
            const double fx = (column + 0.5) / GRID_COLUMNS;
            const size_t x = std::min(width - 1, (size_t)(fx * (double)width));
            const bool in_x = fx >= box.x + EDGE_MARGIN && fx <= box.x + box.width - EDGE_MARGIN;
            const bool in_y = fy >= box.y + EDGE_MARGIN && fy <= box.y + box.height - EDGE_MARGIN;
            const bool out_x = fx < box.x - EDGE_MARGIN || fx > box.x + box.width + EDGE_MARGIN;
            const bool out_y = fy < box.y - EDGE_MARGIN || fy > box.y + box.height + EDGE_MARGIN;
            if (in_x && in_y){
                const bool lit = !is_black(pixel(x, y));
                samples.inside++;
                samples.inside_lit += lit ? 1 : 0;
                const bool narrow = box.width < 1.0;
                const double from = narrow ? fx - box.x : fy - box.y;
                const double to = narrow ? box.x + box.width - fx : box.y + box.height - fy;
                if (from < EDGE_MARGIN + SIDE_STRIP){
                    samples.side_a++;
                    samples.side_a_lit += lit ? 1 : 0;
                }
                if (to < EDGE_MARGIN + SIDE_STRIP){
                    samples.side_b++;
                    samples.side_b_lit += lit ? 1 : 0;
                }
            }else if (out_x || out_y){
                samples.outside++;
                samples.outside_lit += is_black(pixel(x, y)) ? 0 : 1;
            }
        }
    }
    return samples;
}

PictureBox box_of(double aspect, double capture_aspect){
    PictureBox box;
    if (aspect < capture_aspect){
        box.width = aspect / capture_aspect;
        box.x = (1.0 - box.width) / 2;
    }else{
        box.height = capture_aspect / aspect;
        box.y = (1.0 - box.height) / 2;
    }
    return box;
}

}   //  namespace


PictureBox content_box(
    size_t width, size_t height, const std::function<uint32_t(size_t x, size_t y)>& pixel,
    const std::vector<double>& aspects, const PictureBox& current
){
    if (width < (size_t)GRID_COLUMNS || height < (size_t)GRID_ROWS){
        return PictureBox();
    }
    const double capture_aspect = (double)width / (double)height;

    //  The candidates, the largest first: a 4:3 game before an iPhone.
    std::vector<PictureBox> boxes;
    for (double aspect : aspects){
        if (aspect <= 0 || std::fabs(aspect / capture_aspect - 1.0) < 0.05){
            continue;
        }
        boxes.push_back(box_of(aspect, capture_aspect));
    }
    std::sort(boxes.begin(), boxes.end(), [](const PictureBox& a, const PictureBox& b){
        return a.width * a.height > b.width * b.height;
    });

    const Samples whole = count_samples(width, height, pixel, PictureBox());
    //  (Almost) all black: it says nothing about where the game is.
    if (whole.inside_lit * 200 < whole.inside){
        return current;
    }
    for (const PictureBox& box : boxes){
        const Samples samples = count_samples(width, height, pixel, box);
        //  Black around it (a dot of noise or two aside), and the game in it
        //  up to its sides.
        if (samples.outside > 0 && samples.outside_lit * 500 <= samples.outside &&
            samples.inside_lit * 50 >= samples.inside &&
            samples.side_a_lit * 10 >= samples.side_a && samples.side_a > 0 &&
            samples.side_b_lit * 10 >= samples.side_b && samples.side_b > 0
        ){
            return box;
        }
    }
    if (current.whole()){
        return current;
    }
    //  Not one of the shapes: still the box of before if all around it is
    //  black (a dark scene inside it), the whole capture if not.
    const Samples samples = count_samples(width, height, pixel, current);
    return samples.outside_lit * 500 <= samples.outside ? current : PictureBox();
}

void fit_picture(
    double box_width, double box_height, int width, int height,
    int& out_width, int& out_height
){
    box_width = std::max(box_width, 1.0);
    box_height = std::max(box_height, 1.0);
    const double aspect = box_width / box_height;
    const double area = (double)width * (double)height;
    double w = std::sqrt(area * aspect);
    double h = w / aspect;
    //  Never larger than the part of the video itself.
    if (w > box_width){
        h *= box_width / w;
        w = box_width;
    }
    if (h > box_height){
        w *= box_height / h;
        h = box_height;
    }
    out_width = std::max(16, (int)(w + 0.5));
    out_height = std::max(16, (int)(h + 0.5));
}


int console_traits_tests(std::string& report){
    int wrong = 0;
    auto fail = [&](const std::string& what){
        wrong++;
        report += (report.empty() ? "" : "\n") + what;
    };

    //  Every console of a game has traits of its own, and they make sense.
    std::set<std::string> codes;
    for (const ConsoleTraits& entry : all_console_traits()){
        if (!codes.insert(entry.code).second){
            fail("two entries for the console " + entry.code);
        }
        const InputTiming& t = entry.timing;
        if (t.press_ms < 60 || t.press_ms > 500 || t.direction_ms < 60 || t.direction_ms > t.press_ms ||
            t.gap_ms < 100 || t.settle_ms < 100 || t.video_delay_ms < 0 || t.video_delay_ms > 1000 ||
            entry.why.empty()
        ){
            fail("the timing of the console " + entry.code);
        }
    }
    if (all_console_traits()[0].code != "switch" || console_traits("no such console").code != "switch"){
        fail("the Switch is not the first console and the fallback");
    }
    for (GameId id : all_games()){
        const GameProfile& profile = game_profile(id);
        if (console_traits(profile.console).code != profile.console){
            fail("no traits for the console " + profile.console + " of " + profile.identifier);
        }
        const bool playstation =
            profile.pad == PadKind::PS1_CONTROLLER || profile.pad == PadKind::PS2_CONTROLLER ||
            profile.pad == PadKind::PS3_CONTROLLER || profile.pad == PadKind::PS4_CONTROLLER ||
            profile.pad == PadKind::PSCLASSIC_CONTROLLER;
        const std::string japanese = japanese_yes_no(profile.pad);
        if (japanese.empty() == playstation || (playstation && japanese.find("CIRCLE") == std::string::npos)){
            fail("which button is yes in Japan for " + profile.identifier);
        }
    }
    //  The Switch: always the whole capture.
    if (!console_traits("switch").picture_aspects.empty() || console_traits("retro").picture_aspects.empty()){
        fail("the shapes of the pictures of the Switch and the retro consoles");
    }

    //  A made-up capture of 1920 by 1080: lit inside "lit", black around it,
    //  and lit at one more place ("spot") when given.
    struct Frame{
        PictureBox lit;
        bool spot = false;
        uint32_t operator()(size_t x, size_t y) const{
            const double fx = (double)x / 1920.0;
            const double fy = (double)y / 1080.0;
            if (spot && fx < 0.05 && fy < 0.05){
                return 0xffc0c0c0;
            }
            const bool inside = fx >= lit.x && fx < lit.x + lit.width && fy >= lit.y && fy < lit.y + lit.height;
            //  The game's picture: a pattern of colors, with dark parts.
            return inside ? ((x / 40 + y / 40) % 3 == 0 ? 0xff101010 : 0xff3080d0) : 0xff060606;
        }
    };
    auto near = [](const PictureBox& a, const PictureBox& b){
        return std::fabs(a.x - b.x) < 0.01 && std::fabs(a.y - b.y) < 0.01 &&
            std::fabs(a.width - b.width) < 0.01 && std::fabs(a.height - b.height) < 0.01;
    };
    const std::vector<double> retro = console_traits("retro").picture_aspects;
    const std::vector<double> iphone = console_traits("iphone").picture_aspects;
    const PictureBox four_three{0.125, 0, 0.75, 1};

    Frame frame;
    frame.lit = four_three;
    const PictureBox found = content_box(1920, 1080, std::cref(frame), retro, PictureBox());
    if (!near(found, four_three)){
        fail("a 4:3 game in a 16:9 capture is not found");
    }
    //  A 16:9 game: the whole capture.
    frame.lit = PictureBox();
    if (!content_box(1920, 1080, std::cref(frame), retro, PictureBox()).whole()){
        fail("a game that fills the capture is cut");
    }
    //  The Switch has no other shapes: never cut.
    frame.lit = four_three;
    if (!content_box(1920, 1080, std::cref(frame), {}, PictureBox()).whole()){
        fail("the Switch's picture is cut");
    }
    //  A black screen keeps the box it had.
    frame.lit = PictureBox{0, 0, 0, 0};
    if (!near(content_box(1920, 1080, std::cref(frame), retro, four_three), four_three) ||
        !content_box(1920, 1080, std::cref(frame), retro, PictureBox()).whole()
    ){
        fail("a black screen changes the box");
    }
    //  Something outside the box: the whole capture again.
    frame.lit = four_three;
    frame.spot = true;
    if (!content_box(1920, 1080, std::cref(frame), retro, four_three).whole()){
        fail("a picture with something beside the box is still cut");
    }
    frame.spot = false;
    //  A dark scene in the box (only its middle lit): still the box. In a
    //  capture that was whole, it does not make one.
    frame.lit = PictureBox{0.4, 0.4, 0.2, 0.2};
    if (!near(content_box(1920, 1080, std::cref(frame), retro, four_three), four_three) ||
        !content_box(1920, 1080, std::cref(frame), retro, PictureBox()).whole()
    ){
        fail("a dark scene changes the box");
    }
    //  An iPhone upright: the strip in the middle, of either shape.
    for (double aspect : iphone){
        const double w = aspect / (16.0 / 9.0);
        frame.lit = PictureBox{(1 - w) / 2, 0, w, 1};
        if (!near(content_box(1920, 1080, std::cref(frame), iphone, PictureBox()), frame.lit)){
            fail("an upright iPhone is not found");
        }
    }

    //  The size of a picture: as many pixels as 640 by 360, no more than
    //  the video has.
    int w = 0;
    int h = 0;
    fit_picture(1920, 1080, 640, 360, w, h);
    if (w != 640 || h != 360){
        fail("the whole capture is not sent at the size asked for");
    }
    fit_picture(1440, 1080, 640, 360, w, h);
    if (std::abs(w * h - 640 * 360) > 2000 || std::abs(w * 3 - h * 4) > 4){
        fail("a 4:3 part is not sent at 4:3 for as many pixels");
    }
    fit_picture(300, 200, 640, 360, w, h);
    if (w != 300 || h != 200){
        fail("a small part is sent larger than it is");
    }
    return wrong;
}



}
}
}
