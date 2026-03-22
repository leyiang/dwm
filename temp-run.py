#!/usr/bin/env python3

import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
ARTIFACT_DIR = REPO_ROOT / "vm-artifacts" / "focus-overlay"
REMOTE_SCRIPT = "/home/{user}/focus-overlay-temp.sh"
REMOTE_TAR = "/tmp/focus-overlay-artifacts.tar"
REMOTE_SCRIPT_BODY = """#!/bin/sh
set -u
exec >/tmp/focus-overlay-trace.log 2>&1
set -x

export DISPLAY=:0
export XAUTHORITY=/run/user/1000/gdm/Xauthority

wait_alacritty_count() {
    target="$1"
    i=0
    while [ "$i" -lt 30 ]; do
        count="$(wmctrl -lx 2>/dev/null | grep -ci alacritty || true)"
        if [ "$count" -ge "$target" ]; then
            return 0
        fi
        sleep 0.2
        i=$((i + 1))
    done
    return 1
}

rm -f \
    /tmp/focus-single-after.png \
    /tmp/focus-tile-after.png \
    /tmp/focus-monocle-after.png \
    /tmp/focus-workspace-after.png \
    /tmp/focus-overlay-tree.txt \
    /tmp/focus-overlay-wmctrl.txt \
    /tmp/focus-overlay-artifacts.tar \
    /tmp/focus-overlay-a.log \
    /tmp/focus-overlay-b.log \
    /tmp/focus-overlay-c.log

: > /tmp/dwm.log

# Scenario 1: single-window workspace should not animate.
pkill -f '^alacritty$' || true
xdotool key Super_L+1 || true
sleep 1

alacritty -e sh -c 'sleep 20' >/tmp/focus-overlay-a.log 2>&1 &
wait_alacritty_count 1 || true
sleep 0.2
xdotool key Super_L+j || true
sleep 0.08
scrot /tmp/focus-single-after.png || true

# Scenario 2: tiled workspace with 2 windows should animate on focus switch.
alacritty -e sh -c 'sleep 20' >/tmp/focus-overlay-b.log 2>&1 &
wait_alacritty_count 2 || true
sleep 0.08
xdotool key Super_L+k || true
sleep 0.08
scrot /tmp/focus-tile-after.png || true

# Scenario 3: monocle/meta+f should suppress focus animation.
xdotool key Super_L+f || true
sleep 0.2
xdotool key Super_L+j || true
sleep 0.08
scrot /tmp/focus-monocle-after.png || true

# Reset and prepare workspace-switch case.
xdotool key Super_L+f || true
sleep 0.2
pkill -f '^alacritty$' || true
sleep 0.5

# Scenario 4: switching to a workspace with only one window should not animate.
xdotool key Super_L+2 || true
sleep 0.4
alacritty -e sh -c 'sleep 20' >/tmp/focus-overlay-c.log 2>&1 &
wait_alacritty_count 1 || true
sleep 0.2
xdotool key Super_L+1 || true
sleep 0.2
xdotool key Super_L+2 || true
sleep 0.08
scrot /tmp/focus-workspace-after.png || true

xwininfo -root -tree >/tmp/focus-overlay-tree.txt || true
wmctrl -lxG >/tmp/focus-overlay-wmctrl.txt || true

pkill -f '^alacritty$' || true

tar -C /tmp -cf /tmp/focus-overlay-artifacts.tar \
    focus-single-after.png \
    focus-tile-after.png \
    focus-monocle-after.png \
    focus-workspace-after.png \
    focus-overlay-tree.txt \
    focus-overlay-wmctrl.txt \
    focus-overlay-trace.log \
    dwm.log \
    focus-overlay-a.log \
    focus-overlay-b.log \
    focus-overlay-c.log
"""


def run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, env=env)


def maybe_start_vm(vm_name: str, env: dict[str, str]) -> None:
    state = subprocess.run(
        ["virsh", "domstate", vm_name],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()
    print(f"VM state: {state}")
    if state == "running":
        return
    run(["virsh", "start", vm_name], env=env)
    time.sleep(8)


def main() -> None:
    vm_name = os.environ.get("VM_NAME", "ubuntu24.04")
    vm_ip = os.environ.get("VM_IP", "192.168.122.48")
    vm_user = os.environ.get("VM_USER", "test")
    vm_pass = os.environ.get("VM_PASS", "test")

    env = os.environ.copy()
    env["LC_ALL"] = "C"

    maybe_start_vm(vm_name, env)

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    artifact_tar = ARTIFACT_DIR / "focus-overlay-artifacts.tar"
    if artifact_tar.exists():
        artifact_tar.unlink()

    remote_script = REMOTE_SCRIPT.format(user=vm_user)

    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as tmp:
        tmp.write(REMOTE_SCRIPT_BODY)
        local_remote_script = Path(tmp.name)

    try:
        scp_base = [
            "sshpass",
            "-p",
            vm_pass,
            "scp",
            "-o",
            "StrictHostKeyChecking=no",
        ]
        ssh_base = [
            "sshpass",
            "-p",
            vm_pass,
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            f"{vm_user}@{vm_ip}",
        ]

        run(
            scp_base
            + [
                str(local_remote_script),
                f"{vm_user}@{vm_ip}:{remote_script}",
            ],
            env=env,
        )
        run(
            ssh_base
            + [
                f"chmod +x {remote_script} && {remote_script}",
            ],
            env=env,
        )
        run(
            scp_base
            + [
                f"{vm_user}@{vm_ip}:{REMOTE_TAR}",
                str(artifact_tar),
            ],
            env=env,
        )

        for entry in ARTIFACT_DIR.iterdir():
            if entry.name != artifact_tar.name:
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()

        with tarfile.open(artifact_tar) as tar:
            tar.extractall(ARTIFACT_DIR)
    finally:
        local_remote_script.unlink(missing_ok=True)

    print(f"Artifacts extracted to: {ARTIFACT_DIR}")


if __name__ == "__main__":
    main()
