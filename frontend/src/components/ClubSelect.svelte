<script>
  // Club dropdown with inline "new club" creation. Suggested names that are not
  // yet in the club list are offered as one-click additions.
  import { api } from '../lib/api.js'
  import { clubs, refreshClubs, notify } from '../lib/stores.svelte.js'

  let { value = $bindable(), suggested = [], id } = $props()

  const missing = $derived(suggested.filter((n) => !clubs.list.some((c) =>
    [c.name.toLowerCase(), (c.short_name || '').toLowerCase()].includes(n.toLowerCase()))))

  async function create(name) {
    name = (name ?? prompt('Name of the new club'))?.trim()
    if (!name) return
    try {
      const club = await api.post('/api/clubs', { name, short_name: name.length <= 8 && name === name.toUpperCase() ? name : null })
      await refreshClubs()
      value = club.id
    } catch (e) { notify(e.message, 'error') }
  }

  function onchange(e) {
    if (e.target.value === '__new') { e.target.value = value ?? ''; create() }
    else value = e.target.value ? +e.target.value : null
  }
</script>

<select {id} value={value ?? ''} {onchange}>
  <option value="">—</option>
  {#each clubs.list as c (c.id)}<option value={c.id}>{c.name}{c.short_name && c.short_name !== c.name ? ` (${c.short_name})` : ''}</option>{/each}
  <option value="__new">+ New club…</option>
</select>
{#if missing.length}
  <span class="hint">Found on map:
    {#each missing as n}<button type="button" class="small ghost" onclick={() => create(n)}>+ {n}</button>{/each}
  </span>
{/if}
