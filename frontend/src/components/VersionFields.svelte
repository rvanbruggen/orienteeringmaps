<script>
  import { meta } from '../lib/stores.svelte.js'
  import { fmtScale, isPartialDate, parseScale } from '../lib/format.js'
  let { version = $bindable() } = $props()
</script>

<div class="grid-form">
  <label class="field"><span>Survey date</span>
    <input bind:value={version.survey_date} placeholder="2021 · 2021-05 · 2021-05-14" class:invalid={!isPartialDate(version.survey_date)} />
  </label>
  <label class="field"><span>Scale {#if version.scale}<span class="hint">{fmtScale(version.scale)}</span>{/if}</span>
    <input value={version.scale ?? ''} placeholder="e.g. 1:10000" onchange={(e) => (version.scale = parseScale(e.target.value))} />
  </label>
  <label class="field"><span>Contour interval (m)</span>
    <input type="number" step="0.5" min="0" bind:value={version.contour_interval} />
  </label>
  <label class="field"><span>Cartographer</span><input bind:value={version.cartographer} /></label>
  <label class="field"><span>Mapping standard</span>
    <select bind:value={version.standard}>
      <option value={null}>—</option>
      {#each meta.enums.standards as s}<option value={s}>{s}</option>{/each}
    </select>
  </label>
  <label class="field"><span>Version label</span><input bind:value={version.label} placeholder="e.g. v3.1, 2nd edition" /></label>
  <label class="field wide"><span>Notes</span><textarea bind:value={version.notes} rows="2"></textarea></label>
</div>
