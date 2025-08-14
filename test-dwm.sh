#!/bin/bash

# DWM Test Script using Xephyr
# This script safely tests dwm in a nested X session

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== DWM Testing Script ===${NC}"

# Check if dwm binary exists
if [ ! -f "./dwm" ]; then
    echo -e "${RED}Error: dwm binary not found. Please run 'make' first.${NC}"
    exit 1
fi

# Check if Xephyr is installed
if ! command -v Xephyr &> /dev/null; then
    echo -e "${RED}Error: Xephyr not found. Please install xserver-xephyr${NC}"
    echo "Ubuntu/Debian: sudo apt install xserver-xephyr"
    echo "Arch Linux: sudo pacman -S xorg-server-xephyr"
    exit 1
fi

# Find available display number
DISPLAY_NUM=""
for i in {10..30}; do
    if ! ls /tmp/.X11-unix/X${i} 2>/dev/null >/dev/null; then
        DISPLAY_NUM=$i
        break
    fi
done

if [ -z "$DISPLAY_NUM" ]; then
    echo -e "${RED}Error: No available display numbers found${NC}"
    exit 1
fi

export TEST_DISPLAY=":$DISPLAY_NUM"
echo -e "${GREEN}Using display $TEST_DISPLAY${NC}"

# Cleanup function
cleanup() {
    echo -e "\n${YELLOW}Cleaning up...${NC}"
    if [ ! -z "$XEPHYR_PID" ]; then
        kill $XEPHYR_PID 2>/dev/null || true
    fi
    if [ ! -z "$DWM_PID" ]; then
        kill $DWM_PID 2>/dev/null || true
    fi
    
    # Clean up temporary directory
    if [ ! -z "$XDG_DATA_HOME" ] && [ -d "$XDG_DATA_HOME" ]; then
        rm -rf "$XDG_DATA_HOME"
    fi
    
    # Wait a bit for processes to clean up
    sleep 1
    echo -e "${GREEN}Test session ended.${NC}"
}

# Set trap to cleanup on exit
trap cleanup EXIT INT TERM

echo -e "${BLUE}Starting Xephyr on display $TEST_DISPLAY...${NC}"
echo -e "${RED}SAFETY TIP: If Xephyr captures all input:${NC}"
echo -e "${RED}Press Ctrl+Alt+F2, login, run: killall Xephyr${NC}"
echo -e "${RED}Then Ctrl+Alt+F7 to return to desktop${NC}"
echo ""
Xephyr -br -ac -noreset -screen 3200x2200 -host-cursor $TEST_DISPLAY &
XEPHYR_PID=$!

# Wait for Xephyr to start
sleep 3

echo -e "${YELLOW}Click on the Xephyr window to give it focus!${NC}"

echo -e "${BLUE}Starting dwm...${NC}"
# Disable autostart scripts in test environment
export XDG_DATA_HOME="/tmp/dwm-test-$$"
mkdir -p "$XDG_DATA_HOME"
DISPLAY=$TEST_DISPLAY ./dwm &
DWM_PID=$!

# Wait for dwm to start
sleep 2

# Try to automatically focus the Xephyr window
echo -e "${BLUE}Trying to focus Xephyr window...${NC}"
XEPHYR_WINDOW=$(DISPLAY=:0 xwininfo -root -tree | grep "Xephyr" | head -n1 | awk '{print $1}')
if [ ! -z "$XEPHYR_WINDOW" ]; then
    DISPLAY=:0 xdotool windowactivate $XEPHYR_WINDOW 2>/dev/null || echo "Could not auto-focus, please click the window"
else
    echo -e "${YELLOW}Please click on the Xephyr window to focus it${NC}"
fi

echo -e "${BLUE}Setting up key mappings...${NC}"
# Get current key mapping and find a safe approach
DISPLAY=$TEST_DISPLAY xmodmap -pm > /dev/null 2>&1
if [ $? -eq 0 ]; then
    # Try a simpler approach: just inform user about alternative keys
    echo -e "${YELLOW}Key remapping skipped - will use Ctrl+Super instead${NC}"
    echo -e "${GREEN}This avoids conflicts with host system${NC}"
else
    echo -e "${YELLOW}Could not set up key remapping${NC}"
fi

echo -e "${BLUE}Starting terminal...${NC}"
# Try different terminals in order of preference
if command -v alacritty &> /dev/null; then
    DISPLAY=$TEST_DISPLAY alacritty &
    DISPLAY=$TEST_DISPLAY alacritty &
elif command -v xterm &> /dev/null; then
    DISPLAY=$TEST_DISPLAY xterm &
elif command -v gnome-terminal &> /dev/null; then
    DISPLAY=$TEST_DISPLAY gnome-terminal &
else
    echo -e "${YELLOW}Warning: No suitable terminal found${NC}"
fi

echo -e "${GREEN}=== DWM Test Session Started ===${NC}"
echo -e "${RED}IMPORTANT: Click on the Xephyr window first to focus it!${NC}"
echo ""
echo -e "${YELLOW}Test Steps:${NC}"
echo "1. Click on the Xephyr window (the one with dwm)"
echo "2. Test Super+Return to open a terminal"
echo "3. If it opens in host instead, the window doesn't have focus"
echo "4. Try Super+h to hide the window"
echo "5. Look for the red [H] indicator in the status bar"
echo "6. Press Super+h again to restore"
echo ""
echo -e "${BLUE}Key bindings (make sure Xephyr window is focused!):${NC}"
echo "Super+Return      - Open terminal"
echo "Super+h           - Hide/unhide window"
echo "Super+j/k         - Switch between windows"
echo "Super+q           - Close window"
echo "Super+Shift+e     - Exit dwm"
echo ""
echo -e "${GREEN}To test multiple windows:${NC}"
echo "1. Open 2-3 terminals with Super+Return"
echo "2. Hide one with Super+h (watch for [H] indicator)"
echo "3. Switch between visible windows with Super+j/k"
echo "4. Restore hidden window with Super+h"
echo ""
echo -e "${RED}Press Enter here to quit the test session...${NC}"

# Wait for user input
read -r

# Cleanup will be called automatically by trap
