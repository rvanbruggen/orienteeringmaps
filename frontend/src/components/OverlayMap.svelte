<script>
  // Shows placed pages of a map over the base maps, one at a time, with opacity.
  import { onMount, onDestroy, untrack } from 'svelte'
  import L from 'leaflet'
  import { addBasemaps } from '../lib/basemaps.js'
  import { WarpedImage, pixelsToLatLons } from '../lib/warp.js'

  // overlays: [{key, label, page_id, image_url, width, height, corners, clip}]
  let { overlays = [], adjustable = true } = $props()
  let el = $state()
  let map, layer
  let current = $state() // selected overlay key; defaults to the first
  let opacity = $state(0.75)
  let outline = $state(true)
  let outlineLayer

  const active = $derived(overlays.find((o) => o.key === current) ?? overlays[0])

  onMount(() => {
    map = L.map(el, { maxZoom: 22, zoomSnap: 0.5, scrollWheelZoom: true })
    addBasemaps(map)
    if (active) map.fitBounds(L.latLngBounds(active.corners), { padding: [20, 20] })
    show()
  })
  onDestroy(() => map?.remove())

  function show() {
    if (!map) return
    layer?.remove()
    outlineLayer?.remove()
    const o = active
    if (!o) return
    layer = new WarpedImage(o.image_url, o.width, o.height, o.corners, { opacity, clip: o.clip }).addTo(map)
    const ring = o.clip?.length >= 3 ? pixelsToLatLons(o.width, o.height, o.corners, o.clip) : o.corners
    if (outline) outlineLayer = L.polygon(ring, { color: '#a626a4', weight: 1.5, fill: false, dashArray: '4 4', interactive: false }).addTo(map)
  }

  $effect(() => {
    void [active?.key, outline]
    untrack(show)
  })
  $effect(() => {
    const o = opacity
    untrack(() => layer?.setOpacity(o))
  })

  function zoomTo() { if (active) map.fitBounds(L.latLngBounds(active.corners), { padding: [20, 20] }) }
</script>

<div class="wrap">
  <div class="controls row">
    {#if overlays.length > 1}
      <select bind:value={current} aria-label="Placed page">
        {#each overlays as o}<option value={o.key}>{o.label}</option>{/each}
      </select>
    {:else if active}
      <span class="muted small">{active.label}</span>
    {/if}
    <label class="inline">Opacity <input type="range" min="0" max="1" step="0.05" bind:value={opacity} /></label>
    <label class="inline"><input type="checkbox" bind:checked={outline} /> Outline</label>
    <button class="small" onclick={zoomTo}>Zoom to map</button>
    <span class="spacer"></span>
    {#if active && adjustable}<a class="btn small" href="#/place/{active.page_id}">Adjust placement</a>{/if}
  </div>
  <div class="leaf" bind:this={el}></div>
</div>

<style>
  .wrap { border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; background: var(--surface); box-shadow: var(--shadow); }
  .controls { padding: .45rem .6rem; border-bottom: 1px solid var(--border); gap: .6rem; }
  .controls select { width: auto; max-width: 280px; }
  .inline { display: inline-flex; align-items: center; gap: .35rem; font-size: .88rem; white-space: nowrap; }
  .inline input[type='range'] { width: 110px; accent-color: var(--accent); }
  .small { font-size: .85rem; }
  .leaf { height: min(65vh, 560px); background: #e8e6e1; }
</style>
