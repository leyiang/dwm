#!/usr/bin/env python3
"""点击选择 X11 窗口，临时修改它的最小尺寸。"""

import argparse
import os
import re
import subprocess
import sys


def positive_int(value):
    number = int(value)
    if number < 1 or number > 65535:
        raise argparse.ArgumentTypeError('尺寸必须在 1 到 65535 之间')
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('width', nargs='?', type=positive_int, default=1,
                        help='最小宽度，默认 1')
    parser.add_argument('height', nargs='?', type=positive_int, default=1,
                        help='最小高度，默认 1')
    args = parser.parse_args()

    try:
        from Xlib import Xatom, Xutil, display
    except ImportError:
        raise RuntimeError('需要 python-xlib；Ubuntu/Debian 可安装 python3-xlib')

    print('请点击目标窗口（Ctrl+C 取消）……', flush=True)
    try:
        selected = subprocess.run(
            ['xwininfo'], env=dict(os.environ, LC_ALL='C'),
            text=True, stdout=subprocess.PIPE, check=True)
    except FileNotFoundError:
        raise RuntimeError('需要 xwininfo；Ubuntu/Debian 可安装 x11-utils')
    except subprocess.CalledProcessError:
        raise RuntimeError('选取窗口失败，未修改尺寸提示')
    match = re.search(r'Window id:\s*(0x[0-9a-fA-F]+)', selected.stdout)
    if match is None:
        raise RuntimeError('无法从 xwininfo 输出中读取窗口 ID')

    connection = display.Display()
    try:
        window_id = int(match.group(1), 16)
        if window_id == connection.screen().root.id:
            raise RuntimeError('选中了桌面，请重新运行并点击应用窗口')
        window = connection.create_resource_object('window', window_id)
        prop = window.get_full_property(Xatom.WM_NORMAL_HINTS, Xatom.WM_SIZE_HINTS)
        if prop is None:
            values = [0] * 18
        elif prop.format != 32 or len(prop.value) < 15:
            raise RuntimeError('窗口的 WM_NORMAL_HINTS 格式无效，未修改')
        else:
            values = list(prop.value)

        # 直接读写属性，兼容仍调用 array.tostring() 的旧版 python-xlib。
        # ICCCM: flags=0, min_width/height=5/6, base_width/height=15/16。
        values[0] = (values[0] | Xutil.PMinSize) & ~Xutil.PBaseSize
        values[5], values[6] = args.width, args.height
        if len(values) >= 17:
            values[15] = values[16] = 0
        errors = []
        window.change_property(Xatom.WM_NORMAL_HINTS, Xatom.WM_SIZE_HINTS,
                               32, values, onerror=lambda error, _request: errors.append(error))
        connection.sync()
        if errors:
            raise RuntimeError(f'写入尺寸提示失败：{errors[0]}')
        updated = window.get_full_property(Xatom.WM_NORMAL_HINTS, Xatom.WM_SIZE_HINTS)
        if updated is None or list(updated.value) != values:
            raise RuntimeError('尺寸提示未能保持，应用可能已重新设置它')
        print(f'窗口 {window_id:#x}：最小尺寸已设为 {args.width} × {args.height}，现在可以拖动缩小。')
    finally:
        connection.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n已取消。', file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(f'错误：{error}', file=sys.stderr)
        raise SystemExit(1)
