#!/usr/bin/env python3
"""PostToolUse — guard for the startup budget.

Warns AT THE MOMENT someone fattens `90-Meta/PROTOCOL-COMPACT.md`, rather than
finding out sessions later because a section stopped showing up.

The bug it fixes: a new rule in the protocol pushed the T0 block over the cap and
`compass.py` trimmed in silence. The damage did not show when the rule was written,
but on the startups that followed — and since the context still looked complete,
nothing gave the loss away.

It speaks only when the verdict changes: repeating the same warning every time a
file is touched turns the signal into noise and stops being read.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B
import protocol_budget as PB

STATE = os.path.join(B.STATE, "protocol_budget.json")

# Time margin for considering that THIS call touched the protocol.
# Deliberately generous: an edit via `sed` or a heredoc leaves no trace in tool_input,
# so mtime is the only reliable clue.
FRESH_SECONDS = 20


def touched_protocol(data):
    """Was the protocol just touched? By mtime, not by what the tool claims."""
    try:
        if not os.path.exists(PB.PROTOCOL):
            return False
        if B.now() - os.path.getmtime(PB.PROTOCOL) > FRESH_SECONDS:
            return False
    except Exception:
        return False
    return True


def signature(verdict):
    """What counts as "the same warning": status, occupancy decile and fat-line count."""
    return "%s/%d/%d" % (verdict["status"], int(verdict["ratio"] * 10),
                         len(verdict["fat_lines"]))


def load_state():
    try:
        with open(STATE) as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_state(sig):
    try:
        os.makedirs(B.STATE, exist_ok=True)
        B.atomic_write(STATE, json.dumps({"sig": sig}))
    except Exception as e:
        B.log_error("protocol_guard.save_state", e)


AGENTS_STATE = os.path.join(B.STATE, "agent_rules.json")
AGENTS_DIR = os.path.expanduser("~/.claude/agents")


def touched_agents(data):
    """Was an agent definition just edited? By mtime, like the protocol check."""
    try:
        if not os.path.isdir(AGENTS_DIR):
            return False
        newest = max((os.path.getmtime(os.path.join(AGENTS_DIR, f))
                      for f in os.listdir(AGENTS_DIR) if f.endswith(".md")), default=0)
        return B.now() - newest <= FRESH_SECONDS
    except Exception:
        return False


def warn_agent_rules():
    """Speak the moment an agent definition loses a rule a subagent cannot learn
    elsewhere. The harness catches this too, but a whole session can pass between
    harness runs, and in that window every run of that agent is already wrong."""
    missing = B.agents_missing_rules()
    sig = ";".join("%s:%s" % (a, ",".join(r)) for a, r in missing)
    try:
        prev = json.load(open(AGENTS_STATE)).get("sig")
    except Exception:
        prev = None
    if sig == prev:
        return None
    try:
        os.makedirs(B.STATE, exist_ok=True)
        B.atomic_write(AGENTS_STATE, json.dumps({"sig": sig}))
    except Exception:
        pass
    if not missing:
        return None
    return ("Brain: %d agent definition(s) no longer carry a rule a subagent cannot "
            "learn any other way (there is no SubagentStart hook, so the definition is "
            "all it reads): %s"
            % (len(missing),
               "; ".join("%s lacks %s" % (a, ", ".join(r)) for a, r in missing[:3])))


@B.heartbeat("protocol-guard")
@B.fail_open
def main():
    data = B.read_hook_input()
    if not B.enabled():
        B.emit("PostToolUse")

    if touched_agents(data):
        m = warn_agent_rules()
        if m:
            print(json.dumps({"systemMessage": m}, ensure_ascii=False))
            sys.exit(0)

    if not touched_protocol(data):
        B.emit("PostToolUse")

    con = B.db()
    try:
        import compass
        verdict = PB.assess(compass.build_sections(con))
    finally:
        con.close()

    sig = signature(verdict)
    if load_state().get("sig") == sig:
        B.emit("PostToolUse")                 # already warned, do not insist

    msg = None
    if verdict["status"] == "OVER":
        msg = ("Brain: the startup block is over its cap (%d/%d tokens). "
               "Nothing is cut, but the cap should go up. %s"
               % (verdict["total"], verdict["max"], PB.advice(verdict)))
    elif verdict["status"] == "WARN":
        msg = ("Brain: startup is at %.0f%% of budget (%d/%d tokens). %s"
               % (100 * verdict["ratio"], verdict["total"], verdict["max"],
                  PB.advice(verdict)))
    elif verdict["fat_lines"]:
        n, line = verdict["fat_lines"][0]
        msg = ("Brain: %d-token bullet in the protocol (per-line cap: %d). "
               "Keep the rule in the bullet and the detail in its note — \"%s…\""
               % (n, PB.MAX_LINE_TOKENS, line[2:70]))

    save_state(sig)
    B.emit("PostToolUse", system_message=msg)


if __name__ == "__main__":
    main()
