#!/usr/bin/env python3
"""Tests for krisp_transcribe: the prefix, the flow against a fake Krisp, resume. No network."""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import krisp_transcribe as T

fails = 0
passes = 0


def check(name, cond):
    global fails, passes
    print(("ok   " if cond else "FAIL ") + name)
    fails += 0 if cond else 1
    passes += 1 if cond else 0


check("prefix added once", T.job_title("Talk") == "[Transcription job] Talk")
check("prefix not doubled", T.job_title("[Transcription job] Talk") == "[Transcription job] Talk")
check("title capped at Krisp's 200", len(T.job_title("x" * 500)) == 200)

# The flow against a fake Krisp: import, PUT, status until ready, transcript empty once then there.
calls, puts = [], []
status = iter([{"status": "processing"}, {"status": "ready", "meeting_id": "m1"}])
docs = iter(["# t\n## Transcript 1\n# Transcript\n",
             "# t\n## Transcript 1\n# Transcript\n**Ana | 00:01**\nHola.\n"])


def fake_call(tool, args, sleep=None):
    calls.append((tool, args))
    if tool == "import_recording":
        return {"import_id": "i1", "url": "https://upload.example/x"}
    if tool == "get_import_status":
        return next(status)
    if tool == "get_multiple_documents":
        return {"results": [{"document": next(docs)}]}
    raise AssertionError(tool)


class FakeResp:
    def read(self):
        return b""


def fake_urlopen(req, timeout=None):
    puts.append((req.get_method(), req.headers))
    return FakeResp()


T.call = fake_call
T.urllib.request.urlopen = fake_urlopen
T.POLL = 0
with tempfile.TemporaryDirectory() as d:
    src = os.path.join(d, "a.wav")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", src],
                   check=True)
    seen = []
    text, kmid = T.transcribe(src, "Demo video", on_import=seen.append, log=lambda m: None)
check("returns the Krisp meeting id", kmid == "m1" and seen == ["m1"])
check("waits past the empty transcript", text.startswith("**Ana | 00:01**") and "Hola." in text)
imp = [a for t_, a in calls if t_ == "import_recording"][0]
check("import titled with the prefix and sized", imp["title"] == "[Transcription job] Demo video" and imp["size"] > 0)
check("uploaded with PUT as audio/mp4", puts and puts[0][0] == "PUT" and puts[0][1].get("Content-type") == "audio/mp4")

calls.clear()
docs = iter(["**Bo | 00:02**\nOk.\n"])
text, kmid = T.transcribe("/nonexistent", "x", resume="m9", log=lambda m: None)
check("resume skips the upload", kmid == "m9" and all(t_ == "get_multiple_documents" for t_, _ in calls))

print(f"\nRESULT: {passes} passed, {fails} failed")
sys.exit(1 if fails else 0)
