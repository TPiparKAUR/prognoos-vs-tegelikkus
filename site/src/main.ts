import "./style.css";
import proj4 from "proj4";
import {
  loadSite,
  loadStationSeries,
  type BucketScore,
  type Columnar,
  type LeadScore,
  type SiteData,
  type StationFeature,
  type StationScore,
} from "./data";
import { cssVar, h, hoursAgo, local, num, signed } from "./format";
import { createMap, type MapPoint, type StationMap } from "./map";
import { barChart, clearChart, leadChart, stationChart, type BarSeries, type SeriesSpec } from "./charts";
import { isDark, niceMax, quantile, sequential, type Scale } from "./scales";
import * as store from "./state";
import type { MapMode, State, StationVar } from "./state";

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;

// Forecast competitors (order = categorical slot order) and the reference.
const COMPETITORS = ["ifs", "aifs-single", "ifs-0p1"] as const;
const REF = "persistence";
const SHORT: Record<string, string> = {
  ifs: "IFS",
  "aifs-single": "AIFS",
  "ifs-0p1": "IFS 9 km",
  persistence: "Persistents",
};
const VARS: [string, string][] = [
  ["t2m", "Temperatuur"],
  ["wind_speed", "Tuule kiirus"],
  ["wind_dir", "Tuule suund"],
  ["mslp", "Õhurõhk"],
];
const BUCKET_LABEL: Record<string, string> = {
  D1: "1. päev",
  D2: "2. päev",
  D3: "3. päev",
  "D4-5": "4.–5. päev",
  "D6-10": "6.–10. päev",
  "D11-15": "11.–15. päev",
};
const MIN_N_RELIABLE = 100;

const colorOf = (m: string): string =>
  m === "ifs"
    ? cssVar("--series-ifs")
    : m === "aifs-single"
      ? cssVar("--series-aifs")
      : m === "ifs-0p1"
        ? cssVar("--series-kaur")
        : cssVar("--series-ref");

let data: SiteData;
let map: StationMap;
const stationsById = new Map<string, StationFeature>();

// ---------------------------------------------------------------- helpers
function unitOf(variable: string): string {
  return data.meta.variables[variable]?.unit ?? (variable === "precip" ? "mm" : "");
}

/** Temperature without height correction where heights are unknown (XML stations). */
function effVar(variable: string, network: string): string {
  return variable === "t2m" && network === "koik" ? "t2m_nocorr" : variable;
}

function stationVar(variable: string, cls: "kliima" | "xml"): string {
  return variable === "t2m" && cls === "xml" ? "t2m_nocorr" : variable;
}

/** "common9" (with IFS 9 km) once it has data for this selection, else "common". */
function sampleFor(s: State, variable: string): string {
  const v = effVar(variable, s.network);
  const has9 = data.bucket.some(
    (r) =>
      r.sample === "common9" && r.variable === v && r.truth_level === s.truth && r.interp_method === s.method && r.network === s.network && r.n > 0,
  );
  return has9 ? "common9" : "common";
}

function bucketRows(s: State, variable: string): BucketScore[] {
  const v = effVar(variable, s.network);
  const sample = sampleFor(s, variable);
  return data.bucket.filter(
    (r) =>
      r.variable === v &&
      r.truth_level === s.truth &&
      r.interp_method === s.method &&
      r.network === s.network &&
      r.sample === sample,
  );
}

function leadRows(s: State, variable: string): LeadScore[] {
  const v = effVar(variable, s.network);
  return data.lead.filter(
    (r) =>
      r.variable === v &&
      r.truth_level === s.truth &&
      r.interp_method === s.method &&
      r.network === s.network &&
      r.sample === sampleFor(s, variable) &&
      r.lead_h > 0,
  );
}

function fmt(v: number | null | undefined, variable: string): string {
  return num(v, variable === "wind_dir" ? 0 : variable === "mslp" ? 2 : 2);
}

function keyLine(model: string): HTMLElement {
  return h("span", {
    class: `key-line${model === REF ? " dashed" : ""}`,
    style: `border-color:${colorOf(model)}`,
    "aria-hidden": "true",
  });
}

function emptyBox(text: string): HTMLElement {
  return h("p", { class: "empty" }, text);
}

// ---------------------------------------------------------------- controls
function segmented(el: HTMLElement, options: [string, string][], key: keyof State): void {
  el.replaceChildren(
    ...options.map(([value, label]) => {
      const b = h("button", { type: "button", role: "radio", "data-value": value }, label);
      b.addEventListener("click", () => {
        if (!b.disabled) store.set({ [key]: value } as Partial<State>);
      });
      return b;
    }),
  );
  el.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const btns = [...el.querySelectorAll<HTMLButtonElement>("button:not([disabled])")];
    const i = btns.findIndex((b) => b.getAttribute("aria-checked") === "true");
    const next = btns[(i + (e.key === "ArrowRight" ? 1 : btns.length - 1)) % btns.length];
    next?.click();
    next?.focus();
  });
}

function syncSegmented(el: HTMLElement, value: string, disabled: Set<string> = new Set()): void {
  for (const b of el.querySelectorAll<HTMLButtonElement>("button")) {
    const v = b.dataset.value ?? "";
    const on = v === value;
    b.setAttribute("aria-checked", String(on));
    b.tabIndex = on ? 0 : -1;
    b.disabled = disabled.has(v);
  }
}

function tabs(el: HTMLElement, options: [string, string][], key: keyof State): void {
  el.replaceChildren(
    ...options.map(([value, label]) => {
      const b = h("button", { type: "button", role: "tab", "data-value": value }, label);
      b.addEventListener("click", () => store.set({ [key]: value } as Partial<State>));
      return b;
    }),
  );
}

function syncTabs(el: HTMLElement, value: string): void {
  for (const b of el.querySelectorAll<HTMLButtonElement>("button")) {
    b.setAttribute("aria-selected", String(b.dataset.value === value));
  }
}

