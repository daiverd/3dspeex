#!/bin/bash
# Part of 3dspeex: https://github.com/daiverd/3dspeex
# Copyright (C) 2026  daiverd <david@rustytelephone.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# 3dspeex installer. Run on the printer, as the user Klipper runs as:
#   ./install.sh               install / update
#   ./install.sh --usb-audio   also make a USB sound card the default
#   ./install.sh --uninstall   remove 3dspeex (audio setup is left alone)
# Add --no-restart to skip restarting Klipper.
# Paths can be overridden: KLIPPER_DIR=... CONFIG_DIR=... ./install.sh
# and the service name (KIAUH multi-instance): KLIPPER_SERVICE=klipper-1
# Klipper is only restarted once Moonraker says no print is running:
# MOONRAKER_URL=http://localhost:7125 (the default) says where to ask.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
KLIPPER_DIR="${KLIPPER_DIR:-$HOME/klipper}"
CONFIG_DIR="${CONFIG_DIR:-$HOME/printer_data/config}"
KLIPPER_SERVICE="${KLIPPER_SERVICE:-klipper}"
MOONRAKER_URL="${MOONRAKER_URL:-http://localhost:7125}"
EXTRA="$KLIPPER_DIR/klippy/extras/screen_reader.py"
PRINTER_CFG="$CONFIG_DIR/printer.cfg"
OUR_CFG="$CONFIG_DIR/screen_reader.cfg"
INCLUDE_LINE="[include screen_reader.cfg]"
MENU_CFG="$CONFIG_DIR/screen_reader_menu.cfg"
MENU_INCLUDE="[include screen_reader_menu.cfg]"
STAMP="$(date +%Y%m%d-%H%M%S)"

usb_audio=0 restart=1 uninstall=0
for arg in "$@"; do
    case "$arg" in
        --usb-audio) usb_audio=1 ;;
        --no-restart) restart=0 ;;
        --uninstall) uninstall=1 ;;
        -h|--help) sed -n '/^# 3dspeex installer/,/^# and the service/p' "$0" | cut -c3-; exit 0 ;;
        *) echo "unknown option: $arg (try --help)" >&2; exit 1 ;;
    esac
done

say() { echo "==> $*"; }
warn() { echo "!!  $*" >&2; }

have_klipper_service() {
    systemctl cat "$KLIPPER_SERVICE.service" >/dev/null 2>&1
}

# Files that configure [screen_reader] (only the ones Klipper reads here)
configured_in() {
    grep -ls '^\[screen_reader\]' "$PRINTER_CFG" "$OUR_CFG" || true
}

# The print state from Moonraker (standby, printing, paused...), or
# nothing if it can't be asked
print_state() {
    curl -s --max-time 3 \
        "$MOONRAKER_URL/printer/objects/query?print_stats=state" |
        python3 -c 'import json,sys
print(json.load(sys.stdin)["result"]["status"]["print_stats"]["state"])' \
        2>/dev/null || true
}

# Never restart Klipper in the middle of a print: only when Moonraker
# says no print is running, not when it can't be asked.
restart_klipper() {
    local how="sudo systemctl restart $KLIPPER_SERVICE" state
    if [ "$restart" = 0 ] || ! have_klipper_service; then
        say "Restart Klipper yourself to apply: $how"
        return
    fi
    state="$(print_state)"
    if [ -z "$state" ]; then
        warn "Couldn't ask Moonraker ($MOONRAKER_URL) whether a print is" \
             "running, so not restarting Klipper. When the printer is" \
             "idle, restart it yourself: $how"
    elif [ "$state" = printing ] || [ "$state" = paused ]; then
        warn "A print is ${state/printing/running}; not restarting Klipper. When it's" \
             "done, restart it yourself: $how"
    else
        say "Restarting Klipper (print state: $state)"
        sudo systemctl restart "$KLIPPER_SERVICE"
    fi
}

