#!/usr/bin/env python3
"""Tests for first_run_core.adapters: what the first run does to the machine, isolated.

Every test works under a temporary directory: a scratch HOME, vault and state, fake kp.py,
google.py and claude scripts, a fake crontab, and BRAIN_FAKE_SCHEDULER=1 so launchctl
and systemctl are never the real ones. Run standalone:

    python3 integrations/first-run/first_run_core/adapters_test.py
"""
import json
import os
import shutil
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[0] = os.path.dirname(HERE)
VAULT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(1, os.path.join(VAULT, "_bin"))

ok, fail = [], []
TMP = []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def tmpdir():
    d = tempfile.mkdtemp(prefix="first-run-adapters-")
    TMP.append(d)
    return d


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    if mode is not None:
        os.chmod(path, mode)
    return path


RECORDING_SCRIPT = r'''#!/usr/bin/env python3
import json, os, sys
stdin = "" if sys.stdin.isatty() else sys.stdin.read()
with open(%(log)r, "a") as fh:
    fh.write(json.dumps({"args": sys.argv[1:], "stdin": stdin,
                         "env": {k: v for k, v in os.environ.items() if k.startswith("BRAIN_")}}) + "\n")
sys.exit(%(rc)d)
'''


def recorder(d, name, rc=0):
    log = os.path.join(d, name + ".log")
    return write(os.path.join(d, name), RECORDING_SCRIPT % {"log": log, "rc": rc}), log


def calls(log):
    return [json.loads(l) for l in open(log)] if os.path.exists(log) else []


def test_files():
    print("\n== state and mail config files ==")
    d = tmpdir()
    store = AD.JsonStateStore(os.path.join(d, "state", "first-run.json"))
    check("no state file is a new state", store.load() == D.new_state())
    state = D.record(D.new_state(), "scheduler", "done", {"kind": "launchd"}, __import__("datetime").datetime.now())
    state["scheduler"] = D.scheduler_state("launchd", ["guardian"])
    store.save(state)
    check("the state round-trips", store.load() == state)
    check("and is private (0600)", stat.S_IMODE(os.stat(store.path).st_mode) == 0o600)
    import guardian_core.adapters as GA

    check("the guardian reads the accepted jobs from the same file",
          GA.consented_jobs(store.path) == ("launchd", ["guardian"]), GA.consented_jobs(store.path))
    mail = AD.MailConfigFile(os.path.join(d, "state", "guardian-mail.json"))
    path = mail.save({"enabled": True, "adapter": "smtp", "to": "me@example.com"})
    check("the mail config is written where the guardian reads it, private",
          path == mail.path and json.load(open(path))["adapter"] == "smtp"
          and stat.S_IMODE(os.stat(path).st_mode) == 0o600)


def test_kdbx_google():
    print("\n== kp.py and google.py ==")
    d = tmpdir()
    kp, kp_log = recorder(d, "kp.py")
    k = AD.KpKdbx(kp)
    good, _ = k.init(os.path.join(d, "creds.kdbx"), True)
    check("init runs kp.py init with the path and --create", good and calls(kp_log)[-1]["args"]
          == ["init", "--db", os.path.join(d, "creds.kdbx"), "--create"], calls(kp_log))
    k.unlock()
    check("unlock runs kp.py unlock", calls(kp_log)[-1]["args"] == ["unlock"])
    check("exists looks at the path itself", k.exists(kp) and not k.exists(os.path.join(d, "nope.kdbx")))
    bad, _ = AD.KpKdbx(recorder(d, "kpfail.py", rc=6)[0]).init("/x.kdbx", False)
    check("a kp.py failure is (False, detail)", bad is False)

    g, g_log = recorder(d, "google.py")
    state = os.path.join(d, "state")
    gc = AD.GoogleCli(g, environ={"BRAIN_STATE": state})
    good, _ = gc.add("work", "cid-1", "sec-1", "me@example.com")
    c = calls(g_log)[-1]
    check("add runs google.py add with the account, client id and login hint",
          good and c["args"] == ["add", "--account", "work", "--client-id", "cid-1", "--login-hint", "me@example.com"], c)
    check("and hands the client secret on stdin, never in argv", c["stdin"].strip() == "sec-1" and "sec-1" not in c["args"], c)
    gc.authorize("work")
    check("authorize runs google.py auth for the account", calls(g_log)[-1]["args"] == ["auth", "--account", "work"])
    write(os.path.join(state, "google-accounts.json"), json.dumps({"accounts": {"personal": {}, "work": {}}}))
    check("accounts lists what google.py has on record", gc.accounts() == ["personal", "work"], gc.accounts())


