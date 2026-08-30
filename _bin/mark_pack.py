#!/usr/bin/env python3
"""Mark that this directory's session already has a Context Pack (strict mode)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__.strip())
        print("\nUsage: mark_pack.py [pack-path]")
        sys.exit(0)
    if not B.enabled():
        sys.exit(0)
    cwd = os.getcwd()
    try:
        con = B.db()
        rows = con.execute("SELECT sid, cwd, heartbeat FROM sessions ORDER BY heartbeat DESC").fetchall()
        con.close()
        os.makedirs(B.STATE, exist_ok=True)
        marked = []
        for sid, scwd, hb in rows:
            if scwd and (os.path.realpath(scwd) == os.path.realpath(cwd)):
                open(os.path.join(B.STATE, "%s.pack" % sid), "w").write(sys.argv[1] if len(sys.argv) > 1 else "1")
                marked.append(sid)
        if not marked and rows:
            sid = rows[0][0]
            open(os.path.join(B.STATE, "%s.pack" % sid), "w").write("1")
            marked.append(sid)
        print("pack marked for: %s" % (", ".join(marked) or "no session registered"))
    except Exception as exc:
        print("warning: %r" % exc)
    sys.exit(0)


if __name__ == "__main__":
    main()
