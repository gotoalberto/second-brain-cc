#!/usr/bin/env python3
"""Tests for gen_instructions.py — AGENTS.md and CLAUDE.md, generated, never hand-edited.

Runs the generator as a subprocess against a temporary vault holding a fixture
90-Meta/events.json and PROTOCOL-COMPACT.md, with HOME temporary so the home-directory
AGENTS.md is provably untouched. Run standalone:

    python3 _bin/gen_instructions_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
GEN = os.path.join(HERE, "gen_instructions.py")

ok, fail = [], []
TMP = []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


REGISTRY = {"version": 1, "events": [
    {"id": "session-start", "description": "startup context", "handler": "compass",
     "triggers": [{"kind": "claude-hook", "event": "SessionStart", "command": "compass.py", "timeout": 8},
                  {"kind": "cli", "command": "brain session-start"},
                  {"kind": "mcp", "tool": "session_start"}]},
    {"id": "stop-memory-gate", "description": "blocks close without a saved note", "handler": "gate_memory",
     "triggers": [{"kind": "claude-hook", "event": "Stop", "command": "gate_memory.py", "timeout": 10}]},
    {"id": "sync", "description": "commit and push", "handler": "vault_sync",
     "triggers": [{"kind": "launchd", "label": "com.secondbrain.sync"},
                  {"kind": "file-watch", "action": "sync-debounce", "command": "vault_sync.py --hook"}]},
]}
PROTOCOL = "---\nid: protocol-compact\n---\n\n# Protocol\n\nSearch the vault before answering anything non-trivial.\n"


def setup():
    root = tempfile.mkdtemp(prefix="gen-instructions-")
    TMP.append(root)
    vault, home = os.path.join(root, "vault"), os.path.join(root, "home")
    os.makedirs(os.path.join(vault, "90-Meta"))
    os.makedirs(home)
    with open(os.path.join(vault, "90-Meta", "events.json"), "w") as fh:
        json.dump(REGISTRY, fh)
    with open(os.path.join(vault, "90-Meta", "PROTOCOL-COMPACT.md"), "w") as fh:
        fh.write(PROTOCOL)
    env = dict(os.environ, HOME=home, BRAIN_VAULT=vault)
    env.pop("BRAIN_STATE", None)
    return vault, home, env


def gen(env, *args):
    return subprocess.run([sys.executable, GEN] + list(args), env=env, capture_output=True, text=True, timeout=60)


def main():
    if not os.path.isfile(GEN):
        check("gen_instructions.py exists", False, GEN)
        return finish()
    from events_core import domain as D

    vault, home, env = setup()
    p = gen(env)
    agents = os.path.join(vault, "AGENTS.md")
    claude = os.path.join(vault, "CLAUDE.md")
    check("a run writes AGENTS.md and CLAUDE.md at the vault root",
          p.returncode == 0 and os.path.isfile(agents) and os.path.isfile(claude), (p.returncode, p.stdout, p.stderr))
    if not (os.path.isfile(agents) and os.path.isfile(claude)):
        return finish()
    cl = open(claude, "rb").read()
    check("CLAUDE.md is exactly the two-line pointer", cl == D.CLAUDE_MD_POINTER.encode("utf-8"), cl)
    check("and it is two lines", cl.count(b"\n") == 2 and cl.endswith(b"\n"))
    ag = open(agents, encoding="utf-8").read()
    check("AGENTS.md carries the protocol without its frontmatter",
          "Search the vault before answering anything non-trivial." in ag and "id: protocol-compact" not in ag, ag[:300])
    check("AGENTS.md is written for an agent with no adapter: the degraded-mode table is there",
          "Without an agent adapter" in ag and "`brain session-start`" in ag and "stop-memory-gate" in ag, ag)
    check("events that fire with no agent are shown as automatic", "file-watch, launchd" in ag, ag)
    check("AGENTS.md tells any agent to offer the first run on a machine that has not had one",
          "## First session on this machine" in ag and "first-run.json" in ag
          and "integrations/first-run/setup.sh" in ag and "first_run.py status" in ag, ag)
    check("and never to run it or answer its questions without the user",
          "Never run it without the user's yes" in ag, ag)
    check("the first-run block comes right after the protocol, before the events",
          ag.index("## Protocol") < ag.index("## First session on this machine") < ag.index("## Brain events"), ag)
    check("the home-directory AGENTS.md is not touched", not os.path.exists(os.path.join(home, "AGENTS.md")))

    before = (os.path.getmtime(agents), os.path.getmtime(claude))
    time.sleep(0.05)
    p = gen(env)
    check("a second run rewrites nothing",
          p.returncode == 0 and (os.path.getmtime(agents), os.path.getmtime(claude)) == before, p.stdout)
    p = gen(env, "--check")
    check("--check passes when both files are current", p.returncode == 0, (p.returncode, p.stdout))

    with open(claude, "a") as fh:
        fh.write("a hand edit\n")
    p = gen(env, "--check")
    check("--check fails on a hand-edited CLAUDE.md, naming it", p.returncode == 1 and "CLAUDE.md" in (p.stdout + p.stderr),
          (p.returncode, p.stdout, p.stderr))
    check("and writes nothing", open(claude).read().endswith("a hand edit\n"))
    gen(env)
    check("a normal run restores it", open(claude, "rb").read() == D.CLAUDE_MD_POINTER.encode("utf-8"))

    hooks_doc = os.path.join(vault, "90-Meta", "HOOKS-WITHOUT-CLAUDE.md")
    registry = D.load_registry(json.dumps(REGISTRY))
    check("a run writes 90-Meta/HOOKS-WITHOUT-CLAUDE.md from the registry, byte for byte",
          os.path.isfile(hooks_doc) and open(hooks_doc, encoding="utf-8").read() == D.render_hooks_without_claude(registry),
          hooks_doc)
    check("it lists brain hook for an event only Claude Code fires",
          os.path.isfile(hooks_doc) and "`brain hook stop-memory-gate`" in open(hooks_doc).read())
    if os.path.isfile(hooks_doc):
        before = os.path.getmtime(hooks_doc)
        time.sleep(0.05)
        gen(env)
        check("a run with nothing changed does not rewrite it", os.path.getmtime(hooks_doc) == before)
        with open(hooks_doc, "a") as fh:
            fh.write("a hand edit\n")
        p = gen(env, "--check")
        check("--check fails on a hand-edited HOOKS-WITHOUT-CLAUDE.md, naming it",
              p.returncode == 1 and "HOOKS-WITHOUT-CLAUDE.md" in (p.stdout + p.stderr), (p.returncode, p.stdout, p.stderr))
        gen(env)
        check("and a normal run restores it", open(hooks_doc, encoding="utf-8").read() == D.render_hooks_without_claude(registry))

    os.remove(os.path.join(vault, "90-Meta", "events.json"))
    p = gen(env)
    check("a missing registry is exit 2 with the reason", p.returncode == 2 and "events.json" in p.stderr,
          (p.returncode, p.stderr))
    return finish()


def finish():
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
