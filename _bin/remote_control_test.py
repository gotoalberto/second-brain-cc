#!/usr/bin/env python3
"""Tests for remote_control: how the supervised Remote Control server is started.

The pure half takes its environment, paths and probes as arguments. `serve` is run for real as a
subprocess against a fake `claude` on PATH that prints what it was given. Run standalone:

    python3 _bin/remote_control_test.py
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok, fail = [], []
TMP = []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def _cwd(out):
    """The directory the fake claude printed, resolved: macOS temp dirs sit behind a symlink."""
    for line in out.splitlines():
        if line.startswith("cwd="):
            return os.path.realpath(line[len("cwd="):])
    return None


def tmpdir():
    d = tempfile.mkdtemp(prefix="remote-control-test-")
    TMP.append(d)
    return d


FAKE_CLAUDE = """#!/bin/sh
echo "cwd=$(pwd)"
echo "args=$*"
echo "telemetry=${DISABLE_TELEMETRY:-unset} traffic=${CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC:-unset}"
echo "keep=${KEEP_ME:-unset}"
"""


def test_command(RC):
    print("\n== the command ==")
    cmd = RC.command("workstation", "/opt/claude")
    check("it is claude remote-control with --chrome and the machine's name",
          cmd == ["/opt/claude", "remote-control", "--chrome", "--name", "workstation"], cmd)
    check("never --spawn: a worktree spawn mode breaks against Brain's WorktreeCreate hook",
          "--spawn" not in cmd and "worktree" not in cmd, cmd)


def test_env(RC):
    print("\n== the environment ==")
    env = {"PATH": "/usr/bin", "DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1", "DISABLE_GROWTHBOOK": "1",
           "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "HOME": "/home/u"}
    check("the variables that switch off the feature flags Remote Control needs are named",
          RC.blocking_env(env) == ["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_GROWTHBOOK",
                                   "DISABLE_TELEMETRY", "DO_NOT_TRACK"], RC.blocking_env(env))
    check("an empty value does not count", RC.blocking_env({"DISABLE_TELEMETRY": ""}) == [])
    clean = RC.server_env(env)
    check("the server starts without them, and with everything else",
          clean == {"PATH": "/usr/bin", "HOME": "/home/u"}, clean)
    creds = {"ANTHROPIC_API_KEY": "k", "CLAUDE_CODE_OAUTH_TOKEN": "t", "PATH": "/usr/bin"}
    check("an API key or setup-token in the environment would take precedence over the claude.ai login, so it goes too",
          RC.server_env(creds) == {"PATH": "/usr/bin"} and RC.credential_env(creds) == ["ANTHROPIC_API_KEY",
                                                                                       "CLAUDE_CODE_OAUTH_TOKEN"],
          RC.server_env(creds))
    check("the caller's mapping is left as it was", "DISABLE_TELEMETRY" in env)


def test_config(RC):
    print("\n== the recorded working directory and name ==")
    d = tmpdir()
    path = os.path.join(d, "state", "remote-control.json")
    check("with nothing recorded there is no config", RC.load(path) is None)
    written = RC.save(os.path.join(d, "workstation"), "workstation", config_path=path)
    check("save writes the file it names", written == path and os.path.exists(path), written)
    check("privately", stat.S_IMODE(os.stat(path).st_mode) == 0o600, oct(stat.S_IMODE(os.stat(path).st_mode)))
    check("and load reads it back",
          RC.load(path) == {"dir": os.path.join(d, "workstation"), "name": "workstation"}, RC.load(path))
    with open(path, "w") as fh:
        fh.write("{not json")
    check("a broken file is no config", RC.load(path) is None)
    with open(path, "w") as fh:
        json.dump({"dir": "/x"}, fh)
    check("a file without a name is no config", RC.load(path) is None)
    check("the file lives in the Brain state directory",
          RC.config_file({"BRAIN_STATE": "/s"}, "/home/u") == "/s/remote-control.json",
          RC.config_file({"BRAIN_STATE": "/s"}, "/home/u"))


def test_problems(RC):
    print("\n== what stops the server from starting ==")
    repo = {"/home/u/workstation", "/home/u/workstation/.git"}
    cfg = {"dir": "/home/u/workstation", "name": "workstation"}
    exists = lambda p: p in repo
    check("a recorded git repository, as a normal user, is fine",
          RC.problems(cfg, exists, is_root=False, claude="/c") == [])
    check("nothing recorded: the first run's remote_control step has not been done",
          any("first_run.py" in p for p in RC.problems(None, exists, False, "/c")), RC.problems(None, exists, False, "/c"))
    missing = RC.problems({"dir": "/home/u/gone", "name": "x"}, exists, False, "/c")
    check("a working directory that is not there", any("/home/u/gone" in p for p in missing), missing)
    plain = RC.problems(cfg, lambda p: p == "/home/u/workstation", False, "/c")
    check("a working directory that is not a git repository is fine: same-dir spawn mode needs none",
          plain == [], plain)
    home = RC.problems({"dir": "/home/u", "name": "workstation"}, lambda p: p == "/home/u", False, "/c")
    check("the home directory is fine: trust is kept for it like for any directory", home == [], home)
    root = RC.problems(cfg, exists, True, "/c")
    check("root: Claude Code refuses to bypass permissions there", any("root" in p for p in root), root)
    nocli = RC.problems(cfg, exists, False, None)
    check("no claude CLI, naming every place looked in",
          any("claude" in p and "PATH" in p and "/opt/homebrew/bin" in p and "/usr/local/bin" in p for p in nocli),
          nocli)


def test_find_claude(RC):
    print("\n== finding the CLI ==")
    d = tmpdir()
    local = os.path.join(d, ".local", "bin")
    os.makedirs(local)
    exe = os.path.join(local, "claude")
    with open(exe, "w") as fh:
        fh.write("#!/bin/sh\n")
    os.chmod(exe, 0o755)
    check("on PATH first", RC.find_claude({"PATH": "/p"}, d, which=lambda n, path=None: "/p/claude") == "/p/claude")
    check("then ~/.local/bin, where the installer puts it",
          RC.find_claude({"PATH": "/p"}, d, which=lambda n, path=None: None) == exe)
    check("or nothing", RC.find_claude({"PATH": "/p"}, "/nowhere", which=lambda n, path=None: None) is None)
    check("after ~/.local/bin come the Homebrew locations",
          RC.CANDIDATES == ("~/.local/bin/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude"),
          RC.CANDIDATES)

    heads = {"/p/claude": b"#!/bin/sh\nexec claude --flag \"$@\"\n", exe: b"\x7fELF\x02\x01"}
    read = lambda p: heads.get(p, b"")
    check("a shell wrapper on PATH gives way to the real CLI in ~/.local/bin",
          RC.find_claude({"PATH": "/p"}, d, which=lambda n, path=None: "/p/claude", read=read) == exe)
    only = {"/p/claude": b"#!/usr/bin/env bash\nexec x \"$@\"\n"}
    got = RC.find_claude({"PATH": "/p"}, "/nowhere", which=lambda n, path=None: "/p/claude",
                         read=lambda p: only.get(p, b""))
    check("a wrapper is still used when it is all there is", got == "/p/claude", got)
    warn = RC.warnings("/p/claude", read=lambda p: only.get(p, b""))
    check("and then a warning names it and the \"$@\" it must keep",
          len(warn) == 1 and "/p/claude" in warn[0] and '"$@"' in warn[0], warn)
    check("a native binary is no wrapper", not RC.is_wrapper(exe, read) and RC.warnings(exe, read) == [])
    check("nor is the node script an npm install links",
          not RC.is_wrapper("/n", lambda p: b"#!/usr/bin/env node\nrequire('x')\n"))
    check("a zsh wrapper is one", RC.is_wrapper("/z", lambda p: b"#!/bin/zsh\nexec y\n"))
    check("no CLI gives no warning", RC.warnings(None) == [])


def test_serve():
    print("\n== serve, for real, against a fake claude ==")
    d = tmpdir()
    bindir, state, repo = os.path.join(d, "bin"), os.path.join(d, "state"), os.path.join(d, "workstation")
    os.makedirs(bindir)
    os.makedirs(os.path.join(repo, ".git"))
    fake = os.path.join(bindir, "claude")
    with open(fake, "w") as fh:
        fh.write(FAKE_CLAUDE)
    os.chmod(fake, 0o755)
    env = {"PATH": bindir + ":/usr/bin:/bin", "HOME": d, "BRAIN_STATE": state, "DISABLE_TELEMETRY": "1",
           "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "KEEP_ME": "yes"}
    script = os.path.join(HERE, "remote_control.py")
    p = subprocess.run([sys.executable, script, "serve"], capture_output=True, text=True, env=env, timeout=30)
    check("with nothing recorded, serve refuses and says why",
          p.returncode != 0 and "first_run.py" in p.stderr and "cwd=" not in p.stdout, (p.returncode, p.stderr))
    import remote_control as RC
    RC.save(repo, "workstation", config_path=os.path.join(state, "remote-control.json"))
    p = subprocess.run([sys.executable, script, "serve"], capture_output=True, text=True, env=env, timeout=30)
    out = p.stdout
    check("serve runs claude from a dedicated repository, when that is what is recorded",
          p.returncode == 0 and _cwd(out) == os.path.realpath(repo),
          (p.returncode, out, p.stderr))
    check("with --chrome and the recorded name", "args=remote-control --chrome --name workstation" in out, out)
    check("and without the variables that break it", "telemetry=unset traffic=unset" in out, out)
    check("keeping the rest of the environment", "keep=yes" in out, out)
    check("and warns that the claude it found is a shell wrapper", "wrapper" in p.stderr, p.stderr)
    p = subprocess.run([sys.executable, script, "show"], capture_output=True, text=True, env=env, timeout=30)
    check("show prints the directory and the command it would run",
          p.returncode == 0 and repo in p.stdout and "remote-control --chrome --name workstation" in p.stdout,
          (p.returncode, p.stdout, p.stderr))
    RC.save(d, "workstation", config_path=os.path.join(state, "remote-control.json"))
    p = subprocess.run([sys.executable, script, "serve"], capture_output=True, text=True, env=env, timeout=30)
    check("serve runs claude from the home directory, which is no git repository",
          p.returncode == 0 and _cwd(p.stdout) == os.path.realpath(d) and not os.path.exists(os.path.join(d, ".git")),
          (p.returncode, p.stdout, p.stderr))


def test_templates():
    print("\n== the supervisor templates ==")
    plist = open(os.path.join(HERE, "com.secondbrain.remote-control.plist")).read()
    import plistlib
    data = plistlib.loads(plist.encode("utf-8"))
    check("the launchd label is the generic com.secondbrain one",
          data.get("Label") == "com.secondbrain.remote-control", data.get("Label"))
    check("it runs remote_control.py serve through pywrap.sh",
          data.get("ProgramArguments", [])[-2:] == ["/home/brain-origin/Brain/_bin/remote_control.py", "serve"]
          and data["ProgramArguments"][0].endswith("/_bin/pywrap.sh"), data.get("ProgramArguments"))
    check("a long-lived server: RunAtLoad and KeepAlive, never StartInterval",
          data.get("RunAtLoad") is True and data.get("KeepAlive") is True and "StartInterval" not in data, data)
    check("~/.local/bin, where the claude installer puts the CLI, is on its PATH",
          "/home/brain-origin/.local/bin" in data.get("EnvironmentVariables", {}).get("PATH", ""),
          data.get("EnvironmentVariables"))
    check("it logs where the other jobs log",
          data.get("StandardOutPath") == "/home/brain-origin/Library/Application Support/brain/logs/remote-control.log",
          data.get("StandardOutPath"))
    folder = os.path.join(HERE, "systemd")
    unit = open(os.path.join(folder, "second-brain-remote-control.service")).read()
    check("the systemd unit has no timer: it is a server, not a poll",
          not os.path.exists(os.path.join(folder, "second-brain-remote-control.timer")))
    for line in ("Type=simple", "Restart=always", "RestartSec=15", "StartLimitIntervalSec=0",
                 "Environment=BRAIN_JOB_LABEL=second-brain-remote-control", "WantedBy=default.target",
                 "ExecStart=/bin/sh /home/brain-origin/Brain/_bin/pywrap.sh /home/brain-origin/Brain/_bin/remote_control.py serve"):
        check("the unit says %s" % line, line in unit.splitlines(), unit)
    check("and puts ~/.local/bin on PATH", "/home/brain-origin/.local/bin" in unit, unit)
    for name, text in (("plist", plist), ("unit", unit)):
        check("the %s never asks for a worktree spawn mode" % name, "--spawn" not in text, name)


def main():
    try:
        import remote_control as RC
        RC.command
    except Exception as exc:
        check("remote_control imports", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_command, test_env, test_config, test_problems, test_find_claude):
            try:
                t(RC)
            except Exception as exc:
                import traceback
                traceback.print_exc()
                check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
        for t in (test_serve, test_templates):
            try:
                t()
            except Exception as exc:
                import traceback
                traceback.print_exc()
                check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
