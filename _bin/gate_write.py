#!/usr/bin/env python3
"""PreToolUse on Bash|Edit|Write|NotebookEdit. Four jobs, strict scope.

  1. Denies direct writes to 10-Projects/ and 70-Entities/ (forces vw.py).
     Bash counts. Until 2026-09-08 the matcher was `Edit|Write|NotebookEdit`, so
     `echo x >> 10-Projects/note.md` sailed straight past the gate — reproduced by
     hand that day. It matters because under bypass-permissions mode the session is
     told to prefer Bash over the file tools, which routed every write around the
     only thing protecting shared notes. Detail:
     30-Knowledge/2026-09-08-analysis-every-instrument-watches-one-surface-and-reports-on-all-of-them.md
  2. Warns/blocks if another live session holds a claim on that path, on this machine or,
     through claims_sync's local cache, on another one.
  3. Context Pack gate (strict mode, off by default).
  4. Denies a Bash command that commits, pushes or otherwise moves the vault's own git
     history: vault_sync.py is the only process that does that (gate_write_core has why).

Deliberate exemptions so as not to self-block: subagents, the vault itself,
~/.claude, the scratchpad, and anything not inside a git repo.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

CONFIG = os.path.join(B.VAULT, "_index", "config.json")

# The rules themselves live in gate_write_core, shared with the git pre-commit adapter.
# This file is the Claude Code PreToolUse adapter: it reads the hook input, asks the
# core, and answers in Claude Code's JSON.
from gate_write_core import (PROTECTED, bash_rewrites_vault_history,  # noqa: E402,F401
                             bash_touches_protected, claim_conflict,
                             is_exempt_path, protected_folder)


def config():
    try:
        return json.load(open(CONFIG))
    except Exception:
        return {"strict_pack": False, "strict_claims": False}


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason}}, ensure_ascii=False))
    sys.exit(0)


def warn(msg):
    print(json.dumps({"systemMessage": msg}, ensure_ascii=False))
    sys.exit(0)


def remote_claim_conflict(path):
    """(who, project) when a session on ANOTHER machine claims this file, else None.

    Reads only the cache claims_sync leaves in the state directory: no shared-path IO on the
    hook path. With no cache file at all (multi-machine not configured) nothing is imported.
    """
    try:
        if not os.path.exists(os.path.join(B.STATE, "claims-cache.json")):   # claims_sync.CACHE
            return None
        import claims_sync
        hit = claims_sync.remote_conflict(path)
        if hit:
            return "%s on %s" % (hit.get("sid") or "?", hit.get("machine") or "?"), None
    except Exception as e:
        B.log_error("gate_write.remote_claim_conflict", e)
    return None


@B.heartbeat("pre-write-gate")
@B.fail_open
def main():
    data = B.read_hook_input()
    ti = data.get("tool_input") or {}
    sid0 = B.sid8(data.get("session_id"))

    # Bash arrives with a command, not a file_path.
    if data.get("tool_name") == "Bash":
        command = ti.get("command") or ""
        if bash_rewrites_vault_history(command, data.get("cwd") or os.getcwd(), B.VAULT,
                                       os.path.expanduser("~")):
            deny("Sessions do not commit or push the vault: `vault_sync.py` is the only "
                 "process that touches git here, serialised with a flock, so your commit "
                 "races its pass (`cannot lock ref 'HEAD'`) and your files get swept into "
                 "its commit.\n"
                 "Just write the files and leave them. The end-of-turn hook commits them and "
                 "the daemon pushes and retries every 10 minutes.\n"
                 "If it has to happen NOW, run the daemon's own pass instead:\n"
                 "  /usr/bin/python3 %s/_bin/vault_sync.py\n"
                 "(a worktree of the vault is not affected, and `git merge --ff-only` of a "
                 "branch finished in one is allowed.)" % B.VAULT)
        folder = bash_touches_protected(command)
        if folder:
            deny("`%s/` is shared between sessions and this looks like a shell write "
                 "to it. Use:\n"
                 "  /usr/bin/python3 ~/Brain/_bin/vw.py append <note> --sid %s\n"
                 "(locks the file, redacts credentials and writes atomically).\n"
                 "If this command only READS, rewrite it so it does not look like a "
                 "write, or go through vw.py anyway." % (folder, sid0))
        sys.exit(0)

    path = ti.get("file_path") or ti.get("notebook_path") or ""
    if not path:
        sys.exit(0)
    path = os.path.abspath(os.path.expanduser(path))
    sid = B.sid8(data.get("session_id"))
    cwd = data.get("cwd") or os.getcwd()
    cfg = config()
    is_subagent = bool(data.get("agent_type"))

    # 1. shared vault notes -> only through vw.py
    if B.in_vault(path):
        rel = os.path.relpath(path, os.path.realpath(B.VAULT))
        if protected_folder(rel.replace(os.sep, "/")):
            deny("This note is shared between sessions. Write it with:\n"
                 "  /usr/bin/python3 ~/Brain/_bin/vw.py append %s --sid %s\n"
                 "(locks the file, redacts credentials and writes atomically)."
                 % (rel, sid))
        sys.exit(0)          # the rest of the vault is written normally

    # exemptions: Claude config and the session's own ephemeral scratchpad.
    # The pattern is deliberately strict: a user project happening to be called
    # "scratchpad" must NOT be exempted.
    if is_exempt_path(path, os.path.expanduser("~")):
        sys.exit(0)

    con = B.db()

    # 2. claims held by other live sessions
    rows = []
    for osid, pattern in con.execute("SELECT sid, pattern FROM claims WHERE sid != ?", (sid,)).fetchall():
        row = con.execute("SELECT heartbeat, pid, project FROM sessions WHERE sid=?", (osid,)).fetchone()
        if row:
            rows.append((osid, pattern, row[0], row[1], row[2]))
    conflict = claim_conflict(path, sid, rows, B.session_live)   # ghost claims are skipped there
    if not conflict:
        conflict = remote_claim_conflict(path)

    # record this session's dynamic claim
    try:
        con.execute("INSERT OR IGNORE INTO claims VALUES(?,?,?)", (sid, path, B.now()))
        con.commit()
    except Exception:
        pass

    # 3. pack gate (only git repos that are not the vault, never for subagents)
    needs_pack = False
    if cfg.get("strict_pack") and not is_subagent:
        root = B.repo_root(os.path.dirname(path) or cwd)
        if root and not B.in_vault(root):
            marker = os.path.join(B.STATE, "%s.pack" % sid)
            needs_pack = not os.path.exists(marker)
    con.close()

    if conflict:
        msg = ("⚠️ Session %s is working on `%s` (project %s). "
               "Risk of a semantic conflict: coordinate or pick another file."
               % (conflict[0], os.path.basename(path), conflict[1] or "?"))
        if cfg.get("strict_claims"):
            deny(msg)
        if needs_pack:
            deny("No Context Pack in this session. Run `/task` or `/ctx` before changing code.")
        warn(msg)

    if needs_pack:
        deny("No Context Pack in this session. Run `/task` or `/ctx` before changing code.")
    sys.exit(0)


if __name__ == "__main__":
    main()
