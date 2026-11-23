"""What the bag clean-up keeps (option 'Clean up a full bag'): per item how many stay in the bag.

A number: the bag keeps that many and discards the rest (0: all of it goes). None: the item is not touched.
Items that are not on the list are never touched. The user sets the numbers in the web interface
(PokéStops and storage, 'What the bag keeps'); they are stored in ~/gamebot_control.json under 'bag_keep'."""

# (name as the game shows it, how many are kept by default)
ITEMS = [
    ("Potion", 0), ("Super Potion", 0), ("Hyper Potion", 0), ("Max Potion", 30),
    ("Revive", None), ("Max Revive", 30),
    ("Poké Ball", 400), ("Great Ball", 100), ("Ultra Ball", None),
    ("Razz Berry", 30), ("Nanab Berry", 30), ("Pinap Berry", 30), ("Golden Razz Berry", 30), ("Silver Pinap Berry", 30),
]
NAMES = [n for n, _ in ITEMS]
MAX_KEEP = 9999


def defaults():
    return {n: k for n, k in ITEMS}


def clean(d):
    """The user's choice from the page, checked: {name: number or None} for the known items only."""
    out = defaults()
    if not isinstance(d, dict):
        return out
    for n in NAMES:
        if n not in d:
            continue
        v = d[n]
        if v is None or (isinstance(v, str) and not v.strip()):
            out[n] = None
            continue
        try:
            out[n] = max(0, min(MAX_KEEP, int(float(v))))
        except (TypeError, ValueError):
            pass
    return out


def rules(saved=None):
    """[(name, keep)] of the items that are cleaned up, in the order of the list."""
    keep = clean(saved) if saved is not None else defaults()
    return [(n, keep[n]) for n in NAMES if keep[n] is not None]


def summary(saved=None):
    """'Discards Potion and Super Potion; keeps 30 Max Potion and 400 Poké Ball.' for the page."""
    r = rules(saved)
    gone = [n for n, k in r if k == 0]
    kept = [f"{k} {n}" for n, k in r if k > 0]

    def join(xs):
        return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]
    parts = ([f"discards {join(gone)}"] if gone else []) + ([f"keeps {join(kept)}"] if kept else [])
    if not parts:
        return "Nothing is set to be cleaned up."
    text = "; ".join(parts)
    return text[0].upper() + text[1:] + ". Nothing else is touched."
