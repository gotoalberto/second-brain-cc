"""The Brain guardian's rules, with no IO at all.

Everything the guardian decides lives here: how Brain's hooks merge into a settings file
that other tools also write, when a problem is worth telling the user about and when it
is the same problem as fifteen minutes ago, when a routine is due, and what counts as a
problem in the first place. The inputs are plain values and "now" is always passed in,
so every rule can be tested with literals.

What is deliberately NOT imported here: os, subprocess, pathlib, time, json or any
clock. Reading the world is the adapters' job (guardian_core/adapters.py).
"""

from __future__ import annotations

import copy
import datetime as dt
import re
import shlex
from dataclasses import dataclass, field

FAIL = "fail"
WARN = "warn"

# The paths hooks.json and the plists were written with. Another machine rewrites them.
ORIGIN_VAULT = "/home/brain-origin/Brain"
ORIGIN_HOME = "/home/brain-origin"


# ---------------------------------------------------------------- findings


@dataclass(frozen=True)
class Finding:
    key: str                  # stable across runs: it is what alert de-duplication keys on
    severity: str             # FAIL or WARN
    summary: str              # one line, may change wording between runs
    repairable: bool = False  # `guardian.py repair` knows how to fix it


@dataclass(frozen=True)
class Report:
    findings: list = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return not any(f.severity == FAIL for f in self.findings)

    @property
    def exit_code(self) -> int:
        """`guardian.py check`'s exit: 0 ok, 1 warn, 2 fail. For people and scripts only."""
        if not self.findings:
            return 0
        return 1 if self.healthy else 2


GUARDIAN_LABEL = "com.secondbrain.guardian"
# The same job under systemd or cron (integrations/first-run installs one of the three).
GUARDIAN_LABELS = (GUARDIAN_LABEL, "second-brain-guardian")


def repair_exit_code(errors) -> int:
    """`guardian.py repair`'s exit, which launchd records as the job's LastExitStatus.

    Findings never set it: they go to status and alerts. A findings-driven exit made the
    guardian's own job look failed, which the next run reported as a finding, which kept
    the exit non-zero: an alert that could never clear. Non-zero only when the run's own
    work errored (an unhandled exception exits non-zero by itself).
    """
    return 1 if errors else 0


# ---------------------------------------------------------------- hooks

_SCRIPT = re.compile(r"\.py$")


def _tokens(command: str) -> list:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def hook_identity(command: str):
    """What makes a hook "the same Brain hook" wherever it was installed.

    The script's basename plus its arguments: `vault_sync.py --hook`. The interpreter and
    the directory are left out on purpose, because a moved vault or a different python is
    exactly the breakage repair has to recognise as "this hook, with a wrong path".
    """
    toks = _tokens(command or "")
    for i, tok in enumerate(toks):
        if _SCRIPT.search(tok):
            base = tok.rsplit("/", 1)[-1]
            return " ".join([base] + toks[i + 1:])
    return None


@dataclass(frozen=True)
class HookChange:
    kind: str       # added | fixed | moved | deduplicated
    event: str
    identity: str

    @property
    def key(self) -> str:
        return "hooks:%s:%s" % (self.event, self.identity)

    @property
    def text(self) -> str:
        verbs = {"added": "missing", "fixed": "differs from canonical",
                 "moved": "under the wrong matcher", "deduplicated": "wired more than once",
                 "removed": "runs a Brain script that does not exist"}
        return "hook %s %s: %s" % (self.event, self.identity, verbs.get(self.kind, self.kind))


def _matcher(group: dict) -> str:
    return group.get("matcher") or ""


def merge_hooks(canonical: dict, current: dict):
    """Merge Brain's canonical hooks into the hooks block a settings file already has.

    Only hooks whose identity appears in `canonical` are Brain's. Those are added when
    missing, rewritten when they differ, moved when they sit under another matcher and
    collapsed when wired twice. Everything else — another tool's hooks, other events, a
    Brain-looking script canonical no longer lists — is kept exactly as it was: the file
    is shared, and a repair that deletes what it does not recognise is a clobber.

    Returns (merged, changes). Inputs are never mutated.
    """
    merged = copy.deepcopy(current or {})
    changes = []
    for event, can_groups in (canonical or {}).items():
        groups = merged.setdefault(event, [])
        for can_group in can_groups:
            matcher = _matcher(can_group)
            for can_hook in can_group.get("hooks", []):
                ident = hook_identity(can_hook.get("command", ""))
                if ident is None:
                    continue
                # every place this identity is wired today, in order
                places = [(gi, hi) for gi, g in enumerate(groups)
                          for hi, h in enumerate(g.get("hooks", []))
                          if hook_identity(h.get("command", "")) == ident]
                if not places:
                    _group_for(groups, can_group).setdefault("hooks", []).append(
                        copy.deepcopy(can_hook))
                    changes.append(HookChange("added", event, ident))
                    continue
                gi, hi = places[0]
                kinds = []
                if len(places) > 1:
                    for dgi, dhi in reversed(places[1:]):
                        del groups[dgi]["hooks"][dhi]
                    kinds.append("deduplicated")
                if _matcher(groups[gi]) != matcher:
                    del groups[gi]["hooks"][hi]
                    _group_for(groups, can_group).setdefault("hooks", []).append(
                        copy.deepcopy(can_hook))
                    kinds.append("moved")
                elif groups[gi]["hooks"][hi] != can_hook:
                    groups[gi]["hooks"][hi] = copy.deepcopy(can_hook)
                    kinds.append("fixed")
                for kind in kinds:
                    changes.append(HookChange(kind, event, ident))
        merged[event] = [g for g in groups if g.get("hooks")]
        if not merged[event]:
            del merged[event]
    return merged, changes


# The vault directories whose scripts only Brain puts there. A hook that runs one is Brain's.
BRAIN_SCRIPT_DIRS = ("_bin", "githooks", "integrations")


def brain_script_dirs(vault: str) -> tuple:
    """`<vault>/_bin/`, `<vault>/githooks/`, `<vault>/integrations/`, with the trailing slash."""
    base = (vault or "").rstrip("/")
    return tuple("%s/%s/" % (base, d) for d in BRAIN_SCRIPT_DIRS)


def _brain_paths(command: str, brain_dirs) -> list:
    """The absolute paths in `command` that sit under one of Brain's dirs.

    A path with a `..` segment is never Brain's: it can climb out of the vault, and a rule
    that removes things must not guess where a path really lands.
    """
    return [t for t in _tokens(command or "")
            if t.startswith("/") and ".." not in t.split("/")
            and any(t.startswith(d) for d in brain_dirs)]


