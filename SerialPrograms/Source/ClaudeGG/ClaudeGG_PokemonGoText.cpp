/*  Claude GG Pokemon GO Text (the text reader of the Pokemon GO bot, in C++)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QStandardPaths>
#include "ClaudeGG_PokemonGoText.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Text{


namespace{

//  Python's str.isspace() (Qt's QChar::isSpace() does not have the separators of the old ASCII).
bool is_space(QChar c){
    return c.isSpace() || (c.unicode() >= 0x1c && c.unicode() <= 0x1f);
}
//  str.strip() and str.split().
QString stripped(const QString& text){
    qsizetype begin = 0;
    qsizetype end = text.size();
    while (begin < end && is_space(text[begin])){
        begin++;
    }
    while (end > begin && is_space(text[end - 1])){
        end--;
    }
    return text.mid(begin, end - begin);
}
QStringList split_white(const QString& text){
    QStringList words;
    QString word;
    for (QChar c : text){
        if (is_space(c)){
            if (!word.isEmpty()){
                words << word;
                word.clear();
            }
        }else{
            word += c;
        }
    }
    if (!word.isEmpty()){
        words << word;
    }
    return words;
}
//  Python's //.
int floor_div(int a, int b){
    int q = a / b;
    if ((a % b != 0) && ((a < 0) != (b < 0))){
        q--;
    }
    return q;
}

//  int() and float() of a field of the table.
int to_int(const QString& field, const char* what){
    bool ok = false;
    const int value = stripped(field).toInt(&ok);
    if (!ok){
        throw std::runtime_error(std::string("the table of the text reader has no number in '") + what + "': " + field.toStdString());
    }
    return value;
}
double to_float(const QString& field){
    bool ok = false;
    const double value = stripped(field).toDouble(&ok);
    if (!ok){
        throw std::runtime_error("the table of the text reader has no number in 'conf': " + field.toStdString());
    }
    return value;
}

struct Piece{
    QString text;
    int x = 0;
    int y = 0;
    int h = 0;
};

}


Nav::Lines lines_from_tsv(const QString& tsv, double scale, int y0){
    //  (The table is read without quoting rules: a word that is read as a single double quote would otherwise swallow
    //  every word after it.)
    QStringList rows = tsv.split('\n');
    QStringList head;
    int left = -1, top = -1, width = -1, height = -1, conf = -1, text = -1;
    bool first = true;
    std::vector<Piece> words;
    for (QString row : rows){
        if (row.endsWith('\r')){
            row.chop(1);
        }
        if (first){
            first = false;
            head = row.split('\t');
            left = (int)head.indexOf("left");
            top = (int)head.indexOf("top");
            width = (int)head.indexOf("width");
            height = (int)head.indexOf("height");
            conf = (int)head.indexOf("conf");
            text = (int)head.indexOf("text");
            continue;
        }
        if (row.isEmpty()){
            continue;
        }
        const QStringList parts = row.split('\t');
        auto field = [&](int index) -> std::optional<QString>{
            if (index < 0 || index >= parts.size()){
                return std::nullopt;
            }
            return parts[index];
        };
        const QString t = stripped(field(text).value_or(QString()));
        if (t.isEmpty()){
            continue;
        }
        const std::optional<QString> c = field(conf);
        const double confidence = (c.has_value() && !c->isEmpty()) ? to_float(*c) : -1.0;      //  (float(r.get("conf") or -1))
        if (!(confidence >= 40)){
            continue;
        }
        const int l = to_int(field(left).value_or(QString()), "left");
        const int w = to_int(field(width).value_or(QString()), "width");
        const int tp = to_int(field(top).value_or(QString()), "top");
        const int h = to_int(field(height).value_or(QString()), "height");
        Piece piece;
        piece.text = t.toUpper();
        piece.x = (int)(((double)l + (double)w / 2) / scale);
        piece.y = (int)(((double)tp + (double)h / 2) / scale) + y0;
        piece.h = (int)((double)h / scale);
        words.push_back(piece);
    }
    std::stable_sort(words.begin(), words.end(), [](const Piece& a, const Piece& b){
        return a.y != b.y ? a.y < b.y : a.x < b.x;
    });
    std::vector<std::vector<Piece>> lines;
    for (const Piece& w : words){
        if (!lines.empty() && std::abs(lines.back().back().y - w.y) < w.h * 0.7){
            lines.back().push_back(w);
        }else{
            lines.push_back({w});
        }
    }
    Nav::Lines result;
    for (std::vector<Piece>& line : lines){
        std::stable_sort(line.begin(), line.end(), [](const Piece& a, const Piece& b){ return a.x < b.x; });
        Nav::Line out;
        int sum = 0;
        QStringList texts;
        for (const Piece& w : line){
            texts << w.text;
            sum += w.y;
            out.words.push_back(Nav::Word{w.text, w.x, w.y});
        }
        out.text = texts.join(' ');
        out.x = line.front().x;
        out.y = floor_div(sum, (int)line.size());
        result.push_back(out);
    }
    return result;
}

QString one_line(const QString& raw){
    return split_white(raw).join(' ');
}


QString Reader::find_program(){
    const QString given = qEnvironmentVariable("CLAUDEGG_TESSERACT");
    if (!given.isEmpty() && QFile::exists(given)){
        return given;
    }
    QString found = QStandardPaths::findExecutable("tesseract");
    if (!found.isEmpty()){
        return found;
    }
#ifdef Q_OS_WIN
    const QStringList folders = {
        "C:/Program Files/Tesseract-OCR",
        "C:/Program Files (x86)/Tesseract-OCR",
        qEnvironmentVariable("LOCALAPPDATA") + "/Programs/Tesseract-OCR",
    };
    for (const QString& folder : folders){
        found = QStandardPaths::findExecutable("tesseract", {folder});
        if (!found.isEmpty()){
            return found;
        }
    }
#endif
    return QString();
}

Reader::Reader(const QString& program)
    : m_program(program.isEmpty() ? find_program() : program)
{}

namespace{

//  Runs the program with a picture on its standard input.  false: it did not start.
bool run_program(const QString& program, const QStringList& arguments, const std::vector<uchar>& png, int timeout_msec, QByteArray& output){
    QProcess process;
    process.start(program, arguments);
    if (!process.waitForStarted(10000)){
        return false;
    }
    process.write(reinterpret_cast<const char*>(png.data()), (qint64)png.size());
    process.closeWriteChannel();
    if (!process.waitForFinished(timeout_msec)){
        process.kill();
        process.waitForFinished(2000);
        throw std::runtime_error("the tesseract program did not answer in " + std::to_string(timeout_msec / 1000) + " s");
    }
    output = process.readAllStandardOutput();
    return true;
}

cv::Mat grey_of(const cv::Mat& crop, double scale){
    cv::Mat work = crop;
    if (scale != 1.0){
        cv::resize(crop, work, cv::Size(), scale, scale, cv::INTER_AREA);
    }
    if (work.channels() == 1){
        return work;
    }
    cv::Mat grey;
    cv::cvtColor(work, grey, work.channels() == 4 ? cv::COLOR_BGRA2GRAY : cv::COLOR_BGR2GRAY);
    return grey;
}

}

Nav::Lines Reader::lines(const cv::Mat& img, int y0, std::optional<int> y1, double scale) const{
    if (!available()){
        return {};
    }
    //  (img[y0:y1] of Python: the rows that are there)
    const int from = std::clamp(y0, 0, img.rows);
    const int to = std::clamp(y1.has_value() ? *y1 : img.rows, from, img.rows);
    if (to <= from || img.cols <= 0){
        return {};
    }
    std::vector<uchar> png;
    cv::imencode(".png", grey_of(img.rowRange(from, to), scale), png);
    QByteArray output;
    if (!run_program(m_program, {"stdin", "stdout", "--psm", "11", "tsv"}, png, 40000, output)){
        return {};
    }
    return lines_from_tsv(QString::fromUtf8(output), scale, y0);
}

QString Reader::line(const cv::Mat& img, int lines) const{
    if (!available() || img.empty()){
        return QString();
    }
    std::vector<uchar> png;
    cv::imencode(".png", img.channels() == 1 ? img : grey_of(img, 1.0), png);
    QByteArray output;
    try{
        if (!run_program(m_program, {"stdin", "stdout", "--psm", lines == 1 ? "7" : "6"}, png, 20000, output)){
            return QString();
        }
    }catch (const std::runtime_error&){
        return QString();                       //  (a reading that takes too long is no reading)
    }
    return one_line(QString::fromUtf8(output));
}


//  ---- the check

namespace{

QString describe(const Nav::Lines& lines){
    QStringList parts;
    for (const Nav::Line& line : lines){
        QStringList words;
        for (const Nav::Word& w : line.words){
            words << QString("%1@%2,%3").arg(w.text).arg(w.x).arg(w.y);
        }
        parts << QString("[%1 | %2,%3 | %4]").arg(line.text).arg(line.x).arg(line.y).arg(words.join(' '));
    }
    return parts.join(' ');
}

Nav::Lines lines_of(const QJsonArray& array){
    Nav::Lines lines;
    for (const QJsonValue& v : array){
        const QJsonArray a = v.toArray();
        Nav::Line line;
        line.text = a.at(0).toString();
        line.x = a.at(1).toInt();
        line.y = a.at(2).toInt();
        for (const QJsonValue& w : a.at(3).toArray()){
            const QJsonArray word = w.toArray();
            line.words.push_back(Nav::Word{word.at(0).toString(), word.at(1).toInt(), word.at(2).toInt()});
        }
        lines.push_back(line);
    }
    return lines;
}

bool same(const Nav::Lines& a, const Nav::Lines& b){
    if (a.size() != b.size()){
        return false;
    }
    for (size_t i = 0; i < a.size(); i++){
        if (a[i].text != b[i].text || a[i].x != b[i].x || a[i].y != b[i].y || a[i].words.size() != b[i].words.size()){
            return false;
        }
        for (size_t k = 0; k < a[i].words.size(); k++){
            if (a[i].words[k].text != b[i].words[k].text || a[i].words[k].x != b[i].words[k].x || a[i].words[k].y != b[i].words[k].y){
                return false;
            }
        }
    }
    return true;
}

}

int run_text_checks(const QString& golden, QStringList& report){
    QFile file(golden);
    if (!file.open(QIODevice::ReadOnly)){
        report << "FAILED: the tables of the text reader are not there: " + golden;
        return 1;
    }
    const QJsonObject root = QJsonDocument::fromJson(qUncompress(file.readAll())).object();
    const QJsonArray cases = root.value("cases").toArray();
    const QJsonArray texts = root.value("texts").toArray();
    if (cases.isEmpty() || texts.isEmpty()){
        report << "FAILED: the file of tables of the text reader is empty or not right: " + golden;
        return 1;
    }
    int wrong = 0;
    for (const QJsonValue& value : cases){
        const QJsonObject one = value.toObject();
        const Nav::Lines want = lines_of(one.value("lines").toArray());
        Nav::Lines got;
        try{
            got = lines_from_tsv(one.value("tsv").toString(), one.value("scale").toDouble(), one.value("y0").toInt());
        }catch (const std::exception& e){
            wrong++;
            report << "FAILED: " + one.value("id").toString() + ": " + e.what();
            continue;
        }
        if (!same(got, want)){
            wrong++;
            if (wrong <= 8){
                report << "FAILED: " + one.value("id").toString() + ": gamebot.py made " + describe(want) + ", the port " + describe(got);
            }
        }
    }
    for (const QJsonValue& value : texts){
        const QJsonObject one = value.toObject();
        if (one_line(one.value("raw").toString()) != one.value("line").toString()){
            wrong++;
            report << "FAILED: the text '" + one.value("raw").toString() + "' is one line '" + one_line(one.value("raw").toString()) + "', gamebot.py says '" + one.value("line").toString() + "'";
        }
    }
    report << QString("%1 tables and %2 texts made into lines as gamebot.py makes them, %3 of them went another way").arg(cases.size()).arg(texts.size()).arg(wrong);

    //  The program itself, where there is one: a picture with words drawn on it.
    const Reader reader;
    if (reader.available()){
        cv::Mat picture(600, 1768, CV_8UC3, cv::Scalar(255, 255, 255));
        cv::putText(picture, "NEXT BATTLE", cv::Point(300, 200), cv::FONT_HERSHEY_SIMPLEX, 4.0, cv::Scalar(0, 0, 0), 8);
        cv::putText(picture, "GOOD EFFORT", cv::Point(300, 450), cv::FONT_HERSHEY_SIMPLEX, 4.0, cv::Scalar(0, 0, 0), 8);
        bool found_next = false;
        bool found_effort = false;
        QString seen;
        try{
            for (const Nav::Line& line : reader.lines(picture)){
                seen += line.text + "; ";
                found_next = found_next || line.text.contains("NEXT");
                found_effort = found_effort || line.text.contains("EFFORT");
            }
        }catch (const std::exception& e){
            seen = e.what();
        }
        const cv::Mat plain = picture(cv::Rect(0, 100, 1768, 150)).clone();
        const QString one = reader.line(plain);
        if (!(found_next && found_effort) || !one.contains("NEXT")){
            wrong++;
            report << "FAILED: the tesseract program (" + reader.program() + ") read '" + seen + "' and '" + one + "' from a picture of NEXT BATTLE and GOOD EFFORT";
        }else{
            report << "the tesseract program (" + reader.program() + ") reads words with their places";
        }
    }else{
        report << "no tesseract program here: only the tables were tried";
    }
    return wrong;
}


}
}
}
}
