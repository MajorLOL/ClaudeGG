/*  Pokemon FRLG Autostory Readers Tests
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  What the pictures show was looked at by eye, and the tests say only what
 *  is true of them:
 *    - the foe's HP bar is full on every encounter picture,
 *    - the caught mark is in the foe's box of the encounters of a species that
 *      was caught (CHANSEY, DRAGONAIR, KAKUNA, PIKACHU, most UNOWN) and not in
 *      the others, and on the four move menu pictures,
 *    - the player's bar reads full on the move menu pictures; on the first
 *      frame of an encounter there is no player's box yet, and on the level-up
 *      pictures the window covers it: "no bar" (-1) both times,
 *    - pictures with something painted over them (the test repository has no
 *      picture of a bar that is half empty, or covered): a bar that is half
 *      full reads 0.5, a bar covered in part or "filled" after an empty part
 *      reads -1, a mark that is not clear reads -1. The paint is in the
 *      colors the readers say they look for, so this tests the counting and
 *      the thresholds, not the real colors: real captures of low HP bars
 *      would be better (see ROADMAP.md).
 *    - the readers do not read something else when the capture comes out
 *      lighter, darker or tinted (capture cards differ): they read the same
 *      or -1 ("not sure"), never a wrong value. That is what the battle
 *      loop can live with: it keeps a bar only when it was read (>= 0), and a
 *      mark that was not read stays "unknown" (the log says so), while a wrong
 *      value would be believed.
 *
 *  Not pinned, as the readers do not do it (known weaknesses, see
 *  ROADMAP.md): read_player_hp() reads 1.0 on the first frame of an
 *  encounter in front of a sand colored backdrop (ARTICUNO, MACHOP, HO-OH),
 *  where there is no player's box at all, and under a green or warm tint it
 *  does so on some other first frames too. The readers are only asked about
 *  a bar in screens where the box is on screen (the move menu, the battle
 *  menu).
 *
 */

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <string>
#include <vector>
#include "Common/Cpp/CancellableScope.h"
#include "Common/Cpp/TestRunners/UnitTestDatabase.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/ImageTypes/ImageRGB32.h"
#include "Tests/ImageUnitTest.h"
#include "VideoGames/PokemonFRLG/PokemonFRLG_Settings.h"
#include "PokemonFRLG_AutoStoryBattle.h"
#include "PokemonFRLG_AutoStoryReaders_Tests.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonFRLG{

