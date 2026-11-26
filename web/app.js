import { AudioEngine } from "./audio.js";
import { WEB_MODES, VisualizerRenderer } from "./modes.js";
import { THEMES, getThemeChrome, rgbCss } from "./themes.js";

const canvas = document.getElementById("viz-canvas");
const renderer = new VisualizerRenderer(canvas);
const audio = new AudioEngine();

const state = {
  modeIdx: 0,
  theme: "vermilion-teal",
  smoothness: "smooth",
  gain: 1.0,
  autoGain: true,
  showPeaks: true,
  useGap: true,
  showGrid: true,
  hudHidden: false,
  settingsOpen: false,
};

const elWelcome = document.getElementById("welcome");
const elHud = document.getElementById("hud");
const elToast = document.getElementById("toast");
const elBeatDot = document.getElementById("beat-dot");
const elSource = document.getElementById("stat-source");
const elTelemetry = document.getElementById("stat-telemetry");
const elFps = document.getElementById("stat-fps");
const elPopover = document.getElementById("popover-settings");
const selMode = document.getElementById("sel-mode");
const selTheme = document.getElementById("sel-theme");
const selSmooth = document.getElementById("sel-smooth");
const selInput = document.getElementById("sel-input");
const rngGain = document.getElementById("rng-gain");
const lblGain = document.getElementById("lbl-gain");
const btnSpeaker = document.getElementById("btn-speaker");
const btnMic = document.getElementById("btn-mic");
const btnDemo = document.getElementById("btn-demo");
const btnMuteDemo = document.getElementById("btn-mute-demo");
const btnAgc = document.getElementById("btn-autogain");
const btnPeaks = document.getElementById("btn-peaks");
const btnGrid = document.getElementById("btn-grid");
const btnSettings = document.getElementById("btn-settings");

let toastTimer = null;
let idleTimer = null;

function showToast(msg, ms = 2000) {
  elToast.textContent = msg;
  elToast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => elToast.classList.remove("visible"), ms);
}

function resetIdleFade() {
  elHud.classList.remove("idle");
  clearTimeout(idleTimer);
  if (audio.sourceType !== "none" && !state.settingsOpen) {
    idleTimer = setTimeout(() => {
      if (audio.sourceType !== "none" && !state.settingsOpen) {
        elHud.classList.add("idle");
      }
    }, 3500);
  }
}

function setSettingsOpen(open) {
  state.settingsOpen = open;
  elPopover.classList.toggle("open", open);
  elPopover.setAttribute("aria-hidden", String(!open));
  btnSettings.classList.toggle("active", open);
  resetIdleFade();
}

function setModeIndex(idx) {
  state.modeIdx = (idx + WEB_MODES.length) % WEB_MODES.length;
  selMode.value = String(state.modeIdx);
  showToast(`Mode: ${WEB_MODES[state.modeIdx].label}`);
}

function applyThemeCss(theme) {
  const chrome = getThemeChrome(theme);
  const root = document.documentElement.style;
  root.setProperty("--bg", rgbCss(chrome.bgRgb));
  root.setProperty("--surface", rgbCss(chrome.bgRgb, 0.58));
  root.setProperty("--border", rgbCss(chrome.axisRgb, 0.24));
  root.setProperty("--accent", rgbCss(chrome.accentRgb));
}

function populateSelects() {
  WEB_MODES.forEach((m, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = `${i + 1}. ${m.label}`;
    selMode.appendChild(opt);
  });
  THEMES.forEach((t) => {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = t;
    selTheme.appendChild(opt);
  });
  selTheme.value = state.theme;
  applyThemeCss(state.theme);
}

async function refreshDevices() {
  const devs = await audio.listInputs();
  selInput.innerHTML = "";
  const def = document.createElement("option");
  def.value = "";
  def.textContent = "Default Input";
  selInput.appendChild(def);
  for (const d of devs) {
    const opt = document.createElement("option");
    opt.value = d.deviceId;
    opt.textContent = d.label || `Input ${selInput.length}`;
    selInput.appendChild(opt);
  }
}

function updateSourceButtons() {
  btnSpeaker.classList.toggle("active", audio.sourceType === "speaker");
  btnMic.classList.toggle("active", audio.sourceType === "mic");
  btnDemo.classList.toggle("active", audio.sourceType === "demo");
  btnMuteDemo.style.display = audio.sourceType === "demo" ? "inline-block" : "none";
  if (audio.sourceType !== "none") elWelcome.classList.add("hidden");
  elSource.textContent = audio.sourceLabel;
  resetIdleFade();
}

async function handleSpeaker() {
  try {
    await audio.startSpeakerCapture();
    updateSourceButtons();
    showToast("Capturing live speaker / tab audio");
  } catch (err) {
    showToast(err.message || "Speaker capture cancelled", 4200);
  }
}

async function handleMic() {
  try {
    await audio.startMicCapture(selInput.value);
    await refreshDevices();
    updateSourceButtons();
    showToast("Capturing microphone / loopback audio");
  } catch (err) {
    showToast(err.message || "Microphone access denied", 4200);
  }
}

async function handleDemo() {
  try {
    await audio.startDemo(true);
    btnMuteDemo.textContent = "🔊";
    updateSourceButtons();
    showToast("Playing built-in 126 BPM synth");
  } catch (err) {
    showToast(err.message || "Could not start demo synth", 3200);
  }
}

async function handleFile(file) {
  if (!file) return;
  try {
    await audio.startFile(file);
    updateSourceButtons();
    showToast(`Playing ${file.name}`);
  } catch (err) {
    showToast(err.message || "Failed to decode audio file", 3600);
  }
}

