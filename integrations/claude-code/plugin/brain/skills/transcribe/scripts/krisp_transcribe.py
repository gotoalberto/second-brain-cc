#!/usr/bin/env python3
"""Transcribe any audio or video through Krisp, as a "[Transcription job]" meeting.

The file is re-encoded to 48 kbps mono AAC, imported into the user's Krisp account with the title
prefixed `[Transcription job]` (so any reader of the user's real meetings can skip it), and the
transcript is waited for and written out: Krisp's speaker blocks, `**Name | mm:ss**` then the text.

  krisp_transcribe.py <file> --title "<what it is>" [--out <file.txt>] [--language auto|en|es|...]
  krisp_transcribe.py <file> --title "..." --resume <krisp meeting id>   only wait, never upload again

Krisp is reached through krisp_mcp.py next to this file (the OAuth credential is in the kdbx at
kp://apis/krisp-mcp-oauth; `krisp_mcp.py setup` creates it). Needs ffmpeg and ffprobe.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
KRISP = os.path.join(HERE, "krisp_mcp.py")
TRANSCRIPTION_JOB_PREFIX = "[Transcription job]"
SPEAKER = re.compile(r"^\*\*.+\|\s*\d+:\d+\*\*\s*$", re.M)
CALL_TIMEOUT = 600
RETRIES = 5
BACKOFF = 15


def call(tool: str, args: dict, sleep=time.sleep) -> dict:
    """One Krisp call through krisp_mcp.py, retried while Krisp answers 429 (too busy)."""
    last = ""
    for attempt in range(RETRIES + 1):
        r = subprocess.run([sys.executable, KRISP, "call", tool, json.dumps(args), "--json"],
                           capture_output=True, text=True, timeout=CALL_TIMEOUT)
        if r.returncode == 0:
            return json.loads(r.stdout)
        last = (r.stderr or r.stdout).strip()[:300]
        if "429" not in last or attempt == RETRIES:
            break
        sleep(BACKOFF * (2 ** attempt))
    raise RuntimeError("krisp %s failed: %s" % (tool, last))


def transcript_body(document: str) -> str:
    """Krisp's document minus its own title and headings: the speaker blocks, verbatim."""
    m = SPEAKER.search(document or "")
    return document[m.start():].strip() if m else ""


PREFIX = TRANSCRIPTION_JOB_PREFIX
MAX_BYTES = 1 << 30            # Krisp's import limit
WAIT = 3 * 3600                # for the import, and again for the transcript
POLL = 30


def _duration_s(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def job_title(title: str) -> str:
    title = " ".join((title or "untitled").split())
    return (title if title.startswith(PREFIX) else "%s %s" % (PREFIX, title))[:200]


def upload(path, title, language="auto", log=print):
    """Import `path` into Krisp; returns the Krisp meeting id once the import is ready."""
    with tempfile.TemporaryDirectory() as tmp:
        audio = os.path.join(tmp, "audio.m4a")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000",
                        "-c:a", "aac", "-b:a", "48k", audio], check=True)
        size = os.path.getsize(audio)
        if size > MAX_BYTES:
            raise RuntimeError("audio is %d MB, over Krisp's 1 GB: split it" % (size >> 20))
        args = {"title": job_title(title), "language": language, "size": size}
        secs = _duration_s(audio)
        if secs:
            args["duration"] = round(secs)
        for attempt in range(5):
            try:
                imp = call("import_recording", args)
                break
            except RuntimeError as exc:
                # Only one import start per user at a time; another one in flight is not a failure.
                if "still in process" not in str(exc) or attempt == 4:
                    raise
                time.sleep(10)
        with open(audio, "rb") as fh:
            req = urllib.request.Request(imp["url"], data=fh, method="PUT",
                                         headers={"Content-Type": "audio/mp4", "Content-Length": str(size)})
            urllib.request.urlopen(req, timeout=1800).read()
    deadline = time.time() + WAIT
    while True:
        st = call("get_import_status", {"import_id": imp["import_id"]})
        if st.get("status") == "ready" and st.get("meeting_id"):
            break
        if st.get("status") == "failed" or time.time() > deadline:
            raise RuntimeError("krisp import %s: %s" % (st.get("status"), json.dumps(st)[:200]))
        time.sleep(POLL)
    kmid = st["meeting_id"]
    log("imported to Krisp as %s" % kmid)
    return kmid


def wait_transcript(kmid, wait=WAIT):
    """The transcript's speaker blocks (`**Name | mm:ss**` then the text), once Krisp has them."""
    deadline = time.time() + wait
    while True:
        doc = (call("get_multiple_documents", {"ids": [kmid], "include": ["transcript"]})
               .get("results") or [{}])[0].get("document", "")
        body = transcript_body(doc if isinstance(doc, str) else "")
        if body:
            return body.rstrip() + "\n"
        if time.time() > deadline:
            raise RuntimeError("krisp meeting %s: no transcript after %d min" % (kmid, wait // 60))
        time.sleep(POLL)


def transcribe(path, title, language="auto", resume=None, on_import=None, log=print):
    """(transcript, krisp meeting id). `on_import(kmid)` runs right after the upload, so a caller
    can remember the id before the long wait and pass it back as `resume` if it dies."""
    kmid = resume or upload(path, title, language, log)
    if on_import and not resume:
        on_import(kmid)
    return wait_transcript(kmid), kmid


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("file")
    ap.add_argument("--title", required=True)
    ap.add_argument("--out")
    ap.add_argument("--language", default="auto")
    ap.add_argument("--resume")
    a = ap.parse_args()
    if not a.resume and not os.path.exists(a.file):
        sys.exit("no such file: %s" % a.file)
    text, kmid = transcribe(a.file, a.title, a.language, a.resume,
                            log=lambda m: print(m, file=sys.stderr))
    out = a.out or os.path.splitext(a.file)[0] + ".transcript.txt"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(json.dumps({"krisp_meeting_id": kmid, "out": out, "chars": len(text)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
