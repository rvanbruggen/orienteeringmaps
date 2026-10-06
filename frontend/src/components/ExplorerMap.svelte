<script>
  // All (filtered) maps on one map: outlines for placed maps, pins for maps with
  // only a location. Zoomed in, the placed map images themselves are shown.
  import { onMount, onDestroy, untrack } from 'svelte'
  import L from 'leaflet'
  import { addBasemaps } from '../lib/basemaps.js'
  import { WarpedImage } from '../lib/warp.js'
  import { go } from '../lib/router.svelte.js'
  import { fmtDate, fmtScale } from '../lib/format.js'

  // href/open: how to link to a map (the public site uses its own routes).
  let { maps = [], href = (m) => `#/map/${m.id}`, open = (m) => go(`/map/${m.id}`), storageKey = 'omaps.explorer', showUnlocated = true } = $props()

  const VIEW_KEY = untrack(() => `${storageKey}.view`)
  const IMAGES_KEY = untrack(() => `${storageKey}.images`)
  const OPACITY_KEY = untrack(() => `${storageKey}.opacity`)
  const IMAGE_MIN_ZOOM = 14
  const MAX_IMAGES = 12

  let el = $state()
  let map
  const shapes = L.featureGroup()
  const images = L.layerGroup()
  let byId = new Map() // map id -> leaflet layer
  let imageLayers = new Map() // map id -> WarpedImage
  let inView = $state([])
  let onlyInView = $state(true)
  let showImages = $state(load(IMAGES_KEY, true))
  let opacity = $state(load(OPACITY_KEY, 0.85))
  let zoom = $state(0)
  let hovered = $state(null)

  function load(key, fallback) {
    try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v) } catch { return fallback }
  }
  function save(key, v) {
    try { localStorage.setItem(key, JSON.stringify(v)) } catch { /* ignore */ }
  }

  const located = $derived(maps.filter((m) => m.footprint || m.lat != null))
  const unlocated = $derived(maps.length - located.length)
  const listed = $derived(onlyInView ? inView : located)

  onMount(() => {
    map = L.map(el, { maxZoom: 22, zoomSnap: 0.5 })
    addBasemaps(map, { key: `${untrack(() => storageKey)}.basemap`, fallback: 'osm' })
    shapes.addTo(map)
    images.addTo(map)
    const saved = load(VIEW_KEY, null)
    if (saved) map.setView(saved.center, saved.zoom)
    else map.setView([50.85, 4.35], 8)
    map.on('moveend zoomend', () => {
      save(VIEW_KEY, { center: map.getCenter(), zoom: map.getZoom() })
      zoom = map.getZoom()
      refreshView()
    })
    zoom = map.getZoom()
    draw()
    if (!saved) fitAll()
  })
  onDestroy(() => map?.remove())

  function popupHtml(m) {
    const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c])
    const facts = [m.location, m.club_name, fmtScale(m.scale), m.last_survey && `survey ${fmtDate(m.last_survey)}`, m.last_event && `last event ${fmtDate(m.last_event)}`].filter(Boolean)
    return `<a class="xp-pop" href="${esc(href(m))}">
      ${m.thumb_url ? `<img src="${esc(m.thumb_url)}" alt="">` : ''}
      <span><strong>${esc(m.name)}</strong><small>${facts.map(esc).join(' · ')}</small></span></a>`
  }

  function draw() {
    if (!map) return
    shapes.clearLayers()
    byId = new Map()
    for (const m of located) {
      let layer
      if (m.footprint) {
        layer = L.polygon(m.footprint, { color: '#a626a4', weight: 2, fillColor: '#a626a4', fillOpacity: 0.12 })
      } else {
        layer = L.circleMarker([m.lat, m.lon], { radius: 7, color: '#fff', weight: 2, fillColor: '#f26a1b', fillOpacity: 1 })
      }
      layer.bindTooltip(m.name, { direction: 'top', sticky: !!m.footprint })
      layer.bindPopup(popupHtml(m), { maxWidth: 300, minWidth: 220 })
      layer.on('mouseover', () => (hovered = m.id))
      layer.on('mouseout', () => (hovered = null))
      layer.addTo(shapes)
      byId.set(m.id, layer)
    }
    refreshView()
  }

  function refreshView() {
    if (!map) return
    const b = map.getBounds()
    inView = located.filter((m) => {
      const layer = byId.get(m.id)
      return layer && (layer.getBounds ? b.intersects(layer.getBounds()) : b.contains(layer.getLatLng()))
    })
    // Map images when zoomed in: only placed maps in view, nearest to the centre first.
    const want = new Set()
    if (showImages && map.getZoom() >= IMAGE_MIN_ZOOM) {
      const c = map.getCenter()
      inView.filter((m) => m.overlay)
        .sort((a, b2) => c.distanceTo(byId.get(a.id).getCenter()) - c.distanceTo(byId.get(b2.id).getCenter()))
        .slice(0, MAX_IMAGES).forEach((m) => want.add(m.id))
    }
    for (const [id, layer] of imageLayers) {
      if (!want.has(id)) { images.removeLayer(layer); imageLayers.delete(id) }
    }
    for (const id of want) {
      if (imageLayers.has(id)) continue
      const o = located.find((m) => m.id === id).overlay
      const layer = new WarpedImage(o.image_url, o.width, o.height, o.corners, { opacity, clip: o.clip })
      images.addLayer(layer)
      imageLayers.set(id, layer)
    }
  }

  function fitAll() {
    if (shapes.getLayers().length) map.fitBounds(shapes.getBounds(), { padding: [30, 30], maxZoom: 15 })
  }

  function focus(m) {
    const layer = byId.get(m.id)
    if (!layer) return
    if (layer.getBounds) map.fitBounds(layer.getBounds(), { padding: [40, 40] })
    else map.setView(layer.getLatLng(), 16)
    layer.openPopup()
  }

  $effect(() => {
    void located
    untrack(draw)
  })
  $effect(() => {
    const o = opacity
    save(OPACITY_KEY, o)
    untrack(() => imageLayers.forEach((layer) => layer.setOpacity(o)))
  })
  $effect(() => {
    save(IMAGES_KEY, showImages)
    untrack(refreshView)
  })
  $effect(() => {
    const id = hovered
    untrack(() => {
      for (const [mid, layer] of byId) {
        if (layer.setStyle) layer.setStyle(mid === id ? { weight: 4, fillOpacity: 0.3 } : { weight: 2, fillOpacity: layer instanceof L.Polygon ? 0.12 : 1 })
      }
    })
  })
