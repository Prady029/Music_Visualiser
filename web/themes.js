/**
 * Perceptual OKLab / OKLCH Color Engine + 29 Color-Theory Themes
 * Derives 60-30-10 harmonious UI chrome (background, subtle grid, axis tint,
 * primary palette LUT, and +155 deg OKLCH complementary specular accent).
 */

export const THEME_STOPS = {
  "aurora":         [[10, 120, 140], [0, 210, 175], [80, 240, 220], [145, 110, 255], [245, 115, 220]],
  "vermilion-teal": [[14, 72, 88], [28, 148, 165], [218, 212, 198], [242, 108, 62], [255, 178, 118]],
  "bioluminescent": [[18, 24, 72], [24, 88, 178], [0, 198, 194], [112, 246, 206], [228, 255, 246]],
  "solar-flare":    [[48, 16, 46], [148, 32, 62], [235, 88, 42], [255, 178, 52], [255, 244, 188]],
  "iridescent":     [[52, 34, 112], [96, 118, 224], [218, 134, 198], [248, 208, 152], [174, 246, 236], [52, 34, 112]],
  "tokyo-night":    [[61, 89, 161], [122, 162, 247], [125, 207, 255], [187, 154, 247], [247, 118, 142]],
  "catppuccin":     [[116, 199, 236], [180, 190, 254], [203, 166, 247], [245, 194, 231], [243, 139, 168]],
  "kanagawa":       [[126, 156, 216], [149, 127, 184], [118, 148, 106], [255, 158, 59], [195, 64, 67]],
  "everforest":     [[127, 187, 179], [167, 192, 128], [219, 188, 127], [230, 152, 117], [230, 126, 128]],
  "moonlight":      [[99, 109, 166], [130, 170, 255], [192, 153, 255], [255, 117, 127], [255, 199, 119]],
  "ayu":            [[57, 186, 230], [170, 217, 76], [255, 204, 102], [255, 143, 64], [240, 113, 120]],
  "cyberpunk":      [[0, 240, 255], [123, 44, 191], [255, 0, 127], [252, 238, 9]],
  "dracula":        [[98, 114, 164], [139, 233, 253], [189, 147, 249], [255, 121, 198], [80, 250, 123]],
  "nord":           [[67, 76, 94], [94, 129, 172], [129, 161, 193], [136, 192, 208], [236, 239, 244]],
  "rose-pine":      [[49, 116, 143], [156, 207, 216], [196, 167, 231], [246, 193, 119], [235, 111, 146]],
  "vaporwave":      [[84, 13, 110], [238, 66, 102], [255, 136, 209], [160, 231, 229], [59, 206, 172]],
  "sunset":         [[60, 22, 66], [143, 45, 86], [255, 94, 91], [255, 159, 28], [255, 234, 159]],
  "sakura":         [[92, 26, 51], [158, 59, 92], [224, 108, 159], [255, 179, 198], [255, 240, 243]],
  "obsidian":       [[55, 59, 72], [102, 108, 128], [184, 134, 11], [255, 209, 102], [255, 243, 209]],
  "emerald":        [[11, 61, 46], [29, 185, 84], [30, 215, 96], [158, 240, 26], [232, 255, 240]],
  "plasma":         [[46, 5, 143], [126, 3, 168], [204, 71, 120], [248, 149, 64], [240, 249, 33]],
  "gruvbox":        [[69, 133, 136], [152, 151, 26], [215, 153, 33], [214, 93, 14], [251, 73, 52]],
  "prism":          [[0, 245, 212], [0, 187, 249], [155, 93, 229], [241, 91, 181], [254, 228, 64], [0, 245, 212]],
  "synthwave":      [[85, 20, 155], [195, 35, 195], [255, 65, 165], [65, 225, 255], [235, 250, 255]],
  "ocean":          [[15, 40, 130], [20, 105, 225], [25, 185, 245], [105, 240, 255], [225, 252, 255]],
  "fire":           [[95, 10, 15], [195, 25, 15], [255, 95, 15], [255, 195, 40], [255, 248, 190]],
  "rainbow":        [[30, 140, 255], [0, 230, 210], [75, 245, 95], [250, 225, 45], [255, 120, 35], [255, 45, 75]],
  "matrix":         [[10, 75, 20], [20, 150, 45], [40, 225, 75], [130, 255, 145], [220, 255, 225]],
  "mono":           [[90, 95, 105], [155, 160, 170], [210, 215, 220], [255, 255, 255]],
};

export const THEMES = Object.keys(THEME_STOPS);

function srgbChanToLin(c) {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
}

function linToSrgbByte(x) {
  const c = Math.max(0, Math.min(1, x));
  const s = c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055;
  return Math.max(0, Math.min(255, Math.round(s * 255)));
}

