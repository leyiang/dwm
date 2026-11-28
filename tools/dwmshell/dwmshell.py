#!/usr/bin/env python3
"""
dwmshell - Lightweight Desktop Widget Shell for dwm + dwmcomp.

Design principles:
- Zero changes to dwm (uses override_redirect ARGB windows kept pinned at the
  bottom of the X11 root stack, strictly below all normal windows and barwin).
- Works seamlessly with dwmcomp (32-bit ARGB transparency via PictOpOver;
  override_redirect windows never trigger dwmcomp's map/resize freeze).
- Drop-in HTML/CSS/JS widgets with live hot-reload + localhost JSON HTTP API
  for scripts and AI agents.
"""

from __future__ import annotations

import argparse
import http.server
import json
import mimetypes
import os
import posixpath
import signal
import socketserver
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkX11", "3.0")
for _wk_ver in ("4.1", "4.0"):
    try:
        gi.require_version("WebKit2", _wk_ver)
        break
    except ValueError:
        continue
else:
    raise RuntimeError("WebKit2 (4.1 or 4.0) GI typelib is required")

from gi.repository import Gdk, GdkX11, GLib, Gtk, WebKit2  # noqa: E402
from Xlib import X, display as xdisplay  # noqa: E402


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
BUILTIN_WIDGETS_DIR = SCRIPT_DIR / "widgets"
DEFAULT_USER_WIDGETS_DIR = Path.home() / ".config" / "dwmshell" / "widgets"
DEFAULT_STATE_DIR = Path.home() / ".local" / "state" / "dwmshell"


