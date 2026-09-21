#!/usr/bin/env python3
"""The Brain guardian: keeps the vault machinery wired, and speaks up when it is not.

Runs with no AI agent at all. When the user accepted it at first run, launchd
(com.secondbrain.guardian), a systemd user timer or a cron line (second-brain-guardian) starts
`repair` every 15 minutes; the other commands are for a person at a terminal. Only the scheduled
jobs accepted at first run (<brain state>/first-run.json) are installed or reloaded.

  guardian.py check                 look, alert on what changed, exit 0/1/2 (ok/warn/fail)
  guardian.py repair                rewire every present agent, install/reload launchd
                                    jobs, set the vault's core.hooksPath, then check and alert
                                    (a run that changed something always notifies what).
                                    Exit 0 when the run completed, whatever it found; 1 only
                                    when its own repair work errored. This is what launchd runs:
                                    findings reach you through status and alerts, never through
                                    the job's exit status. It also refreshes this
                                    machine's entry in the machine registry
                                    (machines.py register --daily), once a day.
  guardian.py repair --hooks-only   agent wiring only, no launchd, no alerts (bootstrap.sh)
  guardian.py status                everything it watches (the agent routines' token pool
                                    included), changes nothing
  guardian.py run-routine <id>      run one routine from 90-Meta/scheduled-tasks.md now

`--settings PATH` points the Claude Code adapter at another settings.json.

This file only wires real adapters to guardian_core.application. What counts as a
problem, what gets merged and when to speak is decided in guardian_core, and tested
there. Logs go to <brain state>/logs/guardian.log (see brain_paths.py).
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import brain_paths  # noqa: E402
import install_plugin  # noqa: E402
from guardian_core import adapters, application, claude_code, domain, mail_queue, mailer  # noqa: E402

HOME = os.path.expanduser("~")
MAX_LOG_BYTES = 1_000_000
LOG_KEEP = 3


def vault_dir() -> str:
    return os.environ.get("BRAIN_VAULT") or os.path.dirname(HERE)


def log_path() -> str:
    return os.path.join(brain_paths.state_dir(), "logs", "guardian.log")


# ---------------------------------------------------------------- logging


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
    """Never raises: a guardian that dies because its log is unwritable is no guardian."""
    try:
        path = log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rotate(path)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("[%s] %s\n" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message))
    except Exception:
        pass


# ---------------------------------------------------------------- wiring


def build_ports(args) -> application.Ports:
    vault = vault_dir()
    state = brain_paths.state_dir()
    config_dir, settings_file = claude_code.default_locations(HOME)
    settings_path = getattr(args, "settings", None) or settings_file
    if getattr(args, "settings", None):
        config_dir = os.path.dirname(os.path.abspath(settings_path))
    agents = [claude_code.ClaudeCodeAgent(
        claude_code.FileSettingsStore(settings_path, log=log),
        claude_code.CanonicalHooksFile(os.path.join(vault, "integrations", "claude-code", "plugin", "brain", "hooks", "hooks.json"),
                                       vault=vault, home=HOME),
        config_dir=config_dir,
        vault=vault,
        plugin=install_plugin.Syncer(os.path.join(vault, "integrations", "claude-code", "plugin", "brain"), config_dir, state,
                                     log=log, vault=vault))]
    cfg = mailer.load_mail_config(mailer.mail_config_path(state, vault))
    outbox = mail_queue.FileMailQueue(os.path.join(state, "guardian-mail-queue.json"),
                                      mailer=mailer.build_mailer(cfg), log=log)
    # Heartbeats are written by the hooks through brainlib, which follows the state cutover.
    liveness = adapters.HookLivenessSource(
        projects_dir=os.path.join(HOME, ".claude", "projects"),
        heartbeat_log=os.path.join(brain_paths.effective_state_dir(), "logs", "heartbeat.jsonl"),
        registry_path=os.path.join(vault, "90-Meta", "events.json"),
        epoch_path=os.path.join(state, "hook-liveness.json"),
        config_path=os.path.join(vault, "90-Meta", "hook-liveness.json"))
    return application.Ports(
        agents=agents,
        launchd=adapters.build_job_control(vault, state, HOME),
        clock=adapters.SystemClock(),
        notifier=adapters.default_notifier(),
        outbox=outbox,
        vault=adapters.VaultDoctorProbe(vault),
        interpreter=adapters.InterpreterHealthProbe(),
        state=adapters.JsonStateStore(os.path.join(state, "guardian-state.json")),
        raised=adapters.RaisedAlertsFile(),
        routines=adapters.TasksRegistrySource(),
        mail_to=cfg.get("to") or "",
        git_hooks=adapters.GitHooksControl(vault),
        token_pool=adapters.TokenPoolProbe(os.path.join(vault, "90-Meta", "routine-tokens.json"),
                                           os.path.join(state, "routine-auth-state.json")),
        desktop_tasks=adapters.DesktopScheduledTasksProbe(
            os.path.join(HOME, "Library", "Application Support", "Claude", "claude-code-sessions")),
        hook_liveness=liveness,
        hook_probe=adapters.HookProbe(
            claude_code.CanonicalHooksFile(os.path.join(vault, "integrations", "claude-code", "plugin", "brain", "hooks", "hooks.json"),
                                           vault=vault, home=HOME),
            liveness),
    )


# ---------------------------------------------------------------- cli


def parse_args(argv):
    return make_parser().parse_args(argv)


def make_parser():
    ap = argparse.ArgumentParser(prog="guardian.py",
                                 description="keep Brain's machinery wired, and speak up when it is not")
    sub = ap.add_subparsers(dest="cmd", metavar="{check,repair,status,run-routine}")
    helps = {"check": "look, and alert on what changed",
             "repair": "rewire agents and launchd jobs, then check",
             "status": "print everything the guardian watches; changes nothing"}
    for name, text in helps.items():
        p = sub.add_parser(name, help=text)
        p.add_argument("--settings", default=None, help="Claude Code settings.json to use")
        if name == "repair":
            p.add_argument("--hooks-only", "--agents-only", dest="hooks_only", action="store_true",
                           help="agent wiring only: no launchd, no alerts (what bootstrap.sh runs)")
    r = sub.add_parser("run-routine", help="run one routine from the task registry now")
    r.add_argument("id")
    return ap


def register_machine() -> str:
    """Keep this machine's entry in the machine registry fresh: once a day, cheap, never fatal."""
    import machines

    return machines.register_daily()


