#!/usr/bin/env python3
"""The claim rules, with no filesystem, no clock and no git.

claims_sync.py keeps one small JSON record per (resource, machine, session) under
`<shared>/claims/<resource>/<machine>__<sid>.json` on a shared filesystem path the user
configures — Dropbox, iCloud, a NAS, a synced folder; never S3, which this repo does not use.
A resource is repo-independent: the same file checked out on two machines, or in a worktree
with a different local path, resolves to the same `<host>/<org>/<repo>/<relative path>`, so one
machine can tell another "I am editing this" regardless of where each of them cloned it.

What a resource string looks like, what a record holds, what one sync pass must write and
delete, which of the OTHER machines' claims are worth a warning, and which records are old
enough to reap are decided here. Callers pass the clock in and resolve git themselves
(claims_sync.py shells out to `git remote get-url origin` / `rev-parse --show-toplevel`, not
this module). See claims_core_test.py.
"""
import json
import re

SUFFIX = ".json"
SEP = "__"

_SSH_SCP = re.compile(r"^[\w.-]+@([\w.-]+):(.+)$")
_SSH_URL = re.compile(r"^ssh://(?:[\w.-]+@)?([\w.-]+)(?::\d+)?/(.+)$")
_HTTP_URL = re.compile(r"^https?://(?:[^@/]+@)?([\w.-]+)(?::\d+)?/(.+)$")


def normalize_remote(url):
    """A git remote URL -> `<host>/<org>/<repo>`, `.git` and slashes trimmed.

    Handles the shapes git itself accepts: the scp-like ssh form (`git@host:org/repo.git`),
    `ssh://` and `http(s)://`, with or without a userinfo or port. "" when the URL does not
    parse as one of those: a path with no recognisable remote shares no resource.
    """
    u = (url or "").strip()
    if not u:
        return ""
    m = _SSH_URL.match(u) or _HTTP_URL.match(u) or _SSH_SCP.match(u)
    if not m:
        return ""
    host, path = m.group(1), m.group(2).strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not host or not path:
        return ""
    return "%s/%s" % (host, path)


def resource_for(origin, rel_path):
    """`<normalized origin>/<repo-relative path>`, or "" when there is no usable origin.

    `origin` and `rel_path` are already resolved by the caller (claims_sync.py: `git remote
    get-url origin`, `rev-parse --show-toplevel`, then `os.path.relpath`). A path outside any
    repo, or inside one with no configured origin, resolves to "": nothing is shared for it.
    """
    norm = normalize_remote(origin)
    if not norm:
        return ""
    rel = (rel_path or "").strip().replace("\\", "/").strip("/")
    return "%s/%s" % (norm, rel) if rel else norm


def _segment(value, empty="-"):
    text = str(value or "").replace("/", "_").replace("\\", "_").replace("\0", "").strip()
    return text.lstrip(".") or empty


def filename(machine, sid):
    """`<machine>__<sid>.json`: one record per machine and session for a resource.

    The machine segment has any `__` of its own collapsed first, the same way
    presence_core.key does: parse_record_name's partition takes the FIRST separator, so a
    machine name that could contain one would otherwise shift the sid.
    """
    return "%s%s%s%s" % (_segment(machine, "?").replace(SEP, "_"), SEP, _segment(sid), SUFFIX)


def parse_record_name(name):
    """(machine, sid) from a claim file's own name (no directory part), or None."""
    name = name or ""
    if not name.endswith(SUFFIX):
        return None
    machine, sep, sid = name[:-len(SUFFIX)].partition(SEP)
    if not sep or not machine or not sid:
        return None
    return machine, sid


def parse_resource_path(rel):
    """(resource, machine, sid) from a claim record's path under the claims directory, or None.

    The resource itself may hold several path components (`host/org/repo/deep/file.ts`), so
    only the LAST component is the record's own file name; everything before it is the resource.
    """
    rel = (rel or "").replace("\\", "/")
    if "/" not in rel:
        return None
    resource, name = rel.rsplit("/", 1)
    parsed = parse_record_name(name)
    if not resource or not parsed:
        return None
    return (resource,) + parsed


def record(machine, sid, now):
    return {"machine": machine, "sid": sid, "at": now}


def dumps(rec):
    return json.dumps(rec, ensure_ascii=False)


def parse(text):
    """A record from the file's text, or None when it is absent or not a valid record."""
    try:
        rec = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(rec, dict):
        return None
    at = rec.get("at")
    if not isinstance(rec.get("machine"), str) or not isinstance(rec.get("sid"), str):
        return None
    if isinstance(at, bool) or not isinstance(at, (int, float)):
        return None
    return {"machine": rec["machine"], "sid": rec["sid"], "at": at}


def plan(local, remote, machine, sid, now, ttl):
    """(to_put, to_delete): what one sync pass for THIS (machine, sid) must write and remove,
    as resource strings.

    `local` is the set of resources THIS SESSION wants claimed right now. `remote` is every
    claim record found on the shared path (claims_sync.scan()): dicts carrying at least
    resource/machine/sid/at. `sid` is the one session performing this pass — a sync pass
    always belongs to a single session, never a mix.

    A local claim already on the remote, fresh (`at` within `ttl`) and still wanted is left
    alone — no need to touch the shared path every sync pass. One that has gone stale is
    republished, which is what turns the periodic sync into a renewal and keeps an
    actively-held claim from ever reaching the reaper's `ttl + margin`.

    Only records for THIS EXACT (machine, sid) are ever proposed for deletion: matching on
    `machine` alone would let one session's sync pass release a claim a DIFFERENT session on
    the same machine is actively holding — two concurrent sessions on one machine are the
    norm here, not the exception. Another machine's claim, or another session's, is never put
    or deleted here.
    """
    local = set(local)
    mine = {r["resource"]: r for r in remote
            if r.get("machine") == machine and r.get("sid") == sid and "resource" in r}
    to_put = [resource for resource in local
              if resource not in mine or now - (mine[resource].get("at") or 0) > ttl]
    to_delete = [resource for resource in mine if resource not in local]
    return to_put, to_delete


def foreign_claims(remote, machine, now, ttl):
    """Fresh claims held by machines other than `machine`, each with its age — for warning."""
    out = []
    for r in remote:
        if r.get("machine") == machine:
            continue
        try:
            age = now - float(r.get("at") or 0)
        except (TypeError, ValueError):
            continue
        if age <= ttl:
            row = dict(r)
            row["age"] = round(age, 1)
            out.append(row)
    return out


def purgeable(remote, now, ttl, margin):
    """Keys of claim records old enough to reap: at or past `ttl + margin`.

    No claim still being renewed by `plan()` ever reaches this age; one that does belongs to a
    session that never withdrew (crashed, or the machine vanished).
    """
    out = []
    for r in remote:
        try:
            age = now - float(r.get("at") or 0)
        except (TypeError, ValueError):
            continue
        if age >= ttl + margin:
            key = r.get("key")
            if key:
                out.append(key)
    return out
