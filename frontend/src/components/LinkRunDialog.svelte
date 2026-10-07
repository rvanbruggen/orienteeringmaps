<script>
  // Link a Strava activity to the map, event and course you ran, with your result.
  // Existing ones are picked from suggestions; anything missing can be created here.
  import { untrack } from 'svelte'
  import Modal from './Modal.svelte'
  import { api } from '../lib/api.js'
  import { meta, notify, refreshMeta } from '../lib/stores.svelte.js'
  import { fmtDate, fmtDistance, fmtDuration, label } from '../lib/format.js'

  let { activity, open = $bindable(false), onsaved } = $props()

  let loading = $state(true), busy = $state(false)
  let choices = $state([])            // maps offered, each with its events and courses
  let allMaps = $state([])            // for "another map"
  let mapSel = $state('')             // map id as string, or 'new'
  let newMap = $state({ name: '', location: '', map_type: null })
  let eventSel = $state('')           // event id as string, or 'new'
  let newEvent = $state({ name: '', date: '', event_type: null, discipline: null })
  let courseSel = $state('')          // course id as string, 'new' or '' (not known)
  let newCourse = $state({ name: '', length_km: null })
  let result = $state({ time: '', position: null, competitors: null, notes: '' })
  let photos = $state(null)           // null = loading; [] = none
  let photoError = $state('')
  let pick = $state({})               // photo id -> kind to import ('' = don't)

  const day = $derived(activity?.start_local?.slice(0, 10) ?? '')
  const choice = $derived(choices.find((c) => String(c.map_id) === mapSel))
  const event = $derived(choice?.events.find((e) => String(e.id) === eventSel))

  // A first guess at type and discipline from the activity's name.
  function guess(name, race) {
    const n = name.toLowerCase()
    const discipline = /sprint/.test(n) ? 'sprint' : /\b(long|lang)\b/.test(n) ? 'long' : /\bmiddle\b|\bmidden/.test(n) ? 'middle'
      : /night|nacht/.test(n) ? 'night' : /relay|estafette/.test(n) ? 'relay' : null
    const event_type = /hitta|mapico|permanent/.test(n) ? 'permanent' : /\bbk\b|champ|kampioen/.test(n) ? 'championship'
      : race || /race|wedstrijd|series|cup/.test(n) ? 'race' : /training/.test(n) ? 'training' : null
    return { event_type, discipline }
  }

  async function loadPhotos() {
    photos = null
    photoError = ''
    pick = {}
    if (!activity.photo_count) { photos = []; return }
    try { photos = await api.get(`/api/strava/activities/${activity.id}/photos`) } catch (e) { photos = []; photoError = e.message }
  }

  async function load() {
    loading = true
    loadPhotos()
    try {
      const [res, maps] = await Promise.all([api.get(`/api/strava/activities/${activity.id}/choices`), allMaps.length ? allMaps : api.get('/api/maps')])
      choices = res.maps
      allMaps = maps
      const link = res.activity.link
      newMap = { name: '', location: '', map_type: null }
      newEvent = { name: activity.name, date: day, ...guess(activity.name, activity.race) }
      newCourse = { name: '', length_km: null }
      if (link) {
        mapSel = String(link.map_id)
        eventSel = String(link.event_id)
        courseSel = link.course_id ? String(link.course_id) : ''
        result = { time: link.result_time_s ? fmtDuration(link.result_time_s) : '', position: link.position, competitors: link.competitors, notes: link.notes ?? '' }
      } else {
        mapSel = choices.length ? String(choices[0].map_id) : 'new'
        pickEvent(mapSel)
        result = { time: '', position: null, competitors: null, notes: '' }
      }
    } catch (e) { notify(e.message, 'error') }
    loading = false
  }

  // Preselect the event that fits the date, if there is exactly one good candidate.
  function pickEvent(mapId) {
    const evs = choices.find((c) => String(c.map_id) === String(mapId))?.events ?? []
    const same = evs.filter((e) => e.fit === 'same_day')
    // A permanent course is "open" every day, so only pick it when the run's name says so;
    // a race in a town with a HITTA map is not a HITTA run.
    const permanentRun = /hitta|mapico|permanent/i.test(activity.name)
    const open = evs.filter((e) => e.fit === 'open' && (e.event_type !== 'permanent' || permanentRun))
    const best = same.length === 1 ? same[0] : !same.length && open.length === 1 ? open[0] : null
    eventSel = best ? String(best.id) : 'new'
    courseSel = ''
  }

  async function chooseOtherMap(id) {
    if (!id) return
    if (!choices.some((c) => String(c.map_id) === id)) {
      try {
        const res = await api.get(`/api/strava/activities/${activity.id}/choices?map_id=${id}`)
        const extra = res.maps.find((c) => String(c.map_id) === id)
        if (extra) choices = [...choices, extra]
      } catch (e) { notify(e.message, 'error'); return }
    }
    mapSel = id
    pickEvent(id)
  }

  $effect(() => { if (open && activity) untrack(load) })

  function parseTime(s) {
    if (!s?.trim()) return null
    const parts = s.trim().split(/[:.]/).map(Number)
    if (parts.some(isNaN) || parts.length > 3) return NaN
    return parts.reduce((acc, n) => acc * 60 + n, 0)
  }
  const timeS = $derived(parseTime(result.time))
  const valid = $derived(
    (mapSel === 'new' ? newMap.name.trim() : !!choice) &&
    (eventSel === 'new' ? newEvent.name.trim() : !!event) &&
    (courseSel !== 'new' || newCourse.name.trim()) &&
    !Number.isNaN(timeS))

  async function save() {
    busy = true
    const body = {
      result_time_s: timeS, position: result.position || null, competitors: result.competitors || null,
      notes: result.notes || null,
    }
    if (mapSel === 'new') body.new_map = { name: newMap.name, location: newMap.location || null, map_type: newMap.map_type }
    else body.map_id = +mapSel
    if (eventSel === 'new') body.new_event = { name: newEvent.name, date: newEvent.date || null, event_type: newEvent.event_type, discipline: newEvent.discipline }
    else body.event_id = +eventSel
    if (courseSel === 'new') body.new_course = { name: newCourse.name, length_km: newCourse.length_km || null }
    else if (courseSel) body.course_id = +courseSel
    try {
      const r = await api.put(`/api/strava/activities/${activity.id}/link`, body)
      const wanted = Object.entries(pick).filter(([, kind]) => kind).map(([id, kind]) => ({ id, kind }))
      let added = ''
      if (wanted.length) {
        const res = await api.post(`/api/strava/activities/${activity.id}/photos/import`, { photos: wanted })
        const ok = res.filter((x) => x.status !== 'error').length
        const failed = res.filter((x) => x.status === 'error')
        added = `, ${ok} photo${ok === 1 ? '' : 's'} added to the map`
        if (failed.length) notify(`Photo import failed: ${failed[0].error}`, 'error')
      }
      notify(`Linked to ${r.link.map_name}${added}`)
      if (body.new_map) refreshMeta()
      open = false
      onsaved?.(r)
    } catch (e) { notify(e.message, 'error') }
    busy = false
  }

  async function unlink() {
    if (!confirm('Unlink this run? The map, event and course stay.')) return
    busy = true
    try {
      await api.del(`/api/strava/activities/${activity.id}/link`)
      open = false
      onsaved?.({ ...activity, link: null })
    } catch (e) { notify(e.message, 'error') }
    busy = false
  }

  const fitLabel = { same_day: 'same day', open: 'open that day' }
  const PHOTO_KINDS = [
    { value: 'course', label: 'Course map' },
    { value: 'map', label: 'Map (no course)' },
    { value: 'result_card', label: 'Result card' },
    { value: 'control_descriptions', label: 'Control descriptions' },
    { value: 'other', label: 'Other' },
  ]

  // Change the type of a photo that is already in the library; saved straight away.
  async function setKind(p, kind) {
    try {
      const res = await api.patch(`/api/strava/activities/${activity.id}/photos/${p.id}`, { kind })
      p.file = { ...p.file, kind: res.kind, map_id: res.map_id }
      notify(`Photo saved as ${PHOTO_KINDS.find((k) => k.value === kind)?.label.toLowerCase() ?? kind}`)
    } catch (e) { notify(e.message, 'error') }
  }
  const scoreText = (sc) => !sc ? '' : sc.inside ? `${Math.round(sc.inside * 100)}% of your route is on this map` : `${sc.distance_m} m from the map’s location`
  const otherMaps = $derived(allMaps.filter((mp) => !choices.some((c) => c.map_id === mp.id)).sort((a, b) => a.name.localeCompare(b.name)))
