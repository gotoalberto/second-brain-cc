#!/usr/bin/env python3
"""git pre-commit adapter for Brain's pre-write-gate event.

Runs from githooks/pre-commit (generated from 90-Meta/events.json) in whatever repository
is committing — the vault or one of its worktrees — whichever agent, editor or person made
the change. It reads what is STAGED, from the index, not the working tree: a secret staged
and then fixed only on disk is still what would be committed.

  - A staged text file that looks like it carries a credential BLOCKS the commit. Same
    detector (brainlib.scan_secrets), same exemption (`brain:allow-secrets` in the first
    lines) and same read bound as vault_sync.py's secret gate, imported, not copied.
  - A staged change under 10-Projects/ or 70-Entities/ that vw.py did not write last only
    WARNS: a person committing by hand is exactly who this should reach, and blocking would
    make those commits impossible.

Escape hatch: `git commit --no-verify`. It skips this hook entirely, secret scan included,
so a credential committed that way reaches the remote.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.dirname(HERE)
if BIN not in sys.path:
    sys.path.insert(0, BIN)

import brainlib as B  # noqa: E402

# The protected-path rule is gate_write_core's, the same one the Claude Code gate enforces.
from gate_write_core import protected_folder  # noqa: E402

try:
    import vault_sync as _VS

    ALLOW_MARKER, ALLOW_MARKER_LINES, SCAN_MAX_CHARS = _VS.ALLOW_MARKER, _VS.ALLOW_MARKER_LINES, _VS.SCAN_MAX_CHARS
except Exception:            # the gate must still run if vault_sync cannot be imported here
    ALLOW_MARKER, ALLOW_MARKER_LINES, SCAN_MAX_CHARS = "brain:allow-secrets", 10, 8_000_000


def git(*args):
    p = subprocess.run(["git"] + list(args), capture_output=True, timeout=30)
    return p.returncode, p.stdout


def staged_paths():
    rc, out = git("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR")
    if rc != 0:
        return []
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def secret_hits(rel):
    rc, blob = git("show", ":" + rel)
    if rc != 0:
        return []
    blob = blob[:SCAN_MAX_CHARS]
    if b"\0" in blob[:8000]:
        return []                                   # binary: not text a credential hides in
    text = blob.decode("utf-8", "replace")
    if ALLOW_MARKER in "\n".join(text.splitlines()[:ALLOW_MARKER_LINES]):
        return []
    return sorted({kind for kind, _fragment in B.scan_secrets(text)})


def main():
    rc, root = git("rev-parse", "--show-toplevel")
    root = root.decode("utf-8", "replace").strip() if rc == 0 else os.getcwd()
    blocked, unlocked = [], []
    for rel in staged_paths():
        for kind in secret_hits(rel):
            blocked.append((rel, kind))
        if protected_folder(rel) and not B.vw_wrote_last(os.path.join(root, rel)):
            unlocked.append(rel)

    if unlocked:
        sys.stderr.write(
            "Brain: warning — %d staged change(s) to 10-Projects/ or 70-Entities/ were not written "
            "through vw.py, so with no lock and no secret redaction:\n%s\n"
            "The commit goes ahead. Next time write these notes with "
            "`python3 ~/Brain/_bin/vw.py append <note>`.\n"
            % (len(unlocked), "\n".join("  " + r for r in unlocked[:10])))

    if blocked:
        sys.stderr.write(
            "Brain: commit blocked — staged content looks like it carries credentials:\n%s\n"
            "What to do:\n"
            "  1. If it is real: remove it, restage the file, and rotate the credential.\n"
            "     Its place is the kdbx (python3 ~/Brain/_bin/kp.py put ...); the note keeps kp://...\n"
            "  2. If it is a synthetic example (tests, docs): put `%s` in the file's first lines.\n"
            "  3. `git commit --no-verify` skips this check AND the secret scan: a credential\n"
            "     committed that way reaches the remote. Use it only when the scan is wrong.\n"
            % ("\n".join("  %s — %s" % (rel, kind) for rel, kind in blocked), ALLOW_MARKER))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
