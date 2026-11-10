---
name: audio
description: Generates spoken audio (narration, a story, a voice over, a text read aloud, an MP3) with Qwen3-TTS run locally, in the configured default language and voice (Spain Spanish with a public domain Castilian reader out of the box), any word in another language spoken in that language with the same voice, and soft background music only when the user asks for it. Use it every time the user asks for audio of any kind ("make me an audio", "read this aloud", "narrate this story", "voice over", "an mp3 with..."), and inside any skill, routine or video that needs a voice. The first use on a machine sets up its runtime by itself.
argument-hint: <text file> --out <file.mp3>
allowed-tools: Bash(python3 ~/.claude/skills/audio/scripts/audio.py:*), Bash(ffmpeg:*), Bash(ffprobe:*), Read, Write
---

# Audio (Qwen3-TTS, local)

**Every audio request is made with Qwen3-TTS, locally.** It was picked over XTTS v2, Chatterbox, F5,
Piper and Kokoro after all of them told the same story: it sounded the most natural, kept the accent
of the reference voice and clones a voice from ten seconds of speech. Its licence is Apache 2.0. One
engine means one sound across everything the vault produces.

- **Default language and voice, configurable.** Out of the box the main language is Spanish and the
  voice is `assets/voice-es-castellano.wav`, a 10 s clip of a Castilian LibriVox reader (public domain
  recording of Galdós, *Zaragoza*), with its exact words in `assets/voice-es-castellano.txt`. Qwen3
  clones it in ICL mode (reference audio plus its exact text), which also carries the accent. For
  another language or voice pass `--language` and `--voice` (below), or replace the two asset files
  with your own clip and its text.
- **Words in another language are spoken in that language, only those words.** This is the skill's
  job every time, without being asked: before generating, read the text and mark each one,
  `{en:smartphone}`, `{fr:savoir faire}`, `{en:machine learning}`. Codes: en fr de it pt ru zh ja ko es.
  The script cuts the sentence around the word, generates the word with the same model and voice but
  in that language and with only the speaker embedding (x-vector mode, so the reference's accent does
  not leak into it), trims the silences and splices the pieces with 70 ms gaps. Mark loanwords people
  say in the original language (smartphone, marketing, wallet), names of foreign companies and
  products, and quotes in other languages. Do not mark words with a normal form in the main language.
- **No music unless the user asks for it.** The section below explains how to add it when they do.

## How

1. Write the text into a UTF-8 file, with blank lines between paragraphs (a paragraph pause is
   0.5 s). If the text is ours, not the user's, it goes through the `humanizer` skill first (house rule
   for every text for people). Spell out numbers as they should be read. Mark every foreign word
   yourself, always, also when the user did not mention it and when the text is theirs.
2. Generate:
   ```bash
   python3 ~/.claude/skills/audio/scripts/audio.py say text.txt --out ~/audio/<slug>.mp3
   ```
   It prints `{"out", "seconds", "units", "foreign", "untagged_suspects", "check"}`.
   `untagged_suspects` lists unmarked words that look foreign (w, k, sh, th, -ing...). If one of them
   is really foreign, mark it and run again (the cache keeps every unchanged paragraph). The MP3 is
   192 kbps at -16 LUFS. Options: `--voice clip.wav --voice-text "exact words of the clip"` for another
   voice (10 s of clean speech that ends on a pause; a `clip.txt` next to it works too),
   `--language English` when the main text is not Spanish, `--small` for the 0.6B model,
   `--device cpu|mps|cuda`.
3. Pace: on a server CPU the 1.7B model takes about 14 s per second of audio when the CPU is free
   (10 s of audio in 2 min 20 s), so a minute of audio takes about 15 min, and much longer with other
   models running at the same time. Anything over a minute of audio runs in the background
   (`run_in_background`) and the user gets a progress message. Every piece is cached by content in
   `~/.cache/brain-audio/cache`, so a run that dies resumes by running the same command again.
4. Deliver the file the way the user's deliverables go (a shared link from object storage, an
   attachment), never as a bare local path.
