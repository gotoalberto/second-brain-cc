#!/bin/bash
# Installs the Claude Code integration: agents, skills, hooks and the git-sync daemon.
# Run the core bootstrap first (bash bootstrap.sh), then this:
#     bash integrations/claude-code/install.sh
set -euo pipefail
VAULT="${BRAIN_VAULT:-$(cd "$(dirname "$0")/../.." && pwd)}"
PY3=/usr/bin/python3
PLUGIN="$VAULT/integrations/claude-code/plugin/brain"
echo "== Claude Code integration =="

echo "-> skills catalogue"; $PY3 "$VAULT/_bin/skills_index.py" </dev/null || true

echo "-> installing agents and skills into ~/.claude"
mkdir -p "$HOME/.claude/agents" "$HOME/.claude/skills"
cp -f "$PLUGIN/agents/"*.md "$HOME/.claude/agents/" 2>/dev/null || true
# Copy each skill whole (some carry scripts/ and reference/), not just SKILL.md.
for d in "$PLUGIN/skills/"*/; do
  n=$(basename "$d")
  rm -rf "$HOME/.claude/skills/$n"
  cp -R "$d" "$HOME/.claude/skills/$n"
done

echo "-> wiring hooks into ~/.claude/settings.json"
$PY3 - <<PYEOF
import json, os
p = os.path.expanduser("~/.claude/settings.json")
st = json.load(open(p)) if os.path.exists(p) else {}
raw = open("$PLUGIN/hooks/hooks.json").read().replace("__VAULT__", "$VAULT")
st["hooks"] = json.loads(raw)["hooks"]
json.dump(st, open(p, "w"), indent=2, ensure_ascii=False)
print("   hooks connected:", ", ".join(sorted(st["hooks"])))
PYEOF

echo "-> git-sync daemon (macOS launchd; optional)"
PL="$HOME/Library/LaunchAgents/com.secondbrain.sync.plist"
SRC="$VAULT/_bin/com.secondbrain.sync.plist"
if [ "$(uname)" = "Darwin" ] && [ -f "$SRC" ]; then
  mkdir -p "$HOME/Library/LaunchAgents" "$HOME/.claude/state/brain/logs"
  sed -e "s#__VAULT__#$VAULT#g" -e "s#__HOME__#$HOME#g" "$SRC" > "$PL"
  launchctl bootout "gui/$(id -u)/com.secondbrain.sync" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PL" && echo "   daemon active" \
    || echo "   WARNING: launchctl could not start it; sync still runs in the Stop hook"
else
  echo "   not macOS (or no plist) — the Stop hook syncs on session end; for periodic"
  echo "   sync add a cron/systemd job that runs: python3 $VAULT/_bin/vault_sync.py"
fi

echo
echo "Done. Start a Claude Code session in $VAULT — /recall, /save, /task, /secret are live."
