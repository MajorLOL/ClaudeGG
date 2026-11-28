/*  ClaudeGG Claude Plays: what the program's own readers see, tests
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  game_sees() puts the answers of the readers into words, so these tests do
 *  not measure the readers again: they hold the words to the answers the
 *  readers' own tests (PokemonLZA_DialogDetector.cpp,
 *  PokemonLZA_MainMenuDetector.cpp) already pin on the same stored pictures:
 *    - a picture a reader recognizes has its phrase in the words,
 *    - a picture it does not recognize does not have it,
 *    - the words of the other readers are not asserted either way, as nothing
 *      measured says whether two readers may both answer on one picture,
 *    - the words themselves are tested for every mix of answers,
 *    - a game without readers says nothing, on any picture.
 *  Like the readers' tests, these run again on the pictures re-colored like
 *  other capture cards (ImageUnitTest).
 *
 */

#include <cctype>
#include <string>
#include <vector>
#include "Common/Cpp/CancellableScope.h"
#include "Common/Cpp/TestRunners/UnitTest.h"
#include "CommonFramework/ImageTypes/ImageRGB32.h"
#include "Tests/ImageUnitTest.h"
#include "ClaudePlays_AnyGame.h"
#include "ClaudePlays_Calibrate.h"
#include "ClaudePlays_Consoles.h"
#include "ClaudePlays_KnownGames.h"
#include "ClaudePlays_Sees.h"
#include "ClaudePlays_Sees_Tests.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace ClaudePlays{

