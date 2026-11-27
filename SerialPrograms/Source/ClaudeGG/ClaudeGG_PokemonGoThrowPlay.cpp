/*  Claude GG Pokemon GO Throw Play (the throw of a ball: holding it, timing the ring, letting it go, and learning from where it came down)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port of throw_touch(), throw_ball(), humanize(), aim(), ring_track() and watch_flight() of Mobile/gamebot.py.  Every number is
 *  made in the order and in the way that Python makes it (round() to the nearest even number, % that is never negative, products that are
 *  rounded before they are added), and every call to the Host is made where Python makes it: the check plays the stories of the Python
 *  code and compares them event by event.
 *
 */

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <stdexcept>
#include <QJsonArray>
#include "ClaudeGG_PokemonGoThrowPlay.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Throw{

namespace{

const int W = Loop::REF_W;


//  A product that is rounded before it is added to something (Python rounds it; a compiler may fuse the two).
inline double mul(double a, double b){
    volatile double r = a * b;
    return r;
}

//  f"{x:.2f}" and f"{x:+.0f}": Python and printf both round the number as it is, to the nearest, a tie to the even one.
QString fixed(double x, int digits){
    char buffer[512];
    std::snprintf(buffer, sizeof(buffer), "%.*f", digits, x);
    return QString::fromLatin1(buffer);
}
QString signed_fixed(double x, int digits){
    char buffer[512];
    std::snprintf(buffer, sizeof(buffer), "%+.*f", digits, x);
    return QString::fromLatin1(buffer);
}

//  round(x, digits) of Python.
double py_round(double x, int digits){
    char buffer[512];
    std::snprintf(buffer, sizeof(buffer), "%.*f", digits, x);
    return std::strtod(buffer, nullptr);
}

//  repr() of a float: the shortest text that is read back as the same number.
QString py_repr(double x){
    char buffer[64];
    for (int digits = 1; digits <= 17; digits++){
        std::snprintf(buffer, sizeof(buffer), "%.*g", digits, x);
        if (std::strtod(buffer, nullptr) == x){
            break;
        }
    }
    QString text = QString::fromLatin1(buffer);
    if (!text.contains('.') && !text.contains('e') && !text.contains("inf") && !text.contains("nan")){
        text += ".0";
    }
    return text;
}
QString repr_or_none(const std::optional<double>& value){
    return value.has_value() ? py_repr(*value) : QString("None");
}

//  x % 1.0 of Python: never negative.
double mod1(double x){
    const double r = std::fmod(x, 1.0);
    if (r == 0.0){
        return 0.0;
    }
    return r < 0.0 ? r + 1.0 : r;
}

//  A touch event of a throw: DOWN, MOVE or UP at a place of the canvas.
struct Touch{
    const char* action;
    double x;
    double y;
};

//  _touch(): the shell line (it runs on the phone) that sends the touch events one after another.
QString touch_line(Host& host, const std::vector<Touch>& events){
    const QString ip = host.input_cmd().join(" ");
    QStringList parts;
    for (const Touch& event : events){
        const Point real = host.to_real(event.x, event.y);
        parts << QString("%1 motionevent %2 %3 %4").arg(ip, QString::fromLatin1(event.action)).arg(real.x).arg(real.y);
    }
    return "{ " + parts.join("; ") + "; } 2>&1";
}

//  The white rings that the detector found on a catch screen and that can be the ring of a Pokémon that is being caught.
std::vector<Detection> ring_candidates(const std::vector<Detection>& objects){
    std::vector<Detection> out;
    for (const Detection& o : objects){
        if (o.label == "boundingBox" && o.score >= TH_RING && o.cy < BALL_XY.y - 300){
            out.push_back(o);
        }
    }
    return out;
}

//  The least and the most of the ring that a throw for this target aims at; false: it is no target (off).
bool band_of(const QString& name, double& lo, double& hi){
    if (name == "nice"){
        lo = BAND_NICE_LO;
        hi = BAND_NICE_HI;
        return true;
    }
    if (name == "great"){
        lo = BAND_GREAT_LO;
        hi = BAND_GREAT_HI;
        return true;
    }
    if (name == "excellent"){
        lo = BAND_EXCELLENT_LO;
        hi = BAND_EXCELLENT_HI;
        return true;
    }
    return false;
}

//  THROW_TARGETS.get(name).
std::optional<double> target_of(const QString& name){
    if (name == "nice"){
        return TARGET_NICE;
    }
    if (name == "great"){
        return TARGET_GREAT;
    }
    if (name == "excellent"){
        return TARGET_EXCELLENT;
    }
    return std::nullopt;
}

QString lower_of(const QString& name){
    if (name == "excellent"){
        return LOWER_OF_EXCELLENT;
    }
    if (name == "great"){
        return LOWER_OF_GREAT;
    }
    return LOWER_OF_NICE;
}

//  str.capitalize().
QString capitalized(const QString& text){
    return text.isEmpty() ? text : text.left(1).toUpper() + text.mid(1).toLower();
}

//  _landing(): the first picture, and where the ball came down.
Flight landing(const std::vector<cv::Mat>& imgs, const cv::Mat& before, const std::optional<Detection>& ring){
    Flight flight;
    flight.first = imgs.front();
    flight.land = landing_x(imgs, before, ring.has_value() ? &*ring : nullptr);
    return flight;
}

}


