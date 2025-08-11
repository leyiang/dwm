# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## About this Repository

This is a customized build of dwm (dynamic window manager) version 6.4 with multiple patches applied.

## Build System

### Standard Commands
- `make` - Build dwm binary
- `make clean` - Clean build artifacts
- `make install` - Install dwm to system (requires root)
- `make uninstall` - Remove dwm from system (requires root)

### Configuration
dwm follows the suckless philosophy - configuration is done by editing config.h and recompiling:
1. Edit `config.h` for customization
2. Run `make clean && make` to rebuild

## Architecture Overview

### Core Files
- `dwm.c` - Main window manager implementation (~2500+ lines)
- `config.h` - Configuration (keybindings, colors, rules, layouts)
- `config.mk` - Build configuration and compiler flags
- `drw.c/drw.h` - Drawing utilities for rendering
- `util.c/util.h` - Utility functions

### Applied Patches
This build includes several patches from the dwm community:
- **systray** - System tray support in the status bar
- **swallow** - Terminal swallowing (hide terminal when opening GUI apps)
- **gaps** - Configurable gaps between windows
- **colorbar** - Enhanced color scheme support
- **status2d** - Status bar with 2D drawing capabilities
- **actualfullscreen** - True fullscreen mode
- **autostart** - Auto-start applications on dwm launch
- **hide_vacant_tags** - Hide empty tags from tag bar

### Configuration Highlights
- Super key (Mod4) as main modifier
- Custom color scheme with gruvbox-like colors
- Alacritty as default terminal
- Custom volume/brightness controls via `~/scripts/vol` and `~/scripts/bri`
- Screenshot functionality via `capt` script
- Media key support for audio control

### Window Rules
Predefined rules for applications:
- Gimp: floating by default
- Firefox: assigned to tag 9
- Alacritty: marked as terminal for swallowing
- Cursor IDE: no swallowing
- Android Studio: no swallowing

### File Structure Notes
- `.orig` files are backups of original files before patches
- `patches/` directory contains all applied patch files
- Configuration follows suckless minimal philosophy
- No runtime configuration - all settings compile-time

## Development Workflow

1. Make changes to config.h or source files
2. Run `make clean && make` to rebuild
3. Test the new build: `./dwm` (in a nested X session or via xinitrc)
4. Install when satisfied: `sudo make install`

## Key Considerations

- dwm is designed to be recompiled for configuration changes
- Always backup config.h before major changes
- Patches may conflict when updating - check patches/ directory
- The build uses optimized flags (-Os) for size optimization
- No linting tools configured - code follows suckless style guidelines