</script>

<div class="explorer">
  <div class="mapbox">
    <div class="leaf" bind:this={el}></div>
    <div class="tools card">
      <button class="small" onclick={fitAll}>Fit all</button>
      <label class="inline"><input type="checkbox" bind:checked={showImages} /> Map images
        {#if showImages && zoom < IMAGE_MIN_ZOOM}<span class="muted">(zoom in)</span>{/if}</label>
      {#if showImages && zoom >= IMAGE_MIN_ZOOM}
        <label class="inline">Opacity <input type="range" min="0" max="1" step="0.05" bind:value={opacity} aria-label="Map image opacity" /></label>
      {/if}
    </div>
  </div>
  <aside class="card side">
    <div class="row head">
      <strong>{listed.length} map{listed.length === 1 ? '' : 's'}</strong>
      <span class="spacer"></span>
      <label class="inline"><input type="checkbox" bind:checked={onlyInView} /> in view</label>
    </div>
    {#if unlocated && showUnlocated}<p class="muted note">{unlocated} map{unlocated === 1 ? ' has' : 's have'} no location yet — place {unlocated === 1 ? 'it' : 'them'} or add coordinates.</p>{/if}
    <ul>
      {#each listed as m (m.id)}
        <li class:hover={hovered === m.id} onmouseenter={() => (hovered = m.id)} onmouseleave={() => (hovered = null)}>
          <button class="ghost item" onclick={() => focus(m)} ondblclick={() => open(m)}>
            {#if m.thumb_url}<img src={m.thumb_url} alt="" loading="lazy" />{/if}
            <span class="txt">
              <span class="nm">{m.name}</span>
              <span class="muted small">{[m.location, fmtScale(m.scale)].filter(Boolean).join(' · ')}</span>
            </span>
            <span class="dot {m.footprint ? 'placed' : 'pin'}" title={m.footprint ? 'Placed' : 'Location only'}></span>
          </button>
        </li>
      {/each}
      {#if !listed.length}<li class="muted note">No maps here. Zoom out or untick “in view”.</li>{/if}
    </ul>
  </aside>
</div>

<style>
  .explorer { display: grid; grid-template-columns: 1fr 300px; gap: .75rem; height: calc(100vh - 210px); min-height: 460px; }
  .mapbox { position: relative; border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow); }
  .leaf { position: absolute; inset: 0; background: #e8e6e1; }
  .tools { position: absolute; left: 3.2rem; top: .6rem; z-index: 500; padding: .3rem .5rem; display: flex; gap: .6rem; align-items: center; }
  .inline { display: inline-flex; align-items: center; gap: .3rem; font-size: .85rem; white-space: nowrap; }
  .inline input[type='range'] { width: 90px; accent-color: var(--accent); }
  .side { padding: 0; display: flex; flex-direction: column; min-height: 0; }
  .head { padding: .55rem .75rem; border-bottom: 1px solid var(--border); }
  .note { font-size: .82rem; padding: .5rem .75rem; margin: 0; }
  ul { list-style: none; margin: 0; padding: .25rem; overflow-y: auto; flex: 1; }
  li.hover .item { background: var(--surface-2); }
  .item { width: 100%; justify-content: flex-start; text-align: left; gap: .55rem; padding: .35rem .4rem; }
  .item img { width: 34px; height: 34px; object-fit: cover; border-radius: 4px; border: 1px solid var(--border); flex: none; }
  .txt { display: flex; flex-direction: column; min-width: 0; flex: 1; }
  .nm { font-weight: 600; overflow: hidden; text-overflow: ellipsis; }
  .small { font-size: .8rem; }
  .dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
  .dot.placed { background: #a626a4; }
  .dot.pin { background: #f26a1b; }

  :global(.xp-pop) { display: flex; gap: .6rem; align-items: center; color: inherit !important; text-decoration: none !important; }
  :global(.xp-pop img) { width: 64px; height: 64px; object-fit: cover; border-radius: 4px; flex: none; }
  :global(.xp-pop span) { display: flex; flex-direction: column; gap: .15rem; }
  :global(.xp-pop small) { color: #666; }

  @media (max-width: 860px) {
    .explorer { grid-template-columns: 1fr; height: auto; }
    .mapbox { height: 60vh; }
    .side { max-height: 40vh; }
  }
</style>
