#!/usr/bin/env python3
"""Runs the vault's periodic tasks, filtered by the machine it is running on.

The registry lives in the vault (90-Meta/scheduled-tasks.md) so every machine sees
the same list, but each task declares WHICH machine owns it. A task whose `machine`
column does not match this host is never executed here — the harness runs on several
machines and a task pinned to one must not fire on the others.

Invoked every 10 minutes by com.secondbrain.tasks (launchd). A task fires when:
  - its `machine` matches this host (or is `*`),
  - today matches its `days`,
  - its scheduled time has passed today,
  - and it has not already run today.

That last condition is what makes a 10-minute poll safe: a task scheduled at 06:00 runs
once, not six times an hour. It also means a machine that was asleep at 06:00 still runs
the task when it wakes — late is better than skipped. Use `catchup=no` to opt out.

Usage:
  tasks.py            run whatever is due on this machine
  tasks.py --list     show the registry as this machine sees it
  tasks.py --dry-run  say what would run, run nothing
  tasks.py --force <id>  run one task now, ignoring schedule and last-run
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
VAULT = HOME / "Brain"
REGISTRY = VAULT / "90-Meta" / "scheduled-tasks.md"
STATE_DIR = HOME / ".claude" / "state" / "brain"
STATE_FILE = STATE_DIR / "tasks-state.json"
LOG_DIR = STATE_DIR / "logs" / "tasks"
RUNNER_LOG = LOG_DIR / "_runner.log"

MAX_LOG_BYTES = 1_000_000
LOG_KEEP = 3
DEFAULT_TIMEOUT = 1800  # 30 min; a periodic task that runs longer is a bug, not a feature


def host() -> str:
    return socket.gethostname().split(".")[0]


def now() -> dt.datetime:
    return dt.datetime.now()


# ---------------------------------------------------------------- logging


def rotate(path: Path) -> None:
    """Keep logs bounded. Brain's convention: everything logs, and logs rotate."""
    if not path.exists() or path.stat().st_size < MAX_LOG_BYTES:
        return
    for i in range(LOG_KEEP - 1, 0, -1):
        older, newer = path.with_suffix(f".{i}.log"), path.with_suffix(f".{i - 1}.log")
        if i - 1 == 0:
            newer = path
        if newer.exists():
            older.unlink(missing_ok=True)
            newer.rename(older)


def log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rotate(path)
    stamp = now().strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a") as fh:
        fh.write(f"[{stamp}] {message}\n")


# ---------------------------------------------------------------- state


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(STATE_FILE)


# ---------------------------------------------------------------- registry


def parse_days(spec: str) -> set[int]:
    """`*` = every day. Otherwise ISO weekdays: 1=Mon .. 7=Sun. Accepts `1-5`, `1,3,5`, `6`."""
    spec = spec.strip()
    if spec in ("*", "", "-"):
        return set(range(1, 8))
    days: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            days.update(range(int(a), int(b) + 1))
        elif part:
            days.add(int(part))
    return days


def read_registry() -> list[dict]:
    """Parse the markdown table out of the registry note.

    Rows look like:
      | id | machine | time | days | type | command | enabled | notes |
    """
    if not REGISTRY.exists():
        return []
    tasks = []
    for line in REGISTRY.read_text().splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 7:
            continue
        if cells[0].lower() in ("id", "---") or set(cells[0]) <= {"-", ":"}:
            continue
        # Strip markdown emphasis and code ticks the note uses for readability
        cells = [re.sub(r"^[`*_]+|[`*_]+$", "", c) for c in cells]
        # `--` marks a row with no schedule (ad-hoc, started by hand). It is kept so the
        # registry stays the complete inventory, but it is never due.
        if not re.match(r"^(\d{1,2}:\d{2}|--)$", cells[2]):
            continue
        tasks.append(
            {
                "id": cells[0],
                "machine": cells[1],
                "time": cells[2],
                "days": cells[3],
                "type": cells[4].lower(),
                "command": cells[5],
                "enabled": cells[6].lower() in ("yes", "sí", "si", "true", "1", "on"),
                "notes": cells[7] if len(cells) > 7 else "",
            }
        )
    return tasks


