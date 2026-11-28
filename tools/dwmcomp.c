/*
 * dwmcomp - Minimal X11 compositor with atomic Map/Resize/Unmap presentation.
 *
 * Build:
 *   cc -O2 -Wall -Wextra -o tools/dwmcomp tools/dwmcomp.c \
 *      -lXcomposite -lXdamage -lXfixes -lXrender -lXext -lX11
 */

#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <time.h>
#include <unistd.h>

#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/extensions/Xcomposite.h>
#include <X11/extensions/Xdamage.h>
#include <X11/extensions/Xfixes.h>
#include <X11/extensions/Xrender.h>
#include <X11/extensions/shape.h>

#define FREEZE_TIMEOUT_MS       200
#define RESIZE_TIMEOUT_MS       140
#define SHRINK_COALESCE_MS      16
#define UNMAP_COALESCE_MS       35

typedef struct CompWin CompWin;
struct CompWin {
	Window id;
	XWindowAttributes a;
	int mapped;
	int argb;
	Pixmap pixmap;
	Picture picture;
	Damage damage;
	int waiting_paint;
	int damage_count;
	long long freeze_start_ms;
	long long wait_deadline_ms;
	CompWin *prev;
	CompWin *next;
};

static Display *dpy;
static int scr;
static Window root;
static Window overlay;
static int sw, sh, root_depth;
static XRenderPictFormat *root_fmt;
static Pixmap back_pixmap;
static Picture back_pic;
static Picture overlay_pic;
static Picture root_tile = None;
static Atom atom_xrootpmap;
static Atom atom_esetroot;

static int damage_event_base, shape_event_base;
static CompWin *win_head = NULL; /* bottom */
static CompWin *win_tail = NULL; /* top */
static int dirty = 1;
static long long coalesce_until_ms = 0;
static volatile sig_atomic_t running = 1;
static int verbose = 0;

static long long
now_ms(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (long long)ts.tv_sec * 1000LL + ts.tv_nsec / 1000000LL;
}

static void
on_signal(int sig)
{
	(void)sig;
	running = 0;
}

static int
xerror_ignore(Display *d, XErrorEvent *e)
{
	(void)d;
	(void)e;
	return 0;
}

static CompWin *
find_win(Window id)
{
	for (CompWin *w = win_head; w; w = w->next) {
		if (w->id == id)
			return w;
	}
	return NULL;
}

static int
win_on_screen(const CompWin *w)
{
	int bw = w->a.border_width;
	int x1 = w->a.x;
	int y1 = w->a.y;
	int x2 = x1 + w->a.width + 2 * bw;
	int y2 = y1 + w->a.height + 2 * bw;
	return w->a.width > 0 && w->a.height > 0 && x2 > 0 && y2 > 0 && x1 < sw && y1 < sh;
}

static int
is_normal_onscreen_win(const CompWin *w)
{
	return w && w->mapped && !w->a.override_redirect &&
	       w->a.class == InputOutput &&
	       w->a.width > 1 && w->a.height > 1 && win_on_screen(w);
}

static int
count_other_normal_onscreen_wins(const CompWin *exclude)
{
	int n = 0;
	for (CompWin *w = win_head; w; w = w->next) {
		if (w != exclude && is_normal_onscreen_win(w))
			n++;
	}
	return n;
}

static Bool
match_win_damage(Display *d, XEvent *ev, XPointer arg)
{
	(void)d;
	Window target = *(Window *)arg;
	if (ev->type == damage_event_base + XDamageNotify) {
		XDamageNotifyEvent *dev = (XDamageNotifyEvent *)ev;
		return dev->drawable == target;
	}
	return False;
}

static void
drain_win_damage(CompWin *w)
{
	if (!w || w->damage == None)
		return;
	XDamageSubtract(dpy, w->damage, None, None);
	XSync(dpy, False);
	XEvent ev;
	Window wid = w->id;
	while (XCheckIfEvent(dpy, &ev, match_win_damage, (XPointer)&wid))
		XDamageSubtract(dpy, w->damage, None, None);
}

static void
release_win_pixmap(CompWin *w)
{
	if (w->picture != None) {
		XRenderFreePicture(dpy, w->picture);
		w->picture = None;
	}
	if (w->pixmap != None) {
		XFreePixmap(dpy, w->pixmap);
		w->pixmap = None;
	}
}

