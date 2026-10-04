---
name: twitterapi-io
description: Reads real, current X/Twitter content (an account's recent tweets, a keyword or topic search, an X list's timeline, or specific tweets by id) through twitterapi.io, a paid third-party API that needs no X developer account and no OAuth. Use it whenever a skill, routine or one-off task needs X/Twitter content. Always through its script, with the API key read from KeePass, never raw curl with the key inlined.
argument-hint: [what X/Twitter content you need]
allowed-tools: Bash(python3 ~/.claude/skills/twitterapi-io/scripts/twitterapi_io.py:*), Bash(/usr/bin/python3 ~/.claude/skills/twitterapi-io/scripts/twitterapi_io.py:*), Read
---

# twitterapi.io

A paid third-party API (docs: https://docs.twitterapi.io/) for reading X/Twitter content without
official X API access and without OAuth. This skill is the controlled path to X/Twitter content:
never a logged-in browser session, never raw curl with the key inlined.

It is a plain HTTP API behind a script, so it runs headless and from a scheduled routine without
changes: allowing the script's command in the routine's tool allowlist is enough.

## How to call it

Always through the script, never any other path to the credential:

```
python3 ~/.claude/skills/twitterapi-io/scripts/twitterapi_io.py <subcommand> [args...]
```

`--help`, and `<subcommand> --help`, list every parameter. It prints the raw JSON response on
stdout: pipe it to `python3 -m json.tool`, `jq`, or a short Python snippet to pull out what you need.

| Subcommand | What it returns | Where the tweets are |
|---|---|---|
| `user-tweets --username NAME` (or `--user-id ID`) | an account's recent tweets | nested under `data.tweets` |
| `list-timeline LIST_ID` | an X list's recent tweets, with `has_next_page` and `next_cursor` | top-level `tweets` |
| `search "QUERY" --type Latest\|Top` | advanced search: keywords, `from:account`, `since_time:<unix>`, `until_time:<unix>`, `OR` and quoted phrases | top-level `tweets` |
| `user-info NAME` | one account's profile | |
| `tweets-by-ids ID,ID` | specific tweets by id | |

`user-tweets` wraps its answer in a `data` object and the others do not: check which shape you got
before parsing. Every subcommand that pages takes `--cursor` with the previous page's `next_cursor`.

An example search: `search '("heat pump" OR "solar panel") (install OR price) since_time:1700000000'`.

## Cost

Credit based and charged on every call: on the order of fifteen cents per thousand tweets read,
profiles slightly more, with a small minimum per request (current prices on the provider's site).
Keep pulls small and targeted: one page unless there is a specific reason to go further, and never
loop through pages just in case. The rate limit is generous and not a practical concern.

## Credential

The API key lives in the user's KeePass database at `kp://apis/twitterapi-io` (the password field).
The user creates that entry in KeePassXC inside the agent group (see the `kp` skill). The script reads
it once per run with `kp.py get apis/twitterapi-io --pipe cat`, sends it only as the `x-api-key`
header, and never prints it. Never hardcode it, never put it in a note, never pass it as a command
argument yourself. If the script says it could not read the key, run `kp.py news` and `kp.py ls -R`
to see whether the entry exists under that name.

The script finds `kp.py` in the vault (`BRAIN_VAULT`, or the path the installer wrote into it);
`BRAIN_KP_SCRIPT` overrides that path.
