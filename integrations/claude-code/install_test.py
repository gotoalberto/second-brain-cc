#!/usr/bin/env python3
"""Smoke test for integrations/claude-code/install.sh in a scratch HOME.

install.sh runs for real, with HOME and BRAIN_STATE pointed at a temporary directory and stdin
that is not a terminal: skills and agents land in the scratch ~/.claude with the vault path filled
in, the hooks are merged into its settings.json, recommended settings are shown but not merged, and
no scheduled job is installed. Run standalone:

    python3 integrations/claude-code/install_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
INSTALL = os.path.join(HERE, "install.sh")

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def main():
    root = tempfile.mkdtemp(prefix="claude-install-")
    try:
        home, state = os.path.join(root, "home"), os.path.join(root, "state")
        os.makedirs(home)
        # A scratch copy of the repository: install.sh writes generated files (the skills catalogue)
        # into the vault it is given, and a test must never write into the real tree.
        vault = os.path.join(root, "vault")
        shutil.copytree(REPO, vault, ignore=shutil.ignore_patterns(".git", "_index", "__pycache__", "*.pyc"))
        before = sorted(os.listdir(os.path.join(REPO, "40-Skills")))
        env = {k: v for k, v in os.environ.items() if not k.startswith("BRAIN_")}
        env.update(HOME=home, BRAIN_STATE=state, BRAIN_VAULT=vault)
        script = open(INSTALL, encoding="utf-8").read()
        schedulers = [w for w in ("launchctl", "systemctl", "crontab") if w in script]
        check("install.sh never talks to a scheduler (the first run owns scheduled jobs)", schedulers == [], schedulers)
        if schedulers:
            # Never execute a script that would reach the real launchd, systemd or cron from a test.
            print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
            return 1
        p = subprocess.run(["bash", INSTALL], env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=300)
        out = p.stdout + p.stderr
        check("install.sh exits 0", p.returncode == 0, out[-1500:])
        claude = os.path.join(home, ".claude")
        skills = os.path.join(claude, "skills")
        check("the vault's skills are installed into the scratch ~/.claude",
              os.path.isfile(os.path.join(skills, "recall", "SKILL.md")), os.listdir(claude) if os.path.isdir(claude) else None)
        leftovers = []
        for dp, _dns, fns in os.walk(claude):
            for fn in fns:
                try:
                    if "__VAULT__" in open(os.path.join(dp, fn), encoding="utf-8").read():
                        leftovers.append(os.path.join(dp, fn))
                except (UnicodeDecodeError, OSError):
                    pass
        check("no installed file still says __VAULT__", leftovers == [], leftovers)
        settings = os.path.join(claude, "settings.json")
        data = json.load(open(settings)) if os.path.isfile(settings) else {}
        commands = [h.get("command", "") for groups in data.get("hooks", {}).values() for g in groups for h in g.get("hooks", [])]
        check("the hooks are merged into settings.json and name this vault's scripts",
              any(os.path.join(vault, "_bin", "retrieve.py") in c for c in commands)
              and not any("brain-origin" in c for c in commands), commands[:4])
        check("recommended settings are shown but not merged without a terminal",
              "permissions" not in data and "claude_settings.py merge" in out, (sorted(data), out[-600:]))
        check("no scheduled job is installed by this integration",
              not os.path.exists(os.path.join(home, "Library", "LaunchAgents"))
              and not os.path.exists(os.path.join(home, ".config", "systemd")), out[-400:])
        check("it points at the first run for everything else", "first-run/setup.sh" in out, out[-400:])
        check("nothing was written into the real repository's tree",
              sorted(os.listdir(os.path.join(REPO, "40-Skills"))) == before, sorted(os.listdir(os.path.join(REPO, "40-Skills"))))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
