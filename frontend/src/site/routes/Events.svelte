<script>
  import { store, mapHref, normalize } from '../data.svelte.js'
  import { fmtDate, label } from '../../lib/format.js'

  let q = $state('')
  let type = $state('')

  const all = $derived(store.maps.flatMap((m) => m.events.map((e) => ({ ...e, map: m })))
    .sort((a, b) => (b.date ?? '').localeCompare(a.date ?? '') || a.name.localeCompare(b.name)))
  const types = $derived([...new Set(all.map((e) => e.type).filter(Boolean))].sort())
  const filtered = $derived.by(() => {
    const words = normalize(q).split(/\s+/).filter(Boolean)
    return all.filter((e) => {
      const hay = normalize([e.name, e.organiser, e.map.name, e.map.location, ...(e.courses ?? []).map((c) => c.name)].join(' '))
      return words.every((w) => hay.includes(w)) && (!type || e.type === type)
    })
  })
  const byYear = $derived.by(() => {
    const groups = new Map()
    for (const e of filtered) {
      const y = e.date?.slice(0, 4) ?? 'Undated'
      if (!groups.has(y)) groups.set(y, [])
      groups.get(y).push(e)
    }
    return [...groups]
  })
</script>

<main class="page">
  <h1>Events</h1>
  <div class="filters">
    <input type="search" placeholder="Search events, maps, clubs, courses…" bind:value={q} aria-label="Search events" />
    {#if types.length > 1}
      <select bind:value={type} aria-label="Event type">
        <option value="">All types</option>
        {#each types as t}<option value={t}>{label(t)}</option>{/each}
      </select>
    {/if}
    <span class="muted">{filtered.length} event{filtered.length === 1 ? '' : 's'}</span>
  </div>
  {#each byYear as [year, events]}
    <h2>{year}</h2>
    <ul class="card list">
      {#each events as e}
        <li>
          <div class="row">
            <strong>{e.name}</strong>
            {#if e.date}<span class="muted">{fmtDate(e.date)}{e.end_date ? ` – ${fmtDate(e.end_date)}` : ''}</span>{/if}
            {#if e.type}<span class="chip">{label(e.type)}</span>{/if}
            {#if e.discipline}<span class="chip">{label(e.discipline)}</span>{/if}
            <span class="spacer"></span>
            {#if e.results_url}<a href={e.results_url} target="_blank" rel="noopener">Results ↗</a>{/if}
          </div>
          <div class="muted small">
            on <a href={mapHref(e.map)}>{e.map.name}</a>{e.map.location ? `, ${e.map.location}` : ''}{e.organiser ? ` · organised by ${e.organiser}` : ''}
            {#if e.courses?.length} · {e.courses.map((c) => c.name).join(', ')}{/if}
          </div>
        </li>
      {/each}
    </ul>
  {:else}
    <p class="empty">No events found.</p>
  {/each}
</main>

<style>
  .filters { display: flex; gap: .5rem; flex-wrap: wrap; margin: .5rem 0 1rem; align-items: center; }
  .filters input { flex: 1 1 260px; }
  .filters select { width: auto; }
  .list { list-style: none; padding: 0; margin: 0 0 1.25rem; }
  .list li { padding: .6rem .9rem; border-bottom: 1px solid var(--border); }
  .list li:last-child { border-bottom: 0; }
  .small { font-size: .85rem; }
</style>
