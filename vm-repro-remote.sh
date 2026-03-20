#!/bin/sh

set -u
exec >/tmp/vm-repro-trace.log 2>&1
set -x

export DISPLAY=:0
export XAUTHORITY=/run/user/1000/gdm/Xauthority

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
    /tmp/ffplay-repro.log \
    /tmp/xset.txt

xset q >/tmp/xset.txt 2>&1 || true
xdotool key Super_L+b || true
sleep 2

alacritty -e ffplay -f lavfi -i anoisesrc=color=pink >/tmp/ffplay-repro.log 2>&1 &
sleep 4

scrot /tmp/dwm-repro-before.png || true
xwininfo -root -tree >/tmp/dwm-tree-before.txt || true
wmctrl -lxG >/tmp/wmctrl-before.txt || true

xdotool key Super_L+1 || true
sleep 2

scrot /tmp/dwm-repro-after.png || true
xwininfo -root -tree >/tmp/dwm-tree-after.txt || true
wmctrl -lxG >/tmp/wmctrl-after.txt || true
for wid in $(awk '$1 ~ /^0x[0-9a-f]+$/ {print $1}' /tmp/dwm-tree-after.txt); do
    xwininfo -id "$wid" -stats >>/tmp/dwm-map-after.txt 2>&1 || true
done

pkill -f 'ffplay -f lavfi -i anoisesrc=color=pink' || true
