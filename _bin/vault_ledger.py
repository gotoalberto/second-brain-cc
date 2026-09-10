#!/usr/bin/env python3
"""PostToolUse — records which vault notes THIS session wrote.

It replaces the `wrote` counter, which only `vw.py` and the `librarian` subagent
incremented: a note written straight into `30-Knowledge/` —which is exactly what
protocol §5 mandates— did not count as having saved.

The command is not parsed and the tool is not taken at its word: the disk is checked.
After each tool call, notes with an mtime inside the window are looked up
(this session's last post, now], and credited to the `sid` arriving in the
hook — never deduced from cwd (see 2026-08-21-failure-wrote-credited-to-the-wrong-session).

The window is capped at MAX_WINDOW seconds. If a call takes longer, the write is lost
and the gate will ask for /save again: it fails on the safe side (asking too much), never
towards crediting someone who did not save.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

MAX_WINDOW = 120.0


@B.fail_open
def main():
    if not B.enabled():
        sys.exit(0)
    data = B.read_hook_input()
    if not data.get("session_id"):
        sys.exit(0)               # fail-open: with no session nothing is credited
    sid = B.sid8(data.get("session_id"))
    if not sid:
        sys.exit(0)

    os.makedirs(B.STATE, exist_ok=True)
    marker = os.path.join(B.STATE, "%s.vwin" % sid)
    now_ = B.now()
    try:
        since = float(open(marker).read().strip())
    except Exception:
        since = 0.0
    since = max(since, now_ - MAX_WINDOW)

    # the marker is written BEFORE working: if something blows up later, the next call
    # starts from a short window instead of rescanning the whole vault.
    try:
        B.atomic_write(marker, str(now_))
    except Exception:
        pass

    if since <= 0:
        sys.exit(0)
    notes = B.vault_notes_modified_since(since)
    if not notes:
        sys.exit(0)
    con = B.db()
    B.record_vault_writes(con, sid, notes, now_)
    con.close()

    # A protected note that changed without vw.py went around gate_write.py. The gate
    # cannot reliably parse a shell command, so it will miss some; the disk cannot be
    # fooled. Prevention is best-effort, detection is not — say it out loud rather than
    # let a shared note be edited unlocked in silence.
    # Detail: 30-Knowledge/2026-09-08-analysis-every-instrument-watches-one-surface-and-reports-on-all-of-them.md
    raw = [n for n in notes
           if os.path.relpath(n, B.VAULT).split(os.sep)[0] in ("10-Projects", "70-Entities")
           and not B.vw_wrote_last(n)]
    if raw:
        print(json.dumps({"systemMessage":
            "Brain: %d shared note(s) changed without vw.py, so unlocked and with no "
            "secret redaction: %s. Write 10-Projects/ and 70-Entities/ with "
            "`python3 ~/Brain/_bin/vw.py`." % (
                len(raw), ", ".join(os.path.relpath(n, B.VAULT) for n in raw[:3]))},
            ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
