"""google.py's use cases: connect a named account, authorise it, get tokens, call APIs, send mail.

Only the ports are touched. What counts as a valid account, a good token or a send record is
decided in domain.py.
"""

from __future__ import annotations

import dataclasses
import secrets as _secrets
from dataclasses import dataclass

from . import domain as D
from .ports import HttpError


@dataclass
class Ports:
    secrets: object                 # ports.SecretStore
    http: object                    # ports.Http
    accounts: object                # ports.AccountStore
    receiver: object = None         # ports.ConsentReceiver, for auth
    send_log: object = None         # ports.SendLog, for send
    clock: object = None            # ports.Clock
    open_url: object = None         # callable(url), for auth: a browser, or None to only print it


def list_accounts(ports) -> list:
    return [a for _, a in sorted(ports.accounts.load().items())]


def get_account(ports, name) -> D.Account:
    accounts = ports.accounts.load()
    if name not in accounts:
        raise D.AccountError("no Google account named %r on this machine; connect it with "
                             "google.py add --account %s --client-id <id> (the first run offers it)"
                             % (name, name if D.valid_account(name) else "<name>"))
    return accounts[name]


def add_account(ports, name, client_id, client_secret, login_hint="", scope_sets=D.DEFAULT_SCOPE_SETS,
                port=D.DEFAULT_PORT) -> D.Account:
    """Record an account and file its OAuth client in KeePass. Authorising it is `authorize`."""
    if not D.valid_account(name):
        raise D.UsageError("invalid account name %r: lowercase letters, digits and dashes" % name)
    if not (client_id or "").strip():
        raise D.UsageError("--client-id is required")
    if not (client_secret or "").strip():
        raise D.UsageError("the OAuth client secret is required (on stdin)")
    account = D.Account(name, login_hint or "", D.scopes_for(scope_sets), int(port))
    ports.secrets.write(D.client_entry(name), client_secret.strip(), username=client_id.strip(),
                        notes="google.py account %s: OAuth desktop client (UserName is the client id)" % name)
    accounts = ports.accounts.load()
    accounts[name] = account
    ports.accounts.save(accounts)
    return account


def _client(ports, account, timeout):
    entry = D.client_entry(account.name)
    return ports.secrets.read(entry, "UserName", timeout), ports.secrets.read(entry, "Password", timeout)


def authorize(ports, name, timeout=300) -> str:
    """The loopback consent: open the URL, wait for Google's callback on 127.0.0.1, exchange the code,
    store the refresh token. Returns the KeePass entry it was stored in."""
    account = get_account(ports, name)
    client_id, client_secret = _client(ports, account, 60)
    state = _secrets.token_urlsafe(16)
    url = D.consent_url(client_id, account, state)
    if ports.open_url:
        ports.open_url(url)
    params = ports.receiver.wait(account.port, url, state, timeout)
    code = D.parse_callback(params, state)
    try:
        payload = ports.http.post_form(D.TOKEN_URL, D.code_request(client_id, client_secret, code, account.port),
                                       timeout=30)
    except HttpError as exc:
        raise D.GoogleError("the code exchange was refused (%d): %s" % (exc.status, exc.body[:200]))
    refresh = D.refresh_token_from(payload)
    entry = D.refresh_entry(name)
    ports.secrets.write(entry, refresh)
    if ports.clock:                 # the instant google_token_watch.py counts an expiry from
        accounts = ports.accounts.load()
        if name in accounts:
            accounts[name] = dataclasses.replace(accounts[name],
                                                 authorized_at=ports.clock.now().isoformat(timespec="seconds"))
            ports.accounts.save(accounts)
    return entry


def access_token(ports, name, required_scope=None, timeout=20) -> str:
    """A fresh access token for `name`. Never prompts when the secret store is headless."""
    account = get_account(ports, name)
    client_id, client_secret = _client(ports, account, timeout)
    try:
        refresh = ports.secrets.read(D.refresh_entry(name), "Password", timeout)
    except D.Unavailable as exc:
        raise D.Unavailable("no usable refresh token for %s (%s): run google.py auth --account %s"
                            % (name, exc, name))
    try:
        payload = ports.http.post_form(D.TOKEN_URL, D.refresh_request(client_id, client_secret, refresh),
                                       timeout=timeout)
    except HttpError as exc:
        raise D.Unavailable("the token refresh for %s was refused (%d): %s; if it says invalid_grant or "
                            "invalid_client, run google.py auth --account %s"
                            % (name, exc.status, " ".join(exc.body.split())[:200], name))
    return D.access_token_from(payload, required_scope)


def api(ports, name, method, url, body=None, timeout=30) -> dict:
    """An authenticated REST call. An HTTP error comes back as {"_http_error": status, "_body": text},
    so the caller sees Google's own message; google.py exits 1 on it (domain.api_exit_code)."""
    token = access_token(ports, name, timeout=min(timeout, 30))
    try:
        return ports.http.request(method, url, token, body, timeout)
    except HttpError as exc:
        return {"_http_error": exc.status, "_body": exc.body[:400]}


def send(ports, mailer, name, to, subject, body, html=False, run_id=None) -> dict:
    """One message through `mailer`, then one record in the send log. Returns the record.

    Usage problems raise UsageError before anything is sent. A delivery failure raises whatever the
    mailer raised and logs nothing. A log that cannot be written leaves `log_error` on the record: the
    message was delivered, and that is not undone."""
    if not D.valid_address(to):
        raise D.UsageError("--to must be exactly one email address")
    if not (subject or "").strip() or "\n" in subject or "\r" in subject:
        raise D.UsageError("--subject is required, on one line")
    if not (body or "").strip():
        raise D.UsageError("empty body: pass it on stdin or with --body-file")
    message_id = mailer.send(to, subject, body, html=html) or ""
    record = D.sent_record(name, to, subject, message_id, run_id, ports.clock.now() if ports.clock else None)
    try:
        ports.send_log.append(record)
    except Exception as exc:
        record["log_error"] = "%s: %s" % (type(exc).__name__, exc)
    return record
