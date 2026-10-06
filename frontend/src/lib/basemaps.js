// Public base maps. The Flemish layers (Digitaal Vlaanderen) are the most
// detailed for Flanders: recent aerial photos (~25 cm) and the GRB, the
// large-scale reference map with every building and parcel.
import L from 'leaflet'

const VL = (svc, layer) =>
  `https://geo.api.vlaanderen.be/${svc}/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=${layer}` +
  '&STYLE=&FORMAT=image/png&TILEMATRIXSET=GoogleMapsVL&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}'
const VL_ATTR = '© <a href="https://www.vlaanderen.be/digitaal-vlaanderen">Digitaal Vlaanderen</a>'

export const BASEMAPS = [
  { id: 'vl-ortho', name: 'Aerial photo (Vlaanderen)', url: VL('OMWRGBMRVL', 'omwrgbmrvl'), attribution: VL_ATTR, maxNativeZoom: 21 },
  { id: 'esri', name: 'Satellite (Esri)', url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', attribution: 'Imagery © Esri, Maxar, Earthstar Geographics', maxNativeZoom: 19 },
  { id: 'osm', name: 'OpenStreetMap', url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors', maxNativeZoom: 19 },
  { id: 'vl-grb', name: 'GRB base map (Vlaanderen)', url: VL('GRB', 'grb_bsk'), attribution: VL_ATTR, maxNativeZoom: 21 },
]

/**
 * Add a layer switcher to a Leaflet map; returns the layers by name.
 * The choice is remembered per `key`, so the overview map and the
 * placement editor can each keep their own preferred base map.
 */
export function addBasemaps(map, { key = 'omaps.basemap', fallback = 'vl-ortho' } = {}) {
  let initial = fallback
  try { initial = localStorage.getItem(key) || fallback } catch { /* ignore */ }
  const layers = {}
  for (const b of BASEMAPS) {
    layers[b.name] = L.tileLayer(b.url, { attribution: b.attribution, maxNativeZoom: b.maxNativeZoom, maxZoom: 22, id: b.id })
  }
  const first = BASEMAPS.find((b) => b.id === initial) ?? BASEMAPS[0]
  layers[first.name].addTo(map)
  L.control.layers(layers, null, { position: 'topright' }).addTo(map)
  map.on('baselayerchange', (e) => {
    try { localStorage.setItem(key, e.layer.options.id) } catch { /* ignore */ }
  })
  return layers
}
