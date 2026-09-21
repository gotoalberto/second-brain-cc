#!/usr/bin/env python3
"""Runs the vault's periodic tasks, filtered by the machine it is running on.

The registry lives in the vault (90-Meta/scheduled-tasks.md) so every machine sees
the same list, but each task declares WHICH machine owns it. A task whose `machine`
column does not match this host is never executed here — the harness runs on several
machines and a task pinned to one must not fire on the others.

Invoked every 10 minutes by the scheduler accepted at first run (launchd com.secondbrain.tasks, a
systemd user timer or a cron line second-brain-tasks). A task fires when:
  - its `machine` is `*`, this host's name, or any form machine_identity.machine_is_mine()
    accepts for this machine (its key, its uuid, a historical key),
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

Task types:
  shell       the runner executes `command` with the vault as working directory
  agent       `command` is a routine file (90-Meta/routines/<id>.md); its body is handed
              to the CLI agent named in 90-Meta/agent-command.txt (or BRAIN_AGENT_CMD),
              followed by the routine's own `agent_args`. First, routine_requires.py checks
              that this machine has the repos, programs and paths the routine needs (its
              agent_args and its `requires:` line); a gap refuses the run, exit 2, before any
              token is read. The run goes through
              routine_auth_core: a token from the pool in 90-Meta/routine-tokens.json, read
              from KeePass, is the only credential in an environment built from scratch;
              a refused or limited token fails over to the next. Each attempt gets a run id,
              a private scratch directory under <brain state>/routine-scratch (granted with
              --add-dir, deleted on success, kept 7 days on failure) and a prompt that wraps
              the body in an explicit order to run it now. A routine whose contract requires
              sends succeeds only if google.py send logged them under that run id.
              A failure raises an alert through the guardian's channel naming what to do; a
              success clears it.
  claude-app  inventory only: run by the Claude app's own scheduler, never by this runner
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import errno
import fcntl
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# The due-ness rule is shared with the guardian's status report: one rule, one place.
from guardian_core import domain as GD  # noqa: E402

HOME = Path.home()
# The vault is BRAIN_VAULT, else the repository this file lives in.
VAULT = Path(os.environ.get("BRAIN_VAULT") or Path(__file__).resolve().parent.parent)
REGISTRY = VAULT / "90-Meta" / "scheduled-tasks.md"
# Resolved like brainlib.STATE: the legacy ~/.claude/state/brain until it is migrated.
import brain_paths  # noqa: E402

STATE_DIR = Path(brain_paths.effective_state_dir())
STATE_FILE = STATE_DIR / "tasks-state.json"
LOG_DIR = STATE_DIR / "logs" / "tasks"
RUNNER_LOG = LOG_DIR / "_runner.log"
# Agent routines' token pool state and failed-attempt log live where the guardian reads them.
ROUTINE_AUTH_STATE = Path(brain_paths.state_dir()) / "routine-auth-state.json"
ROUTINE_AUTH_LOG = Path(brain_paths.state_dir()) / "logs" / "routine-auth.log"
# One private scratch directory per routine attempt, granted to the CLI with --add-dir.
ROUTINE_SCRATCH_DIR = Path(brain_paths.state_dir()) / "routine-scratch"
# google.py send appends every delivered message here; a routine's delivery is checked against it.
MAIL_SENT_LOG = Path(brain_paths.state_dir()) / "logs" / "mail-sent.jsonl"
CLI_HEALTH_CACHE: dict = {}          # template -> CliResolver: the CLI is checked once per process

MAX_LOG_BYTES = 1_000_000
LOG_KEEP = 3
DEFAULT_TIMEOUT = 1800  # 30 min; a periodic task that runs longer is a bug, not a feature
STATE_LOCK_TIMEOUT = 30  # seconds a save waits for another run's save before giving up


def host() -> str:
    return socket.gethostname().split(".")[0]


def now() -> dt.datetime:
    return dt.datetime.now()


# ---------------------------------------------------------------- logging


def rotate(path: Path) -> None:
    """Keep logs bounded. Brain's convention: everything logs, and logs rotate."""
    path = Path(path)
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
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rotate(path)
    stamp = now().strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a") as fh:
        fh.write(f"[{stamp}] {message}\n")