//  ---- what is learned, on disk

QJsonObject cal_json(const Cal& cal, bool rounded){
    const auto number = [rounded](double x){ return rounded ? py_round(x, 6) : x; };
    const auto rows = [&number](const std::vector<std::array<double, 3>>& obs){
        QJsonArray out;
        for (const std::array<double, 3>& row : obs){
            out.append(QJsonArray{number(row[0]), number(row[1]), number(row[2])});
        }
        return out;
    };
    QJsonObject out;
    out.insert("k", number(cal.k));
    out.insert("c", number(cal.c));
    out.insert("lat", number(cal.lat));
    out.insert("rel", number(cal.rel));
    out.insert("aim", number(cal.aim));
    out.insert("obs", rows(cal.obs));
    out.insert("c_live", number(cal.c_live));
    out.insert("obs_live", rows(cal.obs_live));
    if (cal.no_curve){
        out.insert("no_curve", true);
    }
    return out;
}

QJsonObject cal_file(const Cal& cal){
    QJsonObject out = cal_json(cal, false);
    out.insert("v", CAL_VERSION);
    return out;
}

bool cal_load(Cal& cal, const QJsonObject& file){
    if (!file.value("v").isDouble() || file.value("v").toInt() != CAL_VERSION){
        return false;
    }
    const auto rows = [](const QJsonValue& value, std::vector<std::array<double, 3>>& into){
        if (!value.isArray()){
            return;
        }
        std::vector<std::array<double, 3>> out;
        for (const QJsonValue& v : value.toArray()){
            const QJsonArray row = v.toArray();
            if (row.size() != 3){
                return;
            }
            out.push_back({row.at(0).toDouble(), row.at(1).toDouble(), row.at(2).toDouble()});
        }
        into = out;
    };
    const auto number = [&file](const char* key, double& into){
        if (file.value(key).isDouble()){
            into = file.value(key).toDouble();
        }
    };
    number("k", cal.k);
    number("c", cal.c);
    number("lat", cal.lat);
    number("rel", cal.rel);
    number("aim", cal.aim);
    number("c_live", cal.c_live);
    rows(file.value("obs"), cal.obs);
    rows(file.value("obs_live"), cal.obs_live);
    return true;
}


//  ---- the variation of a throw

