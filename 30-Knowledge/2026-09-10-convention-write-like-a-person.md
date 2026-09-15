---
id: 2026-09-10-convention-write-like-a-person
title: Write for the user the way a person would
type: convention
area: [writing]
projects: []
tags: [writing, style, headings, communication, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The rule

Everything written for the user or in their name reads like a person wrote it, as simply as
possible. That covers chat replies, questions, emails, messages, drafts, documents,
reports, READMEs, PR and commit text.

1. **No dashes as punctuation.** No em dash, no en dash, no spaced hyphen used as a dash,
   and none of their encoded forms (`---`, `--`, `&mdash;`, `&ndash;`). A hyphen inside a
   word is fine. Use a comma, a full stop, a colon or parentheses; usually rewriting the
   sentence is best. For ranges write "to" (`pages 10 to 20`).
2. **Plain words, short sentences.** Say it the way you would to a colleague. Answer first,
   then only the context they need.
3. **No excess detail.** Leave out token counts, file counts, line numbers, internal tool
   names and step by step narration unless asked. If one sentence covers it, one sentence
   is the answer.
4. **Drop the AI tells:** headers, bold and bullet lists on short answers; arrows, emoji and
   decorative symbols; stock openers and closers ("Great question", "I hope this helps");
   recaps; lists of options that will not be pursued; forced triads; "it's not X, it's Y";
   stacked hedges; over-formal vocabulary where a normal word exists.
5. **Messages in the user's name sound like them:** direct, friendly, brief.

Structure is still fine when the content really is a list or a table. The test: would a
careful person writing by hand format it this way?

## Titles and headings

People use a heading as a label for what the section covers, so the reader can find it:
"Viable options", "Implementation", "Risks", "Test plan". The conclusion goes in the first
sentence under the heading.

The AI habit is to turn every heading into a headline that announces the finding. Seen once
it is a style; seen in every section it is a signature. Shapes to avoid:

1. Count and reveal: "Five ways to cache it, and only one survives a restart".
2. "It's not X, it's Y", "X, not Y".
3. A triad or list as the title: "One queue, two workers and a retry loop".
4. Parallel antithesis: "The client asks, the server decides".
5. Colon reveal: "The key: ...", "The trap: ...", "The real pattern: ...".
6. "The real X", "What actually happened".
7. Dramatic absolutes: "... in silence", "and nobody noticed".
8. "Why it matters" as a heading.
9. Rhetorical questions as headings.
10. Aphorisms and story headings.

**How to check a draft:** read only the headings, top to bottom. They should read like a
table of contents a person would write.

This also covers vault notes: the `title:` and section headings of every note, context pack
and plan. A decision note may state its decision in the title, plainly ("Startup context
budget only warns and is raised when full").

## Watch out for

- **A rule that only lives in a note does not reach sessions.** This one is in
  `90-Meta/PROTOCOL-COMPACT.md` and `90-Meta/AGENT-PROTOCOL.md`, and pasted into the agent
  definitions, because subagents never see the startup protocol.
- Before sending any draft, scan it for dashes, then read the headings alone.
- Adapt the list to your own taste. It is a convention, not code.

## Links

- [[2026-09-08-convention-vault-is-written-in-english]]
- [[2026-09-15-convention-descriptive-language-no-internal-labels]]
- [[2026-09-08-convention-one-question-at-a-time-when-answer-may-be-uncomfortable]]
