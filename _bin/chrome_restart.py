#!/usr/bin/env python3
"""Restart this machine's desktop Chrome, and only it (Linux).

The desktop Chrome (the one Claude in Chrome drives, with the user's logged in sessions) runs in the
VNC desktop under ~/.local/bin/chrome-keepalive.sh, which relaunches it 5 s after it exits. Other
tasks start their own Chrome processes at the same time: headless renders of cards and PDFs
(Playwright, /opt/google/chrome/chrome --headless) and Playwright browsers with their own
--user-data-dir. `pkill -x chrome` killed all of them; this kills only the desktop one.

    chrome_restart.py status     the desktop Chrome, the keepalive, the headless ones left alone, the lock
    chrome_restart.py check      exit 0 when a restart is allowed now, 75 when not (says why)
    chrome_restart.py restart [--grace 10] [--timeout 30] [--settle 5]

The desktop Chrome is a `chrome` process with no --headless, no --type= (renderers, GPU and the
other helpers carry one), no Playwright or automation flags, no --user-data-dir other than
~/.config/google-chrome, whose parent is not another Chrome; its parent is normally the keepalive.

A restart is allowed only when it cannot break someone else: the lock group `chrome`, which tasks.py
holds for every routine that drives this Chrome and `browser_lock.py hold` takes for an interactive
session, must be free (taken for the restart itself) or held by the caller (the tasks.py above it
inside a routine, or a hold of the Claude session it runs in). Otherwise it refuses with exit 75 and
names the holder. It also refuses when the keepalive is not running, since nothing would relaunch
Chrome.

`restart` sends SIGTERM, then SIGKILL to what is left after --grace seconds, waits up to --timeout
seconds for the keepalive to start a new desktop Chrome, then --settle seconds for the extension.
Exit 0 restarted (or relaunched by the keepalive), 1 no new Chrome in time, 3 no keepalive or
nothing it may restart, 75 not safe now (lock held by someone else), 2 usage.
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import browser_lock  # noqa: E402  (who holds a lock group, and whether it is the caller)
import task_locks  # noqa: E402

GROUP = browser_lock.CHROME_GROUP
BUSY = 75
NOT_POSSIBLE = 3
KEEPALIVE = "chrome-keepalive.sh"
PROFILE_DIR = os.path.expanduser("~/.config/google-chrome")
# flags that mark a Chrome started by a tool (Playwright, Puppeteer, chromedriver), never the desktop one
AUTOMATION_FLAGS = ("--headless", "--type=", "--remote-debugging-pipe", "--enable-automation",
                    "--test-type", "--remote-debugging-port")


# ---------------------------------------------------------------- the process table (mocked in tests)

def list_procs() -> list:
    """Every process of this user: dicts with pid, ppid, comm and args (a list)."""
    uid = os.getuid()
    out = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        base = f"/proc/{name}"
        try:
            if os.stat(base).st_uid != uid:
                continue
            with open(f"{base}/comm") as fh:
                comm = fh.read().strip()
            with open(f"{base}/cmdline", "rb") as fh:
                args = [a.decode("utf-8", "replace") for a in fh.read().split(b"\0") if a]
            with open(f"{base}/stat") as fh:
                ppid = int(fh.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        out.append({"pid": int(name), "ppid": ppid, "comm": comm, "args": args})
    return out


def send(pid: int, sig: int) -> None:
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass


# ---------------------------------------------------------------- telling the processes apart

def tokens(p: dict) -> list:
    """The command line as words. Chrome rewrites the command line of its helper processes into one
    space joined string, so the NUL separated args alone do not show their flags."""
    return " ".join(p["args"]).split()


def is_chrome(p: dict) -> bool:
    t = tokens(p)
    exe = os.path.basename(t[0]) if t else ""
    return p["comm"] == "chrome" or exe == "chrome"


def user_data_dir(p: dict) -> str:
    for a in tokens(p):
        if a.startswith("--user-data-dir="):
            return os.path.realpath(os.path.expanduser(a.split("=", 1)[1]))
    return ""


def is_keepalive(p: dict) -> bool:
    return any(os.path.basename(a) == KEEPALIVE for a in p["args"][:3])


def is_desktop(p: dict, by_pid: dict) -> bool:
    """The desktop Chrome browser process: see the module docstring."""
    if not is_chrome(p):
        return False
    if any(a.startswith(f) for a in tokens(p)[1:] for f in AUTOMATION_FLAGS):
        return False
    udd = user_data_dir(p)
    if udd and udd != os.path.realpath(PROFILE_DIR):
        return False
    parent = by_pid.get(p["ppid"])
    if parent and is_chrome(parent):
        return False
    return True


def survey(procs: list) -> dict:
    """{desktop: [...], keepalive: [...], others: [...]} where others are the Chrome processes left alone."""
    by_pid = {p["pid"]: p for p in procs}
    desktop = [p for p in procs if is_desktop(p, by_pid)]
    # with a keepalive running, its own child is the desktop Chrome; prefer it when several qualify
    keep = [p for p in procs if is_keepalive(p)]
    keep_pids = {k["pid"] for k in keep}
    if len(desktop) > 1 and any(p["ppid"] in keep_pids for p in desktop):
        desktop = [p for p in desktop if p["ppid"] in keep_pids]
    ids = {p["pid"] for p in desktop}
    others = [p for p in procs if is_chrome(p) and p["pid"] not in ids
              and not any(a.startswith("--type=") for a in tokens(p))]
    return {"desktop": desktop, "keepalive": keep, "others": others}


def short(p: dict) -> str:
    return f"pid {p['pid']}: {' '.join(p['args'])[:140]}"


# ---------------------------------------------------------------- safety

def safety():
    """(state, holder) of the chrome lock for the caller: free, mine or other (browser_lock.group_state)."""
    return browser_lock.group_state(GROUP)


def refusal(holder: str) -> str:
    who = holder or "holder unknown"
    if browser_lock.inside_routine():
        return (f"not safe: lock group {GROUP} is held by another run ({who}), not by this routine. "
                f"Add mcp__claude-in-chrome to its allowedTools or drop `chrome_lock: false`, so tasks.py "
                f"holds it for this routine; do not restart.")
    return (f"not safe: lock group {GROUP} is held by someone else ({who}). A routine or another session "
            f"is using Chrome. Take it first with `python3 ~/Brain/_bin/browser_lock.py hold` (waits for "
            f"them), then restart; or ask the user.")


# ---------------------------------------------------------------- commands

def cmd_status(a, procs=None) -> int:
    s = survey(procs if procs is not None else list_procs())
    if s["desktop"]:
        for p in s["desktop"]:
            parent = "keepalive" if p["ppid"] in {k["pid"] for k in s["keepalive"]} else f"parent {p['ppid']}"
            print(f"desktop Chrome: {short(p)} ({parent})")
    else:
        print("desktop Chrome: not running")
    print(f"keepalive: {'running (pid ' + ', '.join(str(k['pid']) for k in s['keepalive']) + ')' if s['keepalive'] else 'NOT running'}")
    print(f"other Chrome processes left alone: {len(s['others'])}")
    for p in s["others"][:10]:
        print(f"  {short(p)}")
    state, holder = safety()
    print(f"lock group {GROUP}: {state}" + (f" ({holder})" if holder else ""))
    return 0 if s["desktop"] else 1


def cmd_check(a, procs=None) -> int:
    state, holder = safety()
    if state == "other":
        print(refusal(holder))
        return BUSY
    s = survey(procs if procs is not None else list_procs())
    if not s["keepalive"]:
        print(f"not possible: {KEEPALIVE} is not running, nothing would relaunch Chrome. Ask the user.")
        return NOT_POSSIBLE
    print(f"ok: a restart is allowed now (lock group {GROUP} {state})")
    return 0


def restart(a, procs_fn=list_procs, kill=send, sleep=time.sleep, clock=time.monotonic) -> int:
    """The restart itself, with the process table, signals and time injected for the tests."""
    s = survey(procs_fn())
    if not s["keepalive"]:
        print(f"not possible: {KEEPALIVE} is not running, nothing would relaunch Chrome. Ask the user.")
        return NOT_POSSIBLE
    old = {p["pid"] for p in s["desktop"]}
    for p in s["desktop"]:
        print(f"stopping desktop Chrome {short(p)}", flush=True)
        kill(p["pid"], signal.SIGTERM)
    if s["others"]:
        print(f"leaving alone {len(s['others'])} other Chrome process(es) (headless renders, Playwright)")
    end = clock() + a.grace
    alive = set(old)
    while alive and clock() < end:
        sleep(0.5)
        alive = {p["pid"] for p in procs_fn() if p["pid"] in old}
    for pid in alive:
        print(f"pid {pid} still up after {a.grace:g} s: SIGKILL", flush=True)
        kill(pid, signal.SIGKILL)
    if not old:
        print("no desktop Chrome was running: waiting for the keepalive to start one")
    end = clock() + a.timeout
    while clock() < end:
        new = [p for p in survey(procs_fn())["desktop"] if p["pid"] not in old]
        if new:
            sleep(a.settle)
            print(f"restarted: desktop Chrome is pid {new[0]['pid']}"
                  + (f" (was {', '.join(str(x) for x in sorted(old))})" if old else "")
                  + ". Probe the browser again.")
            return 0
        sleep(1)
    print(f"failed: no new desktop Chrome {a.timeout:g} s after the restart; check `chrome_restart.py status` "
          f"and the keepalive log ~/.cache/chrome-keepalive.log")
    return 1


def cmd_restart(a) -> int:
    state, holder = safety()
    if state == "other":
        print(refusal(holder))
        return BUSY
    if state == "mine":
        return restart(a)
    # free: hold it for the restart, so no routine or session starts on a Chrome that is going away
    with task_locks.open_lock(f"group-{GROUP}") as fh:
        if not task_locks.try_lock(fh):
            print(refusal(browser_lock.holder_text(GROUP)))
            return BUSY
        task_locks.mark(fh, "chrome_restart.py restart")
        return restart(a)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("check")
    r = sub.add_parser("restart")
    r.add_argument("--grace", type=float, default=10, help="seconds between SIGTERM and SIGKILL")
    r.add_argument("--timeout", type=float, default=30, help="seconds to wait for the new Chrome")
    r.add_argument("--settle", type=float, default=5, help="seconds after it appears, for the extension")
    a = ap.parse_args(argv)
    return {"status": cmd_status, "check": cmd_check, "restart": cmd_restart}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
