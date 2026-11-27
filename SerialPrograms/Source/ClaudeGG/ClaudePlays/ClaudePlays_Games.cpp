/*  ClaudeGG Claude Plays: the games
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The notes say only what is certain: the controls as the games' manuals
 *  and the routines of this program's other programs have them. Claude is
 *  told to go by the buttons the screen shows.
 *
 */

#include <map>
#include "Pokemon/Pokemon_Strings.h"
#include "ClaudePlays_Games.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace ClaudePlays{


const char* const OTHER_GAMES_LIST = "Other Games";


namespace{

std::map<GameId, GameProfile> make_profiles(){
    const std::string& POKEMON = Pokemon::STRING_POKEMON;
    std::map<GameId, GameProfile> profiles;
    auto add = [&](GameProfile profile){
        profiles[profile.id] = std::move(profile);
    };

    add(GameProfile{
        GameId::OTHER_GAMES,
        "OtherGames:ClaudePlays",
        OTHER_GAMES_LIST,
        "",
        "whatever game is on the screen",
        "",
        PadKind::PRO_CONTROLLER,
        false,
    });
    add(GameProfile{
        GameId::POKEMON_HOME,
        "PokemonHome:ClaudePlays",
        POKEMON + " Home",
        "Pokemon HOME, the app that keeps Pokemon in boxes and moves them between games",
        POKEMON + " HOME",
        "It is an app, not a game: the stick or the d-pad moves the cursor, A picks, B goes back. What is "
        "moved or released there is final once the app has saved it: do only what the goal names.",
        PadKind::PRO_CONTROLLER,
        false,
    });
    add(GameProfile{
        GameId::LETS_GO,
        "PokemonLGPE:ClaudePlays",
        POKEMON + " LGPE",
        "Pokemon Let's Go, Pikachu! or Let's Go, Eevee!",
        POKEMON + " Let's Go, Pikachu! and Let's Go, Eevee!",
        "The stick walks and moves the cursor, A confirms and talks, B cancels, X opens the menu. Catching a "
        "wild Pokemon takes a throwing motion of the controller, which the program cannot make: an encounter "
        "can only be left again, with the button the screen shows for running away.",
        PadKind::RIGHT_JOYCON,
        false,
    });
    add(GameProfile{
        GameId::SWORD_SHIELD,
        "PokemonSwSh:ClaudePlays",
        POKEMON + " SwSh",
        "Pokemon Sword or Shield",
        POKEMON + " Sword and Shield",
        "The left stick walks, the right stick turns the camera in the Wild Area. A confirms and talks, B "
        "cancels, X opens the menu, Y opens Y-Comm, PLUS gets on and off the bike.",
        PadKind::PRO_CONTROLLER,
        true,
    });
    add(GameProfile{
        GameId::BRILLIANT_DIAMOND_SHINING_PEARL,
        "PokemonBDSP:ClaudePlays",
        POKEMON + " BDSP",
        "Pokemon Brilliant Diamond or Shining Pearl",
        POKEMON + " Brilliant Diamond and Shining Pearl",
        "The left stick or the d-pad walks, and B held runs. A confirms and talks, B cancels, X opens the "
        "menu.",
        PadKind::PRO_CONTROLLER,
        true,
    });
    add(GameProfile{
        GameId::LEGENDS_ARCEUS,
        "PokemonLA:ClaudePlays",
        POKEMON + " LA",
        "Pokemon Legends: Arceus",
        POKEMON + " Legends: Arceus",
        "The left stick walks (pressed in: run), the right stick turns the camera. A talks, picks up and "
        "confirms, B crouches and goes back in menus, Y rolls out of the way. X switches between items and "
        "Pokemon to throw, L and R pick which one, ZR aims while held and throws when let go, ZL locks on. "
        "PLUS calls the ride Pokemon, MINUS opens the map, UP on the d-pad opens the satchel and the menu.",
        PadKind::PRO_CONTROLLER,
        true,
    });
    add(GameProfile{
        GameId::SCARLET_VIOLET,
        "PokemonSV:ClaudePlays",
        POKEMON + " SV",
        "Pokemon Scarlet or Violet",
        POKEMON + " Scarlet and Violet",
        "The left stick walks, the right stick turns the camera, L puts the camera behind the player. A "
        "talks, picks up and confirms, B cancels (on foot it crouches, on the ride Pokemon it jumps), X opens "
        "the main menu, Y the map, PLUS gets on and off the ride Pokemon, MINUS opens the Pokedex. ZR throws "
        "the first Pokemon's ball (at a wild Pokemon: a battle), R sends it out to fight on its own, ZL "
        "locks on.",
        PadKind::PRO_CONTROLLER,
        true,
    });
    add(GameProfile{
        GameId::LEGENDS_ZA,
        "PokemonLZA:ClaudePlays",
        POKEMON + " LZA",
        "Pokemon Legends: Z-A",
        POKEMON + " Legends: Z-A",
        "The left stick walks, the right stick turns the camera, B held runs. X opens the main menu, PLUS "
        "the map. Battles happen in real time, where the player stands.",
        PadKind::PRO_CONTROLLER,
        true,
    });
    add(GameProfile{
        GameId::POKOPIA,
        "PokemonPokopia:ClaudePlays",
        POKEMON + " Pokopia",
        "Pokemon Pokopia",
        POKEMON + " Pokopia",
        "A life simulation with Pokemon, not a game of battles.",
        PadKind::PRO_CONTROLLER,
        false,
    });
    add(GameProfile{
        GameId::RUBY_SAPPHIRE_EMERALD,
        "PokemonRSE:ClaudePlays",
        POKEMON + " RSE",
        "Pokemon Ruby, Sapphire or Emerald",
        POKEMON + " Ruby, Sapphire, and Emerald",
        "A Game Boy Advance game: the d-pad walks, A confirms and talks, B cancels, START is PLUS and SELECT "
        "is MINUS on this controller. The overworld is a grid of tiles. Leave ZL and ZR alone: they are not "
        "the game's.",
        PadKind::PRO_CONTROLLER,
        false,
    });
    add(GameProfile{
        GameId::ZELDA_TOTK,
        "ZeldaTotK:ClaudePlays",
        "Zelda: TotK",
        "The Legend of Zelda: Tears of the Kingdom",
        "The Legend of Zelda: Tears of the Kingdom",
        "The left stick walks, the right stick turns the camera. A talks, picks up and confirms, B cancels, "
        "puts the weapon away and, held, sprints. X jumps, Y strikes, ZL raises the shield and locks on, ZR "
        "draws the bow, R throws, L uses the chosen ability. PLUS opens the inventory, MINUS the map.",
        PadKind::PRO_CONTROLLER,
        false,
    });
    add(GameProfile{
        GameId::OCTOPATH_TRAVELER_0,
        "OctopathTraveler0:ClaudePlays",
        "Octopath Traveler 0",
        "Octopath Traveler 0",
        "Octopath Traveler 0",
        "A turn-based role-playing game. The left stick walks, B dashes. A talks, examines and confirms, B "
        "cancels, X opens the menu, Y uses the character's Path Action (on the people of a town), L and R "
        "switch between the tabs of a menu, ZL opens the map of the area.",
        PadKind::PRO_CONTROLLER,
        false,
    });
    add(GameProfile{
        GameId::MARIO_KART_8_DELUXE,
        "MarioKart8Deluxe:ClaudePlays",
        "Mario Kart 8 DX",
        "Mario Kart 8 Deluxe",
        "Mario Kart 8 Deluxe",
        "The left stick steers. A accelerates, B brakes and, held, reverses. L or ZL uses the item, R or ZR "
        "hops and, held while steering, drifts. X looks behind, PLUS pauses. The game has assists for "
        "steering and acceleration: whether they are on shows in its options. A race goes on while Claude "
        "thinks, so one decision is a long time on the track: prefer holding a button for a moment over "
        "many short presses.",
        PadKind::PRO_CONTROLLER,
        false,
    });
    add(GameProfile{
        GameId::SPLATOON_3,
        "Splatoon3:ClaudePlays",
        "Splatoon 3",
        "Splatoon 3",
        "Splatoon 3",
        "The left stick moves, the right stick turns the camera and aims. B jumps. ZR fires the main weapon, "
        "R uses the sub weapon, ZL turns into a squid and back (swimming in the player's own ink refills "
        "it), pressing the right stick in uses the special weapon when it is charged. Y resets the camera, X "
        "opens the menu. The game can also aim by the motion of the controller, which the program cannot "
        "make: aim with the right stick.",
        PadKind::PRO_CONTROLLER,
        false,
    });
    add(GameProfile{
        GameId::ANIMAL_CROSSING_NEW_HORIZONS,
        "AnimalCrossingNH:ClaudePlays",
        "Animal Crossing NH",
        "Animal Crossing: New Horizons",
        "Animal Crossing: New Horizons",
        "A life simulation that runs on the Switch's clock, and saves by itself now and then. The left stick "
        "walks, and B held runs. A talks, picks up, uses the tool in hand and enters houses, B cancels, X "
        "opens the pockets, Y picks up an item that lies on the ground, ZL opens the NookPhone.",
        PadKind::PRO_CONTROLLER,
        false,
    });
    {
        //  Not one game: the console. The program does not know which game
        //  is in it, so it has no name for Claude.
        GameProfile ps3{
            GameId::PLAYSTATION_3,
            "PlayStation3:ClaudePlays",
            "PlayStation 3",
            "",
            "PlayStation 3 games",
            "The console is a PlayStation 3. On it, CROSS usually confirms and CIRCLE goes back (on a "
            "Japanese console, and in some Japanese games, the other way round). START opens a game's menu "
            "in many games, and the PS button (HOME here) the console's own menu. The board that plays the "
            "controller is a plain USB gamepad to the console, not its own controller: L2 and R2 are only "
            "pressed fully, there is no motion sensing and no rumble.",
            PadKind::PS3_CONTROLLER,
            false,
        };
        ps3.console = "ps3";
        add(std::move(ps3));
    }
    {
        GameProfile xbox{
            GameId::ORIGINAL_XBOX,
            "OriginalXbox:ClaudePlays",
            "Original Xbox",
            "",
            "Original Xbox games",
            "The console is the original Xbox. On it, A usually confirms and B goes back. START opens a "
            "game's menu in many games. Its controller has no button for the console's menu. The pad is "
            "played through an adapter (a board that is a Switch pad, passed on as an Xbox pad): WHITE, "
            "BLACK, LT and RT are only pressed fully, and there is no rumble.",
            PadKind::XBOX_CONTROLLER,
            false,
        };
        xbox.console = "xbox";
        add(std::move(xbox));
    }
    //  The retro consoles: a wireless board through a BlueRetro adapter.
    const char* const BLUERETRO =
        " The pad is played through an adapter (BlueRetro, which takes a Bluetooth pad and passes it on as "
        "this console's own): there is no rumble.";
    auto retro = [&](GameId id, const char* identifier, const char* category, const char* title, std::string notes, PadKind pad){
        GameProfile profile{id, identifier, category, "", title, std::move(notes), pad, false};
        profile.console = "retro";
        add(std::move(profile));
    };
    retro(
        GameId::PLAYSTATION_1, "PlayStation:ClaudePlays", "PlayStation", "PlayStation games",
        std::string("The console is the first PlayStation. In most games CROSS confirms and CIRCLE goes back (in "
        "many Japanese games the other way round), and START opens the game's menu. Its pad has no button for "
        "the console's menu. Games save only to a memory card, from a save point or the game's menu.") + BLUERETRO,
        PadKind::PS1_CONTROLLER
    );
    retro(
        GameId::PLAYSTATION_2, "PlayStation2:ClaudePlays", "PlayStation 2", "PlayStation 2 games",
        std::string("The console is a PlayStation 2. In most games CROSS confirms and CIRCLE goes back (in many "
        "Japanese games the other way round), and START opens the game's menu. Its pad has no button for the "
        "console's menu. The buttons are only pressed fully, never half (some games use the pressure).") + BLUERETRO,
        PadKind::PS2_CONTROLLER
    );
    retro(
        GameId::GAMECUBE, "GameCube:ClaudePlays", "GameCube", "GameCube games",
        std::string("The console is a Nintendo GameCube. In most games A confirms and B goes back, START opens the "
        "game's menu. The C stick is the second stick. L and R are only pressed fully. Its pad has no button "
        "for the console's menu.") + BLUERETRO,
        PadKind::GAMECUBE_CONTROLLER
    );
    retro(
        GameId::NINTENDO_64, "Nintendo64:ClaudePlays", "Nintendo 64", "Nintendo 64 games",
        std::string("The console is a Nintendo 64. In most games A confirms and B goes back, START opens the game's "
        "menu or pauses. C_UP, C_DOWN, C_LEFT and C_RIGHT are the yellow buttons, often the camera. Z is the "
        "trigger under the pad. The stick is the one in the middle of the pad. Its pad has no button for the "
        "console's menu.") + BLUERETRO,
        PadKind::N64_CONTROLLER
    );
    retro(
        GameId::DREAMCAST, "Dreamcast:ClaudePlays", "Dreamcast", "Dreamcast games",
        std::string("The console is a Sega Dreamcast. In most games A confirms and B goes back, START opens the "
        "game's menu or pauses. L and R are triggers and only pressed fully. Its pad has no button for the "
        "console's menu.") + BLUERETRO,
        PadKind::DREAMCAST_CONTROLLER
    );
    //  The Xbox 360, Remote Play and the iPhone: a console of the setup each.
    auto other = [&](GameId id, const char* identifier, const char* category, const char* title, std::string notes, PadKind pad, const char* console){
        GameProfile profile{id, identifier, category, "", title, std::move(notes), pad, false};
        profile.console = console;
        add(std::move(profile));
    };
    other(
        GameId::XBOX_360, "Xbox360:ClaudePlays", "Xbox 360", "Xbox 360 games",
        "The console is an Xbox 360. On it, A usually confirms and B goes back, START opens a game's menu in "
        "many games, and the Guide button (HOME here) the console's own guide. The pad is played through an "
        "adapter (a board that is a Switch pad, passed on as an Xbox 360 pad): LT and RT are only pressed "
        "fully, and there is no rumble.",
        PadKind::XBOX360_CONTROLLER, "xbox360"
    );
    other(
        GameId::PS_REMOTE_PLAY, "PSRemotePlay:ClaudePlays", "PlayStation Remote Play", "PS4 and PS5 games",
        "The console is a PlayStation 4 or 5, played through Remote Play: the picture is its stream on the "
        "computer, and comes a moment late. CROSS usually confirms and CIRCLE goes back (on a Japanese console "
        "the other way round). OPTIONS opens a game's menu, the PS button (HOME here) the console's own. The "
        "pad is a USB gamepad of the computer that the Remote Play client passes on: there is no touchpad, "
        "no motion sensing and no rumble, and L2 and R2 are only pressed fully.",
        PadKind::PS4_CONTROLLER, "psremote"
    );
    other(
        GameId::XBOX_REMOTE_PLAY, "XboxRemotePlay:ClaudePlays", "Xbox Remote Play", "Xbox One and Series games",
        "The console is an Xbox One or an Xbox Series X|S, played through Remote Play: the picture is its "
        "stream on the computer, and comes a moment late. A usually confirms and B goes back. MENU opens a "
        "game's menu, VIEW its map or a second screen in many games. The Xbox button is not passed on. The "
        "pad is a USB gamepad of the computer that the Remote Play client passes on: LT and RT are only "
        "pressed fully, and there is no rumble.",
        PadKind::XBOXONE_CONTROLLER, "xboxremote"
    );
    other(
        GameId::IPHONE, "iPhone:ClaudePlays", "iPhone", "iPhone apps",
        "The device is an iPhone, worked with a keyboard through Full Keyboard Access (an accessibility "
        "setting): a frame shows which item has the focus. TAB goes to the next item and SHIFT_TAB back, the "
        "arrow keys move between items, SPACE taps the item that has the focus, ESCAPE goes back, HOME goes "
        "to the home screen. Games that want touches on the screen itself cannot be played this way: this is "
        "for apps and their menus.",
        PadKind::IPHONE_KEYBOARD, "iphone"
    );
    return profiles;
}

}   //  namespace


