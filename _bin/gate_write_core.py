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
_ALLOWED = re.compile(r"\b(?:vw\.py|va\.py|files\.py|vault_sync\.py|index_vault\.py|git)\b")

# ...but only for the segment that actually runs them. A single `_ALLOWED` hit anywhere in
# the command used to waive the whole thing, so `cp /tmp/x 10-Projects/note.md && git add -A`
# passed: the raw write and the word "git" travelled in one command. Splitting on the
# shell's sequencing operators and judging each segment on its own keeps the remedy working
# (a real vw.py call is its own segment) while the raw write beside it is still caught.
#
# A plain `|` is deliberately NOT a separator here. It chains one data flow rather than
# sequencing independent commands, and splitting on it would let
# `grep foo 10-Projects/a.md | tee out.txt` through: the gate's standing posture is to deny
# when a protected path and a writer share a command, even though that particular one only
# writes to out.txt. gate_write_core_test.py pins that case.
_SEGMENT = re.compile(r"&&|\|\||;|\n")

_SCRATCHPAD = re.compile(r"^/(private/)?tmp/claude-\d+/")


# vault_sync.py is the only process that touches git in the vault: sessions write files, and
# the daemon (and the end-of-turn `--hook` pass) commits and pushes under a flock. That was a
# docstring and nothing else, so a session ran its own `git add && git commit && git push` in
# the vault and collided with a daemon pass in flight: `cannot lock ref 'HEAD'`, and the
# session's files were swept into the daemon's own commit, losing the message that explained
# them. Both processes did what they were written to do; what was missing was the barrier.
#
# Only history-writing verbs are denied. Reads (status, log, diff, show) and `git add` are
# untouched: staging is harmless on its own, and the daemon commits whatever is staged. `pull`
# is in because it moves HEAD, which is exactly what collides with the daemon; `fetch` is not.
#
# The verb must be git's SUBCOMMAND, not the word anywhere in the line: matching it loosely
# denied `git log -- <a note whose filename contains "commit">`, a plain read. So git's own
# options and their values are skipped, the first bare word is the subcommand, and nothing
# after `--` is looked at.
_GIT_VERBS = {"commit", "push", "pull", "rebase", "merge", "cherry-pick", "revert", "reset", "stash"}
_GIT_OPTS_WITH_VALUE = ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path")

# A worktree of the vault is a different checkout with its own HEAD. The daemon never touches
# it, so committing there is the sanctioned flow (code goes in a worktree) and must not be
# caught just because its path sits under the vault.
_WORKTREE = re.compile(r"worktree|/_worktrees/")
_CD = re.compile(r"^\s*\(?\s*cd\s+([^\s|&;)]+)")


def _git_invocation(segment):
    """(subcommand, the directory it was aimed at with -C/--git-dir/--work-tree or None)
    for the first `git` in this shell segment, or (None, None)."""
    words = segment.split()
    try:
        i = next(n for n, w in enumerate(words) if w == "git" or w.endswith("/git"))
    except StopIteration:
        return None, None
    i += 1
    target = None
    while i < len(words):
        w = words[i]
        if w == "--":                       # everything after this is paths, not verbs
            return None, target
        if w in _GIT_OPTS_WITH_VALUE:       # `-C <path>`: the value is not the subcommand
            if w != "-c" and i + 1 < len(words):
                target = words[i + 1]
            i += 2
            continue
        if w.startswith("--git-dir=") or w.startswith("--work-tree="):
            target = w.split("=", 1)[1]
        if w.startswith("-"):               # `--git-dir=x`, `--no-pager`, `--help`, ...
            i += 1
            continue
        return w, target
    return None, target


def _normpath(path):
    out = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if out:
                out.pop()
            continue
        out.append(part)
    return "/" + "/".join(out)


def _resolve_dir(path, cwd, home):
    """An absolute, normalised directory for a `cd` or `-C` argument, or "" if unknowable."""
    path = (path or "").strip("'\"")
    for prefix in ("${HOME}", "$HOME", "~"):
        if path == prefix or path.startswith(prefix + "/"):
            path = (home or "") + path[len(prefix):]
            break
    if not path or "$" in path or path.startswith("~"):
        return ""
    if not path.startswith("/"):
        if not cwd:
            return ""
        path = cwd + "/" + path
    return _normpath(path)


def _is_vault(path, vault):
    """Does this directory sit in the vault checkout itself (not a worktree under it)?"""
    if not path or not vault or _WORKTREE.search(path):
        return False
    if path.endswith("/.git"):
        path = path[:-len("/.git")]
    return path == vault or path.startswith(vault + "/")


def bash_rewrites_vault_history(command, cwd="", vault="", home=""):
    """True if this shell command would write the VAULT's own git history.

    `cwd` is the session's working directory, `vault` the vault root and `home` what `~` and
    `$HOME` expand to. A `cd` is not judged per segment: it sets the directory for everything
    after it, so `cd <vault> && git commit` and `cd <other repo> && git commit` are read as a
    whole. Anything aimed elsewhere (another repo, a worktree) is never denied.
    """
    if not command or not vault:
        return False
    vault = _normpath(vault)
    here = _resolve_dir(cwd, "", home)
    for segment in _SEGMENT.split(command):
        cd = _CD.search(segment)
        if cd:
            here = _resolve_dir(cd.group(1), here, home)
        verb, target = _git_invocation(segment)
        if verb not in _GIT_VERBS or _WORKTREE.search(segment):
            continue
        # A fast-forward of a branch finished in a worktree is how /task integrates work into
        # the vault. Its commits already exist with their own messages, so nothing can be
        # swept into the daemon's commit; if it meets the daemon's lock it fails and is retried.
        if verb == "merge" and "--ff-only" in segment.split():
            continue
        where = _resolve_dir(target, here, home) if target else here
        if _is_vault(where, vault):
            return True
    return False


def bash_touches_protected(command):
    """Which protected folder this shell command looks like it writes to, or None.

    Judged per shell segment: a sanctioned writer only exempts the segment it runs in.
    """
    if not command:
        return None
    for segment in _SEGMENT.split(command):
        if _ALLOWED.search(segment):
            continue
        hit = next((p for p in PROTECTED if p in segment), None)
        if hit and _WRITERS.search(segment):
            return hit
    return None


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
