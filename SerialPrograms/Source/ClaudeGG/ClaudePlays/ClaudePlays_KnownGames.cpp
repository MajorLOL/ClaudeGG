/*  ClaudeGG Claude Plays: well-known games of the other consoles
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The notes name buttons only in capitals, and only the list's own (a
 *  test holds them to the pad's names): the rest of a note is plain words.
 *
 */

#include <algorithm>
#include <set>
#include <utility>
#include "ClaudePlays_KnownGames.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace ClaudePlays{


namespace{

std::vector<KnownGame> make_known_games(){
    std::vector<KnownGame> games;
    auto add = [&](GameId list, const char* slug, const char* name, const char* notes, const char* yes_no, int frame_rate){
        games.push_back(KnownGame{list, slug, name, notes, yes_no, frame_rate, ""});
    };
    auto add_on = [&](const char* console, const char* slug, const char* name, const char* notes, const char* yes_no){
        games.push_back(KnownGame{GameId::OTHER_GAMES, slug, name, notes, yes_no, 0, console});
    };

    //  The first PlayStation.
    add(
        GameId::PLAYSTATION_1, "ff7", "Final Fantasy VII",
        "This is a turn-based role-playing game. The d-pad walks, CIRCLE talks, examines and picks, CROSS cancels, "
        "TRIANGLE opens the menu. In battle each character's commands come up when the character's bar "
        "is full: CIRCLE picks one and its target, CROSS goes back.",
        "In this game CIRCLE is yes and CROSS no or back, in every region.",
        15
    );
    add(
        GameId::PLAYSTATION_1, "crash", "Crash Bandicoot",
        "This is a platform game: the d-pad runs, CROSS jumps, SQUARE spins (it breaks crates and beats enemies), "
        "START pauses.",
        "", 0
    );
    add(
        GameId::PLAYSTATION_1, "gran-turismo", "Gran Turismo",
        "This is a racing game: the d-pad steers, CROSS accelerates, SQUARE brakes. In the menus CROSS picks and "
        "TRIANGLE goes back. The race goes on while Claude thinks: prefer holding a button for a while over "
        "many short presses.",
        "", 0
    );

    //  The PlayStation 2.
    add(
        GameId::PLAYSTATION_2, "ffx", "Final Fantasy X",
        "This is a turn-based role-playing game. The left stick walks, CROSS talks, examines and picks, CIRCLE "
        "cancels, TRIANGLE opens the menu. In battle the turn order is shown at the right: CROSS picks a "
        "command and its target, CIRCLE goes back.",
        "", 0
    );
    add(
        GameId::PLAYSTATION_2, "kingdom-hearts", "Kingdom Hearts",
        "An action role-playing game. The left stick walks, CROSS does the command chosen in the menu at "
        "the bottom left (Attack, Talk, Open, ...; the d-pad moves through it), CIRCLE jumps, R1 locks "
        "on, L2 and R2 turn the camera, START pauses.",
        "Outside Japan CROSS is yes and CIRCLE no in this game; in the Japanese version the other way "
        "round.",
        0
    );
    add(
        GameId::PLAYSTATION_2, "gta-sa", "Grand Theft Auto: San Andreas",
        "An open-world game. On foot: the left stick walks, CROSS held sprints, SQUARE jumps, CIRCLE "
        "attacks, R1 held aims, TRIANGLE gets into a vehicle. In a car: CROSS accelerates, SQUARE brakes "
        "and reverses, TRIANGLE gets out. START opens the pause menu with the map. The game saves only "
        "at the safe houses.",
        "", 0
    );

    //  The Nintendo 64.
    add(
        GameId::NINTENDO_64, "mario64", "Super Mario 64",
        "This is a 3D platform game. The stick runs, A jumps (again on landing: higher), B punches (while "
        "running: a dive), Z crouches (in the air: a ground pound), C_UP to C_RIGHT move the camera, R "
        "changes how it follows, START pauses. The paintings in the castle lead to the courses.",
        "", 0
    );
    add(
        GameId::NINTENDO_64, "zelda-oot", "The Legend of Zelda: Ocarina of Time",
        "An action adventure. The stick walks, A does the action named at the top of the screen (talk, "
        "open, climb, roll while running), B swings the sword, C_LEFT, C_DOWN and C_RIGHT use the items "
        "set on them, C_UP looks around, Z targets, R raises the shield. START opens the menus, where Z "
        "and R turn the pages.",
        "", 20
    );
    add(
        GameId::NINTENDO_64, "mario-kart-64", "Mario Kart 64",
        "This is a racing game: the stick steers, A accelerates, B brakes, Z uses the item, R hops and, held "
        "while steering, drifts. START pauses. The race goes on while Claude thinks: prefer holding a "
        "button for a while over many short presses.",
        "", 0
    );
    add(
        GameId::NINTENDO_64, "goldeneye", "GoldenEye 007",
        "This is a first-person shooter. By default the stick walks forward and back and turns, C_LEFT and C_RIGHT "
        "step to the side, C_UP and C_DOWN look up and down, Z fires, R held aims, B opens doors and uses, "
        "A changes the weapon. START opens the watch (the menu).",
        "", 20
    );

    //  The GameCube.
    add(
        GameId::GAMECUBE, "melee", "Super Smash Bros. Melee",
        "This is a fighting game. The stick moves, A attacks, B does a special move, X or Y jumps, L or R "
        "shields, Z grabs, the second stick does smash attacks. START pauses. In the menus A picks and B goes "
        "back.",
        "", 0
    );
    add(
        GameId::GAMECUBE, "wind-waker", "The Legend of Zelda: The Wind Waker",
        "An action adventure. The stick walks, A does the action named at the top right (talk, open, "
        "climb, roll while running), B swings the sword, X, Y and Z use the items set on them, L targets, "
        "the second stick (the yellow one) turns the camera. START opens the menus.",
        "", 0
    );
    add(
        GameId::GAMECUBE, "mario-kart-dd", "Mario Kart: Double Dash!!",
        "This is a racing game with two drivers on each kart: the stick steers, A accelerates, B brakes, R hops "
        "and, held while steering, drifts, X or Y uses the item, Z swaps the drivers. START pauses.",
        "", 0
    );

    //  The Dreamcast.
    add(
        GameId::DREAMCAST, "sonic-adventure", "Sonic Adventure",
        "This is a 3D platform game. The stick runs, A jumps (again in the air, as Sonic: an attack at the "
        "nearest enemy), B or X does the action (picks up, and held: a spin dash), L and R turn the "
        "camera. START pauses.",
        "", 0
    );

    //  The PlayStation Classic: games it came with.
    add(
        GameId::PS_CLASSIC, "psc-ff7", "Final Fantasy VII",
        "This is a turn-based role-playing game. The d-pad walks, CIRCLE talks, examines and picks, CROSS cancels, "
        "TRIANGLE opens the menu. In battle each character's commands come up when the character's bar "
        "is full: CIRCLE picks one and its target, CROSS goes back.",
        "In this game CIRCLE is yes and CROSS no or back, in every region.",
        15
    );
    add(
        GameId::PS_CLASSIC, "psc-tekken3", "Tekken 3",
        "This is a fighting game. Each button is a limb: SQUARE the left punch, TRIANGLE the right punch, CROSS "
        "the left kick, CIRCLE the right kick. The d-pad walks and, held away from the other fighter, blocks; UP "
        "jumps, DOWN crouches. START pauses.",
        "", 0
    );
    add(
        GameId::PS_CLASSIC, "psc-rayman", "Rayman",
        "This is a 2D platform game: the d-pad runs, CROSS jumps, SQUARE punches (once Rayman has the fist), "
        "START pauses. Each level ends at its sign; the cages of the level free the Electoons.",
        "", 0
    );

    //  The PlayStation 3.
    add(
        GameId::PLAYSTATION_3, "ps3-minecraft", "Minecraft: PlayStation 3 Edition",
        "This is a game of building and surviving in a world of blocks. The left stick walks, the right stick looks, "
        "CROSS jumps, R2 held breaks a block or attacks, L2 places a block or uses the item in hand, L1 and R1 "
        "pick in the bar of items at the bottom, TRIANGLE opens the inventory, SQUARE the crafting, CIRCLE drops "
        "the item, R3 crouches. START pauses and saves.",
        "", 0
    );
    add(
        GameId::PLAYSTATION_3, "ps3-uncharted2", "Uncharted 2: Among Thieves",
        "An action adventure that shoots from behind the player. The left stick walks, the right stick turns "
        "the camera, CROSS jumps and climbs, CIRCLE takes cover and rolls, SQUARE punches, TRIANGLE picks up a "
        "weapon, L1 held aims and R1 fires, L2 throws a grenade. START pauses.",
        "", 0
    );
    add(
        GameId::PLAYSTATION_3, "ps3-persona5", "Persona 5",
        "This is a turn-based role-playing game that is half school life. The left stick walks, CIRCLE talks, examines "
        "and picks, CROSS cancels, TRIANGLE opens the menu. In battle each command is shown next to the button "
        "that gives it.",
        "In this game CIRCLE is yes and CROSS no or back, in every region.",
        0
    );

    //  The original Xbox.
    add(
        GameId::ORIGINAL_XBOX, "xbox-halo", "Halo: Combat Evolved",
        "This is a first-person shooter. The left stick walks, the right stick looks, RT fires, LT throws a "
        "grenade, A jumps, B strikes, X reloads and, held, picks up or uses, Y changes the weapon, WHITE turns "
        "the flashlight on and off, RSTICK zooms. START pauses.",
        "", 0
    );

    //  The Xbox 360.
    add(
        GameId::XBOX_360, "x360-minecraft", "Minecraft: Xbox 360 Edition",
        "This is a game of building and surviving in a world of blocks. The left stick walks, the right stick looks, "
        "A jumps, RT held breaks a block or attacks, LT places a block or uses the item in hand, LB and RB pick "
        "in the bar of items at the bottom, Y opens the inventory, X the crafting, B drops the item, RSTICK "
        "crouches. START pauses and saves.",
        "", 0
    );
    add(
        GameId::XBOX_360, "x360-halo3", "Halo 3",
        "This is a first-person shooter. The left stick walks, the right stick looks, RT fires, LT throws a "
        "grenade, A jumps, B strikes, RB reloads and, held, picks up or uses, X uses the equipment, Y changes "
        "the weapon, RSTICK zooms. START pauses.",
        "", 0
    );

    //  The PlayStation 4 and 5, through Remote Play and direct: the same
    //  games, in both lists.
    for (GameId list : {GameId::PS_REMOTE_PLAY, GameId::PS_DIRECT}){
        add(
            list, "ps4-minecraft", "Minecraft",
            "This is a game of building and surviving in a world of blocks. The left stick walks, the right stick looks, "
            "CROSS jumps, R2 held breaks a block or attacks, L2 places a block or uses the item in hand, L1 and R1 "
            "pick in the bar of items at the bottom, TRIANGLE opens the inventory, R3 crouches. OPTIONS pauses.",
            "", 0
        );
        add(
            list, "ps4-persona5", "Persona 5 Royal",
            "This is a turn-based role-playing game that is half school life. The left stick walks, CIRCLE talks, examines "
            "and picks, CROSS cancels, TRIANGLE opens the menu. In battle each command is shown next to the "
            "button that gives it.",
            "In this game CIRCLE is yes and CROSS no or back, in every region.",
            0
        );
        add(
            list, "ps4-stardew", "Stardew Valley",
            "This is a farming and life game without hurry: a day goes by in about a quarter of an hour. The left stick "
            "walks, CROSS does the action on what is in front (talk, harvest, open, pick up), SQUARE uses the "
            "tool or item in hand, CIRCLE opens the menu with the bag, L1 and R1 pick in the toolbar. The game "
            "saves when the farmer goes to bed.",
            "", 0
        );
    }

    //  The Xbox One and Series, through Remote Play and direct, and Steam:
    //  the pad of an Xbox One.
    for (GameId list : {GameId::XBOX_REMOTE_PLAY, GameId::XBOX_DIRECT, GameId::STEAM}){
        if (list != GameId::STEAM){
            add(
                list, "xone-minecraft", "Minecraft",
                "This is a game of building and surviving in a world of blocks. The left stick walks, the right stick "
                "looks, A jumps, RT held breaks a block or attacks, LT places a block or uses the item in hand, LB "
                "and RB pick in the bar of items at the bottom, Y opens the inventory, RSTICK crouches. MENU pauses.",
                "", 0
            );
        }
        add(
            list, "xone-stardew", "Stardew Valley",
            "This is a farming and life game without hurry: a day goes by in about a quarter of an hour. The left stick "
            "walks, A does the action on what is in front (talk, harvest, open, pick up), X uses the tool or "
            "item in hand, B opens the menu with the bag, LB and RB pick in the toolbar. The game saves when "
            "the farmer goes to bed.",
            "", 0
        );
    }
    add(
        GameId::STEAM, "steam-celeste", "Celeste",
        "This is a hard 2D platform game of short screens. The d-pad or the left stick runs, A jumps, X dashes once in "
        "the air in the direction held (it comes back on landing), RT held grabs and climbs a wall. MENU pauses. "
        "Dying only starts the screen again: try the same jump more than once.",
        "", 0
    );

    //  The consoles over Wi-Fi, with programs of their own.
    add_on(
        "wiiu", "wiiu-mario-kart-8", "Mario Kart 8",
        "This is a racing game: the left stick steers, A accelerates, B brakes, R hops and, held while "
        "steering, drifts, L or ZL uses the item. PLUS pauses. The race goes on while Claude thinks: prefer "
        "holding a button for a while over many short presses.",
        ""
    );
    add_on(
        "wiiu", "wiiu-3d-world", "Super Mario 3D World",
        "This is a 3D platform game. The left stick runs, A or B jumps, X or Y held dashes and picks up, ZL or "
        "ZR crouches (in the air: a ground pound), R turns the camera a little. PLUS pauses. Each level ends "
        "at the flagpole.",
        ""
    );
    add_on(
        "wiiu", "wiiu-nsmbu", "New Super Mario Bros. U",
        "This is a 2D platform game: the left stick or the d-pad runs, A or B jumps, X or Y held runs fast and "
        "picks up a shell (let go: a throw). PLUS pauses. Each level ends at the flagpole; the map between them "
        "is walked with the d-pad, A enters a level.",
        ""
    );
    add_on(
        "vita", "vita-persona4g", "Persona 4 Golden",
        "This is a turn-based role-playing game that is half school life. The left stick walks, CROSS talks, "
        "examines and picks, CIRCLE cancels, TRIANGLE opens the menu. In battle the commands are a menu: the "
        "d-pad moves in it, CROSS picks a command and its target.",
        "Outside Japan CROSS is yes and CIRCLE no in this game; in the Japanese version the other way round."
    );
    add_on(
        "vita", "vita-ffx", "Final Fantasy X HD Remaster",
        "This is a turn-based role-playing game. The left stick walks, CROSS talks, examines and picks, CIRCLE "
        "cancels, TRIANGLE opens the menu. In battle the turn order is shown at the right: CROSS picks a "
        "command and its target, CIRCLE goes back.",
        ""
    );
    add_on(
        "vita", "vita-stardew", "Stardew Valley",
        "This is a farming and life game without hurry: a day goes by in about a quarter of an hour. The left "
        "stick walks, CROSS does the action on what is in front (talk, harvest, open, pick up), SQUARE uses the "
        "tool or item in hand, CIRCLE opens the menu with the bag, L and R pick in the toolbar. The game saves "
        "when the farmer goes to bed.",
        ""
    );
    add_on(
        "3ds", "3ds-pokemon-sm", "Pok\xc3\xa9mon Sun and Moon",
        "This is a turn-based role-playing game. The circle pad (the left stick here) walks, B held runs, A "
        "talks, examines and confirms, B cancels, X opens the menu. In battle the commands are on both "
        "screens: A picks the one with the cursor, B goes back; a touch on the lower screen works too.",
        ""
    );
    add_on(
        "3ds", "3ds-animal-crossing", "Animal Crossing: New Leaf",
        "This is a life game in a town of animals, without hurry; it goes by the console's clock. The circle pad (the "
        "left stick here) walks, B held runs, A talks, picks up and uses the tool in hand, B cancels, X opens "
        "the pockets. START opens the menu to save and stop.",
        ""
    );
    add_on(
        "3ds", "3ds-mario-kart-7", "Mario Kart 7",
        "This is a racing game: the circle pad (the left stick here) steers, A accelerates, B brakes, R hops "
        "and, held while steering, drifts, L uses the item. START pauses. The race goes on while Claude thinks: "
        "prefer holding a button for a while over many short presses.",
        ""
    );
    return games;
}

const std::vector<KnownGame>& all_known_games(){
    static const std::vector<KnownGame> games = make_known_games();
    return games;
}

}   //  namespace


