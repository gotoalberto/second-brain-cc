#!/usr/bin/env python3
"""secret.py — credentials for the brain, backed by 1Password CLI (`op`).

The vault never stores secrets. A note cites a reference and nothing else:

    op://<vault>/<item>/<field>        e.g.  op://Private/GitHub/token

This wrapper resolves that reference through the 1Password CLI without ever
printing the secret into the conversation. By default it copies to the clipboard;
`--pipe` streams it into another process's stdin; `--show` prints it (with a warning).

Usage:
  secret.py get op://Vault/Item/field            # -> clipboard (default)
  secret.py get op://Vault/Item/field --pipe 'gh auth login --with-token'
  secret.py get op://Vault/Item/field --show     # prints it; use only if asked
  secret.py put Vault/Item -f token=... -f user=...   # create/overwrite an item
  secret.py ref Vault/Item/field                 # print the op:// reference for a note
  secret.py check                                # is `op` installed and signed in?

Requires the 1Password CLI: https://developer.1password.com/docs/cli/
Sign in once (`op signin`) or enable the desktop-app integration.
"""
import sys, subprocess, argparse, shutil

OP = shutil.which("op")

def die(msg, code=1):
    print("secret: " + msg, file=sys.stderr); sys.exit(code)

def need_op():
    if not OP:
        die("1Password CLI not found. Install it: https://developer.1password.com/docs/cli/", 6)

def clipboard_cmd():
    """First available clipboard tool for this OS, or None."""
    for cmd in (["pbcopy"],                        # macOS
                ["wl-copy"],                        # Linux (Wayland)
                ["xclip", "-selection", "clipboard"],  # Linux (X11)
                ["xsel", "--clipboard", "--input"],    # Linux (X11)
                ["clip.exe"]):                      # Windows / WSL
        if shutil.which(cmd[0]):
            return cmd
    return None

def op_read(ref):
    need_op()
    p = subprocess.run([OP, "read", ref], capture_output=True, text=True)
    if p.returncode != 0:
        err = p.stderr.strip()
        if "not currently signed in" in err or "no active session" in err:
            die("not signed in to 1Password. Run `op signin` (or enable the app integration).", 4)
        die("op read failed: " + err, 1)
    return p.stdout.rstrip("\n")

def cmd_get(a):
    val = op_read(a.ref)
    if a.show:
        print("secret: WARNING — printing the secret to the terminal.", file=sys.stderr)
        sys.stdout.write(val + "\n")
    elif a.pipe:
        subprocess.run(a.pipe, shell=True, input=val, text=True)
    else:
        clip = clipboard_cmd()
        if not clip:
            die("no clipboard tool found (pbcopy / wl-copy / xclip / xsel / clip.exe); "
                "use --pipe or --show", 1)
        subprocess.run(clip, input=val, text=True)
        print("secret: value copied to the clipboard.")

def cmd_put(a):
    need_op()
    vault, _, item = a.target.partition("/")
    if not item:
        die("target must be Vault/Item", 1)
    fields = [f"{k}={v}" for k, v in (kv.split("=", 1) for kv in a.field)]
    # create if missing, else edit
    exists = subprocess.run([OP, "item", "get", item, "--vault", vault],
                            capture_output=True, text=True).returncode == 0
    if exists:
        p = subprocess.run([OP, "item", "edit", item, "--vault", vault, *fields],
                           capture_output=True, text=True)
    else:
        p = subprocess.run([OP, "item", "create", "--category", "Login",
                            "--title", item, "--vault", vault, *fields],
                           capture_output=True, text=True)
    if p.returncode != 0:
        die("op item write failed: " + p.stderr.strip(), 1)
    first = a.field[0].split("=", 1)[0] if a.field else "password"
    print("secret: stored. Reference for the note:  op://%s/%s/%s" % (vault, item, first))

def cmd_ref(a):
    print("op://" + a.path.lstrip("/"))

def cmd_check(a):
    need_op()
    p = subprocess.run([OP, "account", "list"], capture_output=True, text=True)
    if p.returncode == 0 and p.stdout.strip():
        print("secret: op installed and an account is configured.")
    else:
        print("secret: op installed but not signed in. Run `op signin`.")

def main():
    ap = argparse.ArgumentParser(prog="secret.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("get"); g.add_argument("ref")
    g.add_argument("--pipe"); g.add_argument("--show", action="store_true"); g.set_defaults(fn=cmd_get)
    p = sub.add_parser("put"); p.add_argument("target"); p.add_argument("-f", "--field", action="append", default=[]); p.set_defaults(fn=cmd_put)
    r = sub.add_parser("ref"); r.add_argument("path"); r.set_defaults(fn=cmd_ref)
    c = sub.add_parser("check"); c.set_defaults(fn=cmd_check)
    a = ap.parse_args(); a.fn(a)

if __name__ == "__main__":
    main()