namespace{


//  Pictures of the first frame of a wild encounter: the foe's box, no player's
//  box. "mark": the ball mark is in the foe's box.
struct Picture{
    const char* path;
    int mark;
};
const Picture ENCOUNTERS[] = {
    {"PokemonFRLG/WildEncounterReader/eng_articuno.jpg",        0},
    {"PokemonFRLG/WildEncounterReader/eng_chansey.jpg",         1},
    {"PokemonFRLG/WildEncounterReader/eng_chansey_dark.png",    0},
    {"PokemonFRLG/WildEncounterReader/eng_dragonair.jpg",       1},
    {"PokemonFRLG/WildEncounterReader/eng_heracross.jpg",       0},
    {"PokemonFRLG/WildEncounterReader/eng_ho-oh.jpg",           0},
    {"PokemonFRLG/WildEncounterReader/eng_kakuna.jpg",          1},
    {"PokemonFRLG/WildEncounterReader/eng_machop.jpg",          0},
    {"PokemonFRLG/WildEncounterReader/eng_pikachu.jpg",         1},
    {"PokemonFRLG/WildEncounterReader/eng_unown_c.png",         1},
    {"PokemonFRLG/WildEncounterReader/eng_unown_ex.jpg",        1},
    {"PokemonFRLG/WildEncounterReader/eng_unown_h.png",         1},
    {"PokemonFRLG/WildEncounterReader/eng_unown_j.png",         1},
    {"PokemonFRLG/WildEncounterReader/eng_unown_n.png",         1},
    {"PokemonFRLG/WildEncounterReader/eng_unown_p.png",         1},
    {"PokemonFRLG/WildEncounterReader/eng_unown_qu.jpg",        0},
    {"PokemonFRLG/WildEncounterReader/eng_unown_s.png",         1},
    {"PokemonFRLG/WildEncounterReader/fra_snorlax.jpg",         0},
};
//  Of the encounters, the ones where read_player_hp() is right: no player's
//  box, so -1. (The sand colored ones read 1.0: see the top of this file.)
const char* const ENCOUNTERS_WITHOUT_PLAYER_BOX[] = {
    "PokemonFRLG/WildEncounterReader/eng_chansey.jpg",
    "PokemonFRLG/WildEncounterReader/eng_chansey_dark.png",
    "PokemonFRLG/WildEncounterReader/eng_dragonair.jpg",
    "PokemonFRLG/WildEncounterReader/eng_heracross.jpg",
    "PokemonFRLG/WildEncounterReader/eng_kakuna.jpg",
    "PokemonFRLG/WildEncounterReader/eng_pikachu.jpg",
    "PokemonFRLG/WildEncounterReader/eng_unown_c.png",
    "PokemonFRLG/WildEncounterReader/eng_unown_ex.jpg",
    "PokemonFRLG/WildEncounterReader/eng_unown_h.png",
    "PokemonFRLG/WildEncounterReader/eng_unown_j.png",
    "PokemonFRLG/WildEncounterReader/eng_unown_n.png",
    "PokemonFRLG/WildEncounterReader/eng_unown_p.png",
    "PokemonFRLG/WildEncounterReader/eng_unown_qu.jpg",
    "PokemonFRLG/WildEncounterReader/eng_unown_s.png",
    "PokemonFRLG/WildEncounterReader/fra_snorlax.jpg",
};

//  The move menu of a battle (the foe's box with the mark, the player's box
//  at full HP).
const char* const MOVE_MENUS[] = {
    "PokemonFRLG/BattleMoveSelectionArrow/MoveArrow-BottomLeft.png",
    "PokemonFRLG/BattleMoveSelectionArrow/MoveArrow-BottomRight.png",
    "PokemonFRLG/BattleMoveSelectionArrow/MoveArrow-TopLeft.png",
    "PokemonFRLG/BattleMoveSelectionArrow/MoveArrow-TopRight.png",
};

//  The level-up window covers the player's box and the foe's mark.
const char* const LEVEL_UPS[] = {
    "PokemonFRLG/BattleLevelUpReader/charizard_1.png",
    "PokemonFRLG/BattleLevelUpReader/deoxys_1_jpn.jpg",
    "PokemonFRLG/BattleLevelUpReader/horsea_1.png",
    "PokemonFRLG/BattleLevelUpReader/horsea_2.png",
    "PokemonFRLG/BattleLevelUpReader/horsea_3.png",
};


bool same(double a, double b){
    return std::abs(a - b) < 1e-6;
}


class Test_CaughtMark : public ImageUnitTest{
public:
    Test_CaughtMark(const std::string& image, int expected)
        : ImageUnitTest("PokemonFRLG::AutoStoryCaughtMark - " + image, {image})
        , m_expected(expected)
    {}
private:
    UnitTestResult run_on_images(
        Logger&, CancellableScope&,
        const std::vector<ImageRGB32>& images
    ) const override{
        const int mark = read_caught_mark(images[0]);
        if (mark == m_expected){
            return true;
        }
        return "Expected: " + std::to_string(m_expected) + ", received: " + std::to_string(mark);
    }
    int m_expected;
};

class Test_FoeHp : public ImageUnitTest{
public:
    Test_FoeHp(const std::string& image)
        : ImageUnitTest("PokemonFRLG::AutoStoryFoeHp - " + image, {image})
    {}
private:
    UnitTestResult run_on_images(
        Logger&, CancellableScope&,
        const std::vector<ImageRGB32>& images
    ) const override{
        const double hp = read_foe_hp(images[0]);
        if (same(hp, 1.0)){
            return true;
        }
        return "Expected a full bar, received: " + std::to_string(hp);
    }
};

class Test_PlayerHp : public ImageUnitTest{
public:
    Test_PlayerHp(const std::string& image, double expected)
        : ImageUnitTest("PokemonFRLG::AutoStoryPlayerHp - " + image, {image})
        , m_expected(expected)
    {}
private:
    UnitTestResult run_on_images(
        Logger&, CancellableScope&,
        const std::vector<ImageRGB32>& images
    ) const override{
        const double hp = read_player_hp(images[0]);
        if (same(hp, m_expected)){
            return true;
        }
        return "Expected: " + std::to_string(m_expected) + ", received: " + std::to_string(hp);
    }
    double m_expected;
};



//  Paint a rectangle of the game screen in a frame. The rectangle is in game
//  pixels (the screen of the GBA is 240 x 160), from "x0", "y0" up to "x1", "y1".
void paint(ImageRGB32& frame, double x0, double y0, double x1, double y1, uint32_t color){
    const ImageFloatBox game = GameSettings::instance().GAME_BOX;
    const size_t left = (size_t)((double)frame.width() * game.x + 0.5);
    const size_t top = (size_t)((double)frame.height() * game.y + 0.5);
    const double sx = (double)(size_t)((double)frame.width() * game.width + 0.5) / 240.0;
    const double sy = (double)(size_t)((double)frame.height() * game.height + 0.5) / 160.0;
    const size_t px0 = left + (size_t)(x0 * sx);
    const size_t px1 = std::min(frame.width(), left + (size_t)std::ceil(x1 * sx));
    const size_t py0 = top + (size_t)(y0 * sy);
    const size_t py1 = std::min(frame.height(), top + (size_t)std::ceil(y1 * sy));
    for (size_t y = py0; y < py1; y++){
        for (size_t x = px0; x < px1; x++){
            frame.pixel(x, y) = color;
        }
    }
}

//  Colors in the ranges the readers look for.
constexpr uint32_t EMPTY_BAR = 0xff506058;      //  dark grey-green: the empty part of an HP bar
constexpr uint32_t WHITE = 0xffffffff;          //  neither filled nor empty
constexpr uint32_t CREAM = 0xfff8f0d0;          //  the HP box
constexpr uint32_t DARK = 0xff303030;           //  not the HP box
constexpr uint32_t DARK_RED = 0xff643c3c;       //  neither filled nor empty
constexpr uint32_t GREY = 0xff9696a0;           //  not cream (all three channels far below)


//  An HP bar with columns painted over: the bar of the player's Pokemon or
//  the foe's, from column "from" up to "to" (0 to 48), all rows of the bar.
class Test_PaintedBar : public ImageUnitTest{
public:
    Test_PaintedBar(
        const std::string& what, const std::string& image,
        bool player, int from, int to, uint32_t color, double expected
    )
        : ImageUnitTest("PokemonFRLG::AutoStoryPaintedBar - " + image + " " + what, {image})
        , m_player(player)
        , m_from(from)
        , m_to(to)
        , m_color(color)
        , m_expected(expected)
    {
        m_memory += MAX_TEST_IMAGE_RGB32_BYTES;     //  the copy
    }
private:
    UnitTestResult run_on_images(
        Logger&, CancellableScope&,
        const std::vector<ImageRGB32>& images
    ) const override{
        ImageRGB32 frame = images[0].copy();
        //  The player's bar: x = 174, rows 91 to 93. The foe's: x = 52, rows 34 to 36.
        const double left = m_player ? 174 : 52;
        const double top = m_player ? 90 : 33;
        paint(frame, left + m_from, top, left + m_to, top + 5, m_color);
        const double hp = m_player ? read_player_hp(frame) : read_foe_hp(frame);
        if (same(hp, m_expected)){
            return true;
        }
        return "Expected: " + std::to_string(m_expected) + ", received: " + std::to_string(hp);
    }
    bool m_player;
    int m_from;
    int m_to;
    uint32_t m_color;
    double m_expected;
};

//  The foe's box with a rectangle painted in it (game pixels). The mark area
//  is x = 20 to 26, rows 31 to 37; the box around it is cream.
class Test_PaintedMark : public ImageUnitTest{
public:
    Test_PaintedMark(
        const std::string& what, const std::string& image,
        int x, int y, int w, int h, uint32_t color, int expected
    )
        : ImageUnitTest("PokemonFRLG::AutoStoryPaintedMark - " + image + " " + what, {image})
        , m_x(x)
        , m_y(y)
        , m_w(w)
        , m_h(h)
        , m_color(color)
        , m_expected(expected)
    {
        m_memory += MAX_TEST_IMAGE_RGB32_BYTES;     //  the copy
    }
private:
    UnitTestResult run_on_images(
        Logger&, CancellableScope&,
        const std::vector<ImageRGB32>& images
    ) const override{
        ImageRGB32 frame = images[0].copy();
        paint(frame, m_x, m_y, m_x + m_w, m_y + m_h, m_color);
        const int mark = read_caught_mark(frame);
        if (mark == m_expected){
            return true;
        }
        return "Expected: " + std::to_string(m_expected) + ", received: " + std::to_string(mark);
    }
    int m_x;
    int m_y;
    int m_w;
    int m_h;
    uint32_t m_color;
    int m_expected;
};


//  A capture that comes out other than the game draws it: every color
//  channel c becomes  255 * (clamp(c * gain + offset) / 255) ^ gamma.
struct Distortion{
    const char* name;
    double gain[3];
    double offset[3];
    double gamma;
};
const Distortion DISTORTIONS[] = {
    {"limited range",   {219 / 255.0, 219 / 255.0, 219 / 255.0}, {16, 16, 16}, 1.0},
    {"expanded range",  {255 / 219.0, 255 / 219.0, 255 / 219.0}, {-16 * 255 / 219.0, -16 * 255 / 219.0, -16 * 255 / 219.0}, 1.0},
    {"15% darker",      {0.85, 0.85, 0.85}, {0, 0, 0}, 1.0},
    {"30% darker",      {0.70, 0.70, 0.70}, {0, 0, 0}, 1.0},
    {"10% brighter",    {1.10, 1.10, 1.10}, {0, 0, 0}, 1.0},
    {"gamma 0.8",       {1, 1, 1}, {0, 0, 0}, 0.8},
    {"gamma 1.25",      {1, 1, 1}, {0, 0, 0}, 1.25},
    {"warm",            {1.06, 1.00, 0.92}, {0, 0, 0}, 1.0},
    {"cool",            {0.92, 1.00, 1.06}, {0, 0, 0}, 1.0},
    {"green tint",      {0.92, 1.06, 0.92}, {0, 0, 0}, 1.0},
};

ImageRGB32 distort(const ImageViewRGB32& image, const Distortion& distortion){
    //  One table per channel: the same input gives the same output.
    uint32_t table[3][256];
    for (int k = 0; k < 3; k++){
        for (int c = 0; c < 256; c++){
            double t = (double)c * distortion.gain[k] + distortion.offset[k];
            t = std::min(255.0, std::max(0.0, t));
            t = 255.0 * std::pow(t / 255.0, distortion.gamma);
            table[k][c] = (uint32_t)std::min(255.0, std::max(0.0, t + 0.5));
        }
    }
    ImageRGB32 out(image.width(), image.height());
    for (size_t y = 0; y < image.height(); y++){
        for (size_t x = 0; x < image.width(); x++){
            const uint32_t p = image.pixel(x, y);
            out.pixel(x, y) = 0xff000000u
                | (table[0][(p >> 16) & 0xff] << 16)
                | (table[1][(p >> 8) & 0xff] << 8)
                | table[2][p & 0xff];
        }
    }
    return out;
}

//  The readers on a picture re-colored in every way of DISTORTIONS: each
//  answer is the right one or -1, nothing else. A negative expected value
//  is not asked about ("player": the bar is read only where it is on screen).
class Test_Distorted : public ImageUnitTest{
public:
    //  "mark": the right answer of read_caught_mark(), "foe" and "player" those of
    //  the HP readers; a reader with "expected" -2 is left out.
    Test_Distorted(const std::string& image, int mark, double foe, double player)
        : ImageUnitTest("PokemonFRLG::AutoStoryReadersDistorted - " + image, {image})
        , m_mark(mark)
        , m_foe(foe)
        , m_player(player)
    {
        m_memory += MAX_TEST_IMAGE_RGB32_BYTES;     //  the re-colored copy
    }
private:
    static bool ok(double read, double expected){
        return same(read, -1.0) || same(read, expected);
    }
    UnitTestResult run_on_images(
        Logger&, CancellableScope& scope,
        const std::vector<ImageRGB32>& images
    ) const override{
        std::string failures;
        for (const Distortion& distortion : DISTORTIONS){
            scope.throw_if_cancelled();
            const ImageRGB32 image = distort(images[0], distortion);
            const int mark = read_caught_mark(image);
            const double foe = read_foe_hp(image);
            const double player = read_player_hp(image);
            std::string line;
            if (m_mark > -2 && !ok(mark, m_mark)){
                line += " mark " + std::to_string(mark) + " (expected " + std::to_string(m_mark) + " or -1);";
            }
            if (m_foe > -2 && !ok(foe, m_foe)){
                line += " foe HP " + std::to_string(foe) + " (expected " + std::to_string(m_foe) + " or -1);";
            }
            if (m_player > -2 && !ok(player, m_player)){
                line += " player HP " + std::to_string(player) + " (expected " + std::to_string(m_player) + " or -1);";
            }
            if (!line.empty()){
                failures += std::string("[") + distortion.name + "]" + line + " ";
            }
        }
        if (failures.empty()){
            return true;
        }
        return failures;
    }
    int m_mark;
    double m_foe;
    double m_player;
};


}


