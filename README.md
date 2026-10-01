# 3dspeex

3dspeex makes a Klipper 3D printer talk. It is a screen reader for the
printer's own display: it reads the menu aloud as you turn the knob,
reads the status screen, and announces heating, print progress, finished
prints, and errors.

Speech plays through a speaker connected to the printer, such as a USB
speaker. Everything runs on the printer itself.

Developed on a Sovol SV08. Other Klipper printers with a screen and
control knob should work but haven't been tested; reports are welcome.
Touchscreen-only printers are not supported yet.

## Usage

- Turning or clicking the knob in the menu speaks the selected item. The
  menu name is included when you enter a menu.
- With the menu closed, turn the knob to step through the status screen
  one item at a time, most interesting first: the print status or
  message, progress, print time, then temperatures, fan and speed.
  Turning the way that moves down a menu goes to the next item; the
  other way goes back. Going back from the first item reads the whole
  screen. After a minute without turning, it starts again
  from the top. Items the reader doesn't know about, like ones a printer
  maker added, come first. The order is `STATUS_ORDER` in
  `screen_reader.py`.
- Closing the menu says the first status item; turning then continues
  from there. `ANNOUNCE_SCREEN` reads the whole status screen.
- Knob speech (menu and status items) interrupts whatever is being said.
  Other announcements are queued.
- The **Screen reader** menu, at the end of the main menu, sets the
  speech rate, volume and voice, how often print progress is said, and
  whether info lines are read. Each change is heard right away and is
  saved (see Settings menu).

Abbreviated menu labels are expanded for speech, e.g. `Ex0:220 ( 215)` is
read as "nozzle target 220, now 215°" and `Load Fil. fast` as "Load
filament fast". The display is not changed. See `SPEECH_RULES` in
`screen_reader.py`.

Events announced:

- M117 display messages
- print started, paused, resumed, complete, cancelled, error
- print progress (every 10% by default)
- heater target changes, and heaters reaching target
- `!!` errors, `RESPOND`/`M118` output, and shutdown reasons

## Requirements

- Klipper with a `[display]` menu
- espeak-ng and alsa-utils (`amixer` sets the volume)
- a speaker

## Installation

On the printer, as the user Klipper runs as:

    git clone https://github.com/daiverd/3dspeex.git ~/3dspeex
    cd ~/3dspeex
    ./install.sh

The script installs espeak-ng and alsa-utils (via apt) if needed,
symlinks `screen_reader.py` into `~/klipper/klippy/extras/`, creates
`~/printer_data/config/screen_reader.cfg` and includes it from `printer.cfg`
(a backup of `printer.cfg` is made), symlinks `screen_reader_menu.cfg`
into the config folder and includes it from `screen_reader.cfg`, adds the Klipper user to the `audio`
group, and restarts Klipper. It will not restart Klipper while a print is
running.

Options:

    --usb-audio    make a USB sound card the default ALSA device (see below)
    --no-restart   don't restart Klipper
    --uninstall    remove the symlink and the include

For non-standard locations, set `KLIPPER_DIR`, `CONFIG_DIR`, or
`KLIPPER_SERVICE` (e.g. `klipper-1` for KIAUH multi-instance setups).

To update, pull and re-run the installer with the options you used
before. It keeps your `screen_reader.cfg`, and reinstalls the
`--usb-audio` files in case they changed:

    cd ~/3dspeex && git pull && ./install.sh --usb-audio

