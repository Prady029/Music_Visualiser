# Music Visualiser

An in-browser and terminal live audio visualizer powered by perceptual OKLab/OKLCH color harmony, 18 HiDPI Canvas 2D modes, vizz.fm effects stack, and 29 themes.

**Live Web App:** https://prady029.github.io/Music_Visualiser/

## Why It Was Created

Built for a house-party vibe-coding competition — the goal was to put live party speaker/tab music straight onto a big screen in the browser with zero setup, reactive physics, and aesthetic color palettes. This in-browser visualizer took first place.

Created by **Pradyumna Kumar Sahoo** ([Portfolio](https://prady029.github.io) · [GitHub](https://github.com/Prady029)).

## Web Visualizer (`webapp` branch / `web/`)

Runs directly in the browser with no build step:

- **Speaker / Tab Audio** (`Capture Speaker`) — Captures live system or browser-tab audio via `getDisplayMedia`.
- **Mic / Virtual Loopback** (`Mic / Input`) — Captures microphone or loopback audio (such as BlackHole) via `getUserMedia`.
- **Audio Files & Drag-and-Drop** — Open or drop any local audio file onto the canvas.
- **Built-in 126 BPM Demo Synth** — Instant preview with a mute toggle (`🔊`).
- **18 Visual Modes & 29 OKLab/OKLCH Themes** — Includes Audio Tunnel (vizz.fm), Mesh Grid (vizz.fm), Particle Nebula (vizz.fm), Plasma Orb (vizz.fm), spectrum, mirror, curve, radial, hybrid, cymatics, faraday, vortex, horizon, starfield, wave, lissajous, stereo, and spectrogram modes.
- **vizz.fm Effect Stack** — Stackable real-time post-processing effects:
  - **Bloom (`B`)**: Glowing neon radiance reacting to audio beat spikes.
  - **Feedback Trails (`T`)**: Motion blur and hall-of-mirrors zoom decay.
  - **Kaleidoscope (`K`)**: Symmetrical 8-fold radial kaleidoscope mandala mirror.
  - **RGB Shift (`R`)**: Bass-reactive chromatic aberration and color fringe glitch.
  - **CRT (`X`)**: Retro phosphor scanlines and corner vignette.

### Run Locally

Because `getDisplayMedia`, `getUserMedia`, and ES modules require a secure context (`http://localhost`), serve `web/` over HTTP:

```sh
python3 -m http.server 8000 --directory web
```

Then open `http://localhost:8000/`.

## Terminal CLI (`visualizer.py` + `audio_tap.swift`)

This repository also includes the macOS terminal visualizer (`visualizer.py`) and CoreAudio tap helper (`audio_tap.swift`).
