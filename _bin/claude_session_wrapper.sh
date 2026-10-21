#!/bin/sh
# Launcher Claude Code puts in front of its own self-spawns when CLAUDE_CODE_PROCESS_WRAPPER names it.
# remote_control.py sets that variable for the Remote Control server only, never for your own shell.
# Claude calls it as
#   claude_session_wrapper.sh <path of the running claude binary> <args...>
# A Remote Control session (its arguments carry --sdk-url) gets --allow-dangerously-skip-permissions,
# so bypassPermissions stays in the app's mode picker after the app switches the session to another
# mode; `claude remote-control` has no flag of its own to forward it. Every other self-spawn passes
# through untouched. It must exec: Claude requires that of a process wrapper.
bin="$1"; shift
case " $* " in
  *" --sdk-url "*)
    case " $* " in
      *" --allow-dangerously-skip-permissions "*|*" --dangerously-skip-permissions "*) ;;
      *) exec "$bin" --allow-dangerously-skip-permissions "$@" ;;
    esac ;;
esac
exec "$bin" "$@"
