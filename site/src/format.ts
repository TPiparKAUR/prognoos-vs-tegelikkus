// Formatting: Estonian number style, Estonian local time labelled EET/EEST (docs/05 §4).

const TZ = "Europe/Tallinn";

const nf = new Map<number, Intl.NumberFormat>();
export function num(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  let f = nf.get(digits);
  if (!f) {
    f = new Intl.NumberFormat("et-EE", { minimumFractionDigits: digits, maximumFractionDigits: digits });
    nf.set(digits, f);
  }
  return f.format(v);
}

export function pct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  return `${num(v * 100, digits)} %`;
}

export function signed(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${num(Math.abs(v), digits)}`;
}

/** "EET" or "EEST" for a UTC instant (offset +2 / +3 in Europe/Tallinn). */
export function tzLabel(d: Date): string {
  const part = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, timeZoneName: "shortOffset" })
    .formatToParts(d)
    .find((p) => p.type === "timeZoneName")?.value;
  return part === "GMT+3" ? "EEST" : "EET";
}

const dtf = new Intl.DateTimeFormat("et-EE", {
  timeZone: TZ,
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});
const dtfYear = new Intl.DateTimeFormat("et-EE", {
  timeZone: TZ,
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});
const utcf = new Intl.DateTimeFormat("et-EE", {
  timeZone: "UTC",
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

/** Local time with zone label, e.g. "13.11 15:20 EET". */
export function local(iso: string | null | undefined, withYear = false): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return `${(withYear ? dtfYear : dtf).format(d)} ${tzLabel(d)}`;
}

export function utc(iso: string | null | undefined): string {
  if (!iso) return "–";
  return `${utcf.format(new Date(iso))} UTC`;
}

export function hoursAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "–";
  const h = (now - new Date(iso).getTime()) / 3_600_000;
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min tagasi`;
  if (h < 48) return `${num(h, 0)} h tagasi`;
  return `${num(h / 24, 0)} päeva tagasi`;
}

/** Minimal DOM builder; text always goes through textContent (data is untrusted). */
export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, string | number | boolean | undefined> = {},
  ...children: (Node | string | null | undefined | false)[]
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === false) continue;
    if (k === "class") el.className = String(v);
    else if (k === "style") el.setAttribute("style", String(v));
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    el.append(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return el;
}

export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
