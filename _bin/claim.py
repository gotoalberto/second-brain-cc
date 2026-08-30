#!/usr/bin/env python3
"""Records which files this session is going to touch, to warn the others.

  claim.py file1.py file2.py              records
  claim.py --list                         shows the live claims
  claim.py --release                      releases this session's
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B


def current_sid(con, cwd):
    rows = con.execute("SELECT sid, cwd, heartbeat FROM sessions ORDER BY heartbeat DESC").fetchall()
    for sid, scwd, _ in rows:
        if scwd and os.path.realpath(scwd) == os.path.realpath(cwd):
            return sid
    return rows[0][0] if rows else None


def main():
    if not B.enabled():
        return 0
    con = B.db()
    cwd = os.getcwd()
    sid = current_sid(con, cwd)

    if "--list" in sys.argv:
        for s, pat, ts in con.execute("SELECT sid, pattern, created FROM claims ORDER BY created DESC"):
            row = con.execute("SELECT heartbeat, pid, project FROM sessions WHERE sid=?", (s,)).fetchone()
            alive = bool(row) and B.session_alive(row[0])
            print("%s  %s  %s" % ("LIVE " if alive else "dead", s, pat))
        return 0

    if "--release" in sys.argv:
        con.execute("DELETE FROM claims WHERE sid=?", (sid,)); con.commit()
        print("claims released for %s" % sid); return 0

    if not sid:
        print("no session registered; no claims recorded"); return 0
    n = 0
    for arg in sys.argv[1:]:
        if arg.startswith("--"):
            continue
        path = os.path.abspath(os.path.expanduser(arg))
        con.execute("INSERT OR IGNORE INTO claims VALUES(?,?,?)", (sid, path, B.now()))
        n += 1
    con.commit()
    print("%d claim(s) recorded for session %s" % (n, sid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
