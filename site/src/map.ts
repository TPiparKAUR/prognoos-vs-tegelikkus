// Station map in L-EST97 (EPSG:3301) with the Maa- ja Ruumiamet grey basemap (WMS).
// The WMS (kaart.maaamet.ee/wms/hallkaart, layer kaart_ht) offers EPSG:3301 only
// (GetCapabilities, 2026-11-13), so the map view itself is EPSG:3301. A self-hosted OSM
// land/lake outline sits underneath as fallback when the WMS is unreachable.
import "ol/ol.css";
import OlMap from "ol/Map";
import View from "ol/View";
import ImageLayer from "ol/layer/Image";
import VectorLayer from "ol/layer/Vector";
import ImageWMS from "ol/source/ImageWMS";
import VectorSource from "ol/source/Vector";
import GeoJSON from "ol/format/GeoJSON";
import Feature from "ol/Feature";
import Point from "ol/geom/Point";
import { Circle, Fill, Stroke, Style } from "ol/style";
import { register } from "ol/proj/proj4";
import { fromLonLat, get as getProjection } from "ol/proj";
import { defaults as defaultControls, Attribution } from "ol/control";
import proj4 from "proj4";
import { cssVar } from "./format";

// EPSG:3301 (Estonian Coordinate System of 1997), Lambert conformal conic on GRS80.
proj4.defs(
  "EPSG:3301",
  "+proj=lcc +lat_1=59.33333333333334 +lat_2=58 +lat_0=57.51755393055556 +lon_0=24 " +
    "+x_0=500000 +y_0=6375000 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs",
);
register(proj4);
const L_EST97 = getProjection("EPSG:3301");
L_EST97?.setExtent([40500, 5993000, 1064500, 7017000]);

const WMS_URL = "https://kaart.maaamet.ee/wms/hallkaart";
const WMS_LAYER = "kaart_ht";

export interface MapPoint {
  id: string;
  lon: number;
  lat: number;
  kind: "kliima" | "xml";
  color: string | null; // null = no value -> hollow
  radius: number;
}

export interface StationMap {
  update(points: MapPoint[], selected: string | null): void;
  restyle(): void;
}

export function createMap(
  container: HTMLElement,
  onHover: (id: string | null, x: number, y: number) => void,
  onClick: (id: string) => void,
): StationMap {
  const outline = new VectorLayer({
    source: new VectorSource({
      url: new URL("basemap/estonia.geojson", document.baseURI).href,
      format: new GeoJSON({ dataProjection: "EPSG:4326", featureProjection: "EPSG:3301" }),
    }),
    style: (f) =>
      new Style({
        fill: new Fill({ color: f.get("kind") === "lake" ? cssVar("--sea") : cssVar("--land") }),
        stroke: new Stroke({ color: cssVar("--coast"), width: 0.6 }),
      }),
  });
  const wms = new ImageLayer({
    className: "ol-layer basemap-wms",
    source: new ImageWMS({
      url: WMS_URL,
      params: { LAYERS: WMS_LAYER, VERSION: "1.1.1", FORMAT: "image/png" },
      projection: "EPSG:3301",
      ratio: 1.2,
      attributions: '© <a href="https://maaaruum.ee" target="_blank" rel="noopener">Maa- ja Ruumiamet</a>',
      crossOrigin: null,
    }),
  });
  const source = new VectorSource<Feature<Point>>();
  let selected: string | null = null;
  const stations = new VectorLayer({
    source,
    style: (f) => {
      const color = f.get("color") as string | null;
      const isSel = f.getId() === selected;
      const ring = cssVar("--surface");
      const r = f.get("radius") as number;
      return new Style({
        zIndex: isSel ? 3 : f.get("kind") === "kliima" ? 2 : 1,
        image: new Circle({
          radius: r,
          fill: new Fill({ color: color ?? ring }),
          stroke: new Stroke({ color: isSel ? cssVar("--ink") : color ? cssVar("--marker-ring") : cssVar("--axis"), width: isSel ? 3 : 1.5 }),
        }),
      });
    },
  });
  const map = new OlMap({
    target: container,
    layers: [outline, wms, stations],
    controls: defaultControls({ attribution: false }).extend([new Attribution({ collapsible: true, collapsed: true })]),
    view: new View({
      projection: "EPSG:3301",
      center: fromLonLat([25.0, 58.65], "EPSG:3301"),
      // EPSG:3301 extent of 1024 km -> zoom 0 = 4 km/px; Estonia needs ~zoom 3-4.
      zoom: 3,
      minZoom: 2,
      maxZoom: 11,
      extent: [250000, 6300000, 800000, 6650000],
    }),
  });
  // Fit Estonia once the container has a size (fitting at construction uses a 0-size map).
  const ESTONIA: [number, number, number, number] = [365000, 6375000, 745000, 6635000];
  let fitted = false;
  const fitOnce = () => {
    const size = map.getSize();
    if (fitted || !size || size[0] === 0 || size[1] === 0) return;
    map.getView().fit(ESTONIA, { padding: [12, 12, 12, 12] });
    fitted = true;
  };

  map.on("pointermove", (e) => {
    if (e.dragging) return;
    const f = map.forEachFeatureAtPixel(e.pixel, (x) => x, { layerFilter: (l) => l === stations, hitTolerance: 8 });
    const id = f ? String(f.getId()) : null;
    container.style.cursor = id ? "pointer" : "";
    const rect = container.getBoundingClientRect();
    onHover(id, rect.left + e.pixel[0]!, rect.top + e.pixel[1]!);
  });
  container.addEventListener("pointerleave", () => onHover(null, 0, 0));
  map.on("singleclick", (e) => {
    const f = map.forEachFeatureAtPixel(e.pixel, (x) => x, { layerFilter: (l) => l === stations, hitTolerance: 8 });
    if (f) onClick(String(f.getId()));
  });
  new ResizeObserver(() => {
    map.updateSize();
    fitOnce();
  }).observe(container);
  map.once("change:size", fitOnce);

  return {
    update(points, sel) {
      selected = sel;
      source.clear(true);
      source.addFeatures(
        points.map((p) => {
          const f = new Feature({ geometry: new Point(fromLonLat([p.lon, p.lat], "EPSG:3301")) });
          f.setId(p.id);
          f.setProperties({ color: p.color, radius: p.radius, kind: p.kind });
          return f;
        }),
      );
    },
    restyle() {
      outline.changed();
      stations.changed();
    },
  };
}
