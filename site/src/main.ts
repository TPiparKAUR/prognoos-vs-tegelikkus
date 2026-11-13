import "./style.css";
import {
  loadSite,
  loadStationSeries,
  type BucketScore,
  type Columnar,
  type SiteData,
  type StationFeature,
  type StationScore,
} from "./data";
import { cssVar, h, hoursAgo, local, num, pct, signed } from "./format";
import { createMap, type MapPoint, type StationMap } from "./map";
import { clearChart, leadChart, stationChart, type SeriesSpec } from "./charts";
import { diverging, isDark, niceMax, quantile, sequential, type Scale } from "./scales";
import * as store from "./state";
import type { MapModel, Metric, State, StationVar } from "./state";

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;

const MODELS = ["ifs", "aifs-single"] as const;
const SHORT: Record<string, string> = { ifs: "IFS", "aifs-single": "AIFS", persistence: "Persistents" };
const METRICS: Record<Metric, string> = { mae: "MAE", me: "ME (nihe)", rmse: "RMSE" };
const VAR_TABS: [string, string][] = [
  ["t2m", "Temperatuur"],
  ["wind_speed", "Tuule kiirus"],
  ["wind_dir", "Tuule suund"],
  ["wind_vec", "Tuulevektor"],
  ["mslp", "Rõhk"],
];
const BUCKET_LABEL: Record<string, string> = {
  D1: "1. päev",
  D2: "2. päev",
  D3: "3. päev",
  "D4-5": "4.–5. p",
  "D6-10": "6.–10. p",
  "D11-15": "11.–15. p",
};
const MIN_N_MAP = 20; // fewer pairs -> hollow symbol (docs/05 §1)

const seriesColor = (m: string) =>
  m === "ifs" ? cssVar("--series-ifs") : m === "aifs-single" ? cssVar("--series-aifs") : cssVar("--series-ref");

let data: SiteData;
let map: StationMap;
const stationsById = new Map<string, StationFeature>();

// ---------- segmented controls ----------
function segmented(el: HTMLElement, options: [string, string][], key: keyof State): void {
  el.replaceChildren(
    ...options.map(([value, label]) => {
      const b = h("button", { type: "button", role: "radio", "data-value": value }, label);
      b.addEventListener("click", () => store.set({ [key]: value } as Partial<State>));
      return b;
    }),
  );
  // Arrow-key navigation inside the radio group.
  el.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const btns = [...el.querySelectorAll<HTMLButtonElement>("button")];
    const i = btns.findIndex((b) => b.getAttribute("aria-checked") === "true");
    const next = btns[(i + (e.key === "ArrowRight" ? 1 : btns.length - 1)) % btns.length];
    next?.click();
    next?.focus();
  });
}

function syncSegmented(el: HTMLElement, value: string): void {
  for (const b of el.querySelectorAll<HTMLButtonElement>("button")) {
    const on = b.dataset.value === value;
    b.setAttribute("aria-checked", String(on));
    b.tabIndex = on ? 0 : -1;
  }
}

function fillSelect(el: HTMLSelectElement, options: [string, string][], key: keyof State): void {
  el.replaceChildren(...options.map(([v, l]) => h("option", { value: v }, l)));
  el.addEventListener("change", () => store.set({ [key]: el.value } as Partial<State>));
}

// ---------- helpers ----------
function unitOf(variable: string): string {
  return data.meta.variables[variable]?.unit ?? "";
}

function metricValue(r: { me: number | null; mae: number | null; rmse: number | null }, m: Metric): number | null {
  return r[m];
}

function bucketRows(s: State, sample = "common"): BucketScore[] {
  return data.bucket.filter(
    (r) =>
      r.variable === s.variable &&
      r.truth_level === s.truth &&
      r.interp_method === s.method &&
      r.sample === sample &&
      r.lead_bucket === s.bucket,
  );
}

