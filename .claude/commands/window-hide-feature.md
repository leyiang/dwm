# Window Hide Feature

## Overview
Implements toggle-based window hiding with Super+h keybinding. Single window can be hidden/restored with visual indicator.

## Key Components

### Files Modified
- `config.h`: Added SchemeHidden color scheme, Super+h keybinding
- `dwm.c`: Core hiding logic implementation

### Critical Implementation Details

**IMPORTANT**: Must use `XMoveWindow()` not `XUnmapWindow()` - XUnmapWindow causes X11 events that clear hidden pointer.

**Global State**: Uses `globalhidden` pointer (not per-monitor) to avoid pertag/monitor switching issues.

### Code Changes

1. **Client struct**: Added `ishidden` field
2. **ISVISIBLE macro**: Modified to exclude hidden windows `&& !C->ishidden`  
3. **Global variable**: `static Client *globalhidden = NULL;`
4. **hide() function**: 
   - Hide: `XMoveWindow(dpy, c->win, -9999, c->y);`
   - Restore: Moves window to current tag/monitor
5. **showhide()**: Skip manually hidden windows
6. **drawbar()**: Shows [H] indicator when `globalhidden != NULL`

### Known Issues Fixed
- ❌ XUnmapWindow() - causes pointer clearing
- ❌ Per-monitor hidden field - loses state on tag/monitor switch  
- ✅ Global pointer + XMoveWindow - stable solution

### Usage
- Super+h: Hide current window / Restore hidden window
- [H] indicator appears in status bar when window is hidden
- Restored windows move to current tag/monitor

### Testing
Works with cross-tag, cross-monitor scenarios. Only one window can be hidden at a time.