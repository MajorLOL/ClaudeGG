/*  Claude GG Pokemon GO Flow (the walk around a fight of the Pokémon GO bot)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  See the header.  The numbers, the order of the things that are looked at and the words of the log lines are those of
 *  gamebot.py (_settled, button_label, _battle_to_map, battle_open_menu, battle_run); where Python does something in an
 *  expression (an `or`, a walrus) that has a reading of the screen in it, the port does it in the same order, because the
 *  checks hold it to the order of what was read.
 *
 */

#include <algorithm>
#include <cmath>
#include <opencv2/imgproc.hpp>
#include "ClaudeGG_PokemonGoFlow.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Flow{

namespace{

const int REF_W = Loop::REF_W;
const int REF_H = Loop::REF_H;

const int BATTLE_NAV_STEPS = 20;            //  screens looked at on the way to the party screen
const double BATTLE_NAV_SECONDS = 240;      //  ... and the most time that may take
const int COLLECT_TAPS = 6;                 //  gold COLLECT tiles of a Battle screen with a grey BATTLE button tapped at most
const int CLAIM_TAPS = 4;                   //  the claim button of the Battle screen is tapped this often at most
const int CLAIM_STEPS = 14;                 //  screens looked at after it (the rank-up and its rewards) ...
const double CLAIM_SECONDS = 150;           //  ... and the most time that may take
const char* const CLAIM_NOT[] = {"SHOP", "BUY", "COIN", "SHARE", "EXCHANGE", "PREMIUM", "PASS", "PURCHASE"};   //  buttons never tapped there
const double CLAIM_TAP_ON[2] = {0.5, 0.30}; //  where a screen with nothing to tap on it is tapped to go on (tap to continue)
const double HOME_SCROLL[3][2] = {{0.70, 0.56}, {0.64, 0.48}, {0.78, 0.62}};
const int HOME_SCROLL_MS = 900;
const int HOME_TAPS = 4;                    //  the BATTLE button is tapped this often at most
const int POPUP_TAPS = 4;                   //  pop-ups on the way tapped away at most
const double WELCOME_BUTTON[2] = {0.5, 0.916};  //  where LET'S GO! is when the button itself is not seen
const Point MENU_BTN = {884, 1985};         //  Poké Ball button on the map -> main menu
const double TH_CLASS = 0.5;                //  minimal certainty of the screen classifier

//  A position as fractions of the screen -> canvas pixels.
Point frac_xy(double fx, double fy){
    return Point{(int)(fx * REF_W), (int)(fy * REF_H)};
}
Point frac_xy(const Vision::Spot& p){
    return frac_xy(p.x, p.y);
}

bool claim_not(const QString& text){
    for (const char* bad : CLAIM_NOT){
        if (text.contains(QLatin1String(bad))){
            return true;
        }
    }
    return false;
}

//  Answer 'Do you want to exit Pokémon GO?' with CANCEL.
void cancel_exit(Host& host, const Nav::Lines& lines){
    for (const Nav::Line& line : lines){
        for (const Nav::Word& w : line.words){
            if (Nav::like(w.text, "CANCEL", 0.8)){
                host.tap(w.x, w.y);
                return;
            }
        }
    }
    host.back();
}

QString battle_kind(Host& host, const cv::Mat& shot, const Nav::Lines& lines){
    const bool on_map = host.on_map(shot);
    return Nav::screen_kind(lines, on_map, host.league(), (double)shot.rows / 2208);
}

QString spot_text(const Spot& s){
    return QString("(%1, %2)").arg(s.first).arg(s.second);
}

}   //  namespace


QString Host::button_label(const cv::Mat& img, const Vision::Button& button){
    return Flow::button_label(*this, img, button);
}

Loop::Result Host::fight(const std::vector<Battle::Mon>& team, const std::vector<Point>& use_spots){
    return Loop::fight_battle(*this, team, use_spots);
}


//  ---- what is looked at

bool screen_changed(const cv::Mat& a, const cv::Mat& b, double share){
    cv::Mat sa;
    cv::Mat sb;
    cv::resize(a, sa, cv::Size(221, 276), 0, 0, cv::INTER_AREA);
    cv::resize(b, sb, cv::Size(221, 276), 0, 0, cv::INTER_AREA);
    long long count = 0;
    for (int y = 0; y < sa.rows; y++){
        for (int x = 0; x < sa.cols; x++){
            int largest = 0;
            for (int c = 0; c < sa.channels(); c++){
                const int d = std::abs((int)sa.ptr<uchar>(y)[x * sa.channels() + c] - (int)sb.ptr<uchar>(y)[x * sb.channels() + c]);
                largest = std::max(largest, d);
            }
            if (largest > 25){
                count++;
            }
        }
    }
    return (double)count / ((double)sa.rows * sa.cols) >= share;
}