def load_env_value(key: str) -> str:
    """Look up a secret/config key from process env or .env files."""
    val = os.environ.get(key) or os.environ.get(key.upper())
    if val:
        return val.strip()
    candidates = [
        Path.home() / ".config" / "dwmshell" / ".env",
        REPO_ROOT / ".env",
        Path.cwd() / ".env",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip().lower() == key.lower():
                    return v.strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


BRIDGE_JS_TEMPLATE = r"""
(function() {
  const WID = __WIDGET_ID__;
  const listeners = new Set();
  const occListeners = new Set();
  let lastData = __INITIAL_DATA__;
  let occupied = __INITIAL_OCCUPIED__;

  window.__dwmshellEmitData = function(data) {
    lastData = data;
    for (const fn of listeners) {
      try { fn(data); } catch (e) { console.error(e); }
    }
    window.dispatchEvent(new CustomEvent('dwmshell:data', { detail: data }));
  };

  window.__dwmshellSetOccupied = function(isOcc) {
    occupied = !!isOcc;
    if (document.documentElement) {
      document.documentElement.classList.toggle('dwmshell-occupied', occupied);
    }
    for (const fn of occListeners) {
      try { fn(occupied); } catch (e) { console.error(e); }
    }
  };

  window.dwmshell = {
    id: WID,
    getData: () => lastData,
    isOccupied: () => occupied,
    onData: (fn, opts) => {
      listeners.add(fn);
      if (opts && opts.immediate && lastData !== null && lastData !== undefined) {
        try { fn(lastData); } catch (e) { console.error(e); }
      }
      return () => listeners.delete(fn);
    },
    onOccupied: (fn) => {
      occListeners.add(fn);
      try { fn(occupied); } catch (e) { console.error(e); }
      return () => occListeners.delete(fn);
    },
    async loadState() {
      const r = await fetch(`/api/widgets/${encodeURIComponent(WID)}/state`, { cache: 'no-store' });
      if (!r.ok) return {};
      return await r.json();
    },
    async saveState(obj) {
      const r = await fetch(`/api/widgets/${encodeURIComponent(WID)}/state`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(obj ?? {}),
      });
      return r.ok;
    },
    async getSystem() {
      const r = await fetch('/api/system', { cache: 'no-store' });
      if (!r.ok) return {};
      return await r.json();
    },
  };

  document.addEventListener('DOMContentLoaded', () => {
    document.documentElement.classList.toggle('dwmshell-occupied', occupied);
  });
})();
"""


def read_system_stats() -> dict[str, Any]:
    """Read lightweight Linux CPU/memory/uptime stats from /proc."""
    mem_total = 0
    mem_avail = 0
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    mem_avail = int(line.split()[1])
    except OSError:
        pass

    uptime_sec = 0.0
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as f:
            uptime_sec = float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        pass

    load1 = load5 = load15 = 0.0
    try:
        load1, load5, load15 = os.getloadavg()
    except OSError:
        pass

    cpu_stat = (0, 0)
    try:
        with open("/proc/stat", "r", encoding="utf-8") as f:
            parts = f.readline().split()
            if parts and parts[0] == "cpu":
                vals = [int(v) for v in parts[1:]]
                idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
                total = sum(vals)
                cpu_stat = (idle, total)
    except (OSError, ValueError):
        pass

    mem_used = max(mem_total - mem_avail, 0)
    mem_pct = round((mem_used / mem_total) * 100.0, 1) if mem_total > 0 else 0.0
    return {
        "mem_total_mb": round(mem_total / 1024.0, 1),
        "mem_used_mb": round(mem_used / 1024.0, 1),
        "mem_percent": mem_pct,
        "uptime_sec": int(uptime_sec),
        "loadavg": [round(load1, 2), round(load5, 2), round(load15, 2)],
        "cpu_raw": cpu_stat,
        "ts": int(time.time()),
    }


def _safe_widget_id(wid: str) -> str | None:
    if not wid or "/" in wid or "\\" in wid or wid in (".", ".."):
        return None
    if not all(c.isalnum() or c in "-_" for c in wid):
        return None
    return wid


def _dir_signature(path: Path) -> tuple[tuple[str, int, int], ...]:
    """Compute a lightweight mtime+size signature for hot-reload detection."""
    entries: list[tuple[str, int, int]] = []
    if not path.is_dir():
        return ()
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for fname in sorted(files):
            fp = Path(root) / fname
            try:
                st = fp.stat()
                rel = str(fp.relative_to(path))
                entries.append((rel, int(st.st_mtime_ns), int(st.st_size)))
            except OSError:
                continue
    return tuple(entries)


class WidgetInstance:
    def __init__(
        self,
        shell: "DwmShell",
        wid: str,
        widget_dir: Path,
        meta: dict[str, Any],
        signature: tuple[tuple[str, int, int], ...],
    ) -> None:
        self.shell = shell
        self.wid = wid
        self.widget_dir = widget_dir
        self.meta = meta
        self.signature = signature
        self.rev = 1
        self.xid: int | None = None
        self.data: Any = meta.get("data")

        self.win = Gtk.Window(type=Gtk.WindowType.POPUP)
        self.win.set_title(f"dwmshell:{wid}")
        self.win.set_decorated(False)
        self.win.set_skip_taskbar_hint(True)
        self.win.set_skip_pager_hint(True)
        self.win.set_accept_focus(False)
        self.win.set_app_paintable(True)

        screen = self.win.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            self.win.set_visual(visual)

        css = Gtk.CssProvider()
        css.load_from_data(b"window { background-color: transparent; }")
        self.win.get_style_context().add_provider(
            css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self.webview = WebKit2.WebView.new_with_related_view(self.shell.anchor_webview)
        settings = self.webview.get_settings()
        settings.set_enable_developer_extras(False)
        settings.set_enable_javascript(True)
        try:
            settings.set_hardware_acceleration_policy(
                WebKit2.HardwareAccelerationPolicy.NEVER
            )
        except Exception:
            pass

        self.webview.set_background_color(Gdk.RGBA(0.0, 0.0, 0.0, 0.0))
        self.webview.connect("context-menu", lambda *_args: True)

        self.win.add(self.webview)
        self.apply_geometry(meta)
        self.win.show_all()

        gdk_win = self.win.get_window()
        if gdk_win is not None:
            self.xid = int(gdk_win.get_xid())

        self.reload_content()

    def _eval_js(self, js: str) -> None:
        if hasattr(self.webview, "evaluate_javascript"):
            self.webview.evaluate_javascript(js, -1, None, None, None, None)
        else:
            self.webview.run_javascript(js, None, None, None)

    def bridge_script_html(self) -> str:
        js = (
            BRIDGE_JS_TEMPLATE.replace("__WIDGET_ID__", json.dumps(self.wid))
            .replace("__INITIAL_DATA__", json.dumps(self.data))
            .replace("__INITIAL_OCCUPIED__", "true" if self.shell.occupied else "false")
        )
        return f"<script>{js}</script>"

    def apply_geometry(self, meta: dict[str, Any]) -> None:
        self.meta = meta
        mx, my, sw, sh = self.shell.monitor_geometry()
        w = max(int(meta.get("width", 280)), 40)
        h = max(int(meta.get("height", 140)), 40)
        raw_x = int(meta.get("x", 32))
        raw_y = int(meta.get("y", 48))

        x = (sw + raw_x - w) if raw_x < 0 else raw_x
        y = (sh + raw_y - h) if raw_y < 0 else raw_y
        x = mx + max(0, min(x, max(sw - w, 0)))
        y = my + max(0, min(y, max(sh - h, 0)))

        self.win.set_size_request(w, h)
        self.win.resize(w, h)
        self.win.move(x, y)

    def reload_content(self) -> None:
        self.rev += 1
        entry = str(self.meta.get("entry", "index.html")).lstrip("/")
        url = f"http://127.0.0.1:{self.shell.port}/w/{urllib.parse.quote(self.wid)}/{entry}?v={self.rev}"
        self.webview.load_uri(url)

    def push_data(self, data: Any) -> None:
        self.data = data
        js = f"window.__dwmshellEmitData && window.__dwmshellEmitData({json.dumps(data)});"
        self._eval_js(js)

    def set_occupied(self, occupied: bool) -> None:
        js = f"window.__dwmshellSetOccupied && window.__dwmshellSetOccupied({'true' if occupied else 'false'});"
        self._eval_js(js)

    def destroy(self) -> None:
        self.win.destroy()


class ShellHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class DwmShell:
    def __init__(
        self,
        port: int,
        user_widgets_dir: Path,
        builtin_widgets_dir: Path | None,
        state_dir: Path,
        verbose: bool = False,
    ) -> None:
        self.port = port
        self.user_widgets_dir = user_widgets_dir
        self.builtin_widgets_dir = builtin_widgets_dir
        self.state_dir = state_dir
        self.verbose = verbose

        self.user_widgets_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.widgets: dict[str, WidgetInstance] = {}
        self.widget_dirs: dict[str, Path] = {}
        self.occupied = False
        self._lower_scheduled = False
        self._prev_cpu: tuple[int, int] | None = None
        self._aqi_cache: tuple[float, dict[str, Any]] | None = None
        self._lock = threading.RLock()

        # Align GTK/WebKit Xft DPI with GDK logical resolution to avoid double-scaling
        # fonts when GDK_SCALE>1 is combined with high Xft.dpi (e.g. GDK_SCALE=2 + Xft.dpi=196).
        gdk_screen = Gdk.Screen.get_default()
        gtk_settings = Gtk.Settings.get_default()
        if gdk_screen is not None and gtk_settings is not None:
            res = gdk_screen.get_resolution()
            if res and res > 0:
                gtk_settings.set_property("gtk-xft-dpi", int(round(res * 1024)))

        # Single anchor WebView so all widget views share ONE WebKitWebProcess.
        WebKit2.WebContext.get_default().set_cache_model(
            WebKit2.CacheModel.DOCUMENT_VIEWER
        )
        self.anchor_webview = WebKit2.WebView()

        # X11 connection for bottom-stacking and active-window observation
        self.xdisp = xdisplay.Display()
        self.xroot = self.xdisp.screen().root
        self.atom_active = self.xdisp.intern_atom("_NET_ACTIVE_WINDOW")
        self.xroot.change_attributes(
            event_mask=X.SubstructureNotifyMask | X.PropertyChangeMask
        )
        self.xdisp.flush()
        self.occupied = self._query_occupied()

        self.httpd = self._start_http_server()

    def log(self, msg: str) -> None:
        if self.verbose:
            print(f"dwmshell: {msg}", flush=True)

    def monitor_geometry(self) -> tuple[int, int, int, int]:
        """Return primary monitor (x, y, w, h) in GTK logical coordinates (HiDPI-safe)."""
        gdk_disp = Gdk.Display.get_default()
        if gdk_disp is not None:
            mon = gdk_disp.get_primary_monitor() or gdk_disp.get_monitor(0)
            if mon is not None:
                geo = mon.get_geometry()
                return int(geo.x), int(geo.y), int(geo.width), int(geo.height)
        scr = self.xdisp.screen()
        return 0, 0, int(scr.width_in_pixels), int(scr.height_in_pixels)

    def _query_occupied(self) -> bool:
        try:
            prop = self.xroot.get_full_property(self.atom_active, X.AnyPropertyType)
            if prop and len(prop.value) > 0 and int(prop.value[0]) != 0:
                return True
        except Exception:
            pass
        return False

    def _widget_xids(self) -> set[int]:
        return {inst.xid for inst in self.widgets.values() if inst.xid is not None}

    def schedule_lower(self) -> None:
        if not self._lower_scheduled:
            self._lower_scheduled = True
            GLib.idle_add(self._ensure_bottom_layer)

    def _ensure_bottom_layer(self) -> bool:
        self._lower_scheduled = False
        xids = self._widget_xids()
        if not xids:
            return False

        try:
            children = [int(w.id) for w in self.xroot.query_tree().children]
        except Exception:
            return False

        # Check whether all widget windows sit strictly below every non-widget window.
        seen_non_widget = False
        to_lower: list[int] = []
        for cid in children:
            if cid in xids:
                if seen_non_widget:
                    to_lower.append(cid)
            else:
                seen_non_widget = True

        if to_lower:
            for cid in to_lower:
                try:
                    w = self.xdisp.create_resource_object("window", cid)
                    w.configure(stack_mode=X.Below)
                except Exception:
                    pass
            self.xdisp.flush()
            self.log(f"lowered {len(to_lower)} widget window(s) to desktop bottom")
        return False

    def _on_x_event(self, _source: int, _cond: GLib.IOCondition) -> bool:
        xids = self._widget_xids()
        need_lower = False
        active_changed = False

        while self.xdisp.pending_events():
            ev = self.xdisp.next_event()
            etype = ev.type
            if etype in (X.MapNotify, X.ConfigureNotify, X.CirculateNotify):
                wid = int(ev.window.id)
                if wid not in xids:
                    need_lower = True
            elif etype == X.PropertyNotify:
                if ev.atom == self.atom_active:
                    active_changed = True

        if need_lower:
            self.schedule_lower()

        if active_changed:
            new_occ = self._query_occupied()
            if new_occ != self.occupied:
                self.occupied = new_occ
                self.log(f"occupied={self.occupied}")
                for inst in self.widgets.values():
                    inst.set_occupied(self.occupied)

        return True

    def discover_widget_sources(self) -> dict[str, tuple[Path, dict[str, Any], tuple[tuple[str, int, int], ...]]]:
        """Discover widgets from built-in and user directories (user overrides built-in)."""
        found: dict[str, tuple[Path, dict[str, Any], tuple[tuple[str, int, int], ...]]] = {}
        search_dirs: list[Path] = []
        if self.builtin_widgets_dir and self.builtin_widgets_dir.is_dir():
            search_dirs.append(self.builtin_widgets_dir)
        if self.user_widgets_dir.is_dir():
            search_dirs.append(self.user_widgets_dir)

        for base in search_dirs:
            for child in sorted(base.iterdir()):
                if not child.is_dir():
                    continue
                wid = _safe_widget_id(child.name)
                if not wid:
                    continue
                meta_path = child / "widget.json"
                if not meta_path.is_file():
                    continue
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    self.log(f"skip invalid widget.json for {wid}: {exc}")
                    continue
                if not isinstance(meta, dict):
                    continue
                if not meta.get("enabled", True):
                    found.pop(wid, None)
                    continue
                entry = str(meta.get("entry", "index.html")).lstrip("/")
                if not (child / entry).is_file():
                    continue
                found[wid] = (child, meta, _dir_signature(child))
        return found

    def sync_widgets(self) -> bool:
        discovered = self.discover_widget_sources()

        with self._lock:
            self.widget_dirs = {wid: item[0] for wid, item in discovered.items()}

        # Remove deleted or disabled widgets
        for wid in list(self.widgets.keys()):
            if wid not in discovered:
                self.log(f"remove widget {wid}")
                self.widgets.pop(wid).destroy()

        # Add new widgets or hot-reload changed widgets
        for wid, (wdir, meta, sig) in discovered.items():
            existing = self.widgets.get(wid)
            if existing is None:
                self.log(f"load widget {wid} from {wdir}")
                inst = WidgetInstance(self, wid, wdir, meta, sig)
                self.widgets[wid] = inst
                self.schedule_lower()
            elif existing.widget_dir != wdir or existing.signature != sig:
                self.log(f"reload widget {wid}")
                existing.widget_dir = wdir
                existing.signature = sig
                if "data" in meta:
                    existing.data = meta["data"]
                existing.apply_geometry(meta)
                existing.reload_content()
                self.schedule_lower()

        return True

    def get_system_snapshot(self) -> dict[str, Any]:
        stats = read_system_stats()
        idle, total = stats.pop("cpu_raw")
        cpu_pct = 0.0
        with self._lock:
            if self._prev_cpu is not None:
                prev_idle, prev_total = self._prev_cpu
                d_total = total - prev_total
                d_idle = idle - prev_idle
                if d_total > 0:
                    cpu_pct = round((1.0 - d_idle / d_total) * 100.0, 1)
            self._prev_cpu = (idle, total)
        stats["cpu_percent"] = max(0.0, min(cpu_pct, 100.0))
        return stats

    def get_aqi_snapshot(self, force_refresh: bool = False) -> tuple[int, dict[str, Any]]:
        now = time.monotonic()
        with self._lock:
            if not force_refresh and self._aqi_cache is not None:
                cached_at, cached_data = self._aqi_cache
                if now - cached_at < 300.0:
                    return 200, cached_data

        token = load_env_value("aqi_token")
        if not token:
            return 500, {"error": "aqi_token not found in .env"}

        url = f"https://aqi.xunzhang.top/?auth={urllib.parse.quote(token, safe='')}"
        req = urllib.request.Request(url, headers={"User-Agent": "dwmshell/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            with self._lock:
                if self._aqi_cache is not None:
                    stale = dict(self._aqi_cache[1])
                    stale["_stale"] = True
                    return 200, stale
            return 502, {"error": str(exc)}

        if isinstance(data, dict):
            with self._lock:
                self._aqi_cache = (now, data)
            return 200, data
        return 502, {"error": "invalid upstream json"}

    def _state_file(self, wid: str) -> Path:
        return self.state_dir / f"{wid}.json"

    def read_widget_state(self, wid: str) -> Any:
        sf = self._state_file(wid)
        if not sf.is_file():
            return {}
        try:
            return json.loads(sf.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def write_widget_state(self, wid: str, obj: Any) -> None:
        sf = self._state_file(wid)
        sf.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

    def api_upsert_widget(self, wid: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        safe_id = _safe_widget_id(wid)
        if not safe_id:
            return 400, {"error": "invalid widget id"}

        wdir = self.user_widgets_dir / safe_id
        wdir.mkdir(parents=True, exist_ok=True)
        meta_path = wdir / "widget.json"
        meta: dict[str, Any] = {}
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}

        for key in ("title", "x", "y", "width", "height", "enabled", "entry", "data"):
            if key in payload:
                meta[key] = payload[key]
        meta.setdefault("title", safe_id)
        meta.setdefault("x", -32)
        meta.setdefault("y", 48)
        meta.setdefault("width", 280)
        meta.setdefault("height", 150)
        meta.setdefault("enabled", True)
        meta.setdefault("entry", "index.html")

        html = payload.get("html")
        if isinstance(html, str):
            (wdir / str(meta["entry"]).lstrip("/")).write_text(html, encoding="utf-8")

        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        GLib.idle_add(self.sync_widgets)
        return 200, {"ok": True, "id": safe_id, "meta": meta}

    def api_push_data(self, wid: str, data: Any) -> tuple[int, dict[str, Any]]:
        safe_id = _safe_widget_id(wid)
        if not safe_id:
            return 400, {"error": "invalid widget id"}

        def _apply() -> bool:
            inst = self.widgets.get(safe_id)
            if inst is not None:
                inst.push_data(data)
            return False

        GLib.idle_add(_apply)
        return 200, {"ok": True, "id": safe_id}

    def api_delete_widget(self, wid: str) -> tuple[int, dict[str, Any]]:
        safe_id = _safe_widget_id(wid)
        if not safe_id:
            return 400, {"error": "invalid widget id"}

        user_dir = self.user_widgets_dir / safe_id
        builtin_exists = bool(
            self.builtin_widgets_dir and (self.builtin_widgets_dir / safe_id / "widget.json").is_file()
        )
        if builtin_exists:
            user_dir.mkdir(parents=True, exist_ok=True)
            (user_dir / "widget.json").write_text(
                json.dumps({"enabled": False}, indent=2), encoding="utf-8"
            )
        elif user_dir.is_dir():
            for root, dirs, files in os.walk(user_dir, topdown=False):
                for fname in files:
                    (Path(root) / fname).unlink(missing_ok=True)
                for dname in dirs:
                    (Path(root) / dname).rmdir()
            user_dir.rmdir()

        GLib.idle_add(self.sync_widgets)
        return 200, {"ok": True, "id": safe_id}

    def _start_http_server(self) -> ShellHTTPServer:
        shell = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:
                if shell.verbose:
                    shell.log("http: " + (fmt % args))

            def _send_json(self, status: int, obj: Any) -> None:
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_json_body(self) -> Any:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0:
                    return {}
                raw = self.rfile.read(min(length, 2 * 1024 * 1024))
                return json.loads(raw.decode("utf-8"))

            def do_GET(self) -> None:
                parsed = urllib.parse.urlsplit(self.path)
                path = parsed.path

                if path == "/api/health":
                    self._send_json(200, {"ok": True, "widgets": list(shell.widgets.keys())})
                    return

                if path == "/api/system":
                    self._send_json(200, shell.get_system_snapshot())
                    return

                if path == "/api/aqi":
                    qs = urllib.parse.parse_qs(parsed.query)
                    force = qs.get("refresh", ["0"])[0] in ("1", "true", "yes")
                    status, data = shell.get_aqi_snapshot(force_refresh=force)
                    self._send_json(status, data)
                    return

                if path == "/api/widgets":
                    out = {}
                    for wid, inst in list(shell.widgets.items()):
                        out[wid] = {
                            "xid": hex(inst.xid) if inst.xid else None,
                            "dir": str(inst.widget_dir),
                            "meta": inst.meta,
                            "data": inst.data,
                        }
                    self._send_json(200, out)
                    return

                if path.startswith("/api/widgets/") and path.endswith("/state"):
                    wid = urllib.parse.unquote(path[len("/api/widgets/") : -len("/state")])
                    safe_id = _safe_widget_id(wid)
                    if not safe_id:
                        self._send_json(400, {"error": "invalid widget id"})
                        return
                    self._send_json(200, shell.read_widget_state(safe_id))
                    return

                if path.startswith("/w/"):
                    rest = path[3:]
                    parts = rest.split("/", 1)
                    if len(parts) != 2:
                        self.send_error(404)
                        return
                    wid = _safe_widget_id(urllib.parse.unquote(parts[0]))
                    rel = posixpath.normpath("/" + urllib.parse.unquote(parts[1])).lstrip("/")
                    if not wid or not rel or rel.startswith(".."):
                        self.send_error(403)
                        return
                    with shell._lock:
                        wdir = shell.widget_dirs.get(wid)
                    if not wdir:
                        self.send_error(404)
                        return
                    target = (wdir / rel).resolve()
                    try:
                        target.relative_to(wdir.resolve())
                    except ValueError:
                        self.send_error(403)
                        return
                    if not target.is_file():
                        self.send_error(404)
                        return
                    data = target.read_bytes()
                    ctype, _ = mimetypes.guess_type(str(target))
                    ctype = ctype or "application/octet-stream"
                    if ctype == "text/html":
                        inst = shell.widgets.get(wid)
                        if inst is not None:
                            html_text = data.decode("utf-8", errors="replace")
                            bridge_tag = inst.bridge_script_html()
                            lower = html_text.lower()
                            head_idx = lower.find("<head>")
                            if head_idx != -1:
                                insert_at = head_idx + len("<head>")
                                html_text = html_text[:insert_at] + bridge_tag + html_text[insert_at:]
                            else:
                                html_text = bridge_tag + html_text
                            data = html_text.encode("utf-8")
                    if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                        ctype = f"{ctype}; charset=utf-8"
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return

                self.send_error(404)

            def do_POST(self) -> None:
                parsed = urllib.parse.urlsplit(self.path)
                path = parsed.path
                try:
                    payload = self._read_json_body()
                except Exception as exc:
                    self._send_json(400, {"error": f"invalid json: {exc}"})
                    return

                if path == "/api/reload":
                    GLib.idle_add(shell.sync_widgets)
                    self._send_json(200, {"ok": True})
                    return

                if path.startswith("/api/widgets/") and path.endswith("/state"):
                    wid = urllib.parse.unquote(path[len("/api/widgets/") : -len("/state")])
                    safe_id = _safe_widget_id(wid)
                    if not safe_id:
                        self._send_json(400, {"error": "invalid widget id"})
                        return
                    shell.write_widget_state(safe_id, payload)
                    self._send_json(200, {"ok": True})
                    return

                if path.startswith("/api/widgets/") and path.endswith("/data"):
                    wid = urllib.parse.unquote(path[len("/api/widgets/") : -len("/data")])
                    status, resp = shell.api_push_data(wid, payload)
                    self._send_json(status, resp)
                    return

                if path.startswith("/api/widgets/"):
                    wid = urllib.parse.unquote(path[len("/api/widgets/") :])
                    if not isinstance(payload, dict):
                        self._send_json(400, {"error": "payload must be json object"})
                        return
                    status, resp = shell.api_upsert_widget(wid, payload)
                    self._send_json(status, resp)
                    return

                self._send_json(404, {"error": "not found"})

            def do_DELETE(self) -> None:
                parsed = urllib.parse.urlsplit(self.path)
                path = parsed.path
                if path.startswith("/api/widgets/"):
                    wid = urllib.parse.unquote(path[len("/api/widgets/") :])
                    status, resp = shell.api_delete_widget(wid)
                    self._send_json(status, resp)
                    return
                self._send_json(404, {"error": "not found"})

        httpd = ShellHTTPServer(("127.0.0.1", self.port), Handler)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        self.log(f"http api listening on http://127.0.0.1:{self.port}")
        return httpd

    def run(self) -> None:
        self.sync_widgets()
        GLib.io_add_watch(self.xdisp.fileno(), GLib.IO_IN, self._on_x_event)
        GLib.timeout_add(3000, self.sync_widgets)

        def _quit(*_args: Any) -> bool:
            self.shutdown()
            Gtk.main_quit()
            return False

        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, _quit)
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, _quit)

        Gtk.main()

    def shutdown(self) -> None:
        self.log("shutting down")
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass
        for inst in list(self.widgets.values()):
            inst.destroy()
        self.widgets.clear()
        try:
            self.xdisp.close()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="dwmshell desktop widget runtime")
    parser.add_argument("--port", type=int, default=17777, help="Localhost API port (default: 17777)")
    parser.add_argument(
        "--widgets-dir",
        type=Path,
        default=DEFAULT_USER_WIDGETS_DIR,
        help=f"User widgets directory (default: {DEFAULT_USER_WIDGETS_DIR})",
    )
    parser.add_argument(
        "--no-builtin",
        action="store_true",
        help="Do not load built-in starter widgets from tools/dwmshell/widgets",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=DEFAULT_STATE_DIR,
        help=f"Widget state directory (default: {DEFAULT_STATE_DIR})",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    # Improve stability in software-rendered/VM X11 environments
    os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")

    shell = DwmShell(
        port=args.port,
        user_widgets_dir=args.widgets_dir,
        builtin_widgets_dir=None if args.no_builtin else BUILTIN_WIDGETS_DIR,
        state_dir=args.state_dir,
        verbose=args.verbose,
    )
    shell.run()


if __name__ == "__main__":
    main()
