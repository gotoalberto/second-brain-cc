#!/usr/bin/env python3
"""Smoke test for bootstrap.sh, run against a scratch copy of the repository and a scratch HOME.

The script is checked first: it must not call a credential manager's CLI or a scheduler. Only then
is it run, with stdin that is not a terminal, so the first run it offers asks nothing. Run
standalone:

    python3 _bin/bootstrap_test.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def main():
    script_path = os.path.join(REPO, "bootstrap.sh")
    script = open(script_path, encoding="utf-8").read()
    reaches = [w for w in ("op account", "op signin", "1password", "launchctl", "systemctl", "crontab ")
               if w in script.lower()]
    check("bootstrap.sh never calls 1Password or a scheduler", reaches == [], reaches)
    check("it checks for keepassxc-cli and offers the first run",
          "keepassxc-cli" in script and "integrations/first-run/setup.sh" in script)
    if reaches:
        print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
        return 1

    root = tempfile.mkdtemp(prefix="bootstrap-")
    try:
        vault = os.path.join(root, "vault")
        shutil.copytree(REPO, vault, ignore=shutil.ignore_patterns(".git", "_index", "__pycache__", "*.pyc"))
        home, state = os.path.join(root, "home"), os.path.join(root, "state")
        os.makedirs(home)
        env = {k: v for k, v in os.environ.items() if not k.startswith("BRAIN_")}
        env.update(HOME=home, BRAIN_STATE=state, BRAIN_VAULT=vault)
        p = subprocess.run(["bash", os.path.join(vault, "bootstrap.sh")], env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=300)
        out = p.stdout + p.stderr
        check("bootstrap.sh exits 0 in a scratch HOME", p.returncode == 0, out[-1500:])
        check("it builds the search index in the vault", os.path.isdir(os.path.join(vault, "_index")), out[-400:])
        check("without a terminal it only says how to start the first run", "first-run/setup.sh" in out
              and not os.path.exists(os.path.join(state, "first-run.json")), out[-600:])
        check("it installs no scheduled job and touches no agent config",
              not os.path.exists(os.path.join(home, "Library", "LaunchAgents"))
              and not os.path.exists(os.path.join(home, ".claude")), sorted(os.listdir(home)))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
