"""The guardian's use cases: check, repair, status.

Each takes a `Ports` bundle and nothing else — no file, subprocess or clock is reached
from here — so the same code runs from launchd, from bootstrap.sh and from the tests.

- `run_check`  looks, and speaks up when something changed. Writes only alert state.
- `run_repair` repairs every present agent's event wiring, installs, reinstalls and
               reloads launchd jobs, points the vault's core.hooksPath at githooks and
               makes the hook files executable, then checks and speaks up like `run_check`.
- `run_status` looks and prints. Writes nothing, notifies nobody.

No agent is special here: Claude Code is one entry in `ports.agents`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from . import domain as D

MAIL_STUCK_S = 6 * 3600


@dataclass
class Ports:
    agents: list
    launchd: object
    clock: object
    notifier: object
    outbox: object
    vault: object
    interpreter: object
    state: object
    raised: object
    routines: object
    mail_to: str = ""
    git_hooks: object = None     # ports.GitHooksControl for the vault repository
    token_pool: object = None    # ports.TokenPoolProbe: the agent routines' token pool, read-only
    desktop_tasks: object = None  # ports.DesktopTasksProbe: the Claude app's own scheduled tasks, read-only
    hook_liveness: object = None  # ports.HookLivenessSource: transcripts, heartbeats, registry hooks, epoch
    hook_probe: object = None     # ports.HookProbe: every canonical hook run in a scratch state


@dataclass
class RepairResult:
    changes: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    backups: list = field(default_factory=list)
    report: D.Report = field(default_factory=D.Report)
    alerts: list = field(default_factory=list)     # subjects of what this run told the user


def _agent_name(agent) -> str:
    try:
        return agent.name()
    except Exception:
        return type(agent).__name__


# ---------------------------------------------------------------- sections


def _agents(ports):
    out = []
    for agent in ports.agents:
        try:
            if agent.present():
                out += D.agent_findings(agent.check())
        except Exception as exc:
            name = _agent_name(agent)
            out.append(D.Finding("probe:agent:" + name, D.WARN,
                                 "could not check %s wiring: %s: %s" % (name, type(exc).__name__, exc)))
    return out


def _launchd(ports):
    out = []
    for label in ports.launchd.labels():
        installed = ports.launchd.installed(label)
        loaded = installed and ports.launchd.is_loaded(label)
        last_ok, detail = ports.launchd.last_exit_ok(label) if loaded else (True, "")
        drifted = installed and ports.launchd.drifted(label)
        out += D.launchd_findings(label, installed, loaded, last_ok, detail, drifted=drifted)
    return out


def _interpreter(ports):
    return D.interpreter_findings(ports.interpreter.python3_health())


def _vault(ports):
    return D.vault_findings(ports.vault.sync_status(), ports.vault.index_age_s())


def _git_hooks(ports):
    if ports.git_hooks is None:
        return []
    return D.git_hooks_findings(ports.git_hooks.status())


def _token_pool(ports):
    if ports.token_pool is None:
        return []
    return D.token_pool_findings(ports.token_pool.pool(), ports.clock.now())


def _agent_rows(ports):
    """Agent rows with their routine file's app_task and needs_bridge (none when the source has no meta)."""
    meta = getattr(ports.routines, "meta", None)
    rows = []
    for r in ports.routines.routines():
        if r.get("type") != "agent":
            continue
        m = meta(r) if meta else {}
        rows.append({"id": r["id"], "enabled": r.get("enabled"), "app_task": m.get("app_task"),
                     "needs_bridge": list(m.get("needs_bridge") or []),
                     "permission_problem": m.get("permission_problem")})
    return rows


def _bridge_stale(ports) -> bool:
    return "bridge:stale" in (ports.raised.load() or {})


def _duplicates(ports):
    if ports.desktop_tasks is None:
        return []
    return D.duplicate_task_findings(ports.desktop_tasks.enabled(), _agent_rows(ports))


