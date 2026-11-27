/*  Claude GG Pokemon GO Minigame (the little game of a charged attack)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port of Mobile/battle_minigame.py: the same steps in the same order, so
 *  that the answers are the same (see the header).
 *
 */

#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdlib>
#include <map>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <QByteArray>
#include <QFile>
#include <QHash>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include "ClaudeGG_PokemonGoMinigame.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Minigame{


namespace{


//  ---- the way Python and NumPy count -----------------------------------------------------------------

//  round(x, n): the decimal that is nearest to the real value of the double, a tie to the even one.
double py_round(double x, int digits){
    char buf[64];
    const std::to_chars_result done = std::to_chars(buf, buf + sizeof(buf) - 1, x, std::chars_format::fixed, digits);
    *done.ptr = 0;
    return std::strtod(buf, nullptr);
}

//  round(x) of a float: the nearest integer, a tie to the even one.
int py_round_int(double x){
    return static_cast<int>(std::nearbyint(x));
}

double dmin(double a, double b){
    return b < a ? b : a;
}
double dmax(double a, double b){
    return b > a ? b : a;
}


//  ---- the colours of the types (R, G, B) -------------------------------------------------------------

struct TypeColour{
    const char* name;
    int r;
    int g;
    int b;
};
const TypeColour TYPE_RGB[] = {
    {"normal", 0xA0, 0xA2, 0x9F}, {"fire", 0xFB, 0xA5, 0x4C}, {"water", 0x53, 0x9D, 0xDF},
    {"electric", 0xF2, 0xD9, 0x4E}, {"grass", 0x5F, 0xBD, 0x58}, {"ice", 0x75, 0xD0, 0xC1},
    {"fighting", 0xD3, 0x42, 0x5F}, {"poison", 0xB7, 0x63, 0xCF}, {"ground", 0xDA, 0x7C, 0x4D},
    {"flying", 0xA1, 0xBB, 0xEC}, {"psychic", 0xFA, 0x85, 0x81}, {"bug", 0x92, 0xBC, 0x2C},
    {"rock", 0xC9, 0xBB, 0x8A}, {"ghost", 0x5F, 0x6D, 0xBC}, {"dragon", 0x0C, 0x69, 0xC8},
    {"dark", 0x59, 0x57, 0x61}, {"steel", 0x56, 0x95, 0xA3}, {"fairy", 0xEE, 0x90, 0xE6},
};


//  ---- where the icons of a type come by, from recordings of real fights --------------------------------

struct KnownLines{
    std::vector<Line> gates;
    std::vector<Line> rows;
};
const KnownLines* builtin_lines(const QString& kind){
    static const std::map<QString, KnownLines> KNOWN = {
        {"water", {{{0.68, 0.39, 0.68, 0.78}}, {}}},
        {"flying", {{{0.62, 0.42, 0.62, 0.87}}, {}}},
        {"electric", {{{0.26, 0.70, 0.76, 0.70}}, {}}},
        {"ghost", {{}, {{0.42, 0.56, 0.62, 0.56}, {0.29, 0.79, 0.50, 0.79}, {0.55, 0.79, 0.75, 0.79}}}},
    };
    const auto it = KNOWN.find(kind);
    return it == KNOWN.end() ? nullptr : &it->second;
}
//  The types that are not known yet get these lines until their icons are seen: a cross and two lines through
//  the middle of the screen.
const Line STAR[] = {
    {0.18, 0.36, 0.82, 0.86}, {0.82, 0.36, 0.18, 0.86}, {0.12, 0.60, 0.88, 0.60}, {0.50, 0.32, 0.50, 0.90},
};


//  ---- the masks of an icon, as averaging filters for a picture "gw" wide ---------------------------------

struct Masks{
    cv::Mat ring;
    cv::Mat outer;
    cv::Mat inner;
    int win = 0;
};

const Masks& masks_for(int gw){
    static std::map<int, Masks> cache;
    auto it = cache.find(gw);
    if (it != cache.end()){
        return it->second;
    }
    Masks masks;
    const double r = ICON_R * gw;
    const int n = static_cast<int>(std::ceil(1.6 * r));
    const int size = 2 * n + 1;
    masks.ring = cv::Mat(size, size, CV_32F, cv::Scalar(0));
    masks.outer = cv::Mat(size, size, CV_32F, cv::Scalar(0));
    masks.inner = cv::Mat(size, size, CV_32F, cv::Scalar(0));
    float ring_count = 0;
    float outer_count = 0;
    float inner_count = 0;
    for (int y = -n; y <= n; y++){
        for (int x = -n; x <= n; x++){
            const double d = std::hypot(static_cast<double>(x), static_cast<double>(y));
            if (d >= 0.60 * r && d <= 0.95 * r){
                masks.ring.at<float>(y + n, x + n) = 1.0f;
                ring_count += 1.0f;
            }
            if (d >= 1.20 * r && d <= 1.55 * r){
                masks.outer.at<float>(y + n, x + n) = 1.0f;
                outer_count += 1.0f;
            }
            if (d <= 0.45 * r){
                masks.inner.at<float>(y + n, x + n) = 1.0f;
                inner_count += 1.0f;
            }
        }
    }
    //  (a mask divided by the number of its ones, in 32 bit like NumPy does: the average)
    for (int y = 0; y < size; y++){
        for (int x = 0; x < size; x++){
            if (masks.ring.at<float>(y, x) != 0.0f){
                masks.ring.at<float>(y, x) = 1.0f / ring_count;
            }
            if (masks.outer.at<float>(y, x) != 0.0f){
                masks.outer.at<float>(y, x) = 1.0f / outer_count;
            }
            if (masks.inner.at<float>(y, x) != 0.0f){
                masks.inner.at<float>(y, x) = 1.0f / inner_count;
            }
        }
    }
    masks.win = static_cast<int>(r) | 1;
    return cache.emplace(gw, std::move(masks)).first->second;
}


//  ---- geometry ------------------------------------------------------------------------------------------------

Point clip(const Point& p){
    return {dmin(dmax(p.first, 0.03), 0.97), dmin(dmax(p.second, TOP + 0.04), 0.975)};
}

//  The line a -> b made "extra" screen widths longer at both ends.
std::pair<Point, Point> stretch(const Point& a, const Point& b, double extra){
    const double d = dist(a, b);
    if (d < 1e-6){
        return {{a.first - extra, a.second}, {b.first + extra, b.second}};
    }
    const double ux = (b.first - a.first) / d;
    const double uy = (b.second - a.second) / d;
    return {{a.first - ux * extra, a.second - uy * extra}, {b.first + ux * extra, b.second + uy * extra}};
}

//  The way of the main axis of centred points (in widths) that points to the right (down when vertical): the
//  eigenvector of the larger eigenvalue of the 2 x 2 matrix of the sums of squares and products.
struct Vec2{
    double x;
    double y;
};
Vec2 main_axis(const std::vector<Vec2>& c){
    double a = 0;
    double b = 0;
    double d = 0;
    for (const Vec2& v : c){
        a += v.x * v.x;
        b += v.x * v.y;
        d += v.y * v.y;
    }
    //  (lambda - d = half + root and lambda - a = root - half, written so that nothing cancels)
    const double half = (a - d) / 2.0;
    const double root = std::sqrt(half * half + b * b);
    Vec2 axis{1.0, 0.0};
    if (b == 0.0){
        axis = a >= d ? Vec2{1.0, 0.0} : Vec2{0.0, 1.0};
    }else if (half >= 0.0){
        axis = Vec2{half + root, b};
    }else{
        axis = Vec2{b, root - half};
    }
    const double norm = std::hypot(axis.x, axis.y);
    axis.x /= norm;
    axis.y /= norm;
    if (axis.x < -1e-12 || (std::abs(axis.x) <= 1e-12 && axis.y < 0)){
        axis.x = -axis.x;
        axis.y = -axis.y;
    }
    return axis;
}

//  The points in screen widths (x, y * ASPECT), and their mean (the way NumPy adds: in order).
std::vector<Vec2> widths(const Points& points){
    std::vector<Vec2> out;
    out.reserve(points.size());
    for (const Point& p : points){
        out.push_back({p.first, p.second * ASPECT});
    }
    return out;
}
Vec2 mean_of(const std::vector<Vec2>& points, size_t count){
    double sx = 0;
    double sy = 0;
    for (size_t i = 0; i < count; i++){
        sx += points[i].x;
        sy += points[i].y;
    }
    const double n = static_cast<double>(count);
    return {sx / n, sy / n};
}

//  The points of a group sorted along its longest direction.
Points in_line(const Points& grp){
    if (grp.size() < 3){
        Points sorted = grp;
        std::sort(sorted.begin(), sorted.end());
        return sorted;
    }
    const std::vector<Vec2> pts = widths(grp);
    const Vec2 mean = mean_of(pts, pts.size());
    std::vector<Vec2> c;
    c.reserve(pts.size());
    for (const Vec2& p : pts){
        c.push_back({p.x - mean.x, p.y - mean.y});
    }
    const Vec2 axis = main_axis(c);
    std::vector<std::pair<double, size_t>> order;
    order.reserve(c.size());
    for (size_t i = 0; i < c.size(); i++){
        order.emplace_back(c[i].x * axis.x + c[i].y * axis.y, i);
    }
    std::stable_sort(order.begin(), order.end(), [](const auto& a, const auto& b){ return a.first < b.first; });
    Points out;
    out.reserve(grp.size());
    for (const auto& item : order){
        out.push_back(grp[item.second]);
    }
    return out;
}


//  ---- what to swipe -------------------------------------------------------------------------------------

int ms_of(const Point& a, const Point& b){
    return std::max(py_round_int(dist(a, b) / SPEED * 1000), MIN_MS);
}

Swipe make_swipe(const Point& from, const Point& to){
    const Point a = clip(from);
    const Point b = clip(to);
    return {py_round(a.first, 4), py_round(a.second, 4), py_round(b.first, 4), py_round(b.second, 4), ms_of(a, b)};
}

//  The points of a group as one path: from one end, always on to the nearest point that is left.
Points chain(const Points& grp){
    Points left = grp;
    Points path;
    path.push_back(left.front());
    left.erase(left.begin());
    while (!left.empty()){
        size_t best = 0;
        double best_dist = dist(path.back(), left[0]);
        for (size_t i = 1; i < left.size(); i++){
            const double d = dist(path.back(), left[i]);
            if (d < best_dist){
                best = i;
                best_dist = d;
            }
        }
        path.push_back(left[best]);
        left.erase(left.begin() + static_cast<std::ptrdiff_t>(best));
    }
    return path;
}

//  Is this path a smooth line (no sharp bends, no big jumps)?
bool smooth(const Points& path){
    for (size_t i = 1; i < path.size(); i++){
        if (dist(path[i - 1], path[i]) > CHAIN_GAP){
            return false;
        }
    }
    for (size_t i = 2; i < path.size(); i++){
        const Point& a = path[i - 2];
        const Point& b = path[i - 1];
        const Point& c = path[i];
        const double v1x = b.first - a.first;
        const double v1y = (b.second - a.second) * ASPECT;
        const double v2x = c.first - b.first;
        const double v2y = (c.second - b.second) * ASPECT;
        const double n1 = std::hypot(v1x, v1y);
        const double n2 = std::hypot(v2x, v2y);
        if (n1 < 1e-6 || n2 < 1e-6){
            continue;
        }
        const double cosine = (v1x * v2x + v1y * v2y) / (n1 * n2);
        if (cosine < CHAIN_BEND){
            return false;
        }
    }
    return true;
}

//  The path with the points left out that lie (nearly) on the line between their neighbours.
Points simplify(const Points& path, double tol){
    if (path.size() <= 2){
        return path;
    }
    const Point& a = path.front();
    const Point& b = path.back();
    double far = -1;
    size_t where = 0;
    for (size_t i = 1; i + 1 < path.size(); i++){
        const double d = near_line(path[i], Line{a.first, a.second, b.first, b.second});
        //  (the largest (distance, index): a tie goes to the later one)
        if (far < 0 || d >= far){
            far = d;
            where = i;
        }
    }
    if (far <= tol){
        return Points{a, b};
    }
    Points head = simplify(Points(path.begin(), path.begin() + static_cast<std::ptrdiff_t>(where) + 1), tol);
    head.pop_back();
    const Points tail = simplify(Points(path.begin() + static_cast<std::ptrdiff_t>(where), path.end()), tol);
    head.insert(head.end(), tail.begin(), tail.end());
    return head;
}


}


