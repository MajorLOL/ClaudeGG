/*  Claude GG Pokemon GO Models (the RegiBot networks that read the screen of the game)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  A port to C++ of the way gamebot.py runs the models of RegiBot (issue #30):
 *
 *    screen()        the screen classifier: which of the nine screens of the game
 *                    is this, and how sure is it
 *    map_objects()   the map detector: Pokémon, gyms and PokéStops on a map
 *    buttons()       the detector of what can be clicked
 *    encounter_objects()  the encounter detector: the ring of a Pokémon, its box, the ball
 *    throw_params()  the throw predictor: where and how long to swipe for a ball
 *
 *  The Raspberry Pi runs the TFLite files with LiteRT; this program runs ONNX
 *  copies of them with the ONNX Runtime it already has (Mobile/tools/
 *  convert_models_to_onnx.py makes them and checks them against the originals).
 *  What is around the networks is the Python code step by step: the picture is
 *  made 384 x 384 (224 x 224 for the classifier) with OpenCV, the 27,621 boxes
 *  of a detector are decoded with its anchors the way MediaPipe does (yxhw and
 *  exp, no sigmoid), the best 200 above the threshold are kept, boxes that are
 *  far too big are dropped and boxes of one label that cover each other are
 *  taken out.
 *
 *  The two runtimes do not give the same bits, so the check has a margin:
 *  certainties and scores differ by at most 1e-4, a position or a size by at
 *  most one pixel, a throw by 0.01.  Mobile/tools/make_models_golden.py makes
 *  a file with what the TFLite models say on 110 pictures, on 18 made-up answers of a network (and on 200 throws)
 *  and run_models_checks() holds this port to it in every build (--mobile-test,
 *  when the models are there: see CLAUDEGG_MODELS).
 *
 *  The encounter detector ends in an operation that ONNX has no name for
 *  (TFLite_Detection_PostProcess), so its network is cut in front of it (see
 *  Mobile/tools/convert_models_to_onnx.py) and this port does what that
 *  operation did: decode the 51,150 boxes with the anchors, take the best class
 *  of every box, and keep the 10 best boxes that do not cover each other (the
 *  fast variant of non-maximum suppression, as TensorFlow Lite does it, down to
 *  the order of equal certainties).
 *
 *  Not here yet: the loop that takes the pictures and acts on the answers.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoModels_H
#define PokemonAutomation_ClaudeGG_PokemonGoModels_H

#include <memory>
#include <string>
#include <vector>
#include <opencv2/core.hpp>
#include <QString>
#include <QStringList>

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Models{


//  The canvas of the phone that the throw predictor was made for.
extern const int FRAME_W;
extern const int FRAME_H;

//  The files that Models() needs in its folder.
extern const char* const FILE_CLASSIFIER;       //  model_classifier_screen_v5.onnx
extern const char* const FILE_MAP;              //  model_detector_map_v2.onnx
extern const char* const FILE_CLICKABLE;        //  model_detector_clickable_v2.onnx
extern const char* const FILE_ENCOUNTER;        //  model_detector_encounter.onnx (cut in front of the post-processing)
extern const char* const FILE_PREDICTOR;        //  predictor.onnx
extern const char* const FILE_MAP_ANCHORS;      //  model_detector_map_v2_anchors.f32 (27,621 x 4 floats)
extern const char* const FILE_CLICKABLE_ANCHORS;
extern const char* const FILE_ENCOUNTER_ANCHORS;    //  model_detector_encounter_anchors.f32 (51,150 x 4 floats: y, x, h, w)


//  A box a detector found: the label, how sure it is (0 - 1), the middle and the size in pixels of the picture it looked at.
struct Detection{
    std::string label;
    double score;
    int cx, cy, w, h;
};

//  What the classifier says about a picture: the best screen, its certainty and the certainty of all nine.
struct ScreenGuess{
    std::string name;
    double score;
    std::vector<float> probabilities;
};

//  How to throw: the swipe's length up (in pixels) and how long it takes (in milliseconds).
struct ThrowParams{
    double dy_px;
    double duration_ms;
};

//  What a detector made of a picture, before anything is chosen from it: one row per anchor.
struct RawBoxes{
    int picture_w = 0;
    int picture_h = 0;
    int classes = 0;
    std::vector<float> boxes;       //  n x 4 (y, x, h, w as the network gives them)
    std::vector<float> scores;      //  n x classes
};


class Models{
public:
    //  Opens the networks and the anchors in the folder (throws std::runtime_error with the reason).
    explicit Models(const QString& folder);
    ~Models();
    Models(const Models&) = delete;
    void operator=(const Models&) = delete;

    ScreenGuess screen(const cv::Mat& bgr) const;

    //  Brain._ssd of gamebot.py: the network once (map_raw) and the choice from its answer (decode_map), or both in one.
    RawBoxes map_raw(const cv::Mat& bgr) const;
    RawBoxes clickable_raw(const cv::Mat& bgr) const;
    std::vector<Detection> decode_map(const RawBoxes& raw, double threshold, int top) const;
    std::vector<Detection> decode_clickable(const RawBoxes& raw, double threshold, int top) const;
    std::vector<Detection> map_objects(const cv::Mat& bgr, double threshold = 0.2, int top = 10) const;
    std::vector<Detection> buttons(const cv::Mat& bgr, double threshold = 0.2, int top = 10) const;

    //  Brain.encounter_objects: the network once (encounter_raw: 51,150 boxes and 51,150 x 4 certainties, the background and
    //  three classes) and what TensorFlow Lite's post-processing and gamebot.py make of it (decode_encounter).
    RawBoxes encounter_raw(const cv::Mat& bgr) const;
    std::vector<Detection> decode_encounter(const RawBoxes& raw, double threshold) const;
    std::vector<Detection> encounter_objects(const cv::Mat& bgr, double threshold = 0.2) const;

    ThrowParams throw_params(double cx, double cy, double w, double h) const;

private:
    struct Impl;
    std::unique_ptr<Impl> m_impl;
};


//  The choice of Brain._ssd for a detector's answer, on its own: the anchors are (x, y, w, h) per box.
std::vector<Detection> decode_detections(
    const RawBoxes& raw,
    const std::vector<float>& anchors,
    const std::vector<std::string>& labels,
    double threshold, int top
);


//  The post-processing of the encounter detector on its own: the anchors are (y, x, h, w) per box.  Returns what gamebot.py's
//  Brain.encounter_objects returns: the best of the 10 boxes at the threshold or above, best first.
std::vector<Detection> decode_encounter_detections(const RawBoxes& raw, const std::vector<float>& anchors, double threshold);


//  Holds the port to models_golden.json (the files of the models are in `models`, the pictures in `fixtures`
//  (tests/fixtures)).  Returns how many things differ and adds what it did to the report.
int run_models_checks(const QString& golden, const QString& fixtures, const QString& models, QStringList& report);



}
}
}
}
#endif
