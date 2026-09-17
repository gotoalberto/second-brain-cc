#!/usr/bin/env python3
"""Machine identity: a key that tells apart two machines that share a hostname.

`brainlib._machine()` is the hostname alone, and stays that way: every existing caller
(`claim.py`, `lease.py`, `vault_sync.py`'s local logging) is unaffected by this module. But a
hostname is not unique — several machines can report the very same one — and that only matters
once two machines coordinate over a shared path (the presence beat, `claims_sync.py`'s record
filenames): a lease or a claim keyed on hostname alone would then silently apply to both.

`machine_key()` appends the first 8 hex characters of a hardware/boot UUID, read the way the OS
exposes it:

  macOS    `ioreg -rd1 -c IOPlatformExpertDevice -r`, "IOPlatformUUID"
  Linux    `/etc/machine-id` (no root needed), else `/sys/class/dmi/id/product_uuid`

Only that 8-hex fragment is ever written to disk; the full UUID never is, and neither leaves the
machine it was read on. Every effect (which platform this is, how to run a command, how to open a
file) is a parameter, the same style as `kp.py`'s `cache_backend()` / `dialog_backend()`, so the
decision is testable with no real hardware. See machine_identity_test.py.
"""
import os
import re
import subprocess
import sys

_HEX8 = re.compile(r"^[0-9A-Fa-f]{8}$")
_IOREG_UUID = re.compile(r'"IOPlatformUUID"\s*=\s*"([0-9A-Fa-f-]{36})"')
_MACHINE_ID = re.compile(r"^[0-9A-Fa-f]{32}$")
_PRODUCT_UUID = re.compile(r"^[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$")


def sanitize_hostname(hostname):
    """One path/key component: the first label only, no slashes, never empty."""
    text = str(hostname or "").split(".")[0].strip()
    text = text.replace("/", "_").replace("\\", "_")
    return text or "machine"


def machine_key(hostname, uuid):
    """`<hostname>-<8hex>`, or the hostname alone when no usable uuid is given.

    Only this derived key is ever written to disk; the uuid it was built from is not — the
    caller reads it, folds it in here, and lets it go.
    """
    host = sanitize_hostname(hostname)
    frag = str(uuid or "").replace("-", "").strip()[:8]
    if _HEX8.match(frag):
        return "%s-%s" % (host, frag.lower())
    return host


def parse_ioreg_uuid(text):
    """The value of "IOPlatformUUID" in `ioreg -rd1 -c IOPlatformExpertDevice -r` output, or ""."""
    m = _IOREG_UUID.search(text or "")
    return m.group(1) if m else ""


def parse_machine_id(text):
    """/etc/machine-id: one bare 32-hex line, no dashes. "" when it is not that shape."""
    t = (text or "").strip()
    return t if _MACHINE_ID.match(t) else ""


def parse_product_uuid(text):
    """/sys/class/dmi/id/product_uuid: one dashed uuid line. "" when it is not that shape."""
    t = (text or "").strip()
    return t if _PRODUCT_UUID.match(t) else ""


def read_uuid(platform, run, open_):
    """The machine's uuid, read the way this platform exposes it, or "" when none is readable.

    `run(cmd)` -> (returncode, stdout, stderr), `open_(path)` -> a context manager with
    `.read()`, both injected so this never touches a real machine in a test. Any failure — the
    command is missing, the file cannot be read — is silent: an unreadable uuid is not an error,
    it is the fallback-to-hostname case `machine_key()` already handles.
    """
    if platform == "darwin":
        try:
            code, out, _err = run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice", "-r"])
        except Exception:
            return ""
        return parse_ioreg_uuid(out) if code == 0 else ""
    try:
        with open_("/etc/machine-id") as fh:
            found = parse_machine_id(fh.read())
        if found:
            return found
    except OSError:
        pass
    try:
        with open_("/sys/class/dmi/id/product_uuid") as fh:
            return parse_product_uuid(fh.read())
    except OSError:
        return ""


def _run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return p.returncode, p.stdout, p.stderr
    except Exception:
        return 1, "", "error"


def current_key(hostname=None, platform=None, run=None, open_=None, environ=None):
    """`machine_key()` for the machine this process runs on.

    `BRAIN_MACHINE_KEY`, when set, is returned as-is instead of reading real hardware: the
    test suite forces it, the same way `kp.py`'s `BRAIN_KP_CACHE_BACKEND=none` keeps a test
    process out of the real keyring. Without it every test that touches this function would
    read (and could print, or write to a fixture) this machine's actual hostname and uuid
    fragment — exactly the identity this module exists to keep off shared state.
    """
    environ = os.environ if environ is None else environ
    forced = (environ.get("BRAIN_MACHINE_KEY") or "").strip()
    if forced:
        return forced
    hostname = hostname if hostname is not None else os.uname().nodename
    platform = platform if platform is not None else sys.platform
    run = run or _run
    open_ = open_ or open
    return machine_key(hostname, read_uuid(platform, run, open_))


def main():
    print(current_key())
    return 0


if __name__ == "__main__":
    sys.exit(main())
