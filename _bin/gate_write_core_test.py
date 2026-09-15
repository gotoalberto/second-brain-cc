#!/usr/bin/env python3
"""Regression tests for gate_write_core — the protected-path rules gate_write.py enforces.

These pin CURRENT behaviour, taken from gate_write.py's own comments and code: Bash
counts, vw.py/va.py/s3v.py/vault_sync.py/index_vault.py/git are the sanctioned writers,
reads are not writes, ~/.claude and the session scratchpad are exempt, and another live
session's claim is a conflict. The rules move into a module both the Claude Code hook and
the git pre-commit hook can call; these tests say they did not change on the way.
Pure: no disk, no database. Run standalone:

    python3 _bin/gate_write_core_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


BASH_CASES = [
    ("echo x >> 10-Projects/note.md", "10-Projects", "append redirect into a project note"),
    ("echo x > 70-Entities/person.md", "70-Entities", "overwrite redirect into an entity"),
    ("sed -i '' s/a/b/ 70-Entities/e.md", "70-Entities", "in-place sed"),
    ("cp draft.md 10-Projects/", "10-Projects", "copy into the folder"),
    ("rm 10-Projects/old.md", "10-Projects", "delete"),
    ("python3 -c \"open('10-Projects/x.md','w').write('x')\"", "10-Projects", "python open for write"),
    ("grep foo 10-Projects/a.md | tee out.txt", "10-Projects", "tee anywhere counts as a writer"),
    ("cat 10-Projects/note.md", None, "a read"),
    ("grep -r decision 70-Entities/", None, "a search"),
    ("python3 ~/Brain/_bin/vw.py append 10-Projects/x.md --sid abc", None, "vw.py is the sanctioned writer"),
    ("git add 10-Projects/x.md && git commit -m x", None, "git is allowed"),
    ("python3 _bin/vault_sync.py", None, "vault_sync is allowed"),
    ("echo hi > 30-Knowledge/x.md", None, "an unprotected folder"),
    ("", None, "empty command"),
    (None, None, "no command"),
]

FOLDER_CASES = [
    ("10-Projects/a.md", "10-Projects"),
    ("70-Entities/sub/b.md", "70-Entities"),
    ("30-Knowledge/c.md", None),
    ("10-Projects-archive/d.md", None),
    ("README.md", None),
]

EXEMPT_CASES = [
    ("/home/u/.claude/settings.json", True, "Claude config"),
    ("/home/u/.claude/skills/x/SKILL.md", True, "Claude skills"),
    ("/private/tmp/claude-501/abc/scratch.md", True, "the session scratchpad"),
    ("/tmp/claude-12/x", True, "the scratchpad without /private"),
    ("/private/var/folders/ab/cd/T/x", True, "per-user temp"),
    ("/home/u/proyectos/scratchpad/x.py", False, "a project merely called scratchpad"),
    ("/tmp/other/x", False, "other temp"),
    ("/home/u/Brain/10-Projects/a.md", False, "the vault is not exempt here"),
]


def main():
    try:
        import gate_write_core as G
        import gate_write
    except Exception as exc:
        check("gate_write_core imports", False, "%s: %s" % (type(exc).__name__, exc))
        return finish()

    print("\n== bash_touches_protected ==")
    for command, expected, why in BASH_CASES:
        got = G.bash_touches_protected(command)
        check("%s -> %s" % (why, expected), got == expected, "%r gave %r" % (command, got))
    check("gate_write.py answers every case exactly as the core does",
          all(gate_write.bash_touches_protected(c) == G.bash_touches_protected(c) for c, _e, _w in BASH_CASES))

    print("\n== protected_folder ==")
    for rel, expected in FOLDER_CASES:
        check("%s -> %s" % (rel, expected), G.protected_folder(rel) == expected, G.protected_folder(rel))
    check("the protected folders are the two shared ones", tuple(G.PROTECTED) == ("10-Projects", "70-Entities"))

    print("\n== is_exempt_path ==")
    for path, expected, why in EXEMPT_CASES:
        check("%s -> %s" % (why, expected), G.is_exempt_path(path, home="/home/u") is expected,
              G.is_exempt_path(path, home="/home/u"))

    print("\n== claim_conflict ==")
    claims = [("other", "/repo/*.py", 1000.0, 42, "proj-a"),
              ("mine", "/repo/a.py", 1000.0, 7, "proj-a"),
              ("ghost", "/repo/b.py", 1.0, 0, "proj-b"),
              ("exact", "/repo/docs/readme.md", 1000.0, 43, None)]

    def live(pid, heartbeat):
        return heartbeat > 100

    check("another live session's matching pattern is a conflict",
          G.claim_conflict("/repo/a.py", "mine", claims, live) == ("other", "proj-a"))
    check("this session's own claim is not", G.claim_conflict("/repo/x.txt", "mine", claims, live) is None)
    check("a dead session's claim is a ghost, not a conflict",
          G.claim_conflict("/repo/b.py", "other", [c for c in claims if c[0] == "ghost"], live) is None)
    check("an exact path claim conflicts",
          G.claim_conflict("/repo/docs/readme.md", "mine", claims, live) == ("exact", None))
    check("no claims, no conflict", G.claim_conflict("/repo/a.py", "mine", [], live) is None)
    return finish()


def finish():
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
