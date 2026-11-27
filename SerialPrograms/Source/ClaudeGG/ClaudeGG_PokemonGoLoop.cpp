/*  Claude GG Pokemon GO Loop (the fight loop of the Pokémon GO bot)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <stdexcept>
#include <tuple>
#include <opencv2/imgproc.hpp>
#include <QRegularExpression>
#include "ClaudeGG_PokemonGoLoop.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Loop{

using Battle::Move;


//  The numbers of gamebot.py (see there for what they mean).
static const double FIGHT_START_SECONDS = 240;
static const double FIGHT_SECONDS = 480;
static const int FIGHT_TAP_MS = 70;
static const double CHARGE_HOLD = 2.8;
static const double GAME_BLOCK = 8.5;
static const double THROW_CHECK = 1.1;
static const int THROW_RETRIES = 2;
static const double THROW_LATEST = 3.0;
static const int PLAIN_PICTURES[2] = {5, 2};
static const int ZOOM_PICTURES[2] = {3, 1};
static const double ZOOM_AFTER = 2.0;
static const int BARS_ONLY[2] = {20, 2};
static const int HELD_LIT = 5;
static const int HELD_BACK[2] = {15, 2};
static const double AIM_RECENT = 4.0;
static const double AIM_CHECK = 10.0;
static const int GIVE_UP_LOOKS = 4;
static const double GIVE_UP_EVERY = 0.8;
static const double GIVE_UP_WAIT = 3.5;
static const double RETAP_AFTER = 0.8;
static const int RETAP_MAX = 3;
static const double BALLS_FRESH = 120.0;
static const double READY_RECENT = 3.0;
static const double USED_FROM = 4.0;
static const double USED_UNTIL = 11.0;
static const double USED_EVERY = 0.35;
static const int MAP_PICTURES = 3;
static const double MAP_SECONDS = 2.0;
static const int SWITCH_TAP_MS = 220;
static const double SWITCH_TAP_Y[4] = {0.74, 0.78, 0.71, 0.81};
static const char* const SWITCH_TOUCH_NAMES[4] = {"quick tap", "finger down and up", "press 60 ms", "press 220 ms"};
static const int SWITCH_RETAPS = 13;
static const double RESULT_SETTLE = 0.7;
static const double THEIR_ATTACK = 12.0;
static const double OUR_ATTACK = 4.0;
static const double ATTACK_EDGES = 1.5;
static const double PRE_FIGHT_TAPS = 25.0;
static const double FIGHT_WAIT_LOOK = 8.0;
static const double SWEEP_SECONDS = 0.6;
static const int FOE_CHECK_EVERY = 3;
static const int SHIELDS_BACK = 6;


std::vector<std::pair<QString, std::vector<double>>> loop_constants(){
    return {
        {"FIGHT_START_SECONDS", {(double)FIGHT_START_SECONDS}},
        {"FIGHT_SECONDS", {(double)FIGHT_SECONDS}},
        {"FIGHT_TAP_MS", {(double)FIGHT_TAP_MS}},
        {"CHARGE_HOLD", {(double)CHARGE_HOLD}},
        {"GAME_BLOCK", {(double)GAME_BLOCK}},
        {"THROW_CHECK", {(double)THROW_CHECK}},
        {"THROW_RETRIES", {(double)THROW_RETRIES}},
        {"THROW_LATEST", {(double)THROW_LATEST}},
        {"PLAIN_PICTURES", {(double)PLAIN_PICTURES[0], (double)PLAIN_PICTURES[1]}},
        {"ZOOM_PICTURES", {(double)ZOOM_PICTURES[0], (double)ZOOM_PICTURES[1]}},
        {"ZOOM_AFTER", {(double)ZOOM_AFTER}},
        {"BARS_ONLY", {(double)BARS_ONLY[0], (double)BARS_ONLY[1]}},
        {"HELD_LIT", {(double)HELD_LIT}},
        {"HELD_BACK", {(double)HELD_BACK[0], (double)HELD_BACK[1]}},
        {"AIM_RECENT", {(double)AIM_RECENT}},
        {"AIM_CHECK", {(double)AIM_CHECK}},
        {"GIVE_UP_LOOKS", {(double)GIVE_UP_LOOKS}},
        {"GIVE_UP_EVERY", {(double)GIVE_UP_EVERY}},
        {"GIVE_UP_WAIT", {(double)GIVE_UP_WAIT}},
        {"RETAP_AFTER", {(double)RETAP_AFTER}},
        {"RETAP_MAX", {(double)RETAP_MAX}},
        {"BALLS_FRESH", {(double)BALLS_FRESH}},
        {"READY_RECENT", {(double)READY_RECENT}},
        {"USED_FROM", {(double)USED_FROM}},
        {"USED_UNTIL", {(double)USED_UNTIL}},
        {"USED_EVERY", {(double)USED_EVERY}},
        {"MAP_PICTURES", {(double)MAP_PICTURES}},
        {"MAP_SECONDS", {(double)MAP_SECONDS}},
        {"SWITCH_TAP_MS", {(double)SWITCH_TAP_MS}},
        {"SWITCH_TAP_Y", {(double)SWITCH_TAP_Y[0], (double)SWITCH_TAP_Y[1], (double)SWITCH_TAP_Y[2], (double)SWITCH_TAP_Y[3]}},
        {"SWITCH_RETAPS", {(double)SWITCH_RETAPS}},
        {"RESULT_SETTLE", {(double)RESULT_SETTLE}},
        {"THEIR_ATTACK", {(double)THEIR_ATTACK}},
        {"OUR_ATTACK", {(double)OUR_ATTACK}},
        {"ATTACK_EDGES", {(double)ATTACK_EDGES}},
        {"PRE_FIGHT_TAPS", {(double)PRE_FIGHT_TAPS}},
        {"FIGHT_WAIT_LOOK", {(double)FIGHT_WAIT_LOOK}},
        {"SWEEP_SECONDS", {(double)SWEEP_SECONDS}},
        {"FOE_CHECK_EVERY", {(double)FOE_CHECK_EVERY}},
        {"SHIELDS_BACK", {(double)SHIELDS_BACK}},
    };
}


namespace{


//  f"{x:.Nf}" of Python.
QString fixed(double x, int digits){
    char buffer[64];
    std::snprintf(buffer, sizeof(buffer), "%.*f", digits, x);
    return QString::fromLatin1(buffer);
}

//  round(x, 2) of Python, and repr() of a float: the shortest text that is read back as the same number.
double round_two(double x){
    char buffer[64];
    std::snprintf(buffer, sizeof(buffer), "%.2f", x);
    return std::strtod(buffer, nullptr);
}
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

Point frac_xy(double fx, double fy){
    return Point{(int)(fx * REF_W), (int)(fy * REF_H)};
}
Point frac_xy(const double p[2]){
    return frac_xy(p[0], p[1]);
}

//  The features of a picture as the state of a fight takes them.
Fight::Features fight_features(const Vision::Seen& s){
    Fight::Features f;
    f.hud = s.hud;
    f.white = s.white;
    f.versus = s.versus;
    f.ring = s.ring;
    f.result = s.result;
    f.done = s.done;
    f.hp_me = s.hp.me;
    f.hp_foe = s.hp.foe;
    f.shields_me = s.shields.me;
    f.shields_foe = s.shields.foe;
    f.lit[0] = s.ready.first;
    f.lit[1] = s.ready.second;
    if (s.balls.has_value()){
        f.has_balls = true;
        f.balls[0] = s.balls->me.red;
        f.balls[1] = s.balls->me.grey;
    }
    return f;
}

//  Which question a picture with the countdown shows, as far as the picture itself tells: "shield" (the big lilac
//  shield), "switch" (its countdown sits lower than that of the other questions) or "".
QString question_seen(const Vision::Seen& feat){
    if (feat.hex){
        return "shield";
    }
    return feat.count == "switch" ? QString("switch") : QString();
}

}


//  ---- the thread that taps the fast attacks

ThreadedTapper::ThreadedTapper(Fingers& fingers, Point xy, int ms)
    : m_fingers(fingers)
    , m_xy(xy)
    , m_ms(ms)
{
    m_thread = std::thread([this]{ run(); });
}
ThreadedTapper::~ThreadedTapper(){
    close();
}
void ThreadedTapper::run(){
    while (!m_quit){
        if (m_hold){
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
            continue;
        }
        Planner planner;
        {
            std::lock_guard<std::mutex> state(m_state);
            planner = m_sweep;
        }
        if (planner){
            std::vector<Stroke> strokes;
            try{
                strokes = planner();
            }catch (...){
            }
            if (!strokes.empty()){
                try{
                    std::lock_guard<std::mutex> lock(m_lock);
                    bool same;
                    {
                        std::lock_guard<std::mutex> state(m_state);
                        same = (bool)m_sweep;       //  (the little game was not ended meanwhile)
                    }
                    if (same && !m_hold){
                        m_fingers.swipes(strokes);
                        m_swipes += (int)strokes.size();
                    }
                }catch (...){
                    std::this_thread::sleep_for(std::chrono::milliseconds(300));
                }
                continue;
            }
        }
        {
            std::unique_lock<std::mutex> state(m_state);
            if (!m_wake.wait_for(state, std::chrono::milliseconds(200), [this]{ return m_on.load() || m_quit.load(); })){
                continue;
            }
        }
        if (m_quit){
            break;
        }
        try{
            std::lock_guard<std::mutex> lock(m_lock);
            if (m_on && !m_hold){
                Point xy = m_xy;
                {
                    std::lock_guard<std::mutex> state(m_state);
                    if (m_aim.has_value()){
                        xy = *m_aim;
                    }
                }
                m_fingers.tap(xy.x, xy.y, m_ms);
                m_taps++;
            }
        }catch (...){
            std::this_thread::sleep_for(std::chrono::milliseconds(500));
        }
    }
}
void ThreadedTapper::go(){
    m_on = true;
    m_wake.notify_all();
}
void ThreadedTapper::pause(){
    m_on = false;
}
void ThreadedTapper::aim(const std::optional<Point>& xy){
    std::lock_guard<std::mutex> state(m_state);
    m_aim = xy;
}
void ThreadedTapper::sweep(const Planner& planner){
    std::lock_guard<std::mutex> state(m_state);
    m_sweep = planner;
}
void ThreadedTapper::tap(int x, int y, int ms){
    m_hold = true;
    try{
        std::lock_guard<std::mutex> lock(m_lock);
        m_fingers.tap(x, y, ms);
    }catch (...){
        m_hold = false;
        throw;
    }
    m_hold = false;
}
void ThreadedTapper::touch(int how, int x, int y){
    m_hold = true;
    try{
        std::lock_guard<std::mutex> lock(m_lock);
        switch (how){
        case 0: m_fingers.quick(x, y); break;
        case 1: m_fingers.motion(x, y); break;
        case 2: m_fingers.tap(x, y, 60); break;
        default: m_fingers.tap(x, y, 220); break;
        }
    }catch (...){
        m_hold = false;
        throw;
    }
    m_hold = false;
}
void ThreadedTapper::close(){
    m_quit = true;
    {
        std::lock_guard<std::mutex> state(m_state);
        m_sweep = Planner();
    }
    m_on = false;
    m_wake.notify_all();
    if (m_thread.joinable()){
        m_thread.join();
    }
}


//  ---- the pictures of the fight

Eyes::Eyes(Host& host)
    : m_host(host)
    , m_stream(host.stream())
{}

void Eyes::say_mode(const QString& new_mode, const QString& note){
    if (new_mode != mode){
        mode = new_mode;
        m_host.log(new_mode == "live video"
            ? "battle: pictures from the " + new_mode + (note.isEmpty() ? QString() : " (" + note + ")")
            : QString("battle: no live video - the pictures are screenshots (slow)"));
    }
}

Look Eyes::look(double not_before){
    bool got = false;
    long long new_seq = 0;
    double t = 0;
    cv::Mat small;
    if (m_stream != nullptr && m_stream->healthy()){
        got = m_stream->wait_new(seq, 1.0, not_before, new_seq, t, small);
        if (!got && live > 0 && m_stream->starting()){
            //  (screenrecord stops by itself every three minutes and is started again: its pictures are back within a
            //  second or two, a screenshot would take longer)
            got = m_stream->wait_new(seq, 2.5, not_before, new_seq, t, small);
        }
    }
    Look out;
    if (got){
        seq = new_seq;
        say_mode("live video", QString("%1x%2").arg(small.cols).arg(small.rows));
        live++;
        video = true;
        cv::resize(small, out.canvas, cv::Size(REF_W, REF_H), 0, 0, cv::INTER_LINEAR);
        out.small = small;
        out.t = t;
    }else{
        say_mode("screenshots");
        if (m_stream != nullptr && m_told < 3 && m_host.monotonic() - m_said >= 30.0){
            m_said = m_host.monotonic();            //  (why does the video not come?  the programs' own words)
            m_told++;
            m_host.log("battle: the live video gives no pictures: " + m_stream->describe());
        }
        out.canvas = m_host.screenshot();
        cv::resize(out.canvas, out.small, cv::Size(VIEW_W, VIEW_H), 0, 0, cv::INTER_AREA);
        shots++;
        video = false;
        out.t = m_host.monotonic();
    }
    return out;
}

cv::Mat Eyes::real(const cv::Mat& canvas){
    if (!video){
        return canvas;
    }
    try{
        return m_host.screenshot();
    }catch (const std::exception&){
        return canvas;
    }
}

void Eyes::close(){
    if (m_stream != nullptr){
        m_stream->close();
    }
}


//  ---- reading text

bool map_visible(const cv::Mat& canvas){
    if (canvas.rows <= 2030 || canvas.cols <= 883){
        return false;
    }
    const cv::Vec3b top = canvas.at<cv::Vec3b>(1930, 883);
    const cv::Vec3b bottom = canvas.at<cv::Vec3b>(2030, 883);
    const int r1 = top[2], g1 = top[1], b1 = top[0];
    const int r2 = bottom[2], g2 = bottom[1], b2 = bottom[0];
    const bool red_top = r1 > 35 && r1 > 2.5 * std::max({g1, b1, 1});
    const bool white_bottom = std::max({r2, g2, b2}) - std::min({r2, g2, b2}) < 20 && r2 > 0.8 * r1;
    return red_top && white_bottom;
}

QString white_words(Host& host, const cv::Mat& pic, double x0, double y0, double x1, double y1, int lines, double wide){
    const int h = pic.rows;
    const int w = pic.cols;
    const int ya = (int)(y0 * h);
    const int yb = std::min((int)(y1 * h), h);
    const int xa = (int)(x0 * w);
    const int xb = std::min((int)(x1 * w), w);
    if (yb <= ya || xb <= xa){
        return QString();
    }
    const cv::Mat zone = pic(cv::Rect(xa, ya, xb - xa, yb - ya));
    std::vector<cv::Mat> channels;
    cv::split(zone, channels);
    cv::Mat darkest;
    cv::min(channels[0], channels[1], darkest);
    cv::min(darkest, channels[2], darkest);
    cv::Mat white = darkest >= 215;
    const double share = (double)cv::countNonZero(white) / (double)(white.rows * white.cols);
    if (!(0.01 <= share && share <= 0.45)){         //  (no letters at all, or a white screen)
        return QString();
    }
    const double k = wide / zone.cols;
    cv::Mat black_on_white;
    cv::bitwise_not(white, black_on_white);
    cv::Mat scaled;
    cv::resize(black_on_white, scaled, cv::Size(), k, k, k > 1 ? cv::INTER_CUBIC : cv::INTER_AREA);
    cv::Mat padded;
    cv::copyMakeBorder(scaled, padded, 20, 20, 20, 20, cv::BORDER_CONSTANT, cv::Scalar(255));
    return host.ocr_line(padded, lines);
}

//  The big words in the middle of the result screen: 'YOU WIN!' or 'GOOD EFFORT!' (two lines).
QString result_words(Host& host, const cv::Mat& pic){
    return white_words(host, pic, 0.12, 0.40, 0.88, 0.61, 2, 1100.0);
}

namespace{

//  The banner at the top of a fight ('Mismagius used Dark Pulse!').
QString banner_text(Host& host, const cv::Mat& pic){
    return white_words(host, pic, 0.05, 0.150, 0.95, 0.210);
}

//  The name and the CP in one of the two name boxes at the top (mine on the left, the foe's on the right).
Nav::NameBox fight_box(Host& host, const cv::Mat& shot, bool me){
    const int h = shot.rows;
    const int w = shot.cols;
    const double x0 = me ? 0.03 : 0.60;
    const double x1 = me ? 0.39 : 0.97;
    const cv::Mat crop = shot(cv::Rect((int)(x0 * w), (int)(0.108 * h), (int)(x1 * w) - (int)(x0 * w), (int)(0.150 * h) - (int)(0.108 * h)));
    cv::Mat bordered;
    //  (the border is made of the white only: it is not taken from the pixels around the crop in the picture)
    cv::copyMakeBorder(crop, bordered, 20, 20, 20, 20, cv::BORDER_CONSTANT | cv::BORDER_ISOLATED, cv::Scalar(255, 255, 255));
    return Nav::name_box(host.ocr_lines(bordered));
}

//  Reads what the fight asks for: the name boxes (who is on the field) now and then, the labels under the charged attack
//  buttons after a new Pokémon came in.  The reading is done outside the lock, what it finds is put into the fight inside it.
//  Returns whether the name of the foe was found (nothing: the names were not read).
std::optional<bool> fight_look(Host& host, const cv::Mat& shot, Fight::Fight& fight, std::recursive_mutex& lock){
    bool due;
    bool labels;
    {
        std::lock_guard<std::recursive_mutex> guard(lock);
        due = fight.foe_due();
        labels = fight.need_labels;
    }
    std::optional<bool> found;
    if (due){
        const Nav::NameBox foe = fight_box(host, shot, false);
        const Nav::NameBox mine = fight_box(host, shot, true);
        found = !foe.name.isEmpty();
        std::lock_guard<std::recursive_mutex> guard(lock);
        fight.set_foe(foe.name, foe.has_cp ? std::optional<int>(foe.cp) : std::nullopt);
        fight.set_active(mine.has_cp ? std::optional<int>(mine.cp) : std::nullopt);
    }
    if (labels){
        const int h = shot.rows;
        const std::pair<QString, QString> texts = Nav::button_texts(host.ocr_lines(shot, (int)(0.895 * h), (int)(0.96 * h), 1.0), shot.cols);
        std::lock_guard<std::recursive_mutex> guard(lock);
        fight.set_buttons(texts.first, texts.second);
    }
    return found;
}

}


Looker::Looker(Host& host, Fight::Fight& fight, std::recursive_mutex& lock)
    : m_host(host)
    , m_fight(fight)
    , m_flock(lock)
{}
Looker::~Looker(){
    close();
}
void Looker::start(){
    if (m_host.threads()){
        m_thread = std::thread([this]{ run(); });
    }
}
void Looker::close(){
    m_quit = true;
    {
        std::lock_guard<std::mutex> guard(m_wake_lock);
        m_woken = true;
    }
    m_wake.notify_all();
    if (m_thread.joinable()){
        m_thread.join();
    }
}
void Looker::run(){
    while (!m_quit){
        {
            std::unique_lock<std::mutex> guard(m_wake_lock);
            if (!m_wake.wait_for(guard, std::chrono::milliseconds(300), [this]{ return m_woken; })){
                continue;
            }
            m_woken = false;
        }
        if (m_quit){
            break;
        }
        work();
    }
}
void Looker::read_banner(const cv::Mat& shot){
    if (m_busy || m_quit){
        return;
    }
    m_shot = shot;
    m_what = "banner";
    m_busy = true;
    if (trace){
        trace("banner");
    }
    if (m_host.threads()){
        {
            std::lock_guard<std::mutex> guard(m_wake_lock);
            m_woken = true;
        }
        m_wake.notify_all();
    }else{
        work();
    }
}
void Looker::ask(const cv::Mat& shot){
    if (m_busy || m_quit){
        return;
    }
    bool wanted;
    {
        std::lock_guard<std::recursive_mutex> guard(m_flock);
        wanted = m_fight.foe_due() || m_fight.need_labels;
    }
    if (!wanted){
        return;
    }
    m_shot = shot;
    m_what = "names";
    m_busy = true;
    if (trace){
        trace("ask");
    }
    if (m_host.threads()){
        {
            std::lock_guard<std::mutex> guard(m_wake_lock);
            m_woken = true;
        }
        m_wake.notify_all();
    }else{
        work();
    }
}
void Looker::work(){
    cv::Mat shot = m_shot;
    m_shot = cv::Mat();
    if (shot.empty()){
        m_busy = false;
        return;
    }
    try{
        if (m_what == "banner"){
            const QString text = banner_text(m_host, shot);
            if (!text.isEmpty()){
                std::optional<Move> move;
                {
                    std::lock_guard<std::recursive_mutex> guard(m_flock);
                    move = m_fight.foe_used(text);
                }
                if (move.has_value()){
                    m_used_at = m_host.monotonic();
                }
            }
            m_busy = false;
            return;
        }
        if (m_empty >= 2 && video){                 //  (the video picture is too small for this text: a real one)
            m_empty = 0;
            try{
                shot = m_host.screenshot();
            }catch (const std::exception&){
            }
        }
        const std::optional<bool> found = fight_look(m_host, shot, m_fight, m_flock);
        if (found.has_value()){
            m_empty = *found ? 0 : m_empty + 1;
        }
    }catch (const std::exception& e){
        m_host.log(QString("battle: reading the name boxes failed: ") + e.what());
    }
    m_busy = false;
}


//  ---- the little game of a charged attack

LittleGame::LittleGame(const Move& move_, double t0, const std::map<QString, Minigame::Learned>& learned, int button_)
    : move(move_)
    , button(button_)
    , game(move_.type, t0, [&]() -> std::optional<Minigame::Learned>{
        const auto it = learned.find(move_.type);
        if (it == learned.end()){
            return std::nullopt;
        }
        return it->second;
    }())
{
    game.plain = true;          //  (nothing is swiped blind before the camera was seen there)
}

Minigame::Points LittleGame::look(const cv::Mat& small){
    const double aspect = small.rows / (double)small.cols;
    const Minigame::Points found = Minigame::find_icons(small, game.kind);
    Minigame::Points away;
    for (const Minigame::Point& p : found){
        bool at_button = false;
        for (int i = 0; i < 2; i++){
            if (std::abs(p.first - Vision::BTN_X[i]) < 0.10 && std::abs(p.second - Vision::BTN_Y) * aspect < 0.10){
                at_button = true;
            }
        }
        if (!at_button){
            away.push_back(p);
        }
    }
    if (away.size() >= 2 || found.size() >= 3){
        on = true;
        return found;
    }
    return away;
}

Minigame::Points LittleGame::others(const cv::Mat& small) const{
    const double aspect = small.rows / (double)small.cols;
    Minigame::Points out;
    for (const Minigame::Point& p : Minigame::find_icons(small, alt->type)){
        bool at_button = false;
        for (int i = 0; i < 2; i++){
            if (std::abs(p.first - Vision::BTN_X[i]) < 0.10 && std::abs(p.second - Vision::BTN_Y) * aspect < 0.10){
                at_button = true;
            }
        }
        if (!at_button){
            out.push_back(p);
        }
    }
    return out;
}

void LittleGame::see(const Minigame::Points& icons, double t){
    std::lock_guard<std::mutex> guard(lock);
    game.see(t, icons);
}

std::vector<Stroke> LittleGame::strokes(double now){
    std::vector<Minigame::Swipe> plan;
    {
        std::lock_guard<std::mutex> guard(lock);
        plan = game.plan(now);
    }
    std::vector<Stroke> out;
    double total = 0.0;
    for (const Minigame::Swipe& s : plan){
        out.push_back(Stroke{(int)(s.x1 * REF_W), (int)(s.y1 * REF_H), (int)(s.x2 * REF_W), (int)(s.y2 * REF_H), s.ms});
        total += s.ms / 1000.0 + 0.06;
        if (total >= SWEEP_SECONDS){
            break;
        }
    }
    return out;
}

bool LittleGame::over(double now){
    std::lock_guard<std::mutex> guard(lock);
    return game.over(now);
}

int LittleGame::view(bool fight, bool bars, int need, std::optional<double> now){
    if (fight && bars){
        plain++;
        zoomed = 0;
    }else if (fight){
        plain = 0;
        zoomed++;
    }else{                          //  (an animation, a flash, a banner over the name boxes: no plain fight, and not the camera on the attacker)
        plain = 0;
        zoomed = 0;
    }
    const bool zoom = zoomed >= need && (!now.has_value() || *now - game.t0 >= ZOOM_AFTER);
    std::lock_guard<std::mutex> guard(lock);    //  (after 'Get Ready!' only the plain fight itself stops the swipes)
    game.plain = plain > 0 || !(ready || zoom);
    return plain;
}

bool LittleGame::started(double now){
    if (ready || on){
        return false;
    }
    ready = true;
    std::lock_guard<std::mutex> guard(lock);
    game.started(now);
    return true;
}

void LittleGame::give_up(){
    doubt = true;
    std::lock_guard<std::mutex> guard(lock);
    game.blind = false;
}

void LittleGame::hold(double now){
    held = true;
    asked = now;                    //  (when the question was last on the screen)
    std::lock_guard<std::mutex> guard(lock);
    game.hold(now);
}

QString LittleGame::report() const{
    const Minigame::Game& g = game;
    QString text = QString("battle: little game of %1 (%2): icons on %3 picture(s), %4 swipes planned")
        .arg(move.name, g.kind).arg(g.pictures).arg(g.swipes);
    if (held){
        text += ", it had to wait for the other side's attack";
    }
    if (unseen){
        text += ", thrown by a tap of the fast attacks on its button";
    }
    if (doubt){
        text += QString(", it did not start after the tap") + (on ? " but came later" : "");
    }
    if (g.gate.has_value()){
        text += QString(", the stream crossed (%1, %2, %3, %4)").arg(py_repr(g.gate->x1), py_repr(g.gate->y1), py_repr(g.gate->x2), py_repr(g.gate->y2));
    }
    QStringList rows;
    for (const Minigame::Game::Row& r : g.rows){
        if (r.seen.has_value()){
            rows << QString("(%1, %2, %3, %4)").arg(py_repr(round_two(r.line.x1)), py_repr(round_two(r.line.y1)),
                                                      py_repr(round_two(r.line.x2)), py_repr(round_two(r.line.y2)));
        }
    }
    if (!rows.isEmpty()){
        text += ", rows seen [" + rows.join(", ") + "]";
    }
    if (g.pictures == 0 && g.swipes != 0){
        text += " - no icons seen: what is known of this type was swiped";
    }
    return text;
}


//  ---- the answers to the questions of the game

namespace{

//  What the loop knows for the shield question.
struct Know{
    std::optional<int> foes;                    //  how many Pokémon the foe has left (nothing: not known)
    bool ready = false;                         //  a charged attack of ours was ready when the question came
};
struct Answer{
    std::optional<Point> xy;                    //  where was tapped (nothing: nothing)
    QString kind;                               //  "shield" / "noshield" / "switch"
};

//  The countdown ring is up: find out which question it is and answer it.  Nothing: the question was not read (look
//  again at the next picture).  The shield question is known from its picture: the answer has to be tapped within the
//  five seconds of the countdown, there is no time to read text first.  The switch question is known from its picture too.
std::optional<Answer> fight_answer(Host& host, const cv::Mat& shot, const Vision::Seen& feat, Fight::Fight& fight,
    std::recursive_mutex& lock, Tapper& tapper, int& unknown, Eyes* eyes, const Know& know){
    auto read = [&](const cv::Mat& pic){
        const int h = pic.rows;
        QString kind = Nav::question_kind(host.ocr_lines(pic, (int)(0.44 * h), (int)(0.60 * h), 1.0));
        if (kind.isEmpty()){
            kind = Nav::question_kind(host.ocr_lines(pic, (int)(0.40 * h), (int)(0.66 * h), 0.8));
        }
        return kind;
    };

    const bool video = eyes != nullptr && eyes->video;
    QString kind = question_seen(feat);
    if (kind.isEmpty()){
        kind = read(shot);
    }
    const bool sure = !kind.isEmpty();          //  (seen or read, not only taken for a question)
    if (kind.isEmpty()){                        //  not read: look again at the next picture
        unknown++;
        if (unknown < 2){
            return std::nullopt;
        }
        {
            std::lock_guard<std::recursive_mutex> guard(lock);
            kind = fight.my_shields > 0 ? "shield" : "noshield";    //  (twice in a row: a question we must not miss)
        }
        host.log("battle: the question was not read - taking it for '" + kind + "'");
    }
    unknown = 0;
    const int h = shot.rows;
    const int w = shot.cols;
    (void)h;
    std::optional<Point> xy;
    if (kind == "noshield"){
        host.log("battle: an attack is coming and we have no shields left");
        std::lock_guard<std::recursive_mutex> guard(lock);
        fight.foe_threw(sure);
    }else if (kind == "shield"){
        bool use;
        QString why;
        {
            std::lock_guard<std::recursive_mutex> guard(lock);
            if (feat.hex && fight.my_shields <= 0){
                fight.my_shields = 1;           //  (the game offers a shield: the count we kept was too low)
            }
            const std::optional<double> had = fight.foe_energy();
            const std::pair<bool, QString> verdict = fight.shield(know.foes, know.ready);
            use = verdict.first;
            why = verdict.second;
            fight.foe_threw(sure);              //  (its energy goes down by what the attack costs)
            if (had.has_value() && !why.contains("at most")){   //  (for whoever reads the log: what the count said)
                why += QString(" (%1 has %2 energy at most)").arg(fight.foe->label()).arg((int)*had);
            }
        }
        host.log(QString("battle: shield question - %1: %2").arg(use ? "SHIELD" : "no shield (NOT NOW)", why));
        xy = frac_xy(use ? Vision::TAP_SHIELD : Vision::TAP_NOT_NOW);
        tapper.tap(xy->x, xy->y);
    }else if (kind == "switch"){
        //  The tiles stand in party order, so nothing has to be read to know which is which - and there is no time to read:
        //  the countdown of this question does not always start at 12.  Only a real screenshot is read for its CP numbers
        //  (they are too small on the video picture).
        std::vector<std::pair<int, int>> tiles;
        if (!video){
            tiles = Nav::popup_tiles(host.ocr_lines(shot, (int)(0.60 * shot.rows), (int)(0.70 * shot.rows), 1.0));
        }
        const int shown_n = Vision::popup_tiles_shown(shot);    //  (the tiles on the screen, not our count of who is left)
        Fight::Switched pick;
        int place;
        int n;
        {
            std::lock_guard<std::recursive_mutex> guard(lock);
            pick = fight.switch_in(tiles, shown_n);
            place = fight.tile.first;
            n = std::max(fight.tile.second, shown_n);
        }
        if (!pick.mon.has_value()){
            host.log("battle: our Pokémon fainted and nobody is left");
        }else{
            int x;
            if (pick.tile.has_value()){
                x = tiles[(size_t)*pick.tile].second;
            }else{                                  //  its CP was not read: the tiles stand in party order
                x = (int)((n < 2 ? 0.5 : Vision::POPUP_TILES[std::min(place, 1)]) * w);
            }
            host.log(QString("battle: switching to %1 - %2").arg(fight.team[(size_t)*pick.mon].label(), pick.why));
            xy = Point{(int)((double)x * REF_W / w), (int)(Vision::POPUP_TILE_Y * REF_H)};
            tapper.tap(xy->x, xy->y, SWITCH_TAP_MS);
        }
    }
    return Answer{xy, kind};
}

//  Where to tap on the result screen of a battle, and what that is: NEXT BATTLE when that button is there, otherwise the
//  round button with the check mark under it.
std::pair<Point, QString> result_spot(const cv::Mat& pic){
    if (!Vision::result_button(pic) && Vision::done_button(pic)){
        return {frac_xy(Vision::TAP_DONE), "the check mark"};
    }
    return {frac_xy(Vision::TAP_NEXT), "NEXT BATTLE"};
}

//  Give up the battle: tap the button with the running trainer (top left) and answer the question 'Exit the Trainer Battle?'
//  with YES.  The question is known by its green YES button in the middle of the screen.  True when YES was tapped; false when
//  the question did not come up - then nothing happened and the fight goes on.
bool fight_give_up(Host& host, Tapper& tapper, Eyes& eyes, const QString& why){
    host.log("battle: giving up - " + why);
    tapper.aim(std::nullopt);
    tapper.pause();
    cv::Mat shot;
    try{
        Look first = eyes.look();
        shot = first.canvas;
        if (Vision::exit_yes(first.small).has_value()){     //  (something green is there already: not a question)
            host.log("battle: not giving up after all - the place of the YES button is green before the question");
            return false;
        }
        const Point run = frac_xy(Vision::RUN_BUTTON);
        tapper.tap(run.x, run.y);
        const double end = host.monotonic() + GIVE_UP_WAIT;
        int seen = 0;
        while (host.monotonic() < end){
            Look next = eyes.look();
            shot = next.canvas;
            host.beat();
            const std::optional<Vision::Spot> spot = Vision::exit_yes(next.small);
            seen = spot.has_value() ? seen + 1 : 0;
            if (spot.has_value() && seen >= (eyes.video ? 2 : 1)){      //  (twice on the video: no flicker)
                host.save_picture("g_battle_giveup.png", shot);
                const Point yes = frac_xy(spot->x, spot->y);
                tapper.tap(yes.x, yes.y);
                host.log("battle: 'Exit the Trainer Battle?' - YES");
                return true;
            }
        }
        host.log("battle: the question to leave the battle did not come up - fighting on");
    }catch (const std::exception& e){
        host.log(QString("battle: giving up failed (%1) - fighting on").arg(e.what()));
    }
    if (!shot.empty()){
        host.save_picture("g_battle_giveup.png", shot);
    }
    return false;
}


//  ---- the loop

struct AskState{
    double seen = -100.0;               //  the question on the screen
    double since = 0.0;
    bool done = false;
    std::optional<Point> xy;
    double tapped = 0.0;
    int tries = 0;
    QString kind;
    int n = 0;
};
struct ThrowState{
    std::optional<int> b;               //  the charged attack that was tapped
    Point xy;
    double t = 0.0;
    int tries = 0;
    double until = 0.0;
    int dark = 0;
};
struct ArmState{
    bool on = false;                    //  the fast attacks on a button: which one, when last, and whether the foe's HP goes down meanwhile
    std::optional<int> b;
    double t = 0.0;
    std::optional<std::tuple<int, QString, int>> key;
    double acc = 0.0;
    double hp = 1.0;
    bool proven = false;
};
struct GiveState{
    bool on = false;
    bool tried = false;
    int n = 0;
    double t = 0.0;
    double yes = 0.0;
};
struct Key{
    cv::Mat cur;                        //  the text in a name box now, a new one, how often the new one was seen
    cv::Mat cand;
    int n = 0;
};

class Battle_Loop{
public:
    Battle_Loop(Host& host, const std::vector<Battle::Mon>& team, const std::vector<Point>& use_spots)
        : m_host(host)
        , m_use_spots(use_spots)
        , m_fight(team, [&host](const QString& m){ host.log("battle: " + m); }, host.load_seen())
        , m_eyes(host)
        , m_looker(host, m_fight, m_flock)
    {}

    Result run();

private:
    double now_() const{ return m_host.monotonic(); }
    void log(const QString& text){ m_host.log(text); }

    void end_minigame(const QString& why = QString());
    void start_unseen(double now);
    void finish();

    Host& m_host;
    std::vector<Point> m_use_spots;
    std::recursive_mutex m_flock;               //  (the fight is changed by the loop and by the looker that reads the names)
    Fight::Fight m_fight;
    Eyes m_eyes;
    Looker m_looker;
    std::unique_ptr<Tapper> m_tapper;

    Result out;
    double t0 = 0.0;
    std::optional<double> started;              //  when the HUD was first seen
    double fight_seen = 0.0;
    AskState ask;
    ThrowState thr;
    std::shared_ptr<LittleGame> mini;
    std::pair<bool, bool> lit_prev{false, false};
    std::optional<double> lit_t[2];
    std::optional<int> last_lit_b;
    double last_lit_t = 0.0;
    ArmState arm;
    int ready_n = 0;
    struct{ int me = 3; int foe = 3; double t = 0.0; } balls;
    GiveState give;
    struct{ double since = 0.0; double until = 0.0; double t = 0.0; } used;
    struct{ int n = 0; std::optional<double> t; } on_map;
    struct{ std::optional<double> t; bool bars = false; double mini = -100.0; } clock;
    struct{ int n = 0; bool on = false; } bars;
    std::map<QString, Minigame::Learned> learned;
    Key keys[2];
    double versus_seen = 0.0;
    struct{ int n = 0; double t = 0.0; double feat = 0.0; int logged = 0; } tim;
    int unknown_ring = 0;
    struct{ double t = 0.0; int n = 0; } look_;
    int party_taps = 0;
    int result_seen = 0;
    int errors = 0;
    std::optional<double> result_at;
};

void Battle_Loop::end_minigame(const QString& why){
    if (!mini){
        return;
    }
    m_tapper->sweep(Planner());
    clock.mini = now_();
    log(mini->report() + (why.isEmpty() ? QString() : " (" + why + ")"));
    const std::optional<Minigame::Learned> found = mini->game.learned();
    if (found.has_value()){                     //  (a type that is not known from recordings: remember it)
        learned[mini->game.kind] = *found;
        m_host.save_minigames(learned);
    }
    mini.reset();
}

//  The banner 'Get Ready!' is up and no charged attack was thrown from here: a tap of the fast attacks on its button threw it
//  (or a swipe, or a tap the loop had given up on).  Which one: the button the fast attacks were on - then it is that one for
//  sure.  Else the one that was last seen ready, else the one that is ready first (the cheaper attack): a guess, and the icons
//  tell when it is wrong.
void Battle_Loop::start_unseen(double now){
    bool sure = false;
    int b;
    Move move;
    std::optional<Move> other;
    int me;
    {
        std::lock_guard<std::recursive_mutex> guard(m_flock);
        const Move* both[2] = {m_fight.move_of(0), m_fight.move_of(1)};
        if (arm.b.has_value() && now - arm.t <= AIM_RECENT){
            b = *arm.b;                         //  (the taps were on this button and on no other)
            sure = true;
        }else if (last_lit_b.has_value() && now - last_lit_t <= AIM_RECENT){
            b = *last_lit_b;
        }else{
            b = (both[1] == nullptr || (both[0] != nullptr && both[0]->energy <= both[1]->energy)) ? 0 : 1;
        }
        move = both[b] != nullptr ? *both[b] : m_fight.me_mon().charged[0];
        if (both[1 - b] != nullptr){
            other = *both[1 - b];
        }
        m_fight.throws++;
        me = m_fight.me;
    }
    const double t = now - Minigame::GET_READY;
    thr.b.reset();
    thr.t = t;
    thr.tries = 0;
    thr.dark = 0;
    thr.until = t + GAME_BLOCK;
    mini = std::make_shared<LittleGame>(move, t, learned, b);
    mini->mon = me;
    mini->unseen = true;
    if (!(sure || !other.has_value() || other->type == move.type)){
        mini->alt = other;
    }
    mini->started(now);
    {
        std::shared_ptr<LittleGame> game = mini;
        Host& host = m_host;
        m_tapper->sweep([game, &host]{ return game->strokes(host.monotonic()); });
    }
    log(QString("battle: 'Get Ready!' - %1 was thrown by a tap on its button, its little game starts").arg(move.name));
}

void Battle_Loop::finish(){
    m_tapper->sweep(Planner());
    m_tapper->close();
    m_looker.close();
    m_eyes.close();
    m_host.busy(0);
    if (mini){
        log(mini->report());
    }
    if (m_fight.learned){                       //  (the attacks the opponents really used: for the battles to come)
        m_host.save_seen(m_fight.known);
    }
    if (out.gave_up && out.result.isEmpty() && out.why.startsWith("back on")){
        out.result = "loss";                    //  (given up, and the game did not show a result screen)
        out.why = QString();
    }
    out.seconds = (int)(now_() - t0);
    log(QString("battle: fight loop ended after %1 s: ").arg(out.seconds)
        + (!out.result.isEmpty() ? out.result : !out.why.isEmpty() ? out.why : QString("no result"))
        + (out.gave_up ? " (given up)" : "")
        + QString(" (%1 fast taps, %2 charged attacks with %3 swipes, shields left %4)")
            .arg(m_tapper->taps()).arg(m_fight.throws).arg(m_tapper->swipes()).arg(m_fight.my_shields));
}

Result Battle_Loop::run(){
    m_host.busy(FIGHT_START_SECONDS + FIGHT_SECONDS);   //  (no screen check, no screenshot test during the fight)
    m_tapper = m_host.make_tapper(frac_xy(Vision::TAP_FAST), FIGHT_TAP_MS);
    m_looker.trace = m_host.looker_trace();
    m_looker.start();
    t0 = m_host.monotonic();
    arm.on = m_host.aim_enabled();
    give.on = m_host.give_up_enabled();
    learned = m_host.load_minigames();
    tim.t = m_host.monotonic();
    look_.t = t0;
    Tapper& tapper = *m_tapper;
    Fight::Fight& fight = m_fight;
    Eyes& eyes = m_eyes;
    Looker& looker = m_looker;
    std::recursive_mutex& flock = m_flock;
    Host& host = m_host;
    const QString league = host.league();

    auto battle_kind = [&](const cv::Mat& shot, const Nav::Lines& lines){
        return Nav::screen_kind(lines, host.on_map(shot), league, shot.rows / 2208.0);
    };
    auto sweep_game = [&](){
        std::shared_ptr<LittleGame> game = mini;
        tapper.sweep([game, &host]{ return game->strokes(host.monotonic()); });
    };

    try{
        while (true){
            double now = now_();
            if (host.stop()){
                out.why = "stopped";
                break;
            }
            if (!started.has_value() && now - t0 > FIGHT_START_SECONDS){
                out.why = "the fight did not start";
                break;
            }
            if (started.has_value() && now - *started > FIGHT_SECONDS){
                out.why = "the fight takes too long";
                break;
            }
            Look seen;
            try{
                seen = eyes.look();
            }catch (const std::exception& e){
                errors++;
                log(QString("battle: screenshot failed (%1)").arg(e.what()));
                if (errors > 8){
                    out.why = "the phone does not answer";
                    break;
                }
                host.sleep(1.0);
                continue;
            }
            const cv::Mat shot = seen.canvas;
            const cv::Mat small = seen.small;
            const double t_seen = seen.t;
            host.beat();
            now = now_();
            //  Back on the map: only when the map is on every picture for a while.  One picture of the loading screens before a
            //  fight was once taken for the map, the loop ended and the bot did not fight at all.
            if (host.on_map(shot)){
                if (!on_map.t.has_value()){
                    on_map.t = now;
                    host.save_picture("g_battle_map.png", shot);    //  (to see afterwards what was taken for the map)
                }
                on_map.n++;
                if (on_map.n >= MAP_PICTURES && now - *on_map.t >= MAP_SECONDS){
                    out.why = "back on the map";
                    break;
                }
                continue;
            }
            on_map.n = 0;
            on_map.t.reset();
            //  the video gives ~10 pictures a second: the names are then read when a name box changes (and every five seconds to be
            //  sure) and a shield that was not used is believed after six seconds; with screenshots (one every one to three seconds)
            //  these are counted in pictures as before
            fight.foe_every = eyes.video ? 50 : FOE_CHECK_EVERY;
            fight.shields_back = eyes.video ? 60 : SHIELDS_BACK;
            looker.video = eyes.video;
            try{
                Vision::Seen feat = host.features(small);
                tim.n++;
                tim.feat += now_() - now;
                if (tim.n >= 100 && tim.logged < 3){
                    log(QString("battle: timing - %1 pictures in %2 s (%3 from the live video, %4 screenshots), reading one takes %5 ms")
                        .arg(tim.n).arg(fixed(now_() - tim.t, 0)).arg(eyes.live).arg(eyes.shots).arg(fixed(tim.feat / tim.n * 1000, 0)));
                    tim.n = 0;
                    tim.t = now_();
                    tim.feat = 0.0;
                    tim.logged++;
                    eyes.live = 0;
                    eyes.shots = 0;
                }
                QString st = Fight::state(fight_features(feat));
                if (!started.has_value() || bars.on){
                    //  A net under the name boxes.  They are known by their Poké Balls; should those ever not be recognised (another
                    //  arena, other colours on the video), no picture would count as the fight and the bot would stand still.  Two HP
                    //  bars for two seconds are the fight as well.
                    const bool both = (st == "other" && feat.hp.me.has_value() && feat.hp.foe.has_value()
                                       && !feat.versus && !feat.white && !feat.result);
                    bars.n = both ? bars.n + 1 : 0;
                    if (!bars.on && !started.has_value() && bars.n >= BARS_ONLY[eyes.video ? 0 : 1]){
                        bars.on = true;
                        log("battle: both HP bars are on the screen but the name boxes are not recognised - "
                            "fighting on the HP bars (a recording of this fight would show why)");
                        host.save_picture("g_battle_bars.png", shot);
                    }
                    if (bars.on && st == "other" && (feat.hp.me.has_value() || feat.hp.foe.has_value())){
                        feat.hud = true;
                        feat.ready = Vision::charge_ready(small);
                        st = "fight";
                    }
                }
                if (feat.balls.has_value()){            //  the Poké Balls of the name boxes: who can still fight
                    const Vision::BallSlots& six = *feat.balls;
                    if (six.me.red + six.me.grey == 3 && six.foe.red + six.foe.grey == 3){   //  (all six: none under a banner)
                        balls.me = six.me.red;
                        balls.foe = six.foe.red;
                        balls.t = now;
                    }
                }
                if (st != "fight"){
                    tapper.aim(std::nullopt);           //  (a button is only tapped in the plain fight)
                }
                if (st != "result"){
                    result_at.reset();
                }
                if (now < used.until){                  //  the foe's charged attack: its banner names it
                    if (looker.used_at() >= used.since){
                        used.until = 0.0;               //  (read)
                    }else if (now - used.since >= USED_FROM && now - used.t >= USED_EVERY && st != "result"){
                        used.t = now;
                        looker.read_banner(shot);
                    }
                }
                if (mini){                              //  the little game of our charged attack
                    bool other;
                    {
                        std::lock_guard<std::recursive_mutex> g(flock);
                        other = mini->mon.has_value() && fight.me != *mini->mon;
                    }
                    if (st == "result"){
                        end_minigame("the fight is over");
                    }else if (other){                   //  (the one that threw it is not on the field any more)
                        end_minigame("another Pokémon is on the field");
                    }else if (st == "prompt"){
                        if (mini->on || mini->doubt || !eyes.video){
                            end_minigame("a question came up");
                        }else if (mini->held && now - mini->asked > 3.0){
                            end_minigame("the charged attack did not start");  //  (a second question, and ours did not come in between)
                        }else{
                            mini->hold(now);            //  before its icons came: the other side's attack goes first, ours may follow
                        }                               //  - wait for 'Get Ready!'
                    }else if (mini->over(now)){
                        end_minigame();
                    }else{
                        const int k = eyes.video ? 0 : 1;
                        if (feat.get_ready && mini->started(now)){      //  the one sure sign that it starts
                            log(QString("battle: 'Get Ready!' - the little game of %1 starts").arg(mini->move.name)
                                + (mini->held ? " (it waited for the other side's attack)" : ""));
                        }
                        const int n = mini->view(st == "fight", feat.hp.me.has_value() || feat.hp.foe.has_value(), ZOOM_PICTURES[k], now);
                        Minigame::Points icons = mini->look(small);
                        if (mini->alt.has_value() && !mini->on && icons.empty()){
                            //  nobody saw which button was thrown and the attack was a guess: the icons tell.  Those of the other attack
                            //  have to be on two pictures in a row of the camera on the attacker, after the banner (by day the sky behind
                            //  'Get Ready!' gave four "flying" icons, and a Shadow Ball was swiped as a Sky Attack)
                            mini->alt_n = (mini->zoomed != 0 && !feat.get_ready && mini->others(small).size() >= 3) ? mini->alt_n + 1 : 0;
                            if (mini->alt_n >= (eyes.video ? 2 : 1)){
                                log(QString("battle: the icons are those of %1, not of %2").arg(mini->alt->name, mini->move.name));
                                if (!mini->unseen && !mini->race){      //  (our own tap on a button that was taken for the other attack)
                                    std::lock_guard<std::recursive_mutex> g(flock);
                                    fight.buttons_swapped(*mini->mon);
                                }
                                std::shared_ptr<LittleGame> was = mini;
                                mini = std::make_shared<LittleGame>(*was->alt, was->game.t0, learned, 1 - was->button);
                                mini->mon = was->mon;
                                mini->unseen = true;
                                mini->started(now);
                                mini->view(true, false, 1);
                                sweep_game();
                                icons = mini->look(small);
                            }
                        }
                        if (eyes.video){                //  (a screenshot is too old to aim with)
                            mini->see(icons, t_seen);
                        }
                        if (icons.size() >= 3 && !mini->saved){
                            mini->saved = true;         //  (one picture of it, to check what was seen)
                            cv::Mat pic = small.clone();
                            for (const Minigame::Point& p : icons){
                                cv::circle(pic, cv::Point((int)(p.first * pic.cols), (int)(p.second * pic.rows)),
                                    (int)(0.065 * pic.cols), cv::Scalar(0, 0, 255), 2);
                            }
                            host.save_picture("g_battle_minigame.png", pic);
                        }
                        if (mini->held && !mini->on && !mini->ready){
                            //  waited for.  The fight is back and its button is ready again, or the plain fight with both HP bars has
                            //  been back for a while: it does not come
                            const bool again = st == "fight" && icons.empty() && (mini->button == 0 ? feat.ready.first : feat.ready.second);
                            mini->lit = again ? mini->lit + 1 : 0;
                            if (st == "fight" && feat.hp.me.has_value() && feat.hp.foe.has_value()){
                                mini->back++;
                            }
                        }
                        if ((!icons.empty() && !mini->doubt) || mini->ready){   //  (icons, so no buttons: what looks ready there is an icon)
                            feat.ready = {false, false};
                        }
                        if (mini->on && n >= 2 && icons.empty()){
                            end_minigame();             //  (the plain fight is back: nothing is swiped over it)
                        }else if (mini->on){            //  (the attack was thrown: no other one before it is over)
                            if (mini->doubt && !mini->late){
                                mini->late = true;      //  (it was given up, and its icons are there after all)
                                log(QString("battle: the little game of %1 started after all").arg(mini->move.name));
                                {
                                    std::lock_guard<std::recursive_mutex> g(flock);
                                    fight.throws++;
                                }
                                thr.t = now - Minigame::LEAD;
                            }
                            thr.until = std::max(thr.until, thr.t + GAME_BLOCK);
                        }else if (mini->held && !mini->ready && (mini->lit >= HELD_LIT || mini->back >= HELD_BACK[k])){
                            end_minigame("the charged attack did not start");
                        }else if (!mini->held && !mini->doubt && !mini->ready){
                            //  no icons yet.  The camera goes to the attacker when a charged attack starts and no HP bar is shown until it
                            //  is over: pictures of the plain fight say "not started"
                            if (n >= PLAIN_PICTURES[k] && t_seen - thr.t >= THROW_LATEST){
                                mini->give_up();        //  (a throw of something that was not ready, or a tap the game did not take: the fast
                                thr.b.reset();          //  attacks go on, the next throw does not wait, the icons are still watched for)
                                thr.until = 0.0;
                                {
                                    std::lock_guard<std::recursive_mutex> g(flock);
                                    fight.throws = std::max(fight.throws - 1, 0);
                                }
                                log(QString("battle: %1 did not start - the fight is still on the screen %2 s after the tap, going on")
                                    .arg(mini->move.name, fixed(t_seen - thr.t, 1)));
                            }
                        }
                    }
                }
                //  The clock of the plain fight: both sides tap fast attacks, and the foe gains energy.  It runs while the name boxes and an
                //  HP bar are on the picture and no little game of ours is on (a charged attack of either side stops the game for both).  The
                //  name boxes without an HP bar count too (a flash hides the bars for a moment) - but not within the seconds after a question
                //  or after our little game: that is the banner of the attack.  What the clock is used for is the MOST energy the foe can have,
                //  so in doubt time counts: the time between two pictures of the plain fight counts in full (also when the video stood still for
                //  seconds), unless a question or a little game lay in it - then the game stood still, and only its edges count.
                const bool has_bar = feat.hp.me.has_value() || feat.hp.foe.has_value();
                if (st == "fight" && has_bar){
                    clock.bars = true;
                }
                if (st == "fight" && (!mini || !(mini->on || mini->ready))
                    && (has_bar || (clock.bars && now - ask.seen > THEIR_ATTACK && now - clock.mini > OUR_ATTACK))){
                    if (clock.t.has_value()){
                        double gap = now - *clock.t;
                        if (std::max(ask.seen, clock.mini) >= *clock.t){
                            gap = std::min(gap, ATTACK_EDGES);
                        }
                        std::lock_guard<std::recursive_mutex> g(flock);
                        fight.fought(gap);
                    }
                    clock.t = now;
                }
                const std::pair<bool, bool> ready = feat.ready;     //  what this picture says about the two buttons
                if (eyes.video){                        //  on the video a button is lit when two pictures in a row say so (one can be a
                    feat.ready = {ready.first && lit_prev.first, ready.second && lit_prev.second};  //  flash or a banner over the label)
                }
                lit_prev = st == "fight" ? ready : std::make_pair(false, false);    //  (a flash or a banner)
                for (int b = 0; b < 2; b++){
                    const bool is_ready = b == 0 ? ready.first : ready.second;
                    if (st == "fight" && is_ready){
                        if (!lit_t[b].has_value() || *lit_t[b] == 0.0){
                            lit_t[b] = t_seen;
                        }
                    }else{
                        lit_t[b].reset();
                    }
                    if (lit_t[b].has_value() && *lit_t[b] != 0.0){
                        last_lit_b = b;
                        last_lit_t = now;
                    }
                }
                if (st != "fight"){
                    std::lock_guard<std::recursive_mutex> g(flock);
                    fight.lit[0] = false;               //  (no HUD: what was lit is not known any more)
                    fight.lit[1] = false;
                }
                if (st == "fight" || (st == "other" && started.has_value() && now - fight_seen < 12)){
                    std::lock_guard<std::recursive_mutex> g(flock);
                    fight.see(fight_features(feat));
                }
                if (st == "fight"){
                    if (!started.has_value()){
                        started = now;
                        log("battle: the fight has started");
                    }
                    fight_seen = now;
                    look_.t = now;
                    unknown_ring = 0;
                    tapper.go();
                    for (int s = 0; s < 2; s++){        //  another text in a name box: read the names now
                        const cv::Mat key = Vision::name_key(small, s == 0);
                        Key& k = keys[s];
                        if (!Vision::key_differs(key, k.cur)){
                            k.cand = cv::Mat();
                            k.n = 0;
                        }else if (!k.cand.empty() && !Vision::key_differs(key, k.cand)){
                            k.n++;
                        }else{
                            k.cand = key;
                            k.n = 1;
                        }
                        if (k.n >= (eyes.video ? 2 : 1)){   //  (the same new text twice: no flicker)
                            const bool first = k.cur.empty();
                            k.cur = key;
                            k.cand = cv::Mat();
                            k.n = 0;
                            if (!first){
                                std::lock_guard<std::recursive_mutex> g(flock);
                                fight.read_names(s == 0 ? "me" : "foe");
                            }
                        }
                    }
                    looker.ask(shot);                   //  (names and labels are read next to this loop)
                    ready_n = (!mini && feat.get_ready) ? ready_n + 1 : 0;
                    if (ready_n >= (eyes.video ? 2 : 1)){   //  our charged attack starts, and it was not thrown from here: a tap of the
                        ready_n = 0;                    //  fast attacks on its button did it
                        start_unseen(now);
                    }
                    if (thr.b.has_value()){             //  a charged attack was tapped: did it count?
                        if (mini && mini->on){
                            thr.b.reset();              //  (the icons of the little game are there: it counted)
                        }else if (now - thr.t >= THROW_CHECK){
                            if (!(*thr.b == 0 ? ready.first : ready.second)){
                                thr.dark++;             //  (the button is gone or dark: it counted - on the video only after three pictures
                                if (thr.dark >= (eyes.video ? 3 : 1)){      //  in a row, one could be a flicker)
                                    thr.b.reset();
                                }
                            }else if (thr.tries < THROW_RETRIES){
                                thr.dark = 0;
                                thr.tries++;
                                log("battle: the button is still ready - the tap did not count, tapping again");
                                tapper.tap(thr.xy.x, thr.xy.y, 90);
                                thr.t = now_();
                                thr.until = thr.t + CHARGE_HOLD;
                                if (mini){              //  (when its swipes start is told by the pictures, not by this time: a second tap
                                    mini->game.t0 = thr.t;  //  does not make them late)
                                }
                            }else{                      //  tapped again and again, and it is still lit: the game is slow, or it does not take
                                thr.b.reset();          //  the taps.  The icons are still watched for and the next throw (the button is lit!)
                                if (mini && !mini->doubt){  //  does not wait
                                    mini->give_up();
                                    {
                                        std::lock_guard<std::recursive_mutex> g(flock);
                                        fight.throws = std::max(fight.throws - 1, 0);
                                    }
                                    log(QString("battle: %1 did not start - the button is still ready after %2 taps, going on")
                                        .arg(mini->move.name).arg(THROW_RETRIES + 1));
                                }
                            }
                        }
                    }else if ((!mini || (mini->doubt && !mini->on && !mini->ready)) && now >= thr.until){
                        std::optional<Fight::Thrown> throw_;
                        {
                            std::lock_guard<std::recursive_mutex> g(flock);
                            throw_ = fight.throw_now();
                        }
                        if (throw_.has_value()){
                            end_minigame();             //  (one that was given up: this throw takes its place)
                            const int button = throw_->button;
                            const Move move = throw_->move;
                            const Point xy = frac_xy(Vision::BTN_X[button], Vision::BTN_Y);
                            const double t_tap = now_();
                            tapper.tap(xy.x, xy.y, 90);
                            thr.b = button;
                            thr.xy = xy;
                            thr.t = now_();
                            thr.tries = 0;
                            thr.dark = 0;
                            thr.until = thr.t + CHARGE_HOLD;
                            //  (for the log: how old the first picture of the ready button was when the tap went out, and how long the tap
                            //  itself took - together the time the throw came late)
                            const double lit_since = (lit_t[button].has_value() && *lit_t[button] != 0.0) ? *lit_t[button] : t_tap;
                            log(QString("battle: throwing %1 on the %2 button - %3 (seen ready %4 s before, the tap took %5 s)")
                                .arg(move.name, button == 0 ? "left" : "right", throw_->why)
                                .arg(fixed(std::max(t_tap - lit_since, 0.0), 1)).arg(fixed(thr.t - t_tap, 1)));
                            mini = std::make_shared<LittleGame>(move, thr.t, learned, button);     //  its little game: swipe the icons
                            std::optional<Move> other;
                            {
                                std::lock_guard<std::recursive_mutex> g(flock);
                                mini->mon = fight.me;
                                const Move* m = fight.move_of(1 - button);
                                if (m != nullptr){
                                    other = *m;
                                }
                            }
                            if (other.has_value() && other->type != move.type){
                                //  The icons tell which attack it really was: the fast taps were on the other button a moment ago and one of them may
                                //  have thrown that one - or the names under the buttons were read the wrong way round (22 November: 'Thunderbolt /
                                //  Surf' for Lanturn, every Thunderbolt was swiped as a Surf)
                                mini->alt = other;
                                mini->race = arm.b.has_value() && *arm.b != button && now - arm.t <= AIM_RECENT;
                            }
                            sweep_game();
                        }
                    }
                    //  Where the fast attacks are tapped: on the button of the charged attack that is to be thrown the moment it is ready -
                    //  only while our HP bar is on the picture (the plain fight: when our Pokémon faints, the tiles of the switch question come
                    //  up right where the buttons are)
                    std::optional<int> spot;
                    if (arm.on && !mini && !thr.b.has_value() && now >= thr.until && feat.hp.me.has_value()){
                        std::optional<Fight::Aim> aimed;
                        double foe_hp;
                        std::tuple<int, QString, int> who;
                        {
                            std::lock_guard<std::recursive_mutex> g(flock);
                            aimed = fight.aim();
                            foe_hp = fight.foe_hp;
                            who = std::make_tuple(fight.me_mon().pos, fight.foe.has_value() ? fight.foe->species : QString(), 0);
                        }
                        if (aimed.has_value()){
                            spot = aimed->button;
                            std::get<2>(who) = *spot;
                            if (!arm.key.has_value() || *arm.key != who || foe_hp > arm.hp + 0.05){     //  (more HP: another foe came in)
                                arm.key = who;
                                arm.acc = 0.0;
                                arm.hp = foe_hp;
                            }else if (!arm.proven && feat.hp.foe.has_value()){
                                //  do such taps count as fast attacks?  The foe's HP has to go down meanwhile
                                arm.acc += std::min(std::max(now - arm.t, 0.0), 0.3);
                                if (arm.acc < 1.5){
                                    arm.hp = foe_hp;    //  (an attack that was on its way does not count)
                                }else if (foe_hp < arm.hp - 0.01){
                                    arm.proven = true;
                                }else if (arm.acc >= AIM_CHECK){
                                    arm.on = false;
                                    spot.reset();
                                    host.aim_disabled();    //  (not in the next fights of this run either)
                                    log(QString("battle: the foe's HP did not go down in %1 s of fast attacks tapped on a charged attack button - "
                                                "they do not seem to count there, the middle of the screen is tapped again "
                                                "(GAMEBOT_FIGHT_AIM=0 switches this off for good)").arg(fixed(AIM_CHECK, 0)));
                                }
                            }
                            arm.b = spot;
                            arm.t = now;
                        }
                    }
                    if (spot.has_value()){
                        tapper.aim(frac_xy(Vision::BTN_X[*spot], Vision::BTN_Y));
                    }else{
                        tapper.aim(std::nullopt);
                    }
                    //  A fight that is lost is given up: our last Pokémon against two or more, and it loses the duel it is in (the same answer
                    //  several times in a row - one reading of an HP bar is not enough)
                    if (out.gave_up && now - give.yes > 8.0){
                        out.gave_up = false;            //  (YES was tapped and the fight is still going on)
                        log("battle: still fighting 8 s after YES - the battle was not left, it goes on");
                    }
                    if (give.on && !give.tried && !mini && !thr.b.has_value() && now - give.t >= GIVE_UP_EVERY){
                        give.t = now;
                        bool lost = false;
                        QString why;
                        if (balls.me == 1 && balls.foe >= 2 && now - balls.t < 5.0 && feat.hp.me.has_value() && feat.hp.foe.has_value()){
                            std::lock_guard<std::recursive_mutex> g(flock);
                            if (!fight.foe_due()){      //  (the name in the foe's box is the one that was read)
                                const std::optional<std::pair<bool, QString>> told = host.hopeless(fight, balls.foe);
                                const std::pair<bool, QString> verdict = told.has_value() ? *told : fight.hopeless(balls.foe);
                                lost = verdict.first;
                                why = verdict.second;
                            }
                        }
                        give.n = lost ? give.n + 1 : 0;
                        if (give.n >= GIVE_UP_LOOKS){
                            give.tried = true;
                            out.gave_up = fight_give_up(host, tapper, eyes, why);
                            give.yes = now_();
                        }
                    }
                }else if (st == "prompt"){
                    fight_seen = look_.t = now;
                    const QString seen_kind = question_seen(feat);
                    if (now - ask.seen > 3.0 || (ask.done && !seen_kind.isEmpty() && seen_kind != ask.kind)){
                        //  a new question: after a while without one - or another one than the one that was answered (the shield question
                        //  can follow the switch question within a second or two)
                        ask.since = now;
                        ask.done = false;
                        ask.xy.reset();
                        ask.tapped = 0.0;
                        ask.tries = 0;
                        ask.kind = QString();
                        ask.n = 0;
                        unknown_ring = 0;
                    }
                    ask.seen = now;
                    ask.n++;
                    thr.b.reset();
                    if (!ask.done){
                        tapper.pause();
                        if (seen_kind == "switch"){     //  ours fainted: no swipes of a little game over the tiles
                            tapper.sweep(Planner());    //  (they went on until the answer and spoilt its tap)
                        }
                        //  (the answer to the switch question tells the bot that our Pokémon fainted: on the video that waits for a second
                        //  picture of it, a tenth of a second - not longer, the countdown of this question can be nearly over when it comes up)
                        Know know;
                        if (balls.t != 0.0 && now - balls.t < BALLS_FRESH){
                            know.foes = balls.foe;
                        }
                        know.ready = last_lit_b.has_value() && now - last_lit_t <= READY_RECENT;
                        std::optional<Answer> res;
                        if (!(seen_kind == "switch" && eyes.video && ask.n < 2)){
                            res = fight_answer(host, shot, feat, fight, flock, tapper, unknown_ring, &eyes, know);
                        }
                        if (res.has_value()){
                            ask.done = true;
                            ask.xy = res->xy;
                            ask.tapped = now_();
                            ask.seen = now_();
                            ask.kind = res->kind;
                            log(QString("battle: answered %1 s after the question was seen").arg(fixed(ask.tapped - ask.since, 1)));
                            if (res->kind == "switch"){     //  (ours fainted: its charged attack does not come)
                                end_minigame("another Pokémon comes in");
                            }else{                      //  (their attack: its banner will say which one it is)
                                used.since = ask.tapped;
                                used.until = ask.tapped + USED_UNTIL;
                                used.t = 0.0;
                            }
                            const bool last = balls.me == 1 && now - balls.t < 30.0;    //  (our last Pokémon, by its box)
                            if (res->kind == "noshield" && give.on && !give.tried && last){
                                bool lost;
                                QString why;
                                QString on;
                                {
                                    std::lock_guard<std::recursive_mutex> g(flock);     //  an attack on our last Pokémon, and no shield: is that
                                    const std::pair<bool, QString> verdict = fight.doomed();   //  the end of the fight?  Then give it up
                                    lost = verdict.first;
                                    why = verdict.second;
                                    if (!lost){
                                        on = fight.fights_on();
                                    }
                                }
                                if (lost){
                                    give.tried = true;
                                    out.gave_up = fight_give_up(host, tapper, eyes, why);
                                    give.yes = now_();
                                    ask.seen = give.yes;    //  (the same question, still)
                                    if (out.gave_up){
                                        end_minigame("the battle was given up");
                                    }
                                }else{                  //  (said, so that a log tells why a lost end was played)
                                    log("battle: not giving up - " + on);
                                }
                            }else if (res->kind == "noshield"){
                                bool alone;
                                {
                                    std::lock_guard<std::recursive_mutex> g(flock);
                                    alone = fight.alive().size() == 1;
                                }
                                if (last || alone){     //  (our last one by its box or by our own count)
                                    log("battle: not giving up - " + (
                                        !give.on ? QString("the option 'Give up a lost battle' is off") :
                                        give.tried ? QString("it was tried before in this battle") :
                                        QString("the Poké Balls of our name box showed %1 of ours that can still fight, %2 s ago")
                                            .arg(balls.me).arg(fixed(now - balls.t, 0))));
                                }
                            }
                            if (!res->xy.has_value() && !out.gave_up){
                                tapper.go();            //  (nothing to tap: the attack plays out)
                            }
                        }
                    }else if (ask.xy.has_value() && now - ask.tapped >= RETAP_AFTER){
                        if (ask.tries < (ask.kind == "switch" ? SWITCH_RETAPS : RETAP_MAX)){
                            ask.tries++;                //  (a tap that did not count: the question is still there)
                            tapper.sweep(Planner());
                            int x = ask.xy->x;
                            int y = ask.xy->y;
                            if (ask.kind == "switch"){
                                //  22 November: eleven presses on the tile in eleven seconds and none counted - so each time another kind of
                                //  touch (and another height of the tile); the log says which one, to find the one the game takes
                                y = (int)(SWITCH_TAP_Y[ask.tries % 4] * REF_H);
                                const int how = ask.tries % 4;
                                log(QString("battle: the question is still on the screen - tapping again (%1 at %2, %3)")
                                    .arg(SWITCH_TOUCH_NAMES[how]).arg(x).arg(y));
                                try{
                                    tapper.touch(how, x, y);
                                }catch (const std::exception& e){
                                    log(QString("battle: that touch did not work here (%1)").arg(e.what()));
                                }
                            }else{
                                log("battle: the question is still on the screen - tapping again");
                                tapper.tap(x, y, 120);
                            }
                            ask.tapped = now_();
                        }else{
                            tapper.go();
                        }
                    }
                }else if (st == "result"){
                    tapper.pause();
                    if (!result_at.has_value()){
                        result_at = now;
                    }
                    if (started.has_value() && eyes.video && now - *result_at < RESULT_SETTLE){
                        continue;                       //  (its button is still coming in: a tap now is lost)
                    }
                    const QString words = result_words(host, shot);     //  the big white words: 'YOU WIN!' / 'GOOD EFFORT!'
                    QString res = Nav::result_word(words);
                    cv::Mat real;
                    Nav::Lines lines;
                    if (!res.isEmpty()){                //  (read from the picture at hand: no screenshot, no reading of the whole screen)
                        real = shot;
                        Nav::Line line;
                        line.text = words.toUpper();
                        for (const QString& w : words.toUpper().split(QRegularExpression("\\s+"), Qt::SkipEmptyParts)){
                            line.words.push_back(Nav::Word{w, 0, 0});
                        }
                        lines.push_back(line);
                    }else{
                        real = eyes.real(shot);         //  (other text is read from a real screenshot)
                        lines = host.ocr_lines(real, 100, std::nullopt, 0.6);
                        res = Nav::result_kind(lines);
                    }
                    if (res.isEmpty() && started.has_value() && result_seen < 2 && battle_kind(real, lines) != "party"){
                        result_seen++;                  //  (the text of the result comes in: read it once more)
                        continue;
                    }
                    if (res.isEmpty() && (!started.has_value() || battle_kind(real, lines) == "party")){
                        //  a green button at the bottom that is no result: the party screen (USE THIS PARTY sits where NEXT BATTLE does) or a
                        //  pop-up before the fight
                        if (!m_use_spots.empty() && party_taps < 3 && battle_kind(real, lines) == "party"){
                            const Point p = m_use_spots[(size_t)std::min(party_taps, (int)m_use_spots.size() - 1)];
                            party_taps++;
                            log(QString("battle: still on the party screen - tapping USE THIS PARTY at (%1, %2)").arg(p.x).arg(p.y));
                            tapper.tap(p.x, p.y);
                            host.sleep(2.0);
                        }else if (now - look_.t >= FIGHT_WAIT_LOOK){
                            look_.t = now;
                            log("battle: waiting - a green button, no result (" + Nav::reads(lines, 90) + ")");
                        }
                        continue;
                    }
                    out.result = res;
                    out.gave_up = out.gave_up && res != "win";
                    const std::pair<Point, QString> spot_what = result_spot(real);
                    log("battle: the fight is over: " + (res.isEmpty() ? QString("result not read") : res)
                        + (out.gave_up ? " - given up" : "") + " (" + Nav::reads(lines, 90) + ") - tapping " + spot_what.second);
                    host.save_picture("g_battle_result.png", real);
                    tapper.tap(spot_what.first.x, spot_what.first.y);
                    host.sleep(2.5);
                    break;
                }else{                                  //  VS screen, animation, banner, loading ...
                    if (feat.versus && !started.has_value()){
                        versus_seen = now;
                    }
                    if (started.has_value() && now - fight_seen < 12){
                        if (!out.gave_up){
                            tapper.go();                //  (an animation in the middle of the fight)
                        }
                        continue;
                    }
                    if (!started.has_value() && versus_seen != 0.0 && now - versus_seen < PRE_FIGHT_TAPS){
                        tapper.go();                    //  (the fight starts any moment: the first tap must not wait for a picture of the HUD;
                    }else{                              //  before it taps are ignored)
                        tapper.pause();
                    }
                    if (now - look_.t < FIGHT_WAIT_LOOK){
                        continue;
                    }
                    look_.t = now;
                    look_.n++;
                    const cv::Mat real = eyes.real(shot);
                    const Nav::Lines lines = host.ocr_lines(real, 100, std::nullopt, 0.6);
                    const QString kind = battle_kind(real, lines);
                    if (kind == "party"){
                        versus_seen = 0.0;              //  (no VS screen: this is still the party screen)
                    }
                    log("battle: waiting - screen is " + kind + " (" + Nav::reads(lines, 90) + ")");
                    if (look_.n == 2){
                        host.save_picture("g_battle_wait.png", real);
                    }
                    QString res = Nav::result_word(result_words(host, real));
                    if (res.isEmpty()){
                        res = Nav::result_kind(lines);
                    }
                    if (!res.isEmpty() && (Vision::result_button(real) || Vision::done_button(real))){
                        out.result = res;
                        const std::pair<Point, QString> spot_what = result_spot(real);
                        log("battle: the fight is over: " + res + " - tapping " + spot_what.second);
                        tapper.tap(spot_what.first.x, spot_what.first.y);
                        host.sleep(2.5);
                        break;
                    }
                    if (kind == "party" && !m_use_spots.empty() && party_taps < 3){
                        const Point p = m_use_spots[(size_t)std::min(party_taps, (int)m_use_spots.size() - 1)];
                        party_taps++;
                        log(QString("battle: still on the party screen - tapping USE THIS PARTY at (%1, %2)").arg(p.x).arg(p.y));
                        tapper.tap(p.x, p.y);
                    }else if (kind == "home" || kind == "league" || kind == "menu" || kind == "map"){
                        out.why = "back on the " + kind + " screen";
                        break;
                    }else if (kind == "exit_battle"){
                        const Nav::ExitSpots spots = Nav::exit_battle_spots(lines, real.rows / 2208.0);
                        if (give.tried){                //  (the question we asked for: the tap on YES did not count)
                            out.gave_up = true;
                            log("battle: 'Exit the Trainer Battle?' is still on the screen - YES");
                            give.yes = now_();
                            tapper.tap(spots.yes.first, spots.yes.second);
                        }else if (spots.has_no){
                            tapper.tap(spots.no.first, spots.no.second);
                        }
                    }
                }
            }catch (const std::exception& e){
                errors++;
                log(QString("battle: error in the fight loop: %1").arg(e.what()));
                if (errors > 8){
                    out.why = "too many errors";
                    break;
                }
            }
        }
    }catch (...){
        finish();
        throw;
    }
    finish();
    return out;
}

}


bool fight_on_screen(Host& host){
    try{
        const cv::Mat shot = host.screenshot();
        cv::Mat small;
        cv::resize(shot, small, cv::Size(VIEW_W, (int)std::nearbyint(shot.rows * 704.0 / shot.cols)), 0, 0, cv::INTER_AREA);
        const QString state = Fight::state(fight_features(host.features(small)));
        return state == "fight" || state == "prompt";
    }catch (const std::exception&){
        return false;                                   //  (gamebot: any error is "no")
    }
}

Result fight_battle(Host& host, const std::vector<Battle::Mon>& team, const std::vector<Point>& use_spots){
    Battle_Loop loop(host, team, use_spots);
    return loop.run();
}


}
}
}
}
