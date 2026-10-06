#!/usr/bin/env bash
# Follow upstream Vaultwarden (and with it the web vault it bundles) without a
# human, and put the result back the way it was if anything about it is wrong.
#
#   bash auto-update.sh [dir=/srv/multipass-dev] [container=multipass-dev]
#
# Run weekly by multipass-update.timer. Steps:
#   1. newest 1.x.y-alpine tag on Docker Hub; stop if it is not newer than the
#      one in docker-compose.yml;
#   2. pull it, bump the tag, rebuild the branded vault from the NEW image
#      (apply_branding.py exits non-zero if an upstream string it relies on
#      changed - that is the "look at this" signal, and nothing is swapped);
#   3. start it and check /alive, the login page title and the logo;
#   4. any failure: restore the old compose file and vault, restart, exit 1
#      (the journal line is the alert; nothing half-branded ever stays up).
# It never touches data/.
set -uo pipefail
DIR="${1:-/srv/multipass-dev}"
CONTAINER="${2:-multipass-dev}"
HERE="$(cd "$(dirname "$0")" && pwd)"
COMPOSE="$DIR/docker-compose.yml"
log() { echo "multipass-update: $*"; }

CURRENT="$(grep -o 'vaultwarden/server:[0-9][0-9.]*' "$COMPOSE" | head -1 | cut -d: -f2)"
LATEST="$(curl -fsS 'https://hub.docker.com/v2/repositories/vaultwarden/server/tags?page_size=50&name=-alpine' \
  | python3 -c "
import sys, json, re
tags = [t['name'][:-7] for t in json.load(sys.stdin)['results']
        if re.fullmatch(r'\d+\.\d+\.\d+-alpine', t['name'])]
tags.sort(key=lambda v: tuple(map(int, v.split('.'))))
print(tags[-1] if tags else '')
")"
[ -n "$LATEST" ] && [ -n "$CURRENT" ] || { log "could not read versions (current='$CURRENT' latest='$LATEST')"; exit 1; }
newest="$(printf '%s\n%s\n' "$CURRENT" "$LATEST" | sort -V | tail -1)"
if [ "$newest" = "$CURRENT" ]; then log "up to date ($CURRENT)"; exit 0; fi
log "updating $CURRENT -> $LATEST"

BACKUP="$(mktemp -d)"
cp "$COMPOSE" "$BACKUP/docker-compose.yml"
[ -d "$DIR/web-vault" ] && cp -r "$DIR/web-vault" "$BACKUP/web-vault"

rollback() {
  log "FAILED ($1) - rolling back to $CURRENT"
  cp "$BACKUP/docker-compose.yml" "$COMPOSE"
  rm -rf "$DIR/web-vault"
  [ -d "$BACKUP/web-vault" ] && cp -r "$BACKUP/web-vault" "$DIR/web-vault"
  (cd "$DIR" && docker compose up -d >/dev/null 2>&1)
  exit 1
}

docker pull "vaultwarden/server:$LATEST-alpine" >/dev/null || rollback "pull"
sed -i "s#vaultwarden/server:$CURRENT-alpine#vaultwarden/server:$LATEST-alpine#" "$COMPOSE"
(cd "$DIR" && docker compose up -d >/dev/null 2>&1) || rollback "compose up"
sleep 8
# build the branded vault from the NEW image's own vault
WORK="$(mktemp -d)"
docker cp "$CONTAINER:/web-vault" "$WORK/src" || rollback "docker cp"
python3 "$HERE/apply_branding.py" "$WORK/src" "$WORK/out" --icon "$HERE/../brand/icon.svg" \
  || rollback "branding no longer matches upstream"
rm -rf "$DIR/web-vault"; cp -r "$WORK/out" "$DIR/web-vault"
docker restart "$CONTAINER" >/dev/null
sleep 8
curl -fsS http://127.0.0.1:8222/alive >/dev/null || rollback "/alive"
# the page title is set by the app's JS, so check the manifest (static) instead
curl -fsS http://127.0.0.1:8222/manifest.json | grep -q '"name": *"Multipass"' || rollback "manifest is not Multipass"
curl -fsS http://127.0.0.1:8222/images/logo.svg | grep -q "<title>Multipass" || rollback "logo"
rm -rf "$BACKUP" "$WORK"
log "ok: now on $LATEST ($(cat "$DIR/web-vault/version.json"))"
