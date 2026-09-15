#!/usr/bin/env python3
# brain:allow-secrets (synthetic token-shaped values only, never a real credential)
"""Tests for routine_auth_core.application: run_routine, the bounded failover loop.

Every port is an in-memory fake that records what was asked of it; CLI outcomes come from
the recorded fixtures. No file, subprocess, KeePass, network or clock is touched. Run
standalone:

    python3 _bin/routine_auth_core/application_test.py
"""
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[0] = os.path.dirname(HERE)

ok, fail = [], []

TOK = {"a": "sk-ant-oat01-" + "aaaA1_-" * 12, "b": "sk-ant-oat01-" + "bbbB2_-" * 12,
       "c": "sk-ant-oat01-" + "cccC3_-" * 12, "d": "sk-ant-oat01-" + "dddD4_-" * 12,
       "e": "sk-ant-oat01-" + "eeeE5_-" * 12}
NOW = dt.datetime(2026, 9, 15, 13, 0, 0)


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


# ---------------------------------------------------------------- fakes


class FakePool:
    def __init__(self, labels=("a",), error=None):
        self.labels, self.error = list(labels), error

    def entries(self):
        if self.error:
            raise self.error
        return [D.PoolEntry(l, "kp://Brain/apis/claude-code-oauth-routines-%s" % l, dt.date(2026, 9, 15),
                            account="routines") for l in self.labels]


class FakeTokens:
    def __init__(self, values=None, error=None):
        self.values = dict(TOK if values is None else values)
        self.error = error
        self.reads = []

    def read(self, kp_ref, timeout):
        self.reads.append((kp_ref, timeout))
        if self.error:
            raise self.error
        return self.values[kp_ref.rsplit("-", 1)[-1]]


class FakeState:
    def __init__(self, data=None):
        self.data, self.saves = dict(data or {}), 0

    def load(self):
        return dict(self.data)

    def save(self, data):
        self.saves += 1
        self.data = dict(data)


class FakeClock:
    def __init__(self, step=10.0):
        self.t, self.step = 0.0, step

    def now(self):
        return NOW

    def monotonic(self):
        return self.t


class FakeCli:
    def __init__(self, status=None):
        self.status = status or D.CliStatus(True, "/h/.local/bin/claude", "2.1.272")
        self.checks = 0

    def check(self):
        self.checks += 1
        return self.status


class FakeRunner:
    """Each call pops the next outcome: a fixture name, a (rc, stdout, stderr) triple, or a callable
    given the recorded call (so a fake run can write a send record under its own run id)."""

    def __init__(self, outcomes, clock=None, cost_s=10.0):
        self.outcomes, self.clock, self.cost_s = list(outcomes), clock, cost_s
        self.calls = []

    def run(self, prompt, agent_args, env, timeout):
        self.calls.append({"prompt": prompt, "args": list(agent_args), "env": dict(env), "timeout": timeout})
        if self.clock:
            self.clock.t += self.cost_s
        out = self.outcomes.pop(0) if self.outcomes else "ok_json"
        if callable(out):
            return out(self.calls[-1])
        if isinstance(out, str):
            fx = FIXTURES[out]
            return fx["exit_code"], fx["stdout"], fx["stderr"]
        return out


class FakeRawLog:
    def __init__(self):
        self.records = []

    def record(self, routine_id, label, cls, rc, stdout, stderr, secrets=(), run_id=None):
        self.records.append({"routine": routine_id, "label": label, "kind": cls.kind, "rc": rc,
                             "secrets": list(secrets), "run_id": run_id})


class FakeScratch:
    def __init__(self, fail=False):
        self.created, self.removed, self.pruned, self.fail = [], [], [], fail

    def create(self, run_id):
        if self.fail:
            raise OSError("read-only file system")
        path = "/state/routine-scratch/" + run_id
        self.created.append(path)
        return path

    def remove(self, path):
        self.removed.append(path)

    def prune(self, now):
        self.pruned.append(now)
        return []


class FakeRunIds:
    def __init__(self):
        self.n = 0

    def new(self, routine_id, now):
        self.n += 1
        return "%s-run%d" % (routine_id, self.n)


