/*  Claude GG Pokemon GO Text (the text reader of the Pokemon GO bot, in C++)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  What gamebot.ocr_lines() and gamebot.ocr_line() do: the words of a picture with the place of each, grouped
 *  into lines, and the text of a picture that holds nothing else.  Both ask the tesseract program (`tesseract
 *  stdin stdout --psm 11 tsv`): the text reader that the program has inside (tesseractPA) gives the text of a
 *  picture but not the place of its words, and the screens of the game are read by the place of their words.
 *
 *  The part that makes lines of the table of Tesseract (lines_from_tsv, one_line) is held, in every build, to
 *  what gamebot.py makes of 354 tables (Mobile/tools/make_text_golden.py: 36 read from frames of real fights by
 *  Tesseract, made-up ones and 300 random ones).  The program itself is called where it is found (the setting
 *  CLAUDEGG_TESSERACT, the PATH, the usual folders on Windows); without it every reading says "nothing", as
 *  gamebot.py does.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoText_H
#define PokemonAutomation_ClaudeGG_PokemonGoText_H

#include <optional>
#include <vector>
#include <opencv2/core.hpp>
#include <QString>
#include <QStringList>
#include "ClaudeGG_PokemonGoNav.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Text{


//  The lines of the table that Tesseract wrote (`tsv`) for a picture that was read from row y0 on, made `scale` times
//  as big: [(TEXT, x of the first word, y, [(word, x, y), ...]), ...] in capitals, the places in the whole picture.
//  Words of which Tesseract is not sure (confidence under 40) are left out.  Throws std::runtime_error for a number
//  that is none (gamebot.py raises there as well).
Nav::Lines lines_from_tsv(const QString& tsv, double scale = 1.0, int y0 = 0);

//  What Tesseract wrote for a picture with text and nothing else, white space as one space.
QString one_line(const QString& raw);


//  The tesseract program.
class Reader{
public:
    //  `program`: the file to run; empty: it is looked for.
    explicit Reader(const QString& program = QString());

    bool available() const{ return !m_program.isEmpty(); }
    QString program() const{ return m_program; }

    //  Rows y0 to y1 of a picture (to the end: none), made `scale` times as big for a faster reading (the places are
    //  those of the whole picture).  Nothing when the program is not there; throws std::runtime_error when it does
    //  not answer in 40 s.
    Nav::Lines lines(const cv::Mat& img, int y0 = 0, std::optional<int> y1 = {}, double scale = 1.0) const;
    //  The text of a picture that holds nothing else (black letters on white): one line, or a few under each other
    //  (lines > 1) as one.  "" when nothing is read or the program is not there.
    QString line(const cv::Mat& img, int lines = 1) const;
    //  The table that the program writes (`--psm 11 tsv`) for a picture as it is (gamebot.tray_labels(): the berry tray).  Nothing when the
    //  program is not there or does not start; throws std::runtime_error when it does not answer in 30 s.
    std::optional<QString> table(const cv::Mat& img) const;

    //  Where the program is looked for: the setting CLAUDEGG_TESSERACT, the PATH and, on Windows, the folders that its
    //  installers use.  Empty: not found.
    static QString find_program();

private:
    QString m_program;
};


//  The check: the tables of the file of Mobile/tools/make_text_golden.py (tests/fixtures/text_golden.json.qz) made
//  into lines, and the texts made into one line, as gamebot.py does.  Where the tesseract program is found it reads a
//  picture with a few words drawn on it as well ("ok" lines in `report`; "FAILED: ..." lines say what differs).
//  Returns how many went another way.
int run_text_checks(const QString& golden, QStringList& report);


}
}
}
}
#endif
