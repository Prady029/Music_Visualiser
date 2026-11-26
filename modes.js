/**
 * HiDPI Canvas 2D Visualization Modes + Chladni/Faraday/Vortex Particle Simulators
 */

import { getThemeChrome, getThemeLut, rgbCss } from "./themes.js";

export const WEB_MODES = [
  { id: "spectrum",    label: "Spectrum" },
  { id: "mirror",      label: "Mirror" },
  { id: "curve",       label: "Aura Curve" },
  { id: "radial",      label: "Radial" },
  { id: "hybrid",      label: "Hybrid Burst" },
  { id: "cymatics",    label: "Cymatics" },
  { id: "faraday",     label: "Faraday" },
  { id: "vortex",      label: "Vortex" },
  { id: "horizon",     label: "Horizon" },
  { id: "starfield",   label: "Starfield" },
  { id: "wave",        label: "Oscilloscope" },
  { id: "lissajous",   label: "Lissajous" },
  { id: "stereo",      label: "Stereo L/R" },
  { id: "spectrogram", label: "Spectrogram" },
];

// Precompute Bessel J_m(z) and dJ_m/dz LUTs for Cymatics/Vortex simulations
const BESSEL_Z_MAX = 90;
const BESSEL_N = 1024;
const BESSEL_INV_DZ = (BESSEL_N - 1) / BESSEL_Z_MAX;
const BESSEL_J = [];
const BESSEL_DJ = [];
(() => {
  const steps = 48;
  const dt = Math.PI / steps;
  for (let m = 0; m <= 10; m++) {
    const jm = new Float32Array(BESSEL_N);
    for (let zi = 0; zi < BESSEL_N; zi++) {
      const z = (zi / (BESSEL_N - 1)) * BESSEL_Z_MAX;
      let sum = 0;
      for (let s = 0; s <= steps; s++) {
        const tau = s * dt;
        const w = s === 0 || s === steps ? 0.5 : 1.0;
        sum += w * Math.cos(z * Math.sin(tau) - m * tau);
      }
      jm[zi] = (sum * dt) / Math.PI;
    }
    BESSEL_J.push(jm);
  }
  for (let m = 0; m < 10; m++) {
    const dj = new Float32Array(BESSEL_N);
    if (m === 0) {
      for (let zi = 0; zi < BESSEL_N; zi++) dj[zi] = -BESSEL_J[1][zi];
    } else {
      for (let zi = 0; zi < BESSEL_N; zi++) dj[zi] = 0.5 * (BESSEL_J[m - 1][zi] - BESSEL_J[m + 1][zi]);
    }
    BESSEL_DJ.push(dj);
  }
})();

const CHLADNI_MODES = [
  [0, 13.5, 0.0, 4, 10.5, 0.38],
  [3, 13.0, 0.22, 0, 15.5, 0.32],
  [4, 14.5, -0.18, 0, 12.0, 0.36],
  [5, 15.5, 0.26, 0, 17.5, 0.30],
  [6, 16.5, -0.22, 3, 11.5, 0.34],
  [7, 17.5, 0.20, 0, 19.5, 0.28],
  [8, 19.0, -0.26, 4, 13.0, 0.36],
];
const FARADAY_MODES = [
  [5, 11.5, 0.35, 0.0], [6, 12.5, -0.30, 0.2], [7, 14.0, 0.28, 0.0],
  [8, 15.0, -0.25, 0.4], [6, 17.0, 0.32, 0.6], [9, 18.0, -0.22, 0.0],
];
const VORTEX_MODES = [
  [2, 12.0, 4.5, 0.65], [3, 13.5, -5.2, -0.70], [4, 15.0, 6.0, 0.75],
  [5, 16.5, -6.5, -0.80], [6, 18.0, 7.2, 0.85], [3, 20.0, -8.0, -0.90],
];

function cubicUpsample(values, outLen, periodic = false) {
  const n = values.length;
  const out = new Float32Array(outLen);
  if (n < 4 || outLen <= n) {
    for (let i = 0; i < outLen; i++) {
      const p = (i / Math.max(1, outLen - 1)) * (n - 1);
      const lo = Math.min(n - 2, Math.floor(p));
      const f = p - lo;
      out[i] = values[lo] * (1 - f) + values[lo + 1] * f;
    }
    return out;
  }
  for (let i = 0; i < outLen; i++) {
    let idx, u, p0, p1, p2, p3;
    if (periodic) {
      const t = (i / outLen) * n;
      idx = Math.floor(t) % n;
      u = t - Math.floor(t);
      p0 = values[(idx - 1 + n) % n];
      p1 = values[idx];
      p2 = values[(idx + 1) % n];
      p3 = values[(idx + 2) % n];
    } else {
      const t = (i / (outLen - 1)) * (n - 1);
      idx = Math.min(n - 2, Math.floor(t));
      u = t - idx;
      p0 = values[Math.max(0, idx - 1)];
      p1 = values[idx];
      p2 = values[Math.min(n - 1, idx + 1)];
      p3 = values[Math.min(n - 1, idx + 2)];
    }
    const u2 = u * u;
    const val = 0.5 * (2 * p1 + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u2 + (-p0 + 3 * p1 - 3 * p2 + p3) * (u2 * u));
    out[i] = Math.max(0, Math.min(1, val));
  }
  return out;
}

