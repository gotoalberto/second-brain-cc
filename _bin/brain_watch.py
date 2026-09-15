#!/usr/bin/env python3
"""Brain's file-watch job and git-hook installer. Needs no AI agent.

  brain_watch.py tick       one pass: what changed on disk since the last tick, what to run
                            for it (ledger, reindex, linkfix, debounced sync), and the alerts
                            that replace the Stop memory gate. Then the agent watch: a wiped
                            Claude Code hooks block triggers `guardian.py repair --hooks-only`
                            (debounced), and Claude Desktop's main.log is read for account
                            switches and a stale browser bridge. launchd runs it every 60 s
                            (com.secondbrain.watch).
  brain_watch.py generate   write githooks/pre-commit, githooks/post-commit and
                            integrations/claude-code/plugin/brain/hooks/hooks.json from 90-Meta/events.json
  brain_watch.py install    generate, then point this vault's core.hooksPath at githooks —
                            the only command that touches git config, run once per clone
  brain_watch.py status     last tick, pending sync, open detections; changes nothing

Everything it decides lives in events_core and is tested there; this file wires the real
adapters. State: <brain state>/watch-state.json, <brain state>/main-log-cursor.json.
Log: <brain state>/logs/watch.log. BRAIN_CLAUDE_MAIN_LOG points the account watch at another
main.log (a scratch copy, for a smoke check). It only chooses what is read, so a tick with a
scratch main.log refuses to run (exit 2, one line) unless BRAIN_STATE also names a scratch
directory: otherwise it would write the real account watch, cursor and alerts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import brain_paths  # noqa: E402
from events_core import adapters as EAD  # noqa: E402
from events_core import application as EA  # noqa: E402
from events_core import domain as ED  # noqa: E402

MAX_LOG_BYTES = 1_000_000
LOG_KEEP = 3


def vault_dir() -> str:
    return os.environ.get("BRAIN_VAULT") or os.path.dirname(HERE)


def registry_path() -> str:
    return os.path.join(vault_dir(), "90-Meta", "events.json")


def state_path() -> str:
    return os.path.join(brain_paths.state_dir(), "watch-state.json")


def log_path() -> str:
    return os.path.join(brain_paths.state_dir(), "logs", "watch.log")


def rotate(path: str) -> None:
    """Keep logs bounded. Brain's convention: everything logs, and logs rotate."""
    try:
        if os.path.getsize(path) < MAX_LOG_BYTES:
            return
    except OSError:
        return
    base = path[:-len(".log")] if path.endswith(".log") else path
    for i in range(LOG_KEEP - 1, 0, -1):
        older = "%s.%d.log" % (base, i)
        newer = path if i == 1 else "%s.%d.log" % (base, i - 1)
        if os.path.exists(newer):
            if os.path.exists(older):
                os.remove(older)
            os.rename(newer, older)


def log(message: str) -> None:
    try:
        path = log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rotate(path)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("[%s] %s\n" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message))
    except Exception:
        pass


def load_registry(path=None):
    path = path or registry_path()
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise ED.RegistryError("cannot read %s: %s" % (path, exc))
    return ED.load_registry(text)


def real_claude_main_log() -> str:
    return os.path.join(os.path.expanduser("~"), "Library", "Logs", "Claude", "main.log")


def claude_main_log() -> str:
    return os.environ.get("BRAIN_CLAUDE_MAIN_LOG") or real_claude_main_log()


def isolation_problem() -> str:
    """A scratch main.log may only be read into a scratch state directory (events_core.domain)."""
    real = os.path.realpath
    no_override = {k: v for k, v in os.environ.items() if k != "BRAIN_STATE"}
    main_log = os.environ.get("BRAIN_CLAUDE_MAIN_LOG") or ""
    return ED.main_log_isolation_problem(
        real(main_log) if main_log else "", real(real_claude_main_log()), real(brain_paths.state_dir()),
        [real(brain_paths.state_dir(environ=no_override)), real(brain_paths.legacy_state_dir())])


def hook_liveness_source(vault):
    """The guardian's liveness source, wired exactly as guardian.py wires it."""
    from guardian_core import adapters as GAD

    return GAD.HookLivenessSource(
        projects_dir=os.path.join(os.path.expanduser("~"), ".claude", "projects"),
        heartbeat_log=os.path.join(brain_paths.effective_state_dir(), "logs", "heartbeat.jsonl"),
        registry_path=os.path.join(vault, "90-Meta", "events.json"),
        epoch_path=os.path.join(brain_paths.state_dir(), "hook-liveness.json"),
        config_path=os.path.join(vault, "90-Meta", "hook-liveness.json"))


