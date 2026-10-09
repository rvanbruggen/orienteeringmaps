<script>
  // Races from the O'Punch calendar: everything seen since the daily pull began (plus the backfill),
  // which ones you ran, and which map event each one is.
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { notify } from '../lib/stores.svelte.js'
  import { fmtDate, label } from '../lib/format.js'
  import Modal from '../components/Modal.svelte'

  let st = $state(null), races = $state([]), events = $state(null), loading = $state(true)
  let q = $state(''), year = $state(''), ran = $state(false), when = $state('past'), club = $state('')
  let pulling = $state(false), busy = $state(null)
  let linking = $state(null), linkOpen = $state(false), eventSel = $state(''), eventQ = $state('')
  let openId = $state(null)

  const today = new Date().toISOString().slice(0, 10)

  async function load() {
    try { [st, races] = await Promise.all([api.get('/api/opunch/status'), api.get('/api/opunch/races')]) } catch (e) { notify(e.message, 'error') }
    loading = false
  }
  onMount(load)

  async function pull() {
    pulling = true
    try {
      const r = await api.post('/api/opunch/pull')
      notify(r.added ? `${r.added} new race${r.added === 1 ? '' : 's'} from O’Punch (${r.in_feed} in the calendar)` : `Up to date: ${r.in_feed} races in the calendar, none new`)
      await load()
    } catch (e) { notify(e.message, 'error') }
    pulling = false
  }

  function replace(r) {
    const i = races.findIndex((x) => x.id === r.id)
    if (i >= 0) races[i] = r
  }

  async function toggleRan(r) {
    busy = r.id
    try { replace(await api.patch(`/api/opunch/races/${r.id}`, { ran: !r.ran })) } catch (e) { notify(e.message, 'error') }
    busy = null
  }

  async function details(r) {
    busy = r.id
    try { replace(await api.post(`/api/opunch/races/${r.id}/details`)); openId = r.id } catch (e) { notify(e.message, 'error') }
    busy = null
  }

  async function startLink(r) {
    linking = r
    eventSel = ''
    eventQ = ''
    linkOpen = true
    if (!events) {
      try { events = await api.get('/api/events') } catch (e) { notify(e.message, 'error'); events = [] }
    }
  }

  // Events of the library that could be this race: same date first, then by name, then the rest.
  const candidates = $derived.by(() => {
    if (!linking || !events) return []
    const t = eventQ.trim().toLowerCase()
    const words = linking.name.toLowerCase().split(/\W+/).filter((w) => w.length > 3)
    const score = (e) => (e.date === linking.date ? 4 : e.date?.slice(0, 7) === linking.date.slice(0, 7) ? 1 : 0) +
      words.filter((w) => `${e.name} ${e.map_name} ${e.map_location ?? ''}`.toLowerCase().includes(w)).length
    return events
      .filter((e) => !e.opunch_id || e.opunch_id === linking.id)
      .filter((e) => !t || `${e.name} ${e.map_name} ${e.map_location ?? ''}`.toLowerCase().includes(t))
      .map((e) => ({ e, s: score(e) }))
      .sort((a, b) => b.s - a.s || (b.e.date ?? '').localeCompare(a.e.date ?? ''))
      .slice(0, t ? 40 : 12)
      .map((x) => x.e)
  })

  async function saveLink() {
    if (!eventSel) return
    busy = linking.id
    try {
      replace(await api.post(`/api/opunch/races/${linking.id}/link`, { event_id: +eventSel }))
      events = null // the event now carries the race
      notify('Race tied to the event')
      linkOpen = false
    } catch (e) { notify(e.message, 'error') }
    busy = null
  }

  async function unlink(r, ev) {
    busy = r.id
    try {
      await api.del(`/api/opunch/races/${r.id}/link/${ev.id}`)
      replace(await api.get(`/api/opunch/races/${r.id}`))
      events = null
    } catch (e) { notify(e.message, 'error') }
    busy = null
  }

  const years = $derived([...new Set(races.map((r) => r.date.slice(0, 4)))].sort().reverse())
  const clubs = $derived([...new Set(races.map((r) => r.club_name).filter(Boolean))].sort())
  const shown = $derived(races.filter((r) => {
    const t = q.trim().toLowerCase()
    return (!t || [r.name, r.venue, r.town, r.club_name, r.map_name, ...r.events.map((e) => e.map_name)].some((v) => v?.toLowerCase().includes(t))) &&
      (!year || r.date.startsWith(year)) &&
      (!club || r.club_name === club) &&
      (when === 'all' || (when === 'past' ? r.date <= today : r.date >= today)) &&
      (!ran || r.you_ran)
  }))
  const groups = $derived.by(() => {
    const g = new Map()
    for (const r of shown) {
      const k = when === 'upcoming' ? 'Coming up' : r.date.slice(0, 4)
      if (!g.has(k)) g.set(k, [])
      g.get(k).push(r)
    }
    return [...g.entries()]
  })
  const LEVEL = { local: 'LOC', regional: 'REG', national: 'NAT' }
  const timeOf = (s) => s?.slice(11) ?? ''
  const whenText = (d) => d ? new Date(d).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : 'never'
