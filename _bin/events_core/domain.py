"""Brain's event registry and the rules built on it. No IO.

The registry (90-Meta/events.json) names every Brain event, the module that implements
it and every trigger wired to it. Everything else is derived from it here: Claude Code's
hooks.json, the AGENTS.md table any agent reads, the git hook scripts, and what the
file-watch job should do on each tick. Nothing hardcodes that mapping a second time.

What is deliberately NOT imported: os, subprocess, pathlib, time or any clock. Text comes
in as strings and "now" is always passed in.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

TRIGGER_KINDS = ("claude-hook", "file-watch", "git-hook", "launchd", "cli", "mcp")
# Triggers that fire with no AI agent in the loop.
AGENT_INDEPENDENT = ("file-watch", "git-hook", "launchd")
# Triggers a person or an agent has to call by hand.
MANUAL = ("cli", "mcp")

# The modules an event may name. A whitelist, not a pattern: a typo must fail loud.
APPROVED_HANDLERS = (
    "compass", "skills_index", "retrieve", "gate_write", "vault_ledger", "protocol_guard",
    "log_subagent", "gate_memory", "vault_sync", "session_end", "seed_worktree",
    "index_vault", "linkfix", "git_pre_commit", "git_post_commit",
)
WATCH_ACTIONS = ("ledger-update", "index-trigger", "linkfix-trigger", "sync-debounce")
GIT_HOOKS = ("pre-commit", "post-commit")
# How often a Claude Code hook is expected to fire, for the guardian's liveness check: `session` in
# every session that finished a turn, `regular` within the silent window of normal use,
# `conditional` only when its situation arises (never called silent).
LIVENESS_CLASSES = ("session", "regular", "conditional")
CLAUDE_HOOK_OPTIONS = ("timeout", "statusMessage", "async")   # in the order hooks.json writes them

ORIGIN_PYTHON = "/usr/bin/python3"
ORIGIN_BIN = "/home/brain-origin/Brain/_bin"

CLAUDE_MD_POINTER = (
    "See AGENTS.md: it holds Brain's protocol and events for any agent.\n"
    "This file exists only because Claude Code looks for CLAUDE.md specifically; it is generated.\n"
)

_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class RegistryError(ValueError):
    """The registry text is not a valid Brain event registry."""


@dataclass(frozen=True)
class Trigger:
    kind: str
    spec: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Event:
    id: str
    description: str
    handler: str
    triggers: tuple = ()
    liveness: str = ""


@dataclass(frozen=True)
class WatchConfig:
    paths: tuple = ("00-Inbox", "10-Projects", "20-Areas", "30-Knowledge",
                    "70-Entities", "90-Meta", "_bin")
    debounce_s: float = 120.0
    unsynced_alert_s: float = 3600.0
    unsaved_alert_s: float = 7200.0
    save_prefixes: tuple = ("00-Inbox", "10-Projects", "20-Areas", "30-Knowledge", "70-Entities")
    unsaved_ignore: tuple = ("50-Sessions", "60-Context-Packs", "40-Skills", "90-Meta/presence")


@dataclass(frozen=True)
class Registry:
    events: tuple
    watch: WatchConfig

    def event(self, event_id):
        for e in self.events:
            if e.id == event_id:
                return e
        raise KeyError(event_id)

    def triggers(self, kind):
        """[(event, trigger)] of one kind, in registry order."""
        return [(e, t) for e in self.events for t in e.triggers if t.kind == kind]


# ---------------------------------------------------------------- loading


_REQUIRED = {"claude-hook": ("event", "command"), "file-watch": ("action", "command"),
             "git-hook": ("hook", "command"), "launchd": ("label",), "cli": ("command",),
             "mcp": ("tool",)}


def _trigger(event_id, raw):
    if not isinstance(raw, dict):
        raise RegistryError("event %s: a trigger must be an object" % event_id)
    kind = raw.get("kind")
    if kind not in TRIGGER_KINDS:
        raise RegistryError("event %s: unknown trigger kind %r (known: %s)"
                            % (event_id, kind, ", ".join(TRIGGER_KINDS)))
    spec = {k: v for k, v in raw.items() if k != "kind"}
    for key in _REQUIRED[kind]:
        if not spec.get(key):
            raise RegistryError("event %s: %s trigger needs %r" % (event_id, kind, key))
    if kind == "file-watch" and spec["action"] not in WATCH_ACTIONS:
        raise RegistryError("event %s: unknown file-watch action %r" % (event_id, spec["action"]))
    if kind == "git-hook" and spec["hook"] not in GIT_HOOKS:
        raise RegistryError("event %s: unsupported git hook %r" % (event_id, spec["hook"]))
    return Trigger(kind, spec)


def _watch(raw):
    if raw is None:
        return WatchConfig()
    if not isinstance(raw, dict):
        raise RegistryError("watch must be an object")
    d = WatchConfig()
    return WatchConfig(
        paths=tuple(raw.get("paths", d.paths)),
        debounce_s=float(raw.get("debounce_s", d.debounce_s)),
        unsynced_alert_s=float(raw.get("unsynced_alert_s", d.unsynced_alert_s)),
        unsaved_alert_s=float(raw.get("unsaved_alert_s", d.unsaved_alert_s)),
        save_prefixes=tuple(raw.get("save_prefixes", d.save_prefixes)),
        unsaved_ignore=tuple(raw.get("unsaved_ignore", d.unsaved_ignore)),
    )


def load_registry(text: str) -> Registry:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise RegistryError("registry is not valid JSON: %s" % exc)
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise RegistryError("registry must be an object with an `events` list")
    events, seen = [], set()
    for raw in data["events"]:
        if not isinstance(raw, dict):
            raise RegistryError("an event must be an object")
        eid = raw.get("id") or ""
        if not _ID.match(eid):
            raise RegistryError("event id %r is not kebab-case" % eid)
        if eid in seen:
            raise RegistryError("duplicate event id %r" % eid)
        seen.add(eid)
        handler = raw.get("handler")
        if handler not in APPROVED_HANDLERS:
            raise RegistryError("event %s: handler %r is not an approved module" % (eid, handler))
        triggers = tuple(_trigger(eid, t) for t in raw.get("triggers") or [])
        liveness = raw.get("liveness") or ""
        if liveness and liveness not in LIVENESS_CLASSES:
            raise RegistryError("event %s: unknown liveness %r (known: %s)"
                                % (eid, liveness, ", ".join(LIVENESS_CLASSES)))
        events.append(Event(eid, raw.get("description") or "", handler, triggers, liveness))
    return Registry(tuple(events), _watch(data.get("watch")))


# ---------------------------------------------------------------- rendering


def render_claude_hooks_json(registry: Registry, python=ORIGIN_PYTHON, bin_dir=ORIGIN_BIN) -> dict:
    """Claude Code's hooks.json, from the registry's claude-hook triggers.

    Claude events appear in the order the registry first uses them; within one, triggers
    sharing a matcher share a group, in registry order. That order is what makes the
    output byte-comparable with the file build_plugin.py used to copy from settings.json.
    """
    hooks = {}
    for _event, trig in registry.triggers("claude-hook"):
        spec = trig.spec
        groups = hooks.setdefault(spec["event"], [])
        matcher = spec.get("matcher")
        group = next((g for g in groups if g.get("matcher") == matcher), None)
        if group is None:
            group = {"matcher": matcher, "hooks": []} if matcher else {"hooks": []}
            groups.append(group)
        entry = {"type": "command", "command": "%s %s/%s" % (python, bin_dir, spec["command"])}
        for key in CLAUDE_HOOK_OPTIONS:
            if key in spec:
                entry[key] = spec[key]
        group["hooks"].append(entry)
    return {"hooks": hooks}


def strip_frontmatter(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + len("\n---\n"):]
    return text


def _manual(event):
    out = []
    for t in event.triggers:
        if t.kind == "cli":
            out.append("`%s`" % t.spec["command"])
        elif t.kind == "mcp":
            out.append("MCP tool `%s`" % t.spec["tool"])
    return out


# Every agent that reads AGENTS.md learns to offer the first run: nothing on the machine asks for accounts,
# credentials or scheduled jobs until the user says yes to each one there.
FIRST_RUN_BLOCK = [
    "## First session on this machine",
    "",
    "Check whether this machine has had its first run: `python3 integrations/first-run/first_run.py status` "
    "(exit 0 done, exit 3 not yet; the answers live in `<brain state>/first-run.json`). If it has not, ask the "
    "user, before any other work, whether to run it now with `bash integrations/first-run/setup.sh` in their own "
    "terminal. It asks one step at a time, and installs nothing without a yes, whether to connect a KeePass "
    "database, Google accounts, object storage, an alert email, the MCP server for their agents, scheduled "
    "jobs, and CLI-agent routines with a token pool. Never run it without the user's yes, and never answer its "
    "questions for them. If they decline, say it can be run any time and carry on; ask again only in a later "
    "session.",
    "",
]


def render_agents_md(registry: Registry, protocol_text: str, known_triggers) -> str:
    """AGENTS.md: the protocol, every Brain event, and what is lost without an adapter.

    `known_triggers` is what fires automatically for the agent reading it. An event that
    only an agent adapter would fire, when that adapter is not among them, goes into the
    degraded-mode table with its manual equivalent — or is named as lost if it has none.
    """
    known = set(known_triggers)
    automatic = [k for k in TRIGGER_KINDS if k not in MANUAL]
    lines = [
        "# AGENTS.md",
        "",
        "<!-- Generated by _bin/gen_instructions.py from 90-Meta/events.json and "
        "90-Meta/PROTOCOL-COMPACT.md. Do not edit by hand: edit those and regenerate. -->",
        "",
        "## Protocol",
        "",
        strip_frontmatter(protocol_text).strip(),
        "",
    ] + FIRST_RUN_BLOCK + [
        "## Brain events",
        "",
        "| event | what it does | fires automatically through |",
        "|---|---|---|",
    ]
    degraded = []
    for e in registry.events:
        fires = sorted({t.kind for t in e.triggers if t.kind in automatic and t.kind in known})
        lines.append("| `%s` | %s | %s |" % (e.id, e.description, ", ".join(fires) or "nothing: call it by hand"))
        adapter_only = any(t.kind in automatic and t.kind not in AGENT_INDEPENDENT for t in e.triggers)
        if adapter_only and not fires:
            degraded.append(e)
    if degraded:
        lines += [
            "",
            "## Without an agent adapter",
            "",
            "No adapter wires these events into the agent reading this, so they do not fire on "
            "their own. Run the manual equivalent yourself at the moment the event would happen.",
            "",
            "| event | what it does | manual equivalent |",
            "|---|---|---|",
        ]
        for e in degraded:
            manual = _manual(e)
            lines.append("| `%s` | %s | %s |" % (e.id, e.description,
                                                 " or ".join(manual) if manual else "none: lost without an adapter"))
    return "\n".join(lines) + "\n"


HOOKS_DOC_REL = "90-Meta/HOOKS-WITHOUT-CLAUDE.md"


def render_hooks_without_claude(registry: Registry) -> str:
    """90-Meta/HOOKS-WITHOUT-CLAUDE.md: every event's ways to run with no Claude Code.

    Per event: its Claude Code hook, the `brain hook <id>` equivalent, every CLI, MCP, git
    hook, file-watch and launchd trigger, and the exact handler command. Generated, so it
    cannot drift from the registry the way a hand-written claim can.
    """
    lines = [
        "# Brain events without Claude Code",
        "",
        "<!-- Generated by _bin/gen_instructions.py from 90-Meta/events.json. Do not edit by hand: "
        "edit the registry and regenerate. -->",
        "",
        "Every Brain event is Brain's, not an agent's. For each one, this page lists every way to trigger it "
        "that does not need Claude Code, and the exact command its handler runs. Claude Code's own wiring "
        "(`integrations/claude-code/plugin/brain/hooks/hooks.json`) and `AGENTS.md` are generated from the same registry.",
        "",
        "## How a hook handler is called",
        "",
        "- `brain hook <event-id>` (`integrations/cli/brain`) runs the event's hook command from the vault's "
        "`_bin`, with the vault as working directory and a JSON object on stdin: `session_id`, `cwd`, `source` "
        "(`cli`) and `hook_event_name`. `--payload '<json object>'` adds the event's own fields, for example "
        "`tool_name` and `tool_input` for a tool-use event.",
        "- The exit code is the handler's. As in Claude Code, 0 lets the action go on and 2 blocks it.",
        "- Verify the exact JSON fields a handler reads (its script under `_bin/`) before wiring another agent's "
        "hook to it. The contract is Claude Code's hook contract, and `brain hook` only guarantees `session_id`, "
        "`cwd`, `source` and `hook_event_name`.",
        "- File-watch actions run from `brain_watch.py tick` (launchd, every 60 s) with no stdin. Git hooks run "
        "from `githooks/` with git's own arguments.",
        "",
        "## Heartbeats and liveness",
        "",
        "- Every Claude Code hook handler records one JSON line per run in `<brain state>/logs/heartbeat.jsonl` "
        "(`brainlib.heartbeat`): the event id, the short session id, `ok`, `blocked`, `off` or `error` with the "
        "exception class, the exit code and the duration. The line is written even when the handler fails, and only "
        "for a run that received a hook payload on stdin.",
        "- The guardian reads it with no agent involved (`python3 ~/Brain/_bin/guardian.py status`, section "
        "`hook liveness`): an active Claude Code session with no heartbeat is `hooks:not-firing`, a hook that keeps "
        "failing is `hooks:failing:<event>`, and a hook that stops firing is `hooks:silent:<event>`. It also runs "
        "every hook in a scratch state with a canned payload and reports `hooks:probe:<event>` when one fails.",
        "- Each event's liveness says what to expect: `session` fires in every session that finished a turn, "
        "`regular` fires within a week of normal use, `conditional` fires only when its situation arises and is "
        "never called silent.",
        "",
        "## Events",
    ]
    for e in registry.events:
        hook_command = "brain hook %s" % e.id
        hooks = [t for t in e.triggers if t.kind == "claude-hook"]
        lines += ["", "### `%s`" % e.id, "", e.description, ""]
        for t in hooks:
            matcher = ", matcher `%s`" % t.spec["matcher"] if t.spec.get("matcher") else ""
            lines.append("- Claude Code hook: `%s`%s" % (t.spec["event"], matcher))
        if hooks and e.liveness:
            lines.append("- Liveness: `%s`" % e.liveness)
        if hooks:
            lines.append("- Without Claude Code: `%s`" % hook_command)
        for t in e.triggers:
            spec = t.spec
            if t.kind == "cli" and spec["command"] != hook_command:
                lines.append("- CLI: `%s`" % spec["command"])
            elif t.kind == "mcp":
                lines.append("- MCP tool: `%s` (`integrations/mcp/server.py`)" % spec["tool"])
            elif t.kind == "git-hook":
                lines.append("- Git hook: `githooks/%s` runs `_bin/%s` with git's arguments" % (spec["hook"], spec["command"]))
            elif t.kind == "file-watch":
                extra = " `--sid <session id> --paths <changed notes>`" if spec["action"] == "ledger-update" else ""
                lines.append("- File watch: action `%s`, `brain_watch.py tick` runs `_bin/%s`%s"
                             % (spec["action"], spec["command"], extra))
            elif t.kind == "launchd":
                lines.append("- launchd job: `%s`" % spec["label"])
        for t in hooks:
            lines.append("- Handler command: `python3 _bin/%s`, stdin: the hook JSON object" % t.spec["command"])
    lines += [
        "",
        "## Wiring another agent",
        "",
        "Examples only: verify against that agent's current documentation, not tested here.",
        "",
        "An agent whose config runs a shell command on an event (a command hook):",
        "",
        "```json",
        '{"hooks": {"<the agent\'s before-tool event>": [{"type": "command", "command": '
        '"~/Brain/integrations/cli/brain hook pre-write-gate --payload \'<the tool call as a JSON object>\'"}]}}',
        "```",
        "",
        "An agent that only reads an instruction file (a Markdown protocol or rules file): point that file at the "
        "vault's `AGENTS.md`. Its table of events that do not fire without an adapter lists the command to run by "
        "hand for each, `brain hook <event-id>` included.",
    ]
    return "\n".join(lines) + "\n"


def _git_hook_script(registry: Registry, hook: str) -> str:
    entries = [(e, t) for e, t in registry.triggers("git-hook") if t.spec["hook"] == hook]
    lines = [
        "#!/bin/sh",
        "# Brain %s hook. Generated by _bin/brain_watch.py install from 90-Meta/events.json." % hook,
        "# Do not edit by hand: edit the registry and run brain_watch.py install again.",
    ]
    if hook == "pre-commit":
        lines += [
            "#",
            "# Blocks a commit only when a staged file carries something that looks like a secret.",
            "# Staged changes to 10-Projects/ or 70-Entities/ not written through vw.py only warn.",
            "# Escape hatch: `git commit --no-verify` skips this hook, and the secret scan with it:",
            "# a credential committed that way reaches the remote. Use it only when the scan is wrong.",
        ]
    if not entries:
        return "\n".join(lines + ["exit 0", ""])
    lines += [
        "",
        "ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0",
        "# A clone without Brain's engine has nothing to run: never block it.",
        '[ -x "$ROOT/_bin/pywrap.sh" ] || exit 0',
    ]
    for event, trig in entries:
        lines += ["# event: %s" % event.id,
                  '"$ROOT/_bin/pywrap.sh" "$ROOT/_bin/%s" "$@" || exit $?' % trig.spec["command"]]
    lines += ["exit 0", ""]
    return "\n".join(lines)


def render_git_pre_commit(registry: Registry) -> str:
    return _git_hook_script(registry, "pre-commit")


def render_git_post_commit(registry: Registry) -> str:
    return _git_hook_script(registry, "post-commit")


# ---------------------------------------------------------------- the watch tick


@dataclass(frozen=True)
class WatchAction:
    kind: str
    paths: tuple = ()


@dataclass(frozen=True)
class WatchMemory:
    last_change_at: object = None
    sync_pending: bool = False
    unsaved_since: object = None
    alerted: tuple = ()


@dataclass(frozen=True)
class TickPlan:
    actions: list
    memory: WatchMemory
    raise_alerts: list
    clear_alerts: list


UNSAVED_KEY = "watch:unsaved-writes"
UNSYNCED_KEY = "watch:unsynced"


def _under(path, prefixes):
    return any(path == p or path.startswith(p.rstrip("/") + "/") for p in prefixes)


def plan_watch_tick(previous, current, now, memory, watch, unsynced_oldest=None) -> TickPlan:
    """Decide one file-watch tick from two {path: mtime} snapshots. No sleeping, no IO.

    - A changed note credits the ledger (to whoever the session source resolves, "system"
      when no agent session is behind it) and reindexes; an added or removed note also
      relinks, since link targets appeared or vanished.
    - Any change restarts the sync debounce; a sync runs once nothing changed for
      `debounce_s`.
    - With no agent adapter there is no Stop memory gate, so it is replaced by detection:
      files changed with no saved note for `unsaved_alert_s`, and vault changes unsynced
      for `unsynced_alert_s`, each raise an alert once and clear it once.
    """
    alerted = set(memory.alerted or ())
    last_change_at, sync_pending, unsaved_since = memory.last_change_at, memory.sync_pending, memory.unsaved_since
    actions, raise_alerts, clear_alerts = [], [], []

    if previous is None:
        added, removed, changed = [], [], []
    else:
        added = sorted(set(current) - set(previous))
        removed = sorted(set(previous) - set(current))
        modified = sorted(p for p in set(current) & set(previous) if current[p] != previous[p])
        changed = sorted(set(added) | set(removed) | set(modified))

    notes = [p for p in changed if p.endswith(".md")]
    present_notes = tuple(p for p in notes if p not in removed)
    if present_notes:
        actions.append(WatchAction("ledger-update", present_notes))
    if notes:
        actions.append(WatchAction("index-trigger", tuple(notes)))
    relink = tuple(p for p in added + removed if p.endswith(".md"))
    if relink:
        actions.append(WatchAction("linkfix-trigger", relink))

    if changed:
        last_change_at, sync_pending = now, True
    elif sync_pending and last_change_at is not None and now - last_change_at >= watch.debounce_s:
        actions.append(WatchAction("sync-debounce"))
        sync_pending = False

    saved = [p for p in present_notes if _under(p, watch.save_prefixes)]
    others = [p for p in changed if not _under(p, watch.save_prefixes) and not _under(p, watch.unsaved_ignore)]
    if saved:
        unsaved_since = None
        if UNSAVED_KEY in alerted:
            clear_alerts.append(UNSAVED_KEY)
            alerted.discard(UNSAVED_KEY)
    elif others and unsaved_since is None:
        unsaved_since = now
    if unsaved_since is not None and now - unsaved_since >= watch.unsaved_alert_s and UNSAVED_KEY not in alerted:
        raise_alerts.append((UNSAVED_KEY,
                             "files changed for %.1f h with no note saved (writes attributed to system: "
                             "no agent session recorded them)" % ((now - unsaved_since) / 3600)))
        alerted.add(UNSAVED_KEY)

    if unsynced_oldest is not None and now - unsynced_oldest >= watch.unsynced_alert_s:
        if UNSYNCED_KEY not in alerted:
            raise_alerts.append((UNSYNCED_KEY, "vault changes unsynced for %.0f min"
                                 % ((now - unsynced_oldest) / 60)))
            alerted.add(UNSYNCED_KEY)
    elif UNSYNCED_KEY in alerted:
        clear_alerts.append(UNSYNCED_KEY)
        alerted.discard(UNSYNCED_KEY)

    memory = WatchMemory(last_change_at, sync_pending, unsaved_since, tuple(sorted(alerted)))
    return TickPlan(actions, memory, raise_alerts, clear_alerts)


# ---------------------------------------------------------------- the agent watch: hooks and account switches

REPAIR_TRIGGER_MIN_S = 300.0


def claude_hook_commands(registry: Registry) -> list:
    """Every claude-hook command the registry wires (`vault_sync.py --hook`), once each, in order."""
    out = []
    for _event, trig in registry.triggers("claude-hook"):
        command = trig.spec["command"]
        if command not in out:
            out.append(command)
    return out


def _live_hook_commands(settings_hooks):
    for groups in (settings_hooks or {}).values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            for hook in group.get("hooks") or []:
                if isinstance(hook, dict) and isinstance(hook.get("command"), str):
                    yield hook["command"].strip()


def hooks_look_present(settings_hooks, expected_commands) -> bool:
    """A cheap look at Claude Code's `hooks` block: is every registry command wired somewhere?

    A command counts when a live hook's command is it, or ends with `/` plus it, so the
    interpreter and the vault path may differ. This is only the trigger for a repair; what
    exactly is wrong and how to merge it back is the guardian's job.
    """
    expected = list(expected_commands or ())
    if not expected:
        return True
    live = list(_live_hook_commands(settings_hooks if isinstance(settings_hooks, dict) else {}))
    return all(any(c == e or c.endswith("/" + e) for c in live) for e in expected)


def repair_trigger_due(last_trigger, now, min_interval_s=REPAIR_TRIGGER_MIN_S) -> bool:
    """At most one watch-triggered repair per `min_interval_s`: a hook that stays broken must not
    spawn a repair every minute."""
    return last_trigger is None or now - last_trigger >= min_interval_s


ACCOUNT_SWITCH_KEY = "account:switch"
BRIDGE_STALE_KEY = "bridge:stale"
_ARROW = r"\s*(?:→|->)\s*"
_TRANSITION = re.compile(r"\[account\] Login-state transition \((?:loggedOut:\s*([^\s,]+)" + _ARROW
                         + r"([^\s,]+),\s*)?uuid:\s*([^\s,)]+)" + _ARROW + r"([^\s,)]+)\)")
_BRIDGE_CONNECT = re.compile(r"claude-in-chrome\] Connecting to bridge.*?"
                             r"wss://bridge\.claudeusercontent\.com/chrome/([0-9A-Za-z-]+)")
_NO_ACCOUNT = ("", "none", "null", "undefined")


@dataclass(frozen=True)
class LoginTransition:
    old_uuid: str
    new_uuid: str
    logged_out_before: object = None
    logged_out_after: object = None


@dataclass(frozen=True)
class AccountWatch:
    account_uuid: object = None     # the account Claude Desktop is logged into, as far as the log says
    bridge_uuid: object = None      # the account Claude in Chrome's bridge last connected under
    bridge_stale: bool = False


@dataclass(frozen=True)
class AccountWatchPlan:
    memory: dict
    raise_alerts: list
    clear_alerts: list


def parse_login_transitions(text: str) -> list:
    """Claude Desktop's `[account] Login-state transition (loggedOut: X → Y, uuid: A → B)` lines.

    The wording is not a documented format: a line that does not match is skipped, never an
    error, so an app update that rewords it fails closed (no switch seen) rather than loud.
    """
    out = []
    for line in (text or "").splitlines():
        m = _TRANSITION.search(line)
        if m:
            out.append(LoginTransition(m.group(3), m.group(4), m.group(1), m.group(2)))
    return out


def _real(uuid) -> bool:
    return bool(uuid) and uuid.lower() not in _NO_ACCOUNT


def same_account(a, b) -> bool:
    """Two uuids name the same account; one side may be truncated to 8 or more characters."""
    if not (_real(a) and _real(b)):
        return False
    a, b = a.lower(), b.lower()
    return min(len(a), len(b)) >= 8 and (a.startswith(b) or b.startswith(a))


def advance_account_watch(memory: AccountWatch, text: str):
    """Walk new main.log text in order. Returns (memory, switches).

    The recipe from the 2026-09-13 diagnosis: the bridge is pinned to the account it
    connected under, so it is stale once a transition moves away from that account, until
    it connects again under the current one.
    """
    account, bridge, stale = memory.account_uuid, memory.bridge_uuid, memory.bridge_stale
    switches = []
    for line in (text or "").splitlines():
        m = _TRANSITION.search(line)
        if m:
            t = LoginTransition(m.group(3), m.group(4), m.group(1), m.group(2))
            if (_real(t.old_uuid) or _real(t.new_uuid)) and not same_account(t.old_uuid, t.new_uuid):
                switches.append(t)
                if bridge and same_account(bridge, t.old_uuid):
                    stale = True
            account = t.new_uuid if _real(t.new_uuid) else None
            continue
        m = _BRIDGE_CONNECT.search(line)
        if m:
            bridge = m.group(1)
            stale = account is not None and not same_account(bridge, account)
    return AccountWatch(account, bridge, stale), switches


def _short(uuid) -> str:
    return (uuid or "none")[:8]


def plan_account_watch(memory: dict, text: str, fresh: bool = False) -> AccountWatchPlan:
    """What one tick of new main.log text means for the guardian's alerts.

    A switch is a warning for one tick, not an open problem: switching accounts is normal,
    and the notice exists so a broken hook or bridge right after it is not a mystery. A stale
    bridge is a warning while it lasts. `fresh` is the first read of a log with history in
    it: its old switches are not news, but a bridge that is stale right now is.
    """
    memory = memory or {}
    before = AccountWatch(memory.get("account_uuid"), memory.get("bridge_uuid"), bool(memory.get("bridge_stale")))
    after, switches = advance_account_watch(before, text)
    switch_alerted = bool(memory.get("switch_alerted"))
    raises, clears = [], []
    if switches and not fresh:
        last = switches[-1]
        raises.append((ACCOUNT_SWITCH_KEY,
                       "Claude Desktop switched account %s to %s%s: Brain's Claude Code hooks are re-checked within "
                       "a minute; Claude in Chrome keeps using the old account until the Claude app is restarted"
                       % (_short(last.old_uuid), _short(last.new_uuid),
                          " (%d switches since the last tick)" % len(switches) if len(switches) > 1 else "")))
        switch_alerted = True
    elif switch_alerted:
        clears.append(ACCOUNT_SWITCH_KEY)
        switch_alerted = False
    if after.bridge_stale and not before.bridge_stale:
        raises.append((BRIDGE_STALE_KEY,
                       "Claude in Chrome's bridge is still connected under account %s, which Claude Desktop switched "
                       "away from: quit and restart the Claude app; routines that need the browser run degraded "
                       "until then" % _short(after.bridge_uuid)))
    elif before.bridge_stale and not after.bridge_stale:
        clears.append(BRIDGE_STALE_KEY)
    new_memory = {"account_uuid": after.account_uuid, "bridge_uuid": after.bridge_uuid,
                  "bridge_stale": after.bridge_stale, "switch_alerted": switch_alerted}
    return AccountWatchPlan(new_memory, raises, clears)


# ---------------------------------------------------------------- smoke-check isolation


def _norm(path: str) -> str:
    return path.rstrip("/") or "/"


def main_log_isolation_problem(main_log: str, real_main_log: str, state_dir: str, real_state_dirs) -> str:
    """Why a tick must not run, or "" when it may.

    BRAIN_CLAUDE_MAIN_LOG only chooses which main.log is read; the tick still writes the
    account watch, the main.log cursor and raised alerts into the state directory. A scratch
    main.log read into the real state would leave a real `bridge:stale` or `account:switch`
    for the guardian to announce. So a main.log other than the real one needs a state
    directory other than the real ones (the default and the legacy one). Paths arrive
    resolved by the caller; this compares them and nothing else.
    """
    if not main_log or _norm(main_log) == _norm(real_main_log):
        return ""
    if _norm(state_dir) in {_norm(d) for d in real_state_dirs}:
        return ("BRAIN_CLAUDE_MAIN_LOG points at a scratch main.log (%s) but the state directory is the real "
                "one (%s): set BRAIN_STATE to a scratch directory too" % (main_log, state_dir))
    return ""
