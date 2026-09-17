"""The first run's flow: one question at a time, nothing installed without a yes, resumable.

Each step asks whether to connect one piece, except the files step, which asks only where: Brain keeps
files in a local directory and does not work without one, so that step has no yes or no and is asked
until it is done. A yes leads to the few questions that piece needs and
to the change itself, through a port; a no is recorded so it is never asked again (until
`first_run.py reset <step>`). The state is saved after every step, so an interrupted run resumes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import domain as D


@dataclass
class Ports:
    prompt: object
    state: object
    kdbx: object
    google: object
    files: object
    multi_machine: object
    mail: object
    mcp: object
    scheduler: object
    routines: object
    clock: object
    home: str
    platform: str


@dataclass
class RunResult:
    complete: bool = False
    done: list = field(default_factory=list)
    declined: list = field(default_factory=list)
    failed: list = field(default_factory=list)          # [(step, reason)]


class _Ctx:
    def __init__(self, ports, state, dry_run):
        self.p, self.state, self.dry_run = ports, state, dry_run
        self.result = RunResult()

    def done(self, step, **details):
        self.state = D.record(self.state, step, "done", details, self.p.clock.now())
        self.result.done.append(step)

    def declined(self, step, **details):
        self.state = D.record(self.state, step, "declined", details, self.p.clock.now())
        self.result.declined.append(step)

    def failed(self, step, reason):
        self.p.prompt.say("  %s did not complete: %s. The next run asks it again." % (step, reason))
        self.result.failed.append((step, reason))

    def ask_until(self, question, valid, default="", error="that does not look right"):
        while True:
            value = self.p.prompt.ask(question, default).strip()
            if valid(value):
                return value
            self.p.prompt.say("  %s, try again." % error)


# ---------------------------------------------------------------- steps


def _kdbx(c):
    p = c.p
    if not p.prompt.yes_no("Connect a KeePass database for credentials (read with keepassxc-cli)?", False):
        return c.declined("kdbx")
    path = c.ask_until("  Database path", lambda v: bool(v), D.default_kdbx_path(p.platform, p.home))
    create = False
    if not p.kdbx.exists(path):
        if not p.prompt.yes_no("  %s does not exist. Create it now? keepassxc-cli asks for its master password" % path,
                               True):
            return c.declined("kdbx", reason="no database to use")
        create = True
    good, detail = p.kdbx.init(path, create)
    if not good:
        return c.failed("kdbx", detail)
    if p.prompt.yes_no("  Arm the master password cache now, so scheduled jobs can read credentials (kp.py unlock)?",
                       True):
        armed, why = p.kdbx.unlock()
        if not armed:
            p.prompt.say("  The cache was not armed (%s). Run python3 _bin/kp.py unlock later." % why)
    c.done("kdbx", db=path)


def _google(c):
    p = c.p
    p.prompt.say("Google accounts need an OAuth client: in a Google Cloud project, enable the Gmail, Calendar and "
                 "Drive APIs and create an OAuth client of type Desktop app. Each account can use its own.")
    if not p.prompt.yes_no("Connect Google accounts (Gmail, Calendar and Drive, through google.py)?", False):
        return c.declined("google")
    count = int(c.ask_until("  How many accounts?", lambda v: v.isdigit() and 0 < int(v) <= 9, "1",
                            "a number from 1 to 9"))
    names = []
    for i in range(count):
        name = c.ask_until("  Account %d name (for example personal or work)" % (i + 1),
                           lambda v: _valid_account(v) and v not in names, "",
                           "lowercase letters, digits and dashes, not used yet")
        hint = p.prompt.ask("  Its email address (optional, used as the login hint and sender)", "").strip()
        client_id = c.ask_until("  OAuth client id", lambda v: bool(v), "", "the client id is required")
        client_secret = p.prompt.secret("  OAuth client secret (not shown)").strip()
        good, detail = p.google.add(name, client_id, client_secret, hint)
        if not good:
            return c.failed("google", detail)
        names.append(name)
        if p.prompt.yes_no("  Authorise %s in the browser now?" % name, True):
            good, detail = p.google.authorize(name)
            if not good:
                p.prompt.say("  Not authorised yet (%s): python3 _bin/google.py auth --account %s" % (detail, name))
    c.done("google", accounts=names)


def _valid_account(name):
    import re

    return bool(re.match(r"^[a-z0-9][a-z0-9-]{0,31}$", name or ""))


def _files(c):
    p = c.p
    p.prompt.say("Brain keeps files (deliverables, intermediate steps, source material) in a local directory "
                 "outside the vault, and notes point at them. This step is required: choose the directory.")
    while True:
        path = c.ask_until("Directory for files", lambda v: bool(v), p.files.propose_default(), "a directory is required")
        if c.dry_run:
            p.prompt.say("  Dry run: %s would be created if missing and recorded." % path)
            return
        good, detail = p.files.check(path)
        if good:
            break
        p.prompt.say("  %s cannot be used (%s). Choose another directory." % (path, detail))
    saved, why = p.files.persist(detail)
    if not saved:
        return c.failed("files", why)
    c.done("files", dir=detail)


def _multi_machine(c):
    p = c.p
    if not p.prompt.yes_no("Do you want this machine to coordinate presence and file claims "
                           "with other machines over a shared folder you already sync — "
                           "Dropbox, iCloud, a NAS, a USB drive?", False):
        return c.declined("multi_machine")
    while True:
        path = c.ask_until("  Shared folder path", lambda v: bool(v), "", "a directory is required")
        if c.dry_run:
            p.prompt.say("  Dry run: %s would be created if missing and recorded." % path)
            return
        good, detail = p.multi_machine.check(path)
        if good:
            break
        p.prompt.say("  %s cannot be used (%s). Choose another directory." % (path, detail))
    saved, why = p.multi_machine.persist(detail)
    if not saved:
        return c.failed("multi_machine", why)
    c.done("multi_machine", dir=detail)


def _alert_email(c):
    p = c.p
    if not p.prompt.yes_no("Send the guardian's alerts by email?", False):
        return c.declined("alert_email")
    google = c.state["steps"].get("google", {})
    accounts = google.get("accounts") if google.get("status") == "done" else None
    accounts = accounts or p.google.accounts()
    if accounts:
        account = accounts[0]
        if len(accounts) > 1:
            account = c.ask_until("  Which Google account sends them (%s)?" % ", ".join(accounts),
                                  lambda v: v in accounts, accounts[0])
        to = c.ask_until("  Send alerts to which address?", D.valid_email, "", "one email address")
        sender = c.ask_until("  From address (the account's own address)", D.valid_email, to, "one email address")
        config = {"enabled": True, "adapter": "gmail-api", "account": account, "from": sender, "to": to}
    else:
        host = c.ask_until("  SMTP host", lambda v: bool(v), "", "the host is required")
        port = int(c.ask_until("  SMTP port", lambda v: v.isdigit(), "587", "a port number"))
        user = p.prompt.ask("  SMTP user", "").strip()
        entry = c.ask_until("  KeePass entry with the SMTP password", lambda v: bool(v), "mail/smtp")
        to = c.ask_until("  Send alerts to which address?", D.valid_email, "", "one email address")
        sender = c.ask_until("  From address", D.valid_email, to, "one email address")
        config = {"enabled": True, "adapter": "smtp", "from": sender, "to": to,
                  "smtp": {"host": host, "port": port, "user": user, "security": "ssl" if port == 465 else "starttls",
                           "kp_ref": "kp://%s#Password" % entry}}
    path = p.mail.save(config)
    c.done("alert_email", adapter=config["adapter"], config=path)


def _mcp(c):
    p = c.p
    if not p.prompt.yes_no("Register the Brain MCP server with your agents?", False):
        return c.declined("mcp")
    for name, text in sorted(p.mcp.snippets().items()):
        p.prompt.say("  %s:\n%s" % (name, "\n".join("    " + line for line in text.splitlines())))
    registered = False
    if p.mcp.claude_available() and p.prompt.yes_no("  Register it with Claude Code now (claude mcp add)?", False):
        registered, detail = p.mcp.register_claude()
        if not registered:
            p.prompt.say("  Claude Code registration failed: %s" % detail)
    exported = False
    line = D.profile_line(p.mcp.vault())
    if p.prompt.yes_no("  Add `%s` to %s (a backup is kept)?" % (line, p.mcp.profile_path()), False):
        exported, detail = p.mcp.append_profile(line)
        if not exported:
            p.prompt.say("  The profile was not changed: %s" % detail)
    c.done("mcp", claude_code=bool(registered), profile=bool(exported))


def _scheduler(c):
    p = c.p
    kind = p.scheduler.detect()
    if kind not in D.SCHEDULERS:
        p.prompt.say("No supported scheduler here (launchd, systemd user units or cron): no job can be installed.")
        c.state["scheduler"] = D.scheduler_state("none", [])
        return c.declined("scheduler", reason="no supported scheduler")
    if not p.prompt.yes_no("Install scheduled jobs with %s? Each one is asked, and nothing is installed until you "
                           "confirm" % kind, False):
        c.state["scheduler"] = D.scheduler_state(kind, [])
        return c.declined("scheduler", kind=kind)
    accepted = [job for job, what in D.JOBS if p.prompt.yes_no("  %s: %s?" % (job, what), job in ("guardian", "sync"))]
    if not accepted:
        c.state["scheduler"] = D.scheduler_state(kind, [])
        return c.declined("scheduler", kind=kind)
    p.prompt.say("  This is what would be installed:\n%s" % p.scheduler.preview(kind, accepted))
    if c.dry_run:
        p.prompt.say("  Dry run: nothing installed.")
        return
    if not p.prompt.yes_no("  Install these now?", False):
        c.state["scheduler"] = D.scheduler_state(kind, [])
        return c.declined("scheduler", kind=kind)
    results = {label: (good, detail) for label, good, detail in p.scheduler.install(kind, accepted)}
    installed = [job for job in accepted if results.get(D.job_label(kind, job), (False, ""))[0]]
    c.state["scheduler"] = D.scheduler_state(kind, installed)
    broken = ["%s (%s)" % (job, results.get(D.job_label(kind, job), (False, "not attempted"))[1])
              for job in accepted if job not in installed]
    if broken:
        return c.failed("scheduler", "not installed: " + "; ".join(broken))
    c.done("scheduler", kind=kind, jobs=installed)


def _routines(c):
    p = c.p
    if not p.prompt.yes_no("Run routines (90-Meta/routines) through a CLI agent, with a token pool in KeePass?", False):
        return c.declined("routines")
    good, detail = p.routines.agent_available()
    if not good:
        return c.failed("routines", "no agent command: %s (see 90-Meta/agent-command.txt)" % detail)
    count = int(c.ask_until("  How many tokens in the pool?", lambda v: v.isdigit() and 0 < int(v) <= 9, "1",
                            "a number from 1 to 9"))
    issued = p.clock.now().date().isoformat()
    for n in range(1, count + 1):
        entry = D.token_ref(n)[len("kp://"):]
        p.prompt.say("  Token %d: create it with your agent CLI (for Claude Code: claude setup-token), then store it:\n"
                     "    python3 _bin/kp.py put %s --stdin" % (n, entry))
        good, detail = p.routines.add_token(D.token_label(n), D.token_ref(n), issued, "routines")
        if not good:
            return c.failed("routines", detail)
    p.prompt.say("  Enable a routine's row in 90-Meta/scheduled-tasks.md when you want it to run.")
    c.done("routines", tokens=count)


STEP_FUNCS = {"kdbx": _kdbx, "google": _google, "files": _files, "multi_machine": _multi_machine,
              "alert_email": _alert_email, "mcp": _mcp, "scheduler": _scheduler, "routines": _routines}


# ---------------------------------------------------------------- use cases


def run(ports, dry_run=False) -> RunResult:
    if not ports.prompt.interactive():
        ports.prompt.say("The first run asks questions and needs a terminal. Run it later with: "
                         "bash integrations/first-run/setup.sh")
        return RunResult(complete=False)
    c = _Ctx(ports, ports.state.load(), dry_run)
    for step in D.STEPS:
        if step in c.state["steps"]:
            continue
        parent = D.DEPENDS.get(step)
        if parent:
            parent_status = c.state["steps"].get(parent, {}).get("status")
            if parent_status == "declined":
                c.declined(step, reason="needs the KeePass database, which was declined")
                continue
            if parent_status != "done":
                continue
        STEP_FUNCS[step](c)
        if not dry_run:
            ports.state.save(c.state)
    if not dry_run:
        ports.state.save(c.state)
    c.result.complete = D.is_complete(c.state) and not dry_run
    return c.result


def _files_unattended(ports):
    """(ok, details or why not): the default files directory, created and recorded with no question."""
    good, detail = ports.files.check(ports.files.propose_default())
    if not good:
        return False, detail
    saved, why = ports.files.persist(detail)
    return (True, {"dir": detail}) if saved else (False, why)


UNATTENDED = {"files": _files_unattended}


def skip_all(ports):
    """`first_run.py skip-all`: answer every unanswered step without asking. A required step gets its default
    (the files directory is created and recorded); every other step is declined. Returns (state, failed)."""
    state, failed = ports.state.load(), []
    for step in D.STEPS:
        if step in state["steps"]:
            continue
        if step in D.REQUIRED:
            good, result = UNATTENDED[step](ports)
            if good:
                result["reason"] = "default chosen by first_run.py skip-all"
                state = D.record(state, step, "done", result, ports.clock.now())
            else:
                failed.append((step, result))
            continue
        state = D.record(state, step, "declined", {"reason": "skipped with first_run.py skip-all"}, ports.clock.now())
    ports.state.save(state)
    return state, failed


def run_status(ports):
    """(complete, lines): every step and its answer, for `first_run.py status`."""
    state = ports.state.load()
    lines = []
    for step in D.STEPS:
        entry = state["steps"].get(step)
        lines.append("%-12s %s" % (step, entry["status"] if entry else "not asked yet"))
    sched = state.get("scheduler") or {}
    lines.append("%-12s %s %s" % ("jobs", sched.get("kind", "none"), ",".join(sched.get("jobs") or []) or "-"))
    return D.is_complete(state), lines


def reset(ports, step):
    ports.state.save(D.forget(ports.state.load(), step))
