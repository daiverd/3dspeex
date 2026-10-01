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
#        rate <N>          words per minute, from the next line on
#        voice [<name>]    espeak-ng voice from the next line on (no name:
#                          espeak-ng's default)
#        volume [<N>]      set the sound card's volume to N percent; with
#                          no N, just report it
#   out: done <id>         that line finished or was stopped
#        voice <name>      the voice in use, after "voice" (unchanged if
#                          the one asked for doesn't exist)
#        volume <N>        the card's volume, after "volume" ("none"
#                          after an error: there's no volume to set)
#        error <text>      a problem to tell the user about
#        info <text>       something for the log
# End of input stops speech and exits.
#
# Usage: speech_helper.py [--rate N] [--voice NAME] [mixer options]
#        speech_helper.py [mixer options] command ...
# The first form uses espeak-ng; screen_reader passes the settings from
# [screen_reader]. The second runs any command that reads the text on
# stdin, and can't change its rate or voice. To use another speech
# engine, replace this file with anything that speaks the same protocol.
#
# Volume is the sound card's own mixer (ALSA, through amixer), not
# espeak-ng's, so 100% is as loud as the card goes. Mixer options:
# --mixer-device (default "default", the card /etc/asound.conf picks) and
# --mixer-control (default: found by find_control).
import argparse
import os
import re
import select
import subprocess
import sys

DEFAULT_RATE = 170  # words per minute
CHECK_TIME = 0.05  # how often to check whether speech has finished
STOP_WAIT = 1.0    # how long to let a stopped command exit before kill
AMIXER_TIMEOUT = 5.0

# Playback controls are named differently on every card. Without
# --mixer-control, take the first of these the card has, else its first
# playback control that isn't an input. A USB headset adapter's
# "Sidetone", for one, has a playback volume but is the microphone fed
# back to the headphones.
OUTPUT_CONTROLS = ('Master', 'PCM', 'Speaker', 'Headphone', 'Headset')
NOT_OUTPUT = re.compile(
    r'sidetone|mic|capture|input|loopback|monitor|boost|line in', re.I)


class Speaker:
    def __init__(self, cmd):
        self.cmd = cmd  # returns the speech command to run
        self.proc = None
        self.id = None

    def say(self, line_id, text):
        self.stop()
        cmd = self.cmd()
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        except OSError as e:
            log("can't run %s: %s" % (cmd[0], e))
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


class Espeak:
    """The espeak-ng command line, with the rate and voice to use"""
    def __init__(self, rate, voice):
        self.rate, self.voice = rate, voice or ''

    def command(self):
        cmd = ['espeak-ng', '-s', str(self.rate)]
        if self.voice:
            cmd += ['-v', self.voice]
        return cmd + ['--stdin']

    def set_voice(self, voice):
        # espeak-ng exits with an error for an unknown voice; -q checks
        # without speaking
        if voice:
            try:
                ok = subprocess.run(
                    ['espeak-ng', '-q', '-v', voice, 'x'],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=AMIXER_TIMEOUT).returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                ok = False
            if not ok:
                send("error voice %s not found" % (voice,))
                return
        self.voice = voice


class FixedCommand:
    """A speech command given on the command line: its own settings"""
    voice = ''

    def __init__(self, cmd):
        self.cmd = cmd

    def command(self):
        return self.cmd

    def set_voice(self, voice):
        send("error the speech command sets its own voice")


class MixerError(Exception):
    pass


def playback_controls(scontents):
    """(name, index, has mute switch) for each control in amixer
    scontents output that has a playback volume"""
    found = []
    for block in re.split(r'^(?=Simple mixer control )', scontents,
                          flags=re.M):
        name = re.match(r"Simple mixer control '(.*)',(\d+)", block)
        caps = re.search(r'Capabilities:(.*)', block)
        if not name or not caps:
            continue
        caps = caps.group(1).split()
        if 'pvolume' in caps or 'volume' in caps:
            found.append((name.group(1), int(name.group(2)),
                          'pswitch' in caps or 'switch' in caps))
    return found


