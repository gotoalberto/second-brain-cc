#!/usr/bin/env python3
"""T0 — SessionStart hook. Compass: rules, active projects, skills and warnings."""
import os, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

STALE_SESSION = 3600 * 6

# The cap lives in protocol_budget: it is the same number the write guard and the doctor
# look at, and keeping it in two places is how they drift apart.
import protocol_budget as PB

# Skills are NOT injected here. The harness already puts the full catalogue in the system
# prompt, so repeating it cost ~350 tokens (a quarter of the cap) and added nothing. The
# reader stays in case it ever stops coming for free.
INCLUDE_SKILLS = False


def active_projects(con, limit=6):
    rows = con.execute(
        "SELECT title, path, updated FROM notes WHERE folder='10-Projects' "
        "AND status='active' ORDER BY updated DESC, mtime DESC LIMIT ?", (limit,)).fetchall()
    return rows


def skills_lines(limit=14):
    """Skills catalogue for THIS machine.

    The index is split per machine (`INDEX-<machine>.md`) ever since the shared
    `INDEX.md` ping-ponged between machines. We read ours: the other machine's lists
    skills that are not installed here, and announcing at startup a skill that does not
    exist is worse than announcing none.

    The path comes from skills_index, which is what writes it — keeping it in two places
    is how you end up reading a different file from the one that gets generated. It is
    imported inside the function and not at the top because with INCLUDE_SKILLS at False
    this never runs, and compass does run on every startup.
    """
    import skills_index as SI
    idx = SI.index_path()
    out = []
    if os.path.exists(idx):
        for line in open(idx, errors="replace"):
            if line.startswith("- `/"):
                out.append(line.rstrip())
            if len(out) >= limit:
                break
    return out


def overlapping(con, sid, cwd):
    project = B.project_name(cwd)
    warn = []
    for osid, oproj, obranch, hb, _pid in con.execute(
            "SELECT sid, project, branch, heartbeat, pid FROM sessions WHERE sid != ?", (sid,)):
        if not B.session_alive(hb):
            continue
        if oproj and oproj == project:
            mins = int((B.now() - hb) / 60)
            warn.append("⚠️ Another session (%s) is working on `%s` (branch %s), active %d min ago."
                        % (osid, oproj, obranch or "?", mins))
    return warn


def cleanup(con):
    """Purges dead sessions and their claims. Keeps ghost claims out."""
    dead = []
    for sid, hb, _pid in con.execute("SELECT sid, heartbeat, pid FROM sessions"):
        if B.now() - (hb or 0) > STALE_SESSION:
            dead.append(sid)
    for sid in dead:
        con.execute("DELETE FROM sessions WHERE sid=?", (sid,))
        con.execute("DELETE FROM claims WHERE sid=?", (sid,))
        con.execute("DELETE FROM injected WHERE sid=?", (sid,))
        con.execute("DELETE FROM lastprompt WHERE sid=?", (sid,))
        con.execute("DELETE FROM vault_writes WHERE sid=?", (sid,))
    con.commit()


def baseline(sid, cwd):
    """Snapshot of the working tree at startup, so the memory gate can tell "the repo
    was already dirty" apart from "this session dirtied it".
    Without this snapshot the gate cannot claim the work done on the first turn."""
    try:
        os.makedirs(B.STATE, exist_ok=True)
        marker = os.path.join(B.STATE, "%s.memgate" % sid)
        if os.path.exists(marker):
            return                        # resume: the session already had state
        fp = B.tree_fingerprint(cwd)
        B.atomic_write(marker, json.dumps(
            {"ack_claims": 0, "ack_turn": 0, "ack_saves": 0,
             "ack_fp": fp, "blocked_turn": -1}))
    except Exception as e:
        B.log_error("compass.baseline", e)


def build_sections(con, sid=None, cwd=None):
    """The startup block, by section and with priority.

    High priority = it stays. It is trimmed by WHOLE SECTIONS, never by loose
    lines: trimming lines left orphaned headings ("## Active projects" without a
    single project underneath), which is worse than not putting it there at all.
    """
    secs = [("header", "# Brain — the user's memory (vault: ~/Brain)", 100)]

    prot = PB.protocol_text()
    if prot:
        secs.append(("protocol", "\n## Protocol\n" + prot, 90))

    projs = active_projects(con)
    if projs:
        secs.append(("projects", "\n## Active projects\n" +
                     "\n".join("- %s — `%s`" % (t, p) for t, p, _ in projs), 70))

    if INCLUDE_SKILLS:
        sk = skills_lines()
        if sk:
            secs.append(("skills", "\n## Available skills\n" + "\n".join(sk), 20))

    if sid is not None and cwd is not None:
        warns = overlapping(con, sid, cwd)
        if warns:
            secs.append(("warning", "\n## Warning\n" + "\n".join(warns), 95))

    total = con.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    secs.append(("footer", "\n%d notes indexed. Search with `/recall`, run with "
                 "`/task`, save with `/save`." % total, 80))
    return secs


