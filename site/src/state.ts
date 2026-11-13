// Application state, mirrored to the URL hash so every view is a shareable link.
// Unknown or unavailable values in a link fall back to defaults (sanitize() in main.ts).

export type MapMode = "better" | "ifs" | "aifs-single";
export type StationVar = "t2m" | "wind" | "mslp" | "precip";

export interface State {
  truth: string;
  network: string;
  method: string;
  variable: string;
  bucket: string;
  mapMode: MapMode;
  station: string | null;
  stationVar: StationVar;
}

export const DEFAULTS: State = {
  truth: "T2",
  network: "kliima",
  method: "nearest_land",
  variable: "t2m",
  bucket: "D1",
  mapMode: "better",
  station: null,
  stationVar: "t2m",
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

/** Replace the state without notifying (used once after sanitizing a shared link). */
export function replace(s: State): void {
  state = s;
  history.replaceState(null, "", toHash(state));
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

export function onExternalChange(cb: (partial: Partial<State>) => void): void {
  window.addEventListener("hashchange", () => cb({ ...DEFAULTS, ...fromHash() }));
}
