// Color scales: sequential = one hue light->dark; diverging = blue <-> red, gray midpoint.
// Steps from the validated reference palette (dataviz skill, references/palette.md).

const SEQ_LIGHT = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];
const SEQ_DARK = ["#184f95", "#1c5cab", "#256abf", "#2a78d6", "#3987e5", "#6da7ec", "#b7d3f6"];
const DIV_LIGHT = ["#184f95", "#3987e5", "#9ec5f4", "#f0efec", "#f4b0ae", "#e66767", "#b8302f"];
const DIV_DARK = ["#6da7ec", "#3987e5", "#1c5cab", "#383835", "#9c3634", "#e34948", "#f19a99"];

export function isDark(): boolean {
  const t = document.documentElement.dataset.theme;
  if (t === "dark") return true;
  if (t === "light") return false;
  return matchMedia("(prefers-color-scheme: dark)").matches;
}

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function lerpColor(stops: string[], t: number): string {
  const x = Math.min(1, Math.max(0, t)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(x));
  const f = x - i;
  const a = hexToRgb(stops[i] as string);
  const b = hexToRgb(stops[i + 1] as string);
  const c = a.map((v, k) => Math.round(v + ((b[k] as number) - v) * f));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

export interface Scale {
  kind: "seq" | "div";
  min: number;
  max: number;
  color: (v: number) => string;
  stops: string[];
}

export function sequential(max: number): Scale {
  const stops = isDark() ? SEQ_DARK : SEQ_LIGHT;
  const m = max > 0 ? max : 1;
  return { kind: "seq", min: 0, max: m, stops, color: (v) => lerpColor(stops, v / m) };
}

export function diverging(absMax: number): Scale {
  const stops = isDark() ? DIV_DARK : DIV_LIGHT;
  const m = absMax > 0 ? absMax : 1;
  return { kind: "div", min: -m, max: m, stops, color: (v) => lerpColor(stops, (v + m) / (2 * m)) };
}

/** A "nice" upper bound (1, 2, 2.5, 5 x 10^k) for legend ticks. */
export function niceMax(v: number): number {
  if (!(v > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 2.5, 5, 10]) if (v <= m * p) return m * p;
  return 10 * p;
}

export function quantile(values: number[], q: number): number {
  const s = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!s.length) return 0;
  const i = (s.length - 1) * q;
  const lo = Math.floor(i);
  const hi = Math.ceil(i);
  return (s[lo] as number) + ((s[hi] as number) - (s[lo] as number)) * (i - lo);
}
