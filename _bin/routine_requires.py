#!/usr/bin/env python3
"""Preflight for agent routines: does THIS machine have the repos, programs and paths a routine needs?

A routine written on one machine and moved to another fails in the most expensive way when
nothing checks first: it runs, half-blind, on schedule, and reports the gap in its own output (a
repo never cloned, a program not installed, a path that only exists on the first machine). This
module turns the gap into a refusal before the agent starts, with the fix in the message. tasks.py
calls it before every agent run; people call it before pinning a task to a machine.

What is checked, for a routine file:

- **Implicit**, read from `agent_args` so nothing is declared twice: every `--add-dir` directory;
  for every `Bash(<command>:*)` in `--allowedTools`, its program (on PATH, or executable when it is
  an absolute path), every script path in it (`~/...` or `/...` ending in a script extension) and a
  `--cwd`/`-C` directory.
- **Explicit**, the `requires:` frontmatter line (routine_auth_core.domain.parse_requires):
  `{"repos": [...], "programs": [...], "paths": [...]}`. A repo is a git checkout (`<path>/.git`);
  one given as `{"path": ..., "url": ...}` can be cloned by `--fix`.

A relative path is relative to the vault, `~` is the home directory. `--fix` clones a missing repo
that carries a url and nothing else: a missing program is for a person to install.

Usage:
    routine_requires.py check <routine.md>...   each routine, ✓ or ✗ with its gaps; exit 2 on any gap
    routine_requires.py here [--fix]            every enabled agent task this machine runs
"""
import os
import re
import shlex
import shutil
import subprocess
import sys

if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from routine_auth_core import domain as RD  # noqa: E402

SCRIPT_EXT = (".py", ".sh", ".ts", ".js", ".mjs", ".pl", ".rb")
GAP_EXIT = 2
_TRUE = ("yes", "sí", "si", "true", "1", "on")


# ---------------------------------------------------------------- pure rules

def requirements(text):
    """([(kind, target, hint)], problem) for everything a routine needs. kind: repo, program, path, dir.

    `hint` is the clone url for a repo ("" when none), else where the requirement came from.
    `problem` is set when the `requires:` line does not parse.
    """
    out = []
    args, _args_problem = RD.parse_agent_args(text)
    args = list(args)
    for i, arg in enumerate(args):
        if arg == "--add-dir" and i + 1 < len(args):
            out.append(("dir", args[i + 1], "an --add-dir directory"))
        if arg in ("--allowedTools", "--allowed-tools") and i + 1 < len(args):
            for cmd in re.findall(r"Bash\(([^)]*)\)", args[i + 1]):
                cmd = cmd[:-2] if cmd.endswith(":*") else cmd
                try:
                    words = shlex.split(cmd)
                except ValueError:
                    words = cmd.split()
                if not words:
                    continue
                out.append(("program", words[0], "the program of `%s`" % cmd))
                for j, word in enumerate(words[1:], 1):
                    if word in ("--cwd", "-C") and j + 1 < len(words):
                        out.append(("dir", words[j + 1], "a directory in `%s`" % cmd))
                    elif word.startswith(("~/", "/")) and word.endswith(SCRIPT_EXT):
                        out.append(("path", word, "a script in `%s`" % cmd))
    req, problem = RD.parse_requires(text)
    if req is not None:
        out += [("repo", path, url) for path, url in req.repos]
        out += [("program", p, "declared in requires") for p in req.programs]
        out += [("path", p, "declared in requires") for p in req.paths]
    seen, uniq = set(), []
    for item in out:
        if item[:2] not in seen:
            seen.add(item[:2])
            uniq.append(item)
    return uniq, problem


def resolve(target, vault, home):
    """An absolute path: `~` is `home`, a relative path is under `vault`."""
    if target == "~" or target.startswith("~/"):
        return home + target[1:]
    if os.path.isabs(target):
        return target
    return os.path.normpath(os.path.join(vault, target))


