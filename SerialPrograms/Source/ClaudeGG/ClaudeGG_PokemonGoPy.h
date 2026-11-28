/*  Claude GG Pokemon GO Py (what Python does with texts and numbers, for the ports of gamebot.py)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  gamebot.py writes log lines with f-strings and reads what the text readers give with str.strip(), int() and float(); an error of
 *  Python is told in the log (and held to the golden files of the ports), so the ports do those things as Python does them, to the last
 *  character.  Held, in every build, by the checks of the parts that use them (the stories of the catch screen, the bag, ...).
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PokemonGoPy_H
#define PokemonAutomation_ClaudeGG_PokemonGoPy_H

#include <cstdio>
#include <limits>
#include <stdexcept>
#include <QChar>
#include <QString>
#include <QStringList>

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PokemonGo{
namespace Py{


//  f"{x:.2f}": Python and printf both round the number as it is, to the nearest, a tie to the even one.
inline QString fixed(double x, int digits){
    char buffer[512];
    std::snprintf(buffer, sizeof(buffer), "%.*f", digits, x);
    return QString::fromLatin1(buffer);
}

//  repr() of a text (Python: single quotes, unless the text has one and no double quote; what cannot be printed is escaped).
inline QString py_repr(const QString& text){
    const bool single = text.contains('\'');
    const bool double_q = text.contains('"');
    const QChar quote = (single && !double_q) ? QChar('"') : QChar('\'');
    QString out(quote);
    for (const char32_t c : text.toUcs4()){
        if (c == (char32_t)quote.unicode() || c == '\\'){
            out += '\\';
            out += QChar((ushort)c);
        }else if (c == '\n'){
            out += "\\n";
        }else if (c == '\r'){
            out += "\\r";
        }else if (c == '\t'){
            out += "\\t";
        }else{
            bool printable = true;
            if (c < 0x20 || c == 0x7f){
                printable = false;
            }else if (c > 0x7f){
                switch (QChar::category(c)){
                case QChar::Other_Control:
                case QChar::Other_Format:
                case QChar::Other_Surrogate:
                case QChar::Other_PrivateUse:
                case QChar::Other_NotAssigned:
                case QChar::Separator_Line:
                case QChar::Separator_Paragraph:
                case QChar::Separator_Space:
                    printable = false;
                    break;
                default:
                    break;
                }
            }
            if (printable){
                out += QString::fromUcs4(&c, 1);
            }else if (c < 0x100){
                out += QString("\\x%1").arg((uint)c, 2, 16, QChar('0'));
            }else if (c < 0x10000){
                out += QString("\\u%1").arg((uint)c, 4, 16, QChar('0'));
            }else{
                out += QString("\\U%1").arg((uint)c, 8, 16, QChar('0'));
            }
        }
    }
    out += quote;
    return out;
}

//  What str.isspace() of Python calls white space (QString::trimmed() leaves out the four separators 0x1C - 0x1F that Python takes).
inline bool py_space(QChar c){
    const ushort u = c.unicode();
    return (u >= 0x09 && u <= 0x0d) || (u >= 0x1c && u <= 0x20) || u == 0x85 || u == 0xa0 || u == 0x1680 || (u >= 0x2000 && u <= 0x200a)
        || u == 0x2028 || u == 0x2029 || u == 0x202f || u == 0x205f || u == 0x3000;
}
//  str.strip().
inline QString py_strip(const QString& text){
    qsizetype from = 0;
    qsizetype to = text.size();
    while (from < to && py_space(text.at(from))){
        from++;
    }
    while (to > from && py_space(text.at(to - 1))){
        to--;
    }
    return text.mid(from, to - from);
}

//  str.split() without an argument: the pieces between runs of white space.
inline QStringList py_split(const QString& text){
    QStringList out;
    QString piece;
    for (const QChar c : text){
        if (py_space(c)){
            if (!piece.isEmpty()){
                out << piece;
                piece.clear();
            }
        }else{
            piece += c;
        }
    }
    if (!piece.isEmpty()){
        out << piece;
    }
    return out;
}

//  str.title() for what is written with letters of the alphabet and spaces ("RAZZ BERRY" is "Razz Berry").
inline QString py_title(const QString& text){
    QString out;
    bool after_letter = false;
    for (const QChar c : text){
        if (c.isLetter()){
            out += after_letter ? c.toLower() : c.toUpper();
            after_letter = true;
        }else{
            out += c;
            after_letter = false;
        }
    }
    return out;
}

//  float(text) of Python: false when the text is no number.  What float() takes: white space around it, a sign, then inf, infinity or nan (in any
//  case) or digits with a point and an exponent, one underscore allowed between two digits; digits of other scripts are digits too (those of the
//  Basic Multilingual Plane).
inline bool py_parse_float(const QString& text, double& value){
    const QString stripped = py_strip(text);
    QString a;
    for (const QChar c : stripped){
        if (c.unicode() < 128){
            a += c;
        }else if (c.category() == QChar::Number_DecimalDigit){
            a += QChar((ushort)('0' + c.digitValue()));
        }else{
            return false;
        }
    }
    const qsizetype n = a.size();
    qsizetype i = 0;
    bool negative = false;
    if (i < n && (a.at(i) == '+' || a.at(i) == '-')){
        negative = a.at(i) == '-';
        i++;
    }
    const QString word = a.mid(i).toLower();
    if (word == "inf" || word == "infinity"){
        value = negative ? -std::numeric_limits<double>::infinity() : std::numeric_limits<double>::infinity();
        return true;
    }
    if (word == "nan"){
        value = std::numeric_limits<double>::quiet_NaN();
        return true;
    }
    const auto digit = [&](qsizetype at){ return at < n && a.at(at) >= '0' && a.at(at) <= '9'; };
    const auto digits = [&](qsizetype& at){
        if (!digit(at)){
            return false;
        }
        at++;
        while (at < n){
            if (digit(at)){
                at++;
            }else if (a.at(at) == '_' && digit(at + 1)){
                at += 2;
            }else{
                break;
            }
        }
        return true;
    };
    qsizetype j = i;
    bool have = digits(j);
    if (j < n && a.at(j) == '.'){
        j++;
        qsizetype k = j;
        if (digits(k)){
            j = k;
            have = true;
        }
    }
    if (!have){
        return false;
    }
    bool negative_exponent = false;
    if (j < n && (a.at(j) == 'e' || a.at(j) == 'E')){
        j++;
        if (j < n && (a.at(j) == '+' || a.at(j) == '-')){
            negative_exponent = a.at(j) == '-';
            j++;
        }
        if (!digits(j)){
            return false;
        }
    }
    if (j != n){
        return false;
    }
    a.remove('_');
    bool ok = false;
    value = a.toDouble(&ok);
    if (!ok){                                               //  (more than a double holds: Python gives infinity or zero)
        value = negative_exponent ? 0.0 : (negative ? -std::numeric_limits<double>::infinity() : std::numeric_limits<double>::infinity());
    }
    return true;
}
inline double py_float(const QString& text){
    double value = 0;
    if (!py_parse_float(text, value)){
        throw std::runtime_error(("could not convert string to float: " + py_repr(text)).toStdString());
    }
    return value;
}
inline int py_int(const QString& text){
    bool ok = false;
    const int value = py_strip(text).toInt(&ok);
    if (!ok){
        throw std::runtime_error(("invalid literal for int() with base 10: " + py_repr(text)).toStdString());
    }
    return value;
}


}
}
}
}
#endif