def mine(task: dict) -> bool:
    return task["machine"] in ("*", host())


def due(task: dict, state: dict) -> tuple[bool, str]:
    """Returns (should_run, reason_if_not)."""
    if not task["enabled"]:
        return False, "disabled"
    if not mine(task):
        return False, f"belongs to {task['machine']}"
    if task["time"] == "--":
        return False, "manual only (no schedule)"
    if task["type"] != "shell":
        return False, f"type '{task['type']}' is not run by this runner"

    today = now()
    if today.isoweekday() not in parse_days(task["days"]):
        return False, "not scheduled today"

    hh, mm = (int(x) for x in task["time"].split(":"))
    scheduled = today.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if today < scheduled:
        return False, f"not yet ({task['time']})"

    last = state.get(task["id"], {}).get("last_run_date")
    if last == today.strftime("%Y-%m-%d"):
        return False, "already ran today"

    return True, ""


# ---------------------------------------------------------------- running


def run_task(task: dict, state: dict) -> int:
    task_log = LOG_DIR / f"{task['id']}.log"
    started = now()
    log(task_log, f"START  {task['id']}  (scheduled {task['time']}, host {host()})")
    log(RUNNER_LOG, f"running {task['id']} on {host()}")

    try:
        proc = subprocess.run(
            task["command"],
            shell=True,
            cwd=str(VAULT),
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT,
        )
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        rc, out, err = 124, "", f"timed out after {DEFAULT_TIMEOUT}s"
    except Exception as exc:  # a broken command must not kill the whole runner
        rc, out, err = 1, "", f"{type(exc).__name__}: {exc}"

    for stream, label in ((out, "out"), (err, "err")):
        for line in (stream or "").splitlines():
            log(task_log, f"  {label}| {line}")

    secs = (now() - started).total_seconds()
    log(task_log, f"END    {task['id']}  exit={rc}  {secs:.1f}s")

    entry = state.setdefault(task["id"], {})
    entry["last_run_date"] = started.strftime("%Y-%m-%d")
    entry["last_run_at"] = started.isoformat(timespec="seconds")
    entry["last_exit"] = rc
    entry["host"] = host()
    return rc


# ---------------------------------------------------------------- cli


def cmd_list(tasks: list[dict], state: dict) -> None:
    print(f"host: {host()}   registry: {REGISTRY}")
    if not tasks:
        print("  (registry empty or unreadable)")
        return
    for t in tasks:
        ok, why = due(t, state)
        last = state.get(t["id"], {}).get("last_run_at", "never")
        owner = "this machine" if mine(t) else t["machine"]
        status = "DUE NOW" if ok else why
        print(f"\n  {t['id']}")
        print(f"    machine : {owner}")
        when = "manual only" if t["time"] == "--" else f"{t['time']}  days={t['days']}"
        print(f"    when    : {when}   type={t['type']}")
        print(f"    status  : {status}")
        print(f"    last run: {last}")


def main() -> int:
    ap = argparse.ArgumentParser(description="run the vault's periodic tasks for this machine")
    ap.add_argument("--list", action="store_true", help="show the registry as this machine sees it")
    ap.add_argument("--dry-run", action="store_true", help="say what would run, run nothing")
    ap.add_argument("--force", metavar="ID", help="run one task now, ignoring schedule and last-run")
    args = ap.parse_args()

    tasks = read_registry()
    state = load_state()

    if args.list:
        cmd_list(tasks, state)
        return 0

    if args.force:
        for t in tasks:
            if t["id"] == args.force:
                if t["type"] != "shell":
                    print(f"{t['id']}: type '{t['type']}' is not run by this runner", file=sys.stderr)
                    return 2
                rc = run_task(t, state)
                save_state(state)
                print(f"{t['id']}: exit={rc}  (log: {LOG_DIR / (t['id'] + '.log')})")
                return rc
        print(f"no task with id '{args.force}'", file=sys.stderr)
        return 2

    ran = 0
    for t in tasks:
        ok, _ = due(t, state)
        if not ok:
            continue
        if args.dry_run:
            print(f"would run: {t['id']}")
            ran += 1
            continue
        run_task(t, state)
        ran += 1

    if ran and not args.dry_run:
        save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
