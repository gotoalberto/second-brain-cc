---
id: 2026-09-23-howto-google-doc-with-charts-and-a-linked-editable-sheet
title: A Google Doc deliverable with embedded charts and a linked editable Sheet
type: howto
area: [tooling, deliverables]
projects: []
tags: [google-docs, google-sheets, drive, charts, svg, headless-chrome, python-docx, deliverable, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-23
supersedes: []
---

## When to use this

A user who asks for business deliverables "as a Google Drive document" often wants more than text:
charts drawn first as HTML and embedded as images, and every calculation living in a Google Sheet with
editable formulas that the document links to, with the chart HTML kept alongside so a chart can be
edited later without rebuilding it.

## The pipeline

1. **Charts**: one standalone HTML file per chart with inline SVG written from Python. No chart
   library and no network dependency at render time beyond a webfont.
2. **Render**: `google-chrome --headless=new --disable-gpu --hide-scrollbars
   --force-device-scale-factor=2 --virtual-time-budget=6000 --screenshot=x.png
   --window-size=1400,<h> file://<abs path>`. The `--virtual-time-budget` is what lets the webfont
   land; without it the text renders in the fallback font.
3. **Crop**: the window height is always a guess, so trim the dead space afterwards with Pillow,
   scanning rows from the bottom for the first one that differs from the corner pixel.
4. **Document**: build a `.docx` with `python-docx`, then upload it to Drive asking for conversion.
   Do not build the doc through the Docs API with `insertInlineImage`: that needs a publicly
   fetchable image URI, which means sharing the PNGs by link first.
5. **Upload**: `POST https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart` with a
   `multipart/related` body, metadata `{"mimeType":"application/vnd.google-apps.document"}` and the
   docx bytes, using a token from `google.py token --account <name>`. **To revise in place,
   `PATCH .../files/<id>?uploadType=multipart`** with the same body, so the link the user already has
   keeps working.
6. **Sheet**: create it with `POST /v4/spreadsheets`, write formulas with
   `valueInputOption=USER_ENTERED`, format with `:batchUpdate`. Link it from the doc.
7. **Keep the sources**: `files.py put charts/*.html charts/*.png *.py *.docx --to <note> --project
   <slug>`, so the next revision starts from the generators
   ([[2026-09-15-decision-file-vault-in-a-local-directory]]).

## Gotchas

- **`python-docx` may not be installed**, and a system pip can refuse to install it; use a virtual
  environment.
- **Hyperlinks in python-docx need raw XML**: `part.relate_to(url, <hyperlink reltype>,
  is_external=True)` and then a `w:hyperlink` element. There is no high level API.
- **Sheet ranges with a space must be URL quoted.** `'Rule comparison'!A1` in a bare f-string raises
  `InvalidURL: URL can't contain control characters`. Use `urllib.parse.quote`.
- **Never mix %-formatting with an already quoted URL.** `"...?x=%s" % v` on a string containing
  `%20` raises `unsupported format character`. Concatenate instead.
- **It is `gridProperties.frozenRowCount`**, not `frozenRowIndex`; the second spelling returns 400.
- **Month labels get eaten as dates.** `"Oct-26"` written with `USER_ENTERED` becomes a date serial.
  Write header labels with `valueInputOption=RAW`, or spell them `"Oct 2026"`.
- **Build the formula grid from a list and track row numbers as you append.** Hardcoded row numbers
  produced two rounds of off by one bugs on a tab with blank spacer rows.
- **Look at every rendered PNG before shipping.** Clipped captions and a misplaced annotation only
  showed up by looking.
- **Check the finished text for dashes and AI shapes** before handing it over, and fix every finding:
  [[2026-09-10-convention-write-like-a-person]].

## Links

[[2026-09-22-howto-fill-google-doc-via-docs-api-batchupdate]] ·
[[2026-09-15-convention-every-artifact-also-as-html-file]] ·
[[2026-09-15-decision-file-vault-in-a-local-directory]]
