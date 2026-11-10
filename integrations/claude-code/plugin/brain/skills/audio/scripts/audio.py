#!/usr/bin/env python3
"""Spoken audio with Qwen3-TTS, run locally, plus optional background music.

    audio.py setup                     build or check the runtime on this machine
    audio.py status                    what is installed, nothing changed
    audio.py say TEXT_FILE --out OUT.mp3 [options]
    audio.py music --prompt "..." --out BED.wav [--seconds 100] [--small]
    audio.py mix VOICE MUSIC --out OUT.mp3 [--below 12]
    audio.py check AUDIO TEXT_FILE [--language es]   faster-whisper against the text

`say` options:
    --voice WAV --voice-text "..."   reference voice to clone (default: the Castilian voice in assets/)
    --language Spanish               main language of the text (default Spanish)
    --small                          Qwen3-TTS 0.6B instead of 1.7B (faster, a bit flatter)
    --device auto|cpu|mps|cuda       default auto
    --music BED.wav                  mix a music bed under the voice (only when the user asks for music)
    --below DB                       music level under the voice, default 12
    --no-check                       skip the faster-whisper check that runs after every say

Foreign words in the text are marked `{en:smartphone}` or `{fr:déjà vu}`; only those words are
spoken in that language, with the same voice. Codes: en fr de it pt ru zh ja ko es.

Runtime lives in ~/.cache/brain-audio (override BRAIN_AUDIO_HOME): a uv venv with torch,
qwen-tts and transformers; models go to the Hugging Face cache. This script itself needs only
the standard library, ffmpeg and ffprobe.
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path(os.environ.get("BRAIN_AUDIO_HOME", Path.home() / ".cache" / "brain-audio"))
VENV = HOME / "venv"
PY = VENV / "bin" / "python"
STAMP = HOME / "setup.json"
HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
DEFAULT_VOICE = ASSETS / "voice-es-castellano.wav"
#: Versions known to work together (qwen-tts 0.1.1 pulls transformers 4.57.3).
DEPS = ["qwen-tts==0.1.1", "soundfile", "numpy", "scipy", "accelerate", "faster-whisper"]
MODELS = {"large": "Qwen/Qwen3-TTS-12Hz-1.7B-Base", "small": "Qwen/Qwen3-TTS-12Hz-0.6B-Base"}
LANGS = {"en": "English", "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese",
         "ru": "Russian", "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "es": "Spanish"}
TAG = re.compile(r"\{([a-z]{2}):([^{}]+)\}")


def sh(cmd, **kw):
    print("+ " + " ".join(str(c) for c in cmd), file=sys.stderr)
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def uv_bin():
    return shutil.which("uv") or next(
        (str(p) for p in [Path.home() / ".local/bin/uv", Path("/opt/homebrew/bin/uv")] if p.exists()), None)


def cmd_setup(_args=None):
    if not shutil.which("ffmpeg") and platform.system() == "Darwin" and shutil.which("brew"):
        sh(["brew", "install", "ffmpeg"])
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"missing {tool} on PATH (Linux: apt-get install ffmpeg; Mac: brew install ffmpeg)")
    uv = uv_bin()
    if not uv:
        sh(["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"])
        uv = uv_bin()
    HOME.mkdir(parents=True, exist_ok=True)
    if not PY.exists():
        sh([uv, "venv", "-q", "--python", "3.12", VENV])
    env = {**os.environ, "VIRTUAL_ENV": str(VENV)}
    torch_args = ["torch", "torchaudio"]
    if platform.system() == "Linux" and not shutil.which("nvidia-smi"):
        torch_args = ["--index-url", "https://download.pytorch.org/whl/cpu"] + torch_args
    sh([uv, "pip", "install", "-q", *torch_args], env=env)
    sh([uv, "pip", "install", "-q", *DEPS], env=env)
    sh([PY, "-c", "import qwen_tts, soundfile; print('qwen-tts imports ok')"])
    STAMP.write_text(json.dumps({"deps": DEPS, "machine": platform.node()}))
    print(json.dumps({"ready": True, "home": str(HOME)}))


def ready():
    try:
        return json.loads(STAMP.read_text()).get("deps") == DEPS and PY.exists()
    except Exception:
        return False


def need_ready():
    """The runtime is per machine and not in the vault: the first use on a machine builds it."""
    if not ready():
        print("runtime not ready on this machine, running setup first (one time, about 2 GB)", file=sys.stderr)
        cmd_setup()


def cmd_status(_args):
    print(json.dumps({"home": str(HOME), "ready": ready(), "ffmpeg": bool(shutil.which("ffmpeg")),
                      "uv": bool(uv_bin()), "default_voice": DEFAULT_VOICE.exists()}, indent=2))


def parse_units(text, language="Spanish"):
    """Paragraphs -> list of units {text, lang, foreign, para}. A paragraph without tags is one
    unit (long ones are cut at sentence ends); a tagged one is cut around each foreign word."""
    units = []
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    for i, para in enumerate(paras):
        para = re.sub(r"\s+", " ", para)
        pos = 0
        for m in TAG.finditer(para):
            if m.group(1) not in LANGS:
                raise ValueError(f"unknown language code {m.group(1)!r} in {m.group(0)!r}")
            before = para[pos:m.start()].strip()
            if before:
                units += [{"text": t, "lang": language, "foreign": False, "para": i} for t in split_long(before)]
            units.append({"text": m.group(2).strip(), "lang": LANGS[m.group(1)], "foreign": True, "para": i})
            pos = m.end()
        rest = para[pos:].strip()
        if rest:
            units += [{"text": t, "lang": language, "foreign": False, "para": i} for t in split_long(rest)]
    return units


#: Letter patterns that native Spanish words almost never have. Only a hint for a review: it
#: misses foreign words spelled like Spanish ones and flags some proper names.
FOREIGN_HINT = re.compile(r"(w|k|sh|th|ph|ck|oo|ou|tz|ing$|tion$|ght|(?<=[^aeiouáéíóú\W])y$)", re.I)
SPANISH_OK = {"ok", "kilo", "kilos", "kilómetro", "kilómetros", "whisky", "hay", "hoy", "muy", "ley", "rey",
              "soy", "estoy", "voy", "doy", "buey", "virrey", "jersey", "caray", "uruguay", "paraguay"}


def foreign_suspects(text):
    """Untagged words that look foreign, to be reviewed before generating (Spanish texts only)."""
    bare = TAG.sub(" ", text)
    found = []
    for w in re.findall(r"[A-Za-zÁÉÍÓÚÑÜáéíóúñü]+", bare):
        if w.lower() not in SPANISH_OK and FOREIGN_HINT.search(w) and w not in found:
            found.append(w)
    return found


def split_long(text, limit=350):
    """Qwen drifts on long inputs; keep each generation under ~350 characters, cut at sentences."""
    if len(text) <= limit:
        return [text]
    out, cur = [], ""
    for sent in re.split(r"(?<=[.!?…])\s+", text):
        if cur and len(cur) + len(sent) + 1 > limit:
            out.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    return out + ([cur] if cur else [])


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(path)], capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def lufs(path, pre="anull"):
    err = subprocess.run(["ffmpeg", "-nostats", "-i", str(path), "-af", f"{pre},ebur128", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    if not m:
        raise RuntimeError(f"could not measure loudness of {path}")
    return float(m[-1])


def encode(src, out):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    codec = ["-c:a", "libmp3lame", "-b:a", "192k"] if out.suffix == ".mp3" else []
    sh(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-af", "alimiter=limit=0.89:level=false", *codec, out])


VOICE_PRE = "pan=mono|c0=c0,highpass=f=70,acompressor=threshold=-20dB:ratio=3"


def mix(voice, music, out, below=12.0):
    """Voice at -18 LUFS, music `below` dB under it and ducked while someone speaks, 2 s of music
    before the voice, 3 s after, 4 s fade out, master at -16 LUFS. Gains are fixed from measured
    loudness: single-pass loudnorm falls back to dynamic mode and lifts the music intro up to
    voice level, so it is never used here."""
    vg = -18 - lufs(voice, VOICE_PRE)
    mg = -18 - below - lufs(music, "pan=mono|c0=c0")
    d = duration(voice)
    total, fade_at = round(d + 5, 2), round(d + 1, 2)
    graph = (f"[0:a]aresample=44100,{VOICE_PRE},volume={vg:.2f}dB,adelay=2000,apad,asplit=2[v][sc];"
             f"[1:a]aresample=44100,pan=mono|c0=c0,atrim=0:{total},volume={mg:.2f}dB,"
             f"afade=t=in:d=2,afade=t=out:st={fade_at}:d=4[m];"
             "[m][sc]sidechaincompress=threshold=0.05:ratio=3:attack=80:release=900[md];"
             f"[v][md]amix=inputs=2:duration=longest:normalize=0,atrim=0:{total}[o]")
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "mix.wav"
        sh(["ffmpeg", "-loglevel", "error", "-y", "-i", voice, "-stream_loop", "-1", "-i", music,
            "-filter_complex", graph, "-map", "[o]", "-c:a", "pcm_f32le", raw])
        gain = -16 - lufs(raw)
        lev = Path(tmp) / "lev.wav"
        sh(["ffmpeg", "-loglevel", "error", "-y", "-i", raw, "-af", f"volume={gain:.2f}dB", "-ac", "2",
            "-c:a", "pcm_f32le", lev])
        encode(lev, out)


def cmd_say(args):
    text = Path(args.text_file).read_text(encoding="utf-8")
    units = parse_units(text, args.language)
    voice = Path(args.voice or DEFAULT_VOICE)
    voice_text = args.voice_text
    if voice_text is None:
        side = voice.with_suffix(".txt")
        if not side.exists():
            sys.exit(f"--voice-text is required: no {side.name} next to {voice}")
        voice_text = side.read_text(encoding="utf-8").strip()
    need_ready()
    with tempfile.TemporaryDirectory() as tmp:
        job = Path(tmp) / "job.json"
        wav = Path(tmp) / "voice.wav"
        job.write_text(json.dumps({
            "units": units, "voice": str(voice), "voice_text": voice_text,
            "model": MODELS["small" if args.small else "large"], "device": args.device, "out": str(wav),
            "cache": str(HOME / "cache"),
        }, ensure_ascii=False))
        sh([PY, HERE / "qwen_say.py", job])
        if args.music:
            mix(wav, args.music, args.out, args.below)
        else:
            norm = Path(tmp) / "norm.wav"
            g = -16 - lufs(wav)
            sh(["ffmpeg", "-loglevel", "error", "-y", "-i", wav, "-af", f"volume={g:.2f}dB", "-ac", "2", norm])
            encode(norm, args.out)
    result = {"out": str(args.out), "seconds": round(duration(args.out), 1),
              "units": len(units), "foreign": sum(u["foreign"] for u in units)}
    if args.language == "Spanish":
        result["untagged_suspects"] = foreign_suspects(text)
    if not args.no_check:
        result["check"] = check(args.out, args.text_file, LANG_CODES.get(args.language, "es"))
    print(json.dumps(result, ensure_ascii=False))


LANG_CODES = {v: k for k, v in LANGS.items()}


def check(audio, text_file, language="es"):
    """faster-whisper is allowed only here, to check this skill's own output, never as a transcript."""
    need_ready()
    out = subprocess.run([str(PY), str(HERE / "whisper_check.py"), str(audio), str(text_file),
                          "--language", language], capture_output=True, text=True, check=True).stdout
    return json.loads(out.strip().splitlines()[-1])


