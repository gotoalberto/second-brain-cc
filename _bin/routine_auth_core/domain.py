"""Routine authentication rules, with no IO at all.

How a failed CLI run is read, what a well-formed routine token looks like, what may be
written to a log about a failure, which token to try next, when a token expires, what the
pool config says and what environment a routine's CLI process gets. Inputs are plain
values and "now" is always passed in, so every rule is tested with literals.

What is deliberately NOT imported here: os, subprocess, pathlib, time or any clock.
KeePass, the state file and the CLI are the adapters' job (routine_auth_core/adapters.py).

Only the 401 invalid-token shapes are verified against the real CLI. The usage-limit and
credit-exhaustion patterns are guesses, marked as such, and anything that matches nothing
is UNKNOWN: an alert and no failover, never a guessed kind.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import re
from dataclasses import dataclass

# ---------------------------------------------------------------- kinds

OK = "ok"
AUTH_INVALID = "auth_invalid"              # verified: 401, the token is refused
USAGE_LIMIT = "usage_limit"                # UNVERIFIED pattern
CREDIT_EXHAUSTED = "credit_exhausted"      # UNVERIFIED pattern
NETWORK = "network"                        # UNVERIFIED pattern
TIMEOUT = "timeout"                        # the runner's own exit 124
CLI_MISSING = "cli_missing"                # the runner's own exit 126/127, or the health check
KEEPASS_LOCKED = "keepass_locked"          # raised by the token source before any run
KEEPASS_UNAVAILABLE = "keepass_unavailable"
TOKEN_MALFORMED = "token_malformed"        # the stored value is not one sk-ant-oat01- token
CONFIG = "config"                          # the pool config is missing or invalid
NO_TOKEN = "no_usable_token"               # every token is limited right now
CONTRACT_BREACH = "contract_breach"        # exit 0, but the routine did not deliver what its contract requires
UNKNOWN = "unknown"

VERIFIED_KINDS = (OK, AUTH_INVALID, TIMEOUT, CLI_MISSING)


@dataclass(frozen=True)
class Classification:
    kind: str
    detail: str = ""
    retry_after: object = None     # seconds, when the output says "try again in ..."
    resets_at: object = None       # epoch seconds, when the output carries a reset time
    verified: bool = True          # the pattern that matched was seen from the real CLI


# ---------------------------------------------------------------- classify

_AUTH_401 = re.compile(r"Failed to authenticate\.?.{0,40}?\b401\b|API Error:\s*401\b", re.I | re.S)
_CREDIT = re.compile(r"credit balance is too low|insufficient credit|out of credits|"
                     r"API Error:\s*402\b|payment required", re.I)
_USAGE = re.compile(r"usage limit|rate[ _]limit|limit reached|API Error:\s*429\b|too many requests", re.I)
_NETWORK = re.compile(r"Connection error|ECONNREFUSED|ENOTFOUND|ETIMEDOUT|ECONNRESET|EAI_AGAIN|"
                      r"getaddrinfo|socket hang up|network is unreachable|fetch failed", re.I)
_OTHER_STATUS = re.compile(r"API Error:\s*(?!401\b)\d{3}\b")
_RETRY_IN = re.compile(r"(?:try again|retry|resets?) in (\d+)\s*(second|minute|hour)s?", re.I)
_RETRY_AFTER = re.compile(r"retry-after:\s*(\d+)", re.I)
_RESET_EPOCH = re.compile(r"limit reached\|(\d{10})\b", re.I)
_UNIT = {"second": 1, "minute": 60, "hour": 3600}


def parse_json_output(stdout):
    """The result object `--output-format json` prints: the whole stdout, else its last
    line that parses as a JSON object. None when there is none."""
    text = (stdout or "").strip()
    if not text:
        return None
    candidates = [text] + [line.strip() for line in reversed(text.splitlines())]
    for c in candidates:
        if not c.startswith("{"):
            continue
        try:
            data = json.loads(c)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _first_line_matching(rx, text) -> str:
    for line in text.splitlines():
        if rx.search(line):
            return redact(line.strip(), limit=200)
    return ""


def _retry(text):
    m = _RETRY_IN.search(text)
    if m:
        return int(m.group(1)) * _UNIT[m.group(2).lower()], None
    m = _RETRY_AFTER.search(text)
    if m:
        return int(m.group(1)), None
    m = _RESET_EPOCH.search(text)
    if m:
        return None, int(m.group(1))
    return None, None


def classify(exit_code, stdout, stderr, json_output=None) -> Classification:
    """Read one CLI run's outcome. Order matters, and is the order below.

    1. exit 0 is ok; 124, 126 and 127 are the runner's own timeout and missing-binary codes.
    2. The verified 401 text.
    3. The unverified credit, usage-limit and network patterns, in the text or in the json
       result.
    4. The verified json shape of a 401 (`terminal_reason` api_error, `total_cost_usd` 0),
       but only when no other HTTP status appears: an api_error with cost 0 can also be a
       429 or a 529, and marking a good token dead is worse than an unknown.
    5. Anything else is UNKNOWN.
    """
    if exit_code == 0:
        return Classification(OK)
    if exit_code == 124:
        return Classification(TIMEOUT, "the run timed out")
    if exit_code in (126, 127):
        return Classification(CLI_MISSING, redact((stderr or "").strip(), limit=200))
    data = json_output if json_output is not None else parse_json_output(stdout)
    result_text = ""
    if isinstance(data, dict):
        result_text = "\n".join(str(data.get(k) or "") for k in ("result", "error", "message"))
    text = "\n".join(t for t in (stdout or "", stderr or "", result_text) if t)

    if _AUTH_401.search(text):
        return Classification(AUTH_INVALID, _first_line_matching(_AUTH_401, text) or "401")
    for kind, rx in ((CREDIT_EXHAUSTED, _CREDIT), (USAGE_LIMIT, _USAGE), (NETWORK, _NETWORK)):
        if rx.search(text):
            retry_after, resets_at = _retry(text) if kind == USAGE_LIMIT else (None, None)
            return Classification(kind, _first_line_matching(rx, text), retry_after, resets_at, verified=False)
    if (isinstance(data, dict) and data.get("terminal_reason") == "api_error"
            and data.get("total_cost_usd") in (0, 0.0) and not _OTHER_STATUS.search(text)):
        return Classification(AUTH_INVALID, "api_error with no cost (the verified json shape of a 401)")
    last = [l for l in text.splitlines() if l.strip()]
    return Classification(UNKNOWN, "exit %s%s" % (exit_code, (": " + redact(last[-1].strip(), limit=160)) if last else ""),
                          verified=False)


# ---------------------------------------------------------------- token shape

TOKEN_PREFIX = "sk-ant-oat01-"
_TOKEN_BODY = re.compile(r"^[A-Za-z0-9_-]+$")


def token_shape(value):
    """(well_formed, shape). The shape describes the value without quoting any of it.

    Well formed is exactly one `sk-ant-oat01-` token: no whitespace anywhere (a pasted
    newline or a label in front of it is the usual accident), nothing but letters, digits,
    `_` and `-` after the prefix.
    """
    if not value:
        return False, "empty"
    n = len(value)
    if any(c.isspace() for c in value):
        return False, "contains whitespace (%d word(s), %d characters)" % (len(value.split()), n)
    if not value.startswith(TOKEN_PREFIX):
        return False, "does not start with %s (%d characters)" % (TOKEN_PREFIX, n)
    body = value[len(TOKEN_PREFIX):]
    if not body:
        return False, "is the %s prefix alone" % TOKEN_PREFIX
    if not _TOKEN_BODY.match(body):
        return False, "has characters outside [A-Za-z0-9_-] after %s (%d characters)" % (TOKEN_PREFIX, n)
    return True, "one %s token, %d characters" % (TOKEN_PREFIX, n)


# ---------------------------------------------------------------- redact

_TOKENISH = re.compile(r"sk-ant-[A-Za-z0-9_\-]+")
_BEARER = re.compile(r"(Bearer\s+)\S+", re.I)
_LONG_OPAQUE = re.compile(r"[A-Za-z0-9_\-+/=]{48,}")


def redact(text, secrets=(), limit=4000) -> str:
    """What may be written to a log about a run: token-looking values, bearer credentials,
    long opaque strings and every value in `secrets` replaced, and at most the last
    `limit` characters kept."""
    out = text or ""
    for s in secrets or ():
        if s:
            out = out.replace(s, "[redacted]")
    out = _TOKENISH.sub("[redacted token]", out)
    out = _BEARER.sub(r"\1[redacted]", out)
    out = _LONG_OPAQUE.sub("[redacted]", out)
    if limit and len(out) > limit:
        out = "[%d characters cut]\n" % (len(out) - limit) + out[-limit:]
    return out


# ---------------------------------------------------------------- pool state and failover

HEALTHY = "healthy"
DEAD = "dead"
LIMITED = "limited-until"

# How long a limited token rests when the output gives no reset time. Guesses, like the
# patterns that produce these kinds: calibrate them from the raw-output log.
DEFAULT_BACKOFF_S = {USAGE_LIMIT: 3600, CREDIT_EXHAUSTED: 24 * 3600}

FAILOVER_KINDS = (AUTH_INVALID, TOKEN_MALFORMED, USAGE_LIMIT, CREDIT_EXHAUSTED)   # this token is the problem
RETRY_SAME_KINDS = (NETWORK,)                                                    # the token is fine, the wire is not


def _iso(t: dt.datetime) -> str:
    return t.isoformat(timespec="seconds")


def _parse(s):
    try:
        return dt.datetime.fromisoformat(s) if s else None
    except (TypeError, ValueError):
        return None


def token_status(state: dict, label: str, now: dt.datetime) -> str:
    """HEALTHY, DEAD or LIMITED. A token never seen is healthy; a limit that has passed is too."""
    entry = (state or {}).get(label) or {}
    status = entry.get("status") or HEALTHY
    if status == LIMITED:
        until = _parse(entry.get("until"))
        if until is None or until <= now:
            return HEALTHY
    return status if status in (HEALTHY, DEAD, LIMITED) else HEALTHY


def attempt_order(labels, state: dict, now: dt.datetime) -> list:
    """Which tokens to try, in order: healthy ones in pool order, then dead ones.

    A dead token is kept as the last resort on purpose. The state cannot see KeePass, so
    it cannot tell that a refused token has since been re-stored; one more 401 costs
    nothing, and a run that succeeds with it marks it healthy again. A limited token is
    left out until its limit ends.
    """
    labels = list(labels)
    healthy = [l for l in labels if token_status(state, l, now) == HEALTHY]
    dead = [l for l in labels if token_status(state, l, now) == DEAD]
    return healthy + dead


def record(state: dict, label: str, cls: Classification, now: dt.datetime, backoff=None) -> dict:
    """The pool state after one attempt with `label`. Returns a new dict; `state` is untouched.

    OK makes the token healthy. A refused or malformed token is dead. A usage or credit
    limit rests it until the reset time in the output, else for the backoff. Every other
    kind (network, timeout, KeePass, the CLI, unknown) says nothing about the token, so
    its status is kept and only the last kind and time are stamped.
    """
    backoff = DEFAULT_BACKOFF_S if backoff is None else backoff
    new = copy.deepcopy(state or {})
    entry = dict(new.get(label) or {})
    entry.setdefault("status", HEALTHY)
    entry.setdefault("until", None)
    if cls.kind == OK:
        entry["status"], entry["until"] = HEALTHY, None
    elif cls.kind in (AUTH_INVALID, TOKEN_MALFORMED):
        entry["status"], entry["until"] = DEAD, None
    elif cls.kind in (USAGE_LIMIT, CREDIT_EXHAUSTED):
        until = None
        if cls.retry_after:
            until = now + dt.timedelta(seconds=int(cls.retry_after))
        elif cls.resets_at:
            reset = dt.datetime.fromtimestamp(int(cls.resets_at))
            until = reset if reset > now else None
        if until is None:
            until = now + dt.timedelta(seconds=int(backoff.get(cls.kind, DEFAULT_BACKOFF_S.get(cls.kind, 3600))))
        entry["status"], entry["until"] = LIMITED, _iso(until)
    entry["last_kind"] = cls.kind
    entry["last_at"] = _iso(now)
    entry["detail"] = redact(cls.detail, limit=200)
    new[label] = entry
    return new


def next_token(labels, state: dict, current: str, kind: str, now: dt.datetime, tried=()):
    """The token to try after `current` failed with `kind`, or None to stop.

    `state` is the pool state after that failure was recorded. A token-level failure moves
    to the next token not yet tried in this run; a network failure retries the same token;
    anything else stops: KeePass, the CLI, a timeout or an unknown failure are not "this
    token is bad", and trying the next one would only repeat them.
    """
    if kind in RETRY_SAME_KINDS:
        return current
    if kind not in FAILOVER_KINDS:
        return None
    tried = set(tried or ()) | {current}
    for label in attempt_order(labels, state, now):
        if label not in tried:
            return label
    return None


# ---------------------------------------------------------------- the pool config

TOKEN_LIFETIME_DAYS = 365
KP_GROUP = "Brain"
_POOL_KEYS = ("label", "account", "kp_ref", "issued", "notes")


class PoolConfigError(ValueError):
    """90-Meta/routine-tokens.json is not a valid pool. The message never quotes a value."""


@dataclass(frozen=True)
class PoolEntry:
    label: str
    kp_ref: str
    issued: dt.date
    account: str = ""
    notes: str = ""


def parse_pool(text: str) -> list:
    """The ordered token pool from the config text: `{"tokens": [...]}` or a bare list.

    Strict on purpose: the file sits in a synced vault, so an unknown key (someone pasting
    a `token` field) or anything that looks like a token value is refused, and the error
    names the key, never the value.
    """
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise PoolConfigError("not valid JSON (line %s)" % getattr(exc, "lineno", "?"))
    tokens = data.get("tokens") if isinstance(data, dict) else data
    if not isinstance(tokens, list):
        raise PoolConfigError("`tokens` must be a list")
    if not tokens:
        raise PoolConfigError("the pool has no tokens")
    out, seen = [], set()
    for i, raw in enumerate(tokens, 1):
        where = "token %d" % i
        if not isinstance(raw, dict):
            raise PoolConfigError("%s is not an object" % where)
        unknown = sorted(k for k in raw if k not in _POOL_KEYS)
        if unknown:
            raise PoolConfigError("%s has unknown key(s) %s; allowed: %s"
                                  % (where, ", ".join(unknown), ", ".join(_POOL_KEYS)))
        for k, v in raw.items():
            if not isinstance(v, str):
                raise PoolConfigError("%s: %s must be a string" % (where, k))
            if _TOKENISH.search(v) or TOKEN_PREFIX in v:
                raise PoolConfigError("%s: %s looks like it holds a token value; the pool keeps kp:// "
                                      "references only (move the value to the kdbx)" % (where, k))
        label = raw.get("label", "").strip()
        if not label:
            raise PoolConfigError("%s has no label" % where)
        if label in seen:
            raise PoolConfigError("duplicate label %s" % label)
        seen.add(label)
        ref = raw.get("kp_ref", "").strip()
        if not ref.startswith("kp://") or not kp_entry(ref):
            raise PoolConfigError("%s (%s): kp_ref must be a kp://Group/Entry reference" % (where, label))
        try:
            issued = dt.date.fromisoformat(raw.get("issued", ""))
        except ValueError:
            raise PoolConfigError("%s (%s): issued must be YYYY-MM-DD" % (where, label))
        out.append(PoolEntry(label, ref, issued, raw.get("account", ""), raw.get("notes", "")))
    return out


def kp_entry(kp_ref: str) -> str:
    """The entry name kp.py takes: `kp://Brain/apis/x#password` is `apis/x`.

    kp.py puts every name inside its agent group (`Brain` by default), so the group is dropped
    here the same way kp.py's norm() drops it.
    """
    e = (kp_ref or "").strip()
    if e.startswith("kp://"):
        e = e[len("kp://"):]
    e = e.split("#", 1)[0].strip("/")
    parts = [p for p in e.split("/") if p]
    if parts and parts[0].lower() == KP_GROUP.lower():
        parts = parts[1:]
    return "/".join(parts)


def kp_attr(kp_ref: str) -> str:
    return (kp_ref or "").split("#", 1)[1] if "#" in (kp_ref or "") else "password"


def restore_command(kp_ref: str) -> str:
    """How to store a copied token so it arrives as exactly one word."""
    return "pbpaste | tr -d '[:space:]' | python3 ~/Brain/_bin/kp.py set \"%s\" --stdin" % kp_entry(kp_ref)


def renew_command(kp_ref: str) -> str:
    return "claude setup-token (copy the token it prints), then: " + restore_command(kp_ref)


def expires_on(issued: dt.date) -> dt.date:
    return issued + dt.timedelta(days=TOKEN_LIFETIME_DAYS)


@dataclass(frozen=True)
class ExpiryNotice:
    label: str
    expires: dt.date
    days_left: int
    expired: bool


def expiry_findings(entries, now: dt.datetime, warn_days=30) -> list:
    """Tokens expiring within `warn_days` of `now`, or already expired, in pool order."""
    today = now.date() if isinstance(now, dt.datetime) else now
    out = []
    for e in entries:
        expires = expires_on(e.issued)
        left = (expires - today).days
        if left <= warn_days:
            out.append(ExpiryNotice(e.label, expires, left, left < 0))
    return out


# ---------------------------------------------------------------- the CLI

# Where the Claude Desktop app keeps its own copies of the CLI. A routine never runs one:
# that copy follows the app's login and updates, which is exactly what routines must not.
DESKTOP_CLI_PREFIXES = ("/Applications/Claude.app/", "{home}/Library/Application Support/Claude/")
FORBIDDEN_ARGS = ("--bare",)


@dataclass(frozen=True)
class CliStatus:
    ok: bool
    path: str = ""
    version: str = ""
    detail: str = ""


def expand_home(tokens, home: str) -> list:
    """`~` and `~/...` become the home directory. `~user` and a tilde inside a word do not."""
    out = []
    for t in tokens:
        if t == "~":
            out.append(home)
        elif t.startswith("~/"):
            out.append(home.rstrip("/") + t[1:])
        else:
            out.append(t)
    return out


def template_tokens(template: str, home: str) -> list:
    import shlex

    try:
        return expand_home(shlex.split(template or ""), home)
    except ValueError:
        return []


def cli_path_problem(resolved: str, real: str, home: str):
    """Why this CLI path must not run routines, or None."""
    prefixes = [p.format(home=home.rstrip("/")) for p in DESKTOP_CLI_PREFIXES]
    for path in (resolved, real):
        if any((path or "").startswith(p) for p in prefixes):
            return ("%s is the Claude Desktop app's own copy of the CLI (it follows the app's login and "
                    "updates). Install the standalone CLI with the official installer and point "
                    "90-Meta/agent-command.txt at ~/.local/bin/claude" % real)
    return None


def forbidden_arg_problem(tokens):
    for t in tokens:
        for bad in FORBIDDEN_ARGS:
            if t == bad or t.startswith(bad + "="):
                return ("%s is refused: it ignores CLAUDE_CODE_OAUTH_TOKEN and skips skills, hooks and MCP, "
                        "so the routine would run unauthenticated or half-blind" % bad)
    return None


# ---------------------------------------------------------------- permissions an unattended run may never have

UNRESTRICTED_BASH = ("Bash", "Bash(*)", "Bash(:*)")
SKIP_PERMISSION_FLAGS = ("--dangerously-skip-permissions", "--allow-dangerously-skip-permissions")
_ALLOWED_TOOLS_FLAGS = ("--allowedTools", "--allowed-tools")


def _tool_entries(value: str) -> list:
    """`Read,Bash(git -C x status:*) WebFetch` as its entries: split on commas and whitespace
    outside parentheses, so a pattern's own spaces and commas stay inside it."""
    out, cur, depth = [], "", 0
    for ch in value or "":
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if depth == 0 and (ch == "," or ch.isspace()):
            if cur:
                out.append(cur)
            cur = ""
            continue
        cur += ch
    if cur:
        out.append(cur)
    return out