def build_ports():
    vault = vault_dir()
    bin_dir = os.path.join(vault, "_bin")
    return EA.Ports(
        snapshot=EAD.FsSnapshot(vault),
        state=EAD.JsonWatchState(state_path()),
        runner=EAD.SubprocessRunner(cwd=vault),
        session=EAD.EnvThenProcessTreeSessionId(),
        alerts=EAD.GuardianAlertSink(),
        git=EAD.GitUnsyncedProbe(vault),
        files=EAD.VaultFiles(vault),
        clock=EAD.SystemClock(),
        python=[os.path.join(bin_dir, "pywrap.sh")],
        bin_dir=bin_dir,
        settings_hooks=EAD.ClaudeSettingsHooks(os.path.join(os.path.expanduser("~"), ".claude")),
        main_log=EAD.MainLogReader(claude_main_log(), os.path.join(brain_paths.state_dir(), "main-log-cursor.json")),
        hook_liveness=EAD.GuardianHookLiveness(hook_liveness_source(vault)),
    )


def set_hooks_path(vault):
    """git -C <vault> config core.hooksPath githooks. (ok, detail)."""
    try:
        p = subprocess.run(["git", "-C", vault, "config", "core.hooksPath", "githooks"],
                           capture_output=True, text=True, timeout=30)
        return p.returncode == 0, (p.stderr or p.stdout).strip()
    except Exception as exc:
        return False, "%s: %s" % (type(exc).__name__, exc)


def make_parser():
    ap = argparse.ArgumentParser(prog="brain_watch.py",
                                 description="Brain's file-watch job and git-hook installer")
    sub = ap.add_subparsers(dest="cmd", metavar="{tick,generate,install,status}")
    sub.add_parser("tick", help="one watch pass (what launchd runs)")
    sub.add_parser("generate", help="write git hooks and hooks.json from the registry")
    sub.add_parser("install", help="generate, then set core.hooksPath (once per clone)")
    sub.add_parser("status", help="last tick, pending sync, open detections; changes nothing")
    return ap


def _generate(registry):
    results = list(EA.generate_git_hooks(build_ports(), registry))
    results.append(EA.generate_claude_hooks(build_ports(), registry))
    for r in results:
        print("%s %s" % ("wrote    " if r.changed else "unchanged", r.path))
    return results


def _status():
    try:
        with open(state_path(), encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        print("no tick recorded yet (%s)" % state_path())
        return 0
    memory = st.get("memory") or {}
    last = st.get("last_tick")
    print("last tick:     %s" % (dt.datetime.fromtimestamp(last).isoformat(timespec="seconds") if last else "never"))
    print("last actions:  %s" % (", ".join(st.get("last_actions") or []) or "none"))
    print("sync:          %s" % ("pending (debouncing)" if memory.get("sync_pending") else "nothing pending"))
    unsaved = memory.get("unsaved_since")
    print("unsaved since: %s" % (dt.datetime.fromtimestamp(unsaved).isoformat(timespec="seconds") if unsaved else "-"))
    print("detections:    %s" % (", ".join(memory.get("alerted") or []) or "none open"))
    print("files watched: %d" % len(st.get("snapshot") or {}))
    return 0


def main(argv=None) -> int:
    args = make_parser().parse_args(sys.argv[1:] if argv is None else argv)
    if not args.cmd:
        make_parser().print_help(sys.stderr)
        return 2
    if args.cmd == "status":
        return _status()

    try:
        registry = load_registry()
    except ED.RegistryError as exc:
        print("brain_watch: invalid event registry: %s" % exc, file=sys.stderr)
        log("%s: invalid event registry: %s" % (args.cmd, exc))
        return 2

    if args.cmd == "tick":
        why = isolation_problem()
        if why:
            print("brain_watch: tick refused: %s" % why, file=sys.stderr)   # no log: it lives in real state
            return 2
        ports = build_ports()
        actions = EA.run_watch_tick(ports, registry)
        did = EA.run_agent_watch(ports, registry)
        if actions or did:
            log("tick: %s" % ", ".join(["%s(%d)" % (a.kind, len(a.paths)) for a in actions] + list(did or [])))
        return 0

    results = _generate(registry)
    log("%s: %s" % (args.cmd, ", ".join("%s=%s" % (r.path, "written" if r.changed else "unchanged") for r in results)))
    if args.cmd == "generate":
        return 0
    done, detail = set_hooks_path(vault_dir())
    if not done:
        print("could not set core.hooksPath: %s" % detail, file=sys.stderr)
        log("install: core.hooksPath failed: %s" % detail)
        return 1
    print("core.hooksPath = githooks in %s" % vault_dir())
    log("install: core.hooksPath = githooks in %s" % vault_dir())
    return 0


if __name__ == "__main__":
    sys.exit(main())
