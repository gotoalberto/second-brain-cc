#!/usr/bin/env python3
"""Mails the owner the moment Google refuses a google.py account's token.

A refresh token can die at any time: revoked, the password changed, the OAuth client's secret
rotated, a scope it needs taken away. Everything that reads or sends through that account then
fails, routine after routine, each with its own alert in its own log. So the alert lives at the
one place every consumer goes through to get a token, google_core.application.access_token, and
fires only when Google REFUSES the token (an HTTP 400/401/403 from the token endpoint, or a token
that lacks a scope its caller needs). A network blip or a server error is not an alert: only a
refusal needs a person.

The mail never travels through the token that just died. It goes to the guardian's address
(<brain state>/guardian-mail.json, `to`) through the first sender that works among: the
guardian's own transport (SMTP, or a google.py account other than the dead one), then every other
google.py account on this machine that can send. At most one mail per token per day, kept in
<brain state>/token-alert.json, so a morning of routines failing on one token sends one mail.

`alert()` never raises: a failed alert must not change how its caller fails. While it sends it
sets BRAIN_TOKEN_ALERT_OFF, so a sender whose own token is refused does not start a second
alert from inside the first.

google_token_watch.py is a different check and stays: it warns BEFORE a Testing-mode token's
7 day expiry, while this one reports a refusal after it happened.

Usage (by hand, for testing):
  token_alert.py <account> "detail"            send the alert now, ignoring the daily mark
  token_alert.py <account> "detail" --dry-run  print it, send nothing
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

OFF_ENV = "BRAIN_TOKEN_ALERT_OFF"
STATE_NAME = "token-alert.json"


def _state_dir(environ):
    import brain_paths

    return brain_paths.state_dir(environ)


def state_path(environ=None):
    return os.path.join(_state_dir(os.environ if environ is None else environ), STATE_NAME)


def _load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def compose(account, detail, caller):
    """(subject, html): one phone screen, the command that fixes it first."""
    subject = "Google token of account %s refused: re-authorise it" % account
    command = "python3 ~/Brain/_bin/google.py auth --account %s" % account
    body = """<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px;line-height:1.5;max-width:640px">
<p>Google refused the token of the google.py account <strong>%s</strong>. <code>%s</code> noticed it, and
everything that reads or sends through that account will fail until it is authorised again.</p>
<p style="margin:18px 0 6px;font-weight:600">On a machine with a browser, run:</p>
<pre style="background:#f4f4f5;border-left:3px solid #6b7280;padding:12px 14px;white-space:pre-wrap;font-size:14px">%s</pre>
<p style="color:#555;font-size:13px">Google said: %s</p>
<p style="color:#555;font-size:13px">At most one alert a day per account.</p>
</div>""" % (html.escape(account), html.escape(caller), html.escape(command), html.escape(detail[:400]))
    return subject, body


def route(dead, environ):
    """(to, [(label, mailer)]) for an alert about account `dead`, or None when no address is configured.

    Never a sender that goes through `dead`'s own token."""
    from google_core import adapters as GAD
    from google_core import domain as GD
    from guardian_core import mailer as ML

    cfg = ML.load_mail_config(ML.mail_config_path(_state_dir(environ)))
    to = str(cfg.get("to") or "").strip()
    if not to:
        return None
    senders, used = [], {dead}
    if cfg.get("enabled"):
        through = str(cfg.get("account") or "").strip() if cfg.get("adapter") == "gmail-api" else ""
        if through != dead:
            mailer = ML.build_mailer(cfg)
            if mailer is not None:
                senders.append(("guardian", mailer))
                if through:
                    used.add(through)
    try:
        accounts = GAD.JsonAccountStore(GAD.accounts_path(environ)).load()
    except Exception:
        accounts = {}
    for name, acc in sorted(accounts.items()):
        if name in used or GD.GMAIL_SEND_SCOPE not in acc.scopes or not acc.login_hint:
            continue
        senders.append(("google:" + name, ML.GmailApiMailer(acc.login_hint, ML.google_token_provider(name))))
    return to, senders


def alert(account, detail, caller=None, environ=None, now=None, route=route, force=False):
    """Mail the alert once per token per day. Returns what happened; never raises."""
    try:
        environ = os.environ if environ is None else environ
        if environ.get(OFF_ENV) and not force:
            return "off"
        caller = caller or os.path.basename(sys.argv[0] or "?")
        today = (now or dt.datetime.now().astimezone()).date().isoformat()
        path = state_path(environ)
        state = _load(path)
        key = "google:%s" % account
        if (state.get(key) or {}).get("last_sent_day") == today and not force:
            return "already-sent-today"
        where = route(account, environ)
        if not where:
            sys.stderr.write("[token-alert] no address to alert (guardian-mail.json has no `to`)\n")
            return "no-route"
        to, senders = where
        subject, body = compose(account, " ".join(str(detail).split()), caller)
        errors = []
        saved = os.environ.get(OFF_ENV)
        os.environ[OFF_ENV] = "1"
        try:
            for label, mailer in senders:
                try:
                    mailer.send(to, subject, body, html=True)
                except Exception as exc:
                    errors.append("%s: %s" % (label, " ".join(str(exc).split())[:160]))
                    continue
                state[key] = {"last_sent_day": today, "via": label, "caller": caller, "detail": str(detail)[:300]}
                _save(path, state)
                return "sent:" + label
        finally:
            if saved is None:
                os.environ.pop(OFF_ENV, None)
            else:
                os.environ[OFF_ENV] = saved
        sys.stderr.write("[token-alert] could not mail the alert for %s: %s\n"
                         % (account, " | ".join(errors) or "no sender other than the refused account"))
        return "failed"
    except Exception as exc:  # an alert must never change how its caller fails
        try:
            sys.stderr.write("[token-alert] %s: %s\n" % (type(exc).__name__, exc))
        except Exception:
            pass
        return "error"


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    if "--dry-run" in argv:
        subject, body = compose(argv[0], argv[1], "token_alert.py")
        print(subject + "\n\n" + body)
        return 0
    res = alert(argv[0], argv[1], caller="token_alert.py (by hand)", force=True)
    print(res)
    return 0 if res.startswith("sent") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
