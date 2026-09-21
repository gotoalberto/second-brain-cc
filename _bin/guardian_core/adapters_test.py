#!/usr/bin/env python3
"""Tests for the guardian's adapters: the code that actually touches the machine.

Every test works in a temporary directory: a scratch settings.json, a fake `launchctl`
script passed by path, fake python3 executables, a throwaway git repository with a bare
remote, a temporary queue file, and fakes in place of Google. The real
~/.claude/settings.json, launchctl, osascript, KeePass and network are never reached.
Run standalone:

    python3 _bin/guardian_core/adapters_test.py
"""
import base64
import datetime as dt
import email
import io
import json
import os
import plistlib
import shutil
import smtplib
import subprocess
import sys
import tempfile
import types
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[0] = os.path.dirname(HERE)

ok, fail = [], []
TMP = []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def tmpdir():
    d = tempfile.mkdtemp(prefix="guardian-adapters-")
    TMP.append(d)
    return d


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    if mode is not None:
        os.chmod(path, mode)
    return path


class StepClock:
    def __init__(self):
        self.t = dt.datetime(2026, 9, 15, 10, 0, 0)

    def now(self):
        self.t += dt.timedelta(seconds=1)
        return self.t


def outcome(fn, *a, **kw):
    try:
        return fn(*a, **kw), None
    except BaseException as exc:
        return None, exc


# ---------------------------------------------------------------- launchd

FAKE_LAUNCHCTL = r'''#!/bin/sh
echo "$*" >> "%(log)s"
case "$1 $2" in
  "print gui/501/com.test.loaded"|"print gui/501/com.test.failed"|"print gui/501/com.test.never") exit 0 ;;
  "list com.test.loaded") printf '{\n\t"Label" = "com.test.loaded";\n\t"LastExitStatus" = 0;\n};\n'; exit 0 ;;
  "list com.test.failed") printf '{\n\t"Label" = "com.test.failed";\n\t"LastExitStatus" = 256;\n};\n'; exit 0 ;;
  "list com.test.never") printf '{\n\t"Label" = "com.test.never";\n};\n'; exit 0 ;;
  "bootstrap gui/501") exit 0 ;;
  "bootout gui/501/com.test.loaded") exit 0 ;;
esac
exit 113
'''

TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>%(label)s</string>
  <key>ProgramArguments</key>
  <array>
    <string>/home/brain-origin/Brain/_bin/pywrap.sh</string>
    <string>/home/brain-origin/Brain/_bin/guardian.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>HOME</key><string>/home/brain-origin</string></dict>
  <key>StandardOutPath</key><string>/home/brain-origin/.claude/state/brain/logs/sub/%(label)s.log</string>
  <key>StandardErrorPath</key><string>/home/brain-origin/.claude/state/brain/logs/sub/%(label)s.log</string>