def brain_hook_paths(hooks: dict, brain_dirs) -> list:
    """Every path under Brain's dirs that a hooks block names, once each, in first-seen order.

    These are the paths the adapter checks on disk before calling `reconcile_hooks`.
    """
    seen = []
    for groups in (hooks or {}).values():
        for g in groups:
            for h in g.get("hooks", []):
                for p in _brain_paths(h.get("command", ""), brain_dirs):
                    if p not in seen:
                        seen.append(p)
    return seen


def reconcile_hooks(canonical: dict, current: dict, brain_dirs, missing_paths):
    """Remove stale Brain hooks, then merge the canonical ones (`merge_hooks`).

    Stale means: the command runs a path under the vault's Brain dirs, that path is in
    `missing_paths` (the adapter looked on disk), and the hook's identity is not one
    canonical lists. Such a hook can only fail on every event, and nobody but Brain put a
    script path under the vault's `_bin/` there, so removing it is not a clobber. What is
    kept: every hook outside the vault, even with a missing script (not Brain's to judge);
    a Brain-looking hook from another directory (merge_hooks rewrites it if canonical knows
    it); a canonical hook whose script is missing (that is the missing-path finding, and
    removing it would only re-add it on every run).

    Returns (merged, changes), removals first. Inputs are never mutated.
    """
    known = {hook_identity(h.get("command", ""))
             for groups in (canonical or {}).values() for g in groups for h in g.get("hooks", [])}
    known.discard(None)
    missing = set(missing_paths or ())
    pruned = copy.deepcopy(current or {})
    changes = []
    for event in list(pruned):
        groups = pruned[event]
        emptied = False
        for g in groups:
            kept = []
            for h in g.get("hooks", []):
                command = h.get("command", "")
                gone = [p for p in _brain_paths(command, brain_dirs) if p in missing]
                ident = hook_identity(command)
                if gone and ident not in known:
                    changes.append(HookChange("removed", event, ident or gone[0]))
                else:
                    kept.append(h)
            if len(kept) != len(g.get("hooks", [])):
                g["hooks"] = kept
                emptied = emptied or not kept
        if emptied:
            pruned[event] = [g for g in groups if g.get("hooks")]
            if not pruned[event]:
                del pruned[event]
    merged, merge_changes = merge_hooks(canonical, pruned)
    return merged, changes + merge_changes


def _group_for(groups: list, can_group: dict) -> dict:
    matcher = _matcher(can_group)
    for g in groups:
        if _matcher(g) == matcher:
            return g
    new = {k: copy.deepcopy(v) for k, v in can_group.items() if k != "hooks"}
    new["hooks"] = []
    groups.append(new)
    return new


def localize_hooks(hooks: dict, vault: str, home: str,
                   origin_vault: str = ORIGIN_VAULT, origin_home: str = ORIGIN_HOME) -> dict:
    """hooks.json carries the original machine's paths; rewrite them for this one.

    The vault first, then the home: the vault path contains the home path, and replacing
    the home first would turn the vault into `<new home>/Brain` even when it lives
    somewhere else.
    """
    out = copy.deepcopy(hooks or {})
    for groups in out.values():
        for g in groups:
            for h in g.get("hooks", []):
                c = h.get("command")
                if isinstance(c, str):
                    h["command"] = c.replace(origin_vault, vault).replace(origin_home, home)
    return out


def hook_command_paths(hooks: dict) -> list:
    """Every absolute path a hook command names, once each, in first-seen order."""
    seen = []
    for groups in (hooks or {}).values():
        for g in groups:
            for h in g.get("hooks", []):
                for tok in _tokens(h.get("command", "")):
                    if tok.startswith("/") and tok not in seen:
                        seen.append(tok)
    return seen


# ---------------------------------------------------------------- routines

RUNNABLE_TYPES = ("shell", "agent")


def parse_days(spec: str) -> set:
    """`*` = every day. Otherwise ISO weekdays: 1=Mon .. 7=Sun. Accepts `1-5`, `1,3,5`, `6`."""
    spec = (spec or "").strip()
    if spec in ("*", "", "-"):
        return set(range(1, 8))
    days = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            days.update(range(int(a), int(b) + 1))
        elif part:
            days.add(int(part))
    return days


def machine_matches(machine, host: str, is_mine=None) -> bool:
    """Does a registry `machine` cell name this machine?

    `*` is every machine. The bare hostname is how rows were written before machine identity
    existed, and keeps working. Anything else goes to `is_mine` (machine_identity.machine_is_mine
    in production), which accepts this machine's key, its uuid, and every historical form.
    """
    machine = str(machine or "").strip()
    if not machine:
        return False
    if machine in ("*", host):
        return True
    return bool(is_mine is not None and is_mine(machine))


EVERY_RE = re.compile(r"^every\s+(\d+)\s*h$", re.I)


def parse_every_hours(spec):
    """`every 1h`, `every 6h` in the time column, or None when it is a plain `HH:MM`.

    An interval row repeats through the day instead of firing once. The runner already polls
    every 10 minutes, so the cadence needs no second scheduler: only the due-ness rule has to
    know the difference.
    """
    m = EVERY_RE.match(str(spec or "").strip())
    return int(m.group(1)) if m and int(m.group(1)) > 0 else None


def routine_due(routine: dict, last_run_date, now: dt.datetime, host: str, is_mine=None,
                last_run_at=None):
    """Returns (should_run, reason_if_not). The one due-ness rule tasks.py runs by.

    A routine fires when it is enabled, belongs to this machine (`machine_matches`), has a
    schedule, is of a type the runner executes, today is one of its days, its time has passed,
    and it has not already run today. That is what lets a 10-minute poll run a 06:00
    routine once, and a machine asleep at 06:00 still run it when it wakes.

    A `time` of `every Nh` instead of `HH:MM` repeats through the day: the daily mark is not
    used, the gap since `last_run_at` is. A machine asleep over an interval does not catch it
    up when it wakes; it runs at the next poll and the clock restarts from there.
    """
    if not routine.get("enabled"):
        return False, "disabled"
    if not machine_matches(routine.get("machine"), host, is_mine):
        return False, "belongs to %s" % routine.get("machine")
    if routine.get("time") == "--":
        return False, "manual only (no schedule)"
    if routine.get("type") not in RUNNABLE_TYPES:
        return False, "type '%s' is not run by this runner" % routine.get("type")
    if now.isoweekday() not in parse_days(routine.get("days", "*")):
        return False, "not scheduled today"
    every = parse_every_hours(routine.get("time"))
    if every:
        if not last_run_at:
            return True, ""
        try:
            last = dt.datetime.fromisoformat(str(last_run_at))
        except (TypeError, ValueError):
            return True, ""
        due_at = last + dt.timedelta(hours=every)
        if now < due_at:
            return False, "not yet (every %dh, next %s)" % (every, due_at.strftime("%H:%M"))
        return True, ""
    hh, mm = (int(x) for x in routine["time"].split(":"))
    if now < now.replace(hour=hh, minute=mm, second=0, microsecond=0):
        return False, "not yet (%s)" % routine["time"]
    if last_run_date == now.strftime("%Y-%m-%d"):
        return False, "already ran today"
    return True, ""