class ChladniSim {
  constructor(count = 5200) {
    this.n = count;
    this.x = new Float32Array(count);
    this.y = new Float32Array(count);
    this.vx = new Float32Array(count);
    this.vy = new Float32Array(count);
    this.mass = new Float32Array(count);
    this.energy = new Float32Array(count);
    this.xMax = 1.6;
    this.yMax = 1.0;
    this.curIdx = 1;
    this.spinPhase = 0;
    this.holdTimer = 0;
    this.lastBeatT = 0;
    this.scatter();
  }

  setAspect(w, h) {
    const md = Math.max(1, Math.min(w, h));
    this.xMax = w / md;
    this.yMax = h / md;
  }

  scatter() {
    for (let i = 0; i < this.n; i++) {
      this.x[i] = (Math.random() * 2 - 1) * this.xMax;
      this.y[i] = (Math.random() * 2 - 1) * this.yMax;
      this.vx[i] = 0;
      this.vy[i] = 0;
      this.mass[i] = 0.7 + Math.random() * 0.7;
      this.energy[i] = 0;
    }
  }

  _bessel(m, z) {
    const pos = Math.max(0, Math.min(BESSEL_N - 1.001, z * BESSEL_INV_DZ));
    const lo = Math.floor(pos);
    const f = pos - lo;
    const jm = BESSEL_J[m][lo] * (1 - f) + BESSEL_J[m][lo + 1] * f;
    const djm = BESSEL_DJ[m][lo] * (1 - f) + BESSEL_DJ[m][lo + 1] * f;
    return [jm, djm];
  }

  step(dt, energy, centroid, beatFlash, now, silent, kind = "cymatics") {
    this.holdTimer += dt;
    this.spinPhase += dt * (0.45 + 0.65 * Math.min(1, energy));
    const table = kind === "faraday" ? FARADAY_MODES : (kind === "vortex" ? VORTEX_MODES : CHLADNI_MODES);
    const nModes = table.length;
    const targetIdx = Math.min(nModes - 1, Math.max(0, Math.floor(centroid * nModes)));
    if ((this.holdTimer > 2.0 || (beatFlash > 0.78 && now - this.lastBeatT > 1.3)) && targetIdx !== this.curIdx) {
      this.curIdx = targetIdx;
      this.holdTimer = 0;
      if (beatFlash > 0.78) this.lastBeatT = now;
    }

    const mode = table[this.curIdx % nModes];
    const damp = Math.exp(-dt * 14);
    const drive = 0.48 + 1.05 * Math.min(1.4, energy);
    const driftK = 0.022 * drive;

    for (let i = 0; i < this.n; i++) {
      let x = this.x[i];
      let y = this.y[i];
      let w = 0, gx = 0, gy = 0;

      if (kind === "faraday") {
        const [nW, k, spd, sym] = mode;
        const norm = 1 / Math.sqrt(nW);
        const rot = this.spinPhase * spd * 0.35;
        for (let j = 0; j < nW; j++) {
          const ang = (2 * Math.PI * j) / nW + rot;
          const ca = Math.cos(ang);
          const sa = Math.sin(ang);
          const arg = k * (x * ca + y * sa) + (j % 2 === 0 ? this.spinPhase * spd : -this.spinPhase * spd + sym);
          w += Math.cos(arg);
          const sArg = Math.sin(arg);
          gx -= k * ca * sArg;
          gy -= k * sa * sArg;
        }
        w *= norm; gx *= norm; gy *= norm;
      } else {
        const r = Math.hypot(x, y);
        const rSafe = Math.max(r, 1e-3);
        const cosT = x / rSafe;
        const sinT = y / rSafe;
        const theta = Math.atan2(y, x);
        const env = Math.sqrt(1 + 0.55 * r);
        const denv = 0.275 / env;

        const evalTerm = (m, k, phi, twist = 0) => {
          const [jm, djm] = this._bessel(m, k * r);
          if (m === 0 && twist === 0) {
            const tw = jm * env;
            const dwr = k * djm * env + jm * denv;
            return [tw, dwr * cosT, dwr * sinT];
          }
          const ang = m * theta - twist * r + phi;
          const ca = Math.cos(ang);
          const sa = Math.sin(ang);
          const tw = jm * ca * env;
          const dwr = (k * djm * env + jm * denv) * ca + jm * env * twist * sa;
          const dwt = -(m * jm * env / rSafe) * sa;
          return [tw, dwr * cosT - dwt * sinT, dwr * sinT + dwt * cosT];
        };

        if (kind === "vortex") {
          const [m, k, twist, spd] = mode;
          [w, gx, gy] = evalTerm(m, k, this.spinPhase * spd, twist);
        } else {
          const [m1, k1, sp1, m2, k2, a2] = mode;
          const [w1, gx1, gy1] = evalTerm(m1, k1, this.spinPhase * sp1, 0);
          const [w2, gx2, gy2] = evalTerm(m2, k2, -this.spinPhase * 0.5, 0);
          w = w1 + a2 * w2;
          gx = gx1 + a2 * gx2;
          gy = gy1 + a2 * gy2;
        }
      }

      if (silent) {
        this.vx[i] *= 0.8;
        this.vy[i] *= 0.8;
      } else {
        const absW = Math.abs(w);
        const denom = (Math.hypot(gx, gy) + 0.55) * this.mass[i];
        let fx = (-driftK * w * gx) / denom;
        let fy = (-driftK * w * gy) / denom;
        if (kind === "vortex") {
          const swirl = (0.006 * (0.5 + energy)) / Math.max(0.08, Math.hypot(x, y));
          fx -= y * swirl;
          fy += x * swirl;
        }
        const vib = (0.015 * Math.min(1.5, energy) * absW + 0.042 * beatFlash * (0.18 + absW)) / this.mass[i];
        const jx = (Math.random() - 0.5) * 2 * vib;
        const jy = (Math.random() - 0.5) * 2 * vib;
        this.vx[i] = Math.max(-0.1, Math.min(0.1, this.vx[i] * damp + fx * (dt * 60) + jx));
        this.vy[i] = Math.max(-0.1, Math.min(0.1, this.vy[i] * damp + fy * (dt * 60) + jy));
        x += this.vx[i] * (dt * 27);
        y += this.vy[i] * (dt * 27);
        if (Math.abs(x) > this.xMax * 1.02 || Math.abs(y) > this.yMax * 1.02) {
          x = (Math.random() * 2 - 1) * this.xMax;
          y = (Math.random() * 2 - 1) * this.yMax;
          this.vx[i] = this.vy[i] = 0;
        }
        this.x[i] = x;
        this.y[i] = y;
        this.energy[i] = Math.min(1, Math.hypot(this.vx[i], this.vy[i]) * 18 + absW * 0.35);
      }
    }
  }
}