</dict>
</plist>
"""


def test_launchd():
    print("\n== LaunchctlControl ==")
    d = tmpdir()
    vault, home = os.path.join(d, "Vault"), os.path.join(d, "Home")
    agents = os.path.join(home, "Library", "LaunchAgents")
    log = os.path.join(d, "launchctl.log")
    fake = write(os.path.join(d, "launchctl"), FAKE_LAUNCHCTL % {"log": log}, mode=0o755)
    for label in ("com.test.loaded", "com.test.failed", "com.test.missing"):
        write(os.path.join(vault, "_bin", label + ".plist"), TEMPLATE % {"label": label})
    write(os.path.join(agents, "com.test.loaded.plist"), TEMPLATE % {"label": "com.test.loaded"})

    lc = AD.LaunchctlControl(vault=vault, home=home, uid=501, agents_dir=agents, launchctl=fake)
    check("the jobs are the plists the vault carries",
          lc.labels() == ["com.test.failed", "com.test.loaded", "com.test.missing"], lc.labels())
    check("installed means the plist is in LaunchAgents",
          lc.installed("com.test.loaded") and not lc.installed("com.test.missing"))
    check("a job launchctl can print is loaded", lc.is_loaded("com.test.loaded"))
    check("a job launchctl does not know is not loaded", not lc.is_loaded("com.test.missing"))
    check("a zero LastExitStatus is ok", lc.last_exit_ok("com.test.loaded")[0] is True)
    good, detail = lc.last_exit_ok("com.test.failed")
    check("a non-zero LastExitStatus is not ok, and says so", good is False and "256" in detail, detail)
    check("a job that never exited is ok", lc.last_exit_ok("com.test.never")[0] is True)

    done, detail = lc.install("com.test.missing")
    installed = os.path.join(agents, "com.test.missing.plist")
    check("install writes the plist into LaunchAgents", done and os.path.exists(installed), detail)
    rendered = open(installed).read()
    check("the original machine's paths are rewritten for this one",
          "/home/brain-origin" not in rendered and vault + "/_bin/pywrap.sh" in rendered, rendered)
    parsed = plistlib.loads(rendered.encode())
    check("the installed plist is still a valid plist with its label",
          parsed["Label"] == "com.test.missing", parsed)
    check("the log directory the plist names is created (launchd will not start without it)",
          os.path.isdir(os.path.join(home, ".claude", "state", "brain", "logs", "sub")))

    done, detail = lc.bootstrap("com.test.missing")
    calls = open(log).read()
    check("bootstrap asks launchctl to load the installed plist into the user domain",
          done and ("bootstrap gui/501 %s" % installed) in calls, calls)
    check("only the fake launchctl was ever called", os.path.exists(log))


def test_launchd_drift():
    print("\n== LaunchctlControl drift ==")
    d = tmpdir()
    vault, home = os.path.join(d, "Vault"), os.path.join(d, "Home")
    agents = os.path.join(home, "Library", "LaunchAgents")
    backups = os.path.join(d, "state", "plist-backups")
    log = os.path.join(d, "launchctl.log")
    fake = write(os.path.join(d, "launchctl"), FAKE_LAUNCHCTL % {"log": log}, mode=0o755)
    for label in ("com.test.loaded", "com.test.missing"):
        write(os.path.join(vault, "_bin", label + ".plist"), TEMPLATE % {"label": label})
    lc = AD.LaunchctlControl(vault=vault, home=home, uid=501, agents_dir=agents, launchctl=fake,
                             backup_dir=backups, environ={})
    installed = os.path.join(agents, "com.test.loaded.plist")
    write(installed, lc.render("com.test.loaded"))
    check("a plist installed from the current template has not drifted", not lc.drifted("com.test.loaded"))
    stale = lc.render("com.test.loaded").replace("pywrap.sh", "old-python")
    write(installed, stale)
    check("a plist that differs from the template has drifted", lc.drifted("com.test.loaded"))
    check("an uninstalled plist is not drift", not lc.drifted("com.test.missing"))

    done, detail = lc.reinstall("com.test.loaded")
    calls = open(log).read()
    check("reinstall rewrites the plist from the template",
          done and open(installed).read() == lc.render("com.test.loaded"), detail)
    saved = [os.path.join(backups, f) for f in os.listdir(backups)] if os.path.isdir(backups) else []
    check("the drifted plist is backed up outside LaunchAgents first",
          len(saved) == 1 and open(saved[0]).read() == stale, saved)
    check("reinstall's detail names that backup, so the repair alert can list it",
          len(saved) == 1 and saved[0] in detail, detail)
    check("a loaded job is booted out and bootstrapped again so launchd reads the new file",
          calls.find("bootout gui/501/com.test.loaded") != -1
          and calls.find("bootout gui/501/com.test.loaded") < calls.find("bootstrap gui/501 %s" % installed),
          calls)
    check("after reinstall it no longer drifts", not lc.drifted("com.test.loaded"))

    check("self_label is the launchd job this process runs as",
          AD.LaunchctlControl(vault=vault, home=home, uid=501, launchctl=fake,
                              environ={"XPC_SERVICE_NAME": "com.test.loaded"}).self_label()
          == "com.test.loaded")
    check("and empty from a terminal", lc.self_label() == "")


def test_state_dir():
    print("\n== default_state_dir delegates to brain_paths ==")
    import brain_paths
    old = os.environ.get("BRAIN_STATE")
    d = tmpdir()
    os.environ["BRAIN_STATE"] = d
    try:
        check("the guardian's state directory is brain_paths.state_dir()",
              AD.default_state_dir() == brain_paths.state_dir() == d, AD.default_state_dir())
        check("raised alerts live under it", AD.raised_path().startswith(d + os.sep), AD.raised_path())
    finally:
        if old is None:
            os.environ.pop("BRAIN_STATE", None)
        else:
            os.environ["BRAIN_STATE"] = old


# ---------------------------------------------------------------- small adapters


def test_notifier_state_paths():
    print("\n== OsascriptNotifier, JsonStateStore, LocalPaths, SystemClock ==")
    seen = []

    def fake_run(cmd, **kw):
        seen.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    AD.OsascriptNotifier(run=fake_run).notify('Brain "guardian"', 'it\'s "broken"')
    cmd, kw = seen[0]
    script = cmd[-1]
    check("the notification goes through osascript", cmd[0].endswith("osascript"), cmd)
    check("quotes in title and message are escaped",
          '\\"guardian\\"' in script and '\\"broken\\"' in script, script)
    check("osascript is bounded by a timeout", kw.get("timeout"), kw)

    def exploding(cmd, **kw):
        raise OSError("no GUI session")

    _, exc = outcome(AD.OsascriptNotifier(run=exploding).notify, "t", "m")
    check("a notifier that cannot notify never raises", exc is None, repr(exc))

    d = tmpdir()
    st = AD.JsonStateStore(os.path.join(d, "sub", "state.json"))
    check("missing state loads as empty", st.load() == {})
    st.save({"alerts": {"active": {}}})
    check("state round-trips", st.load() == {"alerts": {"active": {}}})
    write(os.path.join(d, "sub", "state.json"), "garbage")
    check("corrupt state loads as empty instead of crashing", st.load() == {})

    check("LocalPaths sees what exists", AD.LocalPaths().exists(d) and not AD.LocalPaths().exists(d + "/nope"))
    check("SystemClock returns a datetime", isinstance(AD.SystemClock().now(), dt.datetime))


def test_raised_alerts():
    print("\n== raise_alert / clear_alert ==")
    d = tmpdir()
    path = os.path.join(d, "raised.json")
    AD.raise_alert("routine:x", "routine x failed: exit=127", path=path)
    AD.raise_alert("routine:y", "routine y timed out", severity="warn", path=path)
    got = AD.RaisedAlertsFile(path).load()
    check("raised alerts are recorded with severity and summary",
          got["routine:x"]["severity"] == "fail" and got["routine:y"]["severity"] == "warn"
          and "exit=127" in got["routine:x"]["summary"], got)
    AD.raise_alert("routine:x", "routine x failed again", path=path)
    check("raising the same key again replaces it",
          AD.RaisedAlertsFile(path).load()["routine:x"]["summary"] == "routine x failed again")
    AD.clear_alert("routine:x", path=path)
    check("clearing removes only that key", sorted(AD.RaisedAlertsFile(path).load()) == ["routine:y"])
    _, exc = outcome(AD.clear_alert, "never-raised", path=path)
    check("clearing a key that was never raised is harmless", exc is None, repr(exc))
    check("a missing raised-alerts file loads as empty",
          AD.RaisedAlertsFile(os.path.join(d, "none.json")).load() == {})


# ---------------------------------------------------------------- probes


def git(cwd, *args):
    p = subprocess.run(["/usr/bin/git", "-c", "user.name=t", "-c", "user.email=t@example.com",
                        "-c", "init.defaultBranch=main"] + list(args),
                       cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout


def test_vault_probe():
    print("\n== VaultDoctorProbe on a fixture repository ==")
    d = tmpdir()
    remote, vault, state = os.path.join(d, "remote.git"), os.path.join(d, "vault"), os.path.join(d, "state")
    os.makedirs(vault)
    git(d, "init", "-q", "--bare", remote)
    git(vault, "init", "-q")
    write(os.path.join(vault, "a.md"), "a\n")
    git(vault, "add", "-A")
    git(vault, "commit", "-qm", "one")
    git(vault, "remote", "add", "origin", remote)
    git(vault, "push", "-q", "-u", "origin", "HEAD:main")
    git(vault, "branch", "-q", "--set-upstream-to=origin/main")

    probe = AD.VaultDoctorProbe(vault=vault, state_dir=state, run=AD.plain_run)
    s = probe.sync_status()
    check("a pushed, clean repository has nothing pending and an upstream",
          s.pending == 0 and s.unpushed_age_s is None and s.remote_ok, s)

    write(os.path.join(vault, "b.md"), "b\n")
    git(vault, "add", "-A")
    git(vault, "commit", "-qm", "two")
    write(os.path.join(vault, "c.md"), "c\n")
    s = probe.sync_status()
    check("an uncommitted file is pending", s.pending == 1, s)
    check("an unpushed commit has an age", s.unpushed_age_s is not None and s.unpushed_age_s >= 0, s)

    lone = os.path.join(d, "lone")
    os.makedirs(lone)
    git(lone, "init", "-q")
    write(os.path.join(lone, "x.md"), "x\n")
    git(lone, "add", "-A")
    git(lone, "commit", "-qm", "x")
    s = AD.VaultDoctorProbe(vault=lone, state_dir=state, run=AD.plain_run).sync_status()
    check("a repository with no upstream says so", s.remote_ok is False, s)

    check("a missing index has no age", probe.index_age_s() is None)
    write(os.path.join(vault, "_index", "vault.db"), "")
    age = probe.index_age_s()
    check("an index just written is fresh", age is not None and age < 60, age)

    check("no linkfix state means no broken links", probe.broken_links() == 0)
    write(os.path.join(state, "linkfix.json"), json.dumps({"broken": [["a", "b"], ["c", "d"]]}))
    check("broken links come from linkfix's saved state", probe.broken_links() == 2)


def config_lines(git_dir):
    """Every key=value in one config file, read by file so nothing global leaks in."""
    p = subprocess.run(["/usr/bin/git", "config", "--file", os.path.join(git_dir, "config"), "--list"],
                       capture_output=True, text=True)
    return sorted(p.stdout.splitlines())


def files_under(folder):
    return sorted(os.path.relpath(os.path.join(root, f), folder)
                  for root, _, names in os.walk(folder) for f in names)


def hooks_repo(d, name):
    vault = os.path.join(d, name)
    os.makedirs(vault)
    git(vault, "init", "-q")
    write(os.path.join(vault, "githooks", "pre-commit"), "#!/bin/sh\nexit 0\n", mode=0o644)
    write(os.path.join(vault, "githooks", "post-commit"), "#!/bin/sh\nexit 0\n", mode=0o755)
    git(vault, "add", "-A")
    git(vault, "commit", "-qm", "hooks", "--no-verify")
    return vault


def test_git_hooks():
    print("\n== GitHooksControl on a fixture repository ==")
    d = tmpdir()
    vault = hooks_repo(d, "vault")
    gh = AD.GitHooksControl(vault)
    before = config_lines(os.path.join(vault, ".git"))
    s = gh.status()
    check("an unset core.hooksPath reads as None", s.hooks_path is None, s)
    files = {f.name: f for f in s.files}
    check("every Brain git hook is listed, with whether it exists and is executable",
          sorted(files) == ["post-commit", "pre-commit"]
          and files["pre-commit"].exists and not files["pre-commit"].executable
          and files["post-commit"].exists and files["post-commit"].executable, s)
    check("reading changes no config", config_lines(os.path.join(vault, ".git")) == before)

    done, detail = gh.set_hooks_path()
    after = config_lines(os.path.join(vault, ".git"))
    check("set_hooks_path writes core.hooksPath=githooks to the repository config",
          done and "core.hookspath=githooks" in after, (done, detail, after))
    check("and no other key", sorted(set(after) - set(before)) == ["core.hookspath=githooks"]
          and set(before) <= set(after), (before, after))
    done, detail = gh.make_executable("pre-commit")
    mode = os.stat(os.path.join(vault, "githooks", "pre-commit")).st_mode & 0o777
    check("make_executable adds the execute bits where read bits are", done and mode == 0o755, oct(mode))
    s = gh.status()
    check("afterwards the repository reads healthy",
          s.hooks_path == "githooks" and AD.D.git_hooks_findings(s) == [], s)
    check("setting it again leaves the config as it is",
          gh.set_hooks_path()[0] and config_lines(os.path.join(vault, ".git")) == after)
    done, _ = gh.make_executable("../../escape")
    check("make_executable refuses a name that is not a Brain git hook", not done)

    main = hooks_repo(d, "main")
    wt = os.path.join(d, "wt")
    git(main, "worktree", "add", "-q", wt)
    common = os.path.join(main, ".git")
    before, before_files = config_lines(common), files_under(common)
    gh = AD.GitHooksControl(wt)
    check("from a linked worktree the status reads the main repository's config",
          gh.status().hooks_path is None)
    done, detail = gh.set_hooks_path()
    after = config_lines(common)
    check("from a linked worktree the key lands in the main repository config",
          done and sorted(set(after) - set(before)) == ["core.hookspath=githooks"], (detail, before, after))
    check("no per-worktree config file is created and no other git file appears",
          files_under(common) == before_files
          and not any(f.endswith("config.worktree") for f in files_under(common)),
          sorted(set(files_under(common)) ^ set(before_files)))
    check("the main checkout then reads healthy too",
          AD.GitHooksControl(main).status().hooks_path == "githooks")
    rc, out = git(wt, "config", "--get", "extensions.worktreeConfig")
    check("worktree config is not switched on", rc != 0 and not out.strip(), (rc, out))

    plain = os.path.join(d, "plain")
    os.makedirs(plain)
    _, exc = outcome(AD.GitHooksControl(plain).status)
    check("a directory that is not a git repository raises", isinstance(exc, Exception), repr(exc))


def test_interpreter_probe():
    print("\n== InterpreterHealthProbe ==")
    d = tmpdir()
    clt = os.path.join(d, "CLT")
    os.mkdir(clt)
    broken = write(os.path.join(d, "broken"), "#!/bin/sh\necho 'xcrun: error' >&2\nexit 69\n", mode=0o755)
    dev_only = write(os.path.join(d, "dev_only"),
                     '#!/bin/sh\n[ "$DEVELOPER_DIR" = "%s" ] || exit 69\nexit 0\n' % clt, mode=0o755)
    good = write(os.path.join(d, "good"), "#!/bin/sh\nexit 0\n", mode=0o755)
    missing = os.path.join(d, "missing")

    probe = AD.InterpreterHealthProbe(hook_python=broken, fallbacks=[dev_only, good, missing], clt=clt)
    st = probe.python3_health()
    check("the first status is the hooks' interpreter, run as the hooks run it",
          st[0].path == broken and st[0].ok is False and "69" in st[0].detail, st)
    check("a fallback that needs DEVELOPER_DIR is reported working with it",
          any(s.ok and dev_only in s.path and "DEVELOPER_DIR" in s.path for s in st), st)
    check("a working fallback is reported working", any(s.ok and s.path == good for s in st), st)
    check("a missing fallback is reported missing",
          any((not s.ok) and s.path == missing and "missing" in s.detail for s in st), st)

    old = os.environ.get("DEVELOPER_DIR")
    os.environ["DEVELOPER_DIR"] = clt
    try:
        st = AD.InterpreterHealthProbe(hook_python=dev_only, fallbacks=[], clt=clt).python3_health()
    finally:
        if old is None:
            os.environ.pop("DEVELOPER_DIR", None)
        else:
            os.environ["DEVELOPER_DIR"] = old
    check("the hooks' interpreter is judged without the caller's DEVELOPER_DIR (hooks do not have it)",
          st[0].ok is False, st)


# ---------------------------------------------------------------- agent runner and routines


def test_agent_runner():
    print("\n== CliAgentRunner, load_agent_command, TasksRegistrySource ==")
    d = tmpdir()
    out = os.path.join(d, "agent-args.txt")
    agent = write(os.path.join(d, "agent"),
                  '#!/bin/sh\nprintf "%%s\\n" "$@" > "%s"\necho agent-ran\n[ "$1" = "--fail" ] && exit 3\nexit 0\n' % out,
                  mode=0o755)
    routine = write(os.path.join(d, "routine.md"),
                    "---\nid: r\nneeds_bridge: none\n---\n\nDo the thing, carefully.\n")

    r = AD.CliAgentRunner('%s -p {prompt} --file {prompt_file}' % agent, cwd=d)
    check("an agent command whose binary exists is available", r.available())
    rc, so, se = r.run(routine, timeout=20)
    args = open(out).read().splitlines()
    check("the agent runs and its exit code and output come back", rc == 0 and "agent-ran" in so, (rc, so, se))
    check("{prompt} becomes the routine body without its frontmatter, as one argument",
          args[1] == "Do the thing, carefully." and "needs_bridge" not in open(out).read(), args)
    check("{prompt_file} becomes the routine's path", args[3] == routine, args)

    rc, _, _ = AD.CliAgentRunner('%s --fail' % agent, cwd=d).run(routine, timeout=20)
    check("a failing agent's exit code comes back", rc == 3, rc)

    missing = AD.CliAgentRunner('/nonexistent/agent-cli -p {prompt}', cwd=d)
    check("an agent whose binary does not exist is not available", not missing.available())
    rc, _, se = missing.run(routine, timeout=20)
    check("running it is exit 127 with a reason, not an exception", rc == 127 and se, (rc, se))

    empty = AD.CliAgentRunner("", cwd=d)
    rc, _, se = empty.run(routine, timeout=20)
    check("no configured agent command is exit 127 saying so",
          not empty.available() and rc == 127 and "agent command" in se, (rc, se))

    slow = write(os.path.join(d, "slow"), "#!/bin/sh\nsleep 5\n", mode=0o755)
    rc, _, se = AD.CliAgentRunner(slow, cwd=d).run(routine, timeout=1)
    check("an agent past its timeout is exit 124", rc == 124, (rc, se))

    vault = tmpdir()
    write(os.path.join(vault, "90-Meta", "agent-command.txt"),
          "# the agent adapter\n\nsome-agent --print {prompt}\n")
    check("the agent command is read from the vault's configuration file",
          AD.load_agent_command(vault, {}) == "some-agent --print {prompt}")
    check("BRAIN_AGENT_CMD overrides the file",
          AD.load_agent_command(vault, {"BRAIN_AGENT_CMD": "other {prompt}"}) == "other {prompt}")
    check("no file and no variable is an empty command", AD.load_agent_command(tmpdir(), {}) == "")

    fake_tasks = types.SimpleNamespace(host=lambda: "box", read_registry=lambda: [{"id": "a"}],
                                       load_state=lambda: {"a": {"last_exit": 0}})
    src = AD.TasksRegistrySource(fake_tasks)
    check("the routine source reads the task runner's registry and state",
          src.host() == "box" and src.routines() == [{"id": "a"}] and src.last_runs() == {"a": {"last_exit": 0}})
    fake_tasks.machine_is_mine = lambda m: m == "box-1a2b3c4d"
    check("the routine source answers 'is this machine mine' with the task runner's identity check",
          src.is_mine("box-1a2b3c4d") and not src.is_mine("other"))


# ---------------------------------------------------------------- mail


class RecordingMailer:
    def __init__(self, fail_times=0, error=None):
        self.sent = []
        self.fail_times = fail_times
        self.error = error

    def send(self, to, subject, body):
        if self.fail_times:
            self.fail_times -= 1
            raise self.error or P.MailUnavailable("offline")
        self.sent.append((to, subject, body))


def test_mail_queue():
    print("\n== FileMailQueue ==")
    d = tmpdir()
    logs = []
    now = [1_000_000.0]
    path = os.path.join(d, "q", "outbox.json")

    q = MQ.FileMailQueue(path, mailer=None, log=logs.append, now=lambda: now[0])
    q.enqueue("me@example.com", "s1", "b1")
    q.enqueue("me@example.com", "s2", "b2")
    check("a disabled outbox is not enabled", q.enabled() is False)
    sent, kept = q.flush()
    check("a disabled outbox sends nothing and keeps everything", (sent, kept) == (0, 2), (sent, kept))
    check("and logs that mail is disabled", any("disabled" in l for l in logs), logs)
    now[0] += 120
    check("pending and oldest age are reported", q.pending() == 2 and q.oldest_age_s() == 120,
          (q.pending(), q.oldest_age_s()))

    m = RecordingMailer(fail_times=1)
    q2 = MQ.FileMailQueue(path, mailer=m, log=logs.append, now=lambda: now[0])
    sent, kept = q2.flush()
    check("when the mailer is unavailable the first message stays queued and flush stops",
          (sent, kept) == (0, 2) and m.sent == [], (sent, kept, m.sent))
    check("the queue survives on disk for the next run", q2.pending() == 2)
    sent, kept = q2.flush()
    check("the next run sends everything, oldest first",
          (sent, kept) == (2, 0) and [s for _, s, _ in m.sent] == ["s1", "s2"], (sent, kept, m.sent))
    check("a sent message leaves the queue", q2.pending() == 0 and q2.oldest_age_s() is None)

    m = RecordingMailer(fail_times=1, error=RuntimeError("unexpected bug"))
    q3 = MQ.FileMailQueue(path, mailer=m, log=logs.append, now=lambda: now[0])
    q3.enqueue("me@example.com", "s3", "b3")
    _, exc = outcome(q3.flush)
    check("even an unexpected mailer error never escapes flush", exc is None, repr(exc))
    check("and the message is kept", q3.pending() == 1)

    q4 = MQ.FileMailQueue(path, mailer=RecordingMailer(), log=logs.append, now=lambda: now[0],
                          max_age_s=3600)
    now[0] += 7200
    sent, kept = q4.flush()
    check("messages older than the maximum age are dropped, not sent", (sent, kept) == (0, 0), (sent, kept))
    check("and the drop is logged", any("dropped" in l for l in logs), logs)

    q5 = MQ.FileMailQueue(path, mailer=None, log=logs.append, now=lambda: now[0], max_messages=3)
    for i in range(5):
        q5.enqueue("me@example.com", "m%d" % i, "b")
    check("the queue is bounded, keeping the newest", q5.pending() == 3)

    write(path, "{corrupt")
    q6 = MQ.FileMailQueue(path, mailer=None, log=logs.append, now=lambda: now[0])
    _, exc = outcome(q6.enqueue, "me@example.com", "after corruption", "b")
    check("a corrupt queue file does not stop new messages", exc is None and q6.pending() == 1, repr(exc))

    blocked = os.path.join(d, "not-a-dir")
    write(blocked, "file in the way")
    q7 = MQ.FileMailQueue(os.path.join(blocked, "outbox.json"), mailer=None, log=logs.append)
    _, exc = outcome(q7.enqueue, "me@example.com", "s", "b")
    check("an outbox that cannot write never raises", exc is None, repr(exc))


class FakeResponse(io.BytesIO):
    status = 200


def test_gmail_mailer():
    print("\n== GmailApiMailer and build_mailer ==")
    seen = {}

    def ok_urlopen(req, timeout=None):
        seen.update(req=req, timeout=timeout)
        return FakeResponse(b'{"id": "abc"}')

    m = ML.GmailApiMailer(sender="me@example.com", token_provider=lambda: "tok-1",
                          urlopen=ok_urlopen, timeout=11)
    _, exc = outcome(m.send, "me@example.com", "Brain guardian: 1 new", "NEW [fail] x")
    req = seen.get("req")
    check("a send posts to the Gmail API send endpoint",
          exc is None and req is not None and req.get_method() == "POST"
          and req.full_url == "https://gmail.googleapis.com/gmail/v1/users/me/messages/send", (exc, req))
    check("with the bearer token", req.get_header("Authorization") == "Bearer tok-1")
    check("bounded by the timeout", seen.get("timeout") == 11)
    raw = json.loads(req.data.decode())["raw"]
    msg = email.message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    check("the message carries sender, recipient, subject and body",
          msg["From"] == "me@example.com" and msg["To"] == "me@example.com"
          and msg["Subject"] == "Brain guardian: 1 new" and "NEW [fail] x" in msg.get_payload(decode=True).decode(),
          dict(msg.items()))

    calls = []

    def never(req, timeout=None):
        calls.append(req)
        raise AssertionError("must not be called")

    def no_scope():
        raise RuntimeError("the personal Google token lacks the gmail.send scope")

    _, exc = outcome(ML.GmailApiMailer("me@example.com", no_scope, urlopen=never).send, "a", "b", "c")
    check("a token without the send scope is MailUnavailable and nothing is posted",
          isinstance(exc, P.MailUnavailable) and "gmail.send" in str(exc) and calls == [], repr(exc))

    def forbidden(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {},
                                     io.BytesIO(b'{"error": {"message": "insufficient scopes"}}'))

    _, exc = outcome(ML.GmailApiMailer("me@example.com", lambda: "t", urlopen=forbidden).send, "a", "b", "c")
    check("a refused send is MailUnavailable with the status", isinstance(exc, P.MailUnavailable)
          and "403" in str(exc), repr(exc))

    def offline(req, timeout=None):
        raise urllib.error.URLError("no route")

    _, exc = outcome(ML.GmailApiMailer("me@example.com", lambda: "t", urlopen=offline).send, "a", "b", "c")
    check("no network is MailUnavailable", isinstance(exc, P.MailUnavailable), repr(exc))

    d = tmpdir()
    check("a missing mail config is disabled",
          ML.load_mail_config(os.path.join(d, "none.json"))["enabled"] is False)
    write(os.path.join(d, "bad.json"), "{nope")
    check("a corrupt mail config is disabled", ML.load_mail_config(os.path.join(d, "bad.json"))["enabled"] is False)
    cfg = {"enabled": True, "adapter": "gmail-api", "from": "me@example.com", "to": "me@example.com"}
    check("a gmail-api config that names no google.py account builds no mailer", ML.build_mailer(cfg) is None)
    check("disabled config builds no mailer", ML.build_mailer(dict(cfg, enabled=False)) is None)
    check("an unknown adapter builds no mailer", ML.build_mailer(dict(cfg, adapter="smoke-signals")) is None)
    check("a config without sender builds no mailer", ML.build_mailer(dict(cfg, **{"from": ""})) is None)
    built = ML.build_mailer(cfg, token_provider=lambda: "t")
    check("an enabled gmail-api config builds the Gmail API mailer",
          isinstance(built, ML.GmailApiMailer), built)

    q = MQ.FileMailQueue(os.path.join(d, "outbox.json"),
                         mailer=ML.GmailApiMailer("me@example.com", no_scope, urlopen=never), log=lambda s: None)
    q.enqueue("me@example.com", "s", "b")
    _, exc = outcome(q.flush)
    check("through the queue, a token without scope keeps the message and never raises",
          exc is None and q.pending() == 1 and calls == [], (repr(exc), q.pending()))


def test_token_pool_probe():
    print("\n== TokenPoolProbe ==")
    from guardian_core import domain as D

    d = tmpdir()
    pool_path = write(os.path.join(d, "vault", "90-Meta", "routine-tokens.json"), json.dumps({"tokens": [
        {"label": "routines-1", "account": "routines", "kp_ref": "kp://Brain/apis/claude-code-oauth-routines-1",
         "issued": "2026-09-15"},
        {"label": "routines-2", "account": "spare", "kp_ref": "kp://Brain/apis/claude-code-oauth-routines-2",
         "issued": "2026-01-10"}]}))
    state_path = write(os.path.join(d, "state", "routine-auth-state.json"), json.dumps({
        "routines-1": {"status": "dead", "until": None, "last_kind": "auth_invalid",
                       "last_at": "2026-09-15T12:00:00", "detail": "401"}}))
    tp = AD.TokenPoolProbe(pool_path, state_path).pool()
    check("the probe returns every pool token in order", [t.label for t in tp.tokens] == ["routines-1", "routines-2"]
          and tp.config_error is None, tp)
    first, second = tp.tokens
    check("with the state routine_auth_core recorded", first.status == "dead" and first.last_kind == "auth_invalid"
          and first.last_at == "2026-09-15T12:00:00", first)
    check("a token with no state is healthy", second.status == "healthy" and second.account == "spare", second)
    check("each token carries its expiry date", first.expires == "2027-09-15" and second.expires == "2027-01-10",
          (first.expires, second.expires))
    check("and the exact renewal and re-store commands",
          'kp.py set "apis/claude-code-oauth-routines-1" --stdin' in first.restore
          and first.renew.startswith("claude setup-token") and first.restore in first.renew, (first.renew, first.restore))

    tp = AD.TokenPoolProbe(os.path.join(d, "nope.json"), state_path).pool()
    check("no pool file on this machine is an empty pool, not an error", tp.tokens == [] and tp.config_error is None, tp)
    bad = write(os.path.join(d, "bad.json"), json.dumps({"tokens": [{"label": "x", "kp_ref": "kp://Brain/x",
                                                                       "issued": "2026-09-15", "value": "nope"}]}))
    tp = AD.TokenPoolProbe(bad, state_path).pool()
    check("an invalid pool file is a config error saying why", tp.tokens == [] and "unknown key" in (tp.config_error or ""),
          tp)
    tp = AD.TokenPoolProbe(pool_path, os.path.join(d, "missing-state.json")).pool()
    check("no state yet means every token is healthy", [t.status for t in tp.tokens] == ["healthy", "healthy"], tp)
    check("the probe is read-only", not os.path.exists(os.path.join(d, "missing-state.json")))


def test_desktop_tasks_probe():
    print("\n== DesktopScheduledTasksProbe ==")
    d = tmpdir()
    base = os.path.join(d, "Claude", "claude-code-sessions")
    write(os.path.join(base, "acct-1111", "sess-a", "scheduled-tasks.json"), json.dumps({"scheduledTasks": [
        {"id": "daily-digest", "displayName": "Daily", "cronExpression": "0 6 * * *", "enabled": True,
         "filePath": "/x/SKILL.md", "cwd": "/y"},
        {"id": "digest-now", "enabled": False}]}))
    write(os.path.join(base, "acct-2222", "sess-b", "scheduled-tasks.json"), "{broken")
    write(os.path.join(base, "acct-2222", "sess-c", "scheduled-tasks.json"),
          json.dumps({"scheduledTasks": [{"id": "example-routine-b", "enabled": True}, "junk"]}))
    before = {p: os.path.getmtime(os.path.join(r, p)) for r, _, fs in os.walk(base) for p in fs}
    got = sorted(AD.DesktopScheduledTasksProbe(base).enabled())
    check("every enabled Claude app task, per account, across sessions",
          got == [("daily-digest", "acct-1111"), ("example-routine-b", "acct-2222")], got)
    check("an unreadable sessions file is skipped, not fatal", True)
    check("the probe writes nothing",
          before == {p: os.path.getmtime(os.path.join(r, p)) for r, _, fs in os.walk(base) for p in fs})
    check("no Claude app sessions directory is no tasks",
          AD.DesktopScheduledTasksProbe(os.path.join(d, "nope")).enabled() == [])


def test_routine_meta_source():
    print("\n== TasksRegistrySource.meta ==")
    d = tmpdir()
    write(os.path.join(d, "90-Meta", "routines", "r.md"),
          "---\nid: routine-r\napp_task: daily-digest\nneeds_bridge: [email]\n---\n\nbody\n")
    src = AD.TasksRegistrySource(types.SimpleNamespace(VAULT=d))
    check("a routine row's frontmatter is read from the vault the task runner uses",
          src.meta({"command": "90-Meta/routines/r.md"})
          == {"app_task": "daily-digest", "needs_bridge": ["email"], "permission_problem": None},
          src.meta({"command": "90-Meta/routines/r.md"}))
    check("a missing routine file is no metadata",
          src.meta({"command": "90-Meta/routines/missing.md"})
          == {"app_task": None, "needs_bridge": [], "permission_problem": None})
    write(os.path.join(d, "90-Meta", "routines", "open.md"),
          '---\nid: routine-open\nagent_args: ["--permission-mode", "acceptEdits", "--allowedTools", "Read,Bash"]\n---\n')
    problem = src.meta({"command": "90-Meta/routines/open.md"})["permission_problem"]
    check("agent_args granting bare Bash come back as a permission problem, judged by routine_auth_core",
          problem and "Bash" in problem, problem)
    write(os.path.join(d, "90-Meta", "routines", "narrow.md"),
          '---\nagent_args: ["--allowedTools", "Read,Bash(python3 ~/Brain/_bin/vw.py append:*)"]\n---\n')
    check("narrow Bash patterns are no problem",
          src.meta({"command": "90-Meta/routines/narrow.md"})["permission_problem"] is None)


# ---------------------------------------------------------------- hook liveness and the probe


def test_hook_liveness_source():
    print("\n== HookLivenessSource ==")
    import time
    from guardian_core import adapters as A_
    from guardian_core import domain as D_

    if not hasattr(A_, "HookLivenessSource"):
        check("guardian_core.adapters has HookLivenessSource", False)
        return
    d = tmpdir()
    now = time.time()
    projects = os.path.join(d, "projects")
    app = os.path.join(projects, "-Users-me-code-app")
    write(os.path.join(app, "3ac18522-ed92-4c1a-9d0e-000000000001.jsonl"), '{"type": "user"}\n')
    old = write(os.path.join(app, "0dd00000-0000-4000-8000-000000000002.jsonl"), "{}\n")
    os.utime(old, (now - 10000, now - 10000))
    write(os.path.join(app, "3ac18522-ed92-4c1a-9d0e-000000000001", "subagents", "agent-1.jsonl"), "{}\n")
    write(os.path.join(app, "notes.txt"), "x")

    log = os.path.join(d, "state", "logs", "heartbeat.jsonl")

    def rec(ago, status="ok"):
        return json.dumps({"ts": now - ago, "event": "prompt-submit", "sid": "3ac18522", "status": status,
                           "exit": 0, "exc": "", "ms": 5, "hook_event": "UserPromptSubmit"})

    write(log + ".2", rec(900) + "\n")
    os.utime(log + ".2", (now - 5000, now - 5000))
    write(log + ".1", rec(3000) + "\n" + rec(1500) + "\n")
    os.utime(log + ".1", (now - 1400, now - 1400))
    write(log, rec(60) + "\nnot json\n" + json.dumps({"ts": "x"}) + "\n" + rec(30, "error") + "\n")
    registry = write(os.path.join(d, "events.json"), json.dumps({"version": 1, "events": [
        {"id": "session-start", "description": "s", "handler": "compass", "liveness": "session",
         "triggers": [{"kind": "claude-hook", "event": "SessionStart", "command": "compass.py", "timeout": 8},
                      {"kind": "cli", "command": "brain session-start"}]},
        {"id": "sync", "description": "s", "handler": "vault_sync",
         "triggers": [{"kind": "claude-hook", "event": "Stop", "command": "vault_sync.py --hook"}]},
        {"id": "reindex", "description": "r", "handler": "index_vault",
         "triggers": [{"kind": "file-watch", "action": "index-trigger", "command": "index_vault.py"}]}]}))
    epoch = os.path.join(d, "state", "hook-liveness.json")
    src = A_.HookLivenessSource(projects_dir=projects, heartbeat_log=log, registry_path=registry, epoch_path=epoch)

    ss = src.sessions(now - 3600)
    check("top-level transcripts written since the horizon are sessions, keyed by short id",
          [(x.sid, x.project_dir) for x in ss] == [("3ac18522", "-Users-me-code-app")], ss)
    check("with a start time no later than their last write", ss and ss[0].started <= ss[0].mtime, ss)
    check("a missing projects directory is no sessions",
          A_.HookLivenessSource(os.path.join(d, "nope"), log, registry, os.path.join(d, "e")).sessions(0) == [])

    hbs = src.heartbeats(now - 2000)
    check("heartbeats since the horizon, oldest first, across rotated files",
          [round(now - h.ts) for h in hbs] == [1500, 60, 30], [now - h.ts for h in hbs])
    check("malformed lines are skipped", all(isinstance(h, D_.Heartbeat) for h in hbs))
    check("a rotated file last written before the horizon is not read", not any(round(now - h.ts) == 900 for h in hbs))

    specs = src.events()
    check("the registry's Claude Code hooks become event specs: hook event, identity and liveness (regular when unsaid)",
          [(x.id, x.hook_event, x.identity, x.liveness) for x in specs]
          == [("session-start", "SessionStart", "compass.py", "session"), ("sync", "Stop", "vault_sync.py --hook", "regular")],
          specs)
    check("no epoch until one is started", src.epoch() is None)
    check("starting it records the time", src.start_epoch(1000.0) == 1000.0 and src.epoch() == 1000.0)
    check("starting it again keeps the first", src.start_epoch(2000.0) == 1000.0 and src.epoch() == 1000.0)
    check("the default window is thirty minutes", src.config().window_s == 1800, src.config())
    cfg = write(os.path.join(d, "cfg.json"), json.dumps({"window_min": 45, "silent_days": 3}))
    src2 = A_.HookLivenessSource(projects, log, registry, os.path.join(d, "e2"), config_path=cfg)
    check("an optional config file sets the windows",
          src2.config().window_s == 2700 and src2.config().silent_s == 3 * 86400, src2.config())


def test_hook_probe():
    print("\n== HookProbe ==")
    from guardian_core import adapters as A_
    from guardian_core import claude_code as CC
    from guardian_core import domain as D_

    if not hasattr(A_, "HookProbe"):
        check("guardian_core.adapters has HookProbe", False)
        return

    class Canonical:
        def __init__(self, hooks, path="/v/integrations/claude-code/plugin/brain/hooks/hooks.json"):
            self.hooks, self.path = hooks, path

        def load(self):
            return self.hooks

    class Events:
        def __init__(self, specs):
            self.specs = specs

        def events(self):
            return list(self.specs)

    specs = [D_.HookEventSpec("session-start", "SessionStart", "compass.py", "session"),
             D_.HookEventSpec("pre-write-gate", "PreToolUse", "gate_write.py", "regular")]
    hooks = {"SessionStart": [{"hooks": [{"type": "command", "command": "/usr/bin/python3 /v/_bin/compass.py", "timeout": 8}]}],
             "PreToolUse": [{"matcher": "Write", "hooks": [
                 {"type": "command", "command": "/usr/bin/python3 /v/_bin/gate_write.py", "timeout": 5}]}]}
    calls = []
    ctx = '{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "# Brain"}}'

    def fake_run(argv, **kw):
        calls.append((list(argv), kw))
        return types.SimpleNamespace(returncode=0, stdout=ctx if argv[-1].endswith("compass.py") else "", stderr="")

    root = tmpdir()
    old_dev = os.environ.get("DEVELOPER_DIR")
    os.environ["DEVELOPER_DIR"] = "/Library/Developer/CommandLineTools"
    try:
        probe = A_.HookProbe(Canonical(hooks), Events(specs), run=fake_run, scratch_root=root)
        check("a probe is built without running anything", probe.ran is False and calls == [])
        pairs = probe.results()
    finally:
        if old_dev is None:
            os.environ.pop("DEVELOPER_DIR", None)
        else:
            os.environ["DEVELOPER_DIR"] = old_dev
    check("every canonical Brain hook runs once, as an argv list (no shell)",
          [c[0] for c in calls] == [["/usr/bin/python3", "/v/_bin/compass.py"], ["/usr/bin/python3", "/v/_bin/gate_write.py"]],
          calls)
    check("and all pass", D_.probe_findings(pairs) == [], [(c.event_id, r) for c, r in pairs])
    env = (calls[0][1].get("env") or {}) if calls else {}
    check("in a scratch Brain state, vault and home under the probe's own temporary directory",
          all(str(env.get(k, "")).startswith(root) for k in ("BRAIN_STATE", "BRAIN_VAULT", "HOME", "TMPDIR")), env)
    check("offline, with no bytecode written beside the scripts and git discovery fenced in",
          env.get("BRAIN_OFFLINE") == "1" and env.get("PYTHONDONTWRITEBYTECODE") == "1"
          and str(env.get("GIT_CEILING_DIRECTORIES", "")).startswith(root), env)
    check("without the caller's DEVELOPER_DIR, as hooks run", "DEVELOPER_DIR" not in env, sorted(env))
    stdin = json.loads((calls[0][1].get("input") if calls else None) or "{}")
    check("fed the canned SessionStart payload under the probe session id",
          stdin.get("session_id") == D_.PROBE_SESSION_ID and stdin.get("hook_event_name") == "SessionStart", stdin)
    check("with the hook's timeout", [c[1].get("timeout") for c in calls] == [8, 5], [c[1].get("timeout") for c in calls])
    probe.results()
    check("results are kept for the process: status and check do not run it twice",
          len(calls) == 2 and probe.ran is True, len(calls))
    check("the scratch directory is removed afterwards", os.listdir(root) == [], os.listdir(root))

    def timeout_run(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw.get("timeout"))

    def missing_run(argv, **kw):
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    r = A_.HookProbe(Canonical(hooks), Events(specs), run=timeout_run, scratch_root=tmpdir()).results()
    check("a hook that runs past its timeout is reported timed out", r and all(res.timed_out for _c, res in r), r)
    r = A_.HookProbe(Canonical(hooks), Events(specs), run=missing_run, scratch_root=tmpdir()).results()
    check("an interpreter that is not there is reported with the reason",
          r and all("No such file" in res.error for _c, res in r), r)

    d = tmpdir()
    broken = write(os.path.join(d, "_bin", "compass.py"), "def main(:\n    pass\n")
    good = write(os.path.join(d, "_bin", "gate_write.py"), "import json, sys\njson.load(sys.stdin)\nsys.exit(0)\n")
    real_hooks = {"SessionStart": [{"hooks": [{"type": "command", "command": "%s %s" % (sys.executable, broken), "timeout": 8}]}],
                  "PreToolUse": [{"hooks": [{"type": "command", "command": "%s %s" % (sys.executable, good), "timeout": 8}]}]}
    fs = D_.probe_findings(A_.HookProbe(Canonical(real_hooks), Events(specs)).results())
    check("a hook script broken in a scratch copy fails the probe, with the reason",
          [f.key for f in fs] == ["hooks:probe:session-start"] and "SyntaxError" in fs[0].summary, fs)

    vault = os.path.dirname(os.path.dirname(HERE))
    # home=ORIGIN_HOME leaves the home part alone: this checkout may itself live under the origin home,
    # and the probe gives every hook a scratch HOME anyway.
    canonical = CC.CanonicalHooksFile(os.path.join(vault, "integrations", "claude-code", "plugin", "brain", "hooks", "hooks.json"),
                                      vault=vault, home=D_.ORIGIN_HOME)
    events = A_.HookLivenessSource(os.path.join(d, "projects"), os.path.join(d, "hb.jsonl"),
                                   os.path.join(vault, "90-Meta", "events.json"), os.path.join(d, "epoch.json"))
    pairs = A_.HookProbe(canonical, events).results()
    bad = [(c.event_id, D_.probe_verdict(c, r), r.stderr[-300:]) for c, r in pairs if D_.probe_verdict(c, r)]
    check("this checkout's eleven hooks, run the way Claude Code runs them in a scratch state, all pass",
          len(pairs) == 11 and bad == [], (len(pairs), bad))


FAKE_SYSTEMCTL = r"""#!/bin/sh
echo "$*" >> "%(log)s"
case "$*" in
  "--user is-active --quiet second-brain-loaded.timer") exit 0 ;;
  "--user is-active --quiet second-brain-server.service") exit 0 ;;
  "--user show second-brain-loaded.service --property=Result --property=ExecMainStatus") printf 'Result=success\nExecMainStatus=0\n'; exit 0 ;;
  "--user show second-brain-failed.service --property=Result --property=ExecMainStatus") printf 'Result=exit-code\nExecMainStatus=1\n'; exit 0 ;;
  "--user daemon-reload") exit 0 ;;
  "--user enable --now "*) exit 0 ;;
  "--user restart "*) exit 0 ;;
