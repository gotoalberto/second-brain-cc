#!/usr/bin/env python3
"""Which vault notes a session gets credit for, with no hook input and no database.

vault_ledger.py (the Claude Code PostToolUse adapter) and the file-watch job both decide
credit with these rules. The window rule is unchanged from vault_ledger.py: a note counts
when its mtime is later than the session's previous look, capped at MAX_WINDOW seconds —
it fails on the safe side (asking for /save again), never towards crediting someone who
did not save — and notes a git pull rewrote are never anyone's.
"""

import os

from gate_write_core import protected_folder

MAX_WINDOW = 120.0


def window_since(marker_text, now, max_window=MAX_WINDOW):
    """Start of the credit window from the session's last marker (a timestamp, or junk)."""
    try:
        since = float((marker_text or "").strip())
    except ValueError:
        since = 0.0
    return max(since, now - max_window)


def credited_notes(since, mtimes, git_touched=()):
    """Notes from {path: mtime} written strictly after `since`, minus what git rewrote."""
    skip = set(git_touched)
    return sorted(p for p, m in mtimes.items() if m > since and p not in skip)


def unlocked_protected(notes, vault, wrote_by_vw):
    """The notes under 10-Projects/ or 70-Entities/ whose last write was not vw.py's."""
    return [n for n in notes
            if protected_folder(os.path.relpath(n, vault).replace(os.sep, "/")) and not wrote_by_vw(n)]


def unlocked_notice(raw, vault):
    return ("Brain: %d shared note(s) changed without vw.py, so unlocked and with no "
            "secret redaction: %s. Write 10-Projects/ and 70-Entities/ with "
            "`python3 ~/Brain/_bin/vw.py`." % (
                len(raw), ", ".join(os.path.relpath(n, vault) for n in raw[:3])))
