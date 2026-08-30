#!/bin/bash
# Reads the task prompt on stdin and runs it through OpenCode, non-interactive.
# Model is chosen by OpenCode config or OPENCODE_MODEL (provider/model), e.g. anthropic/claude-...
prompt="$(cat)"
if [ -n "${OPENCODE_MODEL:-}" ]; then
  exec opencode run --model "$OPENCODE_MODEL" "$prompt"
fi
exec opencode run "$prompt"
