// Station map: MapLibre GL JS with a self-hosted vector basemap (no tile server).
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, MapLayerMouseEvent, StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// The worker is resolved relative to the library file, which bundling moves; ship it as
// an asset and point MapLibre at it explicitly.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { cssVar } from "./format";

export interface MapPoint {
  id: string;
  name: string;
  lon: number;
  lat: number;
  verified: boolean;
  color: string | null; // null = no score (hollow / gray)
  radius: number;
  hollow: boolean;
}

export interface StationMap {
  update(points: MapPoint[], selected: string | null): void;
  restyle(): void;
}

function style(): StyleSpecification {
  return {
    version: 8,
    sources: {
      base: { type: "geojson", data: new URL("basemap/estonia.geojson", document.baseURI).href, attribution: "© OpenStreetMap contributors" },
    },
    layers: [
      { id: "sea", type: "background", paint: { "background-color": cssVar("--sea") } },
      {
        id: "land",
        type: "fill",
        source: "base",
        filter: ["==", ["get", "kind"], "land"],
        paint: {
          "fill-color": ["case", ["get", "home"], cssVar("--land-home"), cssVar("--land")],
        },
      },
      {
        id: "lakes",
        type: "fill",
        source: "base",
        filter: ["==", ["get", "kind"], "lake"],
        paint: { "fill-color": cssVar("--sea") },
      },
      {
        id: "coast",
        type: "line",
        source: "base",
        filter: ["==", ["get", "kind"], "land"],
        paint: { "line-color": cssVar("--coast"), "line-width": 0.8 },
      },
      {
        id: "lake-shore",
        type: "line",
        source: "base",
        filter: ["==", ["get", "kind"], "lake"],
        paint: { "line-color": cssVar("--coast"), "line-width": 0.5 },
      },
    ],
  };
}

maplibregl.setWorkerUrl(new URL(workerUrl, document.baseURI).href);

export function createMap(
  container: HTMLElement,
  onHover: (id: string | null, x: number, y: number) => void,
  onClick: (id: string) => void,
): StationMap {
  const map = new maplibregl.Map({
    container,
    style: style(),
    bounds: [
      [21.6, 57.45],
      [28.4, 59.85],
    ],
    fitBoundsOptions: { padding: 20 },
    maxBounds: [
      [17.5, 55.5],
      [32.5, 62.0],
    ],
    attributionControl: { compact: true },
    dragRotate: false,
    pitchWithRotate: false,
  });
  map.touchZoomRotate.disableRotation();
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

  let pending: { points: MapPoint[]; selected: string | null } | null = null;
  let ready = false;

  const toGeo = (points: MapPoint[], selected: string | null) => ({
    type: "FeatureCollection" as const,
    features: points.map((p) => ({
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [p.lon, p.lat] },
      properties: {
        id: p.id,
        color: p.color ?? cssVar("--axis"),
        radius: p.radius,
        hollow: p.hollow || p.color === null,
        verified: p.verified,
        selected: p.id === selected,
      },
    })),
  });

  function addLayers(): void {
    if (!map.getSource("stations")) {
      map.addSource("stations", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    }
    const ring = cssVar("--surface");
    const ink = cssVar("--ink");
    map.addLayer({
      id: "st-unverified",
      type: "circle",
      source: "stations",
      filter: ["!", ["get", "verified"]],
      paint: {
        "circle-radius": 3,
        "circle-color": cssVar("--axis"),
        "circle-opacity": 0.7,
        "circle-stroke-color": ring,
        "circle-stroke-width": 1,
      },
    });
    map.addLayer({
      id: "st-hit",
      type: "circle",
      source: "stations",
      // Hit target larger than the mark (dataviz interaction rule): >= 24 px.
      paint: { "circle-radius": 13, "circle-opacity": 0 },
    });
    map.addLayer({
      id: "st-verified",
      type: "circle",
      source: "stations",
      filter: ["get", "verified"],
      paint: {
        "circle-radius": ["get", "radius"],
        "circle-color": ["case", ["get", "hollow"], ring, ["get", "color"]],
        "circle-stroke-color": ["case", ["get", "selected"], ink, ["get", "hollow"], ["get", "color"], ring],
        "circle-stroke-width": ["case", ["get", "selected"], 3, 2],
      },
    });
  }

  map.on("load", () => {
    ready = true;
    addLayers();
    if (pending) apply(pending.points, pending.selected);
  });

  map.on("mousemove", "st-hit", (e: MapLayerMouseEvent) => {
    const f = e.features?.[0];
    const id = (f?.properties?.id as string | undefined) ?? null;
    map.getCanvas().style.cursor = id ? "pointer" : "";
    const rect = container.getBoundingClientRect();
    onHover(id, rect.left + e.point.x, rect.top + e.point.y);
  });
  map.on("mouseleave", "st-hit", () => {
    map.getCanvas().style.cursor = "";
    onHover(null, 0, 0);
  });
  map.on("click", "st-hit", (e: MapLayerMouseEvent) => {
    const id = e.features?.[0]?.properties?.id as string | undefined;
    if (id) onClick(id);
  });

  function apply(points: MapPoint[], selected: string | null): void {
    const src = map.getSource("stations") as GeoJSONSource | undefined;
    src?.setData(toGeo(points, selected));
  }

  return {
    update(points, selected) {
      pending = { points, selected };
      if (ready) apply(points, selected);
    },
    restyle() {
      ready = false;
      map.setStyle(style());
      map.once("styledata", () => {
        ready = true;
        addLayers();
        if (pending) apply(pending.points, pending.selected);
      });
    },
  };
}
