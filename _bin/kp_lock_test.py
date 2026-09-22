#!/usr/bin/env python3
"""Tests for kp.py's reading of the database lock across machines.

Two machines can report the same hostname, and a kdbx in a synced folder is seen by all of
them, so a lock is judged by the machine key kp.py writes into it, never by the hostname
alone. Never touches a real database: BRAIN_KP_DB points at a temporary file and only the
lock beside it is written; the machine key is forced with BRAIN_MACHINE_KEY and the network
probe is replaced. Run standalone:

    python3 _bin/kp_lock_test.py
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail and not cond else ""))


def main():
    tmp = tempfile.mkdtemp(prefix="kp-lock-test-")
    for k in [k for k in os.environ if k.startswith("BRAIN_")]:
        os.environ.pop(k)
    os.environ.update(BRAIN_KP_DB=os.path.join(tmp, "store.kdbx"),
                      BRAIN_KP_STATE=os.path.join(tmp, "state"),
                      BRAIN_STATE=os.path.join(tmp, "state"),
                      BRAIN_KP_CACHE_BACKEND="none", BRAIN_KP_NOPROMPT="1",
                      BRAIN_MACHINE_KEY="workstation-0f0f0f0f")
    import kp as K

    dead_pid = "999999"
    me = K._machine_key()
    twin = K._host() + "-deadbeef"                  # same hostname, another machine
    this_uuid = "0f0f0f0f-0000-4000-8000-000000000001"
    K._machine_uuid = lambda: this_uuid
    K.host_reach = lambda host: "answers"           # no network in a test

    def lock(lines, age=0):
        path = K.lock_path()
        with open(path, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        t = time.time() - age
        os.utime(path, (t, t))

    print("== a lock kp.py wrote ==")
    check("the machine key comes from machine_identity", me == "workstation-0f0f0f0f", me)
    lock([dead_pid, "u", K._host(), K.BRAIN_LOCK_TAG + me])
    lk = K.lock_state()
    check("our machine key and a dead pid is our own dead lock", lk["status"] == "own-dead", lk)
    check("which is cleared", K.lock_stale(lk) is not None)

    lock([dead_pid, "u", K._host(), K.BRAIN_LOCK_TAG + twin])
    lk = K.lock_state()
    check("same hostname but another machine key is foreign, never judged by our pids",
          lk["status"] == "foreign-alive", lk)
    check("and a fresh one is not cleared, even though its pid is dead here", K.lock_stale(lk) is None)

    lock([dead_pid, "u", K._host(), K.BRAIN_LOCK_TAG + twin], age=K.BRAIN_LOCK_STALE_S + 60)
    lk = K.lock_state()
    reason = K.lock_stale(lk)
    check("a kp.py lock from another machine older than 30 min is stale, even if that machine answers",
          reason is not None and "never lasts" in reason, reason)
    check("who holds it names the machine key", twin in K.lock_who(lk), K.lock_who(lk))
    check("the threshold is 30 minutes", K.BRAIN_LOCK_STALE_S == 1800, K.BRAIN_LOCK_STALE_S)

    lock([dead_pid, "u", K._host(), K.BRAIN_LOCK_TAG + K._host()])
    lk = K.lock_state()
    check("a key that is only our bare hostname is not ours while our own key carries an id",
          lk["status"].startswith("foreign"), lk)

    print("== KeePassXC's own lock ==")
    lock([dead_pid, "u", K._host()])
    lk = K.lock_state()
    check("our hostname and a dead pid, with no machine id, is never assumed ours",
          lk["status"] == "foreign-alive" and K.lock_stale(lk) is None, lk)

    lock([dead_pid, "KeePassXC", K._host(), this_uuid.replace("-", "")])
    lk = K.lock_state()
    check("a KeePassXC lock carrying this machine's id and a dead pid is our own dead lock",
          lk["status"] == "own-dead" and K.lock_stale(lk) is not None, lk)

    lock([dead_pid, "KeePassXC", K._host(), "11111111-2222-3333-4444-555555555555"])
    lk = K.lock_state()
    check("a KeePassXC lock with another machine's id and our hostname is foreign",
          lk["status"] == "foreign-alive" and K.lock_stale(lk) is None, lk)

    lock([str(os.getpid()), "u", K._host()])
    check("a live local pid is still our own live lock", K.lock_state()["status"] == "own-alive")

    lock(["123", "u", "some-other-box"], age=K.BRAIN_LOCK_STALE_S + 60)
    lk = K.lock_state()
    check("an old KeePassXC lock from a machine that answers is never cleared automatically",
          K.lock_stale(lk) is None, lk)

    print("== what kp.py writes ==")
    os.remove(K.lock_path())
    open(K.DB, "w").close()
    with K.write_lock():
        lines = open(K.lock_path()).read().split("\n")
    check("the lock carries pid, user, hostname and the machine key",
          lines[0] == str(os.getpid()) and lines[2] == K._host() and lines[3] == K.BRAIN_LOCK_TAG + me, lines)
    check("and is gone after the write", not os.path.exists(K.lock_path()))

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("RESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