const fold = (t: string) =>
  t.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase().replace(/[^A-Z0-9]+/g, "_");

/** Old links may carry the XML id of a climate station (e.g. XML_KUUSIKU_58973_...). */
function resolveOldId(id: string): string | null {
  const m = /^XML_(.+?)_\d{5}_\d{5}/.exec(id);
  if (!m) return null;
  for (const f of data.stations.features) {
    if (f.properties.class === "kliima" && fold(f.properties.name) === m[1]) return f.properties.id;
  }
  return null;
}

/** Make a shared link safe: unknown values fall back to defaults. */
function sanitize(s: State): State {
  const out = { ...s };
  if (!(out.truth in data.meta.truth_levels) || !(out.truth in data.meta.availability)) {
    out.truth = store.DEFAULTS.truth;
  }
  if (!(out.network in data.meta.networks)) out.network = store.DEFAULTS.network;
  if (out.truth === "T2") out.network = "kliima"; // XML stations have no T2
  if (!(out.method in data.meta.methods)) out.method = store.DEFAULTS.method;
  if (!VARS.some(([v]) => v === out.variable)) out.variable = store.DEFAULTS.variable;
  if (!data.meta.lead_buckets.includes(out.bucket)) out.bucket = store.DEFAULTS.bucket;
  if (!["better", "ifs", "aifs-single", "ifs-0p1"].includes(out.mapMode)) out.mapMode = "better";
  if (!["t2m", "wind", "mslp", "precip"].includes(out.stationVar)) out.stationVar = "t2m";
  if (out.station && !stationsById.has(out.station)) out.station = resolveOldId(out.station);
  if (!out.station && stationsById.has("AJHARK01")) out.station = "AJHARK01";
  return out;
}

function syncControls(s: State): void {
  const t1 = Object.keys(data.meta.availability).includes("T1");
  syncSegmented($("f-truth"), s.truth, t1 ? new Set() : new Set(["T1"]));
  syncSegmented($("f-network"), s.network, s.truth === "T2" ? new Set(["koik"]) : new Set());
  $<HTMLSelectElement>("f-method").value = s.method;
  syncTabs($("f-variable"), s.variable);
  syncSegmented($("f-mapmode"), s.mapMode);
  syncSegmented($("f-bucket"), s.bucket);
  syncSegmented($("f-stationvar"), s.stationVar);
  const notes: string[] = [];
  if (!t1) notes.push("T1 (toormõõtmine) paarid alles kogunevad – esimesed tekivad tunni-ajastuse käivitumisel.");
  if (s.truth === "T2") notes.push("T2 on ainult kliimajaamades; kõik vaatlusjaamad on valitavad T1 korral.");
  if (s.network === "koik") notes.push("Kõigi jaamade korral on temperatuur ilma kõrguskorrektsioonita (XML-jaamade kõrgus pole teada).");
  $("filters-note").textContent = notes.join(" ");
}

// ---------------------------------------------------------------- 1. leaderboard
interface Cell {
  winner: string | null;
  values: Record<string, { mae: number | null; n: number }>;
}

function leaderCell(s: State, variable: string, bucket: string): Cell {
  const values: Cell["values"] = {};
  if (variable === "precip") {
    if (s.truth !== "T2") return { winner: null, values };
    for (const r of data.precip) {
      if (r.interp_method === s.method && r.window === "06-06" && r.lead_bucket === bucket && r.threshold_mm === data.meta.precip_thresholds_mm[0]) {
        values[r.model_id] = { mae: r.mae, n: r.n };
      }
    }
  } else {
    for (const r of bucketRows(s, variable)) {
      if (r.lead_bucket === bucket) values[r.model_id] = { mae: r.mae, n: r.n };
    }
  }
  let winner: string | null = null;
  for (const m of COMPETITORS) {
    const v = values[m]?.mae;
    if (v === null || v === undefined) continue;
    if (winner === null || v < (values[winner]?.mae ?? Infinity)) winner = m;
  }
  return { winner, values };
}

