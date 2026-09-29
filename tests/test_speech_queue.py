#!/usr/bin/env python3
# Part of 3dspeex: https://github.com/daiverd/3dspeex
# Copyright (C) 2026  daiverd <david@rustytelephone.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
"""Tests for screen_reader's speech queue talking to speech_helper.py.

Run: python3 tests/test_speech_queue.py

Uses a small stand-in for Klipper's reactor and the fake speech command
from test_speech_helper, so no printer or sound card is needed.
"""
import os
import select
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import screen_reader  # noqa: E402
from test_speech_helper import FAKE, log  # noqa: E402

HELPER = os.path.abspath(screen_reader.HELPER)


class Reactor:
    NOW, NEVER = 0., 9999999999999999.

    def __init__(self):
        self.timers = {}
        self.fds = {}

    def monotonic(self):
        return time.monotonic()

    def register_timer(self, callback, waketime=NEVER):
        self.timers[callback] = waketime
        return callback

    def update_timer(self, timer, waketime):
        self.timers[timer] = waketime

    def register_fd(self, fd, callback):
        self.fds[fd] = callback
        return fd

    def unregister_fd(self, handle):
        del self.fds[handle]

    def run(self, secs, until=None):
        end = time.monotonic() + secs
        while time.monotonic() < end and not (until and until()):
            now = time.monotonic()
            for timer, waketime in list(self.timers.items()):
                if waketime <= now:
                    self.timers[timer] = timer(now)
            r, _, _ = select.select(list(self.fds), [], [], 0.01)
            for fd in r:
                if fd in self.fds:
                    self.fds[fd](time.monotonic())


class Printer:
    def __init__(self):
        self.reactor = Reactor()
        self.handlers = {}

    def get_reactor(self):
        return self.reactor

    def register_event_handler(self, event, callback):
        self.handlers[event] = callback

    def lookup_object(self, name, default=None):
        return self

    # the gcode object
    def register_output_handler(self, callback):
        pass

    def register_command(self, *args, **kwargs):
        pass


class Config:
    def __init__(self):
        self.printer = Printer()

    def get_printer(self):
        return self.printer

    def getint(self, name, default, **kwargs):
        return default

    def getboolean(self, name, default):
        return default


def make_reader(tmp, secs):
    """A ScreenReader whose helper runs the fake speech command."""
    wrapper = os.path.join(tmp, 'helper.py')
    with open(wrapper, 'w') as f:
        f.write("import os, runpy, sys\n"
                "os.environ.update(D=%r, SECS=%r)\n"
                "sys.argv = [%r, 'sh', '-c', %r]\n"
                "runpy.run_path(sys.argv[0], run_name='__main__')\n"
                % (tmp, str(secs), HELPER, FAKE))
    screen_reader.HELPER = wrapper
    reader = screen_reader.ScreenReader(Config())
    return reader, reader.printer.reactor


def idle(reader):
    return reader.speaking is None and not reader.queue


def test_scrolling_then_event():
    with tempfile.TemporaryDirectory() as tmp:
        reader, reactor = make_reader(tmp, 0.3)
        reader._say("printer ready")
        reactor.run(1, lambda: reader.helper is not None)
        for i in range(1, 16):  # knob turns interrupt each other
            reader._say("item %d" % (i,), interrupt=True)
            reactor.run(0.05)
        reader._say("bed at 60", key='bed')  # an event waits its turn
        reactor.run(5, lambda: idle(reader))
        assert idle(reader)
        helper = reader.helper
        reader._close_helper()  # klippy:disconnect
        assert helper.poll() is not None
        lines = log(tmp)
        assert "OVERLAP" not in lines, lines
        assert lines[-2:] == ["said item 15", "said bed at 60"], lines


def test_restarts_dead_helper():
    with tempfile.TemporaryDirectory() as tmp:
        screen_reader.HELPER_RETRY = 0.2
        reader, reactor = make_reader(tmp, 0.1)
        reader._say("one")
        reactor.run(2, lambda: idle(reader))
        first = reader.helper
        first.kill()
        first.wait()
        reader._say("two")
        reactor.run(3, lambda: idle(reader) and reader.helper is not None)
        assert reader.helper is not None and reader.helper is not first
        reader._close_helper()
        assert log(tmp) == ["said one", "said two"], log(tmp)


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
