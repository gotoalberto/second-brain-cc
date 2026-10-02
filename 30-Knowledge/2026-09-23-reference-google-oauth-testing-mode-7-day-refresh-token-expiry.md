---
id: 2026-09-23-reference-google-oauth-testing-mode-7-day-refresh-token-expiry
title: Google OAuth consent screens in Testing publishing status expire refresh tokens after 7 days
type: reference
area: [harness]
projects: []
tags: [google, google-cloud, oauth, testing-mode, refresh-token, expiry, publishing-status, gmail, credential]
status: active
confidence: high
source: agent
provenance: "generalized from a working vault where a personal Gmail token died twice on the same 7 day cadence; names and dates are illustrative"
updated: 2026-09-28
supersedes: []
---

## Context

Google Cloud OAuth consent screens have a publishing status: **Testing** or **Production**.
While a consent screen is in Testing, every refresh token it issues **expires 7 days after the
user consents**, however much it is used. This is not an incident, a revoke or a password
change. It is the platform's designed behaviour for unpublished apps, and it recurs on a fixed
clock until the app is published.

## Content

**How it showed up.** A personal Gmail account connected through its own Cloud project lost
its refresh token twice, exactly 7 days after each consent. Every routine that read or sent
mail through it stopped the same day with no warning. The symptom the user saw was only that a
morning email never arrived.

**The controlled comparison that proves it.** A second OAuth app, in another Cloud project,
was consented on the same day, on the same machine, through the same loopback flow. On day 8 it
was still alive; the first had died on day 7. Same machinery, same day, same machine: the only
variable was the Cloud project and its publishing status. That rules out a password change, a
manual revoke or an account security action.

**Why publishing is not a quick fix.** The console's publish button stays disabled until the
app has a public home page URL, a privacy policy URL and an authorized domain. A domain that
only handles mail and serves no web page is not enough, so publishing means standing those
pages up first. That is a real decision to make, well beyond a console setting.

**The alert channel shares the fate.** When the guardian or a routine reports problems by
mail through the same account, the report that the mail died dies with it. The warning has to
go out while the token still works, and ideally through an account that does not share its fate
([[2026-09-15-runbook-brain-guardian]]).

**What the harness does about it.** `google.py auth` stamps the consent instant in the account
registry (`authorized_at` in `<brain state>/google-accounts.json`). `_bin/google_token_watch.py`
counts from that stamp, probes the token for real, and mails a warning three days before the
deadline, at most once a day per account:

```bash
python3 ~/Brain/_bin/google_token_watch.py --account personal --to me@example.com --via work
```

Run it daily from the scheduler. Name only the accounts whose app is in Testing status (a
published app's tokens do not expire on this clock), and give `--via` an account that does not
share the watched one's fate whenever there is one.

**Rule for any new Google OAuth client.** Check the consent screen's publishing status at
once. If it is Testing, either publish it up front (when the app has what publishing needs) or
schedule the token watch from day one, rather than finding the expiry through a missing email.

**Renewing** is `google.py auth --account <name>` on a machine with a browser. When the machine
runs the Remote Control server, finish the consent before restarting that server: the loopback
listener waiting for Google's redirect lives inside the session's process tree
([[2026-09-23-runbook-claude-code-update-on-a-linux-server]]).

## Publishing to production

Publishing the app removes the 7 day expiry. What it took in practice:

- A home page URL and a privacy policy URL on a domain the project lists as authorized. Two static
  pages on any static host the user controls are enough; nothing has to run behind them.
- An app that has not gone through Google's verification still publishes. Its consent screen then
  shows Google's "unverified app" warning, which the owner clicks through once per consent.

Record the change for the account: `google.py auth --account <name> --publishing production` stamps
the account as published in the registry (an account with no stamp reads as testing). From then on
`google_token_watch.py` sets no expiry for it and only keeps the liveness probe, and its output says
the token does not expire. Any app left in Testing keeps the 7 day clock described above.

## Links

- [[2026-09-15-runbook-brain-guardian]]
- [[2026-09-23-runbook-claude-code-update-on-a-linux-server]]