[ -d "$KLIPPER_DIR/klippy/extras" ] ||
    { warn "No Klipper at $KLIPPER_DIR (set KLIPPER_DIR)"; exit 1; }
[ -f "$PRINTER_CFG" ] ||
    { warn "No printer.cfg in $CONFIG_DIR (set CONFIG_DIR)"; exit 1; }

if [ "$uninstall" = 1 ]; then
    if [ -L "$EXTRA" ]; then
        say "Removing $EXTRA"
        rm "$EXTRA"
    fi
    if [ -L "$MENU_CFG" ]; then
        say "Removing $MENU_CFG"
        rm "$MENU_CFG"
    fi
    if grep -qxF -e "$INCLUDE_LINE" -e "$MENU_INCLUDE" "$PRINTER_CFG"; then
        say "Removing 3dspeex includes from printer.cfg (backup: printer.cfg.$STAMP)"
        cp "$PRINTER_CFG" "$PRINTER_CFG.$STAMP"
        grep -vxF -e "$INCLUDE_LINE" -e "$MENU_INCLUDE" \
            "$PRINTER_CFG.$STAMP" > "$PRINTER_CFG"
    fi
    if [ -f "$OUR_CFG" ]; then
        say "Keeping your settings in $OUR_CFG.$STAMP"
        mv "$OUR_CFG" "$OUR_CFG.$STAMP"
    fi
    saved="$CONFIG_DIR/screen_reader_settings.json"
    if [ -f "$saved" ]; then
        say "Keeping settings changed from the menu in $saved.$STAMP"
        mv "$saved" "$saved.$STAMP"
    fi
    if [ -n "$(configured_in)" ]; then
        warn "printer.cfg still has a [screen_reader] section; remove it" \
             "or Klipper will fail to start."
    fi
    restart_klipper
    exit 0
fi

# 1. Speech packages
missing=()
command -v espeak-ng >/dev/null || missing+=(espeak-ng)
command -v aplay >/dev/null || missing+=(alsa-utils)
if [ "${#missing[@]}" -gt 0 ]; then
    say "Installing ${missing[*]}"
    sudo apt-get install -y "${missing[@]}"
fi

# 2. Link the Klipper module, so a git pull here updates it
if [ -e "$EXTRA" ] && [ ! -L "$EXTRA" ]; then
    say "Moving existing $EXTRA to $EXTRA.$STAMP"
    mv "$EXTRA" "$EXTRA.$STAMP"
fi
say "Linking $EXTRA -> $REPO_DIR/screen_reader.py"
ln -sfn "$REPO_DIR/screen_reader.py" "$EXTRA"
# Keep Klipper's git checkout clean so Moonraker doesn't call it "dirty"
exclude="$KLIPPER_DIR/.git/info/exclude"
if [ -d "$KLIPPER_DIR/.git" ] &&
        ! grep -qxF "klippy/extras/screen_reader.py" "$exclude" 2>/dev/null; then
    mkdir -p "$(dirname "$exclude")"
    echo "klippy/extras/screen_reader.py" >> "$exclude"
fi

# 3. Config: a separate screen_reader.cfg, included from printer.cfg. Adding
#    the include at the top keeps clear of the SAVE_CONFIG block at the end.
if [ -n "$(configured_in)" ]; then
    say "[screen_reader] already configured in $(configured_in | xargs -n1 basename)"
else
    say "Writing $OUR_CFG"
    cat > "$OUR_CFG" <<'EOF'
# 3dspeex - spoken screen reader for the printer's LCD
# https://github.com/daiverd/3dspeex
[screen_reader]
# progress_step: 10     # say print progress every N percent (0 = off)
# announce_info: False  # also say "//" info lines (chatty)
# speech_rate: 170      # words per minute
# voice: en-us          # an espeak-ng voice (espeak-ng --voices)
# voices: en-us, en-gb, en-us+f3  # voices to choose from in the menu
# volume: 70            # sound card volume, 10 to 100 percent
# mixer_device: default # ALSA device whose volume to set
# mixer_control:        # its volume control (amixer scontrols); found
#                       # by itself on most cards
# The "Screen reader" menu on the display; put # in front to hide it.
[include screen_reader_menu.cfg]
EOF
    say "Adding $INCLUDE_LINE to printer.cfg (backup: printer.cfg.$STAMP)"
    cp "$PRINTER_CFG" "$PRINTER_CFG.$STAMP"
    { echo "$INCLUDE_LINE"; cat "$PRINTER_CFG.$STAMP"; } > "$PRINTER_CFG"
