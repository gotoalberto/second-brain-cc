---
id: routine-preamble-browser-restart
title: "Routine preamble: BROWSER probe and restart"
type: routine-preamble
provenance: "The probe and restart rule shared by every routine that drives this machine's Chrome; it used to be pasted, in several variants, into each of them."
---
<!-- Put in front of the prompt by _bin/tasks.py for routines that allow Claude in Chrome (the
     default) or list `browser_restart` in `preamble:`. Edit the rule here, never in a routine.
     What a routine does when the browser stays down stays in the routine. -->
BROWSER (this machine's Chrome): it comes through the CLI login and `--chrome`. Probe it first
(`tabs_context_mcp`, and `list_connected_browsers` if needed; when several are connected, select
this machine's own Chrome as the session banner names it). If it does not answer, restart it with
`python3 ~/Brain/_bin/chrome_restart.py restart`, never `pkill`: it restarts only the desktop
Chrome (headless renders of other tasks keep running), waits for the keepalive to relaunch it and
says so, and refuses with exit 75 when another run or a session holds the Chrome lock (tasks.py
holds it for this routine). Then probe again, up to two restarts. A refusal is not a restart: do
not retry it. When this run has no browser tools at all, do not restart anything. Browser still
down, or no browser tools: do what this routine says for a missing browser; when it says nothing,
publish and send nothing through the browser, log it and end with `ROUTINE_FAILED: no browser`.
