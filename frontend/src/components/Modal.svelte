<script>
  // Accessible modal dialog built on <dialog>. Closes on Escape and backdrop click.
  let { title, open = $bindable(false), wide = false, children, footer } = $props()
  let dlg

  $effect(() => {
    if (!dlg) return
    if (open && !dlg.open) dlg.showModal()
    if (!open && dlg.open) dlg.close()
  })
</script>

<dialog bind:this={dlg} class:wide onclose={() => (open = false)}
  onclick={(e) => e.target === dlg && (open = false)}>
  <div class="inner">
    <header class="row">
      <h2>{title}</h2>
      <span class="spacer"></span>
      <button class="ghost" aria-label="Close" onclick={() => (open = false)}>✕</button>
    </header>
    <div class="content">{@render children?.()}</div>
    {#if footer}<footer class="row">{@render footer()}</footer>{/if}
  </div>
</dialog>

<style>
  dialog {
    border: 1px solid var(--border); border-radius: 10px; padding: 0;
    background: var(--surface); color: var(--text); box-shadow: var(--shadow);
    width: min(640px, calc(100vw - 2rem)); max-height: calc(100vh - 2rem);
  }
  dialog.wide { width: min(980px, calc(100vw - 2rem)); }
  dialog::backdrop { background: rgb(0 0 0 / 45%); }
  .inner { display: flex; flex-direction: column; max-height: calc(100vh - 2rem); }
  header { padding: .8rem 1rem; border-bottom: 1px solid var(--border); }
  header h2 { margin: 0; }
  .content { padding: 1rem; overflow-y: auto; }
  footer { padding: .75rem 1rem; border-top: 1px solid var(--border); justify-content: flex-end; }
</style>
