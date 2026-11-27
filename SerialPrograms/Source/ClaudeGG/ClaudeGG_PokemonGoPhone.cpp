/*  Claude GG Pokemon GO Phone (what the fight loop of the Pokemon GO bot is connected to, in C++)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <algorithm>
#include <chrono>
#include <cmath>
#include <stdexcept>
#include <thread>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <QDate>
#include <QDir>
#include <QFile>
#include <QImage>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSaveFile>
#include <QTemporaryDir>
#include "ClaudeGG_PokemonGoPhone.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Phone{

using Loop::map_visible;
using Loop::REF_H;
using Loop::REF_W;
using Loop::VIEW_H;
using Loop::VIEW_W;


double now_seconds(){
    return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}


cv::Mat mat_of(const QImage& picture){
    if (picture.isNull()){
        return cv::Mat();
    }
    const QImage rgb = picture.convertToFormat(QImage::Format_RGB888);
    cv::Mat shared(rgb.height(), rgb.width(), CV_8UC3, const_cast<uchar*>(rgb.constBits()), (size_t)rgb.bytesPerLine());
    cv::Mat bgr;
    cv::cvtColor(shared, bgr, cv::COLOR_RGB2BGR);
    return bgr;
}

cv::Mat canvas_of(const cv::Mat& screen){
    if (screen.empty() || (screen.cols == REF_W && screen.rows == REF_H)){
        return screen;
    }
    cv::Mat out;
    cv::resize(screen, out, cv::Size(REF_W, REF_H), 0, 0,
               (long long)screen.cols * screen.rows >= (long long)REF_W * REF_H ? cv::INTER_AREA : cv::INTER_LINEAR);
    return out;
}


//  ---- the live video

AgentStream::AgentStream(const QString& host, int port, const QString& token, int fps)
    : m_video(host, port, token, fps, VIEW_W)
    , m_started(now_seconds())
{
    m_video.start();
}

AgentStream::~AgentStream(){
    close();
}

bool AgentStream::healthy(){
    if (m_closed){
        return false;
    }
    QImage picture;
    quint64 serial = 0;
    double when = 0;
    if (!m_video.latest(picture, &serial, &when)){
        return m_video.error().isEmpty();       //  (starting up: wait_new() has a time-out of its own)
    }
    return now_seconds() - when < 2.5;
}

bool AgentStream::starting(){
    if (m_closed){
        return false;
    }
    QImage picture;
    quint64 serial = 0;
    double when = 0;
    if (!m_video.latest(picture, &serial, &when)){
        return now_seconds() - m_started < 4.0;
    }
    //  (the agent starts screenrecord again every three minutes: its pictures are back in a second or two)
    return now_seconds() - when < 4.0;
}

bool AgentStream::wait_new(long long seq, double timeout, double not_before, long long& seq_out, double& t, cv::Mat& small){
    const double end = now_seconds() + timeout;
    quint64 after = seq < 0 ? 0 : (quint64)seq;
    for (;;){
        const double left = end - now_seconds();
        if (m_closed || left <= 0){
            return false;
        }
        QImage picture;
        quint64 serial = 0;
        double when = 0;
        if (!m_video.wait_newer(picture, after, (int)std::min(200.0, left * 1000.0) + 1, &serial, &when)){
            continue;
        }
        after = serial;
        if (when < not_before){
            continue;                           //  (taken before the moment that is asked for: a newer one is waited for)
        }
        cv::Mat bgr = mat_of(picture);
        if (bgr.empty()){
            continue;
        }
        if (bgr.cols != VIEW_W || bgr.rows != VIEW_H){
            cv::resize(bgr, bgr, cv::Size(VIEW_W, VIEW_H), 0, 0, cv::INTER_AREA);
        }
        m_frames++;
        m_last = when;
        seq_out = (long long)serial;
        t = when;
        small = bgr;
        return true;
    }
}

QString AgentStream::describe(){
    QImage picture;
    quint64 serial = 0;
    m_video.latest(picture, &serial);
    QString text = QString("%1 pictures of the live video of the agent").arg((qulonglong)serial);
    const QString error = m_video.error();
    if (!error.isEmpty()){
        text += ", " + error;
    }
    return text;
}

void AgentStream::close(){
    if (m_closed.exchange(true)){
        return;
    }
    m_video.stop();
}


//  ---- the touches

AgentFingers::AgentFingers(const MobileAgent& agent, int width, int height, std::function<void(const QString&)> log)
    : m_agent(agent)
    , m_width(width)
    , m_height(height)
    , m_log(std::move(log))
{}

Point AgentFingers::to_real(int x, int y) const{
    const int width = m_width;
    const int height = m_height;
    if (width <= 0 || height <= 0){
        return Point{x, y};
    }
    //  int(round(x * w / REF_W)): the numbers are whole until the division; round() of Python goes to the even one at a half.
    return Point{
        (int)std::nearbyint((double)((long long)x * width) / (double)REF_W),
        (int)std::nearbyint((double)((long long)y * height) / (double)REF_H),
    };
}

void AgentFingers::set_screen(int width, int height){
    m_width = width;
    m_height = height;
}

void AgentFingers::failed(const QString& what, const QString& why){
    if (m_log){
        m_log("battle: " + what + " did not reach the phone: " + why);
    }
}

void AgentFingers::touch(const QString& kind, int x, int y, int ms){
    const Point p = to_real(x, y);
    QString error;
    if (!m_agent.touch(kind, p.x, p.y, ms, &error)){
        failed("a " + kind + " at (" + QString::number(p.x) + ", " + QString::number(p.y) + ")", error);
    }
}

void AgentFingers::tap(int x, int y, int ms){
    touch("press", x, y, std::max(ms, 1));
}

void AgentFingers::quick(int x, int y){
    touch("tap", x, y, 1);
}

void AgentFingers::motion(int x, int y){
    touch("motion", x, y, 80);
}

void AgentFingers::swipes(const std::vector<Stroke>& strokes){
    std::vector<MobileStroke> list;
    for (const Stroke& s : strokes){
        const Point a = to_real(s.x1, s.y1);
        const Point b = to_real(s.x2, s.y2);
        list.push_back(MobileStroke{a.x, a.y, b.x, b.y, std::max(s.ms, 1)});
    }
    //  (the agent takes up to 50 swipes in one command)
    for (size_t at = 0; at < list.size(); at += 50){
        const std::vector<MobileStroke> part(list.begin() + (std::ptrdiff_t)at, list.begin() + (std::ptrdiff_t)std::min(list.size(), at + 50));
        QString error;
        if (!m_agent.swipes(part, &error)){
            failed(QString("%1 swipes").arg(part.size()), error);
            return;
        }
    }
}


//  ---- the files of what the bot learns

namespace{

QJsonObject read_object(const QString& file, bool& ok){
    ok = false;
    QFile in(file);
    if (!in.open(QIODevice::ReadOnly)){
        return QJsonObject();
    }
    QJsonParseError error;
    const QJsonDocument doc = QJsonDocument::fromJson(in.readAll(), &error);
    if (error.error != QJsonParseError::NoError || !doc.isObject()){
        return QJsonObject();
    }
    ok = true;
    return doc.object();
}

bool write_object(const QString& file, const QJsonObject& object){
    QDir().mkpath(QFileInfo(file).absolutePath());
    QSaveFile out(file);
    if (!out.open(QIODevice::WriteOnly)){
        return false;
    }
    out.write(QJsonDocument(object).toJson(QJsonDocument::Indented));
    return out.commit();
}

QJsonArray lines_to_json(const std::vector<Minigame::Line>& lines){
    QJsonArray array;
    for (const Minigame::Line& l : lines){
        array.append(QJsonArray{l.x1, l.y1, l.x2, l.y2});
    }
    return array;
}

std::vector<Minigame::Line> lines_of(const QJsonValue& value){
    std::vector<Minigame::Line> lines;
    for (const QJsonValue& v : value.toArray()){
        const QJsonArray a = v.toArray();
        if (a.size() == 4){
            lines.push_back(Minigame::Line{a.at(0).toDouble(), a.at(1).toDouble(), a.at(2).toDouble(), a.at(3).toDouble()});
        }
    }
    return lines;
}

}

Fight::Known read_seen(const QString& file){
    bool ok = false;
    const QJsonObject all = read_object(file, ok);
    Fight::Known known;
    if (!ok){
        return known;
    }
    //  (as load_seen(): {species: {charged attack: number of battles}}; a file that is not that is no file)
    for (auto it = all.begin(); it != all.end(); ++it){
        if (!it.value().isObject()){
            continue;
        }
        Fight::Counts counts;
        const QJsonObject moves = it.value().toObject();
        for (auto m = moves.begin(); m != moves.end(); ++m){
            if (!m.value().isDouble()){
                return Fight::Known();
            }
            counts.push_back({m.key(), (int)m.value().toDouble()});
        }
        known.push_back({it.key(), counts});
    }
    return known;
}

bool write_seen(const QString& file, const Fight::Known& known){
    QJsonObject all;
    for (const auto& species : known){
        QJsonObject moves;
        for (const auto& move : species.second){
            moves[move.first] = move.second;
        }
        all[species.first] = moves;
    }
    return write_object(file, all);
}

std::map<QString, Minigame::Learned> read_minigames(const QString& file){
    bool ok = false;
    const QJsonObject all = read_object(file, ok);
    std::map<QString, Minigame::Learned> learned;
    for (auto it = all.begin(); it != all.end(); ++it){
        if (!it.value().isObject()){
            continue;
        }
        Minigame::Learned one;
        one.rows = lines_of(it.value().toObject().value("rows"));
        one.gates = lines_of(it.value().toObject().value("gates"));
        learned[it.key()] = one;
    }
    return learned;
}

bool write_minigames(const QString& file, const std::map<QString, Minigame::Learned>& learned){
    QJsonObject all;
    for (const auto& one : learned){
        QJsonObject object;
        object["gates"] = lines_to_json(one.second.gates);
        object["rows"] = lines_to_json(one.second.rows);
        all[one.first] = object;
    }
    return write_object(file, all);
}


//  ---- the host

AgentHost::AgentHost(const QString& address, int port, const QString& token, const Options& options,
                     std::function<void(const QString&)> log, std::function<bool()> stop)
    : m_address(address)
    , m_port(port)
    , m_token(token)
    , m_options(options)
    , m_log(std::move(log))
    , m_stop(std::move(stop))
    , m_agent(address, port, token, 20000)
    , m_reader(options.tesseract)
    , m_aim(options.aim)
{
    MobileInfo info;
    QString error;
    if (m_agent.info(info, &error)){
        m_width = info.width;
        m_height = info.height;
    }else{
        this->log("battle: the phone did not say how big its screen is (" + error + "): the touches are made as if it were the canvas");
    }
    m_fingers = std::make_unique<AgentFingers>(m_agent, m_width, m_height, m_log);
}

AgentHost::~AgentHost(){
    if (m_stream){
        m_stream->close();
    }
}

double AgentHost::monotonic(){
    return now_seconds();
}

void AgentHost::sleep(double seconds){
    const double end = now_seconds() + seconds;
    for (;;){
        const double left = end - now_seconds();
        if (left <= 0 || stop()){
            return;
        }
        std::this_thread::sleep_for(std::chrono::duration<double>(std::min(left, 0.05)));
    }
}

void AgentHost::log(const QString& text){
    if (m_log){
        m_log(text);
    }
}

cv::Mat AgentHost::screenshot(){
    QImage picture;
    QString error;
    if (!m_agent.screen(picture, &error)){
        throw std::runtime_error("the screenshot of the phone failed: " + error.toStdString());
    }
    const cv::Mat screen = mat_of(picture);
    if (screen.cols != m_width || screen.rows != m_height){
        //  (as spin_stop._normalize: the real size is what the screenshot has)
        m_width = screen.cols;
        m_height = screen.rows;
        m_fingers->set_screen(m_width, m_height);
        log(QString("screen size is %1x%2").arg(m_width.load()).arg(m_height.load()));
    }
    return canvas_of(screen);
}

Stream* AgentHost::stream(){
    if (!m_options.video){
        return nullptr;
    }
    if (!m_stream || m_stream->closed()){
        m_stream = std::make_unique<AgentStream>(m_address, m_port, m_token);
    }
    return m_stream.get();
}

std::unique_ptr<Tapper> AgentHost::make_tapper(Point fast, int ms){
    return std::make_unique<ThreadedTapper>(*m_fingers, fast, ms);
}

bool AgentHost::on_map(const cv::Mat& canvas){
    return map_visible(canvas);
}

Nav::Lines AgentHost::ocr_lines(const cv::Mat& img, int y0, std::optional<int> y1, double scale){
    return m_reader.lines(img, y0, y1, scale);
}

QString AgentHost::ocr_line(const cv::Mat& img, int lines){
    return m_reader.line(img, lines);
}

Fight::Known AgentHost::load_seen(){
    return read_seen(m_options.folder + "/battle_seen.json");
}

void AgentHost::save_seen(const Fight::Known& known){
    write_seen(m_options.folder + "/battle_seen.json", known);
}

std::map<QString, Minigame::Learned> AgentHost::load_minigames(){
    return read_minigames(m_options.folder + "/battle_minigame.json");
}

void AgentHost::save_minigames(const std::map<QString, Minigame::Learned>& learned){
    write_minigames(m_options.folder + "/battle_minigame.json", learned);
}

void AgentHost::save_picture(const QString& name, const cv::Mat& img){
    if (m_options.folder.isEmpty() || img.empty()){
        return;
    }
    const QString folder = m_options.folder + "/pictures";
    try{
        QDir().mkpath(folder);
        cv::imwrite((folder + "/" + name).toStdString(), img);
    }catch (const cv::Exception&){
        log("battle: the picture " + name + " could not be saved");
    }
}

bool AgentHost::stop(){
    return m_stop && m_stop();
}

void AgentHost::beat(){
    if (m_hooks.beat){
        m_hooks.beat();
    }
}


//  ---- the walk and the start of the game

double AgentHost::wall(){
    return std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();
}

void AgentHost::tap(int x, int y){
    m_fingers->tap(x, y, 120);
}

void AgentHost::swipe(int x1, int y1, int x2, int y2, int ms){
    m_fingers->swipes({Stroke{x1, y1, x2, y2, ms}});
}

void AgentHost::back(){
    QString error;
    if (!m_agent.key("BACK", &error)){
        throw std::runtime_error("BACK did not reach the phone: " + error.toStdString());
    }
}

std::pair<QString, double> AgentHost::screen_class(const cv::Mat& img){
    std::lock_guard<std::mutex> lock(m_models_lock);
    if (!m_models && !m_models_failed){
        try{
            if (m_options.models.isEmpty()){
                throw std::runtime_error("there is no folder of models");
            }
            m_models = std::make_unique<Models::Models>(m_options.models);
        }catch (const std::exception& e){
            m_models_failed = true;
            log(QString("the screen classifier cannot be used here (%1)").arg(QString::fromUtf8(e.what())));
        }
    }
    if (!m_models){
        return {QString("onbekend"), 0.0};
    }
    try{
        const Models::ScreenGuess guess = m_models->screen(img);
        return {QString::fromStdString(guess.name), guess.score};
    }catch (const std::exception& e){
        m_models_failed = true;
        m_models.reset();
        log(QString("the screen classifier cannot be used here (%1)").arg(QString::fromUtf8(e.what())));
        return {QString("onbekend"), 0.0};
    }
}

void AgentHost::restart_game(){
    Start::restart_game(*this);
}

QString today_text(){
    return QDate::currentDate().toString("yyyy-MM-dd");
}

void AgentHost::mark_battles_done(){
    QJsonObject object;
    object["day"] = today_text();
    if (!write_object(m_options.folder + "/battle_done.json", object)){
        log("battle: could not write down that the battles of today are done");
    }
}

bool AgentHost::battles_done_today() const{
    bool ok = false;
    const QJsonObject object = read_object(m_options.folder + "/battle_done.json", ok);
    return ok && object.value("day").toString() == today_text();
}

std::vector<Battle::Mon> AgentHost::load_team() const{
    return Battle::load_team(m_options.folder + "/battle_team.json");
}

QString AgentHost::day_count(const QString& key){
    return m_hooks.day_count ? m_hooks.day_count(key) : QString();
}

QStringList AgentHost::team_names(){
    return m_hooks.team_names ? m_hooks.team_names() : QStringList();
}

bool AgentHost::no_more(){
    return m_hooks.no_more && m_hooks.no_more();
}

void AgentHost::stop_game(){
    QString error;
    if (!m_agent.app_stop(m_options.package, &error)){
        throw std::runtime_error("closing the game failed: " + error.toStdString());
    }
}

void AgentHost::start_game(){
    m_launch_failed.reset();
    QString error;
    if (!m_agent.app_start(m_options.package, &error)){
        Start::Launch failed;
        failed.running = false;
        failed.code = 1;
        failed.error = error;
        m_launch_failed = failed;
    }
}

Start::Launch AgentHost::start_state(){
    if (m_launch_failed.has_value()){
        return *m_launch_failed;
    }
    MobileLaunch state;
    QString error;
    Start::Launch launch;
    if (!m_agent.app_state(m_options.package, state, &error)){
        launch.running = false;
        launch.code = 1;
        launch.error = error;
        return launch;
    }
    launch.running = state.running;
    launch.code = state.code;
    launch.error = state.error;
    return launch;
}

void AgentHost::start_end(){
    if (!m_launch_failed.has_value()){
        m_agent.app_end(m_options.package);
    }
}


//  ---- the check

int run_phone_checks(QStringList& report){
    int wrong = 0;
    int tried = 0;
    auto check = [&](bool ok, const QString& what){
        tried++;
        if (!ok){
            wrong++;
            report << "FAILED: " + what;
        }
    };

    //  The picture of the agent as a picture of OpenCV: BGR.
    {
        QImage two(2, 1, QImage::Format_RGB888);
        two.setPixelColor(0, 0, QColor(255, 10, 20));
        two.setPixelColor(1, 0, QColor(0, 200, 40));
        const cv::Mat bgr = mat_of(two);
        check(bgr.cols == 2 && bgr.rows == 1 && bgr.type() == CV_8UC3, "the picture of the agent is a 2 x 1 picture of OpenCV");
        check(bgr.at<cv::Vec3b>(0, 0) == cv::Vec3b(20, 10, 255) && bgr.at<cv::Vec3b>(0, 1) == cv::Vec3b(40, 200, 0), "its colours are blue, green, red");
        QImage grey_alpha(2, 1, QImage::Format_ARGB32);
        grey_alpha.fill(QColor(9, 8, 7, 128));
        check(mat_of(grey_alpha).at<cv::Vec3b>(0, 0) == cv::Vec3b(7, 8, 9), "a picture with a channel for see-through gives its colours");
        check(mat_of(QImage()).empty(), "no picture is no picture");
    }
    //  The screenshot on the canvas.
    {
        const cv::Mat big(4416, 3536, CV_8UC3, cv::Scalar(10, 20, 30));
        const cv::Mat small(1104, 884, CV_8UC3, cv::Scalar(10, 20, 30));
        const cv::Mat same(REF_H, REF_W, CV_8UC3, cv::Scalar(10, 20, 30));
        check(canvas_of(big).cols == REF_W && canvas_of(big).rows == REF_H, "a screenshot that is twice as big is brought to the canvas");
        check(canvas_of(small).cols == REF_W && canvas_of(small).rows == REF_H, "a screenshot that is half as big is brought to the canvas");
        check(canvas_of(same).data == same.data, "a screenshot of the size of the canvas is left as it is");
        check(canvas_of(big).at<cv::Vec3b>(5, 5) == cv::Vec3b(10, 20, 30), "and keeps its colours");
        check(canvas_of(cv::Mat()).empty(), "no screenshot stays none");
    }
    //  The canvas to the real screen: int(round(x * w / REF_W)), the even one at a half.
    {
        AgentFingers fingers(MobileAgent("127.0.0.1", 1, ""), 1000, 2200, nullptr);
        const Point middle = fingers.to_real(884, 1104);
        check(middle.x == 500 && middle.y == 1100, "the middle of the canvas is the middle of the screen");
        const Point corner = fingers.to_real(1768, 2208);
        check(corner.x == 1000 && corner.y == 2200, "the corner of the canvas is the corner of the screen");
        AgentFingers halves(MobileAgent("127.0.0.1", 1, ""), 884, 1104, nullptr);
        //  (x * 884 / 1768 is x / 2: 0.5, 1.5, 2.5 and 3.5 come out as 0, 2, 2 and 4 in Python)
        check(halves.to_real(1, 1).x == 0 && halves.to_real(3, 3).x == 2 && halves.to_real(5, 5).x == 2 && halves.to_real(7, 7).x == 4,
              "a half goes to the even one, as round() of Python does");
        check(halves.to_real(1, 1).y == 0 && halves.to_real(3, 3).y == 2 && halves.to_real(5, 5).y == 2, "also for the height");
        AgentFingers unknown(MobileAgent("127.0.0.1", 1, ""), 0, 0, nullptr);
        check(unknown.to_real(12, 34).x == 12 && unknown.to_real(12, 34).y == 34, "a screen of unknown size is taken for the canvas");
        halves.set_screen(1768, 2208);
        check(halves.to_real(5, 7).x == 5 && halves.to_real(5, 7).y == 7, "and a screenshot that says the size changes it");
    }
    //  What is seen of the foes and what the little games learned: written, read back, and the files of gamebot.py read.
    {
        QTemporaryDir folder;
        check(folder.isValid(), "a folder for the files is made");
        const QString seen_file = folder.path() + "/sub/battle_seen.json";
        const Fight::Known seen = {
            {"Dragalge", {{"Gunk Shot", 3}, {"Outrage", 1}, {"first:Gunk Shot", 2}}},
            {"Lanturn", {{"Surf", 5}}},
        };
        check(read_seen(seen_file).empty(), "no file is nothing seen");
        check(write_seen(seen_file, seen), "what is seen is written (in a folder that was not there)");
        check(read_seen(seen_file) == seen, "and is read back as it was");
        //  A file as gamebot.py writes it: json.dump(d, f, indent=1, sort_keys=True).
        {
            QFile out(seen_file);
            check(out.open(QIODevice::WriteOnly | QIODevice::Truncate), "the test file can be written");
            out.write("{\n \"Dragalge\": {\n  \"Gunk Shot\": 3,\n  \"Outrage\": 1,\n  \"first:Gunk Shot\": 2\n },\n \"Lanturn\": {\n  \"Surf\": 5\n }\n}");
        }
        check(read_seen(seen_file) == seen, "the file of gamebot.py is read");
        {
            QFile out(seen_file);
            check(out.open(QIODevice::WriteOnly | QIODevice::Truncate), "the test file can be written");
            out.write("{\"Dragalge\": {\"Outrage\": \"many\"}}");
        }
        check(read_seen(seen_file).empty(), "a file with something else in it is no file");
        {
            QFile out(seen_file);
            check(out.open(QIODevice::WriteOnly | QIODevice::Truncate), "the test file can be written");
            out.write("{not json");
        }
        check(read_seen(seen_file).empty(), "a file that is not JSON is no file");

        const QString game_file = folder.path() + "/battle_minigame.json";
        std::map<QString, Minigame::Learned> learned;
        learned["Ghost"].rows = {{0.25, 0.5, 0.75, 0.5}, {0.1, 0.2, 0.3, 0.4}};
        learned["Ghost"].gates = {{0.29, 0.79, 0.5, 0.79}};
        learned["Flying"].gates = {{0.1, 0.6, 0.9, 0.6}};
        check(write_minigames(game_file, learned), "what the little games learned is written");
        const std::map<QString, Minigame::Learned> back = read_minigames(game_file);
        check(back.size() == 2 && back.at("Ghost").rows == learned["Ghost"].rows && back.at("Ghost").gates == learned["Ghost"].gates
              && back.at("Flying").gates == learned["Flying"].gates && back.at("Flying").rows.empty(), "and is read back as it was");
        {
            QFile out(game_file);
            check(out.open(QIODevice::WriteOnly | QIODevice::Truncate), "the test file can be written");
            out.write("{\n \"Ghost\": {\n  \"gates\": [\n   [\n    0.29,\n    0.79,\n    0.5,\n    0.79\n   ]\n  ],\n  \"rows\": []\n }\n}");
        }
        const std::map<QString, Minigame::Learned> python = read_minigames(game_file);
        check(python.size() == 1 && python.at("Ghost").gates.size() == 1 && python.at("Ghost").gates[0] == Minigame::Line{0.29, 0.79, 0.5, 0.79}
              && python.at("Ghost").rows.empty(), "the file of gamebot.py is read");
        check(read_minigames(folder.path() + "/not-there.json").empty(), "no file is nothing learned");
    }
    report << QString("%1 checks of the pictures, the touches and the files of the phone side, %2 of them failed").arg(tried).arg(wrong);
    return wrong;
}


}
}
}
}
