---
name: dev
description: Code development pipeline. Use it whenever the task produces code (backend, frontend, scripts, a website or an HTML deliverable). It enforces tests before implementation with red commits first, hexagonal architecture, and for anything with an interface a design interview, a design skill stack, motion built with animation skills, three critique rounds and verification in a real browser after every correction. Do not use it for tasks that produce no code.
argument-hint: [task description]
---

Develop «$ARGUMENTS» with the code pipeline. This does **not** replace `/task`, it extends it: follow
the `/task` procedure (context, worktree, plan, implementation, verification, integration, memory) and
apply the gates below on top. They are mandatory and verifiable, not recommendations.

## Current state

- Directory: !`pwd`
- Repository: !`/usr/bin/git rev-parse --show-toplevel 2>/dev/null || echo "(not a git repo)"`
- Project conventions: !`/usr/bin/python3 __VAULT__/_bin/query.py "convention code architecture tests" 2>/dev/null | head -6 || true`

---

## Gate 1: tests first, always

**No implementation line is written before a test exists that fails for its absence.** This is the
condition for reaching Gate 2.

For each unit of behaviour:

1. **Red.** Write the test. Run it. **Show it failing.** A test that passes before anything is
   implemented does not prove what you think and has to be redone.
2. **Green.** The minimum implementation that turns it green.
3. **Refactor**, with the tests green, running them again afterwards.

**Coverage before implementing.** The suite covers the whole behaviour first: the happy path, the edges
and the failure modes. A case that is not in the tests has not been agreed.

**How it is verified.** The worktree's history must show the test commits **before** the implementation
commits. It is the one piece of evidence that cannot be faked after the fact:

```
/usr/bin/git -C <worktree> log --oneline --name-only
```

Tests in the same commit as the code, or after it, mean the gate was not passed. Say so and redo the
work; do not reorder commits to hide it.

**What does not count as a test:** asserting that a string appears in the source, checking that a
function exists, or any test that would pass with the bug still in place. If the test passed before the
fix, the test is worthless. A green run of source-pattern tests also does not prove the file compiles:
run the build.

For a deletion the direction flips: the test is red against the current code, and it comes with an
over-deletion guard that passes on both sides.

## Gate 2: hexagonal architecture

Ports and adapters, with no "this one is small" exceptions.

```
domain/           business rules. No framework, database, HTTP, clock or filesystem.
application/      use cases. They orchestrate the domain and depend on ports, never implementations.
ports/            the interfaces the inside needs from the outside.
adapters/         whatever touches the world: HTTP, SQL, queues, object storage, UI, clocks.
                  They depend inwards, never the other way round.
```

Dependencies always point towards the domain. A domain import that names a framework, a database
library or an HTTP request is wrong.

The consequence that makes it worth it: **the domain and the use cases are testable without standing
anything up.** If testing a business rule needs a database, a server or a browser, the boundary is in
the wrong place. Adapters are tested against the port, with doubles inside and a few slow contract
tests against the real thing.

---

## Gate 3: design, only if the deliverable has an interface

A website, an HTML page, an app, a dashboard, a component. **Backend-only work skips this gate** and no
design questions are asked.

### 3a. Design interview before building

Never start laying anything out without asking. A visual deliverable built on assumptions gets thrown
away, not corrected. Ask, with a structured question when the options can be listed, and above all ask
for concrete examples:

1. **References.** Two or three sites or screenshots they like, and **what** they like about each:
   typography, density, colour.
2. **Anti-references.** What they do not want. Often more informative.
3. **Tone.** Sober and utilitarian, or editorial with character. What it should feel like.
4. **Real constraints.** Brand, required typefaces, palette, design system, where it will be seen.
5. **Real content.** Real copy and images, not filler. If there is none, say so before starting.

If the user says "you decide", propose one concrete, described direction and confirm it before building.

**No strong reference to anchor on?** Don't fall back on the generic AI default (purple gradient
hero, text-left/graphic-right, three feature cards). Two techniques help:

