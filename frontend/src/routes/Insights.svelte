<script>
  // Coverage & insights: what the library covers, how fresh it is, and what to tidy up.
  import { onMount, onDestroy } from 'svelte'
  import L from 'leaflet'
  import { api } from '../lib/api.js'
  import { addBasemaps } from '../lib/basemaps.js'
  import { meta, notify } from '../lib/stores.svelte.js'
  import { fmtDate, fmtScale, label, yearsAgo } from '../lib/format.js'
  import BarChart from '../components/BarChart.svelte'

  let maps = $state([]), events = $state([]), loading = $state(true)
  let oldYears = $state(10), quietYears = $state(5)
  let mapEl = $state()
  let lmap

  // Survey age buckets: one blue hue, lighter = more recent (validated ordinal ramp).
  const AGE = [
    { key: 'lt5', label: 'Under 5 years', max: 5, color: '#86b6ef' },
    { key: '5-10', label: '5–10 years', max: 10, color: '#3987e5' },
    { key: '10-20', label: '10–20 years', max: 20, color: '#1c5cab' },
    { key: 'gt20', label: '20+ years', max: Infinity, color: '#0d366b' },
  ]
  const UNKNOWN = { key: 'unknown', label: 'Survey date unknown', color: '#9a988f' }
  const ageBucket = (m) => {
    const y = yearsAgo(m.last_survey)
    return y == null ? UNKNOWN : AGE.find((b) => y < b.max)
  }

  onMount(async () => {
    try {
      ;[maps, events] = await Promise.all([api.get('/api/maps'), api.get('/api/events')])
    } catch (e) { notify(e.message, 'error') }
    loading = false
  })
  onDestroy(() => lmap?.remove())

  // ------------------------------------------------------------- numbers --
  function areaKm2(fp) {
    // Shoelace in a local equirectangular frame: fine for a few km.
    const lat0 = fp.reduce((a, p) => a + p[0], 0) / fp.length
    const kx = 111.32 * Math.cos((lat0 * Math.PI) / 180), ky = 110.57
    let s = 0
    for (let i = 0; i < fp.length; i++) {
      const [la1, lo1] = fp[i], [la2, lo2] = fp[(i + 1) % fp.length]
      s += lo1 * kx * la2 * ky - lo2 * kx * la1 * ky
    }
    return Math.abs(s) / 2
  }

  const placed = $derived(maps.filter((m) => m.footprint))
  const located = $derived(maps.filter((m) => m.footprint || m.lat != null))
  const area = $derived(placed.reduce((a, m) => a + areaKm2(m.footprint), 0))
  const courses = $derived(events.reduce((a, e) => a + e.course_count, 0))
  const clubCount = $derived(new Set(maps.map((m) => m.club_name).filter(Boolean)).size)
  const oldest = $derived(maps.filter((m) => m.last_survey).sort((a, b) => a.last_survey.localeCompare(b.last_survey))[0])
  const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0)

  // -------------------------------------------------------------- charts --
  const eventsPerYear = $derived.by(() => {
    const years = events.map((e) => e.date && +e.date.slice(0, 4)).filter(Boolean)
    if (!years.length) return []
    const now = new Date().getFullYear()
    const out = []
    for (let y = Math.min(...years); y <= Math.max(now, ...years); y++) {
      const n = years.filter((x) => x === y).length
      out.push({ label: String(y), value: n })
    }
    return out
  })
  // Your runs (linked Strava activities and other recorded runs), by year.
  const runDates = $derived(events.flatMap((e) => e.run_dates ?? []))
  const runMaps = $derived(new Set(events.filter((e) => e.run_dates?.length).map((e) => e.map_id)).size)
  const runsPerYear = $derived.by(() => {
    const years = runDates.map((d) => +d.slice(0, 4)).filter(Boolean)
    if (!years.length) return []
    const now = new Date().getFullYear()
    const out = []
    for (let y = Math.min(...years); y <= Math.max(now, ...years); y++) {
      out.push({ label: String(y), value: years.filter((x) => x === y).length })
    }
    return out
  })
  const countBy = (list, keyFn, emptyLabel) => {
    const c = new Map()
    for (const m of list) {
      const k = keyFn(m) ?? emptyLabel
      c.set(k, (c.get(k) ?? 0) + 1)
    }
    return [...c.entries()].map(([label, value]) => ({ label, value }))
  }
  // Ranked by count; the "none" bucket always goes last so it never reads as a club.
  const lastIf = (name) => (a, b) => (a.label === name) - (b.label === name) || b.value - a.value || a.label.localeCompare(b.label)
  const perClub = $derived(countBy(maps, (m) => m.club_name, 'No club').sort(lastIf('No club')))
  const perAge = $derived([...AGE, UNKNOWN].map((b) => ({ label: b.label, value: maps.filter((m) => ageBucket(m) === b).length })).filter((d) => d.value))
  const perScale = $derived(countBy(maps, (m) => m.scale, null).filter((d) => d.label != null)
    .sort((a, b) => +a.label - +b.label).map((d) => ({ ...d, label: fmtScale(+d.label) })))
  const perType = $derived(countBy(maps, (m) => (m.map_type ? label(m.map_type) : null), 'No type').sort(lastIf('No type')))

  // --------------------------------------------------------------- lists --
  const oldSurveys = $derived(maps.filter((m) => (yearsAgo(m.last_survey) ?? -1) >= oldYears)
    .sort((a, b) => a.last_survey.localeCompare(b.last_survey)))
  const quiet = $derived(maps.filter((m) => m.last_event && yearsAgo(m.last_event) >= quietYears)
    .sort((a, b) => a.last_event.localeCompare(b.last_event)))
  const noEvents = $derived(maps.filter((m) => !m.last_event))

  const todo = $derived([
    { label: 'Need review (from the bulk import)', maps: maps.filter((m) => m.needs_review) },
    { label: 'Not placed on the map yet', maps: maps.filter((m) => !m.footprint) },
    { label: 'No location at all (not placed, no coordinates)', maps: maps.filter((m) => !m.footprint && m.lat == null) },
    { label: 'No survey date', maps: maps.filter((m) => !m.last_survey) },
    { label: 'No club', maps: maps.filter((m) => !m.club_name) },
  ])

  // ------------------------------------------------------- coverage map --
  $effect(() => {
    if (!mapEl || loading || lmap) return
    lmap = L.map(mapEl, { maxZoom: 22, zoomSnap: 0.5 })
    addBasemaps(lmap, { key: 'omaps.explorer.basemap', fallback: 'osm' })
    const group = L.featureGroup().addTo(lmap)
    for (const m of located) {
      const b = ageBucket(m)
      const tip = `${m.name} · ${m.last_survey ? `survey ${fmtDate(m.last_survey)}` : 'survey date unknown'}`
      const layer = m.footprint
        ? L.polygon(m.footprint, { color: b.color, weight: 2, fillColor: b.color, fillOpacity: 0.45 })
        : L.circleMarker([m.lat, m.lon], { radius: 7, color: '#fff', weight: 2, fillColor: b.color, fillOpacity: 1 })
      layer.bindTooltip(tip).on('click', () => (location.hash = `#/map/${m.id}`)).addTo(group)
    }
    if (group.getLayers().length) lmap.fitBounds(group.getBounds(), { padding: [30, 30], maxZoom: 14 })
    else lmap.setView([50.85, 4.35], 8)
  })