def find_control(controls, wanted=None):
    """The control to set the volume with (see OUTPUT_CONTROLS), or None.
    wanted is a control name, or name,index, as amixer takes it."""
    if wanted:
        name, _, index = wanted.partition(',')
        for control in controls:
            if (control[0].lower() == name.strip().lower()
                    and control[1] == (int(index) if index.strip().isdigit()
                                       else 0)):
                return control
        return None
    for name in OUTPUT_CONTROLS:
        for control in controls:
            if control[0] == name:
                return control
    for control in controls:
        if not NOT_OUTPUT.search(control[0]):
            return control
    return None


def playback_percent(sget):
    """The first playback channel's level in amixer sget output"""
    m = re.search(r'^\s*[^:\n]+: Playback -?\d+ \[(\d+)%\]', sget, re.M)
    if m is None:  # a control with one volume for playback and capture
        m = re.search(r'^\s*[^:\n]+: -?\d+ \[(\d+)%\]', sget, re.M)
    if m is None:
        raise MixerError("can't read the volume")
    return int(m.group(1))


class Mixer:
    """The sound card's volume, through amixer. -M sets it on a scale that
    sounds even, so each step is about as much louder as the last."""
    def __init__(self, device, control):
        self.device, self.wanted = device, control
        self.control = None

    def _amixer(self, *args):
        try:
            proc = subprocess.run(
                ['amixer', '-D', self.device, '-M'] + list(args),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True, timeout=AMIXER_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise MixerError("amixer: %s" % (e,))
        if proc.returncode != 0:
            raise MixerError(proc.stderr.strip() or "amixer failed")
        return proc.stdout

    def _find(self):
        if self.control is None:
            self.control = find_control(
                playback_controls(self._amixer('scontents')), self.wanted)
            if self.control is None:
                raise MixerError("no volume control found")
            send("info volume control %s,%d on %s"
                 % (self.control[0], self.control[1], self.device))
        return "%s,%d" % self.control[:2]

    def volume(self, percent=None):
        """Set the volume (and unmute) if given; return the volume now"""
        for retry in (True, False):
            try:
                control = self._find()
                if percent is not None:
                    args = ['-q', 'sset', control, 'playback',
                            '%d%%' % (percent,)]
                    if self.control[2]:
                        args.append('unmute')
                    self._amixer(*args)
                return playback_percent(self._amixer('sget', control))
            except MixerError:
                # the card may have changed (replugged): look again, once
                if not retry or self.control is None:
                    raise
                self.control = None


def send(line):
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def reply(line_id):
    send("done %s" % (line_id,))


def log(msg):
    sys.stderr.write("speech_helper: %s\n" % (msg,))
    sys.stderr.flush()


def handle(speaker, engine, mixer, line):
    cmd, _, rest = line.partition(' ')
    if cmd == 'say':
        line_id, _, text = rest.partition(' ')
        speaker.say(line_id, text)
    elif cmd == 'stop':
        speaker.stop()
    elif cmd == 'rate':
        if isinstance(engine, Espeak) and rest.strip().isdigit():
            engine.rate = int(rest)
        else:
            send("error can't set the rate to %s" % (rest,))
    elif cmd == 'voice':
        engine.set_voice(rest.strip())
        send("voice %s" % (engine.voice,))
    elif cmd == 'volume':
        try:
            percent = int(rest) if rest.strip() else None
            send("volume %d" % (mixer.volume(percent),))
        except ValueError:
            send("error bad volume %s" % (rest,))
        except MixerError as e:
            log(str(e))
            send("error %s" % (e,))
            send("volume none")
    elif cmd:
        log("unknown command %r" % (cmd,))


def parse_args(argv):
    parser = argparse.ArgumentParser(prog='speech_helper.py')
    parser.add_argument('--rate', type=int, default=DEFAULT_RATE)
    parser.add_argument('--voice')
    parser.add_argument('--mixer-device', default='default')
    parser.add_argument('--mixer-control')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv[1:])
    if args.command:
        engine = FixedCommand(args.command)
    else:
        engine = Espeak(args.rate, args.voice)
    return engine, Mixer(args.mixer_device, args.mixer_control)


def main(argv):
    engine, mixer = parse_args(argv)
    speaker = Speaker(engine.command)
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
                    handle(speaker, engine, mixer,
                           line.decode('utf-8', 'replace'))
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