def _app_tasks(ports):
    if ports.desktop_tasks is None:
        return []
    return D.app_task_registry_findings(ports.desktop_tasks.enabled(), ports.routines.routines(),
                                        ports.routines.host(), getattr(ports.routines, "is_mine", None))


def _permissions(ports):
    return D.routine_permission_findings(_agent_rows(ports))


def _degraded(ports):
    if not _bridge_stale(ports):
        return []
    return D.degraded_routine_findings(_agent_rows(ports), True)


def _raised(ports):
    return [D.Finding(k, v.get("severity", D.FAIL), v.get("summary", k))
            for k, v in sorted(ports.raised.load().items())]


def _mail(ports):
    ob = ports.outbox
    if ob.enabled() and ob.pending():
        age = ob.oldest_age_s()
        if age is not None and age >= MAIL_STUCK_S:
            return [D.Finding("mail:undelivered", D.WARN,
                              "%d alert email(s) undelivered for %.0f h"
                              % (ob.pending(), age / 3600))]
    return []


def hook_liveness_report(source, now: float, include_silent: bool = True) -> D.LivenessReport:
    """The liveness verdict from one HookLivenessSource at `now` (epoch seconds).

    Shared with the file watch (events_core.adapters.GuardianHookLiveness), which asks for the
    cheap mode: only the active window, no silent window."""
    cfg = source.config()
    horizon = now - (cfg.silent_s if include_silent else cfg.window_s)
    sessions = source.sessions(horizon)
    recent = [s.started for s in sessions if s.mtime >= now - cfg.window_s]
    beats = source.heartbeats(min([horizon] + recent))
    return D.hook_liveness(sessions, beats, source.events(), now, source.epoch(), cfg, include_silent)


def _hook_liveness(ports):
    if ports.hook_liveness is None:
        return []
    return hook_liveness_report(ports.hook_liveness, ports.clock.now().timestamp()).findings


def _hook_probe(ports):
    if ports.hook_probe is None:
        return []
    return D.probe_findings(ports.hook_probe.results())


SECTIONS = (("agents", _agents), ("launchd", _launchd), ("interpreter", _interpreter),
            ("vault", _vault), ("githooks", _git_hooks), ("token_pool", _token_pool),
            ("duplicates", _duplicates), ("app_tasks", _app_tasks), ("permissions", _permissions), ("degraded", _degraded),
            ("hook_liveness", _hook_liveness), ("hook_probe", _hook_probe), ("raised", _raised), ("mail", _mail))


def collect(ports, sections=None) -> D.Report:
    """Every finding, read-only. A section that raises is itself a warning, not a crash:
    the guardian is the thing that has to keep talking when other things break."""
    findings = []
    for name, fn in SECTIONS:
        if sections and name not in sections:
            continue
        try:
            findings += fn(ports)
        except Exception as exc:
            findings.append(D.Finding("probe:" + name, D.WARN,
                                      "could not check %s: %s: %s" % (name, type(exc).__name__, exc)))
    return D.Report(findings)


# ---------------------------------------------------------------- alerting


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception:
        return None


