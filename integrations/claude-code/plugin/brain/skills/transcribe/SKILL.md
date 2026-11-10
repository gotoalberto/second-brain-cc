---
name: transcribe
description: Transcribes any audio or video (a recording, a video file, a voice note, a meeting nobody recorded, a downloaded call) through Krisp, uploaded as a "[Transcription job]" meeting that readers of the user's real meetings skip. Use it whenever anything has to be turned into text ("transcribe this", "what is said in this video"), and inside any skill, routine or script that needs a transcript. Needs a Krisp account connected once with `krisp_mcp.py setup`.
argument-hint: <file> --title "<what it is>"
allowed-tools: Bash(python3 ~/.claude/skills/transcribe/scripts/krisp_transcribe.py:*), Bash(python3 ~/.claude/skills/transcribe/scripts/krisp_mcp.py:*), Bash(ffmpeg:*), Bash(ffprobe:*), Read, Write
---

# Transcribe (through Krisp)

**One transcription backend, always the same.** Everything that has to become text goes through
Krisp with the `[Transcription job]` prefix. Krisp returns the transcript with speaker names in a few
minutes (an hour of audio takes about five), and one backend means one quality, one place to look
and one set of traps. If Krisp fails, report it and retry later with `--resume`; do not produce the
transcript another way, and do not treat a transcript published elsewhere (a wiki page, an AI
summary, a video platform's captions) as a substitute.

Two uses of a local speech model do not count as transcribing, and are the only ones allowed:

- **Timing.** Word synced captions need a time per word and Krisp gives one per speaker block, so a
  forced aligner (torchaudio's MMS_FA, for example) may place Krisp's words in time. It never
  produces text; the words stay Krisp's.
- **Checking generated speech.** The `audio` skill runs faster-whisper on the speech it has just
  generated, to compare it with the text it was given. Its output is never used as a transcript.

## How

```bash
python3 ~/.claude/skills/transcribe/scripts/krisp_transcribe.py <file> --title "<what it is>" \
    [--out <file.txt>] [--language auto|en|es|...]
```

- Any format ffmpeg reads. The script re-encodes to 48 kbps mono AAC first (an hour is about 20 MB;
  Krisp accepts 1 GB at most, so only files over about 40 hours need splitting).
- It prints one JSON line `{"krisp_meeting_id", "out", "chars"}` and writes the transcript to `--out`
  (default `<file>.transcript.txt`): Krisp's speaker blocks, `**Name | mm:ss**` then the text.
  Unknown voices come as `Speaker 1`, `Speaker 2`.
- It takes minutes, not seconds: run it in the background for long files. If it dies after the
  upload, rerun with `--resume <krisp_meeting_id>`: it only waits for that transcript and never
  uploads the file twice.
- From Python: `import krisp_transcribe as KT; text, kmid = KT.transcribe(path, title, ...)` (with
  `~/.claude/skills/transcribe/scripts` on `sys.path`). `on_import=` gets the Krisp id right after
  the upload, so the caller can store it before the long wait.

## What happens in Krisp, and why the prefix

The file becomes a meeting in the user's Krisp titled `[Transcription job] <title>`, dated at the
upload, not when the thing happened. It is not a meeting the user had, so anything that reads their
real meetings (a daily sweep into the vault, a summary routine) must skip titles with that prefix.
Choose a title that says what it is and when: `All hands 2026-01-15: Q&A`, `Podcast episode 12 full cut`.

Where the transcript goes afterwards is the caller's job: a vault note, object storage, a summary.
Internal material stays in the user's own Krisp account and their own storage; nothing else
receives it.

## Setup, once per machine

`python3 ~/.claude/skills/transcribe/scripts/krisp_mcp.py setup` adds Krisp's MCP server
(`https://mcp.krisp.ai/mcp`) to Claude Code, runs the OAuth login in the browser and backs the
credential up to the kdbx at `kp://apis/krisp-mcp-oauth`. From then on the kdbx copy is the source
of truth: the script reads it first, falls back to Claude Code's own copy (the macOS Keychain or
`~/.claude/.credentials.json`) and writes that back into the kdbx when it is fresher.
`krisp_mcp.py status` shows both copies and their expiry.

## Rules

- Krisp is reached only through `krisp_mcp.py`, never through a vendor connector.
- `import_recording` is a write to the user's Krisp account. It is what this skill is for; anything
  else written to Krisp still needs asking.
- Only one import start per user can be in flight; the script retries "Action is still in process"
  on its own. Transcribe files one after another, not in parallel.
- `ready` in `get_import_status` means imported. The transcript arrives a few minutes later; the
  script waits for it (up to 3 hours) before returning.
- Correct proper nouns before publishing anything from a transcript: automatic transcripts mangle
  names and product terms.

Tests: `scripts/krisp_transcribe_test.py` (a fake Krisp, no network; needs ffmpeg).
