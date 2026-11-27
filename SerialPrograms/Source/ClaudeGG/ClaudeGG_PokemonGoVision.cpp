/*  Claude GG Pokemon GO Vision (the screen of a GO Battle League fight, read from the picture)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  See the header.  The Python code is the reference: every function here is
 *  its twin, in the same order of steps, with the same OpenCV calls where it
 *  has them (cvtColor, inRange, resize with INTER_AREA, morphologyEx,
 *  connectedComponentsWithStats), and with the rounding of Python and NumPy
 *  where it counts (round() is half to even, int() cuts, the standard
 *  deviation of the pop-up check is a 32 bit one, the percentile is cut to 32
 *  bits).  The comments are those of battle_vision.py, shortened.
 *
 */

#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdlib>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <QByteArray>
#include <QFile>
#include <QHash>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include "ClaudeGG_PokemonGoVision.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Vision{


//  ---- where things are (fractions of the screen width / height) --------------------------------------

const double BTN_Y = 0.816;
const double BTN_X[2] = {0.307, 0.690};
const double TAP_FAST[2] = {0.50, 0.45};
const double TAP_SHIELD[2] = {0.50, 0.70};
const double TAP_NOT_NOW[2] = {0.50, 0.91};
const double TAP_NEXT[2] = {0.50, 0.866};
const double TAP_DONE[2] = {0.50, 0.926};
const double DONE_R = 0.040;
const double POPUP_TILES[2] = {0.32, 0.68};
const double POPUP_TILE_Y = 0.74;
const double BAR_FULL = 484 / 1768.0;
const double RUN_BUTTON[2] = {0.081, 0.268};
const double EXIT_YES_Y[2] = {0.42, 0.64};

namespace{

const double LABEL_Y[2] = {0.895, 0.935};   //  the name of the move under a button (bright white when it is ready)
const double LABEL_HALF = 0.11;             //  ... the zone that is looked at reaches this far to both sides
const int LABEL_RUNS = 4;                   //  ... a row of text: this many short white stretches or more
const double LABEL_ROWS[2] = {0.008, 0.026};
const double LABEL_INK = 0.18;
const int LABEL_STROKES = 2;
const double SHIELD_SLOTS_Y = 0.171;        //  the two shield icons in each name box
const double SHIELD_SLOTS[2][2] = {{0.235, 0.283}, {0.717, 0.764}};     //  me, foe
const double COUNT_DISCS[2][3] = {{0.499, 0.143, 0.066}, {0.501, 0.158, 0.070}};
const double COUNT_LAST[2] = {238.0, 267.0};
const double BALL_Y = 0.170;
const double BALL_X[2][3] = {{0.053, 0.107, 0.161}, {0.836, 0.890, 0.944}};     //  me, foe
const double BALL_R = 0.011;
const double SHIELD_ICON[2] = {0.50, 0.715};
const double KEY_DIFF = 7.0;
const double GET_READY_ZONE[4] = {0.412, 0.154, 0.588, 0.204};
const double GET_READY_MATCH = 0.65;
const int GET_READY_W = 62;
const int GET_READY_H = 22;
const char* const GET_READY[GET_READY_H] = {
    "..............................................................",
    "..............................................................",
    "..............................................................",
    "..............................................................",
    "..............................................................",
    "......................######..............................#...",
    "............##........########............................#...",
    "............##........###...###...........................##..",
    "............##........###...###..........................###..",
    "...#####..######......###...###...######...######....#######.#",
    "..##..###..####.......###...##...########..######...########.#",
    ".##....##...##........########...##....##......###.###...###..",
    ".########...##........#######....########......###.###...###..",
    ".########..###........###.###....########..#######.###...###..",
    ".##.........##........##...###...##.......###..###.###...###..",
    "..##........##........##....##...###......##...###..##...###..",
    "..#######...####......##....###...#######.########..########..",
    "....###......###......##.....##....#####...####.##...###..#...",
    "..............................................................",
    "..............................................................",
    "..............................................................",
    "..............................................................",
};
struct ButtonColour{
    const char* name;
    int hue0;
    int hue1;
    int sat_min;
    int val_min;
};
const ButtonColour BUTTON_COLOURS[2] = {{"green", 55, 95, 70, 150}, {"orange", 8, 24, 110, 200}};
const int BUTTON_TINT = 25;                 //  the label makes the colour paler: this saturation still belongs to the button
const double BUTTON_WIDE = 0.25;
const double BUTTON_HIGH[2] = {0.018, 0.11};


//  ---- the way Python and NumPy count -----------------------------------------------------------------

//  int(): cuts towards zero.
int pyint(double v){
    return static_cast<int>(v);
}

//  round(x, 3): the decimal that is nearest to the real value of the double, a tie to the even one.
double py_round3(double x){
    char buf[64];
    const std::to_chars_result done = std::to_chars(buf, buf + sizeof(buf) - 1, x, std::chars_format::fixed, 3);
    *done.ptr = 0;
    return std::strtod(buf, nullptr);
}

//  .mean() of a mask: the part that is True (NaN for nothing at all, as NumPy has it).
double share(long long count, long long total){
    return total > 0 ? static_cast<double>(count) / static_cast<double>(total) : std::nan("");
}

//  A slice [a:b] of a length n.
int clip(int v, int n){
    return std::max(0, std::min(v, n));
}

bool valid(const cv::Mat& img){
    return img.type() == CV_8UC3 && img.rows > 0 && img.cols > 0;
}

inline int mn3(const uchar* p){
    return std::min(std::min<int>(p[0], p[1]), static_cast<int>(p[2]));
}
inline int mx3(const uchar* p){
    return std::max(std::max<int>(p[0], p[1]), static_cast<int>(p[2]));
}

//  A part of the picture (the part that is inside it, as a slice of NumPy gives it).
struct Win{
    int y0;
    int y1;
    int x0;
    int x1;
    int rows() const{ return std::max(y1 - y0, 0); }
    int cols() const{ return std::max(x1 - x0, 0); }
    long long size() const{ return static_cast<long long>(rows()) * cols(); }
};
Win slice(const cv::Mat& img, int y0, int y1, int x0, int x1){
    return Win{clip(y0, img.rows), clip(y1, img.rows), clip(x0, img.cols), clip(x1, img.cols)};
}
//  _box(): a part of the picture given in fractions.
Win box(const cv::Mat& img, double x0, double y0, double x1, double y1){
    const int h = img.rows, w = img.cols;
    return slice(img, pyint(y0 * h), pyint(y1 * h), pyint(x0 * w), pyint(x1 * w));
}

//  Pale, hardly coloured pixels (the name boxes at the top, the white of a ring).
inline bool pale_px(const uchar* p){
    const int mn = mn3(p), mx = mx3(p);
    return mn > 190 && mx - mn < 50;
}
//  (the frame of an HP bar:) light and hardly coloured.
inline bool frame_px(int mn, int mx){
    return mn > 150 && mx - mn < 90;
}

//  np.median of a list of numbers, as the double it gives.
double median_of(std::vector<int> values){
    std::sort(values.begin(), values.end());
    const size_t n = values.size();
    if (n % 2 == 1){
        return static_cast<double>(values[n / 2]);
    }
    return (static_cast<double>(values[n / 2 - 1]) + static_cast<double>(values[n / 2])) / 2.0;
}

//  NumPy's sum of 32 bit numbers that lie after each other (pairwise, eight at a time).
float pairwise_sum(const float* a, long long n){
    if (n < 8){
        float res = 0.0f;
        for (long long i = 0; i < n; i++){
            res += a[i];
        }
        return res;
    }
    if (n <= 128){
        float r[8];
        for (int j = 0; j < 8; j++){
            r[j] = a[j];
        }
        long long i = 8;
        for (; i < n - (n % 8); i += 8){
            for (int j = 0; j < 8; j++){
                r[j] += a[i + j];
            }
        }
        float res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
        for (; i < n; i++){
            res += a[i];
        }
        return res;
    }
    long long n2 = n / 2;
    n2 -= n2 % 8;
    return pairwise_sum(a, n2) + pairwise_sum(a + n2, n - n2);
}

}