def _alert(ports, report, repaired=(), backups=()):
    """Tell the user what changed, once. Never raises. Returns the actions taken.

    Two channels, two different bars. The desktop notification says only that something
    changed and how many: it can appear on a shared or recorded screen, and a finding may
    name a private routine. The detail always goes to the log and to `guardian.py status`.

    The inbox has the higher bar, and `D.mail_decide` owns it: only a FAIL still open in
    `report` once this run's repair has been attempted, something no amount of waiting
    fixes because the guardian already tried. A repair that succeeded, a problem that
    resolved, a warn-only change: desktop only. The mail is built from those findings
    themselves, not from the notification actions, so a run that repairs something while an
    unrelated FAIL happens to be open does not mail about the repair.

    `hooks:probe:*` FAILs are debounced one run by `D.probe_mail_worthy()`: they page only
    once still open on the next run, since the probe's own findings have been seen to
    resolve themselves within one 15-minute cycle.
    """
    state = _safe(ports.state.load) or {}
    now = ports.clock.now()
    prev_alerts = state.get("alerts") or {}
    alerts, actions = D.decide(prev_alerts, report.findings, now)
    actions = D.merge_alerts(D.repair_alert(list(repaired), list(backups)), actions)
    open_count = len(report.findings)
    status = ("%d open problem(s). Details: guardian.py status" % open_count
              if open_count else "All clear.")
    for a in actions:
        if a.kind == "notify-repair":
            _safe(ports.notifier.notify, "Brain guardian", "Repaired %d item(s). %s" % (len(repaired), status))
        elif a.kind == "notify-change":
            _safe(ports.notifier.notify, "Brain guardian", status)
    mail_worthy = D.probe_mail_worthy(report.findings, prev_alerts.get("active"))
    mails, mail_state = D.mail_decide(mail_worthy, prev_alerts.get("mail"), now)
    if ports.mail_to:
        for m in mails:
            _safe(ports.outbox.enqueue, ports.mail_to, m.subject, m.body)
        alerts["mail"] = mail_state
    else:
        mails = []
        alerts["mail"] = prev_alerts.get("mail") or {}
    state["alerts"] = alerts
    _safe(ports.state.save, state)
    _safe(ports.outbox.flush)
    return actions + mails


# ---------------------------------------------------------------- use cases


def _start_liveness(ports):
    """Liveness judges only sessions that start after the guardian first looked. Check and repair
    start it; status never does."""
    if ports.hook_liveness is not None:
        _safe(ports.hook_liveness.start_epoch, ports.clock.now().timestamp())


def run_check(ports) -> D.Report:
    _start_liveness(ports)
    report = collect(ports)
    _alert(ports, report)
    return report


def _repair_agents(ports, res):
    for agent in ports.agents:
        name = _agent_name(agent)
        try:
            if not agent.present():
                continue
            wiring = agent.check()
            if wiring.unreadable:
                res.errors.append("%s wiring not repaired, config unreadable: %s"
                                  % (name, wiring.unreadable))
                continue
            if not wiring.changes:
                continue
            outcome = agent.repair()
            res.changes += list(outcome.changes)
            res.errors += list(outcome.errors)
            if outcome.backup:
                res.backups.append(outcome.backup)
        except Exception as exc:
            res.errors.append("%s wiring not repaired: %s: %s" % (name, type(exc).__name__, exc))


def _repair_launchd(ports, res):
    lc = ports.launchd
    try:
        labels = lc.labels()
        own = lc.self_label()
    except Exception as exc:
        res.errors.append("launchd jobs not listed: %s: %s" % (type(exc).__name__, exc))
        return
    for label in labels:
        try:
            installed = lc.installed(label)
            if not installed:
                done, detail = lc.install(label)
                if done:
                    res.changes.append("installed launchd job %s" % label)
                    installed = True
                else:
                    res.errors.append("could not install %s: %s" % (label, detail))
            elif lc.drifted(label):
                if label == own:
                    res.errors.append("%s is the guardian's own job and its plist has drifted: "
                                      "run guardian.py repair from a terminal to reload it" % label)
                else:
                    done, detail = lc.reinstall(label)
                    if done:
                        res.changes.append("reinstalled launchd job %s (plist had drifted%s)"
                                           % (label, "; " + detail if detail else ""))
                    else:
                        res.errors.append("could not reinstall %s: %s" % (label, detail))
            if installed and not lc.is_loaded(label):
                done, detail = lc.bootstrap(label)
                if done:
                    res.changes.append("loaded launchd job %s" % label)
                else:
                    res.errors.append("could not load %s: %s" % (label, detail))
        except Exception as exc:
            res.errors.append("launchd %s: %s: %s" % (label, type(exc).__name__, exc))


