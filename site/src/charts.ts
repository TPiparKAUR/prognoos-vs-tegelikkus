// Charts (ECharts, SVG renderer): score vs lead time and the station time series.
import * as echarts from "echarts/core";
import { LineChart, BarChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  MarkAreaComponent,
  DataZoomComponent,
  AriaComponent,
} from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import type { EChartsCoreOption } from "echarts/core";
import { cssVar, local, num, utc } from "./format";

echarts.use([
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  MarkAreaComponent,
  DataZoomComponent,
  AriaComponent,
  SVGRenderer,
]);

export interface SeriesSpec {
  key: string;
  name: string;
  color: string;
  dashed?: boolean;
  points: [number | string, number | null][];
  kind?: "line" | "bar" | "dots";
  width?: number;
  band?: [number | string, number | null, number | null][]; // CI band (x, low, high)
}

const charts = new Map<HTMLElement, echarts.ECharts>();

function chartFor(el: HTMLElement): echarts.ECharts {
  let c = charts.get(el);
  if (!c) {
    c = echarts.init(el, undefined, { renderer: "svg" });
    charts.set(el, c);
    new ResizeObserver(() => c?.resize()).observe(el);
  }
  return c;
}

function chrome() {
  return {
    ink: cssVar("--ink"),
    ink2: cssVar("--ink-2"),
    muted: cssVar("--muted"),
    grid: cssVar("--grid"),
    baseline: cssVar("--baseline"),
    surface: cssVar("--surface"),
    border: cssVar("--border"),
  };
}

function tooltipBase() {
  const c = chrome();
  return {
    trigger: "axis" as const,
    backgroundColor: c.surface,
    borderColor: c.border,
    textStyle: { color: c.ink, fontSize: 12 },
    axisPointer: { type: "line" as const, lineStyle: { color: c.muted, width: 1 } },
    extraCssText: "border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.18);",
  };
}