function renderLeaderboard(s: State): void {
  const el = $("leaderboard");
  const buckets = data.meta.lead_buckets;
  const rowsDef: [string, string][] = [...VARS, ["precip", "24 h sademed"]];
  const wins: Record<string, Record<string, number>> = {};
  let anyData = false;
  const body = rowsDef.map(([v, label]) => {
    const isPrecip = v === "precip";
    const tr = h(
      "tr",
      { class: isPrecip ? "" : "clickable", "aria-selected": String(v === s.variable) },
      h("th", { scope: "row" }, label, h("span", { class: "unit" }, ` ${unitOf(v)}`)),
    );
    for (const b of buckets) {
      const c = leaderCell(s, v, b);
      if (!c.winner) {
        tr.append(h("td", { class: "lb-cell none" }, "–"));
        continue;
      }
      anyData = true;
      (wins[v] ??= {})[c.winner] = (wins[v]?.[c.winner] ?? 0) + 1;
      const best = c.values[c.winner];
      const others = COMPETITORS.filter((m) => m !== c.winner && c.values[m]?.mae != null);
      const second = others[0] ? c.values[others[0]]?.mae ?? null : null;
      const rel = best?.mae && second ? (second - best.mae) / best.mae : null;
      const ref = c.values[REF]?.mae ?? null;
      const refBetter = ref !== null && best?.mae != null && ref < best.mae;
      const few = (best?.n ?? 0) < MIN_N_RELIABLE;
      const title = [
        ...[...COMPETITORS, REF]
          .filter((m) => c.values[m])
          .map((m) => `${SHORT[m]}: MAE ${fmt(c.values[m]?.mae, v)} ${unitOf(v)} (n = ${c.values[m]?.n})`),
        few ? "Vähe paare – tulemus on esialgne." : "",
      ]
        .filter(Boolean)
        .join("\n");
      tr.append(
        h(
          "td",
          { class: `lb-cell${few ? " few" : ""}`, title },
          h("span", { class: "lb-win" }, keyLine(c.winner), SHORT[c.winner] ?? c.winner),
          h("span", { class: "lb-val" }, fmt(best?.mae, v)),
          rel !== null ? h("span", { class: "lb-rel" }, `teine +${num(rel * 100, 0)} %`) : null,
          refBetter ? h("span", { class: "lb-warn" }, "persistents parem") : null,
        ),
      );
    }
    if (!isPrecip) {
      const pick = () => {
        store.set({ variable: v });
        document.getElementById("f-variable")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      };
      tr.addEventListener("click", pick);
      tr.tabIndex = 0;
      tr.addEventListener("keydown", (e) => {
        if (e.key === "Enter") pick();
      });
    }
    return tr;
  });
  if (!anyData) {
    el.replaceChildren(emptyBox(`Valitud tõe (${s.truth}) ja jaamade jaoks pole veel paare.`));
    $("insight").textContent = "";
    $("leaderboard-hint").textContent = "";
    return;
  }
  el.replaceChildren(
    h(
      "div",
      { class: "table-view lb", style: "max-height:none" },
      h(
        "table",
        {},
        h(
          "thead",
          {},
          h("tr", {}, h("th", {}, "Muutuja"), ...buckets.map((b) => h("th", { class: "c" }, BUCKET_LABEL[b] ?? b))),
        ),
        h("tbody", {}, ...body),
      ),
    ),
  );
  // Automatic plain-language summary.
  const parts: string[] = [];
  for (const [v, label] of rowsDef) {
    const w = wins[v];
    if (!w) continue;
    const total = Object.values(w).reduce((a, b) => a + b, 0);
    const [top, k] = Object.entries(w).sort((a, b) => b[1] - a[1])[0] ?? ["", 0];
    parts.push(k === total ? `${label.toLowerCase()}: ${SHORT[top]} kõigis ${total} vahemikus` : `${label.toLowerCase()}: ${SHORT[top]} ${k}/${total}`);
  }
  const p = data.meta.period;
  $("insight").textContent =
    `Võitja ehk väikseim keskmine viga (MAE) ${p.n_days} päeva andmetel – ${parts.join("; ")}. ` +
    (p.n_days < 30 ? "Andmeid on veel vähe: erinevused on esialgsed ja statistiliselt kontrollimata (vaja ≥ 30 päeva)." : "");
  const pend = Object.keys(data.meta.pending_models);
  $("leaderboard-hint").textContent =
    `Lahtris: kõige väiksema veaga prognoos, selle MAE ja kui palju suurem on teise viga. „Persistents parem“: eilne vaatlus oli täpsem. Hall = vähem kui ${MIN_N_RELIABLE} paari. ` +
    (pend.length ? `Ootel: ${pend.map((m) => SHORT[m]).join(", ")} (andmeallikas pole veel kättesaadav, vt jaotis 4). ` : "") +
    (sampleFor(s, s.variable) === "common"
      ? "IFS 9 km (KAURi asukohaprognoosi alus) kogub andmeid alates 13.11 – see lisandub tabelisse, kui tal on samad juhtumid mis teistel. "
      : "IFS 9 km = KAURi asukohaprognoosi alus (sama mudel ja lähima ruudupunkti meetod, ECMWF avaandmetest). ") +
    "Klõpsa real, et näha graafikuid.";
}

// ---------------------------------------------------------------- 1b. lead charts
function renderLeadCharts(s: State): void {
  const unit = unitOf(s.variable);
  const sel = leadRows(s, s.variable);
  const models = [...COMPETITORS, REF].filter((m) => sel.some((r) => r.model_id === m));
  for (const [metric, chartId, tableId] of [
    ["mae", "mae-chart", "mae-table"],
    ["me", "me-chart", "me-table"],
  ] as const) {
    const el = $(chartId);
    const series: SeriesSpec[] = models
      .filter((m) => !(metric === "me" && (s.variable === "wind_dir" || m === REF)))
      .map((m) => ({
        key: m,
        name: SHORT[m] ?? m,
        color: colorOf(m),
        dashed: m === REF,
        points: sel
          .filter((r) => r.model_id === m)
          .sort((a, b) => a.lead_h - b.lead_h)
          .map((r) => [r.lead_h, r[metric]] as [number, number | null]),
      }));
    if (!series.some((x) => x.points.length)) {
      clearChart(el, "Selle valiku jaoks paare veel pole");
    } else {
      leadChart(el, series, unit, metric === "me");
    }
    const tbl = $(tableId);
    if (!tbl.hidden) {
      const leads = [...new Set(sel.map((r) => r.lead_h))].sort((a, b) => a - b);
      tbl.replaceChildren(
        h(
          "table",
          {},
          h("thead", {}, h("tr", {}, h("th", {}, "Etteanne, h"), ...series.map((x) => h("th", {}, `${x.name}, ${unit}`)), h("th", {}, "n"))),
          h(
            "tbody",
            {},
            ...leads.map((L) => {
              const rs = sel.filter((r) => r.lead_h === L);
              return h(
                "tr",
                {},
                h("td", {}, String(L)),
                ...series.map((x) => {
                  const v = rs.find((q) => q.model_id === x.key)?.[metric];
                  return h("td", {}, metric === "me" ? signed(v ?? null, 2) : fmt(v, s.variable));
                }),
                h("td", { class: "muted" }, String(rs[0]?.n ?? "")),
              );
            }),
          ),
        ),
      );
    }
  }
  const label = data.meta.variables[effVar(s.variable, s.network)]?.label ?? s.variable;
  $("mae-hint").textContent = `${label}, ${unit}. Mida madalam, seda täpsem. Katkendjoon: persistents (eilne vaatlus) – prognoos peab olema sellest parem.`;
  $("me-hint").textContent =
    s.variable === "wind_dir"
      ? "Tuule suuna nihet ei arvutata (ringsuurus); vaata MAE-d."
      : `${label}, ${unit}. Üle nulli: prognoos keskmiselt liiga kõrge; alla nulli: liiga madal.`;
}

