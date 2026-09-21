#!/usr/bin/env python3
"""Tests for the Brain health notice compass.py adds at SessionStart.

BRAIN_STATE, BRAIN_VAULT and HOME point at temporary directories before compass and brainlib are
imported, and BRAIN_OFFLINE is set. compass also runs once as a real SessionStart hook in a
subprocess with the same variables. The guardian state it reads is written here. Nothing reaches
the real Brain state, the real vault, ~/.claude, KeePass or the network. Run standalone:

    python3 _bin/compass_health_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

ROOT = tempfile.mkdtemp(prefix="brain-compass-health-")
PATHS = {n: os.path.join(ROOT, n) for n in ("home", "state", "vault")}
for _p in PATHS.values():
    os.makedirs(_p)
ENV = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": PATHS["home"], "TMPDIR": ROOT,
       "BRAIN_STATE": PATHS["state"], "BRAIN_VAULT": PATHS["vault"], "BRAIN_OFFLINE": "1",
       "PYTHONDONTWRITEBYTECODE": "1", "GIT_CEILING_DIRECTORIES": ROOT, "BRAIN_MACHINE_KEY": "test-box-12345678"}
os.environ.update({k: ENV[k] for k in ("HOME", "BRAIN_STATE", "BRAIN_VAULT", "BRAIN_OFFLINE", "BRAIN_MACHINE_KEY")})
sys.path.insert(0, HERE)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


OPEN = {"hooks:not-firing": {"first_seen": "2026-09-15T10:00:00", "severity": "fail",
                             "summary": "2 active Claude Code session(s) fired no Brain hook in the last 30 min"}}


def write_state(active=None, raised=None):
    for name in ("guardian-state.json", "guardian-raised.json"):
        path = os.path.join(PATHS["state"], name)
        if os.path.exists(path):
            os.remove(path)
    if active is not None:
        with open(os.path.join(PATHS["state"], "guardian-state.json"), "w") as fh:
            json.dump({"alerts": {"active": active, "last_digest": None}}, fh)
    if raised is not None:
        with open(os.path.join(PATHS["state"], "guardian-raised.json"), "w") as fh:
            json.dump(raised, fh)


def run_compass(sid):
    payload = {"session_id": sid, "hook_event_name": "SessionStart", "cwd": PATHS["vault"], "source": "startup"}
    p = subprocess.run([sys.executable, os.path.join(HERE, "compass.py")], input=json.dumps(payload), env=ENV,
                       capture_output=True, text=True, timeout=60)
    try:
        out = json.loads(p.stdout) if p.stdout.strip().startswith("{") else {}
    except ValueError:
        out = {}
    return p, out, (out.get("hookSpecificOutput") or {}).get("additionalContext") or ""


def main():
    try:
        import brainlib as B
        import compass as C
        import protocol_budget as PB
        C.health_section
    except Exception as exc:
        check("compass imports with health_section", False, "%s: %s" % (type(exc).__name__, exc))
        return finish()

    check("brainlib and compass see the temporary state and vault, not the real ones",
          B.VAULT == PATHS["vault"] and B.STATE == PATHS["state"], (B.VAULT, B.STATE))

    write_state()
    check("with no guardian state there is no health section", C.health_section(PATHS["state"]) is None)
    write_state(active={}, raised={})
    check("a healthy guardian state adds nothing", C.health_section(PATHS["state"]) is None)

    write_state(active=OPEN)
    sec = C.health_section(PATHS["state"])
    text = sec[1] if sec else ""
    check("an open finding gives a health section", sec is not None and sec[0] == "health", sec)
    check("it names the problem in one line with its severity",
          "- [fail] 2 active Claude Code session(s) fired no Brain hook" in text, text)
    check("and the command to inspect it", "python3 ~/Brain/_bin/guardian.py status" in text, text)
    check("the default state directory is the guardian's (BRAIN_STATE here)",
          (C.health_section() or ("", ""))[1] == text, C.health_section())

    write_state(active=OPEN, raised={"bridge:stale": {"severity": "warn", "summary": "browser bridge stale", "at": "x"},
                                     "hooks:not-firing": {"severity": "fail", "summary": "dup", "at": "x"}})
    text = (C.health_section(PATHS["state"]) or ("", ""))[1]
    check("raised alerts are listed too, each key once",
          "browser bridge stale" in text and text.count("fired no Brain hook") == 1 and "dup" not in text, text)

    many = {"k%02d" % i: {"severity": "warn", "summary": "problem number %d " % i + "x" * 300} for i in range(20)}
    write_state(active=many)
    text = (C.health_section(PATHS["state"]) or ("", ""))[1]
    items = [line for line in text.splitlines() if line.startswith("- [")]
    check("a long list is cut to a few lines and says how many more", len(items) <= 5 and "15 more" in text, text)
    check("every line stays short", text and all(len(line) <= 140 for line in text.splitlines()),
          [len(line) for line in text.splitlines()])
    check("the whole notice stays a small part of the startup budget", B.est_tokens(text) <= 200, B.est_tokens(text))

    with open(os.path.join(PATHS["state"], "guardian-state.json"), "w") as fh:
        fh.write("{not json")
    check("an unreadable guardian state adds nothing and raises nothing", C.health_section(PATHS["state"]) is None)

    write_state(active=OPEN)
    con = B.db()
    try:
        secs = C.build_sections(con, "aaaa1111", PATHS["vault"])
        plain = C.build_sections(con)
    finally:
        con.close()
    check("a session's startup block carries the health section", "health" in [s[0] for s in secs],
          [s[0] for s in secs])
    check("and the startup budget measures it", "health" in [s[0] for s in PB.assess(secs)["sections"]])
    check("the budget report, which has no session, does not", "health" not in [s[0] for s in plain])
    names = [s[0] for s in secs]
    check("the startup block carries the This machine section right after the header",
          names[:2] == ["header", "machine"], names)
    machine = dict((s[0], s[1]) for s in secs).get("machine", "")
    check("it names this machine by its key", "## This machine" in machine and "test-box-12345678" in machine, machine)
    check("the budget measures it, and the budget report sees it too",
          "machine" in [s[0] for s in PB.assess(secs)["sections"]] and "machine" in [s[0] for s in plain])
    check("the section stays a small part of the startup budget", B.est_tokens(machine) <= 250, B.est_tokens(machine))

    write_state(active=OPEN)
    p, out, ctx = run_compass("aaaa1111-0000-4000-8000-000000000001")
    check("compass, run as the SessionStart hook, puts the health block in the context",
          p.returncode == 0 and "## Brain health" in ctx and "fired no Brain hook" in ctx,
          (p.returncode, p.stdout[:300], p.stderr[-300:]))
    check("and the This machine block, with the forced key", "## This machine" in ctx and "test-box-12345678" in ctx,
          ctx[:400])
    check("and tells the user in its message, with the command",
          "guardian.py status" in (out.get("systemMessage") or ""), out.get("systemMessage"))
    write_state(active={}, raised={})
    p, out, ctx = run_compass("bbbb2222-0000-4000-8000-000000000002")
    check("a healthy guardian adds neither",
          p.returncode == 0 and ctx and "Brain health" not in ctx and "guardian.py status" not in (out.get("systemMessage") or ""),
          (p.returncode, out))
    return finish()


def finish():
    shutil.rmtree(ROOT, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