cv::Mat settled(Host& host, double first_wait){
    host.sleep(first_wait);
    double t0 = host.wall();
    cv::Mat prev = host.screenshot();
    for (int i = 0; i < 3; i++){
        host.sleep(std::max(1.0 - (host.wall() - t0), 0.0));
        t0 = host.wall();
        const cv::Mat cur = host.screenshot();
        if (!screen_changed(prev, cur, 0.01)){
            return cur;
        }
        prev = cur;
    }
    return prev;
}

cv::Mat label_picture(const cv::Mat& img, const Vision::Button& button){
    const int h = img.rows;
    const int w = img.cols;
    const int y0 = (int)(std::max(button.y0 - 0.012, 0.0) * h);
    const int y1 = (int)(std::min(button.y1 + 0.012, 1.0) * h);
    const int x0 = (int)(button.x0 * w);
    const int x1 = (int)(button.x1 * w);
    const int rows = y1 - y0;
    const int cols = x1 - x0;
    if (rows < 8 || cols <= 0){
        return cv::Mat();
    }
    const cv::Mat crop = img(cv::Rect(x0, y0, cols, rows));
    const double f = 110.0 / rows;      //  (letters of 40 to 60 px: what tesseract reads best)
    cv::Mat resized;
    cv::resize(crop, resized, cv::Size(), f, f, f > 1 ? cv::INTER_CUBIC : cv::INTER_AREA);
    const int ch = resized.rows;
    const int cw = resized.cols;
    std::vector<cv::Mat> channels;
    cv::split(resized, channels);
    cv::Mat darkest = channels[0];
    for (size_t c = 1; c < channels.size(); c++){
        cv::min(darkest, channels[c], darkest);
    }
    cv::Mat top;
    cv::morphologyEx(darkest, top, cv::MORPH_TOPHAT, cv::getStructuringElement(cv::MORPH_ELLIPSE, cv::Size(31, 31)));
    //  The label is in the middle of the button (lower down in one that is cut off by the lower edge of the screen).
    const bool cut = button.y1 >= 0.985;
    const int zone_y0 = (int)((cut ? 0.30 : 0.24) * ch);
    const int zone_y1 = (int)((cut ? 0.98 : 0.80) * ch);
    const int zone_x0 = (int)(0.08 * cw);
    const int zone_x1 = (int)(0.92 * cw);
    const cv::Mat zone = top(cv::Rect(zone_x0, zone_y0, zone_x1 - zone_x0, zone_y1 - zone_y0)).clone();
    cv::Mat values = zone.reshape(1, (int)zone.total());
    cv::Mat unused;
    const double otsu = cv::threshold(values, unused, 0, 255, cv::THRESH_BINARY + cv::THRESH_OTSU);
    const double thr = std::max(otsu, 18.0);
    cv::Mat text(ch, cw, CV_8UC1, cv::Scalar(255));
    for (int y = zone_y0; y < zone_y1; y++){
        for (int x = zone_x0; x < zone_x1; x++){
            if ((double)top.at<uchar>(y, x) > thr){
                text.at<uchar>(y, x) = 0;
            }
        }
    }
    cv::Mat padded;
    cv::copyMakeBorder(text, padded, 16, 16, 16, 16, cv::BORDER_CONSTANT, cv::Scalar(255));
    return padded;
}

QString button_label(Loop::Host& host, const cv::Mat& img, const Vision::Button& button){
    const cv::Mat picture = label_picture(img, button);
    if (picture.empty()){
        return QString();
    }
    return host.ocr_line(picture, 1).toUpper();
}


//  ---- the walk

bool to_map(Host& host, bool leaving_setup){
    int yes_taps = 0;
    for (int i = 0; i < 10; i++){
        const cv::Mat shot = host.screenshot();
        if (host.on_map(shot)){
            return true;
        }
        const Nav::Lines lines = host.ocr_lines(shot, 100, std::nullopt, 0.6);
        const QString kind = battle_kind(host, shot, lines);
        host.beat();
        if (kind == "exit"){
            cancel_exit(host, lines);
        }else if (kind == "exit_battle"){
            const Nav::ExitSpots spots = Nav::exit_battle_spots(lines, (double)shot.rows / 2208);
            if (leaving_setup && yes_taps < 3){
                yes_taps++;
                host.log("battle: leaving the league screens - answering YES to 'Exit the Trainer Battle?' "
                         "(no battle was started), at " + spot_text(spots.yes));
                host.tap(spots.yes.first, spots.yes.second);
            }else if (spots.has_no){
                host.tap(spots.no.first, spots.no.second);
            }else{
                host.back();
            }
        }else if (kind == "menu"){
            host.tap(MENU_BTN.x, MENU_BTN.y);           //  the X of the main menu
        }else{
            host.back();
        }
        host.sleep(2.5);
    }
    return host.on_map(host.screenshot());
}

