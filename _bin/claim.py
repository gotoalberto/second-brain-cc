#!/usr/bin/env python3
"""Records which files this session is going to touch, to warn the others.

  claim.py file1.py file2.py              records
  claim.py --list                         shows the live claims
  claim.py --release                      releases this session's
  claim.py --release --sid <id>           releases that one's, no guessing

The whole thing rests on knowing WHICH session is running it, and that turned out to
be the hard part. It used to be worked out by comparing the current directory against
the `sessions` table, and when nothing matched it settled for whichever session had
beaten last. On 2026-09-02 that deleted a live session's claims and left the caller's
own untouched: several sessions on one machine can share the cwd `~`, so the tie-break was a
coin toss. Claims are the only thing keeping two agents off the same file, so a
`--release` pointed at the wrong session disarms them with nobody the wiser.

The identity that does not lie is the PROCESS. `claude_session_pid()` climbs to the
long-lived Claude Code process, and `sessions.pid` holds that same number, written by
the hooks. That is something observed, not inferred from where somebody was standing.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B


# The rule for working out whose session this is lives in brainlib, and there is
# only one copy on purpose: it used to be written out twice — here and in
# `brainlib.current_sid()` — and both copies got the same answer wrong, each doing
# its own damage. Duplicating it is what let the second one survive the first fix.
current_sid = B.current_sid


def candidates(con, cwd):
    """Who it might have been, to say so instead of only refusing."""
    out = []
    for sid, scwd, spid, hb in con.execute(
            "SELECT sid, cwd, pid, heartbeat FROM sessions ORDER BY heartbeat DESC"):
        if B.session_live(spid or 0, hb):
            same = scwd and os.path.realpath(scwd) == os.path.realpath(cwd)
            out.append("%s%s" % (sid, " (this cwd)" if same else ""))
    return out


def arg_value(name):
    """`--sid X`, and also `--sid=X`."""
    for i, a in enumerate(sys.argv):
        if a == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def main():
    if not B.enabled():
        return 0
    con = B.db()
    cwd = os.getcwd()
    explicit = arg_value("--sid")
    sid, how = (explicit, "--sid") if explicit else current_sid(con, cwd)

    if "--list" in sys.argv:
        for s, pat, ts in con.execute("SELECT sid, pattern, created FROM claims ORDER BY created DESC"):
            row = con.execute("SELECT heartbeat, pid, project FROM sessions WHERE sid=?", (s,)).fetchone()
            alive = bool(row) and B.session_alive(row[0])
            print("%s  %s  %s" % ("LIVE " if alive else "dead", s, pat))
        return 0

    if "--release" in sys.argv:
        if not sid:
            # Refusing IS the fix. Releasing somebody else's claims is worse than
            # releasing none: nobody notices, and the next collision arrives with no
            # warning at all.
            print("I cannot tell which session this is, so I am releasing nothing.")
            others = candidates(con, cwd)
            if others:
                print("live sessions right now: %s" % ", ".join(others))
            print("name it: claim.py --release --sid <id>")
            return 1
        n = con.execute("SELECT COUNT(*) FROM claims WHERE sid=?", (sid,)).fetchone()[0]
        con.execute("DELETE FROM claims WHERE sid=?", (sid,)); con.commit()
        print("%d claim(s) released for %s (by %s)" % (n, sid, how))
        return 0

    if not sid:
        print("I cannot tell which session this is; nothing recorded.")
        return 0
    n = 0
    for arg in sys.argv[1:]:
        if arg.startswith("--"):
            continue
        if explicit and arg == explicit:      # the value of --sid, not a file
            continue
        path = os.path.abspath(os.path.expanduser(arg))
        con.execute("INSERT OR IGNORE INTO claims VALUES(?,?,?)", (sid, path, B.now()))
        n += 1
    con.commit()
    print("%d claim(s) recorded for session %s (by %s)" % (n, sid, how))
    return 0


if __name__ == "__main__":
    sys.exit(main())
