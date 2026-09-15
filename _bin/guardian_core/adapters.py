"""The guardian's adapters: every place it actually touches the machine.

Each class implements one port from ports.py. Anything external (subprocess, launchctl,
osascript) is injectable so the tests can put a fake in its place; the defaults are the
real thing.

Nothing here decides anything. What is a problem, what to merge, when to speak up —
that is domain.py; these only read and write.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import plistlib
import re
import shlex
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from contextlib import contextmanager

from . import domain as D

HOME = os.path.expanduser("~")
CLT = "/Library/Developer/CommandLineTools"


def default_state_dir() -> str:
    """Brain's own state directory. Resolved by brain_paths.state_dir(), nowhere else.

    Deliberately not under ~/.claude: the guardian's state, queue and raised alerts must
    survive any agent being uninstalled, reset or swapped. (Older scripts still log under
    ~/.claude/state/brain; they are read where needed, never written by the guardian.)
    """
    import brain_paths

    return brain_paths.state_dir()


def legacy_state_dir():
    """Where the pre-guardian scripts (linkfix, tasks) keep their state: brainlib.STATE."""
    try:
        import brainlib as B

        return B.STATE
    except Exception:
        return None


# ---------------------------------------------------------------- file helpers


def atomic_write(path: str, text: str, mode=None) -> None:
    """Write next to the target and rename over it: a reader never sees half a file."""
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


@contextmanager
def locked(path: str):
    """An exclusive advisory lock on `<path>.lock`, for files two processes write."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".lock", "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def plain_run(cmd, cwd=None, timeout=10):
    """(rc, stdout, stderr), stripped. Never raises."""
    try:
        p = subprocess.run(cmd, cwd=cwd, timeout=timeout, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except Exception as exc:
        return 1, "", "%s: %s" % (type(exc).__name__, exc)


def _brainlib_run():
    """brainlib.run, which logs slow subprocesses the way the rest of _bin does."""
    try:
        import brainlib as B

        return lambda cmd, cwd=None, timeout=10: B.run(cmd, cwd=cwd, timeout=timeout)
    except Exception:
        return plain_run


# ---------------------------------------------------------------- launchd


class LaunchctlControl:
    """The launchd jobs the vault defines: every `_bin/*.plist` is one.

    `allowed` narrows them to the labels the user accepted at first run; None means every
    template (tests, and a person running the adapter by hand)."""

    def __init__(self, vault, home=HOME, uid=None, agents_dir=None, launchctl="/bin/launchctl",
                 run=subprocess.run, timeout=15, backup_dir=None, environ=None, clock=None, allowed=None):
        self.vault, self.home = vault, home
        self.allowed = None if allowed is None else set(allowed)
        self.uid = os.getuid() if uid is None else uid
        self.agents_dir = agents_dir or os.path.join(home, "Library", "LaunchAgents")
        self.launchctl, self.run, self.timeout = launchctl, run, timeout
        self.backup_dir = backup_dir
        self.environ = os.environ if environ is None else environ
        self.clock = clock or SystemClock()

    def _call(self, *args):
        try:
            p = self.run([self.launchctl] + list(args), capture_output=True, text=True,
                         timeout=self.timeout, stdin=subprocess.DEVNULL)
            return p.returncode, p.stdout or "", p.stderr or ""
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, "", "%s: %s" % (type(exc).__name__, exc)

    def _template(self, label):
        return os.path.join(self.vault, "_bin", label + ".plist")

    def _installed(self, label):
        return os.path.join(self.agents_dir, label + ".plist")

    def labels(self) -> list:
        folder = os.path.join(self.vault, "_bin")
        try:
            names = sorted(f[:-len(".plist")] for f in os.listdir(folder) if f.endswith(".plist"))
        except OSError:
            return []
        return [n for n in names if self.allowed is None or n in self.allowed]

    def installed(self, label) -> bool:
        return os.path.exists(self._installed(label))

    def is_loaded(self, label) -> bool:
        return self._call("print", "gui/%d/%s" % (self.uid, label))[0] == 0

    def last_exit_ok(self, label):
        rc, out, _ = self._call("list", label)
        if rc != 0:
            return False, "not listed by launchctl (exit %d)" % rc
        m = re.search(r'"LastExitStatus"\s*=\s*(-?\d+)\s*;', out)
        if not m:
            return True, "never exited"
        status = int(m.group(1))
        return status == 0, "LastExitStatus=%d" % status

    def render(self, label) -> str:
        """The vault's plist with the original machine's paths rewritten, like bootstrap.sh."""
        with open(self._template(label), encoding="utf-8") as fh:
            text = fh.read()
        return text.replace(D.ORIGIN_VAULT, self.vault).replace(D.ORIGIN_HOME, self.home)

    def install(self, label):
        try:
            text = self.render(label)
            data = plistlib.loads(text.encode("utf-8"))
            for key in ("StandardOutPath", "StandardErrorPath"):
                if data.get(key):
                    os.makedirs(os.path.dirname(data[key]), exist_ok=True)
            atomic_write(self._installed(label), text)
            return True, self._installed(label)
        except Exception as exc:
            return False, "%s: %s" % (type(exc).__name__, exc)

    def bootstrap(self, label):
        rc, out, err = self._call("bootstrap", "gui/%d" % self.uid, self._installed(label))
        return rc == 0, (err or out).strip()

    def drifted(self, label) -> bool:
        """The installed plist is not what the vault's template renders to on this machine."""
        try:
            with open(self._installed(label), encoding="utf-8") as fh:
                return fh.read() != self.render(label)
        except OSError:
            return False

    def self_label(self) -> str:
        """The launchd job this process runs as (launchd sets XPC_SERVICE_NAME), or ""."""
        name = self.environ.get("XPC_SERVICE_NAME") or ""
        return name if name.startswith("com.") else ""

    def reinstall(self, label):
        """Back the drifted plist up, rewrite it from the template and make launchd reread it.

        The backup goes to the state directory, not next to the plist: launchd reads
        LaunchAgents at login, and a stray copy there is one more thing it might load.
        """
        try:
            backup_dir = self.backup_dir or os.path.join(default_state_dir(), "plist-backups")
            os.makedirs(backup_dir, exist_ok=True)
            stamp = self.clock.now().strftime("%Y%m%d-%H%M%S")
            backup = os.path.join(backup_dir, "%s.plist.%s" % (label, stamp))
            shutil.copy2(self._installed(label), backup)
        except Exception as exc:
            return False, "backup failed, plist left as it was: %s: %s" % (type(exc).__name__, exc)
        note = "previous plist in %s" % backup          # the repair alert lists it
        was_loaded = self.is_loaded(label)
        done, detail = self.install(label)
        if not done:
            return False, "%s; %s" % (detail, note)
        if was_loaded:
            self._call("bootout", "gui/%d/%s" % (self.uid, label))
            done, detail = self.bootstrap(label)
            return done, "; ".join(x for x in (note, detail) if x)
        return True, "rewritten (not loaded); " + note


# ---------------------------------------------------------------- small adapters


class SystemClock:
    def now(self) -> dt.datetime:
        return dt.datetime.now()


def _as_quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


class OsascriptNotifier:
    """A macOS notification. Best effort: no GUI session, no notification, no error."""

    def __init__(self, run=subprocess.run, osascript="/usr/bin/osascript", timeout=10):
        self.run, self.osascript, self.timeout = run, osascript, timeout

    def notify(self, title: str, message: str) -> None:
        script = "display notification %s with title %s" % (_as_quote(message), _as_quote(title))
        try:
            self.run([self.osascript, "-e", script], capture_output=True, text=True,
                     timeout=self.timeout, stdin=subprocess.DEVNULL)
        except Exception:
            pass


class LocalPaths:
    def exists(self, path: str) -> bool:
        return os.path.exists(path)


class JsonStateStore:
    def __init__(self, path):
        self.path = path

    def load(self) -> dict:
        return read_json(self.path, {})

    def save(self, data: dict) -> None:
        atomic_write(self.path, json.dumps(data, indent=2, sort_keys=True))


# ---------------------------------------------------------------- raised alerts


def raised_path() -> str:
    return os.path.join(default_state_dir(), "guardian-raised.json")


class RaisedAlertsFile:
    """Alerts other processes raise for the guardian to carry (the task runner's failures)."""

    def __init__(self, path=None):
        self.path = path or raised_path()

    def load(self) -> dict:
        return read_json(self.path, {})


def raise_alert(key: str, summary: str, severity: str = D.FAIL, path=None) -> None:
    """Record a problem the next guardian run will report. Replaces the same key."""
    path = path or raised_path()
    with locked(path):
        data = read_json(path, {})
        data[key] = {"severity": severity, "summary": summary,
                     "at": dt.datetime.now().isoformat(timespec="seconds")}
        atomic_write(path, json.dumps(data, indent=2, sort_keys=True))


def clear_alert(key: str, path=None) -> None:
    """The problem behind `key` is gone (the routine succeeded). No-op when never raised."""
    path = path or raised_path()
    if key not in read_json(path, {}):
        return
    with locked(path):
        data = read_json(path, {})
        if data.pop(key, None) is not None:
            atomic_write(path, json.dumps(data, indent=2, sort_keys=True))


# ---------------------------------------------------------------- probes


class VaultDoctorProbe:
    """Sync, index and link health, read the way doctor.py reads them."""

    def __init__(self, vault, state_dir=None, git="/usr/bin/git", run=None, now=time.time):
        self.vault = vault
        self.state_dir = state_dir or legacy_state_dir()     # linkfix.json lives there
        self.git, self.now = git, now
        self.run = run or _brainlib_run()

    def sync_status(self):
        rc, out, err = self.run([self.git, "status", "--porcelain"], cwd=self.vault)
        if rc != 0:
            raise RuntimeError("git status failed in %s: %s" % (self.vault, err or rc))
        pending = len([l for l in out.splitlines() if l.strip()])
        rc_u, _, _ = self.run([self.git, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
                              cwd=self.vault)
        remote_ok = rc_u == 0
        unpushed = None
        if remote_ok:
            rc, out, _ = self.run([self.git, "log", "@{u}..HEAD", "--format=%ct"], cwd=self.vault)
            stamps = [int(x) for x in out.split() if x.isdigit()]
            if rc == 0 and stamps:
                unpushed = max(0.0, self.now() - min(stamps))
        return D.SyncStatus(pending=pending, unpushed_age_s=unpushed, remote_ok=remote_ok)

    def index_age_s(self):
        try:
            return max(0.0, self.now() - os.path.getmtime(os.path.join(self.vault, "_index", "vault.db")))
        except OSError:
            return None

    def broken_links(self) -> int:
        if not self.state_dir:
            return 0
        return len(read_json(os.path.join(self.state_dir, "linkfix.json"), {}).get("broken") or [])


def _git_hook_names() -> tuple:
    """The git hooks Brain generates: events_core's list, the one brain_watch.py writes from."""
    from events_core import domain as ED

    return tuple(ED.GIT_HOOKS)


class GitHooksControl:
    """core.hooksPath and the githooks/ files of the vault's repository.

    One key, in one file: the main repository's config, found with
    `git rev-parse --git-common-dir` and then read and written with `git config --file`.
    From a linked worktree of the vault that is the same shared .git/config, which is the
    point: the hooks are the vault's, for every checkout. `--file` is what keeps
    config.worktree, the global and the system config out of reach, even when
    extensions.worktreeConfig is on.
    """

    def __init__(self, vault, git="/usr/bin/git", run=plain_run, names=None):
        self.vault, self.git, self.run = vault, git, run
        self.names = tuple(names) if names else _git_hook_names()

    def _config_file(self) -> str:
        rc, out, err = self.run([self.git, "-C", self.vault, "rev-parse", "--git-common-dir"])
        if rc != 0 or not out:
            raise RuntimeError("not a git repository: %s (%s)" % (self.vault, err or "exit %d" % rc))
        return os.path.join(os.path.normpath(os.path.join(self.vault, out)), "config")

    def _hook(self, name) -> str:
        return os.path.join(self.vault, D.GIT_HOOKS_DIR, name)

    def status(self):
        config = self._config_file()
        rc, out, err = self.run([self.git, "config", "--file", config, "--get", "core.hooksPath"])
        if rc not in (0, 1):                                  # 1: the key is not set
            raise RuntimeError("git config --get core.hooksPath failed on %s: %s" % (config, err or rc))
        files = []
        for name in self.names:
            path = self._hook(name)
            exists = os.path.isfile(path)
            files.append(D.GitHookFile(name, exists, exists and os.access(path, os.X_OK)))
        return D.GitHooksStatus(out if rc == 0 else None, files)

    def set_hooks_path(self):
        try:
            config = self._config_file()
        except RuntimeError as exc:
            return False, str(exc)
        rc, _, err = self.run([self.git, "config", "--file", config, "core.hooksPath", D.GIT_HOOKS_DIR])
        if rc != 0:
            return False, err or "git config exit %d" % rc
        return True, "core.hooksPath = %s in %s" % (D.GIT_HOOKS_DIR, config)

    def make_executable(self, name):
        """chmod +x: an execute bit wherever there is a read bit. Only Brain's own hook files."""
        if name not in self.names:
            return False, "%s is not one of Brain's git hooks" % name
        path = self._hook(name)
        try:
            mode = stat.S_IMODE(os.stat(path).st_mode)
            new = mode | ((mode & 0o444) >> 2)
            os.chmod(path, new)
        except OSError as exc:
            return False, "%s: %s" % (type(exc).__name__, exc)
        return True, "%s mode %o" % (path, new)


class TokenPoolProbe:
    """The agent routines' token pool: 90-Meta/routine-tokens.json plus the state file
    routine_auth_core writes after every attempt. Reads both, writes neither, never reads
    KeePass. The pool rules (parsing, expiry, the renewal commands) are routine_auth_core's;
    this is where the two hexagons meet.
    """

    def __init__(self, pool_path, state_path):
        self.pool_path, self.state_path = pool_path, state_path

    def pool(self):
        from routine_auth_core import domain as RA

        if not os.path.exists(self.pool_path):
            return D.TokenPool([])
        try:
            with open(self.pool_path, encoding="utf-8") as fh:
                entries = RA.parse_pool(fh.read())
        except OSError as exc:
            return D.TokenPool([], "unreadable: %s" % type(exc).__name__)
        except RA.PoolConfigError as exc:
            return D.TokenPool([], str(exc))
        state = read_json(self.state_path, {})
        tokens = []
        for e in entries:
            s = state.get(e.label) if isinstance(state.get(e.label), dict) else {}
            tokens.append(D.TokenHealth(
                label=e.label, account=e.account, kp_ref=e.kp_ref, status=s.get("status") or "healthy",
                until=s.get("until"), last_kind=s.get("last_kind"), last_at=s.get("last_at"),
                detail=s.get("detail") or "", expires=RA.expires_on(e.issued).isoformat(),
                renew=RA.renew_command(e.kp_ref), restore=RA.restore_command(e.kp_ref)))
        return D.TokenPool(tokens)


class DesktopScheduledTasksProbe:
    """Enabled Claude app scheduled tasks, per account: every
    `<sessions dir>/<account>/<session>/scheduled-tasks.json` `scheduledTasks[]` entry with
    `enabled: true`. Reads only; a file that does not parse is skipped."""

    def __init__(self, sessions_dir):
        self.sessions_dir = sessions_dir

    def enabled(self) -> list:
        out = []
        try:
            accounts = sorted(os.listdir(self.sessions_dir))
        except OSError:
            return out
        for account in accounts:
            account_dir = os.path.join(self.sessions_dir, account)
            if not os.path.isdir(account_dir):
                continue
            try:
                sessions = sorted(os.listdir(account_dir))
            except OSError:
                continue
            for session in sessions:
                tasks = read_json(os.path.join(account_dir, session, "scheduled-tasks.json"), {}).get("scheduledTasks")
                if not isinstance(tasks, list):
                    continue
                for t in tasks:
                    if isinstance(t, dict) and t.get("enabled") is True and isinstance(t.get("id"), str):
                        item = (t["id"], account)
                        if item not in out:
                            out.append(item)
        return out


class InterpreterHealthProbe:
    """Does python3 run? The hooks' interpreter first, judged the way hooks run it."""

    DEFAULT_FALLBACKS = ("/usr/bin/python3", "/opt/homebrew/bin/python3", "/usr/local/bin/python3")

    def __init__(self, hook_python="/usr/bin/python3", fallbacks=DEFAULT_FALLBACKS, clt=CLT,
                 run=subprocess.run, timeout=10):
        self.hook_python, self.fallbacks = hook_python, list(fallbacks)
        self.clt, self.run, self.timeout = clt, run, timeout

    def _probe(self, path, extra_env=None):
        if not os.path.exists(path):
            return False, "missing"
        env = dict(os.environ)
        env.pop("DEVELOPER_DIR", None)       # hooks and launchd do not carry the caller's
        env.update(extra_env or {})
        try:
            p = self.run([path, "-c", "import sqlite3"], env=env, capture_output=True, text=True,
                         timeout=self.timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return False, "timed out"
        except OSError as exc:
            return False, "%s: %s" % (type(exc).__name__, exc)
        if p.returncode == 0:
            return True, "ok"
        last = (p.stderr or "").strip().splitlines()
        return False, "exit %d%s" % (p.returncode, (": " + last[-1][:120]) if last else "")

    def python3_health(self) -> list:
        out = [D.InterpreterStatus(self.hook_python, *self._probe(self.hook_python))]
        for c in self.fallbacks:
            if os.path.isdir(self.clt) and os.path.exists(c):
                out.append(D.InterpreterStatus("%s (DEVELOPER_DIR=%s)" % (c, self.clt),
                                               *self._probe(c, {"DEVELOPER_DIR": self.clt})))
            out.append(D.InterpreterStatus(c, *self._probe(c)))
        return out


# ---------------------------------------------------------------- routines and agents


def strip_frontmatter(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + len("\n---\n"):]
    return text


def load_agent_command(vault: str, environ=None) -> str:
    """The agent command template: BRAIN_AGENT_CMD, else 90-Meta/agent-command.txt.

    Configuration, never code: switching to another CLI agent, account or model is
    editing that one line. Blank lines and `#` comments are skipped.
    """
    environ = os.environ if environ is None else environ
    value = (environ.get("BRAIN_AGENT_CMD") or "").strip()
    if value:
        return value
    try:
        with open(os.path.join(vault, "90-Meta", "agent-command.txt"), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    except OSError:
        pass
    return ""


def _split(template: str) -> list:
    try:
        return shlex.split(template or "")
    except ValueError:
        return []


class CliAgentRunner:
    """Runs a routine through whatever CLI agent the template names.

    `{prompt}` becomes the routine's body (frontmatter stripped) as one argument,
    `{prompt_file}` its path. The agent runs in its own process group so a timeout kills
    everything it started, not just the top process.
    """

    def __init__(self, template, cwd=None, env=None, popen=subprocess.Popen, which=shutil.which):
        self.template, self.cwd, self.env = template, cwd, env
        self.popen, self.which = popen, which

    def available(self) -> bool:
        toks = _split(self.template)
        if not toks:
            return False
        if "/" in toks[0]:
            return os.path.isfile(toks[0]) and os.access(toks[0], os.X_OK)
        return self.which(toks[0], path=(self.env or os.environ).get("PATH")) is not None

    def run(self, prompt_path: str, timeout: int):
        toks = _split(self.template)
        if not toks:
            return 127, "", "no agent command configured (90-Meta/agent-command.txt or BRAIN_AGENT_CMD)"
        try:
            with open(prompt_path, encoding="utf-8") as fh:
                body = strip_frontmatter(fh.read()).strip()
        except OSError as exc:
            return 2, "", "routine file unreadable: %s" % exc
        argv = [t.replace("{prompt_file}", prompt_path).replace("{prompt}", body) for t in toks]
        try:
            proc = self.popen(argv, cwd=self.cwd, env=self.env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              start_new_session=True)
        except FileNotFoundError:
            return 127, "", "agent command not found: %s" % toks[0]
        except PermissionError:
            return 126, "", "agent command not executable: %s" % toks[0]
        except OSError as exc:
            return 1, "", "%s: %s" % (type(exc).__name__, exc)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            out, err = proc.communicate()
            return 124, out or "", (err or "") + "agent timed out after %ss" % timeout
        return proc.returncode, out or "", err or ""


def _routine_permission_problem(text: str):
    """routine_auth_core's verdict on a routine's agent_args: where the two hexagons meet."""
    from routine_auth_core import domain as RA

    args, _ = RA.parse_agent_args(text)
    return RA.permission_problem(args)


class TasksRegistrySource:
    """The routines as tasks.py sees them: its registry parser and its local state."""

    def __init__(self, tasks_module=None):
        self._tasks = tasks_module

    def _t(self):
        if self._tasks is None:
            import tasks

            self._tasks = tasks
        return self._tasks

    def host(self) -> str:
        return self._t().host()

    def routines(self) -> list:
        return self._t().read_registry()

    def last_runs(self) -> dict:
        return self._t().load_state()

    def meta(self, row) -> dict:
        path = row.get("command") or ""
        if not os.path.isabs(path):
            path = os.path.join(str(self._t().VAULT), path)
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            text = ""
        meta = D.routine_meta(text)
        meta["permission_problem"] = _routine_permission_problem(text)
        return meta


# ---------------------------------------------------------------- hook liveness


class HookLivenessSource:
    """Evidence that Brain's hooks fire, gathered with no agent in the loop.

    - Claude Code writes one transcript per session, `<projects>/<project dir>/<session uuid>.jsonl`.
      Subagent transcripts sit one directory deeper and are not sessions.
    - Every Brain hook appends one line per run to `<brain state>/logs/heartbeat.jsonl`
      (brainlib.heartbeat), rotated to `.1` ... `.5`.
    - The event registry says which hook each event is and how often it should fire.
    - The epoch file records when liveness started, so no session from before it is judged.
    - An optional JSON config (`window_min`, `silent_days`, `ignore_dirs`) changes the windows.
    """

    def __init__(self, projects_dir, heartbeat_log, registry_path, epoch_path, config_path=None, keep=5):
        self.projects_dir, self.heartbeat_log = projects_dir, heartbeat_log
        self.registry_path, self.epoch_path, self.config_path = registry_path, epoch_path, config_path
        self.keep = keep

    def sessions(self, since):
        out = []
        try:
            dirs = sorted(os.listdir(self.projects_dir))
        except OSError:
            return out
        for d in dirs:
            folder = os.path.join(self.projects_dir, d)
            try:
                names = sorted(os.listdir(folder))
            except OSError:
                continue
            for name in names:
                if not name.endswith(".jsonl"):
                    continue
                try:
                    st = os.stat(os.path.join(folder, name))
                except OSError:
                    continue
                if not stat.S_ISREG(st.st_mode) or st.st_mtime < since:
                    continue
                started = getattr(st, "st_birthtime", None) or st.st_mtime
                out.append(D.SessionTranscript(D.session_sid(name[:-len(".jsonl")]), d,
                                               min(started, st.st_mtime), st.st_mtime))
        return out

    def heartbeats(self, since):
        out = []
        paths = [self.heartbeat_log] + ["%s.%d" % (self.heartbeat_log, i) for i in range(1, self.keep + 1)]
        for path in paths:
            try:
                if os.path.getmtime(path) < since:
                    continue          # last written before the horizon: every line in it is older
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        try:
                            h = D.heartbeat_from_record(json.loads(line))
                        except ValueError:
                            continue
                        if h is not None and h.ts >= since:
                            out.append(h)
            except OSError:
                continue
        out.sort(key=lambda h: h.ts)
        return out

    def events(self):
        from events_core import domain as ED     # the registry's own parser: the two hexagons meet in adapters

        with open(self.registry_path, encoding="utf-8") as fh:
            registry = ED.load_registry(fh.read())
        return [D.HookEventSpec(e.id, t.spec["event"], D.hook_identity(t.spec["command"]) or t.spec["command"],
                                getattr(e, "liveness", "") or D.LIVENESS_REGULAR)
                for e, t in registry.triggers("claude-hook")]

    def epoch(self):
        v = read_json(self.epoch_path, {}).get("since")
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def start_epoch(self, ts):
        with locked(self.epoch_path):
            current = self.epoch()
            if current is not None:
                return current
            atomic_write(self.epoch_path, json.dumps({"since": ts}))
            return ts

    def config(self):
        import dataclasses

        raw = read_json(self.config_path, {}) if self.config_path else {}
        base = D.LivenessConfig()

        def number(key, scale, default):
            v = raw.get(key)
            return float(v) * scale if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else default

        extra = tuple(p for p in (raw.get("ignore_dirs") or []) if isinstance(p, str))
        return dataclasses.replace(base, window_s=number("window_min", 60, base.window_s),
                                   silent_s=number("silent_days", 86400, base.silent_s),
                                   ignore_dirs=base.ignore_dirs + extra)


class HookProbe:
    """Every canonical Brain hook, run the way Claude Code runs it, with no Claude at all.

    Same interpreter and script path as hooks.json, Claude Code's stdin for the event, the
    hook's timeout. Everything a hook writes lands in a scratch directory made for the run and
    removed after it: HOME, BRAIN_STATE, BRAIN_VAULT and TMPDIR all point inside it, BRAIN_OFFLINE
    stops presence, lease, pull, reindex and link-repair processes, git cannot discover a
    repository above it, and no bytecode is written beside the real scripts. The environment is
    built from scratch, so neither DEVELOPER_DIR nor the caller's Brain variables leak in. Runs
    once per process: check, repair and status share the results.
    """

    KEEP_ENV = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "USER", "LOGNAME", "SHELL")

    def __init__(self, canonical, events, run=subprocess.run, scratch_root=None, environ=None):
        self.canonical, self.events = canonical, events
        self.run, self.scratch_root = run, scratch_root
        self.environ = os.environ if environ is None else environ
        self.ran = False
        self._results = []

    def _env(self, root):
        env = {k: self.environ[k] for k in self.KEEP_ENV if self.environ.get(k)}
        env.setdefault("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
        env.update({"HOME": os.path.join(root, "home"), "TMPDIR": root,
                    "BRAIN_STATE": os.path.join(root, "state"), "BRAIN_VAULT": os.path.join(root, "vault"),
                    "BRAIN_OFFLINE": "1", "PYTHONDONTWRITEBYTECODE": "1",
                    "GIT_CEILING_DIRECTORIES": "%s:%s" % (root, os.path.realpath(root)),
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        return env

    def _one(self, case, env, cwd):
        try:
            argv = shlex.split(case.command)
        except ValueError as exc:
            return D.ProbeResult(case.event_id, None, error="command does not parse: %s" % exc)
        try:
            p = self.run(argv, input=json.dumps(case.stdin), env=env, cwd=cwd, capture_output=True, text=True,
                         timeout=case.timeout)
        except subprocess.TimeoutExpired:
            return D.ProbeResult(case.event_id, None, timed_out=True)
        except OSError as exc:
            return D.ProbeResult(case.event_id, None, error="%s: %s" % (type(exc).__name__, exc))
        stdout, stderr = p.stdout or "", p.stderr or ""
        parsed, parse_error = None, ""
        if stdout.lstrip().startswith("{"):
            try:
                parsed = json.loads(stdout)
            except ValueError as exc:
                parse_error = str(exc)
        return D.ProbeResult(case.event_id, p.returncode, stdout[-4000:], stderr[-4000:],
                             parsed=parsed, parse_error=parse_error)

    def results(self):
        if self.ran:
            return list(self._results)
        root = tempfile.mkdtemp(prefix="brain-hook-probe-", dir=self.scratch_root)
        try:
            for sub in ("home", "state", "work", os.path.join("vault", "_index")):
                os.makedirs(os.path.join(root, sub), exist_ok=True)
            env, cwd = self._env(root), os.path.join(root, "work")
            results = [(case, self._one(case, env, cwd))
                       for case in D.probe_cases(self.canonical.load(), self.events.events(), cwd)]
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self._results, self.ran = results, True
        return list(results)


# ---------------------------------------------------------------- scheduled jobs beyond launchd


class SystemdUserControl:
    """The scheduled jobs the vault defines, as systemd user units (Linux).

    Every `_bin/systemd/<label>.timer` with its `<label>.service` is one job. Same port as
    LaunchctlControl: install writes both units into ~/.config/systemd/user and reloads the
    user manager, bootstrap enables and starts the timer, reinstall backs drifted units up
    first. `allowed` narrows the jobs to the ones accepted at first run.
    """

    def __init__(self, vault, home=HOME, units_dir=None, systemctl="systemctl", run=subprocess.run, timeout=15,
                 backup_dir=None, environ=None, clock=None, allowed=None):
        self.vault, self.home = vault, home
        self.units_dir = units_dir or os.path.join(home, ".config", "systemd", "user")
        self.systemctl, self.run, self.timeout = systemctl, run, timeout
        self.backup_dir = backup_dir
        self.environ = os.environ if environ is None else environ
        self.clock = clock or SystemClock()
        self.allowed = None if allowed is None else set(allowed)

    def _call(self, *args):
        try:
            p = self.run([self.systemctl, "--user"] + list(args), capture_output=True, text=True,
                         timeout=self.timeout, stdin=subprocess.DEVNULL)
            return p.returncode, p.stdout or "", p.stderr or ""
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, "", "%s: %s" % (type(exc).__name__, exc)

    def _folder(self):
        return os.path.join(self.vault, "_bin", "systemd")

    @staticmethod
    def _units(label):
        return (label + ".service", label + ".timer")

    def labels(self) -> list:
        try:
            names = sorted(f[:-len(".timer")] for f in os.listdir(self._folder()) if f.endswith(".timer"))
        except OSError:
            return []
        return [n for n in names if self.allowed is None or n in self.allowed]

    def render(self, label) -> dict:
        out = {}
        for unit in self._units(label):
            with open(os.path.join(self._folder(), unit), encoding="utf-8") as fh:
                out[unit] = fh.read().replace(D.ORIGIN_VAULT, self.vault).replace(D.ORIGIN_HOME, self.home)
        return out

    def installed(self, label) -> bool:
        return all(os.path.exists(os.path.join(self.units_dir, u)) for u in self._units(label))

    def is_loaded(self, label) -> bool:
        return self._call("is-active", "--quiet", label + ".timer")[0] == 0

    def last_exit_ok(self, label):
        rc, out, _ = self._call("show", label + ".service", "--property=Result", "--property=ExecMainStatus")
        if rc != 0:
            return False, "not known to systemctl (exit %d)" % rc
        props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        result = (props.get("Result") or "success").strip()
        status = (props.get("ExecMainStatus") or "0").strip()
        return result == "success" and status == "0", "Result=%s ExecMainStatus=%s" % (result, status)

    def install(self, label):
        try:
            for unit, text in self.render(label).items():
                atomic_write(os.path.join(self.units_dir, unit), text)
        except Exception as exc:
            return False, "%s: %s" % (type(exc).__name__, exc)
        rc, out, err = self._call("daemon-reload")
        if rc != 0:
            return False, "daemon-reload failed: %s" % (err or out).strip()
        return True, os.path.join(self.units_dir, label + ".timer")

    def bootstrap(self, label):
        rc, out, err = self._call("enable", "--now", label + ".timer")
        return rc == 0, (err or out).strip()

    def drifted(self, label) -> bool:
        """An installed unit is not what the vault's template renders to on this machine."""
        try:
            for unit, text in self.render(label).items():
                with open(os.path.join(self.units_dir, unit), encoding="utf-8") as fh:
                    if fh.read() != text:
                        return True
        except OSError:
            return False
        return False

    def self_label(self) -> str:
        """The job this process runs as: the units set BRAIN_JOB_LABEL, or ""."""
        return self.environ.get("BRAIN_JOB_LABEL") or ""

    def reinstall(self, label):
        try:
            backup_dir = self.backup_dir or os.path.join(default_state_dir(), "unit-backups")
            os.makedirs(backup_dir, exist_ok=True)
            stamp = self.clock.now().strftime("%Y%m%d-%H%M%S")
            for unit in self._units(label):
                src = os.path.join(self.units_dir, unit)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(backup_dir, "%s.%s" % (unit, stamp)))
        except Exception as exc:
            return False, "backup failed, units left as they were: %s: %s" % (type(exc).__name__, exc)
        note = "previous units in %s" % backup_dir
        was_loaded = self.is_loaded(label)
        done, detail = self.install(label)
        if not done:
            return False, "%s; %s" % (detail, note)
        if was_loaded:
            rc, out, err = self._call("restart", label + ".timer")
            return rc == 0, "; ".join(x for x in (note, (err or out).strip()) if x)
        return True, "rewritten (not loaded); " + note


CRON_BEGIN = "# BEGIN second-brain (managed by guardian.py; edit _bin/cron/*.cron in the vault instead)"
CRON_END = "# END second-brain"


class CronControl:
    """Where there are no systemd user units: one crontab line per job, inside a block Brain owns.

    Every `_bin/cron/<label>.cron` is one job (its first line that is not a comment); the line
    installed ends in `# brain:<label>`. Lines outside the block are never touched. Cron keeps
    no exit status and needs no load step, so those two answers are fixed.
    """

    def __init__(self, vault, home=HOME, crontab="crontab", run=subprocess.run, timeout=15, environ=None,
                 allowed=None):
        self.vault, self.home = vault, home
        self.crontab, self.run, self.timeout = crontab, run, timeout
        self.environ = os.environ if environ is None else environ
        self.allowed = None if allowed is None else set(allowed)

    def _call(self, args, stdin=None):
        try:
            p = self.run([self.crontab] + list(args), input=stdin, capture_output=True, text=True,
                         timeout=self.timeout)
            return p.returncode, p.stdout or "", p.stderr or ""
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, "", "%s: %s" % (type(exc).__name__, exc)

    def _folder(self):
        return os.path.join(self.vault, "_bin", "cron")

    def labels(self) -> list:
        try:
            names = sorted(f[:-len(".cron")] for f in os.listdir(self._folder()) if f.endswith(".cron"))
        except OSError:
            return []
        return [n for n in names if self.allowed is None or n in self.allowed]

    def render(self, label) -> str:
        with open(os.path.join(self._folder(), label + ".cron"), encoding="utf-8") as fh:
            lines = [l.strip() for l in fh if l.strip() and not l.strip().startswith("#")]
        line = lines[0].replace(D.ORIGIN_VAULT, self.vault).replace(D.ORIGIN_HOME, self.home)
        return "%s # brain:%s" % (line, label)

    def _split(self):
        rc, out, _ = self._call(["-l"])
        lines = out.splitlines() if rc == 0 else []
        if CRON_BEGIN in lines and CRON_END in lines[lines.index(CRON_BEGIN):]:
            i = lines.index(CRON_BEGIN)
            j = lines.index(CRON_END, i)
            return lines[:i], lines[i + 1:j], lines[j + 1:]
        return lines, [], []

    def _line(self, label):
        marker = "# brain:%s" % label
        return next((l for l in self._split()[1] if l.endswith(marker)), None)

    def installed(self, label) -> bool:
        return self._line(label) is not None

    def is_loaded(self, label) -> bool:
        return self.installed(label)

    def last_exit_ok(self, label):
        return True, "cron keeps no exit status"

    def install(self, label):
        try:
            wanted = self.render(label)
        except (OSError, IndexError) as exc:
            return False, "%s: %s" % (type(exc).__name__, exc)
        before, block, after = self._split()
        block = [l for l in block if not l.endswith("# brain:%s" % label)] + [wanted]
        text = "\n".join(before + [CRON_BEGIN] + block + [CRON_END] + after) + "\n"
        rc, out, err = self._call(["-"], stdin=text)
        return rc == 0, (err or out).strip() or "crontab updated"

    def bootstrap(self, label):
        return True, "cron runs installed lines without a load step"

    def drifted(self, label) -> bool:
        line = self._line(label)
        try:
            return line is not None and line != self.render(label)
        except (OSError, IndexError):
            return False

    def self_label(self) -> str:
        return self.environ.get("BRAIN_JOB_LABEL") or ""

    def reinstall(self, label):
        done, detail = self.install(label)
        return done, "rewritten; " + detail


class NotifySendNotifier:
    """A desktop notification on Linux, through notify-send. Best effort, like OsascriptNotifier."""

    def __init__(self, run=subprocess.run, notify_send="notify-send", timeout=10):
        self.run, self.notify_send, self.timeout = run, notify_send, timeout

    def notify(self, title: str, message: str) -> None:
        try:
            self.run([self.notify_send, "--app-name=Brain", title, message], capture_output=True, text=True,
                     timeout=self.timeout, stdin=subprocess.DEVNULL)
        except Exception:
            pass


def default_notifier(platform=None, which=shutil.which):
    """osascript on macOS, notify-send elsewhere."""
    import sys as _sys

    if (platform or _sys.platform) == "darwin":
        return OsascriptNotifier()
    return NotifySendNotifier(notify_send=which("notify-send") or "notify-send")


# ---------------------------------------------------------------- first-run consent

JOBS = ("guardian", "sync", "tasks", "watch")
SCHEDULERS = ("launchd", "systemd", "cron")


def first_run_state_path(state_dir=None) -> str:
    """Where integrations/first-run keeps the user's answers: <brain state>/first-run.json."""
    return os.path.join(state_dir or default_state_dir(), "first-run.json")


def consented_jobs(path):
    """(scheduler kind, [job names]) the user accepted at first run; ("", []) when nothing was.

    Brain installs no scheduled job the user did not accept there: the guardian repairs and
    reloads only these."""
    data = read_json(path, {})
    sched = data.get("scheduler") if isinstance(data, dict) else None
    if not isinstance(sched, dict) or sched.get("kind") not in SCHEDULERS:
        return "", []
    return sched["kind"], [j for j in (sched.get("jobs") or []) if j in JOBS]


def job_label(kind: str, job: str) -> str:
    return ("com.secondbrain.%s" % job) if kind == "launchd" else ("second-brain-%s" % job)


def build_job_control(vault, state_dir=None, home=HOME):
    """The scheduler adapter for what the user accepted: launchd, systemd user units or cron."""
    kind, jobs = consented_jobs(first_run_state_path(state_dir))
    labels = [job_label(kind, j) for j in jobs]
    if kind == "systemd":
        return SystemdUserControl(vault=vault, home=home, allowed=labels)
    if kind == "cron":
        return CronControl(vault=vault, home=home, allowed=labels)
    return LaunchctlControl(vault=vault, home=home, allowed=labels)
