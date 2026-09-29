# 3dspeex

Speech output for Klipper printers with an LCD and rotary knob. It reads
the menu aloud as you navigate, reads the status screen on request, and
announces printer events such as heaters reaching temperature, print
progress, M117 messages, and errors.

Speech is done with espeak-ng on the Klipper host.

Developed on a Sovol SV08 (stock Sovol Klipper). It uses only standard
Klipper interfaces, so other printers with a Klipper `[display]` menu
should work, but none have been tested yet. Reports are welcome.
Touchscreen-only setups (KlipperScreen etc.) are not supported.

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
`3dspeex.py`.

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
symlinks `3dspeex.py` into `~/klipper/klippy/extras/`, creates
`~/printer_data/config/3dspeex.cfg` and includes it from `printer.cfg`
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

    ln -s ~/3dspeex/3dspeex.py ~/klipper/klippy/extras/

and add a `[3dspeex]` section to `printer.cfg`.

## Configuration

    [3dspeex]
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

Speech goes through `speak()` in `3dspeex.py`. To change speed or
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
`[3dspeex]` section and that it has no unknown options.

Last letter of each word cut off: some espeak-ng versions drop the final
byte of stdin if it is not a newline. `speak()` appends one; keep this if
you replace it.

During timelapse rendering, the `TIMELAPSE_RENDER` macro's M117 spinner is
spoken repeatedly.

## Tests

    python3 tests/test_speakable.py

## License

GNU GPLv3, the same as Klipper. See [LICENSE](LICENSE).
