#!/usr/bin/env python3
"""Startup context budget (T0).

Single source of truth for the size of the block `compass.py` injects on every
SessionStart, and of whether that block fits. Three places use it:

  - compass.py        to trim by section and warn when it trims
  - protocol_guard.py to warn AT THE MOMENT the protocol is fattened
  - doctor.py         to show the headroom in the health report

Why it exists: compass's trimming was silent and line-by-line, so as the protocol grew,
whole sections vanished (`## Active projects`) with nobody the wiser. A context
that trims itself without saying so is worse than one that does not fit: it looks
complete.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

# Cap for the whole startup block. Raising it is cheap (injected once
# per session and rides in the prompt cache), but it is not the first lever: before it
# comes not duplicating what the harness already injects, and keeping lines thin.
MAX_TOKENS = 1400

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
    """sections: list of (name, text, priority). High priority = it stays.

    Returns the verdict without deciding anything: compass is the one that trims.
    """
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
        return ("the block does not fit: drop a low-priority section or raise "
                "MAX_TOKENS in _bin/protocol_budget.py")
    return "no headroom left: the next rule will force a trim"


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
    return {"OK": 0, "WARN": 1, "OVER": 2}[v["status"]] if not v["fat_lines"] else 1


if __name__ == "__main__":
    sys.exit(_cli())
