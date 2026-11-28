/*  ClaudeGG Console Guide
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  Every text here goes through tr_ui, one sentence or one item of a list at
 *  a time, without tags: the tags are put around it here. A text that is
 *  added must be added to the four languages (Resources/lang): the language
 *  test checks that each of them has every text of the guide.
 *
 */

#include <vector>
#include <QHBoxLayout>
#include <QIcon>
#include <QPainter>
#include <QPixmap>
#include <QListWidget>
#include <QPushButton>
#include <QTextBrowser>
#include <QVBoxLayout>
#include "Common/Cpp/Logging/AbstractLogger.h"
#include "Common/Cpp/ColoredText.h"
#include "CommonFramework/Logging/Logger.h"
#include "ClaudeGG_Language.h"
#include "ClaudeGG_Theme.h"
#include "ClaudeGG_ConsoleGuide.h"

namespace PokemonAutomation{
namespace ClaudeGG{


namespace{


enum class Status{
    SUPPORTED,      //  Pokemon Automation's own way, used by many
    EXPERIMENTAL,   //  written for it, not tried on the console yet
    COMING,         //  not in the setup yet
};

enum class Speed{
    FASTEST,
    FAST,
    SLOWER,
    SLOW,
    UNKNOWN,
};

//  A line of the picture of the connection: the parts, with what joins them
//  in between ("Computer", "USB", "ESP32-S3", "USB", "PlayStation 3").
using Chain = std::vector<const char*>;

struct Guide{
    const char* code;
    const char* name;
    Status status;
    Speed speed;
    //  For the page that compares them.
    const char* board;
    const char* video;
    //  One or two sentences: how it works.
    const char* summary;
    std::vector<const char*> need;
    std::vector<Chain> chains;
    std::vector<const char*> steps;
    const char* speed_note;
    std::vector<const char*> games;
    std::vector<const char*> limits;
    std::vector<const char*> trouble;
};


//  Texts that several consoles share.
const char* const NEED_CAPTURE = "A capture card with an HDMI input (for example an Elgato HD60 X or a cheap USB 3 one), and an HDMI cable.";
const char* const NEED_ESP32S3 = "An ESP32-S3 board with two USB ports (one labeled COM or UART, one labeled USB or OTG), and two USB cables that carry data.";
const char* const NEED_PICO_OGX = "A Raspberry Pi Pico with a USB port for a controller, and the OGX-Mini firmware (free, MIT license).";
const char* const NEED_COMPUTER = "A Windows computer with Claude GG.";

const char* const STEP_FLASH = "In the setup, pick the console and the board: the program flashes the firmware onto the board for you.";
const char* const STEP_PORTS = "In the program, pick Serial: PABotBase2 as the controller, the board as the serial port and the type the setup names.";
const char* const STEP_VIDEO = "Pick the capture card as the video and check the picture and the sound.";
const char* const STEP_TEST = "Click the video and press the arrow keys: the menu of the console should move.";
const char* const STEP_OGX = "Copy the Pi Pico file of OGX-Mini onto the Pico (hold Bootsel while plugging it in).";

const char* const TROUBLE_PORT = "The board is not listed as a port: try another USB cable (some only charge), another USB port, and install the CP210x or CH340 driver from the setup.";
const char* const TROUBLE_WRONG_PORT = "Nothing happens with the ESP32-S3: the two ports are not interchangeable. COM or UART goes to the computer, USB or OTG to the console or the Pico.";
const char* const TROUBLE_RESET = "The controller does not come up after flashing: press EN or RESET on the board, then Reset Ctrl in the program.";
const char* const TROUBLE_BLACK = "The video stays black: check the HDMI cable and the input of the capture card, and close other programs that use the capture card (OBS, Discord, the Camera app).";
const char* const TROUBLE_TYPE = "The console does not react: check the type. Consoles other than the Switch need NS1: Wired Controller, not NS1: Wired Pro Controller.";
const char* const TROUBLE_OGX_MODE = "The Pico is in the wrong mode: plug any USB controller into it and hold the button combination of the mode again for 3 seconds.";

const char* const LIMIT_UNTESTED = "Not tried on this console yet: please tell us how it goes, so the steps can be made right.";
const char* const LIMIT_POSITION = "The board sends the buttons of a Switch pad. The console reads them by position: B is the lowest face button (CROSS on a PlayStation, A on an Xbox), A the right one.";

const char* const GAMES_CLAUDE_PLAYS = "Claude Plays plays any game on the screen: it looks at the video and presses the buttons of this console.";
const char* const GAMES_MACRO = "Macro: record what you press on the keyboard or a controller, and play it back as often and as fast as you want.";


const std::vector<Guide>& guides(){
    static const std::vector<Guide> GUIDES{
        {
            "switch", "Nintendo Switch", Status::SUPPORTED, Speed::FASTEST,
            "Pico W, Pico 2 W, ESP32 or ESP32-S3", "Capture card (HDMI from the dock)",
            "The board plays a Pro Controller: wireless over Bluetooth (Pico W, Pico 2 W, ESP32), or wired in the dock (ESP32-S3). The picture comes from the dock through a capture card.",
            {
                NEED_COMPUTER,
                "A Switch with a dock. The Switch Lite has no picture for the TV, so it cannot be used.",
                "One board: a Raspberry Pi Pico W or Pico 2 W, an ESP32, or an ESP32-S3 (wired, the most reliable).",
                NEED_CAPTURE,
                "A USB cable that carries data for the board.",
            },
            {
                {"Computer", "USB", "Board", "Bluetooth or USB", "Switch"},
                {"Switch dock", "HDMI", "Capture card", "USB", "Computer"},
            },
            {
                STEP_FLASH,
                "Wireless boards: open Controllers, then Change Grip/Order on the Switch, and wait until the controller shows up.",
                "ESP32-S3: turn on Pro Controller Wired Communication in the settings of the Switch.",
                STEP_PORTS,
                STEP_VIDEO,
            },
            "Wired (ESP32-S3) is the quickest and steadiest: no radio in between. Bluetooth adds a few milliseconds and can drop out when other wireless devices are near.",
            {
                "The programs of Pokemon Automation for the Pokemon games (Sword and Shield, Scarlet and Violet, Legends, Let's Go, Home and more).",
                GAMES_CLAUDE_PLAYS,
                "Macro, in the list Other Games: record what you press and play it back.",
            },
            {
                "Keep a wireless board within 1 m (3 ft) of the Switch.",
                "Only one wireless controller can pair at a time through the Grip menu.",
            },
            {
                "The controller does not pair: the Switch must be on the Change Grip/Order screen while the board looks for it.",
                TROUBLE_PORT,
                TROUBLE_RESET,
                TROUBLE_BLACK,
            },
        },
        {
            "switch2", "Nintendo Switch 2", Status::SUPPORTED, Speed::FASTEST,
            "Pico W, Pico 2 W, ESP32 or ESP32-S3", "Capture card (HDMI from the dock)",
            "The same as the first Switch: the Switch 2 takes the Pro Controller of the Switch. The picture comes from its dock through a capture card.",
            {
                NEED_COMPUTER,
                "A Switch 2 with its dock.",
                "One board: a Raspberry Pi Pico W or Pico 2 W, an ESP32, or an ESP32-S3 (wired, the most reliable).",
                NEED_CAPTURE,
            },
            {
                {"Computer", "USB", "Board", "Bluetooth or USB", "Switch 2"},
                {"Switch 2 dock", "HDMI", "Capture card", "USB", "Computer"},
            },
            {
                STEP_FLASH,
                "Wireless boards: open the controller settings of the Switch 2 and pair a new controller.",
                "ESP32-S3: turn on Pro Controller Wired Communication in the settings of the Switch 2.",
                STEP_PORTS,
                "Set the TV output of the Switch 2 to 1080p, so a capture card that takes 1080p gets a picture.",
                STEP_VIDEO,
            },
            "Wired (ESP32-S3) is the quickest and steadiest: no radio in between. Bluetooth adds a few milliseconds and can drop out when other wireless devices are near.",
            {
                "The programs of Pokemon Automation, for the Switch games that run on the Switch 2 and for its own games where they say so.",
                GAMES_CLAUDE_PLAYS,
            },
            {
                "The types that start with NS2 play a Switch 2 controller, with the buttons GL, GR and C. A game that does not need those works with the NS1 types too.",
                "A capture card that only takes 1080p gets no picture from 4K: lower the TV output.",
            },
            {
                TROUBLE_PORT,
                TROUBLE_RESET,
                TROUBLE_BLACK,
            },
        },
        {
            "mobile", "Android phone", Status::EXPERIMENTAL, Speed::SLOWER,
            "Raspberry Pi (no board)", "The Raspberry Pi sends the screen",
            "The phone is plugged into a Raspberry Pi over USB. A small program on the Pi (the agent) sends the screen to Claude GG and taps the phone for it. There is no board and no capture card.",
            {
                NEED_COMPUTER,
                "A Raspberry Pi (3, 4 or 5) on the same network as the computer.",
                "An Android phone with USB debugging turned on, and its USB cable.",
                "For Pokemon GO: Tesseract on the computer (the installer of UB Mannheim).",
            },
            {
                {"Computer", "Network", "Raspberry Pi", "USB (ADB)", "Phone"},
            },
            {
                "On the phone, turn on the developer options and USB debugging, and allow the Raspberry Pi when the phone asks.",
                "On the Raspberry Pi, install the agent from the folder Mobile of Claude GG with install-agent.sh.",
                "In the setup, pick Android phone and type the address of the Raspberry Pi and its port (8765).",
                "Press Test: the screen of the phone should appear.",
            },
            "Slower than a board: the screen goes over the network and every tap goes through ADB. Fine for Pokemon GO, not for games where a fraction of a second counts. A wired network for the Pi helps.",
            {
                "Pokemon GO: Auto play (spinning, catching, gifts, Team GO Rocket and the GO Pass, each one to choose), the Daily run, the GO Battle League and more.",
            },
            {
                "Not tried with a real phone yet.",
                "An iPhone does not work this way; it has its own page.",
            },
            {
                "Test finds nothing: check the address of the Raspberry Pi, that the agent runs (systemctl status) and that a firewall does not block port 8765.",
                "The Pi sees no phone: unlock the phone and allow USB debugging for this computer; try another cable.",
            },
        },
        {
            "ps3", "PlayStation 3", Status::EXPERIMENTAL, Speed::FASTEST,
            "ESP32-S3", "Capture card (component, or HDMI without HDCP)",
            "The ESP32-S3 plays a plain USB gamepad (a HORIPAD), which the PlayStation 3 takes in any USB port.",
            {
                NEED_COMPUTER,
                NEED_ESP32S3,
                "A capture card. The PlayStation 3 always puts HDCP on its HDMI, so use component cables with a converter, or an HDMI splitter that removes HDCP.",
            },
            {
                {"Computer", "USB (COM)", "ESP32-S3", "USB (OTG)", "PlayStation 3"},
                {"PlayStation 3", "Component or HDMI", "Converter or splitter", "HDMI", "Capture card", "USB", "Computer"},
            },
            {
                "Plug the port COM or UART into the computer and the port USB or OTG into the PlayStation 3.",
                STEP_FLASH,
                STEP_PORTS,
                STEP_VIDEO,
                STEP_TEST,
            },
            "Direct USB to the console: as quick as a board gets.",
            {
                "The list PlayStation 3 of Claude Plays.",
                GAMES_CLAUDE_PLAYS,
                GAMES_MACRO,
            },
            {
                LIMIT_UNTESTED,
                LIMIT_POSITION,
                "A gamepad of this kind has no PS button: the PlayStation 3 has to be turned on by hand.",
            },
            {
                "The video is black over HDMI: that is the HDCP of the PlayStation 3. Use component cables or a splitter that removes it.",
                TROUBLE_WRONG_PORT,
                TROUBLE_TYPE,
                TROUBLE_PORT,
            },
        },
        {
            "xbox", "Original Xbox", Status::EXPERIMENTAL, Speed::FAST,
            "ESP32-S3 and a Pico with OGX-Mini", "Capture card (through an HDMI converter)",
            "The ESP32-S3 plays a Switch pad into a Raspberry Pi Pico with OGX-Mini, which plays an original Xbox controller to the console.",
            {
                NEED_COMPUTER,
                NEED_ESP32S3,
                NEED_PICO_OGX,
                "An Xbox-to-USB adapter cable for the controller port.",
                "A converter from composite or component to HDMI (the Xbox has no HDMI), and a capture card.",
            },
            {
                {"Computer", "USB (COM)", "ESP32-S3", "USB (OTG)", "Pico with OGX-Mini", "Adapter cable", "Xbox"},
                {"Xbox", "Composite or component", "HDMI converter", "HDMI", "Capture card", "USB", "Computer"},
            },
            {
                STEP_FLASH,
                STEP_OGX,
                "Plug the port USB or OTG of the ESP32-S3 into the Pico, and the Pico into the Xbox with the adapter cable.",
                STEP_PORTS,
                STEP_TEST,
            },
            "The Pico adds one short step in between; that is hardly noticeable.",
            {
                "The list Original Xbox of Claude Plays.",
                GAMES_CLAUDE_PLAYS,
                GAMES_MACRO,
            },
            {
                LIMIT_UNTESTED,
                LIMIT_POSITION,
            },
            {
                TROUBLE_WRONG_PORT,
                TROUBLE_TYPE,
                "The Xbox does not see the Pico: check the adapter cable and that the Pico has the OGX-Mini file for the Pi Pico.",
                TROUBLE_BLACK,
            },
        },
        {
            "retro", "Retro consoles", Status::EXPERIMENTAL, Speed::FAST,
            "Pico W, Pico 2 W or ESP32, and BlueRetro", "Capture card (through an upscaler)",
            "A wireless board plays a Pro Controller over Bluetooth to a BlueRetro adapter in the controller port. BlueRetro plays the pad of the console: PlayStation, PlayStation 2, GameCube, Nintendo 64 or Dreamcast.",
            {
                NEED_COMPUTER,
                "A wireless board: a Raspberry Pi Pico W or Pico 2 W, or an ESP32. The ESP32-S3 has no Bluetooth for a pad.",
                "A BlueRetro adapter for your console: ready-made, or a second ESP32 (not an S3) with the BlueRetro firmware.",
                "An upscaler or converter to HDMI (these consoles have analog video, the Dreamcast VGA), and a capture card.",
            },
            {
                {"Computer", "USB", "Pico W or ESP32", "Bluetooth", "BlueRetro", "Controller port", "Console"},
                {"Console", "Analog video", "Upscaler", "HDMI", "Capture card", "USB", "Computer"},
            },
            {
                "Flash BlueRetro with its web installer, the build for your console, and plug it into the first controller port.",
                STEP_FLASH,
                STEP_PORTS,
                "Turn on the console: BlueRetro looks for the pad by itself. Wait until its light stays on.",
                STEP_TEST,
            },
            "Bluetooth to the adapter, then wired to the console: quick, but a little slower than wired all the way. A cheap converter can add delay to the picture; a good upscaler adds almost none.",
            {
                "Five lists of Claude Plays: PlayStation, PlayStation 2, GameCube, Nintendo 64 and Dreamcast.",
                GAMES_CLAUDE_PLAYS,
                GAMES_MACRO,
            },
            {
                LIMIT_UNTESTED,
                "BlueRetro maps the buttons by position. On the GameCube, the digital click of L and R needs the web settings of BlueRetro.",
                "BlueRetro is no longer updated (archived in December 2025). Whether it pairs with this board is not known yet: try one console first.",
            },
            {
                "BlueRetro does not pair: start the board first, then turn on the console; keep them within 1 m (3 ft) of each other.",
                TROUBLE_PORT,
                TROUBLE_BLACK,
            },
        },
        {
            "xbox360", "Xbox 360", Status::EXPERIMENTAL, Speed::FAST,
            "ESP32-S3 and a Pico with OGX-Mini-2026", "Capture card (HDMI)",
            "As the original Xbox: the ESP32-S3 goes into a Pico with OGX-Mini-2026, here in its Xbox 360 mode. That version answers the check of the Xbox 360, so the console needs no modification.",
            {
                NEED_COMPUTER,
                NEED_ESP32S3,
                "A Raspberry Pi Pico with a USB port for a controller, and OGX-Mini-2026 (its Multi file, free).",
                "An Xbox 360.",
                NEED_CAPTURE,
            },
            {
                {"Computer", "USB (COM)", "ESP32-S3", "USB (OTG)", "Pico with OGX-Mini-2026", "USB", "Xbox 360"},
                {"Xbox 360", "HDMI", "Capture card", "USB", "Computer"},
            },
            {
                STEP_FLASH,
                "Copy the Multi file of OGX-Mini-2026 onto the Pico (hold Bootsel while plugging it in).",
                "Put the Pico in its Xbox 360 mode once: plug any USB controller into it and hold START and UP for 3 seconds.",
                "Plug the ESP32-S3 into the Pico and the Pico into the Xbox 360.",
                STEP_PORTS,
                STEP_TEST,
            },
            "The Pico adds one short step in between; that is hardly noticeable.",
            {
                "The list Xbox 360 of Claude Plays.",
                GAMES_CLAUDE_PLAYS,
                GAMES_MACRO,
            },
            {
                LIMIT_UNTESTED,
                "With the older OGX-Mini, only an Xbox 360 with UsbdSecPatch (a modified console) takes it. That OGX-Mini-2026 works on an unmodified one is what its makers say; it is not confirmed here.",
                LIMIT_POSITION,
            },
            {
                TROUBLE_OGX_MODE,
                TROUBLE_WRONG_PORT,
                TROUBLE_TYPE,
            },
        },
        {
            "psremote", "PS4 and PS5", Status::EXPERIMENTAL, Speed::SLOW,
            "ESP32-S3", "OBS Virtual Camera (the stream)",
            "The console streams to the computer with Remote Play (chiaki-ng). The ESP32-S3 is a USB gamepad of the computer, which chiaki-ng passes on. OBS turns the stream window into a camera for Claude GG.",
            {
                NEED_COMPUTER,
                NEED_ESP32S3,
                "chiaki-ng (free) on the computer, and a PlayStation account to register the console.",
                "OBS Studio (free), for its Virtual Camera.",
                "A good home network; a cable for the console and the computer is best.",
            },
            {
                {"Computer", "USB (COM)", "ESP32-S3", "USB (OTG)", "Same computer", "chiaki-ng", "PS4 or PS5"},
                {"PS4 or PS5", "Network", "chiaki-ng", "OBS Virtual Camera", "Claude GG"},
            },
            {
                "Plug both ports of the ESP32-S3 into the computer.",
                STEP_FLASH,
                "Turn on Remote Play on the console, register it in chiaki-ng and start the stream.",
                "In OBS, add a Window Capture of chiaki-ng and press Start Virtual Camera; pick OBS Virtual Camera as the video.",
                STEP_PORTS,
                STEP_TEST,
            },
            "The slowest way: the stream adds delay, often 50 to 100 ms or more, and it changes with the network. Use a cable, 720p and 60 frames per second in chiaki-ng for the least delay.",
            {
                "The list PS4 and PS5 Remote Play of Claude Plays.",
                GAMES_CLAUDE_PLAYS,
                GAMES_MACRO,
            },
            {
                LIMIT_UNTESTED,
                "Games that need quick reactions will feel the delay of the stream.",
                LIMIT_POSITION,
            },
            {
                "chiaki-ng does not see the pad: open its settings, look for the gamepad, and start the stream after the board is plugged in.",
                "The video is black: OBS must capture the window of chiaki-ng, and the Virtual Camera must be started.",
                TROUBLE_TYPE,
            },
        },
        {
            "xboxremote", "Xbox One and Series", Status::EXPERIMENTAL, Speed::SLOW,
            "ESP32-S3 and a Pico with OGX-Mini", "OBS Virtual Camera (the stream)",
            "The Xbox streams to a browser (xbox.com/remoteplay). It takes only controllers it knows, so the ESP32-S3 goes through a Pico with OGX-Mini, which Windows sees as an Xbox 360 controller.",
            {
                NEED_COMPUTER,
                NEED_ESP32S3,
                NEED_PICO_OGX,
                "Edge or Chrome, and the Microsoft account of the Xbox.",
                "OBS Studio (free), for its Virtual Camera.",
            },
            {
                {"Computer", "USB (COM)", "ESP32-S3", "USB (OTG)", "Pico with OGX-Mini", "USB", "Same computer"},
                {"Xbox", "Network", "Browser", "OBS Virtual Camera", "Claude GG"},
            },
            {
                STEP_FLASH,
                STEP_OGX,
                "Put the Pico in its Xbox 360 mode once: plug any USB controller into it and hold START and UP for 3 seconds.",
                "Turn on remote features on the Xbox, open xbox.com/remoteplay in Edge or Chrome and start Remote Play.",
                "In OBS, add a Window Capture of the browser and press Start Virtual Camera; pick OBS Virtual Camera as the video.",
                STEP_PORTS,
            },
            "The slowest way: the stream adds delay, often 50 to 100 ms or more, and it changes with the network. A cable for the Xbox and the computer helps most.",
            {
                "The list Xbox One and Series Remote Play of Claude Plays.",
                GAMES_CLAUDE_PLAYS,
                GAMES_MACRO,
            },
            {
                LIMIT_UNTESTED,
                "Keep the browser window in front while Claude plays: the browser may read the pad only then.",
            },
            {
                "The browser does not react: click once in the Remote Play window, and keep it in front.",
                TROUBLE_OGX_MODE,
                TROUBLE_TYPE,
            },
        },
        {
            "iphone", "iPhone", Status::EXPERIMENTAL, Speed::FAST,
            "ESP32-S3 (as a keyboard)", "Capture card (HDMI adapter)",
            "The ESP32-S3 is a USB keyboard for the iPhone. With Full Keyboard Access, the keys move a frame over the screen and Space taps what is in it.",
            {
                NEED_COMPUTER,
                NEED_ESP32S3,
                "An HDMI adapter for the iPhone (USB-C, or Lightning), or a USB-C hub with HDMI and a USB port for the board too.",
                NEED_CAPTURE,
            },
            {
                {"Computer", "USB (COM)", "ESP32-S3", "USB (OTG)", "iPhone"},
                {"iPhone", "HDMI adapter", "Capture card", "USB", "Computer"},
            },
            {
                STEP_FLASH,
                "On the iPhone: Settings, Accessibility, Keyboards, turn on Full Keyboard Access. Under Commands, set Home to Command-H.",
                "Pick HID: Keyboard as the type.",
                "Click the video and press Tab: a frame should move over the screen.",
            },
            "Each key is quick, but reaching a button can take many presses of Tab. Good for menus and slow games, not for action games.",
            {
                "The list iPhone of Claude Plays.",
            },
            {
                LIMIT_UNTESTED,
                "Some apps and games draw their own buttons, which Full Keyboard Access cannot reach.",
                "Leave AssistiveTouch off and plug in no mouse: with a mouse as well, some keys go to the home screen.",
            },
            {
                "Home does nothing: set Home to Command-H under Commands of Full Keyboard Access.",
                "No frame on the screen: turn Full Keyboard Access off and on again, and check that the type is HID: Keyboard.",
                TROUBLE_WRONG_PORT,
            },
        },
        {
            "psclassic", "PlayStation Classic", Status::EXPERIMENTAL, Speed::FAST,
            "ESP32-S3 and a Pico with OGX-Mini", "Capture card (HDMI)",
            "As the original Xbox: the ESP32-S3 goes into a Pico with OGX-Mini, here in its PlayStation Classic mode. The console takes it as its own pad.",
            {
                NEED_COMPUTER,
                NEED_ESP32S3,
                NEED_PICO_OGX,
                NEED_CAPTURE,
            },
            {
                {"Computer", "USB (COM)", "ESP32-S3", "USB (OTG)", "Pico with OGX-Mini", "USB", "PlayStation Classic"},
                {"PlayStation Classic", "HDMI", "Capture card", "USB", "Computer"},
            },
            {
                STEP_FLASH,
                STEP_OGX,
                "Put the Pico in its PlayStation Classic mode once: plug any USB controller into it and hold START and the lowest face button for 3 seconds.",
                "Plug the ESP32-S3 into the Pico and the Pico into the first controller port.",
                STEP_PORTS,
                STEP_TEST,
            },
            "The Pico adds one short step in between; that is hardly noticeable.",
            {
                "The list PlayStation Classic of Claude Plays (its twenty games).",
                GAMES_MACRO,
            },
            {
                LIMIT_UNTESTED,
                "The pad of the PlayStation Classic has no sticks: games that need them do not run on it anyway.",
            },
            {
                TROUBLE_OGX_MODE,
                TROUBLE_WRONG_PORT,
                TROUBLE_TYPE,
            },
        },
        {
            "wiiu", "Nintendo Wii U", Status::EXPERIMENTAL, Speed::SLOWER,
            "Raspberry Pi as the GamePad (no board)", "The picture of the GamePad, from the Pi",
            "A Raspberry Pi with a 5 GHz Wi-Fi adapter is the Wii U GamePad (with Vanilla). It sends the screen of the GamePad to Claude GG and presses its buttons, sticks and touch screen. There is no board, and the console needs no modification.",
            {
                NEED_COMPUTER,
                "A Raspberry Pi 4 or 5 with Raspberry Pi OS (64-bit), or another Linux computer.",
                "A 5 GHz USB Wi-Fi adapter that is on the list of Vanilla. The Wi-Fi built into the Pi does not work.",
                "Optional: a capture card for the TV picture, over HDMI.",
            },
            {
                {"Computer", "Network", "Raspberry Pi with Vanilla", "5 GHz Wi-Fi", "Wii U"},
                {"Wii U", "HDMI", "Capture card", "USB", "Computer"},
            },
            {
                "On the Pi, install vanilla-pipe and the bridge from the folder WiiU of Claude GG, and start both.",
                "In the setup, pick Nintendo Wii U and type the address of the Raspberry Pi.",
                "Press SYNC on the Wii U and give the program Connect the GamePad the four symbols on the TV. This is needed once.",
                "Run Connect the GamePad: the screen of the GamePad should appear.",
            },
            "Every press goes over the network to the Pi and then over Wi-Fi to the Wii U, and the picture of the GamePad comes back as a stream of pictures, not through a capture card. Fine for menus and turn-based games; how quick it is in action games is not known yet.",
            {
                "The list Nintendo Wii U: Connect the GamePad, and Claude Plays with the touch screen.",
            },
            {
                LIMIT_UNTESTED,
                "The Wii U pairs one GamePad at a time: after the Pi, the real GamePad needs to be synced again.",
                "Vanilla is still alpha, so a Wii U update or another adapter can break it.",
            },
            {
                "The Pi does not connect: check that the adapter is on the list of Vanilla, that vanilla-pipe runs on that adapter (often wlan1), and keep the Pi close to the Wii U.",
                "The Wii U refuses the GamePad: start the bridge with the region of the console (EUR, USA or JPN).",
                "No picture: check the address of the Pi and that a firewall does not block ports 51200 to 51202.",
            },
        },
        {
            "psdirect", "PS4 and PS5, direct", Status::EXPERIMENTAL, Speed::FAST,
            "ESP32-S3 and a Brook Wingman XE", "Capture card (HDMI)",
            "The ESP32-S3 plays a Switch pad into a bought Brook Wingman XE, which plays a PlayStation 4 controller and answers the console's check of a pad. No network and no stream: quicker than Remote Play.",
            {
                NEED_COMPUTER,
                NEED_ESP32S3,
                "A Brook Wingman XE (bought, about 40 dollars or euros): it answers the console's check",
                "A PlayStation 4 or 5 (a PlayStation 5 takes it in PS4 games only)",
                NEED_CAPTURE,
            },
            {
                {"Computer", "USB (COM)", "ESP32-S3", "USB (OTG)", "Brook Wingman XE", "USB", "PS4 or PS5"},
                {"PS4 or PS5", "HDMI", "Capture card", "USB", "Computer"},
            },
            {
                STEP_FLASH,
                "Update the Brook Wingman XE to its latest firmware with Brook's updater. It plays a PlayStation 4 controller: a PlayStation 5 takes it in PS4 games only.",
                "Plug the adapter into a USB port of the console, and the USB or OTG port of the ESP32-S3 into the adapter. The console's picture goes into the capture card over HDMI.",
                STEP_PORTS,
                STEP_VIDEO,
                STEP_TEST,
            },
            "Wired all the way: the adapter adds a few milliseconds, far less than the stream of Remote Play.",
            {
                "The list PS4 and PS5 games, direct of Claude Plays.",
                GAMES_CLAUDE_PLAYS,
                GAMES_MACRO,
            },
            {
                LIMIT_UNTESTED,
                "The adapter has to be bought: no open adapter answers the check of these consoles.",
                LIMIT_POSITION,
            },
            {
                "The console does not take the adapter: update it with Brook's updater and plug it straight into the console, without a hub.",
                TROUBLE_WRONG_PORT,
                TROUBLE_TYPE,
            },
        },
        {
            "xboxdirect", "Xbox One and Series, direct", Status::EXPERIMENTAL, Speed::FAST,
            "ESP32-S3 and a Brook Wingman XB 3", "Capture card (HDMI)",
            "The ESP32-S3 plays a Switch pad into a bought Brook Wingman XB 3, which plays an Xbox controller and answers the console's check of a pad. No network and no stream: quicker than Remote Play.",
            {
                NEED_COMPUTER,
                NEED_ESP32S3,
                "A Brook Wingman XB 3 (bought): it answers the console's check",
                "An Xbox One or Series",
                NEED_CAPTURE,
            },
            {
                {"Computer", "USB (COM)", "ESP32-S3", "USB (OTG)", "Brook Wingman XB 3", "USB", "Xbox"},
                {"Xbox", "HDMI", "Capture card", "USB", "Computer"},
            },
            {
                STEP_FLASH,
                "Update the Brook Wingman XB 3 to its latest firmware with Brook's updater. It plays an Xbox controller to an Xbox One or Series.",
                "Plug the adapter into a USB port of the console, and the USB or OTG port of the ESP32-S3 into the adapter. The console's picture goes into the capture card over HDMI.",
                STEP_PORTS,
                STEP_VIDEO,
                STEP_TEST,
            },
            "Wired all the way: the adapter adds a few milliseconds, far less than the stream of Remote Play.",
            {
                "The list Xbox One and Series games, direct of Claude Plays.",
                GAMES_CLAUDE_PLAYS,
                GAMES_MACRO,
            },
            {
                LIMIT_UNTESTED,
                "The adapter has to be bought: no open adapter answers the check of these consoles.",
                LIMIT_POSITION,
            },
            {
                "The console does not take the adapter: update it with Brook's updater and plug it straight into the console, without a hub.",
                TROUBLE_WRONG_PORT,
                TROUBLE_TYPE,
            },
        },
        {
            "steam", "Steam Deck and PC", Status::EXPERIMENTAL, Speed::FAST,
            "ESP32-S3", "Capture card (HDMI from the dock), or OBS Virtual Camera",
            "The ESP32-S3 is a plain USB gamepad of the Steam Deck or the PC, and Steam takes it like any other pad. The picture of a Steam Deck comes from its dock through a capture card; a game on this same computer comes in through OBS.",
            {
                NEED_COMPUTER,
                NEED_ESP32S3,
                "A Steam Deck with a USB-C dock that has HDMI, or a PC with Steam",
                "A capture card for the Steam Deck; for a game on this same PC, OBS Studio (free) instead",
            },
            {
                {"Computer", "USB (COM)", "ESP32-S3", "USB (OTG)", "Steam Deck dock or PC"},
                {"Steam Deck dock", "HDMI", "Capture card", "USB", "Computer"},
            },
            {
                STEP_FLASH,
                "Plug the USB or OTG port of the ESP32-S3 into a USB port of the Steam Deck's dock, or of the PC that runs the game (this same computer is fine). In Steam, under Settings and Controller, it shows up as a gamepad.",
                "Steam Deck: from the HDMI of its dock into the capture card. A game on this same computer: in OBS Studio, add a Window Capture of the game, press Start Virtual Camera and pick OBS Virtual Camera as the video.",
                STEP_PORTS,
                STEP_TEST,
            },
            "Wired all the way, and Steam reads the pad at once. A game on this same computer comes in through OBS, a frame or two late.",
            {
                "The list Steam Deck and PC games of Claude Plays.",
                GAMES_CLAUDE_PLAYS,
            },
            {
                LIMIT_UNTESTED,
                "Steam passes the buttons on by their places, as an Xbox pad's. If A and B are swapped, turn off the Nintendo button layout in Steam's controller settings.",
                "A game outside Steam may not see the pad: add it to Steam as a game that is not from Steam, so that Steam Input passes the pad on.",
            },
            {
                "Steam does not show the pad: try another USB port of the dock, and check that the USB or OTG port of the ESP32-S3 is the one plugged in.",
                TROUBLE_WRONG_PORT,
                TROUBLE_TYPE,
            },
        },
    };
    return GUIDES;
}

const Guide* find_guide(const QString& code){
    for (const Guide& guide : guides()){
        if (code == guide.code){
            return &guide;
        }
    }
    return nullptr;
}


//  The texts of the headings and the table.
const char* const HEADINGS[] = {
    "Consoles",
    "All consoles",
    "Overview",
    "What you need",
    "How it connects",
    "Steps in short",
    "Reaction time",
    "Games",
    "Good to know",
    "If it does not work",
    "Console",
    "Board",
    "Video",
    "Status",
    "Supported",
    "Experimental",
    "Coming soon",
    "Fastest",
    "Fast",
    "Slower",
    "Slow",
    "Not known yet",
    "Open the setup",
    "Show the tour",
    "Pick a console on the left. Each page says what you need, how it is connected, how quick it is and what to do when it does not work.",
    "Written for this console, not tried on one yet.",
    "The way of Pokemon Automation, used by many people.",
    "Not in the setup yet.",
    "The setup shows every step with pictures and flashes the board for you.",
    "For the quickest reactions",
    "A wired board (the ESP32-S3) where the console takes one: no Bluetooth in between.",
    "The capture card in a USB 3 port of the computer itself, not in a hub, at 1080p and 60 frames per second.",
    "Close other programs that show the capture card: each one adds work.",
    "For Remote Play and the phone: a network cable instead of Wi-Fi.",
    "In Claude Plays, turn on Measure the timing first once, with a menu on the screen, and keep the numbers the log gives.",
    "On every console",
    "Claude Plays: Claude plays any game; it looks at the video and presses the buttons.",
    "Macro: record what you press on the keyboard or a controller and play it back, as often and as fast as you want. In every list without programs of its own (not on the iPhone and the Wii U).",
    "Measure the timing first, an option of Claude Plays: with a menu on the screen, the program measures how late the picture is and how short a press can be, and plays with that.",
    "Reaction time in the log: every action of Claude Plays says how long Claude took and how long the console took, so you see where the time goes.",
};

QString t(const char* english){
    return tr_ui(english).toHtmlEscaped();
}

QString status_text(Status status){
    switch (status){
    case Status::SUPPORTED:     return t("Supported");
    case Status::EXPERIMENTAL:  return t("Experimental");
    case Status::COMING:        return t("Coming soon");
    }
    return QString();
}
QString status_note(Status status){
    switch (status){
    case Status::SUPPORTED:     return t("The way of Pokemon Automation, used by many people.");
    case Status::EXPERIMENTAL:  return t("Written for this console, not tried on one yet.");
    case Status::COMING:        return t("Not in the setup yet.");
    }
    return QString();
}
QColor status_color(Status status){
    const ThemeColors& theme = theme_colors();
    switch (status){
    case Status::SUPPORTED:     return theme.ok;
    case Status::EXPERIMENTAL:  return theme.warning;
    case Status::COMING:        return theme.muted;
    }
    return theme.muted;
}
QString speed_text(Speed speed){
    switch (speed){
    case Speed::FASTEST:    return t("Fastest");
    case Speed::FAST:       return t("Fast");
    case Speed::SLOWER:     return t("Slower");
    case Speed::SLOW:       return t("Slow");
    case Speed::UNKNOWN:    return t("Not known yet");
    }
    return QString();
}
//  Five bars, as on a phone: how quick.
QString speed_bars(Speed speed, const ThemeColors& theme){
    int filled = 0;
    switch (speed){
    case Speed::FASTEST:    filled = 5; break;
    case Speed::FAST:       filled = 4; break;
    case Speed::SLOWER:     filled = 2; break;
    case Speed::SLOW:       filled = 1; break;
    case Speed::UNKNOWN:    filled = 0; break;
    }
    QString html = "<span style=\"font-family: monospace;\">";
    for (int c = 0; c < 5; c++){
        html += "<span style=\"color: " + (c < filled ? theme.accent : theme.line).name() + ";\">&#9646;</span>";
    }
    return html + "</span>";
}

QString badge(Status status){
    const QColor color = status_color(status);
    return "<span style=\"color: " + color.name() + "; font-weight: 600;\">&#9679; " + status_text(status) + "</span>";
}

QString list(const std::vector<const char*>& items, bool numbered){
    if (items.empty()){
        return QString();
    }
    QString html = numbered ? "<ol style=\"margin-top: 2px;\">" : "<ul style=\"margin-top: 2px;\">";
    for (const char* item : items){
        html += "<li style=\"margin-bottom: 3px;\">" + t(item) + "</li>";
    }
    return html + (numbered ? "</ol>" : "</ul>");
}

QString heading(const char* text, const ThemeColors& theme){
    return "<h3 style=\"color: " + theme.accent.name() + "; margin-top: 16px; margin-bottom: 4px;\">" + t(text) + "</h3>";
}

//  A line of boxes with arrows: the parts, with what joins them under each
//  arrow.
QString chain_html(const Chain& chain, const ThemeColors& theme){
    QString html = "<table cellspacing=\"0\" cellpadding=\"6\" style=\"margin-top: 4px; margin-bottom: 4px;\"><tr>";
    for (size_t c = 0; c < chain.size(); c++){
        if (c % 2 == 0){
            html += "<td align=\"center\" valign=\"middle\" style=\"background-color: " + theme.surface_alt.name()
                + "; border: 1px solid " + theme.line.name() + "; color: " + theme.text.name() + ";\"><b>"
                + t(chain[c]) + "</b></td>";
        }else{
            html += "<td align=\"center\" valign=\"middle\" style=\"color: " + theme.muted.name() + ";\">"
                "<span style=\"font-size: small;\">" + t(chain[c]) + "</span><br>"
                "<span style=\"color: " + theme.accent.name() + ";\">&#10230;</span></td>";
        }
    }
    return html + "</tr></table>";
}

QString page_style(const ThemeColors& theme){
    return "<body style=\"color: " + theme.text.name() + ";\">";
}

QString overview_html(){
    const ThemeColors& theme = theme_colors();
    QString html = page_style(theme);
    html += "<h2 style=\"margin-bottom: 2px;\">" + t("All consoles") + "</h2>";
    html += "<p style=\"color: " + theme.muted.name() + ";\">" + t("Pick a console on the left. Each page says what you need, how it is connected, how quick it is and what to do when it does not work.") + "</p>";
    html += "<table cellspacing=\"0\" cellpadding=\"6\" width=\"100%\" style=\"border: 1px solid " + theme.line.name() + ";\">";
    html += "<tr style=\"background-color: " + theme.surface_alt.name() + ";\">";
    for (const char* column : {"Console", "Board", "Video", "Reaction time", "Status"}){
        html += "<th align=\"left\">" + t(column) + "</th>";
    }
    html += "</tr>";
    for (const Guide& guide : guides()){
        html += "<tr>";
        html += "<td><a href=\"console:" + QString::fromLatin1(guide.code) + "\" style=\"color: " + theme.accent.name()
            + "; text-decoration: none;\"><b>" + t(guide.name) + "</b></a></td>";
        html += "<td>" + t(guide.board) + "</td>";
        html += "<td>" + t(guide.video) + "</td>";
        html += "<td>" + speed_bars(guide.speed, theme) + "&nbsp; " + speed_text(guide.speed) + "</td>";
        html += "<td>" + badge(guide.status) + "</td>";
        html += "</tr>";
    }
    html += "</table>";
    html += heading("For the quickest reactions", theme);
    html += list({
        "A wired board (the ESP32-S3) where the console takes one: no Bluetooth in between.",
        "The capture card in a USB 3 port of the computer itself, not in a hub, at 1080p and 60 frames per second.",
        "Close other programs that show the capture card: each one adds work.",
        "For Remote Play and the phone: a network cable instead of Wi-Fi.",
        "In Claude Plays, turn on Measure the timing first once, with a menu on the screen, and keep the numbers the log gives.",
    }, false);
    html += heading("On every console", theme);
    html += list({
        "Claude Plays: Claude plays any game; it looks at the video and presses the buttons.",
        "Macro: record what you press on the keyboard or a controller and play it back, as often and as fast as you want. In every list without programs of its own (not on the iPhone and the Wii U).",
        "Measure the timing first, an option of Claude Plays: with a menu on the screen, the program measures how late the picture is and how short a press can be, and plays with that.",
        "Reaction time in the log: every action of Claude Plays says how long Claude took and how long the console took, so you see where the time goes.",
    }, false);
    html += "<p>";
    for (Status status : {Status::SUPPORTED, Status::EXPERIMENTAL, Status::COMING}){
        html += badge(status) + " &nbsp; <span style=\"color: " + theme.muted.name() + ";\">" + status_note(status) + "</span><br>";
    }
    html += "</p>";
    return html + "</body>";
}

QString guide_html(const Guide& guide){
    const ThemeColors& theme = theme_colors();
    QString html = page_style(theme);
    html += "<h2 style=\"margin-bottom: 2px;\">" + t(guide.name) + "</h2>";
    html += "<p>" + badge(guide.status) + " &nbsp; <span style=\"color: " + theme.muted.name() + ";\">"
        + status_note(guide.status) + "</span></p>";
    html += "<p>" + t(guide.summary) + "</p>";

    html += heading("What you need", theme);
    html += list(guide.need, false);

    html += heading("How it connects", theme);
    for (const Chain& chain : guide.chains){
        html += chain_html(chain, theme);
    }

    if (!guide.steps.empty()){
        html += heading("Steps in short", theme);
        html += list(guide.steps, true);
        //  (Not for the two with a Raspberry Pi in place of a board.)
        if (QString(guide.code) != "mobile" && QString(guide.code) != "wiiu"){
            html += "<p style=\"color: " + theme.muted.name() + ";\">" + t("The setup shows every step with pictures and flashes the board for you.") + "</p>";
        }
    }

    html += heading("Reaction time", theme);
    html += "<p>" + speed_bars(guide.speed, theme) + "&nbsp; <b>" + speed_text(guide.speed) + "</b><br>" + t(guide.speed_note) + "</p>";

    if (!guide.games.empty()){
        html += heading("Games", theme);
        html += list(guide.games, false);
    }

    html += heading("Good to know", theme);
    html += list(guide.limits, false);

    if (!guide.trouble.empty()){
        html += heading("If it does not work", theme);
        html += list(guide.trouble, false);
    }
    return html + "</body>";
}


class ConsoleGuide : public QWidget{
public:
    ConsoleGuide(QWidget* parent, const QString& console_code, std::function<void()> open_setup, std::function<void()> show_tour)
        : QWidget(parent)
        , m_open_setup(std::move(open_setup))
        , m_show_tour(std::move(show_tour))
    {
        setObjectName("ppConsoleGuide");
        QHBoxLayout* layout = new QHBoxLayout(this);
        layout->setContentsMargins(0, 0, 0, 0);
        layout->setSpacing(14);

        QVBoxLayout* left = new QVBoxLayout();
        left->setSpacing(10);
        layout->addLayout(left);
        m_list = new QListWidget(this);
        m_list->setObjectName("ppConsoleGuideList");
        m_list->setMinimumWidth(220);
        m_list->setMaximumWidth(280);
        left->addWidget(m_list, 1);
        if (m_show_tour){
            m_tour = new QPushButton(this);
            m_tour->setObjectName("ppConsoleGuideTour");
            left->addWidget(m_tour);
            connect(m_tour, &QPushButton::clicked, this, [this]{
                m_show_tour();
            });
        }
        if (m_open_setup){
            m_setup = new QPushButton(this);
            m_setup->setObjectName("ppConsoleGuideSetup");
            left->addWidget(m_setup);
            connect(m_setup, &QPushButton::clicked, this, [this]{
                m_open_setup();
            });
        }

        m_page = new QTextBrowser(this);
        m_page->setObjectName("ppConsoleGuidePage");
        m_page->setOpenExternalLinks(false);
        m_page->setOpenLinks(false);
        m_page->setMinimumWidth(560);
        layout->addWidget(m_page, 1);
        connect(m_page, &QTextBrowser::anchorClicked, this, [this](const QUrl& url){
            if (url.scheme() == "console"){
                select(url.path());
            }
        });
        connect(m_list, &QListWidget::currentRowChanged, this, [this](int){
            show_current();
        });

        fill();
        select(console_code);
        on_language_changed(this, [this]{
            const QString code = current_code();
            fill();
            select(code);
        });
    }

private:
    QString current_code() const{
        QListWidgetItem* item = m_list->currentItem();
        return item == nullptr ? QString() : item->data(Qt::UserRole).toString();
    }
    void fill(){
        //  The texts are set here, already translated: the filter of the
        //  language leaves them as they are.
        QSignalBlocker block(m_list);
        m_list->clear();
        QListWidgetItem* all = new QListWidgetItem(dot(Qt::transparent), tr_ui("All consoles"), m_list);
        all->setData(Qt::UserRole, QString());
        for (const Guide& guide : guides()){
            QListWidgetItem* item = new QListWidgetItem(dot(status_color(guide.status)), tr_ui(guide.name), m_list);
            item->setData(Qt::UserRole, QString::fromLatin1(guide.code));
            item->setForeground(guide.status == Status::COMING ? theme_colors().muted : theme_colors().text);
            item->setToolTip(tr_ui(guide.board));
        }
        if (m_setup != nullptr){
            m_setup->setText(tr_ui("Open the setup"));
        }
        if (m_tour != nullptr){
            m_tour->setText(tr_ui("Show the tour"));
        }
    }
    //  A dot in the color of the status, before the name.
    static QIcon dot(const QColor& color){
        QPixmap pixmap(24, 24);
        pixmap.fill(Qt::transparent);
        QPainter painter(&pixmap);
        painter.setRenderHint(QPainter::Antialiasing);
        painter.setPen(Qt::NoPen);
        painter.setBrush(color);
        painter.drawEllipse(QRectF(6, 6, 12, 12));
        return QIcon(pixmap);
    }
    void select(const QString& code){
        int row = 0;
        for (int c = 0; c < m_list->count(); c++){
            if (m_list->item(c)->data(Qt::UserRole).toString() == code){
                row = c;
                break;
            }
        }
        if (m_list->currentRow() == row){
            show_current();
        }else{
            m_list->setCurrentRow(row);
        }
    }
    void show_current(){
        m_page->setHtml(console_guide_html(current_code()));
    }

private:
    std::function<void()> m_open_setup;
    std::function<void()> m_show_tour;
    QListWidget* m_list = nullptr;
    QPushButton* m_setup = nullptr;
    QPushButton* m_tour = nullptr;
    QTextBrowser* m_page = nullptr;
};


//  Every English text of the guide, once.
QStringList all_texts(){
    QStringList texts;
    auto add = [&](const char* text){
        if (text != nullptr && !texts.contains(QString::fromUtf8(text))){
            texts.append(QString::fromUtf8(text));
        }
    };
    for (const char* text : HEADINGS){
        add(text);
    }
    for (const Guide& guide : guides()){
        add(guide.name);
        add(guide.board);
        add(guide.video);
        add(guide.summary);
        add(guide.speed_note);
        for (const auto* items : {&guide.need, &guide.steps, &guide.games, &guide.limits, &guide.trouble}){
            for (const char* item : *items){
                add(item);
            }
        }
        for (const Chain& chain : guide.chains){
            for (const char* part : chain){
                add(part);
            }
        }
    }
    return texts;
}


}   //  namespace



QWidget* make_console_guide(
    QWidget* parent, const QString& console_code,
    std::function<void()> open_setup,
    std::function<void()> show_tour
){
    return new ConsoleGuide(parent, console_code, std::move(open_setup), std::move(show_tour));
}

QStringList console_guide_codes(){
    QStringList codes;
    for (const Guide& guide : guides()){
        codes.append(QString::fromLatin1(guide.code));
    }
    return codes;
}

QString console_guide_html(const QString& console_code){
    const Guide* guide = find_guide(console_code);
    return guide == nullptr ? overview_html() : guide_html(*guide);
}

QStringList console_guide_texts(){
    return all_texts();
}

int console_guide_self_test(){
    Logger& logger = global_logger_command_line();
    int failures = 0;
    auto check = [&](bool ok, const QString& what){
        if (!ok){
            failures++;
            logger.log("Console guide test: FAILED: " + what.toStdString(), COLOR_RED);
        }
    };
    //  Every console of the setup has a page.
    for (const char* code : {"switch", "switch2", "mobile", "ps3", "xbox", "retro", "xbox360", "psremote", "xboxremote", "iphone", "psclassic", "wiiu", "psdirect", "xboxdirect", "steam"}){
        const Guide* guide = find_guide(code);
        check(guide != nullptr, QString("no page for ") + code);
        if (guide == nullptr){
            continue;
        }
        check(!guide->need.empty(), QString(code) + ": what you need");
        check(!guide->chains.empty(), QString(code) + ": how it connects");
        check(!guide->limits.empty(), QString(code) + ": good to know");
        for (const Chain& chain : guide->chains){
            check(chain.size() >= 3 && chain.size() % 2 == 1, QString(code) + ": a line of the connection is part, link, part");
        }
        if (guide->status != Status::COMING){
            check(!guide->steps.empty(), QString(code) + ": the steps");
            check(!guide->trouble.empty(), QString(code) + ": if it does not work");
        }
        const QString html = console_guide_html(code);
        check(html.contains(t(guide->name)) && html.contains(t("What you need")), QString(code) + ": the page has its heading and parts");
    }
    check(console_guide_html(QString()).contains("console:psremote"), "the overview links to the pages");
    check(all_texts().size() > 100, "the texts of the guide");
    logger.log(
        failures == 0 ? "Console guide test: passed." : "Console guide test: FAILED.",
        failures == 0 ? COLOR_BLUE : COLOR_RED
    );
    return failures;
}



}
}