</script>

<Modal title="Link run" bind:open wide>
  {#if activity}
    <p class="act">
      <strong>{activity.name}</strong><br />
      <span class="muted">{fmtDate(day)} · {fmtDistance(activity.distance_m)} · {fmtDuration(activity.moving_time_s)}</span>
    </p>
  {/if}
  {#if loading}
    <p class="muted">Looking for maps along your route…</p>
  {:else}
    <section>
      <h3>Map</h3>
      {#if !choices.length}<p class="muted small">Your route doesn’t lie on any placed map. Choose one, or add the map.</p>{/if}
      {#each choices as c (c.map_id)}
        <label class="opt">
          <input type="radio" name="map" value={String(c.map_id)} bind:group={mapSel} onchange={() => pickEvent(c.map_id)} />
          <span><strong>{c.name}</strong>{c.location ? ` · ${c.location}` : ''}<br /><span class="muted small">{scoreText(c.score)}</span></span>
        </label>
      {/each}
      <div class="row other">
        <select aria-label="Another map" onchange={(e) => { chooseOtherMap(e.target.value); e.target.value = '' }}>
          <option value="">Another map in the library…</option>
          {#each otherMaps as mp (mp.id)}<option value={String(mp.id)}>{mp.name}{mp.location ? ` · ${mp.location}` : ''}</option>{/each}
        </select>
      </div>
      <label class="opt">
        <input type="radio" name="map" value="new" bind:group={mapSel} onchange={() => (eventSel = 'new')} />
        <span><strong>New map here</strong> <span class="muted small">at the middle of your route; add the map files later</span></span>
      </label>
      {#if mapSel === 'new'}
        <div class="grid-form sub">
          <label class="field"><span>Map name *</span><input bind:value={newMap.name} placeholder="e.g. Kamp Grobbendonk" /></label>
          <label class="field"><span>Location</span><input bind:value={newMap.location} placeholder="town" /></label>
          <label class="field"><span>Type</span>
            <select bind:value={newMap.map_type}>
              <option value={null}>—</option>
              {#each meta.enums.map_types as t}<option value={t}>{label(t)}</option>{/each}
            </select>
          </label>
        </div>
      {/if}
    </section>

    <section>
      <h3>Event</h3>
      {#each choice?.events ?? [] as e (e.id)}
        <label class="opt">
          <input type="radio" name="event" value={String(e.id)} bind:group={eventSel} onchange={() => (courseSel = '')} />
          <span>
            <strong>{e.name}</strong>
            {#if e.date}<span class="muted">{fmtDate(e.date)}{e.end_date ? ` – ${fmtDate(e.end_date)}` : ''}</span>{/if}
            {#if e.event_type}<span class="chip">{label(e.event_type)}</span>{/if}
            {#if e.fit}<span class="chip ok">{fitLabel[e.fit]}</span>{/if}
          </span>
        </label>
      {/each}
      <label class="opt">
        <input type="radio" name="event" value="new" bind:group={eventSel} />
        <span><strong>New event</strong></span>
      </label>
      {#if eventSel === 'new'}
        <div class="grid-form sub">
          <label class="field wide"><span>Event name *</span><input bind:value={newEvent.name} /></label>
          <label class="field"><span>Date</span><input bind:value={newEvent.date} placeholder="2026-10-04" /></label>
          <label class="field"><span>Type</span>
            <select bind:value={newEvent.event_type}>
              <option value={null}>—</option>
              {#each meta.enums.event_types as t}<option value={t}>{label(t)}</option>{/each}
            </select>
          </label>
          <label class="field"><span>Discipline</span>
            <select bind:value={newEvent.discipline}>
              <option value={null}>—</option>
              {#each meta.enums.disciplines as t}<option value={t}>{label(t)}</option>{/each}
            </select>
          </label>
        </div>
      {/if}
    </section>

    <section>
      <h3>Course</h3>
      <div class="row">
        <select bind:value={courseSel} aria-label="Course">
          <option value="">Not known</option>
          {#each event?.courses ?? [] as c (c.id)}<option value={String(c.id)}>{c.name}{c.length_km ? ` (${String(c.length_km).replace('.', ',')} km)` : ''}</option>{/each}
          <option value="new">New course…</option>
        </select>
        {#if courseSel === 'new'}
          <input class="cname" bind:value={newCourse.name} placeholder="Course name, e.g. Lang or H50" aria-label="Course name" />
          <input class="km" type="number" step="0.1" min="0" bind:value={newCourse.length_km} placeholder="km" aria-label="Course length in km" />
        {/if}
      </div>
    </section>

    {#if activity?.photo_count}
      <section>
        <h3>Photos on Strava <span class="muted small">(choose what each photo is to add it to the map; for photos already in the library, changing the type saves straight away)</span></h3>
        {#if photos === null}
          <p class="muted small">Fetching photos…</p>
        {:else if photoError}
          <p class="error small">{photoError}</p>
        {:else if !photos.length}
          <p class="muted small">No photos found.</p>
        {:else}
          <div class="photos">
            {#each photos as p (p.id)}
              <figure class:on={!!pick[p.id] || !!p.file}>
                <a href={p.url} target="_blank" rel="noopener" title="Open full size"><img src={p.url} alt="Attached to the run on Strava" loading="lazy" /></a>
                <figcaption>
                  {#if p.file}
                    <select value={p.file.kind} onchange={(e) => setKind(p, e.target.value)} aria-label="Type of this photo in the library" disabled={busy}>
                      {#each PHOTO_KINDS as k}<option value={k.value}>{k.label}</option>{/each}
                      {#if !PHOTO_KINDS.some((k) => k.value === p.file.kind)}<option value={p.file.kind}>{label(p.file.kind)}</option>{/if}
                    </select>
                    <span class="small in-lib">✓ In library{p.file.map_id ? '' : ' (Inbox)'}</span>
                  {:else}
                    <select bind:value={pick[p.id]} aria-label="Add this photo as">
                      <option value="">Don’t add</option>
                      {#each PHOTO_KINDS as k}<option value={k.value}>{k.label}</option>{/each}
                    </select>
                  {/if}
                </figcaption>
              </figure>
            {/each}
          </div>
          <p class="hint">Strava keeps photos at up to 2048 pixels, which is enough to place the map. Photos from Strava are for you only: for the public site, upload your own copy.</p>
        {/if}
      </section>
    {/if}

    <section>
      <h3>Your result <span class="muted small">(optional)</span></h3>
      <div class="grid-form">
        <label class="field"><span>Official time</span>
          <input bind:value={result.time} placeholder="1:04:10" class:invalid={Number.isNaN(timeS)} />
        </label>
        <label class="field"><span>Position</span><input type="number" min="1" bind:value={result.position} /></label>
        <label class="field"><span>Of (runners)</span><input type="number" min="1" bind:value={result.competitors} /></label>
        <label class="field wide"><span>Notes</span><textarea rows="2" bind:value={result.notes} placeholder="Mistakes, route choices, …"></textarea></label>
      </div>
    </section>
  {/if}

  {#snippet footer()}
    {#if activity?.link}<button class="danger" onclick={unlink} disabled={busy}>Unlink</button><span class="spacer"></span>{/if}
    <button onclick={() => (open = false)}>Cancel</button>
    <button class="primary" onclick={save} disabled={!valid || busy || loading}>{activity?.link ? 'Save' : 'Link run'}</button>
  {/snippet}
</Modal>

<style>
  .act { margin-bottom: 1rem; }
  section { margin-bottom: 1.1rem; }
  h3 { margin-bottom: .4rem; }
  .small { font-size: .85rem; }
  .opt { display: flex; gap: .55rem; align-items: flex-start; padding: .35rem .5rem; border-radius: 6px; cursor: pointer; }
  .opt:hover { background: var(--surface-2); }
  .opt input { margin-top: .25rem; width: auto; flex: none; }
  .opt .chip { margin-left: .25rem; }
  .other { padding: .25rem .5rem .25rem 2rem; }
  .other select { width: auto; max-width: 100%; }
  .sub { padding: .25rem .5rem .5rem 2rem; }
  select { width: auto; }
  .cname { flex: 1 1 200px; width: auto; }
  .km { width: 6rem; }
  .photos { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: .6rem; margin-bottom: .4rem; }
  figure { margin: 0; border: 2px solid var(--border); border-radius: 8px; overflow: hidden; background: var(--surface-2); }
  figure.on { border-color: var(--accent); }
  figure img { width: 100%; height: 120px; object-fit: cover; display: block; }
  figcaption { padding: .35rem; }
  figcaption select { width: 100%; font-size: .85rem; }
  .in-lib { display: block; margin-top: .2rem; color: var(--ok); }
  .error { color: var(--danger); }
</style>