bool type_colour(const QString& kind, int rgb[3]){
    const QString name = kind.toLower();
    for (const TypeColour& colour : TYPE_RGB){
        if (name == QLatin1String(colour.name)){
            rgb[0] = colour.r;
            rgb[1] = colour.g;
            rgb[2] = colour.b;
            return true;
        }
    }
    return false;
}


Points find_icons(const cv::Mat& img, const QString& kind, double top, int limit){
    int rgb[3];
    if (img.empty() || !type_colour(kind, rgb)){
        return {};
    }
    const int h = img.rows;
    const int w = img.cols;
    const int gw = GRID_W;
    const int gh = std::max(py_round_int(static_cast<double>(gw * h) / static_cast<double>(w)), 8);
    cv::Mat small;
    cv::resize(img, small, cv::Size(gw, gh), 0, 0, cv::INTER_AREA);
    const Masks& masks = masks_for(gw);

    cv::Mat mask(gh, gw, CV_32F);
    cv::Mat white(gh, gw, CV_32F);
    //  (BGR pictures, the colour of the type as B, G, R)
    const int target[3] = {rgb[2], rgb[1], rgb[0]};
    for (int y = 0; y < gh; y++){
        const cv::Vec3b* row = small.ptr<cv::Vec3b>(y);
        float* mask_row = mask.ptr<float>(y);
        float* white_row = white.ptr<float>(y);
        for (int x = 0; x < gw; x++){
            int far = 0;
            int lowest = 255;
            for (int c = 0; c < 3; c++){
                far = std::max(far, std::abs(static_cast<int>(row[x][c]) - target[c]));
                lowest = std::min(lowest, static_cast<int>(row[x][c]));
            }
            mask_row[x] = far <= COLOUR_TOL ? 1.0f : 0.0f;
            white_row[x] = lowest >= 190 ? 1.0f : 0.0f;
        }
    }
    cv::Mat ring;
    cv::Mat outer;
    cv::Mat inner;
    cv::filter2D(mask, ring, -1, masks.ring, cv::Point(-1, -1), 0, cv::BORDER_CONSTANT);
    cv::filter2D(mask, outer, -1, masks.outer, cv::Point(-1, -1), 0, cv::BORDER_CONSTANT);
    cv::filter2D(white, inner, -1, masks.inner, cv::Point(-1, -1), 0, cv::BORDER_CONSTANT);
    cv::Mat score = ring - outer;
    cv::Mat peak;
    cv::dilate(score, peak, cv::Mat::ones(masks.win, masks.win, CV_8U));

    const int skip = static_cast<int>(top * gh);
    struct Candidate{
        double score;
        double x;
        double y;
    };
    std::vector<Candidate> found;
    for (int y = std::max(skip, 0); y < gh; y++){
        for (int x = 0; x < gw; x++){
            const float s = score.at<float>(y, x);
            const bool ok = ring.at<float>(y, x) >= 0.55f && outer.at<float>(y, x) <= 0.55f &&
                            s >= 0.45f && inner.at<float>(y, x) >= 0.06f;
            if (ok && s >= peak.at<float>(y, x) - 1e-6f){
                found.push_back({static_cast<double>(s), x / static_cast<double>(gw), y / static_cast<double>(gh)});
            }
        }
    }
    //  (the clearest first: by score, then by x, then by y, the larger first)
    std::sort(found.begin(), found.end(), [](const Candidate& a, const Candidate& b){
        if (a.score != b.score){
            return a.score > b.score;
        }
        if (a.x != b.x){
            return a.x > b.x;
        }
        return a.y > b.y;
    });
    Points out;
    for (const Candidate& candidate : found){
        const Point p{candidate.x, candidate.y};
        bool apart = true;
        for (const Point& q : out){
            if (!(dist(p, q) > 1.2 * ICON_R)){
                apart = false;
                break;
            }
        }
        if (apart){
            out.push_back(p);
            if (static_cast<int>(out.size()) >= limit){
                break;
            }
        }
    }
    return out;
}