# ---------------------------------------------------------------- alerting


@dataclass(frozen=True)
class AlertAction:
    kind: str       # notify-change | notify-digest | notify-repair | mail
    subject: str
    body: str


DIGEST_EVERY = dt.timedelta(hours=24)
_RANK = {WARN: 1, FAIL: 2}


def _iso(t: dt.datetime) -> str:
    return t.isoformat(timespec="seconds")


def _parse(s):
    try:
        return dt.datetime.fromisoformat(s) if s else None
    except (TypeError, ValueError):
        return None


def _line(f: Finding) -> str:
    return "[%s] %s%s" % (f.severity, f.summary, "  (repairable)" if f.repairable else "")


def decide(previous: dict, findings: list, now: dt.datetime, digest_every=DIGEST_EVERY):
    """Decide what to tell the user, given what was already told.

    A problem is announced when it first appears, when it escalates from warn to fail,
    and when it goes away. While it stays open and unchanged the guardian is quiet,
    except for one digest a day listing what is still open — a check every 15 minutes
    that re-announced the same thing would be muted by the user within a morning, and
    then the next real problem would go unheard.

    Returns (new_state, actions). `previous` is what the last call returned (or None).
    """
    previous = previous or {}
    prev = previous.get("active") or {}
    last_digest = _parse(previous.get("last_digest"))
    current = {}
    for f in findings:
        current.setdefault(f.key, f)

    new = [f for k, f in current.items() if k not in prev]
    escalated = [f for k, f in current.items()
                 if k in prev and _RANK.get(f.severity, 0) > _RANK.get(prev[k].get("severity"), 0)]
    resolved = [(k, v) for k, v in prev.items() if k not in current]

    active = {}
    for k, f in current.items():
        active[k] = {"first_seen": (prev.get(k) or {}).get("first_seen") or _iso(now),
                     "severity": f.severity, "summary": f.summary}

    actions = []
    still_open = [f for f in current.values() if f not in new and f not in escalated]
    if new or escalated or resolved:
        parts = []
        if new:
            parts.append("%d new" % len(new))
        if escalated:
            parts.append("%d escalated" % len(escalated))
        if resolved:
            parts.append("%d resolved" % len(resolved))
        lines = ["NEW       " + _line(f) for f in new]
        lines += ["ESCALATED " + _line(f) for f in escalated]
        lines += ["RESOLVED  %s" % v.get("summary", k) for k, v in resolved]
        if still_open:
            lines += ["", "Still open:"] + ["          " + _line(f) for f in still_open]
        actions.append(AlertAction("notify-change",
                                   "Brain guardian: " + ", ".join(parts), "\n".join(lines)))
        last_digest = now
    elif current and (last_digest is None or now - last_digest >= digest_every):
        lines = ["Still open:"] + ["          " + _line(f) for f in current.values()]
        actions.append(AlertAction("notify-digest",
                                   "Brain guardian: %d problem(s) still open" % len(current),
                                   "\n".join(lines)))
        last_digest = now

    state = {"active": active, "last_digest": _iso(last_digest) if last_digest else None}
    return state, actions


_SUBJECT = "Brain guardian: "


def repair_alert(changes: list, backups: list):
    """What a repair that changed something tells the user: exactly what, and where the backups are.

    No state and no de-duplication, on purpose. A repair that changed nothing says nothing,
    so a quiet machine stays quiet. A repair that changed something is always a new event:
    the same hook wiped again an hour later was broken again, and repaired again, and the
    user has to hear it again, because something keeps breaking it.

    Returns an AlertAction, or None when nothing changed.
    """
    if not changes:
        return None
    lines = ["REPAIRED  " + c for c in changes]
    if backups:
        lines += ["", "Backups:"] + ["          " + b for b in backups]
    return AlertAction("notify-repair", _SUBJECT + "repaired %d item(s)" % len(changes), "\n".join(lines))


def merge_alerts(repair, actions: list) -> list:
    """At most one message per run: a repair notice absorbs what `decide` had to say.

    A repair that fixes a problem an earlier check announced also resolves it; two
    notifications a second apart about the same thing is noise.
    """
    actions = list(actions or [])
    if repair is None:
        return actions
    subject, body = repair.subject, repair.body
    for a in actions:
        subject += "; " + (a.subject[len(_SUBJECT):] if a.subject.startswith(_SUBJECT) else a.subject)
        body += "\n\n" + a.body
    return [AlertAction(repair.kind, subject, body)]


def mail_decide(mail_worthy: list, previous: dict, now: dt.datetime, digest_every=DIGEST_EVERY):
    """What this run puts in the user's inbox, and the state to remember it by.

    The inbox is only for a problem that needs a person: a FAIL the guardian has already
    tried and failed to fix. Everything else (a repair that worked, a problem that resolved
    itself, a warn) is a desktop notification and a line in `guardian.py status`, never a
    mail. The guardian checks and repairs every 15 minutes on its own, so mailing about its
    own successful work fills the inbox with messages nobody can act on, and buries the one
    that matters.

    `mail_worthy` is what `probe_mail_worthy` left after the probe debounce. A key pages
    once, when it first becomes mail-worthy; while it stays open it is carried by one
    digest a day and nothing else. A key that resolves drops out of `mailed`, so a fresh
    occurrence later pages again.

    Returns (actions, state); `state` replaces `previous` under `alerts["mail"]`.
    """
    previous = previous or {}
    mailed = set(previous.get("mailed") or ())
    last = _parse(previous.get("last_digest"))
    open_keys = {f.key for f in mail_worthy}
    fresh = [f for f in mail_worthy if f.key not in mailed]
    actions = []
    if fresh:
        actions.append(AlertAction(
            "mail", _SUBJECT + "%d problem(s) need you" % len(fresh),
            "\n".join(["The guardian could not fix these itself:", ""]
                      + ["          " + _line(f) for f in fresh]
                      + ["", "Details: guardian.py status"])))
        last = now
    elif mail_worthy and (last is None or now - last >= digest_every):
        actions.append(AlertAction(
            "mail", _SUBJECT + "%d problem(s) still open" % len(mail_worthy),
            "\n".join(["Still open, and still needing a person:", ""]
                      + ["          " + _line(f) for f in mail_worthy]
                      + ["", "Details: guardian.py status"])))
        last = now
    state = {"mailed": sorted((mailed & open_keys) | {f.key for f in fresh}),
             "last_digest": _iso(last) if last else None}
    return actions, state