export class VisualizerRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d", { alpha: false });
    this.w = 1280;
    this.h = 720;
    this.dpr = 1;

    this.chladni = new ChladniSim(5200);
    this.stars = Array.from({ length: 650 }, () => ({
      x: (Math.random() * 2 - 1) * 1.6,
      y: (Math.random() * 2 - 1) * 1.1,
      z: 0.12 + Math.random() * 2.4,
      pz: 2.0,
    }));
    this.sparks = [];
    this.ridgeHist = [];
    this.lissajousTrails = [];
    this.radialAngle = 0;
    this.prismPhase = 0;
    this.histAccum = 0;

    // Offscreen scrolling spectrogram canvas
    this.specCanvas = document.createElement("canvas");
    this.specCanvas.width = 480;
    this.specCanvas.height = 180;
    this.specCtx = this.specCanvas.getContext("2d");
  }

  resize() {
    this.dpr = Math.min(2, window.devicePixelRatio || 1);
    const cw = Math.max(300, this.canvas.clientWidth || window.innerWidth);
    const ch = Math.max(200, this.canvas.clientHeight || window.innerHeight);
    this.w = Math.floor(cw * this.dpr);
    this.h = Math.floor(ch * this.dpr);
    this.canvas.width = this.w;
    this.canvas.height = this.h;
    this.chladni.setAspect(this.w, this.h);
  }

  render(modeId, audio, state, dt) {
    const ctx = this.ctx;
    const { w, h, dpr } = this;
    const { theme, showGrid, showPeaks, useGap, gain, autoGain } = state;
    const chrome = getThemeChrome(theme);

    this.prismPhase = (this.prismPhase + dt * (0.14 + 0.32 * audio.beatFlash)) % 1;
    const lut = getThemeLut(theme, 128, audio.beatFlash * 0.22, this.prismPhase);
    const bgCss = rgbCss(chrome.bgRgb);

    this.histAccum += dt;
    const histTicks = Math.min(3, Math.floor(this.histAccum * 60));
    if (histTicks > 0) this.histAccum -= histTicks / 60;

    // 60% Theme-harmonized subtle background gradient
    const bgGrad = ctx.createRadialGradient(w * 0.5, h * 0.45, Math.min(w, h) * 0.05, w * 0.5, h * 0.5, Math.max(w, h) * 0.8);
    bgGrad.addColorStop(0, rgbCss([
      Math.min(255, chrome.bgRgb[0] + 10),
      Math.min(255, chrome.bgRgb[1] + 10),
      Math.min(255, chrome.bgRgb[2] + 14),
    ]));
    bgGrad.addColorStop(1, bgCss);
    ctx.globalCompositeOperation = "source-over";
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, w, h);

    if (showGrid && ["spectrum", "stereo", "wave", "lissajous"].includes(modeId)) {
      ctx.strokeStyle = rgbCss(chrome.gridRgb, 0.42);
      ctx.lineWidth = Math.max(1, dpr);
      ctx.setLineDash([4 * dpr, 6 * dpr]);
      for (const f of [0.25, 0.5, 0.75]) {
        const y = Math.round((1 - f) * h) + 0.5;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }
      ctx.setLineDash([]);
    }

    if (modeId === "spectrum" || modeId === "mirror") {
      this._renderBars(audio.smooth, audio.peaks, lut, chrome, modeId === "mirror", showPeaks, useGap, showGrid, audio._binBounds);
    } else if (modeId === "stereo") {
      this._renderStereo(audio.smoothL, audio.peaksL, audio.smoothR, audio.peaksR, lut, chrome, showPeaks, useGap);
    } else if (modeId === "curve") {
      this._renderCurve(audio.smooth, lut, chrome);
    } else if (modeId === "radial" || modeId === "hybrid") {
      const bass = meanSlice(audio.smooth, 0, Math.max(1, Math.floor(audio.smooth.length / 6)));
      this.radialAngle = (this.radialAngle + dt * (0.35 + audio.beatFlash * 0.65)) % (2 * Math.PI);
      this._renderRadial(audio.smooth, bass, this.radialAngle, lut, chrome, audio.beatFlash);
      if (modeId === "hybrid") {
        if (audio.beatFlash > 0.72 && !audio.silent) this._spawnSparks(22, 0.28, 0.95 + 0.6 * audio.beatFlash);
        this._stepAndDrawSparks(dt, lut, chrome);
        const scopeG = gain * (autoGain ? 1 / Math.max(audio.waveAgc * 0.9, 0.08) : 1);
        this._renderHybridScope(audio.timeL, audio.timeR, scopeG, bass, chrome);
      }
    } else if (modeId === "cymatics" || modeId === "faraday" || modeId === "vortex") {
      let sum = 0, wSum = 0;
      for (let i = 0; i < audio.smooth.length; i++) {
        sum += audio.smooth[i];
        wSum += audio.smooth[i] * (i / Math.max(1, audio.smooth.length - 1));
      }
      const centroid = wSum / (sum + 1e-6);
      const energy = (sum / Math.max(1, audio.smooth.length)) * 1.45;
      this.chladni.step(dt, energy, centroid, audio.beatFlash, performance.now() / 1000, audio.silent, modeId);
      this._renderCymatics(lut, chrome);
    } else if (modeId === "horizon") {
      if (histTicks > 0 || this.ridgeHist.length === 0) {
        for (let t = 0; t < Math.max(1, histTicks); t++) {
          this.ridgeHist.push(new Float32Array(audio.smooth));
          if (this.ridgeHist.length > 22) this.ridgeHist.shift();
        }
      }
      this._renderHorizon(lut, chrome);
    } else if (modeId === "starfield") {
      const bass = meanSlice(audio.smooth, 0, Math.max(1, Math.floor(audio.smooth.length / 6)));
      this._renderStarfield(dt, bass, audio.beatFlash, audio.silent, lut, chrome);
    } else if (modeId === "wave") {
      const waveG = gain * (autoGain ? 1 / audio.waveAgc : 1);
      this._renderWave(audio.timeL, audio.timeR, waveG, lut);
    } else if (modeId === "lissajous") {
      if (histTicks > 0 || this.lissajousTrails.length === 0) {
        const sg = gain * (autoGain ? 1 / Math.max(audio.waveAgc * 0.92, 0.08) : 1);
        const pts = [];
        const len = audio.timeL.length;
        for (let i = len - 240; i < len; i += 2) {
          const l = audio.timeL[i] * sg;
          const r = audio.timeR[i] * sg;
          pts.push([Math.max(-1, Math.min(1, (l - r) * 0.85)), Math.max(-1, Math.min(1, (l + r) * 0.85))]);
        }
        this.lissajousTrails.push(pts);
        if (this.lissajousTrails.length > 8) this.lissajousTrails.shift();
      }
      this._renderLissajous(lut, chrome);
    } else if (modeId === "spectrogram") {
      if (histTicks > 0) this._pushSpectrogram(audio.smooth, lut);
      ctx.drawImage(this.specCanvas, 0, 0, w, h);
    }
  }

  _makeVGrad(x0, y0, x1, y1, lut, shiftFrac = 0) {
    const g = this.ctx.createLinearGradient(x0, y0, x1, y1);
    const n = lut.css.length;
    for (let s = 0; s <= 4; s++) {
      const idx = Math.max(0, Math.min(n - 1, Math.round(((s / 4) + shiftFrac) * (n - 1))));
      g.addColorStop(s / 4, lut.css[idx]);
    }
    return g;
  }

  _renderBars(vals, peaks, lut, chrome, mirror, showPeaks, useGap, showAxis, binBounds) {
    const ctx = this.ctx;
    const { w, h, dpr } = this;
    const n = vals.length;
    const slotW = w / n;
    const gap = useGap && slotW >= 5 * dpr ? Math.max(1.5 * dpr, slotW * 0.2) : 0;
    const peakCss = rgbCss(chrome.accentRgb);
    const bottomPad = showAxis && !mirror ? 24 * dpr : 4 * dpr;

    for (let i = 0; i < n; i++) {
      const bx = i * slotW;
      const bw = Math.max(1.5, slotW - gap);
      const shift = ((i / Math.max(1, n - 1)) - 0.35) * 0.14;
      if (mirror) {
        const cy = h * 0.5;
        const bh = vals[i] * (cy - 12 * dpr);
        if (bh > 0.5) {
          ctx.fillStyle = this._makeVGrad(0, cy - bh, 0, cy + bh, lut, shift);
          ctx.fillRect(bx, cy - bh, bw, bh * 2);
        }
        if (showPeaks && peaks[i] > 0.015) {
          const ph = peaks[i] * (cy - 12 * dpr);
          ctx.fillStyle = peakCss;
          ctx.fillRect(bx, cy - ph - 2 * dpr, bw, 2 * dpr);
          ctx.fillRect(bx, cy + ph, bw, 2 * dpr);
        }
      } else {
        const usableH = h - bottomPad - 8 * dpr;
        const bh = vals[i] * usableH;
        const yTop = h - bottomPad - bh;
        if (bh > 0.5) {
          ctx.fillStyle = this._makeVGrad(0, h - bottomPad, 0, 8 * dpr, lut, shift);
          ctx.fillRect(bx, yTop, bw, bh);
        }
        if (showPeaks && peaks[i] > 0.015) {
          const py = h - bottomPad - peaks[i] * usableH;
          if (py < yTop) {
            ctx.fillStyle = peakCss;
            ctx.fillRect(bx, py - 2 * dpr, bw, 2 * dpr);
          }
        }
      }
    }

    if (showAxis && !mirror && binBounds?.length === n) {
      ctx.fillStyle = rgbCss(chrome.axisRgb, 0.85);
      ctx.font = `${Math.round(11 * dpr)}px ui-monospace, SFMono-Regular, Menlo, monospace`;
      ctx.textBaseline = "bottom";
      let lastX = -40;
      for (const hz of [50, 100, 200, 500, 1000, 2000, 4000, 8000, 14000]) {
        let bestI = 0, bestD = Infinity;
        for (let i = 0; i < n; i++) {
          const d = Math.abs(binBounds[i].centerHz - hz);
          if (d < bestD) { bestD = d; bestI = i; }
        }
        const x = bestI * slotW;
        if (x > lastX + 28 * dpr && x < w - 28 * dpr) {
          const lbl = hz >= 1000 ? `${hz / 1000}k` : `${hz}`;
          ctx.fillText(lbl, x, h - 5 * dpr);
          lastX = x + lbl.length * 7 * dpr;
        }
      }
    }
  }

  _renderStereo(valsL, peaksL, valsR, peaksR, lut, chrome, showPeaks, useGap) {
    const ctx = this.ctx;
    const { w, h, dpr } = this;
    const cx = w * 0.5;
    const n = valsL.length;
    const halfW = cx - 8 * dpr;
    const slotW = halfW / n;
    const gap = useGap && slotW >= 5 * dpr ? Math.max(1.5 * dpr, slotW * 0.2) : 0;
    const peakCss = rgbCss(chrome.accentRgb);

    ctx.fillStyle = rgbCss(chrome.axisRgb, 0.45);
    ctx.fillRect(cx - dpr, 0, 2 * dpr, h);

    for (let i = 0; i < n; i++) {
      const bw = Math.max(1.5, slotW - gap);
      const lx = cx - 6 * dpr - (i + 1) * slotW + gap * 0.5;
      const rx = cx + 6 * dpr + i * slotW;
      const shift = ((i / Math.max(1, n - 1)) - 0.35) * 0.14;
      const grad = this._makeVGrad(0, h - 10 * dpr, 0, 10 * dpr, lut, shift);

      for (const [x, v, pk] of [[lx, valsL[i], peaksL[i]], [rx, valsR[i], peaksR[i]]]) {
        const bh = v * (h - 24 * dpr);
        if (bh > 0.5) {
          ctx.fillStyle = grad;
          ctx.fillRect(x, h - 10 * dpr - bh, bw, bh);
        }
        if (showPeaks && pk > 0.015) {
          const py = h - 10 * dpr - pk * (h - 24 * dpr);
          if (py < h - 10 * dpr - bh) {
            ctx.fillStyle = peakCss;
            ctx.fillRect(x, py - 2 * dpr, bw, 2 * dpr);
          }
        }
      }
    }
  }

  _renderCurve(vals, lut, chrome) {
    const ctx = this.ctx;
    const { w, h, dpr } = this;
    const pts = Math.min(360, Math.floor(w / dpr));
    const up = cubicUpsample(vals, pts, false);
    const stepX = w / (pts - 1);

    ctx.beginPath();
    ctx.moveTo(0, h);
    for (let i = 0; i < pts; i++) {
      ctx.lineTo(i * stepX, (1 - up[i]) * (h * 0.88) + h * 0.06);
    }
    ctx.lineTo(w, h);
    ctx.closePath();

    const grad = ctx.createLinearGradient(0, h, 0, h * 0.06);
    for (let s = 0; s <= 4; s++) {
      const rgb = lut.rgbs[Math.round((s / 4) * (lut.rgbs.length - 1))];
      grad.addColorStop(s / 4, rgbCss(rgb, 0.25 + 0.55 * (s / 4)));
    }
    ctx.fillStyle = grad;
    ctx.fill();

    ctx.beginPath();
    for (let i = 0; i < pts; i++) {
      const x = i * stepX;
      const y = (1 - up[i]) * (h * 0.88) + h * 0.06;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = rgbCss(chrome.accentRgb);
    ctx.lineWidth = 2.2 * dpr;
    ctx.stroke();
  }

  _renderRadial(vals, bass, angleOff, lut, chrome, beatFlash) {
    const ctx = this.ctx;
    const { w, h, dpr } = this;
    const cx = w * 0.5, cy = h * 0.5;
    const maxR = Math.min(cx, cy) * 0.84;
    const baseR = maxR * (0.26 + 0.12 * Math.min(1, bass + 0.2 * beatFlash));
    const sym = new Float32Array(vals.length * 2);
    for (let i = 0; i < vals.length; i++) {
      sym[i] = vals[i];
      sym[sym.length - 1 - i] = vals[i];
    }
    const ring = cubicUpsample(sym, 280, true);
    const nL = lut.css.length;

    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    ctx.lineWidth = 2 * dpr;
    for (let i = 0; i < ring.length; i += 2) {
      const ang = (2 * Math.PI * i) / ring.length + angleOff - Math.PI * 0.5;
      const ca = Math.cos(ang), sa = Math.sin(ang);
      const rEnd = baseR + ring[i] * (maxR - baseR);
      const ci = Math.min(nL - 1, Math.floor(ring[i] * (nL - 1)));
      ctx.strokeStyle = lut.css[ci];
      ctx.beginPath();
      ctx.moveTo(cx + ca * baseR, cy + sa * baseR);
      ctx.lineTo(cx + ca * rEnd, cy + sa * rEnd);
      ctx.stroke();
    }

    ctx.strokeStyle = lut.css[Math.min(nL - 1, 16)];
    ctx.beginPath();
    ctx.arc(cx, cy, baseR, 0, 2 * Math.PI);
    ctx.stroke();

    ctx.strokeStyle = rgbCss(chrome.accentRgb, 0.92);
    ctx.lineWidth = 2.4 * dpr;
    ctx.beginPath();
    for (let i = 0; i <= ring.length; i++) {
      const v = ring[i % ring.length];
      const ang = (2 * Math.PI * (i % ring.length)) / ring.length + angleOff - Math.PI * 0.5;
      const rEnd = baseR + v * (maxR - baseR);
      const px = cx + Math.cos(ang) * rEnd;
      const py = cy + Math.sin(ang) * rEnd;
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }
    ctx.stroke();
    ctx.restore();
  }

  _spawnSparks(count, baseR, speedScale) {
    for (let i = 0; i < count; i++) {
      const ang = Math.random() * 2 * Math.PI;
      const spd = (0.45 + Math.random() * 0.7) * speedScale;
      this.sparks.push({ x: Math.cos(ang) * baseR, y: Math.sin(ang) * baseR, vx: Math.cos(ang) * spd, vy: Math.sin(ang) * spd, life: 1 });
    }
    if (this.sparks.length > 360) this.sparks.splice(0, this.sparks.length - 360);
  }

  _stepAndDrawSparks(dt, lut, chrome) {
    const ctx = this.ctx;
    const { w, h, dpr } = this;
    const cx = w * 0.5, cy = h * 0.5, maxR = Math.min(cx, cy) * 0.84;
    const damp = Math.exp(-dt * 2.2);
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    const alive = [];
    for (const s of this.sparks) {
      s.x += s.vx * dt; s.y += s.vy * dt;
      s.vx *= damp; s.vy *= damp;
      s.life -= dt * 1.35;
      if (s.life <= 0.02) continue;
      alive.push(s);
      const ci = Math.min(lut.rgbs.length - 1, Math.floor(s.life * (lut.rgbs.length - 1)));
      const col = s.life > 0.45 ? chrome.accentRgb : lut.rgbs[ci];
      ctx.fillStyle = rgbCss(col, s.life);
      ctx.fillRect(cx + s.x * maxR, cy + s.y * maxR, 2.5 * dpr, 2.5 * dpr);
    }
    this.sparks = alive;
    ctx.restore();
  }

  _renderHybridScope(timeL, timeR, scopeG, bass, chrome) {
    const ctx = this.ctx;
    const { w, h, dpr } = this;
    const cx = w * 0.5, cy = h * 0.5;
    const baseR = Math.min(cx, cy) * 0.84 * (0.24 + 0.10 * Math.min(1, bass));
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    ctx.strokeStyle = rgbCss(chrome.accentRgb, 0.85);
    ctx.lineWidth = 1.6 * dpr;
    ctx.beginPath();
    const len = timeL.length;
    for (let i = len - 200; i < len; i += 2) {
      const l = timeL[i] * scopeG * 1.4;
      const r = timeR[i] * scopeG * 1.4;
      const x = cx + Math.max(-1, Math.min(1, (l - r) * 0.72)) * baseR * 0.85;
      const y = cy - Math.max(-1, Math.min(1, (l + r) * 0.72)) * baseR * 0.85;
      if (i === len - 200) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.restore();
  }

  _renderCymatics(lut, chrome) {
    const ctx = this.ctx;
    const { w, h, dpr } = this;
    const s = this.chladni;
    const nL = lut.rgbs.length;
    const gSize = Math.max(1.5, 2.0 * dpr);

    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    for (let i = 0; i < s.n; i++) {
      const px = ((s.x[i] / s.xMax + 1) * 0.5) * w;
      const py = ((s.y[i] / s.yMax + 1) * 0.5) * h;
      const e = s.energy[i];
      const ci = Math.min(nL - 1, Math.floor((0.18 + e * 0.78) * (nL - 1)));
      const rgb = e > 0.62 ? chrome.accentRgb : lut.rgbs[ci];
      ctx.fillStyle = rgbCss(rgb, 0.35 + e * 0.55);
      ctx.fillRect(px, py, gSize, gSize);
    }
    ctx.restore();
  }

  _renderHorizon(lut, chrome) {
    const ctx = this.ctx;
    const { w, h, dpr } = this;
    const hist = this.ridgeHist;
    const nLayers = hist.length;
    if (!nLayers) return;
    const nL = lut.rgbs.length;
    const pts = 160;
    const stepX = w / (pts - 1);
    const ampPx = h * 0.32;
    const baseTop = h * 0.22;
    const baseSpan = h * 0.70;

    // Back-to-front painter's order so foreground layers naturally occlude distant ridges
    for (let li = 0; li < nLayers; li++) {
      const spec = hist[li];
      const depthT = 1 - li / Math.max(1, nLayers - 1); // 1 = far/back, 0 = front
      const baseY = baseTop + (1 - depthT) * baseSpan;
      const up = cubicUpsample(spec, pts, false);
      const baseRgb = lut.rgbs[Math.min(nL - 1, Math.floor((1 - depthT) * (nL - 1)))];
      const hazeW = depthT * 0.58;
      const rgb = [
        Math.round(baseRgb[0] * (1 - hazeW) + chrome.gridRgb[0] * hazeW),
        Math.round(baseRgb[1] * (1 - hazeW) + chrome.gridRgb[1] * hazeW),
        Math.round(baseRgb[2] * (1 - hazeW) + chrome.gridRgb[2] * hazeW),
      ];

      ctx.beginPath();
      ctx.moveTo(0, h);
      for (let i = 0; i < pts; i++) {
        const edge = Math.pow(Math.max(0, Math.sin(Math.PI * (i / (pts - 1)))), 0.45);
        ctx.lineTo(i * stepX, baseY - up[i] * ampPx * edge);
      }
      ctx.lineTo(w, h);
      ctx.closePath();
      ctx.fillStyle = rgbCss(chrome.bgRgb, 0.94);
      ctx.fill();

      ctx.beginPath();
      for (let i = 0; i < pts; i++) {
        const edge = Math.pow(Math.max(0, Math.sin(Math.PI * (i / (pts - 1)))), 0.45);
        const y = baseY - up[i] * ampPx * edge;
        if (i === 0) ctx.moveTo(i * stepX, y); else ctx.lineTo(i * stepX, y);
      }
      ctx.strokeStyle = rgbCss(rgb, 1 - depthT * 0.48);
      ctx.lineWidth = (2.1 - depthT * 0.9) * dpr;
      ctx.stroke();
    }
  }

  _renderStarfield(dt, bass, beatFlash, silent, lut, chrome) {
    const ctx = this.ctx;
    const { w, h, dpr } = this;
    const cx = w * 0.5, cy = h * 0.5, scale = Math.min(cx, cy) * 0.85;
    const spd = silent ? 0.25 : (0.65 + 2.4 * Math.min(1.5, bass) + 2.2 * beatFlash);
    const nL = lut.rgbs.length;

    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    ctx.lineWidth = (beatFlash > 0.4 ? 2.2 : 1.4) * dpr;
    for (const s of this.stars) {
      s.pz = s.z;
      s.z -= spd * dt;
      if (s.z <= 0.08) {
        s.x = (Math.random() * 2 - 1) * 1.6;
        s.y = (Math.random() * 2 - 1) * 1.1;
        s.z = 1.8 + Math.random() * 0.8;
        s.pz = s.z;
      }
      const depth = Math.max(0, Math.min(1, 1 - s.z / 2.6));
      const x0 = cx + (s.x / s.pz) * scale;
      const y0 = cy + (s.y / s.pz) * scale;
      const x1 = cx + (s.x / s.z) * scale;
      const y1 = cy + (s.y / s.z) * scale;
      const ci = Math.min(nL - 1, Math.floor((depth * 0.85 + beatFlash * 0.25) * (nL - 1)));
      const rgb = (depth > 0.72 || beatFlash > 0.5) ? chrome.accentRgb : lut.rgbs[ci];
      ctx.strokeStyle = rgbCss(rgb, 0.35 + 0.65 * depth);
      ctx.beginPath();
      ctx.moveTo(x0, y0);
      ctx.lineTo(x1, y1);
      ctx.stroke();
    }
    ctx.restore();
  }

  _renderWave(timeL, timeR, gain, lut) {
    const ctx = this.ctx;
    const { w, h, dpr } = this;
    const len = timeL.length;
    const searchEnd = Math.min(len - 1024, 1600);
    let armed = false, trig = 0;
    for (let i = 1; i < searchEnd; i++) {
      const cur = 0.5 * (timeL[i] + timeR[i]);
      const prev = 0.5 * (timeL[i - 1] + timeR[i - 1]);
      if (cur <= -0.01) armed = true;
      else if (armed && prev < 0 && cur >= 0) {
        trig = i;
        break;
      }
    }

    const span = Math.min(len - trig - 2, 1400);
    if (span < 8) return;
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    ctx.lineWidth = 2.2 * dpr;
    const nL = lut.css.length;
    for (const [sig, cy, frac] of [[timeL, h * 0.28, 0.28], [timeR, h * 0.72, 0.72]]) {
      ctx.strokeStyle = lut.css[Math.min(nL - 1, Math.floor(frac * (nL - 1)))];
      ctx.beginPath();
      for (let px = 0; px < 320; px++) {
        const idx = trig + Math.floor((px / 319) * span);
        const v = Math.max(-1, Math.min(1, sig[idx] * gain * 1.5));
        const x = (px / 319) * w;
        const y = cy - v * (h * 0.21);
        if (px === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    ctx.restore();
  }

  _renderLissajous(lut, chrome) {
    const ctx = this.ctx;
    const { w, h, dpr } = this;
    const cx = w * 0.5, cy = h * 0.5, scale = Math.min(cx, cy) * 0.85;
    const nL = lut.rgbs.length;
    const nt = this.lissajousTrails.length;
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    for (let ai = 0; ai < nt; ai++) {
      const pts = this.lissajousTrails[ai];
      const frac = (ai + 1) / Math.max(1, nt);
      const rgb = ai === nt - 1 ? chrome.accentRgb : lut.rgbs[Math.min(nL - 1, Math.floor(frac * (nL - 1)))];
      ctx.strokeStyle = rgbCss(rgb, 0.25 + 0.75 * frac);
      ctx.lineWidth = (ai === nt - 1 ? 2.4 : 1.3) * dpr;
      ctx.beginPath();
      for (let i = 0; i < pts.length; i++) {
        const x = cx + pts[i][0] * scale;
        const y = cy - pts[i][1] * scale;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    ctx.restore();
  }

  _pushSpectrogram(vals, lut) {
    const sw = this.specCanvas.width, sh = this.specCanvas.height;
    const sc = this.specCtx;
    sc.drawImage(this.specCanvas, 1, 0, sw - 1, sh, 0, 0, sw - 1, sh);
    sc.clearRect(sw - 1, 0, 1, sh);
    const nL = lut.css.length;
    const up = cubicUpsample(vals, sh, false);
    for (let y = 0; y < sh; y++) {
      const v = up[sh - 1 - y];
      if (v > 0.03) {
        sc.fillStyle = lut.css[Math.min(nL - 1, Math.floor(v * (nL - 1)))];
        sc.fillRect(sw - 1, y, 1, 1);
      }
    }
  }
}

function meanSlice(arr, start, end) {
  let s = 0;
  for (let i = start; i < end; i++) s += arr[i];
  return s / Math.max(1, end - start);
}
