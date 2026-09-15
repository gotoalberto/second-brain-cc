"""The first run's adapters: the terminal, kp.py, google.py, the files directory, agent CLIs, the shell profile,
the guardian's scheduler adapters and the routine token pool.

Each class implements one port from ports.py. Every method that changes the machine returns
(ok, detail) and never raises, so one failed step never ends the run.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shlex
import shutil
import subprocess
import sys

from . import domain as D

VAULT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
BIN = os.path.join(VAULT, "_bin")
if BIN not in sys.path:
    sys.path.insert(0, BIN)


def _private_write(path, text):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _last_line(text):
    lines = (text or "").strip().splitlines()
    return lines[-1][:200] if lines else ""


# ---------------------------------------------------------------- terminal


class TtyPrompt:
    def __init__(self, stdin=None, stdout=None):
        self.stdin, self.stdout = stdin or sys.stdin, stdout or sys.stdout

    def interactive(self):
        try:
            return self.stdin.isatty()
        except Exception:
            return False

    def say(self, text):
        self.stdout.write(text + "\n")
        self.stdout.flush()

    def _read(self, prompt):
        self.stdout.write(prompt)
        self.stdout.flush()
        line = self.stdin.readline()
        if not line:
            raise EOFError("the terminal closed")
        return line.rstrip("\n")

    def yes_no(self, question, default=False):
        while True:
            answer = D.parse_yes_no(self._read("%s [%s] " % (question, "Y/n" if default else "y/N")), default)
            if answer is not None:
                return answer
            self.say("  Please answer yes or no.")

    def ask(self, question, default=""):
        value = self._read("%s%s: " % (question, " [%s]" % default if default else "")).strip()
        return value or default

    def secret(self, question):
        import getpass

        return getpass.getpass(question + ": ")


# ---------------------------------------------------------------- files


class JsonStateStore:
    def __init__(self, path):
        self.path = path

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                return D.parse_state(fh.read())
        except OSError:
            return D.new_state()

    def save(self, state):
        _private_write(self.path, D.render_state(state))


class MailConfigFile:
    def __init__(self, path):
        self.path = path

    def save(self, config):
        _private_write(self.path, json.dumps(config, indent=2, ensure_ascii=False) + "\n")
        return self.path


# ---------------------------------------------------------------- vault scripts


class KpKdbx:
    def __init__(self, kp, run=subprocess.run):
        self.kp, self.run = kp, run

    def exists(self, path):
        return os.path.exists(os.path.expanduser(path))

    def _call(self, args):
        try:
            p = self.run([sys.executable, self.kp] + args)       # on the terminal: keepassxc-cli may ask
        except OSError as exc:
            return False, "%s: %s" % (type(exc).__name__, exc)
        return p.returncode == 0, "kp.py %s exit %d" % (args[0], p.returncode)

    def init(self, path, create):
        return self._call(["init", "--db", os.path.expanduser(path)] + (["--create"] if create else []))

    def unlock(self):
        return self._call(["unlock"])


class GoogleCli:
    def __init__(self, google, environ=None, run=subprocess.run):
        self.google, self.run = google, run
        self.environ = os.environ if environ is None else environ

    def accounts(self):
        try:
            from google_core import adapters as GA

            return sorted(GA.JsonAccountStore(GA.accounts_path(self.environ)).load())
        except Exception:
            return []

    def add(self, name, client_id, client_secret, login_hint):
        cmd = [sys.executable, self.google, "add", "--account", name, "--client-id", client_id]
        if login_hint:
            cmd += ["--login-hint", login_hint]
        try:
            p = self.run(cmd, input=client_secret + "\n", capture_output=True, text=True, timeout=180,
                         env=dict(os.environ, **{k: v for k, v in self.environ.items() if k.startswith("BRAIN_")}))
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, "%s: %s" % (type(exc).__name__, exc)
        return p.returncode == 0, _last_line(p.stderr) or _last_line(p.stdout)

    def authorize(self, name):
        try:
            p = self.run([sys.executable, self.google, "auth", "--account", name])
        except OSError as exc:
            return False, "%s: %s" % (type(exc).__name__, exc)
        return p.returncode == 0, "google.py auth exit %d" % p.returncode


class LocalFiles:
    """The files directory: proposed, proven writable, and recorded where files.py reads it (brain_files.py)."""

    def __init__(self, home, environ=None, config_path=None):
        self.home, self.config_path = home, config_path
        self.environ = os.environ if environ is None else environ

    def propose_default(self):
        import brain_files

        return (brain_files.files_dir(self.environ, self.home, self.config_path)
                or brain_files.default_files_dir(self.home))

    def check(self, path):
        full = path.strip()
        if full == "~" or full.startswith("~/"):
            full = self.home + full[1:]
        full = os.path.abspath(full)
        probe = os.path.join(full, ".brain-write-probe-%d" % os.getpid())
        try:
            os.makedirs(full, exist_ok=True)
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("ok\n")
            os.remove(probe)
        except OSError as exc:
            return False, "%s: %s" % (type(exc).__name__, exc)
        return True, full

    def persist(self, path):
        import brain_files

        try:
            return True, brain_files.set_files_dir(
                path, config_path=self.config_path or brain_files.config_file(self.environ, self.home))
        except OSError as exc:
            return False, "%s: %s" % (type(exc).__name__, exc)


# ---------------------------------------------------------------- MCP and the shell profile


class McpSetup:
    def __init__(self, vault, home, environ=None, which=shutil.which, run=subprocess.run, platform=None, clock=None):
        self._vault, self.home = vault, home
        self.environ = os.environ if environ is None else environ
        self.which, self.run = which, run
        self.platform = platform or sys.platform
        self.clock = clock or (lambda: dt.datetime.now())

    def vault(self):
        return self._vault

    def snippets(self):
        return D.mcp_snippets(self._vault, "python3")

    def claude_available(self):
        return bool(self.which("claude"))

    def register_claude(self):
        server = os.path.join(self._vault, "integrations", "mcp", "server.py")
        try:
            p = self.run([self.which("claude") or "claude", "mcp", "add", "brain", "--", "python3", server],
                         capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, "%s: %s" % (type(exc).__name__, exc)
        return p.returncode == 0, _last_line(p.stderr) or _last_line(p.stdout)

    def profile_path(self):
        shell = os.path.basename(self.environ.get("SHELL") or "")
        if shell == "zsh":
            return os.path.join(self.home, ".zshrc")
        if shell == "bash":
            return os.path.join(self.home, ".bashrc" if self.platform != "darwin" else ".bash_profile")
        return os.path.join(self.home, ".profile")

    def append_profile(self, line):
        path = self.profile_path()
        try:
            current = open(path, encoding="utf-8").read() if os.path.exists(path) else None
            if current is not None and line in current.splitlines():
                return True, "already in %s" % path
            if current is not None:
                stamp = self.clock().strftime("%Y%m%d-%H%M%S")
                shutil.copy2(path, "%s.bak-second-brain-%s" % (path, stamp))
            with open(path, "a", encoding="utf-8") as fh:
                if current and not current.endswith("\n"):
                    fh.write("\n")
                fh.write("\n# Second Brain vault location (added by the first run)\n%s\n" % line)
        except OSError as exc:
            return False, "%s: %s" % (type(exc).__name__, exc)
        return True, path


# ---------------------------------------------------------------- scheduled jobs


class SchedulerSetup:
    """The guardian's own scheduler adapters, narrowed to the accepted jobs. BRAIN_FAKE_SCHEDULER=1 swaps
    launchctl, systemctl and crontab for `true`: files are written under HOME, no scheduler is told."""

    def __init__(self, vault, home, state_dir, platform=None, environ=None, which=shutil.which):
        self.vault, self.home, self.state_dir = vault, home, state_dir
        self.platform = platform or sys.platform
        self.environ = os.environ if environ is None else environ
        self.which = which

    def detect(self):
        return D.detect_scheduler(self.platform, self.which, self.environ)

    def control(self, kind, labels):
        from guardian_core import adapters as GA

        fake = self.environ.get("BRAIN_FAKE_SCHEDULER") == "1"
        if kind == "launchd":
            return GA.LaunchctlControl(vault=self.vault, home=self.home, launchctl="true" if fake else "/bin/launchctl",
                                       backup_dir=os.path.join(self.state_dir, "plist-backups"), allowed=labels)
        if kind == "systemd":
            return GA.SystemdUserControl(vault=self.vault, home=self.home, systemctl="true" if fake else "systemctl",
                                         backup_dir=os.path.join(self.state_dir, "unit-backups"), allowed=labels)
        return GA.CronControl(vault=self.vault, home=self.home, crontab="true" if fake else "crontab", allowed=labels)

    def preview(self, kind, jobs):
        labels = [D.job_label(kind, j) for j in jobs]
        control = self.control(kind, labels)
        out = []
        for label in labels:
            try:
                rendered = control.render(label)
            except OSError as exc:
                out.append("== %s: no template (%s)" % (label, exc))
                continue
            if kind == "launchd":
                out.append("== %s\n%s" % (os.path.join(self.home, "Library", "LaunchAgents", label + ".plist"), rendered))
            elif kind == "systemd":
                out += ["== %s\n%s" % (unit, text) for unit, text in rendered.items()]
            else:
                out.append("== crontab line\n%s" % rendered)
        return "\n".join(out)

    def install(self, kind, jobs):
        labels = [D.job_label(kind, j) for j in jobs]
        control = self.control(kind, labels)
        results = []
        for label in labels:
            good, detail = control.install(label)
            if good:
                good, loaded = control.bootstrap(label)
                detail = loaded or detail
            results.append((label, good, detail))
        return results


# ---------------------------------------------------------------- routines


class RoutinePool:
    def __init__(self, vault, environ=None):
        self.vault = vault
        self.environ = os.environ if environ is None else environ

    def agent_available(self):
        from guardian_core import adapters as GA

        template = GA.load_agent_command(self.vault, self.environ)
        if not template:
            return False, "no command in 90-Meta/agent-command.txt"
        try:
            exe = os.path.expanduser(shlex.split(template)[0])
        except (ValueError, IndexError):
            return False, "the agent command does not parse"
        if os.path.isfile(exe) and os.access(exe, os.X_OK):
            return True, exe
        found = shutil.which(exe)
        return (True, found) if found else (False, "%s is not installed" % exe)

    def add_token(self, label, kp_ref, issued, account):
        path = os.path.join(self.vault, "90-Meta", "routine-tokens.json")
        try:
            data = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
            tokens = data.get("tokens") if isinstance(data, dict) else None
            tokens = tokens if isinstance(tokens, list) else []
            if any(isinstance(t, dict) and t.get("label") == label for t in tokens):
                return True, "%s is already in the pool" % label
            tokens.append({"label": label, "account": account, "kp_ref": kp_ref, "issued": issued})
            _private_write(path, json.dumps({"tokens": tokens}, indent=2) + "\n")
        except (OSError, ValueError) as exc:
            return False, "%s: %s" % (type(exc).__name__, exc)
        return True, path


# ---------------------------------------------------------------- wiring


class SystemClock:
    def now(self):
        return dt.datetime.now().astimezone()


def build_ports(vault=VAULT, environ=None, stdin=None, stdout=None):
    from . import application as A
    import brain_paths

    environ = os.environ if environ is None else environ
    home = os.path.expanduser("~")
    state = brain_paths.state_dir(environ)
    return A.Ports(
        prompt=TtyPrompt(stdin, stdout),
        state=JsonStateStore(os.path.join(state, "first-run.json")),
        kdbx=KpKdbx(os.path.join(vault, "_bin", "kp.py")),
        google=GoogleCli(os.path.join(vault, "_bin", "google.py"), environ),
        files=LocalFiles(home, environ),
        mail=MailConfigFile(os.path.join(state, "guardian-mail.json")),
        mcp=McpSetup(vault, home, environ),
        scheduler=SchedulerSetup(vault, home, state, environ=environ),
        routines=RoutinePool(vault, environ),
        clock=SystemClock(),
        home=home,
        platform=sys.platform,
    )
