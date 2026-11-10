#!/usr/bin/env python3
"""Hold a scheduled-task lock group from an interactive session.

Routines that drive the same account in this machine's Chrome share a lock group (tasks.py,
`lock_group:` in their front matter): one waits for the other. A Claude session that does the
same work by hand must take the same lock, or it switches accounts under a running routine.
This takes it the same way tasks.py does (flock on <state>/task-locks/group-<name>.lock), so
routines wait for the session and the session waits for routines.

    browser_lock.py hold [--group chrome] [--label TEXT] [--wait-minutes 9 | --forever]
                         [--max-hours 3] [--idle-minutes N]
    browser_lock.py release [--group chrome] [--force]
    browser_lock.py status [--group chrome]

Every command also covers the group `chrome`, the lock tasks.py gives every routine that drives
this machine's Chrome: a session holding the browser blocks those routines and any Chrome restart
by someone else (chrome_restart.py), and may restart Chrome itself. The groups are taken in sorted
order, like tasks.py, so a session and a routine never deadlock.

`hold` waits up to --wait-minutes (a Bash tool call lasts at most 10), then leaves a small
detached process holding the lock and returns. That process lets go on `release`, when the
Claude session that took it ends, after --max-hours, or after --idle-minutes with no command,
whichever comes first, so a session that forgets to release never blocks the routines for long.
--forever waits with no limit: run it with run_in_background, so a session that has to wait never
gives up (a foreground Bash call dies after 10 minutes). Inside a routine `hold` takes nothing,
since tasks.py already holds the routine's groups, unless --in-routine: a routine with
`chrome_lock: false` that uses this machine's Chrome for one short step only takes them for that
step and lets go with `release`. `release` lets go only of the caller's own hold: a hold taken by
another session is refused with exit 75 unless --force. Exit 0 held, 75 still busy (the holder is
printed: tell the user, or retry), 2 usage.
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import task_locks  # noqa: E402  (the same lock files and rules tasks.py uses)

BUSY = 75


def lock_path(group: str) -> str:
    return task_locks.path(f"group-{group}")


def pid_path(group: str) -> str:
    return os.path.join(os.path.dirname(lock_path(group)), f"session-{group}.pid")


def holder_text(group: str) -> str:
    return task_locks.holder(f"group-{group}")


CHROME_GROUP = "chrome"   # the group tasks.py adds to every routine that drives this machine's Chrome
# Groups for a resource that is not a Chrome user (a device driven over its own API): taken alone,
# without `chrome`. None ship by default; add yours here.
STANDALONE = set()
IDLE_DEFAULT = {}   # per group, minutes with no command before a session's hold lets go


def groups_for(group: str) -> list:
    """The groups a command covers: the one named plus `chrome` (except for a STANDALONE group), in
    the order they are taken."""
    return [group] if group in STANDALONE else sorted({group, CHROME_GROUP})


def touch(group: str) -> None:
    """Mark the session's hold of `group` as used now (the idle clock of --idle-minutes)."""
    try:
        os.utime(pid_path(group))
    except OSError:
        pass


def inside_routine() -> bool:
    """True inside a routine run: tasks.py sets BRAIN_ROUTINE_SCRATCH and holds its lock groups."""
    return bool(os.environ.get("BRAIN_ROUTINE_SCRATCH"))


