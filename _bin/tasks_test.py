#!/usr/bin/env python3
"""Tests for tasks.py — the periodic task runner — and its `agent` task type.

The registry, the vault, the state file, the logs and the Brain state directory are
all temporary. The "agent" is a small shell script standing in for a CLI agent, named
through BRAIN_AGENT_CMD; no real agent, network or account is involved. Run standalone:

    python3 _bin/tasks_test.py
"""
import datetime as dt
import io
import json
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok, fail = [], []
TMP = []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def tmpdir():
    d = tempfile.mkdtemp(prefix="tasks-test-")
    TMP.append(d)
    return d


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    if mode is not None:
        os.chmod(path, mode)
    return path


REGISTRY = """---
id: scheduled-tasks
---

| id | machine | time | days | type | command | enabled | notes |
|----|---------|------|------|------|---------|---------|-------|
| shell-ok | box | 05:00 | * | shell | echo shell-ran | yes | a shell row |
| shell-bad | box | 05:00 | * | shell | exit 4 | yes | a failing shell row |
| routine-a | box | 06:00 | * | agent | 90-Meta/routines/routine-a.md | yes | an agent row |
| routine-off | box | 06:00 | * | agent | 90-Meta/routines/routine-a.md | no | disabled agent row |
| routine-now | box | -- | -- | agent | 90-Meta/routines/routine-a.md | yes | manual only |
| routine-gone | box | 06:00 | * | agent | 90-Meta/routines/missing.md | yes | file missing |
| app-row | box | 06:00 | * | claude-app | (Claude app scheduler) | yes | inventory only |
| elsewhere | other-box | 06:00 | * | agent | 90-Meta/routines/routine-a.md | yes | other machine |
| by-key | box-1a2b3c4d | -- | -- | agent | 90-Meta/routines/routine-a.md | yes | pinned by machine key |
| hourly | box | every 1h | * | shell | echo hourly | yes | an interval row |
"""

# The registry's own cells as the note writes them: a bare `*`, one in code ticks, and emphasis
# around a real value. Only the emphasis may go.
STAR_REGISTRY = """| id | machine | time | days | type | command | enabled | notes |
|----|---------|------|------|------|---------|---------|-------|
| everywhere | * | 06:00 | * | agent | 90-Meta/routines/routine-a.md | yes | every machine |
| ticked | `*` | 06:00 | `*` | agent | 90-Meta/routines/routine-a.md | yes | in code ticks |
| **bold** | *box* | 06:00 | * | shell | echo hi | yes | emphasis |
"""

ROUTINE = "---\nid: routine-a\nneeds_bridge: none\n---\n\nSummarise the day in one line.\n"


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *a):
        self.calls.append(a)


FAKE_TOKEN = "sk-ant-oat01-" + "T3st_Tok-" * 10          # the right shape, not a real token
POOL = {"tokens": [{"label": "routines-1", "account": "routines",
                    "kp_ref": "kp://Brain/apis/claude-code-oauth-routines-1", "issued": "2026-09-15"}]}


class FakeTokenSource:
    """KeePass stand-in: never the real kdbx."""

    def __init__(self, value):
        self.value, self.reads = value, 0

    def read(self, kp_ref, timeout):
        self.reads += 1
        return self.value


PREAMBLE = {
    "humanizer": "---\nid: preamble-humanizer\ntype: routine-preamble\n---\n<!-- who uses it -->\n"
                 "HUMANIZER (test): every text for a person goes through humanizer.\n",
    "browser_restart": "---\nid: preamble-browser\n---\nBROWSER (test): probe, restart, probe again.\n",
}


def write_preamble(vault, blocks=PREAMBLE):
    for name, text in blocks.items():
        write(os.path.join(vault, "90-Meta", "routines", "_preamble", name + ".md"), text)


def setup(T, agent_exit=0, agent_body="echo agent-said-hello", token_value=FAKE_TOKEN):
    """A fresh temporary world wired into the tasks module."""
    root = tmpdir()
    vault = os.path.join(root, "Vault")
    state = os.path.join(root, "state")
    write(os.path.join(vault, "90-Meta", "scheduled-tasks.md"), REGISTRY)
    write(os.path.join(vault, "90-Meta", "routines", "routine-a.md"), ROUTINE)
    write(os.path.join(vault, "90-Meta", "routine-tokens.json"), json.dumps(POOL))
    write_preamble(vault)
    args_file = os.path.join(root, "agent-args.txt")
    agent = write(os.path.join(root, "agent"),
                  '#!/bin/sh\nif [ "$1" = "--version" ]; then echo "$1" >> "%s"; echo "1.0 (fake)"; exit 0; fi\n'
                  'printf "%%s\\n" "$@" > "%s"\nenv > "%s"\n%s\nexit %d\n'
                  % (os.path.join(root, "versions.txt"), args_file, os.path.join(root, "agent-env.txt"),
                     agent_body, agent_exit), mode=0o755)
    T.VAULT = vault
    T.REGISTRY = os.path.join(vault, "90-Meta", "scheduled-tasks.md")
    T.STATE_DIR = state
    T.STATE_FILE = os.path.join(state, "tasks-state.json")
    T.LOG_DIR = os.path.join(state, "logs", "tasks")
    T.RUNNER_LOG = os.path.join(T.LOG_DIR, "_runner.log")
    T.ROUTINE_AUTH_STATE = os.path.join(state, "routine-auth-state.json")
    T.ROUTINE_AUTH_LOG = os.path.join(state, "logs", "routine-auth.log")
    T.ROUTINE_SCRATCH_DIR = os.path.join(state, "routine-scratch")
    T.MAIL_SENT_LOG = os.path.join(state, "logs", "mail-sent.jsonl")
    T.CLI_HEALTH_CACHE = {}
    source = FakeTokenSource(token_value)
    T.token_source = lambda: source
    T.host = lambda: "box"
    T.now = lambda: dt.datetime(2026, 9, 14, 7, 0)       # a Monday, after 06:00
    T.raise_alert, T.clear_alert = Recorder(), Recorder()
    os.environ["BRAIN_AGENT_CMD"] = "%s --prompt {prompt} --file {prompt_file}" % agent
    return root, args_file


