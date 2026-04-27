#!/usr/bin/env sh
# Portable keepalive pinger for the EduAlign Render backend.
# Use locally with cron/launchd or in any CI environment as a backup to the
# GitHub Actions workflow (.github/workflows/keepalive.yml).
#
# Override target with KEEPALIVE_URL=https://your-host/health
set -eu

URL="${KEEPALIVE_URL:-https://edualign-nymh.onrender.com/health}"

if curl -fsSL --max-time 30 "$URL" >/dev/null; then
  echo "ok $(date -u +%FT%TZ) $URL"
  exit 0
fi

echo "fail $(date -u +%FT%TZ) $URL" >&2
exit 1