// ---------------------------------------------------------------- 2. map + list
function stationSample(rows: StationScore[]): StationScore[] {
  const nine = rows.filter((r) => r.sample === "common9");
  return nine.length ? nine : rows.filter((r) => r.sample === "common");
}

function stationScoreRows(s: State): Map<string, StationScore[]> {
  const out = new Map<string, StationScore[]>();
  for (const r of data.station) {
    if (r.sample === "all" || r.truth_level !== s.truth || r.interp_method !== s.method || r.lead_bucket !== s.bucket) continue;
    const f = stationsById.get(r.station_id);
    if (!f || r.variable !== stationVar(s.variable, f.properties.class)) continue;
    const list = out.get(r.station_id) ?? [];
    list.push(r);
    out.set(r.station_id, list);
  }
  for (const [k, v] of out) out.set(k, stationSample(v));
  return out;
}

function mapValue(list: StationScore[] | undefined, mode: MapMode): { v: number | null; n: number } {
  if (!list) return { v: null, n: 0 };
  const by = (m: string) => list.find((r) => r.model_id === m);
  if (mode === "better") {
    const a = by("ifs");
    const b = by("aifs-single");
    if (a?.mae == null || b?.mae == null) return { v: null, n: 0 };
    return { v: a.mae - b.mae, n: Math.min(a.n, b.n) };
  }
  const r = by(mode);
  return { v: r?.mae ?? null, n: r?.n ?? 0 };
}

// Diverging blue (IFS better) <-> orange (AIFS better), gray midpoint.
function betterScale(absMax: number): Scale {
  const light = ["#184f95", "#3987e5", "#9ec5f4", "#e6e5e0", "#f6bc9f", "#eb6834", "#a8441b"];
  const dark = ["#6da7ec", "#3987e5", "#1c5cab", "#3a3a37", "#8a3a17", "#d95926", "#f0a27f"];
  const stops = isDark() ? dark : light;
  const m = absMax > 0 ? absMax : 1;
  const lerp = (t: number) => {
    const x = Math.min(1, Math.max(0, t)) * (stops.length - 1);
    const i = Math.min(stops.length - 2, Math.floor(x));
    const f = x - i;
    const pa = parseInt((stops[i] as string).slice(1), 16);
    const pb = parseInt((stops[i + 1] as string).slice(1), 16);
    const ch = (sh: number) => Math.round(((pa >> sh) & 255) + ((((pb >> sh) & 255) - ((pa >> sh) & 255)) * f));
    return `rgb(${ch(16)}, ${ch(8)}, ${ch(0)})`;
  };
  return { kind: "div", min: -m, max: m, stops, color: (v) => lerp((v + m) / (2 * m)) };
}

let lastMapRows = new Map<string, StationScore[]>();

function renderMapAndList(s: State): void {
  const scores = stationScoreRows(s);
  lastMapRows = scores;
  const vals: { f: StationFeature; v: number | null; n: number }[] = data.stations.features.map((f) => ({
    f,
    ...mapValue(scores.get(f.properties.id), s.mapMode),
  }));
  const finite = vals.map((x) => x.v).filter((v): v is number => v !== null);
  const scale =
    s.mapMode === "better"
      ? betterScale(niceMax(quantile(finite.map(Math.abs), 0.9)))
      : sequential(niceMax(quantile(finite, 0.95)));
  const points: MapPoint[] = vals.map(({ f, v }) => ({
    id: f.properties.id,
    lon: f.geometry.coordinates[0],
    lat: f.geometry.coordinates[1],
    kind: f.properties.class,
    color: v === null ? null : scale.color(v),
    radius: f.properties.class === "kliima" ? 8 : 5.5,
  }));
  map.update(points, s.station);
  // Legend
  const unit = unitOf(s.variable);
  const grad = `linear-gradient(90deg, ${scale.stops.join(",")})`;
  const legend = $("map-legend");
  legend.replaceChildren(
    h("div", {}, h("strong", {}, s.mapMode === "better" ? `Kumb mudel on täpsem? (MAE vahe, ${unit})` : `${SHORT[s.mapMode]} keskmine viga (MAE), ${unit}`)),
    h("div", { class: "ramp", style: `background:${grad}` }),
    s.mapMode === "better"
      ? h("div", { class: "ticks" }, h("span", {}, `IFS parem ${num(scale.max, 1)}`), h("span", {}, "võrdne"), h("span", {}, `AIFS parem ${num(scale.max, 1)}`))
      : h("div", { class: "ticks" }, h("span", {}, "0"), h("span", {}, num(scale.max / 2, 1)), h("span", {}, num(scale.max, 1))),
    h(
      "div",
      { class: "sym" },
      h("span", {}, h("span", { class: "c big" }), "kliimajaam"),
      h("span", {}, h("span", { class: "c small" }), "muu vaatlusjaam (XML)"),
      h("span", {}, h("span", { class: "c hollow" }), "andmed puuduvad"),
    ),
  );
  const nWith = finite.length;
  $("map-lead").textContent =
    `${BUCKET_LABEL[s.bucket]} · ${data.meta.variables[stationVar(s.variable, "kliima")]?.label ?? s.variable} · tõde ${s.truth}. ` +
    `Andmed ${nWith} jaamas ${data.stations.features.length}-st. ` +
    (s.truth === "T2" ? "Muud vaatlusjaamad (XML) on hallid: neil on ainult T1-mõõtmised – vali üleval „T1“." : "");
  renderList(s, vals);
}

