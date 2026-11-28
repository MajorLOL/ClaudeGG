/*  Claude GG Pokemon GO Bot (Claude GG itself plays Pokémon GO on the phone of the Pi: the steps of the bot over the agent)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  See ClaudeGG_PokemonGoBot.h.
 *
 */

#include <cmath>
#include <future>
#include <stdexcept>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include "ClaudeGG_PokemonGoBot.h"
#include "ClaudeGG_PokemonGoCatch.h"
#include "ClaudeGG_PokemonGoFlow.h"
#include "ClaudeGG_PokemonGoMap.h"
#include "ClaudeGG_PokemonGoRocketFight.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Bot{

namespace{
const double BAG_FULL_WAIT = 30 * 60;               //  s: no spinning after the message that the bag is full (spin_stop.BAG_FULL_WAIT)
const double STEP_ERROR_WAIT = 10;                  //  s after a step that failed (the loop of gamebot.py)
}


std::vector<Detection> PhoneDetector::map(const cv::Mat& img, const cv::Rect& box, double threshold, int top){
    const cv::Rect inside = box & cv::Rect(0, 0, img.cols, img.rows);
    if (inside.width <= 0 || inside.height <= 0){
        return {};
    }
    return m_phone.map_objects(img(inside), threshold, top);
}


Switches playable(const Switches& asked){
    Switches out = asked;
    //  Not ported yet: off, so that the steps leave them alone.
    for (const char* key : {"daily_cycle", "battle", "teams_weekly"}){
        out[QString::fromLatin1(key)] = false;
    }
    //  The pause for the heat needs temperatures that the agent cannot give yet.
    out["heat_pause"] = false;
    return out;
}


PhoneBot::PhoneBot(Phone::AgentHost& phone, const Switches& switches, const Texts& texts, const QString& folder)
    : m_phone(phone)
    , m_switches(playable(switches))
    , m_texts(texts)
    , m_folder(folder)
    , m_detector(phone)
    , m_eyes(m_detector)
    , m_random(std::random_device{}())
{
    m_map.catching = m_switches["catch"];
    m_map.spin = m_switches["spin"];
    //  What the throws learned before (load_cal()).
    if (!m_folder.isEmpty()){
        QFile file(m_folder + "/gamebot_throw.json");
        if (file.open(QIODevice::ReadOnly)){
            const QJsonObject saved = QJsonDocument::fromJson(file.readAll()).object();
            if (Throw::cal_load(m_memory.cal, saved)){
                log("throw: what was learned of the throws is taken from gamebot_throw.json");
            }
        }
    }
}

PhoneBot::~PhoneBot(){
    std::lock_guard<std::mutex> lock(m_running_lock);
    for (auto& one : m_running){
        if (one.second->thread.joinable()){
            one.second->thread.join();
        }
    }
}

cv::Mat PhoneBot::quick_screenshot(){
    cv::Mat img = m_phone.screenshot();
    m_quick_t = monotonic();
    return img;
}

void PhoneBot::timers(){
    if (m_spin_at.has_value() && wall() >= *m_spin_at){
        m_spin_at.reset();
        m_map.spin = m_switches["spin"];
        m_map.bag_is_full = false;
        log("spinning PokéStops again (the pause for the full bag is over)");
    }
    if (m_catch_at.has_value() && wall() >= *m_catch_at){
        m_catch_at.reset();
        Step::resume_catching(*this, m_map);
    }
}

QString PhoneBot::counts() const{
    return QString("(this run: %1 stops, %2 caught, %3 fled)").arg(m_stops).arg(m_caught).arg(m_fled);
}

double PhoneBot::uniform(double lo, double hi){
    return std::uniform_real_distribution<double>(lo, hi)(m_random);
}
double PhoneBot::unit(){
    return std::uniform_real_distribution<double>(0.0, 1.0)(m_random);
}

bool PhoneBot::setting(const QString& key, bool fallback){
    const auto it = m_switches.find(key);
    return it == m_switches.end() ? fallback : it->second;
}
bool PhoneBot::wanted(const QString& key){
    //  (gamebot.wanted(): on when the web interface does not say; the two of the daily run and the full storage are off then.)
    const auto it = m_switches.find(key);
    if (it == m_switches.end()){
        return key != "spin_only_when_full" && key != "daily_cycle";
    }
    return it->second;
}

