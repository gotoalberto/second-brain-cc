---
id: 2026-09-13-howto-import-pptx-into-google-slides-without-api
title: Getting a local .pptx into Google Slides with no Drive or Slides API access
type: howto
area: [deliverables, browser-automation]
projects: []
tags: [google-slides, google-drive, pptx, browser-automation, no-api, slides, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## When this applies

Prefer the APIs: with a Google account connected with the `drive` scope and the Slides API enabled in the
OAuth project, a presentation can be created and edited directly
([[2026-09-22-howto-fill-google-doc-via-docs-api-batchupdate]]). This browser route is the fallback for
when neither API is available: build the slides locally as a `.pptx` (`python-pptx`) and merge them into an
existing deck through the web UI with the browser extension.

## Recipe

1. **Upload into a Drive tab.** On a `drive.google.com` tab, inject an `<input type="file">` with the
   JavaScript tool, get a reference to it with `find`, and use the file upload action to put the local
   `.pptx` into it.
2. **Drop it into Drive as a real upload.** Drive ignores a bare file input. Dispatch synthetic
   `dragenter`, `dragover` and `drop` events, each carrying a `DataTransfer` that holds the `File`, at
   `document.elementFromPoint(x, y)` over the file list. Drive treats it as a drag and drop upload. If a
   file with the same name exists, confirm "replace" or "keep both" in the upload options dialog.
3. **Import from inside the target deck.** Open the destination presentation, then File, Import slides.
   The picker is a **cross-origin iframe**: `find` and `read_page` cannot reach its upload input, and
   "Browse" opens a native file dialog that automation cannot drive. Use the picker's own search box
   instead (clear it first, it keeps the previous text), find the file uploaded in step 2, double-click it,
   then "Select all" and "Import slides". Keep "Keep original theme" ticked so the slides are not
   restyled.

## Gotchas

- A batch of browser steps has a short maximum wait per step; poll across several batches for the upload
  and the import.
- Custom web fonts in the `.pptx` render fine in Slides when they are embedded or web-available.
- With no local renderer, check every imported slide at full size in Slides itself.
- When the API route is used, Slides responses can contain raw control characters: parse them with
  `json.loads(text, strict=False)`. A strict parser failed on successful creates and hid them.

## Links

- [[2026-08-25-convention-pitches-as-web-artifacts-with-infographics]]
