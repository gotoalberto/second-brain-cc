#!/usr/bin/env python3
"""Syncs agents, skills and hooks from ~/.claude into the vault plugin.

The plugin is what makes the system portable: cloud/Cowork sessions and other machines
do not read your ~/.claude, but they do install a plugin.
"""
import os, sys, json, shutil, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

HOME = os.path.expanduser("~")
PLUGIN = os.path.join(B.VAULT, "plugin", "brain")


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
    n_agents = sync_dir(os.path.join(HOME, ".claude", "agents"),
                        os.path.join(PLUGIN, "agents"),
                        os.path.join(HOME, ".claude", "agents", "*.md"))
    n_skills, stale = sync_skills(os.path.join(HOME, ".claude", "skills"),
                                  os.path.join(PLUGIN, "skills"))
    if stale:
        print("warning: the plugin has skills that no longer exist in ~/.claude: %s"
              % ", ".join(stale))
    st = json.load(open(os.path.join(HOME, ".claude", "settings.json")))
    os.makedirs(os.path.join(PLUGIN, "hooks"), exist_ok=True)
    # Written ONLY when the content changes. Rewriting it unconditionally advanced its
    # mtime on every run, and `vault_sync.py` calls refresh_plugin() before deciding what
    # to commit — so `hooks.json` never sat still for the QUIESCENCE window and was never
    # committed, on any pass, ever. The skill and agent copies use shutil.copy2, which
    # preserves mtime, so only this generated file had the problem.
    hooks_path = os.path.join(PLUGIN, "hooks", "hooks.json")
    body = json.dumps({"hooks": st.get("hooks", {})}, indent=2, ensure_ascii=False)
    try:
        current = open(hooks_path, encoding="utf-8").read()
    except OSError:
        current = None
    if current != body:
        B.atomic_write(hooks_path, body)
    print("plugin updated: %d agents, %d skills, hooks included" % (n_agents, n_skills))
    print("install on another machine:")
    print("  /plugin marketplace add %s" % os.path.join(B.VAULT, "plugin"))
    print("  /plugin install brain@brain-marketplace")


if __name__ == "__main__":
    main()
