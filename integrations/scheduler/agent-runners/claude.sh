#!/bin/bash
# Reads the task prompt on stdin and runs it through Claude Code, headless.
# Claude Code uses your existing CLI auth; no API key needed here.
prompt="$(cat)"
exec claude -p "$prompt"