class FakeSends:
    def __init__(self, records=None):
        self.log = list(records or [])

    def records(self):
        return list(self.log)


class FakeAlerts:
    def __init__(self):
        self.raised, self.cleared = {}, []

    def raise_alert(self, key, summary, severity="fail"):
        self.raised[key] = (severity, summary)

    def clear_alert(self, key):
        self.cleared.append(key)


def ports(labels=("a",), outcomes=(), tokens=None, state=None, cli=None, pool_error=None, clock=None,
          cost_s=10.0, base_env=None, scratch=None, sends=None, run_env=None):
    clock = clock or FakeClock()
    return A.Ports(pool=FakePool(labels, pool_error), tokens=tokens or FakeTokens(), state=FakeState(state),
                   clock=clock, cli=cli or FakeCli(), runner=FakeRunner(outcomes, clock, cost_s),
                   raw_log=FakeRawLog(), alerts=FakeAlerts(),
                   base_env=dict(base_env if base_env is not None else BASE_ENV), kp_timeout=20,
                   scratch=scratch or FakeScratch(), run_ids=FakeRunIds(), sends=sends or FakeSends(),
                   run_env=dict(run_env or {}))


BASE_ENV = {"HOME": "/h", "PATH": "/usr/bin:/bin", "USER": "someone", "LANG": "en_US.UTF-8",
            "ANTHROPIC_API_KEY": "parent-api-key", "ANTHROPIC_AUTH_TOKEN": "parent-auth",
            "ANTHROPIC_BASE_URL": "https://proxy.example", "CLAUDE_CODE_OAUTH_TOKEN": "parent-oauth",
            "CLAUDE_CODE_USE_BEDROCK": "1", "AWS_ACCESS_KEY_ID": "AKIAEXAMPLE", "AWS_PROFILE": "x",
            "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/sa.json", "CLAUDE_CODE_USE_VERTEX": "1",
            "BRAIN_VAULT": "/h/Brain", "SOME_RANDOM_VAR": "not inherited"}


def routine(agent_args=(), problem=None, text="---\nid: r\n---\n\nBuild the digest.\n"):
    return A.Routine("digest-now-agent", "/h/Brain/90-Meta/routines/digest-now.md", tuple(agent_args), problem,
                     text=text)


def no_token_anywhere(p, result):
    blob = repr(result.summary) + repr(result.attempts) + repr(p.alerts.raised) + repr(p.state.data) \
        + repr([{k: v for k, v in r.items() if k != "secrets"} for r in p.raw_log.records])
    # The prefix alone may appear: a malformed-token summary names the shape it expected.
    return not any(t in blob or t[len("sk-ant-oat01-"):] in blob for t in TOK.values())


# ---------------------------------------------------------------- tests


def test_success():
    print("\n== one healthy token ==")
    p = ports(outcomes=["ok_json"])
    res = A.run_routine(p, routine(["--permission-mode", "acceptEdits"]), budget_s=1800)
    call = p.runner.calls[0] if p.runner.calls else {"env": {}, "args": []}
    env = call["env"]
    check("a good run exits 0 with no summary", res.rc == 0 and res.kind == D.OK and res.summary == "", res)
    check("the CLI gets the pool token as CLAUDE_CODE_OAUTH_TOKEN, never the parent's",
          env.get("CLAUDE_CODE_OAUTH_TOKEN") == TOK["a"], sorted(env))
    leaked = [k for k in env if k.startswith(("ANTHROPIC_", "AWS_", "CLAUDE_CODE_USE_", "GOOGLE_APPLICATION"))]
    check("no Anthropic or cloud provider credential of the parent reaches it", leaked == [], leaked)
    check("the environment is built from scratch, not copied", "SOME_RANDOM_VAR" not in env, sorted(env))
    check("it keeps what a CLI needs to run", env.get("HOME") == "/h" and env.get("PATH") and env.get("LANG"), env)
    check("auto-update is off during a routine run", env.get("DISABLE_AUTOUPDATER") == "1", env)
    check("the routine's own agent_args reach the runner, before the scratch directory",
          call["args"][:2] == ["--permission-mode", "acceptEdits"] and call["args"][2:3] == ["--add-dir"], call)
    check("the token was read with the KeePass timeout", p.tokens.reads == [("kp://Brain/apis/claude-code-oauth-routines-a", 20)],
          p.tokens.reads)
    check("the token is marked healthy", p.state.data.get("a", {}).get("status") == D.HEALTHY, p.state.data)
    check("a good run clears the CLI, KeePass and config alerts",
          {"cli:health", "routine-auth:keepass", "routine-auth:config"} <= set(p.alerts.cleared), p.alerts.cleared)
    check("nothing is written to the raw-output log", p.raw_log.records == [])
    check("the CLI health is checked", p.cli.checks == 1)


