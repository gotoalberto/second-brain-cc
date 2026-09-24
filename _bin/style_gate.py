#!/usr/bin/env python3
"""Stop hook: the reply just written must not read as written by an AI.

The convention (30-Knowledge/2026-09-10-convention-write-like-a-person.md) had been in the
startup context for weeks and replies still came back full of dashes, "X, not Y" contrasts,
label colons and stock phrases, in English and in Spanish. So every reply is checked
mechanically with style_check.py.

It reads the transcript, takes the assistant text written since the last user prompt (tool
results are not prompts) and scans its prose; quotes, code and URLs are skipped. On a finding
it blocks the stop once and asks for the reply to be sent again, rewritten.

Anti-loop:
  1. never blocks when Claude Code says the stop already comes from a stop hook;
  2. at most one block per reply: the hash of the blocked text is remembered per session;
  3. any error passes (fail open). A broken style check must never trap a session.
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402
import style_check as S  # noqa: E402


def _last_reply(path):
    """Assistant text blocks after the last real user prompt (tool results are not prompts)."""
    texts = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if not isinstance(e, dict):
                continue
            msg = e.get("message") or {}
            role = msg.get("role") or e.get("type")
            content = msg.get("content")
            if role == "user":
                if isinstance(content, str) and content.strip():
                    texts = []
                elif isinstance(content, list) and any(
                        isinstance(c, dict) and c.get("type") == "text" for c in content):
                    texts = []
            elif role == "assistant" and isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text" and c.get("text"):
                        texts.append(c["text"])
    return "\n\n".join(texts)


@B.heartbeat("stop-style-gate")
@B.fail_open
def main():
    data = B.read_hook_input()
    if not isinstance(data, dict) or data.get("stop_hook_active"):
        sys.exit(0)
    path = data.get("transcript_path")
    sid = B.sid8(data.get("session_id") or "nosession")
    if not path or not os.path.exists(path):
        sys.exit(0)
    reply = _last_reply(path)
    if not reply.strip():
        sys.exit(0)
    hits = S.find(reply)
    if not hits:
        sys.exit(0)
    h = hashlib.sha1(reply.encode("utf-8")).hexdigest()
    os.makedirs(B.STATE, exist_ok=True)
    marker = os.path.join(B.STATE, "%s.stylegate" % sid)
    try:
        with open(marker, encoding="utf-8") as fh:
            if fh.read().strip() == h:
                sys.exit(0)
    except OSError:
        pass
    with open(marker, "w", encoding="utf-8") as fh:
        fh.write(h)
    sys.stderr.write(
        "Style gate: the reply you just wrote has expressions that read as written by an AI "
        "(any language):\n%s\n\n"
        "Send the reply again, rewritten in plain words the way a colleague would say it, "
        "keeping every fact and number. Do not mention this check. Rule: "
        "30-Knowledge/2026-09-10-convention-write-like-a-person.md\n" % S.report(hits, 12))
    sys.exit(2)


if __name__ == "__main__":
    main()
