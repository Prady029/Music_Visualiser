/**
 * Web Audio Capture & Stereo DSP Engine
 * Sources:
 *  - System / Tab Speaker Audio via getDisplayMedia (stops dummy video track immediately)
 *  - Microphone / Virtual Loopback (e.g., BlackHole) via raw getUserMedia
 *  - Local audio file playback (.mp3, .wav, .flac, .ogg, .m4a)
 *  - Built-in 126 BPM stereo synthesizer (zero setup)
 */

export const SMOOTH_PRESETS = {
  snappy: { tauUp: 0.012, tauDn: 0.055, spatial: 0.15, gravity: 1.80, hold: 0.16 },
  smooth: { tauUp: 0.022, tauDn: 0.105, spatial: 0.35, gravity: 1.25, hold: 0.22 },
  silky:  { tauUp: 0.036, tauDn: 0.160, spatial: 0.55, gravity: 0.90, hold: 0.28 },
  liquid: { tauUp: 0.055, tauDn: 0.240, spatial: 0.75, gravity: 0.65, hold: 0.34 },
};

export class AudioEngine {
  constructor() {
    this.ctx = null;
    this.analyserL = null;
    this.analyserR = null;
    this.analyserM = null;
    this.splitter = null;
    this.merger = null;
    this.sourceNode = null;
    this.activeStream = null;
    this.audioEl = null;
    this.audioElUrl = null;
    this.demoTimer = null;
    this.demoGain = null;
    this.demoMuted = false;

    this.sourceType = "none";
    this.sourceLabel = "Idle";
    this.fftSize = 4096;

    // Analysis buffers
    this.freqFloatM = null;
    this.freqFloatL = null;
    this.freqFloatR = null;
    this.timeL = new Float32Array(this.fftSize);
    this.timeR = new Float32Array(this.fftSize);

    this._cachedBars = 0;
    this._cachedRate = 0;
    this._binBounds = [];
    this.smooth = new Float32Array(64);
    this.peaks = new Float32Array(64);
    this.peakVel = new Float32Array(64);
    this.peakHold = new Float32Array(64);
    this.smoothL = new Float32Array(64);
    this.smoothR = new Float32Array(64);
    this.peaksL = new Float32Array(64);
    this.peaksR = new Float32Array(64);
    this.velL = new Float32Array(64);
    this.velR = new Float32Array(64);
    this.holdL = new Float32Array(64);
    this.holdR = new Float32Array(64);

    this.agcScale = 0.35;
    this.waveAgc = 0.25;
    this.prevBassMag = null;
    this.fluxHist = [];
    this.beatTimes = [];
    this.lastBeatT = 0;
    this.beatFlash = 0;
    this.bpm = 0;
    this.rmsL = 0;
    this.rmsR = 0;
    this.rms = 0;
    this.db = -60;
    this.silent = true;
    this.onEnded = null;
  }