// ---------- KPIs ----------
function renderKpis(s: State): void {
  const el = $("kpis");
  const br = bucketRows(s);
  const unit = unitOf(s.variable);
  const get = (m: string) => br.find((r) => r.model_id === m);
  const tiles: HTMLElement[] = [];
  for (const m of [...MODELS, "persistence"]) {
    const r = get(m);
    const v = r ? metricValue(r, s.metric) : null;
    const ci =
      r && s.metric === "mae" && r.mae_ci_low !== null
        ? `95 % CI ${num(r.mae_ci_low, 2)}…${num(r.mae_ci_high, 2)}`
        : "CI alates 10 päevast";
    tiles.push(
      h(
        "div",
        { class: "kpi" },
        h(
          "div",
          { class: "k-label" },
          h("span", {
            class: `key-line${m === "persistence" ? " dashed" : ""}`,
            style: `border-color:${seriesColor(m)}`,
          }),
          `${METRICS[s.metric]} · ${data.meta.models[m] ?? m}`,
        ),
        h("div", { class: "k-value" }, s.metric === "me" ? signed(v, 2) : num(v, 2), h("span", { class: "k-unit" }, unit)),
        h("div", { class: "k-foot" }, r ? `n = ${r.n.toLocaleString("et-EE")} · ${r.n_days} päeva · ${ci}` : "andmed puuduvad"),
      ),
    );
  }
  const ifs = get("ifs");
  const aifs = get("aifs-single");
  const ss = (r?: BucketScore) => (r?.ss_mae_persistence ?? null);
  tiles.push(
    h(
      "div",
      { class: "kpi" },
      h("div", { class: "k-label" }, "MAE oskus persistentsi suhtes"),
      h(
        "div",
        { class: "k-value" },
        `${pct(ss(ifs))}`,
        h("span", { class: "k-unit" }, `IFS · ${pct(ss(aifs))} AIFS`),
      ),
      h("div", { class: "k-foot" }, "1 − MAE / MAE(persistents); 0 = mitte parem kui eilne ilm"),
    ),
  );
  el.replaceChildren(...tiles);
}

// ---------- map ----------
function stationScores(s: State): Map<string, StationScore[]> {
  const out = new Map<string, StationScore[]>();
  for (const r of data.station) {
    if (
      r.variable !== s.variable ||
      r.truth_level !== s.truth ||
      r.interp_method !== s.method ||
      r.lead_bucket !== s.bucket
    )
      continue;
    const list = out.get(r.station_id) ?? [];
    list.push(r);
    out.set(r.station_id, list);
  }
  return out;
}

function mapValue(list: StationScore[] | undefined, s: State): { v: number | null; n: number } {
  if (!list) return { v: null, n: 0 };
  const by = (m: string) => list.find((r) => r.model_id === m);
  if (s.mapModel === "diff") {
    const a = by("ifs");
    const b = by("aifs-single");
    const va = a ? metricValue(a, s.metric) : null;
    const vb = b ? metricValue(b, s.metric) : null;
    if (va === null || vb === null) return { v: null, n: 0 };
    const v = s.metric === "me" ? Math.abs(va) - Math.abs(vb) : va - vb;
    return { v, n: Math.min(a?.n ?? 0, b?.n ?? 0) };
  }
  const r = by(s.mapModel);
  return { v: r ? metricValue(r, s.metric) : null, n: r?.n ?? 0 };
}