static void
release_win_damage(CompWin *w)
{
	if (w->damage != None) {
		XDamageDestroy(dpy, w->damage);
		w->damage = None;
	}
}

static int
ensure_win_picture(CompWin *w)
{
	if (w->picture != None)
		return 1;
	if (!w->mapped || w->a.class == InputOnly)
		return 0;

	XRenderPictFormat *fmt = XRenderFindVisualFormat(dpy, w->a.visual);
	if (!fmt)
		return 0;

	Pixmap pm = XCompositeNameWindowPixmap(dpy, w->id);
	if (pm == None)
		return 0;

	XRenderPictureAttributes pa;
	pa.subwindow_mode = IncludeInferiors;
	Picture pic = XRenderCreatePicture(dpy, pm, fmt, CPSubwindowMode, &pa);
	if (pic == None) {
		XFreePixmap(dpy, pm);
		return 0;
	}

	w->pixmap = pm;
	w->picture = pic;
	w->argb = (fmt->type == PictTypeDirect && fmt->direct.alphaMask != 0);
	return 1;
}

/*
 * Check that a 32-bit ARGB window's offscreen pixmap has actually been painted
 * with non-transparent content across its full bounds (both center and bottom-right),
 * preventing premature unfreeze on transparent/uninitialized or partial-size frames.
 */
static int
win_pixmap_ready(CompWin *w)
{
	if (!w->argb)
		return 1;
	if (!ensure_win_picture(w) || w->pixmap == None)
		return 0;

	int bw = w->a.border_width;
	int pts[2][2] = {
		{ bw + w->a.width / 2, bw + w->a.height / 2 },
		{ bw + (w->a.width > 16 ? w->a.width - 8 : w->a.width / 2),
		  bw + (w->a.height > 16 ? w->a.height - 8 : w->a.height / 2) }
	};
	for (int i = 0; i < 2; i++) {
		XImage *img = XGetImage(dpy, w->pixmap, pts[i][0], pts[i][1], 1, 1, AllPlanes, ZPixmap);
		if (!img)
			return 0;
		unsigned long px = XGetPixel(img, 0, 0);
		XDestroyImage(img);
		if (((px >> 24) & 0xFFUL) == 0)
			return 0;
	}
	return 1;
}

static void
unlink_win(CompWin *w)
{
	if (w->prev)
		w->prev->next = w->next;
	else
		win_head = w->next;
	if (w->next)
		w->next->prev = w->prev;
	else
		win_tail = w->prev;
	w->prev = w->next = NULL;
}

static void
append_win_top(CompWin *w)
{
	w->prev = win_tail;
	w->next = NULL;
	if (win_tail)
		win_tail->next = w;
	else
		win_head = w;
	win_tail = w;
}

static void
insert_win_above(CompWin *w, Window above_id)
{
	unlink_win(w);
	if (above_id == None) {
		w->prev = NULL;
		w->next = win_head;
		if (win_head)
			win_head->prev = w;
		else
			win_tail = w;
		win_head = w;
		return;
	}
	CompWin *ref = find_win(above_id);
	if (!ref) {
		append_win_top(w);
		return;
	}
	w->prev = ref;
	w->next = ref->next;
	if (ref->next)
		ref->next->prev = w;
	else
		win_tail = w;
	ref->next = w;
}

static void
update_root_tile(void)
{
	if (root_tile != None) {
		XRenderFreePicture(dpy, root_tile);
		root_tile = None;
	}

	Atom props[2] = { atom_xrootpmap, atom_esetroot };
	Pixmap pm = None;

	for (int i = 0; i < 2; i++) {
		Atom actual_type;
		int actual_format;
		unsigned long nitems, bytes_after;
		unsigned char *data = NULL;
		if (XGetWindowProperty(dpy, root, props[i], 0, 1, False, XA_PIXMAP,
		                       &actual_type, &actual_format, &nitems, &bytes_after,
		                       &data) == Success && data) {
			if (actual_type == XA_PIXMAP && actual_format == 32 && nitems == 1)
				pm = *(Pixmap *)data;
			XFree(data);
			if (pm != None)
				break;
		}
	}

	if (pm != None) {
		XRenderPictureAttributes pa;
		pa.repeat = RepeatNormal;
		root_tile = XRenderCreatePicture(dpy, pm, root_fmt, CPRepeat, &pa);
	}
}

