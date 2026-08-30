#!/bin/bash
# Reads the task prompt on stdin and runs it through Simon Willison's `llm` CLI (any model).
# NOTE: plain `llm` is a bare model call with NO tools — good for pure-generation tasks
# (summaries, drafts). Tasks that must READ/WRITE the vault need an agent that can run the
# `brain` CLI or MCP tools (use claude.sh or opencode.sh for those).
# Set LLM_MODEL to choose the model (see `llm models`).
if [ -n "${LLM_MODEL:-}" ]; then
  exec llm -m "$LLM_MODEL"
fi
exec llm
