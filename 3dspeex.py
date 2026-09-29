# 3dspeex.py - speak what the Klipper LCD shows, and what the printer
# is doing (espeak-ng by default; see speak() to change that)
#
# Part of 3dspeex: https://github.com/daiverd/3dspeex
# Copyright (C) 2026  daiverd <david@rustytelephone.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Install with install.sh, or symlink this file into
# ~/klipper/klippy/extras/ (see README.md).
# Config (printer.cfg or an included file):
#   [3dspeex]
#   progress_step: 10   # announce print progress every N percent (0 = off)
#   announce_info: False  # also speak "// " info lines (chatty)
#
# Menu: each knob turn / click / back says where you are. Entering a menu
# names it, turning within it names just the item, e.g.
#   "Prepare: Back"   "Move Z"   "Speed: 100%, editing"   "Speed: 105%, done"
# Status screen (menu closed): the screen is read out when the menu
# closes, and whenever the knob is turned, e.g.
#   "nozzle 25° fan 0%. bed 24° speed 100%. 0% 00:00. Ready"
# Events: M117 messages, print state and progress, heaters reaching
# target, "!!" errors, RESPOND/M118 echoes, and shutdowns.
# G-code: ANNOUNCE MSG="text"   say a line (for your own macros)
#         ANNOUNCE_SCREEN       read out the screen now
#
# Navigation and screen reads interrupt whatever is being said, like a
# screen reader. Events wait their turn; a newer event of the same kind
# (another M117, the next progress step) replaces one still waiting.
import logging
import re
import subprocess

SPEAK_CMD = ['espeak-ng', '-s', '170', '--stdin']


