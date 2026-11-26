#!/usr/bin/env python3
"""Full-screen real-time terminal music visualizer.

Captures live macOS speaker output via CoreAudio Process Tap (./audio_tap) by
default, or reads 16/24/32-bit PCM & IEEE-Float WAV files, ffmpeg AVFoundation
devices, or a phase-continuous built-in synth. Renders across HD Kitty pixels,
aspect-corrected 2x2 Quadrant blocks, or 2x4 Unicode Braille with OKLab/OKLCH
perceptual color harmony across 17 modes and 29 themes.
"""

import argparse
import base64
import collections
import fcntl
import functools
import math
import os
import select
import shutil
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
import traceback
import tty
import zlib
from typing import Optional

import numpy as np

_TRAPEZOID = getattr(np, "trapezoid", None) or getattr(np, "trapz")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_TAP_BIN = os.path.join(SCRIPT_DIR, "audio_tap")
AUDIO_TAP_SRC = os.path.join(SCRIPT_DIR, "audio_tap.swift")

BLOCKS_UP = " ▁▂▃▄▅▆▇█"
DENSITY_CHARS = " ░▒▓█"
QUAD_CHARS = " ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█"
RENDERERS = ("pixel", "blocks", "braille")
MC_METHODS = ("deterministic", "metropolis", "importance", "langevin")
SMOOTH_ORDER = ("snappy", "smooth", "silky", "liquid")
SMOOTH_PRESETS = {
    "snappy": {"tau_up": 0.012, "tau_dn": 0.055, "spatial": 0.15, "gravity": 1.80, "hold": 0.16},
    "smooth": {"tau_up": 0.022, "tau_dn": 0.105, "spatial": 0.35, "gravity": 1.25, "hold": 0.22},
    "silky":  {"tau_up": 0.036, "tau_dn": 0.160, "spatial": 0.55, "gravity": 0.90, "hold": 0.28},
    "liquid": {"tau_up": 0.055, "tau_dn": 0.240, "spatial": 0.75, "gravity": 0.65, "hold": 0.34},
}
MODES = (
    "spectrum", "mirror", "braille", "radial", "cymatics", "faraday", "vortex",
    "milkdrop", "hybrid", "starfield", "wave", "lissajous", "lorenz", "horizon",
    "spectrogram", "stereo", "scroll",
)
MODE_HOTKEYS = "1234567890!@#$%^&"
CELL_MODES = frozenset(("spectrum", "mirror", "stereo", "spectrogram", "scroll"))

# 24-bit RGB stops ordered bottom (low intensity) -> top (high intensity)
THEME_STOPS = {
    "aurora":         [(10, 120, 140), (0, 210, 175), (80, 240, 220), (145, 110, 255), (245, 115, 220)],
    "vermilion-teal": [(14, 72, 88), (28, 148, 165), (218, 212, 198), (242, 108, 62), (255, 178, 118)],
    "bioluminescent": [(18, 24, 72), (24, 88, 178), (0, 198, 194), (112, 246, 206), (228, 255, 246)],
    "solar-flare":    [(48, 16, 46), (148, 32, 62), (235, 88, 42), (255, 178, 52), (255, 244, 188)],
    "iridescent":     [(52, 34, 112), (96, 118, 224), (218, 134, 198), (248, 208, 152), (174, 246, 236), (52, 34, 112)],
    "tokyo-night":    [(61, 89, 161), (122, 162, 247), (125, 207, 255), (187, 154, 247), (247, 118, 142)],
    "catppuccin":     [(116, 199, 236), (180, 190, 254), (203, 166, 247), (245, 194, 231), (243, 139, 168)],
    "kanagawa":       [(126, 156, 216), (149, 127, 184), (118, 148, 106), (255, 158, 59), (195, 64, 67)],
    "everforest":     [(127, 187, 179), (167, 192, 128), (219, 188, 127), (230, 152, 117), (230, 126, 128)],
    "moonlight":      [(99, 109, 166), (130, 170, 255), (192, 153, 255), (255, 117, 127), (255, 199, 119)],
    "ayu":            [(57, 186, 230), (170, 217, 76), (255, 204, 102), (255, 143, 64), (240, 113, 120)],
    "cyberpunk":      [(0, 240, 255), (123, 44, 191), (255, 0, 127), (252, 238, 9)],
    "dracula":        [(98, 114, 164), (139, 233, 253), (189, 147, 249), (255, 121, 198), (80, 250, 123)],
    "nord":           [(67, 76, 94), (94, 129, 172), (129, 161, 193), (136, 192, 208), (236, 239, 244)],
    "rose-pine":      [(49, 116, 143), (156, 207, 216), (196, 167, 231), (246, 193, 119), (235, 111, 146)],
    "vaporwave":      [(84, 13, 110), (238, 66, 102), (255, 136, 209), (160, 231, 229), (59, 206, 172)],
    "sunset":         [(60, 22, 66), (143, 45, 86), (255, 94, 91), (255, 159, 28), (255, 234, 159)],
    "sakura":         [(92, 26, 51), (158, 59, 92), (224, 108, 159), (255, 179, 198), (255, 240, 243)],
    "obsidian":       [(55, 59, 72), (102, 108, 128), (184, 134, 11), (255, 209, 102), (255, 243, 209)],
    "emerald":        [(11, 61, 46), (29, 185, 84), (30, 215, 96), (158, 240, 26), (232, 255, 240)],
    "plasma":         [(46, 5, 143), (126, 3, 168), (204, 71, 120), (248, 149, 64), (240, 249, 33)],
    "gruvbox":        [(69, 133, 136), (152, 151, 26), (215, 153, 33), (214, 93, 14), (251, 73, 52)],
    "prism":          [(0, 245, 212), (0, 187, 249), (155, 93, 229), (241, 91, 181), (254, 228, 64), (0, 245, 212)],
    "synthwave":      [(85, 20, 155), (195, 35, 195), (255, 65, 165), (65, 225, 255), (235, 250, 255)],
    "ocean":          [(15, 40, 130), (20, 105, 225), (25, 185, 245), (105, 240, 255), (225, 252, 255)],
    "fire":           [(95, 10, 15), (195, 25, 15), (255, 95, 15), (255, 195, 40), (255, 248, 190)],
    "rainbow":        [(30, 140, 255), (0, 230, 210), (75, 245, 95), (250, 225, 45), (255, 120, 35), (255, 45, 75)],
    "matrix":         [(10, 75, 20), (20, 150, 45), (40, 225, 75), (130, 255, 145), (220, 255, 225)],
    "mono":           [(90, 95, 105), (155, 160, 170), (210, 215, 220), (255, 255, 255)],
}
THEMES = tuple(THEME_STOPS)

BRAILLE_BITS = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))

CHLADNI_MODES = (
    (0, 13.5, 0.0, 4, 10.5, 0.38), (3, 13.0, 0.22, 0, 15.5, 0.32),
    (4, 14.5, -0.18, 0, 12.0, 0.36), (5, 15.5, 0.26, 0, 17.5, 0.30),
    (6, 16.5, -0.22, 3, 11.5, 0.34), (7, 17.5, 0.20, 0, 19.5, 0.28),
    (8, 19.0, -0.26, 4, 13.0, 0.36), (6, 20.5, 0.16, 2, 15.0, 0.38),
    (9, 21.5, -0.20, 0, 17.0, 0.32), (5, 23.0, 0.24, 3, 18.5, 0.40),
)
FARADAY_MODES = (
    (5, 11.5, 0.35, 0.0), (6, 12.5, -0.30, 0.2), (7, 14.0, 0.28, 0.0), (8, 15.0, -0.25, 0.4),
    (6, 17.0, 0.32, 0.6), (9, 18.0, -0.22, 0.0), (10, 19.5, 0.26, 0.3), (7, 21.0, -0.30, 0.5),
)
VORTEX_MODES = (
    (2, 12.0, 4.5, 0.65), (3, 13.5, -5.2, -0.70), (4, 15.0, 6.0, 0.75), (5, 16.5, -6.5, -0.80),
    (6, 18.0, 7.2, 0.85), (3, 20.0, -8.0, -0.90), (7, 21.0, 8.5, 0.95), (4, 23.0, -9.5, -1.00),
)

# Precomputed Bessel J_m(z) and dJ_m/dz LUTs sized for max k=23 * max corner radius ~4.5
_BESSEL_Z_MAX, _BESSEL_N = 110.0, 2048
_BESSEL_INV_DZ = (_BESSEL_N - 1) / _BESSEL_Z_MAX
_BESSEL_Z = np.linspace(0.0, _BESSEL_Z_MAX, _BESSEL_N, dtype=np.float64)
_TAU = np.linspace(0.0, math.pi, 64, dtype=np.float64)[:, None]
_BESSEL_J = {
    m: (_TRAPEZOID(np.cos(_BESSEL_Z[None, :] * np.sin(_TAU) - m * _TAU), _TAU[:, 0], axis=0) / math.pi).astype(np.float32)
    for m in range(12)
}
_BESSEL_DJ = {0: -_BESSEL_J[1], **{m: (0.5 * (_BESSEL_J[m - 1] - _BESSEL_J[m + 1])).astype(np.float32) for m in range(1, 11)}}


def ensure_audio_tap_binary() -> bool:
    """Compile audio_tap.swift if missing or older than the Swift source."""
    has_bin = os.path.isfile(AUDIO_TAP_BIN) and os.access(AUDIO_TAP_BIN, os.X_OK)
    if not os.path.isfile(AUDIO_TAP_SRC):
        return has_bin
    if has_bin and os.path.getmtime(AUDIO_TAP_BIN) >= os.path.getmtime(AUDIO_TAP_SRC):
        return True
    cache_dir = "/tmp/swift_cache"
    os.makedirs(cache_dir, exist_ok=True)
    env = {**os.environ, "TMPDIR": "/tmp", "CLANG_MODULE_CACHE_PATH": cache_dir}
    cmd = ["swiftc", "-O", "-module-cache-path", cache_dir, AUDIO_TAP_SRC, "-o", AUDIO_TAP_BIN]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to compile audio_tap.swift:\n{res.stderr.strip()}")
    return True


# ---------------------------------------------------------------------------
# Perceptual OKLab / OKLCH Color Engine & Vectorized Terminal Color LUTs
# ---------------------------------------------------------------------------

def _build_xterm256_lut() -> np.ndarray:
    """Precompute a 32x32x32 5-bit RGB -> xterm-256 palette index LUT."""
    vals = np.arange(32, dtype=np.int32) * 8 + 4
    rr, gg, bb = np.meshgrid(vals, vals, vals, indexing="ij")
    rgb = np.stack((rr.ravel(), gg.ravel(), bb.ravel()), axis=1)
    levels = np.array([0, 95, 135, 175, 215, 255], dtype=np.int32)
    ri = np.argmin(np.abs(rgb[:, 0:1] - levels[None, :]), axis=1)
    gi = np.argmin(np.abs(rgb[:, 1:2] - levels[None, :]), axis=1)
    bi = np.argmin(np.abs(rgb[:, 2:3] - levels[None, :]), axis=1)
    cube_idx = 16 + 36 * ri + 6 * gi + bi
    cube_d = (levels[ri] - rgb[:, 0]) ** 2 + (levels[gi] - rgb[:, 1]) ** 2 + (levels[bi] - rgb[:, 2]) ** 2
    g_vals = np.arange(24, dtype=np.int32) * 10 + 8
    avg = np.round((rgb.mean(axis=1) - 8.0) / 10.0).astype(np.int32).clip(0, 23)
    gv = g_vals[avg]
    gray_d = (gv - rgb[:, 0]) ** 2 + (gv - rgb[:, 1]) ** 2 + (gv - rgb[:, 2]) ** 2
    return np.where(gray_d < cube_d, 232 + avg, cube_idx).astype(np.uint8).reshape(32, 32, 32)


_XTERM256_LUT = _build_xterm256_lut()


def detect_color_mode(requested: str) -> str:
    if requested != "auto":
        return requested
    ct = os.environ.get("COLORTERM", "").lower()
    tp = os.environ.get("TERM_PROGRAM", "").lower()
    if "truecolor" in ct or "24bit" in ct or tp in ("iterm.app", "ghostty", "wezterm", "vscode", "alacritty", "kitty", "warpterminal"):
        return "truecolor"
    return "256"


def detect_renderer(requested: str) -> str:
    if requested == "text":
        return "braille"
    if requested != "auto":
        return requested
    if os.environ.get("TMUX"):
        return "blocks"
    tp = os.environ.get("TERM_PROGRAM", "").lower()
    term = os.environ.get("TERM", "").lower()
    if tp in ("ghostty", "kitty", "wezterm") or "kitty" in term or "ghostty" in term or os.environ.get("KITTY_WINDOW_ID"):
        return "pixel"
    return "blocks"


def rgb_to_xterm256(r: int, g: int, b: int) -> int:
    return int(_XTERM256_LUT[r >> 3, g >> 3, b >> 3])


@functools.lru_cache(maxsize=4096)
def _ansi_fg_cached(rq: int, gq: int, bq: int, color_mode: str) -> str:
    if color_mode == "mono":
        return ""
    if color_mode == "truecolor":
        return f"\x1b[38;2;{rq};{gq};{bq}m"
    return f"\x1b[38;5;{rgb_to_xterm256(rq, gq, bq)}m"


def ansi_fg_from_rgb(rgb, color_mode: str) -> str:
    if color_mode == "mono":
        return ""
    return _ansi_fg_cached(int(rgb[0]) & 0xFC, int(rgb[1]) & 0xFC, int(rgb[2]) & 0xFC, color_mode)


def _srgb_to_oklab(rgb_u8: np.ndarray) -> np.ndarray:
    c = rgb_u8.astype(np.float64) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = lin[:, 0], lin[:, 1], lin[:, 2]
    l = np.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = np.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = np.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return np.column_stack((
        0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
    ))


def _oklab_to_srgb(lab: np.ndarray) -> np.ndarray:
    L, a, b = lab[:, 0], lab[:, 1], lab[:, 2]
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    lin = np.clip(np.column_stack((
        +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )), 0.0, 1.0)
    srgb = np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * (lin ** (1.0 / 2.4)) - 0.055)
    return np.clip(np.round(srgb * 255.0), 0, 255).astype(np.uint8)


_THEME_OKLAB = {name: _srgb_to_oklab(np.asarray(stops, dtype=np.uint8)) for name, stops in THEME_STOPS.items()}
_CHROME_CACHE = {}


