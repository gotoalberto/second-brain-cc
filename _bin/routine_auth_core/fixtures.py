"""Recorded CLI outcomes the classifier is written against. Test data, no IO.

Each fixture is one (exit code, stdout, stderr) triple and the kind the classifier must
give it. `verified` says whether the triple was seen from the real standalone CLI or is a
guess. Only the 401 invalid-token shapes are verified (the standalone CLI at
`~/.local/bin/claude`, run with a deliberately invalid CLAUDE_CODE_OAUTH_TOKEN). Every other one carries
UNVERIFIED in its note: when a real failure of that kind happens, compare the redacted raw
output in <brain state>/logs/routine-auth.log with the fixture and correct the fixture and
the pattern together.

No fixture holds anything that looks like a real token.
"""

import json

UNVERIFIED = "UNVERIFIED: pattern guessed, confirm against a real failure"

FIXTURES = {
    "ok_json": {
        "verified": False,
        "note": UNVERIFIED + " (only the exit code 0 is relied on)",
        "exit_code": 0,
        "stdout": json.dumps({"type": "result", "is_error": False, "total_cost_usd": 0.0412,
                              "result": "Done."}),
        "stderr": "",
        "kind": "ok",
    },
    "ok_no_request_reply": {
        "verified": True,
        "note": ("seen 2026-09-15: example-routine-b-agent through tasks.py, exit 0 after 6 s, no tool used, "
                 "when the routine body was handed over unframed. Only the result text is verified; the json "
                 "around it is reconstructed. The CLI succeeded, so this is ok to the classifier: the routine's "
                 "success contract is what catches it"),
        "exit_code": 0,
        "stdout": json.dumps({"type": "result", "is_error": False,
                              "result": "I don't see an actual request in your message, just session context and "
                                        "reminders. What would you like me to help with?"}),
        "stderr": "",
        "kind": "ok",
    },
    "auth_invalid_text": {
        "verified": True,
        "note": "seen 2026-09-15: --output-format text, invalid CLAUDE_CODE_OAUTH_TOKEN, exit 1",
        "exit_code": 1,
        "stdout": "Failed to authenticate. API Error: 401 OAuth access token is invalid.\n",
        "stderr": "",
        "kind": "auth_invalid",
    },
    "auth_invalid_json": {
        "verified": True,
        "note": "seen 2026-09-15: --output-format json, exit 1; only these two keys are verified",
        "exit_code": 1,
        "stdout": json.dumps({"terminal_reason": "api_error", "total_cost_usd": 0}),
        "stderr": "",
        "kind": "auth_invalid",
    },
    "usage_limit_text": {
        "verified": False,
        "note": UNVERIFIED,
        "exit_code": 1,
        "stdout": "Claude AI usage limit reached. Try again in 3 hours.\n",
        "stderr": "",
        "kind": "usage_limit",
        "retry_after": 3 * 3600,
    },
    "usage_limit_epoch": {
        "verified": False,
        "note": UNVERIFIED,
        "exit_code": 1,
        "stdout": "Claude AI usage limit reached|1789999200\n",
        "stderr": "",
        "kind": "usage_limit",
        "resets_at": 1789999200,
    },
    "usage_limit_json_429": {
        "verified": False,
        "note": UNVERIFIED,
        "exit_code": 1,
        "stdout": json.dumps({"terminal_reason": "api_error", "total_cost_usd": 0,
                              "result": "API Error: 429 rate_limit_error"}),
        "stderr": "",
        "kind": "usage_limit",
    },
    "credit_exhausted_text": {
        "verified": False,
        "note": UNVERIFIED,
        "exit_code": 1,
        "stdout": "API Error: 400 Your credit balance is too low to access the Anthropic API.\n",
        "stderr": "",
        "kind": "credit_exhausted",
    },
    "network_text": {
        "verified": False,
        "note": UNVERIFIED,
        "exit_code": 1,
        "stdout": "",
        "stderr": "API Error: Connection error. (ECONNREFUSED)\n",
        "kind": "network",
    },
    "network_json": {
        "verified": False,
        "note": UNVERIFIED + " (an api_error with cost 0 that is not a 401 must never mark a token dead)",
        "exit_code": 1,
        "stdout": json.dumps({"terminal_reason": "api_error", "total_cost_usd": 0,
                              "result": "API Error: Connection error."}),
        "stderr": "",
        "kind": "network",
    },
    "overloaded_json": {
        "verified": False,
        "note": UNVERIFIED + " (a 5xx is not the token's fault: unknown, no failover)",
        "exit_code": 1,
        "stdout": json.dumps({"terminal_reason": "api_error", "total_cost_usd": 0,
                              "result": "API Error: 529 overloaded_error"}),
        "stderr": "",
        "kind": "unknown",
    },
    "timeout": {
        "verified": True,
        "note": "produced by guardian_core.adapters.CliAgentRunner itself on a timeout",
        "exit_code": 124,
        "stdout": "",
        "stderr": "agent timed out after 1800s",
        "kind": "timeout",
    },
    "cli_missing": {
        "verified": True,
        "note": "produced by guardian_core.adapters.CliAgentRunner itself",
        "exit_code": 127,
        "stdout": "",
        "stderr": "agent command not found: /nonexistent/claude",
        "kind": "cli_missing",
    },
    "unknown": {
        "verified": False,
        "note": "anything that matches nothing: alert, no failover, raw output logged",
        "exit_code": 1,
        "stdout": "Error: something nobody has seen before\n",
        "stderr": "",
        "kind": "unknown",
    },
}
