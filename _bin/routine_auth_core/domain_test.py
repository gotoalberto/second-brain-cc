#!/usr/bin/env python3
# brain:allow-secrets (synthetic token-shaped values only, never a real credential)
"""Tests for routine_auth_core.domain: the pure rules of routine authentication.

Nothing here touches the disk, a subprocess, KeePass or the clock: every input is a
literal or a recorded fixture, and every "now" is passed in. Run standalone:

    python3 _bin/routine_auth_core/domain_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[0] = os.path.dirname(HERE)          # _bin, so `routine_auth_core` imports as a package

ok, fail = [], []

FAKE_TOKEN = "sk-ant-oat01-" + "A1b2_C3d4-" * 9       # the right shape, not a real token


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def test_classify(D):
    from routine_auth_core.fixtures import FIXTURES, UNVERIFIED

    print("\n== classify, against the recorded fixtures ==")
    for name, fx in sorted(FIXTURES.items()):
        got = D.classify(fx["exit_code"], fx["stdout"], fx["stderr"])
        check("%s is %s" % (name, fx["kind"]), got.kind == fx["kind"], got)
        if "retry_after" in fx:
            check("%s carries retry_after %s" % (name, fx["retry_after"]), got.retry_after == fx["retry_after"], got)
        if "resets_at" in fx:
            check("%s carries resets_at %s" % (name, fx["resets_at"]), got.resets_at == fx["resets_at"], got)
        check("%s is marked verified or UNVERIFIED" % name,
              fx["verified"] or UNVERIFIED in fx["note"] or "nothing" in fx["note"], fx["note"])

    verified = [n for n, fx in FIXTURES.items() if fx["verified"] and fx["kind"] == D.AUTH_INVALID]
    check("the 401 shapes are the verified ones, in text and json form",
          sorted(verified) == ["auth_invalid_json", "auth_invalid_text"], verified)
    check("a classification says whether its pattern is verified",
          D.classify(1, FIXTURES["auth_invalid_text"]["stdout"], "").verified is True
          and D.classify(1, FIXTURES["usage_limit_text"]["stdout"], "").verified is False)
    check("exit 0 is ok whatever the text says", D.classify(0, "usage limit reached", "").kind == D.OK)
    check("exit 126 is a CLI problem, not a token problem", D.classify(126, "", "not executable").kind == D.CLI_MISSING)
    check("an empty failure is unknown", D.classify(1, "", "").kind == D.UNKNOWN)
    check("json on the last line of stdout is read",
          D.classify(1, 'noise\n{"terminal_reason": "api_error", "total_cost_usd": 0}\n', "").kind == D.AUTH_INVALID)
    check("an api_error that cost money is not a 401",
          D.classify(1, '{"terminal_reason": "api_error", "total_cost_usd": 0.3}', "").kind == D.UNKNOWN)
    check("stdout that is not json is still classified by its text",
          D.classify(1, "{not json", "Failed to authenticate. API Error: 401 x").kind == D.AUTH_INVALID)
    got = D.classify(1, "Failed to authenticate. API Error: 401 %s" % FAKE_TOKEN, "")
    check("a detail never carries a token-looking value", FAKE_TOKEN not in got.detail and "sk-ant" not in got.detail,
          got.detail)


def test_token_shape(D):
    print("\n== token shape ==")
    good, shape = D.token_shape(FAKE_TOKEN)
    check("one sk-ant-oat01- token is well formed", good, shape)
    cases = {
        "empty": "",
        "none": None,
        "trailing space": FAKE_TOKEN + " ",
        "a newline inside": FAKE_TOKEN[:30] + "\n" + FAKE_TOKEN[30:],
        "two words": "token: " + FAKE_TOKEN,
        "wrong prefix": "sk-ant-" "api03-" + "x" * 40,
        "prefix only": "sk-ant-oat01-",
        "odd characters": "sk-ant-oat01-abc$def",
    }
    for name, value in cases.items():
        good, shape = D.token_shape(value)
        check("%s is malformed" % name, not good, shape)
        check("%s: the shape text carries no part of the value" % name,
              not value or all(part not in shape for part in (value.strip()[13:] or "@@", "api03", "abc$def")),
              shape)
    check("a malformed value names what is wrong with it",
          "whitespace" in D.token_shape("a b")[1] and "sk-ant-oat01-" in D.token_shape("x" * 20)[1],
          (D.token_shape("a b"), D.token_shape("x" * 20)))


def test_redact(D):
    print("\n== redact ==")
    text = "header Authorization: Bearer abc.def.ghi\nvalue %s end\n" % FAKE_TOKEN
    out = D.redact(text)
    check("token-looking values are removed", FAKE_TOKEN not in out and "sk-ant-oat01-A1b2" not in out, out)
    check("bearer credentials are removed", "abc.def.ghi" not in out, out)
    check("the rest of the text stays readable", "header" in out and "end" in out, out)
    secret = "plainsecretvalue42"
    check("an explicitly given secret is removed wherever it appears",
          secret not in D.redact("x %s y %s" % (secret, secret), secrets=[secret]))
    long = "line\n" * 5000
    cut = D.redact(long, limit=1000)
    check("long output is cut to the limit, keeping the end", len(cut) < 1100 and cut.endswith("line\n"), len(cut))
    check("None redacts to an empty string", D.redact(None) == "")


def test_failover(D):
    import datetime as dt

    print("\n== pool state and failover ==")
    now = dt.datetime(2026, 9, 15, 13, 0, 0)
    later = (now + dt.timedelta(hours=2)).isoformat(timespec="seconds")
    earlier = (now - dt.timedelta(minutes=1)).isoformat(timespec="seconds")
    labels = ["a", "b", "c"]

    check("an empty state tries the pool in its order", D.attempt_order(labels, {}, now) == ["a", "b", "c"])
    check("a dead token goes last, kept as a last resort (a re-stored token heals itself)",
          D.attempt_order(labels, {"b": {"status": D.DEAD}}, now) == ["a", "c", "b"])
    check("a token limited until later is not tried",
          D.attempt_order(labels, {"a": {"status": D.LIMITED, "until": later}}, now) == ["b", "c"])
    check("a token whose limit has passed is healthy again",
          D.attempt_order(labels, {"a": {"status": D.LIMITED, "until": earlier}}, now) == ["a", "b", "c"]
          and D.token_status({"a": {"status": D.LIMITED, "until": earlier}}, "a", now) == D.HEALTHY)
    check("state for a label no longer in the pool is ignored",
          D.attempt_order(["a"], {"zz": {"status": D.HEALTHY}}, now) == ["a"])

    C = D.Classification
    before = {"a": {"status": D.DEAD, "until": None, "last_kind": D.AUTH_INVALID, "last_at": earlier}}
    snapshot = repr(before)
    after = D.record(before, "a", C(D.OK), now)
    check("a successful run makes a token healthy", after["a"]["status"] == D.HEALTHY and after["a"]["until"] is None,
          after)
    check("record never mutates its input", repr(before) == snapshot)
    check("record stamps the kind and the time", after["a"]["last_kind"] == D.OK
          and after["a"]["last_at"] == now.isoformat(timespec="seconds"), after)

    table = [
        (C(D.AUTH_INVALID, "401"), D.DEAD, None),
        (C(D.TOKEN_MALFORMED, "empty"), D.DEAD, None),
        (C(D.USAGE_LIMIT, retry_after=600), D.LIMITED, now + dt.timedelta(seconds=600)),
        (C(D.USAGE_LIMIT), D.LIMITED, now + dt.timedelta(seconds=D.DEFAULT_BACKOFF_S[D.USAGE_LIMIT])),
        (C(D.CREDIT_EXHAUSTED), D.LIMITED, now + dt.timedelta(seconds=D.DEFAULT_BACKOFF_S[D.CREDIT_EXHAUSTED])),
    ]
    for cls, status, until in table:
        got = D.record({}, "a", cls, now)["a"]
        check("%s marks the token %s" % (cls.kind, status),
              got["status"] == status
              and got["until"] == (until.isoformat(timespec="seconds") if until else None), got)
    got = D.record({}, "a", C(D.USAGE_LIMIT, resets_at=1789999200), now)["a"]
    check("a reset time in the output is the limit's end",
          got["until"] == dt.datetime.fromtimestamp(1789999200).isoformat(timespec="seconds"), got)
    got = D.record({}, "a", C(D.CREDIT_EXHAUSTED), now, backoff={D.CREDIT_EXHAUSTED: 60})["a"]
    check("the backoff is configurable", got["until"] == (now + dt.timedelta(seconds=60)).isoformat(timespec="seconds"),
          got)
    for kind in (D.NETWORK, D.TIMEOUT, D.UNKNOWN, D.CLI_MISSING, D.KEEPASS_LOCKED, D.KEEPASS_UNAVAILABLE):
        got = D.record({"a": {"status": D.DEAD}}, "a", C(kind), now)["a"]
        healthy = D.record({}, "a", C(kind), now)["a"]
        check("%s says nothing about the token: its status is unchanged" % kind,
              got["status"] == D.DEAD and healthy["status"] == D.HEALTHY and got["last_kind"] == kind, (got, healthy))

    print("\n== next_token ==")
    for kind in (D.AUTH_INVALID, D.TOKEN_MALFORMED, D.USAGE_LIMIT, D.CREDIT_EXHAUSTED):
        state = D.record({}, "a", C(kind), now)
        check("%s fails over to the next token" % kind, D.next_token(labels, state, "a", kind, now, ["a"]) == "b")
    check("network retries the same token", D.next_token(labels, {}, "a", D.NETWORK, now, ["a"]) == "a")
    for kind in (D.OK, D.CLI_MISSING, D.KEEPASS_LOCKED, D.KEEPASS_UNAVAILABLE, D.UNKNOWN, D.TIMEOUT, D.CONFIG):
        check("%s never fails over" % kind, D.next_token(labels, {}, "a", kind, now, ["a"]) is None)
    state = D.record({}, "b", C(D.AUTH_INVALID), now)
    check("a token already tried in this run is skipped",
          D.next_token(labels, state, "b", D.AUTH_INVALID, now, ["a", "b"]) == "c")
    check("nothing left to try is None",
          D.next_token(labels, state, "c", D.AUTH_INVALID, now, ["a", "b", "c"]) is None)
    state = {"b": {"status": D.LIMITED, "until": later}}
    state = D.record(state, "a", C(D.AUTH_INVALID), now)
    check("a limited token is skipped by failover", D.next_token(labels, state, "a", D.AUTH_INVALID, now, ["a"]) == "c")
    state = D.record({"b": {"status": D.DEAD}}, "a", C(D.AUTH_INVALID), now)
    check("a dead token is still tried when nothing healthy is left",
          D.next_token(["a", "b"], state, "a", D.AUTH_INVALID, now, ["a"]) == "b")


def test_pool_and_expiry(D):
    import datetime as dt
    import json

    print("\n== the pool config ==")
    raw = {"_about": "references only", "tokens": [
        {"label": "routines-1", "account": "routines", "kp_ref": "kp://Brain/apis/claude-code-oauth-routines-1",
         "issued": "2026-09-15", "notes": "first"},
        {"label": "routines-2", "kp_ref": "kp://Brain/apis/claude-code-oauth-routines-2#password",
         "issued": "2026-09-20"}]}
    pool = D.parse_pool(json.dumps(raw))
    check("the pool keeps its order", [e.label for e in pool] == ["routines-1", "routines-2"], pool)
    check("an entry carries its reference, account, issue date and notes",
          pool[0].kp_ref == "kp://Brain/apis/claude-code-oauth-routines-1" and pool[0].account == "routines"
          and pool[0].issued == dt.date(2026, 9, 15) and pool[0].notes == "first", pool[0])
    check("a bare list is a pool too", [e.label for e in D.parse_pool(json.dumps(raw["tokens"]))] == ["routines-1", "routines-2"])

    def error(text):
        try:
            D.parse_pool(text)
        except D.PoolConfigError as exc:
            return str(exc)
        return None

    secretish = "sk-ant-oat01-" + "Zz9" * 20
    bad = {
        "not json": "{",
        "not a list": json.dumps({"tokens": "x"}),
        "empty": json.dumps({"tokens": []}),
        "missing kp_ref": json.dumps([{"label": "a", "issued": "2026-09-15"}]),
        "kp_ref not a kp:// reference": json.dumps([{"label": "a", "kp_ref": "apis/x", "issued": "2026-09-15"}]),
        "bad date": json.dumps([{"label": "a", "kp_ref": "kp://Brain/x", "issued": "15/09/2026"}]),
        "missing label": json.dumps([{"kp_ref": "kp://Brain/x", "issued": "2026-09-15"}]),
        "duplicate label": json.dumps([{"label": "a", "kp_ref": "kp://Brain/x", "issued": "2026-09-15"},
                                       {"label": "a", "kp_ref": "kp://Brain/y", "issued": "2026-09-15"}]),
        "an unknown key": json.dumps([{"label": "a", "kp_ref": "kp://Brain/x", "issued": "2026-09-15",
                                       "token": "hunter2-value"}]),
        "a token value": json.dumps([{"label": "a", "kp_ref": "kp://Brain/x", "issued": "2026-09-15",
                                      "notes": secretish}]),
    }
    for name, text in bad.items():
        msg = error(text)
        check("%s is a PoolConfigError" % name, msg is not None, msg)
        check("%s: the error quotes no value" % name,
              msg is None or ("hunter2" not in msg and "Zz9Zz9" not in msg), msg)
    check("the unknown key is named", "token" in (error(bad["an unknown key"]) or ""), error(bad["an unknown key"]))

    print("\n== KeePass references and renewal commands ==")
    check("the kp.py entry drops kp://, the Claude group and the attribute",
          D.kp_entry("kp://Brain/apis/claude-code-oauth-routines-1#password") == "apis/claude-code-oauth-routines-1"
          and D.kp_entry("kp://Brain/apis/claude-code-oauth-routines-1") == "apis/claude-code-oauth-routines-1")
    check("an entry outside the Claude group keeps its path", D.kp_entry("kp://Other/x") == "Other/x")
    check("the attribute defaults to password",
          D.kp_attr("kp://Brain/x") == "password" and D.kp_attr("kp://Brain/x#UserName") == "UserName")
    check("the re-store command is exact",
          D.restore_command("kp://Brain/apis/claude-code-oauth-routines-1")
          == "pbpaste | tr -d '[:space:]' | python3 ~/Brain/_bin/kp.py set \"apis/claude-code-oauth-routines-1\" --stdin",
          D.restore_command("kp://Brain/apis/claude-code-oauth-routines-1"))
    check("the renewal starts with claude setup-token and ends with the re-store",
          D.renew_command("kp://Brain/apis/x").startswith("claude setup-token")
          and D.renew_command("kp://Brain/apis/x").endswith(D.restore_command("kp://Brain/apis/x")))

    print("\n== expiry ==")
    entry = D.PoolEntry("routines-1", "kp://Brain/apis/x", dt.date(2026, 9, 15))
    check("a token expires 365 days after it was issued", D.expires_on(entry.issued) == dt.date(2027, 9, 15))
    check("a fresh token has no notice", D.expiry_findings([entry], dt.datetime(2026, 9, 15, 13, 0)) == [])
    notices = D.expiry_findings([entry], dt.datetime(2027, 8, 16, 9, 0))
    check("30 days before expiry is a notice", len(notices) == 1 and notices[0].days_left == 30
          and not notices[0].expired and notices[0].label == "routines-1", notices)
    check("31 days before is not", D.expiry_findings([entry], dt.datetime(2027, 8, 15, 9, 0)) == [])
    notices = D.expiry_findings([entry], dt.datetime(2027, 9, 16, 9, 0))
    check("the day after expiry is expired", len(notices) == 1 and notices[0].expired and notices[0].days_left == -1,
          notices)
    check("warn_days is configurable", len(D.expiry_findings([entry], dt.datetime(2027, 6, 1), warn_days=120)) == 1)

    print("\n== the vault's own 90-Meta/routine-tokens.json ==")
    path = os.path.join(os.path.dirname(os.path.dirname(HERE)), "90-Meta", "routine-tokens.json")
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    ignore = os.path.join(os.path.dirname(os.path.dirname(HERE)), ".gitignore")
    ignored = open(ignore, encoding="utf-8").read().splitlines() if os.path.exists(ignore) else []
    check("the token pool is machine-local: git ignores 90-Meta/routine-tokens.json",
          "90-Meta/routine-tokens.json" in ignored, ignored)
    if text:
        pool = D.parse_pool(text)
        check("a pool this machine keeps parses", len(pool) >= 1, pool)
        check("it holds references only", "sk-ant-" not in text)


def test_cli_rules(D):
    print("\n== the CLI template and path ==")
    check("~ expands to the home directory in every token",
          D.expand_home(["~/.local/bin/claude", "-p", "~", "--add-dir", "~/git/x"], "/h")
          == ["/h/.local/bin/claude", "-p", "/h", "--add-dir", "/h/git/x"])
    check("~user and a tilde inside a word are left alone",
          D.expand_home(["~other/x", "a~b"], "/h") == ["~other/x", "a~b"])
    check("the template splits like a shell and expands ~",
          D.template_tokens("~/.local/bin/claude -p {prompt} --output-format json", "/h")
          == ["/h/.local/bin/claude", "-p", "{prompt}", "--output-format", "json"])
    check("a template with broken quoting is no command", D.template_tokens('claude -p "{prompt}', "/h") == [])

    home = "/home/someone"
    check("the standalone install is fine",
          D.cli_path_problem(home + "/.local/bin/claude", home + "/.local/share/claude/versions/2.1.272", home) is None)
    for resolved, real in (
            ("/Applications/Claude.app/Contents/Resources/claude", "/Applications/Claude.app/Contents/Resources/claude"),
            (home + "/bin/claude", "/Applications/Claude.app/Contents/Helpers/claude"),
            (home + "/bin/claude", home + "/Library/Application Support/Claude/claude-code/2.1.0/claude")):
        problem = D.cli_path_problem(resolved, real, home)
        check("the Claude Desktop app's own copy is refused (%s)" % real,
              problem is not None and "Desktop" in problem and "official installer" in problem, problem)

    check("--bare is refused wherever it appears",
          "--bare" in (D.forbidden_arg_problem(["claude", "-p", "--bare"]) or "")
          and "CLAUDE_CODE_OAUTH_TOKEN" in (D.forbidden_arg_problem(["claude", "--bare=1"]) or ""))
    check("an ordinary template has no forbidden argument",
          D.forbidden_arg_problem(["claude", "-p", "{prompt}", "--output-format", "json"]) is None)


def test_run_rules(D):
    import datetime as dt

    print("\n== the routine's environment ==")
    base = {"HOME": "/h", "PATH": "/usr/bin:/bin", "USER": "u", "LANG": "en_US.UTF-8", "TMPDIR": "/t",
            "SSH_AUTH_SOCK": "/s", "BRAIN_VAULT": "/h/Brain", "ANTHROPIC_API_KEY": "k", "ANTHROPIC_AUTH_TOKEN": "t",
            "ANTHROPIC_BASE_URL": "https://proxy", "ANTHROPIC_MODEL": "m", "CLAUDE_CODE_OAUTH_TOKEN": "parent",
            "CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_CODE_USE_VERTEX": "1", "CLAUDE_CODE_USE_FOUNDRY": "1",
            "AWS_ACCESS_KEY_ID": "a", "AWS_BEARER_TOKEN_BEDROCK": "b", "GOOGLE_APPLICATION_CREDENTIALS": "g",
            "AZURE_CLIENT_SECRET": "z", "RANDOM": "r"}
    snapshot = dict(base)
    env = D.routine_env(base, FAKE_TOKEN)
    check("the pool token is the only credential", env.get("CLAUDE_CODE_OAUTH_TOKEN") == FAKE_TOKEN
          and not [k for k in env if k.startswith(("ANTHROPIC_", "AWS_", "AZURE_", "CLAUDE_CODE_USE_", "GOOGLE_"))],
          sorted(env))
    check("what the CLI needs is kept", all(env.get(k) == base[k] for k in ("HOME", "PATH", "USER", "LANG", "TMPDIR",
                                                                               "SSH_AUTH_SOCK", "BRAIN_VAULT")), env)
    check("anything else is not inherited", "RANDOM" not in env, sorted(env))
    check("auto-update is off", env.get("DISABLE_AUTOUPDATER") == "1")
    check("the parent environment is not mutated", base == snapshot)
    check("a missing PATH gets a system default", "/usr/bin" in D.routine_env({"HOME": "/h"}, FAKE_TOKEN)["PATH"])

    print("\n== agent_args in a routine's frontmatter ==")
    fm = "---\nid: r\nneeds_bridge: [email]\n%s---\n\nbody\nagent_args: [\"--bare\"]\n"
    check("no frontmatter, no args", D.parse_agent_args("just a prompt") == ((), None))
    check("no agent_args key, no args", D.parse_agent_args(fm % "") == ((), None))
    got = D.parse_agent_args(fm % 'agent_args: ["--permission-mode", "acceptEdits", "--allowedTools", "Bash,Read"]\n')
    check("a JSON list of strings is read, in order",
          got == (("--permission-mode", "acceptEdits", "--allowedTools", "Bash,Read"), None), got)
    for name, line in (("a YAML flow list", "agent_args: [--permission-mode, acceptEdits]\n"),
                       ("a list of numbers", "agent_args: [1, 2]\n"),
                       ("a string", 'agent_args: "--permission-mode acceptEdits"\n')):
        args, problem = D.parse_agent_args(fm % line)
        check("%s is ignored with a problem saying why" % name, args == () and "JSON list of strings" in (problem or ""),
              (args, problem))
    args, problem = D.parse_agent_args(fm % 'agent_args: ["-p", "--bare"]\n')
    check("--bare in agent_args is ignored with a problem naming it", args == () and "--bare" in (problem or ""), problem)

    print("\n== what a failed run tells him ==")
    entry = D.PoolEntry("routines-1", "kp://Brain/apis/claude-code-oauth-routines-1", dt.date(2026, 9, 15), "routines")
    s = D.failure_summary(D.AUTH_INVALID, "401", entry)
    check("a refused token names itself, its account and the renewal",
          "routines-1" in s and "routines" in s and D.renew_command(entry.kp_ref) in s, s)
    s = D.failure_summary(D.TOKEN_MALFORMED, "contains whitespace (2 word(s), 120 characters)", entry)
    check("a malformed value names the reference, the shape and the exact re-store command",
          entry.kp_ref in s and "whitespace" in s and D.restore_command(entry.kp_ref) in s, s)
    for kind in (D.USAGE_LIMIT, D.CREDIT_EXHAUSTED):
        s = D.failure_summary(kind, "limit reached", entry, until="2026-09-15T16:00:00")
        check("%s says its pattern is unverified and until when" % kind, "unverified" in s and "16:00" in s, s)
    s = D.failure_summary(D.KEEPASS_LOCKED, "KeePass is locked for headless reads", entry)
    check("a KeePass failure is described as KeePass's", "KeePass" in s, s)
    s = D.failure_summary(D.UNKNOWN, "exit 1: boom", entry)
    check("an unknown failure points at the raw-output log", "routine-auth.log" in s and "boom" in s, s)
    s = D.failure_summary(D.NO_TOKEN, "", None, until="2026-09-15T16:00:00")
    check("no usable token says when the first one frees up", "16:00" in s, s)
    s = D.failure_summary(D.CLI_MISSING, "agent command not found: /x/claude", None)
    check("a CLI failure carries its reason", "/x/claude" in s, s)
    check("runs that never reached the CLI have their own exit codes",
          D.EXIT_CODES[D.CLI_MISSING] == 127 and D.EXIT_CODES[D.CONFIG] == 78 and D.EXIT_CODES[D.TOKEN_MALFORMED] == 78
          and D.EXIT_CODES[D.KEEPASS_LOCKED] == 75 and D.EXIT_CODES[D.KEEPASS_UNAVAILABLE] == 75
          and D.EXIT_CODES[D.NO_TOKEN] == 75)


def test_success_contract(D):
    import json

    print("\n== the routine's success contract ==")
    fm = "---\nid: r\n%s---\n\nbody\nsuccess_contract: {\"final_line\": \"NOT-THIS\"}\n"
    check("no contract in the frontmatter is no contract", D.parse_success_contract(fm % "") == (None, None))
    check("nor with no frontmatter", D.parse_success_contract("just a prompt") == (None, None))
    c, p = D.parse_success_contract(fm % ('success_contract: {"final_line": "ROUTINE_OK", '
                                          '"required": ["report at"], "forbidden": ["EMAIL NOT SENT:"]}\n'))
    check("a JSON object with final_line, required and forbidden is read",
          c == D.SuccessContract("ROUTINE_OK", ("report at",), ("EMAIL NOT SENT:",)) and p is None, (c, p))
    for name, line in (("a YAML value", "success_contract: final_line ROUTINE_OK\n"),
                       ("an unknown key", 'success_contract: {"final": "ROUTINE_OK"}\n'),
                       ("a list of numbers", 'success_contract: {"forbidden": [1]}\n'),
                       ("an empty object", "success_contract: {}\n")):
        c, p = D.parse_success_contract(fm % line)
        check("%s is no contract, with a problem saying why" % name, c is None and "success_contract" in (p or ""),
              (c, p))

    c = D.SuccessContract("ROUTINE_OK", ("report at",), ("EMAIL NOT SENT:",))
    good = json.dumps({"type": "result", "is_error": False,
                       "result": "Sent the report.\nreport at /tmp/r.html\n\nROUTINE_OK\n"})
    check("a result meeting the contract has nothing unmet", D.check_contract(c, good) == [], D.check_contract(c, good))
    unmet = D.check_contract(c, json.dumps({"result": "Sent.\nreport at x"}))
    check("a missing final line is unmet, naming it", len(unmet) == 1 and "ROUTINE_OK" in unmet[0], unmet)
    unmet = D.check_contract(c, json.dumps({"result": "report at x\nEMAIL NOT SENT: no token\nROUTINE_OK"}))
    check("a forbidden marker is unmet, naming it", len(unmet) == 1 and "EMAIL NOT SENT:" in unmet[0], unmet)
    unmet = D.check_contract(c, json.dumps({"result": "done\nROUTINE_OK"}))
    check("a missing required marker is unmet, naming it", len(unmet) == 1 and "report at" in unmet[0], unmet)
    check("plain text output is checked the same way", D.check_contract(c, "report at x\nROUTINE_OK\n\n") == [])
    unmet = D.check_contract(c, json.dumps({"result": "private body text sk-ant-oat01-abc\n"}))
    check("what is unmet names only the contract's markers, never the output",
          unmet and not any("private body" in u or "sk-ant" in u for u in unmet), unmet)
    check("no contract, nothing to check", D.check_contract(None, "anything") == [])
    check("a contract breach has its own exit code", D.EXIT_CODES[D.CONTRACT_BREACH] == 65)
    s = D.failure_summary(D.CONTRACT_BREACH, "final line is not ROUTINE_OK", None)
    check("its summary says the run exited 0 without delivering, and what is unmet",
          "exited 0" in s and "ROUTINE_OK" in s, s)


def test_permission_problem(D):
    print("\n== permissions an unattended run may never have ==")
    bad = {
        "bare Bash in a comma list": ["--allowedTools", "Read,Bash"],
        "bare Bash as its own argument": ["--allowedTools", "Read", "Bash"],
        "Bash(*)": ["--allowedTools", "Read,Bash(*)"],
        "Bash(:*)": ["--allowedTools", "Bash(:*)"],
        "the = form": ["--allowedTools=Read,Bash"],
        "the --allowed-tools spelling": ["--allowed-tools", "Bash"],
        "space separated": ["--allowedTools", "Read Bash WebFetch"],
    }
    for name, args in bad.items():
        problem = D.permission_problem(args)
        check("%s is refused, naming bare Bash" % name, problem is not None and "Bash" in problem, (args, problem))
    for args, needle in ((["--dangerously-skip-permissions"], "--dangerously-skip-permissions"),
                         (["--allow-dangerously-skip-permissions"], "--allow-dangerously-skip-permissions"),
                         (["--permission-mode", "bypassPermissions"], "bypassPermissions"),
                         (["--permission-mode=bypassPermissions"], "bypassPermissions")):
        problem = D.permission_problem(args)
        check("%s is refused" % needle, problem is not None and needle in problem, problem)
    fine = [
        ["--permission-mode", "acceptEdits", "--allowedTools",
         "Read,Bash(python3 ~/Brain/_bin/google.py send:*),WebFetch"],
        ["--allowedTools", "Read Bash(git -C ~/git/x status:*)"],
        ["--allowedTools", "Bash(jq '.a, .b':*),Read"],
        ["--disallowedTools", "Bash"],
        ["-p", "{prompt}", "--output-format", "json"],
    ]
    for args in fine:
        check("narrow permissions pass: %s" % " ".join(args)[:70], D.permission_problem(args) is None,
              D.permission_problem(args))


LONG_ROUTINE = """---
id: routine-example-routine-b
agent_args: ["--permission-mode", "acceptEdits"]
---