//  ---- the readers --------------------------------------------------------------------------------------------

bool is_white_screen(const cv::Mat& img){
    if (!valid(img)){
        return false;
    }
    long long sum = 0, n = 0;
    for (int y = 0; y < img.rows; y += 8){
        const uchar* p = img.ptr<uchar>(y);
        for (int x = 0; x < img.cols; x += 8){
            sum += p[3 * x] + p[3 * x + 1] + p[3 * x + 2];
            n += 3;
        }
    }
    return n > 0 && static_cast<double>(sum) / static_cast<double>(n) > 245;
}

bool is_versus(const cv::Mat& img){
    if (!valid(img)){
        return false;
    }
    const int h = img.rows, w = img.cols;
    const Win b = slice(img, pyint(0.495 * h), pyint(0.505 * h), pyint(0.02 * w), pyint(0.98 * w));
    const int bw = b.cols();
    //  (a white line is in a column when any of the rows has white there)
    std::vector<char> white(bw, 0);
    for (int y = b.y0; y < b.y1; y++){
        const uchar* p = img.ptr<uchar>(y);
        for (int x = 0; x < bw; x++){
            if (mn3(p + 3 * (b.x0 + x)) > 225){
                white[x] = 1;
            }
        }
    }
    //  (the round VS badge sits in the middle: leave it out)
    const int cut0 = pyint(0.40 * bw), cut1 = pyint(0.60 * bw);
    long long total = 0, count = 0;
    for (int x = 0; x < bw; x++){
        if (x >= cut0 && x < cut1){
            continue;
        }
        total++;
        count += white[x];
    }
    return share(count, total) > 0.85;
}

BallSlots ball_slots(const cv::Mat& img){
    BallSlots out;
    if (!valid(img)){
        return out;
    }
    const int h = img.rows, w = img.cols;
    const int y = pyint(BALL_Y * h);
    const int r = std::max(static_cast<int>(std::nearbyint(BALL_R * w)), 3);
    const int top = std::max(y - r, 0);
    const int bot = std::min(y + r + 1, h);
    if (top >= bot){
        return out;
    }
    cv::Mat hsv;
    cv::cvtColor(img.rowRange(top, bot), hsv, cv::COLOR_BGR2HSV);
    for (int side = 0; side < 2; side++){
        Balls& balls = side == 0 ? out.me : out.foe;
        for (int i = 0; i < 3; i++){
            const int x = pyint(BALL_X[side][i] * w);
            const int xa = std::max(x - r, 0), xb = std::min(x + r + 1, w);
            long long total = 0, red = 0, dark = 0;
            for (int row = 0; row < hsv.rows; row++){
                const uchar* p = hsv.ptr<uchar>(row);
                for (int xx = xa; xx < xb; xx++){
                    const int hue = p[3 * xx], sat = p[3 * xx + 1], val = p[3 * xx + 2];
                    total++;
                    //  the red of a ball is a little orange (hue 7-9 of 180, saturation ~220, value ~240; under a
                    //  banner value ~180)
                    if ((hue <= 14 || hue >= 164) && sat >= 110 && val >= 120){
                        red++;
                    }
                    if (val < 125){
                        dark++;
                    }
                }
            }
            if (share(red, total) >= 0.25){
                balls.red++;
            }else if (share(dark, total) >= 0.45){      //  (val is the brightest channel: a grey ball is dark)
                balls.grey++;
            }
        }
    }
    return out;
}

bool hud_visible(const cv::Mat& img){
    if (!valid(img)){
        return false;
    }
    static const double SIDES[2][2] = {{0.03, 0.39}, {0.61, 0.97}};
    for (const auto& side : SIDES){
        const Win b = box(img, side[0], 0.115, side[1], 0.19);
        long long light = 0;
        for (int y = b.y0; y < b.y1; y++){
            const uchar* p = img.ptr<uchar>(y);
            for (int x = b.x0; x < b.x1; x++){
                const int mn = mn3(p + 3 * x), mx = mx3(p + 3 * x);
                //  (a box is dimmed while an attack is shown, and a video can be darker than a screenshot)
                if (mn > 140 && mx - mn < 60){
                    light++;
                }
            }
        }
        if (share(light, b.size()) <= 0.12){
            return false;
        }
    }
    const BallSlots balls = ball_slots(img);
    for (const Balls& side : {balls.me, balls.foe}){
        if (!(side.red >= 1 && side.red + side.grey >= 2)){
            return false;
        }
    }
    return true;
}

namespace{

//  Is the name of the move under a button written in bright white (see _label_text())?
bool label_text(const cv::Mat& img, double bx){
    const int h = img.rows, w = img.cols;
    const Win z = slice(img, pyint(LABEL_Y[0] * h), pyint(LABEL_Y[1] * h),
                        std::max(pyint((bx - LABEL_HALF) * w), 0), pyint((bx + LABEL_HALF) * w));
    const int rows = z.rows(), zw = z.cols();
    if (rows < 4 || zw < 16){
        return false;
    }
    std::vector<uchar> white(static_cast<size_t>(rows) * zw);
    for (int r = 0; r < rows; r++){
        const uchar* p = img.ptr<uchar>(z.y0 + r);
        for (int x = 0; x < zw; x++){
            white[static_cast<size_t>(r) * zw + x] = static_cast<uchar>(mn3(p + 3 * (z.x0 + x)) > 200 ? 1 : 0);
        }
    }
    const double short_run = 0.1 * zw;
    int best = 0, cur = 0, end = 0;
    for (int r = 0; r < rows; r++){
        const uchar* row = &white[static_cast<size_t>(r) * zw];
        int runs = 0, longest = 0, length = 0;
        for (int x = 0; x <= zw; x++){
            if (x < zw && row[x]){
                length++;
            }else if (length > 0){
                runs++;
                longest = std::max(longest, length);
                length = 0;
            }
        }
        cur = (runs >= LABEL_RUNS && static_cast<double>(longest) <= short_run) ? cur + 1 : 0;
        if (cur > best){
            best = cur;
            end = r;
        }
    }
    if (!(std::max(LABEL_ROWS[0] * h, 3.0) <= best && best <= LABEL_ROWS[1] * h)){
        return false;
    }
    const int first_row = end - best + 1;
    int c0 = -1, c1 = -1;
    for (int x = 0; x < zw; x++){
        bool any = false;
        for (int r = first_row; r <= end; r++){
            any = any || white[static_cast<size_t>(r) * zw + x];
        }
        if (any){
            if (c0 < 0){
                c0 = x;
            }
            c1 = x;
        }
    }
    if (c0 < 0){
        return false;
    }
    if (std::abs((c0 + c1) / 2.0 / zw - 0.5) > 0.15){
        return false;
    }
    long long ink = 0;
    for (int r = first_row; r <= end; r++){
        for (int x = c0; x <= c1; x++){
            ink += white[static_cast<size_t>(r) * zw + x];
        }
    }
    if (share(ink, static_cast<long long>(best) * (c1 - c0 + 1)) < LABEL_INK){
        return false;
    }
    //  (strokes that stand upright over the whole height of the band: U, R, F, T, B, L ...)
    int strokes = 0;
    bool before = false;
    for (int x = 0; x < zw; x++){
        int sum = 0;
        for (int r = first_row; r <= end; r++){
            sum += white[static_cast<size_t>(r) * zw + x];
        }
        const bool upright = static_cast<double>(sum) >= 0.7 * best;
        if (upright && !before){
            strokes++;
        }
        before = upright;
    }
    return strokes >= LABEL_STROKES;
}

}

std::pair<bool, bool> charge_ready(const cv::Mat& img){
    if (!valid(img)){
        return {false, false};
    }
    return {label_text(img, BTN_X[0]), label_text(img, BTN_X[1])};
}

