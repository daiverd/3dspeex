# screen_reader.py - speak what the Klipper LCD shows, and what the printer
# is doing (through speech_helper.py; espeak-ng by default)
#
# Part of 3dspeex: https://github.com/daiverd/3dspeex
# Copyright (C) 2026  daiverd <david@rustytelephone.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Install with install.sh, or symlink this file into
# ~/klipper/klippy/extras/ (see README.md).
# Config (printer.cfg or an included file):
#   [screen_reader]
#   progress_step: 10   # announce print progress every N percent (0 = off)
#   announce_info: False  # also speak "// " info lines (chatty)
#
# Menu: each knob turn / click / back says where you are. Entering a menu
# names it, turning within it names just the item, e.g.
#   "Prepare: Back"   "Move Z"   "Speed: 100%, editing"   "Speed: 105%, done"
# Status screen (menu closed): turning the knob steps through it one
# item at a time, most interesting first (see STATUS_ORDER): the way that
# moves down a menu goes to the next item, the other way back. Closing
# the menu says the first item, e.g. "menu closed. Ready". After a minute
# without turning, it starts again from the top. ANNOUNCE_SCREEN reads
# the whole screen, e.g.
#   "nozzle 25° fan 0%. bed 24° speed 100%. 0% 00:00. Ready"
# Events: M117 messages, print state and progress, heaters reaching
# target, "!!" errors, RESPOND/M118 echoes, and shutdowns.
# G-code: ANNOUNCE MSG="text"   say a line (for your own macros)
#         ANNOUNCE_SCREEN       read out the screen now
#
# Navigation and screen reads interrupt whatever is being said, like a
# screen reader. Events wait their turn; a newer event of the same kind
# (another M117, the next progress step) replaces one still waiting.
import fcntl
import logging
import os
import re
import signal
import subprocess
import sys

# One long-running process does all the talking (see its header), so
# Klipper never forks per line and only one line plays at a time.
HELPER = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                      'speech_helper.py')


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
HELPER_RETRY = 10.0     # wait this long before restarting a failed helper
SPEECH_TIMEOUT = 120.0  # give up on a line the helper never finishes
MAX_LINE_BYTES = 4000   # under PIPE_BUF, so each write is all or nothing
MAX_QUEUE = 8
INTERRUPT = object()  # queue key for navigation and screen reads
AT_TEMP = 2.0  # same "close enough" the status screen uses

# Status screen items in the order the knob steps through them, most
# interesting first, named as in Klipper's display.cfg ([display_data
# <group> <item>]). Items not listed here (a vendor's or your own) come
# first, since they're what's unusual about this printer; items that
# draw no text, like the progress bar or a missing second extruder, are
# skipped.
STATUS_ORDER = [
    'print_status', 'print_progress', 'printing_time',
    'extruder', 'extruder1', 'heater_bed',
    'fan', 'fan_generic', 'speed_factor',
]
# Said before items that have no icon to name them
STATUS_LABELS = {'print_progress': 'progress', 'printing_time': 'time'}
STATUS_RESET = 60.0  # seconds without turning before starting over


