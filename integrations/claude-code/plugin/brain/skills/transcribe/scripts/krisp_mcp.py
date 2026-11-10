#!/usr/bin/env python3
"""Krisp MCP from the shell, for sessions where the `mcp__krisp__*` tools are not loaded.

Talks JSON-RPC to https://mcp.krisp.ai/mcp. The OAuth credential lives in the kdbx
(`apis/krisp-mcp-oauth`); Claude Code keeps its own working copy in the macOS Keychain.
The token never reaches stdout, argv or a file.

  krisp_mcp.py setup                  add the `krisp` server to Claude Code, log in, back up to kdbx
  krisp_mcp.py status                 server config, token presence and expiry in kdbx and Keychain
  krisp_mcp.py tools [--schema]       tool names, or full input schemas
  krisp_mcp.py call <tool> [json|-]   call a tool; args as JSON on argv or stdin
                   [--json]           print structuredContent instead of the text blocks
  krisp_mcp.py backup                 copy Claude Code's Keychain credential into the kdbx
  krisp_mcp.py login                  run the OAuth login in a pty (opens the browser)

Token order: kdbx first. If the kdbx copy is missing, expired or rejected, the Keychain copy is
used and written back into the kdbx, so the kdbx heals itself after Claude Code refreshes.

Python 3.9 compatible (it runs under the Xcode python too).
"""
import glob, json, os, shutil, subprocess, sys, time, urllib.error, urllib.request

URL = "https://mcp.krisp.ai/mcp"
SERVER = "krisp"
KEYCHAIN_SERVICE = "Claude Code-credentials"
KDBX_ENTRY = "apis/krisp-mcp-oauth"
INSTALLED_VAULT = "__VAULT__"  # the installer writes this machine's vault path here


def _kp_script():
    """kp.py: BRAIN_KP_SCRIPT, else <vault>/_bin/kp.py, the vault being BRAIN_VAULT or the installed one."""
    explicit = os.environ.get("BRAIN_KP_SCRIPT")
    if explicit:
        return explicit
    vault = os.environ.get("BRAIN_VAULT") or INSTALLED_VAULT
    if not os.path.isdir(vault):
        vault = os.path.expanduser("~/Brain")
    return os.path.join(vault, "_bin", "kp.py")


KP = _kp_script()
# Krisp's edge answers 403 to urllib's default User-Agent. Any real-looking UA works.
UA = "claude-code-krisp-skill/1.0"
FIELDS = ("serverName", "serverUrl", "issuer", "clientId", "clientSecret",
          "redirectUri", "accessToken", "refreshToken", "expiresAt", "scope")


class Unauthorized(Exception):
    pass


def claude_bin():
    # PATH first, and the Linux machines install the CLI at ~/.local/bin/claude, which a
    # non-login shell may not have. The `zsh -lc` trick below is a macOS habit: zsh is not
    # installed on Ubuntu, so it raised FileNotFoundError and the whole script died before
    # reaching the token, which is what made Krisp look macOS-only when it is not. The
    # token itself has lived in the kdbx all along, and the kdbx is reachable everywhere.
    direct = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
    if os.path.exists(direct):
        return direct
    try:
        found = subprocess.run(["/bin/zsh", "-lc", "command -v claude"],
                               capture_output=True, text=True).stdout.strip()
    except OSError:
        found = ""
    if found:
        return found
    # Claude desktop app: the CLI ships inside a versioned bundle and is not on PATH.
    pat = os.path.expanduser("~/Library/Application Support/Claude/claude-code/*/claude.app/Contents/MacOS/claude")
    cands = glob.glob(pat)
    if not cands:
        sys.exit("claude CLI not found (not on PATH, no desktop app bundle)")

    def ver(p):
        v = p.split("/claude-code/")[1].split("/")[0]
        return tuple(int(x) if x.isdigit() else 0 for x in v.split("."))
    return max(cands, key=ver)


def claude(*args):
    return subprocess.run([claude_bin()] + list(args), capture_output=True, text=True,
                          cwd=os.path.expanduser("~"))


