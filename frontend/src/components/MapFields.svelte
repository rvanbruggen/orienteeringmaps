<script>
  import { api } from '../lib/api.js'
  import { meta, notify } from '../lib/stores.svelte.js'
  import { label, PUBLISH_LEVELS } from '../lib/format.js'
  import ClubSelect from './ClubSelect.svelte'
  import TagInput from './TagInput.svelte'

  let { map = $bindable(), suggestedClubs = [], tagSuggestions = [], prefix = 'm' } = $props()
  let results = $state(null)
  let searching = $state(false)

  async function geocode() {
    const q = [map.location || map.name].filter(Boolean).join(' ')
    if (!q) return
    searching = true
    try { results = await api.get(`/api/geocode?q=${encodeURIComponent(q)}`) } catch (e) { notify(e.message, 'error') }
    searching = false
  }
  function pick(r) { map.lat = +r.lat.toFixed(6); map.lon = +r.lon.toFixed(6); results = null }
</script>

<div class="grid-form">
  <label class="field wide"><span>Map name *</span><input id="{prefix}-name" bind:value={map.name} required /></label>
  <label class="field"><span>Nearest village / town</span><input bind:value={map.location} /></label>
  <label class="field"><span>Map type</span>
    <select bind:value={map.map_type}>
      <option value={null}>—</option>
      {#each meta.enums.map_types as t}<option value={t}>{label(t)}</option>{/each}
    </select>
  </label>
  <label class="field"><span>Club (original mapper / owner)</span><ClubSelect bind:value={map.club_id} suggested={suggestedClubs} id="{prefix}-club" /></label>
  <div class="field coords">
    <span class="lbl">Coordinates <span class="hint">(centre of the map)</span></span>
    <div class="row nowrap">
      <input type="number" step="any" placeholder="lat" bind:value={map.lat} aria-label="Latitude" />
      <input type="number" step="any" placeholder="lon" bind:value={map.lon} aria-label="Longitude" />
      <button type="button" onclick={geocode} disabled={searching} title="Look up the location on OpenStreetMap">{searching ? '…' : 'Find'}</button>
    </div>
    {#if results}
      <ul class="results">
        {#each results as r}<li><button type="button" class="ghost small" onclick={() => pick(r)}>{r.name}</button></li>{/each}
        {#if !results.length}<li class="hint">No places found.</li>{/if}
      </ul>
    {/if}
  </div>
  <label class="field wide"><span>Tags</span><TagInput bind:tags={map.tags} id="{prefix}-tags" suggestions={tagSuggestions} /></label>
  <label class="field wide"><span>Notes <span class="hint">(private)</span></span><textarea bind:value={map.notes} rows="2"></textarea></label>
  <label class="field"><span>Public site</span>
    <select bind:value={map.publish_level}>
      {#each PUBLISH_LEVELS as l}<option value={l.value}>{l.label}</option>{/each}
    </select>
    <span class="hint">{PUBLISH_LEVELS.find((l) => l.value === (map.publish_level ?? 'private'))?.hint}</span>
  </label>
  {#if map.publish_level && map.publish_level !== 'private'}
    <label class="field wide"><span>Public note <span class="hint">(shown on the public site)</span></span><textarea bind:value={map.public_note} rows="2"></textarea></label>
  {/if}
</div>

<style>
  .coords { display: flex; flex-direction: column; gap: .2rem; font-size: .85rem; color: var(--muted); grid-column: span 2; }
  .lbl { font-weight: 500; }
  .nowrap { flex-wrap: nowrap; }
  .results { list-style: none; margin: .25rem 0 0; padding: 0; max-height: 10rem; overflow: auto; border: 1px solid var(--border); border-radius: 6px; }
  .results button { white-space: normal; text-align: left; width: 100%; }
  @media (max-width: 640px) { .coords { grid-column: 1 / -1; } }
</style>