def test_local_files_storage():
    print("\n== the local files directory ==")
    d = tmpdir()
    home, state = os.path.join(d, "home"), os.path.join(d, "state")
    target = os.path.join(home, "BrainFiles")
    lf = AD.LocalFiles(home, environ={"BRAIN_STATE": state})
    check("the proposed default is ~/BrainFiles", lf.propose_default() == target, lf.propose_default())
    check("a directory already set in BRAIN_FILES_DIR is proposed instead",
          AD.LocalFiles(home, environ={"BRAIN_STATE": state, "BRAIN_FILES_DIR": "/srv/files"}).propose_default()
          == "/srv/files")
    good, detail = lf.check("~/BrainFiles")
    check("check expands ~ against this HOME, creates the directory and returns its absolute path",
          good and detail == target and os.path.isdir(target), detail)
    check("and leaves no probe file behind", os.listdir(target) == [], os.listdir(target))
    check("an existing directory checks fine again", lf.check(target) == (True, target))
    blocker = write(os.path.join(d, "a-file"), "x")
    bad, why = lf.check(blocker)
    check("a path that is a file is (False, why)", bad is False and bool(why), why)
    bad, why = lf.check(os.path.join(blocker, "sub"))
    check("a path that cannot be created is (False, why)", bad is False and bool(why), why)
    if os.geteuid() != 0:
        ro = os.path.join(d, "read-only")
        os.makedirs(ro)
        os.chmod(ro, 0o500)
        bad, why = lf.check(ro)
        os.chmod(ro, 0o700)
        check("a directory that cannot be written is (False, why)", bad is False and bool(why), why)
    good, written = lf.persist(target)
    check("persist records it in <brain state>/files-dir.json, private",
          good and written == os.path.join(state, "files-dir.json") and json.load(open(written)) == {"dir": target}
          and stat.S_IMODE(os.stat(written).st_mode) == 0o600, written)
    import brain_files

    check("which is where files.py reads it",
          brain_files.files_dir(environ={"BRAIN_STATE": state}, home=home) == target)
    check("once recorded, it is what the next run proposes", lf.propose_default() == target)


def test_local_shared_storage():
    print("\n== the shared coordination path ==")
    d = tmpdir()
    home, state = os.path.join(d, "home"), os.path.join(d, "state")
    target = os.path.join(home, "BrainShared")
    ls = AD.LocalShared(home, environ={"BRAIN_STATE": state})
    check("no propose_default: this step is opt-in, unlike the files directory",
          not hasattr(ls, "propose_default"))
    good, detail = ls.check("~/BrainShared")
    check("check expands ~ against this HOME, creates the directory and returns its absolute path",
          good and detail == target and os.path.isdir(target), detail)
    check("and leaves no probe file behind", os.listdir(target) == [], os.listdir(target))
    check("an existing directory checks fine again", ls.check(target) == (True, target))
    blocker = write(os.path.join(d, "a-shared-file"), "x")
    bad, why = ls.check(blocker)
    check("a path that is a file is (False, why)", bad is False and bool(why), why)
    good, written = ls.persist(target)
    check("persist records it in <brain state>/shared-dir.json, private",
          good and written == os.path.join(state, "shared-dir.json") and json.load(open(written)) == {"dir": target}
          and stat.S_IMODE(os.stat(written).st_mode) == 0o600, written)
    import brain_shared

    check("which is where presence.py and claims_sync.py read it",
          brain_shared.shared_dir(environ={"BRAIN_STATE": state}, home=home) == target)
    check("and brain_shared.configured() agrees",
          brain_shared.configured(environ={"BRAIN_STATE": state}, home=home) is True)


def test_mcp():
    print("\n== MCP registration and the shell profile ==")
    d = tmpdir()
    home = os.path.join(d, "home")
    claude, claude_log = recorder(d, "claude")
    os.chmod(claude, 0o755)
    m = AD.McpSetup("/srv/vault", home, environ={"SHELL": "/bin/zsh"}, which=lambda n: claude if n == "claude" else None)
    check("the snippets name this vault's server", "/srv/vault/integrations/mcp/server.py" in m.snippets()["claude-code"])
    check("Claude Code is offered only when its CLI is on PATH",
          m.claude_available() and not AD.McpSetup("/v", home, environ={}, which=lambda n: None).claude_available())
    good, _ = m.register_claude()
    check("registration runs claude mcp add for this server",
          good and calls(claude_log)[-1]["args"][:4] == ["mcp", "add", "brain", "--"]
          and calls(claude_log)[-1]["args"][-1] == "/srv/vault/integrations/mcp/server.py", calls(claude_log))
    check("zsh users get ~/.zshrc", m.profile_path() == os.path.join(home, ".zshrc"))
    check("bash users on Linux get ~/.bashrc",
          AD.McpSetup("/v", home, environ={"SHELL": "/bin/bash"}, platform="linux").profile_path()
          == os.path.join(home, ".bashrc"))
    profile = write(os.path.join(home, ".zshrc"), "alias ll='ls -l'\n")
    line = D.profile_line("/srv/vault")
    good, detail = m.append_profile(line)
    text = open(profile).read()
    backups = [f for f in os.listdir(home) if f.startswith(".zshrc.bak-second-brain")]
    check("the line is appended after the user's own content", good and text.startswith("alias ll") and line in text, text)
    check("the profile was backed up first", len(backups) == 1 and open(os.path.join(home, backups[0])).read()
          == "alias ll='ls -l'\n", backups)
    m.append_profile(line)
    check("appending again never duplicates it", open(profile).read().count(line) == 1)


