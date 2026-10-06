<script>
  import { store } from '../data.svelte.js'

  const site = $derived(store.site)
  const paragraphs = $derived((site.about ?? '').split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean))
  const contactHref = $derived(site.contact?.includes('@') && !site.contact.includes('://') ? `mailto:${site.contact}` : site.contact)
  const counts = $derived({
    maps: store.maps.length,
    placed: store.maps.filter((m) => m.footprint).length,
    events: store.maps.reduce((a, m) => a + m.events.length, 0),
  })
</script>

<main class="page narrow">
  <h1>About</h1>
  {#each paragraphs as p}<p class="para">{p}</p>{/each}
  {#if site.author}<p>This collection is kept by {site.author}.</p>{/if}
  <p class="muted">{counts.maps} maps, {counts.placed} of them placed on aerial photos, with {counts.events} events.</p>

  <h2>Copyright</h2>
  <p>Orienteering maps are made by clubs and their cartographers, who own the copyright. They are shown here for reference and so that fellow orienteers can find them. Please don’t use them to organise events or print them for sale without asking the club.</p>
  {#if site.contact}
    <p>Are you the owner of a map and would you rather not see it here, or did something go wrong? Contact <a href={contactHref}>{site.contact}</a> and it will be removed or fixed.</p>
  {/if}

  <h2>Base maps</h2>
  <p class="muted">Aerial photos and the GRB base map © Digitaal Vlaanderen. Satellite imagery © Esri, Maxar, Earthstar Geographics. Map data © OpenStreetMap contributors.</p>
</main>

<style>
  .narrow { max-width: 760px; }
  .para { white-space: pre-line; }
  h2 { margin-top: 1.5rem; }
</style>