<!-- What it does: sweeps recent items into the vault.
     Runs as the `example-routine-b-agent` row, disabled until enabled by hand.
     If the app task's prompt changes, update this copy too. -->

Capture the outlines of recent items into the Brain vault.

Keep <!-- an inline note --> this sentence.
"""


def test_prompt_framing(D):
    print("\n== the prompt a routine run receives ==")
    check("an HTML comment block is stripped, across lines",
          D.strip_html_comments("a <!-- one\ntwo\nthree --> b") == "a  b", D.strip_html_comments("a <!-- one\ntwo --> b"))
    check("several comments are stripped, the text between them kept",
          D.strip_html_comments("<!--x-->keep<!--y-->also") == "keepalso")
    check("an unterminated comment is left as it is", D.strip_html_comments("a <!-- open") == "a <!-- open")
    body = D.routine_body(LONG_ROUTINE)
    check("the body has no frontmatter and no HTML comment, and starts with the procedure",
          body.startswith("Capture the outlines") and "<!--" not in body and "agent_args" not in body
          and "What it does" not in body, body[:120])
    check("text around an inline comment survives", "Keep  this sentence." in body, body)
    check("a routine with no frontmatter is its whole text, stripped", D.routine_body("\n\nDo it.\n") == "Do it.")

    prompt = D.frame_prompt("example-routine-b-agent", body, "example-routine-b-agent-20260915T074500-ab12cd34",
                            "/state/routine-scratch/example-routine-b-agent-20260915T074500-ab12cd34")
    check("it opens as an instruction to run this routine now, unattended",
          prompt.startswith('You are running the Brain routine "example-routine-b-agent" unattended, right now, '
                            "with nobody at the keyboard. Execute the procedure below from start to finish now. "
                            "Do not ask for a request, do not wait for input."), prompt[:300])
    check("it states the run id and the scratch directory",
          "example-routine-b-agent-20260915T074500-ab12cd34" in prompt
          and "/state/routine-scratch/example-routine-b-agent-20260915T074500-ab12cd34" in prompt, prompt)
    check("it names $BRAIN_ROUTINE_SCRATCH and forbids /tmp and temp files inside the vault",
          "$BRAIN_ROUTINE_SCRATCH" in prompt and "/tmp" in prompt and "~/Brain" in prompt, prompt)
    lower = prompt.lower()
    check("it forbids the save skill and subagents", "`save` skill" in prompt and "subagent" in lower, prompt)
    check("it says to use git -C, never cd ... &&", "git -C" in prompt and "cd <dir> &&" in prompt, prompt)
    check("it says how vw.py append takes its entry and not to add a timestamp",
          "vw.py append <note> <" in prompt and "timestamp" in lower, prompt)
    check("it says to read files with the Read tool and load skills with the Skill tool",
          "Read tool" in prompt and "Skill tool" in prompt, prompt)
    check("the routine body follows the wrapper, whole", prompt.rstrip().endswith(body.rstrip()), prompt[-200:])
    check("framing is pure: the same inputs give the same prompt",
          prompt == D.frame_prompt("example-routine-b-agent", body,
                                   "example-routine-b-agent-20260915T074500-ab12cd34",
                                   "/state/routine-scratch/example-routine-b-agent-20260915T074500-ab12cd34"))
    bare = D.frame_prompt("r", "Do it.", "r-1", None)
    check("with no scratch directory it says not to write temporary files",
          "no scratch directory" in bare.lower() and "Do it." in bare, bare)


def test_run_identity_and_env(D):
    import datetime as dt

    print("\n== a run's identity and environment ==")
    now = dt.datetime(2026, 9, 15, 15, 45, 7)
    rid = D.run_id("digest-now-agent", now, "ab12cd34")
    check("a run id is the routine id, the time and a random suffix",
          rid == "digest-now-agent-20260915T154507-ab12cd34", rid)
    odd = D.run_id("../we ird/id", now, "x/y")
    check("a run id is always safe as one directory name", "/" not in odd and " " not in odd and not odd.startswith("."),
          odd)
    env = D.routine_env({"HOME": "/h", "PATH": "/usr/bin", "BRAIN_ROUTINE_RUN_ID": "parent-run",
                         "BRAIN_HEADLESS": "0"}, FAKE_TOKEN, run_id=rid, scratch="/s/" + rid,
                        extra={"BRAIN_MAIL_SENT_LOG": "/s/logs/mail-sent.jsonl",
                               "CLAUDE_CODE_OAUTH_TOKEN": "an extra must never replace the pool token"})
    check("the run id and the scratch directory are exported",
          env.get("BRAIN_ROUTINE_RUN_ID") == rid and env.get("BRAIN_ROUTINE_SCRATCH") == "/s/" + rid, env)
    check("a routine run is marked headless", env.get("BRAIN_HEADLESS") == "1", env)
    check("the runner's extra variables are exported", env.get("BRAIN_MAIL_SENT_LOG") == "/s/logs/mail-sent.jsonl", env)
    check("an extra variable never replaces the pool token", env.get("CLAUDE_CODE_OAUTH_TOKEN") == FAKE_TOKEN)
    env = D.routine_env({"HOME": "/h", "BRAIN_ROUTINE_RUN_ID": "parent-run"}, FAKE_TOKEN)
    check("with no run, no run id is inherited from the parent", "BRAIN_ROUTINE_RUN_ID" not in env
          and "BRAIN_ROUTINE_SCRATCH" not in env and env.get("BRAIN_HEADLESS") == "1", env)


def test_delivery_contract(D):
    import json

    print("\n== delivery proved by the send log ==")
    fm = "---\nid: r\n%s---\n\nbody\n"
    c, p = D.parse_success_contract(fm % ('success_contract: {"required_sends": 1, "sends_to": '
                                          '"me@example.com", "forbidden": ["EMAIL NOT SENT:"]}\n'))
    check("required_sends and sends_to are read",
          p is None and c == D.SuccessContract(None, (), ("EMAIL NOT SENT:",), 1, "me@example.com"),
          (c, p))
    for name, line in (("zero sends", 'success_contract: {"required_sends": 0}\n'),
                       ("a string count", 'success_contract: {"required_sends": "1"}\n'),
                       ("a boolean count", 'success_contract: {"required_sends": true}\n'),
                       ("sends_to without a count", 'success_contract: {"sends_to": "a@b.co"}\n'),
                       ("sends_to that is not one address", 'success_contract: {"required_sends": 1, "sends_to": "a, b"}\n')):
        c, p = D.parse_success_contract(fm % line)
        check("%s is no contract, with a problem" % name, c is None and "success_contract" in (p or ""), (c, p))

    log = "\n".join([
        json.dumps({"ts": "2026-09-15T15:45:00+02:00", "to": "me@example.com", "subject": "Ofertas",
                    "message_id": "m-1", "run_id": "run-1"}),
        "not json at all",
        json.dumps(["a", "list"]),
        json.dumps({"ts": "2026-09-15T15:46:00+02:00", "to": "someone@example.com", "subject": "Informe",
                    "message_id": "m-2", "run_id": "run-2"}),
        json.dumps({"ts": "2026-09-15T15:47:00+02:00", "to": "me@example.com", "subject": "manual",
                    "message_id": "m-3"}),
        ""])
    records = D.parse_send_log(log)
    check("the send log parses one record per good line, skipping the rest",
          [r.get("message_id") for r in records] == ["m-1", "m-2", "m-3"], records)
    check("records are filtered by run id", [r["message_id"] for r in D.sends_for_run(records, "run-1")] == ["m-1"])
    check("a send with no run id belongs to no run", D.sends_for_run(records, None) == []
          and all(r["message_id"] != "m-3" for r in D.sends_for_run(records, "run-2")))

    c = D.SuccessContract(None, (), ("EMAIL NOT SENT:",), 1, "me@example.com")
    ending = json.dumps({"result": "Sent the shortlist.\n\nLibrarian agent launched in background to save notes."})
    check("a recorded send for this run meets the contract, whatever the last line says",
          D.check_contract(c, ending, sends=D.sends_for_run(records, "run-1")) == [],
          D.check_contract(c, ending, sends=D.sends_for_run(records, "run-1")))
    claimed = json.dumps({"result": "sent to me@example.com: Ofertas\nROUTINE_OK"})
    unmet = D.check_contract(c, claimed, sends=[])
    check("an answer claiming the send with no record is unmet, naming the send log",
          len(unmet) == 1 and "mail-sent.jsonl" in unmet[0] and "me@example.com" in unmet[0], unmet)
    unmet = D.check_contract(c, ending, sends=D.sends_for_run(records, "run-2"))
    check("a send to another address does not count", len(unmet) == 1, unmet)
    upper = [dict(records[0], to="Me@Example.com")]
    check("the address comparison ignores case", D.check_contract(c, ending, sends=upper) == [])
    check("without sends_to any recorded send counts",
          D.check_contract(D.SuccessContract(None, (), (), 1), ending, sends=D.sends_for_run(records, "run-2")) == [])
    unmet = D.check_contract(c, json.dumps({"result": "EMAIL NOT SENT: token\n"}), sends=D.sends_for_run(records, "run-1"))
    check("forbidden markers still apply next to the send check", len(unmet) == 1 and "EMAIL NOT SENT:" in unmet[0], unmet)
    two = D.SuccessContract(None, (), (), 2)
    check("the count is enforced", len(D.check_contract(two, ending, sends=D.sends_for_run(records, "run-1"))) == 1)
    check("ROUTINE_OK as a required marker is met anywhere in the answer",
          D.check_contract(D.SuccessContract(None, ("ROUTINE_OK",), ()),
                           json.dumps({"result": "ROUTINE_OK\nand then a closing remark"})) == [])

    print("\n== an answer that never ran the routine ==")
    from routine_auth_core.fixtures import FIXTURES

    fx = FIXTURES["ok_no_request_reply"]
    reply = D.result_text(fx["stdout"])
    check("the recorded reply is recognised as asking for a request", D.asked_for_request(reply), reply)
    check("a real report is not", not D.asked_for_request("Saved 3 meetings, 0 questions.\nROUTINE_OK")
          and not D.asked_for_request(""))
    meetings = D.SuccessContract(None, ("ROUTINE_OK",), ("ROUTINE_FAILED:",))
    unmet = D.check_contract(meetings, fx["stdout"])
    check("its breach says plainly that the routine was not run, before the missing marker",
          len(unmet) == 2 and "did not run the routine" in unmet[0] and "ROUTINE_OK" in unmet[1], unmet)
    check("and quotes nothing of the answer", not any("session context" in u for u in unmet), unmet)


def test_scratch_rules(D):
    import datetime as dt

    print("\n== scratch directories to prune ==")
    now = dt.datetime(2026, 9, 15, 12, 0)
    entries = [("old", now - dt.timedelta(days=8)), ("edge", now - dt.timedelta(days=7, seconds=1)),
               ("young", now - dt.timedelta(days=6, hours=23)), ("future", now + dt.timedelta(hours=1))]
    check("dirs older than 7 days are pruned, younger ones kept",
          D.scratch_to_prune(entries, now) == ["old", "edge"], D.scratch_to_prune(entries, now))
    check("the retention is 7 days", D.SCRATCH_KEEP_DAYS == 7)
    check("the age is a parameter", D.scratch_to_prune(entries, now, keep_days=30) == [])


def test_vault_routines(D):
    import glob
    import re

    print("\n== the vault's own 90-Meta/routines ==")
    vault = os.path.dirname(os.path.dirname(HERE))
    files = sorted(glob.glob(os.path.join(vault, "90-Meta", "routines", "*.md")))
    check("the vault ships at least the example routine",
          any(os.path.basename(f) == "example-routine.md" for f in files), files)
    send = "Bash(python3 ~/Brain/_bin/google.py send:*)"
    for path in files:
        name = os.path.basename(path)
        text = open(path, encoding="utf-8").read()
        args, args_problem = D.parse_agent_args(text)
        check("%s: agent_args parse" % name, bool(args) and args_problem is None, args_problem)
        check("%s: agent_args grant no unrestricted permissions" % name, D.permission_problem(args) is None,
              D.permission_problem(args))
        contract, contract_problem = D.parse_success_contract(text)
        check("%s: a success contract that parses" % name, contract is not None and contract_problem is None,
              (contract, contract_problem))
        if contract is None:
            continue
        body = D.routine_body(text)
        joined = " ".join(args)
        check("%s: success is a recorded send or ROUTINE_OK anywhere, never a last-line rule" % name,
              contract.final_line is None and (contract.required_sends or "ROUTINE_OK" in contract.required), contract)
        needs = [l for l in (D.frontmatter(text) or "").splitlines() if l.startswith("needs_bridge:")]
        if needs and "email" in needs[0]:
            check("%s emails through google.py send, allowed as one narrow Bash pattern" % name,
                  send in joined and "python3 ~/Brain/_bin/google.py send" in body, args)
            to = re.findall(r"google\.py send\b[^\n`]*?--to (\S+)", body)   # argparse takes flags in any order
            check("%s: delivery is proved by one recorded send to the address its prompt sends to" % name,
                  contract.required_sends == 1 and to and contract.sends_to == to[0], (contract, to))
            check("%s: a report that was not sent breaks its contract" % name, "EMAIL NOT SENT:" in contract.forbidden,
                  contract)
        check("%s: the prompt never points temporary files at /tmp" % name, "/tmp" not in body)
        check("%s: the prompt never chains cd with &&" % name, not re.search(r"\bcd [^`\n]*&&", body),
              re.findall(r"\bcd [^`\n]*&&", body))
        check("%s: the prompt never pipes printf into vw.py" % name, not re.search(r"printf[^\n]*\|\s*python3", body))
        if "vw.py append" in body:
            check("%s: vw.py append entries come from a scratch file, with no timestamp of their own" % name,
                  "scratch directory" in body and "timestamp" in body
                  and not re.search(r"\*\*<YYYY-MM-DD HH:MM>\*\*", body), name)
        for skill in sorted(set(re.findall(r"~/\.claude/skills/([a-z0-9-]+)/", body))):
            check("%s: the %s skill's files may be read, by one narrow Read rule" % (name, skill),
                  "Read(~/.claude/skills/%s/**)" % skill in joined, args)
        check("%s: the prompt tells the run not to invoke save or spawn agents" % name,
              "`save` skill" in body and "subagent" in body.lower(), name)


def main():
    try:
        from routine_auth_core import domain as D
    except Exception as exc:
        check("routine_auth_core.domain imports", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_classify, test_token_shape, test_redact, test_failover, test_pool_and_expiry,
                  test_cli_rules, test_run_rules, test_success_contract, test_permission_problem,
                  test_prompt_framing, test_run_identity_and_env, test_delivery_contract, test_scratch_rules,
                  test_vault_routines):
            try:
                t(D)
            except Exception as exc:
                import traceback
                traceback.print_exc()
                check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
