#!/usr/bin/env python3
"""PreToolUse on Bash|Edit|Write|NotebookEdit. Three jobs, strict scope.

  1. Denies direct writes to 10-Projects/ and 70-Entities/ (forces vw.py).
     Bash counts. Until 2026-09-08 the matcher was `Edit|Write|NotebookEdit`, so
     `echo x >> 10-Projects/note.md` sailed straight past the gate — reproduced by
     hand that day. It matters because under bypass-permissions mode the session is
     told to prefer Bash over the file tools, which routed every write around the
     only thing protecting shared notes. Detail:
     30-Knowledge/2026-09-08-analysis-every-instrument-watches-one-surface-and-reports-on-all-of-them.md
  2. Warns/blocks if another live session holds a claim on that path.
  3. Context Pack gate (strict mode, off by default).

Deliberate exemptions so as not to self-block: subagents, the vault itself,
~/.claude, the scratchpad, and anything not inside a git repo.
"""
import os, re, sys, json, fnmatch
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

CONFIG = os.path.join(B.VAULT, "_index", "config.json")
PROTECTED = ("10-Projects", "70-Entities")

# A shell command cannot be parsed reliably, so this does not try. It asks two
# questions: does the command name a protected folder, and does it look like it
# writes? Both yes -> deny. That misses an obfuscated path and is fine: the point is
# to stop the ordinary `>>`, `sed -i` and `open(...,"w")`, not to be a sandbox.
# vault_ledger.py catches after the fact whatever gets through, by mtime.
_WRITERS = re.compile(
    r">>?\s*['\"]?[^\s|&;'\"]*(?:10-Projects|70-Entities)"   # > file  /  >> file
    r"|\b(?:sed\s+-i|tee|truncate|dd|install)\b"             # in-place editors
    r"|\b(?:cp|mv|rm|touch|mkdir|rsync|ln)\b"                # file moves
    r"|open\s*\([^)]*['\"][wa]\+?['\"]"                      # python open(..., 'w')
    r"|\.write(?:lines)?\s*\("                               # python .write(
    r"|\bshutil\.(?:copy|move)\b"
)

# Sanctioned writers and version control: this is how a protected note is SUPPOSED to
# be written, so they must never be denied or the gate blocks its own remedy.
_ALLOWED = re.compile(r"\b(?:vw\.py|va\.py|s3v\.py|vault_sync\.py|index_vault\.py|git)\b")


def bash_touches_protected(command):
    """Which protected folder this shell command looks like it writes to, or None."""
    if not command or _ALLOWED.search(command):
        return None
    hit = next((p for p in PROTECTED if p in command), None)
    if not hit:
        return None
    return hit if _WRITERS.search(command) else None


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


@B.fail_open
def main():
    data = B.read_hook_input()
    ti = data.get("tool_input") or {}
    sid0 = B.sid8(data.get("session_id"))

    # Bash arrives with a command, not a file_path.
    if data.get("tool_name") == "Bash":
        folder = bash_touches_protected(ti.get("command") or "")
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
        if rel.split(os.sep)[0] in PROTECTED:
            deny("This note is shared between sessions. Write it with:\n"
                 "  /usr/bin/python3 ~/Brain/_bin/vw.py append %s --sid %s\n"
                 "(locks the file, redacts credentials and writes atomically)."
                 % (rel, sid))
        sys.exit(0)          # the rest of the vault is written normally

    # exemptions: Claude config and the session's own ephemeral scratchpad.
    # The pattern is deliberately strict: a user project happening to be called
    # "scratchpad" must NOT be exempted.
    home = os.path.expanduser("~")
    if path.startswith(os.path.join(home, ".claude")):
        sys.exit(0)
    if re.match(r"^/(private/)?tmp/claude-\d+/", path) or path.startswith("/private/var/folders/"):
        sys.exit(0)

    con = B.db()

    # 2. claims held by other live sessions
    conflict = None
    for osid, pattern in con.execute("SELECT sid, pattern FROM claims WHERE sid != ?", (sid,)):
        row = con.execute("SELECT heartbeat, pid, project FROM sessions WHERE sid=?", (osid,)).fetchone()
        if not row:
            continue
        hb, opid, proj = row
        if not B.session_live(opid, hb):
            continue                      # ghost claim from a dead session
        if fnmatch.fnmatch(path, pattern) or path == pattern:
            conflict = (osid, proj)
            break

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
