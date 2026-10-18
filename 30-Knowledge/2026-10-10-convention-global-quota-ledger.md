---
id: 2026-10-10-convention-global-quota-ledger
title: Every service with a quota is accounted in one global ledger
type: convention
area: [harness, tooling]
projects: []
tags: [quota, credits, usage, ledger, quota-py, skills, routines, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-10
supersedes: []
---

## The rule

The use of every service that has a quota (image or video generation credits, a chat app's usage
window, a paid API's monthly calls, an agent CLI's allowance) is tracked in one place for the whole
vault, whatever skill or routine spends it, on whatever machine. `_bin/quota.py` is that place.

## Why

A quota is shared by everything that spends it, and each skill only sees its own spending. Two
skills drawing on the same image credits, or the same service used from two machines, run it out
without either of them knowing, and the job that hits the wall is usually halfway through (a video
with half its clips, a batch of images with the last ones refused). One ledger that every spender
writes to, and that every job reads before it starts, is what lets a job see the wall coming.

## How

```sh
python3 ~/Brain/_bin/quota.py status [service]       # before a job that spends a quota
python3 ~/Brain/_bin/quota.py spend <service> <amount> --what "..." --skill <skill>
python3 ~/Brain/_bin/quota.py reading <service> --remaining N
python3 ~/Brain/_bin/quota.py reading <service> --used-pct P --window 5h --resets "..."
python3 ~/Brain/_bin/quota.py services               # the catalogue
python3 ~/Brain/_bin/quota.py log [service] [--days 7]
```

- **Before a job**: `status <service>` shows the last reading, what was spent after it, the estimate
  now, the spend over the last hours, day, week and month, and the limits the catalogue knows. When
  the service shows its own figure, take a fresh `reading` first.
- **After each unit of work** (one clip, one image, one batch of API calls): one `spend` row. `--unit`
  when the spend is counted in a different unit from the quota, for example clips against a quota
  the service reports as a percentage.
- **Readings are the truth, spends fill the gaps.** A service's own page or API figure beats any sum
  of spends, so a `reading` resets the estimate and the spends after it are added on top.
- **Where it lives.** Rows go to `90-Meta/quota/<YYYY-MM>-<machine>.jsonl`, one file per machine and
  month, so vault syncs from several machines never conflict on the same file. The machine part is
  the vault's own machine identity, never a raw hostname.
- **The catalogue** `90-Meta/quota/services.json` names each service with its unit, the limits known
  for it, where to check its real figure, and which skills spend it. An unknown service is refused
  until it is added there, so a typo never starts a second, silent ledger.

## Example

An invented setup with two services in the catalogue: `illustrator` (images, 200 a month) and
`clip-maker` (credits, 1,000 a month, 10 per clip). A routine that makes a short video first runs
`quota.py status clip-maker`, sees 120 credits left against the 80 it needs, and goes ahead. After
each clip it logs `quota.py spend clip-maker 10 --what "intro clip" --skill short-video`. At the end
it reads the service's own counter and logs `quota.py reading clip-maker --remaining 40`.

## Wiring in skills

Every skill that spends one of the catalogued services carries a one line "Quota account" step that
points here: `status` before, `spend` after. A routine that runs on a schedule does the same, so
unattended spending lands in the same ledger as a person's.

## Links

- [[2026-09-12-reference-tool-and-service-catalogue]]
- [[2026-09-21-convention-scheduled-task-resources-checked-per-machine]]
- [[2026-10-11-decision-lock-groups-for-routines-sharing-a-scarce-resource]]