bool get_ready(const cv::Mat& img){
    if (!valid(img)){
        return false;
    }
    const Win b = box(img, GET_READY_ZONE[0], GET_READY_ZONE[1], GET_READY_ZONE[2], GET_READY_ZONE[3]);
    if (b.size() == 0){
        return false;
    }
    cv::Mat small;
    cv::resize(img(cv::Range(b.y0, b.y1), cv::Range(b.x0, b.x1)), small, cv::Size(GET_READY_W, GET_READY_H), 0, 0,
               cv::INTER_AREA);
    std::vector<float> zone(static_cast<size_t>(GET_READY_W) * GET_READY_H);
    for (int y = 0; y < GET_READY_H; y++){
        const uchar* p = small.ptr<uchar>(y);
        for (int x = 0; x < GET_READY_W; x++){
            zone[static_cast<size_t>(y) * GET_READY_W + x] = static_cast<float>(mn3(p + 3 * x));
        }
    }
    std::vector<float> sorted = zone;
    std::sort(sorted.begin(), sorted.end());
    const size_t n = sorted.size();
    const double base = (static_cast<double>(sorted[n / 2 - 1]) + static_cast<double>(sorted[n / 2])) / 2.0;
    //  np.percentile(zone, 99): a straight line between the two numbers around place (n - 1) * 0.99, and the answer
    //  is a 32 bit number as the numbers are
    const double at = static_cast<double>(n - 1) * 0.99;
    const size_t below = static_cast<size_t>(std::floor(at));
    const double gamma = at - static_cast<double>(below);
    const double lo = sorted[below], hi = sorted[std::min(below + 1, n - 1)];
    double line = lo + (hi - lo) * gamma;
    if (gamma >= 0.5){
        line = hi - (hi - lo) * (1.0 - gamma);
    }
    const double top = static_cast<double>(static_cast<float>(line));
    if (top - base < 25){
        return false;                   //  (nothing bright on something darker)
    }
    //  (the picture is 32 bit numbers, so the number that it is compared with is, too)
    const float limit = static_cast<float>(base + 0.5 * (top - base));
    std::vector<char> text(zone.size());
    for (size_t i = 0; i < zone.size(); i++){
        text[i] = static_cast<char>(zone[i] > limit ? 1 : 0);
    }
    std::vector<char> want(zone.size());
    for (int y = 0; y < GET_READY_H; y++){
        for (int x = 0; x < GET_READY_W; x++){
            want[static_cast<size_t>(y) * GET_READY_W + x] = static_cast<char>(GET_READY[y][x] == '#' ? 1 : 0);
        }
    }
    double best = 0.0;
    for (int dy = -1; dy <= 1; dy++){           //  (a pixel of play: np.roll, round the edges)
        for (int dx = -1; dx <= 1; dx++){
            long long inter = 0, uni = 0;
            for (int y = 0; y < GET_READY_H; y++){
                const int sy = ((y - dy) % GET_READY_H + GET_READY_H) % GET_READY_H;
                for (int x = 0; x < GET_READY_W; x++){
                    const int sx = ((x - dx) % GET_READY_W + GET_READY_W) % GET_READY_W;
                    const char moved = text[static_cast<size_t>(sy) * GET_READY_W + sx];
                    const char wanted = want[static_cast<size_t>(y) * GET_READY_W + x];
                    inter += (moved && wanted) ? 1 : 0;
                    uni += (moved || wanted) ? 1 : 0;
                }
            }
            if (uni != 0){
                best = std::max(best, static_cast<double>(inter) / static_cast<double>(uni));
            }
        }
    }
    return best >= GET_READY_MATCH;
}

namespace{

//  How much of the last piece of the countdown's arc is on the picture (0..1).
double count_last(const cv::Mat& img, double cx, double cy, double r){
    const int h = img.rows, w = img.cols;
    const int N = 24;
    double ang[N];
    const double step = (COUNT_LAST[1] - COUNT_LAST[0]) / (N - 1);
    for (int i = 0; i < N; i++){
        const double deg = i == N - 1 ? COUNT_LAST[1] : static_cast<double>(i) * step + COUNT_LAST[0];
        ang[i] = deg * (3.14159265358979323846 / 180.0);
    }
    const double rings[5] = {r - 0.014, r - 0.004, r, r + 0.004, r + 0.012};
    const uchar* px[5][N];
    for (int k = 0; k < 5; k++){
        for (int i = 0; i < N; i++){
            const int xs = clip(static_cast<int>(std::nearbyint(cx * w + rings[k] * w * std::cos(ang[i]))), w - 1);
            const int ys = clip(static_cast<int>(std::nearbyint(cy * h + rings[k] * w * std::sin(ang[i]))), h - 1);
            px[k][i] = img.ptr<uchar>(ys) + 3 * xs;
        }
    }
    //  the line is white there and the disc on both sides of it is not
    long long count = 0;
    for (int i = 0; i < N; i++){
        const bool line = mn3(px[1][i]) > 215 || mn3(px[2][i]) > 215 || mn3(px[3][i]) > 215;
        const bool disc = mx3(px[0][i]) < 190 && mx3(px[4][i]) < 190;
        count += (line && disc) ? 1 : 0;
    }
    return static_cast<double>(count) / N;
}

}

QString countdown_kind(const cv::Mat& img){
    if (!valid(img)){
        return QString();
    }
    const int h = img.rows, w = img.cols;
    const int r = pyint(0.040 * w);
    static const char* const KINDS[2] = {"attack", "switch"};
    for (int k = 0; k < 2; k++){
        const double cx = COUNT_DISCS[k][0], cy = COUNT_DISCS[k][1], radius = COUNT_DISCS[k][2];
        const int x = pyint(cx * w), y = pyint(cy * h);
        const Win mid = slice(img, std::max(y - r, 0), y + r + 1, std::max(x - r, 0), x + r + 1);
        long long pale = 0, dark = 0;
        for (int yy = mid.y0; yy < mid.y1; yy++){
            const uchar* p = img.ptr<uchar>(yy);
            for (int xx = mid.x0; xx < mid.x1; xx++){
                pale += pale_px(p + 3 * xx) ? 1 : 0;
                dark += mx3(p + 3 * xx) < 190 ? 1 : 0;
            }
        }
        const double digit = share(pale, mid.size());                       //  the white number ...
        if (!(0.04 < digit && digit < 0.60)){
            continue;
        }
        if (share(dark, mid.size()) < 0.35){                                //  ... on the disc
            continue;
        }
        double last = 0.0;
        for (double d : {-0.003, 0.0, 0.003}){
            last = std::max(last, count_last(img, cx, cy, radius + d));
        }
        if (last >= 0.70){
            return QString::fromLatin1(KINDS[k]);
        }
    }
    return QString();
}

bool countdown_ring(const cv::Mat& img){
    return !countdown_kind(img).isEmpty();
}

cv::Mat name_key(const cv::Mat& img, bool me){
    if (!valid(img)){
        return cv::Mat();
    }
    const double x0 = me ? 0.035 : 0.615, x1 = me ? 0.385 : 0.965;
    const Win b = box(img, x0, 0.118, x1, 0.148);
    if (b.size() == 0){
        return cv::Mat();
    }
    cv::Mat ink(b.rows(), b.cols(), CV_8UC1);              //  the letters are dark on the pale box
    for (int y = 0; y < b.rows(); y++){
        const uchar* p = img.ptr<uchar>(b.y0 + y);
        uchar* q = ink.ptr<uchar>(y);
        for (int x = 0; x < b.cols(); x++){
            q[x] = static_cast<uchar>(mx3(p + 3 * (b.x0 + x)) < 150 ? 255 : 0);
        }
    }
    cv::Mat key;
    cv::resize(ink, key, cv::Size(40, 4), 0, 0, cv::INTER_AREA);
    return key;
}