5. Check (automatic): after every `say` the script transcribes the MP3 with faster-whisper
   (large-v3-turbo, int8, CPU) and compares it with the text. `check` in the output gives the
   similarity and the words that differ. Read the diffs before delivering. A missing sentence, a
   repeated phrase or a tail the text does not have means the paragraph has to be regenerated: delete
   its cache file, or change a comma, and run again. Numbers written in words come back as digits, and
   a foreign word can come back split ("smart phone"); neither is an error. To check any file on its
   own: `audio.py check <file> <text file> [--language es]`. `--no-check` skips it.
   **faster-whisper runs only here, only to check this skill's own output.** Transcription of anything
   else goes through the `transcribe` skill. The check has caught a model skipping a whole number
   written in words, which nobody noticed by ear.

## Setup

Automatic on first use (`say` and `music` call `setup` when the runtime is missing or stale). To
prepare a machine ahead, or to check it:

```bash
python3 ~/.claude/skills/audio/scripts/audio.py setup     # idempotent
python3 ~/.claude/skills/audio/scripts/audio.py status
python3 ~/.claude/skills/audio/scripts/audio_test.py      # standard library only
```

A machine needs `python3` (any 3.9+, the venv gets its own 3.12 through `uv`, which setup installs if
missing), `ffmpeg` and `ffprobe` (on a Mac setup runs `brew install ffmpeg`), about 2 GB in
`~/.cache/brain-audio` (override with `BRAIN_AUDIO_HOME`) for the venv and about 4.5 GB in the Hugging
Face cache for the 1.7B model (1.5 GB for 0.6B), downloaded on the first `say`. On Linux without
NVIDIA, torch comes from the CPU index. On Apple Silicon `--device auto` picks `mps` with CPU
fallback for missing ops; if mps gives garbled audio, use `--device cpu`. No API key is needed.

## Background music (only when the user asks)

1. Make a bed with MusicGen, locally:
   ```bash
   python3 ~/.claude/skills/audio/scripts/audio.py music --out bed.wav --seconds 120 \
     --prompt "calm folk instrumental, solo guitar and soft flute, slow tempo, gentle, warm, no drums, no vocals"
   ```
   The prompt names the instruments and the mood, and says no drums and no vocals; drums and voices
   fight with the narration. MusicGen makes about 30 s per pass, so the script chains copies with 4 s
   triangular crossfades until it reaches at least `--seconds` (one hard loop is audible). `medium`
   can take 40 min on a busy CPU; `--small` is several times faster and thinner. Generate the bed in
   the background while the voice is being made. A music file of the user's, or a public domain one,
   works the same way as the bed.
2. Mix: `audio.py say ... --music bed.wav`, or `audio.py mix voice.wav bed.wav --out final.mp3`. The
   voice goes to -18 LUFS and the music sits `--below` dB under it (default 12; 15 was too quiet to
   notice, and about 4 dB competed with the voice). The music is sidechain-ducked further while someone
   speaks, plays 2 s alone before the voice and 3 s after it, and fades out over 4 s. The master is
   -16 LUFS.
3. Pitfalls already paid for: ffmpeg's single-pass `loudnorm` silently falls back to dynamic mode
   (even with `linear=true` when no measured values are given) and lifts the music intro to voice
   level, so gains are fixed from an `ebur128` measurement. `mktemp --suffix` does not exist on macOS,
   which is why the mixer is Python. RMS readings (`volumedetect`) overrate bass-heavy music, so music
   level is judged in LUFS.

## Notes

- The ICL reference must end on a pause that matches the end of its text exactly. A clip that ran on
  past its text leaked its last words into every paragraph. Cut a new voice with
  `ffmpeg -ss <start> -t <len>` at word boundaries, then add 0.4 s of silence.
- Long paragraphs are cut at sentence ends under 350 characters, because Qwen drifts on long inputs.
- Do not name a script after a package it imports (a script called `f5_tts.py` shadowed `f5_tts`).
- Video voice overs and narration in other skills take the MP3 from here.