# ---------------------------------------------------------------- finding rules


@dataclass(frozen=True)
class InterpreterStatus:
    path: str
    ok: bool
    detail: str


def interpreter_findings(statuses: list) -> list:
    """The first status is the interpreter the hooks run on; the rest are fallbacks."""
    if not statuses:
        return []
    out = []
    hook = statuses[0]
    if not hook.ok:
        out.append(Finding(
            "interpreter:hooks", FAIL,
            "%s does not run (%s): every Brain hook fails with it. If it is the Xcode "
            "license gate, `sudo xcodebuild -license accept`" % (hook.path, hook.detail)))
    if not any(s.ok for s in statuses):
        out.append(Finding("interpreter:none", FAIL,
                           "no working python3 on this machine (%s)"
                           % ", ".join("%s: %s" % (s.path, s.detail) for s in statuses)))
    return out


def launchd_findings(label: str, installed: bool, loaded: bool, last_ok: bool, detail: str,
                     drifted: bool = False) -> list:
    if not installed:
        return [Finding("launchd:%s" % label, FAIL,
                        "launchd job %s is not installed" % label, repairable=True)]
    out = []
    if drifted:
        out.append(Finding("launchd-drift:%s" % label, WARN,
                           "launchd job %s: installed plist differs from the vault template" % label,
                           repairable=True))
    if not loaded:
        out.append(Finding("launchd:%s" % label, FAIL,
                           "launchd job %s is installed but not loaded" % label, repairable=True))
    elif not last_ok and label not in GUARDIAN_LABELS:
        # the guardian never judges its own job by its exit status: a guardian that broke
        # says so in its own log and errors, and judging itself would be circular
        out.append(Finding("launchd-exit:%s" % label, WARN,
                           "launchd job %s: last run failed (%s)" % (label, detail)))
    return out


# ---------------------------------------------------------------- agents


@dataclass(frozen=True)
class AgentWiring:
    """What one agent adapter found when it compared its live wiring with Brain's.

    `changes` are (stable key, one-line text) pairs the adapter knows how to apply;
    `missing_paths` are commands the wiring names that do not exist on disk, which no
    rewiring can fix; `unreadable` is set when the agent's config cannot be parsed and
    must therefore not be touched.
    """
    name: str
    unreadable: object = None
    changes: list = field(default_factory=list)
    missing_paths: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)   # (key, text) repair must not resolve


@dataclass
class AgentRepair:
    name: str
    changes: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    backup: object = None


def agent_findings(wiring: AgentWiring) -> list:
    prefix = "agent:%s:" % wiring.name
    if wiring.unreadable:
        return [Finding(prefix + "unreadable", FAIL,
                        "%s config unreadable, left untouched: %s" % (wiring.name, wiring.unreadable))]
    out = [Finding(prefix + key, FAIL, "%s %s" % (wiring.name, text), repairable=True)
           for key, text in wiring.changes]
    out += [Finding(prefix + "path:" + p, FAIL, "%s wiring names a missing path: %s" % (wiring.name, p))
            for p in wiring.missing_paths]
    out += [Finding(prefix + "conflict:" + key, FAIL, "%s %s" % (wiring.name, text))
            for key, text in wiring.conflicts]
    return out


GIT_HOOKS_DIR = "githooks"      # core.hooksPath, relative to the vault's working tree


@dataclass(frozen=True)
class GitHookFile:
    name: str                    # pre-commit, post-commit
    exists: bool
    executable: bool


@dataclass(frozen=True)
class GitHooksStatus:
    hooks_path: object           # core.hooksPath in the vault's main repository config, or None
    files: list = field(default_factory=list)


def git_hooks_findings(status: GitHooksStatus) -> list:
    """Brain's git hooks only run when core.hooksPath is `githooks` and the files are executable.

    A failure, because the pre-commit hook is the secret scan: while it is off a credential
    can be committed and pushed with nobody told. A missing file is not repairable here:
    brain_watch.py generates it from the event registry.
    """
    out = []
    if status.hooks_path != GIT_HOOKS_DIR:
        out.append(Finding("githooks:hooks-path", FAIL,
                           "vault core.hooksPath is %s, not %s: Brain's git hooks do not run"
                           % ("unset" if not status.hooks_path else repr(status.hooks_path), GIT_HOOKS_DIR),
                           repairable=True))
    for f in status.files:
        if not f.exists:
            out.append(Finding("githooks:missing:" + f.name, FAIL,
                               "vault git hook %s/%s is missing: run brain_watch.py generate"
                               % (GIT_HOOKS_DIR, f.name)))
        elif not f.executable:
            out.append(Finding("githooks:mode:" + f.name, FAIL,
                               "vault git hook %s/%s is not executable" % (GIT_HOOKS_DIR, f.name),
                               repairable=True))
    return out


def git_hooks_repairs(status: GitHooksStatus) -> list:
    """What repair does about `git_hooks_findings`: (kind, hook name or None), in order."""
    out = []
    if status.hooks_path != GIT_HOOKS_DIR:
        out.append(("set-hooks-path", None))
    out += [("chmod", f.name) for f in status.files if f.exists and not f.executable]
    return out


@dataclass(frozen=True)
class TokenHealth:
    """One routine token as routine_auth_core last left it. References and dates only.

    `renew` and `restore` are the exact commands, rendered by the adapter from the token's
    kp:// reference, so the guardian never has to know how KeePass entries are named.
    """
    label: str
    account: str = ""
    kp_ref: str = ""
    status: str = "healthy"          # healthy | dead | limited-until
    until: object = None             # ISO time a limited token rests until
    last_kind: object = None
    last_at: object = None
    detail: str = ""
    expires: object = None           # ISO date the token stops working
    renew: str = ""
    restore: str = ""


