/*  Claude GG Pokemon GO Models (the RegiBot networks that read the screen of the game)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port to C++ of Brain in Mobile/gamebot.py: see the header.
 *
 */

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <onnxruntime_cxx_api.h>
#include <QFile>
#include <QHash>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include "ML/Models/ML_OrtEnv.h"
#include "ClaudeGG_PokemonGoModels.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Models{


const int FRAME_W = 1768;
const int FRAME_H = 2208;

const char* const FILE_CLASSIFIER = "model_classifier_screen_v5.onnx";
const char* const FILE_MAP = "model_detector_map_v2.onnx";
const char* const FILE_CLICKABLE = "model_detector_clickable_v2.onnx";
const char* const FILE_PREDICTOR = "predictor.onnx";
const char* const FILE_MAP_ANCHORS = "model_detector_map_v2_anchors.f32";
const char* const FILE_CLICKABLE_ANCHORS = "model_detector_clickable_v2_anchors.f32";


namespace{


const char* const SCREENS[9] = {
    "areneScreen", "eggScreen", "encounterScreen", "mapScreen", "menusScreen",
    "pokestopScreen", "rewardScreen", "rocketScreen", "summaryScreen",
};
const std::vector<std::string> MAP_LABELS = {
    "background", "gym", "pokemon", "pokestop", "rocket_pokestop", "unable_pokestop",
};
const std::vector<std::string> CLICK_LABELS = {"background", "clickable", "passenger"};

const size_t ANCHORS = 27621;               //  boxes of both detectors
const int DETECTOR_SIZE = 384;              //  the picture of a detector, in pixels, both ways
const int CLASSIFIER_SIZE = 224;
const int CLASSIFIER_FIRST_SIZE = 256;      //  the classifier's picture is made 256 x 256 first
const size_t MOST_BEFORE_NMS = 200;
const double TOO_BIG = 0.6;                 //  a box wider or higher than this share of the picture is nonsense
const double NMS_OVERLAP = 0.5;


std::basic_string<ORTCHAR_T> ort_path(const QString& path){
#ifdef _WIN32
    return path.toStdWString();
#else
    return path.toStdString();
#endif
}


//  One network: its file is opened once, a call is one run.
class Net{
public:
    struct Output{
        std::vector<int64_t> shape;
        std::vector<float> data;
    };

    explicit Net(const QString& path)
        : m_session(make_session(path))
    {
        Ort::AllocatorWithDefaultOptions allocator;
        m_input = m_session.GetInputNameAllocated(0, allocator).get();
        const size_t outputs = m_session.GetOutputCount();
        for (size_t c = 0; c < outputs; c++){
            m_outputs.emplace_back(m_session.GetOutputNameAllocated(c, allocator).get());
        }
    }

    std::vector<Output> run(std::vector<float>& input, const std::vector<int64_t>& shape){
        Ort::MemoryInfo memory = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
        Ort::Value tensor = Ort::Value::CreateTensor<float>(
            memory, input.data(), input.size(), shape.data(), shape.size()
        );
        const char* input_names[] = {m_input.c_str()};
        std::vector<const char*> output_names;
        for (const std::string& name : m_outputs){
            output_names.push_back(name.c_str());
        }
        std::vector<Ort::Value> result = m_session.Run(
            Ort::RunOptions{nullptr}, input_names, &tensor, 1, output_names.data(), output_names.size()
        );
        std::vector<Output> out;
        for (const Ort::Value& value : result){
            const auto info = value.GetTensorTypeAndShapeInfo();
            Output one;
            one.shape = info.GetShape();
            const float* data = value.GetTensorData<float>();
            one.data.assign(data, data + info.GetElementCount());
            out.push_back(std::move(one));
        }
        return out;
    }

private:
    static Ort::Session make_session(const QString& path){
        Ort::SessionOptions options;
        //  The program's one ONNX Runtime has its own pool of threads (global_ort_env).
        options.DisablePerSessionThreads();
        return Ort::Session(global_ort_env(), ort_path(path).c_str(), options);
    }

    Ort::Session m_session;
    std::string m_input;
    std::vector<std::string> m_outputs;
};


std::vector<float> read_floats(const QString& path, size_t count){
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)){
        throw std::runtime_error("cannot open " + path.toStdString());
    }
    const QByteArray bytes = file.readAll();
    if (static_cast<size_t>(bytes.size()) != count * sizeof(float)){
        throw std::runtime_error(path.toStdString() + " is not " + std::to_string(count) + " floats long");
    }
    std::vector<float> out(count);
    std::memcpy(out.data(), bytes.constData(), count * sizeof(float));
    return out;
}


