#!/bin/sh

set -eu

export DISPLAY=:0
export XAUTHORITY=/run/user/1000/gdm/Xauthority

wait_for_session() {
    i=0
    while [ "$i" -lt 50 ]; do
        if pgrep -x dwm >/dev/null 2>&1 && xset q >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.2
        i=$((i + 1))
    done
    return 1
}

wait_for_alacritty_count() {
    target="$1"
    i=0
    while [ "$i" -lt 25 ]; do
        count=$(wmctrl -lx 2>/dev/null | awk '$3 == "Alacritty.Alacritty" {count++} END {print count + 0}')
        if [ "$count" -eq "$target" ]; then
            return 0
        fi
        sleep 0.2
        i=$((i + 1))
    done
    return 1
}

capture_geometries() {
    wmctrl -lxG 2>/dev/null | awk '$7 == "Alacritty.Alacritty" {print $3, $4, $5, $6}' | sort
}

wait_for_session

: >/tmp/dwm.log
pkill -f '^alacritty$' || true
wait_for_alacritty_count 0 || true

xdotool key Super_L+1
sleep 1
xdotool key Super_L+b
sleep 1

alacritty >/tmp/alacritty-layout-check-1.log 2>&1 &
alacritty >/tmp/alacritty-layout-check-2.log 2>&1 &
wait_for_alacritty_count 2
sleep 1
capture_geometries >/tmp/layout-magicgrid.txt

xdotool key Super_L+f
sleep 1
capture_geometries >/tmp/layout-tile.txt

xdotool key Super_L+1
sleep 1
xdotool key Super_L+b
sleep 1
capture_geometries >/tmp/layout-return.txt

echo "== magicgrid =="
cat /tmp/layout-magicgrid.txt
echo
echo "== tile =="
cat /tmp/layout-tile.txt
echo
echo "== return =="
cat /tmp/layout-return.txt
echo

if cmp -s /tmp/layout-magicgrid.txt /tmp/layout-return.txt &&
   ! cmp -s /tmp/layout-magicgrid.txt /tmp/layout-tile.txt; then
    echo "RESULT: PASS"
else
    echo "RESULT: FAIL"
    exit 1
fi

echo
echo "== dwm log =="
tail -n 120 /tmp/dwm.log || true
