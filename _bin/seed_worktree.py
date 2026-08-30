#!/usr/bin/env python3
"""WorktreeCreate — seeds the new worktree.

CRITICAL: this hook fails worktree creation on any exit code != 0.
Todo va envuelto y termina siempre en exit 0.
"""
import os, sys, glob, shutil, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

# Content-addressed caches: safe to link across branches.
LINKABLE = [".pnpm-store", ".cargo-cache", ".uv-cache"]
# node_modules and .venv are NEVER linked: if the branches differ in dependencies
# they corrupt each other.
COPYABLE = [".env", ".env.local", ".env.development", ".envrc",
            "config.local.json", ".tool-versions"]


def find_worktree_path(data):
    for key in ("worktree_path", "path", "worktree", "target", "directory"):
        v = data.get(key)
        if isinstance(v, str) and os.path.isdir(v):
            return v
    for v in data.values():
        if isinstance(v, str) and os.path.isdir(v) and os.path.isdir(os.path.join(v, ".git")) is False\
                and os.path.exists(os.path.join(v, ".git")):
            return v
    return data.get("cwd") if isinstance(data.get("cwd"), str) else None


def alloc_port(wt):
    h = int(hashlib.sha1(os.path.basename(wt).encode()).hexdigest()[:6], 16)
    return 3000 + (h % 1000)


def main():
    try:
        if not B.enabled():
            sys.exit(0)
        data = B.read_hook_input()
        wt = find_worktree_path(data)
        if not wt or not os.path.isdir(wt):
            sys.exit(0)
        src = B.main_repo(wt) or ""
        notes = []
        sembrados = [".claude/CONTEXT-PACK.md", ".claude/BRAIN-PROTOCOL.md", "plan.md"]

        # 1. unversioned local files the build needs
        if src and os.path.isdir(src):
            for name in COPYABLE:
                s, d = os.path.join(src, name), os.path.join(wt, name)
                if os.path.exists(s) and not os.path.exists(d):
                    try:
                        shutil.copy2(s, d); notes.append("copied %s" % name)
                        sembrados.append(name)
                    except Exception:
                        pass
            for name in LINKABLE:
                s, d = os.path.join(src, name), os.path.join(wt, name)
                if os.path.isdir(s) and not os.path.exists(d):
                    try:
                        os.symlink(s, d); notes.append("linked %s" % name)
                        sembrados.append(name)
                    except Exception:
                        pass

        # 2. its own port so as not to collide with other sessions
        try:
            port = alloc_port(wt)
            envl = os.path.join(wt, ".env.local")
            line = "PORT=%d\n" % port
            if not os.path.exists(envl) or "PORT=" not in open(envl, errors="replace").read():
                with open(envl, "a") as fh:
                    fh.write(line)
                notes.append("PORT=%d" % port)
                sembrados.append(".env.local")
        except Exception:
            pass

        # 3. context: protocol + this session's most recent pack
        try:
            cdir = os.path.join(wt, ".claude")
            os.makedirs(cdir, exist_ok=True)
            proto = os.path.join(B.VAULT, "90-Meta", "PROTOCOL-COMPACT.md")
            if os.path.exists(proto):
                shutil.copy2(proto, os.path.join(cdir, "BRAIN-PROTOCOL.md"))
            sid = B.sid8(data.get("session_id"))
            packs = sorted(glob.glob(os.path.join(B.VAULT, "60-Context-Packs", "*%s*.md" % sid)),
                           key=os.path.getmtime, reverse=True)
            if packs:
                shutil.copy2(packs[0], os.path.join(cdir, "CONTEXT-PACK.md"))
                notes.append("pack seeded")
        except Exception:
            pass

        # 4. exclude from version control EVERYTHING we seeded.
        # Without this a `git add -A` takes the pack, the plan and —the serious one—
        # the `.env` we just copied, which is a credentials file, into the repository.
        # info/exclude is local: it does not dirty the project's .gitignore nor travel to other clones.
        try:
            code, gitpath, _ = B.run([B.GIT, "rev-parse", "--git-path", "info/exclude"], cwd=wt)
            if code == 0 and gitpath:
                excl = gitpath if os.path.isabs(gitpath) else os.path.join(wt, gitpath)
                os.makedirs(os.path.dirname(excl), exist_ok=True)
                existing = open(excl, errors="replace").read() if os.path.exists(excl) else ""
                fresh = [n for n in dict.fromkeys(sembrados) if ("\n" + n) not in ("\n" + existing)]
                if fresh:
                    with open(excl, "a") as fh:
                        fh.write("\n# brain: artifacts seeded into worktrees\n")
                        fh.write("\n".join(fresh) + "\n")
                    notes.append("%d git exclusions" % len(fresh))
        except Exception:
            pass

        if notes:
            sys.stderr.write("brain: " + ", ".join(notes) + "\n")
    except Exception:
        pass
    sys.exit(0)          # ALWAYS 0: a failure here would abort worktree creation


if __name__ == "__main__":
    main()