</script>

<main class="page">
  <h1>Insights</h1>
  <p class="muted lead">What your library covers, how fresh the maps are, and what is left to tidy up.</p>

  {#if loading}
    <p class="empty">Loading…</p>
  {:else if !maps.length}
    <div class="empty card">No maps yet. <a href="#/upload">Add maps</a> to see insights.</div>
  {:else}
    <section class="tiles">
      <div class="tile card"><span class="lbl">Maps</span><span class="val num">{maps.length}</span><span class="sub">{meta.counts.files ?? '–'} files</span></div>
      <div class="tile card"><span class="lbl">Placed on the map</span><span class="val num">{placed.length}</span><span class="sub">{pct(placed.length, maps.length)}% of maps</span></div>
      <div class="tile card"><span class="lbl">Mapped area</span><span class="val num">{area < 10 ? area.toFixed(1) : Math.round(area)} km²</span><span class="sub">placed maps only, overlaps counted twice</span></div>
      <div class="tile card"><span class="lbl">Events</span><span class="val num">{events.length}</span><span class="sub">{courses} courses</span></div>
      <div class="tile card"><span class="lbl">Your runs</span><span class="val num">{runDates.length}</span><span class="sub">on {runMaps} map{runMaps === 1 ? '' : 's'} · <a href="#/runs">link more</a></span></div>
      <div class="tile card"><span class="lbl">Clubs</span><span class="val num">{clubCount}</span><span class="sub">owning a map</span></div>
      <div class="tile card"><span class="lbl">Oldest survey</span><span class="val">{oldest ? fmtDate(oldest.last_survey) : '—'}</span>
        <span class="sub">{oldest ? oldest.name : `${maps.filter((m) => !m.last_survey).length} maps undated`}</span></div>
    </section>

    <section class="card block">
      <div class="row">
        <h2>Coverage by survey age</h2>
        <span class="spacer"></span>
        <span class="muted small">{located.length} of {maps.length} maps have a location · click an area to open it</span>
      </div>
      <div class="legend row" aria-label="Legend">
        {#each [...AGE, UNKNOWN] as b}<span class="key"><i style="background: {b.color}"></i>{b.label}</span>{/each}
        <span class="key"><i class="pin"></i>pin = location only</span>
      </div>
      <div class="covmap" bind:this={mapEl}></div>
    </section>

    <section class="charts">
      <div class="card"><BarChart title="Events per year" orientation="vertical" data={eventsPerYear} format={(v) => String(Math.round(v))} /></div>
      {#if runsPerYear.length}<div class="card"><BarChart title="Your runs per year" orientation="vertical" data={runsPerYear} format={(v) => String(Math.round(v))} /></div>{/if}
      <div class="card"><BarChart title="Maps by survey age" data={perAge} /></div>
      <div class="card"><BarChart title="Maps per club" data={perClub} /></div>
      <div class="card"><BarChart title="Maps per scale" data={perScale} /></div>
      <div class="card"><BarChart title="Maps per type" data={perType} /></div>
    </section>

    <section class="lists">
      <div class="card">
        <div class="row">
          <h2>Surveys older than</h2>
          <input class="years" type="number" min="1" max="60" bind:value={oldYears} aria-label="Years" />
          <span>years</span>
          <span class="spacer"></span><span class="muted num">{oldSurveys.length}</span>
        </div>
        {#if oldSurveys.length}
          <ul class="maplist">
            {#each oldSurveys as m}<li><a href="#/map/{m.id}">{m.name}</a><span class="muted num">{fmtDate(m.last_survey)} · {Math.floor(yearsAgo(m.last_survey))} y</span></li>{/each}
          </ul>
        {:else}<p class="muted small">None. {maps.filter((m) => !m.last_survey).length} maps have no survey date.</p>{/if}
      </div>

      <div class="card">
        <div class="row">
          <h2>No event in</h2>
          <input class="years" type="number" min="1" max="60" bind:value={quietYears} aria-label="Years" />
          <span>years</span>
          <span class="spacer"></span><span class="muted num">{quiet.length}</span>
        </div>
        {#if quiet.length}
          <ul class="maplist">
            {#each quiet as m}<li><a href="#/map/{m.id}">{m.name}</a><span class="muted num">last {fmtDate(m.last_event)}</span></li>{/each}
          </ul>
        {:else}<p class="muted small">None.</p>{/if}
        {#if noEvents.length}
          <details>
            <summary class="muted small">{noEvents.length} map{noEvents.length === 1 ? ' has' : 's have'} no dated event at all</summary>
            <ul class="maplist">{#each noEvents as m}<li><a href="#/map/{m.id}">{m.name}</a></li>{/each}</ul>
          </details>
        {/if}
      </div>

      <div class="card">
        <h2>To tidy up</h2>
        <ul class="todo">
          {#each todo as t}
            <li>
              <details>
                <summary><span>{t.label}</span><span class="num count" class:done={!t.maps.length}>{t.maps.length || '✓'}</span></summary>
                {#if t.maps.length}<ul class="maplist">{#each t.maps as m}<li><a href="#/map/{m.id}">{m.name}</a></li>{/each}</ul>{/if}
              </details>
            </li>
          {/each}
          <li class="inboxrow"><a href="#/inbox">Files in the inbox</a><span class="num count" class:done={!meta.counts.inbox}>{meta.counts.inbox || '✓'}</span></li>
        </ul>
      </div>
    </section>
  {/if}
</main>

<style>
  .lead { margin-bottom: 1.25rem; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: .75rem; margin-bottom: 1.25rem; }
  .tile { display: flex; flex-direction: column; gap: .1rem; padding: .8rem 1rem; }
  .lbl { font-size: .8rem; color: var(--muted); }
  .val { font-size: 1.6rem; font-weight: 700; line-height: 1.2; }
  .sub { font-size: .78rem; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .block { margin-bottom: 1.25rem; }
  .block h2, .lists h2 { margin: 0; font-size: 1.05rem; }
  .small { font-size: .85rem; }
  .legend { gap: .9rem; margin: .5rem 0 .6rem; font-size: .82rem; color: var(--text); }
  .key { display: inline-flex; align-items: center; gap: .35rem; }
  .key i { width: 14px; height: 14px; border-radius: 3px; display: inline-block; }
  .key i.pin { border-radius: 50%; background: #9a988f; box-shadow: 0 0 0 2px var(--surface), 0 0 0 3px #9a988f; width: 10px; height: 10px; }
  .covmap { height: min(55vh, 460px); border-radius: 6px; border: 1px solid var(--border); background: #e8e6e1; }
  .charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: .75rem; margin-bottom: 1.25rem; }
  .charts > :first-child { grid-column: 1 / -1; }
  .lists { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: .75rem; align-items: start; }
  .years { width: 4.2rem; padding: .15rem .35rem; }
  .maplist { list-style: none; padding: 0; margin: .6rem 0 0; max-height: 320px; overflow: auto; }
  .maplist li { display: flex; justify-content: space-between; gap: .5rem; padding: .25rem 0; border-bottom: 1px solid var(--border); font-size: .9rem; }
  .maplist li:last-child { border-bottom: 0; }
  .todo { list-style: none; padding: 0; margin: .6rem 0 0; }
  .todo > li { border-bottom: 1px solid var(--border); padding: .35rem 0; font-size: .9rem; }
  .todo summary { display: flex; justify-content: space-between; gap: .5rem; cursor: pointer; }
  .inboxrow { display: flex; justify-content: space-between; }
  .count { font-weight: 600; color: var(--warn); }
  .count.done { color: var(--ok); }
  details summary.muted { cursor: pointer; margin-top: .5rem; }
  @media (max-width: 640px) {
    .charts { grid-template-columns: 1fr; }
  }
</style>
