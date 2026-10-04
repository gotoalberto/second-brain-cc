---
id: 2026-08-25-howto-extract-transcript-and-stills-from-a-video
title: Pulling clips and the stills that matter out of a local video with ffmpeg
type: howto
area: [deliverables, tooling]
projects: []
tags: [video, ffmpeg, screenshots, scene-detection, contact-sheet, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-04
supersedes: []
---

All local, without uploading the video anywhere. The transcript half of the job is left to whatever
transcription tool the user has configured; this note covers cutting the video and choosing the frames
that illustrate a summary.

## Cut, extract audio, extract stills

```sh
# cut without re-encoding (near instant)
ffmpeg -ss 00:20:00 -to 00:35:00 -i input.mp4 -c copy -avoid_negative_ts make_zero clip.mp4

# 16 kHz mono audio, the format most transcription tools want
ffmpeg -i clip.mp4 -vn -ac 1 -ar 16000 -c:a pcm_s16le clip.wav

# one still per second
mkdir -p shots && ffmpeg -i clip.mp4 -vf "fps=1,scale=1280:-2" -q:v 3 shots/shot_%04d.jpg
```

`-ss` **before** `-i` seeks by keyframe, which is what makes the cut immediate; with `-c copy` there is no
re-encoding.

## From hundreds of stills to the ones that matter

Scene change detection over the extracted sequence gives the frames where the screen really changed:

```sh
ffmpeg -f image2 -framerate 1 -i shots/shot_%04d.jpg \
  -vf "select='gt(scene,0.04)',metadata=print:file=-" -f null - 2>&1 \
  | grep pts_time | awk -F'pts_time:' '{print int($2)+1}'
```

For an app demo, which changes by scrolling and navigation, a low threshold (around 0.04) over the 1 fps
sequence works far better than a high one (0.15) over the original video, which only finds hard cuts.

Crop the browser chrome and shed weight before embedding:

```sh
ffmpeg -i shots/shot_0040.jpg -vf "crop=1000:640:120:60,scale=1000:-2" -q:v 6 slide.jpg
```

## Slides out of a video call recording

Full frames from a screen share are mostly useless: participant tiles eat part of the frame. Build one
labelled contact sheet per video first (a grid of small frames with mm:ss burned in, one every 15 s), read
it as an image to pick the timestamps that show a slide, then pull those frames at full size and crop the
tile strip:

```sh
mkdir -p sheet && ffmpeg -i call.mp4 -vf "fps=1/15,scale=640:-1" sheet/frame_%04d.jpg
# assemble a labelled grid with Pillow, look at it, pick timestamps
ffmpeg -ss 00:12:34 -i call.mp4 -frames:v 1 -vf "crop=1700:1080:0:0" slide.jpg
```

The tile strip's width shifts with the call layout; check one frame before batch cropping.

## Traps

- **`pgrep -f <pattern>` finds itself** when the waiting loop's own command line contains the pattern, so
  `while pgrep -f model.bin; do sleep 5; done` never ends
  ([[2026-09-23-trap-pkill-f-matches-its-own-wrapper-and-kills-the-shell]]).
- **Headless Chrome does not go below 500 px wide** with `--window-size`: a 390 px request renders at 500
  and crops, which looks like a horizontal overflow that does not exist. Check a phone layout with a real
  emulated viewport (Playwright device profiles) instead.
- Check a multi-page PDF built from these stills by rendering its pages (`pdftoppm`), not only by its page
  count ([[2026-09-10-convention-report-deliverable-shape]]).

## Links

- [[2026-08-24-convention-local-ocr-to-audit-text-in-images]]
