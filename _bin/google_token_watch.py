#!/usr/bin/env python3
"""Warns BEFORE a Google refresh token expires, instead of after it has.

Why this exists. A Google Cloud OAuth consent screen left in **Testing** publishing status gets
refresh tokens that Google expires 7 days after the consent that minted them, however much they
are used. Everything that reads or sends mail through that account stops on the same day, with
no warning. Worse, when the alert channel is that same Gmail account, the alert that the mail
died dies with it. So the warning has to go out while the token still works.

google.py stamps the instant of every consent in its account registry (`authorized_at`). This
script counts the days left from that stamp, probes the token for real (a revoke or a password
change that beat the clock is caught on the next run, not at the next routine), and mails the
warning a few days before the deadline, at most once a day per account.

  google_token_watch.py [--account NAME ...] [--days 7] [--warn-within 3]
                        [--to ADDRESS] [--via ACCOUNT] [--dry-run] [--force]

  --account      the accounts to watch (repeatable); default: every account with a consent stamp.
                 Watch only accounts whose OAuth app is in Testing status: a published app's
                 tokens do not expire on this clock and would only give false warnings.
  --to           where the warning goes. Without it the report is printed and nothing is sent.
  --via          the google.py account that sends it. Default: a watched account that is still
                 alive and not the one in trouble, else the account itself. Give it an account
                 that does not share the watched one's fate whenever you have one.
  --dry-run      print the message, send nothing.  --force  send even when nothing is due.

Exit status: 0 whenever the check ran, whatever the tokens' state (a warning is the product, not
a failure); 1 when a warning was due and could not be sent; 2 on a usage error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# Google's documented lifetime for a refresh token issued by an app in Testing status.
TESTING_LIFETIME_DAYS = 7
# How early the warning goes out. Three days, so a day lost to a machine being off or a failed
# run still leaves time: a warning that arrives after the expiry is worthless.
WARN_WITHIN_DAYS = 3
STATE_NAME = "google-token-watch.json"


# ---------------------------------------------------------------- pure logic


def parse_instant(text):
    """An aware datetime from an ISO string, or None."""
    try:
        when = dt.datetime.fromisoformat((text or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def assess(account, authorized_at, alive, detail, now, lifetime_days=TESTING_LIFETIME_DAYS):
    """One account's footing: alive or not, when its token expires, how many days are left."""
    granted = parse_instant(authorized_at)
    expires = granted + dt.timedelta(days=lifetime_days) if granted else None
    left = round((expires - now).total_seconds() / 86400, 2) if expires else None
    return {"account": account, "alive": bool(alive), "detail": detail, "granted": granted,
            "expires": expires, "days_left": left}


def due(status, last_sent_day, today, warn_within=WARN_WITHIN_DAYS):
    """"dead", "expiring" or None: is a warning owed for this account today? At most one a day."""
    if last_sent_day == today:
        return None
    if not status["alive"]:
        return "dead"
    if status["days_left"] is not None and status["days_left"] <= warn_within:
        return "expiring"
    return None


def pick_sender(statuses, reasons, via=None):
    """The account that sends the warning: `via` when given, else an alive account that needs no
    warning itself, else the first account in trouble that is still alive, else None."""
    if via:
        return via
    calm = [s["account"] for s in statuses if s["alive"] and s["account"] not in reasons]
    if calm:
        return calm[0]
    alive = [s["account"] for s in statuses if s["alive"]]
    return alive[0] if alive else None


def _when(value):
    return value.strftime("%a %Y-%m-%d %H:%M %Z").strip() if value else "unknown"


def summary_line(status):
    left = "unknown" if status["days_left"] is None else "%.2f" % status["days_left"]
    return "%s: token %s (%s); consent %s; expires %s; days left %s" % (
        status["account"], "alive" if status["alive"] else "NOT working", status["detail"],
        _when(status["granted"]), _when(status["expires"]), left)


