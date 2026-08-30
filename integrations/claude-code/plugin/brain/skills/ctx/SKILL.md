---
name: ctx
description: Gathers the context a task needs into a Context Pack before any work starts. Use it when you are about to tackle something non-trivial and want the context distilled without burning your window searching for it.
argument-hint: [task description]
---

Run `context-scout` for the task «$ARGUMENTS».

1. Invoke the `context-scout` subagent with the task description, the current working
   directory and the repository if there is one. Wait for its result (not in background).
2. The scout returns `PACK: <path>` plus a summary. **Read the pack with `Read`.**
3. Mark the session as context-provided:
   ```
   /usr/bin/python3 ~/Brain/_bin/mark_pack.py <pack-path>
   ```
4. Summarise for the user in five lines: what the vault already knows, which earlier
   decisions constrain the task, and which gaps the scout declared.
5. Do not start implementing. This only prepares the ground; to execute, use `/task`.