def permission_problem(tokens):
    """Why these CLI arguments would give an unattended run unrestricted permissions, or None.

    Refused: skipping permission checks (`--dangerously-skip-permissions`, its `--allow-` form,
    `--permission-mode bypassPermissions`) and an allowed-tools list granting any shell command
    (bare `Bash`, `Bash(*)`, `Bash(:*)`). A routine lists narrow prefix patterns instead, such
    as `Bash(python3 ~/Brain/_bin/vw.py append:*)`.
    """
    toks = list(tokens or ())
    for i, t in enumerate(toks):
        for flag in SKIP_PERMISSION_FLAGS:
            if t == flag or t.startswith(flag + "="):
                return "%s is refused: an unattended run must never skip permission checks" % flag
        if t == "--permission-mode=bypassPermissions" or (
                t == "--permission-mode" and i + 1 < len(toks) and toks[i + 1] == "bypassPermissions"):
            return "--permission-mode bypassPermissions is refused: an unattended run must never skip permission checks"
        values = []
        if t in _ALLOWED_TOOLS_FLAGS:
            for v in toks[i + 1:]:
                if v.startswith("-"):
                    break
                values.append(v)
        else:
            for flag in _ALLOWED_TOOLS_FLAGS:
                if t.startswith(flag + "="):
                    values.append(t[len(flag) + 1:])
        for v in values:
            for entry in _tool_entries(v):
                if entry in UNRESTRICTED_BASH:
                    return ("--allowedTools grants unrestricted Bash (%s): list narrow prefix patterns such as "
                            "Bash(python3 ~/Brain/_bin/vw.py append:*) instead" % entry)
    return None