Info open_menu(Host& host, bool restart, bool stay, bool leagues_only){
    const QString league = host.league();
    Info info;
    const QStringList names = host.team_names();
    const double t0 = host.monotonic();
    int taps_map = 0;
    int taps_home = 0;
    int taps_league = 0;
    std::optional<std::vector<Spot>> menu_spots;
    int others = 0;
    bool tapped = false;
    bool in_setup = false;                      //  the league list or party screen was seen
    struct Claim{                               //  the claim button and what follows it
        int taps = 0;
        double since = 0.0;
        int steps = 0;
        int idle = 0;
        int catching = 0;
    } claim;
    int collect_taps = 0;                       //  the gold COLLECT tiles of the rewards of a set
    int collect_catch = 0;
    int scroll_down = 0;                        //  how often the Battle screen was scrolled
    int scroll_up = 0;
    int popups = 0;                             //  pop-ups that were tapped away
    int max_steps = BATTLE_NAV_STEPS;
    double max_seconds = BATTLE_NAV_SECONDS;
    int step = -1;

    //  A screen that came after the claim button (the rank-up, its rewards): tap what takes it further.
    //  True when the walk has to stop here (info says why).
    auto after_claim = [&](const cv::Mat& shot, const Nav::Lines& lines, double k) -> bool{
        claim.steps++;
        if (claim.steps <= 8){
            host.save_picture(QString("g_battle_claim_%1.png").arg(claim.steps), shot);
        }
        const std::vector<Vision::Button> buttons = Vision::wide_buttons(shot);
        const std::pair<QString, double> screen = host.screen_class(shot);
        if (screen.first == "encounterScreen" && screen.second >= TH_CLASS && buttons.empty() && !Nav::battle_words(lines)){
            claim.catching++;                   //  a Pokémon to catch as a reward (seen twice: no flicker)
            if (claim.catching >= 2){
                info.why = "a Pokémon to catch came up after the claim (a reward)";
                info.leave = true;
                return true;
            }
            return false;
        }
        claim.catching = 0;
        if (claim.steps > CLAIM_STEPS || host.monotonic() - claim.since > CLAIM_SECONDS){
            info.why = "the screens after the claim did not come to an end (see debug/g_battle_claim_*.png)";
            info.leave = true;
            return true;
        }
        std::optional<Point> spot;
        QString what;
        for (const Vision::Button& b : buttons){    //  a green or orange button: CLAIM, OK, NEXT ... (lowest first)
            const QString text = host.button_label(shot, b);
            if (Nav::keep_off_label(text) || claim_not(text)){
                host.log("battle: claiming: not tapping the button '" + text + "'");
                continue;
            }
            spot = frac_xy(Vision::button_spot(b));
            what = "the " + b.color + " button '" + (text.isEmpty() ? QString("label not read") : text) + "'";
            break;
        }
        if (!spot.has_value()){
            const std::vector<Nav::NextWord> words = Nav::next_words(lines, k);
            if (!words.empty()){
                spot = Point{words[0].x, words[0].y};
                what = "'" + words[0].text + "'";
            }
        }
        if (!spot.has_value()){
            claim.idle++;                       //  an animation, or a screen that goes on with a tap anywhere
            if (claim.idle < 2){
                return false;
            }
            spot = frac_xy(CLAIM_TAP_ON[0], CLAIM_TAP_ON[1]);
            what = "the screen (nothing to tap is seen on it)";
        }
        claim.idle = 0;
        host.log(QString("battle: claiming: tapping %1 at (%2, %3)").arg(what).arg(spot->x).arg(spot->y));
        host.tap(spot->x, spot->y);
        return false;
    };

    //  A screen the bot does not know, with a green button: (x, y, label) when that button may be tapped.  It may when its label
    //  says that it only takes the screen further (LET'S GO!, OK, CONTINUE, NEXT BATTLE ...), or when the label is not read and
    //  the button is where NEXT BATTLE is on a result screen.  Never when the label says something else that is read (USE THIS
    //  PARTY, YES, JOIN ...) or when the screen is about buying, leaving or giving something away.
    struct Popup{
        Point at;
        QString text;
    };
    auto popup_button = [&](const cv::Mat& shot, const Nav::Lines& lines) -> std::optional<Popup>{
        if (!Nav::danger_words(lines).isEmpty()){
            return std::nullopt;
        }
        std::vector<Vision::Button> green;
        for (const Vision::Button& b : Vision::wide_buttons(shot)){
            if (b.color == "green"){
                green.push_back(b);
            }
        }
        if (green.empty()){                     //  (not found as a button, but the place of NEXT BATTLE is green)
            if (Vision::result_button(shot)){
                return Popup{frac_xy(Vision::TAP_NEXT[0], Vision::TAP_NEXT[1]), "label not read"};
            }
            if (Vision::done_button(shot) && (!Nav::result_word(Loop::result_words(host, shot)).isEmpty() || !Nav::result_kind(lines).isEmpty())){
                return Popup{frac_xy(Vision::TAP_DONE[0], Vision::TAP_DONE[1]), "the check mark of the result screen"};   //  (no NEXT BATTLE there)
            }
            return std::nullopt;
        }
        const QString text = host.button_label(shot, green[0]);
        if (Nav::keep_off_label(text) || claim_not(text)){
            return std::nullopt;
        }
        const Point at = frac_xy(Vision::button_spot(green[0]));
        if (Nav::go_on_label(text)){
            return Popup{at, text};
        }
        if (Vision::result_button(shot) && green[0].y0 < Vision::TAP_NEXT[1] && Vision::TAP_NEXT[1] < green[0].y1){
            return Popup{at, (text.isEmpty() ? QString("label not read") : text) + ", where NEXT BATTLE is"};
        }
        return std::nullopt;
    };

    //  What is done when the walk is over, whatever way it ended.
    auto finally_do = [&](){
        if (info.ok && stay){
            //  (the caller starts the fight from the party screen)
        }else if (info.leave){
            host.log("battle: the screen is left as it is (no BACK: that could throw a reward away)");
        }else if (!to_map(host, in_setup)){
            if (restart){
                host.log("battle: could not get back to the map - restarting the game");
                host.restart_game();
            }else{
                host.log("battle: could not get back to the map - the normal bot takes over");
            }
        }
    };

    try{
        for (;;){
            step++;
            if (step >= max_steps){
                info.why = "too many steps";
                break;
            }
            if (host.stop() || host.monotonic() - t0 > max_seconds){
                info.why = "stopped or out of time";
                break;
            }
            const cv::Mat shot = settled(host, step == 0 ? 1.0 : 1.8);
            const bool map_now = host.on_map(shot);
            const Nav::Lines lines = map_now ? Nav::Lines() : host.ocr_lines(shot, 100, std::nullopt, 0.6);     //  (the map needs no reading)
            const QString kind = battle_kind(host, shot, lines);
            if (kind != "party"){                           //  (the party screen gets its own picture below)
                host.save_picture(QString("g_battle_s%1.png").arg(step), shot);
            }
            if (collect_taps != 0 && kind != "home" && kind != "party" && kind != "league" && kind != "map" && claim.since == 0.0){
                //  a reward tile was collected and something else is on the screen: a Pokémon to catch (the rewards of a set can be
                //  an encounter, 22 November) - leave it as it is, BACK would run away
                const std::pair<QString, double> screen = host.screen_class(shot);
                if (screen.first == "encounterScreen" && screen.second >= TH_CLASS && !Nav::battle_words(lines)){
                    collect_catch++;
                    if (collect_catch >= 2){
                        host.save_picture("g_battle_reward_catch.png", shot);
                        info.why = "a Pokémon to catch came up as a reward of the set";
                        info.leave = true;
                        info.catch_reward = true;
                        break;
                    }
                    continue;
                }
            }
            host.log(QString("battle: step %1: screen is %2 (%3)").arg(step).arg(kind, Nav::reads(lines, 90)));
            host.beat();
            const double k = (double)shot.rows / 2208;
            if (kind == "party" || kind == "league"){
                in_setup = true;
            }
            if (leagues_only && kind == "league"){
                info.leagues = Nav::read_leagues(lines, shot.cols);
                host.save_picture("g_leagues.png", shot);
                if (!info.leagues.empty()){
                    info.ok = true;
                    QStringList parts;
                    for (const auto& league_cp : info.leagues){
                        parts << QString("%1 (max CP %2)").arg(league_cp.first).arg(league_cp.second);
                    }
                    host.log("leagues: " + parts.join(", "));
                }else{
                    info.why = "the leagues on the list were not read (see debug/g_leagues.png)";
                }
                break;
            }
            if (leagues_only && kind == "party"){           //  (the game went to a party screen by itself: back)
                host.back();
                continue;
            }
            if (kind == "party"){
                info.ok = true;
                info.title = Nav::party_title(lines, k);
                info.members = Nav::party_members(lines, names);
                info.use_spots = Nav::party_use_spots(lines, k);
                host.save_picture("g_battle_party.png", shot);
                break;
            }
            if (kind == "map"){
                taps_map++;
                if (taps_map > 3){
                    info.why = "the main menu does not stay open";
                    break;
                }
                host.tap(MENU_BTN.x, MENU_BTN.y);
                tapped = true;
            }else if (kind == "menu"){
                if (!menu_spots.has_value()){
                    menu_spots = Nav::menu_battle_spots(lines, k);
                    if (menu_spots->empty()){
                        host.save_picture("g_battle_menu.png", shot);
                        info.why = "the BATTLE tile is not in the main menu (see debug/g_battle_menu.png)";
                        break;
                    }
                }
                if (menu_spots->empty()){
                    info.why = "tapped every spot of the BATTLE tile and the Battle screen did not open";
                    break;
                }
                const Spot spot = menu_spots->front();
                menu_spots->erase(menu_spots->begin());
                host.log(QString("battle: tapping BATTLE in the main menu at (%1, %2)").arg(spot.first).arg(spot.second));
                host.tap(spot.first, spot.second);
                tapped = true;
            }else if (kind == "welcome"){                   //  'Welcome to the GO Battle League' (a new season): LET'S GO!
                popups++;
                if (popups > POPUP_TAPS){
                    info.why = "the pop-up 'Welcome to the GO Battle League' does not go away";
                    break;
                }
                std::vector<Vision::Button> green;
                for (const Vision::Button& b : Vision::wide_buttons(shot)){
                    if (b.color == "green"){
                        green.push_back(b);
                    }
                }
                const Point at = !green.empty() ? frac_xy(Vision::button_spot(green[0])) : frac_xy(WELCOME_BUTTON[0], WELCOME_BUTTON[1]);
                host.log(QString("battle: 'Welcome to the GO Battle League' - tapping LET'S GO! at (%1, %2)").arg(at.x).arg(at.y)
                         + (!green.empty() ? QString() : QString(" (the button was not seen: its usual place)")));
                host.save_picture("g_battle_welcome.png", shot);
                host.tap(at.x, at.y);
                tapped = true;
            }else if (kind == "home" && Nav::max_battles_today(lines)){
                //  'You've reached the maximum number of battles for today.' (22 November, after the third set)
                host.save_picture("g_battle_home.png", shot);
                info.why = "the game says: the maximum number of battles for today is reached";
                info.done_today = true;
                break;
            }else if (kind == "home"){
                std::optional<Vision::Button> button = Vision::home_button(shot);       //  orange: claim first; green: BATTLE; none: not in view
                if (!button.has_value() && Vision::home_button_off(shot)){
                    //  The BATTLE button is grey.  First the rewards of the last set have to be collected: the gold tiles with
                    //  COLLECT under them (22 November: two of them); after them the game asks to claim a new rank (the orange
                    //  button, see above), and then a new set starts with a green BATTLE button.  Grey with nothing to collect:
                    //  no set is left today.
                    std::vector<Spot> tiles = Nav::collect_spots(lines, shot.rows);
                    if (tiles.empty()){
                        for (const Vision::Spot& tile : Vision::gold_tiles(shot)){
                            tiles.push_back(Spot{(int)(tile.x * shot.cols), (int)(tile.y * shot.rows)});
                        }
                    }
                    if (!tiles.empty() && collect_taps < COLLECT_TAPS){
                        collect_taps++;
                        host.log(QString("battle: the BATTLE button is grey - collecting a reward first (COLLECT at (%1, %2))")
                                 .arg(tiles[0].first).arg(tiles[0].second));
                        host.save_picture(QString("g_battle_collect_%1.png").arg(collect_taps), shot);
                        host.tap(tiles[0].first, tiles[0].second);
                        tapped = true;
                        continue;
                    }
                    host.save_picture("g_battle_home.png", shot);
                    info.why = "the BATTLE button is grey - the battles of today are done";
                    info.done_today = true;
                    break;
                }
                QString label = Nav::claim_label(lines, k);
                if ((button.has_value() && button->color == "orange") || !label.isEmpty()){
                    claim.taps++;                   //  something has to be claimed before the next battle
                    if (claim.taps > CLAIM_TAPS){
                        info.why = QString("the claim button of the Battle screen was tapped %1 times and is still there").arg(CLAIM_TAPS);
                        break;
                    }
                    Point at;
                    if (button.has_value() && button->color == "orange"){
                        if (label.isEmpty()){
                            label = host.button_label(shot, *button);
                        }
                        at = frac_xy(Vision::button_spot(*button, 0.25));       //  (not its middle: the round X is there)
                    }else{
                        const Spot fallback = Nav::home_button_fallback(0);
                        at = Point{(int)(fallback.first * k), (int)(fallback.second * k)};
                    }
                    host.log(QString("battle: something has to be claimed before the next battle (button '%1') - tapping it at (%2, %3)")
                             .arg(label.isEmpty() ? QString("not read") : label).arg(at.x).arg(at.y));
                    host.save_picture("g_battle_claim.png", shot);
                    host.tap(at.x, at.y);
                    tapped = true;
                    if (claim.since == 0.0){        //  (the screens that follow take their time: allow for them)
                        max_steps += CLAIM_STEPS + CLAIM_TAPS;
                        max_seconds += CLAIM_SECONDS;
                    }
                    claim.since = host.monotonic();
                    claim.steps = 0;
                    claim.idle = 0;
                    claim.catching = 0;
                    scroll_down = 0;
                    continue;
                }
                const QString text = button.has_value() ? host.button_label(shot, *button) : QString();
                if (button.has_value() && (Nav::premium_above(lines, button->y0 * shot.rows) || claim_not(text))){
                    //  scrolled too far: this is the BATTLE button of the premium rewards (it costs a pass)
                    scroll_up++;
                    if (scroll_up > 2){
                        info.why = "only the BATTLE button of the premium rewards is in view - not tapping that one";
                        break;
                    }
                    host.log("battle: the BATTLE button in view is the one of the premium rewards ('"
                             + (text.isEmpty() ? QString("label not read") : text) + "') - not tapping it, scrolling back up");
                    const Point from = frac_xy(0.5, HOME_SCROLL[0][1]);
                    const Point to = frac_xy(0.5, HOME_SCROLL[0][0]);
                    host.swipe(from.x, from.y, to.x, to.y, HOME_SCROLL_MS);
                    tapped = true;
                    continue;
                }
                if (!button.has_value()){
                    //  No button in view.  When a new set starts ('Choose a reward tier ...') the card is longer and the BATTLE
                    //  button is below the lower edge of the screen: scroll down a little, so that the first BATTLE button comes
                    //  into view (the basic rewards) and not the second one.
                    const std::vector<Spot> found = Nav::home_battle_spots(host.ocr_lines(shot, 1500, std::nullopt, 0.8), k);
                    std::vector<Spot> spots;
                    const size_t keep = found.size() > Nav::HOME_BUTTON_FALLBACKS ? found.size() - Nav::HOME_BUTTON_FALLBACKS : 0;
                    for (size_t i = 0; i < keep; i++){
                        if ((double)found[i].second > 0.93 * shot.rows){            //  (BATTLE at the very bottom, not in a sentence)
                            spots.push_back(found[i]);
                        }
                    }
                    if (!spots.empty() && scroll_down == 0 && taps_home < 2){       //  (its label was read: tap that)
                        taps_home++;
                        host.log(QString("battle: tapping the BATTLE button at its label (%1, %2)").arg(spots[0].first).arg(spots[0].second));
                        host.tap(spots[0].first, spots[0].second);
                        tapped = true;
                        continue;
                    }
                    if (scroll_down < 3){
                        const double y_from = HOME_SCROLL[scroll_down][0];
                        const double y_to = HOME_SCROLL[scroll_down][1];
                        scroll_down++;
                        if (scroll_down == 1){
                            host.save_picture("g_battle_home_top.png", shot);
                        }
                        host.log(QString("battle: no BATTLE button in view on the Battle screen (a new set starts?) - scrolling down (%1 of %2)")
                                 .arg(scroll_down).arg(3));
                        const Point from = frac_xy(0.5, y_from);
                        const Point to = frac_xy(0.5, y_to);
                        host.swipe(from.x, from.y, to.x, to.y, HOME_SCROLL_MS);
                        tapped = true;
                        continue;
                    }
                    if (claim.since != 0.0){        //  (after a claim: something that goes on with a tap?)
                        if (after_claim(shot, lines, k)){
                            break;
                        }
                        tapped = true;
                        continue;
                    }
                    host.save_picture("g_battle_home.png", shot);
                    info.why = "the BATTLE button was not found on the Battle screen (see debug/g_battle_home.png)";
                    break;
                }
                if (claim.since != 0.0){
                    host.log("battle: claimed - the BATTLE button is there");
                    claim.since = 0.0;
                }
                taps_home++;
                if (taps_home > HOME_TAPS){
                    info.why = QString("the BATTLE button was tapped %1 times and nothing happened").arg(HOME_TAPS);
                    break;
                }
                if (taps_home == 1){
                    host.save_picture("g_battle_home.png", shot);
                }
                const Point at = frac_xy(Vision::button_spot(*button, taps_home % 2 ? 0.25 : 0.75));       //  (the X is over its middle)
                host.log(QString("battle: tapping the BATTLE button at (%1, %2)").arg(at.x).arg(at.y)
                         + (!text.isEmpty() ? " ('" + text + "')" : QString())
                         + (scroll_down != 0 ? QString(" after scrolling down %1x").arg(scroll_down) : QString()));
                host.tap(at.x, at.y);
                tapped = true;
            }else if (kind == "league"){
                taps_league++;
                const std::vector<Nav::LeagueLine> spots = Nav::league_lines(lines, league);
                if (spots.empty()){
                    host.save_picture("g_battle_leagues.png", shot);
                    info.why = QString("the league '%1' is not on the league list: ").arg(league) + Nav::reads(lines, 120)
                               + " (see debug/g_battle_leagues.png)";
                    break;
                }
                if (taps_league > 2){
                    info.why = QString("the league '%1' was tapped but the party screen did not open").arg(league);
                    break;
                }
                host.log(QString("battle: choosing the league '%1' at (%2, %3)").arg(spots[0].text).arg(spots[0].x).arg(spots[0].y));
                info.chosen = spots[0].text;        //  (the party screen that follows is the one of this league)
                host.tap(spots[0].x, spots[0].y);
            }else if (kind == "exit"){
                cancel_exit(host, lines);
            }else if (kind == "exit_battle"){
                info.why = "a battle is going on (Exit the Trainer Battle?) - not touching it";
                break;
            }else if (claim.since != 0.0 && kind == "other"){       //  the screens after the claim button
                if (after_claim(shot, lines, k)){
                    break;
                }
                tapped = true;
            }else{
                std::optional<Popup> found;
                if (kind == "other" && popups < POPUP_TAPS){
                    found = popup_button(shot, lines);
                }
                if (found.has_value()){
                    popups++;                       //  a pop-up or a result screen with a button that takes it further
                    const QString read = Nav::reads(lines, 60);
                    if (found->text.startsWith("the check mark")){
                        host.log(QString("battle: a result screen is still there (%1) - tapping %2 at (%3, %4)")
                                 .arg(read, found->text).arg(found->at.x).arg(found->at.y));
                    }else{
                        host.log(QString("battle: a screen with a green button (%1) - tapping '%2' at (%3, %4)")
                                 .arg(read, found->text).arg(found->at.x).arg(found->at.y));
                    }
                    host.save_picture(QString("g_battle_popup_%1.png").arg(popups), shot);
                    host.tap(found->at.x, found->at.y);
                    tapped = true;
                }else{                              //  something in the way, or still loading
                    others++;
                    if (others > 6){                //  (the league screens can take a while to load)
                        info.why = QString("an unknown screen (see debug/g_battle_s%1.png)").arg(step);
                        break;
                    }
                    if (!tapped){
                        host.back();
                    }
                }
            }
        }
    }catch (...){
        finally_do();
        throw;
    }
    finally_do();
    if (!info.ok && info.why.isEmpty()){
        info.why = "unknown";
    }
    return info;
}


