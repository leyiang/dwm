# Fix Per-Tag Layout Command

## Purpose
Enable per-tag (workspace) independent layouts in dwm - each tag can have different layout settings.

## What Was Done

### 1. Applied pertag patch
- Downloaded: `dwm-pertag-20200914-61bb8b2.diff`
- Applied with: `patch -p1 < dwm-pertag-20200914-61bb8b2.diff`
- Enables per-tag: layout, mfact, nmaster, barpos

### 2. Fixed custom togglelayout function
**Issue**: Custom `togglelayout()` function bypassed pertag system
**Location**: `dwm.c:2086-2104`
**Fix**: Changed line 2098 from:
```c
selmon->lt[selmon->sellt] = target;
```
To:
```c
selmon->lt[selmon->sellt] = selmon->pertag->ltidxs[selmon->pertag->curtag][selmon->sellt] = target;
```

### 3. Build Process
```bash
make clean && make
```

## Result
- Each workspace (tag) now maintains independent layout
- Super+f toggles between tile/monocle per tag
- Layout persists when switching between workspaces

## Key Files Modified
- `dwm.c` - Main pertag integration + togglelayout fix
- Added `dwm-pertag-20200914-61bb8b2.diff` patch file

## Important Notes
- Any custom layout functions must use pertag system: `selmon->pertag->ltidxs[selmon->pertag->curtag][selmon->sellt]`
- Not just direct `selmon->lt[selmon->sellt]` modifications