  _ensureContext() {
    if (!this.ctx) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AudioCtx();
      this.analyserM = this.ctx.createAnalyser();
      this.analyserL = this.ctx.createAnalyser();
      this.analyserR = this.ctx.createAnalyser();
      for (const an of [this.analyserM, this.analyserL, this.analyserR]) {
        an.fftSize = this.fftSize;
        an.smoothingTimeConstant = 0; // We apply our own frame-rate-independent smoothing
      }
      this.splitter = this.ctx.createChannelSplitter(2);
      this.splitter.connect(this.analyserL, 0);
      this.splitter.connect(this.analyserR, 1);

      const nBins = this.analyserM.frequencyBinCount;
      this.freqFloatM = new Float32Array(nBins);
      this.freqFloatL = new Float32Array(nBins);
      this.freqFloatR = new Float32Array(nBins);
      this.timeL = new Float32Array(this.fftSize);
      this.timeR = new Float32Array(this.fftSize);
    }
    if (this.ctx.state === "suspended") {
      return this.ctx.resume();
    }
    return Promise.resolve();
  }

  resumeContext() {
    if (this.ctx && this.ctx.state === "suspended") {
      this.ctx.resume().catch(() => {});
    }
  }

  stop() {
    if (this.demoTimer) {
      clearInterval(this.demoTimer);
      this.demoTimer = null;
    }
    if (this.demoGain) {
      this.demoGain.disconnect();
      this.demoGain = null;
    }
    if (this.sourceNode) {
      try { this.sourceNode.disconnect(); } catch {}
      this.sourceNode = null;
    }
    if (this.activeStream) {
      for (const tr of this.activeStream.getTracks()) tr.stop();
      this.activeStream = null;
    }
    if (this.audioEl) {
      this.audioEl.pause();
      this.audioEl.src = "";
      this.audioEl = null;
    }
    if (this.audioElUrl) {
      URL.revokeObjectURL(this.audioElUrl);
      this.audioElUrl = null;
    }
    this.sourceType = "none";
    this.sourceLabel = "Stopped";
  }

  async startSpeakerCapture() {
    const isMobile = /Android|iPhone|iPad|iPod|webOS|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) ||
      (navigator.maxTouchPoints > 1 && window.innerWidth <= 1024);
    if (!navigator.mediaDevices?.getDisplayMedia || isMobile) {
      if (isMobile) {
        throw new Error("Mobile operating systems (iOS & Android) do not allow web browsers to capture internal speaker output. Use Mic or choose an Audio File.");
      }
      throw new Error("Screen/Speaker capture (getDisplayMedia) is not supported in this browser. Try desktop Chrome, Edge, or Brave.");
    }
    await this._ensureContext();

    // Browsers require a minimal video track request to prompt for tab/system audio; we drop video immediately after.
    const rawStream = await navigator.mediaDevices.getDisplayMedia({
      video: { width: 1, height: 1, frameRate: 1 },
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
        suppressLocalAudioPlayback: false,
      },
      systemAudio: "include",
    });

    const audioTracks = rawStream.getAudioTracks();
    for (const vt of rawStream.getVideoTracks()) {
      vt.stop();
    }
    if (!audioTracks.length) {
      throw new Error("No audio track was shared. Re-try and enable 'Share system audio' or 'Share tab audio'.");
    }

    this.stop();
    const audioStream = new MediaStream(audioTracks);
    this.activeStream = audioStream;
    audioTracks[0].onended = () => {
      if (this.sourceType === "speaker") {
        this.stop();
        this.sourceLabel = "Capture Ended";
        this.onEnded?.();
      }
    };

    const src = this.ctx.createMediaStreamSource(audioStream);
    src.connect(this.analyserM);
    src.connect(this.splitter);
    // Do NOT connect live capture to ctx.destination to avoid feedback loops.
    this.sourceNode = src;
    this.sourceType = "speaker";
    this.sourceLabel = audioTracks[0].label ? `Speaker: ${audioTracks[0].label}` : "Speaker Output (Live)";
  }

  async startMicCapture(deviceId = "") {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Audio input capture (getUserMedia) is unavailable in this browser context.");
    }
    await this._ensureContext();
    const constraints = {
      audio: {
        deviceId: deviceId ? { exact: deviceId } : undefined,
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
    };
    const stream = await navigator.mediaDevices.getUserMedia(constraints);
    this.stop();
    this.activeStream = stream;
    const track = stream.getAudioTracks()[0];
    const src = this.ctx.createMediaStreamSource(stream);
    src.connect(this.analyserM);
    src.connect(this.splitter);
    this.sourceNode = src;
    this.sourceType = "mic";
    this.sourceLabel = track?.label ? `Input: ${track.label}` : "Mic / Loopback Input";
  }

  async startFile(file) {
    await this._ensureContext();
    this.stop();
    const el = new Audio();
    const url = URL.createObjectURL(file);
    el.src = url;
    el.loop = true;
    el.crossOrigin = "anonymous";
    const src = this.ctx.createMediaElementSource(el);
    src.connect(this.analyserM);
    src.connect(this.splitter);
    src.connect(this.ctx.destination);
    await el.play();

    this.audioEl = el;
    this.audioElUrl = url;
    this.sourceNode = src;
    this.sourceType = "file";
    this.sourceLabel = `File: ${file.name}`;
  }

  async startDemo(audible = true) {
    await this._ensureContext();
    this.stop();
    const ctx = this.ctx;
    const mix = ctx.createGain();
    mix.gain.value = 0.85;
    mix.connect(this.analyserM);
    mix.connect(this.splitter);

    const spk = ctx.createGain();
    this.demoMuted = !audible;
    spk.gain.value = audible ? 0.45 : 0.0;
    mix.connect(spk);
    spk.connect(ctx.destination);

    this.sourceNode = mix;
    this.demoGain = spk;
    this.sourceType = "demo";
    this.sourceLabel = "Demo Synth (126 BPM)";

    const stepSec = 60 / 126 / 4; // 16th-note step (~119 ms)
    let stepIdx = 0;
    let nextTime = ctx.currentTime + 0.03;
    const bassNotes = [55.0, 55.0, 65.41, 73.42, 55.0, 55.0, 82.41, 73.42];
    const arpNotes = [220.0, 261.63, 329.63, 440.0, 523.25, 440.0, 329.63, 392.0];

    // Precomputed 0.25s noise buffer for snare & hi-hat
    const nBuf = ctx.createBuffer(1, Math.floor(ctx.sampleRate * 0.25), ctx.sampleRate);
    const nd = nBuf.getChannelData(0);
    for (let i = 0; i < nd.length; i++) nd[i] = Math.random() * 2 - 1;

    const scheduleStep = (t, s) => {
      if (s % 4 === 0) {
        // Punchy kick drum
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = "sine";
        osc.frequency.setValueAtTime(145, t);
        osc.frequency.exponentialRampToValueAtTime(44, t + 0.09);
        g.gain.setValueAtTime(0.95, t);
        g.gain.exponentialRampToValueAtTime(0.001, t + 0.24);
        osc.connect(g).connect(mix);
        osc.start(t);
        osc.stop(t + 0.25);
      }
      if (s % 4 === 2) {
        // Snare on offbeat
        const ns = ctx.createBufferSource();
        ns.buffer = nBuf;
        const bp = ctx.createBiquadFilter();
        bp.type = "bandpass";
        bp.frequency.setValueAtTime(1900, t);
        const g = ctx.createGain();
        g.gain.setValueAtTime(0.32, t);
        g.gain.exponentialRampToValueAtTime(0.001, t + 0.14);
        ns.connect(bp).connect(g).connect(mix);
        ns.start(t);
      }
      // Crisp 16th hi-hat
      const hs = ctx.createBufferSource();
      hs.buffer = nBuf;
      const hp = ctx.createBiquadFilter();
      hp.type = "highpass";
      hp.frequency.setValueAtTime(6800, t);
      const hg = ctx.createGain();
      hg.gain.setValueAtTime(s % 2 === 1 ? 0.14 : 0.07, t);
      hg.gain.exponentialRampToValueAtTime(0.001, t + 0.045);
      hs.connect(hp).connect(hg).connect(mix);
      hs.start(t);

      if (s % 4 === 0) {
        const bf = bassNotes[Math.floor(s / 4) % bassNotes.length];
        const bOsc = ctx.createOscillator();
        const lp = ctx.createBiquadFilter();
        const bg = ctx.createGain();
        bOsc.type = "sawtooth";
        bOsc.frequency.setValueAtTime(bf, t);
        lp.type = "lowpass";
        lp.frequency.setValueAtTime(340, t);
        bg.gain.setValueAtTime(0.28, t);
        bg.gain.exponentialRampToValueAtTime(0.02, t + stepSec * 3.8);
        bOsc.connect(lp).connect(bg).connect(mix);
        bOsc.start(t);
        bOsc.stop(t + stepSec * 4);
      }

      // Stereo-panned synth arpeggio
      const af = arpNotes[s % arpNotes.length];
      const aOsc = ctx.createOscillator();
      const pan = ctx.createStereoPanner();
      const ag = ctx.createGain();
      aOsc.type = "triangle";
      aOsc.frequency.setValueAtTime(af, t);
      pan.pan.setValueAtTime(Math.sin(s * 0.45) * 0.72, t);
      ag.gain.setValueAtTime(0.22, t);
      ag.gain.exponentialRampToValueAtTime(0.002, t + stepSec * 0.9);
      aOsc.connect(pan).connect(ag).connect(mix);
      aOsc.start(t);
      aOsc.stop(t + stepSec);
    };

    this.demoTimer = setInterval(() => {
      if (!this.ctx || this.sourceType !== "demo") return;
      while (nextTime < this.ctx.currentTime + 0.12) {
        scheduleStep(nextTime, stepIdx++);
        nextTime += stepSec;
      }
    }, 25);
  }

  setDemoAudible(audible) {
    this.demoMuted = !audible;
    if (this.demoGain && this.ctx) {
      this.demoGain.gain.setTargetAtTime(audible ? 0.45 : 0.0, this.ctx.currentTime, 0.02);
    }
  }

  async listInputs() {
    if (!navigator.mediaDevices?.enumerateDevices) return [];
    const devs = await navigator.mediaDevices.enumerateDevices();
    return devs.filter((d) => d.kind === "audioinput");
  }

  _configureBands(numBars) {
    const sr = this.ctx ? this.ctx.sampleRate : 48000;
    if (this._cachedBars === numBars && this._cachedRate === sr) return;
    this._cachedBars = numBars;
    this._cachedRate = sr;

    const nyq = sr * 0.5;
    const fHi = Math.min(16500, nyq * 0.95);
    const fLo = Math.min(40, fHi * 0.25);
    const nBins = this.fftSize / 2;
    const hzPerBin = sr / this.fftSize;

    this._binBounds = [];
    for (let i = 0; i < numBars; i++) {
      const f0 = fLo * Math.pow(fHi / fLo, i / numBars);
      const f1 = fLo * Math.pow(fHi / fLo, (i + 1) / numBars);
      const fc = Math.sqrt(f0 * f1);
      const pos0 = Math.max(1, Math.min(f0 / hzPerBin, nBins - 1.001));
      const pos1 = Math.max(pos0, Math.min(f1 / hzPerBin, nBins - 0.001));
      const weight = Math.pow(fc / 380, 0.34);
      this._binBounds.push({ pos0, pos1, weight, centerHz: fc });
    }

    const alloc = () => new Float32Array(numBars);
    this.smooth = alloc(); this.peaks = alloc(); this.peakVel = alloc(); this.peakHold = alloc();
    this.smoothL = alloc(); this.smoothR = alloc();
    this.peaksL = alloc(); this.peaksR = alloc();
    this.velL = alloc(); this.velR = alloc();
    this.holdL = alloc(); this.holdR = alloc();
  }

  _computeSpectrum(dbBins, gain) {
    const n = this._binBounds.length;
    const out = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const { pos0, pos1, weight } = this._binBounds[i];
      const b0 = Math.floor(pos0);
      const b1 = Math.ceil(pos1);
      let rawLin = 0;
      if (b1 <= b0 + 1) {
        const center = 0.5 * (pos0 + pos1);
        const lo = Math.max(0, Math.min(dbBins.length - 2, Math.floor(center)));
        const frac = center - lo;
        const m0 = Math.pow(10, Math.max(-120, dbBins[lo]) / 20);
        const m1 = Math.pow(10, Math.max(-120, dbBins[lo + 1]) / 20);
        rawLin = m0 * (1 - frac) + m1 * frac;
      } else {
        let sumSq = 0;
        const end = Math.min(b1, dbBins.length);
        for (let b = b0; b < end; b++) {
          const lin = Math.pow(10, Math.max(-120, dbBins[b]) / 20);
          sumSq += lin * lin;
        }
        rawLin = Math.sqrt(sumSq / Math.max(1, end - b0));
      }
      out[i] = Math.log1p(rawLin * weight * 48 * gain);
    }
    return out;
  }

  _spatialSmooth(arr, strength) {
    const n = arr.length;
    if (strength <= 0 || n < 5) return arr;
    const out = new Float32Array(n);
    const k = [0.08, 0.22, 0.40, 0.22, 0.08];
    for (let i = 0; i < n; i++) {
      let s = 0;
      for (let j = -2; j <= 2; j++) {
        const idx = Math.max(0, Math.min(n - 1, i + j));
        s += arr[idx] * k[j + 2];
      }
      out[i] = (1 - strength) * arr[i] + strength * s;
    }
    return out;
  }

  _advancePeaks(vals, peaks, vel, hold, dt, gravity, holdSec) {
    for (let i = 0; i < vals.length; i++) {
      if (vals[i] >= peaks[i]) {
        peaks[i] = vals[i];
        vel[i] = 0;
        hold[i] = holdSec;
      } else {
        vel[i] += dt * gravity;
        hold[i] -= dt;
        if (hold[i] <= 0) {
          peaks[i] = Math.max(0, peaks[i] - vel[i] * dt);
        }
      }
    }
  }

  update(numBars, dt, now, presetName, gain, autoGain) {
    this._configureBands(numBars);
    const sp = SMOOTH_PRESETS[presetName] || SMOOTH_PRESETS.smooth;
    const aUp = 1 - Math.exp(-dt / sp.tauUp);
    const aDn = 1 - Math.exp(-dt / sp.tauDn);

    if (!this.ctx || this.sourceType === "none") {
      this.silent = true;
      this.rms = this.rmsL = this.rmsR = 0;
      this.db = -60;
      this.beatFlash = Math.max(0, this.beatFlash - dt * 4.5);
      for (let i = 0; i < numBars; i++) {
        this.smooth[i] += aDn * -this.smooth[i];
        this.smoothL[i] += aDn * -this.smoothL[i];
        this.smoothR[i] += aDn * -this.smoothR[i];
      }
      this._advancePeaks(this.smooth, this.peaks, this.peakVel, this.peakHold, dt, sp.gravity, sp.hold);
      return;
    }

    this.analyserM.getFloatFrequencyData(this.freqFloatM);
    this.analyserL.getFloatFrequencyData(this.freqFloatL);
    this.analyserR.getFloatFrequencyData(this.freqFloatR);
    this.analyserL.getFloatTimeDomainData(this.timeL);
    this.analyserR.getFloatTimeDomainData(this.timeR);

    let sl = 0;
    let sr = 0;
    const tN = 1024;
    const off = this.timeL.length - tN;
    for (let i = 0; i < tN; i++) {
      const vl = this.timeL[off + i];
      const vr = this.timeR[off + i];
      sl += vl * vl;
      sr += vr * vr;
    }
    this.rmsL = Math.sqrt(sl / tN);
    this.rmsR = Math.sqrt(sr / tN);
    this.rms = 0.5 * (this.rmsL + this.rmsR);
    this.db = 20 * Math.log10(Math.max(this.rms, 1e-5));
    this.silent = this.rms < 1e-4;

    if (!this.silent) {
      const waveT = Math.max(0.08, this.rms * 2.8);
      this.waveAgc += (1 - Math.exp(-dt / (waveT > this.waveAgc ? 0.12 : 1.6))) * (waveT - this.waveAgc);
    }

    // Fixed 40..150 Hz spectral flux onset + BPM tracking
    this.beatFlash = Math.max(0, this.beatFlash - dt * 4.5);
    const hzPerBin = this.ctx.sampleRate / this.fftSize;
    const loB = Math.max(1, Math.floor(40 / hzPerBin));
    const hiB = Math.min(this.freqFloatM.length - 1, Math.max(4, Math.ceil(150 / hzPerBin)));
    let flux = 0;
    const curBass = new Float32Array(hiB - loB + 1);
    for (let b = loB; b <= hiB; b++) {
      const mag = Math.pow(10, Math.max(-120, this.freqFloatM[b]) / 20);
      curBass[b - loB] = mag;
      if (this.prevBassMag && !this.silent) {
        flux += Math.max(0, mag - this.prevBassMag[b - loB]);
      }
    }
    this.prevBassMag = curBass;

    this.fluxHist.push([now, flux]);
    while (this.fluxHist.length && this.fluxHist[0][0] < now - 1.5) {
      this.fluxHist.shift();
    }
    if (!this.silent && this.fluxHist.length >= 15) {
      let sum = 0;
      for (const [, v] of this.fluxHist) sum += v;
      const mean = sum / this.fluxHist.length;
      let vSum = 0;
      for (const [, v] of this.fluxHist) vSum += (v - mean) * (v - mean);
      const std = Math.sqrt(vSum / this.fluxHist.length);
      if (flux > Math.max(mean * 1.65, mean + 1.55 * std) && now - this.lastBeatT > 0.24) {
        if (this.lastBeatT > 0) {
          const interval = now - this.lastBeatT;
          if (interval >= 0.28 && interval <= 1.5) {
            this.beatTimes.push(interval);
            if (this.beatTimes.length > 12) this.beatTimes.shift();
            if (this.beatTimes.length >= 3) {
              const sorted = [...this.beatTimes].sort((a, b) => a - b);
              this.bpm = 60 / sorted[Math.floor(sorted.length / 2)];
            }
          }
        }
        this.lastBeatT = now;
        this.beatFlash = 1.0;
      }
    }

    const rawM = this.silent ? new Float32Array(numBars) : this._computeSpectrum(this.freqFloatM, gain);
    const rawL = this.silent ? new Float32Array(numBars) : this._computeSpectrum(this.freqFloatL, gain);
    const rawR = this.silent ? new Float32Array(numBars) : this._computeSpectrum(this.freqFloatR, gain);

    if (autoGain && !this.silent) {
      const sorted = Float32Array.from(rawM).sort();
      const target = Math.max(0.08, sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.96))]);
      const alpha = 1 - Math.exp(-dt / (target > this.agcScale ? 0.09 : 2.4));
      this.agcScale = Math.max(0.08, this.agcScale + alpha * (target - this.agcScale));
    }
    const div = autoGain ? this.agcScale : 1.5;

    const normM = new Float32Array(numBars);
    const normL = new Float32Array(numBars);
    const normR = new Float32Array(numBars);
    for (let i = 0; i < numBars; i++) {
      normM[i] = Math.min(1, Math.max(0, rawM[i] / div));
      normL[i] = Math.min(1, Math.max(0, rawL[i] / div));
      normR[i] = Math.min(1, Math.max(0, rawR[i] / div));
    }

    const smT = this._spatialSmooth(normM, sp.spatial);
    const smL = this._spatialSmooth(normL, sp.spatial);
    const smR = this._spatialSmooth(normR, sp.spatial);

    for (let i = 0; i < numBars; i++) {
      this.smooth[i] += (smT[i] > this.smooth[i] ? aUp : aDn) * (smT[i] - this.smooth[i]);
      this.smoothL[i] += (smL[i] > this.smoothL[i] ? aUp : aDn) * (smL[i] - this.smoothL[i]);
      this.smoothR[i] += (smR[i] > this.smoothR[i] ? aUp : aDn) * (smR[i] - this.smoothR[i]);
    }
    this._advancePeaks(this.smooth, this.peaks, this.peakVel, this.peakHold, dt, sp.gravity, sp.hold);
    this._advancePeaks(this.smoothL, this.peaksL, this.velL, this.holdL, dt, sp.gravity, sp.hold);
    this._advancePeaks(this.smoothR, this.peaksR, this.velR, this.holdR, dt, sp.gravity, sp.hold);
  }
}
