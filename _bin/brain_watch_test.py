#!/usr/bin/env python3
"""Tests for brain_watch.py — the agent-independent file-watch job and git-hook installer.

Dispatch is tested with the registry loader, the port wiring, the use cases and the git
config call replaced by recorders. One real `install` runs against a temporary git
repository standing in for the vault, with BRAIN_STATE, HOME and the git global config
pointed at temporary locations. Run standalone:

    python3 _bin/brain_watch_test.py
"""
import contextlib
import io
import json
import os
import shutil
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


def tmpdir():
    d = tempfile.mkdtemp(prefix="brain-watch-test-")
    TMP.append(d)
    return d


class Recorder:
    def __init__(self, result=None):
        self.calls = []
        self.result = result

    def __call__(self, *a, **kw):
        self.calls.append((a, kw))
        return self.result


def run_main(W, argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = W.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


REGISTRY = {"version": 1, "events": [
    {"id": "sync", "description": "sync", "handler": "vault_sync",
     "triggers": [{"kind": "claude-hook", "event": "Stop", "command": "vault_sync.py --hook", "async": True},
                  {"kind": "file-watch", "action": "sync-debounce", "command": "vault_sync.py --hook"}]},
    {"id": "pre-write-gate", "description": "gate", "handler": "gate_write",
     "triggers": [{"kind": "git-hook", "hook": "pre-commit", "command": "events_core/git_pre_commit.py"}]},
    {"id": "post-commit-dirty", "description": "dirty", "handler": "git_post_commit",
     "triggers": [{"kind": "git-hook", "hook": "post-commit", "command": "events_core/git_post_commit.py"}]},
]}


def main():
    try:
        import brain_watch as W
        from events_core import application as EA
        from events_core import domain as ED
        W.main, W.build_ports, W.load_registry, W.set_hooks_path
    except Exception as exc:
        check("brain_watch.py imports with main, build_ports, load_registry, set_hooks_path", False,
              "%s: %s" % (type(exc).__name__, exc))
        return finish()

    state = tmpdir()
    saved_env = {k: os.environ.get(k) for k in ("BRAIN_STATE", "BRAIN_VAULT")}
    os.environ["BRAIN_STATE"] = state
    names = ("run_watch_tick", "generate_git_hooks", "generate_claude_hooks", "run_agent_watch")
    saved = {n: getattr(EA, n) for n in names}
    saved_w = {n: getattr(W, n) for n in ("build_ports", "load_registry", "set_hooks_path")}
    try:
        reg = ED.load_registry(json.dumps(REGISTRY))
        sentinel = object()
        W.build_ports = Recorder(sentinel)
        W.load_registry = Recorder(reg)
        W.set_hooks_path = Recorder((True, ""))
        EA.run_watch_tick = Recorder([ED.WatchAction("index-trigger", ("30-Knowledge/a.md",))])
        EA.run_agent_watch = Recorder(["hooks-repair"])
        EA.generate_git_hooks = Recorder([EA.WriteResult("githooks/pre-commit", True),
                                          EA.WriteResult("githooks/post-commit", False)])
        EA.generate_claude_hooks = Recorder(EA.WriteResult("integrations/claude-code/plugin/brain/hooks/hooks.json", False))

        code, out = run_main(W, ["tick"])
        check("tick runs one watch tick with the built ports and the loaded registry",
              EA.run_watch_tick.calls and EA.run_watch_tick.calls[0][0][0] is sentinel
              and EA.run_watch_tick.calls[0][0][1] is reg and code == 0, (EA.run_watch_tick.calls, code))
        check("tick never touches git config", W.set_hooks_path.calls == [])
        check("tick also runs the agent watch (wiped hooks, account switches) on the same ports and registry",
              EA.run_agent_watch.calls and EA.run_agent_watch.calls[0][0][0] is sentinel
              and EA.run_agent_watch.calls[0][0][1] is reg, EA.run_agent_watch.calls)
        log = os.path.join(state, "logs", "watch.log")
        check("the tick is logged under the Brain state directory",
              os.path.exists(log) and "index-trigger" in open(log).read(), log)
        check("with what the agent watch did", "hooks-repair" in open(log).read(), open(log).read())

        code, out = run_main(W, ["generate"])
        check("generate writes the git hooks and hooks.json from the registry",
              EA.generate_git_hooks.calls and EA.generate_claude_hooks.calls and code == 0, out)
        check("generate does not touch git config either", W.set_hooks_path.calls == [])

        code, out = run_main(W, ["install"])
        check("install generates, then points core.hooksPath at githooks",
              len(EA.generate_git_hooks.calls) == 2 and len(W.set_hooks_path.calls) == 1 and code == 0,
              (W.set_hooks_path.calls, code))
        check("install says what it did", "core.hooksPath" in out and "githooks/pre-commit" in out, out)

        W.set_hooks_path = Recorder((False, "not a git repository"))
        code, out = run_main(W, ["install"])
        check("an install whose git config fails exits non-zero and says why",
              code == 1 and "not a git repository" in out, (code, out))

        def bad_registry(*a, **kw):
            raise ED.RegistryError("event x: unknown trigger kind 'pigeon'")

        W.load_registry = bad_registry
        code, out = run_main(W, ["tick"])
        check("an invalid registry is exit 2 with the reason", code == 2 and "pigeon" in out, (code, out))
        W.load_registry = Recorder(reg)

        with open(os.path.join(state, "watch-state.json"), "w") as fh:
            json.dump({"last_tick": 1_800_000_000.0, "last_actions": ["sync-debounce"],
                       "memory": {"sync_pending": True, "alerted": ["watch:unsynced"]}}, fh)
        before = open(os.path.join(state, "watch-state.json")).read()
        code, out = run_main(W, ["status"])
        check("status shows the last tick, pending sync and open detections",
              code == 0 and "sync-debounce" in out and "watch:unsynced" in out and "pending" in out, out)
        check("status changes nothing", open(os.path.join(state, "watch-state.json")).read() == before)

        code, _ = run_main(W, [])
        check("no command is a usage error", code == 2, code)
        # a scratch main.log must not write real state: HOME is a temporary directory, so even a
        # wrong answer here writes nothing real
        import brain_paths
        home = tmpdir()
        scratch_log = os.path.join(tmpdir(), "main.log")
        saved_iso = {k: os.environ.get(k) for k in ("HOME", "BRAIN_STATE", "BRAIN_CLAUDE_MAIN_LOG")}
        try:
            os.environ["HOME"] = home
            os.environ.pop("BRAIN_STATE", None)
            os.environ["BRAIN_CLAUDE_MAIN_LOG"] = scratch_log
            default_state = brain_paths.state_dir(environ={}, home=home)

            def tick_fresh():
                W.build_ports = Recorder(sentinel)
                EA.run_watch_tick = Recorder([])
                EA.run_agent_watch = Recorder([])
                return run_main(W, ["tick"])

            code, out = tick_fresh()
            check("a tick with a scratch main.log and no BRAIN_STATE refuses, non-zero, with a one-line reason",
                  code not in (0, None) and len(out.strip().splitlines()) == 1 and "BRAIN_STATE" in out, (code, out))
            check("and touches no state: no ports built, no tick, no agent watch",
                  W.build_ports.calls == [] and EA.run_watch_tick.calls == [] and EA.run_agent_watch.calls == [],
                  (W.build_ports.calls, EA.run_watch_tick.calls))
            check("and writes nothing under the default state directory, not even its log",
                  not os.path.exists(default_state), default_state)

            for label, value in (("the default state directory spelled out", default_state),
                                 ("the default state directory with a leading ~",
                                  "~" + default_state[len(home):]),
                                 ("the legacy state directory", brain_paths.legacy_state_dir(home))):
                os.environ["BRAIN_STATE"] = value
                code, out = tick_fresh()
                check("BRAIN_STATE set to %s is still refused" % label,
                      code not in (0, None) and W.build_ports.calls == [], (value, code, out))

            os.environ["BRAIN_STATE"] = tmpdir()
            code, out = tick_fresh()
            check("a scratch main.log with a scratch BRAIN_STATE ticks",
                  code == 0 and EA.run_watch_tick.calls and EA.run_agent_watch.calls, (code, out))

            os.environ.pop("BRAIN_STATE", None)
            os.environ["BRAIN_CLAUDE_MAIN_LOG"] = os.path.join(home, "Library", "Logs", "Claude", "main.log")
            code, out = tick_fresh()
            check("BRAIN_CLAUDE_MAIN_LOG naming the real main.log ticks on the real state",
                  code == 0 and EA.run_watch_tick.calls, (code, out))
            os.environ.pop("BRAIN_CLAUDE_MAIN_LOG", None)
            code, out = tick_fresh()
            check("no BRAIN_CLAUDE_MAIN_LOG ticks as launchd runs it", code == 0 and EA.run_watch_tick.calls, (code, out))
        finally:
            for k, v in saved_iso.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    finally:
        for n, fn in saved.items():
            setattr(EA, n, fn)
        for n, fn in saved_w.items():
            setattr(W, n, fn)

    # the real ports, constructed and never called: nothing reads ~/.claude or the real main.log
    os.environ["BRAIN_CLAUDE_MAIN_LOG"] = os.path.join(state, "fake-main.log")
    try:
        ports = W.build_ports()
        ml, sh = getattr(ports, "main_log", None), getattr(ports, "settings_hooks", None)
        check("the real tick watches Claude Desktop's main.log (BRAIN_CLAUDE_MAIN_LOG overrides it), "
              "with its cursor in the Brain state directory",
              ml is not None and ml.log_path == os.path.join(state, "fake-main.log")
              and ml.cursor_path == os.path.join(state, "main-log-cursor.json"), ml and (ml.log_path, ml.cursor_path))
        check("and Claude Code's settings under the home directory",
              sh is not None and sh.config_dir == os.path.join(os.path.expanduser("~"), ".claude"), sh and sh.config_dir)
        hl = getattr(ports, "hook_liveness", None)
        src = getattr(hl, "source", None)
        check("the tick's cheap hook liveness reads heartbeats from the Brain state logs and Claude Code transcripts "
              "under the home directory",
              src is not None and src.heartbeat_log == os.path.join(state, "logs", "heartbeat.jsonl")
              and src.projects_dir == os.path.join(os.path.expanduser("~"), ".claude", "projects"),
              src and (src.heartbeat_log, src.projects_dir))
    finally:
        os.environ.pop("BRAIN_CLAUDE_MAIN_LOG", None)

    # a real install into a temporary repository standing in for the vault
    root = tmpdir()
    vault, home = os.path.join(root, "vault"), os.path.join(root, "home")
    os.makedirs(os.path.join(vault, "90-Meta"))
    os.makedirs(home)
    with open(os.path.join(vault, "90-Meta", "events.json"), "w") as fh:
        json.dump(REGISTRY, fh)
    gcfg = os.path.join(root, "gitconfig")
    open(gcfg, "w").close()
    env = dict(os.environ, HOME=home, BRAIN_VAULT=vault, BRAIN_STATE=os.path.join(root, "state"),
               GIT_CONFIG_GLOBAL=gcfg, GIT_CONFIG_NOSYSTEM="1")
    subprocess.run(["git", "init", "-q"], cwd=vault, env=env, capture_output=True)
    p = subprocess.run([sys.executable, os.path.join(HERE, "brain_watch.py"), "install"], cwd=vault, env=env,
                       capture_output=True, text=True, timeout=60)
    pre = os.path.join(vault, "githooks", "pre-commit")
    check("a real install writes executable git hooks into the vault", p.returncode == 0 and os.access(pre, os.X_OK),
          (p.returncode, p.stdout, p.stderr))
    got = subprocess.run(["git", "config", "--get", "core.hooksPath"], cwd=vault, env=env,
                         capture_output=True, text=True).stdout.strip()
    check("and sets core.hooksPath in that repository only", got == "githooks", got)
    hooks = os.path.join(vault, "integrations", "claude-code", "plugin", "brain", "hooks", "hooks.json")
    check("and generates the plugin's hooks.json from the registry",
          os.path.exists(hooks) and "vault_sync.py --hook" in open(hooks).read(), hooks)

    for k, v in saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    p = subprocess.run([sys.executable, os.path.join(HERE, "brain_watch.py"), "--help"],
                       capture_output=True, text=True, env=dict(os.environ, BRAIN_STATE=tmpdir()), timeout=30)
    check("--help exits 0 and names the commands",
          p.returncode == 0 and all(c in p.stdout for c in ("tick", "install", "generate", "status")), p.stdout)
    return finish()


def finish():
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
