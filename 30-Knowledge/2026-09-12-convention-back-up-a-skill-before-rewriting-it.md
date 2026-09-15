---
id: 2026-09-12-convention-back-up-a-skill-before-rewriting-it
title: Skill lifecycle in the vault
type: convention
area: [tooling, skills]
projects: []
tags: [skills, self-contained, backup, install-plugin, skill-forge, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## When a skill is created

A procedure carried out the same way twice, or a correction the user has had to make twice,
becomes a skill. `skill-forge` does it: it checks the catalogue in `40-Skills/` for something
equivalent, improves that if it exists, and otherwise creates the skill and records the case it
was born from. One occurrence is not a pattern; a catalogue of skills nobody invokes is worse
than none.

## A skill is self-contained

Everything a skill needs in order to run lives in its own directory: the method, the playbooks,
the worked commands, the scripts in `tools/`. Nothing it needs lives in a repository it points
at.

The test for any line: **if that external directory did not exist on this machine, could the
skill still be run end to end?** If not, the content belongs inside the skill.

A skill once named a local working copy of another repository as its "canonical manual". That
working copy was deleted by an unrelated session. The skill did not fail loudly; it became
unrunnable and would have stayed that way until someone tried it. Repointing the path is not the
fix, because it keeps the dependency. The fix is to bring the content in.

Saying where a method came from is fine. Provenance is a sentence, never a step.

## Where skills live

- `integrations/claude-code/plugin/brain/skills/` and `.../agents/` in the vault are
  **canonical**. `~/.claude/skills/` and `~/.claude/agents/` hold installed copies.
- `_bin/install_plugin.py` keeps the two in step, three way, from a manifest of what each side
  was last synced to: a vault change is installed, a live edit is back-ported into the vault, and
  a skill changed on both sides is left alone and reported as a conflict.
- Nothing is overwritten without a backup: every replaced copy goes to the Brain state directory
  first as a tar.gz, with a diff for back-ports and conflicts.

```sh
python3 ~/Brain/_bin/install_plugin.py status   # what each skill and agent needs
python3 ~/Brain/_bin/install_plugin.py sync     # apply it
```

A skill edit that has not been synced exists in one place with no history. Sync when you finish.

## Before a wholesale rewrite

The automatic backup covers only what a sync replaces. Before handing a skill to an agent for a
large rewrite, take a manual copy of the skill and its siblings:

```sh
tar -czf "<scratch dir>/skills-backup-$(date +%Y%m%d-%H%M%S).tar.gz" \
    -C ~/.claude skills/<name> [skills/<sibling> ...]
```

Back up every skill in the family: a change to one usually means edits to the siblings that
reference it.

## Habits that go with it

- Never delete a reference file without moving its content somewhere. Renumbering or merging
  `references/` pages is where content quietly disappears.
- Before deleting a worktree, repository or directory, grep the skills for its path.
- Editing the same skill on both sides between two syncs is a conflict; resolve it from the two
  backups and the diff, then sync.

## Links

- [[2026-09-15-runbook-brain-events]]
- [[2026-09-08-failure-scheduled-tasks-write-into-the-vault-unguarded]]
