#!/usr/bin/env bash
# Runs one of the animated-video skill's tools with its runtime ready.
#   usage: av.sh setup              build or check the runtime (~/.cache/animated-video)
#          av.sh <tool> [args...]   node tools/<tool>.mjs args, with Playwright on the require path
# The runtime lives outside the vault, per machine: a pinned Playwright in ANIMATED_VIDEO_RUNTIME
# (default ~/.cache/animated-video) and its Chromium in Playwright's own cache. ffmpeg comes from
# the system. Added in this repository; not part of upstream's skill (see SOURCE.md).
set -euo pipefail
SKILL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RT="${ANIMATED_VIDEO_RUNTIME:-$HOME/.cache/animated-video}"
PW_VERSION="1.64.0"

usage() { sed -n 3,4p "$0" | sed 's/^# //'; }

setup() {
  command -v node >/dev/null || { echo "node is missing (Node 18+ needed)"; exit 1; }
  command -v ffmpeg >/dev/null || { echo "ffmpeg is missing (install it with the system package manager)"; exit 1; }
  if [ ! -f "$RT/node_modules/playwright/package.json" ] || ! grep -q "\"version\": \"$PW_VERSION\"" "$RT/node_modules/playwright/package.json"; then
    mkdir -p "$RT"
    [ -f "$RT/package.json" ] || printf '{"name":"animated-video-runtime","private":true}\n' > "$RT/package.json"
    (cd "$RT" && npm install --silent --no-audit --no-fund "playwright@$PW_VERSION")
  fi
  (cd "$RT" && npx --yes playwright install chromium >/dev/null)
  printf 'ok %s\n' "$PW_VERSION" > "$RT/.ready"
}

[ $# -ge 1 ] || { usage; exit 2; }
case "$1" in
  --pinned-version) echo "$PW_VERSION"; exit 0;;
  setup) setup; echo "runtime ready in $RT"; exit 0;;
esac
tool="$1"; shift
case "$tool" in
  *[!A-Za-z0-9_-]*) echo "no tool $tool (see $SKILL/tools)"; exit 2;;
esac
{ [ -f "$RT/.ready" ] && grep -q "$PW_VERSION" "$RT/.ready"; } || setup
[ -f "$SKILL/tools/$tool.mjs" ] || { echo "no tool $tool (see $SKILL/tools)"; exit 2; }
export NODE_PATH="$RT/node_modules${NODE_PATH:+:$NODE_PATH}"
exec node "$SKILL/tools/$tool.mjs" "$@"
