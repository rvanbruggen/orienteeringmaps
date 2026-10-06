<script>
  // Full-screen page viewer with wheel/pinch-free zoom (buttons, wheel) and drag to pan.
  let { pages = [], index = $bindable(0), open = $bindable(false), title = '' } = $props()
  let scale = $state(1), tx = $state(0), ty = $state(0)
  let dragging = null

  const page = $derived(pages[index])
  function reset() { scale = 1; tx = 0; ty = 0 }
  function step(d) { index = (index + d + pages.length) % pages.length; reset() }
  function zoom(f, cx = 0, cy = 0) {
    const ns = Math.min(12, Math.max(1, scale * f))
    const k = ns / scale
    tx = cx - (cx - tx) * k; ty = cy - (cy - ty) * k
    scale = ns
    if (scale === 1) { tx = 0; ty = 0 }
  }
  function onwheel(e) {
    e.preventDefault()
    const r = e.currentTarget.getBoundingClientRect()
    zoom(e.deltaY < 0 ? 1.2 : 1 / 1.2, e.clientX - r.left - r.width / 2, e.clientY - r.top - r.height / 2)
  }
  function onpointerdown(e) { dragging = { x: e.clientX - tx, y: e.clientY - ty }; e.currentTarget.setPointerCapture(e.pointerId) }
  function onpointermove(e) { if (dragging) { tx = e.clientX - dragging.x; ty = e.clientY - dragging.y } }
  function onkey(e) {
    if (!open) return
    if (e.key === 'Escape') open = false
    else if (e.key === 'ArrowRight' && pages.length > 1) step(1)
    else if (e.key === 'ArrowLeft' && pages.length > 1) step(-1)
    else if (e.key === '+' || e.key === '=') zoom(1.25)
    else if (e.key === '-') zoom(0.8)
  }
  $effect(() => { if (open) reset() })
</script>

<svelte:window onkeydown={onkey} />

{#if open && page}
  <div class="lb" role="dialog" aria-modal="true" aria-label={title || 'Page viewer'}>
    <div class="bar row">
      <strong>{title}</strong>
      {#if pages.length > 1}<span class="muted">page {page.page_no} / {pages.length}</span>{/if}
      <span class="spacer"></span>
      {#if pages.length > 1}
        <button onclick={() => step(-1)} aria-label="Previous page">‹</button>
        <button onclick={() => step(1)} aria-label="Next page">›</button>
      {/if}
      <button onclick={() => zoom(0.8)} aria-label="Zoom out">−</button>
      <button onclick={() => zoom(1.25)} aria-label="Zoom in">+</button>
      <button onclick={reset}>Fit</button>
      <a class="btn" href={page.image_url} target="_blank" rel="noopener">Open image</a>
      <button onclick={() => (open = false)} aria-label="Close">✕</button>
    </div>
    <div class="stage" {onwheel} {onpointerdown} {onpointermove}
      onpointerup={() => (dragging = null)} ondblclick={(e) => zoom(scale > 2 ? 1 / scale : 2.5)} role="presentation">
      <img src={page.image_url} alt="Page {page.page_no}" draggable="false"
        style="transform: translate({tx}px, {ty}px) scale({scale})" />
    </div>
  </div>
{/if}

<style>
  .lb { position: fixed; inset: 0; z-index: 200; background: rgb(15 15 15 / 94%); display: flex; flex-direction: column; color: #eee; }
  .bar { padding: .5rem .75rem; gap: .4rem; }
  .bar button, .bar .btn { background: #2a2a2a; color: #eee; border-color: #444; }
  .bar .muted { color: #aaa; }
  .stage { flex: 1; overflow: hidden; display: flex; align-items: center; justify-content: center; cursor: grab; touch-action: none; }
  .stage:active { cursor: grabbing; }
  img { max-width: 100%; max-height: 100%; object-fit: contain; transform-origin: center; user-select: none; background: #fff; }
</style>