//  A picture as the network wants it: the picture made `size` x `size` (a straight line between pixels, as cv2.resize
//  does without a word about it), the channels as R, G, B planes, every value (v - 127.5) / 127.5 for a detector and
//  v / 255 for the classifier.  A value of a 8 bit channel is exact in a float, and the two steps are floats as in NumPy.
std::vector<float> network_input(const cv::Mat& resized, bool detector){
    const int w = resized.cols, h = resized.rows;
    const size_t plane = static_cast<size_t>(w) * static_cast<size_t>(h);
    std::vector<float> out(3 * plane);
    for (int y = 0; y < h; y++){
        const uchar* row = resized.ptr<uchar>(y);
        for (int x = 0; x < w; x++){
            for (int c = 0; c < 3; c++){
                const float v = static_cast<float>(row[3 * x + (2 - c)]);     //  the picture is B, G, R
                out[static_cast<size_t>(c) * plane + static_cast<size_t>(y) * static_cast<size_t>(w) + static_cast<size_t>(x)] =
                    detector ? (v - 127.5f) / 127.5f : v / 255.0f;
            }
        }
    }
    return out;
}


void require_picture(const cv::Mat& bgr){
    if (bgr.empty() || bgr.type() != CV_8UC3){
        throw std::runtime_error("a picture of 8 bit B, G, R is needed");
    }
}


//  int(x) of Python for a float: towards zero (and kept in range: a box that big is thrown away by its size).
int to_int(float x){
    if (!(x > -2e9f)){
        return -2000000000;
    }
    if (!(x < 2e9f)){
        return 2000000000;
    }
    return static_cast<int>(x);
}


RawBoxes run_detector(Net& net, const cv::Mat& bgr){
    require_picture(bgr);
    cv::Mat small;
    cv::resize(bgr, small, cv::Size(DETECTOR_SIZE, DETECTOR_SIZE));
    std::vector<float> input = network_input(small, true);
    std::vector<Net::Output> out = net.run(input, {1, 3, DETECTOR_SIZE, DETECTOR_SIZE});
    RawBoxes raw;
    raw.picture_w = bgr.cols;
    raw.picture_h = bgr.rows;
    bool have_boxes = false, have_scores = false;
    for (Net::Output& one : out){
        if (one.shape.size() != 3 || one.shape[1] != static_cast<int64_t>(ANCHORS)){
            continue;
        }
        if (one.shape[2] == 4 && !have_boxes){
            raw.boxes = std::move(one.data);
            have_boxes = true;
        }else if (one.shape[2] != 4 && !have_scores){
            raw.classes = static_cast<int>(one.shape[2]);
            raw.scores = std::move(one.data);
            have_scores = true;
        }
    }
    if (!have_boxes || !have_scores){
        throw std::runtime_error("a detector did not answer with boxes and scores");
    }
    return raw;
}


//  _nms of gamebot.py: the boxes (best first) without the ones that mostly cover a better box of the same label.
std::vector<Detection> nms(const std::vector<Detection>& boxes){
    std::vector<Detection> keep;
    for (const Detection& b : boxes){
        bool ok = true;
        for (const Detection& k : keep){
            if (k.label != b.label){
                continue;
            }
            const double x1 = std::max(b.cx - b.w / 2.0, k.cx - k.w / 2.0);
            const double y1 = std::max(b.cy - b.h / 2.0, k.cy - k.h / 2.0);
            const double x2 = std::min(b.cx + b.w / 2.0, k.cx + k.w / 2.0);
            const double y2 = std::min(b.cy + b.h / 2.0, k.cy + k.h / 2.0);
            const double inter = std::max(0.0, x2 - x1) * std::max(0.0, y2 - y1);
            const double both = static_cast<double>(b.w) * b.h + static_cast<double>(k.w) * k.h - inter;
            if (both > 0 && inter / both > NMS_OVERLAP){
                ok = false;
                break;
            }
        }
        if (ok){
            keep.push_back(b);
        }
    }
    return keep;
}


}   //  namespace


struct Models::Impl{
    Net classifier;
    Net map;
    Net clickable;
    Net predictor;
    std::vector<float> map_anchors;
    std::vector<float> clickable_anchors;

