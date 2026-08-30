#!/bin/bash
# Installs the Brain system on a new machine.
# Usage:  git clone <vault-repo> ~/Brain && bash ~/Brain/bootstrap.sh
set -euo pipefail
VAULT="${BRAIN_VAULT:-$HOME/Brain}"
PY3=/usr/bin/python3
echo "== Brain bootstrap =="

command -v brew >/dev/null || { echo "Instala Homebrew primero: https://brew.sh"; exit 1; }
[ -d /Applications/Obsidian.app ] || { echo "-> instalando Obsidian"; brew install --cask obsidian; }
command -v rg >/dev/null || brew install ripgrep || true

echo "-> checking python3 and SQLite/FTS5"
$PY3 - <<'PYEOF'
import sqlite3; c=sqlite3.connect(':memory:')
c.execute('CREATE VIRTUAL TABLE t USING fts5(b)')
print("   FTS5 disponible, SQLite", sqlite3.sqlite_version)
PYEOF

echo "-> initial index"; $PY3 "$VAULT/_bin/index_vault.py" --full
echo "-> skills catalogue"; $PY3 "$VAULT/_bin/skills_index.py" </dev/null

echo "-> installing agents and skills into ~/.claude"
mkdir -p "$HOME/.claude/agents" "$HOME/.claude/skills"
cp -f "$VAULT/plugin/brain/agents/"*.md "$HOME/.claude/agents/" 2>/dev/null || true
# The whole skill, not just SKILL.md: several carry scripts/ and reference/ and without
# them they announce themselves but do not work.
for d in "$VAULT/plugin/brain/skills/"*/; do
  n=$(basename "$d")
  rm -rf "$HOME/.claude/skills/$n"
  cp -R "$d" "$HOME/.claude/skills/$n"
done

echo "-> wiring hooks into ~/.claude/settings.json"
$PY3 - <<PYEOF
import json, os
p=os.path.expanduser("~/.claude/settings.json")
st=json.load(open(p)) if os.path.exists(p) else {}
raw=open("$VAULT/plugin/brain/hooks/hooks.json").read().replace("__VAULT__", "$VAULT")
hooks=json.loads(raw)["hooks"]
st["hooks"]=hooks
json.dump(st, open(p,"w"), indent=2, ensure_ascii=False)
print("   hooks conectados:", ", ".join(sorted(hooks)))
PYEOF

echo "-> sync daemon"
# The plist in the repo carries the original machine's paths. They are rewritten here:
# copying it as-is installs a daemon pointing at a HOME that does not exist and that fails
# silently — the sync stops running and nobody notices until the day it is needed.
# notes. Both the old HOME and the old vault path are substituted.
PL="$HOME/Library/LaunchAgents/com.secondbrain.sync.plist"
SRC="$VAULT/_bin/com.secondbrain.sync.plist"
if [ -f "$SRC" ]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  sed -e "s#__VAULT__#$VAULT#g" \
      -e "s#__HOME__#$HOME#g" \
      "$SRC" > "$PL"
  # The plist names this directory; launchd will not start a job whose log path is missing.
  mkdir -p "$HOME/.claude/state/brain/logs"
  launchctl bootout "gui/$(id -u)/com.secondbrain.sync" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PL" && echo "   daemon active" \
    || echo "   WARNING: launchctl could not start it; the sync will still run in the Stop hook"
fi

echo "-> external tools"
for t in aws op; do
  command -v "$t" >/dev/null 2>&1 \
    || echo "   note: $t not found (only needed for optional modules: aws=S3, op=1Password)"
done

echo "-> credentials (1Password CLI, optional)"
# The credential module is OPTIONAL and uses the 1Password CLI (op). The repo stores NO
# secrets: notes only ever carry op://vault/item/field references. Skip if you do not use it.
if command -v op >/dev/null 2>&1; then
  if op account list >/dev/null 2>&1 && [ -n "$(op account list 2>/dev/null)" ]; then
    echo "   op installed and an account is configured"
  else
    echo "   op installed but not signed in — run: op signin"
  fi
else
  echo "   1Password CLI (op) not found — install it to use /secret (optional):"
  echo "     https://developer.1password.com/docs/cli/  (brew install --cask 1password-cli)"
fi

echo "-> health check"; $PY3 "$VAULT/_bin/doctor.py" </dev/null | tail -5
echo
echo "Done. Open the vault in Obsidian ($VAULT) and start a Claude session."