static CompWin *
add_win(Window id, int initial_scan)
{
	if (id == overlay || id == root)
		return NULL;
	CompWin *existing = find_win(id);
	if (existing)
		return existing;

	XWindowAttributes wa;
	if (!XGetWindowAttributes(dpy, id, &wa))
		return NULL;

	CompWin *w = calloc(1, sizeof(CompWin));
	if (!w)
		return NULL;
	w->id = id;
	w->a = wa;
	w->mapped = (wa.map_state == IsViewable);
	if (wa.class != InputOnly) {
		XRenderPictFormat *fmt = XRenderFindVisualFormat(dpy, wa.visual);
		w->argb = (fmt && fmt->type == PictTypeDirect && fmt->direct.alphaMask != 0);
		XShapeSelectInput(dpy, id, ShapeNotifyMask);
		if (w->mapped) {
			w->damage = XDamageCreate(dpy, id, XDamageReportNonEmpty);
			XDamageSubtract(dpy, w->damage, None, None);
		}
	}
	append_win_top(w);
	if (!initial_scan && w->mapped)
		dirty = 1;
	return w;
}

static void
maybe_coalesce_on_hide(const CompWin *w, const char *reason)
{
	if (!is_normal_onscreen_win(w))
		return;
	if (count_other_normal_onscreen_wins(w) <= 0)
		return;
	long long now = now_ms();
	long long target = now + UNMAP_COALESCE_MS;
	if (target > coalesce_until_ms)
		coalesce_until_ms = target;
	if (verbose) {
		fprintf(stderr, "dwmcomp: coalesce on %s win=0x%lx until=+35ms t=%lld\n",
		        reason, w->id, now);
		fflush(stderr);
	}
}

static void
destroy_win(Window id)
{
	CompWin *w = find_win(id);
	if (!w)
		return;
	maybe_coalesce_on_hide(w, "destroy");
	release_win_pixmap(w);
	release_win_damage(w);
	unlink_win(w);
	free(w);
	dirty = 1;
}

static void
handle_map(Window id)
{
	CompWin *w = find_win(id);
	if (!w)
		w = add_win(id, 0);
	if (!w)
		return;

	XWindowAttributes wa;
	if (XGetWindowAttributes(dpy, id, &wa))
		w->a = wa;
	w->mapped = 1;
	release_win_pixmap(w);
	release_win_damage(w);

	if (w->a.class != InputOnly) {
		XRenderPictFormat *fmt = XRenderFindVisualFormat(dpy, w->a.visual);
		w->argb = (fmt && fmt->type == PictTypeDirect && fmt->direct.alphaMask != 0);
		w->damage = XDamageCreate(dpy, id, XDamageReportNonEmpty);
		/* Synchronize and discard the initial server-side allocation damage. */
		drain_win_damage(w);
	}

	if (is_normal_onscreen_win(w)) {
		long long now = now_ms();
		w->waiting_paint = 1;
		w->damage_count = 0;
		w->freeze_start_ms = now;
		w->wait_deadline_ms = now + FREEZE_TIMEOUT_MS;
		if (verbose) {
			fprintf(stderr, "dwmcomp: freeze on map win=0x%lx geom=%dx%d+%d+%d argb=%d t=%lld\n",
			        w->id, w->a.width, w->a.height, w->a.x, w->a.y, w->argb, now);
			fflush(stderr);
		}
	}
	dirty = 1;
}

static void
handle_unmap(Window id)
{
	CompWin *w = find_win(id);
	if (!w)
		return;
	maybe_coalesce_on_hide(w, "unmap");
	w->mapped = 0;
	w->waiting_paint = 0;
	w->wait_deadline_ms = 0;
	release_win_pixmap(w);
	release_win_damage(w);
	dirty = 1;
}

