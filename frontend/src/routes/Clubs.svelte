<script>
  import { onMount } from 'svelte'
  import { api, pick } from '../lib/api.js'
  import { clubs, notify, refreshClubs } from '../lib/stores.svelte.js'

  const KEYS = ['name', 'short_name', 'federation', 'website', 'notes']
  let editing = $state(null) // {id|null, ...fields}

  onMount(refreshClubs)

  async function save() {
    try {
      if (editing.id) await api.patch(`/api/clubs/${editing.id}`, pick(editing, KEYS))
      else await api.post('/api/clubs', pick(editing, KEYS))
      editing = null
      await refreshClubs()
    } catch (e) { notify(e.message, 'error') }
  }
  async function remove(c) {
    if (!confirm(`Delete club “${c.name}”? ${c.map_count} map(s) will keep existing without a club.`)) return
    try { await api.del(`/api/clubs/${c.id}`); await refreshClubs() } catch (e) { notify(e.message, 'error') }
  }
</script>

<main class="page">
  <div class="row head">
    <h1>Clubs</h1>
    <span class="spacer"></span>
    <button class="primary" onclick={() => (editing = { id: null, name: '', short_name: '', federation: '', website: '', notes: '' })}>+ New club</button>
  </div>

  {#if editing}
    <form class="card edit" onsubmit={(e) => { e.preventDefault(); save() }}>
      <div class="grid-form">
        <label class="field"><span>Name *</span><input bind:value={editing.name} required /></label>
        <label class="field"><span>Short name</span><input bind:value={editing.short_name} placeholder="e.g. OMEGA" /></label>
        <label class="field"><span>Federation</span><input bind:value={editing.federation} placeholder="e.g. Orienteering Vlaanderen" /></label>
        <label class="field"><span>Website</span><input type="url" bind:value={editing.website} /></label>
        <label class="field wide"><span>Notes</span><textarea bind:value={editing.notes} rows="2"></textarea></label>
      </div>
      <div class="row end">
        <button type="button" onclick={() => (editing = null)}>Cancel</button>
        <button class="primary" type="submit">Save</button>
      </div>
    </form>
  {/if}

  {#if !clubs.list.length}
    <p class="empty">No clubs yet. Clubs are also created when you import maps that name one.</p>
  {:else}
    <div class="card table-wrap">
      <table>
        <thead><tr><th>Name</th><th>Short</th><th>Federation</th><th class="num">Maps</th><th></th></tr></thead>
        <tbody>
          {#each clubs.list as c (c.id)}
            <tr>
              <td>{#if c.website}<a href={c.website} target="_blank" rel="noopener">{c.name}</a>{:else}{c.name}{/if}</td>
              <td>{c.short_name ?? ''}</td>
              <td>{c.federation ?? ''}</td>
              <td class="num"><a href="#/" onclick={() => { try { localStorage.setItem('omaps.library', JSON.stringify({ ...JSON.parse(localStorage.getItem('omaps.library') || '{}'), club: c.name })) } catch { /* ignore */ } }}>{c.map_count}</a></td>
              <td class="acts">
                <button class="small ghost" onclick={() => (editing = { ...c })}>Edit</button>
                <button class="small ghost danger" onclick={() => remove(c)}>Delete</button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</main>

<style>
  .head { margin-bottom: 1rem; }
  .head h1 { margin: 0; }
  .edit { margin-bottom: 1rem; }
  .end { justify-content: flex-end; margin-top: .75rem; }
  .table-wrap { padding: 0; overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; font-size: .8rem; color: var(--muted); font-weight: 600; padding: .6rem; border-bottom: 1px solid var(--border); }
  td { padding: .5rem .6rem; border-bottom: 1px solid var(--border); }
  tr:last-child td { border-bottom: 0; }
  .num { text-align: right; }
  .acts { text-align: right; white-space: nowrap; }
</style>