def parent_pid(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return int(fh.read().rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return 0


def ancestors(pid: int = 0) -> list:
    """The pids above `pid` (default: this process), nearest first."""
    out, pid = [], parent_pid(pid or os.getpid())
    while pid > 1 and len(out) < 64:
        out.append(pid)
        pid = parent_pid(pid)
    return out


def _is_claude(pid: int) -> bool:
    """A Claude Code process: `claude`, or the versioned binary remote-control starts sessions with
    (~/.local/share/claude/versions/<n>, whose comm is the version number)."""
    try:
        with open(f"/proc/{pid}/comm") as fh:
            if fh.read().strip() == "claude":
                return True
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            first = fh.read().split(b"\0", 1)[0].decode("utf-8", "replace")
    except OSError:
        return False
    return "/claude/versions/" in first


def claude_ancestor() -> int:
    """Pid of the nearest Claude Code process above us: the session that asked for the lock.
    The versioned binary counts too: under remote-control the nearest `claude` is the shared
    remote-control process, which never ends and is the same for every session."""
    for pid in ancestors():
        if _is_claude(pid):
            return pid
    return 0


def holder_pid(group: str) -> int:
    """The pid the holder wrote in the lock file (task_locks.mark), 0 when none."""
    words = holder_text(group).split()
    for i, w in enumerate(words[:-1]):
        if w == "pid" and words[i + 1].isdigit():
            return int(words[i + 1])
    return 0


def session_owner(group: str) -> tuple:
    """(holder process pid, owning Claude session pid) of a `hold` on this group, (0, 0) when none."""
    try:
        with open(pid_path(group)) as p:
            parts = p.read().split()
        return int(parts[0]), (int(parts[1]) if len(parts) > 1 else 0)
    except (OSError, ValueError, IndexError):
        return 0, 0


def group_state(group: str) -> tuple:
    """("free" | "mine" | "other", holder text) for the caller.

    "mine" is a group held by the caller's own run: the tasks.py above it (inside a routine), or a
    `hold` taken by the Claude session the caller runs in. Anything else holding it is "other"."""
    with task_locks.open_lock(f"group-{group}") as fh:
        if task_locks.try_lock(fh):
            return "free", ""
    text = holder_text(group)
    pid = holder_pid(group)
    if pid and pid in ancestors():
        return "mine", text
    daemon, owner = session_owner(group)
    if pid and daemon == pid and owner and owner == claude_ancestor():
        return "mine", text
    return "other", text


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def cmd_hold(a) -> int:
    groups = groups_for(a.group)
    if inside_routine() and not a.in_routine and not (a.group in STANDALONE and group_state(a.group)[0] != "mine"):
        # tasks.py took the routine's lock groups before starting it: taking one again here
        # would wait for ourselves forever
        print(f"inside a routine: tasks.py already holds its lock groups, nothing to take")
        return 0
    idle = a.idle_minutes if a.idle_minutes is not None else IDLE_DEFAULT.get(a.group, 0)
    owner = claude_ancestor()
    held = []
    for g in groups:
        if group_state(g)[0] == "mine":
            touch(g)
            continue   # this session already holds it (an earlier `hold`): nothing more to take
        fh = task_locks.open_lock(f"group-{g}")
        deadline = time.monotonic() + a.wait_minutes * 60
        said = False
        while not task_locks.try_lock(fh):
            if not said:
                print(f"waiting: lock group {g} busy ({holder_text(g) or 'holder unknown'})", flush=True)
                said = True
            if not a.forever and time.monotonic() >= deadline:
                print(f"still busy after {a.wait_minutes} min: {holder_text(g) or 'holder unknown'}")
                for _, h in held:
                    h.close()
                fh.close()
                return BUSY
            time.sleep(5)
        held.append((g, fh))
    names = ", ".join(groups)
    if not held:
        print(f"held: lock group {names} already held by this session")
        return 0
    if os.fork():
        for _, fh in held:
            fh.close()  # the child keeps the open files, so the locks stay held
        time.sleep(0.3)
        print(f"held: lock group {names} for '{a.label}' (released by `browser_lock.py release`, "
              f"when the session ends, after {a.max_hours} h"
              + (f" or after {idle:g} min with no command)" if idle else ")"))
        return 0
    os.setsid()
    if os.fork():
        os._exit(0)
    for fd in (0, 1, 2):
        try:
            os.close(fd)
        except OSError:
            pass
    for g, fh in held:
        task_locks.mark(fh, f"session {a.label}")
        with open(pid_path(g), "w") as p:
            p.write(f"{os.getpid()} {owner}\n")
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    end = time.monotonic() + a.max_hours * 3600
    while time.monotonic() < end and (not owner or alive(owner)):
        if idle and _idle_for(held[0][0]) > idle * 60:
            break
        time.sleep(min(10, idle * 60 / 4) if idle else 10)
    for g, _ in held:
        _remove(pid_path(g))
    os._exit(0)


def _idle_for(group: str) -> float:
    """Seconds since the session last used its hold of `group` (touch), 0 when unknown."""
    try:
        return time.time() - os.path.getmtime(pid_path(group))
    except OSError:
        return 0


def cmd_release(a) -> int:
    """Let go of the groups this session holds, and only those.

    A `hold` belongs to the Claude session that took it (the owner written next to the holder pid).
    Releasing another session's hold leaves it working in the Chrome with no lock, so a routine can
    walk in under it: a session whose own `hold` had timed out once ran `release` and freed the
    hold of another session that was using the browser. So a hold owned by someone else is
    refused (exit 75, the holder printed) unless --force, which is only for the user's explicit
    word or a holder known to be stuck."""
    groups = groups_for(a.group)
    me = claude_ancestor()
    pids = {}
    for g in groups:
        pid, owner = session_owner(g)
        if pid:
            pids.setdefault((pid, owner), []).append(g)
    released, refused = [], []
    for (pid, owner), gs in pids.items():
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                is_hold = b"browser_lock.py" in fh.read()
        except OSError:
            is_hold = False
        if not is_hold:
            # the holder is gone (or the pid was reused): the pid file is stale, clear it
            for g in gs:
                _remove(pid_path(g))
            continue
        if owner != me and not a.force:
            refused += gs
            who = "another Claude session" if owner else "a hold taken outside any Claude session"
            print(f"not yours: lock group {', '.join(gs)} is held by {who} "
                  f"(owner pid {owner or 'none'}, holder pid {pid}; {holder_text(gs[0]) or 'holder unknown'}). "
                  f"Left in place. Only the session that took it releases it, or --force on the user's word.")
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        for g in gs:
            _remove(pid_path(g))
        print(f"released lock group {', '.join(gs)} (pid {pid}{', forced' if owner != me else ''})")
        released += gs
    if refused:
        return BUSY
    if not released:
        print(f"no hold of this session on lock group {', '.join(groups)}")
    return 0


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def cmd_status(a) -> int:
    rc = 0
    for g in groups_for(a.group):
        with task_locks.open_lock(f"group-{g}") as fh:
            if task_locks.try_lock(fh):
                print(f"free: lock group {g}")
                continue
        print(f"busy: lock group {g} ({holder_text(g) or 'holder unknown'})")
        rc = BUSY
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("hold", "release", "status"):
        sp = sub.add_parser(name)
        sp.add_argument("--group", default=CHROME_GROUP)
        if name == "hold":
            sp.add_argument("--label", default="interactive session")
            sp.add_argument("--wait-minutes", type=float, default=9)
            sp.add_argument("--forever", action="store_true",
                            help="wait with no time limit (run it with run_in_background)")
            sp.add_argument("--max-hours", type=float, default=3)
            sp.add_argument("--in-routine", action="store_true",
                            help="inside a routine with `chrome_lock: false`, take the groups for one step")
            sp.add_argument("--idle-minutes", type=float, default=None,
                            help="let go after this long with no command (default: IDLE_DEFAULT, off when unset)")
        if name == "release":
            sp.add_argument("--force", action="store_true",
                            help="release a hold taken by another session (only on the user's word)")
    a = ap.parse_args(argv)
    return {"hold": cmd_hold, "release": cmd_release, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