    explicit Impl(const QString& folder)
        : classifier(folder + "/" + FILE_CLASSIFIER)
        , map(folder + "/" + FILE_MAP)
        , clickable(folder + "/" + FILE_CLICKABLE)
        , predictor(folder + "/" + FILE_PREDICTOR)
        , map_anchors(read_floats(folder + "/" + FILE_MAP_ANCHORS, ANCHORS * 4))
        , clickable_anchors(read_floats(folder + "/" + FILE_CLICKABLE_ANCHORS, ANCHORS * 4))
    {}
};


Models::Models(const QString& folder){
    for (const char* name : {FILE_CLASSIFIER, FILE_MAP, FILE_CLICKABLE, FILE_PREDICTOR, FILE_MAP_ANCHORS, FILE_CLICKABLE_ANCHORS}){
        if (!QFile::exists(folder + "/" + name)){
            throw std::runtime_error(std::string(name) + " is not in " + folder.toStdString());
        }
    }
    try{
        m_impl = std::make_unique<Impl>(folder);
    }catch (const Ort::Exception& e){
        throw std::runtime_error(std::string("ONNX Runtime: ") + e.what());
    }
}

Models::~Models() = default;


ScreenGuess Models::screen(const cv::Mat& bgr) const{
    require_picture(bgr);
    cv::Mat first, small;
    cv::resize(bgr, first, cv::Size(CLASSIFIER_FIRST_SIZE, CLASSIFIER_FIRST_SIZE));
    cv::resize(first, small, cv::Size(CLASSIFIER_SIZE, CLASSIFIER_SIZE));
    std::vector<float> input = network_input(small, false);
    std::vector<Net::Output> out = m_impl->classifier.run(input, {1, 3, CLASSIFIER_SIZE, CLASSIFIER_SIZE});
    if (out.empty() || out[0].data.size() != 9){
        throw std::runtime_error("the screen classifier did not answer with nine certainties");
    }
    ScreenGuess guess;
    guess.probabilities = out[0].data;
    size_t best = 0;
    for (size_t c = 1; c < guess.probabilities.size(); c++){
        if (guess.probabilities[c] > guess.probabilities[best]){
            best = c;
        }
    }
    guess.name = SCREENS[best];
    guess.score = static_cast<double>(guess.probabilities[best]);
    return guess;
}


RawBoxes Models::map_raw(const cv::Mat& bgr) const{
    return run_detector(m_impl->map, bgr);
}

RawBoxes Models::clickable_raw(const cv::Mat& bgr) const{
    return run_detector(m_impl->clickable, bgr);
}

std::vector<Detection> Models::decode_map(const RawBoxes& raw, double threshold, int top) const{
    return decode_detections(raw, m_impl->map_anchors, MAP_LABELS, threshold, top);
}

std::vector<Detection> Models::decode_clickable(const RawBoxes& raw, double threshold, int top) const{
    return decode_detections(raw, m_impl->clickable_anchors, CLICK_LABELS, threshold, top);
}

std::vector<Detection> Models::map_objects(const cv::Mat& bgr, double threshold, int top) const{
    return decode_map(map_raw(bgr), threshold, top);
}

std::vector<Detection> Models::buttons(const cv::Mat& bgr, double threshold, int top) const{
    return decode_clickable(clickable_raw(bgr), threshold, top);
}


ThrowParams Models::throw_params(double cx, double cy, double w, double h) const{
    std::vector<float> input = {
        static_cast<float>(cx / FRAME_W), static_cast<float>(cy / FRAME_H),
        static_cast<float>(w / FRAME_W), static_cast<float>(h / FRAME_H),
    };
    std::vector<Net::Output> out = m_impl->predictor.run(input, {1, 4});
    if (out.empty() || out[0].data.size() != 2){
        throw std::runtime_error("the throw predictor did not answer with two numbers");
    }
    return {static_cast<double>(out[0].data[0]) * FRAME_H, static_cast<double>(out[0].data[1]) * 1000};
}