def get_theme_chrome(theme: str) -> dict:
    """Derive 60-30-10 harmonious grid, axis, HUD, and complementary accent colors."""
    cached = _CHROME_CACHE.get(theme)
    if cached is not None:
        return cached
    lab = _THEME_OKLAB.get(theme, _THEME_OKLAB["aurora"])
    base, mid, top = lab[0], lab[len(lab) // 2], lab[-1]
    hue = math.atan2(mid[2], mid[1]) + math.radians(155.0)
    chroma = max(0.06, min(0.18, math.hypot(mid[1], mid[2]) * 1.15))
    is_mono = theme == "mono"
    labs = np.array([
        [0.34, base[1] * 0.25, base[2] * 0.25],
        [0.58, mid[1] * 0.35, mid[2] * 0.35],
        [0.21, base[1] * 0.28, base[2] * 0.28],
        [0.29, mid[1] * 0.55, mid[2] * 0.55],
        [max(0.84, float(top[0])), 0.0, 0.0] if is_mono else [max(0.84, min(0.94, float(top[0]) + 0.07)), chroma * math.cos(hue), chroma * math.sin(hue)],
    ], dtype=np.float64)
    rgbs = _oklab_to_srgb(labs)
    chrome = {k: rgbs[i] for i, k in enumerate(("grid_rgb", "axis_rgb", "hud_bg", "hud_beat", "accent_rgb"))}
    _CHROME_CACHE[theme] = chrome
    return chrome


@functools.lru_cache(maxsize=1024)
def _interp_rgb_cached(theme: str, steps: int, boost_q: int, phase_q: int) -> bytes:
    lab_stops = _THEME_OKLAB.get(theme, _THEME_OKLAB["aurora"])
    n_seg = len(lab_stops) - 1
    ts = np.linspace(0.0, 1.0, steps)
    if phase_q:
        ts = (ts + phase_q / 60.0) % 1.0
    scaled = ts * n_seg
    idx = np.minimum(n_seg - 1, np.floor(scaled).astype(np.int32))
    lab = lab_stops[idx] + (lab_stops[idx + 1] - lab_stops[idx]) * (scaled - idx)[:, None]
    if boost_q:
        b_amt = boost_q / 20.0
        lab = lab.copy()
        lab[:, 0] = np.clip(lab[:, 0] + (1.0 - lab[:, 0]) * (b_amt * 0.45), 0.0, 1.0)
        lab[:, 1:] *= 1.0 + b_amt * 0.12
    return _oklab_to_srgb(lab).tobytes()


def interpolate_rgb_array(theme: str, steps: int, boost: float = 0.0, phase: float = 0.0) -> np.ndarray:
    """Return a cached (steps, 3) uint8 LUT interpolated smoothly in perceptual OKLab space."""
    boost_q = int(round(max(0.0, min(0.5, boost)) * 20.0))
    phase_q = int(round((phase % 1.0) * 60.0)) % 60 if theme in ("prism", "iridescent") else 0
    buf = _interp_rgb_cached(theme, steps, boost_q, phase_q)
    return np.frombuffer(buf, dtype=np.uint8).reshape(steps, 3)


def interpolate_palette(theme: str, steps: int, color_mode: str, boost: float = 0.0, phase: float = 0.0):
    if color_mode == "mono":
        return [""] * steps
    return [ansi_fg_from_rgb(rgb, color_mode) for rgb in interpolate_rgb_array(theme, steps, boost, phase)]


# ---------------------------------------------------------------------------
# Audio Ring Buffer, Capture (WAV PCM16/24/32/Float32, CoreAudio, ffmpeg, Synth)
# ---------------------------------------------------------------------------

def _open_wav_stream(path: str):
    """Parse RIFF/WAV fmt + data chunks (supports PCM 16/24/32-bit and IEEE float32)."""
    f = open(path, "rb")
    try:
        riff = f.read(12)
        if len(riff) < 12 or riff[:4] != b"RIFF" or riff[8:12] != b"WAVE":
            raise RuntimeError("Not a valid RIFF/WAVE file.")
        audio_fmt = channels = rate = bits = None
        data_start = data_size = None
        while True:
            hdr = f.read(8)
            if len(hdr) < 8:
                break
            cid, csz = hdr[:4], struct.unpack("<I", hdr[4:8])[0]
            if cid == b"fmt ":
                fmt_bytes = f.read(csz)
                audio_fmt, channels, rate, _, block_align, bits = struct.unpack("<HHIIHH", fmt_bytes[:16])
                if audio_fmt == 0xFFFE and len(fmt_bytes) >= 40:  # WAVE_FORMAT_EXTENSIBLE
                    audio_fmt = struct.unpack("<H", fmt_bytes[24:26])[0]
            elif cid == b"data":
                data_start, data_size = f.tell(), csz
                break
            else:
                f.seek(csz, os.SEEK_CUR)
            if csz & 1:
                f.seek(1, os.SEEK_CUR)
        if audio_fmt not in (1, 3) or bits not in (16, 24, 32) or data_start is None:
            raise RuntimeError(f"Unsupported WAV format (fmt={audio_fmt}, bits={bits}).")
        return f, audio_fmt, channels, rate, bits, data_start, data_size
    except Exception:
        f.close()
        raise


def _decode_wav_chunk(raw: bytes, audio_fmt: int, channels: int, bits: int) -> np.ndarray:
    if audio_fmt == 3 and bits == 32:
        arr = np.frombuffer(raw, dtype="<f4")
    elif bits == 16:
        arr = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif bits == 32:
        arr = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:  # 24-bit signed LE PCM
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        i32 = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
        i32 = np.where(i32 & 0x800000, i32 - 0x1000000, i32)
        arr = i32.astype(np.float32) / 8388608.0
    return np.column_stack((arr, arr)) if channels == 1 else arr.reshape(-1, channels)[:, :2]


class AudioRingBuffer:
    def __init__(self, capacity_frames: int = 32768):
        self.capacity = capacity_frames
        self.buf = np.zeros((capacity_frames, 2), dtype=np.float32)
        self.write_pos = 0
        self.lock = threading.Lock()
        self.sample_rate = 48000
        self.last_data_time = 0.0

    def push(self, frames: np.ndarray):
        n = frames.shape[0]
        if n == 0:
            return
        if n >= self.capacity:
            frames, n = frames[-self.capacity :], self.capacity
        with self.lock:
            end = self.write_pos + n
            if end <= self.capacity:
                self.buf[self.write_pos : end] = frames
            else:
                first = self.capacity - self.write_pos
                self.buf[self.write_pos :] = frames[:first]
                self.buf[: n - first] = frames[first:]
            self.write_pos = end % self.capacity
            self.last_data_time = time.monotonic()

    def read_latest(self, n_frames: int) -> np.ndarray:
        n = min(n_frames, self.capacity)
        with self.lock:
            idx = self.write_pos
            if idx >= n:
                return self.buf[idx - n : idx].copy()
            return np.vstack((self.buf[self.capacity - (n - idx) :], self.buf[:idx]))


class AudioCapture:
    """Background capture from CoreAudio speaker tap, ffmpeg, WAV, or phase-continuous demo synth."""

    def __init__(self, args, ring: AudioRingBuffer):
        self.args = args
        self.ring = ring
        self.stop_event = threading.Event()
        self.proc = self.aux_proc = self.error = None
        self.source_label = ""
        self.ended = False
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        for p in (self.proc, self.aux_proc):
            if p is not None and p.poll() is None:
                try:
                    p.terminate()
                    p.wait(timeout=0.5)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass

    def _run(self):
        try:
            {"demo": self._run_demo, "wav": self._run_wav, "ffmpeg": self._run_ffmpeg}.get(
                self.args.source, self._run_speaker_tap
            )()
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error = str(exc)

    def _read_f32_stream(self, channels: int, name: str):
        err_lines = collections.deque(maxlen=32)

        def drain_stderr():
            try:
                for line in self.proc.stderr:
                    err_lines.append(line.decode("utf-8", errors="replace").rstrip())
            except Exception:
                pass

        t_err = threading.Thread(target=drain_stderr, daemon=True)
        t_err.start()

        frame_bytes = channels * 4
        read_bytes = 512 * frame_bytes
        pending = b""
        while not self.stop_event.is_set():
            chunk = self.proc.stdout.read(read_bytes)
            if not chunk:
                rc = self.proc.wait()
                t_err.join(timeout=0.2)
                if rc not in (None, 0) and not self.stop_event.is_set():
                    raise RuntimeError("\n".join(err_lines) or f"{name} exited unexpectedly (code {rc}).")
                self.ended = True
                break
            raw = pending + chunk
            usable = len(raw) - (len(raw) % frame_bytes)
            pending = raw[usable:]
            if usable == 0:
                continue
            arr = np.frombuffer(raw[:usable], dtype=np.float32).reshape(-1, channels)
            if channels == 1:
                arr = np.column_stack((arr[:, 0], arr[:, 0]))
            self.ring.push(arr[:, :2])

    def _run_speaker_tap(self):
        self.source_label = "Speaker Output (CoreAudio)"
        if not ensure_audio_tap_binary():
            raise RuntimeError(f"Could not find or compile {AUDIO_TAP_BIN}.")
        self.proc = subprocess.Popen([AUDIO_TAP_BIN], stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        header = self.proc.stdout.readline().decode("utf-8", errors="replace").strip()
        if not header.startswith("MVIZ "):
            err = self.proc.stderr.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(err or f"audio_tap failed to start (header: {header!r}).")
        _, rate_s, ch_s = header.split()[:3]
        self.ring.sample_rate = int(rate_s)
        self._read_f32_stream(int(ch_s), "audio_tap")

    def _run_ffmpeg(self):
        dev = self.args.device
        self.source_label = f"AVFoundation ({dev})"
        self.ring.sample_rate = 48000
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "avfoundation",
            "-i", f":{dev}", "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "2", "-ar", "48000", "pipe:1",
        ]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self._read_f32_stream(2, "ffmpeg")

    def _run_wav(self):
        wav_path = self.args.wav
        if not wav_path or not os.path.isfile(wav_path):
            raise RuntimeError(f"WAV file not found: {wav_path}")
        self.source_label = f"WAV ({os.path.basename(wav_path)})"
        f, audio_fmt, channels, rate, bits, data_start, data_size = _open_wav_stream(wav_path)
        self.ring.sample_rate = rate
        frame_bytes = channels * (bits // 8)
        chunk_frames = max(int(rate * 0.015), 256)
        chunk_bytes = chunk_frames * frame_bytes
        chunk_sec = chunk_frames / float(rate)

        def start_afplay():
            if self.args.play and sys.platform == "darwin":
                if self.aux_proc and self.aux_proc.poll() is None:
                    self.aux_proc.terminate()
                self.aux_proc = subprocess.Popen(["afplay", wav_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        try:
            start_afplay()
            rem = data_size
            next_tick = time.monotonic()
            while not self.stop_event.is_set():
                to_read = min(chunk_bytes, rem)
                to_read -= to_read % frame_bytes
                raw = f.read(to_read) if to_read > 0 else b""
                if not raw:
                    if self.args.loop:
                        f.seek(data_start)
                        rem = data_size
                        start_afplay()
                        continue
                    self.ended = True
                    break
                rem -= len(raw)
                self.ring.push(_decode_wav_chunk(raw, audio_fmt, channels, bits))
                next_tick += chunk_sec
                delay = next_tick - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_tick = time.monotonic()
        finally:
            f.close()

    def _run_demo(self):
        self.source_label = "Demo Synth (126 BPM)"
        rate, chunk_frames = 48000, 512
        self.ring.sample_rate = rate
        chunk_sec = chunk_frames / float(rate)
        rng = np.random.default_rng()
        bass_notes = (55.0, 55.0, 65.41, 73.42, 55.0, 55.0, 82.41, 73.42)
        arp_notes = (220.0, 261.63, 329.63, 440.0, 523.25, 440.0, 329.63, 392.0)

        t_offset = 0
        kick_ph = sub_ph = sub2_ph = arp_ph = arp2_ph = arp3_ph = 0.0
        next_tick = time.monotonic()

        while not self.stop_event.is_set():
            sample_idx = np.arange(t_offset, t_offset + chunk_frames, dtype=np.float64)
            t = sample_idx / rate
            t_offset += chunk_frames

            beat_pos = (t * 2.1) % 1.0
            f_kick = 48.0 + 95.0 * np.exp(-beat_pos * 24.0)
            k_phases = kick_ph + 2.0 * np.pi * np.cumsum(f_kick) / rate
            kick_ph = float(k_phases[-1] % (2.0 * np.pi))
            kick = np.exp(-beat_pos * 13.5) * np.sin(k_phases)

            bf = bass_notes[(int(t[0] * 2.1)) % len(bass_notes)]
            s_phases = sub_ph + np.cumsum(np.full(chunk_frames, 2.0 * np.pi * bf / rate))
            sub_ph = float(s_phases[-1] % (2.0 * np.pi))
            s2_phases = sub2_ph + np.cumsum(np.full(chunk_frames, 4.0 * np.pi * bf / rate))
            sub2_ph = float(s2_phases[-1] % (2.0 * np.pi))
            sub = 0.25 * np.sin(s_phases) + 0.12 * np.sin(s2_phases)

            af = arp_notes[(int(t[0] * 8.4)) % len(arp_notes)]
            a1 = arp_ph + np.cumsum(np.full(chunk_frames, 2.0 * np.pi * af / rate))
            a2 = arp2_ph + np.cumsum(np.full(chunk_frames, 4.0 * np.pi * af / rate))
            a3 = arp3_ph + np.cumsum(np.full(chunk_frames, 6.0 * np.pi * af / rate))
            arp_ph, arp2_ph, arp3_ph = float(a1[-1] % (2.0 * np.pi)), float(a2[-1] % (2.0 * np.pi)), float(a3[-1] % (2.0 * np.pi))
            arp = np.exp(-((t * 8.4) % 1.0) * 5.0) * (0.22 * np.sin(a1) + 0.14 * np.sin(a2) + 0.08 * np.sin(a3))

            snare = np.exp(-(((t * 2.1) + 0.5) % 1.0) * 22.0) * rng.normal(0.0, 0.22, chunk_frames)
            hihat = np.exp(-((t * 8.4) % 1.0) * 32.0) * rng.normal(0.0, 0.12, chunk_frames)
            pan = 0.5 + 0.45 * np.sin(2.0 * np.pi * 0.35 * t)
            left = (0.55 * kick + sub + 0.9 * snare + arp * (1.2 - pan * 0.5) + hihat * 0.8).astype(np.float32)
            right = (0.55 * kick + sub + 0.9 * snare + arp * (0.7 + pan * 0.5) + hihat * 1.1).astype(np.float32)
            self.ring.push(np.column_stack((left, right)))

            next_tick += chunk_sec
            delay = next_tick - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_tick = time.monotonic()


# ---------------------------------------------------------------------------
# Multi-Resolution SpectrumAnalyzer, Power-Mean Matrix, Flux Onset & Autocorrelation BPM
# ---------------------------------------------------------------------------

def _build_band_matrix(fft_size: int, sample_rate: int, edges_hz: np.ndarray, lo_idx: int, hi_idx: int) -> np.ndarray:
    """Build normalized power-aggregation weight matrix W of shape (hi_idx - lo_idx, fft_size//2 + 1)."""
    n_bins = fft_size // 2 + 1
    n_sub = hi_idx - lo_idx
    W = np.zeros((n_sub, n_bins), dtype=np.float32)
    freq_per_bin = sample_rate / float(fft_size)
    max_bin = fft_size // 2
    for row, bi in enumerate(range(lo_idx, hi_idx)):
        f0, f1 = float(edges_hz[bi]), float(edges_hz[bi + 1])
        pos0 = max(1.0, min(f0 / freq_per_bin, max_bin - 1.001))
        pos1 = max(pos0, min(f1 / freq_per_bin, max_bin - 0.001))
        b0, b1 = int(math.floor(pos0)), int(math.ceil(pos1))
        if b1 <= b0 + 1:
            center = 0.5 * (pos0 + pos1)
            lo = max(0, min(max_bin - 1, int(math.floor(center))))
            frac = center - lo
            W[row, lo] = 1.0 - frac
            W[row, lo + 1] += frac
        else:
            sl = slice(b0, min(b1, max_bin + 1))
            count = max(1, (min(b1, max_bin + 1) - b0))
            W[row, sl] = 1.0 / count
    return W


class SpectrumAnalyzer:
    """Dual-resolution FFT analyzer with RMS/power band aggregation, silence-safe AGC, and flux+autocorr BPM."""

    def __init__(self, base_fft_size: int):
        self.low_fft = max(base_fft_size, 8192)
        self.hi_fft = min(base_fft_size, 1024)
        self.onset_fft = 2048
        self.w_low = np.blackman(self.low_fft).astype(np.float32)
        self.w_hi = np.hanning(self.hi_fft).astype(np.float32)
        self.w_onset = np.hanning(self.onset_fft).astype(np.float32)
        self.ring_needed = max(base_fft_size, self.low_fft)

        self._cached_layout = None
        self.plan = []
        self.n_split = 0
        self.W_low = self.W_hi = None
        self.tilts = None

        self.agc_scale = 0.35
        self.prev_onset_mag = None
        self.flux_hist = collections.deque()   # (timestamp, flux) over last 1.5s
        self.onset_grid = collections.deque(maxlen=200)  # 50 Hz uniform envelope (4.0s)
        self.onset_grid_t = 0.0
        self.last_beat_t = 0.0
        self.beat_flash = 0.0
        self.bpm = 0.0
        self._onset_accum = 0.0

    def configure(self, num_bars: int, sample_rate: int, f_min: float = 40.0, f_max: float = 16500.0):
        key = (num_bars, sample_rate)
        if key == self._cached_layout:
            return
        self._cached_layout = key
        nyq = sample_rate * 0.5
        f_hi = min(f_max, nyq * 0.95)
        f_lo = min(f_min, f_hi * 0.25)
        edges_hz = np.geomspace(f_lo, f_hi, num_bars + 1)
        centers = np.sqrt(edges_hz[:-1] * edges_hz[1:])
        self.plan = [(float(edges_hz[i]), float(edges_hz[i + 1]), 0.0, float(c)) for i, c in enumerate(centers)]
        self.tilts = ((centers / 380.0) ** 0.34).astype(np.float32)
        self.n_split = int(np.searchsorted(centers, 280.0))
        self.W_low = _build_band_matrix(self.low_fft, sample_rate, edges_hz, 0, self.n_split) if self.n_split > 0 else None
        self.W_hi = _build_band_matrix(self.hi_fft, sample_rate, edges_hz, self.n_split, num_bars) if self.n_split < num_bars else None

    def compute_bands(self, sig_1d: np.ndarray) -> np.ndarray:
        """Return log-compressed weighted RMS magnitude for every frequency bar."""
        parts = []
        if self.W_low is not None:
            buf = sig_1d[-self.low_fft :]
            if len(buf) < self.low_fft:
                buf = np.pad(buf, (self.low_fft - len(buf), 0))
            buf = buf - np.mean(buf)
            mag_sq = (np.abs(np.fft.rfft(buf * self.w_low)) * (2.0 / self.low_fft)) ** 2
            parts.append(np.sqrt(np.maximum(0.0, self.W_low @ mag_sq)))
        if self.W_hi is not None:
            buf = sig_1d[-self.hi_fft :]
            if len(buf) < self.hi_fft:
                buf = np.pad(buf, (self.hi_fft - len(buf), 0))
            buf = buf - np.mean(buf)
            mag_sq = (np.abs(np.fft.rfft(buf * self.w_hi)) * (2.0 / self.hi_fft)) ** 2
            parts.append(np.sqrt(np.maximum(0.0, self.W_hi @ mag_sq)))
        amp = np.concatenate(parts) * self.tilts if len(parts) == 2 else parts[0] * self.tilts
        return np.log1p(amp * 48.0).astype(np.float32)

    def update_onset_and_bpm(self, mono: np.ndarray, sample_rate: int, now: float, dt: float, silent: bool) -> float:
        """Mode-independent 40-150 Hz spectral flux onset + autocorrelation BPM estimator."""
        self.beat_flash = max(0.0, self.beat_flash - dt * 4.5)
        buf = mono[-self.onset_fft :]
        if len(buf) < self.onset_fft:
            buf = np.pad(buf, (self.onset_fft - len(buf), 0))
        buf = buf - np.mean(buf)
        mag = np.abs(np.fft.rfft(buf * self.w_onset)) * (2.0 / self.onset_fft)
        hz_per_bin = sample_rate / float(self.onset_fft)
        lo_b, hi_b = max(1, int(40.0 / hz_per_bin)), min(len(mag), max(4, int(150.0 / hz_per_bin)) + 1)
        sub_mag = mag[lo_b:hi_b]

        flux = 0.0
        if not silent and self.prev_onset_mag is not None and len(self.prev_onset_mag) == len(sub_mag):
            flux = float(np.sum(np.maximum(0.0, sub_mag - self.prev_onset_mag)))
        self.prev_onset_mag = sub_mag.copy()

        self.flux_hist.append((now, flux))
        cutoff = now - 1.5
        while self.flux_hist and self.flux_hist[0][0] < cutoff:
            self.flux_hist.popleft()

        # Maintain 50 Hz uniform onset envelope for autocorrelation tempo tracking
        self._onset_accum += dt
        if self._onset_accum >= 0.02:
            steps = min(4, int(self._onset_accum / 0.02))
            self._onset_accum -= steps * 0.02
            for _ in range(steps):
                self.onset_grid.append(flux)

        if len(self.flux_hist) >= 15 and not silent:
            vals = np.array([v for _, v in self.flux_hist], dtype=np.float32)
            mean_f, std_f = float(np.mean(vals)), float(np.std(vals))
            if flux > max(mean_f * 1.65, mean_f + 1.6 * std_f) and (now - self.last_beat_t) > 0.24:
                self.last_beat_t = now
                self.beat_flash = 1.0
                if len(self.onset_grid) >= 100:
                    env = np.asarray(self.onset_grid, dtype=np.float32)
                    env = np.maximum(0.0, env - np.mean(env))
                    if float(np.max(env)) > 1e-6:
                        ac = np.correlate(env, env, mode="full")[len(env) - 1 :]
                        # Lags 17..46 at 50 Hz correspond to 65.2 .. 176.5 BPM
                        lags = np.arange(17, min(47, len(ac)))
                        if len(lags) > 0:
                            # Mild bias toward ~115-125 BPM breaks harmonic ties naturally
                            weight = np.exp(-0.5 * ((lags - 25.0) / 14.0) ** 2)
                            best_lag = int(lags[int(np.argmax(ac[lags] * weight))])
                            bpm_est = 3000.0 / best_lag  # 60 * 50 Hz / lag
                            self.bpm = bpm_est if self.bpm == 0.0 else (0.75 * self.bpm + 0.25 * bpm_est)
        return self.beat_flash

    def normalize(self, raw: np.ndarray, dt: float, auto_gain: bool, silent: bool) -> np.ndarray:
        if auto_gain and not silent and len(raw) > 0:
            target = max(0.08, float(np.percentile(raw, 96)))
            alpha = 1.0 - math.exp(-dt / (0.09 if target > self.agc_scale else 2.4))
            self.agc_scale = max(0.08, self.agc_scale + alpha * (target - self.agc_scale))
        return np.clip(raw / (self.agc_scale if auto_gain else 1.5), 0.0, 1.0)


def spatial_smooth(arr: np.ndarray, strength: float) -> np.ndarray:
    if strength <= 0.0 or len(arr) < 5:
        return arr
    kernel = np.array([0.08, 0.22, 0.40, 0.22, 0.08], dtype=np.float32)
    filtered = np.convolve(np.pad(arr, 2, mode="edge"), kernel, mode="valid")
    return (1.0 - strength) * arr + strength * filtered


def cubic_upsample(values: np.ndarray, out_len: int, periodic: bool = False) -> np.ndarray:
    n = len(values)
    if n < 4 or out_len <= n:
        return np.interp(np.linspace(0.0, 1.0, out_len), np.linspace(0.0, 1.0, n), values).astype(np.float32)
    if periodic:
        t = np.linspace(0.0, float(n), out_len, endpoint=False)
        idx = np.floor(t).astype(np.int32) % n
        u = (t - np.floor(t)).astype(np.float32)
        p0, p1, p2, p3 = values[(idx - 1) % n], values[idx], values[(idx + 1) % n], values[(idx + 2) % n]
    else:
        t = np.linspace(0.0, float(n - 1), out_len)
        idx = np.minimum(n - 2, np.floor(t).astype(np.int32))
        u = (t - idx).astype(np.float32)
        p0 = values[np.maximum(0, idx - 1)]
        p1, p2 = values[idx], values[np.minimum(n - 1, idx + 1)]
        p3 = values[np.minimum(n - 1, idx + 2)]
    u2 = u * u
    out = 0.5 * (2.0 * p1 + (-p0 + p2) * u + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * u2 + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * (u2 * u))
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def advance_peaks(smooth: np.ndarray, peaks: np.ndarray, vel: np.ndarray, hold: np.ndarray, dt: float, gravity: float, hold_sec: float):
    hi = smooth >= peaks
    peaks[:] = np.where(hi, smooth, peaks)
    vel[:] = np.where(hi, 0.0, vel + dt * gravity)
    hold[:] = np.where(hi, hold_sec, hold - dt)
    falling = (~hi) & (hold <= 0.0)
    peaks[:] = np.where(falling, np.maximum(0.0, peaks - vel * dt), peaks)


# ---------------------------------------------------------------------------
# Terminal & Framebuffer Renderers (Kitty Pixel / Aspect-True Blocks / Braille)
# ---------------------------------------------------------------------------

class TerminalCanvas:
    """Alternate-screen ANSI/Kitty renderer with safe signal cleanup & escape parsing."""

    def __init__(self):
        self.fd_out = sys.stdout.fileno()
        self.fd_in = sys.stdin.fileno()
        self.is_tty = os.isatty(self.fd_in)
        self.old_termios = None
        self.resized = True
        self._active = False
        self._in_buf = bytearray()

    def __enter__(self):
        if self.is_tty:
            self.old_termios = termios.tcgetattr(self.fd_in)
            tty.setcbreak(self.fd_in)
        self._write("\x1b[?1049h\x1b[?25l\x1b[2J")
        self._active = True
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._active:
            self._write("\x1b_Ga=d,d=I,i=1,q=2\x1b\\\x1b[0m\x1b[?25h\x1b[?1049l")
            self._active = False
        if self.old_termios is not None:
            try:
                termios.tcsetattr(self.fd_in, termios.TCSADRAIN, self.old_termios)
            except Exception:
                pass

    def _write(self, text: str):
        data = text.encode("utf-8", errors="replace")
        view, total, written = memoryview(data), len(data), 0
        while written < total:
            try:
                n = os.write(self.fd_out, view[written:])
                if n <= 0:
                    break
                written += n
            except BlockingIOError:
                time.sleep(0.001)
            except OSError:
                break

    def probe_kitty(self) -> bool:
        """Query terminal for Kitty Graphics Protocol support before enabling auto pixel mode."""
        if not (self.is_tty and os.isatty(self.fd_out)):
            return False
        self._write("\x1b_Gi=31,s=1,v=1,a=q,t=d,f=24;AAAA\x1b\\\x1b[c")
        deadline = time.monotonic() + 0.08
        resp = bytearray()
        while time.monotonic() < deadline:
            rem = max(0.005, deadline - time.monotonic())
            if not select.select([self.fd_in], [], [], rem)[0]:
                break
            try:
                chunk = os.read(self.fd_in, 4096)
            except OSError:
                break
            if not chunk:
                break
            resp.extend(chunk)
            if b"\x1b_G" in resp and b"c" in resp:
                break
        return b"\x1b_G" in resp and b"OK" in resp

    def clear_kitty(self):
        self._write("\x1b_Ga=d,d=I,i=1,q=2\x1b\\\x1b[2J")

    def clear_screen(self):
        self._write("\x1b[2J")

    def render_frame(self, lines):
        self._write("\x1b[?2026h\x1b[H" + "\r\n".join(lines) + "\x1b[0m\x1b[?2026l")

    def render_pixel_frame(self, rgba: np.ndarray, cols: int, rows: int, canvas_h: int, top_hud: Optional[str] = None, axis_bar: Optional[str] = None, bot_hud: Optional[str] = None):
        ph, pw, _ = rgba.shape
        rgb24 = (rgba[:, :, :3].astype(np.float32) * (rgba[:, :, 3:4].astype(np.float32) * (1.0 / 255.0))).astype(np.uint8)
        b64 = base64.standard_b64encode(zlib.compress(rgb24.tobytes(), level=1)).decode("ascii")
        parts = ["\x1b[?2026h"]
        top_row = 1
        if top_hud is not None:
            parts.append(f"\x1b[1;1H{top_hud}")
            top_row = 2
        if axis_bar is not None:
            parts.append(f"\x1b[{top_row + canvas_h};1H{axis_bar}")
        if bot_hud is not None:
            parts.append(f"\x1b[{rows};1H{bot_hud}")
        parts.append(f"\x1b[{top_row};1H")
        total = len(b64)
        for off in range(0, total, 4096):
            chunk = b64[off : off + 4096]
            more = 1 if off + 4096 < total else 0
            if off == 0:
                parts.append(f"\x1b_Ga=T,f=24,s={pw},v={ph},c={cols},r={canvas_h},i=1,p=1,C=1,q=2,o=z,m={more};{chunk}\x1b\\")
            else:
                parts.append(f"\x1b_Gm={more};{chunk}\x1b\\")
        parts.append("\x1b[0m\x1b[?2026l")
        self._write("".join(parts))

    def read_keys(self):
        """Parse UTF-8 chars and complete CSI/Alt escape sequences without choking on multi-byte input."""
        if not self.is_tty:
            return []
        while select.select([self.fd_in], [], [], 0)[0]:
            try:
                chunk = os.read(self.fd_in, 4096)
            except OSError:
                break
            if not chunk:
                break
            self._in_buf.extend(chunk)

        keys = []
        buf = self._in_buf
        i, n = 0, len(buf)
        while i < n:
            b = buf[i]
            if b == 0x1B:
                if i + 1 >= n:
                    if not select.select([self.fd_in], [], [], 0.004)[0]:
                        keys.append("ESC")
                        i += 1
                        continue
                    try:
                        more = os.read(self.fd_in, 64)
                        buf.extend(more)
                        n = len(buf)
                    except OSError:
                        keys.append("ESC")
                        i += 1
                        continue
                nxt = buf[i + 1]
                if nxt == ord("["):  # Full CSI sequence: ESC [ <params> <final 0x40..0x7E>
                    j = i + 2
                    while j < n and not (0x40 <= buf[j] <= 0x7E):
                        j += 1
                    if j < n:
                        final = chr(buf[j])
                        params = buf[i + 2 : j].decode("ascii", errors="ignore")
                        if final in ("A", "B", "C", "D") and not params:
                            keys.append(f"ARROW_{final}")
                        else:
                            keys.append(f"CSI_{params}{final}")
                        i = j + 1
                        continue
                    break  # incomplete CSI wait next cycle
                elif nxt == ord("O") and i + 2 < n:
                    keys.append(f"SS3_{chr(buf[i + 2])}")
                    i += 3
                else:
                    keys.append(f"ALT_{chr(nxt)}")
                    i += 2
            elif b < 0x80:
                keys.append(chr(b))
                i += 1
            else:
                seq_len = 2 if (b & 0xE0) == 0xC0 else (3 if (b & 0xF0) == 0xE0 else (4 if (b & 0xF8) == 0xF0 else 1))
                if i + seq_len > n:
                    break
                ch = bytes(buf[i : i + seq_len]).decode("utf-8", errors="ignore")
                if ch:
                    keys.append(ch)
                i += seq_len
        del buf[:i]
        return keys


def query_terminal_pixel_size(fd_out: int, rows: int, cols: int, canvas_h: int):
    xp = yp = 0
    if os.isatty(fd_out):
        try:
            _, _, xp, yp = struct.unpack("HHHH", fcntl.ioctl(fd_out, termios.TIOCGWINSZ, b"\x00" * 8))
        except Exception:
            xp = yp = 0
    if xp <= 0 or yp <= 0:
        xp, yp = cols * 10, rows * 20
    canvas_yp = max(40, int(round(yp * (canvas_h / max(1, rows)))))
    scale = min(1.0, 680.0 / max(xp, canvas_yp))
    return max(120, int(round(xp * scale))), max(60, int(round(canvas_yp * scale)))


_XTERM_FG_SOLO = tuple(f"\x1b[38;5;{i}m\x1b[49m" for i in range(256))


def render_quadrant_lines(rgba: np.ndarray, cols: int, height: int, color_mode: str):
    """Vectorized 2x2 Quadrant renderer using precomputed 5-bit xterm-256 LUT."""
    rgb = (rgba[:, :, :3].astype(np.float32) * (rgba[:, :, 3:4].astype(np.float32) / 255.0)).astype(np.uint8)
    cells = rgb.reshape(height, 2, cols, 2, 3).transpose(0, 2, 1, 3, 4).reshape(height, cols, 4, 3)
    lum = cells[:, :, :, 0].astype(np.int32) * 3 + cells[:, :, :, 1].astype(np.int32) * 6 + cells[:, :, :, 2].astype(np.int32)
    l_min, l_max = lum.min(axis=2, keepdims=True), lum.max(axis=2, keepdims=True)
    fg_mask = (lum > ((l_min + l_max) >> 1)) | ((l_max == l_min) & (l_max > 20))
    bits = sum(fg_mask[:, :, i].astype(np.int32) << i for i in range(4))
    bg_mask = ~fg_mask
    fg_rgb = ((cells * fg_mask[:, :, :, None]).sum(axis=2) // np.maximum(1, fg_mask.sum(axis=2, keepdims=True))).astype(np.uint8)
    bg_rgb = ((cells * bg_mask[:, :, :, None]).sum(axis=2) // np.maximum(1, bg_mask.sum(axis=2, keepdims=True))).astype(np.uint8)

    use_tc, use_mono = color_mode == "truecolor", color_mode == "mono"
    bits_l = bits.tolist()
    lmax_l = l_max[:, :, 0].tolist()
    hbg_l = ((bg_rgb.sum(axis=2) > 18) & (bits != 15)).tolist()
    if use_tc:
        fg_l, bg_l = fg_rgb.tolist(), bg_rgb.tolist()
    elif not use_mono:
        fg_l = _XTERM256_LUT[fg_rgb[:, :, 0] >> 3, fg_rgb[:, :, 1] >> 3, fg_rgb[:, :, 2] >> 3].tolist()
        bg_l = _XTERM256_LUT[bg_rgb[:, :, 0] >> 3, bg_rgb[:, :, 1] >> 3, bg_rgb[:, :, 2] >> 3].tolist()

    lines = []
    for r in range(height):
        row_out, last_key = [], None
        b_row, l_row, hbg_row = bits_l[r], lmax_l[r], hbg_l[r]
        if use_tc:
            fg_r, bg_r = fg_l[r], bg_l[r]
        elif not use_mono:
            fg_r, bg_r = fg_l[r], bg_l[r]
        for c in range(cols):
            b = b_row[c]
            if b == 0 and l_row[c] <= 20:
                if last_key is not None:
                    row_out.append("\x1b[0m")
                    last_key = None
                row_out.append(" ")
                continue
            ch = QUAD_CHARS[b]
            if use_mono:
                row_out.append(ch)
                continue
            hbg = hbg_row[c]
            if use_tc:
                fr, fg_v, fb = fg_r[c]
                if hbg:
                    br, bg_v, bb = bg_r[c]
                    key = (fr, fg_v, fb, br, bg_v, bb)
                    if key != last_key:
                        row_out.append(f"\x1b[38;2;{fr};{fg_v};{fb};48;2;{br};{bg_v};{bb}m")
                        last_key = key
                else:
                    key = (fr, fg_v, fb)
                    if key != last_key:
                        row_out.append(f"\x1b[38;2;{fr};{fg_v};{fb}m\x1b[49m")
                        last_key = key
            else:
                fi = fg_r[c]
                if hbg:
                    bi = bg_r[c]
                    key = (fi, bi)
                    if key != last_key:
                        row_out.append(f"\x1b[38;5;{fi};48;5;{bi}m")
                        last_key = key
                else:
                    if fi != last_key:
                        row_out.append(_XTERM_FG_SOLO[fi])
                        last_key = fi
            row_out.append(ch)
        if last_key is not None:
            row_out.append("\x1b[0m")
        lines.append("".join(row_out))
    return lines


def rgba_to_braille_grid(rgba: np.ndarray, chars, col_grid, cols: int, height: int, color_mode: str):
    """Vectorized 2x4 Braille downsample preserving OKLab hues via precomputed 256 LUT."""
    ph, pw, _ = rgba.shape
    if ph < height * 4 or pw < cols * 2:
        return
    blk = rgba[: height * 4, : cols * 2]
    a = blk[:, :, 3].reshape(height, 4, cols, 2).transpose(0, 2, 1, 3)
    lit = a > 55
    masks = np.zeros((height, cols), dtype=np.int32)
    for dy in range(4):
        for dx in range(2):
            masks |= np.where(lit[:, :, dy, dx], BRAILLE_BITS[dx][dy], 0)
    nz = np.argwhere(masks > 0)
    if len(nz) == 0:
        return
    rgb_cells = blk[:, :, :3].astype(np.float32).reshape(height, 4, cols, 2, 3).transpose(0, 2, 1, 3, 4)
    w = np.where(lit, a.astype(np.float32), 0.0)[:, :, :, :, None]
    avg_rgb = np.clip((rgb_cells * w).sum(axis=(2, 3)) / np.maximum(1.0, w.sum(axis=(2, 3))), 0, 255).astype(np.uint8)
    if color_mode == "mono":
        for r, c in nz:
            chars[r][c] = chr(0x2800 + int(masks[r, c]))
        return
    if color_mode == "256":
        x_idx = _XTERM256_LUT[avg_rgb[:, :, 0] >> 3, avg_rgb[:, :, 1] >> 3, avg_rgb[:, :, 2] >> 3]
        seqs = [f"\x1b[38;5;{i}m" for i in range(256)]
        for r, c in nz:
            chars[r][c] = chr(0x2800 + int(masks[r, c]))
            col_grid[r][c] = seqs[int(x_idx[r, c])]
        return
    for r, c in nz:
        chars[r][c] = chr(0x2800 + int(masks[r, c]))
        col_grid[r][c] = ansi_fg_from_rgb(avg_rgb[r, c], color_mode)


def grid_to_lines(chars, colors):
    lines = []
    for row_chars, row_cols in zip(chars, colors):
        out, cur = [], ""
        for ch, col in zip(row_chars, row_cols):
            if ch == " ":
                if cur:
                    out.append("\x1b[0m")
                    cur = ""
                out.append(" ")
            else:
                if col != cur:
                    out.append(col or "\x1b[0m")
                    cur = col
                out.append(ch)
        if cur:
            out.append("\x1b[0m")
        lines.append("".join(out))
    return lines


def paint_bar(chars, colors, height: int, x: int, width: int, val: float, peak: float, palette, peak_col: str, show_peaks: bool, mirror: bool = False):
    n_pal, n_rows, n_cols = len(palette), len(chars), len(chars[0])
    if mirror:
        if height < 2:
            return
        half = height // 2
        c_up, c_dn = half - 1, half
        total_sub = val * half
        full_rows, frac = int(total_sub), int((total_sub - int(total_sub)) * 8.0)
        for off in range(half):
            if off < full_rows:
                cu, cd = "█", "█"
            elif off == full_rows and frac > 0:
                cu, cd = BLOCKS_UP[frac], ("▀" if frac >= 4 else "─")
            else:
                continue
            col = palette[min(n_pal - 1, int((off / max(half - 1, 1)) * (n_pal - 1)))]
            for dx in range(width):
                cx = x + dx
                if cx < n_cols:
                    chars[c_up - off][cx], colors[c_up - off][cx] = cu, col
                    chars[c_dn + off][cx], colors[c_dn + off][cx] = cd, col
        if show_peaks and peak > 0.015:
            p_off = min(half - 1, int(peak * (half - 1)))
            if p_off >= full_rows:
                for dx in range(width):
                    cx = x + dx
                    if cx < n_cols:
                        chars[c_up - p_off][cx], colors[c_up - p_off][cx] = "▔", peak_col
                        chars[c_dn + p_off][cx], colors[c_dn + p_off][cx] = "▁", peak_col
        return

    total_sub = val * height
    full_rows, frac = int(total_sub), int((total_sub - int(total_sub)) * 8.0)
    for off in range(height):
        r = height - 1 - off
        if not (0 <= r < n_rows):
            continue
        if off < full_rows:
            ch = "█"
        elif off == full_rows and frac > 0:
            ch = BLOCKS_UP[frac]
        else:
            continue
        col = palette[min(n_pal - 1, int((off / max(height - 1, 1)) * (n_pal - 1)))]
        for dx in range(width):
            if x + dx < n_cols:
                chars[r][x + dx], colors[r][x + dx] = ch, col
    if show_peaks and peak > 0.015:
        p_off = min(height - 1, int(peak * (height - 1)))
        pr = height - 1 - p_off
        if 0 <= pr < n_rows and p_off >= full_rows:
            for dx in range(width):
                if x + dx < n_cols:
                    chars[pr][x + dx], colors[pr][x + dx] = "▔", peak_col


def paint_grid_lines(chars, colors, height: int, cols: int, color_mode: str, theme: str):
    if height < 8:
        return
    dim_col = ansi_fg_from_rgb(get_theme_chrome(theme)["grid_rgb"], color_mode)
    for frac in (0.25, 0.5, 0.75):
        r = int((1.0 - frac) * (height - 1))
        for x in range(0, cols, 2):
            if chars[r][x] == " ":
                chars[r][x], colors[r][x] = "·", dim_col


def format_freq_axis_line(cols: int, start_x: int, step: int, plan, color_mode: str, theme: str, stereo_cx: Optional[int] = None) -> str:
    """Build a single ANSI-formatted frequency or stereo L/R axis line (shared across all renderers)."""
    axis_col = ansi_fg_from_rgb(get_theme_chrome(theme)["axis_rgb"], color_mode)
    row_c, row_col = [" "] * cols, [""] * cols
    if stereo_cx is not None:
        for dx, lbl in ((-2, "L"), (0, "│"), (2, "R")):
            if 0 <= stereo_cx + dx < cols:
                row_c[stereo_cx + dx], row_col[stereo_cx + dx] = lbl, axis_col
    elif plan:
        last_end = -2
        for hz in (50, 100, 200, 500, 1000, 2000, 4000, 8000, 14000):
            best_i = min(range(len(plan)), key=lambda i: abs(plan[i][3] - hz))
            label = f"{hz // 1000}k" if hz >= 1000 else f"{hz}"
            x = start_x + best_i * step
            if x > last_end + 1 and x + len(label) < cols:
                for j, ch in enumerate(label):
                    row_c[x + j], row_col[x + j] = ch, axis_col
                last_end = x + len(label)
    return grid_to_lines([row_c], [row_col])[0]


# ---------------------------------------------------------------------------
# Physics Simulations (Cymatics with Interpolated Bessel, Starfield, Sparks)
# ---------------------------------------------------------------------------

class ChladniSim:
    """Aspect-aware particle simulator for Polar Bessel, Faraday Water, and Spiral Vortex cymatics."""

    _TABLES = {"polar": CHLADNI_MODES, "faraday": FARADAY_MODES, "vortex": VORTEX_MODES}

    def __init__(self):
        self.rng = np.random.default_rng()
        self.n_particles = 0
        self.x = self.y = self.vx = self.vy = self.mass = self.grain_bias = np.empty(0, dtype=np.float32)
        self.x_max, self.y_max = 1.8, 1.0
        self.cur_idx = self.next_idx = 2
        self.morph, self.hold_timer, self.last_beat_t, self.spin_phase = 1.0, 0.0, 0.0, 0.0

    def ensure_size(self, pix_w: int, pix_h: int, y_scale: float = 1.0, max_particles: int = 45000, density: float = 1.4):
        eff_h = pix_h * y_scale
        min_dim = max(1.0, min(float(pix_w), eff_h))
        nx, ny = pix_w / min_dim, eff_h / min_dim
        target = min(max_particles, max(12000, int(pix_w * pix_h * density)))
        changed = abs(target - self.n_particles) > 1200 or self.n_particles == 0 or abs(nx - self.x_max) > 0.12 or abs(ny - self.y_max) > 0.12
        self.x_max, self.y_max = nx, ny
        if changed:
            self.n_particles = target
            self.scatter()

    def scatter(self):
        if self.n_particles <= 0:
            return
        n = self.n_particles
        self.x = self.rng.uniform(-self.x_max, self.x_max, n).astype(np.float32)
        self.y = self.rng.uniform(-self.y_max, self.y_max, n).astype(np.float32)
        self.vx = np.zeros(n, dtype=np.float32)
        self.vy = np.zeros(n, dtype=np.float32)
        self.mass = self.rng.uniform(0.70, 1.40, n).astype(np.float32)
        self.grain_bias = self.rng.normal(0.0, 0.018, n).astype(np.float32)

    @staticmethod
    def _polar_term(r, r_safe, cos_t, sin_t, theta, m: int, k: float, phi: float, twist: float = 0.0):
        pos = np.clip((k * _BESSEL_INV_DZ) * r, 0.0, float(_BESSEL_N - 1))
        lo = np.minimum(_BESSEL_N - 2, pos.astype(np.int32))
        frac = (pos - lo).astype(np.float32)
        jm_t, djm_t = _BESSEL_J[m], _BESSEL_DJ[m]
        jm = jm_t[lo] * (1.0 - frac) + jm_t[lo + 1] * frac
        djm = djm_t[lo] * (1.0 - frac) + djm_t[lo + 1] * frac
        env = np.sqrt(1.0 + 0.55 * r)
        denv = 0.275 / env
        if m == 0 and twist == 0.0:
            w, dw_dr, dw_dt_r = jm * env, k * djm * env + jm * denv, np.zeros_like(r)
        else:
            ang = m * theta - twist * r + phi
            ca, sa = np.cos(ang), np.sin(ang)
            w = jm * ca * env
            dw_dr = (k * djm * env + jm * denv) * ca + jm * env * twist * sa
            dw_dt_r = -(m * jm * env / r_safe) * sa
        return w, dw_dr * cos_t - dw_dt_r * sin_t, dw_dr * sin_t + dw_dt_r * cos_t

    def _eval_field(self, x: np.ndarray, y: np.ndarray, kind: str, mode_idx: int):
        if kind == "faraday":
            n_waves, k, spd, sym = FARADAY_MODES[mode_idx % len(FARADAY_MODES)]
            w, gx, gy = np.zeros_like(x), np.zeros_like(x), np.zeros_like(x)
            norm, rot = 1.0 / math.sqrt(n_waves), self.spin_phase * spd * 0.35
            for j in range(n_waves):
                ang = (2.0 * math.pi * j) / n_waves + rot
                ca, sa = math.cos(ang), math.sin(ang)
                arg = k * (x * ca + y * sa) + (self.spin_phase * spd if j % 2 == 0 else -self.spin_phase * spd + sym)
                w += np.cos(arg)
                s_arg = np.sin(arg)
                gx -= k * ca * s_arg
                gy -= k * sa * s_arg
            return w * norm, gx * norm, gy * norm

        r = np.sqrt(x * x + y * y)
        r_safe = np.maximum(r, 1e-3)
        cos_t, sin_t, theta = x / r_safe, y / r_safe, np.arctan2(y, x)
        if kind == "vortex":
            m, k, twist, spd = VORTEX_MODES[mode_idx % len(VORTEX_MODES)]
            return self._polar_term(r, r_safe, cos_t, sin_t, theta, m, k, self.spin_phase * spd, twist=twist)
        m1, k1, spin1, m2, k2, alpha2 = CHLADNI_MODES[mode_idx % len(CHLADNI_MODES)]
        w1, gx1, gy1 = self._polar_term(r, r_safe, cos_t, sin_t, theta, m1, k1, self.spin_phase * spin1)
        w2, gx2, gy2 = self._polar_term(r, r_safe, cos_t, sin_t, theta, m2, k2, -self.spin_phase * 0.5)
        return w1 + alpha2 * w2, gx1 + alpha2 * gx2, gy1 + alpha2 * gy2

    def _eval_blended(self, x: np.ndarray, y: np.ndarray, kind: str):
        w1, gx1, gy1 = self._eval_field(x, y, kind, self.cur_idx)
        if self.morph < 0.999 and self.cur_idx != self.next_idx:
            w2, gx2, gy2 = self._eval_field(x, y, kind, self.next_idx)
            t = self.morph
            return (1.0 - t) * w1 + t * w2, (1.0 - t) * gx1 + t * gx2, (1.0 - t) * gy1 + t * gy2
        return w1, gx1, gy1

    def step(self, dt: float, energy: float, centroid: float, beat_flash: float, now: float, silent: bool, kind: str = "polar", mc_method: str = "deterministic"):
        if self.n_particles == 0:
            return np.empty(0, dtype=np.float32)
        self.hold_timer += dt
        self.morph = min(1.0, self.morph + dt * 0.75)
        self.spin_phase += dt * (0.45 + 0.65 * min(1.0, energy))

        n_modes = len(self._TABLES[kind])
        target_idx = min(n_modes - 1, max(0, int(centroid * n_modes)))
        beat_trigger = beat_flash > 0.78 and (now - self.last_beat_t) > 1.3
        if self.morph >= 0.99 and target_idx != (self.next_idx % n_modes) and (self.hold_timer >= 1.8 or beat_trigger):
            self.cur_idx, self.next_idx, self.morph, self.hold_timer = self.next_idx % n_modes, target_idx, 0.0, 0.0
            if beat_trigger:
                self.last_beat_t = now

        w, gx, gy = self._eval_blended(self.x, self.y, kind)
        abs_w, n = np.abs(w), self.n_particles

        if silent:
            self.vx *= 0.80
            self.vy *= 0.80
        elif mc_method == "metropolis":
            sig = 0.025 + 0.045 * min(1.5, energy) + 0.05 * beat_flash
            xp = self.x + (self.rng.random(n, dtype=np.float32) - 0.5) * (2.0 * sig)
            yp = self.y + (self.rng.random(n, dtype=np.float32) - 0.5) * (2.0 * sig)
            wp, _, _ = self._eval_blended(xp, yp, kind)
            beta = 14.0 / (0.28 + 0.55 * min(1.4, energy) + 0.65 * beat_flash)
            acc = ((wp * wp) <= (w * w)) | (self.rng.random(n, dtype=np.float32) < np.exp(-np.clip(beta * ((wp * wp) - (w * w)), 0.0, 20.0)))
            self.vx = np.where(acc, (xp - self.x) * 0.5, self.vx * 0.6)
            self.vy = np.where(acc, (yp - self.y) * 0.5, self.vy * 0.6)
            self.x, self.y = np.where(acc, xp, self.x), np.where(acc, yp, self.y)
        elif mc_method == "importance":
            weights = np.exp(-np.clip((w * w) / (0.045 + 0.08 * min(1.4, energy) + 0.12 * beat_flash), 0.0, 20.0))
            w_sum = float(np.sum(weights))
            if w_sum > 1e-8:
                n_res = max(1, int(n * min(0.28, 0.08 + 0.12 * min(1.4, energy))))
                bad = np.argpartition(weights, n_res)[:n_res]
                src = self.rng.choice(n, size=n_res, replace=True, p=weights / w_sum)
                jitter = 0.022 + 0.025 * beat_flash
                self.x[bad] = self.x[src] + (self.rng.random(n_res, dtype=np.float32) - 0.5) * jitter
                self.y[bad] = self.y[src] + (self.rng.random(n_res, dtype=np.float32) - 0.5) * jitter
            jit = (0.008 * min(1.4, energy) * abs_w + 0.020 * beat_flash) / self.mass
            self.vx = (self.rng.random(n, dtype=np.float32) - 0.5) * jit
            self.vy = (self.rng.random(n, dtype=np.float32) - 0.5) * jit
            self.x += self.vx
            self.y += self.vy
        elif mc_method == "langevin":
            drift = -0.020 * (0.55 + energy) * ((w - self.grain_bias) / (np.sqrt(gx * gx + gy * gy) + 0.55))
            diff = np.sqrt(np.maximum(1e-5, (0.00025 + 0.0009 * energy * abs_w + 0.0018 * beat_flash) * dt)) / self.mass
            self.vx = drift * gx * (dt * 60.0) + (self.rng.random(n, dtype=np.float32) - 0.5) * (3.464 * diff)
            self.vy = drift * gy * (dt * 60.0) + (self.rng.random(n, dtype=np.float32) - 0.5) * (3.464 * diff)
            self.x += self.vx * 0.45
            self.y += self.vy * 0.45
        else:
            w_eff = w - self.grain_bias
            drift_k = 0.022 * (0.48 + 1.05 * min(1.4, energy))
            denom = (np.sqrt(gx * gx + gy * gy) + 0.55) * self.mass
            fx, fy = -drift_k * (w_eff * gx) / denom, -drift_k * (w_eff * gy) / denom
            if kind == "vortex":
                swirl = 0.006 * (0.5 + energy) / np.maximum(0.08, np.sqrt(self.x * self.x + self.y * self.y))
                fx, fy = fx - self.y * swirl, fy + self.x * swirl
            vib = ((0.015 * min(1.5, energy) * abs_w + 0.042 * beat_flash * (0.18 + abs_w)) / self.mass).astype(np.float32)
            damp = math.exp(-dt * 14.0)
            self.vx = np.clip(self.vx * damp + fx * (dt * 60.0) + (self.rng.random(n, dtype=np.float32) - 0.5) * (2.0 * vib), -0.10, 0.10)
            self.vy = np.clip(self.vy * damp + fy * (dt * 60.0) + (self.rng.random(n, dtype=np.float32) - 0.5) * (2.0 * vib), -0.10, 0.10)
            self.x += self.vx * (dt * 27.0)
            self.y += self.vy * (dt * 27.0)

        oob = (np.abs(self.x) > self.x_max * 1.02) | (np.abs(self.y) > self.y_max * 1.02)
        n_oob = int(np.sum(oob))
        if n_oob > 0:
            self.x[oob] = self.rng.uniform(-self.x_max, self.x_max, n_oob).astype(np.float32)
            self.y[oob] = self.rng.uniform(-self.y_max, self.y_max, n_oob).astype(np.float32)
            self.vx[oob] = self.vy[oob] = 0.0
        return np.clip(np.sqrt(self.vx * self.vx + self.vy * self.vy) * 18.0 + abs_w * 0.35, 0.0, 1.0)


class StarfieldSim:
    def __init__(self, count: int = 900):
        self.rng = np.random.default_rng()
        self.x = self.rng.uniform(-1.6, 1.6, count).astype(np.float32)
        self.y = self.rng.uniform(-1.1, 1.1, count).astype(np.float32)
        self.z = self.rng.uniform(0.12, 2.5, count).astype(np.float32)
        self.pz = self.z.copy()

    def step(self, dt: float, bass: float, beat_flash: float, silent: bool):
        self.pz[:] = self.z
        self.z -= (0.25 if silent else (0.65 + 2.4 * min(1.5, bass) + 2.2 * beat_flash)) * dt
        dead = self.z <= 0.08
        n_dead = int(np.sum(dead))
        if n_dead > 0:
            self.x[dead] = self.rng.uniform(-1.6, 1.6, n_dead).astype(np.float32)
            self.y[dead] = self.rng.uniform(-1.1, 1.1, n_dead).astype(np.float32)
            self.z[dead] = self.rng.uniform(1.8, 2.6, n_dead).astype(np.float32)
            self.pz[dead] = self.z[dead]


class SparkBurst:
    def __init__(self, max_sparks: int = 360):
        self.rng, self.max_sparks = np.random.default_rng(), max_sparks
        self.x = self.y = self.vx = self.vy = self.life = np.zeros(0, dtype=np.float32)

    def spawn(self, count: int, base_r: float, speed_scale: float):
        angs = self.rng.uniform(0.0, 2.0 * math.pi, count).astype(np.float32)
        spd = self.rng.uniform(0.45, 1.15, count).astype(np.float32) * speed_scale
        self.x = np.concatenate((self.x, np.cos(angs) * base_r))[-self.max_sparks :]
        self.y = np.concatenate((self.y, np.sin(angs) * base_r))[-self.max_sparks :]
        self.vx = np.concatenate((self.vx, np.cos(angs) * spd))[-self.max_sparks :]
        self.vy = np.concatenate((self.vy, np.sin(angs) * spd))[-self.max_sparks :]
        self.life = np.concatenate((self.life, np.ones(count, dtype=np.float32)))[-self.max_sparks :]

    def step(self, dt: float):
        if len(self.life) == 0:
            return
        self.x += self.vx * dt
        self.y += self.vy * dt
        damp = math.exp(-dt * 2.2)
        self.vx *= damp
        self.vy *= damp
        self.life -= dt * 1.35
        alive = self.life > 0.02
        self.x, self.y, self.vx, self.vy, self.life = self.x[alive], self.y[alive], self.vx[alive], self.vy[alive], self.life[alive]


# ---------------------------------------------------------------------------
# Aspect-Corrected Unified RGBA Framebuffer
# ---------------------------------------------------------------------------

class PixelFramebuffer:
    """High-DPI RGBA pixel renderer shared across Kitty, Quadrant, and Braille backends."""

    def __init__(self, width: int, height: int):
        self.y_scale = 1.0
        self._alloc(width, height)

    def _alloc(self, width: int, height: int):
        self.w, self.h = width, height
        self.rgba = np.zeros((height, width, 4), dtype=np.uint8)
        self.spec_buf = np.zeros((height, width, 4), dtype=np.uint8)
        self.d_glow = np.zeros((height, width), dtype=np.float32)
        self.e_glow = np.zeros((height, width), dtype=np.float32)

    def resize(self, width: int, height: int, y_scale: float = 1.0):
        self.y_scale = y_scale
        if width != self.w or height != self.h:
            self._alloc(width, height)

    def clear(self):
        self.rgba.fill(0)

    def draw_grid(self, grid_rgb: Optional[np.ndarray] = None):
        col = grid_rgb if grid_rgb is not None else np.array([72, 78, 92], dtype=np.uint8)
        for frac in (0.25, 0.5, 0.75):
            y = int((1.0 - frac) * (self.h - 1))
            self.rgba[y, ::4, :3] = col
            self.rgba[y, ::4, 3] = 75

    def _clip_segment(self, x0: float, y0: float, x1: float, y1: float):
        """Liang-Barsky viewport clip so long off-screen streaks never waste steps."""
        dx, dy = x1 - x0, y1 - y0
        t0, t1 = 0.0, 1.0
        w_m, h_m = self.w - 1.0, self.h - 1.0
        for p, q in ((-dx, x0), (dx, w_m - x0), (-dy, y0), (dy, h_m - y0)):
            if p == 0.0:
                if q < 0.0:
                    return None
            else:
                r = q / p
                if p < 0.0:
                    if r > t1:
                        return None
                    if r > t0:
                        t0 = r
                else:
                    if r < t0:
                        return None
                    if r < t1:
                        t1 = r
        return x0 + t0 * dx, y0 + t0 * dy, x0 + t1 * dx, y0 + t1 * dy

    def draw_segments(self, x0: np.ndarray, y0: np.ndarray, x1: np.ndarray, y1: np.ndarray, rgb_colors: np.ndarray, thickness: int = 1, alpha: int = 245, additive: bool = True):
        """Clipped, bucketed per-segment rasterizer with optional max-glow blending."""
        if len(x0) == 0:
            return
        w_m, h_m = self.w - 1.0, self.h - 1.0
        inside = (np.maximum(x0, x1) >= 0) & (np.minimum(x0, x1) <= w_m) & (np.maximum(y0, y1) >= 0) & (np.minimum(y0, y1) <= h_m)
        if not np.any(inside):
            return
        x0, y0, x1, y1, rgb_colors = x0[inside], y0[inside], x1[inside], y1[inside], rgb_colors[inside]

        # Clip only segments that extend outside the viewport
        oob = (x0 < 0) | (x0 > w_m) | (x1 < 0) | (x1 > w_m) | (y0 < 0) | (y0 > h_m) | (y1 < 0) | (y1 > h_m)
        if np.any(oob):
            keep = np.ones(len(x0), dtype=bool)
            for idx in np.flatnonzero(oob):
                clipped = self._clip_segment(float(x0[idx]), float(y0[idx]), float(x1[idx]), float(y1[idx]))
                if clipped is None:
                    keep[idx] = False
                else:
                    x0[idx], y0[idx], x1[idx], y1[idx] = clipped
            if not np.any(keep):
                return
            x0, y0, x1, y1, rgb_colors = x0[keep], y0[keep], x1[keep], y1[keep], rgb_colors[keep]

        lens = np.abs(x1 - x0) + np.abs(y1 - y0)
        r0 = (-thickness // 2 + 1) if thickness > 1 else 0
        offsets = [(dx, dy) for dy in range(r0, thickness // 2 + 1) for dx in range(r0, thickness // 2 + 1)]

        # Bucket segments by power-of-two length so short segments aren't padded to max_len
        for lo_l, hi_l, steps in ((0.0, 4.0, 5), (4.0, 24.0, 26), (24.0, 96.0, 98), (96.0, 1e9, int(min(512, np.max(lens) + 2)))):
            mask = (lens >= lo_l) & (lens < hi_l)
            if not np.any(mask):
                continue
            bx0, by0, bx1, by1, bcol = x0[mask], y0[mask], x1[mask], y1[mask], rgb_colors[mask]
            t = np.linspace(0.0, 1.0, steps, dtype=np.float32)[None, :]
            xs_f = np.round(bx0[:, None] + (bx1 - bx0)[:, None] * t).astype(np.int32).ravel()
            ys_f = np.round(by0[:, None] + (by1 - by0)[:, None] * t).astype(np.int32).ravel()
            cols_f = np.repeat(bcol[:, None, :], steps, axis=1).reshape(-1, 3)
            for dx, dy in offsets:
                px, py = xs_f + dx, ys_f + dy
                valid = (px >= 0) & (px < self.w) & (py >= 0) & (py < self.h)
                if not np.any(valid):
                    continue
                vx, vy, vc = px[valid], py[valid], cols_f[valid]
                if additive:
                    np.maximum(self.rgba[vy, vx, :3], vc, out=self.rgba[vy, vx, :3])
                    np.maximum(self.rgba[vy, vx, 3], alpha, out=self.rgba[vy, vx, 3])
                else:
                    self.rgba[vy, vx, :3] = vc
                    self.rgba[vy, vx, 3] = alpha

    def _draw_vbar_up(self, x0: int, x1: int, val: float, peak: float, base_idx: np.ndarray, rgb_lut: np.ndarray, shift: int, peak_col: np.ndarray, show_peaks: bool):
        n_lut = len(rgb_lut)
        bh = int(float(val) * (self.h - 2))
        if bh > 0:
            yt = self.h - bh
            self.rgba[yt : self.h, x0:x1, :3] = rgb_lut[np.clip(base_idx[yt : self.h] + shift, 0, n_lut - 1)][:, None, :]
            self.rgba[yt : self.h, x0:x1, 3] = 245
        if show_peaks and peak > 0.015:
            py = max(0, self.h - 1 - int(float(peak) * (self.h - 2)))
            if py < self.h - bh:
                self.rgba[max(0, py - 1) : py + 1, x0:x1, :3] = peak_col
                self.rgba[max(0, py - 1) : py + 1, x0:x1, 3] = 255

    def render_cymatics(self, sim: ChladniSim, particle_energy: np.ndarray, rgb_lut: np.ndarray, chrome: Optional[dict] = None):
        self.clear()
        if sim.n_particles == 0:
            return
        px = np.clip(((sim.x / sim.x_max + 1.0) * 0.5) * self.w, 0, self.w - 1).astype(np.int32)
        py = np.clip(((sim.y / sim.y_max + 1.0) * 0.5) * self.h, 0, self.h - 1).astype(np.int32)
        idx = py * self.w + px
        n_pix = self.w * self.h
        density = np.bincount(idx, minlength=n_pix).astype(np.float32)
        energy_mean = np.bincount(idx, weights=particle_energy, minlength=n_pix).astype(np.float32) / np.maximum(1.0, density)

        d2, e2 = density.reshape(self.h, self.w), energy_mean.reshape(self.h, self.w)
        dg, eg = self.d_glow, self.e_glow
        dg[:] = d2 * 0.52
        dg[1:, :] += d2[:-1, :] * 0.12
        dg[:-1, :] += d2[1:, :] * 0.12
        dg[:, 1:] += d2[:, :-1] * 0.12
        dg[:, :-1] += d2[:, 1:] * 0.12
        eg[:] = e2
        np.maximum(eg[1:, :], e2[:-1, :] * 0.72, out=eg[1:, :])
        np.maximum(eg[:-1, :], e2[1:, :] * 0.72, out=eg[:-1, :])
        np.maximum(eg[:, 1:], e2[:, :-1] * 0.72, out=eg[:, 1:])
        np.maximum(eg[:, :-1], e2[:, 1:] * 0.72, out=eg[:, :-1])

        nz = np.flatnonzero(dg > 0.01)
        if len(nz) == 0:
            return
        dv, ev = dg.ravel()[nz], eg.ravel()[nz]
        bright = np.clip(1.0 - np.exp(-dv * 1.15), 0.0, 1.0)
        n_lut = len(rgb_lut)
        color_t = np.clip(0.18 + ev * 0.58 + np.minimum(0.30, dv * 0.10), 0.0, 1.0)
        base_rgb = rgb_lut[np.clip((color_t * (n_lut - 1)).astype(np.int32), 0, n_lut - 1)].astype(np.float32)
        if chrome is not None:
            crest = np.clip((ev - 0.45) * 1.6, 0.0, 0.55)[:, None]
            base_rgb = base_rgb * (1.0 - crest) + chrome["accent_rgb"].astype(np.float32) * crest
        shade = np.clip(0.34 + bright * 0.72, 0.0, 1.05)[:, None]
        flat = self.rgba.reshape(-1, 4)
        flat[nz, :3] = np.clip(base_rgb * shade, 0, 255).astype(np.uint8)
        flat[nz, 3] = (bright * 255.0).astype(np.uint8)

    def render_bars(self, values: np.ndarray, peaks: np.ndarray, rgb_lut: np.ndarray, mirror: bool = False, show_peaks: bool = True, show_grid: bool = False, use_gap: bool = True, chrome: Optional[dict] = None):
        self.clear()
        peak_col = chrome["accent_rgb"] if chrome else rgb_lut[-1]
        if show_grid and not mirror:
            self.draw_grid(chrome["grid_rgb"] if chrome else None)
        n = len(values)
        if n == 0:
            return
        n_lut, y_rows = len(rgb_lut), np.arange(self.h, dtype=np.float32)
        shift_span = max(1, int(n_lut * 0.14))
        slot_w = self.w / float(n)
        gap = max(1, int(slot_w * 0.18)) if (use_gap and slot_w >= 4.0) else 0

        if mirror:
            half = self.h // 2
            base_idx = np.clip((y_rows[:half] / max(half - 1, 1)) * (n_lut - 1), 0, n_lut - 1).astype(np.int32)
            for i in range(n):
                x0, x1 = int(i * slot_w), max(int(i * slot_w) + 1, int((i + 1) * slot_w) - gap)
                bh = int(float(values[i]) * (half - 2))
                if bh > 0:
                    shift = int(((i / max(n - 1, 1)) - 0.35) * shift_span)
                    bar_rgb = rgb_lut[np.clip(base_idx[:bh] + shift, 0, n_lut - 1)]
                    self.rgba[half - bh : half, x0:x1, :3] = bar_rgb[::-1, None, :]
                    self.rgba[half - bh : half, x0:x1, 3] = 245
                    self.rgba[half : half + bh, x0:x1, :3] = bar_rgb[:, None, :]
                    self.rgba[half : half + bh, x0:x1, 3] = 245
                if show_peaks and peaks[i] > 0.015:
                    ph = int(float(peaks[i]) * (half - 2))
                    if ph >= bh:
                        self.rgba[max(0, half - ph - 2) : max(1, half - ph), x0:x1, :3] = peak_col
                        self.rgba[max(0, half - ph - 2) : max(1, half - ph), x0:x1, 3] = 255
                        self.rgba[min(self.h - 2, half + ph) : min(self.h, half + ph + 2), x0:x1, :3] = peak_col
                        self.rgba[min(self.h - 2, half + ph) : min(self.h, half + ph + 2), x0:x1, 3] = 255
            return

        base_idx = np.clip(((self.h - 1 - y_rows) / max(self.h - 1, 1)) * (n_lut - 1), 0, n_lut - 1).astype(np.int32)
        for i in range(n):
            x0, x1 = int(i * slot_w), max(int(i * slot_w) + 1, int((i + 1) * slot_w) - gap)
            shift = int(((i / max(n - 1, 1)) - 0.35) * shift_span)
            self._draw_vbar_up(x0, x1, values[i], peaks[i], base_idx, rgb_lut, shift, peak_col, show_peaks)

    def render_stereo_bars(self, vals_l: np.ndarray, peaks_l: np.ndarray, vals_r: np.ndarray, peaks_r: np.ndarray, rgb_lut: np.ndarray, show_peaks: bool, show_grid: bool, use_gap: bool, chrome: Optional[dict] = None):
        self.clear()
        if show_grid:
            self.draw_grid(chrome["grid_rgb"] if chrome else None)
        cx = self.w // 2
        self.rgba[:, cx : cx + 2, :3] = chrome["axis_rgb"] if chrome else np.array([130, 130, 130], dtype=np.uint8)
        self.rgba[:, cx : cx + 2, 3] = 120
        n = len(vals_l)
        if n == 0:
            return
        n_lut = len(rgb_lut)
        base_idx = np.clip(((self.h - 1 - np.arange(self.h, dtype=np.float32)) / max(self.h - 1, 1)) * (n_lut - 1), 0, n_lut - 1).astype(np.int32)
        peak_col = chrome["accent_rgb"] if chrome else rgb_lut[-1]
        shift_span = max(1, int(n_lut * 0.14))
        slot_w = max(4, cx - 4) / float(n)
        gap = max(1, int(slot_w * 0.18)) if (use_gap and slot_w >= 4.0) else 0
        for i in range(n):
            lx1, lx0 = cx - 3 - int(i * slot_w), max(0, cx - 3 - int((i + 1) * slot_w) + gap)
            rx0, rx1 = cx + 4 + int(i * slot_w), min(self.w, cx + 4 + int((i + 1) * slot_w) - gap)
            shift = int(((i / max(n - 1, 1)) - 0.35) * shift_span)
            if lx1 > lx0:
                self._draw_vbar_up(lx0, lx1, vals_l[i], peaks_l[i], base_idx, rgb_lut, shift, peak_col, show_peaks)
            if rx1 > rx0:
                self._draw_vbar_up(rx0, rx1, vals_r[i], peaks_r[i], base_idx, rgb_lut, shift, peak_col, show_peaks)

    def render_curve(self, values: np.ndarray, rgb_lut: np.ndarray, chrome: Optional[dict] = None):
        self.clear()
        if len(values) < 4:
            return
        up = cubic_upsample(values, self.w, periodic=False)
        ys = np.clip((1.0 - up) * (self.h - 2), 0, self.h - 1).astype(np.int32)
        y_grid = np.arange(self.h, dtype=np.int32)[:, None]
        fill_mask = y_grid >= ys[None, :]
        h_frac = (self.h - 1 - y_grid[:, 0]) / max(self.h - 1, 1)
        row_rgb = rgb_lut[np.clip(h_frac * (len(rgb_lut) - 1), 0, len(rgb_lut) - 1).astype(np.int32)][:, None, :]
        self.rgba[:, :, :3] = np.where(fill_mask[:, :, None], row_rgb, 0)
        self.rgba[:, :, 3] = np.where(fill_mask, (96.0 + 138.0 * h_frac)[:, None], 0).astype(np.uint8)
        xs = np.arange(self.w - 1, dtype=np.float32)
        self.draw_segments(xs, ys[:-1].astype(np.float32), xs + 1, ys[1:].astype(np.float32), np.tile(chrome["accent_rgb"] if chrome else rgb_lut[-1], (self.w - 1, 1)), thickness=2, alpha=255, additive=False)

    def render_wave(self, stereo_frames: np.ndarray, gain: float, rgb_lut: np.ndarray, show_grid: bool, chrome: Optional[dict] = None):
        self.clear()
        if show_grid:
            self.draw_grid(chrome["grid_rgb"] if chrome else None)
        mono = 0.5 * (stereo_frames[:, 0] + stereo_frames[:, 1])
        trig_buf = np.convolve(mono, np.ones(11, dtype=np.float32) / 11.0, mode="same")
        search_end = max(2, min(len(trig_buf) - self.w - 2, 1600))
        seg = trig_buf[:search_end]
        arm_thresh = -max(0.005, float(np.max(np.abs(seg))) * 0.06)
        armed_pts = np.flatnonzero(seg <= arm_thresh)
        trig_f = 0.0
        if len(armed_pts) > 0:
            s0 = int(armed_pts[0]) + 1
            if s0 < search_end:
                cross = np.flatnonzero((seg[s0 - 1 : -1] < 0.0) & (seg[s0:] >= 0.0))
                if len(cross) > 0:
                    idx = s0 + int(cross[0])
                    denom = float(seg[idx] - seg[idx - 1])
                    trig_f = (idx - 1) + ((-float(seg[idx - 1]) / denom) if abs(denom) > 1e-7 else 0.0)

        span = min(len(stereo_frames) - int(trig_f) - 2, max(self.w, 1024))
        if span < 8:
            return
        s_idx, b_idx = np.linspace(trig_f, trig_f + span - 1, self.w), np.arange(len(stereo_frames), dtype=np.float64)
        xs, n_lut = np.arange(self.w - 1, dtype=np.float32), len(rgb_lut)
        for ch, cy, c_frac in ((0, self.h * 0.27, 0.27), (1, self.h * 0.73, 0.73)):
            sig = np.clip(np.interp(s_idx, b_idx, stereo_frames[:, ch]) * gain * 1.5, -1.0, 1.0)
            ys = np.clip(cy - sig * (self.h * 0.21), 0, self.h - 1).astype(np.float32)
            dist = np.abs((ys[:-1] / max(self.h - 1, 1)) - c_frac)
            self.draw_segments(xs, ys[:-1], xs + 1, ys[1:], rgb_lut[np.clip(((1.0 - np.minimum(1.0, dist * 1.6)) * (n_lut - 1)).astype(np.int32), 0, n_lut - 1)], thickness=2, alpha=255)

    def render_radial(self, values: np.ndarray, bass_level: float, angle_offset: float, rgb_lut: np.ndarray, chrome: Optional[dict] = None):
        self.clear()
        if len(values) < 4:
            return
        cx, cy = self.w * 0.5, self.h * 0.5
        rx_max = min(cx, cy * self.y_scale) * 0.90
        ry_max = rx_max / self.y_scale
        base_frac = 0.26 + 0.12 * min(1.0, bass_level)
        ring_vals = cubic_upsample(np.concatenate((values, values[::-1])), 280, periodic=True)
        angs = np.linspace(0.0, 2.0 * math.pi, len(ring_vals), endpoint=False, dtype=np.float32) + angle_offset - math.pi * 0.5
        ca, sa = np.cos(angs), np.sin(angs)
        r_frac = base_frac + ring_vals * (1.0 - base_frac)
        x0, y0 = cx + ca * (rx_max * base_frac), cy + sa * (ry_max * base_frac)
        x1, y1 = cx + ca * (rx_max * r_frac), cy + sa * (ry_max * r_frac)
        n_lut = len(rgb_lut)
        c_idx = np.clip((ring_vals * (n_lut - 1)).astype(np.int32), 0, n_lut - 1)
        env_rgb = rgb_lut[np.minimum(n_lut - 1, c_idx + 12)].astype(np.float32)
        if chrome is not None:
            tip = np.clip((ring_vals - 0.55) * 1.4, 0.0, 0.60)[:, None]
            env_rgb = np.clip(env_rgb * (1.0 - tip) + chrome["accent_rgb"].astype(np.float32) * tip, 0, 255)
        self.draw_segments(x0[::2], y0[::2], x1[::2], y1[::2], rgb_lut[c_idx[::2]], thickness=2, alpha=230)
        self.draw_segments(x0, y0, np.roll(x0, -1), np.roll(y0, -1), np.tile(rgb_lut[min(n_lut - 1, 10)], (len(x0), 1)), thickness=2, alpha=240)
        self.draw_segments(x1, y1, np.roll(x1, -1), np.roll(y1, -1), env_rgb.astype(np.uint8), thickness=2, alpha=255)

    def render_lissajous(self, trail_frames, rgb_lut: np.ndarray, show_grid: bool, chrome: Optional[dict] = None):
        self.clear()
        if show_grid:
            self.draw_grid(chrome["grid_rgb"] if chrome else None)
        if not trail_frames:
            return
        cx, cy = self.w * 0.5, self.h * 0.5
        sx = min(cx, cy * self.y_scale) * 0.88
        sy = sx / self.y_scale
        n_lut, n_trails = len(rgb_lut), len(trail_frames)
        for age_idx, arr in enumerate(trail_frames):
            if len(arr) < 2:
                continue
            xs, ys = cx + arr[:, 0] * sx, cy - arr[:, 1] * sy
            frac = (age_idx + 1) / max(n_trails, 1)
            col = rgb_lut[min(n_lut - 1, int(frac * (n_lut - 1)))]
            self.draw_segments(xs[:-1], ys[:-1], xs[1:], ys[1:], np.tile(col, (len(xs) - 1, 1)), thickness=2 if age_idx == n_trails - 1 else 1, alpha=int(80 + 175 * frac))

    def render_lorenz(self, points, yaw: float, pitch: float, zoom: float, rgb_lut: np.ndarray):
        self.clear()
        if len(points) < 2:
            return
        arr = np.asarray(points, dtype=np.float32)
        zc = arr[:, 2] - 25.0
        cy_a, sy_a, cp_a, sp_a = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
        xr = arr[:, 0] * cy_a - zc * sy_a
        yr = arr[:, 1] * cp_a - (arr[:, 0] * sy_a + zc * cy_a) * sp_a
        sx = min(self.w, self.h * self.y_scale) * 0.022 * zoom
        sy = sx / self.y_scale
        xs, ys = self.w * 0.5 + xr * sx, self.h * 0.5 - yr * sy
        c_idx = np.clip((np.linspace(0.0, 1.0, len(xs) - 1) * (len(rgb_lut) - 1)).astype(np.int32), 0, len(rgb_lut) - 1)
        self.draw_segments(xs[:-1], ys[:-1], xs[1:], ys[1:], rgb_lut[c_idx], thickness=2, alpha=245)

    def render_horizon(self, ridge_history, rgb_lut: np.ndarray, chrome: Optional[dict] = None):
        self.clear()
        if not ridge_history:
            return
        n_layers, n_lut = len(ridge_history), len(rgb_lut)
        xs = np.arange(self.w, dtype=np.float32)
        edge = (np.maximum(0.0, np.sin(math.pi * (xs / max(self.w - 1, 1)))) ** 0.45).astype(np.float32)
        horizon_top = np.full(self.w, self.h, dtype=np.int32)
        amp_px, base_top, base_span = self.h * 0.34, self.h * 0.24, self.h * 0.72
        haze = (chrome["grid_rgb"] if chrome else rgb_lut[0]).astype(np.float32)
        for layer_idx, spec in enumerate(reversed(ridge_history)):
            depth_t = layer_idx / max(n_layers - 1, 1)
            up = cubic_upsample(spec, self.w, periodic=False)
            ys = np.clip(np.round(base_top + (1.0 - depth_t) * base_span - up * amp_px * edge), 0, self.h - 1).astype(np.int32)
            base_col = rgb_lut[min(n_lut - 1, int((1.0 - depth_t) * (n_lut - 1)))].astype(np.float32)
            col = np.clip(base_col * (1.0 - depth_t * 0.58) + haze * (depth_t * 0.58), 0, 255).astype(np.uint8)
            vis = ys < horizon_top
            if np.any(vis):
                vx, vy = np.flatnonzero(vis), ys[vis]
                self.rgba[vy, vx, :3], self.rgba[vy, vx, 3] = col, int(250 - depth_t * 115)
                vy2 = np.minimum(self.h - 1, vy + 1)
                self.rgba[vy2, vx, :3], self.rgba[vy2, vx, 3] = col, int(205 - depth_t * 110)
            horizon_top = np.minimum(horizon_top, ys)

    def render_spectrogram_col(self, col_vals: np.ndarray, rgb_lut: np.ndarray):
        self.spec_buf[:, :-1, :] = self.spec_buf[:, 1:, :]
        up = cubic_upsample(col_vals, self.h, periodic=False)[::-1]
        self.spec_buf[:, -1, :3] = rgb_lut[np.clip((up * (len(rgb_lut) - 1)).astype(np.int32), 0, len(rgb_lut) - 1)]
        self.spec_buf[:, -1, 3] = np.where(up > 0.03, np.clip(up * 255.0, 0, 255), 0).astype(np.uint8)
        self.rgba[:] = self.spec_buf

    def render_scroll(self, history, rgb_lut: np.ndarray, show_peaks: bool, show_grid: bool, chrome: Optional[dict] = None):
        self.clear()
        if show_grid:
            self.draw_grid(chrome["grid_rgb"] if chrome else None)
        if not history:
            return
        n_lut = len(rgb_lut)
        row_rgb = rgb_lut[np.clip(((self.h - 1 - np.arange(self.h, dtype=np.float32)) / max(self.h - 1, 1)) * (n_lut - 1), 0, n_lut - 1).astype(np.int32)]
        peak_col = chrome["accent_rgb"] if chrome else rgb_lut[-1]
        hist_list = list(history)[-self.w :]
        offset_x = self.w - len(hist_list)
        for i, (v_rms, v_pk) in enumerate(hist_list):
            x, bh = offset_x + i, int(v_rms * (self.h - 2))
            if bh > 0:
                self.rgba[self.h - bh : self.h, x, :3] = row_rgb[self.h - bh : self.h]
                self.rgba[self.h - bh : self.h, x, 3] = 240
            if show_peaks and v_pk > 0.015:
                py = max(0, self.h - 1 - int(v_pk * (self.h - 2)))
                if py < self.h - bh:
                    self.rgba[py, x, :3], self.rgba[py, x, 3] = peak_col, 255

    def render_milkdrop(self, phase_t: float, bass: float, treble: float, beat_flash: float, rgb_lut: np.ndarray):
        key = (self.h, self.w, self.y_scale)
        if not hasattr(self, "_md_key") or self._md_key != key:
            self._md_key = key
            md = max(1.0, min(float(self.w), self.h * self.y_scale))
            gx, gy = np.meshgrid(
                np.linspace(-self.w / md, self.w / md, self.w, dtype=np.float32),
                np.linspace(-(self.h * self.y_scale) / md, (self.h * self.y_scale) / md, self.h, dtype=np.float32),
            )
            self._md_r, self._md_ang = np.sqrt(gx * gx + gy * gy).astype(np.float32), np.arctan2(gy, gx).astype(np.float32)
        r, ang = self._md_r, self._md_ang
        u = 1.65 / (r + 0.22) + phase_t * 1.4
        v = np.cos((5.0 + 2.0 * math.sin(phase_t * 0.23)) * ang + (1.4 + 1.2 * min(1.5, bass)) * np.sin(u * 0.55 - phase_t))
        field = 0.5 + 0.5 * np.sin(u * 2.2 + phase_t * 1.8 + bass * 2.2) * np.cos(v * 2.4 + treble * 1.8)
        glow = np.clip(field * np.minimum(1.0, 0.35 + r * 0.85) * (0.85 + 0.35 * beat_flash), 0.0, 1.0)
        c_idx = np.clip(((glow * 0.85 + (u * 0.12) % 0.25) * (len(rgb_lut) - 1)).astype(np.int32), 0, len(rgb_lut) - 1)
        self.rgba[:, :, :3] = (rgb_lut[c_idx].astype(np.float32) * (0.25 + 0.85 * glow[:, :, None])).clip(0, 255).astype(np.uint8)
        self.rgba[:, :, 3] = np.clip(glow * 255.0, 0, 255).astype(np.uint8)

    def render_hybrid(self, values: np.ndarray, bass_level: float, angle_offset: float, stereo_frames: np.ndarray, gain: float, sparks: SparkBurst, rgb_lut: np.ndarray, chrome: Optional[dict] = None):
        self.render_radial(values, bass_level, angle_offset, rgb_lut, chrome=chrome)
        cx, cy = self.w * 0.5, self.h * 0.5
        rx_max = min(cx, cy * self.y_scale) * 0.90
        ry_max = rx_max / self.y_scale
        base_f = 0.25 + 0.11 * min(1.0, bass_level)
        seg_l, seg_r = stereo_frames[-180::2, 0] * gain * 1.4, stereo_frames[-180::2, 1] * gain * 1.4
        xs = np.clip((seg_l - seg_r) * 0.72, -1.0, 1.0) * (rx_max * base_f * 0.85) + cx
        ys = cy - np.clip((seg_l + seg_r) * 0.72, -1.0, 1.0) * (ry_max * base_f * 0.85)
        self.draw_segments(xs[:-1], ys[:-1], xs[1:], ys[1:], np.tile(chrome["accent_rgb"] if chrome else rgb_lut[-1], (len(xs) - 1, 1)), thickness=1, alpha=215)
        if len(sparks.life) > 0:
            sx, sy = np.round(cx + sparks.x * rx_max).astype(np.int32), np.round(cy + sparks.y * ry_max).astype(np.int32)
            valid = (sx >= 1) & (sx < self.w - 1) & (sy >= 1) & (sy < self.h - 1)
            if np.any(valid):
                vx, vy, vl = sx[valid], sy[valid], sparks.life[valid]
                spark_rgb = rgb_lut[np.clip((vl * (len(rgb_lut) - 1)).astype(np.int32), 0, len(rgb_lut) - 1)].astype(np.float32)
                if chrome is not None:
                    hot = np.clip((vl - 0.35) * 1.1, 0.0, 0.75)[:, None]
                    spark_rgb = spark_rgb * (1.0 - hot) + chrome["accent_rgb"].astype(np.float32) * hot
                col, al = np.clip(spark_rgb, 0, 255).astype(np.uint8), np.clip(vl * 255.0, 0, 255).astype(np.uint8)
                self.rgba[vy, vx, :3], self.rgba[vy, vx, 3] = col, al
                self.rgba[vy, vx + 1, :3], self.rgba[vy, vx + 1, 3] = col, al // 2

    def render_starfield(self, stars: StarfieldSim, rgb_lut: np.ndarray, beat_flash: float, chrome: Optional[dict] = None):
        self.clear()
        cx, cy = self.w * 0.5, self.h * 0.5
        sx = min(cx, cy * self.y_scale) * 0.85
        sy = sx / self.y_scale
        depth = np.clip(1.0 - (stars.z / 2.6), 0.0, 1.0)
        star_rgb = rgb_lut[np.clip(((depth * 0.85 + beat_flash * 0.25) * (len(rgb_lut) - 1)).astype(np.int32), 0, len(rgb_lut) - 1)].astype(np.float32)
        if chrome is not None:
            doppler = np.clip((depth ** 1.5) * 0.55 + beat_flash * 0.30, 0.0, 0.75)[:, None]
            star_rgb = star_rgb * (1.0 - doppler) + chrome["accent_rgb"].astype(np.float32) * doppler
        star_rgb *= (0.38 + 0.62 * depth)[:, None]
        self.draw_segments(
            cx + (stars.x / stars.pz) * sx, cy + (stars.y / stars.pz) * sy,
            cx + (stars.x / stars.z) * sx, cy + (stars.y / stars.z) * sy,
            np.clip(star_rgb, 0, 255).astype(np.uint8), thickness=2 if beat_flash > 0.4 else 1, alpha=240,
        )


# ---------------------------------------------------------------------------
# HUD, State Controller, Main Visualizer Loop & CLI
# ---------------------------------------------------------------------------

def format_hud_bar(text: str, cols: int, color_mode: str, beat_flash: float = 0.0, theme: str = "aurora") -> str:
    trimmed = text[:cols].ljust(cols)
    if color_mode == "mono":
        return f"\x1b[7m{trimmed}\x1b[0m"
    chrome = get_theme_chrome(theme)
    bg_rgb = chrome["hud_beat"] if beat_flash >= 0.35 else chrome["hud_bg"]
    fg_rgb = chrome["axis_rgb"]
    r, g, b = int(bg_rgb[0]), int(bg_rgb[1]), int(bg_rgb[2])
    fr, fg_c, fb = int(fg_rgb[0]), int(fg_rgb[1]), int(fg_rgb[2])
    if color_mode == "truecolor":
        return f"\x1b[48;2;{r};{g};{b}m\x1b[38;2;{fr};{fg_c};{fb}m{trimmed}\x1b[0m"
    return f"\x1b[48;5;{rgb_to_xterm256(r, g, b)}m\x1b[38;5;{rgb_to_xterm256(fr, fg_c, fb)}m{trimmed}\x1b[0m"


def print_themes_preview(color_mode: str):
    cm = detect_color_mode(color_mode)
    print(f"Available themes ({len(THEMES)}, color mode: {cm}):")
    for name in THEMES:
        swatches = "".join(f"{c}██" for c in interpolate_palette(name, 14, cm))
        print(f"  {name:<16} {swatches}\x1b[0m")


def _alloc_bar_buffers(n: int):
    return (np.zeros(n, dtype=np.float32) for _ in range(4))


class _SignalQuit(BaseException):
    pass


def run_visualizer(args, ring: AudioRingBuffer, capture: AudioCapture):
    color_mode = detect_color_mode(args.color_mode)
    renderer = detect_renderer(args.renderer)
    mode_idx, theme_idx = MODES.index(args.mode), THEMES.index(args.theme)
    gain, auto_gain, show_peaks, use_gap, show_hud, show_grid = args.gain, not args.no_autogain, not args.no_peaks, not args.no_gap, not args.no_hud, not args.no_grid
    smooth_idx, mc_idx = SMOOTH_ORDER.index(args.smoothness), MC_METHODS.index(args.mc_method)

    px_fb = PixelFramebuffer(640, 360)
    analyzer = SpectrumAnalyzer(args.fft_size)

    cached_key = None
    smooth = peaks = peak_vel = peak_hold = np.zeros(1, dtype=np.float32)
    smooth_l = smooth_r = peaks_l = peaks_r = vel_l = vel_r = hold_l = hold_r = np.zeros(1, dtype=np.float32)

    scroll_history, spectrogram_cols = collections.deque(maxlen=512), collections.deque(maxlen=512)
    lissajous_trails, ridge_history, lorenz_pts = collections.deque(maxlen=8), collections.deque(maxlen=18), collections.deque(maxlen=950)
    lx, ly, lz, lorenz_yaw, lorenz_bass, lorenz_treble, lorenz_zoom = 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0
    radial_angle = milkdrop_t = prism_phase = scroll_rms_ema = scroll_pk_ema = wave_agc = 0.0
    wave_agc = 0.25
    hist_tick_accum = 0.0
    chladni_sim, starfield_sim, spark_burst = ChladniSim(), StarfieldSim(), SparkBurst()

    frame_interval = 1.0 / max(args.fps, 1)
    fps_ema, last_t = float(args.fps), time.monotonic()
    next_frame_t = last_t + frame_interval
    toast_msg, toast_until = "", 0.0
    cols, rows = 100, 30
    quit_requested = False

    def set_toast(msg: str):
        nonlocal toast_msg, toast_until
        toast_msg, toast_until = msg, time.monotonic() + 1.4

    with TerminalCanvas() as canvas:
        if args.renderer == "auto" and renderer == "pixel" and not canvas.probe_kitty():
            renderer = "blocks"

        def on_term_signal(signum, frame):
            raise _SignalQuit()

        signal.signal(signal.SIGWINCH, lambda *_: setattr(canvas, "resized", True))
        signal.signal(signal.SIGTERM, on_term_signal)
        signal.signal(signal.SIGHUP, on_term_signal)

        while True:
            loop_start = time.monotonic()
            dt = max(1e-4, min(0.1, loop_start - last_t))
            last_t = loop_start
            fps_ema = 0.9 * fps_ema + 0.1 * (1.0 / dt)
            if capture.error:
                raise RuntimeError(capture.error)

            for key in canvas.read_keys():
                if key in ("q", "Q", "ESC"):
                    return
                elif key in ("m", "M", " ", "ARROW_C", "ARROW_D"):
                    mode_idx = (mode_idx + (-1 if key == "ARROW_D" else 1)) % len(MODES)
                    cached_key = None
                    set_toast(f"Mode: {MODES[mode_idx]}")
                elif len(key) == 1 and key in MODE_HOTKEYS:
                    idx = MODE_HOTKEYS.index(key)
                    if idx < len(MODES):
                        mode_idx, cached_key = idx, None
                        set_toast(f"Mode: {MODES[mode_idx]} ({mode_idx + 1}/{len(MODES)})")
                elif key in ("c", "C"):
                    theme_idx = (theme_idx + (-1 if key == "C" else 1)) % len(THEMES)
                    set_toast(f"Theme: {THEMES[theme_idx]} ({theme_idx + 1}/{len(THEMES)})")
                elif key in ("+", "=", "ARROW_A", "-", "_", "ARROW_B"):
                    gain = min(gain * 1.15, 25.0) if key in ("+", "=", "ARROW_A") else max(gain / 1.15, 0.05)
                    set_toast(f"Gain: {gain:.2f}x")
                elif key in ("g", "G"):
                    auto_gain = not auto_gain
                    set_toast(f"Auto-Gain: {'ON' if auto_gain else 'OFF'}")
                elif key in ("p", "P"):
                    show_peaks = not show_peaks
                    set_toast(f"Peaks: {'ON' if show_peaks else 'OFF'}")
                elif key in ("s", "S"):
                    use_gap, cached_key = not use_gap, None
                    set_toast(f"Spacing: {'Gaps' if use_gap else 'Dense'}")
                elif key in ("h", "H"):
                    show_hud = not show_hud
                    canvas.resized = True
                elif key in ("f", "F"):
                    show_grid = not show_grid
                    canvas.resized = True
                    set_toast(f"Grid/Axis: {'ON' if show_grid else 'OFF'}")
                elif key in ("r", "R"):
                    analyzer.agc_scale = 0.25
                    peaks.fill(0.0)
                    peaks_l.fill(0.0)
                    peaks_r.fill(0.0)
                    chladni_sim.scatter()
                    set_toast("Reset AGC, Peaks & Sand")
                elif key in ("v", "V"):
                    smooth_idx = (smooth_idx + 1) % len(SMOOTH_ORDER)
                    set_toast(f"Smoothing: {SMOOTH_ORDER[smooth_idx]}")
                elif key in ("k", "K"):
                    mc_idx = (mc_idx + 1) % len(MC_METHODS)
                    set_toast(f"Monte Carlo: {MC_METHODS[mc_idx]}")
                elif key in ("x", "X"):
                    old_r = renderer
                    renderer = RENDERERS[(RENDERERS.index(renderer) + 1) % len(RENDERERS)]
                    if old_r == "pixel":
                        canvas.clear_kitty()
                    canvas.resized = True
                    lbl = {"pixel": "HD Kitty Pixels", "blocks": "2x2 Quadrant Blocks", "braille": "Unicode Braille"}[renderer]
                    set_toast(f"Renderer: {lbl}")

            mode, theme, mc_method = MODES[mode_idx], THEMES[theme_idx], MC_METHODS[mc_idx]
            hud_lines = 2 if show_hud else 0
            axis_row = 1 if (show_grid and mode in ("spectrum", "braille", "stereo") and rows >= 12) else 0
            canvas_h = max(2, rows - hud_lines - axis_row)
            use_fb = renderer in ("pixel", "blocks")
            use_px = use_fb or (mode not in CELL_MODES)

            if canvas.resized:
                canvas.resized = False
                term_size = shutil.get_terminal_size((100, 30))
                cols, rows = max(20, term_size.columns), max(8, term_size.lines)
                axis_row = 1 if (show_grid and mode in ("spectrum", "braille", "stereo") and rows >= 12) else 0
                canvas_h = max(2, rows - hud_lines - axis_row)
                if renderer == "pixel":
                    pw, ph = query_terminal_pixel_size(canvas.fd_out, rows, cols, canvas_h)
                    px_fb.resize(pw, ph, y_scale=1.0)
                    canvas.clear_screen()
                elif renderer == "blocks":
                    px_fb.resize(cols * 2, canvas_h * 2, y_scale=2.0)
                    canvas.clear_screen()
                elif use_px:
                    px_fb.resize(cols * 2, canvas_h * 4, y_scale=1.0)
                    canvas.clear_screen()
                cached_key = None
            elif renderer == "blocks":
                px_fb.resize(cols * 2, canvas_h * 2, y_scale=2.0)
            elif use_px and renderer == "braille":
                px_fb.resize(cols * 2, canvas_h * 4, y_scale=1.0)

            stereo_frames = ring.read_latest(analyzer.ring_needed)
            if capture.ended and (loop_start - ring.last_data_time) > 0.2:
                stereo_frames.fill(0.0)
            left_sig, right_sig = stereo_frames[:, 0], stereo_frames[:, 1]
            mono = 0.5 * (left_sig + right_sig)
            rms_l = float(np.sqrt(np.mean(left_sig[-1024:] ** 2)))
            rms_r = float(np.sqrt(np.mean(right_sig[-1024:] ** 2)))
            rms_now = 0.5 * (rms_l + rms_r)
            db_now, silent = 20.0 * math.log10(max(rms_now, 1e-5)), rms_now < 1e-4

            # Mode-independent spectral flux onset & autocorrelation BPM
            beat_flash = analyzer.update_onset_and_bpm(mono, ring.sample_rate, loop_start, dt, silent)

            if mode in ("scroll", "wave", "lissajous"):
                bar_w, step, num_bars = 1, 1, (px_fb.w if use_fb else cols)
            elif mode == "lorenz":
                bar_w, step, num_bars = 1, 1, 16
            elif mode == "spectrogram":
                bar_w, step, num_bars = 1, 1, (min(128, px_fb.h) if use_fb else canvas_h)
            elif mode not in ("spectrum", "mirror", "stereo"):
                bar_w, step = 1, 1
                num_bars = 64 if mode in ("radial", "cymatics", "faraday", "vortex", "hybrid") else max(16, min(cols if renderer == "braille" else 128, 128))
            else:
                if use_fb:
                    bar_w, step = 1, 1
                    num_bars = min(56, max(16, px_fb.w // 12)) if mode == "stereo" else min(96, max(24, px_fb.w // 7))
                else:
                    bar_w = 2 if (cols >= 84 and use_gap) else 1
                    gap = 1 if (use_gap and cols >= 44) else 0
                    step = bar_w + gap
                    avail = max(1, (cols - 2) // 2) if mode == "stereo" else cols
                    num_bars = max(6, (avail + gap) // step)

            layout_key = (mode, num_bars, ring.sample_rate)
            if layout_key != cached_key:
                cached_key = layout_key
                if mode not in ("scroll", "wave", "lissajous"):
                    analyzer.configure(num_bars, ring.sample_rate)
                smooth, peaks, peak_vel, peak_hold = _alloc_bar_buffers(num_bars)
                smooth_l, peaks_l, vel_l, hold_l = _alloc_bar_buffers(num_bars)
                smooth_r, peaks_r, vel_r, hold_r = _alloc_bar_buffers(num_bars)

            sp = SMOOTH_PRESETS[SMOOTH_ORDER[smooth_idx]]
            a_up, a_dn = 1.0 - math.exp(-dt / sp["tau_up"]), 1.0 - math.exp(-dt / sp["tau_dn"])
            prism_phase = (prism_phase + dt * 0.14) % 1.0
            if not silent:
                wave_t = max(0.08, rms_now * 2.8)
                wave_agc += (1.0 - math.exp(-dt / (0.12 if wave_t > wave_agc else 1.6))) * (wave_t - wave_agc)

            # Fixed 60 Hz step budget for scrolling/trail histories so visuals are FPS-independent
            hist_tick_accum += dt
            hist_ticks = min(3, int(hist_tick_accum * 60.0))
            if hist_ticks > 0:
                hist_tick_accum -= hist_ticks / 60.0

            chrome = get_theme_chrome(theme)
            chars, col_grid = (None, None) if use_fb else ([[" "] * cols for _ in range(canvas_h)], [[""] * cols for _ in range(canvas_h)])
            axis_start_x, axis_step, stereo_cx_axis = 0, step, None

            if mode in ("spectrum", "mirror", "braille", "radial", "horizon", "hybrid"):
                raw = np.zeros(num_bars, dtype=np.float32) if silent else analyzer.compute_bands(mono) * gain
                target = spatial_smooth(analyzer.normalize(raw, dt, auto_gain, silent), sp["spatial"])
                smooth = np.where(target > smooth, smooth + a_up * (target - smooth), smooth + a_dn * (target - smooth))
                advance_peaks(smooth, peaks, peak_vel, peak_hold, dt, sp["gravity"], sp["hold"])
                prism_phase = (prism_phase + beat_flash * dt * 0.35) % 1.0
                bass_level = float(np.mean(smooth[: max(1, num_bars // 6)]))

                if mode in ("radial", "hybrid"):
                    radial_angle = (radial_angle + dt * (0.35 + beat_flash * 0.65)) % (2.0 * math.pi)
                if mode == "hybrid":
                    if beat_flash > 0.72 and not silent:
                        spark_burst.spawn(22, 0.28, 0.95 + 0.6 * beat_flash)
                    spark_burst.step(dt)
                elif mode == "horizon" and hist_ticks > 0:
                    for _ in range(hist_ticks):
                        ridge_history.append(smooth.copy())

                if use_px:
                    rgb_lut = interpolate_rgb_array(theme, 128, boost=beat_flash * 0.22, phase=prism_phase)
                    if mode == "braille":
                        px_fb.render_curve(smooth, rgb_lut, chrome=chrome)
                        axis_start_x, axis_step = 0, max(1, cols // max(1, num_bars))
                    elif mode == "radial":
                        px_fb.render_radial(smooth, bass_level, radial_angle, rgb_lut, chrome=chrome)
                    elif mode == "hybrid":
                        scope_g = gain * (1.0 / max(wave_agc * 0.9, 0.08) if auto_gain else 1.0)
                        px_fb.render_hybrid(smooth, bass_level, radial_angle, stereo_frames, scope_g, spark_burst, rgb_lut, chrome=chrome)
                    elif mode == "horizon":
                        px_fb.render_horizon(ridge_history, rgb_lut, chrome=chrome)
                    else:
                        px_fb.render_bars(smooth, peaks, rgb_lut, mirror=(mode == "mirror"), show_peaks=show_peaks, show_grid=show_grid, use_gap=use_gap, chrome=chrome)
                        slot_c = cols / float(max(1, num_bars))
                        axis_start_x, axis_step = 0, max(1, int(round(slot_c)))
                    if not use_fb:
                        rgba_to_braille_grid(px_fb.rgba, chars, col_grid, cols, canvas_h, color_mode)
                else:
                    palette = interpolate_palette(theme, max(8, canvas_h), color_mode, boost=beat_flash * 0.22, phase=prism_phase)
                    peak_col = ansi_fg_from_rgb(chrome["accent_rgb"], color_mode) if color_mode != "mono" else ""
                    if show_grid and mode == "spectrum":
                        paint_grid_lines(chars, col_grid, canvas_h, cols, color_mode, theme)
                    start_x = max(0, (cols - (num_bars * step - (step - bar_w))) // 2)
                    axis_start_x, axis_step = start_x, step
                    for i in range(num_bars):
                        bx = start_x + i * step
                        if bx + bar_w > cols:
                            break
                        paint_bar(chars, col_grid, canvas_h, bx, bar_w, float(smooth[i]), float(peaks[i]), palette, peak_col, show_peaks, mirror=(mode == "mirror"))

            elif mode == "stereo":
                raw_l = np.zeros(num_bars, dtype=np.float32) if silent else analyzer.compute_bands(left_sig) * gain
                raw_r = np.zeros(num_bars, dtype=np.float32) if silent else analyzer.compute_bands(right_sig) * gain
                if auto_gain and not silent:
                    t_ag = max(0.08, float(np.percentile(np.concatenate((raw_l, raw_r)), 96)))
                    analyzer.agc_scale = max(0.08, analyzer.agc_scale + (1.0 - math.exp(-dt / (0.09 if t_ag > analyzer.agc_scale else 2.4))) * (t_ag - analyzer.agc_scale))
                div = analyzer.agc_scale if auto_gain else 1.5
                t_l = spatial_smooth(np.clip(raw_l / div, 0.0, 1.0), sp["spatial"])
                t_r = spatial_smooth(np.clip(raw_r / div, 0.0, 1.0), sp["spatial"])
                smooth_l = np.where(t_l > smooth_l, smooth_l + a_up * (t_l - smooth_l), smooth_l + a_dn * (t_l - smooth_l))
                smooth_r = np.where(t_r > smooth_r, smooth_r + a_up * (t_r - smooth_r), smooth_r + a_dn * (t_r - smooth_r))
                advance_peaks(smooth_l, peaks_l, vel_l, hold_l, dt, sp["gravity"], sp["hold"])
                advance_peaks(smooth_r, peaks_r, vel_r, hold_r, dt, sp["gravity"], sp["hold"])
                stereo_cx_axis = cols // 2
                if use_fb:
                    px_fb.render_stereo_bars(smooth_l, peaks_l, smooth_r, peaks_r, interpolate_rgb_array(theme, 128, boost=beat_flash * 0.22, phase=prism_phase), show_peaks, show_grid, use_gap, chrome=chrome)
                else:
                    palette = interpolate_palette(theme, max(8, canvas_h), color_mode, boost=beat_flash * 0.22, phase=prism_phase)
                    peak_col = ansi_fg_from_rgb(chrome["accent_rgb"], color_mode) if color_mode != "mono" else ""
                    if show_grid:
                        paint_grid_lines(chars, col_grid, canvas_h, cols, color_mode, theme)
                    div_col = ansi_fg_from_rgb(chrome["axis_rgb"], color_mode) if color_mode != "mono" else "\x1b[2m"
                    for r in range(canvas_h):
                        chars[r][stereo_cx_axis], col_grid[r][stereo_cx_axis] = "│", div_col
                    for i in range(num_bars):
                        lx, rx = stereo_cx_axis - 1 - (i + 1) * step + (step - bar_w), stereo_cx_axis + 2 + i * step
                        if lx >= 0:
                            paint_bar(chars, col_grid, canvas_h, lx, bar_w, float(smooth_l[i]), float(peaks_l[i]), palette, peak_col, show_peaks)
                        if rx + bar_w <= cols:
                            paint_bar(chars, col_grid, canvas_h, rx, bar_w, float(smooth_r[i]), float(peaks_r[i]), palette, peak_col, show_peaks)

            elif mode in ("cymatics", "faraday", "vortex"):
                cym_kind = "polar" if mode == "cymatics" else mode
                raw = np.zeros(num_bars, dtype=np.float32) if silent else analyzer.compute_bands(mono) * gain
                norm_spec = analyzer.normalize(raw, dt, auto_gain, silent)
                centroid = float(np.sum(norm_spec * np.linspace(0.0, 1.0, len(norm_spec)))) / (float(np.sum(norm_spec)) + 1e-6)
                chladni_sim.ensure_size(px_fb.w, px_fb.h, y_scale=px_fb.y_scale, max_particles=48000 if renderer == "pixel" else (24000 if renderer == "blocks" else 42000), density=0.25 if renderer == "pixel" else 1.2)
                p_energy = chladni_sim.step(dt, float(np.mean(norm_spec)) * 1.4, centroid, beat_flash, loop_start, silent, kind=cym_kind, mc_method=mc_method)
                px_fb.render_cymatics(chladni_sim, p_energy, interpolate_rgb_array(theme, 128, boost=beat_flash * 0.22, phase=prism_phase), chrome=chrome)
                if not use_fb:
                    rgba_to_braille_grid(px_fb.rgba, chars, col_grid, cols, canvas_h, color_mode)

            elif mode == "milkdrop":
                raw = np.zeros(num_bars, dtype=np.float32) if silent else analyzer.compute_bands(mono) * gain
                bass_e = float(np.mean(raw[: max(1, num_bars // 6)]))
                treble_e = float(np.mean(raw[max(1, num_bars // 2) :]))
                milkdrop_t += dt * (0.45 + 0.85 * min(1.5, bass_e) + 0.7 * beat_flash)
                px_fb.render_milkdrop(milkdrop_t, bass_e, treble_e, beat_flash, interpolate_rgb_array(theme, 128, boost=beat_flash * 0.25, phase=prism_phase))
                if not use_fb:
                    rgba_to_braille_grid(px_fb.rgba, chars, col_grid, cols, canvas_h, color_mode)

            elif mode == "starfield":
                raw = np.zeros(num_bars, dtype=np.float32) if silent else analyzer.compute_bands(mono) * gain
                bass_e = float(np.mean(raw[: max(1, num_bars // 6)]))
                starfield_sim.step(dt, bass_e, beat_flash, silent)
                px_fb.render_starfield(starfield_sim, interpolate_rgb_array(theme, 128, boost=beat_flash * 0.25, phase=prism_phase), beat_flash, chrome=chrome)
                if not use_fb:
                    rgba_to_braille_grid(px_fb.rgba, chars, col_grid, cols, canvas_h, color_mode)

            elif mode == "wave":
                wave_g = gain * (1.0 / wave_agc if auto_gain else 1.0)
                px_fb.render_wave(stereo_frames, wave_g, interpolate_rgb_array(theme, 128, phase=prism_phase), show_grid and use_fb, chrome=chrome)
                if not use_fb:
                    if show_grid:
                        paint_grid_lines(chars, col_grid, canvas_h, cols, color_mode, theme)
                    rgba_to_braille_grid(px_fb.rgba, chars, col_grid, cols, canvas_h, color_mode)

            elif mode == "lissajous":
                if hist_ticks > 0 or not lissajous_trails:
                    scope_g = gain * (1.0 / max(wave_agc * 0.92, 0.08) if auto_gain else 1.0)
                    k3 = np.array([0.22, 0.56, 0.22], dtype=np.float32)
                    seg_l = np.convolve(np.pad(stereo_frames[-240::2, 0] * scope_g, 1, mode="edge"), k3, mode="valid")
                    seg_r = np.convolve(np.pad(stereo_frames[-240::2, 1] * scope_g, 1, mode="edge"), k3, mode="valid")
                    pts = np.column_stack((np.clip((seg_l - seg_r) * 0.85, -1.0, 1.0), np.clip((seg_l + seg_r) * 0.85, -1.0, 1.0))).astype(np.float32)
                    lissajous_trails.append(pts)
                px_fb.render_lissajous(lissajous_trails, interpolate_rgb_array(theme, 128, boost=beat_flash * 0.2, phase=prism_phase), show_grid and use_fb, chrome=chrome)
                if not use_fb:
                    if show_grid:
                        paint_grid_lines(chars, col_grid, canvas_h, cols, color_mode, theme)
                    rgba_to_braille_grid(px_fb.rgba, chars, col_grid, cols, canvas_h, color_mode)

            elif mode == "lorenz":
                raw = np.zeros(num_bars, dtype=np.float32) if silent else analyzer.compute_bands(mono) * gain
                lorenz_bass += a_dn * (float(np.mean(raw[: max(1, num_bars // 6)])) - lorenz_bass)
                lorenz_treble += a_dn * (float(np.mean(raw[max(1, num_bars // 2) :])) - lorenz_treble)
                sigma, rho, beta, step_dt = 10.0 + min(3.5, lorenz_treble * 2.2), 26.0 + min(16.0, lorenz_bass * 11.0), 8.0 / 3.0, 0.0055
                for _ in range(int(24 + min(18, lorenz_bass * 14))):
                    dx1, dy1, dz1 = sigma * (ly - lx), lx * (rho - lz) - ly, lx * ly - beta * lz
                    mx, my, mz = lx + 0.5 * step_dt * dx1, ly + 0.5 * step_dt * dy1, lz + 0.5 * step_dt * dz1
                    lx, ly, lz = lx + step_dt * (sigma * (my - mx)), ly + step_dt * (mx * (rho - mz) - my), lz + step_dt * (mx * my - beta * mz)
                    if abs(lx) > 100 or abs(ly) > 100 or abs(lz) > 120:
                        lx, ly, lz = 0.1, 0.0, 0.0
                    lorenz_pts.append((lx, ly, lz))
                lorenz_yaw = (lorenz_yaw + dt * (0.40 + lorenz_treble * 0.55)) % (2.0 * math.pi)
                lorenz_zoom += a_up * ((1.0 + 0.22 * min(1.0, lorenz_bass) + 0.12 * beat_flash) - lorenz_zoom)
                px_fb.render_lorenz(lorenz_pts, lorenz_yaw, 0.35, lorenz_zoom, interpolate_rgb_array(theme, 128, boost=beat_flash * 0.25, phase=prism_phase))
                if not use_fb:
                    rgba_to_braille_grid(px_fb.rgba, chars, col_grid, cols, canvas_h, color_mode)

            elif mode == "spectrogram":
                raw = np.zeros(num_bars, dtype=np.float32) if silent else analyzer.compute_bands(mono) * gain
                col_vals = spatial_smooth(analyzer.normalize(raw, dt, auto_gain, silent), sp["spatial"] * 0.65)
                lut = interpolate_rgb_array(theme, 128, phase=prism_phase)
                for _ in range(max(1, hist_ticks) if hist_ticks > 0 else 0):
                    if use_fb:
                        px_fb.render_spectrogram_col(col_vals, lut)
                    else:
                        spectrogram_cols.append(col_vals)
                        while len(spectrogram_cols) > cols:
                            spectrogram_cols.popleft()
                if not use_fb:
                    palette = interpolate_palette(theme, 16, color_mode, phase=prism_phase)
                    offset_x = cols - len(spectrogram_cols)
                    for cx_off, spec_col in enumerate(spectrogram_cols):
                        x = offset_x + cx_off
                        for row_off in range(min(canvas_h, len(spec_col))):
                            v = float(spec_col[row_off])
                            if v >= 0.04:
                                r = canvas_h - 1 - row_off
                                chars[r][x] = DENSITY_CHARS[min(len(DENSITY_CHARS) - 1, max(1, int(v * (len(DENSITY_CHARS) - 1))))]
                                col_grid[r][x] = palette[min(len(palette) - 1, int(v * (len(palette) - 1)))]

            elif mode == "scroll":
                val = 0.0 if silent else math.log1p(rms_now * 32.0 * gain)
                pk_amp = 0.0 if silent else math.log1p(float(np.max(np.abs(mono[-1024:]))) * 16.0 * gain)
                scroll_rms_ema += (a_up if val > scroll_rms_ema else a_dn) * (val - scroll_rms_ema)
                scroll_pk_ema += (a_up if pk_amp > scroll_pk_ema else a_dn) * (pk_amp - scroll_pk_ema)
                sample_pair = analyzer.normalize(np.array([scroll_rms_ema, scroll_pk_ema * 0.85], dtype=np.float32), dt, auto_gain, silent)
                norm_pair = (float(min(1.0, sample_pair[0])), float(min(1.0, sample_pair[1] / 0.85)))
                for _ in range(hist_ticks):
                    scroll_history.append(norm_pair)
                    while len(scroll_history) > max(cols, px_fb.w):
                        scroll_history.popleft()
                if use_fb:
                    px_fb.render_scroll(scroll_history, interpolate_rgb_array(theme, 128, boost=beat_flash * 0.18, phase=prism_phase), show_peaks, show_grid, chrome=chrome)
                else:
                    palette = interpolate_palette(theme, max(8, canvas_h), color_mode, boost=beat_flash * 0.18, phase=prism_phase)
                    peak_col = ansi_fg_from_rgb(chrome["accent_rgb"], color_mode) if color_mode != "mono" else ""
                    if show_grid:
                        paint_grid_lines(chars, col_grid, canvas_h, cols, color_mode, theme)
                    offset_x = cols - len(scroll_history)
                    for i, (v_rms, v_pk) in enumerate(scroll_history):
                        paint_bar(chars, col_grid, canvas_h, offset_x + i, 1, v_rms, v_pk, palette, peak_col, show_peaks)

            axis_bar = format_freq_axis_line(cols, axis_start_x, axis_step, analyzer.plan, color_mode, theme, stereo_cx=stereo_cx_axis) if axis_row else None
            top_bar = bot_bar = None
            if show_hud:
                beat_str = "* BEAT" if beat_flash > 0.35 else "o     "
                bpm_str = f" {analyzer.bpm:4.0f} BPM" if analyzer.bpm > 0 else ""
                bal = (rms_r - rms_l) / max(rms_l + rms_r, 1e-6)
                bal_pos = int(round((bal + 1.0) * 3.0))
                bal_meter = "".join("*" if i == bal_pos else "-" for i in range(7))
                src_lbl = f"{capture.source_label} [ENDED]" if capture.ended else capture.source_label
                res_lbl = f"{px_fb.w}x{px_fb.h} ({renderer})" if use_fb else f"{cols}x{canvas_h} (braille)"
                mc_lbl = f" | mc:{mc_method}" if (mode in ("cymatics", "faraday", "vortex") and mc_method != "deterministic") else ""
                top_hud = f" {src_lbl} | {res_lbl} | [{mode_idx + 1}/{len(MODES)} {mode}]{mc_lbl} {theme} ({theme_idx + 1}/{len(THEMES)}) | {SMOOTH_ORDER[smooth_idx]} | Gain {gain:.2f}x ({'AUTO' if auto_gain else 'MAN'}) | L[{bal_meter}]R {db_now:5.1f}dB | {beat_str}{bpm_str} | {fps_ema:4.0f}fps"
                top_bar = format_hud_bar(top_hud, cols, color_mode, beat_flash, theme)
                bot_hud = f" >> {toast_msg}" if (toast_msg and loop_start < toast_until) else " [1-9,0,!-&/Space] Mode  [c/C] Theme  [x] Pixel/Blocks/Braille  [k] MC  [v] Smooth  [h] HUD  [q] Quit"
                bot_bar = format_hud_bar(bot_hud, cols, color_mode, 0.0, theme)

            if renderer == "pixel":
                canvas.render_pixel_frame(px_fb.rgba, cols, rows, canvas_h, top_bar, axis_bar, bot_bar)
            else:
                out_lines = [top_bar] if top_bar is not None else []
                out_lines.extend(render_quadrant_lines(px_fb.rgba, cols, canvas_h, color_mode) if renderer == "blocks" else grid_to_lines(chars, col_grid))
                if axis_bar is not None:
                    out_lines.append(axis_bar)
                if bot_bar is not None:
                    out_lines.append(bot_bar)
                canvas.render_frame(out_lines)

            now_end = time.monotonic()
            sleep_for = next_frame_t - now_end
            if sleep_for > 0:
                time.sleep(sleep_for)
                next_frame_t += frame_interval
            else:
                next_frame_t = now_end + frame_interval


def parse_args():
    p = argparse.ArgumentParser(description="Full-screen real-time terminal music visualizer (defaults to live macOS speaker output).")
    p.add_argument("wav_positional", nargs="?", help="Optional WAV file path (16/24/32-bit PCM or float32).")
    p.add_argument("--source", choices=("speaker", "wav", "ffmpeg", "demo"), default="speaker", help="Audio input source.")
    p.add_argument("--wav", help="Path to a WAV file (with --source wav).")
    p.add_argument("--play", action="store_true", help="Also play WAV via afplay while visualizing.")
    p.add_argument("--loop", action="store_true", help="Loop WAV playback.")
    p.add_argument("--device", default="0", help="AVFoundation device index/name with --source ffmpeg (default: 0).")
    p.add_argument("--mode", choices=MODES, default="spectrum", help="Initial visualization mode.")
    p.add_argument("--theme", choices=THEMES, default="aurora", help="Color theme.")
    p.add_argument("--smoothness", choices=SMOOTH_ORDER, default="smooth", help="Smoothing preset (default: smooth).")
    p.add_argument("--renderer", choices=("auto", "pixel", "blocks", "braille", "text"), default="auto", help="Render backend.")
    p.add_argument("--mc-method", choices=MC_METHODS, default="deterministic", help="Particle solver for cymatics/faraday/vortex.")
    p.add_argument("--color-mode", choices=("auto", "truecolor", "256", "mono"), default="auto", help="Terminal color mode.")
    p.add_argument("--fps", type=int, default=60, help="Target FPS (1..240, default: 60).")
    p.add_argument("--fft-size", type=int, default=4096, help="FFT window size (power of two >= 1024, default: 4096).")
    p.add_argument("--gain", type=float, default=1.0, help="Initial gain multiplier (default: 1.0).")
    p.add_argument("--no-autogain", action="store_true", help="Disable automatic gain control.")
    p.add_argument("--no-peaks", action="store_true", help="Hide peak-hold markers.")
    p.add_argument("--no-gap", action="store_true", help="Draw dense bars with no gaps.")
    p.add_argument("--no-hud", action="store_true", help="Start with top/bottom HUD hidden.")
    p.add_argument("--no-grid", action="store_true", help="Hide background grid lines and frequency ticks.")
    p.add_argument("--list-themes", action="store_true", help="Print all themes with color swatches and exit.")
    p.add_argument("--debug", action="store_true", help="Print full tracebacks on error.")
    args = p.parse_args()

    if not (1 <= args.fps <= 240):
        p.error("--fps must be between 1 and 240.")
    if args.fft_size < 1024 or (args.fft_size & (args.fft_size - 1)) != 0:
        p.error("--fft-size must be a power of two >= 1024.")
    if args.wav_positional and not args.wav:
        args.wav, args.source = args.wav_positional, "wav"
    elif args.wav and args.source == "speaker":
        args.source = "wav"
    return args


def main():
    args = parse_args()
    if args.list_themes:
        print_themes_preview(args.color_mode)
        return
    ring = AudioRingBuffer(capacity_frames=max(args.fft_size * 4, 32768))
    capture = AudioCapture(args, ring)
    capture.start()
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        if capture.error:
            capture.stop()
            sys.exit(f"Audio capture error: {capture.error}")
        if ring.last_data_time > 0 or args.source == "demo":
            break
        time.sleep(0.02)
    try:
        run_visualizer(args, ring, capture)
    except (KeyboardInterrupt, _SignalQuit):
        pass
    except Exception as exc:
        capture.stop()
        if args.debug:
            traceback.print_exc()
        sys.exit(f"Visualizer error: {exc}")
    finally:
        capture.stop()


if __name__ == "__main__":
    main()
