#!/bin/bash
# Simple script to show current workspace

# Get current workspace from dwm
current=$(xprop -root _DWM_CURRENT_WORKSPACE 2>/dev/null | awk '{print $3}')

if [[ -z "$current" || "$current" == "" ]]; then
    # Not in a dynamic workspace, check which fixed tag is active
    # This requires checking dwm's internal state, for now show "Fixed Tag"
    echo "Fixed Tag"
    exit 0
fi

# Decode the workspace number
if [[ "$current" =~ ^[0-9]+$ ]]; then
    # Find which bit is set
    for i in {10..31}; do
        if (( current & (1 << i) )); then
            ws_num=$((i - 9))
            echo "WS$ws_num"
            exit 0
        fi
    done
    
    # Check if it's a fixed tag (bits 0-9)
    for i in {0..9}; do
        if (( current & (1 << i) )); then
            echo "Tag $((i + 1))"
            exit 0
        fi
    done
fi

echo "Unknown"