# ---------------------------------------------------------------- one run

TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"
# What a routine's CLI process inherits, and nothing else. An allowlist, so no Anthropic,
# cloud provider or proxy variable of the parent (ANTHROPIC_*, AWS_*, CLAUDE_CODE_USE_*,
# GOOGLE_APPLICATION_CREDENTIALS, a stale CLAUDE_CODE_OAUTH_TOKEN) can outrank the pool token.
ENV_KEEP = ("HOME", "PATH", "USER", "LOGNAME", "SHELL", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "TERM",
            "SSH_AUTH_SOCK", "__CF_USER_TEXT_ENCODING", "BRAIN_VAULT", "BRAIN_STATE")
DEFAULT_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
# What the runner itself tells the child about the run, never inherited from the parent.
RUN_ID_ENV = "BRAIN_ROUTINE_RUN_ID"            # google.py send stamps its log record with it
SCRATCH_ENV = "BRAIN_ROUTINE_SCRATCH"          # the attempt's private scratch directory
HEADLESS_ENV = "BRAIN_HEADLESS"                # "1": nobody is at the keyboard (hook scripts may read it)
SEND_LOG_ENV = "BRAIN_MAIL_SENT_LOG"           # where google.py send logs, so writer and reader agree

# Exit codes for runs that never reached the CLI (sysexits: 75 temporary, 78 configuration).
EXIT_CODES = {CLI_MISSING: 127, CONFIG: 78, TOKEN_MALFORMED: 78,
              KEEPASS_LOCKED: 75, KEEPASS_UNAVAILABLE: 75, NO_TOKEN: 75, CONTRACT_BREACH: 65}


