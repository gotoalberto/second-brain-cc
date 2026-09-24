#!/usr/bin/env python3
"""Tests for the hook heartbeat (brainlib.heartbeat) and the offline switch the hook probe relies on.

Every hook here runs in a subprocess whose BRAIN_STATE, BRAIN_VAULT, HOME and TMPDIR are
temporary directories and whose BRAIN_OFFLINE is set, so nothing reaches the real Brain state,
the real vault, ~/.claude, KeePass or the network. In the offline-switch test anything that
would start a process is replaced by a recorder before it is called. Run standalone:

    python3 _bin/heartbeat_test.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok, fail = [], []
TMP = []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def tmpdir():
    d = tempfile.mkdtemp(prefix="brain-heartbeat-test-")
    TMP.append(d)
    return d


def scratch():
    root = tmpdir()
    paths = {n: os.path.join(root, n) for n in ("home", "state", "vault")}
    for p in paths.values():
        os.makedirs(p)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": paths["home"], "TMPDIR": root,
           "BRAIN_STATE": paths["state"], "BRAIN_VAULT": paths["vault"], "BRAIN_OFFLINE": "1",
           "PYTHONDONTWRITEBYTECODE": "1", "GIT_CEILING_DIRECTORIES": root}
    return root, env, paths


HOOK = r'''
import sys
sys.path.insert(0, %(bin)r)
import brainlib as B

MODE = sys.argv[1]


@B.heartbeat("session-start")
@B.fail_open
def main():
    if MODE != "noread":
        B.read_hook_input()
    if MODE == "raise":
        raise ValueError("boom")
    if MODE == "block":
        sys.exit(2)
    B.emit("SessionStart", "the context")


@B.heartbeat("sync")
def bare():
    B.read_hook_input()
    if MODE == "bare-raise":
        raise KeyError("x")
    return 1 if MODE == "bare-return-1" else 0


@B.heartbeat("sync")
def quiet():
    return 0


if __name__ == "__main__":
    if MODE.startswith("bare"):
        sys.exit(bare())
    main()
'''

IMPORTER = r'''
import sys
sys.path.insert(0, %(dir)r)
import hookmod
rc = hookmod.quiet()
print("rc=%%s stdin=%%s" %% (rc, sys.stdin.read()))
'''

OFFLINE = r'''
import json, subprocess, sys
sys.path.insert(0, %(bin)r)
calls = []


class Recorder:
    def __init__(self, *a, **kw):
        calls.append(" ".join(str(x) for x in (a[0] if a else kw.get("args", []))))


subprocess.Popen = Recorder
import brainlib as B
B.run = lambda cmd, *a, **kw: (calls.append(" ".join(str(x) for x in cmd)), (1, "", ""))[1]
B.presence_beat_async("aaaa1111", "proj")
B.presence_withdraw_async("aaaa1111", "proj")
B.lease_acquire_async("10-Projects/x.md", "aaaa1111")
B.lease_release_async("10-Projects/x.md", "aaaa1111")
import retrieve
retrieve.maybe_pull()
retrieve.maybe_reindex()
import linkfix
spawned = linkfix.maybe_spawn({"fix": [("a", "b")], "broken": [("c", "d")]})
print(json.dumps({"offline": getattr(B, "OFFLINE", None), "calls": calls, "spawned": spawned}))
'''

PAYLOAD = {"session_id": "3ac18522-ed92-4c1a-9d0e-000000000001", "hook_event_name": "SessionStart",
           "cwd": "/nonexistent", "source": "startup"}


def run(script, args, env, payload=None, timeout=60):
    kw = dict(input=json.dumps(payload)) if payload is not None else dict(stdin=subprocess.DEVNULL)
    return subprocess.run([sys.executable, script] + list(args), env=env, capture_output=True, text=True,
                          timeout=timeout, **kw)


def beats(paths):
    p = os.path.join(paths["state"], "logs", "heartbeat.jsonl")
    try:
        with open(p, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except (OSError, ValueError):
        return []


def test_heartbeat():
    print("\n== brainlib.heartbeat ==")
    root, env, paths = scratch()
    script = os.path.join(root, "hookmod.py")
    with open(script, "w") as fh:
        fh.write(HOOK % {"bin": HERE})

    p = run(script, ["read"], env, PAYLOAD)
    b = beats(paths)
    check("a hook run records one heartbeat line", len(b) == 1, (p.returncode, p.stderr[-400:], b))
    h = b[-1] if b else {}
    check("with the registry event id, the short session id and ok",
          h.get("event") == "session-start" and h.get("sid") == "3ac18522" and h.get("status") == "ok"
          and h.get("exit") == 0, h)
    check("with the Claude Code hook event, a duration in ms and a timestamp",
          h.get("hook_event") == "SessionStart" and isinstance(h.get("ms"), int) and h.get("ms", -1) >= 0
          and isinstance(h.get("ts"), (int, float)), h)
    out = json.loads(p.stdout) if p.stdout.strip().startswith("{") else {}
    check("and the hook's own output and exit are untouched",
          p.returncode == 0 and (out.get("hookSpecificOutput") or {}).get("additionalContext") == "the context",
          (p.returncode, p.stdout))

    p = run(script, ["raise"], env, PAYLOAD)
    h = (beats(paths) or [{}])[-1]
    check("an exception fail_open swallows still exits 0", p.returncode == 0, (p.returncode, p.stderr[-300:]))
    check("but its heartbeat says error, with the exception class",
          h.get("status") == "error" and h.get("exc") == "ValueError", h)

    p = run(script, ["block"], env, PAYLOAD)
    h = (beats(paths) or [{}])[-1]
    check("a deliberate exit 2 is recorded as blocked, not as an error",
          p.returncode == 2 and h.get("status") == "blocked" and h.get("exit") == 2, (p.returncode, h))

    p = run(script, ["noread"], env, PAYLOAD)
    h = (beats(paths) or [{}])[-1]
    check("a hook that never reads its stdin still gets its session id recorded",
          h.get("sid") == "3ac18522" and len(beats(paths)) == 4, beats(paths))

    n = len(beats(paths))
    p = run(script, ["read"], env, None)
    check("a run with no hook payload (launchd, the file watch, a person) records nothing",
          len(beats(paths)) == n and p.returncode == 0, (p.returncode, beats(paths)[n:]))

    p = run(script, ["bare-raise"], env, dict(PAYLOAD, hook_event_name="Stop"))
    h = (beats(paths) or [{}])[-1]
    check("an exception that escapes the hook is recorded as error and still propagates",
          p.returncode != 0 and "KeyError" in p.stderr and h.get("event") == "sync" and h.get("status") == "error"
          and h.get("exc") == "KeyError", (p.returncode, h))
    p = run(script, ["bare-return-1"], env, dict(PAYLOAD, hook_event_name="Stop"))
    h = (beats(paths) or [{}])[-1]
    check("a non-zero exit other than 2 is an error",
          p.returncode == 1 and h.get("status") == "error" and h.get("exit") == 1, (p.returncode, h))

    p = run(script, ["read"], dict(env, BRAIN_OFF="1"), PAYLOAD)
    h = (beats(paths) or [{}])[-1]
    check("with Brain switched off the hook still reports that it fired, as off",
          p.returncode == 0 and h.get("status") == "off", h)

    importer = os.path.join(root, "importer.py")
    with open(importer, "w") as fh:
        fh.write(IMPORTER % {"dir": root})
    n = len(beats(paths))
    p = run(importer, ["quiet"], env, PAYLOAD)
    check("a decorated function imported by another program (the MCP server, the CLI) records nothing",
          len(beats(paths)) == n, beats(paths)[n:])
    check("and never reads that program's stdin", p.returncode == 0 and "3ac18522" in p.stdout,
          (p.returncode, p.stdout, p.stderr[-300:]))

    root2, env2, paths2 = scratch()
    script2 = os.path.join(root2, "hookmod.py")
    with open(script2, "w") as fh:
        fh.write(HOOK % {"bin": HERE})
    blocked = os.path.join(root2, "state-is-a-file")
    with open(blocked, "w") as fh:
        fh.write("x")
    p = run(script2, ["read"], dict(env2, BRAIN_STATE=blocked), PAYLOAD)
    check("an unwritable heartbeat log never changes what the hook does",
          p.returncode == 0 and "the context" in p.stdout, (p.returncode, p.stdout, p.stderr[-300:]))

    logs = os.path.join(paths2["state"], "logs")
    os.makedirs(logs)
    big = os.path.join(logs, "heartbeat.jsonl")
    with open(big, "w") as fh:
        fh.write(("x" * 1023 + "\n") * 2100)
    run(script2, ["read"], env2, PAYLOAD)
    check("the heartbeat log rotates like the other Brain logs",
          os.path.exists(big + ".1") and len(open(big).read().splitlines()) == 1, os.listdir(logs))


def test_registry_hooks_carry_heartbeat():
    print("\n== every Claude Code hook in the registry records a heartbeat ==")
    from events_core import domain as ED

    with open(os.path.join(os.path.dirname(HERE), "90-Meta", "events.json"), encoding="utf-8") as fh:
        reg = ED.load_registry(fh.read())
    hooks = reg.triggers("claude-hook")
    check("the registry wires twelve Claude Code hooks", len(hooks) == 12, [e.id for e, _ in hooks])
    missing = []
    for e, t in hooks:
        script = t.spec["command"].split()[0]
        with open(os.path.join(HERE, script), encoding="utf-8") as fh:
            text = fh.read()
        if not re.search(r'@B\.heartbeat\("%s"\)\s*\n(?:@B\.fail_open\s*\n)?def main\(' % re.escape(e.id), text):
            missing.append("%s (%s)" % (script, e.id))
    check("each hook script's main is decorated with @B.heartbeat(<its event id>), outside fail_open",
          missing == [], missing)


def test_offline_switch():
    print("\n== BRAIN_OFFLINE: what the probe sets so a hook starts no network or KeePass work ==")
    root, env, paths = scratch()
    os.makedirs(os.path.join(paths["vault"], "_index"))
    script = os.path.join(root, "offline.py")
    with open(script, "w") as fh:
        fh.write(OFFLINE % {"bin": HERE})

    def outcome(e):
        p = run(script, [], e, None)
        try:
            return json.loads(p.stdout.strip().splitlines()[-1]), p
        except (ValueError, IndexError):
            return {}, p

    got, p = outcome(env)
    check("brainlib knows it is offline", got.get("offline") is True, (got, p.stderr[-400:]))
    check("offline, presence and lease beats, the vault pull, the background reindex and the link repair start nothing",
          got.get("calls") == [] and got.get("spawned") is False, got)
    online = {k: v for k, v in env.items() if k != "BRAIN_OFFLINE"}
    got, p = outcome(online)
    check("without it the same calls do start their processes (recorded here, never run)",
          len(got.get("calls") or []) >= 5 and got.get("spawned") is True, (got, p.stderr[-400:]))


def main():
    for t in (test_heartbeat, test_registry_hooks_carry_heartbeat, test_offline_switch):
        try:
            t()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    return finish()


def finish():
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
