#!/usr/bin/env python3
"""WireGuard VPN exits for command line tools, without touching the machine's network.

Each exit is a WireGuard config in KeePass, read through kp.py: the entry's password is the private
key, its notes hold the rest of the config with `{{PRIVATE_KEY}}` where the key goes. `up` runs
wireproxy (userspace WireGuard, no root) with a SOCKS5 proxy on 127.0.0.1:<port>; only the programs
pointed at that proxy go through the VPN, everything else keeps the machine's own IP. wireproxy
installs itself on first use (a pinned GitHub release, sha256 checked against the release checksums).

  vpn.py list                       configured exits, their ports and KeePass references
  vpn.py up <exit> [--no-ip]        start the exit; prints the proxy URL (and the public IP it shows)
  vpn.py down [<exit>|all]          stop it (default all)
  vpn.py status [--no-ip]           running exits (and the public IP each one shows)
  vpn.py ip <exit>                  public IP and country seen through that exit
  vpn.py install                    download wireproxy for this OS (done by `up` when missing)

Configuration:
  VPN_PROXY_EXITS      required: the exits, comma separated, `name` or `name=port`
                       (e.g. `nl,se=1090`); a name without a port gets 1080 plus its position
  VPN_PROXY_KP_PREFIX  KeePass entry prefix, default `infra/vpn-wg-` (entry `infra/vpn-wg-<name>`)
  BRAIN_KP_SCRIPT      where kp.py is, default <vault>/_bin/kp.py
  VPN_PROXY_STATE      state and logs, default ~/.local/state/vpn-proxy
  VPN_PROXY_WIREPROXY  a wireproxy binary to use instead of the self-installed one

Use: curl --socks5-hostname 127.0.0.1:1080 ...   ALL_PROXY=socks5h://127.0.0.1:1080 <tool>
"""
import hashlib
import json
import os
import platform
import re
import signal
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request

INSTALLED_VAULT = "__VAULT__"  # the installer writes this machine's vault path here
WP_VERSION = "v1.1.3"
WP_RELEASES = "https://github.com/windtf/wireproxy/releases/download/%s/" % WP_VERSION
WP_DIR = os.path.expanduser("~/.local/share/vpn-proxy")
FIRST_PORT = 1080
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def die(msg):
    sys.stderr.write(msg.rstrip() + "\n")
    sys.exit(1)


def kp_script():
    explicit = os.environ.get("BRAIN_KP_SCRIPT")
    if explicit:
        return explicit
    vault = os.environ.get("BRAIN_VAULT") or INSTALLED_VAULT
    if not os.path.isdir(vault):
        vault = os.path.expanduser("~/Brain")
    return os.path.join(vault, "_bin", "kp.py")


def state_dir():
    return os.environ.get("VPN_PROXY_STATE") or os.path.expanduser("~/.local/state/vpn-proxy")


def wireproxy_path():
    return os.environ.get("VPN_PROXY_WIREPROXY") or os.path.join(WP_DIR, "wireproxy")


def kp_prefix():
    return os.environ.get("VPN_PROXY_KP_PREFIX") or "infra/vpn-wg-"


def kp_entry(name, prefix):
    return prefix + name


def parse_exits(spec):
    """`a, b=1090, c` -> [("a", 1080), ("b", 1090), ("c", 1082)]."""
    exits, seen = [], set()
    for i, item in enumerate(x.strip() for x in (spec or "").split(",")):
        if not item:
            continue
        name, _, port = item.partition("=")
        name = name.strip().lower()
        if not NAME.match(name) or name in seen:
            raise ValueError("bad or repeated exit name: %r" % name)
        if port.strip():
            if not port.strip().isdigit() or not 0 < int(port) < 65536:
                raise ValueError("bad port for %s: %r" % (name, port))
            port = int(port)
        else:
            port = FIRST_PORT + i
        seen.add(name)
        exits.append((name, port))
    return exits


def exits_or_die():
    try:
        exits = parse_exits(os.environ.get("VPN_PROXY_EXITS"))
    except ValueError as exc:
        die("VPN_PROXY_EXITS: %s" % exc)
    if not exits:
        die("no exits configured: set VPN_PROXY_EXITS (e.g. `nl,se`), one KeePass entry per exit")
    return dict(exits)


def render_config(notes, key, port):
    """The wireproxy config: the key in place, comment lines and IPv6 addresses dropped."""
    if "[Interface]" not in (notes or ""):
        raise ValueError("the notes hold no [Interface] section")
    if "{{PRIVATE_KEY}}" not in notes:
        raise ValueError("the notes must carry {{PRIVATE_KEY}} where the key goes, never the key itself")
    lines = []
    for line in notes.replace("{{PRIVATE_KEY}}", key).splitlines():
        if line.strip().startswith("#"):
            continue
        if line.startswith(("Address", "DNS")) and "=" in line:
            keep = [x.strip() for x in line.split("=", 1)[1].split(",") if ":" not in x]
            line = line.split("=", 1)[0].rstrip() + " = " + ", ".join(keep)
        lines.append(line)
    return "\n".join(lines).rstrip() + "\n\n[Socks5]\nBindAddress = 127.0.0.1:%d\n" % port


