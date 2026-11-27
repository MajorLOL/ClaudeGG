/*  Claude GG Pokemon GO Throw (what the throw of a ball looks at: the rings, the ball in the air, the buttons of the catch screen)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <initializer_list>
#include <tuple>
#include <opencv2/imgproc.hpp>
#include <QJsonArray>
#include <QJsonObject>
#include "ClaudeGG_PokemonGoThrow.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Throw{

namespace{

const double PI = 3.14159265358979323846;


//  ---- the arithmetic of numpy (the Python code does its sums with it; the port must come to the same numbers, to the last bit)

//  A product that is rounded before it is added to something (numpy multiplies and adds in two steps; a compiler may not make one
//  fused step of them).
inline float mul(float a, float b){
    volatile float r = a * b;
    return r;
}
inline double mul(double a, double b){
    volatile double r = a * b;
    return r;
}

//  numpy's sum of float64 numbers: in blocks of eight up to 128 numbers, above that in halves.
double pairwise_sum(const double* a, size_t n){
    if (n < 8){
        double res = 0.0;
        for (size_t i = 0; i < n; i++){
            res += a[i];
        }
        return res;
    }
    if (n <= 128){
        double r[8];
        for (size_t j = 0; j < 8; j++){
            r[j] = a[j];
        }
        size_t i = 8;
        for (; i < n - (n % 8); i += 8){
            for (size_t j = 0; j < 8; j++){
                r[j] += a[i + j];
            }
        }
        double res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
        for (; i < n; i++){
            res += a[i];
        }
        return res;
    }
    size_t half = n / 2;
    half -= half % 8;
    return pairwise_sum(a, half) + pairwise_sum(a + half, n - half);
}

//  The mean of numpy of float64 numbers.
double np_mean(const double* a, size_t n){
    return (0.0 + pairwise_sum(a, n)) / (double)n;
}

//  np.arange(start, stop, step) of floats: the first number is `start`, the second `start + step`, then `start + i * (second - start)`.
std::vector<double> np_arange(double start, double stop, double step){
    const size_t length = (size_t)std::ceil((stop - start) / step);
    std::vector<double> out(length);
    if (length > 0){
        out[0] = start;
    }
    if (length > 1){
        out[1] = start + step;
    }
    const double delta = length > 1 ? out[1] - start : 0.0;
    for (size_t i = 2; i < length; i++){
        out[i] = start + mul((double)i, delta);
    }
    return out;
}

//  a % 1.0 as numpy (and Python) does it: the result has the sign of the divisor.
double mod1(double a){
    double m = std::fmod(a, 1.0);
    if (m != 0.0){
        if (m < 0.0){
            m += 1.0;
        }
    }else{
        m = 0.0;
    }
    return m;
}

//  round(x, 2) of Python.
double round2(double x){
    return QString::number(x, 'f', 2).toDouble();
}


//  ---- the rings

//  The strong colour edges of the crop: places and unit directions of the gradient (_edge_points).
struct Edges{
    std::vector<float> xs, ys, ux, uy;
};

Edges edge_points(const cv::Mat& crop){
    cv::Mat blurred;
    cv::GaussianBlur(crop, blurred, cv::Size(0, 0), 1.2);
    cv::Mat f;
    blurred.convertTo(f, CV_32F);
    cv::Mat gx, gy;
    cv::Sobel(f, gx, CV_32F, 1, 0, 3);
    cv::Sobel(f, gy, CV_32F, 0, 1, 3);
    const int rows = f.rows;
    const int cols = f.cols;
    //  per pixel: the colour channel with the strongest edge
    std::vector<float> mag((size_t)rows * (size_t)cols);
    std::vector<float> sx(mag.size());
    std::vector<float> sy(mag.size());
    for (int y = 0; y < rows; y++){
        const float* px = gx.ptr<float>(y);
        const float* py = gy.ptr<float>(y);
        for (int x = 0; x < cols; x++){
            int best = 0;
            float best_mag = 0.0f;
            for (int c = 0; c < 3; c++){
                const float a = px[3 * x + c];
                const float b = py[3 * x + c];
                const float m = std::sqrt(a * a + b * b);
                if (c == 0 || m > best_mag){
                    best = c;
                    best_mag = m;
                }
            }
            const size_t at = (size_t)y * (size_t)cols + (size_t)x;
            mag[at] = best_mag;
            sx[at] = px[3 * x + best];
            sy[at] = py[3 * x + best];
        }
    }
    const double thr = std::max((double)percentile80(mag), 18.0);
    const float thr_f = (float)thr;
    Edges out;
    for (int y = 0; y < rows; y++){
        for (int x = 0; x < cols; x++){
            const size_t at = (size_t)y * (size_t)cols + (size_t)x;
            if (mag[at] > thr_f){
                out.xs.push_back((float)x);
                out.ys.push_back((float)y);
                out.ux.push_back(sx[at] / mag[at]);
                out.uy.push_back(sy[at] / mag[at]);
            }
        }
    }
    return out;
}

constexpr int N_THETA = 72;

//  Per radius: the share of directions with an edge that runs along a circle around (cx, cy) (_circle_profile).
std::vector<double> circle_profile(const Edges& pts, int cx, int cy, int rmax, int band){
    const int rows = rmax + 1;
    cv::Mat hit = cv::Mat::zeros(rows, N_THETA, CV_8U);
    const float fcx = (float)cx;
    const float fcy = (float)cy;
    const float frmax = (float)rmax;
    const float eps = 1e-6f;
    const float pi = (float)PI;
    const float two_pi = (float)(2 * PI);
    for (size_t i = 0; i < pts.xs.size(); i++){
        const float dx = pts.xs[i] - fcx;
        const float dy = pts.ys[i] - fcy;
        const float r = std::sqrt(dx * dx + dy * dy) + eps;
        if (!(r < frmax)){
            continue;
        }
        const float along = std::fabs((mul(dx, pts.ux[i]) + mul(dy, pts.uy[i])) / r);
        if (!(along > 0.85f)){
            continue;
        }
        const int ri = (int)r;
        const float angle = (float)std::atan2((double)dy, (double)dx);
        const float t = (angle + pi) / two_pi * (float)N_THETA;
        const int ti = (int)t % N_THETA;
        hit.at<uchar>(ri, ti) = 1;
    }
    if (band){
        cv::Mat wide;
        cv::dilate(hit, wide, cv::Mat::ones(2 * band + 1, 1, CV_8U));
        hit = wide;
    }
    std::vector<double> prof((size_t)rows);
    for (int r = 0; r < rows; r++){
        int count = 0;
        for (int t = 0; t < N_THETA; t++){
            count += hit.at<uchar>(r, t);
        }
        prof[(size_t)r] = (double)count / (double)N_THETA;
    }
    return prof;
}

//  Pixels with the bright, saturated colour of the shrinking ring (green, yellow, orange, red).
cv::Mat ring_colour_mask(const cv::Mat& crop){
    cv::Mat hsv;
    cv::cvtColor(crop, hsv, cv::COLOR_BGR2HSV);
    cv::Mat mask(hsv.rows, hsv.cols, CV_8U);
    for (int y = 0; y < hsv.rows; y++){
        const cv::Vec3b* row = hsv.ptr<cv::Vec3b>(y);
        uchar* out = mask.ptr<uchar>(y);
        for (int x = 0; x < hsv.cols; x++){
            const int h = row[x][0];
            const int s = row[x][1];
            const int v = row[x][2];
            out[x] = (((h <= 82) || (h >= 170)) && s > 95 && v > 165) ? 1 : 0;
        }
    }
    return mask;
}

//  Per radius: the share of directions in which the mask is set (within +-band px) (_polar_cov).
std::vector<double> polar_cov(const cv::Mat& mask, int cx, int cy, double rmax, int band){
    const int n_theta = 120;
    cv::Mat polar;
    cv::warpPolar(mask, polar, cv::Size((int)rmax, n_theta), cv::Point2f((float)cx, (float)cy), rmax,
                  (int)cv::WARP_POLAR_LINEAR | (int)cv::INTER_NEAREST | (int)cv::WARP_FILL_OUTLIERS);
    if (band){
        cv::Mat wide;
        cv::dilate(polar, wide, cv::Mat::ones(1, 2 * band + 1, CV_8U));
        polar = wide;
    }
    std::vector<double> cov((size_t)polar.cols);
    for (int r = 0; r < polar.cols; r++){
        int count = 0;
        for (int t = 0; t < polar.rows; t++){
            count += polar.at<uchar>(t, r);
        }
        cov[(size_t)r] = (double)count / (double)polar.rows;
    }
    return cov;
}

struct ColourFit{
    double score = 0.0;
    bool found = false;
    double radius = 0.0;
};

//  The coloured ring around (cx, cy): a thin circle that is coloured (almost) all the way round while it is not coloured just inside and
//  just outside it (_colour_ring).
ColourFit colour_ring(const cv::Mat& mask, int cx, int cy, double rmax, double r_lo){
    const std::vector<double> cov = polar_cov(mask, cx, cy, rmax, 2);
    const int len = (int)cov.size();
    double best_score = 0.0;
    int best_r = -1;
    for (int r = (int)r_lo; r < len - 1; r++){
        if (cov[(size_t)r] < 0.7){
            continue;
        }
        const int g = std::max((int)(r * 0.12), 10);
        const int i0 = std::max(r - 2 * g, 0);
        const int i1 = std::max(r - g, 1);
        const int o0 = std::min(r + g, len - 1);
        const int o1 = std::min(r + 2 * g, len);
        const double inner = np_mean(cov.data() + i0, (size_t)(i1 - i0));
        const double outer = np_mean(cov.data() + o0, (size_t)(o1 - o0));
        const double score = cov[(size_t)r] - (outer > inner ? outer : inner);
        if (score > best_score){
            best_score = score;
            best_r = r;
        }
    }
    ColourFit out;
    if (best_r < 0){
        return out;
    }
    const int r = best_r;                           //  middle of the line
    int a = r;
    int b = r;
    while (a - 1 > 0 && cov[(size_t)(a - 1)] >= 0.6 * cov[(size_t)r]){
        a--;
    }
    while (b + 1 < len && cov[(size_t)(b + 1)] >= 0.6 * cov[(size_t)r]){
        b++;
    }
    if (b - a > RING_LINE_MAX){                     //  too thick for the ring line: part of the Pokémon
        return out;
    }
    out.score = best_score;
    out.found = true;
    out.radius = (double)(a + b) / 2.0;
    return out;
}

struct WhiteFit{
    double score;
    int r;
    int cx;
    int cy;
};

//  (Python compares these as tuples.)
bool better(const WhiteFit& a, const WhiteFit& b){
    if (a.score != b.score){
        return a.score > b.score;
    }
    if (a.r != b.r){
        return a.r > b.r;
    }
    if (a.cx != b.cx){
        return a.cx > b.cx;
    }
    return a.cy > b.cy;
}

}


//  np.percentile(values, 80) of float32 numbers (the method 'linear'; numpy does it all in float32 for these).
float percentile80(std::vector<float> values){
    const size_t n = values.size();
    const float q = 0.8f;
    const float virt = (float)(n - 1) * q;
    const float prev_f = std::floor(virt);
    const size_t prev = (size_t)prev_f;
    const size_t next = std::min(prev + 1, n - 1);
    std::nth_element(values.begin(), values.begin() + (std::ptrdiff_t)prev, values.end());
    const float x = values[prev];
    float y = x;
    if (next != prev){
        y = *std::min_element(values.begin() + (std::ptrdiff_t)next, values.end());
    }
    const float g = (float)((double)virt - (double)prev_f);
    const float d = y - x;
    if (g >= 0.5f){
        return y - mul(d, 1.0f - g);
    }
    return x + mul(d, g);
}


std::optional<Ring> measure_ring(const cv::Mat& img, const Detection& box, RingDiag* diag){
    if (diag){
        *diag = RingDiag();
    }
    const int bx = box.cx;
    const int by = box.cy;
    const double r0 = std::max(box.w, box.h) / 2.0;
    if (r0 < 40){
        return std::nullopt;
    }
    const int pad = (int)(r0 * 1.5);
    const int x0 = std::max(bx - pad, 0);
    const int y0 = std::max(by - pad, 0);
    const int x1 = std::min(bx + pad, img.cols);
    const int y1 = std::min(by + pad, img.rows);
    if (y1 - y0 < 80 || x1 - x0 < 80){
        return std::nullopt;
    }
    //  (a copy: the filters must not look outside the crop at the rest of the picture)
    const cv::Mat crop = img(cv::Rect(x0, y0, x1 - x0, y1 - y0)).clone();

    //  1. the white ring (edges on a circle about as big as the box): the middle and the radius
    Edges all = edge_points(crop);
    const int rmax = (int)(r0 * 1.3);
    const int band = std::max((int)(r0 * 0.02), 2);
    const int step = std::max((int)(r0 * 0.03), 2);
    const int lo = (int)(r0 * 0.78);
    const int hi = (int)(r0 * 1.12);
    //  only edges that can belong to that ring, and not more than needed (speed on the Pi)
    std::vector<size_t> keep;
    {
        const float fx = (float)(bx - x0);
        const float fy = (float)(by - y0);
        const float near_d = (float)(r0 * 0.6);
        const float far_d = (float)(r0 * 1.3);
        for (size_t i = 0; i < all.xs.size(); i++){
            const float dx = all.xs[i] - fx;
            const float dy = all.ys[i] - fy;
            const float dist = (float)std::sqrt((double)dx * (double)dx + (double)dy * (double)dy);
            if (dist > near_d && dist < far_d){
                keep.push_back(i);
            }
        }
    }
    if (keep.size() > 9000){
        const size_t every = keep.size() / 9000 + 1;
        std::vector<size_t> fewer;
        for (size_t i = 0; i < keep.size(); i += every){
            fewer.push_back(keep[i]);
        }
        keep.swap(fewer);
    }
    Edges pts;
    for (size_t i : keep){
        pts.xs.push_back(all.xs[i]);
        pts.ys.push_back(all.ys[i]);
        pts.ux.push_back(all.ux[i]);
        pts.uy.push_back(all.uy[i]);
    }

    auto white_fit = [&](int cx, int cy){
        const std::vector<double> prof = circle_profile(pts, cx, cy, rmax, band);
        double top = prof[(size_t)lo];
        for (int r = lo; r < hi; r++){
            top = std::max(top, prof[(size_t)r]);
        }
        int outer = lo;
        for (int r = lo; r < hi; r++){
            if (prof[(size_t)r] >= 0.85 * top){
                outer = r;                                  //  the outermost circle
            }
        }
        return WhiteFit{prof[(size_t)outer], outer, cx, cy};
    };

    WhiteFit best{0.0, 0, 0, 0};
    bool first = true;
    for (int dx = -2; dx <= 2; dx++){                       //  coarse ...
        for (int dy = -2; dy <= 2; dy++){
            const WhiteFit one = white_fit(bx - x0 + dx * 2 * step, by - y0 + dy * 2 * step);
            if (first || better(one, best)){
                best = one;
                first = false;
            }
        }
    }
    {
        const WhiteFit centre = best;
        first = true;
        for (int dx = -1; dx <= 1; dx++){                   //  ... then fine
            for (int dy = -1; dy <= 1; dy++){
                const WhiteFit one = white_fit(centre.cx + dx * step, centre.cy + dy * step);
                if (first || better(one, best)){
                    best = one;
                    first = false;
                }
            }
        }
    }
    if (diag){
        diag->white = round2(best.score);
    }
    if (best.score < 0.6){
        return std::nullopt;
    }
    const int rw = best.r;
    const int cx = best.cx;
    const int cy = best.cy;

    //  2. the coloured ring: same middle (fine-tuned), anywhere from tiny to the white ring
    const cv::Mat mask = ring_colour_mask(crop);
    double best_score = 0.0;
    bool best_found = false;
    double best_radius = 0.0;
    int best_cx = cx;
    int best_cy = cy;
    const int spans[2][2] = {{2, 7}, {1, 3}};
    for (const auto& span : spans){                         //  coarse search, then fine around the best
        const int ox = best_cx;
        const int oy = best_cy;
        for (int dx = -span[0]; dx <= span[0]; dx++){
            for (int dy = -span[0]; dy <= span[0]; dy++){
                const ColourFit one = colour_ring(mask, ox + dx * span[1], oy + dy * span[1], rw * 1.15, std::max(rw * 0.04, 5.0));
                if (one.found && one.score > best_score){
                    best_score = one.score;
                    best_found = true;
                    best_radius = one.radius;
                    best_cx = ox + dx * span[1];
                    best_cy = oy + dy * span[1];
                }
            }
        }
    }
    if (diag){
        diag->colour = round2(best_score);
        if (best_found){
            diag->size = round2(best_radius / rw);
        }
        diag->has_size = true;
    }
    if (!best_found || best_score < 0.6){
        return std::nullopt;
    }
    Ring ring;
    ring.ratio = std::min(best_radius / rw, 1.0);
    ring.rw = rw;
    ring.rc = (int)best_radius;
    ring.cx = best_cx + x0;
    ring.cy = best_cy + y0;
    ring.q = round2(best_score);
    return ring;
}


//  ---- the ball in the air

std::optional<Ball> find_ball(const cv::Mat& img, const cv::Mat& before){
    auto red = [](const cv::Mat& im){
        cv::Mat hsv;
        cv::cvtColor(im.rowRange(0, 1560), hsv, cv::COLOR_BGR2HSV);
        cv::Mat out(hsv.rows, hsv.cols, CV_8U);
        for (int y = 0; y < hsv.rows; y++){
            const cv::Vec3b* row = hsv.ptr<cv::Vec3b>(y);
            uchar* o = out.ptr<uchar>(y);
            for (int x = 0; x < hsv.cols; x++){
                o[x] = ((row[x][0] < 8 || row[x][0] > 172) && row[x][1] > 150 && row[x][2] > 110) ? 1 : 0;
            }
        }
        return out;
    };
    const cv::Mat now = red(img);
    cv::Mat old;
    cv::dilate(red(before), old, cv::Mat::ones(41, 41, CV_8U));
    cv::Mat m(now.rows, now.cols, CV_8U);
    for (int y = 0; y < now.rows; y++){
        for (int x = 0; x < now.cols; x++){
            m.at<uchar>(y, x) = (now.at<uchar>(y, x) != 0 && old.at<uchar>(y, x) == 0) ? 1 : 0;
        }
    }
    cv::Mat opened;
    cv::morphologyEx(m, opened, cv::MORPH_OPEN, cv::Mat::ones(7, 7, CV_8U));
    cv::Mat labels, stats, centroids;
    const int n = cv::connectedComponentsWithStats(opened, labels, stats, centroids);
    std::optional<Ball> best;
    for (int i = 1; i < n; i++){
        const int area = stats.at<int>(i, cv::CC_STAT_AREA);
        const int w = stats.at<int>(i, cv::CC_STAT_WIDTH);
        const int h = stats.at<int>(i, cv::CC_STAT_HEIGHT);
        const double aspect = (double)w / (double)std::max(h, 1);
        if (!(700 <= area && area <= 26000 && stats.at<int>(i, cv::CC_STAT_TOP) > 150 && 0.5 < aspect && aspect < 2.2)){
            continue;
        }
        Ball ball;
        ball.area = area;
        ball.x = (int)centroids.at<double>(i, 0);
        ball.y = (int)centroids.at<double>(i, 1);
        //  (the biggest; of the same size the one with the greater x, then the greater y)
        if (!best.has_value() || std::make_tuple(ball.area, ball.x, ball.y) > std::make_tuple(best->area, best->x, best->y)){
            best = ball;
        }
    }
    return best;
}

std::optional<int> landing_x(const std::vector<cv::Mat>& imgs, const cv::Mat& before, const Detection* ring){
    if (ring == nullptr){
        return std::nullopt;
    }
    const double want_y = ring->cy - 0.4 * ring->h;         //  the ball comes down onto the Pokémon from above
    std::optional<int> land;
    double land_gap = 0.0;
    for (const cv::Mat& im : imgs){
        const std::optional<Ball> ball = find_ball(im, before);
        if (!ball.has_value()){
            continue;
        }
        const double gap = std::fabs(ball->y - want_y);
        if (gap < 380 && (!land.has_value() || gap < land_gap)){
            land = ball->x;
            land_gap = gap;
        }
    }
    return land;
}


//  ---- the catch screen

bool enc_buttons(const cv::Mat& img){
    //  the disc is ~122 px in radius
    bool inside[330][330];
    bool outside[330][330];
    int n_ring = 0;
    int n_out = 0;
    for (int y = -165; y < 165; y++){
        for (int x = -165; x < 165; x++){
            const double r = std::sqrt((double)(x * x + y * y));
            inside[y + 165][x + 165] = r > 88 && r < 112;
            outside[y + 165][x + 165] = r > 140 && r < 162;
            n_ring += inside[y + 165][x + 165] ? 1 : 0;
            n_out += outside[y + 165][x + 165] ? 1 : 0;
        }
    }
    for (const Point& at : {ENC_BERRY_BTN, ENC_BALL_BTN}){
        cv::Mat hsv;
        cv::cvtColor(img(cv::Rect(at.x - 165, at.y - 165, 330, 330)), hsv, cv::COLOR_BGR2HSV);
        int light_ring = 0;
        int light_out = 0;
        for (int y = 0; y < 330; y++){
            const cv::Vec3b* row = hsv.ptr<cv::Vec3b>(y);
            for (int x = 0; x < 330; x++){
                if (row[x][1] < 45 && row[x][2] > 150){
                    light_ring += inside[y][x] ? 1 : 0;
                    light_out += outside[y][x] ? 1 : 0;
                }
            }
        }
        //  a light disc on a darker scene
        if ((double)light_ring / (double)n_ring < 0.4 || (double)light_out / (double)n_out > 0.3){
            return false;
        }
    }
    return true;
}

namespace{
bool is_red(const cv::Vec3b& px){
    const int b = px[0];
    const int g = px[1];
    const int r = px[2];
    return r > 120 && r > 2 * std::max(g, b);
}
}

bool in_encounter(const cv::Mat& img){
    return !Loop::map_visible(img) && is_red(img.at<cv::Vec3b>(1870, 877)) && is_red(img.at<cv::Vec3b>(1960, 877));
}

bool ball_ready(const cv::Mat& img){
    return in_encounter(img) || enc_buttons(img);
}

std::optional<Point> result_ok_button(const cv::Mat& img){
    const int y0 = 1500;
    cv::Mat hsv;
    cv::cvtColor(img.rowRange(y0, 2150), hsv, cv::COLOR_BGR2HSV);
    cv::Mat m(hsv.rows, hsv.cols, CV_8U);
    for (int y = 0; y < hsv.rows; y++){
        const cv::Vec3b* row = hsv.ptr<cv::Vec3b>(y);
        uchar* o = m.ptr<uchar>(y);
        for (int x = 0; x < hsv.cols; x++){
            const int h = row[x][0];
            const int s = row[x][1];
            const int v = row[x][2];
            o[x] = (h >= 80 && h <= 100 && s >= 70 && s <= 210 && v >= 110 && v <= 235) ? 1 : 0;
        }
    }
    cv::Mat opened, closed;
    cv::morphologyEx(m, opened, cv::MORPH_OPEN, cv::Mat::ones(7, 7, CV_8U));
    cv::morphologyEx(opened, closed, cv::MORPH_CLOSE, cv::Mat::ones(25, 25, CV_8U));
    cv::Mat labels, stats, centroids;
    const int n = cv::connectedComponentsWithStats(closed, labels, stats, centroids);
    bool have = false;
    int best_area = 0;
    Point best;
    for (int i = 1; i < n; i++){
        const int x = stats.at<int>(i, cv::CC_STAT_LEFT);
        const int y = stats.at<int>(i, cv::CC_STAT_TOP);
        const int w = stats.at<int>(i, cv::CC_STAT_WIDTH);
        const int h = stats.at<int>(i, cv::CC_STAT_HEIGHT);
        const int a = stats.at<int>(i, cv::CC_STAT_AREA);
        if (600 < w && w < 1200 && 110 < h && h < 330 && w > 2.5 * h && std::abs(x + w / 2 - 884) < 160
            && a > 0.6 * w * h && (!have || a > best_area)){
            have = true;
            best_area = a;
            best = Point{x + w / 2, y + h / 2 + y0};
        }
    }
    if (!have){
        return std::nullopt;
    }
    return best;
}


//  ---- what is learned from the throws

std::optional<double> ring_speed(const std::vector<std::pair<double, double>>& points){
    std::vector<double> steps;
    for (size_t i = 1; i < points.size(); i++){
        const double t0 = points[i - 1].first;
        const double r0 = points[i - 1].second;
        const double t1 = points[i].first;
        const double r1 = points[i].second;
        if (t1 - t0 >= 0.05 && 0 < r0 - r1 && r0 - r1 < 0.6){
            steps.push_back((r0 - r1) / (t1 - t0));
        }
    }
    if (steps.size() < 2){
        return std::nullopt;
    }
    std::sort(steps.begin(), steps.end());
    const size_t mid = steps.size() / 2;
    const double k = steps.size() % 2 == 1 ? steps[mid] : (steps[mid - 1] + steps[mid]) / 2.0;
    if (0.25 <= k && k <= 1.0){
        return k;
    }
    return std::nullopt;
}

void refit_timing(Cal& cal, bool live){
    const std::vector<std::array<double, 3>>& all = live ? cal.obs_live : cal.obs;
    const size_t from = all.size() > 16 ? all.size() - 16 : 0;
    const size_t n = all.size() - from;
    if (n == 0){
        return;
    }
    std::vector<double> r(n), t(n), g(n);
    for (size_t i = 0; i < n; i++){
        r[i] = all[from + i][0];
        t[i] = all[from + i][1];
        g[i] = all[from + i][2];
    }
    const double spread = *std::max_element(t.begin(), t.end()) - *std::min_element(t.begin(), t.end());
    const std::vector<double> ks = (n >= 6 && spread >= 0.6) ? np_arange(0.35, 0.801, 0.01) : std::vector<double>{cal.k};
    const std::vector<double> cs = np_arange(-0.3, 1.21, 0.02);
    const size_t keep = std::max((size_t)((double)n * 0.75), (size_t)1);        //  ignore the worst quarter (e.g. an attack froze the ring)
    bool have = false;
    double best_cost = 0.0;
    double best_k = 0.0;
    double best_c = 0.0;
    std::vector<double> res(n);
    for (double k : ks){
        size_t at = 0;
        double at_cost = 0.0;
        for (size_t ci = 0; ci < cs.size(); ci++){
            for (size_t j = 0; j < n; j++){
                const double pred = mod1(r[j] - mul(k, t[j] - cs[ci]));
                res[j] = std::fabs(mod1(g[j] - pred + 0.5) - 0.5);
            }
            std::sort(res.begin(), res.end());
            const double cost = np_mean(res.data(), keep);
            if (ci == 0 || cost < at_cost){
                at = ci;
                at_cost = cost;
            }
        }
        if (!have || at_cost < best_cost){
            have = true;
            best_cost = at_cost;
            best_k = k;
            best_c = cs[at];
        }
    }
    cal.k = best_k;
    (live ? cal.c_live : cal.c) = best_c;
}


//  ---- the curveball

int curve_lean(const Cal& cal, std::optional<int> target_x){
    const int middle = Loop::REF_W / 2;
    const int t = (target_x.has_value() ? *target_x : middle) - middle;
    const double lean = ((double)(t - CURVE_LAND) - cal.aim) / CURVE_LEAN_GAIN;
    return (int)std::min(std::max(lean, (double)-CURVE_LEAN_MAX), (double)CURVE_LEAN_MAX);
}

std::vector<Point> spin_points(){
    const int cx = Loop::REF_W / 2 - CURVE_D + CURVE_RADIUS;
    const int cy = std::min(BALL_XY.y - 60, Loop::REF_H - CURVE_RADIUS - 60);
    const int n = (int)std::lround(CURVE_SPINS * 8);        //  8 points per circle
    std::vector<Point> out;
    for (int i = 0; i <= n; i++){
        const double angle = i * PI / 4;
        out.push_back(Point{(int)(cx + mul((double)CURVE_RADIUS, std::cos(angle))), (int)(cy + mul((double)CURVE_RADIUS, std::sin(angle)))});
    }
    return out;
}

QString aim_note(int aim_dx, int ring_w){
    const QString side = aim_dx > 0 ? "right" : "left";
    if (std::abs(aim_dx) > HIT_SHARE * ring_w){
        return QString("aim %1 px %2 of the Pokémon on purpose - MEANT TO MISS").arg(std::abs(aim_dx)).arg(side);
    }
    if (std::abs(aim_dx) < 8){
        return "aimed at the middle";
    }
    return QString("aim %1 px %2 of the middle on purpose - still on the Pokémon").arg(std::abs(aim_dx)).arg(side);
}


//  ---- the numbers

QJsonObject throw_constants(){
    auto numbers = [](std::initializer_list<double> values){
        QJsonArray out;
        for (double v : values){
            out.append(v);
        }
        return out;
    };
    QJsonObject o;
    o["THROW_TARGETS"] = QJsonObject{{"nice", TARGET_NICE}, {"great", TARGET_GREAT}, {"excellent", TARGET_EXCELLENT}};
    o["TOUCH_SHOT"] = TOUCH_SHOT;
    o["CURVE_SPINS"] = CURVE_SPINS;
    o["CURVE_RADIUS"] = CURVE_RADIUS;
    o["CURVE_D"] = CURVE_D;
    o["CURVE_LAND"] = CURVE_LAND;
    o["CURVE_LEAN_GAIN"] = CURVE_LEAN_GAIN;
    o["CURVE_LEAN_MAX"] = CURVE_LEAN_MAX;
    o["CURVE_POWER"] = CURVE_POWER;
    o["RING_SPEED"] = RING_SPEED;
    o["RING_TRACK_S"] = RING_TRACK_S;
    o["RING_TRACK_EVERY"] = RING_TRACK_EVERY;
    o["RING_LINE_MAX"] = RING_LINE_MAX;
    o["HIT_SHARE"] = HIT_SHARE;
    o["TH_RING"] = TH_RING;
    o["MAX_THROWS"] = MAX_THROWS;
    o["THROW_BOOST"] = THROW_BOOST;
    o["THROW_FALLBACK"] = numbers({THROW_FALLBACK_DY, THROW_FALLBACK_MS});
    o["REAL_BASE"] = QString(REAL_BASE);
    o["REAL_KEEP"] = REAL_KEEP;
    o["REAL_LOWER"] = REAL_LOWER;
    o["REAL_BANDS"] = QJsonObject{{"nice", numbers({BAND_NICE_LO, BAND_NICE_HI})},
                                  {"great", numbers({BAND_GREAT_LO, BAND_GREAT_HI})},
                                  {"excellent", numbers({BAND_EXCELLENT_LO, BAND_EXCELLENT_HI})}};
    o["REAL_LOWER_OF"] = QJsonObject{{"excellent", QString(LOWER_OF_EXCELLENT)}, {"great", QString(LOWER_OF_GREAT)}, {"nice", QString(LOWER_OF_NICE)}};
    o["REAL_CURVE"] = REAL_CURVE;
    o["REAL_AIM"] = REAL_AIM;
    o["REAL_SLOPPY"] = numbers({REAL_SLOPPY_SHARE, REAL_SLOPPY_AIM});
    o["REAL_POWER"] = REAL_POWER;
    o["REAL_PAUSE"] = numbers({REAL_PAUSE_MIN, REAL_PAUSE_MAX});
    o["REAL_LONG_PAUSE"] = numbers({REAL_LONG_PAUSE_SHARE, REAL_LONG_PAUSE_MIN, REAL_LONG_PAUSE_MAX});
    o["RESULT_FIRST_LOOK"] = RESULT_FIRST_LOOK;
    o["RESULT_WINDOW"] = RESULT_WINDOW;
    o["POLL_PAUSE"] = POLL_PAUSE;
    o["POLL_PAUSE_LIVE"] = POLL_PAUSE_LIVE;
    o["AFTER_OK_WAIT"] = AFTER_OK_WAIT;
    o["AFTER_TAP_WAIT"] = AFTER_TAP_WAIT;
    o["FAST_BACK_AFTER"] = FAST_BACK_AFTER;
    o["FAST_BACK_LATEST"] = FAST_BACK_LATEST;
    o["FAST_LOOK_AFTER"] = FAST_LOOK_AFTER;
    o["CAL_VERSION"] = CAL_VERSION;
    const Cal cal;
    o["cal"] = QJsonObject{{"k", cal.k}, {"c", cal.c}, {"lat", cal.lat}, {"rel", cal.rel}, {"aim", cal.aim}, {"c_live", cal.c_live}};
    o["BALL_XY"] = numbers({(double)BALL_XY.x, (double)BALL_XY.y});
    o["ENC_BERRY_BTN"] = numbers({(double)ENC_BERRY_BTN.x, (double)ENC_BERRY_BTN.y});
    o["ENC_BALL_BTN"] = numbers({(double)ENC_BALL_BTN.x, (double)ENC_BALL_BTN.y});
    return o;
}


}
}
}
}