Humanized humanize(Host& host, const QString& target_name, bool curve){
    Humanized h;
    h.target_name = target_name;
    h.curve = curve;
    double lo = 0.0;
    double hi = 0.0;
    const double r = host.unit();
    if (band_of(h.target_name, lo, hi) && r >= REAL_KEEP){
        h.target_name = r < REAL_KEEP + REAL_LOWER ? lower_of(h.target_name) : QString("off");
    }
    if (band_of(h.target_name, lo, hi)){
        h.target = host.uniform(lo, hi);
    }
    if (h.curve && host.unit() >= REAL_CURVE){
        h.curve = false;
    }
    const bool sloppy = host.unit() < REAL_SLOPPY_SHARE;
    h.aim_dx = (int)host.gauss(0.0, sloppy ? REAL_SLOPPY_AIM : REAL_AIM);
    h.power = std::min(std::max(host.gauss(1.0, REAL_POWER), 0.92), 1.08);
    h.pause = host.unit() < REAL_LONG_PAUSE_SHARE
        ? host.uniform(REAL_LONG_PAUSE_MIN, REAL_LONG_PAUSE_MAX)
        : host.uniform(REAL_PAUSE_MIN, REAL_PAUSE_MAX);
    return h;
}


//  ---- looking while the ball is held and while it flies

Track ring_track(Host& host, const cv::Mat& first, std::optional<double> t_first){
    //  The wall clock time of a picture of the video, which has the time of the monotonic clock.
    const auto wall = [&host](double t){ return host.wall() - (host.monotonic() - t); };
    std::vector<std::pair<double, cv::Mat>> frames;
    frames.emplace_back((t_first.has_value() && *t_first != 0.0) ? wall(*t_first) : host.wall(), first);
    for (const std::pair<double, cv::Mat>& live : host.live_frames(RING_TRACK_S, RING_TRACK_EVERY)){
        frames.emplace_back(wall(live.first), live.second);
    }
    Track track;
    const std::vector<Detection> rings = ring_candidates(host.encounter_objects(first));
    if (rings.empty()){
        return track;
    }
    for (const std::pair<double, cv::Mat>& frame : frames){
        const std::optional<Ring> m = measure_ring(frame.second, rings[0]);
        if (m.has_value()){
            track.points.emplace_back(frame.first, m->ratio);
        }
    }
    track.box = rings[0];
    return track;
}

Flight watch_flight(Host& host, const cv::Mat& before, const std::optional<Detection>& ring){
    std::vector<cv::Mat> imgs;
    if (host.live_on()){                                    //  the live video: a picture every tenth of a second
        host.sleep(0.15);
        const std::vector<std::pair<double, cv::Mat>> live = host.live_frames(1.0, 0.12);
        for (size_t i = 0; i < live.size() && i < 8; i++){
            imgs.push_back(live[i].second);
        }
        if (!imgs.empty()){
            return landing(imgs, before, ring);
        }
    }
    std::vector<Later> shots;
    host.sleep(0.2);
    for (int i = 0; i < 4; i++){
        shots.push_back(host.screenshot_later());
        host.sleep(0.16);
    }
    for (Later& shot : shots){
        try{
            imgs.push_back(shot());
        }catch (const std::exception&){
        }
    }
    if (imgs.empty()){
        return Flight();
    }
    return landing(imgs, before, ring);
}

std::optional<Detection> aim(Host& host){
    const Point ball = host.to_real(BALL_XY.x, BALL_XY.y);
    QStringList argv{"adb", "shell"};
    argv += host.input_cmd();
    argv << "swipe" << QString::number(ball.x) << QString::number(ball.y) << QString::number(ball.x) << QString::number(ball.y) << "1300";
    const int hold = host.adb_start(argv, false);
    host.sleep(0.4);
    const cv::Mat img = host.quick_screenshot();
    host.adb_wait(hold);
    host.sleep(0.2);
    const std::vector<Detection> rings = ring_candidates(host.encounter_objects(img));
    host.save_picture("g_richten.png", img);
    if (rings.empty()){
        return std::nullopt;
    }
    return rings[0];
}