const GameProfile& game_profile(GameId id){
    //  On the first call: the names of the series are strings of another
    //  file, which have to be there first.
    static const std::map<GameId, GameProfile> profiles = make_profiles();
    return profiles.at(id);
}

bool has_only_claude_plays(GameId id){
    switch (id){
    case GameId::OCTOPATH_TRAVELER_0:
    case GameId::MARIO_KART_8_DELUXE:
    case GameId::SPLATOON_3:
    case GameId::ANIMAL_CROSSING_NEW_HORIZONS:
    case GameId::PLAYSTATION_3:
    case GameId::ORIGINAL_XBOX:
    case GameId::PLAYSTATION_1:
    case GameId::PLAYSTATION_2:
    case GameId::GAMECUBE:
    case GameId::NINTENDO_64:
    case GameId::DREAMCAST:
    case GameId::XBOX_360:
    case GameId::PS_REMOTE_PLAY:
    case GameId::XBOX_REMOTE_PLAY:
    case GameId::IPHONE:
        return true;
    default:
        return false;
    }
}

bool is_other_games_choice(GameId id){
    return has_only_claude_plays(id) && game_profile(id).console == "switch";
}

std::vector<std::string> consoles_of_list(const std::string& list_name){
    for (GameId id : all_games()){
        const GameProfile& profile = game_profile(id);
        if (profile.console != "switch" && has_only_claude_plays(id) && profile.title == list_name){
            return {profile.console};
        }
    }
    return {};
}

