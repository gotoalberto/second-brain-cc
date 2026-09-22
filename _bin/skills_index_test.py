#!/usr/bin/env python3
"""Tests for skills_index: the instruction excerpt, its fence, stale machine indexes and the
machine key line.

The excerpt was `body.strip()[:1200]`, a hard character slice: every note in 40-Skills/ ended
mid-sentence, sometimes mid-word, with a dangling `**`. These pin what it must do instead:

  - a body that fits is kept whole, with no marker;
  - a long body is cut at a line boundary and says it was cut;
  - a fence inside the excerpt cannot close the block the excerpt is shown in.

Only temporary directories are written. Run standalone:

    python3 _bin/skills_index_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail and not cond else ""))


def main():
    import skills_index as S

    print("== the instruction excerpt ==")
    short = "# Title\n\nOne line.\n"
    check("a body that fits is kept whole", S.excerpt(short) == short.strip(), S.excerpt(short))

    lines = ["%d. **Rule number %d.** It says something long enough to matter here." % (i, i) for i in range(60)]
    body = "\n".join(lines)
    ex = S.excerpt(body)
    kept = ex.split("\n")[:-1]
    check("a long body stays within the limit", len(ex) <= S.EXCERPT_CHARS + len(S.CUT_MARK) + 1, len(ex))
    check("it is cut at a line boundary: every kept line is a whole line of the body",
          kept and all(l in lines for l in kept), kept[-1:] if kept else ex)
    check("and it says it was cut", ex.endswith(S.CUT_MARK), ex[-60:])
    check("no `**` is left open on the last kept line", kept and kept[-1].count("**") % 2 == 0, kept[-1:])

    one = "x" * 5000
    ex = S.excerpt(one)
    check("a single line longer than the limit is cut at a word or at the limit, and marked",
          ex.endswith(S.CUT_MARK) and len(ex) <= S.EXCERPT_CHARS + len(S.CUT_MARK) + 1, len(ex))

    fenced = "Run it:\n```bash\npython3 x.py\n```\nThen stop.\n"
    check("the fence around an excerpt is longer than any backtick run inside it",
          S.fence_for(fenced) == "````", S.fence_for(fenced))
    check("plain text gets the ordinary fence", S.fence_for("no code here") == "```")

    import datetime as dt
    import tempfile
    import brainlib as B
    saved_vault = B.VAULT
    with tempfile.TemporaryDirectory() as tmp:
        B.VAULT = tmp
        folder = os.path.join(tmp, "40-Skills")
        os.makedirs(folder)

        print("== stale machine indexes ==")

        def index(name, updated, provenance="skills_index.py", status="active"):
            path = os.path.join(folder, name)
            open(path, "w").write("---\nid: x\nstatus: %s\nprovenance: %s\nupdated: %s\n---\n\n"
                                  "Skills installed on somewhere.\n" % (status, provenance, updated))
            return path

        today = dt.date(2026, 9, 17)
        old = index("INDEX-old-laptop.md", "2026-09-10")
        fresh = index("INDEX-workstation.md", "2026-09-17")
        hand = index("INDEX-hand.md", "2026-01-01", provenance="human")
        mine = index(os.path.basename(S.index_path()), "2026-01-01")
        retired = S.retire_stale_indexes(today=today)
        check("an index untouched for a week is superseded", retired == ["INDEX-old-laptop.md"], retired)
        check("its frontmatter says superseded", "\nstatus: superseded\n" in open(old).read())
        check("and its body says why", "**Superseded** on 2026-09-17" in open(old).read())
        check("a fresh index is left active", "status: active" in open(fresh).read())
        check("a hand-written index is never touched", "status: active" in open(hand).read())
        check("this machine's own index is never retired", "status: active" in open(mine).read())
        check("running it again changes nothing", S.retire_stale_indexes(today=today) == [])

        print("== the index names the machine by its key ==")
        saved_key = os.environ.get("BRAIN_MACHINE_KEY")
        os.environ["BRAIN_MACHINE_KEY"] = "workstation-0f0f0f0f"
        try:
            S.write_index([{"name": "demo", "scope": "user", "desc": "Does a thing.", "when": ""}])
            text = open(S.index_path()).read()
        finally:
            if saved_key is None:
                os.environ.pop("BRAIN_MACHINE_KEY", None)
            else:
                os.environ["BRAIN_MACHINE_KEY"] = saved_key
        check("the frontmatter carries machine_key", "\nmachine_key: workstation-0f0f0f0f\n" in text, text[:400])
        check("and the skill line is separated by a colon, not a dash",
              "- `/demo` (user): Does a thing." in text and " — " not in text, text)

        print("== a note's excerpt is fenced safely ==")
        S.write_note({"name": "demo", "scope": "user", "path": "/x/SKILL.md", "desc": "d", "when": "",
                      "tools": "", "ctx": "", "agent": "", "model": "", "body": S.excerpt(fenced)})
        note = open(os.path.join(folder, "demo.md")).read()
        check("an excerpt with a code block inside is wrapped in a longer fence",
              "````\nRun it:" in note and note.count("````") == 2, note)
    B.VAULT = saved_vault

    print()
    print("RESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
