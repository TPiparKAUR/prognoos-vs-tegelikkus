// Application state, mirrored to the URL hash so every view is a shareable link.

export type Metric = "mae" | "me" | "rmse";
export type MapModel = "ifs" | "aifs-single" | "diff";
export type StationVar = "t2m" | "wind" | "mslp" | "precip";

export interface State {
  variable: string;
  metric: Metric;
  bucket: string;
  truth: string;
  method: string;
  mapModel: MapModel;
  station: string | null;
  stationVar: StationVar;
  window: string;
}

export const DEFAULTS: State = {
  variable: "t2m",
  metric: "mae",
  bucket: "D1",
  truth: "T2",
  method: "nearest_land",
  mapModel: "ifs",
  station: null,
  stationVar: "t2m",
  window: "06-06",
};

type Listener = (s: State, changed: Set<keyof State>) => void;

const listeners: Listener[] = [];
let state: State = { ...DEFAULTS, ...fromHash() };

function fromHash(): Partial<State> {
  const p = new URLSearchParams(location.hash.slice(1));
  const out: Partial<State> = {};
  for (const k of Object.keys(DEFAULTS) as (keyof State)[]) {
    const v = p.get(k);
    if (v !== null && v !== "") (out as Record<string, string>)[k] = v;
  }
  return out;
}

function toHash(s: State): string {
  const p = new URLSearchParams();
  for (const k of Object.keys(DEFAULTS) as (keyof State)[]) {
    const v = s[k];
    if (v !== null && v !== DEFAULTS[k]) p.set(k, String(v));
  }
  const str = p.toString();
  return str ? `#${str}` : location.pathname + location.search;
}

export function get(): State {
  return state;
}

export function set(patch: Partial<State>): void {
  const changed = new Set<keyof State>();
  for (const [k, v] of Object.entries(patch) as [keyof State, State[keyof State]][]) {
    if (state[k] !== v) changed.add(k);
  }
  if (!changed.size) return;
  state = { ...state, ...patch };
  history.replaceState(null, "", toHash(state));
  for (const l of listeners) l(state, changed);
}

export function subscribe(l: Listener): void {
  listeners.push(l);
}

window.addEventListener("hashchange", () => set({ ...DEFAULTS, ...fromHash() }));
