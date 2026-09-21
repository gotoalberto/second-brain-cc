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
machine it was read on.

The key carries the hostname, so it changes when the hostname does. That is fine for a file name
and wrong for "is this record mine?": `machine_is_mine()` answers that one, and accepts every form
this machine has written (the current key, the raw uuid, the bare label `brainlib._machine()` still
writes locally, a key from before a rename that ends in the same fragment, and any alias listed in
`BRAIN_MACHINE_ALIASES`). A machine that stops recognising its own name either locks itself out of
its own records or clears someone else's. Every effect (which platform this is, how to run a command, how to open a
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


def machine_label(hostname=None):
    """The human name of this machine: the sanitised short hostname. It may change; the uuid may not."""
    return sanitize_hostname(hostname if hostname is not None else os.uname().nodename)


def id8(value):
    """The first 8 hex digits of an id, lowercased, or "" when it has fewer. Dashes and case ignored."""
    hexes = re.sub(r"[^0-9a-f]", "", str(value or "").lower())
    return hexes[:8] if len(hexes) >= 8 else ""


_KEY_FRAGMENT = re.compile(r"-([0-9a-f]{8})$")


def historical_keys(environ=None):
    """Names this machine went by that nothing else can recognise, from `BRAIN_MACHINE_ALIASES`.

    A comma-separated list. It is only needed for a machine with no readable uuid that was
    renamed: a key with the same uuid fragment is already recognised on its own.
    """
    environ = os.environ if environ is None else environ
    out = []
    for item in (environ.get("BRAIN_MACHINE_ALIASES") or "").split(","):
        item = item.strip()
        if item and item not in out:
            out.append(item)
    return tuple(out)


def machine_is_mine(value, current=None, uuid=None, label=None, historical=None,
                    hostname=None, platform=None, run=None, open_=None, environ=None):
    """Does `value` name THIS machine? Every form it has ever written counts, case aside.

    Accepted: the current key, the raw uuid (with or without dashes), the bare label, any key
    ending in this machine's own uuid fragment (the same machine under an older hostname) and
    every historical key. The bare label is the loose end, on purpose: local records written by
    `brainlib._machine()` carry it, and a machine must recognise those. Two machines that share a
    hostname also share that bare form, which is why nothing shared across machines uses it.

    `current`, `uuid`, `label` and `historical` default to what this machine reports; tests pass
    them in. With `BRAIN_MACHINE_KEY` forced, no hardware is read: the forced key, its own
    fragment and the listed aliases are the whole identity.
    """
    v = str(value or "").strip().casefold()
    if not v:
        return False
    environ = os.environ if environ is None else environ
    forced = (environ.get("BRAIN_MACHINE_KEY") or "").strip()
    if historical is None:
        historical = historical_keys(environ)
    if current is None and forced:
        current, uuid, label = forced, "", ""
    if current is None or uuid is None:
        hostname = hostname if hostname is not None else os.uname().nodename
        if uuid is None:
            uuid = read_uuid(platform if platform is not None else sys.platform, run or _run, open_ or open)
        if current is None:
            current = machine_key(hostname, uuid)
    if label is None:
        label = machine_label(hostname)
    names = {str(n).strip().casefold() for n in (current, uuid, label) + tuple(historical) if n}
    if v in names:
        return True
    if uuid and set(v) <= set("0123456789abcdef-") and v.replace("-", "") == str(uuid).replace("-", "").lower():
        return True
    frag = id8(uuid)
    if not frag:
        m = _KEY_FRAGMENT.search(str(current or "").lower())
        frag = m.group(1) if m else ""
    return bool(frag) and v.endswith("-" + frag)


def main():
    print(current_key())
    return 0


if __name__ == "__main__":
    sys.exit(main())
