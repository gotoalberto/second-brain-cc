---
id: 2026-09-07-convention-backup-vercel-project-before-deleting
title: Before deleting a hosting project, dump it to one KeePass entry with a restore payload
type: convention
area: [deploy, security]
projects: []
tags: [vercel, backup, keepass, kdbx, deletion, restore, convention]
status: active
confidence: high
source: user
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-04
supersedes: []
---

## The rule

Deleting a hosting project (a Vercel project, or the equivalent elsewhere) is never just deleting it. The
user set this once as a standing rule, so it runs every time without asking whether a backup is wanted:

1. Dump the project's **whole configuration and every environment variable with its value**.
2. Store the dump as **one KeePass entry** in the agent group (a `backups/` category, say
   `kp://backups/hosting-<name>-<date>`), the JSON being the password field
   ([[2026-08-20-decision-credentials-in-keepass]], [[2026-08-20-convention-claude-kdbx-group-layout]]).
3. Write the restore steps where they will be found (the section below, or a project note).
4. **Verify the backup reads back and parses** before deleting anything.
5. **Confirm the exact list of projects with the user** before the destructive call.

The backup is worthless unless step 4 passes: a first attempt once stored two bytes.

## What "whole configuration" means

Not only the variables: framework and build, install and output settings, root directory, runtime version,
the git link (repository, production branch), custom domains with their redirect and branch settings,
**cron definitions** (they die with the project and are easy to forget), and the **last production
deployment's commit**, which is what makes a restore reproducible instead of "deploy whatever is at HEAD".

## Traps

- **Store the payload as single-line JSON** (`json.dumps(d, separators=(",", ":"))`). A pretty-printed JSON
  can come back as `{` from a reader that parses the CLI's output line by line. Round-trip it through
  `kp.py` and compare with the original.
- **A store command that consumes its input file** leaves no local evidence to compare with. Store a copy.
- **Variables marked sensitive never return a value** from any endpoint; they come back empty,
  indistinguishable from a variable that really is empty. Count the empties and refuse to proceed if any is
  unreadable: those must be recovered from a local `.env.local` or regenerated.
- **A list endpoint may not decrypt values** even when asked to; read each variable from its
  single-variable endpoint.
- A project deployed from a local directory with no git link cannot be fully restored from the backup: its
  source is not in it. Say so before deleting.
- Check account-level resources that do not disappear with the project (storage stores, edge configs,
  integrations, domains). Removing an externally registered domain from the hosting account only detaches
  it; the registration is untouched.

## Restoring

1. Recreate the project through the API with its name, framework, build settings and git repository. It
   gets a new id; the old ids in the payload are for reference.
2. Re-import the variables in one call, each with its original targets, as encrypted (not sensitive)
   variables, so a future audit can read them back.
3. Re-attach the domains, point DNS at the host again where needed, and expect propagation delay.
4. Deploy the recorded commit, not HEAD.
5. Crons come back with the deployment that declares them (in `vercel.json`); verify they are enabled and
   firing.
6. Verify in production, not in the dashboard.

Deployment history, build logs and platform analytics are gone for good with the project; the backup
cannot bring them back. Pipe the payload into the restore script (`kp.py get <entry> --pipe <script>`)
instead of printing it: it is every production secret of the project in one string.

## Links

- [[2026-08-20-convention-claude-kdbx-group-layout]]
- [[2026-09-22-decision-kp-rm-refuses-without-yes-and-reports-refs]]
