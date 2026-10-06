<script>
  // Where a map is, for maps published without images: its outline or a pin.
  import { onMount, onDestroy } from 'svelte'
  import L from 'leaflet'
  import { addBasemaps } from '../lib/basemaps.js'

  let { footprint = null, lat = null, lon = null } = $props()
  let el = $state()
  let map

  onMount(() => {
    map = L.map(el, { maxZoom: 20, zoomSnap: 0.5, scrollWheelZoom: false })
    addBasemaps(map, { key: 'omaps.public.basemap', fallback: 'osm' })
    if (footprint) {
      const poly = L.polygon(footprint, { color: '#a626a4', weight: 2, fillOpacity: 0.15 }).addTo(map)
      map.fitBounds(poly.getBounds(), { padding: [30, 30] })
    } else {
      L.circleMarker([lat, lon], { radius: 8, color: '#fff', weight: 2, fillColor: '#f26a1b', fillOpacity: 1 }).addTo(map)
      map.setView([lat, lon], 15)
    }
  })
  onDestroy(() => map?.remove())
</script>

<div class="leaf" bind:this={el}></div>

<style>
  .leaf { height: min(55vh, 460px); border: 1px solid var(--border); border-radius: var(--radius); background: #e8e6e1; }
</style>
