#!/usr/bin/env python3
# Part of 3dspeex: https://github.com/daiverd/3dspeex
# Copyright (C) 2026  daiverd <david@rustytelephone.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
"""Tests for the menu-name rewording in screen_reader.speakable().

Run: python3 tests/test_speakable.py

Names are as the screen shows them (rendered from mainline Klipper's and
Sovol's menu.cfg), with runs of spaces collapsed the way screen_reader
does before rewording. Add a case for every new rule, and a "must not
change" case for anything it could wrongly match.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from screen_reader import speakable  # noqa: E402

REWORDED = [
    # temperature settings
    ("Ex0:220 ( 215)", "nozzle target 220, now 215°"),
    ("Ex0: 0 ( 23)", "nozzle off, now 23°"),
    ("Ex1:200 ( 41)", "nozzle 2 target 200, now 41°"),
    ("Bed: 60 ( 58)", "bed target 60, now 58°"),
    ("Bed: 0 ( -3)", "bed off, now -3°"),
    # other extruder words
    ("Ex0", "extruder"),
    ("Ex0 fan", "extruder fan"),
    ("Ex1 fan", "extruder 2 fan"),
    ("Tune Ex1 PID", "Tune extruder 2 PID"),
    ("Move E:+005.0", "Move extruder: +5.0"),
    ("Move E:-010.0", "Move extruder: -10.0"),
    # numbers after a colon
    ("Move X:005.0", "Move X: 5.0"),
    ("Move Z:000.0", "Move Z: 0.0"),
    ("Offset Z:00.20", "Offset Z: 0.20"),
    ("Offset Z:0.125", "Offset Z: 0.125"),
    ("Offset Z:-0.05", "Offset Z: -0.05"),
    ("ExhaustFan:100%", "exhaust fan: 100%"),
    # Test Z (manual probe) values
    ("Test Z: ++", "Test Z: plus plus"),
    ("Test Z: +", "Test Z: plus"),
    ("Test Z: +.01", "Test Z: +0.01"),
    ("Test Z: +.5", "Test Z: +0.5"),
    ("Test Z: -.1", "Test Z: -0.1"),
    ("Test Z: -", "Test Z: minus"),
    ("Test Z: --", "Test Z: minus minus"),
    # abbreviations
    ("Fil", "filament"),
    ("Change fil", "Change filament"),
    ("Load Fil", "Load filament"),
    ("Load Fil. fast", "Load filament fast"),
    ("Unload Fil.slow", "Unload filament slow"),
    ("Quad Gantry Lvl", "Quad Gantry level"),
    ("Restart FW", "Restart firmware"),
    ("Delta cal. auto", "Delta calibration auto"),
    ("Calibrate Zoffset", "Calibrate Z offset"),
    ("Set Zhop", "Set Z hop"),
    ("Xoffset", "X offset"),
    ("Home X/Y", "Home X and Y"),
    ("Move 10mm", "Move 10 millimeters"),
    ("Move 1mm", "Move 1 millimeter"),
    ("Move 0.1mm", "Move 0.1 millimeters"),
    ("2025.11.14", "November 14, 2025"),
    # SD card file names: only the extension goes, and repr() quotes
    ("Fil_holder.gcode", "Fil_holder"),
    ("'Lvl test.gcode'", "Lvl test"),
    ("FW update.GCO", "FW update"),
    ("Fil cal.g", "Fil cal"),
    ("Recal.gcode", "Recal"),
    ("Move 10mm.gcode", "Move 10mm"),
    ("2025.11.14.gcode", "2025.11.14"),
    ("Test Z: -.g", "Test Z: -"),
    ("Benchy_0.2mm_PLA_1h2m.gcode", "Benchy_0.2mm_PLA_1h2m"),
]

UNCHANGED = [
    # real menu items that are fine as they are
    "Bed Mesh", "Bed probe", "Tune Hotbed PID", "Preheat hotend",
    "Filament", "Feed: 5.0", "Speed: 100%", "Fan speed: 5%", "Fan: ON",
    "Led: ON", "Save & Exit", "Timelapse: ON", "Show IP", "Z Tilt",
    "Home Z", "2.5.0", "Code: 012345", "Code: 000123", "Move Z: 0.20",
    "PID tuning", "SD Card", "Preheat PLA", "Auto-Calibrate",
    # lookalikes the rules must not touch
    "Ex01", "Ex0fan", "Ex0: hot", "Extruder test", "Bed: hot",
    "Exhaust fan", "Profile fil2", "FWD motion", "calibrate", "Zeta",
    "Zoffsets", "XYZ/ABC", "Home X/YZ", "5mmx", "Printed 01:23",
    "2025.13.40", "v1.2.3", "Z-offset",
]


def main():
    failures = 0
    cases = REWORDED + [(name, name) for name in UNCHANGED]
    for name, want in cases:
        got = speakable(name)
        if got != want:
            failures += 1
            print("FAIL %r -> %r (want %r)" % (name, got, want))
    print("%d cases, %d failures" % (len(cases), failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