# ---------------------------------------------------------------- state


def load_state() -> dict:
    try:
        state = json.loads(Path(STATE_FILE).read_text())
    except (FileNotFoundError, ValueError):  # ValueError: JSONDecodeError and undecodable bytes
        return {}
    return state if isinstance(state, dict) else {}


def _last_run_at(entry) -> str:
    return str(entry.get("last_run_at") or "") if isinstance(entry, dict) else ""


def merge_state(current: dict, mine: dict, changed) -> dict:
    """What a run writes back: the state as it is on disk now, plus this run's own entries.

    Only the ids in `changed` are taken from `mine`. For each, an entry on disk that is newer
    by `last_run_at` (a run of the same task that started after this one) is kept.
    Neither input is modified.
    """
    merged = dict(current)
    for task_id in changed:
        if task_id not in mine:
            continue
        if _last_run_at(current.get(task_id)) > _last_run_at(mine[task_id]):
            continue
        merged[task_id] = mine[task_id]
    return merged


def state_lock_path() -> str:
    return str(STATE_FILE) + ".lock"


def _lock(fh, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError as exc:
            if exc.errno not in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES):
                raise
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def _write_atomically(path, text: str) -> None:
    """A temp file of this writer's own beside `path`, fsynced, then renamed over it."""
    path = str(path)
    directory = os.path.dirname(os.path.abspath(path))
    try:
        mode = os.stat(path).st_mode & 0o777
    except OSError:
        mode = 0o644
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
            fh.flush()
            os.fchmod(fh.fileno(), mode)
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    with contextlib.suppress(OSError):
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def save_state(state: dict, changed=None, lock_timeout=None) -> bool:
    """Write this run's entries into the state file without losing another run's.

    Under an exclusive lock on a sibling lock file, the file is re-read and only the ids in
    `changed` (every id in `state` when not given) are merged in, the newer entry winning.
    Returns False, having logged why, when the lock is not free within the timeout.
    """
    changed = set(state) if changed is None else set(changed)
    timeout = STATE_LOCK_TIMEOUT if lock_timeout is None else lock_timeout
    Path(STATE_DIR).mkdir(parents=True, exist_ok=True)
    lock = state_lock_path()
    with open(lock, "a") as fh:
        if not _lock(fh, timeout):
            ids = ", ".join(sorted(changed)) or "no task"
            message = (f"state not saved: could not get the lock {lock} within {timeout}s; "
                       f"last-run entries for {ids} are not recorded")
            log(RUNNER_LOG, message)
            print(message, file=sys.stderr)
            return False
        merged = merge_state(load_state(), state, changed)
        _write_atomically(STATE_FILE, json.dumps(merged, indent=2, sort_keys=True))
    return True


# ---------------------------------------------------------------- registry


def parse_days(spec: str) -> set[int]:
    """`*` = every day. Otherwise ISO weekdays: 1=Mon .. 7=Sun. Accepts `1-5`, `1,3,5`, `6`."""
    return GD.parse_days(spec)


def clean_cell(cell: str) -> str:
    """A table cell without the emphasis and code ticks the note uses for readability.

    A bare `*` (or `*` in code ticks) is the "every machine" / "every day" value, not emphasis:
    stripping it would leave an empty cell that no machine and no day matches.
    """
    text = re.sub(r"^[`*_]+|[`*_]+$", "", cell)
    if not text and cell.strip("`") == "*":
        return "*"
    return text


def read_registry() -> list[dict]:
    """Parse the markdown table out of the registry note.

    Rows look like:
      | id | machine | time | days | type | command | enabled | notes |
    """
    registry = Path(REGISTRY)
    if not registry.exists():
        return []
    tasks = []
    for line in registry.read_text().splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 7:
            continue
        if cells[0].lower() in ("id", "---") or set(cells[0]) <= {"-", ":"}:
            continue
        cells = [clean_cell(c) for c in cells]
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


_MINE_CACHE: dict = {}                # machine cell -> machine_identity's verdict, once per process


