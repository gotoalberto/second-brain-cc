"""google.py's adapters: KeePass through kp.py, urllib, JSON files, a loopback HTTP server, Gmail.

Each class implements one port from ports.py. Everything that touches the machine is here.
"""

from __future__ import annotations

import datetime as dt
import http.server
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from . import domain as D
from .ports import HttpError

BIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- paths


def _state_dir(environ=None) -> str:
    if BIN not in sys.path:
        sys.path.insert(0, BIN)
    import brain_paths

    return brain_paths.state_dir(os.environ if environ is None else environ)


def accounts_path(environ=None) -> str:
    return os.path.join(_state_dir(environ), "google-accounts.json")


def sent_log_path(environ=None) -> str:
    """BRAIN_MAIL_SENT_LOG when set (the routine runner sets it), else <brain state>/logs/mail-sent.jsonl."""
    environ = os.environ if environ is None else environ
    explicit = (environ.get("BRAIN_MAIL_SENT_LOG") or "").strip()
    if explicit:
        return os.path.expanduser(explicit)
    return os.path.join(_state_dir(environ), "logs", "mail-sent.jsonl")


def kp_path(environ=None) -> str:
    environ = os.environ if environ is None else environ
    return environ.get("BRAIN_GOOGLE_KP") or os.path.join(BIN, "kp.py")


# ---------------------------------------------------------------- KeePass


class KpSecretStore:
    """Secrets through kp.py. Values travel on stdin or a pipe, never in argv.

    headless=True sets BRAIN_KP_NOPROMPT: no dialog, bounded by the timeout, Unavailable when the
    master is not cached. Interactive use (add, auth) may prompt for the master."""

    def __init__(self, kp, headless=True, run=subprocess.run):
        self.kp, self.headless, self.run = kp, headless, run

    def _env(self):
        env = dict(os.environ)
        if self.headless:
            env["BRAIN_KP_NOPROMPT"] = "1"
        return env

    def read(self, entry, attr="Password", timeout=20):
        cmd = [sys.executable, self.kp, "get", entry, "-a", attr, "--pipe", "cat"]
        try:
            p = self.run(cmd, env=self._env(), capture_output=True, text=True, timeout=timeout,
                         stdin=subprocess.DEVNULL if self.headless else None)
        except subprocess.TimeoutExpired:
            raise D.Unavailable("kp://%s#%s: KeePass did not answer within %ds" % (entry, attr, timeout))
        except OSError as exc:
            raise D.Unavailable("kp://%s#%s: %s" % (entry, attr, type(exc).__name__))
        value = (p.stdout or "").rstrip("\n")
        if p.returncode != 0 or not value:
            why = (p.stderr or "").strip().splitlines()
            raise D.Unavailable("kp://%s#%s unreadable (kp.py exit %d)%s"
                                % (entry, attr, p.returncode, (": " + why[-1][:160]) if why else ""))
        return value

    def write(self, entry, value, username=None, notes=None):
        """`put` first, `set` only when put refuses: `set` on a name that does not exist resolves by
        similarity and could overwrite another entry, while `put` fails cleanly on an existing one."""
        extra = (["-u", username] if username else [])
        put = [sys.executable, self.kp, "put", entry, "--stdin"] + extra + (["--notes", notes] if notes else [])
        p = self.run(put, input=value, env=self._env(), capture_output=True, text=True, timeout=120)
        if p.returncode != 0:
            p = self.run([sys.executable, self.kp, "set", entry, "--stdin"] + extra, input=value, env=self._env(),
                         capture_output=True, text=True, timeout=120)
        if p.returncode != 0:
            raise D.GoogleError("could not store kp://%s (kp.py exit %d): %s"
                                % (entry, p.returncode, (p.stderr or "").strip()[:200]))


# ---------------------------------------------------------------- HTTP


