#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <X11/extensions/shape.h>

#include "focus_overlay.h"
#include "util.h"

static unsigned int
focusoverlayresolvegridstep(unsigned int span, unsigned int fake_opacity_step,
	unsigned int fake_opacity_lines)
{
	const unsigned int base_stripe_step = 8;
	unsigned int grid_step;
	unsigned int nlines;

	if (fake_opacity_step > 0)
		grid_step = fake_opacity_step;
	else if (fake_opacity_lines > 0) {
		nlines = fake_opacity_lines < span ? fake_opacity_lines : span;
		if (nlines < 1)
			nlines = 1;
		grid_step = (span + nlines - 1) / nlines;
	} else
		grid_step = base_stripe_step;

	if (grid_step < 1)
		grid_step = 1;
	return grid_step;
}

static unsigned int
focusoverlaygridcount(unsigned int span, unsigned int step)
{
	if (!span)
		return 0;
	return (span + step - 1) / step;
}

static void
focusoverlayshapemask(Display *dpy, Window win, unsigned int w, unsigned int h,
	unsigned int fake_opacity_pattern, unsigned int fake_opacity_step,
	unsigned int fake_opacity_lines, unsigned int fake_opacity_line_height, double opacity)
{
	const unsigned int max_grid_rects = 8192;
	unsigned int grid_step;
	unsigned int cell_size;
	unsigned int nrows, ncols;
	unsigned int i, j, nrects, rect_index;
	XRectangle *rects;

	if (opacity <= 0.0 || !w || !h) {
		XShapeCombineMask(dpy, win, ShapeBounding, 0, 0, None, ShapeSet);
		return;
	}

	grid_step = focusoverlayresolvegridstep(h, fake_opacity_step, fake_opacity_lines);
	nrows = focusoverlaygridcount(h, grid_step);

	/* Keep the fade profile tied to the configured base thickness so density
	 * tweaks do not also change how solid each visible shape feels.
	 */
	cell_size = (unsigned int)(fake_opacity_line_height * opacity + 0.5);
	if (cell_size < 1)
		cell_size = 1;
	if (cell_size > grid_step)
		cell_size = grid_step;

	if (fake_opacity_pattern == FOCUS_FAKE_OPACITY_GRID) {
		ncols = focusoverlaygridcount(w, grid_step);
		while (nrows && ncols && nrows > max_grid_rects / ncols) {
			grid_step *= 2;
			nrows = focusoverlaygridcount(h, grid_step);
			ncols = focusoverlaygridcount(w, grid_step);
			if (cell_size > grid_step)
				cell_size = grid_step;
		}
		nrects = nrows * ncols;
		rects = ecalloc(nrects, sizeof(XRectangle));
		rect_index = 0;
		for (i = 0; i < nrows; i++) {
			unsigned int y = i * grid_step;
			unsigned int remaining_h = h > y ? h - y : 0;
			unsigned int rect_h = remaining_h < cell_size ? remaining_h : cell_size;

			for (j = 0; j < ncols; j++) {
				unsigned int x = j * grid_step;
				unsigned int remaining_w = w > x ? w - x : 0;
				unsigned int rect_w = remaining_w < cell_size ? remaining_w : cell_size;

				rects[rect_index].x = x;
				rects[rect_index].y = y;
				rects[rect_index].width = rect_w;
				rects[rect_index].height = rect_h;
				rect_index++;
			}
		}
		XShapeCombineRectangles(dpy, win, ShapeBounding, 0, 0, rects, nrects, ShapeSet, Unsorted);
	} else {
		nrects = nrows;
		rects = ecalloc(nrects, sizeof(XRectangle));
		for (i = 0; i < nrects; i++) {
			unsigned int y = i * grid_step;
			unsigned int remaining_h = h > y ? h - y : 0;

			rects[i].x = 0;
			rects[i].y = y;
			rects[i].width = w;
			rects[i].height = remaining_h < cell_size ? remaining_h : cell_size;
		}
		XShapeCombineRectangles(dpy, win, ShapeBounding, 0, 0, rects, nrects, ShapeSet, YXBanded);
	}
	free(rects);
}

int
focusoverlay_is_enabled(const FocusOverlayConfig *config)
{
	return config
		&& config->duration_ms > 0
		&& config->frame_ms > 0
		&& (!config->enable_fake_opacity || config->opacity > 0.0);
}

