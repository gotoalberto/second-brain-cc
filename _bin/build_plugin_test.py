#!/usr/bin/env python3
"""Tests for build_plugin.py after its direction was reversed.

It used to copy ~/.claude's agents, skills and settings.json hooks into the vault,
unconditionally. Now the vault is canonical: skills and agents go through the three-way
sync (install_plugin.py) with backups, and hooks.json is generated from 90-Meta/events.json,
never copied from a live settings.json. Runs as a subprocess against a temporary vault,
HOME and BRAIN_STATE. Run standalone:

    python3 _bin/build_plugin_test.py
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

ok, fail = [], []
TMP = []

REGISTRY = {"version": 1, "events": [
    {"id": "sync", "description": "sync", "handler": "vault_sync",
     "triggers": [{"kind": "claude-hook", "event": "Stop", "command": "vault_sync.py --hook", "async": True}]}]}


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    return path


def read(path):
    with open(path) as fh:
        return fh.read()


def setup(with_registry=True):
    root = tempfile.mkdtemp(prefix="build-plugin-")
    TMP.append(root)
    vault, home, state = os.path.join(root, "vault"), os.path.join(root, "home"), os.path.join(root, "state")
    plugin = os.path.join(vault, "integrations", "claude-code", "plugin", "brain")
    claude = os.path.join(home, ".claude")
    write(os.path.join(plugin, "skills", "edited-live", "SKILL.md"), "vault wording\n")
    write(os.path.join(claude, "skills", "edited-live", "SKILL.md"), "live wording\n")
    write(os.path.join(plugin, "skills", "vault-only", "SKILL.md"), "from the vault\n")
    write(os.path.join(claude, "agents", "planner.md"), "planner\n")
    write(os.path.join(plugin, "hooks", "hooks.json"), '{"hooks": {"Stale": []}}')
    write(os.path.join(claude, "settings.json"), json.dumps({"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": "/usr/local/bin/someone-elses-hook"}]}]}}))
    if with_registry:
        write(os.path.join(vault, "90-Meta", "events.json"), json.dumps(REGISTRY))
    env = dict(os.environ, HOME=home, BRAIN_VAULT=vault, BRAIN_STATE=state)
    return vault, plugin, claude, state, env


def build(env):
    return subprocess.run([sys.executable, os.path.join(HERE, "build_plugin.py")], env=env,
                          capture_output=True, text=True, timeout=120)


def main():
    vault, plugin, claude, state, env = setup()
    p = build(env)
    check("build_plugin.py runs", p.returncode == 0, (p.returncode, p.stdout, p.stderr))
    hooks = read(os.path.join(plugin, "hooks", "hooks.json"))
    check("hooks.json is generated from 90-Meta/events.json",
          "vault_sync.py --hook" in hooks and "Stale" not in hooks, hooks)
    check("and never copied from the live settings.json", "someone-elses-hook" not in hooks, hooks)
    check("a live skill edit is back-ported into the vault",
          read(os.path.join(plugin, "skills", "edited-live", "SKILL.md")) == "live wording\n")
    backups = os.path.join(state, "plugin-backups")
    check("with the replaced vault copy backed up first",
          os.path.isdir(backups) and any(f.endswith(".tar.gz") and "edited-live" in f for f in os.listdir(backups)),
          os.listdir(backups) if os.path.isdir(backups) else None)
    check("a skill only the vault has is installed into ~/.claude (the vault is canonical)",
          read(os.path.join(claude, "skills", "vault-only", "SKILL.md")) == "from the vault\n")
    check("a live-only agent is added to the vault", read(os.path.join(plugin, "agents", "planner.md")) == "planner\n")

    mtime = os.path.getmtime(os.path.join(plugin, "hooks", "hooks.json"))
    time.sleep(0.05)
    build(env)
    check("a second run does not touch hooks.json (it must settle to be committed)",
          os.path.getmtime(os.path.join(plugin, "hooks", "hooks.json")) == mtime)

    vault2, plugin2, _, _, env2 = setup(with_registry=False)
    p = build(env2)
    check("with no event registry hooks.json is left as it was, not rebuilt from settings.json",
          p.returncode == 0 and read(os.path.join(plugin2, "hooks", "hooks.json")) == '{"hooks": {"Stale": []}}',
          (p.returncode, p.stdout, p.stderr))
    check("and it says why", "events.json" in (p.stdout + p.stderr), p.stdout + p.stderr)
    return finish()


def finish():
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