@dataclass(frozen=True)
class TokenPool:
    tokens: list = field(default_factory=list)
    config_error: object = None      # why 90-Meta/routine-tokens.json is invalid, or None


TOKEN_WARN_DAYS = 30


def _date(s):
    try:
        return dt.date.fromisoformat(s) if s else None
    except (TypeError, ValueError):
        return None


def token_pool_findings(pool: TokenPool, now: dt.datetime, warn_days=TOKEN_WARN_DAYS) -> list:
    """What the routine token pool needs from a person. Read-only: nothing here is repairable.

    A refused or malformed token is a failure with the command that fixes it; a token
    resting after a limit is a warning until its rest ends; a token within `warn_days` of
    expiry is a warning, an expired one a failure; no usable token at all is its own failure,
    because then every agent routine fails. An invalid pool config is the one finding.
    """
    if pool.config_error:
        return [Finding("routine-auth:config", FAIL,
                        "routine token pool 90-Meta/routine-tokens.json is invalid: %s" % pool.config_error)]
    out, usable = [], 0
    for t in pool.tokens:
        who = "routine token %s%s" % (t.label, " (account %s)" % t.account if t.account else "")
        until = _parse(t.until)
        resting = t.status == "limited-until" and until is not None and until > now
        if t.status == "dead" and t.last_kind == "token_malformed":
            out.append(Finding("routine-auth:token:" + t.label, FAIL,
                               "%s: the value stored at %s is not a single sk-ant-oat01- token (%s): re-store it with: %s"
                               % (who, t.kp_ref, t.detail or "malformed", t.restore)))
        elif t.status == "dead":
            out.append(Finding("routine-auth:token:" + t.label, FAIL,
                               "%s was refused as invalid%s: renew it: %s"
                               % (who, " at %s" % t.last_at if t.last_at else "", t.renew)))
        elif resting:
            out.append(Finding("routine-auth:limited:" + t.label, WARN,
                               "%s is resting after %s until %s (unverified pattern: check logs/routine-auth.log)"
                               % (who, t.last_kind or "a limit", t.until)))
        else:
            usable += 1
        expires = _date(t.expires)
        if expires is not None:
            left = (expires - now.date()).days
            if left < 0:
                out.append(Finding("routine-auth:expiry:" + t.label, FAIL,
                                   "%s expired on %s: renew it: %s" % (who, t.expires, t.renew)))
            elif left <= warn_days:
                out.append(Finding("routine-auth:expiry:" + t.label, WARN,
                                   "%s expires on %s (in %d days): renew it: %s" % (who, t.expires, left, t.renew)))
    if pool.tokens and not usable:
        out.append(Finding("routine-auth:pool", FAIL,
                           "no usable routine token: every token in 90-Meta/routine-tokens.json is refused or "
                           "resting, so every agent routine fails until one is renewed"))
    return out


# ---------------------------------------------------------------- routines enabled twice, routines degraded

BROWSER_NEEDS = ("browser", "claude-in-chrome", "chrome")


def _flow_list(value) -> list:
    """A frontmatter flow list (`[a, b]`), a single value, or none."""
    v = (value or "").strip()
    if v.lower() in ("", "none", "[]", "-"):
        return []
    if v.startswith("[") and v.endswith("]"):
        v = v[1:-1]
    return [x.strip().strip("'\"") for x in v.split(",") if x.strip().strip("'\"")]


def routine_meta(text: str) -> dict:
    """`app_task` and `needs_bridge` from a routine file's frontmatter, and only from there."""
    out = {"app_task": None, "needs_bridge": []}
    t = text or ""
    if not t.startswith("---\n"):
        return out
    end = t.find("\n---", 3)
    if end == -1:
        return out
    for line in t[4:end].splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        if key == "app_task":
            out["app_task"] = value.strip().strip("'\"") or None
        elif key == "needs_bridge":
            out["needs_bridge"] = _flow_list(value)
    return out


def duplicate_task_findings(desktop_enabled, agent_rows) -> list:
    """An agent row enabled while its Claude app task is enabled too: the routine runs twice.

    `desktop_enabled` is [(app task id, account)] as the Claude app's sessions record them;
    `agent_rows` are {"id", "enabled", "app_task"}. Never repairable: which one to keep is his
    call, and disabling a task in the Claude app is a manual step he confirms.
    """
    accounts = {}
    for task_id, account in desktop_enabled or ():
        accounts.setdefault(task_id, [])
        if account not in accounts[task_id]:
            accounts[task_id].append(account)
    out = []
    for row in agent_rows or ():
        app = row.get("app_task")
        if row.get("enabled") and app and app in accounts:
            out.append(Finding(
                "duplicate:%s" % row["id"], FAIL,
                "routine %s is enabled both as the Claude app scheduled task %s (account %s) and as this agent "
                "row, so it runs twice: disable the app task by hand in the Claude app before this can be trusted"
                % (row["id"], app, ", ".join(sorted(accounts[app])))))
    return out


def app_task_registry_findings(desktop_enabled, registry_rows, host: str, is_mine=None) -> list:
    """The Claude app's enabled tasks on THIS machine against 90-Meta/scheduled-tasks.md.

    The app's scheduler has no idea which machine it runs on: its tasks live per install and
    are not synced. So the registry is the only place that says which machine owns a task,
    and nothing enforced it. Three drifts, each one a way a task silently runs twice or
    never:

      - an enabled app task with no registry row at all (say `weekly-report-to-chat`):
        another machine can run the same task and nobody can tell;
      - an enabled app task whose row names another machine: it runs here AND wherever the
        registry says, a real duplicate, so it is a failure;
      - a `claude-app` row owned by this machine whose `enabled` disagrees with the app.

    `desktop_enabled` is [(app task id, account)]; `registry_rows` are tasks.py's parsed
    rows. A row of any type whose id equals the app task counts as its registration.
    `host` and `is_mine` are `machine_matches`'s. Never repairable: the app's tasks are
    changed by hand, in the app.
    """
    enabled_here = []
    for task_id, _account in desktop_enabled or ():
        if task_id not in enabled_here:
            enabled_here.append(task_id)
    by_id = {r.get("id"): r for r in registry_rows or ()}
    out = []
    for task_id in enabled_here:
        row = by_id.get(task_id)
        if row is None:
            out.append(Finding(
                "app-task:unregistered:%s" % task_id, WARN,
                "Claude app task %s is enabled on this machine but has no row in "
                "90-Meta/scheduled-tasks.md: add a claude-app row with machine %s, or another "
                "machine can run the same task without anyone noticing" % (task_id, host)))
            continue
        machine = row.get("machine")
        if not machine_matches(machine, host, is_mine):
            out.append(Finding(
                "app-task:wrong-machine:%s" % task_id, FAIL,
                "Claude app task %s is enabled on this machine (%s), but the registry assigns it "
                "to %s: it runs twice. Disable it here in the Claude app, or move the row to "
                "this machine and disable it there" % (task_id, host, machine)))
        elif not row.get("enabled"):
            out.append(Finding(
                "app-task:registry-drift:%s" % task_id, WARN,
                "Claude app task %s is enabled on this machine but its registry row says "
                "enabled: no. Fix whichever side is wrong" % task_id))
    for row in registry_rows or ():
        if (row.get("type") == "claude-app" and str(row.get("machine") or "").strip() != "*"
                and machine_matches(row.get("machine"), host, is_mine)
                and row.get("enabled") and row.get("id") not in enabled_here):
            out.append(Finding(
                "app-task:registry-drift:%s" % row["id"], WARN,
                "the registry says claude-app task %s is enabled on this machine, but the "
                "Claude app has it disabled or does not have it: set enabled: no in "
                "90-Meta/scheduled-tasks.md, or enable it in the app" % row["id"]))
    return out


