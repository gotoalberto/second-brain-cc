#!/usr/bin/env python3
"""Tests for model_fallback.py: the model a routine runs on, and the repair attempt on a stronger one.

Pure functions only: no CLI, no routine file on disk, no network. Run standalone:

    python3 _bin/model_fallback_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import model_fallback as M  # noqa: E402

ok, fail = [], []
# The tier names come from the module, so the tests follow its MODELS tuple.
CHEAP, STRONG = M.MODELS[0], M.DEFAULT_FALLBACK

ROUTINE = """---
id: class-reminders
model: %s
agent_args: ["--allowedTools", "Read,Bash(python3 ~/Brain/_bin/query.py:*)"]
---

Email tomorrow's class list to the front desk.
""" % CHEAP


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail and not cond else ""))


def test_routine_model():
    print("\n== the model of the first attempt and of the repair ==")
    check("a routine's model, with the stronger default fallback",
          M.routine_model(ROUTINE) == (CHEAP, M.DEFAULT_FALLBACK), M.routine_model(ROUTINE))
    check("no model means the template's, still with a fallback",
          M.routine_model("---\nid: y\n---\nbody") == (None, M.DEFAULT_FALLBACK))
    check("a template that pins the fallback model already gets no second attempt on it",
          M.routine_model("---\nid: y\n---\nbody", default=M.DEFAULT_FALLBACK) == (None, None))
    check("a routine on the strongest model has no fallback",
          M.routine_model("---\nmodel: %s\n---\nb" % M.DEFAULT_FALLBACK) == (M.DEFAULT_FALLBACK, None))
    check("the model may come from the routine's own agent_args",
          M.routine_model("---\nid: z\n---\nb", ("--model", CHEAP)) == (CHEAP, M.DEFAULT_FALLBACK))
    check("and from --model=<name>", M.routine_model("---\nid: z\n---\nb", ("--model=" + CHEAP,))[0] == CHEAP)
    check("fallback_model: none turns the repair off",
          M.routine_model("---\nmodel: %s\nfallback_model: none\n---\nb" % CHEAP) == (CHEAP, None))
    check("an unknown model name is ignored", M.routine_model("---\nmodel: gpt-x\n---\nb")[0] is None)
    check("model: in the body does not count",
          M.routine_model("---\nid: y\n---\nmodel: %s\n" % CHEAP)[0] is None)


def test_template_model():
    print("\n== the model the agent command template pins ==")
    check("a template with --model <name>",
          M.template_model("~/.local/bin/claude -p {prompt} --model " + CHEAP) == CHEAP)
    check("a template with --model=<name>", M.template_model("claude -p {prompt} --model=" + CHEAP) == CHEAP)
    check("a template without one", M.template_model("~/.local/bin/claude -p {prompt}") is None)
    check("no template at all", M.template_model(None) is None)


def test_with_model():
    print("\n== --model on the command line ==")
    check("an earlier --model in the args is replaced",
          M.with_model(("--model", STRONG, "-x"), CHEAP) == ("-x", "--model", CHEAP),
          M.with_model(("--model", STRONG, "-x"), CHEAP))
    check("so is --model=<name>", M.with_model(("--model=" + STRONG,), CHEAP) == ("--model", CHEAP))
    check("no model leaves the args alone, without --model", M.with_model(("-x",), None) == ("-x",))


def test_eligible():
    print("\n== which failures get the repair attempt ==")
    check("an unrecognised failure does", M.fallback_eligible("unknown", 1))
    check("a broken success contract does", M.fallback_eligible("contract_breach", 65))
    check("a timeout does", M.fallback_eligible("timeout", 124))
    for kind in ("auth_invalid", "usage_limit", "credit_exhausted", "network", "cli_missing", "keepass_locked",
                 "keepass_unavailable", "token_malformed", "config", "no_usable_token"):
        check("%s does not: a better model cannot fix it" % kind, not M.fallback_eligible(kind, 1))
    check("a success does not", not M.fallback_eligible("ok", 0))


def test_repair_args():
    print("\n== the repair attempt's arguments ==")
    a = M.repair_args(("--allowedTools", "Read"), "/scratch/run-1")
    check("the repair tools join the routine's allowlist", "Edit" in a[1] and "install_plugin.py sync" in a[1]
          and a[1].startswith("Read,"), a)
    check("the failed attempt's scratch directory is readable", a[-2:] == ("--add-dir", "/scratch/run-1"), a)
    b = M.repair_args(("--allowed-tools", "Read,Edit"), None)
    check("a tool already allowed is not added twice", b[1].count("Edit") == 1, b)
    check("no scratch directory, no --add-dir", "--add-dir" not in b, b)
    c = M.repair_args(("--permission-mode", "acceptEdits"), None)
    check("a routine with no allowlist gets one with the repair tools",
          c[-2] == "--allowedTools" and "Write" in c[-1], c)


def test_repair_text():
    print("\n== the repair prompt ==")
    t = M.repair_text(ROUTINE, "class-reminders", CHEAP, STRONG, "exit 1",
                      '{"result": "ROUTINE_FAILED: the class list was empty"}', "trace line", "/scratch/run-1")
    check("the front matter is kept first", t.startswith("---\nid: class-reminders\n"), t[:60])
    check("it opens with the repair header", "REPAIR RUN ON " + STRONG.upper() in t, t[:400])
    check("it quotes the failed attempt's last answer and stderr",
          "ROUTINE_FAILED: the class list was empty" in t and "trace line" in t)
    check("it points at the kept scratch directory", "/scratch/run-1" in t)
    check("it forbids repeating a side effect", "Never repeat a side effect" in t)
    check("it names the fix log", M.FIX_LOG in t)
    check("and the routine's body follows unchanged",
          t.rstrip().endswith("Email tomorrow's class list to the front desk."), t[-200:])
    long_out = "x" * 10000
    t2 = M.repair_text("no front matter\n", "r", CHEAP, STRONG, "", long_out, "", None)
    check("a long answer is cut to its tail", len(t2) < 8000 and "[...]" in t2, len(t2))
    check("a missing scratch directory is said so", "was not kept" in t2)
    check("a routine without front matter still gets the preamble", t2.startswith("## REPAIR RUN"), t2[:40])


if __name__ == "__main__":
    for t in (test_routine_model, test_template_model, test_with_model, test_eligible, test_repair_args,
              test_repair_text):
        try:
            t()
        except Exception as exc:
            check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    sys.exit(1 if fail else 0)
