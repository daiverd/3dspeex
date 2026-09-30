#!/usr/bin/env python3
# speech_helper.py - the one process that talks, for screen_reader.py
#
# Part of 3dspeex: https://github.com/daiverd/3dspeex
# Copyright (C) 2026  daiverd <david@rustytelephone.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# screen_reader starts this once and keeps it running, so Klipper never
# forks per line and speech can't pile up. It says one thing at a time:
# a new line stops the current one, and waits for it to exit, before
# starting.
#
# Protocol, one UTF-8 line each way:
#   in:  say <id> <text>   stop what's being said and say text
#        stop              stop what's being said
#   out: done <id>         that line finished or was stopped
# End of input stops speech and exits.
#
# Usage: speech_helper.py [--rate N] [--voice NAME] [--volume N]
#        speech_helper.py command ...
# The first form uses espeak-ng; screen_reader passes the settings from
# [screen_reader]. The second runs any command that reads the text on
# stdin, ignoring those settings. To use another speech engine, replace
# this file with anything that speaks the same protocol.
import argparse
import os
import select
import subprocess
import sys

DEFAULT_RATE = 170    # words per minute
DEFAULT_VOLUME = 100  # 0 to 200
CHECK_TIME = 0.05  # how often to check whether speech has finished
STOP_WAIT = 1.0    # how long to let a stopped command exit before kill


class Speaker:
    def __init__(self, cmd):
        self.cmd = cmd
        self.proc = None
        self.id = None

    def say(self, line_id, text):
        self.stop()
        try:
            proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        except OSError as e:
            log("can't run %s: %s" % (self.cmd[0], e))
            reply(line_id)
            return
        self.proc, self.id = proc, line_id
        try:
            # espeak-ng --stdin drops the last byte of input, expecting
            # a newline
            proc.stdin.write((text + '\n').encode('utf-8'))
            proc.stdin.close()
        except OSError:
            pass  # it exited early; check() reports it

    def stop(self):
        if self.proc is None:
            return
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(STOP_WAIT)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self._finished()

    def check(self):
        if self.proc is not None and self.proc.poll() is not None:
            self._finished()

    def _finished(self):
        line_id, self.proc, self.id = self.id, None, None
        reply(line_id)


def reply(line_id):
    sys.stdout.write("done %s\n" % (line_id,))
    sys.stdout.flush()


def log(msg):
    sys.stderr.write("speech_helper: %s\n" % (msg,))
    sys.stderr.flush()


def handle(speaker, line):
    cmd, _, rest = line.partition(' ')
    if cmd == 'say':
        line_id, _, text = rest.partition(' ')
        speaker.say(line_id, text)
    elif cmd == 'stop':
        speaker.stop()
    elif cmd:
        log("unknown command %r" % (cmd,))


def speak_cmd(argv):
    parser = argparse.ArgumentParser(prog='speech_helper.py')
    parser.add_argument('--rate', type=int, default=DEFAULT_RATE)
    parser.add_argument('--voice')
    parser.add_argument('--volume', type=int, default=DEFAULT_VOLUME)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv[1:])
    if args.command:
        return args.command
    cmd = ['espeak-ng', '-s', str(args.rate), '-a', str(args.volume)]
    if args.voice:
        cmd += ['-v', args.voice]
    return cmd + ['--stdin']


def main(argv):
    speaker = Speaker(speak_cmd(argv))
    fd = sys.stdin.fileno()
    buf = b''
    try:
        while True:
            timeout = CHECK_TIME if speaker.proc is not None else None
            readable, _, _ = select.select([fd], [], [], timeout)
            if readable:
                data = os.read(fd, 4096)
                if not data:
                    break
                buf += data
                while b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    handle(speaker, line.decode('utf-8', 'replace'))
            speaker.check()
    except BrokenPipeError:
        pass  # screen_reader is gone
    finally:
        try:
            speaker.stop()
        except BrokenPipeError:
            pass


if __name__ == '__main__':
    main(sys.argv)
