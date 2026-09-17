#!/usr/bin/env python3
"""Routes kp.py's credential calls to whichever KeePass client this machine actually has.

kp.py speaks one protocol: keepassxc-cli's. That is still the default and, unmodified, the
only backend most users ever need. But keepassxc-cli cannot be installed on every machine, and
someone sharing a `.kdbx` over a synced path (never S3 — see brain_shared.py) between two
machines may have `kpcli` (the Perl KeePass client) on the one where KeePassXC will not go.
This module is the single place that knows the difference: `_resolve()` decides which backend
this machine speaks, `translate()` turns the small, fixed set of keepassxc-cli-shaped argv
kp.py's own `cli()` builds into what `kp_kdbx.pl` (the kpcli-backed helper, new to this repo)
expects, and `run()` carries out one call end to end.

**Scope, on purpose.** Only the six subcommands `kp.py` actually issues through its central
`cli()` function are translated: `ls`, `search`, `show`, `mkdir`, `add`, `edit` (checked
against every `cli([...])` call site in kp.py). Everything else — `mv`, `rmdir`, and whatever
else reaches `cli()` — raises `Unsupported`, which kp.py's `cli()` turns into a clear `die()`
naming the operation, never a silent no-op or a bare traceback. `clip`, `db-create` and the
`.lock`-file probing in `guard_lock`/`lock_state` never reach this module at all — they call
`CLI` directly in kp.py and get their own explicit `KIND == "kpcli"` guard there, for the same
reason: a full port of every direct call site in a 1700-line, carefully hardened file is
meaningfully riskier than translating the handful that matter (see the plan's open design
decision on this cut).

**The kpcli bug this exists to fix.** kp.py's `cmd_put` always sends `given + "\\n" + given +
"\\n"` on stdin when writing a secret — keepassxc-cli's own protocol reads that as
password-then-confirmation correctly, but a Perl script that just slurps stdin would store
BOTH lines as one literal value, silently doubling every secret it writes. `split_confirmation`
is the fix, applied only on the kpcli path; keepassxc-cli's already-correct behavior is
untouched. See kp_backend_test.py.
"""
import os
import shutil
import subprocess
import sys
import tempfile


class Unsupported(Exception):
    """Raised by translate() for anything outside the six subcommands the kpcli backend
    covers, and by build()/run() for a backend kind neither "keepassxc" nor "kpcli"."""


BACKENDS = ("keepassxc", "kpcli")


KP_KDBX_PL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kp_kdbx.pl")


def binary_name(kind):
    """What is actually invoked for each kind. The real interactive `kpcli` shell cannot be
    scripted (no non-interactive mode worth the name) — that is the whole reason kp_kdbx.pl
    exists, as a direct File::KDBX binding — so the kpcli backend never shells out to a
    binary literally called "kpcli"; it always runs THIS repo's own kp_kdbx.pl, whose name is
    deliberately what gets looked for."""
    return "keepassxc-cli" if kind == "keepassxc" else "kp_kdbx.pl"


def default_fallback_paths(kind):
    """Well-known install locations, kept in one place so this is honest about being a LAST
    resort after BRAIN_KP_BACKEND and shutil.which() have both had their say — never presented
    as the only way to find the binary, the same spirit as kp.py's own CLI resolution.

    kpcli has no fallback path here on purpose. kp_kdbx.pl ships inside this repo, so
    os.path.exists() on it is always true regardless of whether Perl or File::KDBX are
    actually installed — it is not a signal that the kpcli backend is usable, only that the
    checkout is complete. Treating it as "found" here used to make kpcli win by default on
    any machine without keepassxc-cli installed (including a bare CI checkout), silently
    switching every user without keepassxc-cli to a backend that then fails outright. kpcli
    stays reachable only through an explicit `BRAIN_KP_BACKEND=kpcli`, or through
    shutil.which() genuinely finding kp_kdbx.pl on $PATH — both real signals that someone
    chose it, unlike the file merely existing in the repo.
    """
    if kind == "keepassxc":
        candidates = ("/opt/homebrew/bin/keepassxc-cli", "/usr/local/bin/keepassxc-cli", "/usr/bin/keepassxc-cli")
    else:
        candidates = ()
    return [p for p in candidates if os.path.exists(p)]