static void
handle_configure(XConfigureEvent *ev)
{
	CompWin *w = find_win(ev->window);
	if (!w)
		return;

	int was_onscreen = is_normal_onscreen_win(w);
	int old_area = w->a.width * w->a.height;
	int size_changed = (w->a.width != ev->width || w->a.height != ev->height ||
	                    w->a.border_width != ev->border_width);

	w->a.x = ev->x;
	w->a.y = ev->y;
	w->a.width = ev->width;
	w->a.height = ev->height;
	w->a.border_width = ev->border_width;
	w->a.override_redirect = ev->override_redirect;

	insert_win_above(w, ev->above);

	if (size_changed) {
		release_win_pixmap(w);
		if (is_normal_onscreen_win(w)) {
			long long now = now_ms();
			int new_area = w->a.width * w->a.height;
			if (new_area < old_area) {
				long long target = now + SHRINK_COALESCE_MS;
				if (target > coalesce_until_ms)
					coalesce_until_ms = target;
			}
			w->waiting_paint = 1;
			w->damage_count = 0;
			w->freeze_start_ms = now;
			w->wait_deadline_ms = now + RESIZE_TIMEOUT_MS;
			drain_win_damage(w);
			if (verbose) {
				fprintf(stderr, "dwmcomp: freeze on resize win=0x%lx geom=%dx%d+%d+%d t=%lld\n",
				        w->id, w->a.width, w->a.height, w->a.x, w->a.y, now);
				fflush(stderr);
			}
		}
	} else if (was_onscreen && !win_on_screen(w)) {
		/* Window moved offscreen (e.g. hidden/tagged away); coalesce if siblings remain. */
		if (count_other_normal_onscreen_wins(w) > 0) {
			long long target = now_ms() + SHRINK_COALESCE_MS;
			if (target > coalesce_until_ms)
				coalesce_until_ms = target;
		}
	}

	if (w->waiting_paint && !win_on_screen(w)) {
		w->waiting_paint = 0;
		w->wait_deadline_ms = 0;
	}
	dirty = 1;
}

static void
handle_damage(XDamageNotifyEvent *ev)
{
	CompWin *w = find_win(ev->drawable);
	if (!w)
		return;
	if (w->damage != None)
		XDamageSubtract(dpy, w->damage, None, None);

	if (w->waiting_paint) {
		long long now = now_ms();
		long long elapsed = now - w->freeze_start_ms;
		w->damage_count++;

		/* Require full-window damage and non-transparent ARGB content before unfreezing. */
		int full_area = (ev->area.width >= w->a.width && ev->area.height >= w->a.height);
		if (!full_area || !win_pixmap_ready(w)) {
			if (verbose) {
				fprintf(stderr, "dwmcomp: wait more win=0x%lx damage#%d area=%dx%d/%dx%d dt=%lldms\n",
				        w->id, w->damage_count, ev->area.width, ev->area.height,
				        w->a.width, w->a.height, elapsed);
				fflush(stderr);
			}
			return;
		}
		if (verbose) {
			fprintf(stderr, "dwmcomp: unfreeze win=0x%lx on damage#%d area=%dx%d+%d+%d dt=%lldms t=%lld\n",
			        w->id, w->damage_count, ev->area.width, ev->area.height,
			        ev->area.x, ev->area.y, elapsed, now);
			fflush(stderr);
		}
		w->waiting_paint = 0;
		w->wait_deadline_ms = 0;
	}
	dirty = 1;
}

static int
is_frozen(long long now, int *next_timeout_ms)
{
	int frozen = 0;
	int min_rem = -1;

	if (coalesce_until_ms > now) {
		frozen = 1;
		min_rem = (int)(coalesce_until_ms - now);
	} else {
		coalesce_until_ms = 0;
	}

	for (CompWin *w = win_head; w; w = w->next) {
		if (!w->waiting_paint)
			continue;
		if (now >= w->wait_deadline_ms) {
			w->waiting_paint = 0;
			w->wait_deadline_ms = 0;
			if (verbose) {
				fprintf(stderr, "dwmcomp: unfreeze win=0x%lx on timeout t=%lld\n", w->id, now);
				fflush(stderr);
			}
			continue;
		}
		frozen = 1;
		int rem = (int)(w->wait_deadline_ms - now);
		if (min_rem < 0 || rem < min_rem)
			min_rem = rem;
	}

	*next_timeout_ms = min_rem;
	return frozen;
}