def routine_env(base_env: dict, token: str, run_id=None, scratch=None, extra=None) -> dict:
    """The environment of one routine attempt, built from scratch: the allowlist, the runner's
    `extra` variables (the send log path), the run's id and scratch directory, BRAIN_HEADLESS=1,
    auto-update off so a CLI upgrade never lands in the middle of a run, and the pool token
    last, so nothing can replace it."""
    base = base_env or {}
    env = {k: base[k] for k in ENV_KEEP if base.get(k)}
    env.setdefault("PATH", DEFAULT_PATH)
    for k, v in (extra or {}).items():
        if v:
            env[k] = str(v)
    env["DISABLE_AUTOUPDATER"] = "1"
    env[HEADLESS_ENV] = "1"
    if run_id:
        env[RUN_ID_ENV] = run_id
    if scratch:
        env[SCRATCH_ENV] = scratch
    env[TOKEN_ENV] = token
    return env


_UNSAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


def run_id(routine_id: str, now: dt.datetime, suffix: str) -> str:
    """One attempt's id: `<routine id>-<YYYYMMDDTHHMMSS>-<suffix>`, safe as one directory name.
    The suffix is the adapter's randomness, so two attempts in the same second still differ."""
    def safe(s):
        return _UNSAFE_ID.sub("-", s or "").strip(".-") or "x"

    return "%s-%s-%s" % (safe(routine_id), now.strftime("%Y%m%dT%H%M%S"), safe(suffix))