function renderList(s: State, vals: { f: StationFeature; v: number | null; n: number }[]): void {
  const q = $<HTMLInputElement>("station-search").value.trim().toLowerCase();
  const unit = unitOf(s.variable);
  const rows = vals
    .filter(({ f }) => !q || f.properties.name.toLowerCase().includes(q))
    .sort((a, b) => {
      if (a.v === null && b.v !== null) return 1;
      if (b.v === null && a.v !== null) return -1;
      if (a.v !== null && b.v !== null) return a.v - b.v;
      return a.f.properties.name.localeCompare(b.f.properties.name, "et");
    });
  $("list-hint").textContent =
    s.mapMode === "better"
      ? `IFS − AIFS MAE (${unit}): negatiivne = IFS täpsem. Klõpsa jaamal analüüsi nägemiseks.`
      : `${SHORT[s.mapMode]} MAE (${unit}), väiksem on parem. Klõpsa jaamal analüüsi nägemiseks.`;
  const body = rows.map(({ f, v, n }) => {
    const p = f.properties;
    const winner = s.mapMode === "better" && v !== null ? (v < 0 ? "ifs" : v > 0 ? "aifs-single" : null) : null;
    const tr = h(
      "tr",
      { class: `clickable${p.id === s.station ? " sel" : ""}`, tabindex: 0 },
      h("td", {}, p.name, h("span", { class: `tag ${p.class}` }, p.class === "kliima" ? "kliima" : "XML")),
      h("td", {}, v === null ? h("span", { class: "muted" }, "–") : s.mapMode === "better" ? signed(v, 2) : fmt(v, s.variable)),
      h("td", {}, winner ? h("span", { class: "lb-win" }, keyLine(winner), SHORT[winner] ?? "") : ""),
      h("td", { class: "muted" }, n ? String(n) : ""),
    );
    const pick = () => {
      store.set({ station: p.id });
      $("station").scrollIntoView({ behavior: "smooth", block: "start" });
    };
    tr.addEventListener("click", pick);
    tr.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        pick();
      }
    });
    return tr;
  });
  $("station-list").replaceChildren(
    h(
      "table",
      {},
      h("thead", {}, h("tr", {}, h("th", {}, "Jaam"), h("th", {}, s.mapMode === "better" ? "Vahe" : "MAE"), h("th", {}, "Parem"), h("th", {}, "n"))),
      h("tbody", {}, ...body),
    ),
  );
}

function showStationTooltip(id: string | null, x: number, y: number): void {
  const tip = $("tooltip");
  if (!id) {
    tip.hidden = true;
    return;
  }
  const f = stationsById.get(id);
  if (!f) return;
  const s = store.get();
  const p = f.properties;
  const parts: (HTMLElement | string)[] = [h("strong", {}, p.name), h("div", { class: "muted" }, p.class === "kliima" ? "Kliimajaam (kinnitatud)" : "Vaatlusjaam XML-ist (ainult T1)")];
  const list = lastMapRows.get(id);
  const v = stationVar(s.variable, p.class);
  for (const m of [...COMPETITORS, REF]) {
    const r = list?.find((x) => x.model_id === m);
    if (!r) continue;
    parts.push(h("div", { class: "row" }, h("span", {}, keyLine(m), ` ${SHORT[m]}`), h("strong", {}, `${fmt(r.mae, v)} ${unitOf(v)}`)));
  }
  if (!list?.length) parts.push(h("div", { class: "muted" }, "Selles valikus paare pole."));
  const o = p.latest_obs;
  if (o) {
    const bits = [
      o.t2m_degC !== null ? `${num(o.t2m_degC, 1)} °C` : "",
      o.wind_speed_m_s !== null ? `tuul ${num(o.wind_speed_m_s, 1)} m/s` : "",
      o.phenomenon ?? "",
    ].filter(Boolean);
    if (bits.length) parts.push(h("div", { class: "muted", style: "margin-top:4px" }, `${local(o.time_utc)}: ${bits.join(", ")}`));
  }
  tip.replaceChildren(...parts);
  tip.hidden = false;
  const w = tip.offsetWidth;
  tip.style.left = `${Math.min(window.innerWidth - w - 8, x + 14)}px`;
  tip.style.top = `${y + 14}px`;
}

// ---------------------------------------------------------------- 3. station
const STATION_VARS: [StationVar, string][] = [
  ["t2m", "Temp."],
  ["wind", "Tuul"],
  ["mslp", "Rõhk"],
  ["precip", "Sademed"],
];

function col(c: Columnar | undefined, name: string): unknown[] {
  return (c?.[name] as unknown[] | undefined) ?? [];
}

function zip(c: Columnar | undefined, field: string): [string, number | null][] {
  const t = col(c, "valid_time_utc") as string[];
  const v = col(c, field) as (number | null)[];
  return t.map((x, i) => [x, v[i] ?? null]);
}

function stepPrecip(c: Columnar | undefined): [string, number | null][] {
  const pts = zip(c, "precip_acc_mm");
  const out: [string, number | null][] = [];
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1]?.[1];
    const b = pts[i]?.[1];
    out.push([pts[i]?.[0] as string, a == null || b == null ? null : Math.max(0, b - a)]);
  }
  return out;
}

function lest97(lon: number, lat: number): [number, number] {
  const [x, y] = proj4("EPSG:4326", "EPSG:3301", [lon, lat]);
  return [x ?? NaN, y ?? NaN];
}

let stationToken = 0;