fi

# 4. The "Screen reader" settings menu, linked like the module so it
#    updates with git pull. Older installs get the include added.
if [ -e "$MENU_CFG" ] && [ ! -L "$MENU_CFG" ]; then
    say "Moving existing $MENU_CFG to $MENU_CFG.$STAMP"
    mv "$MENU_CFG" "$MENU_CFG.$STAMP"
fi
ln -sfn "$REPO_DIR/screen_reader_menu.cfg" "$MENU_CFG"
# (a commented-out include counts: that hides the menu on purpose)
if ! grep -qF "$MENU_INCLUDE" "$PRINTER_CFG" "$OUR_CFG" 2>/dev/null; then
    if [ -f "$OUR_CFG" ]; then
        say "Adding the Screen reader menu to $(basename "$OUR_CFG")"
        { echo
          echo '# The "Screen reader" menu on the display; put # in front to hide it.'
          echo "$MENU_INCLUDE"; } >> "$OUR_CFG"
    else
        say "Adding $MENU_INCLUDE to printer.cfg (backup: printer.cfg.$STAMP)"
        cp "$PRINTER_CFG" "$PRINTER_CFG.$STAMP"
        { echo "$MENU_INCLUDE"; cat "$PRINTER_CFG.$STAMP"; } > "$PRINTER_CFG"
    fi
fi

# 5. Let the Klipper service's user reach the sound card
if have_klipper_service; then
    kuser="$(systemctl show -p User --value "$KLIPPER_SERVICE.service")"
    kuser="${kuser:-root}"
    if [ "$kuser" != root ] && ! id -nG "$kuser" | grep -qw audio; then
        say "Adding $kuser to the audio group"
        sudo usermod -aG audio "$kuser"
    fi
fi

# 6. Optional: always use a USB sound card
if [ "$usb_audio" = 1 ]; then
    if command -v pactl >/dev/null && pactl info >/dev/null 2>&1; then
        warn "PulseAudio/PipeWire is running; it manages the default" \
             "device itself, so the ALSA setup below may be ignored."
    fi
    say "Installing USB audio udev rule and /etc/asound.conf"
    sudo install -m 644 "$REPO_DIR/audio/85-usb-audio-default.rules" \
        /etc/udev/rules.d/85-usb-audio-default.rules
    if [ -f /etc/asound.conf ] &&
            ! cmp -s /etc/asound.conf "$REPO_DIR/audio/asound.conf"; then
        say "Backing up /etc/asound.conf to /etc/asound.conf.$STAMP"
        sudo cp /etc/asound.conf "/etc/asound.conf.$STAMP"
    fi
    sudo install -m 644 "$REPO_DIR/audio/asound.conf" /etc/asound.conf
    sudo udevadm control --reload
    sudo udevadm trigger --subsystem-match=sound --action=add
    sleep 1
    if grep -q '\[usbaudio' /proc/asound/cards; then
        say "USB sound card found:"
        grep -A1 '\[usbaudio' /proc/asound/cards
    else
        warn "No card named usbaudio yet. Unplug and replug the USB" \
             "speaker, then check: cat /proc/asound/cards"
    fi
fi

# 7. Test the voice
say "Testing speech"
echo "3D speex installed" | espeak-ng --stdin ||
    warn "espeak-ng couldn't play; see Troubleshooting in README.md"

restart_klipper
say "Done. Turn the knob with the menu closed to hear the screen."
