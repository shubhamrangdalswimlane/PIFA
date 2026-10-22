#!/bin/bash
set -euo pipefail

if [ -z "${SFTP_PUBLIC_KEY:-}" ]; then
  echo "SFTP_PUBLIC_KEY is required (public key of files-svc)" >&2
  exit 1
fi

# Persist host keys on the disk so files-svc can pin them.
mkdir -p /home/.hostkeys
chmod 700 /home/.hostkeys
for type in ed25519 rsa; do
  key="/home/.hostkeys/ssh_host_${type}_key"
  [ -f "$key" ] || ssh-keygen -q -t "$type" -f "$key" -N ''
  cp "$key" "$key.pub" /etc/ssh/
done

mkdir -p /home/pifa/.ssh/keys
echo "$SFTP_PUBLIC_KEY" > /home/pifa/.ssh/keys/files-svc.pub

# atmoz/sftp creates and chowns these folders inside the chroot (/home/pifa).
DIRS="files,files/inbound,files/inbound/forecast,files/inbound/inventory,files/inbound/allocation,files/processed,files/rejected,files/outbound"
exec /entrypoint "pifa::1001:1001:${DIRS}"