def machine_is_mine(value: str) -> bool:
    """Does a registry `machine` cell name this machine, by machine_identity.machine_is_mine?

    It accepts this machine's key, its uuid, its label and every historical form. The verdict is
    kept per value: on macOS each question would otherwise read the hardware uuid again. A
    failure is "not mine", never a crash of the runner.
    """
    if value not in _MINE_CACHE:
        try:
            import machine_identity

            _MINE_CACHE[value] = bool(machine_identity.machine_is_mine(value))
        except Exception:
            _MINE_CACHE[value] = False
    return _MINE_CACHE[value]


def mine(task: dict) -> bool:
    return GD.machine_matches(task["machine"], host(), machine_is_mine)


def due(task: dict, state: dict) -> tuple[bool, str]:
    """Returns (should_run, reason_if_not). The rule lives in guardian_core.domain.routine_due."""
    return GD.routine_due(task, state.get(task["id"], {}).get("last_run_date"), now(), host(),
                          machine_is_mine)


# ---------------------------------------------------------------- running


def raise_alert(key: str, summary: str, severity: str = "fail") -> None:
    """Record a problem for the guardian to report. Never breaks the runner."""
    try:
        from guardian_core import adapters as GA

        GA.raise_alert(key, summary, severity=severity)
    except Exception as exc:
        try:
            log(RUNNER_LOG, f"could not raise alert {key}: {type(exc).__name__}: {exc}")
        except Exception:
            pass


def clear_alert(key: str) -> None:
    """The problem behind `key` is gone. Never breaks the runner."""
    try:
        from guardian_core import adapters as GA

        GA.clear_alert(key)
    except Exception as exc:
        try:
            log(RUNNER_LOG, f"could not clear alert {key}: {type(exc).__name__}: {exc}")
        except Exception:
            pass


class _RunnerAlerts:
    """routine_auth_core's alert port, through this module's own raise_alert/clear_alert."""

    def raise_alert(self, key, summary, severity="fail"):
        raise_alert(key, summary, severity)

    def clear_alert(self, key):
        clear_alert(key)


def token_source():
    """Where routine tokens are read from: the kdbx, through the vault's kp.py, headless."""
    from routine_auth_core import adapters as RAD

    return RAD.KpTokenSource(os.path.join(str(VAULT), "_bin", "kp.py"))


def cli_health(template: str):
    from routine_auth_core import adapters as RAD

    resolver = CLI_HEALTH_CACHE.get(template)
    if resolver is None:
        resolver = CLI_HEALTH_CACHE[template] = RAD.CliResolver(template, home=str(HOME))
    return resolver


def run_agent(task: dict) -> tuple[int, str, str, str]:
    """Hand a routine file to the configured CLI agent: (rc, stdout, stderr, summary).

    The command template is configuration (90-Meta/agent-command.txt); the credential is
    the token pool (90-Meta/routine-tokens.json); which token, how a failure reads and
    whether to fail over is routine_auth_core. `summary` is the one line the alert carries.
    """
    from guardian_core import adapters as GA
    from routine_auth_core import adapters as RAD
    from routine_auth_core import application as RA
    from routine_auth_core import domain as RD

    path = task["command"]
    if not os.path.isabs(path):
        path = os.path.join(str(VAULT), path)
    if not os.path.isfile(path):
        msg = f"routine file missing: {path}"
        return 2, "", msg, msg
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"routine file unreadable: {path}: {exc}"
        return 2, "", msg, msg
    # Preflight: a repo, program or path this machine lacks refuses the run before any token is
    # read, instead of letting the agent run half-blind and report the gap in its own output.
    import routine_requires as RQ

    gaps = RQ.problems(text, RQ.RealProbe(), str(VAULT), str(HOME))
    if gaps:
        msg = ("this machine lacks what the routine needs: " + "; ".join(gaps)
               + " (check: python3 ~/Brain/_bin/routine_requires.py here --fix)")
        return 2, "", msg, msg
    args, problem = RD.parse_agent_args(text)
    contract, contract_problem = RD.parse_success_contract(text)
    template = GA.load_agent_command(str(VAULT))
    ports = RA.Ports(
        pool=RAD.PoolFile(os.path.join(str(VAULT), "90-Meta", "routine-tokens.json")),
        tokens=token_source(),
        state=RAD.JsonStateStore(str(ROUTINE_AUTH_STATE)),
        clock=RAD.SystemClock(),
        cli=cli_health(template),
        runner=RAD.CliAttempt(template, cwd=str(VAULT), home=str(HOME)),
        raw_log=RAD.RawOutputLog(str(ROUTINE_AUTH_LOG)),
        alerts=_RunnerAlerts(),
        base_env=dict(os.environ),
        scratch=RAD.ScratchDirs(str(ROUTINE_SCRATCH_DIR)),
        run_ids=RAD.RandomRunIds(),
        sends=RAD.MailSentLog(str(MAIL_SENT_LOG)),
        run_env={RD.SEND_LOG_ENV: str(MAIL_SENT_LOG)},
    )
    res = RA.run_routine(ports, RA.Routine(task["id"], path, args, problem, contract, contract_problem, text=text),
                         DEFAULT_TIMEOUT)
    summary = res.summary
    for a in res.attempts:
        log(RUNNER_LOG, f"{task['id']}: token {a.label}: {a.kind}" + (f" (run {a.run_id})" if a.run_id else ""))
        if a.scratch:
            log(RUNNER_LOG, f"{task['id']}: run {a.run_id} failed; its scratch directory is kept for "
                            f"{RD.SCRATCH_KEEP_DAYS} days: {a.scratch}")
    kept = [a.scratch for a in res.attempts if a.scratch]
    if summary and kept:
        summary += f"; scratch directory kept for inspection: {kept[-1]}"
    return res.rc, res.stdout, res.stderr, summary


