<script>
  // Create a new map (+ first version, optional event/courses) from one or more files.
  import { untrack } from 'svelte'
  import { api, pick, MAP_KEYS, VERSION_KEYS, EVENT_KEYS } from '../lib/api.js'
  import { clubs, notify, refreshMeta } from '../lib/stores.svelte.js'
  import { isPartialDate } from '../lib/format.js'
  import Modal from './Modal.svelte'
  import MapFields from './MapFields.svelte'
  import VersionFields from './VersionFields.svelte'

  let { files = [], open = $bindable(false), oncreated } = $props()

  let map = $state({}), version = $state({}), event = $state({})
  let courses = $state([]), withEvent = $state(false), perPage = $state(false)
  let saving = $state(false)

  const suggestions = $derived(files.map((f) => f.suggestions || {}))
  const suggestedClubs = $derived([...new Set(suggestions.flatMap((s) => s.clubs || []))])
  const multiPage = $derived(files.find((f) => f.page_count > 1))

  const first = (key) => suggestions.map((s) => s[key]).find((v) => v !== undefined && v !== null)
  const findClub = (names) => clubs.list.find((c) => names.some((n) =>
    [c.name.toLowerCase(), (c.short_name || '').toLowerCase()].includes(n.toLowerCase())))?.id ?? null

  // Re-initialise only when the dialog opens (not when clubs etc. change while it is open).
  $effect(() => {
    if (open) untrack(init)
  })

  function init() {
    const tags = [...new Set(suggestions.flatMap((s) => s.tags || []))]
    const exif = files.find((f) => f.exif_lat != null)
    map = { name: first('name') ?? '', location: first('location') ?? '', map_type: first('map_type') ?? null,
            club_id: findClub(suggestedClubs), tags, notes: '', lat: exif?.exif_lat ?? null, lon: exif?.exif_lon ?? null }
    const scales = suggestions.map((s) => s.scale).filter(Boolean)
    version = { survey_date: first('survey_date') ?? '', scale: scales.length ? Math.max(...scales) : null,
                contour_interval: first('contour_interval') ?? null, cartographer: first('cartographer') ?? '',
                label: first('label') ?? '', standard: null, notes: '' }
    courses = files.filter((f) => f.suggestions?.course).map((f) => ({
      name: f.suggestions.course.name, length_km: f.suggestions.course.length_km ?? null,
      scale: f.suggestions.course.scale ?? null, file_id: f.id }))
    withEvent = courses.length > 0 || !!multiPage
    perPage = !!multiPage && !courses.length
    const series = tags.find((t) => t !== 'Oriëntatieparcours')
    event = { name: '', event_type: map.map_type === 'permanent' ? 'permanent' : null, date: '', _series: series }
  }

  const eventName = $derived(event.name || [event._series, map.name].filter(Boolean).join(' '))
  const valid = $derived(map.name?.trim() && isPartialDate(version.survey_date) && isPartialDate(event.date))

  async function save() {
    saving = true
    try {
      const body = { ...pick(map, MAP_KEYS), version: pick(version, VERSION_KEYS), file_ids: files.map((f) => f.id) }
      if (withEvent) {
        body.event = { ...pick(event, EVENT_KEYS), name: eventName }
        body.courses = courses.filter((c) => c.name?.trim()).map((c) => ({ ...c, scale: c.scale !== version.scale ? c.scale : null }))
      }
      for (const f of files) {
        if (withEvent && courses.some((c) => c.file_id === f.id) && f.kind === 'map') await api.patch(`/api/files/${f.id}`, { kind: 'course' })
      }
      const created = await api.post('/api/maps', body)
      if (withEvent && perPage && multiPage) {
        const ev = created.versions[0].events[0]
        await api.post(`/api/events/${ev.id}/courses/from-file`, { file_id: multiPage.id })
      }
      await refreshMeta()
      notify(`Created “${created.name}”`)
      open = false
      oncreated?.(created)
    } catch (e) {
      notify(e.message, 'error')
    }
    saving = false
  }
</script>

<Modal title="New map" bind:open wide>
  <p class="muted">From: {files.map((f) => f.original_name).join(', ')}. Fields are pre-filled from the file — check them.</p>
  <h3>Map</h3>
  <MapFields bind:map {suggestedClubs} prefix="nm" />
  <h3 class="sect">First version</h3>
  <VersionFields bind:version />
  <h3 class="sect"><label class="row"><input type="checkbox" bind:checked={withEvent} /> Add an event with courses</label></h3>
  {#if withEvent}
    <div class="grid-form">
      <label class="field wide"><span>Event name</span><input bind:value={event.name} placeholder={eventName} /></label>
      <label class="field"><span>Date</span><input bind:value={event.date} placeholder="optional" class:invalid={!isPartialDate(event.date)} /></label>
    </div>
    {#if courses.length}
      <table class="courses">
        <thead><tr><th>Course</th><th>Length (km)</th><th>File</th></tr></thead>
        <tbody>
          {#each courses as c}
            <tr>
              <td><input bind:value={c.name} /></td>
              <td><input type="number" step="0.1" bind:value={c.length_km} /></td>
              <td class="muted">{files.find((f) => f.id === c.file_id)?.original_name}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
    {#if multiPage}
      <label class="row perpage"><input type="checkbox" bind:checked={perPage} />
        Create one course per page of “{multiPage.original_name}” ({multiPage.page_count} pages)</label>
    {/if}
  {/if}
  {#snippet footer()}
    <button onclick={() => (open = false)}>Cancel</button>
    <button class="primary" onclick={save} disabled={!valid || saving}>{saving ? 'Saving…' : 'Create map'}</button>
  {/snippet}
</Modal>

<style>
  .sect { margin-top: 1.25rem; }
  .sect label { font-size: inherit; font-weight: inherit; gap: .5rem; }
  .courses { width: 100%; border-collapse: collapse; margin-top: .75rem; font-size: .9rem; }
  .courses th { text-align: left; font-size: .8rem; color: var(--muted); font-weight: 500; padding: .2rem .3rem; }
  .courses td { padding: .2rem .3rem; }
  .perpage { margin-top: .75rem; font-size: .92rem; }
</style>