def _print_findings(report):
    if not report.findings:
        print("healthy")
    for f in report.findings:
        print("[%s] %s%s" % (f.severity, f.summary, "  (repairable)" if f.repairable else ""))


def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not args.cmd:
        make_parser().print_help(sys.stderr)
        return 2

    if args.cmd == "run-routine":
        import tasks

        log("run-routine %s" % args.id)
        return tasks.main(["--force", args.id])

    ports = build_ports(args)

    if args.cmd == "check":
        report = application.run_check(ports)
        _print_findings(report)
        log("check: exit=%d findings=%s" % (report.exit_code, ",".join(f.key for f in report.findings) or "-"))
        return report.exit_code

    if args.cmd == "repair":
        res = application.run_repair(ports, agents_only=args.hooks_only)
        if not args.hooks_only:
            try:
                log("machine registry: %s" % register_machine())
            except Exception as exc:
                log("machine registry: failed: %s" % exc.__class__.__name__)
        for c in res.changes:
            print("changed: " + c)
        for b in res.backups:
            print("backup:  " + b)
        for e in res.errors:
            print("error:   " + e, file=sys.stderr)
        _print_findings(res.report)
        code = domain.repair_exit_code(res.errors)
        log("repair%s: exit=%d changes=%d errors=%d findings=%s"
            % (" (agents only)" if args.hooks_only else "", code, len(res.changes), len(res.errors),
               ",".join(f.key for f in res.report.findings) or "-"))
        for line in res.changes + res.errors:
            log("  " + line)
        for subject in res.alerts:
            log("  alert: " + subject)
        return code

    print(application.run_status(ports))
    return 0


if __name__ == "__main__":
    sys.exit(main())
