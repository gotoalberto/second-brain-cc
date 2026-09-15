"""run_routine: one routine run, with the token pool, classification and bounded failover.

Takes a `Ports` bundle and nothing else, so tasks.py and the tests run the same code. The
rules (what a failure is, which token is next, what the environment holds, what the prompt
says) are domain.py; this only sequences them:

  1. the CLI health check (once per process: the adapter caches it)
  2. the pool config
  3. old scratch directories pruned
  4. per attempt: read the token from KeePass, check its shape, give the attempt a run id and
     a private scratch directory, frame the prompt, run the CLI with an environment built from
     scratch, classify the outcome, check the success contract (the send log included), record
     it in the pool state, delete the scratch directory if the attempt succeeded
  5. fail over, retry or stop, within at most MAX_ATTEMPTS attempts and the time budget

The alerts it raises are about the machinery (`cli:health`, `routine-auth:keepass`,
`routine-auth:config`, `routine-args:<id>`, `routine-permissions:<id>`). The routine's own failure alert stays
tasks.py's (`routine:<id>`), carrying `RunResult.summary`. Token health lives in the pool
state, which the guardian reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import domain as D
from .ports import TokenUnavailable

MAX_ATTEMPTS = 3
MIN_ATTEMPT_S = 60           # no attempt starts with less time than this left in the budget

ALERT_CLI = "cli:health"
ALERT_KEEPASS = "routine-auth:keepass"
ALERT_CONFIG = "routine-auth:config"


@dataclass
class Ports:
    pool: object          # ports.PoolSource
    tokens: object        # ports.TokenSource
    state: object         # ports.StateStore
    clock: object         # ports.Clock
    cli: object           # ports.CliHealth
    runner: object        # ports.RunOnce
    raw_log: object       # ports.RawLog
    alerts: object        # ports.AlertSink
    base_env: dict = field(default_factory=dict)
    kp_timeout: int = 20
    scratch: object = None    # ports.ScratchDirs; None: attempts run with no scratch directory
    run_ids: object = None    # ports.RunIds; None: a run id from the routine, the time and the attempt number
    sends: object = None      # ports.SendLog; None: a contract requiring sends can only fail
    run_env: dict = field(default_factory=dict)   # exported to every attempt (the send log path)


@dataclass(frozen=True)
class Routine:
    id: str
    prompt_path: str
    agent_args: tuple = ()
    agent_args_problem: object = None
    contract: object = None           # domain.SuccessContract, or None: exit 0 is success
    contract_problem: object = None   # the contract did not parse: an exit 0 is still a failure
    text: str = ""                    # the routine file as read; the prompt is framed from it


@dataclass(frozen=True)
class Attempt:
    label: str
    kind: str
    detail: str = ""
    rc: object = None
    run_id: object = None
    scratch: object = None            # the scratch directory kept because this attempt failed


@dataclass
class RunResult:
    rc: int
    stdout: str = ""
    stderr: str = ""
    kind: str = D.OK
    label: object = None
    summary: str = ""                 # one line for the routine alert when rc != 0; never a token
    attempts: list = field(default_factory=list)
    run_id: object = None             # the last attempt's


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception:
        return None


def _new_run_id(ports, routine_id, now, number):
    rid = _safe(ports.run_ids.new, routine_id, now) if ports.run_ids is not None else None
    return rid or D.run_id(routine_id, now, str(number))


def run_routine(ports, routine: Routine, budget_s: int) -> RunResult:
    alerts = ports.alerts
    permissions_key = "routine-permissions:%s" % routine.id
    problem = D.permission_problem(routine.agent_args)
    if problem:
        summary = "routine %s agent_args refused before running: %s" % (routine.id, problem)
        _safe(alerts.raise_alert, permissions_key, summary)
        return RunResult(D.EXIT_CODES[D.CONFIG], stderr=problem, kind=D.CONFIG, summary=summary)
    _safe(alerts.clear_alert, permissions_key)
    args_key = "routine-args:%s" % routine.id
    if routine.agent_args_problem:
        _safe(alerts.raise_alert, args_key, "routine %s: %s" % (routine.id, routine.agent_args_problem), "warn")
    else:
        _safe(alerts.clear_alert, args_key)

    cli = ports.cli.check()
    if not cli.ok:
        summary = D.failure_summary(D.CLI_MISSING, cli.detail, None)
        _safe(alerts.raise_alert, ALERT_CLI, summary)
        return RunResult(D.EXIT_CODES[D.CLI_MISSING], stderr=cli.detail, kind=D.CLI_MISSING, summary=summary)
    _safe(alerts.clear_alert, ALERT_CLI)

    try:
        entries = ports.pool.entries()
    except D.PoolConfigError as exc:
        summary = D.failure_summary(D.CONFIG, str(exc), None)
        _safe(alerts.raise_alert, ALERT_CONFIG, summary)
        return RunResult(D.EXIT_CODES[D.CONFIG], stderr=str(exc), kind=D.CONFIG, summary=summary)
    _safe(alerts.clear_alert, ALERT_CONFIG)

    by_label = {e.label: e for e in entries}
    labels = [e.label for e in entries]
    start = ports.clock.monotonic()
    state = _safe(ports.state.load) or {}
    order = D.attempt_order(labels, state, ports.clock.now())
    if not order:
        untils = sorted(state[l]["until"] for l in labels if (state.get(l) or {}).get("until"))
        summary = D.failure_summary(D.NO_TOKEN, "", None, until=untils[0] if untils else None)
        return RunResult(D.EXIT_CODES[D.NO_TOKEN], kind=D.NO_TOKEN, summary=summary)
    if ports.scratch is not None:
        _safe(ports.scratch.prune, ports.clock.now())
    body = D.routine_body(routine.text)

    cap = min(len(entries), MAX_ATTEMPTS)
    label, tried, attempts, used = order[0], [], [], []
    rc, out, err, cls, entry, run_id = 0, "", "", None, None, None
    while True:
        remaining = budget_s - (ports.clock.monotonic() - start)
        if attempts and remaining < MIN_ATTEMPT_S:
            break
        entry = by_label[label]
        now = ports.clock.now()
        token, run_id, scratch = None, None, None
        out, err = "", ""
        try:
            token = ports.tokens.read(entry.kp_ref, ports.kp_timeout)
        except TokenUnavailable as exc:
            cls = D.Classification(exc.kind, str(exc))
            rc = D.EXIT_CODES.get(exc.kind, 75)
            _safe(alerts.raise_alert, ALERT_KEEPASS, D.failure_summary(exc.kind, str(exc), entry))
        else:
            _safe(alerts.clear_alert, ALERT_KEEPASS)
            used.append(token)
            well_formed, shape = D.token_shape(token)
            if not well_formed:
                cls = D.Classification(D.TOKEN_MALFORMED, shape)
                rc = D.EXIT_CODES[D.TOKEN_MALFORMED]
            else:
                run_id = _new_run_id(ports, routine.id, now, len(attempts) + 1)
                scratch = _safe(ports.scratch.create, run_id) if ports.scratch is not None else None
                env = D.routine_env(ports.base_env, token, run_id=run_id, scratch=scratch, extra=ports.run_env)
                args = list(routine.agent_args) + (["--add-dir", scratch] if scratch else [])
                prompt = D.frame_prompt(routine.id, body, run_id, scratch)
                rc, out, err = ports.runner.run(prompt, args, env, int(max(1, remaining)))
                cls = D.classify(rc, out, err)
        token_cls = cls
        if cls.kind == D.OK and (routine.contract is not None or routine.contract_problem):
            if routine.contract_problem:
                unmet = [routine.contract_problem]
            else:
                sends = []
                if routine.contract.required_sends:
                    records = _safe(ports.sends.records) if ports.sends is not None else None
                    sends = D.sends_for_run(records or [], run_id)
                unmet = D.check_contract(routine.contract, out, sends=sends)
            if unmet:
                cls = D.Classification(D.CONTRACT_BREACH, "; ".join(unmet))
                rc = D.EXIT_CODES[D.CONTRACT_BREACH]
        tried.append(label)
        state = D.record(state, label, token_cls, now)
        _safe(ports.state.save, state)
        kept = None
        if scratch:
            if cls.kind == D.OK:
                _safe(ports.scratch.remove, scratch)
            else:
                kept = scratch
        if cls.kind != D.OK:
            _safe(ports.raw_log.record, routine.id, label, cls, rc, out, err, [t for t in used if t], run_id)
        attempts.append(Attempt(label, cls.kind, cls.detail, rc, run_id, kept))
        token = None
        if cls.kind == D.OK or len(attempts) >= cap:
            break
        nxt = D.next_token(labels, state, label, cls.kind, now, tried)
        if nxt is None:
            break
        label = nxt

    result = RunResult(rc, D.redact(out, secrets=used, limit=0), D.redact(err, secrets=used, limit=0),
                       cls.kind, entry.label if entry else None, "", attempts, run_id)
    used[:] = []
    if cls.kind != D.OK:
        until = (state.get(result.label) or {}).get("until")
        summary = D.failure_summary(cls.kind, cls.detail, entry, until=until)
        if len(attempts) > 1:
            summary += " (tried: %s)" % ", ".join("%s %s" % (a.label, a.kind) for a in attempts)
        result.summary = summary
    return result
