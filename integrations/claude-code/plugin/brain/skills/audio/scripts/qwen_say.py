"""Qwen3-TTS worker, runs inside the skill venv (audio.py setup builds it).

    qwen_say.py JOB.json

JOB: {units: [{text, lang, foreign, para}], voice, voice_text, model, device, out, cache}.
Main-language units clone the voice in ICL mode (reference audio plus its text, best accent).
Foreign units use only the speaker embedding of the same voice (x-vector mode), so the word keeps
the timbre but is pronounced in its own language instead of continuing the reference's accent.
Every unit is cached by content, so a run that dies resumes where it stopped.
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

PARA_GAP = 0.5    # seconds between paragraphs
JOIN_GAP = 0.07   # seconds around a foreign word inside a sentence
UNIT_GAP = 0.25   # seconds between two cuts of the same long paragraph


def pick_device(name):
    if name != "auto":
        return name
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def trim(wav, sr, margin=0.04, floor_db=-42):
    """Cut leading and trailing near-silence of a fragment, so spliced pieces join tightly."""
    if wav.size == 0:
        return wav
    hop = int(sr * 0.01)
    frames = np.lib.stride_tricks.sliding_window_view(np.pad(wav, (0, hop)), hop)[::hop]
    rms = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)
    loud = np.where(rms > rms.max() + floor_db)[0]
    if loud.size == 0:
        return wav
    a = max(0, loud[0] * hop - int(margin * sr))
    b = min(len(wav), (loud[-1] + 1) * hop + int(margin * sr))
    return wav[a:b]


def fade(wav, sr, ms=8):
    n = min(len(wav) // 2, int(sr * ms / 1000))
    if n:
        ramp = np.linspace(0, 1, n)
        wav = wav.copy()
        wav[:n] *= ramp
        wav[-n:] *= ramp[::-1]
    return wav


def main():
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    device = pick_device(job["device"])
    if device == "mps":
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    torch.set_num_threads(max(1, os.cpu_count() or 1))
    dtype = torch.bfloat16 if device == "cuda" else torch.float32
    from qwen_tts import Qwen3TTSModel

    cache = Path(job["cache"])
    cache.mkdir(parents=True, exist_ok=True)
    voice_id = hashlib.sha1(Path(job["voice"]).read_bytes() + job["voice_text"].encode()).hexdigest()[:12]
    model = prompts = None
    units = job["units"]
    pieces, sr = [], 24000
    t0 = time.time()
    for i, u in enumerate(units):
        key = hashlib.sha1(json.dumps([job["model"], voice_id, u["text"], u["lang"], u["foreign"]],
                                      ensure_ascii=False).encode()).hexdigest()
        f = cache / f"{key}.wav"
        if not f.exists():
            if model is None:
                print(f"loading {job['model']} on {device}", file=sys.stderr, flush=True)
                model = Qwen3TTSModel.from_pretrained(job["model"], device_map=device, dtype=dtype)
                prompts = {
                    False: model.create_voice_clone_prompt(ref_audio=job["voice"], ref_text=job["voice_text"]),
                    True: model.create_voice_clone_prompt(ref_audio=job["voice"], x_vector_only_mode=True),
                }
            wavs, sr = model.generate_voice_clone(text=u["text"], language=u["lang"],
                                                  voice_clone_prompt=prompts[u["foreign"]])
            sf.write(f, wavs[0], sr)
        wav, sr = sf.read(f, dtype="float32")
        pieces.append(wav)
        print(f"unit {i + 1}/{len(units)} {u['lang']}{' (foreign)' if u['foreign'] else ''} "
              f"{time.time() - t0:.0f}s", file=sys.stderr, flush=True)

    out = []
    for i, (u, wav) in enumerate(zip(units, pieces)):
        prev = units[i - 1] if i else None
        nxt = units[i + 1] if i + 1 < len(units) else None
        joined = (prev and prev["para"] == u["para"] and (prev["foreign"] or u["foreign"])) or \
                 (nxt and nxt["para"] == u["para"] and (nxt["foreign"] or u["foreign"]))
        if joined:
            wav = fade(trim(wav, sr), sr)
        if prev is not None:
            if prev["para"] != u["para"]:
                gap = PARA_GAP
            elif prev["foreign"] or u["foreign"]:
                gap = JOIN_GAP
            else:
                gap = UNIT_GAP
            out.append(np.zeros(int(sr * gap), dtype=np.float32))
        out.append(wav.astype(np.float32))
    sf.write(job["out"], np.concatenate(out), sr)
    print(json.dumps({"wav": job["out"], "seconds": round(sum(len(x) for x in out) / sr, 1),
                      "elapsed": round(time.time() - t0)}), file=sys.stderr)


if __name__ == "__main__":
    main()
