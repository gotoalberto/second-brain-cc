#!/bin/sh
# Picks a python3 that actually runs, then execs it with every argument unchanged.
#
# launchd starts brain-sync, brain-tasks and brain-guardian through this instead of
# naming /usr/bin/python3 directly. /usr/bin/python3 is an xcrun shim: after an Xcode
# update whose license was not accepted it exits 69 without running anything, and every
# daemon pinned to it died in silence. Here it degrades to the next interpreter instead.
#
# Order (the first that answers `-c ""` with exit 0 wins):
#   each candidate with DEVELOPER_DIR=CommandLineTools (only when the caller did not set
#   DEVELOPER_DIR and that directory exists), then the same candidate as-is.
# Candidates: /usr/bin/python3, /opt/homebrew/bin/python3, /usr/local/bin/python3.
#
# Pure POSIX sh on purpose: it has to run before any Python is known to work.
# BRAIN_PY_CANDIDATES (colon-separated) and BRAIN_PY_CLT override the defaults; the
# tests use them, and so can a machine with its interpreter somewhere else.

CANDIDATES="${BRAIN_PY_CANDIDATES:-/usr/bin/python3:/opt/homebrew/bin/python3:/usr/local/bin/python3}"
CLT="${BRAIN_PY_CLT:-/Library/Developer/CommandLineTools}"

tried=""
OLD_IFS=$IFS
IFS=:
set -f
for c in $CANDIDATES; do
  IFS=$OLD_IFS
  [ -n "$c" ] || continue
  tried="$tried $c"
  [ -x "$c" ] || continue
  if [ -z "${DEVELOPER_DIR:-}" ] && [ -d "$CLT" ]; then
    if DEVELOPER_DIR="$CLT" "$c" -c "" >/dev/null 2>&1 </dev/null; then
      DEVELOPER_DIR="$CLT"
      export DEVELOPER_DIR
      exec "$c" "$@"
    fi
  fi
  if "$c" -c "" >/dev/null 2>&1 </dev/null; then
    exec "$c" "$@"
  fi
done

echo "pywrap: no working python3 (tried:$tried); if it is the Xcode license gate: sudo xcodebuild -license accept" >&2
exit 69
