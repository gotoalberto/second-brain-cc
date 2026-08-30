#!/usr/bin/env python3
"""context-scout's own hook: it may only write Context Packs."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B


@B.fail_open
def main():
    data = B.read_hook_input()
    ti = data.get("tool_input") or {}
    path = ti.get("file_path") or ""
    if not path:
        sys.exit(0)
    allowed = os.path.realpath(os.path.join(B.VAULT, "60-Context-Packs"))
    if not os.path.realpath(os.path.expanduser(path)).startswith(allowed):
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason":
                "context-scout is read-only except in 60-Context-Packs/. "
                "Write the pack there and return its path; change nothing else."}},
            ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
