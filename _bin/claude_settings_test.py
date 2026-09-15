#!/usr/bin/env python3
"""Tests for claude_settings.py: recommended Claude Code settings, merged only with consent.

The merge is tested as a pure function, then the command runs as a subprocess against a scratch
HOME, so the real ~/.claude/settings.json is never read or written. Run standalone:

    python3 _bin/claude_settings_test.py
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPO = os.path.dirname(HERE)
CLI = os.path.join(HERE, "claude_settings.py")
EXAMPLE = os.path.join(REPO, "integrations", "claude-code", "settings.example.json")

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


EX = {
    "_comment": "hooks are installed by the guardian",
    "permissions": {"defaultMode": "acceptEdits",
                    "allow": ["Bash(git status*)", "Bash(python3 __VAULT__/_bin/query.py *)"]},
    "skipWorkflowUsageWarning": True,
    "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "rm -rf /"}]}]},
}


def test_merge(CS):
    print("\n== merge ==")
    user = {"permissions": {"defaultMode": "plan", "allow": ["Bash(ls *)", "Bash(git status*)"]}, "theme": "dark",
            "hooks": {"Stop": []}}
    merged, changes = CS.merge(user, EX, "/srv/vault")
    check("a value the user already set is never changed", merged["permissions"]["defaultMode"] == "plan", merged)
    check("allow entries the user lacks are appended once, after theirs, with the vault path filled in",
          merged["permissions"]["allow"] == ["Bash(ls *)", "Bash(git status*)", "Bash(python3 /srv/vault/_bin/query.py *)"],
          merged["permissions"]["allow"])
    check("a key the user has not set is added", merged.get("skipWorkflowUsageWarning") is True and merged["theme"] == "dark")
    check("hooks and comment keys are never merged", merged["hooks"] == {"Stop": []} and "_comment" not in merged, merged)
    check("each change is listed", len(changes) == 2 and any("query.py" in c for c in changes), changes)
    check("the user's dict is not modified in place", user["permissions"]["allow"] == ["Bash(ls *)", "Bash(git status*)"])
    again, changes2 = CS.merge(merged, EX, "/srv/vault")
    check("merging again changes nothing", again == merged and changes2 == [], changes2)
    odd, _ = CS.merge({"permissions": "strict"}, EX, "/v")
    check("a permissions value that is not an object is left alone", odd["permissions"] == "strict", odd)
    fresh, _ = CS.merge({}, EX, "/v")
    check("an empty settings file gets the whole recommendation",
          fresh["permissions"]["defaultMode"] == "acceptEdits" and len(fresh["permissions"]["allow"]) == 2, fresh)


def test_example():
    print("\n== the shipped example ==")
    data = json.load(open(EXAMPLE))
    text = open(EXAMPLE).read()
    check("settings.example.json parses and carries permissions", isinstance(data.get("permissions"), dict), data)
    check("it names no absolute path except through __VAULT__",
          "/Users/" not in text and "/home/" not in text and "__VAULT__" in text, text)
    check("it carries no hooks: the guardian installs those", "hooks" not in data)


def test_cli():
    print("\n== claude_settings.py ==")
    root = tempfile.mkdtemp(prefix="claude-settings-")
    try:
        home = os.path.join(root, "home")
        settings = os.path.join(home, ".claude", "settings.json")
        os.makedirs(os.path.dirname(settings))
        user = {"permissions": {"defaultMode": "plan", "allow": ["Bash(ls *)"]}, "hooks": {"Stop": []}}
        with open(settings, "w") as fh:
            json.dump(user, fh)
        env = {k: v for k, v in os.environ.items() if not k.startswith("BRAIN_")}
        env.update(HOME=home, BRAIN_VAULT=REPO, BRAIN_STATE=os.path.join(root, "state"))

        def run(*args):
            p = subprocess.run([sys.executable, CLI] + list(args), env=env, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=60)
            return p.returncode, p.stdout, p.stderr

        rc, out, err = run("show")
        check("show lists what a merge would add and writes nothing",
              rc == 0 and "permissions.allow" in out and json.load(open(settings)) == user, (rc, out, err))
        rc, out, err = run("merge")
        check("merge without a terminal and without --yes writes nothing and says how",
              rc == 0 and json.load(open(settings)) == user and "--yes" in out, (rc, out, err))
        rc, out, err = run("merge", "--yes")
        after = json.load(open(settings))
        backups = glob.glob(settings + ".bak-*")
        check("merge --yes writes the additions, keeping the user's values and hooks",
              rc == 0 and after["permissions"]["defaultMode"] == "plan" and "Bash(ls *)" in after["permissions"]["allow"]
              and after["hooks"] == {"Stop": []} and len(after["permissions"]["allow"]) > 1, (rc, out, err, after))
        check("and backs the old file up first", len(backups) == 1 and json.load(open(backups[0])) == user, backups)
        check("the vault path is filled in", not any("__VAULT__" in a for a in after["permissions"]["allow"]), after)
        rc, out, err = run("merge", "--yes")
        check("a second merge has nothing to add", rc == 0 and "nothing to add" in out and len(glob.glob(settings + ".bak-*")) == 1,
              (out, glob.glob(settings + ".bak-*")))
        with open(settings, "w") as fh:
            fh.write("{broken")
        rc, out, err = run("merge", "--yes")
        check("an unreadable settings file is refused, exit 1, and left as it was",
              rc == 1 and open(settings).read() == "{broken", (rc, err))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    try:
        import claude_settings as CS
    except Exception as exc:
        check("claude_settings imports", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (lambda: test_merge(CS), test_example, test_cli):
            try:
                t()
            except Exception as exc:
                import traceback
                traceback.print_exc()
                check("a test ran to the end", False, "%s: %s" % (type(exc).__name__, exc))
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