def fit(sections):
    """Fits the sections under the cap. Returns (text, dropped, verdict).

    Drops whole lower-priority sections first, and leaves a record: a silent trim
    makes the context LOOK complete, which is exactly the bug this comes to fix.
    """
    kept = list(sections)
    dropped = []
    verdict = PB.assess(kept)
    while verdict["total"] > PB.MAX_TOKENS and len(kept) > 1:
        victim = min(kept, key=lambda s: s[2])
        if victim[2] >= 90:                 # the core is untouchable: better to overflow
            break
        kept.remove(victim)
        dropped.append(victim[0])
        verdict = PB.assess(kept)
    return "\n".join(s[1] for s in kept), dropped, verdict


def company_warning(sid, project):
    """If another session — this machine or another — is on the same project, say so NOW.

    Two sessions on the same project do not collide over code: they collide over the
    project NOTE, because both append to its end and git cannot merge two appends on the
    same line. Knowing it in time, you write a new note instead of appending.
    """
    B.presence_mark(sid, project)          # the git one: instant and local
    B.presence_beat_async(sid, project)    # the S3 one: detached, ~1 s behind
    # And the project note's lease is requested: if another machine holds it, `vw.py`
    # redirects the appends by itself instead of causing a merge conflict.
    B.lease_acquire_async(B.project_note(project), sid)
    others = B.presence_all(sid, project)  # what was already known, from both paths
    if not others:
        return ""
    # "Same project" is only announced if the project EXISTS as a note. Otherwise the
    # slug comes from the directory name and would group anyone working in the home
    # directory under the same banner.
    same = [o for o in others if o["same_project"]] if B.is_real_project(project) else []
    if same:
        who = ", ".join("%s%s" % (o["machine"],
                                    " (%.0fs ago)" % o["age"] if o.get("age") else "")
                          for o in same)
        return ("\n**HEADS UP: %s is already on project `%s`.** Do not append to the "
                "project note: write a new note and link it. Two appends to the same "
                "note from two places end in a merge conflict.\n" % (who, project))
    return ("\n%d other live session(s) (%s), on other projects.\n"
            % (len(others), ", ".join(o["machine"] for o in others)))


@B.fail_open
def main():
    t0 = time.time()
    data = B.read_hook_input()
    sid = B.sid8(data.get("session_id"))
    cwd = data.get("cwd") or os.getcwd()

    con = B.db()
    cleanup(con)
    con.execute(
        "INSERT INTO sessions(sid,cwd,project,branch,started,heartbeat,pid) "
        "VALUES(?,?,?,?,?,?,?) ON CONFLICT(sid) DO UPDATE SET heartbeat=excluded.heartbeat",
        (sid, cwd, B.project_name(cwd), B.current_branch(cwd), B.now(), B.now(), 0))
    con.commit()

    baseline(sid, cwd)

    sections = build_sections(con, sid, cwd)
    text, dropped, verdict = fit(sections)

    # Deliberately OUTSIDE the budget: it is two lines and it prevents a merge conflict.
    # Trimming this to save tokens would be a very expensive saving.
    text += company_warning(sid, B.project_name(cwd))
    n_projs = len(active_projects(con))

    # Make the trimming visible. If something was dropped, it is said inside the
    # context (for the agent) and via systemMessage (for the user).
    msg = None
    if dropped:
        text += ("\n\n> ⚠️ Startup trimmed for budget: omitted sections %s. "
                 "Check with `python3 ~/Brain/_bin/protocol_budget.py`."
                 % ", ".join(dropped))
        msg = ("Brain: the startup context did not fit and %s was omitted. "
               "Diagnose with: python3 ~/Brain/_bin/protocol_budget.py"
               % ", ".join(dropped))
    elif verdict["status"] in ("WARN", "OVER"):
        # Early warning: it still fits, but the next rule will push something out.
        msg = ("Brain: startup is at %.0f%% of budget (%d/%d tokens). %s"
               % (100 * verdict["ratio"], verdict["total"], verdict["max"],
                  PB.advice(verdict)))

    B.metric(con, sid, "compass", tokens=verdict["total"],
             latency_ms=(time.time() - t0) * 1000, hits=n_projs,
             extra="%s pct=%d dropped=%s" % (verdict["status"],
                                             int(100 * verdict["ratio"]),
                                             ",".join(dropped) or "-"))
    con.close()
    B.emit("SessionStart", text, system_message=msg)


if __name__ == "__main__":
    main()