def _claude_credentials():
    """Claude Code's own credential blob, wherever this machine keeps it.

    Same JSON either way (`mcpOAuth` keyed `<server>|<hash>`); only the container differs:
    the macOS Keychain, or `~/.claude/.credentials.json` on Linux. Reading only the Keychain
    is what made this script look macOS-only; it is not, and the kdbx copy of the token has
    always been the source of truth anyway.
    """
    if sys.platform == "darwin":
        r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                           capture_output=True, text=True)
        return r.stdout if r.returncode == 0 and r.stdout.strip() else ""
    try:
        return open(os.path.expanduser("~/.claude/.credentials.json"), errors="replace").read()
    except OSError:
        return ""


def keychain_entry():
    raw = _claude_credentials()
    if not raw.strip():
        return None
    try:
        oauth = json.loads(raw).get("mcpOAuth", {})
    except ValueError:
        return None
    for k, v in oauth.items():
        if k.split("|")[0] == SERVER and v.get("accessToken"):
            return v
    return None


def kdbx_entry():
    if not os.path.exists(KP):
        return None
    r = subprocess.run([sys.executable, KP, "get", KDBX_ENTRY, "--pipe", "cat"],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout.strip())
    except ValueError:
        return None


def expired(entry):
    exp = entry.get("expiresAt")
    return bool(exp) and exp / 1000 < time.time()


def backup_to_kdbx(entry):
    """Write the credential into the kdbx. Returns (returncode, kp.py output)."""
    keep = {k: entry.get(k) for k in FIELDS}
    keep["backed_up_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    exists = subprocess.run([sys.executable, KP, "get", KDBX_ENTRY, "--info"],
                            capture_output=True, text=True).returncode == 0
    cmd = [sys.executable, KP, "set" if exists else "put", KDBX_ENTRY, "--stdin"]
    if not exists:
        cmd += ["-u", entry.get("clientId") or "krisp-mcp", "--url", URL, "--notes",
                "Krisp MCP OAuth credential for Claude Code (server `krisp`, user scope). JSON blob: "
                "clientId, clientSecret, accessToken, refreshToken, expiresAt (ms), scope. The kdbx is "
                "the home of this credential; Claude Code keeps a working copy in the macOS Keychain item "
                "'Claude Code-credentials' > mcpOAuth > krisp|*. Refreshed by the krisp skill's "
                "scripts/krisp_mcp.py (backup, or automatically when the kdbx copy goes stale)."]
    r = subprocess.run(cmd, input=json.dumps(keep), capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def _alert_dead_token(detail):
    """No Krisp token works: say so on stderr, where the caller's log keeps it."""
    print("[krisp] %s" % detail, file=sys.stderr)


class Client:
    def __init__(self):
        self.sid = None
        self.n = 0
        self.tok = None
        tried = []
        kdbx = kdbx_entry()
        sources = [("kdbx", lambda: kdbx), ("keychain", keychain_entry)]
        for source, fetch in sources:
            entry = fetch()
            if not entry or not entry.get("accessToken"):
                tried.append("%s: none" % source)
                continue
            if expired(entry):
                tried.append("%s: expired" % source)
                continue
            self.tok, self.sid, self.n = entry["accessToken"], None, 0
            try:
                init = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                               "clientInfo": {"name": "krisp-skill", "version": "1.0"}})
            except Unauthorized:
                tried.append("%s: rejected (401)" % source)
                continue
            self.server = init.get("result", {}).get("serverInfo")
            self.rpc("notifications/initialized", notify=True)
            if source == "keychain" and (not kdbx or kdbx.get("accessToken") != entry["accessToken"]):
                rc, out = backup_to_kdbx(entry)
                print("[krisp] kdbx copy was stale; refreshed from the Keychain (%s)" %
                      ("ok" if rc == 0 else "FAILED: " + out[:200]), file=sys.stderr)
            return
        _alert_dead_token("no working token (%s)" % "; ".join(tried))
        sys.exit("[krisp] no working token (%s). Run: krisp_mcp.py login" % "; ".join(tried))

    def rpc(self, method, params=None, notify=False, retries=2):
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            self.n += 1
            body["id"] = self.n
        h = {"Authorization": "Bearer " + self.tok, "Content-Type": "application/json",
             "Accept": "application/json, text/event-stream", "User-Agent": UA}
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        req = urllib.request.Request(URL, json.dumps(body).encode(), h)
        for attempt in range(retries + 1):
            try:
                r = urllib.request.urlopen(req, timeout=90)
                break
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    raise Unauthorized()
                if e.code in (502, 503, 504) and attempt < retries:
                    time.sleep(3)
                    continue
                detail = e.read().decode(errors="replace")[:300]
                sys.exit("[krisp] HTTP %s on %s: %s" % (e.code, method, detail))
            except (urllib.error.URLError, OSError) as e:
                # socket.timeout is not a TimeoutError on Python 3.9; OSError covers both.
                if attempt < retries:
                    time.sleep(3)
                    continue
                sys.exit("[krisp] network error on %s: %s" % (method, e))
        self.sid = r.headers.get("Mcp-Session-Id") or self.sid
        text = r.read().decode()
        if not text.strip():
            return {}
        if "data:" in text[:200]:
            text = [l[5:].strip() for l in text.splitlines() if l.startswith("data:")][-1]
        return json.loads(text)