//  Brain._ssd of gamebot.py from the answer of the network on: the class with the best certainty of every box (the
//  background, class 0, does not count), the boxes at the threshold or above, the best 200 (equal certainties keep the
//  order of the boxes), decoded with the anchors, the far too big ones out, the overlapping ones out, the best `top`.
std::vector<Detection> decode_detections(
    const RawBoxes& raw,
    const std::vector<float>& anchors,
    const std::vector<std::string>& labels,
    double threshold, int top
){
    std::vector<Detection> found;
    if (raw.classes < 2 || raw.boxes.empty() || raw.scores.size() != raw.boxes.size() / 4 * static_cast<size_t>(raw.classes) ||
        anchors.size() != raw.boxes.size() || labels.size() != static_cast<size_t>(raw.classes) || top <= 0
    ){
        return found;
    }
    const size_t boxes = raw.boxes.size() / 4;
    const size_t classes = static_cast<size_t>(raw.classes);
    const float limit = static_cast<float>(threshold);
    std::vector<size_t> best_class(boxes);
    std::vector<float> best_score(boxes);
    std::vector<size_t> chosen;
    for (size_t n = 0; n < boxes; n++){
        const float* row = &raw.scores[n * classes];
        size_t best = 1;
        for (size_t c = 2; c < classes; c++){
            if (row[c] > row[best]){
                best = c;
            }
        }
        best_class[n] = best;
        best_score[n] = row[best];
        if (row[best] >= limit){
            chosen.push_back(n);
        }
    }
    std::stable_sort(chosen.begin(), chosen.end(), [&](size_t a, size_t b){
        return best_score[a] > best_score[b];
    });
    if (chosen.size() > MOST_BEFORE_NMS){
        chosen.resize(MOST_BEFORE_NMS);
    }

    const float w0 = static_cast<float>(raw.picture_w);
    const float h0 = static_cast<float>(raw.picture_h);
    for (size_t n : chosen){
        const float ax = anchors[4 * n], ay = anchors[4 * n + 1], aw = anchors[4 * n + 2], ah = anchors[4 * n + 3];
        const float yc = raw.boxes[4 * n], xc = raw.boxes[4 * n + 1], hh = raw.boxes[4 * n + 2], ww = raw.boxes[4 * n + 3];
        const float cx = (xc * aw + ax) * w0;
        const float cy = (yc * ah + ay) * h0;
        const float bw = std::exp(ww) * aw * w0;
        const float bh = std::exp(hh) * ah * h0;
        Detection one{labels[best_class[n]], static_cast<double>(best_score[n]), to_int(cx), to_int(cy), to_int(bw), to_int(bh)};
        if (one.w < TOO_BIG * raw.picture_w && one.h < TOO_BIG * raw.picture_h){
            found.push_back(std::move(one));
        }
    }
    found = nms(found);
    if (found.size() > static_cast<size_t>(top)){
        found.resize(static_cast<size_t>(top));
    }
    return found;
}


//  ---- the check against models_golden.json ---------------------------------------------------------------------------

