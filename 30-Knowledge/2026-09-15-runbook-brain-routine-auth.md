---
id: 2026-09-15-runbook-brain-routine-auth
title: Runbook for routine authentication
type: howto
area: [harness]
projects: []
tags: [routines, auth, oauth, token-pool, keepass, failover, headless, success-contract, send-log, runbook]
status: active
confidence: medium
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative. Only the invalid-token failure shape was seen from a real CLI; the other failure patterns are best guesses until a real failure confirms them"
updated: 2026-09-22
supersedes: []
---

## What this covers

Agent routines (the `type: agent` rows of `90-Meta/scheduled-tasks.md`) run through a standalone CLI
agent with a dedicated long-lived token taken from a pool. They never run as whichever account an
agent app or a terminal happens to be logged into, so switching accounts there changes nothing for
them. Code: `_bin/routine_auth_core/`, wired by `tasks.py`.

Commands and file shapes below describe the mechanism; the scripts' `--help` and the tests are
authoritative.

## How a run authenticates

1. **The CLI.** `90-Meta/agent-command.txt` holds the command template, for Claude Code something like
   `~/.local/bin/claude -p {prompt} --output-format json`. Each routine appends its own `agent_args`
   from its frontmatter, a JSON list of strings. Arguments that would give an unattended run
   unrestricted permissions (bare `Bash`, `Bash(*)`, `--dangerously-skip-permissions`,
   `bypassPermissions`) are refused before any token is read.