bool key_differs(const cv::Mat& a, const cv::Mat& b){
    if (a.empty() || b.empty() || a.size() != b.size() || a.type() != CV_8UC1 || b.type() != CV_8UC1){
        return true;
    }
    long long sum = 0;
    for (int y = 0; y < a.rows; y++){
        const uchar* p = a.ptr<uchar>(y);
        const uchar* q = b.ptr<uchar>(y);
        for (int x = 0; x < a.cols; x++){
            sum += std::abs(static_cast<int>(p[x]) - static_cast<int>(q[x]));
        }
    }
    return static_cast<double>(sum) / static_cast<double>(a.total()) > KEY_DIFF;
}

bool shield_question(const cv::Mat& img){
    if (!valid(img)){
        return false;
    }
    const int h = img.rows, w = img.cols;
    const double cx = SHIELD_ICON[0] * w, cy = SHIELD_ICON[1] * h, r = 0.045 * w;
    const Win a = slice(img, pyint(cy - r), pyint(cy + r) + 1, pyint(cx - r), pyint(cx + r) + 1);
    if (a.size() == 0){
        return false;
    }
    cv::Mat hsv;
    cv::cvtColor(img(cv::Range(a.y0, a.y1), cv::Range(a.x0, a.x1)), hsv, cv::COLOR_BGR2HSV);
    long long inside = 0, lilac = 0;
    for (int y = 0; y < hsv.rows; y++){
        const uchar* p = hsv.ptr<uchar>(y);
        for (int x = 0; x < hsv.cols; x++){
            const double dx = (a.x0 + x) - cx, dy = (a.y0 + y) - cy;
            if (dx * dx + dy * dy <= r * r){
                inside++;
                const int hue = p[3 * x], sat = p[3 * x + 1], val = p[3 * x + 2];
                if (hue >= 130 && hue <= 170 && sat >= 25 && sat <= 150 && val >= 170){
                    lilac++;
                }
            }
        }
    }
    return share(lilac, inside) > 0.6;
}

ShieldSlots shield_icon_slots(const cv::Mat& img){
    ShieldSlots out;
    if (!valid(img)){
        return out;
    }
    const int h = img.rows, w = img.cols;
    const int y = pyint(SHIELD_SLOTS_Y * h), r = std::max(pyint(0.007 * w), 3);
    const int top = std::max(y - r, 0), bot = std::min(y + r + 1, h);
    if (top >= bot){
        return out;
    }
    cv::Mat hsv;
    cv::cvtColor(img.rowRange(top, bot), hsv, cv::COLOR_BGR2HSV);          //  (only the strip the icons are in)
    for (int side = 0; side < 2; side++){
        std::optional<int> n = 0;
        for (int i = 0; i < 2; i++){
            const int x = pyint(SHIELD_SLOTS[side][i] * w);
            const int ya = std::max(y - r - top, 0), yb = std::min(y + r + 1 - top, hsv.rows);
            const int xa = std::max(x - r, 0), xb = std::min(x + r + 1, w);
            std::vector<int> hue, sat, val;
            for (int yy = ya; yy < yb; yy++){
                const uchar* p = hsv.ptr<uchar>(yy);
                for (int xx = xa; xx < xb; xx++){
                    hue.push_back(p[3 * xx]);
                    sat.push_back(p[3 * xx + 1]);
                    val.push_back(p[3 * xx + 2]);
                }
            }
            if (hue.empty()){
                n.reset();
                break;
            }
            const double mh = median_of(hue), ms = median_of(sat), mv = median_of(val);
            if (125 <= mh && mh <= 155 && 45 <= ms && ms <= 120 && mv >= 200){          //  left: (140, 70-84, 240)
                n = *n + 1;
            }else if (!(125 <= mh && mh <= 155 && 50 <= ms && ms <= 115 && 105 <= mv && mv <= 140)){   //  used
                n.reset();                                                  //  neither: covered, or no name box
                break;
            }
        }
        (side == 0 ? out.me : out.foe) = n;
    }
    return out;
}

std::vector<HpBar> hp_bars(const cv::Mat& img){
    std::vector<HpBar> out;
    if (!valid(img)){
        return out;
    }
    const int h = img.rows, w = img.cols;
    const int top = pyint(0.20 * h), bot = std::min(pyint(0.62 * h), h);
    if (top >= bot){
        return out;
    }
    const cv::Mat reg = img.rowRange(top, bot);
    const int reg_h = reg.rows;
    cv::Mat hsv;
    cv::cvtColor(reg, hsv, cv::COLOR_BGR2HSV);
    cv::Mat green, yellow, red, red_high;
    cv::inRange(hsv, cv::Scalar(70, 151, 201), cv::Scalar(90, 255, 255), green);
    cv::inRange(hsv, cv::Scalar(22, 91, 221), cv::Scalar(34, 255, 255), yellow);
    cv::inRange(hsv, cv::Scalar(0, 111, 201), cv::Scalar(6, 255, 255), red);
    cv::inRange(hsv, cv::Scalar(170, 111, 201), cv::Scalar(180, 255, 255), red_high);
    cv::bitwise_or(red, red_high, red);
    cv::Mat colored, fill, closed;
    cv::bitwise_or(green, yellow, colored);
    cv::bitwise_or(colored, red, colored);
    cv::threshold(colored, fill, 0, 1, cv::THRESH_BINARY);
    cv::morphologyEx(fill, closed, cv::MORPH_CLOSE,
                     cv::getStructuringElement(cv::MORPH_RECT, cv::Size(std::max(3, w / 190), 1)));
    cv::Mat labels, stats, centroids;
    const int n = cv::connectedComponentsWithStats(closed, labels, stats, centroids, 8);
    const double full = BAR_FULL * w;
    for (int j = 1; j < n; j++){
        const int x = stats.at<int>(j, cv::CC_STAT_LEFT), y = stats.at<int>(j, cv::CC_STAT_TOP);
        const int bw = stats.at<int>(j, cv::CC_STAT_WIDTH), bh = stats.at<int>(j, cv::CC_STAT_HEIGHT);
        const int area = stats.at<int>(j, cv::CC_STAT_AREA);
        if (!(0.008 * h <= bh && bh <= 0.03 * h) || bw < 0.008 * w || bw > full * 1.08 || area < 0.6 * bw * bh){
            continue;
        }
        const int yc = y + bh / 2;
        if (top + yc > 0.55 * h){
            continue;                                   //  (small coloured things lower down are no bars)
        }
        //  the mean of the five rows round the middle of the bar
        const int ra = std::max(yc - 2, 0), rb = std::min(yc + 3, reg_h);
        const int nr = rb - ra;
        if (nr <= 0){
            continue;
        }
        const int l0 = std::max(x - pyint(0.009 * w), 0);
        const int l1 = std::min(std::max(x - pyint(0.001 * w), l0 + 1), w);
        bool pale_left = false;
        for (int xx = l0; xx < l1 && !pale_left; xx++){
            double m[3] = {0, 0, 0};
            for (int c = 0; c < 3; c++){
                long long sum = 0;
                for (int yy = ra; yy < rb; yy++){
                    sum += reg.ptr<uchar>(yy)[3 * xx + c];
                }
                m[c] = static_cast<double>(sum) / static_cast<double>(nr);
            }
            const double mn = std::min(std::min(m[0], m[1]), m[2]), mx = std::max(std::max(m[0], m[1]), m[2]);
            pale_left = mn > 150 && mx - mn < 90;
        }
        if (!pale_left){
            continue;                                   //  no pale frame on its left: not an HP bar
        }
        //  the right edge of the frame is there whatever the fill (a coloured blob of an attack is not a bar)
        const int r0 = std::min(pyint(x + full + 0.002 * w), w - 2);
        const int r1 = std::min(pyint(x + full + 0.008 * w), w - 1);
        const int sa = std::max(yc - pyint(0.005 * h), 0), sb = std::min(yc + pyint(0.005 * h) + 1, reg_h);
        const int ca = std::max(r0, 0), cb = std::min(std::max(r1, r0 + 1), w);
        if (cb <= ca){
            continue;
        }
        double edge_max = sb > sa ? 0.0 : std::nan("");
        for (int xx = ca; xx < cb; xx++){
            long long count = 0;
            for (int yy = sa; yy < sb; yy++){
                const uchar* p = reg.ptr<uchar>(yy) + 3 * xx;
                count += frame_px(mn3(p), mx3(p)) ? 1 : 0;
            }
            edge_max = std::max(edge_max, share(count, sb - sa));
        }
        if (edge_max < 0.6){
            continue;
        }
        //  ... and so are the lines of the frame above and below the part that is not filled
        const int e0 = pyint(x + bw + 0.012 * w), e1 = pyint(x + full - 0.004 * w);
        if (e1 - e0 >= std::max(0.02 * w, 6.0)){
            double lines[2];
            const int ys[2][2] = {{yc - pyint(0.012 * h), yc - pyint(0.003 * h)}, {yc + pyint(0.004 * h), yc + pyint(0.013 * h)}};
            for (int k = 0; k < 2; k++){
                const int ya = std::max(ys[k][0], 0), yb = std::min(std::max(ys[k][1], 1), reg_h);
                const int xa = std::max(e0, 0), xb = std::min(e1, w);
                double line = 0.0;
                if (yb > ya && xb > xa){
                    for (int yy = ya; yy < yb; yy++){
                        long long count = 0;
                        const uchar* p = reg.ptr<uchar>(yy);
                        for (int xx = xa; xx < xb; xx++){
                            count += frame_px(mn3(p + 3 * xx), mx3(p + 3 * xx)) ? 1 : 0;
                        }
                        line = std::max(line, share(count, xb - xa));
                    }
                }
                lines[k] = line;
            }
            if (std::min(lines[0], lines[1]) < 0.6){                //  (a bar in clear view: 0.96 and more)
                continue;
            }
        }
        const int cx = std::min(x + 1, w - 1);
        HpBar bar;
        bar.x0 = x;
        bar.frac = std::min(bw / full, 1.0);
        bar.color = green.at<uchar>(yc, cx) ? "green" : yellow.at<uchar>(yc, cx) ? "yellow" : "red";
        bar.y = top + yc;
        out.push_back(bar);
    }
    std::stable_sort(out.begin(), out.end(), [](const HpBar& a, const HpBar& b){ return a.x0 < b.x0; });
    return out;
}

