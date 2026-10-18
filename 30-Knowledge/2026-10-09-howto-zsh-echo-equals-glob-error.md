---
id: 2026-10-09-howto-zsh-echo-equals-glob-error
title: zsh fails on an unquoted word starting with an equals sign, such as echo =====
type: howto
area: [shell]
projects: []
tags: [zsh, bash, shell, echo, equals-expansion, quoting, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-09
supersedes: []
---

## Symptom

A visual separator between sections of script output, `echo =====`, prints nothing and fails:

```
zsh:1: ==== not found
```

## Cause

In zsh, an unquoted word that starts with `=` goes through *equals expansion*: `=name` is replaced by
the full path of the command `name`, as `which name` would print it (`echo =ls` prints `/bin/ls`).
`=====` is read as `=` followed by a command called `====`, there is no such command, and the whole
command line fails with "not found". The behaviour belongs to the `EQUALS` option, on by default in
zsh. bash has no such expansion and prints the five signs.

## Fix

Quote the word, or do not start it with `=`:

```zsh
echo "====="
echo '====='
printf '%s\n' "====="
echo "----------"
```

`setopt NO_EQUALS` turns the expansion off for a script, but quoting is the habit that also covers the
other zsh surprises.

## The habit

Quote every string literal in a zsh command line that carries a character zsh treats as special: a
leading `=`, backticks, glob characters (`*`, `?`, `[`), and `#` or `^` when `EXTENDED_GLOB` is on.
The sibling traps are in [[2026-09-01-howto-zsh-unquoted-var-no-word-splitting]].

## Links

- [[2026-09-01-howto-zsh-unquoted-var-no-word-splitting]]