function renderMap(s: State): void {
  const scores = stationScores(s);
  const values: number[] = [];
  const pts: { f: StationFeature; v: number | null; n: number }[] = [];
  for (const f of data.stations.features) {
    const { v, n } = f.properties.verified ? mapValue(scores.get(f.properties.id), s) : { v: null, n: 0 };
    if (v !== null) values.push(v);
    pts.push({ f, v, n });
  }
  const useDiv = s.metric === "me" || s.mapModel === "diff";
  const scale = useDiv
    ? diverging(niceMax(quantile(values.map(Math.abs), 0.95)))
    : sequential(niceMax(quantile(values, 0.95)));
  const maxN = Math.max(1, ...pts.map((p) => p.n));
  const points: MapPoint[] = pts.map(({ f, v, n }) => ({
    id: f.properties.id,
    name: f.properties.name,
    lon: f.geometry.coordinates[0],
    lat: f.geometry.coordinates[1],
    verified: f.properties.verified,
    color: v === null ? null : scale.color(v),
    radius: 6 + 5 * Math.sqrt(n / maxN),
    hollow: n < MIN_N_MAP,
  }));
  map.update(points, s.station);
  renderLegend(s, scale);
  const unit = unitOf(s.variable);
  const what =
    s.mapModel === "diff"
      ? `${METRICS[s.metric]} IFS − AIFS${s.metric === "me" ? " (|ME| vahe)" : ""}`
      : `${METRICS[s.metric]} · ${SHORT[s.mapModel]}`;
  $("map-hint").textContent = `${what}, ${unit} · ${BUCKET_LABEL[s.bucket] ?? s.bucket} · ${data.meta.methods[s.method] ?? s.method}. Sümboli suurus = paaride arv; õõnes = alla ${MIN_N_MAP}.`;
  renderMapTable(s, scores);
}

function renderLegend(s: State, scale: Scale): void {
  const unit = unitOf(s.variable);
  const el = $("map-legend");
  const grad = `linear-gradient(90deg, ${scale.stops.join(",")})`;
  const ticks =
    scale.kind === "div"
      ? [signed(scale.min, 1), "0", signed(scale.max, 1)]
      : [num(0, 1), num(scale.max / 2, 1), num(scale.max, 1)];
  const labels =
    s.mapModel === "diff"
      ? ["IFS parem", "AIFS parem"]
      : s.metric === "me"
        ? ["prognoos liiga madal", "liiga kõrge"]
        : ["väike viga", "suur viga"];
  el.replaceChildren(
    h("div", {}, h("strong", {}, `${METRICS[s.metric]}${s.mapModel === "diff" ? " IFS − AIFS" : ""}, ${unit}`)),
    h("div", { class: "ramp", style: `background:${grad}` }),
    h("div", { class: "ticks" }, ...ticks.map((t) => h("span", {}, t))),
    h("div", { class: "ticks muted" }, h("span", {}, labels[0] ?? ""), h("span", {}, labels[1] ?? "")),
    h(
      "div",
      { class: "sym" },
      h("span", {}, h("span", { class: "c", style: `background:${cssVar("--axis")};width:6px;height:6px` }), "kinnitamata jaam (ainult vaatlus)"),
    ),
  );
}

function renderMapTable(s: State, scores: Map<string, StationScore[]>): void {
  const el = $("map-table");
  if (el.hidden) return;
  const unit = unitOf(s.variable);
  const head = h(
    "tr",
    {},
    h("th", {}, "Jaam"),
    ...MODELS.flatMap((m) => [h("th", {}, `${SHORT[m]} ${METRICS[s.metric]}, ${unit}`), h("th", {}, `${SHORT[m]} n`)]),
  );
  const body = data.stations.features
    .filter((f) => f.properties.verified)
    .map((f) => {
      const list = scores.get(f.properties.id) ?? [];
      const tr = h(
        "tr",
        { class: "clickable", tabindex: 0 },
        h("td", {}, f.properties.name),
        ...MODELS.flatMap((m) => {
          const r = list.find((x) => x.model_id === m);
          const v = r ? metricValue(r, s.metric) : null;
          return [h("td", {}, s.metric === "me" ? signed(v, 2) : num(v, 2)), h("td", { class: "muted" }, r ? String(r.n) : "–")];
        }),
      );
      const pick = () => store.set({ station: f.properties.id });
      tr.addEventListener("click", pick);
      tr.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          pick();
        }
      });
      return tr;
    });
  el.replaceChildren(h("table", {}, h("thead", {}, head), h("tbody", {}, ...body)));
}