def _find(kind, which, fallback_paths):
    found = which(binary_name(kind))
    if found:
        return found
    for p in fallback_paths(kind):
        return p
    return binary_name(kind)


def _resolve(environ, which, fallback_paths):
    """(KIND, PATH). `BRAIN_KP_BACKEND` ("keepassxc" or "kpcli"), when set, wins outright and
    names which protocol this machine speaks — kpcli is for a machine keepassxc-cli cannot be
    installed on. Without it, keepassxc-cli is preferred (today's only backend, unchanged
    default) and kpcli is used only if nothing finds keepassxc-cli at all. Either way the
    binary itself is found with shutil.which() first, then the fallback list.
    """
    forced = (environ.get("BRAIN_KP_BACKEND") or "").strip().lower()
    if forced in BACKENDS:
        return forced, _find(forced, which, fallback_paths)
    for kind in BACKENDS:
        found = which(binary_name(kind))
        if found:
            return kind, found
    for kind in BACKENDS:
        for p in fallback_paths(kind):
            return kind, p
    return "keepassxc", binary_name("keepassxc")


KIND, PATH = _resolve(os.environ, shutil.which, default_fallback_paths)


# ------------------------------------------------------------------ argv translation
TRANSLATED = ("ls", "search", "show", "mkdir", "add", "edit")


def _pop_flag(rest, flag):
    if flag in rest:
        rest.remove(flag)
        return True
    return False


def _pop_value(rest, flag):
    if flag in rest:
        i = rest.index(flag)
        value = rest[i + 1] if i + 1 < len(rest) else None
        del rest[i:i + 2]
        return value
    return None


def _translate_ls(rest):
    recursive = _pop_flag(rest, "-R")
    flatten = _pop_flag(rest, "-f")
    if len(rest) > 1:
        raise Unsupported("ls")
    group = rest[0] if rest else None
    out = ["ls"]
    if recursive:
        out.append("--recursive")
    if flatten:
        out.append("--flatten")
    if group:
        out += ["--group", group]
    return out


def _translate_search(rest):
    if len(rest) != 1:
        raise Unsupported("search")
    return ["search", "--text", rest[0]]


def _translate_show(rest):
    reveal = _pop_flag(rest, "-s")
    attr = _pop_value(rest, "-a")
    if len(rest) != 1:
        raise Unsupported("show")
    out = ["show", "--entry", rest[0]]
    if attr:
        out += ["--attr", attr]
    if reveal:
        out.append("--reveal")
    return out


def _translate_mkdir(rest):
    if len(rest) != 1:
        raise Unsupported("mkdir")
    return ["mkdir", "--group", rest[0]]


def _translate_add_edit(op, rest):
    if not rest:
        raise Unsupported(op)
    entry = rest.pop(0)
    user = _pop_value(rest, "-u")
    url = _pop_value(rest, "--url")
    notes = _pop_value(rest, "--notes")
    stdin_secret = _pop_flag(rest, "-p")
    generate = _pop_flag(rest, "-g")
    length = _pop_value(rest, "-L")
    # keepassxc-cli's per-charset flags (-l lower, -U upper, -n digits, -s symbols): kpcli
    # generates its own way, so these are accepted (kp.py always sends them together with -g)
    # and dropped rather than raising Unsupported over a shape kp.py itself always produces.
    for flag in ("-l", "-U", "-n", "-s"):
        _pop_flag(rest, flag)
    if rest:
        raise Unsupported(op)
    out = [op, "--entry", entry]
    if user:
        out += ["--user", user]
    if url:
        out += ["--url", url]
    if notes:
        out += ["--notes", notes]
    if stdin_secret:
        out.append("--stdin-secret")
    if generate:
        out.append("--generate")
        if length:
            out += ["--length", length]
    return out