double dist(const Point& a, const Point& b){
    return std::hypot(a.first - b.first, (a.second - b.second) * ASPECT);
}

double near_line(const Point& p, const Line& row){
    const double ax = row.x1;
    const double ay = row.y1 * ASPECT;
    const double bx = row.x2;
    const double by = row.y2 * ASPECT;
    const double px = p.first;
    const double py = p.second * ASPECT;
    const double dx = bx - ax;
    const double dy = by - ay;
    const double n = dx * dx + dy * dy;
    const double t = n < 1e-9 ? 0.0 : dmin(dmax(((px - ax) * dx + (py - ay) * dy) / n, 0.0), 1.0);
    return std::hypot(px - (ax + t * dx), py - (ay + t * dy));
}

std::vector<Points> groups(const Points& points, double link){
    Points left = points;
    std::vector<Points> out;
    while (!left.empty()){
        Points grp{left.front()};
        left.erase(left.begin());
        bool grew = true;
        while (grew){
            grew = false;
            //  (a copy of what is left: the group grows while it is walked through)
            const Points snapshot = left;
            for (const Point& p : snapshot){
                bool near = false;
                for (const Point& q : grp){
                    if (dist(p, q) <= link){
                        near = true;
                        break;
                    }
                }
                if (near){
                    grp.push_back(p);
                    left.erase(std::find(left.begin(), left.end(), p));
                    grew = true;
                }
            }
        }
        out.push_back(in_line(grp));
    }
    return out;
}