//  ---- the battles

Run battle_run(Host& host, const std::vector<Battle::Mon>& team, int count){
    Run res;
    int failures = 0;
    const QString league = host.league();
    bool interrupted = false;
    bool unfinished = false;                        //  the last fight ended without a result

    //  The walk back to the map at the end, whatever way the battles ended.
    auto finally_do = [&](){
        if (!interrupted && !(res.leave.has_value() && *res.leave)){
            host.beat();
            if (!host.on_map(host.screenshot())){
                if (!to_map(host, true)){
                    host.log("battle: could not get back to the map - restarting the game");
                    host.restart_game();
                }
            }
        }
    };
    auto done_text = [&](const Loop::Result& fought) -> QString{
        if (fought.result == "win" || fought.result == "loss"){
            return " " + host.day_count(fought.result == "win" ? "won" : "lost");
        }
        return QString();
    };

    try{
        for (int n = 1; n <= count; n++){
            if (host.stop()){
                break;
            }
            host.recheck_shot_mode();               //  (the quiet screens before a battle: a good moment to compare)
            if (unfinished && Loop::fight_on_screen(host)){     //  the last fight ended without a result and a fight is still
                host.log("battle: a fight is on the screen - fighting it");             //  going on (the loop let go of it too
                unfinished = false;                                                      //  early): fight it, the menus do not
                const Loop::Result fought = host.fight(team, {});                       //  lead anywhere from here
                if (!fought.result.isEmpty()){
                    res.fought++;
                    res.wins += fought.result == "win" ? 1 : 0;
                    failures = 0;
                    host.log(QString("battle: battle %1 done: %2 (%3 won of %4)").arg(n).arg(fought.result).arg(res.wins).arg(res.fought)
                             + done_text(fought));
                    host.beat();
                    continue;
                }
                if (host.stop()){
                    break;
                }
            }
            if (host.no_more()){                    //  the time of the run is up: the last fight is done, no new one
                host.log(QString("battle: the run time is up - no new battle after %1").arg(res.fought));
                break;
            }
            const Info info = open_menu(host, true, true, false);
            if (!info.ok){
                host.log("battle: the party screen was not reached: " + info.why);
                res.leave = info.leave;
                res.catch_reward = info.catch_reward;
                if (info.done_today){
                    res.done_today = true;
                    host.mark_battles_done();
                }
                finally_do();
                return res;
            }
            const QStringList words = Nav::league_words(league);
            const QString title = info.title.toUpper();
            bool title_ok = true;
            for (const QString& w : words){
                title_ok = title_ok && title.contains(w);
            }
            //  The title is read with OCR and a word can be missing ('2026 LEAGUE EDITION' for the Great League edition: the bot
            //  went back and fought nothing, 22 November).  When the bot chose the league itself on the list a moment ago, by its
            //  name, this is its party screen - unless the title names another.
            const QString chosen = info.chosen.toUpper();
            const bool names_other = title.contains("ULTRA") || title.contains("MASTER") || title.contains("LITTLE");
            const bool names_first = !words.isEmpty() && title.contains(words[0]);
            const bool other = names_other && !names_first;
            bool chosen_has_all = true;
            for (const QString& w : words){
                chosen_has_all = chosen_has_all && chosen.contains(w);
            }
            const bool by_choice = !title_ok && !chosen.isEmpty() && chosen_has_all && !other;
            title_ok = title_ok || by_choice;
            host.log(QString("battle: party screen '%1' (team seen: %2)")
                     .arg(info.title.isEmpty() ? QString("?") : info.title, info.members.isEmpty() ? QString("not read") : info.members.join(", "))
                     + (by_choice ? QString(" - the league '%1' was chosen on the list just now").arg(info.chosen) : QString())
                     + (title_ok ? QString() : QString(" - this is not '%1', not fighting").arg(league)));
            if (!title_ok){
                break;
            }
            const Spot use = info.use_spots.at(0);
            host.log(QString("battle: battle %1 of %2 - tapping USE THIS PARTY at (%3, %4)").arg(n).arg(count).arg(use.first).arg(use.second));
            host.tap(use.first, use.second);
            std::vector<Point> spots;
            for (const Spot& s : info.use_spots){
                spots.push_back(Point{s.first, s.second});
            }
            const Loop::Result fought = host.fight(team, spots);
            if (!fought.result.isEmpty()){
                res.fought++;
                res.wins += fought.result == "win" ? 1 : 0;
                failures = 0;
                host.log(QString("battle: battle %1 done: %2").arg(n).arg(fought.result) + (fought.gave_up ? QString(" (given up)") : QString())
                         + QString(" (%1 won of %2)").arg(res.wins).arg(res.fought) + done_text(fought));
            }else{
                failures++;
                unfinished = true;
                host.log(QString("battle: battle %1 did not finish normally: %2").arg(n).arg(fought.why.isEmpty() ? QString("no result") : fought.why));
                if (failures >= 2 || fought.why == "stopped"){
                    break;
                }
            }
            host.beat();
        }
    }catch (const Interrupted&){
        interrupted = true;                         //  (Ctrl+C: stop here, do not walk back through the menus - BACK in a running
        throw;                                      //  battle would give it up)
    }catch (...){
        finally_do();
        throw;
    }
    finally_do();
    return res;
}


