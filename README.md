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
- With the menu closed, turn the knob to hear the status screen. It is
  also read when the menu closes.
- Menu speech interrupts whatever is being said. Other announcements are
  queued.

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
- espeak-ng and alsa-utils
- a speaker

## Installation

On the printer, as the user Klipper runs as:

    git clone https://github.com/daiverd/3dspeex.git ~/3dspeex
    cd ~/3dspeex
    ./install.sh

The script installs espeak-ng and alsa-utils (via apt) if needed,
symlinks `screen_reader.py` into `~/klipper/klippy/extras/`, creates
`~/printer_data/config/screen_reader.cfg` and includes it from `printer.cfg`
(a backup of `printer.cfg` is made), adds the Klipper user to the `audio`
group, and restarts Klipper. It will not restart Klipper while a print is
running.

Options:

    --usb-audio    make a USB sound card the default ALSA device (see below)
    --no-restart   don't restart Klipper
    --uninstall    remove the symlink and the include

For non-standard locations, set `KLIPPER_DIR`, `CONFIG_DIR`, or
`KLIPPER_SERVICE` (e.g. `klipper-1` for KIAUH multi-instance setups).

To update:

    cd ~/3dspeex && git pull && sudo systemctl restart klipper

### Manual installation

    ln -s ~/3dspeex/screen_reader.py ~/klipper/klippy/extras/

and add a `[screen_reader]` section to `printer.cfg`.

## Configuration

    [screen_reader]
    #progress_step: 10
    #   Announce print progress every N percent. 0 disables.
    #announce_info: False
    #   Also speak "//" info lines. These are frequent during QGL and
    #   bed mesh calibration.

## G-Code commands

`ANNOUNCE MSG=<text>`: Speak the given text.

`ANNOUNCE_SCREEN`: Speak the current contents of the display.

## USB audio

The SV08 host board has onboard and HDMI audio outputs, so a USB speaker
is not the default ALSA device. `install.sh --usb-audio` installs two
files from `audio/`:

- `/etc/udev/rules.d/85-usb-audio-default.rules` sets the ALSA ID of any
  USB sound card to `usbaudio`
- `/etc/asound.conf` makes `usbaudio` the default device

After installing, replug the USB device and check that it is listed as
`usbaudio` in `/proc/asound/cards`.

If no USB audio device is connected, playback fails rather than falling
back to the onboard outputs. With two USB devices, only the first one
connected gets the `usbaudio` name. This setup assumes plain ALSA; it has
no effect if PulseAudio or PipeWire is managing audio.

## Voice

Speech goes through `speak()` in `screen_reader.py`. To change speed or
voice, edit `SPEAK_CMD`. To use another speech engine, replace `speak()`;
see its docstring.

## kcon

`kcon` is a line-based console for Klipper's pseudo-terminal
(`~/printer_data/comms/klippy.serial`), useful with a screen reader over
SSH. See `kcon --help`.

## Troubleshooting

No speech: check that the Klipper user can play audio outside a login
session:

    sudo systemd-run --uid=sovol --pty --quiet espeak-ng hello

If this fails, add the user to the `audio` group, or see USB audio above.

Klipper fails to start: check `klippy.log`. Make sure there is only one
`[screen_reader]` section and that it has no unknown options.

Last letter of each word cut off: some espeak-ng versions drop the final
byte of stdin if it is not a newline. `speak()` appends one; keep this if
you replace it.

During timelapse rendering, the `TIMELAPSE_RENDER` macro's M117 spinner is
spoken repeatedly.

## Tests

    python3 tests/test_speakable.py

## License

GNU GPLv3, the same as Klipper. See [LICENSE](LICENSE).
