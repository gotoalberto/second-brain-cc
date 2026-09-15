#!/usr/bin/env python3
"""The protected-path rules, with no hook input and no database.

gate_write.py (the Claude Code PreToolUse adapter) and the git pre-commit adapter both call
these, so the rule that 10-Projects/ and 70-Entities/ are written only through vw.py lives
in one place. Behaviour is exactly what gate_write.py enforced before the split; see
gate_write_core_test.py.
"""

import fnmatch
import re

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

_SCRATCHPAD = re.compile(r"^/(private/)?tmp/claude-\d+/")


def bash_touches_protected(command):
    """Which protected folder this shell command looks like it writes to, or None."""
    if not command or _ALLOWED.search(command):
        return None
    hit = next((p for p in PROTECTED if p in command), None)
    if not hit:
        return None
    return hit if _WRITERS.search(command) else None


def protected_folder(rel_path):
    """The protected top-level folder a vault-relative path is under, or None."""
    top = (rel_path or "").replace("\\", "/").split("/", 1)[0]
    return top if top in PROTECTED else None


def is_exempt_path(path, home):
    """Paths the gate never judges: Claude's own config and the session's ephemeral space.

    The scratchpad pattern is deliberately strict: a user project happening to be called
    "scratchpad" must NOT be exempted.
    """
    return (path.startswith(home.rstrip("/") + "/.claude")
            or bool(_SCRATCHPAD.match(path))
            or path.startswith("/private/var/folders/"))


def claim_conflict(path, sid, claims, live):
    """(other session id, its project) holding a claim that covers `path`, or None.

    `claims` are (sid, pattern, heartbeat, pid, project) rows; `live(pid, heartbeat)`
    says whether that session is still running — a dead session's claim is a ghost.
    """
    for osid, pattern, heartbeat, pid, project in claims:
        if osid == sid or not live(pid, heartbeat):
            continue
        if fnmatch.fnmatch(path, pattern) or path == pattern:
            return osid, project
    return None