Hp hp_of_sides(const cv::Mat& img){
    Hp out;
    if (!valid(img)){
        return out;
    }
    const int w = img.cols;
    for (const HpBar& b : hp_bars(img)){
        if (b.frac < 0.02){
            continue;
        }
        const double xf = b.x0 / static_cast<double>(w);
        if (xf < 0.30 && !out.me){
            out.me = b.frac;
        }else if (xf >= 0.40 && !out.foe){
            out.foe = b.frac;
        }
    }
    return out;
}

namespace{

double green_share(const cv::Mat& img, double x0, double y0, double x1, double y1){
    const Win b = box(img, x0, y0, x1, y1);
    if (b.size() == 0){
        return std::nan("");
    }
    cv::Mat hsv;
    cv::cvtColor(img(cv::Range(b.y0, b.y1), cv::Range(b.x0, b.x1)), hsv, cv::COLOR_BGR2HSV);
    long long count = 0;
    for (int y = 0; y < hsv.rows; y++){
        const uchar* p = hsv.ptr<uchar>(y);
        for (int x = 0; x < hsv.cols; x++){
            const int hue = p[3 * x], sat = p[3 * x + 1], val = p[3 * x + 2];
            count += (hue >= 65 && hue <= 95 && sat >= 70 && val >= 150) ? 1 : 0;
        }
    }
    return share(count, b.size());
}

}

bool result_button(const cv::Mat& img){
    if (!valid(img)){
        return false;
    }
    //  a quick look first (green where the button is, not green left and right of it: the grass of an arena by
    //  day and the map are green from edge to edge)
    if (green_share(img, 0.31, 0.845, 0.69, 0.885) <= 0.45){
        return false;
    }
    if (std::max(green_share(img, 0.05, 0.845, 0.22, 0.885), green_share(img, 0.78, 0.845, 0.95, 0.885)) >= 0.25){
        return false;
    }
    const double top = 0.70;
    for (const Button& b : wide_buttons(img, top)){
        if (b.color == "green" && b.y0 > top + 0.02 && b.x0 < TAP_NEXT[0] && TAP_NEXT[0] < b.x1
            && b.y0 < TAP_NEXT[1] && TAP_NEXT[1] < b.y1 && 0.25 <= b.x1 - b.x0 && b.x1 - b.x0 <= 0.50
            && 0.035 <= b.y1 - b.y0 && b.y1 - b.y0 <= 0.095){
            return true;
        }
    }
    return false;
}

bool done_button(const cv::Mat& img){
    if (!valid(img)){
        return false;
    }
    const int h = img.rows, w = img.cols;
    const double cx = TAP_DONE[0] * w, cy = TAP_DONE[1] * h, r = DONE_R * w;
    const int x0 = pyint(cx - 1.8 * r), y0 = pyint(cy - 1.8 * r);
    const int x1 = pyint(cx + 1.8 * r) + 1, y1 = std::min(pyint(cy + 1.8 * r) + 1, h);
    if (x0 < 0 || y0 < 0 || x1 > w || r < 6 || y1 <= y0 || x1 <= x0){
        return false;
    }
    cv::Mat hsv;
    cv::cvtColor(img(cv::Range(y0, y1), cv::Range(x0, x1)), hsv, cv::COLOR_BGR2HSV);
    const int rows = hsv.rows, cols = hsv.cols;
    std::vector<double> dist(static_cast<size_t>(rows) * cols), dxs(dist.size()), dys(dist.size());
    long long in_count = 0, in_teal = 0, around_count = 0, around_teal = 0;
    std::vector<int> centre;
    for (int y = 0; y < rows; y++){
        const uchar* p = hsv.ptr<uchar>(y);
        for (int x = 0; x < cols; x++){
            const double dx = ((x0 + x) - cx) / r, dy = ((y0 + y) - cy) / r;
            const double d = std::hypot(dx, dy);
            const size_t at = static_cast<size_t>(y) * cols + x;
            dist[at] = d;
            dxs[at] = dx;
            dys[at] = dy;
            const int hue = p[3 * x], sat = p[3 * x + 1], val = p[3 * x + 2];
            const bool teal = hue >= 84 && hue <= 104 && sat >= 110 && val >= 105;       //  the disc: about (93, 205, 148)
            if (d <= 0.85){
                in_count++;
                in_teal += teal ? 1 : 0;
            }
            if (d >= 1.2 && d <= 1.7){
                around_count++;
                around_teal += teal ? 1 : 0;
            }
            if (d <= 0.5){
                centre.push_back(val);
            }
        }
    }
    if (share(in_teal, in_count) < 0.85 || share(around_teal, around_count) > 0.12){
        return false;
    }
    if (centre.empty()){
        return false;
    }
    const int light_from = pyint(median_of(centre)) + 32;                   //  the drawing in it (about 240)
    double part[4];
    int i = 0;
    for (int sy : {-1, 1}){        //  the upper left, upper right, lower left, lower right
        for (int sx : {-1, 1}){
            long long count = 0, lit = 0;
            for (int y = 0; y < rows; y++){
                const uchar* p = hsv.ptr<uchar>(y);
                for (int x = 0; x < cols; x++){
                    const size_t at = static_cast<size_t>(y) * cols + x;
                    if (dist[at] <= 0.55 && sx * dxs[at] > 0.06 && sy * dys[at] > 0.06){
                        count++;
                        lit += p[3 * x + 2] >= light_from ? 1 : 0;
                    }
                }
            }
            part[i++] = count > 0 ? share(lit, count) : 0.0;
        }
    }
    const double ul = part[0], ur = part[1], ll = part[2], lr = part[3];
    const double stroke = std::min(ur, ll);
    return stroke >= 0.035 && ul <= 0.4 * stroke && lr <= 0.4 * stroke;
}


//  ---- the buttons of the screens around a fight ------------------------------------------------------------