// Map tooltip
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
  const parts: (HTMLElement | string)[] = [h("strong", {}, p.name)];
  if (p.verified) {
    const list = stationScores(s).get(id);
    const unit = unitOf(s.variable);
    for (const m of MODELS) {
      const r = list?.find((x) => x.model_id === m);
      const v = r ? metricValue(r, s.metric) : null;
      parts.push(
        h(
          "div",
          { class: "row" },
          h("span", {}, h("span", { class: "key-line", style: `border-color:${seriesColor(m)};margin-right:6px` }), `${SHORT[m]} ${METRICS[s.metric]}`),
          h("strong", {}, `${s.metric === "me" ? signed(v, 2) : num(v, 2)} ${unit}`),
        ),
      );
    }
    const n = list?.[0]?.n;
    parts.push(h("div", { class: "muted" }, n ? `n = ${n} · ${BUCKET_LABEL[s.bucket]}` : "selles valikus paare pole"));
  } else {
    parts.push(h("div", { class: "muted" }, "Kinnitamata asukoht – skoore ei arvutata"));
  }
  const o = p.latest_obs;
  if (o) {
    parts.push(
      h(
        "div",
        { class: "muted", style: "margin-top:4px" },
        `Viimane vaatlus ${local(o.time_utc)}: ${num(o.t2m_degC, 1)} °C, tuul ${num(o.wind_speed_m_s, 1)} m/s` +
          (o.phenomenon ? `, ${o.phenomenon}` : ""),
      ),
    );
  }
  tip.replaceChildren(...parts);
  tip.hidden = false;
  const w = tip.offsetWidth;
  tip.style.left = `${Math.min(window.innerWidth - w - 8, x + 14)}px`;
  tip.style.top = `${y + 14}px`;
}

// ---------- lead chart ----------
function renderLead(s: State): void {
  const unit = unitOf(s.variable);
  const sel = data.lead.filter(
    (r) =>
      r.variable === s.variable && r.truth_level === s.truth && r.interp_method === s.method && r.sample === "common",
  );
  const series: SeriesSpec[] = [...MODELS, "persistence"].map((m) => ({
    key: m,
    name: data.meta.models[m] ?? m,
    color: seriesColor(m),
    dashed: m === "persistence",
    points: sel
      .filter((r) => r.model_id === m && r.lead_h > 0)
      .sort((a, b) => a.lead_h - b.lead_h)
      .map((r) => [r.lead_h, metricValue(r, s.metric)] as [number, number | null]),
  }));
  const el = $("lead-chart");
  if (!series.some((x) => x.points.length)) {
    clearChart(el, "Selle valiku jaoks paare veel pole");
  } else {
    leadChart(el, series, unit);
  }
  $("lead-hint").textContent =
    `${METRICS[s.metric]}, ${unit} · ${data.meta.variables[s.variable]?.label ?? s.variable} · ${data.meta.truth_levels[s.truth] ?? s.truth} · ühine valim (samad jooksud, etteanded, jaamad, tunnid). ` +
    `${data.meta.variables[s.variable]?.note ?? ""}`;
  const tbl = $("lead-table");
  if (!tbl.hidden) {
    const leads = [...new Set(sel.map((r) => r.lead_h))].sort((a, b) => a - b);
    tbl.replaceChildren(
      h(
        "table",
        {},
        h("thead", {}, h("tr", {}, h("th", {}, "Etteanne, h"), ...series.map((x) => h("th", {}, `${SHORT[x.key]}, ${unit}`)), h("th", {}, "n"))),
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
                const r = rs.find((q) => q.model_id === x.key);
                return h("td", {}, r ? (s.metric === "me" ? signed(metricValue(r, s.metric), 2) : num(metricValue(r, s.metric), 2)) : "–");
              }),
              h("td", { class: "muted" }, String(rs[0]?.n ?? "")),
            );
          }),
        ),
      ),
    );
  }
}

