#!/usr/bin/env python3
"""Launch a normal native application on a background dwm workspace without stealing focus."""

import argparse
import os
import re
import secrets
import subprocess
import time


TAG_PATTERN = re.compile(r'^([1-9]|10|[bB]|[wW][sS]([1-9]|1[0-9]|20))$')


def normalize_tag(value):
    text = value.strip()
    if not TAG_PATTERN.match(text):
        raise argparse.ArgumentTypeError(
            f'invalid tag {value!r}; expected 1-10, b, or ws1-ws20'
        )
    if text.lower() == 'b':
        return 'b'
    if text.lower().startswith('ws'):
        return 'ws' + text[2:]
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '-t', '--tag',
        required=True,
        type=normalize_tag,
        help='target workspace: 1-10, b, or ws1-ws20',
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=15,
        help='routing window in seconds before DWM_BG_* expires (0 = no expiry, default: 15)',
    )
    parser.add_argument(
        '--wait',
        action='store_true',
        help='wait for the launched process to exit instead of returning immediately',
    )
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = args.command
    if command[:1] == ['--']:
        command = command[1:]
    if not command:
        parser.error('provide a command to launch (e.g. -- alacritty)')
    if args.timeout < 0:
        parser.error('--timeout must be >= 0')
    if not os.environ.get('DISPLAY'):
        parser.error('DISPLAY must be set to the dwm X11 display')

    expires = int(time.time()) + args.timeout if args.timeout > 0 else 0
    token = secrets.token_hex(8)
    startup_id = f'dwm-bg-{args.tag}-{expires}-{token}'

    env = dict(os.environ)
    env['DWM_BG_TAG'] = args.tag
    env['DWM_BG_EXPIRES'] = str(expires)
    env['DWM_BG_TOKEN'] = token
    env['DESKTOP_STARTUP_ID'] = startup_id

    if args.wait:
        process = subprocess.Popen(command, env=env)
        return process.wait()

    process = subprocess.Popen(
        command,
        env=env,
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f'pid={process.pid} tag={args.tag}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
