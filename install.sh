#!/bin/bash
# 3dspeex installer. Run on the printer, as the user Klipper runs as:
#   ./install.sh               install / update
#   ./install.sh --usb-audio   also make a USB sound card the default
#   ./install.sh --uninstall   remove 3dspeex (audio setup is left alone)
# Add --no-restart to skip restarting Klipper.
# Paths can be overridden: KLIPPER_DIR=... CONFIG_DIR=... ./install.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
KLIPPER_DIR="${KLIPPER_DIR:-$HOME/klipper}"
CONFIG_DIR="${CONFIG_DIR:-$HOME/printer_data/config}"
EXTRA="$KLIPPER_DIR/klippy/extras/menu_announce.py"
PRINTER_CFG="$CONFIG_DIR/printer.cfg"
OUR_CFG="$CONFIG_DIR/3dspeex.cfg"
INCLUDE_LINE="[include 3dspeex.cfg]"
STAMP="$(date +%Y%m%d-%H%M%S)"

usb_audio=0 restart=1 uninstall=0
for arg in "$@"; do
    case "$arg" in
        --usb-audio) usb_audio=1 ;;
        --no-restart) restart=0 ;;
        --uninstall) uninstall=1 ;;
        -h|--help) sed -n '2,8p' "$0" | cut -c3-; exit 0 ;;
        *) echo "unknown option: $arg (try --help)" >&2; exit 1 ;;
    esac
done

say() { echo "==> $*"; }
warn() { echo "!!  $*" >&2; }

have_klipper_service() {
    systemctl cat klipper.service >/dev/null 2>&1
}

# Files that configure [menu_announce] (only the ones Klipper reads here)
configured_in() {
    grep -ls '^\[menu_announce\]' "$PRINTER_CFG" "$OUR_CFG" || true
}

# Refuse to restart Klipper in the middle of a print.
printer_busy() {
    local state
    state="$(curl -s --max-time 3 \
        'http://localhost:7125/printer/objects/query?print_stats=state' |
        python3 -c 'import json,sys
print(json.load(sys.stdin)["result"]["status"]["print_stats"]["state"])' \
        2>/dev/null)" || return 1
    [ "$state" = printing ] || [ "$state" = paused ]
}

restart_klipper() {
    if [ "$restart" = 0 ] || ! have_klipper_service; then
        say "Restart Klipper yourself to apply: sudo systemctl restart klipper"
    elif printer_busy; then
        warn "A print is running; not restarting Klipper. Restart it later."
    else
        say "Restarting Klipper"
        sudo systemctl restart klipper
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
    if grep -qxF "$INCLUDE_LINE" "$PRINTER_CFG"; then
        say "Removing $INCLUDE_LINE from printer.cfg (backup: printer.cfg.$STAMP)"
        cp "$PRINTER_CFG" "$PRINTER_CFG.$STAMP"
        grep -vxF "$INCLUDE_LINE" "$PRINTER_CFG.$STAMP" > "$PRINTER_CFG"
    fi
    if [ -f "$OUR_CFG" ]; then
        say "Keeping your settings in $OUR_CFG.$STAMP"
        mv "$OUR_CFG" "$OUR_CFG.$STAMP"
    fi
    if [ -n "$(configured_in)" ]; then
        warn "printer.cfg still has a [menu_announce] section; remove it" \
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
say "Linking $EXTRA -> $REPO_DIR/menu_announce.py"
ln -sfn "$REPO_DIR/menu_announce.py" "$EXTRA"
# Keep Klipper's git checkout clean so Moonraker doesn't call it "dirty"
exclude="$KLIPPER_DIR/.git/info/exclude"
if [ -d "$KLIPPER_DIR/.git" ] &&
        ! grep -qxF "klippy/extras/menu_announce.py" "$exclude" 2>/dev/null; then
    mkdir -p "$(dirname "$exclude")"
    echo "klippy/extras/menu_announce.py" >> "$exclude"
fi

# 3. Config: a separate 3dspeex.cfg, included from printer.cfg. Adding
#    the include at the top keeps clear of the SAVE_CONFIG block at the end.
if [ -n "$(configured_in)" ]; then
    say "[menu_announce] already configured in $(configured_in | xargs -n1 basename)"
else
    say "Writing $OUR_CFG"
    cat > "$OUR_CFG" <<'EOF'
# 3dspeex - spoken screen reader for the printer's LCD
# https://github.com/daiverd/3dspeex
[menu_announce]
# progress_step: 10     # say print progress every N percent (0 = off)
# announce_info: False  # also say "//" info lines (chatty)
EOF
    say "Adding $INCLUDE_LINE to printer.cfg (backup: printer.cfg.$STAMP)"
    cp "$PRINTER_CFG" "$PRINTER_CFG.$STAMP"
    { echo "$INCLUDE_LINE"; cat "$PRINTER_CFG.$STAMP"; } > "$PRINTER_CFG"
fi

# 4. Let the Klipper service's user reach the sound card
if have_klipper_service; then
    kuser="$(systemctl show -p User --value klipper.service)"
    kuser="${kuser:-root}"
    if [ "$kuser" != root ] && ! id -nG "$kuser" | grep -qw audio; then
        say "Adding $kuser to the audio group"
        sudo usermod -aG audio "$kuser"
    fi
fi

# 5. Optional: always use a USB sound card
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

# 6. Test the voice
say "Testing speech"
echo "3D speex installed" | espeak-ng --stdin ||
    warn "espeak-ng couldn't play; see Troubleshooting in README.md"

restart_klipper
say "Done. Turn the knob with the menu closed to hear the screen."