// ---------- scorecard ----------
function renderScorecard(s: State): void {
  const el = $("scorecard");
  const buckets = data.meta.lead_buckets;
  const vars = VAR_TABS.map(([k]) => k);
  const sel = data.diff.filter((r) => r.truth_level === s.truth && r.interp_method === s.method);
  if (!sel.length) {
    el.replaceChildren(h("p", { class: "empty" }, "Ühisel valimil pole veel võrdlusandmeid."));
    return;
  }
  const scale = diverging(0.3);
  const body = vars.map((v) =>
    h(
      "tr",
      {},
      h("td", {}, data.meta.variables[v]?.label ?? v),
      ...buckets.map((b) => {
        const r = sel.find((x) => x.variable === v && x.lead_bucket === b);
        if (!r || r.rel_diff === null) return h("td", { class: "muted", style: "text-align:center" }, "·");
        const bg = scale.color(Math.max(-0.3, Math.min(0.3, r.rel_diff)));
        const strong = Math.abs(r.rel_diff) > 0.15;
        const td = h(
          "td",
          {
            class: "cell",
            style: `background:${bg};color:${strong ? "#fff" : "var(--ink)"}`,
            title: `IFS ${num(r.mae_ifs, 2)} vs AIFS ${num(r.mae_aifs, 2)}; n = ${r.n}, ${r.n_days} päeva` +
              (r.diff_ci_low !== null ? `; 95 % CI vahe ${num(r.diff_ci_low, 2)}…${num(r.diff_ci_high, 2)}` : "; CI pole (alla 10 päeva)"),
          },
          signed(r.rel_diff * 100, 0) + " %",
        );
        if (r.significant) td.append(h("span", { class: "sig", "aria-label": "statistiliselt oluline" }, " ●"));
        return td;
      }),
    ),
  );
  el.replaceChildren(
    h(
      "div",
      { class: "table-view", style: "max-height:none" },
      h(
        "table",
        {},
        h("thead", {}, h("tr", {}, h("th", {}, "Muutuja"), ...buckets.map((b) => h("th", { style: "text-align:center" }, BUCKET_LABEL[b] ?? b)))),
        h("tbody", {}, ...body),
      ),
    ),
    h(
      "p",
      { class: "hint" },
      "(MAE_IFS − MAE_AIFS) / MAE_AIFS. Negatiivne = IFS-i viga väiksem. ● = 95 % plokk-bootstrapi vahemik ei sisalda nulli (alates 10 päevast). Hõljuta lahtril detailide nägemiseks.",
    ),
  );
}

// ---------- precipitation ----------
function renderPrecip(s: State): void {
  const el = $("precip");
  const sel = data.precip.filter((r) => r.interp_method === s.method && r.window === s.window && r.lead_bucket === s.bucket);
  $("precip-hint").textContent =
    `Ööpäev ${s.window} UTC · ${BUCKET_LABEL[s.bucket]} · tõde T2 (PR1H summa). ` +
    "Prognoosi pakkimistäpsuse tõttu on osa juhtumeid „ebamäärased“ (ADR-005) – skoorid arvutatakse kindlatel juhtudel.";
  if (!sel.length) {
    el.replaceChildren(h("p", { class: "empty" }, "Selle valiku jaoks 24 h paare veel pole."));
    return;
  }
  const thr = data.meta.precip_thresholds_mm;
  const first = (m: string) => sel.find((r) => r.model_id === m);
  const summary = h(
    "div",
    { class: "kpis", style: "margin:0" },
    ...MODELS.map((m) => {
      const r = first(m);
      return h(
        "div",
        { class: "kpi" },
        h("div", { class: "k-label" }, h("span", { class: "key-line", style: `border-color:${seriesColor(m)}` }), `${SHORT[m]} · MAE`),
        h("div", { class: "k-value" }, num(r?.mae, 2), h("span", { class: "k-unit" }, "mm")),
        h("div", { class: "k-foot" }, r ? `ME ${signed(r.me, 2)} mm · n = ${r.n}` : "–"),
      );
    }),
  );
  const table = h(
    "table",
    {},
    h(
      "thead",
      {},
      h(
        "tr",
        {},
        h("th", {}, "Lävi"),
        ...MODELS.flatMap((m) => [h("th", {}, `${SHORT[m]} POD`), h("th", {}, "FAR"), h("th", {}, "CSI"), h("th", { title: "ebamäärased juhtumid (ADR-005)" }, "ebam.")]),
        h("th", { title: "vaadeldud sündmuste arv" }, "sünd."),
      ),
    ),
    h(
      "tbody",
      {},
      ...thr.map((t) => {
        const cells = MODELS.flatMap((m) => {
          const r = sel.find((x) => x.model_id === m && x.threshold_mm === t);
          return [
            h("td", {}, num(r?.pod, 2)),
            h("td", {}, num(r?.far, 2)),
            h("td", {}, num(r?.csi, 2)),
            h("td", { class: "muted" }, r ? String(r.n_uncertain) : "–"),
          ];
        });
        const ev = sel.find((x) => x.threshold_mm === t)?.n_obs_events;
        return h("tr", {}, h("td", {}, `≥ ${num(t, 1)} mm`), ...cells, h("td", { class: "muted" }, ev === undefined ? "–" : String(ev)));
      }),
    ),
  );
  el.replaceChildren(summary, h("div", { class: "table-view", style: "margin-top:10px" }, table));
}

