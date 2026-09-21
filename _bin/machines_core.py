#!/usr/bin/env python3
"""The machine registry's rules, with no filesystem, no clock and no subprocess.

machines.py keeps one small JSON file per machine that runs Brain and reads them back. What a
record holds, how `claude auth status` is read, how a new registration merges into the record
already there, when two records describe one machine and how the list is shown are decided
here. Dates are passed in as ISO strings. See machines_core_test.py.

A record never carries the full hardware uuid, only its 8-hex fragment (`id8`), the same fragment
`machine_identity.machine_key()` already puts in the key. That fragment is what tells one machine
under two hostnames apart from two machines under one hostname.
"""
import datetime as dt
import json

FIELDS = ("key", "id8", "label", "os", "user", "claude_account", "claude_org", "first_seen", "last_seen")
# What describes the machine: a change in any of these is written the same day.
DESCRIBING = ("key", "id8", "label", "os", "user", "claude_account", "claude_org")
UNKNOWN_ACCOUNT = "unknown"
STALE_DAYS = 14


def parse_claude_auth(stdout):
    """(account, org) from `claude auth status` output, or (UNKNOWN_ACCOUNT, "").

    A machine whose CLI cannot be asked (not on PATH, too old for the command, output that is
    not JSON) still belongs in the registry: it answers `unknown`. A CLI that answers and is
    signed out says `logged out`.
    """
    try:
        data = json.loads(stdout or "")
    except ValueError:
        return UNKNOWN_ACCOUNT, ""
    if not isinstance(data, dict):
        return UNKNOWN_ACCOUNT, ""
    if not data.get("loggedIn"):
        return "logged out", ""
    return str(data.get("email") or UNKNOWN_ACCOUNT), str(data.get("orgName") or "")


def parse(text):
    """A record from a file's text: a JSON object with a non-empty `key`, else None.

    Only the known fields are kept, as strings; a missing one reads as "".
    """
    try:
        data = json.loads(text or "")
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("key"), str) or not data["key"].strip():
        return None
    return {f: str(data.get(f) or "") for f in FIELDS}


def dump(record):
    """The file text for a record: one JSON object, fields in a fixed order."""
    return json.dumps({f: record.get(f, "") for f in FIELDS}, ensure_ascii=False, indent=1) + "\n"


def filename(key):
    """`<key>.json`, one path component: no separators, no leading dots, never empty."""
    text = str(key or "").replace("/", "_").replace("\\", "_").replace("\0", "").strip().lstrip(".")
    return (text or "machine") + ".json"


def merge(existing, info, today, first_seen=""):
    """(record, changed): `info` registered on `today` over the `existing` record (or None).

    `first_seen` survives every refresh, and one carried over from an older record of this
    machine (see first_seen_elsewhere) wins over today. A probe that could not answer does not
    erase the account the machine already reported: otherwise a CLI missing from a scheduler's
    PATH would flip the account to `unknown` and back on every pass. The record is rewritten
    when something describing the machine changed, or once a day for `last_seen`.
    """
    new = {f: str(info.get(f) or "") for f in DESCRIBING}
    if existing:
        if new["claude_account"] == UNKNOWN_ACCOUNT and existing.get("claude_account"):
            new["claude_account"] = existing["claude_account"]
            new["claude_org"] = existing.get("claude_org", "")
        new["first_seen"] = existing.get("first_seen") or first_seen or today
    else:
        new["first_seen"] = first_seen or today
    new["last_seen"] = today
    if existing:
        same = all(str(existing.get(f, "")) == new[f] for f in DESCRIBING)
        if same and existing.get("last_seen") == today:
            return dict(existing), False
    return new, True


def same_machine(a, b):
    """Whether two records describe one machine.

    The uuid fragment settles it when both carry one. A machine with no readable uuid is only
    ever recognised by its exact key: its hostname is all it has, and a hostname is shared.
    """
    fa, fb = a.get("id8") or "", b.get("id8") or ""
    if fa or fb:
        return bool(fa) and fa == fb
    return bool(a.get("key")) and a.get("key") == b.get("key")


def first_seen_elsewhere(records, info):
    """The earliest `first_seen` among older records of the machine `info` describes, or "".

    A rename changes the key and so the file name; without this the machine would claim it was
    installed today. The older record is left where it is: nothing here deletes.
    """
    best = ""
    for rec in records:
        if rec.get("key") == info.get("key") or not same_machine(rec, info):
            continue
        seen = rec.get("first_seen") or ""
        if seen and (not best or seen < best):
            best = seen
    return best


def dedupe(records):
    """One entry per machine, most recently seen first: {"entry": newest record, "aliases": [older keys]}."""
    groups = []
    for rec in sorted(records, key=lambda r: r.get("last_seen") or "", reverse=True):
        for group in groups:
            if same_machine(group["entry"], rec):
                group["aliases"].append(rec["key"])
                break
        else:
            groups.append({"entry": rec, "aliases": []})
    return groups


def days_since(last_seen, today):
    """Whole days from `last_seen` to `today` (both ISO dates), or None when either is unreadable."""
    try:
        return (dt.date.fromisoformat(str(today)[:10]) - dt.date.fromisoformat(str(last_seen)[:10])).days
    except ValueError:
        return None


def render_list(machines, is_mine, today):
    """The registry as `machines.py list` prints it. `is_mine(key)` stars this machine."""
    if not machines:
        return "no machine has registered yet: run `python3 _bin/machines.py register` on each one"
    lines = []
    for m in machines:
        e = m["entry"]
        days = days_since(e.get("last_seen"), today)
        stale = "  (not seen in %d days)" % days if days is not None and days > STALE_DAYS else ""
        lines.append("%s %-32s last seen %s%s" % ("*" if is_mine(e["key"]) else " ", e["key"],
                                                  e.get("last_seen") or "?", stale))
        lines.append("    %s, user %s, claude account %s%s"
                     % (e.get("os") or "?", e.get("user") or "?", e.get("claude_account") or "unrecorded",
                        " (%s)" % e["claude_org"] if e.get("claude_org") else ""))
        if m["aliases"]:
            lines.append("    also registered as " + ", ".join(m["aliases"]))
    total = sum(1 + len(m["aliases"]) for m in machines)
    lines.append("")
    lines.append("%d machine(s), %d record(s)." % (len(machines), total))
    return "\n".join(lines)
