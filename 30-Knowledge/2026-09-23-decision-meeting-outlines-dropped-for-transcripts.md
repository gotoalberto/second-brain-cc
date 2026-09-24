---
id: 2026-09-23-decision-meeting-outlines-dropped-for-transcripts
title: Meeting summaries are written from the full transcript, never from the recording tool's outline
type: decision
area: [communication, meetings]
projects: []
tags: [decision, meetings, transcript, summaries, publishing]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-23
supersedes: []
---

## What was decided

Nothing reads a meeting recording tool's generated outline, notes, summary or key points any
more. Every consumer (a scheduled post of the daily meeting to a team channel, the sweep that
files meetings into the vault, interview notes) fetches the **full transcript** and the agent
writes the summary itself, with the vault's context loaded.

## Why

The tool's note generation failed silently: on one day it produced no notes for three of four
meetings while every transcript was complete, and a scheduled post stalled for no good reason.
Its own error message suggested the notes existed. Regenerating them needed a browser signed in
to the tool, which not every machine has. The transcript is always there, so depending on it
removes the failure.

## Consequences

- A raw transcript is noisier than an outline: misheard names, unlabelled speakers, filler. The
  main editorial work is now the pass that corrects names of people, products and places against
  what the vault knows. Context corrects, it never adds.
- A meeting with no generated notes is never a blocker. A run fails only when the transcript
  itself is missing or empty.
- The summary follows [[2026-09-10-convention-write-like-a-person]].

## Links

- [[2026-08-28-convention-publishing-to-a-team-chat-channel]]