def test_failover():
    print("\n== failover ==")
    p = ports(labels=("a", "b"), outcomes=["auth_invalid_text", "ok_json"])
    res = A.run_routine(p, routine(), budget_s=1800)
    check("a refused token fails over to the next and the run succeeds",
          res.rc == 0 and [c["env"]["CLAUDE_CODE_OAUTH_TOKEN"] for c in p.runner.calls] == [TOK["a"], TOK["b"]],
          res)
    check("the refused token is dead, the next healthy", p.state.data["a"]["status"] == D.DEAD
          and p.state.data["b"]["status"] == D.HEALTHY, p.state.data)
    check("state is saved after every attempt", p.state.saves == 2, p.state.saves)
    check("the failed attempt's raw output is logged, redacted with the token that was used",
          len(p.raw_log.records) == 1 and p.raw_log.records[0]["label"] == "a"
          and TOK["a"] in p.raw_log.records[0]["secrets"], p.raw_log.records)
    check("the attempts are listed by label and kind", [(x.label, x.kind) for x in res.attempts]
          == [("a", D.AUTH_INVALID), ("b", D.OK)], res.attempts)
    check("no token value anywhere in what the run reports", no_token_anywhere(p, res))

    p = ports(outcomes=["auth_invalid_json"])
    res = A.run_routine(p, routine(), budget_s=1800)
    check("a single refused token is a failure naming the renewal", res.rc == 1 and res.kind == D.AUTH_INVALID
          and "claude setup-token" in res.summary
          and D.restore_command("kp://Brain/apis/claude-code-oauth-routines-a") in res.summary, res.summary)
    check("and still no token value anywhere", no_token_anywhere(p, res))

    p = ports(labels=("a", "b"), outcomes=["usage_limit_text", "ok_json"])
    res = A.run_routine(p, routine(), budget_s=1800)
    check("a usage limit rests the token and fails over", res.rc == 0 and p.state.data["a"]["status"] == D.LIMITED,
          p.state.data)

    p = ports(labels=("a", "b"), outcomes=["network_text", "ok_json"])
    res = A.run_routine(p, routine(), budget_s=1800)
    check("a network failure retries the same token",
          res.rc == 0 and [c["env"]["CLAUDE_CODE_OAUTH_TOKEN"] for c in p.runner.calls] == [TOK["a"], TOK["a"]],
          [c["env"]["CLAUDE_CODE_OAUTH_TOKEN"][-6:] for c in p.runner.calls])

    p = ports(labels=("a", "b", "c"), outcomes=["unknown"])
    res = A.run_routine(p, routine(), budget_s=1800)
    check("an unknown failure stops: one attempt, no failover", res.rc == 1 and len(p.runner.calls) == 1
          and res.kind == D.UNKNOWN and "routine-auth.log" in res.summary, res)
    check("and its raw output is logged for calibration", len(p.raw_log.records) == 1)
    check("an unknown failure says nothing about the token", p.state.data["a"]["status"] == D.HEALTHY, p.state.data)

    p = ports(labels=("a", "b", "c", "d", "e"), outcomes=["auth_invalid_text"] * 5)
    res = A.run_routine(p, routine(), budget_s=1800)
    check("at most three attempts per run", len(p.runner.calls) == 3 and res.rc == 1, len(p.runner.calls))
    check("the summary lists what was tried", "a" in res.summary and "c" in res.summary, res.summary)


