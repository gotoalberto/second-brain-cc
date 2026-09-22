#!/usr/bin/env python3
"""kp — credentials for the Brain system. The only path to read and write passwords.

The vault NEVER stores credentials: it stores `kp://Group/Entry#password` references
that resolve against a local KeePass database (.kdbx) chosen by its owner at first run
(`kp.py init --db PATH`, or BRAIN_KP_DB). macOS and Linux.

  kp.py status                      state of the kdbx, the lock and the cache
  kp.py init --db PATH [--keyfile PATH] [--create [--no-password]]
                                    record (or create) the database this machine uses
  kp.py unlock [--ttl 365d]         arm the master cache for 365 days (to work remotely later)
  kp.py lock                        forget the cached master
  kp.py ls [group] [-R]             list entries (never secrets)
  kp.py search <text>
  kp.py get <entry> [-a attr] [--copy|--show|--pipe CMD]
  kp.py put <entry> [-u user] [--url U] [--notes N] [--generate|--ask] [-L n]
  kp.py set <entry> [...]           edit an existing entry
  kp.py ref <entry>                 print the kp:// reference to paste into a note

Invariants (do not break them when editing):
  1. The master never passes through argv, nor the environment, nor plaintext on disk.
     It goes from the prompt (or the OS keyring cache) into keepassxc-cli's stdin and dies there.
  2. A secret is never printed unless the user explicitly asks with `--show`. By default
     it goes to the clipboard or into another process's stdin: that way it never enters
     the transcript.
  3. Every write takes a backup first and verifies the database afterwards. If the
     database does not open after writing, the backup is restored automatically.
"""
import os, sys, re, time, json, shutil, socket, argparse, binascii, contextlib, subprocess, hashlib, tempfile, atexit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import brainlib as B
    STATE = B.STATE
except Exception:                                   # kp.py must work without the vault
    B = None
    STATE = os.path.join(os.path.expanduser("~"), ".claude", "state", "brain")

import kp_backend as KPB                            # backend resolution and argv translation
try:
    import machine_identity as MI                   # whose lock is it, beyond the hostname
except Exception:                                   # kp.py must work on its own
    MI = None

# The harness redirects state to a temp dir: that way no test writes (or deletes) backups
# backups under $HOME.
STATE = os.environ.get("BRAIN_KP_STATE") or STATE

# Where the database is: BRAIN_KP_DB, else what `kp.py init` recorded at first run in
# <state>/kp-config.json, else nowhere. There is no guessed default: a credential store is
# chosen by its owner, on a local disk or a synced folder of their choosing.
CONFIG   = os.path.join(STATE, "kp-config.json")


def load_config(path=None):
    """The first-run config ({"db", "keyfile", "group", "inbox"}); {} when missing or unreadable."""
    try:
        with open(path or CONFIG, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def resolve_db(environ, config):
    """The database path from the environment, then the first-run config; "" when neither names one."""
    raw = (environ.get("BRAIN_KP_DB") or "").strip() or str((config or {}).get("db") or "").strip()
    return os.path.expanduser(raw) if raw else ""


_CFG     = load_config()
DB       = resolve_db(os.environ, _CFG)
KEYFILE  = os.environ.get("BRAIN_KP_KEYFILE") or os.path.expanduser(str(_CFG.get("keyfile") or ""))
# A store may have no master at all: the key file is the whole key, the same trust model as
# an SSH private key. That is found out by trying once (see `keyfile_only`); this variable
# skips the probe on a machine where it is known and the probe would be wasted.
NO_PASSWORD = os.environ.get("BRAIN_KP_NO_PASSWORD") in ("1", "true", "yes")
# Backend and binary: kp_backend._resolve() (BRAIN_KP_BACKEND, then shutil.which(), then a
# short fallback list) is the single place that owns this precedence now; kp.py only adds its
# own long-standing BRAIN_KP_CLI override on top, and only for keepassxc-cli — kp_backend's
# own resolution already ran at ITS import (KPB.KIND / KPB.PATH), so this is the same
# precedence, relocated, not duplicated.
KIND     = KPB.KIND
CLI      = (os.environ.get("BRAIN_KP_CLI") or KPB.PATH) if KIND == "keepassxc" else KPB.PATH
SERVICE  = "second-brain-kdbx"
TTL_DEF  = 365 * 86400                             # 365 days from unlock, survives reboot
PROMPT_TIMEOUT = int(os.environ.get("BRAIN_KP_PROMPT_TIMEOUT") or 45)
NOPROMPT = os.environ.get("BRAIN_KP_NOPROMPT") in ("1", "true", "yes")
GROUP_DEF = os.environ.get("BRAIN_KP_GROUP") or str(_CFG.get("group") or "Brain")
BACKUPS  = os.path.join(STATE, "kp-backups")
# Inbox: the way to hand an agent a secret without writing it in the conversation. A folder
# the user drops a file into. Point BRAIN_KP_INBOX (or `inbox` in the config) at a synced
# folder to use it from another device.
INBOX    = (os.environ.get("BRAIN_KP_INBOX") or os.path.expanduser(str(_CFG.get("inbox") or ""))
            or os.path.join(STATE, "kp-inbox"))
EXPOSED = "[EXPOSED"
# The marker used to be written in Spanish. Changing the string outright made `kp.py audit`
# stopped seeing the ALREADY marked entries and answered "none compromised" — with
# genuinely compromised credentials inside. On READ both forms are accepted;
# only the new one is written.
EXPOSED_MARKS = ("[EXPOSED", "[EXPUESTO")
META     = os.path.join(STATE, "kp-cache.json")
MARK     = "kp1:"                                   # prefix disambiguating hex from text
# ~245 KB each, so 40 is ~10 MB — and it gives a burst of `mv` calls headroom
# without evicting the history down to a few days. It was 10, which at the
# observed write rate was a four-day window.
KEEP_BACKUPS = 40
# Another machine's lock whose host does not resolve on the network and has gone longer
# than this untouched
# is treated as stale. At 0 the automation is off and every lock needs a human hand.
LOCK_STALE_H = float(os.environ.get("BRAIN_KP_LOCK_STALE_H") or 12)
# kp.py writes a 4th line into its lock, this tag plus the machine key, so that a lock is
# judged by WHICH machine took it and not by hostname: two machines can share a hostname,
# and a kdbx in a synced folder shows both of them the same lock. Judged by hostname alone,
# a twin's dead pid read as our own dead process and the lock was cleared under a live write.
BRAIN_LOCK_TAG = "brain:"
# kp.py holds its lock for one write (backup, write, verify): well under a minute. A kp.py
# lock older than this is a killed process on whichever machine, whether or not it answers.
BRAIN_LOCK_STALE_S = float(os.environ.get("BRAIN_KP_BRAIN_LOCK_STALE_S") or 1800)

EXIT_NOMASTER = 4                                   # the agent can tell "master missing" apart
EXIT_LOCKED   = 5                                   # the database is open elsewhere
EXIT_NODB     = 6                                   # no database configured or found


def die(msg, code=1):
    sys.stderr.write("kp: %s\n" % msg)
    sys.exit(code)


def human_ttl(s):
    """'8h', '30m', '900' -> segundos."""
    s = str(s).strip().lower()
    m = re.match(r"^(\d+)\s*([smhd]?)$", s)
    if not m:
        die("invalid ttl: %s (use 900, 30m, 8h, 2d)" % s)
    n, u = int(m.group(1)), m.group(2)
    return n * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[u]


# ------------------------------------------------------------------ platform
PLATFORM = sys.platform


def cache_backend(platform, which, environ):
    """Where the cached master lives: "keychain" (macOS), "secret-tool" (Linux, libsecret) or "none".

    BRAIN_KP_CACHE_BACKEND forces one; the tests force "none" so no real keyring is touched."""
    forced = (environ.get("BRAIN_KP_CACHE_BACKEND") or "").strip()
    if forced in ("keychain", "secret-tool", "none"):
        return forced
    if platform == "darwin":
        return "keychain"
    return "secret-tool" if which("secret-tool") else "none"


def dialog_backend(platform, environ, which):
    """How the master is asked for: "osascript" (macOS), "zenity" (a Linux desktop) or "tty"."""
    if platform == "darwin":
        return "osascript"
    if (environ.get("DISPLAY") or environ.get("WAYLAND_DISPLAY")) and which("zenity"):
        return "zenity"
    return "tty"


def clipboard_commands(platform, environ, which):
    """(paste argv, copy argv) for this desktop, or (None, None) when there is no clipboard tool."""
    if platform == "darwin":
        return ["/usr/bin/pbpaste"], ["/usr/bin/pbcopy"]
    if environ.get("WAYLAND_DISPLAY") and which("wl-paste") and which("wl-copy"):
        return [which("wl-paste"), "--no-newline"], [which("wl-copy")]
    if which("xclip"):
        return ([which("xclip"), "-selection", "clipboard", "-o"],
                [which("xclip"), "-selection", "clipboard"])
    return None, None


def ping_command(platform, host, which):
    """One ICMP echo with a short wait: -W is milliseconds on macOS and seconds on Linux."""
    ping = which("ping") or "/sbin/ping"
    return [ping, "-c", "1", "-W", "1500" if platform == "darwin" else "2", host]


def db_ok(need_write=False):
    if not DB:
        die("no credential database configured on this machine.\n"
            "    Record one:  python3 _bin/kp.py init --db /path/to/your.kdbx [--create]\n"
            "    (the first run, integrations/first-run/setup.sh, asks for it), or set BRAIN_KP_DB.",
            EXIT_NODB)
    if not (os.path.exists(CLI) or shutil.which(CLI)):
        die("keepassxc-cli not found (macOS: brew install --cask keepassxc; Linux: the keepassxc "
            "package)", EXIT_NODB)
    if not os.path.exists(DB):
        die("the database does not exist: %s" % DB, EXIT_NODB)
    if need_write and not os.access(DB, os.W_OK):
        die("no write permission on %s" % DB, EXIT_NODB)


def lock_info():
    """KeePassXC leaves `.<name>.lock` beside the database: pid, user (the app), host, and on
    a 4th line the machine's unique id (Qt's QLockFile). kp.py writes the same shape with its
    own tag and the machine key on that 4th line."""
    p = os.path.join(os.path.dirname(DB), "." + os.path.basename(DB) + ".lock")
    if not os.path.exists(p):
        return None
    try:
        lines = open(p, errors="replace").read().split("\n")
        tag = lines[3].strip() if len(lines) > 3 else ""
        ours = tag.startswith(BRAIN_LOCK_TAG)
        return {"path": p, "pid": lines[0].strip(),
                "user": lines[1].strip() if len(lines) > 1 else "?",
                "host": lines[2].strip() if len(lines) > 2 else "?",
                "machine": tag[len(BRAIN_LOCK_TAG):] if ours else "",
                "qt_machine": "" if ours else tag,
                "age": int(time.time() - os.path.getmtime(p))}
    except Exception:
        return {"path": p, "pid": "?", "user": "?", "host": "?", "machine": "",
                "qt_machine": "", "age": -1}


def lock_path():
    return os.path.join(os.path.dirname(DB), "." + os.path.basename(DB) + ".lock")


def _host():
    return socket.gethostname().split(".")[0]


def _machine_key():
    """This machine's key (`<hostname>-<8hex>`), or the hostname when machine_identity is missing."""
    try:
        return MI.current_key() if MI else _host()
    except Exception:
        return _host()


def _machine_uuid():
    """The id KeePassXC writes into its lock: /etc/machine-id on Linux, IOPlatformUUID on macOS."""
    try:
        return MI.read_uuid(sys.platform, MI._run, open) if MI else ""
    except Exception:
        return ""


def _same_id(a, b):
    ha = re.sub(r"[^0-9a-f]", "", (a or "").lower())
    hb = re.sub(r"[^0-9a-f]", "", (b or "").lower())
    return bool(ha) and ha == hb


def _key_is_mine(value):
    """Does this kp.py lock key name this machine? machine_is_mine() accepts every form this
    machine has written, including one from before a rename. The bare hostname is the one form
    it accepts that a twin can also write, so it counts only while our own key is bare too."""
    mine = _machine_key()
    if MI is None:
        return value == mine
    if value.strip().casefold() == _host().casefold() and mine.casefold() != _host().casefold():
        return False
    try:
        return MI.machine_is_mine(value)
    except Exception:
        return value == mine


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return True                      # when in doubt, assume alive


def host_reach(host):
    """'responde' | 'mudo' | 'no-resuelve'. The only external evidence available about
    another machine's lock: its process table cannot be inspected from here."""
    if not host or host == "?":
        return "no-resolve"
    for cand in (host, host + ".local"):
        try:
            socket.setdefaulttimeout(2.0)
            socket.gethostbyname(cand)
        except Exception:
            continue
        p = subprocess.run(ping_command(PLATFORM, cand, shutil.which),
                           capture_output=True)
        return "answers" if p.returncode == 0 else "mute"
    return "no-resolve"


def lock_state():
    """Classify the lock from the available evidence, without guessing."""
    lk = lock_info()
    if not lk:
        return {"status": "free"}
    if lk.get("machine"):
        # Written by kp.py: the machine key settles whose it is, hostname twins included.
        own = _key_is_mine(lk["machine"])
    elif lk.get("qt_machine"):
        # KeePassXC names the machine too: compare it with this machine's own id.
        own = _same_id(lk["qt_machine"], _machine_uuid())
    else:
        # Only a hostname to go on. Two machines can share it, so a dead pid proves nothing:
        # the lock is ours only while its pid is alive here. A dead one of ours is then
        # cleared by hand (`kp.py locks --clear`) or by age, never by guessing whose it was.
        own = lk["host"] == _host() and pid_alive(lk["pid"])
    if own:
        lk["reach"] = "local"
        lk["status"] = "own-alive" if pid_alive(lk["pid"]) else "own-dead"
    else:
        lk["reach"] = host_reach(lk["host"])
        lk["status"] = "foreign-alive" if lk["reach"] == "answers" else "foreign-doubtful"
    lk["hours"] = lk["age"] / 3600.0 if lk["age"] >= 0 else -1
    return lk


def lock_who(lk):
    return "%s@%s (pid %s, for %.1f h)" % (lk["user"], lk.get("machine") or lk["host"],
                                           lk["pid"], lk["hours"])


def lock_stale(lk):
    """Return the reason if the lock can be treated as dead, or None.

    Only the provable or the very improbable is automated:
      - a process on this machine that no longer exists: direct proof,
      - a kp.py lock from another machine older than any kp.py write lasts (30 min),
      - a machine whose name does not even resolve and has been idle half a day.
    A lock from a machine that answers is NEVER cleared automatically: it may be real,
    and two clients writing at once clobber each other."""
    if lk["status"] == "own-dead":
        return "process %s belonged to this machine and no longer exists" % lk["pid"]
    if (lk.get("machine") and lk["status"].startswith("foreign")
            and lk["age"] > BRAIN_LOCK_STALE_S):
        return ("kp.py on %s took it %.0f min ago, and a kp.py write never lasts that long"
                % (lk["machine"], lk["age"] / 60.0))
    if (lk["status"] == "foreign-doubtful" and LOCK_STALE_H > 0
            and lk["hours"] > LOCK_STALE_H):
        return ("\"%s\" does not resolve on this network and the lock has been idle %.1f h"
                % (lk["host"], lk["hours"]))
    return None


def lock_clear(lk, reason):
    """Clear the lock and record it: if a conflict shows up later, there is a trail."""
    try:
        os.remove(lock_path())
    except FileNotFoundError:
        pass
    except Exception as e:
        die("could not clear the lock: %s" % e, EXIT_LOCKED)
    meta = _meta_read()
    hist = meta.setdefault("locks_cleared", [])
    hist.append({"when": time.time(), "who": lock_who(lk), "reason": reason,
                 "status": lk["status"]})
    meta["locks_cleared"] = hist[-5:]
    _meta_write(meta)
    sys.stderr.write("kp: stale lock cleared — %s\n    (held by %s)\n"
                     % (reason, lock_who(lk)))


def ask_confirm(title_, body, button):
    """Confirmation through the same channel as the master: a dialog on the machine's screen
    (osascript, zenity) or the terminal.

    Remotely nobody sees it and it times out; there, the confirmation is typing --force."""
    if NOPROMPT:
        return False
    how = dialog_backend(PLATFORM, os.environ, shutil.which)
    if how == "zenity":
        try:
            p = subprocess.run(["zenity", "--question", "--title", title_, "--text", body,
                                "--ok-label", button, "--timeout", str(PROMPT_TIMEOUT)],
                               capture_output=True, text=True, timeout=PROMPT_TIMEOUT + 15)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return p.returncode == 0
    if how == "tty":
        if not sys.stdin.isatty():
            return False
        try:
            return input("%s\n%s\nType yes to %s: " % (title_, body, button)).strip().lower() == "yes"
        except Exception:
            return False
    esc = lambda t: t.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    script = ['set r to display dialog "%s" with title "%s" buttons {"Cancel", "%s"} '
              'default button "Cancel" with icon caution giving up after %d'
              % (esc(body), esc(title_), esc(button), PROMPT_TIMEOUT),
              'if gave up of r then error number -128',
              'return button returned of r']
    cmd = ["/usr/bin/osascript"]
    for line in script:
        cmd += ["-e", line]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=PROMPT_TIMEOUT + 15)
    except subprocess.TimeoutExpired:
        return False
    return p.returncode == 0 and p.stdout.strip() == button


