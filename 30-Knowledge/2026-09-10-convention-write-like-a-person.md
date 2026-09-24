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
updated: 2026-09-24
supersedes: []
---

## The rule

Everything written for the user or in their name reads like a person wrote it, as simply as
possible. That covers chat replies, questions, emails, messages, drafts, documents,
reports, READMEs, PR and commit text.

1. **No dashes as punctuation.** No em dash, no en dash, no spaced hyphen used as a dash,
   and none of their encoded forms (`---`, `--`, `&mdash;`, `&ndash;`,
   `\textemdash`, `\textendash`). A hyphen inside a
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
5. **Messages in the user's name sound like them:** direct, friendly, brief. No corporate filler,
   no signature block unless the user uses one.

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

## Shapes in body text, in any language

The same habits show up in the body of replies and documents, in English and in any other
language the user reads. None of these go into a reply to the user or a document written for
the user or in their name. Spanish is the example second language here.

| Shape | English example | Spanish example | Write instead |
|---|---|---|---|
| Aphoristic opener | "Two questions travel together." | «Son dos preguntas que van juntas.» | say what the document covers |
| Label and colon before the point | "The ask: a bigger budget." "The risk: ..." | «La petición: ...», «El riesgo: ...», «Lo importante: ...» | a normal sentence: "We are asking for a bigger budget." |
| Contrast built to sound conclusive | "billed per request, not a flat fee", "it's not a workaround, it's a fix" | «no es un gasto, es una inversión» | state the fact; if the contrast matters, give it its own sentence |
| Announced count | "Three things decide the release date." | «Dos cosas a tener en cuenta» | just give the list |
| Personified abstraction | "the roadmap leans on", "where the upside sits" | «el trimestre carga con...» | say who or what does it |
| Stock phrase | "That is the whole idea", "worth reading once", "on purpose", "does not bite", "genuinely" | «más o menos en equilibrio», «dicho de otra forma», «en definitiva» | plain words |
| Drama and verdicts | "the picture changes a lot" | «esa es la diferencia real entre...» | the number, stated |

## The mechanical check

Knowing the rule has never been enough: it sat in the startup context and was still broken,
again and again. So it is checked by code.

- `_bin/style_check.py` holds the patterns (English and Spanish) and skips quotes, code,
  blockquotes and URLs, since a verbatim quote stays as it was said. `style_check.py FILE...`
  reads txt, md, html and docx; `-` reads stdin; `--gdoc DOC_ID --account NAME` exports a Google
  Doc through a `google.py` account. Exit 1 on any finding. Tests: `_bin/style_check_test.py`.
- **The Stop hook `style_gate.py`** (event `stop-style-gate` in `90-Meta/events.json`) scans every
  chat reply and blocks the stop once, asking for the reply to be sent again rewritten, with the
  same facts and numbers and without mentioning the check. It never blocks twice on the same text
  and fails open. Better to write plainly from the start so it never fires.
- **Every document is checked before it is delivered**: run `style_check.py` on the file, or with
  `--gdoc` on the Google Doc after uploading it, and fix every finding. Skills and scheduled
  routines that write documents carry the same step, since a headless prompt only obeys the
  conventions it names.
- When a new shape turns up, add it to `style_check.py` with a case in `CAUGHT` in the test, and an
  ordinary sentence that must not trip it in `CLEAN`. Add the patterns of your own language the
  same way.

## Watch out for

- **A rule that only lives in a note does not reach sessions.** This one is in
  `90-Meta/PROTOCOL-COMPACT.md` and `90-Meta/AGENT-PROTOCOL.md`, and pasted into the agent
  definitions, because subagents never see the startup protocol.
- Before sending any draft, scan it for dashes, then read the headings alone. The dash scan is
  its own separate step (`style_check.py` does it, along with the other shapes above), never
  folded into a general reread. It is needed even when this rule is already in the
  session's context. Knowing the rule is not the same as checking for it, and the usual slip sits
  where a pause feels natural, such as right after the greeting.
- When summarising a dense technical source (design docs, an architecture, a spec), translate its
  vocabulary into plain language instead of compressing it. Every term is explained the first time
  it appears, headings stay plain topics, and the same pass covers diagram labels, captions and
  tooltips as well as the body text. A deck that keeps the source's jargon reads as machine written
  and cannot be understood by the people it was made for.
- The dash ban also covers vault notes and code comments.
- For generated documents (LaTeX, HTML rendered to PDF), run a check that fails on dash characters
  and their encoded forms before rendering. A rule that only lives in template documentation gets
  broken as soon as the work speeds up.
- Text taken from other tools (transcripts, generated summaries, meeting notes) is rewritten into
  this style, never copied through with its dashes and filler.
- **A message to a senior reader is one short sentence.** Draft the full argument for the user's
  own use if it helps, then give the sendable version as one or two plain sentences, with no bold
  and none of the internal framework's vocabulary, however long the analysis behind it. Offer the
  long version separately.
- Adapt the list to your own taste. The patterns in `style_check.py` are meant to be edited.

## Links

- [[2026-09-08-convention-vault-is-written-in-english]]
- [[2026-09-15-convention-language-per-audience]]
- [[2026-09-15-convention-never-assess-peoples-workload]]
- [[2026-08-29-convention-decisions-as-plain-text-lettered-lists]]
- [[2026-09-15-convention-descriptive-language-no-internal-labels]]
- [[2026-09-08-convention-one-question-at-a-time-when-answer-may-be-uncomfortable]]
