"""The event layer's adapters: mtimes, state, processes, session identity, alerts, git, files.

Each class implements one port from ports.py. Anything external is injectable so the
tests can substitute it; the defaults are the real thing.
"""

from __future__ import annotations

import json
import os
import subprocess
import time

SKIP_DIRS = {"__pycache__", "node_modules", "_index"}


def _atomic_write(path, text, mode=None):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


class FsSnapshot:
    """{relative path: mtime} for the listed paths only.

    Bounded on purpose: the registry lists what is watched, and nothing else is walked
    (80-Private, 60-Context-Packs, _index and hidden directories never are). A stat per
    file every tick is cheap for a vault of a few thousand files.
    """

    def __init__(self, vault):
        self.vault = vault

    def read(self, paths) -> dict:
        out = {}
        for rel in paths:
            full = os.path.join(self.vault, rel)
            if os.path.isfile(full):
                try:
                    out[rel] = os.path.getmtime(full)
                except OSError:
                    pass
                continue
            if not os.path.isdir(full):
                continue
            for root, dirs, files in os.walk(full):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
                for name in sorted(files):
                    if name.startswith(".") or name.endswith(".pyc"):
                        continue
                    path = os.path.join(root, name)
                    try:
                        out[os.path.relpath(path, self.vault).replace(os.sep, "/")] = os.path.getmtime(path)
                    except OSError:
                        pass
        return out


class JsonWatchState:
    def __init__(self, path):
        self.path = path

    def load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, data: dict) -> None:
        _atomic_write(self.path, json.dumps(data, indent=1, sort_keys=True))


class SubprocessRunner:
    """Runs argv lists, never a shell string. Never raises."""

    def __init__(self, cwd=None, env=None, run=subprocess.run):
        self.cwd, self.env, self._run = cwd, env, run

    def run(self, argv, timeout):
        try:
            p = self._run(list(argv), cwd=self.cwd, env=self.env, capture_output=True, text=True,
                          timeout=timeout, stdin=subprocess.DEVNULL)
            return p.returncode, p.stdout or "", p.stderr or ""
        except FileNotFoundError:
            return 127, "", "command not found: %s" % (argv[0] if argv else "")
        except PermissionError:
            return 126, "", "command not executable: %s" % (argv[0] if argv else "")
        except subprocess.TimeoutExpired:
            return 124, "", "timed out after %ss" % timeout
        except OSError as exc:
            return 1, "", "%s: %s" % (type(exc).__name__, exc)