export function srgbToOklab([r, g, b]) {
  const rl = srgbChanToLin(r);
  const gl = srgbChanToLin(g);
  const bl = srgbChanToLin(b);
  const l = Math.cbrt(0.4122214708 * rl + 0.5363325363 * gl + 0.0514459929 * bl);
  const m = Math.cbrt(0.2119034982 * rl + 0.6806995451 * gl + 0.1073969566 * bl);
  const s = Math.cbrt(0.0883024619 * rl + 0.2817188376 * gl + 0.6299787005 * bl);
  return [
    0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
  ];
}

export function oklabToSrgb([L, a, b]) {
  const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = L - 0.0894841775 * a - 1.2914855480 * b;
  const l = l_ * l_ * l_;
  const m = m_ * m_ * m_;
  const s = s_ * s_ * s_;
  return [
    linToSrgbByte(+4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    linToSrgbByte(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    linToSrgbByte(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s),
  ];
}

const THEME_LAB = Object.fromEntries(
  THEMES.map((name) => [name, THEME_STOPS[name].map(srgbToOklab)])
);
const CHROME_CACHE = new Map();
const LUT_CACHE = new Map();

export function rgbCss([r, g, b], alpha = 1) {
  return alpha >= 1 ? `rgb(${r},${g},${b})` : `rgba(${r},${g},${b},${alpha})`;
}

export function getThemeChrome(theme) {
  if (CHROME_CACHE.has(theme)) return CHROME_CACHE.get(theme);
  const stops = THEME_LAB[theme] || THEME_LAB.aurora;
  const base = stops[0];
  const mid = stops[Math.floor(stops.length / 2)];
  const top = stops[stops.length - 1];
  const hue = Math.atan2(mid[2], mid[1]) + (155 * Math.PI) / 180;
  const chroma = Math.max(0.06, Math.min(0.18, Math.hypot(mid[1], mid[2]) * 1.15));

  const bgRgb = oklabToSrgb([0.13, base[1] * 0.28, base[2] * 0.28]);
  const gridRgb = oklabToSrgb([0.34, base[1] * 0.25, base[2] * 0.25]);
  const axisRgb = oklabToSrgb([0.62, mid[1] * 0.35, mid[2] * 0.35]);
  const primaryRgb = oklabToSrgb(mid);
  const accentRgb = theme === "mono"
    ? oklabToSrgb([Math.max(0.86, top[0]), 0, 0])
    : oklabToSrgb([Math.max(0.84, Math.min(0.94, top[0] + 0.07)), chroma * Math.cos(hue), chroma * Math.sin(hue)]);

  const chrome = { bgRgb, gridRgb, axisRgb, primaryRgb, accentRgb };
  CHROME_CACHE.set(theme, chrome);
  return chrome;
}

export function getThemeLut(theme, steps = 128, boost = 0, phase = 0) {
  const boostQ = Math.round(Math.max(0, Math.min(0.5, boost)) * 20);
  const phaseQ = (theme === "prism" || theme === "iridescent") ? (Math.round((((phase % 1) + 1) % 1) * 60) % 60) : 0;
  const key = `${theme}:${steps}:${boostQ}:${phaseQ}`;
  if (LUT_CACHE.has(key)) return LUT_CACHE.get(key);

  const stops = THEME_LAB[theme] || THEME_LAB.aurora;
  const nSeg = stops.length - 1;
  const rgbs = new Array(steps);
  const css = new Array(steps);
  const bAmt = boostQ / 20;

  for (let i = 0; i < steps; i++) {
    let t = steps > 1 ? i / (steps - 1) : 0;
    if (phaseQ) t = (t + phaseQ / 60) % 1;
    const scaled = t * nSeg;
    const idx = Math.min(nSeg - 1, Math.floor(scaled));
    const frac = scaled - idx;
    const c0 = stops[idx];
    const c1 = stops[idx + 1];
    let L = c0[0] + (c1[0] - c0[0]) * frac;
    let a = c0[1] + (c1[1] - c0[1]) * frac;
    let b = c0[2] + (c1[2] - c0[2]) * frac;
    if (bAmt > 0) {
      L = Math.max(0, Math.min(1, L + (1 - L) * (bAmt * 0.45)));
      a *= 1 + bAmt * 0.12;
      b *= 1 + bAmt * 0.12;
    }
    const rgb = oklabToSrgb([L, a, b]);
    rgbs[i] = rgb;
    css[i] = `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
  }
  const res = { rgbs, css };
  if (LUT_CACHE.size > 1024) LUT_CACHE.clear();
  LUT_CACHE.set(key, res);
  return res;
}
