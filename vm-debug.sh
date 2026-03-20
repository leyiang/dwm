#!/bin/sh

set -eu

VM_IP="${VM_IP:-192.168.122.48}"
VM_USER="${VM_USER:-test}"
VM_PASS="${VM_PASS:-test}"
REMOTE_DWM_TMP="/home/$VM_USER/dwm.new"
REMOTE_REPRO_TMP="/home/$VM_USER/vm-repro-remote.sh"
ARTIFACT_DIR="${ARTIFACT_DIR:-/home/yiang/source/dwm/vm-artifacts}"

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

maybe_remote_scp_from() {
    remote_ssh "test -f '$1'" || return 0
    remote_scp_from "$1" "$2"
}

build() {
    make qemu
}

deploy() {
    build
    remote_scp_to "./dwm" "$REMOTE_DWM_TMP"
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
    remote_scp_to "./vm-repro-remote.sh" "$REMOTE_REPRO_TMP"
    remote_ssh "chmod +x '$REMOTE_REPRO_TMP' && '$REMOTE_REPRO_TMP'"
    maybe_remote_scp_from "/tmp/dwm-repro-before.png" "$ARTIFACT_DIR/dwm-repro-before.png"
    maybe_remote_scp_from "/tmp/dwm-repro-after.png" "$ARTIFACT_DIR/dwm-repro-after.png"
    maybe_remote_scp_from "/tmp/dwm-tree-before.txt" "$ARTIFACT_DIR/dwm-tree-before.txt"
    maybe_remote_scp_from "/tmp/dwm-tree-after.txt" "$ARTIFACT_DIR/dwm-tree-after.txt"
    maybe_remote_scp_from "/tmp/dwm-map-after.txt" "$ARTIFACT_DIR/dwm-map-after.txt"
    maybe_remote_scp_from "/tmp/wmctrl-before.txt" "$ARTIFACT_DIR/wmctrl-before.txt"
    maybe_remote_scp_from "/tmp/wmctrl-after.txt" "$ARTIFACT_DIR/wmctrl-after.txt"
    maybe_remote_scp_from "/tmp/dwm.log" "$ARTIFACT_DIR/dwm.log"
    maybe_remote_scp_from "/tmp/vm-repro-trace.log" "$ARTIFACT_DIR/vm-repro-trace.log"
    maybe_remote_scp_from "/tmp/ffplay-repro.log" "$ARTIFACT_DIR/ffplay-repro.log"
    maybe_remote_scp_from "/tmp/xset.txt" "$ARTIFACT_DIR/xset.txt"
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