class UrllibHttp:
    def __init__(self, urlopen=urllib.request.urlopen):
        self.urlopen = urlopen

    def _open(self, req, timeout):
        try:
            resp = self.urlopen(req, timeout=timeout)
            return getattr(resp, "status", 200), resp.read()
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8", "replace")
            except Exception:
                body = ""
            raise HttpError(exc.code, body)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise D.Unavailable("network: %s: %s" % (type(exc).__name__, exc))

    def post_form(self, url, fields, timeout=20):
        req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        _, raw = self._open(req, timeout)
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise D.Unavailable("the token endpoint answered with something that is not JSON")

    def request(self, method, url, token, body=None, timeout=30):
        headers = {"Authorization": "Bearer " + token}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        status, raw = self._open(urllib.request.Request(url, data=data, headers=headers, method=method), timeout)
        if not raw.strip():
            return {"_status": status}
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return {"_status": status, "_text": raw.decode("utf-8", "replace")[:2000]}


# ---------------------------------------------------------------- files


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


class JsonAccountStore:
    def __init__(self, path):
        self.path = path

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                return D.parse_registry(fh.read())
        except FileNotFoundError:
            return {}

    def save(self, accounts):
        _private_write(self.path, D.render_registry(accounts))


class JsonlSendLog:
    def __init__(self, path):
        self.path = path

    def append(self, record):
        """One JSON line in a single write, to a 0600 file (its directory made 0700 if new)."""
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, mode=0o700, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            os.close(fd)


class SystemClock:
    def now(self):
        return dt.datetime.now().astimezone()


# ---------------------------------------------------------------- consent


class LoopbackReceiver:
    """Waits on 127.0.0.1:<port> for the browser to come back from Google's consent page."""

    def __init__(self, host="127.0.0.1"):
        self.host = host

    def free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((self.host, 0))
            return s.getsockname()[1]

    def wait(self, port, url, state, timeout):
        box = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                params = {k: v[0] for k, v in query.items()}
                if "code" in params or "error" in params:
                    box.update(params)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<p>Done. You can close this tab and go back to the terminal.</p>")

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer((self.host, port), Handler)
        server.timeout = 0.5
        deadline = time.monotonic() + timeout
        try:
            while not box and time.monotonic() < deadline:
                server.handle_request()
        finally:
            server.server_close()
        if not box:
            raise D.GoogleError("nobody came back from the consent page within %ds" % timeout)
        return box


# ---------------------------------------------------------------- Gmail


class GmailSender:
    """Sends through the guardian's GmailApiMailer, so Brain has one Gmail send path, and returns
    Gmail's message id for the send log."""

    def __init__(self, sender, token_provider, urlopen=None, timeout=20):
        self.sender, self.token_provider = sender, token_provider
        self.urlopen, self.timeout = urlopen or urllib.request.urlopen, timeout

    def send(self, to, subject, body, html=False):
        if BIN not in sys.path:
            sys.path.insert(0, BIN)
        from guardian_core import mailer as ML

        replies = []

        class _Reply:
            def __init__(self, data):
                self.data = data

            def read(self, *a):
                return self.data

        def capturing(req, timeout=None):
            data = self.urlopen(req, timeout=timeout).read()
            replies.append(data)
            return _Reply(data)

        ML.GmailApiMailer(self.sender, self.token_provider, urlopen=capturing, timeout=self.timeout).send(
            to, subject, body, html=html)
        try:
            data = json.loads(replies[-1].decode("utf-8", "replace"))
            return str(data.get("id") or "") if isinstance(data, dict) else ""
        except (IndexError, ValueError, AttributeError):
            return ""


# ---------------------------------------------------------------- wiring


def build_ports(environ=None, headless=False, open_browser=True):
    from .application import Ports

    environ = os.environ if environ is None else environ
    opener = None
    if open_browser:
        import webbrowser

        opener = webbrowser.open
    return Ports(secrets=KpSecretStore(kp_path(environ), headless=headless), http=UrllibHttp(),
                 accounts=JsonAccountStore(accounts_path(environ)), receiver=LoopbackReceiver(),
                 send_log=JsonlSendLog(sent_log_path(environ)), clock=SystemClock(), open_url=opener)