namespace{


const char* const MAIN_MENU = "the main menu";
const char* const WHITE = "a white dialog box";
const char* const BATTLE = "a transparent battle dialog box";
const char* const BLUE = "a blue message box";


//  The words for each mix of answers.
class Test_LegendsZaWords : public UnitTest{
public:
    Test_LegendsZaWords()
        : UnitTest("ClaudePlays::SeesWords - Legends Z-A, every mix of answers")
    {}
    virtual UnitTestResult run(Logger&, CancellableScope&) const override{
        std::string failures;
        for (int mix = 0; mix < 16; mix++){
            LegendsZaFindings findings;
            findings.main_menu = (mix & 1) != 0;
            findings.white_dialog = (mix & 2) != 0;
            findings.battle_dialog = (mix & 4) != 0;
            findings.blue_dialog = (mix & 8) != 0;

            //  What the words must hold, in this order.
            std::vector<std::string> expected;
            if (findings.main_menu){
                expected.emplace_back(MAIN_MENU);
            }
            if (findings.white_dialog){
                expected.emplace_back(WHITE);
            }
            if (findings.battle_dialog){
                expected.emplace_back(BATTLE);
            }
            if (findings.blue_dialog){
                expected.emplace_back(BLUE);
            }
            std::string words;
            for (size_t c = 0; c < expected.size(); c++){
                if (c != 0){
                    words += c + 1 == expected.size() ? " and " : ", ";
                }
                words += expected[c];
            }

            const std::string got = legends_za_words(findings);
            if (got != words){
                failures += "mix " + std::to_string(mix) + ": expected \"" + words + "\", received \"" + got + "\". ";
            }
        }

        //  A few of them by hand, so that the loop above is not only the
        //  code over again.
        LegendsZaFindings one;
        one.white_dialog = true;
        if (legends_za_words(one) != "a white dialog box"){
            failures += "one answer: \"" + legends_za_words(one) + "\". ";
        }
        one.blue_dialog = true;
        if (legends_za_words(one) != "a white dialog box and a blue message box"){
            failures += "two answers: \"" + legends_za_words(one) + "\". ";
        }
        LegendsZaFindings all;
        all.main_menu = all.white_dialog = all.battle_dialog = all.blue_dialog = true;
        if (legends_za_words(all) !=
            "the main menu, a white dialog box, a transparent battle dialog box and a blue message box"
        ){
            failures += "all four: \"" + legends_za_words(all) + "\". ";
        }
        if (!legends_za_words(LegendsZaFindings()).empty()){
            failures += "no answer: not empty. ";
        }

        if (!game_has_readers(GameId::LEGENDS_ZA)){
            failures += "Legends Z-A has readers, but game_has_readers() says no. ";
        }
        for (GameId game : all_games()){
            if (game != GameId::LEGENDS_ZA && game_has_readers(game)){
                failures += "A game without measured readers claims to have them: " + game_profile(game).identifier + ". ";
            }
        }
        if (failures.empty()){
            return true;
        }
        return failures;
    }
};


//  What differs from console to console (ClaudePlays_Consoles.h): the
//  table, the box of the game in a capture, and what Claude is told of it.
class Test_ConsoleDifferences : public UnitTest{
public:
    Test_ConsoleDifferences()
        : UnitTest("ClaudePlays::Consoles - timing, its measuring, picture box and yes or no per console")
    {}
    virtual UnitTestResult run(Logger&, CancellableScope&) const override{
        std::string failures;
        console_traits_tests(failures);
        calibration_tests(failures);
        known_games_tests(failures);
        //  The buttons a known game's notes name (the words in capitals)
        //  are those of its list's pad.
        for (GameId list : all_games()){
            const PadLayout& layout = pad_layout(game_profile(list).pad);
            for (const KnownGame* game : known_games(list)){
                for (const std::string* text : {&game->notes, &game->yes_no}){
                    size_t at = 0;
                    while (at < text->size()){
                        //  To the start of the next word; one that does not start
                        //  with a capital ("3D") is skipped whole.
                        while (at < text->size() && !std::isalnum((unsigned char)(*text)[at])){
                            at++;
                        }
                        if (at < text->size() && !((*text)[at] >= 'A' && (*text)[at] <= 'Z')){
                            while (at < text->size() && std::isalnum((unsigned char)(*text)[at])){
                                at++;
                            }
                            continue;
                        }
                        size_t end = at;
                        bool capitals = true;
                        while (end < text->size() && (std::isalnum((unsigned char)(*text)[end]) || (*text)[end] == '_')){
                            capitals = capitals && !((*text)[end] >= 'a' && (*text)[end] <= 'z');
                            end++;
                        }
                        const std::string word = text->substr(at, end - at);
                        if (capitals && !word.empty() && !layout.has_button(word)){
                            failures += "The notes of " + game->slug + " name " + word + ", not a button of the pad. ";
                        }
                        at = end;
                    }
                }
            }
        }
        if (!failures.empty()){
            failures += ". ";
        }

        //  The black around a 4:3 game is left out, and Claude is told so,
        //  only where a console has such games.
        const char* const BARS = "the black around it is left out";
        for (GameId id : all_games()){
            const GameProfile& profile = game_profile(id);
            const ConsoleTraits& traits = console_traits(profile.console);
            AnyGameOptions options;
            options.timing = traits.timing;
            options.picture_aspects = traits.picture_aspects;
            GameFacts facts;
            facts.name = profile.name;
            facts.notes = profile.notes;
            const PadLayout& layout = pad_layout(profile.pad);
            const std::string plain = any_game_instructions(layout, options, facts, profile.save_routine);
            if ((plain.find(BARS) != std::string::npos) == traits.picture_aspects.empty()){
                failures += "The black bars told wrong for " + profile.identifier + ". ";
            }
            if (plain.find(layout.yes_no) == std::string::npos){
                failures += "The controller's yes and no missing for " + profile.identifier + ". ";
            }
            //  A Japanese PlayStation game: CIRCLE is yes, instead of the
            //  controller's usual words.
            facts.yes_no = japanese_yes_no(profile.pad);
            if (!facts.yes_no.empty()){
                const std::string japanese = any_game_instructions(layout, options, facts, profile.save_routine);
                if (japanese.find(facts.yes_no) == std::string::npos ||
                    japanese.find(layout.yes_no) != std::string::npos
                ){
                    failures += "Japanese yes and no not told for " + profile.identifier + ". ";
                }
            }
        }
        if (failures.empty()){
            return true;
        }
        return failures;
    }
};


//  A picture of Legends Z-A: does game_sees() have this phrase?
class Test_Sees : public ImageUnitTest{
public:
    Test_Sees(const std::string& image, const char* phrase, bool expected)
        : ImageUnitTest(
            std::string("ClaudePlays::Sees - ") + image + (expected ? " has \"" : " has not \"") + phrase + "\"",
            {image}
        )
        , m_phrase(phrase)
        , m_expected(expected)
    {}
private:
    UnitTestResult run_on_images(
        Logger&, CancellableScope&,
        const std::vector<ImageRGB32>& images
    ) const override{
        const std::string seen = game_sees(GameId::LEGENDS_ZA, images[0]);
        const bool has = seen.find(m_phrase) != std::string::npos;
        if (has == m_expected){
            return true;
        }
        return std::string(m_expected ? "Expected" : "Not expected") + " \"" + m_phrase + "\" in \"" + seen + "\".";
    }
    std::string m_phrase;
    bool m_expected;
};

//  A game without readers says nothing on a picture the readers of
//  Legends Z-A recognize.
class Test_SeesNothing : public ImageUnitTest{
public:
    Test_SeesNothing(const std::string& image, GameId game)
        : ImageUnitTest(
            "ClaudePlays::SeesNothing - " + game_profile(game).identifier + " on " + image,
            {image}
        )
        , m_game(game)
    {}
private:
    UnitTestResult run_on_images(
        Logger&, CancellableScope&,
        const std::vector<ImageRGB32>& images
    ) const override{
        const std::string seen = game_sees(m_game, images[0]);
        if (seen.empty()){
            return true;
        }
        return "Expected nothing, received \"" + seen + "\".";
    }
    GameId m_game;
};


}