def speak(text):
    """Start saying text and return without waiting.

    Return something with poll() (None while still talking) and
    terminate(), like a subprocess.Popen, or None if there's nothing to
    wait for. Replace this to change the voice or send the text elsewhere.
    """
    proc = subprocess.Popen(SPEAK_CMD, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    # espeak-ng --stdin drops the last byte of input, expecting a newline
    proc.stdin.write((text + '\n').encode('utf-8'))
    proc.stdin.close()
    return proc


# How LCD icons are read out
GLYPH_WORDS = {
    'extruder': ' nozzle ', 'bed': ' bed ', 'bed_heat1': ' bed ',
    'bed_heat2': ' bed ', 'fan': ' fan ', 'fan1': ' fan ', 'fan2': ' fan ',
    'feedrate': ' speed ', 'clock': ' time ', 'usb': ' usb ', 'sd': ' sd ',
    'degrees': '°', 'right_arrow': ' target ',
}
HEATER_WORDS = {'extruder': 'nozzle', 'extruder1': 'nozzle 2',
                'heater_bed': 'bed'}


# Menu names are written for a 16-character screen, not for listening:
# "Ex0:220 ( 215)", "Load Fil. fast", "Quad Gantry Lvl". These rules
# reword them for speech only; the screen is unchanged. They apply to
# menu names alone (not messages or the status screen), skip file names,
# and each pattern is anchored or whole-word so it only hits the menu
# wording it was written for (from Klipper's and Sovol's menu.cfg).

def _heater_setting(word):
    # "Ex0:220 ( 215)" -> "nozzle target 220, now 215°"; target 0 is "off"
    def repl(m):
        n = int(m.groupdict().get('n') or 0)
        label = word if n == 0 else "%s %d" % (word, n + 1)
        target = int(m.group('target'))
        state = "off" if target == 0 else "target %d" % (target,)
        return "%s %s, now %s°" % (label, state, m.group('now'))
    return repl


TEMP_READING = r':\s*(?P<target>-?\d+)\s*\(\s*(?P<now>-?\d+)\s*\)$'
MONTHS = ('January', 'February', 'March', 'April', 'May', 'June', 'July',
          'August', 'September', 'October', 'November', 'December')


def _date(m):
    # "2025.11.14" -> "November 14, 2025" (Sovol's Information menu)
    year, month, day = (int(g) for g in m.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return m.group(0)
    return "%s %d, %d" % (MONTHS[month - 1], day, year)


def _millimeters(m):
    return "%s millimeter%s" % (m.group(1), "" if m.group(1) == "1" else "s")


SIGN_WORDS = {'++': 'plus plus', '+': 'plus', '--': 'minus minus',
              '-': 'minus'}

SPEECH_RULES = [
    (re.compile(r'^Ex(?P<n>\d)' + TEMP_READING), _heater_setting('nozzle')),
    (re.compile(r'^Bed' + TEMP_READING), _heater_setting('bed')),
    # any other "Ex0" / "Ex1" word, like "Ex0 fan" -> "extruder fan"
    (re.compile(r'\bEx(\d)\b(?!:)'),
     lambda m: "extruder" + ("" if m.group(1) == '0'
                             else " %d" % (int(m.group(1)) + 1))),
    (re.compile(r'^Move E:'), 'Move extruder:'),
    # "Offset Z:0.125": without a space espeak says "colon". Only after a
    # letter, so times like 01:23 are left alone.
    (re.compile(r'(?<=[A-Za-z]):(?=\S)'), ': '),
    (re.compile(r'\b[Ff]il\b\.?'), 'filament '),   # Fil, Fil., fil
    (re.compile(r'\bLvl\b'), 'level'),
    (re.compile(r'\bFW\b'), 'firmware'),
    (re.compile(r'\bcal\.(?=\s|$)'), 'calibration'),
    # an axis glued to a word: "Zoffset" -> "Z offset", also Zhop, Zprobe
    (re.compile(r'\b([XYZ])(?i:(offset|hop|probe|tilt|endstop))\b'),
     r'\1 \2'),
    (re.compile(r'\bExhaustFan\b'), 'exhaust fan'),
    (re.compile(r'\b([XYZE])/([XYZE])\b'), r'\1 and \2'),   # Home X/Y
    (re.compile(r'\b(\d+(?:\.\d+)?) ?mm\b'), _millimeters),  # Move 10mm
    # "Move X:005.0" -> "Move X: 5.0". Only a decimal number ending the
    # name, so codes like "Code: 012345" keep their digits.
    (re.compile(r':\s*([+-]?)0+(?=\d+\.\d+$)'), r': \1'),
    # "+.01" -> "+0.01", or espeak says "plus dot zero one"
    (re.compile(r'(?<![\w.])([+-]?)\.(?=\d)'), r'\g<1>0.'),
    # a bare sign as the value (Test Z: ++ / - / --): espeak skips "-"
    (re.compile(r':\s*(\+\+|--|\+|-)$'),
     lambda m: ": " + SIGN_WORDS[m.group(1)]),
    (re.compile(r'^(\d{4})\.(\d{1,2})\.(\d{1,2})$'), _date),
]
# SD card listings: Klipper only lists these extensions, and names the
# menu item with repr(filename), so allow a closing quote
LOOKS_LIKE_FILE = re.compile(r'\.(gcode|gco|g)[\'"]?$', re.IGNORECASE)


def speakable(name):
    """Reword a menu name for speech (see SPEECH_RULES)."""
    if LOOKS_LIKE_FILE.search(name):
        return name
    for pattern, repl in SPEECH_RULES:
        name = pattern.sub(repl, name)
    return " ".join(name.split())
PRINT_STATES = {
    'paused': "print paused", 'complete': "print complete",
    'cancelled': "print cancelled",
}
POLL_TIME = 1.0
SPEECH_CHECK_TIME = 0.1
MAX_QUEUE = 8
INTERRUPT = object()  # queue key for navigation and screen reads
AT_TEMP = 2.0  # same "close enough" the status screen uses


class ScreenReader:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.progress_step = config.getint('progress_step', 10,
                                           minval=0, maxval=100)
        self.announce_info = config.getboolean('announce_info', False)
        self.speaking = None
        self.queue = []
        self.speech_timer = self.reactor.register_timer(self._speech_pump)
        self.last = None
        self.last_top = None
        self.last_editing = False
        self.menu = None
        self.depth = 0
        self.outer = None
        self.lcd_size = (16, 4)  # replaced by the real size once hooked
        self.grid = self._blank_grid()
        self.screen = []
        self.pending_read = None  # prefix to say before the next screen
        self.printer.register_event_handler("klippy:ready", self._ready)
        self.printer.register_event_handler("klippy:shutdown",
                                            self._shutdown)
        gcode = self.printer.lookup_object('gcode')
        gcode.register_output_handler(self._gcode_output)
        gcode.register_command('ANNOUNCE', self.cmd_ANNOUNCE,
                               desc="Say a line out loud")
        gcode.register_command('ANNOUNCE_SCREEN', self.cmd_ANNOUNCE_SCREEN,
                               desc="Read out the LCD's current text")

    def _ready(self):
        hooked = []
        display = self.printer.lookup_object('display', None)
        if display is None:
            logging.warning("3dspeex: no [display] found")
        else:
            hooked += self._hook_menu(getattr(display, 'menu', None))
            hooked += self._hook_lcd(display.lcd_chip)
        self._init_watch()
        self.reactor.register_timer(self._poll, self.reactor.NOW)
        logging.info("3dspeex: hooked %s", ",".join(hooked))
        self._say("printer voice ready")

    # Menu navigation

    def _hook_menu(self, menu):
        if menu is None:
            return []
        self.menu = menu
        # Wrap every navigation entry point that exists in this Klipper
        # (mainline and vendor forks name/route these differently).
        # key_event can't be hooked: menu_keys captured the bound method at
        # config time, so the encoder calls the original. It routes clicks
        # to press() and turns to up()/down(), which it looks up on the
        # instance, so wrapping those works. A depth counter makes nested
        # calls (press -> stack_push, press -> back -> back) announce once.
        hooked = []
        for name in ('press', 'stack_push', 'up', 'down', 'select', 'back',
                     'exit', 'begin', 'push_container', 'pop_container'):
            orig = getattr(menu, name, None)
            if not callable(orig):
                continue
            setattr(menu, name, self._wrap(menu, name, orig))
            hooked.append(name)
        return hooked

    def _wrap(self, menu, name, orig):
        def wrapper(*args, **kwargs):
            if self.depth == 0:
                self.outer = name
            self.depth += 1
            try:
                return orig(*args, **kwargs)
            finally:
                self.depth -= 1
                if self.depth == 0:
                    self._announce(menu)
        return wrapper

    def _name(self, element):
        try:
            text = element.render_name()
        except Exception:
            text = getattr(element, 'get_name', lambda: '?')()
        return speakable(" ".join(str(text).split()).lstrip(">*~ "))

    def _announce(self, menu):
        try:
            if not menu.is_running():
                # A knob turn with the menu closed does nothing on the
                # printer, so use it as "read me the screen".
                if self.outer in ('up', 'down'):
                    self.pending_read = ""
                    return
                self.last_top = None
                if self.last != "menu closed":
                    self.last = "menu closed"
                    # said together with the status screen once drawn
                    self.pending_read = "menu closed. "
                return
            top = menu.stack_peek()
            item = top.selected_item()
            text = self._name(item) if item is not None else "empty"
            editing = item is not None and item.is_editing()
            if editing != self.last_editing:
                text += ", editing" if editing else ", done"
            if top is not self.last_top:
                text = "%s: %s" % (self._name(top), text)
        except Exception:
            logging.exception("3dspeex: failed to read menu state")
            return
        self.last_top, self.last_editing, self.last = top, editing, text
        self._say(text, interrupt=True)

    # LCD text capture: every screen is drawn as clear, write_text /
    # write_glyph calls, then flush, so keep a text copy of each frame.

    def _hook_lcd(self, lcd):
        try:
            self.lcd_size = lcd.get_dimensions()  # 16x4, or 20x4 on HD44780
        except Exception:
            pass
        self.grid = self._blank_grid()
        hooked = []
        for name, after in (('clear', self._lcd_clear),
                            ('write_text', self._lcd_text),
                            ('write_glyph', self._lcd_glyph),
                            ('flush', self._lcd_flush)):
            orig = getattr(lcd, name, None)
            if not callable(orig):
                continue
            setattr(lcd, name, self._wrap_lcd(orig, after))
            hooked.append('lcd.' + name)
        return hooked

    def _wrap_lcd(self, orig, after):
        def wrapper(*args):
            ret = orig(*args)
            try:
                after(ret, *args)
            except Exception:
                logging.exception("3dspeex: lcd capture failed")
            return ret
        return wrapper

    def _blank_grid(self):
        cols, rows = self.lcd_size
        return [[' '] * cols for _ in range(rows)]

    def _lcd_clear(self, ret):
        self.grid = self._blank_grid()

    def _put(self, x, y, cells):
        if 0 <= y < len(self.grid):
            row = self.grid[y]
            for i, cell in enumerate(cells):
                if 0 <= x + i < len(row):
                    row[x + i] = cell

    def _lcd_text(self, ret, x, y, data):
        if not isinstance(data, str):
            data = bytes(data).decode('utf-8', 'replace')
        self._put(x, y, data)

    def _lcd_glyph(self, ret, x, y, glyph_name):
        if ret:  # number of cells drawn; 0 if the glyph is unknown
            word = GLYPH_WORDS.get(glyph_name, ' %s ' % (glyph_name,))
            self._put(x, y, [word] + [''] * (ret - 1))

    def _lcd_flush(self, ret):
        self.screen = [" ".join("".join(row).split()) for row in self.grid]
        if self.pending_read is not None and not self._menu_running():
            prefix, self.pending_read = self.pending_read, None
            self._say(prefix + self._screen_text(), interrupt=True)

    def _menu_running(self):
        return self.menu is not None and self.menu.is_running()

    def _screen_text(self):
        return ". ".join(r for r in self.screen if r) or "screen blank"

    # Printer events

    def _init_watch(self):
        eventtime = self.reactor.monotonic()
        self.display_status = self.printer.lookup_object('display_status',
                                                         None)
        self.print_stats = self.printer.lookup_object('print_stats', None)
        pheaters = self.printer.lookup_object('heaters', None)
        self.heaters = []
        if pheaters is not None:
            for name in pheaters.get_all_heaters():
                short = name.split()[-1]
                heater = pheaters.lookup_heater(short)
                target = heater.get_status(eventtime)['target']
                self.heaters.append([HEATER_WORDS.get(short, short), heater,
                                     target, True])
        self.last_msg = self._status_message()
        self.last_state = self._print_status(eventtime)['state']
        self.last_bucket = 0

    def _status_message(self):
        if self.display_status is None:
            return None
        return self.display_status.message

    def _print_status(self, eventtime):
        if self.print_stats is None:
            return {'state': None}
        return self.print_stats.get_status(eventtime)

    def _poll(self, eventtime):
        try:
            self._check_message()
            self._check_print(eventtime)
            self._check_heaters(eventtime)
        except Exception:
            logging.exception("3dspeex: status poll failed")
        return eventtime + POLL_TIME

    def _check_message(self):
        msg = self._status_message()
        if msg != self.last_msg:
            self.last_msg = msg
            if msg:
                self._say(msg, key='message')

    def _check_print(self, eventtime):
        status = self._print_status(eventtime)
        state = status['state']
        if state != self.last_state:
            prev, self.last_state = self.last_state, state
            if state == 'printing':
                if prev == 'paused':
                    self._say("print resumed")
                else:
                    self.last_bucket = 0
                    name = (status.get('filename') or '').split('/')[-1]
                    self._say(("printing " + name).strip())
            elif state == 'error':
                self._say("print error: %s" % (status.get('message'),))
            elif state in PRINT_STATES:
                self._say(PRINT_STATES[state])
        if (state == 'printing' and self.progress_step
                and self.display_status is not None):
            progress = self.display_status.get_status(eventtime)['progress']
            bucket = int(progress * 100 + .5) // self.progress_step
            if bucket > self.last_bucket:
                self.last_bucket = bucket
                text = "%d%%" % (bucket * self.progress_step,)
                info = status.get('info') or {}
                if info.get('total_layer'):
                    text += ", layer %s of %s" % (info.get('current_layer'),
                                                  info['total_layer'])
                self._say(text, key='progress')

    def _check_heaters(self, eventtime):
        for entry in self.heaters:
            word, heater, last_target, reached = entry
            status = heater.get_status(eventtime)
            target, temp = status['target'], status['temperature']
            if target != last_target:
                entry[2], entry[3] = target, False
                if target:
                    self._say("%s heating to %.0f°" % (word, target),
                              key=word)
                elif last_target:
                    self._say("%s off, at %.0f°" % (word, temp), key=word)
            elif target and not reached and abs(temp - target) <= AT_TEMP:
                entry[3] = True
                self._say("%s at %.0f°" % (word, target), key=word)

    def _shutdown(self):
        msg, _ = self.printer.get_state_message()
        self._say("shutdown: " + msg.strip().split('\n')[0], interrupt=True)

    def _gcode_output(self, msg):
        for line in msg.split('\n'):
            if line.startswith('!! '):
                self._say("error: " + line[3:])
            elif line.startswith('echo:'):
                self._say(line[5:].strip())
            elif self.announce_info and line.startswith('// '):
                self._say(line[3:])

    def cmd_ANNOUNCE(self, gcmd):
        self._say(gcmd.get('MSG'))

    def cmd_ANNOUNCE_SCREEN(self, gcmd):
        self._say(self._screen_text(), interrupt=True)

    # Speech queue. speak() only starts talking; this timer waits for each
    # line to finish before starting the next, without blocking Klipper.

    def _say(self, text, interrupt=False, key=None):
        if not text:
            return
        if interrupt:
            # Cut off what's being said and jump the queue, but keep
            # waiting events (an error shouldn't vanish on a knob turn).
            self._stop_speaking()
            self.queue = [q for q in self.queue if q[0] != INTERRUPT]
            self.queue.insert(0, (INTERRUPT, text))
        else:
            if key is not None:
                self.queue = [q for q in self.queue if q[0] != key]
            self.queue.append((key, text))
        del self.queue[:-MAX_QUEUE]
        self.reactor.update_timer(self.speech_timer, self.reactor.NOW)

    def _stop_speaking(self):
        try:
            if self.speaking is not None and self.speaking.poll() is None:
                self.speaking.terminate()
        except Exception:
            pass
        self.speaking = None

    def _speech_pump(self, eventtime):
        try:
            if self.speaking is not None and self.speaking.poll() is None:
                return eventtime + SPEECH_CHECK_TIME
            self.speaking = None
            if not self.queue:
                return self.reactor.NEVER
            key, text = self.queue.pop(0)
            self.speaking = speak(text)
        except Exception:
            # never let speaking break the printer
            logging.exception("3dspeex: speak failed")
            self.speaking = None
        return eventtime + SPEECH_CHECK_TIME


def load_config(config):
    return ScreenReader(config)
