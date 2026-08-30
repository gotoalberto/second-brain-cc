#!/usr/bin/env python3
"""Stop — memory gate. Demands a save on EVERY iteration that leaves work unsaved.

It used to block once per session: ignoring it at the start was enough for the rest of
the session to end without writing anything to the vault. Now the gate is evaluated every
turn and warns again whenever new work appears.

Both signals are MEASURED, not self-declared (2026-08-21, see
30-Knowledge/2026-08-21-decision-gate-measures-effect-not-event.md):

  did it work?    Edit/Write claims  ∪  the working tree fingerprint (and its worktrees)
                  changed against the startup snapshot. The second one sees work done
                  through Bash, invisible to the first — which is how every session works
                  in bypass mode.
  did it save?    the `vault_writes` ledger (vault notes whose mtime falls inside one of
                  this session's calls) ∪ the old `wrote` counter. That counter was only
                  touched by vw.py and the librarian: a note written by hand into
                  30-Knowledge/, which is what the protocol mandates, did not count.

Anti-loop, in three layers:
  1. at most ONE block per turn (`blocked_turn`);
  2. if nothing was saved after warning, the work is treated as acknowledged and it does
     not insist again until new work appears;
  3. state is written BEFORE blocking, so a later failure never traps the session.

The push to the remote does NOT happen here: vault_sync.py does it, the only process that
touches git, chained behind this hook on the Stop event.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

MIN_TURNS = 6


def _load(path):
    try:
        with open(path) as fh:
            d = json.load(fh)
        if isinstance(d, dict):
            return {"ack_claims": int(d.get("ack_claims", -1)),
                    "ack_turn": int(d.get("ack_turn", 0)),
                    # old format: the `wrote` counter played the part of ack_saves
                    "ack_saves": int(d.get("ack_saves", d.get("wrote", 0))),
                    "ack_fp": d.get("ack_fp"),
                    "blocked_turn": int(d.get("blocked_turn", -1))}
    except Exception:
        pass
    # old-format marker ("1"): session already warned, start from zero
    return {"ack_claims": -1, "ack_turn": 0, "ack_saves": 0,
            "ack_fp": None, "blocked_turn": -1}


def _save(path, st):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(st, fh)
    os.replace(tmp, path)


@B.fail_open
def main():
    data = B.read_hook_input()
    if not data.get("session_id"):
        sys.exit(0)               # no session, nobody to claim from (fail-open)
    sid = B.sid8(data.get("session_id"))
    cwd = data.get("cwd") or os.getcwd()
    os.makedirs(B.STATE, exist_ok=True)
    marker = os.path.join(B.STATE, "%s.memgate" % sid)

    con = B.db()
    row = con.execute("SELECT turns, wrote FROM sessions WHERE sid=?", (sid,)).fetchone()
    edits = con.execute("SELECT COUNT(*) FROM claims WHERE sid=?", (sid,)).fetchone()[0]
    guardadas = B.vault_writes_count(con, sid)
    con.close()
    if not row:
        sys.exit(0)
    turns, wrote = row[0] or 0, row[1] or 0
    saves = wrote + guardadas

    st = _load(marker)
    # What OTHER live sessions wrote is not this one's work and cannot be claimed from
    # it. With two sessions in the same tree, without this the gate blames whoever did
    # not do it. The attribution available is the vault-writes ledger, which is per
    # mtime and per session; for code there is none, and there the false positive is
    # accepted: the gate insists at most once per turn.
    foreign_ones = set()
    try:
        con3 = B.db()
        for other in B.live_sessions(con3, exclude=sid):
            for (path,) in con3.execute("SELECT path FROM vault_writes WHERE sid=?", (other,)):
                foreign_ones.add(os.path.relpath(path, B.VAULT))
        con3.close()
    except Exception:
        foreign_ones = set()
    fp = B.tree_fingerprint(cwd, exclude=foreign_ones)   # None if cwd is not in a git repo

    def ack(blocked_turn=None):
        _save(marker, {"ack_claims": edits, "ack_turn": turns, "ack_saves": saves,
                       "ack_fp": fp if fp else st["ack_fp"],
                       "blocked_turn": st["blocked_turn"] if blocked_turn is None
                                       else blocked_turn})

    # something was saved since the last look: current work counts as covered
    if saves > st["ack_saves"]:
        ack()
        sys.exit(0)

    # max(...,0): with no recorded edits there is no "new work" to claim. With the
    # initial -1, 0 > -1 was true and the warning read "0 file(s)".
    new_edits = edits > max(st["ack_claims"], 0)
    # with no reference snapshot (a session older than this change, or a cwd outside a
    # repo) the fingerprint accuses nobody: take today's and it counts from the next turn.
    disk_changed = bool(fp) and st["ack_fp"] is not None and fp != st["ack_fp"]
    long_overdue = (turns - st["ack_turn"]) >= MIN_TURNS and saves == 0

    if not (new_edits or disk_changed or long_overdue):
        if fp and st["ack_fp"] is None:
            ack()                          # only pins the snapshot that was missing
        sys.exit(0)

    # already warned in this same turn: do not insist (avoids the Stop->Stop loop)
    if st["blocked_turn"] == turns:
        ack()
        sys.exit(0)

    _save(marker, {"ack_claims": st["ack_claims"], "ack_turn": st["ack_turn"],
                   "ack_saves": saves, "ack_fp": st["ack_fp"], "blocked_turn": turns})
    if new_edits:
        what = "touched %d file(s)" % edits
    elif disk_changed:
        what = "changed the working tree"
    else:
        what = "run %d turns without saving" % (turns - st["ack_turn"])
    sys.stderr.write(
        "This iteration %s and nothing was saved to the vault.\n"
        "Run /save before handing control back: a decision made, a convention "
        "discovered, or project state. If there genuinely is nothing memorable, "
        "say so in one line and finish.\n" % what)
    sys.exit(2)


if __name__ == "__main__":
    main()
