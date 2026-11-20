#!/usr/bin/env python3
"""
Collects what is needed to make the bot work on another phone.

Open Pokémon GO on the map screen of the phone (unfolded / the screen you want to use), then run:

    ~/gbvenv/bin/python device_check.py            (what phone / screen is this?)
    ~/gbvenv/bin/python device_check.py --speed    (how fast can screenshots be taken?)
    ~/gbvenv/bin/python device_check.py --layout   (is the game drawn the way the bot expects? changes nothing)
    ~/gbvenv/bin/python device_check.py --reset-display   (put back a display size the bot changed)

It prints a short report and writes two kinds of files to ~/debug/:
  device_check.txt             phone model, screens (display ids, sizes), density, Pokémon GO packages
  device_check_<display>.png   one screenshot of every display that is switched on

The text file contains no account data. The screenshots show whatever is on the screen, so look at
them before you share them (trainer name and the map around you are visible).
"""
import os
import re
import sys

import spin_stop as S

OUT_DIR = S.DEBUG_DIR
REPORT = []


def say(line=""):
    print(line, flush=True)
    REPORT.append(line)


def sh(*args, limit=1500):
    """Output of 'adb shell ...' (never raises), cut to a sensible length."""
    try:
        out = S.adb("shell", *args).strip()
    except Exception as e:  # noqa: BLE001
        return f"(failed: {e})"
    return out if len(out) <= limit else out[:limit] + " ..."


def grep(text, *words, keep=12):
    lines = [l.strip() for l in text.splitlines() if any(w in l for w in words)]
    return "\n    ".join(lines[:keep]) or "(nothing found)"


def speed_test(rounds=4):
    """How long does a screenshot take as PNG and as raw data, and do the two show the same colours?
    (The raw way is much faster, but the bot only uses it when the colours match.) Leave the phone
    on a screen that does not move (e.g. the item bag) while this runs."""
    import time

    import cv2
    import numpy as np
    print("Screenshot speed test (keep the screen still) ...", flush=True)
    t_png, t_raw, diffs, fitted = [], [], [], []
    small = lambda im: cv2.resize(im, (221, 276), interpolation=cv2.INTER_AREA).astype(np.int16)
    for i in range(rounds):
        t0 = time.time()
        png = S._grab_png()
        t_png.append(time.time() - t0)
        t0 = time.time()
        raw = S._grab_raw()
        t_raw.append(time.time() - t0)
        if raw.shape != png.shape:
            print(f"  round {i + 1}: raw {raw.shape[1]}x{raw.shape[0]} and PNG {png.shape[1]}x{png.shape[0]} differ in size")
            continue
        diff = float(np.abs(small(png) - small(raw)).mean())
        xf = S._fit_colours(raw, png)
        after = float(np.abs(small(png) - small(cv2.transform(raw, xf))).mean())
        diffs.append(diff)
        fitted.append(after)
        print(f"  round {i + 1}: PNG {t_png[-1]:.2f} s, raw {t_raw[-1]:.2f} s, colour difference {diff:.1f}"
              f" -> {after:.1f} after the colour fit", flush=True)
        if i == 0:
            cv2.imwrite(os.path.join(OUT_DIR, "speed_png.png"), png)
            cv2.imwrite(os.path.join(OUT_DIR, "speed_raw.png"), raw)
    if not diffs:
        say("== Screenshot speed: no comparable pairs")
        return
    say("\n== Screenshot speed")
    say(f"  PNG  {np.mean(t_png):.2f} s on average ({min(t_png):.2f} - {max(t_png):.2f})")
    say(f"  raw  {np.mean(t_raw):.2f} s on average ({min(t_raw):.2f} - {max(t_raw):.2f})")
    say(f"  colour difference raw against PNG: {np.mean(diffs):.1f}, after fitting {np.mean(fitted):.1f} "
        f"(the bot uses raw screenshots when this is below 4 and raw is clearly faster)")
    say("  pictures: ~/debug/speed_png.png and speed_raw.png (compare them: is the raw one paler or more saturated?)")


def layout_report():
    """Read-only: where is the Poké Ball menu button on this phone, and what would the bot do about it?
    Open Pokémon GO on the map first. Nothing on the phone is changed."""
    print("Layout check (Pokémon GO has to be on the map) ...", flush=True)
    try:
        S.adb("get-state")
    except Exception as e:  # noqa: BLE001
        say(f"No phone found over ADB ({e}).")
        return 1
    S.screen["checked"] = 0.0
    if not S.detect_screen(wake=False):
        say("No display could be captured.")
        return 1
    w, h = S.screen["w"], S.screen["h"]
    say(f"Screen the bot would use: {w}x{h}, width/height {w / h:.2f} (the canvas has {S.REF_W / S.REF_H:.2f})")
    try:
        phys, over = S.wm_info()
        say(f"wm size: physical {phys[0]}x{phys[1]}" + (f", override {over[0]}x{over[1]}" if over else ", no override") if phys else "wm size: unknown")
        mine = S.load_wm_record()
        if over and mine:
            say(f"The display size {mine.get('set')} was set by this bot. Put it back with: device_check.py --reset-display")
        elif over:
            say("This override was not set by this bot: the bot will leave it alone (adb shell wm size reset removes it).")
    except Exception as e:  # noqa: BLE001
        say(f"wm size does not work here ({e})")
    img = S.screenshot()
    os.makedirs(OUT_DIR, exist_ok=True)
    import cv2
    cv2.imwrite(os.path.join(OUT_DIR, "layout_check.png"), img)
    found = S.find_menu_button(img)
    ok, text = S.menu_button_check(found)
    say(f"Menu button: {text}")
    if ok:
        say("=> The game is drawn the way the bot expects. Nothing to do.")
    else:
        if ok is None:
            say("=> Not found: is Pokémon GO on the map (no dialog in front)? Look at ~/debug/layout_check.png.")
        else:
            say("=> The button is somewhere else than expected: the bot will try to let Android draw the game in the right shape.")
        cmd, size, why = S.display_plan()
        if cmd:
            say(f"   It would run: adb shell wm size {cmd}  (screenshots then {size[0]}x{size[1]}; black bars on the phone; put back when the bot stops)")
        else:
            say(f"   It would not change the display: {why}")
    path = os.path.join(OUT_DIR, "layout_check.txt")
    with open(path, "w") as f:
        f.write("\n".join(REPORT) + "\n")
    print(f"\nReport written to {path} (picture: {os.path.join(OUT_DIR, 'layout_check.png')})")
    return 0