namespace{


struct Margins{
    double score = 1e-4;
    int pixel = 1;
    double throw_ = 0.01;
};


//  The lines of the detections of the golden file and of the port, to put in a message.
QString describe(const std::vector<Detection>& list){
    QStringList parts;
    for (const Detection& d : list){
        parts << QString("%1 %2 (%3, %4) %5x%6")
            .arg(QString::fromStdString(d.label)).arg(d.score, 0, 'f', 4).arg(d.cx).arg(d.cy).arg(d.w).arg(d.h);
    }
    return "[" + parts.join("; ") + "]";
}


std::vector<Detection> detections_of(const QJsonArray& found){
    std::vector<Detection> out;
    for (const QJsonValue& value : found){
        const QJsonArray a = value.toArray();
        out.push_back(Detection{
            a.at(0).toString().toStdString(), a.at(1).toDouble(),
            a.at(2).toInt(), a.at(3).toInt(), a.at(4).toInt(), a.at(5).toInt(),
        });
    }
    return out;
}


//  What differs between what the TFLite models said (want) and what this port says (got), empty when it is the same.
QString detections_differ(const std::vector<Detection>& want, const std::vector<Detection>& got, const Margins& margins){
    bool same = want.size() == got.size();
    for (size_t n = 0; same && n < want.size(); n++){
        same = want[n].label == got[n].label
            && std::abs(want[n].score - got[n].score) <= margins.score
            && std::abs(want[n].cx - got[n].cx) <= margins.pixel
            && std::abs(want[n].cy - got[n].cy) <= margins.pixel
            && std::abs(want[n].w - got[n].w) <= margins.pixel
            && std::abs(want[n].h - got[n].h) <= margins.pixel;
    }
    if (same){
        return QString();
    }
    return QString("the models say %1, the port says %2").arg(describe(want).left(400)).arg(describe(got).left(400));
}


//  The little generator of numbers that make_models_golden.py has too (a linear congruential one of 64 bits, the top 31).
class Lcg{
public:
    explicit Lcg(uint64_t seed) : m_state(seed){}
    uint32_t next(){
        m_state = m_state * 6364136223846793005ULL + 1442695040888963407ULL;
        return static_cast<uint32_t>(m_state >> 33);
    }
private:
    uint64_t m_state;
};


//  The answer of a network that never was (see made_up_answer() in make_models_golden.py): most certainties low, a few
//  high, all from short lists of values, so that many are equal.
RawBoxes made_up_answer(uint64_t seed, int classes, int picture_w, int picture_h){
    Lcg g(seed);
    RawBoxes raw;
    raw.picture_w = picture_w;
    raw.picture_h = picture_h;
    raw.classes = classes;
    raw.boxes.resize(ANCHORS * 4);
    raw.scores.resize(ANCHORS * static_cast<size_t>(classes));
    for (size_t n = 0; n < ANCHORS; n++){
        for (size_t j = 0; j < 4; j++){
            raw.boxes[4 * n + j] = j < 2
                ? static_cast<float>((static_cast<double>(g.next() % 2001) - 1000.0) / 10000.0)
                : static_cast<float>((static_cast<double>(g.next() % 1001) - 500.0) / 1000.0);
        }
        for (size_t c = 0; c < static_cast<size_t>(classes); c++){
            const uint32_t r = g.next();
            raw.scores[n * static_cast<size_t>(classes) + c] = static_cast<float>(
                (r >> 10) % 25 == 0 ? static_cast<double>(r % 100) / 100.0 : static_cast<double>(r % 16) / 160.0
            );
        }
    }
    return raw;
}


cv::Mat load_picture(const QString& path){
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)){
        return cv::Mat();
    }
    const QByteArray bytes = file.readAll();
    const std::vector<uchar> buffer(bytes.begin(), bytes.end());
    return cv::imdecode(buffer, cv::IMREAD_COLOR);
}


}   //  namespace


