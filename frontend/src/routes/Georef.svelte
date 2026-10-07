<script>
  // Place a page image on the world: pair points on the orienteering map (left)
  // with the same spots on aerial imagery (right), fit, preview, save.
  import { onMount, onDestroy, tick, untrack } from 'svelte'
  import L from 'leaflet'
  import { api } from '../lib/api.js'
  import { addBasemaps } from '../lib/basemaps.js'
  import { WarpedImage, pixelToLatLon, latLonToPixel, invert3 } from '../lib/warp.js'
  import { go } from '../lib/router.svelte.js'
  import { notify } from '../lib/stores.svelte.js'
  import { fmtScale } from '../lib/format.js'
  import { loadRoute } from '../lib/route.js'

  let { pageId } = $props()

  const METHODS = [
    { id: 'auto', label: 'Auto', hint: 'similarity for 2 points, affine for 3+' },
    { id: 'similarity', label: 'True to scale', hint: 'shift, rotate and scale only — best for clean PDF prints' },
    { id: 'affine', label: 'Affine', hint: 'also corrects stretch and shear — scans and prints' },
    { id: 'projective', label: 'Perspective', hint: 'photos of a paper map taken at an angle (4+ points)' },
  ]
  const MIN = { auto: 2, similarity: 2, affine: 3, projective: 4 }

  let ctx = $state(null), error = $state('')
  let points = $state([]) // [{x, y, lat, lon}]
  let pending = $state(null) // {x, y} or {lat, lon}: half of a pair
  let method = $state('auto')
  let fitRes = $state(null), fitErr = $state('')
  let showOverlay = $state(true), opacity = $state(0.6)
  let clip = $state(null), clipMode = $state(false), clipDraft = $state([])
  let applyAll = $state(true)
  let selected = $state(-1)
  let saving = $state(false), dirty = $state(false)
  let search = $state('')
  let guides = $state([]) // GPS routes of your runs on this map, as a guide for finding points
  let showRoute = $state(true)

  let imgEl = $state(), worldEl = $state()
  let imgMap, worldMap, overlay
  const imgLayer = L.layerGroup(), worldLayer = L.layerGroup()
  const imgRoute = L.layerGroup(), worldRoute = L.layerGroup()

  // Image pixels <-> CRS.Simple lat/lng (y grows downwards in the image).
  const toLL = (x, y) => L.latLng(-y, x)
  const fromLL = (ll) => [ll.lng, -ll.lat]
  const r1 = (v) => Math.round(v * 10) / 10
  const r7 = (v) => Math.round(v * 1e7) / 1e7

  onMount(async () => {
    try {
      ctx = await api.get(`/api/pages/${pageId}/georef`)
    } catch (e) { error = e.message; return }
    if (ctx.georef) {
      points = ctx.georef.points.map((p) => ({ ...p }))
      method = ctx.georef.requested_method
      clip = ctx.georef.clip
    }
    await tick()
    initMaps()
  })

  onDestroy(() => {
    imgMap?.remove()
    worldMap?.remove()
  })

  async function initMaps() {
    const { width: w, height: h, image_url } = ctx.page
    imgMap = L.map(imgEl, { crs: L.CRS.Simple, minZoom: -5, maxZoom: 4, zoomSnap: 0.25, attributionControl: false })
    const bounds = L.latLngBounds(toLL(0, h), toLL(w, 0))
    L.imageOverlay(image_url, bounds).addTo(imgMap)
    imgMap.fitBounds(bounds)
    imgMap.setMaxBounds(bounds.pad(0.25))
    imgLayer.addTo(imgMap)
    imgMap.on('click', onImageClick)

    worldMap = L.map(worldEl, { maxZoom: 22, zoomSnap: 0.5 })
    addBasemaps(worldMap)
    worldLayer.addTo(worldMap)
    worldMap.on('click', onWorldClick)
    imgRoute.addTo(imgMap)
    worldRoute.addTo(worldMap)
    await setInitialWorldView()
    redraw()
    loadGuides()
  }

  // Your route(s) on this map: on the aerial photo always, and on the map image once there is a fit,
  // which also shows at a glance whether the placement is right (the route should follow the paths).
  async function loadGuides() {
    const list = (ctx.runs ?? []).slice(0, 3)
    const loaded = await Promise.all(list.map((r) => loadRoute(r.activity_id).catch(() => null)))
    guides = loaded.filter((r) => r?.latlng.length)
    if (guides.length && !ctx.georef && !ctx.other_placed.length) {
      worldMap.fitBounds(L.latLngBounds(guides.flatMap((r) => r.latlng)), { padding: [20, 20] })
    }
  }

  const ROUTE_STYLE = { color: '#e6007e', weight: 3, opacity: 0.8, interactive: false }

  $effect(() => {
    const H = fitRes?.matrix, show = showRoute, list = guides
    untrack(() => {
      if (!worldMap) return
      worldRoute.clearLayers()
      imgRoute.clearLayers()
      if (!show) return
      for (const r of list) {
        L.polyline(r.latlng, ROUTE_STYLE).addTo(worldRoute)
        if (H) {
          const Hinv = invert3(H)
          L.polyline(r.latlng.map(([lat, lon]) => toLL(...latLonToPixel(Hinv, lat, lon))), ROUTE_STYLE).addTo(imgRoute)
        }
      }
    })
  })

  async function setInitialWorldView() {
    if (ctx.georef) return worldMap.fitBounds(L.latLngBounds(ctx.georef.corners))
    if (ctx.other_placed.length) return worldMap.fitBounds(L.latLngBounds(ctx.other_placed.flatMap((o) => o.corners)))
    if (ctx.map_lat != null) return worldMap.setView([ctx.map_lat, ctx.map_lon], 16)
    if (ctx.exif_lat != null) return worldMap.setView([ctx.exif_lat, ctx.exif_lon], 16)
    worldMap.setView([50.85, 4.35], 8) // Belgium
    const q = ctx.map_location || ctx.map_name
    if (q) {
      search = q
      await doSearch()
    }
  }

  async function doSearch() {
    if (!search.trim()) return
    try {
      const res = await api.get(`/api/geocode?q=${encodeURIComponent(search)}`)
      if (res.length) worldMap.setView([res[0].lat, res[0].lon], 16)
      else notify('Place not found', 'error')
    } catch (e) { notify(e.message, 'error') }
  }

  // ---------------------------------------------------------------- clicks --
  function onImageClick(e) {
    const [x, y] = fromLL(e.latlng)
    if (x < 0 || y < 0 || x > ctx.page.width || y > ctx.page.height) return
    if (clipMode) { clipDraft = [...clipDraft, [r1(x), r1(y)]]; return }
    if (pending?.lat != null) addPoint({ x: r1(x), y: r1(y), lat: pending.lat, lon: pending.lon })
    else pending = { x: r1(x), y: r1(y) }
  }

  function onWorldClick(e) {
    if (clipMode) return
    const { lat, lng } = e.latlng
    if (pending?.x != null) addPoint({ ...pending, lat: r7(lat), lon: r7(lng) })
    else pending = { lat: r7(lat), lon: r7(lng) }
  }

  function addPoint(p) {
    points = [...points, p]
    pending = null
    selected = points.length - 1
    dirty = true
  }

  function removePoint(i) {
    points = points.filter((_, j) => j !== i)
    selected = -1
    dirty = true
  }

  function selectPoint(i) {
    selected = i
    const p = points[i]
    imgMap.panTo(toLL(p.x, p.y))
    worldMap.panTo([p.lat, p.lon])
  }

  function onkeydown(e) {
    if (e.target.closest?.('input, select, textarea')) return
    if (e.key === 'Escape') { pending = null; if (clipMode) { clipMode = false; clipDraft = [] } }
    if ((e.key === 'Delete' || e.key === 'Backspace') && selected >= 0) removePoint(selected)
  }

  // ------------------------------------------------------------------- fit --
  let fitTimer
  $effect(() => {
    const pts = $state.snapshot(points), m = method
    clearTimeout(fitTimer)
    if (!ctx || pts.length < MIN[m]) {
      fitRes = null
      fitErr = ''
      return
    }
    fitTimer = setTimeout(async () => {
      try {
        fitRes = await api.post('/api/georef/fit', { width: ctx.page.width, height: ctx.page.height, dpi: ctx.page.dpi, method: m, points: pts })
        fitErr = ''
      } catch (e) {
        fitRes = null
        fitErr = e.message
      }
    }, 200)
  })

  const predicted = $derived.by(() => {
    if (!fitRes || !pending) return null
    if (pending.x != null) return { world: pixelToLatLon(fitRes.matrix, pending.x, pending.y) }
    return { image: latLonToPixel(invert3(fitRes.matrix), pending.lat, pending.lon) }
  })

  // ----------------------------------------------------------------- draw --
  const icon = (label, cls) => L.divIcon({ className: `gp-icon ${cls}`, html: `<i></i><b>${label}</b>`, iconSize: [24, 24], iconAnchor: [12, 12] })

  function redraw() {
    if (!imgMap || !worldMap) return
    imgLayer.clearLayers()
    worldLayer.clearLayers()
    points.forEach((p, i) => {
      const cls = i === selected ? 'sel' : ''
      const mi = L.marker(toLL(p.x, p.y), { icon: icon(i + 1, cls), draggable: true }).addTo(imgLayer)
      mi.on('dragend', () => {
        const [x, y] = fromLL(mi.getLatLng())
        points[i] = { ...points[i], x: r1(x), y: r1(y) }
        dirty = true
      })
      mi.on('click', () => (selected = i))
      const mw = L.marker([p.lat, p.lon], { icon: icon(i + 1, cls), draggable: true }).addTo(worldLayer)
      mw.on('dragend', () => {
        const ll = mw.getLatLng()
        points[i] = { ...points[i], lat: r7(ll.lat), lon: r7(ll.lng) }
        dirty = true
      })
      mw.on('click', () => (selected = i))
    })
    const next = points.length + 1
    if (pending?.x != null) L.marker(toLL(pending.x, pending.y), { icon: icon(next, 'pending'), interactive: false }).addTo(imgLayer)
    if (pending?.lat != null) L.marker([pending.lat, pending.lon], { icon: icon(next, 'pending'), interactive: false }).addTo(worldLayer)
    if (predicted?.world) {
      L.marker(predicted.world, { icon: icon('?', 'ghost'), interactive: false }).addTo(worldLayer)
      if (!worldMap.getBounds().pad(-0.1).contains(predicted.world)) worldMap.panTo(predicted.world)
    }
    if (predicted?.image) {
      const ll = toLL(...predicted.image)
      L.marker(ll, { icon: icon('?', 'ghost'), interactive: false }).addTo(imgLayer)
      if (!imgMap.getBounds().pad(-0.1).contains(ll)) imgMap.panTo(ll)
    }
    const poly = clipMode ? clipDraft : clip
    if (poly?.length) {
      const opts = { color: '#a626a4', weight: 2, dashArray: clipMode ? '6 4' : null, fill: !clipMode, fillOpacity: 0.04, interactive: false }
      ;(clipMode ? L.polyline : L.polygon)(poly.map(([x, y]) => toLL(x, y)), opts).addTo(imgLayer)
    }
  }

  $effect(() => {
    // Track everything the markers depend on.
    void [points.map((p) => [p.x, p.y, p.lat, p.lon]), pending, selected, predicted, clip, clipDraft.length, clipMode]
    untrack(redraw)
  })

  $effect(() => {
    const corners = fitRes?.corners, show = showOverlay, op = opacity
    const c = clipMode ? null : clip
    untrack(() => {
      if (!worldMap) return
      if (!corners || !show) { overlay?.remove(); overlay = null; return }
      if (!overlay) {
        overlay = new WarpedImage(ctx.page.image_url, ctx.page.width, ctx.page.height, corners, { opacity: op, clip: c }).addTo(worldMap)
      } else overlay.setCorners(corners).setOpacity(op).setClip(c)
    })
  })

  // ------------------------------------------------------------- outline --
  function startClip() { clipMode = true; clipDraft = []; pending = null }
  function finishClip() {
    if (clipDraft.length >= 3) { clip = clipDraft; dirty = true }
    clipMode = false
    clipDraft = []
  }
  function clearClip() { clip = null; dirty = true }

  // ---------------------------------------------------------------- save --
  async function save() {
    saving = true
    try {
      ctx = await api.put(`/api/pages/${pageId}/georef`, {
        method, points: $state.snapshot(points), clip: clip ? $state.snapshot(clip) : null,
        also_page_ids: applyAll ? ctx.same_layout_pages.map((p) => p.id) : [],
      })
      dirty = false
      notify(applyAll && ctx.same_layout_pages.length ? `Placement saved for ${ctx.same_layout_pages.length + 1} pages` : 'Placement saved')
    } catch (e) { notify(e.message, 'error') }
    saving = false
  }

  async function removePlacement() {
    if (!confirm('Remove the placement of this page?')) return
    try {
      await api.del(`/api/pages/${pageId}/georef`)
      ctx = await api.get(`/api/pages/${pageId}/georef`)
      points = []; clip = null; pending = null; dirty = false
      notify('Placement removed')
    } catch (e) { notify(e.message, 'error') }
  }

  function leave() {
    if (dirty && !confirm('Leave without saving the placement?')) return
    go(ctx?.map_id ? `/map/${ctx.map_id}` : '/inbox')
  }

  // ---------------------------------------------------------------- text --
  const step = $derived.by(() => {
    if (clipMode) return 'Click around the edge of the mapped area on the left. Finish when done; the rest (legend, margins) is hidden in the overlay.'
    if (pending?.x != null) return `Now click the same spot on the aerial photo (right).${predicted ? ' The dashed “?” is where the current fit expects it.' : ''}`
    if (pending?.lat != null) return `Now click the same spot on the orienteering map (left).${predicted ? ' The dashed “?” is where the current fit expects it.' : ''}`
    if (!points.length) return 'Click a sharp feature on the orienteering map — path junction, building corner, fence corner — then the same spot on the aerial photo. Either side can go first.'
    if (points.length < MIN[method]) return `${MIN[method] - points.length} more point${MIN[method] - points.length > 1 ? 's' : ''} for a first placement.`
    return 'Add points spread over the whole map — 4 to 6 is usually plenty. Drag markers to fine-tune; a large error shows a misplaced point.'
  })
  const resClass = (r) => (r == null ? '' : r < 3 ? 'good' : r < 8 ? 'meh' : 'bad')
  const scaleOff = $derived(fitRes?.scale && ctx?.stated_scale ? Math.abs(fitRes.scale / ctx.stated_scale - 1) : null)