QString PhoneBot::count(const QString& key){
    if (key == "stops"){
        m_stops++;
    }else if (key == "caught"){
        m_caught++;
    }else if (key == "fled"){
        m_fled++;
    }
    return counts();
}

void PhoneBot::gifts_round(){
    Gifts::gifts_round(*this);
}
bool PhoneBot::quests_due(const cv::Mat& img){
    return Quests::quests_due(*this, m_quests, img);
}
QString PhoneBot::claim_quests(){
    return Quests::claim_quests(*this, m_quests);
}
QString PhoneBot::screen_state(const cv::Mat& small){
    return Loop::fight_state(*this, small);
}
void PhoneBot::rocket_fight(){
    RocketFight::rocket_fight(*this);
}
void PhoneBot::check_menu_full(){
    Bag::check_menu_full(*this, m_map);
}
void PhoneBot::check_all_full(){
    Bag::check_all_full(*this, m_map);
}
int PhoneBot::clean_bag(){
    return Bag::clean_bag(*this, m_bag);
}
void PhoneBot::bag_to_map(){
    Bag::bag_to_map(*this);
}

QString PhoneBot::shell(const QStringList& args){
    QStringList words = args;
    if (!words.isEmpty() && words.front() == "adb"){
        words.pop_front();
    }
    if (!words.isEmpty() && words.front() == "shell"){
        words.pop_front();
    }
    QString error;
    if (words.size() == 3 && words[0] == "am" && words[1] == "force-stop"){
        if (words[2] != m_phone.package()){
            throw std::runtime_error("only the Pokémon GO app that is played can be closed: " + words[2].toStdString());
        }
        if (!m_phone.agent().app_stop(words[2], &error)){
            throw std::runtime_error("closing the game failed: " + error.toStdString());
        }
        return QString();
    }
    if (words.size() == 3 && words[0] == "input" && words[1] == "keyevent" && words[2].startsWith("KEYCODE_")){
        if (!m_phone.agent().key(words[2].mid(8), &error)){
            throw std::runtime_error(("the key " + words[2] + " did not reach the phone: " + error).toStdString());
        }
        return QString();
    }
    if (words.size() == 2 && words[0] == "pidof"){
        //  gamebot.py waits here until the game runs again; the agent cannot say whether it does, so the bot ends the run.
        log("the game is closed and the agent cannot tell when it is open again: the bot stops here - start it again when the game is open");
        throw Flow::Interrupted();
    }
    throw std::runtime_error("not a command that the agent can give the phone: " + words.join(" ").toStdString());
}

QJsonValue PhoneBot::bag_keep_saved(){
    const auto it = m_texts.find("bag_keep");
    if (it == m_texts.end()){
        return QJsonValue();
    }
    const QJsonDocument doc = QJsonDocument::fromJson(it->second.toUtf8());
    return doc.isObject() ? QJsonValue(doc.object()) : QJsonValue();
}

void PhoneBot::run_done(){
    log("the daily run is over for today (the daily run itself is not in Claude GG yet)");
}

std::optional<QByteArray> PhoneBot::gift_state_read(const QString& file){
    if (m_folder.isEmpty()){
        const auto it = m_files.find(file);
        return it == m_files.end() ? std::nullopt : std::optional<QByteArray>(it->second);
    }
    QFile in(m_folder + "/" + file);
    if (!in.open(QIODevice::ReadOnly)){
        return std::nullopt;
    }
    return in.readAll();
}

void PhoneBot::gift_state_write(const QString& file, const QByteArray& json){
    if (m_folder.isEmpty()){
        m_files[file] = json;
        return;
    }
    QFile out(m_folder + "/" + file);
    if (!out.open(QIODevice::WriteOnly | QIODevice::Truncate)){
        log("gifts: the memory of the day cannot be written to " + out.fileName());
        return;
    }
    out.write(json);
}

