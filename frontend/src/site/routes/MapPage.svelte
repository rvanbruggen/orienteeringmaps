<script>
  import { store, mapHref, km, removalUrl } from '../data.svelte.js'
  import { fmtBytes, fmtContour, fmtDate, fmtKm, fmtScale, label } from '../../lib/format.js'
  import OverlayMap from '../../components/OverlayMap.svelte'
  import Lightbox from '../../components/Lightbox.svelte'
  import LocationMap from '../LocationMap.svelte'

  let { slug } = $props()
  // Slugs start with the map id, so old links keep working after a rename.
  const map = $derived(store.maps.find((m) => m.slug === slug) ?? store.maps.find((m) => String(m.id) === slug.split('-')[0]))
  let lb = $state({ open: false, pages: [], index: 0, title: '' })

  $effect(() => {
    if (map) document.title = `${map.name} – ${store.site.title}`
  })

  const asPages = (pages) => pages.map((p) => ({ ...p, image_url: p.img, page_no: p.no }))

  const versionTitle = (v) => v.label ? `${v.label}${v.survey ? ` · survey ${fmtDate(v.survey)}` : ''}` : v.survey ? `Survey ${fmtDate(v.survey)}` : 'Map version'

  // Every placed page (level "full"), or the main image when it is placed.
  const overlays = $derived.by(() => {
    if (!map) return []
    const out = []
    for (const v of map.versions) for (const f of v.files ?? []) for (const p of f.pages ?? []) {
      if (p.place) out.push({ key: `${f.key}-${p.no}`, image_url: p.img, width: p.w, height: p.h, corners: p.place.corners, clip: p.place.clip,
        label: `${versionTitle(v)} · ${f.name}${(f.pages?.length ?? 0) > 1 ? ` · p${p.no}` : ''}` })
    }
    if (!out.length && map.hero?.place) {
      const h = map.hero
      out.push({ key: 'hero', image_url: h.img, width: h.w, height: h.h, corners: h.place.corners, clip: h.place.clip, label: map.name })
    }
    return out
  })

  const fileByKey = $derived(new Map((map?.files ?? []).map((f) => [f.key, f])))

  function viewHero() {
    const f = map.files.find((f) => f.pages?.some((p) => p.img === map.hero.img))
    if (f) viewFile(f, f.pages.findIndex((p) => p.img === map.hero.img))
    else lb = { open: true, pages: asPages([map.hero]), index: 0, title: map.name }
  }
  function viewFile(f, index = 0) {
    lb = { open: true, pages: asPages(f.pages), index: Math.max(0, index), title: f.name }
  }
  function courseThumb(c) {
    const f = c.file && fileByKey.get(c.file)
    const p = f?.pages?.find((p) => p.no === c.page) ?? f?.pages?.[0]
    return p ? { f, p } : null
  }

  const credit = $derived(map ? ['©', map.club ?? 'the map’s owner', map.cartographer && `· drawn by ${map.cartographer}`].filter(Boolean).join(' ') : '')

  const nearby = $derived.by(() => {
    if (!map?.centre) return []
    return store.maps.filter((m) => m.id !== map.id && m.centre)
      .map((m) => ({ m, d: km(map.centre, m.centre) })).filter((x) => x.d <= 5).sort((a, b) => a.d - b.d).slice(0, 8)
  })
</script>