// ---------- station panel ----------
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

/** Forecast accumulation -> amount per step interval, plotted at the interval end. */
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

let stationToken = 0;

async function renderStation(s: State): Promise<void> {
  const el = $("station-chart");
  syncSegmented($("f-stationvar"), s.stationVar);
  if (!s.station) {
    $("station-title").textContent = "Vali jaam";
    $("station-meta").textContent = "Klõpsa kaardil jaamale või vali see kaardi tabelist.";
    clearChart(el, "Jaam valimata");
    return;
  }
  const f = stationsById.get(s.station);
  $("station-title").textContent = f?.properties.name ?? s.station;
  const p = f?.properties;
  $("station-meta").textContent = p
    ? `${p.id}${p.wmo_code ? ` · WMO ${p.wmo_code}` : ""} · ${num(f.geometry.coordinates[1], 4)} N, ${num(f.geometry.coordinates[0], 4)} E` +
      (p.height_m_EH2000 !== null ? ` · ${num(p.height_m_EH2000, 1)} m (EH2000)` : "") +
      (p.verified ? "" : " · kinnitamata asukoht")
    : "";
  const token = ++stationToken;
  const series = await loadStationSeries(s.station);
  if (token !== stationToken) return;
  if (!series) {
    clearChart(el, p?.verified ? "Aegrida puudub" : "Kinnitamata jaam: aegrida ei koostata");
    $("station-foot").textContent = "";
    return;
  }
  const obsColor = cssVar("--series-obs");
  const specs: SeriesSpec[] = [];
  let unit = "°C";
  const fcField = s.stationVar === "t2m" ? "t2m_degC" : s.stationVar === "wind" ? "wind_speed_m_s" : "mslp_hPa";
  const obsField = s.stationVar === "precip" ? "precip_1h_mm" : fcField;
  unit = s.stationVar === "t2m" ? "°C" : s.stationVar === "wind" ? "m/s" : s.stationVar === "mslp" ? "hPa" : "mm";
  if (s.stationVar === "precip") {
    specs.push({ key: "obs", name: "Vaatlus T2, mm/h", color: obsColor, kind: "bar", points: zip(series.obs.T2, obsField) });
    for (const m of MODELS) {
      const r = series.latest_run[m];
      if (r) specs.push({ key: m, name: `${SHORT[m]} viimane jooks, mm/samm`, color: seriesColor(m), kind: "bar", points: stepPrecip(r) });
    }
  } else {
    if (series.obs.T2) specs.push({ key: "T2", name: "Vaatlus T2 (kvaliteedikontrollitud)", color: obsColor, points: zip(series.obs.T2, obsField), width: 2.5 });
    if (series.obs.T1 && s.stationVar !== "mslp")
      specs.push({ key: "T1", name: "Vaatlus T1 (XML, toores)", color: obsColor, kind: "dots", points: zip(series.obs.T1, obsField) });
    for (const m of MODELS) {
      const tr = series.trace_24h[m];
      if (tr) specs.push({ key: `${m}-24`, name: `${SHORT[m]} 24–30 h ette`, color: seriesColor(m), dashed: true, width: 1.5, points: zip(tr, fcField) });
      const r = series.latest_run[m];
      if (r) specs.push({ key: m, name: `${SHORT[m]} viimane jooks`, color: seriesColor(m), points: zip(r, fcField) });
    }
  }
  const now = Date.now();
  const nowIso = new Date(now).toISOString();
  // Initial window: last 4 days of observations and the next 5 days of forecasts.
  const startIso = new Date(now - 4 * 86_400_000).toISOString();
  const endIso = new Date(now + 5 * 86_400_000).toISOString();
  if (!specs.some((x) => x.points.length)) clearChart(el, "Selle muutuja andmed puuduvad");
  else stationChart(el, { title: "", unit, series: specs, nowIso, startIso, endIso, bars: s.stationVar === "precip" });
  const runs = MODELS.map((m) => {
    const r = series.latest_run[m];
    return r?.issue_time_utc ? `${SHORT[m]} ${local(r.issue_time_utc as string)} (${r.model_cycle ?? ""})` : null;
  }).filter(Boolean);
  $("station-foot").textContent =
    `Viimased jooksud: ${runs.join(" · ") || "–"}. Prognoos: lähim maapunkt, temperatuur kõrguskorrektsiooniga. ` +
    "Katkendjoon: prognoos, mis tehti 24–30 h enne vaatlust. Kerimine/suum hiire või puutega.";
}