namespace{

struct Run{
    int a;
    int b;
};

//  The stretches of True in a row (b is one past the end).
std::vector<Run> runs_of(const std::vector<uchar>& row){
    std::vector<Run> out;
    const int n = static_cast<int>(row.size());
    int start = -1;
    for (int x = 0; x <= n; x++){
        const bool on = x < n && row[x];
        if (on && start < 0){
            start = x;
        }else if (!on && start >= 0){
            out.push_back({start, x});
            start = -1;
        }
    }
    return out;
}

struct Block{
    int r0;
    int r1;
    int a;
    int b;
    std::vector<Run> all;
};

}

std::vector<Button> wide_buttons(const cv::Mat& img, double top){
    std::vector<Button> out;
    if (!valid(img)){
        return out;
    }
    const int h = img.rows, w = img.cols;
    const int y_top = pyint(top * h);
    if (y_top >= h){
        return out;
    }
    const int sw = 221;
    const double k = sw / static_cast<double>(w);
    const int sh = std::max(static_cast<int>(std::nearbyint((h - y_top) * k)), 1);
    cv::Mat small, hsv;
    cv::resize(img.rowRange(y_top, h), small, cv::Size(sw, sh), 0, 0, cv::INTER_AREA);
    cv::cvtColor(small, hsv, cv::COLOR_BGR2HSV);
    const double full_h = h * k;
    const int need = pyint(BUTTON_WIDE * sw);
    for (const ButtonColour& colour : BUTTON_COLOURS){
        std::vector<std::vector<uchar>> strict(sh, std::vector<uchar>(sw)), tint(sh, std::vector<uchar>(sw));
        for (int r = 0; r < sh; r++){
            const uchar* p = hsv.ptr<uchar>(r);
            for (int x = 0; x < sw; x++){
                const int hue = p[3 * x], sat = p[3 * x + 1], val = p[3 * x + 2];
                const bool in_hue = hue >= colour.hue0 && hue <= colour.hue1 && val >= colour.val_min;
                strict[r][x] = in_hue && sat >= colour.sat_min;
                tint[r][x] = in_hue && sat >= BUTTON_TINT;
            }
        }
        std::vector<std::optional<Run>> rows(sh);          //  per row: its widest stretch that looks like a button
        for (int r = 0; r < sh; r++){
            std::optional<Run> best;
            for (const Run& run : runs_of(tint[r])){
                if (run.b - run.a < need || !(run.a > 2) || !(run.b < sw - 2)){
                    continue;
                }
                long long hits = 0;
                for (int x = run.a; x < run.b; x++){
                    hits += strict[r][x];
                }
                bool head = false, tail = false;
                for (int x = run.a; x < run.a + 4; x++){
                    head = head || strict[r][x];
                }
                for (int x = run.b - 4; x < run.b; x++){
                    tail = tail || strict[r][x];
                }
                if (share(hits, run.b - run.a) >= 0.35 && head && tail){
                    if (!best || run.b - run.a > best->b - best->a){
                        best = run;
                    }
                }
            }
            rows[r] = best;
        }
        std::vector<Block> blocks;                          //  rows on top of each other that cover the same stretch
        for (int r = 0; r < sh; r++){
            if (!rows[r]){
                continue;
            }
            const Run run = *rows[r];
            if (!blocks.empty()){
                Block& last = blocks.back();
                if (r - last.r1 <= 2
                    && std::min(run.b, last.b) - std::max(run.a, last.a)
                        >= 0.6 * std::min(run.b - run.a, last.b - last.a)){
                    last.r1 = r;
                    last.all.push_back(run);
                    last.a = run.a;
                    last.b = run.b;
                    continue;
                }
            }
            blocks.push_back({r, r, run.a, run.b, {run}});
        }
        std::vector<Block> merged;                          //  the rows of the label can fall out: two blocks, one button
        for (const Block& blk : blocks){
            if (!merged.empty()){
                Block& last = merged.back();
                const int a = std::min(last.a, blk.a), b = std::max(last.b, blk.b);
                const int gap_rows = std::max(blk.r0 - (last.r1 + 1), 0);
                if (0 < gap_rows && gap_rows <= 0.04 * full_h){
                    long long on = 0;
                    for (int r = last.r1 + 1; r < blk.r0; r++){
                        for (int x = a; x < b; x++){
                            on += tint[r][x];
                        }
                    }
                    if (share(on, static_cast<long long>(gap_rows) * (b - a)) >= 0.5
                        && std::min(last.b, blk.b) - std::max(last.a, blk.a) >= 0.6 * (b - a)){
                        last.r1 = blk.r1;
                        last.all.insert(last.all.end(), blk.all.begin(), blk.all.end());
                        continue;
                    }
                }
            }
            merged.push_back(blk);
        }
        for (const Block& blk : merged){
            std::vector<int> starts, ends;
            for (const Run& run : blk.all){
                starts.push_back(run.a);
                ends.push_back(run.b);
            }
            const int x0 = pyint(median_of(starts)), x1 = pyint(median_of(ends));
            const int bh = blk.r1 - blk.r0 + 1, bw = x1 - x0;
            if (!(BUTTON_HIGH[0] * full_h <= bh && bh <= BUTTON_HIGH[1] * full_h) || bw < 2.2 * bh){
                continue;
            }
            Button button;
            button.color = QString::fromLatin1(colour.name);
            button.x0 = py_round3(x0 / static_cast<double>(sw));
            button.x1 = py_round3(x1 / static_cast<double>(sw));
            button.y0 = py_round3((y_top * k + blk.r0) / full_h);
            button.y1 = py_round3(std::min((y_top * k + blk.r1 + 1) / full_h, 1.0));
            out.push_back(button);
        }
    }
    std::stable_sort(out.begin(), out.end(), [](const Button& a, const Button& b){ return a.y1 > b.y1; });
    return out;
}

Spot button_spot(const Button& button, double side){
    return Spot{
        py_round3(button.x0 + side * (button.x1 - button.x0)),
        py_round3(std::min(button.y0 + 0.6 * (button.y1 - button.y0), 0.981)),     //  (not on the very edge)
    };
}

std::optional<Button> home_button(const cv::Mat& img){
    return home_button(wide_buttons(img, 0.45));
}

std::optional<Button> home_button(const std::vector<Button>& found){
    for (const Button& b : found){
        if (b.color == "orange"){
            return b;
        }
    }
    //  the TOPMOST green button, never a lower one (the second BATTLE button costs a pass)
    std::optional<Button> best;
    for (const Button& b : found){
        if (!best || b.y0 < best->y0){
            best = b;
        }
    }
    return best;
}

bool home_button_off(const cv::Mat& img){
    if (!valid(img)){
        return false;
    }
    const Win b = box(img, 0.32, 0.955, 0.68, 0.995);
    if (b.size() == 0){
        return false;
    }
    cv::Mat hsv;
    cv::cvtColor(img(cv::Range(b.y0, b.y1), cv::Range(b.x0, b.x1)), hsv, cv::COLOR_BGR2HSV);
    long long pale = 0, vivid = 0;
    for (int y = 0; y < hsv.rows; y++){
        const uchar* p = hsv.ptr<uchar>(y);
        for (int x = 0; x < hsv.cols; x++){
            const int hue = p[3 * x], sat = p[3 * x + 1], val = p[3 * x + 2];
            pale += (hue >= 70 && hue <= 100 && sat >= 15 && sat <= 75 && val >= 190) ? 1 : 0;
            vivid += (hue >= 45 && hue <= 100 && sat > 90) ? 1 : 0;
        }
    }
    return share(pale, b.size()) >= 0.6 && share(vivid, b.size()) < 0.2;
}

