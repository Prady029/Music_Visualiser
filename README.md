# Music Visualiser

An in-browser and terminal live audio visualizer powered by perceptual OKLab/OKLCH color harmony, 14 HiDPI Canvas 2D modes, and 29 themes.

**Live Web App:** https://prady029.github.io/Music_Visualiser/

## Why It Was Created

Built for a house-party vibe-coding competition — the goal was to put live party speaker/tab music straight onto a big screen in the browser with zero setup, reactive physics, and aesthetic color palettes. This in-browser visualizer took first place.

## Web Visualizer (`webapp` branch / `web/`)

Runs directly in the browser with no build step:

- **Speaker / Tab Audio** (`Capture Speaker`) — Captures live system or browser-tab audio via `getDisplayMedia`.
- **Mic / Virtual Loopback** (`Mic / Input`) — Captures microphone or loopback audio (such as BlackHole) via `getUserMedia`.
- **Audio Files & Drag-and-Drop** — Open or drop any local audio file onto the canvas.
- **Built-in 126 BPM Demo Synth** — Instant preview with a mute toggle (`🔊`).
- **14 Visual Modes & 29 OKLab/OKLCH Themes** — Includes spectrum, mirror, curve, radial, hybrid, cymatics, faraday, vortex, horizon, starfield, wave, lissajous, stereo, and spectrogram modes, plus `Snappy` / `Smooth` / `Silky` / `Liquid` smoothing and AGC.

### Run Locally

Because `getDisplayMedia`, `getUserMedia`, and ES modules require a secure context (`http://localhost`), serve `web/` over HTTP:

```sh
python3 -m http.server 8000 --directory web
```

Then open `http://localhost:8000/`.

## Terminal CLI (`visualizer.py` + `audio_tap.swift`)

This repository also includes the macOS terminal visualizer (`visualizer.py`) and CoreAudio tap helper (`audio_tap.swift`).
