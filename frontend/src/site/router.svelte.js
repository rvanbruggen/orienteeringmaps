// Path router for the public site. Every page exists as a real file
// (map/<slug>/index.html), so links work on reload and for search engines;
// inside the app, navigation just swaps the view.

export const basePath = new URL(document.baseURI).pathname

function parse() {
  let p = location.pathname
  if (p.startsWith(basePath)) p = p.slice(basePath.length)
  p = p.replace(/index\.html$/, '')
  return { path: '/' + p, query: new URLSearchParams(location.search) }
}

export const route = $state(parse())

function update() {
  Object.assign(route, parse())
}

window.addEventListener('popstate', update)

/** Navigate to a site path like 'map/12-park/' or '/events/'. */
export function go(path, { replace = false } = {}) {
  const url = basePath + path.replace(/^\.?\//, '')
  history[replace ? 'replaceState' : 'pushState']({}, '', url)
  update()
  if (!replace) window.scrollTo(0, 0)
}

// Same-site links navigate without reloading.
document.addEventListener('click', (e) => {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
  const a = e.target.closest?.('a[href]')
  if (!a || a.target || a.hasAttribute('download')) return
  const url = new URL(a.href, document.baseURI)
  if (url.origin !== location.origin || !url.pathname.startsWith(basePath)) return
  if (/\.(json|xml|txt|pdf|png|jpe?g|webp|tiff?|heic|kmz)$/i.test(url.pathname)) return
  e.preventDefault()
  go(url.pathname.slice(basePath.length) + url.search)
})
