<script>
  import { onMount } from 'svelte'
  import { api, pick, uploadFile, MAP_KEYS, VERSION_KEYS, EVENT_KEYS, COURSE_KEYS } from '../lib/api.js'
  import { go } from '../lib/router.svelte.js'
  import { meta, notify, refreshMeta } from '../lib/stores.svelte.js'
  import { fmtBytes, fmtContour, fmtDate, fmtDistance, fmtDuration, fmtKm, fmtScale, isPartialDate, label, PUBLISH_LEVELS } from '../lib/format.js'
  import Lightbox from '../components/Lightbox.svelte'
  import MapFields from '../components/MapFields.svelte'
  import VersionFields from '../components/VersionFields.svelte'
  import EventFields from '../components/EventFields.svelte'
  import CourseFields from '../components/CourseFields.svelte'
  import OverlayMap from '../components/OverlayMap.svelte'

  let { id } = $props()
  let map = $state(null)
  let error = $state('')

  // Only one thing is edited at a time: {kind: 'map'|'version'|'event'|'course', id?, parentId?, data}
  let edit = $state(null)
  let lb = $state({ open: false, pages: [], index: 0, title: '' })
  let busy = $state(false)

  let allMaps = $state([])
  async function load() {
    try { map = await api.get(`/api/maps/${id}`) } catch (e) { error = e.message }
    api.get('/api/maps').then((list) => (allMaps = list)).catch(() => {})
  }

  // ----------------------------------------------------------- nearby maps --
  const NEARBY_KM = 3
  const centre = (m) => m.footprint
    ? [m.footprint.reduce((a, p) => a + p[0], 0) / m.footprint.length, m.footprint.reduce((a, p) => a + p[1], 0) / m.footprint.length]
    : m.lat != null ? [m.lat, m.lon] : null
  const bbox = (fp) => fp && [Math.min(...fp.map((p) => p[0])), Math.min(...fp.map((p) => p[1])), Math.max(...fp.map((p) => p[0])), Math.max(...fp.map((p) => p[1]))]
  const km = ([a, b], [c, d]) => {
    const r = Math.PI / 180, x = (d - b) * r * Math.cos(((a + c) / 2) * r), y = (c - a) * r
    return Math.sqrt(x * x + y * y) * 6371
  }
  const nearby = $derived.by(() => {
    const me = allMaps.find((m) => m.id === id)
    const c = me && centre(me)
    if (!c) return []
    const mb = bbox(me.footprint)
    return allMaps.filter((m) => m.id !== id).map((m) => {
      const oc = centre(m)
      if (!oc) return null
      const ob = bbox(m.footprint)
      const overlaps = !!(mb && ob && mb[0] <= ob[2] && ob[0] <= mb[2] && mb[1] <= ob[3] && ob[1] <= mb[3])
      return { ...m, km: km(c, oc), overlaps }
    }).filter((m) => m && (m.overlaps || m.km <= NEARBY_KM)).sort((a, b) => a.km - b.km)
  })
  onMount(load)

  const allFiles = $derived(map ? map.versions.flatMap((v) => v.files) : [])
  const overlays = $derived(map ? map.versions.flatMap((v) => v.files.flatMap((f) => f.pages.filter((p) => p.georef).map((p) => ({
    key: p.id, page_id: p.id, image_url: p.image_url, width: p.width, height: p.height,
    corners: p.georef.corners, clip: p.georef.clip,
    label: `${versionTitle(v)} · ${f.original_name}${f.page_count > 1 ? ` · p${p.page_no}` : ''}`,
  })))) : [])
  const firstPlaceable = $derived(allFiles.find((f) => f.kind !== 'manual' && f.pages.length))
  const hero = $derived(map?.versions.flatMap((v) => v.files).find((f) => f.kind !== 'manual' && f.pages.length))

  // ------------------------------------------------------------- timeline --
  const timeline = $derived.by(() => {
    if (!map) return null
    const items = []
    for (const v of map.versions) {
      if (v.survey_date) items.push({ year: +v.survey_date.slice(0, 4), kind: 'survey', label: `Survey ${fmtDate(v.survey_date)}` })
      for (const e of v.events) if (e.date) items.push({ year: +e.date.slice(0, 4), kind: 'event', label: `${e.name} · ${fmtDate(e.date)}` })
    }
    if (!items.length) return null
    const min = Math.min(...items.map((i) => i.year)), max = Math.max(...items.map((i) => i.year), new Date().getFullYear())
    const span = Math.max(1, max - min)
    return { min, max, items: items.map((i) => ({ ...i, x: ((i.year - min) / span) * 100 })) }
  })

  // ----------------------------------------------------------------- edit --
  function startEdit(kind, data, extra = {}) {
    edit = { kind, data: $state.snapshot(data), ...extra }
  }

  const editValid = $derived.by(() => {
    if (!edit) return false
    const d = edit.data
    if (edit.kind === 'map') return !!d.name?.trim()
    if (edit.kind === 'version') return isPartialDate(d.survey_date)
    if (edit.kind === 'event') return !!d.name?.trim() && isPartialDate(d.date) && isPartialDate(d.end_date)
    if (edit.kind === 'course') return !!d.name?.trim()
    return true
  })

  async function saveEdit() {
    const { kind, data: d } = edit
    busy = true
    try {
      if (kind === 'map') await api.patch(`/api/maps/${id}`, pick(d, MAP_KEYS))
      else if (kind === 'version') {
        if (d.id) await api.patch(`/api/versions/${d.id}`, pick(d, VERSION_KEYS))
        else await api.post(`/api/maps/${id}/versions`, pick(d, VERSION_KEYS))
      } else if (kind === 'event') {
        if (d.id) await api.patch(`/api/events/${d.id}`, pick(d, EVENT_KEYS))
        else await api.post(`/api/versions/${edit.parentId}/events`, pick(d, EVENT_KEYS))
      } else if (kind === 'course') {
        if (d.id) await api.patch(`/api/courses/${d.id}`, pick(d, COURSE_KEYS))
        else await api.post(`/api/events/${edit.parentId}/courses`, pick(d, COURSE_KEYS))
      }
      edit = null
      await load()
    } catch (e) { notify(e.message, 'error') }
    busy = false
  }

  async function act(fn, msg) {
    busy = true
    try { await fn(); await load(); await refreshMeta(); if (msg) notify(msg) } catch (e) { notify(e.message, 'error') }
    busy = false
  }

  const removeMap = () => confirm(`Delete map “${map.name}” with all its versions, events and courses?\nIts files go back to the inbox.`) &&
    act(async () => { await api.del(`/api/maps/${id}`); await refreshMeta(); go('/') })
  const removeVersion = (v) => confirm('Delete this version and its events? Its files go back to the inbox.') && act(() => api.del(`/api/versions/${v.id}`))
  const removeEvent = (e) => confirm(`Delete event “${e.name}” and its courses?`) && act(() => api.del(`/api/events/${e.id}`))
  const removeCourse = (c) => confirm(`Delete course “${c.name}”?`) && act(() => api.del(`/api/courses/${c.id}`))
  const detachFile = (f) => confirm(`Move “${f.original_name}” back to the inbox?`) && act(() => api.patch(`/api/files/${f.id}`, { map_version_id: null }), 'Moved to inbox')
  const setKind = (f, kind) => act(() => api.patch(`/api/files/${f.id}`, { kind }))
  const setPublish = (level) => act(() => api.patch(`/api/maps/${id}`, { publish_level: level }),
    level === 'private' ? 'Removed from the public site at the next publish' : `Public site: ${PUBLISH_LEVELS.find((l) => l.value === level).label}`)
  const markReviewed = () => act(() => api.patch(`/api/maps/${id}`, { needs_review: false }), 'Marked as reviewed')
  const coursesFromPages = (ev, f) => act(() => api.post(`/api/events/${ev.id}/courses/from-file`, { file_id: f.id }), `Created ${f.page_count} courses`)

  async function uploadTo(version, fileList) {
    busy = true
    for (const file of fileList) {
      try {
        notify(`Uploading ${file.name}…`)
        const res = await uploadFile(file)
        if (res.status === 'error') { notify(`${file.name}: ${res.error}`, 'error'); continue }
        if (res.status === 'duplicate' && res.file.map_version_id) { notify(`${file.name} is already on “${res.file.map_name}”`, 'error'); continue }
        await api.patch(`/api/files/${res.file.id}`, { map_version_id: version.id })
      } catch (e) { notify(e.message, 'error') }
    }
    await load(); await refreshMeta()
    busy = false
  }

  function view(file, page = 1) {
    lb = { open: true, pages: file.pages, index: Math.max(0, page - 1), title: file.original_name }
  }
  function viewCourse(c) {
    const f = allFiles.find((x) => x.id === c.file_id)
    if (f) view(f, c.page_no || 1)
  }

  const versionTitle = (v) => v.label ? `${v.label}${v.survey_date ? ` · survey ${fmtDate(v.survey_date)}` : ''}` : v.survey_date ? `Survey ${fmtDate(v.survey_date)}` : 'Undated version'
  const emptyEvent = () => ({ name: '', date: '', end_date: '', event_type: null, discipline: null, organiser_club_id: null, results_url: '', notes: '' })
  const emptyCourse = () => ({ name: '', length_km: null, climb_m: null, controls: null, scale: null, file_id: null, page_no: null, notes: '' })
