// Data contract with `pvt build-site` (src/pvt/site/build.py). All times are UTC ISO 8601.

export type Columnar = Record<string, unknown[]>;

export interface Meta {
  generated_utc: string;
  ingest_version: string;
  period: { first_valid_utc: string | null; last_valid_utc: string | null; n_pairs: number; n_days: number };
  runs: Record<string, { n: number; first_utc: string; last_utc: string; cycles: string[] }>;
  models: Record<string, string>;
  methods: Record<string, string>;
  primary_method: string;
  truth_levels: Record<string, string>;
  variables: Record<string, { label: string; unit: string; note: string }>;
  lead_buckets: string[];
  precip_thresholds_mm: number[];
  attribution: { text: string; url: string }[];
  freshness: {
    generated_at_utc: string;
    problems: string[];
    sources: Record<string, { age_hours: number | null; status: string; threshold_hours: number; latest_utc?: string; latest_complete_issue_utc?: string }>;
  } | null;
  inventory: {
    models: Record<string, { completeness_fraction: number; runs_complete: number; runs_expected: number }>;
  } | null;
  notes: string[];
}

export interface LeadScore {
  model_id: string;
  variable: string;
  truth_level: string;
  interp_method: string;
  sample: string;
  lead_h: number;
  n: number;
  n_days: number;
  me: number | null;
  mae: number | null;
  rmse: number | null;
  corr: number | null;
}

export interface BucketScore extends Omit<LeadScore, "lead_h"> {
  lead_bucket: string;
  n_stations: number;
  ss_mae_persistence: number | null;
  mae_ci_low: number | null;
  mae_ci_high: number | null;
}

export interface StationScore {
  model_id: string;
  variable: string;
  truth_level: string;
  interp_method: string;
  station_id: string;
  lead_bucket: string;
  n: number;
  n_days: number;
  me: number | null;
  mae: number | null;
  rmse: number | null;
}

export interface DiffScore {
  variable: string;
  truth_level: string;
  interp_method: string;
  lead_bucket: string;
  n: number;
  n_days: number;
  mae_ifs: number;
  mae_aifs: number;
  diff_mae: number;
  rel_diff: number | null;
  diff_ci_low: number | null;
  diff_ci_high: number | null;
  significant: boolean;
}

export interface PrecipScore {
  model_id: string;
  interp_method: string;
  window: string;
  lead_bucket: string;
  n: number;
  me: number;
  mae: number;
  n_clipped: number;
  threshold_mm: number;
  a: number;
  b: number;
  c: number;
  d: number;
  n_uncertain: number;
  n_obs_events: number;
  pod: number | null;
  far: number | null;
  csi: number | null;
  ets: number | null;
  freq_bias: number | null;
}

export interface LatestObs {
  time_utc: string;
  t2m_degC: number | null;
  wind_speed_m_s: number | null;
  wind_dir_deg: number | null;
  gust_m_s: number | null;
  precip_1h_mm: number | null;
  phenomenon: string | null;
}

export interface StationProps {
  id: string;
  name: string;
  verified: boolean;
  height_m_EH2000: number | null;
  wmo_code: string | null;
  latest_obs: LatestObs | null;
}

export interface StationFeature {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: StationProps;
}

export interface StationsGeo {
  type: "FeatureCollection";
  features: StationFeature[];
}

export interface StationSeries {
  station_id: string;
  obs: Partial<Record<"T1" | "T2", Columnar>>;
  latest_run: Record<string, Columnar & { issue_time_utc?: string; model_cycle?: string }>;
  trace_24h: Record<string, Columnar>;
}

export interface SiteData {
  meta: Meta;
  stations: StationsGeo;
  lead: LeadScore[];
  bucket: BucketScore[];
  station: StationScore[];
  diff: DiffScore[];
  precip: PrecipScore[];
}

/** Columnar JSON -> array of row objects. */
export function rows<T>(c: Columnar | Record<string, never>): T[] {
  const cols = Object.keys(c);
  const first = cols[0];
  if (first === undefined) return [];
  const n = (c[first] as unknown[]).length;
  const out: T[] = new Array(n);
  for (let i = 0; i < n; i++) {
    const r: Record<string, unknown> = {};
    for (const k of cols) r[k] = (c[k] as unknown[])[i];
    out[i] = r as T;
  }
  return out;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(new URL(path, document.baseURI), { cache: "no-cache" });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return (await res.json()) as T;
}

export async function loadSite(): Promise<SiteData> {
  const [meta, stations, lead, bucket, station, diff, precip] = await Promise.all([
    getJson<Meta>("data/meta.json"),
    getJson<StationsGeo>("data/stations.geojson"),
    getJson<Columnar>("data/scores_lead.json"),
    getJson<Columnar>("data/scores_bucket.json"),
    getJson<Columnar>("data/scores_station.json"),
    getJson<Columnar>("data/scores_diff.json"),
    getJson<Columnar>("data/scores_precip.json"),
  ]);
  return {
    meta,
    stations,
    lead: rows<LeadScore>(lead),
    bucket: rows<BucketScore>(bucket),
    station: rows<StationScore>(station),
    diff: rows<DiffScore>(diff),
    precip: rows<PrecipScore>(precip),
  };
}

const seriesCache = new Map<string, Promise<StationSeries | null>>();

export function loadStationSeries(id: string): Promise<StationSeries | null> {
  let p = seriesCache.get(id);
  if (!p) {
    p = getJson<StationSeries>(`data/station/${encodeURIComponent(id)}.json`).catch(() => null);
    seriesCache.set(id, p);
  }
  return p;
}
