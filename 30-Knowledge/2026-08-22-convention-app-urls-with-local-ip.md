---
id: 2026-08-22-convention-app-urls-with-local-ip
title: App URLs for the user use the machine's LAN address
type: convention
area: [communication, development]
projects: []
tags: [urls, dev-server, lan, localhost, preview, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The rule

When an app, dev server or preview is started, the URL handed to the user uses the machine's LAN
address, `http://<lan-ip>:<port>`, never `localhost` or `127.0.0.1`. The user often opens it from a
phone, another machine or an emulator, where `localhost` means something else. The localhost variant may
be mentioned as secondary.

## Get the address on the spot

It is usually a DHCP address and changes between networks, so never hardcode it:

```sh
ipconfig getifaddr en0                                   # macOS, Wi-Fi
ipconfig getifaddr "$(route -n get default | awk '/interface:/{print $2}')"   # macOS, default route
hostname -I | awk '{print $1}'                           # Linux
```

With several interfaces on the same LAN, either works as long as the server listens on all of them.

## The server must listen on all interfaces

A server bound to loopback cannot be reached from another device however correct the URL is. Bind
`0.0.0.0` before handing over the address:

- Vite: `vite --host`
- Next.js: `next dev -H 0.0.0.0`
- webpack-dev-server: `HOST=0.0.0.0`
- Python: `python -m http.server --bind 0.0.0.0`, Flask `--host=0.0.0.0`

## Verifying inside the agent's own browser

The rule is about the URL given to the user. The agent's embedded browser may treat private-network
addresses as needing approval per origin, and some frameworks block dev resources requested from a
non-local origin unless it is allowlisted. For the agent's own verification, open
`http://localhost:<port>` on the same server; hand the user the LAN address.

An app that redirects every unknown hostname to production cannot be opened by LAN address at all; for
that app, say so and give `localhost`.

## Links

- [[2026-08-28-convention-clickable-links-and-send-files]]
- [[2026-08-26-convention-code-development-pipeline]]
