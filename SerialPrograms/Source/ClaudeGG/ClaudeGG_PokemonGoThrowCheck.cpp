/*  Claude GG Pokemon GO Throw Check (the readers and the sums of the throw, held to the Python code)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The file of Mobile/tools/make_throw_golden.py holds, for the readers of the throw of gamebot.py, pictures (drawn on the canvas as
 *  the file says: a background, discs, rings, noise) and what the Python code made of them: the size of the coloured ring (measure_ring),
 *  the ball in the air and where it came down (find_ball, _landing), the buttons of the catch screen (enc_buttons, in_encounter,
 *  ball_ready, result_ok_button), and the sums: the speed of the ring (ring_speed), what is learned from the last throws (refit_timing)
 *  and the curveball (curve_lean, spin_points, aim_note), and the numbers of the throw.  Every picture is drawn here the same way and
 *  every number must come out the same.
 *
 */

#include <algorithm>
#include <cmath>
#include <map>
#include <opencv2/imgproc.hpp>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include "ClaudeGG_PokemonGoThrow.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Throw{

namespace{

const int W = Loop::REF_W;
const int H = Loop::REF_H;


QString describe(const QJsonValue& value){
    QString text;
    if (value.isArray()){
        text = QString::fromUtf8(QJsonDocument(value.toArray()).toJson(QJsonDocument::Compact));
    }else if (value.isObject()){
        text = QString::fromUtf8(QJsonDocument(value.toObject()).toJson(QJsonDocument::Compact));
    }else if (value.isNull()){
        text = "none";
    }else{
        text = value.toVariant().toString();
    }
    if (text.size() > 300){
        text = text.left(300) + "...";
    }
    return text;
}

//  The first place where two JSON values are not the same (numbers: exactly, the port must come to the same numbers as numpy), or nothing.
QString difference(const QJsonValue& want, const QJsonValue& got, const QString& path){
    if (want.isDouble() && got.isDouble()){
        if (want.toDouble() != got.toDouble()){
            return QString("%1: %2 is not %3").arg(path, describe(want), describe(got));
        }
        return QString();
    }
    if (want.isArray() && got.isArray()){
        const QJsonArray a = want.toArray();
        const QJsonArray b = got.toArray();
        if (a.size() != b.size()){
            return QString("%1: %2 is not %3").arg(path, describe(want), describe(got));
        }
        for (qsizetype i = 0; i < a.size(); i++){
            const QString one = difference(a.at(i), b.at(i), QString("%1[%2]").arg(path).arg(i));
            if (!one.isEmpty()){
                return one;
            }
        }
        return QString();
    }
    if (want.isObject() && got.isObject()){
        const QJsonObject a = want.toObject();
        const QJsonObject b = got.toObject();
        for (auto it = a.begin(); it != a.end(); ++it){
            if (!b.contains(it.key())){
                return QString("%1: '%2' is missing").arg(path, it.key());
            }
            const QString one = difference(it.value(), b.value(it.key()), path + "." + it.key());
            if (!one.isEmpty()){
                return one;
            }
        }
        for (auto it = b.begin(); it != b.end(); ++it){
            if (!a.contains(it.key())){
                return QString("%1: '%2' is there but should not be").arg(path, it.key());
            }
        }
        return QString();
    }
    if (want == got){
        return QString();
    }
    return QString("%1: %2 is not %3").arg(path, describe(want), describe(got));
}


//  ---- the pictures (make_throw_golden.make_scene())

cv::Scalar colour_of(const QJsonValue& value){
    const QJsonArray c = value.toArray();
    return cv::Scalar(c.at(0).toDouble(), c.at(1).toDouble(), c.at(2).toDouble());
}

//  Python's a // b for a whole number b > 0.
long long floor_div(long long a, long long b){
    long long q = a / b;
    if ((a % b != 0) && (a < 0)){
        q--;
    }
    return q;
}

cv::Mat make_scene(const QJsonArray& ops){
    cv::Mat img(H, W, CV_8UC3, cv::Scalar(0, 0, 0));
    for (const QJsonValue& v : ops){
        const QJsonArray op = v.toArray();
        const QString kind = op.at(0).toString();
        if (kind == "fill"){
            img.setTo(cv::Scalar(op.at(1).toDouble(), op.at(2).toDouble(), op.at(3).toDouble()));
        }else if (kind == "vgrad"){
            const QJsonArray c0 = op.at(1).toArray();
            const QJsonArray c1 = op.at(2).toArray();
            for (int y = 0; y < H; y++){
                cv::Vec3b px;
                for (int c = 0; c < 3; c++){
                    const long long a = c0.at(c).toInt();
                    const long long b = c1.at(c).toInt();
                    px[c] = (uchar)(a + floor_div((b - a) * y, H - 1));
                }
                img.row(y).setTo(cv::Scalar(px[0], px[1], px[2]));
            }
        }else if (kind == "rect"){
            const int x = op.at(1).toInt();
            const int y = op.at(2).toInt();
            const int w = op.at(3).toInt();
            const int h = op.at(4).toInt();
            const int xa = std::max(x, 0);
            const int ya = std::max(y, 0);
            const int xb = std::min(std::max(x + w, 0), W);
            const int yb = std::min(std::max(y + h, 0), H);
            if (xa < xb && ya < yb){
                img(cv::Range(ya, yb), cv::Range(xa, xb)).setTo(colour_of(op.at(5)));
            }
        }else if (kind == "circle"){
            cv::circle(img, cv::Point(op.at(1).toInt(), op.at(2).toInt()), op.at(3).toInt(), colour_of(op.at(5)), op.at(4).toInt());
        }else if (kind == "ellipse"){
            //  (and, when it is not the whole ellipse, the angles to start and to end)
            const double start = op.size() > 8 ? op.at(8).toDouble() : 0.0;
            const double end = op.size() > 9 ? op.at(9).toDouble() : 360.0;
            cv::ellipse(img, cv::Point(op.at(1).toInt(), op.at(2).toInt()), cv::Size(op.at(3).toInt(), op.at(4).toInt()), op.at(5).toDouble(),
                        start, end, colour_of(op.at(7)), op.at(6).toInt());
        }else if (kind == "noise"){
            const quint32 seed = (quint32)(((quint64)op.at(1).toInt() * 2654435761ULL) & 0xFFFFFFFFULL);
            const int amp = op.at(2).toInt();
            for (int y = 0; y < H; y++){
                uchar* row = img.ptr<uchar>(y);
                for (int x = 0; x < W; x++){
                    for (int c = 0; c < 3; c++){
                        quint32 n = ((quint32)x * 73856093u) ^ ((quint32)y * 19349663u) ^ ((quint32)c * 83492791u) ^ seed;
                        n = n ^ (n >> 13);
                        n = n * 1274126177u;
                        n = n ^ (n >> 16);
                        const int v2 = (int)(n % (quint32)(2 * amp + 1)) - amp;
                        row[3 * x + c] = (uchar)std::min(std::max((int)row[3 * x + c] + v2, 0), 255);
                    }
                }
            }
        }
    }
    return img;
}

//  (the last few pictures are kept: the cases use the same one over and over)
cv::Mat scene(const QJsonArray& ops){
    static std::map<QString, cv::Mat> kept;
    const QString key = QString::fromUtf8(QJsonDocument(ops).toJson(QJsonDocument::Compact));
    const auto at = kept.find(key);
    if (at != kept.end()){
        return at->second;
    }
    if (kept.size() > 6){
        kept.clear();
    }
    const cv::Mat img = make_scene(ops);
    kept[key] = img;
    return img;
}

QJsonValue maybe(const std::optional<double>& v){
    return v.has_value() ? QJsonValue(*v) : QJsonValue(QJsonValue::Null);
}

Detection detection_of(const QJsonArray& box){
    Detection d;
    d.label = box.at(0).toString().toStdString();
    d.score = box.at(1).toDouble();
    d.cx = box.at(2).toInt();
    d.cy = box.at(3).toInt();
    d.w = box.at(4).toInt();
    d.h = box.at(5).toInt();
    return d;
}

}


