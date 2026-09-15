#!/usr/bin/env python3
"""Advisory write lease on a note, for the sessions on this machine.

**What it actually solves.** Two sessions on the same project don't collide over code:
they collide over the project NOTE, because both append to its end and git cannot merge
two appends on the same line. Presence already warns about that (see presence.py), but a
warning only helps if someone reads it. This one **acts**: if another session holds the
note, `vw.py append` redirects itself to a new linked note.

**What it is NOT.** It is not mutual exclusion over the file. Obsidian desktop, Obsidian
mobile, a mobile git client and a hand-typed `git commit` never consult it, so the lease is
*advisory* by construction: it decides **where** the harness writes, never **whether** it
may write. And it only sees sessions on this machine. Across machines the safety net is
git, which on two edits to the same note gives a loud, aborted conflict rather than a
silent merge.

**The primitive.** One small JSON record per note under `<state>/locks/`, read and written
only while holding B.flock on that file. On one machine the lock serialises every acquirer,
so a transition is "lock, read, decide, write": there is nothing to compare-and-swap. The
decision itself (take, renew, steal, foreign) is lease_core.decide. Releasing removes the
record, and that is safe for the same reason: it happens under the lock, and only after
reading ourselves as the holder inside it.

**The invariant the whole thing hangs on**, worth reading twice:

    Nobody declares themselves holder without having written the record under the lock.
    B.flock fails open on a timeout, so when the lock was not held the answer is 'unknown'
    and nothing is written: an unlocked write is how two sessions would both hold it.
"""
import os, sys, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B
import brain_paths
import lease_core as C

LOCKS = os.path.join(brain_paths.effective_state_dir(), "locks")
CACHE = os.path.join(B.STATE, "leases.json")

TTL = 1200.0        # without renewal, the lease expires after 20 min
GUARD = 120.0       # the holder stops believing it holds at TTL-120...
CUSHION = 60.0      # ...and the thief waits until TTL+60. 180 s of margin.
LEASED_FOLDERS = ("10-Projects", "70-Entities")

slug = C.slug


def _path(rel):
    return os.path.join(LOCKS, C.filename(rel))


def _me():
    return B._machine()


def _load(path):
    """The record in a lease file, None when absent or unreadable as a record."""
    try:
        with open(path, encoding="utf-8") as fh:
            return C.parse(fh.read())
    except (FileNotFoundError, UnicodeDecodeError):
        return None


def holder(rel):
    """Who holds the note's lease, read without the lock: records are replaced atomically,
    so a reader sees the old record or the new one, never half of either."""
    try:
        return C.owner(_load(_path(rel)))
    except OSError:
        return "?"


def acquire(rel, sid):
    """Try to become the holder. Returns 'mine' | 'foreign' | 'unknown'."""
    path = _path(rel)
    try:
        with B.flock(path) as lk:
            if not lk.held:
                B.log("lease", "lock-busy", note=rel)
                return "unknown"
            rec = _load(path)
            decision = C.decide(rec, _me(), sid, time.time(), TTL, CUSHION)
            if decision != "foreign":
                B.atomic_write(path, C.dumps(C.record(_me(), sid, time.time())))
            if decision == "steal":
                B.log("lease", "stolen", note=rel, a=C.owner(rec),
                      age="%.0f" % (time.time() - rec["at"]))
            return C.outcome(decision)
    except OSError as e:
        B.log("lease", "acquire-fails", note=rel, err=repr(e)[:200])
        return "unknown"


def release_lease(rel, sid):
    """Remove the record, only if this session holds it. See the module docstring."""
    path = _path(rel)
    try:
        with B.flock(path) as lk:
            if not lk.held or not C.may_release(_load(path), _me(), sid):
                return False                   # not ours, or no lock: leave it alone
            os.remove(path)
            return True
    except OSError:
        return False


# ------------------------------------------------------------------- local cache
def cache_read():
    """What vw.py consults: an open(), no lock, no exceptions."""
    try:
        with open(CACHE) as fh:
            return json.load(fh)
    except Exception:
        return {}


def _row(d, rel, sid=""):
    """This session's row, falling back to the shared pre-sid one."""
    return C.select_row(d, rel, sid)


def local_state(rel, sid=""):
    """'mine' | 'foreign' | '' — from the cache row this session's last acquire left.

    The row is per SESSION, not just per note. Sharing one row per note meant a SECOND
    session, told "foreign" because the sid differs, wrote that verdict over the row the
    true holder was reading — and `vw.py` then redirected the holder's own appends to a
    side note.

    `valid_until` is only written after our own acquire succeeded. That is why a laptop
    waking after two hours with the lid shut self-demotes for free, without detecting the
    suspend: local arithmetic already says it expired. Intervals use time.time() and NOT
    time.monotonic(), which on this interpreter does not advance while the machine sleeps —
    and that is exactly the time that has to be counted.
    """
    return C.row_state(_row(cache_read(), rel, sid), time.time(), TTL)


def local_owner(rel, sid=""):
    return _row(cache_read(), rel, sid).get("owner") or "?"


def _store(rel, state, owner="", sid=""):
    d = cache_read()
    d[C.row_key(rel, sid)] = C.row(state, owner, rel, sid, time.time(), TTL, GUARD)
    try:
        os.makedirs(B.STATE, exist_ok=True)
        B.atomic_write(CACHE, json.dumps(d, ensure_ascii=False))
    except Exception as e:
        B.log_error("lease._store", e)


# ------------------------------------------------------------------- execution
def main():
    import argparse
    p = argparse.ArgumentParser(prog="lease")
    p.add_argument("action", choices=["acquire", "release", "status"])
    p.add_argument("note", nargs="?", default="")
    p.add_argument("--sid", default="")
    a = p.parse_args()

    if a.action == "status":
        print(json.dumps(cache_read(), ensure_ascii=False, indent=1))
        return 0
    if not a.note or not a.sid:
        return 2

    t0 = time.time()
    if a.action == "release":
        ok = release_lease(a.note, a.sid)
        _store(a.note, "", "", a.sid)
        B.log("lease", "release_lease", note=a.note, ok=ok,
              ms="%.0f" % ((time.time() - t0) * 1000))
        return 0

    r = acquire(a.note, a.sid)
    if r != "unknown":
        owner = "%s/%s" % (_me(), a.sid[:8]) if r == "mine" else holder(a.note)
        _store(a.note, r, owner, a.sid)
    B.log("lease", "acquire", note=a.note, r=r, ms="%.0f" % ((time.time() - t0) * 1000))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