//  ---- one little game -----------------------------------------------------------------------------------------

Game::Game(const QString& kind_, double t0_, const std::optional<Learned>& learned_)
    : kind(kind_.toLower())
    , t0(t0_)
{
    const KnownLines* builtin_known = builtin_lines(kind);
    std::vector<Line> known_gates;
    std::vector<Line> known_rows;
    if (builtin_known != nullptr){
        known_gates = builtin_known->gates;
        known_rows = builtin_known->rows;
    }else if (learned_.has_value()){
        known_gates = learned_->gates;
        known_rows = learned_->rows;
    }
    prior = known_gates;
    for (const Line& row : known_rows){
        rows.push_back({row, std::nullopt});
    }
    builtin = builtin_known != nullptr;
}

void Game::see(double t, const Points& icons_seen){
    frames.push_back({t, icons_seen});
    std::vector<Frame> kept;
    for (const Frame& frame : frames){
        if (frame.t >= t - 1.5){
            kept.push_back(frame);
        }
    }
    frames = std::move(kept);
    if (icons_seen.empty()){
        return;
    }
    pictures++;
    icons += static_cast<int>(icons_seen.size());
    if (!first.has_value()){
        first = t;
        if (!blind){
            t0 = t - LEAD;                          //  (it was waited for: this is when it really started)
        }
    }
    last = t;
    for (const Points& grp : groups(icons_seen)){
        const std::optional<bool> is_moving = moving(grp);
        if (is_moving.has_value() && !*is_moving && grp.size() >= 2){     //  a row that stands still is remembered
            remember(Line{grp.front().first, grp.front().second, grp.back().first, grp.back().second}, t);
        }else if (is_moving.has_value() && *is_moving){
            //  (what is new is judged against what was there before this group)
            Points fresh;
            const size_t from = trail.size() > 60 ? trail.size() - 60 : 0;
            for (const Point& p : grp){
                bool apart = true;
                for (size_t i = from; i < trail.size(); i++){
                    if (!(dist(p, trail[i]) > 0.02)){
                        apart = false;
                        break;
                    }
                }
                if (apart){
                    fresh.push_back(p);
                }
            }
            trail.insert(trail.end(), fresh.begin(), fresh.end());
            if (trail.size() > 600){
                trail.resize(600);                  //  (the first ones stay: they tell where the stream starts)
            }
        }
    }
    find_gate();
}

void Game::remember(const Line& row, std::optional<double> t){
    for (Row& old : rows){
        if (dist({old.line.x1, old.line.y1}, {row.x1, row.y1}) <= 0.09 &&
            dist({old.line.x2, old.line.y2}, {row.x2, row.y2}) <= 0.09
        ){
            if (t.has_value()){
                old.seen = t;
            }
            return;
        }
    }
    if (rows.size() < 8){
        rows.push_back({row, t});
    }
}

//  The place to wait for a stream of icons: a line across it, halfway along the part of the screen where the
//  icons were seen, as wide as the stream has been there.
void Game::find_gate(){
    if (static_cast<int>(trail.size()) < GATE_ICONS){
        return;
    }
    const std::vector<Vec2> pts = widths(trail);
    const Vec2 src = mean_of(pts, 3);
    const Vec2 all = mean_of(pts, pts.size());
    const double dx = all.x - src.x;
    const double dy = all.y - src.y;
    const double n = std::hypot(dx, dy);
    if (n < 0.10){
        return;                                     //  (icons around one place: no stream)
    }
    const Vec2 axis{dx / n, dy / n};
    const Vec2 across{-axis.y, axis.x};
    std::vector<double> along;
    std::vector<double> side;
    along.reserve(pts.size());
    side.reserve(pts.size());
    for (const Vec2& p : pts){
        const double rx = p.x - src.x;
        const double ry = p.y - src.y;
        along.push_back(rx * axis.x + ry * axis.y);
        side.push_back(rx * across.x + ry * across.y);
    }
    const double along_min = *std::min_element(along.begin(), along.end());
    const double along_max = *std::max_element(along.begin(), along.end());
    if (along_max - along_min < GATE_LONG){
        return;                                     //  (too little of the stream was seen)
    }
    const double at = (along_min + along_max) / 2.0;
    bool any = false;
    double side_min = 0;
    double side_max = 0;
    for (size_t i = 0; i < along.size(); i++){
        if (std::abs(along[i] - at) <= GATE_NEAR){
            if (!any){
                side_min = side_max = side[i];
                any = true;
            }else{
                side_min = dmin(side_min, side[i]);
                side_max = dmax(side_max, side[i]);
            }
        }
    }
    if (!any){
        return;
    }
    double lo = side_min - GATE_SIDE;
    double hi = side_max + GATE_SIDE;
    const double centre = (lo + hi) / 2.0;
    lo = dmin(lo, centre - GATE_HALF);
    hi = dmax(hi, centre + GATE_HALF);
    const double px = src.x + axis.x * at + across.x * lo;
    const double py = src.y + axis.y * at + across.y * lo;
    const double qx = src.x + axis.x * at + across.x * hi;
    const double qy = src.y + axis.y * at + across.y * hi;
    const Point a = clip({px, py / ASPECT});
    const Point b = clip({qx, qy / ASPECT});
    gate = Line{py_round(a.first, 3), py_round(a.second, 3), py_round(b.first, 3), py_round(b.second, 3)};
}

