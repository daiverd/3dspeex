#!/usr/bin/env python3
# Part of 3dspeex: https://github.com/daiverd/3dspeex
# Copyright (C) 2026  daiverd <david@rustytelephone.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
"""Tests for speech_helper.py: one line at a time, never two at once.

Run: python3 tests/test_speech_helper.py

A fake speech command stands in for espeak-ng. It takes a lock
directory while "talking" and logs OVERLAP if another one holds it.
"""
import os
import select
import subprocess
import sys
import tempfile
import time

HELPER = os.path.join(os.path.dirname(__file__), '..', 'speech_helper.py')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import speech_helper  # noqa: E402

FAKE = r'''
# slow to let go when stopped, like a busy sound device
trap 'sleep 0.2; rmdir "$D/lock"; exit 0' TERM
mkdir "$D/lock" 2>/dev/null || echo OVERLAP >> "$D/log"
read -r text
echo "said $text" >> "$D/log"
sleep "$SECS" & wait $!
rmdir "$D/lock"
'''


# Stand-ins for amixer and espeak-ng, put first on PATH: they log their
# arguments, and amixer prints the mixer in $D/scontents and $D/sget
FAKE_AMIXER = r'''#!/bin/sh
echo "$*" >> "$D/amixer.log"
case "$*" in
  *scontents*) cat "$D/scontents" ;;
  *sget*) cat "$D/sget" ;;
esac
'''
FAKE_ESPEAK = r'''#!/bin/sh
echo "$*" >> "$D/espeak.log"
case "$*" in *bogus*) exit 1 ;; esac
cat > /dev/null
'''

# amixer -M output from a USB headset adapter
HEADSET = """\
Simple mixer control 'Sidetone',0
  Capabilities: pvolume pvolume-joined pswitch pswitch-joined
  Playback channels: Mono
  Limits: Playback 0 - 8192
  Mono: Playback 4096 [35%] [16.00dB] [on]
Simple mixer control 'Headset',0
  Capabilities: pvolume cvolume cvolume-joined pswitch pswitch-joined \
cswitch cswitch-joined
  Playback channels: Front Left - Front Right
  Capture channels: Mono
  Limits: Playback 0 - 24 Capture 0 - 4
  Mono: Capture 1 [25%] [2.00dB] [on]
  Front Left: Playback 20 [69%] [-3.00dB] [on]
  Front Right: Playback 20 [69%] [-3.00dB] [on]
"""
HEADSET_SGET = HEADSET[HEADSET.index("Simple mixer control 'Headset'"):]
# a laptop's onboard card
ONBOARD = """\
Simple mixer control 'Mic Boost',0
  Capabilities: volume
Simple mixer control 'Speaker',0
  Capabilities: pvolume pswitch
Simple mixer control 'Master',0
  Capabilities: pvolume pvolume-joined pswitch pswitch-joined
Simple mixer control 'Capture',0
  Capabilities: cvolume cswitch
"""


def fake_tools(tmp, scontents=HEADSET, sget=HEADSET_SGET):
    """An environment whose amixer and espeak-ng are the fakes"""
    bin_dir = os.path.join(tmp, 'bin')
    os.makedirs(bin_dir, exist_ok=True)
    for name, script in (('amixer', FAKE_AMIXER),
                         ('espeak-ng', FAKE_ESPEAK)):
        path = os.path.join(bin_dir, name)
        with open(path, 'w') as f:
            f.write(script)
        os.chmod(path, 0o755)
    for name, text in (('scontents', scontents), ('sget', sget)):
        with open(os.path.join(tmp, name), 'w') as f:
            f.write(text)
    return dict(os.environ, D=tmp, PATH=bin_dir + os.pathsep
                + os.environ['PATH'])


class Helper:
    def __init__(self, tmp, secs=0, args=None):
        env = dict(fake_tools(tmp), SECS=str(secs))
        if args is None:
            args = ['sh', '-c', FAKE]
        self.proc = subprocess.Popen(
            [sys.executable, HELPER] + args,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=env)
        self.buf = b''

    def send(self, line):
        self.proc.stdin.write((line + '\n').encode())
        self.proc.stdin.flush()

    def replies(self, count, timeout=10):
        # read the pipe directly: replies can arrive several at once
        end = time.monotonic() + timeout
        while self.buf.count(b'\n') < count and time.monotonic() < end:
            r, _, _ = select.select([self.proc.stdout], [], [], 0.1)
            if r:
                self.buf += os.read(self.proc.stdout.fileno(), 4096)
        out = self.buf.split(b'\n')
        out, rest = out[:count], out[count:]
        self.buf = b'\n'.join(rest)
        return [line.decode().strip() for line in out if line]

    def close(self):
        self.proc.stdin.close()
        return self.proc.wait(5)


