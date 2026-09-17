#!/usr/bin/env python3
"""Tests for claims_sync — cross-machine file claims, run as a subprocess CLI in a scratch
world: a temporary directory standing in for the shared path (Dropbox, iCloud, a NAS — never
touched here; never S3) and a throwaway `git init` repository for resource_for(). Every
subprocess gets BRAIN_MACHINE_KEY forced to an obviously fake key
(machine_identity.current_key()'s test override), so this never reads or writes this
machine's real hostname or hardware uuid. Run standalone:

    python3 _bin/claims_sync_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "claims_sync.py")
sys.path.insert(0, HERE)

import claims_core as C          # noqa: E402  pure: safe to import directly

FAKE_MACHINE = "laptop-a1b2c3d4"

ok, fail = [], []
TMP = []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def tmpdir():
    d = tempfile.mkdtemp(prefix="claims-sync-test-")
    TMP.append(d)
    return d


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    return path


def run_git(argv, cwd, env):
    return subprocess.run(["git"] + argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=30)


def main():
    root = tmpdir()
    try:
        home, state, shared = (os.path.join(root, n) for n in ("home", "state", "shared"))
        os.makedirs(home)
        base = {k: v for k, v in os.environ.items() if not k.startswith("BRAIN_")}
        base.update(HOME=home, BRAIN_STATE=state, BRAIN_MACHINE_KEY=FAKE_MACHINE, PYTHONDONTWRITEBYTECODE="1")
        # Applied to THIS process's own environ too, and before brainlib is ever imported here:
        # the one in-process check below (the sync lock) uses B.flock directly, and it must
        # resolve the very same scratch state directory the subprocess CLI calls use, never
        # this machine's real one.
        for k in list(os.environ):
            if k.startswith("BRAIN_"):
                del os.environ[k]
        os.environ.update(HOME=home, BRAIN_STATE=state, BRAIN_MACHINE_KEY=FAKE_MACHINE)

        def run(*args, **env_over):
            e = dict(base, **env_over)
            p = subprocess.run([sys.executable, CLI] + list(args), env=e, cwd=root, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=60)
            return p.returncode, p.stdout, p.stderr

        # A throwaway repo with a real origin, so resource_for() has something to resolve.
        repo = os.path.join(root, "repo")
        os.makedirs(repo)
        gcfg = write(os.path.join(root, "gitconfig"), "[user]\n\tname = t\n\temail = t@example.com\n")
        genv = dict(base, GIT_CONFIG_GLOBAL=gcfg, GIT_CONFIG_NOSYSTEM="1")
        run_git(["init", "-q", "-b", "main"], repo, genv)
        run_git(["remote", "add", "origin", "git@github.com:example-org/example-repo.git"], repo, genv)
        tracked = write(os.path.join(repo, "src", "x.ts"), "// fixture\n")
        run_git(["add", "src/x.ts"], repo, genv)
        run_git(["commit", "-qm", "base", "--no-verify"], repo, genv)
        resource = "github.com/example-org/example-repo/src/x.ts"

        machine = FAKE_MACHINE             # forced above via BRAIN_MACHINE_KEY; never the real one
        claims_root = os.path.join(shared, "claims")

        def record_path(res, sid, mach=machine):
            return os.path.join(claims_root, *res.split("/"), C.filename(mach, sid))

        def write_record(res, mach, sid, at):
            p = record_path(res, sid, mach)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as fh:
                fh.write(C.dumps(C.record(mach, sid, at)))
            os.utime(p, (at, at))
            return p

        print("\n== unconfigured (no BRAIN_SHARED_DIR) ==")
        rc, out, err = run("view")
        check("view with nothing configured reads as nobody, not an error", rc == 0 and out.strip() == "[]", (rc, out, err))
        rc, out, err = run("reap")
        check("reap with nothing configured does nothing", rc == 0 and "0 claim" in out, (rc, out, err))
        rc, out, err = run("claim", tracked, "--sid", "sess0001")
        check("claim with nothing configured fails clearly, writes nothing",
              rc == 1 and "not configured" in out and not os.path.isdir(shared), (rc, out, err))

        print("\n== claim, scan (via view/on-disk), release ==")
        rc, out, err = run("claim", tracked, "--sid", "sess0001", BRAIN_SHARED_DIR=shared)
        check("claim exits ok", rc == 0 and out.strip() == "ok", (rc, out, err))
        p = record_path(resource, "sess0001")
        check("the claim lands at <shared>/claims/<host>/<org>/<repo>/<relative path>/<machine>__<sid>.json",
              os.path.isfile(p), (p, os.path.isdir(claims_root) and list(os.walk(claims_root))))
        rec = C.parse(open(p).read())
        check("the record holds this machine and session",
              rec is not None and rec["machine"] == machine and rec["sid"] == "sess0001", rec)

        rc, out, err = run("claim", tracked, "--sid", "sess0001", BRAIN_SHARED_DIR=shared)
        all_files = [fn for _dp, _dn, fns in os.walk(claims_root) for fn in fns]
        check("claiming the same file again renews it in place, no second file",
              rc == 0 and os.path.isfile(p) and all_files == [os.path.basename(p)], (rc, out, err, all_files))

        rc, out, err = run("release", tracked, "--sid", "sess0001", BRAIN_SHARED_DIR=shared)
        check("release removes it", rc == 0 and not os.path.exists(p), (rc, out, err))
        rc, out, err = run("release", tracked, "--sid", "sess0001", BRAIN_SHARED_DIR=shared)
        check("releasing something absent is not an error", rc == 0, (rc, out, err))

        print("\n== a path outside any repo shares no resource ==")
        before = sorted(fn for _dp, _dn, fns in os.walk(shared) for fn in fns)
        outside = write(os.path.join(root, "not-a-repo.ts"), "x")
        rc, out, err = run("claim", outside, "--sid", "sess0001", BRAIN_SHARED_DIR=shared)
        after = sorted(fn for _dp, _dn, fns in os.walk(shared) for fn in fns)
        check("claim on a file outside any repo succeeds but publishes nothing",
              rc == 0 and out.strip() == "ok" and before == after, (rc, out, err, before, after))

        print("\n== claim declares the whole desired set: what is dropped gets released ==")
        # sync()'s local set is built from real paths via resource_for(); only `tracked` resolves
        # to a real resource in this fixture (`resource`), so a `claim tracked` call declares
        # exactly {resource} as wanted. Everything else pre-seeded for this session is not in
        # that set and must be released; a claim under a different session or machine must not be.
        released_res = resource + "-drop"
        released = write_record(released_res, machine, "sess0002", time.time() - 10)
        other_session = write_record(resource + "-other-sid", machine, "sess-not-0002", time.time() - 10)
        foreign_machine = machine + "-other"     # still an obviously-fake key, just a different one
        foreign = write_record(resource + "-foreign", foreign_machine, "sess0003", time.time() - 10)
        rc, out, err = run("claim", tracked, "--sid", "sess0002", BRAIN_SHARED_DIR=shared)
        check("claim exits ok", rc == 0, (rc, out, err))
        check("the newly wanted resource is published", os.path.isfile(record_path(resource, "sess0002")))
        check("a claim of mine, this session, not named in this pass, is released",
              not os.path.exists(released), released)
        check("a claim of mine under a DIFFERENT session is not this session's to release",
              os.path.exists(other_session), other_session)
        check("another machine's claim is never touched by my claim", os.path.exists(foreign), foreign)

        print("\n== the sync lock fails open ==")
        import brainlib as B
        lock_path = os.path.join(state, "claims-sync.lock")
        with B.flock(lock_path, timeout=0.2) as lk:
            check("the lock is actually held by this test", lk.held, lk)
            rc, out, err = run("claim", tracked, "--sid", "sess0004", BRAIN_SHARED_DIR=shared)
            check("a claim while the lock is held fails instead of hanging or raising",
                  rc == 1 and "lock" in out, (rc, out, err))

        print("\n== reap() ==")
        old = write_record(resource + "-reap-old", machine, "sess0009", time.time() - 900.0 - 120.0 - 5)
        fresh = write_record(resource + "-reap-fresh", machine, "sess0009", time.time())
        rc, out, err = run("reap", BRAIN_SHARED_DIR=shared)
        check("reap exits ok and reports what it removed", rc == 0 and "claim" in out, (rc, out, err))
        check("a record past ttl + margin is removed", not os.path.exists(old), old)
        check("a fresh one survives", os.path.exists(fresh), fresh)

        print("\n== view() shows fresh foreign claims only ==")
        shutil.rmtree(claims_root, ignore_errors=True)
        write_record(resource + "-mine", machine, "sess0010", time.time() - 5)
        write_record(resource + "-friend", machine + "-b", "sess0011", time.time() - 5)
        write_record(resource + "-stale-friend", machine + "-b", "sess0012", time.time() - 900.0 - 1)
        rc, out, err = run("view", BRAIN_SHARED_DIR=shared)
        rows = json.loads(out)
        check("view exits ok with JSON", rc == 0, (rc, out, err))
        check("only a fresh claim from a DIFFERENT machine key is reported",
              [r["resource"] for r in rows] == [resource + "-friend"], rows)
    finally:
        for d in TMP:
            shutil.rmtree(d, ignore_errors=True)

    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