def translate(args, db_path):
    """The keepassxc-cli-shaped argv kp.py's `cli()` builds -> kp_kdbx.pl's own argv tail.

    Only the six subcommands kp.py actually issues through `cli()` are covered (see the module
    docstring). `db_path` is skipped wherever it appears in `args` rather than assumed to sit
    at a fixed position: kp.py's own argv shapes do not all put it in the same place (`ls`'s DB
    argument moves depending on which of `-R`/`-f` precede it).
    """
    if not args:
        raise Unsupported("(empty)")
    op = args[0]
    if op not in TRANSLATED:
        raise Unsupported(op)
    rest = [a for a in args[1:] if a != db_path]
    if op == "ls":
        return _translate_ls(rest)
    if op == "search":
        return _translate_search(rest)
    if op == "show":
        return _translate_show(rest)
    if op == "mkdir":
        return _translate_mkdir(rest)
    return _translate_add_edit(op, rest)


# ------------------------------------------------------------------ one call, end to end
def _shred(path):
    """Overwrite and delete a private temp file. Best-effort, same spirit as kp.py's own
    shred(): no forensic guarantee, but it removes the obvious trace."""
    try:
        n = os.path.getsize(path)
        with open(path, "r+b", buffering=0) as fh:
            fh.seek(0)
            fh.write(os.urandom(max(n, 1)))
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        pass
    try:
        os.remove(path)
    except OSError:
        pass


def build(kind, path, args, db_path, master, pwfile_dir):
    """(argv, stdin_prefix, cleanup_fn) for one backend call.

    keepassxc-cli: unchanged from today — `args` (already keepassxc-cli-shaped) becomes the
    argv tail as-is, and `master` is the first line on stdin.

    kpcli: `args` is translate()'s OUTPUT (kp_kdbx.pl's own argv tail). The master is written
    to a private 0600 temp file under `pwfile_dir` instead of stdin, so stdin is free to carry
    only a NEW secret — kp_kdbx.pl reads the master from `--pwfile`, never from argv or a
    duplicated stdin payload. `cleanup_fn` shreds that temp file; call it once the process has
    exited, success or not.
    """
    if kind == "keepassxc":
        return [path] + list(args), master + "\n", (lambda: None)
    if kind == "kpcli":
        os.makedirs(pwfile_dir, mode=0o700, exist_ok=True)
        fd, pwfile = tempfile.mkstemp(prefix="kp-master-", dir=pwfile_dir)
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(master)
            os.chmod(pwfile, 0o600)
        except OSError:
            _shred(pwfile)
            raise
        argv = [path] + list(args) + ["--db", db_path, "--pwfile", pwfile]
        return argv, "", (lambda: _shred(pwfile))
    raise Unsupported(kind)


def split_confirmation(payload):
    """kp.py's `cmd_put` always sends `given + "\\n" + given + "\\n"` on stdin when writing a
    secret. keepassxc-cli's own protocol consumes that correctly (password, then
    confirmation); a naive slurp — what kp_kdbx.pl would do without this — stores both lines
    as one literal value, doubling the secret. Splits on the first two lines and collapses to
    one when they are identical; anything else (a single line, mismatched halves, empty) is
    returned unchanged, so a future single-line caller is not corrupted by this fix.
    """
    lines = payload.split("\n")
    if len(lines) == 3 and lines[2] == "" and lines[0] == lines[1]:
        return lines[0]
    return payload


def run(kind, path, args, db_path, master, stdin_extra="", timeout=60, pwfile_dir=None):
    """One backend call end to end: translate (kpcli only), build, invoke, clean up. Returns
    the completed subprocess. Raises Unsupported for a subcommand the kpcli backend does not
    cover — kp.py's cli() catches that and dies with a clear message."""
    if kind == "kpcli":
        argv_tail = translate(args, db_path)
        stdin_extra = split_confirmation(stdin_extra)
    else:
        argv_tail = args
    argv, prefix, cleanup = build(kind, path, argv_tail, db_path, master, pwfile_dir)
    try:
        return subprocess.run(argv, input=prefix + stdin_extra, capture_output=True, text=True, timeout=timeout)
    finally:
        cleanup()


def main():
    print("backend : %s" % KIND)
    print("binary  : %s" % PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