def test_malformed():
    print("\n== a malformed stored value ==")
    values = dict(TOK, a="token: " + TOK["a"])
    p = ports(outcomes=[], tokens=FakeTokens(values))
    res = A.run_routine(p, routine(), budget_s=1800)
    check("is caught before the CLI runs", p.runner.calls == [] and res.kind == D.TOKEN_MALFORMED, res)
    check("names the shape and the exact re-store command",
          "whitespace" in res.summary
          and "pbpaste | tr -d '[:space:]' | python3 ~/Brain/_bin/kp.py set \"apis/claude-code-oauth-routines-a\" --stdin"
          in res.summary, res.summary)
    check("quotes no part of the stored value", TOK["a"][13:] not in res.summary and no_token_anywhere(p, res),
          res.summary)
    check("and marks the token dead", p.state.data["a"]["status"] == D.DEAD, p.state.data)
    p = ports(labels=("a", "b"), outcomes=["ok_json"], tokens=FakeTokens(values))
    res = A.run_routine(p, routine(), budget_s=1800)
    check("a malformed token fails over to the next one", res.rc == 0
          and [c["env"]["CLAUDE_CODE_OAUTH_TOKEN"] for c in p.runner.calls] == [TOK["b"]], res)


def test_stops():
    print("\n== what stops a run before or without failover ==")
    from routine_auth_core.ports import TokenUnavailable

    p = ports(labels=("a", "b", "c"), tokens=FakeTokens(error=TokenUnavailable(D.KEEPASS_LOCKED, "KeePass is locked")))
    res = A.run_routine(p, routine(), budget_s=1800)
    check("a locked KeePass never runs the CLI and never fails over",
          p.runner.calls == [] and len(p.tokens.reads) == 1 and res.kind == D.KEEPASS_LOCKED, res)
    check("it raises the KeePass alert, not a token alert",
          "routine-auth:keepass" in p.alerts.raised and res.rc == 75, (p.alerts.raised, res.rc))
    check("and leaves the token's status alone", p.state.data.get("a", {}).get("status", D.HEALTHY) == D.HEALTHY,
          p.state.data)

    p = ports(cli=FakeCli(D.CliStatus(False, detail="agent command not found: /nonexistent/claude")))
    res = A.run_routine(p, routine(), budget_s=1800)
    check("an unhealthy CLI reads no token and runs nothing", p.tokens.reads == [] and p.runner.calls == [], res)
    check("it is exit 127 with the CLI alert and the reason", res.rc == 127 and "cli:health" in p.alerts.raised
          and "/nonexistent/claude" in res.summary, (res, p.alerts.raised))

    p = ports(pool_error=D.PoolConfigError("the pool has no tokens"))
    res = A.run_routine(p, routine(), budget_s=1800)
    check("an invalid pool config runs nothing and raises the config alert",
          p.runner.calls == [] and res.kind == D.CONFIG and "routine-auth:config" in p.alerts.raised and res.rc == 78,
          (res, p.alerts.raised))

    later = (NOW + dt.timedelta(hours=2)).isoformat(timespec="seconds")
    p = ports(state={"a": {"status": D.LIMITED, "until": later}})
    res = A.run_routine(p, routine(), budget_s=1800)
    check("when every token is limited, nothing runs and the summary says until when",
          p.runner.calls == [] and p.tokens.reads == [] and res.kind == D.NO_TOKEN and later in res.summary, res)


