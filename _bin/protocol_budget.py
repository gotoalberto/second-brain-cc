#!/usr/bin/env python3
"""Startup context budget (T0).

Single source of truth for the size of the block `compass.py` injects on every
SessionStart, and of whether that block fits. Three places use it:

  - compass.py        to warn the user when the block runs out of headroom
  - protocol_guard.py to warn AT THE MOMENT the protocol is fattened
  - doctor.py         to show the headroom in the health report

Why it exists: compass used to trim to fit, first silently and line by line, later by
whole sections. Either way the agent lost context (`## Active projects`) to save tokens
that cost next to nothing. Since 2026-09-10 nothing is trimmed: the cap only warns, and
when it is reached the cap goes up.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

# Cap for the whole startup block. It is an ALARM, never a trim: compass always injects
# the whole block, and going over only warns. The rule: raise it
# whenever it is needed, and never cut context or lose effectiveness to stay under it.
# It is cheap to raise (injected once per session and rides in the prompt cache). Before
# raising, check the two cheap levers: not duplicating what the harness already injects,
# and keeping bullets thin (MAX_LINE_TOKENS).
MAX_TOKENS = 1600   # 1400 until 2026-09-10: at 96% any live session warning tipped it over

# Past this % of the cap it warns, even while it still fits.
WARN_RATIO = 0.85

# Per-bullet cap for the protocol. A rule longer than this is almost always a rule with
# the detail inside it: the detail belongs in the note, the bullet keeps
# with what must be known without opening anything.
MAX_LINE_TOKENS = 60

PROTOCOL = os.path.join(B.VAULT, "90-Meta", "PROTOCOL-COMPACT.md")


def protocol_text():
    try:
        with open(PROTOCOL, errors="replace") as fh:
            return fh.read().strip()
    except Exception:
        return ""


def fat_lines(text=None):
    """Protocol bullets that exceed the per-line cap."""
    if text is None:
        text = protocol_text()
    out = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        n = B.est_tokens(stripped)
        if n > MAX_LINE_TOKENS:
            out.append((n, stripped))
    out.sort(reverse=True)
    return out


def assess(sections):
    """sections: list of (name, text, priority). Returns the verdict; nobody trims on it."""
    sized = [(name, text, prio, B.est_tokens(text)) for name, text, prio in sections]
    total = sum(s[3] for s in sized)
    if total > MAX_TOKENS:
        status = "OVER"
    elif total > MAX_TOKENS * WARN_RATIO:
        status = "WARN"
    else:
        status = "OK"
    return {
        "sections": sized,
        "total": total,
        "max": MAX_TOKENS,
        "ratio": total / float(MAX_TOKENS) if MAX_TOKENS else 0.0,
        "status": status,
        "fat_lines": fat_lines(),
    }


def advice(verdict):
    """What to do, in one line, depending on what happened. Without this the warning is noise."""
    if verdict["fat_lines"]:
        n, line = verdict["fat_lines"][0]
        return ("slim the %d-token bullet (\"%s…\"): keep the rule in the bullet "
                "and move the detail to its note" % (n, line[2:60]))
    if verdict["status"] == "OVER":
        return ("over the cap: raise MAX_TOKENS in _bin/protocol_budget.py "
                "(never cut a section to fit)")
    return "little headroom left: raise MAX_TOKENS when the next rule needs it"



def subagent_report():
    """What a SUBAGENT receives, which is a different surface from the session's.

    This tool measured only `PROTOCOL-COMPACT.md` — the block `compass.py` injects at
    SessionStart. That hook does not fire for subagents, so the number above says nothing
    at all about what a subagent knows: its definition is the whole of its context. An
    instrument that reports one surface and is read as covering both is how the language
    rule ended up missing from all six agents while this said OK.
    """
    d = os.path.expanduser("~/.claude/agents")
    if not os.path.isdir(d):
        return []
    out = []
    for f in sorted(os.listdir(d)):
        if not f.endswith(".md"):
            continue
        try:
            text = open(os.path.join(d, f), errors="replace").read()
        except OSError:
            continue
        out.append((f[:-3], B.est_tokens(text)))
    return out

def _cli():
    # Reproduces compass's real block so the report does not lie.
    import compass
    con = B.db()
    try:
        sections = compass.build_sections(con)
    finally:
        con.close()
    v = assess(sections)
    print("Startup budget (T0)")
    print("  cap        : %d tokens   (warns from %d)"
          % (v["max"], int(v["max"] * WARN_RATIO)))
    print("  used       : %d tokens   (%.0f%%)   -> %s"
          % (v["total"], 100 * v["ratio"], v["status"]))
    print("  headroom   : %d tokens" % (v["max"] - v["total"]))
    print("  sections   :")
    for name, _t, prio, n in sorted(v["sections"], key=lambda s: -s[3]):
        print("    %-14s %5d tokens   priority %d" % (name, n, prio))
    if v["fat_lines"]:
        print("  bullets over %d tokens:" % MAX_LINE_TOKENS)
        for n, line in v["fat_lines"]:
            print("    %4d  %s…" % (n, line[2:88]))
    if v["status"] != "OK" or v["fat_lines"]:
        print("\n  -> %s" % advice(v))

    # The other surface. Numbered separately because it is NOT part of the T0 budget:
    # a subagent never receives the block above.
    subs = subagent_report()
    if subs:
        missing = dict(B.agents_missing_rules())
        print("\nWhat a SUBAGENT receives (T0 does not reach it: no SubagentStart hook)")
        print("  its definition is the whole of its context, so a rule absent from it")
        print("  is a rule that agent cannot follow.")
        for name, n in sorted(subs, key=lambda x: -x[1]):
            flag = "  <== missing: %s" % ", ".join(missing[name]) if name in missing else ""
            print("    %-16s %5d tokens%s" % (name, n, flag))
        if missing:
            print("  -> paste the rule into the definition; nothing else reaches it")
    return {"OK": 0, "WARN": 1, "OVER": 2}[v["status"]] if not v["fat_lines"] else 1


if __name__ == "__main__":
    sys.exit(_cli())
