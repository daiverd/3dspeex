#!/usr/bin/env python3
# Part of 3dspeex: https://github.com/daiverd/3dspeex
# Copyright (C) 2026  daiverd <david@rustytelephone.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
"""Tests for SCREEN_READER_SET: changing, saving and resetting settings.

Run: python3 tests/test_settings.py

Uses the stand-ins from test_speech_queue and test_speech_helper (a fake
speech command and a fake amixer for a USB headset adapter).
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import screen_reader  # noqa: E402
from test_speech_helper import log  # noqa: E402
from test_speech_queue import Config, idle, make_reader  # noqa: E402


class GCmd:
    def __init__(self, **params):
        self.params = params
        self.responses = []

    def get(self, name, default=None, **kwargs):
        return self.params.get(name, default)

    def get_int(self, name, default=None, minval=None, maxval=None):
        value = self.params.get(name, default)
        if value is not None:
            assert minval is None or value >= minval
            assert maxval is None or value <= maxval
        return value

    def respond_info(self, msg):
        self.responses.append(msg)


def started(tmp, **options):
    """A reader whose config is in tmp, with its helper running"""
    config = Config(**options)
    config.printer.start_args = {
        'config_file': os.path.join(tmp, 'printer.cfg')}
    reader, reactor = make_reader(tmp, 0.05, config)
    reader._say("ready")
    reactor.run(3, lambda: idle(reader) and reader.volume_now is not None)
    return reader, reactor


def saved(tmp):
    with open(os.path.join(tmp, screen_reader.SETTINGS_FILE)) as f:
        return json.load(f)


def test_card_volume_left_alone_unless_set():
    with tempfile.TemporaryDirectory() as tmp:
        reader, reactor = started(tmp)
        assert reader.get_status(0)['volume'] == 69  # what the card says
        assert not any('sset' in c for c in log(tmp, 'amixer.log'))
        reader._close_helper()


def test_set_saves_and_restores():
    with tempfile.TemporaryDirectory() as tmp:
        screen_reader.SAVE_DELAY = 0.1
        reader, reactor = started(tmp, speech_rate=170)
        gcmd = GCmd(RATE=250, VOLUME=5, PROGRESS_STEP=25, ANNOUNCE_INFO=1)
        reader.cmd_SCREEN_READER_SET(gcmd)
        assert gcmd.responses == []  # quiet when changing, for the menu
        reactor.run(1, lambda: os.path.exists(
            os.path.join(tmp, screen_reader.SETTINGS_FILE)))
        assert saved(tmp) == {'rate': 250, 'volume': 10,  # the floor
                              'progress_step': 25, 'announce_info': True}
        assert ("-D default -M -q sset Headset,0 playback 10% unmute"
                in log(tmp, 'amixer.log'))
        status = reader.get_status(0)
        assert (status['rate'], status['volume']) == (250, 10), status
        reader._close_helper()
        # restarted: the saved settings win over printer.cfg
        again, _ = started(tmp, speech_rate=170)
        assert (again.rate, again.volume, again.progress_step,
                again.announce_info) == (250, 10, 25, True)
        assert again.helper_args()[:2] == ['--rate', '250']
        again._close_helper()


def test_reset_goes_back_to_config():
    with tempfile.TemporaryDirectory() as tmp:
        screen_reader.SAVE_DELAY = 0.1
        reader, reactor = started(tmp, speech_rate=170)
        reader.cmd_SCREEN_READER_SET(GCmd(RATE=300))
        reactor.run(1, lambda: os.path.exists(
            os.path.join(tmp, screen_reader.SETTINGS_FILE)))
        reader.cmd_SCREEN_READER_SET(GCmd(RESET=1))
        assert reader.rate == 170
        assert not os.path.exists(
            os.path.join(tmp, screen_reader.SETTINGS_FILE))
        reactor.run(2, lambda: idle(reader))
        assert "said settings reset" in log(tmp)
        reader._close_helper()


def test_missing_voice_is_said_and_not_kept():
    with tempfile.TemporaryDirectory() as tmp:
        reader, reactor = started(tmp)
        # the fake speech command can't change voice, like a bad name
        reader.cmd_SCREEN_READER_SET(GCmd(VOICE='en-gb'))
        reactor.run(2, lambda: reader.voice == '' and idle(reader))
        assert reader.voice == ''
        assert ("said the speech command sets its own voice"
                in log(tmp)), log(tmp)
        reader._close_helper()


def test_report():
    with tempfile.TemporaryDirectory() as tmp:
        reader, reactor = started(tmp, voice='')
        gcmd = GCmd()
        reader.cmd_SCREEN_READER_SET(gcmd)
        assert gcmd.responses == [
            "rate 170, voice default, volume 69%, progress step 10%,"
            " info lines off"], gcmd.responses
        reader._close_helper()


def test_voice_list():
    reader = screen_reader.ScreenReader(
        Config(voices='en-us, en-gb ,en-us+f3', voice='en-gb'))
    status = reader.get_status(0)
    assert status['voices'] == ['en-us', 'en-gb', 'en-us+f3']
    assert status['voice_index'] == 1
    assert status['volume'] == -1  # the card isn't known yet


def test_progress_choices():
    for step, index in ((0, 0), (1, 1), (10, 3), (20, 4), (100, 4)):
        status = screen_reader.ScreenReader(
            Config(progress_step=step)).get_status(0)
        assert status['progress_steps'][status['progress_index']] == \
            screen_reader.PROGRESS_STEPS[index], (step, status)


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
