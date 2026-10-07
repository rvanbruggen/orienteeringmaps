<script>
  // Shows placed pages of a map over the base maps, one at a time, with opacity.
  // With your runs: draws the GPS route of one run, coloured by pace, either on the
  // aerial photo ("On the map") or on the map image as printed ("Map only", like Livelox).
  // Extras per run: replay, a correction for a GPS offset ("Adjust route"), and the course's
  // controls ("Controls"), which split the run into legs with times and route efficiency.
  import { onMount, onDestroy, untrack } from 'svelte'
  import L from 'leaflet'
  import { api } from '../lib/api.js'
  import { notify } from '../lib/stores.svelte.js'
  import { addBasemaps } from '../lib/basemaps.js'
  import { WarpedImage, pixelsToLatLons, homography, invert3, applyH, toMerc, pixelToLatLon } from '../lib/warp.js'
  import { loadRoute, colouredSegments, typicalPace, fmtPace, adjustRoute, positionAt, legSplits, CONTROL_RADIUS_M } from '../lib/route.js'
  import { fmtDate, fmtDuration } from '../lib/format.js'

  // overlays: [{key, label, page_id, image_url, width, height, corners, clip}]
  // runs: [{activity_id, participation_id, date, event_name, course_id, course_name, result_time_s,
  //         route_adjust, controls}], newest first
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
  let routeLayer, controlsLayer, legLayer, replayLayer, runner, tail

  // Saved here after editing, so the page doesn't need to reload: participation id -> adjust, course id -> controls.
  let adjusts = $state({}), controlsByCourse = $state({})
  let mode = $state('') // '' | 'replay' | 'adjust' | 'controls'
  let adjDraft = $state({ dx: 0, dy: 0, rot: 0 }), step = $state(2)
  let ctrlDraft = $state([])
  let saving = $state(false)
  let selectedLeg = $state(null)
  // Replay: t is seconds since the first GPS point.
  let t = $state(0), playing = $state(false), speed = $state(30)
  let raf

  const active = $derived(overlays.find((o) => o.key === current) ?? overlays[0])
  const run = $derived(runs.find((r) => String(r.activity_id) === runSel))
  const savedAdjust = $derived(run ? (run.participation_id in adjusts ? adjusts[run.participation_id] : run.route_adjust) : null)
  const savedControls = $derived(run?.course_id ? (controlsByCourse[run.course_id] ?? run.controls ?? []) : [])
  const curAdjust = $derived(mode === 'adjust' ? adjDraft : savedAdjust)
  const curControls = $derived(mode === 'controls' ? ctrlDraft : savedControls)
  const shown = $derived(route ? adjustRoute(route, curAdjust) : null)
  const splits = $derived(shown && curControls.length >= 2 ? legSplits(shown, curControls) : null)
  const t0 = $derived(route?.time?.[0] ?? 0)
  const duration = $derived(route?.time?.length ? route.time[route.time.length - 1] - t0 : 0)

  onMount(() => {
    build()
  })
  onDestroy(() => {
    cancelAnimationFrame(raf)
    map?.remove()
  })

  // (Re)create the Leaflet map for the current view: Web Mercator for the world, flat pixels for the paper map.
  function build() {
    map?.remove()
    layer = outlineLayer = routeLayer = controlsLayer = legLayer = replayLayer = null
    if (view === 'paper') {
      map = L.map(el, { crs: L.CRS.Simple, minZoom: -6, maxZoom: 4, zoomSnap: 0.25, scrollWheelZoom: true, attributionControl: false })
    } else {
      map = L.map(el, { maxZoom: 22, zoomSnap: 0.5, scrollWheelZoom: true })
      addBasemaps(map)
    }
    map.on('click', onMapClick)
    zoomTo()
    show()
    drawAll()
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

  // Image pixels -> Web Mercator for the placed page.
  const paperH = (o) => homography([[0, 0], [o.width, 0], [o.width, o.height], [0, o.height]], o.corners.map(([lat, lon]) => toMerc(lat, lon)))

  // Where to draw a GPS point: as is on the world map, or through the inverse placement on the paper map.
  function projector() {
    if (view !== 'paper') return (lat, lon) => [lat, lon]
    const Hinv = invert3(paperH(active))
    return (lat, lon) => {
      const [x, y] = applyH(Hinv, ...toMerc(lat, lon))
      return [-y, x]
    }
  }
  // The other way: a point clicked or dragged on the map -> [lat, lon] in the world.
  function unproject(ll) {
    if (view !== 'paper') return [ll.lat, ll.lng]
    return pixelToLatLon(paperH(active), ll.lng, -ll.lat)
  }

  // ------------------------------------------------------------------ draw --
  function drawAll() {
    drawRoute()
    drawControls()
    drawLeg()
    drawReplay()
  }

  function drawRoute() {
    routeLayer?.remove()
    routeLayer = null
    if (!map || !shown?.latlng.length || !active) return
    const renderer = L.canvas({ padding: 0.5 })
    const project = projector()
    const faded = mode === 'replay'
    routeLayer = L.layerGroup()
    for (const seg of colouredSegments(shown, project, byPace)) {
      L.polyline(seg.points, { color: seg.colour, weight: 5, opacity: faded ? 0.4 : 0.85, renderer, interactive: false }).addTo(routeLayer)
    }
    const [first, last] = [shown.latlng[0], shown.latlng[shown.latlng.length - 1]]
    L.circleMarker(project(...first), { radius: 7, color: '#fff', weight: 2, fillColor: '#2e7d32', fillOpacity: 1, renderer }).bindTooltip('Start').addTo(routeLayer)
    L.circleMarker(project(...last), { radius: 7, color: '#fff', weight: 2, fillColor: '#c62828', fillOpacity: 1, renderer }).bindTooltip('Finish').addTo(routeLayer)
    routeLayer.addTo(map)
  }

  const PURPLE = '#b5179e'
  function controlIcon(i, n) {
    const kind = i === 0 ? 'start' : i === n - 1 && n > 2 ? 'finish' : 'control'
    const shape = kind === 'start'
      ? `<polygon points="13,3 24,22 2,22" fill="none" stroke="${PURPLE}" stroke-width="2.5"/>`
      : kind === 'finish'
        ? `<circle cx="13" cy="13" r="10" fill="none" stroke="${PURPLE}" stroke-width="2.5"/><circle cx="13" cy="13" r="6" fill="none" stroke="${PURPLE}" stroke-width="2.5"/>`
        : `<circle cx="13" cy="13" r="10" fill="none" stroke="${PURPLE}" stroke-width="2.5"/>`
    const label = kind === 'control' ? `<b>${i}</b>` : ''
    return L.divIcon({ className: 'omaps-ctrl', html: `<svg viewBox="0 0 26 26" width="26" height="26">${shape}</svg>${label}`, iconSize: [26, 26], iconAnchor: [13, 13] })
  }

  function drawControls() {
    controlsLayer?.remove()
    controlsLayer = null
    if (!map || !active || !curControls.length) return
    const project = projector()
    const editing = mode === 'controls'
    controlsLayer = L.layerGroup()
    const pts = curControls.map(([lat, lon]) => project(lat, lon))
    if (pts.length > 1) L.polyline(pts, { color: PURPLE, weight: 2, opacity: 0.8, interactive: false }).addTo(controlsLayer)
    pts.forEach((p, i) => {
      const mk = L.marker(p, { icon: controlIcon(i, pts.length), draggable: editing, keyboard: false, interactive: editing })
      if (editing) {
        mk.on('dragend', () => { ctrlDraft[i] = unproject(mk.getLatLng()) })
        mk.bindTooltip('Drag to move', { direction: 'top' })
      }
      mk.addTo(controlsLayer)
    })
    controlsLayer.addTo(map)
  }

  function drawLeg() {
    legLayer?.remove()
    legLayer = null
    const leg = splits?.legs.find((l) => l.k === selectedLeg)
    if (!map || !leg || !shown) return
    const project = projector()
    const pts = shown.latlng.slice(leg.from, leg.to + 1).map(([lat, lon]) => project(lat, lon))
    legLayer = L.layerGroup([
      L.polyline(pts, { color: '#fff', weight: 10, opacity: 0.9, interactive: false }),
      L.polyline(pts, { color: '#111', weight: 5, opacity: 1, interactive: false }),
    ]).addTo(map)
  }

  function drawReplay() {
    if (mode !== 'replay' || !map || !shown?.time?.length) {
      replayLayer?.remove()
      replayLayer = runner = tail = null
      return
    }
    const project = projector()
    const now = t0 + t
    const pos = positionAt(shown, now)
    const start = positionAt(shown, now - 60) // the last minute, as a tail
    const tailPts = [...shown.latlng.slice(start.i + 1, pos.i + 1), pos.latlng].map(([lat, lon]) => project(lat, lon))
    if (!replayLayer) {
      tail = L.polyline(tailPts, { color: '#1565c0', weight: 6, opacity: 0.95, interactive: false })
      runner = L.circleMarker(project(...pos.latlng), { radius: 8, color: '#fff', weight: 3, fillColor: '#1565c0', fillOpacity: 1, interactive: false })
      replayLayer = L.layerGroup([tail, runner]).addTo(map)
    } else {
      tail.setLatLngs(tailPts)
      runner.setLatLng(project(...pos.latlng))
    }
  }

  // ---------------------------------------------------------------- events --
  function onMapClick(e) {
    if (mode !== 'controls') return
    ctrlDraft = [...ctrlDraft, unproject(e.latlng)]
  }

  async function pickRun(id) {
    stopPlay()
    route = null
    routeError = ''
    selectedLeg = null
    mode = ''
    drawAll()
    if (!id) return
    routeLoading = true
    try {
      const r = await loadRoute(+id)
      if (String(r.activity_id) !== runSel) return // another run was picked meanwhile
      route = r
      t = 0
      if (!r.latlng.length) routeError = 'Strava has no GPS track for this run.'
    } catch (e) { routeError = e.message }
    routeLoading = false
  }

  function setMode(m) {
    stopPlay()
    if (m === mode) m = ''
    if (m === 'adjust') adjDraft = { dx: 0, dy: 0, rot: 0, ...(savedAdjust ?? {}) }
    if (m === 'controls') ctrlDraft = savedControls.map((p) => [...p])
    mode = m
  }

  // Replay
  function play() {
    if (t >= duration) t = 0
    playing = true
    let last = performance.now()
    const tick = (now) => {
      if (!playing) return
      t = Math.min(duration, t + ((now - last) / 1000) * speed)
      last = now
      if (t >= duration) { playing = false; return }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
  }
  function stopPlay() {
    playing = false
    cancelAnimationFrame(raf)
  }

  // Adjust route
  const nudge = (dx, dy, rot = 0) => {
    adjDraft = { dx: +(adjDraft.dx + dx).toFixed(1), dy: +(adjDraft.dy + dy).toFixed(1), rot: +(adjDraft.rot + rot).toFixed(2) }
  }
  async function saveAdjust() {
    saving = true
    try {
      const res = await api.patch(`/api/participations/${run.participation_id}`, { route_adjust: adjDraft })
      adjusts[run.participation_id] = res.route_adjust
      mode = ''
      notify(res.route_adjust ? 'Route correction saved' : 'Route correction removed')
    } catch (e) { notify(e.message, 'error') }
    saving = false
  }

  // Controls
  async function saveControls() {
    saving = true
    try {
      const res = await api.put(`/api/courses/${run.course_id}/controls`, { points: ctrlDraft })
      controlsByCourse[run.course_id] = res.control_coords ?? []
      mode = ''
      notify(`Controls saved for ${run.course_name}`)
    } catch (e) { notify(e.message, 'error') }
    saving = false
  }

  function pickLeg(leg) {
    selectedLeg = selectedLeg === leg.k ? null : leg.k
    if (selectedLeg != null && shown?.time?.length) t = shown.time[leg.from] - t0
  }

  // -------------------------------------------------------------- reactivity --
  $effect(() => {
    void view
    untrack(build)
  })
  $effect(() => {
    void [active?.key, outline]
    untrack(() => { show(); if (view === 'paper') { zoomTo(); drawAll() } })
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
    void [shown, byPace, mode]
    untrack(() => { drawRoute(); drawLeg(); replayLayer?.remove(); replayLayer = null; drawReplay() })
  })
  $effect(() => {
    void [curControls, curControls.length, mode]
    untrack(drawControls)
  })
  $effect(() => {
    void [selectedLeg, splits]
    untrack(drawLeg)
  })
  $effect(() => {
    void t
    untrack(drawReplay)
  })

  function zoomTo() {
    if (!map || !active) return
    if (view === 'paper') map.fitBounds(paperBounds(active), { padding: [10, 10] })
    else map.fitBounds(L.latLngBounds(active.corners), { padding: [20, 20] })
  }

  const med = $derived(route ? typicalPace(route) : null)
  const runLabel = (r) => `${fmtDate(r.date)} · ${r.course_name ?? r.event_name}${r.result_time_s ? ` · ${fmtDuration(r.result_time_s)}` : ''}`
  const clock = (s) => fmtDuration(Math.max(0, Math.round(s)))
  const pct = (x) => (x == null ? '' : `${x >= 0 ? '+' : ''}${Math.round(x * 100)}%`)
  const km = (m) => (m == null ? '' : m >= 1000 ? `${(m / 1000).toFixed(2).replace('.', ',')} km` : `${Math.round(m)} m`)
  const legName = (k, n) => `${k === 1 ? 'S' : k - 1}–${k === n ? 'F' : k}`
  const slowest = $derived(splits ? Math.max(...splits.legs.map((l) => l.pace ?? 0)) : 0)
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
        {#if route?.latlng.length}
          <span class="spacer"></span>
          <div class="seg" role="group" aria-label="Tools">
            <button class="small" class:on={mode === 'replay'} onclick={() => setMode('replay')} disabled={!route.time?.length}>▶ Replay</button>
            <button class="small" class:on={mode === 'adjust'} onclick={() => setMode('adjust')}
              title="Shift or turn the route to fix a GPS offset against the map">Adjust route{savedAdjust ? ' •' : ''}</button>
            <button class="small" class:on={mode === 'controls'} onclick={() => setMode('controls')} disabled={!run?.course_id}
              title={run?.course_id ? `Start, controls and finish of ${run.course_name}` : 'Link this run to a course first (Runs → Edit)'}>Controls{savedControls.length ? ` (${Math.max(0, savedControls.length - 2)})` : ''}</button>
          </div>
        {/if}
      {/if}
    </div>

    {#if mode === 'replay'}
      <div class="controls row tool">
        {#if playing}<button class="small" onclick={stopPlay}>⏸ Pause</button>{:else}<button class="small primary" onclick={play}>▶ Play</button>{/if}
        <input class="timeline" type="range" min="0" max={duration} step="1" bind:value={t} oninput={stopPlay} aria-label="Time" />
        <span class="num small">{clock(t)} / {clock(duration)}</span>
        <select bind:value={speed} aria-label="Replay speed">
          {#each [5, 10, 30, 60, 120] as s}<option value={s}>{s}×</option>{/each}
        </select>
      </div>
    {:else if mode === 'adjust'}
      <div class="controls row tool">
        <span class="small muted">Move the route onto the paths you ran:</span>
        <button class="small" onclick={() => nudge(-step, 0)} aria-label="West">←</button>
        <button class="small" onclick={() => nudge(0, step)} aria-label="North">↑</button>
        <button class="small" onclick={() => nudge(0, -step)} aria-label="South">↓</button>
        <button class="small" onclick={() => nudge(step, 0)} aria-label="East">→</button>
        <select bind:value={step} aria-label="Step">{#each [1, 2, 5, 20] as s}<option value={s}>{s} m</option>{/each}</select>
        <button class="small" onclick={() => nudge(0, 0, -0.5)} aria-label="Turn anticlockwise">⟲</button>
        <button class="small" onclick={() => nudge(0, 0, 0.5)} aria-label="Turn clockwise">⟳</button>
        <span class="num small muted">{adjDraft.dx} m E, {adjDraft.dy} m N, {adjDraft.rot}°</span>
        <span class="spacer"></span>
        <button class="small" onclick={() => (adjDraft = { dx: 0, dy: 0, rot: 0 })}>Reset</button>
        <button class="small" onclick={() => setMode('')}>Cancel</button>
        <button class="small primary" onclick={saveAdjust} disabled={saving}>Save</button>
      </div>
    {:else if mode === 'controls'}
      <div class="controls row tool">
        <span class="small muted">
          {#if !ctrlDraft.length}Click the <strong>start</strong> on the map.
          {:else if ctrlDraft.length === 1}Now click control 1, then the others in order, and last the <strong>finish</strong>.
          {:else}Click to add the next point (the last one is the <strong>finish</strong>). Drag a mark to move it; Undo removes the last.{/if}
        </span>
        <span class="spacer"></span>
        <button class="small" onclick={() => (ctrlDraft = ctrlDraft.slice(0, -1))} disabled={!ctrlDraft.length}>Undo</button>
        <button class="small" onclick={() => (ctrlDraft = [])} disabled={!ctrlDraft.length}>Clear</button>
        <button class="small" onclick={() => setMode('')}>Cancel</button>
        <button class="small primary" onclick={saveControls} disabled={saving || ctrlDraft.length === 1}>Save</button>
      </div>
    {/if}
  {/if}
  <div class="leaf" class:paper={view === 'paper'} class:picking={mode === 'controls'} bind:this={el}></div>

  {#if splits}
    <div class="splits">
      <table>
        <thead><tr>
          <th>Leg</th><th class="num">Split</th><th class="num">Time</th><th class="num">Run</th>
          <th class="num" title="Straight line between the controls">Straight</th>
          <th class="num" title="How much longer your route was than the straight line">Extra</th><th class="num">Pace</th>
        </tr></thead>
        <tbody>
          {#each splits.legs as leg (leg.k)}
            <tr class:sel={selectedLeg === leg.k} class:slow={leg.pace === slowest && splits.legs.length > 2} onclick={() => pickLeg(leg)}>
              <td>{legName(leg.k, splits.legs.length)}{#if leg.uncertain}<span class="warn" title="Your route never came within {CONTROL_RADIUS_M} m of this control (closest {leg.missDistance} m): check its position, or adjust the route"> ?</span>{/if}</td>
              <td class="num">{clock(leg.time)}</td>
              <td class="num muted">{clock(leg.total)}</td>
              <td class="num">{km(leg.run)}</td>
              <td class="num muted">{km(leg.straight)}</td>
              <td class="num" class:bad={leg.extra > 0.5}>{pct(leg.extra)}</td>
              <td class="num">{fmtPace(leg.pace)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
      <p class="hint">Click a leg to show it on the map{mode === 'replay' ? ' and jump the replay there' : ''}. A control counts as visited when your route comes within {CONTROL_RADIUS_M} m.</p>
    </div>
  {:else if route && run?.course_id && !savedControls.length && mode !== 'controls'}
    <p class="hint pad">Add the controls of {run.course_name} (button “Controls”) to see your split times per leg.</p>
  {/if}
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
  .leaf.picking { cursor: crosshair; }
  .routes { background: var(--surface-2); }
  .tool { background: color-mix(in srgb, var(--accent) 7%, var(--surface)); gap: .4rem; }
  .timeline { flex: 1 1 200px; accent-color: #1565c0; }
  .seg { display: inline-flex; }
  .seg button { border-radius: 0; }
  .seg button:first-child { border-radius: 6px 0 0 6px; }
  .seg button:last-child { border-radius: 0 6px 6px 0; }
  .seg button + button { margin-left: -1px; }
  .seg button.on { background: var(--text); color: var(--bg); border-color: var(--text); }
  .legend { display: inline-flex; align-items: center; gap: .3rem; color: var(--muted); }
  .legend i { display: inline-block; width: 14px; height: 5px; border-radius: 2px; margin-left: .2rem; }
  .error { color: var(--danger); }
  .splits { padding: .5rem .6rem; border-top: 1px solid var(--border); overflow-x: auto; }
  .splits table { border-collapse: collapse; width: 100%; font-size: .88rem; }
  .splits th { text-align: left; font-size: .75rem; color: var(--muted); font-weight: 500; padding: .2rem .5rem; }
  .splits td { padding: .25rem .5rem; border-top: 1px solid var(--border); white-space: nowrap; }
  .splits th.num, .splits td.num { text-align: right; }
  .splits tr { cursor: pointer; }
  .splits tbody tr:hover { background: var(--surface-2); }
  .splits tr.sel { background: color-mix(in srgb, var(--text) 10%, transparent); }
  .splits tr.slow td:first-child { font-weight: 700; }
  .splits .bad { color: var(--danger); }
  .splits .warn { color: var(--warn); font-weight: 700; cursor: help; }
  .hint.pad { padding: .5rem .6rem; margin: 0; border-top: 1px solid var(--border); }
  :global(.omaps-ctrl) { position: relative; }
  :global(.omaps-ctrl svg) { display: block; overflow: visible; }
  :global(.omaps-ctrl b) {
    position: absolute; left: 24px; top: -10px; color: #b5179e; font: 700 15px/1 system-ui, sans-serif;
    text-shadow: 0 0 2px #fff, 0 0 2px #fff, 0 0 2px #fff;
  }
</style>
