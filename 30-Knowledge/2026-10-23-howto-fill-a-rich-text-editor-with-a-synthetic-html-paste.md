---
id: 2026-10-23-howto-fill-a-rich-text-editor-with-a-synthetic-html-paste
title: Filling a rich text editor in the browser with a synthetic HTML paste
type: howto
area: [harness, browser]
projects: []
tags: [claude-in-chrome, browser-automation, prosemirror, rich-text, paste, file-upload, howto]
status: active
confidence: medium
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-23
supersedes: []
---

## Context

Long formatted text (headings, links, lists) is slow and fragile to type into a web editor key by key,
and many editors built on ProseMirror or similar ignore a value set straight on the DOM. They do accept
a paste, and a paste can be synthesized from the page with the HTML already formatted.

## Steps

1. Click into the editor body so it has the caret.
2. Dispatch a paste event carrying both an HTML and a plain text version:

   ```js
   const dt = new DataTransfer();
   dt.setData('text/html', html);
   dt.setData('text/plain', plain);
   document.activeElement.dispatchEvent(
     new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
   ```

3. Read the result back from the page. The editor maps the HTML onto its own schema: a heading level
   it does not support becomes the nearest one it does (an `h2` can land as an `h3`), unsupported tags
   are dropped, links are usually kept. Adjust the HTML to what the editor keeps rather than fixing it
   by hand afterwards.
4. **Images and covers go through the file input**, not the paste. Open the editor's image or cover
   control, then set the file on the `input[type=file]` it exposes (in Claude in Chrome, the
   `file_upload` tool). An inline image usually lands at the caret followed by an empty paragraph,
   so place the caret before inserting each one.
5. Publishing usually opens one more dialog (a share text, a visibility choice). Read it before
   pressing the final button.

## Notes

- Send browser steps one after another after a navigation; calls sent in parallel can hit a tab that
  has no URL yet ([[2026-09-21-reference-where-claude-in-chrome-is-available]]).
- Publishing in the user's name follows the usual rules: only when asked, and in an unattended routine
  only with the wording in [[2026-10-23-convention-routine-that-publishes-states-it-as-the-users-request]].

## Example

An invented library newsletter is written as HTML with two sections and three links, pasted into the
blog editor in one event, then the cover photo of the reading room is set through the cover control's
file input.
