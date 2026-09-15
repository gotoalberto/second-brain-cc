"""routine_auth_core's adapters: every place it touches the machine.

Each class implements one port from ports.py. Anything external (kp.py, subprocess, the
clock) is injectable so the tests put a fake in its place; the defaults are the real thing.
Nothing here decides anything: what a failure means and what to try next is domain.py.
"""

from __future__ import annotations

import datetime as dt
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

from guardian_core.adapters import JsonStateStore, atomic_write  # noqa: F401  (same atomic-write state file)

from . import domain as D
from .ports import TokenUnavailable  # noqa: F401  (re-exported for callers)

KP_EXIT_NOMASTER = 4        # kp.py: the master password is not available (headless, BRAIN_KP_NOPROMPT)


# ---------------------------------------------------------------- KeePass


class KpTokenSource:
    """Reads a routine token from the kdbx through kp.py, headless.

    The same quiet-read shape as google.kp_read_quiet: BRAIN_KP_NOPROMPT=1 so no
    dialog ever waits for a person, a bounded timeout, and the value handed by kp.py's
    `--pipe` to a one-line reader that writes it to a 0600 temporary file, so it never
    passes through argv or stdout. Two differences, both needed here: kp.py's own exit code
    separates "KeePass is locked" from "the entry cannot be read", and the value comes back
    as stored (only the newline the pipe adds is removed), so a pasted space or newline
    reaches domain.token_shape instead of being silently stripped.
    """

    def __init__(self, kp_path, python=None, run=subprocess.run, environ=None, tmp_dir=None):
        self.kp_path = kp_path
        self.python = python or sys.executable
        self.run = run
        self.environ = os.environ if environ is None else environ
        self.tmp_dir = tmp_dir

    def read(self, kp_ref: str, timeout: int) -> str:
        where = (kp_ref or "").split("#", 1)[0]
        if not os.path.isfile(self.kp_path):
            raise TokenUnavailable(D.KEEPASS_UNAVAILABLE, "%s: kp.py not found at %s" % (where, self.kp_path))
        fd, path = tempfile.mkstemp(prefix="kp-", dir=self.tmp_dir)
        os.close(fd)
        os.chmod(path, 0o600)
        reader = "import sys,os;open(os.environ['KPOUT'],'wb').write(sys.stdin.buffer.read())"
        env = dict(self.environ, KPOUT=path, BRAIN_KP_NOPROMPT="1")
        argv = [self.python, self.kp_path, "get", D.kp_entry(kp_ref), "-a", D.kp_attr(kp_ref),
                "--pipe", '%s -c "%s"' % (self.python, reader)]
        try:
            try:
                p = self.run(argv, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                             timeout=timeout)
            except subprocess.TimeoutExpired:
                raise TokenUnavailable(D.KEEPASS_UNAVAILABLE,
                                       "%s: KeePass did not answer within %ss" % (where, timeout))
            except OSError as exc:
                raise TokenUnavailable(D.KEEPASS_UNAVAILABLE, "%s: %s: %s" % (where, type(exc).__name__, exc))
            with open(path, encoding="utf-8", errors="replace") as fh:
                value = fh.read()
        finally:
            if os.path.exists(path):
                os.remove(path)
        if p.returncode != 0:
            why = [l for l in (p.stderr or "").strip().splitlines() if l.strip()]
            reason = D.redact(why[-1].strip(), limit=160) if why else "exit %d" % p.returncode
            if p.returncode == KP_EXIT_NOMASTER:
                raise TokenUnavailable(D.KEEPASS_LOCKED,
                                       "%s: KeePass is locked for headless reads (%s). This is a KeePass "
                                       "problem, not a token problem: open any kp.py get at a terminal to "
                                       "unlock it" % (where, reason))
            raise TokenUnavailable(D.KEEPASS_UNAVAILABLE, "%s unreadable (kp.py exit %d): %s"
                                   % (where, p.returncode, reason))
        return value[:-1] if value.endswith("\n") else value


# ---------------------------------------------------------------- files