// Tooltip rows: value first (strong), series name secondary, short line key (dataviz spec).
function row(color: string, name: string, value: string, dashed = false): string {
  const esc = (s: string) => s.replace(/[&<>"]/g, (ch) => `&#${ch.charCodeAt(0)};`);
  return `<div style="display:flex;gap:8px;align-items:center;justify-content:space-between">
    <span style="display:flex;gap:6px;align-items:center"><span style="width:14px;border-top:2px ${
      dashed ? "dashed" : "solid"
    } ${esc(color)}"></span><span style="opacity:.8">${esc(name)}</span></span><strong>${esc(value)}</strong></div>`;
}

export function leadChart(el: HTMLElement, series: SeriesSpec[], unit: string): void {
  const c = chrome();
  const chart = chartFor(el);
  const option: EChartsCoreOption = {
    animationDuration: 300,
    aria: { enabled: true },
    grid: { left: 44, right: 18, top: 40, bottom: 44 },
    legend: { top: 0, left: 0, itemWidth: 18, itemHeight: 8, textStyle: { color: c.ink2 } },
    tooltip: {
      ...tooltipBase(),
      formatter: (params: unknown) => {
        const ps = params as { axisValue: number; seriesName: string; color: string; value: [number, number | null] }[];
        if (!ps.length) return "";
        const lead = ps[0]?.axisValue ?? 0;
        const head = `<div style="margin-bottom:4px">Etteanne <strong>${lead} h</strong> (${num(lead / 24, 1)} päeva)</div>`;
        return (
          head +
          ps
            .filter((p) => p.value[1] !== null && !p.seriesName.endsWith("CI"))
            .map((p) => {
              const s = series.find((x) => x.name === p.seriesName);
              return row(s?.color ?? p.color, p.seriesName, `${num(p.value[1], 2)} ${unit}`, s?.dashed);
            })
            .join("")
        );
      },
    },
    xAxis: {
      type: "value",
      name: "Etteanne, h",
      nameLocation: "middle",
      nameGap: 28,
      min: 0,
      interval: 24,
      axisLine: { lineStyle: { color: c.baseline } },
      axisLabel: { color: c.muted },
      splitLine: { lineStyle: { color: c.grid } },
      nameTextStyle: { color: c.muted },
    },
    yAxis: {
      type: "value",
      name: "",
      axisLabel: { color: c.muted },
      splitLine: { lineStyle: { color: c.grid } },
      axisLine: { show: false },
    },
    series: series.map((s) => ({
      name: s.name,
      type: "line",
      showSymbol: s.points.length < 30,
      symbolSize: 8,
      connectNulls: false,
      data: s.points,
      lineStyle: { color: s.color, width: 2, type: s.dashed ? "dashed" : "solid" },
      itemStyle: { color: s.color, borderColor: c.surface, borderWidth: 2 },
      emphasis: { focus: "series" },
    })),
  };
  chart.setOption(option, true);
}

export interface StationChartSpec {
  title: string;
  unit: string;
  series: SeriesSpec[];
  nowIso: string;
  startIso?: string;
  endIso?: string;
  bars?: boolean;
}

export function stationChart(el: HTMLElement, spec: StationChartSpec): void {
  const c = chrome();
  const chart = chartFor(el);
  const option: EChartsCoreOption = {
    animationDuration: 300,
    aria: { enabled: true },
    grid: { left: 48, right: 16, top: 72, bottom: 64 },
    legend: { top: 0, left: 0, itemWidth: 14, itemHeight: 8, textStyle: { color: c.ink2 } },
    dataZoom: [
      { type: "inside", throttle: 50, startValue: spec.startIso, endValue: spec.endIso },
      {
        type: "slider",
        startValue: spec.startIso,
        endValue: spec.endIso,
        height: 18,
        bottom: 8,
        borderColor: c.border,
        textStyle: { color: c.muted },
        labelFormatter: (v: number) => local(new Date(v).toISOString()).replace(/ EES?T$/, ""),
      },
    ],
    tooltip: {
      ...tooltipBase(),
      formatter: (params: unknown) => {
        const ps = params as { axisValue: number; seriesName: string; color: string; value: [string, number | null] }[];
        if (!ps.length) return "";
        const iso = new Date(ps[0]?.axisValue ?? 0).toISOString();
        const head = `<div style="margin-bottom:4px"><strong>${local(iso)}</strong> <span style="opacity:.7">(${utc(iso)})</span></div>`;
        return (
          head +
          ps
            .filter((p) => p.value[1] !== null && p.value[1] !== undefined)
            .map((p) => {
              const s = spec.series.find((x) => x.name === p.seriesName);
              return row(s?.color ?? p.color, p.seriesName, `${num(p.value[1], 1)} ${spec.unit}`, s?.dashed);
            })
            .join("")
        );
      },
    },
    xAxis: {
      type: "time",
      axisLine: { lineStyle: { color: c.baseline } },
      axisLabel: {
        color: c.muted,
        hideOverlap: true,
        formatter: (v: number) => {
          const d = new Date(v);
          const s = local(d.toISOString());
          return s.replace(/ EES?T$/, "").replace(" ", "\n");
        },
      },
      splitLine: { show: true, lineStyle: { color: c.grid } },
    },
    yAxis: {
      type: "value",
      scale: !spec.bars,
      name: spec.unit,
      nameTextStyle: { color: c.muted, align: "right" },
      axisLabel: { color: c.muted },
      splitLine: { lineStyle: { color: c.grid } },
    },
    series: spec.series.map((s, i) => {
      const base = {
        name: s.name,
        data: s.points,
        emphasis: { focus: "series" },
        ...(i === 0
          ? {
              markLine: {
                silent: true,
                symbol: "none",
                label: { formatter: "praegu", color: c.muted, position: "insideEndTop" },
                lineStyle: { color: c.muted, type: "solid", width: 1 },
                data: [{ xAxis: spec.nowIso }],
              },
            }
          : {}),
      };
      if (s.kind === "bar") {
        return { ...base, type: "bar", barMaxWidth: 6, itemStyle: { color: s.color, borderRadius: [2, 2, 0, 0] } };
      }
      if (s.kind === "dots") {
        return {
          ...base,
          type: "line",
          lineStyle: { width: 0 },
          symbol: "circle",
          symbolSize: 6,
          itemStyle: { color: s.color, borderColor: c.surface, borderWidth: 1 },
        };
      }
      return {
        ...base,
        type: "line",
        showSymbol: false,
        connectNulls: false,
        lineStyle: { color: s.color, width: s.width ?? 2, type: s.dashed ? "dashed" : "solid" },
        itemStyle: { color: s.color },
      };
    }),
  };
  chart.setOption(option, true);
}

export function clearChart(el: HTMLElement, message: string): void {
  const chart = chartFor(el);
  const c = chrome();
  chart.setOption(
    {
      title: { text: message, left: "center", top: "middle", textStyle: { color: c.muted, fontSize: 13, fontWeight: 400 } },
      series: [],
      xAxis: { show: false },
      yAxis: { show: false },
    },
    true,
  );
}