cv::Mat make_check_scene(const QJsonArray& ops){
    return make_scene(ops);
}


int run_throw_checks(const QString& golden, QStringList& report){
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the throw's numbers and pictures are not there: " + golden;
        return 1;
    }
    const QJsonObject root = QJsonDocument::fromJson(qUncompress(file.readAll())).object();
    int failed = 0;
    auto wrong = [&](const QString& id, const QString& what){
        report << QString("FAILED: the throw reader '%1' reads another way than the Python code: %2").arg(id, what);
        failed++;
    };

    //  the numbers
    {
        const QString what = difference(root.value("constants"), throw_constants(), "constants");
        if (!what.isEmpty()){
            report << "FAILED: the numbers of the throw are not those of the Python code: " + what;
            failed++;
        }
    }

    //  the rings
    const QJsonArray rings = root.value("rings").toArray();
    for (const QJsonValue& v : rings){
        const QJsonObject c = v.toObject();
        const cv::Mat img = scene(c.value("pic").toArray());
        RingDiag diag;
        const std::optional<Ring> m = measure_ring(img, detection_of(c.value("box").toArray()), &diag);
        QJsonObject got;
        got["found"] = m.has_value();
        got["ratio"] = m ? QJsonValue(m->ratio) : QJsonValue(QJsonValue::Null);
        got["rw"] = m ? QJsonValue(m->rw) : QJsonValue(QJsonValue::Null);
        got["rc"] = m ? QJsonValue(m->rc) : QJsonValue(QJsonValue::Null);
        got["cx"] = m ? QJsonValue(m->cx) : QJsonValue(QJsonValue::Null);
        got["cy"] = m ? QJsonValue(m->cy) : QJsonValue(QJsonValue::Null);
        got["q"] = m ? QJsonValue(m->q) : QJsonValue(QJsonValue::Null);
        got["diag"] = QJsonObject{{"white", maybe(diag.white)}, {"colour", maybe(diag.colour)}, {"size", maybe(diag.size)},
                                  {"has_size", diag.has_size}};
        const QString what = difference(c.value("result"), got, "ring");
        if (!what.isEmpty()){
            wrong(c.value("id").toString(), what);
        }
    }

    //  the threshold of the edges (np.percentile of float32 numbers)
    const QJsonArray percentiles = root.value("percentiles").toArray();
    for (const QJsonValue& v : percentiles){
        const QJsonObject c = v.toObject();
        std::vector<float> values;
        for (const QJsonValue& x : c.value("values").toArray()){
            values.push_back((float)x.toDouble());
        }
        const double got = (double)percentile80(values);
        if (got != c.value("p").toDouble()){
            wrong(c.value("id").toString(), QString("the 80th percentile is %1, not %2").arg(c.value("p").toDouble(), 0, 'g', 10).arg(got, 0, 'g', 10));
        }
    }

    //  the ball in the air
    const QJsonArray balls = root.value("balls").toArray();
    for (const QJsonValue& v : balls){
        const QJsonObject c = v.toObject();
        const std::optional<Ball> ball = find_ball(scene(c.value("after").toArray()), scene(c.value("before").toArray()));
        const QJsonValue got = ball ? QJsonValue(QJsonArray{ball->x, ball->y, ball->area}) : QJsonValue(QJsonValue::Null);
        const QString what = difference(c.value("result"), got, "ball");
        if (!what.isEmpty()){
            wrong(c.value("id").toString(), what);
        }
    }

    //  where the ball came down
    const QJsonArray landings = root.value("landings").toArray();
    for (const QJsonValue& v : landings){
        const QJsonObject c = v.toObject();
        std::vector<cv::Mat> imgs;
        for (const QJsonValue& a : c.value("afters").toArray()){
            imgs.push_back(make_scene(a.toArray()));
        }
        const cv::Mat before = make_scene(c.value("before").toArray());
        std::optional<Detection> ring;
        if (c.value("ring").isArray()){
            ring = detection_of(c.value("ring").toArray());
        }
        const std::optional<int> land = landing_x(imgs, before, ring ? &*ring : nullptr);
        const QString what = difference(c.value("land"), land ? QJsonValue(*land) : QJsonValue(QJsonValue::Null), "land");
        if (!what.isEmpty()){
            wrong(c.value("id").toString(), what);
        }
    }

    //  the buttons of the catch screen
    const QJsonArray buttons = root.value("buttons").toArray();
    for (const QJsonValue& v : buttons){
        const QJsonObject c = v.toObject();
        const cv::Mat img = scene(c.value("pic").toArray());
        const std::optional<Point> ok = result_ok_button(img);
        QJsonObject got;
        got["enc_buttons"] = enc_buttons(img);
        got["in_encounter"] = in_encounter(img);
        got["ball_ready"] = ball_ready(img);
        got["ok"] = ok ? QJsonValue(QJsonArray{ok->x, ok->y}) : QJsonValue(QJsonValue::Null);
        QJsonObject want = c;
        want.remove("id");
        want.remove("pic");
        const QString what = difference(want, got, "buttons");
        if (!what.isEmpty()){
            wrong(c.value("id").toString(), what);
        }
    }

    //  the speed of the ring
    const QJsonArray speeds = root.value("speeds").toArray();
    for (const QJsonValue& v : speeds){
        const QJsonObject c = v.toObject();
        std::vector<std::pair<double, double>> points;
        for (const QJsonValue& p : c.value("points").toArray()){
            points.push_back({p.toArray().at(0).toDouble(), p.toArray().at(1).toDouble()});
        }
        const std::optional<double> k = ring_speed(points);
        const QString what = difference(c.value("k"), maybe(k), "speed");
        if (!what.isEmpty()){
            wrong(c.value("id").toString(), what);
        }
    }

    //  what is learned from the last throws
    const QJsonArray timing = root.value("timing").toArray();
    for (const QJsonValue& v : timing){
        const QJsonObject c = v.toObject();
        Cal cal;
        cal.k = c.value("k_before").toDouble();
        std::vector<std::array<double, 3>>& obs = c.value("live").toBool() ? cal.obs_live : cal.obs;
        for (const QJsonValue& o : c.value("obs").toArray()){
            const QJsonArray a = o.toArray();
            obs.push_back({a.at(0).toDouble(), a.at(1).toDouble(), a.at(2).toDouble()});
        }
        refit_timing(cal, c.value("live").toBool());
        const QJsonObject got{{"k", cal.k}, {"c", cal.c}, {"c_live", cal.c_live}};
        const QString what = difference(c.value("after"), got, "timing");
        if (!what.isEmpty()){
            wrong(c.value("id").toString(), what);
        }
    }

    //  the curveball
    {
        const QJsonObject aims = root.value("aims").toObject();
        for (const QJsonValue& v : aims.value("lean").toArray()){
            const QJsonObject c = v.toObject();
            Cal cal;
            cal.aim = c.value("aim").toDouble();
            std::optional<int> target;
            if (!c.value("target").isNull()){
                target = c.value("target").toInt();
            }
            const int lean = curve_lean(cal, target);
            if (lean != c.value("lean").toInt()){
                wrong(QString("curve_lean(aim %1, target %2)").arg(cal.aim).arg(describe(c.value("target"))),
                      QString("%1 is not %2").arg(c.value("lean").toInt()).arg(lean));
            }
        }
        QJsonArray points;
        for (const Point& p : spin_points()){
            points.append(QJsonArray{p.x, p.y});
        }
        const QString what = difference(aims.value("points"), points, "spin_points");
        if (!what.isEmpty()){
            wrong("spin_points", what);
        }
        for (const QJsonValue& v : aims.value("notes").toArray()){
            const QJsonObject c = v.toObject();
            const int aim_dx = c.value("aim_dx").toInt();
            const QString note = c.value("ring_w").isNull() ? aim_note(aim_dx) : aim_note(aim_dx, c.value("ring_w").toInt());
            if (note != c.value("note").toString()){
                wrong(QString("aim_note(%1, %2)").arg(aim_dx).arg(describe(c.value("ring_w"))),
                      QString("'%1' is not '%2'").arg(c.value("note").toString(), note));
            }
        }
    }

    report << QString("throw: %1 rings, %2 balls, %3 landings, %4 buttons, %5 speeds, %6 timings and %7 percentiles played, %8 went another way")
              .arg(rings.size()).arg(balls.size()).arg(landings.size()).arg(buttons.size()).arg(speeds.size()).arg(timing.size()).arg(percentiles.size()).arg(failed);
    return failed;
}


}
}
}
}