class PoolFile:
    """90-Meta/routine-tokens.json, validated by domain.parse_pool."""

    def __init__(self, path):
        self.path = path

    def entries(self) -> list:
        try:
            with open(self.path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            raise D.PoolConfigError("%s missing or unreadable: %s" % (self.path, type(exc).__name__))
        return D.parse_pool(text)


class CliResolver:
    """Is the CLI the template names the standalone one, and does it run?

    Resolves the template's first token (`~` expanded, a bare name looked up on PATH),
    refuses the Claude Desktop app's own copy wherever a symlink leads, refuses --bare, and
    runs `<cli> --version` with a short timeout in an environment built from scratch: no
    Anthropic credential of the parent reaches it. Checked once per process.
    """

    def __init__(self, template, home=None, which=shutil.which, run=subprocess.run, env_path=None, timeout=15):
        self.template = template
        self.home = home or os.path.expanduser("~")
        self.which, self.run, self.timeout = which, run, timeout
        self.env_path = env_path
        self._status = None

    def _resolve(self, tok):
        if "/" in tok:
            return tok if os.path.isfile(tok) and os.access(tok, os.X_OK) else None
        path = self.env_path or os.environ.get("PATH") or os.defpath
        return self.which(tok, path=path)

    def check(self):
        if self._status is None:
            self._status = self._check()
        return self._status

    def _check(self):
        tokens = D.template_tokens(self.template, self.home)
        if not tokens:
            return D.CliStatus(False, detail="no agent command configured (90-Meta/agent-command.txt or BRAIN_AGENT_CMD)")
        problem = D.forbidden_arg_problem(tokens) or D.permission_problem(tokens)
        if problem:
            return D.CliStatus(False, detail=problem)
        resolved = self._resolve(tokens[0])
        if not resolved:
            return D.CliStatus(False, detail="agent command not found: %s" % tokens[0])
        real = os.path.realpath(resolved)
        problem = (D.cli_path_problem(resolved, real, self.home)
                   or D.cli_path_problem(resolved, real, os.path.realpath(self.home)))
        if problem:
            return D.CliStatus(False, resolved, detail=problem)
        env = {"HOME": self.home, "PATH": os.environ.get("PATH") or os.defpath, "DISABLE_AUTOUPDATER": "1"}
        try:
            p = self.run([resolved, "--version"], env=env, stdin=subprocess.DEVNULL, capture_output=True,
                         text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return D.CliStatus(False, resolved, detail="`%s --version` did not answer within %ss" % (resolved, self.timeout))
        except OSError as exc:
            return D.CliStatus(False, resolved, detail="`%s --version`: %s: %s" % (resolved, type(exc).__name__, exc))
        if p.returncode != 0:
            last = [l for l in (p.stderr or p.stdout or "").strip().splitlines() if l.strip()]
            return D.CliStatus(False, resolved, detail="`%s --version` exited %d%s"
                               % (resolved, p.returncode, (": " + D.redact(last[-1], limit=160)) if last else ""))
        version = ((p.stdout or "").strip().splitlines() or [""])[0]
        return D.CliStatus(True, resolved, version)


class CliAttempt:
    """One routine attempt: the template, then the routine's agent_args, in the given env.

    Wraps guardian_core.adapters.CliAgentRunner rather than re-implementing it: `{prompt}`
    and `{prompt_file}` substitution, the process group killed on timeout and the 124/126/127
    exit codes stay exactly what they are for every other agent run. `~` is expanded in the
    template and in agent_args, so the vault's config can say `~/.local/bin/claude`.

    The prompt arrives as text (domain.frame_prompt's output). CliAgentRunner reads a file, so
    the text goes to a 0600 temporary file for the length of the run: `{prompt_file}` is that
    file, and it is removed when the run ends, however it ends.
    """

    def __init__(self, template, cwd=None, home=None, tmp_dir=None):
        self.template, self.cwd = template, cwd
        self.home = home or os.path.expanduser("~")
        self.tmp_dir = tmp_dir

    def run(self, prompt, agent_args, env, timeout):
        from guardian_core.adapters import CliAgentRunner

        tokens = D.template_tokens(self.template, self.home) + D.expand_home(list(agent_args or ()), self.home)
        template = " ".join(shlex.quote(t) for t in tokens)
        fd, path = tempfile.mkstemp(prefix="routine-prompt-", suffix=".md", dir=self.tmp_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(prompt or "")
            os.chmod(path, 0o600)
            return CliAgentRunner(template, cwd=self.cwd, env=dict(env)).run(path, timeout)
        finally:
            if os.path.exists(path):
                os.remove(path)


class ScratchDirs:
    """<brain state>/routine-scratch/<run id>/: one private directory per attempt.

    Inside the Brain state directory, so the runner can grant it with `--add-dir` instead of
    the run reaching for /tmp (outside the allowed directories) or writing temporary files into
    the vault. 0700, the root too. `remove` deletes only a direct child of the root; `prune`
    deletes the run directories domain.scratch_to_prune names, and never a plain file.
    """

    def __init__(self, root, keep_days=D.SCRATCH_KEEP_DAYS):
        self.root, self.keep_days = root, keep_days

    def create(self, run_id):
        os.makedirs(self.root, mode=0o700, exist_ok=True)
        os.chmod(self.root, 0o700)
        path = os.path.join(self.root, run_id)
        if not self._inside(path):
            raise ValueError("a run id must be one directory name")
        os.mkdir(path, 0o700)
        os.chmod(path, 0o700)
        return path

    def _inside(self, path):
        root = os.path.realpath(self.root)
        real = os.path.realpath(path)
        return real != root and os.path.dirname(real) == root

    def remove(self, path):
        if not path or os.path.islink(path) or not self._inside(path) or not os.path.isdir(path):
            return False
        shutil.rmtree(path, ignore_errors=True)
        return not os.path.exists(path)

    def prune(self, now):
        try:
            names = sorted(os.listdir(self.root))
        except OSError:
            return []
        entries = []
        for name in names:
            path = os.path.join(self.root, name)
            if os.path.islink(path) or not os.path.isdir(path):
                continue
            try:
                entries.append((name, dt.datetime.fromtimestamp(os.stat(path).st_mtime)))
            except OSError:
                continue
        return [name for name in D.scratch_to_prune(entries, now, self.keep_days)
                if self.remove(os.path.join(self.root, name))]


class RandomRunIds:
    """Run ids with 8 random hex characters, so two attempts in the same second never collide."""

    def __init__(self, token_hex=None):
        import secrets

        self.token_hex = token_hex or secrets.token_hex

    def new(self, routine_id, now):
        return D.run_id(routine_id, now, self.token_hex(4))


class MailSentLog:
    """<brain state>/logs/mail-sent.jsonl, which google.py send appends to on every
    delivered message. Read only; a missing or unreadable log is no sends."""

    def __init__(self, path):
        self.path = path

    def records(self):
        try:
            with open(self.path, encoding="utf-8", errors="replace") as fh:
                return D.parse_send_log(fh.read())
        except OSError:
            return []


class SystemClock:
    def now(self) -> dt.datetime:
        return dt.datetime.now()

    def monotonic(self) -> float:
        return time.monotonic()


class RawOutputLog:
    """<brain state>/logs/routine-auth.log: every failed attempt's raw output, redacted.

    Kept so the unverified patterns can be calibrated from real failures without
    reproducing them. Redacted with domain.redact plus the token that was used; bounded
    per stream; rotated like every Brain log.
    """

    def __init__(self, path, clock=None, max_bytes=1_000_000, keep=3, stream_limit=4000):
        self.path = path
        self.clock = clock or (lambda: dt.datetime.now())
        self.max_bytes, self.keep, self.stream_limit = max_bytes, keep, stream_limit

    def _rotate(self):
        try:
            if os.path.getsize(self.path) < self.max_bytes:
                return
        except OSError:
            return
        base = self.path[:-len(".log")] if self.path.endswith(".log") else self.path
        for i in range(self.keep - 1, 0, -1):
            older = "%s.%d.log" % (base, i)
            newer = self.path if i == 1 else "%s.%d.log" % (base, i - 1)
            if os.path.exists(newer):
                if os.path.exists(older):
                    os.remove(older)
                os.rename(newer, older)

    def record(self, routine_id, label, cls, rc, stdout, stderr, secrets=(), run_id=None) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._rotate()
        stamp = self.clock().strftime("%Y-%m-%d %H:%M:%S")
        # The run id is not redacted: it names the kept scratch directory, and it is no secret.
        lines = ["[%s] routine=%s%s token=%s kind=%s (%s) exit=%s detail=%s"
                 % (stamp, routine_id, " run=%s" % run_id if run_id else "", label, cls.kind,
                    "verified" if cls.verified else "unverified pattern",
                    rc, D.redact(cls.detail, secrets=secrets, limit=200))]
        for name, stream in (("out", stdout), ("err", stderr)):
            for line in D.redact(stream, secrets=secrets, limit=self.stream_limit).splitlines():
                lines.append("  %s| %s" % (name, line))
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
