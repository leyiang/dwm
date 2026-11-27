#!/usr/bin/env python3
"""VM integration check: native apps launched onto background workspaces without disturbing foreground."""

import os
from pathlib import Path
import shutil
import subprocess as S
import sys
import tempfile
import threading
import time


def app(kind, result, present=False):
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import GLib, Gtk

    window = Gtk.Window(title=f'DwmNativeProbe-{kind}')
    window.set_default_size(400, 220)
    entry = Gtk.Entry()
    entry.connect('changed', lambda _: Path(result + '.text').write_text(entry.get_text()))
    window.add(entry)
    window.connect('destroy', Gtk.main_quit)
    window.show_all()
    entry.grab_focus()
    if present:
        # Deliberately emit _NET_ACTIVE_WINDOW shortly after mapping to verify dwm blocks focus theft.
        GLib.timeout_add(150, lambda: (window.present(), False)[1])
    Gtk.main()


def run(*command, env=None):
    return S.check_output(command, env=env, text=True).strip()


def wait_for(predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError('timed out waiting for test condition')


def find_window(title):
    result = S.run(
        ['xdotool', 'search', '--name', '^' + title + '$'],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines[-1] if lines else None


def get_desktop(win_id):
    result = S.run(
        ['xprop', '-id', win_id, '_NET_WM_DESKTOP'],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0 or '=' not in result.stdout:
        return None
    return int(result.stdout.rsplit('=', 1)[1].strip())


def find_managed_window(title):
    win_id = find_window(title)
    if not win_id:
        return None
    if get_desktop(win_id) is None:
        return None
    return win_id


def get_geometry(win_id):
    out = run('xdotool', 'getwindowgeometry', '--shell', win_id)
    return {k: int(v) for k, v in (line.split('=', 1) for line in out.splitlines() if '=' in line)}


def state():
    return (
        run('xprop', '-root', '_NET_CURRENT_DESKTOP', '_NET_ACTIVE_WINDOW'),
        run('xdotool', 'getwindowfocus'),
        run('xdotool', 'getmouselocation', '--shell'),
    )


def kill_window(win_id):
    S.run(['xdotool', 'windowclose', win_id], stdout=S.DEVNULL, stderr=S.DEVNULL)


def check():
    helper = Path(__file__).resolve().parents[1] / 'tools/open-bg.py'
    tag = int(os.environ.get('PROBE_TAG', '8'))
    assert 2 <= tag <= 10, 'PROBE_TAG must be 2 through 10 (foreground uses tag 1)'

    processes = []
    windows_to_close = []
    finished = threading.Event()
    changes = []

    with tempfile.TemporaryDirectory(prefix='dwm-native-bg-test-') as directory:
        fg_result = str(Path(directory) / 'fg')
        bg_result = str(Path(directory) / 'bg')
        fg_text = Path(fg_result + '.text')

        try:
            # 1. Prepare foreground input window on workspace 1 (desktop 0)
            run('xdotool', 'set_desktop', '0')
            fg_proc = S.Popen([sys.executable, __file__, '--app', 'foreground', fg_result])
            processes.append(fg_proc)
            fg_win = wait_for(lambda: find_managed_window('DwmNativeProbe-foreground'))
            run('xdotool', 'windowactivate', '--sync', fg_win)
            time.sleep(0.2)
            run('xdotool', 'mousemove', '--window', fg_win, '80', '80', 'click', '1')
            run('xdotool', 'type', '--clearmodifiers', 'fg-before')
            wait_for(lambda: fg_text.exists() and fg_text.read_text() == 'fg-before')

            before = state()

            def monitor():
                while not finished.is_set():
                    try:
                        current = state()
                        if current != before:
                            changes.append(current)
                    except Exception as error:
                        changes.append(str(error))
                    finished.wait(0.01)

            watcher = threading.Thread(target=monitor)
            watcher.start()

            # 2. Launch native alacritty onto workspace 8 while typing in foreground
            alacritty_bin = shutil.which('alacritty')
            alacritty_win = None
            if alacritty_bin:
                typing = S.Popen(['xdotool', 'type', '--delay', '50', '--clearmodifiers', '--', '-during1'])
                processes.append(typing)
                out = run(
                    sys.executable, str(helper), '--tag', str(tag), '--',
                    alacritty_bin, '-t', 'DwmNativeBgAlacritty',
                )
                assert 'pid=' in out and f'tag={tag}' in out, out
                alacritty_win = wait_for(lambda: find_managed_window('DwmNativeBgAlacritty'))
                windows_to_close.append(alacritty_win)
                assert typing.wait(timeout=5) == 0
                processes.remove(typing)

                wm_class = run('xprop', '-id', alacritty_win, 'WM_CLASS')
                assert 'Alacritty' in wm_class and 'Xephyr' not in wm_class, wm_class
                assert get_desktop(alacritty_win) == tag - 1, get_desktop(alacritty_win)
                geom = get_geometry(alacritty_win)
                assert geom['X'] < 0, geom
                print(f'PASS: native Alacritty opened on workspace {tag} ({wm_class})', flush=True)
            else:
                print('INFO: alacritty not installed in VM; skipping alacritty-specific check', flush=True)

            # 3. Launch native GTK app that deliberately calls window.present() (_NET_ACTIVE_WINDOW)
            typing2 = S.Popen(['xdotool', 'type', '--delay', '50', '--clearmodifiers', '--', '-during2'])
            processes.append(typing2)
            out = run(
                sys.executable, str(helper), '--tag', str(tag), '--',
                sys.executable, __file__, '--app-present', 'background-gtk', bg_result,
            )
            assert f'tag={tag}' in out, out
            bg_win = wait_for(lambda: find_managed_window('DwmNativeProbe-background-gtk'))
            windows_to_close.append(bg_win)
            time.sleep(0.4)  # allow delayed window.present() to fire
            assert typing2.wait(timeout=5) == 0
            processes.remove(typing2)
            assert get_desktop(bg_win) == tag - 1, get_desktop(bg_win)
            assert get_geometry(bg_win)['X'] < 0, get_geometry(bg_win)
            print(f'PASS: GTK app with window.present() stayed on workspace {tag} without focus theft', flush=True)

            # 4. Launch onto dynamic workspace ws1 (desktop 10)
            out = run(
                sys.executable, str(helper), '--tag', 'ws1', '--',
                sys.executable, __file__, '--app', 'background-ws1', bg_result,
            )
            assert 'tag=ws1' in out, out
            ws1_win = wait_for(lambda: find_managed_window('DwmNativeProbe-background-ws1'))
            windows_to_close.append(ws1_win)
            assert get_desktop(ws1_win) == 10, get_desktop(ws1_win)
            active_ws = run('xprop', '-root', '_DWM_ACTIVE_WORKSPACES')
            active_mask = int(active_ws.rsplit('=', 1)[1].strip())
            assert active_mask & (1 << 10), active_ws
            print('PASS: dynamic workspace ws1 launch works and marks active workspace', flush=True)

            # 5. Stop foreground monitor and verify zero disturbance throughout all launches
            assert state() == before, (before, state())
            finished.set()
            watcher.join()
            assert not changes, changes[:3]

            expected = 'fg-before-during1-during2' if alacritty_bin else 'fg-before-during2'
            run('xdotool', 'type', '--clearmodifiers', '--', '-after')
            wait_for(lambda: fg_text.read_text() == expected + '-after')
            print('PASS: foreground desktop, active window, focus, pointer, and typing undisturbed', flush=True)

            # 6. Verify terminal token consumption (subsequent app with same terminal token opens on current workspace)
            if alacritty_bin:
                shared_token = 'deadbeef12345678'
                shared_env = dict(
                    os.environ,
                    DWM_BG_TAG=str(tag),
                    DWM_BG_EXPIRES=str(int(time.time()) + 30),
                    DWM_BG_TOKEN=shared_token,
                )
                term_proc = S.Popen([alacritty_bin, '-t', 'DwmNativeTokenTerm'], env=shared_env)
                processes.append(term_proc)
                tok_term = wait_for(lambda: find_managed_window('DwmNativeTokenTerm'))
                windows_to_close.append(tok_term)
                assert get_desktop(tok_term) == tag - 1, get_desktop(tok_term)

                # Now launch a child GUI with the exact same env; token was consumed by terminal -> stays on desktop 0
                child_proc = S.Popen(
                    [sys.executable, __file__, '--app', 'after-token', bg_result],
                    env=shared_env,
                )
                processes.append(child_proc)
                after_tok_win = wait_for(lambda: find_managed_window('DwmNativeProbe-after-token'))
                windows_to_close.append(after_tok_win)
                assert get_desktop(after_tok_win) == 0, get_desktop(after_tok_win)
                print('PASS: terminal launch consumed token so child apps do not leak to old workspace', flush=True)

            # 7. Switch to workspace 8 and verify Alacritty tiles properly inside screen bounds
            if alacritty_win:
                run('xdotool', 'set_desktop', str(tag - 1))
                time.sleep(0.3)
                vis_geom = get_geometry(alacritty_win)
                assert vis_geom['X'] >= 0 and vis_geom['WIDTH'] > 300 and vis_geom['HEIGHT'] > 200, vis_geom
                run('xdotool', 'set_desktop', '0')
                print(f'PASS: Alacritty tiled normally when viewing workspace {tag} ({vis_geom})', flush=True)

            # 8. Verify launching via open-bg.py from inside a foreground Alacritty is NOT swallowed
            if alacritty_bin:
                cmd = (
                    f'{sys.executable} {helper} --tag {tag} -- '
                    f'{sys.executable} {__file__} --app noswallow-child {bg_result}; '
                    'sleep 5'
                )
                fg_term_proc = S.Popen([alacritty_bin, '-t', 'DwmNativeFgTerm', '-e', 'sh', '-c', cmd])
                processes.append(fg_term_proc)
                fg_term = wait_for(lambda: find_managed_window('DwmNativeFgTerm'))
                windows_to_close.append(fg_term)
                ns_child = wait_for(lambda: find_managed_window('DwmNativeProbe-noswallow-child'))
                windows_to_close.append(ns_child)
                assert get_desktop(fg_term) == 0, get_desktop(fg_term)
                assert get_desktop(ns_child) == tag - 1, get_desktop(ns_child)
                assert get_geometry(ns_child)['X'] < 0, get_geometry(ns_child)
                print('PASS: background app launched from foreground Alacritty is not swallowed', flush=True)

        finally:
            finished.set()
            if 'watcher' in locals():
                watcher.join()
            for win_id in reversed(windows_to_close):
                kill_window(win_id)
            for proc in reversed(processes):
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except S.TimeoutExpired:
                        proc.kill()
                        proc.wait()


if __name__ == '__main__':
    if sys.argv[1:2] == ['--app']:
        app(sys.argv[2], sys.argv[3], present=False)
    elif sys.argv[1:2] == ['--app-present']:
        app(sys.argv[2], sys.argv[3], present=True)
    else:
        check()