def test_budget_and_args():
    print("\n== the time budget and agent_args ==")
    clock = FakeClock()
    p = ports(labels=("a", "b", "c"), outcomes=["auth_invalid_text"] * 3, clock=clock, cost_s=1700)
    res = A.run_routine(p, routine(), budget_s=1800)
    check("the first attempt gets the whole budget", p.runner.calls and p.runner.calls[0]["timeout"] == 1800,
          [c["timeout"] for c in p.runner.calls])
    check("failover never exceeds the total budget", len(p.runner.calls) == 2
          and p.runner.calls[1]["timeout"] <= 100, [c["timeout"] for c in p.runner.calls])

    clock = FakeClock()
    p = ports(labels=("a", "b"), outcomes=["auth_invalid_text"] * 2, clock=clock, cost_s=1780)
    A.run_routine(p, routine(), budget_s=1800)
    check("no attempt starts when less than a minute is left", len(p.runner.calls) == 1, len(p.runner.calls))

    p = ports(outcomes=["ok_json"])
    A.run_routine(p, routine(problem="agent_args is not a JSON list of strings: ignored"), budget_s=1800)
    check("malformed agent_args raise a warning and the run goes ahead",
          p.alerts.raised.get("routine-args:digest-now-agent", ("",))[0] == "warn" and len(p.runner.calls) == 1,
          p.alerts.raised)
    p = ports(outcomes=["ok_json"])
    A.run_routine(p, routine(), budget_s=1800)
    check("well-formed agent_args clear that warning", "routine-args:digest-now-agent" in p.alerts.cleared,
          p.alerts.cleared)


def test_contract():
    import json

    print("\n== the success contract ==")
    contract = D.SuccessContract("ROUTINE_OK", (), ("EMAIL NOT SENT:",))

    def with_contract(c=contract, problem=None):
        return A.Routine("digest-now-agent", "/h/Brain/90-Meta/routines/digest-now.md", (), None,
                         contract=c, contract_problem=problem)

    p = ports(labels=("a", "b"), outcomes=["ok_json"])
    res = A.run_routine(p, with_contract(), budget_s=1800)
    check("exit 0 without the contract's final line is a contract breach, exit 65",
          res.rc == 65 and res.kind == D.CONTRACT_BREACH and "ROUTINE_OK" in res.summary, res)
    check("it never fails over: the token did its job", len(p.runner.calls) == 1
          and p.state.data["a"]["status"] == D.HEALTHY, (len(p.runner.calls), p.state.data))
    check("its raw output is logged for a person to read",
          [r["kind"] for r in p.raw_log.records] == [D.CONTRACT_BREACH], p.raw_log.records)
    check("and no token value appears anywhere", no_token_anywhere(p, res))

    p = ports(outcomes=[(0, json.dumps({"result": "report sent\nROUTINE_OK"}), "")])
    res = A.run_routine(p, with_contract(), budget_s=1800)
    check("a run meeting its contract is ok", res.rc == 0 and res.kind == D.OK and res.summary == "", res)

    p = ports(outcomes=[(0, json.dumps({"result": "EMAIL NOT SENT: no mail path\nROUTINE_OK"}), "")])
    res = A.run_routine(p, with_contract(), budget_s=1800)
    check("a forbidden marker is a breach naming it", res.rc == 65 and "EMAIL NOT SENT:" in res.summary, res.summary)

    p = ports(outcomes=["ok_json"])
    res = A.run_routine(p, routine(), budget_s=1800)
    check("a routine with no contract keeps today's behaviour", res.rc == 0 and res.kind == D.OK, res)

    p = ports(outcomes=[(0, json.dumps({"result": "fine\nROUTINE_OK"}), "")])
    res = A.run_routine(p, with_contract(None, "success_contract is not a JSON object"), budget_s=1800)
    check("an unreadable contract is a breach, never a silent success",
          res.rc == 65 and "success_contract" in res.summary, res)

    p = ports(outcomes=["auth_invalid_text"])
    res = A.run_routine(p, with_contract(), budget_s=1800)
    check("a failed run keeps its own classification", res.kind == D.AUTH_INVALID and res.rc == 1, res)