esac
exit 3
"""
SERVICE_TEMPLATE = ("[Service]\nType=oneshot\nEnvironment=BRAIN_JOB_LABEL=%(label)s\n"
                    "ExecStart=/bin/sh /home/brain-origin/Brain/_bin/pywrap.sh /home/brain-origin/Brain/_bin/guardian.py repair\n")
TIMER_TEMPLATE = "[Timer]\nOnUnitActiveSec=15min\n[Install]\nWantedBy=timers.target\n"


def test_systemd():
    print("\n== SystemdUserControl ==")
    d = tmpdir()
    vault, home = os.path.join(d, "Vault"), os.path.join(d, "Home")
    units = os.path.join(home, ".config", "systemd", "user")
    log = os.path.join(d, "systemctl.log")
    fake = write(os.path.join(d, "systemctl"), FAKE_SYSTEMCTL % {"log": log}, mode=0o755)
    for label in ("second-brain-loaded", "second-brain-failed", "second-brain-missing"):
        write(os.path.join(vault, "_bin", "systemd", label + ".service"), SERVICE_TEMPLATE % {"label": label})
        write(os.path.join(vault, "_bin", "systemd", label + ".timer"), TIMER_TEMPLATE)
    sc = AD.SystemdUserControl(vault=vault, home=home, systemctl=fake, backup_dir=os.path.join(d, "backups"),
                               environ={}, clock=StepClock())
    check("the jobs are the timers the vault carries",
          sc.labels() == ["second-brain-failed", "second-brain-loaded", "second-brain-missing"], sc.labels())
    check("consent narrows them to the jobs the user accepted",
          AD.SystemdUserControl(vault=vault, home=home, systemctl=fake,
                                allowed=["second-brain-loaded"]).labels() == ["second-brain-loaded"])
    check("nothing is installed before install", not sc.installed("second-brain-missing"))
    done, detail = sc.install("second-brain-missing")
    svc = os.path.join(units, "second-brain-missing.service")
    check("install writes the service and the timer into ~/.config/systemd/user",
          done and os.path.exists(svc) and os.path.exists(os.path.join(units, "second-brain-missing.timer")), detail)
    text = open(svc).read() if os.path.exists(svc) else ""
    check("the vault path is rendered into the unit",
          "/home/brain-origin/Brain" not in text and vault + "/_bin/pywrap.sh" in text, text)
    calls = open(log).read() if os.path.exists(log) else ""
    check("install reloads the systemd user manager", "--user daemon-reload" in calls, calls)
    done, detail = sc.bootstrap("second-brain-missing")
    calls = open(log).read() if os.path.exists(log) else ""
    check("bootstrap enables and starts the timer",
          done and "--user enable --now second-brain-missing.timer" in calls, calls)
    check("an active timer is loaded", sc.is_loaded("second-brain-loaded") and not sc.is_loaded("second-brain-missing"))
    check("a successful last run is ok", sc.last_exit_ok("second-brain-loaded")[0] is True)
    good, detail = sc.last_exit_ok("second-brain-failed")
    check("a failed last run is not ok, and says so", good is False and "exit-code" in detail, detail)
    write(svc, text.replace("pywrap.sh", "old-python"))
    check("a unit that differs from the template has drifted", sc.drifted("second-brain-missing"))
    done, detail = sc.reinstall("second-brain-missing")
    check("reinstall rewrites it and names the backup",
          done and not sc.drifted("second-brain-missing") and "backups" in detail, detail)
    check("self_label comes from the unit's BRAIN_JOB_LABEL",
          AD.SystemdUserControl(vault=vault, environ={"BRAIN_JOB_LABEL": "second-brain-guardian"}).self_label()
          == "second-brain-guardian")


SERVER_TEMPLATE = ("[Service]\nType=simple\nEnvironment=BRAIN_JOB_LABEL=%(label)s\nRestart=always\n"
                   "ExecStart=/bin/sh /home/brain-origin/Brain/_bin/pywrap.sh /home/brain-origin/Brain/_bin/server.py\n"
                   "[Install]\nWantedBy=default.target\n")


def test_systemd_long_lived():
    print("\n== SystemdUserControl: a long-lived service with no timer ==")
    d = tmpdir()
    vault, home = os.path.join(d, "Vault"), os.path.join(d, "Home")
    units = os.path.join(home, ".config", "systemd", "user")
    log = os.path.join(d, "systemctl.log")
    fake = write(os.path.join(d, "systemctl"), FAKE_SYSTEMCTL % {"log": log}, mode=0o755)
    write(os.path.join(vault, "_bin", "systemd", "second-brain-loaded.service"),
          SERVICE_TEMPLATE % {"label": "second-brain-loaded"})
    write(os.path.join(vault, "_bin", "systemd", "second-brain-loaded.timer"), TIMER_TEMPLATE)
    write(os.path.join(vault, "_bin", "systemd", "second-brain-server.service"),
          SERVER_TEMPLATE % {"label": "second-brain-server"})
    sc = AD.SystemdUserControl(vault=vault, home=home, systemctl=fake, backup_dir=os.path.join(d, "backups"),
                               environ={}, clock=StepClock())
    check("a service with no timer is still a job, next to the timed ones",
          sc.labels() == ["second-brain-loaded", "second-brain-server"], sc.labels())
    check("its units are the service alone", list(sc.render("second-brain-server")) == ["second-brain-server.service"],
          list(sc.render("second-brain-server")))
    done, detail = sc.install("second-brain-server")
    check("install writes the service, and no timer",
          done and os.path.exists(os.path.join(units, "second-brain-server.service"))
          and not os.path.exists(os.path.join(units, "second-brain-server.timer")), detail)
    check("install names the service it wrote", detail.endswith("second-brain-server.service"), detail)
    check("an installed service with no timer counts as installed", sc.installed("second-brain-server"))
    done, detail = sc.bootstrap("second-brain-server")
    calls = open(log).read() if os.path.exists(log) else ""
    check("bootstrap enables and starts the service itself, not a timer",
          done and "--user enable --now second-brain-server.service" in calls
          and "second-brain-server.timer" not in calls, calls)
    check("a running service is loaded", sc.is_loaded("second-brain-server"))
    svc = os.path.join(units, "second-brain-server.service")
    write(svc, open(svc).read().replace("Restart=always", "Restart=no"))
    check("a service that differs from its template has drifted", sc.drifted("second-brain-server"))
    open(log, "w").close()
    done, detail = sc.reinstall("second-brain-server")
    calls = open(log).read()
    check("reinstall rewrites it and restarts the service, since it was running",
          done and not sc.drifted("second-brain-server") and "--user restart second-brain-server.service" in calls
          and ".timer" not in calls, (detail, calls))
    check("a timed job still bootstraps through its timer",
          sc.bootstrap("second-brain-loaded")[0] and "--user enable --now second-brain-loaded.timer" in open(log).read())


FAKE_CRONTAB = r"""#!/bin/sh
TAB="%(tab)s"
if [ "$1" = "-l" ]; then
  if [ -f "$TAB" ]; then cat "$TAB"; exit 0; fi
  echo "no crontab for user" >&2; exit 1
