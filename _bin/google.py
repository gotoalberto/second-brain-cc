#!/usr/bin/env python3
"""google.py — Google accounts for Brain: Gmail, Calendar and Drive, read and write, through the APIs.

Any number of named accounts (personal, work, ...), each with its own OAuth desktop client and
refresh token in the local KeePass database. No connector, no third-party library: the loopback
OAuth flow and the REST calls are the standard library.

  google.py accounts
      the accounts connected on this machine (names, login hints, scopes; never a secret)
  google.py add --account NAME --client-id ID [--login-hint ADDRESS] [--scopes gmail,calendar,drive] [--port N]
      record an account and file its OAuth client in KeePass; the client secret is read from stdin
  google.py auth --account NAME [--no-browser] [--timeout S]
      one-off consent: opens Google's page, waits on 127.0.0.1:<port>, stores the refresh token and
      stamps the consent instant in the registry (google_token_watch.py counts a Testing-mode
      app's 7 day expiry from it)
  google.py token --account NAME
      print a fresh access token (for a manual curl)
  google.py api --account NAME URL [--method GET|POST|PUT|PATCH|DELETE] [--body-file FILE] [--force]
      an authenticated REST call; prints Google's JSON reply. On an HTTP error the reply is
      {"_http_error": <status>, "_body": "<Google's message>"} and the exit status is 1.
      Creating or moving a Calendar event is checked for conflicts first
      (google_core/calendar_guard.py): when the slot overlaps anything, nothing is written, the
      conflicts and free alternatives are printed and the exit status is 3. `--force` writes anyway,
      once the user has chosen to accept the overlap
  google.py slots --account NAME --start ISO [--minutes N] [--with ADDRESS ...] [--calendar ID]
                  [--tz ZONE] [--hours 9-19]
      the same conflict check for a slot, writing nothing: conflicts, attendees whose calendar is
      not shared, and free alternatives; exit 3 when the slot is taken
  google.py send --account NAME --to ADDRESS --subject S [--body-file FILE] [--html]
      one message from the account through the Gmail API (the gmail.send scope); the body comes from
      stdin or --body-file. Write it as plain text with a blank line between paragraphs and no hard
      wrapping: it goes out as HTML paragraphs with the text as the fallback part (mail_body.py);
      --html means the body already is markup and is sent as is. Every delivered message appends one JSON line (time, account, to, subject,
      Gmail message id, BRAIN_ROUTINE_RUN_ID when set; never the body) to BRAIN_MAIL_SENT_LOG, else
      <brain state>/logs/mail-sent.jsonl: the routine runner checks a routine's delivery there

Scope sets for --scopes: gmail (read, compose, send, labels, trash), calendar, drive, contacts (read).

Exit status: 0 done, 1 not done (a token or credential unavailable, an HTTP error, a message not
delivered, a calendar the conflict check could not read), 2 asked wrongly (usage, an unknown
account), 3 a calendar slot that is already taken (nothing written). token, api and send never prompt: they read
KeePass headless (arm its cache with `kp.py unlock`), so they are safe in scheduled jobs. So does slots.

KeePass entries per account: google/<account>/oauth-client (UserName = client id, Password = client
secret) and google/<account>/refresh-token. Creating the OAuth client (a Google Cloud project with a
"Desktop app" client and the Gmail, Calendar and Drive APIs enabled) is a manual step: the first run,
integrations/first-run/setup.sh, walks through it.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from google_core import adapters as AD  # noqa: E402
from google_core import calendar_guard as CG  # noqa: E402
from google_core import application as A  # noqa: E402
from google_core import domain as D  # noqa: E402
from google_core.ports import HttpError  # noqa: E402

HEADLESS = ("token", "api", "send", "slots")


class _Parser(argparse.ArgumentParser):
    """argparse, but a usage error is one line and exit 2, never a usage dump."""

    def error(self, message):
        raise D.UsageError(message)


def make_parser():
    ap = _Parser(prog="google.py", description="Google accounts for Brain: Gmail, Calendar and Drive",
                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", metavar="{accounts,add,auth,token,api,send,slots}", parser_class=_Parser)
    sub.add_parser("accounts", help="the accounts connected on this machine")
    p = sub.add_parser("add", help="record an account and file its OAuth client (secret on stdin)")
    p.add_argument("--account", required=True)
    p.add_argument("--client-id", required=True)
    p.add_argument("--login-hint", default="")
    p.add_argument("--scopes", default=",".join(D.DEFAULT_SCOPE_SETS))
    p.add_argument("--port", type=int, default=D.DEFAULT_PORT)
    p = sub.add_parser("auth", help="one-off consent in the browser; stores the refresh token")
    p.add_argument("--account", required=True)
    p.add_argument("--no-browser", action="store_true", help="only print the consent URL")
    p.add_argument("--timeout", type=int, default=300)
    p = sub.add_parser("token", help="print a fresh access token")
    p.add_argument("--account", required=True)
    p = sub.add_parser("api", help="an authenticated REST call; exit 1 on an HTTP error")
    p.add_argument("--account", required=True)
    p.add_argument("url")
    p.add_argument("--method", default="GET", choices=["GET", "POST", "PUT", "PATCH", "DELETE"])
    p.add_argument("--body-file")
    p.add_argument("--force", action="store_true", help="write a calendar event even over a conflict")
    p = sub.add_parser("send", help="send one message through the Gmail API")
    p.add_argument("--account", required=True)
    p.add_argument("--to", required=True)
    p.add_argument("--subject", required=True)
    p.add_argument("--body-file")
    p.add_argument("--html", action="store_true")
    p = sub.add_parser("slots", help="check a calendar slot for conflicts and propose free ones; writes nothing")
    p.add_argument("--account", required=True)
    p.add_argument("--start", required=True, help="ISO datetime, e.g. 2030-01-07T16:30:00+01:00")
    p.add_argument("--minutes", type=int, default=30)
    p.add_argument("--with", dest="people", nargs="*", default=[])
    p.add_argument("--calendar", default="primary")
    p.add_argument("--tz", default="", help="IANA zone for the alternatives; default this machine's")
    p.add_argument("--hours", default="%d-%d" % (CG.WORK_START, CG.WORK_END),
                   help="window for the alternatives in --tz, e.g. 15-20 when someone is hours behind")
    return ap


def _one_line(text) -> str:
    return " ".join(str(text).split())


def _caller(ports, account):
    """`call(url, method, body)` for calendar_guard: an authenticated request through this account."""
    return lambda url, method="GET", body=None: A.api(ports, account, method, url, body)


def _me(ports, account):
    hint = (A.get_account(ports, account).login_hint or "").strip().lower()
    return (hint,) if hint else ()


def _calendar_guard(ports, account, url, method, body, environ):
    """The conflict report when this request would book a taken calendar slot, else None."""
    if not CG.target(url, method):
        return None
    try:
        return CG.guard(_caller(ports, account), url, method, body, _me(ports, account),
                        default_tz=CG.local_zone(environ))
    except CG.GuardError as exc:
        raise D.GoogleError("the calendar conflict check could not run (%s); nothing was written. Rerun with "
                            "--force to write without it" % exc)


def _slots(ports, args, stdout, environ) -> int:
    import datetime as dt

    try:
        hours = CG.parse_hours(args.hours)
    except ValueError as exc:
        raise D.UsageError(str(exc))
    if args.minutes <= 0:
        raise D.UsageError("--minutes must be positive")
    tz = args.tz or CG.local_zone(environ)
    try:
        start = CG.parse_ts(args.start, tz)
    except Exception:
        raise D.UsageError("--start must be an ISO datetime, e.g. 2030-01-07T16:30:00+01:00")
    end = start + dt.timedelta(minutes=args.minutes)
    try:
        rep = CG.check(_caller(ports, args.account), args.calendar, start, end,
                       [{"email": p} for p in args.people], tz, me=_me(ports, args.account), hours=hours)
    except CG.GuardError as exc:
        raise D.GoogleError("could not read the calendar: %s" % exc)
    stdout.write(json.dumps(rep, indent=2, ensure_ascii=False) + "\n")
    return CG.EXIT_CONFLICT if rep["conflicts"] else 0


def run(args, ports, stdin, stdout, environ) -> int:
    if args.cmd == "accounts":
        accounts = A.list_accounts(ports)
        if not accounts:
            stdout.write("no accounts connected yet: google.py add --account <name> --client-id <id>\n")
        for a in accounts:
            sets = [s for s, scopes in sorted(D.SCOPES.items()) if all(x in a.scopes for x in scopes)]
            stdout.write("%-16s %-32s %s\n" % (a.name, a.login_hint or "-", ",".join(sets) or "custom scopes"))
        return 0

    if args.cmd == "add":
        if stdin.isatty():
            import getpass

            secret = getpass.getpass("OAuth client secret for %s: " % args.account)
        else:
            secret = stdin.read()
        sets = [s.strip() for s in args.scopes.split(",") if s.strip()]
        A.add_account(ports, args.account, args.client_id, secret.strip(), args.login_hint, sets, args.port)
        stdout.write("added %s; now authorise it: google.py auth --account %s\n" % (args.account, args.account))
        return 0

    if args.cmd == "auth":
        account = A.get_account(ports, args.account)
        stdout.write("Open Google's consent page%s, sign in%s and allow access. Waiting on %s ...\n"
                     % (" (printed below)" if args.no_browser else " (opening it now)",
                        " as " + account.login_hint if account.login_hint else "", D.redirect_uri(account.port)))
        stdout.flush()
        if args.no_browser:
            ports.open_url = lambda url: (stdout.write(url + "\n"), stdout.flush())
        entry = A.authorize(ports, args.account, timeout=args.timeout)
        stdout.write("refresh token stored in kp://%s\n" % entry)
        return 0

    if args.cmd == "token":
        stdout.write(A.access_token(ports, args.account) + "\n")
        return 0

    if args.cmd == "api":
        body = None
        if args.body_file:
            with open(args.body_file, encoding="utf-8") as fh:
                body = json.load(fh)
        if not args.force:
            blocked = _calendar_guard(ports, args.account, args.url, args.method, body, environ)
            if blocked:
                stdout.write(json.dumps(blocked, indent=2, ensure_ascii=False) + "\n")
                return CG.EXIT_CONFLICT
        result = A.api(ports, args.account, args.method, args.url, body)
        stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        return D.api_exit_code(result)

    if args.cmd == "slots":
        return _slots(ports, args, stdout, environ)

    if args.cmd == "send":
        account = A.get_account(ports, args.account)
        if args.body_file:
            try:
                with open(args.body_file, encoding="utf-8") as fh:
                    body = fh.read()
            except OSError as exc:
                raise D.UsageError("cannot read the body file %s (%s)" % (args.body_file, type(exc).__name__))
        else:
            body = stdin.read()
        sender = account.login_hint or "me"
        mailer = AD.GmailSender(sender, lambda: A.access_token(ports, args.account, D.GMAIL_SEND_SCOPE))
        run_id = (environ.get("BRAIN_ROUTINE_RUN_ID") or "").strip() or None
        record = A.send(ports, mailer, args.account, args.to, args.subject, body, html=args.html, run_id=run_id)
        stdout.write("sent to %s: %s\n" % (args.to, args.subject))
        if record.get("log_error"):
            sys.stderr.write("google.py send: delivered, but the send log could not be written (%s)\n"
                             % _one_line(record["log_error"]))
        return 0
    return 2


def main(argv=None, stdin=None, stdout=None, stderr=None, environ=None) -> int:
    stdin, stdout, stderr = stdin or sys.stdin, stdout or sys.stdout, stderr or sys.stderr
    environ = os.environ if environ is None else environ
    ap = make_parser()
    try:
        args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    except D.UsageError as exc:
        stderr.write("google.py: %s\n" % _one_line(exc))
        return 2
    if not args.cmd:
        ap.print_help(stderr)
        return 2
    ports = AD.build_ports(environ, headless=args.cmd in HEADLESS, open_browser=args.cmd == "auth")
    label = "google.py %s" % args.cmd
    try:
        return run(args, ports, stdin, stdout, environ)
    except (D.UsageError, D.AccountError) as exc:
        stderr.write("%s: %s\n" % (label, _one_line(exc)))
        return 2
    except (D.GoogleError, HttpError) as exc:
        stderr.write("%s: %s\n" % (label, _one_line(exc)))
        return 1
    except KeyboardInterrupt:
        stderr.write("%s: interrupted\n" % label)
        return 1
    except Exception as exc:
        stderr.write("%s: %s: %s\n" % (label, type(exc).__name__, _one_line(exc)))
        return 1


if __name__ == "__main__":
    sys.exit(main())
