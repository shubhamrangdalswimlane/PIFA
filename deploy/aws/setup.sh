#!/usr/bin/env bash
# Writes deploy/aws/.env for the single-server AWS deployment: host names, random secrets and the SFTP key pair.
#
#   ./setup.sh                     # on the EC2 server: uses its public IP and free *.sslip.io host names
#   ./setup.sh 3.12.34.56          # same, with an explicit public (Elastic) IP
#   APP_HOST=pifa.example.com AUTH_HOST=auth.example.com ./setup.sh   # your own domain (both names must point to the server)
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then
  echo ".env already exists. Delete it first if you really want new secrets (existing data would stop working)." >&2
  exit 1
fi

# Random alphanumeric string of the given length (no characters that need quoting).
rand() { head -c 96 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | cut -c1-"$1"; }

if [ -z "${APP_HOST:-}" ] || [ -z "${AUTH_HOST:-}" ]; then
  ip="${1:-}"
  if [ -z "$ip" ]; then
    # EC2 instance metadata (IMDSv2): the server's own public IPv4 address.
    token=$(curl -s -m 3 -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60" || true)
    ip=$(curl -s -m 3 -H "X-aws-ec2-metadata-token: $token" http://169.254.169.254/latest/meta-data/public-ipv4 || true)
  fi
  if ! [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Could not find the public IP. Run: ./setup.sh <public-ip>   or set APP_HOST and AUTH_HOST." >&2
    exit 1
  fi
  dashed="${ip//./-}"
  APP_HOST="app.${dashed}.sslip.io"
  AUTH_HOST="auth.${dashed}.sslip.io"
fi

# SFTP key pair for files-svc (OpenSSH format). The private key goes into .env on one line with literal \n.
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
ssh-keygen -q -t ed25519 -N "" -C files-svc -f "$tmp/key"
sftp_public=$(cut -d' ' -f1,2 "$tmp/key.pub")" files-svc"
sftp_private=$(awk '{printf "%s%c%c", $0, 92, 110}' "$tmp/key")  # each line break becomes a literal backslash + n

seed=$(rand 16)
kc_admin=$(rand 20)

umask 077
cat > .env <<ENV
APP_HOST=$APP_HOST
AUTH_HOST=$AUTH_HOST
POSTGRES_PASSWORD=$(rand 24)
KC_ADMIN_PASSWORD=$kc_admin
PIFA_SEED_PASSWORD=$seed
SVC_CLIENT_SECRET=$(rand 40)
DROOLS_PASSWORD=$(rand 24)
UPSTREAM_CLIENT_SECRET=$(rand 40)
SFTP_PUBLIC_KEY="$sftp_public"
SFTP_PRIVATE_KEY="$sftp_private"
ENV

cat <<DONE

.env written (deploy/aws/.env, readable only by you).

  Web app:            https://$APP_HOST
  Keycloak sign-in:   https://$AUTH_HOST   (admin console: /admin, user kcadmin)

  Password of all 11 PIFA users (sm.north ... admin):  $seed
  Keycloak admin password:                             $kc_admin

Save both passwords now (they are also in .env). Next:
  docker compose -f docker-compose.aws.yml up -d --build
DONE