fi
if [ "$1" = "-" ]; then cat > "$TAB"; exit 0; fi
exit 2
"""


def test_cron():
    print("\n== CronControl ==")
    d = tmpdir()
    vault, tab = os.path.join(d, "Vault"), os.path.join(d, "tab")
    fake = write(os.path.join(d, "crontab"), FAKE_CRONTAB % {"tab": tab}, mode=0o755)
    for label, when in (("second-brain-guardian", "*/15 * * * *"), ("second-brain-sync", "*/10 * * * *")):
        write(os.path.join(vault, "_bin", "cron", label + ".cron"),
              "# comment\n%s /bin/sh /home/brain-origin/Brain/_bin/pywrap.sh /home/brain-origin/Brain/_bin/x.py\n" % when)
    write(tab, "0 3 * * * /usr/bin/backup-my-photos\n")
    cc = AD.CronControl(vault=vault, home=os.path.join(d, "Home"), crontab=fake, environ={})
    check("the jobs are the cron templates the vault carries",
          cc.labels() == ["second-brain-guardian", "second-brain-sync"], cc.labels())
    check("a job not in the crontab is not installed", not cc.installed("second-brain-guardian"))
    done, detail = cc.install("second-brain-guardian")
    body = open(tab).read()
    check("install adds the job inside Brain's own block",
          done and AD.CRON_BEGIN in body and "# brain:second-brain-guardian" in body
          and body.index(AD.CRON_BEGIN) < body.index("# brain:second-brain-guardian") < body.index(AD.CRON_END), body)
    check("the user's own lines are left as they were", body.startswith("0 3 * * * /usr/bin/backup-my-photos\n"), body)
    check("the vault path is rendered into the line", vault + "/_bin/pywrap.sh" in body and "/home/brain-origin/Brain" not in body, body)
    check("an installed cron job counts as loaded and needs no load step",
          cc.installed("second-brain-guardian") and cc.is_loaded("second-brain-guardian")
          and cc.bootstrap("second-brain-guardian")[0])
    cc.install("second-brain-sync")
    cc.install("second-brain-guardian")
    body = open(tab).read()
    check("installing again never duplicates a line or the block",
          body.count("# brain:second-brain-guardian") == 1 and body.count(AD.CRON_BEGIN) == 1, body)
    write(tab, body.replace("*/15", "*/30"))
    check("a line that differs from its template has drifted",
          cc.drifted("second-brain-guardian") and not cc.drifted("second-brain-sync"))
    done, _ = cc.reinstall("second-brain-guardian")
    check("reinstall puts the template's line back", done and not cc.drifted("second-brain-guardian"))
    check("cron keeps no exit status to judge", cc.last_exit_ok("second-brain-sync")[0] is True)
    check("consent narrows the jobs",
          AD.CronControl(vault=vault, crontab=fake, allowed=["second-brain-sync"]).labels() == ["second-brain-sync"])


def test_job_consent():
    print("\n== first-run consent decides which scheduled jobs exist ==")
    d = tmpdir()
    vault, state = os.path.join(d, "Vault"), os.path.join(d, "state")
    for label in ("com.secondbrain.guardian", "com.secondbrain.sync"):
        write(os.path.join(vault, "_bin", label + ".plist"), TEMPLATE % {"label": label})
    path = AD.first_run_state_path(state)
    check("the first-run answers live in the Brain state directory",
          path == os.path.join(state, "first-run.json"), path)
    check("with no first run nothing was accepted", AD.consented_jobs(path) == ("", []), AD.consented_jobs(path))
    jc = AD.build_job_control(vault, state, home=os.path.join(d, "Home"))
    check("and the guardian manages no scheduled job at all", jc.labels() == [], jc.labels())
    write(path, json.dumps({"version": 1, "scheduler": {"kind": "launchd", "jobs": ["guardian", "made-up"]}}))
    check("only known jobs the user accepted count",
          AD.consented_jobs(path) == ("launchd", ["guardian"]), AD.consented_jobs(path))
    jc = AD.build_job_control(vault, state, home=os.path.join(d, "Home"))
    check("on launchd the accepted jobs are the com.secondbrain labels",
          isinstance(jc, AD.LaunchctlControl) and jc.labels() == ["com.secondbrain.guardian"], jc.labels())
    write(path, json.dumps({"scheduler": {"kind": "systemd", "jobs": ["sync"]}}))
    jc = AD.build_job_control(vault, state)
    check("on systemd the control is the user units, labelled second-brain-<job>",
          isinstance(jc, AD.SystemdUserControl) and jc.allowed == {"second-brain-sync"}, jc)
    write(path, json.dumps({"scheduler": {"kind": "cron", "jobs": ["tasks"]}}))
    check("on cron the control is the managed crontab block",
          isinstance(AD.build_job_control(vault, state), AD.CronControl))
    write(path, json.dumps({"scheduler": {"kind": "none", "jobs": ["guardian"]}}))
    check("a declined scheduler accepts no job", AD.consented_jobs(path) == ("", []), AD.consented_jobs(path))
    rc = {"status": "done", "kind": "systemd", "dir": "/home/u/workstation", "name": "workstation"}
    write(path, json.dumps({"scheduler": {"kind": "systemd", "jobs": ["sync"]}, "steps": {"remote_control": rc}}))
    check("a Remote Control server accepted at first run is one more job the guardian keeps",
          AD.consented_jobs(path) == ("systemd", ["sync", "remote-control"]), AD.consented_jobs(path))
    write(path, json.dumps({"scheduler": {"kind": "systemd", "jobs": []}, "steps": {"remote_control": rc}}))
    check("even when every periodic job was declined",
          AD.consented_jobs(path) == ("systemd", ["remote-control"]), AD.consented_jobs(path))
    write(path, json.dumps({"scheduler": {"kind": "none", "jobs": []}, "steps": {"remote_control": rc}}))
    check("and when the scheduler step was skipped, the server's own supervisor kind is used",
          AD.consented_jobs(path) == ("systemd", ["remote-control"]), AD.consented_jobs(path))
    write(path, json.dumps({"scheduler": {"kind": "launchd", "jobs": ["sync"]},
                            "steps": {"remote_control": dict(rc, kind="launchd")}}))
    jc = AD.build_job_control(vault, state, home=os.path.join(d, "Home"))
    check("on launchd its label is com.secondbrain.remote-control",
          jc.allowed == {"com.secondbrain.sync", "com.secondbrain.remote-control"}, jc.allowed)
    write(path, json.dumps({"scheduler": {"kind": "systemd", "jobs": ["sync", "remote-control"]},
                            "steps": {"remote_control": {"status": "declined"}}}))
    check("a declined Remote Control step installs no server, whatever the job list says",
          AD.consented_jobs(path) == ("systemd", ["sync"]), AD.consented_jobs(path))
    write(path, json.dumps({"scheduler": {"kind": "cron", "jobs": ["sync"]},
                            "steps": {"remote_control": dict(rc, kind="cron")}}))
    check("cron cannot supervise a server, so it never counts there",
          AD.consented_jobs(path) == ("cron", ["sync"]), AD.consented_jobs(path))


def test_linux_notifier():
    print("\n== NotifySendNotifier and the platform default ==")
    seen = []
    AD.NotifySendNotifier(run=lambda cmd, **kw: seen.append((cmd, kw))).notify("Brain guardian", "1 new")
    check("Linux notifications go through notify-send with title and message",
          seen and seen[0][0][0].endswith("notify-send") and seen[0][0][-2:] == ["Brain guardian", "1 new"]
          and seen[0][1].get("timeout"), seen)

    def exploding(cmd, **kw):
        raise OSError("no session bus")

    _, exc = outcome(AD.NotifySendNotifier(run=exploding).notify, "t", "m")
    check("a notifier with no desktop never raises", exc is None, repr(exc))
    check("macOS uses osascript, Linux notify-send",
          isinstance(AD.default_notifier("darwin"), AD.OsascriptNotifier)
          and isinstance(AD.default_notifier("linux"), AD.NotifySendNotifier))


def test_smtp_mailer():
    print("\n== SmtpMailer, the smtp config and the headless KeePass password ==")
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent.update(host=host, port=port, timeout=timeout, calls=[])

        def starttls(self, context=None):
            sent["calls"].append("starttls")

        def login(self, user, password):
            sent["calls"].append(("login", user, password))

        def send_message(self, msg):
            sent["msg"] = msg

        def quit(self):
            sent["calls"].append("quit")

    m = ML.SmtpMailer("me@example.com", "smtp.example.com", 587, "me@example.com", lambda: "app-pass", timeout=9,
                      smtp_factory=FakeSMTP)
    _, exc = outcome(m.send, "you@example.com", "Brain guardian: 1 new", "NEW [fail] x")
    msg = sent.get("msg")
    check("an smtp send connects to the configured host and port with the timeout",
          exc is None and sent.get("host") == "smtp.example.com" and sent.get("port") == 587
          and sent.get("timeout") == 9, (repr(exc), sent))
    check("it upgrades with STARTTLS before logging in, then quits",
          sent.get("calls", [])[:2] == ["starttls", ("login", "me@example.com", "app-pass")]
          and sent.get("calls", [None])[-1] == "quit", sent.get("calls"))
    check("the message carries sender, recipient and subject",
          msg is not None and msg["From"] == "me@example.com" and msg["To"] == "you@example.com"
          and msg["Subject"] == "Brain guardian: 1 new")

    def no_password():
        raise RuntimeError("KeePass locked")

    _, exc = outcome(ML.SmtpMailer("me@example.com", "h", 587, "u", no_password, smtp_factory=FakeSMTP).send,
                     "a", "b", "c")
    check("no password is MailUnavailable", isinstance(exc, P.MailUnavailable) and "password" in str(exc), repr(exc))

    class Refusing(FakeSMTP):
        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    _, exc = outcome(ML.SmtpMailer("me@example.com", "h", 587, "u", lambda: "p", smtp_factory=Refusing).send,
                     "a", "b", "c")
    check("a refused login is MailUnavailable", isinstance(exc, P.MailUnavailable) and "535" in str(exc), repr(exc))

    cfg = {"enabled": True, "adapter": "smtp", "from": "me@example.com", "to": "me@example.com",
           "smtp": {"host": "smtp.example.com", "port": 465, "user": "me@example.com",
                    "kp_ref": "kp://Brain/mail/smtp#Password", "security": "ssl"}}
    built = ML.build_mailer(cfg)
    check("an enabled smtp config builds the SMTP mailer with its port and security",
          isinstance(built, ML.SmtpMailer) and built.port == 465 and built.security == "ssl",
          built and vars(built))
    check("an smtp config with no host builds no mailer", ML.build_mailer(dict(cfg, smtp={})) is None)
    check("an smtp config with a user but no kp_ref builds no mailer",
          ML.build_mailer(dict(cfg, smtp={"host": "h", "user": "u"})) is None)

    d = tmpdir()
    log = os.path.join(d, "kp.log")
    fake_kp = write(os.path.join(d, "kp.py"),
                    "import os, sys\nopen(%r, 'a').write(' '.join(sys.argv[1:]) + ' NOPROMPT='"
                    " + os.environ.get('BRAIN_KP_NOPROMPT', '') + '\\n')\nprint('app-pass')\n" % log)
    value, exc = outcome(ML.kp_password_provider("kp://Brain/mail/smtp#Password", kp_path=fake_kp))
    logged = open(log).read() if os.path.exists(log) else ""
    check("the SMTP password is read through kp.py headless, by entry and attribute",
          exc is None and value == "app-pass" and "get Brain/mail/smtp -a Password" in logged
          and "NOPROMPT=1" in logged, (value, repr(exc), logged))
    fail_kp = write(os.path.join(d, "kpfail.py"), "import sys\nsys.exit(4)\n")
    _, exc = outcome(ML.kp_password_provider("kp://Brain/x", kp_path=fail_kp))
    check("a locked database is MailUnavailable, never a prompt",
          isinstance(exc, P.MailUnavailable) and "exit 4" in str(exc), repr(exc))

    sd, vd = tmpdir(), tmpdir()
    check("the mail config lives in the Brain state directory",
          ML.mail_config_path(sd, vd) == os.path.join(sd, "guardian-mail.json"), ML.mail_config_path(sd, vd))
    write(os.path.join(vd, "90-Meta", "guardian-mail.json"), "{}")
    check("a vault-local config is read only when the state one is missing",
          ML.mail_config_path(sd, vd) == os.path.join(vd, "90-Meta", "guardian-mail.json"))


def main():
    global AD, P, MQ, ML
    try:
        from guardian_core import adapters as AD
        from guardian_core import ports as P
        from guardian_core import mail_queue as MQ
        from guardian_core import mailer as ML
    except Exception as exc:
        check("guardian_core.adapters, mail_queue and mailer import", False,
              "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_launchd, test_launchd_drift, test_state_dir, test_notifier_state_paths,
                  test_raised_alerts, test_vault_probe, test_git_hooks, test_interpreter_probe, test_agent_runner,
                  test_mail_queue, test_gmail_mailer, test_token_pool_probe, test_desktop_tasks_probe,
                  test_routine_meta_source, test_hook_liveness_source, test_hook_probe,
                  test_systemd, test_systemd_long_lived, test_cron, test_job_consent, test_linux_notifier, test_smtp_mailer):
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
