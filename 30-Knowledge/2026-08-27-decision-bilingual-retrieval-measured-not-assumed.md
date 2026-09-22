---
id: 2026-08-27-decision-bilingual-retrieval-measured-not-assumed
title: Retrieval in a second language over an English vault is measured with a held-out set
type: decision
area: [memory-system]
projects: []
tags: [retrieval, glossary, bilingual, evaluation, coverage, decision]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; the history numbers are illustrative, the last section was measured on this repository"
updated: 2026-09-22
supersedes: []
---

## What was decided

The Spanish to English bridge (`GLOSARIO` in `_bin/brainlib.py`) is built from the vault's
own vocabulary and validated by an eval, never extended by intuition. Spanish is the example
language; the same approach works for any language a user asks in while the vault stays in
English ([[2026-09-08-convention-vault-is-written-in-english]]). Three mechanisms carry it:

1. **The glossary maps onto terms the vault actually uses.** Candidates come from word
   frequency over the index, filtered to what no Spanish word can already reach. A glossary
   written by guessing looked complete and left five of fifteen questions mute.
2. **One word may carry several senses.** A value can name more than one English word
   (`"guardan": "save store"`). Both are searched and coverage counts the group once;
   otherwise a synonym enlarges the denominator and penalises the notes it was added to reach.
3. **Coverage tolerates bounded inflection.** `store` counts a note saying `stored`,
   `machine` counts `machines`. The suffix set is closed and the stem must be four or more
   characters, so a short word cannot match a longer unrelated one.

## Why

Retrieval is lexical. An unbridged Spanish term matches no note, so it adds nothing to the
search and pure weight to the coverage denominator, and the real terms next to it fall under
the threshold. The question is searched, its answer is discarded, and nothing logs an error.
The first measurement of a working vault scored 61% parity with five of fifteen questions
mute or disjoint. The mechanism was fine; words like `contexto`, `arranque` and
`presupuesto` simply had no bridge.

## How it is measured

`_bin/bilingual_eval.py` asks pairs of questions (Spanish, English twin) through the real
retrieval hook. A pair fails when the Spanish side surfaces nothing while its twin does
(MUTE) or when the two share no note (DISJOINT). Note count alone is not a pass: a Spanish
question about where files are stored once returned nine notes, none about files. Nothing
on either side is reported as a gap in the vault, apart from the failures.

Two rules the eval had to learn:

- **A fresh session id per run.** Retrieval dedups notes already injected to a session and
  raises that session's threshold after misses. Reusing ids measures the dedup.
- **A held-out set.** After the first pass scored 15 of 15 on the questions the glossary was
  fitted to, ten questions it had not seen scored 4 of 10. Fitting the glossary to the
  questions you test with proves nothing. The fitted set measures regression; the held-out
  set measures generalisation, and it is spent the moment the glossary is extended to make
  it pass.

## A tempting fix that is wrong

Dropping prompt terms that appear in no note looks like it removes unbridged Spanish from the
denominator, and it measures well on questions about topics the vault covers. It cannot tell
two cases apart: a Spanish word with no bridge (noise), and the subject of a question about
something the vault has never heard of (the reason to stay quiet). Gating on it made out of
vault prompts inject unrelated notes matched on their filler words. A retrieval system that
invents relevance for what it does not know is worse than one that says nothing.

## Learning from real misses

`retrieve.py` records the terms of every `no-hits` and `below-threshold` miss in the metrics
table, scrubbed of credentials. `bilingual_eval.py --from-misses` lists the missed terms the
vault has never used and no glossary value reaches, and every full run prints that list too.
A term there is one of three things:

- a Spanish word with no bridge: add a `GLOSARIO` entry;
- a proper noun: nothing, people say product names as they are;
- a subject the vault does not cover: write a note, never a glossary entry.

The users' own questions are an honest source that does not run out, unlike an invented set.
`doctor.py` also reports how much of the vault's frequent vocabulary no Spanish word reaches.

## On this repository

Measured on 2026-09-22 against the example vault in this repository (124 notes), with a
scratch HOME: fitted set 13 of 15 pass (one mute, one disjoint), held-out set 4 of 10 pass
(four mute, two disjoint), no vault gaps. The held-out result is the honest one and was left
as it is: extending the glossary for those words would spend the set.

## Links

- [[2026-09-08-convention-vault-is-written-in-english]]
- [[2026-09-13-analysis-a-negative-result-is-a-claim-about-the-measurement]]
- [[2026-09-17-trap-measurement-artefacts-shaped-like-answers]]
- [[2026-09-08-analysis-every-instrument-watches-one-surface-and-reports-on-all-of-them]]
