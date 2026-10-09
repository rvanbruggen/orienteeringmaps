<script>
  import { onMount } from 'svelte'
  import { route } from './lib/router.svelte.js'
  import { meta, refreshMeta, refreshClubs, toast } from './lib/stores.svelte.js'
  import Library from './routes/Library.svelte'
  import MapDetail from './routes/MapDetail.svelte'
  import Upload from './routes/Upload.svelte'
  import Inbox from './routes/Inbox.svelte'
  import Clubs from './routes/Clubs.svelte'
  import Georef from './routes/Georef.svelte'
  import Events from './routes/Events.svelte'
  import Insights from './routes/Insights.svelte'
  import Publish from './routes/Publish.svelte'
  import Runs from './routes/Runs.svelte'
  import Races from './routes/Races.svelte'
  import Imports from './routes/Imports.svelte'
  import ImportTask from './routes/ImportTask.svelte'

  onMount(() => {
    refreshMeta()
    refreshClubs()
  })

  const mapMatch = $derived(route.path.match(/^\/map\/(\d+)$/))
  const placeMatch = $derived(route.path.match(/^\/place\/(\d+)$/))
  const importMatch = $derived(route.path.match(/^\/imports\/(\d+)$/))
  const active = (p) => (p === '/' ? route.path === '/' || mapMatch : route.path.startsWith(p))
</script>

<header class="top">
  <a class="brand" href="#/">
    <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true">
      <rect x="2" y="2" width="28" height="28" rx="3" fill="#fff" stroke="currentColor" stroke-width="1.5" />
      <path d="M3 3 L29 29 L29 3 Z" fill="#f26a1b" />
    </svg>
    <span>Orienteering Maps</span>
  </a>
  <nav>
    <a href="#/" class:active={active('/')}>Library <span class="count">{meta.counts.maps ?? ''}</span></a>
    <a href="#/inbox" class:active={active('/inbox')}>
      Inbox {#if meta.counts.inbox}<span class="count badge">{meta.counts.inbox}</span>{/if}
    </a>
    <a href="#/events" class:active={active('/events')}>Events</a>
    <a href="#/runs" class:active={active('/runs')}>Runs</a>
    <a href="#/races" class:active={active('/races')}>Races</a>
    <a href="#/imports" class:active={active('/imports')}>
      Imports {#if meta.counts.imports}<span class="count badge" title="Imported scans to review">{meta.counts.imports}</span>{/if}
    </a>
    <a href="#/insights" class:active={active('/insights')}>Insights</a>
    <a href="#/clubs" class:active={active('/clubs')}>Clubs</a>
    <a href="#/publish" class:active={active('/publish')}>Publish</a>
    <a href="#/upload" class="upload" class:active={active('/upload')}>+ Add maps</a>
  </nav>
</header>

{#if placeMatch}
  {#key placeMatch[1]}<Georef pageId={+placeMatch[1]} />{/key}
{:else if mapMatch}
  {#key mapMatch[1]}<MapDetail id={+mapMatch[1]} />{/key}
{:else if importMatch}
  {#key importMatch[1]}<ImportTask id={+importMatch[1]} />{/key}
{:else if route.path === '/imports'}
  <Imports />
{:else if route.path === '/upload'}
  <Upload />
{:else if route.path === '/inbox'}
  <Inbox />
{:else if route.path === '/events'}
  <Events />
{:else if route.path === '/runs'}
  <Runs />
{:else if route.path === '/races'}
  <Races />
{:else if route.path === '/insights'}
  <Insights />
{:else if route.path === '/clubs'}
  <Clubs />
{:else if route.path === '/publish'}
  <Publish />
{:else}
  <Library />
{/if}

<footer>
  <span>v{meta.version}</span>
  <a href="/api/export" download>Export everything (.zip)</a>
  <a href="/api/export/kmz" download title="All placed maps for Google Earth">Google Earth (.kmz)</a>
  <a href="/api/export/geojson" download title="Map outlines for QGIS, uMap, …">GeoJSON</a>
</footer>

{#if toast.message}
  <div class="toast {toast.kind}" role="status">{toast.message}</div>
{/if}

<style>
  .top {
    position: sticky; top: 0; z-index: 20;
    display: flex; align-items: center; gap: 1rem; flex-wrap: wrap;
    padding: .55rem 1rem;
    background: color-mix(in srgb, var(--surface) 92%, transparent);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--border);
  }
  .brand { display: flex; align-items: center; gap: .55rem; font-weight: 700; color: var(--text); font-size: 1.05rem; }
  .brand:hover { text-decoration: none; }
  nav { display: flex; gap: .25rem; margin-left: auto; flex-wrap: wrap; }
  nav a { color: var(--muted); padding: .35rem .65rem; border-radius: 6px; font-weight: 500; }
  nav a:hover { background: var(--surface-2); text-decoration: none; color: var(--text); }
  nav a.active { color: var(--text); background: var(--surface-2); }
  nav a.upload { color: #fff; background: var(--accent); }
  nav a.upload:hover { filter: brightness(1.06); }
  .count { font-size: .78rem; color: var(--muted); font-variant-numeric: tabular-nums; }
  .badge { background: var(--accent); color: #fff; border-radius: 999px; padding: 0 .4rem; }
  footer { display: flex; gap: 1rem; justify-content: center; flex-wrap: wrap; padding: 1.5rem; font-size: .82rem; color: var(--muted); }
  .toast {
    position: fixed; bottom: 1rem; left: 50%; transform: translateX(-50%); z-index: 100;
    background: var(--text); color: var(--bg); padding: .6rem 1rem; border-radius: 8px; box-shadow: var(--shadow);
    max-width: min(90vw, 560px);
  }
  .toast.error { background: var(--danger); color: #fff; }
  @media (max-width: 640px) {
    nav { margin-left: 0; width: 100%; }
  }
</style>
