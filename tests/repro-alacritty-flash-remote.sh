#!/bin/sh

set -u
MODE="${1:-baseline}"
exec >/tmp/vm-flash-repro-trace.log 2>&1
set -x

export DISPLAY=:0
export XAUTHORITY="/run/user/$(id -u)/gdm/Xauthority"

# 等待 Xorg 与 dwm 就绪（防止刚重启 gdm3 时尚未登录完成）
i=0
while [ "$i" -lt 60 ]; do
    if xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null | grep -q 'window id # 0x'; then
        break
    fi
    sleep 0.25
    i=$((i + 1))
done
sleep 0.5

VIDEO_OUT="/tmp/dwm-alacritty-flash.mp4"
ARTIFACT_BUNDLE="/tmp/dwm-flash-artifacts.tar"

rm -f "$VIDEO_OUT" "$ARTIFACT_BUNDLE" /tmp/alacritty-1.log /tmp/alacritty-2.log /tmp/picom.log /tmp/dwmcomp.log /tmp/alacritty-wininfo.txt

# 清理残留进程
pkill -f 'dwm-flash-repro-term' || true
pkill -x picom || true
pkill -x dwmcomp || true
sleep 0.3

SCREEN_SIZE=$(xdpyinfo 2>/dev/null | awk '/dimensions:/ {print $2; exit}')
if [ -z "$SCREEN_SIZE" ]; then
    SCREEN_SIZE="1280x800"
fi
echo "MODE=$MODE SCREEN_SIZE=$SCREEN_SIZE"

# 设置兼容 picom (_XROOTPMAP_ID) 与原生 X11 的肉粉色桌面背景 #dbb199
python3 - <<'PY' || true
from Xlib import X, Xatom, display
d = display.Display()
s = d.screen()
root = s.root
pm = root.create_pixmap(1, 1, s.root_depth)
gc = pm.create_gc(foreground=0xdbb199)
pm.fill_rectangle(gc, 0, 0, 1, 1)
root.change_attributes(background_pixmap=pm)
for name in ("_XROOTPMAP_ID", "ESETROOT_PMAP_ID"):
    atom = d.intern_atom(name)
    root.change_property(atom, Xatom.PIXMAP, 32, [pm.id])
root.clear_area(0, 0, 0, 0, False)
d.set_close_down_mode(X.RetainPermanent)
d.sync()
PY

ldconfig -p | grep -E 'libXdamage|libXcomposite' || true

# 按模式启动 picom（方案 1）
if [ "$MODE" = "picom-default" ] || [ "$MODE" = "picom-fade" ]; then
    if ! command -v picom >/dev/null 2>&1; then
        echo test | sudo -S apt-get update
        echo test | sudo -S apt-get install -y picom
    fi
fi

if [ "$MODE" = "picom-default" ]; then
    picom --backend xrender --no-fading-openclose >/tmp/picom.log 2>&1 &
    PICOM_PID=$!
    sleep 0.8
elif [ "$MODE" = "picom-fade" ]; then
    picom --backend xrender --fading --fade-in-step=0.06 --fade-out-step=0.06 --fade-delta=10 >/tmp/picom.log 2>&1 &
    PICOM_PID=$!
    sleep 0.8
elif [ "$MODE" = "dwmcomp" ] || [ "$MODE" = "dwmcomp-contrast" ] || [ "$MODE" = "dwmcomp-lifecycle" ]; then
    "$HOME/dwmcomp" -v >/tmp/dwmcomp.log 2>&1 &
    PICOM_PID=$!
    sleep 0.8
else
    PICOM_PID=""
fi

# 切到 workspace 3
xdotool key Super_L+3 || true
sleep 0.5

# 启动 60fps 录屏
ffmpeg -y -f x11grab -framerate 60 -video_size "$SCREEN_SIZE" -i :0.0 \
    -c:v libx264 -preset ultrafast -crf 12 -pix_fmt yuv420p \
    "$VIDEO_OUT" >/tmp/ffmpeg-flash-repro.log 2>&1 &
FFMPEG_PID=$!

sleep 0.8

# 打开第一个 alacritty
alacritty --title "dwm-flash-repro-term-1" \
    -o 'colors.primary.background="#fff9e9"' \
    -o 'colors.primary.foreground="#333333"' \
    >/tmp/alacritty-1.log 2>&1 &
