#!/bin/bash

# Script to build and transfer dwm binary to QEMU VM
# Usage: ./qemu.sh [config] [vm-ip] [username]

CONFIG=${1:-"qemu"}            # Configuration: default, qemu (default to qemu)
VM_IP=${2:-"192.168.122.48"}   # Default QEMU/libvirt IP
USERNAME=${3:-"test"}          # Default username
PASSWORD="test"                # VM password

# Build dwm with specified configuration
echo "Building dwm with '$CONFIG' configuration..."
case $CONFIG in
    "qemu")
        make qemu
        ;;
    "default")
        make clean && make
        ;;
    *)
        echo "Error: Unknown configuration '$CONFIG'"
        echo "Available configurations: default, qemu"
        exit 1
        ;;
esac

if [ ! -f "./dwm" ]; then
    echo "Error: Build failed. dwm binary not found."
    exit 1
fi

echo "Transferring dwm to VM at $VM_IP..."

# Check if sshpass is available
if ! command -v sshpass &> /dev/null; then
    echo "sshpass not found. Installing..."
    sudo apt-get update && sudo apt-get install -y sshpass
fi

# Copy dwm binary
sshpass -p "$PASSWORD" scp ./dwm $USERNAME@$VM_IP:~/dwm

# Copy config.h for reference
sshpass -p "$PASSWORD" scp ./config.h $USERNAME@$VM_IP:~/config.h

# Optional: copy startup script
if [ -f "./start-dwm.sh" ]; then
    sshpass -p "$PASSWORD" scp ./start-dwm.sh $USERNAME@$VM_IP:~/start-dwm.sh
fi

# Replace system dwm binary
echo "Installing dwm to /usr/local/bin/..."
sshpass -p "$PASSWORD" ssh $USERNAME@$VM_IP "echo '$PASSWORD' | sudo -S cp ~/dwm /usr/local/bin/dwm && echo '$PASSWORD' | sudo -S chmod +x /usr/local/bin/dwm"

echo "Transfer complete!"
echo "SSH into VM: ssh $USERNAME@$VM_IP"
echo "Run dwm: dwm (or ./dwm from home directory)"