int run_models_checks(const QString& golden, const QString& fixtures, const QString& models, QStringList& report){
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the answers of the models are not there: " + golden;
        return 1;
    }
    const QJsonObject root = QJsonDocument::fromJson(file.readAll()).object();
    const QJsonArray cases = root.value("cases").toArray();
    const QJsonArray throws = root.value("throws").toArray();
    if (cases.isEmpty() || throws.isEmpty()){
        report << "FAILED: the file with the answers of the models is empty or not right: " + golden;
        return 1;
    }
    Margins margins;
    margins.score = root.value("score_tol").toDouble(margins.score);
    margins.pixel = root.value("pixel_tol").toInt(margins.pixel);
    margins.throw_ = root.value("throw_tol").toDouble(margins.throw_);

    std::unique_ptr<Models> net;
    try{
        net = std::make_unique<Models>(models);
    }catch (const std::exception& e){
        report << QString("FAILED: the models cannot be opened: %1").arg(e.what());
        return 1;
    }

    int wrong = 0;
    const auto fail = [&](const QString& what){
        wrong++;
        if (wrong <= 12){
            report << "FAILED: " + what;
        }
    };

    QHash<QString, cv::Mat> pictures;
    try{
        for (qsizetype index = 0; index < cases.size(); index++){
            const QJsonObject one = cases[index].toObject();
            const QString name = one.value("picture").toString();
            if (!pictures.contains(name)){
                pictures.insert(name, load_picture(fixtures + "/" + name));
            }
            cv::Mat img = pictures.value(name);
            if (img.empty()){
                fail(QString("picture %1: %2 is not in %3").arg(index).arg(name).arg(fixtures));
                continue;
            }
            const QJsonArray cut = one.value("cut").toArray();
            if (cut.size() == 4){
                const int x0 = std::max(cut.at(0).toInt(), 0), y0 = std::max(cut.at(1).toInt(), 0);
                const int x1 = std::min(cut.at(2).toInt(), img.cols), y1 = std::min(cut.at(3).toInt(), img.rows);
                if (x1 <= x0 || y1 <= y0){
                    fail(QString("picture %1: the cut-out of %2 is empty").arg(index).arg(name));
                    continue;
                }
                img = img(cv::Rect(x0, y0, x1 - x0, y1 - y0));
            }
            const QString where = QString("picture %1 (%2%3)").arg(index).arg(name).arg(cut.isEmpty() ? "" : ", cut out");

            //  the classifier
            const QJsonObject screen = one.value("screen").toObject();
            const ScreenGuess guess = net->screen(img);
            if (QString::fromStdString(guess.name) != screen.value("label").toString()){
                fail(QString("%1: the screen is %2 for the models and %3 for the port")
                    .arg(where).arg(screen.value("label").toString()).arg(QString::fromStdString(guess.name)));
            }else{
                const QJsonArray probabilities = screen.value("probs").toArray();
                bool same = static_cast<size_t>(probabilities.size()) == guess.probabilities.size();
                for (qsizetype c = 0; same && c < probabilities.size(); c++){
                    same = std::abs(probabilities.at(c).toDouble() - static_cast<double>(guess.probabilities[static_cast<size_t>(c)])) <= margins.score;
                }
                if (!same){
                    fail(where + ": the certainties of the screen classifier differ by more than the margin");
                }
            }

            //  the detectors: one run, then every look at it
            for (const char* kind : {"map", "clickable"}){
                const bool is_map = std::strcmp(kind, "map") == 0;
                const RawBoxes raw = is_map ? net->map_raw(img) : net->clickable_raw(img);
                for (const QJsonValue& look_value : one.value(kind).toArray()){
                    const QJsonObject look = look_value.toObject();
                    const double th = look.value("th").toDouble();
                    const int top = look.value("top").toInt();
                    const std::vector<Detection> got = is_map ? net->decode_map(raw, th, top) : net->decode_clickable(raw, th, top);
                    const QString difference = detections_differ(detections_of(look.value("found").toArray()), got, margins);
                    if (!difference.isEmpty()){
                        fail(QString("%1: the %2 detector at %3 (best %4): %5").arg(where).arg(kind).arg(th).arg(top).arg(difference));
                    }
                }
            }
        }
        //  the choice from the boxes of a detector, on answers that no network gave
        const QJsonArray decode = root.value("decode").toArray();
        for (qsizetype index = 0; index < decode.size(); index++){
            const QJsonObject one = decode[index].toObject();
            const bool is_map = one.value("kind").toString() == "map";
            const RawBoxes raw = made_up_answer(
                static_cast<uint64_t>(one.value("seed").toDouble()), is_map ? 6 : 3,
                one.value("w").toInt(), one.value("h").toInt()
            );
            const double th = one.value("th").toDouble();
            const int top = one.value("top").toInt();
            const std::vector<Detection> got = is_map ? net->decode_map(raw, th, top) : net->decode_clickable(raw, th, top);
            const QString difference = detections_differ(detections_of(one.value("found").toArray()), got, margins);
            if (!difference.isEmpty()){
                fail(QString("made-up answer %1 (%2, seed %3, threshold %4, best %5): %6")
                    .arg(index).arg(one.value("kind").toString()).arg(one.value("seed").toInt()).arg(th).arg(top).arg(difference));
            }
        }
        for (qsizetype index = 0; index < throws.size(); index++){
            const QJsonObject one = throws[index].toObject();
            const QJsonArray in = one.value("in").toArray();
            const ThrowParams got = net->throw_params(in.at(0).toDouble(), in.at(1).toDouble(), in.at(2).toDouble(), in.at(3).toDouble());
            if (std::abs(got.dy_px - one.value("dy").toDouble()) > margins.throw_ ||
                std::abs(got.duration_ms - one.value("ms").toDouble()) > margins.throw_
            ){
                fail(QString("throw %1: the models say %2 px, %3 ms, the port says %4 px, %5 ms")
                    .arg(index).arg(one.value("dy").toDouble()).arg(one.value("ms").toDouble()).arg(got.dy_px).arg(got.duration_ms));
            }
        }
    }catch (const std::exception& e){
        fail(QString("a model could not be run: %1").arg(e.what()));
    }

    if (wrong == 0){
        report << QString("%1 pictures, %2 made-up answers and %3 throws read as the models of gamebot.py read them (within %4 in a certainty and %5 pixel)")
            .arg(cases.size()).arg(root.value("decode").toArray().size()).arg(throws.size()).arg(margins.score).arg(margins.pixel);
    }else{
        report << QString("%1 things differ from what the models of gamebot.py say (%2 pictures, %3 throws)")
            .arg(wrong).arg(cases.size()).arg(throws.size());
    }
    return wrong;
}


}
}
}
}
