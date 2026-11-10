"""Checks a generated audio against its text with faster-whisper; runs inside the skill venv.

    whisper_check.py AUDIO TEXT_FILE [--language es]

Allowed only here: faster-whisper may check what this skill generates, never transcribe anything else.
Every other transcription still goes through Krisp (skill `transcribe`).

Prints JSON: similarity (0..1, word sequence ratio after normalising), heard and expected word
counts, and the words that differ, so a skipped sentence, a repeat or an invented tail shows up.
Numbers are compared as words are, so "1132" against "mil ciento treinta y dos" counts as a
difference; read the diff before regenerating.
"""
import argparse
import difflib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audio import TAG  # noqa: E402


def words(text):
    text = TAG.sub(lambda m: m.group(2), text).lower()
    return re.sub(r"[^\wáéíóúñüàèìòùâêîôûçäëïöß' ]", " ", text).split()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("text_file")
    ap.add_argument("--language", default="es")
    args = ap.parse_args()
    from faster_whisper import WhisperModel

    model = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8",
                         cpu_threads=max(1, os.cpu_count() or 1))
    # Decoded by ffmpeg: faster-whisper's own decoder breaks on newer PyAV (metadata_errors).
    import numpy as np
    pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", args.audio, "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    segments, _ = model.transcribe(np.frombuffer(pcm, dtype=np.float32), language=args.language)
    heard = words(" ".join(s.text for s in segments))
    expected = words(Path(args.text_file).read_text(encoding="utf-8"))
    sm = difflib.SequenceMatcher(None, expected, heard)
    diffs = [{"op": op, "expected": " ".join(expected[a:b]), "heard": " ".join(heard[c:d])}
             for op, a, b, c, d in sm.get_opcodes() if op != "equal"]
    print(json.dumps({"similarity": round(sm.ratio(), 3), "heard_words": len(heard),
                      "expected_words": len(expected), "diffs": diffs}, ensure_ascii=False))


if __name__ == "__main__":
    main()