def kp_read(entry, attr=None):
    """One attribute of a KeePass entry through `kp.py get --pipe cat`: never printed, never in argv."""
    cmd = [sys.executable, kp_script(), "get", entry]
    if attr:
        cmd += ["-a", attr]
    cmd += ["--pipe", "cat"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        die("could not read kp://%s: %s" % (entry, exc))
    if r.returncode != 0:
        die("could not read kp://%s: %s" % (entry, (r.stderr or "").strip() or "kp.py exited %d" % r.returncode))
    return r.stdout


def asset_name(system, machine):
    osname = {"Linux": "linux", "Darwin": "darwin"}.get(system)
    arch = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(machine.lower())
    if not osname or not arch:
        return None
    return "wireproxy_%s_%s.tar.gz" % (osname, arch)


def install():
    """Fetch the pinned wireproxy release for this OS and CPU, checked against the release checksums."""
    name = asset_name(platform.system(), platform.machine())
    if not name:
        die("no wireproxy build for %s %s" % (platform.system(), platform.machine()))
    sums = urllib.request.urlopen(WP_RELEASES + "checksums.txt", timeout=30).read().decode()
    want = next((l.split()[0] for l in sums.splitlines() if l.endswith(name)), None)
    blob = urllib.request.urlopen(WP_RELEASES + name, timeout=120).read()
    if not want or hashlib.sha256(blob).hexdigest() != want:
        die("checksum mismatch for %s, not installed" % name)
    os.makedirs(WP_DIR, exist_ok=True)
    tgz = os.path.join(WP_DIR, name)
    with open(tgz, "wb") as fh:
        fh.write(blob)
    with tarfile.open(tgz) as t:
        member = t.getmember("wireproxy")
        if not member.isfile():
            die("unexpected archive layout in %s" % name)
        t.extract(member, WP_DIR)
    os.remove(tgz)
    target = os.path.join(WP_DIR, "wireproxy")
    os.chmod(target, 0o755)
    if platform.system() == "Darwin":  # downloaded binaries carry the quarantine flag
        subprocess.run(["xattr", "-d", "com.apple.quarantine", target], capture_output=True)
    print("wireproxy %s installed: %s" % (WP_VERSION, target))


def port_open(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def pidfile(name):
    return os.path.join(state_dir(), "%s.pid" % name)


def running(name):
    try:
        with open(pidfile(name)) as fh:
            pid = int(fh.read())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def public_ip(port):
    r = subprocess.run(["curl", "-s", "-m", "15", "--socks5-hostname", "127.0.0.1:%d" % port,
                        "https://ipinfo.io/json"], capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
        return "%s %s, %s (%s)" % (d.get("ip"), d.get("city"), d.get("country"), d.get("org"))
    except ValueError:
        return "no answer"


def write_private(path, body):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, body.encode())
    finally:
        os.close(fd)


def up(name, check_ip=True):
    exits = exits_or_die()
    if name not in exits:
        die("unknown exit %s; configured: %s" % (name, ", ".join(exits)))
    port = exits[name]
    if not os.path.exists(wireproxy_path()):
        install()
    if running(name) and port_open(port):
        print("%s already up: socks5://127.0.0.1:%d" % (name, port))
        return
    if port_open(port):
        die("port %d is taken by another program; give %s another port in VPN_PROXY_EXITS" % (port, name))
    os.makedirs(state_dir(), mode=0o700, exist_ok=True)
    entry = kp_entry(name, kp_prefix())
    notes = kp_read(entry, "Notes")
    key = kp_read(entry).strip()
    if not key:
        die("kp://%s has an empty password (the WireGuard private key)" % entry)
    try:
        body = render_config(notes, key, port)
    except ValueError as exc:
        die("kp://%s: %s" % (entry, exc))
    conf = os.path.join(state_dir(), "%s.conf" % name)
    write_private(conf, body)
    log = open(os.path.join(state_dir(), "%s.log" % name), "w")
    try:
        p = subprocess.Popen([wireproxy_path(), "-c", conf], stdout=log, stderr=log,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        with open(pidfile(name), "w") as fh:
            fh.write(str(p.pid))
        for _ in range(40):
            if port_open(port) or p.poll() is not None:
                break
            time.sleep(0.25)
        time.sleep(1)
    finally:
        if os.path.exists(conf):
            os.remove(conf)  # wireproxy has read it; the key never stays on disk
        log.close()
    if p.poll() is not None or not port_open(port):
        die("%s failed to start, see %s" % (name, os.path.join(state_dir(), "%s.log" % name)))
    line = "%s up: socks5://127.0.0.1:%d" % (name, port)
    print(line + (" -> " + public_ip(port) if check_ip else ""))


def down(which):
    exits = exits_or_die()
    names = list(exits) if which in (None, "all") else [which]
    for name in names:
        pid = running(name)
        if pid:
            os.kill(pid, signal.SIGTERM)
            print("%s down" % name)
        for f in (pidfile(name), os.path.join(state_dir(), "%s.conf" % name)):
            if os.path.exists(f):
                os.remove(f)


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    check_ip = "--no-ip" not in a
    a = [x for x in a if x != "--no-ip"]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = a[0]
    if cmd == "list":
        prefix = kp_prefix()
        for name, port in exits_or_die().items():
            print("%-10s socks5://127.0.0.1:%d  kp://%s" % (name, port, kp_entry(name, prefix)))
    elif cmd == "up":
        if len(a) < 2:
            die("usage: vpn.py up <exit>")
        up(a[1], check_ip)
    elif cmd == "down":
        down(a[1] if len(a) > 1 else "all")
    elif cmd == "status":
        any_up = False
        for name, port in exits_or_die().items():
            if running(name) and port_open(port):
                any_up = True
                print("%s up  socks5://127.0.0.1:%d%s" % (name, port, ("  " + public_ip(port)) if check_ip else ""))
        if not any_up:
            print("no exit running")
    elif cmd == "install":
        install()
    elif cmd == "ip":
        exits = exits_or_die()
        if len(a) < 2 or a[1] not in exits:
            die("usage: vpn.py ip <exit>; configured: %s" % ", ".join(exits))
        print(public_ip(exits[a[1]]))
    else:
        die(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
