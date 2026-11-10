#!/usr/bin/env python3
"""Tests for rc_approve.py: Remote Control sessions behave as bypass outside plan mode.

    python3 _bin/rc_approve_test.py
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from rc_approve import decide

_p, _f = 0, 0


def check(name, cond, detail=None):
    global _p, _f
    if cond:
        _p += 1
        print("  ✓ " + name)
    else:
        _f += 1
        print("  ✗ " + name + ("\n      → %r" % (detail,) if detail is not None else ""))


BRIDGE = {"CLAUDE_CODE_ENVIRONMENT_KIND": "bridge"}
bash = {"tool_name": "Bash", "permission_mode": "auto", "tool_input": {"command": "cd ~; S=~/x; ls"}}
out = decide(bash, BRIDGE)
check("a bridge session in auto gets allow", out and out["hookSpecificOutput"]["permissionDecision"] == "allow", out)
check("so does default and acceptEdits", all(decide(dict(bash, permission_mode=m), BRIDGE) for m in ("default", "acceptEdits")))
check("plan mode is left alone", decide(dict(bash, permission_mode="plan"), BRIDGE) is None)
check("bypass needs nothing", decide(dict(bash, permission_mode="bypassPermissions"), BRIDGE) is None)
check("a question to the user still asks the user", decide(dict(bash, tool_name="AskUserQuestion"), BRIDGE) is None)
check("a terminal session is not touched", decide(bash, {}) is None)
r = subprocess.run([sys.executable, os.path.join(HERE, "rc_approve.py")], input="not json", capture_output=True, text=True,
                   env={"CLAUDE_CODE_ENVIRONMENT_KIND": "bridge"})
check("bad input: exit 0 and silent", r.returncode == 0 and not r.stdout, r)
r = subprocess.run([sys.executable, os.path.join(HERE, "rc_approve.py")], input=json.dumps(bash), capture_output=True, text=True,
                   env={"CLAUDE_CODE_ENVIRONMENT_KIND": "bridge"})
check("as a hook it prints the allow", '"permissionDecision": "allow"' in r.stdout, r.stdout)

print("\nRESULT: %d passed, %d failed" % (_p, _f))
sys.exit(1 if _f else 0)
