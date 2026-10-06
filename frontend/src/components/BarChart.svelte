<script>
  // Single-series bar chart (no legend needed: the title names the series).
  // horizontal: ranked categories with the value at the bar end.
  // vertical: a time axis (e.g. years) with hairline gridlines and hover values.
  // Every chart can flip to a plain table.
  let { data = [], orientation = 'horizontal', title, unit = '', format = (v) => String(v), onselect = null } = $props()

  let showTable = $state(false)
  let hover = $state(null) // {i, x, y}
  let box = $state()

  const max = $derived(Math.max(1, ...data.map((d) => d.value)))
  const niceMax = $derived.by(() => {
    const p = 10 ** Math.floor(Math.log10(max))
    return [1, 2, 4, 5, 10].map((k) => k * p).find((v) => v >= max) ?? max
  })
  // Counts are whole numbers: only show a middle gridline when it lands on one.
  const ticks = $derived(Number.isInteger(niceMax / 2) ? [0, niceMax / 2, niceMax] : [0, niceMax])
  const labelEvery = $derived(Math.max(1, Math.ceil(data.length / 12)))

  function move(e, i) {
    const r = box.getBoundingClientRect()
    hover = { i, x: e.clientX - r.left, y: e.clientY - r.top }
  }
</script>

<figure class="chart">
  <figcaption class="row">
    <span class="title">{title}</span>
    <span class="spacer"></span>
    <button class="small ghost" onclick={() => (showTable = !showTable)} aria-pressed={showTable}>{showTable ? 'Chart' : 'Table'}</button>
  </figcaption>

  {#if !data.length}
    <p class="empty-chart">No data yet.</p>
  {:else if showTable}
    <table class="tbl">
      <tbody>
        {#each data as d}<tr><td>{d.label}</td><td class="num">{format(d.value)}{unit}</td></tr>{/each}
      </tbody>
    </table>
  {:else if orientation === 'horizontal'}
    <div class="hbars" bind:this={box} role="list">
      {#each data as d, i}
        <div class="hrow" role="listitem" class:clickable={!!onselect}
          onmousemove={(e) => move(e, i)} onmouseleave={() => (hover = null)}
          onclick={() => onselect?.(d)} onkeydown={(e) => e.key === 'Enter' && onselect?.(d)} tabindex={onselect ? 0 : -1}>
          <span class="hlabel" title={d.label}>{d.label}</span>
          <span class="htrack">
            <span class="hbar" style="width: {(d.value / max) * 100}%"></span>
            <span class="hval num">{format(d.value)}{unit}</span>
          </span>
        </div>
      {/each}
      {#if hover}
        {@const d = data[hover.i]}
        <div class="tip" style="left: {hover.x}px; top: {hover.y}px">
          <strong>{d.label}</strong><br />{format(d.value)}{unit}{d.note ? ` · ${d.note}` : ''}
        </div>
      {/if}
    </div>
  {:else}
    <div class="vchart" bind:this={box}>
      <div class="grid">
        {#each ticks.slice().reverse() as t}<div class="gl"><span class="num">{format(t)}</span></div>{/each}
      </div>
      <div class="cols" role="list">
        {#each data as d, i}
          <div class="col" role="listitem" aria-label="{d.label}: {format(d.value)}{unit}"
            onmousemove={(e) => move(e, i)} onmouseleave={() => (hover = null)}>
            <span class="vbar" class:on={hover?.i === i} style="height: {(d.value / niceMax) * 100}%"></span>
          </div>
        {/each}
      </div>
      <div class="xlabels">
        {#each data as d, i}<span class="num">{i % labelEvery === 0 ? d.label : ''}</span>{/each}
      </div>
      {#if hover}
        {@const d = data[hover.i]}
        <div class="tip" style="left: {hover.x}px; top: {hover.y}px">
          <strong>{d.label}</strong><br />{format(d.value)}{unit}{d.note ? ` · ${d.note}` : ''}
        </div>
      {/if}
    </div>
  {/if}
</figure>

<style>
  .chart {
    --series: #2a78d6;
    --grid: #e6e4df;
    margin: 0; display: flex; flex-direction: column; gap: .6rem; min-width: 0;
  }
  @media (prefers-color-scheme: dark) {
    .chart { --series: #3987e5; --grid: #33332f; }
  }
  .title { font-weight: 600; font-size: .95rem; }
  .empty-chart { color: var(--muted); font-size: .9rem; margin: 0; }

  .hbars { position: relative; display: flex; flex-direction: column; gap: 2px; }
  .hrow { display: grid; grid-template-columns: minmax(80px, 38%) 1fr; align-items: center; gap: .6rem; padding: 3px 0; border-radius: 4px; }
  .hrow:hover { background: var(--surface-2); }
  .hrow.clickable { cursor: pointer; }
  .hlabel { font-size: .85rem; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .htrack { display: flex; align-items: center; gap: .4rem; min-width: 0; }
  .hbar { height: 16px; min-width: 2px; background: var(--series); border-radius: 0 4px 4px 0; }
  .hval { font-size: .8rem; color: var(--muted); white-space: nowrap; }

  .vchart { position: relative; display: grid; grid-template-rows: 150px auto; padding-left: 2rem; }
  .grid { grid-row: 1; grid-column: 1; display: flex; flex-direction: column; justify-content: space-between; pointer-events: none; }
  .gl { border-top: 1px solid var(--grid); height: 0; position: relative; }
  .gl span { position: absolute; right: calc(100% + .35rem); top: -.55rem; font-size: .72rem; color: var(--muted); }
  .cols { grid-row: 1; grid-column: 1; display: flex; align-items: flex-end; gap: 2px; border-bottom: 1px solid var(--muted); }
  .col { flex: 1; height: 100%; display: flex; align-items: flex-end; justify-content: center; }
  .vbar { width: min(24px, 80%); background: var(--series); border-radius: 4px 4px 0 0; min-height: 0; }
  .vbar.on { filter: brightness(1.15); }
  .xlabels { display: flex; gap: 2px; margin-top: .3rem; }
  .xlabels span { flex: 1; text-align: center; font-size: .72rem; color: var(--muted); white-space: nowrap; overflow: visible; }

  .tip {
    position: absolute; transform: translate(12px, -110%); pointer-events: none; z-index: 5;
    background: var(--surface); border: 1px solid var(--border); box-shadow: var(--shadow);
    border-radius: 6px; padding: .3rem .5rem; font-size: .8rem; white-space: nowrap; color: var(--text);
  }
  .tbl { width: 100%; border-collapse: collapse; font-size: .85rem; }
  .tbl td { padding: .2rem .3rem; border-bottom: 1px solid var(--border); }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
</style>