def run_task(task: dict, state: dict, changed: set | None = None) -> int:
    """Run one task and record it in `state`; its id is added to `changed` for save_state."""
    task_log = Path(LOG_DIR) / f"{task['id']}.log"
    started = now()
    log(task_log, f"START  {task['id']}  (scheduled {task['time']}, host {host()})")
    log(RUNNER_LOG, f"running {task['id']} on {host()}")

    summary = ""
    try:
        if task["type"] == "agent":
            rc, out, err, summary = run_agent(task)
        else:
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

    if summary:
        log(task_log, f"  why| {summary}")
    secs = (now() - started).total_seconds()
    log(task_log, f"END    {task['id']}  exit={rc}  {secs:.1f}s")

    if task["type"] == "agent":
        # A routine nobody watches reports its own failure: silence would be
        # indistinguishable from a broken schedule.
        key = f"routine:{task['id']}"
        if rc == 0:
            clear_alert(key)
        else:
            last = (err or "").strip().splitlines()
            why = summary or (last[-1][:160] if last else "")
            raise_alert(key, f"routine {task['id']} failed: exit={rc}" + (f": {why}" if why else ""))

    entry = state.setdefault(task["id"], {})
    entry["last_run_date"] = started.strftime("%Y-%m-%d")
    entry["last_run_at"] = started.isoformat(timespec="seconds")
    entry["last_exit"] = rc
    entry["host"] = host()
    if changed is not None:
        changed.add(task["id"])
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="run the vault's periodic tasks for this machine")
    ap.add_argument("--list", action="store_true", help="show the registry as this machine sees it")
    ap.add_argument("--dry-run", action="store_true", help="say what would run, run nothing")
    ap.add_argument("--force", metavar="ID", help="run one task now, ignoring schedule and last-run")
    args = ap.parse_args(argv)

    tasks = read_registry()
    state = load_state()
    changed: set = set()  # the ids this run recorded: the only entries its save may touch

    if args.list:
        cmd_list(tasks, state)
        return 0

    if args.force:
        for t in tasks:
            if t["id"] == args.force:
                if t["type"] not in GD.RUNNABLE_TYPES:
                    print(f"{t['id']}: type '{t['type']}' is not run by this runner", file=sys.stderr)
                    return 2
                rc = run_task(t, state, changed)
                save_state(state, changed)
                print(f"{t['id']}: exit={rc}  (log: {Path(LOG_DIR) / (t['id'] + '.log')})")
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
        run_task(t, state, changed)
        ran += 1

    if ran and not args.dry_run:
        save_state(state, changed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
