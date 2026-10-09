<script>
  // Import tasks: batches of scans, processed in the background and then reviewed one by one.
  import { onDestroy, onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { go } from '../lib/router.svelte.js'
  import { notify, refreshMeta } from '../lib/stores.svelte.js'
  import { fmtDate } from '../lib/format.js'

  let tasks = $state([]), loading = $state(true)
  let name = $state(''), byDate = $state(true), creating = $state(false)
  let timer

  async function load() {
    try { tasks = await api.get('/api/imports') } catch (e) { notify(e.message, 'error') }
    loading = false
    refreshMeta()
    clearTimeout(timer)
    if (tasks.some((t) => t.state === 'processing')) timer = setTimeout(load, 4000)
  }
  onMount(load)
  onDestroy(() => clearTimeout(timer))

  async function create(e) {
    e.preventDefault()
    creating = true
    try {
      const t = await api.post('/api/imports', { name: name.trim() || null, match_by_date: byDate })
      go(`/imports/${t.id}`)
    } catch (err) { notify(err.message, 'error') }
    creating = false
  }

  const STATE = { processing: 'Processing', review: 'To review', done: 'Done' }
</script>

<main class="page">
  <h1>Imports</h1>
  <p class="muted">Upload a batch of scans; they are processed on the server, so you can close the browser once the upload is done.
    When a file name starts with the date (<code>YYYYMMDD</code>), the scan is matched to your Strava run of that day,
    and filed on the map where it can be. Then you check each scan here.</p>

  <form class="card new" onsubmit={create}>
    <h2>New import</h2>
    <div class="row">
      <input bind:value={name} placeholder="Name, e.g. Archive 2005–2012" aria-label="Name of the import" />
      <label class="row check"><input type="checkbox" bind:checked={byDate} /> Match to Strava runs by the date in the file name</label>
      <span class="spacer"></span>
      <button class="primary" disabled={creating}>Create and add files</button>
    </div>
  </form>

  {#if loading}
    <p class="empty">Loading…</p>
  {:else if !tasks.length}
    <div class="empty card">No imports yet.</div>
  {:else}
    <div class="list">
      {#each tasks as t (t.id)}
        <a class="card task" href="#/imports/{t.id}">
          <div class="row">
            <strong>{t.name}</strong>
            <span class="chip {t.state === 'done' ? 'ok' : t.state === 'review' ? 'accent' : ''}">{STATE[t.state]}</span>
            <span class="spacer"></span>
            <span class="muted small">{fmtDate(t.created_at.slice(0, 10))}</span>
          </div>
          <div class="row stats">
            <span>{t.total} file{t.total === 1 ? '' : 's'}</span>
            {#if t.groups.waiting}<span>{t.processed} / {t.total} processed</span>{/if}
            {#if t.to_review}<span class="warn">{t.to_review} to review</span>{/if}
            {#if t.groups.error}<span class="err">{t.groups.error} failed</span>{/if}
            {#if t.groups.done}<span class="muted">{t.groups.done} done</span>{/if}
            {#if t.groups.aside}<span class="muted">{t.groups.aside} set aside</span>{/if}
          </div>
          {#if t.groups.waiting}<progress max={t.total} value={t.processed}></progress>{/if}
        </a>
      {/each}
    </div>
  {/if}
</main>

<style>
  .new { margin: 1rem 0 1.5rem; }
  .new h2 { margin: 0 0 .6rem; font-size: 1.05rem; }
  .new input:not([type]) { flex: 1 1 260px; }
  .check { font-size: .9rem; gap: .35rem; }
  .list { display: flex; flex-direction: column; gap: .75rem; }
  .task { color: var(--text); display: flex; flex-direction: column; gap: .4rem; }
  .task:hover { text-decoration: none; border-color: var(--accent); }
  .stats { font-size: .9rem; gap: .25rem 1rem; }
  .small { font-size: .85rem; }
  .warn { color: var(--warn); }
  .err { color: var(--danger); }
  progress { width: 100%; accent-color: var(--accent); }
  code { font-family: var(--mono); font-size: .9em; }
</style>