static void
paint_all(void)
{
	/*
	 * Grab the server and sync before painting: if dwm has already issued a
	 * Configure/Map/Unmap on the server that hasn't been drained from our queue
	 * yet, abort this paint and process those events first (so freeze engages
	 * before we ever render a desynced intermediate frame).
	 */
	XGrabServer(dpy);
	XSync(dpy, False);
	if (XPending(dpy)) {
		XUngrabServer(dpy);
		XFlush(dpy);
		return;
	}

	if (root_tile != None) {
		XRenderComposite(dpy, PictOpSrc, root_tile, None, back_pic,
		                 0, 0, 0, 0, 0, 0, sw, sh);
	} else {
		XRenderColor bg = { 0x1e00, 0x1e00, 0x1e00, 0xffff };
		XRenderFillRectangle(dpy, PictOpSrc, back_pic, &bg, 0, 0, sw, sh);
	}

	for (CompWin *w = win_head; w; w = w->next) {
		if (!w->mapped || w->a.class == InputOnly || !win_on_screen(w))
			continue;
		if (!ensure_win_picture(w))
			continue;

		int bw = w->a.border_width;
		int x = w->a.x;
		int y = w->a.y;
		int full_w = w->a.width + 2 * bw;
		int full_h = w->a.height + 2 * bw;

		XserverRegion reg = XFixesCreateRegionFromWindow(dpy, w->id, WindowRegionBounding);
		XFixesTranslateRegion(dpy, reg, x + bw, y + bw);
		XFixesSetPictureClipRegion(dpy, back_pic, 0, 0, reg);

		int op = w->argb ? PictOpOver : PictOpSrc;
		XRenderComposite(dpy, op, w->picture, None, back_pic,
		                 0, 0, 0, 0, x, y, full_w, full_h);

		XFixesSetPictureClipRegion(dpy, back_pic, 0, 0, None);
		XFixesDestroyRegion(dpy, reg);
	}

	XRenderComposite(dpy, PictOpSrc, back_pic, None, overlay_pic,
	                 0, 0, 0, 0, 0, 0, sw, sh);
	XUngrabServer(dpy);
	XFlush(dpy);
	dirty = 0;
}

static void
process_event(XEvent *ev)
{
	if (ev->type == damage_event_base + XDamageNotify) {
		handle_damage((XDamageNotifyEvent *)ev);
		return;
	}
	if (ev->type == shape_event_base + ShapeNotify) {
		dirty = 1;
		return;
	}

	switch (ev->type) {
	case CreateNotify:
		add_win(ev->xcreatewindow.window, 0);
		break;
	case DestroyNotify:
		destroy_win(ev->xdestroywindow.window);
		break;
	case MapNotify:
		handle_map(ev->xmap.window);
		break;
	case UnmapNotify:
		handle_unmap(ev->xunmap.window);
		break;
	case ConfigureNotify:
		handle_configure(&ev->xconfigure);
		break;
	case ReparentNotify:
		if (ev->xreparent.parent == root)
			add_win(ev->xreparent.window, 0);
		else
			destroy_win(ev->xreparent.window);
		break;
	case CirculateNotify:
		if (ev->xcirculate.window != overlay) {
			CompWin *w = find_win(ev->xcirculate.window);
			if (w) {
				if (ev->xcirculate.place == PlaceOnTop) {
					unlink_win(w);
					append_win_top(w);
				} else {
					insert_win_above(w, None);
				}
				dirty = 1;
			}
		}
		break;
	case PropertyNotify:
		if (ev->xproperty.window == root &&
		    (ev->xproperty.atom == atom_xrootpmap || ev->xproperty.atom == atom_esetroot)) {
			update_root_tile();
			dirty = 1;
		}
		break;
	default:
		break;
	}
}

