<script>
  import { meta } from '../lib/stores.svelte.js'
  import { isPartialDate, label, versionName } from '../lib/format.js'
  import ClubSelect from './ClubSelect.svelte'
  // versions: the map's versions, to move an existing event (with its courses and runs) to another one.
  let { event = $bindable(), prefix = 'e', versions = [] } = $props()
</script>

<div class="grid-form">
  {#if event.id && versions.length > 1}
    <label class="field wide"><span>Version <span class="hint">(moves the event with its courses and your runs)</span></span>
      <select bind:value={event.map_version_id}>
        {#each versions as v (v.id)}<option value={v.id}>{versionName(v)}</option>{/each}
      </select>
    </label>
  {/if}
  <label class="field wide"><span>Event name *</span><input bind:value={event.name} required /></label>
  <label class="field"><span>Date</span>
    <input bind:value={event.date} placeholder="2024-10-06" class:invalid={!isPartialDate(event.date)} />
  </label>
  <label class="field"><span>End date <span class="hint">(permanent courses)</span></span>
    <input bind:value={event.end_date} placeholder="optional" class:invalid={!isPartialDate(event.end_date)} />
  </label>
  <label class="field"><span>Type</span>
    <select bind:value={event.event_type}>
      <option value={null}>—</option>
      {#each meta.enums.event_types as t}<option value={t}>{label(t)}</option>{/each}
    </select>
  </label>
  <label class="field"><span>Discipline</span>
    <select bind:value={event.discipline}>
      <option value={null}>—</option>
      {#each meta.enums.disciplines as t}<option value={t}>{label(t)}</option>{/each}
    </select>
  </label>
  <label class="field"><span>Organiser</span><ClubSelect bind:value={event.organiser_club_id} id="{prefix}-org" /></label>
  <label class="field"><span>Results / Livelox link</span><input type="url" bind:value={event.results_url} placeholder="https://" /></label>
  <label class="field"><span>O’Punch race <span class="hint">(the number in opunch.org/in/event/…)</span></span>
    <input type="number" min="1" bind:value={event.opunch_id} placeholder="e.g. 3641" /></label>
  <label class="field wide"><span>Notes</span><textarea bind:value={event.notes} rows="2"></textarea></label>
</div>