{#if !map}
  <main class="page"><p class="empty">This map isn’t on the site (any more). <a href="./">See all maps</a></p></main>
{:else}
  <main class="page">
    <a href="./" class="back">← All maps</a>

    <section class="top">
      {#if map.hero}
        <button class="hero" onclick={viewHero} aria-label="View the map image">
          <img src={map.hero.thumb} alt="Map {map.name}" />
          <span class="zoom">View map</span>
        </button>
      {/if}
      <div class="summary">
        <h1>{map.name}</h1>
        <dl class="facts">
          {#if map.location}<div><dt>Near</dt><dd>{map.location}</dd></div>{/if}
          {#if map.club}<div><dt>Club</dt><dd>{#if map.club_url}<a href={map.club_url} target="_blank" rel="noopener">{map.club}</a>{:else}{map.club}{/if}</dd></div>{/if}
          {#if map.type}<div><dt>Type</dt><dd>{label(map.type)}</dd></div>{/if}
          {#if map.scale}<div><dt>Scale</dt><dd>{fmtScale(map.scale)}</dd></div>{/if}
          {#if map.contours}<div><dt>Contours</dt><dd>{fmtContour(map.contours)}</dd></div>{/if}
          {#if map.survey}<div><dt>Last survey</dt><dd>{fmtDate(map.survey)}</dd></div>{/if}
          {#if map.cartographer}<div><dt>Cartographer</dt><dd>{map.cartographer}</dd></div>{/if}
          {#if map.last_event}<div><dt>Last event</dt><dd>{fmtDate(map.last_event)}</dd></div>{/if}
        </dl>
        {#if map.tags.length}<div class="row">{#each map.tags as t}<span class="chip accent">{t}</span>{/each}</div>{/if}
        {#if map.note}<p class="note">{map.note}</p>{/if}
        <p class="muted small credit">
          {credit}
          {#if removalUrl(map)}· <a href={removalUrl(map)} target="_blank" rel="noopener" title="Own this map and want it taken off this site? Open a request on GitHub.">Request removal</a>{/if}
        </p>
      </div>
    </section>

    {#if overlays.length}
      <section>
        <h2>On the aerial photo</h2>
        <OverlayMap {overlays} adjustable={false} />
      </section>
    {:else if map.centre}
      <section>
        <h2>Location</h2>
        <LocationMap footprint={map.footprint} lat={map.lat} lon={map.lon} />
      </section>
    {/if}

    {#each map.versions as v}
      <section class="card version">
        <h2>{versionTitle(v)}</h2>
        <div class="muted small">{[v.cartographer && `drawn by ${v.cartographer}`, fmtScale(v.scale), v.contours && `contours ${fmtContour(v.contours)}`, v.standard].filter(Boolean).join(' · ')}</div>

        {#each v.events ?? [] as e}
          <div class="event">
            <div class="row">
              <strong>{e.name}</strong>
              {#if e.date}<span class="muted">{fmtDate(e.date)}{e.end_date ? ` – ${fmtDate(e.end_date)}` : ''}</span>{/if}
              {#if e.type}<span class="chip">{label(e.type)}</span>{/if}
              {#if e.discipline}<span class="chip">{label(e.discipline)}</span>{/if}
              {#if e.organiser}<span class="muted small">by {e.organiser}</span>{/if}
              {#if e.results_url}<a href={e.results_url} target="_blank" rel="noopener" class="small">Results ↗</a>{/if}
            </div>
            {#if e.courses?.length}
              <div class="courses">
                {#each e.courses as c}
                  {@const t = courseThumb(c)}
                  {#if t}
                    <button class="course" onclick={() => viewFile(t.f, t.f.pages.indexOf(t.p))}>
                      <img src={t.p.thumb} alt="" loading="lazy" />
                      <span><strong>{c.name}</strong><small>{[fmtKm(c.length_km), c.climb_m && `${c.climb_m} m climb`, c.controls && `${c.controls} controls`].filter(Boolean).join(' · ')}</small></span>
                    </button>
                  {:else}
                    <span class="chip course">{c.name}{c.length_km ? ` · ${fmtKm(c.length_km)}` : ''}</span>
                  {/if}
                {/each}
              </div>
            {/if}
          </div>
        {/each}

        {#if v.files?.length}
          <ul class="files">
            {#each v.files as f}
              <li class="row">
                {#if f.pages?.length}<button class="ghost small" onclick={() => viewFile(f)}>View{f.pages.length > 1 ? ` ${f.pages.length} pages` : ''}</button>{/if}
                <span>{f.name}</span>
                <span class="muted small">{label(f.kind)} · {fmtBytes(f.size)}</span>
                {#if f.url}<a class="btn small" href={f.url} download>Download {f.format?.toUpperCase()}</a>{/if}
              </li>
            {/each}
          </ul>
        {/if}
      </section>
    {/each}

    {#if nearby.length}
      <section>
        <h2>Nearby maps</h2>
        <ul class="nearby">
          {#each nearby as { m, d }}
            <li><a href={mapHref(m)}>{m.name}</a> <span class="muted small">{d < 1 ? `${Math.round(d * 1000)} m` : `${d.toFixed(1)} km`}</span></li>
          {/each}
        </ul>
      </section>
    {/if}
  </main>
  <Lightbox bind:open={lb.open} bind:index={lb.index} pages={lb.pages} title={lb.title} />
{/if}

<style>
  section { margin-bottom: 1.5rem; }
  .top { display: grid; grid-template-columns: 260px 1fr; gap: 1.5rem; align-items: start; }
  .top:not(:has(.hero)) { grid-template-columns: 1fr; }
  .hero { padding: 0; border-radius: var(--radius); overflow: hidden; position: relative; background: var(--surface-2); display: block; }
  .hero img { width: 100%; aspect-ratio: 3 / 4; object-fit: cover; object-position: top; }
  .hero .zoom { position: absolute; bottom: .5rem; right: .5rem; background: rgb(0 0 0 / 65%); color: #fff; padding: .2rem .55rem; border-radius: 6px; font-size: .85rem; }
  .note { white-space: pre-line; }
  .credit { margin-top: .5rem; }
  .small { font-size: .85rem; }
  .version { margin-bottom: 1rem; }
  .event { border-top: 1px solid var(--border); padding-top: .6rem; margin-top: .6rem; }
  .courses { display: flex; flex-wrap: wrap; gap: .5rem; margin-top: .5rem; }
  .course { padding: .3rem; gap: .5rem; text-align: left; white-space: normal; }
  .course img { width: 54px; height: 54px; object-fit: cover; border-radius: 4px; border: 1px solid var(--border); }
  .course span { display: flex; flex-direction: column; }
  .course small { color: var(--muted); }
  .files { list-style: none; padding: 0; margin: .75rem 0 0; display: flex; flex-direction: column; gap: .35rem; border-top: 1px solid var(--border); padding-top: .6rem; }
  .files span:first-of-type { overflow-wrap: anywhere; }
  .nearby { columns: 2 240px; padding-left: 1.1rem; }
  @media (max-width: 700px) {
    .top { grid-template-columns: 1fr; }
    .hero img { aspect-ratio: 4 / 3; }
  }
</style>