// ---------- status ----------
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
            { class: "state", title: `lävi ${v.threshold_hours} h` },
            h("span", { class: "dot", style: `background:${ok ? cssVar("--good") : cssVar("--critical")}` }),
            ok ? "värske" : "vananenud",
            h("span", { class: "muted", style: "font-weight:400" }, ` · ${v.age_hours === null ? "–" : `${num(v.age_hours, 1)} h`}`),
          ),
        );
      })
    : [h("p", { class: "muted" }, "Monitori olekut pole.")];
  const inv = m.inventory?.models ?? {};
  const runRows = Object.entries(m.runs).map(([k, v]) =>
    h(
      "div",
      { class: "src-row" },
      h("span", {}, m.models[k] ?? k),
      h("span", {}, `${v.n} jooksu · ${local(v.first_utc)} … ${local(v.last_utc)} · tsükkel ${v.cycles.join(", ")}`),
    ),
  );
  const invRows = Object.entries(inv).map(([k, v]) =>
    h("div", { class: "src-row" }, h("span", {}, `${SHORT[k] ?? k}: viimased 14 päeva`), h("span", {}, `${v.runs_complete}/${v.runs_expected} jooksu (${pct(v.completeness_fraction)}; arhiiv algas ${local(m.runs[k]?.first_utc)})`)),
  );
  $("status").replaceChildren(
    h("div", {}, h("h3", {}, "Allikate värskus"), ...srcRows),
    h(
      "div",
      {},
      h("h3", {}, "Arhiiv"),
      ...runRows,
      ...invRows,
      h(
        "div",
        { class: "src-row" },
        h("span", {}, "Paare"),
        h("span", {}, `${m.period.n_pairs.toLocaleString("et-EE")} · ${m.period.n_days} päeva (${local(m.period.first_valid_utc)} … ${local(m.period.last_valid_utc)})`),
      ),
    ),
    h(
      "div",
      {},
      h("h3", {}, "Metoodika lühidalt"),
      h(
        "ul",
        {},
        ...m.notes.map((n) => h("li", {}, n)),
        h("li", {}, "Punktverifitseerimine jaamas (ADR-001); 25 kinnitatud kliimajaama. Lähim maapunkt + 0,0065 K/m (ADR-006), bilineaarne ja lähim ruudupunkt diagnostikana."),
        h("li", {}, "T2 = KAURi kliimaandmestik (kvaliteedikontrollitud, ~1 päev viitega); T1 = vaatluste XML (toormõõtmine, hetktõmmis 10–30 min pärast täistundi)."),
        h("li", {}, "Persistents: vaatlus väljastusajal teadaolevast ööpäevast (valiidsusaeg − k·24 h)."),
      ),
    ),
  );
  $("attribution").replaceChildren(
    ...m.attribution.flatMap((a, i) => [i ? " · " : "", h("a", { href: a.url, rel: "noopener" }, a.text)]),
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

// ---------- wiring ----------
function syncControls(s: State): void {
  syncSegmented($("f-variable"), s.variable);
  syncSegmented($("f-metric"), s.metric);
  syncSegmented($("f-bucket"), s.bucket);
  syncSegmented($("f-mapmodel"), s.mapModel);
  syncSegmented($("f-window"), s.window);
  $<HTMLSelectElement>("f-truth").value = s.truth;
  $<HTMLSelectElement>("f-method").value = s.method;
}

function renderAll(s: State, changed?: Set<keyof State>): void {
  syncControls(s);
  const only = (...k: (keyof State)[]) => !changed || k.some((x) => changed.has(x));
  if (only("variable", "metric", "bucket", "truth", "method")) renderKpis(s);
  if (only("variable", "metric", "bucket", "truth", "method", "mapModel", "station")) renderMap(s);
  if (only("variable", "metric", "truth", "method")) renderLead(s);
  if (only("truth", "method")) renderScorecard(s);
  if (only("method", "window", "bucket")) renderPrecip(s);
  if (only("station", "stationVar")) void renderStation(s);
}

function setupTheme(): void {
  const btn = $("theme-toggle");
  btn.addEventListener("click", () => {
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
      const id = `${b.dataset.tableToggle}-table`;
      const t = $(id);
      t.hidden = !t.hidden;
      b.setAttribute("aria-pressed", String(!t.hidden));
      renderAll(store.get());
    });
  }
}

