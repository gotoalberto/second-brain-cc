#!/usr/bin/env python3
# brain:allow-secrets (synthetic token-shaped values only, never a real credential)
"""Tests for routine_auth_core.adapters: KeePass, the pool file, the state file, the raw log.

Every test works in a temporary directory. KeePass is a fake `kp.py` script written by the
test, which records its argv and environment and hands a synthetic value to the `--pipe`
command exactly as the real one does. The real kdbx, Keychain, ~/.claude and network are
never reached. Run standalone:

    python3 _bin/routine_auth_core/adapters_test.py
"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[0] = os.path.dirname(HERE)

ok, fail = [], []
TMP = []

FAKE_TOKEN = "sk-ant-oat01-" + "Q7w_E8r-" * 11


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def tmpdir():
    d = tempfile.mkdtemp(prefix="routine-auth-adapters-")
    TMP.append(d)
    return d


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    if mode is not None:
        os.chmod(path, mode)
    return path


FAKE_KP = r'''
import json, os, subprocess, sys, time
record = os.environ["FAKE_KP_RECORD"]
with open(record, "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "noprompt": os.environ.get("BRAIN_KP_NOPROMPT"),
                         "kpout_set": bool(os.environ.get("KPOUT"))}) + "\n")
mode = os.environ.get("FAKE_KP_MODE", "ok")
if mode == "locked":
    sys.stderr.write("kp: master password not available (BRAIN_KP_NOPROMPT)\n"); sys.exit(4)
if mode == "nodb":
    sys.stderr.write("kp: the KP drive is not mounted\n"); sys.exit(6)
if mode == "hang":
    time.sleep(30)
pipe = sys.argv[sys.argv.index("--pipe") + 1]
p = subprocess.run(["/bin/sh", "-c", pipe], input=os.environ.get("FAKE_KP_VALUE", "") + "\n", text=True)
sys.exit(p.returncode)
'''


def outcome(fn, *a, **kw):
    try:
        return fn(*a, **kw), None
    except Exception as exc:
        return None, exc


def test_kp_token_source(A, D):
    print("\n== KpTokenSource ==")
    root = tmpdir()
    kp = write(os.path.join(root, "kp.py"), FAKE_KP)
    record = os.path.join(root, "record.jsonl")
    scratch = os.path.join(root, "scratch")
    os.makedirs(scratch)
    ref = "kp://Brain/apis/claude-code-oauth-routines-1"

    def source(mode="ok", value=FAKE_TOKEN):
        env = {"PATH": os.environ.get("PATH", ""), "HOME": root, "FAKE_KP_RECORD": record,
               "FAKE_KP_MODE": mode, "FAKE_KP_VALUE": value}
        return A.KpTokenSource(kp, python=sys.executable, environ=env, tmp_dir=scratch)

    value, exc = outcome(source().read, ref, timeout=20)
    check("a stored token is returned", value == FAKE_TOKEN and exc is None, (exc,))
    calls = [json.loads(l) for l in open(record)] if os.path.exists(record) else []
    last = calls[-1] if calls else {}
    check("kp.py is asked for the entry and attribute, by name",
          last.get("argv", [])[:4] == ["get", "apis/claude-code-oauth-routines-1", "-a", "password"], last)
    check("the read never prompts (BRAIN_KP_NOPROMPT=1)", last.get("noprompt") == "1", last)
    check("the value travels through a file, never through argv",
          FAKE_TOKEN not in json.dumps(calls) and last.get("kpout_set") is True, last)
    check("the temporary file is removed", os.listdir(scratch) == [], os.listdir(scratch))

    value, exc = outcome(source(value="two words").read, ref, timeout=20)
    check("a malformed value comes back as stored, for the domain to judge", value == "two words", (value, exc))
    value, exc = outcome(source(value=FAKE_TOKEN + " ").read, ref, timeout=20)
    check("only the newline the pipe adds is removed, not a stored trailing space", value == FAKE_TOKEN + " ", exc)

    _, exc = outcome(source("locked").read, ref, timeout=20)
    check("exit 4 (no master password headless) is keepass_locked",
          isinstance(exc, A.TokenUnavailable) and exc.kind == D.KEEPASS_LOCKED, repr(exc))
    check("and says it is a KeePass problem, not a token problem",
          exc is not None and "KeePass" in str(exc) and "not a token problem" in str(exc), str(exc))
    _, exc = outcome(source("nodb").read, ref, timeout=20)
    check("any other kp.py failure is keepass_unavailable with its reason",
          isinstance(exc, A.TokenUnavailable) and exc.kind == D.KEEPASS_UNAVAILABLE and "not mounted" in str(exc),
          repr(exc))
    _, exc = outcome(source("hang").read, ref, timeout=1)
    check("a read that does not answer in time is keepass_unavailable, and says so",
          isinstance(exc, A.TokenUnavailable) and exc.kind == D.KEEPASS_UNAVAILABLE and "1s" in str(exc), repr(exc))
    check("no temporary file is left behind by a failed read", os.listdir(scratch) == [], os.listdir(scratch))
    missing = A.KpTokenSource(os.path.join(root, "nope.py"), python=sys.executable, environ={}, tmp_dir=scratch)
    _, exc = outcome(missing.read, ref, timeout=5)
    check("a missing kp.py is keepass_unavailable", isinstance(exc, A.TokenUnavailable)
          and exc.kind == D.KEEPASS_UNAVAILABLE, repr(exc))
    for e in [x for x in (exc,) if x]:
        check("no failure message carries the value", FAKE_TOKEN not in str(e))


def test_pool_file(A, D):
    print("\n== PoolFile ==")
    root = tmpdir()
    path = write(os.path.join(root, "routine-tokens.json"), json.dumps({"tokens": [
        {"label": "routines-1", "account": "routines", "kp_ref": "kp://Brain/apis/x", "issued": "2026-09-15"}]}))
    entries, exc = outcome(A.PoolFile(path).entries)
    check("the pool file is read and validated by the domain",
          exc is None and [e.label for e in entries] == ["routines-1"], (entries, exc))
    _, exc = outcome(A.PoolFile(os.path.join(root, "missing.json")).entries)
    check("a missing pool file is a PoolConfigError naming the path",
          isinstance(exc, D.PoolConfigError) and "missing.json" in str(exc), repr(exc))


def test_state_store(A):
    print("\n== JsonStateStore ==")
    root = tmpdir()
    path = os.path.join(root, "state", "routine-auth-state.json")
    store = A.JsonStateStore(path)
    check("a missing state file loads as empty", store.load() == {})
    store.save({"routines-1": {"status": "dead"}})
    check("state round-trips", A.JsonStateStore(path).load() == {"routines-1": {"status": "dead"}})
    check("no temporary file is left next to it", sorted(os.listdir(os.path.dirname(path))) == ["routine-auth-state.json"],
          os.listdir(os.path.dirname(path)))
    write(path, "{broken")
    check("a corrupt state file loads as empty rather than crashing the run", store.load() == {})


def test_raw_log(A, D):
    print("\n== RawOutputLog ==")
    root = tmpdir()
    path = os.path.join(root, "logs", "routine-auth.log")
    log = A.RawOutputLog(path, clock=lambda: dt.datetime(2026, 9, 15, 13, 0), max_bytes=4000)
    cls = D.Classification(D.UNKNOWN, "exit 1: boom", verified=False)
    log.record("digest-now-agent", "routines-1", cls, 1,
               "stdout says %s and more" % FAKE_TOKEN, "stderr Bearer abc.def", secrets=[FAKE_TOKEN])
    text = open(path).read() if os.path.exists(path) else ""
    check("a failed run is logged with its routine, token label, kind and exit code",
          all(s in text for s in ("digest-now-agent", "routines-1", "unknown", "exit=1")), text)
    check("the raw output is there, redacted", "stdout says" in text and FAKE_TOKEN not in text
          and "abc.def" not in text, text)
    check("the log says whether the pattern is verified", "unverified" in text.lower(), text)
    for _ in range(40):
        log.record("r", "routines-1", cls, 1, "x" * 300, "", secrets=[])
    check("the log rotates", os.path.exists(os.path.join(root, "logs", "routine-auth.1.log"))
          and os.path.getsize(path) < 8000, os.listdir(os.path.dirname(path)))


FAKE_CLI = r'''#!/bin/sh
echo "$*" >> "%(calls)s"
env | cut -d= -f1 >> "%(envs)s"
case "$1" in
  --version) %(version)s ;;
esac
exit 0
'''


def fake_cli(root, name="claude", version='echo "2.1.272 (Claude Code)"'):
    calls, envs = os.path.join(root, name + ".calls"), os.path.join(root, name + ".envs")
    path = write(os.path.join(root, "bin", name), FAKE_CLI % {"calls": calls, "envs": envs, "version": version},
                 mode=0o755)
    return path, calls, envs


def test_cli_resolver(A, D):
    print("\n== CliResolver ==")
    root = tmpdir()
    cli, calls, envs = fake_cli(root)
    os.environ["ANTHROPIC_API_KEY"] = "must-not-reach-the-cli"
    try:
        r = A.CliResolver("%s -p {prompt} --output-format json" % cli, home=root)
        st = r.check()
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)
    check("a standalone CLI that answers --version is healthy",
          st.ok and st.path == cli and "2.1.272" in st.version, st)
    check("the version check runs with no Anthropic credentials from the parent",
          os.path.exists(envs) and "ANTHROPIC_API_KEY" not in open(envs).read().split()
          and "CLAUDE_CODE_OAUTH_TOKEN" not in open(envs).read().split(), open(envs).read() if os.path.exists(envs) else "")
    r.check()
    check("the health check runs once per process, not per routine",
          len(open(calls).read().splitlines()) == 1, open(calls).read())

    st = A.CliResolver("~/bin/claude -p {prompt}", home=root).check()
    check("a ~ path in the template resolves under the home directory", st.ok and st.path == cli, st)
    st = A.CliResolver("claude -p {prompt}", home=root, env_path=os.path.join(root, "bin")).check()
    check("a bare name resolves on the given PATH", st.ok and st.path == cli, st)

    st = A.CliResolver("", home=root).check()
    check("no template is unhealthy, saying so", not st.ok and "no agent command configured" in st.detail, st)
    st = A.CliResolver("/nonexistent/claude -p {prompt}", home=root).check()
    check("a missing binary is unhealthy, naming it", not st.ok and "/nonexistent/claude" in st.detail, st)
    st = A.CliResolver("%s -p {prompt} --bare" % cli, home=root).check()
    check("a template passing --bare is unhealthy", not st.ok and "--bare" in st.detail, st)
    st = A.CliResolver("%s -p {prompt} --dangerously-skip-permissions" % cli, home=root).check()
    check("a template skipping permissions is unhealthy",
          not st.ok and "--dangerously-skip-permissions" in st.detail, st)
    st = A.CliResolver("%s -p {prompt} --allowedTools Bash" % cli, home=root).check()
    check("a template granting bare Bash is unhealthy", not st.ok and "Bash" in st.detail, st)

    bundle = write(os.path.join(root, "Library", "Application Support", "Claude", "claude-code", "2.1.0", "claude"),
                   FAKE_CLI % {"calls": calls, "envs": envs, "version": "echo 2.1.0"}, mode=0o755)
    link = os.path.join(root, "bin", "desktop-claude")
    os.symlink(bundle, link)
    st = A.CliResolver("%s -p {prompt}" % link, home=root).check()
    check("a symlink into the Claude Desktop app's copy is refused", not st.ok and "Desktop" in st.detail, st)

    broken, _, _ = fake_cli(root, "broken", version='echo "boom" >&2; exit 3')
    st = A.CliResolver("%s -p {prompt}" % broken, home=root).check()
    check("a CLI whose --version fails is unhealthy with the exit code", not st.ok and "3" in st.detail, st)
    hang, _, _ = fake_cli(root, "hang", version="sleep 30")
    st = A.CliResolver("%s -p {prompt}" % hang, home=root, timeout=1).check()
    check("a CLI whose --version hangs is unhealthy, not a hung runner", not st.ok and "1s" in st.detail, st)


ATTEMPT_CLI = r'''#!/bin/sh
printf "%%s\n" "$@" > "%(args)s"
env > "%(env)s"
pwd > "%(pwd)s"
%(body)s
'''


def test_cli_attempt(A, D):
    print("\n== CliAttempt ==")
    root = tmpdir()
    work = os.path.join(root, "work")
    os.makedirs(work)
    files = {k: os.path.join(root, k + ".txt") for k in ("args", "env", "pwd")}
    write(os.path.join(root, "bin", "claude"), ATTEMPT_CLI % dict(files, body='echo \'{"total_cost_usd": 0.01}\''),
          mode=0o755)
    prompt_tmp = os.path.join(root, "prompt-tmp")
    os.makedirs(prompt_tmp)
    os.environ["SOME_PARENT_VAR"] = "must-not-reach-the-cli"
    try:
        attempt = A.CliAttempt("~/bin/claude -p {prompt} --output-format json", cwd=work, home=root, tmp_dir=prompt_tmp)
        rc, out, err = attempt.run("Do the thing.", ["--add-dir", "~/work", "--allowedTools", "Bash,Read"],
                                   {"HOME": root, "PATH": "/usr/bin:/bin", "CLAUDE_CODE_OAUTH_TOKEN": FAKE_TOKEN},
                                   timeout=20)
    finally:
        os.environ.pop("SOME_PARENT_VAR", None)
    args = open(files["args"]).read().splitlines() if os.path.exists(files["args"]) else []
    check("the template runs with ~ expanded, the prompt text, then the routine's agent_args",
          rc == 0 and args == ["-p", "Do the thing.", "--output-format", "json", "--add-dir", work,
                               "--allowedTools", "Bash,Read"], (rc, args, err))
    check("the prompt's temporary file is removed after the run", os.listdir(prompt_tmp) == [], os.listdir(prompt_tmp))
    copy = os.path.join(root, "prompt-copy.txt")
    reader_files = {k: v + ".reader" for k, v in files.items()}    # the checks below still read the first run's
    write(os.path.join(root, "bin", "reader"), ATTEMPT_CLI % dict(reader_files, body='cat "$4" > "%s"' % copy),
          mode=0o755)
    framed = 'You are running the Brain routine "r" unattended.\n\n---\nnot frontmatter\n---\nLast line.'
    rc, _, err = A.CliAttempt("~/bin/reader -p {prompt} --file {prompt_file}", cwd=work, home=root,
                              tmp_dir=prompt_tmp).run(framed, [], {"PATH": "/usr/bin:/bin"}, timeout=20)
    check("{prompt_file} is a private file holding exactly the prompt text",
          rc == 0 and os.path.exists(copy) and open(copy).read().strip() == framed, (rc, err))
    check("and it is gone once the run ends", os.listdir(prompt_tmp) == [], os.listdir(prompt_tmp))
    env = dict(l.split("=", 1) for l in open(files["env"]).read().splitlines() if "=" in l) \
        if os.path.exists(files["env"]) else {}
    check("the CLI gets exactly the environment it was given",
          env.get("CLAUDE_CODE_OAUTH_TOKEN") == FAKE_TOKEN and "SOME_PARENT_VAR" not in env, sorted(env))
    check("the token never travels in argv", FAKE_TOKEN not in "\n".join(args))
    check("it runs in the given working directory",
          os.path.exists(files["pwd"]) and os.path.realpath(open(files["pwd"]).read().strip()) == os.path.realpath(work))
    check("stdout comes back for the classifier", '"total_cost_usd"' in out, out)
    write(os.path.join(root, "bin", "slow"), ATTEMPT_CLI % dict(files, body="sleep 30"), mode=0o755)
    rc, _, err = A.CliAttempt("~/bin/slow -p {prompt}", cwd=work, home=root).run("Do it.", [], {"PATH": "/usr/bin:/bin"},
                                                                                 timeout=1)
    check("an attempt past its timeout is exit 124, killed", rc == 124 and "timed out" in err, (rc, err))


def test_scratch_dirs(A, D):
    import stat

    print("\n== ScratchDirs ==")
    root = tmpdir()
    base = os.path.join(root, "state", "routine-scratch")
    scratch = A.ScratchDirs(base)
    rid = "digest-now-agent-20260915T154507-ab12cd34"
    path, exc = outcome(scratch.create, rid)
    check("a run's scratch directory is created under <brain state>/routine-scratch/<run id>",
          exc is None and path == os.path.join(base, rid) and os.path.isdir(path), (path, exc))
    check("it is private (0700), and so is its parent",
          path and stat.S_IMODE(os.stat(path).st_mode) == 0o700 and stat.S_IMODE(os.stat(base).st_mode) == 0o700)
    _, exc = outcome(scratch.create, rid)
    check("the same run id never gets a directory twice", exc is not None, repr(exc))
    write(os.path.join(base, rid, "email.html"), "<p>draft</p>")
    outcome(scratch.remove, os.path.join(base, rid))
    check("remove deletes the directory and what the run left in it", not os.path.exists(os.path.join(base, rid)))
    outside = tmpdir()
    write(os.path.join(outside, "keep.txt"), "not scratch")
    outcome(scratch.remove, outside)
    outcome(scratch.remove, base)
    outcome(scratch.remove, os.path.join(base, ".."))
    check("remove refuses anything that is not one directory inside the scratch root",
          os.path.exists(os.path.join(outside, "keep.txt")) and os.path.isdir(base) and os.path.isdir(root))

    now = dt.datetime.now()
    old = scratch.create("r-old")
    young = scratch.create("r-young")
    stray = write(os.path.join(base, "stray.txt"), "a file, not a run")
    t_old = (now - dt.timedelta(days=8)).timestamp()
    t_young = (now - dt.timedelta(days=2)).timestamp()
    os.utime(old, (t_old, t_old))
    os.utime(young, (t_young, t_young))
    os.utime(stray, (t_old, t_old))
    removed, exc = outcome(scratch.prune, now)
    check("prune removes run directories older than 7 days and keeps the rest",
          exc is None and removed == ["r-old"] and not os.path.exists(old) and os.path.isdir(young), (removed, exc))
    check("and never touches a plain file", os.path.exists(stray))
    removed, exc = outcome(A.ScratchDirs(os.path.join(root, "never-created")).prune, now)
    check("pruning a root that does not exist is nothing, not an error", exc is None and removed == [], (removed, exc))


def test_run_ids(A, D):
    import re

    print("\n== RandomRunIds ==")
    ids = A.RandomRunIds()
    now = dt.datetime(2026, 9, 15, 15, 45, 7)
    a, b = ids.new("digest-now-agent", now), ids.new("digest-now-agent", now)
    check("two attempts in the same second still get different run ids", a != b, (a, b))
    check("a run id names the routine and the time", a.startswith("digest-now-agent-20260915T154507-"), a)
    check("and is safe as a directory name", re.match(r"^[A-Za-z0-9._-]+$", a) is not None, a)


def test_mail_sent_log(A, D):
    print("\n== MailSentLog ==")
    root = tmpdir()
    path = os.path.join(root, "logs", "mail-sent.jsonl")
    check("a missing send log is no sends", A.MailSentLog(path).records() == [])
    write(path, json.dumps({"to": "a@b.co", "subject": "S", "message_id": "m-1", "run_id": "r-1"}) + "\nbroken\n")
    recs = A.MailSentLog(path).records()
    check("the log's records are read through the domain parser", [r.get("message_id") for r in recs] == ["m-1"], recs)
    os.makedirs(os.path.join(root, "a-dir.jsonl"))
    recs, exc = outcome(A.MailSentLog(os.path.join(root, "a-dir.jsonl")).records)
    check("an unreadable log is no sends, never a crash", exc is None and recs == [], (recs, exc))


def test_raw_log_run_id(A, D):
    print("\n== RawOutputLog names the run ==")
    root = tmpdir()
    path = os.path.join(root, "logs", "routine-auth.log")
    log = A.RawOutputLog(path, clock=lambda: dt.datetime(2026, 9, 15, 13, 0))
    rid = "example-routine-b-agent-20260915T074500-ab12cd34"
    log.record("example-routine-b-agent", "routines-1", D.Classification(D.CONTRACT_BREACH, "unmet"), 65,
               "out", "", secrets=[], run_id=rid)
    text = open(path).read() if os.path.exists(path) else ""
    check("a failed attempt's entry carries its run id, whole", "run=" + rid in text, text)


def main():
    try:
        from routine_auth_core import adapters as A
        from routine_auth_core import domain as D
    except Exception as exc:
        check("routine_auth_core.adapters imports", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t, args in ((test_kp_token_source, (A, D)), (test_pool_file, (A, D)), (test_state_store, (A,)),
                        (test_raw_log, (A, D)), (test_cli_resolver, (A, D)), (test_cli_attempt, (A, D)),
                        (test_scratch_dirs, (A, D)), (test_run_ids, (A, D)), (test_mail_sent_log, (A, D)),
                        (test_raw_log_run_id, (A, D))):
            try:
                t(*args)
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