</script>

<svelte:window {onkeydown} onbeforeunload={(e) => { if (dirty) e.preventDefault() }} />

{#if error}
  <main class="page"><p class="empty">{error}</p></main>
{:else if !ctx}
  <main class="page"><p class="empty">Loading…</p></main>
{:else}
  <div class="editor">
    <div class="bar">
      <button class="ghost" onclick={leave}>← {ctx.map_name ?? 'Back'}</button>
      <div class="title">
        <strong>Place on map</strong>
        <span class="muted">{ctx.file_name}{ctx.page_count > 1 ? ` · page ${ctx.page.page_no}` : ''}</span>
      </div>
      <span class="spacer"></span>
      <label class="inline">Fit
        <select bind:value={method} title={METHODS.find((m) => m.id === method)?.hint}>
          {#each METHODS as m}<option value={m.id}>{m.label}</option>{/each}
        </select>
      </label>
      {#if !clipMode}
        <button onclick={startClip} title="Hide legend and margins in the overlay">{clip ? 'Redraw outline' : 'Outline map area'}</button>
        {#if clip}<button class="ghost" onclick={clearClip}>Clear outline</button>{/if}
      {:else}
        <button class="primary" onclick={finishClip} disabled={clipDraft.length < 3}>Finish outline ({clipDraft.length})</button>
        <button onclick={() => { clipMode = false; clipDraft = [] }}>Cancel</button>
      {/if}
      {#if ctx.georef}<button class="ghost danger" onclick={removePlacement}>Remove</button>{/if}
      <button class="primary" onclick={save} disabled={!fitRes || saving || clipMode}>{saving ? 'Saving…' : dirty || !ctx.georef ? 'Save' : 'Saved ✓'}</button>
    </div>

    <p class="step">{step}</p>

    <div class="panes">
      <div class="pane">
        <div class="pane-label">Orienteering map</div>
        <div class="leaf" bind:this={imgEl}></div>
      </div>
      <div class="pane">
        <div class="pane-label">World
          <form class="search" onsubmit={(e) => { e.preventDefault(); doSearch() }}>
            <input type="search" placeholder="Go to place…" bind:value={search} />
          </form>
          {#if guides.length}
            <label class="inline route-toggle" title="The GPS route of your run{guides.length > 1 ? 's' : ''} on this map. Once the map is fitted, it is drawn on the map too: it should follow the paths you ran.">
              <input type="checkbox" bind:checked={showRoute} /> <i></i>My route
            </label>
          {/if}
        </div>
        <div class="leaf" bind:this={worldEl}></div>
        {#if fitRes}
          <div class="ovl card">
            <label class="inline"><input type="checkbox" bind:checked={showOverlay} /> Overlay</label>
            <input type="range" min="0" max="1" step="0.05" bind:value={opacity} disabled={!showOverlay} aria-label="Overlay opacity" />
          </div>
        {/if}
      </div>
    </div>

    <div class="bottom">
      <div class="stats card">
        {#if fitRes}
          <div><span class="muted">Fit</span> {METHODS.find((m) => m.id === fitRes.method)?.label} · {points.length} points</div>
          <div><span class="muted">Error (RMS)</span>
            {#if fitRes.rms_m == null}<span class="muted">exact fit — add a point to check accuracy</span>{:else}<span class={resClass(fitRes.rms_m)}>{fitRes.rms_m.toFixed(1)} m</span>{/if}</div>
          {#if fitRes.scale}
            <div><span class="muted">Implied scale</span> {fmtScale(fitRes.scale)}
              {#if ctx.stated_scale}<span class={scaleOff < 0.03 ? 'good' : scaleOff < 0.08 ? 'meh' : 'bad'}>
                (map says {fmtScale(ctx.stated_scale)}{scaleOff < 0.03 ? ' ✓' : ''})</span>{/if}</div>
          {/if}
          <div><span class="muted">Rotation</span> {Math.abs(fitRes.rotation_deg).toFixed(1)}° {fitRes.rotation_deg >= 0 ? 'clockwise' : 'anticlockwise'} from grid north</div>
        {:else if fitErr}
          <div class="bad">{fitErr}</div>
        {:else}
          <div class="muted">No placement yet.</div>
        {/if}
        {#if ctx.same_layout_pages.length}
          <label class="inline apply"><input type="checkbox" bind:checked={applyAll} />
            Also place the other {ctx.same_layout_pages.length} page{ctx.same_layout_pages.length > 1 ? 's' : ''} with the same layout</label>
        {/if}
      </div>

      {#if points.length}
        <table class="pts card">
          <thead><tr><th>#</th><th class="num">Image x, y</th><th class="num">Lat, lon</th><th class="num">Error</th><th></th></tr></thead>
          <tbody>
            {#each points as p, i}
              <tr class:sel={i === selected} onclick={() => selectPoint(i)}>
                <td>{i + 1}</td>
                <td class="num mono">{Math.round(p.x)}, {Math.round(p.y)}</td>
                <td class="num mono">{p.lat.toFixed(6)}, {p.lon.toFixed(6)}</td>
                <td class="num {resClass(fitRes?.rms_m == null ? null : fitRes?.residuals_m[i])}">
                  {fitRes && fitRes.rms_m != null && fitRes.residuals_m[i] != null ? `${fitRes.residuals_m[i].toFixed(1)} m` : '—'}</td>
                <td><button class="small ghost danger" onclick={(e) => { e.stopPropagation(); removePoint(i) }} aria-label="Delete point {i + 1}">✕</button></td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>
  </div>
{/if}

<style>
  .editor { padding: .5rem 1rem 2rem; max-width: 1800px; margin: 0 auto; }
  .bar { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; padding: .25rem 0; }
  .title { display: flex; flex-direction: column; line-height: 1.2; min-width: 0; }
  .title .muted { font-size: .85rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 40vw; }
  .inline { display: inline-flex; align-items: center; gap: .35rem; font-size: .9rem; white-space: nowrap; }
  .inline select { width: auto; }
  .step { margin: .4rem 0 .6rem; padding: .5rem .75rem; background: color-mix(in srgb, var(--accent) 9%, var(--surface)); border-radius: 6px; font-size: .92rem; }
  .panes { display: grid; grid-template-columns: 1fr 1fr; gap: .75rem; height: calc(100vh - 240px); min-height: 420px; }
  .pane { position: relative; display: flex; flex-direction: column; min-width: 0; border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; background: var(--surface); }
  .pane-label { display: flex; align-items: center; gap: .5rem; padding: .3rem .6rem; font-size: .8rem; font-weight: 600; color: var(--muted); border-bottom: 1px solid var(--border); min-height: 2.2rem; }
  .search { margin-left: auto; }
  .search input { padding: .15rem .45rem; font-size: .85rem; width: 200px; }
  .leaf { flex: 1; min-height: 0; background: #e8e6e1; cursor: crosshair; }
  .route-toggle { font-weight: 500; white-space: nowrap; }
  .route-toggle i { display: inline-block; width: 14px; height: 3px; background: #e6007e; border-radius: 2px; }
  .ovl { position: absolute; left: .6rem; bottom: 1.6rem; z-index: 500; padding: .35rem .6rem; display: flex; align-items: center; gap: .5rem; }
  .ovl input[type='range'] { width: 120px; accent-color: var(--accent); }
  .bottom { display: grid; grid-template-columns: minmax(260px, 360px) 1fr; gap: .75rem; margin-top: .75rem; align-items: start; }
  .stats { display: flex; flex-direction: column; gap: .3rem; font-size: .9rem; }
  .apply { margin-top: .4rem; white-space: normal; }
  .pts { padding: 0; border-collapse: collapse; width: 100%; font-size: .85rem; overflow: hidden; }
  .pts th { text-align: left; font-weight: 500; color: var(--muted); font-size: .75rem; padding: .35rem .6rem; border-bottom: 1px solid var(--border); }
  .pts td { padding: .25rem .6rem; border-bottom: 1px solid var(--border); cursor: pointer; }
  .pts tr.sel td { background: color-mix(in srgb, var(--accent) 12%, transparent); }
  .num { text-align: right; }
  .mono { font-family: var(--mono); font-size: .8rem; }
  .good { color: var(--ok); }
  .meh { color: var(--warn); }
  .bad { color: var(--danger); }

  :global(.gp-icon) { background: none; border: none; }
  :global(.gp-icon i) { position: absolute; left: 4px; top: 4px; width: 16px; height: 16px; border: 2px solid #a626a4; border-radius: 50%; box-shadow: 0 0 0 1px #fff; }
  :global(.gp-icon i::after) { content: ''; position: absolute; left: 6px; top: 6px; width: 2px; height: 2px; background: #a626a4; border-radius: 50%; }
  :global(.gp-icon b) { position: absolute; left: 20px; top: -8px; font: 700 12px/1 system-ui, sans-serif; color: #fff; background: #a626a4; padding: 2px 4px; border-radius: 3px; white-space: nowrap; }
  :global(.gp-icon.sel i) { border-color: #f26a1b; }
  :global(.gp-icon.sel b) { background: #f26a1b; }
  :global(.gp-icon.pending i) { border-color: #2b6cb0; border-style: solid; animation: gp-pulse 1s infinite alternate; }
  :global(.gp-icon.pending b) { background: #2b6cb0; }
  :global(.gp-icon.ghost i) { border-color: #2b6cb0; border-style: dashed; }
  :global(.gp-icon.ghost b) { background: transparent; color: #2b6cb0; text-shadow: 0 0 2px #fff; }
  @keyframes -global-gp-pulse { from { box-shadow: 0 0 0 1px #fff; } to { box-shadow: 0 0 0 5px rgb(43 108 176 / 35%); } }

  @media (max-width: 860px) {
    .panes { grid-template-columns: 1fr; height: auto; }
    .pane { height: 55vh; }
    .bottom { grid-template-columns: 1fr; }
    .search input { width: 140px; }
  }
</style>
