---
id: 2026-09-01-howto-zsh-unquoted-var-no-word-splitting
title: Shell traps in zsh and macOS scripts
type: howto
area: [shell]
projects: []
tags: [zsh, bash, macos, shell, timeout, pgrep, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## zsh does not word-split an unquoted variable

In bash, an unquoted `$VAR` holding several words expands to several arguments. In zsh it does not
(`SH_WORD_SPLIT` is off by default). A reusable flag string collapses into one argument:

```zsh
FLAGS="--account deployer --password-file /path/to/pw"
some-cli send "$TARGET" $FLAGS     # zsh passes ONE argument: the whole string
```

The command fails, or worse, misparses: `--account` receives the rest of the string glued on.

Use an array whenever a variable is meant to expand into several arguments:

```zsh
FLAGS=(--account deployer --password-file /path/to/pw)
some-cli send "$TARGET" "${FLAGS[@]}"
```

The same trap has several shapes, all with the same fix:

- **A whole command in a variable.** `CMD="python3 tool.py set ..."; $CMD` fails with "no such file
  or directory", because zsh looks for one file whose name is the whole string. Use a shell function.
- **A list of filenames in a string.** `FILES="a b c"; for f in $FILES` loops once over one path.
  Use `files=(a b c); for f in "${files[@]}"`.

Treat "build flags or a command in a variable and expand it bare" as a smell on sight. This trap
recurs even after it has been written down; the habit is to reach for an array first.

## `echo =====` aborts a chained command

In zsh, an unquoted word starting with `=` is subject to expansion. `echo =====` as a visual
separator fails with "no matches found" and stops the rest of a `&&` chain. Quote it, or use `-----`.

## macOS has no `timeout`

Scripts written against GNU coreutils' `timeout <seconds> <cmd>` fail on macOS with "command not
found". Install coreutils (which provides `gtimeout`) or use perl, which needs nothing extra:

```sh
perl -e 'alarm shift; exec @ARGV' 30 some-command --flag
```

## A wait loop built on `pgrep -f` finds itself

```sh
until ! pgrep -f "long-running-test --profile ci" >/dev/null; do sleep 15; done
```

This never ends. `pgrep -f` matches the full command line of every process, and the loop's own
command line contains the pattern. The same goes for `ps aux | grep -c <pattern>`, which counts the
grep. Wait for the effect instead: the final line appearing in an output file, a file that stops
growing, or a background job whose completion the harness reports.

## Links

- [[2026-08-30-convention-check-the-effect-not-the-exit-code]]
- [[2026-09-14-howto-python39-socket-timeout-is-not-timeouterror]]