def cmd_status():
    cfg = claude("mcp", "get", SERVER)
    print((cfg.stdout or cfg.stderr).strip())
    for source, entry in (("kdbx", kdbx_entry()), ("keychain", keychain_entry())):
        if not entry:
            print("%-8s: no token" % source)
            continue
        exp = entry.get("expiresAt")
        left = "unknown" if not exp else "%.1f days" % ((exp / 1000 - time.time()) / 86400)
        print("%-8s: token present, expires in %s, scope: %s" % (source, left, entry.get("scope")))


def cmd_tools(schema):
    c = Client()
    tools = c.rpc("tools/list")["result"]["tools"]
    if schema:
        print(json.dumps(tools, indent=2))
        return
    print("server:", c.server)
    for t in tools:
        ann = t.get("annotations", {})
        kind = "read " if ann.get("readOnlyHint") else "WRITE"
        print("%s  %-24s %s" % (kind, t["name"], " ".join(t.get("description", "").split())[:100]))


def cmd_call(tool, raw, as_json):
    if raw == "-":
        raw = sys.stdin.read()
    args = json.loads(raw) if raw else {}
    res = Client().rpc("tools/call", {"name": tool, "arguments": args})
    if "error" in res:
        sys.exit("[krisp] %s" % json.dumps(res["error"]))
    result = res.get("result", {})
    if as_json:
        print(json.dumps(result.get("structuredContent", result), indent=2, ensure_ascii=False))
    else:
        for block in result.get("content", []):
            if block.get("type") == "text":
                print(block["text"])
    if result.get("isError"):
        sys.exit(1)


def cmd_backup():
    entry = keychain_entry()
    if not entry:
        sys.exit("[krisp] nothing in the Keychain to back up. Run `krisp_mcp.py login` first.")
    rc, out = backup_to_kdbx(entry)
    print(out or "ok")
    sys.exit(rc)


def login():
    # `claude mcp login` refuses without a TTY; `script` gives it one and it opens the browser.
    return subprocess.run(["script", "-q", "/dev/null", claude_bin(), "mcp", "login", SERVER]).returncode


def cmd_setup():
    if claude("mcp", "get", SERVER).returncode != 0:
        r = claude("mcp", "add", "--scope", "user", "--transport", "http", SERVER, URL)
        print((r.stdout + r.stderr).strip())
        if r.returncode != 0:
            sys.exit(r.returncode)
    else:
        print("[krisp] server already configured")
    if login() != 0:
        sys.exit("[krisp] login failed; the user has to approve in the browser")
    cmd_backup()


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return
    c = argv[0]
    if c == "status":
        cmd_status()
    elif c == "tools":
        cmd_tools("--schema" in argv)
    elif c == "call":
        rest = [a for a in argv[1:] if a != "--json"]
        if not rest:
            sys.exit("usage: krisp_mcp.py call <tool> [json|-] [--json]")
        cmd_call(rest[0], rest[1] if len(rest) > 1 else "", "--json" in argv)
    elif c == "backup":
        cmd_backup()
    elif c == "login":
        sys.exit(login())
    elif c == "setup":
        cmd_setup()
    else:
        sys.exit("unknown command %r" % c)


if __name__ == "__main__":
    main(sys.argv[1:])