std::vector<std::pair<QString, std::vector<double>>> flow_constants(){
    return {
        {"BATTLE_NAV_STEPS", {(double)BATTLE_NAV_STEPS}},
        {"BATTLE_NAV_SECONDS", {BATTLE_NAV_SECONDS}},
        {"COLLECT_TAPS", {(double)COLLECT_TAPS}},
        {"CLAIM_TAPS", {(double)CLAIM_TAPS}},
        {"CLAIM_STEPS", {(double)CLAIM_STEPS}},
        {"CLAIM_SECONDS", {CLAIM_SECONDS}},
        {"CLAIM_TAP_ON", {CLAIM_TAP_ON[0], CLAIM_TAP_ON[1]}},
        {"HOME_SCROLL", {HOME_SCROLL[0][0], HOME_SCROLL[0][1], HOME_SCROLL[1][0], HOME_SCROLL[1][1], HOME_SCROLL[2][0], HOME_SCROLL[2][1]}},
        {"HOME_SCROLL_MS", {(double)HOME_SCROLL_MS}},
        {"HOME_TAPS", {(double)HOME_TAPS}},
        {"POPUP_TAPS", {(double)POPUP_TAPS}},
        {"WELCOME_BUTTON", {WELCOME_BUTTON[0], WELCOME_BUTTON[1]}},
        {"MENU_BTN", {(double)MENU_BTN.x, (double)MENU_BTN.y}},
        {"TH_CLASS", {TH_CLASS}},
    };
}


}
}
}
}
