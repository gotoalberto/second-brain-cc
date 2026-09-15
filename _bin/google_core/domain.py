"""The rules behind google.py's named Google accounts. Pure: no IO, no clock, no network.

An account is a name the user picks at first run (personal, work, ...). Each one has its own
OAuth desktop client and its own refresh token, both kept in the KeePass database:

  google/<account>/oauth-client    UserName = the client id, Password = the client secret
  google/<account>/refresh-token   Password = the refresh token

The two leaves share no prefix on purpose: `kp.py set` resolves a name by similarity, and a
refresh token must never land on the client's entry.

The registry of accounts (names, login hints, scopes, loopback ports) holds no secret and lives
in <brain state>/google-accounts.json.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
DEFAULT_PORT = 8766

SCOPES = {
    # read, compose, send, labels, archive, trash (no permanent delete)
    "gmail": ("https://www.googleapis.com/auth/gmail.modify", GMAIL_SEND_SCOPE),
    # every calendar and event, read and write
    "calendar": ("https://www.googleapis.com/auth/calendar",),
    # every Drive file, read and write
    "drive": ("https://www.googleapis.com/auth/drive",),
    # the account's own contacts, read only
    "contacts": ("https://www.googleapis.com/auth/contacts.readonly",),
}
DEFAULT_SCOPE_SETS = ("gmail", "calendar", "drive")

_ACCOUNT = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_ADDRESS = re.compile(r"[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+")


class GoogleError(Exception):
    """Something google.py cannot do, said in one line."""


class UsageError(GoogleError):
    """The command was asked wrongly: exit 2."""


class AccountError(GoogleError):
    """An account that is not in the registry, or a registry that does not parse: exit 2."""


class Unavailable(GoogleError):
    """A credential or token cannot be had right now, without asking anyone: exit 1."""


def valid_account(name) -> bool:
    return bool(_ACCOUNT.match(name or ""))


def scopes_for(sets) -> tuple:
    out = []
    for s in sets:
        if s not in SCOPES:
            raise UsageError("unknown scope set %r (known: %s)" % (s, ", ".join(sorted(SCOPES))))
        for scope in SCOPES[s]:
            if scope not in out:
                out.append(scope)
    return tuple(out)


DEFAULT_SCOPES = scopes_for(DEFAULT_SCOPE_SETS)


def client_entry(account: str) -> str:
    return "google/%s/oauth-client" % account


def refresh_entry(account: str) -> str:
    return "google/%s/refresh-token" % account


@dataclass(frozen=True)
class Account:
    name: str
    login_hint: str = ""
    scopes: tuple = DEFAULT_SCOPES
    port: int = DEFAULT_PORT


def parse_registry(text: str) -> dict:
    import json

    if not (text or "").strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise AccountError("the account registry is not JSON: %s" % exc)
    if not isinstance(data, dict):
        raise AccountError("the account registry must be an object")
    accounts = data.get("accounts") or {}
    if not isinstance(accounts, dict):
        raise AccountError("`accounts` must be an object")
    out = {}
    for name, spec in accounts.items():
        if not valid_account(name):
            raise AccountError("invalid account name %r" % name)
        spec = spec if isinstance(spec, dict) else {}
        scopes = spec.get("scopes", list(DEFAULT_SCOPES))
        if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
            raise AccountError("account %s: `scopes` must be a list of scope URLs" % name)
        port = spec.get("port", DEFAULT_PORT)
        if isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536:
            raise AccountError("account %s: `port` must be a TCP port number" % name)
        out[name] = Account(name, str(spec.get("login_hint") or ""), tuple(scopes) or DEFAULT_SCOPES, port)
    return out


def render_registry(accounts: dict) -> str:
    import json

    body = {name: {"login_hint": a.login_hint, "scopes": list(a.scopes), "port": a.port}
            for name, a in sorted(accounts.items())}
    return json.dumps({"accounts": body}, indent=2, ensure_ascii=False) + "\n"


def redirect_uri(port: int) -> str:
    return "http://127.0.0.1:%d" % port


def consent_url(client_id: str, account: Account, state: str) -> str:
    params = [("client_id", client_id), ("redirect_uri", redirect_uri(account.port)), ("response_type", "code"),
              ("access_type", "offline"), ("prompt", "consent"), ("scope", " ".join(account.scopes)),
              ("state", state)]
    if account.login_hint:
        params.append(("login_hint", account.login_hint))
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def parse_callback(params: dict, expected_state: str) -> str:
    if params.get("error"):
        raise GoogleError("consent was not given: %s" % params["error"])
    if params.get("state") != expected_state:
        raise GoogleError("the consent callback carries another state: refused")
    if not params.get("code"):
        raise GoogleError("the consent callback carries no code")
    return params["code"]


def code_request(client_id, client_secret, code, port) -> dict:
    return {"client_id": client_id, "client_secret": client_secret, "code": code,
            "grant_type": "authorization_code", "redirect_uri": redirect_uri(port)}


def refresh_request(client_id, client_secret, refresh_token) -> dict:
    return {"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh_token,
            "grant_type": "refresh_token"}


def access_token_from(payload, required_scope=None) -> str:
    """The access token in a token response. With `required_scope`, a token whose granted scopes
    lack it is Unavailable; a response with no `scope` field has nothing to check against."""
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not token:
        raise Unavailable("the token response carries no access_token")
    granted = payload.get("scope")
    if required_scope and granted is not None and required_scope not in str(granted).split():
        raise Unavailable("the token lacks the %s scope: authorise the account again with it"
                          % required_scope.rsplit("/", 1)[-1])
    return token


def refresh_token_from(payload) -> str:
    token = payload.get("refresh_token") if isinstance(payload, dict) else None
    if not token:
        raise GoogleError("Google returned no refresh token. Remove the app's access at "
                          "https://myaccount.google.com/permissions and run auth again: the new consent "
                          "returns one")
    return token


def valid_address(address) -> bool:
    return bool(_ADDRESS.fullmatch(address or ""))


def sent_record(account, to, subject, message_id, run_id=None, now=None) -> dict:
    """One line of the send log: account, recipient, subject, Gmail's message id, time and the routine
    run that sent it. Never the body, which may hold anything."""
    import datetime as dt

    stamp = now or dt.datetime.now().astimezone()
    record = {"ts": stamp.isoformat(timespec="seconds"), "account": account, "to": to, "subject": subject,
              "message_id": message_id or ""}
    if run_id:
        record["run_id"] = run_id
    return record


def api_exit_code(result) -> int:
    """`google.py api` prints Google's reply either way; an HTTP error exits 1."""
    return 1 if isinstance(result, dict) and "_http_error" in result else 0
