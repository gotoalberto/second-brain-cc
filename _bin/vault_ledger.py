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
import vault_ledger_core as L

MAX_WINDOW = L.MAX_WINDOW


@B.heartbeat("post-write-ledger")
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
        marker_text = open(marker).read()
    except Exception:
        marker_text = ""
    since = L.window_since(marker_text, now_)

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
    raw = L.unlocked_protected(notes, B.VAULT, B.vw_wrote_last)
    if raw:
        print(json.dumps({"systemMessage": L.unlocked_notice(raw, B.VAULT)}, ensure_ascii=False))
    sys.exit(0)


def cli(argv):
    """`vault_ledger.py --sid <sid> --paths <vault-relative notes...>`

    The entry for triggers that are not a Claude Code hook: the file-watch job credits the
    notes it saw change to the session id it resolved ("system" when no agent session is
    behind the write). Paths that do not exist are ignored.
    """
    import argparse
    ap = argparse.ArgumentParser(prog="vault_ledger.py", description="credit written notes to a session")
    ap.add_argument("--sid", required=True)
    ap.add_argument("--paths", nargs="+", required=True)
    args = ap.parse_args(argv)
    if not B.enabled():
        return 0
    notes = [os.path.join(B.VAULT, p) for p in args.paths if os.path.isfile(os.path.join(B.VAULT, p))]
    if notes:
        con = B.db()
        B.record_vault_writes(con, args.sid, notes, B.now())
        con.close()
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(cli(sys.argv[1:]))
    main()
