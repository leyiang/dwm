#ifndef FOCUS_OVERLAY_H
#define FOCUS_OVERLAY_H

#include <time.h>
#include <X11/Xlib.h>

enum {
	FOCUS_FAKE_OPACITY_STRIPES = 0,
	FOCUS_FAKE_OPACITY_GRID = 1,
};

typedef struct {
	int enable_fake_opacity;
	int shape_supported;
	unsigned int duration_ms;
	unsigned int frame_ms;
	unsigned int fake_opacity_pattern;
	unsigned int fake_opacity_step;
	unsigned int fake_opacity_lines;
	unsigned int fake_opacity_line_height;
	double opacity;
} FocusOverlayConfig;

typedef struct {
	void *client_ref;
	Window client_win;
	char client_name[256];
	Window window;
	int active;
	struct timespec started_at;
} FocusOverlay;

int focusoverlay_is_enabled(const FocusOverlayConfig *config);
int focusoverlay_timeout_ms(const FocusOverlay *overlay, const FocusOverlayConfig *config);
void focusoverlay_cleanup_state(Display *dpy, FocusOverlay *overlay);
void focusoverlay_hide_state(Display *dpy, const FocusOverlayConfig *config, FocusOverlay *overlay);
void focusoverlay_raise_state(Display *dpy, const FocusOverlay *overlay);
void focusoverlay_start_state(
	Display *dpy,
	FocusOverlay *overlay,
	const FocusOverlayConfig *config,
	void *client_ref,
	Window client_win,
	const char *client_name,
	const char *reason,
	int x,
	int y,
	unsigned int w,
	unsigned int h
);
void focusoverlay_update_state(
	Display *dpy,
	int screen,
	Window root,
	FocusOverlay *overlay,
	const FocusOverlayConfig *config,
	unsigned long color,
	void *client_ref,
	int x,
	int y,
	unsigned int w,
	unsigned int h
);

#endif