//  ---- the throw

std::optional<double> throw_touch(Host& host, Memory& memory, bool curve, std::optional<double> target, const QString& target_name,
                                  int aim_dx, double power){
    Cal& cal = memory.cal;
    const double t_touch = host.wall();
    std::vector<Touch> start;
    start.push_back(Touch{"DOWN", (double)BALL_XY.x, (double)BALL_XY.y});
    Point hand = BALL_XY;                                   //  where the finger rests after this
    if (curve){
        for (const Point& p : spin_points()){
            start.push_back(Touch{"MOVE", (double)p.x, (double)p.y});
            hand = p;
        }
    }
    const int spin = host.adb_start({"adb", "shell", touch_line(host, start)}, true);

    std::optional<Detection> ring;
    std::optional<double> measured;
    std::optional<double> t_shot;
    cv::Mat before;
    double t_grab = 0.0;                                    //  where does the time of the hold go? (for the log)
    double t_find = 0.0;
    double k_now = cal.k;                                   //  (the speed of the ring for this throw)
    bool live_timed = false;
    host.sleep(TOUCH_SHOT);
    try{
        if (target.has_value() && host.live_on()){          //  the live video: follow the ring for a moment
            const double t_s = host.wall();
            const cv::Mat img = host.quick_screenshot();
            t_grab += host.wall() - t_s;
            if (host.quick_live()){
                before = img;
                const double t_f = host.wall();
                const Track track = ring_track(host, img, host.quick_time());
                t_find += host.wall() - t_f;
                if (track.box.has_value()){
                    ring = track.box;
                }
                if (!track.points.empty()){
                    t_shot = track.points.back().first;
                    measured = track.points.back().second;
                    live_timed = true;
                    const std::optional<double> k = ring_speed(track.points);
                    if (k.has_value()){
                        k_now = mul(0.5, *k) + mul(0.5, cal.k);
                    }
                    host.log(QString("  ring followed in the live video: %1 pictures, size %2 -> %3")
                        .arg((int)track.points.size()).arg(fixed(track.points.front().second, 2), fixed(*measured, 2))
                        + (k.has_value() ? QString(", speed %1/s").arg(fixed(*k, 2)) : QString()));
                }
            }
        }
        const int attempts = live_timed ? 0 : 2;            //  screenshots - 2nd look: no ring seen / not readable (yet)
        for (int attempt = 0; attempt < attempts; attempt++){
            const double t_s = host.wall();
            const cv::Mat img = host.quick_screenshot();
            t_grab += host.wall() - t_s;
            before = img;
            const double t_f = host.wall();
            const std::vector<Detection> rings = ring_candidates(host.encounter_objects(img));
            if (!rings.empty()){
                ring = rings[0];
                RingDiag diag;
                std::optional<Ring> m;
                if (target.has_value()){
                    m = measure_ring(img, *ring, &diag);
                }
                if (m.has_value()){
                    measured = m->ratio;
                    t_shot = t_s;
                    if (host.quick_live()){                 //  (a picture of the video: its own moment and its own c)
                        t_shot = host.wall() - (host.monotonic() - host.quick_time());
                        live_timed = true;
                    }
                }else if (target.has_value()){
                    host.save_picture(QString("g_ring_unreadable_%1.png").arg(attempt + 1), img);   //  to see afterwards why it could not be read
                    host.log(QString("  ring attempt %1 not readable (%2 s after touch-down; white ring fit %3, coloured ring score %4, size %5)")
                        .arg(attempt + 1).arg(fixed(t_s - t_touch, 2), repr_or_none(diag.white), repr_or_none(diag.colour),
                                              repr_or_none(diag.has_size ? diag.size : std::nullopt)));
                }
            }else if (target.has_value()){
                host.log(QString("  ring attempt %1: no ring found (%2 s after touch-down)").arg(attempt + 1).arg(fixed(t_s - t_touch, 2)));
            }
            t_find += host.wall() - t_f;
            if (ring.has_value() && (!target.has_value() || measured.has_value())){
                break;
            }
        }
    }catch (const std::exception&){                         //  never leave the finger 'down' (also when the person stops the bot)
        host.adb_communicate(spin);
        QStringList up{"adb", "shell"};
        up += host.input_cmd();
        const Point real = host.to_real(hand.x, hand.y);
        up << "motionevent" << "UP" << QString::number(real.x) << QString::number(real.y);
        host.adb_start(up, false);
        throw;
    }
    memory.ring_shots = memory.ring_shots % 6 + 1;          //  keep the last 6: g_ring_1.png ... g_ring_6.png
    host.save_picture(QString("g_ring_%1.png").arg(memory.ring_shots), before);

    const double t_w = host.wall();
    const QString out = host.adb_communicate(spin);
    const double t_spin = host.wall() - t_w;                //  how long the spin was still going after the ring was read
    if (out.contains("rror") || out.contains("nknown") || out.contains("Usage")){
        try{                                                //  never leave the finger 'down'
            QStringList up{"shell"};
            up += host.input_cmd();
            const Point real = host.to_real(hand.x, hand.y);
            up << "motionevent" << "UP" << QString::number(real.x) << QString::number(real.y);
            host.adb(up);
        }catch (const std::exception&){
        }
        host.log(QString("single touch events not possible on this phone (%1) - using simple throws").arg(out.trimmed().left(80)));
        cal.no_curve = true;
        return std::nullopt;
    }

    double dy;
    double dur;
    int tx;
    if (ring.has_value()){
        const std::pair<double, double> params = host.throw_params(ring->cx, ring->cy, ring->w, ring->h);
        dy = params.first;
        dur = params.second;
        tx = ring->cx;
        host.log(QString("target ring (%1, %2, %3x%4) [%5] -> deltaY %6, %7 ms")
            .arg(ring->cx).arg(ring->cy).arg(ring->w).arg(ring->h).arg(fixed(ring->score, 2), fixed(dy, 0), fixed(dur, 0)));
    }else{
        dy = THROW_FALLBACK_DY;
        dur = THROW_FALLBACK_MS;
        tx = W / 2;
        host.log("target ring not found - default throw");
    }
    tx = tx + aim_dx;                                       //  'realistic throwing': not dead centre every time
    dy = dy * power;
    const int dur_ms = std::max((int)(dur * THROW_BOOST), 60);
    const int steps = std::min(std::max((int)std::nearbyint(dur_ms / std::max(cal.lat, 5.0)), 2), 8);
    const int lean = curve ? curve_lean(cal, tx) : 0;
    int end_x;
    int end_y;
    if (curve){
        end_x = hand.x + lean;
        end_y = std::max((int)(hand.y + mul(dy, CURVE_POWER)), 50);
    }else{
        end_x = tx;
        end_y = std::max((int)(BALL_XY.y + dy), 50);
    }
    end_x = std::min(std::max(end_x, 20), W - 20);
    std::vector<Touch> release;
    for (int i = 0; i < steps; i++){
        const double x = hand.x + (double)((end_x - hand.x) * (i + 1)) / steps;
        const double y = hand.y + (double)((end_y - hand.y) * (i + 1)) / steps;
        release.push_back(Touch{i + 1 < steps ? "MOVE" : "UP", x, y});
    }

    const double c_now = live_timed ? cal.c_live : cal.c;
    const auto ring_at = [&](double t){                     //  ring size at wall clock time t
        return mod1(*measured - mul(k_now, (t - *t_shot) - c_now));
    };

    std::optional<double> expect;
    double wait = 0.0;
    if (measured.has_value()){
        double diff = mod1(ring_at(host.wall() + cal.rel) - *target);
        if (diff > 0.93){                                   //  already just below the target: throw now
            diff -= 1.0;
        }
        wait = std::max(diff, 0.0) / k_now;
        host.log(QString("throw target %1: ring measured %2, holding %3 s more").arg(target_name, fixed(*measured, 2), fixed(wait, 2)));
        host.sleep(wait);
    }else if (target.has_value()){
        host.log("throw target: ring not readable - throwing without timing (NOT on purpose)");
    }

    const double t_b = host.wall();
    try{
        QStringList args{"shell"};
        args << touch_line(host, release);
        host.adb(args);
    }catch (const std::exception& e){
        host.log(QString("throw failed: %1").arg(QString::fromUtf8(e.what())));
    }
    const double t_rel = host.wall();
    cal.rel = mul(0.7, cal.rel) + mul(0.3, t_rel - t_b);
    cal.lat = mul(0.7, cal.lat) + mul(mul(0.3, 1000.0), t_rel - t_b) / (double)(release.size() + 1);
    if (measured.has_value()){
        expect = ring_at(t_rel);
    }
    host.log((curve ? QString("curveball") : QString("ball")) + QString(" thrown from x=%1 towards x=%2 (held %3 s, throw in %4 steps)")
        .arg(hand.x).arg(end_x).arg(fixed(t_rel - t_touch, 1)).arg(steps));
    host.log(QString("  hold time: %1 %2 s + ring search %3 s + spin still going %4 s + ring wait %5 s + release %6 s")
        .arg(live_timed ? QString("live video") : QString("screenshot"), fixed(t_grab, 1), fixed(t_find, 1), fixed(t_spin, 1), fixed(wait, 1), fixed(t_rel - t_b, 1)));

    const Flight flight = watch_flight(host, before, ring);    //  where does the ball go, and how big was the ring?
    if (!flight.first.empty() && expect.has_value()){
        const std::optional<Ring> m = measure_ring(flight.first, *ring);
        if (m.has_value()){
            const double got = m->ratio;
            const QString kind = got < 0.3 ? "Excellent" : got < 0.7 ? "Great" : "Nice";
            host.log(QString("ring at release %1 (%2 size, wanted %3, expected %4)")
                .arg(fixed(got, 2), kind, fixed(*target, 2), fixed(*expect, 2)));
            std::vector<std::array<double, 3>>& obs = live_timed ? cal.obs_live : cal.obs;
            obs.push_back({py_round(*measured, 3), py_round(t_rel - *t_shot, 3), py_round(got, 3)});
            if (obs.size() > 16){
                obs.erase(obs.begin(), obs.end() - 16);
            }
            refit_timing(cal, live_timed);
            memory.stats_n++;
            memory.stats_on += kind.toLower() == target_name.toLower() ? 1 : 0;
            if (memory.stats_n % 10 == 0){
                host.log(QString("throws timed: %1 of the last %2 hit the wanted ring size (ring speed %3/s)")
                    .arg(memory.stats_on).arg(memory.stats_n).arg(fixed(cal.k, 2)));
                memory.stats_n = 0;
                memory.stats_on = 0;
            }
        }
    }
    if (flight.land.has_value() && ring.has_value()){
        const int err = *flight.land - ring->cx;
        const int aimed = err - aim_dx;                     //  compared with where this throw was meant to go
        const QString side = err < 0 ? "left" : "right";
        const double hit_r = HIT_SHARE * ring->w;
        memory.hit = std::abs(err) <= 0.85 * hit_r;         //  a clear hit, not one on the edge
        QString verdict;
        if (std::abs(err) > hit_r){
            verdict = QString(" - MISSED the Pokémon") + (std::abs(aim_dx) > hit_r ? QString(" (on purpose, as planned)") : QString(" (NOT on purpose)"));
        }else if (std::abs(aim_dx) > hit_r){
            verdict = " - planned miss, but it landed on the Pokémon";
        }
        //  learn from a throw only when it could go where it was meant to: not a deliberately
        //  sloppy one and not one that was already leaning as far as it can
        const bool learn = curve && std::abs(aimed) > 70 && std::abs(aim_dx) <= 2.5 * REAL_AIM && std::abs(lean) < CURVE_LEAN_MAX;
        const QString meant = QString(" (meant %1)").arg(aim_dx >= 0 ? QString("+%1").arg(aim_dx) : QString::number(aim_dx));
        if (learn){
            const double step_px = 0.3 * std::min(std::max(aimed, -300), 300);
            cal.aim = std::min(std::max(cal.aim + std::min(std::max(step_px, -100.0), 100.0), -700.0), 700.0);
            host.log(QString("ball came down %1 px %2 of the Pokémon%3%4 - adjusting the aim by %5 px (correction now %6 px)")
                .arg(std::abs(err)).arg(side, meant, verdict, signed_fixed(step_px, 0), fixed(cal.aim, 0)));
        }else{
            host.log(QString("ball came down %1 px %2 of the Pokémon").arg(std::abs(err)).arg(side) + (aim_dx != 0 ? meant : QString()) + verdict);
        }
    }
    host.save_cal(cal);
    return t_rel;
}

