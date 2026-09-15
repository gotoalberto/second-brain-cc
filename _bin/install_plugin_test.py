#!/usr/bin/env python3
"""Tests for install_plugin.py — skills and agents: the vault is canonical, ~/.claude is a copy.

Three temporary roots stand in for the vault's plugin/brain, ~/.claude and the Brain state
directory; nothing else is read or written. Run standalone:

    python3 _bin/install_plugin_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok, fail = [], []
TMP = []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def tmpdir():
    d = tempfile.mkdtemp(prefix="install-plugin-")
    TMP.append(d)
    return d


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    return path


def read(path):
    with open(path) as fh:
        return fh.read()


def skill(root, name, body, script="print('hi')\n"):
    write(os.path.join(root, "skills", name, "SKILL.md"), "---\nname: %s\n---\n%s\n" % (name, body))
    write(os.path.join(root, "skills", name, "scripts", "run.py"), script)


def world():
    root = tmpdir()
    plugin, claude, state = os.path.join(root, "integrations", "claude-code", "plugin", "brain"), os.path.join(root, "home", ".claude"), os.path.join(root, "state")
    os.makedirs(plugin)
    os.makedirs(claude)
    return plugin, claude, state


def actions(syncer):
    return {("%s/%s" % (i["kind"], i["name"])): i["action"] for i in syncer.plan()}


def test_decide(IP):
    print("\n== decide (three-way) ==")
    table = [
        (("a", "a", None), "same", "identical"),
        (("a", "a", "b"), "same", "identical whatever the base"),
        (("a", None, None), "install", "only in the vault"),
        (("a", None, "a"), "removed-live", "removed from ~/.claude after a sync: not reinstalled"),
        ((None, "a", None), "backport", "only live: a new skill to add to the vault"),
        ((None, "a", "a"), "removed-vault", "removed from the vault after a sync: live left alone"),
        (("a", "b", None), "backport", "never synced and different: today's live copy wins"),
        (("b", "a", "a"), "install", "the vault moved on (a pull), live did not"),
        (("a", "b", "a"), "backport", "live was edited, the vault did not move"),
        (("b", "c", "a"), "conflict", "both changed since the last sync"),
        ((None, None, None), "none", "nowhere"),
    ]
    for (vault, live, base), expected, why in table:
        got = IP.decide(vault, live, base)
        check("%s -> %s" % (why, expected), got == expected, got)


def test_digest(IP):
    print("\n== digests ==")
    a, b = tmpdir(), tmpdir()
    for root in (a, b):
        skill(root, "x", "body")
    write(os.path.join(b, "skills", "x", "__pycache__", "run.cpython-39.pyc"), "junk")
    write(os.path.join(b, "skills", "x", ".DS_Store"), "junk")
    da, db = IP.digest(os.path.join(a, "skills", "x")), IP.digest(os.path.join(b, "skills", "x"))
    check("the same skill digests the same, caches and .DS_Store ignored", da == db and da, (da, db))
    write(os.path.join(b, "skills", "x", "scripts", "run.py"), "print('changed')\n")
    check("a change anywhere in the skill directory changes the digest", IP.digest(os.path.join(b, "skills", "x")) != da)
    check("a missing path has no digest", IP.digest(os.path.join(a, "skills", "nope")) is None)
    f = write(os.path.join(a, "agents", "planner.md"), "agent\n")
    check("an agent file digests too", IP.digest(f))


def test_sync(IP):
    print("\n== plan and apply ==")
    plugin, claude, state = world()
    skill(plugin, "vault-only", "from the vault")
    skill(claude, "live-only", "from live")
    skill(plugin, "same", "same")
    skill(claude, "same", "same")
    skill(plugin, "edited", "old wording")
    skill(claude, "edited", "new wording, edited live")
    write(os.path.join(plugin, "agents", "planner.md"), "planner v1\n")
    write(os.path.join(claude, "agents", "planner.md"), "planner v2 edited live\n")
    s = IP.Syncer(plugin, claude, state)
    got = actions(s)
    check("first run: vault-only installs, live-only and live edits back-port, identical is same",
          got == {"skills/vault-only": "install", "skills/live-only": "backport", "skills/same": "same",
                  "skills/edited": "backport", "agents/planner": "backport"}, got)

    dry = s.apply(dry_run=True)
    check("a dry run changes nothing and writes no manifest",
          not os.path.exists(os.path.join(claude, "skills", "vault-only"))
          and read(os.path.join(plugin, "skills", "edited", "SKILL.md")).endswith("old wording\n")
          and not os.path.exists(os.path.join(state, "plugin-manifest.json")) and len(dry) == 5, dry)

    report = {("%s/%s" % (r["kind"], r["name"])): r for r in s.apply()}
    check("install copies the whole skill into ~/.claude, scripts included",
          read(os.path.join(claude, "skills", "vault-only", "scripts", "run.py")) == "print('hi')\n")
    check("backport copies a live-only skill into the vault",
          os.path.isfile(os.path.join(plugin, "skills", "live-only", "SKILL.md")))
    check("backport replaces the vault copy with the live edit",
          read(os.path.join(plugin, "skills", "edited", "SKILL.md")).endswith("new wording, edited live\n"))
    check("the live copy is never touched by a backport",
          read(os.path.join(claude, "skills", "edited", "SKILL.md")).endswith("new wording, edited live\n"))
    bk = report["skills/edited"].get("backup")
    check("the vault copy it replaced is saved to a tar.gz first",
          bk and bk.endswith(".tar.gz") and os.path.isfile(bk) and bk.startswith(state), bk)
    if bk and os.path.isfile(bk):
        with tarfile.open(bk) as tar:
            member = [m for m in tar.getmembers() if m.name.endswith("SKILL.md")]
            old = tar.extractfile(member[0]).read().decode() if member else ""
        check("and the backup holds the old wording", "old wording" in old, old)
    diff = report["skills/edited"].get("diff")
    check("with a unified diff of what changed", diff and "-old wording" in read(diff) and "+new wording" in read(diff),
          diff)
    check("an agent back-ports the same way",
          read(os.path.join(plugin, "agents", "planner.md")) == "planner v2 edited live\n"
          and report["agents/planner"].get("backup"))
    check("after applying, everything is in sync", set(actions(s).values()) == {"same"}, actions(s))

    skill(plugin, "edited", "wording updated in the vault by another machine")
    got = actions(s)
    check("a vault change after a sync installs into ~/.claude (the vault is canonical)",
          got["skills/edited"] == "install", got)
    report = {("%s/%s" % (r["kind"], r["name"])): r for r in s.apply()}
    check("the live copy it replaces is backed up first",
          read(os.path.join(claude, "skills", "edited", "SKILL.md")).endswith("by another machine\n")
          and report["skills/edited"].get("backup") and os.path.isfile(report["skills/edited"]["backup"]))

    skill(claude, "same", "live edit")
    check("a live edit after a sync back-ports", actions(s)["skills/same"] == "backport")
    s.apply()
    skill(claude, "same", "live edit two")
    skill(plugin, "same", "vault edit two")
    check("both sides edited since the sync is a conflict", actions(s)["skills/same"] == "conflict")
    report = {("%s/%s" % (r["kind"], r["name"])): r for r in s.apply()}
    r = report["skills/same"]
    check("a conflict changes neither side",
          read(os.path.join(claude, "skills", "same", "SKILL.md")).endswith("live edit two\n")
          and read(os.path.join(plugin, "skills", "same", "SKILL.md")).endswith("vault edit two\n"))
    check("but backs both up and writes the diff for a person to resolve",
          len(r.get("backups") or []) == 2 and all(os.path.isfile(b) for b in r["backups"])
          and r.get("diff") and os.path.isfile(r["diff"]), r)
    check("and stays a conflict until resolved", actions(s)["skills/same"] == "conflict")

    shutil.rmtree(os.path.join(claude, "skills", "vault-only"))
    check("a skill removed from ~/.claude after a sync is reported, not reinstalled",
          actions(s)["skills/vault-only"] == "removed-live")
    s.apply()
    check("and apply leaves it removed", not os.path.exists(os.path.join(claude, "skills", "vault-only")))

    check("nothing was written outside the vault plugin, ~/.claude and the state directory",
          sorted(os.listdir(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(plugin)))))) == ["home", "integrations", "state"])


def test_install_only(IP):
    print("\n== install mode (bootstrap) ==")
    plugin, claude, state = world()
    skill(plugin, "fresh", "vault")
    skill(plugin, "edited", "vault")
    skill(claude, "edited", "live edit")
    report = IP.Syncer(plugin, claude, state).apply(install_only=True)
    got = {r["name"]: r["action"] for r in report}
    check("install mode installs what is missing", os.path.isfile(os.path.join(claude, "skills", "fresh", "SKILL.md")))
    check("but never back-ports or overwrites a live edit",
          read(os.path.join(claude, "skills", "edited", "SKILL.md")).endswith("live edit\n")
          and read(os.path.join(plugin, "skills", "edited", "SKILL.md")).endswith("vault\n")
          and got.get("edited") == "backport (skipped: install only)", got)


def test_vault_placeholder(IP):
    print("\n== the __VAULT__ placeholder ==")
    root = tmpdir()
    vault = os.path.join(root, "My Vault")
    plugin = os.path.join(vault, "integrations", "claude-code", "plugin", "brain")
    claude, state = os.path.join(root, "home", ".claude"), os.path.join(root, "state")
    os.makedirs(claude)
    skill(plugin, "placeholder", "Run `python3 __VAULT__/_bin/query.py`.", script="VAULT = '__VAULT__'\n")
    write(os.path.join(plugin, "agents", "scout.md"), "---\nname: scout\n---\nRead __VAULT__/AGENTS.md first.\n")
    s = IP.Syncer(plugin, claude, state, vault=vault)
    s.apply()
    live = read(os.path.join(claude, "skills", "placeholder", "SKILL.md"))
    check("an installed skill names this vault where the canonical copy says __VAULT__",
          "python3 %s/_bin/query.py" % vault in live and "__VAULT__" not in live, live)
    check("in every text file of the skill, and in agents",
          read(os.path.join(claude, "skills", "placeholder", "scripts", "run.py")) == "VAULT = '%s'\n" % vault
          and vault + "/AGENTS.md" in read(os.path.join(claude, "agents", "scout.md")))
    check("the canonical copy keeps the placeholder",
          "__VAULT__" in read(os.path.join(plugin, "skills", "placeholder", "SKILL.md")))
    check("after installing, the two copies count as the same",
          actions(s).get("skills/placeholder") == "same" and actions(s).get("agents/scout") == "same", actions(s))
    write(os.path.join(claude, "skills", "placeholder", "SKILL.md"), live + "A live edit naming %s/_bin/vw.py.\n" % vault)
    check("a live edit is still a back-port", actions(s).get("skills/placeholder") == "backport", actions(s))
    s.apply()
    back = read(os.path.join(plugin, "skills", "placeholder", "SKILL.md"))
    check("the back-ported copy has the vault path turned back into __VAULT__",
          "__VAULT__/_bin/vw.py" in back and vault not in back, back)
    check("and then the copies are the same again", actions(s).get("skills/placeholder") == "same", actions(s))


def test_cli():
    print("\n== install_plugin.py command line ==")
    root = tmpdir()
    vault, home, state = os.path.join(root, "vault"), os.path.join(root, "home"), os.path.join(root, "state")
    skill(os.path.join(vault, "integrations", "claude-code", "plugin", "brain"), "cli-skill", "vault")
    os.makedirs(os.path.join(home, ".claude"))
    env = dict(os.environ, BRAIN_VAULT=vault, HOME=home, BRAIN_STATE=state)
    p = subprocess.run([sys.executable, os.path.join(HERE, "install_plugin.py"), "status"], env=env,
                       capture_output=True, text=True, timeout=60)
    check("status lists each skill and agent with its action and changes nothing",
          p.returncode == 0 and "skills/cli-skill" in p.stdout and "install" in p.stdout
          and not os.path.exists(os.path.join(home, ".claude", "skills")), (p.returncode, p.stdout, p.stderr))
    p = subprocess.run([sys.executable, os.path.join(HERE, "install_plugin.py"), "sync"], env=env,
                       capture_output=True, text=True, timeout=60)
    check("sync applies it", p.returncode == 0 and os.path.isfile(os.path.join(home, ".claude", "skills", "cli-skill", "SKILL.md")),
          (p.returncode, p.stdout, p.stderr))
    check("its manifest lives in the Brain state directory",
          os.path.isfile(os.path.join(state, "plugin-manifest.json"))
          and "skills/cli-skill" in json.load(open(os.path.join(state, "plugin-manifest.json"))))


def main():
    try:
        import install_plugin as IP
        IP.decide, IP.digest, IP.Syncer
    except Exception as exc:
        check("install_plugin imports", False, "%s: %s" % (type(exc).__name__, exc))
        return finish()
    for t in (test_decide, test_digest, test_sync, test_install_only, test_vault_placeholder):
        try:
            t(IP)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    try:
        test_cli()
    except Exception as exc:
        check("test_cli ran to the end", False, "%s: %s" % (type(exc).__name__, exc))
    return finish()


def finish():
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
