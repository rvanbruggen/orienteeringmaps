<script>
  // One uploaded / inbox file with its suggestions and the actions to file it.
  import { api } from '../lib/api.js'
  import { go } from '../lib/router.svelte.js'
  import { notify, refreshMeta } from '../lib/stores.svelte.js'
  import { fmtBytes, fmtContour, fmtDate, fmtScale, fmtKm } from '../lib/format.js'
  import Lightbox from './Lightbox.svelte'
  import NewMapDialog from './NewMapDialog.svelte'
  import AttachDialog from './AttachDialog.svelte'
  import Modal from './Modal.svelte'

  // item: {status, file, similar, candidate_maps}
  let { item, onfiled, ondeleted } = $props()
  let viewer = $state(false), pageIdx = $state(0)
  let newOpen = $state(false), attachOpen = $state(false), textOpen = $state(false), text = $state('')

  const f = $derived(item.file)
  const s = $derived(f.suggestions || {})

  async function showText() {
    text = (await api.get(`/api/files/${f.id}/text`)).text || '(no text found)'
    textOpen = true
  }
  async function remove() {
    if (!confirm(`Permanently delete “${f.original_name}” from the library? This removes the stored file.`)) return
    try {
      await api.del(`/api/files/${f.id}`)
      await refreshMeta()
      ondeleted?.(f)
    } catch (e) { notify(e.message, 'error') }
  }
</script>

<article class="card triage">
  <button class="thumb" onclick={() => { pageIdx = 0; viewer = true }} aria-label="View {f.original_name}">
    {#if f.thumb_url}<img src={f.thumb_url} alt="" />{/if}
    {#if f.page_count > 1}<span class="pages">{f.page_count} pages</span>{/if}
  </button>
  <div class="info">
    <div class="row">
      <strong class="fname">{f.original_name}</strong>
      <span class="chip">{f.format.toUpperCase()} · {fmtBytes(f.size_bytes)}</span>
      {#if f.text_source === 'ocr'}<span class="chip" title="Text was read from the image with OCR">OCR</span>{/if}
    </div>

    {#if item.status === 'duplicate'}
      <p class="warn">Already in the library{f.map_name ? ` — on “${f.map_name}”` : ' (in the inbox)'}.
        {#if f.map_id}<a href="#/map/{f.map_id}">Open map</a>{/if}</p>
    {:else}
      <div class="sugg">
        {#if s.name}<span><span class="muted">Name</span> {s.name}</span>{/if}
        {#if s.location && s.location !== s.name}<span><span class="muted">Near</span> {s.location}</span>{/if}
        {#if s.scale}<span><span class="muted">Scale</span> {fmtScale(s.scale)}</span>{/if}
        {#if s.contour_interval}<span><span class="muted">Contours</span> {fmtContour(s.contour_interval)}</span>{/if}
        {#if s.survey_date}<span><span class="muted">Survey</span> {fmtDate(s.survey_date)}</span>{/if}
        {#if s.cartographer}<span><span class="muted">Drawn by</span> {s.cartographer}</span>{/if}
        {#if s.clubs?.length}<span><span class="muted">Club</span> {s.clubs.join(', ')}</span>{/if}
        {#if s.course}<span class="chip course">course {s.course.name}{s.course.length_km ? ` · ${fmtKm(s.course.length_km)}` : ''}</span>{/if}
        {#if s.kind === 'manual'}<span class="chip">manual</span>{/if}
        {#each s.tags || [] as t}<span class="chip accent">{t}</span>{/each}
        {#if f.exif_lat != null}<span class="chip" title="{f.exif_lat}, {f.exif_lon}">📍 GPS in photo</span>{/if}
      </div>
      {#if item.similar?.length}
        <p class="warn">Looks similar to:
          {#each item.similar.slice(0, 3) as sim, i}{i ? ', ' : ''}{#if sim.map_id}<a href="#/map/{sim.map_id}">{sim.original_name}</a>{:else}{sim.original_name}{/if}{/each}
        </p>
      {/if}
      {#if item.candidate_maps?.length}
        <p class="muted small">Possibly the same map as: {item.candidate_maps.map((c) => c.name).join(', ')}</p>
      {/if}
      <div class="row actions">
        <button class="primary" onclick={() => (newOpen = true)}>New map</button>
        <button onclick={() => (attachOpen = true)}>Add to existing map…</button>
        <button class="ghost" onclick={showText}>Text</button>
        <a class="btn ghost" href={f.original_url} target="_blank" rel="noopener">Original</a>
        <span class="spacer"></span>
        <button class="ghost danger" onclick={remove}>Delete</button>
      </div>
    {/if}
  </div>
</article>

<Lightbox pages={f.pages} bind:index={pageIdx} bind:open={viewer} title={f.original_name} />
<NewMapDialog files={[f]} bind:open={newOpen} oncreated={(m) => { onfiled?.(f); go(`/map/${m.id}`) }} />
<AttachDialog file={f} candidates={item.candidate_maps || []} bind:open={attachOpen} ondone={(m) => { onfiled?.(f); go(`/map/${m.id}`) }} />
<Modal title="Text found in {f.original_name}" bind:open={textOpen}>
  <pre class="text">{text}</pre>
</Modal>

<style>
  .triage { display: grid; grid-template-columns: 120px 1fr; gap: 1rem; align-items: start; }
  .thumb { padding: 0; border: 1px solid var(--border); border-radius: 6px; overflow: hidden; position: relative; background: var(--surface-2); aspect-ratio: 3 / 4; width: 120px; }
  .thumb img { width: 100%; height: 100%; object-fit: cover; }
  .pages { position: absolute; bottom: 4px; right: 4px; font-size: .7rem; background: rgb(0 0 0 / 65%); color: #fff; padding: 0 .35rem; border-radius: 4px; }
  .info { min-width: 0; display: flex; flex-direction: column; gap: .5rem; }
  .fname { overflow-wrap: anywhere; }
  .sugg { display: flex; flex-wrap: wrap; gap: .35rem 1rem; font-size: .9rem; align-items: center; }
  .warn { color: var(--warn); margin: 0; font-size: .9rem; }
  .small { font-size: .85rem; margin: 0; }
  .actions { margin-top: .25rem; }
  .text { white-space: pre-wrap; font-family: var(--mono); font-size: .8rem; margin: 0; }
  @media (max-width: 560px) {
    .triage { grid-template-columns: 80px 1fr; }
    .thumb { width: 80px; }
  }
</style>
