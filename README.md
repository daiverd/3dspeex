# 3dspeex

A screen reader for 3D printers with a Klipper LCD and knob. It speaks the
menu as you move through it, reads out the status screen on request, and
announces what the printer is doing: heaters reaching temperature, print
progress, messages, and errors.

Built and used on a Sovol SV08, but written for Klipper in general: see
[Compatibility](#compatibility).

## What you hear

**In the menu:** every knob turn, click, and back says where you are.
Entering a menu names it; turning within it names just the item.

Menu names written for a small screen are reworded for listening; the
screen itself is unchanged:

| On screen | Spoken |
|---|---|
| `Ex0:220 ( 215)` | nozzle target 220, now 215° |
| `Ex0:  0 (  23)` | nozzle off, now 23° |
| `Bed: 60 (  58)` | bed target 60, now 58° |
| `Move E:+005.0` | Move extruder: +5.0 |
| `Ex0 fan` / `Ex1 fan` | extruder fan / extruder 2 fan |
| `Load Fil. fast` | Load filament fast |
| `Quad Gantry Lvl` / `Restart FW` | Quad Gantry level / Restart firmware |
| `Move 10mm` / `Home X/Y` | Move 10 millimeters / Home X and Y |
| `Offset Z:0.125` / `Calibrate Zoffset` | Offset Z: 0.125 / Calibrate Z offset |
| `Test Z: -` / `Test Z: +.01` | Test Z: minus / Test Z: +0.01 |

The rules are in `SPEECH_RULES` in `menu_announce.py`. They only touch
menu names, leave SD card file names alone, and only match whole words
or whole items, so they can't change things that merely look similar.
`python3 tests/test_speakable.py` checks them against every name in
mainline Klipper's and Sovol's menus plus lookalikes that must not
change; add cases there when adding a rule.

```
Main: Back          (menu opened)
Prepare             (turned)
Prepare: Back       (clicked into Prepare)
Speed: 100%, editing
Speed: 105%, done
menu closed. nozzle 25° fan 0%. bed 24° speed 100%. 0% 00:00. Ready
```

**With the menu closed, turn the knob to hear the status screen.** The
turn does nothing else on the printer, so it's free to use as "read me
the screen". The screen is also read out whenever the menu closes.

**As things happen:**

- messages shown on the screen (`M117`), like "Nozzle heating..."
- print started, paused, resumed, complete, cancelled, or failed
- progress every 10%, with the layer number when the slicer provides it
- "nozzle heating to 220°", "nozzle at 220°", "bed off, at 58°"
- errors, like "error: Must home axis first"
- `RESPOND` and `M118` messages from macros
- the reason for a Klipper shutdown

Menu speech and screen reads cut off whatever is being said, like a screen
reader, so fast scrolling only speaks where you stop. Events wait their
turn instead, and a knob turn never throws away a waiting event. A newer
event of the same kind (another message, the next progress step) replaces
one that hasn't been spoken yet.

## Requirements

- Klipper with an LCD menu (`[display]` in `printer.cfg`)
- `espeak-ng` and `alsa-utils` (the installer adds them if missing, using
  `apt`, so on a non-Debian host install them yourself first)
- a speaker. On the SV08 a USB speaker or headset works well; see
  [USB speaker setup](#usb-speaker-setup).

## Compatibility

3dspeex only uses parts of Klipper that are in mainline, not anything Sovol
added: the standard LCD menu, the display drivers, and the usual status
objects (heaters, `print_stats`, `display_status`). Everything it hooks has
been checked against current mainline Klipper's source.

| Setup | Status |
|---|---|
| Sovol SV08, stock Sovol Klipper, 128×64 knob screen | In daily use |
| Mainline Klipper, 12864-style screens (`uc1701`, `st7920`, `ssd1306`, `sh1106`) | Should work; untested |
| Mainline Klipper, 20×4 character LCDs (`hd44780`) | Should work; untested |
| Kalico (formerly Danger Klipper) and other close forks | Probably; untested |
| Touchscreen-only printers (KlipperScreen, Creality K1 screen, ...) | No: there's no Klipper menu to read |

Printer-specific details that are handled:

- **Screen size** comes from the display driver, so 20-column screens are
  read in full.
- **Custom screen layouts** work, because "read the screen" reads what's
  actually drawn. Custom icons are read by their name.
- **Menus from any config** (your own `[menu ...]` sections, or a vendor's)
  are read the same way, by the names shown on screen.
- **Reversed knob direction** doesn't matter; speech follows the selection.
- **Install paths:** the installer assumes the usual KIAUH layout
  (`~/klipper`, `~/printer_data/config`, a `klipper` service). Other setups
  can override these, below.

If you try it on another printer, an issue saying whether it worked would
help.

## Install

On the printer, logged in as the user Klipper runs as (`sovol` on the SV08):

```bash
git clone https://github.com/daiverd/3dspeex.git ~/3dspeex
cd ~/3dspeex
./install.sh --usb-audio    # leave off --usb-audio if sound already works
```

The installer:

1. installs `espeak-ng` and `alsa-utils` if they're missing
2. links `menu_announce.py` into `~/klipper/klippy/extras/`, so a
   `git pull` updates it, and hides the link from Klipper's git status
3. writes `~/printer_data/config/3dspeex.cfg` and adds
   `[include 3dspeex.cfg]` to the top of `printer.cfg` (a timestamped
   backup of `printer.cfg` is kept). If `printer.cfg` already has a
   `[menu_announce]` section, it's left as is.
4. adds Klipper's service user to the `audio` group
5. with `--usb-audio`, sets up a USB sound card as the default (below)
6. says "3D speex installed", then restarts Klipper. It won't restart
   during a print; use `--no-restart` to skip the restart entirely.

If your Klipper or config lives elsewhere, or you run several Klipper
instances with KIAUH:

```bash
KLIPPER_DIR=/path/to/klipper CONFIG_DIR=/path/to/config ./install.sh
KLIPPER_SERVICE=klipper-1 CONFIG_DIR=~/printer_1_data/config ./install.sh
```

**Update:** `cd ~/3dspeex && git pull && sudo systemctl restart klipper`

**Uninstall:** `./install.sh --uninstall` removes the link and the include
line, and keeps your `3dspeex.cfg` settings as a timestamped copy. USB
audio setup is left in place.

## USB speaker setup

The SV08's main board has its own sound outputs (the H616 codec and HDMI),
so ALSA's default device usually isn't the USB speaker you plugged in, and
the card numbers can change between boots. `--usb-audio` fixes that with
plain ALSA, no PulseAudio or PipeWire:

- **`/etc/udev/rules.d/85-usb-audio-default.rules`** renames any sound card
  on the USB bus to `usbaudio`. Onboard and HDMI audio are never touched.
- **`/etc/asound.conf`** makes `usbaudio` the default device, with
  `type plug` converting sample rate and channels, so mono speech plays on
  stereo devices. An existing `asound.conf` is backed up first.

Check it with:

```bash
cat /proc/asound/cards      # the USB card should show as [usbaudio]
speaker-test -c 1 -t wav    # plays through the default device
```

If the card doesn't show as `usbaudio`, unplug and replug it.

Things to know:

- **With no USB audio plugged in, speech fails silently** rather than
  falling back to the onboard outputs. On a printer that's usually what you
  want: no speech going to an unplugged HDMI port.
- **With two USB audio devices,** only the first gets the `usbaudio` name
  (the kernel won't give two cards the same ID), so the first one plugged
  in is the default.
- **Hotplug works:** unplug one speaker and plug in another, and the new
  one becomes the default.
- **This is for plain ALSA.** If your image runs PulseAudio or PipeWire
  (`pactl info` says so), they choose the default device themselves. The
  stock SV08 image doesn't appear to run either, but check. The installer
  warns if it finds one.

The two files are in [`audio/`](audio/) if you'd rather install them by hand.

## Configuration

Settings go in the `[menu_announce]` section (in `3dspeex.cfg` after a
normal install). Both are optional:

```ini
[menu_announce]
progress_step: 10     # say print progress every N percent (0 = never)
announce_info: False  # also say "//" info lines (chatty during QGL/mesh)
```

## G-code commands

| Command | What it does |
|---|---|
| `ANNOUNCE MSG="text"` | Say a line, waiting its turn like other events |
| `ANNOUNCE_SCREEN` | Read out the screen now |

For example, in your print-end macro:

```ini
ANNOUNCE MSG="Print done. Bed cooling."
```

## Changing the voice

All speech goes through `speak()` near the top of `menu_announce.py`.

- **Speed or voice:** edit `SPEAK_CMD`, for example
  `['espeak-ng', '-s', '150', '-v', 'en-us', '--stdin']`.
- **A different speech engine or output:** replace `speak()`. It gets the
  text, must return straight away, and returns something with `poll()`
  (None while still talking) and `terminate()`, like a
  `subprocess.Popen`, or `None` when there's nothing to wait for.

Restart Klipper after editing.

## kcon

`kcon` is a small line-based console for Klipper's serial port
(`~/printer_data/comms/klippy.serial`), handy over SSH with a screen
reader: type G-code, read plain-text replies, with line editing and
history. `:temps some|all|none` controls how many temperature lines are
shown while heating, and `:quit` exits. Only one program can use the port
at a time.

## Troubleshooting

**No speech at all.** Check that Klipper's user can play sound without a
login session, which is how the service runs:

```bash
sudo systemd-run --uid=sovol --pty --quiet espeak-ng hello
```

If that's silent but `espeak-ng hello` works when you're logged in, the
user probably isn't in the `audio` group (`id sovol`; the installer adds
it, and it takes effect when Klipper restarts), or your login uses
PulseAudio/PipeWire and the service can't reach it. See
[USB speaker setup](#usb-speaker-setup).

**Klipper won't start after installing.** Check `klippy.log`. The usual
cause is `[menu_announce]` appearing twice, or an old setup's `host:` /
`port:` options under `[menu_announce]`; delete those lines.

**The last letter of each word is cut off** ("filamen", "contro"). Some
`espeak-ng` versions drop the last byte of input when it isn't a newline.
`speak()` adds a newline for this; keep it if you replace `speak()`.

**Speech says "Rendering dash, Rendering pipe…" during timelapse renders.**
The timelapse `TIMELAPSE_RENDER` macro animates a spinner with `M117`,
and each frame is a new message. A known rough edge.

## How it works

`menu_announce.py` is a Klipper "extra" module. At startup it:

- wraps the menu's navigation methods (`press`, `up`, `down`, `back`, ...)
  to speak the new position after each action. It doesn't hook
  `key_event`, because the knob handler keeps its own reference to the
  original method.
- wraps the LCD driver's `clear` / `write_text` / `write_glyph` / `flush`
  to keep a text copy of every frame, with icons turned into words. That's
  what "read the screen" reads, so it follows whatever layout the display
  uses.
- checks messages, print state, progress, and heaters once a second.
- listens to Klipper's G-code output for errors and echo lines.

Speech runs in separate `espeak-ng` processes checked from Klipper's event
loop, so it never blocks the printer, and every hook is wrapped so a
failure is only logged.

## License

GPLv3, the same as Klipper. See [LICENSE](LICENSE).
