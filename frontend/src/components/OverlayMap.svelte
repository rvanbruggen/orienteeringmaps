<script>
  // Shows placed pages of a map over the base maps, one at a time, with opacity.
  // With your runs: draws the GPS route of one run, coloured by pace, either on the
  // aerial photo ("On the map") or on the map image as printed ("Map only", like Livelox).
  import { onMount, onDestroy, untrack } from 'svelte'
  import L from 'leaflet'
  import { addBasemaps } from '../lib/basemaps.js'
  import { WarpedImage, pixelsToLatLons, homography, invert3, applyH, toMerc } from '../lib/warp.js'
  import { loadRoute, colouredSegments, typicalPace, fmtPace } from '../lib/route.js'
  import { fmtDate, fmtDuration } from '../lib/format.js'

  // overlays: [{key, label, page_id, image_url, width, height, corners, clip}]
  // runs: [{activity_id, date, event_name, course_name, result_time_s}], newest first
  let { overlays = [], adjustable = true, runs = [] } = $props()
  let el = $state()
  let map, layer
  let current = $state() // selected overlay key; defaults to the first
  let opacity = $state(0.75)
  let outline = $state(true)
  let outlineLayer
  let view = $state('world') // 'world': on the aerial photo; 'paper': the map image as printed
  let runSel = $state(untrack(() => (runs[0] ? String(runs[0].activity_id) : ''))) // newest run first
  let byPace = $state(true)
  let route = $state(null), routeError = $state(''), routeLoading = $state(false)
  let routeLayer

  const active = $derived(overlays.find((o) => o.key === current) ?? overlays[0])

  onMount(() => {
    build()
  })
  onDestroy(() => map?.remove())

  // (Re)create the Leaflet map for the current view: Web Mercator for the world, flat pixels for the paper map.
  function build() {
    map?.remove()
    layer = outlineLayer = routeLayer = null
    if (view === 'paper') {
      map = L.map(el, { crs: L.CRS.Simple, minZoom: -6, maxZoom: 4, zoomSnap: 0.25, scrollWheelZoom: true, attributionControl: false })
    } else {
      map = L.map(el, { maxZoom: 22, zoomSnap: 0.5, scrollWheelZoom: true })
      addBasemaps(map)
    }
    zoomTo()
    show()
    drawRoute()
  }

  const paperBounds = (o) => [[-o.height, 0], [0, o.width]]

  function show() {
    if (!map) return
    layer?.remove()
    outlineLayer?.remove()
    const o = active
    if (!o) return
    if (view === 'paper') {
      layer = L.imageOverlay(o.image_url, paperBounds(o), { opacity: Math.max(opacity, 0.35) }).addTo(map)
      return
    }
    layer = new WarpedImage(o.image_url, o.width, o.height, o.corners, { opacity, clip: o.clip }).addTo(map)
    const ring = o.clip?.length >= 3 ? pixelsToLatLons(o.width, o.height, o.corners, o.clip) : o.corners
    if (outline) outlineLayer = L.polygon(ring, { color: '#a626a4', weight: 1.5, fill: false, dashArray: '4 4', interactive: false }).addTo(map)
  }

  // Where to draw a GPS point: as is on the world map, or through the inverse placement on the paper map.
  function projector() {
    if (view !== 'paper') return (lat, lon) => [lat, lon]
    const o = active
    const H = homography([[0, 0], [o.width, 0], [o.width, o.height], [0, o.height]], o.corners.map(([lat, lon]) => toMerc(lat, lon)))
    const Hinv = invert3(H)
    return (lat, lon) => {
      const [x, y] = applyH(Hinv, ...toMerc(lat, lon))
      return [-y, x]
    }
  }

  function drawRoute() {
    routeLayer?.remove()
    routeLayer = null
    if (!map || !route?.latlng.length || !active) return
    const renderer = L.canvas({ padding: 0.5 })
    const project = projector()
    routeLayer = L.layerGroup()
    for (const seg of colouredSegments(route, project, byPace)) {
      L.polyline(seg.points, { color: seg.colour, weight: 5, opacity: 0.85, renderer, interactive: false }).addTo(routeLayer)
    }
    const [first, last] = [route.latlng[0], route.latlng[route.latlng.length - 1]]
    L.circleMarker(project(...first), { radius: 7, color: '#fff', weight: 2, fillColor: '#2e7d32', fillOpacity: 1, renderer }).bindTooltip('Start').addTo(routeLayer)
    L.circleMarker(project(...last), { radius: 7, color: '#fff', weight: 2, fillColor: '#c62828', fillOpacity: 1, renderer }).bindTooltip('Finish').addTo(routeLayer)
    routeLayer.addTo(map)
  }

  async function pickRun(id) {
    route = null
    routeError = ''
    drawRoute()
    if (!id) return
    routeLoading = true
    try {
      const r = await loadRoute(+id)
      if (String(r.activity_id) !== runSel) return // another run was picked meanwhile
      route = r
      if (!r.latlng.length) routeError = 'Strava has no GPS track for this run.'
      drawRoute()
    } catch (e) { routeError = e.message }
    routeLoading = false
  }

  $effect(() => {
    void view
    untrack(build)
  })
  $effect(() => {
    void [active?.key, outline]
    untrack(() => { show(); if (view === 'paper') { zoomTo(); drawRoute() } })
  })
  $effect(() => {
    const o = opacity
    untrack(() => layer?.setOpacity(view === 'paper' ? Math.max(o, 0.35) : o))
  })
  $effect(() => {
    const id = runSel
    untrack(() => pickRun(id))
  })
  $effect(() => {
    void byPace
    untrack(drawRoute)
  })

  function zoomTo() {
    if (!map || !active) return
    if (view === 'paper') map.fitBounds(paperBounds(active), { padding: [10, 10] })
    else map.fitBounds(L.latLngBounds(active.corners), { padding: [20, 20] })
  }

  const med = $derived(route ? typicalPace(route) : null)
  const runLabel = (r) => `${fmtDate(r.date)} · ${r.course_name ?? r.event_name}${r.result_time_s ? ` · ${fmtDuration(r.result_time_s)}` : ''}`
