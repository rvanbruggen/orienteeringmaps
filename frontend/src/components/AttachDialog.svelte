<script>
  // Attach a file to an existing map: to one of its versions (or a new version),
  // optionally also as a course in an event.
  import { untrack } from 'svelte'
  import { api, pick, VERSION_KEYS } from '../lib/api.js'
  import { meta, notify, refreshMeta } from '../lib/stores.svelte.js'
  import { fmtDate, fmtScale, isPartialDate, label } from '../lib/format.js'
  import Modal from './Modal.svelte'
  import VersionFields from './VersionFields.svelte'

  let { file, candidates = [], open = $bindable(false), ondone } = $props()

  let maps = $state([]), q = $state(''), detail = $state(null)
  let versionId = $state('new'), newVersion = $state({}), kind = $state('map')
  let asCourse = $state(false), eventId = $state('new'), eventName = $state(''), courseName = $state(''), perPage = $state(false)
  let saving = $state(false)

  $effect(() => {
    if (open) untrack(init)
  })

  async function init() {
    const s = file.suggestions || {}
    detail = null; q = ''; kind = file.kind || 'map'
    newVersion = { survey_date: s.survey_date ?? '', scale: s.scale ?? null, contour_interval: s.contour_interval ?? null,
                   cartographer: s.cartographer ?? '', label: s.label ?? '', standard: null, notes: '' }
    asCourse = !!s.course || file.page_count > 1
    courseName = s.course?.name ?? ''
    perPage = file.page_count > 1 && !s.course
    try { maps = await api.get('/api/maps') } catch (e) { notify(e.message, 'error') }
    if (candidates.length === 1) choose(candidates[0].id)
  }

  const shown = $derived.by(() => {
    const t = q.trim().toLowerCase()
    const ids = new Set(candidates.map((c) => c.id))
    return maps.filter((m) => !t || `${m.name} ${m.location ?? ''}`.toLowerCase().includes(t))
      .sort((a, b) => (ids.has(b.id) - ids.has(a.id)) || a.name.localeCompare(b.name)).slice(0, 30)
  })

  async function choose(id) {
    try {
      detail = await api.get(`/api/maps/${id}`)
      versionId = detail.versions[0]?.id ?? 'new'
      // A file whose scale differs from every version is probably a new survey.
      if (file.suggestions?.scale && !detail.versions.some((v) => v.scale === file.suggestions.scale) && !file.suggestions?.course) versionId = 'new'
    } catch (e) { notify(e.message, 'error') }
  }

  const version = $derived(detail?.versions.find((v) => v.id === versionId))
  $effect(() => {
    // Default to the first event of the chosen version.
    eventId = version?.events[0]?.id ?? 'new'
  })

  const valid = $derived(detail && (versionId !== 'new' || isPartialDate(newVersion.survey_date)) &&
    (!asCourse || perPage || courseName.trim()))

  async function save() {
    saving = true
    try {
      let vid = versionId
      if (vid === 'new') vid = (await api.post(`/api/maps/${detail.id}/versions`, pick(newVersion, VERSION_KEYS))).id
      await api.patch(`/api/files/${file.id}`, { map_version_id: vid, kind: asCourse && kind === 'map' ? 'course' : kind })
      if (asCourse) {
        let eid = eventId
        if (eid === 'new') eid = (await api.post(`/api/versions/${vid}/events`, { name: eventName.trim() || detail.name })).id
        if (perPage) await api.post(`/api/events/${eid}/courses/from-file`, { file_id: file.id })
        else {
          const c = file.suggestions?.course || {}
          await api.post(`/api/events/${eid}/courses`, { name: courseName.trim(), file_id: file.id, length_km: c.length_km ?? null,
            scale: c.scale && c.scale !== (version?.scale ?? newVersion.scale) ? c.scale : null })
        }
      }
      await refreshMeta()
      notify(`Added to “${detail.name}”`)
      open = false
      ondone?.(detail)
    } catch (e) {
      notify(e.message, 'error')
    }
    saving = false
  }
</script>

<Modal title="Add to an existing map" bind:open wide>
  <p class="muted">File: {file.original_name}</p>
  {#if !detail}
    <input type="search" placeholder="Search maps…" bind:value={q} />
    <ul class="maplist">
      {#each shown as m (m.id)}
        <li><button class="ghost" onclick={() => choose(m.id)}>
          <strong>{m.name}</strong> <span class="muted">{m.location ?? ''}</span>
          {#if candidates.some((c) => c.id === m.id)}<span class="chip accent">suggested</span>{/if}
        </button></li>
      {/each}
      {#if !shown.length}<li class="muted">No maps found.</li>{/if}
    </ul>
  {:else}
    <div class="row"><h3 class="nomargin">{detail.name}</h3><button class="small" onclick={() => (detail = null)}>Change map</button></div>

    <h3 class="sect">Version</h3>
    <div class="opts">
      {#each detail.versions as v (v.id)}
        <label class="opt"><input type="radio" bind:group={versionId} value={v.id} />
          {v.label || (v.survey_date ? `Survey ${fmtDate(v.survey_date)}` : 'Undated version')}
          <span class="muted">{fmtScale(v.scale)} · {v.files.length} file(s)</span></label>
      {/each}
      <label class="opt"><input type="radio" bind:group={versionId} value="new" /> New version (new survey)</label>
    </div>
    {#if versionId === 'new'}<div class="indent"><VersionFields bind:version={newVersion} /></div>{/if}

    <h3 class="sect">File type</h3>
    <select bind:value={kind} class="auto">
      {#each meta.enums.file_kinds as k}<option value={k}>{label(k)}</option>{/each}
    </select>

    <h3 class="sect"><label class="row"><input type="checkbox" bind:checked={asCourse} /> Also add as course in an event</label></h3>
    {#if asCourse}
      <div class="grid-form">
        <label class="field"><span>Event</span>
          <select bind:value={eventId}>
            {#each version?.events ?? [] as e}<option value={e.id}>{e.name}{e.date ? ` (${fmtDate(e.date)})` : ''}</option>{/each}
            <option value="new">+ New event…</option>
          </select>
        </label>
        {#if eventId === 'new'}<label class="field"><span>New event name</span><input bind:value={eventName} placeholder={detail.name} /></label>{/if}
        {#if file.page_count > 1}
          <label class="field wide row"><input type="checkbox" bind:checked={perPage} /> One course per page ({file.page_count} pages)</label>
        {/if}
        {#if !perPage}<label class="field"><span>Course name</span><input bind:value={courseName} placeholder="e.g. Lang" /></label>{/if}
      </div>
    {/if}
  {/if}
  {#snippet footer()}
    <button onclick={() => (open = false)}>Cancel</button>
    <button class="primary" onclick={save} disabled={!valid || saving}>{saving ? 'Saving…' : 'Add to map'}</button>
  {/snippet}
</Modal>

<style>
  .maplist { list-style: none; padding: 0; margin: .5rem 0 0; max-height: 50vh; overflow: auto; }
  .maplist button { width: 100%; justify-content: flex-start; gap: .5rem; text-align: left; }
  .sect { margin-top: 1.1rem; }
  .sect label { font-size: inherit; font-weight: inherit; gap: .5rem; }
  .nomargin { margin: 0; }
  .opts { display: flex; flex-direction: column; gap: .3rem; }
  .opt { display: flex; gap: .5rem; align-items: center; }
  .indent { margin: .5rem 0 0 1.5rem; }
  .auto { width: auto; }
</style>