async function renderStation(s: State): Promise<void> {
  const f = s.station ? stationsById.get(s.station) : undefined;
  const notice = $("station-notice");
  notice.replaceChildren();
  if (!f) {
    $("station-title").replaceChildren(h("span", { class: "num" }, "3"), " Jaama analüüs");
    $("station-meta").textContent = "Vali jaam kaardilt või loendist.";
    $("station-kpis").replaceChildren();
    clearChart($("st-err-chart"), "Jaam valimata");
    clearChart($("st-ts-chart"), "Jaam valimata");
    return;
  }
  const p = f.properties;
  const [lon, lat] = f.geometry.coordinates;
  const [east, north] = lest97(lon, lat);
  $("station-title").replaceChildren(h("span", { class: "num" }, "3"), ` Jaama analüüs: ${p.name}`);
  const measures = p.latest_obs?.measures ?? [];
  const mLabel: Record<string, string> = { t2m: "temperatuur", wind: "tuul", precip: "sademed", pressure: "õhurõhk" };
  $("station-meta").textContent =
    `${p.class === "kliima" ? "Kliimajaam" : "Vaatlusjaam (XML)"} · ${p.id}${p.wmo_code ? ` · WMO ${p.wmo_code}` : ""} · ` +
    `${num(lat, 4)} N, ${num(lon, 4)} E (L-EST97 x ${num(north, 0)}, y ${num(east, 0)})` +
    (p.height_m_EH2000 !== null ? ` · ${num(p.height_m_EH2000, 1)} m (EH2000)` : " · kõrgus teadmata") +
    (measures.length ? ` · mõõdab: ${measures.map((m) => mLabel[m] ?? m).join(", ")}` : "");
  if (p.class === "xml" && s.truth === "T2") {
    const btn = h("button", { type: "button", class: "ghost" }, "Vaheta tõeks T1");
    btn.addEventListener("click", () => store.set({ truth: "T1", network: "koik" }));
    notice.append(h("div", { class: "notice" }, "See jaam on ainult vaatluste XML-is: kvaliteedikontrollitud (T2) andmeid pole. Skoorid on T1 (toormõõtmine) korral. ", btn));
  }
  // KPIs + error by bucket from station scores
  const v = stationVar(s.variable, p.class);
  const unit = unitOf(v);
  const rowsAll = stationSample(
    data.station.filter((r) => r.station_id === p.id && r.truth_level === s.truth && r.interp_method === s.method && r.variable === v),
  );
  const kpis = [...COMPETITORS, REF]
    .map((m) => ({ m, r: rowsAll.find((r) => r.model_id === m && r.lead_bucket === s.bucket) }))
    .filter((x) => x.r);
  $("station-kpis").replaceChildren(
    ...(kpis.length
      ? kpis.map(({ m, r }) =>
          h(
            "div",
            { class: "kpi" },
            h("div", { class: "k-label" }, keyLine(m), `${SHORT[m]} · MAE · ${BUCKET_LABEL[s.bucket]}`),
            h("div", { class: "k-value" }, fmt(r?.mae, v), h("span", { class: "k-unit" }, unit)),
            h("div", { class: "k-foot" }, `nihe ${signed(r?.me ?? null, 2)} ${unit} · n = ${r?.n}`),
          ),
        )
      : [emptyBox(`${data.meta.variables[v]?.label ?? v}: selles jaamas pole valitud tõe (${s.truth}) ja etteande jaoks paare.`)]),
  );
  const buckets = data.meta.lead_buckets.filter((b) => rowsAll.some((r) => r.lead_bucket === b));
  const bars: BarSeries[] = [...COMPETITORS, REF]
    .filter((m) => rowsAll.some((r) => r.model_id === m))
    .map((m) => ({
      name: SHORT[m] ?? m,
      color: colorOf(m),
      dashed: m === REF,
      values: buckets.map((b) => rowsAll.find((r) => r.model_id === m && r.lead_bucket === b)?.mae ?? null),
    }));
  const errEl = $("st-err-chart");
  if (!buckets.length) clearChart(errEl, "Selles jaamas pole valitud tõe ja muutuja jaoks paare");
  else barChart(errEl, buckets.map((b) => BUCKET_LABEL[b] ?? b), bars, unit);
  $("st-err-hint").textContent = `${data.meta.variables[v]?.label ?? v} (MAE, ${unit}), tõde ${s.truth}. Madalam tulp = täpsem. Muutujat vaheta jaotise 1 vahelehtedelt.`;

  // Time series
  const el = $("st-ts-chart");
  const token = ++stationToken;
  const series = await loadStationSeries(p.id);
  if (token !== stationToken) return;
  if (!series) {
    clearChart(el, "Aegrida puudub (selles jaamas pole veel prognoose ega vaatlusi)");
    $("st-ts-hint").textContent = "";
    return;
  }
  const obsColor = cssVar("--series-obs");
  const specs: SeriesSpec[] = [];
  const sv = s.stationVar;
  const fcField = sv === "t2m" ? "t2m_degC" : sv === "wind" ? "wind_speed_m_s" : "mslp_hPa";
  const tsUnit = sv === "t2m" ? "°C" : sv === "wind" ? "m/s" : sv === "mslp" ? "hPa" : "mm";
  if (sv === "precip") {
    const obs = series.obs.T2 ?? series.obs.T1;
    if (obs) specs.push({ key: "obs", name: `Vaatlus ${series.obs.T2 ? "T2" : "T1"}, mm/h`, color: obsColor, kind: "bar", points: zip(obs, "precip_1h_mm") });
    for (const m of COMPETITORS) {
      const r = series.latest_run[m];
      if (r) specs.push({ key: m, name: `${SHORT[m]} viimane jooks, mm/samm`, color: colorOf(m), kind: "bar", points: stepPrecip(r) });
    }
  } else {
    if (series.obs.T2) specs.push({ key: "T2", name: "Vaatlus T2", color: obsColor, points: zip(series.obs.T2, fcField), width: 2.5 });
    if (series.obs.T1 && sv !== "mslp") specs.push({ key: "T1", name: "Vaatlus T1 (XML)", color: obsColor, kind: "dots", points: zip(series.obs.T1, fcField) });
    for (const m of COMPETITORS) {
      const tr = series.trace_24h[m];
      if (tr) specs.push({ key: `${m}-24`, name: `${SHORT[m]} 1 päev ette`, color: colorOf(m), dashed: true, width: 1.5, points: zip(tr, fcField) });
      const r = series.latest_run[m];
      if (r) specs.push({ key: m, name: `${SHORT[m]} viimane jooks`, color: colorOf(m), points: zip(r, fcField) });
    }
  }
  const now = Date.now();
  if (!specs.some((q) => q.points.some((pt) => pt[1] !== null))) {
    clearChart(el, p.class === "xml" && sv === "mslp" ? "XML-jaamade rõhku ei võrrelda" : "Selle muutuja andmed puuduvad");
  } else {
    stationChart(el, {
      title: "",
      unit: tsUnit,
      series: specs,
      nowIso: new Date(now).toISOString(),
      startIso: new Date(now - 4 * 86_400_000).toISOString(),
      endIso: new Date(now + 5 * 86_400_000).toISOString(),
      bars: sv === "precip",
    });
  }
  const runs = COMPETITORS.map((m) => {
    const r = series.latest_run[m];
    return r?.issue_time_utc ? `${SHORT[m]} ${local(r.issue_time_utc as string)}` : null;
  }).filter(Boolean);
  $("st-ts-hint").textContent =
    `Viimased jooksud: ${runs.join(" · ") || "–"}. Katkendjoon = prognoos, mis tehti ~1 päev enne. ` +
    (p.class === "xml" && sv === "t2m" ? "Temperatuur ilma kõrguskorrektsioonita. " : "") +
    "Suumi hiire/puutega.";
}