A1_PID=$!

i=0
while [ "$i" -lt 40 ]; do
    if wmctrl -lx 2>/dev/null | grep -qi 'alacritty'; then
        break
    fi
    sleep 0.1
    i=$((i + 1))
done
sleep 0.8

# 记录第一个 Alacritty 的 X11 窗口属性（Depth / Visual）
WID1=$(wmctrl -lx 2>/dev/null | awk 'tolower($0) ~ /alacritty/ {print $1; exit}')
if [ -n "$WID1" ]; then
    xwininfo -id "$WID1" >/tmp/alacritty-wininfo.txt 2>&1 || true
fi

# 打开第二个 alacritty
if [ "$MODE" = "dwmcomp-contrast" ]; then
    alacritty --title "dwm-flash-repro-term-2" \
        -o 'colors.primary.background="#1e222a"' \
        -o 'colors.primary.foreground="#e5e9f0"' \
        >/tmp/alacritty-2.log 2>&1 &
else
    alacritty --title "dwm-flash-repro-term-2" \
        -o 'colors.primary.background="#fff9e9"' \
        -o 'colors.primary.foreground="#333333"' \
        >/tmp/alacritty-2.log 2>&1 &
fi
A2_PID=$!

i=0
while [ "$i" -lt 40 ]; do
    COUNT=$(wmctrl -lx 2>/dev/null | grep -ci 'alacritty' || true)
    if [ "$COUNT" -ge 2 ]; then
        break
    fi
    sleep 0.1
    i=$((i + 1))
done
sleep 1.0

# 完整生命周期模式：继续录制关闭第 2 个窗口 (2->1)、关闭第 1 个窗口 (1->0)、再空 workspace 开深色窗口 (0->1)
if [ "$MODE" = "dwmcomp-lifecycle" ]; then
    # 关闭第 2 个窗口（模拟真实 kill 窗口，观察剩余窗口放大回全屏是否闪烁）
    kill "$A2_PID" 2>/dev/null || true
    i=0
    while [ "$i" -lt 40 ]; do
        COUNT=$(wmctrl -lx 2>/dev/null | grep -ci 'alacritty' || true)
        if [ "$COUNT" -le 1 ]; then
            break
        fi
        sleep 0.05
        i=$((i + 1))
    done
    sleep 0.9

    # 关闭第 1 个窗口回到空 workspace
    kill "$A1_PID" 2>/dev/null || true
    i=0
    while [ "$i" -lt 40 ]; do
        COUNT=$(wmctrl -lx 2>/dev/null | grep -ci 'alacritty' || true)
        if [ "$COUNT" -eq 0 ]; then
            break
        fi
        sleep 0.05
        i=$((i + 1))
    done
    sleep 0.6

    # 在空 workspace 打开深色 Alacritty
    alacritty --title "dwm-flash-repro-term-3" \
        -o 'colors.primary.background="#1e222a"' \
        -o 'colors.primary.foreground="#e5e9f0"' \
        >/tmp/alacritty-3.log 2>&1 &
    A3_PID=$!
    i=0
    while [ "$i" -lt 40 ]; do
        if wmctrl -lx 2>/dev/null | grep -qi 'alacritty'; then
            break
        fi
        sleep 0.1
        i=$((i + 1))
    done
    sleep 0.8
fi

# 结束录屏
kill -INT "$FFMPEG_PID" 2>/dev/null || true
wait "$FFMPEG_PID" 2>/dev/null || true

# 清理测试窗口与 picom
kill "${A3_PID:-}" "$A2_PID" "$A1_PID" 2>/dev/null || true
pkill -f 'dwm-flash-repro-term' || true
if [ -n "$PICOM_PID" ]; then
    kill "$PICOM_PID" 2>/dev/null || true
    pkill -x picom || true
    pkill -x dwmcomp || true
fi

ls -lh "$VIDEO_OUT" || true

tar -C /tmp -cf "$ARTIFACT_BUNDLE" \
    dwm-alacritty-flash.mp4 \
    vm-flash-repro-trace.log \
    ffmpeg-flash-repro.log \
    alacritty-1.log \
    alacritty-2.log \
    alacritty-wininfo.txt \
    picom.log \
    dwmcomp.log \
    dwm.log 2>/dev/null || true