void add_tests_AutoStoryReaders(UnitTestDatabase& database){
    for (const Picture& picture : ENCOUNTERS){
        database.add<Test_CaughtMark>(picture.path, picture.mark);
        database.add<Test_FoeHp>(picture.path);
        //  The player's bar is not asked about on the first frame (see above).
        database.add<Test_Distorted>(picture.path, picture.mark, 1.0, -2.0);
    }
    for (const char* path : ENCOUNTERS_WITHOUT_PLAYER_BOX){
        database.add<Test_PlayerHp>(path, -1.0);
    }
    for (const char* path : MOVE_MENUS){
        database.add<Test_CaughtMark>(path, 1);
        database.add<Test_FoeHp>(path);
        database.add<Test_PlayerHp>(path, 1.0);
        database.add<Test_Distorted>(path, 1, 1.0, 1.0);
    }
    //  Bars of a Pokemon that took damage, on the full ones of the move menu:
    //  the filled part is "columns filled / 48".
    const std::string menu = MOVE_MENUS[2];
    for (int filled : {0, 12, 24, 36, 47}){
        const std::string what = std::to_string(filled) + " of 48 filled";
        database.add<Test_PaintedBar>(what, menu, true, filled, 48, EMPTY_BAR, filled / 48.0);
        database.add<Test_PaintedBar>(what, menu, false, filled, 48, EMPTY_BAR, filled / 48.0);
    }
    //  Not a bar: a part covered, or filled columns after empty ones.
    database.add<Test_PaintedBar>("10 columns covered", menu, true, 20, 30, WHITE, -1.0);
    database.add<Test_PaintedBar>("10 columns covered", menu, false, 20, 30, WHITE, -1.0);
    database.add<Test_PaintedBar>("10 columns dark red", menu, true, 38, 48, DARK_RED, -1.0);
    database.add<Test_PaintedBar>("10 columns dark red", menu, false, 38, 48, DARK_RED, -1.0);
    database.add<Test_PaintedBar>("empty before filled", menu, true, 0, 24, EMPTY_BAR, -1.0);
    database.add<Test_PaintedBar>("empty before filled", menu, false, 0, 24, EMPTY_BAR, -1.0);
    //  The mark: a speck is not a mark, something between is not clear, a
    //  ball sized spot is the mark; and the mark painted over is no mark.
    const std::string no_mark = ENCOUNTERS[0].path;     //  ARTICUNO
    const std::string mark = ENCOUNTERS[1].path;        //  CHANSEY
    database.add<Test_PaintedMark>("one speck", no_mark, 20, 31, 1, 1, DARK, 0);
    database.add<Test_PaintedMark>("2 x 4 spot", no_mark, 20, 31, 2, 4, DARK, -1);
    database.add<Test_PaintedMark>("4 x 5 spot", no_mark, 20, 31, 4, 5, DARK, 1);
    database.add<Test_PaintedMark>("mark painted over", mark, 20, 30, 8, 8, CREAM, 0);
    //  No box: the area is not cream (the rectangle is bigger than the mark,
    //  the box around it is painted too).
    database.add<Test_PaintedMark>("box not cream", no_mark, 14, 30, 22, 8, GREY, -1);
    for (const char* path : LEVEL_UPS){
        database.add<Test_CaughtMark>(path, -1);
        database.add<Test_PlayerHp>(path, -1.0);
        //  The foe's bar: not asked about (the window is not what it reads).
        database.add<Test_Distorted>(path, -1, -2.0, -1.0);
    }
}


}
}
}