def guard_lock(force):
    """Writing while the database is open in another client loses changes: whoever saves
    afterwards clobbers the other. Hence a write stops at a lock — unless it can be
    proved that nobody holds that lock any more.

    KeePassXC's `.lock` file convention (pid/user/host beside the database) is not something
    kpcli/File::KDBX writes or reads, so there is nothing here to probe under that backend.
    `cmd_put`, `cmd_mv` and `cmd_rmdir` all call this unconditionally before they write, so
    dying here would make every kpcli write refuse outright — defeating the whole point of
    the translated add/edit/mkdir. The skip is LOGGED rather than silent (never a quiet
    no-op): the dedicated `kp.py locks` command, which exists only to probe or clear a lock
    and nothing depends on it succeeding, is where this limitation is surfaced to the user —
    see cmd_locks below.
    """
    if KIND == "kpcli":
        _B_log("kp", "guard_lock-skip-kpcli")
        return
    lk = lock_state()
    if lk["status"] == "free":
        return
    reason = lock_stale(lk)
    if reason:
        lock_clear(lk, reason)
        return
    if force:
        sys.stderr.write("kp: WARNING — writing while the database is open by %s.\n"
                         "    If that client saves afterwards, whatever I write is lost.\n"
                         "    There is a prior backup at %s\n" % (lock_who(lk), BACKUPS))
        return
    die("the database is open by %s.\n"
        "    State: %s (%s).\n"
        "    Close it in KeePassXC, or inspect the lock with:  kp.py locks\n"
        "    If you know it is stale:  kp.py locks --clear"
        % (lock_who(lk), lk["status"], lk["reach"]), EXIT_LOCKED)


