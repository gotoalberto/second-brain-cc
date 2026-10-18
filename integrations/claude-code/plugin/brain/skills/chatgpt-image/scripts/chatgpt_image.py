#!/usr/bin/env python3
"""Export images generated on chatgpt.com through the system clipboard.

chatgpt.com's content security policy blocks posting the image blob anywhere, and a browser that
asks where to save every download cannot be driven unattended, so the export path is: clear the
clipboard here, click ChatGPT's "Copy image" button with a real mouse click, then read image/png
from the clipboard of the desktop the browser runs on.

  chatgpt_image.py config                        project URL, output dir, clipboard backend
  chatgpt_image.py check                         clipboard backend ready?
  chatgpt_image.py clear                         put a placeholder in the clipboard
  chatgpt_image.py export --name <slug> [--prompt TEXT] [--chat-url URL] [--out PATH]

Configuration, all optional:
  CHATGPT_IMAGE_PROJECT_URL  the ChatGPT project every new image starts in (a chatgpt.com URL);
                             unset means a plain new chat at https://chatgpt.com/
  CHATGPT_IMAGE_DIR          where exports go, default ~/chatgpt-images (<dir>/<YYYY-MM-DD>/<slug>.png)
  CHATGPT_IMAGE_DISPLAY      X display on Linux, default $DISPLAY or :0

export prints JSON with the saved path, size, dimensions and sha256, and writes a .json sidecar
next to the PNG with the prompt and chat URL so other flows can reuse both.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.parse

PLACEHOLDER = "chatgpt-image-placeholder"
PLAIN_CHAT = "https://chatgpt.com/"


def config():
    problems = []
    project = (os.environ.get("CHATGPT_IMAGE_PROJECT_URL") or "").strip() or None
    if project:
        host = urllib.parse.urlparse(project).hostname or ""
        if host != "chatgpt.com" and not host.endswith(".chatgpt.com"):
            problems.append("CHATGPT_IMAGE_PROJECT_URL is not a chatgpt.com URL: ignored")
            project = None
    out_dir = os.path.expanduser(os.environ.get("CHATGPT_IMAGE_DIR") or "~/chatgpt-images")
    return {"project_url": project, "start_url": project or PLAIN_CHAT,
            "out_dir": os.path.abspath(out_dir), "problems": problems}


class XClipboard:
    """Linux: the X clipboard through xclip, on the display the browser runs on."""

    def __init__(self):
        self.display = os.environ.get("CHATGPT_IMAGE_DISPLAY") or os.environ.get("DISPLAY") or ":0"

    def _run(self, *args, timeout=10):
        env = dict(os.environ, DISPLAY=self.display)
        return subprocess.run(["xclip", "-selection", "clipboard", *args], capture_output=True,
                              env=env, timeout=timeout)

    def problems(self):
        return [] if shutil.which("xclip") else ["xclip missing (install it with the system package manager)"]

    def has_png(self):
        return "image/png" in self._run("-o", "-t", "TARGETS").stdout.decode(errors="ignore").split()

    def read_png(self):
        return self._run("-o", "-t", "image/png", timeout=30).stdout

    def clear(self):
        # xclip -i forks and keeps owning the selection until something else copies.
        env = dict(os.environ, DISPLAY=self.display)
        p = subprocess.Popen(["xclip", "-selection", "clipboard", "-i"], stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        p.communicate(PLACEHOLDER.encode(), timeout=5)


class MacClipboard:
    """macOS: the general pasteboard through osascript and pbcopy."""

    def problems(self):
        return [] if shutil.which("osascript") and shutil.which("pbcopy") else ["osascript or pbcopy missing"]

    def has_png(self):
        out = subprocess.run(["osascript", "-e", "clipboard info"], capture_output=True, text=True, timeout=10)
        return "PNGf" in (out.stdout or "")

    def read_png(self):
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            script = ['set f to open for access POSIX file "%s" with write permission' % path,
                      "set eof f to 0", "write (the clipboard as «class PNGf») to f", "close access f"]
            cmd = ["osascript"]
            for line in script:
                cmd += ["-e", line]
            subprocess.run(cmd, capture_output=True, timeout=30)
            with open(path, "rb") as fh:
                return fh.read()
        finally:
            os.unlink(path)

    def clear(self):
        subprocess.run(["pbcopy"], input=PLACEHOLDER.encode(), timeout=5)


def clipboard_for(platform):
    if platform == "darwin":
        return MacClipboard()
    if platform.startswith("linux"):
        return XClipboard()
    return None


def png_size(data):
    if not data or data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
        return None
    return struct.unpack(">II", data[16:24])


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s[:60] or "image"


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    return 1


def export(args, clip, out_root, today=None):
    if not clip.has_png():
        return fail("clipboard holds no image/png: click ChatGPT's 'Copy image' with a real mouse click "
                    "(computer left_click; a JS .click() has no user gesture and copies nothing)")
    data = clip.read_png()
    dims = png_size(data)
    if not dims:
        return fail("clipboard data is not a PNG")
    if args.out:
        out = os.path.abspath(os.path.expanduser(args.out))
    else:
        day = today or datetime.date.today().isoformat()
        base = os.path.join(out_root, day, slugify(args.name))
        out, n = base + ".png", 2
        while os.path.exists(out):
            out, n = "%s-%d.png" % (base, n), n + 1
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as fh:
        fh.write(data)
    info = {
        "ok": True, "path": out, "bytes": len(data), "width": dims[0], "height": dims[1],
        "sha256": hashlib.sha256(data).hexdigest(), "prompt": args.prompt,
        "chat_url": args.chat_url, "created": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    with open(os.path.splitext(out)[0] + ".json", "w", encoding="utf-8") as fh:
        json.dump(info, fh, indent=2, ensure_ascii=False)
    clip.clear()  # so the next export can never pick up this image again by mistake
    print(json.dumps(info, ensure_ascii=False))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("config")
    sub.add_parser("check")
    sub.add_parser("clear")
    e = sub.add_parser("export")
    e.add_argument("--name", default="image", help="short slug for the file name")
    e.add_argument("--out", help="exact output path (.png); default <CHATGPT_IMAGE_DIR>/<date>/<slug>.png")
    e.add_argument("--prompt", help="prompt that produced the image, stored in the sidecar")
    e.add_argument("--chat-url", help="ChatGPT conversation URL, stored in the sidecar")
    args = ap.parse_args(argv)
    cfg = config()
    clip = clipboard_for(sys.platform)
    problems = list(cfg["problems"])
    problems += clip.problems() if clip else ["no clipboard backend for %s (macOS and Linux only)" % sys.platform]
    if args.cmd == "config":
        print(json.dumps(dict(cfg, clipboard=type(clip).__name__ if clip else None, problems=problems)))
        return 0
    if args.cmd == "check":
        print(json.dumps({"ok": not problems, "problems": problems}))
        return 1 if problems else 0
    if clip is None or clip.problems():
        return fail("; ".join(problems))
    if args.cmd == "clear":
        clip.clear()
        print(json.dumps({"ok": True}))
        return 0
    return export(args, clip, cfg["out_dir"])


if __name__ == "__main__":
    sys.exit(main())
