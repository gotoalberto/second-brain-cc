---
id: 2026-09-22-howto-fill-google-doc-via-docs-api-batchupdate
title: Filling a Google Doc template through the Docs API batchUpdate
type: howto
area: [tooling, deliverables]
projects: []
tags: [google-docs, docs-api, google.py, templates, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-22
supersedes: []
---

## Context

A copied Google Doc template had to be filled with task specific text: several sections, several
placeholders. Driving the browser's own Find and Replace works but is fragile (viewport reflow,
clicks that land twice). The same result comes out with no browser at all by calling the Docs API.

## How

**Send `replaceAllText` requests in one `documents/<id>:batchUpdate` call.** It applies them
atomically, and it is reliable when the target is a native Google Doc (not a `.docx` opened in
Office editing mode, where `batchUpdate` does not apply) and every placeholder is a unique marker
string.

```sh
cat > "$SCRATCH/fill.json" <<'JSON'
{"requests": [
  {"replaceAllText": {"containsText": {"text": "{{ROLE}}", "matchCase": true}, "replaceText": "Example role"}},
  {"replaceAllText": {"containsText": {"text": "{{TEAM}}", "matchCase": true}, "replaceText": "Example team"}}
]}
JSON
python3 ~/Brain/_bin/google.py api --account <name> --method POST --body-file "$SCRATCH/fill.json" \
  "https://docs.googleapis.com/v1/documents/<doc id>:batchUpdate"
```

The account's `drive` scope is enough for the Docs API; no separate documents scope is needed.

## Traps

- **`google.py api` takes the full URL**, not a path fragment. Always pass the complete
  `https://docs.googleapis.com/...` or Drive URL.
- **`google.py api` parses the response as JSON.** That breaks any call whose answer is not JSON,
  such as exporting a doc as plain text (`/export?mimeType=text/plain`). For those, take a token with
  `google.py token --account <name>` and call `curl` yourself.
- **Repeated placeholders leave duplicates behind.** When the same placeholder appears on several
  nearby lines (a block of four "choose a tag" lines, say), one blind pass can leave a duplicated block.
  Handle a repeated block as one unit, then export the text and check that area again rather than
  trusting a single pass.

## Links

[[2026-09-23-howto-google-doc-with-charts-and-a-linked-editable-sheet]]