def compose(statuses, reasons, lifetime_days=TESTING_LIFETIME_DAYS):
    """(subject, html body) for the accounts in `reasons` ({account: "dead"|"expiring"}). Pure.
    One screen, the command to run first: it is read on a phone."""
    trouble = [s for s in statuses if s["account"] in reasons]
    dead = [s["account"] for s in trouble if reasons[s["account"]] == "dead"]
    if dead:
        subject = "Google token no longer works: %s" % ", ".join(dead)
    else:
        soonest = min([s["days_left"] for s in trouble if s["days_left"] is not None] or [0])
        subject = "Google token expires in %s: %s" % (
            "less than a day" if soonest < 1 else "%.0f days" % soonest, ", ".join(s["account"] for s in trouble))
    items = []
    for s in trouble:
        name = html.escape(s["account"])
        if reasons[s["account"]] == "dead":
            items.append("<li><strong>%s</strong> no longer works: %s</li>" % (name, html.escape(s["detail"])))
        elif s["days_left"] is None:
            items.append("<li><strong>%s</strong> has no consent stamp, so its expiry is unknown.</li>" % name)
        else:
            items.append("<li><strong>%s</strong> expires %s, in about %d hours. It still works: renewing it "
                         "now keeps everything running.</li>"
                         % (name, html.escape(_when(s["expires"])), int(round(s["days_left"] * 24))))
    commands = "\n".join("python3 ~/Brain/_bin/google.py auth --account %s" % s["account"] for s in trouble)
    body = """<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px;line-height:1.5;color:#1a1a1a;max-width:640px">
<ul>%s</ul>
<p style="margin:18px 0 6px;font-weight:600">Renew the consent on a machine with a browser:</p>
<pre style="background:#f4f4f5;border-left:3px solid #6b7280;padding:12px 14px;white-space:pre-wrap;font-size:14px;border-radius:4px">%s</pre>
<p style="color:#555;font-size:13px">The OAuth app is in Testing publishing status, so Google expires each
refresh token %d days after the consent. Publishing the app to production ends this for good; it needs
a home page and a privacy policy URL.</p>
</div>""" % ("".join(items), html.escape(commands), lifetime_days)
    return subject, body


# ---------------------------------------------------------------- adapters


def state_path(environ=None):
    import brain_paths
    return os.path.join(brain_paths.effective_state_dir(environ), STATE_NAME)


def load_state(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except OSError as exc:
        sys.stderr.write("google_token_watch: could not save the state: %s\n" % exc)


def probe(account, timeout=20):
    """(alive, detail) for the real token: a revoke that beat the clock is caught here."""
    from google_core import headless
    from google_core import domain as D
    try:
        headless.access_token(account, timeout=timeout)
        return True, "the token refreshes"
    except D.GoogleError as exc:
        return False, " ".join(str(exc).split())[:300]


def registry():
    from google_core import adapters as AD
    return AD.JsonAccountStore(AD.accounts_path()).load()


def send(via, to, subject, body):
    """Through google.py send, the one Gmail send path in Brain."""
    proc = subprocess.run([sys.executable, os.path.join(HERE, "google.py"), "send", "--account", via,
                           "--to", to, "--subject", subject, "--html"],
                          input=body, text=True, capture_output=True, timeout=120)
    return proc.returncode == 0, ((proc.stdout or "").strip() or (proc.stderr or "").strip())


def main(argv=None, now=None, accounts=None, probe_fn=None, send_fn=None, path=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(prog="google_token_watch.py",
                                 description="warn before a Google refresh token expires")
    ap.add_argument("--account", action="append", default=[])
    ap.add_argument("--days", type=int, default=TESTING_LIFETIME_DAYS)
    ap.add_argument("--warn-within", type=float, default=WARN_WITHIN_DAYS)
    ap.add_argument("--to", default="")
    ap.add_argument("--via", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    try:
        args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        return 2 if exc.code else 0

    known = registry() if accounts is None else accounts
    names = args.account or sorted(n for n, a in known.items() if getattr(a, "authorized_at", ""))
    missing = [n for n in names if n not in known]
    if missing:
        sys.stderr.write("google_token_watch: no google.py account named %s\n" % ", ".join(missing))
        return 2
    if not names:
        out.write("no account has a consent stamp yet: run google.py auth once, or name one with --account\n")
        return 0

    now = now or dt.datetime.now().astimezone()
    today = now.date().isoformat()
    probe_fn = probe_fn or probe
    statuses = []
    for n in names:
        alive, detail = probe_fn(n)
        statuses.append(assess(n, known[n].authorized_at, alive, detail, now, args.days))
    for s in statuses:
        out.write(summary_line(s) + "\n")

    path = path or state_path()
    state = load_state(path)
    sent = state.get("last_sent_day") if isinstance(state.get("last_sent_day"), dict) else {}
    reasons = {}
    for s in statuses:
        reason = due(s, sent.get(s["account"]), today, args.warn_within)
        if reason or args.force:
            reasons[s["account"]] = reason or ("dead" if not s["alive"] else "expiring")
    if not reasons:
        out.write("no warning due.\n")
        return 0
    subject, body = compose(statuses, reasons, args.days)
    if args.dry_run or not args.to:
        out.write("\n--- SUBJECT ---\n%s\n--- BODY ---\n%s\n" % (subject, body))
        if not args.to and not args.dry_run:
            out.write("(no --to: printed, not sent)\n")
        return 0
    via = pick_sender(statuses, reasons, args.via)
    if not via:
        out.write("NOT sent: no watched account can send and no --via was given\n")
        return 1
    ok, detail = (send_fn or send)(via, args.to, subject, body)
    out.write(("sent via %s: " % via if ok else "NOT sent via %s: " % via) + detail + "\n")
    if not ok:
        return 1
    for account in reasons:
        sent[account] = today
    state["last_sent_day"] = sent
    save_state(path, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