int
focusoverlay_timeout_ms(const FocusOverlay *overlay, const FocusOverlayConfig *config)
{
	struct timespec now;
	long elapsed_ms;
	long remaining_ms;

	if (!overlay || !overlay->active || !focusoverlay_is_enabled(config))
		return -1;

	clock_gettime(CLOCK_MONOTONIC, &now);
	elapsed_ms = (now.tv_sec - overlay->started_at.tv_sec) * 1000L
		+ (now.tv_nsec - overlay->started_at.tv_nsec) / 1000000L;
	remaining_ms = (long)config->duration_ms - elapsed_ms;
	if (remaining_ms <= 0)
		return 0;
	if (remaining_ms < (long)config->frame_ms)
		return (int)remaining_ms;
	return (int)config->frame_ms;
}

void
focusoverlay_cleanup_state(Display *dpy, FocusOverlay *overlay)
{
	if (!dpy || !overlay)
		return;

	if (overlay->window) {
		XDestroyWindow(dpy, overlay->window);
		overlay->window = None;
	}
	overlay->active = 0;
	overlay->client_ref = NULL;
	overlay->client_win = None;
	overlay->client_name[0] = '\0';
}

void
focusoverlay_hide_state(Display *dpy, const FocusOverlayConfig *config, FocusOverlay *overlay)
{
	if (!dpy || !overlay || !focusoverlay_is_enabled(config))
		return;

	if (overlay->active && overlay->client_win) {
		fprintf(stderr, "focuspulse: stop win=0x%lx name=%s\n",
			(unsigned long)overlay->client_win, overlay->client_name);
	}
	if (overlay->window)
		XUnmapWindow(dpy, overlay->window);
	overlay->active = 0;
	overlay->client_ref = NULL;
	overlay->client_win = None;
	overlay->client_name[0] = '\0';
	XFlush(dpy);
}

void
focusoverlay_raise_state(Display *dpy, const FocusOverlay *overlay)
{
	if (!dpy || !overlay || !overlay->active || !overlay->client_ref || !overlay->window)
		return;

	XRaiseWindow(dpy, overlay->window);
}

void
focusoverlay_start_state(
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
	unsigned int h)
{
	if (!dpy || !overlay || !client_ref || !focusoverlay_is_enabled(config))
		return;

	overlay->client_ref = client_ref;
	overlay->client_win = client_win;
	snprintf(overlay->client_name, sizeof(overlay->client_name), "%s", client_name ? client_name : "");
	overlay->active = 1;
	clock_gettime(CLOCK_MONOTONIC, &overlay->started_at);
	fprintf(stderr,
		"focuspulse: start reason=%s win=0x%lx name=%s geom=%ux%u+%d+%d\n",
		reason,
		(unsigned long)overlay->client_win,
		overlay->client_name,
		w,
		h,
		x,
		y);
}

void
focusoverlay_update_state(
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
	unsigned int h)
{
	struct timespec now;
	long elapsed_ms;
	double progress;
	double opacity;
	XSetWindowAttributes wa;

	if (!dpy || !overlay || !client_ref || !focusoverlay_is_enabled(config))
		return;
	if (overlay->client_ref != client_ref)
		return;

	clock_gettime(CLOCK_MONOTONIC, &now);
	elapsed_ms = (now.tv_sec - overlay->started_at.tv_sec) * 1000L
		+ (now.tv_nsec - overlay->started_at.tv_nsec) / 1000000L;
	if (elapsed_ms >= (long)config->duration_ms) {
		focusoverlay_hide_state(dpy, config, overlay);
		return;
	}

	if (!overlay->window) {
		wa.override_redirect = True;
		wa.background_pixel = color;
		wa.border_pixel = color;
		overlay->window = XCreateWindow(
			dpy, root, 0, 0, 1, 1, 0, DefaultDepth(dpy, screen),
			CopyFromParent, DefaultVisual(dpy, screen),
			CWOverrideRedirect|CWBackPixel|CWBorderPixel, &wa);
	} else {
		XSetWindowBackground(dpy, overlay->window, color);
	}

	progress = (double)elapsed_ms / (double)config->duration_ms;
	opacity = config->opacity * (1.0 - progress);
	if (opacity < 0.0)
		opacity = 0.0;

	XMoveResizeWindow(dpy, overlay->window, x, y, w, h);
	if (config->enable_fake_opacity && config->shape_supported)
		focusoverlayshapemask(
			dpy,
			overlay->window,
			w,
			h,
			config->fake_opacity_pattern,
			config->fake_opacity_step,
			config->fake_opacity_lines,
			config->fake_opacity_line_height,
			opacity);
	else if (config->shape_supported)
		XShapeCombineMask(dpy, overlay->window, ShapeBounding, 0, 0, None, ShapeSet);
	XMapRaised(dpy, overlay->window);
	XFlush(dpy);
}