(leave out `--usb-audio` if you didn't use it).

### Manual installation

    ln -s ~/3dspeex/screen_reader.py ~/klipper/klippy/extras/

and add a `[screen_reader]` section to `printer.cfg`. For the settings
menu, also link `screen_reader_menu.cfg` into the config folder and add
`[include screen_reader_menu.cfg]`. Link rather than
copy: `screen_reader.py` finds `speech_helper.py` next to its real
location.

## Configuration

    [screen_reader]
    #progress_step: 10
    #   Announce print progress every N percent. 0 disables.
    #announce_info: False
    #   Also speak "//" info lines. These are frequent during QGL and
    #   bed mesh calibration.
    #speech_rate: 170
    #   Words per minute, 80 to 500.
    #voice:
    #   An espeak-ng voice, e.g. en-us or en-gb. The default is
    #   espeak-ng's. List them with: espeak-ng --voices
    #voices:
    #   Voices to choose from in the Screen reader menu, separated by
    #   commas, e.g. en-us, en-gb, en-us+f3 (+f3 is a variant; see
    #   espeak-ng --voices=variant). With fewer than two, the menu has no
    #   Voice item.
    #volume:
    #   The sound card's volume, 10 to 100 percent. If unset, the card's
    #   volume is left as it is. Values under 10 are raised to 10, so
    #   speech can't be turned all the way off. (Before the settings
    #   menu this was espeak-ng's volume, 0 to 200; values over 100 are
    #   now read as 100.)
    #mixer_device: default
    #   The ALSA device whose volume is set, as for amixer -D. "default"
    #   is the card /etc/asound.conf names (the USB card, with
    #   --usb-audio), or the first card.
    #mixer_control:
    #   The volume control on that device, as listed by amixer
    #   scontrols, e.g. Headset, or Speaker,1 for the second control of
    #   that name. If unset, the first of Master, PCM, Speaker,
    #   Headphone and Headset is used, else the first playback control
    #   that isn't an input (Sidetone, Mic, Capture...). klippy.log
    #   says which control was picked.

## G-Code commands

`ANNOUNCE MSG=<text>`: Speak the given text.

`ANNOUNCE_SCREEN`: Speak the current contents of the display.

`SCREEN_READER_SET [RATE=<wpm>] [VOICE=<name>] [VOLUME=<percent>]
[PROGRESS_STEP=<percent>] [ANNOUNCE_INFO=0|1] [RESET=1]`: Change
settings now and save them (see Settings menu). `RESET=1` deletes the
saved settings and goes back to the ones in `screen_reader.cfg`. With no
parameters, reports the current settings.

## Settings menu

`screen_reader_menu.cfg` adds a **Screen reader** menu with Rate,
Volume, Voice, Progress (how often print progress is said: off, or
every 1%, 5%, 10% or 25%), Info lines, and Reset to config. Turning the knob
while editing applies each change as you go, so you hear the new rate or
voice saying its own value.

Changes are saved to `screen_reader_settings.json` next to `printer.cfg`
and are used instead of `screen_reader.cfg` from then on, even if you
edit `screen_reader.cfg` later. Choose Reset to config (or run
`SCREEN_READER_SET RESET=1`) to go back to `screen_reader.cfg`.

Volume is the sound card's own volume control (ALSA), not espeak-ng's,
so the top of the range is as loud as the card goes. It can't go below
10%. If the card has no volume control 3dspeex can find, the menu says
"Volume: not available"; set `mixer_device` or `mixer_control` (see
Configuration). While no volume is set, in the config or from the
menu, the card's volume is not changed.

To hide the menu, put `#` in front of `[include screen_reader_menu.cfg]`
in `screen_reader.cfg`. To change it, copy it to another name and
include that instead: the installed file is a link into the repo.

## USB audio

The SV08 host board has onboard and HDMI audio outputs, so a USB speaker
is not the default ALSA device. `install.sh --usb-audio` installs two
files from `audio/`:

- `/etc/udev/rules.d/85-usb-audio-default.rules` sets the ALSA ID of any
  USB sound card to `usbaudio`
- `/etc/asound.conf` makes `usbaudio` the default device, through
  `dmix` so other programs can play sound at the same time

After installing, replug the USB device and check that it is listed as
`usbaudio` in `/proc/asound/cards`.

If no USB audio device is connected, playback fails rather than falling
back to the onboard outputs. With two USB devices, only the first one
connected gets the `usbaudio` name. This setup assumes plain ALSA; it has
no effect if PulseAudio or PipeWire is managing audio.

## Voice

Set the speed, voice and volume from the Screen reader menu, or in
`screen_reader.cfg` (see Configuration) and restart Klipper.

Klipper starts `speech_helper.py` once and sends it each line to say.
It says one line at a time: a new line stops the current one, and waits
for it to exit, before starting. To use another speech engine, replace
the helper with a program that follows the protocol in its header.

## kcon

`kcon` is a line-based console for Klipper's pseudo-terminal
(`~/printer_data/comms/klippy.serial`), useful with a screen reader over
SSH. See `kcon --help`.

## Troubleshooting

No speech: check that the Klipper user can play audio outside a login
session:

    sudo systemd-run --uid=sovol --pty --quiet espeak-ng hello

If this fails, add the user to the `audio` group, or see USB audio above.
If it works but the printer is silent, look for `screen_reader: speech
helper` lines in `klippy.log`; the helper is restarted every 10 seconds
while it keeps failing.

Klipper fails to start: check `klippy.log`. Make sure there is only one
`[screen_reader]` section and that it has no unknown options.

`git pull` refuses to update: you have edited a file in the repo, such
as `STATUS_ORDER` in `screen_reader.py`. Save your change with `git stash`, pull, then
`git stash pop` to put it back.

Last letter of each word cut off: some espeak-ng versions drop the final
byte of stdin if it is not a newline. `speech_helper.py` appends one;
keep this if you replace it.

No volume control, or the wrong one: run `amixer -D default
scontents` (with your `mixer_device`) to see the card's controls, and set
`mixer_control` to the one for the speaker. `screen_reader: speech
helper` lines in `klippy.log` show amixer's errors.

During timelapse rendering, the `TIMELAPSE_RENDER` macro's M117 spinner is
spoken repeatedly.

## Tests

    python3 tests/test_settings.py
    python3 tests/test_speakable.py
    python3 tests/test_speech_helper.py
    python3 tests/test_speech_queue.py
    python3 tests/test_status_steps.py

## License

GNU GPLv3, the same as Klipper. See [LICENSE](LICENSE).
