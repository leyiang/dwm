#!/usr/bin/env python3
"""VM integration check: hidden Xephyr, real GTK input, undisturbed outer X."""

import json
import os
from pathlib import Path
import subprocess as S
import sys
import tempfile
import threading
import time


def app(kind, result):
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    window = Gtk.Window(title=f'DwmProbe-{kind}')
    window.set_default_size(400, 200)
    layout = Gtk.Fixed()
    entry = Gtk.Entry()
    entry.set_size_request(240, 40)
    layout.put(entry, 20, 110)
    button = Gtk.Button(label='Record text')
    button.set_size_request(240, 60)
    layout.put(button, 20, 20)

    def record(_):
        with open(result, 'a') as output:
            output.write(json.dumps(entry.get_text()) + '\n')

    button.connect('clicked', record)
    entry.connect('changed', lambda _: Path(result + '.text').write_text(entry.get_text()))
    window.add(layout)
    window.connect('destroy', Gtk.main_quit)
    window.show_all()
    entry.grab_focus()
    Gtk.main()


def run(*command, env=None):
    return S.check_output(command, env=env, text=True).strip()


def wait_for(predicate):
    for _ in range(100):
        value = predicate()
        if value:
            return value
        time.sleep(.05)
    raise AssertionError('timed out waiting for test condition')


def find_window(title, env=None):
    result = S.run(['xdotool', 'search', '--name', '^' + title + '$'],
                   env=env, text=True, capture_output=True)
    return result.stdout.splitlines()[0] if result.returncode == 0 else None


def state():
    return (run('xprop', '-root', '_NET_CURRENT_DESKTOP', '_NET_ACTIVE_WINDOW'),
            run('xdotool', 'getwindowfocus'),
            run('xdotool', 'getmouselocation', '--shell'))


def check():
    helper = Path(__file__).resolve().parents[1] / 'tools/background-session.py'
    tag = int(os.environ.get('PROBE_TAG', '9'))
    assert 2 <= tag <= 10, 'PROBE_TAG must be 2 through 10 (foreground uses tag 1)'
    processes = []
    finished = threading.Event()
    changes = []
    with tempfile.TemporaryDirectory(prefix='dwm-background-test-') as directory:
        foreground_result = str(Path(directory) / 'foreground')
        background_result = str(Path(directory) / 'background')
        try:
            # This setup uses the VM's foreground; the measured operation below must not.
            run('xdotool', 'set_desktop', '0')
            processes.append(S.Popen([sys.executable, __file__, '--app', 'foreground', foreground_result]))
            foreground = wait_for(lambda: find_window('DwmProbe-foreground'))
            run('xdotool', 'windowactivate', '--sync', foreground)
            time.sleep(.2)
            run('xdotool', 'mousemove', '--window', foreground, '50', '130', 'click', '1')
            run('xdotool', 'type', '--clearmodifiers', 'foreground-before')
            foreground_text = Path(foreground_result + '.text')
            wait_for(lambda: foreground_text.exists() and foreground_text.read_text() == 'foreground-before')
            before = state()

            def monitor():
                while not finished.is_set():
                    try:
                        current = state()
                        if current != before:
                            changes.append(current)
                    except Exception as error:
                        changes.append(str(error))
                    finished.wait(.01)

            watcher = threading.Thread(target=monitor)
            watcher.start()
            session = S.Popen([sys.executable, str(helper), '--tag', str(tag), '--screen', '640x480',
                               '--', sys.executable, __file__, '--app', 'background', background_result],
                              stdout=S.PIPE, text=True)
            processes.append(session)
            line = session.stdout.readline().strip()
            assert line.startswith('DISPLAY='), line
            nested = dict(os.environ, **dict(item.split('=', 1) for item in line.split()))
            background = wait_for(lambda: find_window('DwmProbe-background', nested))
            outer = wait_for(lambda: find_window(r'Background session \(tag ' + str(tag) + r', :[0-9]+\)'))
            print(run('xprop', '-id', outer, 'WM_CLASS'), flush=True)
            desktop = run('xprop', '-id', outer, '_NET_WM_DESKTOP')
            assert desktop.endswith(f'= {tag - 1}'), desktop
            geometry = run('xdotool', 'getwindowgeometry', '--shell', outer)
            assert int(dict(item.split('=', 1) for item in geometry.splitlines())['X']) < 0, geometry
            typing = S.Popen(['xdotool', 'type', '--delay', '80', '--clearmodifiers', '--', '-during'])
            processes.append(typing)
            for index in range(3):
                run('xdotool', 'mousemove', '--window', background, '50', '130', 'click', '1', env=nested)
                run('xdotool', 'key', 'ctrl+a', env=nested)
                run('xdotool', 'type', '--clearmodifiers', f'background-{index}', env=nested)
                run('xdotool', 'mousemove', '--window', background, '50', '45', 'click', '1', env=nested)
            assert typing.wait(timeout=5) == 0
            processes.remove(typing)
            wait_for(lambda: Path(background_result).exists()
                     and len(Path(background_result).read_text().splitlines()) == 3)
            callbacks = [json.loads(row) for row in Path(background_result).read_text().splitlines()]
            assert callbacks == [f'background-{index}' for index in range(3)], callbacks
            if os.environ.get('BACKGROUND_SCREENSHOT'):
                run('scrot', os.environ['BACKGROUND_SCREENSHOT'], env=nested)
            session.terminate()
            session.wait(timeout=10)
            processes.remove(session)
            assert state() == before, (before, state())
            finished.set()
            watcher.join()
            assert not changes, changes[:3]
            run('xdotool', 'type', '--clearmodifiers', '--', '-after')
            wait_for(lambda: foreground_text.read_text() == 'foreground-before-during-after')
            print(f'PASS: tag {tag}, three real GTK clicks and text input, concurrent foreground typing stays separate')
            print('PASS: outer desktop, active window, keyboard focus and pointer stayed unchanged through open/input/close')
            print('BACKGROUND_CALLBACKS', json.dumps(callbacks))
        finally:
            finished.set()
            if 'watcher' in locals():
                watcher.join()
            for process in reversed(processes):
                process.terminate()
                process.wait(timeout=10)


if __name__ == '__main__':
    if sys.argv[1:2] == ['--app']:
        app(sys.argv[2], sys.argv[3])
    else:
        check()
