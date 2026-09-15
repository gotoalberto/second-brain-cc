#!/usr/bin/env python3
"""The presence rules, with no filesystem and no clock.

presence.py keeps one empty file per live session at <state>/presence/<project>/<machine>__<sid>
and reads the names and mtimes back. Everything that decides from those names and times lives
here: how a key is built and parsed, how old a heartbeat is, who is alive, what gets purged,
when a beat is due and when the cache is too old to trust. Callers pass the clock in. See
presence_core_test.py.
"""

SEP = "__"


def segment(value, empty="-"):
    """One path component: no directory separators, no leading dots, never empty.

    Project names come from a cwd and sids from hook input, so neither may add a directory
    level or climb out of the presence directory.
    """
    text = str(value or "").replace("/", "_").replace("\\", "_").replace("\0", "").strip()
    return text.lstrip(".") or empty


def key(project, machine, sid):
    """`<project>/<machine>__<sid>`, relative to the presence directory."""
    return "%s/%s%s%s" % (segment(project), segment(machine, "?").replace(SEP, "_"), SEP, segment(sid))


def parse_key(rel):
    """(project, machine, sid) from a key, or None when it is not one."""
    parts = str(rel or "").split("/")
    if len(parts) != 2:
        return None
    project, who = parts
    machine, sep, sid = who.partition(SEP)
    if not project or not sep or not machine or not sid:
        return None
    return project, machine, sid


def rows(entries, now, ttl, own_sid=None):
    """Split (key, mtime) pairs into alive and expired sessions.

    A heartbeat at most `ttl` seconds old is alive. `own_sid` is left out of the alive list
    (nobody needs warning about themselves) but kept among the expired, so it can be purged.
    """
    alive, expired = [], []
    for rel, stamp in entries:
        parsed = parse_key(rel)
        if not parsed:
            continue
        try:
            age = now - float(stamp)
        except (TypeError, ValueError):
            continue
        project, machine, sid = parsed
        row = {"machine": machine, "sid": sid, "project": project, "age": round(age, 1), "key": rel}
        (alive if age <= ttl else expired).append(row)
    return {"alive": [r for r in alive if r["sid"] != own_sid], "expired": expired, "read_at": now}


def purgeable(expired, ttl, factor=4):
    """Keys of heartbeats gone long enough to remove: older than `factor` TTLs."""
    return [r["key"] for r in expired if (r.get("age") or 0) > ttl * factor]


def beat_due(last_attempt, now, every):
    """True when no beat was attempted in the last `every` seconds. None means never."""
    return last_attempt is None or now - last_attempt >= every


def cache_view(data, now, ttl):
    """The cached reading, or {} when it is older than `ttl`: better to say nothing than to lie."""
    if not isinstance(data, dict) or now - (data.get("read_at") or 0) > ttl:
        return {}
    return data