- **Seed-string technique.** Generate a long random alphanumeric string first, derive the creative
  direction from it (colour, layout, typography, looking for subpatterns, not the literal
  characters), and don't reveal the string in the output. The randomness has to come from outside
  the model: asking it to "be random" or "totally unique" just produces confident fake variety
  with the same underlying defaults.
- **Ambitious/wild prompting loop.** Anchor the brief to a concrete external inspiration (a video
  game, an interior-design movement, an art installation) instead of an abstract adjective. To find
  the inspiration: ask for many shallow ideas (breadth, no detail), react to favourites and note
  what's specifically off, ask for a refinement based on that reaction, then have it write the
  concise build prompt for the refined direction. A direction that sounds like it can't work is
  often worth trying anyway.

Full rationale: `~/Brain/30-Knowledge/2026-09-18-convention-anti-ai-slop-design-techniques.md`.

### 3b. The skill stack

A web interface is not laid out by hand. This gate expects four **third-party skills**, installed
separately (this repository does not ship them):

| Skill | What it brings | Where it comes from |
|---|---|---|
| `impeccable` | Visual hierarchy, typography, spacing, a quality floor, and the `critique` command used in 3d | https://impeccable.style |
| `frontend-design` | Aesthetic direction, so the result does not read as a template | Anthropic's public skills repository |
| `design-taste-frontend` | An anti-template pass for landing pages, portfolios and redesigns | the `leonxlnx/taste-skill` repository |
| `emil-design-eng` | Component polish and the entry to the animation skills in 3c | Emil Kowalski's skills repository |

They are not alternatives. `impeccable` runs the process and the other three inform the judgement
inside it. If one is missing on the machine, install it before building, for example:

```bash
npx skills@latest add emilkowalski/skills -g -a claude-code -s '*' -y
npx skills@latest add anthropics/skills -g -a claude-code -s frontend-design -y
npx skills@latest add leonxlnx/taste-skill -g -a claude-code -s design-taste-frontend -y
```

Check each project's own instructions for the current install command. If a skill cannot be installed,
say so in the closing instead of pretending the gate was met.

### 3c. Motion

**Every web deliverable ships with motion**: state changes, entrances, exits, hovers and transitions are
part of it. Build them with the animation skills from Emil Kowalski's repository, never by guessing
values:

- `animate` to build each one, deciding in order: should it animate at all, why, which properties,
  which curve, how long, how it is interrupted, how it exits;
- `find-animation-opportunities` to find what should move and rule out what should stay still;
- `review-animations` to review the motion before the critique rounds;
- `animate-expo` instead of `animate` for React Native or Expo;
- `apple-design` for gestures, springs, sheets and interruptible transitions.

Left to itself, an agent picks the wrong easing for an entrance and a hard border where a soft shadow
belongs. Small things that add up to an interface that feels cheap.

### 3d. Three critique rounds, minimum

Before calling a website or page finished:

```
/impeccable critique <target>
```

**Three complete rounds, each with its corrections applied.** Reading the critique and saying it looks
fine is not a round. Each round starts from the corrected result of the previous one. This is a
mechanical pass (typography, spacing, accessibility, the checklist rules in `design-taste-frontend`).

**On top of that, at least one round is blind.** Self-review is not objective: the agent that built
the page is anchored on its own code, decisions and rationale, and can't easily zoom out and think
differently. Spawn a fresh subagent as design critic, given only a screenshot, never the code, the
implementation history or the builder's own rationale, and ask it to:

- name the aesthetic the design is going for, imagine how a top design studio would execute that
  specific aesthetic, and list the concrete gaps between the two;
- watch for patterns that feel overdone, excessive or otherwise obviously AI-generated;
- give tight, specific feedback, not vague prose, bold and opinionated, not safe;
- return a score.

Apply its fixes, then run it again in a new fresh context (no memory of the previous round) until it
independently clears the bar. Don't put the passing threshold in the critic's own prompt: it scores
honestly only if it doesn't know what score it needs to hit. Prefer objective, comparative framing
over vague ones: worst is "does this look beautiful, not AI-generated"; best is "here are N
professional references and one screenshot of ours, rank by polish" (real reference images help, as
a moodboard, not a copy target).

Full rationale: `~/Brain/30-Knowledge/2026-09-18-convention-anti-ai-slop-design-techniques.md`.