@contextlib.contextmanager
def write_lock():
    """Serialise writes and warn the other clients while it lasts.

    Two Claude sessions at once are the norm on this machine, and keepassxc-cli does not
    take the lock on its own: without this, two simultaneous `put`s clobber each other."""
    os.makedirs(STATE, exist_ok=True)
    import fcntl
    fh = open(os.path.join(STATE, "kp.write.lock"), "w")
    fcntl.flock(fh, fcntl.LOCK_EX)
    own = False
    try:
        # `if not os.path.exists(): open(..., "w")` was a race: between the two
        # calls another client fitted in, and whoever arrived second rewrote the lock
        # foreign one with its own pid and cleared it on exit, leaving the first writing to
        # kdbx with no lock. The flock above only serialises this machine; the .lock
        # lives on the SMB share and every machine sees it. O_EXCL is one single
        # operation: either you place it,
        # or it was already there. (Verified exclusive over an SMB share.)
        try:
            fd = os.open(lock_path(), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            pass                     # it belongs to someone else: neither clobbered nor cleared in the finally
        except Exception:
            pass                     # the lock is a courtesy; it does not block the write
        else:
            # `own` is marked BEFORE writing on purpose: an empty lock does not
            # nobody claims —lock_info reads it with no host, guard_lock treats it as foreign and
            # blocks every write until the reaper declares it stale, 12 h—.
            # Marking it up front, the finally clears it even if the write is cut short.
            own = True
            try:
                os.write(fd, ("%d\n%s\n%s\n%s%s\n" % (os.getpid(),
                                                      os.environ.get("USER", "?"),
                                                      _host(), BRAIN_LOCK_TAG,
                                                      _machine_key())).encode())
            except Exception:
                pass
            finally:
                try:
                    os.close(fd)
                except Exception:
                    pass
        yield
    finally:
        if own:
            try:
                os.remove(lock_path())
            except Exception:
                pass
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


# ------------------------------------------------------------------ maestra
def boot_id(platform=None, proc_path="/proc/sys/kernel/random/boot_id"):
    """Identifies the machine's current boot: kern.boottime on macOS, the kernel's boot_id on Linux.

    A master cache armed without a TTL expires on reboot. Tying it to boot is the only thing
    that separates "the machine has been on since you typed it" from "someone rebooted and
    nobody has authorised anything since".
    """
    if (platform or PLATFORM) == "darwin":
        try:
            out = subprocess.run(["/usr/sbin/sysctl", "-n", "kern.boottime"],
                                 capture_output=True, text=True).stdout
            m = re.search(r"sec\s*=\s*(\d+)", out)
            if m:
                return m.group(1)
        except Exception:
            pass
        return ""
    try:
        with open(proc_path, encoding="utf-8") as fh:
            return fh.read().strip()
    except Exception:
        return ""


def _acct():
    return hashlib.sha256(os.path.realpath(DB).encode()).hexdigest()[:16]


def _meta_read():
    try:
        return json.load(open(META))
    except Exception:
        return {}


def _meta_write(d):
    try:
        os.makedirs(STATE, exist_ok=True)
        tmp = META + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, META)
    except Exception:
        pass


def cache_fresh(meta):
    """(fresh, reason). Without `exp` the cache lives until the next reboot."""
    if not meta:
        return False, "no cache"
    if meta.get("exp"):
        return (time.time() < meta["exp"]), "expired by time"
    b = boot_id()
    if not b:
        return False, "cannot read the boot time"
    if meta.get("boot") != b:
        return False, "the machine has rebooted"
    return True, ""


def cache_get():
    """Read the master from the Keychain if the cache is still fresh."""
    meta = _meta_read().get(_acct()) or {}
    fresh, _ = cache_fresh(meta)
    if not fresh:
        if meta:
            cache_del()          # after a reboot, ignoring it is not enough: it is deleted
        return None
    backend = cache_backend(PLATFORM, shutil.which, os.environ)
    if backend == "none":
        return None
    if backend == "secret-tool":
        cmd = ["secret-tool", "lookup", "service", SERVICE, "account", _acct()]
    else:
        cmd = ["/usr/bin/security", "find-generic-password", "-w", "-s", SERVICE, "-a", _acct()]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    raw = p.stdout
    if raw.endswith("\n"):
        raw = raw[:-1]
    if re.match(r"^(?:[0-9a-fA-F]{2})+$", raw):      # security returns hex if we stored it with -X
        try:
            raw = binascii.unhexlify(raw).decode("utf-8")
        except Exception:
            return None
    return raw[len(MARK):] if raw.startswith(MARK) else None