def degraded_routine_ids(rows, bridge_stale: bool) -> list:
    """Enabled routines whose `needs_bridge` names the browser, while the browser bridge is stale."""
    if not bridge_stale:
        return []
    return [r["id"] for r in rows or ()
            if r.get("enabled") and any(n in BROWSER_NEEDS for n in (r.get("needs_bridge") or ()))]


def routine_permission_findings(rows) -> list:
    """A routine whose agent_args would give an unattended run unrestricted permissions. Reported
    for disabled rows too, so it is fixed before anyone enables them; routine_auth_core refuses
    such a run anyway. `permission_problem` is routine_auth_core's own verdict, passed in."""
    return [Finding("routine-permissions:%s" % r["id"], FAIL,
                    "routine %s: its agent_args are refused, so it fails before running: %s"
                    % (r["id"], r["permission_problem"]))
            for r in rows or () if r.get("permission_problem")]


def degraded_routine_findings(rows, bridge_stale: bool) -> list:
    """Detect and alert, never block: a degraded routine still runs."""
    return [Finding("degraded:%s" % rid, WARN,
                    "routine %s needs the browser, and Claude in Chrome's bridge is stale after an account "
                    "switch: it runs degraded until the Claude app is restarted" % rid)
            for rid in degraded_routine_ids(rows, bridge_stale)]


@dataclass(frozen=True)
class SyncStatus:
    pending: int                 # uncommitted paths
    unpushed_age_s: object       # seconds since the oldest unpushed commit, or None
    remote_ok: bool              # the branch has an upstream to push to


UNPUSHED_WARN_S = 6 * 3600       # the sync daemon pushes every 10 min; hours means pushing fails
INDEX_STALE_S = 24 * 3600


def vault_findings(sync: SyncStatus, index_age_s) -> list:
    out = []
    if sync.unpushed_age_s is not None and sync.unpushed_age_s >= UNPUSHED_WARN_S:
        out.append(Finding("vault:unpushed", WARN,
                           "vault commits unpushed for %.0f h" % (sync.unpushed_age_s / 3600)))
    if not sync.remote_ok:
        out.append(Finding("vault:no-upstream", WARN, "vault branch has no upstream to push to"))
    if index_age_s is None or index_age_s >= INDEX_STALE_S:
        out.append(Finding("vault:index-stale", WARN,
                           "vault index missing" if index_age_s is None
                           else "vault index not rewritten for %.0f h" % (index_age_s / 3600)))
    return out


# ---------------------------------------------------------------- hook liveness
#
# Wired is not enough: a hook can sit in settings.json and never run, or run and fail on every
# event, and nothing an agent does would say so. What proves the hooks work, with no agent in
# the loop: every hook writes a heartbeat line per run (brainlib.heartbeat), every Claude Code
# session writes a transcript, and a session that wrote a transcript but no heartbeat ran
# without Brain.

LIVENESS_SESSION, LIVENESS_REGULAR, LIVENESS_CONDITIONAL = "session", "regular", "conditional"
HEARTBEAT_FINE = ("ok", "blocked", "off")        # blocked is exit 2 on purpose; off is BRAIN_OFF
PROBE_SESSION_ID = "brainprobe-0000-4000-8000-000000000000"


def session_sid(session_id) -> str:
    """The short session id every Brain hook logs (brainlib.sid8): the uuid's first eight hex digits."""
    return str(session_id or "nosess").replace("-", "")[:8]


@dataclass(frozen=True)
class Heartbeat:
    ts: float
    event: str               # the event id in 90-Meta/events.json
    sid: str
    status: str              # ok | blocked | off | error
    exc: str = ""
    ms: int = 0
    hook_event: str = ""     # Claude Code's event name: SessionStart, Stop, ...


@dataclass(frozen=True)
class SessionTranscript:
    sid: str
    project_dir: str         # Claude Code's encoded directory name under ~/.claude/projects
    started: float
    mtime: float
    # Claude Code hook events (`SessionStart`) whose hooks Claude Code itself cancelled in this
    # session, read from its `hook_cancelled` attachments. Under the SDK an unattended run's
    # queued prompt can cancel SessionStart, killing compass.py before it leaves a heartbeat.
    cancelled: frozenset = frozenset()


@dataclass(frozen=True)
class HookEventSpec:
    id: str
    hook_event: str
    identity: str            # hook_identity of its command: `vault_sync.py --hook`
    liveness: str = LIVENESS_REGULAR


@dataclass(frozen=True)
class LivenessConfig:
    window_s: float = 1800.0          # a session written to within this is active
    silent_s: float = 7 * 86400.0     # a regular hook is expected at least once in this
    grace_s: float = 120.0            # a session or a turn this young is not judged yet
    failing_last: int = 5
    failing_min: int = 3
    # Sessions nobody should hold to Brain's hooks, by rule: the temporary directories tests and
    # scratch checks run in, and the guardian's own probe session.
    ignore_dirs: tuple = (r"^-private-var-folders-", r"^-var-folders-", r"^-private-tmp(-|$)", r"^-tmp(-|$)")
    ignore_sids: tuple = (session_sid(PROBE_SESSION_ID),)