void add_tests_Sees(UnitTestDatabase& database){
    database.add<Test_LegendsZaWords>();
    database.add<Test_ConsoleDifferences>();

    //  The main menu (PokemonLZA_MainMenuDetector.cpp).
    database.add<Test_Sees>("PokemonLZA/MainMenuDetector/french_main_menu_True.png", MAIN_MENU, true);
    database.add<Test_Sees>("PokemonLZA/MainMenuDetector/mac_main_menu_True.png", MAIN_MENU, true);

    //  The white dialog box (PokemonLZA_DialogDetector.cpp).
    const char* const WHITE_DIALOGS[] = {
        "ansha_donuts_welcome_True", "chao_fossil_True", "french_fossil_1_True", "french_fossil_2_True",
        "french_fossil_3_True", "french_fossil_4_True", "french_fossil_5_True", "french_fossil_6_True",
        "french_jacinthe_2_True", "french_jacinthe_3_True", "french_jacinthe_True", "mac_fossil_True",
        "mac_jacinthe_excited_True", "mac_restaurant_True", "mac_seven_wonder_leftout_True",
    };
    for (const char* name : WHITE_DIALOGS){
        database.add<Test_Sees>(std::string("PokemonLZA/FlatWhiteDialogDetector/") + name + ".png", WHITE, true);
    }
    database.add<Test_Sees>(
        "PokemonLZA/FlatWhiteDialogDetector/mac_jacinthe_pre_battle_transparent_False.png", WHITE, false
    );

    //  The transparent dialog box of a battle.
    database.add<Test_Sees>("PokemonLZA/TransparentBattleDialogDetector/french_jacinthe_True.png", BATTLE, true);
    database.add<Test_Sees>("PokemonLZA/TransparentBattleDialogDetector/mac_jacinthe_True.png", BATTLE, true);
    database.add<Test_Sees>("PokemonLZA/TransparentBattleDialogDetector/mac_jacinthe_False.png", BATTLE, false);
    database.add<Test_Sees>("PokemonLZA/TransparentBattleDialogDetector/mac_jacinthe_overworld_False.png", BATTLE, false);

    //  The blue message box.
    database.add<Test_Sees>("PokemonLZA/BlueDialogDetector/mac_cannotFastTravel_True.png", BLUE, true);
    database.add<Test_Sees>("PokemonLZA/BlueDialogDetector/mac_receive_tyrunt_True.png", BLUE, true);
    database.add<Test_Sees>("PokemonLZA/BlueDialogDetector/mac_canFastTravel_False.png", BLUE, false);

    //  The other games have no readers here.
    database.add<Test_SeesNothing>("PokemonLZA/MainMenuDetector/mac_main_menu_True.png", GameId::SCARLET_VIOLET);
    database.add<Test_SeesNothing>("PokemonLZA/FlatWhiteDialogDetector/chao_fossil_True.png", GameId::OTHER_GAMES);
}


}
}
}
