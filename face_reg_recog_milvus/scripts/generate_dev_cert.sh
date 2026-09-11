#!/usr/bin/env bash
# Make a self-signed certificate for the frontend container.
#
#   ./scripts/generate_dev_cert.sh                 # localhost only
#   ./scripts/generate_dev_cert.sh 192.0.2.10      # also this LAN address
#   ./scripts/generate_dev_cert.sh my-host.local   # also this name
#
# The browser needs the address you type in the bar to appear in the certificate,
# so pass the LAN address if you open the UI from another device. The files are
# written to frontend/certs/ and are not tracked by git.
#
# Development only. The certificate is self-signed, so every browser shows a
# warning once, and you accept it.
set -euo pipefail

cert_dir="$(cd "$(dirname "$0")/.." && pwd)/frontend/certs"
mkdir -p "$cert_dir"

# localhost is always present: it is a secure context, so the camera works there
# with no warning at all.
san="DNS:localhost,IP:127.0.0.1"
for host in "$@"; do
    if [[ "$host" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        san="$san,IP:$host"
    else
        san="$san,DNS:$host"
    fi
done

openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
    -keyout "$cert_dir/dev.key" -out "$cert_dir/dev.crt" \
    -subj "/CN=${1:-localhost}" -addext "subjectAltName=$san" 2>/dev/null

chmod 644 "$cert_dir/dev.crt" "$cert_dir/dev.key"
echo "certificate written to frontend/certs/"
echo "valid for: $san"