</script>

{#if error}
  <main class="page"><p class="empty">{error} — <a href="#/">back to the library</a></p></main>
{:else if !map}
  <main class="page"><p class="empty">Loading…</p></main>
{:else}
  <main class="page">
    <a href="#/" class="back">← Library</a>

    <section class="top">
      <button class="hero" onclick={() => hero && view(hero)} disabled={!hero} aria-label="View map">
        {#if hero}<img src={hero.pages[0].image_url} alt="Map {map.name}" />{:else}<span class="muted">No map file yet</span>{/if}
      </button>

      <div class="summary">
        {#if edit?.kind === 'map'}
          <div class="card">
            <MapFields bind:map={edit.data} prefix="em" />
            <div class="row end">
              <button onclick={() => (edit = null)}>Cancel</button>
              <button class="primary" onclick={saveEdit} disabled={!editValid || busy}>Save</button>
            </div>
          </div>
        {:else}
          <div class="row">
            <h1>{map.name}</h1>
            <span class="spacer"></span>
            <button class="small" onclick={() => startEdit('map', map)}>Edit</button>
            <button class="small ghost danger" onclick={removeMap}>Delete</button>
          </div>
          {#if map.needs_review}
            <div class="review row"><span>Created by the bulk import — check the details.</span><span class="spacer"></span><button class="small" onclick={markReviewed}>Mark reviewed</button></div>
          {/if}
          <dl class="facts">
            {#if map.location}<div><dt>Near</dt><dd>{map.location}</dd></div>{/if}
            {#if map.club_name}<div><dt>Club</dt><dd>{map.club_name}</dd></div>{/if}
            {#if map.map_type}<div><dt>Type</dt><dd>{label(map.map_type)}</dd></div>{/if}
            {#if map.scale}<div><dt>Scale</dt><dd>{fmtScale(map.scale)}</dd></div>{/if}
            {#if map.contour_interval}<div><dt>Contours</dt><dd>{fmtContour(map.contour_interval)}</dd></div>{/if}
            <div><dt>Last survey</dt><dd>{fmtDate(map.last_survey) || '—'}</dd></div>
            <div><dt>Last event</dt><dd>{fmtDate(map.last_event) || '—'}</dd></div>
            <div><dt>Public site</dt><dd>
              <select class="pub" value={map.publish_level} onchange={(e) => setPublish(e.target.value)} title={PUBLISH_LEVELS.find((l) => l.value === map.publish_level)?.hint}>
                {#each PUBLISH_LEVELS as l}<option value={l.value}>{l.label}</option>{/each}
              </select>
            </dd></div>
            {#if map.lat != null}<div><dt>Coordinates</dt><dd><a href="https://www.openstreetmap.org/?mlat={map.lat}&mlon={map.lon}#map=15/{map.lat}/{map.lon}" target="_blank" rel="noopener">{map.lat.toFixed(5)}, {map.lon.toFixed(5)}</a></dd></div>{/if}
          </dl>
          {#if map.tags.length}<div class="row">{#each map.tags as t}<span class="chip accent">{t}</span>{/each}</div>{/if}
          {#if map.notes}<p class="notes">{map.notes}</p>{/if}
          {#if map.public_note && map.publish_level !== 'private'}<p class="notes"><span class="chip ok">public note</span> {map.public_note}</p>{/if}
          {#if nearby.length}
            <div class="nearby">
              <span class="muted small">Nearby maps</span>
              <div class="row">
                {#each nearby as n (n.id)}
                  <a class="chip {n.overlaps ? 'course' : ''}" href="#/map/{n.id}" title={n.overlaps ? 'Overlaps this map' : ''}>
                    {n.name} · {n.km < 1 ? `${Math.round(n.km * 1000)} m` : `${n.km.toFixed(1)} km`}{n.overlaps ? ' · overlaps' : ''}</a>
                {/each}
              </div>
            </div>
          {/if}

          {#if timeline}
            <div class="timeline" aria-label="Timeline">
              <div class="line"></div>
              {#each timeline.items as i}
                <span class="dot {i.kind}" style="left: {i.x}%" title={i.label}></span>
              {/each}
              <span class="yr start">{timeline.min}</span><span class="yr end">{timeline.max}</span>
            </div>
            <div class="legend"><span class="dot-s survey"></span> survey <span class="dot-s event"></span> event</div>
          {/if}
        {/if}
      </div>
    </section>

    <section class="onmap">
      <div class="row sect-head">
        <h2>On the map</h2>
        {#if overlays.length}<span class="muted">{overlays.length} placed page{overlays.length > 1 ? 's' : ''}</span>{/if}
        <span class="spacer"></span>
        {#if overlays.length}<a class="btn small" href="/api/maps/{id}/kmz" download title="Open in Google Earth (web, desktop or app)">Google Earth (.kmz)</a>{/if}
        {#if map.lat != null}<a class="btn small ghost" href="https://www.google.com/maps/search/?api=1&query={map.lat},{map.lon}" target="_blank" rel="noopener">Google Maps ↗</a>{/if}
      </div>
      {#if overlays.length}
        {#key overlays.map((o) => o.key + o.corners.flat().join()).join()}<OverlayMap {overlays} />{/key}
      {:else if firstPlaceable}
        <div class="card placehint row">
          <span>Not placed yet. Pair a few points on the map with the aerial photo to show it on top of the real world.</span>
          <span class="spacer"></span>
          <a class="btn primary" href="#/place/{firstPlaceable.pages[0].id}">Place on map</a>
        </div>
      {/if}
    </section>

    <div class="row sect-head">
      <h2>Versions</h2>
      <span class="muted">{map.versions.length}</span>
      <span class="spacer"></span>
      <button onclick={() => startEdit('version', { survey_date: '', scale: map.scale, contour_interval: map.contour_interval, cartographer: '', standard: null, label: '', notes: '' })}>+ New version</button>
    </div>

    {#if edit?.kind === 'version' && !edit.data.id}
      <div class="card version">
        <h3>New version</h3>
        <VersionFields bind:version={edit.data} />
        <div class="row end"><button onclick={() => (edit = null)}>Cancel</button><button class="primary" onclick={saveEdit} disabled={!editValid || busy}>Add version</button></div>
      </div>
    {/if}

    {#each map.versions as v (v.id)}
      <section class="card version">
        {#if edit?.kind === 'version' && edit.data.id === v.id}
          <VersionFields bind:version={edit.data} />
          <div class="row end"><button onclick={() => (edit = null)}>Cancel</button><button class="primary" onclick={saveEdit} disabled={!editValid || busy}>Save</button></div>
        {:else}
          <div class="row">
            <h3 class="vt">{versionTitle(v)}</h3>
            {#if v.scale}<span class="chip">{fmtScale(v.scale)}</span>{/if}
            {#if v.contour_interval}<span class="chip">{fmtContour(v.contour_interval)}</span>{/if}
            {#if v.standard}<span class="chip">{v.standard}</span>{/if}
            {#if v.cartographer}<span class="muted small">by {v.cartographer}</span>{/if}
            <span class="spacer"></span>
            <button class="small ghost" onclick={() => startEdit('version', v)}>Edit</button>
            {#if map.versions.length > 1}<button class="small ghost danger" onclick={() => removeVersion(v)}>Delete</button>{/if}
          </div>
          {#if v.notes}<p class="notes">{v.notes}</p>{/if}
        {/if}

        <!-- Files -->
        <div class="subhead row">
          <h4>Files</h4>
          <span class="spacer"></span>
          <label class="btn small">+ Upload<input type="file" multiple hidden accept=".pdf,image/*" onchange={(e) => { uploadTo(v, [...e.target.files]); e.target.value = '' }} /></label>
        </div>
        {#if v.files.length}
          <div class="files">
            {#each v.files as f (f.id)}
              <div class="file">
                <button class="fthumb" onclick={() => view(f)} aria-label="View {f.original_name}">
                  {#if f.thumb_url}<img src={f.thumb_url} alt="" loading="lazy" />{/if}
                  {#if f.page_count > 1}<span class="pages">{f.page_count} p</span>{/if}
                </button>
                <div class="fmeta">
                  <span class="fname" title={f.original_name}>{f.original_name}</span>
                  <span class="muted small">{f.format.toUpperCase()} · {fmtBytes(f.size_bytes)}{#if f.source === 'strava'} · <span class="strava-src" title="Imported from Strava: only for you, not for the public site">from Strava</span>{/if}</span>
                  <div class="row tight">
                    <select class="kind" value={f.kind} onchange={(e) => setKind(f, e.target.value)} aria-label="File type">
                      {#each meta.enums.file_kinds as k}<option value={k}>{label(k)}</option>{/each}
                    </select>
                    <a class="btn small ghost" href={f.original_url} target="_blank" rel="noopener" title="Original file">↓</a>
                    {#if f.pages.length}
                      <a class="btn small {f.pages.some((p) => p.georef) ? 'ghost placed' : ''}" href="#/place/{f.pages[0].id}"
                        title={f.pages[0].georef ? `Placed with ${f.pages[0].georef.point_count} points` : 'Place this page on the map'}>
                        {f.pages.some((p) => p.georef) ? '✓ Placed' : 'Place'}</a>
                    {/if}
                    <button class="small ghost" onclick={() => detachFile(f)} title="Move back to the inbox">To inbox</button>
                  </div>
                </div>
              </div>
            {/each}
          </div>
        {:else}
          <p class="muted small">No files on this version yet.</p>
        {/if}

        <!-- Events -->
        <div class="subhead row">
          <h4>Events</h4>
          <span class="spacer"></span>
          <button class="small" onclick={() => startEdit('event', emptyEvent(), { parentId: v.id })}>+ Event</button>
        </div>
        {#if edit?.kind === 'event' && !edit.data.id && edit.parentId === v.id}
          <div class="inner">
            <EventFields bind:event={edit.data} prefix="ne{v.id}" />
            <div class="row end"><button onclick={() => (edit = null)}>Cancel</button><button class="primary" onclick={saveEdit} disabled={!editValid || busy}>Add event</button></div>
          </div>
        {/if}
        {#each v.events as ev (ev.id)}
          <div class="event">
            {#if edit?.kind === 'event' && edit.data.id === ev.id}
              <EventFields bind:event={edit.data} prefix="ee{ev.id}" />
              <div class="row end"><button onclick={() => (edit = null)}>Cancel</button><button class="primary" onclick={saveEdit} disabled={!editValid || busy}>Save</button></div>
            {:else}
              <div class="row">
                <strong>{ev.name}</strong>
                {#if ev.date}<span class="muted">{fmtDate(ev.date)}{ev.end_date ? ` – ${fmtDate(ev.end_date)}` : ''}</span>{/if}
                {#if ev.event_type}<span class="chip">{label(ev.event_type)}</span>{/if}
                {#if ev.discipline}<span class="chip">{label(ev.discipline)}</span>{/if}
                {#if ev.organiser_name}<span class="muted small">by {ev.organiser_name}</span>{/if}
                {#if ev.results_url}<a class="small" href={ev.results_url} target="_blank" rel="noopener">results ↗</a>{/if}
                <span class="spacer"></span>
                <button class="small ghost" onclick={() => startEdit('event', ev)}>Edit</button>
                <button class="small ghost danger" onclick={() => removeEvent(ev)}>Delete</button>
              </div>
              {#if ev.notes}<p class="notes">{ev.notes}</p>{/if}
            {/if}

            {#if ev.participations?.length}
              <ul class="ran">
                {#each ev.participations as p (p.id)}
                  <li>
                    <span class="chip accent">You ran</span>
                    <span class="num">{fmtDate(p.date)}</span>
                    {#if p.course_name}<span class="chip course">{p.course_name}</span>{/if}
                    {#if p.result_time_s}<span class="num">{fmtDuration(p.result_time_s)}</span>{/if}
                    {#if p.position}<span class="num">{p.position}{p.competitors ? `/${p.competitors}` : ''}</span>{/if}
                    {#if p.strava}<span class="muted small num">{fmtDistance(p.strava.distance_m)} run</span>
                      <a class="small strava-link" href={p.strava.url} target="_blank" rel="noopener">View on Strava</a>{/if}
                    {#if p.notes}<span class="muted small">{p.notes}</span>{/if}
                  </li>
                {/each}
              </ul>
            {/if}

            {#if ev.courses.length}
              <table class="courses">
                <thead><tr><th></th><th>Course</th><th class="num">Length</th><th class="num">Climb</th><th class="num">Controls</th><th class="num">Scale</th><th></th></tr></thead>
                <tbody>
                  {#each ev.courses as c (c.id)}
                    {#if edit?.kind === 'course' && edit.data.id === c.id}
                      <tr><td colspan="7">
                        <CourseFields bind:course={edit.data} files={v.files} />
                        <div class="row end"><button onclick={() => (edit = null)}>Cancel</button><button class="primary" onclick={saveEdit} disabled={!editValid || busy}>Save</button></div>
                      </td></tr>
                    {:else}
                      <tr>
                        <td class="cthumb">{#if c.thumb_url}<button class="fthumb mini" onclick={() => viewCourse(c)} aria-label="View course {c.name}"><img src={c.thumb_url} alt="" loading="lazy" /></button>{/if}</td>
                        <td><span class="chip course">{c.name}</span>{#if c.notes}<div class="muted small">{c.notes}</div>{/if}</td>
                        <td class="num">{fmtKm(c.length_km)}</td>
                        <td class="num">{c.climb_m != null ? `${c.climb_m} m` : ''}</td>
                        <td class="num">{c.controls ?? ''}</td>
                        <td class="num">{fmtScale(c.scale)}</td>
                        <td class="acts">
                          <button class="small ghost" onclick={() => startEdit('course', c)}>Edit</button>
                          <button class="small ghost danger" onclick={() => removeCourse(c)} aria-label="Delete course">✕</button>
                        </td>
                      </tr>
                    {/if}
                  {/each}
                </tbody>
              </table>
            {/if}

            {#if edit?.kind === 'course' && !edit.data.id && edit.parentId === ev.id}
              <div class="inner">
                <CourseFields bind:course={edit.data} files={v.files} />
                <div class="row end"><button onclick={() => (edit = null)}>Cancel</button><button class="primary" onclick={saveEdit} disabled={!editValid || busy}>Add course</button></div>
              </div>
            {:else}
              <div class="row course-actions">
                <button class="small ghost" onclick={() => startEdit('course', emptyCourse(), { parentId: ev.id })}>+ Course</button>
                {#each v.files.filter((f) => f.page_count > 1) as f}
                  <button class="small ghost" onclick={() => coursesFromPages(ev, f)} disabled={busy}>+ One course per page of {f.original_name}</button>
                {/each}
              </div>
            {/if}
          </div>
        {/each}
        {#if !v.events.length && !(edit?.kind === 'event' && edit.parentId === v.id)}<p class="muted small">No events recorded on this version.</p>{/if}
      </section>
    {/each}
  </main>

  <Lightbox pages={lb.pages} bind:index={lb.index} bind:open={lb.open} title={lb.title} />
{/if}

<style>
  .back { display: inline-block; margin-bottom: .75rem; color: var(--muted); }
  .top { display: grid; grid-template-columns: minmax(220px, 340px) 1fr; gap: 1.5rem; margin-bottom: 2rem; align-items: start; }
  .hero { padding: 0; border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; background: var(--surface-2); aspect-ratio: 3 / 4; width: 100%; justify-content: center; box-shadow: var(--shadow); }
  .hero img { width: 100%; height: 100%; object-fit: cover; object-position: center top; }
  .summary { min-width: 0; display: flex; flex-direction: column; gap: .75rem; }
  .summary h1 { margin: 0; }
  .review { background: color-mix(in srgb, var(--warn) 12%, var(--surface)); border: 1px solid color-mix(in srgb, var(--warn) 40%, transparent); border-radius: 6px; padding: .45rem .7rem; font-size: .9rem; }
  .facts { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: .6rem 1rem; margin: 0; }
  .facts dt { font-size: .78rem; color: var(--muted); }
  .facts dd { margin: 0; font-weight: 500; }
  .facts .pub { padding: .1rem .3rem; font-size: .88rem; width: auto; }
  .nearby { display: flex; flex-direction: column; gap: .3rem; }
  .ran { list-style: none; margin: .4rem 0 0; padding: 0; display: flex; flex-direction: column; gap: .25rem; font-size: .9rem; }
  .ran li { display: flex; flex-wrap: wrap; align-items: center; gap: .45rem; }
  .strava-link, .strava-src { color: #fc5200; }
  .notes { white-space: pre-wrap; color: var(--muted); font-size: .92rem; margin: .25rem 0 0; }

  .timeline { position: relative; height: 34px; margin: .75rem .5rem 0; }
  .timeline .line { position: absolute; left: 0; right: 0; top: 10px; height: 2px; background: var(--border); }
  .timeline .dot { position: absolute; top: 4px; width: 14px; height: 14px; margin-left: -7px; border-radius: 50%; border: 2px solid var(--surface); }
  .dot.survey, .dot-s.survey { background: var(--forest); }
  .dot.event, .dot-s.event { background: var(--course); }
  .timeline .yr { position: absolute; top: 20px; font-size: .75rem; color: var(--muted); }
  .yr.start { left: 0; } .yr.end { right: 0; }
  .legend { font-size: .78rem; color: var(--muted); display: flex; align-items: center; gap: .3rem; }
  .dot-s { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-left: .4rem; }

  .sect-head { margin-bottom: .75rem; }
  .onmap { margin-bottom: 2rem; }
  .placehint { gap: .75rem; }
  .placed { color: var(--ok); }
  .sect-head h2 { margin: 0; }
  .version { margin-bottom: 1.25rem; }
  .vt { margin: 0; }
  .small { font-size: .85rem; }
  .end { justify-content: flex-end; margin-top: .75rem; }
  .subhead { margin: 1.1rem 0 .5rem; border-top: 1px solid var(--border); padding-top: .75rem; }
  .subhead h4 { margin: 0; font-size: .9rem; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }

  .files { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: .75rem; }
  .file { display: flex; gap: .6rem; align-items: flex-start; min-width: 0; }
  .fthumb { padding: 0; width: 64px; height: 84px; flex: none; border: 1px solid var(--border); border-radius: 4px; overflow: hidden; position: relative; background: var(--surface-2); }
  .fthumb img { width: 100%; height: 100%; object-fit: cover; }
  .fthumb.mini { width: 36px; height: 44px; }
  .pages { position: absolute; bottom: 2px; right: 2px; font-size: .65rem; background: rgb(0 0 0 / 65%); color: #fff; padding: 0 .25rem; border-radius: 3px; }
  .fmeta { display: flex; flex-direction: column; gap: .15rem; min-width: 0; flex: 1; }
  .fname { font-weight: 500; font-size: .9rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tight { gap: .25rem; flex-wrap: nowrap; }
  .kind { width: auto; padding: .15rem .3rem; font-size: .8rem; }

  .event { border-left: 3px solid var(--course); padding: .4rem 0 .4rem .8rem; margin-bottom: .75rem; }
  .inner { background: var(--surface-2); border-radius: 6px; padding: .75rem; margin-bottom: .75rem; }
  .courses { width: 100%; border-collapse: collapse; margin-top: .4rem; font-size: .88rem; }
  .courses th { text-align: left; font-size: .75rem; color: var(--muted); font-weight: 500; padding: .2rem .4rem; }
  .courses td { padding: .25rem .4rem; border-top: 1px solid var(--border); vertical-align: middle; }
  .courses .num { text-align: right; }
  .cthumb { width: 44px; }
  .acts { text-align: right; white-space: nowrap; }
  .course-actions { margin-top: .25rem; gap: .25rem; }

  @media (max-width: 720px) {
    .top { grid-template-columns: 1fr; }
    .hero { max-height: 50vh; aspect-ratio: auto; height: 50vh; }
    .courses th:nth-child(4), .courses td:nth-child(4), .courses th:nth-child(5), .courses td:nth-child(5) { display: none; }
  }
</style>