def _repair_git_hooks(ports, res):
    gh = ports.git_hooks
    if gh is None:
        return
    try:
        plan = D.git_hooks_repairs(gh.status())
    except Exception:
        return          # collect() reports it as probe:githooks; nothing to repair blind
    for kind, name in plan:
        if kind == "set-hooks-path":
            what = "set vault core.hooksPath to %s" % D.GIT_HOOKS_DIR
            call = gh.set_hooks_path
        else:
            what = "make vault git hook %s/%s executable" % (D.GIT_HOOKS_DIR, name)
            call = lambda n=name: gh.make_executable(n)
        try:
            done, detail = call()
        except Exception as exc:
            done, detail = False, "%s: %s" % (type(exc).__name__, exc)
        if done:
            res.changes.append(what)
        else:
            res.errors.append("could not %s: %s" % (what, detail))


def run_repair(ports, agents_only=False) -> RepairResult:
    res = RepairResult()
    _repair_agents(ports, res)
    if agents_only:
        res.report = collect(ports, sections=("agents",))
        return res
    _repair_launchd(ports, res)
    _repair_git_hooks(ports, res)
    _start_liveness(ports)
    res.report = collect(ports)
    res.alerts = [a.subject for a in _alert(ports, res.report, res.changes, res.backups)]
    return res


def _age(seconds):
    if seconds is None:
        return "n/a"
    if seconds < 3600:
        return "%.0f min" % (seconds / 60)
    return "%.1f h" % (seconds / 3600)