class ScreenReader:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.progress_step = config.getint('progress_step', 10,
                                           minval=0, maxval=100)
        self.announce_info = config.getboolean('announce_info', False)
        self.helper = None
        self.helper_handle = None
        self.helper_buf = b''
        self.helper_started = None
        self.line_id = 0
        self.speaking = None  # id of the line the helper is saying
        self.speaking_since = 0.
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
        self.pending_read = None  # prefix to say before the first item
        self.display = None
        self.frame_items = []   # (row, col, text) drawn in this frame
        self.status_items = []  # (item name, words) in STATUS_ORDER
        self.pending_step = None  # +1 / -1 to step on the next frame
        self.status_pos = -1    # -1 is before the first item
        self.last_step = 0.
        self.printer.register_event_handler("klippy:ready", self._ready)
        self.printer.register_event_handler("klippy:shutdown",
                                            self._shutdown)
        self.printer.register_event_handler("klippy:disconnect",
                                            self._close_helper)
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
            logging.warning("screen_reader: no [display] found")
        else:
            hooked += self._hook_menu(getattr(display, 'menu', None))
            hooked += self._hook_lcd(display.lcd_chip)
            hooked += self._hook_draw(display)
        self._init_watch()
        self.reactor.register_timer(self._poll, self.reactor.NOW)
        logging.info("screen_reader: hooked %s", ",".join(hooked))
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
                # printer, so use it to step through the status screen,
                # in the direction that moves through a menu the same way.
                if self.outer in ('up', 'down'):
                    step = 1 if self.outer == 'down' else -1
                    if getattr(menu, '_reverse_navigation', False):
                        step = -step
                    self.pending_step = step
                    return
                self.last_top = None
                if self.last != "menu closed":
                    self.last = "menu closed"
                    self.status_pos = -1
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
            logging.exception("screen_reader: failed to read menu state")
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
                logging.exception("screen_reader: lcd capture failed")
            return ret
        return wrapper

    def _blank_grid(self):
        cols, rows = self.lcd_size
        return [[' '] * cols for _ in range(rows)]

    def _lcd_clear(self, ret):
        self.grid = self._blank_grid()
        self.frame_items = []

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
        if not self._menu_running():
            self.status_items = self._status_items()
            if self.pending_read is not None:
                # the menu just closed: say the first item
                prefix, self.pending_read = self.pending_read, None
                self._step_status(1, prefix)
            if self.pending_step is not None:
                step, self.pending_step = self.pending_step, None
                self._step_status(step)

    def _menu_running(self):
        return self.menu is not None and self.menu.is_running()

    def _screen_text(self):
        return ". ".join(r for r in self.screen if r) or "screen blank"

    # Status screen items. Each [display_data] item is drawn with one
    # display.draw_text() call, so capturing those gives each item's text
    # separately, with its icons still named (~extruder~ 25~degrees~).

    def _hook_draw(self, display):
        orig = getattr(display, 'draw_text', None)
        if not callable(orig):
            return []
        self.display = display

        def wrapper(*args):
            try:
                row, col, text = args[:3]
                self.frame_items.append((row, col, text))
            except Exception:
                logging.exception("screen_reader: draw capture failed")
            return orig(*args)
        display.draw_text = wrapper
        return ['display.draw_text']

    def _item_names(self):
        # Templates are named "display_data <group> <item>:text"
        group = getattr(self.display, 'show_data_group', None)
        names = {}
        for row, col, template in getattr(group, 'data_items', []):
            name = getattr(template, 'name', '').rsplit(':', 1)[0].split()
            if name:
                names[(row, col)] = name[-1]
        return names

    def _status_items(self):
        names = self._item_names()
        items = []
        for row, col, text in self.frame_items:
            name = names.get((row, col))
            words = self._item_words(name, str(text))
            if words:
                items.append((name, words))

        def rank(item):
            if item[0] in STATUS_ORDER:
                return STATUS_ORDER.index(item[0])
            return -1  # not planned for: first
        return sorted(items, key=rank)  # stable, so screen order otherwise

    def _item_words(self, name, text):
        parts = text.split('~')
        # odd parts are icon names
        for i in range(1, len(parts), 2):
            parts[i] = GLYPH_WORDS.get(parts[i], ' %s ' % (parts[i],))
        words = " ".join("".join(parts).split())
        if words and len(parts) == 1 and name in STATUS_LABELS:
            words = "%s %s" % (STATUS_LABELS[name], words)
        return words

    def _step_status(self, step, prefix=""):
        items = self.status_items
        if not items:
            # nothing recognised; read the screen as it is
            self._say(prefix + self._screen_text(), interrupt=True)
            return
        now = self.reactor.monotonic()
        if now > self.last_step + STATUS_RESET:
            self.status_pos = -1
        self.last_step = now
        self.status_pos = max(0, min(len(items) - 1, self.status_pos + step))
        self._say(prefix + items[self.status_pos][1], interrupt=True)

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
            logging.exception("screen_reader: status poll failed")
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

    # Speech queue. Lines wait here; the helper gets one at a time and
    # says "done <id>" when it finishes, which sends the next.

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
        if self.speaking is not None:
            self.speaking = None
            self._send("stop")

    def _speech_pump(self, eventtime):
        try:
            if self.speaking is not None:
                if eventtime < self.speaking_since + SPEECH_TIMEOUT:
                    return self.speaking_since + SPEECH_TIMEOUT
                logging.warning("screen_reader: speech helper stuck,"
                                " restarting it")
                self._close_helper()
            if not self.queue:
                return self.reactor.NEVER
            if not self._start_helper(eventtime):
                return self.helper_started + HELPER_RETRY
            key, text = self.queue.pop(0)
            self.line_id += 1
            text = " ".join(text.split()).encode('utf-8')[:MAX_LINE_BYTES]
            text = text.decode('utf-8', 'ignore')
            if self._send("say %d %s" % (self.line_id, text)):
                self.speaking, self.speaking_since = self.line_id, eventtime
                return eventtime + SPEECH_TIMEOUT
        except Exception:
            # never let speaking break the printer
            logging.exception("screen_reader: speech failed")
        return self.reactor.NEVER

    # The helper process

    def _start_helper(self, eventtime):
        if self.helper is not None:
            if self.helper.poll() is None:
                return True
            self._close_helper()
        if (self.helper_started is not None
                and eventtime < self.helper_started + HELPER_RETRY):
            return False
        self.helper_started = eventtime
        try:
            self.helper = subprocess.Popen(
                [sys.executable, HELPER], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, start_new_session=True)
        except Exception:
            logging.exception("screen_reader: can't start %s", HELPER)
            self.helper = None
            return False
        for f in (self.helper.stdin, self.helper.stdout):
            flags = fcntl.fcntl(f.fileno(), fcntl.F_GETFL)
            fcntl.fcntl(f.fileno(), fcntl.F_SETFL, flags | os.O_NONBLOCK)
        self.helper_buf = b''
        self.helper_handle = self.reactor.register_fd(
            self.helper.stdout.fileno(), self._helper_read)
        return True

    def _send(self, line):
        if self.helper is None:
            return False
        try:
            os.write(self.helper.stdin.fileno(),
                     (line + '\n').encode('utf-8'))
            return True
        except OSError as e:
            # gone, or so far behind its pipe is full
            logging.warning("screen_reader: speech helper: %s", e)
            self._close_helper()
            return False

    def _helper_read(self, eventtime):
        try:
            data = os.read(self.helper.stdout.fileno(), 4096)
        except BlockingIOError:
            return
        except OSError:
            data = b''
        if not data:
            logging.warning("screen_reader: speech helper exited")
            self._close_helper()
            return
        self.helper_buf += data
        while b'\n' in self.helper_buf:
            line, self.helper_buf = self.helper_buf.split(b'\n', 1)
            if line == b"done %d" % (self.speaking or 0,):
                self.speaking = None
                self.reactor.update_timer(self.speech_timer,
                                          self.reactor.NOW)

    def _close_helper(self):
        helper, self.helper = self.helper, None
        if self.helper_handle is not None:
            self.reactor.unregister_fd(self.helper_handle)
            self.helper_handle = None
        if self.speaking is not None:
            self.speaking = None
            self.reactor.update_timer(self.speech_timer, self.reactor.NOW)
        if helper is None:
            return
        # Closing its input stops the speech and ends it; wait, so a new
        # helper can never talk over this one.
        try:
            helper.stdin.close()
        except OSError:
            pass
        try:
            helper.wait(1.5)
        except subprocess.TimeoutExpired:
            # its own process group, so this gets espeak-ng too
            os.killpg(helper.pid, signal.SIGKILL)
            helper.wait()
        helper.stdout.close()


def load_config(config):
    return ScreenReader(config)
