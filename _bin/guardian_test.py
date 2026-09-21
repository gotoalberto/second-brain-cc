#!/usr/bin/env python3
"""Tests for guardian.py — the command line that wires real adapters to the use cases.

Dispatch is tested with `build_ports` and the use cases replaced by recorders, so no
adapter ever runs. The one wiring test constructs the real ports against a temporary
vault, state directory and settings path, and calls nothing on them. Run standalone:

    python3 _bin/guardian_test.py
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok, fail = [], []
TMP = []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def tmpdir():
    d = tempfile.mkdtemp(prefix="guardian-cli-")
    TMP.append(d)
    return d


class Recorder:
    def __init__(self, result=None):
        self.calls = []
        self.result = result

    def __call__(self, *a, **kw):
        self.calls.append((a, kw))
        return self.result


def run_main(G, argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = G.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


def main():
    try:
        import guardian as G
        G.main, G.build_ports
        from guardian_core import domain as D
        from guardian_core import application as A
    except Exception as exc:
        check("guardian.py imports with main and build_ports", False, "%s: %s" % (type(exc).__name__, exc))
        return finish()

    state = tmpdir()
    old_state = os.environ.get("BRAIN_STATE")
    os.environ["BRAIN_STATE"] = state
    saved = {name: getattr(A, name) for name in ("run_check", "run_repair", "run_status")}
    saved_build = G.build_ports
    saved_register = getattr(G, "register_machine", None)
    try:
        sentinel = object()
        built = Recorder(sentinel)
        G.build_ports = built
        G.register_machine = Recorder("registered")

        report = D.Report([D.Finding("agent:claude-code:hooks:Stop:x.py", "fail", "claude-code hook Stop x.py: missing", True)])
        A.run_check = Recorder(report)
        code, out = run_main(G, ["check"])
        check("check runs the check use case on the built ports",
              A.run_check.calls and A.run_check.calls[0][0][0] is sentinel, A.run_check.calls)
        check("check exits with the report's exit code", code == 2, code)
        check("check prints the findings", "x.py: missing" in out, out)

        res = A.RepairResult(changes=["claude-code hook Stop x.py: missing"], errors=[],
                             backups=["/tmp/settings.json.bak"], report=D.Report([]))
        A.run_repair = Recorder(res)
        code, out = run_main(G, ["repair"])
        check("repair runs the repair use case, all sections",
              A.run_repair.calls and A.run_repair.calls[0][1].get("agents_only") is False, A.run_repair.calls)
        check("repair prints what it changed and the backup", "x.py" in out and "settings.json.bak" in out, out)
        check("a clean repair exits 0", code == 0, code)

        warn_only = D.Report([D.Finding("launchd-exit:com.x.sync", "warn", "launchd job com.x.sync: last run failed")])
        A.run_repair = Recorder(A.RepairResult(report=warn_only))
        code, out = run_main(G, ["repair"])
        check("a repair that completed with a warning open exits 0 (findings go to status and alerts)",
              code == 0 and "last run failed" in out, (code, out))
        failing = D.Report([D.Finding("launchd:com.x.sync", "fail", "launchd job com.x.sync is not loaded")])
        A.run_repair = Recorder(A.RepairResult(report=failing))
        code, out = run_main(G, ["repair"])
        check("a repair that completed with a failure open exits 0 too", code == 0 and "not loaded" in out,
              (code, out))
        logged = open(os.path.join(state, "logs", "guardian.log")).read().splitlines()
        check("and the log records exit=0 with the findings still named",
              logged and "exit=0" in logged[-1] and "launchd:com.x.sync" in logged[-1], logged[-1:])

        A.run_check = Recorder(warn_only)
        code, _ = run_main(G, ["check"])
        check("check keeps its severity exit for people and scripts: warn-only exits 1", code == 1, code)

        check("the scheduled repair registers this machine in the machine registry",
              len(G.register_machine.calls) > 0, G.register_machine.calls)
        logged = open(os.path.join(state, "logs", "guardian.log")).read()
        check("and logs what the registration did", "machine registry: registered" in logged, logged[-300:])
        G.register_machine = Recorder()
        run_main(G, ["check"])
        check("check does not register (it only looks)", G.register_machine.calls == [])

        def exploding():
            raise RuntimeError("registry unavailable")
        G.register_machine = exploding
        A.run_repair = Recorder(A.RepairResult(report=D.Report([])))
        code, _ = run_main(G, ["repair"])
        check("a registration that blows up never fails the repair", code == 0, code)

        G.register_machine = Recorder()
        A.run_repair = Recorder(res)
        run_main(G, ["repair", "--hooks-only", "--settings", "/tmp/elsewhere/settings.json"])
        check("--hooks-only does not register", G.register_machine.calls == [])
        check("--hooks-only repairs agent wiring only",
              A.run_repair.calls[0][1].get("agents_only") is True, A.run_repair.calls)
        check("--settings reaches the port wiring",
              getattr(built.calls[-1][0][0], "settings", None) == "/tmp/elsewhere/settings.json", built.calls[-1])

        A.run_repair = Recorder(A.RepairResult(errors=["could not load com.x"], report=D.Report([])))
        code, out = run_main(G, ["repair"])
        check("a repair with errors exits non-zero and prints them", code == 1 and "could not load com.x" in out,
              (code, out))

        A.run_status = Recorder("Brain guardian status — all good")
        code, out = run_main(G, ["status"])
        check("status prints the status text and exits 0", code == 0 and "all good" in out, (code, out))

        fake_tasks = types.ModuleType("tasks")
        fake_tasks.calls = []
        fake_tasks.main = lambda argv=None: fake_tasks.calls.append(argv) or 0
        real_tasks = sys.modules.get("tasks")
        sys.modules["tasks"] = fake_tasks
        try:
            code, _ = run_main(G, ["run-routine", "daily-digest-agent"])
        finally:
            if real_tasks is None:
                sys.modules.pop("tasks", None)
            else:
                sys.modules["tasks"] = real_tasks
        check("run-routine hands the routine to the task runner, forced",
              fake_tasks.calls == [["--force", "daily-digest-agent"]] and code == 0, fake_tasks.calls)

        code, _ = run_main(G, [])
        check("no command is a usage error", code == 2, code)

        logs = os.path.join(state, "logs", "guardian.log")
        check("runs are logged under the Brain state directory, not ~/.claude",
              os.path.exists(logs) and "check" in open(logs).read(), logs)
    finally:
        for name, fn in saved.items():
            setattr(A, name, fn)
        G.build_ports = saved_build
        if saved_register is not None:
            G.register_machine = saved_register

    # the real wiring, constructed against temporary locations and never called
    vault = tmpdir()
    os.makedirs(os.path.join(vault, "90-Meta"))
    with open(os.path.join(state, "guardian-mail.json"), "w") as fh:
        json.dump({"enabled": False, "adapter": "gmail-api", "account": "personal", "from": "me@example.com",
                   "to": "me@example.com"}, fh)
    old_vault = os.environ.get("BRAIN_VAULT")
    os.environ["BRAIN_VAULT"] = vault
    try:
        args = G.parse_args(["check", "--settings", os.path.join(tmpdir(), "settings.json")])
        ports = G.build_ports(args)
        check("the real ports carry the Claude Code agent adapter",
              [a.name() for a in ports.agents] == ["claude-code"], ports.agents)
        check("with the settings path given on the command line",
              ports.agents[0].settings.path == args.settings, ports.agents[0].settings.path)
        sync = getattr(ports.agents[0], "plugin", None)
        check("the Claude Code adapter syncs skills and agents from the vault's plugin",
              sync is not None and sync.plugin_dir == os.path.join(vault, "integrations", "claude-code", "plugin", "brain")
              and sync.state_dir == state, sync and (sync.plugin_dir, sync.state_dir))
        check("mail goes to the address in this machine's guardian-mail.json", ports.mail_to == "me@example.com",
              ports.mail_to)
        check("a disabled mail config builds a disabled outbox", ports.outbox.enabled() is False)
        check("the outbox and alert state live under the Brain state directory",
              ports.outbox.path.startswith(state) and ports.state.path.startswith(state),
              (ports.outbox.path, ports.state.path))
        tp = getattr(ports, "token_pool", None)
        check("the real ports read the routine token pool from the vault and its state from the Brain state directory",
              tp is not None and tp.pool_path == os.path.join(vault, "90-Meta", "routine-tokens.json")
              and tp.state_path == os.path.join(state, "routine-auth-state.json"),
              tp and (tp.pool_path, tp.state_path))
        dt_probe = getattr(ports, "desktop_tasks", None)
        check("the real ports look for Claude app scheduled tasks in the app's sessions directory, read-only",
              dt_probe is not None and dt_probe.sessions_dir == os.path.join(
                  G.HOME, "Library", "Application Support", "Claude", "claude-code-sessions"),
              dt_probe and dt_probe.sessions_dir)
        hl = getattr(ports, "hook_liveness", None)
        check("the real ports read Claude Code transcripts under the home directory, heartbeats from the Brain "
              "state logs, hook events from the vault's registry and the liveness epoch from the state directory",
              hl is not None and hl.projects_dir == os.path.join(G.HOME, ".claude", "projects")
              and hl.heartbeat_log == os.path.join(state, "logs", "heartbeat.jsonl")
              and hl.registry_path == os.path.join(vault, "90-Meta", "events.json")
              and hl.epoch_path == os.path.join(state, "hook-liveness.json"),
              hl and (hl.projects_dir, hl.heartbeat_log, hl.registry_path, hl.epoch_path))
        hp = getattr(ports, "hook_probe", None)
        check("and a hook probe over the vault's canonical hooks.json, built but not run",
              hp is not None and hp.canonical.path == os.path.join(vault, "integrations", "claude-code", "plugin", "brain", "hooks", "hooks.json")
              and hp.ran is False, hp and (hp.canonical.path, hp.ran))
        check("with no first-run consent the guardian manages no scheduled job",
              ports.launchd.labels() == [], ports.launchd.labels())
    finally:
        if old_vault is None:
            os.environ.pop("BRAIN_VAULT", None)
        else:
            os.environ["BRAIN_VAULT"] = old_vault
        if old_state is None:
            os.environ.pop("BRAIN_STATE", None)
        else:
            os.environ["BRAIN_STATE"] = old_state

    plist = open(os.path.join(HERE, "com.secondbrain.guardian.plist")).read()
    args = [a.strip() for a in plist.split("<key>ProgramArguments</key>", 1)[1].split("</array>", 1)[0]
            .replace("<array>", "").replace("<string>", "").split("</string>") if a.strip()]
    check("the launchd job runs `repair` (the completion-driven exit), never `check`",
          args[-1:] == ["repair"] and "check" not in args, args)

    env = dict(os.environ, BRAIN_STATE=tmpdir())
    p = subprocess.run([sys.executable, os.path.join(HERE, "guardian.py"), "--help"],
                       capture_output=True, text=True, env=env, timeout=30)
    check("guardian.py --help exits 0 and names its commands",
          p.returncode == 0 and all(c in p.stdout for c in ("check", "repair", "status", "run-routine")),
          (p.returncode, p.stdout, p.stderr))
    return finish()


def finish():
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