int
main(int argc, char **argv)
{
	for (int i = 1; i < argc; i++) {
		if (strcmp(argv[i], "-v") == 0)
			verbose = 1;
	}

	signal(SIGINT, on_signal);
	signal(SIGTERM, on_signal);

	dpy = XOpenDisplay(NULL);
	if (!dpy) {
		fprintf(stderr, "dwmcomp: failed to open X display\n");
		return 1;
	}
	XSetErrorHandler(xerror_ignore);

	scr = DefaultScreen(dpy);
	root = RootWindow(dpy, scr);
	sw = DisplayWidth(dpy, scr);
	sh = DisplayHeight(dpy, scr);
	root_depth = DefaultDepth(dpy, scr);

	int dummy;
	if (!XCompositeQueryExtension(dpy, &dummy, &dummy) ||
	    !XDamageQueryExtension(dpy, &damage_event_base, &dummy) ||
	    !XFixesQueryExtension(dpy, &dummy, &dummy) ||
	    !XRenderQueryExtension(dpy, &dummy, &dummy) ||
	    !XShapeQueryExtension(dpy, &shape_event_base, &dummy)) {
		fprintf(stderr, "dwmcomp: required X11 extensions missing\n");
		XCloseDisplay(dpy);
		return 1;
	}

	atom_xrootpmap = XInternAtom(dpy, "_XROOTPMAP_ID", False);
	atom_esetroot = XInternAtom(dpy, "ESETROOT_PMAP_ID", False);

	root_fmt = XRenderFindVisualFormat(dpy, DefaultVisual(dpy, scr));
	if (!root_fmt) {
		fprintf(stderr, "dwmcomp: failed to find root visual format\n");
		XCloseDisplay(dpy);
		return 1;
	}

	XGrabServer(dpy);
	XCompositeRedirectSubwindows(dpy, root, CompositeRedirectManual);
	overlay = XCompositeGetOverlayWindow(dpy, root);

	XserverRegion empty_reg = XFixesCreateRegion(dpy, NULL, 0);
	XFixesSetWindowShapeRegion(dpy, overlay, ShapeInput, 0, 0, empty_reg);
	XFixesDestroyRegion(dpy, empty_reg);

	XRenderPictureAttributes pa;
	pa.subwindow_mode = IncludeInferiors;
	overlay_pic = XRenderCreatePicture(dpy, overlay, root_fmt, CPSubwindowMode, &pa);

	back_pixmap = XCreatePixmap(dpy, root, sw, sh, root_depth);
	back_pic = XRenderCreatePicture(dpy, back_pixmap, root_fmt, 0, NULL);

	XSelectInput(dpy, root, SubstructureNotifyMask | PropertyChangeMask);
	update_root_tile();

	Window r_ret, p_ret, *children = NULL;
	unsigned int nchildren = 0;
	if (XQueryTree(dpy, root, &r_ret, &p_ret, &children, &nchildren)) {
		for (unsigned int i = 0; i < nchildren; i++)
			add_win(children[i], 1);
		if (children)
			XFree(children);
	}
	XUngrabServer(dpy);
	XSync(dpy, False);

	paint_all();

	int xfd = ConnectionNumber(dpy);
	while (running) {
		while (running && XPending(dpy)) {
			XEvent ev;
			XNextEvent(dpy, &ev);
			process_event(&ev);
		}
		if (!running)
			break;

		int timeout_ms = -1;
		long long now = now_ms();
		if (dirty && !is_frozen(now, &timeout_ms)) {
			paint_all();
			continue;
		}
		if (!dirty)
			is_frozen(now, &timeout_ms);

		fd_set fds;
		FD_ZERO(&fds);
		FD_SET(xfd, &fds);
		struct timeval tv;
		struct timeval *tvp = NULL;
		if (timeout_ms >= 0) {
			tv.tv_sec = timeout_ms / 1000;
			tv.tv_usec = (timeout_ms % 1000) * 1000;
			tvp = &tv;
		}
		int ready = select(xfd + 1, &fds, NULL, NULL, tvp);
		if (ready < 0) {
			if (errno == EINTR)
				continue;
			break;
		}
		if (ready == 0 && dirty) {
			int next_t = -1;
			if (!is_frozen(now_ms(), &next_t))
				paint_all();
		}
	}

	while (win_head)
		destroy_win(win_head->id);
	if (root_tile != None)
		XRenderFreePicture(dpy, root_tile);
	if (back_pic != None)
		XRenderFreePicture(dpy, back_pic);
	if (back_pixmap != None)
		XFreePixmap(dpy, back_pixmap);
	if (overlay_pic != None)
		XRenderFreePicture(dpy, overlay_pic);
	XCompositeUnredirectSubwindows(dpy, root, CompositeRedirectManual);
	XCompositeReleaseOverlayWindow(dpy, root);
	XSync(dpy, False);
	XCloseDisplay(dpy);
	return 0;
}