double throw_ball(Host& host, Memory& memory){
    memory.hit.reset();                                     //  (throw_touch fills this in when it saw where the ball came down)
    QString target_name = host.setting_text("throw_target", "realistic").toLower();
    bool curve = host.setting("curveball", false);
    int aim_dx = 0;
    double power = 1.0;
    const bool realistic = target_name == "realistic";      //  standard profile: mostly Great, with variation
    if (realistic){
        target_name = REAL_BASE;
    }
    std::optional<double> target = target_of(target_name);
    if (realistic){
        const bool chosen_curve = curve;
        const Humanized h = humanize(host, target_name, curve);
        target_name = h.target_name;
        target = h.target;
        curve = h.curve;
        aim_dx = h.aim_dx;
        power = h.power;
        QStringList plan;
        plan << (target.has_value() ? capitalized(target_name) + " ring" : QString("no ring timing (on purpose)"));
        plan << (curve ? QString("curveball") : QString("straight ball") + (chosen_curve ? QString(" (on purpose)") : QString()));
        plan << aim_note(aim_dx);
        host.log("realistic throw: " + plan.join(", "));    //  so you can tell a planned miss from a real one
        host.sleep(h.pause);
    }
    if ((curve || target.has_value()) && !memory.cal.no_curve){
        const std::optional<double> t_rel = throw_touch(host, memory, curve, target, target_name, aim_dx, power);
        if (t_rel.has_value() && *t_rel != 0.0){
            return *t_rel;
        }
    }
    const std::optional<Detection> ring = aim(host);        //  simple throw: look, then one swipe
    double dy;
    double dur;
    int tx;
    if (ring.has_value()){
        const std::pair<double, double> params = host.throw_params(ring->cx, ring->cy, ring->w, ring->h);
        dy = params.first;
        dur = params.second;
        host.log(QString("target ring (%1, %2, %3x%4) [%5] -> deltaY %6, %7 ms")
            .arg(ring->cx).arg(ring->cy).arg(ring->w).arg(ring->h).arg(fixed(ring->score, 2), fixed(dy, 0), fixed(dur, 0)));
        tx = ring->cx;
    }else{
        dy = THROW_FALLBACK_DY;
        dur = THROW_FALLBACK_MS;
        host.log("target ring not found - default throw");
        tx = BALL_XY.x;
    }
    host.swipe(BALL_XY.x, BALL_XY.y, std::min(std::max(tx + aim_dx, 20), W - 20), std::max((int)(BALL_XY.y + mul(dy, power)), 50),
               std::max((int)(dur * THROW_BOOST), 60));
    return host.wall();
}


}
}
}
}
