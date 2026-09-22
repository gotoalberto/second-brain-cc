---
id: 2026-09-17-trap-measurement-artefacts-shaped-like-answers
title: Measurement artefacts that look like real answers
type: analysis
area: [verification, measurement]
projects: []
tags: [measurement, methodology, timeouts, sampling-window, false-negative, analysis]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-17
supersedes: []
---

Two failures from one investigation with the same shape: an artefact of how something was measured,
presented in exactly the same form as a real answer, with nothing in the output to tell them apart.

## A bounded window reported as an unbounded fact

A census ranked producers by how many items each had created, over a fixed recent window, and
presented the result as the ranking of all producers, with no window attached to the numbers. Run
again over all history, one producer went from a modest count to many times more and from an
unremarkable row to the largest by traffic. Its activity had started before the window opened. The
ordering changed, not only the sizes.

- State the window with the number, always: "118 items between X and Y", never "118 items". A
  count with no window reads as a claim about all time.
- Ask over all history when the tool allows it. If a window is unavoidable (cost, retention), choose
  it on purpose and say so, instead of inheriting whatever window an earlier query used.
- Before trusting a ranking, ask whether the top rows could have started before the window. A low
  rank is a fact about the window until it is checked against all history.

## A timeout reported as an empty result

A helper polled an asynchronous query service a fixed number of times, then left the loop without
checking the final state, fetched whatever results existed and printed them. For a query still
queued that is "rows: 0", identical to a query that matched nothing. Correct queries were doubted for
hours, and the leading theory (the service lacked the data) contradicted what was already known.

The tell: even `SELECT count(*)` returned zero rows. An aggregate always returns exactly one row, so
zero rows (as opposed to a count of zero) is a tooling fault, not a data fact. Reading the raw status
showed the query had sat in the queue for longer than the helper waited, while a
trivial query answered instantly and made the service look healthy.

- A poller that stops waiting must check the final state and fail loudly on a timeout, printing the
  last known state and the job id so the result can be fetched later. Make the wait configurable.
- When a result is structurally impossible (zero rows from an aggregate, an empty answer to a query
  shape that worked before), check the job's status before doubting the query or the data.
- An instrument that reports a timeout as emptiness makes you disbelieve correct work. Had the zero
  been trusted here, the write up would have contradicted evidence already in the same repository.

## Links

- [[2026-09-13-analysis-a-negative-result-is-a-claim-about-the-measurement]]
- [[2026-09-08-analysis-every-instrument-watches-one-surface-and-reports-on-all-of-them]]
- [[2026-09-17-convention-measuring-candidate-models-against-ground-truth]]
- [[2026-09-17-trap-a-negative-search-result-calcifies-into-a-permanent-fact]]
