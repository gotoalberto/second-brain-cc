---
id: 2026-09-14-howto-python39-socket-timeout-is-not-timeouterror
title: Socket timeouts on Python 3.9 are not TimeoutError
type: howto
area: [python]
projects: []
tags: [python, python39, macos, socket, timeout, urllib, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## Content

On macOS, `/usr/bin/python3` (the Command Line Tools copy) can be Python 3.9, and this repo's
scripts and hooks run on it. In Python 3.9, `socket.timeout` is a plain `OSError` subclass,
unrelated to the builtin `TimeoutError`; the two were unified only in Python 3.10.

A retry loop around `urllib` or `http.client` calls that catches only `TimeoutError` therefore lets a
real read timeout escape uncaught on 3.9, while working fine on a newer interpreter.

## Fix

Catch `OSError`, or explicitly `(socket.timeout, TimeoutError)`, for network read and connect
timeouts. `OSError` covers both cases on every version, since `TimeoutError` is itself an `OSError`
subclass. Test such code on both the oldest and the newest interpreter the repo supports.

## Links

- [[2026-09-01-howto-zsh-unquoted-var-no-word-splitting]]