def test_permissions():
    print("\n== agent_args permissions ==")
    for args in (["--allowedTools", "Read,Bash"], ["--dangerously-skip-permissions"],
                 ["--permission-mode", "bypassPermissions"]):
        p = ports(outcomes=["ok_json"])
        res = A.run_routine(p, routine(args), budget_s=1800)
        check("%s is a config failure before the CLI runs or a token is read" % " ".join(args),
              res.rc == 78 and res.kind == D.CONFIG and p.runner.calls == [] and p.tokens.reads == [], res)
        raised = p.alerts.raised.get("routine-permissions:digest-now-agent")
        check("raising routine-permissions:<id> as a failure naming the problem",
              raised and raised[0] == "fail" and "agent_args" in raised[1], p.alerts.raised)
    p = ports(outcomes=["ok_json"])
    res = A.run_routine(p, routine(["--allowedTools", "Read,Bash(jq:*)"]), budget_s=1800)
    check("narrow patterns run, and clear that alert",
          res.rc == 0 and "routine-permissions:digest-now-agent" in p.alerts.cleared, (res, p.alerts.cleared))


def test_framing_and_scratch():
    print("\n== each attempt: a run id, a framed prompt, a scratch directory ==")
    text = "---\nid: r\nagent_args: [\"x\"]\n---\n\n<!-- a note for people, not for the agent -->\nDo the whole sweep.\n"
    p = ports(outcomes=["ok_json"], run_env={"BRAIN_MAIL_SENT_LOG": "/state/logs/mail-sent.jsonl"})
    res = A.run_routine(p, routine(["--permission-mode", "acceptEdits"], text=text), budget_s=1800)
    call = p.runner.calls[0] if p.runner.calls else {"prompt": "", "args": [], "env": {}}
    rid = "digest-now-agent-run1"
    scratch = "/state/routine-scratch/" + rid
    check("the runner gets the framed prompt: the wrapper, then the body without frontmatter or comments",
          call["prompt"] == D.frame_prompt("digest-now-agent", "Do the whole sweep.", rid, scratch),
          call["prompt"][:240])
    check("the scratch directory is added with --add-dir after the routine's own args",
          call["args"] == ["--permission-mode", "acceptEdits", "--add-dir", scratch], call["args"])
    env = call["env"]
    check("the child env carries the run id, the scratch directory, headless and the runner's extra variables",
          env.get("BRAIN_ROUTINE_RUN_ID") == rid and env.get("BRAIN_ROUTINE_SCRATCH") == scratch
          and env.get("BRAIN_HEADLESS") == "1" and env.get("BRAIN_MAIL_SENT_LOG") == "/state/logs/mail-sent.jsonl",
          {k: v for k, v in env.items() if k.startswith("BRAIN_")})
    check("a successful attempt's scratch directory is removed", p.scratch.removed == [scratch], p.scratch.removed)
    check("old scratch directories are pruned once per run", p.scratch.pruned == [NOW], p.scratch.pruned)
    check("the attempt and the result name the run id", res.attempts and res.attempts[0].run_id == rid
          and res.run_id == rid, res)

    p = ports(labels=("a", "b"), outcomes=["auth_invalid_text", "ok_json"])
    res = A.run_routine(p, routine(), budget_s=1800)
    ids = [c["env"].get("BRAIN_ROUTINE_RUN_ID") for c in p.runner.calls]
    check("every attempt gets its own run id and scratch directory",
          len(ids) == 2 and None not in ids and len(set(ids)) == 2 and len(set(p.scratch.created)) == 2,
          (ids, p.scratch.created))
    check("a failed attempt's scratch directory is kept, the successful one removed",
          len(p.scratch.created) == 2 and p.scratch.removed == [p.scratch.created[1]], (p.scratch.created, p.scratch.removed))
    check("the failed attempt says where its scratch directory was kept",
          len(res.attempts) == 2 and res.attempts[0].scratch == p.scratch.created[0] and res.attempts[1].scratch is None,
          res.attempts)
    check("the raw log names the failed attempt's run id", [r["run_id"] for r in p.raw_log.records] == ids[:1],
          p.raw_log.records)

    p = ports(outcomes=["ok_json"], scratch=FakeScratch(fail=True))
    res = A.run_routine(p, routine(), budget_s=1800)
    call = p.runner.calls[0] if p.runner.calls else {"prompt": "", "args": [], "env": {}}
    check("a scratch directory that cannot be created does not stop the run, and the prompt says there is none",
          res.rc == 0 and "--add-dir" not in call["args"] and "no scratch directory" in call["prompt"].lower()
          and "BRAIN_ROUTINE_SCRATCH" not in call["env"], (res.rc, call["args"]))

    p = ports(outcomes=[], tokens=FakeTokens(dict(TOK, a="two words")))
    A.run_routine(p, routine(), budget_s=1800)
    check("no scratch directory is made for an attempt that never reaches the CLI", p.scratch.created == [],
          p.scratch.created)