def main():
    if "--layout" in sys.argv:
        return layout_report()
    if "--reset-display" in sys.argv:
        if S.load_wm_record():
            print("display size put back" if S.restore_display() else "could not put the display size back (see above)")
        else:
            print("This bot has not changed the display size (no " + S.WM_FILE + "). To remove any override anyway: adb shell wm size reset")
        return 0
    if "--speed" in sys.argv:
        os.makedirs(OUT_DIR, exist_ok=True)
        speed_test()
        return 0
    os.makedirs(OUT_DIR, exist_ok=True)
    try:
        S.adb("get-state")
    except Exception as e:  # noqa: BLE001
        print(f"No phone found over ADB ({e}).\nCheck the USB cable and that USB debugging is on ('adb devices').")
        return 1

    say("== Phone")
    for name, prop in (("manufacturer", "ro.product.manufacturer"), ("model", "ro.product.model"),
                       ("device", "ro.product.device"), ("Android", "ro.build.version.release"),
                       ("SDK level", "ro.build.version.sdk")):
        say(f"  {name}: {sh('getprop', prop)}")
    say(f"  wm size: {sh('wm', 'size')}")
    say(f"  wm density: {sh('wm', 'density')}")

    say("\n== Displays")
    ids_raw = sh("dumpsys", "SurfaceFlinger", "--display-id")
    say("  SurfaceFlinger --display-id:\n    " + ids_raw.replace("\n", "\n    "))
    say("  display devices (dumpsys display):\n    " + grep(sh("dumpsys", "display", limit=60000), "DisplayDeviceInfo", "mBaseDisplayInfo"))

    say("\n== Pokémon GO")
    say("  installed: " + (sh("pm", "list", "packages", "pokemongo").replace("\n", ", ") or "(not found)"))
    say("  in front: " + grep(sh("dumpsys", "window", limit=200000), "mCurrentFocus", keep=2))

    say("\n== Screenshots")
    S.screen["checked"] = 0.0
    found = S.detect_screen(wake=False)
    ids = re.findall(r"Display (\d+)", ids_raw) or [None]
    shots = 0
    for d in ids:
        info = S._screencap_info(d)
        if not info:
            say(f"  display {d or 'default'}: cannot be captured")
            continue
        w, h, bright = info
        state = "on" if bright > 3.0 else "off (black)"
        say(f"  display {d or 'default'}: {w}x{h}, width/height {w / h:.2f}, {state}")
        if bright > 3.0:
            try:
                raw = S.adb("exec-out", "screencap", *(["-d", str(d)] if d else []), "-p", binary=True)
                path = os.path.join(OUT_DIR, f"device_check_{d or 'default'}.png")
                with open(path, "wb") as f:
                    f.write(raw[raw.find(b"\x89PNG"):])
                say(f"    saved {path}")
                shots += 1
            except Exception as e:  # noqa: BLE001
                say(f"    could not save the screenshot: {e}")

    say("\n== Verdict")
    if not found:
        say("  No display could be captured.")
    else:
        w, h = S.screen["w"], S.screen["h"]
        say(f"  The bot would use display {S.screen['id'] or 'default'} ({w}x{h}).")
        say(f"  The bot is written for {S.REF_W}x{S.REF_H} (width/height {S.REF_W / S.REF_H:.2f}); "
            f"this screen has {w / h:.2f}, allowed difference {S.ASPECT_TOLERANCE:.0%}.")
        if S.screen["ok"]:
            if (w, h) == S.EXPECTED_SIZE:
                say("  This screen has exactly the size the bot is written for.")
            else:
                say("  This screen has a similar shape: the bot converts all positions to it automatically.")
        else:
            say("  This screen has a different shape. The bot will try to let Android draw the game in the right shape")
            say("  (wm size, with black bars; put back when the bot stops) and checks that with the Poké Ball menu button.")
            say("  Run 'device_check.py --layout' with the game on the map to see what it would do. If that does not work")
            say("  on this phone, send device_check.txt and the screenshots so that it can be added.")

    path = os.path.join(OUT_DIR, "device_check.txt")
    with open(path, "w") as f:
        f.write("\n".join(REPORT) + "\n")
    print(f"\nReport written to {path}" + (f" and {shots} screenshot(s) in {OUT_DIR}" if shots else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
