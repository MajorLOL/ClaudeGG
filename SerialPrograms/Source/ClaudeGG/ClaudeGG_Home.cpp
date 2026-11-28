/*  ClaudeGG Home
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <QColor>
#include <QString>
#include "ClaudePlays/ClaudePlays_Games.h"
#include "ClaudeGG_Home.h"
#include "ClaudeGG_WiiU.h"
#include "ClaudeGG_Vita.h"

namespace PokemonAutomation{
namespace ClaudeGG{



namespace{

//  The game of the phone: Pokémon GO (the list of Mobile/, see ClaudeGG_PokemonGo.h).
bool is_pokemon_go(const QString& name){
    return name.startsWith("Pok") && name.endsWith(" GO", Qt::CaseSensitive);
}

}

QStringList consoles_of_game(const QString& name){
    if (is_pokemon_go(name)){
        return QStringList{"mobile"};
    }
    //  The list of the Wii U (ClaudeGG_WiiU.h): its GamePad is a Raspberry Pi.
    if (name == WiiU::WIIU_LIST_NAME){
        return QStringList{"wiiu"};
    }
    //  The list of the PlayStation Vita (ClaudeGG_Vita.h): over the network.
    if (name == Vita::VITA_LIST_NAME){
        return QStringList{"vita"};
    }
    //  The list of another console (the Claude Plays of the PlayStation 3 and
    //  of the original Xbox).
    const std::vector<std::string> others = ClaudePlays::consoles_of_list(name.toStdString());
    if (!others.empty()){
        QStringList consoles;
        for (const std::string& console : others){
            consoles.append(QString::fromStdString(console));
        }
        return consoles;
    }
    return QStringList{"switch", "switch2"};
}

bool game_is_for_console(const HomeGame& game, const QString& console_code){
    return game.consoles.isEmpty() || console_code.isEmpty() || game.consoles.contains(console_code);
}

QString short_game_name(const QString& name){
    //  The series' name is the first word, with an accented letter in it.
    if (name.startsWith("Pok", Qt::CaseInsensitive)){
        const qsizetype space = name.indexOf(' ');
        if (space > 0 && space <= 8 && space + 1 < name.size()){
            const QString rest = name.mid(space + 1);
            //  Not for the ones that would be left as "Home" or "GO".
            if (rest.compare("Home", Qt::CaseInsensitive) != 0 && !is_pokemon_go(name)){
                return rest;
            }
        }
    }
    return name;
}

void game_label_colors(const QString& name, QColor& first, QColor& second){
    struct Entry{
        const char* word;
        QRgb first;
        QRgb second;
    };
    //  The pairs of versions first: each half of the label gets a version.
    static const Entry ENTRIES[] = {
        //  (Pokémon GO is found by its name below: "GO" is in too many others.)
        {"FireRed",         0xffdf5230, 0xff3f9d4e},
        {"Scarlet",         0xffd8402b, 0xff7a4cc4},
        {"Sword",           0xff2f8fd6, 0xffd23a5a},
        {"Brilliant",       0xff4f8fe6, 0xffe38bb0},
        {"Let's Go",        0xffe3b437, 0xff9a693b},
        {"Ruby",            0xffc23048, 0xff2f62c0},
        {"Arceus",          0xff5c6ea8, 0xff5c6ea8},
        {"Z-A",             0xff27a587, 0xff27a587},
        {"Pokopia",         0xffe2875c, 0xffe2875c},
        {"Home",            0xff2c9c93, 0xff2c9c93},
        {"Zelda",           0xff4c8c68, 0xff4c8c68},
        //  The list for whatever else is on the screen (ClaudePlays).
        {"Other Games",     0xff5a55b8, 0xff5a55b8},
    };
    if (is_pokemon_go(name)){
        first = QColor(0x2f, 0x7f, 0xd6);
        second = QColor(0xd2, 0x3a, 0x3a);
        return;
    }
    for (const Entry& entry : ENTRIES){
        if (name.contains(QLatin1String(entry.word), Qt::CaseInsensitive)){
            first = QColor(entry.first);
            second = QColor(entry.second);
            return;
        }
    }
    first = QColor(0x67, 0x6d, 0x84);
    second = first;
}



}
}