def test_delivery():
    import json

    print("\n== delivery proved by the send log, not by the answer ==")
    contract = D.SuccessContract(None, (), ("EMAIL NOT SENT:",), 1, "me@example.com")
    earlier = {"ts": "2026-09-14T06:10:00+02:00", "to": "me@example.com", "subject": "Digest 2026-09-14",
               "message_id": "m-0", "run_id": "digest-now-agent-an-earlier-run"}

    def digest(c=contract):
        return A.Routine("digest-now-agent", "/h/Brain/90-Meta/routines/digest-now.md", (), None,
                         contract=c, text="Build the digest and email it.")

    sends = FakeSends([earlier])

    def sends_then_summarises(call):
        sends.log.append({"ts": "2026-09-15T15:45:00+02:00", "to": "me@example.com",
                          "subject": "Digest 2026-09-15: 2 of 13", "message_id": "m-1",
                          "run_id": call["env"].get("BRAIN_ROUTINE_RUN_ID")})
        return 0, json.dumps({"result": "Shortlist emailed.\n\nLibrarian agent launched in background to save notes."}), ""

    p = ports(outcomes=[sends_then_summarises], sends=sends)
    res = A.run_routine(p, digest(), budget_s=1800)
    check("a send recorded under this run's id is success, even when the answer ends on something else",
          res.rc == 0 and res.kind == D.OK and res.summary == "", res)
    check("and its scratch directory is removed", p.scratch.created and p.scratch.removed == p.scratch.created)

    claim = (0, json.dumps({"result": "sent to me@example.com: Digest 2026-09-15\nROUTINE_OK"}), "")
    p = ports(outcomes=[claim], sends=FakeSends([earlier]))
    res = A.run_routine(p, digest(), budget_s=1800)
    check("an answer claiming the send, with no record for this run, is a contract breach naming the send log",
          res.rc == 65 and res.kind == D.CONTRACT_BREACH and "mail-sent.jsonl" in res.summary, res.summary)
    check("it keeps its scratch directory for inspection",
          p.scratch.removed == [] and res.attempts and res.attempts[0].scratch == p.scratch.created[0], res.attempts)
    check("and never fails over", len(p.runner.calls) == 1)

    p = ports(outcomes=[claim])
    p.sends = None
    res = A.run_routine(p, digest(), budget_s=1800)
    check("with no send log wired, a delivery requirement can only fail", res.rc == 65, res)

    p = ports(outcomes=["ok_no_request_reply"])
    meetings = A.Routine("meeting-notes-to-vault-agent", "/h/Brain/90-Meta/routines/meeting-notes-to-vault.md", (), None,
                      contract=D.SuccessContract(None, ("ROUTINE_OK",), ("ROUTINE_FAILED:",)),
                      text="---\nid: k\n---\n\n<!-- notes -->\nCapture the outlines of the user's meetings.\n")
    res = A.run_routine(p, meetings, budget_s=1800)
    check("a reply asking what to do is a contract breach that says the routine was not run",
          res.rc == 65 and res.kind == D.CONTRACT_BREACH and "did not run the routine" in res.summary, res.summary)


def main():
    global A, D, FIXTURES
    try:
        from routine_auth_core import application as A
        from routine_auth_core import domain as D
        from routine_auth_core.fixtures import FIXTURES
    except Exception as exc:
        check("routine_auth_core.application imports", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_success, test_failover, test_malformed, test_stops, test_budget_and_args, test_contract,
                  test_permissions, test_framing_and_scratch, test_delivery):
            try:
                t()
            except Exception as exc:
                import traceback
                traceback.print_exc()
                check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
