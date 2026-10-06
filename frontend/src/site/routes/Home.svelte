<script>
  import { store, matches, mapHref } from '../data.svelte.js'
  import { route, go } from '../router.svelte.js'
  import { fmtDate, fmtScale, label } from '../../lib/format.js'
  import ExplorerMap from '../../components/ExplorerMap.svelte'

  // Search and filters live in the address, so a search can be shared as a link.
  const q = $derived(route.query.get('q') ?? '')
  const type = $derived(route.query.get('type') ?? '')
  const club = $derived(route.query.get('club') ?? '')
  const scale = $derived(route.query.get('scale') ?? '')
  const view = $derived(route.query.get('view') ?? 'map')
  const sort = $derived(route.query.get('sort') ?? 'name')

  function set(key, value) {
    const p = new URLSearchParams(route.query)
    if (value && !(key === 'view' && value === 'map') && !(key === 'sort' && value === 'name')) p.set(key, value)
    else p.delete(key)
    const s = p.toString()
    go(s ? `?${s}` : './', { replace: true })
  }

  const types = $derived([...new Set(store.maps.map((m) => m.type).filter(Boolean))].sort())
  const clubs = $derived([...new Set(store.maps.map((m) => m.club).filter(Boolean))].sort())
  const scales = $derived([...new Set(store.maps.map((m) => m.scale).filter(Boolean))].sort((a, b) => a - b))

  const filtered = $derived.by(() => {
    const out = store.maps.filter((m) => (!q || matches(m, q)) && (!type || m.type === type) &&
      (!club || m.club === club) && (!scale || String(m.scale) === scale))
    const by = {
      name: (a, b) => a.name.localeCompare(b.name),
      survey: (a, b) => (b.survey ?? '').localeCompare(a.survey ?? '') || a.name.localeCompare(b.name),
      event: (a, b) => (b.last_event ?? '').localeCompare(a.last_event ?? '') || a.name.localeCompare(b.name),
    }
    return out.sort(by[sort] ?? by.name)
  })
  const anyFilter = $derived(q || type || club || scale)
  let typed = $state(q)
  let timer
  function onsearch(e) {
    typed = e.target.value
    clearTimeout(timer)
    timer = setTimeout(() => set('q', typed.trim()), 200)
  }
</script>

<main class="page">
  <div class="intro">
    <h1>{store.site.title}</h1>
    {#if store.site.description}<p class="muted">{store.site.description}</p>{/if}
  </div>

  <div class="filters">
    <input class="search" type="search" placeholder="Search maps, places, clubs, events…" value={typed} oninput={onsearch} aria-label="Search" />
    {#if types.length > 1}
      <select value={type} onchange={(e) => set('type', e.target.value)} aria-label="Map type">
        <option value="">All types</option>
        {#each types as t}<option value={t}>{label(t)}</option>{/each}
      </select>
    {/if}
    {#if clubs.length > 1}
      <select value={club} onchange={(e) => set('club', e.target.value)} aria-label="Club">
        <option value="">All clubs</option>
        {#each clubs as c}<option value={c}>{c}</option>{/each}
      </select>
    {/if}
    {#if scales.length > 1}
      <select value={scale} onchange={(e) => set('scale', e.target.value)} aria-label="Scale">
        <option value="">All scales</option>
        {#each scales as s}<option value={String(s)}>{fmtScale(s)}</option>{/each}
      </select>
    {/if}
    {#if anyFilter}<button class="ghost small" onclick={() => { typed = ''; go('./', { replace: true }) }}>Clear</button>{/if}
    <span class="spacer"></span>
    <span class="muted">{filtered.length}{filtered.length !== store.maps.length ? ` of ${store.maps.length}` : ''} maps</span>
    <div class="seg" role="group" aria-label="View">
      <button class:on={view === 'map'} onclick={() => set('view', 'map')}>Map</button>
      <button class:on={view === 'list'} onclick={() => set('view', 'list')}>List</button>
    </div>
  </div>

  {#if !store.maps.length}
    <p class="empty">No maps published yet.</p>
  {:else if view === 'map'}
    <ExplorerMap maps={filtered} href={mapHref} open={(m) => go(mapHref(m))} storageKey="omaps.public" showUnlocated={false} />
  {:else if !filtered.length}
    <p class="empty">No maps match this search.</p>
  {:else}
    <div class="row sortrow">
      <span class="muted small">Sort by</span>
      <select value={sort} onchange={(e) => set('sort', e.target.value)} aria-label="Sort">
        <option value="name">Name</option>
        <option value="survey">Newest survey</option>
        <option value="event">Most recent event</option>
      </select>
    </div>
    <div class="cards">
      {#each filtered as m (m.id)}
        <a class="mapcard card" href={mapHref(m)}>
          <div class="img">{#if m.thumb}<img src={m.thumb} alt="" loading="lazy" />{:else}<span class="muted small">No image</span>{/if}</div>
          <div class="body">
            <strong>{m.name}</strong>
            <div class="muted small">{[m.location, m.club].filter(Boolean).join(' · ')}</div>
            <div class="chips">
              {#if m.type}<span class="chip">{label(m.type)}</span>{/if}
              {#if m.scale}<span class="chip">{fmtScale(m.scale)}</span>{/if}
              {#if m.survey}<span class="chip">survey {fmtDate(m.survey)}</span>{/if}
              {#if m.events.length}<span class="chip course">{m.events.length} event{m.events.length === 1 ? '' : 's'}</span>{/if}
            </div>
          </div>
        </a>
      {/each}
    </div>
  {/if}
</main>

<style>
  .intro h1 { margin-bottom: .2rem; }
  .filters { display: flex; gap: .5rem; flex-wrap: wrap; margin: .75rem 0 1rem; align-items: center; }
  .filters .search { flex: 1 1 260px; }
  .filters select { width: auto; flex: 0 1 170px; }
  .seg { display: inline-flex; border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }
  .seg button { border: 0; border-radius: 0; background: var(--surface); }
  .seg button.on { background: var(--surface-2); font-weight: 600; }
  .sortrow { margin-bottom: .75rem; }
  .sortrow select { width: auto; }
  .small { font-size: .85rem; }
  .chips { display: flex; gap: .25rem; flex-wrap: wrap; margin-top: .2rem; }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 1rem; }
  .mapcard { padding: 0; overflow: hidden; color: var(--text); display: flex; flex-direction: column; }
  .mapcard:hover { text-decoration: none; border-color: var(--muted); }
  .mapcard .img { aspect-ratio: 4 / 3; background: var(--surface-2); overflow: hidden; display: flex; align-items: center; justify-content: center; }
  .mapcard .img img { width: 100%; height: 100%; object-fit: cover; object-position: center 30%; }
  .mapcard .body { padding: .7rem .8rem .8rem; display: flex; flex-direction: column; gap: .2rem; }
</style>
