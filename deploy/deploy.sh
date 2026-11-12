#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${DEPLOY_ENV_FILE:-$ROOT_DIR/deploy/.deploy.env}"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

: "${DEPLOY_HOST:?Set DEPLOY_HOST in deploy/.deploy.env}"
: "${DEPLOY_USER:=root}"
: "${APP_DIR:=/opt/property-hunt}"
: "${REPO_URL:=https://github.com/guofeng201507/property-hunt.git}"
: "${BASIC_AUTH_USER:?Set BASIC_AUTH_USER in deploy/.deploy.env}"
: "${BASIC_AUTH_PASS:?Set BASIC_AUTH_PASS in deploy/.deploy.env}"
: "${SSH_KEY:?Set SSH_KEY in deploy/.deploy.env}"

if [ ! -f "$SSH_KEY" ]; then
  echo "SSH key not found: $SSH_KEY" >&2
  exit 1
fi
chmod 600 "$SSH_KEY"

if [[ ! "$BASIC_AUTH_PASS" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "BASIC_AUTH_PASS must contain only letters, numbers, dot, underscore or hyphen." >&2
  exit 1
fi

if [ ! -f "$ROOT_DIR/.env" ]; then
  echo "Missing $ROOT_DIR/.env (URA_ACCESS_KEY)." >&2
  exit 1
fi
if [ ! -f "$ROOT_DIR/db/property.db" ]; then
  echo "Missing $ROOT_DIR/db/property.db. Run make ingest first." >&2
  exit 1
fi

SSH_OPTS=(-i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)
REMOTE="$DEPLOY_USER@$DEPLOY_HOST"
SNAPSHOT="$(mktemp "${TMPDIR:-/tmp}/property-hunt-deploy.XXXXXX.db")"
trap 'rm -f "$SNAPSHOT"' EXIT

echo "==> Creating consistent SQLite snapshot"
sqlite3 "$ROOT_DIR/db/property.db" ".backup '$SNAPSHOT'"

echo "==> Preparing remote directories"
ssh "${SSH_OPTS[@]}" "$REMOTE" "mkdir -p '$APP_DIR/db' '$APP_DIR/data/geo' '$APP_DIR/.streamlit'"

echo "==> Uploading SQLite database"
rsync -az -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
  "$SNAPSHOT" "$REMOTE:$APP_DIR/db/property.db"

echo "==> Uploading .env"
rsync -az -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
  "$ROOT_DIR/.env" "$REMOTE:$APP_DIR/.env"

if [ -d "$ROOT_DIR/data/geo" ] && [ -n "$(find "$ROOT_DIR/data/geo" -maxdepth 1 -type f -print -quit)" ]; then
  echo "==> Uploading geo layers"
  rsync -az -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
    "$ROOT_DIR/data/geo/" "$REMOTE:$APP_DIR/data/geo/"
else
  echo "==> No local data/geo layers; skipping (app will show geo as not loaded)"
fi

echo "==> Running server bootstrap"
ssh "${SSH_OPTS[@]}" "$REMOTE" \
  "APP_DIR='$APP_DIR' REPO_URL='$REPO_URL' BASIC_AUTH_USER='$BASIC_AUTH_USER' BASIC_AUTH_PASS='$BASIC_AUTH_PASS' bash -s" \
  < "$ROOT_DIR/deploy/bootstrap.sh"

echo "==> Public check"
curl -fsS -u "$BASIC_AUTH_USER:$BASIC_AUTH_PASS" -o /dev/null "http://$DEPLOY_HOST/" \
  && echo "OK: http://$DEPLOY_HOST/ (Basic Auth user: $BASIC_AUTH_USER)"

echo "Done."
