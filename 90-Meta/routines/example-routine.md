---
id: routine-example-digest
title: Routine prompt for example-digest
type: routine
area: [harness]
projects: []
tags: [routine, scheduled-task, agent-task, headless, example]
status: active
confidence: high
source: agent
provenance: shipped with the harness as the worked example of a type agent routine
updated: 2026-09-15
supersedes: []
routine_id: example-digest
schedule: daily 07:30, from 90-Meta/scheduled-tasks.md (disabled until you enable it)
needs_bridge: [email]
agent_args: ["--permission-mode", "acceptEdits", "--allowedTools", "Read,Grep,Glob,Write,Bash(python3 ~/Brain/_bin/query.py:*),Bash(python3 ~/Brain/_bin/google.py send:*)"]
success_contract: {"required_sends": 1, "sends_to": "me@example.com", "forbidden": ["EMAIL NOT SENT:"]}
---

<!-- What it does: an example routine. Once a day it emails a short digest of the vault notes that changed.
     Runs as the `example-digest-agent` row of 90-Meta/scheduled-tasks.md, disabled until you enable it.
     Before enabling it: connect a Google account with google.py (the first run offers it), put your own
     address in `sends_to` and in the send command below, and add a routine token to the pool.
     `needs_bridge` lists what the run needs beyond a shell: an agent without those tools cannot do it.
     `agent_args` is what this routine may do when tasks.py runs it through the CLI agent named in
     90-Meta/agent-command.txt: a JSON list of strings, with a narrow allowlist and never an unrestricted Bash.
     `success_contract` is checked by the runner: one email to the address below, recorded in Brain's send log
     under this run's id, whatever the answer ends on.
     Runbook: 30-Knowledge/2026-09-15-runbook-brain-routine-auth.md -->

Build a short digest of the vault notes that changed in the last day and email it.

1. List the recently updated notes with `python3 ~/Brain/_bin/query.py --recent 20`.
2. Read the ones updated in the last day and write the digest to a file in this run's scratch directory: for
   each note, its title, its path and one sentence on what changed. Plain text, no headlines.
3. Send it with `python3 ~/Brain/_bin/google.py send --account personal --to me@example.com --subject "Vault digest" --body-file <the digest file>`.
4. If the send fails, answer with one line that starts with `EMAIL NOT SENT:` followed by the reason.

Do not invoke the `save` skill and do not spawn subagents: this run only reads the vault and sends one email.
