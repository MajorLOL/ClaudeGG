/*  Claude GG Pokemon GO Brain (the looks at the map of the Pokémon GO bot)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <algorithm>
#include <cstdlib>
#include <tuple>
#include "ClaudeGG_PokemonGoBrain.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Brain{


const double TH_POKEMON = 0.4;
const double TH_WEAK = 0.35;
const double TH_TILE = 0.5;
const int TILE = 650;
const int TILE_X[4] = {0, 325, 650, 975};
const int TILE_Y[3] = {700, 1025, 1250};
const int ZOOM_X0 = 200;
const int ZOOM_Y0 = 600;
const int ZOOM_X1 = 1400;
const int ZOOM_Y1 = 1700;


namespace{

//  Two boxes with their middles within 100 pixels: the same Pokémon.
bool near_to(const Detection& a, const Detection& b){
    return std::abs(a.cx - b.cx) < 100 && std::abs(a.cy - b.cy) < 100;
}

bool pokemon_near(const std::vector<Detection>& res, const Detection& o){
    for (const Detection& r : res){
        if (r.label == "pokemon" && near_to(r, o)){
            return true;
        }
    }
    return false;
}

}


std::vector<Eyes::Hit> Eyes::look(const cv::Mat& img, const Box& box){
    std::vector<Hit> hits;
    const cv::Rect part = cv::Rect(box.x0, box.y0, box.x1 - box.x0, box.y1 - box.y0) & cv::Rect(0, 0, img.cols, img.rows);
    for (const Detection& o : m_detector.map(img, part, 0.2, 10)){
        if (o.label == "pokemon" && o.score >= TH_WEAK){
            Detection moved = o;
            moved.cx += box.x0;
            moved.cy += box.y0;
            hits.push_back(Hit{moved, box});
        }
    }
    return hits;
}


std::vector<Detection> Eyes::map_objects(const cv::Mat& img, bool tiles){
    m_src.clear();

    std::vector<Detection> res;
    std::vector<Hit> zoom;
    if (!m_seen_img.empty() && m_seen_img.data == img.data && m_seen_img.rows == img.rows && m_seen_img.cols == img.cols){
        //  the same screenshot: the quick look is reused
        res = m_seen_whole;
        zoom = m_seen_zoom;
    }else{
        res = m_detector.map(img, cv::Rect(0, 0, img.cols, img.rows), 0.2, 10);
        zoom = look(img, Box{ZOOM_X0, ZOOM_Y0, ZOOM_X1, ZOOM_Y1});
        m_seen_img = img;
        m_seen_whole = res;
        m_seen_zoom = zoom;
    }

    //  something that could be a Pokémon (a weak hit in the whole screen or the enlarged look)?
    hint = !zoom.empty();
    for (const Detection& r : res){
        if (r.label == "pokemon" && r.score >= 0.2){
            hint = true;
            break;
        }
    }
    for (const Hit& h : zoom){
        if (h.found.score >= TH_POKEMON && !pokemon_near(res, h.found)){
            res.push_back(h.found);
            m_src[{h.found.cx, h.found.cy}] = h.box;
        }
    }

    if (tiles){
        //  the thorough (slower) scan in overlapping square tiles; a real Pokémon is seen in several looks
        std::vector<Hit> hits = zoom;
        for (int y0 : TILE_Y){
            for (int x0 : TILE_X){
                for (const Hit& h : look(img, Box{x0, y0, x0 + TILE, y0 + TILE})){
                    hits.push_back(h);
                }
            }
        }
        std::stable_sort(hits.begin(), hits.end(), [](const Hit& a, const Hit& b){ return a.found.score > b.found.score; });
        while (!hits.empty()){
            const Hit first = hits.front();
            size_t group = 0;
            std::vector<Hit> rest;
            for (const Hit& h : hits){
                if (near_to(h.found, first.found)){
                    group++;
                }else{
                    rest.push_back(h);
                }
            }
            hits.swap(rest);
            if (group >= 2 && first.found.score >= TH_TILE && !pokemon_near(res, first.found)){
                res.push_back(first.found);
                m_src[{first.found.cx, first.found.cy}] = first.box;
            }
        }
    }

    std::stable_sort(res.begin(), res.end(), [](const Detection& a, const Detection& b){ return a.score > b.score; });
    return res;
}


std::optional<Seen> Eyes::second_look(const cv::Mat& img, int x, int y){
    const Box full{0, 0, img.cols, img.rows};
    Box box = full;
    const auto at = m_src.find({x, y});
    if (at != m_src.end()){
        box = at->second;
    }
    second_best = 0.0;
    std::vector<std::pair<Box, double>> looks;
    looks.push_back({box, 0.35});
    if (!(box == full)){
        looks.push_back({full, 0.3});
    }
    for (const auto& one : looks){
        const Box& b = one.first;
        const double th = one.second;
        const cv::Rect part = cv::Rect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0) & cv::Rect(0, 0, img.cols, img.rows);
        std::vector<Seen> near;
        for (const Detection& o : m_detector.map(img, part, 0.15, 10)){
            if (o.label == "pokemon" && std::abs(o.cx + b.x0 - x) < 150 && std::abs(o.cy + b.y0 - y) < 150){
                near.push_back(Seen{o.score, o.cx + b.x0, o.cy + b.y0, o.w, o.h});
            }
        }
        //  (max() of tuples: the surest, then the one most to the right, the lowest, the widest, the highest)
        auto better = [](const Seen& a, const Seen& c){
            return std::tie(a.score, a.x, a.y, a.w, a.h) > std::tie(c.score, c.x, c.y, c.w, c.h);
        };
        if (!near.empty()){
            double best = near.front().score;
            for (const Seen& n : near){
                best = std::max(best, n.score);
            }
            second_best = std::max(second_best, best);
        }
        std::optional<Seen> good;
        for (const Seen& n : near){
            if (n.score >= th && (!good.has_value() || better(n, *good))){
                good = n;
            }
        }
        if (good.has_value()){
            return good;
        }
    }
    return std::nullopt;
}


}
}
}
}
