"""MusicGen background bed, runs inside the skill venv (audio.py setup builds it).

    musicgen_bed.py --prompt "..." --out BED.wav [--seconds 100] [--model facebook/musicgen-medium]

MusicGen makes about 30 s per pass, so the bed is that clip chained with 4 s triangular
crossfades until it reaches --seconds; the joins are not audible under a voice.
medium took about 40 min on a server CPU while other models ran; small is several times faster
and a bit thinner.
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

import scipy.io.wavfile as wavfile
import torch
from transformers import AutoProcessor, MusicgenForConditionalGeneration


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seconds", type=int, default=100)
    ap.add_argument("--model", default="facebook/musicgen-medium")
    args = ap.parse_args()
    torch.set_num_threads(max(1, os.cpu_count() or 1))
    proc = AutoProcessor.from_pretrained(args.model)
    model = MusicgenForConditionalGeneration.from_pretrained(args.model)
    inputs = proc(text=[args.prompt], padding=True, return_tensors="pt")
    audio = model.generate(**inputs, max_new_tokens=1500, do_sample=True, guidance_scale=3.5)
    sr = model.config.audio_encoder.sampling_rate
    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / "clip.wav"
        wavfile.write(clip, sr, audio[0, 0].numpy())
        clip_len = audio.shape[-1] / sr
        copies = max(1, int((args.seconds - 4) // (clip_len - 4)) + 1)
        cmd = ["ffmpeg", "-loglevel", "error", "-y"]
        for _ in range(copies):
            cmd += ["-i", str(clip)]
        if copies == 1:
            cmd += ["-c:a", "pcm_s16le", args.out]
        else:
            chain, last = [], "[0]"
            for i in range(1, copies):
                tag = f"[x{i}]"
                chain.append(f"{last}[{i}]acrossfade=d=4:c1=tri:c2=tri{tag}")
                last = tag
            cmd += ["-filter_complex", ";".join(chain), "-map", last, "-c:a", "pcm_s16le", args.out]
        subprocess.run(cmd, check=True)
    print(args.out)


if __name__ == "__main__":
    main()