// ---------------------------------------------------------------- 4. status + precip
function renderStatus(): void {
  const m = data.meta;
  const fr = m.freshness;
  const srcNames: Record<string, string> = {
    "ecmwf:ifs": "ECMWF IFS",
    "ecmwf:aifs-single": "ECMWF AIFS Single",
    obs_xml: "Vaatluste XML (T1)",
    kliima: "Kliimaandmestik (T2)",
    kaur_fc: "KAURi eesti-prognoos XML",
  };
  const srcRows = fr
    ? Object.entries(fr.sources).map(([k, v]) => {
        const ok = v.status === "ok";
        return h(
          "div",
          { class: "src-row" },
          h("span", {}, srcNames[k] ?? k),
          h(
            "span",
            { class: "state" },
            h("span", { class: "dot", style: `background:${ok ? cssVar("--good") : cssVar("--critical")}` }),
            ok ? "värske" : "vananenud",
            h("span", { class: "muted", style: "font-weight:400" }, ` · ${v.age_hours === null ? "–" : `${num(v.age_hours, 1)} h`}`),
          ),
        );
      })
    : [h("p", { class: "muted" }, "Monitori olekut pole.")];
  const pendingRows = Object.keys(m.pending_models).map((k) =>
    h("div", { class: "src-row" }, h("span", {}, m.models[k] ?? k), h("span", { class: "state" }, h("span", { class: "dot", style: `background:${cssVar("--warning")}` }), "ootel")),
  ).concat(Object.entries(m.pending_models).map(([, why]) => h("p", { class: "hint" }, why)));
  const runRows = Object.entries(m.runs).map(([k, v]) =>
    h("div", { class: "src-row" }, h("span", {}, m.models[k] ?? k), h("span", {}, `${v.n} jooksu · ${local(v.first_utc)} … ${local(v.last_utc)} · ${v.cycles.join(", ")}`)),
  );
  $("status").replaceChildren(
    h("div", {}, h("h3", {}, "Allikad"), ...srcRows, ...pendingRows),
    h(
      "div",
      {},
      h("h3", {}, "Arhiiv"),
      ...runRows,
      h("div", { class: "src-row" }, h("span", {}, "Paare"), h("span", {}, `${m.period.n_pairs.toLocaleString("et-EE")} · ${m.period.n_days} päeva`)),
      h("div", { class: "src-row" }, h("span", {}, "Periood"), h("span", {}, `${local(m.period.first_valid_utc)} … ${local(m.period.last_valid_utc)}`)),
    ),
    h(
      "div",
      {},
      h("h3", {}, "Metoodika lühidalt"),
      h(
        "ul",
        {},
        h("li", {}, "MAE = keskmine absoluutne viga; ME (nihe) = keskmine viga märgiga. Persistents = vaatlus 24 h (või k·24 h) enne – lihtsaim võrdlusprognoos."),
        h("li", {}, "T2 = KAURi kliimaandmestik (kvaliteedikontrollitud, ~1 päev viitega). T1 = vaatluste XML (toormõõtmine, hetktõmmis 10–30 min pärast täistundi)."),
        h("li", {}, "Mudelid võrreldakse ühisel valimil: samad jooksud, etteanded, jaamad ja tunnid."),
        h("li", {}, "Prognoosi väärtus jaamas: lähim maapunkt + temperatuuri kõrguskorrektsioon 0,0065 K/m (kliimajaamad); bilineaarne ja lähim ruudupunkt valitavad."),
        ...m.notes.map((n) => h("li", {}, n)),
      ),
    ),
  );
  $("attribution").replaceChildren(
    ...m.attribution.flatMap((a, i) => [i ? " · " : "", h("a", { href: a.url, rel: "noopener" }, a.text)]),
    " · Aluskaart: © Maa- ja Ruumiamet",
    ` · Andmed koostatud ${local(m.generated_utc, true)}.`,
  );
  const problems = fr?.problems.length ?? 0;
  const pill = $("freshness");
  pill.replaceChildren(
    h("span", { class: "dot", style: `background:${problems ? cssVar("--warning") : cssVar("--good")}` }),
    `Uuendatud ${hoursAgo(m.generated_utc)}`,
    problems ? ` · ${problems} hoiatus${problems > 1 ? "t" : ""}` : "",
  );
  pill.title = fr?.problems.join("\n") || "Kõik allikad värsked";
}

