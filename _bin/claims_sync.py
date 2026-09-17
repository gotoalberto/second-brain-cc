#!/usr/bin/env python3
"""Cross-machine file claims, over a shared filesystem path — not S3.

A second machine sharing this vault (a Dropbox, iCloud or NAS folder configured through
brain_shared.py) can warn "someone is already editing this" for a file that exists in more
than one checkout of the same repo — a second machine, or a worktree with a different local
path. The resource a file maps to is repo-independent: `claims_core.resource_for()` turns a
path into `<host>/<org>/<repo>/<relative path>`, resolved here from `git remote get-url
origin` and `git rev-parse --show-toplevel` (claims_core itself never shells out).

One small JSON record per (resource, machine, session) lives at
`<shared>/claims/<resource>/<machine>__<sid>.json`, guarded by B.flock the same way
lease.py and presence.py guard their own files. `machine_identity.current_key()` is used
instead of bare hostname, so two machines that happen to share one do not collide.

This iteration is **informational only**: nothing here is wired into claim.py's local
SQLite table or gate_write.py's conflict check (see the plan's "what is NOT touched"). A
claim is published or withdrawn explicitly, through this module's own CLI; nobody publishes
one on your behalf.

`sync()` is deliberately safe to call with no known local claims: passing `paths=None` runs
a read-only refresh (rescans the shared path and rewrites the local cache) with no publish or
withdraw. Calling `claims_core.plan()` with an EMPTY local set would read as "release
everything of mine", which is exactly wrong for a periodic housekeeping pass that knows
nothing about what this session currently claims — `None` is not the same as "nothing", and
this module keeps that distinction. `reap()` and this refresh are what presence.py's existing
120 s `should_beat()` cadence calls (see presence.py); actually declaring or releasing a claim
for a specific file is a deliberate call with a real `paths` list, from this module's CLI.

Everything here fails open: with nothing configured, with the shared path unreachable, or
with the sync lock held elsewhere, nothing is written and nothing raises. See
claims_sync_test.py.
"""
import os, sys, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B
import brain_paths
import brain_shared
import claims_core as C
import machine_identity as M

CLAIMS_SUBDIR = "claims"
CACHE = os.path.join(B.STATE, "claims-cache.json")
SYNC_LOCK = os.path.join(brain_paths.effective_state_dir(), "claims-sync.lock")
SYNC_LOCK_TIMEOUT = 30.0

TTL = 900.0                # a claim not renewed in 15 min is stale (but not yet reaped)
REAP_MARGIN = 120.0        # 2x the private Brain's own 60 s cushion: there is no S3 expiry here

_machine = M.current_key


def configured(environ=None, home=None, config_path=None):
    return brain_shared.configured(environ, home, config_path)


def _root():
    shared = brain_shared.shared_dir()
    return os.path.join(shared, CLAIMS_SUBDIR) if shared else None


def _origin(root):
    code, out, _err = B.run([B.GIT, "-C", root, "remote", "get-url", "origin"], timeout=5)
    return out if code == 0 else ""


def resource_for(path):
    """The resource a file maps to, or "" when it is outside any repo or that repo has no
    origin configured. Real git calls live here; claims_core.resource_for does the naming.

    Both sides go through realpath before the relpath: `git rev-parse --show-toplevel`
    resolves symlinks in the path it is given (macOS resolves /tmp to /private/tmp, for
    instance), and comparing that against an unresolved `path` produced a relative path that
    climbed back OUT of the repo instead of naming a file inside it.
    """
    full = os.path.realpath(os.path.abspath(path))
    cwd = full if os.path.isdir(full) else os.path.dirname(full)
    root = B.repo_root(cwd)
    if not root:
        return ""
    return C.resource_for(_origin(root), os.path.relpath(full, os.path.realpath(root)))


def _record_path(resource, machine, sid):
    root = _root()
    if not root or not resource:
        return None
    return os.path.join(root, *resource.split("/"), C.filename(machine, sid))


def publish(resource, machine, sid, now=None):
    """Write (or renew) this machine's claim record for a resource. B.flock-guarded, same as
    presence.py's own beat. (False, reason) when it cannot: nothing configured, or the lock
    was busy — never raises."""
    path = _record_path(resource, machine, sid)
    if not path:
        return False, "multi-machine coordination is not configured"
    now = time.time() if now is None else now
    try:
        with B.flock(path) as lk:
            if not lk.held:
                return False, "lock busy"
            os.makedirs(os.path.dirname(path), exist_ok=True)
            B.atomic_write(path, C.dumps(C.record(machine, sid, now)))
        return True, ""
    except OSError as e:
        return False, repr(e)


def withdraw(resource, machine, sid):
    path = _record_path(resource, machine, sid)
    if not path:
        return False
    try:
        with B.flock(path):
            os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return True


