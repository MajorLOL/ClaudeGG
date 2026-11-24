"""The test chapters: parts of the bot that can be run on their own, from the web interface (Test) or with
'python3 gamebot.py chapter <key>'.  Each one starts on a known screen, does one thing and stops, so a fix can be
tried in a minute instead of waiting for the moment in a whole run.

This file only describes them (the web interface reads it without loading the bot); gamebot.run_chapter() runs
them.  Fields: key, group, title, the screen the game has to be on at the start, what it does."""

CHAPTERS = [
    # key             group                  title                                start screen                       what it does
    ("screen",        "Checks",              "What the bot sees",                 "Any screen",
     "Takes one screenshot, says which screen it is and marks what it finds (debug/g_test.png). No taps."),
    ("video",         "Checks",              "Live video",                        "Any screen",
     "Runs the live video of the phone for 8 seconds, as in a battle, and says how many pictures came. No taps."),
    ("look",          "Checks",              "Looking: video against screenshots", "The map",
     "Takes ten pictures from the live video and three screenshots, and says how long each took and what the bot finds on the map in both. No taps."),
    ("play",          "Checks",              "Normal play for 3 minutes",         "The map",
     "The normal bot (spin, catch, everything that is switched on) for 3 minutes, then it stops."),

    ("battle_menu",   "GO Battle League",    "To the party screen",               "The map",
     "Walks from the map to the party screen of the chosen league (rewards, rank, a new set on the way) and stops there."),
    ("battle_one",    "GO Battle League",    "One battle",                        "The map",
     "One whole battle of the chosen league: the way to it, the fight and the result screen."),
    ("battle_fight",  "GO Battle League",    "The fight on the screen",           "A battle that is going on",
     "Fights the battle that is on the screen now, to its result. Start it during the countdown or in the fight."),
    ("battle_set",    "GO Battle League",    "All battles of the setting",        "The map",
     "As many battles as set under Battles, as in the daily run."),

    ("rocket",        "Team GO Rocket",      "Rocket battle",                     "A grunt or leader talking, at the stop",
     "The whole Team GO Rocket battle: the party, the fight, the rewards and catching the Shadow Pokémon."),
    ("rocket_fight",  "Team GO Rocket",      "The Rocket fight on the screen",    "A Rocket fight that is going on",
     "Fights the Team GO Rocket fight that is on the screen now, until it is over."),

    ("catch",         "Catching",            "Catch this Pokémon",                "An encounter",
     "Catches the Pokémon on the screen (or runs, as the settings say), until the game is out of the encounter."),
    ("throw",         "Catching",            "One throw",                         "An encounter",
     "Throws one ball at the Pokémon on the screen, with the ring timing, and says how it went (ring size at the release, where the ball came down). Nothing else."),
    ("bag",           "Items and rewards",   "Clean up the bag",                  "The map",
     "Opens the bag and discards what the bag rules say, then back to the map."),
    ("quests",        "Items and rewards",   "Claim GO Pass rewards",             "The map",
     "Opens the quests, GO Pass, View rewards, Claim all, and closes them again (also when the button is not gold)."),
    ("gifts",         "Items and rewards",   "Gifts",                             "The map",
     "One round of opening and sending gifts, as the gift settings say."),
]

KEYS = [c[0] for c in CHAPTERS]


def chapter(key):
    """The chapter as a dict, or None."""
    for k, group, title, start, what in CHAPTERS:
        if k == key:
            return {"key": k, "group": group, "title": title, "start": start, "what": what}
    return None


def as_list():
    """For the web interface: [{key, group, title, start, what}]."""
    return [chapter(k) for k in KEYS]
