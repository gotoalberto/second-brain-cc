---
name: vpn-proxy
description: Gives a machine a VPN exit when a site blocks or restricts its IP, in two ways. For command line tools, vpn.py starts a userspace WireGuard tunnel (wireproxy, no root, the machine's network untouched) with a local SOCKS5 proxy per configured exit, keys read from KeePass. For the browser, it switches the VPN provider's browser extension on and off. Use it whenever a download or request fails because of the machine's IP (a bot check, a Cloudflare block page, a 403 by region, a rate limit), when a site fails in the browser for the same reason, before a skill that says it needs a VPN exit, and when the user asks for a VPN or for an exit in another country. Tested with a commercial provider's WireGuard configs; any WireGuard provider works.
argument-hint: "[up <exit> | down | status | browser on|off]"
allowed-tools: Bash(python3 ~/.claude/skills/vpn-proxy/scripts/vpn.py:*), Bash(/usr/bin/python3 ~/.claude/skills/vpn-proxy/scripts/vpn.py:*), Read
---

# VPN exits (WireGuard)

## Configuration

| What | Where | Default |
|---|---|---|
| The exits | `VPN_PROXY_EXITS`, comma separated, `name` or `name=port` (for example `nl,se=1090`). A name without a port gets 1080 plus its position in the list | none: nothing runs until it is set |
| One WireGuard config per exit | KeePass, `kp://infra/vpn-wg-<name>`: the entry's **password** is the WireGuard private key, its **notes** hold the rest of the config with `{{PRIVATE_KEY}}` where the key goes | |
| The entry prefix | `VPN_PROXY_KP_PREFIX` | `infra/vpn-wg-` |
| Where `kp.py` is | `BRAIN_KP_SCRIPT` | `__VAULT__/_bin/kp.py` |

Set the variables in the `env` block of Claude Code's `settings.json` so every session sees them.
Name the exits after what they are for the user (a country code is the usual choice) and check, the
first time each one comes up, which country the exit is actually seen from: a provider can host a
server named after one country in another.

**Adding an exit.** The user downloads a WireGuard config from their VPN provider and files it in
KeePassXC themselves, the normal `kp` path: a new entry `infra/vpn-wg-<name>` in the agent group, the
`PrivateKey` value as the password, the whole config as the notes with that value replaced by
`{{PRIVATE_KEY}}`. Then the name goes into `VPN_PROXY_EXITS`, and the downloaded file is deleted. The
key never passes through the conversation.

## A. Command line tools

```
python3 ~/.claude/skills/vpn-proxy/scripts/vpn.py list          # exits, ports, KeePass references
python3 ~/.claude/skills/vpn-proxy/scripts/vpn.py up <exit>     # prints socks5://127.0.0.1:<port> and the public IP
python3 ~/.claude/skills/vpn-proxy/scripts/vpn.py status
python3 ~/.claude/skills/vpn-proxy/scripts/vpn.py down          # all exits
```

- The first `up` on a machine installs wireproxy (a pinned release of `windtf/wireproxy`, sha256
  checked against the release checksums) into `~/.local/share/vpn-proxy/`, for Linux or macOS, Intel
  or ARM. State and logs live in `~/.local/state/vpn-proxy/`.
- The key never stays on disk and is never printed: `vpn.py` reads it from `kp.py` through a pipe,
  writes the config with mode 600, starts wireproxy and deletes the file about a second later.
- Only what is pointed at the proxy goes through the VPN: SSH, remote sessions, Claude itself and the
  rest of the machine keep their own IP. Several exits can run at once.
- Point tools at it: `curl --socks5-hostname 127.0.0.1:<port>`, `yt-dlp --proxy socks5://127.0.0.1:<port>`,
  Python `proxies={"https": "socks5h://127.0.0.1:<port>"}`, or `ALL_PROXY=socks5h://127.0.0.1:<port>`
  for tools that read it. Prefer `socks5h` (or `--socks5-hostname`) so DNS goes through the exit too.
- Bring the exit down when the job is done.

## B. The browser (the provider's extension)

When the provider has a browser extension and it is installed and signed in in the user's Chrome, that
is how the browser gets an exit. **It stays off by default**: most sites work better without it.
Switch it on:

- before using a skill that says it needs one (for example `grok-browser` from a network grok.com
  blocks);
- whenever a site fails in the browser because of the IP (a block page, a captcha wall, "not
  available in your country", endless loading on one site);

and switch it off again when that job is over.

An extension's popup lives outside the page, so Claude in Chrome cannot open it:

- **On a desktop the user is sitting at**, ask the user to switch it and say which exit.
- **On a Linux machine with an X desktop and nobody at it**, it takes real clicks on the desktop with
  `xdotool`. Take a desktop screenshot first (`ffmpeg -f x11grab -video_size <WxH> -i $DISPLAY
  -frames:v 1 <scratch>/desk.png`), crop the top right and find the extension's icon in the toolbar
  before clicking: toolbars change, and the icon next to it may belong to another extension that
  opens something else. Click it, pick the exit in the popup, wait a few seconds and take another
  screenshot to confirm it says connected (or disconnected when switching off), then close the popup
  with `xdotool key Escape`. Never reuse coordinates without looking at a fresh screenshot.

Never sign in, sign out, or change the provider account or the extension's settings.
