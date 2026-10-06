// Loads the published data (data/site-<hash>.json) and shapes it for the views.

export const store = $state({ site: null, maps: [], error: '' })

const norm = (s) => String(s ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
export const normalize = norm

function centre(m) {
  if (m.footprint) {
    const n = m.footprint.length
    return [m.footprint.reduce((a, p) => a + p[0], 0) / n, m.footprint.reduce((a, p) => a + p[1], 0) / n]
  }
  return m.lat != null ? [m.lat, m.lon] : null
}

function shape(m) {
  const events = m.versions.flatMap((v) => (v.events ?? []).map((e) => ({ ...e, version: v })))
  const files = [...m.versions.flatMap((v) => v.files ?? []), ...(m.extra_files ?? [])]
  const hero = m.hero
  return {
    ...m,
    tags: m.tags ?? [],
    events,
    files,
    centre: centre(m),
    // The shape the shared ExplorerMap component expects.
    thumb_url: m.thumb ?? null,
    club_name: m.club ?? null,
    last_survey: m.survey ?? null,
    overlay: hero?.place ? { image_url: hero.img, width: hero.w, height: hero.h, corners: hero.place.corners, clip: hero.place.clip } : null,
    search: norm([
      m.name, m.location, m.club, m.cartographer, m.type, ...(m.tags ?? []),
      ...events.flatMap((e) => [e.name, e.organiser, ...(e.courses ?? []).map((c) => c.name)]),
    ].filter(Boolean).join(' ')),
  }
}

export async function load() {
  const url = document.querySelector('meta[name="omaps-data"]')?.content
  if (!url) { store.error = 'No data file found.'; return }
  try {
    const res = await fetch(url)
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    const data = await res.json()
    store.site = data.site
    store.maps = data.maps.map(shape)
  } catch (e) {
    store.error = `Could not load the maps (${e.message}).`
  }
}

/** Does a map match a free-text query? Every word must appear somewhere. */
export function matches(m, q) {
  const words = norm(q).split(/\s+/).filter(Boolean)
  return words.every((w) => m.search.includes(w))
}

export const mapHref = (m) => `map/${m.slug}/`

export function km([a, b], [c, d]) {
  const r = Math.PI / 180, x = (d - b) * r * Math.cos(((a + c) / 2) * r), y = (c - a) * r
  return Math.sqrt(x * x + y * y) * 6371
}
