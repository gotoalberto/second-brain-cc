---
name: daily-digest
schedule: "0 8 * * *"
enabled: false
timeout: 600
---
Produce a short daily digest of the vault and save it as a note.

1. Find what changed in the last 24 hours: `brain recent 20`.
2. Skim the most relevant notes and write a 5–10 bullet summary of what moved,
   what decisions were made, and anything that needs follow-up.
3. Save it with:
   `brain new 00-Inbox/$(date +%F)-daily-digest.md --title "Daily digest $(date +%F)" --type note --tag digest`
   (put the bullets in the body, piped on stdin).

Keep it factual and short. If nothing changed, save a one-line note saying so.
