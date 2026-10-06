#!/usr/bin/env bash
# Rebuild the Multipass web vault from whatever vault the running Vaultwarden
# image carries, and swap it in. Run on the host that runs the container
# (/srv/multipass-dev on the dev box): the container name and directory are
# arguments so the same script serves a future production box.
#
#   bash update.sh [container=multipass-dev] [dir=/srv/multipass-dev]
#
# Needs python3 and ImageMagick (convert) on the host; apply_branding.py and
# brand/icon.svg next to this script's repo checkout (this file's directory).
set -euo pipefail
CONTAINER="${1:-multipass-dev}"
DIR="${2:-/srv/multipass-dev}"
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
docker cp "$CONTAINER:/web-vault" "$WORK/src"
python3 "$HERE/apply_branding.py" "$WORK/src" "$WORK/out" --icon "$HERE/../brand/icon.svg"
rm -rf "$DIR/web-vault.new"
cp -r "$WORK/out" "$DIR/web-vault.new"
rm -rf "$DIR/web-vault.old"
[ -d "$DIR/web-vault" ] && mv "$DIR/web-vault" "$DIR/web-vault.old"
mv "$DIR/web-vault.new" "$DIR/web-vault"
(cd "$DIR" && docker compose up -d)
docker restart "$CONTAINER" >/dev/null
echo "Multipass web vault updated from $(cat "$DIR/web-vault/version.json")"
