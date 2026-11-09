#!/usr/bin/env python3
"""Check resize gestures in the test VM's active dwm session."""

import os
import subprocess as sp
import sys
import time


def app(title, cls):
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    window = Gtk.Window(title=title)
    window.set_wmclass(title, cls)
    window.set_default_size(320, 240)
    window.add(Gtk.Label(label='Meta + Alt + left drag to resize'))
    window.connect('destroy', Gtk.main_quit)
    window.show_all()
    Gtk.main()


def run(*args):
    return sp.check_output(args, text=True, timeout=5).strip()


def wait_for(check):
    for _ in range(100):
        value = check()
        if value:
            return value
        time.sleep(.05)
    raise RuntimeError('test timed out')


def geometry(window):
    return {key: int(value) for key, value in
            (line.split('=', 1) for line in run('xdotool', 'getwindowgeometry', '--shell', window).splitlines())}


def pointer():
    values = dict(line.split('=', 1) for line in run('xdotool', 'getmouselocation', '--shell').splitlines())
    return int(values['X']), int(values['Y'])


def drag(window, dx, dy, button=1, alt=True, no_warp=True):
    before = geometry(window)
    sx, sy = before['X'] + before['WIDTH'] // 2, before['Y'] + before['HEIGHT'] // 2
    run('xdotool', 'mousemove', str(sx), str(sy))
    run('xdotool', 'keydown', 'Super_L')
    if alt:
        run('xdotool', 'keydown', 'Alt_L')
    try:
        run('xdotool', 'mousedown', str(button))
        time.sleep(.1)
        if no_warp:
            assert pointer() == (sx, sy), ('pointer warped at press', pointer())
        px, py = pointer()
        for step in range(1, 5):
            run('xdotool', 'mousemove', str(px + dx * step // 4), str(py + dy * step // 4))
            time.sleep(.06)
    finally:
        run('xdotool', 'mouseup', str(button))
        run('xdotool', 'keyup', 'Super_L', 'Alt_L')
    time.sleep(.1)
    if no_warp:
        assert pointer() == (sx + dx, sy + dy), ('pointer warped at release', pointer())
    return before, geometry(window)


def check():
    processes = []
    try:
        wait_for(lambda: 'window id # 0x' in run('xprop', '-root', '_NET_SUPPORTING_WM_CHECK'))
        run('wmctrl', '-s', '0')

        def open_window(title, cls):
            processes.append(sp.Popen([sys.executable, __file__, '--app', title, cls],
                                      env=dict(os.environ, GDK_BACKEND='x11')))

            def find():
                found = sp.run(['xdotool', 'search', '--name', '^' + title + '$'],
                               text=True, capture_output=True, timeout=5)
                return found.stdout.strip() if found.returncode == 0 else None

            window = wait_for(find)
            wait_for(lambda: hex(int(window)) in run('xprop', '-root', '_NET_CLIENT_LIST'))
            time.sleep(.2)
            return window

        floating = open_window('DwmResizeFloating', 'Gimp')
        run('scrot', '/tmp/dwm-resize-before.png')
        for dx, dy in [(80, 60), (-60, -40)]:
            before, after = drag(floating, dx, dy)
            assert (before['X'], before['Y']) == (after['X'], after['Y']), (before, after)
            assert after['WIDTH'] - before['WIDTH'] == dx, (before, after)
            assert after['HEIGHT'] - before['HEIGHT'] == dy, (before, after)
            print('PASS relative floating resize', dx, dy, before, after, flush=True)
            if dx > 0:
                run('scrot', '/tmp/dwm-resize-after.png')

        before, after = drag(floating, 80, 60, button=3, alt=False, no_warp=False)
        assert after['WIDTH'] > before['WIDTH'] and after['HEIGHT'] > before['HEIGHT']
        print('PASS legacy Meta + right drag', flush=True)
        # Move beyond dwm's edge-snap threshold, including when starting at the edge.
        before, after = drag(floating, 100, 80, alt=False)
        assert (after['X'], after['Y']) == (before['X'] + 100, before['Y'] + 80), (before, after)
        assert (after['WIDTH'], after['HEIGHT']) == (before['WIDTH'], before['HEIGHT'])
        print('PASS legacy Meta + left drag moves window', flush=True)

        run('wmctrl', '-i', '-r', floating, '-b', 'add,fullscreen')
        time.sleep(.1)
        before, after = drag(floating, 40, 30)
        assert before == after, (before, after)
        print('PASS fullscreen ignores new gesture', flush=True)
        run('wmctrl', '-i', '-r', floating, '-b', 'remove,fullscreen')

        tiled = open_window('DwmResizeTiled', 'DwmResizeTest')
        before, after = drag(tiled, 40, 30)
        assert before == after, (before, after)
        print('PASS tiled window ignores new gesture', flush=True)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


if __name__ == '__main__':
    if sys.argv[1:2] == ['--app']:
        app(sys.argv[2], sys.argv[3])
    else:
        check()