def cache_put(pw, ttl=TTL_DEF):
    """Stores the master in the Keychain. The value goes in on `security -i` stdin,
    never through argv: argv is visible with `ps` while the process lives.

    The cache expires `ttl` seconds after it is armed (fixed window, not sliding) and
    survives reboots. With a falsy `ttl` it lasts until the machine reboots instead."""
    hexpw = binascii.hexlify((MARK + pw).encode("utf-8")).decode()
    backend = cache_backend(PLATFORM, shutil.which, os.environ)
    if backend == "none":
        return
    try:
        if backend == "secret-tool":
            p = subprocess.run(["secret-tool", "store", "--label", "second-brain kdbx master",
                                "service", SERVICE, "account", _acct()],
                               input=hexpw, capture_output=True, text=True, timeout=15)
        else:
            cmd = "add-generic-password -U -s %s -a %s -l %s -j %s -X %s\n" % (
                SERVICE, _acct(), SERVICE, "second-brain-kdbx-master", hexpw)
            p = subprocess.run(["/usr/bin/security", "-i"], input=cmd,
                               capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        p = None
    if p is None or p.returncode != 0:
        sys.stderr.write("kp: warning — could not cache the master in the OS keyring\n")
        return
    meta = _meta_read()
    entry = {"db": DB, "boot": boot_id(), "since": time.time()}
    if ttl:
        entry.update(exp=time.time() + ttl, ttl=ttl)
    meta[_acct()] = entry
    _meta_write(meta)


def cache_del():
    backend = cache_backend(PLATFORM, shutil.which, os.environ)
    try:
        if backend == "secret-tool":
            subprocess.run(["secret-tool", "clear", "service", SERVICE, "account", _acct()],
                           capture_output=True, text=True, timeout=15)
        elif backend == "keychain":
            subprocess.run(["/usr/bin/security", "delete-generic-password",
                            "-s", SERVICE, "-a", _acct()],
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        pass
    meta = _meta_read()
    meta.pop(_acct(), None)
    _meta_write(meta)


def ask_dialog():
    """A dialog with a hidden field: osascript on macOS, zenity on a Linux desktop, None
    elsewhere (the caller falls back to the terminal). The value lands in a variable of this
    process: it does not pass through the agent's transcript."""
    if NOPROMPT:
        return None
    how = dialog_backend(PLATFORM, os.environ, shutil.which)
    if how == "zenity":
        try:
            p = subprocess.run(["zenity", "--password", "--title", "Brain · KeePass",
                                "--timeout", str(PROMPT_TIMEOUT)], capture_output=True, text=True,
                               timeout=PROMPT_TIMEOUT + 15)
        except (OSError, subprocess.TimeoutExpired):
            return None
        out = p.stdout if p.returncode == 0 else ""
        return (out[:-1] if out.endswith("\n") else out) or None
    if how != "osascript":
        return None
    script = [
        'set r to display dialog "Master password for the credential database\n\n'
        'The Brain system asks for it to open your KeePass database." '
        'with title "Brain · KeePass" default answer "" with hidden answer '
        'with icon caution giving up after %d' % PROMPT_TIMEOUT,
        'if gave up of r then error number -128',
        'return text returned of r']
    cmd = ["/usr/bin/osascript"]
    for line in script:
        cmd += ["-e", line]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=PROMPT_TIMEOUT + 15)
    except subprocess.TimeoutExpired:
        return None
    if p.returncode != 0:
        return None
    out = p.stdout
    return out[:-1] if out.endswith("\n") else out


def get_master(interactive=True):
    pw = cache_get()
    if pw:
        return pw, True
    if not interactive:
        return None, False
    pw = ask_dialog()
    if not pw and not NOPROMPT and sys.stdin.isatty():
        import getpass
        try:
            pw = getpass.getpass("Master for %s: " % os.path.basename(DB))
        except Exception:
            pw = None
    if not pw:
        die("I do not have the master and nobody answered the prompt%s.\n"
            "    At the machine: repeat and answer it.\n"
            "    Headless (a scheduled job, a remote session): the prompt cannot reach you.\n"
            "    Arm the cache first, at the machine:\n"
            "        python3 ~/Brain/_bin/kp.py unlock        (lasts 365 days)\n"
            "    The master must never be typed into the chat."
            % (" (headless: BRAIN_KP_NOPROMPT)" if NOPROMPT else ""), EXIT_NOMASTER)
    return pw, False


# ------------------------------------------------------------------ cli
CLI_TIMEOUT = 60          # cap on every keepassxc-cli call


# ------------------------------------------------------- the working copy
#
# `keepassxc-cli` cannot read the .kdbx over `smbfs`. It is specifically it: `head`,
# `cp` and `python3` read the very same file with no trouble, a path that does not
# exist gives "not found" (so the volume answers), and a local copy —even `cp -p`,
# xattrs and all— opens normally. Most likely it maps the file into memory and smbfs
# does not give it what it expects. Unmounting and remounting does not fix it.
#
# The symptom is cruel: the dialog appears, the master is right, and it dies with
# `cannot open the database:` AND AN EMPTY MESSAGE. Whoever is typing concludes their
# password is wrong. That is why this is not worked around from outside any more.
#
# So when the direct open fails for a reason that is NOT the password, the .kdbx is
# copied to a private local directory and `keepassxc-cli` is pointed at the copy.
# Reads end there. A write goes back over the real file, which by then already has its
# backup taken and its `verify_or_restore` waiting behind it.
#
# What does NOT move to the copy: the lock, the backups, the mount checks, and above
# all the Keychain cache key, which is the hash of the database path. Hashing a
# temporary path would throw away the cached master on every single run.
DBF = [DB]

_WORKDIR = []

#: Subcommands that modify the database. Everything else only reads.
_MUTA = {"add", "edit", "rm", "mv", "mkdir", "rmdir", "import",
         "attachment-import", "attachment-rm"}

_BAD_KEY = r"(?i)invalid credentials|wrong key|could not be decrypted"

#: First four bytes of every KDBX (sig1 = 0x9AA2D903, little-endian). KDBX 2, 3 and 4
#: all share them.
_KDBX_MAGIC = b"\x03\xd9\xa2\x9a"

#: No real database is this small. The one that got written over the real file was
#: eleven bytes long, so the floor only has to be above "obviously not a database".
_KDBX_MIN = 1024


def looks_like_kdbx(path):
    """Does this file at least LOOK like a database? Cheap, and it is not a decryption
    check: it only tells apart a .kdbx from something that plainly is not one."""
    try:
        if os.path.getsize(path) < _KDBX_MIN:
            return False
        with open(path, "rb") as f:
            return f.read(4) == _KDBX_MAGIC
    except Exception:
        return False


def sanctioned_source(src):
    """Where is this coming from? The store is overwritten by its own working copy or
    by its own backup, and by nothing else.

    `looks_like_kdbx` asks WHAT is being written. This asks WHERE IT CAME FROM, and
    that is the question an earlier accident actually failed: the fixture that
    landed on the real database was eleven bytes, so the content check catches that one — but a
    fixture that had looked like a database would have gone straight through, and the
    harness now builds fixtures that look exactly like databases on purpose.

    There are exactly two legitimate origins: the working copy we made under
    `_WORKDIR`, and a backup we took under `BACKUPS`. Every real caller uses one of
    them (`push_back` the first, `verify_or_restore` the second). A file anywhere else
    belongs to somebody else, whatever its magic bytes say."""
    try:
        d = os.path.realpath(os.path.dirname(src))
    except Exception:
        return False
    for w in _WORKDIR:
        try:
            if d == os.path.realpath(w):
                return True
        except Exception:
            continue
    try:
        return d == os.path.realpath(BACKUPS)
    except Exception:
        return False


def write_over_db(src, why):
    """The ONLY way anything is allowed to land on the real database.

    A real .kdbx was once left holding eleven bytes reading `GOOD-BACKUP`. A test
    harness had pointed the module-level `DB` at a temporary file to exercise the
    restore branch, but left `DBF[0]` pointing at the real database: with the two
    roles swapped, `refresh_work_copy()` read `DBF[0] != DB` and copied the eleven-byte
    fixture ONTO the credential store. Nothing checked what was being written, so
    nothing complained.

    The lesson is not "be careful with the fixture" — it is that a path that overwrites
    the credential store must not trust its own arguments. Any write that does not look
    like a database is refused here, whoever asked for it and for whatever reason."""
    if not looks_like_kdbx(src):
        die("refusing to write over %s with %s (%s): it is not a database.\n"
            "    This guard exists because a test fixture once landed there."
            % (DB, src, why), EXIT_NODB)
    if not sanctioned_source(src):
        die("refusing to write over %s with %s (%s): it is neither our working copy\n"
            "    nor one of our backups. The credential store is only ever overwritten\n"
            "    by its own copy or its own backup, whatever the file looks like."
            % (DB, src, why), EXIT_NODB)
    shutil.copy2(src, DB)


def work_copy():
    """A local copy of the .kdbx, private and shredded on the way out."""
    if DBF[0] != DB:
        return DBF[0]
    try:
        d = tempfile.mkdtemp(prefix="kp-")
        os.chmod(d, 0o700)
        dst = os.path.join(d, os.path.basename(DB))
        shutil.copy2(DB, dst)
    except Exception:
        return None
    _WORKDIR.append(d)
    DBF[0] = dst
    atexit.register(_drop_work_copy)
    return dst


def _drop_work_copy():
    for d in _WORKDIR:
        try:
            shred(os.path.join(d, os.path.basename(DB)))
            os.rmdir(d)
        except Exception:
            pass
    del _WORKDIR[:]


def push_back():
    """Returns the written copy to the real database. Only after a write.

    This is where a new credential reaches the real database, which may sit on a network or
    synced drive where concurrent writes can corrupt it. It happens immediately after the
    write, not at exit, so the file on the drive is the one that holds the secret and
    the local copy is never the only place it lives."""
    if DBF[0] == DB:
        return
    write_over_db(DBF[0], "push_back after a write")


def refresh_work_copy():
    """After restoring a backup over the real database, the copy is stale.

    `DB` is the drive and `DBF[0]` is the local copy — never the other way round. When
    a caller swaps them (a test pointing `DB` at a temporary file and forgetting
    `DBF[0]`), this used to copy the temporary file onto the credential store. It now
    refuses instead: a copy that is not under one of OUR working directories is not a
    working copy, and is not written to."""
    if DBF[0] == DB:
        return
    if not any(os.path.dirname(DBF[0]) == d for d in _WORKDIR):
        return                                # not ours: do not touch it
    shutil.copy2(DB, DBF[0])


def _probe(pw, path, no_password=None):
    """Does the master open this file at all? `unlocked()` calls this directly, ahead of
    every command, so it has to speak whichever backend is in use — the "ls" translation is
    always available (one of the six), so this doubles as the kpcli backend's master check.
    """
    if KIND == "kpcli":
        return KPB.run(KIND, CLI, ["ls"] + _key_args(no_password) + [path], path, pw or "",
                       timeout=CLI_TIMEOUT, pwfile_dir=os.path.join(STATE, "kp-pwfiles"))
    return subprocess.run([CLI, "ls", "-q"] + _key_args(no_password) + [path],
                          timeout=CLI_TIMEOUT, input=_master_stdin(pw, no_password),
                          capture_output=True, text=True)


#: Unknown (None), yes or no. Once decided it shapes every argv below, so it is decided once.
_NOPW = [True if (NO_PASSWORD and KEYFILE) else None]


def _key_args(no_password=None):
    """The flags that say how the database is keyed, for every call that opens it.

    `--no-password` is what stops keepassxc-cli waiting on stdin for a master the store does
    not have; kp_backend reads the same flag to leave the kpcli helper's password empty."""
    args = ["-k", KEYFILE] if KEYFILE else []
    if KEYFILE and (_NOPW[0] if no_password is None else no_password):
        args.append("--no-password")
    return args


def _master_stdin(master, no_password=None):
    """What goes on stdin ahead of anything else: the master and a newline, or nothing at all
    for a keyfile-only store. A bare newline there would be read as the next secret."""
    if KEYFILE and (_NOPW[0] if no_password is None else no_password):
        return ""
    return (master or "") + "\n"


def keyfile_only():
    """Is the key file the WHOLE key of this store?

    A store meant for a headless machine (no dialog, no keyring) can be created with a key file
    and no password: possession of the file is the access. Asking for a master there would end
    in EXIT_NOMASTER and send whoever reads it looking for a password nobody ever set.

    Answered by trying once with `--no-password`, not by configuration, so a store with a
    password AND a key file keeps working on the same code path. BRAIN_KP_NO_PASSWORD=1 skips
    the probe."""
    if not KEYFILE:
        return False
    if _NOPW[0] is None:
        p = _probe("", DBF[0], no_password=True)
        if (p.returncode != 0 and DBF[0] == DB
                and not re.search(_BAD_KEY, (p.stderr or p.stdout or ""))):
            local_copy = work_copy()       # the same fallback unlocked() takes for a drive
            if local_copy:
                p = _probe("", local_copy, no_password=True)
        _NOPW[0] = p.returncode == 0
    return _NOPW[0]


def probe_real(pw):
    """Does the file that is now ON THE DRIVE open?

    It cannot be asked directly when the working copy is in play: `keepassxc-cli`
    could not read that drive, which is the whole reason the copy exists, and asking
    anyway answers «it does not open» to every single write. That answer looks exactly
    like a corrupted database, and the caller then restores a backup over a write that
    was perfectly fine.

    So the bytes that landed are brought back into a fresh temporary file and that is
    what gets opened. It is a round trip, and it is the only version of this check that
    actually checks something: not the copy that was written, but the drive."""
    if DBF[0] == DB:
        return _probe(pw, DB)
    d = tempfile.mkdtemp(prefix="kp-check-")
    os.chmod(d, 0o700)
    testigo = os.path.join(d, os.path.basename(DB))
    try:
        shutil.copy2(DB, testigo)
        return _probe(pw, testigo)
    finally:
        try:
            shred(testigo)
            os.rmdir(d)
        except Exception:
            pass


def _B_log(channel, event, **fields):
    """kp.py must work even without brainlib: the import goes inside here."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import brainlib
        brainlib.log(channel, event, **fields)
    except Exception:
        pass


def cli(args, master, extra_stdin="", check=True):
    """Runs the backend for one call — keepassxc-cli (unchanged) or kp_backend.run() for the
    kpcli backend. This is the single place that knows the difference between the two, the
    same way it was already the single place that knew the difference between `DB` and the
    working copy.
    """
    if KIND == "kpcli":
        return _cli_kpcli(args, master, extra_stdin, check)
    cmd = [CLI, args[0], "-q"] + _key_args()
    # The call sites name `DB`, which is the real database. What is handed to
    # `keepassxc-cli` is whatever it can actually open, and here is the single place
    # that knows the difference.
    cmd += [DBF[0] if a == DB else a for a in args[1:]]
    stdin = _master_stdin(master) + extra_stdin
    _t0 = time.time()
    try:
        # ALWAYS capped. The database lives on an SMB mount: if the network drops halfway
        # of a read, `keepassxc-cli` waits and `kp.py` waits with it, saying nothing. The
        # harness already shielded itself with its own 45 s timeout; real usage had none.
        # A process that can hang forever ends up hanging forever.
        p = subprocess.run(cmd, input=stdin, capture_output=True, text=True,
                           timeout=CLI_TIMEOUT)
    except subprocess.TimeoutExpired:
        _B_log("kp", args[0], secs="%.0f" % CLI_TIMEOUT, rc="timeout")
        die("keepassxc-cli %s did not answer in %ds. If %s is on a network or synced\n"
            "    drive, check that the drive responds and try again."
            % (args[0], CLI_TIMEOUT, DB), EXIT_NODB)
    # Metadata only: which subcommand, how long it took and whether it worked. Not the
    # master, not
    # the secret, nor the output —which carries the value when `show` is asked for.
    _B_log("kp", args[0], secs="%.2f" % (time.time() - _t0), rc=p.returncode,
           entry=args[-2] if len(args) > 2 else "")
    if check and p.returncode != 0:
        err = (p.stderr or p.stdout or "").strip()
        if re.search(r"(?i)invalid credentials|wrong key|could not be decrypted", err):
            cache_del()
            die("wrong master password (cache discarded). Repeat the command.", EXIT_NOMASTER)
        die("keepassxc-cli %s failed: %s" % (args[0], err[:400]))
    if p.returncode == 0 and args[0] in _MUTA:
        push_back()
    return p


def _cli_kpcli(args, master, extra_stdin, check):
    """The kpcli branch of cli(): kp_backend.run() straight against the real database — the
    working-copy trick above the module (`DBF`, `work_copy()`) exists only for keepassxc-cli's
    own smbfs quirk; File::KDBX has no such limitation, so there is no copy to make here.
    Only the six subcommands kp_backend.translate() covers succeed; anything else dies with a
    clear message naming the operation, per the plan's scope cut for this backend.
    """
    _t0 = time.time()
    try:
        p = KPB.run(KIND, CLI, [args[0]] + _key_args() + list(args[1:]), DB, master or "",
                    stdin_extra=extra_stdin, timeout=CLI_TIMEOUT,
                    pwfile_dir=os.path.join(STATE, "kp-pwfiles"))
    except KPB.Unsupported as exc:
        die("kp_backend: \"%s\" is not one of the operations available with the kpcli "
            "backend (only ls, search, show, mkdir, add, edit are). Switch to keepassxc-cli "
            "for this, or run it by hand on a machine where KeePassXC is installed."
            % exc, EXIT_NODB)
    except subprocess.TimeoutExpired:
        _B_log("kp", args[0], secs="%.0f" % CLI_TIMEOUT, rc="timeout")
        die("kp_kdbx.pl %s did not answer in %ds." % (args[0], CLI_TIMEOUT), EXIT_NODB)
    _B_log("kp", args[0], secs="%.2f" % (time.time() - _t0), rc=p.returncode,
           entry=args[-2] if len(args) > 2 else "")
    if check and p.returncode != 0:
        err = (p.stderr or p.stdout or "").strip()
        if re.search(r"(?i)cannot open the database", err):
            cache_del()
            die("wrong master password (cache discarded). Repeat the command.", EXIT_NOMASTER)
        die("kp_kdbx.pl %s failed: %s" % (args[0], err[:400]))
    return p


def cli_clip(entry, attr, seconds, master):
    """Copies to the clipboard WITHOUT blocking for the `seconds` of waiting.

    `keepassxc-cli clip` copies and then sleeps until it clears the clipboard. With
    the default value that is **20 seconds stopped** on every `get` and every `put`,
    which is the user's time spent waiting for a process that already did its
    work. In the harness that was 200 s out of 255 — 78% of the total.

    Here it is launched detached (`start_new_session`) and waited on only long enough to
    see whether it fails outright. If it is still alive past that margin, it copied fine
    and is counting down: it is left there and the clipboard clears itself.

    keepassxc-cli only: `clip` is outside the six subcommands kp_backend.translate() covers,
    and there is no equivalent to shell out to for kpcli. Called directly (cmd_get's default),
    this dies with a clear message. cmd_put's own internal call (after generating a NEW
    password) checks KIND itself first and skips this instead of dying mid-write — see there.
    """
    if KIND == "kpcli":
        die("kp_backend: clipboard copying is not available with the kpcli backend. Use "
            "`kp.py get <entry> --show` or `--pipe <cmd>` instead.", EXIT_NODB)
    cmd = [CLI, "clip", "-q"] + _key_args()
    cmd += ["-a", attr, DBF[0], entry, str(seconds)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        proc.stdin.write(_master_stdin(master)); proc.stdin.flush()
    except Exception:
        pass
    try:
        # Margin so a failure (wrong master, missing entry) shows up here.
        _, err = proc.communicate(timeout=1.5)
        if proc.returncode != 0:
            return False, (err or "").strip()[:200]
        return True, ""          # already finished: 0 s wait or immediate clipboard
    except subprocess.TimeoutExpired:
        return True, ""          # still sleeping with the secret already copied


def unlocked(interactive=True):
    """Returns a master already validated against the database, or None when the store has none
    (the key file is the whole key: nothing to ask for and nothing to cache)."""
    db_ok()
    if keyfile_only():
        return None
    # The local copy stays a FALLBACK, taken only when the direct read fails. Making it
    # unconditional was tried once and reverted the same hour: the copy is taken
    # while resolving the master, which happens BEFORE `write_lock()`, so three
    # simultaneous `put`s each copied the database, each wrote its own entry, and each
    # pushed back over the last — two credentials lost with nothing reporting it.
    # the test harness caught it ("3 simultaneous writes: all land and none corrupts").
    for attempt in (1, 2):
        pw, from_cache = get_master(interactive)
        if pw is None:
            die("no master", EXIT_NOMASTER)
        p = _probe(pw, DBF[0])
        # A failure that does not mention the key is not the user's fault. Before
        # blaming the password —which is what the empty message ends up doing— the
        # local copy is tried.
        if (p.returncode != 0 and DBF[0] == DB
                and not re.search(_BAD_KEY, (p.stderr or p.stdout or ""))):
            local_copy = work_copy()
            if local_copy:
                p = _probe(pw, local_copy)
        if p.returncode == 0:
            if not from_cache:
                cache_put(pw, _ttl_wanted())
            return pw
        if from_cache and attempt == 1:
            # Only a REJECTED master means the cache is stale. Anything else — a network
            # mount stalling, the file briefly busy, the backend erroring for its own
            # reasons — says nothing about the password, and deleting the cache over it
            # turns one transient I/O blip into a prompt for every session afterward.
            # _BAD_KEY already draws this distinction; it just was not consulted here.
            if re.search(_BAD_KEY, (p.stderr or p.stdout or "")):
                cache_del()                   # genuinely stale master: ask again
                continue
            continue                          # transient failure: keep the cache, retry
        die("cannot open the database: %s" % (p.stderr or p.stdout).strip()[:300],
            EXIT_NOMASTER)


_TTL = [TTL_DEF]


def _ttl_wanted():
    return _TTL[0]


# ------------------------------------------------------------------ backups
def backup():
    os.makedirs(BACKUPS, exist_ok=True)
    os.chmod(BACKUPS, 0o700)
    dst = os.path.join(BACKUPS, "%s-%s.kdbx" % (
        os.path.basename(DB)[:-5], time.strftime("%Y%m%d-%H%M%S")))
    shutil.copy2(DB, dst)
    os.chmod(dst, 0o600)
    # Only OUR OWN rotating copies count towards the ring and are eligible for eviction.
    # A hand-named milestone (`keepass-preadjuntos-20260821-120216.kdbx`) matched the old
    # `endswith(".kdbx")` test, so it sat permanently in the kept tail: never evicted, but
    # consuming a slot for ever. The ring was nominally 10 and effectively 9.
    #
    # If the kdbx is ever renamed, the previous stem's copies stop rotating and become
    # milestones. That is the safe direction to fail: keeping too much beats deleting a
    # backup nobody asked to delete.
    stem = os.path.basename(DB)[:-5]
    mine = re.compile(r"^" + re.escape(stem) + r"-\d{8}-\d{6}\.kdbx$")
    old_ones = sorted(f for f in os.listdir(BACKUPS) if mine.match(f))
    for f in old_ones[:-KEEP_BACKUPS]:
        try:
            os.remove(os.path.join(BACKUPS, f))
        except Exception:
            pass
    return dst


def verify_or_restore(backup_path, master):
    """A half-written .kdbx over SMB is a total loss. It is checked that
    the database still opens; if it does not, the backup is restored.

    The parameter is `backup_path`, not `backup`: naming it `backup` shadowed the
    module-level `backup()` right above, and the three call sites were passing the
    FUNCTION instead of the path. `shutil.copy2` then raised TypeError and the restore
    — the whole point of this function — never ran on a corrupted database."""
    # Deliberately against the real database and not against the working copy: what
    # has to open tomorrow is the file on the drive, which is the one just written.
    p = probe_real(master)
    if p.returncode == 0:
        return True
    write_over_db(backup_path, "restoring backup after a failed write")
    refresh_work_copy()
    die("the database would not open after writing: backup %s restored" % backup_path)


# --------------------------------------------------------------- input paths
def shred(path):
    """Overwrite and delete. On SMB or APFS there is no forensic guarantee — the file may
    leave copies—, but it removes the obvious trace and stops the second reader."""
    try:
        n = os.path.getsize(path)
        with open(path, "r+b", buffering=0) as f:
            for _ in range(2):
                f.seek(0)
                f.write(os.urandom(max(n, 1)))
                f.flush()
                os.fsync(f.fileno())
    except Exception:
        pass
    try:
        os.remove(path)
        return True
    except Exception:
        return False


def secret_from(a):
    """Read the secret through the chosen path. None of them is argv or the chat.

    Returns (value, source, cleanup) — `cleanup` runs only if the write to the kdbx
    went well: the original is not deleted until the secret is safe.
    """
    ways = [v for v in ("stdin", "clipboard", "file", "ask") if getattr(a, v, None)]
    if len(ways) > 1:
        die("choose a single path for the secret: %s" % ", ".join(ways))
    if a.stdin:
        val = sys.stdin.read()
        return _clean(val), "stdin", None
    if a.clipboard:
        paste, copy = clipboard_commands(PLATFORM, os.environ, shutil.which)
        if not paste:
            die("no clipboard tool found (Linux: wl-clipboard or xclip); use --stdin or --file")
        val = subprocess.run(paste, capture_output=True, text=True,
                             timeout=10).stdout
        if not _clean(val):
            die("the clipboard is empty")
        return (_clean(val), "clipboard",
                lambda: subprocess.run(copy, input="", text=True))
    if a.file:
        path = a.file if os.path.isabs(a.file) else os.path.join(INBOX, a.file)
        if not os.path.exists(path):
            die("does not exist: %s  (check the inbox with `kp.py inbox`)" % path)
        val = open(path, errors="replace").read()
        if not _clean(val):
            die("the file is empty: %s" % path)
        return _clean(val), "file %s" % os.path.basename(path), lambda: shred(path)
    if a.ask:
        val = ask_dialog()
        if not val:
            die("no password (dialog cancelled, or you are remote and cannot see it).\n"
                "    Paths that do work remotely:  --file <inbox file>\n"
                "    or --generate, which KeePassXC generates and which travels nowhere.",
                EXIT_NOMASTER)
        return val, "dialog", None
    return None, None, None


def _clean(val):
    while val.endswith("\n") or val.endswith("\r"):
        val = val[:-1]
    return val


# ------------------------------------------------------------------ entradas
def norm(entry):
    e = entry.strip().lstrip("/")
    if e.startswith("kp://"):
        e = e[5:]
    e = e.split("#")[0]
    return e


def leaf_of(entry):
    """The last segment of a name, normalised. `set` compares leaves before overwriting."""
    return norm(entry).rsplit("/", 1)[-1].strip().lower()


def with_group(entry):
    """Every secret Claude creates falls inside the kdbx group "%s".

    It is not cosmetic: it keeps what an agent wrote separate from what you saved by
    hand, so it can be audited, moved or deleted as a block without touching
    the rest of the database. Subgroups inside are allowed (`%s/servers/example`), but
    leaving is not: a path with its own group hangs off the group, it does not replace it.
    """ % (GROUP_DEF, GROUP_DEF)
    parts = [p for p in norm(entry).split("/") if p]
    if parts and parts[0].lower() == GROUP_DEF.lower():
        parts = parts[1:]
    return "/".join([GROUP_DEF] + parts)


def ensure_group(pw, group):
    """Creates the group and its intermediate levels; `mkdir` does not create them."""
    acc = []
    for parte in group.split("/"):
        if not parte:
            continue
        acc.append(parte)
        cli(["mkdir", DB, "/".join(acc)], pw, check=False)


def exists(pw, entry):
    if KIND == "kpcli":
        return KPB.run(KIND, CLI, ["show"] + _key_args() + [DB, entry], DB, pw or "",
                       timeout=CLI_TIMEOUT,
                       pwfile_dir=os.path.join(STATE, "kp-pwfiles")).returncode == 0
    return subprocess.run([CLI, "show", "-q"] + _key_args() + [DBF[0], entry],
                          input=_master_stdin(pw), timeout=CLI_TIMEOUT,
                          capture_output=True, text=True).returncode == 0


def resolve(pw, raw):
    """Find the entry even when the exact path is not given.

    The user's database has its own hierarchy and the agent does not know it by heart:
    without this, every read was trial and error against invented paths.
    """
    e = norm(raw)
    # Claude's group first: it is where it leaves its own.
    if exists(pw, with_group(e)):
        return with_group(e)
    # A query carrying a "/" is a real PATH lookup and `show` resolves it as such. A BARE
    # name is not: `keepassxc-cli show <title>` falls back to a GLOBAL title match and
    # returns the first entry in database tree order. Brain/ is the last of 25 top-level
    # groups and 32 of its 35 entries live in subgroups, so accepting that result made the
    # whole preference below unreachable — and handed back the user's same-named entry
    # instead of Claude's, silently, straight to the clipboard.
    if "/" in e and exists(pw, e):
        return e
    leaf = e.rsplit("/", 1)[-1]
    out = cli(["search", DB, leaf], pw, check=False).stdout
    cands = [c.strip().lstrip("/") for c in out.split("\n") if c.strip()]
    # An exact leaf match beats a substring one, so `example-api-key` is not made ambiguous
    # by `example-api-key-old`.
    exact = [c for c in cands if c.rsplit("/", 1)[-1].lower() == leaf.lower()]
    if exact:
        cands = exact
    own = [c for c in cands if c.lower().startswith(GROUP_DEF.lower() + "/")]
    # The same name can exist in Claude's group and in the user's hierarchy. If it is in
    # Claude's, that is the one: it is what they just left there to be used.
    if len(own) == 1:
        return own[0]
    if len(own) > 1:
        cands = own
    if len(cands) == 1:
        return cands[0]
    if not cands:
        die("no entry found for \"%s\". Try `kp.py search %s`,\n"
            "    or look at what is in the group:  kp.py ls %s -R -f" % (e, leaf, GROUP_DEF))
    die("\"%s\" is ambiguous, %d candidates:\n    %s" % (e, len(cands), "\n    ".join(cands[:15])))


# ------------------------------------------------------------------ comandos
def cmd_status(a):
    if not DB:
        print("database   : not configured (kp.py init --db PATH, or BRAIN_KP_DB)")
        print("config     : %s" % CONFIG)
        print("cli        : %s" % CLI)
        return
    print("database   : %s" % DB)
    if os.path.exists(DB):
        st = os.stat(DB)
        print("file       : %d KB, modified %s" % (
            st.st_size // 1024, time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))))
    else:
        print("file       : DOES NOT EXIST")
    lk = lock_state()
    if lk["status"] == "free":
        print("lock       : free")
    else:
        reason = lock_stale(lk)
        print("lock       : %s — %s" % (lock_who(lk),
              ("STALE, will clear itself on write" if reason
               else "blocks writing (kp.py locks)")))
    meta = _meta_read().get(_acct()) or {}
    fresh, reason = cache_fresh(meta)
    if _status_keyfile_only():
        # Said plainly: on a keyfile-only store "master: not available" reads as a fault and
        # sends whoever is looking hunting for a password nobody ever set.
        print("master     : not used, the keyfile is the whole key of this store")
    elif fresh and meta.get("exp"):
        left = int(meta["exp"] - time.time())
        print("master     : cached for %dd %dh %dm more, until %s (all Claude sessions)"
              % (left // 86400, left % 86400 // 3600, left % 3600 // 60,
                 time.strftime("%d/%m/%Y %H:%M", time.localtime(meta["exp"]))))
    elif fresh:
        try:
            boot = time.strftime("%d/%m %H:%M", time.localtime(float(meta.get("boot") or 0)))
        except ValueError:
            boot = str(meta.get("boot"))
        print("master     : cached until reboot (booted %s), for all\n"
              "             Claude sessions of this user" % boot)
    else:
        print("master     : not available — %s (will be asked for: %s)" % (reason, dialog_backend(PLATFORM, os.environ, shutil.which)))
    print("group      : %s/  (everything Claude writes goes inside)" % GROUP_DEF)
    print("keyfile    : %s%s" % (KEYFILE or "none",
                                  " (MISSING)" if KEYFILE and not os.path.exists(KEYFILE) else ""))
    print("cli        : %s (%s backend)" % (CLI, KIND))
    n = len([f for f in os.listdir(BACKUPS) if f.endswith(".kdbx")]) if os.path.isdir(BACKUPS) else 0
    print("backups    : %d in %s" % (n, BACKUPS))


def _status_keyfile_only():
    """keyfile_only() for `status`, which must not die: only asked when there is a key file,
    a database and a client to ask, and any failure reads as "no"."""
    if not (KEYFILE and os.path.exists(KEYFILE) and os.path.exists(DB)
            and (os.path.exists(CLI) or shutil.which(CLI))):
        return False
    try:
        return bool(keyfile_only())
    except (Exception, SystemExit):
        return False


def cmd_init(a):
    """Record which database this machine uses, and its key file if it has one, in
    <state>/kp-config.json (0600). Nothing is asked, so a setup script can run it.

    With --create, make a new empty database there first with keepassxc-cli db-create: it asks
    for the master on the terminal (or reads it twice from stdin). With --keyfile the database
    also gets that key file, created by db-create when it does not exist yet. With --keyfile and
    --no-password it gets the key file alone: a keyfile-only store, for a machine where nobody
    can type a master."""
    path = os.path.abspath(os.path.expanduser(a.db))
    keyfile = os.path.abspath(os.path.expanduser(a.keyfile)) if a.keyfile else ""
    if a.no_password and not keyfile:
        die("--no-password needs --keyfile: without a password the key file is the whole key")
    if a.create and not os.path.exists(path):
        if KIND == "kpcli":
            die("kp_backend: creating a new database (`kp.py init --create`) is not "
                "available with the kpcli backend — db-create is outside the six operations "
                "it covers. Create the .kdbx some other way first (KeePassXC on another "
                "machine, or keepassxc-cli directly), then point this machine at it with "
                "`kp.py init --db PATH` (no --create).", EXIT_NODB)
        if not (os.path.exists(CLI) or shutil.which(CLI)):
            die("keepassxc-cli not found", EXIT_NODB)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        new_key = bool(keyfile) and not os.path.exists(keyfile)
        cmd = [CLI, "db-create"]
        if keyfile:
            os.makedirs(os.path.dirname(keyfile), exist_ok=True)
            cmd += ["--set-key-file", keyfile]
        if not a.no_password:
            cmd += ["-p"]
        p = subprocess.run(cmd + [path])
        if p.returncode != 0 or not os.path.exists(path):
            die("could not create %s" % path, EXIT_NODB)
        print("created    : %s%s" % (path, " (keyfile-only)" if a.no_password else ""))
        if new_key and os.path.exists(keyfile):
            print("keyfile    : %s (new: keep a copy somewhere safe, it is part of the key)" % keyfile)
    elif not os.path.exists(path):
        sys.stderr.write("kp: note: %s does not exist yet (pass --create to make it)\n" % path)
    if keyfile and not os.path.exists(keyfile):
        sys.stderr.write("kp: note: the key file %s does not exist yet\n" % keyfile)
    cfg = load_config()
    wanted = dict(cfg, db=path)
    if keyfile:
        wanted["keyfile"] = keyfile
    if a.group:
        wanted["group"] = a.group
    if wanted == cfg:
        print("unchanged  : %s" % CONFIG)
        return
    os.makedirs(STATE, exist_ok=True)
    tmp = CONFIG + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(wanted, fh, indent=2, sort_keys=True)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG)
    print("recorded   : %s -> %s" % (path, CONFIG))


def cmd_unlock(a):
    pw = unlocked()
    if pw is None:
        print("nothing to unlock: the keyfile is the whole key of this store, there is no master\n"
              "to ask for or cache.")
        return
    cache_put(pw, _TTL[0])
    if _TTL[0]:
        print("armed until %s (%s)." % (
            time.strftime("%d/%m/%Y %H:%M", time.localtime(time.time() + _TTL[0])),
            ("%d days" % (_TTL[0] // 86400)) if _TTL[0] % 86400 == 0
            else ("%d min" % (_TTL[0] // 60))))
    else:
        print("armed until the machine's next reboot.")
    print("It covers ALL of this user's Claude sessions — local and remote —\n"
          "without asking again. To revoke it: kp.py lock")


def cmd_lock(a):
    cache_del()
    print("master forgotten")


def cmd_ls(a):
    pw = unlocked()
    args = ["ls"]
    if a.recursive:
        args.append("-R")
    if a.flatten:
        args.append("-f")
    args.append(DB)
    if a.group:
        args.append(a.group)
    sys.stdout.write(cli(args, pw).stdout)


def cmd_search(a):
    pw = unlocked()
    sys.stdout.write(cli(["search", DB, a.text], pw).stdout)


def cmd_get(a):
    pw = unlocked()
    entry = resolve(pw, a.entry)
    attr = a.attr
    if a.pipe:
        val = cli(["show", "-s", "-a", attr, DB, entry], pw).stdout
        val = val[:-1] if val.endswith("\n") else val
        p = subprocess.run(["/bin/sh", "-c", a.pipe], input=val + "\n", text=True)
        sys.exit(p.returncode)
    if a.show:
        sys.stderr.write("kp: WARNING — the secret ends up written in this conversation.\n")
        sys.stdout.write(cli(["show", "-s", "-a", attr, DB, entry], pw).stdout)
        return
    if a.info:
        sys.stdout.write(cli(["show", DB, entry], pw).stdout)
        return
    okc, errc = cli_clip(entry, attr, a.timeout, pw)
    if not okc:
        die("keepassxc-cli clip failed: %s" % errc)
    print("%s of \"%s\" copied to the clipboard (cleared in %ds)."
          % (attr, entry, a.timeout))
    print("kp://%s#%s" % (entry, attr))


def notes_of(pw, entry):
    p = cli(["show", "-a", "Notes", DB, entry], pw, check=False)
    return _clean(p.stdout) if p.returncode == 0 else ""


def mark_exposed(pw, entry, exists, a):
    """Record on the entry itself that this secret has already been out in the open.

    A secret pasted into a chat cannot be un-pasted: it stays in the transcript. The
    only honest thing is to file it and leave it written down that it needs rotating,
    rather than pretend that filing it makes it safe."""
    previous_notes = a.notes if a.notes else (notes_of(pw, entry) if exists else "")
    if any(m in (previous_notes or "") for m in EXPOSED_MARKS):
        return previous_notes
    marker = ("%s %s] This secret arrived through a channel that leaves a trace (chat "
              "or similar). Filing it here does not make it safe: treat it as compromised "
              "until it is rotated." % (EXPOSED, time.strftime("%Y-%m-%d")))
    return ((previous_notes + "\n\n") if previous_notes else "") + marker


def cmd_audit(a):
    """Which secrets need rotating. The counterpart of accepting them pasted in chat."""
    pw = unlocked()
    # Both marks are searched: entries predating the language change carry
    # the old one, and not finding them is worse than any cosmetic inconsistency.
    out = ""
    for mark in EXPOSED_MARKS:
        out += _clean(cli(["search", DB, mark.strip("[")], pw, check=False).stdout) + "\n"
    rows = [l.strip().lstrip("/") for l in out.split("\n") if l.strip()]
    if not rows:
        print("no entry marked as compromised")
        return
    print("compromised — rotate these and file them again:")
    for f in rows:
        print("  %s" % f)
    print("\nwhen rotating:  kp.py set <entry> --stdin   (and clear the mark with --notes '')")


def group_entries(pw):
    """Paths of what is in Claude's group. Names only: no secrets."""
    p = cli(["ls", "-R", "-f", DB, GROUP_DEF], pw, check=False)
    if p.returncode != 0:
        return []
    return sorted("%s/%s" % (GROUP_DEF, l.strip().lstrip("/"))
                  for l in p.stdout.split("\n")
                  if l.strip() and not l.strip().endswith("/"))


def inside_group(path):
    """The reorganisation latch: outside Claude's group nothing is touched.

    The kdbx is the user's password database, with twenty years of their own hierarchy
    inside. Reorganising is useful in `Brain/`; elsewhere it would wreck their system."""
    parts = [p for p in (path or "").split("/") if p]
    return bool(parts) and parts[0].lower() == GROUP_DEF.lower()


def rewrite_refs(old_one, new_one):
    """Updates the vault's kp:// references after moving an entry.

    Without this, reorganising breaks the memory: the note still says where the
    credential was and it is no longer there."""
    if B is None or not os.path.isdir(getattr(B, "VAULT", "")):
        return []
    touched = []
    for raiz, dirs, files_ in os.walk(B.VAULT):
        dirs[:] = [d for d in dirs if d not in (".git", "_index", "integrations", "_bin")]
        for f in files_:
            if not f.endswith(".md"):
                continue
            path = os.path.join(raiz, f)
            try:
                # Anchored at a reference boundary. A bare `str.replace` matched the old
                # path as a SUBSTRING, so moving `Brain/apis/example` rewrote every
                # reference to `Brain/apis/example-api-key` too and pointed it at an entry
                # that does not exist.
                rx = re.compile(r"kp://" + re.escape(old_one) + r"(?![\w./-])")
                if not rx.search(open(path, errors="replace").read()):
                    continue
                with B.flock(path):
                    txt = open(path, errors="replace").read()
                    B.atomic_write(path, rx.sub("kp://" + new_one.replace("\\", "\\\\"), txt))
                touched.append(os.path.relpath(path, B.VAULT))
            except Exception:
                continue
    return touched


def rewrite_kdbx_refs(pw, old_one, new_one):
    """Rewrites `kp://` references living in the Notes field of OTHER kdbx entries.

    `rewrite_refs` only walks the vault's `.md` files. But entries cross-reference each
    other too — an Apple developer entry pointing at the auth key and the fastlane env it
    needs — and those references are exactly the ones the group-layout convention will
    break when it moves an entry into a subgroup. Rewriting the notes and not the kdbx
    fixes half the problem and leaves the other half silently dangling.

    Called inside the caller's write_lock and before verify_or_restore, so a bad write is
    restored with everything else.
    """
    touched = []
    rx = re.compile(r"kp://" + re.escape(old_one) + r"(?![\w./-])")
    out = cli(["ls", DB, "-R", "-f"], pw, check=False).stdout
    for line in out.splitlines():
        entry = line.strip().lstrip("/")
        if not entry or entry.endswith("/") or not inside_group(entry):
            continue
        notes = notes_of(pw, entry)
        if not notes or not rx.search(notes):
            continue
        cli(["edit", DB, entry, "--notes", rx.sub("kp://" + new_one, notes)], pw)
        touched.append(entry)
    return touched


def cmd_mv(a):
    """Moves or renames an entry, always inside Claude's group."""
    pw = unlocked()
    source = resolve(pw, a.source)
    if not inside_group(source):
        die("\"%s\" is outside %s/ and nothing gets touched there.\n"
            "    The user's hierarchy is theirs: reorganising is only %s/ and below."
            % (source, GROUP_DEF, GROUP_DEF), EXIT_LOCKED)
    target = with_group(a.target)
    if target == source:
        print("already at %s" % target)
        return
    if exists(pw, target):
        die("\"%s\" already exists: choose another target." % target)
    guard_lock(a.force)
    group_dst, title_dst = target.rsplit("/", 1)
    title_src = source.rsplit("/", 1)[-1]
    backup_path = backup()
    with write_lock():
        ensure_group(pw, group_dst)
        if group_dst != source.rsplit("/", 1)[0]:
            cli(["mv", DB, source, group_dst], pw)
        intermediate = "%s/%s" % (group_dst, title_src)
        if title_dst != title_src:
            cli(["edit", DB, intermediate, "-t", title_dst], pw)
        kdbx_refs = rewrite_kdbx_refs(pw, source, target)
        verify_or_restore(backup_path, pw)
    print("moved: %s  ->  %s" % (source, target))
    for e in kdbx_refs:
        print("reference updated inside the kdbx: %s" % e)
    refs = rewrite_refs(source, target)
    for r in refs:
        print("reference updated in the vault: %s" % r)
    if not refs:
        print("(no vault note pointed at the previous path)")
    print("backup: %s" % os.path.basename(backup_path))


def cmd_rmdir(a):
    """Remove an empty group left behind after reorganising."""
    pw = unlocked()
    group = with_group(a.group)
    if group.lower() == GROUP_DEF.lower():
        die("the root group %s/ is not touched." % GROUP_DEF, EXIT_LOCKED)
    p = cli(["ls", "-R", "-f", DB, group], pw, check=False)
    if p.returncode != 0:
        die("the group \"%s\" does not exist" % group)
    # keepassxc-cli marks an empty group with a `[empty]` translated into the
    # system: the marker is what must be discarded, not the language.
    content = [l.strip() for l in p.stdout.split("\n")
                 if l.strip() and not re.match(r"^\[.*\]$", l.strip())]
    if content:
        die("\"%s\" is not empty (%d items): nothing with content gets deleted."
            % (group, len(content)), EXIT_LOCKED)
    guard_lock(a.force)
    backup_path = backup()
    with write_lock():
        cli(["rmdir", DB, group], pw)
        verify_or_restore(backup_path, pw)
    print("empty group removed: %s" % group)


def cmd_news(a):
    """What has appeared in the group since the last look.

    The user adds new passwords themselves from KeePassXC — that way the secret never
    passes through the conversation — and only says the name. This confirms it without
    relying on the exact name, comparing paths only: never values.
    """
    pw = unlocked()
    now_ = group_entries(pw)
    meta = _meta_read()
    prev = (meta.get("seen") or meta.get("vistas") or {}).get(_acct())
    if a.reset or prev is None:
        print("%d entry(ies) in %s/ recorded as known." % (len(now_), GROUP_DEF))
    else:
        fresh = [e for e in now_ if e not in prev]
        gone = [e for e in prev if e not in now_]
        if not fresh and not gone:
            print("nothing new in %s/ (%d entries)" % (GROUP_DEF, len(now_)))
        for e in fresh:
            print("  new        %s" % e)
        for e in gone:
            print("  no longer there: %s" % e)
    meta.setdefault("seen", {})[_acct()] = now_
    _meta_write(meta)


def cmd_inbox(a):
    """The inbox: dropping a file here is the traceless path, from the iPhone too."""
    try:
        os.makedirs(INBOX, exist_ok=True)
    except Exception as e:
        die("cannot use the inbox %s: %s" % (INBOX, e))
    files_ = [f for f in sorted(os.listdir(INBOX)) if not f.startswith(".")]
    print("inbox      : %s" % INBOX)
    if not files_:
        print("(empty)")
        return
    for f in files_:
        st = os.stat(os.path.join(INBOX, f))
        print("  %-40s %5d B  %s" % (f, st.st_size,
              time.strftime("%d/%m %H:%M", time.localtime(st.st_mtime))))
    print("\nfile one:  kp.py put <entry> --file %s" % files_[0])
    print("(the file is deleted as soon as the secret is safe in the kdbx)")


def cmd_put(a):
    guard_lock(a.force)          # before asking for the master: do not bother the user for nothing
    pw = unlocked()
    entry = with_group(a.entry)
    already_there = exists(pw, entry)
    if not already_there and a.editing:          # `set` edits what is already there, even if it hangs off another group
        found = resolve(pw, a.entry)
        # ...but it may cross GROUPS, never entries. resolve() matches the leaf by
        # SUBSTRING, which is what makes reads convenient and writes lethal: filing a
        # refresh_token under "<X> refresh" (which did not exist) resolved to "<X>" and
        # overwrote the client_secret that lived there, silently and with exit 0.
        # A legitimate partial path differs from its entry in the GROUP ("apis/example-api-key"
        # -> "Brain/apis/example-api-key"): the LEAF is always spelled in full. So a leaf that
        # does not match is not the entry that was asked for, and guessing costs a credential.
        if leaf_of(found) != leaf_of(a.entry):
            die("\"%s\" does not exist. The nearest match is \"%s\", whose NAME is not the\n"
                "    one you asked for, so I am not overwriting it by guesswork (that is how a\n"
                "    client_secret can be lost).\n"
                "      to create it:        kp.py put \"%s\" ...\n"
                "      to edit that one:    kp.py set \"%s\" ..." % (a.entry, found, a.entry, found))
        entry = found
        already_there = True
    group = entry.rsplit("/", 1)[0]
    if already_there and not a.force:
        die("\"%s\" already exists. Use `set` to edit it, or --force." % entry)
    backup_path = backup()
    if group:
        ensure_group(pw, group)
    args = ["edit" if already_there else "add", DB, entry]
    if a.user:
        args += ["-u", a.user]
    if a.url:
        args += ["--url", a.url]
    notes = mark_exposed(pw, entry, already_there, a) if a.exposed else a.notes
    if notes:
        args += ["--notes", notes]
    # Regenerating on a `set` that only touched metadata would wipe the good password:
    # it is only generated on create, or when a rotation is explicitly requested.
    given, source, cleanup = secret_from(a)
    generate_it = a.generate or (not already_there and given is None)
    extra = ""
    if given is not None:
        args += ["-p"]
        extra = given + "\n" + given + "\n"
    elif generate_it:
        args += ["-g", "-L", str(a.length), "-l", "-U", "-n", "-s"]
    with write_lock():                   # nobody else writes while this lasts
        cli(args, pw, extra_stdin=extra)
        verify_or_restore(backup_path, pw)
    if cleanup:                          # the original is deleted only once the kdbx is written
        cleanup()
    print("%s: %s%s" % ("updated" if already_there else "created", entry,
                        "" if (given is not None or generate_it) else
                        " (metadata only, password untouched)"))
    if source:
        print("source     : %s%s" % (source, ", original deleted" if cleanup else ""))
    if generate_it:
        if KIND == "kpcli":
            # cli_clip() itself would die() here (clip is not one of the six kpcli covers),
            # and the entry has already been written successfully by this point: dying mid-
            # print would hide that from the caller instead of pointing at how to read it.
            print("generated password not copied to the clipboard (clipboard copying is not "
                  "available with the kpcli backend). Read it with:  kp.py get %s --show" % entry)
        else:
            cli_clip(entry, "Password", a.timeout, pw)
            print("password on the clipboard (%ds)." % a.timeout)
    print("backup: %s" % os.path.basename(backup_path))
    print("reference for the note:  kp://%s#password" % entry)


def cmd_set(a):
    a.force = True
    cmd_put(a)


def cmd_locks(a):
    if KIND == "kpcli":
        die("kp_backend: lock-file checks are not available with the kpcli backend "
            "(KeePassXC's .lock file convention is not meaningful to it — kpcli/File::KDBX "
            "neither writes nor reads it). Coordinate writes by hand if another client "
            "might have this database open.", EXIT_NODB)
    lk = lock_state()
    if lk["status"] == "free":
        print("lock       : free, writing is possible")
        _m = _meta_read()
        hist = ((_m.get("candados_retirados") or [])
                + (_m.get("locks_cleared") or []))[-3:]   # old key kept for history
        # Rows written before the translation carry `cuando`/`quien`/`motivo`. Reading
        # the old CONTAINER without also reading the old FIELD names just moves the
        # KeyError one level down.
        for h in hist:
            when = h.get("when", h.get("cuando", 0))
            print("cleared    : %s — %s (%s)" % (
                time.strftime("%d/%m %H:%M", time.localtime(when)),
                h.get("who", h.get("quien", "?")),
                h.get("reason", h.get("motivo", "?"))))
        return
    print("lock       : %s" % lock_who(lk))
    print("file       : %s" % lock_path())
    print("state      : %s" % lk["status"])
    print("machine    : %s" % {"answers": "answers ping: the lock may be real",
                               "mute": "resolves but does not answer",
                               "no-resolve": "its name does not resolve on this network",
                               "local": "this very machine"}[lk["reach"]])
    reason = lock_stale(lk)
    print("verdict    : %s" % (("stale — " + reason) if reason else
                               "cannot prove it is stale"))
    if not a.clear:
        print("\nto clear it:  kp.py locks --clear")
        return
    if reason:
        lock_clear(lk, reason)
        return
    if a.force:
        lock_clear(lk, "cleared by hand with --force")
        return
    body = ("The keepass.kdbx lock is held by %s.\n\n"
              "I cannot prove it is stale: that machine %s.\n\n"
              "If that KeePassXC is genuinely still open and saves after me, the changes "
              "are lost. Clear the lock anyway?"
              % (lock_who(lk), lk["reach"].replace("-", " ")))
    if ask_confirm("Brain · KeePass", body, "Clear lock"):
        lock_clear(lk, "confirmed by hand at the machine")
    else:
        die("lock intact (nobody confirmed).\n"
            "    From a remote session the confirmation is:  kp.py locks --clear --force",
            EXIT_LOCKED)


def cmd_ref(a):
    """The reference is RESOLVED, not just prefixed.

    `with_group()` alone minted `kp://Brain/example-api-key#Password` for an entry that
    actually lives at `Brain/apis/example-api-key` — a reference that looks right, gets
    pasted into a note, and fails the day someone tries to use it. `get` prints the
    resolved path for the same input; the two have to agree."""
    pw = unlocked()
    print("kp://%s#%s" % (resolve(pw, a.entry), a.attr))


def main():
    ap = argparse.ArgumentParser(prog="kp.py", description="Brain system credentials")
    ap.add_argument("--ttl", default=None,
                    help="how long the master cache lasts (900, 30m, 8h, 365d). "
                         "Default 365d from unlock; it survives reboots")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("status").set_defaults(fn=cmd_status)
    i = sub.add_parser("init", help="record (or create) the database this machine uses")
    i.add_argument("--db", required=True); i.add_argument("--keyfile"); i.add_argument("--group")
    i.add_argument("--create", action="store_true")
    i.add_argument("--no-password", action="store_true",
                   help="with --create and --keyfile: the key file is the whole key, no master")
    i.set_defaults(fn=cmd_init)
    u = sub.add_parser("unlock")
    u.add_argument("--ttl", dest="ttl_sub", default=None,   # also after the subcommand:
                   help="how long the cache lasts (900, 30m, 8h, 365d; default 365d)")  # that is how it is documented
    u.set_defaults(fn=cmd_unlock)
    sub.add_parser("lock").set_defaults(fn=cmd_lock)

    l = sub.add_parser("ls"); l.add_argument("group", nargs="?")
    l.add_argument("-R", "--recursive", action="store_true")
    l.add_argument("-f", "--flatten", action="store_true"); l.set_defaults(fn=cmd_ls)

    s = sub.add_parser("search"); s.add_argument("text"); s.set_defaults(fn=cmd_search)

    g = sub.add_parser("get"); g.add_argument("entry")
    g.add_argument("-a", "--attr", default="Password")
    g.add_argument("--show", action="store_true", help="print the secret (it enters the chat)")
    g.add_argument("--info", action="store_true", help="summary without secrets")
    g.add_argument("--pipe", help="pass the secret on stdin to this command")
    # Documented in the usage header above; the clipboard is already the default, so
    # this is an explicit no-op. A flag the docs promise and the parser rejects is worse
    # than a redundant one.
    g.add_argument("--copy", action="store_true", help="copy to the clipboard (the default)")
    g.add_argument("--timeout", type=int, default=20); g.set_defaults(fn=cmd_get)

    for name, fn in (("put", cmd_put), ("set", cmd_set)):
        p = sub.add_parser(name); p.add_argument("entry")
        p.add_argument("-u", "--user"); p.add_argument("--url"); p.add_argument("--notes")
        p.add_argument("--ask", action="store_true", help="ask for the password via dialog")
        p.add_argument("--stdin", action="store_true",
                       help="file an existing password, reading it from stdin")
        p.add_argument("--clipboard", "--pegar", action="store_true",
                       help="take it from the clipboard and clear it afterwards")
        p.add_argument("--file", dest="file",
                       help="take it from a file (from the inbox if not an absolute "
                            "path) and delete it afterwards")
        # `--expuesto` is still accepted: vault notes already written cite that flag, and
        # breaking them for the sake of translation would be rewriting the docs by force.
        p.add_argument("--exposed", "--expuesto", dest="exposed", action="store_true",
                       help="mark the entry as compromised: it needs rotating")
        p.add_argument("-g", "--generate", action="store_true",
                       help="generate a new password (implicit on create, explicit on rotate)")
        p.add_argument("-L", "--length", type=int, default=24)
        p.add_argument("--force", action="store_true")
        p.add_argument("--timeout", type=int, default=20)
        p.set_defaults(fn=fn, editing=(name == "set"))

    sub.add_parser("audit").set_defaults(fn=cmd_audit)
    mv = sub.add_parser("mv")
    mv.add_argument("source"); mv.add_argument("target")
    mv.add_argument("--force", action="store_true")
    mv.set_defaults(fn=cmd_mv)

    rd = sub.add_parser("rmdir"); rd.add_argument("group")
    rd.add_argument("--force", action="store_true"); rd.set_defaults(fn=cmd_rmdir)

    nw = sub.add_parser("news")
    nw.add_argument("--reset", action="store_true",
                    help="mark what is there now as known, without listing it")
    nw.set_defaults(fn=cmd_news)
    sub.add_parser("inbox").set_defaults(fn=cmd_inbox)

    lo = sub.add_parser("locks")
    lo.add_argument("--clear", action="store_true", help="clear the lock")
    lo.add_argument("--force", action="store_true",
                    help="no confirmation (for remote sessions)")
    lo.set_defaults(fn=cmd_locks)

    r = sub.add_parser("ref"); r.add_argument("entry")
    r.add_argument("-a", "--attr", default="password"); r.set_defaults(fn=cmd_ref)

    a = ap.parse_args()
    if not getattr(a, "fn", None):
        ap.print_help(); sys.exit(2)
    elegido = getattr(a, "ttl_sub", None) or a.ttl
    _TTL[0] = human_ttl(elegido) if elegido else TTL_DEF
    a.fn(a)


if __name__ == "__main__":
    main()
