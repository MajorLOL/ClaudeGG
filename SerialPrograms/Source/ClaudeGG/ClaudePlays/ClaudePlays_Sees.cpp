/*  ClaudeGG Claude Plays: what the program's own readers see
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <vector>
#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "VideoGames/PokemonLZA/Inference/PokemonLZA_DialogDetector.h"
#include "VideoGames/PokemonLZA/Inference/PokemonLZA_MainMenuDetector.h"
#include "ClaudePlays_Sees.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace ClaudePlays{


bool game_has_readers(GameId game){
    return game == GameId::LEGENDS_ZA;
}


LegendsZaFindings legends_za_findings(const ImageViewRGB32& frame){
    using namespace NintendoSwitch::PokemonLZA;
    //  No overlay: nothing is drawn on the video, and the detectors are made
    //  for each picture (they keep state from the last one they looked at).
    LegendsZaFindings findings;
    {
        MainMenuDetector detector(COLOR_RED, nullptr);
        findings.main_menu = detector.detect(frame);
    }
    {
        FlatWhiteDialogDetector detector(COLOR_RED, nullptr);
        findings.white_dialog = detector.detect(frame);
    }
    {
        TransparentBattleDialogDetector detector(COLOR_RED, nullptr);
        findings.battle_dialog = detector.detect(frame);
    }
    {
        BlueDialogDetector detector(COLOR_RED, nullptr);
        findings.blue_dialog = detector.detect(frame);
    }
    return findings;
}

std::string legends_za_words(const LegendsZaFindings& findings){
    std::vector<std::string> found;
    if (findings.main_menu){
        found.emplace_back("the main menu");
    }
    if (findings.white_dialog){
        found.emplace_back("a white dialog box");
    }
    if (findings.battle_dialog){
        found.emplace_back("a transparent battle dialog box");
    }
    if (findings.blue_dialog){
        found.emplace_back("a blue message box");
    }
    std::string words;
    for (size_t c = 0; c < found.size(); c++){
        if (c != 0){
            words += c + 1 == found.size() ? " and " : ", ";
        }
        words += found[c];
    }
    return words;
}


std::string game_sees(GameId game, const ImageViewRGB32& frame){
    switch (game){
    case GameId::LEGENDS_ZA:
        return legends_za_words(legends_za_findings(frame));
    default:
        return std::string();
    }
}


}
}
}
