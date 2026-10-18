#!/usr/bin/env python3
"""Regression tests for vw.py's stdin handling.

`vw.py new` used to call sys.stdin.read() whenever stdin was not a tty. Claude Code's Bash
tool hands the process a unix socket on fd 0 that never reaches EOF, so the call blocked for
ever, and killing it mid-write left a stub note behind. read_body() now reads a body only from
a regular file or a pipe. Pure: no disk, no database, no notes written. Run standalone:

    python3 _bin/vw_stdin_test.py
"""
import io
import os
import socket
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail and not cond else ""))


class FakeStdin(io.StringIO):
    def __init__(self, text, fileno, tty=False):
        io.StringIO.__init__(self, text)
        self._fileno = fileno
        self._tty = tty

    def fileno(self):
        return self._fileno

    def isatty(self):
        return self._tty


def with_stdin(vw, stream, required):
    """Call read_body with a given stdin, returning its value or the exit code."""
    saved_in, saved_err = sys.stdin, sys.stderr
    sys.stdin, sys.stderr = stream, io.StringIO()
    try:
        return vw.read_body(required=required)
    except SystemExit as exc:
        return exc.code
    finally:
        sys.stdin, sys.stderr = saved_in, saved_err


def test_read_body(vw):
    print("\n== vw.read_body ==")
    # The hang case: a socket on fd 0 with a peer that never writes and never closes.
    a, b = socket.socketpair()
    check("a socket on fd 0 is no body for new", with_stdin(vw, FakeStdin("", a.fileno()), False) == "")
    check("a socket on fd 0 makes append and set exit 2", with_stdin(vw, FakeStdin("", a.fileno()), True) == 2)
    a.close()
    b.close()

    # A real body still arrives, from a pipe and from a file.
    r, w = os.pipe()
    check("a pipe carries a body", with_stdin(vw, FakeStdin("piped\n", r), False) == "piped\n")
    check("a pipe satisfies append", with_stdin(vw, FakeStdin("piped\n", r), True) == "piped\n")
    os.close(r)
    os.close(w)

    with tempfile.NamedTemporaryFile("w+", suffix=".md") as tmp:
        tmp.write("from a file\n")
        tmp.flush()
        tmp.seek(0)
        check("'< file' carries a body",
              with_stdin(vw, FakeStdin("from a file\n", tmp.fileno()), False) == "from a file\n")

    # /dev/null is a character device: no body, and no waiting either.
    with open(os.devnull) as dn:
        check("'< /dev/null' is no body", with_stdin(vw, FakeStdin("", dn.fileno()), False) == "")

    check("a tty is no body (a person typing)", with_stdin(vw, FakeStdin("", 0, tty=True), False) == "")
    check("an unusable fd is no body, never an exception", with_stdin(vw, FakeStdin("", 9999), False) == "")
    check("no stdin at all is no body", with_stdin(vw, None, False) == "")


def main():
    try:
        import vw
        vw.read_body
    except Exception as exc:
        check("vw.read_body imports", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        try:
            test_read_body(vw)
        except Exception as exc:
            check("test_read_body ran to the end", False, "%s: %s" % (type(exc).__name__, exc))
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
