<script>
  // Every event on every map: your orienteering history at a glance.
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { notify } from '../lib/stores.svelte.js'
  import { fmtDate, label } from '../lib/format.js'

  let events = $state([]), loading = $state(true)
  let q = $state(''), year = $state(''), type = $state(''), mine = $state(false)

  onMount(async () => {
    try { events = await api.get('/api/events') } catch (e) { notify(e.message, 'error') }
    loading = false
  })

  const years = $derived([...new Set(events.map((e) => e.date?.slice(0, 4)).filter(Boolean))].sort().reverse())
  const types = $derived([...new Set(events.map((e) => e.event_type).filter(Boolean))].sort())
  const shown = $derived(events.filter((e) => {
    const t = q.trim().toLowerCase()
    return (!t || [e.name, e.map_name, e.map_location, e.organiser_name, ...e.course_names].some((v) => v?.toLowerCase().includes(t))) &&
      (!year || (year === 'undated' ? !e.date : e.date?.startsWith(year))) &&
      (!type || e.event_type === type) &&
      (!mine || e.run_dates?.length)
  }))
  // Group by year for the timeline layout.
  const groups = $derived.by(() => {
    const g = new Map()
    for (const e of shown) {
      const y = e.date?.slice(0, 4) ?? 'Undated'
      if (!g.has(y)) g.set(y, [])
      g.get(y).push(e)
    }
    return [...g.entries()]
  })
</script>

<main class="page">
  <div class="row head">
    <h1>Events</h1>
    <span class="muted">{shown.length}{shown.length !== events.length ? ` of ${events.length}` : ''} events</span>
  </div>
  <div class="filters">
    <input type="search" placeholder="Search event, map, club, course…" bind:value={q} />
    <select bind:value={year} aria-label="Year">
      <option value="">All years</option>
      {#each years as y}<option value={y}>{y}</option>{/each}
      <option value="undated">Undated</option>
    </select>
    <select bind:value={type} aria-label="Type">
      <option value="">All types</option>
      {#each types as t}<option value={t}>{label(t)}</option>{/each}
    </select>
    <label class="row mine"><input type="checkbox" bind:checked={mine} /> Only events I ran</label>
  </div>

  {#if loading}
    <p class="empty">Loading…</p>
  {:else if !events.length}
    <div class="empty card">No events yet. Add them on a map’s page, under one of its versions.</div>
  {:else}
    {#each groups as [y, list] (y)}
      <section class="year">
        <h2>{y} <span class="muted">{list.length}</span></h2>
        <div class="card list">
          {#each list as e (e.id)}
            <a class="ev" href="#/map/{e.map_id}">
              <span class="date num">{e.date ? fmtDate(e.date) : '—'}{e.end_date ? ` – ${fmtDate(e.end_date)}` : ''}</span>
              <span class="main">
                <strong>{e.name}</strong>
                <span class="muted small">{e.map_name}{e.map_location ? ` · ${e.map_location}` : ''}{e.organiser_name ? ` · ${e.organiser_name}` : ''}</span>
              </span>
              <span class="chips">
                {#if e.run_dates?.length}<span class="chip accent" title={e.run_dates.map(fmtDate).join(', ')}>You ran{e.run_dates.length > 1 ? ` ×${e.run_dates.length}` : ''}</span>{/if}
                {#if e.event_type}<span class="chip">{label(e.event_type)}</span>{/if}
                {#if e.discipline}<span class="chip">{label(e.discipline)}</span>{/if}
                {#each e.course_names.slice(0, 4) as c}<span class="chip course">{c}</span>{/each}
                {#if e.course_names.length > 4}<span class="chip course">+{e.course_names.length - 4}</span>{/if}
              </span>
            </a>
          {/each}
        </div>
      </section>
    {/each}
  {/if}
</main>

<style>
  .head { margin-bottom: .75rem; }
  .head h1 { margin: 0; }
  .filters { display: flex; gap: .5rem; flex-wrap: wrap; margin-bottom: 1rem; }
  .filters input { flex: 1 1 260px; }
  .filters select { width: auto; }
  .mine { font-size: .9rem; color: var(--muted); gap: .35rem; }
  .year { margin-bottom: 1.25rem; }
  .year h2 { font-size: 1.05rem; }
  .list { padding: 0; }
  .ev { display: grid; grid-template-columns: 9.5rem 1fr auto; gap: .75rem; align-items: center; padding: .55rem .9rem; border-bottom: 1px solid var(--border); color: var(--text); }
  .ev:last-child { border-bottom: 0; }
  .ev:hover { background: var(--surface-2); text-decoration: none; }
  .date { color: var(--muted); font-size: .9rem; }
  .main { display: flex; flex-direction: column; min-width: 0; }
  .small { font-size: .85rem; }
  .chips { display: flex; gap: .25rem; flex-wrap: wrap; justify-content: flex-end; }
  @media (max-width: 640px) {
    .ev { grid-template-columns: 1fr; gap: .2rem; }
    .chips { justify-content: flex-start; }
  }
</style>