void PhoneBot::resume_spin_later(){
    m_spin_at = wall() + BAG_FULL_WAIT;
}

double PhoneBot::throw_ball(std::optional<bool>& hit){
    const double t = Throw::throw_ball(*this, m_memory);
    hit = m_memory.hit;
    return t;
}

QString PhoneBot::ball(){
    const QString chosen = setting_text("ball", "poke").toLower();
    return chosen == "great" || chosen == "ultra" ? chosen : QString("poke");
}

QStringList PhoneBot::berry_order(){
    const auto it = m_texts.find("berries");
    if (it == m_texts.end()){
        return {"pinap", "razz", "nanab"};              //  BERRY_ORDER of gamebot.py
    }
    QStringList out;
    for (const QString& one : it->second.split(',', Qt::SkipEmptyParts)){
        out << one.trimmed().toLower();
    }
    return out;
}

Point PhoneBot::to_real(double x, double y){
    const int width = m_phone.screen_width();
    const int height = m_phone.screen_height();
    if (width <= 0 || height <= 0){
        return Point{(int)std::nearbyint(x), (int)std::nearbyint(y)};
    }
    //  int(round(x * w / REF_W)) of spin_stop.to_real (round() goes to the even one at a half, as nearbyint does).
    return Point{(int)std::nearbyint(x * width / Loop::REF_W), (int)std::nearbyint(y * height / Loop::REF_H)};
}

double PhoneBot::gauss(double mu, double sigma){
    return std::normal_distribution<double>(mu, sigma)(m_random);
}

QString PhoneBot::setting_text(const QString& key, const QString& fallback){
    const auto text = m_texts.find(key);
    if (text != m_texts.end()){
        return text->second;
    }
    const auto on = m_switches.find(key);
    if (on != m_switches.end()){
        return on->second ? "True" : "False";               //  str() of a yes or no of Python
    }
    return fallback;
}

Throw::Later PhoneBot::screenshot_later(){
    std::shared_future<cv::Mat> shot = std::async(std::launch::async, [this]{ return m_phone.screenshot(); }).share();
    return [shot]{ return shot.get(); };
}

QString PhoneBot::send(const QStringList& args){
    //  The commands of the throw (see Throw::touch_line(), aim()): "input swipe x1 y1 x2 y2 ms", "input motionevent ACTION x y", or a
    //  shell line with motionevents.  The places are on the real screen already.
    QStringList words = args;
    if (!words.isEmpty() && words.front() == "adb"){
        words.pop_front();
    }
    if (!words.isEmpty() && words.front() == "shell"){
        words.pop_front();
    }
    const QString line = words.join(" ");
    QString error;
    static const QRegularExpression swipe_re("^input swipe (\\d+) (\\d+) (\\d+) (\\d+) (\\d+)$");
    const QRegularExpressionMatch swipe = swipe_re.match(line.trimmed());
    if (swipe.hasMatch()){
        if (!m_phone.agent().swipe(swipe.captured(1).toInt(), swipe.captured(2).toInt(), swipe.captured(3).toInt(), swipe.captured(4).toInt(),
                                   swipe.captured(5).toInt(), &error)){
            throw std::runtime_error("the swipe did not reach the phone: " + error.toStdString());
        }
        return QString();
    }
    static const QRegularExpression touch_re("motionevent (DOWN|MOVE|UP) (\\d+) (\\d+)");
    std::vector<MobileTouch> events;
    QRegularExpressionMatchIterator it = touch_re.globalMatch(line);
    while (it.hasNext()){
        const QRegularExpressionMatch m = it.next();
        events.push_back(MobileTouch{m.captured(1), m.captured(2).toInt(), m.captured(3).toInt()});
    }
    if (events.empty()){
        throw std::runtime_error("not a command that the agent can give the phone: " + line.toStdString());
    }
    QString out;
    if (!m_phone.agent().touch(events, out, &error)){
        throw std::runtime_error("the touch did not reach the phone: " + error.toStdString());
    }
    return out;
}

