<script>
  import { uploadFile } from '../lib/api.js'
  import { notify, refreshMeta } from '../lib/stores.svelte.js'
  import FileTriage from '../components/FileTriage.svelte'

  const ACCEPT = '.pdf,.png,.jpg,.jpeg,.tif,.tiff,.webp,.heic,.heif,.gif,.bmp,application/pdf,image/*'
  let queue = $state([]) // {key, name, progress, phase, result, error}
  let dragging = $state(false)
  let input
  let running = false

  function add(fileList) {
    for (const file of fileList) {
      queue.push({ key: crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`, file, name: file.name, progress: 0, phase: 'waiting', result: null, error: null })
    }
    run()
  }

  // Upload one at a time: the server renders each file before answering.
  async function run() {
    if (running) return
    running = true
    let item
    while ((item = queue.find((q) => q.phase === 'waiting'))) {
      item.phase = 'uploading'
      try {
        const res = await uploadFile(item.file, (p) => {
          item.progress = p
          if (p >= 1) item.phase = 'processing'
        })
        item.result = res
        item.phase = res.status === 'error' ? 'error' : 'done'
        item.error = res.error
      } catch (e) {
        item.phase = 'error'
        item.error = e.message
      }
      item.file = null
    }
    running = false
    refreshMeta()
    const n = queue.filter((q) => q.phase === 'done' && q.result.status === 'created').length
    if (n) notify(`${n} file(s) added. File them below, or later from the inbox.`)
  }

  function ondrop(e) {
    e.preventDefault()
    dragging = false
    if (e.dataTransfer?.files?.length) add(e.dataTransfer.files)
  }
  const removeItem = (key) => (queue = queue.filter((q) => q.key !== key))
</script>

<main class="page">
  <h1>Add maps</h1>
  <p class="muted">PDFs and images (PNG, JPG, TIFF, HEIC, …). Each file is stored unchanged; pages are rendered and the text on the map is read to pre-fill the details.</p>
  <p class="muted">Many scans at once, or scans named by date (<code>YYYYMMDD …</code>) to match to your Strava runs? Use an <a href="#/imports">import</a>: it is processed on the server, and you review the scans afterwards.</p>

  <div class="drop" class:dragging role="button" tabindex="0"
    ondragover={(e) => { e.preventDefault(); dragging = true }} ondragleave={() => (dragging = false)} {ondrop}
    onclick={() => input.click()} onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && input.click()}>
    <strong>Drop files here</strong>
    <span class="muted">or click to choose — on a phone you can also take a photo</span>
    <input bind:this={input} type="file" multiple accept={ACCEPT} hidden onchange={(e) => { add(e.target.files); e.target.value = '' }} />
  </div>

  <div class="list">
    {#each queue as q (q.key)}
      {#if q.phase === 'done' && q.result.file}
        <FileTriage item={q.result} onfiled={() => removeItem(q.key)} ondeleted={() => removeItem(q.key)} />
      {:else}
        <div class="card pending row">
          <strong class="nm">{q.name}</strong>
          <span class="spacer"></span>
          {#if q.phase === 'error'}
            <span class="err">{q.error}</span><button class="small ghost" onclick={() => removeItem(q.key)}>Dismiss</button>
          {:else}
            <span class="muted">{q.phase === 'uploading' ? `Uploading ${Math.round(q.progress * 100)}%` : q.phase === 'processing' ? 'Rendering pages & reading text…' : 'Waiting'}</span>
            <progress max="1" value={q.phase === 'processing' ? undefined : q.progress}></progress>
          {/if}
        </div>
      {/if}
    {/each}
  </div>
</main>

<style>
  .drop {
    border: 2px dashed var(--border); border-radius: 12px; padding: 2.5rem 1rem; margin: 1rem 0 1.5rem;
    display: flex; flex-direction: column; align-items: center; gap: .3rem; cursor: pointer; background: var(--surface); text-align: center;
  }
  .drop:hover, .drop.dragging { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 6%, var(--surface)); }
  .list { display: flex; flex-direction: column; gap: .75rem; }
  .pending { padding: .7rem 1rem; }
  .nm { overflow-wrap: anywhere; }
  .err { color: var(--danger); font-size: .9rem; }
  progress { width: 140px; accent-color: var(--accent); }
  code { font-family: var(--mono); font-size: .9em; }
</style>