### 3e. One round only about the images

At least one whole round looks at each image:

- **Framing.** Is the subject where it should be?
- **Crop.** Does the ratio match its slot, or is it stretched or letterboxed?
- **Quality.** Pixelated, over-compressed, heavier than it is worth?
- **Consistency.** Do the images share a treatment?
- **Background.** Does the image background match what it sits on, or is the box visible?
- **What is actually visible.** Look at each one: a screenshot can carry details the copy never
  mentions, and they survive until someone else spots them.

Fix them: crop, reframe, recompress, replace. Verify with a screenshot, not from memory.

### 3f. Generated media over CSS-only decoration, when it earns its place

Coding agents default to gradients, shapes and CSS-only patterns instead of real images or motion
because that's the path of least resistance, not because it looks better. Two tools to reach for
deliberately, never as a default on every project:

- **Image generation plus shader/3D effects, combined.** A generated image alone still reads as a
  stock photo; a shader or 3D effect alone still reads as a template. Layering a generated image
  with an effect on top (refraction, glass, lighting) is what reads as deliberate craft.
- **Video generation** (an aggregator such as fal.ai, so the choice of model doesn't go stale) for
  motion the CSS/animation toolkit in 3c can't produce: a looping decorative clip (generate on a
  solid background, then chroma-key or matte it out so it drops into the UI like a layered asset)
  or a fluid transition between two UI states (generate two keyframe stills, then use a video
  model's interpolation mode to animate between them, scrubbed by scroll or triggered by
  navigation).

Keys for image/video generation always come from `kp`, never pasted into chat or committed to the
repo: a low-limit key dedicated to the agent's own use.

Full rationale: `~/Brain/30-Knowledge/2026-09-18-convention-anti-ai-slop-design-techniques.md`.

### 3g. Everything is looked at in a real browser

After building, after every critique round and after every single correction, open the page in the
agent's browser tool and look at it. A fix nobody saw rendered is a fix nobody knows works.

- Whether this machine has a browser:
  `~/Brain/30-Knowledge/2026-09-21-reference-where-claude-in-chrome-is-available.md`. Every
  supported environment (macOS and Linux) has its own Chrome with the Claude extension; the
  session-start `## This machine` block says whether it is usable here. Never decide from the OS.
- Start it through the agent's preview or browser tooling, not a stray background server.
- Give the user the app's LAN address, not `localhost`, and verify in the agent's own browser on
  `localhost`: `~/Brain/30-Knowledge/2026-08-22-convention-app-urls-with-local-ip.md`.
- Follow the house style and the craft floor:
  `~/Brain/30-Knowledge/2026-08-30-convention-impeccable-craft-floor-rules-for-web.md`.
- Check the console and network requests, not only the screenshot.
- Look at more than one size (phone, tablet, desktop) and both themes when the page has them.
- Motion cannot be judged from a still: drive the interaction and watch the transition.

**Never ask the user to check whether it works.** Verify it and hand over the proof.

---

## Closing

On top of the `/task` closing, state:

- **Gate 1:** the command showing the tests committed before the implementation.
- **Gate 2:** where the boundary is and what is testable without standing anything up.
- **Gate 3:** which design skills were used, what motion was added and with which skill, how many
  critique rounds (mechanical and blind) and what each changed, whether generated images or video
  were used, what was fixed in the images, and that it was checked in the browser.

If a gate could not be passed, **say so in the closing**. A gate skipped silently is worse than no gate,
because it creates the impression it was met.

## Rules

- The gates are not traded for speed. If there is no time, cut scope, not process.
- If the user asks to skip one, skip it (it is their project), but state it in the closing and record
  it in the vault.
- Architecture and design decisions agreed here are saved as project conventions, so `context-scout`
  brings them next time.

## Language

- **Everything written into the vault goes in English**: `title:`, `tags:`, the prose. A verbatim
  quote keeps the language it was said in, with the English alongside. Answer the user in their
  language; the note goes in English, because retrieval is lexical and a note in another language is
  unreachable by search:
  `~/Brain/30-Knowledge/2026-09-08-convention-vault-is-written-in-english.md`.
