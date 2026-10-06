<script>
  import { fmtScale, parseScale } from '../lib/format.js'
  // files: [{id, original_name, page_count}] that the course may point at
  let { course = $bindable(), files = [] } = $props()
  const selected = $derived(files.find((f) => f.id === course.file_id))
</script>

<div class="grid-form">
  <label class="field wide"><span>Course name *</span><input bind:value={course.name} placeholder="e.g. Kort, H21E, Blauw" required /></label>
  <label class="field"><span>Length (km)</span><input type="number" step="0.1" min="0" bind:value={course.length_km} /></label>
  <label class="field"><span>Climb (m)</span><input type="number" step="5" min="0" bind:value={course.climb_m} /></label>
  <label class="field"><span>Controls</span><input type="number" min="0" bind:value={course.controls} /></label>
  <label class="field"><span>Print scale {#if course.scale}<span class="hint">{fmtScale(course.scale)}</span>{/if}</span>
    <input value={course.scale ?? ''} placeholder="if different" onchange={(e) => (course.scale = parseScale(e.target.value))} />
  </label>
  <label class="field"><span>File</span>
    <select bind:value={course.file_id}>
      <option value={null}>—</option>
      {#each files as f}<option value={f.id}>{f.original_name}</option>{/each}
    </select>
  </label>
  {#if selected && selected.page_count > 1}
    <label class="field"><span>Page</span><input type="number" min="1" max={selected.page_count} bind:value={course.page_no} /></label>
  {/if}
  <label class="field wide"><span>Notes</span><textarea bind:value={course.notes} rows="2"></textarea></label>
</div>