int PhoneBot::adb_start(const QStringList& argv, bool capture){
    (void)capture;
    std::lock_guard<std::mutex> lock(m_running_lock);
    const int handle = m_next_handle++;
    std::unique_ptr<Running> running = std::make_unique<Running>();
    Running* slot = running.get();
    slot->thread = std::thread([this, argv, slot]{
        try{
            slot->out = send(argv);
        }catch (const std::exception& e){
            slot->error = QString::fromUtf8(e.what());
        }
    });
    m_running.emplace(handle, std::move(running));
    return handle;
}

QString PhoneBot::adb_communicate(int handle){
    std::unique_ptr<Running> running;
    {
        std::lock_guard<std::mutex> lock(m_running_lock);
        const auto it = m_running.find(handle);
        if (it == m_running.end()){
            return QString();
        }
        running = std::move(it->second);
        m_running.erase(it);
    }
    if (running->thread.joinable()){
        running->thread.join();
    }
    //  (an error of the agent is what the phone "wrote": the throw looks for the words of a phone that does not know touch events)
    return running->error.isEmpty() ? running->out : running->error;
}

void PhoneBot::adb_wait(int handle){
    adb_communicate(handle);
}

void PhoneBot::adb(const QStringList& args){
    send(args);
}

std::pair<double, double> PhoneBot::throw_params(double cx, double cy, double w, double h){
    const std::optional<std::pair<double, double>> p = m_phone.throw_params(cx, cy, w, h);
    return p.has_value() ? *p : std::make_pair(Throw::THROW_FALLBACK_DY, Throw::THROW_FALLBACK_MS);
}

void PhoneBot::save_cal(const Throw::Cal& cal){
    if (m_folder.isEmpty()){
        return;
    }
    QFile file(m_folder + "/gamebot_throw.json");
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate)){
        log("throw: what was learned cannot be written to " + file.fileName());
        return;
    }
    file.write(QJsonDocument(Throw::cal_file(cal)).toJson(QJsonDocument::Indented));
}

std::pair<std::optional<double>, std::optional<double>> PhoneBot::read_heat(){
    if (!m_told_heat){
        m_told_heat = true;
        log("the temperatures of the phone and the Pi cannot be read through the agent yet: no pause when it gets hot");
    }
    return {std::nullopt, std::nullopt};
}

cv::Mat PhoneBot::quick_screenshot_grab(const std::function<void()>& on_grab){
    cv::Mat img = m_phone.screenshot();
    if (on_grab){
        try{
            on_grab();
        }catch (const Flow::Interrupted&){
            throw;
        }catch (const std::exception& e){
            log(QString("action after the screenshot failed: ") + QString::fromUtf8(e.what()));
        }
    }
    return img;
}

double PhoneBot::do_map(const cv::Mat& img){
    return Map::do_map(*this, m_map, m_eyes, img);
}
double PhoneBot::do_pokestop(const cv::Mat& img){
    return Map::do_pokestop(*this, m_map, img);
}
double PhoneBot::do_encounter(const cv::Mat& img){
    if (m_map.catching && wanted("catch")){
        return Catch::do_encounter(*this, m_map, img);
    }
    //  Not catching (only spinning, or the storage is full): the catch screen opened anyway (a Pokémon came up by itself, or was tapped
    //  by the person).
    log("catch screen, but catching is off - running away");
    tap(Catch::RUN_BTN.x, Catch::RUN_BTN.y);
    Map::reset_encounter(*this, m_map);
    return 3;
}

void PhoneBot::resume_catch_later(double seconds){
    m_catch_at = wall() + seconds;
}


void run(PhoneBot& bot, const std::function<void()>& beat){
    while (!bot.stop()){
        bot.timers();
        double wait;
        try{
            wait = Step::step(bot, bot.map_state(), bot.step_state());
        }catch (const Flow::Interrupted&){
            throw;
        }catch (const std::exception& e){
            if (bot.stop()){
                break;
            }
            bot.log(QString("error: ") + QString::fromUtf8(e.what()));
            wait = STEP_ERROR_WAIT;
        }
        if (beat){
            beat();
        }
        bot.sleep(wait);
    }
    throw Flow::Interrupted();
}


}
}
}
}
