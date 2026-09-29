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

FAKE = r'''
# slow to let go when stopped, like a busy sound device
trap 'sleep 0.2; rmdir "$D/lock"; exit 0' TERM
mkdir "$D/lock" 2>/dev/null || echo OVERLAP >> "$D/log"
read -r text
echo "said $text" >> "$D/log"
sleep "$SECS" & wait $!
rmdir "$D/lock"
'''


class Helper:
    def __init__(self, tmp, secs):
        env = dict(os.environ, D=tmp, SECS=str(secs))
        self.proc = subprocess.Popen(
            [sys.executable, HELPER, 'sh', '-c', FAKE],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)

    def send(self, line):
        self.proc.stdin.write((line + '\n').encode())
        self.proc.stdin.flush()

    def replies(self, count, timeout=10):
        out = []
        end = time.monotonic() + timeout
        while len(out) < count and time.monotonic() < end:
            r, _, _ = select.select([self.proc.stdout], [], [], 0.1)
            if r:
                out.append(self.proc.stdout.readline().decode().strip())
        return out

    def close(self):
        self.proc.stdin.close()
        return self.proc.wait(5)


def log(tmp):
    try:
        with open(os.path.join(tmp, 'log')) as f:
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