const std::vector<GameId>& all_games(){
    static const std::vector<GameId> games{
        GameId::POKEMON_HOME,
        GameId::LETS_GO,
        GameId::SWORD_SHIELD,
        GameId::BRILLIANT_DIAMOND_SHINING_PEARL,
        GameId::LEGENDS_ARCEUS,
        GameId::SCARLET_VIOLET,
        GameId::LEGENDS_ZA,
        GameId::POKOPIA,
        GameId::RUBY_SAPPHIRE_EMERALD,
        GameId::ZELDA_TOTK,
        GameId::OCTOPATH_TRAVELER_0,
        GameId::MARIO_KART_8_DELUXE,
        GameId::SPLATOON_3,
        GameId::ANIMAL_CROSSING_NEW_HORIZONS,
        GameId::OTHER_GAMES,
        GameId::PLAYSTATION_3,
        GameId::ORIGINAL_XBOX,
        GameId::PLAYSTATION_1,
        GameId::PLAYSTATION_2,
        GameId::GAMECUBE,
        GameId::NINTENDO_64,
        GameId::DREAMCAST,
        GameId::XBOX_360,
        GameId::PS_REMOTE_PLAY,
        GameId::XBOX_REMOTE_PLAY,
        GameId::IPHONE,
    };
    return games;
}



}
}
}
