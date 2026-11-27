/*  Claude GG Pokemon GO Map (a step on the map of the Pokémon GO bot: a Pokémon, a PokéStop, the camera)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <opencv2/imgproc.hpp>
#include "ClaudeGG_PokemonGoMap.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Map{

using Brain::Detection;


namespace{

//  gamebot.py
const double TH_STOP = 0.3;                         //  a PokéStop this sure is one
const double GONE_COOLDOWN = 45;                    //  s: a spot where the second look saw nothing is not looked at again right away
const double TAP_UP = 0.22;                         //  a hovering Pokémon floats above its ground: tapped this much of its height higher
const int ROTATE = 1;                               //  turning the camera when there is nothing in view is on
const double ROTATE_TURN[2] = {365, 415};           //  degrees a round of turning goes round
const double ROTATE_REVERSE = 0.3;                  //  the share of the rounds that go from right to left
const double ROTATE_LEN[2] = {570, 830};            //  px: the length of a swipe
const double ROTATE_Y[2] = {780, 1020};             //  px: the height of a swipe
const double ROTATE_DRIFT = 40;                     //  px: how far a swipe may go up or down
const double ROTATE_SPEED[2] = {0.9, 1.5};          //  px per ms
const double ROTATE_PAUSE[2] = {1.6, 2.2};          //  s: the wait for the camera to come to rest
const double ROTATE_LONG_PAUSE[3] = {0.06, 2.8, 5.0};   //  the share of the swipes that is followed by a longer pause, and how long
const double ROTATE_LAG = 0.35;                     //  s: from the picture to the start of a swipe that was started with it
const double ROTATE_REST = 0.5;                     //  s: the camera needs this long to come to rest after a swipe
const double SHOT_LAG = 0.25;                       //  s: from asking for a screenshot to the moment it is taken
const double ROTATE_JITTER[2] = {0.0, 0.4};
const double IDLE_RANGE[2] = {6.0, 11.0};           //  s: the wait when a round is done
const double FAST_PENDING_MAX = 90;                 //  s: a fast catch has to be checked within this time
const int FAST_RADIUS = 200;                        //  px: the Pokémon is the same one when it is this near
const double FAST_SCORE = 0.3;
const int FAST_MAX_FAILS = 2;
const int FAST_REST = 1800;                         //  s: no fast catching after two failures in a row
const double GIFT_INTERVAL = 3600;                  //  s
const double MENU_CHECK_INTERVAL = 600;             //  s
const double STOP_LOAD = 0.5;                       //  s: let the stop screen finish loading
const double SPIN_FIRST_LOOK = 0.8;                 //  s after the swipe until the first look at the ring ...
const double SPIN_POLL_UNTIL = 4.5;                 //  ... then looking again straight away until this many s after the swipe
const double STOP_CLOSE_DELAY = 0.4;                //  s between 'ring is purple' and closing the stop
const double AFTER_STOP_TAP = 2.0;                  //  s between tapping a stop on the map and the next look
const double BAG_CLEAN_EVERY = 1200;                //  s

//  spin_stop.py
const int PLAYER_X = 884;                           //  the place of the player on the map
const int PLAYER_Y = 1480;
const int SPIN_X1 = 450;                            //  the swipe over the photo of a stop
const int SPIN_X2 = 1320;
const int SPIN_Y = 1066;
const int BAG_FULL_WAIT = 1800;                     //  s: no spinning after the message that the bag is full
const int RING_CENTER_X = 883;                      //  the ring around the photo in the stop screen
const int RING_CENTER_Y = 1066;
const int RING_R_LOW = 395;
const int RING_R_HIGH = 445;

//  f"{x:.Nf}" of Python.
QString fixed(double x, int digits){
    char buffer[64];
    std::snprintf(buffer, sizeof(buffer), "%.*f", digits, x);
    return QString::fromLatin1(buffer);
}

bool stop_like(const std::string& label){
    return label == "pokestop" || label == "unable_pokestop" || label == "rocket_pokestop" || label == "gym";
}

//  How many pixels of the part `rows` x `cols` of the (BGR) picture have a colour that `ok(h, s, v)` says yes to.
template <class F>
long long count_colour(const cv::Mat& img, int y0, int y1, int x0, int x1, F ok){
    y0 = std::max(y0, 0);
    x0 = std::max(x0, 0);
    y1 = std::min(y1, img.rows);
    x1 = std::min(x1, img.cols);
    if (y0 >= y1 || x0 >= x1){
        return 0;
    }
    cv::Mat hsv;
    cv::cvtColor(img(cv::Range(y0, y1), cv::Range(x0, x1)), hsv, cv::COLOR_BGR2HSV);
    long long n = 0;
    for (int y = 0; y < hsv.rows; y++){
        const cv::Vec3b* row = hsv.ptr<cv::Vec3b>(y);
        for (int x = 0; x < hsv.cols; x++){
            if (ok(row[x][0], row[x][1], row[x][2])){
                n++;
            }
        }
    }
    return n;
}

int floor_half(int n){
    return n >= 0 ? n / 2 : -((-n + 1) / 2);
}

}


//  ---- the readers of pixels

bool ring_spun(const cv::Mat& img){
    //  (the pixels with a distance to the middle between the two radii: the squares of whole numbers are compared, which is what the
    //  distance of the Python code comes to)
    const int y0 = std::max(RING_CENTER_Y - RING_R_HIGH, 0);
    const int y1 = std::min(RING_CENTER_Y + RING_R_HIGH + 1, img.rows);
    const int x0 = std::max(RING_CENTER_X - RING_R_HIGH, 0);
    const int x1 = std::min(RING_CENTER_X + RING_R_HIGH + 1, img.cols);
    if (y0 >= y1 || x0 >= x1){
        return false;
    }
    cv::Mat hsv;
    cv::cvtColor(img(cv::Range(y0, y1), cv::Range(x0, x1)), hsv, cv::COLOR_BGR2HSV);
    long long total = 0;
    long long purple = 0;
    for (int y = 0; y < hsv.rows; y++){
        const cv::Vec3b* row = hsv.ptr<cv::Vec3b>(y);
        for (int x = 0; x < hsv.cols; x++){
            const long long dx = x + x0 - RING_CENTER_X;
            const long long dy = y + y0 - RING_CENTER_Y;
            const long long d2 = dx * dx + dy * dy;
            if (d2 > (long long)RING_R_LOW * RING_R_LOW && d2 < (long long)RING_R_HIGH * RING_R_HIGH){
                total++;
                if (row[x][0] >= 125 && row[x][0] <= 165 && row[x][1] > 80){
                    purple++;
                }
            }
        }
    }
    //  (the part of the ring that is on the picture; the mean of nothing is not a number: no)
    return total > 0 && (double)purple / (double)total > 0.4;
}

bool bag_full(const cv::Mat& img){
    const long long pink = count_colour(img, 1065, 1140, 580, 1200, [](int h, int s, int v){
        return h >= 150 && h <= 178 && s > 50 && v > 140;
    });
    const long long total = (long long)(std::min(1140, img.rows) - 1065) * (std::min(1200, img.cols) - 580);
    return total > 0 && (double)pink / (double)total > 0.3;
}

bool box_full_ball(const cv::Mat& img){
    const long long gold = count_colour(img, 1920, 2050, 820, 940, [](int h, int s, int v){
        return h >= 12 && h <= 35 && s > 110 && v > 150;
    });
    return gold > 300;
}

bool looks_spun(const cv::Mat& img, const Detection& stop){
    const int y0 = std::max(stop.cy - floor_half(stop.h), 0);
    const int y1 = stop.cy + floor_half(stop.h);
    const int x0 = std::max(stop.cx - floor_half(stop.w), 0);
    const int x1 = stop.cx + floor_half(stop.w);
    if (std::min(y1, img.rows) <= y0 || std::min(x1, img.cols) <= x0){
        return false;
    }
    const cv::Rect part(x0, y0, std::min(x1, img.cols) - x0, std::min(y1, img.rows) - y0);
    cv::Mat hsv;
    cv::cvtColor(img(part), hsv, cv::COLOR_BGR2HSV);
    long long blue = 0;
    long long purple = 0;
    for (int y = 0; y < hsv.rows; y++){
        const cv::Vec3b* row = hsv.ptr<cv::Vec3b>(y);
        for (int x = 0; x < hsv.cols; x++){
            const int h = row[x][0];
            const int s = row[x][1];
            const int v = row[x][2];
            if (h >= 92 && h <= 108 && s > 165){
                blue++;
            }
            if (h >= 128 && h <= 150 && s > 70 && v > 120){
                purple++;
            }
        }
    }
    return purple > blue;
}


//  ---- turning the camera

std::pair<Swipe, double> rotate_swipe(Host& host, int direction){
    double length = host.uniform(ROTATE_LEN[0], ROTATE_LEN[1]);
    double x0 = host.uniform(0.18, 0.26) * Loop::REF_W;
    const double y0 = host.uniform(ROTATE_Y[0], ROTATE_Y[1]);
    const double drift = host.uniform(-ROTATE_DRIFT, ROTATE_DRIFT);
    const double y1 = std::min(std::max(y0 + drift, 700.0), 1100.0);
    const double ms = length / host.uniform(ROTATE_SPEED[0], ROTATE_SPEED[1]);
    if (direction < 0){                                 //  the other way round: from the right side
        x0 = Loop::REF_W - x0;
        length = -length;
    }
    const double share = ROTATE_LONG_PAUSE[0];
    double pause;
    if (host.unit() < share){
        pause = host.uniform(ROTATE_LONG_PAUSE[1], ROTATE_LONG_PAUSE[2]);
    }else{
        pause = host.uniform(ROTATE_PAUSE[0], ROTATE_PAUSE[1]);
    }
    Swipe swipe;
    swipe.x1 = (int)x0;
    swipe.y1 = (int)y0;
    swipe.x2 = (int)(x0 + length);
    swipe.y2 = (int)y1;
    swipe.ms = (int)ms;
    return {swipe, pause};
}

void fire_rotation(Host& host, State& state){
    const std::optional<Swipe> armed = state.rotation.armed;
    state.rotation.armed.reset();
    if (!armed.has_value() || host.wall() - state.rotation.armed_at > 20){
        return;
    }
    Fired fired;
    fired.t = host.wall();
    fired.swipe = *armed;
    state.rotation.fired = fired;
    host.swipe_async(armed->x1, armed->y1, armed->x2, armed->y2, armed->ms);
}

double settle_left(Host& host, const Fired& fired){
    const int ms = fired.swipe.ms;
    return std::max(fired.t + ROTATE_LAG + ms / 1000.0 + ROTATE_REST - SHOT_LAG - host.wall(), 0.0);
}

bool undo_rotation(Host& host, State& state, const std::optional<Fired>& fired){
    state.rotation.fired.reset();
    state.rotation.armed.reset();
    if (!fired.has_value()){
        return false;
    }
    const Swipe& s = fired->swipe;
    host.sleep(std::max(fired->t + ROTATE_LAG + s.ms / 1000.0 + 0.1 - host.wall(), 0.0));       //  let that swipe end first
    host.log("camera had already started turning - turning back to look again");
    host.swipe(s.x2, s.y2, s.x1, s.y1, s.ms);
    host.sleep(ROTATE_REST);
    state.rotation.steps = 0;
    return true;
}

bool cooled(Host& host, State& state, int x, int y){
    const double now = host.wall();
    std::vector<Cool> keep;
    for (const Cool& c : state.cooldown){
        if (c.until > now){
            keep.push_back(c);
        }
    }
    state.cooldown.swap(keep);
    for (const Cool& c : state.cooldown){
        if (std::abs(x - c.x) < 150 && std::abs(y - c.y) < 150){
            return true;
        }
    }
    return false;
}

void reset_encounter(Host& host, State& state){
    Encounter& enc = state.enc;
    if (enc.throws > 0 && !enc.caught){
        const QString counted = host.count("fled");
        host.log(QString("Pokémon fled or gone after %1 ball(s) %2").arg(enc.throws).arg(counted));
    }
    enc = Encounter();
    state.enc_xy.reset();
    state.throw_hit.reset();
}


//  ---- a fast catch

std::optional<bool> fast_check(Host& host, State& state, const std::vector<Detection>& objs){
    FastPending& fp = state.fast_pending;
    if (!fp.xy.has_value()){
        return std::nullopt;
    }
    if (host.wall() - fp.t > FAST_PENDING_MAX){
        host.log("fast catch: could not check the result in time - not counted");
        fp.xy.reset();
        return std::nullopt;
    }
    const int x0 = fp.xy->x;
    const int y0 = fp.xy->y;
    std::vector<Detection> stops;
    for (const Detection& o : objs){
        if (stop_like(o.label)){
            stops.push_back(o);
        }
    }
    auto on_stop = [&](const Detection& o){         //  a "Pokémon" that is really (part of) a stop or gym
        for (const Detection& b : stops){
            if (std::abs(o.cx - b.cx) < b.w / 2.0 && std::abs(o.cy - b.cy) < b.h / 2.0){
                return true;
            }
        }
        return false;
    };
    for (const Detection& o : objs){
        if (o.label == "pokemon" && o.score >= FAST_SCORE && !on_stop(o) && std::abs(o.cx - x0) < FAST_RADIUS && std::abs(o.cy - y0) < FAST_RADIUS){
            return true;
        }
    }
    return false;
}

std::optional<double> fast_verdict(Host& host, State& state, const std::vector<Detection>& objs){
    const std::optional<bool> there = fast_check(host, state, objs);
    if (!there.has_value()){
        return std::nullopt;
    }
    FastPending& fp = state.fast_pending;
    const double now = host.wall();
    if (!*there){
        const QString counted = host.count("caught");
        host.log("Pokémon CAUGHT ✔ (fast catch: gone from the map after BACK) " + counted);
        host.log(QString("fast catch timeline: release -> BACK %1 s, -> map checked %2 s (%3 s in total)")
            .arg(fixed(fp.t_back - fp.t_throw, 1), fixed(now - fp.t_back, 1), fixed(now - fp.t_throw, 1)));
        state.fast_fails = 0;
        fp.xy.reset();
        return std::nullopt;
    }
    fp.looks++;
    if (fp.looks < 2){                                  //  the map may need a moment to drop it: look once more
        host.log("fast catch: the Pokémon is still on the map - looking once more");
        return 1.5;
    }
    const int x0 = fp.xy->x;
    const int y0 = fp.xy->y;
    std::vector<Cool> keep;
    for (const Cool& c : state.cooldown){
        if (!(std::abs(c.x - x0) < 150 && std::abs(c.y - y0) < 150)){
            keep.push_back(c);
        }
    }
    state.cooldown.swap(keep);
    state.fast_fails++;
    host.log(QString("fast catch: the Pokémon is still on the map after BACK - not caught, trying it again (%1 of %2 in a row)")
        .arg(state.fast_fails).arg(FAST_MAX_FAILS));
    if (state.fast_fails >= FAST_MAX_FAILS){
        state.fast_fails = 0;
        state.fast_off_until = now + FAST_REST;
        host.log(QString("fast catch does not seem to work here - catching the normal way for %1 min").arg(FAST_REST / 60));
    }
    fp.xy.reset();
    return std::nullopt;
}


//  ---- the map

double do_map(Host& host, State& state, Brain::Eyes& eyes, const cv::Mat& img){
    if (state.enc.caught && state.enc.t_throw != 0.0 && state.enc.t_result != 0.0){     //  how long did the catch take, start to finish?
        const double now = host.wall();
        host.log(QString("catch timeline: last ball -> result screen seen %1 s, -> back on the map %2 s (%3 s in total)")
            .arg(fixed(state.enc.t_result - state.enc.t_throw, 1), fixed(now - state.enc.t_result, 1), fixed(now - state.enc.t_throw, 1)));
    }
    reset_encounter(host, state);
    std::optional<Fired> fired = state.rotation.fired;      //  fast looking: a swipe was started right after this picture was taken
    state.rotation.fired.reset();
    const bool gifts_due = host.wanted("daily_cycle") ? state.gift_last == 0.0 : host.wall() - state.gift_last > GIFT_INTERVAL;
    if ((host.wanted("gifts_open") || host.wanted("gifts_send")) && gifts_due){
        state.gift_last = host.wall();
        host.gifts_round();
        return 3;
    }
    //  the trainer itself (head and body) is never tapped.  A Pokémon at the trainer's feet is: it is a real wild one when the tap
    //  opens a catch screen; when it does not (your buddy walks there too) that area is left alone for a while.
    const int px = PLAYER_X;
    const int py = PLAYER_Y;
    const bool buddy_walks = host.setting("buddy", false);      //  'My buddy walks along' (off: everything next to the trainer is wild)

    auto on_trainer = [&](const Detection& o){
        return std::abs(o.cx - px) < 110 && -300 < o.cy - py && o.cy - py < 40;
    };
    auto beside_trainer = [&](int x, int y){
        return std::abs(x - px) < 200 && -300 < y - py && y - py < 260;
    };

    typedef std::pair<std::vector<Detection>, std::vector<Detection>> Scan;
    auto scan = [&](bool tiles){
        Scan out;
        for (const Detection& o : eyes.map_objects(img, tiles)){
            const bool dropped = o.label == "pokemon" ? on_trainer(o) : (std::abs(o.cx - px) < 130 && -280 < o.cy - py && o.cy - py < 160);
            if (!dropped){
                out.first.push_back(o);
            }
        }
        std::vector<Detection> stop_boxes;
        for (const Detection& o : out.first){
            if (stop_like(o.label)){
                stop_boxes.push_back(o);
            }
        }
        auto on_stop = [&](const Detection& o){         //  a "Pokémon" that is really (part of) a stop or gym
            for (const Detection& b : stop_boxes){
                if (std::abs(o.cx - b.cx) < b.w / 2.0 && std::abs(o.cy - b.cy) < b.h / 2.0){
                    return true;
                }
            }
            return false;
        };
        for (const Detection& o : out.first){
            if (o.label == "pokemon" && o.score >= Brain::TH_POKEMON
                && o.cy < 1820 && o.cx < 1400                   //  not the buttons on the right / at the bottom
                && !on_stop(o) && !cooled(host, state, o.cx, o.cy)
                && !(buddy_walks && beside_trainer(o.cx, o.cy) && host.wall() < state.near_until)){
                out.second.push_back(o);
            }
        }
        return out;
    };

    const double t_det = host.wall();
    Scan seen = scan(false);
    const bool looking = state.catching && host.wanted("catch")      //  not when only spinning stops
        && !(state.storage_full && (host.wanted("daily_cycle") || host.wanted("spin_only_when_full")));
    if (seen.second.empty() && looking){
        //  nothing found: look again, more thoroughly (12 enlarged looks).  Every other camera position is enough: neighbouring views
        //  overlap, and a weak hit (something that might be a Pokémon) is always worth the thorough look.
        if (eyes.hint || state.rotation.steps % 2 == 0){
            seen = scan(true);
        }
    }
    const std::vector<Detection>& objs = seen.first;
    const std::vector<Detection>& pokemon = seen.second;
    state.perf.detect += host.wall() - t_det;
    state.perf.looks += 1;
    const std::optional<double> wait_more = fast_verdict(host, state, objs);      //  a fast catch waiting for its check on the map
    if (wait_more.has_value()){
        return *wait_more;
    }
    std::vector<Detection> rockets;
    for (const Detection& o : objs){
        if (o.label == "rocket_pokestop" && o.score >= 0.4){
            rockets.push_back(o);
        }
    }
    auto rocket_near = [&](const Detection& o){
        for (const Detection& r : rockets){
            if (std::abs(o.cx - r.cx) < 250 && std::abs(o.cy - r.cy) < 350){
                return true;
            }
        }
        return false;
    };
    std::vector<Detection> stops;
    for (const Detection& o : objs){
        if (o.label == "pokestop" && o.score >= TH_STOP && !rocket_near(o) && !cooled(host, state, o.cx, o.cy) && !looks_spun(img, o)){
            stops.push_back(o);
        }
    }

    const bool full = box_full_ball(img);
    if (full != state.storage_full){
        state.storage_full = full;
        if (full){
            host.log(QString("POKÉMON STORAGE FULL (gold ball)")
                + (host.wanted("spin_only_when_full") ? " - only spinning PokéStops until there is room again" : ""));
        }else{
            host.log("Pokémon storage has room again - catching re-enabled");
        }
    }
    const bool daily = host.wanted("daily_cycle");
    if (full && (daily || host.wanted("close_when_full")) && host.wall() - state.menu_check_last > MENU_CHECK_INTERVAL){
        state.menu_check_last = host.wall();
        host.check_menu_full();                         //  is the bag full as well?
        host.check_all_full();
        return 2;
    }
    const bool catch_on = state.catching && host.wanted("catch") && !(full && (daily || host.wanted("spin_only_when_full")));
    const bool spin_on = state.spin && host.wanted("spin");
    if (((catch_on && !pokemon.empty()) || (spin_on && !stops.empty())) && undo_rotation(host, state, fired)){
        return 0.3;
    }
    if (catch_on && !pokemon.empty()){
        state.rotation.steps = 0;                       //  found: stop turning
        const double sc = pokemon[0].score;
        const int x = pokemon[0].cx;
        const int y = pokemon[0].cy;
        const double t_2 = host.wall();
        const cv::Mat img2 = host.quick_screenshot();
        state.perf.shot += host.wall() - t_2;
        const std::optional<Brain::Seen> found = eyes.second_look(img2, x, y);
        if (!found.has_value()){
            const double best = eyes.second_best;
            host.log(QString("Pokémon on map (%1, %2) [%3] gone at second look (%4) - looking again")
                .arg(x).arg(y).arg(fixed(sc, 2), best != 0.0 ? "best score there now " + fixed(best, 2) : QString("nothing there now")));
            state.cooldown.push_back(Cool{x, y, host.wall() + GONE_COOLDOWN});      //  not the same spot again and again
            cv::Mat dbg = img.clone();                  //  both looks, to see afterwards what it was
            cv::circle(dbg, cv::Point(x, y), 90, cv::Scalar(0, 0, 255), 6);
            host.save_picture("g_look1.png", dbg);
            host.save_picture("g_look2.png", img2);
            return 1;
        }
        const int fx = found->x;                        //  where it is right now
        const int fy = found->y;
        const int bw = found->w;
        const int bh = found->h;
        const bool next_to = beside_trainer(fx, fy);
        int tx, ty;
        if (next_to){                                   //  next to the trainer: tap the side of it that is away from him
            tx = fx + (fx < px ? -1 : 1) * (int)(0.12 * bw);
            ty = fy + (int)(0.05 * bh);
        }else{
            tx = fx;
            ty = fy - (int)(TAP_UP * bh);               //  a hovering Pokémon floats above its ground
        }
        host.log(QString("Pokémon on map (%1, %2) [%3]%4 - tapping").arg(fx).arg(fy).arg(fixed(sc, 2), QString(next_to ? " next to the trainer" : "")));
        cv::Mat dbg = img2.clone();
        cv::circle(dbg, cv::Point(tx, ty), 60, cv::Scalar(0, 0, 255), 8);
        host.save_picture("g_pokemon_kaart.png", dbg);
        host.tap(tx, ty);
        state.cooldown.push_back(Cool{fx, fy, host.wall() + 60});       //  not the same spot again right away
        state.last_tap.kind = QString("pokemon");
        state.last_tap.xy = Point{fx, fy};
        state.last_tap.near = next_to;
        state.last_tap.alt = std::vector<Point>{Point{fx, fy}, Point{fx, fy + (int)(0.3 * bh)}};
        return 3;
    }
    if (spin_on && !stops.empty()){
        state.rotation.steps = 0;
        const double sc = stops[0].score;
        const int x = stops[0].cx;
        const int y = stops[0].cy;
        host.log(QString("PokéStop on map (%1, %2) [%3] - opening").arg(x).arg(y).arg(fixed(sc, 2)));
        state.last_tap.kind = QString("stop");
        state.last_tap.xy = Point{x, y};
        host.tap(x, y);
        state.cooldown.push_back(Cool{x, y, host.wall() + 60});
        return AFTER_STOP_TAP;
    }

    //  nothing to do in view: turn the camera a little and look again
    Rotation& rot = state.rotation;
    if (catch_on && ROTATE && rot.steps == 0){          //  a new round: how far round, which way
        rot.turned = 0.0;
        rot.goal = host.uniform(ROTATE_TURN[0], ROTATE_TURN[1]) * 700 / 45;
        rot.dir = host.unit() < ROTATE_REVERSE ? -1 : 1;
        rot.armed.reset();
        fired.reset();
    }
    if (catch_on && ROTATE && (fired.has_value() || rot.turned < rot.goal)){
        rot.steps += 1;
        if (rot.steps == 1){
            const int n = std::max(state.perf.looks, 1);       //  how long did the looks since the last round take?
            const double rest = std::max(state.perf.total - state.perf.shot - state.perf.detect, 0.0);
            QString text = QString("no Pokémon in view - rotating camera (round of %1 degrees, %2)")
                .arg(fixed(rot.goal * 45 / 700, 0), QString(rot.dir < 0 ? "right to left" : "left to right"));
            if (state.perf.looks >= 3){
                text += QString(" (last %1 looks: %2 s each = screenshot %3 s + detection %4 s + other %5 s + camera wait %6 s)")
                    .arg(state.perf.looks)
                    .arg(fixed(state.perf.total / n + state.perf.wait / n, 1), fixed(state.perf.shot / n, 1), fixed(state.perf.detect / n, 1),
                         fixed(rest / n, 1), fixed(state.perf.wait / n, 1));
            }
            host.log(text);
            const double now = host.wall();
            state.perf.looks = 0;
            state.perf.shot = 0.0;
            state.perf.detect = 0.0;
            state.perf.wait = 0.0;
            state.perf.total = -(now - state.perf.t_step.value_or(now));
            host.save_picture("g_map_none.png", img);       //  what the bot saw when it found nothing
        }
        const bool fast = host.setting("fast_look", true);
        if (!fired.has_value()){                        //  first look of a round (or fast looking is off): turn now
            const std::pair<Swipe, double> turn = rotate_swipe(host, rot.dir);
            const Swipe& swipe = turn.first;
            if (!fast){                                 //  the old way: turn, wait, look
                rot.turned += std::abs(swipe.x2 - swipe.x1);
                host.swipe(swipe.x1, swipe.y1, swipe.x2, swipe.y2, swipe.ms);
                state.perf.wait += turn.second;
                return turn.second;
            }
            Fired now;
            now.t = host.wall();
            now.swipe = swipe;
            fired = now;
            host.swipe_async(swipe.x1, swipe.y1, swipe.x2, swipe.y2, swipe.ms);
        }
        rot.turned += std::abs(fired->swipe.x2 - fired->swipe.x1);
        if (rot.turned < rot.goal){                     //  more to come: it starts when the next picture has been taken
            rot.armed = rotate_swipe(host, rot.dir).first;
            rot.armed_at = host.wall();
        }
        //  cooldowns stay: whatever is always at the same screen position (such as something near the player) is not tapped again and
        //  again; real Pokémon move along with the camera.
        double wait = settle_left(host, *fired) + host.uniform(ROTATE_JITTER[0], ROTATE_JITTER[1]);
        if (host.unit() < ROTATE_LONG_PAUSE[0]){        //  now and then a longer look away
            wait += host.uniform(ROTATE_LONG_PAUSE[1], ROTATE_LONG_PAUSE[2]);
        }
        state.perf.wait += wait;
        return wait;                                    //  the camera has to come to rest first
    }
    rot.steps = 0;                                      //  round done: wait a little
    return host.uniform(IDLE_RANGE[0], IDLE_RANGE[1]);
}


//  ---- the stop

double do_pokestop(Host& host, State& state, const cv::Mat& img){
    if (ring_spun(img)){                                //  already spun (purple): just close it
        host.log("stop already spun - closing");
        host.back();
        return 1.5;
    }
    host.sleep(STOP_LOAD);                              //  let the stop load
    for (int attempt = 1; attempt < 5; attempt++){
        const double t_swipe = host.wall();
        host.swipe(SPIN_X1, SPIN_Y, SPIN_X2, SPIN_Y, 180);
        host.sleep(SPIN_FIRST_LOOK);
        while (true){                                   //  no fixed wait: look until the ring turns purple
            const cv::Mat shot = host.screenshot();
            if (ring_spun(shot)){
                const QString counted = host.count("stops");
                host.log(QString("stop spun ✔ %1 - spin took %2 s").arg(counted, fixed(host.wall() - t_swipe, 1)));
                host.sleep(STOP_CLOSE_DELAY);
                host.back();
                return 1.5;
            }
            if (bag_full(shot)){
                host.back();
                if (host.setting("bag_clean", true) && state.bag_cleaned.value_or(0.0) + BAG_CLEAN_EVERY < host.wall()){
                    state.bag_cleaned = host.wall();
                    host.sleep(2.0);
                    int gone;
                    try{
                        gone = host.clean_bag();
                    }catch (const Flow::Interrupted&){
                        throw;
                    }catch (const std::exception& e){
                        host.log(QString("bag clean-up: error ") + QString::fromUtf8(e.what()));
                        host.bag_to_map();
                        gone = 0;
                    }
                    if (gone != 0){
                        return 2;
                    }
                }
                host.log(QString("BAG FULL - clean up your bag; skipping stops for %1 min").arg(BAG_FULL_WAIT / 60));
                state.spin = false;
                state.bag_is_full = true;
                host.resume_spin_later();
                host.check_all_full();
                return 3;
            }
            if (host.wall() - t_swipe > SPIN_POLL_UNTIL){
                break;
            }
        }
    }
    host.log("spin failed (too far away?) - closing stop");
    host.back();
    return 5;
}


std::vector<std::pair<QString, std::vector<double>>> map_constants(){
    typedef std::vector<double> V;
    std::vector<std::pair<QString, V>> out;
    out.push_back({"TH_POKEMON", V{Brain::TH_POKEMON}});
    out.push_back({"TH_STOP", V{TH_STOP}});
    out.push_back({"TH_WEAK", V{Brain::TH_WEAK}});
    out.push_back({"TH_TILE", V{Brain::TH_TILE}});
    out.push_back({"ZOOM_BOX", V{(double)Brain::ZOOM_X0, (double)Brain::ZOOM_Y0, (double)Brain::ZOOM_X1, (double)Brain::ZOOM_Y1}});
    out.push_back({"TILE", V{(double)Brain::TILE}});
    out.push_back({"TILE_X", V(Brain::TILE_X, Brain::TILE_X + 4)});
    out.push_back({"TILE_Y", V(Brain::TILE_Y, Brain::TILE_Y + 3)});
    out.push_back({"GONE_COOLDOWN", V{GONE_COOLDOWN}});
    out.push_back({"TAP_UP", V{TAP_UP}});
    out.push_back({"ROTATE", V{(double)ROTATE}});
    out.push_back({"ROTATE_TURN", V(ROTATE_TURN, ROTATE_TURN + 2)});
    out.push_back({"ROTATE_REVERSE", V{ROTATE_REVERSE}});
    out.push_back({"ROTATE_LEN", V(ROTATE_LEN, ROTATE_LEN + 2)});
    out.push_back({"ROTATE_Y", V(ROTATE_Y, ROTATE_Y + 2)});
    out.push_back({"ROTATE_DRIFT", V{ROTATE_DRIFT}});
    out.push_back({"ROTATE_SPEED", V(ROTATE_SPEED, ROTATE_SPEED + 2)});
    out.push_back({"ROTATE_PAUSE", V(ROTATE_PAUSE, ROTATE_PAUSE + 2)});
    out.push_back({"ROTATE_LONG_PAUSE", V(ROTATE_LONG_PAUSE, ROTATE_LONG_PAUSE + 3)});
    out.push_back({"ROTATE_LAG", V{ROTATE_LAG}});
    out.push_back({"ROTATE_REST", V{ROTATE_REST}});
    out.push_back({"SHOT_LAG", V{SHOT_LAG}});
    out.push_back({"ROTATE_JITTER", V(ROTATE_JITTER, ROTATE_JITTER + 2)});
    out.push_back({"IDLE_RANGE", V(IDLE_RANGE, IDLE_RANGE + 2)});
    out.push_back({"FAST_PENDING_MAX", V{FAST_PENDING_MAX}});
    out.push_back({"FAST_RADIUS", V{(double)FAST_RADIUS}});
    out.push_back({"FAST_SCORE", V{FAST_SCORE}});
    out.push_back({"FAST_MAX_FAILS", V{(double)FAST_MAX_FAILS}});
    out.push_back({"FAST_REST", V{(double)FAST_REST}});
    out.push_back({"GIFT_INTERVAL", V{GIFT_INTERVAL}});
    out.push_back({"MENU_CHECK_INTERVAL", V{MENU_CHECK_INTERVAL}});
    out.push_back({"STOP_LOAD", V{STOP_LOAD}});
    out.push_back({"SPIN_FIRST_LOOK", V{SPIN_FIRST_LOOK}});
    out.push_back({"SPIN_POLL_UNTIL", V{SPIN_POLL_UNTIL}});
    out.push_back({"STOP_CLOSE_DELAY", V{STOP_CLOSE_DELAY}});
    out.push_back({"AFTER_STOP_TAP", V{AFTER_STOP_TAP}});
    out.push_back({"BAG_CLEAN_EVERY", V{BAG_CLEAN_EVERY}});
    out.push_back({"S.PLAYER", V{(double)PLAYER_X, (double)PLAYER_Y}});
    out.push_back({"S.SPIN_X1", V{(double)SPIN_X1}});
    out.push_back({"S.SPIN_X2", V{(double)SPIN_X2}});
    out.push_back({"S.SPIN_Y", V{(double)SPIN_Y}});
    out.push_back({"S.BAG_FULL_WAIT", V{(double)BAG_FULL_WAIT}});
    out.push_back({"S.RING_CENTER", V{(double)RING_CENTER_X, (double)RING_CENTER_Y}});
    out.push_back({"S.RING_R", V{(double)RING_R_LOW, (double)RING_R_HIGH}});
    return out;
}


}
}
}
}
