"""在虚机中检查 magicgrid 的标题更新延迟和隐藏后的标题栏。"""

import argparse
import subprocess
import time

from Xlib import X, display, error


def wait_until(check, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.02)
    raise RuntimeError("等待 X11 状态变化超时")


def key(shortcut):
    subprocess.run(["xdotool", "key", shortcut], check=True, timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["hide", "latency"])
    parser.add_argument("count", type=int, choices=range(1, 33))
    parser.add_argument("--rounds", type=int, default=0)
    args = parser.parse_args()
    d = display.Display()
    root = d.screen().root

    def prop(name):
        value = root.get_full_property(d.intern_atom(name), X.AnyPropertyType)
        return list(value.value) if value else []

    original = prop("_NET_CURRENT_DESKTOP")[0]
    try:
        key("Super_L+Shift_L+b")
        wait_until(lambda: prop("_NET_CURRENT_DESKTOP") == [9])
        windows = []
        for i in range(args.count):
            w = root.create_window(0, 0, 150, 100, 0, X.CopyFromParent)
            w.set_wm_name(f"Grid check {i}")
            w.set_wm_class("grid-check", "GridCheck")
            w.map()
            windows.append(w)
        d.flush()
        wait_until(lambda: {w.id for w in windows} <= set(prop("_NET_CLIENT_LIST")))
        target = windows[-1]

        def find_title():
            g = target.get_geometry()
            for child in root.query_tree().children:
                try:
                    attr = child.get_attributes()
                    if not attr.override_redirect or attr.map_state != X.IsViewable:
                        continue
                    t = child.get_geometry()
                except error.BadWindow:
                    continue
                if (t.x, t.y + t.height) == (g.x, g.y) and t.width >= g.width:
                    return child

        title = wait_until(find_title)
        if args.mode == "hide":
            subprocess.run(["wmctrl", "-ia", hex(target.id)], check=True)
            wait_until(lambda: prop("_NET_ACTIVE_WINDOW") == [target.id])
            key("Super_L+h")
            wait_until(lambda: target.get_geometry().x < 0)
            wait_until(lambda: prop("_NET_ACTIVE_WINDOW") != [target.id])
            time.sleep(.2)
            try:
                g = title.get_geometry()
                visible = title.get_attributes().map_state == X.IsViewable
            except error.BadWindow:
                print("PASS 标题栏已销毁")
                return 0
            screen = root.get_geometry()
            onscreen = g.x < screen.width and g.x + g.width > 0 and g.y < screen.height and g.y + g.height > 0
            print(f"client_x={target.get_geometry().x} title={hex(title.id)} "
                  f"mapped={visible} geometry={g.width}x{g.height}{g.x:+}{g.y:+}")
            if visible and onscreen:
                print("RED 隐藏窗口后，它的标题栏仍映射在屏幕内")
                return 1
        else:
            for tick in range(args.rounds):
                for i, w in enumerate(windows):
                    w.set_wm_name(f"Grid check {i} tick {tick}")
                d.flush()
                time.sleep(.1)
            start = time.monotonic()
            subprocess.run(["wmctrl", "-s", "0"], check=True)
            wait_until(lambda: prop("_NET_CURRENT_DESKTOP") == [0], seconds=60)
            delay = time.monotonic() - start
            print(f"windows={args.count} rounds={args.rounds} switch_seconds={delay:.3f}")
            if delay > 1:
                print("RED 工作区切换延迟超过一秒")
                return 1
        print("PASS")
        return 0
    finally:
        d.close()
        subprocess.run(["wmctrl", "-s", str(original)], check=True)


if __name__ == "__main__":
    raise SystemExit(main())