@dataclass(frozen=True)
class LivenessReport:
    findings: list = field(default_factory=list)
    checked: int = 0                                  # active sessions judged
    without: list = field(default_factory=list)       # sids of active sessions with no heartbeat
    last_by_event: dict = field(default_factory=dict)  # event id -> latest Heartbeat
    started: bool = True                              # False until liveness has an epoch


def heartbeat_from_record(rec):
    """A Heartbeat from one decoded heartbeat.jsonl line, or None when it is not one."""
    if not isinstance(rec, dict):
        return None
    ts, event, sid = rec.get("ts"), rec.get("event"), rec.get("sid")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return None
    if not isinstance(event, str) or not event or not isinstance(sid, str) or not sid:
        return None
    ms = rec.get("ms")
    ms = int(ms) if isinstance(ms, (int, float)) and not isinstance(ms, bool) else 0
    return Heartbeat(float(ts), event, sid, str(rec.get("status") or ""), str(rec.get("exc") or ""), ms,
                     str(rec.get("hook_event") or ""))


def transcript_ignored(t: SessionTranscript, config: LivenessConfig) -> bool:
    return (any(re.search(p, t.project_dir or "") for p in config.ignore_dirs)
            or any(t.sid.startswith(s) for s in config.ignore_sids))


def hook_liveness(transcripts, heartbeats, specs, now: float, since, config: LivenessConfig = None,
                  include_silent: bool = True) -> LivenessReport:
    """Are Brain's hooks firing and succeeding? Decided from transcripts and heartbeats alone.

    - `hooks:not-firing` (fail): a session active in the window, past its grace, that started
      after liveness began, has no heartbeat at all. The hooks are dead or unwired.
    - `hooks:failing:<event>` (fail): at least `failing_min` of an event's last `failing_last`
      heartbeats are errors. Recovers as soon as clean runs push the errors out.
    - `hooks:silent:<event>` (warn): a `session` event missing from an active session that
      finished a turn (a Stop heartbeat older than the grace); or, over the silent window, a
      `session` or `regular` event with no heartbeat at all while other hooks fired and Claude
      Code was in use. `conditional` events are never silent. The silent window is only judged
      once liveness has run for all of it, and not in the cheap mode the file watch uses.

    `since` is the liveness epoch (epoch seconds) or None before the guardian first ran:
    sessions from before it are never judged. Pure: every input is a value.
    """
    config = config or LivenessConfig()
    beats = sorted(heartbeats or [], key=lambda h: h.ts)
    last = {}
    for h in beats:
        last[h.event] = h
    if since is None:
        return LivenessReport([], 0, [], last, started=False)

    by_sid, per_event = {}, {}
    for h in beats:
        by_sid.setdefault(h.sid, []).append(h)
        per_event.setdefault(h.event, []).append(h)
    judged = [t for t in transcripts or [] if not transcript_ignored(t, config) and t.started >= since]
    active = [t for t in judged if t.mtime >= now - config.window_s and now - t.started >= config.grace_s]

    findings = []
    dead = [t for t in active if not by_sid.get(t.sid)]
    if dead:
        findings.append(Finding(
            "hooks:not-firing", FAIL,
            "%d active Claude Code session(s) in the last %d min fired no Brain hook (session %s in %s): "
            "the hooks are not running or not wired" % (len(dead), config.window_s // 60, dead[0].sid, dead[0].project_dir)))

    for event in sorted(per_event):
        recent = per_event[event][-config.failing_last:]
        errors = [h for h in recent if h.status not in HEARTBEAT_FINE]
        if len(errors) >= config.failing_min:
            findings.append(Finding(
                "hooks:failing:%s" % event, FAIL,
                "hook %s failed %d of its last %d runs (last: %s)"
                % (event, len(errors), len(recent), errors[-1].exc or "status %s" % errors[-1].status)))

    missing = {}
    session_events = [s for s in specs or [] if s.liveness == LIVENESS_SESSION]
    for t in active:
        mine = by_sid.get(t.sid) or []
        stops = [h.ts for h in mine if h.hook_event == "Stop"]
        # No turn inside the window (a long session touched only as its process exited) says
        # nothing about hooks installed since its last turn.
        if not stops or min(stops) > now - config.grace_s or max(stops) < now - config.window_s:
            continue
        seen = {h.event for h in mine}
        for s in session_events:
            if s.id not in seen and s.hook_event not in t.cancelled:
                missing.setdefault(s.id, []).append(t.sid)

    silent = set()
    if include_silent and now - since >= config.silent_s:
        horizon = now - config.silent_s
        fired = {h.event for h in beats if h.ts >= horizon}
        if fired and any(t.mtime >= horizon for t in judged):
            silent = {s.id for s in specs or []
                      if s.liveness in (LIVENESS_SESSION, LIVENESS_REGULAR) and s.id not in fired}

    for event in sorted(set(missing) | silent):
        if event in missing:
            summary = ("hook %s did not fire in %d active session(s) that finished a turn (session %s)"
                       % (event, len(missing[event]), missing[event][0]))
        else:
            summary = ("hook %s has not fired for %d days while other Brain hooks did"
                       % (event, config.silent_s // 86400))
        findings.append(Finding("hooks:silent:%s" % event, WARN, summary))
    return LivenessReport(findings, len(active), [t.sid for t in dead], last, True)


# ---------------------------------------------------------------- synthetic hook probe
#
# Heartbeats need a session to happen. The probe needs nothing: it runs each canonical hook the
# way Claude Code would, with a canned payload, in a scratch state, so a dead interpreter, a
# broken import or a syntax error shows up before any session hits it.

PROBE_MAX_TIMEOUT = 20
PROBE_MAY_BLOCK = ("Stop", "SubagentStop")        # exit 2 is these hooks' job
PROBE_EXPECTS_CONTEXT = ("session-start",)


@dataclass(frozen=True)
class ProbeCase:
    event_id: str
    hook_event: str
    identity: str
    command: str
    timeout: float
    stdin: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ProbeResult:
    event_id: str
    exit: object = None           # int, or None when it never finished
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error: str = ""               # could not start at all
    parsed: object = None         # stdout decoded, when it looked like JSON
    parse_error: str = ""


def probe_payload(hook_event: str, cwd: str) -> dict:
    """Claude Code's stdin for `hook_event`, under the probe's own session id, pointed at `cwd`."""
    base = cwd.rstrip("/")
    target = base + "/brain-probe.txt"
    payload = {"session_id": PROBE_SESSION_ID, "transcript_path": base + "/probe-transcript.jsonl", "cwd": cwd,
               "hook_event_name": hook_event, "permission_mode": "default"}
    write = {"tool_name": "Write", "tool_input": {"file_path": target, "content": "probe\n"}}
    payload.update({
        "SessionStart": {"source": "startup"},
        "UserPromptSubmit": {"prompt": "brain hook probe: which notes describe the guardian?"},
        "PreToolUse": write,
        "PostToolUse": dict(write, tool_response={"filePath": target, "success": True}),
        "Stop": {"stop_hook_active": False},
        "SubagentStop": {"stop_hook_active": False, "agent_type": "brain-probe"},
        "SessionEnd": {"reason": "other"},
        "WorktreeCreate": {"name": "brain-probe"},
    }.get(hook_event, {}))
    return payload


def probe_cases(hooks: dict, specs, cwd: str) -> list:
    """One case per canonical hook the registry knows, in hooks.json order. Others are not Brain's."""
    known = {}
    for s in specs or []:
        known.setdefault((s.hook_event, s.identity), s)
    out, seen = [], set()
    for event, groups in (hooks or {}).items():
        if not isinstance(groups, list):
            continue
        for g in groups:
            for h in (g.get("hooks") or []) if isinstance(g, dict) else []:
                cmd = h.get("command") if isinstance(h, dict) else None
                ident = hook_identity(cmd) if isinstance(cmd, str) else None
                spec = known.get((event, ident))
                if spec is None or (event, ident) in seen:
                    continue
                seen.add((event, ident))
                t = h.get("timeout")
                ok_t = isinstance(t, (int, float)) and not isinstance(t, bool) and t > 0
                out.append(ProbeCase(spec.id, event, ident, cmd, min(t, PROBE_MAX_TIMEOUT) if ok_t else PROBE_MAX_TIMEOUT,
                                     probe_payload(event, cwd)))
    return out


def _last_line(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1][:160] if lines else ""


def probe_verdict(case: ProbeCase, result: ProbeResult) -> str:
    """"" when the hook behaved as Claude Code needs it to, else the one-line reason."""
    if result.timed_out:
        return "timed out after %ds" % case.timeout
    if result.error:
        return result.error[:200]
    allowed = (0, 2) if case.hook_event in PROBE_MAY_BLOCK else (0,)
    if result.exit not in allowed:
        tail = _last_line(result.stderr) or _last_line(result.stdout)
        return "exit %s%s" % (result.exit, (": " + tail) if tail else "")
    if result.parse_error:
        return "output looks like JSON but is not valid JSON (%s)" % result.parse_error[:120]
    out = result.parsed if isinstance(result.parsed, dict) else {}
    specific = out.get("hookSpecificOutput")
    if specific is not None and not isinstance(specific, dict):
        return "hookSpecificOutput is not an object"
    specific = specific or {}
    name = specific.get("hookEventName")
    if name and name != case.hook_event:
        return "answered as %s, not %s" % (name, case.hook_event)
    if case.hook_event == "PreToolUse" and specific.get("permissionDecision") == "deny":
        return "denied a harmless write inside a scratch directory (%s)" % str(specific.get("permissionDecisionReason") or "")[:100]
    if case.event_id in PROBE_EXPECTS_CONTEXT:
        ctx = specific.get("additionalContext")
        if not (isinstance(ctx, str) and ctx.strip()):
            return "returned no additionalContext"
    return ""


def probe_findings(pairs) -> list:
    out = []
    for case, result in pairs or []:
        why = probe_verdict(case, result)
        if why:
            out.append(Finding("hooks:probe:%s" % case.event_id, FAIL,
                               "hook %s (%s) fails when run the way Claude Code runs it: %s"
                               % (case.event_id, case.identity, " ".join(why.split()))))
    return out


PROBE_KEY_PREFIX = "hooks:probe:"


def probe_mail_worthy(findings, prev_active, already_mailed=None) -> list:
    """FAIL-severity findings worth paging a person, given what was already open last run.

    Every non-probe FAIL pages the first time it appears: nobody but a person renews a dead
    token or fixes a missing git hook, so the first occurrence is the only chance to tell
    them promptly. A `hooks:probe:*` FAIL is different: probe timeouts have been seen to
    appear on one run and be gone on the guardian's very next run, with no code change in
    between, so paging on the first occurrence would mostly page for something already
    resolved by the time it is read. It pages once it is still open on the *next* run,
    i.e. its key was already present in `prev_active` (the previous run's alerts state).
    Paging a key at most once while it stays open is `mail_decide()`'s job, for every
    finding, through `state["alerts"]["mail"]["mailed"]`. The optional `already_mailed`
    argument is for a caller that wants that filter applied here too.
    """
    prev_active = prev_active or {}
    already_mailed = already_mailed or ()
    return [f for f in findings
            if f.severity == FAIL and (not f.key.startswith(PROBE_KEY_PREFIX)
                                        or (f.key in prev_active and f.key not in already_mailed))]


# ---------------------------------------------------------------- session-start notice

HEALTH_MAX_ITEMS = 5
HEALTH_LINE_CHARS = 100


def health_notice(active, raised, limit: int = HEALTH_MAX_ITEMS) -> str:
    """The short block compass.py adds at SessionStart while problems are open, else "".

    `active` is the guardian state's open alerts, `raised` what other processes raised; a key
    in both is listed once. Failures first, one short line each, then how many more and the
    command to inspect them. Bounded, because it rides in every session's startup budget.
    """
    items, seen = [], set()
    for source in (active, raised):
        if not isinstance(source, dict):
            continue
        for key in sorted(source):
            v = source[key]
            if key in seen or not isinstance(v, dict):
                continue
            seen.add(key)
            sev = v.get("severity") if v.get("severity") in (FAIL, WARN) else WARN
            summary = " ".join(str(v.get("summary") or key).split())
            if len(summary) > HEALTH_LINE_CHARS:
                summary = summary[:HEALTH_LINE_CHARS - 1].rstrip() + "…"
            items.append((0 if sev == FAIL else 1, key, sev, summary))
    if not items:
        return ""
    items.sort(key=lambda i: (i[0], i[1]))
    lines = ["## Brain health"] + ["- [%s] %s" % (sev, summary) for _r, _k, sev, summary in items[:limit]]
    if len(items) > limit:
        lines.append("- and %d more" % (len(items) - limit))
    lines.append("Open problems the guardian found. Inspect: `python3 ~/Brain/_bin/guardian.py status`")
    return "\n".join(lines)
