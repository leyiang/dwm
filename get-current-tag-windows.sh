#!/bin/bash

# 获取当前标签下的窗口
# Get windows under current tag

# 获取当前桌面/标签编号
current_desktop=$(xprop -root _NET_CURRENT_DESKTOP | cut -d' ' -f3)

echo "Current desktop/tag: $current_desktop"
echo "Windows on current tag:"
echo "======================"

# 获取所有窗口
windows=$(xprop -root _NET_CLIENT_LIST | cut -d'#' -f2 | tr ',' '\n' | sed 's/^ *//')

for win in $windows; do
    if [ -n "$win" ]; then
        # 获取窗口的桌面编号
        win_desktop=$(xprop -id "$win" _NET_WM_DESKTOP 2>/dev/null | cut -d'=' -f2 | tr -d ' ')
        
        # 如果窗口在当前桌面
        if [ "$win_desktop" = "$current_desktop" ]; then
            # 获取窗口名称
            win_name=$(xprop -id "$win" WM_NAME 2>/dev/null | cut -d'=' -f2 | sed 's/^[[:space:]]*//' | sed 's/"//g')
            echo "Window ID: $win"
            echo "  Name: $win_name"
            echo ""
        fi
    fi
done