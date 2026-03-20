#!/bin/sh

set -u
exec >/tmp/vm-repro-trace.log 2>&1
set -x

export DISPLAY=:0
export XAUTHORITY=/run/user/1000/gdm/Xauthority
ARTIFACT_BUNDLE=/tmp/dwm-repro-artifacts.tar

: > /tmp/dwm.log
pkill -f 'ffplay -f lavfi -i anoisesrc=color=pink' || true
pkill -f '^alacritty$' || true

rm -f \
    /tmp/dwm-repro-before.png \
    /tmp/dwm-repro-after.png \
    /tmp/dwm-tree-before.txt \
    /tmp/dwm-tree-after.txt \
    /tmp/dwm-map-after.txt \
    /tmp/wmctrl-before.txt \
    /tmp/wmctrl-after.txt \
    /tmp/dwm-repro-artifacts.tar \
    /tmp/ffplay-repro.log \
    /tmp/xset.txt

xset q >/tmp/xset.txt 2>&1 || true
xdotool key Super_L+b || true

i=0
while [ "$i" -lt 10 ]; do
    sleep 0.2
    i=$((i + 1))
done

alacritty -e ffplay -f lavfi -i anoisesrc=color=pink >/tmp/ffplay-repro.log 2>&1 &
i=0
while [ "$i" -lt 20 ]; do
    if wmctrl -lx 2>/dev/null | grep -q 'ffplay.ffplay'; then
        break
    fi
    sleep 0.2
    i=$((i + 1))
done

scrot /tmp/dwm-repro-before.png || true
xwininfo -root -tree >/tmp/dwm-tree-before.txt || true
wmctrl -lxG >/tmp/wmctrl-before.txt || true

xdotool key Super_L+1 || true
i=0
while [ "$i" -lt 10 ]; do
    sleep 0.2
    i=$((i + 1))
done

scrot /tmp/dwm-repro-after.png || true
xwininfo -root -tree >/tmp/dwm-tree-after.txt || true
wmctrl -lxG >/tmp/wmctrl-after.txt || true
for wid in $(awk '$1 ~ /^0x[0-9a-f]+$/ {print $1}' /tmp/dwm-tree-after.txt); do
    xwininfo -id "$wid" -stats >>/tmp/dwm-map-after.txt 2>&1 || true
done

pkill -f 'ffplay -f lavfi -i anoisesrc=color=pink' || true

tar -C /tmp -cf "$ARTIFACT_BUNDLE" \
    dwm-repro-before.png \
    dwm-repro-after.png \
    dwm-tree-before.txt \
    dwm-tree-after.txt \
    dwm-map-after.txt \
    wmctrl-before.txt \
    wmctrl-after.txt \
    dwm.log \
    vm-repro-trace.log \
    ffplay-repro.log \
    xset.txt
