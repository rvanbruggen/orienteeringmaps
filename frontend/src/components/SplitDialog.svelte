<script>
  // Split a PDF that holds several maps: click between two pages to cut there. The file keeps the
  // first part; every other part becomes a file of its own in the inbox.
  import { api } from '../lib/api.js'
  import { notify, refreshMeta } from '../lib/stores.svelte.js'
  import Modal from './Modal.svelte'

  let { file, open = $bindable(false), onsplit } = $props()
  let cuts = $state([]) // page numbers that start a new part
  let busy = $state(false)

  $effect(() => { if (open) cuts = [] })

  const parts = $derived.by(() => {
    const out = []
    for (const p of file.pages) {
      if (!out.length || cuts.includes(p.page_no)) out.push([])
      out[out.length - 1].push(p.page_no)
    }
    return out
  })
  const partOf = (no) => parts.findIndex((ps) => ps.includes(no))
  const range = (ps) => ps.length === 1 ? `p${ps[0]}` : `p${ps[0]}–${ps[ps.length - 1]}`
  const toggle = (no) => (cuts = cuts.includes(no) ? cuts.filter((c) => c !== no) : [...cuts, no])

  async function split() {
    busy = true
    try {
      const files = await api.post(`/api/files/${file.id}/split`, { parts })
      await refreshMeta()
      notify(`Split into ${files.length} files`)
      open = false
      onsplit?.(files)
    } catch (e) { notify(e.message, 'error') }
    busy = false
  }
</script>

<Modal title="Split {file.original_name}" bind:open wide>
  <p class="muted small">When this PDF holds more than one map, click between two pages to cut it there.
    {file.map_version_id ? 'This map keeps the first part' : 'The first part stays here'}; every other part becomes
    a file of its own in the inbox, to make a new map of or add to another one. Placements, submaps, result cards
    and courses go along with their pages.</p>
  <div class="strip">
    {#each file.pages as p, i (p.id)}
      {#if i}
        <button class="cut" class:on={cuts.includes(p.page_no)} onclick={() => toggle(p.page_no)}
          title={cuts.includes(p.page_no) ? 'Join these pages again' : `Cut between page ${p.page_no - 1} and ${p.page_no}`}
          aria-label="Cut before page {p.page_no}" aria-pressed={cuts.includes(p.page_no)}>✂</button>
      {/if}
      <figure class="pg part{partOf(p.page_no) % 4}">
        <img src={p.thumb_url} alt="Page {p.page_no}" loading="lazy" />
        <figcaption>p{p.page_no}</figcaption>
      </figure>
    {/each}
  </div>
  {#if parts.length > 1}
    <ul class="plan small">
      {#each parts as ps, i}
        <li><span class="dot part{i % 4}"></span>{range(ps)} — {i ? 'new file in the inbox' : file.map_version_id ? 'stays on this map' : 'stays in the inbox'}</li>
      {/each}
    </ul>
  {/if}
  {#snippet footer()}
    <button onclick={() => (open = false)}>Cancel</button>
    <button class="primary" disabled={busy || parts.length < 2} onclick={split}>
      {parts.length < 2 ? 'Split' : `Split into ${parts.length} files`}</button>
  {/snippet}
</Modal>

<style>
  .small { font-size: .85rem; margin-top: 0; }
  .strip { display: flex; flex-wrap: wrap; align-items: center; gap: .25rem 0; }
  .pg { margin: 0; padding: 3px; border-radius: 5px; border-bottom: 4px solid var(--c); text-align: center; }
  .pg img { width: 72px; height: 96px; object-fit: cover; display: block; border: 1px solid var(--border); background: #fff; }
  .pg figcaption { font-size: .75rem; color: var(--muted); }
  .cut { padding: 0 .3rem; height: 96px; border: none; background: none; color: var(--border); font-size: .9rem; cursor: pointer; }
  .cut:hover { color: var(--muted); }
  .cut.on { color: var(--danger); border-left: 2px dashed currentColor; border-radius: 0; }
  .plan { list-style: none; padding: 0; margin: .75rem 0 0; display: flex; flex-direction: column; gap: .2rem; }
  .dot { display: inline-block; width: .7rem; height: .7rem; border-radius: 50%; background: var(--c); margin-right: .4rem; vertical-align: middle; }
  .part0 { --c: var(--accent); }
  .part1 { --c: #2a7ab8; }
  .part2 { --c: #3a9a4a; }
  .part3 { --c: #a626a4; }
</style>
