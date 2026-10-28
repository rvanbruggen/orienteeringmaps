<script>
  // Mark a page, or a part of it, as a result card: drag a box over the card, or take the whole page.
  import { api } from '../lib/api.js'
  import { notify } from '../lib/stores.svelte.js'
  import Modal from './Modal.svelte'

  let { page = null, title = '', open = $bindable(false), onsaved } = $props()
  let box = $state(null) // [x0, y0, x1, y1] image pixels
  let drag = null
  let img = $state()
  let busy = $state(false)

  $effect(() => { if (open && page) box = page.result_card_box ? [...page.result_card_box] : null })

  function toImage(e) {
    const r = img.getBoundingClientRect()
    const k = page.width / r.width
    return [Math.max(0, Math.min(page.width, (e.clientX - r.left) * k)), Math.max(0, Math.min(page.height, (e.clientY - r.top) * k))]
  }
  function onpointerdown(e) {
    e.preventDefault()
    drag = toImage(e)
    box = [...drag, ...drag]
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  function onpointermove(e) {
    if (!drag) return
    const [x, y] = toImage(e)
    box = [Math.min(drag[0], x), Math.min(drag[1], y), Math.max(drag[0], x), Math.max(drag[1], y)]
  }
  function onpointerup(e) {
    onpointermove(e)
    drag = null
    if (box && (box[2] - box[0] < 10 || box[3] - box[1] < 10)) box = null // a click, not a box
  }

  async function save(data, msg) {
    busy = true
    try {
      await api.patch(`/api/pages/${page.id}`, data)
      notify(msg)
      open = false
      onsaved?.()
    } catch (e) { notify(e.message, 'error') }
    busy = false
  }
  const pct = (v, total) => `${(v / total) * 100}%`
</script>

<Modal {title} bind:open wide>
  {#if page}
    <p class="muted small">Drag a box around the result card on this page, or mark the whole page. A page that is all
      result card is not part of the map: it is not placed and does not show on the overview.</p>
    <div class="stage">
      <div class="frame" {onpointerdown} {onpointermove} {onpointerup} role="presentation">
        <img bind:this={img} src={page.image_url} alt="Page {page.page_no}" draggable="false" />
        {#if box}
          <div class="box" style="left: {pct(box[0], page.width)}; top: {pct(box[1], page.height)}; width: {pct(box[2] - box[0], page.width)}; height: {pct(box[3] - box[1], page.height)}"></div>
        {:else if page.result_card && !page.result_card_box}
          <div class="box whole"></div>
        {/if}
      </div>
    </div>
  {/if}
  {#snippet footer()}
    {#if page?.result_card}
      <button class="danger" disabled={busy} onclick={() => save({ result_card: false }, 'No longer a result card')}>Not a result card</button>
    {/if}
    <span class="spacer"></span>
    <button onclick={() => (open = false)}>Cancel</button>
    <button disabled={busy} onclick={() => save({ result_card: true, result_card_box: null }, 'The whole page is a result card')}
      title="The whole page is a result card, not part of the map">Whole page</button>
    <button class="primary" disabled={busy || !box} onclick={() => save({ result_card: true, result_card_box: box }, 'Result card marked')}>Save box</button>
  {/snippet}
</Modal>

<style>
  .small { font-size: .85rem; margin-top: 0; }
  .stage { display: flex; justify-content: center; background: var(--surface-2); border-radius: 6px; padding: .5rem; }
  .frame { position: relative; cursor: crosshair; touch-action: none; user-select: none; line-height: 0; }
  .frame img { max-width: 100%; max-height: 65vh; background: #fff; display: block; }
  .box { position: absolute; border: 2px solid var(--accent); background: color-mix(in srgb, var(--accent) 15%, transparent); pointer-events: none; }
  .box.whole { inset: 0; }
</style>
