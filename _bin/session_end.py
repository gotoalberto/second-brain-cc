#!/usr/bin/env python3
"""SessionEnd — releases claims and marks the vault dirty. Does NOT touch git."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B


@B.fail_open
def main():
    data = B.read_hook_input()
    sid = B.sid8(data.get("session_id"))
    B.presence_remove(sid)
    _proy = B.project_name(data.get("cwd") or ".")
    B.presence_withdraw_async(sid, _proy)
    B.lease_release_async(B.project_note(_proy), sid)
    con = B.db()
    con.execute("DELETE FROM claims WHERE sid=?", (sid,))
    con.execute("DELETE FROM injected WHERE sid=?", (sid,))
    con.execute("DELETE FROM lastprompt WHERE sid=?", (sid,))
    con.execute("DELETE FROM sessions WHERE sid=?", (sid,))
    con.commit(); con.close()
    try:
        open(os.path.join(B.VAULT, "_index", ".dirty"), "w").write(str(time.time()))
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