std::optional<Learned> Game::learned() const{
    Learned out;
    for (const Row& row : rows){
        if (row.seen.has_value()){
            out.rows.push_back(Line{
                py_round(row.line.x1, 3), py_round(row.line.y1, 3), py_round(row.line.x2, 3), py_round(row.line.y2, 3)
            });
        }
    }
    if (builtin || (out.rows.empty() && !gate.has_value())){
        return std::nullopt;
    }
    if (gate.has_value()){
        out.gates.push_back(*gate);
    }
    return out;
}

void Game::hold(double now, double wait){
    if (!first.has_value()){
        blind = false;
        t0 = now + wait - GAME_SECONDS;
    }
}

void Game::started(double now){
    if (!first.has_value()){
        blind = true;
        plain = false;
        t0 = now - GET_READY;
    }
}

bool Game::over(double now) const{
    if (now - t0 > GAME_SECONDS){
        return true;
    }
    if (!last.has_value() || now - *last <= QUIET){
        return false;
    }
    return now - t0 > LEAD + ICONS_FOR;
}

std::optional<bool> Game::moving(const Points& grp) const{
    if (frames.empty()){
        return std::nullopt;
    }
    const double t = frames.back().t;
    const Points& newest = frames.back().icons;
    std::vector<const Frame*> refs;
    for (size_t i = 0; i + 1 < frames.size(); i++){
        const double age = t - frames[i].t;
        if (STILL_FROM <= age && age <= STILL_TO){
            refs.push_back(&frames[i]);
        }
    }
    if (refs.empty() || t - refs.front()->t < STILL_FOR){
        return std::nullopt;
    }
    Points mine;
    for (const Point& p : grp){
        for (const Point& q : newest){
            if (dist(p, q) <= 1e-9){
                mine.push_back(p);
                break;
            }
        }
    }
    if (mine.empty()){
        return std::nullopt;
    }
    int still = 0;
    int moved = 0;
    for (const Point& p : mine){
        bool stays = true;
        for (const Frame* ref : refs){
            bool seen_there = false;
            for (const Point& q : ref->icons){
                if (dist(p, q) <= STILL){
                    seen_there = true;
                    break;
                }
            }
            if (!seen_there){
                stays = false;
                break;
            }
        }
        if (stays){
            still++;
            continue;
        }
        bool was_there = false;
        bool was_close = false;
        for (const Point& q : refs.back()->icons){
            if (dist(p, q) <= STILL){
                was_there = true;
                break;
            }
        }
        for (const Point& q : refs.back()->icons){
            if (dist(p, q) <= MOVED){
                was_close = true;
                break;
            }
        }
        if (!was_there && was_close){
            moved++;                    //  (nothing was here on the picture before, but an icon was close by)
        }
    }
    if (still * 2 > static_cast<int>(mine.size())){
        return false;
    }
    if (moved * 2 > static_cast<int>(mine.size())){
        return true;
    }
    return std::nullopt;
}

std::vector<Swipe> Game::plan(double now){
    if (over(now)){
        return {};
    }
    if (!first.has_value() && (!blind || plain)){
        return {};                      //  (nothing seen yet and the attack has not started: a blind swipe over the
                                        //  fight itself could tap a button)
    }
    Points pts;
    if (!frames.empty() && now - frames.back().t <= FRESH){
        pts = frames.back().icons;      //  (the newest picture, when it is not too old)
    }
    if (plain && pts.empty()){
        return {};                      //  (the plain fight is back and no icon on it)
    }
    turn++;
    const bool flip = turn % 2 == 1;    //  (there and back: not always from the same side)
    std::vector<Swipe> out;
    std::vector<Line> visit;
    for (const Row& row : rows){
        if (!row.seen.has_value() || now - *row.seen <= ROW_LIFE){
            visit.push_back(row.line);
        }
    }
    //  (the row with the most icons on it right now goes first)
    std::vector<std::pair<int, Line>> counted;
    for (const Line& row : visit){
        int count = 0;
        for (const Point& p : pts){
            if (near_line(p, row) <= ICON_R){
                count++;
            }
        }
        counted.emplace_back(count, row);
    }
    std::stable_sort(counted.begin(), counted.end(), [](const auto& a, const auto& b){ return a.first > b.first; });
    visit.clear();
    for (const auto& item : counted){
        visit.push_back(item.second);
    }
    for (const Line& row : visit){                  //  rows of icons that stand still: they come back there
        const std::pair<Point, Point> ends = stretch({row.x1, row.y1}, {row.x2, row.y2}, REACH);
        out.push_back(flip ? make_swipe(ends.second, ends.first) : make_swipe(ends.first, ends.second));
    }
    std::vector<Line> gates = prior;
    if (gates.empty() && gate.has_value()){
        gates.push_back(*gate);
    }
    for (const Line& g : gates){                    //  the place where the stream comes by: there and back
        const int times = std::max(GATE_TIMES / (2 * static_cast<int>(gates.size())), 1);
        for (int i = 0; i < times; i++){
            out.push_back(make_swipe({g.x1, g.y1}, {g.x2, g.y2}));
            out.push_back(make_swipe({g.x2, g.y2}, {g.x1, g.y1}));
        }
    }
    bool painted = false;
    for (const Points& grp : groups(pts)){
        bool on_rows = true;
        for (const Point& p : grp){
            bool on_one = false;
            for (const Line& row : visit){
                if (near_line(p, row) <= ICON_R){
                    on_one = true;
                    break;
                }
            }
            if (!on_one){
                on_rows = false;
                break;
            }
        }
        if (on_rows){
            continue;                               //  (these icons are on a row that is swiped already)
        }
        const std::optional<bool> is_moving = moving(grp);
        const bool not_still = !is_moving.has_value() || *is_moving;
        if (!gates.empty() && not_still){
            continue;                               //  (a stream: the gate takes care of it)
        }
        const std::vector<Swipe> lines = paint(grp, not_still, flip);
        out.insert(out.end(), lines.begin(), lines.end());
        painted = true;
    }
    if (out.empty() || (gates.empty() && visit.empty() && !painted)){
        for (const Line& line : STAR){              //  nothing known, nothing seen: try everywhere
            out.push_back(make_swipe({line.x1, line.y1}, {line.x2, line.y2}));
        }
    }
    if (static_cast<int>(out.size()) > MAX_SWIPES){
        out.resize(static_cast<size_t>(MAX_SWIPES));
    }
    swipes += static_cast<int>(out.size());
    return out;
}

