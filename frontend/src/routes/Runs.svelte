<script>
  // Your Strava activities: connect, sync, and pick out the orienteering races.
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { notify } from '../lib/stores.svelte.js'
  import { route, go } from '../lib/router.svelte.js'
  import { fmtDuration, fmtDistance } from '../lib/format.js'

  let st = $state(null)
  let acts = $state([])
  let showAll = $state(false)
  let q = $state(''), year = $state('')
  let syncing = $state(''), loading = $state(true)

  async function loadStatus() { st = await api.get('/api/strava/status') }
  async function loadActs() { acts = await api.get(`/api/strava/activities${showAll ? '?all=true' : ''}`) }

  onMount(async () => {
    // Back from Strava's approval page.
    const err = route.query.get('error')
    if (err) { notify(err, 'error'); go('/runs') }
    try { await loadStatus(); if (st.connected) await loadActs() } catch (e) { notify(e.message, 'error') }
    loading = false
    if (route.query.get('connected')) {
      go('/runs')
      if (st?.connected) sync(false)
    }
  })

  async function sync(full) {
    syncing = 'Syncing…'
    let added = 0, updated = 0, cursor = null
    try {
      do {
        const r = await api.post('/api/strava/sync', { full, cursor })
        added += r.added; updated += r.updated; cursor = r.next
        syncing = `Syncing… ${added + updated} activities`
      } while (cursor)
      notify(added ? `${added} new activit${added === 1 ? 'y' : 'ies'} from Strava` : 'Up to date with Strava')
    } catch (e) { notify(e.message, 'error') }
    syncing = ''
    await Promise.all([loadStatus(), loadActs()]).catch((e) => notify(e.message, 'error'))
  }

  async function disconnect() {
    if (!confirm('Disconnect Strava? This revokes the app’s access and deletes all imported activities from this app (not from Strava).')) return
    try {
      const r = await api.post('/api/strava/disconnect')
      notify(`Disconnected; ${r.deleted} activities deleted`)
      acts = []
      await loadStatus()
    } catch (e) { notify(e.message, 'error') }
  }

  async function toggle(a) {
    try {
      const r = await api.patch(`/api/strava/activities/${a.id}`, { orienteering: !a.orienteering })
      Object.assign(a, r)
      if (!showAll && !r.orienteering) acts = acts.filter((x) => x.id !== a.id)
      await loadStatus()
    } catch (e) { notify(e.message, 'error') }
  }

  const years = $derived([...new Set(acts.map((a) => a.start_local?.slice(0, 4)).filter(Boolean))].sort().reverse())
  const shown = $derived(acts.filter((a) => {
    const t = q.trim().toLowerCase()
    return (!t || a.name.toLowerCase().includes(t)) && (!year || a.start_local?.startsWith(year))
  }))
  const when = (d) => d ? new Date(d).toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'never'
  const day = (s) => s ? new Date(s.slice(0, 10) + 'T12:00:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }) : ''
</script>

<main class="page">
  <div class="row head">
    <h1>Runs</h1>
    {#if st?.configured && st.connected}
      <span class="muted">{shown.length}{shown.length !== acts.length ? ` of ${acts.length}` : ''} {showAll ? 'activities' : 'orienteering runs'}</span>
      <span class="spacer"></span>
      <button class="primary" onclick={() => sync(false)} disabled={!!syncing}>{syncing || 'Sync from Strava'}</button>
    {/if}
  </div>

  {#if loading}
    <p class="empty">Loading…</p>
  {:else if !st?.configured}
    <section class="card setup">
      <h2>Connect your Strava account</h2>
      <p>Strava isn’t set up yet. To set it up:</p>
      <ol>
        <li>On <a href="https://www.strava.com/settings/api" target="_blank" rel="noopener">strava.com/settings/api</a>, create an API application (free; any name and website).</li>
        <li>Set its <strong>Authorization Callback Domain</strong> to <code>{location.hostname}</code>, the host name you use to open this app.</li>
        <li>Add the <strong>Client ID</strong> and <strong>Client Secret</strong> to <code>.env</code> on the Docker host as <code>OMAPS_STRAVA_CLIENT_ID</code> and <code>OMAPS_STRAVA_CLIENT_SECRET</code>, then run <code>docker compose up -d</code>.</li>
      </ol>
      <p class="hint">Your Strava data stays in this app. It is never put on the public site.</p>
    </section>
  {:else if !st.connected}
    <section class="card setup">
      <h2>Connect your Strava account</h2>
      <p>Import your activities to keep track of the races you ran. Later steps will link them to maps and draw your route on the map.</p>
      <p><a class="btn strava" href="/api/strava/connect">Connect with Strava</a></p>
      <p class="hint">On Strava’s page, keep “View data about your private activities” ticked, so races you didn’t share publicly are imported too. Your Strava data is never put on the public site.</p>
      {#if st.error}<p class="error">{st.error}</p>{/if}
    </section>
  {:else}
    <section class="card account row">
      {#if st.athlete?.profile}<img src={st.athlete.profile} alt="" class="avatar" />{/if}
      <div>
        <strong>{st.athlete?.name ?? 'Strava account'}</strong>
        <div class="muted small">
          {st.counts.activities} activities imported, {st.counts.orienteering} orienteering · last sync {when(st.last_sync)}
          {#if !st.private_activities} · <span class="warn">private activities are not shared with this app</span>{/if}
        </div>
        {#if st.error}<div class="error small">{st.error}</div>{/if}
      </div>
      <span class="spacer"></span>
      <button class="small" onclick={() => sync(true)} disabled={!!syncing} title="Fetch every activity again, to pick up renamed or edited ones">Re-sync all</button>
      <button class="small danger" onclick={disconnect} disabled={!!syncing}>Disconnect</button>
    </section>

    <div class="filters">
      <input type="search" placeholder="Search activity name…" bind:value={q} />
      <select bind:value={year} aria-label="Year">
        <option value="">All years</option>
        {#each years as y}<option value={y}>{y}</option>{/each}
      </select>
      <label class="row toggle"><input type="checkbox" bind:checked={showAll} onchange={() => loadActs().catch((e) => notify(e.message, 'error'))} /> Show all activities</label>
    </div>

    {#if !acts.length}
      <div class="empty card">
        {#if showAll}No activities yet. Press “Sync from Strava”.
        {:else}No orienteering runs found yet. Runs with “orienteering”, “oriëntatie”, “HITTA” or “Mapico” in the title are picked out automatically; tick “Show all activities” to mark others yourself.{/if}
      </div>
    {:else}
      <div class="card list">
        {#each shown as a (a.id)}
          <div class="act" class:dim={!a.orienteering}>
            <span class="date num">{day(a.start_local)}</span>
            <span class="main">
              <strong>{a.name}</strong>
              <span class="muted small">
                {a.sport_type}{a.race ? ' · race' : ''}{a.private ? ' · private' : ''} ·
                <a href={a.strava_url} target="_blank" rel="noopener" class="strava-link">View on Strava</a>
              </span>
            </span>
            <span class="stats num">
              <span>{fmtDistance(a.distance_m)}</span>
              <span>{fmtDuration(a.moving_time_s)}</span>
              {#if a.elevation_gain_m}<span class="muted">↑{Math.round(a.elevation_gain_m)} m</span>{/if}
            </span>
            <label class="o" title={a.orienteering_manual ? 'Set by you' : 'Detected from the name'}>
              <input type="checkbox" checked={a.orienteering} onchange={() => toggle(a)} />
              Orienteering
            </label>
          </div>
        {/each}
      </div>
    {/if}
  {/if}
</main>

<style>
  .head { margin-bottom: .75rem; }
  .head h1 { margin: 0; }
  .setup { max-width: 760px; }
  .setup ol { padding-left: 1.2rem; line-height: 1.6; }
  .btn.strava { background: #fc5200; border-color: #fc5200; color: #fff; font-weight: 600; }
  .btn.strava:hover { filter: brightness(1.06); }
  .account { margin-bottom: 1rem; gap: .75rem; }
  .avatar { width: 40px; height: 40px; border-radius: 50%; }
  .small { font-size: .85rem; }
  .warn { color: var(--warn); }
  .error { color: var(--danger); }
  .filters { display: flex; gap: .5rem; flex-wrap: wrap; margin-bottom: 1rem; align-items: center; }
  .filters input[type='search'] { flex: 1 1 260px; }
  .filters select { width: auto; }
  .toggle { font-size: .9rem; color: var(--muted); gap: .35rem; }
  .list { padding: 0; }
  .act { display: grid; grid-template-columns: 10rem 1fr auto auto; gap: .75rem; align-items: center; padding: .55rem .9rem; border-bottom: 1px solid var(--border); }
  .act:last-child { border-bottom: 0; }
  .act.dim strong { font-weight: 500; color: var(--muted); }
  .date { color: var(--muted); font-size: .9rem; }
  .main { display: flex; flex-direction: column; min-width: 0; }
  .strava-link { color: #fc5200; }
  .stats { display: flex; gap: .75rem; font-size: .9rem; }
  .o { display: flex; align-items: center; gap: .3rem; font-size: .85rem; color: var(--muted); cursor: pointer; }
  @media (max-width: 720px) {
    .act { grid-template-columns: 1fr auto; gap: .25rem .75rem; }
    .date, .main { grid-column: 1 / -1; }
  }
</style>