# ---------------------------------------------------------------- the prompt a run receives

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)


def strip_html_comments(text: str) -> str:
    """Every complete `<!-- ... -->` removed; an unterminated one is left as it is."""
    return _HTML_COMMENT.sub("", text or "")


def routine_body(text: str) -> str:
    """What the agent is asked to do: the routine file without its frontmatter and without the
    HTML comments that document it for people."""
    text = text or ""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            text = text[end + len("\n---\n"):]
    text = strip_html_comments(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def frame_prompt(routine_id: str, body: str, run_id: str, scratch=None) -> str:
    """The whole prompt of one attempt: an explicit order to run the routine now, the facts of
    this run, the rules of an unattended run, then the routine body.

    Handed over bare, a long body that opens with documentation reads as context, and the
    model asks what to do (seen in a real run). The rules are the
    ones the first real runs broke: the `save` skill and a background agent after the work,
    `cd ... &&`, temporary files in /tmp or inside the vault, `cat`, and a timestamp line that
    vw.py adds a second time.
    """
    head = ('You are running the Brain routine "%s" unattended, right now, with nobody at the keyboard. '
            "Execute the procedure below from start to finish now. Do not ask for a request, do not wait for input. "
            "Nobody will read a question: the procedure below is the whole request." % routine_id)
    facts = ["This run:", "- run id: %s" % run_id]
    if scratch:
        facts.append('- scratch directory: "%s" (also in $BRAIN_ROUTINE_SCRATCH). Every temporary file of this run '
                     "goes there, written by that literal path and quoted in shell commands: never /tmp, never "
                     "inside ~/Brain. It is deleted after a successful run." % scratch)
    else:
        facts.append("- there is no scratch directory for this run: write no temporary files, not in /tmp and not "
                     "inside ~/Brain.")
    rules = [
        "Rules for an unattended run:",
        "- The procedure's own steps are the whole job. Do not invoke the `save` skill and do not spawn subagents or "
        "background agents: they die when this process exits. Leave undone whatever the procedure does not ask for.",
        "- Run each shell command on its own, in the exact form the procedure names; other forms are denied. Use "
        "`git -C <dir> <command>`, never `cd <dir> && <command>`.",
        "- Read files with the Read tool, never `cat`, and load a skill with the Skill tool.",
        "- `python3 ~/Brain/_bin/vw.py append <note>` takes the entry on stdin: write the entry to a file in the "
        "scratch directory with the Write tool, then run `python3 ~/Brain/_bin/vw.py append <note> < "
        "\"<scratch directory>/<file>\"`. Do not start the entry with a date or time: vw.py adds the timestamp itself.",
        "- End with the report the procedure asks for.",
    ]
    return "%s\n\n%s\n\n%s\n\nThe procedure:\n\n%s\n" % (head, "\n".join(facts), "\n".join(rules), (body or "").strip())


# ---------------------------------------------------------------- scratch directories

SCRATCH_KEEP_DAYS = 7


def scratch_to_prune(entries, now: dt.datetime, keep_days=SCRATCH_KEEP_DAYS) -> list:
    """Names of the scratch directories to delete: `entries` are (name, last modified), and a
    directory older than `keep_days` is a failed run nobody came back to inspect."""
    cutoff = now - dt.timedelta(days=keep_days)
    return [name for name, modified in entries if modified < cutoff]


def frontmatter(text: str):
    """A note's frontmatter block without its fences, or None."""
    text = text or ""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    return text[4:end + 1] if end != -1 else None


def parse_agent_args(text: str):
    """(args, problem) from a routine file's `agent_args:` frontmatter line.

    The value must be a JSON list of strings, e.g.
    `agent_args: ["--permission-mode", "acceptEdits", "--allowedTools", "Bash,Read"]`.
    Anything else, or a forbidden argument, is ignored with a problem saying why: the
    routine still runs with the template alone, and the problem becomes a warning.
    """
    fm = frontmatter(text)
    if fm is None:
        return (), None
    for line in fm.splitlines():
        if not line.startswith("agent_args:"):
            continue
        try:
            value = json.loads(line[len("agent_args:"):].strip())
        except ValueError:
            value = None
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return (), ("agent_args is not a JSON list of strings: ignored, the agent command template "
                        "runs without it")
        problem = forbidden_arg_problem(value)
        if problem:
            return (), "agent_args ignored: " + problem
        return tuple(value), None
    return (), None


# ---------------------------------------------------------------- what a routine requires

_REQUIRES_KEYS = ("repos", "programs", "paths")
_REQUIRES_PROBLEM = ('requires is not a JSON object with repos (paths, or {"path", "url"} objects), programs and '
                     "paths (lists of non-empty strings): the run is refused until it is fixed")


@dataclass(frozen=True)
class Requires:
    """What a routine needs on the machine that runs it, beyond what its agent_args already name.

    `repos` are (path, clone url) pairs, the url "" when none is given; a path is a git checkout
    when it holds `.git`. `programs` must be on PATH. `paths` must exist. A relative path is
    relative to the vault, a leading ~ is the home directory: routine_requires.py resolves both."""
    repos: tuple = ()
    programs: tuple = ()
    paths: tuple = ()


def _repo(item):
    if isinstance(item, str) and item.strip():
        return item.strip(), ""
    if isinstance(item, dict) and set(item) <= {"path", "url"}:
        path, url = item.get("path"), item.get("url", "")
        if isinstance(path, str) and path.strip() and isinstance(url, str):
            return path.strip(), url.strip()
    return None


def parse_requires(text: str):
    """(requires, problem) from a routine file's `requires:` frontmatter line.

    A JSON object, e.g. `requires: {"repos": ["~/code/tool"], "programs": ["git"], "paths": []}`;
    a repo may also be `{"path": "~/code/tool", "url": "<clone url>"}` so `routine_requires.py
    --fix` can clone it. No key is no requirement (today's behaviour). A key that does not parse is
    a problem, and the runner refuses the run on it: a typo must never turn into a silent pass.
    """
    fm = frontmatter(text)
    if fm is None:
        return None, None
    for line in fm.splitlines():
        if not line.startswith("requires:"):
            continue
        try:
            value = json.loads(line[len("requires:"):].strip())
        except ValueError:
            return None, _REQUIRES_PROBLEM
        if not isinstance(value, dict) or not value or any(k not in _REQUIRES_KEYS for k in value):
            return None, _REQUIRES_PROBLEM
        if any(not isinstance(value.get(k, []), list) for k in _REQUIRES_KEYS):
            return None, _REQUIRES_PROBLEM
        repos = [_repo(r) for r in value.get("repos", [])]
        if any(r is None for r in repos):
            return None, _REQUIRES_PROBLEM
        for key in ("programs", "paths"):
            if value.get(key) and not _strings(value[key]):
                return None, _REQUIRES_PROBLEM
        return Requires(tuple(repos), tuple(p.strip() for p in value.get("programs", [])),
                        tuple(p.strip() for p in value.get("paths", []))), None
    return None, None


# ---------------------------------------------------------------- the success contract

_CONTRACT_KEYS = ("final_line", "required", "forbidden", "required_sends", "sends_to")
_CONTRACT_PROBLEM = ("success_contract is not a JSON object with final_line (a string), required and forbidden "
                     "(lists of strings), required_sends (a whole number from 1) and sends_to (one address, "
                     "with required_sends): the run counts as failed until it is fixed")
_ONE_ADDRESS = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
SEND_LOG_NAME = "<brain state>/logs/mail-sent.jsonl"


@dataclass(frozen=True)
class SuccessContract:
    """What a routine run must show for an exit 0 to count as delivered.

    The markers are checked on the model's answer. `required_sends` is checked on the send log
    google.py send writes, for this attempt's run id: a delivery that happened counts
    whatever the answer ends on, and an answer that only claims one does not."""
    final_line: object = None     # the last non-empty line, exactly
    required: tuple = ()          # markers that must appear
    forbidden: tuple = ()         # markers that must not appear
    required_sends: int = 0       # emails recorded as delivered under this run's id
    sends_to: object = None       # ...to this address (case-insensitive), when set


def _strings(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)


def parse_success_contract(text: str):
    """(contract, problem) from a routine file's `success_contract:` frontmatter line.

    A JSON object, e.g. `{"required_sends": 1, "sends_to": "a@example.com", "forbidden": ["EMAIL NOT SENT:"]}`
    or `{"required": ["ROUTINE_OK"]}`. No key is no contract (exit 0 is success). A key that
    does not parse is a problem, and run_routine fails the run on it: a typo in a contract must
    never turn into a silent success.
    """
    fm = frontmatter(text)
    if fm is None:
        return None, None
    for line in fm.splitlines():
        if not line.startswith("success_contract:"):
            continue
        try:
            value = json.loads(line[len("success_contract:"):].strip())
        except ValueError:
            return None, _CONTRACT_PROBLEM
        if not isinstance(value, dict) or not value or any(k not in _CONTRACT_KEYS for k in value):
            return None, _CONTRACT_PROBLEM
        final = value.get("final_line")
        if final is not None and (not isinstance(final, str) or not final.strip()):
            return None, _CONTRACT_PROBLEM
        for key in ("required", "forbidden"):
            if key in value and not _strings(value[key]):
                return None, _CONTRACT_PROBLEM
        sends = value.get("required_sends", 0)
        if "required_sends" in value and (isinstance(sends, bool) or not isinstance(sends, int) or sends < 1):
            return None, _CONTRACT_PROBLEM
        to = value.get("sends_to")
        if to is not None and (not isinstance(to, str) or not _ONE_ADDRESS.match(to.strip()) or not sends):
            return None, _CONTRACT_PROBLEM
        return SuccessContract(final.strip() if final else None, tuple(value.get("required") or ()),
                               tuple(value.get("forbidden") or ()), sends, to.strip() if to else None), None
    return None, None


def parse_send_log(text: str) -> list:
    """The records of the send log, one JSON object per line; any other line is skipped."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def sends_for_run(records, run_id) -> list:
    """The send records stamped with this run id. A send with no run id belongs to no run."""
    if not run_id:
        return []
    return [r for r in records or () if isinstance(r, dict) and r.get("run_id") == run_id]


_NO_REQUEST = re.compile(
    r"(?:don[’']?t|do not|didn[’']?t|did not|can[’']?t|cannot) see (?:any |an |a |the )?(?:actual |specific |clear )?"
    r"(?:request|question|task)|what would you like (?:me )?to|how can I help(?: you)?(?: today)?\?", re.I)


def asked_for_request(text: str) -> bool:
    """The answer asks what to do instead of reporting on a run (a reply recorded on 2026-09-15)."""
    return bool(_NO_REQUEST.search(text or ""))


def result_text(stdout, json_output=None) -> str:
    """The routine's answer: the `result` of `--output-format json`, else stdout as it is."""
    data = json_output if json_output is not None else parse_json_output(stdout)
    if isinstance(data, dict) and isinstance(data.get("result"), str):
        return data["result"]
    return stdout or ""


def check_contract(contract, stdout, json_output=None, sends=None) -> list:
    """What the run fails of its contract, one line each. Names only the contract's own markers
    and addresses, never a piece of the output.

    `sends` are the send-log records of this attempt's run id (sends_for_run). When anything is
    unmet and the answer asks for a request, a first line says the routine was not run at all,
    so the alert reads as what happened rather than as a missing marker.
    """
    if contract is None:
        return []
    text = result_text(stdout, json_output)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    unmet = []
    if contract.final_line and (not lines or lines[-1] != contract.final_line):
        unmet.append("the last line is not %s" % contract.final_line)
    unmet += ['required marker "%s" is missing' % m for m in contract.required if m not in text]
    unmet += ['forbidden marker "%s" is present' % m for m in contract.forbidden if m in text]
    if contract.required_sends:
        to = (contract.sends_to or "").strip().lower()
        found = [s for s in sends or () if isinstance(s, dict)
                 and (not to or str(s.get("to") or "").strip().lower() == to)]
        if len(found) < contract.required_sends:
            unmet.append("%d delivered email(s)%s required, %d recorded for this run in %s "
                         "(google.py send writes it when Gmail accepts the message)"
                         % (contract.required_sends, " to %s" % contract.sends_to if contract.sends_to else "",
                            len(found), SEND_LOG_NAME))
    if unmet and asked_for_request(text):
        unmet.insert(0, "the agent did not run the routine: its answer asks for a request instead of "
                        "executing the procedure")
    return unmet


def failure_summary(kind: str, detail: str, entry, until=None) -> str:
    """One line for the routine's alert: what happened, whose problem it is, what to do.

    Never carries a token value: `detail` is already a shape, a redacted line or an
    adapter's message, and `entry` holds only references.
    """
    who = "the routine token"
    if entry is not None:
        who = "token %s%s" % (entry.label, " (account %s)" % entry.account if entry.account else "")
    if kind == AUTH_INVALID:
        return "%s was refused as invalid (%s). Renew it: %s" % (
            who, detail or "401", renew_command(entry.kp_ref) if entry else "claude setup-token")
    if kind == TOKEN_MALFORMED:
        ref = entry.kp_ref if entry else "the pool entry"
        return "the value stored at %s for %s is not a single %s token (%s). Re-store it with: %s" % (
            ref, who, TOKEN_PREFIX, detail, restore_command(ref) if entry else "kp.py set <entry> --stdin")
    if kind == USAGE_LIMIT:
        return "%s hit a usage limit (unverified pattern: %s); it rests until %s" % (who, detail, until or "its backoff ends")
    if kind == CREDIT_EXHAUSTED:
        return "%s is out of credit (unverified pattern: %s); it rests until %s" % (who, detail, until or "its backoff ends")
    if kind == NETWORK:
        return "network failure reaching the API with %s (unverified pattern: %s)" % (who, detail)
    if kind == TIMEOUT:
        return "the run timed out with %s (%s)" % (who, detail)
    if kind == CLI_MISSING:
        return "the CLI cannot run routines: %s" % detail
    if kind in (KEEPASS_LOCKED, KEEPASS_UNAVAILABLE):
        return "KeePass, not the token: %s" % detail
    if kind == CONFIG:
        return "the token pool config 90-Meta/routine-tokens.json is invalid: %s" % detail
    if kind == NO_TOKEN:
        return "no usable routine token: every token in the pool is resting after a limit, the first until %s" % (
            until or "unknown")
    if kind == CONTRACT_BREACH:
        return ("the run exited 0 but did not meet its success contract (%s); its redacted output is in "
                "<brain state>/logs/routine-auth.log" % detail)
    if kind == UNKNOWN:
        return ("unrecognised failure with %s (%s); its redacted raw output is in <brain state>/logs/routine-auth.log "
                "for calibration" % (who, detail))
    return "%s: %s" % (kind, detail)
