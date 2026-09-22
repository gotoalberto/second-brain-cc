---
id: 2026-09-16-gotcha-skill-notes-are-truncated-not-corrupt
title: Skill catalogue notes cut mid-sentence by skills_index.py
type: gotcha
area: [harness]
projects: []
tags: [skills, skills-index, 40-skills, generated, truncation, false-alarm]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-16
supersedes: []
---

## What it looks like

A note in `40-Skills/` ends mid-sentence, sometimes mid-word, often with an unterminated `**`:

```
2. **A secret is never printed.*
```

It reads like a truncated write or a bad merge. It is neither.

## What it is

`_bin/skills_index.py` builds the `**Instructions (excerpt)**` block of each skill note with

```python
"body": body.strip()[:1200],
```

a hard slice of 1200 characters, with no line or word boundary and no check that the Markdown stays
balanced. Whatever sits at offset 1200 is where the note stops. Every skill note is cut this way,
not one. Editing a skill does not corrupt its note; it moves where the cut lands, which is what makes
the damage look new.

## Why a hand fix does not hold

The excerpt sits between `<!-- AUTO:BEGIN -->` and `<!-- AUTO:END -->`, and `skills_index.py`
rewrites everything between those markers on every run, at session start. Repairing it by hand is
undone by the next session on any machine, and when two machines disagree about the file it comes
back as a sync diff, which looks like the corruption returning. Only the section after `AUTO:END`
belongs to people and survives.

## What to do

- Seeing it: nothing. The excerpt changes no behaviour. The real instructions live in
  `integrations/claude-code/plugin/brain/skills/<name>/SKILL.md` and in the installed copy under
  `~/.claude/skills/`. Check that `install_plugin.py status` reports them the same and move on.
- Fixing it properly, if it bothers you: cut the excerpt at the last whole line under the limit (a
  word boundary if a single line is longer), mark the cut, and close any bold or code fence the
  excerpt leaves open. Pin that with a test next to `skills_index.py`.

## Links

- [[2026-09-12-convention-back-up-a-skill-before-rewriting-it]]
