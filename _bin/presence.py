#!/usr/bin/env python3
"""Presence heartbeat on this machine: who is working, on what, and since when.

There is also a git-based presence — one `.md` per session in `90-Meta/presence/` — and it
stays, because it is what reaches other machines. It travels in a commit, so another machine
finds out **up to 600 s later**. This one answers the same question for the sessions on THIS
machine, straight away, with nothing to authenticate to and no network.

Two decisions keep it cheap:

1. **Everything lives in the file NAME, not in the body.**
   `<state>/presence/<project>/<machine>__<sid>`, empty. One walk of that directory returns
   who is there, and each file's mtime IS the heartbeat. Zero file bodies read.
2. **One clock.** Every session here reads the same clock, so an age is just now - mtime.

And the rule that governs the rest: **nothing slow on a hook's path.** This is always invoked
detached (`Popen(start_new_session=True)`), leaves the result in a local cache, and the hooks
read that cache, which is an `open()`. The naming and age rules live in presence_core.py,
which touches no disk; this file only does the IO, each session's file guarded by B.flock.
"""
import os, sys, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B
import brain_paths
import presence_core as C

DIR = os.path.join(brain_paths.effective_state_dir(), "presence")
CACHE = os.path.join(B.STATE, "presence-cache.json")
TTL = 900.0            # no heartbeat in 15 min and the session counts as gone
EVERY = 120.0          # never beat more than once every two minutes


# One derivation, in brainlib. Three copies of the same body is how `skills_index.py`
# came to carry a comment asserting "the machine name comes from brainlib … so the two
# places cannot disagree" while three other copies quietly existed.
_machine = B._machine


def _path(key):
    return os.path.join(DIR, *key.split("/"))


def announce(sid, project):
    """Record that this session is alive and which project it is on.

    Empty file on purpose: what gets consulted is the name and its mtime. One file per
    session, same as in git, so a beat competes with nobody; the lock only keeps a purge
    from removing the file between its check and our touch.
    """
    path = _path(C.key(project, _machine(), sid))
    try:
        with B.flock(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a"):
                pass
            os.utime(path, None)
        return True, ""
    except OSError as e:
        return False, repr(e)


def withdraw(sid, project):
    path = _path(C.key(project, _machine(), sid))
    try:
        with B.flock(path):
            os.remove(path)
    except FileNotFoundError:
        pass                        # already gone is what withdrawing asks for
    except OSError:
        return False
    return True


def _entries():
    """(key, mtime) for every session file. A missing directory is nobody, not an error."""
    out = []
    try:
        projects = list(os.scandir(DIR))
    except FileNotFoundError:
        return out
    for project in projects:
        if not project.is_dir(follow_symlinks=False):
            continue
        try:
            files = list(os.scandir(project.path))
        except OSError:
            continue
        for f in files:
            try:
                if f.is_file(follow_symlinks=False):
                    out.append((project.name + "/" + f.name, f.stat(follow_symlinks=False).st_mtime))
            except OSError:
                continue            # withdrawn while we were looking
    return out


def read(own_sid=None):
    """Who is alive on this machine. One walk of the presence directory, no file bodies."""
    try:
        entries = _entries()
    except OSError as e:
        return None, repr(e)        # None = "unknown", different from "nobody there"
    return C.rows(entries, time.time(), TTL, own_sid), ""


def purge(expired_ones):
    """Withdraw heartbeats of sessions that are gone. No separate reaper: it happens in
    passing, when someone comes through here, and only for the long-expired ones. The age
    is checked again under the lock, so a session that beat meanwhile keeps its file."""
    n = 0
    for key in C.purgeable(expired_ones, TTL):
        path = _path(key)
        try:
            with B.flock(path) as lk:
                if not lk.held:
                    continue
                age = time.time() - os.path.getmtime(path)
                if C.purgeable([{"key": key, "age": age}], TTL):
                    os.remove(path)
                    n += 1
        except OSError:
            continue
    return n


def cache_read():
    """What the hooks consult: an open(), nothing else. Never raises."""
    try:
        with open(CACHE) as fh:
            return C.cache_view(json.load(fh), time.time(), TTL)
    except Exception:
        return {}


def cache_write(d):
    try:
        os.makedirs(B.STATE, exist_ok=True)
        B.atomic_write(CACHE, json.dumps(d, ensure_ascii=False))
    except Exception as e:
        B.log_error("presence.cache_write", e)


STAMP = os.path.join(B.STATE, "presence.attempt")


def should_beat():
    """True at most once every EVERY seconds. Stamps the ATTEMPT, not the result.

    It used to read the mtime of the cache, which is written only at the END of the happy
    path. So on any failure the throttle never advanced and EVERY prompt forked a detached
    interpreter that did nothing but log and exit. Anchoring on the attempt makes the
    throttle hold whether the beat works or not.
    """
    try:
        last = os.path.getmtime(STAMP)
    except OSError:
        last = None
    if not C.beat_due(last, time.time(), EVERY):
        return False
    try:
        os.makedirs(B.STATE, exist_ok=True)
        open(STAMP, "w").close()
    except OSError:
        pass
    return True


def main():
    import argparse
    p = argparse.ArgumentParser(prog="presence")
    p.add_argument("action", choices=["beat", "withdraw", "view"])
    p.add_argument("--sid", default="")
    p.add_argument("--project", default="-")
    a = p.parse_args()

    t0 = time.time()
    if a.action == "withdraw":
        ok = withdraw(a.sid, a.project)
        B.log("presence", "withdraw", sid=a.sid, ok=ok, ms="%.0f" % ((time.time()-t0)*1000))
        return 0

    if a.action == "beat" and a.sid:
        ok, err = announce(a.sid, a.project)
        if not ok:
            B.log("presence", "beat-fails", err=err[:150])

    status, err = read(a.sid)
    if status is None:
        B.log("presence", "read-fails", err=err[:150])
        return 1
    status["machine"] = _machine()
    cache_write(status)
    if status["expired"]:
        purge(status["expired"])
    B.log("presence", a.action, alive_ones=len(status["alive"]),
          ms="%.0f" % ((time.time() - t0) * 1000))
    if a.action == "view":
        print(json.dumps(status, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
