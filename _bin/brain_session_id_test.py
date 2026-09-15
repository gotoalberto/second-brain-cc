#!/usr/bin/env python3
"""Tests for brainlib.brain_session_id — one session identity for every trigger.

A Claude Code hook knows its session from the hook input; the brain CLI, the MCP server,
the git hooks and the file-watch job do not. They all resolve it the same way: the
BRAIN_SESSION_ID a wrapper exported, else the Claude Code session process when there is
one, else the literal "system" — never an invented id. The process-tree lookup is
replaced by a stub, so no `ps` runs. Run standalone:

    python3 _bin/brain_session_id_test.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def main():
    import brainlib as B
    if not hasattr(B, "brain_session_id"):
        check("brainlib.brain_session_id exists", False)
        return finish()

    real_pid = B.claude_session_pid
    old = os.environ.get("BRAIN_SESSION_ID")
    try:
        os.environ["BRAIN_SESSION_ID"] = "cli-777"
        B.claude_session_pid = lambda: 4242
        check("BRAIN_SESSION_ID wins", B.brain_session_id() == "cli-777", B.brain_session_id())
        os.environ["BRAIN_SESSION_ID"] = "   "
        check("a blank BRAIN_SESSION_ID is ignored", B.brain_session_id() == "4242", B.brain_session_id())
        os.environ.pop("BRAIN_SESSION_ID")
        check("else the Claude Code session process id", B.brain_session_id() == "4242", B.brain_session_id())
        B.claude_session_pid = lambda: 0
        check("else 'system'", B.brain_session_id() == "system", B.brain_session_id())

        def broken():
            raise OSError("ps unavailable")

        B.claude_session_pid = broken
        check("a failing lookup is 'system' too, never an exception", B.brain_session_id() == "system")
    finally:
        B.claude_session_pid = real_pid
        if old is None:
            os.environ.pop("BRAIN_SESSION_ID", None)
        else:
            os.environ["BRAIN_SESSION_ID"] = old

    env = dict(os.environ, BRAIN_SESSION_ID="from-parent-55")
    p = subprocess.run([sys.executable, "-c", "import brainlib as B; print(B.brain_session_id())"],
                       cwd=HERE, env=env, capture_output=True, text=True, timeout=30)
    check("a child process inherits the session a wrapper exported",
          p.stdout.strip() == "from-parent-55", (p.stdout, p.stderr))
    return finish()


def finish():
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