def log(tmp, name='log'):
    try:
        with open(os.path.join(tmp, name)) as f:
            return f.read().split('\n')[:-1]
    except FileNotFoundError:
        return []


def test_interrupts_never_overlap():
    with tempfile.TemporaryDirectory() as tmp:
        h = Helper(tmp, 0.5)
        for i in range(1, 21):  # fast knob scrolling
            h.send("say %d item %d" % (i, i))
            time.sleep(0.05)
        assert h.replies(20) == ["done %d" % i for i in range(1, 21)]
        assert h.close() == 0
        lines = log(tmp)
        assert "OVERLAP" not in lines, lines
        assert "said item 20" in lines, lines


def test_finishes_on_its_own():
    with tempfile.TemporaryDirectory() as tmp:
        h = Helper(tmp, 0.2)
        h.send("say 7 hello there")
        assert h.replies(1) == ["done 7"]
        h.send("say 8 again")
        assert h.replies(1) == ["done 8"]
        assert h.close() == 0
        assert log(tmp) == ["said hello there", "said again"]


def test_exit_stops_speech():
    with tempfile.TemporaryDirectory() as tmp:
        h = Helper(tmp, 30)
        h.send("say 1 a long message")
        time.sleep(0.3)
        start = time.monotonic()
        assert h.close() == 0
        assert time.monotonic() - start < 2
        assert not os.path.exists(os.path.join(tmp, 'lock'))


def test_missing_command():
    h = subprocess.Popen([sys.executable, HELPER, '/nonexistent/speaker'],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL)
    out, _ = h.communicate(b"say 3 hi\n", timeout=5)
    assert out == b"done 3\n", out


def test_finds_the_output_control():
    controls = speech_helper.playback_controls(HEADSET)
    assert controls == [('Sidetone', 0, True), ('Headset', 0, True)]
    assert speech_helper.find_control(controls) == ('Headset', 0, True)
    assert speech_helper.find_control(controls, 'sidetone') == (
        'Sidetone', 0, True)  # asked for by name
    assert speech_helper.find_control(controls, 'PCM') is None
    controls = speech_helper.playback_controls(ONBOARD)
    assert speech_helper.find_control(controls) == ('Master', 0, True)
    # nothing named, but not an input either
    only = speech_helper.playback_controls(
        "Simple mixer control 'Mic',0\n  Capabilities: pvolume\n"
        "Simple mixer control 'Out 1',0\n  Capabilities: pvolume\n")
    assert speech_helper.find_control(only) == ('Out 1', 0, False)
    assert speech_helper.find_control([('Sidetone', 0, True)]) is None


def test_reads_playback_not_capture():
    # the headset's capture level comes first in its output
    assert speech_helper.playback_percent(HEADSET_SGET) == 69


def test_sets_volume():
    with tempfile.TemporaryDirectory() as tmp:
        h = Helper(tmp)
        h.send("volume")
        h.send("volume 30")
        assert h.replies(3) == ["info volume control Headset,0 on default",
                                "volume 69", "volume 69"]
        assert h.close() == 0
        calls = log(tmp, 'amixer.log')
        assert calls[0] == "-D default -M scontents", calls
        assert ("-D default -M -q sset Headset,0 playback 30% unmute"
                in calls), calls
        assert calls.count("-D default -M scontents") == 1, calls


def test_no_volume_control():
    with tempfile.TemporaryDirectory() as tmp:
        h = Helper(tmp, args=['--mixer-control', 'PCM', 'sh', '-c', FAKE])
        h.send("volume 50")
        assert h.replies(2) == ["error no volume control found",
                                "volume none"]
        h.send("say 1 still talking")
        assert h.replies(1) == ["done 1"]
        assert h.close() == 0


def test_rate_and_voice():
    with tempfile.TemporaryDirectory() as tmp:
        h = Helper(tmp, args=['--rate', '150'])
        h.send("say 1 one")
        assert h.replies(1) == ["done 1"]
        h.send("rate 300")
        h.send("voice en-gb")
        h.send("voice bogus")  # doesn't exist: keeps en-gb
        assert h.replies(3) == ["voice en-gb", "error voice bogus not found",
                                "voice en-gb"]
        h.send("say 2 two")
        assert h.replies(1) == ["done 2"]
        h.send("voice")  # back to espeak-ng's default
        assert h.replies(1) == ["voice"]  # "voice " with no name
        assert h.close() == 0
        said = [c for c in log(tmp, 'espeak.log') if '--stdin' in c]
        assert said == ["-s 150 --stdin", "-s 300 -v en-gb --stdin"], said


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