</script>

<div class="wrap">
  <div class="controls row">
    {#if overlays.length > 1}
      <select bind:value={current} aria-label="Placed page">
        {#each overlays as o}<option value={o.key}>{o.label}</option>{/each}
      </select>
    {:else if active}
      <span class="muted small">{active.label}</span>
    {/if}
    <label class="inline">Opacity <input type="range" min="0" max="1" step="0.05" bind:value={opacity} /></label>
    <label class="inline"><input type="checkbox" bind:checked={outline} /> Outline</label>
    <button class="small" onclick={zoomTo}>Zoom to map</button>
    <span class="spacer"></span>
    {#if active && adjustable}<a class="btn small" href="#/place/{active.page_id}">Adjust placement</a>{/if}
  </div>
  {#if runs.length}
    <div class="controls row routes">
      <div class="seg" role="group" aria-label="View">
        <button class="small" class:on={view === 'world'} onclick={() => (view = 'world')}>On the map</button>
        <button class="small" class:on={view === 'paper'} onclick={() => (view = 'paper')}>Map only</button>
      </div>
      <select bind:value={runSel} aria-label="Your run">
        <option value="">No route</option>
        {#each runs as r (r.activity_id)}<option value={String(r.activity_id)}>{runLabel(r)}</option>{/each}
      </select>
      {#if runSel}
        <label class="inline"><input type="checkbox" bind:checked={byPace} /> Colour by pace</label>
        {#if routeLoading}<span class="muted small">Loading route…</span>{/if}
        {#if routeError}<span class="error small">{routeError}</span>{/if}
        {#if route && byPace && med}
          <span class="legend small" title="Pace compared with your typical pace on this run">
            <i style="background: hsl(120, 85%, 42%)"></i>faster
            <i style="background: hsl(60, 85%, 42%)"></i>{fmtPace(med)}
            <i style="background: hsl(0, 85%, 42%)"></i>slower
            <i style="background: #7a0019"></i>stopped
          </span>
        {/if}
      {/if}
    </div>
  {/if}
  <div class="leaf" class:paper={view === 'paper'} bind:this={el}></div>
</div>

<style>
  .wrap { border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; background: var(--surface); box-shadow: var(--shadow); }
  .controls { padding: .45rem .6rem; border-bottom: 1px solid var(--border); gap: .6rem; }
  .controls select { width: auto; max-width: 280px; }
  .inline { display: inline-flex; align-items: center; gap: .35rem; font-size: .88rem; white-space: nowrap; }
  .inline input[type='range'] { width: 110px; accent-color: var(--accent); }
  .small { font-size: .85rem; }
  .leaf { height: min(65vh, 560px); background: #e8e6e1; }
  .leaf.paper { background: #fff; }
  .routes { background: var(--surface-2); }
  .seg { display: inline-flex; }
  .seg button { border-radius: 0; }
  .seg button:first-child { border-radius: 6px 0 0 6px; }
  .seg button:last-child { border-radius: 0 6px 6px 0; margin-left: -1px; }
  .seg button.on { background: var(--text); color: var(--bg); border-color: var(--text); }
  .legend { display: inline-flex; align-items: center; gap: .3rem; color: var(--muted); }
  .legend i { display: inline-block; width: 14px; height: 5px; border-radius: 2px; margin-left: .2rem; }
  .error { color: var(--danger); }
</style>