2. **A health check** per runner process: the command resolves, it is a standalone install and not a
   copy bundled inside a desktop app (which uses the app's login), the template has no flag that skips
   token authentication, and `--version` answers quickly. A failure raises `cli:health` and nothing
   runs.
3. **The pool.** `90-Meta/routine-tokens.json` lists tokens in failover order, as `kp://` references
   only. It is local configuration and is not committed.
4. **Each attempt** reads the current token from KeePass without prompting (a short timeout, the value
   passed through a private temporary file, never argv or stdout), checks it is exactly one token of
   the expected shape, and runs the CLI in an environment built from scratch: basic session variables,
   `BRAIN_VAULT` and `BRAIN_STATE`, plus what the runner sets (run id, scratch directory, send log path,
   the token). Nothing else is inherited: no cloud credentials, no provider variables, never the
   parent's own token.
5. **Classify and decide.** A token-level failure fails over to the next token, a network failure
   retries the same token, anything else stops. At most three attempts; one time budget covers the
   whole run.
6. **Record.** Every attempt updates `<brain state>/routine-auth-state.json` per token label, and every
   failed attempt appends its redacted output to `<brain state>/logs/routine-auth.log` with its run id.

## Run id, prompt and scratch directory

- **A run id** per attempt, `<routine id>-<timestamp>-<random>`, exported as `BRAIN_ROUTINE_RUN_ID`,
  logged in the runner log and stamped on every email the run sends.
- **A scratch directory** per attempt under `<brain state>/routine-scratch/`, mode 0700, passed to the
  CLI as an allowed directory and exported as `BRAIN_ROUTINE_SCRATCH`. Deleted when the attempt
  succeeds, kept when it fails; old ones are cleaned after a week. Paths may contain spaces, so
  prompts quote them.
- **A framed prompt.** Frontmatter and HTML comments are stripped, and the body is wrapped in text
  stating this is an unattended run happening now, the run id and scratch directory, and the rules of
  a headless run: no subagents or background agents, one command at a time, temporary files only in
  the scratch directory, and `vw.py append` from a scratch file without adding a timestamp of its own.
  [[2026-09-15-convention-headless-agent-prompt-must-be-framed-as-an-order]]

## Setting up or renewing a token

1. With the standalone CLI logged into the account routines should use, run `claude setup-token` and
   copy the token it prints.
2. Store it so it arrives as exactly one word, without passing through argv:

   ```sh
   pbpaste | tr -d '[:space:]' | python3 ~/Brain/_bin/kp.py put apis/agent-routines-token-1 --stdin
   ```

   On Linux use `xclip -o` or `wl-paste` instead of `pbpaste`, then clear the clipboard. Create a new
   entry with `put` before using `set` on it: check `kp.py --help` for how your copy resolves a name
   that does not exist yet.
3. Add the entry to `90-Meta/routine-tokens.json` with today's `issued` date.
4. `guardian.py status` shows the token as healthy.

No alert, log, email or state file ever carries any part of a token. Tokens are named by label and
`kp://` reference, and a bad value is described only by its shape.

## The pool file

```json
{
  "tokens": [
    {"label": "routines-1", "account": "routines", "kp_ref": "kp://apis/agent-routines-token-1",
     "issued": "2026-01-15", "notes": "setup-token output for the routines account"},
    {"label": "routines-2", "account": "second-account", "kp_ref": "kp://apis/agent-routines-token-2",
     "issued": "2026-01-20"}
  ]
}
```

Order is failover order; labels are unique; unknown keys, or anything that looks like a token value,
invalidate the whole file. Tokens from different accounts are what keep routines running when one
account hits a limit.

## Failure classes

| kind | what it means | what the run does | what to do |
|---|---|---|---|
| `auth_invalid` | the token is refused, or on the CLI-login attempt the CLI is not logged in | marks it dead, fails over; a CLI-login attempt falls back to the pool and raises `routine-auth:cli-login` | renew it; for the CLI login, `claude auth login` on that machine |
| `token_malformed` | the stored value is not one token | marks it dead, fails over, the CLI never sees it | re-store it with the command in the alert |
| `usage_limit` | a usage or rate limit | rests the token until the reset time, fails over | wait, or add a token from another account |
| `credit_exhausted` | out of credit | rests the token for a day, fails over | top up, or add a token |
| `network` | the API could not be reached | retries the same token | check the network |
| `timeout` | the run used its whole budget | stops | read the task log |
| `cli_missing` | no runnable standalone CLI | stops, raises `cli:health` | reinstall the standalone CLI |
| `keepass_locked` | KeePass cannot be opened without a person | stops, token status untouched | unlock KeePass at a terminal; do not rotate the token |
| `keepass_unavailable` | entry or database missing, or KeePass not answering | stops | check the database path and entry name |
| `config` | pool file missing or invalid, or refused `agent_args` | stops before the CLI | fix the file, or narrow the allowlist |
| `contract_breach` | exit 0 but the success contract is not met | fails the run, keeps the scratch directory, token stays healthy | read the task log, the auth log and the scratch directory |
| `no_usable_token` | every token is resting | stops | wait, or add a token |
| `unknown` | matches nothing | stops, never fails over, logs the raw output | read the log, then calibrate |

`auth_invalid` is the only shape seen from a real CLI when this was written. When a run fails with an
unverified kind or `unknown`, read its redacted output, add the real example to
`_bin/routine_auth_core/fixtures.py` marked as verified, correct the pattern in the domain, and run the
domain tests on every supported interpreter.

## Success contracts

A routine declares in its frontmatter what an exit 0 must show to count as delivered, as a JSON object:

- `required_sends` and `sends_to`: that many records in the send log carry this attempt's run id, to
  that recipient. Checked on the log, never on the model's words.
  [[2026-09-15-convention-success-contracts-must-check-the-log-not-the-models-final-words]]
- `required`: markers that must appear anywhere in the answer.
- `forbidden`: markers that must not appear.

```yaml
success_contract: {"required_sends": 1, "sends_to": "you@example.com", "forbidden": ["EMAIL NOT SENT:"]}
```

A routine with no contract keeps the old rule: exit 0 is success.

**The send log.** Every message the mail command delivers is appended as one JSON line (timestamp,
recipient, subject, message id, run id when set, never the body) to the path the runner sets, or to
`<brain state>/logs/mail-sent.jsonl`. A send that cannot be logged still exits 0, because the message
went out; the delivery check then fails, which is the honest outcome.

## Allowlists

No routine runs an arbitrary shell command. Each routine's `agent_args` names narrow prefix patterns in
the agent's permission syntax, taken from what its prompt and its skill actually run, for example
`Bash(python3 ~/Brain/_bin/google.py send:*)` and `Bash(python3 ~/Brain/_bin/vw.py append:*)`. Prompts
tell the routine to run each command on its own, never chained with `cd`, `&&` or `;`, because a prefix
rule matches one command.

**To widen an allowlist:** add the narrowest pattern that covers the new command, tell the prompt to run
the command in exactly that form, run the routine-auth domain tests, check `guardian.py status`, and
force one run from a scratch registry to confirm nothing is denied.

## Headless limits

A routine run has no vendor connector. Each routine says what it does headless, and one that needs a
capability it lacks fails and alerts instead of silently doing nothing.

**The browser is the one exception, and it does not come from the pool.** Claude Code keeps Claude in
Chrome off for a `claude setup-token` token even with `--chrome`, so a routine whose `--allowedTools`
allows `mcp__claude-in-chrome` gets a first attempt **on the CLI's own claude.ai login, with
`--chrome`**: no pool token is read and no token variable is set, so the CLI uses its login under
`HOME`. The prompt tells the run that this machine's Chrome is where the user's logged-in sessions
live, to pick the local browser, and never to sign in or accept a consent screen. The attempt is
listed as `cli-login`.

Only when that attempt fails as `auth_invalid` (the CLI's `Not logged in` counts) does the run go on
to the pool, without `--chrome`, with a prompt saying there is no browser so it takes the procedure's
fallback, and it raises the `routine-auth:cli-login` warning: run `claude auth login` on that
machine. Any other failure of the CLI-login attempt is the run's result; no token is spent on it. The
pool's failover limit counts only pool attempts. [[2026-09-21-reference-where-claude-in-chrome-is-available]]
`BRAIN_HEADLESS=1` is exported so hook scripts can tell an unattended run apart.

## Smoke checks

Use a scratch registry and a scratch `BRAIN_STATE`.
[[2026-09-15-convention-smoke-checks-must-isolate-all-state-not-just-the-input-file]]

1. The standalone CLI answers `--version`.
2. After storing the token, `guardian.py status` shows it healthy.
3. A forced run of one routine from a scratch registry: one real run, the pool token, logged.
4. A scratch pool whose first entry points at a throwaway entry with a wrong value: `auth_invalid`,
   failover, that label marked dead. Never edit the real token for this.
5. A throwaway entry holding two words: `token_malformed` and no CLI run.
6. A routine that emails: the send log has a line whose run id matches the runner log, and no scratch
   directory is left for that run.
7. A scratch copy of that routine told to skip the email: `contract_breach`, an alert naming the send
   log, and the scratch directory kept.

## Links

- [[2026-09-15-runbook-brain-guardian]]
- [[2026-09-15-runbook-brain-events]]
- [[2026-09-15-reference-cli-total-cost-usd-is-an-estimate-not-a-bill]]
- [[2026-08-20-decision-credentials-in-keepass]]