class VaultFiles:
    def __init__(self, vault):
        self.vault = vault

    def read(self, rel):
        try:
            with open(os.path.join(self.vault, rel), encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return None

    def write(self, rel, text, executable=False):
        _atomic_write(os.path.join(self.vault, rel), text, 0o755 if executable else 0o644)


class SystemClock:
    def now(self) -> float:
        return time.time()


class ClaudeSettingsHooks:
    """Claude Code's live `hooks` block, read-only. None when Claude Code is not installed here
    (no config directory) or settings.json does not parse: then there is nothing the watch
    should trigger, and the guardian reports the unreadable file itself."""

    def __init__(self, config_dir, settings_path=None):
        self.config_dir = config_dir
        self.settings_path = settings_path or os.path.join(config_dir, "settings.json")

    def hooks(self):
        if not os.path.isdir(self.config_dir):
            return None
        try:
            with open(self.settings_path, encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        hooks = data.get("hooks")
        return hooks if isinstance(hooks, dict) else {}


class MainLogReader:
    """New whole lines of a log that only grows, through a byte-offset cursor.

    The cursor (offset and inode) lives in Brain's state directory. A log that shrank was
    truncated and a log with a new inode was rotated: both are read from their start. A read
    never takes more than `max_bytes`, and only whole lines are consumed, so a line being
    written right now is read on the next tick instead of in two halves. The first read ever
    is `fresh`: its text is history, for the caller to treat as such.
    """

    def __init__(self, log_path, cursor_path, max_bytes=1_000_000):
        self.log_path, self.cursor_path, self.max_bytes = log_path, cursor_path, max_bytes

    def _cursor(self) -> dict:
        try:
            with open(self.cursor_path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def read_new(self):
        try:
            st = os.stat(self.log_path)
        except OSError:
            return "", False
        cursor = self._cursor()
        fresh = not cursor
        size, inode = st.st_size, st.st_ino
        offset = cursor.get("offset") if cursor.get("inode") == inode else 0
        if not isinstance(offset, int) or offset < 0 or offset > size:
            offset = 0
        start = max(offset, size - self.max_bytes)
        text, new_offset = "", size
        if size > start:
            try:
                with open(self.log_path, "rb") as fh:
                    fh.seek(start)
                    data = fh.read(size - start)
            except OSError:
                return "", fresh
            data_start = start
            if start > offset or (fresh and start > 0):      # started mid-line: skip to the next line
                nl = data.find(b"\n")
                data, data_start = (data[nl + 1:], start + nl + 1) if nl != -1 else (b"", size)
            last = data.rfind(b"\n")
            consumed = data[:last + 1] if last != -1 else b""
            new_offset = data_start + len(consumed)
            text = consumed.decode("utf-8", "replace")
        try:
            _atomic_write(self.cursor_path, json.dumps({"offset": new_offset, "inode": inode}))
        except OSError:
            pass
        return text, fresh


def _claude_session_pid():
    import brainlib as B

    return B.claude_session_pid()


class EnvThenProcessTreeSessionId:
    """BRAIN_SESSION_ID, else the Claude Code session process, else "system".

    "system" is honest: a write the watcher or a git hook sees with no session behind it is
    attributed to no one in particular. Inventing an id would misattribute it instead.
    """

    def __init__(self, environ=None, claude_pid=None):
        self.environ = os.environ if environ is None else environ
        self.claude_pid = claude_pid or _claude_session_pid

    def resolve(self) -> str:
        explicit = (self.environ.get("BRAIN_SESSION_ID") or "").strip()
        if explicit:
            return explicit
        try:
            pid = int(self.claude_pid() or 0)
        except Exception:
            pid = 0
        return str(pid) if pid > 0 else "system"


class GuardianAlertSink:
    """Raises alerts into the guardian's channel: notification without detail, personal
    email and log, de-duplicated by the guardian. Warnings, never blocks. Never raises."""

    def __init__(self, path=None):
        self.path = path

    def raise_alert(self, key, summary, severity="warn"):
        try:
            from guardian_core import adapters as GA

            GA.raise_alert(key, summary, severity=severity, path=self.path)
        except Exception:
            pass

    def clear_alert(self, key):
        try:
            from guardian_core import adapters as GA

            GA.clear_alert(key, path=self.path)
        except Exception:
            pass


class GuardianHookLiveness:
    """The guardian's hook liveness verdict for the file watch, in its cheap mode.

    `source` is a guardian_core.adapters.HookLivenessSource. Only the active window is judged:
    the probe and the silent window stay with the guardian's own 15-minute run, and so does
    starting the liveness epoch. Raises when the source cannot be read; the tick skips it.
    """

    def __init__(self, source):
        self.source = source

    def findings(self, now):
        from guardian_core import application as GA

        report = GA.hook_liveness_report(self.source, now, include_silent=False)
        return [(f.key, f.severity, f.summary) for f in report.findings]


class GitUnsyncedProbe:
    """When did the oldest change that has not reached the remote happen?

    Uncommitted files count from their mtime; committed but unpushed work from the commit
    time. None when everything is pushed, or when this is not a git repository.
    """

    def __init__(self, vault, git="/usr/bin/git", now=time.time, timeout=10):
        self.vault, self.git, self.now, self.timeout = vault, git, now, timeout

    def _call(self, *args):
        try:
            p = subprocess.run([self.git, "-C", self.vault] + list(args), capture_output=True, text=True,
                               timeout=self.timeout, stdin=subprocess.DEVNULL)
            return p.returncode, p.stdout
        except Exception:
            return 1, ""

    def oldest_unsynced_mtime(self):
        rc, out = self._call("status", "--porcelain", "-z", "--untracked-files=all")
        if rc != 0:
            return None
        times = []
        entries = out.split("\0")
        i = 0
        while i < len(entries):
            entry = entries[i]
            i += 1
            if len(entry) < 4:
                continue
            code, path = entry[:2], entry[3:]
            if code[0] in "RC":
                i += 1                           # the original path follows a rename or copy
            try:
                times.append(os.path.getmtime(os.path.join(self.vault, path)))
            except OSError:
                pass                             # deleted: no mtime to date it by
        rc_u, _ = self._call("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        if rc_u == 0:
            rc_l, log = self._call("log", "@{u}..HEAD", "--format=%ct")
            if rc_l == 0:
                times += [float(x) for x in log.split() if x.isdigit()]
        return min(times) if times else None