std::vector<Spot> gold_tiles(const cv::Mat& img){
    std::vector<Spot> out;
    if (!valid(img)){
        return out;
    }
    const int h = img.rows, w = img.cols;
    const int y0 = pyint(0.76 * h), y1 = std::min(pyint(0.95 * h), h);
    if (y0 >= y1){
        return out;
    }
    cv::Mat hsv;
    cv::cvtColor(img.rowRange(y0, y1), hsv, cv::COLOR_BGR2HSV);
    cv::Mat gold(hsv.rows, hsv.cols, CV_8UC1);
    for (int y = 0; y < hsv.rows; y++){
        const uchar* p = hsv.ptr<uchar>(y);
        uchar* q = gold.ptr<uchar>(y);
        for (int x = 0; x < hsv.cols; x++){
            const int hue = p[3 * x], sat = p[3 * x + 1], val = p[3 * x + 2];
            q[x] = static_cast<uchar>((hue >= 8 && hue <= 25 && sat >= 120 && val >= 200) ? 1 : 0);
        }
    }
    const int side = std::max(3, h / 60);
    cv::Mat closed;
    cv::morphologyEx(gold, closed, cv::MORPH_CLOSE, cv::Mat::ones(side, side, CV_8UC1));
    cv::Mat labels, stats, centroids;
    const int n = cv::connectedComponentsWithStats(closed, labels, stats, centroids, 8);
    for (int i = 1; i < n; i++){
        const int x = stats.at<int>(i, cv::CC_STAT_LEFT), y = stats.at<int>(i, cv::CC_STAT_TOP);
        const int bw = stats.at<int>(i, cv::CC_STAT_WIDTH), bh = stats.at<int>(i, cv::CC_STAT_HEIGHT);
        const int area = stats.at<int>(i, cv::CC_STAT_AREA);
        if (bw >= 0.08 * w && bh >= 0.05 * h && bw <= 0.22 * w && area >= 0.3 * bw * bh){
            out.push_back(Spot{py_round3((x + bw / 2.0) / w), py_round3((y0 + y + bh / 2.0) / h)});
        }
    }
    std::sort(out.begin(), out.end(), [](const Spot& a, const Spot& b){
        return a.x != b.x ? a.x < b.x : a.y < b.y;
    });
    return out;
}

int popup_tiles_shown(const cv::Mat& img){
    if (!valid(img)){
        return 1;
    }
    const int h = img.rows, w = img.cols;
    const int y0 = pyint(0.66 * h), y1 = std::min(pyint(0.80 * h), h);
    if (y0 >= y1){
        return 1;
    }
    cv::Mat gray;
    cv::cvtColor(img.rowRange(y0, y1), gray, cv::COLOR_BGR2GRAY);
    //  The standard deviation of every column, in 32 bit numbers, in the order that NumPy takes (the rows one after
    //  the other).
    const int rows = gray.rows;
    std::vector<float> cols(w);
    {
        std::vector<float> sum(w, 0.0f), mean(w), square(w, 0.0f);
        for (int y = 0; y < rows; y++){
            const uchar* p = gray.ptr<uchar>(y);
            for (int x = 0; x < w; x++){
                sum[x] += static_cast<float>(p[x]);
            }
        }
        for (int x = 0; x < w; x++){
            mean[x] = sum[x] / static_cast<float>(rows);
        }
        for (int y = 0; y < rows; y++){
            const uchar* p = gray.ptr<uchar>(y);
            for (int x = 0; x < w; x++){
                const float d = static_cast<float>(p[x]) - mean[x];
                const float sq = d * d;
                square[x] += sq;
            }
        }
        for (int x = 0; x < w; x++){
            cols[x] = std::sqrt(square[x] / static_cast<float>(rows));
        }
    }
    auto at = [&](double fx){
        const int x = pyint(fx * w), d = std::max(1, pyint(0.02 * w));
        const int a = std::max(0, x - d), b = std::min(x + d, w);
        if (b <= a){
            return std::nan("");
        }
        const float total = pairwise_sum(&cols[a], b - a);
        return static_cast<double>(total / static_cast<float>(b - a));
    };
    const double left = at(POPUP_TILES[0]), mid = at(0.50), right = at(POPUP_TILES[1]);
    const double low = std::min(left, right);
    return (low >= 25.0 && mid <= 0.35 * low) ? 2 : 1;
}

std::optional<Spot> exit_yes(const cv::Mat& img){
    for (const Button& b : wide_buttons(img, EXIT_YES_Y[0] - 0.04)){
        if (b.color == "green" && b.y0 >= EXIT_YES_Y[0] && b.y1 <= EXIT_YES_Y[1]
            && std::abs((b.x0 + b.x1) / 2.0 - 0.5) <= 0.10 && 0.20 <= b.x1 - b.x0 && b.x1 - b.x0 <= 0.75){
            return Spot{py_round3((b.x0 + b.x1) / 2.0), py_round3((b.y0 + b.y1) / 2.0)};
        }
    }
    return std::nullopt;
}


Seen features(const cv::Mat& img){
    Seen out;
    out.hud = hud_visible(img);
    out.hp = hp_of_sides(img);
    out.count = countdown_kind(img);
    out.white = is_white_screen(img);
    out.versus = is_versus(img);
    //  (the buttons only count with the HUD on the picture: a charged attack's zoom has bright sparks too)
    out.ready = out.hud ? charge_ready(img) : std::pair<bool, bool>(false, false);
    out.ring = !out.count.isEmpty();
    out.shields = shield_icon_slots(img);
    out.result = result_button(img);
    out.hex = shield_question(img);
    out.done = !out.hud && done_button(img);            //  (the check mark of a result screen without NEXT BATTLE)
    out.get_ready = out.hud && !out.ring && get_ready(img);
    if (out.hud){
        out.balls = ball_slots(img);                    //  (who can still fight: only with the name boxes)
    }
    return out;
}



//  ---- the test: the pictures of make_vision_golden.py --------------------------------------------------------------

