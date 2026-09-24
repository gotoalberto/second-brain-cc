---
id: 2026-09-23-howto-attach-a-drive-file-to-a-calendar-invitation
title: Attaching a Drive file to a Google Calendar invitation
type: howto
area: [tooling, calendar]
projects: []
tags: [google, drive, calendar, attachment, google.py, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-23
supersedes: []
---

## Context

`google.py` has no upload subcommand, so attaching a local file (a CV for an interviewer, an agenda)
to a calendar invitation takes three raw API calls with the same account's token.

Two facts decide the recipe:

- **A Calendar attachment must already be a Drive file.** An arbitrary URL or a local path cannot be
  attached.
- **Every attendee needs read permission on that Drive file**, or the attachment shows in the
  invitation and will not open. Calendar attachments do not share the file.

## Recipe

1. **Token**:
   ```sh
   TOKEN=$(python3 ~/Brain/_bin/google.py token --account <name>)
   ```
2. **Upload the file to Drive**, metadata and content in one multipart request; keep the returned
   `id`:
   ```sh
   curl -s -X POST "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&supportsAllDrives=true" \
     -H "Authorization: Bearer $TOKEN" \
     -F "metadata={\"name\":\"<filename>\"};type=application/json;charset=UTF-8" \
     -F "file=@<local path>;type=application/pdf"
   ```
3. **Share it with each attendee as reader**, with no notification mail (they get the invitation):
   ```sh
   curl -s -X POST "https://www.googleapis.com/drive/v3/files/<file id>/permissions?sendNotificationEmail=false" \
     -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"role":"reader","type":"user","emailAddress":"<attendee@example.com>"}'
   ```
4. **Create or patch the event with the attachment**: `supportsAttachments=true` on the query string
   and an `attachments` array (`fileId`, `fileUrl` as `https://drive.google.com/file/d/<file id>/view`,
   `title`, `mimeType`) in the body. Add `conferenceDataVersion=1` and a
   `conferenceData.createRequest` block (any unique `requestId`) in the same call if the event also needs a fresh Meet link,
   and `sendUpdates=all` so attendees get it:
   ```sh
   python3 ~/Brain/_bin/google.py api --account <name> --method POST --body-file event.json \
     "https://www.googleapis.com/calendar/v3/calendars/primary/events?supportsAttachments=true&sendUpdates=all"
   ```

Before creating or moving the event, check the slot for conflicts on the user's calendars and propose
alternatives if it is taken.

## Links

[[2026-09-22-howto-fill-google-doc-via-docs-api-batchupdate]]