//  Swipes that cover the place where a group of icons is.  Icons in a smooth line get one swipe along that
//  line; a group that is spread out gets lines next to each other over the whole strip the icons are in.
std::vector<Swipe> Game::paint(const Points& grp, bool is_moving, bool flip) const{
    const double reach = is_moving ? REACH_MOVING : REACH;
    if (grp.size() == 1){
        const std::pair<Point, Point> ends = stretch(grp[0], grp[0], reach);
        return {flip ? make_swipe(ends.second, ends.first) : make_swipe(ends.first, ends.second)};
    }
    Points line = chain(grp);
    if (smooth(line)){
        line = simplify(line, 0.03);
        const Point first_end = stretch(line[0], line[1], reach).first;
        const Point last_end = stretch(line[line.size() - 2], line[line.size() - 1], reach).second;
        line.front() = first_end;
        line.back() = last_end;
        if (flip){
            std::reverse(line.begin(), line.end());
        }
        std::vector<Swipe> out;
        for (size_t i = 1; i < line.size(); i++){
            out.push_back(make_swipe(line[i - 1], line[i]));
        }
        return out;
    }
    const std::vector<Vec2> pts = widths(grp);
    const Vec2 mid = mean_of(pts, pts.size());
    std::vector<Vec2> c;
    c.reserve(pts.size());
    for (const Vec2& p : pts){
        c.push_back({p.x - mid.x, p.y - mid.y});
    }
    const Vec2 axis = main_axis(c);                 //  the direction of the group (in widths)
    const Vec2 across{-axis.y, axis.x};
    double along_min = 0;
    double along_max = 0;
    double side_min = 0;
    double side_max = 0;
    for (size_t i = 0; i < c.size(); i++){
        const double along = c[i].x * axis.x + c[i].y * axis.y;
        const double side = c[i].x * across.x + c[i].y * across.y;
        if (i == 0){
            along_min = along_max = along;
            side_min = side_max = side;
        }else{
            along_min = dmin(along_min, along);
            along_max = dmax(along_max, along);
            side_min = dmin(side_min, side);
            side_max = dmax(side_max, side);
        }
    }
    const double a0 = along_min - reach;
    const double a1 = along_max + reach;
    const double edge = is_moving ? SIDE_MOVING : 0.0;
    const double s0 = side_min - edge;
    const double s1 = side_max + edge;
    const int n = std::min(std::max(static_cast<int>(std::ceil((s1 - s0) / LINE_GAP)), 1), MAX_LINES);
    std::vector<Swipe> out;
    for (int i = 0; i < n; i++){
        const double sv = n == 1 ? (s0 + s1) / 2.0 : s0 + (s1 - s0) * (i + 0.5) / n;
        const double px = mid.x + axis.x * a0 + across.x * sv;
        const double py = mid.y + axis.y * a0 + across.y * sv;
        const double qx = mid.x + axis.x * a1 + across.x * sv;
        const double qy = mid.y + axis.y * a1 + across.y * sv;
        const Point p{px, py / ASPECT};
        const Point q{qx, qy / ASPECT};
        out.push_back(((i % 2 == 1) != flip) ? make_swipe(q, p) : make_swipe(p, q));
    }
    return out;
}


//  ---- the check ---------------------------------------------------------------------------------------------------

namespace{


//  The first place where two answers differ ("" when they do not).
QString first_difference(const QJsonValue& got, const QJsonValue& want, const QString& path){
    if (got.isDouble() && want.isDouble()){
        const double a = got.toDouble();
        const double b = want.toDouble();
        return std::abs(a - b) <= 1e-9 + 1e-9 * std::abs(b) ? QString() : path;
    }
    if (got.type() != want.type()){
        return path;
    }
    if (got.isArray()){
        const QJsonArray a = got.toArray();
        const QJsonArray b = want.toArray();
        if (a.size() != b.size()){
            return path + "(length)";
        }
        for (qsizetype i = 0; i < a.size(); i++){
            const QString d = first_difference(a[i], b[i], path + "[" + QString::number(i) + "]");
            if (!d.isEmpty()){
                return d;
            }
        }
        return QString();
    }
    if (got.isObject()){
        const QJsonObject a = got.toObject();
        const QJsonObject b = want.toObject();
        if (a.keys() != b.keys()){
            return path + "(keys)";
        }
        for (const QString& key : b.keys()){
            const QString d = first_difference(a.value(key), b.value(key), path + "." + key);
            if (!d.isEmpty()){
                return d;
            }
        }
        return QString();
    }
    return got == want ? QString() : path;
}

QString compact(const QJsonValue& value){
    QJsonArray wrap{value};
    QString text = QString::fromUtf8(QJsonDocument(wrap).toJson(QJsonDocument::Compact));
    return text.mid(1, text.size() - 2);
}

QJsonValue at_path(QJsonValue value, const QString& path){
    //  (only to show the two things that differ: .a.b[3] -> the value there)
    QString rest = path;
    while (!rest.isEmpty()){
        if (rest[0] == '.'){
            qsizetype end = 1;
            while (end < rest.size() && rest[end] != '.' && rest[end] != '['){
                end++;
            }
            value = value.toObject().value(rest.mid(1, end - 1));
            rest = rest.mid(end);
        }else if (rest[0] == '['){
            const qsizetype end = rest.indexOf(']');
            value = value.toArray().at(rest.mid(1, end - 1).toInt());
            rest = rest.mid(end + 1);
        }else{
            break;
        }
    }
    return value;
}

int clip_int(int v, int n){
    return std::max(0, std::min(v, n));
}

//  The pictures of the recipes: the real ones of the fixtures, and the steps that make the others (see run() in
//  make_minigame_golden.py).
class Pictures{
public:
    explicit Pictures(const QString& folder) : m_folder(folder){}

