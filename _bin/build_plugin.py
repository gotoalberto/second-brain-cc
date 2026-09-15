#!/usr/bin/env python3
"""Keeps the vault plugin and ~/.claude in step. The vault is canonical.

The plugin is what makes the system portable: cloud/Cowork sessions and other machines
do not read your ~/.claude, but they do install a plugin.

Until 2026-09-15 this copied ~/.claude into the vault unconditionally — agents, whole
skills, and the hooks block of settings.json. Now:

- skills and agents go through install_plugin.py's three-way sync: live edits are
  back-ported with a tar.gz backup and a diff, vault changes are installed into ~/.claude,
  and a copy changed on both sides is left alone and reported;
- hooks.json is generated from 90-Meta/events.json (events_core), never copied from a live
  settings.json, which may carry hooks that are not Brain's.

vault_sync.py still calls main() before every commit.
"""
import os, sys, json, shutil, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

HOME = os.path.expanduser("~")
PLUGIN = os.path.join(B.VAULT, "integrations", "claude-code", "plugin", "brain")


def sync_dir(src, dst, pattern):
    os.makedirs(dst, exist_ok=True)
    for p in glob.glob(pattern):
        rel = os.path.relpath(p, src)
        target = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(p, target)
    return len(glob.glob(pattern))


def sync_skills(src_root, dst_root):
    """Copies WHOLE skills, not just their SKILL.md.

    A skill is a directory: it can carry `scripts/`, `reference/` and more, and copying
    only the SKILL.md leaves the plugin with a skill that announces itself and
    then cannot find its own files. It happened with `impeccable` (148 files,
    of which 1 travelled).

    It does not delete from the plugin what no longer exists live — nothing is deleted
    here — but it does say so: a ghost skill would be installed on the new machine.
    """
    copied, stale = 0, []
    live = set()
    for skill_md in glob.glob(os.path.join(src_root, "*", "SKILL.md")):
        d = os.path.dirname(skill_md)
        name = os.path.basename(d)
        live.add(name)
        target = os.path.join(dst_root, name)
        if os.path.isdir(target):
            shutil.rmtree(target)          # clean copy: otherwise leftovers survive
        shutil.copytree(d, target, ignore=shutil.ignore_patterns(
            ".git", "node_modules", "__pycache__", "*.pyc", ".DS_Store"))
        copied += 1
    if os.path.isdir(dst_root):
        for name in sorted(os.listdir(dst_root)):
            if os.path.isdir(os.path.join(dst_root, name)) and name not in live:
                stale.append(name)
    return copied, stale


def main():
    import brain_paths
    import install_plugin as IP
    from events_core import adapters as EAD, application as EA, domain as ED

    syncer = IP.Syncer(PLUGIN, os.path.join(HOME, ".claude"), brain_paths.state_dir(),
                       log=lambda s: B.log("plugin", "sync", detail=s))
    report = syncer.apply()
    moved = [r for r in report if r["action"] not in ("same", "none")]
    for r in moved:
        print("%-14s %s/%s%s" % (r["action"], r["kind"], r["name"],
                                 ("  " + (r.get("error") or r.get("backup") or ", ".join(r.get("backups") or [])))
                                 if (r.get("error") or r.get("backup") or r.get("backups")) else ""))

    registry_path = os.path.join(B.VAULT, "90-Meta", "events.json")
    try:
        with open(registry_path, encoding="utf-8") as fh:
            registry = ED.load_registry(fh.read())
    except (OSError, ED.RegistryError) as exc:
        registry = None
        print("warning: hooks.json left as it is — cannot load %s (%s)" % (registry_path, exc))
    hooks_note = "hooks unchanged"
    if registry is not None:
        # Written ONLY when the content changes: vault_sync.py refreshes the plugin before
        # deciding what to commit, and a file whose mtime never settles is never committed.
        ports = EA.Ports(snapshot=None, state=None, runner=None, session=None, alerts=None, git=None,
                         files=EAD.VaultFiles(B.VAULT), clock=None)
        hooks_note = "hooks.json %s from events.json" % (
            "regenerated" if EA.generate_claude_hooks(ports, registry).changed else "current")

    print("plugin updated: %d skills and agents checked, %d moved, %s"
          % (len(report), len(moved), hooks_note))
    print("install on another machine:")
    print("  /plugin marketplace add %s" % os.path.join(B.VAULT, "plugin"))
    print("  /plugin install brain@brain-marketplace")


if __name__ == "__main__":
    main()