async function init(): Promise<void> {
  try {
    data = await loadSite();
  } catch (e) {
    $("freshness").textContent = "Andmete laadimine ebaõnnestus";
    $("main").prepend(h("p", { class: "empty" }, `Andmeid ei õnnestunud laadida: ${String(e)}`));
    return;
  }
  for (const f of data.stations.features) stationsById.set(f.properties.id, f);
  segmented($("f-variable"), VAR_TABS, "variable");
  segmented($("f-metric"), Object.entries(METRICS) as [string, string][], "metric");
  segmented($("f-bucket"), data.meta.lead_buckets.map((b) => [b, BUCKET_LABEL[b] ?? b]), "bucket");
  segmented(
    $("f-mapmodel"),
    [
      ["ifs", "IFS"],
      ["aifs-single", "AIFS"],
      ["diff", "IFS − AIFS"],
    ] as [MapModel, string][],
    "mapModel",
  );
  segmented($("f-stationvar"), STATION_VARS, "stationVar");
  segmented(
    $("f-window"),
    [
      ["06-06", "06–06 UTC"],
      ["00-00", "00–00 UTC"],
    ],
    "window",
  );
  fillSelect($("f-truth"), Object.entries(data.meta.truth_levels).map(([k, v]) => [k, v.split(" - ")[0] + " · " + (k === "T2" ? "kvaliteedikontrollitud" : "toores")]), "truth");
  fillSelect($("f-method"), Object.entries(data.meta.methods), "method");

  map = createMap($("map"), showStationTooltip, (id) => store.set({ station: id }));
  setupTheme();
  setupTableToggles();
  renderStatus();
  store.subscribe((s, changed) => renderAll(s, changed));
  // Default station: Tallinn-Harku when nothing chosen (most-used reference station).
  if (!store.get().station && stationsById.has("AJHARK01")) store.set({ station: "AJHARK01" });
  renderAll(store.get());
}

void init();

