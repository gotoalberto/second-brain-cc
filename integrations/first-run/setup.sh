#!/bin/bash
# The first run: asks, one step at a time, whether to connect each optional piece (a KeePass
# database, Google accounts, coordinating with other machines over a shared folder, alert email,
# the MCP server, scheduled jobs, the Remote Control server, CLI-agent routines), and where to keep
# files, the one required step. Nothing is installed without a yes; answers are remembered, so it is
# safe to re-run.
#
#   bash integrations/first-run/setup.sh            ask what is left
#   bash integrations/first-run/setup.sh --dry-run  show what would be installed, save nothing
set -u
VAULT="${BRAIN_VAULT:-$(cd "$(dirname "$0")/../.." && pwd)}"
PY3="$(command -v python3 || echo /usr/bin/python3)"

if [ ! -t 0 ]; then
  echo "The first run asks questions and needs a terminal. Run it from one:"
  echo "  bash $VAULT/integrations/first-run/setup.sh"
  echo "Unattended machines and CI can set up the default files directory and decline the rest instead:"
  echo "  python3 $VAULT/integrations/first-run/first_run.py skip-all"
  exit 0
fi

BRAIN_VAULT="$VAULT" exec "$PY3" "$VAULT/integrations/first-run/first_run.py" run "$@"