def cmd_check(args):
    print(json.dumps(check(args.audio, args.text_file, args.language), ensure_ascii=False, indent=2))


def cmd_music(args):
    need_ready()
    sh([PY, HERE / "musicgen_bed.py", "--prompt", args.prompt, "--out", args.out,
        "--seconds", str(args.seconds), "--model",
        "facebook/musicgen-small" if args.small else "facebook/musicgen-medium"])


def cmd_mix(args):
    mix(args.voice, args.music, args.out, args.below)
    print(json.dumps({"out": str(args.out), "seconds": round(duration(args.out), 1)}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup").set_defaults(fn=cmd_setup)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    p = sub.add_parser("say")
    p.add_argument("text_file")
    p.add_argument("--out", required=True)
    p.add_argument("--voice")
    p.add_argument("--voice-text")
    p.add_argument("--language", default="Spanish")
    p.add_argument("--small", action="store_true")
    p.add_argument("--device", default="auto", choices=["auto", "cpu", "mps", "cuda"])
    p.add_argument("--music")
    p.add_argument("--below", type=float, default=12.0)
    p.add_argument("--no-check", action="store_true")
    p.set_defaults(fn=cmd_say)
    p = sub.add_parser("check")
    p.add_argument("audio")
    p.add_argument("text_file")
    p.add_argument("--language", default="es")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("music")
    p.add_argument("--prompt", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--seconds", type=int, default=100)
    p.add_argument("--small", action="store_true")
    p.set_defaults(fn=cmd_music)
    p = sub.add_parser("mix")
    p.add_argument("voice")
    p.add_argument("music")
    p.add_argument("--out", required=True)
    p.add_argument("--below", type=float, default=12.0)
    p.set_defaults(fn=cmd_mix)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
