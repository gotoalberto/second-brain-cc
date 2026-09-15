#!/bin/bash
# Installs the Claude Code integration: skills and agents, the hooks, and (with your yes) the
# recommended settings. Run the core bootstrap first (bash bootstrap.sh), then:
#     bash integrations/claude-code/install.sh
# Scheduled jobs, KeePass, Google accounts and the rest are not installed here: the first run
# (bash integrations/first-run/setup.sh) asks for each one.
set -euo pipefail
VAULT="${BRAIN_VAULT:-$(cd "$(dirname "$0")/../.." && pwd)}"
PY3="$(command -v python3 || echo /usr/bin/python3)"
export BRAIN_VAULT="$VAULT"
echo "== Claude Code integration =="

echo "-> skills catalogue"
"$PY3" "$VAULT/_bin/skills_index.py" </dev/null || true

echo "-> skills and agents into ~/.claude (the vault's copy is canonical; __VAULT__ becomes $VAULT)"
"$PY3" "$VAULT/_bin/install_plugin.py" install

echo "-> hooks into ~/.claude/settings.json (merged with what is there, backed up, nothing else touched)"
"$PY3" "$VAULT/_bin/guardian.py" repair --hooks-only

echo "-> recommended settings: only what you do not have, and only with your yes"
if [ -t 0 ]; then
  "$PY3" "$VAULT/_bin/claude_settings.py" merge
else
  "$PY3" "$VAULT/_bin/claude_settings.py" show
  echo "   not a terminal: nothing merged. To merge later: python3 _bin/claude_settings.py merge"
fi

echo
echo "Done. Start a Claude Code session in $VAULT: /recall, /save, /task, /ctx, /kp and /vault-doctor are live."
echo "KeePass, Google accounts, alert email, scheduled jobs and routines: bash integrations/first-run/setup.sh"
