<script>
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { notify } from '../lib/stores.svelte.js'
  import FileTriage from '../components/FileTriage.svelte'

  let items = $state([]), loading = $state(true)

  onMount(async () => {
    try {
      const files = await api.get('/api/files?unassigned=true')
      // Fetch similarity/candidates per file (cheap; the inbox is small).
      items = await Promise.all(files.map((f) => api.get(`/api/files/${f.id}`)))
    } catch (e) { notify(e.message, 'error') }
    loading = false
  })
  const drop = (f) => (items = items.filter((i) => i.file.id !== f.id))
  // A split file is replaced by its parts, in place.
  async function replace(f, files) {
    const parts = await Promise.all(files.map((x) => api.get(`/api/files/${x.id}`)))
    const at = items.findIndex((i) => i.file.id === f.id)
    items = [...items.slice(0, at), ...parts, ...items.slice(at + 1)]
  }
</script>

<main class="page">
  <h1>Inbox</h1>
  <p class="muted">Files that are not attached to a map yet.</p>
  {#if loading}
    <p class="empty">Loading…</p>
  {:else if !items.length}
    <div class="empty card">Nothing waiting. <a href="#/upload">Add maps</a></div>
  {:else}
    <div class="list">
      {#each items as item (item.file.id)}
        <FileTriage {item} onfiled={drop} ondeleted={drop} onsplit={replace} />
      {/each}
    </div>
  {/if}
</main>

<style>
  .list { display: flex; flex-direction: column; gap: .75rem; }
</style>