def quiet(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = fn(*a)
    return rc, buf.getvalue()


# ---------------------------------------------------------------- the state file under concurrent runs

WAIT_FOR_GO = ('touch "loaded-$W" && i=0 && while [ ! -e "go-$W" ] && [ $i -lt 600 ]; '
               'do sleep 0.05; i=$((i+1)); done; exit $RC')

STATE_REGISTRY = """---
id: scheduled-tasks
---

| id | machine | time | days | type | command | enabled | notes |
|----|---------|------|------|------|---------|---------|-------|
| task-a | box | -- | -- | shell | %(wait)s | yes | forced by one run |
| task-b | box | -- | -- | shell | %(wait)s | yes | forced by another run |
| task-s | box | -- | -- | shell | %(wait)s | yes | forced by both runs |
| tick-b | box | 05:30 | * | shell | true | yes | a second task due on the tick |
| tick-a | box | 05:00 | * | shell | true | yes | due on the tick |
""" % {"wait": WAIT_FOR_GO}

# A separate runner process: its own module, the temporary world, `tasks.py --force <task>`.
CHILD_RUN = r'''
import datetime as dt, json, os, sys
cfg = json.loads(sys.argv[1])
sys.path.insert(0, cfg["here"])
import tasks as T
for k in ("VAULT", "REGISTRY", "STATE_DIR", "STATE_FILE", "LOG_DIR", "RUNNER_LOG"):
    setattr(T, k, cfg[k])
T.host = lambda: "box"
T.raise_alert = T.clear_alert = lambda *a, **k: None
if cfg.get("single"):
    T.single_instance = lambda task: task["id"] in cfg["single"]
if cfg.get("now"):
    fixed = dt.datetime.strptime(cfg["now"], "%Y-%m-%dT%H:%M:%S")
    T.now = lambda: fixed
sys.exit(T.main(["--force", cfg["task"]]))
'''

HOLD_LOCK = r'''
import fcntl, sys, time
fh = open(sys.argv[1], "a")
fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
print("held", flush=True)
time.sleep(float(sys.argv[2]) if len(sys.argv) > 2 else 60)
'''

# A writer killed between writing its temp file and replacing the state file.
CHILD_CRASH = r'''
import json, os, sys
cfg = json.loads(sys.argv[1])
sys.path.insert(0, cfg["here"])
import tasks as T
T.STATE_DIR, T.STATE_FILE, T.RUNNER_LOG = cfg["STATE_DIR"], cfg["STATE_FILE"], cfg["RUNNER_LOG"]
events, real_fsync = [], os.fsync
def fsync(fd):
    events.append("fsync")
    return real_fsync(fd)
def crash(src, dst, *a, **k):
    events.append("replace")
    with open(src) as fh:
        written = fh.read()
    with open(cfg["report"], "w") as fh:
        json.dump({"events": events, "temp": str(src), "written": written}, fh)
    os._exit(9)
os.fsync, os.replace = fsync, crash
T.save_state({"task-b": {"last_run_date": "2026-09-14", "last_run_at": "2026-09-14T07:00:00", "last_exit": 0}})
'''


def entry(at, rc=0):
    return {"last_run_date": at[:10], "last_run_at": at, "last_exit": rc, "host": "box"}


def attempt(fn, *a, **k):
    """(result, None) or (None, exception); output swallowed. A missing function is an exception."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            return fn(*a, **k), None
    except Exception as exc:
        return None, exc


def read_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def read_text(path):
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        return ""


def wait_until(pred, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.05)
    return pred()


def state_world(T):
    """A temporary vault and state directory for the state tests; never the real Brain state."""
    root = tmpdir()
    vault = os.path.join(root, "Vault")
    state = os.path.join(root, "state")
    write(os.path.join(vault, "90-Meta", "scheduled-tasks.md"), STATE_REGISTRY)
    T.VAULT = vault
    T.REGISTRY = os.path.join(vault, "90-Meta", "scheduled-tasks.md")
    T.STATE_DIR = state
    T.STATE_FILE = os.path.join(state, "tasks-state.json")
    T.LOG_DIR = os.path.join(state, "logs", "tasks")
    T.RUNNER_LOG = os.path.join(T.LOG_DIR, "_runner.log")
    T.host = lambda: "box"
    T.now = lambda: dt.datetime(2026, 9, 14, 7, 0)
    T.raise_alert, T.clear_alert = Recorder(), Recorder()
    return {"here": HERE, "root": root, "VAULT": vault, "REGISTRY": T.REGISTRY, "STATE_DIR": state,
            "STATE_FILE": T.STATE_FILE, "LOG_DIR": T.LOG_DIR, "RUNNER_LOG": T.RUNNER_LOG}


def child_env(world, **extra):
    env = dict(os.environ, BRAIN_STATE=os.path.join(world["root"], "brain-state"), PYTHONDONTWRITEBYTECODE="1")
    env.update(extra)
    return env


def race(world, runs):
    """Start one runner process per run; each loads the state, then waits in its task for a go.
    Release them one at a time, in the order given, so each saves after all of them loaded."""
    procs = []
    for run in runs:
        cfg = dict(world, **run)
        procs.append(subprocess.Popen([sys.executable, "-c", CHILD_RUN, json.dumps(cfg)],
                                      env=child_env(world, W=run["w"], RC=str(run.get("rc", 0))),
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True))
    marker = lambda name: os.path.join(world["VAULT"], name)
    wait_until(lambda: all(os.path.exists(marker("loaded-" + r["w"])) for r in runs), 30)
    results = []
    for run, proc in zip(runs, procs):
        write(marker("go-" + run["w"]), "")
        try:
            out, _ = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
        results.append((run["w"], proc.returncode, (out or "")[-400:]))
    return read_json(world["STATE_FILE"]) or {}, results


def state_tests(T):
    had_timeout, old_timeout = hasattr(T, "STATE_LOCK_TIMEOUT"), getattr(T, "STATE_LOCK_TIMEOUT", None)
    real_run_task = T.run_task
    try:
        _state_tests(T, real_run_task)
    finally:
        T.run_task = real_run_task
        if had_timeout:
            T.STATE_LOCK_TIMEOUT = old_timeout
        elif hasattr(T, "STATE_LOCK_TIMEOUT"):
            del T.STATE_LOCK_TIMEOUT


def _state_tests(T, real_run_task):
    print("\n== loading the state file ==")
    state_world(T)
    for label, text in (("missing", None), ("empty", ""), ("corrupt", "{not json"), ("non-object", "[1, 2]")):
        if os.path.exists(T.STATE_FILE):
            os.remove(T.STATE_FILE)
        if text is not None:
            write(T.STATE_FILE, text)
        got, exc = attempt(T.load_state)
        check("a %s state file loads as empty" % label, exc is None and got == {}, (got, exc))

    print("\n== merging a run's entries into the state on disk ==")
    merge = getattr(T, "merge_state", None) or (lambda *a: (_ for _ in ()).throw(AttributeError("no merge_state")))
    current = {"other": entry("2026-09-14T08:00:00"), "x": entry("2026-09-14T10:00:00", 0)}
    mine = {"other": entry("2026-09-13T08:00:00"), "x": entry("2026-09-14T09:00:00", 3),
            "y": entry("2026-09-14T09:30:00")}
    before = json.dumps([current, mine], sort_keys=True)
    got, exc = attempt(merge, current, mine, {"x", "y"})
    got = got or {}
    check("an id this run did not change keeps the entry on disk", got.get("other") == current["other"], (got, exc))
    check("a newer entry on disk for an id this run changed is kept", got.get("x") == current["x"], got)
    check("this run's entry for a new id is added", got.get("y") == mine["y"], got)
    check("merging modifies neither input", json.dumps([current, mine], sort_keys=True) == before)
    got, exc = attempt(merge, current, {"x": entry("2026-09-14T11:00:00", 5)}, {"x"})
    check("this run's newer entry replaces an older one on disk", (got or {}).get("x", {}).get("last_exit") == 5,
          (got, exc))

    state_world(T)
    write(T.STATE_FILE, json.dumps({"task-b": entry("2026-09-14T06:59:00")}))
    stale = {"task-b": entry("2026-09-13T06:00:00", 9), "task-a": entry("2026-09-14T07:00:00")}
    res, exc = attempt(T.save_state, stale, {"task-a"})
    st = read_json(T.STATE_FILE) or {}
    check("a save writes only the ids the run says it changed",
          exc is None and st.get("task-b", {}).get("last_exit") == 0 and st.get("task-a") == stale["task-a"],
          (exc, st))

    state_world(T)

    def run_task_while_another_run_saves(*a, **k):
        write(T.STATE_FILE, json.dumps({"task-b": entry("2026-09-14T07:00:30")}))
        return real_run_task(*a, **k)

    T.run_task = run_task_while_another_run_saves
    try:
        rc, exc = attempt(T.main, [])
    finally:
        T.run_task = real_run_task
    st = read_json(T.STATE_FILE) or {}
    check("the scheduled tick keeps an entry another run saved while it was running",
          exc is None and st.get("task-b", {}).get("last_run_at") == "2026-09-14T07:00:30"
          and st.get("tick-a", {}).get("last_exit") == 0, (rc, exc, st))

    print("\n== two runner processes saving the same state file ==")
    for order in (("A", "B"), ("B", "A")):
        world = state_world(T)
        runs = {"A": {"task": "task-a", "w": "A"}, "B": {"task": "task-b", "w": "B"}}
        st, results = race(world, [runs[w] for w in order])
        check("runs of two different tasks saving %s then %s: both entries survive" % order,
              st.get("task-a", {}).get("last_exit") == 0 and st.get("task-b", {}).get("last_exit") == 0,
              (st, results))
    for order in (("A", "B"), ("B", "A")):
        world = state_world(T)
        runs = {"A": {"task": "task-s", "w": "A", "now": "2026-09-14T10:00:00", "rc": 0},
                "B": {"task": "task-s", "w": "B", "now": "2026-09-14T09:00:00", "rc": 3}}
        st, results = race(world, [runs[w] for w in order])
        check("two runs of one task saving %s then %s: the newer entry survives" % order,
              st.get("task-s", {}).get("last_run_at") == "2026-09-14T10:00:00"
              and st.get("task-s", {}).get("last_exit") == 0, (st, results))

    print("\n== a routine's own timeout ==")
    check("no timeout_minutes means the default", T.routine_timeout("---\nid: r\n---\nbody\n") == T.DEFAULT_TIMEOUT)
    check("timeout_minutes in the front matter sets it",
          T.routine_timeout("---\nid: r\ntimeout_minutes: 240\n---\nbody\n") == 240 * 60)
    check("timeout_minutes in the body does not count",
          T.routine_timeout("---\nid: r\n---\ntimeout_minutes: 240\n") == T.DEFAULT_TIMEOUT)
    check("a zero timeout falls back to the default",
          T.routine_timeout("---\nid: r\ntimeout_minutes: 0\n---\n") == T.DEFAULT_TIMEOUT)

    print("\n== a single_instance task never runs twice at once ==")
    world = state_world(T)
    rows = {t["id"]: t for t in T.read_registry()}
    check("a shell row is not single_instance", not T.single_instance(rows["task-s"]))
    routine = os.path.join(world["VAULT"], "90-Meta", "routines", "r.md")
    write(routine, "---\nid: r\nsingle_instance: true\n---\n\nbody\n")
    check("a routine with single_instance: true is",
          T.single_instance({"type": "agent", "command": "90-Meta/routines/r.md"}))
    write(routine, "---\nid: r\n---\n\nsingle_instance: true in the body does not count\n")
    check("a routine without it in the front matter is not",
          not T.single_instance({"type": "agent", "command": "90-Meta/routines/r.md"}))
    cfg = dict(world, task="task-s", w="A", now="2026-09-14T10:00:00", single=["task-s"])
    first = subprocess.Popen([sys.executable, "-c", CHILD_RUN, json.dumps(cfg)],
                             env=child_env(world, W="A", RC="0"),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    try:
        started = wait_until(lambda: os.path.exists(os.path.join(world["VAULT"], "loaded-A")), 30)
        cfg_b = dict(world, task="task-s", w="B", now="2026-09-14T10:30:00", single=["task-s"])
        second = subprocess.run([sys.executable, "-c", CHILD_RUN, json.dumps(cfg_b)],
                                env=child_env(world, W="B", RC="3"), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        check("a --force of a task still running is refused with exit 75",
              started and second.returncode == 75 and "already running" in second.stderr,
              (started, second.returncode, second.stderr[-300:]))
        check("and never starts the task's command", not os.path.exists(os.path.join(world["VAULT"], "loaded-B")))
        check("the lock file names the run holding it",
              "pid %d " % first.pid in read_text(T.task_lock_path("task-s")), read_text(T.task_lock_path("task-s")))
    finally:
        write(os.path.join(world["VAULT"], "go-A"), "")
        out, _ = first.communicate(timeout=60)
    st = read_json(world["STATE_FILE"]) or {}
    check("the running one records its own result, untouched by the refused one",
          first.returncode == 0 and st.get("task-s", {}).get("last_run_at") == "2026-09-14T10:00:00"
          and st.get("task-s", {}).get("last_exit") == 0, (first.returncode, st, out[-300:]))

    def lock_is_free():
        with T.task_lock("task-s") as (held, _holder):
            return held
    check("once it ends the lock is free again", attempt(lock_is_free)[0] is True)

    world = state_world(T)
    real_single = T.single_instance
    T.single_instance = lambda task: task["id"] == "tick-a"
    lock = T.task_lock_path("tick-a")
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    holder = subprocess.Popen([sys.executable, "-c", HOLD_LOCK, lock], stdout=subprocess.PIPE, universal_newlines=True)
    try:
        holder.stdout.readline()
        rc, exc = attempt(T.main, [])
        st = read_json(T.STATE_FILE) or {}
        check("a tick that finds a due task still running skips it and leaves its state alone",
              exc is None and rc == 0 and "tick-a" not in st, (rc, exc, st))
        check("and says so in the runner log", "skipped tick-a: already running" in read_text(T.RUNNER_LOG),
              read_text(T.RUNNER_LOG)[-300:])
    finally:
        holder.kill()
        holder.wait()
    rc, exc = attempt(T.main, [])
    st = read_json(T.STATE_FILE) or {}
    check("the next tick after it ends runs it", exc is None and st.get("tick-a", {}).get("last_exit") == 0,
          (rc, exc, st))
    T.single_instance = real_single

    print("\n== tasks in the same lock_group never run at once ==")
    world = state_world(T)
    routine = os.path.join(world["VAULT"], "90-Meta", "routines", "g.md")
    write(routine, "---\nid: g\nlock_group: Printer\n---\n\nbody\n")
    check("lock_group is read from the front matter, lower case",
          T.lock_group({"type": "agent", "command": "90-Meta/routines/g.md"}) == "printer")
    write(routine, "---\nid: g\n---\n\nlock_group: printer in the body does not count\n")
    check("but not from the body", T.lock_group({"type": "agent", "command": "90-Meta/routines/g.md"}) == "")
    write(routine, "---\nid: g\nlock_group: social, Printer\n---\n\nbody\n")
    check("several groups are read, lower case",
          T.lock_group({"type": "agent", "command": "90-Meta/routines/g.md"}) == "social,printer")
    check("and taken in sorted order",
          T.lock_groups({"type": "agent", "command": "90-Meta/routines/g.md"}) == ["printer", "social"])
    rows = {t["id"]: t for t in T.read_registry()}
    check("a shell row has no lock group", T.lock_group(rows["task-s"]) == "")
    g_task = {"type": "agent", "command": "90-Meta/routines/g.md"}
    browser = 'agent_args: ["--chrome", "--allowedTools", "Read,mcp__claude-in-chrome"]\n'
    write(routine, "---\nid: g\n" + browser + "---\n\nbody\n")
    check("a routine that allows Claude in Chrome gets the chrome group by itself",
          T.lock_groups(g_task) == ["chrome"], T.lock_groups(g_task))
    write(routine, "---\nid: g\nlock_group: social, printer\n" + browser + "---\n\nbody\n")
    check("added to its own groups and taken in sorted order",
          T.lock_groups(g_task) == ["chrome", "printer", "social"], T.lock_groups(g_task))
    write(routine, "---\nid: g\nlock_group: nightly-job, social\n" + browser + "---\n\nbody\n")
    check("chrome goes before nightly-job and social, like every other holder",
          T.lock_groups(g_task) == ["chrome", "nightly-job", "social"], T.lock_groups(g_task))
    write(routine, "---\nid: g\nlock_group: chrome, social\n" + browser + "---\n\nbody\n")
    check("named by hand it is not added twice", T.lock_group(g_task) == "chrome,social", T.lock_group(g_task))
    write(routine, "---\nid: g\nchrome_lock: false\n" + browser + "---\n\nbody\n")
    check("`chrome_lock: false` opts out (a routine on another machine's Chrome)", T.lock_groups(g_task) == [],
          T.lock_groups(g_task))
    write(routine, "---\nid: g\nagent_args: [\"--allowedTools\", \"Read,Bash(ls:*)\"]\n---\n\nmcp__claude-in-chrome in the body\n")
    check("a routine without Claude in Chrome in its agent_args gets no chrome group", T.lock_groups(g_task) == [],
          T.lock_groups(g_task))
    real_group = T.lock_group
    T.lock_group = lambda task: "printer" if task["id"] == "tick-a" else ""
    lock = T.task_lock_path("group-printer")
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    holder = subprocess.Popen([sys.executable, "-c", HOLD_LOCK, lock, "3"], stdout=subprocess.PIPE, universal_newlines=True)
    try:
        holder.stdout.readline()
        t0 = time.monotonic()
        rc, exc = attempt(T.main, [])
        waited = time.monotonic() - t0
        st = read_json(T.STATE_FILE) or {}
        check("a due task whose lock group is busy waits for it and then runs",
              exc is None and rc == 0 and st.get("tick-a", {}).get("last_exit") == 0 and waited >= 2, (rc, exc, st, waited))
        log_text = read_text(T.RUNNER_LOG)
        check("and the runner log says it waited for which group",
              "waiting tick-a: lock group printer busy" in log_text and "lock group printer free for tick-a" in log_text,
              log_text[-400:])
    finally:
        holder.kill()
        holder.wait()

    world = state_world(T)
    T.lock_group = lambda task: "printer,social" if task["id"] == "tick-a" else ""
    claim = T.task_lock_path("tick-a")
    os.makedirs(os.path.dirname(claim), exist_ok=True)
    holder = subprocess.Popen([sys.executable, "-c", HOLD_LOCK, claim, "30"], stdout=subprocess.PIPE, universal_newlines=True)
    try:
        holder.stdout.readline()
        rc, exc = attempt(T.main, [])
        st = read_json(T.STATE_FILE) or {}
        check("a tick that finds the task already waiting or running leaves it alone",
              exc is None and rc == 0 and "tick-a" not in st, (rc, exc, st))
        check("and says so", "skipped tick-a: already running or waiting" in read_text(T.RUNNER_LOG),
              read_text(T.RUNNER_LOG)[-300:])
        check("while a task outside the group still runs on that tick",
              st.get("tick-b", {}).get("last_exit") == 0, st)
    finally:
        holder.kill()
        holder.wait()

    world = state_world(T)
    os.makedirs(os.path.dirname(T.task_lock_path("group-social")), exist_ok=True)
    holder = subprocess.Popen([sys.executable, "-c", HOLD_LOCK, T.task_lock_path("group-social"), "3"],
                              stdout=subprocess.PIPE, universal_newlines=True)
    try:
        holder.stdout.readline()
        t0 = time.monotonic()
        rc, exc = attempt(T.main, [])
        waited = time.monotonic() - t0
        st = read_json(T.STATE_FILE) or {}
        check("with several groups it waits for the busy one and runs",
              exc is None and st.get("tick-a", {}).get("last_exit") == 0 and waited >= 2
              and "waiting tick-a: lock group social busy" in read_text(T.RUNNER_LOG), (rc, exc, st, waited))
        check("the wait does not count against the routine timeout", "timed out" not in read_text(T.RUNNER_LOG))
    finally:
        holder.kill()
        holder.wait()

    world = state_world(T)
    clock = {"t": dt.datetime(2026, 9, 14, 23, 50)}
    T.now = lambda: clock["t"]
    real_wait = T.group_locks
    @contextlib.contextmanager
    def wait_past_midnight(groups, task_id):
        with real_wait(groups, task_id):
            clock["t"] = dt.datetime(2026, 9, 15, 1, 30)   # the holder took hours
            yield
    T.group_locks = wait_past_midnight
    rc, exc = attempt(T.main, [])
    st = read_json(T.STATE_FILE) or {}
    rec = st.get("tick-a", {})
    check("a run that waits past midnight is recorded on the day it was due",
          exc is None and rec.get("last_run_date") == "2026-09-14", (rc, exc, rec))
    check("with its real start time", str(rec.get("last_run_at", "")).startswith("2026-09-15T01:30"), rec)
    clock["t"] = dt.datetime(2026, 9, 15, 7, 0)
    tick_a = next(t for t in T.read_registry() if t["id"] == "tick-a")
    check("so the next day's run is still due", T.due(tick_a, st)[0] is True, T.due(tick_a, st))
    T.group_locks = real_wait
    T.lock_group = real_group

    world = state_world(T)
    T.lock_group = lambda task: "printer" if task["id"] in ("tick-a", "tick-b") else ""
    real_due = T.due
    seen = {"tick-b": 0}

    def late_due(task, state):
        if task["id"] == "tick-b":
            seen["tick-b"] += 1
            if seen["tick-b"] == 1:
                return False, "not due yet in the main pass"
        return real_due(task, state)
    T.due = late_due
    try:
        rc, exc = attempt(T.main, [])
    finally:
        T.due = real_due
        T.lock_group = real_group
    st = read_json(T.STATE_FILE) or {}
    check("a group task that became due while the group was busy runs right after the holder ends",
          exc is None and st.get("tick-a", {}).get("last_exit") == 0 and st.get("tick-b", {}).get("last_exit") == 0,
          (rc, exc, st))
    check("and the runner log says it ran right after",
          "running tick-b right after tick-a freed lock group printer" in read_text(T.RUNNER_LOG),
          read_text(T.RUNNER_LOG)[-400:])

    print("\n== the state lock ==")
    world = state_world(T)
    seed = {"task-a": entry("2026-09-13T06:00:00")}
    write(T.STATE_FILE, json.dumps(seed))
    lock = T.STATE_FILE + ".lock"
    holder = subprocess.Popen([sys.executable, "-c", HOLD_LOCK, lock], stdout=subprocess.PIPE,
                              universal_newlines=True)
    try:
        holder.stdout.readline()
        T.STATE_LOCK_TIMEOUT = 0.3
        started = time.time()
        res, exc = attempt(T.save_state, {"task-b": entry("2026-09-14T07:00:00")})
        waited = time.time() - started
        check("a save that cannot get the lock waits its timeout, then gives up without raising",
              exc is None and res is False and 0.25 <= waited < 5, (res, exc, round(waited, 2)))
        check("and leaves the state file as it was", read_json(T.STATE_FILE) == seed, read_json(T.STATE_FILE))
        runner_log = read_text(T.RUNNER_LOG)
        check("and the runner log says the state was not saved, naming the lock",
              "not saved" in runner_log and lock in runner_log, runner_log)
    finally:
        holder.kill()
        holder.wait()
    res, exc = attempt(T.save_state, {"task-b": entry("2026-09-14T07:00:00")})
    check("once the lock is free the same save goes through, keeping the entry on disk",
          exc is None and res is True and sorted(read_json(T.STATE_FILE) or {}) == ["task-a", "task-b"],
          (res, exc, read_json(T.STATE_FILE)))

    print("\n== temp files and crashes ==")
    state_world(T)
    seen, real_replace = [], os.replace

    def spy(src, dst, *a, **k):
        seen.append(str(src))
        return real_replace(src, dst, *a, **k)

    os.replace = spy
    try:
        attempt(T.save_state, {"task-a": entry("2026-09-14T07:00:00")})
        attempt(T.save_state, {"task-b": entry("2026-09-14T07:01:00")})
    finally:
        os.replace = real_replace
    real_dir = os.path.realpath(T.STATE_DIR)
    check("each save writes through its own temp file beside the state file",
          len(seen) == 2 and seen[0] != seen[1]
          and all(os.path.realpath(os.path.dirname(p)) == real_dir for p in seen)
          and all(os.path.basename(p) != "tasks-state.tmp" for p in seen), seen)
    leftovers = [n for n in os.listdir(T.STATE_DIR) if n.endswith(".tmp")] if os.path.isdir(T.STATE_DIR) else []
    check("and leaves none behind", not leftovers, leftovers)

    world = state_world(T)
    seed = {"task-a": entry("2026-09-13T06:00:00")}
    write(T.STATE_FILE, json.dumps(seed, indent=2))
    report = os.path.join(world["root"], "crash-report.json")
    proc = subprocess.run([sys.executable, "-c", CHILD_CRASH, json.dumps(dict(world, report=report))],
                          env=child_env(world), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True, timeout=60)
    check("a writer killed between writing and replacing leaves the previous state file whole",
          proc.returncode == 9 and read_json(T.STATE_FILE) == seed,
          (proc.returncode, proc.stdout[-400:], read_text(T.STATE_FILE)))
    rep = read_json(report) or {}
    events = rep.get("events", [])
    written = rep.get("written", "")
    check("what it wrote was complete and fsynced before the replace",
          "fsync" in events and "replace" in events and events.index("fsync") < events.index("replace")
          and "task-b" in (json.loads(written) if written.strip().startswith("{") else {}), rep)
    res, exc = attempt(T.save_state, {"task-c": entry("2026-09-14T07:05:00")})
    st, loaded = read_json(T.STATE_FILE) or {}, attempt(T.load_state)[0]
    check("the next writer, with the dead writer's temp file still there, saves a complete state file",
          exc is None and sorted(st) == ["task-a", "task-c"] and loaded == st, (exc, st, loaded))


def main():
    try:
        import tasks as T
        from guardian_core import domain as GD
        T.main, T.raise_alert, T.clear_alert
        T.token_source, T.ROUTINE_AUTH_STATE, T.ROUTINE_AUTH_LOG, T.CLI_HEALTH_CACHE
    except Exception as exc:
        check("tasks.py imports with raise_alert/clear_alert hooks and the routine auth seams", False,
              "%s: %s" % (type(exc).__name__, exc))
        return finish()

    saved = {k: getattr(T, k, None) for k in ("VAULT", "REGISTRY", "STATE_DIR", "STATE_FILE", "LOG_DIR",
                                               "RUNNER_LOG", "host", "now", "raise_alert", "clear_alert",
                                               "machine_is_mine", "token_source", "ROUTINE_AUTH_STATE", "ROUTINE_AUTH_LOG",
                                               "ROUTINE_SCRATCH_DIR", "MAIL_SENT_LOG", "CLI_HEALTH_CACHE")}
    old_cmd = os.environ.get("BRAIN_AGENT_CMD")
    old_state = os.environ.get("BRAIN_STATE")
    try:
        real_vault_preamble_tests(T, str(saved["VAULT"]))

        print("\n== registry and due-ness ==")
        root, args_file = setup(T)
        rows = {t["id"]: t for t in T.read_registry()}
        check("agent rows are read with type 'agent'",
              rows.get("routine-a", {}).get("type") == "agent"
              and rows["routine-a"]["command"] == "90-Meta/routines/routine-a.md", rows.get("routine-a"))
        state = T.load_state()
        check("an `every Nh` row is read, not dropped as unscheduled",
              rows.get("hourly", {}).get("time") == "every 1h", rows.get("hourly"))
        check("an interval row goes by the gap since its last run, not the daily mark",
              T.due(rows["hourly"], {"hourly": {"last_run_date": "2026-09-14",
                                                "last_run_at": "2026-09-14T06:30:00"}})
              == (False, "not yet (every 1h, next 07:30)")
              and T.due(rows["hourly"], {"hourly": {"last_run_date": "2026-09-14",
                                                    "last_run_at": "2026-09-14T05:30:00"}}) == (True, ""))
        check("tasks.due is the shared domain rule, row for row",
              all(T.due(t, state) == GD.routine_due(t, None, T.now(), "box") for t in rows.values()),
              [(i, T.due(t, state)) for i, t in rows.items()])
        check("an enabled agent row past its time is due", T.due(rows["routine-a"], state) == (True, ""))
        check("a disabled agent row is not", T.due(rows["routine-off"], state) == (False, "disabled"))
        check("claude-app rows stay inventory only",
              T.due(rows["app-row"], state) == (False, "type 'claude-app' is not run by this runner"))

        print("\n== a bare `*` in the registry ==")
        main_registry = T.REGISTRY
        T.REGISTRY = write(os.path.join(tmpdir(), "scheduled-tasks.md"), STAR_REGISTRY)
        try:
            stars = {t["id"]: t for t in T.read_registry()}
        finally:
            T.REGISTRY = main_registry
        check("a bare `*` machine survives the emphasis strip",
              stars.get("everywhere", {}).get("machine") == "*", stars.get("everywhere"))
        check("a bare `*` days survives the emphasis strip",
              stars.get("everywhere", {}).get("days") == "*", stars.get("everywhere"))
        check("a `*` in code ticks is `*` too",
              stars.get("ticked", {}).get("machine") == "*" and stars["ticked"].get("days") == "*",
              stars.get("ticked"))
        check("emphasis around a real value is still stripped",
              stars.get("bold", {}).get("id") == "bold" and stars["bold"].get("machine") == "box",
              stars.get("bold"))
        check("a `*` row is due on any machine",
              "everywhere" in stars and T.due(stars["everywhere"], state) == (True, ""))

        print("\n== the machine column and machine identity ==")
        saved_is_mine = T.machine_is_mine
        T.machine_is_mine = lambda m: m == "box-1a2b3c4d"
        try:
            keyed = dict(rows["routine-a"], machine="box-1a2b3c4d")
            check("a row naming this machine's key is due here", T.due(keyed, state) == (True, ""))
            check("and is listed as this machine's", T.mine(keyed))
            check("a row naming another machine is not",
                  T.due(rows["elsewhere"], state) == (False, "belongs to other-box") and not T.mine(rows["elsewhere"]))
            check("an old bare-hostname row still runs here",
                  T.due(rows["routine-a"], state) == (True, "") and T.mine(rows["routine-a"]))
        finally:
            T.machine_is_mine = saved_is_mine
        T._MINE_CACHE.clear()
        asked = []

        def counting(value):
            asked.append(value)
            return False

        import machine_identity
        real = machine_identity.machine_is_mine
        machine_identity.machine_is_mine = counting
        try:
            T.machine_is_mine("some-key")
            T.machine_is_mine("some-key")
        finally:
            machine_identity.machine_is_mine = real
            T._MINE_CACHE.clear()
        check("machine identity is asked once per value per run", asked == ["some-key"], asked)

        print("\n== running an agent routine ==")
        rc, out = quiet(T.main, [])
        st = json.load(open(T.STATE_FILE))
        args = open(args_file).read().splitlines() if os.path.exists(args_file) else []
        check("a due agent routine runs through the configured agent command",
              args[:1] == ["--prompt"] and st.get("routine-a", {}).get("last_exit") == 0, (args, st))
        at = args.index("--file") if "--file" in args else len(args)
        prompt_text = "\n".join(args[1:at])
        check("the prompt is the routine body without its frontmatter, framed as an instruction to run it now",
              prompt_text.startswith('You are running the Brain routine "routine-a" unattended, right now')
              and prompt_text.rstrip().endswith("Summarise the day in one line.")
              and "needs_bridge" not in prompt_text, args)
        check("a routine with no `preamble:` key gets the default humanizer block, before its body, once",
              prompt_text.count("HUMANIZER (test)") == 1
              and prompt_text.index("HUMANIZER (test)") < prompt_text.index("Summarise the day")
              and "BROWSER (test)" not in prompt_text
              and "preamble-humanizer" not in prompt_text and "who uses it" not in prompt_text, prompt_text)
        prompt_file = args[at + 1] if at + 1 < len(args) else ""
        check("{prompt_file} is a temporary file holding that prompt, gone after the run",
              prompt_file and prompt_file != os.path.join(T.VAULT, "90-Meta", "routines", "routine-a.md")
              and not os.path.exists(prompt_file), args)
        log = open(os.path.join(T.LOG_DIR, "routine-a.log")).read()
        check("the run is logged with its output and exit code",
              "START  routine-a" in log and "agent-said-hello" in log and "exit=0" in log, log)
        check("a successful routine clears any alert it had raised",
              ("routine:routine-a",) in T.clear_alert.calls, T.clear_alert.calls)
        check("the missing routine file raises an alert",
              any(c[0] == "routine:routine-gone" for c in T.raise_alert.calls), T.raise_alert.calls)
        check("nothing else raised an alert",
              [c[0] for c in T.raise_alert.calls] == ["routine:routine-gone"], T.raise_alert.calls)
        check("a failing shell row does not raise an alert (unchanged behaviour)",
              st.get("shell-bad", {}).get("last_exit") == 4
              and not any("shell-bad" in c[0] for c in T.raise_alert.calls), st.get("shell-bad"))
        check("shell rows still run", st.get("shell-ok", {}).get("last_exit") == 0, st.get("shell-ok"))
        check("another machine's agent row never runs here", "elsewhere" not in st, sorted(st))
        check("a manual-only agent row never runs on schedule", "routine-now" not in st, sorted(st))

        os.remove(args_file)
        quiet(T.main, [])
        check("the same routine does not run twice the same day", not os.path.exists(args_file))

        rc, _ = quiet(T.main, ["--force", "routine-now"])
        check("--force runs a manual-only agent routine", rc == 0 and os.path.exists(args_file), rc)

        print("\n== --force respects who owns the task ==")
        saved_is_mine, saved_names = T.machine_is_mine, T.host_names
        T.machine_is_mine = lambda m: m == "box-1a2b3c4d"
        T.host_names = lambda: ["box", "box-1a2b3c4d"]
        try:
            os.remove(args_file)
            rc, out = quiet(T.main, ["--force", "by-key"])
            check("--force runs a row pinned to this machine's key, not only to its hostname",
                  rc == 0 and os.path.exists(args_file), (rc, out))
            os.remove(args_file)
            rc, out = quiet(T.main, ["--force", "elsewhere"])
            check("--force refuses a task that belongs to another machine",
                  rc == 3 and not os.path.exists(args_file), (rc, out))
            check("and the refusal names the owner and the flag that overrides it",
                  "other-box" in out and "--anywhere" in out, out)
            rc, out = quiet(T.main, ["--force", "elsewhere", "--anywhere"])
            check("--anywhere runs it anyway, for the rare deliberate case",
                  rc == 0 and os.path.exists(args_file), (rc, out))
            rc, out = quiet(T.main, ["--list"])
            check("--list says what this host matches as",
                  "this host matches as: box, box-1a2b3c4d" in out, out[:400])
        finally:
            T.machine_is_mine, T.host_names = saved_is_mine, saved_names

        print("\n== failures go to the alert channel ==")
        root, args_file = setup(T, agent_exit=3)
        quiet(T.main, [])
        alerts = {c[0]: c[1] for c in T.raise_alert.calls}
        check("a failing agent raises an alert naming its exit code",
              "routine:routine-a" in alerts and "exit=3" in alerts["routine:routine-a"], alerts)
        check("and its state records the failure",
              json.load(open(T.STATE_FILE))["routine-a"]["last_exit"] == 3)

        root, _ = setup(T)
        os.environ["BRAIN_AGENT_CMD"] = "/nonexistent/agent-cli --prompt {prompt}"
        rc, _ = quiet(T.main, ["--force", "routine-a"])
        alerts = {c[0]: c[1] for c in T.raise_alert.calls}
        check("a missing agent binary is exit 127 and an alert, never a silent no-op",
              rc == 127 and "routine:routine-a" in alerts, (rc, alerts))

        root, _ = setup(T)
        os.environ.pop("BRAIN_AGENT_CMD", None)
        rc, _ = quiet(T.main, ["--force", "routine-a"])
        alerts = {c[0]: c[1] for c in T.raise_alert.calls}
        check("no agent command configured is an alert saying so",
              rc == 127 and "agent command" in alerts.get("routine:routine-a", ""), (rc, alerts))

        root, _ = setup(T)
        write(os.path.join(T.VAULT, "90-Meta", "agent-command.txt"),
              "# the agent adapter\n%s --prompt {prompt}\n" % os.path.join(root, "agent"))
        os.environ.pop("BRAIN_AGENT_CMD", None)
        rc, _ = quiet(T.main, ["--force", "routine-a"])
        check("the agent command comes from the vault's agent-command.txt when no variable is set",
              rc == 0, rc)

        rc, out = quiet(T.main, ["--list"])
        check("--list shows agent routines with their status",
              "routine-a" in out and "type=agent" in out and "disabled" in out, out)

        print("\n== the routine preflight: what this machine lacks refuses the run ==")
        root, args_file = setup(T)
        source = FakeTokenSource(FAKE_TOKEN)
        T.token_source = lambda: source
        write(os.path.join(T.VAULT, "90-Meta", "routines", "routine-a.md"),
              '---\nid: routine-a\nneeds_bridge: none\nrequires: {"programs": ["no-such-program-for-this-test"], '
              '"repos": ["repos/missing"]}\n---\n\nSummarise the day in one line.\n')
        rc, _ = quiet(T.main, ["--force", "routine-a"])
        alert = {c[0]: c[1] for c in T.raise_alert.calls}.get("routine:routine-a", "")
        check("a routine whose requirements are missing here is refused, exit 2",
              rc == 2 and json.load(open(T.STATE_FILE))["routine-a"]["last_exit"] == 2, rc)
        check("the agent never starts and the token pool is never read",
              not os.path.exists(args_file) and source.reads == 0 and not os.path.exists(T.ROUTINE_AUTH_STATE),
              (os.path.exists(args_file), source.reads))
        check("the alert names every gap and the preflight command",
              "no-such-program-for-this-test" in alert and "repos/missing" in alert
              and "routine_requires.py here" in alert, alert)
        write(os.path.join(T.VAULT, "90-Meta", "routines", "routine-a.md"),
              '---\nid: routine-a\nneeds_bridge: none\nrequires: {"programs": ["no quotes allowed": 1]}\n---\n\n'
              'Summarise the day in one line.\n')
        rc, _ = quiet(T.main, ["--force", "routine-a"])
        alert = {c[0]: c[1] for c in T.raise_alert.calls}.get("routine:routine-a", "")
        check("a requires line that does not parse refuses the run too",
              rc == 2 and "requires is not a JSON object" in alert and not os.path.exists(args_file), (rc, alert))
        os.makedirs(os.path.join(T.VAULT, "repos", "present", ".git"))
        write(os.path.join(T.VAULT, "90-Meta", "routines", "routine-a.md"),
              '---\nid: routine-a\nneeds_bridge: none\nrequires: {"programs": ["sh"], "repos": ["repos/present"]}'
              '\n---\n\nSummarise the day in one line.\n')
        rc, _ = quiet(T.main, ["--force", "routine-a"])
        check("a routine whose requirements are all here runs as before",
              rc == 0 and os.path.exists(args_file) and source.reads == 1, (rc, source.reads))

        print("\n== routine authentication ==")
        root, args_file = setup(T)
        write(os.path.join(T.VAULT, "90-Meta", "routines", "routine-a.md"),
              '---\nid: routine-a\nneeds_bridge: none\nagent_args: ["--permission-mode", "acceptEdits"]\n---\n\n'
              'Summarise the day in one line.\n')
        os.environ["ANTHROPIC_API_KEY"] = "parent-key-must-not-leak"
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = "parent-oauth-must-not-leak"
        try:
            rc, _ = quiet(T.main, ["--force", "routine-a"])
            quiet(T.main, ["--force", "routine-a"])
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        env_file = os.path.join(root, "agent-env.txt")
        env = dict(l.split("=", 1) for l in open(env_file).read().splitlines() if "=" in l) \
            if os.path.exists(env_file) else {}
        check("the agent gets the pool token read from KeePass as CLAUDE_CODE_OAUTH_TOKEN",
              rc == 0 and env.get("CLAUDE_CODE_OAUTH_TOKEN") == FAKE_TOKEN, (rc, sorted(env)))
        check("and no Anthropic credential of the parent", "ANTHROPIC_API_KEY" not in env, sorted(env))
        check("auto-update is off during the run", env.get("DISABLE_AUTOUPDATER") == "1", sorted(env))
        args = open(args_file).read().splitlines() if os.path.exists(args_file) else []
        check("the routine's agent_args follow the template, then its scratch directory",
              args[-4:-2] == ["--permission-mode", "acceptEdits"] and args[-2] == "--add-dir", args)
        scratch = env.get("BRAIN_ROUTINE_SCRATCH", "")
        check("the run exports its run id, its scratch directory under <brain state>/routine-scratch, and headless",
              env.get("BRAIN_ROUTINE_RUN_ID", "").startswith("routine-a-") and args[-1:] == [scratch]
              and os.path.dirname(scratch) == T.ROUTINE_SCRATCH_DIR
              and os.path.basename(scratch) == env.get("BRAIN_ROUTINE_RUN_ID") and env.get("BRAIN_HEADLESS") == "1",
              (args[-2:], {k: v for k, v in env.items() if k.startswith("BRAIN_")}))
        check("and where google.py send logs its sends", env.get("BRAIN_MAIL_SENT_LOG") == T.MAIL_SENT_LOG, env)
        check("a successful run's scratch directory is removed", scratch and not os.path.exists(scratch), scratch)
        pool_state = json.load(open(T.ROUTINE_AUTH_STATE)) if os.path.exists(T.ROUTINE_AUTH_STATE) else {}
        check("the pool state records the token as healthy",
              pool_state.get("routines-1", {}).get("status") == "healthy", pool_state)
        versions = os.path.join(root, "versions.txt")
        check("the CLI health check ran once for two runs in one process",
              os.path.exists(versions) and open(versions).read().count("--version") == 1)

        root, args_file = setup(T, agent_exit=1,
                                agent_body='echo "Failed to authenticate. API Error: 401 OAuth access token is invalid."')
        rc, _ = quiet(T.main, ["--force", "routine-a"])
        alert = {c[0]: c[1] for c in T.raise_alert.calls}.get("routine:routine-a", "")
        check("a refused token raises the routine alert with the renewal commands",
              rc == 1 and "claude setup-token" in alert
              and 'kp.py set "apis/claude-code-oauth-routines-1" --stdin' in alert, (rc, alert))
        pool_state = json.load(open(T.ROUTINE_AUTH_STATE)) if os.path.exists(T.ROUTINE_AUTH_STATE) else {}
        check("and marks the token dead", pool_state.get("routines-1", {}).get("status") == "dead", pool_state)
        raw = open(T.ROUTINE_AUTH_LOG).read() if os.path.exists(T.ROUTINE_AUTH_LOG) else ""
        check("its raw output is logged for calibration, redacted",
              "401 OAuth access token is invalid" in raw and FAKE_TOKEN not in raw, raw)

        print("\n== routine tokens assigned to machines ==")
        root, args_file = setup(T)
        assigned = dict(POOL["tokens"][0], machines=["studio-box"])
        write(os.path.join(T.VAULT, "90-Meta", "routine-tokens.json"), json.dumps({"tokens": [assigned]}))
        rc, _ = quiet(T.main, ["--force", "routine-a"])
        raised = {c[0]: c[1] for c in T.raise_alert.calls}
        config = raised.get("routine-auth:config", "")
        check("a pool with no token for this machine never reaches the agent or KeePass",
              rc != 0 and not os.path.exists(args_file) and T.token_source().reads == 0, (rc, T.token_source().reads))
        check("and the config alert names this machine and the machines field",
              "box" in config and "machines" in config, raised)

        root, args_file = setup(T)
        real_mine = T.machine_is_mine
        T.machine_is_mine = lambda m: m.strip().casefold() == "box-1a2b3c4d"
        try:
            assigned = dict(POOL["tokens"][0], machines=["studio-box", "BOX-1A2B3C4D"])
            write(os.path.join(T.VAULT, "90-Meta", "routine-tokens.json"), json.dumps({"tokens": [assigned]}))
            rc, _ = quiet(T.main, ["--force", "routine-a"])
        finally:
            T.machine_is_mine = real_mine
        check("a token assigned to this machine's key, in any case, is used",
              rc == 0 and T.token_source().reads == 1, (rc, T.token_source().reads))

        root, args_file = setup(T, token_value="tokenA tokenB")
        rc, _ = quiet(T.main, ["--force", "routine-a"])
        alert = {c[0]: c[1] for c in T.raise_alert.calls}.get("routine:routine-a", "")
        check("a malformed stored token never reaches the agent", rc != 0 and not os.path.exists(args_file), rc)
        check("its alert names the shape and the exact re-store command",
              "whitespace" in alert and "pbpaste | tr -d '[:space:]' | python3 ~/Brain/_bin/kp.py set "
              "\"apis/claude-code-oauth-routines-1\" --stdin" in alert, alert)
        check("and quotes no part of the stored value", "tokenA" not in alert and "tokenB" not in alert, alert)

        contract_routine = ('---\nid: routine-a\nneeds_bridge: none\n'
                            'success_contract: {"final_line": "ROUTINE_OK", "forbidden": ["EMAIL NOT SENT:"]}\n---\n\n'
                            'Summarise the day in one line.\n')
        root, args_file = setup(T, agent_body="printf '%s\\n' '{\"result\": \"done\\nEMAIL NOT SENT: no mail path\"}'")
        write(os.path.join(T.VAULT, "90-Meta", "routines", "routine-a.md"), contract_routine)
        rc, _ = quiet(T.main, ["--force", "routine-a"])
        alert = {c[0]: c[1] for c in T.raise_alert.calls}.get("routine:routine-a", "")
        check("an exit 0 that breaks the routine's success contract is a failure, exit 65",
              rc == 65 and json.load(open(T.STATE_FILE))["routine-a"]["last_exit"] == 65, rc)
        check("alerted with the routine id and the unmet conditions",
              "routine-a" in alert and "EMAIL NOT SENT:" in alert and "ROUTINE_OK" in alert, alert)
        root, args_file = setup(T, agent_body="printf '%s\\n' '{\"result\": \"done\\nROUTINE_OK\"}'")
        write(os.path.join(T.VAULT, "90-Meta", "routines", "routine-a.md"), contract_routine)
        rc, _ = quiet(T.main, ["--force", "routine-a"])
        check("a run that meets its contract succeeds and raises nothing",
              rc == 0 and "routine:routine-a" not in {c[0] for c in T.raise_alert.calls}, (rc, T.raise_alert.calls))

        print("\n== replaying the first real runs ==")
        delivery_routine = ('---\nid: routine-a\nneeds_bridge: [email]\n'
                            'success_contract: {"required_sends": 1, "sends_to": "me@example.com", '
                            '"forbidden": ["EMAIL NOT SENT:"]}\n---\n\n'
                            'Build the digest and email it.\n')
        send_record = ("printf '{\"ts\": \"2026-09-15T15:45:00+02:00\", \"to\": \"me@example.com\", "
                       "\"subject\": \"Digest 2026-09-15: 2 of 13\", \"message_id\": \"m-1\", "
                       "\"run_id\": \"%s\"}\\n' \"$BRAIN_ROUTINE_RUN_ID\" >> \"$BRAIN_MAIL_SENT_LOG\"")
        draft = 'echo "<p>draft</p>" > "$BRAIN_ROUTINE_SCRATCH/email.html"'

        def routine_alert():
            return {c[0]: c[1] for c in T.raise_alert.calls}.get("routine:routine-a", "")

        def child_env(root):
            path = os.path.join(root, "agent-env.txt")
            return dict(l.split("=", 1) for l in open(path).read().splitlines() if "=" in l) \
                if os.path.exists(path) else {}

        # (a) digest-now-agent: it sent, then ended on the librarian's summary.
        root, args_file = setup(T, agent_body="\n".join([
            send_record, draft,
            "printf '%s\\n' '{\"result\": \"Shortlist emailed.\\n\\nLibrarian agent launched in background to save "
            "the session.\"}'"]))
        write(os.path.join(T.VAULT, "90-Meta", "routines", "routine-a.md"), delivery_routine)
        rc, _ = quiet(T.main, ["--force", "routine-a"])
        env = child_env(root)
        sent = open(T.MAIL_SENT_LOG).read() if os.path.exists(T.MAIL_SENT_LOG) else ""
        check("a run that sent the email but ended on another summary line is a success",
              rc == 0 and routine_alert() == "", (rc, routine_alert()))
        check("its send record carries its own run id", env.get("BRAIN_ROUTINE_RUN_ID")
              and '"run_id": "%s"' % env.get("BRAIN_ROUTINE_RUN_ID") in sent, sent)
        check("and its scratch directory is gone", env.get("BRAIN_ROUTINE_SCRATCH")
              and not os.path.exists(env["BRAIN_ROUTINE_SCRATCH"]), env.get("BRAIN_ROUTINE_SCRATCH"))

        # (b) an answer that claims the email went out, with no record for this run.
        root, args_file = setup(T, agent_body="\n".join([
            draft,
            "printf '%s\\n' '{\"result\": \"sent to me@example.com: Digest 2026-09-15\\nROUTINE_OK\"}'"]))
        write(os.path.join(T.VAULT, "90-Meta", "routines", "routine-a.md"), delivery_routine)
        write(T.MAIL_SENT_LOG, json.dumps({"ts": "2026-09-14T06:10:00+02:00", "to": "me@example.com",
                                           "subject": "yesterday", "message_id": "m-0",
                                           "run_id": "routine-a-an-earlier-run"}) + "\n")
        rc, _ = quiet(T.main, ["--force", "routine-a"])
        env = child_env(root)
        alert = routine_alert()
        check("a run claiming \"email sent\" without a send record is a contract breach, exit 65",
              rc == 65 and json.load(open(T.STATE_FILE))["routine-a"]["last_exit"] == 65, rc)
        check("alerted naming the missing send and where it was looked for",
              "mail-sent.jsonl" in alert and "me@example.com" in alert, alert)
        kept = env.get("BRAIN_ROUTINE_SCRATCH", "")
        check("the failed run's scratch directory is kept, with what it wrote",
              kept and os.path.exists(os.path.join(kept, "email.html")), kept)
        runner_log = open(T.RUNNER_LOG).read() if os.path.exists(T.RUNNER_LOG) else ""
        check("the runner log names the run id and the kept scratch directory",
              env.get("BRAIN_ROUTINE_RUN_ID", "?") in runner_log and kept in runner_log, runner_log)

        # (c) example-routine-b-agent: the body arrived unframed and the model asked what to do.
        framed_routine = ('---\nid: routine-a\nneeds_bridge: [example-bridge]\n'
                         'success_contract: {"required": ["ROUTINE_OK"], "forbidden": ["ROUTINE_FAILED:"]}\n---\n\n'
                         '<!-- What it does: sweeps recent items into the vault.\n'
                         '     If the app task\'s prompt changes, update this copy too. -->\n\n'
                         'Capture the outlines of recent items into the Brain vault.\n')
        root, args_file = setup(T, agent_body=(
            "printf '%s\\n' '{\"type\": \"result\", \"result\": \"I don\\u0027t see an actual request in your message, "
            "just session context and reminders. What would you like me to help with?\"}'"))
        write(os.path.join(T.VAULT, "90-Meta", "routines", "routine-a.md"), framed_routine)
        rc, _ = quiet(T.main, ["--force", "routine-a"])
        alert = routine_alert()
        check("a reply asking for a request is a contract breach, exit 65", rc == 65, (rc, alert))
        check("with a clear reason: the routine was not run", "did not run the routine" in alert, alert)
        args = open(args_file).read() if os.path.exists(args_file) else ""
        check("the prompt the CLI got opened as an order to run it now, with the HTML comment stripped",
              args.startswith('--prompt\nYou are running the Brain routine "routine-a" unattended, right now')
              and "<!--" not in args and "What it does" not in args
              and "Capture the outlines of recent items" in args, args[:400])

        root, _ = setup(T)
        source = FakeTokenSource(FAKE_TOKEN)
        T.token_source = lambda: source
        rc, _ = quiet(T.main, ["--force", "shell-ok"])
        check("a shell row runs as before and never reads a token", rc == 0 and source.reads == 0, (rc, source.reads))

        print("\n== the model a routine runs on, and the repair attempt ==")
        import model_fallback as MF
        CHEAP, STRONG = MF.MODELS[0], MF.DEFAULT_FALLBACK
        CHEAP_ROUTINE = ("---\nid: routine-a\nneeds_bridge: none\nmodel: %s\n---\n\nSummarise the day in one line.\n"
                         % CHEAP)
        calls_body = 'echo "=== CALL ===" >> "%s"; echo "$*" >> "%s"; case "$*" in *"--model ' + CHEAP + '"*) echo first-try-failed; exit 3;; esac; echo fixed'
        calls = os.path.join(tmpdir(), "calls.txt")
        root, args_file = setup(T, agent_body=calls_body % (calls, calls))
        write(os.path.join(T.VAULT, "90-Meta", "routines", "routine-a.md"),
              CHEAP_ROUTINE)
        rc, _ = quiet(T.main, ["--force", "routine-a"])
        runs = [c for c in read_text(calls).split("=== CALL ===\n") if c.strip()]
        check("the first attempt runs on the routine's model", runs and "--model " + CHEAP in runs[0], runs[:1])
        check("a failure a better model can help with gets one repair attempt on the fallback model",
              rc == 0 and len(runs) == 2 and "--model " + STRONG in runs[1] and "--model " + CHEAP not in runs[1],
              (rc, [r[-120:] for r in runs]))
        last = runs[-1] if runs else ""
        check("whose prompt is the repair prompt, with the failed attempt's answer",
              "REPAIR RUN ON " + STRONG.upper() in last and "first-try-failed" in last, last[:300])
        check("and which may edit the procedure and sync it", "install_plugin.py sync" in last, last[-400:])
        check("a repaired run raises no routine alert",
              "routine:routine-a" not in {c[0] for c in T.raise_alert.calls}, T.raise_alert.calls)
        check("the runner log names both models",
              "repair attempt on " + STRONG in read_text(T.RUNNER_LOG), read_text(T.RUNNER_LOG)[-400:])

        root, args_file = setup(T, agent_body='echo "$*" >> "%s"; exit 3' % os.path.join(tmpdir(), "unused"))
        write(os.path.join(T.VAULT, "90-Meta", "routines", "routine-a.md"),
              CHEAP_ROUTINE)
        rc, _ = quiet(T.main, ["--force", "routine-a"])
        alert = {c[0]: c[1] for c in T.raise_alert.calls}.get("routine:routine-a", "")
        check("when the repair fails too the alert names both attempts",
              rc != 0 and "failed on " + CHEAP in alert and "and on " + STRONG in alert, (rc, alert))

        calls = os.path.join(tmpdir(), "calls.txt")
        root, args_file = setup(T, agent_exit=1,
                                agent_body='echo "=== CALL ===" >> "%s"; echo run >> "%s"; echo "Failed to authenticate. API Error: 401 OAuth '
                                           'access token is invalid."' % (calls, calls))
        write(os.path.join(T.VAULT, "90-Meta", "routines", "routine-a.md"),
              CHEAP_ROUTINE)
        rc, _ = quiet(T.main, ["--force", "routine-a"])
        runs = [c for c in read_text(calls).split("=== CALL ===\n") if c.strip()]
        check("a refused token gets no repair attempt: a better model cannot fix it",
              rc != 0 and len(runs) == 1, (rc, len(runs)))

        unused = os.path.join(tmpdir(), "calls.txt")
        root, args_file = setup(T, agent_body=calls_body % (unused, unused))
        rc, _ = quiet(T.main, ["--force", "routine-a"])
        args = read_text(args_file).splitlines()
        check("a routine with no model adds no --model of its own", rc == 0 and "--model" not in args, args[-6:])

        preamble_tests(T)

        state_tests(T)

        print("\n== the real alert hook ==")
        T.raise_alert, T.clear_alert = saved["raise_alert"], saved["clear_alert"]
        brain_state = tmpdir()
        os.environ["BRAIN_STATE"] = brain_state
        T.raise_alert("routine:probe", "routine probe failed: exit=1")
        raised = os.path.join(brain_state, "guardian-raised.json")
        check("tasks.raise_alert records the alert where the guardian reads it (BRAIN_STATE)",
              os.path.exists(raised) and "routine:probe" in json.load(open(raised)), raised)
        T.clear_alert("routine:probe")
        check("tasks.clear_alert removes it", "routine:probe" not in json.load(open(raised)))
        blocker = write(os.path.join(tmpdir(), "a-file"), "in the way")
        os.environ["BRAIN_STATE"] = os.path.join(blocker, "state")
        try:
            T.raise_alert("routine:probe", "cannot be written")
            broke = None
        except Exception as exc:
            broke = exc
        check("an alert that cannot be written never breaks the runner", broke is None, repr(broke))
    finally:
        for k, v in saved.items():
            setattr(T, k, v)
        for name, value in (("BRAIN_AGENT_CMD", old_cmd), ("BRAIN_STATE", old_state)):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    return finish()


def preamble_tests(T):
    print("\n== the shared routine preamble ==")
    chrome = ('agent_args: ["--chrome", "--allowedTools", "Read,mcp__claude-in-chrome__navigate"]\n')
    fm = lambda extra="": "---\nid: routine-a\n%s---\n\nDo the work.\n" % extra
    check("no key and no browser: the default is humanizer alone",
          T.preamble_blocks(fm()) == (["humanizer"], None), T.preamble_blocks(fm()))
    check("no key and Claude in Chrome allowed: humanizer and browser_restart",
          T.preamble_blocks(fm(chrome)) == (["humanizer", "browser_restart"], None), T.preamble_blocks(fm(chrome)))
    got = T.preamble_blocks(fm("preamble: [browser_restart, humanizer, humanizer]\n"))
    check("an explicit list is taken as it is, in the canonical order, each block once",
          got == (["humanizer", "browser_restart"], None), got)
    got = T.preamble_blocks(fm(chrome + "preamble: [humanizer]\n"))
    check("an explicit list replaces the default, browser included", got == (["humanizer"], None), got)
    check("`preamble: []` asks for no block", T.preamble_blocks(fm("preamble: []\n")) == ([], None))
    check("quoted names are accepted",
          T.preamble_blocks(fm('preamble: ["humanizer", "browser_restart"]\n')) == (["humanizer", "browser_restart"], None))
    blocks, problem = T.preamble_blocks(fm("preamble: [humaniser]\n"))
    check("an unknown block name is a problem that names it", problem and "humaniser" in problem, problem)
    check("`preamble:` in the body does not count",
          T.preamble_blocks("---\nid: r\n---\npreamble: []\n") == (["humanizer"], None))

    root, args_file = setup(T)
    text = fm("preamble: [humanizer, browser_restart]\nsingle_instance: true\n")
    out, problem = T.with_preamble(text)
    check("with_preamble keeps the front matter as it is and puts the blocks between it and the body",
          problem is None and out.startswith(text.split("\n---\n")[0] + "\n---\n")
          and out.index("HUMANIZER (test)") < out.index("BROWSER (test)") < out.index("Do the work."), out)
    check("the blocks' own front matter and HTML comments are not copied",
          "preamble-humanizer" not in out and "who uses it" not in out, out)
    check("the parsers still read the front matter after the blocks go in",
          T.routine_timeout(out) == T.routine_timeout(text) and T.preamble_blocks(out) == T.preamble_blocks(text))
    twice, _ = T.with_preamble(out)
    check("no duplication: a text that already carries a block does not get it again",
          twice.count("HUMANIZER (test)") == 1 and twice.count("BROWSER (test)") == 1, twice)
    legacy = fm() .replace("Do the work.", "HUMANIZER (an older wording): the old copy.\n\nDo the work.")
    out, _ = T.with_preamble(legacy)
    check("a routine body that still has its own copy of a block keeps one copy only",
          out.count("HUMANIZER (") == 1 and "the old copy" in out, out)
    check("a block named only in prose does not count as a copy",
          T.with_preamble(fm().replace("Do the work.", "See HUMANIZER above."))[0].count("HUMANIZER (test)") == 1)
    out, _ = T.with_preamble("no front matter at all\n")
    check("a routine with no front matter gets the default block before its text",
          out.index("HUMANIZER (test)") < out.index("no front matter at all"), out)

    os.remove(os.path.join(T.VAULT, "90-Meta", "routines", "_preamble", "browser_restart.md"))
    out, problem = T.with_preamble(text)
    check("a missing block file is a problem that names the file", problem and "browser_restart" in problem, problem)
    write(os.path.join(T.VAULT, "90-Meta", "routines", "routine-a.md"), text)
    rc, _ = quiet(T.main, ["--force", "routine-a"])
    alert = [c for c in T.raise_alert.calls if c[0] == "routine:routine-a"]
    check("and the run is refused before the agent starts, exit 2, with the alert naming the block",
          rc == 2 and not os.path.exists(args_file) and alert and "browser_restart" in alert[-1][1], (rc, alert))

    root, args_file = setup(T)
    write(os.path.join(T.VAULT, "90-Meta", "routines", "routine-a.md"),
          fm('preamble: [browser_restart]\n'))
    rc, _ = quiet(T.main, ["--force", "routine-a"])
    args = open(args_file).read() if os.path.exists(args_file) else ""
    check("a forced run hands the agent exactly the declared blocks, each once",
          rc == 0 and args.count("BROWSER (test)") == 1 and "HUMANIZER (test)" not in args
          and args.index("BROWSER (test)") < args.index("Do the work."), args[:600])

    root, args_file = setup(T)
    write(os.path.join(T.VAULT, "90-Meta", "routines", "routine-a.md"), fm(chrome))
    rc, out = quiet(T.main, ["--prompt", "routine-a"])
    check("--prompt <id> prints the whole framed prompt with its blocks and runs nothing",
          rc == 0 and not os.path.exists(args_file)
          and out.startswith('You are running the Brain routine "routine-a" unattended, right now')
          and out.count("HUMANIZER (test)") == 1 and out.count("BROWSER (test)") == 1
          and "this run has Claude in Chrome" in out and out.rstrip().endswith("Do the work."), out[:600])
    check("and leaves no state behind", not os.path.exists(T.STATE_FILE))
    rc2, out2 = quiet(T.main, ["--prompt", "90-Meta/routines/routine-a.md"])
    check("--prompt also takes a routine path, named by its file", rc2 == 0
          and out2.startswith('You are running the Brain routine "routine-a" unattended') and "BROWSER (test)" in out2,
          out2[:300])
    rc3, _ = quiet(T.main, ["--prompt", "no-such-task"])
    check("--prompt with an unknown id fails with exit 2", rc3 == 2, rc3)


def real_vault_preamble_tests(T, vault):
    """The real vault's blocks exist and every routine names only known blocks (read only)."""
    print("\n== the real vault's routine preamble ==")
    pre = os.path.join(vault, "90-Meta", "routines", "_preamble")
    check("every block the runner knows has its file in 90-Meta/routines/_preamble",
          all(os.path.isfile(os.path.join(pre, n + ".md")) for n in T.PREAMBLE_ORDER),
          sorted(os.listdir(pre)) if os.path.isdir(pre) else "missing")
    routines = os.path.join(vault, "90-Meta", "routines")
    bad = []
    for name in sorted(os.listdir(routines)):
        if name.endswith(".md"):
            _, problem = T.preamble_blocks(open(os.path.join(routines, name)).read())
            if problem:
                bad.append((name, problem))
    check("every routine file names only known blocks", not bad, bad)
    from routine_auth_core import domain as RD
    pkill, no_tool = [], []
    for name in sorted(os.listdir(routines)):
        if not name.endswith(".md"):
            continue
        text = open(os.path.join(routines, name)).read()
        args, _ = RD.parse_agent_args(text)
        allowed = " ".join(args)
        if "pkill -x chrome" in allowed:
            pkill.append(name)
        blocks, _ = T.preamble_blocks(text)
        if "browser_restart" in blocks and "Bash(python3 ~/Brain/_bin/chrome_restart.py:*)" not in allowed:
            no_tool.append(name)
    check("no routine may run `pkill -x chrome` (it kills other tasks' headless renders)", not pkill, pkill)
    check("every routine with browser_restart may run chrome_restart.py", not no_tool, no_tool)


def finish():
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