audio.onEnded = () => {
  updateSourceButtons();
  showToast("Audio stream ended");
};

document.getElementById("btn-welcome-speaker").onclick = handleSpeaker;
document.getElementById("btn-welcome-mic").onclick = handleMic;
document.getElementById("btn-welcome-demo").onclick = handleDemo;
btnSpeaker.onclick = handleSpeaker;
btnMic.onclick = handleMic;
btnDemo.onclick = handleDemo;

btnMuteDemo.onclick = () => {
  const audible = audio.demoMuted;
  audio.setDemoAudible(audible);
  btnMuteDemo.textContent = audible ? "🔊" : "🔇";
  showToast(audible ? "Demo audio unmuted" : "Demo audio muted");
};

selInput.onchange = () => {
  if (audio.sourceType === "mic") handleMic();
};

document.getElementById("file-input").onchange = (e) => handleFile(e.target.files?.[0]);

window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => {
  e.preventDefault();
  const file = e.dataTransfer?.files?.[0];
  if (file) handleFile(file);
});

document.getElementById("btn-mode-prev").onclick = () => setModeIndex(state.modeIdx - 1);
document.getElementById("btn-mode-next").onclick = () => setModeIndex(state.modeIdx + 1);
selMode.onchange = () => setModeIndex(Number(selMode.value));

selTheme.onchange = () => {
  state.theme = selTheme.value;
  applyThemeCss(state.theme);
  showToast(`Theme: ${state.theme}`);
};
selSmooth.onchange = () => { state.smoothness = selSmooth.value; };
rngGain.oninput = () => {
  state.gain = Number(rngGain.value);
  lblGain.textContent = `${state.gain.toFixed(1)}x`;
};

btnAgc.onclick = () => {
  state.autoGain = !state.autoGain;
  btnAgc.classList.toggle("active", state.autoGain);
};
btnPeaks.onclick = () => {
  state.showPeaks = !state.showPeaks;
  btnPeaks.classList.toggle("active", state.showPeaks);
};
btnGrid.onclick = () => {
  state.showGrid = !state.showGrid;
  btnGrid.classList.toggle("active", state.showGrid);
};

btnSettings.onclick = (e) => {
  e.stopPropagation();
  setSettingsOpen(!state.settingsOpen);
};

document.addEventListener("click", (e) => {
  if (state.settingsOpen && !elPopover.contains(e.target) && e.target !== btnSettings) {
    setSettingsOpen(false);
  }
});

document.getElementById("btn-hud").onclick = () => {
  state.hudHidden = !state.hudHidden;
  if (state.hudHidden) setSettingsOpen(false);
  elHud.classList.toggle("hidden", state.hudHidden);
};
document.getElementById("btn-fs").onclick = () => {
  if (!document.fullscreenElement) document.documentElement.requestFullscreen?.();
  else document.exitFullscreen?.();
};

window.addEventListener("mousemove", resetIdleFade);
window.addEventListener("touchstart", resetIdleFade);

window.addEventListener("keydown", (e) => {
  resetIdleFade();
  if (e.key === "Escape" && state.settingsOpen) {
    setSettingsOpen(false);
    return;
  }
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  if (e.key === " " || e.key === "m" || e.key === "ArrowRight") {
    e.preventDefault();
    setModeIndex(state.modeIdx + 1);
  } else if (e.key === "ArrowLeft") {
    setModeIndex(state.modeIdx - 1);
  } else if (/^[1-9]$/.test(e.key) && Number(e.key) - 1 < WEB_MODES.length) {
    setModeIndex(Number(e.key) - 1);
  } else if (e.key === "c" || e.key === "C") {
    const dir = e.key === "C" ? -1 : 1;
    const ti = (THEMES.indexOf(state.theme) + dir + THEMES.length) % THEMES.length;
    state.theme = THEMES[ti];
    selTheme.value = state.theme;
    applyThemeCss(state.theme);
    showToast(`Theme: ${state.theme}`);
  } else if (e.key === "h" || e.key === "H") {
    state.hudHidden = !state.hudHidden;
    if (state.hudHidden) setSettingsOpen(false);
    elHud.classList.toggle("hidden", state.hudHidden);
    showToast(state.hudHidden ? "HUD hidden (press H to show)" : "HUD visible", 1600);
  } else if (e.key === "f" || e.key === "F") {
    document.getElementById("btn-fs").click();
  }
});

window.addEventListener("resize", () => renderer.resize());
populateSelects();
refreshDevices();
renderer.resize();

let lastT = performance.now();
let fpsEma = 60;

function tick(nowMs) {
  const dt = Math.max(0.001, Math.min(0.1, (nowMs - lastT) / 1000));
  lastT = nowMs;
  fpsEma = fpsEma * 0.9 + (1 / dt) * 0.1;

  const mode = WEB_MODES[state.modeIdx].id;
  const numBars = mode === "spectrogram" ? 96 : (mode === "stereo" ? 48 : 72);
  audio.update(numBars, dt, nowMs / 1000, state.smoothness, state.gain, state.autoGain);
  renderer.render(mode, audio, state, dt);

  elBeatDot.classList.toggle("active", audio.beatFlash > 0.35);
  const bpmStr = audio.bpm > 0 ? `${Math.round(audio.bpm)} BPM` : "-- BPM";
  elTelemetry.textContent = `${bpmStr} · ${audio.db.toFixed(0)} dB`;
  elFps.textContent = `${Math.round(fpsEma)} fps`;
  requestAnimationFrame(tick);
}

requestAnimationFrame(tick);
