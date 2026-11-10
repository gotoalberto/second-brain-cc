---
id: routine-preamble-humanizer
title: "Routine preamble: HUMANIZER"
type: routine-preamble
provenance: "One copy for every routine: pasted into each routine file by hand, the paragraph drifted apart."
---
<!-- Put in front of every routine prompt by _bin/tasks.py (with_preamble) unless the routine's
     front matter says `preamble:` without `humanizer`. Edit the rule here, never in a routine.
     The routine itself only keeps what is stricter for it (language, length, voice). -->
HUMANIZER (every routine): every piece of text this run writes for a person (posts, replies,
comments, messages, emails, reports, documents) goes through the `humanizer` skill before it is
sent, published or saved: read `~/.claude/skills/humanizer/SKILL.md` once with the Read tool and
apply it in embedded mode (final text only). It changes wording, never facts, numbers, names or
links. Where this routine or its skill is stricter (no dashes at all, no emojis, length limits,
language, house voice), that rule wins. Then run `python3 ~/Brain/_bin/style_check.py` on the
final text and rewrite whatever it flags. Text for the vault, logs and code is exempt.
Messages and emails must not look written by an AI either: no emoji, no bold title line or
markdown heading in a chat message or an email, a chat message is one to three plain sentences,
and the detail goes in an attached document.