def test_scheduler():
    print("\n== scheduler setup, with no real scheduler ==")
    d = tmpdir()
    home, state = os.path.join(d, "home"), os.path.join(d, "state")
    env = {"BRAIN_FAKE_SCHEDULER": "1"}
    s = AD.SchedulerSetup(VAULT, home, state, platform="darwin", environ=env)
    check("macOS detects launchd", s.detect() == "launchd")
    preview = s.preview("launchd", ["guardian"])
    check("the launchd preview shows the rendered plist for this vault",
          "com.secondbrain.guardian" in preview and VAULT + "/_bin/guardian.py" in preview, preview[:400])
    results = s.install("launchd", ["guardian", "sync"])
    agents = os.path.join(home, "Library", "LaunchAgents")
    check("install writes each accepted plist under this HOME's LaunchAgents",
          [r[0] for r in results] == ["com.secondbrain.guardian", "com.secondbrain.sync"] and all(r[1] for r in results)
          and sorted(os.listdir(agents)) == ["com.secondbrain.guardian.plist", "com.secondbrain.sync.plist"],
          (results, os.listdir(agents) if os.path.isdir(agents) else None))
    ls = AD.SchedulerSetup(VAULT, home, state, platform="linux", environ=dict(env, XDG_RUNTIME_DIR="/run/user/1"),
                           which=lambda n: "/usr/bin/" + n)
    check("Linux with a user session detects systemd", ls.detect() == "systemd")
    preview = ls.preview("systemd", ["tasks"])
    check("the systemd preview shows the service and the timer",
          "second-brain-tasks.service" in preview and "[Timer]" in preview and VAULT + "/_bin/tasks.py" in preview, preview)
    results = ls.install("systemd", ["tasks"])
    units = os.path.join(home, ".config", "systemd", "user")
    check("install writes the user units under this HOME",
          results and results[0][1] and sorted(os.listdir(units)) == ["second-brain-tasks.service", "second-brain-tasks.timer"],
          (results, os.listdir(units) if os.path.isdir(units) else None))
    check("the cron preview is the crontab line", "# brain:second-brain-sync" in ls.preview("cron", ["sync"]))
    check("with BRAIN_FAKE_SCHEDULER no real launchctl, systemctl or crontab is used",
          s.control("launchd", []).launchctl == "true" and ls.control("systemd", []).systemctl == "true"
          and ls.control("cron", []).crontab == "true")


def test_routines():
    print("\n== routine token pool and agent command ==")
    d = tmpdir()
    vault = os.path.join(d, "vault")
    agent = write(os.path.join(d, "bin", "agent"), "#!/bin/sh\nexit 0\n", mode=0o755)
    write(os.path.join(vault, "90-Meta", "agent-command.txt"), "# comment\n%s -p {prompt}\n" % agent)
    r = AD.RoutinePool(vault)
    good, detail = r.agent_available()
    check("the agent command from 90-Meta/agent-command.txt is found", good and agent in detail, detail)
    write(os.path.join(vault, "90-Meta", "agent-command.txt"), "/nowhere/agent -p {prompt}\n")
    check("a missing agent binary is reported", r.agent_available()[0] is False)
    r.add_token("routines-1", "kp://apis/agent-routines-token-1", "2026-09-15", "routines")
    r.add_token("routines-2", "kp://apis/agent-routines-token-2", "2026-09-15", "routines")
    good, detail = r.add_token("routines-1", "kp://apis/agent-routines-token-1", "2026-09-15", "routines")
    path = os.path.join(vault, "90-Meta", "routine-tokens.json")
    text = open(path).read()
    import routine_auth_core.domain as RD

    pool = RD.parse_pool(text)
    check("the pool holds each reference once, in the format routine auth reads",
          [e.label for e in pool] == ["routines-1", "routines-2"] and good and "already" in detail, (text, detail))
    check("and references only, in a private file", "kp://" in text and stat.S_IMODE(os.stat(path).st_mode) == 0o600)


def main():
    global AD, D
    try:
        from first_run_core import adapters as AD
        from first_run_core import domain as D
    except Exception as exc:
        check("first_run_core.adapters and domain import", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_files, test_kdbx_google, test_local_files_storage, test_local_shared_storage, test_mcp,
                 test_scheduler, test_routines):
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
