<script>
  let { tags = $bindable(), id, suggestions = [] } = $props()
  const list = $derived(tags ?? [])
  let draft = $state('')

  function add(t) {
    t = t.trim()
    if (t && !list.includes(t)) tags = [...list, t]
    draft = ''
  }
  function onkeydown(e) {
    if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); add(draft) }
    else if (e.key === 'Backspace' && !draft && list.length) tags = list.slice(0, -1)
  }
</script>

<div class="tags">
  {#each list as t}
    <span class="chip accent">{t}<button type="button" class="x" aria-label="Remove {t}" onclick={() => (tags = list.filter((x) => x !== t))}>×</button></span>
  {/each}
  <input {id} list="{id}-list" bind:value={draft} {onkeydown} onblur={() => draft && add(draft)} placeholder={list.length ? '' : 'Add tag…'} />
  <datalist id="{id}-list">{#each suggestions as s}<option value={s}></option>{/each}</datalist>
</div>

<style>
  .tags { display: flex; flex-wrap: wrap; gap: .25rem; align-items: center; border: 1px solid var(--border); border-radius: 6px; padding: .25rem .35rem; background: var(--surface); }
  .tags input { border: 0; flex: 1 1 80px; padding: .15rem .2rem; outline: none; }
  .x { border: 0; background: none; padding: 0 0 0 .15rem; color: inherit; line-height: 1; cursor: pointer; }
</style>
