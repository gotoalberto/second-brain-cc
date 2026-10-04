---
id: 2026-09-01-convention-web-development-skill-stack
title: "Web development pipeline: fixed skill stack, animation, three critique rounds and browser checks"
type: convention
area: [harness, frontend]
projects: []
tags: [web, frontend, skills, animation, impeccable, critique, browser, break-ui, mobile-native, convention]
status: active
confidence: high
source: user
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-04
supersedes: []
---

## The rule

**Whenever a web is developed, the same skills are used. All of them, every time.** It is not a menu
to pick from and it does not depend on the size of the job. The `dev` skill's design gates enforce it;
this note records why the pieces are there.

**Every web UI change goes through the pipeline**, a small layout change included: design interview
first, tests first, the craft floor and detector, motion built with the animation skills, the
worst-case data and phone passes, three critique rounds with at least one blind critic, and a look in
the browser at every width. A change once shipped without it was redone through it.

## The skill stack

| Skill | Role |
|---|---|
| `impeccable` | The spine: hierarchy, typography, spacing, the quality floor and the `critique` command. |
| `frontend-design` | Aesthetic direction, so the result does not read as a templated default. |
| `design-taste-frontend` | An anti-template pass for landing pages, portfolios and redesigns. |
| `emil-design-eng` | Component polish and the invisible details; entry point to the animation skills. |
| `break-ui` | Worst-case data for every rendered value, behind a dev-only "Demo data / Worst case" toggle. |
| `mobile-native` | The fixes that make a web app feel installed on a phone. |

These third-party skills ship **bundled in the repository**, each under its upstream licence (MIT or
Apache 2.0) with the licence file kept next to it. The repository's own README lists where each one
comes from.

### Never hand-edit the bundled third-party skills

They are upstream content copied verbatim. A local edit is lost on the next refresh from upstream,
silently, with no merge and no warning. If a technique belongs conceptually inside one of them, put it
in the `dev` skill (the repository's own code, safe to edit) or in a convention note the `dev` skill
references. To refresh them, copy the new upstream version over the old one and keep the licence.

## Animation on every web

**Every web ships with motion**: entrances, exits, state changes, hovers and transitions. A static
page is not a finished page, and motion is never added "if there is time left". It is built with the
animation skills, never by guessing values:

- `animate` builds each one in decision order: should it animate at all, why, which properties, which
  curve, how long, how it is interrupted, how it exits;
- `find-animation-opportunities` finds what is not moving and should, and rules out what should stay
  still;
- `review-animations` reviews the motion before the critique rounds;
- `animate-expo` replaces `animate` on React Native and Expo;
- `apple-design` for gestures, springs, sheets and interruptible transitions.

Left alone, an agent picks `ease-in` for an entrance when it wants `ease-out`, and a hard border where
a soft shadow belongs: small things that add up to an interface that feels cheap. The user's own motion
preferences are in [[2026-10-03-convention-motion-in-web-interfaces]].

There is no skill called `animate-pro` in that family; a request for it means `animate`.

## Worst-case data and the phone, before the critique rounds

`break-ui` and `mobile-native` run on every web, after the motion is built and **before** the first
critique round, so the critique judges the interface with realistic data on a phone. Both reuse the
local fake data mode ([[2026-10-03-convention-web-runs-locally-with-fake-data-every-page-reviewed]]).

## Three rounds of critique, with their corrections

```
/impeccable critique <target>
```

Three complete rounds minimum, each one critique, then fixes, then critique again, each starting from
the corrected result of the previous one. Reading a critique and deciding it looks fine is not a round.
One round is about the images alone. At least one round is a blind critic: a fresh agent that sees only
screenshots ([[2026-09-18-convention-anti-ai-slop-design-techniques]]).

**Blind critics advise; they do not override choices the user made explicitly.** When the user asked
for a checkbox and a critic proposes a segmented control, or the user picked a shake on error and a
critic wants it gone, the user's choice stands and the critic's other fixes are applied.

## Everything is looked at in the browser

After building and after every single correction, not only at the end:

- bring the app up locally, in its fake data mode, and open it on the LAN address
  ([[2026-08-22-convention-app-urls-with-local-ip]]);
- read the console and the network requests too;
- more than one viewport, and both themes when the page has them;
- motion cannot be judged from a still: drive the interaction and watch the transition;
- never ask the user to check whether it works; verify it and hand over the proof.

When the agent's browser cannot paint, switch tools rather than downgrading to numbers
([[2026-08-23-verify-frontend-findings-against-production]],
[[2026-09-30-howto-browser-verification-when-the-agent-tab-is-hidden]]).

## Links

- [[2026-08-26-convention-code-development-pipeline]]
- [[2026-08-30-convention-impeccable-craft-floor-rules-for-web]]
- [[2026-08-25-convention-pitches-as-web-artifacts-with-infographics]]
