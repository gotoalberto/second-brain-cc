#!/usr/bin/env python3
"""Run Google's Antigravity CLI (agy) headless from Claude Code, safely and parseably.

  agy_run.py doctor
  agy_run.py run --dir <path> (--prompt TEXT | --prompt-file FILE)
                 [--write] [--model SLUG] [--effort low|medium|high]
                 [--timeout 15m] [--schema JSON_OR_FILE] [--conversation ID]

Prints one JSON object on stdout and exits 0 when agy reported SUCCESS, 1 otherwise.

What the wrapper enforces, each point learned by probing the agy CLI:
- `--add-dir <dir>` and cwd=<dir>. Without a declared workspace agy writes into its own
  ~/.gemini/antigravity-cli/scratch instead of the repo.
- `--sandbox` always. It blocks arbitrary writes outside the workspace (a touch in $HOME fails
  with "Operation not permitted"), though tool caches such as ~/Library/Caches/ms-playwright
  are still writable and the network is open.
- Review mode (default): normal permissions. agy can read files, but the first run_command it
  tries is denied and it usually stops there with an empty `response` and `denied_actions`.
  Good for questions about code, useless for anything that needs the browser or a shell.
- `--write`: adds `--dangerously-skip-permissions`, so it edits files, runs commands and drives
  its browser on its own. Allowed only in a linked git worktree, or in a scratch directory that
  is not inside any git repo. Never in a main checkout.
- stdin closed, `--output-format json`, and an outer kill timer 60 s past `--print-timeout`,
  because a headless agent that hangs must not hang the caller.
"""
import argparse, json, os, re, shutil, subprocess, sys, time

AGY = os.environ.get("AGY_BIN") or shutil.which("agy") or os.path.expanduser("~/.local/bin/agy")
LOG = os.path.expanduser("~/.gemini/antigravity-cli/cli.log")


def out(obj, ok):
    print(json.dumps(obj, indent=2, ensure_ascii=False))
    sys.exit(0 if ok else 1)


def seconds(spec):
    m = re.fullmatch(r"(\d+)([smh]?)", spec.strip())
    if not m:
        raise ValueError("timeout must look like 90s, 15m or 1h")
    return int(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600}[m.group(2)]


def git(dirpath, *args):
    r = subprocess.run(["git", "-C", dirpath, *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def autonomy_allowed(dirpath):
    """Linked worktree, or a plain directory outside every git repo."""
    if git(dirpath, "rev-parse", "--is-inside-work-tree") != "true":
        return True
    return is_linked_worktree(dirpath)


def is_linked_worktree(dirpath):
    gd, common = git(dirpath, "rev-parse", "--absolute-git-dir"), git(dirpath, "rev-parse", "--git-common-dir")
    if not gd or not common:
        return False
    common = os.path.realpath(os.path.join(dirpath, common))
    return os.path.realpath(gd) != common


def build_cmd(a, prompt):
    cmd = [AGY, "-p", prompt, "--output-format", "json", "--print-timeout", a.timeout,
           "--add-dir", a.dir, "--sandbox"]
    if a.write:
        cmd.append("--dangerously-skip-permissions")
    for flag, val in (("--model", a.model), ("--effort", a.effort), ("--json-schema", a.schema),
                      ("--conversation", a.conversation)):
        if val:
            cmd += [flag, val]
    return cmd


def parse_envelope(stdout):
    """agy prints one JSON envelope; tolerate stray lines before it."""
    stdout = stdout.strip()
    if not stdout:
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
    return None


def cmd_run(a):
    a.dir = os.path.realpath(os.path.expanduser(a.dir))
    if not os.path.isdir(a.dir):
        out({"status": "INVALID", "error": f"not a directory: {a.dir}"}, False)
    if a.write and not autonomy_allowed(a.dir):
        out({"status": "INVALID", "error": "--write needs a linked git worktree (git worktree add ...) "
             "or a scratch directory outside any repo, never a main checkout", "dir": a.dir}, False)
    prompt = a.prompt if a.prompt is not None else open(a.prompt_file, encoding="utf-8").read()
    before = git(a.dir, "rev-parse", "HEAD")
    cmd = build_cmd(a, prompt)
    started = time.time()
    try:
        r = subprocess.run(cmd, cwd=a.dir, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=seconds(a.timeout) + 60)
    except subprocess.TimeoutExpired:
        out({"status": "TIMEOUT", "error": f"agy did not exit within {a.timeout} + 60s", "log": LOG}, False)
    env = parse_envelope(r.stdout)
    result = {"status": "ERROR", "exit_code": r.returncode, "dir": a.dir, "write": a.write,
              "wall_seconds": round(time.time() - started, 1)}
    if env is None:
        result["error"] = "agy printed no JSON envelope"
        result["stderr_tail"] = r.stderr.strip().splitlines()[-15:]
        result["log"] = LOG
    else:
        result.update({k: env[k] for k in ("status", "response", "error", "conversation_id", "num_turns",
                                           "duration_seconds", "usage", "denied_actions",
                                           "structured_output") if k in env})
    if git(a.dir, "rev-parse", "--is-inside-work-tree") == "true":
        porcelain = git(a.dir, "status", "--porcelain") or ""
        result["changed_files"] = [l[3:] for l in porcelain.splitlines()]
        result["diffstat"] = git(a.dir, "diff", "--stat") or ""
        after = git(a.dir, "rev-parse", "HEAD")
        if before and after and before != after:
            result["new_commits"] = git(a.dir, "log", "--oneline", f"{before}..{after}")
    out(result, result.get("status") == "SUCCESS")


def cmd_doctor(_a):
    info = {"agy": AGY, "exists": os.path.exists(AGY)}
    if not info["exists"]:
        info["fix"] = "curl -fsSL https://antigravity.google/cli/install.sh -o /tmp/agy.sh, read it, then bash it"
        out(info, False)
    info["version"] = subprocess.run([AGY, "--version"], capture_output=True, text=True,
                                     stdin=subprocess.DEVNULL).stdout.strip()
    try:
        m = subprocess.run([AGY, "models"], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=90)
    except subprocess.TimeoutExpired:
        info["signed_in"] = False
        info["error"] = "agy models timed out"
        out(info, False)
    text = m.stdout + m.stderr
    info["signed_in"] = m.returncode == 0 and "sign in" not in text.lower()
    info["models"] = [l.split("\t")[0] for l in m.stdout.splitlines() if "\t" in l]
    if not info["signed_in"]:
        info["fix"] = "the user runs `agy` once in a terminal tab and signs in with Google OAuth"
    out(info, info["signed_in"])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    r = sub.add_parser("run")
    r.add_argument("--dir", required=True)
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--prompt")
    g.add_argument("--prompt-file")
    r.add_argument("--write", action="store_true")
    r.add_argument("--model")
    r.add_argument("--effort", choices=["low", "medium", "high"])
    r.add_argument("--timeout", default="15m")
    r.add_argument("--schema")
    r.add_argument("--conversation")
    a = p.parse_args(argv)
    if a.cmd == "run":
        try:
            seconds(a.timeout)
        except ValueError as e:
            out({"status": "INVALID", "error": str(e)}, False)
    {"doctor": cmd_doctor, "run": cmd_run}[a.cmd](a)


if __name__ == "__main__":
    main()
