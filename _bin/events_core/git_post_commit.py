#!/usr/bin/env python3
"""git post-commit adapter: marks the index dirty after any commit, whoever made it.

It never reindexes itself — that would slow down every commit, a person's included. It
leaves the same `_index/.dirty` marker session_end.py leaves, and the next vault_sync.py
pass or file-watch tick picks it up. A post-commit hook cannot undo a commit, and this one
never reports failure either: at worst the index catches up a little later.
"""

import os
import subprocess
import sys
import time


def main():
    try:
        p = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=10)
        root = p.stdout.strip() if p.returncode == 0 else os.getcwd()
        index = os.path.join(root, "_index")
        os.makedirs(index, exist_ok=True)
        with open(os.path.join(index, ".dirty"), "w") as fh:
            fh.write(str(time.time()))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
