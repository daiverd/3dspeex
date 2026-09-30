#!/usr/bin/env python3
# Part of 3dspeex: https://github.com/daiverd/3dspeex
# Copyright (C) 2026  daiverd <david@rustytelephone.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
"""Tests for stepping through the status screen with the knob.

Run: python3 tests/test_status_steps.py

The screen is Sovol's 16x4 layout from display.cfg: item names and
positions as configured, and text as the templates render it.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import screen_reader  # noqa: E402
from test_speech_queue import Config  # noqa: E402

GROUP = '_default_16x4'
SV08_SCREEN = [
    (0, 0, 'extruder', '~extruder~ 180~right_arrow~215~degrees~'),
    (0, 10, 'fan_generic', '~fan1~ 0%'),
    (1, 0, 'heater_bed', '~bed_heat1~ 58~right_arrow~60~degrees~'),
    (1, 10, 'speed_factor', '~feedrate~ 100%'),
    (2, 0, 'print_progress', '   45%    '),
    (2, 1, 'progress_bar', ''),
    (2, 10, 'printing_time', ' 01:07'),
    (3, 0, 'print_status', 'benchy.gcode'),
]
SV08_ORDER = [
    "benchy.gcode", "progress 45%", "time 01:07",
    "nozzle 180 target 215°", "bed 58 target 60°", "fan 0%", "speed 100%",
]


class Template:
    def __init__(self, name):
        self.name = name


class Group:
    def __init__(self, screen):
        self.data_items = [
            (row, col, Template("display_data %s %s:text" % (GROUP, name)))
            for row, col, name, text in screen]


class Display:
    def __init__(self, screen):
        self.show_data_group = Group(screen)

    def draw_text(self, row, col, text, eventtime):
        return col + len(text)


class Menu:
    running = False
    _reverse_navigation = False

    def is_running(self):
        return self.running


class Clock:
    now = 1000.

    def __call__(self):
        return self.now


def make_reader(screen):
    reader = screen_reader.ScreenReader(Config())
    display = Display(screen)
    reader._hook_draw(display)
    reader.menu = Menu()
    reader.clock = reader.reactor.monotonic = Clock()
    reader.screen_data = screen
    return reader


def turn(reader, direction):
    """Turn the knob with the menu closed, then draw the next frame."""
    reader.outer = direction
    reader._announce(reader.menu)
    reader._lcd_clear(None)
    for row, col, name, text in reader.screen_data:
        reader.display.draw_text(row, col, text, 0.)
    reader._lcd_flush(None)
    spoken = reader.queue[-1][1] if reader.queue else None
    reader.queue = []
    return spoken


def test_order_and_ends():
    reader = make_reader(SV08_SCREEN)
    heard = [turn(reader, 'down') for _ in SV08_ORDER]
    assert heard == SV08_ORDER, heard
    assert turn(reader, 'down') == SV08_ORDER[-1]  # stays at the end
    assert turn(reader, 'up') == SV08_ORDER[-2]
    for _ in SV08_ORDER:
        turn(reader, 'up')
    assert turn(reader, 'up') == SV08_ORDER[0]  # stays at the start


def test_resets_after_a_minute():
    reader = make_reader(SV08_SCREEN)
    turn(reader, 'down')
    reader.clock.now += 30
    assert turn(reader, 'down') == SV08_ORDER[1]
    reader.clock.now += 61
    assert turn(reader, 'down') == SV08_ORDER[0]


def draw(reader):
    """Draw the next frame with no knob turn; return what was said."""
    reader._lcd_clear(None)
    for row, col, name, text in reader.screen_data:
        reader.display.draw_text(row, col, text, 0.)
    reader._lcd_flush(None)
    spoken = reader.queue[-1][1] if reader.queue else None
    reader.queue = []
    return spoken


def test_menu_close_says_first_item():
    reader = make_reader(SV08_SCREEN)
    turn(reader, 'down')
    turn(reader, 'down')
    turn(reader, 'down')
    reader.outer = 'back'
    reader._announce(reader.menu)  # menu closed
    assert draw(reader) == "menu closed. " + SV08_ORDER[0]
    assert draw(reader) is None  # said once
    assert turn(reader, 'down') == SV08_ORDER[1]


def test_menu_close_unknown_layout():
    reader = make_reader(SV08_SCREEN)
    reader.display.show_data_group = None
    reader.screen_data = []
    reader.outer = 'back'
    reader._announce(reader.menu)
    reader.grid = [list("Ready")]
    reader._lcd_flush(None)
    assert reader.queue[-1][1] == "menu closed. Ready", reader.queue


def test_reverse_navigation():
    reader = make_reader(SV08_SCREEN)
    reader.menu._reverse_navigation = True
    assert turn(reader, 'up') == SV08_ORDER[0]
    assert turn(reader, 'up') == SV08_ORDER[1]


def test_unplanned_items_first():
    screen = [(0, 0, 'extruder', '~extruder~ 25~degrees~'),
              (1, 0, 'chamber', 'Chamber 31C'),
              (3, 0, 'print_status', 'Ready'),
              (3, 12, 'z_height', 'Z0.20')]
    reader = make_reader(screen)
    heard = [turn(reader, 'down') for _ in range(4)]
    assert heard == ["Chamber 31C", "Z0.20", "Ready", "nozzle 25°"], heard


def test_unknown_layout_reads_screen():
    reader = make_reader(SV08_SCREEN)
    reader.display.show_data_group = None
    reader.frame_items = []
    reader.screen = ["nozzle 25°", "Ready"]
    reader.status_items = []
    reader.outer = 'down'
    reader._announce(reader.menu)
    reader._step_status(reader.pending_step)
    assert reader.queue[-1][1] == "nozzle 25°. Ready", reader.queue


if __name__ == '__main__':
    failures = 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for test in tests:
        try:
            test()
            print("ok   %s" % (test.__name__,))
        except AssertionError as e:
            failures += 1
            print("FAIL %s: %s" % (test.__name__, e))
    print("%d tests, %d failures" % (len(tests), failures))
    sys.exit(1 if failures else 0)
