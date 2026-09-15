"""The Claude Code agent adapter: Brain's events wired as Claude Code hooks.

This module is the only place in the guardian that knows Claude Code exists — where it
keeps its config (~/.claude), what file holds its wiring (settings.json, under `hooks`)
and what shape that wiring has. The use cases see one `AgentAdapter` among others.

The wiring here is generated, never the source of truth: the vault's
integrations/claude-code/plugin/brain/hooks/hooks.json says what Brain expects, and repair merges that into
settings.json without removing anything else the user or another tool put there. The one
removal is a hook that runs a script under the vault's own dirs that no longer exists:
that hook is Brain's, and it fails on every event.
"""

from __future__ import annotations

import json
import os
import shutil
import stat

from . import domain as D
from .adapters import HOME, LocalPaths, SystemClock, atomic_write
from .ports import SettingsUnreadable


def default_locations(home=HOME):
    """(config_dir, settings_file) for Claude Code under `home`."""
    config = os.path.join(home, ".claude")
    return config, os.path.join(config, "settings.json")


class FileSettingsStore:
    """Claude Code's settings.json.

    Shared with Claude Code itself and with anything else the user installs, so: a
    backup before every change, an atomic rename, the original permissions kept, and a
    file that does not parse is reported rather than replaced.
    """

    def __init__(self, path, clock=None, keep_backups=10, log=None):
        self.path = path
        self.clock = clock or SystemClock()
        self.keep_backups = keep_backups
        self.log = log or (lambda s: None)

    def load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as fh:
                text = fh.read()
        except FileNotFoundError:
            return {}
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise SettingsUnreadable("%s: %s" % (self.path, exc))
        if not isinstance(data, dict):
            raise SettingsUnreadable("%s: top level is %s, not an object"
                                     % (self.path, type(data).__name__))
        return data

    def save(self, data: dict, backup_note: str):
        backup, mode = None, None
        if os.path.exists(self.path):
            mode = stat.S_IMODE(os.stat(self.path).st_mode)
            stamp = self.clock.now().strftime("%Y%m%d-%H%M%S")
            backup = "%s.bak-guardian-%s" % (self.path, stamp)
            n = 1
            while os.path.exists(backup):
                backup = "%s.bak-guardian-%s-%d" % (self.path, stamp, n)
                n += 1
            shutil.copy2(self.path, backup)
            self._prune()
        atomic_write(self.path, json.dumps(data, indent=2, ensure_ascii=False) + "\n", mode)
        self.log("settings written: %s (backup %s)" % (backup_note, backup or "none: new file"))
        return backup

    def _prune(self):
        folder, base = os.path.split(self.path)
        prefix = base + ".bak-guardian-"
        backups = sorted(f for f in os.listdir(folder or ".") if f.startswith(prefix))
        for old in backups[:-self.keep_backups] if self.keep_backups else backups:
            try:
                os.remove(os.path.join(folder, old))
            except OSError:
                pass


class CanonicalHooksFile:
    """The vault's integrations/claude-code/plugin/brain/hooks/hooks.json, localized for this machine."""

    def __init__(self, path, vault, home=HOME):
        self.path, self.vault, self.home = path, vault, home

    def load(self) -> dict:
        with open(self.path, encoding="utf-8") as fh:
            hooks = json.load(fh).get("hooks") or {}
        return D.localize_hooks(hooks, vault=self.vault, home=self.home)


class ClaudeCodeAgent:
    NAME = "claude-code"

    def __init__(self, settings, canonical, config_dir, paths=None, plugin=None, vault=None):
        self.settings, self.canonical = settings, canonical
        self.config_dir = config_dir
        self.paths = paths or LocalPaths()
        # The vault whose _bin, githooks and integrations make a hook Brain's. Defaults to
        # the vault the canonical hooks were localized for.
        self.vault = vault or getattr(canonical, "vault", None)
        # install_plugin.Syncer for the vault's plugin/brain and this config dir, or None.
        # Skills and agents are canonical in the vault; ~/.claude holds installed copies.
        self.plugin = plugin

    def name(self) -> str:
        return self.NAME

    def present(self) -> bool:
        return os.path.isdir(self.config_dir)

    def _plan(self):
        """(current settings or None, canonical, merged hooks, changes, unreadable)."""
        canonical = self.canonical.load()
        try:
            current = self.settings.load()
        except SettingsUnreadable as exc:
            return None, canonical, None, [], str(exc)
        hooks = current.get("hooks") or {}
        dirs = D.brain_script_dirs(self.vault) if self.vault else ()
        missing = {p for p in D.brain_hook_paths(hooks, dirs) if not self.paths.exists(p)}
        merged, changes = D.reconcile_hooks(canonical, hooks, dirs, missing)
        return current, canonical, merged, changes, None

    PLUGIN_TEXT = {"install": "%s: in the vault, to install into the agent",
                   "backport": "%s: edited in the agent, to back-port into the vault"}

    def check(self):
        current, canonical, _, changes, unreadable = self._plan()
        missing = [p for p in D.hook_command_paths(canonical) if not self.paths.exists(p)]
        wiring_changes = [(c.key, c.text) for c in changes]
        conflicts = []
        if self.plugin is not None:
            for item in self.plugin.plan():
                key = "plugin:" + item["key"]
                if item["action"] in self.PLUGIN_TEXT:
                    wiring_changes.append((key, self.PLUGIN_TEXT[item["action"]] % item["key"]))
                elif item["action"] == "conflict":
                    conflicts.append((key, "%s changed in both the vault and %s since the last sync"
                                      % (item["key"], self.config_dir)))
        return D.AgentWiring(self.NAME, unreadable, wiring_changes, missing, conflicts)

    def repair(self):
        result = D.AgentRepair(self.NAME)
        try:
            current, _, merged, changes, unreadable = self._plan()
            if unreadable:
                result.errors.append("settings not repaired, file unreadable: %s" % unreadable)
            elif changes:
                data = dict(current)
                data["hooks"] = merged
                result.backup = self.settings.save(
                    data, "guardian repair: " + "; ".join(c.text for c in changes))
                result.changes = [c.text for c in changes]
        except Exception as exc:
            result.errors.append("hooks not repaired: %s: %s" % (type(exc).__name__, exc))
        if unreadable is not None and self.plugin is None:
            return result
        if self.plugin is not None:
            try:
                for r in self.plugin.apply():
                    label = "%s/%s" % (r["kind"], r["name"])
                    if "error" in r:
                        result.errors.append("%s: %s failed: %s" % (label, r["action"], r["error"]))
                    elif r["action"] in ("install", "backport"):
                        result.changes.append("%s: %s%s" % (label, r["action"],
                                                            (" (previous copy in %s)" % r["backup"]) if r.get("backup") else ""))
                    elif r["action"] == "conflict":
                        result.errors.append("%s: conflict, both copies changed since the last sync; left as they are, "
                                             "backups %s, diff %s" % (label, ", ".join(r.get("backups") or []), r.get("diff")))
            except Exception as exc:
                result.errors.append("skills and agents not synced: %s: %s" % (type(exc).__name__, exc))
        return result
