// One-off generator of the self-hosted basemap (public/basemap/estonia.geojson).
//
// Input: GeoJSON of @geo-maps/countries-land-1km@0.6.0 and @geo-maps/earth-lakes-1km@0.6.0
// (data: (c) OpenStreetMap contributors, ODbL 1.0). Download the npm tarballs into an
// empty directory and pass the two map.geo.json paths:
//
//   node scripts/build-basemap.mjs <land.geo.json> <lakes.geo.json> public/basemap/estonia.geojson
//
// The page needs no third-party tile server: no visitor IPs leave to a map provider
// (docs/03 section 8, GDPR) and the map works offline from the Pages artifact.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import bboxClip from "@turf/bbox-clip";
import simplify from "@turf/simplify";

const [landPath, lakesPath, outPath] = process.argv.slice(2);
if (!landPath || !lakesPath || !outPath) {
  console.error("usage: build-basemap.mjs <land.geo.json> <lakes.geo.json> <out.geojson>");
  process.exit(2);
}
// lon/lat (GeoJSON order), EPSG:4326: Estonia with neighbours for context.
const BBOX = [19.5, 56.6, 30.5, 61.0];
const TOLERANCE_DEG = 0.004; // ~0.25-0.45 km; enough for a national overview map
const MIN_LAKE_EXTENT_DEG = 0.03;

const round = (geom) => JSON.parse(JSON.stringify(geom, (k, v) => (typeof v === "number" ? Math.round(v * 1e4) / 1e4 : v)));

function features(path) {
  const gj = JSON.parse(readFileSync(path, "utf8"));
  if (gj.type === "FeatureCollection") return gj.features;
  return gj.geometries.map((g) => ({ type: "Feature", properties: {}, geometry: g }));
}

function clipAll(feats, kind) {
  const out = [];
  for (const f of feats) {
    if (!f.geometry || !/Polygon/.test(f.geometry.type)) continue;
    // Split multipolygons so each part is clipped and filtered on its own.
    const parts = f.geometry.type === "MultiPolygon" ? f.geometry.coordinates : [f.geometry.coordinates];
    for (const coords of parts) {
      const ring = coords[0];
      let minX = 180, minY = 90, maxX = -180, maxY = -90;
      for (const [x, y] of ring) { minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y); }
      if (maxX < BBOX[0] || minX > BBOX[2] || maxY < BBOX[1] || minY > BBOX[3]) continue;
      if (kind === "lake" && Math.max(maxX - minX, maxY - minY) < MIN_LAKE_EXTENT_DEG) continue;
      const props = kind === "land" ? { kind, home: f.properties?.A3 === "EST" } : { kind };
      const poly = { type: "Feature", properties: props, geometry: { type: "Polygon", coordinates: coords } };
      const clipped = bboxClip(poly, BBOX);
      const rings = clipped.geometry.coordinates.filter((r) => r.length >= 4);
      if (!rings.length) continue;
      clipped.geometry.coordinates = rings;
      const s = simplify(clipped, { tolerance: TOLERANCE_DEG, highQuality: true });
      if (s.geometry.coordinates[0]?.length >= 4) out.push({ ...s, geometry: round(s.geometry) });
    }
  }
  return out;
}

const land = clipAll(features(landPath), "land");
const lakes = clipAll(features(lakesPath), "lake");
const fc = {
  type: "FeatureCollection",
  attribution: "(c) OpenStreetMap contributors, ODbL 1.0 (via @geo-maps 0.6.0)",
  features: [...land, ...lakes],
};
mkdirSync(dirname(outPath), { recursive: true });
writeFileSync(outPath, JSON.stringify(fc));
console.log(`land polygons ${land.length}, lakes ${lakes.length} -> ${outPath}`);