def check(items, probe, vault, home):
    """One row per requirement: {kind, target, hint, path, ok, message}. `probe` is injected.

    `probe` answers which(name), is_dir(path), exists(path) and is_exec(path); RealProbe does it
    on this machine, a test passes a fake.
    """
    rows = []
    for kind, target, hint in items:
        path = resolve(target, vault, home)
        if kind == "program":
            if "/" in target:
                good = probe.is_exec(path)
            else:
                good = probe.which(target) is not None
            message = "program `%s` not found (%s): install it on this machine" % (target, hint)
        elif kind == "repo":
            good = probe.is_dir(os.path.join(path, ".git"))
            fix = "git clone %s %s" % (hint, target) if hint else "clone it"
            message = "repo `%s` is not a git checkout: %s" % (target, fix)
        elif kind == "dir":
            good = probe.is_dir(path)
            message = "directory `%s` missing (%s)" % (target, hint)
        else:
            good = probe.exists(path)
            message = "`%s` missing (%s)" % (target, hint)
        rows.append({"kind": kind, "target": target, "hint": hint, "path": path, "ok": bool(good),
                     "message": "" if good else message})
    return rows


def problems(text, probe, vault, home):
    """What stops this routine from running here, each with its fix. Empty when nothing does."""
    items, problem = requirements(text)
    out = [problem] if problem else []
    return out + [r["message"] for r in check(items, probe, vault, home) if not r["ok"]]


def tasks_from_registry(text, is_mine):
    """(id, routine path) for every enabled agent row whose machine is `*` or `is_mine(machine)`."""
    rows = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        # Code ticks and emphasis are stripped, but a bare `*` is the "every machine" value, not emphasis.
        cells = [c.strip() if c.strip() == "*" else re.sub(r"^[`*_]+|[`*_]+$", "", c.strip())
                 for c in line.strip("|").split("|")]
        if len(cells) < 7 or cells[4].lower() != "agent" or cells[6].lower() not in _TRUE:
            continue
        if cells[1] != "*" and not is_mine(cells[1]):
            continue
        rows.append((cells[0], cells[5]))
    return rows


def fix(rows, run):
    """Clone every missing repo that carries a url; never install anything. Returns the targets cloned."""
    cloned = []
    for r in rows:
        if r["kind"] == "repo" and not r["ok"] and r["hint"]:
            code, _out, _err = run(["git", "clone", "-q", r["hint"], r["path"]])
            if code == 0:
                cloned.append(r["target"])
    return cloned


# ---------------------------------------------------------------- this machine

class RealProbe(object):
    """The real machine: PATH lookups and file checks, nothing else."""

    def which(self, name):
        return shutil.which(name)

    def is_dir(self, path):
        return os.path.isdir(path)

    def exists(self, path):
        return os.path.exists(path)

    def is_exec(self, path):
        return os.path.isfile(path) and os.access(path, os.X_OK)


def _run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return p.returncode, p.stdout, p.stderr
    except Exception as exc:
        return 1, "", repr(exc)


def default_vault():
    return os.environ.get("BRAIN_VAULT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _is_mine(machine):
    import machine_identity
    return machine_identity.machine_is_mine(machine)


def tasks_here(vault=None, is_mine=None):
    """(id, routine path) for every enabled agent task in the registry that this machine runs."""
    vault = vault or default_vault()
    try:
        with open(os.path.join(vault, "90-Meta", "scheduled-tasks.md"), encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return []
    return tasks_from_registry(text, is_mine or _is_mine)


def _report(name, path, probe, vault, home, do_fix, run):
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        print("✗ %s\n    routine file missing: %s" % (name, path))
        return GAP_EXIT
    items, problem = requirements(text)
    if do_fix:
        for target in fix(check(items, probe, vault, home), run):
            print("  cloned %s" % target)
    probs = ([problem] if problem else []) + [r["message"] for r in check(items, probe, vault, home) if not r["ok"]]
    print(("✗ " if probs else "✓ ") + name)
    for p in probs:
        print("    " + p)
    return GAP_EXIT if probs else 0


def main(argv=None, probe=None, vault=None, home=None, is_mine=None, run=None):
    argv = sys.argv[1:] if argv is None else argv
    probe = probe or RealProbe()
    vault = vault or default_vault()
    home = home or os.path.expanduser("~")
    run = run or _run
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "check":
        paths = [a for a in argv[1:] if not a.startswith("--")]
        return max([_report(p, resolve(p, os.getcwd(), home), probe, vault, home, "--fix" in argv, run)
                    for p in paths] or [0])
    if argv[0] == "here":
        rows = tasks_here(vault, is_mine)
        if not rows:
            print("no enabled agent task runs on this machine")
            return 0
        return max(_report(tid, resolve(p, vault, home), probe, vault, home, "--fix" in argv, run)
                   for tid, p in rows)
    print(__doc__)
    return GAP_EXIT


if __name__ == "__main__":
    sys.exit(main())
