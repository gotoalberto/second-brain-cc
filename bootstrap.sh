#!/bin/bash
# Core bootstrap for the Second Brain: agent-agnostic, macOS and Linux.
# Sets up the vault engine (index and health), then offers the first run.
#
#   git clone <this-repo> ~/Brain && bash ~/Brain/bootstrap.sh
#
# It installs nothing into any agent and schedules nothing. Afterwards:
#   - the first run, one yes at a time:  bash integrations/first-run/setup.sh
#   - MCP server (any MCP agent):        integrations/mcp/README.md
#   - command line (any shell agent):    integrations/cli/README.md
#   - Claude Code (deepest):             bash integrations/claude-code/install.sh
set -euo pipefail
VAULT="${BRAIN_VAULT:-$(cd "$(dirname "$0")" && pwd)}"
PY3="$(command -v python3 || echo /usr/bin/python3)"
export BRAIN_VAULT="$VAULT"
echo "== Second Brain: core bootstrap =="
echo "   vault: $VAULT"

echo "-> checking python3 and SQLite/FTS5 (the only hard requirement)"
"$PY3" - <<'PYEOF'
import sys, sqlite3
assert sys.version_info >= (3, 9), "Python 3.9+ required, found %s" % sys.version.split()[0]
c = sqlite3.connect(":memory:")
c.execute("CREATE VIRTUAL TABLE t USING fts5(b)")
print("   OK: Python", sys.version.split()[0], "with SQLite", sqlite3.sqlite_version, "and FTS5")
PYEOF

echo "-> optional tools"
command -v git >/dev/null 2>&1 || echo "   git not found: the vault cannot sync between machines without it"
if command -v keepassxc-cli >/dev/null 2>&1; then
  echo "   keepassxc-cli found: credentials can live in a local KeePass database (the first run asks)"
else
  echo "   keepassxc-cli not found: install KeePassXC only if you want credentials in a KeePass database"
  echo "     macOS: brew install --cask keepassxc    Linux: your distribution's keepassxc package"
fi
[ -d /Applications/Obsidian.app ] || command -v obsidian >/dev/null 2>&1 \
  || echo "   tip: Obsidian (https://obsidian.md) gives the vault a GUI; optional"

echo "-> building the initial search index"
"$PY3" "$VAULT/_bin/index_vault.py" --full

echo "-> health check"
"$PY3" "$VAULT/_bin/doctor.py" </dev/null 2>/dev/null | sed -n '1,6p' || true

echo "-> first run"
bash "$VAULT/integrations/first-run/setup.sh"

cat <<EOF

== Core ready ==

  Connect your agent:
  1) MCP server  (Claude Desktop, Cline, Cursor, Zed, OpenCode, ...)  integrations/mcp/README.md
  2) CLI         (any agent that can run a shell, or you)             integrations/cli/README.md
  3) Claude Code (automatic recall, agents, skills)                   bash integrations/claude-code/install.sh

  The first run can be started, resumed or checked any time:
     bash integrations/first-run/setup.sh
     python3 integrations/first-run/first_run.py status

  Every test, each in a scratch HOME:  python3 _bin/run_all_tests.py
EOF
