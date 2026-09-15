"""The event layer's use cases: one file-watch tick, and the generators.

Each takes a `Ports` bundle and a loaded registry. No file, subprocess or clock is reached
from here, so launchd, the git hooks, the CLI and the tests all run the same code.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import asdict, dataclass, field

from . import domain as D

ACTION_TIMEOUT = 300
HOOKS_REPAIR_TIMEOUT = 90       # the tick waits at most this long for guardian.py repair --hooks-only
HOOK_LIVENESS_EVERY_S = 300.0   # the tick judges hook liveness at most this often


@dataclass
class Ports:
    snapshot: object
    state: object
    runner: object
    session: object
    alerts: object
    git: object
    files: object
    clock: object
    python: list = field(default_factory=lambda: ["/usr/bin/python3"])
    bin_dir: str = ""
    settings_hooks: object = None    # ports.SettingsHooks: Claude Code's live hooks, for the agent watch
    main_log: object = None          # ports.LogTail: Claude Desktop's main.log, for the agent watch
    hook_liveness: object = None     # ports.HookLiveness: are Brain's hooks firing, for the agent watch


@dataclass(frozen=True)
class WriteResult:
    path: str
    changed: bool


def _memory(raw) -> D.WatchMemory:
    raw = raw or {}
    return D.WatchMemory(last_change_at=raw.get("last_change_at"),
                         sync_pending=bool(raw.get("sync_pending")),
                         unsaved_since=raw.get("unsaved_since"),
                         alerted=tuple(raw.get("alerted") or ()))


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def run_watch_tick(ports, registry) -> list:
    """Look at disk once, run what the registry says each change needs, alert, remember.

    A command that cannot run is skipped, never fatal: the tick exists so that the rest
    keeps happening when one piece is broken.
    """
    state = _safe(ports.state.load, {}) or {}
    now = ports.clock.now()
    current = ports.snapshot.read(list(registry.watch.paths))
    plan = D.plan_watch_tick(state.get("snapshot"), current, now, _memory(state.get("memory")),
                             registry.watch, unsynced_oldest=_safe(ports.git.oldest_unsynced_mtime))

    commands = {t.spec["action"]: t.spec["command"] for _e, t in registry.triggers("file-watch")}
    sid = _safe(ports.session.resolve, "system") or "system"
    for action in plan.actions:
        command = commands.get(action.kind)
        if not command:
            continue
        tokens = shlex.split(command)
        argv = list(ports.python) + [ports.bin_dir.rstrip("/") + "/" + tokens[0]] + tokens[1:]
        if action.kind == "ledger-update":
            argv += ["--sid", sid, "--paths"] + list(action.paths)
        try:
            ports.runner.run(argv, ACTION_TIMEOUT)
        except Exception:
            continue

    for key, summary in plan.raise_alerts:
        _safe(lambda k=key, s=summary: ports.alerts.raise_alert(k, s))
    for key in plan.clear_alerts:
        _safe(lambda k=key: ports.alerts.clear_alert(k))

    state.update(snapshot=current, memory=asdict(plan.memory), last_tick=now,
                 last_actions=[a.kind for a in plan.actions])
    _safe(lambda: ports.state.save(state))
    return plan.actions


def run_agent_watch(ports, registry) -> list:
    """The agent watch, after each file-watch tick. Returns what it did (repair trigger, alert keys).

    - Claude Code's hooks: when a registry hook is missing from the live settings (a login or
      a settings reset wiped them), run the guardian's hooks-only repair now instead of
      waiting up to 15 minutes, at most once every five minutes and with a timeout.
    - Claude Desktop's main.log: an account switch is a one-tick notice, a browser bridge left
      on the old account is a warning while it lasts (events_core.domain.plan_account_watch).

    - Hook liveness: at most every five minutes, the guardian's cheap verdict on whether the
      hooks fire (no probe, no silent window), raised into the guardian's channel with its
      severity and cleared once it is gone. The guardian's own run judges the rest.

    All are best effort: a port that fails is skipped, never fatal to the tick.
    """
    did = []
    if ports.settings_hooks is None and ports.main_log is None and ports.hook_liveness is None:
        return did
    state = _safe(ports.state.load, {}) or {}
    now = ports.clock.now()

    if ports.settings_hooks is not None:
        hooks = _safe(ports.settings_hooks.hooks)
        if (hooks is not None and not D.hooks_look_present(hooks, D.claude_hook_commands(registry))
                and D.repair_trigger_due(state.get("last_hooks_repair_trigger"), now)):
            argv = list(ports.python) + [ports.bin_dir.rstrip("/") + "/guardian.py", "repair", "--hooks-only"]
            state["last_hooks_repair_trigger"] = now
            did.append("hooks-repair")
            _safe(lambda: ports.runner.run(argv, HOOKS_REPAIR_TIMEOUT))

    if ports.main_log is not None:
        text, fresh = _safe(ports.main_log.read_new, ("", False)) or ("", False)
        plan = D.plan_account_watch(state.get("account_watch"), text, fresh=fresh)
        for key, summary in plan.raise_alerts:
            _safe(lambda k=key, s=summary: ports.alerts.raise_alert(k, s))
            did.append(key)
        for key in plan.clear_alerts:
            _safe(lambda k=key: ports.alerts.clear_alert(k))
        state["account_watch"] = plan.memory

    if ports.hook_liveness is not None:
        last = state.get("last_hook_liveness")
        if not isinstance(last, (int, float)) or now - last >= HOOK_LIVENESS_EVERY_S:
            state["last_hook_liveness"] = now
            found = _safe(lambda: ports.hook_liveness.findings(now))
            if found is not None:
                current = []
                for key, severity, summary in found:
                    _safe(lambda k=key, s=summary, v=severity: ports.alerts.raise_alert(k, s, severity=v))
                    current.append(key)
                    did.append(key)
                for key in state.get("hook_liveness_raised") or []:
                    if key not in current:
                        _safe(lambda k=key: ports.alerts.clear_alert(k))
                state["hook_liveness_raised"] = current

    _safe(lambda: ports.state.save(state))
    return did


def _write_if_changed(ports, rel, text, executable=False) -> WriteResult:
    """Generated files are written only when their content changes, so their mtime can
    settle — vault_sync.py commits a file only once it has been at rest."""
    if ports.files.read(rel) == text:
        return WriteResult(rel, False)
    ports.files.write(rel, text, executable=executable)
    return WriteResult(rel, True)


def generate_claude_hooks(ports, registry, rel="integrations/claude-code/plugin/brain/hooks/hooks.json") -> WriteResult:
    text = json.dumps(D.render_claude_hooks_json(registry), indent=2, ensure_ascii=False)
    return _write_if_changed(ports, rel, text)


def generate_git_hooks(ports, registry) -> list:
    """Writes githooks/pre-commit and post-commit. Never touches git config: pointing
    core.hooksPath at them is a one-time install step, not something a recurring job does."""
    return [_write_if_changed(ports, "githooks/pre-commit", D.render_git_pre_commit(registry), executable=True),
            _write_if_changed(ports, "githooks/post-commit", D.render_git_post_commit(registry), executable=True)]


def generate_agents_md(ports, registry, protocol_text, known_triggers, rel="AGENTS.md") -> WriteResult:
    return _write_if_changed(ports, rel, D.render_agents_md(registry, protocol_text, known_triggers))


def generate_claude_md(ports, rel="CLAUDE.md") -> WriteResult:
    return _write_if_changed(ports, rel, D.CLAUDE_MD_POINTER)


def generate_hooks_doc(ports, registry, rel=D.HOOKS_DOC_REL) -> WriteResult:
    return _write_if_changed(ports, rel, D.render_hooks_without_claude(registry))
