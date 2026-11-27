/*  Claude GG Pokemon GO Brain (the looks at the map of the Pokémon GO bot)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port of the two ways in which gamebot.py's Brain looks at the map of the game (issue #31):
 *
 *  - map_objects(): the Pokémon, PokéStops and gyms on the screen.  The map detector looks at the whole screen (squeezed to 384 x 384
 *    pixels) and at an enlarged piece of the middle, where the small Pokémon of a far-away spot and the dark map of the night are
 *    often missed otherwise.  A Pokémon that only the enlarged look sees is added when it is sure enough.  The thorough scan (tiles)
 *    looks at twelve overlapping square parts as well: one part alone often sees a 'Pokémon' in a building or in rain, a real one is
 *    seen in more than one look, so one that only one look saw is not believed.  A second call for the same screenshot (the same
 *    picture) does not look again at the whole screen and the middle;
 *  - second_look(): a new screenshot of the place where a Pokémon was seen: is it still there (the pulse around the trainer and the
 *    weather are gone by then; a camera that was still turning has come to rest)?
 *
 *  The detector itself is a Detector: the network of Models (ModelsDetector, in the app) or the answers of a story (the check).  What
 *  Python does with a thread pool for speed is done one look after the other here, in the same order.  run_map_checks() (in
 *  ClaudeGG_PokemonGoMap.h) holds this to the stories of tests/fixtures/map_golden.json.qz.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoBrain_H
#define PokemonAutomation_ClaudeGG_PokemonGoBrain_H

#include <map>
#include <optional>
#include <utility>
#include <vector>
#include <opencv2/core.hpp>
#include "ClaudeGG_PokemonGoModels.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Brain{

using Models::Detection;


extern const double TH_POKEMON;         //  a Pokémon this sure is one
extern const double TH_WEAK;            //  an enlarged look keeps what is this sure ...
extern const double TH_TILE;            //  ... and the thorough scan believes it when this sure (and seen in two looks)
extern const int TILE;                  //  the sides of the parts of the thorough scan
extern const int TILE_X[4];
extern const int TILE_Y[3];
extern const int ZOOM_X0, ZOOM_Y0, ZOOM_X1, ZOOM_Y1;        //  the enlarged middle of the screen


class Detector{
public:
    virtual ~Detector() = default;
    //  Brain._ssd() with the map detector on the part `box` of the picture: the boxes it found (at most `top`, at least `threshold`
    //  sure), the best first, with their middles and sizes in pixels of that part.
    virtual std::vector<Detection> map(const cv::Mat& img, const cv::Rect& box, double threshold, int top) = 0;
};

//  Where a Pokémon is now, after the second look: how sure, the middle and the size.
struct Seen{
    double score = 0;
    int x = 0;
    int y = 0;
    int w = 0;
    int h = 0;
};


class Eyes{
public:
    explicit Eyes(Detector& detector) : m_detector(detector){}

    //  Everything the map shows, the surest first (a Pokémon of the enlarged look, or of the thorough scan, only when it was not seen
    //  in the whole screen).  tiles: the thorough scan as well.
    std::vector<Detection> map_objects(const cv::Mat& img, bool tiles = false);

    //  The Pokémon that was at (x, y) now, on a new screenshot; nothing when it is gone (second_best is then the best certainty seen
    //  near the place, 0 when nothing).
    std::optional<Seen> second_look(const cv::Mat& img, int x, int y);

    //  Something that could be a Pokémon (a weak hit in the whole screen or in the enlarged look) at the last map_objects().
    bool hint = false;
    double second_best = 0.0;

private:
    struct Box{
        int x0, y0, x1, y1;
        bool operator==(const Box& o) const{ return x0 == o.x0 && y0 == o.y0 && x1 == o.x1 && y1 == o.y1; }
    };
    struct Hit{
        Detection found;
        Box box;
    };
    std::vector<Hit> look(const cv::Mat& img, const Box& box);

    Detector& m_detector;
    std::map<std::pair<int, int>, Box> m_src;       //  (x, y) of a Pokémon -> the part of the screen it was seen in
    cv::Mat m_seen_img;                             //  the picture of the last quick look (kept, so that no other picture is at its place)
    std::vector<Detection> m_seen_whole;
    std::vector<Hit> m_seen_zoom;
};


}
}
}
}
#endif
