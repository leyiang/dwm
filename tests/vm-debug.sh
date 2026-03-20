#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

VM_IP="${VM_IP:-192.168.122.48}"
VM_USER="${VM_USER:-test}"
VM_PASS="${VM_PASS:-test}"
REMOTE_DWM_TMP="/home/$VM_USER/dwm.new"
REMOTE_REPRO_TMP="/home/$VM_USER/debug-magicgrid-titlebar-remote.sh"
REMOTE_ARTIFACT_TAR="/tmp/dwm-repro-artifacts.tar"
ARTIFACT_DIR="${ARTIFACT_DIR:-$REPO_ROOT/vm-artifacts}"

usage() {
    echo "Usage: $0 {build|deploy|setup-tools|status|log|repro}"
    exit 1
}

require_sshpass() {
    if ! command -v sshpass >/dev/null 2>&1; then
        echo "sshpass is required" >&2
        exit 1
    fi
}

remote_ssh() {
    require_sshpass
    sshpass -p "$VM_PASS" ssh -o StrictHostKeyChecking=no "$VM_USER@$VM_IP" "$@"
}

remote_scp_to() {
    require_sshpass
    sshpass -p "$VM_PASS" scp -o StrictHostKeyChecking=no "$1" "$VM_USER@$VM_IP:$2"
}

remote_scp_from() {
    require_sshpass
    sshpass -p "$VM_PASS" scp -o StrictHostKeyChecking=no "$VM_USER@$VM_IP:$1" "$2"
}

build() {
    (
        cd "$REPO_ROOT"
        make qemu
    )
}

deploy() {
    build
    remote_scp_to "$REPO_ROOT/dwm-qemu" "$REMOTE_DWM_TMP"
    remote_ssh "set -eu;
        echo '$VM_PASS' | sudo -S cp /usr/local/bin/dwm /usr/local/bin/dwm.backup;
        echo '$VM_PASS' | sudo -S install -m 0755 '$REMOTE_DWM_TMP' /usr/local/bin/dwm;
        : > /tmp/dwm.log;
        echo '$VM_PASS' | sudo -S systemctl restart gdm3"
}

setup_tools() {
    remote_ssh "echo '$VM_PASS' | sudo -S apt-get update"
    remote_ssh "echo '$VM_PASS' | sudo -S apt-get install -y ffmpeg xdotool wmctrl scrot x11-utils"
}

status() {
    remote_ssh "set -eu;
        echo '== dwm sha256 ==';
        sha256sum /usr/local/bin/dwm || true;
        echo;
        echo '== loginctl ==';
        loginctl list-sessions --no-legend || true;
        echo;
        echo '== processes ==';
        ps -ef | grep -E 'dwm|gdm|Xorg|ffplay|alacritty' | grep -v grep || true;
        echo;
        echo '== tools ==';
        command -v ffplay || true;
        command -v xdotool || true;
        command -v wmctrl || true;
        command -v scrot || true;
        echo;
        echo '== dwm log ==';
        tail -n 120 /tmp/dwm.log || true"
}

log() {
    remote_ssh "tail -n 200 /tmp/dwm.log"
}

repro() {
    mkdir -p "$ARTIFACT_DIR"
    remote_scp_to "$SCRIPT_DIR/debug-magicgrid-titlebar-remote.sh" "$REMOTE_REPRO_TMP"
    remote_ssh "chmod +x '$REMOTE_REPRO_TMP' && '$REMOTE_REPRO_TMP'"
    remote_scp_from "$REMOTE_ARTIFACT_TAR" "$ARTIFACT_DIR/dwm-repro-artifacts.tar"
    tar -xf "$ARTIFACT_DIR/dwm-repro-artifacts.tar" -C "$ARTIFACT_DIR"
    echo "Artifacts saved to $ARTIFACT_DIR"
}

case "${1:-}" in
    build) build ;;
    deploy) deploy ;;
    setup-tools) setup_tools ;;
    status) status ;;
    log) log ;;
    repro) repro ;;
    *) usage ;;
esac