std::vector<const KnownGame*> known_games(GameId list){
    std::vector<const KnownGame*> games;
    for (const KnownGame& game : all_known_games()){
        if (game.list == list && game.console.empty()){
            games.push_back(&game);
        }
    }
    return games;
}
std::vector<const KnownGame*> known_games_on(const std::string& console){
    std::vector<const KnownGame*> games;
    for (const KnownGame& game : all_known_games()){
        if (!console.empty() && game.console == console){
            games.push_back(&game);
        }
    }
    return games;
}

InputTiming timing_for_game(const InputTiming& base, int frame_rate){
    if (frame_rate <= 0 || frame_rate >= 30){
        return base;
    }
    InputTiming timing = base;
    const int frame_ms = (1000 + frame_rate - 1) / frame_rate;
    timing.direction_ms = std::max(timing.direction_ms, 3 * frame_ms);
    timing.press_ms = std::max(timing.press_ms, timing.direction_ms + 30);
    timing.gap_ms = std::max(timing.gap_ms, 2 * timing.press_ms);
    timing.settle_ms = std::max(timing.settle_ms, 4 * frame_ms);
    return timing;
}


int known_games_tests(std::string& report){
    int wrong = 0;
    auto fail = [&](const std::string& what){
        wrong++;
        report += (report.empty() ? "" : "\n") + what;
    };
    //  A slug once in each list (a game can be in several lists).
    std::set<std::pair<int, std::string>> slugs;
    for (const KnownGame& game : all_known_games()){
        //  A console over Wi-Fi with a program of its own: one with traits.
        if (!game.console.empty()){
            if (console_traits(game.console).code != game.console || game.frame_rate != 0){
                fail(game.slug + " is for a console without traits");
            }
        }
        //  Only in the lists of consoles that do not know their game.
        const GameProfile& list = game_profile(game.list);
        if (game.console.empty() && (!list.name.empty() || list.console == "switch")){
            fail(game.slug + " is in the list of a game, not of a console");
        }
        if (game.slug.empty() || game.name.empty() || game.notes.empty() || !slugs.insert({game.console.empty() ? (int)game.list : -1, game.console + game.slug}).second ||
            game.slug == "none" || game.notes.back() != '.' || (!game.yes_no.empty() && game.yes_no.back() != '.')
        ){
            fail("the entry " + game.slug);
        }
    }
    //  A game at 20 frames a second: a direction held at least three of
    //  them; at 60, the console's own timing.
    const InputTiming base = console_traits("retro").timing;
    const InputTiming slow = timing_for_game(base, 20);
    if (slow.direction_ms < 150 || slow.press_ms < slow.direction_ms || slow.gap_ms < slow.press_ms){
        fail("the timing of a game at 20 frames a second");
    }
    const InputTiming fast = timing_for_game(base, 60);
    if (fast.direction_ms != base.direction_ms || fast.press_ms != base.press_ms || fast.gap_ms != base.gap_ms){
        fail("the timing of a game at 60 frames a second");
    }
    if (known_games(GameId::NINTENDO_64).empty() || !known_games(GameId::SCARLET_VIOLET).empty() ||
        known_games(GameId::PLAYSTATION_3).empty() || known_games(GameId::STEAM).empty() ||
        known_games_on("wiiu").empty() || known_games_on("vita").empty() || known_games_on("3ds").empty() ||
        !known_games_on("switch").empty() || !known_games_on("").empty()
    ){
        fail("the lists of the known games");
    }
    return wrong;
}



}
}
}
