#!/usr/bin/env python3
"""PreToolUse hook: a Remote Control session behaves as bypass even when the app put it in auto.

Every Brain session runs in bypassPermissions (settings.example.json). Remote Control children are
spawned in bypass, but the Claude app switches a new session to Auto as it opens it, and the phone
offers no bypass in its picker. So a session opened from a link (claude.ai/code/new?q=...) asked for
permission on compound commands, a tilde in a variable or a calendar write, with nobody at the
keyboard to answer.

This hook answers "allow" for every tool call in a Remote Control session (environment kind
`bridge`) whose mode is not already bypass. It leaves alone:
  - plan mode: the user asked to review before anything runs;
  - tools that exist to ask the user something (AskUserQuestion, ExitPlanMode);
  - every other session (a terminal, scheduled tasks), which are already in bypass.
A deny from another hook (gate_write.py) still wins: the most restrictive decision applies.
Never raises and never blocks: on any doubt it prints nothing and Claude Code decides as usual.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402

ASKS_USER = {"AskUserQuestion", "ExitPlanMode"}
LEAVE_MODES = {"bypassPermissions", "plan"}


def decide(event: dict, environ=None):
    """The hook output for this tool call, or None to stay out of it."""
    environ = os.environ if environ is None else environ
    if environ.get("CLAUDE_CODE_ENVIRONMENT_KIND") != "bridge":
        return None
    if (event.get("permission_mode") or "") in LEAVE_MODES:
        return None
    if (event.get("tool_name") or "") in ASKS_USER:
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "permissionDecisionReason": "Remote Control session: every Brain session runs as bypass; "
                                    "the app can only open it in auto",
    }}


@B.heartbeat("rc-approve")
@B.fail_open
def main():
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    out = decide(event if isinstance(event, dict) else {})
    if out:
        sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - a hook must never get in the way
        sys.exit(0)
