#!/bin/bash
# Installs (or removes) the periodic "tick" that drives the scheduler. One crontab entry
# runs run.py --tick every 5 minutes; run.py itself decides which tasks are due.
# Works on macOS and Linux (crontab). For Windows use Task Scheduler to call run.py --tick.
#
#   bash install-cron.sh            # install / update the tick
#   bash install-cron.sh --every 1  # tick every 1 minute instead of 5
#   bash install-cron.sh --uninstall
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VAULT="${BRAIN_VAULT:-$(cd "$HERE/../.." && pwd)}"
PY3="$(command -v python3 || echo /usr/bin/python3)"
STATE="${BRAIN_SCHEDULER_STATE:-$HOME/.second-brain/scheduler}"
MARK="# second-brain-scheduler"
EVERY=5
UNINSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --every) EVERY="$2"; shift 2;;
    --uninstall) UNINSTALL=1; shift;;
    *) echo "unknown arg: $1"; exit 1;;
  esac
done

# Current crontab without our previous line.
current="$(crontab -l 2>/dev/null | grep -v "$MARK" || true)"

if [ "$UNINSTALL" = "1" ]; then
  printf '%s\n' "$current" | crontab -
  echo "removed the second-brain scheduler tick from crontab."
  exit 0
fi

mkdir -p "$STATE/logs"
line="*/$EVERY * * * * BRAIN_VAULT=$VAULT $PY3 $HERE/run.py --tick >> $STATE/logs/tick.log 2>&1 $MARK"
{ printf '%s\n' "$current"; printf '%s\n' "$line"; } | crontab -
echo "installed tick (every $EVERY min):"
echo "  $line"
echo "state + logs: $STATE"
echo
echo "Next: set your agent, e.g.  export BRAIN_AGENT_CMD=$HERE/agent-runners/claude.sh"
echo "and enable a task (set 'enabled: true' in a file under $HERE/tasks/)."
