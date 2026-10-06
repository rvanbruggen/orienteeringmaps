<script>
  import { onMount } from 'svelte'
  import { route } from './router.svelte.js'
  import { store, load } from './data.svelte.js'
  import Home from './routes/Home.svelte'
  import MapPage from './routes/MapPage.svelte'
  import Events from './routes/Events.svelte'
  import About from './routes/About.svelte'

  onMount(load)

  const mapMatch = $derived(route.path.match(/^\/map\/([^/]+)\/?$/))
  const page = $derived(mapMatch ? 'map' : route.path.replace(/\/$/, '') === '/events' ? 'events'
    : route.path.replace(/\/$/, '') === '/about' ? 'about' : route.path === '/' ? 'home' : 'missing')
  const title = $derived(store.site?.title ?? 'Orienteering maps')

  $effect(() => {
    if (page === 'home') document.title = title
    else if (page === 'events') document.title = `Events – ${title}`
    else if (page === 'about') document.title = `About – ${title}`
    else if (page === 'missing') document.title = `Not found – ${title}`
  })
</script>

<header class="top">
  <a class="brand" href="./">
    <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true">
      <rect x="2" y="2" width="28" height="28" rx="3" fill="#fff" stroke="currentColor" stroke-width="1.5" />
      <path d="M3 3 L29 29 L29 3 Z" fill="#f26a1b" />
    </svg>
    <span>{title}</span>
  </a>
  <nav>
    <a href="./" class:active={page === 'home' || page === 'map'}>Maps</a>
    <a href="events/" class:active={page === 'events'}>Events</a>
    <a href="about/" class:active={page === 'about'}>About</a>
  </nav>
</header>

{#if store.error}
  <main class="page"><p class="empty">{store.error}</p></main>
{:else if !store.site}
  <main class="page"><p class="empty">Loading maps…</p></main>
{:else if page === 'map'}
  {#key mapMatch[1]}<MapPage slug={mapMatch[1]} />{/key}
{:else if page === 'events'}
  <Events />
{:else if page === 'about'}
  <About />
{:else if page === 'home'}
  <Home />
{:else}
  <main class="page"><p class="empty">This page doesn’t exist. <a href="./">See all maps</a></p></main>
{/if}

<footer>
  <span>Map images © their clubs and cartographers</span>
  <a href="about/">About &amp; copyright</a>
  {#if store.site?.generated}<span>Updated {new Date(store.site.generated).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}</span>{/if}
</footer>

<style>
  .top {
    position: sticky; top: 0; z-index: 1500;
    display: flex; align-items: center; gap: 1rem; flex-wrap: wrap;
    padding: .55rem 1rem;
    background: color-mix(in srgb, var(--surface) 92%, transparent);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--border);
  }
  .brand { display: flex; align-items: center; gap: .55rem; font-weight: 700; color: var(--text); font-size: 1.05rem; min-width: 0; }
  .brand span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .brand:hover { text-decoration: none; }
  nav { display: flex; gap: .25rem; margin-left: auto; }
  nav a { color: var(--muted); padding: .35rem .65rem; border-radius: 6px; font-weight: 500; }
  nav a:hover { background: var(--surface-2); text-decoration: none; color: var(--text); }
  nav a.active { color: var(--text); background: var(--surface-2); }
  footer { display: flex; gap: 1rem; justify-content: center; flex-wrap: wrap; padding: 1.5rem 1rem; font-size: .82rem; color: var(--muted); }
  @media (max-width: 640px) {
    .top { gap: .4rem; }
    nav { margin-left: 0; width: 100%; }
  }
</style>