namespace{

QJsonValue number_or_null(const std::optional<double>& v){
    return v ? QJsonValue(*v) : QJsonValue(QJsonValue::Null);
}
QJsonValue int_or_null(const std::optional<int>& v){
    return v ? QJsonValue(*v) : QJsonValue(QJsonValue::Null);
}
QJsonArray pair_json(bool a, bool b){
    return QJsonArray{a, b};
}
QJsonObject balls_json(const BallSlots& s){
    return QJsonObject{
        {"me", QJsonArray{s.me.red, s.me.grey}},
        {"foe", QJsonArray{s.foe.red, s.foe.grey}},
    };
}
QJsonObject shields_json(const ShieldSlots& s){
    return QJsonObject{{"me", int_or_null(s.me)}, {"foe", int_or_null(s.foe)}};
}
QJsonArray hp_json(const Hp& hp){
    return QJsonArray{number_or_null(hp.me), number_or_null(hp.foe)};
}
QJsonObject button_json(const Button& b){
    return QJsonObject{{"color", b.color}, {"x0", b.x0}, {"x1", b.x1}, {"y0", b.y0}, {"y1", b.y1}};
}
QJsonArray buttons_json(const std::vector<Button>& list){
    QJsonArray out;
    for (const Button& b : list){
        out.append(button_json(b));
    }
    return out;
}
QJsonArray spot_json(const Spot& s){
    return QJsonArray{s.x, s.y};
}
QString key_hex(const cv::Mat& key){
    if (key.empty()){
        return QString();
    }
    QByteArray bytes;
    for (int y = 0; y < key.rows; y++){
        bytes.append(reinterpret_cast<const char*>(key.ptr<uchar>(y)), key.cols);
    }
    return QString::fromLatin1(bytes.toHex());
}

//  What every reader says about a picture, in the form that make_vision_golden.py writes.
QJsonObject answers(const cv::Mat& img, const cv::Mat& ref_me, const cv::Mat& ref_foe){
    //  (features() holds hud, count, ring, hex, shields, hp and result: the rest are the readers that it leaves
    //  out, or only asks for with the HUD on the picture, so that every reader is asked about every picture)
    const Seen f = features(img);
    QJsonObject features_json{
        {"white", f.white}, {"versus", f.versus}, {"hud", f.hud},
        {"ready", pair_json(f.ready.first, f.ready.second)},
        {"ring", f.ring}, {"count", f.count}, {"shields", shields_json(f.shields)}, {"hp", hp_json(f.hp)},
        {"result", f.result}, {"hex", f.hex}, {"done", f.done}, {"get_ready", f.get_ready},
        {"balls", f.balls ? QJsonValue(balls_json(*f.balls)) : QJsonValue(QJsonValue::Null)},
    };
    const std::pair<bool, bool> ready = charge_ready(img);
    const std::vector<Button> wide = wide_buttons(img);
    const cv::Mat me = name_key(img, true), foe = name_key(img, false);
    QJsonArray bars;
    for (const HpBar& b : hp_bars(img)){
        bars.append(QJsonObject{{"x0", b.x0}, {"frac", b.frac}, {"color", b.color}, {"y", b.y}});
    }
    const std::optional<Button> home = home_button(wide);
    QJsonArray gold;
    for (const Spot& s : gold_tiles(img)){
        gold.append(spot_json(s));
    }
    const std::optional<Spot> exit_at = exit_yes(img);
    return QJsonObject{
        {"features", features_json},
        {"balls", balls_json(ball_slots(img))},
        {"ready", pair_json(ready.first, ready.second)},
        {"get_ready", get_ready(img)},
        {"bars", bars},
        {"done", done_button(img)},
        {"keys", QJsonObject{{"me", key_hex(me)}, {"foe", key_hex(foe)}}},
        {"differs", QJsonArray{key_differs(me, ref_me), key_differs(foe, ref_foe), key_differs(me, ref_foe),
                               key_differs(cv::Mat(), me), key_differs(foe, cv::Mat())}},
        {"wide", QJsonObject{{"0.45", buttons_json(wide)}, {"0.7", buttons_json(wide_buttons(img, 0.70))},
                             {"0.38", buttons_json(wide_buttons(img, 0.38))}}},
        {"home", home ? QJsonValue(button_json(*home)) : QJsonValue(QJsonValue::Null)},
        {"spot", home ? QJsonValue(spot_json(button_spot(*home))) : QJsonValue(QJsonValue::Null)},
        {"spot_q", home ? QJsonValue(spot_json(button_spot(*home, 0.25))) : QJsonValue(QJsonValue::Null)},
        {"off", home_button_off(img)},
        {"gold", gold},
        {"popup", popup_tiles_shown(img)},
        {"exit", exit_at ? QJsonValue(spot_json(*exit_at)) : QJsonValue(QJsonValue::Null)},
    };
}

//  The first place where two answers differ ("" when they do not).
QString first_difference(const QJsonValue& got, const QJsonValue& want, const QString& path){
    if (got.isDouble() && want.isDouble()){
        const double a = got.toDouble(), b = want.toDouble();
        return std::abs(a - b) <= 1e-9 + 1e-9 * std::abs(b) ? QString() : path;
    }
    if (got.type() != want.type()){
        return path;
    }
    if (got.isArray()){
        const QJsonArray a = got.toArray(), b = want.toArray();
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
        const QJsonObject a = got.toObject(), b = want.toObject();
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
                const std::vector<uchar> buffer(bytes.begin(), bytes.end());
                img = cv::imdecode(buffer, cv::IMREAD_COLOR);
            }
            it = m_loaded.insert(name, img);
        }
        return it.value();
    }

    //  The picture of a recipe: the steps that make_vision_golden.py takes (see run() there).
    bool make(const QJsonArray& ops, cv::Mat& img, QString& error){
        for (const QJsonValue& op_value : ops){
            const QJsonArray op = op_value.toArray();
            const QString kind = op.at(0).toString();
            if (kind == "load"){
                img = frame(op.at(1).toString()).clone();
                if (img.empty()){
                    error = "a frame is not there: " + op.at(1).toString();
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
            }else if (kind == "paste" || kind == "blend"){
                const cv::Mat& source = frame(op.at(1).toString());
                if (source.empty()){
                    error = "a frame is not there: " + op.at(1).toString();
                    return false;
                }
                cv::Mat other;
                cv::resize(source, other, img.size(), 0, 0, cv::INTER_LINEAR);
                if (kind == "paste"){
                    const int x0 = clip(op.at(2).toInt(), img.cols), y0 = clip(op.at(3).toInt(), img.rows);
                    const int x1 = clip(op.at(4).toInt(), img.cols), y1 = clip(op.at(5).toInt(), img.rows);
                    if (x1 > x0 && y1 > y0){
                        const cv::Rect area(x0, y0, x1 - x0, y1 - y0);
                        other(area).copyTo(img(area));
                    }
                }else{
                    const double part = op.at(2).toDouble();
                    cv::Mat out;
                    cv::addWeighted(img, 1.0 - part, other, part, 0.0, out);
                    img = out;
                }
            }else if (kind == "fill"){
                const int x0 = clip(op.at(1).toInt(), img.cols), y0 = clip(op.at(2).toInt(), img.rows);
                const int x1 = clip(op.at(3).toInt(), img.cols), y1 = clip(op.at(4).toInt(), img.rows);
                if (x1 > x0 && y1 > y0){
                    img(cv::Rect(x0, y0, x1 - x0, y1 - y0)) =
                        cv::Scalar(op.at(5).toInt(), op.at(6).toInt(), op.at(7).toInt());
                }
            }else if (kind == "disc"){
                cv::circle(img, cv::Point(op.at(1).toInt(), op.at(2).toInt()), op.at(3).toInt(),
                           cv::Scalar(op.at(4).toInt(), op.at(5).toInt(), op.at(6).toInt()), cv::FILLED);
            }else if (kind == "line"){
                cv::line(img, cv::Point(op.at(1).toInt(), op.at(2).toInt()), cv::Point(op.at(3).toInt(), op.at(4).toInt()),
                         cv::Scalar(op.at(5).toInt(), op.at(6).toInt(), op.at(7).toInt()), op.at(8).toInt());
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

}

int run_vision_checks(const QString& golden, const QString& fixtures, QStringList& report){
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the pictures of battle_vision.py are not there: " + golden;
        return 1;
    }
    const QByteArray json = qUncompress(file.readAll());
    const QJsonObject root = QJsonDocument::fromJson(json).object();
    const QJsonArray cases = root.value("cases").toArray();
    if (cases.isEmpty()){
        report << "FAILED: the file of pictures of battle_vision.py is empty or not right: " + golden;
        return 1;
    }
    Pictures pictures(fixtures);
    cv::Mat reference;
    {
        const cv::Mat& frame = pictures.frame("fight_ready.jpg");
        if (frame.empty()){
            report << "FAILED: the frames of the fights are not there: " + fixtures;
            return 1;
        }
        cv::resize(frame, reference, cv::Size(1768, 2208), 0, 0, cv::INTER_LINEAR);
    }
    const cv::Mat ref_me = name_key(reference, true), ref_foe = name_key(reference, false);

    int wrong = 0;
    for (qsizetype index = 0; index < cases.size(); index++){
        const QJsonObject one = cases[index].toObject();
        cv::Mat img;
        QString error;
        if (!pictures.make(one.value("ops").toArray(), img, error)){
            wrong++;
            report << QString("FAILED: picture %1: %2").arg(index).arg(error);
            continue;
        }
        const QJsonObject got = answers(img, ref_me, ref_foe);
        const QJsonObject want = one.value("a").toObject();
        const QString where = first_difference(got, want, QString());
        if (!where.isEmpty()){
            wrong++;
            if (wrong <= 12){
                report << QString("FAILED: picture %1 (%2): %3 differs: battle_vision.py says %4, the port says %5")
                    .arg(index)
                    .arg(compact(one.value("ops").toArray().at(0)).left(60))
                    .arg(where)
                    .arg(compact(at_path(want, where)).left(300))
                    .arg(compact(at_path(got, where)).left(300));
            }
        }
    }
    if (wrong == 0){
        report << QString("%1 pictures read as battle_vision.py reads them").arg(cases.size());
    }else{
        report << QString("%1 of %2 pictures are read differently from battle_vision.py").arg(wrong).arg(cases.size());
    }
    return wrong;
}


}
}
}
}