def _entries(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if not fn.endswith(".json"):
                continue
            full = os.path.join(dirpath, fn)
            try:
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                out.append((rel, os.stat(full, follow_symlinks=False).st_mtime))
            except OSError:
                continue          # withdrawn while we were looking
    return out


def scan():
    """Every claim record on the shared path right now: [{resource, machine, sid, at, key}].
    A missing claims directory (nothing published yet) is nobody, not an error."""
    root = _root()
    if not root:
        return []
    try:
        entries = _entries(root)
    except OSError:
        return []
    rows = []
    for rel, mtime in entries:
        parsed = C.parse_resource_path(rel)
        if not parsed:
            continue
        resource, machine, sid = parsed
        rows.append({"resource": resource, "machine": machine, "sid": sid, "at": mtime, "key": rel})
    return rows


def cache_read():
    """What a fast, filesystem-free caller consults: an open(), never raises."""
    try:
        with open(CACHE) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def cache_write(rows):
    try:
        os.makedirs(B.STATE, exist_ok=True)
        B.atomic_write(CACHE, json.dumps({"rows": rows, "read_at": time.time()}, ensure_ascii=False))
    except Exception as e:
        B.log_error("claims_sync.cache_write", e)


def sync(sid, paths=None, now=None, ttl=TTL):
    """One sync pass. `paths=None` (the default) only rescans the shared path and refreshes
    the local cache — nothing is published or withdrawn. Passed a list of this session's
    currently-claimed file paths (possibly empty, meaning "release everything"), it publishes
    the new or stale ones and withdraws the ones no longer in the list, computed by
    claims_core.plan(). Either way it is serialised by a 30 s flock on <state>/claims-sync.lock,
    so a release and a renewal from this machine can never race and resurrect a stolen claim.
    (True, "") on success; (False, reason) when unconfigured or the lock was busy — never
    raises."""
    if not configured():
        return False, "multi-machine coordination is not configured"
    now = time.time() if now is None else now
    machine = _machine()
    try:
        with B.flock(SYNC_LOCK, timeout=SYNC_LOCK_TIMEOUT) as lk:
            if not lk.held:
                B.log("claims_sync", "lock-busy")
                return False, "lock busy"
            remote = scan()
            if paths is not None:
                local = {r for r in (resource_for(p) for p in paths) if r}
                to_put, to_delete = C.plan(local, remote, machine, sid, now, ttl)
                for resource in to_put:
                    publish(resource, machine, sid, now)
                for resource in to_delete:
                    withdraw(resource, machine, sid)
                remote = scan() if (to_put or to_delete) else remote
    except OSError as e:
        B.log("claims_sync", "sync-fails", err=repr(e)[:200])
        return False, repr(e)
    cache_write(remote)
    return True, ""


def reap(now=None, ttl=TTL, margin=REAP_MARGIN):
    """Remove remote claim records nobody is renewing any more: at or past ttl + margin.
    No claim `sync()` keeps renewing ever reaches this age; one that does belongs to a session
    that never withdrew (crashed, or its machine is gone)."""
    root = _root()
    if not root:
        return 0
    now = time.time() if now is None else now
    n = 0
    for key in C.purgeable(scan(), now, ttl, margin):
        path = os.path.join(root, *key.split("/"))
        try:
            with B.flock(path) as lk:
                if not lk.held:
                    continue
                try:
                    age = now - os.path.getmtime(path)
                except OSError:
                    continue                    # already gone
                if age >= ttl + margin:
                    os.remove(path)
                    n += 1
        except OSError:
            continue
    return n


def foreign_view(ttl=TTL):
    """Fresh claims held by other machines right now — what a warning would show."""
    return C.foreign_claims(scan(), _machine(), time.time(), ttl)


def main():
    import argparse
    p = argparse.ArgumentParser(prog="claims_sync")
    p.add_argument("action", choices=["claim", "release", "reap", "view"])
    p.add_argument("path", nargs="*")
    p.add_argument("--sid", default="")
    a = p.parse_args()

    if a.action == "view":
        print(json.dumps(foreign_view(), ensure_ascii=False, indent=1))
        return 0
    if a.action == "reap":
        n = reap()
        B.log("claims_sync", "reap", n=n)
        print("%d claim(s) reaped" % n)
        return 0
    if not a.sid or not a.path:
        sys.stderr.write("claims_sync: %s needs --sid and at least one path\n" % a.action)
        return 2
    if not configured():
        print("failed: multi-machine coordination is not configured")
        return 1
    if a.action == "release":
        # A direct withdraw of exactly the paths named — sync()'s local set is the whole
        # desired state, and passing only the ones to release would read as "nothing else
        # is claimed any more" and drop every other claim this session holds.
        machine = _machine()
        for path in a.path:
            resource = resource_for(path)
            if resource:
                withdraw(resource, machine, a.sid)
        print("ok")
        return 0
    ok, err = sync(a.sid, a.path)
    if not ok:
        B.log("claims_sync", a.action + "-fails", err=err[:150])
        print("failed: %s" % err)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
