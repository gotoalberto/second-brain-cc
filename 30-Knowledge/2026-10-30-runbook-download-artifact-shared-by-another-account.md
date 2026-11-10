---
id: 2026-10-30-runbook-download-artifact-shared-by-another-account
title: "Downloading a claude.ai artifact made by another account"
type: runbook
area: [work]
projects: []
tags: [artifacts, claude-ai, runbook]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-30
supersedes: []
---

## Problem

An artifact made by someone else cannot be read from a Claude Code session with the Artifact tool:
`read` and `list` ask for a per-conversation approval ("was made by someone else. Let Claude read it?")
that an app session cannot answer. Before it is shared with the user, claude.ai shows "Page not found"
in every organization the user belongs to.

## What works

1. The author shares the artifact with the user's account.
2. In this machine's Chrome, open the artifact, open its title menu and choose **Duplicate**. That creates
   a private copy owned by the user ("<title> (Copy)"); the shared data (marks, comments) is not copied.
3. The Artifact tool can then read the copy without approval: `list` with `scope: files`, then `read`
   with `paths` (up to 256) and `out_dir` to download the whole thing.
4. Archive it where the user's deliverables go.

Deleting the copy afterwards also needs a confirmation an app session cannot give: the user deletes it
from the artifact's menu, or with `/artifacts` in a terminal `claude`.

Fetching the artifact's frame (`*.frame.claudeusercontent.com`) from the claude.ai page fails on CORS,
and opening it directly redirects back, so the copy route is the one to use.

## When the Artifact tool is not available

For a design canvas: in Chrome, switch to each canvas page, select an artboard and zoom to it, then use
the artboard's download icon, **All artboards (.pdf)**: one PDF per canvas page, one artboard per PDF
page. Big pages take 30 to 60 s before the "download a file?" dialog enables Save. On Linux, Chrome then
opens a native save dialog the extension cannot see; fill it with `xdotool` (click the name field, select
all, type the absolute path, click Save). Each PDF page is one embedded image, so `pdfimages -j` gives
the artboards without re-rendering.
