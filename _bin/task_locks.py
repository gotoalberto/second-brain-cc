#!/usr/bin/env python3
"""The run locks of scheduled tasks, shared by tasks.py and browser_lock.py.

One place for where the locks live and how they are taken, so the runner and an interactive
session holding a lock group (browser_lock.py) can never disagree about it. Locks are flock on
<state>/task-locks/<name>.lock: they die with the process that holds them, so a killed holder
never leaves a stale lock. The file only carries a line saying who holds it.

  path(name, state_dir) the lock file of a task id or of `group-<group>`
  try_lock(fh, timeout) take it within `timeout` seconds (0: one try); True when held
  holder(name)          the line the holder wrote, "" when none
  mark(fh, text)        write that line
  wait_groups(groups, label, log)   context manager: every group lock, in sorted order, waiting
                        as long as it takes for each (a task may wait hours for another one that
                        drives the same account; the wait never counts against its timeout)
"""
from __future__ import annotations

import contextlib
import datetime as dt
import errno
import fcntl
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_paths  # noqa: E402

STATE_DIR = str(brain_paths.effective_state_dir())


def path(name: str, state_dir=None) -> str:
    return os.path.join(str(state_dir or STATE_DIR), "task-locks", f"{name}.lock")


def try_lock(fh, timeout: float = 0) -> bool:
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


def holder(name: str, state_dir=None) -> str:
    try:
        with open(path(name, state_dir)) as fh:
            return fh.read().strip()
    except OSError:
        return ""


def mark(fh, text: str) -> None:
    fh.seek(0)
    fh.truncate()
    fh.write(f"{text} pid {os.getpid()} since {dt.datetime.now().isoformat(timespec='seconds')}\n")
    fh.flush()


def open_lock(name: str, state_dir=None):
    p = path(name, state_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return open(p, "a+")


@contextlib.contextmanager
def wait_groups(groups, label: str, log=lambda message: None, state_dir=None):
    """Hold every group lock for the block, in sorted order, waiting with no time limit."""
    with contextlib.ExitStack() as stack:
        for g in sorted(set(groups)):
            fh = stack.enter_context(open_lock(f"group-{g}", state_dir))
            if not try_lock(fh):
                log(f"waiting {label}: lock group {g} busy ({holder(f'group-{g}', state_dir) or 'holder unknown'})")
                t0 = time.monotonic()
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                log(f"lock group {g} free for {label} after {time.monotonic() - t0:.0f}s")
            mark(fh, label)
        yield