    const cv::Mat& frame(const QString& name){
        auto it = m_loaded.find(name);
        if (it == m_loaded.end()){
            cv::Mat img;
            QFile file(m_folder + "/" + name);
            if (file.open(QIODevice::ReadOnly)){
                const QByteArray bytes = file.readAll();
                const uchar* data = reinterpret_cast<const uchar*>(bytes.constData());
                const std::vector<uchar> buffer(data, data + bytes.size());
                img = cv::imdecode(buffer, cv::IMREAD_COLOR);
            }
            it = m_loaded.insert(name, img);
        }
        return it.value();
    }

    bool make(const QJsonArray& ops, cv::Mat& img, QString& error){
        img = cv::Mat();
        for (const QJsonValue& op_value : ops){
            const QJsonArray op = op_value.toArray();
            const QString kind = op.at(0).toString();
            if (kind == "load"){
                img = frame(op.at(1).toString()).clone();
                if (img.empty()){
                    error = "a picture is not there: " + op.at(1).toString();
                    return false;
                }
            }else if (kind == "blank"){
                img = cv::Mat(op.at(2).toInt(), op.at(1).toInt(), CV_8UC3,
                              cv::Scalar(op.at(3).toInt(), op.at(4).toInt(), op.at(5).toInt()));
            }else if (kind == "size"){
                cv::Mat out;
                cv::resize(img, out, cv::Size(op.at(1).toInt(), op.at(2).toInt()), 0, 0, op.at(3).toInt());
                img = out;
            }else if (kind == "scale"){
                cv::Mat out;
                cv::convertScaleAbs(img, out, op.at(1).toDouble(), op.at(2).toDouble());
                img = out;
            }else if (kind == "fill"){
                const int x0 = clip_int(op.at(1).toInt(), img.cols);
                const int y0 = clip_int(op.at(2).toInt(), img.rows);
                const int x1 = clip_int(op.at(3).toInt(), img.cols);
                const int y1 = clip_int(op.at(4).toInt(), img.rows);
                if (x1 > x0 && y1 > y0){
                    img(cv::Rect(x0, y0, x1 - x0, y1 - y0)) =
                        cv::Scalar(op.at(5).toInt(), op.at(6).toInt(), op.at(7).toInt());
                }
            }else if (kind == "disc"){
                cv::circle(img, cv::Point(op.at(1).toInt(), op.at(2).toInt()), op.at(3).toInt(),
                           cv::Scalar(op.at(4).toInt(), op.at(5).toInt(), op.at(6).toInt()), cv::FILLED);
            }else{
                error = "a step that the port does not know: " + kind;
                return false;
            }
        }
        return !img.empty();
    }

private:
    QString m_folder;
    QHash<QString, cv::Mat> m_loaded;
};


Points points_of(const QJsonArray& array){
    Points out;
    for (const QJsonValue& value : array){
        const QJsonArray pair = value.toArray();
        out.emplace_back(pair.at(0).toDouble(), pair.at(1).toDouble());
    }
    return out;
}

QJsonArray json_of(const Points& points){
    QJsonArray out;
    for (const Point& p : points){
        out.append(QJsonArray{p.first, p.second});
    }
    return out;
}

QJsonArray json_of(const Line& line){
    return QJsonArray{line.x1, line.y1, line.x2, line.y2};
}

QJsonValue optional_json(const std::optional<double>& value){
    return value.has_value() ? QJsonValue(*value) : QJsonValue(QJsonValue::Null);
}

Line line_of(const QJsonValue& value){
    const QJsonArray a = value.toArray();
    return Line{a.at(0).toDouble(), a.at(1).toDouble(), a.at(2).toDouble(), a.at(3).toDouble()};
}

QJsonValue learned_json(const std::optional<Learned>& learned){
    if (!learned.has_value()){
        return QJsonValue(QJsonValue::Null);
    }
    QJsonArray rows;
    QJsonArray gates;
    for (const Line& row : learned->rows){
        rows.append(json_of(row));
    }
    for (const Line& g : learned->gates){
        gates.append(json_of(g));
    }
    return QJsonObject{{"rows", rows}, {"gates", gates}};
}

QJsonObject state_json(const Game& game){
    QJsonArray rows;
    for (const Game::Row& row : game.rows){
        QJsonArray item = json_of(row.line);
        item.append(optional_json(row.seen));
        rows.append(item);
    }
    QJsonArray prior;
    for (const Line& g : game.prior){
        prior.append(json_of(g));
    }
    return QJsonObject{
        {"first", optional_json(game.first)}, {"last", optional_json(game.last)},
        {"pictures", game.pictures}, {"icons", game.icons}, {"swipes", game.swipes},
        {"gate", game.gate.has_value() ? QJsonValue(json_of(*game.gate)) : QJsonValue(QJsonValue::Null)},
        {"rows", rows}, {"trail", static_cast<int>(game.trail.size())}, {"turn", game.turn},
        {"blind", game.blind}, {"plain", game.plain}, {"t0", game.t0}, {"prior", prior},
        {"kind", game.kind}, {"builtin", game.builtin},
    };
}

//  The answers of a game to its steps (see play() in make_minigame_golden.py).
bool play(const QJsonArray& steps, QJsonArray& answers, QString& error){
    std::optional<Game> game;
    for (const QJsonValue& step_value : steps){
        const QJsonArray step = step_value.toArray();
        const QString kind = step.at(0).toString();
        if (kind == "new"){
            std::optional<Learned> learned;
            if (step.at(3).isObject()){
                const QJsonObject object = step.at(3).toObject();
                Learned made;
                for (const QJsonValue& row : object.value("rows").toArray()){
                    made.rows.push_back(line_of(row));
                }
                for (const QJsonValue& g : object.value("gates").toArray()){
                    made.gates.push_back(line_of(g));
                }
                learned = made;
            }
            game.emplace(step.at(1).toString(), step.at(2).toDouble(), learned);
            answers.append(state_json(*game));
            continue;
        }
        if (!game.has_value()){
            error = "a game has not begun";
            return false;
        }
        if (kind == "see"){
            game->see(step.at(1).toDouble(), points_of(step.at(2).toArray()));
            answers.append(QJsonValue(QJsonValue::Null));
        }else if (kind == "plan"){
            QJsonArray list;
            for (const Swipe& s : game->plan(step.at(1).toDouble())){
                list.append(QJsonArray{s.x1, s.y1, s.x2, s.y2, s.ms});
            }
            answers.append(list);
        }else if (kind == "over"){
            answers.append(game->over(step.at(1).toDouble()));
        }else if (kind == "hold"){
            if (step.size() > 2){
                game->hold(step.at(1).toDouble(), step.at(2).toDouble());
            }else{
                game->hold(step.at(1).toDouble());
            }
            answers.append(QJsonValue(QJsonValue::Null));
        }else if (kind == "started"){
            game->started(step.at(1).toDouble());
            answers.append(QJsonValue(QJsonValue::Null));
        }else if (kind == "plain"){
            game->plain = step.at(1).toBool();
            answers.append(QJsonValue(QJsonValue::Null));
        }else if (kind == "blind"){
            game->blind = step.at(1).toBool();
            answers.append(QJsonValue(QJsonValue::Null));
        }else if (kind == "moving"){
            const std::optional<bool> is_moving = game->moving(points_of(step.at(1).toArray()));
            answers.append(is_moving.has_value() ? QJsonValue(*is_moving) : QJsonValue(QJsonValue::Null));
        }else if (kind == "learned"){
            answers.append(learned_json(game->learned()));
        }else if (kind == "state"){
            answers.append(state_json(*game));
        }else{
            error = "a step that the port does not know: " + kind;
            return false;
        }
    }
    return true;
}


}