def run_status(ports) -> str:
    """A human-readable picture of everything the guardian watches. Changes nothing."""
    now = ports.clock.now()
    report = collect(ports)
    lines = ["Brain guardian status — %s" % now.isoformat(timespec="seconds")]
    fails = sum(1 for f in report.findings if f.severity == D.FAIL)
    if not report.findings:
        lines.append("health: OK")
    else:
        lines.append("health: %d problem(s) — %d fail, %d warn"
                     % (len(report.findings), fails, len(report.findings) - fails))
        for f in report.findings:
            lines.append("  [%s] %s%s" % (f.severity, f.summary, "  (repairable)" if f.repairable else ""))

    lines.append("")
    lines.append("agents:")
    for agent in ports.agents:
        name = _agent_name(agent)
        try:
            if not agent.present():
                lines.append("  %-20s not present on this machine" % name)
                continue
            n = len(D.agent_findings(agent.check()))
            lines.append("  %-20s %s" % (name, "wiring OK" if not n else "%d wiring problem(s)" % n))
        except Exception as exc:
            lines.append("  %-20s (unavailable: %s)" % (name, exc))

    try:
        lines.append("launchd:")
        for label in ports.launchd.labels():
            installed = ports.launchd.installed(label)
            loaded = installed and ports.launchd.is_loaded(label)
            last = ports.launchd.last_exit_ok(label)[1] if loaded else "-"
            drift = installed and ports.launchd.drifted(label)
            lines.append("  %-34s installed=%s loaded=%s drift=%s last=%s"
                         % (label, "yes" if installed else "no", "yes" if loaded else "no",
                            "yes" if drift else "no", last or "ok"))
    except Exception as exc:
        lines.append("  (unavailable: %s)" % exc)

    try:
        s = ports.vault.sync_status()
        lines.append("vault: %d uncommitted, oldest unpushed %s, upstream %s, index age %s, "
                     "broken links %d"
                     % (s.pending, _age(s.unpushed_age_s), "yes" if s.remote_ok else "no",
                        _age(ports.vault.index_age_s()), ports.vault.broken_links()))
    except Exception as exc:
        lines.append("vault: (unavailable: %s)" % exc)

    if ports.git_hooks is not None:
        try:
            s = ports.git_hooks.status()
            lines.append("git hooks: core.hooksPath %s, %s"
                         % (s.hooks_path or "unset",
                            ", ".join("%s %s" % (f.name, "ok" if f.executable else
                                                 "missing" if not f.exists else "not executable")
                                      for f in s.files) or "no hook files expected"))
        except Exception as exc:
            lines.append("git hooks: (unavailable: %s)" % exc)

    if ports.hook_liveness is not None:
        try:
            src = ports.hook_liveness
            since = src.epoch()
            if since is None:
                lines.append("hook liveness: not started yet (the first check or repair starts it)")
            else:
                cfg = src.config()
                rep = hook_liveness_report(src, now.timestamp())
                stamp = lambda ts: dt.datetime.fromtimestamp(ts).isoformat(sep=" ", timespec="seconds")
                lines.append("hook liveness: since %s, %d session(s) checked in the last %d min, %d without heartbeats"
                             % (stamp(since), rep.checked, cfg.window_s // 60, len(rep.without)))
                for spec in src.events():
                    h = rep.last_by_event.get(spec.id)
                    lines.append("  %-20s %-11s %s" % (spec.id, spec.liveness,
                                                      "last %s %s%s" % (stamp(h.ts), h.status, " " + h.exc if h.exc else "")
                                                      if h else "never"))
        except Exception as exc:
            lines.append("hook liveness: (unavailable: %s)" % exc)

    if ports.hook_probe is not None:
        try:
            pairs = ports.hook_probe.results()
            bad = [(c, D.probe_verdict(c, r)) for c, r in pairs if D.probe_verdict(c, r)]
            if not pairs:
                lines.append("hook probe: no canonical Brain hook to run")
            elif not bad:
                lines.append("hook probe: %d hook(s) ok in a scratch state" % len(pairs))
            else:
                lines.append("hook probe: %d of %d hook(s) failed in a scratch state:" % (len(bad), len(pairs)))
                for c, why in bad:
                    lines.append("  %-20s %s" % (c.event_id, why))
        except Exception as exc:
            lines.append("hook probe: (unavailable: %s)" % exc)

    if ports.token_pool is not None:
        try:
            tp = ports.token_pool.pool()
            if tp.config_error:
                lines.append("routine tokens: pool config invalid: %s" % tp.config_error)
            elif not tp.tokens:
                lines.append("routine tokens: no pool configured on this machine")
            else:
                lines.append("routine tokens: " + ", ".join(
                    "%s %s%s (expires %s)" % (t.label, t.status,
                                             " after %s" % t.last_kind if t.status != "healthy" and t.last_kind else "",
                                             t.expires or "?")
                    for t in tp.tokens))
        except Exception as exc:
            lines.append("routine tokens: (unavailable: %s)" % exc)

    if ports.desktop_tasks is not None:
        try:
            tasks = ports.desktop_tasks.enabled()
            lines.append("claude app scheduled tasks: %d enabled across %d account(s)"
                         % (len(tasks), len({a for _, a in tasks})))
        except Exception as exc:
            lines.append("claude app scheduled tasks: (unavailable: %s)" % exc)

    try:
        ob = ports.outbox
        lines.append("email: %s, %d queued, oldest %s, to %s"
                     % ("enabled" if ob.enabled() else "disabled", ob.pending(),
                        _age(ob.oldest_age_s()), ports.mail_to or "(nobody)"))
    except Exception as exc:
        lines.append("email: (unavailable: %s)" % exc)

    try:
        host = ports.routines.host()
        is_mine = getattr(ports.routines, "is_mine", None)
        last = ports.routines.last_runs()
        lines.append("routines on %s:" % host)
        try:
            degraded = set(D.degraded_routine_ids(_agent_rows(ports), True)) if _bridge_stale(ports) else set()
        except Exception:
            degraded = set()
        for r in ports.routines.routines():
            entry = last.get(r["id"], {})
            due, why = D.routine_due(r, entry.get("last_run_date"), now, host, is_mine)
            lines.append("  %-38s %-10s %-28s last exit %s%s"
                         % (r["id"], r["type"], "DUE NOW" if due else why,
                            entry.get("last_exit", "-"),
                            "  DEGRADED: browser bridge stale" if r["id"] in degraded else ""))
    except Exception as exc:
        lines.append("routines: (unavailable: %s)" % exc)

    try:
        st = (ports.state.load() or {}).get("alerts") or {}
        lines.append("alerts: %d open since last notice, last digest %s"
                     % (len(st.get("active") or {}), st.get("last_digest") or "never"))
    except Exception as exc:
        lines.append("alerts: (unavailable: %s)" % exc)
    return "\n".join(lines)
