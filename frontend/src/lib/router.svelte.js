// Minimal hash router: #/path?query

function parse() {
  const raw = location.hash.slice(1) || '/'
  const [path, q] = raw.split('?')
  return { path, query: new URLSearchParams(q || '') }
}

export const route = $state(parse())

window.addEventListener('hashchange', () => {
  Object.assign(route, parse())
  window.scrollTo(0, 0)
})

export function go(path) {
  location.hash = path
}