</script>

<main class="page">
  <div class="row head">
    <h1>Races</h1>
    <span class="muted">{shown.length}{shown.length !== races.length ? ` of ${races.length}` : ''} races from O’Punch</span>
    <span class="spacer"></span>
    <button class="primary" onclick={pull} disabled={pulling}>{pulling ? 'Pulling…' : 'Pull calendar now'}</button>
  </div>

  {#if loading}
    <p class="empty">Loading…</p>
  {:else}
    {#if st}
      <section class="card status row">
        <div>
          <strong>O’Punch calendar</strong>
          <div class="muted small">
            {st.counts.races} races kept ({st.counts.past} past), {st.counts.ran} you ran, {st.counts.linked} tied to a map event ·
            last pull {whenText(st.last_pull)}{st.auto_pull ? ', once a day by itself' : ' (automatic pull is off)'}
          </div>
          {#if st.error}<div class="error small">Last pull failed: {st.error}</div>{/if}
          {#if !st.counts.past}
            <div class="hint">The calendar only lists upcoming races, so history builds up from now on. For the past year, run <code>python -m app.cli opunch-backfill</code> once on the server (see the README).</div>
          {/if}
        </div>
      </section>
    {/if}

    <div class="filters">
      <input type="search" placeholder="Search race, venue, town, club, map…" bind:value={q} />
      <select bind:value={when} aria-label="Past or upcoming">
        <option value="past">Past</option>
        <option value="upcoming">Upcoming</option>
        <option value="all">All</option>
      </select>
      <select bind:value={year} aria-label="Year">
        <option value="">All years</option>
        {#each years as y}<option value={y}>{y}</option>{/each}
      </select>
      {#if clubs.length}
        <select bind:value={club} aria-label="Club">
          <option value="">All clubs</option>
          {#each clubs as c}<option value={c}>{c}</option>{/each}
        </select>
      {/if}
      <label class="row mine"><input type="checkbox" bind:checked={ran} /> Only races I ran</label>
    </div>

    {#if !races.length}
      <div class="empty card">No races yet. Press “Pull calendar now” to read the O’Punch calendar.</div>
    {:else if !shown.length}
      <div class="empty card">No races match.</div>
    {:else}
      {#each groups as [y, list] (y)}
        <section class="year">
          <h2>{y} <span class="muted">{list.length}</span></h2>
          <div class="card list">
            {#each list as r (r.id)}
              <div class="race" class:open={openId === r.id} class:dim={when === 'all' && r.date > today}>
                <span class="date num">{fmtDate(r.date)}{r.end_date ? ` – ${fmtDate(r.end_date)}` : ''}{#if timeOf(r.start) && timeOf(r.start) !== '00:00'}<br /><span class="small">{timeOf(r.start)}</span>{/if}</span>
                <span class="main">
                  <button class="ghost title" onclick={() => (openId = openId === r.id ? null : r.id)} title="Show details">
                    <strong>{r.name}</strong>
                  </button>
                  <span class="muted small">
                    {[r.venue, r.town, r.club_name].filter(Boolean).join(' · ')}
                    {#if r.map_name} · map: {r.map_name}{/if}
                  </span>
                  {#if r.events.length}
                    <span class="small links">
                      {#each r.events as e (e.id)}
                        <a href="#/map/{e.map_id}">{e.map_name}{e.name !== r.name ? ` · ${e.name}` : ''}</a>
                        <button class="ghost tiny" title="Untie this event from the race" onclick={() => unlink(r, e)} disabled={busy === r.id}>✕</button>
                      {/each}
                    </span>
                  {/if}
                </span>
                <span class="chips">
                  {#if r.you_ran}<span class="chip accent">You ran</span>{/if}
                  {#if r.level_name}<span class="chip" title="{label(r.level_name)} level">{LEVEL[r.level_name]}</span>{/if}
                  {#if r.registrations}<span class="chip" title="Registrations on O’Punch">{r.registrations} reg.</span>{/if}
                  {#if r.lat == null}<span class="chip warn" title="O’Punch gives no coordinates for this race">no location</span>{/if}
                </span>
                <span class="actions">
                  <label class="o" title="Tick the races you ran, also when the map isn’t in the library yet">
                    <input type="checkbox" checked={r.ran || r.events.some((e) => e.runs)} onchange={() => toggleRan(r)} disabled={busy === r.id || (!r.ran && r.events.some((e) => e.runs))} />
                    I ran this
                  </label>
                  <button class="small" onclick={() => startLink(r)} disabled={busy === r.id}>{r.events.length ? 'Tie another…' : 'Tie to event…'}</button>
                  <a class="btn small" href={r.url} target="_blank" rel="noopener">O’Punch ↗</a>
                </span>
                {#if openId === r.id}
                  <div class="details">
                    {#if r.description}<p class="desc">{r.description}</p>{/if}
                    {#if r.location}<p class="muted small loc">{r.location}</p>{/if}
                    <div class="row small wrap">
                      {#if r.lat != null}<span class="muted num">{r.lat.toFixed(5)}, {r.lon.toFixed(5)}</span>{/if}
                      {#if r.results_url && r.date <= today}<a href={r.results_url} target="_blank" rel="noopener">Results ↗</a>{/if}
                      {#if r.splits_url && r.date <= today}<a href={r.splits_url} target="_blank" rel="noopener">Split times ↗</a>{/if}
                      <span class="spacer"></span>
                      {#if r.has_details}
                        <span class="muted">Club, level, map and results read from the race’s page.</span>
                        <button class="small ghost" onclick={() => details(r)} disabled={busy === r.id}>Read again</button>
                      {:else}
                        <button class="small" onclick={() => details(r)} disabled={busy === r.id}>{busy === r.id ? 'Reading…' : 'Read club, level, map and results from O’Punch'}</button>
                      {/if}
                    </div>
                  </div>
                {/if}
              </div>
            {/each}
          </div>
        </section>
      {/each}
    {/if}
  {/if}
</main>

<Modal title="Tie the race to an event" bind:open={linkOpen}>
  {#if linking}
    <p><strong>{linking.name}</strong> <span class="muted">{fmtDate(linking.date)}{linking.town ? ` · ${linking.town}` : ''}</span></p>
    <p class="muted small">Pick the event in the library that is this race. The event’s date, organiser and results link are filled in from the race where they are empty, and the map gets the race’s location if it has none. To make a new event, link your run on the Runs page, or add the event on the map’s page.</p>
    {#if events === null}
      <p class="muted">Loading events…</p>
    {:else}
      <input type="search" placeholder="Search events by name or map…" bind:value={eventQ} />
      <div class="cands">
        {#each candidates as e (e.id)}
          <label class="opt">
            <input type="radio" name="ev" value={String(e.id)} bind:group={eventSel} />
            <span>
              <strong>{e.name}</strong>
              <span class="muted small">{e.date ? fmtDate(e.date) : 'undated'} · {e.map_name}{e.map_location ? ` · ${e.map_location}` : ''}</span>
              {#if e.date === linking.date}<span class="chip ok">same day</span>{/if}
              {#if e.opunch_id === linking.id}<span class="chip accent">already tied</span>{/if}
            </span>
          </label>
        {/each}
        {#if !candidates.length}<p class="muted small">No events match.</p>{/if}
      </div>
    {/if}
  {/if}
  {#snippet footer()}
    <button onclick={() => (linkOpen = false)}>Cancel</button>
    <button class="primary" onclick={saveLink} disabled={!eventSel || busy !== null}>Tie to event</button>
  {/snippet}
</Modal>

<style>
  .head { margin-bottom: .75rem; }
  .head h1 { margin: 0; }
  .status { margin-bottom: 1rem; }
  .small { font-size: .85rem; }
  .error { color: var(--danger); }
  .hint { font-size: .85rem; color: var(--muted); margin-top: .35rem; }
  .filters { display: flex; gap: .5rem; flex-wrap: wrap; margin-bottom: 1rem; align-items: center; }
  .filters input { flex: 1 1 260px; }
  .filters select { width: auto; }
  .mine { font-size: .9rem; color: var(--muted); gap: .35rem; }
  .year { margin-bottom: 1.25rem; }
  .year h2 { font-size: 1.05rem; }
  .list { padding: 0; }
  .race { display: grid; grid-template-columns: 9.5rem 1fr auto auto; gap: .35rem .75rem; align-items: center; padding: .55rem .9rem; border-bottom: 1px solid var(--border); }
  .race:last-child { border-bottom: 0; }
  .race.open { background: var(--surface-2); }
  .race.dim .title strong { color: var(--muted); font-weight: 500; }
  .date { color: var(--muted); font-size: .9rem; line-height: 1.3; }
  .main { display: flex; flex-direction: column; min-width: 0; align-items: flex-start; }
  .title { padding: 0; text-align: left; border: 0; }
  .title:hover { text-decoration: underline; background: none; }
  .links { display: flex; gap: .25rem; flex-wrap: wrap; align-items: center; }
  .tiny { padding: 0 .3rem; font-size: .75rem; line-height: 1.2; }
  .chips { display: flex; gap: .25rem; flex-wrap: wrap; justify-content: flex-end; }
  .actions { display: flex; gap: .4rem; align-items: center; justify-content: flex-end; flex-wrap: wrap; }
  .o { display: flex; align-items: center; gap: .3rem; font-size: .85rem; color: var(--muted); cursor: pointer; white-space: nowrap; }
  .details { grid-column: 1 / -1; padding: .25rem 0 .35rem; }
  .desc { white-space: pre-line; margin: 0 0 .5rem; font-size: .92rem; max-height: 14rem; overflow-y: auto; }
  .loc { white-space: pre-line; margin: 0 0 .5rem; }
  .wrap { flex-wrap: wrap; gap: .75rem; }
  .cands { max-height: 50vh; overflow-y: auto; margin-top: .5rem; }
  .opt { display: flex; gap: .55rem; align-items: flex-start; padding: .35rem .5rem; border-radius: 6px; cursor: pointer; }
  .opt:hover { background: var(--surface-2); }
  .opt input { margin-top: .25rem; width: auto; flex: none; }
  .opt .chip { margin-left: .25rem; }
  @media (max-width: 800px) {
    .race { grid-template-columns: 1fr; gap: .2rem; }
    .chips, .actions { justify-content: flex-start; }
  }
</style>