function renderPrecip(s: State): void {
  const el = $("precip");
  const sel = data.precip.filter((r) => r.interp_method === s.method && r.window === "06-06" && r.lead_bucket === s.bucket);
  if (!sel.length) {
    el.replaceChildren(emptyBox(`${BUCKET_LABEL[s.bucket]}: 24 h sademete paare veel pole.`));
    return;
  }
  const models = COMPETITORS.filter((m) => sel.some((r) => r.model_id === m));
  el.replaceChildren(
    h("p", { class: "hint" }, `${BUCKET_LABEL[s.bucket]} (etteande valik jaotises 2). POD = tabamuste osa, FAR = valehäirete osa, CSI = ühine täpsus. „ebam.“ = juhtumid, mida prognoosi pakkimistäpsuse tõttu ei saa kindlalt liigitada (ADR-005).`),
    h(
      "div",
      { class: "table-view" },
      h(
        "table",
        {},
        h("thead", {}, h("tr", {}, h("th", {}, "Lävi"), ...models.flatMap((m) => [h("th", {}, `${SHORT[m]} POD`), h("th", {}, "FAR"), h("th", {}, "CSI"), h("th", {}, "ebam.")]), h("th", {}, "sündmusi"))),
        h(
          "tbody",
          {},
          ...data.meta.precip_thresholds_mm.map((t) => {
            const cells = models.flatMap((m) => {
              const r = sel.find((x) => x.model_id === m && x.threshold_mm === t);
              return [h("td", {}, num(r?.pod, 2)), h("td", {}, num(r?.far, 2)), h("td", {}, num(r?.csi, 2)), h("td", { class: "muted" }, r ? String(r.n_uncertain) : "–")];
            });
            const ev = sel.find((x) => x.threshold_mm === t)?.n_obs_events;
            return h("tr", {}, h("td", {}, `≥ ${num(t, 1)} mm`), ...cells, h("td", { class: "muted" }, ev === undefined ? "–" : String(ev)));
          }),
        ),
      ),
    ),
  );
}

// ---------------------------------------------------------------- wiring
function renderAll(s: State, changed?: Set<keyof State>): void {
  syncControls(s);
  const any = (...k: (keyof State)[]) => !changed || k.some((x) => changed.has(x));
  if (any("truth", "network", "method", "variable")) renderLeaderboard(s);
  if (any("truth", "network", "method", "variable")) renderLeadCharts(s);
  if (any("truth", "method", "variable", "bucket", "mapMode", "station")) renderMapAndList(s);
  if (any("truth", "method", "variable", "bucket", "station", "stationVar")) void renderStation(s);
  if (any("method", "bucket")) renderPrecip(s);
}

function setupTheme(): void {
  $("theme-toggle").addEventListener("click", () => {
    const next = isDark() ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("pvt-theme", next);
    } catch {
      /* storage unavailable: theme still switches for this view */
    }
    map.restyle();
    renderAll(store.get());
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (!document.documentElement.dataset.theme) {
      map.restyle();
      renderAll(store.get());
    }
  });
}

function setupTableToggles(): void {
  for (const b of document.querySelectorAll<HTMLButtonElement>("[data-table-toggle]")) {
    b.setAttribute("aria-pressed", "false");
    b.addEventListener("click", () => {
      const t = $(`${b.dataset.tableToggle}-table`);
      t.hidden = !t.hidden;
      b.setAttribute("aria-pressed", String(!t.hidden));
      renderLeadCharts(store.get());
    });
  }
}

async function init(): Promise<void> {
  try {
    data = await loadSite();
  } catch (e) {
    $("freshness").textContent = "Andmete laadimine ebaõnnestus";
    $("main").prepend(emptyBox(`Andmeid ei õnnestunud laadida: ${String(e)}`));
    return;
  }
  for (const f of data.stations.features) stationsById.set(f.properties.id, f);
  segmented(
    $("f-truth"),
    [
      ["T2", "T2 · kvaliteedikontrollitud"],
      ["T1", "T1 · toormõõtmine"],
    ],
    "truth",
  );
  segmented(
    $("f-network"),
    [
      ["kliima", "Kliimajaamad"],
      ["koik", "Kõik vaatlusjaamad"],
    ],
    "network",
  );
  const method = $<HTMLSelectElement>("f-method");
  method.replaceChildren(...Object.entries(data.meta.methods).map(([v, l]) => h("option", { value: v }, l)));
  method.addEventListener("change", () => store.set({ method: method.value }));
  tabs($("f-variable"), VARS, "variable");
  segmented(
    $("f-mapmode"),
    [
      ["better", "Kumb parem"],
      ["ifs", "IFS viga"],
      ["aifs-single", "AIFS viga"],
      ["ifs-0p1", "IFS 9 km viga"],
    ],
    "mapMode",
  );
  segmented($("f-bucket"), data.meta.lead_buckets.map((b) => [b, BUCKET_LABEL[b] ?? b]), "bucket");
  segmented($("f-stationvar"), STATION_VARS, "stationVar");
  $("station-search").addEventListener("input", () => renderMapAndList(store.get()));

  map = createMap($("map"), showStationTooltip, (id) => store.set({ station: id }));
  setupTheme();
  setupTableToggles();
  renderStatus();
  // T1 requested via link but T2-only network etc.: normalise once, then render.
  store.replace(sanitize(store.get()));
  store.subscribe((s, changed) => {
    const clean = sanitize(s);
    if (clean.network !== s.network || clean.station !== s.station) {
      store.set(clean);
      return;
    }
    renderAll(s, changed);
  });
  store.onExternalChange((partial) => store.set(sanitize({ ...store.get(), ...partial })));
  renderAll(store.get());
}

void init();
