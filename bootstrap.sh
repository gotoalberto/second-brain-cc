#!/bin/bash
# Core bootstrap for the Second Brain — agent-agnostic, cross-platform.
# Sets up the vault engine (index + health) and points you at an integration.
#
#   git clone <this-repo> ~/Brain && bash ~/Brain/bootstrap.sh
#
# This installs NOTHING into any specific agent. Pick an integration afterwards:
#   - MCP server (any MCP agent):     integrations/mcp/README.md
#   - Command line (any shell agent): integrations/cli/README.md
#   - Claude Code (deepest):          bash integrations/claude-code/install.sh
set -euo pipefail
VAULT="${BRAIN_VAULT:-$(cd "$(dirname "$0")" && pwd)}"
PY3="$(command -v python3 || echo /usr/bin/python3)"
echo "== Second Brain — core bootstrap =="
echo "   vault: $VAULT"

echo "-> checking python3 and SQLite/FTS5 (the only hard requirement)"
"$PY3" - <<'PYEOF'
import sys, sqlite3
assert sys.version_info >= (3, 8), "Python 3.8+ required, found %s" % sys.version.split()[0]
c = sqlite3.connect(":memory:")
c.execute("CREATE VIRTUAL TABLE t USING fts5(b)")
print("   OK — Python", sys.version.split()[0], "· SQLite", sqlite3.sqlite_version, "· FTS5 available")
PYEOF

# Optional niceties. Obsidian is a great vault UI but not required; ripgrep is handy.
if command -v brew >/dev/null 2>&1; then
  [ -d /Applications/Obsidian.app ] || echo "   tip: 'brew install --cask obsidian' for a GUI over the vault (optional)"
  command -v rg >/dev/null 2>&1 || echo "   tip: 'brew install ripgrep' for faster ad-hoc search (optional)"
else
  echo "   tip: install Obsidian (https://obsidian.md) to browse the vault as a GUI — optional"
fi

echo "-> building the initial search index"
"$PY3" "$VAULT/_bin/index_vault.py" --full

echo "-> credentials module (1Password CLI 'op', optional)"
# No secrets are stored in this repo; notes only ever carry op://vault/item/field refs.
if command -v op >/dev/null 2>&1; then
  if [ -n "$(op account list 2>/dev/null || true)" ]; then
    echo "   op installed and an account is configured"
  else
    echo "   op installed but not signed in — run: op signin   (only if you use /secret)"
  fi
else
  echo "   'op' not found — install it only if you want the credentials module:"
  echo "     https://developer.1password.com/docs/cli/  (brew install --cask 1password-cli)"
fi

echo "-> health check"
"$PY3" "$VAULT/_bin/doctor.py" </dev/null | sed -n '1,6p'

cat <<EOF

== Core ready. Now pick how your agent talks to the vault ==

  1) MCP server  — any MCP agent (Claude Desktop, Cline, Cursor, Zed, ...)
                   see integrations/mcp/README.md
  2) CLI         — any agent that can run a shell, or you at a terminal
                   ln -s "$VAULT/integrations/cli/brain" /usr/local/bin/brain
                   see integrations/cli/README.md
  3) Claude Code — automatic recall, agents, slash commands (deepest)
                   bash integrations/claude-code/install.sh

You can use more than one, but avoid running two write-back integrations at once.
Open the vault in Obsidian ($VAULT) whenever you want a GUI.
EOF
