"""Mailer adapters: how guardian alerts and routine reports leave the machine.

Two transports, chosen at first run and kept in <brain state>/guardian-mail.json (machine-local,
never committed: it names addresses):

  gmail-api   a Google account connected with google.py; `account` names it. The message goes
              through the Gmail API with that account's refresh token, which must carry the
              gmail.send scope.
  smtp        any SMTP server (`smtp.host`, `port`, `user`, `security` starttls|ssl|none). The
              password is read from the KeePass database by reference (`smtp.kp_ref`), headless.

The mailer only sends or raises `MailUnavailable`. Queueing and retrying is the outbox's job
(mail_queue.py), so another transport is one more class with a `send` method and a new
`adapter` value in the config.
"""

from __future__ import annotations

import base64
import json
import os
import smtplib
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

from .adapters import read_json
from .ports import MailUnavailable

# mail_body lives one level up, in _bin/, shared by every account and transport.
BIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
ADAPTERS = ("gmail-api", "smtp")

DEFAULT_CONFIG = {"enabled": False, "adapter": "gmail-api", "account": "", "from": "", "to": "", "timeout": 20,
                  "smtp": {}}


def _message(sender, to, subject, body, html=False):
    """A bare text/plain part is re-wrapped by the reading client at its own fixed width, which
    turns a paragraph into a narrow column, so every message carries an HTML part
    (mail_body.build_message). With html=True the body already is markup and goes through as is."""
    if BIN not in sys.path:
        sys.path.insert(0, BIN)
    from mail_body import build_message

    return build_message(to, subject, body, sender=sender, html=body if html else None)


class GmailApiMailer:
    def __init__(self, sender, token_provider, urlopen=urllib.request.urlopen, timeout=20):
        self.sender, self.token_provider = sender, token_provider
        self.urlopen, self.timeout = urlopen, timeout

    def send(self, to: str, subject: str, body: str, html: bool = False) -> None:
        try:
            token = self.token_provider()
        except Exception as exc:
            raise MailUnavailable("no Gmail token: %s" % exc)
        raw = base64.urlsafe_b64encode(_message(self.sender, to, subject, body, html).as_bytes()).decode("ascii")
        req = urllib.request.Request(
            GMAIL_SEND_URL, data=json.dumps({"raw": raw}).encode("utf-8"), method="POST",
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        try:
            resp = self.urlopen(req, timeout=self.timeout)
            resp.read()
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", "replace")[:200]
            except Exception:
                detail = ""
            raise MailUnavailable("gmail send refused (%d): %s" % (exc.code, detail))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise MailUnavailable("gmail send failed: %s: %s" % (type(exc).__name__, exc))


class SmtpMailer:
    def __init__(self, sender, host, port=587, user="", password_provider=None, security="starttls", timeout=20,
                 smtp_factory=None, ssl_factory=None):
        self.sender, self.host, self.port, self.user = sender, host, int(port), user
        self.password_provider, self.security, self.timeout = password_provider, security, timeout
        self.smtp_factory, self.ssl_factory = smtp_factory, ssl_factory

    def send(self, to: str, subject: str, body: str, html: bool = False) -> None:
        try:
            password = self.password_provider() if (self.user and self.password_provider) else ""
        except Exception as exc:
            raise MailUnavailable("no SMTP password: %s" % exc)
        msg = _message(self.sender, to, subject, body, html)
        try:
            if self.security == "ssl":
                server = (self.ssl_factory or smtplib.SMTP_SSL)(self.host, self.port, timeout=self.timeout)
            else:
                server = (self.smtp_factory or smtplib.SMTP)(self.host, self.port, timeout=self.timeout)
            try:
                if self.security == "starttls":
                    server.starttls(context=ssl.create_default_context())
                if self.user:
                    server.login(self.user, password)
                server.send_message(msg)
            finally:
                try:
                    server.quit()
                except Exception:
                    pass
        except (smtplib.SMTPException, OSError, ValueError) as exc:
            raise MailUnavailable("smtp send failed: %s: %s" % (type(exc).__name__, exc))


def google_token_provider(account, timeout=20):
    """An access token for the google.py account `account`, carrying gmail.send. Never prompts."""

    def provide():
        try:
            from google_core import headless
        except ImportError as exc:
            raise MailUnavailable("google.py is not available: %s" % exc)
        try:
            return headless.access_token(account, required_scope=GMAIL_SEND_SCOPE, timeout=timeout)
        except Exception as exc:
            raise MailUnavailable(str(exc))

    return provide


def kp_password_provider(kp_ref, timeout=20, run=subprocess.run, kp_path=None):
    """The value stored at `kp_ref` (kp://Group/Entry#Attribute), read with kp.py headless."""

    def provide():
        ref = kp_ref[len("kp://"):] if kp_ref.startswith("kp://") else kp_ref
        entry, _, attr = ref.partition("#")
        kp = kp_path or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kp.py")
        env = dict(os.environ, BRAIN_KP_NOPROMPT="1")
        try:
            p = run([sys.executable, kp, "get", entry, "-a", attr or "Password", "--pipe", "cat"], env=env,
                    stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MailUnavailable("KeePass did not answer: %s" % type(exc).__name__)
        value = (p.stdout or "").rstrip("\n")
        if p.returncode != 0 or not value:
            raise MailUnavailable("%s unreadable (kp.py exit %d)" % (kp_ref, p.returncode))
        return value

    return provide


def mail_config_path(state_dir, vault=None) -> str:
    """<brain state>/guardian-mail.json. A vault-local 90-Meta/guardian-mail.json (ignored by git) is
    read only while the state one does not exist."""
    path = os.path.join(state_dir, "guardian-mail.json")
    if os.path.exists(path) or not vault:
        return path
    legacy = os.path.join(vault, "90-Meta", "guardian-mail.json")
    return legacy if os.path.exists(legacy) else path


def load_mail_config(path: str) -> dict:
    """The mail config over the defaults. Missing or corrupt means disabled."""
    cfg = dict(DEFAULT_CONFIG)
    data = read_json(path, {})
    cfg.update(data if isinstance(data, dict) else {})
    if not data:
        cfg["enabled"] = False
    return cfg


def build_mailer(config: dict, token_provider=None, password_provider=None):
    """The configured mailer, or None (disabled) when the config does not name a usable one."""
    if not config.get("enabled") or config.get("adapter") not in ADAPTERS:
        return None
    if not config.get("from") or not config.get("to"):
        return None
    timeout = int(config.get("timeout") or 20)
    if config["adapter"] == "gmail-api":
        account = str(config.get("account") or "").strip()
        if not account and token_provider is None:
            return None
        return GmailApiMailer(config["from"], token_provider or google_token_provider(account, timeout),
                              timeout=timeout)
    smtp = config.get("smtp") if isinstance(config.get("smtp"), dict) else {}
    if not smtp.get("host"):
        return None
    if smtp.get("user") and not smtp.get("kp_ref") and password_provider is None:
        return None
    provider = password_provider or (kp_password_provider(smtp["kp_ref"], timeout) if smtp.get("kp_ref") else None)
    return SmtpMailer(config["from"], smtp["host"], int(smtp.get("port") or 587), smtp.get("user") or "", provider,
                      smtp.get("security") or "starttls", timeout)
