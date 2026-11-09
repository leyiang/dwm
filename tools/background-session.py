#!/usr/bin/env python3
"""Run an application in an independent X server on a dwm tag."""

import argparse
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import tempfile
import time


def stop(process):
    if process is None:
        return
    # Include applications started by the command, not just its immediate shell.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', type=int, required=True, choices=range(1, 11))
    parser.add_argument('--screen', default='1024x768')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command[:1] == ['--']:
        command = command[1:]
    if not command:
        parser.error('provide a command after --')
    for program in ('Xephyr', 'xauth', 'xdpyinfo', 'dbus-run-session'):
        if not shutil.which(program):
            parser.error(f'missing dependency: {program}')
    if not os.environ.get('DISPLAY'):
        parser.error('DISPLAY must point to the outer dwm session')
    display = next((f':{number}' for number in range(100, 200)
                    if not Path(f'/tmp/.X11-unix/X{number}').exists()
                    and not Path(f'/tmp/.X{number}-lock').exists()), None)
    if display is None:
        parser.error('no unused display in :100 through :199')

    server = application = None
    with tempfile.TemporaryDirectory(prefix='dwm-background-') as directory:
        authority = Path(directory) / 'Xauthority'
        authority.touch(mode=0o600)
        subprocess.run(['xauth', '-f', str(authority), 'add', display,
                        '.', secrets.token_hex(16)], check=True)
        environment = dict(os.environ, DISPLAY=display, XAUTHORITY=str(authority),
                           GDK_BACKEND='x11', QT_QPA_PLATFORM='xcb')
        environment.pop('WAYLAND_DISPLAY', None)
        environment.pop('DBUS_SESSION_BUS_ADDRESS', None)
        try:
            server = subprocess.Popen([
                'Xephyr', display, '-auth', str(authority), '-nolisten', 'tcp',
                '-noreset', '-no-host-grab', '-screen', args.screen,
                '-name', f'dwm-background-{args.tag}',
                '-title', f'Background session (tag {args.tag}, {display})',
            ], start_new_session=True)
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError('Xephyr exited before becoming ready')
                if subprocess.run(['xdpyinfo'], env=environment,
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL).returncode == 0:
                    break
                time.sleep(.05)
            else:
                raise RuntimeError('Xephyr did not become ready in 5 seconds')
            print(f'DISPLAY={display} XAUTHORITY={authority}', flush=True)
            application = subprocess.Popen(['dbus-run-session', '--', *command],
                                           env=environment, start_new_session=True)
            return application.wait()
        finally:
            stop(application)
            stop(server)


if __name__ == '__main__':
    def terminate(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
