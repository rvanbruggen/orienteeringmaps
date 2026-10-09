<script>
  // One import task: add files (upload or the server's import folder), follow the background
  // processing, and review every scan until it is on the right map with the right run.
  import { onDestroy, onMount } from 'svelte'
  import { api, uploadFile } from '../lib/api.js'
  import { go } from '../lib/router.svelte.js'
  import { notify, refreshMeta } from '../lib/stores.svelte.js'
  import { fmtBytes, fmtDate, fmtDistance, fmtDuration } from '../lib/format.js'
  import Modal from '../components/Modal.svelte'
  import Lightbox from '../components/Lightbox.svelte'
  import LinkRunDialog from '../components/LinkRunDialog.svelte'
  import AttachDialog from '../components/AttachDialog.svelte'
  import NewMapDialog from '../components/NewMapDialog.svelte'

  let { id } = $props()

  const ACCEPT = '.pdf,.png,.jpg,.jpeg,.tif,.tiff,.webp,.heic,.heif,.gif,.bmp,application/pdf,image/*'
  const SECTIONS = [
    { key: 'choose', title: 'Choose the run', help: 'More than one run on that day: which one was it?' },
    { key: 'check', title: 'Check', help: 'Filed for you: is the scan on the right map, with the right run and event?' },
    { key: 'link', title: 'Link the run', help: 'One run that day, but its route is not on a placed map: link it to the map you ran. The scan goes along.' },
    { key: 'file', title: 'No run found', help: 'No date in the name, no run that day, or before your Strava history: choose a run by hand, put the scan on a map, or set it aside.' },
    { key: 'error', title: 'Failed', help: '' },
    { key: 'waiting', title: 'Waiting to be processed', help: '' },
    { key: 'aside', title: 'Set aside', help: '', closed: true },
    { key: 'done', title: 'Done', help: '', closed: true },
  ]

  let task = $state(null), loading = $state(true), busy = $state(false)
  let queue = $state([])        // uploads: {key, file, name, progress, phase, error}
  let dragging = $state(false), input = $state(null)
  let folders = $state([]), folder = $state('')
  let renaming = $state(false), newName = $state('')
  let timer, uploading = false

  // Dialogs work on one item at a time.
  let current = $state(null)
  let linkOpen = $state(false), attachOpen = $state(false), newMapOpen = $state(false)
  let viewer = $state(false), pageIdx = $state(0), viewed = $state(null)
  let pickOpen = $state(false), pickDay = $state(''), pickRuns = $state(null)

  const byGroup = $derived(groupBy(task?.items ?? []))
  const pending = $derived(queue.filter((q) => q.phase === 'waiting' || q.phase === 'uploading').length)
  function groupBy(items) {
    const out = {}
    for (const i of items) (out[i.group] ??= []).push(i)
    return out
  }

  async function load() {
    clearTimeout(timer)
    try { task = await api.get(`/api/imports/${id}`) } catch (e) { notify(e.message, 'error'); loading = false; return }
    loading = false
    refreshMeta()  // the worker files scans meanwhile: keep the inbox and review counts current
    if (task.state === 'processing') timer = setTimeout(load, 3000)
  }
  const warnLeave = (e) => { if (pending) { e.preventDefault(); e.returnValue = '' } }
  onMount(async () => {
    window.addEventListener('beforeunload', warnLeave)
    await load()
    try { folders = (await api.get('/api/imports/folders')).folders } catch { folders = [] }
  })
  onDestroy(() => { clearTimeout(timer); window.removeEventListener('beforeunload', warnLeave) })

  // --- adding files ---------------------------------------------------------------------
  function add(fileList) {
    for (const file of fileList) queue.push({ key: crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`, file, name: file.name, progress: 0, phase: 'waiting', error: null })
    upload()
  }
  // One at a time: each request only stores the file, the server processes it later.
  async function upload() {
    if (uploading) return
    uploading = true
    let q, n = 0
    while ((q = queue.find((x) => x.phase === 'waiting'))) {
      q.phase = 'uploading'
      try {
        await uploadFile(q.file, (p) => (q.progress = p), `/api/imports/${id}/files`)
        q.phase = 'done'
      } catch (e) { q.phase = 'error'; q.error = e.message }
      q.file = null
      if (++n % 10 === 0) load()
    }
    uploading = false
    const failed = queue.filter((x) => x.phase === 'error')
    queue = failed
    await load()
    if (!failed.length) notify('Upload done. Processing continues on the server: you can close this page.')
  }
  function ondrop(e) {
    e.preventDefault()
    dragging = false
    if (e.dataTransfer?.files?.length) add(e.dataTransfer.files)
  }
  async function addFolder() {
    busy = true
    try {
      const r = await api.post(`/api/imports/${id}/folder`, { path: folder })
      notify(r.added ? `${r.added} file${r.added === 1 ? '' : 's'} added from the import folder` : 'No new files in that folder')
      await load()
    } catch (e) { notify(e.message, 'error') }
    busy = false
  }

  // --- the task -------------------------------------------------------------------------
  async function rename(e) {
    e.preventDefault()
    try { Object.assign(task, await api.patch(`/api/imports/${id}`, { name: newName })); renaming = false } catch (err) { notify(err.message, 'error') }
  }
  async function remove() {
    if (!confirm(`Delete the import “${task.name}”? Files already processed stay in the library; files still waiting are dropped.`)) return
    try { await api.del(`/api/imports/${id}`); await refreshMeta(); go('/imports') } catch (e) { notify(e.message, 'error') }
  }

  // --- items ----------------------------------------------------------------------------
  async function act(fn) {
    busy = true
    try { const t = await fn(); if (t?.items) task = t; else await load(); refreshMeta() } catch (e) { notify(e.message, 'error') }
    busy = false
  }
  const review = (item, value) => act(() => api.put(`/api/imports/items/${item.id}/review`, { review: value }))
  const setRun = (item, activityId) => act(() => api.put(`/api/imports/items/${item.id}/run`, { activity_id: activityId }))
  const retry = (item) => act(() => api.post(`/api/imports/items/${item.id}/retry`))
  const dropItem = (item) => act(() => api.del(`/api/imports/items/${item.id}`))

  function view(item) { viewed = item.file; pageIdx = 0; viewer = true }
  function openLink(item) { current = item; linkOpen = true }
  function openAttach(item) { current = item; attachOpen = true }
  function openNewMap(item) { current = item; newMapOpen = true }
  async function openPick(item) {
    current = item
    pickDay = item.day ?? item.activity?.start_local?.slice(0, 10) ?? ''
    pickOpen = true
    await loadRuns()
  }
  async function loadRuns() {
    pickRuns = null
    if (!/^\d{4}-\d{2}-\d{2}$/.test(pickDay)) { pickRuns = []; return }
    try { pickRuns = await api.get(`/api/imports/items/${current.id}/runs?around=${pickDay}&days=3`) } catch (e) { notify(e.message, 'error'); pickRuns = [] }
  }
  async function choose(activityId) {
    pickOpen = false
    await setRun(current, activityId)
  }
  // Filed by you in a dialog: that counts as checked.
  async function filed() { if (current) await review(current, 'confirmed') }
  async function linked(a) { if (a?.link) await filed(); else await load() }

  const runLine = (a) => [fmtDate(a.start_local?.slice(0, 10)), a.start_local?.slice(11, 16), fmtDistance(a.distance_m), fmtDuration(a.moving_time_s)].filter(Boolean).join(' · ')
</script>

<main class="page">
  {#if loading}
    <p class="empty">Loading…</p>
  {:else if task}
    <p class="crumbs"><a href="#/imports">Imports</a></p>
    <div class="row title">
      {#if renaming}
        <form class="row" onsubmit={rename}><input bind:value={newName} aria-label="Name" /><button class="primary">Save</button><button type="button" class="ghost" onclick={() => (renaming = false)}>Cancel</button></form>
      {:else}
        <h1>{task.name}</h1>
        <button class="ghost small" onclick={() => { newName = task.name; renaming = true }}>Rename</button>
      {/if}
      <span class="spacer"></span>
      <button class="ghost danger small" onclick={remove}>Delete import</button>
    </div>
    <p class="muted">
      {task.total} file{task.total === 1 ? '' : 's'}
      {#if task.match_by_date} · matched to Strava runs by the date in the file name{:else} · not matched to runs{/if}
      {#if task.to_review} · <strong class="warn">{task.to_review} to review</strong>{:else if task.total && task.state === 'done'} · <strong class="ok">all reviewed</strong>{/if}
    </p>

    {#if task.state === 'processing'}
      <div class="card progress">
        <div class="row"><strong>Processing on the server</strong><span class="spacer"></span><span class="muted">{task.processed} / {task.total}</span></div>
        <progress max={task.total} value={task.processed}></progress>
        <p class="hint">Rendering pages and reading the text takes a few seconds to a minute per scan. You can close this page; come back later to review.</p>
      </div>
    {/if}

    <div class="adders">
      <div class="drop" class:dragging role="button" tabindex="0"
        ondragover={(e) => { e.preventDefault(); dragging = true }} ondragleave={() => (dragging = false)} {ondrop}
        onclick={() => input.click()} onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && input.click()}>
        <strong>Drop scans here</strong>
        <span class="muted">or click to choose. Only the upload needs this page; processing happens on the server.</span>
        <input bind:this={input} type="file" multiple accept={ACCEPT} hidden onchange={(e) => { add(e.target.files); e.target.value = '' }} />
      </div>
      {#if folders.length}
        <div class="card folder">
          <strong>From the server’s import folder</strong>
          <span class="muted small">Read in place, without uploading.</span>
          <div class="row">
            <select bind:value={folder} aria-label="Folder">
              {#each folders as f}<option value={f.path}>{f.path || '(the whole import folder)'} — {f.files} file{f.files === 1 ? '' : 's'}</option>{/each}
            </select>
            <button onclick={addFolder} disabled={busy}>Add</button>
          </div>
        </div>
      {/if}
    </div>

    {#if queue.length}
      <div class="card uploads">
        {#if pending}
          {@const cur = queue.find((q) => q.phase === 'uploading')}
          <div class="row"><strong>Uploading</strong><span class="muted">{pending} to go — keep this page open until the upload is done</span>
            <span class="spacer"></span>{#if cur}<span class="muted small nm">{cur.name} {Math.round(cur.progress * 100)}%</span>{/if}</div>
          <progress max={queue.length} value={queue.length - pending}></progress>
        {/if}
        {#each queue.filter((q) => q.phase === 'error') as q (q.key)}
          <div class="row"><span class="nm">{q.name}</span><span class="err small">{q.error}</span><span class="spacer"></span>
            <button class="small ghost" onclick={() => (queue = queue.filter((x) => x.key !== q.key))}>Dismiss</button></div>
        {/each}
      </div>
    {/if}

    {#if !task.total}
      <div class="empty card">No files yet. Drop scans above{folders.length ? ', or add a folder from the server' : ''}.</div>
    {/if}

    {#each SECTIONS as sec (sec.key)}
      {@const items = byGroup[sec.key] ?? []}
      {#if items.length}
        <details class="section" open={!sec.closed}>
          <summary><h2>{sec.title} <span class="count">{items.length}</span></h2></summary>
          {#if sec.help}<p class="muted small help">{sec.help}</p>{/if}
          {#if sec.key === 'waiting'}
            <p class="names muted small">{items.map((i) => (i.status === 'processing' ? `${i.original_name} (processing…)` : i.original_name)).join(' · ')}</p>
          {:else}
            <div class="items">
              {#each items as item (item.id)}
                {@const f = item.file}
                {@const a = item.activity}
                <article class="card item">
                  <button class="thumb" onclick={() => f && view(item)} disabled={!f?.thumb_url} aria-label="View {item.original_name}">
                    {#if f?.thumb_url}<img src={f.thumb_url} alt="" loading="lazy" />{/if}
                  </button>
                  <div class="info">
                    <div class="row">
                      <strong class="nm">{item.original_name}</strong>
                      {#if item.day}<span class="chip">{fmtDate(item.day)}</span>{/if}
                      {#if item.status === 'duplicate'}<span class="chip warn" title="This file was in the library already">already in the library</span>{/if}
                      {#if item.outcome === 'auto_linked'}<span class="chip accent">linked for you</span>{/if}
                      {#if f}<span class="muted small">{fmtBytes(f.size_bytes)}</span>{/if}
                    </div>
                    {#if item.error}<p class="err small">{item.error}</p>{/if}
                    {#if a}
                      <p class="run">
                        <span class="muted">Run</span> <a href={a.strava_url} target="_blank" rel="noopener">{a.name}</a>
                        <span class="muted small">{runLine(a)}</span>
                        {#if a.link}<br /><span class="muted">Linked to</span> <a href="#/map/{a.link.map_id}">{a.link.map_name}</a> · {a.link.event_name}{a.link.course_name ? ` · ${a.link.course_name}` : ''}{/if}
                      </p>
                    {/if}
                    {#if f?.map_id && f.map_id !== a?.link?.map_id}
                      <p class="run"><span class="muted">Scan on</span> <a href="#/map/{f.map_id}">{f.map_name}</a></p>
                    {/if}
                    {#if item.note && sec.key !== 'done'}<p class="muted small note">{item.note}</p>{/if}

                    <div class="row actions">
                      {#if sec.key === 'choose'}
                        {#each item.candidates as c (c.id)}
                          <button onclick={() => setRun(item, c.id)} disabled={busy}><strong>{c.name}</strong> <span class="muted small">{runLine(c)}</span></button>
                        {/each}
                        <button class="ghost" onclick={() => openPick(item)}>Another run…</button>
                      {:else if sec.key === 'check'}
                        <button class="primary" onclick={() => review(item, 'confirmed')} disabled={busy}>Looks right</button>
                        {#if a}<button onclick={() => openLink(item)}>Change the link…</button>{/if}
                        <button class="ghost" onclick={() => openPick(item)}>Another run…</button>
                      {:else if sec.key === 'link'}
                        <button class="primary" onclick={() => openLink(item)}>Link the run…</button>
                        <button class="ghost" onclick={() => openPick(item)}>Not this run…</button>
                        <button class="ghost" onclick={() => openAttach(item)}>Only add the scan to a map…</button>
                      {:else if sec.key === 'file'}
                        <button onclick={() => openPick(item)}>Choose a run…</button>
                        <button onclick={() => openAttach(item)}>Add to a map…</button>
                        <button onclick={() => openNewMap(item)}>New map…</button>
                        <button class="ghost" onclick={() => review(item, 'set_aside')} disabled={busy}>Set aside</button>
                      {:else if sec.key === 'error'}
                        {#if item.can_retry}<button onclick={() => retry(item)} disabled={busy}>Try again</button>{/if}
                        <button class="ghost" onclick={() => dropItem(item)} disabled={busy}>Remove from import</button>
                      {:else if sec.key === 'aside'}
                        <button class="ghost" onclick={() => review(item, 'open')} disabled={busy}>Back to review</button>
                      {:else if sec.key === 'done'}
                        <button class="ghost small" onclick={() => review(item, 'open')} disabled={busy}>Review again</button>
                      {/if}
                      {#if f && sec.key !== 'done'}<a class="btn ghost" href={f.original_url} target="_blank" rel="noopener">Original</a>{/if}
                    </div>
                  </div>
                </article>
              {/each}
            </div>
          {/if}
        </details>
      {/if}
    {/each}
  {/if}
</main>

<Lightbox pages={viewed?.pages ?? []} bind:index={pageIdx} bind:open={viewer} title={viewed?.original_name ?? ''} />
{#if current?.activity}
  <LinkRunDialog activity={current.activity} scan={current.file} bind:open={linkOpen} onsaved={linked} />
{/if}
{#if current?.file}
  <AttachDialog file={current.file} bind:open={attachOpen} ondone={filed} />
  <NewMapDialog files={[current.file]} bind:open={newMapOpen} oncreated={filed} />
{/if}
<Modal title="Choose the run" bind:open={pickOpen}>
  {#if current}
    <p class="muted small">Runs and walks within three days of the date. Scan: {current.original_name}</p>
    <div class="row">
      <input type="date" bind:value={pickDay} aria-label="Date" />
      <button onclick={loadRuns}>Show runs</button>
    </div>
    {#if pickRuns === null}
      <p class="muted">Looking…</p>
    {:else if !pickRuns.length}
      <p class="muted">No runs around that date.</p>
    {:else}
      <div class="picks">
        {#each pickRuns as r (r.id)}
          <button class="pick" class:on={r.id === current.activity?.id} onclick={() => choose(r.id)}>
            <strong>{r.name}</strong><span class="muted small">{runLine(r)}{r.link ? ` · linked to ${r.link.map_name}` : ''}</span>
          </button>
        {/each}
      </div>
    {/if}
    {#if current.activity}
      <p><button class="ghost" onclick={() => choose(null)}>No run: take this scan off its run</button></p>
    {/if}
  {/if}
</Modal>

<style>
  .crumbs { margin: 0 0 .25rem; font-size: .9rem; }
  .title h1 { margin: 0; }
  .small { font-size: .85rem; }
  .warn { color: var(--warn); }
  .ok { color: var(--ok); }
  .err { color: var(--danger); margin: 0; }
  .progress, .uploads { margin: 1rem 0; display: flex; flex-direction: column; gap: .4rem; }
  progress { width: 100%; accent-color: var(--accent); }
  .adders { display: grid; grid-template-columns: 1fr auto; gap: .75rem; margin: 1rem 0 1.25rem; }
  .drop {
    border: 2px dashed var(--border); border-radius: 12px; padding: 1.6rem 1rem;
    display: flex; flex-direction: column; align-items: center; gap: .3rem; cursor: pointer; background: var(--surface); text-align: center;
  }
  .drop:hover, .drop.dragging { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 6%, var(--surface)); }
  .folder { display: flex; flex-direction: column; gap: .4rem; justify-content: center; max-width: 360px; }
  .folder select { max-width: 260px; }
  .section { margin-top: 1.25rem; }
  .section summary { cursor: pointer; list-style: none; }
  .section summary::-webkit-details-marker { display: none; }
  .section summary h2 { display: inline; font-size: 1.15rem; }
  .section summary::before { content: '▸'; display: inline-block; width: 1.1rem; color: var(--muted); transition: transform .15s; }
  .section[open] summary::before { transform: rotate(90deg); }
  .count { font-size: .85rem; color: var(--muted); font-weight: 500; }
  .help { margin: .3rem 0 .6rem; }
  .names { overflow-wrap: anywhere; }
  .items { display: flex; flex-direction: column; gap: .6rem; }
  .item { display: grid; grid-template-columns: 96px 1fr; gap: 1rem; align-items: start; padding: .8rem 1rem; }
  .thumb { padding: 0; border: 1px solid var(--border); border-radius: 6px; overflow: hidden; background: var(--surface-2); aspect-ratio: 3 / 4; width: 96px; }
  .thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .info { min-width: 0; display: flex; flex-direction: column; gap: .35rem; }
  .nm { overflow-wrap: anywhere; }
  .run, .note { margin: 0; font-size: .92rem; }
  .actions { margin-top: .2rem; }
  .picks { display: flex; flex-direction: column; gap: .4rem; margin: .75rem 0; }
  .pick { display: flex; flex-direction: column; align-items: flex-start; text-align: left; gap: .1rem; }
  .pick.on { border-color: var(--accent); }
  @media (max-width: 640px) {
    .adders { grid-template-columns: 1fr; }
    .folder { max-width: none; }
    .item { grid-template-columns: 64px 1fr; }
    .thumb { width: 64px; }
  }
</style>