int run_minigame_checks(const QString& golden, const QString& fixtures, QStringList& report){
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the answers of battle_minigame.py are not there: " + golden;
        return 1;
    }
    const QByteArray json = qUncompress(file.readAll());
    const QJsonObject root = QJsonDocument::fromJson(json).object();
    const QJsonArray cases = root.value("cases").toArray();
    if (cases.isEmpty()){
        report << "FAILED: the file of answers of battle_minigame.py is empty or not right: " + golden;
        return 1;
    }
    Pictures pictures(fixtures);
    int differ = 0;
    int pictures_checked = 0;
    int games_checked = 0;
    int steps_checked = 0;
    for (qsizetype index = 0; index < cases.size(); index++){
        const QJsonObject item = cases[index].toObject();
        const QString which = item.value("case").toString();
        QString difference;
        QString detail;
        if (which == "icons"){
            cv::Mat img;
            QString error;
            if (!pictures.make(item.value("ops").toArray(), img, error)){
                report << "FAILED: case " + QString::number(index) + ": " + error;
                differ++;
                continue;
            }
            const double top = item.contains("top") ? item.value("top").toDouble() : TOP;
            const int limit = item.contains("limit") ? item.value("limit").toInt() : 12;
            const QJsonArray got = json_of(find_icons(img, item.value("type").toString(), top, limit));
            const QJsonArray want = item.value("found").toArray();
            difference = first_difference(got, want, "");
            if (!difference.isEmpty()){
                detail = "the icons of " + item.value("type").toString() + ": " + compact(got) + " (Python: " + compact(want) + ")";
            }
            pictures_checked++;
        }else if (which == "game"){
            QJsonArray got;
            QString error;
            const QJsonArray steps = item.value("steps").toArray();
            if (!play(steps, got, error)){
                report << "FAILED: case " + QString::number(index) + ": " + error;
                differ++;
                continue;
            }
            const QJsonArray want = item.value("answers").toArray();
            difference = first_difference(got, want, "");
            if (!difference.isEmpty()){
                //  The step: "[12].x" -> step 12.
                const qsizetype close = difference.indexOf(']');
                const int at = difference.startsWith('[') && close > 1 ? difference.mid(1, close - 1).toInt() : 0;
                detail = "step " + QString::number(at) + " " + compact(steps.at(at)) + ": " +
                         compact(at_path(got, difference)) + " (Python: " + compact(at_path(want, difference)) + ")";
            }
            games_checked++;
            steps_checked += static_cast<int>(steps.size());
        }else{
            report << "FAILED: case " + QString::number(index) + ": a case that the port does not know: " + which;
            differ++;
            continue;
        }
        if (!difference.isEmpty()){
            differ++;
            if (differ <= 8){
                report << "FAILED: case " + QString::number(index) + " (" + which + ") differs at " + difference + ": " + detail;
            }
        }
    }
    report << QString("%1 pictures and %2 games (%3 steps) were checked against battle_minigame.py: %4 differ.")
                  .arg(pictures_checked).arg(games_checked).arg(steps_checked).arg(differ);
    return differ;
}


}
}
}
}
