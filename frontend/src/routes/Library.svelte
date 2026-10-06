<script>
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { go } from '../lib/router.svelte.js'
  import { meta, notify } from '../lib/stores.svelte.js'
  import { fmtScale, fmtContour, fmtDate, label, yearsAgo } from '../lib/format.js'

  const PREFS_KEY = 'omaps.library'
  let maps = $state([])
  let loading = $state(true)

  const defaults = { q: '', type: '', club: '', tag: '', review: false, sort: 'name', dir: 1, view: 'table' }
  let prefs = $state({ ...defaults, ...load() })

  function load() {
    try { return JSON.parse(localStorage.getItem(PREFS_KEY)) || {} } catch { return {} }
  }
  $effect(() => {
    const snapshot = JSON.stringify(prefs)
    try { localStorage.setItem(PREFS_KEY, snapshot) } catch { /* private mode */ }
  })

  onMount(async () => {
    try { maps = await api.get('/api/maps') } catch (e) { notify(e.message, 'error') }
    loading = false
  })

  const columns = [
    { key: 'name', label: 'Name' },
    { key: 'location', label: 'Location' },
    { key: 'club_name', label: 'Club' },
    { key: 'scale', label: 'Scale', num: true },
    { key: 'contour_interval', label: 'Contours', num: true },
    { key: 'last_survey', label: 'Last survey' },
    { key: 'last_event', label: 'Last event' },
    { key: 'version_count', label: 'Versions', num: true },
    { key: 'event_count', label: 'Events', num: true },
  ]

  const clubNames = $derived([...new Set(maps.map((m) => m.club_name).filter(Boolean))].sort())
  const tags = $derived([...new Set(maps.flatMap((m) => m.tags))].sort())
  const types = $derived([...new Set(maps.map((m) => m.map_type).filter(Boolean))].sort())

  const filtered = $derived.by(() => {
    const q = prefs.q.trim().toLowerCase()
    const out = maps.filter((m) =>
      (!q || [m.name, m.location, m.club_name, ...m.tags].some((v) => v?.toLowerCase().includes(q))) &&
      (!prefs.type || m.map_type === prefs.type) &&
      (!prefs.club || m.club_name === prefs.club) &&
      (!prefs.tag || m.tags.includes(prefs.tag)) &&
      (!prefs.review || m.needs_review))
    const k = prefs.sort
    return out.sort((a, b) => {
      const av = a[k], bv = b[k]
      if (av == null && bv == null) return a.name.localeCompare(b.name)
      if (av == null) return 1          // empty values always last
      if (bv == null) return -1
      const c = typeof av === 'number' ? av - bv : String(av).localeCompare(String(bv), undefined, { sensitivity: 'base' })
      return c * prefs.dir || a.name.localeCompare(b.name)
    })
  })

  function sortBy(key) {
    if (prefs.sort === key) prefs.dir = -prefs.dir
    else { prefs.sort = key; prefs.dir = key.startsWith('last_') ? -1 : 1 }
  }

  const anyFilter = $derived(prefs.q || prefs.type || prefs.club || prefs.tag || prefs.review)
  const clearFilters = () => Object.assign(prefs, { q: '', type: '', club: '', tag: '', review: false })

  function exportCsv() {
    const cols = ['name', 'location', 'map_type', 'club_name', 'scale', 'contour_interval', 'last_survey', 'last_event', 'version_count', 'event_count', 'course_count', 'tags', 'lat', 'lon']
    const esc = (v) => {
      const s = Array.isArray(v) ? v.join('; ') : v ?? ''
      return /[",\n;]/.test(String(s)) ? `"${String(s).replaceAll('"', '""')}"` : s
    }
    const csv = [cols.join(','), ...filtered.map((m) => cols.map((c) => esc(m[c])).join(','))].join('\n')
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    a.download = 'orienteering-maps.csv'
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const staleSurvey = (d) => (yearsAgo(d) ?? 0) > 10
</script>

<main class="page">
  <div class="head row">
    <h1>Map library</h1>
    <span class="muted">{filtered.length}{filtered.length !== maps.length ? ` of ${maps.length}` : ''} maps</span>
    <span class="spacer"></span>
    <div class="seg" role="group" aria-label="View">
      <button class:on={prefs.view === 'table'} onclick={() => (prefs.view = 'table')}>Table</button>
      <button class:on={prefs.view === 'grid'} onclick={() => (prefs.view = 'grid')}>Cards</button>
    </div>
    <button onclick={exportCsv} disabled={!filtered.length}>CSV</button>
  </div>

  <div class="filters">
    <input class="search" type="search" placeholder="Search name, location, club, tag…" bind:value={prefs.q} />
    <select bind:value={prefs.type} aria-label="Map type">
      <option value="">All types</option>
      {#each types as t}<option value={t}>{label(t)}</option>{/each}
    </select>
    <select bind:value={prefs.club} aria-label="Club">
      <option value="">All clubs</option>
      {#each clubNames as c}<option value={c}>{c}</option>{/each}
    </select>
    <select bind:value={prefs.tag} aria-label="Tag">
      <option value="">All tags</option>
      {#each tags as t}<option value={t}>{t}</option>{/each}
    </select>
    <label class="check"><input type="checkbox" bind:checked={prefs.review} /> Needs review</label>
    {#if anyFilter}<button class="ghost small" onclick={clearFilters}>Clear</button>{/if}
  </div>

  {#if loading}
    <p class="empty">Loading…</p>
  {:else if !maps.length}
    <div class="empty card">
      <h2>No maps yet</h2>
      <p>Upload PDFs or images of your orienteering maps to get started.</p>
      <a class="btn primary" href="#/upload">+ Add maps</a>
    </div>
  {:else if !filtered.length}
    <p class="empty">No maps match these filters.</p>
  {:else if prefs.view === 'table'}
    <div class="table-wrap card">
      <table>
        <thead>
          <tr>
            <th class="thumbcol"></th>
            {#each columns as c}
              <th class:num={c.num} aria-sort={prefs.sort === c.key ? (prefs.dir > 0 ? 'ascending' : 'descending') : 'none'}>
                <button class="sort" onclick={() => sortBy(c.key)}>
                  {c.label}
                  <span class="arrow">{prefs.sort === c.key ? (prefs.dir > 0 ? '▲' : '▼') : ''}</span>
                </button>
              </th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each filtered as m (m.id)}
            <tr onclick={() => go(`/map/${m.id}`)}>
              <td class="thumbcol">
                {#if m.thumb_url}<img src={m.thumb_url} alt="" loading="lazy" />{:else}<div class="nothumb"></div>{/if}
              </td>
              <td>
                <a href="#/map/{m.id}" class="name" onclick={(e) => e.stopPropagation()}>{m.name}</a>
                <div class="chips">
                  {#if m.needs_review}<span class="chip warn">review</span>{/if}
                  {#if m.map_type}<span class="chip">{label(m.map_type)}</span>{/if}
                  {#each m.tags as t}<span class="chip accent">{t}</span>{/each}
                </div>
              </td>
              <td>{m.location ?? ''}</td>
              <td>{m.club_name ?? ''}</td>
              <td class="num">{fmtScale(m.scale)}</td>
              <td class="num">{fmtContour(m.contour_interval)}</td>
              <td class="num" class:stale={staleSurvey(m.last_survey)} title={staleSurvey(m.last_survey) ? 'Surveyed more than 10 years ago' : ''}>{fmtDate(m.last_survey)}</td>
              <td class="num">{fmtDate(m.last_event)}</td>
              <td class="num">{m.version_count}</td>
              <td class="num">{m.event_count}{m.course_count ? ` · ${m.course_count} crs` : ''}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:else}
    <div class="cards">
      {#each filtered as m (m.id)}
        <a class="mapcard card" href="#/map/{m.id}">
          <div class="img">{#if m.thumb_url}<img src={m.thumb_url} alt="" loading="lazy" />{/if}</div>
          <div class="body">
            <strong>{m.name}</strong>
            <div class="muted small">{[m.location, m.club_name].filter(Boolean).join(' · ')}</div>
            <div class="chips">
              {#if m.scale}<span class="chip">{fmtScale(m.scale)}</span>{/if}
              {#if m.last_survey}<span class="chip">survey {fmtDate(m.last_survey)}</span>{/if}
              {#if m.needs_review}<span class="chip warn">review</span>{/if}
              {#each m.tags as t}<span class="chip accent">{t}</span>{/each}
            </div>
          </div>
        </a>
      {/each}
    </div>
  {/if}
</main>

<style>
  .head { margin-bottom: .75rem; }
  .head h1 { margin: 0; }
  .seg { display: inline-flex; border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }
  .seg button { border: 0; border-radius: 0; background: var(--surface); }
  .seg button.on { background: var(--surface-2); font-weight: 600; }
  .filters { display: flex; gap: .5rem; flex-wrap: wrap; margin-bottom: 1rem; align-items: center; }
  .filters .search { flex: 1 1 260px; }
  .filters select { width: auto; flex: 0 1 170px; }
  .check { display: flex; align-items: center; gap: .35rem; font-size: .9rem; color: var(--muted); white-space: nowrap; }

  .table-wrap { padding: 0; overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: .92rem; }
  th { text-align: left; font-weight: 600; font-size: .8rem; color: var(--muted); border-bottom: 1px solid var(--border); padding: 0; white-space: nowrap; position: sticky; top: 0; background: var(--surface); }
  th.num, td.num { text-align: right; }
  th .sort { border: 0; background: none; padding: .6rem .6rem; font-weight: 600; color: inherit; width: 100%; justify-content: inherit; }
  th.num .sort { justify-content: flex-end; }
  .arrow { font-size: .65rem; width: .7rem; }
  td { padding: .45rem .6rem; border-bottom: 1px solid var(--border); vertical-align: middle; }
  tbody tr { cursor: pointer; }
  tbody tr:hover { background: var(--surface-2); }
  tbody tr:last-child td { border-bottom: 0; }
  .thumbcol { width: 56px; padding-right: 0; }
  .thumbcol img, .nothumb { width: 48px; height: 48px; object-fit: cover; border-radius: 4px; border: 1px solid var(--border); background: var(--surface-2); }
  .name { font-weight: 600; color: var(--text); }
  .chips { display: flex; gap: .25rem; flex-wrap: wrap; margin-top: .2rem; }
  td.stale { color: var(--warn); }

  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 1rem; }
  .mapcard { padding: 0; overflow: hidden; color: var(--text); display: flex; flex-direction: column; }
  .mapcard:hover { text-decoration: none; border-color: var(--muted); }
  .mapcard .img { aspect-ratio: 4 / 3; background: var(--surface-2); overflow: hidden; }
  .mapcard .img img { width: 100%; height: 100%; object-fit: cover; object-position: center 30%; }
  .mapcard .body { padding: .7rem .8rem .8rem; display: flex; flex-direction: column; gap: .2rem; }
  .small { font-size: .85rem; }
</style>
