#!/usr/bin/env python3
"""SubagentStop — a deterministic trace of subagents. No model, zero cost."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B


@B.fail_open
def main():
    data = B.read_hook_input()
    sid = B.sid8(data.get("session_id"))
    agent = data.get("agent_type") or "?"
    day = time.strftime("%Y-%m-%d")
    path = os.path.join(B.VAULT, "50-Sessions", day, "%s.md" % sid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with B.flock(path):
        if not os.path.exists(path):
            header = ("---\nid: %s-session-%s\ntitle: Session %s\ntype: session\n"
                      "area: []\nprojects: [%s]\ntags: []\nstatus: active\n"
                      "confidence: high\nsource: agent\nprovenance: hook\n"
                      "updated: %s\nsupersedes: []\n---\n\n## Trace\n"
                      % (day, sid, sid, B.project_name(data.get("cwd") or ""), day))
            open(path, "w").write(header)
        with open(path, "a") as fh:
            fh.write("- %s · subagent `%s` finished\n" % (time.strftime("%H:%M"), agent))

    # The librarian writes to the vault through vw.py, and vw.py resolves the sid
    # by cwd + heartbeat: with two live sessions in the same directory the `wrote`
    # increment lands on the wrong one. Here we DO have the parent's sid, so we credit
    # the save to whoever actually asked for it.
    if agent == "librarian":
        try:
            con = B.db()
            con.execute("UPDATE sessions SET wrote = wrote + 1 WHERE sid=?", (sid,))
            con.commit(); con.close()
        except Exception:
            pass
    sys.exit(0)


if __name__ == "__main__":
    main()
